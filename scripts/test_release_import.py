#!/usr/bin/env python3
"""Tests for scripts/release-import.py (docs/design/release-entries.md):
the CHANGELOG's sections, an entry's shape, 12:00 in the captain's zone,
and the import on a scratch journal - a scratch server built from the
lcars-release compile line, an empty database - run twice: the dry run
writes nothing, --apply makes every version oldest first, a second
--apply nothing, a deleted release stays deleted. The deploy's own write
is test_version_stamp.py's ("the release entries").

    python3 scripts/test_release_import.py   (~15s with the build; LCARS_TEST_BIN skips it)
"""

import base64
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import testguard  # noqa: E402,F401 - no test reaches the live journal
sys.path.insert(0, str(REPO / "lcars-ui" / "test"))
import killclean  # noqa: E402 - its scratch goes when the run is killed
from caldav import build, free_port  # noqa: E402

_spec = importlib.util.spec_from_file_location("release_import", HERE / "release-import.py")
RI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RI)

TMP = pathlib.Path(killclean.mkdtemp(prefix="release-test-"))
USER = ("t", "t")
LOG = """# Changelog

Preamble, with a `## ` nowhere at a line's start.

## 0.3.0 — 2026-10-03

- **web** three
  continued

### a subheading kept

- more

## next patch — 2026-10-04

- a placeholder: not a release

## 0.2.1 — 2026-10-02

- two, a hyphen's heading below

## 0.1.0 - 2026-01-15 · `abc1234`

- one
"""


class Units(unittest.TestCase):
    def test_sections(self):
        s = RI.sections(LOG)
        self.assertEqual([(v, d) for v, d, _ in s], [("0.3.0", "2026-10-03"), ("0.2.1", "2026-10-02"),
                                                     ("0.1.0", "2026-01-15")])
        self.assertEqual(s[0][2], "- **web** three\n  continued\n\n### a subheading kept\n\n- more")
        self.assertEqual(s[2][2], "- one")

    def test_the_entry(self):
        self.assertEqual(RI.entry("0.3.0", "2026-10-03", "- x", "2026-10-03 09:00:00"),
                         {"kind": "release", "title": "0.3.0", "content": "release:: 0.3.0 2026-10-03\n\n- x",
                          "created_at_utc": "2026-10-03 09:00:00"})

    def test_noon_in_the_captains_zone(self):
        with mock.patch.dict(os.environ, {"LCARS_TZ": "Europe/Helsinki"}):
            self.assertEqual(RI.noon_utc("2026-10-03"), "2026-10-03 09:00:00")   # EEST, +3
            self.assertEqual(RI.noon_utc("2026-01-15"), "2026-01-15 10:00:00")   # EET, +2
        with mock.patch.dict(os.environ, {"LCARS_TZ": "UTC"}):
            self.assertEqual(RI.noon_utc("2026-10-03"), "2026-10-03 12:00:00")

    def test_outcome(self):
        self.assertEqual(RI.outcome([("0.1.0", 4, ""), ("0.2.0", 5, "")]), "release entries: 0.1.0 #4, 0.2.0 #5")
        self.assertEqual(RI.outcome([("0.1.0", 4, ""), ("0.2.0", None, "500: x")]),
                         "release entries: 0.1.0 #4; release entries NOT written: 0.2.0 (500: x)"
                         " - release-import.py --apply catches them up")


class Import(unittest.TestCase):
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
        env.pop("LCARS_DATA_DIR", None)
        cls.log = open(TMP / "server.log", "w")
        cls.proc = killclean.child(subprocess.Popen([binary, "--port", str(cls.port)], cwd=live, env=env,
                                                    stdout=cls.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        cls.changelog = TMP / "CHANGELOG.md"
        cls.changelog.write_text(LOG)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()
        shutil.rmtree(TMP, True)

    def req(self, method, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                   data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json", "Authorization": "Basic "
                                            + base64.b64encode(f"{USER[0]}:{USER[1]}".encode()).decode()})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def run_import(self, *args):
        env = dict(os.environ, LCARS_URL=f"http://127.0.0.1:{self.port}", LCARS_AUTH_USER=USER[0],
                   LCARS_AUTH_PASS=USER[1], LCARS_CHANGELOG=str(self.changelog), LCARS_TZ="Europe/Helsinki")
        p = subprocess.run([sys.executable, str(HERE / "release-import.py"), "--json", *args],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def releases(self):
        return [e for e in self.req("GET", "/dump?kind=release&order=id&dir=asc&deleted=all")]

    def test_the_import_twice(self):
        # a release the deploy wrote already: left alone
        self.req("POST", "/entries", RI.entry("0.2.1", "2026-10-02", "- two", "2026-10-02 15:00:00"))
        dry = self.run_import()
        self.assertEqual([r["version"] for r in dry["create"]], ["0.1.0", "0.3.0"])   # oldest first
        self.assertEqual([r["version"] for r in dry["have"]], ["0.2.1"])
        self.assertEqual(len(self.releases()), 1)   # the dry run wrote nothing

        done = self.run_import("--apply")
        self.assertEqual([r["version"] for r in done["create"]], ["0.1.0", "0.3.0"])
        rows = self.releases()
        self.assertEqual([(e["title"], e["created_at_utc"]) for e in rows],
                         [("0.2.1", "2026-10-02 15:00:00"), ("0.1.0", "2026-01-15 10:00:00"),
                          ("0.3.0", "2026-10-03 09:00:00")])
        self.assertEqual(rows[2]["content"], "release:: 0.3.0 2026-10-03\n\n"
                         "- **web** three\n  continued\n\n### a subheading kept\n\n- more")
        self.assertEqual({e["kind"] for e in rows}, {"release"})

        # again: nothing to make, a deleted one included
        self.req("DELETE", f"/entries/{rows[1]['id']}")
        again = self.run_import("--apply")
        self.assertEqual((again["create"], len(again["have"])), ([], 3))
        self.assertEqual(len(self.releases()), 3)


if __name__ == "__main__":
    unittest.main()
