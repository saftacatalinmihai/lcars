#!/usr/bin/env python3
"""Unit tests for the scratch reaper in scripts/engineer.py (reap_scratch):
ended Claude sessions' scratch is deleted, a running one's never. Real
processes stand in for Claude Code (sleep, run as "claude" so its comm is
claude), in a temp directory; nothing outside it is touched. Linux only.

    python3 scripts/test_reap.py
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
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402

DAY = 86400
IDS = ["0b8e3c2a-1d4f-4e5a-9b6c-%012d" % i for i in range(10)]


class Reap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reap-test-")
        self.root = os.path.join(self.tmp, "claude-tmp")
        self.sessions = os.path.join(self.tmp, "sessions")
        os.makedirs(self.root)
        os.makedirs(self.sessions)
        self.claude = os.path.join(self.tmp, "bin", "claude")
        os.makedirs(os.path.dirname(self.claude))
        os.symlink(shutil.which("sleep"), self.claude)
        self.procs = []
        self.ps = [mock.patch.object(E, "CLAUDE_TMP", self.root), mock.patch.object(E, "CLAUDE_SESSIONS", self.sessions),
                   mock.patch.object(E, "SCRATCH_KEEP_H", 6.0)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d

    def pad(self, cwd, sid, age=2 * DAY):
        """A session's scratch, last written `age` seconds ago."""
        d = os.path.join(self.root, E.claude_slug(cwd), sid)
        os.makedirs(os.path.join(d, "scratchpad", "deep"))
        with open(os.path.join(d, "scratchpad", "deep", "copy.db"), "w") as f:
            f.write("x" * 5000)
        t = time.time() - age
        for top, dirs, files in os.walk(d):
            for n in dirs + files:
                os.utime(os.path.join(top, n), (t, t))
        os.utime(d, (t, t))
        return d

    def spawn(self, cwd, exe=None, env=None, record=None):
        """A running process; with `record`, a Claude session record for it."""
        p = subprocess.Popen([exe or self.claude, "300"], cwd=cwd, env=env)
        self.procs.append(p)
        for _ in range(100):   # until exec has named it
            with open(f"/proc/{p.pid}/comm") as f:
                if f.read().strip() == os.path.basename(exe or self.claude):
                    break
            time.sleep(0.01)
        if record:
            with open(f"/proc/{p.pid}/stat") as f:
                start = f.read().rsplit(")", 1)[1].split()[19]
            rec = {"pid": p.pid, "sessionId": record, "cwd": cwd, "procStart": start}
            with open(os.path.join(self.sessions, f"{p.pid}.json"), "w") as f:
                json.dump(rec, f)
        return p

    def test_an_ended_session_is_deleted(self):
        w = self.project("w")
        d = self.pad(w, IDS[0])
        gone, freed = E.reap_scratch()
        self.assertEqual(gone, [f"{E.claude_slug(w)}/{IDS[0]}"])
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(d))
        self.assertFalse(os.path.exists(os.path.dirname(d)))   # the emptied project too

    def test_a_running_sessions_scratch_is_kept(self):
        w = self.project("w")
        live = self.pad(w, IDS[0])
        dead = self.pad(w, IDS[1])
        self.spawn(w, record=IDS[0])
        E.reap_scratch()
        self.assertTrue(os.path.isfile(os.path.join(live, "scratchpad", "deep", "copy.db")))
        self.assertFalse(os.path.exists(dead))

    def test_a_cleared_sessions_first_scratch_is_kept_while_held_open(self):
        # after /clear the record names the new session, while the process
        # still holds a directory of the first one open
        w = self.project("w")
        first = self.pad(w, IDS[0])
        os.makedirs(os.path.join(first, "tasks"))
        fd = os.open(os.path.join(first, "tasks"), os.O_RDONLY)
        try:
            p = subprocess.Popen([self.claude, "300"], cwd=w, pass_fds=(fd,))
            self.procs.append(p)
            time.sleep(0.05)
            with open(f"/proc/{p.pid}/stat") as f:
                start = f.read().rsplit(")", 1)[1].split()[19]
            with open(os.path.join(self.sessions, f"{p.pid}.json"), "w") as f:
                json.dump({"pid": p.pid, "sessionId": IDS[1], "procStart": start}, f)
        finally:
            os.close(fd)
        E.reap_scratch()
        self.assertTrue(os.path.isdir(first))

    def test_a_claude_without_a_record_keeps_its_whole_project(self):
        w, x = self.project("w"), self.project("x")
        kept = [self.pad(w, IDS[0]), self.pad(w, IDS[1])]
        other = self.pad(x, IDS[2])
        self.spawn(w)   # no record: which session is its own is unknown
        E.reap_scratch()
        for d in kept:
            self.assertTrue(os.path.isdir(d))
        self.assertFalse(os.path.exists(other))

    def test_a_record_left_by_another_process_with_the_pid_is_not_trusted(self):
        w = self.project("w")
        kept = [self.pad(w, IDS[0]), self.pad(w, IDS[1])]
        p = self.spawn(w)
        with open(os.path.join(self.sessions, f"{p.pid}.json"), "w") as f:
            json.dump({"pid": p.pid, "sessionId": IDS[0], "procStart": "1"}, f)
        E.reap_scratch()
        for d in kept:
            self.assertTrue(os.path.isdir(d))

    def test_a_record_of_a_dead_process_keeps_nothing(self):
        w = self.project("w")
        d = self.pad(w, IDS[0])
        p = self.spawn(w, record=IDS[0])
        p.kill()
        p.wait()
        E.reap_scratch()
        self.assertFalse(os.path.exists(d))

    def test_a_process_in_a_sessions_scratch_or_naming_it_keeps_it(self):
        w = self.project("w")
        in_it = self.pad(w, IDS[0])
        by_env = self.pad(w, IDS[1])
        by_arg = self.pad(w, IDS[2])
        dead = self.pad(w, IDS[3])
        sleep = shutil.which("sleep")
        self.spawn(os.path.join(in_it, "scratchpad"), exe=sleep)                         # a shell of it, cd'd there
        self.spawn(w, exe=sleep, env=dict(os.environ, CLAUDE_CODE_SESSION_ID=IDS[1]))   # its tool's child
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", "--resume", IDS[2]], cwd=w)
        self.procs.append(p)
        E.reap_scratch()
        for d in (in_it, by_env, by_arg):
            self.assertTrue(os.path.isdir(d))
        self.assertFalse(os.path.exists(dead))

    def test_a_session_written_lately_is_kept(self):
        w = self.project("w")
        fresh = self.pad(w, IDS[0], age=3600)
        # an old directory with one new file in it is fresh
        stale_top = self.pad(w, IDS[1])
        with open(os.path.join(stale_top, "scratchpad", "deep", "new.txt"), "w") as f:
            f.write("y")
        old = self.pad(w, IDS[2], age=7 * 3600)
        E.reap_scratch()
        self.assertTrue(os.path.isdir(fresh))
        self.assertTrue(os.path.isdir(stale_top))
        self.assertFalse(os.path.exists(old))

    def test_what_is_not_a_session_is_left_alone(self):
        w = self.project("w")
        for n in ("bash-edit-diff", "bundled-skills"):
            os.makedirs(os.path.join(self.root, n, IDS[4]))
        with open(os.path.join(self.root, "no1-suite.log"), "w") as f:
            f.write("log")
        slug = os.path.join(self.root, E.claude_slug(w))
        os.makedirs(os.path.join(slug, "not-a-session"))
        with open(os.path.join(slug, IDS[5]), "w") as f:   # a file, not a directory
            f.write("x")
        target = self.pad(self.project("t"), IDS[6])
        os.symlink(target, os.path.join(slug, IDS[7]))     # a link is never followed
        os.utime(target, (0, 0))
        self.spawn(self.project("t"), record=IDS[6])
        E.reap_scratch()
        for n in ("bash-edit-diff/" + IDS[4], "bundled-skills/" + IDS[4], "no1-suite.log",
                  E.claude_slug(w) + "/not-a-session", E.claude_slug(w) + "/" + IDS[5], E.claude_slug(w) + "/" + IDS[7]):
            self.assertTrue(os.path.lexists(os.path.join(self.root, n)), n)
        self.assertTrue(os.path.isdir(target))

    def test_a_root_that_is_a_link_is_left_alone(self):
        w = self.project("w")
        real = os.path.join(self.tmp, "real")
        os.makedirs(real)
        shutil.rmtree(self.root)
        os.symlink(real, self.root)
        d = os.path.join(real, E.claude_slug(w), IDS[0])
        os.makedirs(d)
        os.utime(d, (0, 0))
        self.assertEqual(E.reap_scratch(), ([], 0))
        self.assertTrue(os.path.isdir(d))

    def test_unreadable_proc_keeps_everything(self):
        d = self.pad(self.project("w"), IDS[0])
        with mock.patch.object(E, "live_sessions", return_value=None):
            self.assertEqual(E.reap_scratch(), ([], 0))
        self.assertTrue(os.path.isdir(d))



class TestTmp(unittest.TestCase):
    """reap_test_tmp: killed test runs' scratch, by name and age, and the
    tests' own cleanup when they are killed (SIGTERM, as the tool's timeout)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reap-test-")
        self.p = mock.patch.object(E, "TEST_TMP_ROOTS", [self.tmp])
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self, name, files=("server.log",), age=2 * DAY):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        for f in files:
            with open(os.path.join(d, f), "w") as fh:
                fh.write("x")
            os.utime(os.path.join(d, f), (time.time() - age,) * 2)
        os.utime(d, (time.time() - age,) * 2)
        return d

    def test_old_test_dirs_go_the_rest_stays(self):
        gone = [self.mk("lcars-perf-base-ab12cd34", ("lcars-ui",)), self.mk("lcars-seat-test-x_9yz"),
                self.mk("lcars-model-test-q1w2e3r4"), self.mk("queue-test-abcdef12"), self.mk("lcars-upd-k3j_9x2a"),
                self.mk("playwright_chromiumdev_profile-UbLdDf"), self.mk("lcars-run.Ab12Cd"),
                self.mk("tmp.ZUPSKym5uy", ("deck", "behaviour", "keyboard", "qjs.out", "kb.out"))]
        kept = [self.mk("lcars-perf-base-fresh123", age=3600),            # a run going on now
                self.mk("lcars-crew-counselor-abc12345"),                 # a crew run's, not a test's
                self.mk("tmp.Vu39oYozZ2", ("deck", "notes.txt")),         # someone's mktemp, not run.sh's
                self.mk("tmp.Wc8hYq2lE3", ()),                            # empty: nothing says whose
                self.mk("my-lcars-perf-base-ab12cd34"), self.mk("lcars.db-backup")]
        old_inside = self.mk("lcars-editor-recent1", ("old.log",))
        with open(os.path.join(old_inside, "new.log"), "w") as fh:         # written to just now
            fh.write("x")
        kept.append(old_inside)
        link = os.path.join(self.tmp, "lcars-perf-base-link1234")
        os.symlink(kept[0], link)                                         # a link is never followed
        swept, freed = E.reap_test_tmp()
        self.assertEqual(sorted(swept), sorted(gone))
        self.assertGreater(freed, 0)
        for d in kept + [link]:
            self.assertTrue(os.path.lexists(d), d)

    def test_keep_hours(self):
        d = self.mk("lcars-logins-abcd1234", age=3 * 3600)
        with mock.patch.object(E, "TEST_TMP_KEEP_H", 24.0):
            self.assertEqual(E.reap_test_tmp(), ([], 0))
        with mock.patch.object(E, "TEST_TMP_KEEP_H", 2.0):
            self.assertEqual(E.reap_test_tmp()[0], [d])

    def test_remotion_bundles(self):
        """Remotion's leftovers (a render's webpack bundle, its assets, a
        render.sh TMPDIR a SIGKILL left) go after REMOTION_KEEP_H, not a day;
        a younger one, one of a render that may still run, stays."""
        gone = [self.mk("remotion-webpack-bundle-KU02qq", age=3 * 3600),
                self.mk("remotion-v4.0.537-assetsv9umqiecmn", age=3 * 3600),
                self.mk("lcars-render-m321MiL3", age=3 * 3600)]
        kept = [self.mk("remotion-webpack-bundle-fresh1", age=3600),        # a render under way
                self.mk("remotion-webpack-bundle-", age=3 * 3600),          # not Remotion's name
                self.mk("my-remotion-webpack-bundle-abc", age=3 * 3600)]
        with mock.patch.object(E, "remotion_running", return_value=False), \
                mock.patch.object(E, "REMOTION_KEEP_H", 2.0):
            swept, _ = E.reap_test_tmp()
        self.assertEqual(sorted(swept), sorted(gone))
        for d in kept:
            self.assertTrue(os.path.isdir(d), d)

    def test_remotion_in_use(self):
        """While any Remotion process of ours runs, no Remotion dir goes,
        however old (a render reads its bundle to the end); the rest of the
        sweep is not held up by it."""
        old = [self.mk("remotion-webpack-bundle-Ab12Cd", age=2 * DAY), self.mk("lcars-render-Zz99yy00", age=2 * DAY)]
        other = self.mk("lcars-logins-abcd1234")
        with mock.patch.object(E, "remotion_running", return_value=True) as rr:
            swept, _ = E.reap_test_tmp()
        self.assertEqual(swept, [other])
        self.assertEqual(rr.call_count, 1)  # asked once a sweep, not per dir
        for d in old:
            self.assertTrue(os.path.isdir(d), d)
        for d in old:
            shutil.rmtree(d)
        with mock.patch.object(E, "remotion_running", side_effect=AssertionError("asked")):
            self.mk("lcars-api-abcd1234")
            E.reap_test_tmp()  # no Remotion dir left to judge: no /proc scan

    def test_remotion_running_reads_proc(self):
        """remotion_running finds a process of ours with a word of its argv
        naming Remotion, and not a shell whose script only mentions it (a
        Claude Code's tool call: `zsh -c '... grep remotion ...'`)."""
        if E.remotion_running():
            self.skipTest("a Remotion process is running on this box")
        talk = subprocess.Popen(["sh", "-c", "sleep 30 # grep remotion src"])
        render = None
        try:
            time.sleep(0.2)
            self.assertFalse(E.remotion_running())
            render = subprocess.Popen(["sh", "-c", "sleep 30", "node_modules/.bin/remotion"])
            time.sleep(0.2)
            self.assertTrue(E.remotion_running())
        finally:
            for p in (talk, render):
                if p:
                    p.kill()
                    p.wait()

    def server(self, d, name="lcars-test"):
        """A stand-in scratch server: sleep, copied to d/name and started from
        there, so its argv[0] is that path."""
        os.makedirs(d, exist_ok=True)
        b = os.path.join(d, name)
        shutil.copy(shutil.which("sleep"), b)
        p = subprocess.Popen([b, "300"])
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait()))
        return p

    def test_stray_test_servers_end_the_rest_run(self):
        stray = self.server(os.path.join(self.tmp, "lcars-off-ab12cd34"))
        nested = self.server(os.path.join(self.tmp, "lcars-model-test-x9y8", "route"), "lcars")
        mine = tempfile.mkdtemp(prefix="eng-build-")       # not under a test's scratch
        self.addCleanup(shutil.rmtree, mine, True)
        own = self.server(os.path.join(mine, "bin"))
        prod = self.server(os.path.join(self.tmp, "lcars-off-ab12cd34-not"), "lcars-new")  # not the name
        time.sleep(0.2)
        self.assertEqual(E.reap_test_servers(), [])                                # all young
        ended = E.reap_test_servers(now=time.time() + 2 * DAY)
        self.assertEqual(sorted(ended), sorted([stray.pid, nested.pid]))
        for p in (stray, nested):
            self.assertEqual(p.wait(timeout=5), -signal.SIGTERM)
        for p in (own, prod):
            self.assertIsNone(p.poll())
        self.assertTrue(E.test_server_path("/tmp/lcars-upd-k3j9/lcars-test"))
        self.assertFalse(E.test_server_path("/srv/ana/lcars/lcars"))

    def test_killclean_ends_its_children_on_sigterm(self):
        ui = os.path.join(os.path.dirname(HERE), "lcars-ui", "test")
        code = (f"import subprocess, sys, time; sys.path.insert(0, {ui!r}); import killclean\n"
                f"d = killclean.mkdtemp('lcars-x-', dir={self.tmp!r})\n"
                "c = killclean.child(subprocess.Popen(['sleep', '300']))\n"
                "open(d + '/pid', 'w').write(str(c.pid))\n"
                "print(d, flush=True); time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        d = p.stdout.readline().strip()
        with open(os.path.join(d, "pid")) as fh:
            child = int(fh.read())
        p.send_signal(signal.SIGTERM)
        p.stdout.close()
        self.assertEqual(p.wait(timeout=30), -signal.SIGTERM)
        self.assertFalse(os.path.exists(d))
        # the child was ended and waited for (reaped), so its pid is gone
        self.assertFalse(os.path.exists(f"/proc/{child}"))

    def killed(self, code, env=None):
        """Run code in a python that prints its scratch dir and sleeps; SIGTERM
        it; (its exit status, the dir)."""
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                             env=dict(os.environ, **(env or {})))
        d = p.stdout.readline().strip()
        self.assertTrue(os.path.isdir(d), d)
        p.send_signal(signal.SIGTERM)
        p.stdout.close()
        return p.wait(timeout=30), d

    def test_killclean_removes_its_dirs_on_sigterm(self):
        ui = os.path.join(os.path.dirname(HERE), "lcars-ui", "test")
        rc, d = self.killed(f"import sys, time; sys.path.insert(0, {ui!r}); import killclean\n"
                            f"print(killclean.mkdtemp('lcars-x-', dir={self.tmp!r}), flush=True); time.sleep(60)")
        self.assertEqual(rc, -signal.SIGTERM)   # ended by the signal, as without the handler
        self.assertFalse(os.path.exists(d))

    def test_seat_tests_scratch_goes_on_sigterm_and_at_exit(self):
        code = (f"import sys, time; sys.path.insert(0, {HERE!r}); import test_seat\n"
                "print(test_seat.TMP, flush=True); time.sleep(60)")
        rc, d = self.killed(code, {"TMPDIR": self.tmp})
        self.assertEqual(rc, -signal.SIGTERM)
        self.assertFalse(os.path.exists(d))
        out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {HERE!r}); import test_engineer_model as t;"
                              " print(t.TMP)"], capture_output=True, text=True, env=dict(os.environ, TMPDIR=self.tmp))
        self.assertTrue(out.stdout.strip().startswith(self.tmp), out.stdout + out.stderr)
        self.assertFalse(os.path.exists(out.stdout.strip()))

    def test_run_sh_removes_its_dir_on_sigterm(self):
        run = os.path.join(os.path.dirname(HERE), "lcars-ui", "test", "run.sh")
        p = subprocess.Popen(["sh", run], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, TMPDIR=self.tmp, PERF="0", KB="0"))
        deadline, d = time.time() + 60, None
        while time.time() < deadline and not d:
            d = next((os.path.join(self.tmp, n) for n in os.listdir(self.tmp) if n.startswith("lcars-run.")), None)
            time.sleep(0.2)
        self.assertTrue(d, "run.sh made no lcars-run. dir")
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=30), 143)
        self.assertFalse(os.path.exists(d))

if __name__ == "__main__":
    unittest.main()
