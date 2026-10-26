#!/usr/bin/env python3
"""The model and effort per engineer: engineer.py model / effort /
model-apply, the defaults (Number One's own), and the
POST /engineer/<name>/model route; and an engineer's earlier conversations,
read through the poll (engineer.py poll's <past>, GET /engineer/<name>?past=).
And say --json, a message with the captain's files (chat attachments): a
line per file with its path on this box and its URL.

The decisions run against engineer.py with herdr stood in for (agent_info,
herdr and the restart are mocked) in a temp state directory. The route runs
on a scratch build of the real server (LCARS_TEST_BIN, else built here,
~30s; SKIP_ROUTE=1 skips it) whose LCARS_ENGINEER_SCRIPT is a stub that
answers with its argv - so what reaches the script is checked, not herdr.
Nothing outside the temp directories is touched.

    python3 scripts/test_engineer_model.py
"""

import atexit
import base64
import http.client
import io
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="lcars-model-test-")
# Gone at the end, and when the run is killed (the tool's timeout, a closed
# terminal), which a unittest would otherwise outlive: it catches the
# SystemExit a handler could raise. Then the signal ends it as it would have.
atexit.register(shutil.rmtree, TMP, True)


# the scratch server, ended first when the run is killed: it would go on
# running with its binary and database deleted under it
_procs = []


def _killed(sig, _frame):
    for p in _procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()
    shutil.rmtree(TMP, ignore_errors=True)
    signal.signal(sig, signal.SIG_DFL)
    os.kill(os.getpid(), sig)


for _sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(_sig, _killed)
os.environ.update(LCARS_ENG_STATE=os.path.join(TMP, "state"), LCARS_ENG_ROOT=os.path.join(TMP, "eng"),
                  LCARS_ENG_SEAT="0")
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402


def call(fn, *a):
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fn(*a)
    except SystemExit as e:
        return e.code or 0, json.loads(buf.getvalue())
    return 0, json.loads(buf.getvalue() or "{}")


def status(s):
    return mock.patch.object(E, "agent_info", return_value={"agent_status": s} if s else None)


class Model(unittest.TestCase):
    def setUp(self):
        os.makedirs(E.STATE, exist_ok=True)
        E.save("ada", {"name": "ada", "session": "s-ada", "title": "Ada"})
        self.restart = mock.patch.object(E, "model_restart", return_value="").start()
        self.addCleanup(mock.patch.stopall)

    def test_idle_is_applied_at_once(self):
        with status("idle"):
            code, r = call(E.cmd_model, "ada", "sonnet")
        self.assertEqual(code, 0)
        self.assertEqual((r["applied"], r["pending"]), (True, False))
        self.restart.assert_called_once_with("ada")
        self.assertEqual(E.load("ada")["model"], "sonnet")
        self.assertNotIn("model_pending", E.load("ada"))

    def test_working_waits_for_the_turn_s_end_and_applies_once(self):
        with status("working"):
            code, r = call(E.cmd_model, "ada", "haiku")
        self.assertEqual((code, r["pending"]), (0, True))
        self.restart.assert_not_called()
        self.assertEqual(E.load("ada")["model_pending"], "haiku")
        # the Stop hook starts model-apply, not the seat's own turn-ended
        with mock.patch.object(E, "spawn") as sp, mock.patch("sys.stdin", io.StringIO("{}")):
            call(E.cmd_hook, "turn-ended", "ada")
        sp.assert_called_once_with("model-apply", "ada")
        with status("idle"), mock.patch.object(E.time, "sleep"):
            call(E.cmd_model_apply, "ada")
            call(E.cmd_model_apply, "ada")  # a second turn's end: nothing left
        self.restart.assert_called_once_with("ada")
        self.assertEqual(E.load("ada")["model"], "haiku")
        self.assertNotIn("model_pending", E.load("ada"))

    def test_a_question_at_the_turn_s_end_keeps_it_pending(self):
        st = E.load("ada")
        st.update(model="opus", model_pending="opus")
        E.save("ada", st)
        with status("blocked"), mock.patch.object(E.time, "sleep"):
            call(E.cmd_model_apply, "ada")
        self.restart.assert_not_called()
        self.assertEqual(E.load("ada")["model_pending"], "opus")

    def test_off_is_recorded_and_the_next_start_uses_it(self):
        with status(None):
            code, r = call(E.cmd_model, "ada", "fable")
        self.assertEqual((code, r["applied"]), (0, False))
        self.restart.assert_not_called()
        started = []

        def herdr(*a, **k):
            if a[:2] == ("agent", "start"):
                started.append(list(a))
            return {}, None
        with status(None), mock.patch.object(E, "prepare", return_value=E.load("ada")), \
                mock.patch.object(E, "ensure_herdr_server"), mock.patch.object(E, "mem_available_mb", return_value=None), \
                mock.patch.object(E, "new_pane", return_value="p1"), mock.patch.object(E, "follow_newest"), \
                mock.patch.object(E, "herdr", side_effect=herdr), mock.patch.object(E, "mcp_config", return_value="{}"), \
                mock.patch.object(E, "cmd_poll", side_effect=lambda *a: E.out({})):
            call(E.cmd_start, "ada", "{}")
        argv = started[0]
        self.assertEqual(argv[argv.index("--model") + 1], "fable")

    def test_a_bad_name_and_a_question_are_refused(self):
        with status("idle"):
            self.assertEqual(call(E.cmd_model, "ada", "gpt")[0], 2)
            self.assertEqual(call(E.cmd_model, "nobody", "opus")[0], 2)
        with status("blocked"):
            self.assertEqual(call(E.cmd_model, "ada", "opus")[0], 3)
        self.assertNotIn("model", E.load("ada"))
        self.restart.assert_not_called()

    def test_a_turn_begun_meanwhile_leaves_it_pending(self):
        self.restart.return_value = "not idle"
        with status("idle"):
            code, r = call(E.cmd_model, "ada", "sonnet")
        self.assertEqual((code, r["pending"]), (0, True))
        self.assertEqual(E.load("ada")["model_pending"], "sonnet")

    def test_poll_and_list_report_it(self):
        path = os.path.join(TMP, "s-ada.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "content": []}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "content": []}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        st = E.load("ada")
        st.update(model="sonnet", model_pending="sonnet")
        E.save("ada", st)
        with mock.patch.object(E, "transcript", return_value=path), status(None), \
                mock.patch.object(E, "git_info", return_value={}), mock.patch.object(E, "deploy_state", return_value={}), \
                mock.patch.object(E, "preview_of", return_value=""), mock.patch.object(E, "follow_session"):
            _, p = call(E.cmd_poll, "ada", "-1")
            _, lst = call(E.cmd_list)
        row = next(r for r in lst["engineers"] if r["name"] == "ada")
        for r in (p, row):
            self.assertEqual((r["model"], r["model_pending"], r["model_used"]), ("sonnet", "sonnet", "claude-opus-5-5"))

    def test_the_default_is_reported_when_none_was_chosen(self):
        f = E.model_fields("ada", {"session": ""})
        self.assertEqual((f["model"], f["effort"]), (E.MODEL, E.EFFORT))


def start_argv(name):
    """The argv cmd_start hands herdr, everything else stood in for."""
    started = []

    def herdr(*a, **k):
        if a[:2] == ("agent", "start"):
            started.append(list(a))
        return {}, None
    with status(None), mock.patch.object(E, "prepare", return_value=E.load(name)), \
            mock.patch.object(E, "ensure_herdr_server"), mock.patch.object(E, "mem_available_mb", return_value=None), \
            mock.patch.object(E, "new_pane", return_value="p1"), mock.patch.object(E, "follow_newest"), \
            mock.patch.object(E, "herdr", side_effect=herdr), mock.patch.object(E, "mcp_config", return_value="{}"), \
            mock.patch.object(E, "brief", return_value=""), \
            mock.patch.object(E, "cmd_poll", side_effect=lambda *a: E.out({})):
        call(E.cmd_start, name, "{}")
    return started[0]


def flag(argv, f):
    return argv[argv.index(f) + 1]


class Effort(unittest.TestCase):
    def setUp(self):
        os.makedirs(E.STATE, exist_ok=True)
        E.save("ada", {"name": "ada", "session": "s-ada", "title": "Ada"})
        self.restart = mock.patch.object(E, "model_restart", return_value="").start()
        self.addCleanup(mock.patch.stopall)

    def test_the_defaults(self):
        # an engineer: opus, medium; Number One with no model in its state
        # (as it has today): fable, xhigh - with nothing run to get there
        self.assertEqual((E.MODEL, E.EFFORT), ("opus", "medium"))
        E.save(E.NO1, {"name": E.NO1, "session": "s-no1"})
        for name, want in (("ada", ("opus", "medium")), (E.NO1, ("fable", "xhigh"))):
            argv = start_argv(name)
            self.assertEqual((flag(argv, "--model"), flag(argv, "--effort")), want, name)
            f = E.model_fields(name, E.load(name))
            self.assertEqual((f["model"], f["effort"]), want, name)

    def test_the_environment_moves_the_crew_s_not_number_one_s(self):
        E.save(E.NO1, {"name": E.NO1, "session": "s-no1"})
        with mock.patch.object(E, "MODEL", "sonnet"), mock.patch.object(E, "EFFORT", "high"):
            self.assertEqual(E.effort_of("ada", {}), "high")
            self.assertEqual((E.model_of(E.NO1, {}), E.effort_of(E.NO1, {})), ("fable", "xhigh"))
        # LCARS_ENG_EFFORT read at import, like LCARS_ENG_MODEL
        p = subprocess.run([sys.executable, "-c", "import engineer as E; print(E.EFFORT, E.MODEL)"], cwd=HERE,
                           env=dict(os.environ, LCARS_ENG_EFFORT="low", LCARS_ENG_MODEL="haiku"),
                           capture_output=True, text=True)
        self.assertEqual(p.stdout.split(), ["low", "haiku"], p.stderr)

    def test_a_chosen_one_is_passed_and_overrides_number_one_s(self):
        E.save(E.NO1, {"name": E.NO1, "session": "s-no1", "model": "opus", "effort": "high"})
        argv = start_argv(E.NO1)
        self.assertEqual((flag(argv, "--model"), flag(argv, "--effort")), ("opus", "high"))

    def test_idle_is_applied_at_once(self):
        with status("idle"):
            code, r = call(E.cmd_effort, "ada", "high")
        self.assertEqual((code, r["effort"], r["applied"], r["pending"]), (0, "high", True, False))
        self.restart.assert_called_once_with("ada")
        self.assertEqual(E.load("ada")["effort"], "high")
        self.assertEqual(flag(start_argv("ada"), "--effort"), "high")

    def test_working_waits_for_the_turn_s_end(self):
        with status("working"):
            code, r = call(E.cmd_effort, "ada", "xhigh")
        self.assertEqual((code, r["pending"]), (0, True))
        self.restart.assert_not_called()
        self.assertEqual(E.load("ada")["effort_pending"], "xhigh")
        with mock.patch.object(E, "spawn") as sp, mock.patch("sys.stdin", io.StringIO("{}")):
            call(E.cmd_hook, "turn-ended", "ada")
        sp.assert_called_once_with("model-apply", "ada")
        with status("idle"), mock.patch.object(E.time, "sleep"):
            call(E.cmd_model_apply, "ada")
            call(E.cmd_model_apply, "ada")
        self.restart.assert_called_once_with("ada")
        self.assertNotIn("effort_pending", E.load("ada"))

    def test_number_one_s_turn_end_applies_it_too(self):
        E.save(E.NO1, {"name": E.NO1, "session": "s-no1", "effort": "high", "effort_pending": "high"})
        with mock.patch.object(E, "spawn") as sp, mock.patch("sys.stdin", io.StringIO("{}")), \
                mock.patch.object(E, "refresh_pending", return_value=None):
            call(E.cmd_hook, "turn-ended", E.NO1)
        sp.assert_called_once_with("model-apply", E.NO1)

    def test_off_is_recorded(self):
        with status(None):
            code, r = call(E.cmd_effort, "ada", "low")
        self.assertEqual((code, r["applied"]), (0, False))
        self.restart.assert_not_called()
        self.assertEqual(E.load("ada")["effort"], "low")

    def test_a_bad_level_and_a_question_are_refused(self):
        with status("idle"):
            for bad in ("max", "", "HIGH", "opus"):
                self.assertEqual(call(E.cmd_effort, "ada", bad)[0], 2, bad)
            self.assertEqual(call(E.cmd_effort, "nobody", "low")[0], 2)
        with status("blocked"):
            self.assertEqual(call(E.cmd_effort, "ada", "low")[0], 3)
        self.assertNotIn("effort", E.load("ada"))
        self.restart.assert_not_called()

    def test_poll_and_list_report_it(self):
        st = E.load("ada")
        st.update(effort="high", effort_pending="high")
        E.save("ada", st)
        with mock.patch.object(E, "transcript", return_value=None), status(None), \
                mock.patch.object(E, "git_info", return_value={}), mock.patch.object(E, "deploy_state", return_value={}), \
                mock.patch.object(E, "preview_of", return_value=""), mock.patch.object(E, "follow_session"):
            _, p = call(E.cmd_poll, "ada", "-1")
            _, lst = call(E.cmd_list)
        row = next(r for r in lst["engineers"] if r["name"] == "ada")
        for r in (p, row):
            self.assertEqual((r["model"], r["effort"], r["effort_pending"]), ("opus", "high", "high"))

    def test_the_verb_is_dispatched(self):
        self.assertIn("effort", E.VERBS)


class Past(unittest.TestCase):
    """A conversation kept by a clear is read by its session, read-only; a
    session not in their `past` is refused."""

    def setUp(self):
        os.makedirs(E.STATE, exist_ok=True)
        E.save("bo", {"name": "bo", "session": "s-now", "title": "Bo",
                      "past": [{"name": "fix the boiler", "session": "s-old", "at": 1791790895}]})
        self.files = {}
        for sid, said in (("s-now", "the current one"), ("s-old", "the boiler again")):
            self.files[sid] = os.path.join(TMP, sid + ".jsonl")
            with open(self.files[sid], "w") as f:
                f.write(json.dumps({"type": "user", "message": {"content": said}}) + "\n")
        for p in (mock.patch.object(E, "transcript", side_effect=lambda sid: self.files.get(sid)), status("idle"),
                  mock.patch.object(E, "git_info", return_value={}), mock.patch.object(E, "deploy_state", return_value={}),
                  mock.patch.object(E, "preview_of", return_value=""), mock.patch.object(E, "follow_session")):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def said(self, r):
        return [e["t"] for e in r["events"] if e["r"] == "me"]

    def test_the_current_one_lists_the_past(self):
        code, r = call(E.cmd_poll, "bo", "-1")
        self.assertEqual((code, self.said(r), r["viewing"]), (0, ["the current one"], ""))
        self.assertEqual(r["past"], [{"name": "fix the boiler", "session": "s-old", "at": 1791790895}])

    def test_a_past_one_is_read_by_its_session(self):
        code, r = call(E.cmd_poll, "bo", "-1", None, "s-old")
        self.assertEqual((code, self.said(r), r["viewing"], r["session"]), (0, ["the boiler again"], "s-old", "s-now"))

    def test_a_session_not_theirs_is_refused(self):
        for sid in ("s-now", "s-other", "../s-old"):
            code, r = call(E.cmd_poll, "bo", "-1", None, sid)
            self.assertEqual(code, 2, sid)


class Say(unittest.TestCase):
    """say --json, the route's when files come with a message: a line per
    file after the words, with its path on this box and its URL."""

    def setUp(self):
        E.save("ada", {"session": "s-ada"})
        self.typed = []
        self.p = [mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}),
                  mock.patch.object(E, "agent", return_value="pane"),
                  mock.patch.object(E, "submit_if_left"), mock.patch.object(E, "sync_to_base"),
                  mock.patch.object(E, "task_begins"),
                  mock.patch.object(E, "msg_post"),  # the message's row (rooms.md): test_rooms.py's
                  mock.patch.object(E, "herdr", side_effect=lambda *a, **k: (self.typed.append(a[3]), ({}, None))[1]),
                  mock.patch.dict(os.environ, {"LCARS_MEDIA_ROOT": "/mnt/nas", "LCARS_REPORT_BASE": "https://box.ts.net/"})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def say(self, body, flag="--json"):
        with mock.patch("sys.stdin", io.StringIO(body if isinstance(body, str) else json.dumps(body))):
            return call(E.VERBS["say"][0], "ada", flag)

    def test_a_line_per_file_after_the_words(self):
        code, r = self.say({"message": "[No.1] look at these", "attachments": [
            {"path": "media/chat/2026/10/shot-0a1b2c3d.png", "name": "Shot\n1.png", "mime": "image/png",
             "bytes": 2_500_000},
            {"path": "media/chat/2026/10/plan-9f3c1a2b.pdf", "name": "plan.pdf", "mime": "application/pdf",
             "bytes": 812}]})
        self.assertEqual((code, r), (0, {"ok": True}))
        self.assertEqual(self.typed, ["[No.1] look at these\n\n"
                                      "Attached file: /mnt/nas/media/chat/2026/10/shot-0a1b2c3d.png (Shot 1.png, "
                                      "image/png, 2.4 MB) - Read that path; without the media mount, fetch "
                                      "https://box.ts.net/media/chat/2026/10/shot-0a1b2c3d.png with your LCARS API auth\n"
                                      "Attached file: /mnt/nas/media/chat/2026/10/plan-9f3c1a2b.pdf (plan.pdf, "
                                      "application/pdf, 812 bytes) - Read that path; without the media mount, fetch "
                                      "https://box.ts.net/media/chat/2026/10/plan-9f3c1a2b.pdf with your LCARS API auth"])
        # Number One's mark is read from the words, which still lead
        self.assertTrue(E.load("ada").get("under_no1"))

    def test_files_alone_are_a_message(self):
        self.assertEqual(self.say({"message": "", "attachments": [
            {"path": "media/chat/2026/10/a-00000000.txt", "name": "a.txt", "mime": "text/plain", "bytes": 3000}]})[0], 0)
        self.assertTrue(self.typed[0].startswith("Attached file: /mnt/nas/media/chat/2026/10/a-00000000.txt (a.txt, "
                                                 "text/plain, 3 KB)"))

    def test_the_refusals(self):
        for body in ("not json", {"message": "x", "attachments": "media/chat/a"},
                     {"message": "x", "attachments": [{"path": "media/reports/r.html"}]},
                     {"message": "x", "attachments": [{"path": "media/chat/../../etc/passwd"}]},
                     {"message": "", "attachments": []}):
            self.assertEqual(self.say(body)[0], 2, body)
        self.assertEqual(self.typed, [])

    def test_without_the_flag_stdin_is_the_message_as_before(self):
        self.assertEqual(self.say('{"message": "x"}', "")[0], 0)
        self.assertEqual(self.typed, ['{"message": "x"}'])


STUB = """#!/usr/bin/env python3
import json, sys
data = sys.stdin.read()
print(json.dumps(dict({"argv": sys.argv[1:]}, **({"in": data} if data else {}))))
# a thread the script does not know: its exit 4, the route's 404
sys.exit(4 if "nope" in sys.argv or '"nope"' in data else 0)
"""
KEY = "k" * 24
USER = ("t", "t")


@unittest.skipIf(os.environ.get("SKIP_ROUTE") == "1", "SKIP_ROUTE=1")
class Route(unittest.TestCase):
    """POST /engineer/<name>/model (and GET /engineer/queue) on the real
    server, the script a stub."""

    @classmethod
    def setUpClass(cls):
        tmp = pathlib.Path(TMP) / "route"
        tmp.mkdir()
        sys.path.insert(0, os.path.join(HERE, "..", "lcars-ui", "test"))
        from caldav import build, free_port
        binary = os.environ.get("LCARS_TEST_BIN")
        if not binary:
            binary = str(tmp / "lcars")
            build(binary)
        stub = tmp / "engineer.py"
        stub.write_text(STUB)
        stub.chmod(0o755)
        cls.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_AUTH_USER=USER[0], LCARS_AUTH_PASS=USER[1],
                   LCARS_ENGINEER="1", LCARS_ENGINEER_KEY=KEY, LCARS_ENGINEER_SCRIPT=str(stub))
        env.pop("LCARS_ENGINEER_LOGIN", None)
        cls.log = open(tmp / "server.log", "w")
        cls.proc = subprocess.Popen([binary, "--http-only", "--port", str(cls.port)], cwd=tmp, env=env,
                                    stdout=cls.log, stderr=subprocess.STDOUT)
        _procs.append(cls.proc)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": "Basic " + base64.b64encode(f"{USER[0]}:{USER[1]}".encode()).decode(),
             "X-LCARS-Engineer-Key": KEY, "Content-Type": "application/json"}
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        c.close()
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def test_a_model_reaches_the_script_as_argv(self):
        for m in ("sonnet", "haiku", "opus", "fable"):
            st, j = self.req("POST", "/engineer/ada/model", {"model": m})
            self.assertEqual((st, j), (200, {"argv": ["model", "ada", m]}))

    def test_anything_else_is_a_400(self):
        for body in ({"model": "gpt"}, {"model": ""}, {"model": "sonnet; rm"}, {}, {"model": "x" * 40}):
            st, _ = self.req("POST", "/engineer/ada/model", body)
            self.assertEqual(st, 400, body)

    def test_get_is_a_405(self):
        self.assertEqual(self.req("GET", "/engineer/ada/model")[0], 405)

    def test_a_job_cancel_reaches_the_script_as_argv(self):
        """POST /engineer/<name>/job-cancel (the Queue view's Cancel)."""
        st, j = self.req("POST", "/engineer/ada/job-cancel", {"id": "ada-20261021-140200"})
        self.assertEqual((st, j), (200, {"argv": ["job-cancel", "ada", "ada-20261021-140200"]}))
        self.assertEqual(self.req("POST", "/engineer/ada/job-cancel", {})[1], {"argv": ["job-cancel", "ada", ""]})
        for bad in ("x;rm", "../etc", "ADA", "a b"):
            self.assertEqual(self.req("POST", "/engineer/ada/job-cancel", {"id": bad})[0], 400, bad)
        self.assertEqual(self.req("GET", "/engineer/ada/job-cancel")[0], 405)

    def test_past_reaches_the_poll_as_argv(self):
        st, j = self.req("GET", "/engineer/ada?off=-1&past=0a1b-c2d3")
        self.assertEqual((st, j), (200, {"argv": ["poll", "ada", "-1", "-1", "0a1b-c2d3", "-"]}))
        self.assertEqual(self.req("GET", "/engineer/ada?off=5")[1], {"argv": ["poll", "ada", "5", "-1", "-", "-"]})
        for bad in ("x;rm", "..%2Fetc", "ABC"):
            self.assertEqual(self.req("GET", "/engineer/ada?past=" + bad)[0], 400, bad)

    def test_number_one_s_threads_reach_the_script(self):
        # no1-threads.md, section 13: the poll's thread= (a filter), the say's
        # thread, the chips' POST .../thread (its body on stdin), exit 4 a 404
        self.assertEqual(self.req("GET", "/engineer/number-one?off=-1&thread=deck")[1],
                         {"argv": ["poll", "number-one", "-1", "-1", "-", "deck"]})
        self.assertEqual(self.req("GET", "/engineer/number-one?off=-1&thread=nope")[0], 404)
        for bad in ("Deck", "a;b", "x" * 25, "-x", "9a"):
            self.assertEqual(self.req("GET", "/engineer/number-one?thread=" + bad)[0], 400, bad)
        st, j = self.req("POST", "/engineer/number-one/say", {"message": "hi", "thread": "deck"})
        self.assertEqual((st, j), (200, {"argv": ["say", "number-one", "--thread", "deck"], "in": "hi"}))
        self.assertEqual(self.req("POST", "/engineer/number-one/say", {"message": "hi"})[1],
                         {"argv": ["say", "number-one"], "in": "hi"})
        self.assertEqual(self.req("POST", "/engineer/number-one/say", {"message": "hi", "thread": ""})[1],
                         {"argv": ["say", "number-one"], "in": "hi"})
        self.assertEqual(self.req("POST", "/engineer/number-one/say", {"message": "hi", "thread": "nope"})[0], 404)
        for bad in ("Deck", "a b", "x" * 30):
            self.assertEqual(self.req("POST", "/engineer/number-one/say", {"message": "hi", "thread": bad})[0], 400, bad)
        body = {"op": "new", "id": "web", "name": "Web app"}
        st, j = self.req("POST", "/engineer/number-one/thread", body)
        self.assertEqual((st, j["argv"], json.loads(j["in"])), (200, ["thread-req", "number-one"], body))
        self.assertEqual(self.req("POST", "/engineer/number-one/thread", {"op": "rename", "id": "nope", "name": "x"})[0], 404)
        self.assertEqual(self.req("GET", "/engineer/number-one/thread")[0], 405)

    def test_the_queue_is_its_own_read_only_route(self):
        # the Queue view's (engineer.py queue), never a poll of one called queue
        self.assertEqual(self.req("GET", "/engineer/queue"), (200, {"argv": ["queue"]}))
        self.assertEqual(self.req("POST", "/engineer/queue")[0], 405)

    def test_the_queue_s_edits_reach_the_script_as_argv(self):
        st, j = self.req("POST", "/engineer/queue/move", {"name": "ada", "to": "up", "expect": "bob,ada,crew:ops"})
        self.assertEqual((st, j), (200, {"argv": ["queue-move", "ada", "up", "bob,ada,crew:ops"]}))
        st, j = self.req("POST", "/engineer/queue/remove", {"name": "ada", "expect": "bob,ada"})
        self.assertEqual((st, j), (200, {"argv": ["queue-remove", "ada", "bob,ada"]}))
        self.assertEqual(self.req("POST", "/engineer/queue/restore", {}), (200, {"argv": ["queue-restore", ""]}))
        self.assertEqual(self.req("POST", "/engineer/queue/restore", {"name": "ada"})[1],
                         {"argv": ["queue-restore", "ada"]})
        for path, body in (("move", {"name": "ada"}), ("move", {"name": "a;b", "to": "up"}),
                           ("remove", {}), ("remove", {"name": "ada,bob"}), ("remove", {"name": "ADA"}),
                           ("remove", {"name": "ada", "expect": "x y"})):
            self.assertEqual(self.req("POST", "/engineer/queue/" + path, body)[0], 400, (path, body))
        self.assertEqual(self.req("GET", "/engineer/queue/move")[0], 405)
        self.assertEqual(self.req("POST", "/engineer/queue/drop", {"name": "ada"})[0], 404)


if __name__ == "__main__":
    unittest.main()
