#!/usr/bin/env python3
"""Write a synthetic journal to a fresh sqlite file, for the behaviour suite.

    python3 test/synth.py /tmp/synth.db [rows] && LCARS_TEST_DB=/tmp/synth.db test/run.sh

The rows are perf.py's journal (dense recent months, a sparse tail, eight
kinds, markdown bodies with a task line), moved so the newest is an hour
ago. A suite that passes on the real journal and on this one does not lean
on what the real one happens to hold that day (0.177.5). Then a handful of
the crew's rooms and messages (docs/design/rooms.md), as the live journal
holds thousands: a check of the Rooms page that counts or orders rooms, or
reads "the first bubble", fails here as it would on the real one.
"""
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from perf import journal  # noqa: E402
import rooms as R  # noqa: E402  (the crew rows' titles and contents, as the crew writes them)

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
# the crew's rooms and messages: project rooms (one of them "deck", the id
# the suite's own checks use, and one closed), a migrated row (at::, src::),
# Number One's order waiting for the seat, a report, a DM, the captain's word;
# then a report entry of each type
top = max(r["id"] for r in rows)
now = (datetime.datetime.strptime(rows[0]["created_at_utc"], fmt) + shift).strftime(fmt)
crew = [(R.ROOM_KIND, "Status report", "id:: status-report\nby:: no1", 0),
        (R.ROOM_KIND, "Deck (the journal's own)", "id:: deck\nby:: captain", 0),
        (R.ROOM_KIND, "Old work", "id:: old-work\nby:: no1", 1)]
for frm, to, room, text, done, extra in (
        ("captain", "no1", "main", "Status?", 1, ("at:: 2026-09-01 08:00:00", "src:: s-old s-old:120")),
        ("no1", "", "main", "All quiet, Captain.", 1, ()),
        ("no1", "obrien-c33", "status-report", "[No.1] Write the status report.", 0, ()),
        ("obrien-c33", "", "status-report", "Report: done.\n\n" + "\n".join(f"- point {i}" for i in range(20)), 1, ()),
        ("obrien-c33", "kim-c35", "kim-c35", "Can you rerun the suite?", 0, ()),
        ("captain", "no1", "deck", "The journal's own word in deck.", 1, ()),
        ("captain", "kim-c35", "kim-c35", "One to one.", 1, ())):
    crew.append((R.MSG_KIND, R.title(frm, to, room, text), R.content(text, room, to, extra), done))
# the published reports (docs/design/reports-as-entries.md): one of each
# type, as report.py writes them - the text types with the file's text, the
# binary ones and an HTML one too big for an entry their first line alone
REP = "media/reports/2026/10/"
for typ, title, text in (
        ("html", "Fleet status", "<!doctype html><html><head><style>h1{color:#c60}</style></head>"
                                 "<body><h1>Fleet status</h1><p>All warp cores nominal.</p></body></html>"),
        ("md", "Weekly review", "# Weekly review\n\nThe **sleep** held at 7h; [[LCARS UI]] slice 6 shipped.\n"),
        ("txt", "Disk check", "/ 41% used\n/mnt/nas 63% used\n"),
        ("csv", "Weights", "date,kg\n2026-10-01,80.2\n2026-10-08,79.6\n"),
        ("pdf", "Audit", ""), ("png", "Sleep chart", ""), ("zip", "Shots", ""), ("other", "Raw dump", ""),
        ("html", "Photo essay (inlined pictures)", ""),
        # raw HTML by design: an inlined picture and a script, which the
        # suite's markup scan must leave to the sandboxed frame
        ("html", "Sleep chart page", "<!doctype html><html><body><h1>Sleep</h1>"
                                     "<img src=\"data:image/png;base64,AAAA\" alt=\"chart\">"
                                     "<script>document.title='ran'</script></body></html>")):
    ext = {"other": "bin"}.get(typ, typ)
    slug = title.lower().split(" (")[0].replace(" ", "-")
    head = f"report:: {typ} {REP}{slug}-{len(crew):08x}.{ext}"
    crew.append(("report", title, head + ("\n\n" + text if text else ""), 0))
# the releases (what the deploy writes): three consecutive versions, the
# newest one past the page's APP_VERSION, so What's new has one to list
import re  # noqa: E402
_page = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "index.html"), encoding="utf-8").read(4096)
_maj, _min, _pat = map(int, re.search(r'const APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', _page).groups())
for d, notes in ((-1, "- **web** the one before this page"), (0, "- **web** this page's own release\n- **ops** its second line"),
                 (1, "- **web** the next one, newer than this page")):
    v = f"{_maj}.{_min}.{max(0, _pat + d)}"
    crew.append(("release", v, f"release:: {v} 2026-10-2{3 + d}\n\n{notes}\n", 0))
for i, (kind, title, content, done) in enumerate(crew):
    con.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (top + 1 + i, kind, title, content, 0, 0, done, 0, now, now, "", ""))
# Number One's question to the captain, answered (task_no1, done, the
# answer's line), and its log quoting it on a line that opens with a task
# word: the Tasks board shows that line, "#<id>" and all - the entry's own
# words, not the board's (slice A's deploy met it in the live journal). The
# old rows, so the board's open tasks (oldest first, 250 of them) hold it;
# a quarter of the way into the history, not its start: gen.py's sample of
# the older rows must still end on one of perf.py's (the media checks hang
# files off the newest and the oldest, and want two kinds).
ask = top + 1 + len(crew)
when = sorted(datetime.datetime.strptime(r["created_at_utc"], fmt) for r in rows)
old = (when[len(when) // 4] + shift + datetime.timedelta(minutes=1)).strftime(fmt)
for i, (kind, title, content, done) in enumerate((
        ("task_no1", "May the crew set the end of an open sleep entry?",
         "Today's rule: the crew never changes dates. Close last night's sleep entries?\n\nanswer : yes", 1),
        ("no1_log", "Open work",
         f"OPEN WORK: nothing queued.\nWAITING ON THE CAPTAIN: nothing open in asks (#{ask} answered yes).", 0))):
    con.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ask + i, kind, title, content, 0, 0, done, 0, old, old, "", ""))
con.commit()
con.close()
print(f"{out}: {len(rows)} rows, newest {rows[0]['created_at_utc']} moved by {shift}")
