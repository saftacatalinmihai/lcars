#!/usr/bin/env python3
"""Unit tests for scripts/engineer.py's `brief <role>`: a scheduled role's
crew/<role>.md, read-only, for a slug naming a file there and nothing else.
A temp crew directory (LCARS_CREW_DIR) stands in for the live checkout's,
with a secret beside it that no role may reach.

    python3 scripts/test_brief.py
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


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="brief-test-")
        self.crew = os.path.join(self.tmp, "crew")
        os.makedirs(self.crew)
        with open(os.path.join(self.crew, "yeoman.md"), "w") as f:
            f.write("---\ntitle: Yeoman, journal hygiene\nbudget: 0.40\n---\nEach night, look for untidiness.\n")
        with open(os.path.join(self.tmp, "secret.md"), "w") as f:
            f.write("not a brief\n")
        os.symlink(os.path.join(self.tmp, "secret.md"), os.path.join(self.crew, "leak.md"))
        self.env = mock.patch.dict(os.environ, {"LCARS_CREW_DIR": self.crew})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def brief(self, *args):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf):
            try:
                E.main(["brief", *args])
            except SystemExit as e:
                code = e.code or 0
        return code, json.loads(buf.getvalue() or "{}")

    def test_a_role_gets_its_brief_without_the_front_matter(self):
        code, r = self.brief("yeoman")
        self.assertEqual(code, 0)
        self.assertEqual(r["role"], "yeoman")
        self.assertEqual(r["title"], "Yeoman, journal hygiene")
        self.assertEqual(r["brief"], "Each night, look for untidiness.")

    def test_an_unknown_role_is_refused(self):
        code, r = self.brief("nope")
        self.assertEqual(code, 2)
        self.assertIn("no such role", r["error"])

    def test_a_path_is_never_a_role(self):
        for bad in ("../secret", "..", "yeoman/../yeoman", "/etc/passwd", "Yeoman", "yeoman\n", "", "-x"):
            code, r = self.brief(bad)
            self.assertEqual(code, 2, bad)
            self.assertNotIn("brief", r, bad)

    def test_a_link_out_of_the_crew_directory_is_refused(self):
        code, r = self.brief("leak")
        self.assertEqual(code, 2)
        self.assertNotIn("brief", r)

    def test_no_role_at_all_is_refused(self):
        code, _ = self.brief()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
