#!/usr/bin/env python3
"""Unit tests for the crew's one seat (scripts/seat.py) and the parts of
engineer.py and crew.py that use it. No herdr, no claude, no journal: the
decisions are pure, and the entries live in a stand-in server on a free
port that keeps rows in memory.

    python3 scripts/test_seat.py
"""

import atexit
import http.server
import io
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="lcars-seat-test-")
# Gone at the end, and when the run is killed (the tool's timeout, a closed
# terminal), which a unittest would otherwise outlive: it catches the
# SystemExit a handler could raise. Then the signal ends it as it would have.
atexit.register(shutil.rmtree, TMP, True)


def _killed(sig, _frame):
    shutil.rmtree(TMP, ignore_errors=True)
    signal.signal(sig, signal.SIG_DFL)
    os.kill(os.getpid(), sig)


for _sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(_sig, _killed)
with open(os.path.join(TMP, "env"), "w") as f:
    f.write("LCARS_CREW_USER=crew\nLCARS_CREW_PASS=pass\n")
# before the imports: these are read when the modules load
os.environ.update(LCARS_CREW_ENV=os.path.join(TMP, "env"), LCARS_ENG_STATE=os.path.join(TMP, "state"),
                  LCARS_ENG_ROOT=os.path.join(TMP, "eng"), LCARS_SEAT_SLICE_MIN="30")
os.environ.pop("LCARS_ENG_SEAT", None)
sys.path.insert(0, HERE)
import seat as S  # noqa: E402
import engineer as E  # noqa: E402
import crew as C  # noqa: E402

M = 60


class Journal:
    """A stand-in LCARS server: GET /entries (kind, done, order=id, dir,
    limit), POST /entries, PUT /entries/<id>, rows in memory."""

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
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
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

    def kind(self, k):
        return [r for r in self.rows if r["kind"] == k]


def queued(s):
    return [e["name"] for e in s["queue"]]


class Decisions(unittest.TestCase):
    def setUp(self):
        self.s = S.empty()
        self.t = 1_000_000

    def seat(self, name, since=None):
        self.s["holder"] = {"name": name, "since": since or self.t, "by": "start"}

    def test_a_free_seat_goes_to_the_first_with_work(self):
        S.want(self.s, "ada", "no1", self.t)
        s, acts = S.step(self.s, {}, self.t)
        self.assertEqual(acts, [("start", "ada")])
        self.assertEqual(s["holder"]["name"], "ada")
        self.assertEqual(s["queue"], [])

    def test_nobody_queued_keeps_the_one_seated_even_idle(self):
        self.seat("ada", self.t - 3 * SLICE_MIN())
        s, acts = S.step(self.s, {"ada": "idle"}, self.t)
        self.assertEqual(acts, [])
        self.assertEqual(s["holder"]["name"], "ada")

    def test_an_order_waits_for_the_turn_to_end(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        s, acts = S.step(self.s, {"ada": "working"}, self.t + 5 * M)
        self.assertEqual(acts, [])
        s, acts = S.step(s, {"ada": "idle"}, self.t + 6 * M)
        self.assertEqual(acts, [("stop", "ada"), ("start", "bob")])
        self.assertEqual(s["holder"]["name"], "bob")
        self.assertNotIn("ada", queued(s))

    def test_the_captain_s_message_goes_first_and_waits_for_the_turn(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        S.want(self.s, "cy", "captain", self.t)
        self.assertEqual(queued(self.s), ["cy", "bob"])
        self.assertIsNone(self.s["preempt"])
        s, acts = S.step(self.s, {"ada": "working"}, self.t + M)
        self.assertEqual(acts, [])
        s, acts = S.step(s, {"ada": "idle"}, self.t + 2 * M)
        self.assertEqual(acts, [("stop", "ada"), ("start", "cy")])

    def test_a_working_turn_is_never_cut_however_long(self):
        self.seat("ada")
        S.want(self.s, "bob", "captain", self.t)
        for mins in (30, 45, 90, 300):
            s, acts = S.step(self.s, {"ada": "working"}, self.t + mins * M)
            self.assertEqual(acts, [], f"cut at {mins} minutes")
            self.assertEqual(s["holder"]["name"], "ada")

    def test_the_captain_s_order_relieves_mid_turn(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        self.assertTrue(S.relieve(self.s, "cy", self.t))
        s, acts = S.step(self.s, {"ada": "working"}, self.t + M)
        self.assertEqual(acts[0][:2], ("relieve", "ada"))
        self.assertIn("captain", acts[0][2])
        self.assertEqual(acts[1], ("start", "cy"))
        # back in line, after those already waiting, to carry on
        self.assertEqual(queued(s), ["bob", "ada"])
        self.assertEqual(s["queue"][-1]["by"], "relieved")
        self.assertIsNone(s["preempt"])

    def test_the_captain_s_order_without_a_name_seats_the_first(self):
        self.seat("ada")
        self.assertFalse(S.relieve(self.s, None, self.t))  # nobody to seat
        self.assertFalse(S.relieve(self.s, "ada", self.t))  # already seated
        S.want(self.s, "bob", "no1", self.t)
        self.assertTrue(S.relieve(self.s, None, self.t))
        s, acts = S.step(self.s, {"ada": "working"}, self.t)
        self.assertEqual([a[0] for a in acts], ["relieve", "start"])
        self.assertEqual(acts[1], ("start", "bob"))

    def test_a_question_left_on_screen_is_cut_after_the_slice(self):
        self.seat("ada")
        S.want(self.s, "bob", "captain", self.t)
        s, acts = S.step(self.s, {"ada": "blocked"}, self.t)
        self.assertEqual(acts, [])
        s, acts = S.step(s, {"ada": "blocked"}, self.t + SLICE_MIN() - M)
        self.assertEqual(acts, [])
        s, acts = S.step(s, {"ada": "blocked"}, self.t + SLICE_MIN())
        self.assertEqual([a[0] for a in acts], ["relieve", "start"])
        self.assertIn("at a question for 30 minutes", acts[0][2])

    def test_an_answered_question_restarts_the_clock(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        s, _ = S.step(self.s, {"ada": "blocked"}, self.t)
        s, _ = S.step(s, {"ada": "working"}, self.t + 20 * M)
        self.assertNotIn("blocked", s["holder"])
        s, acts = S.step(s, {"ada": "blocked"}, self.t + 40 * M)
        self.assertEqual(acts, [])

    def test_a_stuck_holder_is_relieved_only_when_others_wait(self):
        self.seat("ada")
        s, acts = S.step(self.s, {"ada": "stuck"}, self.t)
        self.assertEqual(acts, [])
        S.want(s, "bob", "no1", self.t)
        s, acts = S.step(s, {"ada": "stuck"}, self.t)
        self.assertEqual([a[0] for a in acts], ["relieve", "start"])
        self.assertIn("no sign of work", acts[0][2])

    def test_done_stands_down_even_with_nobody_waiting(self):
        self.seat("ada")
        S.yielded(self.s, "ada", "", self.t)
        s, acts = S.step(self.s, {"ada": "working"}, self.t)
        self.assertEqual(acts, [])  # the turn is still going
        s, acts = S.step(s, {"ada": "idle"}, self.t)
        self.assertEqual(acts, [("stop", "ada")])
        self.assertIsNone(s["holder"])

    def test_a_handover_goes_first(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        S.yielded(self.s, "ada", "cy", self.t)
        self.assertEqual(queued(self.s), ["cy", "bob"])
        s, acts = S.step(self.s, {"ada": "idle"}, self.t)
        self.assertEqual(acts, [("stop", "ada"), ("start", "cy")])

    def test_one_who_left_frees_the_seat(self):
        self.seat("ada")
        S.want(self.s, "bob", "no1", self.t)
        s, acts = S.step(self.s, {"ada": "off"}, self.t)
        self.assertEqual(acts, [("start", "bob")])

    def test_a_scheduled_run_is_never_cut(self):
        self.s["holder"] = {"name": "crew:qa", "since": self.t - 80 * M, "by": "scheduled", "pid": 1}
        S.want(self.s, "bob", "captain", self.t)
        S.relieve(self.s, None, self.t)
        s, acts = S.step(self.s, {"crew:qa": "alive"}, self.t)
        self.assertEqual(acts, [])
        s, acts = S.step(s, {"crew:qa": "off"}, self.t)
        self.assertEqual(acts, [("start", "bob")])

    def test_a_scheduled_run_waits_and_is_granted(self):
        self.seat("ada")
        S.want(self.s, "crew:ops", "scheduled", self.t, pid=42)
        s, acts = S.step(self.s, {"ada": "idle", "crew:ops": "alive"}, self.t)
        self.assertEqual(acts, [("stop", "ada"), ("grant", "crew:ops")])
        self.assertEqual(s["holder"]["pid"], 42)

    def test_a_scheduled_run_that_gave_up_leaves_the_queue(self):
        self.seat("ada")
        S.want(self.s, "crew:ops", "scheduled", self.t, pid=42)
        s, acts = S.step(self.s, {"ada": "idle"}, self.t)
        self.assertEqual(acts, [])
        self.assertEqual(s["queue"], [])

    def test_wanting_the_one_seated_changes_nothing(self):
        self.seat("ada")
        S.want(self.s, "ada", "captain", self.t)
        S.want(self.s, "bob", "no1", self.t)
        S.want(self.s, "bob", "no1", self.t + 1)
        self.assertEqual(queued(self.s), ["bob"])
        self.assertIsNone(self.s["preempt"])

    def test_a_turn_without_yield_waits_on_an_answer(self):
        self.seat("ada")
        S.turn_ended(self.s, "ada", self.t)
        self.assertIn("ada", self.s["waiting"])
        s, _ = S.step(self.s, {"ada": "working"}, self.t)
        self.assertNotIn("ada", s["waiting"])
        self.assertNotIn("idle", s["holder"])

    def test_a_turn_that_only_answered_the_ship_s_note_frees_the_seat(self):
        # reyes-c20, 2026-10-14: seated by report for a deploy's note, a
        # line in answer, no yield - and shown seated, waiting, all night
        S.want(self.s, "ada", S.SHIP, self.t)
        s, acts = S.step(self.s, {}, self.t)
        self.assertEqual(acts, [("start", "ada")])
        S.turn_ended(s, "ada", self.t + 60)
        self.assertEqual(s["waiting"], {})
        self.assertTrue(s["holder"]["yielded"])
        self.assertEqual(s["log"][-1][1], "ada is done, a ship's note answered")
        s, acts = S.step(s, {"ada": "idle"}, self.t + 62)
        self.assertEqual(acts, [("stop", "ada")])
        self.assertIsNone(s["holder"])
        self.assertEqual(s["waiting"], {})
        self.assertTrue(S.render(s, self.t + 62)[0].startswith("Seat: empty"))

    def test_a_turn_after_a_person_s_order_still_waits(self):
        S.want(self.s, "ada", "no1", self.t)
        s, _ = S.step(self.s, {}, self.t)
        S.turn_ended(s, "ada", self.t + 60)
        self.assertIn("ada", s["waiting"])
        self.assertFalse(s["holder"].get("yielded"))
        s, acts = S.step(s, {"ada": "idle"}, self.t + 62)
        self.assertEqual(acts, [])
        self.assertEqual(s["holder"]["name"], "ada")
        self.assertIn("ada", s["waiting"])

    def test_the_ship_s_note_to_the_one_seated_marks_only_its_own_turn(self):
        self.seat("ada")
        # between turns, a deploy's note: the ship's turn
        S.want(self.s, "ada", S.SHIP, self.t)
        S.turn_ended(self.s, "ada", self.t + 1)
        self.assertTrue(self.s["holder"].get("yielded"))
        # a person's order and the ship's note for one turn: the person's,
        # whichever came first
        for order in ([S.SHIP, "captain"], ["captain", S.SHIP]):
            self.seat("ada")
            for by in order:
                S.want(self.s, "ada", by, self.t)
            S.turn_ended(self.s, "ada", self.t + 1)
            self.assertIn("ada", self.s["waiting"], order)
            self.assertFalse(self.s["holder"].get("yielded"), order)
            self.s["waiting"] = {}
        # the mark is the one turn's: the next, typed in by the captain
        # without the seat (the Claude app), waits as before
        self.seat("ada")
        S.want(self.s, "ada", S.SHIP, self.t)
        self.s["holder"]["yielded"] = None
        S.turn_ended(self.s, "ada", self.t + 1)
        self.assertNotIn("turn", self.s["holder"])
        self.s["holder"].pop("yielded")
        S.turn_ended(self.s, "ada", self.t + 2)
        self.assertIn("ada", self.s["waiting"])

    def test_a_yield_after_a_ship_s_note_is_logged_once(self):
        S.want(self.s, "ada", S.SHIP, self.t)
        s, _ = S.step(self.s, {}, self.t)
        S.yielded(s, "ada", None, self.t + 1)
        S.turn_ended(s, "ada", self.t + 2)
        self.assertEqual([x for _, x in s["log"]].count("ada is done"), 1)
        self.assertNotIn("ada is done, a ship's note answered", [x for _, x in s["log"]])

    def test_step_does_not_change_its_input(self):
        S.want(self.s, "ada", "no1", self.t)
        before = json.dumps(self.s, sort_keys=True)
        S.step(self.s, {}, self.t)
        self.assertEqual(json.dumps(self.s, sort_keys=True), before)


def SLICE_MIN():
    return S.SLICE


class Edits(unittest.TestCase):
    """The captain's edits of the line: move, remove, restore (pure)."""

    def setUp(self):
        self.s = S.empty()
        self.t = 1_000_000
        self.s["holder"] = {"name": "hal", "since": self.t, "by": "start"}
        for n in ("ada", "bob", "cy"):
            S.want(self.s, n, "no1", self.t)

    def test_move_up_down_first_and_the_ends_stay_put(self):
        self.assertTrue(S.move(self.s, "cy", "up", self.t))
        self.assertEqual(queued(self.s), ["ada", "cy", "bob"])
        self.assertTrue(S.move(self.s, "ada", "down", self.t))
        self.assertEqual(queued(self.s), ["cy", "ada", "bob"])
        self.assertTrue(S.move(self.s, "bob", "first", self.t))
        self.assertEqual(queued(self.s), ["bob", "cy", "ada"])
        self.assertFalse(S.move(self.s, "bob", "up", self.t))
        self.assertFalse(S.move(self.s, "ada", "down", self.t))
        self.assertIn("moved first", self.s["log"][-1][1])

    def test_a_line_that_changed_since_it_was_read_is_refused_untouched(self):
        before = json.dumps(self.s, sort_keys=True)
        with self.assertRaises(S.Changed):
            S.move(self.s, "cy", "up", self.t, expect=["ada", "bob"])
        with self.assertRaises(S.Changed):
            S.remove(self.s, "cy", self.t, [], expect=["bob", "ada", "cy"])
        self.assertEqual(json.dumps(self.s, sort_keys=True), before)
        S.move(self.s, "cy", "up", self.t, expect=["ada", "bob", "cy"])
        self.assertEqual(queued(self.s), ["ada", "cy", "bob"])

    def test_never_the_one_seated(self):
        for f in (lambda: S.move(self.s, "hal", "first", self.t), lambda: S.remove(self.s, "hal", self.t, [])):
            with self.assertRaises(S.Changed):
                f()
        self.assertEqual(self.s["holder"]["name"], "hal")

    def test_remove_and_restore_put_them_back_in_their_place(self):
        self.s["preempt"] = "bob"
        rec = S.remove(self.s, "bob", self.t, [{"id": 7, "title": "bob ← No.1: x"}])
        self.assertEqual(queued(self.s), ["ada", "cy"])
        self.assertIsNone(self.s["preempt"])
        self.assertEqual((rec["at"], rec["orders"]), (1, [{"id": 7, "title": "bob ← No.1: x"}]))
        # a step now seats nobody removed
        s, acts = S.step(self.s, {"hal": "idle"}, self.t)
        self.assertEqual(acts, [("stop", "hal"), ("start", "ada")])
        back = S.restore(self.s, None, self.t + 1)
        self.assertEqual(back["name"], "bob")
        self.assertEqual(queued(self.s), ["ada", "bob", "cy"])
        self.assertEqual(self.s["queue"][1]["by"], "no1")
        self.assertEqual(self.s["removed"], [])
        with self.assertRaises(S.Changed):
            S.restore(self.s, None, self.t)

    def test_restore_after_the_line_moved_on(self):
        S.remove(self.s, "cy", self.t, [])
        S.remove(self.s, "ada", self.t, [])
        self.s["queue"] = []  # bob was seated meanwhile
        S.restore(self.s, "cy", self.t)
        self.assertEqual(queued(self.s), ["cy"])
        # queued again by a new order: moved back to where they were, once
        S.want(self.s, "ada", "no1", self.t)
        S.restore(self.s, "ada", self.t)
        self.assertEqual(queued(self.s), ["ada", "cy"])
        # seated meanwhile: left there
        S.remove(self.s, "cy", self.t, [])
        self.s["holder"] = {"name": "cy", "since": self.t, "by": "start"}
        S.restore(self.s, "cy", self.t)
        self.assertEqual(queued(self.s), ["ada"])

    def test_removals_survive_the_entry_and_are_capped(self):
        for i in range(S.REMOVED_MAX + 3):
            S.want(self.s, f"e{i}", "no1", self.t)
            S.remove(self.s, f"e{i}", self.t, [])
        s = S.normal(json.loads(json.dumps(self.s)))
        self.assertEqual(len(s["removed"]), S.REMOVED_MAX)
        self.assertEqual(s["removed"][-1]["name"], f"e{S.REMOVED_MAX + 2}")
        self.assertEqual(S.normal({"removed": [{"name": "x"}, 3]})["removed"], [])


class Edited(unittest.TestCase):
    def test_a_hand_edited_state_is_made_whole(self):
        s = S.normal({"holder": {"name": "ada"}, "queue": ["bob", {"name": "bob"}, "ada", {"name": "cy", "by": "no1"}],
                      "preempt": "zed", "waiting": {"x": "soon"}})
        self.assertEqual(queued(s), ["bob", "cy"])
        self.assertEqual(s["queue"][0]["by"], "captain")
        self.assertIsNone(s["preempt"])
        self.assertEqual(s["waiting"], {})
        self.assertIn("since", s["holder"])

    def test_not_an_object_is_refused(self):
        with self.assertRaises(S.Broken):
            S.normal([1, 2])


class Store(unittest.TestCase):
    def setUp(self):
        self.j = Journal()
        os.environ["LCARS_URL"] = self.j.url

    def tearDown(self):
        self.j.httpd.shutdown()
        self.j.httpd.server_close()

    def test_the_state_round_trips_through_one_entry(self):
        rid, s = S.read()
        self.assertIsNone(rid)
        S.want(s, "ada", "captain", 1_000_000)
        rid = S.write(rid, s, 1_000_000, "vps")
        S.write(rid, s, 1_000_000, "vps")
        self.assertEqual(len(self.j.kind("crew_seat")), 1)
        row = self.j.kind("crew_seat")[0]
        self.assertIn("1 waiting", row["title"])
        self.assertIn("**Queue:** 1. ada", row["content"])
        rid2, s2 = S.read()
        self.assertEqual((rid2, s2), (rid, s))

    def test_a_broken_block_stops_the_seat(self):
        S.write(None, S.empty(), 1_000_000)
        self.j.rows[0]["content"] = self.j.rows[0]["content"].replace('"queue"', 'queue')
        with self.assertRaises(S.Broken):
            S.read()

    def test_a_down_journal_is_down(self):
        self.j.down = True
        with self.assertRaises(S.Down):
            S.read()

    def test_changing_writes_only_a_change(self):
        state = os.path.join(TMP, "lock1")
        with S.changing(state) as s:
            S.want(s, "ada", "no1", 1_000_000)
        with S.changing(state) as s:
            pass
        self.assertEqual(len(self.j.kind("crew_seat")), 1)
        with mock.patch.object(S, "write") as w:
            with S.changing(state) as s:
                pass
            w.assert_not_called()

    def test_the_inbox_is_per_name_and_ticked_done(self):
        S.inbox_add("ada", "captain", "first\nmore")
        S.inbox_add("adam", "No.1", "not hers")
        S.inbox_add("ada", "bob", "second")
        got = S.inbox("ada")
        self.assertEqual([r["content"] for r in got], ["first\nmore", "second"])
        self.assertEqual(got[0]["title"], "ada ← captain: first")
        S.inbox_done(got[0]["id"])
        self.assertEqual([r["content"] for r in S.inbox("ada")], ["second"])


class Engineer(unittest.TestCase):
    """engineer.py's side, with herdr stood in for by no running sessions."""

    def setUp(self):
        self.j = Journal()
        os.environ["LCARS_URL"] = self.j.url
        os.makedirs(E.STATE, exist_ok=True)
        for n in ("ada", "bob"):
            E.save(n, {"name": n, "session": "s-" + n, "title": n.title()})
        self.p = [mock.patch.object(E, "agent_info", return_value=None),
                  mock.patch.object(E, "engineer_tab", return_value=None),
                  mock.patch.object(E, "seat_move_later")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.j.httpd.shutdown()
        self.j.httpd.server_close()

    def call(self, fn, *a):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            fn(*a)
        return cm.exception.code, json.loads(buf.getvalue())

    def test_the_seat_is_production_s_and_never_number_one_s(self):
        self.assertTrue(E.seated("ada"))
        self.assertFalse(E.seated(E.NO1))
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"}):
            self.assertFalse(E.seated("ada"))

    def test_a_message_to_one_off_duty_waits_in_their_inbox(self):
        with mock.patch("sys.stdin", io.StringIO("[No.1] fix the header")):
            code, r = self.call(E.cmd_say, "ada")
        self.assertEqual(code, 0)
        self.assertTrue(r["queued"])
        self.assertEqual(r["seat"]["queue"], ["ada"])
        self.assertEqual([x["title"] for x in S.inbox("ada")], ["ada ← No.1: [No.1] fix the header"])
        self.assertTrue(E.load("ada").get("under_no1"))

    def test_a_deploy_s_outcome_is_kept_for_one_off_duty(self):
        self.assertTrue(E.tell("bob", "[deploy finished] live"))
        self.assertEqual([x["content"] for x in S.inbox("bob")], ["[deploy finished] live"])
        self.assertFalse(E.tell("bob", "lost", inbox=False))

    def test_a_deploy_s_outcome_typed_to_the_one_seated_is_the_ship_s_turn(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "no1"}
        typed = []
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "agent", return_value="pane"), \
                mock.patch.object(E, "submit_if_left"), \
                mock.patch.object(E, "herdr", side_effect=lambda *a, **k: (typed.append(a), ("", ""))[1]):
            self.assertTrue(E.tell("ada", "[deploy finished] live"))
            # not bob's: the seat is ada's, and nothing of bob's is marked
            self.assertTrue(E.tell("bob", "[deploy finished] live"))
        self.assertEqual(len(typed), 2)
        _, s = S.read()
        self.assertEqual(s["holder"]["turn"], S.SHIP)
        self.assertEqual(queued(s), [])
        with mock.patch.object(E, "seat_move"), mock.patch.object(E.time, "sleep"):
            self.call(E.cmd_seat_turn_ended, "ada")
        _, s = S.read()
        self.assertTrue(s["holder"]["yielded"])
        self.assertEqual(s["waiting"], {})

    def test_a_deploy_s_outcome_into_a_running_turn_is_that_turn_s(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "no1"}
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}), \
                mock.patch.object(E, "agent", return_value="pane"), \
                mock.patch.object(E, "submit_if_left"), \
                mock.patch.object(E, "herdr", return_value=("", "")):
            self.assertTrue(E.tell("ada", "[deploy finished] live"))
        _, s = S.read()
        self.assertNotIn("turn", s["holder"])

    def test_yield_hands_over_with_a_message(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "start"}
        code, r = self.call(E.cmd_yield, "ada", "bob", "finish the tests")
        self.assertEqual(code, 0)
        _, s = S.read()
        self.assertTrue(s["holder"]["yielded"])
        self.assertEqual(queued(s), ["bob"])
        self.assertEqual([x["content"] for x in S.inbox("bob")], ["[from Ada] finish the tests"])
        code, r = self.call(E.cmd_yield, "ada", "nobody", "")
        self.assertEqual(code, 2)

    def test_a_scheduled_run_takes_a_free_seat_and_gives_it_back(self):
        with E.seat_hold("crew:ops", 5, step=0.1) as (ok, why):
            self.assertTrue(ok, why)
            _, s = S.read()
            self.assertEqual(s["holder"]["name"], "crew:ops")
        _, s = S.read()
        self.assertIsNone(s["holder"])

    def test_a_scheduled_run_gives_up_on_a_busy_seat(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": int(time.time()), "by": "start"}
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}):
            with E.seat_hold("crew:ops", 0.3, step=0.1) as (ok, why):
                self.assertFalse(ok)
        self.assertIn("held by ada", why)
        _, s = S.read()
        self.assertEqual(s["queue"], [])
        self.assertEqual(s["holder"]["name"], "ada")

    def test_a_silent_working_holder_is_stuck_a_writing_one_is_not(self):
        path = os.path.join(TMP, "s-ada.jsonl")
        open(path, "w").close()
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "start"}
        _, s = S.read()
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}), \
                mock.patch.object(E, "transcript", return_value=path):
            now = os.path.getmtime(path)
            self.assertEqual(E.seat_facts(s, now + S.SLICE - 60)["ada"], "working")
            self.assertEqual(E.seat_facts(s, now + S.SLICE)["ada"], "stuck")
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "blocked"}), \
                mock.patch.object(E, "transcript", return_value=path):
            self.assertEqual(E.seat_facts(s, now + S.SLICE)["ada"], "blocked")

    def test_seat_relieve_is_the_captain_s_order(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "start"}
        code, r = self.call(E.cmd_seat_relieve, None)
        self.assertEqual(code, 3)  # nobody else to seat
        code, r = self.call(E.cmd_seat_relieve, "zed")
        self.assertEqual(code, 2)
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}), \
                mock.patch.object(E, "seat_relieve") as rel, mock.patch.object(E, "seat_start", return_value=True):
            code, r = self.call(E.cmd_seat_relieve, "bob")
        self.assertEqual(code, 0, r)
        rel.assert_called_once()
        self.assertEqual(rel.call_args[0][0], "ada")
        self.assertEqual(r["seat"]["holder"], "bob")
        self.assertEqual(r["seat"]["queue"], ["ada"])

    def line(self, *names, holder="hal"):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": holder, "since": 1, "by": "start"}
            s["queue"] = [{"name": n, "t": 1, "by": "no1"} for n in names]

    def test_queue_move_and_a_stale_line_is_a_409(self):
        self.line("ada", "bob")
        code, r = self.call(E.queue_edit, "move", "bob", "up", "ada,bob")
        self.assertEqual(code, 0, r)
        self.assertEqual(r["seat"]["queue"], ["bob", "ada"])
        code, r = self.call(E.queue_edit, "move", "bob", "down", "ada,bob")
        self.assertEqual(code, 3)
        self.assertEqual(r["seat"]["queue"], ["bob", "ada"])  # what it is now, to paint
        code, r = self.call(E.queue_edit, "move", "hal", "first", "")
        self.assertEqual(code, 3)
        self.assertEqual(self.call(E.queue_edit, "move", "bob", "sideways", "")[0], 2)
        self.assertEqual(self.call(E.queue_edit, "remove", "crew:ops", "", "")[0], 2)
        self.assertEqual(self.call(E.queue_edit, "remove", "a;b", "", "")[0], 2)

    def test_queue_remove_cancels_their_orders_and_restore_revives_them(self):
        self.line("ada", "bob")
        S.inbox_add("bob", "No.1", "[No.1] fix the header")
        S.inbox_add("bob", "captain", "and the footer")
        S.inbox_add("ada", "No.1", "hers")
        code, r = self.call(E.queue_edit, "remove", "bob", "", "ada,bob")
        self.assertEqual(code, 0, r)
        self.assertEqual((r["seat"]["queue"], r["cancelled"]), (["ada"], 2))
        self.assertEqual(S.inbox("bob"), [])
        gone = [x for x in self.j.kind("crew_inbox") if x["title"].startswith(S.CANCELLED)]
        self.assertEqual([x["done_bool"] for x in gone], [1, 1])
        self.assertEqual(S.inbox_to(gone[0])[0], "[cancelled] bob")  # never counted as delivered to bob
        self.assertEqual(len(S.inbox("ada")), 1)
        # the seat moving on does not start them
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}),                 mock.patch.object(E, "seat_start", return_value=True) as start:
            E.seat_move()
        self.assertEqual([c[0][0] for c in start.call_args_list], ["ada"])
        # undo: back in their place, both orders live again, in order
        self.line("cy", "dan", holder="ada")
        code, r = self.call(E.queue_edit, "restore", "", "", "")
        self.assertEqual(code, 0, r)
        self.assertEqual((r["name"], r["restored"], r["seat"]["queue"]), ("bob", 2, ["cy", "bob", "dan"]))
        self.assertEqual([x["content"] for x in S.inbox("bob")], ["[No.1] fix the header", "and the footer"])
        self.assertEqual(self.call(E.queue_edit, "restore", "", "", "")[0], 3)

    def test_a_cancel_that_fails_part_way_changes_nothing(self):
        self.line("ada", "bob")
        S.inbox_add("bob", "No.1", "one")
        S.inbox_add("bob", "No.1", "two")
        real, n = S.inbox_cancel, []

        def flaky(row):
            if n:
                raise S.Down("restarting")
            n.append(1)
            real(row)
        with mock.patch.object(S, "inbox_cancel", side_effect=flaky):
            code, r = self.call(E.queue_edit, "remove", "bob", "", "ada,bob")
        self.assertEqual(code, 3)
        _, s = S.read()
        self.assertEqual(queued(s), ["ada", "bob"])
        self.assertEqual(s["removed"], [])
        self.assertEqual([x["content"] for x in S.inbox("bob")], ["one", "two"])

    def test_an_edit_racing_a_handoff_waits_for_the_lock_and_sees_it(self):
        # the seat's move holds seat.lock while it seats the head of the
        # line; a press made on the line before that waits, then finds the
        # line it saw gone: a 409, and nothing done
        self.line("ada", "bob")
        inside, go = threading.Event(), threading.Event()

        def handoff():
            with S.changing(E.STATE) as s:
                inside.set()
                go.wait(5)
                s["holder"] = {"name": "ada", "since": 2, "by": "no1"}
                s["queue"] = s["queue"][1:]
        th = threading.Thread(target=handoff)
        th.start()
        inside.wait(5)
        res = {}

        def press():
            res["r"] = self.call(E.queue_edit, "move", "bob", "first", "ada,bob")
        tp = threading.Thread(target=press)
        tp.start()
        time.sleep(0.3)
        self.assertTrue(tp.is_alive())  # waiting on seat.lock
        go.set()
        th.join(5)
        tp.join(5)
        self.assertEqual(res["r"][0], 3)
        self.assertEqual(res["r"][1]["seat"], {"holder": "ada", "queue": ["bob"], "waiting": [],
                                                  "jobs": {"running": None, "runs": [], "queue": [], "recent": [],
                                                  "line": "no job running"}})
        _, s = S.read()
        self.assertEqual((s["holder"]["name"], queued(s)), ("ada", ["bob"]))

    def test_a_start_into_a_held_seat_only_makes_ready(self):
        with S.changing(E.STATE) as s:
            s["holder"] = {"name": "ada", "since": 1, "by": "start"}
        with mock.patch.object(E, "cmd_start") as start, mock.patch.object(E, "prepare") as prep, \
                mock.patch.object(E, "cmd_poll", side_effect=lambda *a: E.out({"status": "off"})):
            self.call(E.seat_gate_start, "bob", "{}")
            start.assert_not_called()
            prep.assert_called_once()
            E.seat_gate_start("ada", "{}")
            start.assert_called_once()


class Fresh(unittest.TestCase):
    """say --fresh: an order for a new task, into a cleared conversation -
    at once, or from the inbox when the seat comes to them."""

    def setUp(self):
        self.j = Journal()
        os.environ["LCARS_URL"] = self.j.url
        os.makedirs(E.STATE, exist_ok=True)
        E.save("ada", {"name": "ada", "session": "s-ada", "title": "Ada", "task": "old work"})
        self.typed = []
        self.p = [mock.patch.object(E, "engineer_tab", return_value=None),
                  mock.patch.object(E, "seat_move_later"), mock.patch.object(E, "sync_to_base"),
                  mock.patch.object(E, "submit_if_left"),
                  mock.patch.object(E, "herdr", side_effect=lambda *a, **k: (self.typed.append(a[3]), ({}, None))[1])]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.j.httpd.shutdown()
        self.j.httpd.server_close()

    def say(self, text, fresh, status):
        buf = io.StringIO()
        with mock.patch.object(E, "agent_info", return_value={"agent_status": status} if status else None), \
                mock.patch("sys.stdin", io.StringIO(text)), redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            E.cmd_say("ada", fresh)
        return cm.exception.code, json.loads(buf.getvalue())

    def test_the_mark_is_on_the_sender_not_the_text(self):
        self.assertTrue(S.inbox_fresh({"title": S.inbox_title("ada", "No.1", "new task", True)}))
        self.assertFalse(S.inbox_fresh({"title": S.inbox_title("ada", "No.1", "x [fresh]: y")}))
        self.assertFalse(S.inbox_fresh({"title": "ada ← captain: hello"}))

    def test_queued_for_the_seat_it_is_marked(self):
        code, r = self.say("[No.1] new task", True, None)
        self.assertEqual(code, 0)
        self.assertTrue(r["queued"])
        self.assertTrue(S.inbox_fresh(S.inbox("ada")[0]))

    def test_the_seat_clears_once_then_delivers_them_all(self):
        S.inbox_add("ada", "seat", "[deploy finished] old")
        S.inbox_add("ada", "No.1", "[No.1] new task", fresh=True)
        S.inbox_add("ada", "No.1", "[No.1] and this")
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "clear_session", return_value=(0, {"cleared": True})) as clr, \
                mock.patch.object(E, "tell", return_value=True) as tell:
            self.assertTrue(E.seat_deliver("ada", wait=1))
        clr.assert_called_once_with("ada", "old work")
        tell.assert_called_once()
        self.assertEqual(tell.call_args[0][1], "[deploy finished] old\n\n[No.1] new task\n\n[No.1] and this")
        self.assertEqual(S.inbox("ada"), [])

    def test_delivery_types_the_order_as_the_entry_holds_it_then(self):
        # the captain edits a waiting order (the console's Inbox, Open): what
        # is typed is the entry's content at delivery, not the queued copy,
        # and a [No.1] mark his edit dropped is put back
        a = S.inbox_add("ada", "No.1", "[No.1] fix the header")
        b = S.inbox_add("ada", "ship", "[ship] a note")
        next(r for r in self.j.rows if r["id"] == a)["content"] = "fix the header and the footer"
        next(r for r in self.j.rows if r["id"] == b)["content"] = "[ship] a note, edited"
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "tell", return_value=True) as tell:
            self.assertTrue(E.seat_deliver("ada", wait=1))
        self.assertEqual(tell.call_args[0][1], "[No.1] fix the header and the footer\n\n[ship] a note, edited")
        self.assertEqual(S.inbox("ada"), [])

    def test_a_failed_clear_still_delivers_from_the_inbox(self):
        S.inbox_add("ada", "No.1", "[No.1] new task", fresh=True)
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "clear_session", return_value=(1, {"error": "no"})), \
                mock.patch.object(E, "tell", return_value=True) as tell:
            self.assertTrue(E.seat_deliver("ada", wait=1))
        tell.assert_called_once()
        self.assertEqual(S.inbox("ada"), [])

    def test_no_clear_without_a_fresh_row(self):
        S.inbox_add("ada", "No.1", "[No.1] more of the same")
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "clear_session") as clr, mock.patch.object(E, "tell", return_value=True):
            E.seat_deliver("ada", wait=1)
        clr.assert_not_called()

    def test_at_once_it_clears_then_types(self):
        with mock.patch.object(E, "clear_session", side_effect=lambda *a: (self.typed.append("/clear"), (0, {"cleared": True}))[1]):
            code, r = self.say("[No.1] new task", True, "idle")
        self.assertEqual(code, 0)
        self.assertEqual(self.typed, ["/clear", "[No.1] new task"])
        self.assertTrue(r["cleared"])

    def test_a_failed_clear_at_once_still_types_the_order(self):
        with mock.patch.object(E, "clear_session", return_value=(1, {"error": "not delivered"})):
            code, r = self.say("[No.1] new task", True, "idle")
        self.assertEqual(code, 0)
        self.assertEqual(self.typed, ["[No.1] new task"])
        self.assertFalse(r["cleared"])
        self.assertIn("not cleared", r["warning"])

    def test_one_at_work_is_not_cleared_mid_turn(self):
        with mock.patch.object(E, "clear_session") as clr:
            code, r = self.say("[No.1] new task", True, "working")
        self.assertEqual(code, 3)
        clr.assert_not_called()
        self.assertEqual(self.typed, [])

    def test_number_one_s_crew_say_passes_fresh_on(self):
        import no1
        with mock.patch.object(no1, "engineer", return_value=(0, {"ok": True})) as eng:
            no1.crew(["say", "ada", "--fresh", "new", "task"])
            no1.crew(["say", "ada", "more"])
        self.assertEqual(eng.call_args_list[0], mock.call("say", "ada", "--fresh", inp="[No.1] new task"))
        self.assertEqual(eng.call_args_list[1], mock.call("say", "ada", inp="[No.1] more"))

    def test_a_plain_order_does_not_clear(self):
        with mock.patch.object(E, "clear_session") as clr:
            code, r = self.say("[No.1] go on", False, "idle")
        self.assertEqual(code, 0)
        clr.assert_not_called()
        self.assertNotIn("cleared", r)


class SyncToBase(unittest.TestCase):
    """A new order moves a clean branch with nothing of its own to the live
    branch; anything of the engineer's is left alone. A real repository in
    the temp directory: deb, and ada's worktree on eng/ada."""

    def setUp(self):
        import subprocess
        self.sh = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd or self.repo, check=True,
                                                      capture_output=True, text=True).stdout.strip()
        self.repo = os.path.join(TMP, "repo")
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(E.wt("ada"), ignore_errors=True)
        os.makedirs(self.repo)
        self.sh("init", "-q", "-b", "deb")
        self.sh("config", "user.email", "t@t")
        self.sh("config", "user.name", "t")
        self.commit(self.repo, "a")
        self.sh("worktree", "add", "-q", "-b", "eng/ada", E.wt("ada"))
        self.commit(self.repo, "b")  # deb moves on
        self.p = [mock.patch.object(E, "live_branch", return_value="deb")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def commit(self, d, f):
        with open(os.path.join(d, f), "w") as fh:
            fh.write(f)
        self.sh("add", f, cwd=d)
        self.sh("commit", "-q", "-m", f, cwd=d)

    def head(self, ref="HEAD", d=None):
        return self.sh("rev-parse", ref, cwd=d)

    def test_a_clean_branch_with_nothing_of_its_own_moves_to_deb(self):
        self.assertEqual(E.sync_to_base("ada"), "moved")
        self.assertEqual(self.head(d=E.wt("ada")), self.head("deb"))
        self.assertEqual(E.sync_to_base("ada"), "current")

    def test_a_dirty_tree_is_left_alone(self):
        before = self.head(d=E.wt("ada"))
        with open(os.path.join(E.wt("ada"), "a"), "w") as f:
            f.write("changed")
        self.assertEqual(E.sync_to_base("ada"), "dirty")
        with open(os.path.join(E.wt("ada"), "a"), "w") as f:
            f.write("a")
        open(os.path.join(E.wt("ada"), "new"), "w").close()  # untracked is theirs too
        self.assertEqual(E.sync_to_base("ada"), "dirty")
        self.assertEqual(self.head(d=E.wt("ada")), before)

    def test_unmerged_commits_are_left_alone(self):
        self.commit(E.wt("ada"), "mine")
        before = self.head(d=E.wt("ada"))
        self.assertEqual(E.sync_to_base("ada"), "has commits")
        self.assertEqual(self.head(d=E.wt("ada")), before)

    def test_an_order_to_an_idle_engineer_syncs_first(self):
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}), \
                mock.patch.object(E, "herdr", return_value=({}, None)), mock.patch.object(E, "submit_if_left"), \
                mock.patch("sys.stdin", io.StringIO("[No.1] next task")), redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit):
            E.cmd_say("ada")
        self.assertEqual(self.head(d=E.wt("ada")), self.head("deb"))

    def test_a_busy_engineer_is_not_touched(self):
        before = self.head(d=E.wt("ada"))
        with mock.patch.object(E, "agent_info", return_value={"agent_status": "working"}), \
                mock.patch.object(E, "herdr", return_value=({}, None)), mock.patch.object(E, "submit_if_left"), \
                mock.patch("sys.stdin", io.StringIO("[No.1] next task")), redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit):
            E.cmd_say("ada")
        self.assertEqual(self.head(d=E.wt("ada")), before)


class Crew(unittest.TestCase):
    def test_no_seat_where_it_is_switched_off(self):
        with mock.patch.dict(os.environ, {"LCARS_ENG_SEAT": "0"}), mock.patch.object(E, "seat_hold") as h:
            with C.seat("ops", 10) as (ok, why):
                self.assertTrue(ok)
            h.assert_not_called()

    def test_a_run_queues_for_the_seat(self):
        with mock.patch.object(E, "seat_hold") as h:
            h.return_value.__enter__.return_value = (True, "")
            with C.seat("ops", 10) as (ok, why):
                self.assertTrue(ok)
            h.assert_called_once_with("crew:ops", 10)


if __name__ == "__main__":
    unittest.main()
