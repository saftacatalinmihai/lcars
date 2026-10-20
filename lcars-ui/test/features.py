#!/usr/bin/env python3
"""GET /features (lcars_features.h), end to end against scratch servers.

The route says, for each feature, whether it is on and - when off - the
names of the settings (or, for a program with no setting, the program) it
lacks; never a value, never a path or host of the box. This starts:

  1. a bare server: no optional setting, an empty PATH, a media root that
     is not there, chat off, embeddings off - every feature off but
     CalDAV, each needing exactly its names;
  2. a full one: every setting given (keys, logins, a writable media root,
     stand-in ffmpeg/claude/git/gh/engineer.py, a stand-in embedding
     service that answers) - every feature on, and none of the values, the
     stand-ins' paths or the temp directory anywhere in the answer;
  3. one with embeddings on but nothing answering at their URL, and
     LCARS_TTS=elevenlabs with no key - embeddings need LCARS_EMBED_URL,
     speech ELEVENLABS_API_KEY;

and on the full one checks who may ask: the owner's login (200), Number
One's and the crew's (403), none (401), and POST (405); and that GET /
lists the route.

Each server is a scratch build (`make -n lcars-release`, compiled to a temp
path - never `make` itself, which on the VPS would overwrite the live
binary) on an empty database in a temp directory.

    python3 test/features.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/features.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import killclean  # its scratch and servers go when the run is killed

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
USER, PASS = "t", "t"
NO1 = ("no1-test", "n" * 20)
CREW = ("crew-test", "c" * 20)
STEWARD = ("steward-test", "s" * 20)

# values that must never come back (each long and unlike any setting name)
SECRETS = {
    "LCARS_MAPY_KEY": "mapyKEYvalue1234567890",
    "DEEPGRAM_API_KEY": "dgKEYvalue1234567890",
    "LCARS_STRAVA_CLIENT_ID": "stravaID98765",
    "LCARS_STRAVA_CLIENT_SECRET": "stravaSECRET98765",
    "LOGSEQ_URL": "http://logseq.example:12315",
    "LOGSEQ_TOKEN": "logseqTOKEN98765",
    "LCARS_ENGINEER_KEY": "engineerKEY1234567890",
}

ALL = ["media", "media_ffmpeg", "computer", "navigator", "maps", "transcription", "speech",
       "embeddings", "caldav", "strava", "logseq", "engineers", "number_one", "crew", "reports"]

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
        sys.exit("features: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("features: build failed\n" + r.stderr[-3000:])


def auth(user, pw):
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


class Server:
    """A scratch server in `cwd` with exactly `env` (and the login): no
    variable of this shell's reaches it, so the box's own settings cannot
    turn a feature on."""

    def __init__(self, binary, cwd, env):
        self.port = free_port()
        self.cwd = cwd
        full = dict(env, LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS, LCARS_CALDAV_LOG="0")
        self.log = open(cwd / "server.log", "w")
        stdbuf = shutil.which("stdbuf")
        pre = [stdbuf, "-oL", "-eL"] if stdbuf else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--port", str(self.port)],
                                                     cwd=cwd, env=full, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit(f"features: the scratch server did not come up; see {cwd / 'server.log'}")

    def get(self, path, login=(USER, PASS), method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers={"Authorization": auth(*login)} if login else {})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def features(self):
        st, body = self.get("/features")
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        return st, body, doc

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


class Embedder(http.server.BaseHTTPRequestHandler):
    """An OpenAI-shaped embeddings service: a small vector per input."""

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            inputs = json.loads(self.rfile.read(n)).get("input") or []
        except ValueError:
            inputs = []
        out = json.dumps({"data": [{"index": i, "embedding": [0.1, 0.2, 0.3, 0.4]}
                                   for i in range(len(inputs))]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def stub(path, text="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def by_name(doc):
    return {f.get("name"): f for f in (doc or {}).get("features", [])}


def shape(doc):
    fs = (doc or {}).get("features")
    ok = isinstance(fs, list) and [f.get("name") for f in fs] == ALL
    for f in fs or []:
        ok = ok and set(f) == {"name", "on", "needs", "note"} and isinstance(f["on"], bool) \
            and isinstance(f["needs"], list) and all(isinstance(x, str) for x in f["needs"]) \
            and f["on"] == (f["needs"] == []) and isinstance(f["note"], str) and len(f["note"]) > 20
    return ok


def settle(s, name, until):
    """The answer once feature `name` satisfies until(f): the embedding
    service's state is known a request after start, not at it."""
    doc = None
    for _ in range(50):
        _, _, doc = s.features()
        if until(by_name(doc).get(name) or {}):
            break
        time.sleep(0.1)
    return doc


def bare(binary, tmp):
    print("a bare server: every feature off but CalDAV, each naming what it lacks")
    d = tmp / "bare"
    (d / "home").mkdir(parents=True)
    (d / "bin").mkdir()
    env = {"HOME": str(d / "home"), "PATH": str(d / "bin"), "LCARS_EMBED": "0", "LCARS_CHAT": "0",
           "LCARS_MEDIA_ROOT": str(d / "nowhere"), "LCARS_CLAUDE_BIN": str(d / "no-claude")}
    s = Server(binary, d, env)
    try:
        st, body, doc = s.features()
        check(st == 200 and shape(doc), f"200 and every feature in order, each {{name,on,needs,note}} (got {st})")
        py = ["python3"]  # found on $PATH only (EngineerPython), and PATH is an empty dir
        want = {
            "media": ["LCARS_MEDIA_ROOT"], "media_ffmpeg": ["LCARS_FFMPEG_BIN"],
            "computer": ["LCARS_CHAT", "LCARS_CLAUDE_BIN"], "navigator": ["LCARS_CHAT", "LCARS_CLAUDE_BIN"],
            "maps": ["LCARS_MAPY_KEY"], "transcription": ["DEEPGRAM_API_KEY"], "speech": ["DEEPGRAM_API_KEY"],
            "embeddings": ["LCARS_EMBED"], "caldav": [],
            "strava": ["LCARS_STRAVA_CLIENT_ID", "LCARS_STRAVA_CLIENT_SECRET"],
            "logseq": ["LOGSEQ_URL", "LOGSEQ_TOKEN"],
            "engineers": ["LCARS_ENGINEER", "LCARS_ENGINEER_KEY", "LCARS_ENGINEER_SCRIPT", *py, "git", "gh",
                          "LCARS_CLAUDE_BIN"],
            "number_one": ["LCARS_NO1_USER", "LCARS_NO1_PASS"],
            "crew": ["LCARS_CREW_USER", "LCARS_CREW_PASS", "LCARS_STEWARD_USER", "LCARS_STEWARD_PASS"],
            "reports": ["LCARS_MEDIA_ROOT"],
        }
        got = by_name(doc)
        for name in ALL:
            f = got.get(name) or {}
            check(f.get("needs") == want[name] and f.get("on") == (want[name] == []),
                  f"{name}: needs {want[name]} (got {f.get('on')}, {f.get('needs')})")
        check(str(d) not in body and "/home" not in body, "no path of the box in the answer")
    finally:
        s.stop()


def full(binary, tmp):
    print("a full server: every feature on, no value in the answer")
    d = tmp / "full"
    (d / "home").mkdir(parents=True)
    (d / "root" / "media").mkdir(parents=True)
    bindir = d / "bin"
    stub(bindir / "git")
    stub(bindir / "gh")
    stub(bindir / "python3")  # EngineerPython looks on $PATH
    ffmpeg = stub(d / "tools" / "ffmpeg")
    claude = stub(d / "tools" / "claude")
    script = stub(d / "tools" / "engineer.py", "print('stand-in')\n")
    port = free_port()
    emb = http.server.ThreadingHTTPServer(("127.0.0.1", port), Embedder)
    threading.Thread(target=emb.serve_forever, daemon=True).start()
    env = dict(SECRETS, HOME=str(d / "home"), PATH=str(bindir), LCARS_MEDIA_ROOT=str(d / "root"),
               LCARS_FFMPEG_BIN=str(ffmpeg), LCARS_CLAUDE_BIN=str(claude), LCARS_ENGINEER="1",
               LCARS_ENGINEER_SCRIPT=str(script), LCARS_EMBED="1",
               LCARS_EMBED_URL=f"http://127.0.0.1:{port}/v1/embeddings", LCARS_EMBED_MODEL="stand-in",
               LCARS_NO1_USER=NO1[0], LCARS_NO1_PASS=NO1[1], LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
               LCARS_STEWARD_USER=STEWARD[0], LCARS_STEWARD_PASS=STEWARD[1])
    s = Server(binary, d, env)
    try:
        doc = settle(s, "embeddings", lambda f: f.get("on"))
        st, body, doc = s.features()
        check(st == 200 and shape(doc), f"200 and the shape (got {st})")
        off = {n: f["needs"] for n, f in by_name(doc).items() if not f["on"]}
        check(off == {}, f"every feature on (off: {off})")
        leaked = [k for k, v in SECRETS.items() if v in body]
        leaked += [p for p in (NO1[0], NO1[1], CREW[1], STEWARD[1], str(d), str(port)) if p in body]
        check(leaked == [], f"no value, login, path or port in the answer (leaked: {leaked})")

        print("who may ask")
        check(s.get("/features", NO1)[0] == 403, "Number One's login: 403")
        check(s.get("/features", CREW)[0] == 403, "the crew's login: 403")
        check(s.get("/features", STEWARD)[0] == 403, "the steward's login: 403")
        st, body = s.get("/features", NO1)
        check(not any(v in body for v in SECRETS.values()) and "LCARS_" not in body,
              "the refusal names no setting")
        check(s.get("/features", None)[0] == 401, "no login: 401")
        check(s.get("/features", ("t", "wrong"))[0] == 401, "a wrong password: 401")
        check(s.get("/features", method="POST")[0] == 405, "POST: 405")
        st, body = s.get("/")
        check(st == 200 and '"/features"' in body, "GET / lists /features")

        print("the media root going away turns media and reports off at the next ask")
        shutil.rmtree(d / "root" / "media")
        got = by_name(s.features()[2])
        check(got["media"]["needs"] == ["LCARS_MEDIA_ROOT"] and got["reports"]["needs"] == ["LCARS_MEDIA_ROOT"],
              f"media and reports need LCARS_MEDIA_ROOT (got {got['media']['needs']}, {got['reports']['needs']})")
    finally:
        s.stop()
        emb.shutdown()


def unreachable(binary, tmp):
    print("embeddings on with nothing answering; LCARS_TTS=elevenlabs with no key")
    d = tmp / "unreachable"
    (d / "home").mkdir(parents=True)
    env = {"HOME": str(d / "home"), "PATH": str(d), "LCARS_CHAT": "0", "LCARS_EMBED": "1",
           "LCARS_EMBED_URL": f"http://127.0.0.1:{free_port()}/v1/embeddings", "LCARS_TTS": "elevenlabs",
           "DEEPGRAM_API_KEY": SECRETS["DEEPGRAM_API_KEY"]}
    s = Server(binary, d, env)
    try:
        doc = settle(s, "embeddings", lambda f: f.get("needs") == ["LCARS_EMBED_URL"])
        got = by_name(doc)
        check(got["embeddings"]["needs"] == ["LCARS_EMBED_URL"],
              f"embeddings need LCARS_EMBED_URL (got {got['embeddings']['needs']})")
        check(got["speech"]["needs"] == ["ELEVENLABS_API_KEY"],
              f"speech needs ELEVENLABS_API_KEY (got {got['speech']['needs']})")
        check(got["transcription"]["on"], "transcription on: Deepgram's key is there whatever LCARS_TTS speaks with")
    finally:
        s.stop()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-features-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    bare(binary, tmp)
    full(binary, tmp)
    unreachable(binary, tmp)
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server logs under {tmp}")
        sys.exit(1)
    print(f"\nfeatures: all {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
