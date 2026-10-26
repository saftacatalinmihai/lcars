#!/usr/bin/env python3
"""The seat's and the job line's metrics (scripts/eng_metrics.py, and the
events engineer.py and seat.py feed it; docs/ops/seat-metrics.md).

eng_metrics on its own: counters and histogram buckets cumulative across
loads (the file is the memory), an outcome outside the fixed set as
"other", a negative duration dropped, a state that does not parse set aside,
and a render that is valid Prometheus text (HELP and TYPE on every metric,
each metric's samples together, buckets that never fall, +Inf the count).
Then through the events, with a stand-in journal and herdr stood in for:
an order, the seat taken, a turn's end (report, question, job), a relieve
(stuck, stopped), a job's end and a cancel, a deploy and a rollback, an
inbox delivered, reap's census - and a metric that fails never failing
its caller.

    python3 scripts/test_metrics_eng.py
"""

import io
import json
import os
import re
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no live journal, a scratch engineer state
import seat as S  # noqa: E402
import engineer as E  # noqa: E402
import eng_metrics as M  # noqa: E402


class Journal:
    """seat._http over rows in memory: GET /entries (kind, done, dir,
    limit), POST, PUT - what the seat and the inbox use."""

    def __init__(self):
        self.rows = []

    def __call__(self, method, path, body=None):
        if method == "GET":
            q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&"))
            rows = [r for r in self.rows if r["kind"] == q.get("kind", r["kind"])
                    and ("done" not in q or r["done_bool"] == int(q["done"]))]
            rows.sort(key=lambda r: r["id"], reverse=q.get("dir") != "asc")
            return [dict(r) for r in rows[:int(q.get("limit", 100))]]
        if method == "POST":
            r = {"id": len(self.rows) + 1, "kind": body["kind"], "title": body.get("title", ""),
                 "content": body.get("content", ""), "done_bool": 0, "deleted": 0,
                 "created_at_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 90))}
            self.rows.append(r)
            return dict(r)
        rid = int(path.rsplit("/", 1)[1])
        r = next(x for x in self.rows if x["id"] == rid)
        r.update(body)
        return dict(r)


def state():
    return M.load(M.dir_of(E.STATE))


def read(path):
    with open(path) as f:
        return f.read()


def prom():
    return read(os.path.join(M.dir_of(E.STATE), "metrics.prom"))


def sample(text, series):
    m = re.search(r"^" + re.escape(series) + r" (\S+)$", text, re.M)
    return float(m.group(1)) if m else None


def validate(tc, text):
    """The text format, strictly: what Prometheus would refuse, and what it
    would take but read wrong (a bucket that falls, +Inf not the count)."""
    tc.assertTrue(text.endswith("\n"))
    typed, helped, seen, current = {}, set(), set(), None
    line_re = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{(?:[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\\n]|\\[\\"n])*",?)*\})? '
                         r'(-?[0-9.e+]+|\+Inf|-Inf|NaN)$')
    buckets = {}
    for ln in text.splitlines():
        if ln.startswith("# HELP "):
            helped.add(ln.split(" ", 3)[2])
            continue
        if ln.startswith("# TYPE "):
            _, _, name, typ = ln.split(" ")
            tc.assertIn(typ, ("counter", "gauge", "histogram"))
            tc.assertNotIn(name, typed, f"{name} typed twice")
            tc.assertIn(name, helped, f"{name} has no HELP before its TYPE")
            typed[name] = typ
            current = name
            continue
        m = line_re.match(ln)
        tc.assertIsNotNone(m, f"not a sample line: {ln!r}")
        name, labels = m.group(1), m.group(2) or ""
        base = re.sub(r"_(bucket|sum|count)$", "", name) if typed.get(current) == "histogram" else name
        tc.assertEqual(base, current, f"{name} is not under its own TYPE")
        tc.assertNotIn(name + labels, seen, f"{name}{labels} twice")
        seen.add(name + labels)
        if name.endswith("_bucket"):
            key = (base, re.sub(r',?le="[^"]*"', "", labels))
            buckets.setdefault(key, []).append(float(m.group(3)))
        if name.endswith("_count") and typed.get(current) == "histogram":
            key = (base, labels.replace("{}", ""))
            b = buckets.get((base, labels or "{}"), [])
            tc.assertTrue(b, f"{base}{labels} has no buckets")
            tc.assertEqual(b, sorted(b), f"{base}{labels}'s buckets fall")
            tc.assertEqual(b[-1], float(m.group(3)), f"{base}{labels}: +Inf is not the count")
    return typed


class Metrics(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(E.STATE, f"m-{self.id().rsplit('.', 1)[1]}")

    def test_every_metric_declared_before_any_event(self):
        text = M.render(M.empty())
        typed = validate(self, text)
        for name in ("lcars_seat_queue_length", "lcars_seat_held", "lcars_seat_waiting_answer",
                     "lcars_engineers_on_duty", "lcars_engineers_working", "lcars_jobs_queued",
                     "lcars_jobs_running", "lcars_deploy_running", "lcars_no1_inbox_pending",
                     "lcars_engineer_ctx_tokens"):
            self.assertEqual(typed.get(name), "gauge", name)
        for name in ("lcars_seat_turns_total", "lcars_jobs_total", "lcars_deploys_total",
                     "lcars_rollbacks_total", "lcars_orders_total"):
            self.assertEqual(typed.get(name), "counter", name)
        for name in ("lcars_seat_wait_seconds", "lcars_seat_turn_seconds", "lcars_job_wait_seconds",
                     "lcars_job_run_seconds", "lcars_task_seconds", "lcars_deploy_seconds",
                     "lcars_inbox_delivery_seconds"):
            self.assertEqual(typed.get(name), "histogram", name)
        # every outcome's counter at 0 from the start, so increase() sees the first
        for o in M.JOB_OUTCOMES:
            self.assertEqual(sample(text, f'lcars_jobs_total{{outcome="{o}"}}'), 0)
        self.assertEqual(sample(text, 'lcars_job_run_seconds_bucket{outcome="passed",le="+Inf"}'), 0)

    def test_buckets_are_cumulative_and_the_sum_and_count_follow(self):
        with M.changing(self.dir) as m:
            M.observe(m, "lcars_task_seconds", 45)
            M.observe(m, "lcars_task_seconds", 600)
            M.observe(m, "lcars_task_seconds", 9000)  # past the last bucket: +Inf only
        text = read(os.path.join(M.dir_of(self.dir), "metrics.prom"))
        validate(self, text)
        b = lambda le: sample(text, f'lcars_task_seconds_bucket{{le="{le}"}}')
        self.assertEqual((b(30), b(60), b(300), b(600), b(900), b(7200), b("+Inf")), (0, 1, 1, 2, 2, 2, 3))
        self.assertEqual(sample(text, "lcars_task_seconds_sum"), 9645)
        self.assertEqual(sample(text, "lcars_task_seconds_count"), 3)

    def test_counters_survive_a_reload_and_never_fall(self):
        for _ in range(3):  # three processes' worth: each loads what the last wrote
            with M.changing(self.dir) as m:
                M.inc(m, "lcars_orders_total")
                M.inc(m, "lcars_jobs_total", "failed")
                M.observe(m, "lcars_job_run_seconds", 100, "failed")
        text = read(os.path.join(M.dir_of(self.dir), "metrics.prom"))
        self.assertEqual(sample(text, "lcars_orders_total"), 3)
        self.assertEqual(sample(text, 'lcars_jobs_total{outcome="failed"}'), 3)
        self.assertEqual(sample(text, 'lcars_job_run_seconds_count{outcome="failed"}'), 3)
        self.assertEqual(sample(text, 'lcars_job_run_seconds_count{outcome="passed"}'), 0)

    def test_an_unknown_outcome_is_other_and_a_negative_time_is_dropped(self):
        with M.changing(self.dir) as m:
            M.inc(m, "lcars_jobs_total", 'weird"\nthing')
            M.observe(m, "lcars_seat_wait_seconds", -5)
            M.observe(m, "lcars_seat_wait_seconds", None)
        text = read(os.path.join(M.dir_of(self.dir), "metrics.prom"))
        validate(self, text)
        self.assertEqual(sample(text, 'lcars_jobs_total{outcome="other"}'), 1)
        self.assertNotIn("weird", text)
        self.assertEqual(sample(text, "lcars_seat_wait_seconds_count"), 0)

    def test_a_state_that_does_not_parse_is_set_aside(self):
        d = M.dir_of(self.dir)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "state.json"), "w") as f:
            f.write("{not json")
        with M.changing(self.dir) as m:
            M.inc(m, "lcars_rollbacks_total")
        self.assertTrue(os.path.exists(os.path.join(d, "state.json.bad")))
        self.assertEqual(M.load(d)["counters"]["lcars_rollbacks_total"][""], 1)

    def test_a_labelled_gauge_is_replaced_whole(self):
        with M.changing(self.dir) as m:
            M.gauge(m, "lcars_engineer_ctx_tokens", {"ada": 1000, "bob": 2000})
        with M.changing(self.dir) as m:
            M.gauge(m, "lcars_engineer_ctx_tokens", {"bob": 2500})
        text = read(os.path.join(M.dir_of(self.dir), "metrics.prom"))
        self.assertNotIn('name="ada"', text)
        self.assertEqual(sample(text, 'lcars_engineer_ctx_tokens{name="bob"}'), 2500)

    def test_the_render_is_atomic_and_leaves_no_temporary(self):
        with M.changing(self.dir) as m:
            M.inc(m, "lcars_orders_total")
        self.assertEqual(sorted(os.listdir(M.dir_of(self.dir))), ["lock", "metrics.prom", "state.json"])

    def test_a_failing_metric_never_raises(self):
        blocker = os.path.join(E.STATE, "a-file")
        with open(blocker, "w"):
            pass
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            M.record(blocker, lambda m: M.inc(m, "lcars_orders_total"))  # its dir cannot be made
            M.record(self.dir, lambda m: M.inc(m, "no_such_metric"))
        self.assertIn("eng_metrics:", err.getvalue())


class Events(unittest.TestCase):
    """engineer.py's events, into the scratch state's metrics."""

    def setUp(self):
        self.j = Journal()
        import shutil
        shutil.rmtree(M.dir_of(E.STATE), ignore_errors=True)
        os.makedirs(E.STATE, exist_ok=True)
        for n in ("ada", "bob"):
            E.save(n, {"name": n, "session": "s-" + n, "title": n.title()})
        self.p = [mock.patch.object(S, "_http", self.j), mock.patch.object(E, "agent_info", return_value=None),
                  mock.patch.object(E, "engineer_tab", return_value=None), mock.patch.object(E, "seat_move_later"),
                  mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "1"})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def call(self, fn, *a, stdin=""):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stdin", io.StringIO(stdin)):
            try:
                fn(*a)
            except SystemExit:
                pass
        return buf.getvalue()

    def test_an_order_is_counted_and_opens_the_task(self):
        self.call(E.cmd_say, "ada", stdin="[No.1] fix the header")
        self.assertEqual(sample(prom(), "lcars_orders_total"), 1)
        self.assertEqual(sample(prom(), "lcars_seat_queue_length"), 1)  # the seat's write, its gauges
        t = E.load("ada")["order_at"]
        self.call(E.cmd_say, "ada", stdin="and the footer")
        self.assertEqual(sample(prom(), "lcars_orders_total"), 2)
        self.assertEqual(E.load("ada")["order_at"], t, "a second word into an open task keeps its start")

    def test_the_seat_taken_observes_the_wait(self):
        now = time.time()
        with S.changing(E.STATE) as s:
            s["queue"] = [{"name": "ada", "t": int(now) - 400, "by": "no1"}]
        started = []  # on duty once the seat has started them (else a stray, adopted)
        with mock.patch.object(E, "seat_start", side_effect=lambda n: started.append(n) or True), \
                mock.patch.object(E, "agent_info", side_effect=lambda n: {"agent_status": "working"}
                                  if n in started else None):
            E.seat_move()
        text = prom()
        self.assertEqual(sample(text, "lcars_seat_wait_seconds_count"), 1)
        self.assertEqual(sample(text, 'lcars_seat_wait_seconds_bucket{le="300"}'), 0)
        self.assertEqual(sample(text, 'lcars_seat_wait_seconds_bucket{le="600"}'), 1)
        self.assertEqual(sample(text, "lcars_seat_held"), 1)
        self.assertEqual(sample(text, "lcars_seat_queue_length"), 0)

    def test_a_turn_s_clock_from_its_prompt_to_the_seat_s_word(self):
        self.call(E.cmd_hook, "turn-began", "ada", stdin="{}")
        out = self.call(E.cmd_hook, "turn-began", "ada", stdin="{}")
        self.assertEqual(out, "", "a UserPromptSubmit hook prints nothing: it would go into the conversation")
        t0 = E.load("ada")["turn_at"]
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "no1"}
        with mock.patch.object(E, "spawn") as sp, mock.patch.object(E, "eta_close"):
            self.call(E.cmd_hook, "turn-ended", "ada", stdin="{}")
        sp.assert_any_call("seat-turn-ended", "ada", str(t0))
        self.assertNotIn("turn_at", E.load("ada"), "taken off at the turn's end, for the next prompt's")

    def turn_end(self, name, t0, yielded=False, job=False):
        with S.changing(E.STATE) as s:
            s["holder"] = dict({"name": name, "since": 1, "by": "no1"}, **({"yielded": 1} if yielded else {}))
            if job:
                s["jobs"]["queue"] = [{"id": "j1", "name": name, "cmd": "x", "label": "x", "t": 1, "hold": True}]
        with mock.patch.object(E.time, "sleep"), mock.patch.object(E, "seat_move"), \
                mock.patch.object(E, "job_dispatch"):
            self.call(E.cmd_seat_turn_ended, name, str(int(t0)))

    def test_a_report_ends_the_turn_and_the_task(self):
        now = time.time()
        st = E.load("ada")
        st["order_at"] = int(now) - 1000
        E.save("ada", st)
        self.turn_end("ada", now - 200, yielded=True)
        text = prom()
        self.assertEqual(sample(text, 'lcars_seat_turns_total{outcome="report"}'), 1)
        self.assertEqual(sample(text, 'lcars_seat_turn_seconds_bucket{le="120"}'), 0)
        self.assertEqual(sample(text, 'lcars_seat_turn_seconds_bucket{le="300"}'), 1)
        self.assertEqual(sample(text, 'lcars_task_seconds_bucket{le="900"}'), 0)
        self.assertEqual(sample(text, 'lcars_task_seconds_bucket{le="1200"}'), 1)
        self.assertNotIn("order_at", E.load("ada"))

    def test_a_question_and_a_job_keep_the_task_open(self):
        st = E.load("ada")
        st["order_at"] = int(time.time()) - 1000
        E.save("ada", st)
        self.turn_end("ada", time.time() - 50)
        self.turn_end("ada", time.time() - 50, yielded=True, job=True)
        self.turn_end("ada", 0)  # a turn whose start is not known: counted, not timed
        text = prom()
        self.assertEqual(sample(text, 'lcars_seat_turns_total{outcome="question"}'), 2)
        self.assertEqual(sample(text, 'lcars_seat_turns_total{outcome="job"}'), 1)
        self.assertEqual(sample(text, "lcars_seat_turn_seconds_count"), 2)
        self.assertEqual(sample(text, "lcars_task_seconds_count"), 0)
        self.assertIn("order_at", E.load("ada"))

    def test_a_relieve_is_stuck_or_the_captain_s_stop(self):
        st = E.load("ada")
        st["turn_at"] = int(time.time()) - 2000
        E.save("ada", st)
        with mock.patch.object(E, "herdr", return_value=(None, None)), mock.patch.object(E.time, "sleep"), \
                mock.patch.object(E, "agent", return_value="pane"):
            E.seat_relieve("ada", "no sign of work for 30 minutes")
            E.seat_relieve("bob", "the captain's order, for ada")
        text = prom()
        self.assertEqual(sample(text, 'lcars_seat_turns_total{outcome="stuck"}'), 1)
        self.assertEqual(sample(text, 'lcars_seat_turns_total{outcome="stopped"}'), 1)
        self.assertEqual(sample(text, "lcars_seat_turn_seconds_count"), 1, "bob's start was not known")

    def test_a_job_s_end_its_wait_and_run_and_a_cancel(self):
        now = time.time()
        job = {"id": "ada-1", "name": "ada", "cmd": "run.sh", "label": "run.sh", "t": int(now) - 700,
               "started": int(now) - 500}
        with S.changing(E.STATE) as s:
            s["jobs"]["running"] = [dict(job)]
            s["jobs"]["queue"] = [{"id": "bob-1", "name": "bob", "cmd": "x", "label": "x", "t": int(now)}]
        self.assertEqual(sample(prom(), "lcars_jobs_running"), 1)
        self.assertEqual(sample(prom(), "lcars_jobs_queued"), 1)
        with mock.patch.object(E, "job_text", return_value="[job] done"):
            E.job_finish(job, {"outcome": "passed"})
            E.job_finish(job, {"outcome": "passed"})  # reported once
        self.call(E.cmd_job_cancel, "bob")
        text = prom()
        self.assertEqual(sample(text, 'lcars_jobs_total{outcome="passed"}'), 1)
        self.assertEqual(sample(text, 'lcars_jobs_total{outcome="cancelled"}'), 1)
        self.assertEqual(sample(text, "lcars_job_wait_seconds_count"), 1, "a job never started has no wait")
        self.assertEqual(sample(text, 'lcars_job_wait_seconds_bucket{le="120"}'), 0)
        self.assertEqual(sample(text, 'lcars_job_wait_seconds_bucket{le="300"}'), 1)
        self.assertEqual(sample(text, 'lcars_job_run_seconds_bucket{outcome="passed",le="600"}'), 1)
        self.assertEqual(sample(text, "lcars_jobs_running"), 0)
        self.assertEqual(sample(text, "lcars_jobs_queued"), 0)

    def test_deploys_and_rollbacks(self):
        now = time.time()
        E.metric(lambda M_, m: M_.gauge(m, "lcars_deploy_running", 1))
        self.assertEqual(sample(prom(), "lcars_deploy_running"), 1)
        E.deploy_metrics("done", now - 400, now=now)
        E.deploy_metrics("failed", now - 50, now=now)
        E.deploy_metrics("done", 0, "rollback")
        E.deploy_metrics("failed", 0, "rollback")
        text = prom()
        validate(self, text)
        self.assertEqual(sample(text, "lcars_deploy_running"), 0)
        self.assertEqual(sample(text, 'lcars_deploys_total{outcome="done"}'), 1)
        self.assertEqual(sample(text, 'lcars_deploys_total{outcome="failed"}'), 1)
        self.assertEqual(sample(text, 'lcars_deploy_seconds_bucket{outcome="done",le="300"}'), 0)
        self.assertEqual(sample(text, 'lcars_deploy_seconds_bucket{outcome="done",le="600"}'), 1)
        self.assertEqual(sample(text, 'lcars_deploy_seconds_bucket{outcome="failed",le="60"}'), 1)
        self.assertEqual(sample(text, "lcars_rollbacks_total"), 1, "only one that went live")

    def test_an_inbox_delivered_observes_its_time(self):
        S.inbox_add("ada", "captain", "first")
        S.inbox_add("ada", "No.1", "[No.1] second")
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}), \
                mock.patch.object(E, "tell", return_value=True):
            self.assertTrue(E.seat_deliver("ada", wait=1))
        text = prom()
        self.assertEqual(sample(text, "lcars_inbox_delivery_seconds_count"), 2)
        self.assertEqual(sample(text, 'lcars_inbox_delivery_seconds_bucket{le="60"}'), 0)
        self.assertEqual(sample(text, 'lcars_inbox_delivery_seconds_bucket{le="120"}'), 2)

    def test_reap_s_census(self):
        seat_s = S.empty()
        seat_s["holder"] = {"name": "ada", "since": 1}
        seat_s["queue"] = [{"name": "bob", "t": 1}, {"name": "crew:brief", "t": 1}]
        seat_s["waiting"] = {"bob": 1}
        with mock.patch.object(E, "ctx_of", side_effect=lambda st: {"ada": 150000}.get(st.get("name"), 0)), \
                mock.patch.object(E, "deploy_state", return_value={"state": "running"}):
            E.metrics_census({"ada": "working", "bob": "idle", "number-one": "idle"}, 3, seat_s)
        text = prom()
        validate(self, text)
        self.assertEqual(sample(text, "lcars_engineers_on_duty"), 3)
        self.assertEqual(sample(text, "lcars_engineers_working"), 1)
        self.assertEqual(sample(text, 'lcars_engineer_ctx_tokens{name="ada"}'), 150000)
        self.assertNotIn('name="bob"', text, "no context, no series")
        self.assertEqual(sample(text, "lcars_deploy_running"), 1)
        self.assertEqual(sample(text, "lcars_no1_inbox_pending"), 3)
        self.assertEqual(sample(text, "lcars_seat_queue_length"), 2)
        self.assertEqual(sample(text, "lcars_seat_waiting_answer"), 1)
        mt = os.path.getmtime(os.path.join(M.dir_of(E.STATE), "metrics.prom"))
        os.utime(os.path.join(M.dir_of(E.STATE), "metrics.prom"), (mt - 600, mt - 600))
        with mock.patch.object(E, "ctx_of", return_value=0), mock.patch.object(E, "deploy_state", return_value={}):
            E.metrics_census({}, None, None)
        self.assertGreater(os.path.getmtime(os.path.join(M.dir_of(E.STATE), "metrics.prom")), mt - 1,
                           "each census rewrites the file: its mtime is reap's heartbeat")
        self.assertEqual(sample(prom(), "lcars_no1_inbox_pending"), 3, "not known: kept")

    def test_a_missing_metrics_module_never_breaks_a_seat_move(self):
        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"eng_metrics": None}), mock.patch("sys.stderr", err):
            with S.changing(E.STATE) as s:  # import eng_metrics raises ImportError
                s["queue"] = [{"name": "ada", "t": 1, "by": "no1"}]
        self.assertEqual([e["name"] for e in S.read()[1]["queue"]], ["ada"], "the seat was written")
        self.assertIn("seat: metrics not recorded: ModuleNotFoundError", err.getvalue())
        with mock.patch.object(M, "record", side_effect=RuntimeError("broken")), mock.patch("sys.stderr", err):
            with S.changing(E.STATE) as s:
                s["queue"] = []
        self.assertEqual(S.read()[1]["queue"], [])
        self.assertIn("RuntimeError: broken", err.getvalue())

    def test_the_state_file_is_not_an_engineer(self):
        E.metric(lambda M_, m: M_.inc(m, "lcars_orders_total"))
        self.assertNotIn("metrics", E.all_states())
        self.assertNotIn("state", E.all_states())


if __name__ == "__main__":
    unittest.main(verbosity=1)
