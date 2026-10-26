#!/usr/bin/env python3
"""git's merge driver for CHANGELOG.md (docs/design/version-at-deploy.md):
entries only stacked on top on both sides merge by themselves, so that two
branches that each added an entry rebase onto each other without a
conflict - the deploy's stamp (version-stamp.py) then numbers them.

    .gitattributes:  CHANGELOG.md merge=lcars-changelog
    git config merge.lcars-changelog.driver "python3 <repo>/scripts/changelog-merge.py %O %A %B"

The deploy sets the config line (the worktrees share it, so an engineer's
own `git rebase main` gets it too); a clone without it falls back to git's
own merge, harmlessly. O is the base, A ours (in a rebase: the branch being
built, main's side), B theirs (the commit being replayed). The result,
written to A: the preamble, B's new entries, then A's entries whole. A
may hold anything above the base's (main's new entries, and in a rebase
the branch's earlier commits, numbered by then, above them); B may only
have put entries on top of the base's, their headings in the base's
order. An old entry or the preamble changed on one side only is that
side's; an old entry A gave only a new heading (the stamp's number, in
the replay of the branch's earlier commit) and B edited below it keeps
A's heading over B's text. Anything else - an old entry edited differently on both sides, a
heading B put below an old one - exits 1 with git's own conflict
markers in A.
"""

import subprocess
import sys

sys.dont_write_bytecode = True


class Conflict(Exception):
    pass


def split(text):
    """(preamble, [entry]) - an entry from its `## ` line to the next."""
    lines = text.splitlines(keepends=True)
    pre, entries = [], []
    for ln in lines:
        if ln.startswith("## "):
            entries.append([ln])
        elif entries:
            entries[-1].append(ln)
        else:
            pre.append(ln)
    return "".join(pre), ["".join(e) for e in entries]


def head(entry):
    return entry.split("\n", 1)[0]


def body(entry):
    return entry.split("\n", 1)[1] if "\n" in entry else ""


def renamed(x, out, eo):
    """The entry of `out` that is old entry `x` under another heading - the
    stamp's number given in the replay of an earlier commit of the branch,
    a placeholder or an old-way number renumbered - or None: one entry
    only, not itself an old one, its text below the heading unchanged."""
    hits = [e for e in out if e not in eo and head(e) != head(x) and body(e) == body(x)]
    return hits[0] if len(hits) == 1 else None


def pick(o, a, b, what):
    if a == b or b == o:
        return a
    if a == o:
        return b
    raise Conflict(f"{what} changed on both sides")


def sep(e):
    """An entry ends in a blank line before the next one."""
    return e if e.endswith("\n\n") else e.rstrip("\n") + "\n\n"


def merge(o, a, b):
    """B (the commit replayed) may only have put entries on top of O; they go
    on top of A, which is taken whole - main's entries, and in a rebase the
    branch's earlier commits, already numbered, wherever they sit. An old
    entry B edited is carried into A if A still has it as O had it."""
    (po, eo), (pa, ea), (pb, eb) = split(o), split(a), split(b)
    ho = [head(e) for e in eo]
    # matched from the bottom: a new entry may carry an old one's heading
    hb = [head(e) for e in eb]
    k = len(hb) - len(ho)
    if k < 0 or hb[k:] != ho:
        raise Conflict("theirs added, removed or moved an entry below the top")
    nb, ob = eb[:k], eb[k:]
    pre = pick(po, pa, pb, "the preamble")
    out = list(ea)
    for x, z in zip(eo, ob):
        if z == x:
            continue
        if x not in out:
            if z in out:
                continue
            # a later commit's edit of the branch's own entry (a review fix),
            # which the replay of the earlier one has numbered: the heading
            # and the text are separate changes, A's heading over B's text
            y = renamed(x, out, eo)
            if y is not None and head(z) == head(x):
                out[out.index(y)] = head(y) + "\n" + body(z)
                continue
            raise Conflict(f"the entry {head(x)!r} changed on both sides")
        out[out.index(x)] = z
    # the same entry on both sides (a commit already on main): once
    nb = [e for e in nb if e not in out]
    res = [sep(e) for e in nb] + out
    if res and not out:
        res[-1] = res[-1].rstrip("\n") + "\n"
    return pre + "".join(res)


def main(o, a, b):
    read = lambda p: open(p, encoding="utf-8").read()
    try:
        out = merge(read(o), read(a), read(b))
    except Conflict as e:
        print(f"changelog-merge: {e}; left to resolve by hand", file=sys.stderr)
        # git's own markers in A, as with no driver
        subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", a, o, b])
        return 1
    with open(a, "w", encoding="utf-8") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
