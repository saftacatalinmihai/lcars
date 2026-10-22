#!/usr/bin/env python3
"""Unit tests for Number One's threads as tags (docs/design/no1-threads.md,
section 13): engineer.py's `thread` verbs and `thread-req` (labels only),
the state read from the session-era shape (thread_norm), the tag line on
what is typed (the flusher, a say with a thread), which thread each event
of the transcript is in (thread_marks, thread_at, the poll's `th` and its
`thread=` filter), the turn's thread (thread_now) that an order, an ask, a
deploy and a refresh record, and no1.py's `thread` and `escalate`.

Claude Code is a stand-in (Proc) that records what herdr types into it;
the transcript is a file the test writes. The state directory is a temp
directory, the journal's inbox is in memory (Journal); nothing is started
and no server is asked.

    python3 scripts/test_no1_threads.py
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402
import no1  # noqa: E402
import seat  # noqa: E402


def utc(ago=0):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - ago))


class Journal:
    """The entries the seat module writes (seat._http), in memory: the
    inbox. No test here reaches a server."""

    def __init__(self):
        self.rows, self.down = [], False

    def http(self, method, path, body=None):
        if self.down:
            raise seat.Down("down")
        if method == "POST" and path == "/entries":
            r = dict(body, id=len(self.rows) + 1, done_bool=0, deleted=0, created_at_utc=utc())
            self.rows.append(r)
            return {"id": r["id"]}
        if method == "PUT" and path.startswith("/entries/"):
            r = next(x for x in self.rows if x["id"] == int(path.split("/")[2]))
            r.update(body)
            return r
        if method == "GET" and path.startswith("/entries?"):
            q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&"))
            return [dict(r) for r in self.rows if r["kind"] == q["kind"] and r["done_bool"] == int(q["done"])]
        raise AssertionError("unexpected " + method + " " + path)

    def inbox(self):
        return [r for r in self.rows if r["kind"] == "crew_inbox" and not r["done_bool"]]

    def titles(self):
        return [r["title"] for r in self.inbox()]

    def held(self, sender, text, ago=0):
        """A row as no1_send writes it, `ago` seconds old."""
        r = {"id": len(self.rows) + 1, "kind": "crew_inbox", "title": f"{E.NO1} ← {sender}: {text[:90]}",
             "content": text, "done_bool": 0, "deleted": 0, "created_at_utc": utc(ago)}
        self.rows.append(r)
        return r


class Proc:
    """Number One's Claude Code, as herdr sees it: what is typed, recorded."""

    def __init__(self, session):
        self.session, self.status, self.typed = session, "idle", []

    def herdr(self, *a, timeout=0):
        if a[:2] == ("agent", "prompt"):
            self.typed.append(a[3])
        return {}, None

    def info(self, name):
        if name != E.NO1 or self.status == "off":
            return None
        return {"agent_status": self.status, "pane_id": "w2:p1", "agent_session": {"value": self.session}}


def me(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def them(*texts):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": t} for t in texts]}})


def tool(name="Bash"):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name,
                                                                      "input": {"command": "ls"}}]}})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-threads-")
        self.state = os.path.join(self.tmp, "state")
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.state)
        os.makedirs(self.proj)
        self.main = str(uuid.uuid4())
        open(os.path.join(self.proj, self.main + ".jsonl"), "w").close()
        self.p = Proc(self.main)
        self.spawned = []
        self.j = Journal()
        # the paths engineer.py made from STATE when it loaded go with it
        self.ps = [mock.patch.object(E, "STATE", self.state),
                   mock.patch.object(E, "DEPLOY_JSON", os.path.join(self.state, "deploy.json")),
                   mock.patch.object(E, "HISTORY", os.path.join(self.state, "deploys.jsonl")),
                   mock.patch.object(E, "NO1_ANSWERS", os.path.join(self.state, "no1-answers.json")),
                   mock.patch.object(E, "herdr", self.p.herdr),
                   mock.patch.object(E, "agent_info", self.p.info),
                   mock.patch.object(E, "transcript", self.transcript),
                   mock.patch.object(E, "submit_if_left"),
                   mock.patch.object(E, "note_typed"),
                   mock.patch.object(E, "seat_on", return_value=False),
                   mock.patch.object(E, "spawn", side_effect=lambda *a: self.spawned.append(a) or "unit"),
                   mock.patch.object(seat, "_http", self.j.http),
                   mock.patch.object(E.time, "sleep")]
        for p in self.ps:
            p.start()
        E.save(E.NO1, {"name": E.NO1, "session": self.main, "created": 1})

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp)

    def transcript(self, sid):
        path = os.path.join(self.proj, sid + ".jsonl")
        return path if sid and os.path.exists(path) else None

    def write(self, *lines):
        with open(self.transcript(self.main), "a") as f:
            for ln in lines:
                f.write(ln + "\n")

    def call(self, fn, *a, stdin=""):
        with contextlib.redirect_stdout(io.StringIO()) as buf, mock.patch("sys.stdin", io.StringIO(stdin)):
            try:
                fn(*a)
                code = 0
            except SystemExit as e:
                code = e.code
        return code, json.loads(buf.getvalue() or "null")

    def thread(self, *a):
        return self.call(E.cmd_thread, E.NO1, *a)

    def st(self):
        return E.load(E.NO1)

    def ids(self, closed=False):
        return [t["id"] for t in E.threads_of(self.st(), closed)]


class Labels(Base):
    def test_no_threads_is_main(self):
        code, r = self.thread("list")
        self.assertEqual((code, [t["id"] for t in r["threads"]], r["closed"]), (0, ["main"], []))

    def test_new_rename_close_reopen(self):
        n = len(self.p.typed)
        code, r = self.thread("new", "deck", "Deck", "redesign")
        self.assertEqual((code, r["name"]), (0, "Deck redesign"), r)
        self.assertEqual(self.ids(), ["main", "deck"])
        self.assertEqual(self.thread("new", "deck")[0], 2, "there already")
        self.assertEqual(self.thread("rename", "deck", "The", "bridge")[0], 0)
        self.assertEqual(E.thread_find(self.st()["threads"], "deck")["name"], "The bridge")
        self.assertEqual(self.thread("close", "main")[0], 2)
        self.assertEqual(self.thread("close", "deck")[0], 0)
        self.assertEqual((self.ids(), self.ids(True)), (["main"], ["main", "deck"]))
        self.assertEqual(self.thread("close", "deck")[0], 4, "closed already")
        code, r = self.thread("new", "deck")
        self.assertEqual((code, r["reopened"], r["name"]), (0, True, "The bridge"))
        self.assertEqual(self.ids(), ["main", "deck"])
        self.assertEqual(self.thread("rename", "nope", "x")[0], 4)
        self.assertEqual(self.thread("new", "Bad id")[0], 2)
        self.assertEqual(self.thread("switch", "deck")[0], 2, "no switch any more")
        self.assertEqual(self.thread("fork", "deck")[0], 2)
        self.assertEqual(self.p.typed[n:], [], "labels type nothing")
        for i in range(8):  # no cap
            self.assertEqual(self.thread("new", f"t{i}")[0], 0)

    def test_the_session_era_state_is_read_as_labels(self):
        old, gone = str(uuid.uuid4()), str(uuid.uuid4())
        st = self.st()
        st.update(thread="deck", switch={"to": "main"}, switching=5,
                  threads=[{"id": "main", "name": "Main", "session": old, "at": 1, "used": 2, "from": None},
                           {"id": "deck", "name": "Deck", "session": self.main, "at": 3, "used": 4,
                            "from": {"thread": "main", "how": "new"}}],
                  closed=[{"id": "web", "name": "Web", "session": gone, "at": 5, "closed": 6}])
        E.save(E.NO1, st)
        st = self.st()
        self.assertEqual(st["threads"], [{"id": "main", "name": "Main", "at": 1}, {"id": "deck", "name": "Deck", "at": 3},
                                         {"id": "web", "name": "Web", "at": 5, "closed": 6}])
        for k in ("thread", "switch", "switching", "closed"):
            self.assertNotIn(k, st)
        # the conversations no longer in use stay readable, in past
        self.assertEqual({p["session"]: p["name"] for p in st["past"]}, {old: "thread Main", gone: "thread Web"})
        E.save(E.NO1, st)  # again: nothing added twice
        self.assertEqual(len(self.st()["past"]), 2)

    def test_thread_req(self):
        req = lambda body: self.call(E.cmd_thread_req, E.NO1, stdin=json.dumps(body))
        code, r = req({"op": "new", "id": "web", "name": "Web  app"})
        self.assertEqual((code, [t["id"] for t in r["threads"]]), (0, ["main", "web"]), r)
        self.assertEqual(req({"op": "rename", "id": "web", "name": "Site"})[1]["name"], "Site")
        self.assertEqual([t["id"] for t in req({"op": "close", "id": "web"})[1]["closed"]], ["web"])
        for bad in ({"op": "switch", "id": "main"}, {"op": "fork", "id": "main"}, {"op": "new", "id": "Bad id"}):
            self.assertEqual(req(bad)[0], 2, bad)
        self.assertEqual(self.call(E.cmd_thread_req, E.NO1, stdin="not json")[0], 2)
        self.assertEqual(self.call(E.cmd_thread_req, "obrien", stdin="{}")[0], 2)
        self.assertEqual(self.spawned, [], "nothing detached")


class Marks(Base):
    """Which thread each event is in."""

    def marks(self, evs, cur="main"):
        return [(e["th"], e["r"], e["t"]) for e in E.thread_marks(evs, cur)[0]]

    def test_a_message_s_tag_and_the_reply_after_it(self):
        evs = [{"r": "me", "t": "[thread deck]\n[crew] obrien finished"}, {"r": "them", "t": "Reviewed."},
               {"r": "tool", "t": "Bash ls"}, {"r": "me", "t": "And main?"}, {"r": "them", "t": "Fine."}]
        self.assertEqual(self.marks(evs), [("deck", "me", "[crew] obrien finished"), ("deck", "them", "Reviewed."),
                                           ("deck", "tool", "Bash ls"), ("main", "me", "And main?"),
                                           ("main", "them", "Fine.")])
        # a reply whose message came before the chunk: the thread in force
        self.assertEqual(self.marks([{"r": "them", "t": "x"}], "web"), [("web", "them", "x")])

    def test_an_override_moves_the_rest_of_the_turn(self):
        evs = [{"r": "me", "t": "Status?"},
               {"r": "them", "t": "Main is quiet.\n\n[thread deck]\nThe chairs are done.\n\nMore on them."},
               {"r": "tool", "t": "Bash ls"}, {"r": "them", "t": "Still deck."}, {"r": "me", "t": "ok"}]
        self.assertEqual(self.marks(evs), [("main", "me", "Status?"), ("main", "them", "Main is quiet."),
                                           ("deck", "them", "The chairs are done.\n\nMore on them."),
                                           ("deck", "tool", "Bash ls"), ("deck", "them", "Still deck."),
                                           ("main", "me", "ok")])
        # at the text's start too; and not in the middle of a line or paragraph
        self.assertEqual(self.marks([{"r": "them", "t": "[thread web] Hello"}]), [("web", "them", "Hello")])
        t = "See the [thread deck] line.\n[thread deck] not a paragraph's start"
        self.assertEqual(self.marks([{"r": "them", "t": t}]), [("main", "them", t)])

    def test_thread_at_reads_back_to_the_last_message_or_override(self):
        path = self.transcript(self.main)
        self.assertEqual(E.thread_at(path, 0), "main")
        self.write(me("[thread deck]\nlook at the chairs"), them("On it."), tool())
        at = os.path.getsize(path)
        self.write(me("hello"), them("Hi.\n\n[thread web]\nAnd the site: done."), tool(), them("x"))
        self.assertEqual(E.thread_at(path, at), "deck")
        self.assertEqual(E.thread_at(path, os.path.getsize(path)), "web")
        self.assertEqual(E.thread_now(), "web")
        self.write(me("next"))
        self.assertEqual(E.thread_now(), "main")
        with mock.patch.object(E, "THREAD_SCAN_BYTES", 10):
            self.assertEqual(E.thread_at(path, at), "main", "nothing found in reach: main")


class Delivery(Base):
    def test_the_flusher_types_every_thread_s_at_once_tagged(self):
        self.j.held("crew#deck", "[crew] obrien finished")
        self.j.held("ship", "[seat] a note")
        self.j.held("crew#main", "[crew] kim finished")
        self.j.held("deploy failed#web", "[deploy failed] torres: x", ago=900)
        code, r = self.call(E.cmd_no1_flush)
        self.assertEqual((code, r["sent"], r["left"]), (0, 4, 0), r)
        self.assertEqual(self.p.typed[:3], ["[thread deck]\n[crew] obrien finished", "[seat] a note", "[crew] kim finished"])
        self.assertRegex(self.p.typed[3], r"^\[thread web\]\n\(held since .* off duty\) \[deploy failed\] torres: x$")
        self.assertNotIn("held", r)

    def test_a_say_with_a_thread_is_tagged(self):
        self.thread("new", "deck", "Deck")
        code, r = self.call(E.cmd_say, E.NO1, False, False, "deck", stdin="How is the bridge?")
        self.assertEqual(code, 0, r)
        self.assertEqual(self.p.typed[-1], "[thread deck]\nHow is the bridge?")
        self.call(E.cmd_say, E.NO1, False, True, None, stdin=json.dumps({"message": "Main's.", "thread": "main"}))
        self.assertEqual(self.p.typed[-1], "Main's.")
        self.thread("close", "deck")
        self.assertEqual(self.call(E.cmd_say, E.NO1, False, False, "deck", stdin="back")[0], 0)
        self.assertEqual(self.ids(), ["main", "deck"], "a word into a closed thread reopens it")
        self.assertEqual(self.call(E.cmd_say, E.NO1, False, True, None,
                                   stdin=json.dumps({"message": "x", "thread": "nope"}))[0], 4)
        self.assertEqual(self.call(E.cmd_say, E.NO1, False, False, "Bad!", stdin="x")[0], 2)
        self.assertEqual(self.call(E.cmd_say, "obrien", False, False, "deck", stdin="x")[0], 2)

    def test_the_turn_s_thread_routes_what_it_causes(self):
        self.thread("new", "deck", "Deck")
        self.write(me("[thread deck]\nShip obrien's work"), them("Ordering."))
        # an order
        E.save("obrien", {"name": "obrien", "session": "s"})
        self.assertIsNone(E.thread_take("obrien"))
        self.assertEqual(E.load("obrien")["no1_thread"], "deck")
        E.notify_no1("obrien", "[crew] obrien finished a turn")
        self.assertEqual(self.j.titles()[-1], "number-one ← crew#deck: [crew] obrien finished a turn")
        # an ask
        E.thread_ask(41)
        self.assertEqual(self.st()["asks"], {"41": "deck"})
        # a deploy Number One asked for
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(E, "run", return_value=ok), mock.patch.dict(os.environ, {"LCARS_THREAD_BY": "no1"}):
            self.call(E.detach, "deploy", "obrien")
        self.assertEqual(E.read_deploy()["by_thread"], "deck")
        # a refresh
        with mock.patch.object(E, "launched_bare", return_value=False):
            self.call(E.cmd_refresh, E.NO1)
        self.assertEqual(self.st()["refresh"]["thread"], "deck")
        # an order from main while they work for deck: a warning
        self.write(me("Now main"))
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"} if n == "obrien" else None):
            w = E.thread_take("obrien")
        self.assertIn("thread deck", w)
        self.assertIn("thread main", w)

    def test_no1_send_s_retry_keeps_the_thread(self):
        self.j.down = True
        E.no1_send("[crew] x", thread="deck")
        self.assertEqual(self.spawned[-1], ("no1-send", "--thread", "deck", "[crew] x"))
        self.j.down = False
        self.call(E.cmd_no1_send, "--thread", "deck", "[crew]", "x")
        self.assertEqual(self.j.titles(), ["number-one ← crew#deck: [crew] x"])
        self.assertEqual(self.call(E.cmd_no1_send, "--thread", "Bad", "x")[0], 2)

    def test_crew_notes_name_a_thread_or_go_to_main(self):
        import crew_notes as N
        cap = lambda text: {"who": "Captain", "text": text}
        self.assertEqual(N.no1_thread_of({"role": "no1", "turns": [cap("#deck look at the chairs")]}), "deck")
        self.assertEqual(N.no1_thread_of({"role": "no1", "turns": [cap("look at #deck")]}), "main")
        with mock.patch.object(N, "engineer_run", return_value=(0, {})) as run:
            N.engineer_send(E.NO1, "[captain] x", "deck")
        run.assert_called_with("no1-send", "--thread", "deck", "[captain] x")

    def test_the_stop_hook_switches_nothing(self):
        st = self.st()
        st["switch"] = {"to": "deck"}  # a leftover from the session era
        E.save(E.NO1, st)
        self.call(E.cmd_hook, "turn-ended", E.NO1, stdin=json.dumps({"session_id": str(uuid.uuid4())}))
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.st()["session"], self.main)


class Poll(Base):
    def poll(self, *a):
        with mock.patch.object(E, "git_info", return_value={}), mock.patch.object(E, "deploy_state", return_value={}), \
                mock.patch.object(E, "preview_of", return_value=""):
            return self.call(E.cmd_poll, E.NO1, *a)

    def test_events_carry_their_thread_and_thread_filters(self):
        self.thread("new", "deck", "Deck")
        self.thread("new", "web", "Web")
        self.thread("close", "web")
        self.write(me("Status?"), them("Quiet."), me("[thread deck]\nThe chairs?"), them("Done."), tool())
        mid = os.path.getsize(self.transcript(self.main))
        self.write(them("And pushed.\n\n[thread web]\nThe site too."))
        code, r = self.poll("-1", None, None, None)
        self.assertEqual(code, 0, r)
        self.assertEqual(r["threads"], [{"id": "main", "name": "Main"}, {"id": "deck", "name": "Deck"}])
        self.assertNotIn("thread", r)
        # the server's clock, for the page's stale rule (voice-live-narration.md 2.2)
        self.assertLess(abs(r["now"] - time.time()), 5)
        self.assertEqual(len({e["k"] for e in r["events"]}), len(r["events"]))
        self.assertEqual([(e["th"], e["t"]) for e in r["events"] if e["r"] != "tool"],
                         [("main", "Status?"), ("main", "Quiet."), ("deck", "The chairs?"), ("deck", "Done."),
                          ("deck", "And pushed."), ("web", "The site too.")])
        # from an offset in the middle of deck's turn
        code, r = self.poll(str(mid), None, None, None)
        self.assertEqual([(e["th"], e["t"]) for e in r["events"]], [("deck", "And pushed."), ("web", "The site too.")])
        # an earlier page ending there
        code, r = self.poll("-1", str(mid), None, None)
        self.assertEqual([e["th"] for e in r["events"]], ["main", "main", "deck", "deck", "deck"])
        # the filter: a closed thread's too
        code, r = self.poll("-1", None, None, "deck")
        self.assertEqual((r["thread"], {e["th"] for e in r["events"]}), ("deck", {"deck"}))
        self.assertEqual([e["t"] for e in self.poll("-1", None, None, "web")[1]["events"]], ["The site too."])
        self.assertEqual(self.poll("-1", None, None, "nope")[0], 4)
        self.assertEqual(self.call(E.cmd_poll, "obrien", "-1", None, None, "deck")[0], 2)


class No1Verbs(Base):
    def run_no1(self, *a):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                no1.main(list(a))
            except SystemExit as e:
                return e.code, json.loads(buf.getvalue() or "null")
        return 0, json.loads(buf.getvalue())

    def test_escalate_records_the_turn_s_thread(self):
        self.write(me("[thread deck]\nAsk the captain"))
        with mock.patch.object(no1, "http", return_value=(201, '{"id": 77}')):
            self.run_no1("escalate", "Ship it?", "context")
        self.assertEqual(self.st()["asks"], {"77": "deck"})

    def test_through_engineer_py_for_real(self):
        """no1.py's verbs run engineer.py with Number One's state."""
        env = dict(os.environ, LCARS_ENG_STATE=self.state)
        run = lambda *a: E.run([sys.executable, os.path.join(HERE, "engineer.py"), "thread", E.NO1, *a], env=env, inp="")
        self.assertEqual(json.loads(run("new", "deck", "Deck").stdout)["thread"], "deck")
        self.assertEqual([t["id"] for t in json.loads(run("list").stdout)["threads"]], ["main", "deck"])

    def test_the_brief_says_tags_not_switches(self):
        b = E.brief_no1(E.NO1, self.st())
        self.assertIn("[thread <id>]", b)
        self.assertIn("the thread of the message that started your turn", b)
        for gone in ("switch", "held, while", "resume"):
            self.assertNotIn(gone, b.split("Threads:", 1)[1].split("\n\n", 1)[0])

    def test_the_brief_has_the_computers_rule(self):
        """voice-quick-answer.md 9: told what the computer said aloud, not
        repeated; the line it names is index.html's quickLine, word for word."""
        b = E.brief_no1(E.NO1, self.st())
        self.assertIn(E.QUICK_RULE, b)
        self.assertIn('[computer answered the captain aloud: "..."]', b)
        self.assertIn("Do not repeat it.", b)
        self.assertIn("Correction:", b)
        self.assertLess(b.index(E.SPOKEN_RULE), b.index(E.QUICK_RULE))
        page = open(os.path.join(HERE, "..", "lcars-ui", "index.html"), encoding="utf-8").read()
        self.assertIn("'[computer answered the captain aloud: \"'", page)
        self.assertNotIn(E.QUICK_RULE, E.brief("laforge-c34", {"title": "La Forge"}), "an engineer's brief has no such line")


if __name__ == "__main__":
    unittest.main()
