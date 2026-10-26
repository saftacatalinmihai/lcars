#!/usr/bin/env python3
"""Unit tests for rooms, slice 1 (docs/design/rooms.md, section 14.1):
rooms.py's header parser (and the page's copy of it, index.html's
ROOM_HEAD, under node), its titles and rows; and engineer.py's side - a
crew_msg row from every send (a say to Number One or an engineer, an order
of Number One's queued or typed, an engineer's report through the Stop
hook, Number One's own last message cut by room lines, the flusher's notes,
the retry unit's), delivery ticking them, a cancel marking them; the
routing by header with the fallback and a misroute; crew_room rows from the
labels' verbs; threads v2's names read as rooms (no1_thread, by_thread,
LCARS_THREAD_BY, `[thread x]`, the inbox's #mark); and rooms-migrate's dry
run (nothing written) and --apply twice (the second writes nothing).

The journal is test_no1_threads.py's in-memory stand-in, Claude Code its
Proc; nothing is started and no server is asked.

    python3 scripts/test_rooms.py
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402
import rooms as R  # noqa: E402
import seat  # noqa: E402
from test_no1_threads import Base, me, them  # noqa: E402

# (text, (kind, id, body)) - the header's table
HEADERS = [
    ("room:: deck\nhello", ("room", "deck", "hello")),
    ("to:: obrien-c33\n[No.1] go", ("to", "obrien-c33", "[No.1] go")),
    ("Room :: Deck\nx", ("room", "deck", "x")),
    ("  TO::no1  \nx", ("to", "no1", "x")),
    ("room:: deck", ("room", "deck", "")),
    ("room:: deck\r\nx", ("room", "deck", "x")),
    ("[thread web]\nold", ("room", "web", "old")),
    ("[thread web]", ("room", "web", "")),
    ("room: deck\nx", (None, None, "room: deck\nx")),
    ("room:: deck and more\nx", (None, None, "room:: deck and more\nx")),
    ("room:: 9deck\nx", (None, None, "room:: 9deck\nx")),
    ("room:: a-very-long-room-name-past-24\nx", (None, None, "room:: a-very-long-room-name-past-24\nx")),
    ("hello\nroom:: deck", (None, None, "hello\nroom:: deck")),
    ("Report: done. room:: deck", (None, None, "Report: done. room:: deck")),
    ("", (None, None, "")),
]


class Parser(unittest.TestCase):
    def test_the_header_table(self):
        for text, want in HEADERS:
            self.assertEqual(R.header(text), want, text)

    def test_the_page_s_copy_agrees_under_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        page = open(os.path.join(HERE, "..", "lcars-ui", "index.html"), encoding="utf-8").read()
        line = next(ln for ln in page.splitlines() if ln.startswith("const ROOM_HEAD = "))
        js = line + "\nconst cases = " + json.dumps([t for t, _ in HEADERS]) + ";\n" + \
            "console.log(JSON.stringify(cases.map(t => { const m = ROOM_HEAD.exec(t); return m ? " \
            "[m[3] ? 'room' : m[1].toLowerCase(), (m[3] || m[2]).toLowerCase(), t.slice(m[0].length)] : null; })));"
        p = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        for (text, want), got in zip(HEADERS, json.loads(p.stdout)):
            self.assertEqual(tuple(got) if got else (None, None, text), want, text)
        # and the page reads who a line is from past it, as user_from does
        self.assertIn('t = String(t || "").replace(ROOM_HEAD, "");', page)

    def test_the_page_s_title_copy_agrees_under_node(self):
        # the Rooms page reads a row's title with ROOM_TITLE, TITLE_RE's copy
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        page = open(os.path.join(HERE, "..", "lcars-ui", "index.html"), encoding="utf-8").read()
        line = next(ln for ln in page.splitlines() if ln.startswith("const ROOM_TITLE = "))
        cases = [R.title("captain", "no1", "deck", "How?"), R.title("obrien-c33", "", "deck", "Report: done"),
                 R.title("no1", "obrien-c33", "main", "[No.1] Go\nsecond line"), R.title("ship", "no1", "x-1", ""),
                 "no1 → #deck:", "captain → no1 #Deck: caps", "no arrow #deck: x", "a → b c #deck: two words to",
                 "kim → #toolongroomidtoolongroomid: x", "captain → #deck: with # and → inside"]
        js = line + "\nconst cases = " + json.dumps(cases) + ";\n" + \
            "console.log(JSON.stringify(cases.map(t => { const m = ROOM_TITLE.exec(t); return m ? " \
            "{frm: m[1], to: m[2] || '', room: m[3], first: m[4]} : null; })));"
        p = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        for t, got in zip(cases, json.loads(p.stdout)):
            self.assertEqual(got, R.title_parse(t), t)
        self.assertIn('const RM_CANCELLED = "' + seat.CANCELLED + '"', page)

    def test_helpers(self):
        self.assertEqual(R.room_of("room:: deck\nx"), "deck")
        self.assertEqual(R.room_of("to:: kim\nx", "web"), "web")
        self.assertEqual((R.to_of("to:: number-one\nx"), R.to_of("to:: no1\nx"), R.to_of("x")), ("no1", "no1", None))
        self.assertEqual(R.headed("room:: web\nx", "deck"), "room:: deck\nx", "exactly one header")
        self.assertEqual(R.headed("x", to="kim"), "to:: kim\nx")
        self.assertEqual((R.typed_for_no1("x", "main"), R.typed_for_no1("x", "deck")), ("x", "room:: deck\nx"))

    def test_split_at_paragraphs_only(self):
        t = "Main is quiet.\n\nroom:: deck\nThe chairs.\n\n[thread web]\nThe site.\n\nMore."
        self.assertEqual(R.split(t, "main"), ([("main", "Main is quiet."), ("deck", "The chairs."),
                                               ("web", "The site.\n\nMore.")], "web"))
        mid = "See room:: deck here.\nroom:: deck\nnot a paragraph's start"
        parts, cur = R.split(mid, "main")
        self.assertEqual((parts, cur), ([("main", mid)], "main"))
        self.assertIs(parts[0][1], mid, "uncut: the text itself")
        self.assertEqual(R.split("room:: Deck\nHi", "main")[0], [("deck", "Hi")])

    def test_titles_and_content(self):
        t = R.title("no1", "obrien-c33", "deck", "to:: obrien-c33\n[No.1] Rebase onto main\nthen more")
        self.assertEqual(t, "no1 → obrien-c33 #deck: [No.1] Rebase onto main")
        self.assertEqual(R.title_parse(t), {"frm": "no1", "to": "obrien-c33", "room": "deck",
                                            "first": "[No.1] Rebase onto main"})
        t = R.title("kim", "", "main", "x" * 200)
        self.assertEqual(R.title_parse(t)["to"], "")
        self.assertEqual(len(R.title_parse(t)["first"]), 90)
        self.assertEqual(R.content("room:: web\nbody\n\nwhole", "deck", None, ("misrouted:: room:: web",)),
                         "room:: deck\nmisrouted:: room:: web\nbody\n\nwhole")
        self.assertEqual(R.content("x", "deck", "kim"), "to:: kim\nx")
        self.assertEqual(R.room_row_id({"content": "id:: deck\nby:: no1"}), "deck")


class Rows(Base):
    def setUp(self):
        super().setUp()
        self.call(E.cmd_thread, E.NO1, "new", "deck", "Deck")
        self.call(E.cmd_thread, E.NO1, "new", "web", "Web")
        E.save("obrien", {"name": "obrien", "session": "s-ob", "title": "Chief O'Brien"})

    def msg(self, i=-1):
        r = self.j.msgs()[i]
        return R.title_parse(r["title"]), r

    def test_a_say_to_number_one_is_the_captain_s_row(self):
        self.call(E.cmd_say, E.NO1, False, False, "deck", stdin="How is the bridge?")
        p, r = self.msg()
        self.assertEqual((p["frm"], p["to"], p["room"]), ("captain", "no1", "deck"))
        self.assertEqual((r["content"], r["done_bool"]), ("room:: deck\nHow is the bridge?", 1))
        self.call(E.cmd_say, E.NO1, False, False, None, stdin="Main's.")
        self.assertEqual(self.msg()[0]["room"], "main")
        self.call(E.cmd_say, E.NO1, False, False, None, stdin="/compact")
        self.assertEqual(len(self.j.msgs()), 2, "a slash command is no message")

    def test_an_order_queued_then_delivered(self):
        self.write(me("room:: deck\nShip obrien's work"), them("Ordering."))
        slips = []

        def want(name, by, text=None, sender=None, fresh=False, slips=None, room=None):
            slips.append(seat.inbox_add(name, sender or by, text, fresh))
            return {}
        with mock.patch.object(E, "seated", return_value=True), mock.patch.object(E, "seat_want", want), \
                mock.patch.object(E, "seat_brief", return_value={}):
            code, res = self.call(E.cmd_say, "obrien", False, False, None, stdin="[No.1] Fix the chairs")
        self.assertEqual((code, res.get("queued")), (0, True), res)
        p, r = self.msg()
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"]), ("no1", "obrien", "deck", 0))
        self.assertEqual(r["content"], "to:: obrien\n[No.1] Fix the chairs")
        self.assertEqual(r["value_int"], self.j.inbox()[-1]["id"])
        # the captain edits it in the inbox before delivery: the row says what was typed
        slip = self.j.inbox()[-1]
        slip["content"] = "[No.1] Fix the chairs, and the table"
        seat.msg_delivered({slip["id"]: seat.inbox_text(slip)})
        p, r = self.msg()
        self.assertEqual((r["done_bool"], r["content"]), (1, "to:: obrien\n[No.1] Fix the chairs, and the table"))

    def test_orders_from_main_land_in_the_engineer_s_room_and_the_captain_s_too(self):
        self.write(me("Status?"))
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"}):
            self.call(E.cmd_say, "obrien", False, False, None, stdin="[No.1] Look")
            self.assertEqual(self.msg()[0]["room"], "obrien")
            self.call(E.cmd_say, "obrien", False, False, None, stdin="Captain here")
        p, r = self.msg()
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"]), ("captain", "obrien", "obrien", 1))

    def test_a_report_is_a_row_whole_and_its_slip_ticks_it(self):
        st = E.load("obrien")
        st.update(under_no1=1, room="deck")
        E.save("obrien", st)
        last = "Report: done.\n" + "x" * 3000
        self.call(E.cmd_hook, "turn-ended", "obrien", stdin=json.dumps({"last_assistant_message": last}))
        slip = self.j.inbox()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#deck: [crew] obrien"), slip["title"])
        self.assertLess(len(slip["content"]), 1500, "what is typed stays clipped")
        p, r = self.msg()
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"], r["value_int"]),
                         ("obrien", "no1", "deck", 0, slip["id"]))
        self.assertEqual(r["content"], "room:: deck\n" + last, "the row has it whole")
        self.call(E.cmd_no1_flush)
        self.assertEqual(self.p.typed[-1][:13], "room:: deck\n[")
        self.assertEqual(self.msg()[1]["done_bool"], 1, "delivered")

    def test_a_report_s_header_routes_it_and_a_misroute_falls_back(self):
        st = E.load("obrien")
        st.update(under_no1=1, room="deck")
        E.save("obrien", st)
        hook = lambda t: self.call(E.cmd_hook, "turn-ended", "obrien", stdin=json.dumps({"last_assistant_message": t}))
        hook("room:: web\nReport: the site")
        p, r = self.msg()
        self.assertEqual((p["room"], r["content"]), ("web", "room:: web\nReport: the site"))
        self.assertIn("crew#web:", self.j.inbox()[-1]["title"])
        hook("room:: dekc\nReport: a typo")
        p, r = self.msg()
        self.assertEqual((p["room"], r["content"]), ("deck", "room:: deck\nmisrouted:: room:: dekc\nReport: a typo"))
        hook("to:: no1\nReport: to you")
        self.assertEqual(self.msg()[0]["room"], "deck")
        hook("to:: nobody\nReport: x")
        self.assertIn("misrouted:: to:: nobody", self.msg()[1]["content"])

    def test_a_question_on_screen_is_a_notice_not_a_message(self):
        st = E.load("obrien")
        st.update(under_no1=1, room="deck")
        E.save("obrien", st)
        n = len(self.j.msgs())
        self.call(E.cmd_hook, "attention", "obrien",
                  stdin=json.dumps({"message": "needs permission", "notification_type": "permission_prompt"}))
        self.assertEqual((len(self.j.inbox()), len(self.j.msgs())), (1, n))

    def test_the_captain_s_turn_stays_in_the_engineer_s_room(self):
        self.call(E.cmd_hook, "turn-ended", "obrien", stdin=json.dumps({"last_assistant_message": "Done, captain."}))
        self.assertEqual(self.j.inbox(), [], "nothing to Number One")
        verb, name, room, path = self.spawned[-1]
        self.assertEqual((verb, name, room), ("msg-turn", "obrien", "obrien"))
        self.call(E.cmd_msg_turn, name, room, path)
        p, r = self.msg()
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"]), ("obrien", "", "obrien", 1))
        self.assertFalse(os.path.exists(path), "the spool removed")
        self.assertEqual(self.call(E.cmd_msg_turn, "obrien", "obrien", "/etc/passwd")[0], 2)

    def test_number_one_s_last_message_cut_by_room_lines(self):
        self.write(me("room:: deck\nThe chairs?"), them("Checking."),
                   them("Chairs done.\n\nroom:: web\nAnd the site."))
        self.call(E.cmd_hook, "turn-ended", E.NO1, stdin=json.dumps(
            {"last_assistant_message": "Chairs done.\n\nroom:: web\nAnd the site."}))
        verb, name, room, path = self.spawned[-1]
        self.assertEqual((verb, name, room), ("msg-turn", E.NO1, "deck"), "the room the turn began in")
        self.call(E.cmd_msg_turn, name, room, path)
        got = [(R.title_parse(r["title"])["room"], r["content"], r["done_bool"]) for r in self.j.msgs()]
        self.assertEqual(got, [("deck", "room:: deck\nChairs done.", 1), ("web", "room:: web\nAnd the site.", 1)])
        n = len(self.spawned)
        self.call(E.cmd_hook, "turn-ended", E.NO1, stdin=json.dumps({"last_assistant_message": "x",
                                                                     "stop_hook_active": True}))
        self.assertEqual(len(self.spawned), n)

    def test_the_notes_which_are_messages(self):
        E.no1_send("[deploy finished] obrien: deployed as 0.1.2", room="deck")
        E.no1_send("[captain] ticked off your question #4: x. Notes: yes")
        E.no1_send("[seat] obrien is next")
        E.no1_send("[job] the suite passed")
        got = [(p["frm"], p["to"], p["room"]) for p in (R.title_parse(r["title"]) for r in self.j.msgs())]
        self.assertEqual(got, [("ship", "no1", "deck"), ("captain", "no1", "main")])
        self.assertEqual(len(self.j.inbox()), 4, "every note still delivered")
        self.call(E.cmd_no1_flush)
        self.assertTrue(all(r["done_bool"] for r in self.j.msgs()))

    def test_the_retry_keeps_the_whole_text(self):
        self.j.down = True
        E.no1_send("[crew] obrien finished. Last words: short", room="deck",
                   msg={"frm": "obrien", "text": "the whole report"})
        a = self.spawned[-1]
        self.assertEqual(a[:6], ("no1-send", "--thread", "deck", "--from", "obrien", "--full"))
        self.assertIsNone(E.msg_post("obrien", "", "deck", "x"), "a row lost costs nothing")
        self.j.down = False
        self.call(E.cmd_no1_send, *a[1:])
        p, r = self.msg()
        self.assertEqual((p["frm"], p["room"], r["content"]), ("obrien", "deck", "room:: deck\nthe whole report"))
        self.assertFalse(os.path.exists(a[6]))
        self.call(E.cmd_no1_send, "--room", "web", "[deploy failed] x")
        self.assertEqual(self.msg()[0]["room"], "web")

    def test_a_cancel_marks_the_row(self):
        slip = seat.inbox_add("obrien", "No.1", "[No.1] x")
        seat.msg_add("no1", "obrien", "deck", "[No.1] x", False, slip)
        row = dict(self.j.inbox()[-1])
        seat.inbox_cancel(row)
        r = self.msg()[1]
        self.assertTrue(r["title"].startswith(seat.CANCELLED) and r["done_bool"], r)
        seat.inbox_uncancel(row)
        r = self.msg()[1]
        self.assertFalse(r["title"].startswith(seat.CANCELLED) or r["done_bool"], r)

    def test_rooms_rows_follow_the_labels(self):
        rows = lambda: {R.room_row_id(r): (r["title"], r["done_bool"], r["content"]) for r in seat.rooms_rows()}
        self.assertEqual(rows()["deck"], ("Deck", 0, "id:: deck\nby:: no1"))
        self.call(E.cmd_thread, E.NO1, "rename", "deck", "The", "bridge")
        self.call(E.cmd_thread, E.NO1, "close", "web")
        self.assertEqual((rows()["deck"][0], rows()["web"][1]), ("The bridge", 1))
        self.call(E.cmd_say, E.NO1, False, False, "web", stdin="back")
        self.assertEqual(rows()["web"][1], 0, "the captain's word reopens it")
        self.call(E.cmd_thread_req, E.NO1, stdin=json.dumps({"op": "new", "id": "motion", "name": "Motion"}))
        self.assertIn("by:: captain", rows()["motion"][2])
        self.assertEqual(len([r for r in self.j.rows if r["kind"] == R.ROOM_KIND]), 3, "one row per room")

    def test_the_rows_are_the_truth(self):
        # a row changed by hand (the console's journal, another box): the
        # labels follow it on the next thread op or list
        row = next(r for r in self.j.rows if R.room_row_id(r) == "deck")
        row.update(title="Deck two", done_bool=1)
        self.j.rows.append({"id": 9000, "kind": R.ROOM_KIND, "title": "Fresh", "content": "id:: fresh\nby:: captain",
                            "done_bool": 0, "deleted": 0})
        code, r = self.call(E.cmd_thread, E.NO1, "list")
        self.assertEqual(code, 0, r)
        self.assertEqual({t["id"]: t["name"] for t in r["threads"]}.get("fresh"), "Fresh")
        self.assertEqual({t["id"]: t["name"] for t in r["closed"]}.get("deck"), "Deck two")
        # reopened by new, as before
        code, r = self.call(E.cmd_thread, E.NO1, "new", "deck")
        self.assertEqual((code, r.get("reopened")), (0, True), r)
        self.assertEqual(row["done_bool"], 0)

    def test_a_crew_member_s_name_is_no_project_room(self):
        for tid in ("obrien", E.NO1, "queue"):
            code, r = self.call(E.cmd_thread, E.NO1, "new", tid, "X")
            self.assertEqual(code, 2, (tid, r))

    def test_the_captain_tells_an_engineer_in_a_project_room(self):
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"}), \
                mock.patch.object(E, "herdr", return_value=("", "")) as h, mock.patch.object(E, "submit_if_left"):
            code, r = self.call(E.cmd_say, "obrien", False, False, "deck", stdin="Check the chairs")
            self.assertEqual(code, 0, r)
            p, row = self.msg()
            self.assertEqual((p["frm"], p["to"], p["room"]), ("captain", "obrien", "deck"))
            self.assertEqual(row["content"], "to:: obrien\nCheck the chairs")
            self.assertEqual(h.call_args[0][3], "Check the chairs", "typed with no header yet (slice 3)")
            # their own room is a plain say; main or an unknown room refused
            code, r = self.call(E.cmd_say, "obrien", False, False, "obrien", stdin="Own")
            self.assertEqual((code, self.msg()[0]["room"]), (0, "obrien"))
            for bad in ("main", "nowhere"):
                code, r = self.call(E.cmd_say, "obrien", False, False, bad, stdin="x")
                self.assertEqual(code, 4, (bad, r))


class Turns(Base):
    """Slice 3 (rooms.md 4.2, 4.5, 10.7): which turn reports where, the DMs
    between engineers and their cap."""

    def setUp(self):
        super().setUp()
        self.call(E.cmd_thread, E.NO1, "new", "deck", "Deck")
        E.save("obrien", {"name": "obrien", "session": "s-ob", "title": "Chief O'Brien"})
        E.save("kim", {"name": "kim", "session": "s-kim", "title": "Ensign Kim"})
        self.slips = []

        def want(name, by, text=None, sender=None, fresh=False, slips=None, room=None):
            rid = seat.inbox_add(name, sender or by, text, fresh, thread=room)
            self.slips.append((name, by, rid))
            if slips is not None:
                slips.append(rid)
            return {}
        self.ps2 = [mock.patch.object(E, "seat_want", want), mock.patch.object(E, "seat_brief", return_value={}),
                    mock.patch.object(E, "task_begins"), mock.patch.object(E, "sync_to_base"),
                    mock.patch.object(E, "delivery_metrics")]
        for x in self.ps2:
            x.start()

    def tearDown(self):
        for x in self.ps2:
            x.stop()
        super().tearDown()

    def say(self, name, text):
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"}):
            return self.call(E.cmd_say, name, False, False, None, stdin=text)

    def end(self, name, text):
        return self.call(E.cmd_hook, "turn-ended", name, stdin=json.dumps({"last_assistant_message": text}))

    def turn(self, name):
        t = dict(E.load(name).get("turn") or {})
        t.pop("at", None)
        return t

    def no1_slips(self):
        return [r for r in self.j.inbox() if r["title"].startswith(E.NO1 + " ← ")]

    def deliver(self, name, *slips):
        """The seat handing `name` their inbox (seat_deliver), `slips`
        (sender, text, room) put in it first."""
        for sender, text, room in slips:
            seat.inbox_add(name, sender, text, thread=room)
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "idle"} if n != E.NO1 else None):
            self.assertTrue(E.seat_deliver(name, wait=1))
        return self.p.typed[-1]

    def test_a_no1_order_in_a_project_room_reports_there(self):
        self.write(me("room:: deck\nGet obrien on the chairs"))
        self.say("obrien", "[No.1] Fix the chairs")
        self.assertEqual(self.turn("obrien"), {"from": "no1", "room": "deck"})
        self.end("obrien", "Report: done.")
        slip = self.no1_slips()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#deck: [crew] obrien"), slip["title"])
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["frm"], p["to"], p["room"], r["value_int"]), ("obrien", "no1", "deck", slip["id"]))

    def test_an_order_for_a_named_room_reports_there(self):
        """crew say --room (LCARS_ROOM_AT): Number One's turn is main's (a 1:1
        with the captain), the order is the project's - filed in its room,
        to:: the engineer, and the report back there (rooms.md 21)."""
        self.write(me("Status of the chairs?"))
        with mock.patch.dict(os.environ, {"LCARS_ROOM_AT": "deck"}):
            self.say("obrien", "[No.1] Fix the chairs")
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["frm"], p["to"], p["room"]), ("no1", "obrien", "deck"))
        self.assertEqual(self.turn("obrien"), {"from": "no1", "room": "deck"})
        self.assertEqual(E.room_now(), "main", "Number One's own turn is untouched")
        self.end("obrien", "Report: done.")
        slip = self.no1_slips()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#deck: [crew] obrien"), slip["title"])
        self.assertEqual(R.title_parse(self.j.msgs()[-1]["title"])["room"], "deck")
        # queued for the seat, the same: the slip's turn is the named room's
        with mock.patch.dict(os.environ, {"LCARS_ROOM_AT": "deck"}), \
                mock.patch.object(E, "seated", return_value=True):
            self.call(E.cmd_say, "kim", False, False, None, stdin="[No.1] Paint the deck")
        self.assertEqual(R.title_parse(self.j.msgs()[-1]["title"])["room"], "deck")
        self.assertEqual(E.slip_turn("kim", self.j.inbox()[-1])[:2], ("no1", "deck"))

    def test_room_check(self):
        """What crew say --room accepts: main or an open project room; a
        closed one, an unknown one or a crew member's name refused."""
        self.call(E.cmd_thread, E.NO1, "new", "old", "Old")
        self.call(E.cmd_thread, E.NO1, "close", "old")
        self.assertIsNone(E.room_check("deck"))
        self.assertIsNone(E.room_check("main"))
        self.assertIn("closed", E.room_check("old"))
        self.assertIn("no such room: nope", E.room_check("nope"))
        self.assertIn("room list", E.room_check("nope"))
        self.assertIn("crew member, not a room", E.room_check("kim"))
        self.assertIn("a room id", E.room_check("Bad Id"))

    def test_a_no1_order_from_main_reports_to_main(self):
        self.write(me("Status?"))
        self.say("obrien", "[No.1] Look at the logs")
        self.assertEqual(self.turn("obrien"), {"from": "no1", "room": "main"})
        self.end("obrien", "Report: the logs are fine.")
        slip = self.no1_slips()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#main: [crew] obrien"), slip["title"])
        self.assertEqual(R.title_parse(self.j.msgs()[-1]["title"])["room"], "main")

    def test_the_captain_s_1to1_turn_stays_in_the_engineer_s_room(self):
        # even after an order of Number One's: the latest word owns the turn
        self.write(me("room:: deck\nGo"))
        self.say("obrien", "[No.1] Fix the chairs")
        self.say("obrien", "Captain here: what are you on?")
        self.assertEqual(self.turn("obrien"), {"from": "captain", "room": "obrien"})
        self.assertTrue(E.load("obrien").get("under_no1"), "questions still go to Number One")
        n = len(self.no1_slips())
        self.end("obrien", "The chairs, captain.")
        self.assertEqual(len(self.no1_slips()), n, "nothing to Number One's inbox")
        self.assertEqual(self.spawned[-1][:3], ("msg-turn", "obrien", "obrien"))

    def test_to_no1_from_a_1to1_turn_reaches_number_one_in_main(self):
        self.say("obrien", "Captain here: drop the chairs, do the lights")
        self.end("obrien", "to:: no1\nThe captain changed my task: the lights, not the chairs.")
        slip = self.no1_slips()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#main: [crew] obrien"), slip["title"])
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["frm"], p["to"], p["room"]), ("obrien", "no1", "main"))
        self.assertTrue(r["content"].endswith("the lights, not the chairs."))

    def test_the_captain_s_word_in_a_project_room_reports_there(self):
        # the Rooms page's To chip (4.1 row 2): typed at once, the turn is the
        # room's, and the report goes to Number One in it
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"}):
            self.call(E.cmd_say, "obrien", False, False, "deck", stdin="Captain: check the table too")
        self.assertEqual(self.turn("obrien"), {"from": "captain", "room": "deck"})
        self.end("obrien", "Report: the table is fine.")
        slip = self.no1_slips()[-1]
        self.assertTrue(slip["title"].startswith("number-one ← crew#deck: [crew] obrien"), slip["title"])
        p = R.title_parse(self.j.msgs()[-1]["title"])
        self.assertEqual((p["frm"], p["to"], p["room"]), ("obrien", "no1", "deck"))
        # queued for the seat: the slip carries the room, and its delivery the turn
        with mock.patch.object(E, "seated", return_value=True), mock.patch.object(E, "agent_info", lambda n: None):
            code, r = self.call(E.cmd_say, "kim", False, False, "deck", stdin="Captain: run the tests")
        self.assertEqual((code, r.get("queued")), (0, True), r)
        self.assertEqual(seat.inbox_room(self.j.inbox()[-1]), "deck")
        self.deliver("kim")
        self.assertEqual(self.turn("kim"), {"from": "captain", "room": "deck"})
        # his own room as the room: a 1:1 turn, as before
        with mock.patch.object(E, "agent_info", lambda n: {"agent_status": "working"}):
            self.call(E.cmd_say, "obrien", False, False, "obrien", stdin="Captain: and you?")
        self.assertEqual(self.turn("obrien"), {"from": "captain", "room": "obrien"})

    def test_delivery_sets_the_turn_and_a_job_s_note_keeps_it(self):
        self.write(me("room:: deck\nGo"))
        with mock.patch.object(E, "seated", return_value=True), mock.patch.object(E, "agent_info", lambda n: None):
            self.call(E.cmd_say, "obrien", False, False, None, stdin="[No.1] Fix the chairs")
        self.deliver("obrien")
        self.assertEqual(self.turn("obrien"), {"from": "no1", "room": "deck"})
        typed = self.deliver("obrien", (seat.JOB, "[job] the suite passed", None))
        self.assertTrue(typed.startswith("[job]"))
        self.assertEqual(self.turn("obrien"), {"from": "no1", "room": "deck"}, "the ship's note keeps the room")
        self.end("obrien", "Report: tests green.")
        self.assertIn("crew#deck:", self.no1_slips()[-1]["title"])
        self.deliver("obrien", ("captain", "Captain: and the lights", None))
        self.assertEqual(self.turn("obrien"), {"from": "captain", "room": "obrien"})
        # several at once: the last person's word owns it (10.8)
        self.deliver("obrien", ("captain", "x", None), ("ship", "[deploy finished] y", None))
        self.assertEqual(self.turn("obrien")["from"], "captain")

    def test_a_dm_is_filed_slipped_delivered_and_answered_back(self):
        self.write(me("room:: deck\nGo"))
        self.say("obrien", "[No.1] Fix the chairs")
        n = len(self.no1_slips())
        with mock.patch.object(E, "seated", return_value=True):
            self.end("obrien", "to:: kim\nWhich atlas holds the chairs?")
        self.assertEqual(len(self.no1_slips()), n, "a DM is not Number One's")
        slip = [r for r in self.j.inbox() if r["title"].startswith("kim ← ")][-1]
        self.assertTrue(slip["title"].startswith("kim ← obrien#deck: room:: deck"), slip["title"])
        self.assertEqual(slip["content"], "room:: deck\n[DM from obrien (Chief O'Brien)] Which atlas holds the chairs?")
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"], r["value_int"]),
                         ("obrien", "kim", "deck", 0, slip["id"]))
        self.assertEqual(r["content"], "to:: kim\nWhich atlas holds the chairs?")
        self.assertEqual(self.slips[-1][:2], ("kim", "dm"))
        # the seat comes to kim: delivered, the row ticked, kim's turn the DM's
        typed = self.deliver("kim")
        self.assertTrue(typed.startswith("room:: deck\n[DM from obrien"), typed)
        self.assertEqual(self.j.msgs()[-1]["done_bool"], 1)
        self.assertEqual(self.turn("kim"), {"from": "obrien", "room": "deck", "reply_to": "obrien"})
        # kim's answer with no header goes back to obrien, in the DM's room
        with mock.patch.object(E, "seated", return_value=True):
            self.end("kim", "The cabin atlas.")
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["frm"], p["to"], p["room"], r["done_bool"]), ("kim", "obrien", "deck", 0))
        self.assertTrue([r for r in self.j.inbox() if r["title"].startswith("kim ← ")] == [])
        back = [r for r in self.j.inbox() if r["title"].startswith("obrien ← kim#deck: ")]
        self.assertEqual(len(back), 1, self.j.titles())
        self.assertEqual(len(self.no1_slips()), n, "nor is the answer")

    def test_a_dm_from_a_1to1_turn_lands_in_the_addressee_s_room(self):
        self.say("obrien", "Captain here: ask kim about the atlas")
        with mock.patch.object(E, "seated", return_value=True):
            self.end("obrien", "to:: Kim\nWhich atlas?")
        p = R.title_parse(self.j.msgs()[-1]["title"])
        self.assertEqual((p["frm"], p["to"], p["room"]), ("obrien", "kim", "kim"))
        self.assertIn("kim ← obrien#kim: ", self.j.titles()[-1])

    def test_the_dm_cap(self):
        self.say("obrien", "Captain here: work with kim")
        with mock.patch.object(E, "seated", return_value=True):
            for i in range(3):
                self.end("obrien", f"to:: kim\nThanks {i}")
        to_kim = [r for r in self.j.inbox() if r["title"].startswith("kim ← ")]
        self.assertEqual(len(to_kim), 2, "the third is not delivered")
        p, r = R.title_parse(self.j.msgs()[-1]["title"]), self.j.msgs()[-1]
        self.assertEqual((p["to"], r["done_bool"], r["value_int"]), ("kim", 1, 0))
        self.assertIn("held:: the DM cap", r["content"])
        self.assertTrue(r["content"].endswith("Thanks 2"), "filed whole")
        line = self.no1_slips()[-1]
        self.assertIn(f"obrien's third message to kim within the hour was filed, not delivered (crew_msg #{r['id']})",
                      line["content"])
        self.assertEqual(len(self.no1_slips()), 1, "one line")
        self.assertFalse(any("third message" in m["content"] for m in self.j.msgs()), "the line is no message")
        # a DM to someone else is not counted against kim's
        E.save("torres", {"name": "torres", "session": "s-t", "title": "Torres"})
        with mock.patch.object(E, "seated", return_value=True):
            self.end("obrien", "to:: torres\nA question")
        self.assertIn("torres ← obrien#torres: ", self.j.titles()[-1])
        # a word from the captain starts the count again
        self.say("obrien", "Captain: carry on")
        with mock.patch.object(E, "seated", return_value=True):
            self.end("obrien", "to:: kim\nOne more")
        self.assertEqual(len([r for r in self.j.inbox() if r["title"].startswith("kim ← ")]), 3)
        # and an hour later the count is gone too
        st = E.load("obrien")
        st["dms"] = [{"to": "kim", "at": int(time.time()) - 4000}] * 5
        E.save("obrien", st)
        with mock.patch.object(E, "seated", return_value=True):
            self.end("obrien", "to:: kim\nNext hour")
        self.assertEqual(len([r for r in self.j.inbox() if r["title"].startswith("kim ← ")]), 4)

    def test_the_brief_says_so(self):
        b = E.brief("obrien", E.load("obrien"))
        self.assertIn("Rooms: every message between the crew is filed in a room", b)
        self.assertIn("make the first line of that turn's last message `to:: no1`", b)
        self.assertIn("[DM from <name>]", b)


class Verbs(Base):
    """Slice 4 (rooms.md 7): Number One's room verbs, their refusals, and
    no1.py's `room` and the `thread` alias."""

    def setUp(self):
        super().setUp()
        E.save("obrien", {"name": "obrien", "session": "s-ob", "title": "Chief O'Brien"})

    def room(self, *a):
        return self.call(E.cmd_room, E.NO1, *a)

    def test_new_rename_close_reopen_and_list(self):
        code, r = self.room("new", "motion", "Motion", "graphics")
        self.assertEqual((code, r["id"], r["name"], r["reopened"]), (0, "motion", "Motion graphics", False), r)
        self.assertEqual([x["id"] for x in r["rooms"]], ["main", "motion"])
        row = [x for x in seat.rooms_rows() if R.room_row_id(x) == "motion"][0]
        self.assertEqual((row["title"], row["content"]), ("Motion graphics", "id:: motion\nby:: no1"))
        self.assertEqual(self.room("rename", "motion", "Motion")[1]["name"], "Motion")
        self.assertEqual(self.room("close", "motion")[0], 0)
        self.assertEqual([x["id"] for x in self.room("list")[1]["rooms"]], ["main"])
        closed = self.room("list", "--closed")[1]["rooms"]
        self.assertEqual([(x["id"], x.get("closed", False)) for x in closed], [("main", False), ("motion", True)])
        code, r = self.room("new", "motion")
        self.assertEqual((code, r["reopened"], r["name"]), (0, True, "Motion"))
        self.assertEqual(len([x for x in self.j.rows if x["kind"] == R.ROOM_KIND]), 1, "one row per room")

    def test_the_refusals(self):
        self.room("new", "deck")
        for args, code, words in [
                (("new", "obrien"), 2, "crew member's name"),
                (("new", E.NO1), 2, "crew member's name"),
                (("new", "queue"), 2, "crew member's name"),
                (("new", "deck"), 2, "already"),
                (("new", "main"), 2, "already"),
                (("new", "Bad Id"), 2, "room id"),
                (("close", "main"), 2, "main cannot"),
                (("close", "obrien"), 2, "own room"),
                (("close", "nope"), 4, "no such open room"),
                (("rename", "nope", "X"), 4, "no such room"),
                (("rename", "deck"), 2, "rename"),
                (("log", "nope"), 4, "no such room"),
                (("log", "deck", "x"), 2, "n is a number"),
                (("show", "abc"), 2, "room show"),
                (("show", "999"), 4, "no message"),
                (("frob",), 2, "room list"),
        ]:
            got, r = self.room(*args)
            self.assertEqual(got, code, (args, r))
            self.assertIn(words, r["error"], args)
        self.assertEqual(self.call(E.cmd_room, "obrien", "list")[0], 2, "Number One's alone")
        slip = seat.inbox_add("obrien", "No.1", "[No.1] x")
        self.assertEqual(self.room("show", str(slip))[0], 4, "a slip is no message")

    def test_list_log_and_show_read_the_rows(self):
        self.room("new", "deck", "Deck")
        long = "z" * 2000
        E.msg_post("captain", "no1", "deck", "How are the chairs?")
        E.msg_post("no1", "obrien", "deck", "[No.1] Fix the chairs")
        E.msg_post("obrien", "no1", "deck", "Report: done.\n" + long)
        E.msg_post("captain", "no1", "main", "Status?")
        E.msg_post("no1", "", "main", "migrated", extra=("at:: 2026-10-20 10:11:12", "src:: s k"))
        rooms = {x["id"]: x for x in self.room("list")[1]["rooms"]}
        self.assertEqual((rooms["deck"]["count"], rooms["main"]["count"]), (3, 2))
        self.assertEqual((rooms["deck"]["last"]["from"], rooms["deck"]["last"]["first"]), ("obrien", "Report: done."))
        code, r = self.room("log", "deck", "2")
        self.assertEqual((code, r["count"], len(r["messages"])), (0, 3, 2))
        m = r["messages"][-1]
        self.assertEqual((m["from"], m["to"], m["room"]), ("obrien", "no1", "deck"))
        self.assertTrue(m["text"].startswith("Report: done.") and len(m["text"]) < 700, "clipped, the header off")
        self.assertEqual(len(self.room("log", "deck")[1]["messages"]), 3, "20 by default")
        self.assertEqual(self.room("log", "main")[1]["messages"][-1]["at"], "2026-10-20 10:11:12", "a migrated row's time")
        code, r = self.room("show", str(m["id"]))
        self.assertEqual((code, r["text"]), (0, "Report: done.\n" + long), "whole")
        self.assertEqual(len(self.room("log", "obrien")[1]["messages"]), 0, "a crew member's room is a room")

    def test_the_thread_verb_does_the_same(self):
        code, r = self.call(E.cmd_thread, E.NO1, "new", "obrien")
        self.assertEqual(code, 2, "the same refusal")
        code, r = self.call(E.cmd_thread, E.NO1, "new", "web", "Web")
        self.assertEqual((code, r["thread"], r["name"]), (0, "web", "Web"))
        self.assertEqual([x["id"] for x in self.room("list")[1]["rooms"]], ["main", "web"])

    def test_no1_py_room_and_the_alias(self):
        import no1
        calls = []
        with mock.patch.object(no1, "engineer", lambda *a, **k: calls.append(a) or (0, {"ok": True})):
            self.assertEqual(no1.room(["log", "deck", "5"]), (0, {"ok": True}))
            code, j = no1.thread(["new", "web", "Web"])
            for bad in (["log"], ["show"], ["new"], ["list", "x"], ["frob"], []):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    no1.room(bad)
        self.assertEqual(calls, [("room", E.NO1, "log", "deck", "5"), ("thread", E.NO1, "new", "web", "Web")])
        self.assertIn("no1.py room new", j["use"])


class CarryOver(Base):
    """threads v2's names, read as rooms."""

    def test_the_old_names_are_read(self):
        self.assertEqual(E.eng_room({"no1_thread": "deck"}), "deck")
        self.assertEqual(E.eng_room({"room": "web", "no1_thread": "deck"}), "web")
        E.set_deploy(state="queued", by_thread="deck")
        self.assertEqual(E.deploy_room(), "deck")
        self.assertEqual(seat.inbox_room({"title": "number-one ← crew#deck [fresh]: x"}), "deck")
        self.assertIs(seat.inbox_thread, seat.inbox_room)
        evs = [{"r": "me", "t": "[thread deck]\nold"}, {"r": "them", "t": "a\n\n[thread web]\nb"},
               {"r": "me", "t": "room:: deck\nnew"}]
        marked = E.room_marks(evs)[0]
        self.assertEqual([(e["room"], e["t"]) for e in marked],
                         [("deck", "old"), ("deck", "a"), ("web", "b"), ("deck", "new")])
        self.assertFalse(any("th" in e for e in marked), "the poll's events say room only (rooms.md 8)")
        # written under the new names: an order's room, a deploy's
        self.write(me("room:: deck\nGo"))
        E.save("kim", {"name": "kim", "no1_thread": "web"})
        E.thread_take("kim")
        self.assertEqual((E.load("kim").get("room"), "no1_thread" in E.load("kim")), ("deck", False))
        self.assertEqual(E.deploy_room(), "deck")

    def test_a_refresh_under_either_name(self):
        """A refresh noted before 0.310 (`thread`) or after (`room`): its
        notes go to that room."""
        for key in ("thread", "room"):
            st = E.load(E.NO1)
            st["refresh"] = {"at": int(time.time()), key: "deck", "noted": int(time.time())}
            E.save(E.NO1, st)
            with mock.patch.object(E, "clear_session", return_value=(1, {"error": "no"})), \
                    mock.patch.object(E, "refresh_log"):
                self.call(E.cmd_refresh_go, E.NO1)
            self.assertIn("← refresh#deck: ", self.j.inbox()[-1]["title"], key)
        self.assertEqual(E.user_from("room:: deck\n[crew] kim (Ensign Kim) finished")["who"], "kim")

    def test_the_turn_s_room_is_its_first_message_s(self):
        self.write(me("room:: deck\nGo"), them("A.\n\nroom:: web\nB."))
        self.assertEqual((E.room_now(), E.room_turn()), ("web", "deck"))

    def test_deploy_reads_either_env(self):
        self.write(me("room:: deck\nShip"))
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        for k in ("LCARS_ROOM_BY", "LCARS_THREAD_BY"):
            with mock.patch.object(E, "run", return_value=ok), mock.patch.dict(os.environ, {k: "no1"}):
                self.call(E.detach, "deploy", "obrien")
            self.assertEqual(E.read_deploy().get("by_room"), "deck", k)


    def test_deploy_for_a_named_room(self):
        # crew deploy --room: the outcome to the project's room, not the turn's
        self.write(me("Ship it"))
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(E, "run", return_value=ok), \
                mock.patch.dict(os.environ, {"LCARS_ROOM_BY": "no1", "LCARS_ROOM_AT": "deck"}):
            self.call(E.detach, "deploy", "obrien")
        self.assertEqual((E.read_deploy().get("by_room"), E.deploy_room()), ("deck", "deck"))


class Migrate(Base):
    def test_dry_run_then_apply_twice(self):
        self.call(E.cmd_thread, E.NO1, "new", "deck", "Deck")
        self.call(E.cmd_thread, E.NO1, "new", "old", "Old")
        self.call(E.cmd_thread, E.NO1, "close", "old")
        # a room row lost (made before rooms): the migration makes it
        self.j.rows = [r for r in self.j.rows if R.room_row_id(r) != "old"]
        long = "y" * 7000
        self.write(me("Status?"), them("Quiet."), me("[thread deck]\n[crew] kim (Ensign Kim) finished a turn. Last words: x"),
                   them("Reviewing."), json.dumps({"type": "assistant", "message": {"content": [
                       {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}),
                   json.dumps({"type": "assistant", "timestamp": "2026-10-20T10:11:12.000Z", "message": {"content": [
                       {"type": "text", "text": "Deploying.\n\n[thread old]\n" + long}]}}),
                   me("[seat] obrien is next"), them("Noted."),
                   me("[thread deck]\n[deploy failed] kim: the suite failed"),
                   me("[deploy finished] kim: deployed as 0.1.2"), me("[rollback] kim's 0.1.2 rolled back"))
        before = len(self.j.rows)
        code, r = self.call(E.cmd_rooms_migrate)
        self.assertEqual(code, 0, r)
        self.assertEqual(len(self.j.rows), before, "a dry run writes nothing")
        self.assertEqual(r["rooms_to_make"], [{"id": "old", "name": "Old", "closed": True}])
        self.assertEqual({k: (v["messages"], v["new"]) for k, v in r["rooms"].items()},
                         {"main": (5, 5), "deck": (3, 3), "old": (1, 1)})
        self.assertIn("kim → no1 #deck", r["rooms"]["deck"]["sample"][0])
        code, r = self.call(E.cmd_rooms_migrate, "--apply")
        self.assertEqual((code, r["made"], r["written"]), (0, 1, 9), r)
        # a deploy's or rollback's outcome is the ship's, as the live code files
        # it (note_msg), never the engineer's it names; a report is theirs
        frm = {R.strip(x["content"]).split("\n")[-1][:16]: R.title_parse(x["title"])["frm"] for x in self.j.msgs()}
        self.assertEqual((frm["[deploy failed] "], frm["[deploy finished"], frm["[rollback] kim's"]),
                         ("ship", "ship", "ship"))
        self.assertTrue(any(R.title_parse(x["title"])["frm"] == "kim" for x in self.j.msgs()), "kim's report")
        old = [x for x in self.j.msgs() if "#old" in x["title"]][0]
        self.assertTrue(old["content"].endswith(long), "whole, not clipped")
        self.assertRegex(old["content"][:200], r"^room:: old\nat:: 2026-10-20 10:11:12\nsrc:: \S+ \S+\ny")
        # the seat's plumbing and Number One's mid-turn text are not messages
        texts = [R.strip(x["content"]) for x in self.j.msgs()]
        self.assertFalse(any("obrien is next" in t or t.endswith("Reviewing.") for t in texts), texts)
        n = len(self.j.rows)
        code, r = self.call(E.cmd_rooms_migrate, "--apply")
        self.assertEqual((code, r["written"], r["made"], len(self.j.rows)), (0, 0, 0, n), "a second run writes nothing")

    def test_apply_refused_once_live_rows_exist_unless_until(self):
        self.write(json.dumps({"type": "user", "timestamp": "2026-10-20T10:00:00.000Z",
                               "message": {"content": "Early?"}}),
                   json.dumps({"type": "user", "timestamp": "2026-10-22T10:00:00.000Z",
                               "message": {"content": "Late?"}}))
        seat.msg_add("captain", "no1", "main", "Late?")  # the live hook's row: no src::
        n = len(self.j.rows)
        code, r = self.call(E.cmd_rooms_migrate)
        self.assertEqual((code, r["live_rows"]), (0, 1), "a dry run says so, and runs")
        code, r = self.call(E.cmd_rooms_migrate, "--apply")
        self.assertEqual((code, len(self.j.rows)), (2, n), r)
        self.assertIn("--until", str(r))
        code, r = self.call(E.cmd_rooms_migrate, "--apply", "--until", "bad")
        self.assertEqual(code, 2, r)
        code, r = self.call(E.cmd_rooms_migrate, "--apply", "--until", "2026-10-21 00:00")
        self.assertEqual((code, r["written"]), (0, 1), r)
        texts = [R.strip(x["content"]) for x in self.j.msgs()]
        self.assertEqual(sum(t.endswith("Late?") for t in texts), 1, "the live row alone, not copied again")
        self.assertTrue(any(t.endswith("Early?") for t in texts))


if __name__ == "__main__":
    unittest.main()
