#!/usr/bin/env python3
"""POST /say's engines, end to end against a stand-in ElevenLabs and Deepgram.

The route (lcars_say.h) relays a line to the text-to-speech service
LCARS_TTS names; with LCARS_TTS=elevenlabs and DEEPGRAM_API_KEY both there,
Deepgram speaks a line ElevenLabs cannot, in the seat's Aura-2 voice. This
builds a scratch server, points both at one stand-in on loopback
($LCARS_ELEVENLABS_URL, $LCARS_DEEPGRAM_URL) and checks:

  1. ElevenLabs speaking: Flash, mp3 or pcm_24000, the key, the voice in
     the path, X-LCARS-Say: elevenlabs;
  2. falling through to Deepgram - a 500, no connection, no first byte in
     time - in the seat's voice (every ElevenLabs id the page uses mapped),
     the format kept, X-LCARS-Say: deepgram, the log line; ElevenLabs asked
     again on the next line;
  3. a quota (401 quota_exceeded) and a 429 remembered: the next lines go
     to Deepgram without asking ElevenLabs;
  4. what is not fallen through: an unknown voice (404) is still a 502;
     both failing a 502 naming both; no DEEPGRAM_API_KEY, no fallback;
  5. LCARS_TTS=deepgram as before, through $LCARS_DEEPGRAM_URL.

    python3 test/say.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/say.py

Nothing here touches the journal, a running server, or the real services:
no credits are spent.
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import killclean  # noqa: E402  its scratch goes when the run is killed
from caldav import build, free_port  # noqa: E402

MAIN = ("t", "t")
EL_KEY = "el-stand-in-key-0123456789"
DG_KEY = "dg-stand-in-key-0123456789"
# the page's SAY_VOICES, seat by seat: ElevenLabs' id and Aura-2's name
SEATS = [("EXAVITQu4vr4xnSDxMaL", "aura-2-thalia-en"), ("FGY2WhTYpPnrIDTdsKH5", "aura-2-andromeda-en"),
         ("XrExE9yKIg1WjnnlVkGX", "aura-2-luna-en"), ("cgSgspJ2msm6clMCkdW9", "aura-2-asteria-en"),
         ("JBFqnCBsd6RMkjVDRZzb", "aura-2-apollo-en"), ("nPczCjzI2devNBz1zQrb", "aura-2-orion-en"),
         ("onwK4e9ZLuTAKqWW03F9", "aura-2-zeus-en"), ("cjVigY5qzO86Huf0OWal", "aura-2-odysseus-en"),
         ("pFZP5JQG7iQjIQuC4Bku", "aura-2-hera-en"), ("Xb7hH8MSUJpSbSDYk0k2", "aura-2-athena-en")]

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Upstream(http.server.BaseHTTPRequestHandler):
    """Both services on one port, by path. `el` and `dg` say how each answers:
    "ok", or a status to refuse with, or "slow" (no byte for six seconds)."""
    el = "ok"
    dg = "ok"
    seen = []
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        eleven = u.path.startswith("/v1/text-to-speech/")
        who = "elevenlabs" if eleven else "deepgram"
        voice = u.path.split("/")[3] if eleven else q.get("model", "")
        Upstream.seen.append({"who": who, "voice": voice, "q": q, "body": body,
                              "auth": self.headers.get("Authorization"),
                              "xi": self.headers.get("xi-api-key")})
        mode = Upstream.el if eleven else Upstream.dg
        if mode == "slow":
            time.sleep(6)
            mode = "ok"
        if mode == "ok":
            raw = (who + ":" + voice + ":").encode() + b"\x00\x01" * 400
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        status = int(mode)
        err = {"detail": {"status": "quota_exceeded", "message": "This request exceeds your quota."}} \
            if status == 401 else {"detail": {"status": "voice_not_found"}} if status == 404 \
            else {"err_msg": "busy", "status": status}
        raw = json.dumps(err).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class Server:
    def __init__(self, binary, tmp, extra):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1])
        for k in ("DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "LCARS_DEEPGRAM_URL",
                  "LCARS_ELEVENLABS_URL", "LCARS_TTS"):
            env.pop(k, None)
        env.update(extra)
        tmp.mkdir(parents=True, exist_ok=True)
        self.logpath = tmp / "server.log"
        self.log = open(self.logpath, "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("say: the scratch server did not come up; see " + str(self.logpath))

    def say(self, voice, fmt=None, text="Aye, Captain.", style=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=40)
        b = {"text": text, "voice": voice}
        if fmt:
            b["format"] = fmt
        if style is not None:
            b["style"] = style
        h = {"Content-Type": "application/json", "Authorization": "Basic " +
             base64.b64encode(f"{MAIN[0]}:{MAIN[1]}".encode()).decode()}
        Upstream.seen.clear()
        t0 = time.monotonic()
        c.request("POST", "/say", body=json.dumps(b), headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), r.getheader("X-LCARS-Say"), data, time.monotonic() - t0

    def logged(self):
        self.log.flush()
        time.sleep(0.2)
        return self.logpath.read_text()

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-say-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)

    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    both = {"LCARS_TTS": "elevenlabs", "ELEVENLABS_API_KEY": EL_KEY, "DEEPGRAM_API_KEY": DG_KEY,
            "LCARS_ELEVENLABS_URL": base, "LCARS_DEEPGRAM_URL": base}
    servers = []
    try:
        print("ElevenLabs speaking")
        s = Server(binary, tmp / "both", both)
        servers.append(s)
        check("deepgram when it cannot" in s.logged(), "the start log says Deepgram stands behind it")
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        sent = Upstream.seen[:]
        check(st == 200 and ct == "audio/mpeg" and eng == "elevenlabs", f"a line in mp3 by ElevenLabs ({st} {ct} {eng})")
        check(data.startswith(b"elevenlabs:EXAVITQu4vr4xnSDxMaL:"), "the audio relayed as it came")
        check(len(sent) == 1 and sent[0]["xi"] == EL_KEY and sent[0]["body"].get("model_id") == "eleven_flash_v2_5"
              and sent[0]["q"].get("output_format") == "mp3_44100_128", "Flash, the key, mp3_44100_128")
        st, ct, eng, data, _ = s.say("Xb7hH8MSUJpSbSDYk0k2", "pcm")
        check(st == 200 and ct.startswith("audio/L16") and Upstream.seen[0]["q"].get("output_format") == "pcm_24000",
              f"pcm asked as pcm_24000, answered as audio/L16 ({ct})")
        check("voice_settings" not in Upstream.seen[0]["body"], "no style: no voice_settings, ElevenLabs' own")

        print("an engineer's own voice (style)")
        data_style = {"stability": 0.92, "speed": 1.05, "fallback": "aura-2-orpheus-en"}
        st, ct, eng, data, _ = s.say("cjVigY5qzO86Huf0OWal", "pcm", style=data_style)
        vs = Upstream.seen[0]["body"].get("voice_settings") or {}
        check(st == 200 and eng == "elevenlabs" and vs.get("stability") == 0.92 and vs.get("speed") == 1.05
              and vs.get("similarity_boost") == 0.75 and vs.get("style") == 0 and vs.get("use_speaker_boost") is True,
              f"stability and speed sent as voice_settings, the rest at ElevenLabs' defaults ({vs})")
        st, ct, eng, data, _ = s.say("cjVigY5qzO86Huf0OWal", style={"speed": 0.8})
        vs = Upstream.seen[0]["body"].get("voice_settings") or {}
        check(st == 200 and vs.get("speed") == 0.8 and vs.get("stability") == 0.5, f"a speed alone: stability at 0.5 ({vs})")
        for bad, why in (({"stability": 1.5}, "stability"), ({"stability": "0.9"}, "stability"),
                         ({"speed": 2}, "speed"), ({"speed": 0.5}, "speed"),
                         ({"fallback": "EXAVITQu4vr4xnSDxMaL"}, "fallback"), ({"fallback": "aura-2/../x"}, "fallback")):
            st, ct, eng, data, _ = s.say("cjVigY5qzO86Huf0OWal", style=bad)
            if not (st == 400 and why.encode() in data and not Upstream.seen):
                check(False, f"style {bad}: {st} {data[:80]!r}")
                break
        else:
            check(True, "a style out of range, quoted, or a fallback not an Aura-2 name: 400, nothing asked")

        print("falling through to Deepgram")
        Upstream.el = "500"
        for el, aura in SEATS:
            st, ct, eng, data, _ = s.say(el, "pcm")
            seen = [x["who"] for x in Upstream.seen]
            dg = Upstream.seen[-1]
            if not (st == 200 and eng == "deepgram" and seen == ["elevenlabs", "deepgram"] and dg["voice"] == aura
                    and data.startswith(f"deepgram:{aura}:".encode()) and ct.startswith("audio/L16")
                    and dg["q"].get("encoding") == "linear16" and dg["q"].get("container") == "none"
                    and dg["auth"] == "Token " + DG_KEY):
                check(False, f"{el} on a 500: {st} {eng} {seen} {dg['voice']} {ct}")
                break
        else:
            check(True, "a 500: each of the ten seats spoken by Deepgram in its Aura-2 voice, pcm kept, the key")
        st, ct, eng, data, _ = s.say("SomeVoiceThePageAdded1")
        check(st == 200 and eng == "deepgram" and Upstream.seen[-1]["voice"] == "aura-2-thalia-en" and ct == "audio/mpeg"
              and Upstream.seen[-1]["q"].get("encoding") == "mp3", "a voice the table does not know: Deepgram's default, mp3 kept")
        check("Say: elevenlabs refused (HTTP 500), deepgram spoke 13 chars" in s.logged(), "the log line")
        st, ct, eng, data, _ = s.say("cjVigY5qzO86Huf0OWal", "pcm", style=data_style)
        check(st == 200 and eng == "deepgram" and Upstream.seen[-1]["voice"] == "aura-2-orpheus-en"
              and "voice_settings" not in Upstream.seen[-1]["body"],
              "a style's fallback: Deepgram speaks in the page's Aura-2 voice, over the table's, no voice_settings")
        Upstream.el = "ok"
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(eng == "elevenlabs" and len(Upstream.seen) == 1, "a 5xx is not remembered: ElevenLabs speaks the next line")

        Upstream.el = "slow"
        st, ct, eng, data, took = s.say("JBFqnCBsd6RMkjVDRZzb")
        check(st == 200 and eng == "deepgram" and took < 5.8, f"no first byte in time: Deepgram, after {took:.1f}s")
        check("no audio in" in s.logged(), "logged as no audio in time")
        Upstream.el = "404"
        st, ct, eng, data, _ = s.say("NotARealVoiceId00000")
        check(st == 502 and b"elevenlabs answered HTTP 404" in data and [x["who"] for x in Upstream.seen] == ["elevenlabs"],
              "an unknown voice (404) is a 502, Deepgram not asked")
        Upstream.el, Upstream.dg = "500", "500"
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(st == 502 and b"elevenlabs" in data and b"deepgram" in data, "both failing: a 502 naming both")
        Upstream.dg = "ok"

        print("a quota remembered")
        Upstream.el = "401"
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(st == 200 and eng == "deepgram", "quota_exceeded (401): Deepgram speaks")
        check("elevenlabs refused (HTTP 401, quota exceeded), deepgram spoke" in s.logged(), "the log names the quota")
        check("Say: elevenlabs spoke 13 chars" in s.logged(), "a line spoken is logged with its length")
        Upstream.el = "ok"
        st, ct, eng, data, _ = s.say("JBFqnCBsd6RMkjVDRZzb")
        check(st == 200 and eng == "deepgram" and [x["who"] for x in Upstream.seen] == ["deepgram"]
              and Upstream.seen[0]["voice"] == "aura-2-apollo-en", "the next line goes straight to Deepgram")
        check("elevenlabs held off (HTTP 401, quota exceeded" in s.logged(), "and says it held ElevenLabs off")
        s.stop()
        servers.remove(s)

        print("a 429 remembered, no connection")
        s = Server(binary, tmp / "busy", both)
        servers.append(s)
        Upstream.el = "429"
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(st == 200 and eng == "deepgram", "a 429: Deepgram speaks")
        Upstream.el = "ok"
        s.say("EXAVITQu4vr4xnSDxMaL")
        check([x["who"] for x in Upstream.seen] == ["deepgram"], "and the next line skips ElevenLabs")
        s.stop()
        servers.remove(s)
        s = Server(binary, tmp / "gone", dict(both, LCARS_ELEVENLABS_URL=f"http://127.0.0.1:{free_port()}"))
        servers.append(s)
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(st == 200 and eng == "deepgram", "ElevenLabs unreachable: Deepgram speaks")
        s.stop()
        servers.remove(s)

        print("no fallback without Deepgram's key; Deepgram alone")
        s = Server(binary, tmp / "alone", {k: v for k, v in both.items() if k != "DEEPGRAM_API_KEY"})
        servers.append(s)
        check("deepgram when it cannot" not in s.logged(), "the start log promises nothing")
        Upstream.el = "500"
        st, ct, eng, data, _ = s.say("EXAVITQu4vr4xnSDxMaL")
        check(st == 502 and [x["who"] for x in Upstream.seen] == ["elevenlabs"], "ElevenLabs failing is a 502")
        Upstream.el = "ok"
        s.stop()
        servers.remove(s)
        s = Server(binary, tmp / "dg", {"LCARS_TTS": "deepgram", "DEEPGRAM_API_KEY": DG_KEY, "LCARS_DEEPGRAM_URL": base})
        servers.append(s)
        st, ct, eng, data, _ = s.say("aura-2-zeus-en")
        check(st == 200 and eng == "deepgram" and Upstream.seen[0]["voice"] == "aura-2-zeus-en"
              and Upstream.seen[0]["q"].get("encoding") == "mp3", "LCARS_TTS=deepgram speaks as before")
    finally:
        for x in servers:
            x.stop()
        up.shutdown()
    print(f"{checks[0] - len(fails)}/{checks[0]} checks passed")
    if fails:
        print("say: " + str(len(fails)) + " failed; logs in " + str(tmp))
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
