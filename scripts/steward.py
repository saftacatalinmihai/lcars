#!/usr/bin/env python3
"""Data fixes to the captain's journal, one change per call, with the
steward login (the captain's order, 2026-10-27, through Number One).

    steward.py get ID [--json]            the row as the server has it: read before a write
    steward.py title ID TEXT...           its title
    steward.py set ID field=value...      title, kind, start, end, done, value_int,
                                          value_float, created_at (dates in the captain's
                                          time, YYYY-MM-DD HH:MM; an empty start or end clears it)
    steward.py replace ID --file F | -    its whole text, from a file or stdin
    steward.py append ID TEXT... | --file F | -
                                          a quoted block at its end, headed with who added it
    steward.py delete ID
    steward.py restore ID
    steward.py new kind=K [title=T] [start=..] [end=..] [TEXT... | --file F | -]
                                          a new entry of the captain's, opened by a quote
                                          naming who made it; its id printed

Every change, a `new` entry too, is made by crew_notes.py's
apply_change, the code the crew notes' CHANGES lines go through: a fresh read just before (its
last_modified_at_utc is the write's if_modified, so a row that moved in
between is refused with the server's 412, never overwritten), the
captain's kinds only, nothing written into a row changed under QUIET
seconds ago (he may be typing in it), no @role line put into his text.
The server's steward gate (lcars_logins.h, StewardAllowed and
StewardMayWriteKind) is the only gate that counts; this one refuses
earlier, with a plainer reason.

Each change made is recorded as a crew_fix entry, written with the crew
login (the crew's own kind: the steward cannot touch it): who made it,
the op, the entry, the old value and the new, and the JSON record the
crew notes keep for an Undo. Who is the engineer whose worktree the call
is made from (~/lcars-eng/<name>), or $LCARS_STEWARD_WHO (no1.py sets
it); a call from neither is refused, so no fix is anonymous.

The logins are read from ~/.env in this process (crew_tool.read_env), as
no1.py and crew_notes.py read them, and never printed: an engineer's
tools may not read that file (engineer.py's secret_reads), and need not.

Exit status: 0 done, 1 refused or failed (nothing written), 2 a usage
error, 3 the change was made but its record could not be written (the
record is printed, to be kept by hand).
"""

import json
import os
import shlex
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crew_notes as N  # noqa: E402 - apply_change, its parser and its listing
import crew_tool as T  # noqa: E402 - the journal's HTTP and ~/.env

RECORD_KIND = "crew_fix"
OPS = ("get", "title", "set", "replace", "append", "delete", "restore", "new")
NEW_KEYS = ("kind", "title", "start", "end")   # CREATE_KEYS but text, which is the rest
ROOT = os.environ.get("LCARS_ENG_ROOT") or os.path.join(os.path.expanduser("~"), "lcars-eng")


class Refused(Exception):
    pass


def who_am_i(cwd=None):
    """$LCARS_STEWARD_WHO, else the engineer whose worktree holds cwd."""
    w = (os.environ.get("LCARS_STEWARD_WHO") or "").strip()
    if w:
        return w
    rel = os.path.relpath(os.path.realpath(cwd or os.getcwd()), os.path.realpath(ROOT))
    name = rel.split(os.sep)[0]
    if rel.startswith("..") or name in ("", "."):
        raise Refused(f"run it from your worktree under {ROOT} (or no1.py steward): every fix names who made it")
    return name


def logins_ready():
    """Both logins are in ~/.env (their names said, never their values):
    the steward's makes the change, the crew's writes its record, and a
    change without its record is not made."""
    env = T.read_env()
    missing = [k for k in (*N.STEWARD_LOGIN, *T.CREW_LOGIN) if not env.get(k)]
    if missing:
        raise Refused(f"no {', '.join(missing)} in {T.ENV_FILE}")


def read_text(args, what):
    """The text after the id: --file F, - (stdin), or the words given."""
    if args[:1] == ["--file"]:
        if len(args) != 2:
            raise Refused(f"{what} --file F")
        with open(args[1], encoding="utf-8") as f:
            return f.read()
    if args == ["-"]:
        return sys.stdin.read()
    if what == "replace":
        raise Refused("replace takes the whole new text from --file F or - (stdin)")
    return " ".join(args)


def entry_id(s):
    if not s or not s.lstrip("#").isdigit():
        raise Refused("the entry's id, a number")
    return int(s.lstrip("#"))


def change_of(op, rid, args, at):
    """The change as apply_change takes it, through crew_notes' own parser
    (its limits and its refusals) wherever the op has one there."""
    if op == "replace":
        text = read_text(args, op)
        if not text.strip():
            raise Refused("replace needs the entry's whole new text, not an empty one")
        # parse_change's replace reads \n as a new line (a CHANGES line is
        # one line); a file's text is taken as it is
        return {"op": "replace", "id": rid, "text": text, "at": at}
    words = [op, f"#{rid}"]
    if op == "title":
        words.append("text=" + " ".join(args))
    elif op == "append":
        words.append("text=" + read_text(args, op))
    elif op == "set":
        if not args:
            raise Refused(f"set ID field=value...: {', '.join(N.SET_KEYS)}")
        words += args
    elif args:
        raise Refused(f"{op} takes the id alone")
    try:
        return N.parse_change(shlex.join(words + [f"at={at}"]))
    except ValueError as e:
        raise Refused(str(e))


def new_change(args):
    """`new`'s create change: its leading key=value words (NEW_KEYS), then
    the text, through parse_change - a kind's shape, a title or text, the
    dates, no @role line - and a kind of the captain's, said here before
    the server's gate refuses it."""
    words = ["create"]
    while args and args[0].split("=", 1)[0] in NEW_KEYS and "=" in args[0]:
        words.append(args.pop(0))
    text = read_text(args, "new") if args else ""
    if text.strip():
        words.append("text=" + text)
    try:
        c = N.parse_change(shlex.join(words))
    except ValueError as e:
        raise Refused(str(e))
    if not N.eligible({"kind": c["kind"]}):
        raise Refused(f"{c['kind']} is not a kind of the captain's: the steward never writes into it")
    return c


def summary(rec):
    """One line on what changed, as the crew notes list it."""
    op, i = rec["op"], rec["id"]
    if op == "create":
        return f"created #{i} ({rec['kind']}) {N.title_shown(rec['title'])}"
    if op == "title":
        return f"titled #{i}: {N.title_shown(rec['old_title'])} → {N.title_shown(rec['title'])}"
    if op == "set":
        return f"set #{i}: {N.set_listed(rec)}"
    if op == "replace":
        return f"edited the text of #{i}: {N.replace_listed(rec)}"
    if op in ("delete", "restore"):
        return f"{op}d #{i} ({rec['kind']}) {N.title_shown(rec['title'])}"
    first = rec["text"].strip().split("\n")[1:2]
    return f"added to #{i}: {first[0].lstrip('> ') if first else ''}"


def fenced(text, lang=""):
    """text in a fence longer than any backtick run in it."""
    run, n = 0, 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        n = max(n, run)
    f = "`" * max(3, n + 1)
    return f"{f}{lang}\n{text.rstrip(chr(10))}\n{f}"


def old_new(rec):
    """The old value and the new, in full, for the captain to read."""
    op = rec["op"]
    if op == "create":
        return "", f"kind: {rec['kind']}\ntitle: {rec['title']}\n\n{rec.get('text') or ''}"
    if op == "title":
        return rec["old_title"] or "", rec["title"]
    if op == "set":
        return json.dumps(rec["old"], ensure_ascii=False), json.dumps(rec["new"], ensure_ascii=False)
    if op == "replace":
        return rec["old_text"], rec["text"]
    if op == "append":
        return "", rec["text"].strip("\n")
    return ("deleted: 0", "deleted: 1") if op == "delete" else ("deleted: 1", "deleted: 0")


def record(who, rec, row):
    """The crew_fix entry: (its id, None) or (None, why it failed)."""
    old, new = old_new(rec)
    head = (row.get("title") or "").strip()
    lines = [f"who:: {who}", f"op:: {rec['op']}", f"entry:: #{rec['id']}", f"at:: {N.stamp_now()}", "",
             f"{who} {summary(rec)} (steward.py, a data fix on the captain's word).", "",
             "**Old**", fenced(old) if old else "(nothing)", "", "**New**", fenced(new), "",
             fenced(json.dumps(rec, ensure_ascii=False), N.UNDO_FENCE)]
    body = {"kind": RECORD_KIND, "title": f"Fix · {rec['op']} #{rec['id']}" + (f" {head}" if head else "")
            + f" · {who}", "content": "\n".join(lines), "value_int": rec["id"], "done_bool": 1}
    body["title"] = body["title"][:200]
    s, text = T.http("POST", "/entries", body)
    if not 200 <= s < 300:
        return None, f"{s}: {N._err(text)}"
    try:
        return int(json.loads(text).get("id") or 0), None
    except (ValueError, AttributeError):
        return None, "the server's answer had no id"


def run(argv, cwd=None):
    """(exit status, the answer as a dict)."""
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in OPS or len(argv) < 2:
        return 2, {"error": "usage: steward.py " + "|".join(OPS) + " ID ... (--help says more)"}
    op, args = argv[0], argv[2:]
    if op == "new":
        return run_new(argv[1:], cwd)
    try:
        rid = entry_id(argv[1])
        if op == "get":
            row = N.get_row(rid)
            if row is None:
                return 1, {"error": f"#{rid}: no such entry, or it cannot be read"}
            return 0, row
        who = who_am_i(cwd)
        logins_ready()
        row = N.get_row(rid)
        if row is None:
            raise Refused(f"#{rid}: no such entry, or it cannot be read")
        c = change_of(op, rid, args, row.get("last_modified_at_utc") or "")
    except Refused as e:
        return 1, {"error": str(e)}
    except OSError as e:
        return 1, {"error": f"cannot read the text: {e.strerror}"}
    rec, why = N.apply_change(c, who, 0, rid, N.now())
    if rec is None:
        if "changed since it was read" in why:
            why += " (412: refused, nothing written; read it again with get and decide)"
        return 1, {"error": f"not done: {why}"}
    out = {"ok": True, "op": op, "id": rid, "done": summary(rec)}
    fix, err = record(who, rec, dict(row, **({"title": rec["title"]} if op == "title" else {})))
    if fix is None:
        return 3, dict(out, error=f"the change was made but its record was not written ({err}): keep this",
                       record=rec)
    return 0, dict(out, record_id=fix)


def run_new(args, cwd=None):
    try:
        who = who_am_i(cwd)
        logins_ready()
        c = new_change(list(args))
    except Refused as e:
        return 1, {"error": str(e)}
    except OSError as e:
        return 1, {"error": f"cannot read the text: {e.strerror}"}
    rec, why = N.apply_change(c, who, None, None, N.now())
    if rec is None:
        return 1, {"error": f"not done: {why}"}
    row = N.get_row(rec["id"]) or {}
    rec["text"] = row.get("content") or ""
    out = {"ok": True, "op": "new", "id": rec["id"], "done": summary(rec)}
    fix, err = record(who, rec, {"title": rec["title"]})
    if fix is None:
        return 3, dict(out, error=f"the entry was made but its record was not written ({err}): keep this",
                       record=rec)
    return 0, dict(out, record_id=fix)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"] if argv[0] == "get" else argv
    code, out = run(argv)
    if argv[0] == "get" and code == 0 and not as_json:
        print(f"#{out.get('id')} {out.get('kind') or '-'} · {N.title_shown(out.get('title'))}"
              + (" (deleted)" if out.get("deleted") else ""))
        print(f"last_modified_at_utc {out.get('last_modified_at_utc') or '-'}"
              + (f", start {out['start_date']}" if out.get("start_date") else "")
              + (f", end {out['end_date']}" if out.get("end_date") else ""))
        print()
        print(out.get("content") or "")
    else:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
