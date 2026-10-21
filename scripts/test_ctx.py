#!/usr/bin/env python3
"""Unit tests for scripts/engineer.py's context gauge: `context_tokens`, the
size of an engineer's context read from the usage on their session file's
last assistant line, and the turn-ended hook's line for Number One when it
is over ENG_CTX_HANDOVER - once per crossing, re-armed by a clear. A sample
session file in a temp directory, and a temp state directory (STATE).

    python3 scripts/test_ctx.py
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402


def assistant(inp, read, made, model="claude-opus-5-5", side=False):
    return {"type": "assistant", "isSidechain": side,
            "message": {"model": model, "role": "assistant", "content": [{"type": "text", "text": "aye"}],
                        "usage": {"input_tokens": inp, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": made, "output_tokens": 99}}}


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


class Ctx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-test-")
        self.path = os.path.join(self.tmp, "s.jsonl")
        self.state = mock.patch.object(E, "STATE", self.tmp)
        self.state.start()
        E.save("ada", {"title": "Ada", "session": "s", "under_no1": True})

    def tearDown(self):
        self.state.stop()
        shutil.rmtree(self.tmp)

    def write(self, *rows, partial=b""):
        with open(self.path, "wb") as f:
            for r in rows:
                f.write(json.dumps(r).encode() + b"\n")
            f.write(partial)

    def test_the_last_assistant_lines_three_input_counts_summed(self):
        self.write(user("hi"), assistant(3, 1000, 50), user("more"), assistant(2, 40836, 1143))
        self.assertEqual(E.context_tokens(self.path), 2 + 40836 + 1143)

    def test_synthetic_and_sidechain_lines_and_a_cut_last_line_are_passed_over(self):
        self.write(assistant(1, 150000, 5), assistant(9, 9, 9, side=True), assistant(0, 0, 0, model="<synthetic>"),
                   partial=b'{"type":"assistant","message":{"usage":{"input_tok')
        self.assertEqual(E.context_tokens(self.path), 150006)

    def test_found_behind_a_tool_result_longer_than_a_chunk(self):
        # a line bigger than the 256KB chunk, after the one that counts, and
        # one before it the reader must not stop at
        self.write(assistant(1, 10, 1), assistant(5, 210000, 7), user("x" * (600 * 1024)))
        self.assertEqual(E.context_tokens(self.path), 210012)

    def test_nothing_to_read_is_zero(self):
        self.assertEqual(E.context_tokens(None), 0)
        self.assertEqual(E.context_tokens(os.path.join(self.tmp, "none.jsonl")), 0)
        self.write(user("hi"))
        self.assertEqual(E.context_tokens(self.path), 0)

    def hook(self):
        """The turn-ended hook as Claude Code runs it; the note it would
        send Number One (None: nothing sent)."""
        sent = []
        stdin = io.StringIO(json.dumps({"transcript_path": self.path, "last_assistant_message": "Report: done."}))
        with mock.patch.object(E, "notify_no1", lambda about, text, **kw: sent.append(text)), \
                mock.patch.object(E, "spawn"), mock.patch.object(E, "seated", lambda n: False), \
                mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(io.StringIO()):
            with contextlib.suppress(SystemExit):
                E.cmd_hook("turn-ended", "ada")
        return sent[0] if sent else None

    def test_the_report_carries_the_line_once_per_crossing(self):
        mark = "[crew] ada context 210k, over the handover mark"
        self.write(assistant(1, 120000, 1))
        self.assertNotIn("handover", self.hook())
        self.write(assistant(1, 210000, 1))
        note = self.hook()
        self.assertTrue(note.startswith("[crew] ada (Ada) finished a turn. Last words: Report: done."), note)
        self.assertTrue(note.endswith("\n" + mark), note)
        # still over: not said again
        self.write(assistant(1, 230000, 1))
        self.assertNotIn("handover", self.hook())
        # a clear brings it under; the next crossing is told again
        self.write(assistant(1, 20000, 1))
        self.assertNotIn("handover", self.hook())
        self.assertNotIn("ctx_over", E.load("ada"))
        self.write(assistant(1, 250000, 1))
        self.assertIn("[crew] ada context 250k, over the handover mark", self.hook())

    def test_not_under_number_one_nothing_is_sent(self):
        E.save("ada", {"title": "Ada", "session": "s"})
        self.write(assistant(1, 250000, 1))
        self.assertIsNone(self.hook())


if __name__ == "__main__":
    unittest.main()
