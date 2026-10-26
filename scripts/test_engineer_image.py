#!/usr/bin/env python3
"""The pictures an engineer's session saw, served from its transcript:
engineer.py's `image` verb (cmd_image: the key, the line, the picture, the
cache, the cap) and GET /engineer/<name>/image?k=<session>:<offset>:<index>
(lcars_engineer.h's EngineerImage) on a scratch build of the real server
running the real engineer.py against a temp HOME's transcripts and a temp
state directory: the owner gets the bytes with their type and a private
year-long cache; Number One's, the crew's and the steward's logins a 403
(lcars_logins.h); a key of the wrong shape a 400, one naming nothing a 404,
a picture over the cap a 413. Nothing outside the temp directories is
touched.

    python3 scripts/test_engineer_image.py      (LCARS_TEST_BIN skips the build;
                                                 SKIP_ROUTE=1 the server)
"""

import atexit
import base64
import http.client
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="lcars-image-test-")
atexit.register(shutil.rmtree, TMP, True)
_procs = []


def _killed(sig, _frame):
    for p in _procs:
        if p.poll() is None:
            p.kill()
    shutil.rmtree(TMP, ignore_errors=True)
    signal.signal(sig, signal.SIG_DFL)
    os.kill(os.getpid(), sig)


for _sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(_sig, _killed)
STATE, ROOT, FAKE_HOME = (os.path.join(TMP, d) for d in ("state", "eng", "home"))
os.environ.update(LCARS_ENG_STATE=STATE, LCARS_ENG_ROOT=ROOT, LCARS_ENG_SEAT="0")
sys.path.insert(0, HERE)
import testguard  # noqa: E402,F401 - no test reaches the live journal
import engineer as E  # noqa: E402

SID = "0a1b2c3d-1111-4000-8000-000000000000"
OLD = "9f8e7d6c-2222-4000-8000-000000000000"
# the heads of a 2x3 PNG, a 5x7 GIF and an 11x9 JPEG (its SOF holds the
# height, then the width): enough for img_dims and the magic check
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (2).to_bytes(4, "big") + (3).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"x" * 40
GIF = b"GIF89a" + (5).to_bytes(2, "little") + (7).to_bytes(2, "little") + b"\x00" * 20
JPEG = b"\xff\xd8\xff\xe0\x00\x04ab" + b"\xff\xc0\x00\x11\x08" + (9).to_bytes(2, "big") + (11).to_bytes(2, "big") + b"\x03" + b"\x00" * 12


def img(mime, raw):
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(raw).decode()}}


def result(*blocks):
    return {"type": "tool_result", "tool_use_id": "toolu_x", "content": list(blocks)}


def line(content, kind="user", **extra):
    return json.dumps(dict({"type": kind, "timestamp": "2026-10-22T10:00:00.000Z",
                            "message": {"role": kind, "content": content}}, **extra))


LINES = [
    line("Show me the deck."),
    line([{"type": "tool_use", "id": "toolu_x", "name": "Read", "input": {"file_path": "/tmp/shot.png"}}], "assistant"),
    # a Read's result: one picture, its size in toolUseResult
    line([result(img("image/png", PNG))], toolUseResult={"type": "image", "file": {
        "type": "image/png", "dimensions": {"displayWidth": 1280, "displayHeight": 860}}}),
    # a tool's two pictures and a text block, and one of a type not served
    line([result({"type": "text", "text": "two shots"}, img("image/gif", GIF), img("image/svg+xml", b"<svg/>"),
                 img("image/jpeg", JPEG))]),
    # a sub-agent's picture is not the session's own
    line([result(img("image/png", PNG))], isSidechain=True),
    # a picture labelled as what it is not
    line([result(img("image/png", GIF))]),
    # over the cap
    line([result(img("image/png", PNG + b"\x00" * (E.IMG_MAX + 10)))]),
]


def offsets(lines):
    o, at = [], 0
    for ln in lines:
        o.append(at)
        at += len(ln.encode()) + 1
    return o


OFF = offsets(LINES)


def setup_files():
    proj = os.path.join(FAKE_HOME, ".claude", "projects", "-x-eng-ada")
    os.makedirs(proj, exist_ok=True)
    with open(os.path.join(proj, SID + ".jsonl"), "w") as f:
        f.write("".join(ln + "\n" for ln in LINES))
    with open(os.path.join(proj, OLD + ".jsonl"), "w") as f:
        f.write(LINES[2] + "\n")
    os.makedirs(STATE, exist_ok=True)
    for name in ("ada", E.NO1):
        with open(os.path.join(STATE, name + ".json"), "w") as f:
            json.dump({"session": SID, "past": [{"name": "before", "session": OLD, "at": 1}]}, f)


setup_files()
E.HOME = FAKE_HOME


def call(fn, *a):
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fn(*a)
    except SystemExit as e:
        return e.code or 0, json.loads(buf.getvalue())
    return 0, json.loads(buf.getvalue() or "{}")


class Events(unittest.TestCase):
    """events_of: each picture a session saw an "img" event at its place."""

    def test_a_read_is_one_picture_with_its_size(self):
        evs = E.events_of(LINES[2], f"0a1b2c3d:{OFF[2]}")
        self.assertEqual(evs, [{"r": "img", "t": "", "m": "image/png", "w": 1280, "h": 860,
                                "k": f"0a1b2c3d:{OFF[2]}:0", "img": f"0a1b2c3d:{OFF[2]}:0", "at": 1792663200.0}])

    def test_several_in_order_the_size_from_the_head_an_unserved_type_skipped(self):
        evs = E.events_of(LINES[3], "s:7")
        self.assertEqual([(e["m"], e.get("w"), e.get("h"), e["img"], e["k"]) for e in evs],
                         [("image/gif", 5, 7, "s:7:0", "s:7:0"), ("image/jpeg", 11, 9, "s:7:1", "s:7:1")])
        self.assertTrue(all(e["t"] == "" and e["r"] == "img" for e in evs))

    def test_no_key_no_image_key_and_no_path_anywhere(self):
        evs = E.events_of(LINES[2])
        self.assertEqual(evs, [{"r": "img", "t": "", "m": "image/png", "w": 1280, "h": 860}])
        # (the Read's chip names its file, as every tool chip does; the
        # picture's event names only its key)
        self.assertNotIn("shot.png", json.dumps(E.events_of(LINES[2], "s:2")))

    def test_a_sidechain_and_the_captain_s_own_pictures_are_not_events(self):
        self.assertEqual(E.events_of(LINES[4], "s:1"), [])
        own = line([{"type": "text", "text": "this one"}, img("image/png", PNG)])
        self.assertEqual([e["r"] for e in E.events_of(own, "s:1")], ["me"])

    def test_dims_of_each_type(self):
        b = lambda raw: base64.b64encode(raw).decode()
        self.assertEqual(E.img_dims("image/png", b(PNG)), (2, 3))
        self.assertEqual(E.img_dims("image/gif", b(GIF)), (5, 7))
        self.assertEqual(E.img_dims("image/jpeg", b(JPEG)), (11, 9))
        vp8x = b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
        self.assertEqual(E.img_dims("image/webp", b(vp8x)), (100, 50))
        self.assertIsNone(E.img_dims("image/png", b(b"not a png at all, no")))

    def test_the_poll_keeps_them_at_their_place(self):
        path = E.transcript(SID)
        evs, _ = E.poll_forward(path, 0, OFF[4])
        self.assertEqual([e["r"] for e in evs], ["me", "tool", "img", "img", "img"])
        self.assertEqual(evs[2]["img"], f"0a1b2c3d:{OFF[2]}:0")


class Verb(unittest.TestCase):
    """cmd_image: the key to a cache file, or the reason there is none."""

    def test_a_picture_to_the_cache(self):
        code, j = call(E.cmd_image, "ada", f"0a1b2c3d:{OFF[2]}:0")
        self.assertEqual((code, j["mime"], j["bytes"]), (0, "image/png", len(PNG)))
        self.assertTrue(j["file"].startswith(os.path.join(STATE, "img") + "/") and j["file"].endswith(".png"))
        with open(j["file"], "rb") as f:
            self.assertEqual(f.read(), PNG)
        # the same key, the same file
        self.assertEqual(call(E.cmd_image, "ada", f"0a1b2c3d:{OFF[2]}:0")[1]["file"], j["file"])
        code, j = call(E.cmd_image, "ada", f"0a1b2c3d:{OFF[3]}:1")
        self.assertEqual((code, j["mime"]), (0, "image/jpeg"))

    def test_an_earlier_conversation_s(self):
        code, j = call(E.cmd_image, E.NO1, "9f8e7d6c:0:0")
        self.assertEqual((code, j["mime"]), (0, "image/png"))

    def test_the_refusals(self):
        cases = {"x": 2, "0a1b2c3d:1": 2, "../etc:0:0": 2, "0a1b2c3d:0:1:2": 2,
                 "ffffffff:0:0": 4,                         # no conversation of theirs
                 f"0a1b2c3d:{OFF[2] + 1}:0": 4,             # not a line's start
                 f"0a1b2c3d:{OFF[2]}:1": 4,                 # no second picture
                 f"0a1b2c3d:{OFF[0]}:0": 4,                 # a line with none
                 f"0a1b2c3d:{OFF[4]}:0": 4,                 # a sub-agent's
                 f"0a1b2c3d:{OFF[5]}:0": 4,                 # not the type it says
                 f"0a1b2c3d:{OFF[6]}:0": 5,                 # over the cap
                 "0a1b2c3d:99999999999:0": 4}
        for k, want in cases.items():
            self.assertEqual(call(E.cmd_image, "ada", k)[0], want, k)
        self.assertEqual(call(E.cmd_image, "nobody", f"0a1b2c3d:{OFF[2]}:0")[0], 4)

    def test_the_cache_is_pruned(self):
        d = os.path.join(STATE, "img")
        os.makedirs(d, exist_ok=True)
        old = os.path.join(d, "old.png")
        open(old, "wb").close()
        os.utime(old, (time.time() - E.IMG_KEEP_S - 60,) * 2)
        call(E.cmd_image, "ada", f"0a1b2c3d:{OFF[2]}:0")
        self.assertFalse(os.path.exists(old))


KEY = "k" * 24
# (a limited login is off with a password under 16 characters)
OWNER, NO1, CREW, STEWARD = ("t", "tt"), ("no1", "n" * 16), ("crew", "c" * 16), ("stew", "s" * 16)


@unittest.skipIf(os.environ.get("SKIP_ROUTE") == "1", "SKIP_ROUTE=1")
class Route(unittest.TestCase):
    """GET /engineer/<name>/image on the real server and the real script."""

    @classmethod
    def setUpClass(cls):
        tmp = os.path.join(TMP, "route")
        os.makedirs(tmp)
        sys.path.insert(0, os.path.join(HERE, "..", "lcars-ui", "test"))
        from caldav import build, free_port
        binary = os.environ.get("LCARS_TEST_BIN")
        if not binary:
            binary = os.path.join(tmp, "lcars")
            build(binary)
        cls.port = free_port()
        env = dict(os.environ, HOME=FAKE_HOME, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=OWNER[0], LCARS_AUTH_PASS=OWNER[1],
                   LCARS_NO1_USER=NO1[0], LCARS_NO1_PASS=NO1[1], LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
                   LCARS_STEWARD_USER=STEWARD[0], LCARS_STEWARD_PASS=STEWARD[1],
                   LCARS_ENGINEER="1", LCARS_ENGINEER_KEY=KEY,
                   LCARS_ENGINEER_SCRIPT=os.path.join(HERE, "engineer.py"))
        env.pop("LCARS_ENGINEER_LOGIN", None)
        cls.log = open(os.path.join(tmp, "server.log"), "w")
        cls.proc = subprocess.Popen([binary, "--port", str(cls.port)], cwd=tmp, env=env,
                                    stdout=cls.log, stderr=subprocess.STDOUT)
        _procs.append(cls.proc)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()

    def req(self, path, login=OWNER, method="GET", key=KEY):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Authorization": "Basic " + base64.b64encode(f"{login[0]}:{login[1]}".encode()).decode()}
        if key:
            h["X-LCARS-Engineer-Key"] = key
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), body

    def test_the_owner_gets_the_picture(self):
        st, h, body = self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[2]}:0")
        self.assertEqual((st, h["content-type"], body), (200, "image/png", PNG))
        self.assertEqual(h["cache-control"], "private, max-age=31536000, immutable")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        st, h, body = self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[3]}:0")
        self.assertEqual((st, h["content-type"], body), (200, "image/gif", GIF))
        # Number One's session too, and an earlier conversation's
        st, h, body = self.req("/engineer/number-one/image?k=9f8e7d6c:0:0")
        self.assertEqual((st, body), (200, PNG))
        st, h, body = self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[2]}:0", method="HEAD")
        self.assertEqual((st, h["content-length"], body), (200, str(len(PNG)), b""))

    def test_the_limited_logins_and_no_key_are_refused(self):
        k = f"/engineer/ada/image?k=0a1b2c3d:{OFF[2]}:0"
        for login in (NO1, CREW, STEWARD):
            self.assertEqual(self.req(k, login)[0], 403, login[0])
        self.assertEqual(self.req(k, key="")[0], 401)
        self.assertEqual(self.req(k, ("t", "wrong"))[0], 401)

    def test_a_bad_key_and_the_cap(self):
        for q in ("", "?k=", "?k=x", "?k=0a1b2c3d:1", "?k=..%2F:0:0", "?k=0a1b2c3d:0:1234", "?k=0a1b2c3d:0:0;rm"):
            self.assertEqual(self.req("/engineer/ada/image" + q)[0], 400, q)
        self.assertEqual(self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[2]}:3")[0], 404)
        self.assertEqual(self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[2] + 2}:0")[0], 404)
        self.assertEqual(self.req("/engineer/nobody/image?k=0a1b2c3d:0:0")[0], 404)
        self.assertEqual(self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[6]}:0")[0], 413)
        self.assertEqual(self.req(f"/engineer/ada/image?k=0a1b2c3d:{OFF[2]}:0", method="POST")[0], 405)


if __name__ == "__main__":
    unittest.main()
