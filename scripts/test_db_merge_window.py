#!/usr/bin/env python3
"""Tests for scripts/db-merge-window.py: what the copy got while it was live,
copied into the full journal through the API.

    python3 scripts/test_db_merge_window.py    (~40s with the build; LCARS_TEST_BIN skips it)

Two scratch journals: the "live" one behind a scratch server built from
the lcars-release compile line (never ./lcars), seeded through the API with
backdated stamps, and the "copy", a sqlite file holding the same old rows
under the same ids plus what was written to it in the window. The script
is run as the captain would, against both: the dry run's classes (NEW,
MOVED, CONFLICT, MISSING, SKIPPED, PRESENT by title and by content), that
it writes nothing and the copy's bytes never change; --apply's writes (the
fields of a NEW row and its stamps, a deleted one deleted, a MOVED one
patched, a CONFLICT untouched); a second --apply finding nothing to write;
the default window from the state file; and the refusal while the state
file says the copy is live.
"""

import base64
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "lcars-ui" / "test"))
import killclean  # noqa: E402 - its scratch goes when the run is killed
from caldav import build, free_port  # noqa: E402

TMP = pathlib.Path(killclean.mkdtemp(prefix="merge-test-"))
SCRIPT = HERE / "db-merge-window.py"
USER = ("t", "t")
SINCE, UNTIL = "2026-01-01 10:00:00", "2026-01-01 11:00:00"
OLD = "2025-12-01 09:00:00"

SCHEMA = """
CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT '', title TEXT, content TEXT,
  value_int INTEGER, value_float REAL, value_blob BLOB, done_bool INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
  created_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')),
  last_modified_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')),
  start_date TEXT DEFAULT '', end_date TEXT DEFAULT '');
CREATE TABLE entry_media (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, path TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
  created_at_utc TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
"""


class Merge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary = os.environ.get("LCARS_TEST_BIN")
        if not binary:
            binary = str(TMP / "lcars")
            build(binary)
        cls.port = free_port()
        live = TMP / "live"
        live.mkdir()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_AUTH_USER=USER[0], LCARS_AUTH_PASS=USER[1])
        env.pop("LCARS_DB_PATH", None)
        cls.log = open(TMP / "server.log", "w")
        cls.proc = killclean.child(subprocess.Popen([binary, "--port", str(cls.port)], cwd=live, env=env,
                                                    stdout=cls.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        cls.seed()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    @classmethod
    def req(cls, method, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", method=method,
                                   data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json", "Authorization": "Basic "
                                            + base64.b64encode(f"{USER[0]}:{USER[1]}".encode()).decode()})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    @classmethod
    def post(cls, **row):
        st, got = cls.req("POST", "/entries", row)
        assert st in (200, 201), (st, got)
        return got["id"]

    @classmethod
    def seed(cls):
        # Old rows, in both journals under the same ids.
        old = dict(kind="note", created_at_utc=OLD, last_modified_at_utc=OLD)
        cls.moved = cls.post(title="moved", content="before", **old)
        cls.conflict = cls.post(title="conflict", content="before", **old)
        cls.quiet = cls.post(title="quiet", content="same", **old)
        cls.seat = cls.post(kind="crew_seat", title="seat", content="{}", created_at_utc=OLD, last_modified_at_utc=OLD)
        # Changed in the live journal after the window too: a CONFLICT.
        assert cls.req("PATCH", f"/entries/{cls.conflict}", {"content": "live's edit"})[0] == 200
        # Already copied by hand: one with its title, one retitled since.
        cls.present = cls.post(kind="no1_log", title="had it", content="x", created_at_utc="2026-01-01 10:05:00")
        cls.retitled = cls.post(kind="no1_log", title="yeoman's title", content="body kept",
                                created_at_utc="2026-01-01 10:06:00")
        # The ids after the gap, reused by the live journal for other rows.
        cls.reused = cls.post(kind="crew_inbox", title="live's own", content="", created_at_utc="2026-01-01 12:00:00")

        cls.copy = TMP / "copy.db"
        db = sqlite3.connect(cls.copy)
        db.executescript(SCHEMA)
        ins = ("INSERT INTO entries (id, kind, title, content, value_int, value_float, done_bool, deleted,"
               " created_at_utc, last_modified_at_utc, start_date, end_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
        rows = [
            (cls.moved, "note", "moved", "the copy's edit", None, None, 1, 0, OLD, "2026-01-01 10:30:00", "", ""),
            (cls.conflict, "note", "conflict", "the copy's edit", None, None, 0, 0, OLD, "2026-01-01 10:20:00", "", ""),
            (cls.quiet, "note", "quiet", "same", None, None, 0, 0, OLD, OLD, "", ""),
            (cls.seat, "crew_seat", "seat", '{"stale":1}', None, None, 0, 0, OLD, "2026-01-01 10:40:00", "", ""),
            (500, "note", "missing", "gone", None, None, 0, 0, OLD, "2026-01-01 10:10:00", "", ""),
            # Written while the copy was live; the first reuses a live id.
            (cls.reused, "trip", "Drive | home", "a drive", 3, 12.5, 0, 0, "2026-01-01 10:15:00",
             "2026-01-01 10:25:00", "2026-01-01 09:00:00", "2026-01-01 10:00:00"),
            (cls.reused + 1, "no1_log", "log line", "said", None, None, 0, 0, "2026-01-01 10:16:00",
             "2026-01-01 10:16:00", "", ""),
            (cls.reused + 2, "note", "binned", "then deleted", None, None, 0, 1, "2026-01-01 10:17:00",
             "2026-01-01 10:18:00", "", ""),
            (cls.reused + 3, "crew_inbox", "slip", "", None, None, 1, 0, "2026-01-01 10:18:00",
             "2026-01-01 10:18:00", "", ""),
            (cls.reused + 4, "task_no1", "question", "?", None, None, 0, 0, "2026-01-01 10:19:00",
             "2026-01-01 10:19:00", "", ""),
            (cls.reused + 5, "no1_log", "had it", "x", None, None, 0, 0, "2026-01-01 10:05:00",
             "2026-01-01 10:05:00", "", ""),
            (cls.reused + 6, "no1_log", None, "body kept", None, None, 0, 0, "2026-01-01 10:06:00",
             "2026-01-01 10:06:00", "", ""),
            # After the window: not the script's.
            (cls.reused + 7, "note", "later", "", None, None, 0, 0, "2026-01-01 11:30:00",
             "2026-01-01 11:30:00", "", ""),
        ]
        db.executemany(ins, rows)
        db.execute("INSERT INTO entry_media (entry_id, path, mime, bytes, name, created_at_utc)"
                   " VALUES (?, 'media/2026/01/x.jpg', 'image/jpeg', 10, 'x.jpg', '2026-01-01 10:15:30')",
                   (cls.reused,))
        db.commit()
        db.close()
        cls.copy_hash = hashlib.sha256(cls.copy.read_bytes()).hexdigest()
        cls.state = TMP / "db-swap.json"
        cls.state.write_text(json.dumps({"alt_slot": str(cls.copy), "in_live_slot": "lcars.db",
                                         "filtered_at": "2026-01-01T10:00:00Z", "swapped_at": "2026-01-01T11:00:00Z"}))

    def run_script(self, *args, state=None):
        env = dict(os.environ, LCARS_URL=f"http://127.0.0.1:{self.port}", LCARS_AUTH_USER=USER[0],
                   LCARS_AUTH_PASS=USER[1], LCARS_MERGE_STATE=str(state or self.state),
                   LCARS_MERGE_ENV=str(TMP / "no.env"))
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def plan(self, *args):
        p = self.run_script("--copy", str(self.copy), "--json", *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def by_class(self, plan):
        out = {}
        for r in plan["rows"]:
            out.setdefault(r["class"], set()).add((r["kind"], r["copy_id"]))
        return out

    def live_count(self):
        return self.req("GET", "/stats?deleted=all")[1]

    def test_all(self):
        R = self.reused
        before = self.live_count()
        # The dry run: every class, nothing written.
        plan = self.plan()
        self.assertEqual((plan["since"], plan["until"]), (SINCE, UNTIL), "the window from the state file")
        c = self.by_class(plan)
        self.assertEqual(c.get("NEW"), {("trip", R), ("no1_log", R + 1), ("note", R + 2)})
        self.assertEqual(c.get("MOVED"), {("note", self.moved)})
        self.assertEqual(c.get("CONFLICT"), {("note", self.conflict)})
        self.assertEqual(c.get("MISSING"), {("note", 500)})
        self.assertEqual(c.get("SKIPPED"), {("crew_seat", self.seat), ("crew_inbox", R + 3), ("task_no1", R + 4)})
        self.assertEqual(c.get("PRESENT"), {("no1_log", R + 5), ("no1_log", R + 6)})
        self.assertNotIn(self.quiet, [r["copy_id"] for r in plan["rows"]], "unchanged in the window: not listed")
        self.assertNotIn(R + 7, [r["copy_id"] for r in plan["rows"]], "after the window: not listed")
        self.assertEqual(plan["media"], [{"id": 1, "entry_id": R}])
        moved = next(r for r in plan["rows"] if r["class"] == "MOVED")
        self.assertEqual(moved["fields"], ["content", "done_bool"])
        self.assertEqual(self.live_count(), before, "a dry run writes nothing")
        md = TMP / "plan.md"
        p = self.run_script("--copy", str(self.copy), "--markdown", str(md))
        self.assertEqual(p.returncode, 0, p.stderr)
        text = md.read_text()
        self.assertIn("| trip | 1 |", text)
        self.assertIn("Drive \\| home", text, "a title's pipe escaped")
        self.assertNotIn("the copy's edit", text, "no content in the report")
        self.assertNotIn("a drive", text)

        # --apply: the NEW rows inserted, the MOVED one patched, nothing else.
        undo = TMP / "state" / "undo.json"
        plan = self.plan("--apply", "--undo", str(undo))
        res = {r["copy_id"]: r for r in plan["rows"]}
        saved = json.loads(undo.read_text())
        self.assertEqual([(u["id"], u["content"], u["done_bool"], u["last_modified_at_utc"]) for u in saved],
                         [(self.moved, "before", 0, OLD)], "the MOVED row as it was, before the PATCH")
        self.assertEqual(self.run_script("--copy", str(self.copy), "--apply", "--undo", str(undo)).returncode, 2,
                         "an earlier undo file is never overwritten")
        trip = self.req("GET", f"/entries/{res[R]['live_id']}")[1]
        self.assertNotEqual(trip["id"], R, "a new id, not the copy's")
        for k, v in dict(kind="trip", title="Drive | home", content="a drive", value_int=3, value_float=12.5,
                         created_at_utc="2026-01-01 10:15:00", last_modified_at_utc="2026-01-01 10:25:00",
                         start_date="2026-01-01 09:00:00", end_date="2026-01-01 10:00:00", deleted=0).items():
            self.assertEqual(trip[k], v, k)
        binned = self.req("GET", f"/entries/{res[R + 2]['live_id']}")[1]
        self.assertEqual((binned["title"], binned["deleted"]), ("binned", 1))
        self.assertEqual(res[R + 2]["result"], "inserted, deleted")
        mv = self.req("GET", f"/entries/{self.moved}")[1]
        self.assertEqual((mv["content"], mv["done_bool"], mv["title"]), ("the copy's edit", 1, "moved"))
        cf = self.req("GET", f"/entries/{self.conflict}")[1]
        self.assertEqual(cf["content"], "live's edit", "a CONFLICT is never written")
        self.assertEqual(self.req("GET", f"/entries/{R}")[1]["title"], "live's own", "the reused id untouched")
        seat = self.req("GET", f"/entries/{self.seat}")[1]
        self.assertEqual(seat["content"], "{}", "SKIPPED is never written")
        self.assertEqual(self.live_count()["count"], before["count"] + 3)

        # Again: nothing to write.
        plan = self.plan("--apply")
        c = self.by_class(plan)
        self.assertNotIn("NEW", c)
        self.assertNotIn("MOVED", c)
        self.assertEqual(c.get("SAME"), {("note", self.moved)})
        self.assertEqual(len(c.get("PRESENT")), 5)
        self.assertEqual(self.live_count()["count"], before["count"] + 3)
        self.assertEqual(hashlib.sha256(self.copy.read_bytes()).hexdigest(), self.copy_hash,
                         "the copy's bytes never change")

    def test_guard(self):
        """A MOVED row edited between the read and the PATCH: if_modified
        makes it a 412, and the row stays as the other writer left it."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("merge", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        rid = self.post(kind="note", title="raced", content="theirs", created_at_utc=OLD, last_modified_at_utc=OLD)
        item = {"class": "MOVED", "copy": {"id": rid, "content": "mine"}, "fields": ["content"],
                "live": {"last_modified_at_utc": OLD}}
        self.req("PATCH", f"/entries/{rid}", {"content": "theirs, edited"})
        m.apply(m.API(f"http://127.0.0.1:{self.port}", *USER), [item])
        self.assertTrue(item["result"].startswith("failed: 412"), item["result"])
        self.assertEqual(self.req("GET", f"/entries/{rid}")[1]["content"], "theirs, edited")

    def test_refusals(self):
        live_copy = TMP / "copy-live.json"
        live_copy.write_text(json.dumps({"alt_slot": str(self.copy), "in_live_slot": "copy.db",
                                         "filtered_at": "2026-01-01T10:00:00Z", "swapped_at": "2026-01-01T11:00:00Z"}))
        p = self.run_script("--copy", str(self.copy), state=live_copy)
        self.assertEqual(p.returncode, 75)
        self.assertIn("live journal", p.stderr)
        p = self.run_script("--copy", str(self.copy), "--since", "2026-01-01 11:00:00", "--until", "2026-01-01 10:00:00")
        self.assertEqual(p.returncode, 2)
        p = self.run_script("--copy", str(TMP / "nothing.db"))
        self.assertEqual(p.returncode, 75)
        self.assertFalse((TMP / "nothing.db").exists(), "a missing copy is not created")


if __name__ == "__main__":
    unittest.main()
