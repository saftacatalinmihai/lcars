#!/usr/bin/env python3
"""Tests for Number One's inbox (engineer.py no1_send / no1-flush): a note is
a crew_inbox entry for number-one, typed exactly once, even when what started
the flusher ends, or the flusher is stopped, between typing it and ticking it
done; one sent while the journal is down is written when it is back.

The bug (0.152.1): the reap and a deploy are systemd units, and a flusher
they started died with their cgroup in submit_if_left's sleeps, after
typing; the next reap typed the same note again. A stub herdr on PATH logs
each prompt, a stand-in server (test_seat's Journal) holds the entries, and
the state directory is a temp one. Nothing outside it is touched, and no
session is typed into.

    python3 scripts/test_no1_inbox.py
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, "engineer.py")
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import test_seat  # noqa: E402 - for its stand-in server
shutil.rmtree(test_seat.TMP, ignore_errors=True)  # its own scratch, made on import
Journal = test_seat.Journal

# `agent read` shows an empty input box, so submit_if_left sleeps its 1.5s
# and returns: the window a stop used to fall into
HERDR = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["agent", "get"]:
    print(json.dumps({"result": {"agent": {"agent_status": "idle"}}}))
elif a[:2] == ["agent", "prompt"]:
    with open(%r, "a") as f:
        f.write(json.dumps(a[3]) + "\\n")
    print(json.dumps({"result": {}}))
elif a[:2] == ["agent", "read"]:
    print("────\\n\\n────")
else:
    print(json.dumps({"result": {}}))
"""


def user_systemd():
    try:
        return subprocess.run(["systemd-run", "--user", "--quiet", "--wait", "true"],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Inbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-inbox-test-")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "prompts")
        os.makedirs(self.state)
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "herdr"), "w") as f:
            f.write(HERDR % self.log)
        os.chmod(os.path.join(self.bin, "herdr"), 0o755)
        with open(os.path.join(self.state, "number-one.json"), "w") as f:
            json.dump({"name": "number-one"}, f)
        with open(os.path.join(self.tmp, "env"), "w") as f:
            f.write("LCARS_CREW_USER=crew\nLCARS_CREW_PASS=pass\n")
        self.j = Journal()
        self.env = dict(os.environ, LCARS_ENG_STATE=self.state, LCARS_ENG_ROOT=os.path.join(self.tmp, "eng"),
                        LCARS_URL=self.j.url, LCARS_CREW_ENV=os.path.join(self.tmp, "env"),
                        PATH=self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"))

    def tearDown(self):
        self.j.httpd.shutdown()
        shutil.rmtree(self.tmp)

    def queue(self, *texts):
        for t in texts:
            self.j.rows.append({"id": len(self.j.rows) + 1, "kind": "crew_inbox", "title": "number-one ← ship: " + t,
                                "content": t, "done_bool": 0, "deleted": 0})

    def inbox(self):
        return [r["content"] for r in self.j.kind("crew_inbox") if not r["done_bool"]]

    def prompts(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f]

    def flush(self):
        return subprocess.Popen([sys.executable, ENG, "no1-flush"], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_for(self, cond, secs=20):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return False

    def test_flush_delivers_in_order(self):
        self.queue("one", "two")
        p = self.flush()
        o, e = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, e)
        self.assertEqual(json.loads(o), {"ok": True, "sent": 2, "left": 0})
        self.assertEqual(self.prompts(), ["one", "two"])
        self.assertEqual(self.inbox(), [])

    def test_every_thread_s_notes_go_at_once_tagged(self):
        # threads are tags (no1-threads.md section 13), now rooms (rooms.md):
        # nothing is held, a note for a room other than main is typed under
        # its header line
        with open(os.path.join(self.state, "number-one.json"), "w") as f:
            json.dump({"name": "number-one", "session": "s2", "threads": [
                {"id": "main", "name": "Main"}, {"id": "deck", "name": "Deck"}]}, f)
        for title, text in (("crew#main", "for main"), ("ship", "anyone's"), ("crew#deck", "for deck"),
                            ("crew#gone", "a closed one's")):
            self.j.rows.append({"id": len(self.j.rows) + 1, "kind": "crew_inbox", "content": text,
                                "title": f"number-one ← {title}: {text}", "done_bool": 0, "deleted": 0})
        p = self.flush()
        o, e = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, e)
        self.assertEqual(json.loads(o), {"ok": True, "sent": 4, "left": 0})
        self.assertEqual(self.prompts(), ["for main", "anyone's", "room:: deck\nfor deck", "room:: gone\na closed one's"])
        self.assertEqual(self.inbox(), [])

    def test_a_note_s_thread_is_on_its_title(self):
        p = subprocess.run([sys.executable, ENG, "no1-send", "--thread", "deck", "[crew] x"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([r["title"] for r in self.j.kind("crew_inbox")], ["number-one ← crew#deck: [crew] x"])

    def test_twins_both_delivered(self):
        # the same text queued twice in one second is two notes, not one
        self.queue("same", "same")
        p = self.flush()
        p.communicate(timeout=30)
        self.assertEqual(self.prompts(), ["same", "same"])

    def test_stopped_after_typing_is_not_typed_again(self):
        self.queue("deploy failed", "next")
        p = self.flush()
        self.assertTrue(self.wait_for(lambda: self.prompts()), "never typed")
        p.send_signal(signal.SIGTERM)  # in submit_if_left's sleep
        p.communicate(timeout=30)
        self.assertEqual(self.inbox(), ["next"], "the typed note must be out, the next one kept")
        p = self.flush()
        p.communicate(timeout=30)
        self.assertEqual(self.prompts(), ["deploy failed", "next"])
        self.assertEqual(self.inbox(), [])

    @unittest.skipUnless(user_systemd(), "no user systemd here")
    def test_outlives_the_unit_that_queued_it(self):
        # what the reap and a deploy do: queue a note from a oneshot unit
        # that ends at once; its cgroup's leftovers are killed then
        code = f"import sys; sys.path.insert(0, {HERE!r}); import engineer as E; E.no1_send('[crew] from a unit')"
        p = subprocess.run(["systemd-run", "--user", "--quiet", "--wait", "--collect", "-p", "Type=oneshot",
                            *(f"--setenv={k}={self.env[k]}" for k in ("LCARS_ENG_STATE", "LCARS_ENG_ROOT", "PATH", "LCARS_LIVE",
                                                                      "LCARS_URL", "LCARS_CREW_ENV")
                              if k in self.env),
                            sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.wait_for(lambda: self.prompts() and not self.inbox()), "the flusher died with the unit")
        time.sleep(2)  # a second, late typing would show here
        self.assertEqual(self.prompts(), ["[crew] from a unit"])
        self.assertEqual([r["title"] for r in self.j.kind("crew_inbox")], ["number-one ← crew: [crew] from a unit"])

    def test_a_note_while_the_journal_is_down_is_written_when_it_is_back(self):
        self.j.down = True
        p = subprocess.Popen([sys.executable, ENG, "no1-send", "[deploy finished] x"], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1)
        self.assertEqual(self.j.kind("crew_inbox"), [])
        self.j.down = False
        o, e = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, e)
        self.assertEqual([r["title"] for r in self.j.kind("crew_inbox")],
                         ["number-one ← deploy finished: [deploy finished] x"])

    def test_held_since_marks_an_old_note(self):
        import engineer as E
        self.assertEqual(E.held_since({"created_at_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}), "")
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 600))
        self.assertEqual(E.held_since({"created_at_utc": old}), f"(held since {old[:16]} UTC, while you were off duty) ")
        self.assertEqual(E.held_since({}), "")


if __name__ == "__main__":
    unittest.main()
