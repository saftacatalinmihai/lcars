#!/usr/bin/env python3
"""Unit tests for scripts/no1.py's `journal`: which lcars-cli it runs, with
what login, and that the real lcars-cli has no --db at all; and the refresh
(engineer.py's refresh-go): a Handover log marks it, the Stop hook's turn then clears, each step
logged; one relaunched without its hooks (herdr's restore) is restarted first;
and an engineer's: the turn that read the [refresh] ends in the clear, the
handover typed back with its crew_msg row; one out of the seat queued. A stub lcars-cli (a shell script that
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
import re
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
import testguard  # noqa: E402,F401 - no test reaches the live journal
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

    def test_bin_link(self):
        os.makedirs(os.path.join(self.live, "bin"))
        cli = self.stub(os.path.join(self.live, "bin", "lcars-cli"))
        code, err = self.run_journal("kinds")
        self.assertEqual((code, err), (0, None))
        self.assertEqual(self.ran(), [cli, "http://127.0.0.1:9", "no1", "pw", "kinds"])

    def test_retired_copy_not_used(self):
        # The copied build inside <live>/lcars-cli/ retired in 0.279.2: one
        # left behind is not run.
        self.stub(os.path.join(self.live, "lcars-cli", "lcars-cli"))
        code, err = self.run_journal("kinds")
        self.assertEqual(code, 1)
        self.assertIn("not built", err["error"])

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
                   mock.patch.object(E, "no1_send", side_effect=lambda text, **kw: self.sent.append(text)),
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
        self.assertTrue(self.sent[-1].startswith("[refresh] Your conversation was cleared"))
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
        steps = ["refresh asked of number-one, session s1", "turn-ended: no handover noted yet", "handover written",
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
                mock.patch.object(testguard.seat, "_http", return_value=[]), \
                mock.patch.object(E, "seat_on", return_value=False):
            got = self.call(E.cmd_reap)  # an empty inbox stood in (testguard)
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


class EngineerRefresh(unittest.TestCase):
    """The same refresh for an engineer: their handover is the last message of
    the turn that read the [refresh] line (its mark in the transcript), that
    turn's end clears them and the fresh session is typed the handover back,
    with its crew_msg row; one out of the seat gets it in their inbox; the
    refusals are clear's."""

    NAME = "reyes"

    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="eng-refresh-")
        self.path = os.path.join(self.state, "s2.jsonl")
        open(self.path, "w").close()
        self.cleared, self.spawned = [], []
        self.ps = [mock.patch.object(E, "STATE", self.state),
                   mock.patch.object(E, "agent_info", return_value={"agent_status": "idle"}),
                   mock.patch.object(E, "herdr", return_value=({}, "")),
                   mock.patch.object(E, "submit_if_left"),
                   mock.patch.object(E, "seated", return_value=False),
                   mock.patch.object(E, "transcript", return_value=self.path),
                   mock.patch.object(E, "turn_deliver", return_value=42),
                   mock.patch.object(E, "spawn", side_effect=lambda *a: self.spawned.append(a) or "unit"),
                   mock.patch.object(E, "clear_session",
                                     side_effect=lambda n, label: (self.cleared.append((n, label)) or
                                                                   (0, {"ok": True, "cleared": True}))),
                   mock.patch.object(E.time, "sleep")]
        for p in self.ps:
            p.start()
        E.save(self.NAME, {"name": self.NAME, "session": "s2", "task": "the boiler"})

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.state)

    call = Refresh.call

    def typed(self):
        return [c.args[3] for c in E.herdr.call_args_list if c.args[:2] == ("agent", "prompt")]

    def said(self, text):
        # a message of the captain's side in the transcript, as Claude Code writes it
        with open(self.path, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")

    def end_turn(self, last):
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"last_assistant_message": last}))):
            return self.call(E.cmd_hook, "turn-ended", self.NAME)

    def test_the_turn_that_read_it_ends_in_a_clear_and_the_handover_typed_back(self):
        got = self.call(E.cmd_refresh, self.NAME)
        self.assertTrue(got["pending"])
        asked = self.typed()[-1]
        self.assertTrue(asked.startswith("[refresh] (refresh #"))
        self.assertIn("WIP", asked)
        # a turn already under way that never read the line: no clear, the
        # report goes on as any turn's
        self.end_turn("Report: done with the valve.")
        self.assertEqual(self.spawned, [])
        E.turn_deliver.assert_called_once()
        self.assertNotIn("noted", E.load(self.NAME)["refresh"])
        # the next turn reads it, and its last words are the handover
        self.said(asked)
        self.end_turn("Handover: the boiler, valve fixed, tests left.")
        self.assertEqual(len(self.spawned), 1)
        verb, name, spool, t0 = self.spawned[0]
        self.assertEqual((verb, name), ("refresh-go", self.NAME))
        self.assertEqual(E.turn_deliver.call_count, 1)  # refresh-go files it, not the hook
        E.herdr.reset_mock()
        got = self.call(E.cmd_refresh_go, self.NAME, spool, t0)
        self.assertEqual(got, {"ok": True, "cleared": True, "msg": 42})
        self.assertEqual(self.cleared, [(self.NAME, "the boiler")])
        fresh = self.typed()[-1]
        self.assertTrue(fresh.startswith("[refresh] Your conversation was cleared"))
        self.assertIn("crew_msg #42", fresh)
        self.assertIn("Handover: the boiler, valve fixed, tests left.", fresh)
        self.assertNotIn("refresh", E.load(self.NAME))
        self.assertFalse(os.path.exists(spool))

    def test_a_long_handover_is_cut_with_the_pointer(self):
        text = E.refresh_handover_text("x" * (E.REFRESH_TYPED_MAX + 500), 7)
        self.assertIn("the rest is in crew_msg #7", text)
        self.assertLess(len(text), E.REFRESH_TYPED_MAX + 800)
        self.assertNotIn("crew_msg", E.refresh_handover_text("short", None))

    def test_one_out_of_the_seat_gets_it_in_the_inbox(self):
        E.agent_info.return_value = None
        E.seated.return_value = True
        with mock.patch.object(E, "seat_want") as want:
            got = self.call(E.cmd_refresh, self.NAME)
        self.assertTrue(got["queued"])
        self.assertIn("inbox", got["note"])
        self.assertTrue(want.call_args.args[2].startswith("[refresh] (refresh #"))
        self.assertFalse(self.typed())
        r = E.load(self.NAME)["refresh"]
        self.assertTrue(r["queued"])
        # delivered with the seat hours later: still pending
        r["at"] -= E.REFRESH_WAIT_SECONDS + 60
        self.assertTrue(E.refresh_pending({"refresh": r}))

    def test_the_refusals_are_clear_s(self):
        E.agent_info.return_value = None
        self.assertIn("not on duty", self.call(E.cmd_refresh, self.NAME)["error"])
        E.agent_info.return_value = {"agent_status": "blocked"}
        self.assertIn("question", self.call(E.cmd_refresh, self.NAME)["error"])
        self.assertNotIn("refresh", E.load(self.NAME))

    def test_a_failed_clear_moves_the_seat_on_and_tells_number_one(self):
        E.seated.return_value = True
        self.call(E.cmd_refresh, self.NAME)
        self.said(self.typed()[-1])
        self.end_turn("Handover: all of it.")
        spool = self.spawned[0][2]
        self.spawned.clear()
        E.clear_session.side_effect = lambda n, label: (3, {"error": "the engineer is not on duty"})
        with mock.patch.object(E, "notify_no1") as n1:
            got = self.call(E.cmd_refresh_go, self.NAME, spool, "5")
        self.assertFalse(got["cleared"])
        self.assertIn("did not happen", n1.call_args.args[1])
        self.assertIn(("seat-turn-ended", self.NAME, "5"), self.spawned)


class Research(unittest.TestCase):
    """The research tools (Agent, Skill, WebSearch, WebFetch) allowed to Number
    One and the engineers without a prompt, writes only into each one's
    research folder, and every denial still there."""

    SECRETS = (os.path.join(E.HOME, ".env"), os.path.join(E.HOME, ".claude/.credentials.json"),
               os.path.join(E.STATE, "no1.env"), os.path.join(E.LIVE, "lcars.db"),
               os.path.join(E.LIVE, "lcars.db-*"), os.path.join(E.LIVE, "lcars_bkp.db"))

    def check_secrets(self, deny):
        for p in self.SECRETS:
            self.assertIn(f"Read(/{p})", deny)

    def test_number_one(self):
        perms = E.no1_settings()["permissions"]
        allow, deny = perms["allow"], perms["deny"]
        for t in ("Agent", "Skill", "WebSearch", "WebFetch"):
            self.assertIn(t, allow)
            self.assertIn(t, E.NO1_TOOLS.split(","))
        d = E.research_dir(E.NO1)
        self.assertEqual(d, os.path.join(E.STATE, "research", E.NO1))
        self.assertIn(f"Edit(/{d}/**)", allow)
        # writes under the home folder and /tmp (the captain's order,
        # 2026-10-30), never a bare Edit/Write; the checkouts denied
        self.assertFalse([r for r in allow if r in ("Edit", "Write") or
                          (r.startswith(("Edit(", "Write(")) and
                           r not in (f"Edit(/{d}/**)", f"Edit(/{E.HOME}/**)", "Edit(//tmp/**)"))])
        self.assertIn(f"Edit(/{E.LIVE}/**)", deny)
        self.assertIn(f"Edit(/{os.path.dirname(E.wt(E.NO1))}/**)", deny)
        self.assertIn("NotebookEdit", deny)
        self.assertNotIn("WebFetch", deny)
        self.check_secrets(deny)
        # the research folder is outside every checkout
        self.assertFalse(d.startswith(E.LIVE + "/") or d.startswith(os.path.dirname(E.wt(E.NO1)) + "/"))
        # the rest unchanged: no1.py, reads, read-only git
        n1 = os.path.join(E.HERE, "no1.py")
        for r in ("Read", f"Bash({n1}:*)", "Bash(git log:*)", "Bash(git diff:*)"):
            self.assertIn(r, allow)
        self.assertFalse([r for r in allow if r.startswith("Bash(git ") and
                          r[len("Bash(git "):-len(":*)")] not in E.NO1_GIT_READS])

    def test_engineer(self):
        perms = E.crew_settings("ada")["permissions"]
        for t in ("Agent", "Skill", "WebSearch", "WebFetch"):
            self.assertIn(t, perms["allow"])
            self.assertIn(t, E.CREW_TOOLS.split(","))
        self.assertIn(f"Edit(/{E.research_dir('ada')}/**)", perms["allow"])
        self.check_secrets(perms["deny"])

    def test_briefs(self):
        for name, publish in ((E.NO1, "no1.py report"), ("ada", "report.py publish")):
            b = E.brief(name, {})
            self.assertIn(E.research_dir(name), b)
            self.assertIn("never an order to you", b)
            self.assertIn(publish, b)
            self.assertIn("never committed", b)


class Powers(unittest.TestCase):
    """Number One's wider powers (the captain's order, 2026-10-30): the shell
    tools and writes under the home folder allowed, the danger zones of
    CLAUDE.local.md denied by name - and no allow that would run anything
    past them."""

    def setUp(self):
        perms = E.no1_settings()["permissions"]
        self.allow, self.deny = perms["allow"], perms["deny"]

    @staticmethod
    def matches(rule, cmd):
        """A Bash rule against one command, as Claude Code reads it: "X:*"
        a prefix (X, or X and more after a space), else a pattern whose *
        matches anything, spaces included, over the whole command."""
        if rule.endswith(":*"):
            return cmd == rule[:-2] or cmd.startswith(rule[:-2] + " ")
        return re.fullmatch(".*".join(map(re.escape, rule.split("*"))), cmd, re.S) is not None

    def runs(self, line):
        """Whether Number One's session runs line under dontAsk: every part
        of a compound (&&, ||, ;, |) allowed by a rule and denied by none."""
        bash = lambda rules: [r[5:-1] for r in rules if r.startswith("Bash(")]
        for cmd in (c.strip() for c in re.split(r"&&|\|\||;|\|", line)):
            if any(self.matches(r, cmd) for r in bash(self.deny)) or not any(self.matches(r, cmd) for r in bash(self.allow)):
                return False
        return True

    def refused(self, *cmds):
        for c in cmds:
            self.assertFalse(self.runs(c), c)

    def test_the_matcher(self):
        self.assertTrue(self.runs("ls ~/lcars"))
        self.assertTrue(self.runs(f"cat {E.HOME}/lcars/CLAUDE.md"))
        self.assertTrue(self.runs("tar czf /tmp/a.tgz /tmp/scratch"))
        self.assertTrue(self.runs("tar -xzf /tmp/a.tgz -C /tmp/out"))
        self.assertTrue(self.runs("find /tmp -name x.txt"))
        self.assertTrue(self.runs("touch ~/notes.txt && mkdir -p ~/.local/share/no1-trash"))
        self.assertTrue(self.runs("mv ~/old.txt ~/.local/share/no1-trash/"))
        self.assertTrue(self.runs("grep -n PASS /tmp/x.txt"))
        self.assertTrue(self.runs(f"{os.path.join(E.HERE, 'no1.py')} rm -r /tmp/x"))
        self.assertFalse(self.runs("python3 -c 1"))

    def test_gap_1_no_bare_rm(self):
        self.assertNotIn("rm", (*E.NO1_SHELL, *E.NO1_SHELL_WRITES))
        self.refused("rm -rf ~", "rm -rf ~/lcars", f"rm -rf {E.HOME}", "rm /tmp/x", "rm -rf /tmp/x ~/lcars",
                     "rm -rf $HOME", "cd ~ && rm -rf lcars")

    def test_gap_2_no_shell_write_into_the_code(self):
        for home in ("~", E.HOME, "$HOME", "${HOME}"):
            self.refused(f"sed -i s/a/b/ {home}/lcars/lcars-ui/index.html", f"cp /tmp/x {home}/lcars/",
                         f"mv /tmp/a {home}/lcars-eng/number-one/x", f"tee {home}/lcars/x", f"chmod 777 {home}/lcars",
                         f"ln -s /tmp/x {home}/lcars/y", f"touch {home}/lcars/x", f"tar xf /tmp/a.tar -C {home}/lcars",
                         f"unzip /tmp/a.zip -d {home}/lcars-eng", f"awk -i inplace 1 {home}/lcars/x",
                         f"echo hi > {home}/lcars/x", f"echo hi >>{home}/lcars-personal.db",
                         f"gzip {home}/lcars/lcars.db", f"mkdir {home}/lcars/x", f"printf x > {home}/lcars/x")

    def test_gap_3_no_secret_through_the_shell(self):
        for home in ("~", E.HOME, "$HOME"):
            self.refused(f"cat {home}/.env", f"head {home}/.claude/.credentials.json", f"cat {home}/.e*",
                         f"grep PASS {home}/.env", f"tar czf /tmp/h.tgz {home}", f"cp -r {home} /tmp/h".replace(" /tmp/h", "") ,
                         f"find {home} -name x", f"cat {home}/.config/lcars/x")
        self.refused("cat .env", f"cat {E.STATE}/no1.env", "grep -r PASS ~", "grep -R PASS /home", "grep -ir pass ~",
                     "grep -rn pass ~", "grep -nri pass ~", "grep -inr pass ~", "grep -n PASS -r ~", "grep -n PASS -ir ~", "grep --recursive PASS ~", "grep -d recurse PASS ~",
                     "rg PASS ~", "rg --hidden PASS /home")

    def test_no_sed_or_awk(self):
        for c in ("sed", "awk", "gawk", "perl"):
            self.assertNotIn(c, (*E.NO1_SHELL, *E.NO1_SHELL_WRITES))
        for c in ("sed", "awk", "gawk"):
            self.assertIn(f"Bash({c}:*)", self.deny, "denied outright: Claude Code allows a read-only-looking sed by itself")
        self.refused("awk 'BEGIN{system(\"rm -rf ~\")}'", "sed -n 1p /tmp/x.txt", "sed 'e touch /tmp/y' /tmp/x",
                     "sed -n 'w /tmp/z' /tmp/x")
        self.assertIn("never grep -r", E.brief(E.NO1, {}))
        self.assertIn("no sed or awk", E.brief(E.NO1, {}))

    def test_tar_runs_nothing(self):
        self.refused("tar xf /tmp/a.tar --to-command='sh -c id'", "tar --to-command=id -xf /tmp/a.tar",
                     "tar cf /tmp/a.tar --checkpoint=1 --checkpoint-action=exec=id /tmp/s",
                     "tar --use-compress-program=id -cf /tmp/a /tmp/s", "tar -I id -cf /tmp/a /tmp/s",
                     "tar -Iid -cf /tmp/a /tmp/s", "tar cIf id /tmp/a /tmp/s", "tar -cf /tmp/a --info-script=id /tmp/s",
                     "tar -cf /tmp/a --new-volume-script=id /tmp/s", "tar -F id -cf /tmp/a /tmp/s",
                     "tar -cMF id -f /tmp/a /tmp/s", "tar --to-c=id -xf /tmp/a", "tar --use-c=id -cf /tmp/a /tmp/s")

    def test_find_deletes_and_writes_nothing(self):
        for home in ("~", E.HOME, "$HOME"):
            self.refused(f"find {home}/lcars -delete", f"find {home} -name '*.py' -delete",
                         f"find {home} -fprint /tmp/x", f"find {home} -fprintf /tmp/x %p", f"find {home} -fls /tmp/x",
                         f"find {home}/lcars -exec rm {{}} +", f"find {home} -execdir id ;", f"find {home} -ok rm {{}} ;")

    def test_gap_4_no_cd_into_the_code(self):
        for home in ("~", E.HOME, "$HOME"):
            self.refused(f"cd {home}/lcars && touch x", f"cd {home}/lcars; sed -i s/a/b/ lcars-ui/index.html",
                         f"cd {home}/lcars-eng/number-one && touch x", f"pushd {home}/lcars && touch x",
                         f"cd -P {home}/lcars && touch x")

    def test_the_shell_and_the_home_folder(self):
        for c in ("ls", "cat", "find", "grep", "cp", "mv", "mkdir", "tar", "jq"):
            self.assertIn(f"Bash({c}:*)", self.allow)
        self.assertIn(f"Edit(/{E.HOME}/**)", self.allow)
        # outside the working directories a command is refused whatever the allows say
        self.assertEqual(E.no1_settings()["permissions"]["additionalDirectories"], [E.HOME, "/tmp"])

    def test_nothing_that_runs_anything(self):
        for c in ("python3", "python", "bash", "sh", "zsh", "node", "perl", "xargs", "env", "sudo",
                  "curl", "sqlite3", "systemctl", "ssh", "eval", "exec"):
            self.assertNotIn(f"Bash({c}:*)", self.allow, c)
            self.assertFalse([r for r in self.allow if r.startswith(f"Bash({c} ") and "no1.py" not in r
                              and "steward.py" not in r], c)
        self.assertIn("Bash(find *-exec*)", self.deny)

    def test_the_danger_zones_denied(self):
        for s in ("db-push.sh", "db-pull.sh", "db-swap.sh", "db-filter.sh", "db-slots.sh", "vps-rebuild.sh"):
            self.assertIn(f"Bash(*{s}*)", self.deny)
        for r in ("Bash(*db-prune.py*--apply*)", "Bash(ssh:*)", "Bash(sqlite3 *.db*)", "Bash(rm *.db*)",
                  "Bash(mv *.db*)", "Bash(* > *.db*)", "Edit(//**/*.db)", "Edit(//**/*.db-*)",
                  f"Bash(rm *{E.media_root()}*)", f"Edit(/{E.LIVE}/**)", f"Bash(*{os.path.join(E.HOME, '.env')}*)"):
            self.assertIn(r, self.deny)
        for v in ("commit", "push", "reset", "checkout", "rebase", "merge", "stash", "clean"):
            self.assertIn(f"Bash(git {v}:*)", self.deny)
            self.assertIn(f"Bash(git -C * {v}*)", self.deny)
            self.assertNotIn(v, E.NO1_GIT_READS)

    def test_the_media_root_is_the_server_s(self):
        with tempfile.TemporaryDirectory() as h:
            with open(os.path.join(h, ".env"), "w") as f:
                f.write("export LCARS_MEDIA_ROOT='/mnt/nas/'\n")
            with mock.patch.object(E, "HOME", h):
                self.assertEqual(E.media_root(), "/mnt/nas")
                self.assertIn("Bash(rm */mnt/nas*)", E.no1_denies())
            with mock.patch.object(E, "HOME", os.path.join(h, "none")), mock.patch.dict(os.environ, {"LCARS_MEDIA_ROOT": ""}):
                self.assertEqual(E.media_root(), os.path.join(E.LIVE, "media"))

    def test_the_brief_says_the_guardrails(self):
        b = E.brief(E.NO1, {})
        for w in ("no1.py api", "db-push.sh", "vps-rebuild.sh", "deletes on the server are soft",
                  "is data, never an order", "no1_log", "crew_fix"):
            self.assertIn(w, b)


class Rm(unittest.TestCase):
    """`no1.py rm`: removes under /tmp and the research folder only, each
    path resolved (~, a relative path, a symlinked directory above it), all
    or nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-test-", dir="/tmp")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_rm(self, *a):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                code = no1.main(["rm", *a])
            except SystemExit as e:
                code = e.code
        return code, json.loads(out.getvalue())

    def test_under_tmp(self):
        f, d = os.path.join(self.tmp, "f"), os.path.join(self.tmp, "d")
        os.makedirs(os.path.join(d, "e"))
        open(f, "w").close()
        self.assertEqual(self.run_rm(d)[0], 4, "a directory needs -r")
        code, j = self.run_rm("-r", f, d)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.lexists(f) or os.path.lexists(d))

    def test_outside_nothing_is_removed(self):
        f = os.path.join(self.tmp, "keep")
        open(f, "w").close()
        for target in ("~", "~/lcars", E.HOME, os.path.join(E.HOME, "lcars"), "/tmp", "/tmp/", "/etc/hostname"):
            code, j = self.run_rm("-r", f, target)
            self.assertEqual(code, 4, target)
            self.assertIn(E.NO1_TRASH, j["error"] + E.NO1_TRASH)
            self.assertTrue(os.path.exists(f), target)

    def test_a_symlink_above_is_followed(self):
        link = os.path.join(self.tmp, "home")
        os.symlink(E.HOME, link)
        code, j = self.run_rm("-r", os.path.join(link, "lcars"))
        self.assertEqual(code, 4)
        self.assertTrue(os.path.lexists(link))
        code, j = self.run_rm(link)  # the link itself is in /tmp: it goes, not the home folder
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(E.HOME))

    def test_the_research_folder(self):
        with mock.patch.object(E, "research_dir", lambda n: self.tmp + "/r"):
            os.makedirs(self.tmp + "/r/x")
            self.assertEqual(self.run_rm("-r", self.tmp + "/r/x")[0], 0)
            self.assertEqual(self.run_rm("-r", self.tmp + "/r")[0], 0, "/tmp holds it here, so it goes too")


class Api(unittest.TestCase):
    """`no1.py api`: the call as the captain's login (sent through api_send,
    mocked), GET free, a write followed by its no1_log line over Number
    One's login (http mocked), a body from a file as JSON or text, and the
    refusals before anything is sent."""

    def setUp(self):
        self.sent, self.logged = [], []
        self.status = 200
        self.tmp = tempfile.mkdtemp(prefix="no1-test-")
        self.ps = [mock.patch.object(no1, "api_send", self.send), mock.patch.object(no1, "http", self.log)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp)

    def send(self, method, path, data, ctype, timeout=120):
        self.sent.append((method, path, data, ctype))
        return self.status, json.dumps({"ok": True})

    def log(self, method, path, body=None, timeout=60):
        self.logged.append((method, path, body))
        return 201, json.dumps({"id": 501})

    def run_api(self, *a, stdin=b""):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin))):
            try:
                code = no1.main(["api", *a])
            except SystemExit as e:
                code = e.code
        return code, json.loads(out.getvalue())

    def test_a_get_is_free(self):
        code, j = self.run_api("get", "/theme")
        self.assertEqual(code, 0)
        self.assertEqual(j, {"status": 200, "answer": {"ok": True}})
        self.assertEqual(self.sent, [("GET", "/theme", None, None)])
        self.assertEqual(self.logged, [])

    def test_a_write_is_logged_with_its_status(self):
        f = os.path.join(self.tmp, "roles.json")
        with open(f, "w") as fh:
            fh.write('{"task": "todo"}')
        code, j = self.run_api("PUT", "/kinds/roles", "--file", f)
        self.assertEqual(code, 0)
        self.assertEqual(self.sent, [("PUT", "/kinds/roles", b'{"task": "todo"}', "application/json")])
        self.assertEqual(j["logged"], 501)
        (m, path, body), = self.logged
        self.assertEqual((m, path, body["kind"]), ("POST", "/entries", "no1_log"))
        self.assertEqual(body["title"], "api PUT /kinds/roles -> 200")
        self.assertIn("16-byte application/json body", body["content"])

    def test_a_failed_write_is_logged_too(self):
        self.status = 409
        code, j = self.run_api("DELETE", "/entries/12")
        self.assertEqual(code, 1)
        self.assertEqual(self.logged[0][2]["title"], "api DELETE /entries/12 -> 409")

    def test_a_text_body_from_stdin(self):
        code, j = self.run_api("PUT", "/theme?name=x", "-", stdin=b"theme[main_bg]=\"#000\"\n")
        self.assertEqual(self.sent[0][3], "text/plain; charset=utf-8")
        self.assertEqual(self.sent[0][2], b'theme[main_bg]="#000"\n')

    def test_a_log_that_fails_is_said(self):
        with mock.patch.object(no1, "http", lambda *a, **k: (403, "no")):
            code, j = self.run_api("POST", "/say")
        self.assertEqual(code, 1)
        self.assertIn("its no1_log line failed", j["log_error"])

    def test_the_refusals_send_nothing(self):
        for a in (["GET", "http://evil.example/x"], ["GET", "//evil.example/x"], ["GET", "theme"],
                  ["PUT", "/vault"], ["GET", "/vault?x=1"], ["POST", "/engineer/ada/deploy"],
                  ["TRACE", "/health"], ["GET", "/theme", "--file", "/dev/null"], ["GET"]):
            code, j = self.run_api(*a)
            self.assertNotEqual(code, 0, a)
            self.assertIn("error", j, a)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.logged, [])

    def test_the_login_is_the_captain_s(self):
        for p in self.ps:
            p.stop()
        self.ps = []
        seen = {}

        class R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def urlopen(req, timeout=0):
            seen["auth"], seen["url"] = req.get_header("Authorization"), req.full_url
            return R()
        with mock.patch.object(no1.J, "journal_login", return_value=("http://127.0.0.1:9", "cap", "pw")), \
                mock.patch.object(no1.urllib.request, "urlopen", urlopen):
            self.assertEqual(no1.api_send("GET", "/features", None, None), (200, "{}"))
        self.assertEqual(seen["url"], "http://127.0.0.1:9/features")
        self.assertEqual(seen["auth"], "Basic " + __import__("base64").b64encode(b"cap:pw").decode())


class Threads(unittest.TestCase):
    """no1.py thread: each verb handed to engineer.py's `thread number-one`
    (which holds the rules: test_no1_threads.py), and the shapes refused
    before it is asked: no switch, no seed."""

    def run_no1(self, *a):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                no1.main(list(a))
            except SystemExit as e:
                return e.code, json.loads(buf.getvalue())
        return 0, json.loads(buf.getvalue())

    def test_verbs_go_to_engineer_py(self):
        calls = []
        with mock.patch.object(no1, "engineer", side_effect=lambda *a, inp="": calls.append((a, inp)) or (0, {})):
            self.run_no1("thread", "list")
            self.run_no1("thread", "new", "deck", "Deck redesign")
            self.run_no1("thread", "rename", "deck", "The bridge")
            self.run_no1("thread", "close", "deck")
        self.assertEqual(calls, [
            (("thread", E.NO1, "list"), ""),
            (("thread", E.NO1, "new", "deck", "Deck redesign"), ""),
            (("thread", E.NO1, "rename", "deck", "The bridge"), ""),
            (("thread", E.NO1, "close", "deck"), "")])

    def test_refusals(self):
        with mock.patch.object(no1, "engineer") as eng:
            for a in (["thread"], ["thread", "fork", "x"], ["thread", "switch", "main"], ["thread", "rename", "deck"],
                      ["thread", "new"], ["thread", "new", "deck", "Deck", "a seed"], ["thread", "close"]):
                self.assertEqual(self.run_no1(*a)[0], 2, a)
        eng.assert_not_called()


class CrewRoom(unittest.TestCase):
    """crew say|deploy --room <id>: the room checked (engineer.py room_check,
    test_rooms.py), LCARS_ROOM_AT set for engineer.py, the flag taken off
    the order; refused for another verb, without an id, or a bad room."""

    def setUp(self):
        self.calls = []
        env = mock.patch.dict(os.environ, {"LCARS_ROOM_AT": "", "LCARS_ROOM_BY": ""})
        env.start()
        self.addCleanup(env.stop)

    run_no1 = Threads.run_no1

    def eng(self, *a, inp=""):
        self.calls.append((a, inp, os.environ.get("LCARS_ROOM_AT")))
        return 0, {"ok": True}

    def test_say_and_deploy_name_the_room(self):
        with mock.patch.object(no1, "engineer", side_effect=self.eng), \
                mock.patch.object(E, "room_check", return_value=None) as chk:
            self.assertEqual(self.run_no1("crew", "say", "kim", "--room", "deck", "--fresh", "Fix", "it")[0], 0)
            self.assertEqual(self.run_no1("crew", "deploy", "kim", "--room", "deck")[0], 0)
        self.assertEqual(self.calls, [(("say", "kim", "--fresh"), "[No.1] Fix it", "deck"),
                                      (("deploy", "kim"), "", "deck")])
        self.assertEqual([c.args for c in chk.call_args_list], [("deck",), ("deck",)])

    def test_without_it_the_turn_s_room(self):
        with mock.patch.object(no1, "engineer", side_effect=self.eng):
            self.run_no1("crew", "say", "kim", "Go")
        self.assertEqual(self.calls, [(("say", "kim"), "[No.1] Go", "")])

    def test_refusals(self):
        with mock.patch.object(no1, "engineer") as eng, \
                mock.patch.object(E, "room_check", return_value="no such room: nope (no1.py room list names them)"):
            code, j = self.run_no1("crew", "say", "kim", "--room", "nope", "Go")
            self.assertEqual(code, 4)
            self.assertIn("no such room: nope", j["error"])
            for a in (["crew", "poll", "kim", "--room", "deck"], ["crew", "say", "kim", "--room"],
                      ["crew", "say", "kim", "--room", "--fresh", "Go"]):
                self.assertEqual(self.run_no1(*a)[0], 2, a)
        eng.assert_not_called()


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


class ReportBase(unittest.TestCase):
    """A temp media root, a source file, and Number One's http mocked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no1-test-")
        self.root = os.path.join(self.tmp, "root")
        self.src = os.path.join(self.tmp, "brief.html")
        with open(self.src, "w") as f:
            f.write("<p>hi</p>")
        self.posts = []
        self.ps = [mock.patch.dict(os.environ, {"LCARS_MEDIA_ROOT": self.root,
                                                "LCARS_REPORT_BASE": "https://box.example"}),
                   mock.patch.object(no1, "http", self.http),
                   # report.py's entry, written as the captain's login: never
                   # the box's journal from a test
                   mock.patch.object(no1.R, "api", self.report_api)]
        self.report_calls = []
        for p in self.ps:
            p.start()

    def report_api(self, method, path, body=None, timeout=60):
        self.report_calls.append((method, path, body))
        return (200, []) if method == "GET" else (201, {"id": 77})

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


class Report(ReportBase):
    """`no1.py report`: the file published by report.py into a temp media
    root, then its link logged as a no1_log entry over Number One's login
    (http mocked); refused, with no entry, when the root is not mounted."""

    def test_publishes_and_logs_the_link(self):
        os.makedirs(os.path.join(self.root, "media"))
        code, j = self.run_report(self.src, "Weekly brief", "for Monday")
        self.assertEqual(code, 0)
        self.assertTrue(j["url"].startswith("https://box.example/media/reports/"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, j["path"])))
        self.assertEqual(j["entry_id"], 42)
        self.assertEqual(j["id"], 77)   # the report's own entry, by report.py
        [_, (method, path, body)] = self.report_calls
        self.assertEqual((method, path, body["kind"], body["title"]), ("POST", "/entries", "report", "Weekly brief"))
        self.assertTrue(body["content"].startswith("report:: html " + j["path"] + "\n\n<p>hi</p>"))
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


class ReportStdin(ReportBase):
    """`no1.py report - TITLE --as NAME.EXT`: the report piped in, written to
    a private temp file, published through report.py (stood in for here, so
    the file it was handed can be looked at) and that file gone after; the
    refusals publish nothing and leave no temp file."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, "media"))
        self.temps = os.path.join(self.tmp, "temps")
        os.makedirs(self.temps)
        self.handed = []
        real_publish, real_update = no1.R.publish, no1.R.update

        def publish(path, title=None):
            self.handed.append((path, os.stat(path).st_mode & 0o777, read(path),
                                os.stat(os.path.dirname(path)).st_mode & 0o777))
            return real_publish(path, title)

        def update(rel, path):
            self.handed.append((path, None, read(path), None))
            return real_update(rel, path)

        for p in (mock.patch.object(no1.R, "publish", publish), mock.patch.object(no1.R, "update", update),
                  mock.patch.object(no1.tempfile, "tempdir", self.temps)):
            p.start()
            self.ps.append(p)

    def run_stdin(self, data, *a):
        with mock.patch.object(no1.sys, "stdin", io.TextIOWrapper(io.BytesIO(data))):
            return self.run_report(*a)

    def test_publishes_stdin_and_removes_the_temp_file(self):
        code, j = self.run_stdin(b"<h1>Brief</h1>", "-", "Weekly brief", "for Monday", "--as", "brief.html")
        self.assertEqual(code, 0, j)
        [(path, mode, data, dmode)] = self.handed
        self.assertEqual((os.path.basename(path), mode, dmode, data), ("brief.html", 0o600, 0o700, b"<h1>Brief</h1>"))
        self.assertTrue(path.startswith(self.temps + os.sep))
        self.assertEqual(os.listdir(self.temps), [])
        self.assertTrue(j["path"].endswith(".html"))
        with open(os.path.join(self.root, j["path"]), "rb") as f:
            self.assertEqual(f.read(), b"<h1>Brief</h1>")
        [(_, _, body)] = self.posts
        self.assertEqual(body["title"], "Report: Weekly brief")
        self.assertIn("for Monday", body["content"])
        self.assertNotIn("--as", body["content"])

    def test_update_from_stdin(self):
        _, first = self.run_stdin(b"a,b\n1,2\n", "-", "Numbers", "--as", "n.csv")
        self.posts.clear()
        code, j = self.run_stdin(b"a,b\n3,4\n", "--update", first["path"], "-", "--as", "n.csv", "fixed")
        self.assertEqual(code, 0, j)
        self.assertEqual(j["url"], first["url"])
        with open(os.path.join(self.root, j["path"]), "rb") as f:
            self.assertEqual(f.read(), b"a,b\n3,4\n")
        self.assertEqual(self.posts[0][2]["title"], "Report updated: Numbers")
        self.assertEqual(os.listdir(self.temps), [])

    def test_refusals_publish_nothing(self):
        big = b"x" * (no1.STDIN_MAX + 1)
        for data, args, says in [
                (b"", ("-", "T", "--as", "a.md"), "empty"),
                (b"  \n", ("-", "T", "--as", "a.md"), "empty"),
                (big, ("-", "T", "--as", "a.md"), "over"),
                (b"x", ("-", "T", "--as", "../a.md"), "slash"),
                (b"x", ("-", "T", "--as", "a/b.md"), "slash"),
                (b"x", ("-", "T", "--as", "a..md"), "slash"),
                (b"x", ("-", "T", "--as", ".a.md"), "slash"),
                (b"x", ("-", "T", "--as", "a.exe"), "not a report type"),
                (b"x", ("-", "T", "--as", "a.pdf"), "not a report type"),
                (b"x", ("-", "T", "--as", "noext"), "not a report type"),
                (b"x", ("-", "T"), "--as"),
                (b"x", (self.src, "T", "--as", "a.md"), "--as"),
                (b"x", ("-", "T", "--as"), "--as"),
                (b"x", ("--update", "media/reports/2026/10/nope.md", "-", "--as", "a.md"), "no report"),
        ]:
            with self.subTest(args=args, size=len(data)):
                code, j = self.run_stdin(data, *args)
                self.assertNotEqual(code, 0)
                self.assertIn(says, j["error"])
        self.assertEqual((self.handed, self.posts, os.listdir(self.temps)), ([], [], []))
        self.assertFalse(os.path.exists(os.path.join(self.root, "media", "reports")))


def read(path):
    with open(path, "rb") as f:
        return f.read()


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


class Answers(unittest.TestCase):
    """The tick-off typed to Number One (no1_answers): the console's Answer
    block whole, a line per question, whatever its length."""

    ASK = "Shared context.\n\nQ1: Ship it?\nOptions: A) now B) later\nQ2: Keep the view?\n" + "more context\n" * 200

    def test_the_answer_block_goes_whole_and_the_context_is_clipped(self):
        block = "Answer (captain, 2026-10-20 09:00):\nQ1: A (now); note: " + "x" * 1500 + "\nQ2: yes"
        n = E.answer_notes(block + "\n\n" + self.ASK)
        self.assertTrue(n.startswith(block), "every question's answer, past 1200 characters")
        self.assertIn("Shared context.", n)
        self.assertLess(len(n), len(block) + 700, "the ask under it clipped")

    def test_a_plain_tick_is_clipped_as_before(self):
        self.assertEqual(E.answer_notes("y" * 2000), "y" * 1200 + " …")
        self.assertEqual(E.answer_notes("Answer (captain, t): fine"), "Answer (captain, t): fine")

    def test_the_console_s_send_is_typed_with_its_answers(self):
        import sqlite3
        d = tempfile.mkdtemp(prefix="lcars-test-no1-")
        self.addCleanup(shutil.rmtree, d, True)
        con = sqlite3.connect(os.path.join(d, "lcars.db"))
        con.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, kind TEXT, title TEXT, content TEXT,"
                    " last_modified_at_utc TEXT, deleted INTEGER DEFAULT 0, done_bool INTEGER DEFAULT 0)")
        con.execute("INSERT INTO entries VALUES (7, 'task_no1', 'Pins and the view', ?, '2099-01-01 00:00:00', 0, 1)",
                    ("Answer (captain, 2026-10-20 09:00):\nQ1: A (now); note: " + "x" * 1300 + "\nQ2: yes\n\n" + self.ASK,))
        con.commit()
        con.close()
        told = []
        with mock.patch.object(E, "LIVE", d), mock.patch.object(E, "NO1_ANSWERS", os.path.join(d, "a.json")), \
                mock.patch.object(E, "load", return_value={}), \
                mock.patch.object(E, "no1_send", side_effect=lambda t, **kw: told.append(t) or True):
            self.assertEqual(E.no1_answers(), [7])
        self.assertEqual(len(told), 1)
        self.assertIn("ticked off your question #7: Pins and the view", told[0])
        self.assertIn("\nQ2: yes", told[0], "the last question's answer survives the clip")


if __name__ == "__main__":
    unittest.main()
