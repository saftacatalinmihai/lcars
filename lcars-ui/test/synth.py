#!/usr/bin/env python3
"""Write a synthetic journal to a fresh sqlite file, for the behaviour suite.

    python3 test/synth.py /tmp/synth.db [rows] && LCARS_TEST_DB=/tmp/synth.db test/run.sh

The rows are perf.py's journal (dense recent months, a sparse tail, eight
kinds, markdown bodies with a task line), moved so the newest is an hour
ago. A suite that passes on the real journal and on this one does not lean
on what the real one happens to hold that day (0.177.5).
"""
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perf import journal  # noqa: E402

if len(sys.argv) < 2:
    sys.exit("usage: synth.py OUT.db [rows]")
out, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4000
if os.path.exists(out):
    os.remove(out)
rows = journal(n)
fmt = "%Y-%m-%d %H:%M:%S"
shift = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
         - datetime.timedelta(hours=1)) - datetime.datetime.strptime(rows[0]["created_at_utc"], fmt)
con = sqlite3.connect(out)
con.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, kind TEXT, title TEXT, content TEXT,"
            " value_int INTEGER, value_float REAL, done_bool INTEGER, deleted INTEGER,"
            " created_at_utc TEXT, last_modified_at_utc TEXT, start_date TEXT, end_date TEXT)")
for r in rows:
    at = (datetime.datetime.strptime(r["created_at_utc"], fmt) + shift).strftime(fmt)
    con.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["kind"], r["title"], r["content"], r["value_int"], r["value_float"],
                 r["done_bool"], r["deleted"], at, at, r["start_date"], r["end_date"]))
con.commit()
con.close()
print(f"{out}: {len(rows)} rows, newest {rows[0]['created_at_utc']} moved by {shift}")
