#!/usr/bin/env python3
"""Unit tests for the box's housekeeping (scripts/housekeeping.py, the
crew's `housekeeping` role): what it deletes, what its guard never lets it
touch, the dry run, the thresholds and the notice for Number One. Every
path is in a scratch HOME and /tmp; a real process stands in for one that
holds a directory. Linux only.

    python3 scripts/test_housekeeping.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402
import housekeeping as H  # noqa: E402

DAY = 86400


def touch(path, data=b"x" * 4096, age=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


def age_tree(path, age):
    t = time.time() - age
    for top, dirs, files in os.walk(path):
        for n in dirs + files:
            os.utime(os.path.join(top, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t))


class Box(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="housekeeping-test-")
        self.home = os.path.join(self.tmp, "home")
        self.t = os.path.join(self.tmp, "tmp")
        self.media = os.path.join(self.tmp, "nas")
        self.state = os.path.join(self.home, ".local/state/lcars-eng")
        for d in (self.home, self.t, self.media, os.path.join(self.state, "logs")):
            os.makedirs(d)
        self.procs = []
        env = {"LCARS_MEDIA_ROOT": self.media, "LCARS_ENG_STATE": self.state}
        self.ps = [mock.patch.object(H, "HOME", self.home), mock.patch.object(H, "TMP", self.t),
                   mock.patch.object(E, "TEST_TMP_ROOTS", [self.t]),
                   mock.patch.object(E, "CLAUDE_TMP", os.path.join(self.t, "claude-none")),
                   mock.patch.dict(os.environ, env)]
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scratch(self, name, age=2 * DAY, files=("a.txt",)):
        d = os.path.join(self.t, name)
        for f in files:
            touch(os.path.join(d, f))
        age_tree(d, age)
        return d

    def captain(self):
        """The never-touch list, each holding a file, made old."""
        made = [
            touch(os.path.join(self.home, "lcars", "lcars.db")),
            touch(os.path.join(self.home, "lcars", "lcars_backups", "hourly", "x.db.gz")),
            touch(os.path.join(self.home, "lcars-personal.db")),
            touch(os.path.join(self.home, "Documents", "LogSeqCloud2", "journals", "2026_10_22.md")),
            touch(os.path.join(self.home, "lcars-landing-media", "explainer.mp4")),
            touch(os.path.join(self.home, "blog-media", "post.png")),
            touch(os.path.join(self.media, "media", "2026", "photo.jpg")),
            touch(os.path.join(self.home, "lcars-eng", "wt", ".git"), b"gitdir: x"),
            touch(os.path.join(self.home, "lcars-eng", "wt", "build", "lcars.o")),
            touch(os.path.join(self.home, "lcars-public", "README.md")),
        ]
        for p in made:
            age_tree(os.path.dirname(p), 400 * DAY)
        return made


class Guard(Box):
    def test_never_touches_the_captains_data(self):
        made = self.captain()
        p = H.paths()
        held = set()
        targets = set(made)
        for f in made:
            d = os.path.dirname(f)
            while d.startswith(self.home + "/") or d.startswith(self.media + "/"):
                targets.add(d)
                d = os.path.dirname(d)
        targets |= {self.home, self.media, self.t, "/", os.path.join(self.home, "lcars-eng", "wt")}
        for t in sorted(targets):
            self.assertTrue(H.refusal(t, held, p["protected"]), t)
        # and offered all of them as candidates, the sweep deletes none
        with mock.patch.object(H, "reap_known", lambda: [(t, "test") for t in sorted(targets)]):
            r = H.sweep(dry=False)
        self.assertEqual(r["freed"], [])
        for f in made:
            self.assertTrue(os.path.exists(f), f)

    def test_media_root_from_env_file(self):
        os.environ.pop("LCARS_MEDIA_ROOT")
        touch(os.path.join(self.home, ".env"), f"export LCARS_MEDIA_ROOT='{self.media}'\n".encode())
        self.assertIn(self.media, H.paths()["protected"])

    def test_a_tree_with_a_database_symlink_or_git(self):
        db = self.scratch("lcars-off-ab12", files=("lcars.db", "x"))
        wal = self.scratch("lcars-btn-cd34", files=("j/lcars.db-wal",))
        git = self.scratch("lcars-rec-ef56", files=(".git/HEAD",))
        target = self.scratch("lcars-api-real", age=0)
        link = os.path.join(self.t, "lcars-api-gh78")
        os.symlink(target, link)
        held, prot = set(), H.paths()["protected"]
        self.assertEqual(H.refusal(db, held, prot), "holds a database file")
        self.assertEqual(H.refusal(wal, held, prot), "holds a database file")
        self.assertIn("git checkout", H.refusal(git, held, prot))
        self.assertEqual(H.refusal(link, held, prot), "a symlink")
        self.assertEqual(H.refusal("relative/x", held, prot), "not an absolute path")

    def test_a_directory_a_process_holds(self):
        d = self.scratch("lcars-perf-base-busy1", files=("a",))
        p = subprocess.Popen(["sleep", "60"], cwd=d)
        self.procs.append(p)
        time.sleep(0.1)
        r = H.sweep(dry=False)
        self.assertIn((d, "in use by a running process"), r["kept"])
        self.assertTrue(os.path.isdir(d))
        p.kill()
        p.wait()
        self.procs.clear()
        r = H.sweep(dry=False)
        self.assertFalse(os.path.exists(d))


class Sweep(Box):
    def test_dry_run_deletes_nothing(self):
        old = self.scratch("lcars-off-dry1")
        log = touch(os.path.join(self.state, "logs", "deploy-20260101-000000.log"), age=60 * DAY)
        r = H.sweep(dry=True)
        self.assertEqual({p for p, _, _ in r["freed"]}, {old, log})
        self.assertGreater(r["bytes"], 0)
        self.assertTrue(os.path.isdir(old) and os.path.exists(log))
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(H, "worktree_outputs", lambda p: {}):
            H.main(["--dry-run"])
        self.assertIn("Would delete", out.getvalue())
        self.assertTrue(os.path.isdir(old) and os.path.exists(log))

    def test_reaps_known_old_scratch_only(self):
        old = self.scratch("lcars-off-old1")
        chat = self.scratch("lcars-media-chat-x_1y")
        young = self.scratch("lcars-off-new1", age=3600)
        stranger = self.scratch("somebodys-files", age=30 * DAY)
        r = H.sweep(dry=False)
        self.assertFalse(os.path.exists(old) or os.path.exists(chat))
        self.assertTrue(os.path.isdir(young) and os.path.isdir(stranger))
        self.assertEqual(len(r["freed"]), 2)

    def test_logs_past_their_keep(self):
        logs = os.path.join(self.state, "logs")
        dold = touch(os.path.join(logs, "deploy-20260101-000000.log"), age=(H.DEPLOY_LOG_KEEP_DAYS + 1) * DAY)
        dnew = touch(os.path.join(logs, "deploy-20261020-000000.log"), age=(H.DEPLOY_LOG_KEEP_DAYS - 1) * DAY)
        jold = touch(os.path.join(logs, "job-kim-c32-20260101-000000.log"), age=(E.JOB_KEEP_DAYS + 1) * DAY)
        jnew = touch(os.path.join(logs, "job-kim-c32-20261021-000000.log"), age=DAY)
        other = touch(os.path.join(logs, "refresh.log"), age=400 * DAY)
        H.sweep(dry=False)
        self.assertFalse(os.path.exists(dold) or os.path.exists(jold))
        self.assertTrue(all(os.path.exists(x) for x in (dnew, jnew, other)))

    def playwright(self, names, need):
        root = os.path.join(self.home, ".cache", "ms-playwright")
        for n in names:
            touch(os.path.join(root, n, "INSTALLATION_COMPLETE"))
            age_tree(os.path.join(root, n), 30 * DAY)
        pkg = os.path.join(self.tmp, "site-packages", "playwright", "driver", "package")
        touch(os.path.join(pkg, "browsers.json"), json.dumps(
            {"browsers": [{"name": n.rsplit("-", 1)[0].replace("_", "-"), "revision": n.rsplit("-", 1)[1]}
                          for n in need]}).encode())
        touch(os.path.join(root, ".links", "abc"), pkg.encode())
        return root

    def test_stale_playwright_builds(self):
        root = self.playwright(["chromium-1200", "chromium-1243", "chromium_headless_shell-1243",
                                "chromium_headless_shell-1100", "firefox-1500", "webkit-2000", "webkit-2359"],
                               ["chromium-1243", "chromium-headless-shell-1243", "webkit-2000"])
        H.sweep(dry=False)
        self.assertEqual(sorted(os.listdir(root)), sorted([".links", "chromium-1243", "chromium_headless_shell-1243",
                                                           "firefox-1500", "webkit-2000", "webkit-2359"]))

    def test_playwright_left_alone_when_a_link_is_unreadable(self):
        root = self.playwright(["chromium-1200", "chromium-1243"], ["chromium-1243"])
        with open(os.path.join(root, ".links", "abc")) as f:
            pkg = f.read()
        os.remove(os.path.join(pkg, "browsers.json"))
        touch(os.path.join(pkg, "browsers.json"), b"not json")
        H.sweep(dry=False)
        self.assertIn("chromium-1200", os.listdir(root))

    def test_npx_and_crash_dumps(self):
        npx = os.path.join(self.home, ".npm", "_npx")
        old = os.path.dirname(touch(os.path.join(npx, "aaaa", "package.json")))
        new = os.path.dirname(touch(os.path.join(npx, "bbbb", "package.json")))
        age_tree(old, (H.NPX_KEEP_DAYS + 1) * DAY)
        core = touch(os.path.join(self.home, "core.1234"), age=2 * DAY)
        fresh = touch(os.path.join(self.t, "core"), age=60)
        notcore = touch(os.path.join(self.home, "core.txt"), age=30 * DAY)
        H.sweep(dry=False)
        self.assertFalse(os.path.exists(old) or os.path.exists(core))
        self.assertTrue(all(os.path.exists(x) for x in (new, fresh, notcore)))


class Scratchpads(Box):
    """Claude sessions' scratch, through reap_scratch: an idle engineer's
    session two days untouched, its shots deleted and its notes moved to
    research, both counted and said in the report."""

    def test_an_idle_engineers_scratch_is_split(self):
        ct = os.path.join(self.t, "claude-1")
        sid = "0b8e3c2a-1d4f-4e5a-9b6c-000000000001"
        d = os.path.join(ct, E.claude_slug(os.path.join(self.home, "lcars-eng", "geordi-c1")), sid)
        shot = touch(os.path.join(d, "scratchpad", "shots", "a.png"), age=2 * DAY)
        note = touch(os.path.join(d, "scratchpad", "plan.md"), b"# plan", age=2 * DAY)
        age_tree(d, 2 * DAY)
        with open(os.path.join(self.state, "geordi-c1.json"), "w") as f:
            json.dump({"name": "geordi-c1", "session": sid}, f)
        with mock.patch.object(E, "CLAUDE_TMP", ct), mock.patch.object(E, "STATE", self.state), \
                mock.patch.object(E, "ROOT", os.path.join(self.home, "lcars-eng")), \
                mock.patch.object(E, "live_sessions", lambda: (set(), set(), set())), \
                mock.patch.object(E, "job_texts", lambda: []):
            r = H.sweep(dry=True)
            self.assertTrue(os.path.exists(shot) and os.path.exists(note))
            self.assertEqual([p for p, _, _ in r["freed"]], [d])
            self.assertIn("1 files moved to research", r["freed"][0][2])
            r = H.sweep(dry=False)
            text = H.report({"dry": False, "sweep": r, "m": H.measure(H.paths(), []), "alarms": []})
        self.assertFalse(os.path.exists(shot) or os.path.exists(note))
        kept = os.path.join(self.state, "research", "geordi-c1", "scratch-" + time.strftime("%Y-%m-%d"), sid,
                            "scratchpad", "plan.md")
        with open(kept) as f:
            self.assertEqual(f.read(), "# plan")
        self.assertIn("Moved 1 files", text)
        self.assertIn("research/{geordi-c1}/scratch-<date>/", text)


class Measure(Box):
    def test_report_and_unknown_tmp(self):
        self.scratch("lcars-off-k1", age=60)
        touch(os.path.join(self.t, "mystery", "blob"), b"y" * (2 << 20))
        with mock.patch.object(H, "TMP_UNKNOWN_HIGH_MB", 1):
            r = H.run(dry=True)
        kinds = {os.path.basename(e["path"]): e["kind"] for e in r["m"]["tmp"]["entries"]}
        self.assertEqual(kinds["mystery"], "unknown")
        self.assertEqual(kinds["lcars-off-k1"], "test scratch (reap's)")
        self.assertTrue(any("unknown files" in a and "mystery" in a for a in r["alarms"]))
        self.assertTrue(os.path.exists(os.path.join(self.t, "mystery", "blob")))
        body = H.report(r)
        self.assertIn("/tmp", body)
        self.assertIn("memory", body)

    def test_thresholds(self):
        base = {"mem": {"available_mb": 4000, "total_mb": 8000, "swap_pct": 10, "swap_used_mb": 100,
                        "swap_total_mb": 1000},
                "swap": {"cgroups": [("blog-draft.service", 50)], "processes": [], "process_mb": 50},
                "load": (0.1, 0.1, 0.1), "cpus": 4, "disks": [{"path": "/", "pct": 20, "free_mb": 80000}],
                "tmp": {"unknown_mb": 0, "entries": []}}
        self.assertEqual(H.alarms(base), [])
        low = json.loads(json.dumps(base))
        low["mem"].update(available_mb=1500, swap_pct=70, swap_used_mb=700)
        low["disks"][0]["pct"] = 85
        a = H.alarms(low)
        self.assertEqual(len(a), 3)
        self.assertIn("tmpfs and shared memory 650MB", a[1])
        busy = dict(low, load=(3.5, 1, 1))   # memory low under load is the work's
        self.assertEqual(len(H.alarms(busy)), 2)


class Crew(Box):
    def test_notice_to_number_one_past_a_threshold(self):
        import crew as C
        fake = {"dry": False, "sweep": {"freed": [], "kept": [], "bytes": 0},
                "m": {"mem": {"available_mb": 1500}}, "alarms": ["swap 70% used"]}
        with mock.patch.object(H, "run", lambda dry: fake), mock.patch.object(H, "report", lambda r: "body"):
            title, body, urgent, extra = C.run_housekeeping({}, False)
        self.assertIsNone(urgent)
        self.assertEqual(extra["value_int"], 1500)
        self.assertIn("swap 70% used", extra["no1"])
        sent, posted = [], []
        fm = {"posts": "housekeeping", "title": "Housekeeping"}
        rec = {"role": "housekeeping"}
        with mock.patch.object(C.T, "post", lambda *a, **k: posted.append(a) or 41), \
                mock.patch.object(E, "no1_send", lambda text, **k: sent.append(text) or True), \
                mock.patch.object(C, "log_run", lambda r: None), redirect_stdout(io.StringIO()):
            C.finish(fm, rec, title, body, urgent, {"secs": 1}, False, extra)
        self.assertEqual(sent, ["[housekeeping] The box is past a threshold: swap 70% used. Report #41."])
        sent.clear()
        out = io.StringIO()
        with mock.patch.object(E, "no1_send", lambda text, **k: sent.append(text)), \
                mock.patch.object(C, "log_run", lambda r: None), redirect_stdout(out):
            C.finish(fm, dict(rec), title, body, urgent, {"secs": 1}, True, extra)
        self.assertEqual(sent, [])
        self.assertIn("would tell Number One", out.getvalue())

    def test_quiet_run_tells_nobody_and_dry_returns_three(self):
        import crew as C
        fake = {"dry": True, "sweep": {"freed": [], "kept": [], "bytes": 0},
                "m": {"mem": {"available_mb": 4000}}, "alarms": []}
        with mock.patch.object(H, "run", lambda dry: dict(fake, dry=dry)), \
                mock.patch.object(H, "report", lambda r: "body"):
            self.assertEqual(len(C.run_housekeeping({}, True)), 3)
            self.assertNotIn("no1", C.run_housekeeping({}, False)[3])

    def test_role_and_its_timer(self):
        import crew as C
        fm, _ = C.load("housekeeping")
        self.assertEqual((fm["kind"], fm["script"], fm["schedule"]), ("script", "housekeeping", "*-*-* 00,06,12,18:00"))
        self.assertEqual(int(fm["min_free_mb"]), 0)


if __name__ == "__main__":
    unittest.main()
