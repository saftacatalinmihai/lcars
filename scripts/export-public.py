#!/usr/bin/env python3
"""The public release: a snapshot of this repo's tree, made for the public
repo (docs/design/open-source.md, section 5).

    scripts/export-public.py DEST [--repo OWNER/NAME] [--version X.Y.Z]
    scripts/export-public.py --audit-only

DEST is a clone of the public repo (or any git repo of its own). The
export refuses a dirty tree here, copies `git ls-files` minus EXCLUDE,
applies SUBST, writes the public CHANGELOG.md (this release's entry on top
of DEST's own) and TODO.md (DEST's, else a fresh one), audits every file
it wrote against the pattern file, builds and runs the public tree's own
tests in DEST, and commits there as "Release X.Y.Z". Pushing is not its
job: that is a separate, deliberate `git push` in DEST.

--audit-only (or --dry-run) copies, builds and commits nothing: it reads
the files that would ship (substituted, as they would be written) and
prints the hits grouped by pattern, the way to see what the code still
carries. It reads the working tree as it is, dirty or not.

The patterns live in scripts/export-audit.local.txt (--patterns), which
the export leaves out: it *is* the private names. Without it the export
refuses, since an audit of nothing would pass anything.
"""

import argparse
import datetime
import fnmatch
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

# What never ships (the design's 1g), one place. A rule ending in "/" is a
# directory and everything under it; any other is an fnmatch glob over the
# repo-relative path, whose "*" crosses "/". Any file whose name holds
# ".local." is out too (CLAUDE.local.md, crew/context.local.md, the
# pattern file): a box's own, by the name, so a new one needs no line here.
EXCLUDE = [
    # the live box's deploy and its journal swaps, and their test
    "scripts/vps-rebuild.sh", "scripts/db-push.sh", "scripts/db-pull.sh",
    "scripts/db-swap.sh", "scripts/db-slots.sh", "scripts/db-filter.sh",
    "lcars-ui/test/db_swap.py", "scripts/test_vps_rebuild.py",
    # the owner's Grafana Cloud stack
    "scripts/metrics/", "scripts/metrics-setup.sh",
    # the signed shortcuts carry the live address; generate.py builds them
    "shortcuts/*.shortcut", "shortcuts/lcars-shortcuts.zip",
    # real journal content, QA run on the live data
    "reports/", "lcars-ui/report/", "docs/qa/",
    # the release's own design, which surveys the private names it removes
    "docs/design/open-source.md",
    # the explainer film's production: built on the captain's own media
    # store (the music, the narration), his shots and his trip; the film
    # itself is what is shown
    "video/", "docs/design/explainer-video.md",
    # replaced by the public ones (write_changelog, write_todo)
    "CHANGELOG.md", "TODO.md",
]
LOCAL_MARK = ".local."

# The export's rewrites: (path, regex, replacement), "{repo}" the public
# repo's OWNER/NAME. Kept small and generic on purpose: the code is made
# public here (the design's "gen"), so the two trees do not drift, and no
# rule may spell a private name, since this file ships.
SUBST = [
    # the CI badge, and its link, point at the public repo's workflow
    ("README.md", r"github\.com/[\w.-]+/[\w.-]+/actions/workflows/", "github.com/{repo}/actions/workflows/"),
]
PUBLIC_REPO = "saftacatalinmihai/lcars"

PATTERNS = HERE / "export-audit.local.txt"

# untracked, ignored binaries the web suite runs (see run_tests)
TEST_TOOLS = ["lcars-ui/test/esbuild", "lcars-ui/test/qjs"]

FRESH_TODO = """# TODO

The backlog: features, bugs and refactoring ideas worth tracking. Remove
an item in the commit that finishes it (CHANGELOG.md records it).

## The release

- **arm64 decides CI too.** static.yml and release.yml let an arm64
  failure pass (`continue-on-error`) because the private clone's arm64
  runners are metered or absent; once the public repo's arm64 runs have
  proven steady, let them fail the run there.

## Setup

- **Imports from other notes apps.** Logseq's is built (`lcars-cli
  logseq`); Obsidian, a folder of markdown or another app's export is an
  order to the engineers away.
"""

CHANGELOG_HEAD = """# Changelog

The version at the top of this file is **the** version of LCARS. The web UI
shows it under the LCARS badge (`APP_VERSION` in `lcars-ui/index.html`), so a
page showing an older number is running a cached copy. A feature bumps the
minor, a fix the patch, in the same commit as `APP_VERSION`.

"""

# The first release's line, when DEST has no CHANGELOG yet and no --notes
FIRST_NOTES = ("The first public release: one static Linux binary - the server, "
               "the CLI, and the web console and the 3D deck inside it - as "
               "tarballs for x86_64 and arm64 with SHA256SUMS on the Releases "
               "page (README.md, \"Run it\"), with the crew's and the "
               "engineers' scripts beside it.")


# ------------------------------------------------------------- the tree
def git(src, *args, check=True):
    return subprocess.run(["git", "-C", str(src), *args], check=check, capture_output=True, text=True).stdout


def excluded(path):
    if LOCAL_MARK in path.rsplit("/", 1)[-1]:
        return True
    for rule in EXCLUDE:
        if rule.endswith("/") and path.startswith(rule):
            return True
        if not rule.endswith("/") and fnmatch.fnmatchcase(path, rule):
            return True
    return False


def shipped(src):
    """The repo-relative paths that ship: tracked, not excluded, present
    (a tracked file deleted in the worktree is the audit's dirty tree)."""
    files = git(src, "ls-files", "-z").split("\0")
    return [p for p in files if p and not excluded(p) and (src / p).is_file()]


def links(src, files):
    """{path: target} of the tracked symlinks that ship (scripts/omarchy/ to
    the plugin's omarchy/bin/), kept links in DEST: the public tree's tests
    check them as links (test_webapp.py runs the installer through one). A
    link must stay inside the tree, to a file that ships too: one out of it,
    or to an excluded file, would dangle in the public repo or name a path
    of this box's."""
    out = {}
    for line in git(src, "ls-files", "-s", "-z").split("\0"):
        if not line.startswith("120000 "):
            continue
        path = line.split("\t", 1)[1]
        if path not in files:
            continue
        target = os.readlink(src / path)
        to = os.path.normpath(os.path.join(os.path.dirname(path), target))
        if os.path.isabs(target) or to not in files:
            sys.exit(f"export: {path} links to {target}, which does not ship: point it inside the tree")
        out[path] = target
    return out


def substitute(path, data, repo):
    for where, rx, repl in SUBST:
        if where != path:
            continue
        s = data.decode("utf-8")
        s, n = re.subn(rx, repl.replace("{repo}", repo), s)
        if not n:
            # a rule that matches nothing is a page that changed under it
            sys.exit(f"export: {path} has nothing for the rule {rx!r}: the file changed under the export")
        data = s.encode("utf-8")
    return data


def numbered(src):
    """Refuse a tree whose CHANGELOG has a placeholder (`## next patch`): a
    belt to the deploy's check, main being always numbered
    (docs/design/version-at-deploy.md)."""
    log = src / "CHANGELOG.md"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    m = re.search(r"^## (next\s.*)$", text, re.M)
    if m:
        sys.exit(f"export: CHANGELOG.md has a placeholder (## {m.group(1)}): export main, which the deploy numbers")
    # a fragment (changelog.d/, the placeholder's successor) is unnumbered too
    frags = sorted(p.name for p in (src / "changelog.d").glob("*.md")
                   if re.fullmatch(r"[a-z0-9][a-z0-9._-]*\.md", p.name))
    if frags:
        sys.exit(f"export: changelog.d/{frags[0]} is a fragment the deploy has not numbered: export main")


def app_version(src):
    m = re.search(r'const APP_VERSION = "(\d+\.\d+\.\d+)"', (src / "lcars-ui/index.html").read_text(encoding="utf-8"))
    if not m:
        sys.exit("export: no APP_VERSION in lcars-ui/index.html")
    return m.group(1)


def write_changelog(old, version, notes, today):
    """DEST's own CHANGELOG with this release's entry on top (run.sh checks
    the top version against APP_VERSION), or a new one."""
    notes = notes or (f"A snapshot of LCARS at {version}." if old else FIRST_NOTES)
    entry = f"## {version} — {today}\n\n- {notes}\n\n"
    if old and f"## {version} " in old:
        sys.exit(f"export: DEST's CHANGELOG.md already has {version}: bump the version here first")
    if not old:
        return CHANGELOG_HEAD + entry
    m = re.search(r"^## \d", old, re.M)
    return old[:m.start()] + entry + old[m.start():] if m else old.rstrip("\n") + "\n\n" + entry


def tree(src, repo, version, notes, dest=None, today=None):
    """{path: bytes}, every file the public tree gets, as it is written."""
    out = {}
    for p in shipped(src):
        out[p] = substitute(p, (src / p).read_bytes(), repo)
    today = today or datetime.date.today().isoformat()
    old = lambda name: (dest / name).read_text(encoding="utf-8") if dest and (dest / name).is_file() else ""
    out["CHANGELOG.md"] = write_changelog(old("CHANGELOG.md"), version, notes, today).encode("utf-8")
    out["TODO.md"] = (old("TODO.md") or FRESH_TODO).encode("utf-8")
    return out


# ------------------------------------------------------------- the audit
def load_patterns(path):
    """[(name, compiled regex, [globs])] from the pattern file."""
    rules = []
    for n, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [x.strip() for x in line.split(" :: ")]
        if len(parts) not in (2, 3) or not all(parts):
            sys.exit(f"export: {path}:{n}: not 'name :: regex [:: globs]'")
        try:
            rx = re.compile(parts[1])
        except re.error as e:
            sys.exit(f"export: {path}:{n}: {e}")
        rules.append((parts[0], rx, parts[2].split(",") if len(parts) == 3 else []))
    if not rules:
        sys.exit(f"export: {path} has no patterns")
    return rules


def applies(globs, path):
    """Whether a rule with these globs reads path: none means every file;
    a "!glob" leaves its files out (a short acronym's rule out of the
    compressed textures, whose random bytes spell one now and then), and
    the plain ones, if any, are the only files it reads."""
    keep = [g for g in globs if not g.startswith("!")]
    if any(fnmatch.fnmatchcase(path, g[1:]) for g in globs if g.startswith("!")):
        return False
    return not keep or any(fnmatch.fnmatchcase(path, g) for g in keep)


def audit(files, rules):
    """[(name, path, line, text)] for every line of every file that a rule
    matches. Binary files are read too (a path baked into a glb still
    ships), as latin-1 so no byte is skipped."""
    hits = []
    for path in sorted(files):
        data = files[path]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        mine = [(name, rx) for name, rx, globs in rules if applies(globs, path)]
        for i, line in enumerate(text.splitlines(), 1):
            for name, rx in mine:
                if rx.search(line):
                    hits.append((name, path, i, line.strip()[:160]))
    return hits


def report_grouped(hits, rules):
    by = {}
    for name, path, i, text in hits:
        by.setdefault(name, []).append((path, i, text))
    for name, _rx, _g in rules:
        found = by.get(name, [])
        files = sorted({p for p, _i, _t in found})
        print(f"== {name}: {len(found)} lines in {len(files)} files")
        for p in files:
            lines = [i for q, i, _t in found if q == p]
            print(f"   {p}: {len(lines)} ({', '.join(map(str, lines[:12]))}{', ...' if len(lines) > 12 else ''})")


# ------------------------------------------------------------- the export
def write(dest, files, linked=None):
    """DEST becomes the snapshot: everything but .git cleared, then written
    (a link in `linked` as the link, its bytes having been audited as the
    file it points to)."""
    for child in dest.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    for path, data in files.items():
        p = dest / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if linked and path in linked:
            p.symlink_to(linked[path])
        else:
            p.write_bytes(data)


def modes(src, dest, files):
    """The executable bits git tracks, copied, so the scripts still run."""
    for line in git(src, "ls-files", "-s", "-z").split("\0"):
        if line.startswith("100755 "):
            path = line.split("\t", 1)[1]
            if path in files:
                os.chmod(dest / path, 0o755)


def run_tests(src, dest):
    """The public tree's own: make check, the web suite on a synthetic
    journal (no lcars.db in a fresh tree: run.sh makes one), the script
    tests. Each stage's output goes to the terminal; a failure stops."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("LCARS_TEST_DB")}
    env.setdefault("PERF", "0")  # perf compares with main's page, which DEST has not
    # the suite's two binaries are ignored, a box's own (no fresh clone has
    # them yet): lent from this checkout for the run, then taken back
    lent = []
    for tool in TEST_TOOLS:
        mine, theirs = src / tool, dest / tool
        if mine.exists() and not theirs.exists():
            theirs.symlink_to(mine.resolve())
            lent.append(theirs)
    stages = [["make", "check"], ["lcars-ui/test/run.sh"]]
    stages += [["python3", str(p.relative_to(dest))] for p in sorted((dest / "scripts").glob("test_*.py"))]
    try:
        for cmd in stages:
            print(f"== {' '.join(cmd)}", flush=True)
            if subprocess.run(cmd, cwd=dest, env=env).returncode:
                sys.exit(f"export: {' '.join(cmd)} failed in {dest}: nothing committed")
    finally:
        for p in lent:
            p.unlink()


def identity(src, dest):
    """`-c` options naming who commits in DEST: none when DEST's git has a
    user.name and user.email of its own (its config, the global one), else
    the source repo's. A fresh clone on a box that sets the identity per
    repo has none, and git would refuse the Release commit after the whole
    test run; the release is this repo's commit, so its author is too."""
    opts = []
    for key in ("user.name", "user.email"):
        if git(dest, "config", key, check=False).strip():
            continue
        mine = git(src, "config", key, check=False).strip()
        if not mine:
            sys.exit(f"export: no {key} in {dest} or {src}: set one (git config {key} ...)")
        opts += ["-c", f"{key}={mine}"]
    return opts


def commit(src, dest, version):
    git(dest, "add", "-A")
    if not git(dest, "status", "--porcelain").strip():
        print(f"export: {dest} already holds this tree, nothing to commit")
        return
    git(dest, *identity(src, dest), "commit", "-q", "-m", f"Release {version}")
    print(f"export: committed Release {version} in {dest}; push it with git -C {dest} push")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dest", nargs="?", type=pathlib.Path, help="a clone of the public repo")
    ap.add_argument("--audit-only", "--dry-run", action="store_true", help="no copy, build or commit: the hits, grouped")
    ap.add_argument("--repo", default=PUBLIC_REPO, help=f"the public repo, OWNER/NAME (default {PUBLIC_REPO})")
    ap.add_argument("--version", help="the release (default APP_VERSION)")
    ap.add_argument("--notes", help="the CHANGELOG entry's line (default: the first release's, else a snapshot's)")
    ap.add_argument("--patterns", type=pathlib.Path, default=PATTERNS)
    ap.add_argument("--src", type=pathlib.Path, default=HERE.parent, help="the repo exported (default this one)")
    ap.add_argument("--no-tests", action="store_true", help="skip the build and tests in DEST")
    a = ap.parse_args(argv)

    src = a.src.resolve()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        sys.exit(f"export: --repo {a.repo!r} is not OWNER/NAME")
    if not a.patterns.is_file():
        sys.exit(f"export: no pattern file {a.patterns}: an audit of nothing passes anything")
    rules = load_patterns(a.patterns)
    version = a.version or app_version(src)
    notes = a.notes  # None: write_changelog's default, by whether DEST has one

    if a.audit_only:
        files = tree(src, a.repo, version, notes)
        hits = audit(files, rules)
        print(f"export: {len(files)} files would ship, {len(hits)} lines hit")
        report_grouped(hits, rules)
        return 1 if hits else 0

    if a.dest is None:
        ap.error("DEST is needed (or --audit-only, which a branch's placeholder does not stop)")
    numbered(src)
    if git(src, "status", "--porcelain").strip():
        sys.exit("export: the tree is dirty: commit or set aside the changes first (the release is a commit's)")
    dest = a.dest.resolve()
    if not (dest / ".git").exists():
        sys.exit(f"export: {dest} is not a git repo: clone the public repo there first")
    if dest == src or src in dest.parents:
        sys.exit("export: DEST is inside this repo")
    if git(dest, "status", "--porcelain").strip():
        sys.exit(f"export: {dest} has uncommitted changes")

    files = tree(src, a.repo, version, notes, dest)
    hits = audit(files, rules)
    if hits:
        for name, path, i, text in hits:
            print(f"{path}:{i}: {name}: {text}")
        sys.exit(f"export: {len(hits)} lines hit the audit: nothing written")
    linked = links(src, files)
    write(dest, files, linked)
    modes(src, dest, files)
    print(f"export: {len(files)} files written to {dest}, the audit clean")
    if not a.no_tests:
        run_tests(src, dest)
    commit(src, dest, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
