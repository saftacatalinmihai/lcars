#!/usr/bin/env python3
"""Tests for scripts/steward.py, the engineers' data fixes: every op
against test_crew_notes' stand-in journal (its steward gate and if_modified
guard), the 412, a refused kind, the crew_fix record, who from the
worktree, a run as its own process printing nothing of ~/.env, no1.py's
steward verb, and the engineer settings that let it run.

    python3 scripts/test_steward.py      # ~2s
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - before engineer.py (no1.py's): no live state
import test_crew_notes as TCN  # noqa: E402 - the stand-in journal and its clock
import crew_notes as N  # noqa: E402
import crew_tool as T  # noqa: E402
import steward as S  # noqa: E402

SECRETS = ("spw", "crew-secret")


class Steward(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-test-")
        self.env = os.path.join(self.tmp, "env")
        with open(self.env, "w") as f:
            f.write("LCARS_CREW_USER=crew\nLCARS_CREW_PASS=crew-secret\n"
                    "LCARS_STEWARD_USER=steward\nLCARS_STEWARD_PASS=spw\n")
        self.root = os.path.join(self.tmp, "lcars-eng")
        self.wt = os.path.join(self.root, "torres-c2", "scripts")
        os.makedirs(self.wt)
        self.clock = TCN.Clock()
        self.srv = TCN.Server(self.clock)
        os.environ["LCARS_URL"] = self.srv.url
        os.environ.pop("LCARS_STEWARD_WHO", None)
        self.ps = [mock.patch.object(T, "ENV_FILE", self.env), mock.patch.object(S, "ROOT", self.root),
                   mock.patch.object(N, "now", lambda: self.clock())]
        for p in self.ps:
            p.start()
        self.e = self.srv.add(kind="journal", title="Walk in the park and some trailing words",
                              content="We walked.\nIt rained.")
        self.tick(60)   # past the quiet rule

    def tearDown(self):
        for p in self.ps:
            p.stop()
        self.srv.close()
        os.environ.pop("LCARS_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tick(self, secs):
        self.clock.t += secs

    def run_(self, *argv, stdin=None, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin or "")), \
                mock.patch.object(os, "getcwd", lambda: cwd or self.wt):
            code = S.main(list(argv))
        text = out.getvalue() + err.getvalue()
        for s in SECRETS:
            self.assertNotIn(s, text)
        return code, text

    def records(self):
        return [r for r in self.srv.rows.values() if r["kind"] == S.RECORD_KIND]

    def writes(self):
        return [x for x in self.srv.log if x[0] in ("POST", "PATCH", "DELETE")]

    # ---- the ops ----

    def test_title(self):
        code, out = self.run_("title", str(self.e["id"]), "Walk", "in", "the", "park")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["title"], "Walk in the park")
        # the steward wrote it, with the stamp of the fresh read
        w = self.writes()[0]
        self.assertEqual((w[0], w[1], w[3]), ("POST", f"/entries/{self.e['id']}/title", "steward"))
        self.assertTrue(w[2]["if_modified"])
        j = json.loads(out)
        self.assertTrue(j["ok"])
        [rec] = self.records()
        self.assertEqual(j["record_id"], rec["id"])
        # the record: the crew's login, who, the op, the entry, old and new
        self.assertEqual(self.writes()[1][3], "crew")
        self.assertEqual(rec["value_int"], self.e["id"])
        self.assertEqual(rec["done_bool"], 1)
        for s in ("who:: torres-c2", "op:: title", f"entry:: #{self.e['id']}",
                  "Walk in the park and some trailing words", "Walk in the park", N.UNDO_FENCE):
            self.assertIn(s, rec["content"])
        self.assertIn("torres-c2", rec["title"])

    def test_set(self):
        code, out = self.run_("set", str(self.e["id"]), "done=1", "start=2026-10-14 08:00")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["done_bool"], 1)
        self.assertTrue(self.e["start_date"].startswith("2026-10-14 05:00"))   # Helsinki, +3
        [rec] = self.records()
        self.assertIn('"done_bool": 0', rec["content"])
        self.assertIn('"done_bool": 1', rec["content"])

    def test_set_unknown_field(self):
        code, out = self.run_("set", str(self.e["id"]), "colour=red")
        self.assertEqual(code, 1)
        self.assertIn("colour", json.loads(out)["error"])
        self.assertEqual(self.writes(), [])

    def test_replace_from_file_and_stdin(self):
        f = os.path.join(self.tmp, "new.md")
        with open(f, "w") as fh:
            fh.write("We walked.\nIt was sunny, a literal \\n stays.\n")
        code, out = self.run_("replace", str(self.e["id"]), "--file", f)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["content"], "We walked.\nIt was sunny, a literal \\n stays.\n")
        [rec] = self.records()
        self.assertIn("It rained.", rec["content"])          # the old text, whole
        self.tick(60)
        code, out = self.run_("replace", str(self.e["id"]), "-", stdin="Short now.")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["content"], "Short now.")
        # replace never takes the text as words
        code, out = self.run_("replace", str(self.e["id"]), "some", "words")
        self.assertEqual(code, 1)
        self.assertIn("--file", out)

    def test_replace_refuses_a_new_note(self):
        code, out = self.run_("replace", str(self.e["id"]), "-", stdin="We walked.\n@yeoman log it")
        self.assertEqual(code, 1)
        self.assertIn("@role", out)
        self.assertEqual(self.writes(), [])

    def test_append(self):
        code, out = self.run_("append", str(self.e["id"]), "Also", "a", "coffee.")
        self.assertEqual(code, 0, out)
        self.assertIn("> torres-c2 added,", self.e["content"])
        self.assertIn("> Also a coffee.", self.e["content"])
        self.assertTrue(self.e["content"].startswith("We walked.\nIt rained."))

    def test_delete_and_restore(self):
        code, out = self.run_("delete", str(self.e["id"]))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["deleted"], 1)
        self.tick(60)
        code, out = self.run_("restore", str(self.e["id"]))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.e["deleted"], 0)
        self.assertEqual([r["content"].split("\n")[1] for r in self.records()], ["op:: delete", "op:: restore"])
        code, out = self.run_("delete", str(self.e["id"]), "extra")
        self.assertEqual(code, 1)

    def test_get(self):
        code, out = self.run_("get", str(self.e["id"]), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["title"], self.e["title"])
        code, out = self.run_("get", str(self.e["id"]))
        self.assertEqual(code, 0)
        self.assertIn("It rained.", out)
        self.assertIn("last_modified_at_utc", out)
        self.assertEqual(self.writes(), [])
        code, out = self.run_("get", "99999")
        self.assertEqual(code, 1)

    def test_new(self):
        code, out = self.run_("new", "kind=journal", "title=Shared LCARS on Hacker News",
                              "start=2026-10-27 09:30", "Posted it; 12 points by noon.")
        self.assertEqual(code, 0, out)
        j = json.loads(out)
        row = self.srv.rows[j["id"]]
        self.assertEqual((row["kind"], row["title"]), ("journal", "Shared LCARS on Hacker News"))
        self.assertTrue(row["content"].startswith("> torres-c2 created this, "))
        self.assertIn("steward.py", row["content"].split("\n")[0])
        self.assertTrue(row["content"].endswith("Posted it; 12 points by noon."))
        self.assertTrue(row["start_date"].startswith("2026-10-27 07:30"))   # Helsinki, +2 after the 25th
        self.assertEqual(self.writes()[0][3], "steward")
        # the record: nothing old, the entry made new
        [rec] = self.records()
        self.assertEqual(j["record_id"], rec["id"])
        self.assertEqual(rec["value_int"], j["id"])
        for s in ("who:: torres-c2", "op:: create", f"entry:: #{j['id']}", "**Old**\n(nothing)",
                  "kind: journal", "Posted it; 12 points by noon."):
            self.assertIn(s, rec["content"])
        # the text from stdin, and from a file
        self.assertEqual(self.run_("new", "kind=journal", "-", stdin="From stdin.")[0], 0)
        f = os.path.join(self.tmp, "t.md")
        with open(f, "w") as fh:
            fh.write("From a file.\nTwo lines.")
        code, out = self.run_("new", "kind=journal", "title=F", "--file", f)
        self.assertEqual(code, 0, out)
        self.assertIn("From a file.\nTwo lines.", self.srv.rows[json.loads(out)["id"]]["content"])

    def test_new_refused(self):
        n = len(self.srv.rows)
        for argv, why in ((["kind=crew_log", "title=x"], "not a kind of the captain's"),
                          (["kind=task_no1", "title=x"], "not a kind of the captain's"),
                          (["title=no kind"], "needs a kind"),
                          (["kind=journal"], "a title or text"),
                          (["kind=journal", "title=x", "@yeoman log it"], "@role")):
            code, out = self.run_("new", *argv)
            self.assertEqual(code, 1, argv)
            self.assertIn(why, out, argv)
        # and the server's gate, if the check here were passed by
        with mock.patch.object(N, "eligible", lambda r: True):
            code, out = self.run_("new", "kind=crew_log", "title=x")
        self.assertEqual(code, 1)
        self.assertIn("403", out)
        self.assertEqual(len(self.srv.rows), n)
        self.assertEqual(self.records(), [])

    # ---- the guards ----

    def test_412_when_the_row_moved(self):
        real, reads = N.get_row, []

        def moved(rid):
            # the captain saves between steward.py's read and its write
            row = real(rid)
            reads.append(rid)
            if len(reads) == 1:
                self.tick(1)
                self.srv.edit(rid, content="the captain typed")
                self.tick(60)
            return row
        with mock.patch.object(N, "get_row", moved):
            code, out = self.run_("title", str(self.e["id"]), "New")
        self.assertEqual(code, 1, out)
        self.assertIn("412", out)
        self.assertIn("changed since it was read", out)
        self.assertEqual(self.e["title"], "Walk in the park and some trailing words")
        self.assertEqual(self.records(), [])

    def test_refused_kind(self):
        other = self.srv.add(kind="crew_log", title="the crew's own")
        self.tick(60)
        code, out = self.run_("title", str(other["id"]), "Mine now")
        self.assertEqual(code, 1)
        self.assertIn("not one of the captain's entries", out)
        self.assertEqual(other["title"], "the crew's own")
        # and the server's gate, if the check here were passed by
        with mock.patch.object(N, "eligible", lambda r: True):
            code, out = self.run_("title", str(other["id"]), "Mine now")
        self.assertEqual(code, 1)
        self.assertIn("403", out)
        self.assertEqual(other["title"], "the crew's own")
        self.assertEqual(self.records(), [])
        # nor into one of theirs
        code, out = self.run_("set", str(self.e["id"]), "kind=task_no1")
        self.assertEqual(code, 1)
        self.assertIn("not a kind of the captain's", out)

    def test_quiet_rule(self):
        self.srv.edit(self.e["id"], content="typing")
        code, out = self.run_("title", str(self.e["id"]), "New")
        self.assertEqual(code, 1)
        self.assertIn("being edited", out)

    def test_who(self):
        code, out = self.run_("title", str(self.e["id"]), "New", cwd=self.tmp)
        self.assertEqual(code, 1)
        self.assertIn("worktree", out)
        self.assertEqual(self.writes(), [])
        with mock.patch.dict(os.environ, {"LCARS_STEWARD_WHO": "number-one"}):
            code, out = self.run_("title", str(self.e["id"]), "New", cwd=self.tmp)
        self.assertEqual(code, 0, out)
        self.assertIn("who:: number-one", self.records()[0]["content"])

    def test_no_logins(self):
        with open(self.env, "w") as f:
            f.write("LCARS_CREW_USER=crew\nLCARS_CREW_PASS=crew-secret\n")
        code, out = self.run_("title", str(self.e["id"]), "New")
        self.assertEqual(code, 1)
        self.assertIn("LCARS_STEWARD_USER", out)
        self.assertEqual(self.writes(), [])

    def test_record_failing_says_so(self):
        real = T.http

        def no_record(method, path, body=None, **kw):
            if method == "POST" and path == "/entries":
                return 500, '{"error": "disk full"}'
            return real(method, path, body, **kw)
        with mock.patch.object(T, "http", no_record):
            code, out = self.run_("title", str(self.e["id"]), "New")
        self.assertEqual(code, 3)
        j = json.loads(out)
        self.assertIn("record was not written", j["error"])
        self.assertEqual(j["record"]["old_title"], "Walk in the park and some trailing words")

    def test_usage(self):
        for argv in (["frobnicate", "1"], ["title"], ["title", "abc", "x"]):
            code, _ = self.run_(*argv)
            self.assertIn(code, (1, 2), argv)
        self.assertEqual(self.writes(), [])

    def test_own_process_prints_no_secret(self):
        env = dict(os.environ, LCARS_CREW_ENV=self.env, LCARS_URL=self.srv.url, LCARS_STEWARD_WHO="torres-c2",
                   LCARS_CREW_TZ="Europe/Helsinki")
        for argv in (["get", str(self.e["id"]), "--json"], ["title", str(self.e["id"]), "Walk"],
                     ["title", "99999", "x"], ["--help"]):
            p = subprocess.run([sys.executable, os.path.join(HERE, "steward.py"), *argv], env=env,
                               capture_output=True, text=True, timeout=30)
            for s in SECRETS:
                self.assertNotIn(s, p.stdout + p.stderr, argv)
        self.assertEqual(self.e["title"], "Walk")


class Wiring(unittest.TestCase):
    """no1.py's verb, the settings that allow it, the heavy hook."""

    def test_no1_steward(self):
        import no1
        seen = {}

        def fake(argv, env=None, **kw):
            seen.update(argv=argv, who=env.get("LCARS_STEWARD_WHO"))
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(no1.subprocess, "run", fake):
            self.assertEqual(no1.main(["steward", "title", "17058", "Short"]), 0)
        self.assertTrue(seen["argv"][1].endswith("scripts/steward.py"))
        self.assertEqual(seen["argv"][2:], ["title", "17058", "Short"])
        self.assertEqual(seen["who"], no1.E.NO1)

    def test_settings_and_hook(self):
        import engineer as E
        st = os.path.join(E.LIVE, "scripts", "steward.py")
        rule = f"Bash(python3 {st}:*)"
        self.assertIn(rule, E.no1_settings()["permissions"]["allow"])
        with mock.patch.object(E, "seated", lambda n: True):
            s = E.crew_settings("torres-c2")
        self.assertIn(rule, s["permissions"]["allow"])
        # the secrets stay denied: the script reads them, the session never
        self.assertIn(f"Read(/{os.path.join(E.HOME, '.env')})", s["permissions"]["deny"])
        hook = lambda c: E.heavy_check("torres-c2", {"tool_name": "Bash", "tool_input": {"command": c}})
        with mock.patch.object(E, "seated", lambda n: True):
            self.assertIsNone(hook(f"python3 {st} title 17058 'Trim the run.sh tail'"))
            self.assertIsNone(hook(f"{st} get 17058 --json"))
            self.assertIsNotNone(hook(f"python3 {st} get 1 && make lcars-one"))


if __name__ == "__main__":
    unittest.main()
