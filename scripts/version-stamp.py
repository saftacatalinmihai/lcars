#!/usr/bin/env python3
"""The deploy's version stamp (docs/design/version-at-deploy.md): run by
`git rebase -x` after each commit of an engineer's branch is replayed onto
the live branch, under the deploy's lock, so that the deploy - the only
writer of main at that moment - gives each commit's CHANGELOG entry its
number. Never two branches with the same one.

    LCARS_VERSION_FLOOR=0.298.6 git rebase -x "python3 scripts/version-stamp.py" main

What the commit (HEAD) added at the top of CHANGELOG.md, against HEAD^:

- nothing: only its subject's mark is mended - the branch's current top
  when that is one of its own (above the floor), else none;
- `## next patch — <date>` or `## next minor — <date>`: numbered
  bump(max(floor, the numbered heading below it), kind), dated today;
- `## X.Y.Z — <date>` (the old way, an engineer's own pick): kept when it
  is above both, else renumbered as a minor if it ends .0, else a patch.

And what the commit did under changelog.d/ (the fragments, which replace
the placeholder: an engineer writes `changelog.d/<name>-<slug>.md`, its
first line `minor` or `patch`, the rest the entry's text, and never edits
CHANGELOG.md, so two branches never touch one file):

- a fragment added: a section `## X.Y.Z — <today>` with its text, put on
  top of CHANGELOG.md, numbered bump(max(floor, the top number), kind);
  several in one commit (a placeholder too, numbered first) in turn, by
  name. The fragment stays in the tree until the rebase is done, so that a
  later commit of the branch that edits it (a review fix) still applies:
- a fragment edited, that an earlier commit of this rebase numbered: its
  section's text replaced, its number kept (the rebase's own record,
  lcars-fragments.json in git's rebase-merge directory);
- a fragment deleted: its section taken out.

`finish(cwd)`, the deploy's step after the rebase, deletes every fragment
the branch added and amends its last commit: what lands has none left.

Then `APP_VERSION` in lcars-ui/index.html is set to the number, the
subject's `(patch)`, `(minor)` or `(X.Y.Z)` replaced by `(N)` (or `(N)`
appended), and the commit amended. Refused, exit 1 (the rebase stops, the
deploy aborts it and says why): two entries in one commit, a placeholder
of another kind, one below a numbered entry, a heading changed above
HEAD^'s top. The floor is the deploy's: the live branch's top and every
version ever deployed, a rolled-back one included (a phone may hold its
page, and would never be offered another page under the same number).

It runs only inside a rebase with LCARS_VERSION_FLOOR set, the deploy's:
run by hand (`--help` included: it used to take no arguments, and an
engineer reading its usage had their placeholder numbered and their commit
amended) it changes nothing and says so. `hand_set(rev)` is the deploy's
check before the rebase: a commit that adds a placeholder and moves
`APP_VERSION` too.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

CHANGELOG = "CHANGELOG.md"
PAGE = "lcars-ui/index.html"
HEAD_RE = re.compile(r"^## (.*)$", re.M)
NUM_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?=\s|$)")
PLACE_RE = re.compile(r"^next\s+(\w+)\b")
KINDS = ("patch", "minor")
APP_RE = re.compile(r'^const APP_VERSION = "[^"]*";$', re.M)
SUBJ_RE = re.compile(r"\s*\((?:patch|minor|\d+\.\d+\.\d+)\)\s*$")
FRAG_DIR = "changelog.d"
# a fragment's path: lowercase, so changelog.d/README.md (the format's note)
# is never one
FRAG_RE = re.compile(r"^changelog\.d/[a-z0-9][a-z0-9._-]*\.md$")
FRAG_STATE = "lcars-fragments.json"


class Refused(Exception):
    pass


def ver(s):
    """(x, y, z) of a heading's text or a version string, or None."""
    m = NUM_RE.match(s.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def vstr(v):
    return "%d.%d.%d" % v


def bump(v, kind):
    return (v[0], v[1], v[2] + 1) if kind == "patch" else (v[0], v[1] + 1, 0)


def heads(text):
    """The `## ` headings of a CHANGELOG, top first: their text."""
    return HEAD_RE.findall(text or "")


def added(new, old):
    """The headings `new` has above all of `old`'s (all of them if old has
    none), matched from the bottom: two entries may carry the same heading
    (two branches that picked one number the old way). Refused when `old`'s
    headings are not `new`'s last ones: the commit changed or moved one."""
    hn, ho = heads(new), heads(old)
    k = len(hn) - len(ho)
    if k < 0 or hn[k:] != ho:
        raise Refused(f"{CHANGELOG}: an entry below the top was added, changed or moved; add yours on top only")
    return hn[:k]


def today():
    """The captain's day (LCARS_TZ), the CHANGELOG's dates being his.
    LCARS_STAMP_TODAY (YYYY-MM-DD) fixes it: the tests' clock, which must
    reach this process through the deploy's rebase (a mock in the test's
    own process does not), so their expected dates hold on any day."""
    fixed = os.environ.get("LCARS_STAMP_TODAY", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fixed):
        return fixed
    tz = os.environ.get("LCARS_TZ")
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz)).date().isoformat() if tz else dt.date.today().isoformat()
    except Exception:  # noqa: BLE001 - an unknown zone: the box's day
        return dt.date.today().isoformat()


def plan(new, old, floor):
    """What to do with this commit's CHANGELOG: None (nothing added, or an
    old-style number already good) or (the heading line as it is, the
    number to give it). Raises Refused."""
    new_heads = added(new, old)
    for h in heads(new)[len(new_heads):]:
        if PLACE_RE.match(h):
            raise Refused(f"{CHANGELOG}: a placeholder below a numbered entry (## {h}); placeholders go on top")
    if not new_heads:
        return None
    if len(new_heads) > 1:
        raise Refused(f"{CHANGELOG}: {len(new_heads)} new entries in one commit ({', '.join(new_heads)}); one each")
    h = new_heads[0]
    below = next((ver(x) for x in heads(new)[1:] if ver(x)), (0, 0, 0))
    base = max(floor, below)
    m = PLACE_RE.match(h)
    if m:
        if m.group(1) not in KINDS:
            raise Refused(f"{CHANGELOG}: `## {h}`: the kind is patch or minor (a major is the captain's, by hand)")
        return h, bump(base, m.group(1))
    v = ver(h)
    if not v:
        raise Refused(f"{CHANGELOG}: `## {h}` is neither a version nor `next patch`/`next minor`")
    if v > base:
        return h, v
    return h, bump(base, "minor" if v[2] == 0 else "patch")


def apply(new_text, page_text, subject, h, v):
    """(CHANGELOG, index.html, subject) with heading `h` numbered `v`."""
    rest = h.split("—", 1)[1].strip() if "—" in h else ""
    date = rest if (ver(h) and vstr(ver(h)) == vstr(v)) else today()
    line = f"## {vstr(v)} — {date}"
    # the heading's own line, never a mention of the format in the preamble;
    # the first, which is the commit's own when two carry the same text
    m = re.search(r"^## " + re.escape(h) + r"$", new_text, re.M)
    new_text = new_text[:m.start()] + line + new_text[m.end():]
    if page_text is not None:
        page_text = APP_RE.sub(f'const APP_VERSION = "{vstr(v)}";', page_text, count=1)
    subject = SUBJ_RE.sub("", subject).rstrip() + f" ({vstr(v)})"
    return new_text, page_text, subject


def fragment(text, path):
    """(kind, entry text) of a fragment; Refused when it is not one."""
    first, _, rest = (text or "").partition("\n")
    kind = first.strip()
    if kind not in KINDS:
        raise Refused(f"{path}: the first line is `minor` or `patch`, not {first.strip()[:40]!r}")
    body = rest.strip("\n")
    if not body.strip():
        raise Refused(f"{path}: no entry text after its first line")
    return kind, body


def top_number(text):
    return next((ver(h) for h in heads(text) if ver(h)), (0, 0, 0))


def put_on_top(text, v, body):
    """text with a section `## v — today` holding body above its first entry."""
    sec = f"## {vstr(v)} — {today()}\n\n{body}\n\n"
    m = re.search(r"^## ", text, re.M)
    if not m:
        return text.rstrip("\n") + "\n\n" + sec.rstrip("\n") + "\n"
    return text[:m.start()] + sec + text[m.start():]


def section(text, v):
    """(start, end) of the section numbered v, or None."""
    m = re.search(r"^## " + re.escape(vstr(v)) + r"(?=\s|$).*$", text, re.M)
    if not m:
        return None
    n = re.search(r"^## ", text[m.end():], re.M)
    return m.start(), (m.end() + n.start() if n else len(text))


def replace_section(text, v, body):
    """The section numbered v with body as its text (None: taken out)."""
    span = section(text, v)
    if not span:
        raise Refused(f"{CHANGELOG}: no section {vstr(v)} for its fragment")
    a, b = span
    if body is None:
        return text[:a] + text[b:]
    line = text[a:b].split("\n", 1)[0]
    tail = "\n\n" if b < len(text) else "\n"
    return text[:a] + line + "\n\n" + body + tail + text[b:]


def fragments_changed(rev="HEAD"):
    """[(status, path)] of the fragments rev changed against its parent:
    A, M or D, by path (no renames: a rename is a delete and an add)."""
    out = git("diff", "--no-renames", "--name-status", rev + "^", rev, "--", FRAG_DIR + "/")
    rows = []
    for ln in out.splitlines():
        st, _, path = ln.partition("\t")
        if FRAG_RE.match(path):
            rows.append((st[:1], path))
    return sorted(rows, key=lambda r: r[1])


def state_path():
    return git("rev-parse", "--git-path", "rebase-merge/" + FRAG_STATE).strip()


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st):
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(st, f)


def assemble(text, floor, changed, state, show_file):
    """(text, [numbers given]) with this commit's fragment changes put into
    the CHANGELOG text; state ({path: version}) updated. Raises Refused."""
    given = []
    for st, path in changed:
        if st == "A":
            kind, body = fragment(show_file(path), path)
            v = bump(max(floor, top_number(text)), kind)
            text = put_on_top(text, v, body)
            state[path] = vstr(v)
            given.append(v)
        elif st == "M":
            if path not in state:
                raise Refused(f"{path}: edited, but no commit of this branch added it")
            _, body = fragment(show_file(path), path)
            text = replace_section(text, ver(state[path]), body)
        elif st == "D":
            if path in state:
                text = replace_section(text, ver(state.pop(path)), None)
    return text, given


def finish(cwd=None, base=None):
    """The deploy's step after its rebase: every fragment in HEAD's tree that
    base (the live branch) does not have is deleted, and the last commit
    amended - the stamp left them for later commits to edit. Answers the
    paths deleted."""
    run = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, cwd=cwd)
    have = lambda rev: {p for p in run("ls-tree", "-r", "--name-only", rev, "--", FRAG_DIR + "/").stdout.split()
                        if FRAG_RE.match(p)}
    gone = sorted(have("HEAD") - (have(base) if base else set()))
    if not gone:
        return []
    for cmd in (["rm", "-q", "--", *gone],
                ["-c", "core.hooksPath=/dev/null", "commit", "--amend", "--no-verify", "--quiet", "--no-edit"]):
        p = run(*cmd)
        if p.returncode != 0:
            raise Refused(f"git {cmd[0]}: {p.stderr.strip()[-300:]}")
    return gone


def remark(subject, top, floor):
    """A commit that added no entry: its subject's mark - `(patch)`, or an
    old-way number that may be stale or another branch's - would go into the
    deploy's history as a version; it carries the branch's current top
    instead (the entry an earlier commit of the branch added: a review fix
    is part of that version), or none when the branch has added none yet
    (the top is then at or under the floor, the live branch's)."""
    if not SUBJ_RE.search(subject):
        return subject
    subject = SUBJ_RE.sub("", subject).rstrip()
    return subject + f" ({vstr(top)})" if top and top > floor else subject


def amend(subject, body):
    # the message whole, its body and trailers as they were, the subject numbered
    git("-c", "core.hooksPath=/dev/null", "commit", "--amend", "--no-verify", "--quiet", "-m",
        subject + ("\n" + body.rstrip("\n") if body.strip() else ""))


def unmarked(subject, body, text, floor, sha):
    top = next((ver(x) for x in heads(text) if ver(x)), None)
    s2 = remark(subject, top, floor)
    if s2 != subject:
        amend(s2, body)
        print(f"version-stamp: {sha} adds no entry; its subject now " + (f"({vstr(top)})" if top and top > floor else "unmarked"), flush=True)
    return 0


def git(*a, check=True):
    p = subprocess.run(["git", *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Refused(f"git {' '.join(a)}: {p.stderr.strip()[-300:]}")
    return p.stdout


def show(rev, path, cwd=None):
    p = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, cwd=cwd)
    return p.stdout if p.returncode == 0 else None


def app_version(page_text):
    m = APP_RE.search(page_text or "")
    return m.group(0) if m else None


def hand_set(rev, cwd=None):
    """Why commit `rev` is refused before the deploy's rebase, or "": it adds
    a placeholder and moves APP_VERSION by hand. Run before the rebase, so
    the engineer hears that, not an index.html conflict with another
    branch's hand-set number. An old-way commit (a number of its own, and
    APP_VERSION set to it) is not refused: the stamp renumbers it."""
    new, old = show(rev, CHANGELOG, cwd), show(rev + "^", CHANGELOG, cwd)
    if new is None:
        return ""
    try:
        hs = added(new, old or "")
    except Refused:
        return ""  # the stamp refuses it, saying why
    frag = any(FRAG_RE.match(p) for p in subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "--diff-filter=A", rev + "^", rev, "--", FRAG_DIR + "/"],
        capture_output=True, text=True, cwd=cwd).stdout.split())
    if not frag and not any(PLACE_RE.match(h) for h in hs):
        return ""
    if app_version(show(rev, PAGE, cwd)) == app_version(show(rev + "^", PAGE, cwd)):
        return ""
    return "sets APP_VERSION by hand under a placeholder or with a fragment: leave it, the deploy numbers it"


def rebasing():
    """A rebase in progress in this checkout: the deploy's `git rebase -x`."""
    p = subprocess.run(["git", "rev-parse", "--git-path", "rebase-merge"], capture_output=True, text=True)
    return p.returncode == 0 and os.path.isdir(p.stdout.strip())


def main():
    if sys.argv[1:]:
        print(__doc__.strip())
        return 0 if sys.argv[1] in ("-h", "--help") else 2
    if not os.environ.get("LCARS_VERSION_FLOOR") or not rebasing():
        # never by hand: it amends HEAD; a placeholder is the deploy's to number
        print("version-stamp: run by the deploy's rebase only (LCARS_VERSION_FLOOR, a rebase in progress); "
              "nothing changed", file=sys.stderr)
        return 2
    floor = ver(os.environ["LCARS_VERSION_FLOOR"]) or (0, 0, 0)
    new, old = show("HEAD", CHANGELOG), show("HEAD^", CHANGELOG)
    sha = git("rev-parse", "--short", "HEAD").strip()
    try:
        changed = fragments_changed()
        if new is None:
            if not changed:
                return 0
            new = old = ""   # no CHANGELOG yet: the fragment's entry starts one
        p = plan(new, old or "", floor)
        state = load_state()
        text, given = new, []
        if p is not None:   # the placeholder (or an old-way number) first
            h, v = p
            text, _, _ = apply(text, None, "", h, v)
            given.append(v)
        text, more = assemble(text, floor, changed, state, lambda path: show("HEAD", path))
        given += more
    except Refused as e:
        raise Refused(f"{sha}: {e}")
    if changed:
        save_state(state)
    msg = git("log", "-1", "--format=%B", "HEAD")
    subject, _, body = msg.partition("\n")
    page = show("HEAD", PAGE)
    if not given:
        if text != new:   # a fragment's section edited or taken out
            with open(CHANGELOG, "w", encoding="utf-8") as f:
                f.write(text)
            files = [CHANGELOG]
            # one taken out may have been the top: APP_VERSION follows it down
            page2 = APP_RE.sub(f'const APP_VERSION = "{vstr(top_number(text))}";', page, count=1) if page else page
            if page2 != page:
                with open(PAGE, "w", encoding="utf-8") as f:
                    f.write(page2)
                files.append(PAGE)
            git("add", "--", *files)
            amend(subject, body)
            print(f"version-stamp: {sha} edits its fragment's entry", flush=True)
        return unmarked(subject, body, text, floor, sha)
    v = max(given)
    page2 = APP_RE.sub(f'const APP_VERSION = "{vstr(v)}";', page, count=1) if page is not None else None
    subject2 = SUBJ_RE.sub("", subject).rstrip() + f" ({vstr(v)})"
    if text == new and page2 == page and subject2 == subject:
        print(f"version-stamp: {sha} is {vstr(v)}", flush=True)
        return 0
    files = []
    if text != new:
        with open(CHANGELOG, "w", encoding="utf-8") as f:
            f.write(text)
        files.append(CHANGELOG)
    if page2 is not None and page2 != page:
        with open(PAGE, "w", encoding="utf-8") as f:
            f.write(page2)
        files.append(PAGE)
    if files:
        git("add", "--", *files)
    amend(subject2, body)
    print(f"version-stamp: {sha} numbered " + ", ".join(vstr(x) for x in given)
          + (f" (was {p[0].split()[0]})" if p and ver(p[0]) else ""), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as e:
        print(f"version-stamp: REFUSED: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
