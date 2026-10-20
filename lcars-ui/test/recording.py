#!/usr/bin/env python3
"""Recording, end to end: from a microphone (and a camera) to a file that plays.

The QuickJS suite drives dictation's tape against fakes, and e2e.py drives it
in a real browser against stubbed routes. Neither ever met the server, and the
server is where a recording becomes a file: the slices are staged, the tape
attached, the stop order cut off, a WebM given its cues and a fragmented MP4
(what an iPhone records) remuxed into one that says how long it is. That last
one was missing for a while, and an iPhone showed "--:--" and would not play
its own dictation. So this runs the real thing:

  1. a scratch build of the server (`make -n lcars-release`, compiled to a
     temp path - never `make` itself, which on the VPS would overwrite the
     live binary), on an empty database and a temporary media root, with
     real ffmpeg;
  2. the server alone: iPhone-style fragmented M4A/MP4, WebM audio and video,
     cuts, a tape streamed in slices (a resent one, a gap), the attach, and
     GET /media/ (ranges, HEAD, the disk cache, paths it must refuse) - every
     stored file checked with ffprobe;
  3. the page, in headless Chromium with a fake microphone and camera and a
     fake recogniser: audio dictation and video dictation through the editor,
     the slices streamed while it records, the link it types, and the
     reader's player loading a real duration and playing.

    python3 test/recording.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/recording.py
    LCARS_TEST_CONSOLE=1 ...             # the page's console and tape requests, timed

Needs ffmpeg/ffprobe (libx264, aac, libopus, libvpx) and Playwright's
Chromium. Nothing here touches the journal, the NAS or a running server.
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import threading
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
USER, PASS = "t", "t"
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

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


# --------------------------------------------------------------- the server

def build(out):
    """The release compile line, pointed at `out` instead of ./lcars."""
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-release"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and " -o lcars lcars.c" in l), None)
    if not line:
        sys.exit("recording: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("recording: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp):
        self.tmp = tmp
        self.root = tmp / "root"
        self.cache = tmp / "cache"
        (self.root / "media").mkdir(parents=True)
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_MEDIA_ROOT=str(self.root), LCARS_MEDIA_CACHE=str(self.cache),
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS)
        self.log = open(tmp / "server.log", "w")
        # cwd is the temp dir: that is where it makes its lcars.db
        # line-buffered, or what it said last is lost when it is stopped
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + "/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("recording: the scratch server did not come up; see " + str(tmp / "server.log"))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()

    def req(self, method, path, body=None, headers=None, auth=True, host=None):
        """(status, headers, body bytes) - errors are answers too, not exceptions."""
        h = dict(headers or {})
        if auth:
            h["Authorization"] = AUTH
        c = http.client.HTTPConnection(host or "127.0.0.1", self.port, timeout=60)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, data

    def json(self, method, path, body=None, headers=None):
        st, _, data = self.req(method, path, body, headers)
        try:
            return st, json.loads(data or b"null")
        except ValueError:
            return st, data


# ------------------------------------------------------------------- files

def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def probe(path):
    """{'duration': s, 'streams': ['aac', 'h264', ...], 'fragmented': bool}"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_name", "-of", "json", str(path)],
                       capture_output=True, text=True)
    info = json.loads(r.stdout or "{}")
    try:
        dur = float(info.get("format", {}).get("duration", 0))
    except ValueError:
        dur = 0.0
    return {"duration": dur,
            "streams": [s.get("codec_name") for s in info.get("streams", [])],
            "fragmented": fragmented(path)}


def fragmented(path):
    """A top-level 'moof': what the server must never leave an MP4 as."""
    with open(path, "rb") as f:
        off = 0
        for _ in range(64):
            f.seek(off)
            h = f.read(16)
            if len(h) < 8:
                return False
            size, kind = struct.unpack(">I4s", h[:8])
            if kind == b"moof":
                return True
            if size == 1:
                size = struct.unpack(">Q", h[8:16])[0]
            if size < 8:
                return False
            off += size
    return False


def fixtures(d):
    """Four seconds of tone (and test card), in the shapes recorders produce."""
    sine = ["-f", "lavfi", "-i", "sine=frequency=440:duration=4"]
    card = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=4"]
    # empty_moov: the movie header says 0s and every sample is in a fragment,
    # exactly as an iPhone's MediaRecorder writes it
    frag = ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]
    f = {}
    f["frag_a"] = d / "iphone.m4a"
    ffmpeg(*sine, "-c:a", "aac", *frag, "-f", "mp4", str(f["frag_a"]))
    f["frag_v"] = d / "iphone.mp4"
    ffmpeg(*card, *sine, "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-shortest", *frag, "-f", "mp4", str(f["frag_v"]))
    f["flat_v"] = d / "flat.mp4"
    ffmpeg(*card, *sine, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           "-movflags", "+faststart", str(f["flat_v"]))
    f["webm_a"] = d / "chrome.webm"
    ffmpeg(*sine, "-c:a", "libopus", str(f["webm_a"]))
    f["webm_v"] = d / "chrome-video.webm"
    ffmpeg(*card, *sine, "-c:v", "libvpx", "-g", "15", "-c:a", "libopus", "-shortest",
           str(f["webm_v"]))
    f["png"] = d / "pic.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:size=8x8", "-frames:v", "1", str(f["png"]))
    return f


# -------------------------------------------------------- 2. the server alone

def server_checks(srv, f):
    st, ent = srv.json("POST", "/entries", json.dumps(
        {"kind": "rec_test", "title": "Recording test", "content": "- a line\n"}),
        {"Content-Type": "application/json"})
    eid = ent["id"] if st in (200, 201) and isinstance(ent, dict) else 0
    check(eid > 0, "an entry to attach to: %r" % (ent,))

    def upload(fix, mime, name, cut=None):
        q = f"?name={name}" + (f"&cut={cut}" if cut else "")
        st, row = srv.json("POST", f"/entries/{eid}/media{q}", f[fix].read_bytes(),
                           {"Content-Type": mime})
        return st, row

    def stored(row, label, suffix, mime, dur, streams, tol=0.35):
        if not isinstance(row, dict) or "path" not in row:
            check(False, f"{label}: stored ({row!r})")
            return None
        path = srv.root / row["path"]
        p = probe(path) if path.exists() else {"duration": 0, "streams": [], "fragmented": None}
        check(row["path"].endswith(suffix) and row["mime"] == mime,
              f"{label}: stored as …{suffix} ({row['mime']}): {row['path']}")
        check(path.exists() and row["bytes"] == path.stat().st_size,
              f"{label}: the row's bytes are the file's")
        check(p["fragmented"] is False, f"{label}: one ordinary file, not fragmented")
        check(abs(p["duration"] - dur) <= tol,
              f"{label}: lasts {p['duration']:.2f}s, want {dur}s")
        check(sorted(p["streams"]) == sorted(streams),
              f"{label}: streams {p['streams']}, want {streams}")
        return row

    print("-- uploads: what each recorder's file becomes --")
    st, row = upload("frag_a", "audio/mp4", "dictation.m4a")
    check(st == 201, "an iPhone's fragmented M4A is taken: %d" % st)
    stored(row, "iPhone audio", "-remux.m4a", "audio/mp4", 4.0, ["aac"])
    st, row = upload("frag_v", "video/mp4", "video-dictation.mp4")
    stored(row, "iPhone video", "-remux.mp4", "video/mp4", 4.0, ["h264", "aac"])
    st, row = upload("frag_a", "audio/mp4", "dictation.m4a", cut=2500)
    stored(row, "iPhone audio, cut", "-cut.m4a", "audio/mp4", 2.5, ["aac"])
    st, row = upload("webm_a", "audio/webm", "dictation.webm")
    stored(row, "Chrome's WebM audio", ".m4a", "audio/mp4", 4.0, ["aac"])
    check(not row["path"].endswith("-remux.m4a"), "  and named for its new extension, not -remux")
    st, row = upload("webm_a", "audio/webm", "dictation.webm", cut=2000)
    stored(row, "Chrome's WebM audio, cut", ".m4a", "audio/mp4", 2.0, ["aac"])
    st, row = upload("webm_v", "video/webm", "video-dictation.webm")
    stored(row, "Chrome's WebM video", "-remux.webm", "video/webm", 4.0, ["vp8", "opus"])
    # a stream copy cuts at a keyframe (every half second here)
    st, row = upload("webm_v", "video/webm", "video-dictation.webm", cut=1500)
    stored(row, "Chrome's WebM video, cut", "-cut.webm", "video/webm", 1.5, ["vp8", "opus"],
           tol=0.6)
    st, row = upload("flat_v", "video/mp4", "clip.mp4")
    flat = stored(row, "an ordinary MP4", ".mp4", "video/mp4", 4.0, ["h264", "aac"])
    check(flat and not re.search(r"-(remux|cut)\.mp4$", flat["path"]),
          "  is stored as it came")
    if flat:
        check(f["flat_v"].read_bytes() == (srv.root / flat["path"]).read_bytes(),
              "  byte for byte")
    st, row = upload("png", "image/png", "pic.png", cut=1000)
    check(st == 400, "a cut on a picture is refused: %d" % st)
    st, row = upload("png", "image/png", "pic.png")
    check(st == 201 and row["path"].endswith(".png"), "and the picture itself is stored")

    print("-- a tape: streamed in slices while it records, attached at the stop --")
    tape = f["frag_v"].read_bytes()
    a, b = len(tape) // 3, 2 * len(tape) // 3
    tok = secrets.token_hex(16)
    st, r = srv.json("POST", f"/tapes/{tok}?off=0", tape[:a])
    check(st == 200 and r == {"size": a}, "the first slice is staged: %d %r" % (st, r))
    st, r = srv.json("POST", f"/tapes/{tok}?off={b}", tape[b:])
    check(st == 409 and isinstance(r, dict) and r.get("size") == a,
          "a slice past a gap is a 409 that says what is held: %d %r" % (st, r))
    st, r = srv.json("POST", f"/tapes/{tok}?off={a}", tape[a:b])
    st, r = srv.json("POST", f"/tapes/{tok}?off={a}", tape[a:b])
    check(st == 200 and r == {"size": b}, "a slice sent twice overwrites itself: %r" % (r,))
    st, r = srv.json("POST", f"/tapes/{tok}?off={b}", tape[b:])
    check(st == 200 and r == {"size": len(tape)}, "the last slice completes it")
    staged = srv.root / "media" / ".tapes" / tok
    check(staged.exists() and staged.read_bytes() == tape, "the staged file is the recording")
    st, row = srv.json("POST", f"/entries/{eid}/media?tape={tok}&name=video-dictation.mp4"
                       "&cut=2500", b"", {"Content-Type": "video/mp4"})
    check(st == 201, "the body-less attach stores it: %d" % st)
    stored(row, "the attached tape, cut", "-cut.mp4", "video/mp4", 2.5, ["h264", "aac"],
           tol=0.6)
    check(not staged.exists(), "and nothing is left in .tapes")
    st, _ = srv.json("POST", f"/entries/{eid}/media?tape={tok}&name=x.mp4", b"",
                     {"Content-Type": "video/mp4"})
    check(st == 404, "a second attach of the same tape finds nothing: %d" % st)
    st, _ = srv.json("POST", "/tapes/NOT-HEX?off=0", b"x")
    check(st == 404, "a token that is not hex is not a tape: %d" % st)

    print("-- GET /media/: the files, as a <video> asks for them --")
    rel = row["path"] if isinstance(row, dict) and "path" in row else ""
    disk = (srv.root / rel).read_bytes() if rel else b""
    st, h, body = srv.req("GET", "/" + rel, auth=False)
    check(st == 200 and body == disk, "loopback (tailscale serve) needs no password: %d" % st)
    check(h.get("content-type") == "video/mp4" and h.get("accept-ranges") == "bytes",
          "typed by extension, ranges offered: %r" % h.get("content-type"))
    check("cache-control" not in h, "no Cache-Control (iOS mishandles cached partial media)")
    for _ in range(50):
        if (srv.cache / rel).exists():
            break
        time.sleep(0.1)
    check((srv.cache / rel).exists() and (srv.cache / rel).read_bytes() == disk,
          "an upload is copied into the disk cache")
    st, h, body = srv.req("GET", "/" + rel, auth=False, headers={"Range": "bytes=100-199"})
    check(st == 206 and body == disk[100:200] and
          h.get("content-range") == f"bytes 100-199/{len(disk)}",
          "a range is a 206 with exactly those bytes")
    check(h.get("x-lcars-media") == "cache", "served from the cache: %r" % h.get("x-lcars-media"))
    st, h, body = srv.req("GET", "/" + rel, auth=False, headers={"Range": "bytes=-64"})
    check(st == 206 and body == disk[-64:], "a suffix range is the file's end")
    st, h, body = srv.req("GET", "/" + rel, auth=False,
                          headers={"Range": f"bytes={len(disk)}-"})
    check(st == 416 and h.get("content-range") == f"bytes */{len(disk)}",
          "a range past the end is a 416: %d" % st)
    st, h, body = srv.req("HEAD", "/" + rel, auth=False)
    check(st == 200 and body == b"" and h.get("content-length") == str(len(disk)),
          "HEAD answers the length and sends no body")
    # a file only the NAS holds: served from there, then copied in
    nas_only = srv.root / "media" / "2020" / "01" / "01" / "old.m4a"
    nas_only.parent.mkdir(parents=True)
    shutil.copy(f["frag_a"], nas_only)
    st, h, _ = srv.req("GET", "/media/2020/01/01/old.m4a", auth=False)
    check(st == 200 and h.get("x-lcars-media") == "nas", "a file not yet cached comes from the NAS")
    for _ in range(50):
        if (srv.cache / "media/2020/01/01/old.m4a").exists():
            break
        time.sleep(0.1)
    st, h, _ = srv.req("GET", "/media/2020/01/01/old.m4a", auth=False)
    check(h.get("x-lcars-media") == "cache", "and from the cache the next time")
    for bad in ("/media/../lcars.db", "/media/2026/", "/media/.tapes/" + tok, "/media/x/../../a"):
        st, _, _ = srv.req("GET", bad, auth=False)
        check(st in (401, 404), f"{bad} is refused: {st}")
    st, _, _ = srv.req("GET", "/media/2026/01/01/nothing.mp4", auth=False)
    check(st == 404, "a file that is not there is a 404")
    # the API's port is public: from anywhere but loopback, the password
    other = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))         # no packet is sent
            other = s.getsockname()[0]
    except OSError:
        pass
    if other and not other.startswith("127."):
        st, _, _ = srv.req("GET", "/" + rel, auth=False, host=other)
        check(st == 401, f"from {other} (not loopback) it wants the password: {st}")
        st, _, body = srv.req("GET", "/" + rel, auth=True, host=other)
        check(st == 200 and body == disk, "and serves with it")
    else:
        print("  skip  no non-loopback address to test the password from")
    return eid


# ------------------------------------------------------ 3. the page, recording

FAKE_REC = """
class FakeRec {
  constructor() { window.__rec = this; this.started = false; this.results = []; }
  start() { this.started = true; setTimeout(() => this.onstart && this.onstart({}), 0); }
  stop() { this.started = false; setTimeout(() => this.onend && this.onend({}), 0); }
  abort() { this.stop(); }
}
window.SpeechRecognition = FakeRec;
window.webkitSpeechRecognition = FakeRec;
// Numbered as a continuous session numbers them: an interim result is
// replaced by what follows it, and a final one keeps its index for good.
// (Always 0, as this used to say, dated every order by the session's first
// "computer", and the stop cut the dictation tape back to nothing.)
window.__say = (text, final) => {
  const rs = window.__rec.results;
  if (rs.length && !rs[rs.length - 1].isFinal) rs.pop();
  const r = [{ transcript: text }];
  r.isFinal = !!final;
  rs.push(r);
  window.__rec.onresult({ resultIndex: rs.length - 1, results: rs.slice() });
};
"""


class Static(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI), **kw)

    def log_message(self, *a):
        pass


def page_checks(srv, eid):
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Static) as ui:
        threading.Thread(target=ui.serve_forever, daemon=True).start()
        origin = "http://127.0.0.1:%d" % ui.server_address[1]
        cfg = json.dumps({"base": srv.base, "user": USER, "pass": PASS})
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            ctx.add_init_script(FAKE_REC + "localStorage.setItem('lcars.cfg', %s);"
                                % json.dumps(cfg))
            page = ctx.new_page()
            page.on("pageerror", lambda e: fails.append("page error: " + str(e)))
            if os.environ.get("LCARS_TEST_CONSOLE"):
                page.on("console", lambda m: print("  console:", m.text))
            sent = []
            page.on("request", lambda r: sent.append((r.method, r.url))
                    if "/tapes/" in r.url or "/media?" in r.url else None)
            if os.environ.get("LCARS_TEST_CONSOLE"):
                t0 = time.time()
                page.on("request", lambda r: print("  %6.2fs %s %s" % (time.time() - t0, r.method, r.url[-70:]))
                        if "/tapes/" in r.url or "/media?" in r.url else None)
                page.on("response", lambda r: print("  %6.2fs   <- %d %s" % (time.time() - t0, r.status, r.url[-50:]))
                        if "/tapes/" in r.url or "/media?" in r.url else None)
            page.goto(origin + "/index.html")
            page.wait_for_selector(f'.item[data-id="{eid}"]', timeout=15000)

            def until(js, arg=None, ms=8000):
                """Wait for `js` (given `arg`) to hold; whether it did. What a
                check reads after an async step is waited for, not slept on:
                on a busy box a fixed sleep is a race the page can lose."""
                try:
                    page.wait_for_function(js, arg=arg, timeout=ms, polling=100)
                    return True
                except Exception:
                    return False

            def dictate(label, start, mark, ext_re):
                """Open the entry's editor, dictate for a few seconds, stop by voice."""
                print(f"-- {label}, in a real browser against the real server --")
                page.click(f'.item[data-id="{eid}"]')
                page.wait_for_timeout(300)
                page.keyboard.press("e")
                page.wait_for_timeout(200)
                page.click("#content")
                page.keyboard.press("Control+End")
                del sent[:]
                start()
                until("() => !!vx.tape")
                check(page.evaluate("() => !!vx.tape"), "the tape is rolling")
                page.wait_for_timeout(3500)             # a few one-second slices
                page.evaluate("() => window.__say('the warp core is stable period', true)")
                slices = lambda: [u for m, u in sent if m == "POST" and "/tapes/" in u]
                for _ in range(100):                    # up to 5s more, on a busy box
                    if len(slices()) >= 2:
                        break
                    page.wait_for_timeout(50)
                slices = slices()
                check(len(slices) >= 2, "slices go to the server while it records: %d" % len(slices))
                page.evaluate("() => window.__say('computer pause dictation', true)")
                if os.environ.get("LCARS_TEST_CONSOLE"):
                    print("  %6.2fs said: computer pause dictation" % (time.time() - t0))
                try:
                    # this recording's own link: the entry may hold an older one
                    page.wait_for_function(
                        "m => $('#content').value.includes(m) && "
                        "!/\u00b7 uploading/.test($('#content').value)",
                        arg="[" + mark + " ", timeout=20000)
                except Exception:
                    pass
                val = page.evaluate("() => $('#content').value")
                m = re.search(r"The warp core is stable\.\n\[" + re.escape(mark) +
                              r" \d\d:\d\d\]\((media/[^)]+)\)", val)
                check(m is not None, "the text, then the link to the recording: %r" % val[-120:])
                attach = [u for mth, u in sent if mth == "POST" and "/media?" in u]
                check(len(attach) == 1 and "tape=" in attach[0],
                      "the stop attaches the staged tape rather than uploading it: %r" % attach)
                path = m.group(1) if m else None
                if path:
                    check(re.search(ext_re, path) is not None, f"stored as {path}")
                    info = probe(srv.root / path)
                    check(info["duration"] > 2 and info["fragmented"] is False,
                          "a whole file with a duration: %r" % (info,))
                page.keyboard.press("Control+s")
                page.wait_for_function("() => !document.body.classList.contains('dirty')",
                                       timeout=10000)
                page.evaluate("() => voiceStop && voiceStop()")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                return path, info if path else None

            # audio: Chromium on Linux records WebM/Opus, which becomes AAC. An
            # iPhone's fragmented MP4 cannot be made here; the server half
            # above uploads one.
            path, info = dictate("audio dictation",
                                 lambda: (page.click("#bVoice"), page.wait_for_timeout(300),
                                          page.evaluate("() => window.__say('start dictation', true)")),
                                 "🎙 dictation", r"\.m4a$")
            if path:
                check(info["streams"] == ["aac"], "AAC: %r" % info["streams"])
                page.click(f'.item[data-id="{eid}"]')
                sel = f'.lplay audio[src$="{path.rsplit("/", 1)[1]}"]'
                try:
                    page.wait_for_selector(sel, state="attached", timeout=5000)
                    page.wait_for_function(
                        "s => isFinite(document.querySelector(s).duration)", arg=sel, timeout=10000)
                except Exception:
                    pass
                shown = page.evaluate(
                    "s => { const a = document.querySelector(s); return a ? "
                    "[a.duration, a.closest('.lplay').querySelector('.lp-time').textContent] : null }",
                    sel)
                check(shown is not None and abs(shown[0] - info["duration"]) < 0.5 and
                      re.fullmatch(r"\d+:\d\d", shown[1] or "") is not None,
                      "the reader's player knows its length (no --:--): %r" % (shown,))
                page.evaluate("s => document.querySelector(s).closest('.lplay')"
                              ".querySelector('.lp-btn').click()", sel)
                until("s => document.querySelector(s).currentTime > 0.5", sel)
                t = page.evaluate("s => document.querySelector(s).currentTime", sel)
                check(t > 0.5, "and Play plays it: %.2fs in" % t)
                page.evaluate("s => document.querySelector(s).pause()", sel)
                page.keyboard.press("Escape")

            def video_start():
                page.click("#bVid")
                until("() => !$('#vcam').hidden && !!$('#vcam').srcObject")
                check(page.evaluate("() => !$('#vcam').hidden && !!$('#vcam').srcObject"),
                      "the preview shows what is filmed")

            path, info = dictate("video dictation", video_start, "🎥 video dictation",
                                 r"\.(mp4|webm)$")
            if path:
                check("opus" in info["streams"] or "aac" in info["streams"],
                      "with sound: %r" % info["streams"])
                check(any(s in info["streams"] for s in ("vp8", "vp9", "h264")),
                      "and pictures: %r" % info["streams"])
                check(page.evaluate("() => $('#vcam').hidden"), "the preview is gone after")
                page.click(f'.item[data-id="{eid}"]')
                sel = f'video[src*="{path.rsplit("/", 1)[1]}"]'
                try:
                    page.wait_for_selector(sel, state="attached", timeout=5000)
                    page.wait_for_function(
                        "s => isFinite(document.querySelector(s).duration)", arg=sel, timeout=10000)
                except Exception:
                    pass
                d = page.evaluate("s => { const v = document.querySelector(s); "
                                  "return v ? v.duration : null }", sel)
                check(d is not None and abs(d - info["duration"]) < 0.6,
                      "the reader's video knows its length: %r" % d)
                page.evaluate("s => { const v = document.querySelector(s); v.muted = true; "
                              "return v.play() }", sel)
                until("s => document.querySelector(s).currentTime > 0.3", sel)
                t = page.evaluate("s => document.querySelector(s).currentTime", sel)
                check(t > 0.3, "and it plays: %.2fs in" % t)
            browser.close()


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"recording: needs {tool}")
    # On a real disk, not /tmp: the media cache will not fill a disk with
    # under 2GB free, and /tmp is often a small tmpfs.
    scratch = pathlib.Path(os.environ.get("LCARS_TEST_TMP") or
                           pathlib.Path.home() / ".cache")
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-rec-", dir=scratch))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        build(binary)
    srv = Server(binary, tmp)
    try:
        f = fixtures(tmp)
        eid = server_checks(srv, f)
        if eid:
            page_checks(srv, eid)
    finally:
        srv.stop()
    print("\nrecording: %d checks, %d failures" % (checks[0], len(fails)))
    if fails:
        print("server log and files kept in", tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


main()
