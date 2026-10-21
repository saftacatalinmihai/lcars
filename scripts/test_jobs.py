#!/usr/bin/env python3
"""Tests for the job queue (docs/design/job-queue.md): the decisions in
scripts/seat.py ("the job line") and engineer.py's verbs and runner. No
herdr, no systemd, no live journal: a stand-in server keeps the entries in
memory, STATE and the worktree are scratch, and a job's `job-run` is a
child process (LCARS_JOB_RUNNER=direct) that starts nothing else on the box
(LCARS_ENG_SPAWN=0).

    python3 scripts/test_jobs.py      (~15s)
"""

import atexit
import contextlib
import http.server
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import warnings
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lcars-ui", "test"))
import killclean  # noqa: E402 - the scratch goes with a killed run

TMP = killclean.mkdtemp("jobs-test-")
atexit.register(shutil.rmtree, TMP, True)
with open(os.path.join(TMP, "env"), "w") as f:
    f.write("LCARS_CREW_USER=crew\nLCARS_CREW_PASS=pass\n")
# before engineer.py loads: these are read when it does, and every child
# (job-run) inherits them
os.environ.update(LCARS_CREW_ENV=os.path.join(TMP, "env"), LCARS_ENG_STATE=os.path.join(TMP, "state"),
                  LCARS_ENG_ROOT=os.path.join(TMP, "eng"), LCARS_SEAT_SLICE_MIN="30", LCARS_JOB_RUNNER="direct",
                  LCARS_ENG_SPAWN="0", LCARS_ENG_MIN_FREE_MB="0")
os.environ.pop("LCARS_ENG_SEAT", None)
import crew_tool as T  # noqa: E402
import seat as S  # noqa: E402
import engineer as E  # noqa: E402
import crew as C  # noqa: E402

M = 60
# a direct runner's child is left running on purpose (it is the job): not a leak
warnings.simplefilter("ignore", ResourceWarning)


def journal_http(method, path, body=None):
    """seat._http as it is (testguard replaced it), against LCARS_URL - the
    stand-in's, set by each test that has one."""
    status, text = T.http(method, path, body, timeout=20)
    if status == 0 or status >= 500:
        raise S.Down(f"{method} {path}: {status or text[:200]}")
    if status >= 300:
        raise RuntimeError(f"{method} {path}: {status}")
    return json.loads(text) if text else None


class Journal:
    """A stand-in LCARS server (test_seat's): GET/POST/PUT /entries in memory."""

    def __init__(self):
        self.rows, self.down = [], False
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body):
                b = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def body(self):
                return json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")

            def do_GET(self):
                if outer.down:
                    return self.reply(503, {"error": "restarting"})
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                rows = [r for r in outer.rows if r["kind"] == q.get("kind", r["kind"])
                        and ("done" not in q or r["done_bool"] == int(q["done"]))]
                rows.sort(key=lambda r: r["id"], reverse=q.get("dir") != "asc")
                return self.reply(200, rows[:int(q.get("limit", 100))])

            def do_POST(self):
                if outer.down:
                    return self.reply(503, {"error": "restarting"})
                b = self.body()
                r = {"id": len(outer.rows) + 1, "kind": b["kind"], "title": b.get("title", ""),
                     "content": b.get("content", ""), "done_bool": 0, "deleted": 0}
                outer.rows.append(r)
                return self.reply(201, r)

            def do_PUT(self):
                if outer.down:
                    return self.reply(503, {"error": "restarting"})
                rid = int(self.path.rsplit("/", 1)[1])
                r = next(x for x in outer.rows if x["id"] == rid)
                r.update(self.body())
                return self.reply(200, r)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def inbox(self, to):
        return [r for r in self.rows if r["kind"] == "crew_inbox" and r["title"].startswith(to + " ← ")]


def job(name="ada", jid=None, label="run.sh", timeout=1200):
    return {"id": jid or name + "-1", "name": name, "cmd": "true", "label": label, "wt": "/x", "head": "h",
            "tree": "t", "timeout": timeout}


def queued(s):
    return [e["name"] for e in s["queue"]]


class Decisions(unittest.TestCase):
    """seat.py's job line: pure."""

    def setUp(self):
        self.t = 1_000_000
        self.s = S.empty()
        self.s["holder"] = {"name": "ada", "since": self.t, "by": "start"}

    def test_inline_when_nobody_waits_and_no_job_is_busy(self):
        self.assertEqual(S.job_submit(self.s, job(), self.t), "inline")
        r = self.s["jobs"]["running"]
        self.assertTrue(r["inline"])
        self.assertEqual(r["started"], self.t)
        self.assertFalse(self.s["holder"].get("yielded"))

    def test_queued_when_someone_waits_for_the_seat(self):
        S.want(self.s, "bob", "no1", self.t)
        self.assertEqual(S.job_submit(self.s, job(), self.t), "queued")
        self.assertIsNone(self.s["jobs"]["running"])
        self.assertTrue(self.s["jobs"]["queue"][0]["hold"])
        self.assertTrue(self.s["holder"]["yielded"])
        # the seat passes when the turn ends: ada stopped, bob started
        S.turn_ended(self.s, "ada", self.t + 5)
        s, acts = S.step(self.s, {"ada": "idle"}, self.t + 6)
        self.assertEqual(acts, [("stop", "ada"), ("start", "bob")])

    def test_queued_when_a_job_runs_though_nobody_waits(self):
        self.s["jobs"]["running"] = dict(job("bob"), started=self.t)
        self.assertEqual(S.job_submit(self.s, job(), self.t), "queued")
        self.assertEqual(S.job_find(self.s, "ada")[1], 1)

    def test_one_at_a_time(self):
        self.s["jobs"]["running"] = dict(job("bob"), started=self.t)
        self.s["jobs"]["queue"].append(job())
        x, why = S.job_next(self.s, {}, self.t)
        self.assertIsNone(x)
        self.assertIn("bob", why)

    def test_a_held_job_waits_for_its_submitter_s_turn(self):
        S.want(self.s, "bob", "no1", self.t)
        S.job_submit(self.s, job(), self.t)
        self.assertEqual(S.job_next(self.s, {"ada": "working"}, self.t)[0], None)
        # the Stop hook lost: reap's move sees them idle, or gone
        self.assertEqual(S.job_next(self.s, {"ada": "idle"}, self.t)[0]["id"], "ada-1")
        self.assertEqual(S.job_next(self.s, {}, self.t)[0]["id"], "ada-1")
        # the hook's word: released
        S.turn_ended(self.s, "ada", self.t)
        self.assertEqual(S.job_next(self.s, {"ada": "working"}, self.t)[0]["id"], "ada-1")

    def test_a_held_job_does_not_block_the_one_behind_it(self):
        self.s["jobs"]["queue"] = [dict(job(), hold=True), job("bob", "bob-1")]
        self.assertEqual(S.job_next(self.s, {"ada": "working"}, self.t)[0]["id"], "bob-1")

    def test_a_deploy_and_short_memory_hold_the_line(self):
        self.s["jobs"]["queue"] = [job()]
        self.assertEqual(S.job_next(self.s, {}, self.t, deploying=True), (None, "a deploy has the cores first"))
        self.assertEqual(S.job_next(self.s, {}, self.t, mem_ok=False), (None, "waiting for memory"))
        x, _ = S.job_next(self.s, {}, self.t)
        S.job_started(self.s, x["id"], self.t, "lcars-job-ada-1")
        self.assertEqual(self.s["jobs"]["running"]["unit"], "lcars-job-ada-1")
        self.assertEqual(self.s["jobs"]["queue"], [])

    def test_a_result_goes_to_the_head_of_the_line(self):
        self.s["holder"] = {"name": "cy", "since": self.t, "by": "start"}
        S.want(self.s, "bob", "no1", self.t)
        self.s["jobs"]["running"] = dict(job(), started=self.t)
        S.job_done(self.s, "ada-1", "passed", self.t + M)
        self.assertEqual(queued(self.s), ["ada", "bob"])
        self.assertEqual(self.s["queue"][0]["by"], "job")
        self.assertEqual(self.s["jobs"]["recent"][-1]["outcome"], "passed")

    def test_behind_the_captain_and_an_earlier_result(self):
        self.s["holder"] = {"name": "cy", "since": self.t, "by": "start"}
        S.want(self.s, "bob", "no1", self.t)
        S.want(self.s, "dee", "captain", self.t)
        S.job_back(self.s, "eve", self.t)
        S.job_back(self.s, "ada", self.t)
        self.assertEqual(queued(self.s), ["dee", "eve", "ada", "bob"])
        # the captain's later word still goes in front of them
        S.want(self.s, "fay", "captain", self.t)
        self.assertEqual(queued(self.s)[0], "fay")

    def test_behind_anyone_who_has_waited_the_slice(self):
        self.s["holder"] = {"name": "cy", "since": self.t, "by": "start"}
        S.want(self.s, "bob", "no1", self.t - 31 * M)
        S.want(self.s, "dee", "no1", self.t - 5 * M)
        S.job_back(self.s, "ada", self.t)
        self.assertEqual(queued(self.s), ["bob", "ada", "dee"])

    def test_nothing_when_they_hold_the_seat(self):
        S.job_back(self.s, "ada", self.t)
        self.assertEqual(self.s["queue"], [])

    def test_cancelled_queues_nobody_and_done_twice_is_nothing(self):
        S.want(self.s, "bob", "no1", self.t)
        S.job_submit(self.s, job(), self.t)
        self.assertIsNotNone(S.job_done(self.s, "ada-1", "cancelled", self.t, back=False))
        self.assertEqual(queued(self.s), ["bob"])
        self.assertIsNone(S.job_done(self.s, "ada-1", "passed", self.t))

    def test_the_block_reads_back_and_bad_jobs_are_dropped(self):
        S.want(self.s, "bob", "no1", self.t)
        S.job_submit(self.s, job(), self.t)
        title, content = S.render(self.s, self.t)
        self.assertIn("**Jobs queued:** 1. ada, run.sh (turn not over)", content)
        back = S.normal(json.loads(S.BLOCK_RE.findall(content)[-1]))
        self.assertEqual(back["jobs"]["queue"][0]["id"], "ada-1")
        back = S.normal({"jobs": {"running": {"name": "x"}, "queue": [job(), job(), "junk"]}})
        self.assertIsNone(back["jobs"]["running"])
        self.assertEqual(len(back["jobs"]["queue"]), 1)
        self.assertEqual(S.normal({})["jobs"], S.jobs_empty())


class Heavy(unittest.TestCase):
    def test_heavy(self):
        for cmd, what in (("lcars-ui/test/run.sh", "run.sh"), ("PERF=0 sh lcars-ui/test/run.sh", "run.sh"),
                          ("cd x && python3 lcars-ui/test/perf.py --fresh", "perf.py"),
                          ("timeout 600 python3 test/buttons.py 2>&1 | tail", "buttons.py"),
                          ("python3 lcars-ui/test/qa_chat.py", "qa_chat.py"), ("make lcars-release", "make lcars-release"),
                          ("make SANITIZE=0 lcars-one", "make lcars-one"), ("bash scripts/deck-models/build.sh rooms",
                                                                            "scripts/deck-models/build.sh"),
                          ("python3 lcars-ui/test/deckshots.py", "deckshots.py"), ("KB_JOBS=1 python3 test/keyboard.py",
                                                                                   "keyboard.py")):
            self.assertEqual(E.heavy_command(cmd), what, cmd)

    def test_light(self):
        for cmd in ("make check", "make lcars", "make lcars-cli", "lcars-ui/test/run.sh --changed",
                    "python3 lcars-ui/test/back.py", "python3 scripts/test_seat.py", "git log | head",
                    "scripts/engineer.py job obrien -- lcars-ui/test/run.sh",
                    "/usr/bin/python3 /srv/x/engineer.py job a -- make lcars-release",
                    "cat > x.py <<'EOF'\npython3 test/buttons.py\nEOF"):
            self.assertEqual(E.heavy_command(cmd), "", cmd)

    def test_the_deny_message(self):
        msg = E.HEAVY_DENY.format(what="run.sh", eng="scripts/engineer.py", name="ada")
        self.assertIn("scripts/engineer.py job ada -- <the command>", msg)

    def test_the_hook_is_wired(self):
        """slice 3: crew_settings' PreToolUse hook on Bash runs heavy-check,
        never for Number One or with the seat off; heavy_check's answers."""
        pre = E.crew_settings("ada")["hooks"]["PreToolUse"]
        self.assertEqual(pre[0]["matcher"], "Bash")
        self.assertTrue(pre[0]["hooks"][0]["command"].endswith("engineer.py heavy-check ada"), pre)
        self.assertNotIn("PreToolUse", E.no1_settings()["hooks"])
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"}):
            self.assertNotIn("PreToolUse", E.crew_settings("ada")["hooks"])
        call = lambda cmd, tool="Bash": {"tool_name": tool, "tool_input": {"command": cmd}}
        d = E.heavy_check("ada", call("cd lcars-ui/test && ./run.sh"))["hookSpecificOutput"]
        self.assertEqual((d["hookEventName"], d["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("run.sh is a heavy command: run it as `", d["permissionDecisionReason"])
        self.assertIn("scripts/engineer.py job ada -- <the command>`", d["permissionDecisionReason"])
        for light in ("/srv/x/scripts/engineer.py job ada -- lcars-ui/test/run.sh", "make check",
                      "lcars-ui/test/run.sh --changed", "scripts/engineer.py yield ada"):
            self.assertIsNone(E.heavy_check("ada", call(light)), light)
        self.assertIsNone(E.heavy_check("ada", call("run.sh", tool="Read")))
        self.assertIsNone(E.heavy_check(E.NO1, call("lcars-ui/test/run.sh")))
        # the verb: stdin in, the deny printed or nothing; garbage fails open
        me = os.path.join(HERE, "engineer.py")
        p = subprocess.run([sys.executable, me, "heavy-check", "ada"], input=json.dumps(call("make lcars-one")),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((p.returncode, json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]), (0, "deny"))
        for inp in (json.dumps(call("git status")), "not json", ""):
            p = subprocess.run([sys.executable, me, "heavy-check", "ada"], input=inp, capture_output=True, text=True, timeout=30)
            self.assertEqual((p.returncode, p.stdout), (0, ""), inp)


class Runner(unittest.TestCase):
    """engineer.py's verbs against the stand-in, in a scratch git worktree."""

    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # (unittest resets the filters per run)
        self.j = Journal()
        os.environ["LCARS_URL"] = self.j.url
        shutil.rmtree(E.STATE, ignore_errors=True)
        os.makedirs(E.STATE)
        self.runs = []
        real_launch = E.job_launch

        def launch(x):
            unit = real_launch(x)
            self.runs.append(int(unit.split(":")[1]))
            return unit

        self.p = [mock.patch.object(E, "job_launch", launch),
                  mock.patch.object(S, "_http", journal_http), mock.patch.object(E, "agent_info", return_value=None),
                  mock.patch.object(E, "engineer_tab", return_value=None), mock.patch.object(E, "seat_move_later"),
                  mock.patch.object(E, "spawn", return_value="off")]
        for p in self.p:
            p.start()
        for n in ("ada", "bob"):
            E.save(n, {"name": n, "session": "s-" + n, "title": n.title()})
        d = E.wt("ada")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        self.git("init", "-q", "-b", "deb")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.commit("a")
        self.seat("ada")

    def tearDown(self):
        # every job-run this test started has ended (a cancelled one reports
        # first) before the stand-in goes, or it would retry into nothing
        for pid in self.runs:
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                with contextlib.suppress(ChildProcessError):
                    if os.waitpid(pid, os.WNOHANG)[0]:
                        break
                time.sleep(0.1)
            else:
                with contextlib.suppress(OSError):
                    os.killpg(pid, signal.SIGKILL)
        for p in self.p:
            p.stop()
        self.j.httpd.shutdown()
        self.j.httpd.server_close()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=E.wt("ada"), check=True, capture_output=True, text=True).stdout

    def commit(self, f):
        with open(os.path.join(E.wt("ada"), f), "w") as fh:
            fh.write(f)
        self.git("add", f)
        self.git("commit", "-qm", f)

    def seat(self, name, queue=()):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": name, "since": int(time.time()), "by": "start"}
            for q in queue:
                S.want(s, q, "no1", time.time())

    def pass_seat(self):
        """ada's turn over and the seat gone to bob, as the move does."""
        with S.changing(E.STATE) as s:
            S.turn_ended(s, "ada", time.time())
            s["holder"] = {"name": "bob", "since": int(time.time()), "by": "no1"}
            s["queue"] = []

    def state(self):
        with S.locked(E.STATE):
            return S.read()[1]

    def call(self, fn, *a):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            fn(*a)
        text = buf.getvalue()
        return cm.exception.code or 0, json.loads(text.strip().splitlines()[-1]), text

    def submit(self, *cmd, opts=()):
        return self.call(E.cmd_job, "ada", *opts, "--", *cmd)

    def finish(self, secs=30):
        """Release the held job (the turn over), dispatch, and wait for the
        child to settle it."""
        with S.changing(E.STATE) as s:
            S.job_release(s, "ada")
        E.job_dispatch()
        end = time.time() + secs
        while time.time() < end:
            s = self.state()
            if not s["jobs"]["running"] and not s["jobs"]["queue"]:
                return s
            time.sleep(0.2)
        self.fail("the job did not finish: " + json.dumps(s["jobs"]))

    def message(self):
        rows = self.j.inbox("ada")
        self.assertEqual(len(rows), 1, [r["title"] for r in rows])
        return rows[0]["content"]

    def test_inline_streams_and_returns_its_exit_code(self):
        seen = {}
        real = E.job_exec

        def exec_(jb, log, tee=False):
            seen["running"] = self.state()["jobs"]["running"]
            return real(jb, log, tee)

        with mock.patch.object(E, "job_exec", exec_):
            code, res, text = self.submit("echo hello; exit 3")
        self.assertEqual(code, 3)
        self.assertIn("hello", text)
        self.assertEqual((res["outcome"], res["exit"]), ("failed", 3))
        self.assertTrue(seen["running"]["inline"])
        s = self.state()
        self.assertIsNone(s["jobs"]["running"])
        self.assertEqual(s["jobs"]["recent"][-1]["outcome"], "failed")
        self.assertEqual(self.j.inbox("ada"), [])  # their own turn: nothing typed
        self.assertEqual(s["queue"], [])

    def test_queued_then_run_and_reported_at_the_head(self):
        self.seat("ada", ["bob"])
        code, res, _ = self.submit("echo one; echo two", opts=("--label", "the suite"))
        self.assertEqual(code, 0)
        self.assertEqual(res["place"], 1)
        s = self.state()
        self.assertTrue(s["holder"]["yielded"])
        # not before the turn is over
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}):
            E.job_dispatch()
        self.assertEqual(self.state()["jobs"]["queue"][0]["id"], res["queued"])
        # the turn ends, the seat passes to bob, the job runs
        with S.changing(E.STATE) as s:
            S.turn_ended(s, "ada", time.time())
            s["holder"] = {"name": "bob", "since": int(time.time()), "by": "no1"}
            s["queue"] = []
            S.want(s, "cy", "no1", time.time())
        s = self.finish()
        self.assertEqual(s["queue"][0], dict(s["queue"][0], name="ada", by="job"))
        self.assertEqual([e["name"] for e in s["queue"]], ["ada", "cy"])
        msg = self.message()
        self.assertRegex(msg, r"^\[job\] the suite: PASSED \(exit 0\) in \d+s on [0-9a-f]{7}\. Log: ")
        self.assertIn("one\ntwo", msg)
        self.assertEqual(self.j.inbox("ada")[0]["title"].split(":")[0], "ada ← job")

    def test_one_job_each(self):
        self.seat("ada", ["bob"])
        self.submit("true")
        code, res, _ = self.submit("true")
        self.assertEqual(code, 2)
        self.assertIn("in the line already", res["error"])

    def test_a_failure_and_a_huge_log(self):
        self.seat("ada", ["bob"])
        self.submit("echo 'FAIL early thing'; head -c 10000000 /dev/zero | tr '\\0' 'x' | fold -w 100; exit 4")
        self.finish()
        msg = self.message()
        self.assertIn("FAILED (exit 4)", msg)
        self.assertIn("FAIL early thing", msg)
        self.assertLess(len(msg), 4000)
        log = msg.split("Log: ")[1].split("\n")[0]
        self.assertGreater(os.path.getsize(log), 10_000_000)

    def test_a_timeout(self):
        self.seat("ada", ["bob"])
        self.submit("sleep 60")
        with S.changing(E.STATE) as s:
            s["jobs"]["queue"][0]["timeout"] = 1
        t0 = time.time()
        self.finish(60)
        self.assertLess(time.time() - t0, 30)
        self.assertIn("FAILED (timeout after 0m)", self.message())

    def test_head_moved_is_refused_and_requeued(self):
        self.seat("ada", ["bob"])
        self.submit("echo ran")
        self.commit("b")
        self.pass_seat()
        s = self.finish()
        self.assertEqual((s["queue"][0]["name"], s["queue"][0]["by"]), ("ada", "job"))
        msg = self.message()
        self.assertIn("NOT RUN - the tree moved since you submitted it (HEAD", msg)
        self.assertEqual(s["jobs"]["recent"][-1]["outcome"], "refused")

    def test_an_uncommitted_change_is_refused(self):
        self.seat("ada", ["bob"])
        self.submit("echo ran")
        with open(os.path.join(E.wt("ada"), "a"), "w") as f:
            f.write("edited")
        self.finish()
        self.assertIn("NOT RUN - the tree changed since you submitted it", self.message())

    def test_a_deploy_holds_the_line(self):
        self.seat("ada", ["bob"])
        self.submit("true")
        E.set_deploy(state="queued", verb="deploy", name="bob", started=int(time.time()))
        with S.changing(E.STATE) as s:
            S.job_release(s, "ada")
        s = E.job_dispatch()
        self.assertEqual(len(s["jobs"]["queue"]), 1)
        self.assertEqual(s["jobs"]["note"], "a deploy has the cores first")
        E.set_deploy(state="done")
        self.finish()

    def test_the_cores_are_one_at_a_time(self):
        waited = []
        with E.cores(who="deploy"):
            t = threading.Thread(target=lambda: E.cores(waited.append, "x").__enter__())
            t.start()
            t.join(0.5)
            self.assertTrue(t.is_alive())
        t.join(5)
        self.assertEqual(waited, ["deploy"])

    def test_a_runner_that_died_is_reported(self):
        self.seat("ada", ["bob"])
        self.submit("sleep 60")
        self.pass_seat()
        s = E.job_dispatch()
        unit = s["jobs"]["running"]["unit"]
        pid = int(unit.split(":")[1])
        jid = s["jobs"]["running"]["id"]
        for _ in range(100):  # the run's child started
            if os.path.exists(E.job_file(jid, "pid")):
                break
            time.sleep(0.1)
        time.sleep(0.3)
        with open(E.job_file(jid, "pid")) as f:
            child = int(f.read())
        os.killpg(pid, signal.SIGKILL)  # the OOM killer, a reboot
        os.killpg(child, signal.SIGKILL)
        time.sleep(0.3)
        with mock.patch.object(E, "JOB_GRACE", 0):
            s = E.job_dispatch()
        self.assertIsNone(s["jobs"]["running"])
        self.assertIn("FAILED - its run stopped without finishing (its process is gone)", self.message())
        self.assertEqual(self.state()["queue"][0]["name"], "ada")

    def test_cancel_and_dismiss(self):
        self.seat("ada", ["bob"])
        self.submit("true")
        code, res, _ = self.call(E.cmd_job_cancel, "ada")
        self.assertEqual((code, res["was"]), (0, 1))
        self.assertFalse(self.state()["jobs"]["queue"])
        self.seat("ada", ["bob"])
        self.submit("true")
        self.call(E.cmd_dismiss, "ada", False)
        s = self.state()
        self.assertFalse(s["jobs"]["queue"])
        self.assertEqual(s["jobs"]["recent"][-1]["outcome"], "cancelled")
        self.assertEqual(self.j.inbox("ada"), [])

    def test_cancel_a_running_job(self):
        self.seat("ada", ["bob"])
        self.submit("sleep 60")
        with S.changing(E.STATE) as s:
            S.job_release(s, "ada")
        E.job_dispatch()
        jid = self.state()["jobs"]["running"]["id"]
        for _ in range(100):
            if os.path.exists(E.job_file(jid, "pid")):
                break
            time.sleep(0.1)
        code, res, _ = self.call(E.cmd_job_cancel, "ada")
        self.assertEqual(res["was"], "running")
        s = self.state()
        self.assertIsNone(s["jobs"]["running"])
        self.assertEqual(s["jobs"]["recent"][-1]["outcome"], "cancelled")

    def test_not_seated_and_number_one_are_refused(self):
        self.seat("bob")
        code, res, _ = self.submit("true")
        self.assertEqual(code, 2)
        self.assertIn("not in the seat", res["error"])
        code, res, _ = self.call(E.cmd_job, E.NO1, "--", "true")
        self.assertIn("Number One runs no jobs", res["error"])
        code, res, _ = self.call(E.cmd_job, "ada", "true")
        self.assertIn("usage", res["error"])

    def test_no_seat_here_runs_inline(self):
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"}):
            code, res, text = self.submit("echo here")
        self.assertEqual((code, res["outcome"]), (0, "passed"))
        self.assertIn("here", text)


class Crew(unittest.TestCase):
    def test_a_heavy_role_takes_the_cores_and_others_do_not(self):
        fm = C.parse_role(open(os.path.join(os.path.dirname(HERE), "crew", "qa.md")).read(), "qa")[0]
        self.assertEqual(fm["heavy"], "true")
        with mock.patch.object(E, "cores") as c:
            C.cores_for(fm, "qa")
            c.assert_called_once()
            self.assertEqual(c.call_args[0][1], "crew:qa")
            c.reset_mock()
            C.cores_for(dict(fm, heavy=""), "ops")
            with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"}):
                C.cores_for(fm, "qa")
            c.assert_not_called()

    def test_a_stale_queued_deploy_holds_nothing(self):
        ds = {"state": "queued", "started": int(time.time()) - 700}
        with mock.patch.object(E, "deploy_state", return_value=ds), mock.patch.object(S, "_http", journal_http):
            j = Journal()
            os.environ["LCARS_URL"] = j.url
            try:
                with S.changing(E.STATE) as s:
                    s["jobs"]["queue"].append(dict(job("zed", "zed-1"), wt="/nonexistent"))
                with mock.patch.object(E, "job_launch", return_value="pid:1") as launch:
                    E.job_dispatch()
                launch.assert_called_once()
            finally:
                j.httpd.shutdown()
                j.httpd.server_close()


if __name__ == "__main__":
    unittest.main()
