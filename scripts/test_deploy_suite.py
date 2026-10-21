#!/usr/bin/env python3
"""Unit tests for the deploy's web suite in scripts/engineer.py (web_suite,
suite_scope): which run.sh the deploy runs, from test/changed.py's view of
the branch against the live branch. A scratch git repo holds the real
index.html and changed.py; run.sh itself is not run (its call is caught),
changed.py is. The step lines, which go to the deploy log, are kept.

    python3 scripts/test_deploy_suite.py      (~3s)
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402

UI = os.path.join(os.path.dirname(HERE), "lcars-ui")


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Suite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deploy-suite-test-")
        d = self.repo = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(d, "lcars-ui", "test"))
        shutil.copy(os.path.join(UI, "index.html"), os.path.join(d, "lcars-ui"))
        shutil.copy(os.path.join(UI, "test", "changed.py"), os.path.join(d, "lcars-ui", "test"))
        for f, text in (("lcars-ui/deck.html", "<html></html>\n"), ("lcars-ui/test/qa_chat.py", "# qa\n"),
                        ("CHANGELOG.md", "## 0.1.0\n")):
            with open(os.path.join(d, f), "w") as fh:
                fh.write(text)
        sh("git", "init", "-q", "-b", "deb", cwd=d)
        sh("git", "config", "user.email", "t@t", cwd=d)
        sh("git", "config", "user.name", "t", cwd=d)
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "base", cwd=d)
        sh("git", "checkout", "-qb", "eng/x", cwd=d)
        self.steps, self.calls, self.rc = [], [], 0
        real = E.run

        self.held = []  # the cores lock, as each suite run found it

        @contextlib.contextmanager
        def cores(on_wait=None, who=""):
            self.held.append(who)
            yield

        def run(args, **kw):
            if args[:2] == ["sh", "lcars-ui/test/run.sh"]:
                self.calls.append((args, kw.get("env") or {}))
                self.assertEqual(self.held, ["deploy"])  # the suite runs on the cores, one job at a time
                return subprocess.CompletedProcess(args, self.rc, "RESULT: PASS\n" if self.rc == 0 else "  FAIL x\n", "")
            return real(args, **kw)

        # (cores.lock is STATE's - the live one here: never taken by a test)
        self.ps = [mock.patch.object(E, "run", run), mock.patch.object(E, "step", self.steps.append),
                   mock.patch.object(E, "cores", cores)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, path, fn):
        p = os.path.join(self.repo, path)
        with open(p) as fh:
            s = fh.read()
        with open(p, "w") as fh:
            fh.write(fn(s))

    def bump(self):
        """what every commit does: APP_VERSION and the CHANGELOG"""
        self.edit("lcars-ui/index.html", lambda s: s.replace('const APP_VERSION = "', 'const APP_VERSION = "9', 1))
        self.edit("CHANGELOG.md", lambda s: "## 9.0.0\n" + s)

    def deploy(self):
        sh("git", "commit", "-qam", "change", cwd=self.repo)
        files = sh("git", "diff", "--name-only", "deb", "HEAD", cwd=self.repo).splitlines()
        with contextlib.redirect_stdout(io.StringIO()):   # the suite's tail, printed to the log
            E.web_suite(self.repo, files, "deb")
        return files

    def test_a_deck_deploy_runs_what_changed_picks(self):
        self.bump()
        self.edit("lcars-ui/deck.html", lambda s: s + "<!-- moved -->\n")
        files = self.deploy()
        self.assertIn("lcars-ui/index.html", files)       # the version bump is there...
        (args, env), = self.calls
        self.assertEqual(args, ["sh", "lcars-ui/test/run.sh", "--changed"])   # ...and is not a page change
        self.assertEqual((env.get("PERF"), env.get("CHANGED_BASE")), ("0", "deb"))
        self.assertIn("--changed): parse, structure, version, deck - lcars-ui/deck.html: deck", self.steps[-1])

    def test_a_page_deploy_runs_the_full_suite(self):
        self.bump()
        self.edit("lcars-ui/index.html", lambda s: s.replace("/* ===================== the calendar =====================",
                                                             "/* ===================== the calendar =====================\n// moved", 1))
        self.deploy()
        (args, env), = self.calls
        self.assertEqual(args, ["sh", "lcars-ui/test/run.sh"])
        self.assertEqual(env.get("PERF"), "0")
        self.assertEqual(self.steps[-1], "running the web suite (PERF=0)")

    def test_a_test_only_deploy_runs_the_quick_stages(self):
        self.bump()
        self.edit("lcars-ui/test/qa_chat.py", lambda s: s + "# moved\n")
        self.deploy()
        (args, _), = self.calls
        self.assertEqual(args[-1], "--changed")
        self.assertIn("--changed): parse, structure, version - ", self.steps[-1])
        self.assertIn("lcars-ui/test/qa_chat.py: not a run.sh stage", self.steps[-1])

    def test_no_ui_change_runs_nothing(self):
        self.edit("CHANGELOG.md", lambda s: "## 9.0.0\n" + s)
        self.deploy()
        self.assertEqual((self.calls, self.steps, self.held), ([], [], []))  # nor waits for the cores

    def test_changed_py_missing_or_broken_is_the_full_suite(self):
        self.bump()
        self.edit("lcars-ui/deck.html", lambda s: s + "<!-- moved -->\n")
        self.edit("lcars-ui/test/changed.py", lambda s: "raise SystemExit(3)\n")
        self.deploy()
        (args, _), = self.calls
        self.assertEqual(args, ["sh", "lcars-ui/test/run.sh"])

    def test_every_stage_picked_is_the_full_suite_by_name(self):
        self.edit("lcars-ui/test/changed.py", lambda s: s + "# moved\n")   # changed.py itself: the full run
        self.deploy()
        (args, _), = self.calls
        self.assertEqual(args, ["sh", "lcars-ui/test/run.sh"])

    def test_a_failing_suite_stops_the_deploy(self):
        self.rc = 1
        self.edit("lcars-ui/deck.html", lambda s: s + "<!-- moved -->\n")
        with self.assertRaises(RuntimeError):
            self.deploy()


class Classified(unittest.TestCase):
    """classified_touches: the deploy names a diff that touches the page's
    trusted code - the classified block, the CSP block, sw.js - so Number
    One escalates it (docs/design/confidential-entries.md, Q6)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deploy-suite-test-")
        d = self.repo = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(d, "lcars-ui"))
        shutil.copy(os.path.join(UI, "index.html"), os.path.join(d, "lcars-ui"))
        with open(os.path.join(d, "lcars-ui", "sw.js"), "w") as fh:
            fh.write("// sw\n")
        sh("git", "init", "-q", "-b", "deb", cwd=d)
        sh("git", "config", "user.email", "t@t", cwd=d)
        sh("git", "config", "user.name", "t", cwd=d)
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "base", cwd=d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def change(self, fn, path="lcars-ui/index.html"):
        p = os.path.join(self.repo, path)
        with open(p) as fh:
            s = fh.read()
        with open(p, "w") as fh:
            fh.write(fn(s))
        sh("git", "commit", "-qam", "change", cwd=self.repo)
        return E.classified_touches(self.repo, "HEAD~1", "HEAD")

    def test_a_version_bump_or_another_view_is_not_named(self):
        self.assertEqual(self.change(lambda s: s.replace('const APP_VERSION = "', 'const APP_VERSION = "9', 1)), [])
        self.assertEqual(self.change(lambda s: s.replace("/* ===================== state =====================",
                                                         "/* ===================== state =====================\n// x", 1)), [])

    def test_a_line_in_the_classified_block_is_named(self):
        self.assertEqual(self.change(lambda s: s.replace("const CLS_PW_MIN = 8;", "const CLS_PW_MIN = 6;", 1)),
                         ["the classified block"])

    def test_a_line_added_or_removed_in_it_is_named(self):
        self.assertEqual(self.change(lambda s: s.replace("const CLS_PW_MIN = 8;\n", "", 1)), ["the classified block"])
        self.assertEqual(self.change(lambda s: s.replace("const CLS_SECRET = 2;\n", "const CLS_SECRET = 2;\nleak();\n", 1)),
                         ["the classified block"])

    def test_the_csp_and_sw_js_are_named(self):
        self.assertEqual(self.change(lambda s: s.replace('"https://brouter.de"', '"https://evil.example"', 1)),
                         ["the page's CSP"])
        self.assertEqual(self.change(lambda s: s + "// more\n", "lcars-ui/sw.js"), ["sw.js"])

    def test_a_block_whose_markers_go_is_named(self):
        self.assertEqual(self.change(lambda s: s.replace("/* ===================== csp", "/* csp", 1)), ["the page's CSP"])

    def test_the_finished_line_and_deploy_status_carry_it(self):
        # do_deploy against this repo as the live checkout: the branch one
        # commit past deb, the pull and the rebase answered as if done
        sh("git", "checkout", "-qb", "eng/x", cwd=self.repo)
        self.change(lambda s: s.replace("const CLS_PW_MIN = 8;", "const CLS_PW_MIN = 6;", 1))
        sh("git", "checkout", "-q", "deb", cwd=self.repo)
        real = E.run

        def run(args, cwd=None, **kw):
            if args[:2] in (["git", "pull"], ["git", "rebase"]) or args[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            return real(args, cwd=cwd, **kw)
        with mock.patch.object(E, "LIVE", self.repo), mock.patch.object(E, "wt", return_value=self.repo), \
                mock.patch.object(E, "live_branch", return_value="deb"), \
                mock.patch.object(E, "branch", return_value="eng/x"), \
                mock.patch.object(E, "wait_until_idle"), mock.patch.object(E, "web_suite"), \
                mock.patch.object(E, "step"), mock.patch.object(E, "set_deploy") as sd, \
                mock.patch.object(E, "land_commits", return_value="deployed x: 1 files"), \
                mock.patch.object(E, "run", side_effect=run):
            msg = E.do_deploy("x")
        self.assertIn("CLASSIFIED: touches the classified block", msg)
        sd.assert_any_call(classified=["the classified block"])

if __name__ == "__main__":
    unittest.main()
