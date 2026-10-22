#!/usr/bin/env python3
"""Unit tests for scripts/engineer.py's `queue` (GET /engineer/queue, the
console's Queue view): the seat with each one's order, and the deploy
history with its versions, CHANGELOG headlines and outcomes - seeded once
from the deploy logs' failures; and each item's time (queue_times,
live_time): the activity classifier, the tasks cut from a sample
transcript, the item a deploy's commits tie to, and its cache. A temp
state directory, a temp git repo (LCARS_LIVE) and a temp Claude projects
folder stand in for production's; the seat's journal calls are stubbed.

    python3 scripts/test_queue.py
"""

import contextlib
import io
import json
import os
import shutil
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
import seat as S  # noqa: E402

CHANGELOG = """# Changelog

Rules: newest first.

## 0.3.0 — 2026-10-13

- **web:** a live clock in the header: the local time beside LCARS,
  ticking only while it is on screen.
- **ops:** something else.

## 0.2.1 — 2026-10-12

- **server (fix):** request framing is checked, not trusted. A bad
  Content-Length is a 400.

## 0.2.0 — 2026-10-11

- a line without a tag, and `code` in **bold** that goes on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on
"""


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Fixture:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="queue-test-")
        self.state = os.path.join(self.tmp, "state")
        self.live = os.path.join(self.tmp, "live")
        os.makedirs(os.path.join(self.state, "logs"))
        os.makedirs(self.live)
        g = dict(cwd=self.live)
        sh("git", "init", "-q", "-b", "deb", **g)
        sh("git", "config", "user.email", "t@t", **g)
        sh("git", "config", "user.name", "t", **g)
        with open(os.path.join(self.live, "CHANGELOG.md"), "w") as f:
            f.write(CHANGELOG)
        self.c = {}
        for i, subj in enumerate(["Start", "Tag lines (0.2.0)", "Frame requests (0.2.1)", "Docs only",
                                  "Header clock (0.3.0)"]):
            with open(os.path.join(self.live, "f.txt"), "a") as f:
                f.write(f"{i}\n")
            sh("git", "add", "-A", **g)
            sh("git", "commit", "-q", "-m", subj, **g)
            self.c[subj] = sh("git", "rev-parse", "HEAD", **g)
        self.projects = os.path.join(self.tmp, "projects")
        self.patches = [mock.patch.object(E, "STATE", self.state), mock.patch.object(E, "LIVE", self.live),
                        mock.patch.object(E, "CLAUDE_PROJECTS", self.projects),
                        mock.patch.object(E, "ROOT", os.path.join(self.tmp, "eng")),
                        mock.patch.object(E, "HISTORY", os.path.join(self.state, "deploys.jsonl")),
                        mock.patch.object(E, "DEPLOY_JSON", os.path.join(self.state, "deploy.json")),
                        mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"})]
        for p in self.patches:
            p.start()
        for n, t in (("kim-c32", "Lieutenant Harry Kim"), ("yar-c36", "Lieutenant Tasha Yar"),
                     ("obrien-c33", "Chief Miles O'Brien")):
            with open(os.path.join(self.state, n + ".json"), "w") as f:
                json.dump({"title": t, "task": "task of " + n}, f)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def write_history(self, recs):
        with open(E.HISTORY, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in recs)

    def log(self, name, text):
        with open(os.path.join(self.state, "logs", name), "w") as f:
            f.write(text)

    def queue(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as e:
            E.main(["queue"])
        self.assertEqual(e.exception.code, 0)
        return json.loads(buf.getvalue())


class Queue(Fixture, unittest.TestCase):
    def test_changelog_headlines(self):
        heads, top = E.changelog_heads(os.path.join(self.live, "CHANGELOG.md"))
        self.assertEqual(top, "0.3.0")
        self.assertEqual(heads["0.3.0"], {"date": "2026-10-13", "tag": "web", "head": "a live clock in the header"})
        self.assertEqual(heads["0.2.1"]["tag"], "server (fix)")
        self.assertEqual(heads["0.2.1"]["head"], "request framing is checked, not trusted")
        h = heads["0.2.0"]
        self.assertEqual(h["tag"], "")
        self.assertNotIn("`", h["head"])
        self.assertNotIn("**", h["head"])
        self.assertLessEqual(len(h["head"]), E.HEAD_MAX)
        self.assertTrue(h["head"].endswith("…"))
        self.assertEqual(E.changelog_heads(os.path.join(self.tmp, "none.md")), ({}, ""))

    def test_versions_in_commit_subjects(self):
        self.assertEqual(E.versions_in(["Header clock (0.3.0)", "Docs only", 'Revert "Frame (0.2.1)"', "Frame (0.2.1)"]),
                         ["0.3.0", "0.2.1"])

    def test_deploys_newest_first_with_versions_headlines_and_outcomes(self):
        c = self.c
        self.write_history([
            # recorded before versions were: they come from the live branch
            {"ts": 1000, "name": "yar-c36", "prev": c["Start"], "new": c["Frame requests (0.2.1)"], "c": True, "files": 3},
            {"ts": 2000, "name": "kim-c32", "prev": c["Frame requests (0.2.1)"], "new": c["Docs only"], "files": 1,
             "rolled_back": 2500},
            {"ts": 2600, "name": "obrien-c33", "verb": "deploy", "outcome": "failed", "msg": "the web suite failed"},
            {"ts": 3000, "name": "kim-c32", "prev": c["Docs only"], "new": c["Header clock (0.3.0)"], "files": 2,
             "subject": "Header clock (0.3.0)", "versions": ["0.3.0"]},
        ])
        r = self.queue()
        self.assertIsNone(r["seat"])
        self.assertEqual(r["live"], {"version": "0.3.0", "commit": c["Header clock (0.3.0)"][:8]})
        d = r["deploys"]
        self.assertEqual([x["ts"] for x in d], [3000, 2600, 2000, 1000])
        self.assertTrue(d[0]["live"])
        self.assertEqual(d[0]["title"], "Lieutenant Harry Kim")
        self.assertEqual(d[0]["versions"], [{"v": "0.3.0", "date": "2026-10-13", "tag": "web",
                                             "head": "a live clock in the header"}])
        self.assertEqual((d[0]["from"], d[0]["to"]), (c["Docs only"][:8], c["Header clock (0.3.0)"][:8]))
        self.assertEqual(d[1]["outcome"], "failed")
        self.assertEqual(d[1]["msg"], "the web suite failed")
        self.assertNotIn("live", d[1])
        self.assertEqual(d[2]["outcome"], "rolled_back")
        self.assertEqual(d[2]["versions"], [])
        self.assertEqual(d[2]["subject"], "Docs only")
        self.assertEqual([v["v"] for v in d[3]["versions"]], ["0.2.1", "0.2.0"])
        self.assertTrue(d[3]["c"])
        self.assertNotIn("live", d[3])

    def test_failures_are_seeded_once_from_the_logs(self):
        self.write_history([{"ts": 5, "name": "kim-c32", "prev": self.c["Start"], "new": self.c["Docs only"]},
                            {"ts": 6, "name": "obrien-c33", "verb": "deploy", "outcome": "failed", "msg": "x",
                             "log": "deploy-20261013-101008.log"}])
        self.log("deploy-20261013-165601.log", "==> pulling deb\n==> rebasing eng/yar-c36 onto deb\n"
                                               "FAILED: eng/yar-c36 does not rebase cleanly onto deb\n")
        self.log("deploy-20261008-081518.log", "FAILED: moreau-c29 is still working; deploy when they are done\n")
        self.log("deploy-20261013-101008.log", "==> rebasing eng/obrien-c33 onto deb\nFAILED: already recorded\n")
        self.log("deploy-20261013-120000.log", "==> pulling deb\n==> deployed\n")
        self.log("rollback-20261012-090000.log", "FAILED: git revert did not apply cleanly\n")
        d = self.queue()["deploys"]
        failed = [x for x in d if x["outcome"] == "failed"]
        self.assertEqual(sorted((x["name"], x["verb"]) for x in failed),
                         [("", "rollback"), ("moreau-c29", "deploy"), ("obrien-c33", "deploy"), ("yar-c36", "deploy")])
        yar = next(x for x in failed if x["name"] == "yar-c36")
        self.assertEqual(yar["ts"], int(time.mktime(time.strptime("20261013-165601", "%Y%m%d-%H%M%S"))))
        self.assertTrue(yar["seeded"])
        self.assertIn("does not rebase", yar["msg"])
        before = E.history()
        self.queue()
        self.assertEqual(E.history(), before, "seeded once")
        self.assertEqual(sum(1 for r in E.history() if r.get("outcome") == "seed"), 1)

    def test_rollback_works_from_landed_deploys_only(self):
        E.record_failed("yar-c36", "boom", "deploy", "/x/deploy-1.log")
        rec = E.history()[-1]
        self.assertEqual((rec["name"], rec["outcome"], rec["log"]), ("yar-c36", "failed", "deploy-1.log"))
        buf = io.StringIO()
        # the check is the caller's side's; a job's runner sets
        # LCARS_ENG_DETACHED for its command (the export's test run is one),
        # which would make this the detached rollback itself
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as e:
            os.environ.pop("LCARS_ENG_DETACHED", None)
            E.main(["rollback"])
        self.assertEqual(e.exception.code, 3)
        self.assertIn("no deploy to roll back", buf.getvalue())

    def test_queue_is_no_engineer(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as e:
            E.main(["poll", "queue"])
        self.assertEqual(e.exception.code, 2)

    def test_the_seat_with_orders_tasks_and_answers(self):
        s = {"holder": {"name": "kim-c32", "since": 100, "by": "no1", "idle": 150}, "note": "",
             "queue": [{"name": "obrien-c33", "t": 110, "by": "no1"}, {"name": "yar-c36", "t": 120, "by": "report"},
                       {"name": "crew:yeoman", "t": 130, "by": "crew"}],
             "waiting": {"kim-c32": 150}}
        rows = [{"title": "obrien-c33 ← seat: [seat] You were relieved", "content": "[seat] You were relieved"},
                {"title": "obrien-c33 ← No.1 [fresh]: [No.1] Chief, a Queue view", "content": "\n[No.1] [No.1] Chief, a Queue view\nmore"},
                {"title": "obrien-c33 ← captain: later", "content": "later"},
                {"title": "yar-c36 ← ship: [deploy finished] deployed", "content": "[deploy finished] deployed yar-c36"}]
        with mock.patch.object(S, "inbox_all", return_value=rows):
            r = E.queue_seat(s, {})
        h = r["holder"]
        self.assertEqual((h["name"], h["title"], h["task"], h["since"], h["waiting"]),
                         ("kim-c32", "Lieutenant Harry Kim", "task of kim-c32", 100, True))
        q = r["queue"]
        self.assertEqual([x["name"] for x in q], ["obrien-c33", "yar-c36", "crew:yeoman"])
        self.assertEqual((q[0]["order"], q[0]["from"], q[0]["since"]), ("Chief, a Queue view", "No.1", 110))
        self.assertNotIn("note", q[0])
        self.assertEqual((q[1]["order"], q[1]["from"], q[1]["note"], q[1]["task"]),
                         ("[deploy finished] deployed yar-c36", "ship", True, "task of yar-c36"))
        self.assertEqual((q[2]["title"], q[2]["task"]), ("", ""))
        self.assertEqual([x["name"] for x in r["waiting"]], ["kim-c32"])

    def test_the_seat_without_the_journal_still_shows_the_line(self):
        s = {"holder": None, "queue": [{"name": "obrien-c33", "t": 1}], "waiting": {}}
        with mock.patch.object(S, "inbox_all", side_effect=S.Down("no journal")):
            r = E.queue_seat(s, {})
        self.assertIsNone(r["holder"])
        self.assertEqual(r["queue"][0]["task"], "task of obrien-c33")

    def test_the_job_lines(self):
        """slice 2's views: queue_seat's and seat_brief's `jobs`, a crew
        list row's and a poll's `job` (docs/design/job-queue.md)."""
        run = {"id": "kim-c32-20261021-140200", "name": "kim-c32", "label": "run.sh", "t": 900, "started": 1000,
               "unit": "lcars-job-x", "head": "abc", "cmd": "run.sh"}
        held = {"id": "yar-c36-20261021-140500", "name": "yar-c36", "label": "buttons.py", "t": 1100, "hold": True}
        s = {"holder": {"name": "obrien-c33", "since": 100}, "queue": [], "waiting": {},
             "jobs": {"running": run, "queue": [held], "recent": [{"id": "x", "name": "kim-c32", "label": "perf",
                                                                    "t": 1, "started": 2, "ended": 3, "outcome": "passed"}],
                      "note": "short of memory"}}
        with mock.patch.object(E.time, "time", return_value=1180):
            jb = E.jobs_brief(s)
        self.assertEqual(jb["running"], {"id": run["id"], "name": "kim-c32", "label": "run.sh", "t": 900, "since": 1000, "elapsed": 180})
        self.assertEqual(jb["queue"], [{"id": held["id"], "name": "yar-c36", "label": "buttons.py", "t": 1100, "place": 1, "hold": True}])
        self.assertEqual((jb["recent"][0]["outcome"], jb["note"]), ("passed", "short of memory"))
        self.assertNotIn("unit", jb["running"])  # the view's, not the runner's
        with mock.patch.object(S, "inbox_all", return_value=[]):
            q = E.queue_seat(s, {})
        self.assertEqual((q["jobs"]["running"]["title"], q["jobs"]["queue"][0]["title"]), ("Lieutenant Harry Kim", "Lieutenant Tasha Yar"))
        b = E.seat_brief(s, "yar-c36")
        self.assertEqual(b["jobs"]["running"]["name"], "kim-c32")
        self.assertEqual({k: b["job"][k] for k in ("id", "state", "place")}, {"id": held["id"], "state": "queued", "place": 1})
        self.assertEqual(E.seat_brief(s, "kim-c32")["job"]["state"], "running")
        self.assertNotIn("job", E.seat_brief(s, "obrien-c33"))
        # an old block without the key is read as empty lines
        self.assertEqual(E.seat_brief({"holder": None, "queue": [], "waiting": {}})["jobs"]["running"], None)
        # crew list: a row's job, its status left alone (a message still starts an "off" one)
        buf = io.StringIO()
        with mock.patch.object(E, "agent_info", return_value=None), mock.patch.object(E, "git_info", return_value={}), \
                mock.patch.object(E, "seat_on", return_value=True), mock.patch.object(E, "seat_read_quiet", return_value=s), \
                contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            E.cmd_list()
        rows = {r["name"]: r for r in json.loads(buf.getvalue().strip().splitlines()[-1])["engineers"]}
        self.assertEqual((rows["yar-c36"]["job"]["place"], rows["yar-c36"]["status"]), (1, "off"))
        self.assertEqual(rows["kim-c32"]["job"]["state"], "running")
        self.assertNotIn("job", rows.get("obrien-c33", {}))


class Eta(Fixture, unittest.TestCase):
    """`eta <name> <minutes>`: the estimate in the engineer's state file, its
    revisions, its end with the turn, and the queue's fields for it."""

    def run_main(self, *argv, stdin=""):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                self.assertRaises(SystemExit) as e:
            E.main(list(argv))
        return e.exception.code, json.loads(buf.getvalue())

    def st(self, n="kim-c32"):
        return E.load(n)

    def test_the_verb_refuses_what_is_not_whole_minutes(self):
        for bad in ("", "0", "-5", "4.5", "forty", "1441", "99999"):
            code, r = self.run_main("eta", "kim-c32", *([bad] if bad else []))
            self.assertEqual(code, 2, bad)
            self.assertIn("whole minutes", r["error"])
        self.assertEqual(self.run_main("eta", "nobody-c1", "10")[0], 2, "no such engineer")
        self.assertEqual(self.run_main("eta", "kim-c32", "10", "20")[0], 2, "one argument")
        self.assertNotIn("eta_min", self.st())

    def test_first_eta_starts_the_task_and_a_second_replaces_it(self):
        with mock.patch.object(E.time, "time", return_value=10_000):
            code, r = self.run_main("eta", "kim-c32", "40")
        self.assertEqual(code, 0)
        self.assertEqual((r["eta_min"], r["eta_at"], r["task_started_at"], r["elapsed_min"]), (40, 10_000, 10_000, 0))
        with mock.patch.object(E.time, "time", return_value=10_000 + 15 * 60):
            code, r = self.run_main("eta", "kim-c32", "60")
        self.assertEqual((r["eta_min"], r["eta_at"], r["task_started_at"], r["elapsed_min"]), (60, 10_900, 10_000, 15))
        self.assertEqual(r["eta_revisions"], [40, 60])
        st = self.st()
        self.assertEqual([e["min"] for e in st["etas"]], [40, 60])
        for i in range(12):
            with mock.patch.object(E.time, "time", return_value=11_000 + i):
                self.run_main("eta", "kim-c32", str(70 + i))
        self.assertEqual(len(self.st()["etas"]), E.ETA_REVISIONS, "a short list")
        self.assertEqual(self.st()["etas"][-1]["min"], 81)

    def test_an_order_begins_the_task_before_the_estimate(self):
        E.task_begins("kim-c32", now=5_000)
        f = E.eta_fields(self.st(), now=5_000 + 7 * 60 + 30)
        self.assertEqual((f["task_started_at"], f["elapsed_min"], f["eta_min"], f["eta_at"]), (5_000, 7, None, None))
        with mock.patch.object(E.time, "time", return_value=5_600):
            self.run_main("eta", "kim-c32", "30")
        self.assertEqual(self.st()["task_started_at"], 5_000, "the order's time, not the estimate's")
        # a new order drops what was left of the last one
        E.task_begins("kim-c32", now=9_000)
        st = self.st()
        self.assertEqual(st["task_started_at"], 9_000)
        self.assertNotIn("eta_min", st)
        self.assertNotIn("etas", st)
        self.assertEqual(E.eta_fields({}), {"eta_min": None, "eta_at": None, "task_started_at": None,
                                            "elapsed_min": None, "eta_revisions": [],
                                            "expected_min": None, "ratio_from": "none"})

    def test_the_turn_end_closes_it_estimated_against_taken(self):
        E.task_begins("kim-c32", now=1_000)
        with mock.patch.object(E.time, "time", return_value=1_300):
            self.run_main("eta", "kim-c32", "20")
        with mock.patch.object(E.time, "time", return_value=1_900):
            self.run_main("eta", "kim-c32", "45")
        with mock.patch.object(E.time, "time", return_value=1_000 + 52 * 60), mock.patch.object(E, "seated", return_value=False):
            code, _ = self.run_main("turn-ended", "kim-c32", stdin="{}")
        self.assertEqual(code, 0)
        st = self.st()
        for k in E.ETA_KEYS:
            self.assertNotIn(k, st)
        self.assertEqual(st["eta_done"], [{"started": 1_000, "ended": 1_000 + 52 * 60, "est": 45, "first": 20,
                                           "revisions": 2, "actual_min": 52, "task": "task of kim-c32",
                                           "model": E.MODEL, "effort": E.EFFORT, "turns": 1}])
        # a turn that ended with no estimate records nothing, and clears its
        # start (a fresh order: else it would continue the one above)
        E.task_begins("kim-c32", now=9_000, fresh=True)
        self.assertIsNone(E.eta_close("kim-c32", now=9_500))
        self.assertNotIn("task_started_at", self.st())
        self.assertEqual(len(self.st()["eta_done"]), 1)
        # the hook's own re-entry (stop_hook_active) is not a turn's end
        E.task_begins("kim-c32", now=10_000)
        with mock.patch.object(E, "seated", return_value=False):
            self.run_main("turn-ended", "kim-c32", stdin='{"stop_hook_active": true}')
        self.assertEqual(self.st()["task_started_at"], 10_000)

    def test_list_and_queue_show_it(self):
        E.task_begins("kim-c32", now=int(time.time()) - 12 * 60 - 5)
        self.run_main("eta", "kim-c32", "40")
        with mock.patch.object(E, "agent_info", return_value=None), mock.patch.object(E, "git_info", return_value={}):
            code, r = self.run_main("list")
        kim = next(x for x in r["engineers"] if x["name"] == "kim-c32")
        self.assertEqual((kim["eta_min"], kim["elapsed_min"]), (40, 12))
        self.assertIsNotNone(kim["eta_at"])
        yar = next(x for x in r["engineers"] if x["name"] == "yar-c36")
        self.assertIsNone(yar["eta_min"])
        s = {"holder": {"name": "kim-c32", "since": 100}, "queue": [{"name": "yar-c36", "t": 110}], "waiting": {}}
        with mock.patch.object(S, "inbox_all", return_value=[]):
            q = E.queue_seat(s, {})
        h = q["holder"]
        self.assertEqual((h["eta_min"], h["elapsed_min"], h["eta_revisions"]), (40, 12, [40]))
        self.assertEqual(h["task_started_at"], self.st()["task_started_at"])
        self.assertEqual((q["queue"][0]["eta_min"], q["queue"][0]["task_started_at"]), (None, None))

    def test_a_shipped_item_carries_its_estimate(self):
        c = self.c
        st = self.st()
        st["eta_done"] = [{"started": 100, "ended": 900, "est": 10, "first": 10, "revisions": 1, "actual_min": 13, "task": "a"},
                          {"started": 1100, "ended": 1500, "est": 30, "first": 20, "revisions": 2, "actual_min": 7, "task": "b"},
                          {"started": 2500, "ended": 2600, "est": 5, "first": 5, "revisions": 1, "actual_min": 2, "task": "c"}]
        E.save("kim-c32", st)
        self.write_history([
            {"ts": 1000, "name": "kim-c32", "prev": c["Start"], "new": c["Frame requests (0.2.1)"]},
            {"ts": 2000, "name": "kim-c32", "prev": c["Frame requests (0.2.1)"], "new": c["Header clock (0.3.0)"]},
            {"ts": 2100, "name": "yar-c36", "verb": "deploy", "outcome": "failed", "msg": "x"},
            {"ts": 2400, "name": "kim-c32", "prev": c["Header clock (0.3.0)"], "new": c["Header clock (0.3.0)"]},
        ])
        d = {x["ts"]: x for x in self.queue()["deploys"]}
        self.assertEqual(d[1000]["eta"], {"est": 10, "first": 10, "actual": 13, "turns": 1})
        self.assertEqual(d[2000]["eta"], {"est": 30, "first": 20, "actual": 7, "turns": 1}, "the last before it, after the last deploy")
        self.assertNotIn("eta", d[2400], "nothing ended between the two")
        self.assertNotIn("eta", d[2100])



class Calibrated(Fixture, unittest.TestCase):
    """0.213.0: the bar against the record (expected_min, ratio_from), a
    task sent back continuing its record, the brief's line, `etas`."""

    def st(self, n="kim-c32"):
        return E.load(n)

    def recs(self, n, pairs, task="t"):
        st = E.load(n) or {}
        st["eta_done"] = [{"started": 100 * i, "ended": 100 * i + 50, "est": said, "first": said, "revisions": 1,
                           "actual_min": took, "task": f"{task}{i}"} for i, (said, took) in enumerate(pairs)]
        E.save(n, st)

    def with_eta(self, n, minutes):
        st = E.load(n)
        st.update(eta_min=minutes, eta_at=1_000, task_started_at=1_000)
        E.save(n, st)
        return E.eta_fields(E.load(n), now=1_000)

    def test_the_ratio_with_0_1_2_and_10_records(self):
        f = self.with_eta("kim-c32", 100)
        self.assertEqual((f["expected_min"], f["ratio_from"]), (None, "none"), "no record anywhere: drawn as before")
        self.recs("kim-c32", [(100, 10)])
        f = self.with_eta("kim-c32", 100)
        self.assertEqual((f["expected_min"], f["ratio_from"]), (10, "crew"), "one of their own: the crew's, which is it")
        self.assertEqual(E.own_ratio(self.st()), (None, 1))
        self.recs("kim-c32", [(100, 10), (50, 15)])
        f = self.with_eta("kim-c32", 100)
        self.assertEqual((f["expected_min"], f["ratio_from"]), (20, "own"), "two: their median, 0.1 and 0.3")
        # ten counted, the oldest beyond them not: 11 records, the first wildly long
        self.recs("kim-c32", [(10, 500)] + [(100, 10 + 2 * i) for i in range(10)])
        r, n = E.own_ratio(self.st())
        self.assertEqual(n, 10)
        self.assertAlmostEqual(r, 0.19)
        f = self.with_eta("kim-c32", 100)
        self.assertEqual((f["expected_min"], f["ratio_from"]), (19, "own"))
        # a ratio of 0 (a task done inside a minute) still draws a bar of a minute
        self.recs("kim-c32", [(30, 0), (40, 0)])
        self.assertEqual(self.with_eta("kim-c32", 30)["expected_min"], 1)

    def test_the_crew_fallback(self):
        self.recs("yar-c36", [(90, 18), (35, 4), (150, 13)])
        self.recs("obrien-c33", [(100, 11)])
        f = self.with_eta("kim-c32", 80)
        # every record of every engineer: 0.2, 0.114, 0.087, 0.11 -> 0.112
        self.assertEqual((f["expected_min"], f["ratio_from"]), (9, "crew"))
        self.assertAlmostEqual(E.crew_ratio(), (4 / 35 + 11 / 100) / 2)

    def test_a_json_file_of_another_shape_is_no_engineer(self):
        """0.232.0: a list in STATE (a db-merge undo file) crashed every eta
        in crew_ratio; it is skipped, as is a record of another shape."""
        self.recs("obrien-c33", [(100, 11)])
        st = E.load("obrien-c33")
        st["eta_done"].append("garbage")
        E.save("obrien-c33", st)
        with open(os.path.join(self.state, "db-merge-undo-2026-10-16.json"), "w") as f:
            json.dump([{"id": 1, "content": "x"}], f)
        self.assertIsNone(E.load("db-merge-undo-2026-10-16"))
        self.assertNotIn("db-merge-undo-2026-10-16", E.all_states())
        self.assertAlmostEqual(E.crew_ratio(), 0.11)
        self.assertAlmostEqual(E.crew_ratio({"x": [1, 2], "obrien-c33": E.load("obrien-c33")}), 0.11)
        self.assertEqual(self.with_eta("kim-c32", 100)["expected_min"], 11)

    def close(self, at):
        with mock.patch.object(E.time, "time", return_value=at):
            return E.eta_close("kim-c32")

    def test_a_task_sent_back_continues_its_record(self):
        E.task_begins("kim-c32", now=10_000)
        st = self.st()
        st.update(eta_min=60, eta_at=10_060, etas=[{"min": 60, "at": 10_060}])
        E.save("kim-c32", st)
        self.close(10_000 + 20 * 60)
        # sent back an hour later, the label unchanged: the same task
        E.task_begins("kim-c32", now=14_000)
        self.assertEqual(self.st()["eta_continues"], 10_000)
        st = self.st()
        st.update(eta_min=10, eta_at=14_100, etas=[{"min": 10, "at": 14_100}])
        E.save("kim-c32", st)
        f = E.eta_fields(self.st(), now=14_100)
        self.assertEqual(f["eta_min"], 10, "its estimate is drawn while it runs")
        rec = self.close(14_000 + 5 * 60)
        st = self.st()
        self.assertEqual(len(st["eta_done"]), 1, "no new record")
        self.assertEqual((rec["first"], rec["est"], rec["revisions"], rec["actual_min"], rec["turns"]), (60, 10, 2, 25, 2))
        self.assertEqual((rec["started"], rec["ended"], rec["ends"]), (10_000, 14_300, [14_300]))
        self.assertNotIn("eta_continues", st)
        # a third turn with no estimate still adds its minutes
        E.task_begins("kim-c32", now=20_000)
        rec = self.close(20_000 + 3 * 60)
        self.assertEqual((rec["actual_min"], rec["turns"], rec["est"]), (28, 3, 10))
        # the queue's shipped item reads the merged record, for a deploy after any of its turns
        self.assertEqual(E.eta_for_deploy(self.st(), 15_000, 13_000), {"est": 10, "first": 60, "actual": 28, "turns": 3})
        self.assertEqual(E.eta_for_deploy(self.st(), 21_000, 15_000)["turns"], 3)

    def test_what_never_continues(self):
        def first_task():
            st = self.st()
            st.pop("eta_done", None)
            E.save("kim-c32", st)
            E.task_begins("kim-c32", now=10_000, fresh=True)
            st = self.st()
            st.update(eta_min=30, eta_at=10_000, etas=[{"min": 30, "at": 10_000}])
            E.save("kim-c32", st)
            self.close(11_000)
        # a fresh order
        first_task()
        E.task_begins("kim-c32", now=12_000, fresh=True)
        self.assertNotIn("eta_continues", self.st())
        self.assertIsNone(self.close(12_600), "and with no estimate, nothing")
        # a clear in between seals the record
        first_task()
        st = self.st()
        st["eta_done"][-1]["sealed"] = True
        E.save("kim-c32", st)
        E.task_begins("kim-c32", now=12_000)
        self.assertNotIn("eta_continues", self.st())
        # past twelve hours
        first_task()
        E.task_begins("kim-c32", now=11_000 + E.ETA_CONTINUE_S)
        self.assertNotIn("eta_continues", self.st())
        # retitled during the turn: a new task, a record of its own
        first_task()
        E.task_begins("kim-c32", now=12_000)
        st = self.st()
        st.update(task="something else", eta_min=8, eta_at=12_000, etas=[{"min": 8, "at": 12_000}])
        E.save("kim-c32", st)
        self.close(12_600)
        done = self.st()["eta_done"]
        self.assertEqual([(d["task"], d["turns"], d["actual_min"]) for d in done],
                         [("task of kim-c32", 1, 17), ("something else", 1, 10)])

    def test_a_clear_seals_the_last_record(self):
        self.recs("kim-c32", [(30, 5)])
        st = self.st()
        st["session"] = "old"
        E.save("kim-c32", st)

        def follow(name, st, info):
            st["session"] = "new"
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "herdr", return_value=("", "")), mock.patch.object(E, "submit_if_left"), \
                mock.patch.object(E, "follow_session", side_effect=follow), mock.patch.object(E.time, "sleep"):
            code, _ = E.clear_session("kim-c32", "old task")
        self.assertEqual(code, 0)
        self.assertTrue(self.st()["eta_done"][-1]["sealed"])

    def test_the_brief_line(self):
        st = self.st()
        self.assertEqual(E.eta_record_line(st), "", "no record: no line")
        self.assertIn("a fix takes 2 to 6 minutes, a feature 10 to 30", E.brief("kim-c32", st))
        self.assertIn("never a person's hours", E.brief("kim-c32", st))
        self.assertNotIn("Your last", E.brief("kim-c32", st))
        self.recs("kim-c32", [(90, 18), (35, 4), (150, 13)])
        st = self.st()
        line = E.eta_record_line(st)
        self.assertEqual(line, " Your last 3 estimates ran 8.8 times long (the median: they took 0.11 of what you said).")
        self.assertIn(line, E.brief("kim-c32", st))
        self.recs("kim-c32", [(10, 30)])
        self.assertEqual(E.eta_record_line(self.st()),
                         " Your last estimate ran 3.0 times short (the median: they took 3.00 of what you said).")

    def test_the_spoken_rule_in_both_briefs(self):
        # the page marks a message said aloud "[spoken] " (chatSpokenMark);
        # an engineer and Number One are each told what it asks, word for word
        rule = E.SPOKEN_RULE
        self.assertTrue(rule.startswith("Spoken messages: a message that begins [spoken]"))
        self.assertIn("one or two short sentences, before any tool call", rule)
        self.assertIn("short and plain enough to listen to", rule)
        self.assertIn("\n\n" + rule + "\n\n", E.brief("kim-c32", self.st()))
        self.assertIn("\n\n" + rule + "\n", E.brief_no1(E.NO1, {}))
        self.assertEqual(E.brief(E.NO1, {}).count("[spoken]"), 1, "said once, in Number One's")

    def test_etas_prints_every_record_and_the_medians(self):
        self.recs("yar-c36", [(90, 18), (150, 13)])
        st = self.st("yar-c36")
        st["eta_done"][0].update(model="opus", effort="high", turns=2)
        E.save("yar-c36", st)
        self.recs("kim-c32", [(100, 11)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as e:
            E.main(["etas"])
        self.assertEqual(e.exception.code, 0)
        r = json.loads(buf.getvalue())
        self.assertEqual(sorted(r["engineers"]), ["kim-c32", "yar-c36"], "only engineers with records")
        y = r["engineers"]["yar-c36"]
        self.assertEqual(y["records"][0], {"task": "t0", "said_first": 90, "said_last": 90, "took": 18, "ratio": 0.2,
                                           "turns": 2, "model": "opus", "effort": "high",
                                           "started": "1970-01-01T00:00:00Z", "ended": "1970-01-01T00:00:50Z"})
        self.assertEqual((y["median_ratio"], y["own_ratio"]), (0.143, 0.143))
        self.assertIsNone(r["engineers"]["kim-c32"]["own_ratio"], "one record is not a ratio of their own")
        self.assertEqual((r["crew_median_ratio"], r["records"]), (0.11, 3))


# a sample transcript, as Claude Code writes one: T0 is its first order
T0 = 1792000000


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"


def rec(kind, t, content, **kw):
    o = {"type": kind, "timestamp": iso(t), "isSidechain": False, "message": {"role": kind, "content": content}}
    o.update(kw)
    return o


def call(t, name, inp, cid, thinking_at=None):
    out_ = [rec("assistant", thinking_at, [{"type": "thinking", "thinking": "hm"}])] if thinking_at else []
    return out_ + [rec("assistant", t, [{"type": "tool_use", "id": cid, "name": name, "input": inp}])]


def result(t, cid):
    return rec("user", t, [{"type": "tool_result", "tool_use_id": cid, "content": "ok"}])


def say(t, text):
    return rec("assistant", t, [{"type": "text", "text": text}])


def sample():
    """Task one: an order (wrapped as the deck pastes it), a read, an edit
    (30s of it written), a background test run of 600s waited on, a commit,
    the yield. Then the ship's note and the next order in one message: task
    two, which the note's deploy does not end."""
    return [
        rec("user", T0 - 5, "<command-name>/clear</command-name>"),
        rec("user", T0 - 4, "<local-command-caveat>x</local-command-caveat>", isMeta=True),
        rec("user", T0, '\n\n<pasted_content id="a1">\n[No.1] [No.1] New task from the captain. A clock.\nmore\n</pasted_content id="a1">'),
        *call(T0 + 5, "Read", {"file_path": "/x/index.html"}, "c1", thinking_at=T0 + 3),
        result(T0 + 10, "c1"),
        *call(T0 + 40, "Edit", {"file_path": "/x/index.html"}, "c2", thinking_at=T0 + 10),
        result(T0 + 41, "c2"),
        *call(T0 + 45, "Bash", {"command": "lcars-ui/test/run.sh --changed", "run_in_background": True}, "c3"),
        result(T0 + 46, "c3"),
        say(T0 + 50, "Running the suite."),
        rec("user", T0 + 650, "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>c3</tool-use-id>\n"
                              "<status>completed</status>\n</task-notification>"),
        *call(T0 + 655, "Bash", {"command": "git add -A && git commit -qm 'A clock (0.3.0)'"}, "c4"),
        result(T0 + 660, "c4"),
        *call(T0 + 661, "Bash", {"command": "/srv/m/lcars/scripts/engineer.py yield kim-c32"}, "c5"),
        result(T0 + 662, "c5"),
        say(T0 + 665, "Report: done."),
        rec("user", T0 + 2000, "[deploy finished] deployed kim-c32: 1 files. Tell the captain.\n\n"
                               "[No.1] Next: the seconds too."),
        *call(T0 + 2010, "Grep", {"pattern": "clock"}, "c6"),
        result(T0 + 2012, "c6"),
        say(T0 + 2015, "A question first: which font?"),
        rec("user", T0 + 2300, "The mono one."),
        *call(T0 + 2310, "mcp__fff__grep", {"query": "x"}, "c7"),
        result(T0 + 2320, "c7"),
    ]


class Times(Fixture, unittest.TestCase):
    """Each item's time, from a sample transcript of kim-c32's."""

    def setUp(self):
        super().setUp()
        d = os.path.join(self.projects, E.claude_slug(E.wt("kim-c32")))
        os.makedirs(d)
        self.transcript = os.path.join(d, "11111111-2222-3333-4444-555555555555.jsonl")
        with open(self.transcript, "w") as f:
            f.write("\n".join(json.dumps(r) for r in sample()) + "\n")
            f.write('{"type":"last-prompt","lastPrompt":"x"}\n')
        g = dict(cwd=self.live)
        self.base = sh("git", "rev-parse", "HEAD", **g)
        with open(os.path.join(self.live, "clock.txt"), "w") as f:
            f.write("clock\n")
        sh("git", "add", "-A", **g)
        env = dict(os.environ, GIT_AUTHOR_DATE=f"@{T0 + 657} +0000")
        subprocess.run(["git", "commit", "-q", "-m", "A clock (0.3.0)"], cwd=self.live, env=env, check=True)
        self.head = sh("git", "rev-parse", "HEAD", **g)
        # the deploy: its log names kim when it starts (T0+1800), its record
        # when it is live (T0+1900)
        self.log("deploy-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(T0 + 1800)) + ".log",
                 "==> rebasing eng/kim-c32 onto deb\n")
        self.write_history([{"ts": T0 + 1900, "name": "kim-c32", "prev": self.base, "new": self.head, "files": 1,
                             "subject": "A clock (0.3.0)", "versions": ["0.3.0"]}])

    def test_bash_commands_by_what_they_run(self):
        for cmd, kind in [("cd x && make check", "test"), ("lcars-ui/test/run.sh --changed 2>&1 | tail", "test"),
                          ("python3 scripts/test_queue.py", "test"), ("node lcars-ui/test/deckboot.js", "test"),
                          ("PERF=0 KB=0 lcars-ui/test/run.sh", "test"), ("sed -n 1,20p a.py", "read"),
                          ("grep -n x f > /tmp/out", "read"), ("git log --oneline -3", "read"), ("ls -la", "read"),
                          ("sed -i s/a/b/ f", "write"), ("echo hi > notes.md", "write"),
                          ("cat > /tmp/x.py <<'EOF'\nhi\nEOF", "write"),
                          ("python3 - <<'EOF'\nopen('f', 'w').write('x')\nEOF", "write"),
                          ("python3 - <<'EOF'\nprint(open('f').read())\nEOF", "read"),
                          ("make lcars-cli", "build"), ("git add -A && git commit -m x", "git"),
                          ("git -C /x rebase deb", "git"), ("~/lcars/scripts/engineer.py deploy kim-c32", "deploy"),
                          ("until grep -q done ~/.local/state/lcars-eng/deploy.json; do sleep 5; done", "deploy"),
                          ("sed -i s/a/b/ f && make check", "test"), ("curl -s localhost:8080/health", "other"),
                          ("~/lcars/scripts/engineer.py retitle kim-c32 x", "other")]:
            self.assertEqual(E.bash_kind(cmd), kind, cmd)
        self.assertEqual(E.tool_kind("Read", {}), "read")
        self.assertEqual(E.tool_kind("mcp__fff__multi_grep", {}), "read")
        self.assertEqual(E.tool_kind("Edit", {}), "write")
        self.assertEqual(E.tool_kind("AskUserQuestion", {}), "answer")
        self.assertEqual(E.tool_kind("WebSearch", {}), "other")

    def test_tasks_from_a_transcript(self):
        tasks = E.time_tasks(E.time_events(self.transcript))
        self.assertEqual(len(tasks), 2, "the ship's note with the next order in one message: a task of its own")
        one, two = tasks
        self.assertEqual((one["start"], one["last"]), (T0, T0 + 1900 - 1900 + 665))
        self.assertEqual(one["order"], "New task from the captain. A clock.")
        self.assertEqual(one["turns"], 1, "a background run's notice is no turn")
        sums = {}
        for a, b, k in one["spans"]:
            sums[k] = sums.get(k, 0) + b - a
        # 5s before the read, 5s reading it, 30s writing the edit and 1s
        # applying it; the test's call (1s) and 600s waited for its notice,
        # 5s of git, 1s yielding, and the model's own between them
        self.assertEqual(sums, {"think": 5 + 4 + 4 + 5 + 1 + 3, "read": 5, "write": 31, "test": 601, "git": 5,
                                "other": 1}, one["spans"])
        self.assertEqual(two["start"], T0 + 2000)
        self.assertEqual(two["order"], "[No.1] Next: the seconds too.".replace("[No.1] ", ""))
        self.assertEqual(two["turns"], 2)
        sums = {}
        for a, b, k in two["spans"]:
            sums[k] = sums.get(k, 0) + b - a
        self.assertEqual(sums.get("answer"), 285, "a question asked: waiting for the answer")
        self.assertEqual(sums.get("read"), 2 + 10)

    def test_a_seat_wait_and_a_new_task_by_its_words(self):
        evs = [{"w": "u", "t": 0, "text": "Do A."}, {"w": "a", "t": 5, "calls": {"x": "test"}},
               {"w": "u", "t": 100, "text": "[seat] You were relieved mid-turn. You have the seat again."},
               {"w": "a", "t": 110, "calls": {}}, {"w": "u", "t": 200, "text": "And a fix."},
               {"w": "a", "t": 210, "calls": {}}, {"w": "u", "t": 300, "text": "[No.1] New task: B."}]
        tasks = E.time_tasks(evs)
        self.assertEqual([t["start"] for t in tasks], [0, 300], "an answer goes on the task; 'new task' starts one")
        kinds = [k for _, _, k in tasks[0]["spans"]]
        self.assertEqual(kinds, ["think", "seat", "think", "answer", "think"])

    def test_a_shipped_item_its_time_and_its_cache(self):
        d = self.queue()["deploys"][0]
        t = d["time"]
        self.assertEqual((t["start"], t["end"], t["dur"]), (T0, T0 + 1900, 1900))
        self.assertEqual(t["turns"], 1)
        self.assertEqual(t["order"], "New task from the captain. A clock.")
        self.assertNotIn("partial", t)
        k = {x["k"]: x["s"] for x in t["kinds"]}
        self.assertEqual([x["k"] for x in t["kinds"]], [x for x in E.TIME_KINDS if x in k], "in the bar's order")
        self.assertEqual(k["test"], 601)
        self.assertEqual(k["deploy"], 100, "the deploy from its log's start to its record")
        self.assertEqual(k["answer"], 1800 - 665, "the rest of the wait after the report")
        self.assertEqual(sum(k.values()), 1900)
        cache = E.read_json(E.times_path())
        self.assertEqual(cache["v"], E.TIMES_V)
        self.assertIn(f"kim-c32@{T0 + 1900}", cache["items"])
        # cached: the transcripts are not read again
        with mock.patch.object(E, "engineer_tasks", side_effect=AssertionError("read again")):
            self.assertEqual(self.queue()["deploys"][0]["time"], t)
        # a classifier of another version works it out again
        cache["v"] = E.TIMES_V - 1
        cache["items"][f"kim-c32@{T0 + 1900}"]["dur"] = 1
        with open(E.times_path(), "w") as f:
            json.dump(cache, f)
        self.assertEqual(self.queue()["deploys"][0]["time"]["dur"], 1900)

    def test_orders_from_the_inbox(self):
        rows = [{"title": "kim-c32 ← No.1 [fresh]: [No.1] New task from the captain. A clock.", "created_at_utc": "2026-10-14 10:00:00"},
                {"title": "kim-c32 ← ship: [deploy finished] deployed", "created_at_utc": "2026-10-14 10:01:00"},
                {"title": "kim-c32 ← seat: [seat] You were relieved mid-turn", "created_at_utc": "2026-10-14 10:02:00"},
                {"title": "yar-c36 ← captain: short", "created_at_utc": "2026-10-14 10:03:00"}]
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "1"}), mock.patch.object(S, "inbox_delivered", return_value=rows):
            self.assertEqual(E.inbox_orders(), [("kim-c32", E.calendar.timegm((2026, 10, 14, 10, 0, 0)),
                                                 "[No.1] New task from the captain. A clock.")])
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "1"}), mock.patch.object(S, "inbox_delivered", side_effect=S.Down("x")):
            self.assertEqual(E.inbox_orders(), [])
        # a shipped item's order, given before it reached them
        with mock.patch.object(E, "inbox_orders", return_value=[("kim-c32", T0 - 300, "[No.1] New task from the captain. A clock.")]):
            t = self.queue()["deploys"][0]["time"]
        self.assertEqual((t["start"], t["dur"]), (T0 - 300, 2200))
        self.assertEqual({x["k"]: x["s"] for x in t["kinds"]}["seat"], 300)

    def test_commits_outside_every_task_are_partial(self):
        os.remove(self.transcript)
        t = self.queue()["deploys"][0]["time"]
        self.assertTrue(t["partial"])
        self.assertEqual((t["start"], t["end"]), (T0 + 657, T0 + 1900), "from the first commit, what is known")
        self.assertEqual({x["k"] for x in t["kinds"]}, {"deploy", "answer"})

    def test_the_work_under_way(self):
        g = dict(cwd=self.live)
        sh("git", "checkout", "-q", "-b", "eng/kim-c32", **g)
        with open(os.path.join(self.live, "secs.txt"), "w") as f:
            f.write("s\n")
        sh("git", "add", "-A", **g)
        env = dict(os.environ, GIT_AUTHOR_DATE=f"@{T0 + 2305} +0000")
        subprocess.run(["git", "commit", "-q", "-m", "Seconds"], cwd=self.live, env=env, check=True)
        sh("git", "checkout", "-q", "deb", **g)
        s = {"log": [[T0 + 1950, "kim-c32 queued (no1)"], [T0 + 1999, "kim-c32 seated (no1)"]]}
        t = E.live_time("kim-c32", E.history(), s, {}, now=T0 + 2400)
        self.assertTrue(t["live"])
        self.assertEqual((t["start"], t["end"]), (T0 + 1950, T0 + 2400), "from when its order was queued for the seat")
        k = {x["k"]: x["s"] for x in t["kinds"]}
        self.assertEqual(k["seat"], 49, "queued until seated, by the seat's log")
        self.assertEqual(k["read"], 2 + 10)
        self.assertIsNone(E.live_time("yar-c36", E.history(), s, {}, now=T0 + 2400), "no transcripts, no time")
        # queued by the ship's note, the order joining that place later:
        # when it was given is not known from the log
        s = {"log": [[T0 + 1950, "kim-c32 queued (report)"], [T0 + 1999, "kim-c32 seated (report)"]]}
        self.assertEqual(E.live_time("kim-c32", E.history(), s, {}, now=T0 + 2400)["start"], T0 + 2000)
        # but its inbox entry says when
        orders = [("kim-c32", T0 + 1950, "[No.1] Next: the seconds too."), ("yar-c36", T0 + 1900, "[No.1] Next: the seconds too."),
                  ("kim-c32", T0 + 1000, "an older order, not this one")]
        t = E.live_time("kim-c32", E.history(), s, {}, now=T0 + 2400, orders=orders)
        self.assertEqual(t["start"], T0 + 1950)
        self.assertEqual({x["k"]: x["s"] for x in t["kinds"]}["seat"], 50)


if __name__ == "__main__":
    unittest.main()
