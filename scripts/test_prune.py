#!/usr/bin/env python3
"""Tests for scripts/db-prune.py, the crew_inbox prune: the one hard delete.

    python3 scripts/test_prune.py           (~1s: a scratch database, a stand-in /health)
    python3 scripts/test_prune.py --real    (~30s more: a scratch server and the page)

The fast half runs the script as the timer does, on a scratch database
with the server's side tables, and checks that only the right rows go
(crew_inbox, done, untouched for seven days), their dependents with them,
that a dry run changes not one byte, that a younger, undone or other-kind
row stays, that a refusal (no /health, no file) writes nothing, and the
counts and prune.jsonl after, and that a side table added later (any
table with an entry_id column) is cleared with the rest.

--real is the web UI's side (ARCHITECTURE.md, "The count is the last
check"): a scratch server on a synthetic journal with old inbox rows, the
page loaded into its mirror in Chromium, the prune applied under it; the
open tab must catch up (one full load, the pruned rows gone, no error),
and a reload after must paint from the mirror and sync without another.
"""

import hashlib
import http.server
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import threading
import unittest

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "lcars-ui" / "test"))
import killclean  # noqa: E402 - its scratch goes when the run is killed

TMP = pathlib.Path(killclean.mkdtemp(prefix="prune-test-"))
SCRIPT = HERE / "db-prune.py"

# The tables as the server makes them (lcars_db.h, lcars_media.h,
# lcars_embed.h, lcars_caldav.h), the trigger included.
SCHEMA = """
CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT '', title TEXT, content TEXT,
  value_int INTEGER, value_float REAL, value_blob BLOB, done_bool INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
  created_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')),
  last_modified_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')),
  start_date TEXT DEFAULT '', end_date TEXT DEFAULT '');
CREATE TABLE entry_media (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, path TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
  created_at_utc TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE entry_embeddings (entry_id INTEGER PRIMARY KEY, model TEXT NOT NULL, source_modified TEXT NOT NULL,
  dim INTEGER NOT NULL, vec BLOB NOT NULL, embedded_at_utc TEXT NOT NULL);
CREATE TABLE caldav_tasks (entry_id INTEGER PRIMARY KEY, resource_name TEXT NOT NULL UNIQUE, uid TEXT NOT NULL,
  extra_ical TEXT, extra_vcal TEXT, sync_start TEXT, sync_end TEXT);
CREATE TABLE caldav_moves (seq INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, old_kind TEXT,
  old_name TEXT, at TEXT NOT NULL);
CREATE TRIGGER caldav_kind_moved AFTER UPDATE OF kind ON entries WHEN OLD.kind IS NOT NEW.kind BEGIN
  INSERT INTO caldav_moves (entry_id, old_kind, old_name, at) VALUES (OLD.id, OLD.kind,
  (SELECT resource_name FROM caldav_tasks WHERE entry_id = OLD.id), strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc'));
END;
"""


def ago(days):
    return f"strftime('%Y-%m-%d %H:%M:%S', 'now', '-{days} days')"


class Health(http.server.BaseHTTPRequestHandler):
    up = True

    def do_GET(self):  # noqa: N802
        self.send_response(200 if Health.up and self.path == "/health" else 503)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class Prune(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        Health.up = True
        self.dir = TMP / self._testMethodName
        self.dir.mkdir()
        self.db = self.dir / "lcars.db"
        self.state = self.dir / "state"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA)
        self.ids = {}

        def row(name, kind, done, days, deleted=0, stamp=None):
            cur = con.execute(
                f"INSERT INTO entries (kind, title, content, done_bool, deleted, created_at_utc, last_modified_at_utc)"
                f" VALUES (?, ?, 'x', ?, ?, {ago(days + 1)}, {stamp if stamp is not None else ago(days)})",
                (kind, name, done, deleted))
            self.ids[name] = cur.lastrowid
            return cur.lastrowid

        # go: done crew_inbox rows untouched for more than seven days
        row("old1", "crew_inbox", 1, 30)
        b = row("old2", "crew_inbox", 1, 8)
        row("old-deleted", "crew_inbox", 1, 10, deleted=1)
        # stay
        row("young", "crew_inbox", 1, 6)
        row("edge", "crew_inbox", 1, 6.9)
        row("undone", "crew_inbox", 0, 30)
        e = row("other-kind", "no1_log", 1, 30)
        row("other-inbox", "crew_inbox_x", 1, 30)
        m = row("with-media", "crew_inbox", 1, 30)
        row("no-stamp", "crew_inbox", 1, 30, stamp="''")
        for i in (b, e):
            con.execute("INSERT INTO entry_embeddings VALUES (?, 'm', 's', 1, x'00', 'now')", (i,))
            con.execute("INSERT INTO caldav_tasks VALUES (?, ?, 'u', '', '', '', '')", (i, f"r{i}"))
            con.execute("INSERT INTO caldav_moves (entry_id, old_kind, old_name, at) VALUES (?, 'k', 'n', 'now')",
                        (i,))
        con.execute("INSERT INTO entry_media (entry_id, path, created_at_utc) VALUES (?, 'p', 'now')", (m,))
        con.commit()
        con.close()
        self.go = {"old1", "old2", "old-deleted"}

    def run_prune(self, *args, db=None):
        env = dict(os.environ, LCARS_PRUNE_DB=str(db or self.db), LCARS_URL=self.url,
                   LCARS_ENG_STATE=str(self.state))
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True,
                              timeout=60)

    def titles(self):
        con = sqlite3.connect(self.db)
        try:
            return {r[0] for r in con.execute("SELECT title FROM entries")}
        finally:
            con.close()

    def count(self, table, where="1"):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]
        finally:
            con.close()

    def log(self):
        p = self.state / "prune.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def test_dry_run_changes_nothing(self):
        before, rows = self.digest(), self.titles()
        r = self.run_prune()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would remove 3 crew_inbox rows", r.stdout)
        self.assertIn("kept 1 with media", r.stdout)
        self.assertIn("entry_embeddings 1", r.stdout)
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.titles(), rows)
        self.assertFalse(any(p.name != "lcars.db" for p in self.dir.glob("lcars.db*")), "no journal or wal left")
        (rec,) = self.log()
        self.assertFalse(rec["apply"])
        self.assertEqual((rec["counted"], rec["removed"], rec["kept_media"]), (3, 0, 1))
        self.assertLess(rec["oldest"], rec["newest"])

    def test_apply_removes_only_the_right_rows(self):
        rows = self.titles()
        max_id = max(self.ids.values())
        r = self.run_prune("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed 3 crew_inbox rows", r.stdout)
        self.assertEqual(self.titles(), rows - self.go)
        # their dependents went, the other kind's stayed
        b, e = self.ids["old2"], self.ids["other-kind"]
        for t in ("entry_embeddings", "caldav_tasks", "caldav_moves"):
            self.assertEqual(self.count(t, f"entry_id = {b}"), 0, t)
            self.assertEqual(self.count(t, f"entry_id = {e}"), 1, t)
        self.assertEqual(self.count("entry_media"), 1)
        # a delete does not fire the kind trigger
        self.assertEqual(self.count("caldav_moves"), 1)
        (rec,) = self.log()
        self.assertTrue(rec["apply"])
        self.assertEqual((rec["counted"], rec["removed"]), (3, 3))
        self.assertEqual(rec["dependents"], {"entry_embeddings": 1, "caldav_tasks": 1, "caldav_moves": 1})
        # AUTOINCREMENT: a pruned id is never handed out again, so the
        # page's mirror's maxId stays true
        con = sqlite3.connect(self.db)
        new = con.execute("INSERT INTO entries (kind) VALUES ('captain_log')").lastrowid
        con.commit()
        con.close()
        self.assertGreater(new, max_id)
        # a second run finds nothing more
        r = self.run_prune("--apply")
        self.assertIn("removed 0 crew_inbox rows", r.stdout)
        self.assertEqual(self.titles(), (rows - self.go) | {None})

    def test_refuses_without_health(self):
        Health.up = False
        before = self.digest()
        r = self.run_prune("--apply")
        self.assertEqual(r.returncode, 75)
        self.assertIn("/health", r.stderr)
        self.assertEqual(self.digest(), before)
        (rec,) = self.log()
        self.assertIn("refused", rec)
        self.assertEqual(rec["removed"], 0)

    def test_refuses_a_path_not_a_file(self):
        for p in (self.dir / "missing.db", self.dir):
            r = self.run_prune("--apply", db=p)
            self.assertEqual(r.returncode, 75, p)
            self.assertIn("not a file", r.stderr)
        self.assertFalse((self.dir / "missing.db").exists(), "sqlite must not create it")
        self.assertEqual(len(self.log()), 2)

    def test_a_new_side_table_is_covered(self):
        """A table added later with an entry_id column is found in
        sqlite_master, as db-filter.sh finds them; one without is left."""
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE future_side (entry_id INTEGER, note TEXT)")
        con.execute("CREATE TABLE unrelated (id INTEGER, note TEXT)")
        for name in ("old1", "young", "other-kind"):
            con.execute("INSERT INTO future_side VALUES (?, 'x')", (self.ids[name],))
        con.execute("INSERT INTO unrelated VALUES (?, 'x')", (self.ids["old1"],))
        con.commit()
        con.close()
        r = self.run_prune("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.count("future_side", f"entry_id = {self.ids['old1']}"), 0)
        self.assertEqual(self.count("future_side"), 2)
        self.assertEqual(self.count("unrelated"), 1)
        self.assertEqual(self.log()[0]["dependents"]["future_side"], 1)

def real():
    """The page's side: see the module's head."""
    from playwright.sync_api import sync_playwright
    import offline as rig  # the scratch build and server

    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-prune-", dir=os.path.expanduser("~/.cache")))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        rig.build(binary)
    db = tmp / "lcars.db"
    subprocess.run([sys.executable, str(REPO / "lcars-ui/test/synth.py"), str(db), "1500"], check=True,
                   capture_output=True)
    con = sqlite3.connect(db)
    for i in range(120):   # 80 to go, 25 too young, 15 not done
        go, young = i < 80, 80 <= i < 105
        con.execute(f"INSERT INTO entries (kind, title, content, done_bool, deleted, created_at_utc,"
                    f" last_modified_at_utc) VALUES ('crew_inbox', ?, 'say', ?, 0, {ago(20 if not young else 2)},"
                    f" {ago(10 if not young else 1)})", (f"to obrien: order {i}", 0 if i >= 105 else 1))
    con.commit()
    con.close()
    os.environ["LCARS_UI_DIR"] = str(REPO / "lcars-ui")
    srv = rig.Server(binary, tmp)
    check = rig.check
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.set_default_timeout(30000)
            cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
            ctx.add_init_script(f"if (!localStorage.getItem('lcars.cfg')) localStorage.setItem('lcars.cfg', "
                                f"{json.dumps(json.dumps(cfg))});")
            page = ctx.new_page()
            errs, loads = [], []
            page.on("pageerror", lambda e: errs.append(str(e)))
            # a full load is a /dump (or the first page) with no
            # modified_since or min_id: what deltaSync asks is never one
            page.on("request", lambda r: loads.append(r.url) if (
                "/dump?" in r.url or "/entries?" in r.url) and "deleted=all" in r.url
                and "modified_since" not in r.url and "min_id" not in r.url and "kind=" not in r.url else None)

            def held():
                return page.evaluate("st.all.length")

            def count():
                return srv.json("GET", "/stats?deleted=all")["count"]

            def settled(n):
                page.wait_for_function(f"!st.loading && st.all.length === {n} && !!mirror.mark")

            n0 = count()
            page.goto(srv.base + "/ui/", wait_until="domcontentloaded")
            settled(n0)
            page.wait_for_timeout(1500)   # the mirror written
            check(held() == n0, f"the page holds the journal ({held()} of {n0})")
            loads.clear()
            env = dict(os.environ, LCARS_PRUNE_DB=str(db), LCARS_URL=srv.base, LCARS_ENG_STATE=str(tmp / "state"))
            r = subprocess.run([sys.executable, str(SCRIPT), "--apply"], env=env, capture_output=True, text=True)
            check(r.returncode == 0 and "removed 80 crew_inbox rows" in r.stdout, f"the prune: {r.stdout.strip()}")
            n1 = count()
            check(n1 == n0 - 80, f"/stats counts {n1}, {n0} - 80")
            # the open tab hears of it through /events and catches up
            try:
                settled(n1)
                ok = True
            except Exception:  # noqa: BLE001 - reported as the check
                ok = False
            check(ok, f"the open tab catches up by itself ({held()} held, {n1} on the server)")
            check(len(loads) >= 1, f"... by a full load ({len(loads)} requests)")
            gone = page.evaluate("st.all.filter(e => e.kind === 'crew_inbox' && e.done_bool && "
                                 "/order ([0-9]|[1-7][0-9])$/.test(e.title)).length")
            check(gone == 0, f"no pruned row held ({gone})")
            page.wait_for_timeout(1500)   # the replaced mirror written
            loads.clear()
            page.reload(wait_until="domcontentloaded")
            settled(n1)
            page.wait_for_timeout(2000)
            check(not loads, f"a reload syncs from the mirror, no full load ({loads[:2]})")
            check(held() == n1, f"and holds {held()} of {n1}")
            check(not errs, "no page error" + ("" if not errs else ": " + errs[0]))
            browser.close()
    finally:
        srv.stop()
    print(f"\nprune --real: {rig.checks[0]} checks, {len(rig.fails)} failures")
    if rig.fails:
        print(f"server log kept in {tmp}")
        return False
    shutil.rmtree(tmp, ignore_errors=True)
    return True


if __name__ == "__main__":
    want_real = "--real" in sys.argv
    sys.argv = [a for a in sys.argv if a != "--real"]
    res = unittest.main(exit=False, verbosity=1).result
    ok = res.wasSuccessful() and (real() if want_real else True)
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if ok else 1)
