#!/usr/bin/env python3
"""Removes delivered crew_inbox rows from lcars.db: the one hard delete.

    scripts/db-prune.py            # dry run: what would go, nothing written
    scripts/db-prune.py --apply    # delete them

A crew_inbox entry is a delivery slip (scripts/seat.py): one per message
for a crew session, ticked done when it is delivered or cancelled. What
mattered of it is in no1_log and the sessions themselves, and the slips
grew ten times faster than the captain's own entries (400 rows, 289 KB in
their first six days). So once one is done and has not been touched for
seven days, it goes - with every row keyed by its id in the side tables:
its vector (entry_embeddings), its CalDAV rows (caldav_tasks,
caldav_moves), and any table added later with an entry_id column (found
in sqlite_master, as db-filter.sh finds them). The embedding service keeps
no store of its own: llama-server is stateless, and the vectors are
entry_embeddings. A page's cached vector for a pruned id is held the way
one for a soft-deleted row is, and never matched to a row again.
Nothing else is ever deleted: no other kind, no row not done, none
younger than the cutoff. A slip with a file in entry_media is kept, and
counted: its file is in the media store, which this does not touch.

Why a script and not a route: the API deliberately has no hard delete
(ARCHITECTURE.md, the routes), and TODO.md asked for exactly this when the
day came - a deliberate, awkward-to-trigger purge, run by hand or by its
weekly timer (lcars-prune.timer), never by a request. It opens the
database the server serves, ~/lcars/lcars.db (the unit's WorkingDirectory
and LCARS_DB_PATH's relative "lcars.db"), directly: one IMMEDIATE
transaction with a busy timeout, so a server write waits for it (and it
for one) instead of failing. The server watches the database itself
(GET /events), so open pages hear of it; their mirrors then hold more rows
than /stats?deleted=all counts, which costs each one full load
(ARCHITECTURE.md, "The count is the last check"). Ids are AUTOINCREMENT,
so a pruned id is never handed out again - the mirror's maxId stays true.

Not a crew.py verb: crew.py runs the scheduled crew, Claude sessions with
the journal's API and a login; this needs neither, and is a database
chore beside db-swap.sh and db-filter.sh.

Refuses (exit 75, nothing written to the database) when the server does
not answer /health or the path is not a regular file - the slots script
renames lcars.db while the server is stopped, and a missing file must not
be created by sqlite3.connect. Each run, refused or not, appends one JSON
line to $LCARS_ENG_STATE/prune.jsonl (~/.local/state/lcars-eng): when,
whether it applied, counted, removed.

Overrides, for scripts/test_prune.py: LCARS_PRUNE_DB (the database),
LCARS_URL (the server), LCARS_ENG_STATE (the log's directory).
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIND = "crew_inbox"
DAYS = 7
# A row with media is kept (see above), so its entry_media rows never need
# deleting.
KEEP_TABLES = {"entries", "entry_media"}


def live_db():
    """The live checkout's lcars.db: the repository this script belongs to,
    found through git's common dir as engineer.py does, so the copy in a
    worktree still answers ~/lcars."""
    if os.environ.get("LCARS_PRUNE_DB"):
        return os.environ["LCARS_PRUNE_DB"]
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=HERE,
                                capture_output=True, text=True, check=True).stdout.strip()
        live = os.path.dirname(common)
    except (OSError, subprocess.CalledProcessError):
        live = os.path.join(os.path.expanduser("~"), "lcars")
    return os.path.join(live, "lcars.db")


def state_dir():
    return os.environ.get("LCARS_ENG_STATE") or os.path.join(os.path.expanduser("~"), ".local/state/lcars-eng")


def healthy(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=10) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        e.close()
        return False
    except OSError:
        return False


def log(rec):
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(os.path.join(state_dir(), "prune.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        print(f"db-prune: cannot write prune.jsonl: {e}", file=sys.stderr)


def has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def dependents(con):
    """Every table with an entry_id column but entries' own and entry_media:
    the side tables the server's modules make (lcars_embed.h, lcars_caldav.h)
    and any added later, which is then covered without a change here."""
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return [n for n in names if n not in KEEP_TABLES and not n.startswith("sqlite_")
            and any(c[1] == "entry_id" for c in con.execute(f'PRAGMA table_info("{n}")'))]


def prune(db, apply, days=DAYS):
    """{counted, removed, kept_media, oldest, newest, dependents}: the rows
    that qualify, and with apply, deleted in the same transaction they were
    counted in."""
    # The dry run opens the file read-only: it cannot write, whatever this
    # code does. --apply takes the write lock up front (IMMEDIATE), so the
    # rows counted are the rows deleted, and a server write waiting on it
    # waits milliseconds.
    con = sqlite3.connect(f"file:{db}" + ("" if apply else "?mode=ro"), uri=True, timeout=30,
                          isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        try:
            # length = 19: a row with an empty or odd stamp is not provably
            # old, and '' sorts below every cutoff.
            cutoff = con.execute("SELECT strftime('%Y-%m-%d %H:%M:%S', 'now', ?)", (f"-{days} days",)).fetchone()[0]
            media = "EXISTS (SELECT 1 FROM entry_media m WHERE m.entry_id = e.id)" if has_table(con, "entry_media") \
                else "0"
            rows = con.execute(
                f"SELECT e.id, e.last_modified_at_utc, {media} FROM entries e"
                " WHERE e.kind = ? AND e.done_bool = 1 AND length(e.last_modified_at_utc) = 19"
                " AND e.last_modified_at_utc < ? ORDER BY e.last_modified_at_utc",
                (KIND, cutoff)).fetchall()
            go = [r for r in rows if not r[2]]
            res = {"cutoff": cutoff, "counted": len(go), "removed": 0, "kept_media": len(rows) - len(go),
                   "oldest": go[0][1] if go else None, "newest": go[-1][1] if go else None, "dependents": {}}
            ids = [r[0] for r in go]
            for table in dependents(con):
                n = 0
                for i in range(0, len(ids), 500):   # under SQLite's variable limit
                    chunk = ids[i:i + 500]
                    q = ",".join("?" * len(chunk))
                    if apply:
                        n += con.execute(f'DELETE FROM "{table}" WHERE entry_id IN ({q})', chunk).rowcount
                    else:
                        n += con.execute(f'SELECT count(*) FROM "{table}" WHERE entry_id IN ({q})', chunk).fetchone()[0]
                res["dependents"][table] = n
            if apply:
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    # the kind and done are asked again: belt and braces on
                    # the one statement here that removes journal rows
                    res["removed"] += con.execute(
                        f"DELETE FROM entries WHERE id IN ({','.join('?' * len(chunk))})"
                        " AND kind = ? AND done_bool = 1", chunk + [KIND]).rowcount
                if res["removed"] != len(ids):
                    raise RuntimeError(f"deleted {res['removed']} of {len(ids)} rows: rolled back")
                con.execute("COMMIT")
            else:
                con.execute("ROLLBACK")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        return res
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Remove crew_inbox rows done and untouched for 7 days (dry run "
                                             "unless --apply).")
    ap.add_argument("--apply", action="store_true", help="delete them (default: only count)")
    a = ap.parse_args(argv)
    db = live_db()
    url = os.environ.get("LCARS_URL") or "http://127.0.0.1:8080"
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "apply": a.apply, "db": db}
    refused = None
    if not os.path.isfile(db):
        refused = f"{db} is not a file"
    elif not healthy(url):
        refused = f"the server at {url} does not answer /health"
    if refused:
        log(dict(rec, refused=refused, counted=0, removed=0))
        print(f"db-prune: refused: {refused}", file=sys.stderr)
        return 75
    try:
        res = prune(db, a.apply)
    except (sqlite3.Error, RuntimeError) as e:
        log(dict(rec, error=str(e), counted=0, removed=0))
        print(f"db-prune: {e}", file=sys.stderr)
        return 1
    log(dict(rec, **res))
    verb = "removed" if a.apply else "would remove"
    n = res["removed"] if a.apply else res["counted"]
    print(f"{verb} {n} {KIND} rows done before {res['cutoff']} UTC"
          + (f", last touched {res['oldest']} .. {res['newest']}" if res["counted"] else ""))
    deps = ", ".join(f"{t} {c}" for t, c in res["dependents"].items() if c)
    if deps:
        print(f"  and their {deps}")
    if res["kept_media"]:
        print(f"  kept {res['kept_media']} with media (their files are not this script's)")
    if not a.apply:
        print("  dry run: nothing written (--apply deletes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
