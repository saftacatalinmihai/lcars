#!/usr/bin/env python3
"""POST /transcribe, end to end against a stand-in Deepgram.

The route (lcars_say.h) relays a voice note - raw PCM, 16 kHz mono s16le, the
G2 glasses' microphone - to Deepgram's pre-recorded /v1/listen and answers
{"text","bytes","duration_ms"}. This builds a scratch server, points it at a
stand-in Deepgram on loopback (LCARS_DEEPGRAM_URL) and checks:

  1. what Deepgram is sent: the PCM untouched, its shape in the query, the
     key in the Authorization header;
  2. the contract: the transcript (escapes and non-ASCII intact), the bytes,
     the duration; silence is a 200 with "";
  3. what the route refuses before Deepgram: JSON (415), an empty or odd
     body (400), a GET (405), no login (401);
  4. Deepgram failing: a refusal or an answer with no transcript is a 502;
  5. no DEEPGRAM_API_KEY: 503.

    python3 test/transcribe.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/transcribe.py

Nothing here touches the journal, a running server or the real Deepgram.
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build, free_port  # noqa: E402

MAIN = ("t", "t")
KEY = "stand-in-key-0123456789"

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Deepgram(http.server.BaseHTTPRequestHandler):
    """Answers /v1/listen with whatever `reply` holds, and keeps the request."""
    reply = (200, {})
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        Deepgram.seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                              "ctype": self.headers.get("Content-Type"), "body": body})
        status, payload = Deepgram.reply
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def answer(transcript):
    """The shape of a Deepgram pre-recorded answer, words and all."""
    return {"metadata": {"request_id": "x", "duration": 1.0},
            "results": {"channels": [{"alternatives": [{
                "transcript": transcript, "confidence": 0.98,
                "words": [{"word": w, "start": 0.1, "end": 0.2} for w in transcript.split()]}]}]}}


class Server:
    def __init__(self, binary, tmp, extra):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1])
        for k in ("DEEPGRAM_API_KEY", "LCARS_DEEPGRAM_URL", "LCARS_TTS"):
            env.pop(k, None)
        env.update(extra)
        tmp.mkdir(parents=True, exist_ok=True)
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("transcribe: the scratch server did not come up; see " + str(tmp / "server.log"))

    def post(self, body, ctype="application/octet-stream", login=MAIN, method="POST"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=40)
        h = {"Content-Type": ctype}
        if login:
            h["Authorization"] = "Basic " + base64.b64encode(
                f"{login[0]}:{login[1]}".encode()).decode()
        c.request(method, "/transcribe", body=body, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        c.close()
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-transcribe-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)

    dg = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Deepgram)
    threading.Thread(target=dg.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{dg.server_address[1]}"

    # a second of a 440Hz tone: what is in it does not matter to a stand-in
    pcm = b"".join(struct.pack("<h", int(8000 * ((i // 18) % 2 * 2 - 1))) for i in range(16000))

    print("\nwith a key")
    s = Server(binary, tmp / "key", {"DEEPGRAM_API_KEY": KEY, "LCARS_DEEPGRAM_URL": base})
    try:
        Deepgram.reply = (200, answer('Hello, captain. Café "Ten Forward"\nat 0900.'))
        st, ans = s.post(pcm)
        check(st == 200, f"a voice note is a 200 ({st} {ans})")
        check(isinstance(ans, dict) and ans.get("text") == 'Hello, captain. Café "Ten Forward"\nat 0900.',
              "the transcript comes back whole: quotes, a newline, an é")
        check(isinstance(ans, dict) and ans.get("bytes") == len(pcm) and ans.get("duration_ms") == 1000,
              "bytes and duration_ms are the body's")
        check(isinstance(ans, dict) and set(ans) == {"text", "bytes", "duration_ms"},
              "nothing else of Deepgram's answer is passed on")
        req = Deepgram.seen[-1] if Deepgram.seen else {}
        path = urllib.parse.urlparse(req.get("path", ""))
        q = urllib.parse.parse_qs(path.query)
        check(path.path == "/v1/listen", "it asks /v1/listen")
        check(q.get("encoding") == ["linear16"] and q.get("sample_rate") == ["16000"]
              and q.get("channels") == ["1"], "with the PCM's shape in the query")
        check(req.get("auth") == "Token " + KEY, "and the key in Authorization")
        check(req.get("body") == pcm, "the PCM is sent untouched")

        Deepgram.reply = (200, answer(""))
        st, ans = s.post(pcm)
        check(st == 200 and isinstance(ans, dict) and ans.get("text") == "", "silence is a 200 with \"\"")

        n = len(Deepgram.seen)
        check(s.post(json.dumps({"text": "x"}), ctype="application/json")[0] == 415, "a JSON body is a 415")
        check(s.post(b"")[0] == 400, "an empty body is a 400")
        check(s.post(b"\0\0\0")[0] == 400, "an odd length is a 400")
        check(s.post(None, method="GET")[0] == 405, "a GET is a 405")
        check(s.post(pcm, login=None)[0] == 401, "no login is a 401")
        check(len(Deepgram.seen) == n, "none of those reached Deepgram")

        Deepgram.reply = (401, {"err_code": "INVALID_AUTH", "err_msg": "Invalid credentials."})
        st, ans = s.post(pcm)
        check(st == 502 and "401" in str(ans), f"Deepgram refusing is a 502 that says so ({st} {ans})")
        Deepgram.reply = (200, {"metadata": {}})
        st, ans = s.post(pcm)
        check(st == 502, f"an answer without a transcript is a 502 ({st})")
        Deepgram.reply = (200, b"not json")
        check(s.post(pcm)[0] == 502, "an answer that is not JSON is a 502")
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()

    print("\nno key")
    s = Server(binary, tmp / "nokey", {"LCARS_DEEPGRAM_URL": base})
    try:
        n = len(Deepgram.seen)
        st, ans = s.post(pcm)
        check(st == 503 and "DEEPGRAM_API_KEY" in str(ans), f"no DEEPGRAM_API_KEY is a 503 ({st})")
        check(len(Deepgram.seen) == n, "and nothing is sent")
    finally:
        s.stop()
    dg.shutdown()

    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server logs under {tmp}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
