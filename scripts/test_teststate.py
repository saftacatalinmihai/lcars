#!/usr/bin/env python3
"""No test reaches the box's real engineer state (scripts/teststate.py).

On 2026-10-22 test_no1_threads.py's deploy case wrote a phantom "queued"
deploy into the real ~/.local/state/lcars-eng/deploy.json: it patched
E.STATE, and engineer.py's DEPLOY_JSON, made from STATE when it loaded,
was still the real one. Here: every path engineer.py made at load is
outside the real directory; that very case, replayed, leaves the real
deploy.json as it was; teststate.py replaces a real LCARS_ENG_STATE and
keeps a test's own; and every test that loads engineer.py loads teststate
(or testguard) first, or sets LCARS_ENG_STATE itself before it.

    python3 scripts/test_teststate.py
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - and with it teststate
import teststate  # noqa: E402
import engineer as E  # noqa: E402


def paths_of(mod):
    """Every module-level string of mod that looks like a path."""
    return {k: v for k, v in vars(mod).items() if isinstance(v, str) and v.startswith("/")}


class Isolation(unittest.TestCase):
    def test_engineer_paths_are_scratch(self):
        self.assertFalse(teststate.real(E.STATE), E.STATE)
        for k, v in paths_of(E).items():
            self.assertFalse(teststate.real(v), f"engineer.{k} is in the real state: {v}")
        self.assertFalse(teststate.real(E.jobs_dir()))

    def test_the_leak_replayed(self):
        # the guard must hold before this is run at all: it is the write
        # that leaked
        if any(teststate.real(v) for v in paths_of(E).values()):
            self.fail("engineer.py's paths are the real state's: not replaying the deploy case")
        real = os.path.join(teststate.REAL, "deploy.json")
        before = (os.stat(real).st_mtime_ns, open(real, "rb").read()) if os.path.exists(real) else None
        with tempfile.TemporaryDirectory(prefix="guard-test-") as d:
            ok = mock.Mock(returncode=0, stdout="", stderr="")
            # as test_no1_threads.py did: STATE patched, nothing else
            with mock.patch.object(E, "STATE", d), mock.patch.object(E, "run", return_value=ok), \
                    mock.patch.object(E, "out"), mock.patch.dict(os.environ, {"LCARS_THREAD_BY": ""}):
                E.detach("deploy", "obrien")
            self.assertEqual(E.read_deploy()["name"], "obrien", "written, to the scratch state")
        after = (os.stat(real).st_mtime_ns, open(real, "rb").read()) if os.path.exists(real) else None
        self.assertEqual(after, before, "the real deploy.json untouched")

    def run_teststate(self, env):
        code = "import sys; sys.path.insert(0, %r); import teststate, os; print(os.environ['LCARS_ENG_STATE'])" % HERE
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        return p.stdout.strip()

    def test_a_real_state_is_replaced(self):
        env = dict(os.environ, LCARS_ENG_STATE=teststate.REAL)
        got = self.run_teststate(env)
        self.assertFalse(teststate.real(got), got)
        env.pop("LCARS_ENG_STATE")
        self.assertFalse(teststate.real(self.run_teststate(env)))

    def test_a_tests_own_is_kept(self):
        with tempfile.TemporaryDirectory(prefix="guard-test-") as d:
            self.assertEqual(self.run_teststate(dict(os.environ, LCARS_ENG_STATE=d)), d)

    def test_after_engineer_refused(self):
        code = ("import sys; sys.path.insert(0, %r); import os; os.environ.pop('LCARS_ENG_STATE', None); "
                "import types; sys.modules['engineer'] = types.ModuleType('engineer'); import teststate") % HERE
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("after engineer.py", p.stderr)

    def test_every_test_guards_its_import(self):
        """A test file that loads engineer.py names teststate or testguard,
        or sets LCARS_ENG_STATE, on a line before it."""
        load = re.compile(r"^\s*import engineer\b|^\s*from engineer import|spec_from_file_location\([^)]*engineer", re.M)
        guard = re.compile(r"^\s*import (teststate|testguard)\b|LCARS_ENG_STATE=", re.M)
        for name in sorted(os.listdir(HERE)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            src = open(os.path.join(HERE, name), encoding="utf-8").read()
            m = load.search(src)
            if not m:
                continue
            g = guard.search(src[:m.start()])
            self.assertIsNotNone(g, f"{name} loads engineer.py with no teststate/testguard before it")


if __name__ == "__main__":
    unittest.main()
