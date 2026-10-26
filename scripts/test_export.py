#!/usr/bin/env python3
"""Unit tests for scripts/export-public.py, the public release's export, on
a small fixture repo in a temp directory (a made-up pattern file, never
the real one: this test ships): the exclusions, the badge's substitution,
the public CHANGELOG and TODO, an audit hit named with its file and line,
a narrowed rule, a link kept as a link (and one out of the tree
refused), a clean tree exported and committed, a dirty tree and a
DEST that is no repo refused, and --audit-only's groups.

    python3 scripts/test_export.py
"""

import contextlib
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("export_public", HERE / "export-public.py")
X = importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)

FILES = {
    "README.md": "# lcars\n\n[![CI](https://github.com/someone/lcars/actions/workflows/c-cpp.yml/badge.svg)]"
                 "(https://github.com/someone/lcars/actions/workflows/c-cpp.yml)\n",
    "lcars-ui/index.html": '<script>\nconst APP_VERSION = "1.2.3";\n</script>\n',
    "lcars.c": "int main(void) { return 0; }\n",
    "crew/yeoman.md": "Tidy the journal. The owner keeps a log.\n",
    "scripts/tool.py": "#!/usr/bin/env python3\nprint('he said')\n",
    "scripts/db-push.sh": "scp lcars.db box:\n",
    "scripts/metrics/config.alloy": "stack\n",
    "shortcuts/generate.py": "print('build')\n",
    "shortcuts/Log.shortcut": "signed\n",
    "docs/qa/2026-10-13.md": "a run\n",
    "reports/review.html": "<p>real</p>\n",
    "CLAUDE.local.md": "the box's rules\n",
    "crew/context.local.md": "the owner's life\n",
    "scripts/export-audit.local.txt": "zorblax\n",
    "CHANGELOG.md": "# Changelog\n\n## 1.2.3 — 2026-10-19\n\n- the private history\n",
    "TODO.md": "# TODO\n\n- the private backlog\n",
}

PATTERNS = """# made-up names
the fixture's name :: (?i)zorblax
a key :: sk-ant-[A-Za-z0-9_-]{8}
the owner as he :: \\b[Hh]e\\b :: crew/*.md
a short term :: \\bQRX\\b :: !*.bin
"""


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def run(*argv):
    """(exit code or message, stdout) of main(argv)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rc = X.main(list(argv))
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue()


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="export-test-"))
        self.src = self.tmp / "src"
        for path, text in FILES.items():
            p = self.src / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        os.chmod(self.src / "scripts/tool.py", 0o755)
        self.git_init(self.src)
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-qm", "fixture")
        self.pat = self.tmp / "patterns.txt"
        self.pat.write_text(PATTERNS, encoding="utf-8")
        self.dest = self.tmp / "public"
        self.dest.mkdir()
        self.git_init(self.dest)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git_init(self, d):
        sh(d, "git", "init", "-q")
        sh(d, "git", "config", "user.email", "test@example.com")
        sh(d, "git", "config", "user.name", "Test")

    def commit_src(self, path, text):
        (self.src / path).write_text(text, encoding="utf-8")
        sh(self.src, "git", "commit", "-qam", "change")

    def export(self, *extra):
        return run(str(self.dest), "--src", str(self.src), "--patterns", str(self.pat), "--no-tests", *extra)

    def test_exclusions(self):
        rc, out = self.export()
        self.assertEqual(rc, 0, out)
        shipped = sorted(sh(self.dest, "git", "ls-files").split())
        self.assertEqual(shipped, ["CHANGELOG.md", "README.md", "TODO.md", "crew/yeoman.md", "lcars-ui/index.html",
                                   "lcars.c", "scripts/tool.py", "shortcuts/generate.py"])
        for path in ("scripts/db-push.sh", "CLAUDE.local.md", "crew/context.local.md", "scripts/export-audit.local.txt",
                     "docs/qa/2026-10-13.md", "docs/design/open-source.md", "reports/review.html", "shortcuts/Log.shortcut", "scripts/metrics/config.alloy"):
            self.assertTrue(X.excluded(path), path)
        self.assertFalse(X.excluded("scripts/metrics.py"), "a directory rule is not a prefix of a name")
        self.assertTrue(os.access(self.dest / "scripts/tool.py", os.X_OK), "the executable bit copied")

    def test_a_link_kept_as_a_link(self):
        # scripts/omarchy/'s links to the plugin's omarchy/bin/: the public
        # tree's own tests run the installer through one
        (self.src / "scripts/omarchy").mkdir()
        os.symlink("../tool.py", self.src / "scripts/omarchy/tool")
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-qm", "link")
        rc, out = self.export()
        self.assertEqual(rc, 0, out)
        link = self.dest / "scripts/omarchy/tool"
        self.assertTrue(link.is_symlink(), "a link, not a copy")
        self.assertEqual(os.readlink(link), "../tool.py")
        self.assertIn("120000", sh(self.dest, "git", "ls-files", "-s", "scripts/omarchy/tool"))
        self.assertTrue(os.access(link, os.X_OK), "its target executable")

    def test_a_link_out_of_the_tree_refused(self):
        os.symlink("../CLAUDE.local.md", self.src / "scripts/rules.md")
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-qm", "link")
        rc, out = self.export()
        self.assertIn("scripts/rules.md links to ../CLAUDE.local.md, which does not ship", str(rc))
        self.assertEqual(sh(self.dest, "git", "status", "--porcelain"), "", "nothing written")

    def test_substitution_and_public_files(self):
        rc, out = self.export("--repo", "starfleet/lcars-public")
        self.assertEqual(rc, 0, out)
        readme = (self.dest / "README.md").read_text()
        self.assertEqual(readme.count("github.com/starfleet/lcars-public/actions/workflows/"), 2)
        self.assertNotIn("someone", readme)
        log = (self.dest / "CHANGELOG.md").read_text()
        self.assertRegex(log, r"\n## 1\.2\.3 — \d{4}-\d\d-\d\d\n\n- The first public release: ")
        self.assertIn("## The release", (self.dest / "TODO.md").read_text(), "the fresh TODO's items")
        todo = (self.dest / "TODO.md").read_text()
        for done in ("one-file download", "Say what is off", "Kinds as roles"):
            self.assertNotIn(done, todo, "an item done before the first release")
        self.assertIn("tarballs for x86_64 and arm64 with SHA256SUMS", log, "the first release's line: the download")
        self.assertNotIn("from source", log)
        self.assertNotIn("private history", log)
        self.assertNotIn("private backlog", (self.dest / "TODO.md").read_text())
        self.assertEqual(sh(self.dest, "git", "log", "--format=%s"), "Release 1.2.3\n")

    def test_dest_without_an_identity_commits_as_the_source(self):
        # a fresh clone on a box with no global identity: only the source
        # repo's own config names one (the global and system files hidden)
        sh(self.dest, "git", "config", "--unset", "user.name")
        sh(self.dest, "git", "config", "--unset", "user.email")
        sh(self.src, "git", "config", "user.name", "Source Owner")
        sh(self.src, "git", "config", "user.email", "owner@example.com")
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        with unittest.mock.patch.dict(os.environ, env):
            rc, out = self.export()
        self.assertEqual(rc, 0, out)
        self.assertEqual(sh(self.dest, "git", "log", "--format=%s|%an|%ae"), "Release 1.2.3|Source Owner|owner@example.com\n")
        self.assertEqual(sh(self.dest, "git", "config", "--local", "--list").count("user."), 0, "DEST's config left as it was")

    def test_default_repo_and_a_bad_one(self):
        rc, _ = self.export()
        self.assertEqual(rc, 0)
        self.assertIn("github.com/saftacatalinmihai/lcars/actions", (self.dest / "README.md").read_text())
        rc, _ = self.export("--repo", "no slash")
        self.assertIn("not OWNER/NAME", rc)

    def test_next_release_keeps_the_public_history(self):
        self.assertEqual(self.export()[0], 0)
        (self.dest / "TODO.md").write_text("# TODO\n\n- a public item\n")
        sh(self.dest, "git", "commit", "-qam", "public todo")
        self.commit_src("lcars-ui/index.html", '<script>\nconst APP_VERSION = "1.3.0";\n</script>\n')
        rc, out = self.export("--notes", "The deck's voice.")
        self.assertEqual(rc, 0, out)
        log = (self.dest / "CHANGELOG.md").read_text()
        self.assertLess(log.index("## 1.3.0"), log.index("## 1.2.3"), "the new entry on top")
        self.assertIn("- The deck's voice.", log)
        self.assertIn("a public item", (self.dest / "TODO.md").read_text())
        self.assertEqual(log.count("The first public release"), 1, "said once, of the first")
        self.commit_src("lcars-ui/index.html", '<script>\nconst APP_VERSION = "1.3.1";\n</script>\n')
        self.assertEqual(self.export()[0], 0)
        self.assertIn("- A snapshot of LCARS at 1.3.1.", (self.dest / "CHANGELOG.md").read_text(), "a later one's default line")
        rc, _ = self.export("--version", "1.3.0")
        self.assertIn("already has 1.3.0", rc, "a version released once is refused")

    def test_audit_hit_named_with_file_and_line(self):
        self.commit_src("lcars.c", "int main(void) {\n  /* Zorblax's box */\n  return 0;\n}\n")
        rc, out = self.export()
        self.assertIn("1 lines hit the audit", rc)
        self.assertIn("lcars.c:2: the fixture's name: /* Zorblax's box */", out)
        self.assertEqual(sh(self.dest, "git", "ls-files"), "", "nothing written on a hit")
        self.assertEqual(list(p.name for p in self.dest.iterdir()), [".git"])

    def test_a_narrowed_rule(self):
        # "he" in scripts/tool.py is outside the rule's glob (the clean
        # exports above pass with it); in crew/ it hits
        self.commit_src("crew/yeoman.md", "Tidy the journal. He keeps a log.\n")
        rc, out = self.export()
        self.assertIn("1 lines hit", rc)
        self.assertIn("crew/yeoman.md:1: the owner as he:", out)

    def test_a_rule_left_out_of_some_files(self):
        # "!*.bin" keeps the short term's rule out of a binary, whose bytes
        # may spell it by chance; anywhere else it hits
        (self.src / "lcars-ui" / "tex.bin").write_bytes(b"\x00QRX\x01\n")
        (self.src / "lcars-ui" / "notes.txt").write_text("the QRX list\n", encoding="utf-8")
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-qm", "short term")
        rc, out = self.export()
        self.assertIn("1 lines hit", rc)
        self.assertIn("lcars-ui/notes.txt:1: a short term:", out)
        self.assertNotIn("tex.bin", out)

    def test_a_fragment_refused(self):
        # changelog.d/'s fragments are unnumbered too; its README is not one
        (self.src / "changelog.d").mkdir()
        (self.src / "changelog.d" / "README.md").write_text("the format\n")
        (self.src / "changelog.d" / "ada-x.md").write_text("patch\n- mine\n")
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-qm", "fragment")
        rc, _ = self.export()
        self.assertIn("changelog.d/ada-x.md is a fragment the deploy has not numbered", str(rc))
        self.assertEqual(list(self.dest.iterdir()), [self.dest / ".git"])

    def test_a_placeholder_refused(self):
        # main is always numbered: a branch's `## next patch` never ships
        self.commit_src("CHANGELOG.md", "# Changelog\n\n## next patch — 2026-10-22\n\n- mine\n\n"
                                        "## 1.2.3 — 2026-10-19\n\n- the private history\n")
        rc, _ = self.export()
        self.assertIn("CHANGELOG.md has a placeholder (## next patch — 2026-10-22)", str(rc))
        self.assertEqual(list(self.dest.iterdir()), [self.dest / ".git"])
        # the audit alone runs on a branch
        rc, out = run("--src", str(self.src), "--patterns", str(self.pat), "--audit-only")
        self.assertIn("files would ship", out)

    def test_dirty_tree_refused(self):
        (self.src / "lcars.c").write_text("int main(void) { return 1; }\n")
        rc, _ = self.export()
        self.assertIn("the tree is dirty", rc)
        (self.src / "lcars.c").write_text(FILES["lcars.c"])
        (self.src / "new.txt").write_text("untracked\n")
        rc, _ = self.export()
        self.assertIn("the tree is dirty", rc, "an untracked file is dirt too")

    def test_dest_refusals(self):
        rc, _ = run(str(self.tmp / "nowhere"), "--src", str(self.src), "--patterns", str(self.pat), "--no-tests")
        self.assertIn("not a git repo", rc)
        (self.dest / "stray").write_text("x")
        rc, _ = self.export()
        self.assertIn("uncommitted changes", rc)
        rc, _ = run(str(self.dest), "--src", str(self.src), "--patterns", str(self.tmp / "none.txt"), "--no-tests")
        self.assertIn("no pattern file", rc)

    def test_audit_only_groups_and_writes_nothing(self):
        self.commit_src("lcars.c", "/* zorblax */\nint main(void) { return 0; } /* zorblax */\n")
        (self.src / "crew/yeoman.md").write_text("He keeps a log.\n")  # dirty: audit-only reads it anyway
        rc, out = run("--audit-only", "--src", str(self.src), "--patterns", str(self.pat))
        self.assertEqual(rc, 1)
        self.assertIn("== the fixture's name: 2 lines in 1 files\n   lcars.c: 2 (1, 2)\n", out)
        self.assertIn("== a key: 0 lines in 0 files\n", out)
        self.assertIn("== the owner as he: 1 lines in 1 files\n   crew/yeoman.md: 1 (1)\n", out)
        self.assertEqual(list(p.name for p in self.dest.iterdir()), [".git"])

    def test_a_clean_tree_audits_clean(self):
        rc, out = run("--dry-run", "--src", str(self.src), "--patterns", str(self.pat))
        self.assertEqual(rc, 0, out)
        self.assertIn("8 files would ship, 0 lines hit", out)

    def test_bad_pattern_line(self):
        self.pat.write_text("just a name\n")
        rc, _ = run("--audit-only", "--src", str(self.src), "--patterns", str(self.pat))
        self.assertIn("not 'name :: regex", rc)


if __name__ == "__main__":
    unittest.main()
