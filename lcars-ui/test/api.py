#!/usr/bin/env python3
"""The /entries write API's timestamps, end to end against a scratch server.

POST /entries and PUT/PATCH /entries/<id> take created_at_utc (and on POST
last_modified_at_utc, and both start_date/end_date) as "YYYY-MM-DD",
"YYYY-MM-DD HH:MM:SS" in UTC, or ISO 8601 with a zone - what an Apple
Shortcut's "ISO 8601" date format gives, in the phone's local time:
"2026-10-15T07:02:33+03:00", "...Z", "....123Z". lcars_http.h's
ParseZonedTimestamp turns the zoned shape into the stored UTC text without
touching $TZ; this checks the conversions it must get right (offsets either
way, across midnight, a month end, a year end, a leap day) and that anything
else is still a 400. And InitDB (lcars_db.h) plants no seed: a new
journal is empty (docs/design/kinds.md, 4), and so is one emptied by hand
and started again.

  1. a scratch build of the server (`make -n lcars-release`, compiled to a
     temp path - never `make` itself, which on the VPS would overwrite the
     live binary), on an empty database in a temp directory;
  2. POST with each accepted shape, read back by GET /entries/<id>;
  3. PUT and PATCH moving created_at_utc the same way;
  4. malformed stamps: 400, naming the accepted shapes, and nothing written;
  5. no seed: the new database has no row; a copy of it with every row
     taken out, started on again, still has none.

    python3 test/api.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/api.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.request

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
USER, PASS = "t", "t"
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build(out):
    """The release compile line, pointed at `out` instead of ./lcars."""
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-release"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and " -o lcars lcars.c" in l), None)
    if not line:
        sys.exit("api: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("api: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp, args=(), env_extra=None, cwd=None, log="server.log"):
        """A scratch server whose working directory is `cwd` (default tmp),
        with `args` after the port and `env_extra` in its environment; its
        output goes to tmp/`log`."""
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS, LCARS_CALDAV_LOG="0")
        for k in ("LCARS_TZ", "LCARS_TASK_KIND", "LCARS_DB_PATH", "LCARS_DATA_DIR"):
            env.pop(k, None)
        env.update(env_extra or {})
        self.log_path = tmp / log
        self.log = open(self.log_path, "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--http-only", "--port", str(self.port), *args],
                                                     cwd=cwd or tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("api: the scratch server did not come up; see " + str(self.log_path))

    def req(self, method, path, body=None, headers=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": AUTH}
        if ctype:
            h["Content-Type"] = ctype
        h.update(headers or {})
        data = body.encode() if isinstance(body, str) else body
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read().decode()
        c.close()
        return out

    def json(self, method, path, obj=None):
        st, _, body = self.req(method, path, json.dumps(obj) if obj is not None else None,
                               ctype="application/json")
        return st, (json.loads(body) if body.strip().startswith(("{", "[")) else body)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


# (what is sent, what must be stored)
GOOD = [
    ("2026-10-15T07:02:33+03:00", "2026-10-15 04:02:33"),
    ("2026-10-15T04:02:33Z", "2026-10-15 04:02:33"),
    ("2026-10-15T04:02:33.123Z", "2026-10-15 04:02:33"),
    ("2026-10-15T04:02:33,5z", "2026-10-15 04:02:33"),
    ("2026-10-15T07:02:33+0300", "2026-10-15 04:02:33"),
    ("2026-10-15T07:02:33+00:00", "2026-10-15 07:02:33"),
    ("2026-10-15T07:02:33-00:00", "2026-10-15 07:02:33"),
    ("2026-10-15T22:30:00-05:00", "2026-10-16 03:30:00"),  # negative, past midnight
    ("2026-10-31T21:15:00-04:00", "2026-11-01 01:15:00"),  # and past a month end
    ("2026-12-31T23:59:59-00:30", "2027-01-01 00:29:59"),  # a year end
    ("2026-11-01T01:00:00+03:00", "2026-10-31 22:00:00"),  # positive, back a month
    ("2027-01-01T00:00:00+05:45", "2026-12-31 18:15:00"),  # back a year, odd minutes
    ("2028-02-29T23:00:00-02:00", "2028-03-01 01:00:00"),  # a leap day
    ("2028-03-01T01:00:00+02:00", "2028-02-29 23:00:00"),
    ("2026-10-15", "2026-10-15 00:00:00"),                 # the old shapes, unchanged
    ("2026-10-15 07:02:33", "2026-10-15 07:02:33"),
]

BAD = [
    "yesterday", "2026-10-15T07:02:33", "2026-10-15T07:02+03:00",
    "2026-10-15T07:02:33+3:00", "2026-10-15T07:02:33+03:0", "2026-10-15T07:02:33+24:00",
    "2026-10-15T07:02:33.Z", "2026-10-15T07:02:33Zjunk", "2026-13-01T00:00:00Z",
    "2026-02-29T00:00:00Z", "2026-04-31T00:00:00Z", "2026-10-15T24:00:00Z",
    "2026-10-15T07:60:00Z", "2026-10-15X07:02:33Z", "2026-10-15T07:02:33 +03:00",
]


def seeded(s):
    """Every row, deleted ones too: what InitDB planted, if anything."""
    st, rows = s.json("GET", "/entries?deleted=all")
    return rows if st == 200 and isinstance(rows, list) else None


def run(s):
    print("no seed: a new journal is empty")
    rows = seeded(s)
    check(rows == [], f"no row on a new database (got {rows})")

    print("POST: each accepted shape, read back")
    for sent, want in GOOD:
        st, row = s.json("POST", "/entries", {"kind": "note", "title": sent,
                                             "created_at_utc": sent,
                                             "last_modified_at_utc": sent})
        ok = st in (200, 201) and isinstance(row, dict) and row.get("id")
        got = s.json("GET", f"/entries/{row['id']}")[1] if ok else {}
        check(ok and got.get("created_at_utc") == want
              and got.get("last_modified_at_utc") == want,
              f"POST {sent} -> {want} (got {got.get('created_at_utc') if ok else (st, row)})")

    print("POST: the schedule takes the same shapes")
    st, row = s.json("POST", "/entries", {"kind": "task", "title": "span",
                                         "start_date": "2026-10-15T22:30:00-05:00",
                                         "end_date": "2026-10-15T07:02:33.5+03:00"})
    got = s.json("GET", f"/entries/{row['id']}")[1]
    check(got.get("start_date") == "2026-10-16 03:30:00"
          and got.get("end_date") == "2026-10-15 04:02:33",
          f"start_date/end_date converted to UTC (got {got.get('start_date')}, {got.get('end_date')})")

    print("PUT and PATCH")
    st, row = s.json("POST", "/entries", {"kind": "note", "title": "to move"})
    eid = row["id"]
    for method, sent, want in [("PUT", "2026-10-15T07:02:33+03:00", "2026-10-15 04:02:33"),
                               ("PATCH", "2026-10-31T21:15:00-04:00", "2026-11-01 01:15:00"),
                               ("PUT", "2026-10-15T04:02:33.123Z", "2026-10-15 04:02:33")]:
        st, _ = s.json(method, f"/entries/{eid}", {"created_at_utc": sent})
        got = s.json("GET", f"/entries/{eid}")[1]
        check(st == 200 and got.get("created_at_utc") == want and got.get("title") == "to move",
              f"{method} {sent} -> {want} (got {st}, {got.get('created_at_utc')})")

    print("malformed stamps: 400, nothing written")
    before = len(s.json("GET", "/entries?deleted=all&limit=1000")[1])
    for bad in BAD:
        st, err = s.json("POST", "/entries", {"kind": "note", "title": "bad",
                                             "created_at_utc": bad})
        msg = err.get("error", "") if isinstance(err, dict) else str(err)
        check(st == 400 and "YYYY-MM-DDTHH:MM:SS" in msg and "+HH:MM" in msg,
              f"POST {bad!r} -> 400 naming the shapes (got {st}, {msg!r})")
    st, err = s.json("PUT", f"/entries/{eid}", {"created_at_utc": "2026-10-15T07:02:33"})
    check(st == 400, f"PUT with a zoneless T stamp -> 400 (got {st})")
    st, err = s.json("POST", "/entries", {"kind": "note", "last_modified_at_utc": "junk"})
    check(st == 400 and "last_modified_at_utc" in str(err), "a bad last_modified_at_utc -> 400")
    after = len(s.json("GET", "/entries?deleted=all&limit=1000")[1])
    check(after == before, f"no row written by a refused POST ({before} -> {after})")
    got = s.json("GET", f"/entries/{eid}")[1]
    check(got.get("created_at_utc") == "2026-10-15 04:02:33", "a refused PUT left the row alone")

    print("classification (lcars_vault.h): every row Unclassified, the envelope refused without a vault")
    check(got.get("classification") == 0 and "sealed" not in got,
          f"a row reads classification 0 and no sealed ({got.get('classification')})")
    st, rows = s.json("GET", "/entries?limit=1000")
    check(all(r.get("classification") == 0 for r in rows), "every listed row too")
    st, err = s.json("POST", "/entries", {"kind": "note", "classification": 2, "sealed": "lcs1.aGk.aGk"})
    check(st == 409 and "vault" in str(err), f"a Secret create with no vault -> 409 ({st})")
    st, err = s.json("PATCH", f"/entries/{eid}", {"classification": 2, "sealed": "lcs1.aGk.aGk"})
    check(st == 409, f"a raise with no vault -> 409 ({st})")
    st, err = s.json("PATCH", f"/entries/{eid}", {"classification": 7})
    check(st == 400, f"an unknown level -> 400 ({st})")
    check(s.json("GET", f"/entries/{eid}")[1].get("classification") == 0, "and the row is as it was")


def unseeded(binary, tmp):
    """A journal emptied by hand is not seeded on its next start either.
    `tmp/lcars.db` is the first server's, stopped: copied by sqlite's backup
    (whatever is still in its WAL included), every row deleted from the
    copy, a second server started on it."""
    copy = tmp / "unseeded"
    copy.mkdir()
    src = sqlite3.connect(tmp / "lcars.db")
    dst = sqlite3.connect(copy / "lcars.db")
    src.backup(dst)
    src.close()
    had = dst.execute("SELECT count(*) FROM entries").fetchone()[0]
    dst.execute("DELETE FROM entries")
    dst.commit()
    dst.close()
    print("no seed: a journal emptied by hand stays empty")
    check(had > 0, f"the copy had the run's rows before ({had})")
    s = Server(binary, copy)
    try:
        rows = seeded(s)
        check(rows == [], f"no row planted on its start (got {rows})")
    finally:
        s.stop()


def db_line(s):
    """The start log's "Database: <path> (<state>, <n> entries)" line."""
    for line in s.log_path.read_text().splitlines():
        if line.startswith("Database: "):
            return line
    return ""


def where(binary, tmp):
    """The journal's path at run time (LcarsDBPath in lcars_db.h): --db,
    --data, $LCARS_DB_PATH, $LCARS_DATA_DIR, else lcars.db in the working
    directory - each a new, empty journal, in that file and nowhere else, named in the start log; and the refusals."""
    base = tmp / "where"
    base.mkdir()

    def fresh(name):
        d = base / name
        d.mkdir()
        return d

    print("the working directory's lcars.db, named in the start log")
    st = tmp / "server.log"
    line = next((l for l in st.read_text().splitlines() if l.startswith("Database: ")), "")
    check(line.startswith(f"Database: {tmp.resolve() / 'lcars.db'} (NEW: created just now, 0 entries)"),
          f"the first server's start log names its new journal (got {line!r})")

    cases = [  # (name, args, env, the file that must be the journal)
        ("--data", lambda d: ["--data", str(d / "data")], lambda d: {}, lambda d: d / "data" / "lcars.db"),
        ("--data with a slash", lambda d: ["--data", str(d / "data") + "/"], lambda d: {}, lambda d: d / "data" / "lcars.db"),
        ("--db", lambda d: ["--db", str(d / "data" / "j.db")], lambda d: {}, lambda d: d / "data" / "j.db"),
        ("LCARS_DATA_DIR", lambda d: [], lambda d: {"LCARS_DATA_DIR": str(d / "data")}, lambda d: d / "data" / "lcars.db"),
        ("LCARS_DB_PATH", lambda d: [], lambda d: {"LCARS_DB_PATH": str(d / "data" / "j.db")}, lambda d: d / "data" / "j.db"),
        ("--db over LCARS_DATA_DIR", lambda d: ["--db", str(d / "data" / "j.db")],
         lambda d: {"LCARS_DATA_DIR": str(d / "other")}, lambda d: d / "data" / "j.db"),
        ("--data over LCARS_DB_PATH", lambda d: ["--data", str(d / "data")],
         lambda d: {"LCARS_DB_PATH": str(d / "other" / "j.db")}, lambda d: d / "data" / "lcars.db"),
        ("an empty LCARS_DB_PATH is unset", lambda d: [],
         lambda d: {"LCARS_DB_PATH": "", "LCARS_DATA_DIR": str(d / "data")}, lambda d: d / "data" / "lcars.db"),
    ]
    for i, (name, args, env, want) in enumerate(cases):
        d = fresh(f"c{i}")
        (d / "data").mkdir()
        (d / "other").mkdir()
        (d / "cwd").mkdir()
        print(f"a new journal under {name}")
        s = Server(binary, d, args(d), env(d), cwd=d / "cwd")
        try:
            rows = seeded(s)
            check(rows == [], f"{name}: the new journal is empty (got {rows})")
            st, row = s.json("POST", "/entries", {"kind": "note", "title": "kept"})
            check(st in (200, 201), f"{name}: a write lands (got {st})")
        finally:
            s.stop()
        target = want(d)
        made = sorted(str(p.relative_to(d)) for p in d.rglob("*.db"))
        check(made == [str(target.relative_to(d))],
              f"{name}: the journal is {target.relative_to(d)} and no other file (got {made})")
        con = sqlite3.connect(target)
        n = con.execute("SELECT count(*) FROM entries").fetchone()[0]
        con.close()
        check(n == 1, f"{name}: the write, and only it, is in that file ({n} rows)")
        check(db_line(s) == f"Database: {target.resolve()} (NEW: created just now, 0 entries)",
              f"{name}: the start log names it, new (got {db_line(s)!r})")
        if i == 0:
            print("--data again: the same journal, existing, with its count")
            s = Server(binary, d, args(d), env(d), cwd=d / "cwd", log="again.log")
            try:
                st, rows = s.json("GET", "/entries?kind=note")
                check(st == 200 and [r.get("title") for r in rows] == ["kept"],
                      f"the write is read back after a restart (got {st}, {rows})")
            finally:
                s.stop()
            check(db_line(s) == f"Database: {target.resolve()} (existing, 1 entries)",
                  f"the restart's start log: existing, 1 entries (got {db_line(s)!r})")

    print("refused: a --data that does not exist, a --db that is a directory")
    for args, env, says in [(["--data", str(base / "nope")], {}, "does not exist"),
                            ([], {"LCARS_DATA_DIR": str(base / "nope")}, "does not exist"),
                            (["--db", str(base)], {}, "is a directory")]:
        e = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", **env)
        e.pop("LCARS_DB_PATH", None)
        if not env:
            e.pop("LCARS_DATA_DIR", None)
        r = subprocess.run([str(binary), "--port", str(free_port()), *args], cwd=base, env=e,
                           capture_output=True, text=True, timeout=10)
        check(r.returncode == 2 and says in r.stderr,
              f"{args or env}: exit 2 saying {says!r} (got {r.returncode}, {r.stderr.strip()!r})")
    check(not (base / "nope").exists() and not (base / "lcars.db").exists(),
          "nothing made by a refused start")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-api-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    try:
        run(s)
    finally:
        s.stop()
    unseeded(binary, tmp)
    where(binary, tmp)
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server log: {tmp / 'server.log'}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
