#!/usr/bin/env python3
"""Unit tests for the crew runner (scripts/crew.py) and its wrapper
(scripts/crew_tool.py). No network, no claude, no journal: a stub claude
(a script printing claude's JSON) and a stand-in server on a free port.

    python3 scripts/test_crew.py
"""

import datetime as dt
import http.server
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# no run here may queue for the live seat (crew.seat)
os.environ["LCARS_ENG_SEAT"] = "0"
# the captain's zone for every test here (crew_tool reads it at import):
# one with the rules a zone at UTC+2/+3 with the EU's summer time has, so
# the day arithmetic below holds; the box's own zone never leaks in
os.environ["LCARS_CREW_TZ"] = "Europe/Helsinki"
import crew as C  # noqa: E402
import crew_tool as T  # noqa: E402
import crew_notes as N  # noqa: E402
import lcars_roles  # noqa: E402

# The roles: the defaults, or $LCARS_KINDS_FILE's mapping (the same checks
# with a set one, kinds.md 7); the in-process ones never ask a server.
T._ROLES = lcars_roles.load(lambda: None) if os.environ.get("LCARS_KINDS_FILE") else lcars_roles.Roles()
CV = T.roles().kind("child_vocab")


class Server:
    """A stand-in LCARS server: /health, GET /entries, /kinds, POST /entries."""

    def __init__(self, healthy=True, rows=None):
        self.posts, self.auth, self.raw, self.paths = [], [], [], []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body):
                b = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/health":
                    return self.reply(200 if healthy else 503, {"status": "ok"})
                outer.auth.append(self.headers.get("Authorization"))
                if self.path.startswith("/kinds"):
                    return self.reply(200, [])
                return self.reply(200, rows or [])

            def do_POST(self):
                outer.auth.append(self.headers.get("Authorization"))
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                outer.raw.append(raw)
                outer.paths.append(self.path)
                outer.posts.append(json.loads(raw))
                self.reply(200, {"id": 100 + len(outer.posts)})

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


ROLE = """---
title: Test, a role
schedule: *-*-* 06:30
model: haiku
verbs: today agenda get
web: api.open-meteo.com
budget: 0.10
timeout: 30
lock_wait: 0
mem_wait: 0
min_free_mb: 0
---
Do the test pass.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="crew-test-")
        self.crew = os.path.join(self.tmp, "crew")
        os.makedirs(self.crew)
        env = os.path.join(self.tmp, "env")
        with open(env, "w") as f:
            f.write('export LCARS_CREW_USER=crew\nexport LCARS_CREW_PASS="pass with spaces"\nLCARS_AUTH_PASS=captain\n')
        self.patches = [mock.patch.object(C, "CREW_DIR", self.crew), mock.patch.object(C, "STATE", os.path.join(self.tmp, "state")),
                        mock.patch.object(T, "ENV_FILE", env), mock.patch.object(C, "UNIT_DIR", os.path.join(self.tmp, "units"))]
        for p in self.patches:
            p.start()
        os.environ.pop("CREW_IN_AGENT", None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.environ.pop("LCARS_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def role(self, name="test", text=ROLE):
        with open(os.path.join(self.crew, name + ".md"), "w") as f:
            f.write(text)


class Roles(Base):
    def test_every_role_in_the_repo_loads(self):
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            names = C.roles()
            self.assertIn("ops", names)
            for n in names:
                fm, prompt = C.load(n)
                self.assertTrue(prompt)
                if fm["kind"] == "agent":
                    self.assertIn(fm["model"], C.MODELS)
                    self.assertNotIn("post", fm["verbs"].split())
                    float(fm["budget"])

    def test_a_chat_brief_is_no_role(self):
        """crew/architect.md (kind: chat) is the deck's chat's brief: no
        schedule, never a run, never in the list or the timers."""
        self.role("architect", "---\ntitle: The architect\nkind: chat\n---\nChange the ship.\n")
        self.role("test")
        self.assertEqual(C.roles(), ["test"])
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            self.assertNotIn("architect", C.roles())

    def test_the_counselor_only_reads(self):
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            fm, prompt = C.load("counselor")
        self.assertEqual((fm["schedule"], fm["posts"]), ("Sun *-*-* 07:00", "counselor"))
        argv = C.claude_argv(fm, prompt, tool="/x/crew_tool.py")
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash")
        allowed = argv[argv.index("--allowedTools") + 1: argv.index("--permission-mode")]
        self.assertEqual(allowed, [f"Bash(/x/crew_tool.py {v}:*)" for v in ("today", "counsel", "get", "list")])
        self.assertIn("URGENT", prompt)

    def test_schedules_are_spaced_on_the_small_box(self):
        """No two roles that can fall on the same day start within 20
        minutes of each other, none in the zone's DST hour (03-04, skipped
        or doubled), and the 23:00 hour is the linker pass's alone."""
        days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            for day in days:
                times = []
                for n in C.roles():
                    sched = C.load(n)[0]["schedule"].split()
                    if sched[0] in days and sched[0] != day:
                        continue    # a weekly role on another day ("*-*-01" may be any day)
                    hours, mm = sched[-1].split(":")
                    for hh in map(int, hours.split(",")):     # "02,08,14,20:10" (shares)
                        self.assertFalse(hh == 3 or (hh == 23 and n != "yeoman-linker"), n)
                        times.append((hh * 60 + int(mm), n))
                times.sort()
                for (a, na), (b, nb) in zip(times, times[1:]):
                    self.assertGreaterEqual(b - a, 20, f"{day}: {na} and {nb}")

    def test_front_matter(self):
        self.role("historian-monthly", ROLE.replace("model: haiku\n", ""))
        fm, prompt = C.load("historian-monthly")
        self.assertEqual(fm["posts"], "historian")
        self.assertEqual(fm["model"], "sonnet")
        self.assertEqual(prompt, "Do the test pass.")

    def test_the_local_context(self):
        """crew/context.local.md: the shared part to every role and to a note
        turn, a role's section to it alone after its orders, its front matter
        over the role's; the comments never sent; no file, no change."""
        self.role("historian-monthly")
        self.assertEqual(C.load("historian-monthly")[1], "Do the test pass.")
        self.assertEqual(C.local_context(), ({}, ""))
        self.assertNotIn("What to know", C.brief_note(dict(C.DEFAULTS, title="Yeoman", role="yeoman")))
        with open(os.path.join(self.crew, C.LOCAL_CONTEXT), "w") as f:
            f.write("<!--\nthe file's own note\n-->\nAna is the captain's sister.\n\n"
                    "## historian-monthly\n---\nmodel: opus\nwrites: append #77\n---\nName Ana's visits.\n\n"
                    "## other\nNot yours.\n")
        fm, prompt = C.load("historian-monthly")
        self.assertEqual(prompt, "Do the test pass.\n\nAna is the captain's sister.\n\nName Ana's visits.")
        self.assertEqual((fm["model"], fm["schedule"]), ("opus", "*-*-* 06:30"))
        self.assertEqual(C.write_targets(fm), {77})
        self.assertNotIn("Not yours", prompt)
        self.assertNotIn("own note", prompt)
        self.role("test")
        self.assertEqual(C.load("test")[1], "Do the test pass.\n\nAna is the captain's sister.")
        note = C.brief_note(dict(C.DEFAULTS, title="Yeoman", role="yeoman"))
        self.assertTrue(note.endswith("What to know about the captain's journal:\n\nAna is the captain's sister."))
        self.assertNotIn("Ana's visits", note)
        self.assertNotIn("context.local", C.roles())

    def test_the_owner_in_the_briefs(self):
        """LCARS_OWNER names the captain in a brief; unset, "the captain's"."""
        self.role("test")
        fm, prompt = C.load("test")
        with mock.patch.dict(os.environ, {"LCARS_OWNER": ""}):
            self.assertIn("on the captain's LCARS server", C.brief(fm, prompt))
            with open(T.ENV_FILE, "a") as f:
                f.write("LCARS_OWNER=Ana\n")
            self.assertIn("on the captain's (Ana's) LCARS server", C.brief(fm, prompt))
            self.assertIn("on the captain's (Ana's) LCARS journal server", C.brief_note(dict(fm, brief="note")))

    def test_bad_roles_are_refused(self):
        for bad in (ROLE.replace("haiku", "gpt"), ROLE.replace("verbs: today", "verbs: today post"),
                    ROLE.replace("schedule: *-*-* 06:30\n", ""), "no front matter",
                    ROLE.replace("model: haiku", "kind: script\nscript: rm")):
            with self.assertRaises(ValueError):
                C.parse_role(bad, "x")

    def test_role_names(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            C.load("../etc")


class Argv(Base):
    def test_the_agent_gets_only_its_verbs(self):
        self.role()
        fm, prompt = C.load("test")
        argv = C.claude_argv(fm, prompt, tool="/x/crew_tool.py")
        self.assertTrue(os.path.isabs(argv[0]))
        i = argv.index("--allowedTools")
        allowed = argv[i + 1: argv.index("--permission-mode")]
        self.assertEqual(allowed, ["Bash(/x/crew_tool.py today:*)", "Bash(/x/crew_tool.py agenda:*)",
                                   "Bash(/x/crew_tool.py get:*)", "WebFetch(domain:api.open-meteo.com)"])
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash,WebFetch")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.10")
        self.assertNotIn("--add-dir", argv)
        brief = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("crew_test", brief)
        self.assertIn("URGENT:", brief)
        self.assertNotIn("post", brief.split("Your orders")[0].replace("posted", ""))

    def test_a_reader_cannot_read_the_journal_file(self):
        self.role(text=ROLE.replace("web: api.open-meteo.com", "read: repo"))
        fm, prompt = C.load("test")
        argv = C.claude_argv(fm, prompt)
        self.assertIn("Read", argv[argv.index("--tools") + 1])
        denied = argv[argv.index("--disallowedTools") + 1: argv.index("--add-dir")]
        self.assertIn(f"Read(/{C.REPO}/lcars.db)", denied)
        self.assertIn(f"Read(/{C.REPO}/**/.env)", denied)

    def test_the_child_has_no_credentials(self):
        self.role()
        fm, _ = C.load("test")
        with mock.patch.dict(os.environ, {"LCARS_AUTH_PASS": "x", "LCARS_CREW_PASS": "y", "CLAUDECODE": "1"}):
            env = C.child_env(fm)
        self.assertEqual(env["CREW_IN_AGENT"], "1")
        self.assertEqual(env["CREW_ROLE"], "test")
        for k in ("LCARS_AUTH_PASS", "LCARS_CREW_PASS", "CLAUDECODE"):
            self.assertNotIn(k, env)


class Folded(Base):
    """The linker and the sysadmin check, folded in from ~/.claude (0.143.0)."""

    def test_the_linker_pass_keeps_its_own_write_path(self):
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            fm, prompt = C.load("yeoman-linker")
        self.assertEqual((fm["posts"], fm["pre"], fm["brief"], fm["schedule"]), ("yeoman", "measure", "own", "*-*-* 23:12"))
        argv = C.claude_argv(fm, prompt)
        allowed = argv[argv.index("--allowedTools") + 1: argv.index("--permission-mode")]
        self.assertEqual(allowed, [f"Bash({C.REPO}/scripts/lcars-link.sh:*)", f"Read(/{C.HOME}/.lcars-linker/**)"])
        self.assertEqual(argv[argv.index("--tools") + 1], "Bash,Read")      # no Write, as before
        self.assertEqual(argv[argv.index("--effort") + 1], "high")         # the user setting it ran under
        brief = argv[argv.index("--append-system-prompt") + 1]
        self.assertNotIn("~/.claude", brief)
        self.assertNotIn("{repo}", brief)
        self.assertIn(f"{C.REPO}/scripts/lcars-link.sh apply --scan", brief)
        self.assertNotIn("crew_tool.py", brief)
        self.assertIn("crew_yeoman", brief)
        self.assertEqual(C.order(fm, dt.datetime(2026, 10, 10, 23, 12, tzinfo=T.TZ)),
                         "Run your standard pass over 2026-10-10 (the user's local day) and report.")
        for f in ("lcars-link.sh", "lcars_linker.py"):
            self.assertTrue(os.access(os.path.join(HERE, f), os.X_OK), f)

    def test_the_sysadmin_check_is_read_only(self):
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            fm, prompt = C.load("ship")
        self.assertEqual((fm["pre"], fm["brief"], fm["kind"]), ("ship", "own", "agent"))
        argv = C.claude_argv(fm, prompt)
        allowed = argv[argv.index("--allowedTools") + 1: argv.index("--permission-mode")]
        self.assertIn("Bash(apt list --upgradable*)", allowed)
        self.assertIn("Bash([ -f /var/run/reboot-required ]*)", allowed)
        for a in allowed:
            self.assertFalse(re.search(r"apt (install|upgrade)|restart|reboot\b(?!-)", a), a)
        self.assertIn("Never run any command that installs", argv[argv.index("--append-system-prompt") + 1])

    def test_pre_heads_the_entry_and_its_urgency_wins(self):
        t, b, u = C.with_pre(("Ship's health", "- **disk 95%**", "disk full"), "Patches · d", "two updates", None)
        self.assertEqual(t, "Patches · d")
        self.assertTrue(b.startswith("### Ship's health\n\n- **disk 95%**\n\ntwo updates"))
        self.assertEqual(u, "disk full")
        self.assertEqual(C.with_pre(None, "t", "b", "u"), ("t", "b", "u"))
        self.assertEqual(C.with_pre(("M", "x", None), "t", "b", "agent's")[2], "agent's")

    def test_a_folded_run_posts_pre_then_agent(self):
        self.role(text=ROLE.replace("verbs: today agenda get", "verbs:\npre: measure\nbrief: own"))
        stub = os.path.join(self.tmp, "claude")
        with open(stub, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, sys\nsys.stdin.read()\n"
                    "print(json.dumps({'result': '# Linked 3\\n\\n- #1', 'num_turns': 1}))\n")
        os.chmod(stub, 0o755)
        srv = Server()
        os.environ["LCARS_URL"] = srv.url
        try:
            with mock.patch.object(C, "CLAUDE_BIN", stub), \
                    mock.patch.dict(C.SCRIPTS, {"measure": lambda fm, dry: ("Measure", "- #9: 7h 10m", None)}), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(C.run("test"), 0)
        finally:
            srv.close()
        p = srv.posts[0]
        self.assertEqual(p["kind"], "crew_test")
        self.assertTrue(p["title"].startswith("Linked 3 · "))
        self.assertTrue(p["content"].startswith("### Measure\n\n- #9: 7h 10m\n\n- #1"))

    def test_measure_dry_run_writes_nothing(self):
        calls = []
        with mock.patch.object(C.subprocess, "run", side_effect=lambda cmd, **k: calls.append(cmd) or
                               mock.Mock(returncode=0, stdout="would set #4351", stderr="")):
            title, body, _ = C.run_measure({}, True)
        self.assertEqual(calls[0][1:], ["measure", "--dry-run"])
        self.assertEqual(body, "would set #4351")
        out = "# LCARS measure\nrun at x\n\n- sleep #1: end with no start before it — left empty\n" \
              "- sleep #2: 7h 10m since #1\n\n**1 rows updated.**"
        with mock.patch.object(C.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out, stderr="")):
            _, body, _ = C.run_measure({}, False)
        self.assertEqual(body, "- 1 end rows left empty (no start before them, or a gap out of range)\n"
                               "- sleep #2: 7h 10m since #1\n**1 rows updated.**")

    def test_ship_watches_the_linker_pass(self):
        os.environ["LCARS_URL"] = "http://127.0.0.1:9"
        C.log_run({"ts": int(time.time()) - 7 * 3600, "role": "yeoman-linker", "status": "posted"})
        lines, _ = C.ship_checks(self.tmp)
        self.assertIn("- linker pass posted 7h ago", lines)
        C.log_run({"ts": int(time.time()) - 3600, "role": "yeoman-linker", "status": "failed", "why": "budget"})
        lines, _ = C.ship_checks(self.tmp)
        self.assertIn("- **linker pass failed 1h ago (budget)**", lines)


class Report(Base):
    def test_shape(self):
        self.role()
        fm, _ = C.load("test")
        meta = {"usage": {"input_tokens": 10, "cache_creation_input_tokens": 1990, "cache_read_input_tokens": 8000,
                          "output_tokens": 500}, "num_turns": 3, "total_cost_usd": 0.0421, "secs": 12.4}
        title, body, urgent = C.shape(fm, "# Quiet day\n\n- one thing #12\n\nURGENT: backup is stale", meta, "2026-10-10")
        self.assertEqual(title, "Quiet day · 2026-10-10")
        self.assertTrue(body.startswith("- one thing #12"))
        self.assertEqual(urgent, "backup is stale")
        self.assertIn("10.0k in (8.0k cached) / 500 out", body)
        self.assertIn("$0.042", body)
        title, _, urgent = C.shape(fm, "no heading here", meta, "2026-10-10")
        self.assertEqual(title, "Test, a role · 2026-10-10")
        self.assertIsNone(urgent)
        self.assertIsNone(C.shape(fm, "URGENT:\n", meta, "d")[2])


class Preflight(Base):
    def test_the_lock_is_global(self):
        a = C.take_lock(0)
        self.assertIsNotNone(a)
        t0 = time.monotonic()
        self.assertIsNone(C.take_lock(0.3, step=0.1))
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)
        a.close()
        b = C.take_lock(0)
        self.assertIsNotNone(b)
        b.close()

    def test_wait_for(self):
        n = []
        self.assertTrue(C.wait_for(lambda: n.append(1) or len(n) > 2, 5, 0.01))
        self.assertFalse(C.wait_for(lambda: False, 0.05, 0.01))

    def test_memory_is_read(self):
        self.assertGreater(C.mem_available_mb() or 1, 0)


STUB = """#!/usr/bin/env python3
import json, os, re, sys
order = sys.stdin.read()
open("@LOG@", "w").write(json.dumps({"argv": sys.argv[1:], "order": order, "cwd": os.getcwd(),
                                                   "files": os.listdir("."), "env": sorted(os.environ)}))
# litter like Claude Code's: in its working directory, and a session's
# scratch under <tmp>/claude-<uid>/<the cwd's slug>/<session id>/
open("left.txt", "w").write("x")
pad = os.path.join("@CT@", re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()), "0b8e3c2a-1d4f-4e5a-9b6c-7d8e9f0a1b2c", "scratchpad")
os.makedirs(pad)
open(os.path.join(pad, "copy.db"), "w").write("x")
# the runner hands claude a scrubbed environment, so the mode is a file
mode = open("@MODE@").read() if os.path.exists("@MODE@") else "ok"
if mode == "crash":
    print("not logged in", file=sys.stderr); sys.exit(1)
print(json.dumps({"type": "result", "is_error": False, "num_turns": 2, "total_cost_usd": 0.01,
                  "usage": {"input_tokens": 5, "output_tokens": 7},
                  "result": "# All quiet\\n\\nNothing to report.\\n" + ("URGENT: the disk is full" if mode == "urgent" else "")
                            + ("\\nAdded the week to #2291.\\n\\nCHANGES\\nappend #2291 text=\\"- [[Oct 19th, 2026]] week\\\\n  - apa\\"\\n"
                               if mode == "write" else "")}))
"""


class Run(Base):
    def setUp(self):
        super().setUp()
        self.role()
        self.stub = os.path.join(self.tmp, "claude")
        self.log = os.path.join(self.tmp, "stub.json")
        self.mode = os.path.join(self.tmp, "stub.mode")
        self.tmpdir = os.path.join(self.tmp, "tmp")
        self.ctmp = os.path.join(self.tmp, "claude-tmp")
        os.makedirs(self.tmpdir)
        with open(self.stub, "w") as f:
            f.write(STUB.replace("@LOG@", self.log).replace("@MODE@", self.mode).replace("@CT@", self.ctmp))
        os.chmod(self.stub, 0o755)
        self.srv = Server()
        os.environ["LCARS_URL"] = self.srv.url
        self.ps = [mock.patch.object(C, "CLAUDE_BIN", self.stub), mock.patch.object(C, "CLAUDE_TMP", self.ctmp),
                   mock.patch.object(tempfile, "tempdir", self.tmpdir)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        self.srv.close()
        super().tearDown()

    def go(self, *a):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = C.run("test", *a)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def test_a_run_posts_one_entry_as_the_crew(self):
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.srv.posts), 1)
        p = self.srv.posts[0]
        self.assertEqual(p["kind"], "crew_test")
        self.assertTrue(p["title"].startswith("All quiet · "))
        self.assertIn("·".encode(), self.srv.raw[0])   # bytes, never a \u escape
        self.assertNotIn(b"\\u00b7", self.srv.raw[0])
        self.assertIn("Nothing to report.", p["content"])
        self.assertIn("*crew.py test · haiku · 2 turns", p["content"])
        import base64
        self.assertEqual(self.srv.auth[-1], "Basic " + base64.b64encode(b"crew:pass with spaces").decode())
        with open(self.log) as f:
            s = json.load(f)
        self.assertEqual(s["files"], [])               # an empty working directory
        self.assertNotEqual(s["cwd"], os.getcwd())
        self.assertFalse(os.path.exists(s["cwd"]))     # and gone afterwards
        self.assertIn("Run your test pass", s["order"])
        self.assertNotIn("LCARS_CREW_PASS", s["env"])
        runs = C.read_runs()
        self.assertEqual(runs[-1]["status"], "posted")
        self.assertEqual(runs[-1]["entry"], 101)
        self.assertEqual(runs[-1]["tokens_out"], 7)

    def test_urgent_posts_a_task_too(self):
        with open(self.mode, "w") as f:
            f.write("urgent")
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual([p["kind"] for p in self.srv.posts], ["crew_test", "task_crew"])
        self.assertEqual(self.srv.posts[1]["title"], "the disk is full")
        self.assertIn("#101", self.srv.posts[1]["content"])

    def test_a_failed_run_is_posted_as_failed(self):
        with open(self.mode, "w") as f:
            f.write("crash")
        rc, _ = self.go()
        self.assertEqual(rc, 1)
        self.assertTrue(self.srv.posts[0]["title"].endswith("· failed"))
        self.assertIn("not logged in", self.srv.posts[0]["content"])
        self.assertEqual(C.read_runs()[-1]["status"], "failed")

    def test_no_post_and_dry_run_post_nothing(self):
        rc, out = self.go(False, True)
        self.assertEqual(rc, 0)
        self.assertIn("# All quiet", out)
        rc, out = self.go(True)
        self.assertEqual(rc, 0)
        self.assertIn('"server_up": true', out)
        self.assertEqual(self.srv.posts, [])

    def scratch(self):
        return sorted(os.listdir(self.tmpdir)), sorted(os.listdir(self.ctmp)) if os.path.isdir(self.ctmp) else []

    def test_a_run_leaves_no_scratch(self):
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        cwd = json.load(open(self.log))["cwd"]
        self.assertTrue(os.path.basename(cwd).startswith("lcars-crew-test-"))
        self.assertEqual(self.scratch(), ([], []))

    def test_a_failed_run_leaves_no_scratch(self):
        with open(self.mode, "w") as f:
            f.write("crash")
        rc, _ = self.go()
        self.assertEqual(rc, 1)
        self.assertEqual(self.scratch(), ([], []))

    def test_a_killed_runs_scratch_goes_with_the_next_run(self):
        # what a run killed past MemoryMax leaves: its directory and Claude's
        # scratch for it, and Claude's scratch for one whose directory went
        dead = os.path.join(self.tmpdir, "lcars-crew-ops-abc123")
        os.makedirs(os.path.join(dead, "sub"))
        os.makedirs(os.path.join(self.tmpdir, "lcars-qa-xyz", "lcars-ui"))
        for d in (dead, os.path.join(self.tmpdir, "lcars-crew-yeoman-gone")):
            os.makedirs(os.path.join(self.ctmp, re.sub(r"[^A-Za-z0-9]", "-", d), "0b8e3c2a-1d4f-4e5a-9b6c-7d8e9f0a1b2c"))
        # not a crew run's: kept
        mine = re.sub(r"[^A-Za-z0-9]", "-", os.path.join(self.tmpdir, "other"))
        os.makedirs(os.path.join(self.tmpdir, "other"))
        os.makedirs(os.path.join(self.ctmp, mine))
        os.makedirs(os.path.join(self.ctmp, "bash-edit-diff"))
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(self.scratch(), (["other"], sorted([mine, "bash-edit-diff"])))

    def test_a_held_lock_skips(self):
        held = C.take_lock(0)
        try:
            rc, _ = self.go()
        finally:
            held.close()
        self.assertEqual(rc, 75)
        self.assertEqual(self.srv.posts, [])
        self.assertEqual(C.read_runs()[-1]["status"], "skipped")

    def test_short_memory_skips(self):
        self.role(text=ROLE.replace("min_free_mb: 0", "min_free_mb: 99999999"))
        rc, _ = self.go()
        self.assertEqual(rc, 75)
        self.assertIn("needs 99999999MB", C.read_runs()[-1]["why"])

    def test_a_writes_role_appends_and_the_report_carries_the_fence(self):
        self.role(text=ROLE.replace("min_free_mb: 0", "min_free_mb: 0\nwrites: append #2291\nwriter: Test officer"))
        with open(T.ENV_FILE, "a") as f:
            f.write("LCARS_STEWARD_USER=steward\nLCARS_STEWARD_PASS=sp\n")
        self.srv.close()
        self.srv = Server(rows=[{"id": 2291, "kind": "page", "content": "- words", "last_modified_at_utc": "2026-09-07 07:30:48"}])
        os.environ["LCARS_URL"] = self.srv.url
        with open(self.mode, "w") as f:
            f.write("write")
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(self.srv.paths, ["/entries/2291/append", "/entries"])
        ap = self.srv.posts[0]
        self.assertEqual(ap["if_modified"], "2026-09-07 07:30:48")      # the runner's own read
        self.assertRegex(ap["text"], r"^\n\n> Test officer added, \d{4}-\d\d-\d\d \d\d:\d\d:\n> - \[\[Oct 19th, 2026\]\] week\n>   - apa$")
        import base64
        self.assertEqual(self.srv.auth[-2], "Basic " + base64.b64encode(b"steward:sp").decode())
        rep = self.srv.posts[1]["content"]
        self.assertNotIn("CHANGES\n", rep)
        self.assertIn("- added to #2291: - [[Oct 19th, 2026]] week", rep)
        fence = re.search(r"```crew-changes\n(.*)\n```", rep).group(1)
        self.assertEqual(json.loads(fence), {"op": "append", "id": 2291, "text": ap["text"]})
        self.assertLess(rep.index("```crew-changes"), rep.index("*crew.py test"))   # above the footer
        self.assertEqual(C.read_runs()[-1]["changes"], 1)
        with open(os.path.join(C.STATE, "notes-writes.jsonl")) as f:
            log = [json.loads(x) for x in f]
        self.assertEqual([(x["status"], x["role"], x["id"]) for x in log], [("applied", "test", 2291)])

    def test_a_role_without_writes_writes_nothing(self):
        with open(self.mode, "w") as f:
            f.write("write")
        rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(self.srv.paths, ["/entries"])
        self.assertIn("declares no writes", self.srv.posts[0]["content"])
        self.assertNotIn("crew-changes", self.srv.posts[0]["content"])

    def test_a_down_server_skips(self):
        self.srv.close()
        self.srv = Server(healthy=False)
        os.environ["LCARS_URL"] = self.srv.url
        rc, _ = self.go()
        self.assertEqual(rc, 75)
        self.assertFalse(os.path.exists(self.log))   # claude never started


class Writes(Base):
    """scheduled_apply: a writes role's CHANGES lines, against a stand-in
    row and steward (the notes' apply_change does the writing)."""

    FM = {"role": "science", "title": "Science, weekly stats", "writes": "append #2291", "writer": "Science officer"}

    def setUp(self):
        super().setUp()
        with open(T.ENV_FILE, "a") as f:
            f.write("LCARS_STEWARD_USER=steward\nLCARS_STEWARD_PASS=sp\n")
        self.calls, self.log = [], []
        self.row = {"id": 2291, "kind": "page", "content": "- words", "last_modified_at_utc": "2026-10-19 01:00:00"}
        self.t = T.stamp("2026-10-19 02:00:00").timestamp()
        self.ps = [mock.patch.object(N, "get_row", lambda rid: dict(self.row, id=rid)),
                   mock.patch.object(N, "steward", lambda m, p, b=None: self.calls.append((m, p, b)) or (200, "{}")),
                   mock.patch.object(N, "now", lambda: self.t)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        super().tearDown()

    def go(self, *lines, fm=None):
        return C.scheduled_apply(dict(self.FM, **(fm or {})), list(lines), self.log.append)

    def test_an_allowed_append_is_made_on_a_fresh_read(self):
        out, recs = self.go('append #2291 text="- [[Oct 19th, 2026]] week 13 to 19 Oct 2026\\n  - apa"')
        self.assertEqual(len(self.calls), 1)
        m, path, body = self.calls[0]
        self.assertEqual((m, path, body["if_modified"]), ("POST", "/entries/2291/append", "2026-10-19 01:00:00"))
        self.assertTrue(body["text"].startswith("\n\n> Science officer added, "))
        self.assertTrue(body["text"].endswith(":\n> - [[Oct 19th, 2026]] week 13 to 19 Oct 2026\n>   - apa"))
        self.assertEqual(recs, [{"op": "append", "id": 2291, "text": body["text"]}])
        self.assertIn("- added to #2291: - [[Oct 19th, 2026]]", out)
        self.assertIn("```crew-changes\n" + json.dumps(recs[0], ensure_ascii=False) + "\n```", out)
        self.assertEqual([x["status"] for x in self.log], ["applied"])

    def test_a_target_not_declared_is_refused(self):
        out, recs = self.go('append #2581 text="x"')
        self.assertEqual((self.calls, recs), ([], []))
        self.assertIn("#2581 is not one this role may add to (append #2291)", out)
        self.assertEqual([(x["status"], x["line"]) for x in self.log], [("refused", 'append #2581 text="x"')])
        self.assertNotIn("crew-changes", out)

    def test_create_and_title_are_refused(self):
        out, recs = self.go('create kind=page title="Ada, again" text="x"',
                            'title #2291 at="2026-10-19 01:00:00" text="Ada"', "delete #2291")
        self.assertEqual((self.calls, recs), ([], []))
        self.assertIn("a scheduled run only appends; create is not allowed", out)
        self.assertIn("a scheduled run only appends; title is not allowed", out)
        self.assertIn("a scheduled run only appends; delete is not allowed", out)
        self.assertEqual([x["status"] for x in self.log], ["refused"] * 3)

    def test_a_second_append_is_refused(self):
        out, recs = self.go('append #2291 text="one"', 'append #2291 text="two"')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(recs), 1)
        self.assertIn("a run makes at most 1 append", out)
        self.assertEqual([x["status"] for x in self.log], ["applied", "refused"])

    def test_the_quiet_rule(self):
        self.t = T.stamp("2026-10-19 01:00:10").timestamp()       # 10s after the captain's last edit
        out, recs = self.go('append #2291 text="one"')
        self.assertEqual((self.calls, recs), ([], []))
        self.assertIn("is being edited (changed under 20s ago)", out)
        self.assertEqual(self.log[0]["status"], "refused")

    def test_a_role_without_writes_and_no_steward(self):
        out, _ = self.go('append #2291 text="one"', fm={"writes": ""})
        self.assertIn("declares no writes", out)
        with open(T.ENV_FILE, "w") as f:
            f.write("LCARS_CREW_USER=crew\n")
        out, _ = self.go('append #2291 text="one"')
        self.assertIn("steward login is not set up", out)
        self.assertEqual(self.calls, [])

    def test_writes_front_matter(self):
        fm, _ = C.parse_role("---\nschedule: x\nwrites: append #2291 #12   # a comment\n---\nGo.", "t")
        self.assertEqual(C.write_targets(fm), {2291, 12})
        for bad in ("create #1", "append", "append 2291", "title #1"):
            with self.assertRaises(ValueError):
                C.parse_role(f"---\nschedule: x\nwrites: {bad}\n---\nGo.", "t")
        with self.assertRaises(ValueError):
            C.parse_role("---\nschedule: x\nbrief: own\nwrites: append #1\n---\nGo.", "t")
        self.assertIn("adding one block to the end of #12 or #2291", C.writes_brief(fm))
        self.assertIn("You cannot change anything", C.writes_brief(dict(fm, writes="")))
        # the science role's page is the captain's: crew/context.local.md names it
        real, _ = C.parse_role(open(os.path.join(os.path.dirname(HERE), "crew", "science.md")).read(), "science")
        self.assertEqual((C.write_targets(real), real["writer"]), (set(), ""))
        with mock.patch.object(C, "CREW_DIR", os.path.join(os.path.dirname(HERE), "crew")):
            if os.path.exists(os.path.join(C.CREW_DIR, C.LOCAL_CONTEXT)):
                real, _ = C.load("science")
                self.assertEqual((C.write_targets(real), real["writer"]), ({2291}, "Science officer"))


class Tool(Base):
    def test_env_is_parsed_not_sourced(self):
        e = T.read_env()
        self.assertEqual(e["LCARS_CREW_PASS"], "pass with spaces")
        self.assertEqual(e["LCARS_AUTH_PASS"], "captain")

    def test_the_agent_cannot_post(self):
        with mock.patch.dict(os.environ, {"CREW_IN_AGENT": "1"}), self.assertRaises(SystemExit) as e:
            T.post("test", "t", "c")
        self.assertEqual(e.exception.code, 3)

    def test_post_kinds(self):
        srv = Server()
        try:
            os.environ["LCARS_URL"] = srv.url
            T.post("ops", "t", "c")
            T.post("ops", "u", "c", urgent=True)
            self.assertEqual([p["kind"] for p in srv.posts], ["crew_ops", "task_crew"])
            with self.assertRaises(SystemExit):
                T.post("Ops; rm", "t", "c")
        finally:
            srv.close()

    def test_cli_escapes_are_refused(self):
        for bad in (["--db"], ["--db-path", "x"], ["--url", "http://x"], ["--user=a"], ["--password", "p"]):
            with self.assertRaises(SystemExit):
                T.cmd_cli("list", bad)

    def test_unknown_verbs_are_refused(self):
        for v in ("set", "rm", "new", "done"):
            with self.assertRaises(SystemExit):
                T.main([v, "1"])

    def test_local_days_across_dst(self):
        self.assertEqual(T.utc_window(dt.date(2026, 10, 10)), ("2026-10-09 21:00:00", "2026-10-10 20:59:59"))
        self.assertEqual(T.utc_window(dt.date(2026, 12, 1)), ("2026-11-30 22:00:00", "2026-12-01 21:59:59"))
        # the night the clocks go back is 25 hours long
        lo, hi = T.utc_window(dt.date(2026, 10, 25))
        self.assertEqual((lo, hi), ("2026-10-24 21:00:00", "2026-10-25 21:59:59"))

    def test_week_numbers(self):
        rows = [{"kind": "sleep", "value_float": 7.5, "created_at_utc": "2026-10-05 05:00:00"},
                {"kind": "sleep", "value_float": 6.5, "created_at_utc": "2026-10-06 05:00:00"},
                {"kind": "sleep", "value_float": 0, "content": "start", "created_at_utc": "2026-10-05 21:00:00"},
                {"kind": CV, "title": "trei", "value_int": 151, "created_at_utc": "2026-10-05 10:00:00"},
                {"kind": CV, "title": "patru", "value_int": 152, "created_at_utc": "2026-10-06 10:00:00"},
                {"kind": "personal_log", "content": "one two three", "created_at_utc": "2026-10-06 22:30:00"},
                {"kind": "counter", "title": "diaper", "value_int": 1, "created_at_utc": "2026-10-05 08:00:00"},
                {"kind": "counter", "title": "Diaper", "value_int": 1, "created_at_utc": "2026-10-06 08:00:00"},
                {"kind": "counter", "title": "feed", "value_int": 1, "created_at_utc": "2026-10-06 09:00:00"},
                {"kind": "counter", "title": "feed", "value_int": 1, "deleted": 1, "created_at_utc": "2026-10-06 10:00:00"}]
        n = T.week_numbers(rows)
        self.assertEqual(dict(n["counters"]), {"diaper": 2, "feed": 1})   # by title, a deleted one not counted
        self.assertEqual(n["series"]["sleep"], {"unit": "h", "n": 2, "total": 14.0, "avg": 7.0, "min": 6.5, "max": 7.5})
        self.assertEqual(n["vocab"], ["trei", "patru"])
        self.assertEqual(n["vocab_total"], 152)
        self.assertEqual(n["words"], 3)
        self.assertEqual(n["by_day"]["Wed 07"], 1)    # 22:30 UTC is the next day in Helsinki
        self.assertNotIn("gym", n["series"])

    def test_week_numbers_gym_and_spans(self):
        span = lambda s, e: {"start_date": s, "end_date": e}
        rows = [{"kind": "personal_log", "title": "HTTP Entry", "content": "at gym . ", "value_float": 52.0,
                 "created_at_utc": "2026-10-14 09:34:23", **span("2026-10-14 09:34:23", "2026-10-14 10:26:50")},
                {"kind": "personal_log", "title": "gym", "content": "pull", "value_float": 67.0,
                 "created_at_utc": "2026-10-13 17:35:57"},
                {"kind": "personal_log", "title": "HTTP Entry", "content": "Ana is at the gym",
                 "created_at_utc": "2026-10-13 16:51:58"},                       # no value: not a session
                {"kind": "drive", "value_float": 41.0, "content": "end", "created_at_utc": "2026-10-13 17:06:23"},
                # a stopwatch-timed night, measured: its evening, not the one before
                {"kind": "sleep", "value_float": 7.46, "content": "start", "created_at_utc": "2026-10-12 19:24:00",
                 **span("2026-10-12 19:17:40", "2026-10-13 02:45:25")}]
        n = T.week_numbers(rows)
        self.assertEqual(n["series"]["gym"], {"unit": "min", "n": 2, "total": 119.0, "avg": 59.5, "min": 52.0, "max": 67.0})
        self.assertEqual(n["series"]["drive"]["total"], 41.0)
        self.assertEqual(n["series"]["sleep"]["n"], 1)
        self.assertEqual(T._night_hours(rows), {dt.date(2026, 10, 12): 7.5})
        with redirect_stdout(io.StringIO()) as out:
            T._print_week("Week", n)
        self.assertIn("  gym: 2 measured, avg 59.5min, min 52.0, max 67.0, total 119.0min", out.getvalue())

    def test_weather_place(self):
        day, now = dt.date(2026, 10, 15), dt.datetime(2026, 10, 15, 3, 30, tzinfo=dt.timezone.utc)
        block = lambda name: f'1. {name} — 14:00\n\n```json trip\n{{"v":1,"points":[{{"name":"{name}","lat":39.8,"lon":2.9}}]}}\n```'
        trip = lambda i, s, e="", name="Valdemar": {"id": i, "kind": "trip", "title": "t", "start_date": s, "end_date": e,
                                                     "content": block(name)}
        # the bug of #5206: the newest trip, ended the evening before last
        ended = [trip(4741, "2026-10-12 20:00:00"), trip(4755, "2026-10-12 20:00:00", "2026-10-12 20:18:34")]
        self.assertEqual(T.weather_place(ended, day, now, "Tampere"),
                         ("Tampere", None, None, "home: trip #4755 ended Mon 12 Oct 23:18"))
        # running today: its first stop, with the planner's coordinates
        running = ended + [trip(5300, "2026-10-14 06:00:00", "2026-10-16 18:00:00", "Montclar")]
        self.assertEqual(T.weather_place(running, day, now, "Tampere"), ("Montclar", 39.8, 2.9, "trip #5300 running today"))
        later = ended + [trip(5301, "2026-10-15 12:00:00", name="Serrat")]
        self.assertEqual(T.weather_place(later, day, now, "X")[3], "trip #5301 running today")
        # started in the last three days and not ended: no end_date, or one still ahead
        open_ = [trip(5200, "2026-10-13 08:00:00", name="Portbella")]
        self.assertEqual(T.weather_place(open_, day, now, "X")[:1], ("Portbella",))
        self.assertIn("not ended", T.weather_place(open_, day, now, "X")[3])
        # too old to count, or none at all: home
        self.assertEqual(T.weather_place([trip(1, "2026-10-10 08:00:00")], day, now, "Cluj")[0], "Cluj")
        self.assertEqual(T.weather_place([], day, now, "Cluj"), ("Cluj", None, None, "home: no trip in the last three days"))
        # without a trip block, the "1. <stop> — hh:mm" line, then the title
        self.assertEqual(T.trip_first_stop({"content": "**x**\n\n1. Carrer del Pou — 10:30\n2. y"})[0], "Carrer del Pou")
        self.assertEqual(T.trip_first_stop({"title": "Sibiu", "content": ""})[0], "Sibiu")

    # ---- secrets (hygiene) --------------------------------------------------
    # Every token here is made up and built from parts at run time, so no
    # secret-shaped literal sits in the repository (GitHub's push protection
    # would refuse the push, and a scanner would cry wolf).

    @staticmethod
    def fake(prefix, n, alphabet="aB3dE5gH7jK9mN1pQ2rS4tU6vW8xY0z"):
        return prefix + "".join(alphabet[(i * 7 + 3) % len(alphabet)] for i in range(n))

    def secret_rows(self):
        glc = self.fake("gl" + "c_", 120)
        jwt = ".".join(["ey" + "J" + self.fake("", 30), "ey" + "J" + self.fake("", 40), self.fake("", 43)])
        hexrun = "".join("0123456789abcdef"[(i * 5 + 1) % 16] for i in range(40))
        row = lambda i, kind, content, title="note": {"id": i, "kind": kind, "title": title, "content": content,
                                                       "created_at_utc": "2026-10-13 12:33:42"}
        return glc, jwt, hexrun, [
            row(4824, "personal_log", f"grafana cloud\n{glc}"),
            row(1, "page", f"curl -H 'Authorization: Bearer {self.fake('', 24)}' https://x"),
            row(2, "personal_log", f"the session cookie was {jwt} today"),
            row(3, "project", f"commit and key: {hexrun}"),
            row(4, "personal_log", "password: Summer" + "2024!x\ntoken: none\napi key: <yours>"),
            row(5, "personal_log", "We walked to the beach and Ada found a shell. Then lunch, then a nap."),
            row(6, "personal_log", "a file Blender_Scene_v2_Final_Render_Output_0001.png and /usr/local/share/applications/x"),
            row(7, "crew_yeoman", f"seen: {glc}"),
            row(8, "no1_log", f"seen: {glc}"),
            row(9, "logseq_journal", f"old: {glc}"),
            row(10, "task_crew", f"rotate {glc}"),
        ]

    def test_secret_prefixes(self):
        for pre, n, what in (("gl" + "c_", 60, "Grafana Cloud"), ("gl" + "sa_", 32, "Grafana service"),
                             ("s" + "k-ant-", 40, "API secret key"), ("gh" + "p_", 36, "GitHub token"),
                             ("gh" + "o_", 36, "GitHub token"), ("github" + "_pat_", 60, "fine-grained"),
                             ("AK" + "IA", 16, "AWS"), ("xo" + "xb-", 30, "Slack"), ("xo" + "xp-", 30, "Slack"),
                             ("AI" + "za", 35, "Google API"), ("ya" + "29.", 40, "OAuth")):
            alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ234567" if pre.startswith("AK") else "aB3dE5gH7jK9mN1pQ2rS4tU6vW8xY0z"
            v = self.fake(pre, n, alpha)
            got = T.find_secrets(f"pasted it here: {v}. done")
            self.assertEqual([x[0] for x in got], [v], pre)
            self.assertIn(what, got[0][1], pre)

    def test_secret_shapes(self):
        glc, jwt, hexrun, rows = self.secret_rows()
        self.assertEqual(T.find_secrets(rows[2]["content"]), [(jwt, "a JWT")])   # not also a long run
        self.assertEqual(T.find_secrets(rows[3]["content"])[0][1], "a long hex run (a key, or a hash?)")
        self.assertEqual(T.find_secrets(rows[1]["content"])[0][1], "a Bearer token")
        found = T.find_secrets(rows[4]["content"])
        self.assertEqual(len(found), 1)                     # "none" and "<yours>" are remarks
        self.assertEqual(found[0][1], "a value after 'password:'")
        self.assertEqual(T.find_secrets(rows[5]["content"]), [])    # a plain sentence
        self.assertEqual(T.find_secrets(rows[6]["content"]), [])    # a file name, a path
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(T.find_secrets(f"id {uuid} and https://docs.example.com/d/{self.fake('', 44)}/edit"), [])

    def test_secret_mask(self):
        glc = self.fake("gl" + "c_", 120)
        self.assertEqual(T.mask(glc), "glc_… (124 chars)")
        self.assertEqual(T.mask("Summer2024"), "Su… (10 chars)")    # a short one shows less
        self.assertEqual(T.redact(f"x {glc} y", {glc}), "x glc_… (124 chars) y")

    def test_secret_findings_read_only_his_kinds(self):
        glc, jwt, hexrun, rows = self.secret_rows()
        out = T.secret_findings(rows)
        ids = {int(re.match(r"#(\d+)", t).group(1)) for _, t in out}
        self.assertEqual(ids, {4824, 1, 2, 3, 4})          # never crew_*, no1_*, task_crew or an import
        line = next(t for _, t in out if t.startswith("#4824 "))
        self.assertEqual(line, "#4824 [personal_log] 13 Oct 2026: glc_… (124 chars) - a Grafana Cloud token; "
                               "the entry has 2 other words")
        for _, t in out:
            for v in (glc, jwt, hexrun, "Summer" + "2024!x"):
                self.assertNotIn(v, t)

    def test_hygiene_never_prints_a_secret(self):
        glc, jwt, hexrun, rows = self.secret_rows()
        # a twin of #4824 too: the duplicates section quotes its text
        rows.append(dict(rows[0], id=4825, created_at_utc="2026-10-13 12:34:00"))
        buf = io.StringIO()
        with mock.patch.object(T, "entries_all", return_value=rows), \
                mock.patch.object(T, "kinds", return_value={"personal_log": 50}), redirect_stdout(buf):
            T.cmd_hygiene([])
        out = buf.getvalue()
        self.assertLess(out.index("secrets ("), out.index("duplicates ("))
        self.assertIn("#4824 [personal_log] 13 Oct 2026: glc_… (124 chars) - a Grafana Cloud token", out)
        self.assertIn("#4824 and #4825", out)
        for v in (glc, jwt, hexrun, "Summer" + "2024!x", glc[:12]):
            self.assertNotIn(v, out)

    # ---- trip ------------------------------------------------------------------

    def trip_rows(self):
        block = {"v": 1, "depart": "2026-10-11T09:30",
                 "points": [{"name": "Home", "stay": 0}, {"name": "Cala Blava", "stay": 15}, {"name": "Home", "stay": 0}],
                 "legs": [{"mode": "car"}, {"mode": "car"}], "calc": [{"len": 54000, "dur": 2580}, {"len": 55000, "dur": 2580}]}
        body = ("**Home → Home** — departs Sun 11 Oct 09:30\n\n1. Home — 09:30\n   ↓ drive · 54 km · 43m\n"
                "2. Cala Blava — 10:13, stay 15m\n   ↓ drive · 55 km · 43m\n3. Home — 11:11\n\n"
                "```json trip\n" + json.dumps(block) + "\n```\n")
        trip = {"id": 4486, "kind": "trip", "title": "Home → Home", "content": body,
                "start_date": "2026-10-11 07:30:00", "end_date": "2026-10-11 14:16:30"}
        r = lambda i, kind, at, content="", title="", **kw: dict({"id": i, "kind": kind, "title": title, "content": content,
                                                                   "created_at_utc": at}, **kw)
        rows = [trip,
                r(10, "drive", "2026-10-11 07:31:00", "start Carrer del Pou, 9\n07999 Valdemar"),
                r(11, "drive", "2026-10-11 08:20:00", "end Cala Blava\n07998 Miraval", "49 min", value_float=49.0),
                r(12, "drive", "2026-10-11 13:20:00", "start Cala Blava\n07998 Miraval"),
                r(13, "drive", "2026-10-11 14:05:00", "end Carrer del Pou, 9\n07999 Valdemar · 54.5 km", value_float=45.0),
                r(20, "personal_log", "2026-10-11 09:00:00", "stopped to let ada down\n\nMiraval (39.71234, 2.71234 ±5 m)",
                  "stop"),
                r(21, "personal_log", "2026-10-11 10:30:00", "lunch. paid 12 € for parking. lesson: leave earlier.", "lunch"),
                r(22, "personal_log", "2026-10-10 21:30:00", "the evening before, local time", "late"),   # 23:30 Fri
                r(23, "crew_historian", "2026-10-11 03:10:00", "a report"),
                r(24, CV, "2026-10-11 11:00:00", "cais", "cais"),
                r(25, "personal_log", "2026-10-11 12:00:00", "deleted", "gone", deleted=1),
                r(26, "trip", "2026-10-11 14:00:00", "", "valldemossa walk")]
        media = {20: ["image/jpeg", "image/heic", "video/mp4"], 21: ["application/pdf"]}
        return trip, rows, media

    def test_trip_zone_and_days(self):
        trip, _, _ = self.trip_rows()
        tz = T.trip_zone(trip)               # depart 09:30 at 07:30 UTC: +2, not Helsinki's +3
        self.assertEqual(tz.utcoffset(None), dt.timedelta(hours=2))
        self.assertEqual(T.trip_days(trip), [dt.date(2026, 10, 11)])
        # no end: the departure plus the legs and the stays is its last stop
        open_ = dict(trip, end_date="", start_date="2026-10-11 21:00:00",
                     content=trip["content"].replace("2026-10-11T09:30", "2026-10-11T23:00"))
        self.assertEqual(T.trip_end(open_), dt.datetime(2026, 10, 11, 22, 41, tzinfo=dt.timezone.utc))
        self.assertEqual(T.trip_days(open_), [dt.date(2026, 10, 11), dt.date(2026, 10, 12)])
        self.assertIs(T.trip_zone({"start_date": "2026-10-11 07:30:00", "content": ""}), T.TZ)

    def test_trip_report(self):
        trip, rows, media = self.trip_rows()
        out = "\n".join(T.trip_report(trip, rows, media))
        self.assertIn("departs Sun 11 Oct 2026 09:30, ends Sun 11 Oct 16:16 (times: UTC+2, the trip's own)", out)
        self.assertIn("Planned (3 stops):\n  1. Home at 09:30\n     ↓ drive · 54 km · 43m\n"
                      "  2. Cala Blava at 10:13, stay 15m", out)
        self.assertIn("planned total: 109.0 km, 86 min on the move", out)
        self.assertIn("drives (2 legs, 94 min, 54.5 km):", out)
        self.assertIn("Carrer del Pou, 9 → Cala Blava: 49 min", out)
        self.assertIn("Cala Blava → Carrer del Pou, 9: 45 min, 54.5 km", out)
        self.assertIn("other trip plans this day: #26 valldemossa walk", out)
        self.assertIn("entries (2):", out)
        self.assertIn("11:00 #20 [personal_log] stop [2 photos, 1 videos]", out)
        self.assertIn("at Miraval (39.71234, 2.71234)", out)
        self.assertIn("12:30 #21 [personal_log] lunch [1 other files]", out)
        self.assertIn("money: paid 12 € for parking.", out)
        self.assertIn(f"also: 1 {CV}", out)
        for gone in ("#22 ", "#23 ", "#25 ", "a report"):     # another day, the crew's, deleted
            self.assertNotIn(gone, out)
        self.assertTrue(out.endswith("Totals: 2 drive legs, 94 min driving, 54.5 km recorded on 1 legs "
                                     "(planned 109.0 km, 86 min); 2 entries, 1 with a location; 2 photos, "
                                     "1 videos, 1 other files; 1 lines about money"), out[-300:])

    def test_trip_verb(self):
        trip, rows, media = self.trip_rows()
        now = dt.datetime(2026, 10, 12, 2, 10, tzinfo=dt.timezone.utc)
        ended = [trip, dict(trip, id=4700, end_date="2026-10-13 10:00:00"), dict(trip, id=4701, deleted=1)]
        self.assertEqual([r["id"] for r in T.ended_trips(ended, now - dt.timedelta(days=1), now)], [4486])
        self.assertEqual(T.ended_trips(ended, dt.datetime(2026, 10, 11, 15, tzinfo=dt.timezone.utc), now), [])
        # `trip <id>`: the row, its days' rows, their media in one GET /media
        def http(method, path, body=None, timeout=60, login=None):
            if path == "/entries/4486":
                return 200, json.dumps(trip)
            if path == "/media":
                return 200, json.dumps([{"entry_id": i, "mime": m} for i, ms in media.items() for m in ms]
                                       + [{"entry_id": 999, "mime": "image/jpeg"}])
            return 404, "{}"
        buf = io.StringIO()
        with mock.patch.object(T, "http", side_effect=http), \
                mock.patch.object(T, "entries_all", return_value=rows) as ea, redirect_stdout(buf):
            T.cmd_trip(["4486"])
        self.assertEqual(ea.call_args.kwargs["since"], "2026-10-10 22:00:00")    # its zone's midnight
        self.assertIn("2 photos, 1 videos, 1 other files", buf.getvalue())
        with mock.patch.object(T, "http", return_value=(200, json.dumps(dict(trip, kind="personal_log")))), \
                self.assertRaises(SystemExit):
            T.cmd_trip(["4486"])

    def test_home_setting(self):
        views = {"id": 3994, "kind": "settings", "title": "views", "content": '{"v": 1, "views": []}'}
        self.assertEqual(T.home_place([]), "Helsinki")        # the zone's city
        self.assertEqual(T.home_place([views]), "Helsinki")
        self.assertEqual(T.home_place([views, {"id": 4000, "kind": "settings", "title": "home", "content": "Cluj-Napoca\n"}]),
                         "Cluj-Napoca")
        self.assertEqual(T.home_place([{"id": 9, "kind": "settings", "title": "places", "content": '{"home": "Brașov"}'}]),
                         "Brașov")
        self.assertEqual(T.home_place([{"id": 9, "kind": "settings", "title": "home", "content": "Iași", "deleted": 1}]),
                         "Helsinki")

    def test_agenda_place_line(self):
        rows = {"trip": [{"id": 7, "kind": "trip", "title": "t", "start_date": "2026-10-14 06:00:00",
                          "end_date": "2026-10-14 08:00:00", "content": "1. Valdemar — 09:00"}],
                "settings": [{"id": 1, "kind": "settings", "title": "home", "content": "Cluj"}]}
        fake = lambda **q: rows.get(q.get("kind"), [])
        out = io.StringIO()
        with mock.patch.object(T, "entries", fake), mock.patch.object(T, "entries_all", fake), \
                mock.patch.object(T, "kinds", lambda: {}), redirect_stdout(out):
            T.cmd_agenda(["2026-10-15"])
        self.assertIn("Weather place: Cluj - home: trip #7 ended Wed 14 Oct 11:00", out.getvalue())

    def test_tomorrow_lines(self):
        r = lambda i, kind, content: {"id": i, "kind": kind, "content": content, "created_at_utc": f"2026-10-11 19:{i % 60:02d}:00"}
        rows = [r(4612, "personal_log", "for tomorrow- buy broken things, pack bags for trip back. take out trash."),
                r(4613, "personal_log", "a day\n- Tomorrow: call the garage\nnothing for tomorrow here"),
                r(4614, "logseq_journal", "- TODO renew the passport\n- TODO pay the water bill"),
                r(4615, "crew_ops", "for tomorrow: the crew's own line"),
                r(4616, "no1_log", "TODO Number One's"),
                r(4617, "task_crew", "tomorrow: no")]
        tasks = [{"id": 1, "title": "Pay the water bill", "kind": "task_personal"}]
        self.assertEqual(T.tomorrow_lines(rows, tasks), [
            (4612, "buy broken things, pack bags for trip back. take out trash."),
            (4613, "call the garage"),
            (4614, "renew the passport")])

    def test_stale_tasks(self):
        now = dt.datetime(2026, 10, 15, 3, 30, tzinfo=dt.timezone.utc)
        t = lambda i, at, **k: dict(id=i, title=f"t{i}", created_at_utc=at, **k)
        tasks = [t(2722, "2026-09-16 10:08:41"), t(2, "2026-09-01 10:00:00", start_date="2026-10-20 10:00:00"),
                 t(3, "2026-10-10 10:00:00"), t(4, "2026-09-02 10:00:00", done_bool=1)]
        self.assertEqual([r["id"] for r in T.stale_tasks(tasks, now)], [2722])
        fake = lambda **q: tasks[:3] if q.get("done") == 0 and q.get("kind") == "task" else []
        for day, monday in (("2026-10-15", False), ("2026-10-19", True)):
            out = io.StringIO()
            with mock.patch.object(T, "entries", fake), mock.patch.object(T, "entries_all", lambda **q: []), \
                    mock.patch.object(T, "kinds", lambda: {"task": 3}), \
                    mock.patch.object(T.dt, "datetime", mock.Mock(wraps=dt.datetime, now=lambda tz=None: now)), \
                    redirect_stdout(out):
                T.cmd_agenda([day])
            o = out.getvalue()
            self.assertIn("  #2722 t2722 (since 16 Sep)\n", o)
            self.assertNotIn("#2722 [", o)                  # not one line of its own among the open tasks
            self.assertIn("#3 [", o)
            self.assertEqual("ask once whether these still matter" in o, monday)

    def test_bedtimes(self):
        r = lambda kind, at, **k: dict(kind=kind, created_at_utc=at, **k)
        # Helsinki is UTC+3 until the 25th: 20:30 UTC is 23:30, 21:30 UTC 00:30
        rows = [r("personal_log", "2026-10-05 19:00:00"), r("personal_log", "2026-10-05 20:30:00"),     # Mon 23:30
                r("crew_ops", "2026-10-05 22:00:00"), r("no1_log", "2026-10-05 23:00:00"),             # not his
                r("sleep", "2026-10-05 20:40:00", start_date="2026-10-05 20:40:00", end_date="2026-10-06 03:40:00"),
                r("page", "2026-10-06 21:30:00"),                                                       # Tue 00:30
                r("sleep", "2026-10-07 05:00:00", value_float=6.5),                                     # Tue's night
                r("personal_log", "2026-10-07 10:00:00"),                                               # by day
                r("personal_log", "2026-10-12 00:10:00")]                                               # Sun's, past the week
        week = {dt.date(2026, 10, 5) + dt.timedelta(days=i) for i in range(7)}
        b = T.bedtimes(rows, week)
        self.assertEqual(b["nights"], [(dt.date(2026, 10, 5), "23:30", 7.0), (dt.date(2026, 10, 6), "00:30", 6.5),
                                       (dt.date(2026, 10, 11), "03:10", None)])
        self.assertEqual(b["avg"], "01:03")                 # (23:30 + 24:30 + 27:10) / 3
        self.assertEqual(b["sleep_avg"], 6.8)
        n = T.week_numbers(rows, week)
        self.assertEqual(n["entries"], 8)                   # the row past the week is a bedtime only
        self.assertEqual(n["bedtime"]["n"], 3)

    def test_hygiene(self):
        r = lambda i, kind, title="", content="", at="2026-10-01 10:00:00", **k: dict(
            id=i, kind=kind, title=title, content=content, created_at_utc=at, last_modified_at_utc=at, **k)
        rows = [r(1, "personal_log", "walk", "a walk in the park", "2026-10-01 10:00:00"),
                r(2, "personal_log", "walk", "a walk in the park", "2026-10-01 10:00:30"),
                r(3, "personal_log", "walk", "a walk in the park", "2026-10-03 10:00:00"),
                r(4, "sleep", "HTTP Entry", "slept badly"),
                r(5, "task", "call bank tomorrow", ""),
                r(6, "task_personal", "old thing", "", "2026-08-01 10:00:00"),
                r(7, "task", "dentist", "", start_date="2026-09-01 08:00:00"),
                r(8, "personal_log", "x", "", start_date="2026-10-02 10:00:00", end_date="2026-10-01 10:00:00"),
                r(9, "logseq_journal", "walk", "a walk in the park", "2026-10-01 10:00:10"),
                r(10, "sleep", "HTTP Entry", "start")]
        kinds = {"personal_log": 900, "personal-log": 1, "task_personal": 1, "person": 170, "sleep": 80, "task": 3}
        f = T.hygiene_findings(rows, kinds, dt.date(2026, 10, 10))
        text = "\n".join(f"{s}: {t}" for s, t in f)
        self.assertIn("duplicates: #1 and #2", text)
        self.assertNotIn("#2 and #3", text)             # two days apart: meant
        self.assertNotIn("#9", text)                    # imported journals are frozen
        self.assertIn("kind 'personal-log'", text)
        self.assertNotIn("task_personal' (1 rows) looks", text)
        self.assertIn("#4 [sleep]", text)
        self.assertNotIn("#10 [sleep]", text)
        self.assertIn("#5 [task] call bank tomorrow: names a time ('tomorrow')", text)
        self.assertIn("stale: #6", text)
        self.assertIn("stale: #7", text)
        self.assertIn("dates: #8", text)

    def test_yeoman_ledger(self):
        # the shapes, as the page's QuickJS check has them (index.html YEO_RE)
        text = ("- #1 and #11: keep #1, delete #11. Say \"delete 11\" and \"delete 15\".\n"
                "- prose that says delete #11. and then goes on\n"
                "- #12 is personal_log. Set kind of 12 to child_sleep.\n"
                "- #13 names 10:00; set due of 13 to 2026-10-16T07:00:00Z\n"
                "- #14 is untitled. Say \"title 14 to Leg day\".\n"
                "- not a shape: merge 11 into 12\n\n```\ndelete 4242\n```\n")
        self.assertEqual(T.yeo_proposals(text), ["delete 11", "delete 15", "set kind of 12 to child_sleep",
                                                 "set due of 13 to 2026-10-16 07:00:00", "title 14 to Leg day"])
        fence = lambda *recs: "\n\n```yeoman-ledger\n" + "\n".join(json.dumps(r) for r in recs) + "\n```\n"
        reps = [
            dict(id=100, created_at_utc="2026-10-10 01:00:00", content=text + fence(
                {"change": "delete 11", "applied": "2026-10-10 08:00:00", "old": {"deleted": 0}, "seen": "x"},
                {"change": "delete 15", "dismissed": "2026-10-10 08:01:00"})),
            dict(id=101, created_at_utc="2026-10-11 01:00:00", content=text + fence(
                {"change": "set kind of 12 to child_sleep", "applied": "2026-10-11 08:00:00", "undone": "2026-10-11 08:05:00"},
                {"change": "delete 4242", "dismissed": "2026-10-11 09:00:00"})),
            dict(id=102, created_at_utc="2026-10-12 01:00:00", content="- delete 16\n- Say \"title 14 to Leg day\"."),
        ]
        led = T.yeoman_ledger(reps)
        self.assertEqual(led["delete 11"]["state"], "applied")
        self.assertEqual(led["delete 15"]["state"], "dismissed")
        self.assertEqual(led["set kind of 12 to child_sleep"]["state"], "undone")
        self.assertEqual(led["set due of 13 to 2026-10-16 07:00:00"]["state"], "pending")
        self.assertEqual((led["title 14 to Leg day"]["nights"], led["title 14 to Leg day"]["first"],
                          led["title 14 to Leg day"]["last"]), (3, 100, 102))
        self.assertEqual(led["delete 16"]["nights"], 1)
        self.assertNotIn("delete 4242", led)              # a mark for no proposal is no proposal
        out = "\n".join(T.ledger_lines(reps))
        self.assertIn("pending (proposed before, neither applied nor dismissed) (3):", out)
        self.assertIn("title 14 to Leg day  - in 3 reports, first #100, last #102", out)
        self.assertIn("dismissed (1):\n    delete 15", out)
        self.assertIn("undone (applied, then put back by the captain) (1):", out)
        # the verb prints it under the findings, from the last 14 days only
        old = dict(id=90, created_at_utc="2026-09-01 01:00:00", content="delete 77")
        with mock.patch.object(T, "entries_all", side_effect=lambda **q: reps + [old] if q.get("kind") == "crew_yeoman" else []), \
             mock.patch.object(T, "kinds", return_value={}), \
             mock.patch.object(T, "now_local", return_value=dt.datetime(2026, 10, 13, 4, 0, tzinfo=T.TZ)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(T.cmd_hygiene([]), 0)
        self.assertIn("ledger: what became of your proposals in the last 14 days (3 reports)", buf.getvalue())
        self.assertNotIn("delete 77", buf.getvalue())

    def test_counsel_digest(self):
        r = lambda i, at, content="", kind="personal_log", **k: dict(id=i, kind=kind, title="HTTP Entry",
                                                                       content=content, created_at_utc=at, **k)
        end = dt.date(2026, 10, 10)                      # a Saturday; the week is Sun 04 - Sat 10
        week = [r(1, "2026-10-04 08:00:00", "tired but the walk helped"),
                r(2, "2026-10-09 22:30:00", "x" * 4000),   # 01:30 Saturday in Helsinki
                r(3, "2026-10-08 08:00:00", "gone", deleted=1)]
        base = [r(10, "2026-10-02 09:00:00", "work all day, no walk"),
                dict(r(12, "2026-10-01 09:00:00", "![x](https://i/1.png) with [[Ana]] at https://a.b/c"), title="2026-10-01 - with Ana"),
                r(11, "2026-09-10 09:00:00", "a good week")]
        sleep = [r(20, "2026-10-05 05:00:00", "end", "sleep", value_float=7.5),
                 r(21, "2026-10-04 20:00:00", "start", "sleep", value_float=0),
                 r(22, "2026-10-01 05:00:00", "end", "sleep", value_float=5.0)]
        past = [r(30, "2025-10-08 10:00:00", "a year ago", "logseq_journal")]
        text = "\n".join(T.counsel_digest(end, week, base, sleep, past, 4))
        self.assertIn("Sun 04 Oct – Sat 10 Oct 2026", text)
        self.assertIn("2 logs, 6 words", text)
        self.assertIn("#1 Sun 04 Oct 11:00\ntired but the walk helped", text)   # no placeholder title
        self.assertIn("#2 Sat 10 Oct 01:30", text)
        self.assertIn(f"[... {4000 - T.COUNSEL_FULL_CHARS} more chars: get 2]", text)
        self.assertNotIn("#3 ", text)                                           # deleted
        self.assertIn("Mon 05 7.5", text)
        self.assertIn("Sun 04 -", text)                                         # a start row is not a night
        self.assertIn("avg 7.5h over 1 nights", text)
        self.assertIn("#12 Thu 01 12:00: with Ana\n", text)        # the title, its date dropped
        self.assertEqual(T._plain("![x](https://i/1.png) with [[Ana]] at https://a.b/c"), "[image] with Ana at [link]")
        self.assertIn("week 27 Sep – 03 Oct: 2 logs, 10 words, sleep avg 5.0h (1 nights)", text)
        self.assertIn("#10 Fri 02 12:00: work all day", text)
        self.assertIn("week 06 Sep – 12 Sep: 1 logs", text)
        self.assertIn("week 20 Sep – 26 Sep: 0 logs, 0 words, sleep not recorded", text)
        self.assertIn("#30 [logseq_journal] 08 Oct 2025: a year ago", text)

    def test_counsel_pages_fit_what_claude_shows(self):
        lines = [f"#{i} " + "x" * 90 for i in range(1000)]
        ps = T.pages(lines, 24000)
        self.assertEqual(sum(ps, []), lines)                  # nothing lost, nothing split
        self.assertTrue(all(len("\n".join(p)) <= 24000 for p in ps))
        self.assertEqual(len(ps), 4)
        self.assertEqual(T.pages(["y" * 30000, "z"], 24000), [["y" * 30000], ["z"]])
        self.assertEqual(T.pages([], 10), [[]])

    def test_counsel_reads_through_the_server(self):
        srv = Server(rows=[{"id": 5, "kind": "personal_log", "content": "hello", "created_at_utc": "2026-10-08 10:00:00"}])
        try:
            os.environ["LCARS_URL"] = srv.url
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(T.main(["counsel", "2026-10-10", "2"]), 0)
            self.assertIn("#5 Thu 08 Oct 13:00\nhello", out.getvalue())
            self.assertTrue(out.getvalue().startswith("[part 1 of 1]"))
            self.assertEqual(srv.posts, [])
        finally:
            srv.close()

    def test_audit_files_flag_loose_secrets(self):
        home, lh = os.path.join(self.tmp, "h"), os.path.join(self.tmp, "h", "lcars")
        os.makedirs(os.path.join(home, ".ssh"), mode=0o700)
        os.makedirs(lh)
        for p, m in ((os.path.join(home, ".env"), 0o644), (os.path.join(lh, "lcars.db"), 0o640)):
            open(p, "w").close()
            os.chmod(p, m)
        got = {os.path.basename(p): f for p, _, f in T.audit_files(home, lh)}
        self.assertIn("OPEN", got[".env"])
        self.assertIn("ok", got["lcars.db"])
        self.assertIn("missing", got["authorized_keys"])

    def test_backups_that_never_leave(self):
        lh = os.path.join(self.tmp, "lcars")
        os.makedirs(os.path.join(lh, "lcars_backups", "hourly"))
        open(os.path.join(lh, "lcars_backups", "hourly", "lcars_hourly_1.db.gz"), "w").close()
        with mock.patch.dict(os.environ, {"HOME": self.tmp}):
            f = T.backup_facts(lh, "0 * * * * backup_lcars.py\n# rsync once\n")
            self.assertIn("NONE", f[-1])
            self.assertTrue(f[0].startswith("hourly: 1 copies"))
            f = T.backup_facts(lh, "30 3 * * * rclone sync ~/lcars/lcars_backups b2:x\n")
            self.assertIn("rclone sync", f[-1])


class Scripts(Base):
    def test_ship_flags_a_stale_backup(self):
        lh = os.path.join(self.tmp, "lcars")
        hourly = os.path.join(lh, "lcars_backups", "hourly")
        os.makedirs(hourly)
        f = os.path.join(hourly, "lcars_hourly_20261010_01.db.gz")
        open(f, "w").close()
        os.utime(f, (time.time() - 5 * 3600,) * 2)
        srv = Server()
        try:
            os.environ["LCARS_URL"] = srv.url
            lines, urgent = C.ship_checks(lh)
        finally:
            srv.close()
        self.assertIn("- server answers /health", lines)
        self.assertTrue(any("**last backup 5.0h ago**" in ln for ln in lines), lines)
        self.assertEqual(urgent, "last backup 5.0h ago")

    def test_ship_flags_a_down_server_first(self):
        os.environ["LCARS_URL"] = "http://127.0.0.1:9"
        lines, urgent = C.ship_checks(self.tmp)
        self.assertEqual(urgent, "server does not answer /health")

    def test_qa_dry_run_names_its_plan(self):
        self.role("qa", "---\nschedule: *-*-* 01:40\nkind: script\nscript: qa\n---\nx\n")
        fm, _ = C.load("qa")
        with mock.patch.dict(os.environ, {"LCARS_HOME": self.tmp}):
            title, body, urgent = C.run_qa(fm, True)
        self.assertIn("PERF=0 KB=0", body)
        self.assertIsNone(urgent)


class Install(Base):
    def test_dropins_and_removal(self):
        self.role("ops")
        self.role("old")
        units = os.path.join(self.tmp, "units")
        with mock.patch.object(C.subprocess, "run") as run, redirect_stdout(io.StringIO()):
            C.install()
            os.remove(os.path.join(self.crew, "old.md"))
            C.install()
        with open(os.path.join(units, "lcars-crew@ops.timer.d", "schedule.conf")) as f:
            conf = f.read()
        self.assertIn("OnCalendar=\nOnCalendar=*-*-* 06:30 Europe/Helsinki", conf)
        self.assertTrue(os.path.exists(os.path.join(units, "lcars-crew@.service")))
        self.assertFalse(os.path.exists(os.path.join(units, "lcars-crew@old.timer.d")))
        cmds = [" ".join(c.args[0]) for c in run.call_args_list]
        self.assertIn("systemctl --user enable --now lcars-crew@ops.timer", cmds)
        self.assertIn("systemctl --user disable --now lcars-crew@old.timer", cmds)

    def test_dry_run_writes_nothing(self):
        self.role("ops")
        with mock.patch.object(C.subprocess, "run") as run, redirect_stdout(io.StringIO()) as out:
            C.install(dry=True)
        self.assertFalse(run.called)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "units")))
        self.assertIn("enable --now lcars-crew@ops.timer", out.getvalue())


class Zone(unittest.TestCase):
    """The captain's zone (crew_tool.crew_zone): LCARS_CREW_TZ, LCARS_TZ
    from the environment, then from the env file, then the box's own; and
    what follows from it - the home place, the units' calendars."""

    def zone(self, env, file_text=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "env")
            if file_text is not None:
                with open(path, "w") as f:
                    f.write(file_text)
            keep = {k: v for k, v in env.items()}
            with mock.patch.dict(os.environ, keep, clear=False), mock.patch.object(T, "ENV_FILE", path), \
                    mock.patch.object(T, "system_zone", return_value="America/Chicago"):
                for k in ("LCARS_CREW_TZ", "LCARS_TZ"):
                    if k not in env:
                        os.environ.pop(k, None)
                err = io.StringIO()
                with mock.patch.object(sys, "stderr", err):
                    return T.crew_zone().key, err.getvalue()

    def test_the_order(self):
        self.assertEqual(self.zone({"LCARS_CREW_TZ": "Asia/Tokyo", "LCARS_TZ": "Europe/Oslo"}), ("Asia/Tokyo", ""))
        self.assertEqual(self.zone({"LCARS_TZ": "Europe/Oslo"}, "LCARS_TZ=Europe/Rome\n"), ("Europe/Oslo", ""))
        self.assertEqual(self.zone({}, "X=1\nexport LCARS_TZ='Europe/Rome'\n"), ("Europe/Rome", ""))
        self.assertEqual(self.zone({}, "X=1\n"), ("America/Chicago", ""), "unset: the box's own")
        self.assertEqual(self.zone({}), ("America/Chicago", ""), "no env file at all")

    def test_a_bad_name_is_the_boxs_said(self):
        key, err = self.zone({"LCARS_TZ": "Atlantis/Lost"})
        self.assertEqual(key, "America/Chicago")
        self.assertIn("is no zone", err)

    def test_zone_city(self):
        self.assertEqual(T.zone_city("America/New_York"), "New York")
        self.assertEqual(T.zone_city("America/Argentina/Buenos_Aires"), "Buenos Aires")
        self.assertIsNone(T.zone_city("UTC"))
        self.assertIsNone(T.zone_city("Etc/GMT+2"))

    def test_no_home_and_no_city(self):
        with mock.patch.object(T, "TZ", T.ZoneInfo("UTC")):
            self.assertIsNone(T.home_place([]))

    def test_units_get_the_zone_on_their_calendars(self):
        text = C.unit_text("lcars-prune.timer")
        self.assertIn("\nOnCalendar=Sun *-*-* 05:10:00 Europe/Helsinki\n", text)
        self.assertEqual(text.count("Europe/Helsinki"), 1, "the comment naming OnCalendar= untouched")
        self.assertNotRegex(C.unit_text("lcars-crew@.timer"), r"(?m)^OnCalendar=", "the template has none: its drop-ins do")


class KindRoles(unittest.TestCase):
    """Kinds by role (docs/design/kinds.md): lcars_roles.py and the crew's
    use of it."""

    def test_the_table_is_the_servers(self):
        src = open(os.path.join(os.path.dirname(HERE), "lcars_kinds.h"), encoding="utf-8").read()
        tab = src[src.index("g_kind_roles[] = {"):]
        tab = tab[:tab.index("};")]
        c = [(m[0], m[1], m[2] == "true") for m in
             re.findall(r'\{"([a-z_]+)",\s*"([a-z_]+)",\s*(?:"(?:[^"\\]|\\.)*"\s*)+,\s*(true|false)\}', tab)]
        self.assertEqual(len(c), 18)
        self.assertEqual(tuple(c), lcars_roles.DEFAULTS)

    def test_an_answer_and_a_mapping(self):
        r = lcars_roles.from_answer({"roles": [
            {"role": "child_sleep", "kind": "naps", "kinds": ["naps"], "name": "Ada"},
            {"role": "imported", "kind": "a_journal,b_journal", "kinds": ["a_journal", "b_journal"]},
            {"role": "task", "kind": "todo"}, {"role": "", "kind": "x"}, "junk"]})
        self.assertEqual((r.kind("child_sleep"), r.name("child_sleep")), ("naps", "Ada"))
        self.assertEqual(r.kinds("imported"), ("a_journal", "b_journal"))
        self.assertEqual(r.kind("log"), "personal_log")
        self.assertEqual(r.ask("crew"), "todo_crew")
        m = lcars_roles.from_mapping({"v": 1, "roles": {"work_log": {"kind": "my_log"}, "child_vocab": {"kind": ""}}})
        self.assertEqual((m.kind("work_log"), m.kind("child_vocab")), ("my_log", "child_vocab"))

    def test_no_answer_is_the_defaults(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"LCARS_KINDS_FILE": ""}), mock.patch("sys.stderr", err):
            r = lcars_roles.load(lambda: (_ for _ in ()).throw(RuntimeError("GET /kinds/roles: 404")))
        self.assertEqual(r.kind("child_sleep"), "child_sleep")
        self.assertIn("every role its default (GET /kinds/roles: 404)", err.getvalue())

    def test_the_crew_follows_a_set_mapping(self):
        was = T._ROLES
        T._ROLES = lcars_roles.from_mapping({"roles": {"child_sleep": {"kind": "naps"}, "child_vocab": {"kind": "words"},
                                                       "log": {"kind": "diary"}, "task": {"kind": "todo"},
                                                       "imported": {"kind": "a_journal,b_journal"}}})
        try:
            self.assertEqual(T.fill_kinds("a `<kind:log>`; frozen: <kinds:imported>; <kind:sleep>"),
                             "a `diary`; frozen: a_journal, b_journal; sleep")
            self.assertEqual(T.never_write(), "crew_*, no1_*, todo_crew, todo_no1, a_journal, b_journal")
            self.assertEqual(T.urgent_kind(), "todo_crew")
            self.assertFalse(T.own_kind("todo_no1"))
            self.assertTrue(T.own_kind("task_no1"))
            n = T.week_numbers([{"kind": "words", "title": "unu", "value_int": 1, "created_at_utc": "2026-10-05 10:00:00"},
                                {"kind": "naps", "value_float": 1.5, "created_at_utc": "2026-10-05 13:00:00"},
                                {"kind": "diary", "content": "three words here", "created_at_utc": "2026-10-05 20:00:00"}])
            self.assertEqual(n["vocab"], ["unu"])
            self.assertEqual(n["series"]["naps"]["total"], 1.5)
            self.assertEqual(n["words"], 3)
            self.assertFalse(N.eligible({"kind": "todo_crew_x"}))
            self.assertFalse(N.eligible({"kind": "b_journal"}))
            self.assertTrue(N.eligible({"kind": "diary"}))
            _, prompt = C.load("yeoman-linker")
            self.assertIn("a timed gym `diary`", prompt)
            self.assertNotIn("<kind:", prompt)
        finally:
            T._ROLES = was


if __name__ == "__main__":
    unittest.main(verbosity=1)
