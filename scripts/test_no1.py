#!/usr/bin/env python3
"""Unit tests for scripts/no1.py's `journal`: which lcars-cli it runs, with
what login, and that the real lcars-cli has no --db at all; and the refresh
(engineer.py's refresh-go): a Handover log marks it, the Stop hook's turn then clears, each step
logged; one relaunched without its hooks (herdr's restore) is restarted first. A stub lcars-cli (a shell script that
records its argv and login) stands in, in a temp live checkout laid out like
the VPS's - lcars-cli/ a directory with the binary inside it, which is what
the old lookup handed to exec (PermissionError). Nothing outside the temp
directory is touched, and no server is asked (the real lcars-cli is built
to the temp directory and only refuses its arguments). And `no1.py sync`
(engineer.py's sync_no1) on a scratch repo with a Number One worktree: a
clean fast-forward, a dirty worktree, commits of its own or another branch
refused; and the deploy's call to it, whose failure is a line in the
outcome, never a failed deploy.

    python3 scripts/test_no1.py
"""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import engineer as E  # noqa: E402
import no1  # noqa: E402

STUB = """#!/bin/sh
printf '%s\\n' "$0" "$LCARS_URL" "$LCARS_AUTH_USER" "$LCARS_AUTH_PASS" "$@" > "{out}"
"""


class Journal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-test-")
        self.live = os.path.join(self.tmp, "lcars")
        self.state = os.path.join(self.tmp, "state")
        self.out = os.path.join(self.tmp, "ran")
        os.makedirs(os.path.join(self.live, "lcars-cli"))
        os.makedirs(self.state)
        env = os.path.join(self.tmp, ".env")
        with open(env, "w") as f:
            f.write("export LCARS_CREW_USER=crew\nLCARS_NO1_USER=no1\nLCARS_NO1_PASS='pw'\n")
        self.ps = [mock.patch.object(E, "LIVE", self.live), mock.patch.object(E, "STATE", self.state),
                   mock.patch.object(no1.T, "ENV_FILE", env),
                   mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "LCARS_CLI": "",
                                                "LCARS_URL": "http://127.0.0.1:9"})]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp)

    def stub(self, path):
        with open(path, "w") as f:
            f.write(STUB.format(out=self.out))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def run_journal(self, *a):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code, _ = no1.journal(list(a))
        except SystemExit as e:
            return e.code, json.loads(buf.getvalue())
        return code, None

    def ran(self):
        with open(self.out) as f:
            return f.read().splitlines()

    def test_binary_inside_the_directory(self):
        cli = self.stub(os.path.join(self.live, "lcars-cli", "lcars-cli"))
        code, err = self.run_journal("kinds")
        self.assertEqual((code, err), (0, None))
        self.assertEqual(self.ran(), [cli, "http://127.0.0.1:9", "no1", "pw", "kinds"])

    def test_directory_alone_is_not_built(self):
        code, err = self.run_journal("kinds")
        self.assertEqual(code, 1)
        self.assertIn("not built", err["error"])
        self.assertFalse(os.path.exists(self.out))

    def test_make_output_file(self):
        os.rmdir(os.path.join(self.live, "lcars-cli"))
        cli = self.stub(os.path.join(self.live, "lcars-cli"))
        self.assertEqual(self.run_journal("list", "-n", "3"), (0, None))
        self.assertEqual(self.ran()[0], cli)
        self.assertEqual(self.ran()[4:], ["list", "-n", "3"])

    def test_cli_has_no_db(self):
        # lcars-cli is HTTP only (0.177.0): --db is not refused by no1.py
        # any more because there is none to refuse. A real build says so.
        plan = subprocess.run(["make", "-n", "-B", "lcars-cli"], cwd=REPO,
                              capture_output=True, text=True).stdout
        line = next(l for l in plan.splitlines() if " -o lcars-cli " in l)
        cli = os.path.join(self.tmp, "real-cli")
        subprocess.run(line.replace(" -o lcars-cli ", f" -o {cli} ", 1), shell=True,
                       cwd=REPO, check=True)
        for a in (["--db", "kinds"], ["--db-path", "/x.db", "kinds"]):
            r = subprocess.run([cli, *a], capture_output=True, text=True,
                               env=dict(os.environ, LCARS_URL="http://127.0.0.1:9"))
            self.assertEqual(r.returncode, 2)
            self.assertIn("unknown option", r.stderr)
        r = subprocess.run([cli, "--help"], capture_output=True, text=True)
        self.assertNotIn("--db", r.stdout)

class Refresh(unittest.TestCase):
    """A [refresh] clears Number One once a Handover entry is written and
    that turn ends, and not before: herdr, the server and the clear are
    stand-ins, the engineer's record a temp state directory."""

    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="no1-refresh-")
        self.sent, self.cleared = [], []
        self.ps = [mock.patch.object(E, "STATE", self.state),
                   mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}),
                   mock.patch.object(E, "herdr", return_value=({}, "")),
                   mock.patch.object(E, "submit_if_left"),
                   mock.patch.object(E, "no1_send", side_effect=self.sent.append),
                   mock.patch.object(E, "clear_session",
                                     side_effect=lambda n, label: (self.cleared.append(label) or
                                                                   (0, {"ok": True, "cleared": True}))),
                   mock.patch.object(E.time, "sleep"),
                   mock.patch.object(no1, "http", return_value=(201, "{}"))]
        for p in self.ps:
            p.start()
        E.save(E.NO1, {"name": E.NO1, "session": "s1", "task": "the sweep"})

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.state)

    def call(self, fn, *a):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                fn(*a)
            except SystemExit:
                pass
        return json.loads(buf.getvalue() or "null")

    def log(self, title):
        with contextlib.redirect_stdout(io.StringIO()):
            no1.main(["log", title, "text"])

    def test_a_handover_then_the_turn_s_end_clears(self):
        self.assertTrue(self.call(E.cmd_refresh, E.NO1)["pending"])
        self.log("Routine note")  # a turn already under way logs something else
        self.assertEqual(self.call(E.cmd_refresh_go, E.NO1), {"ok": True, "cleared": False})
        self.log("Handover")
        self.assertEqual(self.call(E.cmd_refresh_go, E.NO1), {"ok": True, "cleared": True})
        self.assertEqual(self.cleared, ["the sweep"])
        self.assertIn("Read your log", self.sent[-1])
        self.assertNotIn("refresh", E.load(E.NO1))

    def test_the_stop_hook_spawns_the_clear_only_once_noted(self):
        self.call(E.cmd_refresh, E.NO1)
        with mock.patch.object(E, "spawn") as sp, mock.patch("sys.stdin", io.StringIO("{}")):
            self.call(E.cmd_hook, "turn-ended", E.NO1)
            self.assertFalse(sp.called)
        self.log("Handover")
        with mock.patch.object(E, "spawn", return_value="unit") as sp, mock.patch("sys.stdin", io.StringIO("{}")):
            self.call(E.cmd_hook, "turn-ended", E.NO1)
            sp.assert_called_once_with("refresh-go", E.NO1)
        self.call(E.cmd_refresh_go, E.NO1)
        # each step leaves its line, so a stuck refresh shows how far it got
        steps = ["refresh asked of session s1", "turn-ended: no handover noted yet", "handover written",
                 "turn-ended: handover noted, refresh-go started (unit)", "refresh-go: Number One idle",
                 "refresh-go: cleared"]
        with open(os.path.join(self.state, "logs", "refresh.log")) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), len(steps), lines)
        for line, step in zip(lines, steps):
            self.assertIn(step, line)

    def test_a_number_one_relaunched_bare_is_restarted_before_the_refresh(self):
        # herdr's restore relaunches it without --settings: no Stop hook, so
        # a refresh asked of it would never clear (0.191.2)
        with mock.patch.object(E, "launched_bare", return_value=True), \
                mock.patch.object(E, "engineer_tab", return_value="w2:t1"), \
                mock.patch.object(E, "no1_wake", return_value=True) as wake:
            self.assertTrue(self.call(E.cmd_refresh, E.NO1)["pending"])
            E.herdr.assert_any_call("tab", "close", "w2:t1", timeout=15)
            wake.assert_called_once_with()
            E.herdr.reset_mock()
            E.save(E.NO1, {"name": E.NO1, "session": "s1"})
            # mid-turn it is not cut short: refused, and nothing pending
            E.agent_info.return_value = {"agent_status": "working"}
            self.assertIn("mid-turn", self.call(E.cmd_refresh, E.NO1)["error"])
            self.assertNotIn("refresh", E.load(E.NO1))
            self.assertFalse(E.herdr.called)
        with open(os.path.join(self.state, "logs", "refresh.log")) as f:
            self.assertIn("refused", f.read())

    def test_the_reap_restarts_one_relaunched_bare_once_idle(self):
        E.save("ada", {"name": "ada", "session": "s2"})
        status = {E.NO1: "done", "ada": "working"}
        with mock.patch.object(E, "agent_info", side_effect=lambda n: {"agent_status": status[n], "pane_id": n}), \
                mock.patch.object(E, "launched_bare", return_value=True), \
                mock.patch.object(E, "engineer_tab", side_effect=lambda n: "tab-" + n), \
                mock.patch.object(E, "deploy_state", return_value={}), \
                mock.patch.object(E, "reap_scratch", return_value=([], 0)), \
                mock.patch.object(E, "reap_test_tmp", return_value=([], 0)), \
                mock.patch.object(E, "reap_test_servers", return_value=[]), \
                mock.patch.object(E, "no1_answers", return_value=[]), \
                mock.patch.object(E, "seat_on", return_value=False):
            got = self.call(E.cmd_reap)
        self.assertEqual(got["relaunched"], [E.NO1])  # ada is mid-turn: left alone
        self.assertEqual(got["kept"], ["ada"])
        E.herdr.assert_called_once_with("tab", "close", "tab-" + E.NO1, timeout=15)


    def test_a_lapsed_refresh_is_not_noted(self):
        st = E.load(E.NO1)
        st["refresh"] = {"at": int(E.time.time()) - E.REFRESH_WAIT_SECONDS - 1}
        E.save(E.NO1, st)
        self.log("Handover")
        self.assertNotIn("noted", E.load(E.NO1)["refresh"])
        self.assertTrue(self.call(E.cmd_refresh, E.NO1)["pending"])  # a new one may start


class Bare(unittest.TestCase):
    """launched_bare against real processes: one named claude in the pane,
    started as herdr's restore does (no --settings) and as cmd_start does."""

    def claude(self, pane, *args):
        p = subprocess.Popen(["bash", "-c", 'exec -a claude python3 -c "import time; time.sleep(30)" "$@"', "-", *args],
                             env=dict(os.environ, HERDR_PANE_ID=pane))
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        for _ in range(100):  # until bash has exec'd
            with open(f"/proc/{p.pid}/cmdline", "rb") as f:
                if f.read().startswith(b"claude\0"):
                    return p
            E.time.sleep(0.05)
        self.fail("no claude process")

    def test_a_bare_resume_is_told_from_a_start_with_settings(self):
        pane = f"test:{os.getpid()}"
        self.claude(pane + "a", "--resume", "x")
        self.claude(pane + "b", "--settings", "/s.json", "--resume", "x")
        self.assertTrue(E.launched_bare({"pane_id": pane + "a"}))
        self.assertFalse(E.launched_bare({"pane_id": pane + "b"}))
        self.assertIn("--resume", E.claude_argv({"pane_id": pane + "a"}))
        # no such pane, or no pane at all: not known to be bare
        self.assertFalse(E.launched_bare({"pane_id": pane + "c"}))
        self.assertFalse(E.launched_bare({}))


class Report(unittest.TestCase):
    """`no1.py report`: the file published by report.py into a temp media
    root, then its link logged as a no1_log entry over Number One's login
    (http mocked); refused, with no entry, when the root is not mounted."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-test-")
        self.root = os.path.join(self.tmp, "root")
        self.src = os.path.join(self.tmp, "brief.html")
        with open(self.src, "w") as f:
            f.write("<p>hi</p>")
        self.posts = []
        self.ps = [mock.patch.dict(os.environ, {"LCARS_MEDIA_ROOT": self.root,
                                                "LCARS_REPORT_BASE": "https://box.example"}),
                   mock.patch.object(no1, "http", self.http)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp)

    def http(self, method, path, body=None, timeout=60):
        self.posts.append((method, path, body))
        return 200, json.dumps({"id": 42})

    def run_report(self, *a):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                code = no1.main(["report", *a])
            except SystemExit as e:
                code = e.code
        return code, json.loads(out.getvalue())

    def test_publishes_and_logs_the_link(self):
        os.makedirs(os.path.join(self.root, "media"))
        code, j = self.run_report(self.src, "Weekly brief", "for Monday")
        self.assertEqual(code, 0)
        self.assertTrue(j["url"].startswith("https://box.example/media/reports/"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, j["path"])))
        self.assertEqual(j["entry_id"], 42)
        [(method, path, body)] = self.posts
        self.assertEqual((method, path, body["kind"]), ("POST", "/entries", "no1_log"))
        self.assertEqual(body["title"], "Report: Weekly brief")
        self.assertIn("[Weekly brief](" + j["url"] + ")", body["content"])
        self.assertIn("for Monday", body["content"])

    def test_unmounted_is_refused_and_nothing_logged(self):
        code, j = self.run_report(self.src, "Weekly brief")
        self.assertEqual(code, 1)
        self.assertIn("mounted", j["error"])
        self.assertEqual(self.posts, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "media")))

    def test_wants_a_title(self):
        code, j = self.run_report(self.src)
        self.assertEqual(code, 2)
        self.assertEqual(self.posts, [])


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Sync(unittest.TestCase):
    """A scratch live repo on deb and a worktree for Number One on
    eng/number-one under a scratch ROOT, as on the VPS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-test-")
        self.live, root = os.path.join(self.tmp, "lcars"), os.path.join(self.tmp, "eng")
        self.n1 = os.path.join(root, E.NO1)
        os.makedirs(self.live)
        sh("git", "init", "-q", "-b", "deb", cwd=self.live)
        sh("git", "config", "user.email", "t@t", cwd=self.live)
        sh("git", "config", "user.name", "t", cwd=self.live)
        self.base = self.commit(self.live, "a")
        sh("git", "worktree", "add", "-q", "-b", "eng/" + E.NO1, self.n1, cwd=self.live)
        self.steps = []
        self.ps = [mock.patch.object(E, "LIVE", self.live), mock.patch.object(E, "ROOT", root),
                   mock.patch.object(E, "STATE", os.path.join(self.tmp, "state")),
                   mock.patch.object(E, "HISTORY", os.path.join(self.tmp, "deploys.jsonl")),
                   mock.patch.object(E, "push", lambda: ""), mock.patch.object(E, "step", self.steps.append)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, d, name):
        with open(os.path.join(d, name), "w") as f:
            f.write(name + "\n")
        sh("git", "add", name, cwd=d)
        sh("git", "commit", "-qm", name, cwd=d)
        return sh("git", "rev-parse", "HEAD", cwd=d)

    def head(self):
        return sh("git", "rev-parse", "HEAD", cwd=self.n1)

    def sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = no1.main(["sync"])
        return code, json.loads(out.getvalue())

    def test_a_clean_worktree_is_fast_forwarded(self):
        self.commit(self.live, "b")
        new = self.commit(self.live, "c")
        code, j = self.sync()
        self.assertEqual(code, 0, j)
        self.assertEqual((j["before"], j["after"], j["behind"]), (self.base, new, 2))
        self.assertEqual(self.head(), new)
        code, j = self.sync()  # already current: the same commit twice
        self.assertEqual((code, j["before"], j["after"], j["behind"]), (0, new, new, 0))

    def test_a_dirty_worktree_is_refused(self):
        self.commit(self.live, "b")
        with open(os.path.join(self.n1, "a"), "w") as f:
            f.write("edited\n")
        code, j = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", j["error"])
        self.assertEqual(self.head(), self.base)

    def test_an_untracked_file_does_not_refuse_it(self):
        new = self.commit(self.live, "b")
        with open(os.path.join(self.n1, "scratch.txt"), "w") as f:
            f.write("x\n")
        self.assertEqual(self.sync()[0], 0)
        self.assertEqual(self.head(), new)

    def test_commits_of_its_own_are_refused(self):
        self.commit(self.live, "b")
        own = self.commit(self.n1, "mine")
        code, j = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("1 commit(s) of its own", j["error"])
        self.assertEqual(self.head(), own)

    def test_another_branch_is_refused(self):
        sh("git", "checkout", "-q", "-b", "other", cwd=self.n1)
        code, j = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("not eng/number-one", j["error"])

    def land(self):
        sh("git", "checkout", "-q", "-b", "eng/x", cwd=self.live)
        new = self.commit(self.live, "b")
        sh("git", "checkout", "-q", "deb", cwd=self.live)
        with mock.patch.object(E, "c_changed", lambda a, b: False):
            return new, E.land_commits("x", self.base, new, ["b"])

    def test_a_deploy_ends_with_number_one_on_the_live_branch(self):
        new, msg = self.land()
        self.assertEqual(self.head(), new)
        self.assertNotIn("Number One", msg)
        self.assertTrue(any(s.startswith("Number One's worktree: ") for s in self.steps), self.steps)

    def test_a_failed_sync_is_a_line_in_the_deploy_s_outcome(self):
        self.commit(self.n1, "mine")
        new, msg = self.land()  # no exception: the deploy stands
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.live), new)
        self.assertIn(" - Number One's worktree not synced: eng/number-one has 1 commit(s)", msg)


if __name__ == "__main__":
    unittest.main()
