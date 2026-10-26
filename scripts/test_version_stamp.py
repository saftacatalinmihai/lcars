#!/usr/bin/env python3
"""Tests for the version the deploy gives (docs/design/version-at-deploy.md):
scripts/version-stamp.py (the rebase's -x), scripts/changelog-merge.py (the
CHANGELOG merge driver), and do_deploy's floor, checks and outcome, on
scratch git repos - a "live" checkout and engineers' worktrees of it.

    python3 scripts/test_version_stamp.py      (~5s)
"""

import atexit
import contextlib
import io
import json
import re
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lcars-ui", "test"))
import killclean  # noqa: E402 - the scratch goes with a killed run

TMP = killclean.mkdtemp("version-stamp-test-")
atexit.register(shutil.rmtree, TMP, True)
VS = E.stamp_mod()
STAMP = os.path.join(HERE, "version-stamp.py")
DRIVER = os.path.join(HERE, "changelog-merge.py")
sys.path.insert(0, HERE)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("changelog_merge", DRIVER)
CM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CM)

PRE = "# Changelog\n\nThe version at the top is the version.\n\n"


def log(*entries):
    """A CHANGELOG of these (heading, text) entries, top first."""
    return PRE + "\n".join(f"## {h}\n\n- {t}\n" for h, t in entries)


def page(v):
    return f'<script>\nconst APP_VERSION = "{v}";\n</script>\n<p>page</p>\n'


def sh(*a, cwd, check=True, env=None):
    p = subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(f"{' '.join(a)}: {p.stdout}{p.stderr}")
    return p


class Plan(unittest.TestCase):
    """version-stamp.py's decision for one commit: pure."""

    OLD = log(("0.5.2 — 2026-10-01", "b"), ("0.5.1 — 2026-09-30", "a"))

    def plan(self, top, floor=(0, 0, 0)):
        return VS.plan(log((top, "new"), ("0.5.2 — 2026-10-01", "b"), ("0.5.1 — 2026-09-30", "a")), self.OLD, floor)

    def test_patch_and_minor(self):
        self.assertEqual(self.plan("next patch — 2026-10-22")[1], (0, 5, 3))
        self.assertEqual(self.plan("next minor — 2026-10-22")[1], (0, 6, 0))

    def test_above_the_floor(self):
        # a rolled-back 0.5.7: the floor is above main's top
        self.assertEqual(self.plan("next patch — 2026-10-22", (0, 5, 7))[1], (0, 5, 8))
        self.assertEqual(self.plan("next minor — 2026-10-22", (0, 5, 7))[1], (0, 6, 0))

    def test_an_old_style_number(self):
        self.assertEqual(self.plan("0.5.9 — 2026-10-22")[1], (0, 5, 9))  # above both: kept
        self.assertEqual(self.plan("0.5.2 — 2026-10-22")[1], (0, 5, 3))  # taken: renumbered, a patch
        self.assertEqual(self.plan("0.5.3 — 2026-10-22", (0, 5, 4))[1], (0, 5, 5))
        self.assertEqual(self.plan("0.5.0 — 2026-10-22")[1], (0, 6, 0))  # .0: a minor

    def test_nothing_added(self):
        self.assertIsNone(VS.plan(self.OLD, self.OLD, (0, 0, 0)))
        # an edit inside an old entry's text adds nothing
        self.assertIsNone(VS.plan(self.OLD.replace("- b", "- b, fixed"), self.OLD, (0, 0, 0)))

    def test_refusals(self):
        two = log(("next patch — x", "1"), ("next patch — y", "2"), ("0.5.2 — 2026-10-01", "b"),
                  ("0.5.1 — 2026-09-30", "a"))
        with self.assertRaisesRegex(VS.Refused, "2 new entries in one commit"):
            VS.plan(two, self.OLD, (0, 0, 0))
        with self.assertRaisesRegex(VS.Refused, "the kind is patch or minor"):
            self.plan("next major — 2026-10-22")
        with self.assertRaisesRegex(VS.Refused, "neither a version"):
            self.plan("soon — 2026-10-22")
        below = log(("0.5.2 — 2026-10-01", "b"), ("next patch — x", "n"), ("0.5.1 — 2026-09-30", "a"))
        with self.assertRaisesRegex(VS.Refused, "below the top"):
            VS.plan(below, self.OLD, (0, 0, 0))
        # a placeholder left below by an earlier commit
        old = log(("0.5.2 — 2026-10-01", "b"), ("next patch — x", "n"))
        with self.assertRaisesRegex(VS.Refused, "a placeholder below a numbered entry"):
            VS.plan(log(("next patch — y", "m"), ("0.5.2 — 2026-10-01", "b"), ("next patch — x", "n")), old, (0, 0, 0))

    def test_apply(self):
        new = log(("next patch — 2026-10-20", "new"), ("0.5.2 — 2026-10-01", "b"))
        with mock.patch.object(VS, "today", return_value="2026-10-22"):
            text, pg, subj = VS.apply(new, page("0.5.2"), "Fix the thing (patch)", "next patch — 2026-10-20", (0, 5, 3))
        self.assertTrue(text.startswith(PRE + "## 0.5.3 — 2026-10-22\n\n- new\n"))
        self.assertIn('const APP_VERSION = "0.5.3";', pg)
        self.assertEqual(subj, "Fix the thing (0.5.3)")
        self.assertEqual(VS.apply(new, None, "No mark", "next patch — 2026-10-20", (0, 5, 3))[2], "No mark (0.5.3)")
        self.assertEqual(VS.apply(new, None, "Old (0.5.2)", "next patch — 2026-10-20", (0, 5, 3))[2], "Old (0.5.3)")
        # the heading's own line, not a mention of the format in the preamble
        doc = new.replace(PRE, PRE[:-1] + "Write `## next patch — 2026-10-20` on top.\n\n")
        with mock.patch.object(VS, "today", return_value="2026-10-22"):
            out = VS.apply(doc, None, "s", "next patch — 2026-10-20", (0, 5, 3))[0]
        self.assertIn("Write `## next patch — 2026-10-20` on top.", out)
        self.assertIn("\n## 0.5.3 — 2026-10-22\n\n- new\n", out)
        # an old-style number kept keeps its date
        kept = log(("0.5.9 — 2026-10-20", "new"), ("0.5.2 — 2026-10-01", "b"))
        self.assertTrue(VS.apply(kept, None, "s (0.5.9)", "0.5.9 — 2026-10-20", (0, 5, 9))[0]
                        .startswith(PRE + "## 0.5.9 — 2026-10-20"))


    def test_a_fixed_day_from_the_environment(self):
        with mock.patch.dict(os.environ, {"LCARS_STAMP_TODAY": "2031-02-03"}):
            self.assertEqual(VS.today(), "2031-02-03")
        with mock.patch.dict(os.environ, {"LCARS_STAMP_TODAY": "tomorrow", "LCARS_TZ": "UTC"}):
            self.assertRegex(VS.today(), r"^\d{4}-\d{2}-\d{2}$")  # not a day: the clock's
            self.assertNotEqual(VS.today(), "tomorrow")

    def test_a_commit_with_no_entry_is_marked_by_its_branch(self):
        self.assertEqual(VS.remark("Review fixes (patch)", (0, 5, 4), (0, 5, 3)), "Review fixes (0.5.4)")
        self.assertEqual(VS.remark("Review fixes (0.5.3)", (0, 5, 4), (0, 5, 3)), "Review fixes (0.5.4)")
        # none of the branch's own yet: the live branch's top is not this commit's
        self.assertEqual(VS.remark("Prep (0.5.2)", (0, 5, 3), (0, 5, 3)), "Prep")
        self.assertEqual(VS.remark("Prep", (0, 5, 4), (0, 5, 3)), "Prep")


_vspec = importlib.util.spec_from_file_location("version_check", os.path.join(os.path.dirname(HERE), "lcars-ui",
                                                                              "test", "version.py"))
VC = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(VC)
EXPLAINER = os.path.join(os.path.dirname(HERE), "video", "explainer")


class Check(unittest.TestCase):
    """run.sh's version check (lcars-ui/test/version.py), and the explainer's
    readers, under a placeholder."""

    MAIN = log(("0.5.2 — 2026-10-01", "b"), ("0.5.1 — 2026-09-30", "a"))

    def top(self, *heads_):
        return log(*[(h, "x") for h in heads_], ("0.5.2 — 2026-10-01", "b"), ("0.5.1 — 2026-09-30", "a"))

    def test_numbered(self):
        self.assertEqual(VC.check(self.MAIN, page("0.5.2")), ("ok", "0.5.2"))
        self.assertEqual(VC.check(self.MAIN, page("0.5.3"))[0], "FAIL")

    def test_placeholders_on_top(self):
        self.assertEqual(VC.check(self.top("next patch — 2026-10-22"), page("0.5.2")),
                         ("ok", "0.5.2 + next patch, numbered at deploy"))
        self.assertEqual(VC.check(self.top("next patch — y", "next minor — x"), page("0.5.2")),
                         ("ok", "0.5.2 + next patch, next minor, numbered at deploy"))

    def test_fragments(self):
        frags = {"ada-x.md": "minor\n- ada's x\n", "bob-y.md": "patch\n- y\n"}
        self.assertEqual(VC.check(self.MAIN, page("0.5.2"), frags=frags),
                         ("ok", "0.5.2 + fragment minor, fragment patch, numbered at deploy"))
        self.assertEqual(VC.check(self.top("next patch — x"), page("0.5.2"), frags={"a.md": "minor\n- a\n"}),
                         ("ok", "0.5.2 + next patch, fragment minor, numbered at deploy"))
        for text, why in (("major\n- x\n", "the first line is `minor` or `patch`"), ("patch\n\n", "no entry text")):
            v, msg = VC.check(self.MAIN, page("0.5.2"), frags={"a.md": text})
            self.assertEqual(v, "FAIL")
            self.assertIn(why, msg)
        v, msg = VC.check(self.MAIN, page("0.5.3"), frags=frags)
        self.assertEqual(v, "FAIL")
        self.assertIn("beside a fragment", msg)
        root = os.path.join(TMP, "fragroot")
        os.makedirs(os.path.join(root, "changelog.d"), exist_ok=True)
        for name in ("README.md", "ok-one.md", "Bad Name.md"):
            with open(os.path.join(root, "changelog.d", name), "w") as f:
                f.write("patch\n- x\n")
        import pathlib
        frags2, bad = VC.fragments(pathlib.Path(root))
        self.assertEqual((list(frags2), len(bad)), (["ok-one.md"], 1))

    def test_the_failures(self):
        for text, app, why in ((self.top("0.5.3 — x", "next patch — y"), "0.5.3", "a placeholder below a numbered"),
                               (self.top("next major — x"), "0.5.2", "the kind is patch or minor"),
                               (self.top("next patch — x"), "0.5.3", "APP_VERSION is 0.5.3 under a placeholder"),
                               (self.top("Unreleased"), "0.5.2", "neither a version")):
            v, msg = VC.check(text, page(app))
            self.assertEqual(v, "FAIL", text)
            self.assertIn(why, msg)
        two = self.top("next patch — y", "next patch — x")
        v, msg = VC.check(two, page("0.5.2"), [("commit abc1234", two, self.MAIN)])
        self.assertEqual((v, msg), ("FAIL", "commit abc1234 adds 2 CHANGELOG entries: one each (the deploy numbers "
                                            "one per commit)"))
        # one each in two commits passes
        one = self.top("next patch — x")
        self.assertEqual(VC.check(two, page("0.5.2"), [("c1", one, self.MAIN), ("c2", two, one)])[0], "ok")

    # the public tree has no video/ (the export leaves the explainer's
    # production out), so nothing of it to check there
    @unittest.skipUnless(os.path.isdir(EXPLAINER), "no video/explainer/ (the public tree)")
    def test_the_explainers_plus_and_deliver_refusing(self):
        root = os.path.join(TMP, "explainer")
        d = os.path.join(root, "video", "explainer")
        os.makedirs(os.path.join(root, "lcars-ui"), exist_ok=True)
        os.makedirs(d, exist_ok=True)
        for f in ("version.mjs", "deliver.sh"):
            shutil.copy(os.path.join(EXPLAINER, f), d)
        with open(os.path.join(root, "lcars-ui", "index.html"), "w") as f:
            f.write(page("0.5.2"))
        js = "import('./version.mjs').then(m => console.log(m.appVersion()))"
        for text, want in ((self.MAIN, "0.5.2"), (self.top("next patch — x"), "0.5.2+")):
            with open(os.path.join(root, "CHANGELOG.md"), "w") as f:
                f.write(text)
            self.assertEqual(sh("node", "-e", js, cwd=d).stdout.strip(), want)
            p = sh("sh", "deliver.sh", "Cut", cwd=d, check=False)
            self.assertEqual(p.returncode, 1)
            if want.endswith("+"):
                self.assertIn("placeholder on top: deliver after the deploy has numbered this tree", p.stderr)
            else:
                self.assertIn("no out/Cut.mp4", p.stderr)  # past the check, to its own


class Driver(unittest.TestCase):
    """changelog-merge.py's merge(): base, ours, theirs."""

    BASE = log(("0.5.2 — d", "b"), ("0.5.1 — d", "a"))

    def test_two_stacked_tops_in_both_orders(self):
        ours = log(("0.5.3 — d", "main's"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        theirs = log(("next patch — d", "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        self.assertEqual(CM.merge(self.BASE, ours, theirs),
                         log(("next patch — d", "mine"), ("0.5.3 — d", "main's"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a")))
        self.assertEqual(CM.merge(self.BASE, theirs, ours),
                         log(("0.5.3 — d", "main's"), ("next patch — d", "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a")))
        # the same number picked on both sides the old way: both kept, the stamp renumbers
        clash = log(("0.5.3 — d", "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        self.assertEqual(VS.heads(CM.merge(self.BASE, ours, clash)), ["0.5.3 — d"] * 2 + ["0.5.2 — d", "0.5.1 — d"])

    def test_one_sided_changes(self):
        ours = log(("0.5.3 — d", "main's"), ("0.5.2 — d", "b, fixed"), ("0.5.1 — d", "a"))
        theirs = ("# Changelog\n\nA new preamble.\n\n" + self.BASE[len(PRE):]).replace("- a", "- a, too")
        out = CM.merge(self.BASE, ours, theirs)
        self.assertTrue(out.startswith("# Changelog\n\nA new preamble.\n\n## 0.5.3"))
        self.assertIn("- b, fixed", out)
        self.assertIn("- a, too", out)

    def test_conflicts(self):
        a = self.BASE.replace("- b", "- b, ours")
        b = self.BASE.replace("- b", "- b, theirs")
        with self.assertRaisesRegex(CM.Conflict, "changed on both sides"):
            CM.merge(self.BASE, a, b)
        below = log(("0.5.2 — d", "b"), ("next patch — d", "n"), ("0.5.1 — d", "a"))
        with self.assertRaisesRegex(CM.Conflict, "below the top"):
            CM.merge(self.BASE, self.BASE, below)

    def test_a_later_commit_edits_an_entry_the_stamp_renumbered(self):
        # the replay of a branch's second commit: O its first as written, A
        # that first as stamped, B the second, which edited the entry's text
        for was in ("next patch — 2026-10-20", "0.5.2 — 2026-10-20"):
            o = log((was, "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
            a = log(("0.5.4 — 2026-10-22", "mine"), ("0.5.3 — d", "main's"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
            b = log((was, "mine, reviewed"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
            self.assertEqual(CM.merge(o, a, b), a.replace("- mine\n", "- mine, reviewed\n"))
        # its heading changed by B too: a conflict
        b2 = log(("next minor — x", "mine, reviewed"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        o = log(("next patch — x", "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        a = log(("0.5.3 — y", "mine"), ("0.5.2 — d", "b"), ("0.5.1 — d", "a"))
        with self.assertRaises(CM.Conflict):
            CM.merge(o, a, b2)
        # any old entry: A's heading, B's text, as git's own merge would
        o = self.BASE
        self.assertEqual(CM.merge(o, o.replace("0.5.2 — d", "0.5.2 — e"), o.replace("- b\n", "- b, theirs\n")),
                         o.replace("0.5.2 — d", "0.5.2 — e").replace("- b\n", "- b, theirs\n"))

    def test_the_driver_leaves_markers_on_a_conflict(self):
        d = os.path.join(TMP, "drv")
        os.makedirs(d, exist_ok=True)
        for n, t in (("o", self.BASE), ("a", self.BASE.replace("- b", "- b, ours")),
                     ("b", self.BASE.replace("- b", "- b, theirs"))):
            with open(os.path.join(d, n), "w") as f:
                f.write(t)
        p = sh(sys.executable, DRIVER, "o", "a", "b", cwd=d, check=False)
        self.assertEqual(p.returncode, 1)
        with open(os.path.join(d, "a")) as f:
            self.assertIn("<<<<<<< ours", f.read())


class Deploys(unittest.TestCase):
    """End to end: a scratch live checkout on `deb`, two engineers' worktrees
    of it, do_deploy with the pull, the wait, the web suite, the rebuild and
    the push stood in for."""

    def setUp(self):
        self.root = os.path.join(TMP, self.id().rsplit(".", 1)[1])
        shutil.rmtree(self.root, ignore_errors=True)
        self.live = os.path.join(self.root, "live")
        os.makedirs(os.path.join(self.live, "lcars-ui"))
        os.makedirs(os.path.join(self.live, "scripts"))
        for f in ("version-stamp.py", "changelog-merge.py"):
            shutil.copy(os.path.join(HERE, f), os.path.join(self.live, "scripts", f))
        self.write(self.live, log(("0.5.2 — 2026-10-01", "b"), ("0.5.1 — 2026-09-30", "a")), "0.5.2")
        with open(os.path.join(self.live, ".gitattributes"), "w") as f:
            f.write("CHANGELOG.md merge=lcars-changelog\nTODO.md merge=union\n")
        with open(os.path.join(self.live, "TODO.md"), "w") as f:
            f.write("# TODO\n\n- [ ] one\n\n- [ ] two\n")
        sh("git", "init", "-q", "-b", "deb", cwd=self.live)
        sh("git", "config", "user.email", "t@t", cwd=self.live)
        sh("git", "config", "user.name", "t", cwd=self.live)
        sh("git", "add", "-A", cwd=self.live)
        sh("git", "commit", "-qm", "base (0.5.2)", cwd=self.live)
        for n in ("ada", "bob"):
            sh("git", "worktree", "add", "-q", "-b", "eng/" + n, self.wt(n), "deb", cwd=self.live)
        self.hist = os.path.join(self.root, "deploys.jsonl")
        real = E.run

        def run(args, cwd=None, **kw):
            if args[:2] == ["git", "pull"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            return real(args, cwd=cwd, **kw)
        self.p = [mock.patch.object(E, "LIVE", self.live), mock.patch.object(E, "wt", self.wt),
                  mock.patch.object(E, "live_branch", return_value="deb"),
                  mock.patch.object(E, "branch", lambda n: "eng/" + n),
                  mock.patch.object(E, "wait_until_idle"), mock.patch.object(E, "web_suite"),
                  mock.patch.object(E, "step"), mock.patch.object(E, "set_deploy"),
                  mock.patch.object(E, "c_changed", return_value=False), mock.patch.object(E, "push", return_value=""),
                  mock.patch.object(E, "no1_after_land", return_value=""), mock.patch.object(E, "HISTORY", self.hist),
                  # never the real report in the media store: a test turns it on with a scratch path
                  mock.patch.object(E, "MANUAL_REPORT", ""),
                  mock.patch.object(E, "run", side_effect=run), mock.patch.object(VS, "today", return_value="2026-10-22"),
                  # the stamp runs in the deploy's rebase, a process of its
                  # own: the day reaches it in its environment, not the mock
                  mock.patch.dict(os.environ, {"LCARS_TZ": "UTC", "LCARS_STAMP_TODAY": "2026-10-22"})]
        # the journal the release entries are written to: a stand-in
        self.journal, self.journal_down = [], False
        self.p.append(mock.patch.object(E.release_mod(), "api", self.journal_api))
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def journal_api(self, method, path, body=None, timeout=60):
        if self.journal_down:
            return 0, {"error": "http://127.0.0.1:9: refused"}
        if method == "GET" and path.startswith("/dump?") and "kind=release" in path:
            return 200, [dict(e, id=i + 1) for i, e in enumerate(self.journal)]
        if method == "POST" and path == "/entries":
            self.journal.append(body)
            return 201, {"id": len(self.journal)}
        return 404, {"error": "not stood in: " + path}

    def wt(self, n):
        return os.path.join(self.root, n)

    def write(self, d, changelog=None, app=None):
        if changelog is not None:
            with open(os.path.join(d, "CHANGELOG.md"), "w") as f:
                f.write(changelog)
        if app is not None:
            with open(os.path.join(d, "lcars-ui", "index.html"), "w") as f:
                f.write(page(app))

    def read(self, d, f="CHANGELOG.md"):
        with open(os.path.join(d, f)) as fh:
            return fh.read()

    def entry(self, n, top, text, app=None, subject=None, other=None):
        """A commit on n's branch: an entry `top` on their CHANGELOG."""
        d = self.wt(n)
        self.write(d, log((top, text)) [:len(PRE)] + f"## {top}\n\n- {text}\n\n" + self.read(d)[len(PRE):], app)
        if other:
            with open(os.path.join(d, other), "w") as f:
                f.write(text)
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", subject or f"{text} (patch)", cwd=d)

    def deploy(self, n):
        with contextlib.redirect_stdout(io.StringIO()):  # the rebase's log, the deploy log's
            return E.do_deploy(n)

    def main_top(self):
        return VS.heads(self.read(self.live))[0]

    def app(self):
        return self.read(self.live, "lcars-ui/index.html").split('"')[1]

    def test_two_placeholders_from_one_main_land_in_order(self):
        self.entry("ada", "next patch — 2026-10-20", "ada's fix", other="a.txt")
        self.entry("bob", "next minor — 2026-10-21", "bob's feature", other="b.txt")
        self.entry("bob", "next patch — 2026-10-21", "bob's polish", subject="Polish it")
        msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.5.3: ", msg)
        self.assertEqual((self.main_top(), self.app()), ("0.5.3 — 2026-10-22", "0.5.3"))
        # bob's own rebase onto it resolves through the driver
        sh("git", "rebase", "deb", cwd=self.wt("bob"))
        msg = self.deploy("bob")
        self.assertIn("deployed bob as 0.6.0, 0.6.1: ", msg)
        hs = VS.heads(self.read(self.live))
        self.assertEqual(hs, ["0.6.1 — 2026-10-22", "0.6.0 — 2026-10-22", "0.5.3 — 2026-10-22",
                              "0.5.2 — 2026-10-01", "0.5.1 — 2026-09-30"])
        self.assertEqual(self.app(), "0.6.1")
        subj = sh("git", "log", "--format=%s", "-3", cwd=self.live).stdout.split("\n")
        self.assertEqual(subj[:3], ["Polish it (0.6.1)", "bob's feature (0.6.0)", "ada's fix (0.5.3)"])
        self.assertEqual(E.versions_in(subj), ["0.6.1", "0.6.0", "0.5.3"])
        # the trailers are kept, and nothing is left unnumbered
        self.assertNotIn("next ", self.read(self.live))
        hist = [json.loads(ln) for ln in open(self.hist)]
        self.assertEqual([r["versions"] for r in hist], [["0.5.3"], ["0.6.1", "0.6.0"]])

    def test_without_their_own_rebase_too(self):
        self.entry("ada", "next patch — 2026-10-20", "ada's fix")
        self.entry("bob", "next patch — 2026-10-21", "bob's fix")
        self.deploy("ada")
        self.assertIn("deployed bob as 0.5.4: ", self.deploy("bob"))
        self.assertEqual(VS.heads(self.read(self.live))[:2], ["0.5.4 — 2026-10-22", "0.5.3 — 2026-10-22"])

    def test_the_old_way_collides_and_is_renumbered(self):
        # both picked 0.5.3 by hand, APP_VERSION and all, from the same main
        self.entry("ada", "0.5.3 — 2026-10-20", "ada's fix", app="0.5.3", subject="Fix (0.5.3)")
        self.entry("bob", "0.5.3 — 2026-10-21", "bob's fix", app="0.5.3", subject="Fix too (0.5.3)")
        self.assertIn("deployed ada as 0.5.3: ", self.deploy("ada"))
        self.assertEqual(self.main_top(), "0.5.3 — 2026-10-20")  # kept, its date too
        self.assertIn("deployed bob as 0.5.4: ", self.deploy("bob"))
        self.assertEqual(self.app(), "0.5.4")
        self.assertEqual(sh("git", "log", "-1", "--format=%s", cwd=self.live).stdout.strip(), "Fix too (0.5.4)")

    def review_fix(self, top, own_rebase, app=None):
        """bob lands 0.5.3 first; ada's branch: a commit with no entry, her
        entry `top`, and a review fix editing that entry's text."""
        self.entry("bob", "next patch — 2026-10-21", "bob's fix")
        self.deploy("bob")
        d = self.wt("ada")
        with open(os.path.join(d, "prep.txt"), "w") as f:
            f.write("prep")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "Prep (0.5.2)", cwd=d)
        self.entry("ada", top, "ada's fix", app=app, subject="Fix (patch)" if top.startswith("next") else "Fix (0.5.3)")
        self.write(d, self.read(d).replace("- ada's fix\n", "- ada's fix, reviewed\n"))
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("review")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "Review fixes " + ("(patch)" if top.startswith("next") else "(0.5.3)"), cwd=d)
        if own_rebase:
            sh("git", "rebase", "deb", cwd=d)
        self.assertIn("deployed ada as 0.5.4: ", self.deploy("ada"))
        text = self.read(self.live)
        self.assertTrue(text.startswith(PRE + "## 0.5.4 — 2026-10-22\n\n- ada's fix, reviewed\n\n## 0.5.3 — 2026-10-22\n"),
                        text[:300])
        self.assertEqual(self.app(), "0.5.4")
        subj = sh("git", "log", "--format=%s", "-3", cwd=self.live).stdout.split("\n")[:3]
        self.assertEqual(subj, ["Review fixes (0.5.4)", "Fix (0.5.4)", "Prep"])
        hist = [json.loads(ln) for ln in open(self.hist)]
        self.assertEqual(hist[-1]["versions"], ["0.5.4"])

    def test_a_review_fix_of_a_placeholder(self):
        self.review_fix("next patch — 2026-10-20", False)

    def test_a_review_fix_of_a_placeholder_after_their_own_rebase(self):
        self.review_fix("next patch — 2026-10-20", True)

    def test_a_review_fix_of_an_old_way_number_renumbered(self):
        self.review_fix("0.5.3 — 2026-10-20", False, app="0.5.3")

    def test_a_review_fix_of_an_old_way_number_after_their_own_rebase(self):
        self.review_fix("0.5.3 — 2026-10-20", True, app="0.5.3")

    def test_the_stamp_gets_the_captains_zone(self):
        with mock.patch.dict(os.environ, {"HOME": self.root}), mock.patch.object(E, "HOME", self.root):
            os.environ.pop("LCARS_TZ", None)
            with open(os.path.join(self.root, ".env"), "w") as f:
                f.write("export LCARS_TZ=Pacific/Auckland\n")
            env = E.stamp_env("0.5.2")
        self.assertEqual((env["LCARS_TZ"], env["LCARS_VERSION_FLOOR"]), ("Pacific/Auckland", "0.5.2"))

    def test_the_floor_counts_a_rolled_back_version(self):
        with open(self.hist, "w") as f:
            f.write(json.dumps({"versions": ["0.5.7"], "outcome": "rolled_back"}) + "\n")
        self.assertEqual(E.version_floor("deb"), "0.5.7")
        self.entry("ada", "next patch — 2026-10-20", "ada's fix")
        self.assertIn("deployed ada as 0.5.8: ", self.deploy("ada"))

    def test_a_real_conflict_leaves_the_branch_as_it_was(self):
        self.entry("ada", "next patch — 2026-10-20", "ada's fix")
        self.deploy("ada")
        # the same old entry edited on main and on bob's branch
        d = self.wt("bob")
        sh("git", "-C", self.live, "checkout", "-q", "deb", cwd=self.live)
        with open(os.path.join(self.live, "CHANGELOG.md")) as f:
            t = f.read()
        self.write(self.live, t.replace("- a\n", "- a, main's\n"))
        sh("git", "commit", "-qam", "main edits 0.5.1", cwd=self.live)
        self.write(d, self.read(d).replace("- a\n", "- a, bob's\n"))
        sh("git", "commit", "-qam", "bob edits 0.5.1", cwd=d)
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout
        with self.assertRaisesRegex(RuntimeError, r"conflicts: CHANGELOG.md\).*edited on both sides"):
            self.deploy("bob")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout, before)
        self.assertEqual(sh("git", "status", "--porcelain", cwd=d).stdout, "")

    def test_a_refused_stamp_fails_the_deploy(self):
        d = self.wt("ada")
        self.write(d, PRE + "## next patch — x\n\n- 1\n\n## next patch — y\n\n- 2\n\n" + self.read(d)[len(PRE):])
        sh("git", "commit", "-qam", "two (patch)", cwd=d)
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout
        with self.assertRaisesRegex(RuntimeError, "could not be numbered: .*2 new entries in one commit"):
            self.deploy("ada")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout, before)
        self.assertEqual(self.main_top(), "0.5.2 — 2026-10-01")

    def test_the_checks(self):
        self.assertEqual(E.version_check(self.wt("ada"), "deb", "0.5.2"), "")  # nothing added
        d = self.wt("ada")
        self.write(d, log(("next patch — x", "n")) + "\n" + self.read(d)[len(PRE):])
        sh("git", "commit", "-qam", "left", cwd=d)
        self.assertIn("still has a placeholder", E.version_check(d, "deb", "0.5.2"))
        sh("git", "reset", "-q", "--hard", "deb", cwd=d)
        self.write(d, log(("0.5.3 — x", "n"), ("0.5.4 — x", "m")) + "\n" + self.read(d)[len(PRE):])
        sh("git", "commit", "-qam", "order", cwd=d)
        self.assertIn("do not fall: 0.5.3 above 0.5.4", E.version_check(d, "deb", "0.5.2"))
        sh("git", "reset", "-q", "--hard", "deb", cwd=d)
        self.write(d, log(("0.5.3 — x", "n")) + "\n" + self.read(d)[len(PRE):])
        sh("git", "commit", "-qam", "app", cwd=d)
        self.assertIn("APP_VERSION is 0.5.2, CHANGELOG.md's top 0.5.3", E.version_check(d, "deb", "0.5.2"))
        self.assertIn("not above 0.5.7", E.version_check(d, "deb", "0.5.7"))

    def test_the_stamp_run_by_hand_changes_nothing(self):
        # 4a9468f: `version-stamp.py --help`, to read its usage, numbered a
        # placeholder and amended the commit; by hand it is now a no-op
        self.entry("ada", "next patch — 2026-10-20", "ada's fix")
        d = self.wt("ada")
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout
        env = {k: v for k, v in os.environ.items() if k != "LCARS_VERSION_FLOOR"}
        p = sh("python3", STAMP, "--help", cwd=d, env=env)
        self.assertIn("The deploy's version stamp", p.stdout)
        self.assertEqual(sh("python3", STAMP, "--bogus", cwd=d, env=env, check=False).returncode, 2)
        p = sh("python3", STAMP, cwd=d, env=env, check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("deploy's rebase only", p.stderr)
        # the floor alone is not enough: no rebase in progress
        self.assertEqual(sh("python3", STAMP, cwd=d, env=dict(env, LCARS_VERSION_FLOOR="0.5.2"),
                            check=False).returncode, 2)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout, before)
        self.assertEqual(sh("git", "status", "--porcelain", cwd=d).stdout, "")
        self.assertEqual(VS.heads(self.read(d))[0], "next patch — 2026-10-20")
        # and the deploy still numbers it
        self.assertIn("deployed ada as 0.5.3: ", self.deploy("ada"))

    def test_app_version_set_by_hand_under_a_placeholder_is_refused(self):
        self.entry("ada", "next patch — 2026-10-20", "ada's fix", other="a.txt")
        self.entry("ada", "next patch — 2026-10-21", "ada's second", app="0.5.4", other="a.txt")
        d = self.wt("ada")
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout
        with self.assertRaisesRegex(RuntimeError, before[:7] + " sets APP_VERSION by hand under a placeholder"):
            self.deploy("ada")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout, before)
        self.assertEqual(self.main_top(), "0.5.2 — 2026-10-01")
        # put back in that commit (a later one undoing it would still
        # conflict at the replay), it lands; the old way is not refused
        self.write(d, app="0.5.2")
        sh("git", "commit", "-qa", "--amend", "--no-edit", cwd=d)
        self.entry("bob", "0.5.3 — 2026-10-20", "bob's fix", app="0.5.3", subject="Fix (0.5.3)")
        self.assertEqual(E.hand_set_versions(self.wt("bob"), "deb"), "")
        self.assertIn("deployed ada as 0.5.3, 0.5.4: ", self.deploy("ada"))
        self.assertEqual(self.app(), "0.5.4")

    # ---- fragments (changelog.d/), the placeholder's successor ----

    def frag(self, n, name, kind, text, subject=None, other=None, app=None, delete=False):
        """A commit on n's branch adding (or editing, or deleting) the
        fragment changelog.d/<name>.md; CHANGELOG.md untouched."""
        d = self.wt(n)
        os.makedirs(os.path.join(d, "changelog.d"), exist_ok=True)
        path = os.path.join(d, "changelog.d", name + ".md")
        if delete:
            os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(f"{kind}\n- {text}\n")
        if other:
            with open(os.path.join(d, other), "w") as f:
                f.write(text)
        self.write(d, app=app)
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", subject or f"{text} ({kind})", cwd=d)

    def frags_live(self):
        d = os.path.join(self.live, "changelog.d")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def section(self, v):
        text = self.read(self.live)
        a = text.index(f"## {v} — ")
        b = text.find("\n## ", a + 1)
        return text[a:b if b > 0 else len(text)].split("\n", 1)[1].strip()

    def test_a_fragment_alone(self):
        self.frag("ada", "ada-feature", "minor", "ada's feature", other="a.txt")
        msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.6.0: ", msg)
        self.assertEqual((self.main_top(), self.app()), ("0.6.0 — 2026-10-22", "0.6.0"))
        self.assertEqual(self.section("0.6.0"), "- ada's feature")
        self.assertEqual(self.frags_live(), [])   # deleted in the merge
        self.assertEqual(sh("git", "log", "--format=%s", "-1", cwd=self.live).stdout.strip(), "ada's feature (0.6.0)")
        # the entry below kept whole, the preamble too
        self.assertTrue(self.read(self.live).startswith(PRE + "## 0.6.0 — 2026-10-22\n\n- ada's feature\n\n## 0.5.2"))

    def test_two_fragments_from_one_main_land_in_order(self):
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        self.frag("bob", "bob-feature", "minor", "bob's feature", other="b.txt")
        self.frag("bob", "bob-polish", "patch", "bob's polish", subject="Polish it")
        self.assertIn("deployed ada as 0.5.3: ", self.deploy("ada"))
        # no rebase of bob's own: the fragments are files only bob has
        self.assertIn("deployed bob as 0.6.0, 0.6.1: ", self.deploy("bob"))
        self.assertEqual(VS.heads(self.read(self.live))[:3],
                         ["0.6.1 — 2026-10-22", "0.6.0 — 2026-10-22", "0.5.3 — 2026-10-22"])
        self.assertEqual((self.section("0.6.1"), self.section("0.6.0"), self.section("0.5.3")),
                         ("- bob's polish", "- bob's feature", "- ada's fix"))
        self.assertEqual((self.app(), self.frags_live()), ("0.6.1", []))
        subj = sh("git", "log", "--format=%s", "-3", cwd=self.live).stdout.split("\n")
        self.assertEqual(subj[:3], ["Polish it (0.6.1)", "bob's feature (0.6.0)", "ada's fix (0.5.3)"])

    def test_two_fragments_in_one_commit_numbered_in_turn(self):
        d = self.wt("ada")
        os.makedirs(os.path.join(d, "changelog.d"))
        for name, kind in (("ada-a", "patch"), ("ada-b", "minor")):
            with open(os.path.join(d, "changelog.d", name + ".md"), "w") as f:
                f.write(f"{kind}\n- {name}\n")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "Both (minor)", cwd=d)
        self.assertIn("deployed ada as 0.6.0: ", self.deploy("ada"))
        self.assertEqual(VS.heads(self.read(self.live))[:2], ["0.6.0 — 2026-10-22", "0.5.3 — 2026-10-22"])
        self.assertEqual((self.section("0.5.3"), self.section("0.6.0")), ("- ada-a", "- ada-b"))

    def test_a_fragment_plus_a_placeholder(self):
        # one branch in the transition: a fragment, then a placeholder
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        self.entry("ada", "next minor — 2026-10-21", "ada's feature", subject="Feature (minor)")
        # another: a placeholder, then a fragment
        self.entry("bob", "next patch — 2026-10-21", "bob's fix", other="b.txt")
        self.frag("bob", "bob-polish", "patch", "bob's polish")
        self.assertIn("deployed ada as 0.5.3, 0.6.0: ", self.deploy("ada"))
        sh("git", "rebase", "deb", cwd=self.wt("bob"))   # the placeholder through the driver
        self.assertIn("deployed bob as 0.6.1, 0.6.2: ", self.deploy("bob"))
        self.assertEqual(VS.heads(self.read(self.live))[:4],
                         ["0.6.2 — 2026-10-22", "0.6.1 — 2026-10-22", "0.6.0 — 2026-10-22", "0.5.3 — 2026-10-22"])
        self.assertEqual([self.section(v) for v in ("0.6.2", "0.6.1", "0.6.0", "0.5.3")],
                         ["- bob's polish", "- bob's fix", "- ada's feature", "- ada's fix"])
        self.assertNotIn("next ", self.read(self.live))
        self.assertEqual((self.app(), self.frags_live()), ("0.6.2", []))
        # and both in one commit: the placeholder numbered first, the fragment above
        self.frag("ada", "ada-x", "patch", "ada's x", other="c.txt")
        d = self.wt("ada")
        sh("git", "reset", "-q", "--soft", "HEAD^", cwd=d)
        sh("git", "rebase", "-q", "deb", cwd=d, check=False)
        self.write(d, log(("next patch — x", "ada's y"))[:len(PRE)] + "## next patch — x\n\n- ada's y\n\n"
                   + self.read(d)[len(PRE):])
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "Both kinds (patch)", cwd=d)
        self.assertIn("deployed ada as 0.6.4: ", self.deploy("ada"))
        self.assertEqual([self.section(v) for v in ("0.6.4", "0.6.3")], ["- ada's x", "- ada's y"])

    # ---- the release entries (docs/design/release-entries.md) ----

    def test_a_deploy_writes_its_release_entry(self):
        self.frag("ada", "ada-feature", "minor", "ada's feature", other="a.txt")
        with mock.patch.object(E.release_mod(), "utc_now", return_value="2026-10-22 09:30:00"):
            msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.6.0: ", msg)
        self.assertIn(" - release entries: 0.6.0 #1", msg)
        self.assertEqual(self.journal, [{"kind": "release", "title": "0.6.0",
                                         "content": "release:: 0.6.0 2026-10-22\n\n- ada's feature",
                                         "created_at_utc": "2026-10-22 09:30:00"}])
        # a deploy that numbers nothing writes nothing
        self.frag("ada", "ada-x", "patch", "x", delete=False)
        os.unlink(os.path.join(self.wt("ada"), "changelog.d", "ada-x.md"))
        sh("git", "commit", "-qam", "no entry after all", cwd=self.wt("ada"))
        self.assertNotIn("release entries", self.deploy("ada"))
        self.assertEqual(len(self.journal), 1)

    def test_a_deploy_of_two_versions_writes_two_oldest_first(self):
        # two fragments in one commit: its subject names only the last
        # version, the CHANGELOG both
        d = self.wt("ada")
        os.makedirs(os.path.join(d, "changelog.d"))
        for name, kind in (("ada-a", "patch"), ("ada-b", "minor")):
            with open(os.path.join(d, "changelog.d", name + ".md"), "w") as f:
                f.write(f"{kind}\n- {name}\n  more of {name}\n")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "Both (minor)", cwd=d)
        msg = self.deploy("ada")
        self.assertIn(" - release entries: 0.5.3 #1, 0.6.0 #2", msg)
        self.assertEqual([(e["title"], e["content"]) for e in self.journal],
                         [("0.5.3", "release:: 0.5.3 2026-10-22\n\n- ada-a\n  more of ada-a"),
                          ("0.6.0", "release:: 0.6.0 2026-10-22\n\n- ada-b\n  more of ada-b")])
        # the text is the section's exactly as CHANGELOG.md holds it
        self.assertEqual(self.journal[1]["content"].split("\n\n", 1)[1], self.section("0.6.0"))

    def test_a_failed_write_does_not_fail_the_deploy(self):
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        self.journal_down = True
        msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.5.3: ", msg)
        self.assertIn("release entries NOT written: 0.5.3 (the journal's release entries could not be read (0)", msg)
        self.assertIn("release-import.py --apply catches them up", msg)
        self.assertEqual((self.main_top(), self.journal), ("0.5.3 — 2026-10-22", []))
        # a POST refused: said too, the deploy landed all the same
        self.journal_down = False
        self.frag("bob", "bob-fix", "patch", "bob's fix", other="b.txt")
        with mock.patch.object(E.release_mod(), "post", side_effect=E.release_mod().Refused("403: no")):
            msg = self.deploy("bob")
        self.assertIn("deployed bob as 0.5.4: ", msg)
        self.assertIn("release entries NOT written: 0.5.4 (403: no)", msg)

    def test_an_unreadable_old_changelog_writes_nothing(self):
        # prev's CHANGELOG.md cannot be read: not taken as empty (every
        # version new), but the write refused, said, and the deploy landed
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        prev = sh("git", "rev-parse", "HEAD", cwd=self.live).stdout.strip()
        real = E.run

        def run(args, cwd=None, **kw):
            if args[:2] == ["git", "show"] and args[2] == f"{prev}:CHANGELOG.md":
                return real(["git", "show", "0" * 40 + ":CHANGELOG.md"], cwd=cwd, **kw)
            if args[:2] == ["git", "pull"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            return real(args, cwd=cwd, **kw)
        with mock.patch.object(E, "run", side_effect=run):
            msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.5.3: ", msg)
        self.assertIn("release entries NOT written (git show ", msg)
        self.assertIn("release-import.py --apply catches them up", msg)
        self.assertEqual((self.main_top(), self.journal), ("0.5.3 — 2026-10-22", []))

    # ---- the manual's report (docs/design/manual.md) ----

    MAN_REL = "media/reports/2026/10/manual-test.html"

    def manual_standins(self, n, report_rc=0):
        """site/manual/build.py and scripts/report.py stood in for in n's
        worktree (they land with its commit): the build writes its first
        argument into OUT, the update records its arguments and the file it
        was given, then answers report_rc."""
        d, rec = self.wt(n), os.path.join(self.root, "report.json")
        os.makedirs(os.path.join(d, "site", "manual"), exist_ok=True)
        with open(os.path.join(d, "site", "manual", "build.py"), "w") as f:
            f.write("import sys\nopen(sys.argv[2], 'w').write('built ' + sys.argv[1])\n")
        with open(os.path.join(d, "scripts", "report.py"), "w") as f:
            f.write(f"import json, sys\njson.dump([sys.argv[1:], open(sys.argv[3]).read()], open({rec!r}, 'w'))\n"
                    f"print('https://reports.test/' + sys.argv[2])\nsys.exit({report_rc})\n")
        return rec

    def test_a_manual_change_updates_its_report(self):
        rec = self.manual_standins("ada")
        with mock.patch.object(E, "MANUAL_REPORT", self.MAN_REL):
            msg = self.deploy_frag("ada", "ada-manual", "the manual's pages")
            self.assertIn("deployed ada as 0.5.3: ", msg)
            self.assertIn(" - manual report updated: https://reports.test/" + self.MAN_REL, msg)
            with open(rec) as f:
                argv, text = json.load(f)
            self.assertEqual((argv[:2], text), (["update", self.MAN_REL], "built --inline"))
            # a deploy that leaves the manual alone leaves its report alone
            os.unlink(rec)
            msg = self.deploy_frag("ada", "ada-other", "something else", other="a.txt")
            self.assertNotIn("manual report", msg)
            self.assertFalse(os.path.exists(rec))

    def test_a_failed_manual_report_does_not_fail_the_deploy(self):
        self.manual_standins("ada", report_rc=3)
        with mock.patch.object(E, "MANUAL_REPORT", self.MAN_REL):
            msg = self.deploy_frag("ada", "ada-manual", "the manual's pages")
        self.assertIn("deployed ada as 0.5.3: ", msg)
        self.assertIn(" - manual report NOT updated (", msg)
        self.assertEqual(self.main_top(), "0.5.3 — 2026-10-22")

    def deploy_frag(self, n, name, text, other=None):
        self.frag(n, name, "patch", text, other=other)
        return self.deploy(n)

    def test_a_failed_deploy_writes_nothing(self):
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        with mock.patch.object(E, "rebuild", return_value="make failed"), \
                mock.patch.object(E, "c_changed", return_value=True):
            with self.assertRaises(RuntimeError):
                self.deploy("ada")
        self.assertEqual(self.journal, [])

    def suite_fails(self, n, how="suite"):
        """A deploy of n that fails after its rebase numbered the branch: the
        web suite, or the rebuild after the merge."""
        boom = RuntimeError("the web suite failed in the worktree; nothing was deployed")
        p = [mock.patch.object(E, "web_suite", side_effect=boom)] if how == "suite" else \
            [mock.patch.object(E, "rebuild", return_value="make failed"), mock.patch.object(E, "c_changed", return_value=True)]
        with contextlib.ExitStack() as st:
            for x in p:
                st.enter_context(x)
            with self.assertRaises(RuntimeError) as cm:
                self.deploy(n)
        return str(cm.exception)

    def test_a_failed_suite_leaves_the_branch_as_it_was_and_a_retry_lands(self):
        # 25 Oct (deploy-20261025-143913.log): the suite failed, the branch
        # kept its numbered rebase, and the next deploy refused it as an
        # APP_VERSION set by hand under a fragment
        self.frag("bob", "bob-fix", "patch", "bob's fix", other="b.txt")
        self.deploy("bob")   # main moves: ada's rebase is a real one
        d = self.wt("ada")
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip()
        msg = self.suite_fails("ada")
        self.assertIn("the web suite failed", msg)
        self.assertIn(f"eng/ada is put back at {before[:8]}, as it was before the deploy", msg)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip(), before)
        self.assertEqual(sh("git", "status", "--porcelain", cwd=d).stdout, "")
        self.assertTrue(os.path.exists(os.path.join(d, "changelog.d", "ada-fix.md")))
        self.assertEqual(E.hand_set_versions(d, "deb"), "")
        self.assertEqual(self.main_top(), "0.5.3 — 2026-10-22")
        # the second deploy numbers it afresh and lands
        msg = self.deploy("ada")
        self.assertIn("deployed ada as 0.5.4: ", msg)
        self.assertEqual((self.main_top(), self.app()), ("0.5.4 — 2026-10-22", "0.5.4"))

    def test_a_failed_suite_puts_a_placeholder_branch_back_too(self):
        d = self.wt("ada")
        self.entry("ada", "next patch — 2026-10-20", "ada's fix", other="a.txt")
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip()
        self.suite_fails("ada")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip(), before)
        self.assertIn("## next patch — 2026-10-20", self.read(d))
        self.assertIn("deployed ada as 0.5.3: ", self.deploy("ada"))

    def test_a_failed_rebuild_leaves_the_branch_as_it_was(self):
        d = self.wt("ada")
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        before = sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip()
        live = sh("git", "rev-parse", "HEAD", cwd=self.live).stdout.strip()
        msg = self.suite_fails("ada", "rebuild")
        self.assertIn("the rebuild failed", msg)
        self.assertIn("put back at " + before[:8], msg)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip(), before)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.live).stdout.strip(), live)
        self.assertIn("deployed ada as 0.5.3: ", self.deploy("ada"))

    def test_a_failure_with_the_branch_unmoved_says_nothing_of_it(self):
        # a rebase that stops is aborted, which already puts the branch back
        d = self.wt("ada")
        self.write(d, PRE + "## next patch — x\n\n- 1\n\n## next patch — y\n\n- 2\n\n" + self.read(d)[len(PRE):])
        sh("git", "commit", "-qam", "two (patch)", cwd=d)
        with self.assertRaises(RuntimeError) as cm:
            self.deploy("ada")
        self.assertNotIn("put back", str(cm.exception))

    def test_a_review_fix_edits_the_fragment(self):
        self.frag("ada", "ada-fix", "patch", "ada's fix", other="a.txt")
        self.frag("ada", "ada-fix", "patch", "ada's fix, reworded", subject="Review fix")
        self.frag("ada", "ada-more", "patch", "ada's more")
        self.frag("ada", "ada-more", "patch", "gone", delete=True, subject="Not that after all")
        self.assertIn("deployed ada as 0.5.3", self.deploy("ada"))
        self.assertEqual(VS.heads(self.read(self.live))[:2], ["0.5.3 — 2026-10-22", "0.5.2 — 2026-10-01"])
        self.assertEqual(self.section("0.5.3"), "- ada's fix, reworded")
        self.assertEqual(self.frags_live(), [])
        # the review fix and the rest carry the branch's number, no more
        subj = sh("git", "log", "--format=%s", "-4", cwd=self.live).stdout.split("\n")
        self.assertEqual(subj[0], "Not that after all")
        self.assertEqual(subj[3], "ada's fix (0.5.3)")

    def test_a_bad_fragment_fails_the_deploy(self):
        for kind, why in (("major", "the first line is `minor` or `patch`"), ("patch\n", "no entry text")):
            d = self.wt("ada")
            sh("git", "reset", "-q", "--hard", "deb", cwd=d)
            os.makedirs(os.path.join(d, "changelog.d"), exist_ok=True)
            with open(os.path.join(d, "changelog.d", "ada-x.md"), "w") as f:
                f.write(kind if kind.endswith("\n") else kind + "\n- x\n")
            sh("git", "add", "-A", cwd=d)
            sh("git", "commit", "-qm", "x", cwd=d)
            before = sh("git", "rev-parse", "HEAD", cwd=d).stdout
            with self.assertRaisesRegex(RuntimeError, "could not be numbered: .*" + re.escape(why)):
                self.deploy("ada")
            self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=d).stdout, before)
            self.assertEqual(self.main_top(), "0.5.2 — 2026-10-01")

    def test_app_version_set_by_hand_with_a_fragment_is_refused(self):
        self.frag("ada", "ada-fix", "patch", "ada's fix", app="0.5.3")
        with self.assertRaisesRegex(RuntimeError, "sets APP_VERSION by hand under a placeholder or with a fragment"):
            self.deploy("ada")

    def test_a_fragment_left_fails_the_check(self):
        d = self.wt("ada")
        os.makedirs(os.path.join(d, "changelog.d"))
        with open(os.path.join(d, "changelog.d", "x.md"), "w") as f:
            f.write("patch\n- x\n")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "x", cwd=d)
        self.assertIn("a changelog fragment is left in the tree (changelog.d/x.md)", E.version_check(d, "deb", "0.5.2"))
        # the README is not one
        sh("git", "rm", "-q", "changelog.d/x.md", cwd=d)
        os.makedirs(os.path.join(d, "changelog.d"), exist_ok=True)
        with open(os.path.join(d, "changelog.d", "README.md"), "w") as f:
            f.write("the format\n")
        sh("git", "add", "-A", cwd=d)
        sh("git", "commit", "-qm", "readme", cwd=d)
        self.assertEqual(E.version_check(d, "deb", "0.5.2"), "")

    def test_todo_items_at_one_place_both_land(self):
        # .gitattributes' TODO.md merge=union, through the deploy's rebase
        for n in ("ada", "bob"):
            d = self.wt(n)
            with open(os.path.join(d, "TODO.md"), "w") as f:
                f.write(f"# TODO\n\n- [ ] one\n\n- [ ] {n}'s item\n\n- [ ] two\n")
            self.frag(n, f"{n}-fix", "patch", f"{n}'s fix")
        self.deploy("ada")
        self.assertIn("deployed bob as 0.5.4: ", self.deploy("bob"))
        todo = self.read(self.live, "TODO.md")
        self.assertIn("- [ ] ada's item", todo)
        self.assertIn("- [ ] bob's item", todo)
        self.assertEqual(todo.count("- [ ] two"), 1)
        self.assertNotIn("<<<<<<<", todo)

    def test_the_driver_is_configured_once(self):
        E.changelog_driver()
        E.changelog_driver()
        cfg = sh("git", "config", "--get-all", "merge.lcars-changelog.driver", cwd=self.live).stdout.splitlines()
        self.assertEqual(len(cfg), 1)
        self.assertIn("changelog-merge.py %O %A %B", cfg[0])


if __name__ == "__main__":
    unittest.main()
