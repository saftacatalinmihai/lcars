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


if __name__ == "__main__":
    unittest.main()
