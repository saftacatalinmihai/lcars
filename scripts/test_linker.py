#!/usr/bin/env python3
"""Unit tests for the measure pass of scripts/lcars_linker.py (`lcars-link.sh
measure`): the pairing of start and end rows, the stopwatch's one-row spans,
gym sessions, and that --dry-run writes nothing. No server, no CLI: the
rows are dicts in lcars-cli's --json shape, and the CLI is mocked.

    python3 scripts/test_linker.py
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lcars_linker as L  # noqa: E402
import lcars_roles  # noqa: E402

# The roles: the defaults, or $LCARS_KINDS_FILE's mapping (a run with a set
# one: the same checks on the journal's own kinds). Never the CLI.
L._ROLES = lcars_roles.load(lambda: None) if os.environ.get("LCARS_KINDS_FILE") else lcars_roles.Roles()
LOG = L.roles().kind("log")
CHILD_SLEEP = L.roles().kind("child_sleep")
DRIVE = L.roles().kind("drive")


def row(i, at, content="", kind="drive", title="HTTP Entry", **k):
    r = dict(id=i, kind=kind, title=title, content=content, created_at_utc=at,
             last_modified_at_utc=at, value_float=0.0, value_int=0, start_date="", end_date="")
    r.update(k)
    return r


def measured(kind, rows, paired=True):
    unit, lo, hi = L.GYM if kind == "gym" else L.paired_kinds()[kind]
    items, log = L.measure_kind(kind, rows, unit, lo, hi, paired)
    return {r["id"]: (v, note) for r, v, note in items}, log


class Pairing(unittest.TestCase):
    def test_start_then_end(self):
        m, log = measured("drive", [row(1, "2026-10-07 16:25:09", "start Portbella"),
                                    row(2, "2026-10-07 17:06:23", "end Valdemar")])
        self.assertEqual(m, {2: (41, "since #1")})
        self.assertEqual(log, [])

    def test_orphan_end_and_out_of_range(self):
        m, log = measured("drive", [row(1, "2026-08-15 10:14:25", "end Ridgeway"),
                                    row(2, "2026-10-09 17:51:22", "start Temporal"),
                                    row(3, "2026-10-10 09:49:40", "end Muro")])
        self.assertEqual(m, {})
        self.assertEqual(log, ["- drive #1: end with no start before it — left empty",
                               "- drive #3: 958.3 minutes since start #2 is out of range — left empty"])

    def test_mis_tapped_start_before_end(self):
        # the child's sleep #825/#830/#831: asleep the evening before, then at
        # waking Start and End four seconds apart; the night is #825 -> #831
        m, log = measured(CHILD_SLEEP, [row(825, "2026-08-29 18:37:37", "start", CHILD_SLEEP),
                                           row(830, "2026-08-30 04:57:50", "start", CHILD_SLEEP),
                                           row(831, "2026-08-30 04:57:54", "end", CHILD_SLEEP)])
        self.assertEqual(m, {831: (10.34, "since #825 (start #830 a mis-tap)")})
        self.assertEqual(log, [])

    def test_mis_tap_with_nothing_before_is_left_empty(self):
        m, log = measured(CHILD_SLEEP, [row(1, "2026-08-11 04:46:20", "start", CHILD_SLEEP),
                                           row(2, "2026-08-11 04:46:23", "end", CHILD_SLEEP)])
        self.assertEqual(m, {})
        self.assertIn("out of range", log[0])

    def test_latest_start_wins_and_an_end_consumes_it(self):
        m, log = measured("drive", [row(1, "2026-09-19 14:07:54", "start Lakeside"),
                                    row(2, "2026-09-19 16:14:51", "start Parkside"),
                                    row(3, "2026-09-19 17:07:16", "end Northgate"),
                                    row(4, "2026-09-19 17:30:00", "end again")])
        self.assertEqual(m, {3: (52, "since #2")})
        self.assertEqual(log, ["- drive #4: end with no start before it — left empty"])

    def test_order_is_by_creation_not_id(self):
        # #4017 was backdated before its end #4015
        m, _ = measured("drive", [row(4015, "2026-10-01 07:55:50", "end Tampere"),
                                  row(4017, "2026-10-01 06:30:00", "start")])
        self.assertEqual(m, {4015: (86, "since #4017")})


class Spans(unittest.TestCase):
    def test_stopwatch_row_is_measured_by_its_span(self):
        # drive #4153: the stopwatch's one row, no end row after it
        m, log = measured("drive", [row(4153, "2026-10-04 15:12:08", "start Valdemar",
                                        start_date="2026-10-04 15:12:08", end_date="2026-10-04 15:53:39")])
        self.assertEqual(m, {4153: (42, "its own span from 2026-10-04 15:12")})
        self.assertEqual(log, [])

    def test_span_row_paired_with_an_end_row_counts_once(self):
        # #4259 carries a span and #4261 ends it: the end row is the drive
        m, _ = measured("drive", [row(4259, "2026-10-07 16:25:09", "start",
                                      start_date="2026-10-07 16:32:09", end_date="2026-10-07 17:15:46"),
                                  row(4261, "2026-10-07 17:06:23", "end")])
        self.assertEqual(list(m), [4261])

    def test_running_stopwatch_is_not_measured(self):
        m, log = measured("sleep", [row(1, "2026-10-11 22:21:44", "start", "sleep", start_date="2026-10-11 22:21:44")])
        self.assertEqual((m, log), ({}, []))

    def test_orphan_end_measured_by_its_own_start_date(self):
        # what an end row with no start can carry: Scheduled's start, set by hand
        m, log = measured("drive", [row(633, "2026-08-15 10:14:25", "end Ridgeway", start_date="2026-08-15 09:40:00")])
        self.assertEqual(m, {633: (34, "its own span from 2026-08-15 09:40")})
        self.assertEqual(log, [])

    def test_span_out_of_range(self):
        m, log = measured("drive", [row(1, "2026-10-04 15:12:08", "start",
                                        start_date="2026-10-04 15:12:08", end_date="2026-10-05 15:53:39")])
        self.assertEqual(m, {})
        self.assertIn("own span of 1481.5 minutes is out of range", log[0])


class Gym(unittest.TestCase):
    def test_which_rows_are_gym(self):
        g = lambda title, content, kind=LOG: L.is_gym(row(1, "2026-10-14 09:34:23", content, kind, title))
        self.assertTrue(g("HTTP Entry", "at gym . "))                       # #5037
        self.assertTrue(g("gym", "pull"))                                   # #4003
        self.assertTrue(g("2026-09-28 Gym", "start\npush"))
        self.assertFalse(g("HTTP Entry", "after work\nthen went to gym"))  # not the first line
        self.assertFalse(g("gymnastics", ""))
        self.assertFalse(g("gym", "", "workout"))

    def test_gym_session_measured_and_titled(self):
        rows = [row(5037, "2026-10-14 09:34:23", "at gym . ", LOG,
                    start_date="2026-10-14 09:34:23", end_date="2026-10-14 10:26:50"),
                row(4003, "2026-09-30 17:35:57", "pull", LOG, "gym",
                    start_date="2026-09-30 16:30:00", end_date="2026-09-30 17:36:36")]
        items, log = L.measure_kind("gym", rows, *L.GYM, paired=False)
        plan = L.plan_values("gym", items, L.GYM[0], "gym · ")
        self.assertEqual([(r["id"], f, v, t) for r, f, v, t, _ in plan],
                         [(4003, "--value-float", 67, None),                # a person's title stays
                          (5037, "--value-float", 52, "gym · 52 min")])
        # a second run over what the first wrote plans nothing
        for r, _, v, t, _ in plan:
            r["value_float"], r["title"] = v, t or r["title"]
        items, _ = L.measure_kind("gym", rows, *L.GYM, paired=False)
        self.assertEqual(L.plan_values("gym", items, L.GYM[0], "gym · "), [])

    def test_a_start_word_alone_is_not_a_session(self):
        # gym rows are measured by their span only, never paired as start/end
        rows = [row(1, "2026-09-28 05:54:56", "start\npush", LOG, "gym"),
                row(2, "2026-09-28 07:00:00", "end", LOG, "gym")]
        items, _ = L.measure_kind("gym", rows, *L.GYM, paired=False)
        self.assertEqual(items, [])


class Ownership(unittest.TestCase):
    def test_a_persons_value_is_never_touched(self):
        rows = [row(1, "2026-10-07 16:25:09", "start"), row(2, "2026-10-07 17:06:23", "end", value_float=45.0, title="mine")]
        items, _ = L.measure_kind("drive", rows, *L.paired_kinds()[DRIVE])
        self.assertEqual(L.plan_values("drive", items, "minutes"), [])

    def test_own_value_follows_a_moved_start(self):
        rows = [row(1, "2026-10-07 16:15:09", "start"), row(2, "2026-10-07 17:06:23", "end", value_float=41.0, title="41 min")]
        items, _ = L.measure_kind("drive", rows, *L.paired_kinds()[DRIVE])
        self.assertEqual([(v, t) for _, _, v, t, _ in L.plan_values("drive", items, "minutes")], [(51, "51 min")])


class DryRun(unittest.TestCase):
    def run_measure(self, dry):
        kinds = {DRIVE: [row(1, "2026-10-07 16:25:09", "start"), row(2, "2026-10-07 17:06:23", "end")],
                 LOG: [row(3, "2026-10-14 09:34:23", "at gym", LOG,
                                      start_date="2026-10-14 09:34:23", end_date="2026-10-14 10:26:50")]}
        calls = []
        args = SimpleNamespace(dry_run=dry, quiet_minutes=30)
        with mock.patch.object(L, "list_kind", side_effect=lambda k, *a: [dict(r) for r in kinds.get(k, [])]), \
             mock.patch.object(L.subprocess, "run", side_effect=lambda cmd, **k: calls.append(cmd) or
                               mock.Mock(returncode=0, stderr="")), \
             mock.patch.object(L, "LOG_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "lcars-linker-test-none")), \
             mock.patch("os.makedirs"), mock.patch("builtins.open", mock.mock_open()) as op:
            out = io.StringIO()
            with redirect_stdout(out):
                L.cmd_measure(args)
        return out.getvalue(), calls, op

    def test_dry_run_prints_the_writes_and_makes_none(self):
        out, calls, op = self.run_measure(True)
        self.assertEqual(calls, [])
        op.assert_not_called()                          # no log file either
        self.assertIn("(DRY RUN)", out)
        self.assertIn(f"- {DRIVE} #2 (2026-10-07 17:06): value-float = 41, titled '41 min' — 41 min since #1", out)
        self.assertIn(f"- {LOG} #3 (2026-10-14 09:34): value-float = 52, titled 'gym · 52 min'", out)
        self.assertIn("**2 rows would change.**", out)

    def test_the_writing_pass_writes_the_same(self):
        out, calls, _ = self.run_measure(False)
        self.assertEqual([c[1:] for c in calls], [["set", "2", "--value-float", "41", "--title", "41 min"],
                                                  ["set", "3", "--value-float", "52", "--title", "gym · 52 min"]])
        self.assertIn("**2 rows updated.**", out)


if __name__ == "__main__":
    unittest.main()
