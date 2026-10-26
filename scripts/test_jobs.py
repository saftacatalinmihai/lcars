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
import fcntl
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
        r = self.s["jobs"]["running"][0]
        self.assertTrue(r["inline"])
        self.assertEqual(r["started"], self.t)
        self.assertFalse(self.s["holder"].get("yielded"))

    def test_queued_when_someone_waits_for_the_seat(self):
        S.want(self.s, "bob", "no1", self.t)
        self.assertEqual(S.job_submit(self.s, job(), self.t), "queued")
        self.assertEqual(self.s["jobs"]["running"], [])
        self.assertTrue(self.s["jobs"]["queue"][0]["hold"])
        self.assertTrue(self.s["holder"]["yielded"])
        # the seat passes when the turn ends: ada stopped, bob started
        S.turn_ended(self.s, "ada", self.t + 5)
        s, acts = S.step(self.s, {"ada": "idle"}, self.t + 6)
        self.assertEqual(acts, [("stop", "ada"), ("start", "bob")])

    def test_queued_when_a_job_runs_though_nobody_waits(self):
        self.s["jobs"]["running"] = [dict(job("bob"), started=self.t)]
        self.assertEqual(S.job_submit(self.s, job(), self.t), "queued")
        self.assertEqual(S.job_find(self.s, "ada")[1], 1)

    def test_one_at_a_time(self):
        self.s["jobs"]["running"] = [dict(job("bob"), started=self.t)]
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
        self.assertEqual(self.s["jobs"]["running"][0]["unit"], "lcars-job-ada-1")
        self.assertEqual(self.s["jobs"]["queue"], [])

    def test_a_result_goes_to_the_head_of_the_line(self):
        self.s["holder"] = {"name": "cy", "since": self.t, "by": "start"}
        S.want(self.s, "bob", "no1", self.t)
        self.s["jobs"]["running"] = [dict(job(), started=self.t)]
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
        self.assertEqual(back["jobs"]["running"], [])
        self.assertEqual(len(back["jobs"]["queue"]), 1)
        # one running job, as the block held it before 0.298.6
        back = S.normal({"jobs": {"running": dict(job(), started=self.t)}})
        self.assertEqual([x["id"] for x in back["jobs"]["running"]], ["ada-1"])
        self.assertEqual(S.normal({})["jobs"], S.jobs_empty())


GOOD = {"avail_mb": 6000, "cpu_psi": 5.0, "mem_psi": 0.0, "swapin_kbs": 0.0}


def cjob(name, cls, **kw):
    return dict(job(name, name + "-1"), cls=cls, **kw)


class MoreThanOne(unittest.TestCase):
    """The job side of "More than one": seat.py's job_limit and job_next
    over a list of running jobs, the readings fed in."""

    def setUp(self):
        self.t = 1_000_000
        self.s = S.empty()
        S.job_limit(self.s, GOOD, self.t, 2)

    def run_(self, *xs):
        self.s["jobs"]["running"] = [dict(x, started=self.t - 600) for x in xs]

    def nxt(self, r=GOOD, **kw):
        return S.job_next(self.s, {}, self.t, r=r, **kw)

    def test_two_shared_together(self):
        self.run_(cjob("bob", "browser"))
        self.s["jobs"]["queue"] = [cjob("ada", "parallel")]
        self.assertEqual(self.nxt()[0]["id"], "ada-1")
        S.job_started(self.s, "ada-1", self.t, "u")
        self.assertEqual([x["name"] for x in self.s["jobs"]["running"]], ["bob", "ada"])
        # the limit reached: a third waits
        self.s["jobs"]["queue"] = [cjob("cy", "build")]
        x, why = self.nxt()
        self.assertIsNone(x)
        self.assertIn("bob, ada's jobs are running", why)

    def test_an_exclusive_head_holds_a_shared_one_behind_it(self):
        self.run_(cjob("bob", "browser"))
        self.s["jobs"]["queue"] = [cjob("ada", "exclusive"), cjob("cy", "browser")]
        x, why = self.nxt()
        self.assertIsNone(x)
        self.assertIn("ada's runs alone", why)
        # a job of before the classes (no cls) runs alone too
        self.s["jobs"]["queue"] = [job("ada"), cjob("cy", "browser")]
        self.assertIsNone(self.nxt()[0])
        # and with nothing running, the exclusive head starts, then holds the rest
        self.s["jobs"]["running"] = []
        self.assertEqual(self.nxt()[0]["id"], "ada-1")
        S.job_started(self.s, "ada-1", self.t, "u")
        x, why = self.nxt()
        self.assertIsNone(x)
        self.assertIn("ada's job runs alone", why)

    def test_a_held_job_does_not_block_the_shared_one_behind_it(self):
        self.run_(cjob("bob", "browser"))
        self.s["jobs"]["queue"] = [cjob("ada", "exclusive", hold=True), cjob("cy", "browser")]
        self.assertEqual(S.job_next(self.s, {"ada": "working"}, self.t, r=GOOD)[0]["id"], "cy-1")

    def test_a_deploy_holds_both(self):
        self.s["jobs"]["queue"] = [cjob("ada", "browser")]
        self.assertEqual(self.nxt(deploying=True), (None, "a deploy has the cores first"))
        self.run_(cjob("bob", "browser"))
        self.assertEqual(self.nxt(deploying=True), (None, "a deploy has the cores first"))

    def test_the_cores_add_up(self):
        self.run_(cjob("bob", "parallel"))
        self.s["jobs"]["queue"] = [cjob("ada", "parallel")]
        self.assertEqual(self.nxt()[0]["id"], "ada-1")  # 2 + 2 = 4
        with mock.patch.object(S, "JOB_CORES", 3):
            self.assertIn("no cores to spare", self.nxt()[1])

    def test_the_memory_reserve(self):
        self.run_(cjob("bob", "browser"))
        self.s["jobs"]["queue"] = [cjob("ada", "parallel")]
        # 4400 - 3000 (run.sh's peak) = 1400 < 1500
        x, why = self.nxt(dict(GOOD, avail_mb=4400))
        self.assertIsNone(x)
        self.assertIn("waiting for memory", why)
        self.assertEqual(self.nxt(dict(GOOD, avail_mb=4500))[0]["id"], "ada-1")
        # bob started a moment ago: his peak is not in the reading yet
        self.s["jobs"]["running"][0]["started"] = self.t - 10
        self.assertIsNone(self.nxt(dict(GOOD, avail_mb=4500))[0])
        self.assertEqual(self.nxt(dict(GOOD, avail_mb=5200))[0]["id"], "ada-1")

    def test_two_run_sh_never_share_on_this_box(self):
        # one PERF=0 run.sh going leaves ~2.7 GB of the ~5.4 GB free at
        # rest (measured 2026-10-24): a second wants 3000 + the reserve
        self.run_(cjob("bob", "parallel"))
        self.s["jobs"]["queue"] = [cjob("ada", "parallel")]
        self.assertIn("waiting for memory", self.nxt(dict(GOOD, avail_mb=2700))[1])
        # its peak against the reserve, not 1800's: 3200 free would have
        # let a second one start before
        self.assertIsNone(self.nxt(dict(GOOD, avail_mb=3300))[0])

    def test_cpu_pressure_and_unknown_readings(self):
        self.run_(cjob("bob", "browser"))
        self.s["jobs"]["queue"] = [cjob("ada", "browser")]
        self.assertIn("the CPU is busy", self.nxt(dict(GOOD, cpu_psi=25.0))[1])
        self.assertIsNone(self.nxt(dict(GOOD, cpu_psi=None))[0])
        self.assertIsNone(self.nxt(dict(GOOD, avail_mb=None))[0])
        self.assertEqual(self.nxt(dict(GOOD, cpu_psi=24.9))[0]["id"], "ada-1")

    def test_closing_and_hysteresis(self):
        self.run_(cjob("bob", "browser"), cjob("cy", "browser"))
        self.assertEqual(self.s["jobs"]["limit"]["n"], 2)
        for bad in ({"avail_mb": 900}, {"mem_psi": 6.0}, {"swapin_kbs": 3000.0}, {"cpu_psi": 41.0}):
            S.job_limit(self.s, GOOD, self.t, 2)
            self.s["jobs"]["limit"]["n"] = 2
            self.assertEqual(S.job_limit(self.s, dict(GOOD, **bad), self.t, 2), 1, bad)
        # closing kills nothing: both still run, the next waits
        self.assertEqual(len(self.s["jobs"]["running"]), 2)
        self.s["jobs"]["running"].pop()
        self.s["jobs"]["queue"] = [cjob("ada", "browser")]
        x, why = self.nxt()
        self.assertIsNone(x)
        self.assertIn("held at 1: CPU pressure 41%", why)
        title, content = S.render(self.s, self.t)
        self.assertIn("**Jobs held at 1 of 2:** CPU pressure 41%", content)
        # five minutes of good readings to open again; a bad one starts over
        t = self.t
        self.assertEqual(S.job_limit(self.s, GOOD, t, 2), 1)
        self.assertEqual(S.job_limit(self.s, GOOD, t + 200, 2), 1)
        self.assertEqual(S.job_limit(self.s, dict(GOOD, cpu_psi=30.0), t + 250, 2), 1)  # not good: no clock
        self.assertEqual(S.job_limit(self.s, GOOD, t + 310, 2), 1)
        self.assertEqual(S.job_limit(self.s, GOOD, t + 600, 2), 1)
        self.assertEqual(S.job_limit(self.s, GOOD, t + 611, 2), 2)
        self.assertEqual(self.s["jobs"]["limit"]["why"], "")
        self.assertEqual(self.nxt()[0]["id"], "ada-1")
        # the block reads back
        back = S.normal(json.loads(S.BLOCK_RE.findall(S.render(self.s, t)[1])[-1]))
        self.assertEqual(back["jobs"]["limit"]["n"], 2)

    def test_jobs_max_1_is_the_line_as_it_was(self):
        S.job_limit(self.s, GOOD, self.t, 1)
        self.assertEqual(self.s["jobs"]["limit"], dict(self.s["jobs"]["limit"], n=1, max=1, why=""))
        self.run_(cjob("bob", "build"))
        self.s["jobs"]["queue"] = [cjob("ada", "build")]
        x, why = self.nxt()
        self.assertIsNone(x)
        self.assertEqual(why, "bob's job is running")
        # nothing running: the head starts on today's rule alone, readings unknown or not
        self.s["jobs"]["running"] = []
        self.assertEqual(S.job_next(self.s, {}, self.t)[0]["id"], "ada-1")
        self.assertEqual(S.job_next(self.s, {}, self.t, mem_ok=False), (None, "waiting for memory"))
        # a bad reading cannot take it below 1
        self.assertEqual(S.job_limit(self.s, dict(GOOD, avail_mb=10), self.t, 1), 1)


class Classes(unittest.TestCase):
    def test_classes(self):
        for cmd, cls in (("lcars-ui/test/run.sh", "exclusive"), ("PERF=0 lcars-ui/test/run.sh", "parallel"),
                         ("export PERF=0; lcars-ui/test/run.sh", "parallel"),
                         ("python3 lcars-ui/test/perf.py --fresh", "exclusive"),
                         ("KB_JOBS=1 python3 test/keyboard.py", "parallel"),
                         ("python3 lcars-ui/test/buttons.py", "browser"), ("python3 test/qa_chat.py", "browser"),
                         ("python3 test/editor.py", "browser"), ("python3 test/architect.py", "browser"),
                         ("python3 test/deckvoice.py", "browser"), ("python3 test/classified.py", "browser"),
                         ("make SANITIZE=0 lcars-one", "build"), ("make lcars-release", "build"),
                         ("make lcars-embed", "build"), ("make lcars-static", "exclusive"),
                         ("python3 lcars-ui/test/deckshots.py", "exclusive"), ("python3 test/shots.py", "exclusive"),
                         ("python3 test/deckmem.py --check", "exclusive"), ("bash test/dates.sh", "exclusive"),
                         ("bash scripts/deck-models/build.sh rooms", "exclusive"),
                         ("bash video/explainer/render.sh scene1", "explainer"),
                         ("echo something unknown", "exclusive"),
                         # the short functional tests: one core, beside another job
                         ("python3 lcars-ui/test/demo_static.py", "test"), ("python3 test/recording.py", "test"),
                         ("node lcars-ui/test/deckboot.js", "test"), ("python3 scripts/test_jobs.py", "test"),
                         ("cd /tmp/x/wt && git log --oneline -1 && python3 lcars-ui/test/demo_static.py", "test"),
                         ("bash -c 'cd /tmp/x/wt && git log --oneline -1 && python3 lcars-ui/test/demo_static.py'",
                          "test"),
                         ("python3 test/demo_static.py && bash all5.sh", "test"),
                         ("python3 test/demo_static.py && python3 test/perf.py", "exclusive"),
                         ("python3 other/test_x.py", "exclusive"),
                         # two in one: the stricter
                         ("PERF=0 lcars-ui/test/run.sh && python3 test/buttons.py", "parallel"),
                         ("python3 test/buttons.py; python3 test/perf.py", "exclusive")):
            self.assertEqual(E.job_class(cmd, lambda: self.fail("asked")), cls, cmd)
        # --changed: perf only when changed.py picks it
        self.assertEqual(E.job_class("lcars-ui/test/run.sh --changed", lambda: True), "exclusive")
        self.assertEqual(E.job_class("lcars-ui/test/run.sh --changed", lambda: False), "parallel")
        self.assertEqual(E.job_class("PERF=0 lcars-ui/test/run.sh --changed", lambda: self.fail("asked")), "parallel")

    def test_the_unit_bounds_by_class(self):
        for cls, hi, mx in (("exclusive", "3584M", "4G"), ("parallel", "3584M", "4G"), ("browser", "1G", "1536M"),
                            ("build", "1G", "1536M"), ("explainer", "3584M", "4608M"), ("test", "1536M", "2G")):
            props = E.JOB_UNIT_PROPS[cls]
            self.assertIn(f"MemoryHigh={hi}", props)
            self.assertIn(f"MemoryMax={mx}", props)
            self.assertIn("OOMScoreAdjust=900", props)


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


class RunnerBase(unittest.TestCase):
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


class Runner(RunnerBase):
    def test_inline_streams_and_returns_its_exit_code(self):
        code, res, text = self.submit("echo hello; exit 3")
        self.assertEqual(code, 3)
        self.assertIn("hello", text)
        self.assertEqual((res["outcome"], res["exit"]), ("failed", 3))
        self.assertEqual(len(self.runs), 1)  # in a run of its own (a unit), not this process
        s = self.state()
        self.assertEqual(s["jobs"]["running"], [])
        self.assertEqual((s["jobs"]["recent"][-1]["outcome"], s["jobs"]["recent"][-1]["told"]), ("failed", "turn"))
        self.assertEqual(self.j.inbox("ada"), [])  # their own turn: nothing typed
        self.assertEqual(s["queue"], [])

    def test_an_inline_job_outlives_its_waiter(self):
        """2026-10-25: an inline dates.sh died with the session whose
        background shell ran it. The run is its own now; the waiter gone,
        the result is typed to its engineer as a queued job's is."""
        def die(r, log, step=0.5):
            raise KeyboardInterrupt  # the session that waited ended

        with mock.patch.object(E, "job_follow", die), self.assertRaises(KeyboardInterrupt):
            self.submit("sleep 2; echo late")
        s = self.state()
        self.assertTrue(s["jobs"]["running"][0]["inline"])
        self.assertTrue(s["jobs"]["running"][0]["unit"].startswith("pid:"))
        self.assertTrue(E.lock_free(E.job_file(s["jobs"]["running"][0]["id"], "waiter")))
        s = self.wait_done()
        self.assertEqual((s["jobs"]["recent"][-1]["outcome"], s["jobs"]["recent"][-1]["told"]), ("passed", "inbox"))
        self.assertRegex(self.message(), r"^\[job\] .*: PASSED \(exit 0\)")
        self.assertIn("late", self.message())

    def test_a_waiting_waiter_is_left_to_report(self):
        """While its waiter follows it, the dispatcher leaves an inline job
        alone, though its run has ended: the waiter says it in the turn."""
        seen = {}
        real = E.job_follow

        def follow(r, log, step=0.5):
            while not os.path.exists(E.job_file(r["id"], "result")):
                time.sleep(0.1)
            time.sleep(0.5)
            E.job_dispatch()
            seen["running"] = [x["id"] for x in self.state()["jobs"]["running"]]
            return real(r, log, step)

        with mock.patch.object(E, "job_follow", follow):
            code, res, _ = self.submit("true")
        self.assertEqual((code, seen["running"]), (0, [res["job"]]))
        self.assertEqual(self.j.inbox("ada"), [])

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

    def start_queued(self, cmd, timeout=None):
        """A queued job of ada's started (the seat passed), its id."""
        self.seat("ada", ["bob"])
        jid = self.submit(cmd)[1]["queued"]
        self.pass_seat()
        with S.changing(E.STATE) as s:
            S.job_release(s, "ada")
            if timeout:
                s["jobs"]["queue"][0]["timeout"] = timeout
        E.job_dispatch()
        self.assertEqual([r["id"] for r in self.state()["jobs"]["running"]], [jid])
        return jid

    def lose(self):
        """The block written over by older code: its running jobs gone."""
        with S.changing(E.STATE) as s:
            s["jobs"]["running"] = []

    def wait_done(self, secs=30):
        end = time.time() + secs
        while time.time() < end:
            s = self.state()
            if not s["jobs"]["running"] and not s["jobs"]["queue"] and self.j.inbox("ada"):
                return s
            time.sleep(0.2)
        self.fail("not reported: " + json.dumps(self.state()["jobs"]))

    def test_a_job_the_block_lost_mid_run_is_carried_over(self):
        jid = self.start_queued("sleep 3; echo ran")
        time.sleep(1)  # its run holds its lock
        self.lose()
        s = E.job_dispatch()
        self.assertEqual([r["id"] for r in s["jobs"]["running"]], [jid])
        self.assertIn("ada's job carried over", json.dumps(s))
        s = self.wait_done()
        self.assertIn("PASSED", self.message())
        self.assertEqual(s["jobs"]["recent"][-1]["id"], jid)
        # reported once: its end is told, a later dispatch finds nothing
        self.assertTrue(os.path.exists(E.job_file(jid, "told")))
        self.lose()
        with S.changing(E.STATE) as s:
            s["jobs"]["recent"] = []
        E.job_dispatch()
        self.assertEqual(self.state()["jobs"]["running"], [])
        self.assertEqual(len(self.j.inbox("ada")), 1)

    def test_a_result_the_block_lost_is_reported(self):
        # 0.298.6's case: the run ends (its result written) with its job no
        # longer in the block; the job-run's own next step finds it
        jid = self.start_queued("sleep 2; echo ran")
        self.lose()
        self.wait_done()
        self.assertIn("PASSED", self.message())
        self.assertTrue(os.path.exists(E.job_file(jid, "told")))

    def test_an_old_result_is_never_carried_over(self):
        # the jobs before this code kept no `.told`: a result older than its
        # first look was reported in its day
        os.makedirs(E.jobs_dir(), exist_ok=True)
        for jid in ("ada-20261022-090000", "ada-20261022-090001"):
            with open(E.job_file(jid, "spec"), "w") as f:
                json.dump({"id": jid, "name": "ada", "cmd": "true", "label": "old", "wt": E.wt("ada")}, f)
        with open(E.job_file("ada-20261022-090000", "result"), "w") as f:
            json.dump({"outcome": "passed"}, f)
        old = time.time() - 60
        os.utime(E.job_file("ada-20261022-090000", "result"), (old, old))
        E.job_dispatch()
        s = self.state()
        # nor one with no result whose lock is free: nothing in flight
        self.assertEqual((s["jobs"]["running"], self.j.inbox("ada")), ([], []))

    def test_waiting_for_the_cores_is_not_run_time(self):
        held, go = threading.Event(), threading.Event()

        def hold():
            with E.cores(who="a deploy's suite"):
                held.set()
                go.wait(30)

        t = threading.Thread(target=hold)
        t.start()
        held.wait(10)
        try:
            jid = self.start_queued("echo ran", timeout=2)  # the run's own: shorter than the wait
            self.assertEqual(E.read_json(E.job_file(jid, "spec"))["timeout"], 2)
            time.sleep(4)
        finally:
            go.set()
            t.join()
        self.wait_done()
        msg = self.message()
        self.assertIn("PASSED", msg)

    def test_a_wait_for_the_cores_is_bounded(self):
        held, go = threading.Event(), threading.Event()

        def hold():
            with E.cores(who="an old job-run"):
                held.set()
                go.wait(30)

        t = threading.Thread(target=hold)
        t.start()
        held.wait(10)
        try:
            with mock.patch.dict(os.environ, {"LCARS_JOB_CORES_WAIT": "2"}):  # the child job-run's
                self.start_queued("echo ran")
                self.wait_done()
        finally:
            go.set()
            t.join()
        self.assertIn("FAILED - its run stopped without finishing (it waited 0m for the cores, held by an old job-run)",
                      self.message())

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

    def test_two_shared_jobs_start_together(self):
        with S.changing(E.STATE) as s:
            s["jobs"]["queue"] = [cjob("bob", "browser"), cjob("cy", "browser")]
        with mock.patch.object(E, "job_launch", return_value="pid:1"), \
                mock.patch.object(E, "box_readings", return_value=GOOD), \
                mock.patch.dict(os.environ, {"LCARS_JOBS_MAX": "2"}):
            s = E.job_dispatch()
        self.assertEqual([x["name"] for x in s["jobs"]["running"]], ["bob", "cy"])
        self.assertEqual(s["jobs"]["note"], "")
        self.assertEqual(E.jobs_brief(s)["running"]["name"], "bob")
        self.assertEqual([(x["name"], x["cls"]) for x in E.jobs_brief(s)["runs"]], [("bob", "browser"), ("cy", "browser")])

    def test_the_views_line(self):
        # slice B: every running job in words, the limit's chip, the line's
        jb = {"runs": [{"name": "bob", "label": "run.sh", "elapsed": 250}, {"name": "cy", "label": "", "elapsed": 59}],
              "queue": [{"name": "dee"}], "limit": {"n": 2, "max": 2, "why": ""}}
        self.assertEqual(E.jobs_line(jb), "cores 2/2: bob run.sh 4m, cy a job 0m; 1 waiting (dee)")
        jb = {"runs": [jb["runs"][0]], "queue": [], "limit": {"n": 1, "max": 2, "why": "memory pressure 7%"}}
        self.assertEqual(E.jobs_line(jb), "held at 1 of 2 (memory pressure 7%): bob run.sh 4m")
        self.assertEqual(E.jobs_line({"runs": [], "queue": [], "limit": {"n": 2, "max": 2}}), "no job running (cores 0/2)")
        self.assertEqual(E.jobs_line({"runs": [], "queue": []}), "no job running")
        with S.changing(E.STATE) as s:
            s["jobs"]["queue"] = [cjob("bob", "browser"), cjob("cy", "browser")]
        with mock.patch.object(E, "job_launch", return_value="pid:1"), \
                mock.patch.object(E, "box_readings", return_value=GOOD), \
                mock.patch.dict(os.environ, {"LCARS_JOBS_MAX": "2"}):
            s = E.job_dispatch()
        jb = E.jobs_brief(s)
        self.assertEqual(jb["limit"], {"n": 2, "max": 2, "why": ""})
        self.assertTrue(jb["line"].startswith("cores 2/2: bob "), jb["line"])
        self.assertEqual(E.seat_brief(s)["jobs"]["line"], jb["line"])

    def test_jobs_max_1_starts_one(self):
        with S.changing(E.STATE) as s:
            s["jobs"]["queue"] = [cjob("bob", "browser"), cjob("cy", "browser")]
        with mock.patch.object(E, "job_launch", return_value="pid:1"), \
                mock.patch.object(E, "box_readings", return_value=GOOD), \
                mock.patch.dict(os.environ, {"LCARS_JOBS_MAX": "1"}):
            s = E.job_dispatch()
        self.assertEqual([x["name"] for x in s["jobs"]["running"]], ["bob"])
        self.assertEqual(s["jobs"]["note"], "bob's job is running")

    def pair(self, ca, cb):
        """Two direct runners of ada's tree, classes `ca` and `cb`, started
        together: their (start, end) times, from files outside the tree."""
        d = E.wt("ada")
        head, tree = E.tree_print(d)
        out = os.path.join(TMP, f"pair-{ca}-{cb}")
        os.makedirs(out, exist_ok=True)
        for i, c in enumerate((ca, cb)):
            f = os.path.join(out, str(i))
            E.job_launch({"id": f"ada-pair{i}-{ca}-{cb}", "name": "ada", "label": "pair", "wt": d, "head": head,
                          "tree": tree, "timeout": 60, "cls": c,
                          "cmd": f"date +%s.%N > {f}.a; sleep 1.5; date +%s.%N > {f}.b"})
        end = time.time() + 20
        while time.time() < end and not all(os.path.exists(os.path.join(out, f"{i}.b")) for i in (0, 1)):
            time.sleep(0.1)
        time.sleep(0.1)

        def t(i, e):
            with open(os.path.join(out, f"{i}.{e}")) as f:
                return float(f.read())
        return [(t(i, "a"), t(i, "b")) for i in (0, 1)]

    def overlap(self, ab):
        (a0, b0), (a1, b1) = ab
        return a0 < b1 and a1 < b0

    def test_the_cores_lock_shared_and_exclusive(self):
        self.assertTrue(self.overlap(self.pair("browser", "parallel")))
        self.assertFalse(self.overlap(self.pair("exclusive", "browser")))
        self.assertFalse(self.overlap(self.pair("build", "exclusive")))
        # a deploy's suite (exclusive) waits out a shared job
        waited = []
        with E.cores(who="job", shared=True):
            with E.cores(who="job2", shared=True):  # a second shared holder: no wait
                pass
            t = threading.Thread(target=lambda: E.cores(waited.append, "deploy").__enter__())
            t.start()
            t.join(0.5)
            self.assertTrue(t.is_alive())
        t.join(5)
        self.assertEqual(waited, ["the running jobs"])

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
        unit = s["jobs"]["running"][0]["unit"]
        pid = int(unit.split(":")[1])
        jid = s["jobs"]["running"][0]["id"]
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
        self.assertEqual(s["jobs"]["running"], [])
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
        jid = self.state()["jobs"]["running"][0]["id"]
        for _ in range(100):
            if os.path.exists(E.job_file(jid, "pid")):
                break
            time.sleep(0.1)
        code, res, _ = self.call(E.cmd_job_cancel, "ada")
        self.assertEqual(res["was"], "running")
        s = self.state()
        self.assertEqual(s["jobs"]["running"], [])
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


class Watchdog(RunnerBase):
    """engineer.py's watch (docs/design/job-queue.md, "The watchdog"): what
    the line and the seat should have done and have not, acted on and said
    to Number One once."""

    def setUp(self):
        super().setUp()
        self.moves = []
        self.p2 = [mock.patch.object(E, "seat_move", lambda *a: self.moves.append(1) or ([], self.state()))]
        for p in self.p2:
            p.start()

    def tearDown(self):
        for p in self.p2:
            p.stop()
        super().tearDown()

    def no1(self):
        return [r["content"] for r in self.j.inbox(E.NO1)]

    def running(self, **kw):
        x = dict(job(), id="ada-dead", label="dates.sh", started=int(time.time()) - 3 * 3600, **kw)
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "bob", "since": int(time.time()), "by": "no1"}  # ada long off
            s["jobs"]["running"].append(x)
        os.makedirs(E.jobs_dir(), exist_ok=True)
        return x

    def test_a_dead_job_is_closed_and_its_engineer_told(self):
        self.running(inline=True)  # its waiter gone with the session, as on 2026-10-25
        f = E.watch()
        self.assertEqual(self.state()["jobs"]["running"], [])
        self.assertIn("FAILED - its run stopped without finishing (its process is gone)", self.message())
        self.assertEqual(self.state()["queue"][0]["name"], "ada")
        notes = self.no1()
        self.assertEqual(len(notes), 1)
        self.assertRegex(notes[0], r"^\[watchdog\] - ada's job dates.sh \(ada-dead\), started \d\d:\d\d UTC: "
                                   r"died \(its process is gone\); closed it and told them")
        self.assertTrue(f[0]["new"])
        # said once: the next run finds it again among the recent, says nothing
        f = E.watch()
        self.assertEqual(len(self.no1()), 1)
        self.assertEqual([x["new"] for x in f], [False])

    def test_a_job_past_its_limit_is_stopped(self):
        self.running(timeout=60)
        with open(E.job_file("ada-dead", "lock"), "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)  # its run still holds its lock: hung
            E.watch()
        self.assertEqual(E.read_json(E.job_file("ada-dead", "result"))["outcome"], "timeout")
        self.assertIn("FAILED (timeout after 1m)", self.message())
        self.assertIn("past its limit, still going: stopped it and told them", self.no1()[0])

    def test_a_job_within_its_limit_is_left(self):
        x = self.running()
        with S.changing(E.STATE) as s:
            s["jobs"]["running"][0]["started"] = int(time.time()) - 60
        with open(E.job_file(x["id"], "lock"), "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            self.assertEqual(E.watch(), [])
        self.assertEqual(self.no1(), [])

    def untold(self, mtime_ago):
        ended = int(time.time()) - 10 * M
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "bob", "since": int(time.time()), "by": "no1"}
            s["jobs"]["recent"].append({"id": "ada-x", "name": "ada", "label": "dates.sh", "t": ended - M,
                                        "started": ended - M, "ended": ended, "outcome": "passed", "told": "turn"})
        E.job_result_write("ada-x", {"outcome": "passed", "exit": 0, "secs": 60, "head": "abcdef0"})
        tr = os.path.join(TMP, "transcript.jsonl")
        with open(tr, "w"):
            pass
        os.utime(tr, (time.time() - mtime_ago, time.time() - mtime_ago))
        return tr

    def test_an_untold_result_is_typed_to_them(self):
        tr = self.untold(20 * M)  # their session ended before the job did
        with mock.patch.object(E, "transcript", return_value=tr):
            E.watch()
        self.assertRegex(self.message(), r"^\[job\] dates.sh: PASSED \(exit 0\) in 1m00s on abcdef0")
        s = self.state()
        self.assertEqual(s["queue"][0], dict(s["queue"][0], name="ada", by="job"))
        self.assertEqual(s["jobs"]["recent"][-1]["told"], "inbox")
        self.assertIn("its result only on a session that has ended: typed its result to them", self.no1()[0])
        with mock.patch.object(E, "transcript", return_value=tr):
            E.watch()
        self.assertEqual(len(self.j.inbox("ada")), 1)

    def test_a_result_seen_in_a_later_turn_is_left(self):
        tr = self.untold(M)  # a turn of theirs after it ended: the waiter's output reached them
        with mock.patch.object(E, "transcript", return_value=tr):
            self.assertEqual(E.watch(), [])
        self.assertEqual(self.j.inbox("ada"), [])

    def test_a_stuck_order_queues_them_and_moves_the_seat(self):
        with S.changing(E.STATE) as s:
            s["holder"] = None
        rid = S.inbox_add("bob", "No.1", "build the thing")
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 8 * M))
        next(r for r in self.j.rows if r["id"] == rid)["created_at_utc"] = old
        E.watch()
        self.assertEqual(queued(self.state()), ["bob"])
        self.assertEqual(self.moves, [1])
        self.assertIn(f"bob has had an order waiting since {old[11:16]} UTC (#{rid}), off and not in the "
                      "seat's line: queued them", self.no1()[0])

    def test_a_fresh_order_is_left(self):
        with S.changing(E.STATE) as s:
            s["holder"] = None
        rid = S.inbox_add("bob", "No.1", "build the thing")
        next(r for r in self.j.rows if r["id"] == rid)["created_at_utc"] = \
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - M))
        self.assertEqual(E.watch(), [])
        self.assertEqual(self.moves, [])

    def test_the_seat_free_with_a_line_is_moved(self):
        with S.changing(E.STATE) as s:
            s["holder"] = None
            S.want(s, "bob", "no1", time.time() - 8 * M)
        E.watch()
        self.assertEqual(self.moves, [1])
        self.assertIn("the seat is free and bob waited since", self.no1()[0])

    def test_a_silent_holder_past_the_rule_is_said(self):
        self.seat("ada", ["bob"])
        tr = os.path.join(TMP, "transcript.jsonl")
        with open(tr, "w"):
            pass
        os.utime(tr, (time.time() - 45 * M, time.time() - 45 * M))
        with mock.patch.object(E, "seat_facts", return_value={"ada": "stuck", "bob": "off"}), \
                mock.patch.object(E, "transcript", return_value=tr):
            E.watch()
        self.assertEqual(self.moves, [1])
        self.assertIn("ada has held the seat silent since", self.no1()[0])
        self.assertIn("with bob waiting, and the 30-minute rule has not relieved them", self.no1()[0])

    def test_a_dry_run_does_and_says_nothing(self):
        self.running(inline=True)
        with mock.patch.object(E, "job_settled", return_value={"outcome": "died"}):
            self.assertEqual(E.watch(act=False), [])  # a dead job is found only by settling it
        with S.changing(E.STATE) as s:
            s["holder"] = None
            S.want(s, "bob", "no1", time.time() - 8 * M)
        f = E.watch(act=False)
        self.assertIn("a dry run", f[0]["text"])
        self.assertEqual((self.moves, self.no1(), len(self.state()["jobs"]["running"])), ([], [], 1))


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


class Unit(unittest.TestCase):
    """The job's systemd unit: its memory bounds, and OOMScoreAdjust=900 so
    that the kernel, short of memory, takes a job's process before the
    journal's server (200, the user manager's default for every unit)."""

    def test_the_unit_properties(self):
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        env = {k: v for k, v in os.environ.items() if k != "LCARS_JOB_RUNNER"}
        job = {"id": "ada-20261022-120000", "wt": HERE, "timeout": 1200}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(E, "run", fake_run):
            self.assertEqual(E.job_launch(job), "lcars-job-ada-20261022-120000")
        argv = seen[0]
        self.assertEqual(argv[:2], ["systemd-run", "--user"])
        props = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
        # the run's timeout, the unit's own 300 s, and the wait for the cores
        for want in ("OOMScoreAdjust=900", "MemoryHigh=3584M", "MemoryMax=4G", f"RuntimeMaxSec={1500 + E.JOB_CORES_WAIT}"):
            self.assertIn(want, props)
        # the properties come before the command the unit runs
        self.assertLess(argv.index("OOMScoreAdjust=900"), argv.index("job-run"))


if __name__ == "__main__":
    unittest.main()
