#!/usr/bin/env python3
"""run.sh's version check (docs/design/version-at-deploy.md, "What reads
the version"): CHANGELOG.md is the version's home and the page carries a
copy (`APP_VERSION`) to show it. Two shapes pass:

- numbered: the top entry `## X.Y.Z — <date>` and `APP_VERSION` equal to
  it (main, always: the deploy numbers every entry before it lands);
- fragments: one or more `changelog.d/<name>-<slug>.md` (first line
  `minor` or `patch`, then the entry's text), CHANGELOG.md's top numbered
  and `APP_VERSION` equal to it - the deploy makes each a numbered section
  on top (scripts/version-stamp.py) and deletes it;
- placeholders (retired, still numbered in the transition): one or more
  `## next patch|minor — <date>` on top, and `APP_VERSION` left at the
  first number below them - the deploy gives each its number and moves
  `APP_VERSION`. A placeholder and fragments together pass too.

Fails: a placeholder below a numbered entry, a kind other than patch or
minor (a placeholder's or a fragment's first line), a fragment with no
text or a name not lowercase `[a-z0-9._-]`, `APP_VERSION` moved under a
placeholder or beside a fragment, and - read from git when
there is a base (`--base`, default main; none in a fresh clone or on main
itself: skipped) - a commit of the branch, or the worktree's change, that
adds two entries at once (the stamp numbers one per commit).

    python3 lcars-ui/test/version.py [--base REF]     (from anywhere)

Prints `ok (X.Y.Z)` or `ok (X.Y.Z + next patch, numbered at deploy)`;
exit 1 with `FAIL: ...` otherwise.
"""

import argparse
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parents[2]
HEAD_RE = re.compile(r"^## (.*)$", re.M)
NUM_RE = re.compile(r"^(\d+\.\d+\.\d+)(?=\s|$)")
PLACE_RE = re.compile(r"^next\s+(\w+)\b")
KINDS = ("patch", "minor")
APP_RE = re.compile(r'^const APP_VERSION = "([^"]*)";$', re.M)


def heads(text):
    return HEAD_RE.findall(text or "")


def added(new, old):
    """How many headings `new` put above `old`'s, matched from the bottom
    (as the stamp does); None when old's are not new's last ones."""
    hn, ho = heads(new), heads(old)
    k = len(hn) - len(ho)
    return k if k >= 0 and hn[k:] == ho else None


FRAG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")


def fragments(root=ROOT):
    """{name: text} of changelog.d/'s fragments (README.md, the format's
    note, is not one), and [why] for a file there that is neither."""
    d = root / "changelog.d"
    frags, bad = {}, []
    for f in sorted(d.iterdir()) if d.is_dir() else []:
        if f.name == "README.md":
            continue
        if not f.is_file() or not FRAG_NAME_RE.match(f.name):
            bad.append(f"changelog.d/{f.name}: a fragment is changelog.d/<name>-<slug>.md, lowercase")
            continue
        frags[f.name] = f.read_text(encoding="utf-8")
    return frags, bad


def check(changelog, page, commits=(), frags=None):
    """("ok", text) or ("FAIL", why). `commits`: (label, new, old) for each
    commit of the branch (and the worktree), oldest first. `frags`: {name:
    text} of changelog.d's fragments."""
    frags = frags or {}
    for name, text in sorted(frags.items()):
        first, _, rest = text.partition("\n")
        if first.strip() not in KINDS:
            return "FAIL", f"changelog.d/{name}: the first line is `minor` or `patch`, not {first.strip()[:40]!r}"
        if not rest.strip():
            return "FAIL", f"changelog.d/{name}: no entry text after its first line"
    hs = heads(changelog)
    app = (APP_RE.search(page or "") or [None, None])[1]
    places = []
    for h in hs:
        if not PLACE_RE.match(h):
            break
        places.append(h)
    for h in places:
        if PLACE_RE.match(h).group(1) not in KINDS:
            return "FAIL", f"CHANGELOG.md: `## {h}`: the kind is patch or minor (a major is the captain's, by hand)"
    rest = hs[len(places):]
    below = next((h for h in rest if PLACE_RE.match(h)), None)
    if below:
        return "FAIL", f"CHANGELOG.md: a placeholder below a numbered entry (## {below}): placeholders go on top"
    if rest and not NUM_RE.match(rest[0]):
        return "FAIL", f"CHANGELOG.md: `## {rest[0]}` is neither a version nor `next patch`/`next minor`"
    num = NUM_RE.match(rest[0]).group(1) if rest else None
    for label, new, old in commits:
        k = added(new, old)
        if k is not None and k > 1:
            return "FAIL", f"{label} adds {k} CHANGELOG entries: one each (the deploy numbers one per commit)"
    if not places and not frags:
        if not num or num != app:
            return "FAIL", f"CHANGELOG.md says {num or 'nothing'}, index.html APP_VERSION says {app or 'nothing'}"
        return "ok", num
    if app != num:
        return "FAIL", (f"index.html APP_VERSION is {app or 'nothing'} under a placeholder or beside a fragment: "
                        f"leave it at {num or '?'}, CHANGELOG.md's top number - the deploy numbers both")
    kinds = ", ".join([" ".join(h.split()[:2]) for h in places]
                      + [f"fragment {t.split(chr(10), 1)[0].strip()}" for _, t in sorted(frags.items())])
    return "ok", f"{num} + {kinds}, numbered at deploy"


def git(*a):
    p = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def branch_commits(base):
    """(label, new, old) for each commit since base, and the worktree's
    change against HEAD; () with no git or no base."""
    if git("rev-parse", "--verify", "-q", base + "^{commit}") is None:
        return []
    mb = (git("merge-base", "HEAD", base) or "").strip()
    revs = (git("rev-list", "--reverse", f"{mb}..HEAD") or "").split() if mb else []
    show = lambda rev: git("show", f"{rev}:CHANGELOG.md") or ""
    out = [(f"commit {r[:7]}", show(r), show(r + "^")) for r in revs]
    work = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    out.append(("the worktree's change", work, show("HEAD")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="main")
    a = ap.parse_args(argv)
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    page = (ROOT / "lcars-ui/index.html").read_text(encoding="utf-8")
    frags, bad = fragments()
    if bad:
        print(f"   FAIL: {bad[0]}")
        return 1
    verdict, text = check(log, page, branch_commits(a.base), frags)
    print(f"   {verdict}" + (f" ({text})" if verdict == "ok" else f": {text}"))
    return 0 if verdict == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
