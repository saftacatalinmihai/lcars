#!/usr/bin/env python3
"""Unit tests for scripts/engineer.py's `events_of`: a transcript line made
into the console chat's bubbles. A user message wrapped in Claude Code's
<pasted_content> (a quote reply from the Claude app, a line the ship types
in) is the message and shows; a harness wrapper (a slash-command echo, a
system-reminder) does not.

    python3 scripts/test_events.py
"""

import json
import os
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402


def user(content):
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}})


def shown(content):
    return [e["t"] for e in E.events_of(user(content)) if e["r"] == "me"]


# A real user line of Number One's transcript (the start of a crew notice,
# as Claude Code stored it: two newlines, then the pasted block).
REAL = ('\n\n<pasted_content id="0533">\n[crew] okafor-c30 (Lieutenant Daniel Okafor) finished a turn. '
        'Last words: Report: done and committed, not deployed.\n</pasted_content id="0533">')


class Events(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(shown("Make the chips bigger."), ["Make the chips bigger."])

    def test_quote_reply(self):
        body = "> the deck is slow\nYes, on the phone too."
        for wrapped in (f'<pasted_content id="12">\n{body}\n</pasted_content>',
                        f'\n\n<pasted_content id="12">\n{body}\n</pasted_content>',
                        f'\n\n<pasted_content id="12">\n{body}\n</pasted_content id="12">'):
            self.assertEqual(shown(wrapped), [body], repr(wrapped))

    def test_crew_notice(self):
        t = "[deploy finished] obrien-c33: deployed, 3 files"
        self.assertEqual(shown(f'\n\n<pasted_content id="9">\n{t}\n</pasted_content id="9">'), [t])

    def test_real_line(self):
        self.assertEqual(shown(REAL), ["[crew] okafor-c30 (Lieutenant Daniel Okafor) finished a turn. "
                                       "Last words: Report: done and committed, not deployed."])

    def test_text_around_and_several(self):
        c = ('Look at these:\n<pasted_content id="1">one</pasted_content>\n'
             '<pasted_content id="2">\ntwo\n</pasted_content id="2">\nThanks.')
        self.assertEqual(shown(c), ["Look at these:\n\none\n\ntwo\n\nThanks."])

    def test_pasted_html_kept(self):
        self.assertEqual(shown('<pasted_content id="3"><b>bold</b></pasted_content>'), ["<b>bold</b>"])

    def test_empty_after_unwrap(self):
        self.assertEqual(shown('\n\n<pasted_content id="4">\n\n</pasted_content>'), [])

    def test_wrappers_dropped(self):
        for c in ("<command-name>/clear</command-name>\n<command-message>clear</command-message>\n"
                  "<command-args></command-args>",
                  "<local-command-stdout></local-command-stdout>",
                  "<local-command-caveat>Caveat: ...</local-command-caveat>",
                  "<system-reminder>\nSomething.\n</system-reminder>"):
            self.assertEqual(shown(c), [], c)

    def test_blocks(self):
        c = [{"type": "text", "text": "<system-reminder>x</system-reminder>"},
             {"type": "text", "text": '\n\n<pasted_content id="5">\n[crew] a notice\n</pasted_content>'},
             {"type": "tool_result", "tool_use_id": "t", "content": "ok"},
             {"type": "text", "text": "And a plain line."}]
        self.assertEqual(shown(c), ["[crew] a notice", "And a plain line."])


def froms(content):
    """The "me" events' who-from fields, without r and t."""
    return [{k: v for k, v in e.items() if k not in ("r", "t")} for e in E.events_of(user(content)) if e["r"] == "me"]


def pasted(t):
    return f'\n\n<pasted_content id="7">\n{t}\n</pasted_content id="7">'


class From(unittest.TestCase):
    """Who a user turn is from (`from`, docs/design/chat.md §3.4): the
    captain, his words the ship carries, Number One, or the ship."""

    def one(self, text, wrap=True):
        r = froms(pasted(text) if wrap else text)
        self.assertEqual(len(r), 1, text)
        return r[0]

    def test_captain(self):
        for t in ("Make the chips bigger.", "[spoken] Is it deployed?",
                  "[conversation] the captain is talking\n[spoken] go on",
                  "[thread deck]\nAnd the deck too.", "[somethingelse] his own brackets"):
            self.assertEqual(self.one(t, wrap=False), {"from": "captain"}, t)

    def test_quote_reply_stays_his(self):
        # a quote reply from the Claude app, pasted: even quoting a ship line
        self.assertEqual(self.one("> [crew] okafor-c30 finished a turn\nGood, ship it."), {"from": "captain"})
        self.assertEqual(self.one("> the deck is slow\nYes, on the phone too."), {"from": "captain"})

    def test_ship_tags(self):
        cases = {
            "[crew] okafor-c30 (Lieutenant Daniel Okafor) finished a turn. Last words: Report: done.":
                {"from": "ship", "tag": "crew", "who": "okafor-c30"},
            "[crew] obrien-c33 context 412k, over the handover mark":
                {"from": "ship", "tag": "crew", "who": "obrien-c33"},
            "[deploy finished] obrien-c33: deployed, 3 files": {"from": "ship", "tag": "deploy finished", "who": "obrien-c33"},
            "[deploy failed] obrien-c33: the suite failed": {"from": "ship", "tag": "deploy failed", "who": "obrien-c33"},
            "[deploy finished] 0.296.0 is live. Tell the captain.": {"from": "ship", "tag": "deploy finished"},
            "[deploy failed] the suite failed. Nothing went live.": {"from": "ship", "tag": "deploy failed"},
            "[rollback] rolled back to a3eabfc": {"from": "ship", "tag": "rollback"},
            "[job] run.sh: PASSED (exit 0) on a3eabfc": {"from": "ship", "tag": "job"},
            "[seat] You were relieved mid-turn (the captain's order).": {"from": "ship", "tag": "seat"},
            "[refresh] Your conversation was cleared for a fresh context.": {"from": "ship", "tag": "refresh"},
            "[from Miles O'Brien] Take the deck's half.": {"from": "ship", "tag": "from", "who": "Miles O'Brien"},
        }
        for t, want in cases.items():
            self.assertEqual(self.one(t), want, t)

    def test_via(self):
        self.assertEqual(self.one("[captain] ticked off your question #812: Ship it? (`no1.py asks`) Notes: yes"),
                         {"from": "via", "tag": "question", "ref": "ask", "id": 812})
        for what in ("A note to you", "More in a note to you"):
            t = f"[captain] {what}, written in the captain's journal entry #40 \"Mon\" (crew note #4410): look at it"
            self.assertEqual(self.one(t), {"from": "via", "tag": "note", "ref": "note", "id": 4410}, t)
        self.assertEqual(self.one("[captain] answered your question: use the blue"), {"from": "via", "tag": "captain"})

    def test_no1(self):
        self.assertEqual(self.one("[No.1] A new task, from the captain: build it."), {"from": "no1", "tag": "No.1"})

    def test_thread_and_held_prefix(self):
        self.assertEqual(self.one("[thread deck]\n[crew] okafor-c30 (Lt. Okafor) finished a turn."),
                         {"from": "ship", "tag": "crew", "who": "okafor-c30"})
        self.assertEqual(self.one("[thread q4]\n(held since 2026-10-22 03:10 UTC, while you were off duty) "
                                  "[captain] ticked off your question #9: Go?"),
                         {"from": "via", "tag": "question", "ref": "ask", "id": 9})
        self.assertEqual(self.one("(held since 2026-10-22 03:10 UTC, while you were off duty) [job] x: PASSED"),
                         {"from": "ship", "tag": "job"})
        # the thread survives the poll's cut (thread_marks), the fields too
        ev = E.events_of(user(pasted("[thread deck]\n[seat] relieved")))
        res, _ = E.room_marks(ev)
        self.assertEqual((res[0]["room"], res[0]["from"], res[0]["t"]), ("deck", "ship", "[seat] relieved"))

    def test_real_line(self):
        self.assertEqual(froms(REAL), [{"from": "ship", "tag": "crew", "who": "okafor-c30"}])

    def test_assistant_untouched(self):
        evs = E.events_of(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "[crew] x"}]}}))
        self.assertEqual(evs, [{"r": "them", "t": "[crew] x"}])


def line(kind, content, ts):
    return json.dumps({"type": kind, "timestamp": ts, "message": {"role": kind, "content": content}})


class Keys(unittest.TestCase):
    """`k` and `at` (docs/design/voice-live-narration.md 2.1, 2.2): the page
    says a line once by its key, and not at all when it is old."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp(prefix="lcars-test-events-")
        self.path = os.path.join(self.d, "0a1b2c3d-0000-4000-8000-000000000000.jsonl")
        self.lines = [line("user", "Status?", "2026-10-22T10:00:00.000Z"),
                      line("assistant", [{"type": "text", "text": "Looking."},
                                         {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                           "2026-10-22T10:00:02.500Z"),
                      line("assistant", [{"type": "text", "text": "Quiet."}], "2026-10-22T10:00:09.000Z")]
        with open(self.path, "w") as f:
            f.write("".join(ln + "\n" for ln in self.lines))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def test_no_key_no_fields(self):
        self.assertEqual(E.events_of(self.lines[2]), [{"r": "them", "t": "Quiet."}])

    def test_key_and_time(self):
        evs = E.events_of(self.lines[1], "s:40")
        self.assertEqual([e["k"] for e in evs], ["s:40:0", "s:40:1"])
        self.assertEqual({e["at"] for e in evs}, {1792663202.5})
        self.assertNotIn("at", E.events_of(line("assistant", [{"type": "text", "text": "x"}], None), "s:0")[0])

    def test_forward_and_back_agree(self):
        size = os.path.getsize(self.path)
        fwd, nxt = E.poll_forward(self.path, 0, size)
        back, first = E.poll_back(self.path, size)
        self.assertEqual((nxt, first), (size, 0))
        self.assertEqual(fwd, back)
        keys = [e["k"] for e in fwd]
        self.assertEqual(len(set(keys)), len(keys), keys)
        off2 = len(self.lines[0]) + 1
        self.assertEqual(keys[1], f"0a1b2c3d:{off2}:0")
        # from the middle: the same keys for the same lines
        later, _ = E.poll_forward(self.path, off2, size)
        self.assertEqual([e["k"] for e in later], keys[1:])

    def test_tool_words(self):
        tl = lambda name, **inp: {k: v for k, v in E.tool_line({"name": name, "input": inp}).items() if k in ("n", "a")}
        self.assertEqual(tl("Read", file_path="/x/lcars-ui/index.html"), {"n": "Read", "a": "index.html"})
        self.assertEqual(tl("Bash", command="make check", description="Compile the server"), {"n": "Bash", "a": "Compile the server"})
        self.assertEqual(tl("Bash", command="ls"), {"n": "Bash"})
        self.assertEqual(tl("mcp__fff__grep", query="sayCut"), {"n": "mcp__fff__grep", "a": "sayCut"})
        self.assertEqual(tl("mcp__fff__multi_grep", patterns=["a", "b"]), {"n": "mcp__fff__multi_grep", "a": "a or b"})
        self.assertEqual(tl("Grep", pattern="x\ny"), {"n": "Grep", "a": "x"})
        self.assertEqual(E.tool_line({"name": "Bash", "input": {"command": "ls"}})["t"], "Bash: ls")

    def test_a_split_event_keeps_keys_apart(self):
        ev = {"r": "them", "t": "Done.\n\n[thread deck]\nAnd the deck.", "k": "s:9:0", "at": 1.0}
        res, _ = E.room_marks([ev])
        self.assertEqual([(e["room"], e["k"]) for e in res], [("main", "s:9:0.0"), ("deck", "s:9:0.1")])
        self.assertEqual(E.room_marks([dict(ev, t="One.")])[0][0]["k"], "s:9:0")


if __name__ == "__main__":
    unittest.main()
