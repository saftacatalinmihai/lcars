#!/usr/bin/env python3
"""Files in a chat, the server's half: POST /chat/media and the attachments
POST /chat, /ask and /engineer/<name>/say take.

    python3 test/chat_media.py     (~40s; LCARS_TEST_BIN=<binary> skips the build)

- POST /chat/media?name=: the file stored byte for byte at
  media/chat/YYYY/MM/<slug>-<id>.<ext> (no .part left), the answer
  {path, url, name, mime, bytes}, the extension rules an entry's upload has
  (a photo by its type, a PDF by its name, HTML and an odd extension as
  .bin), and GET /media/<path> serving it, from the NAS and then the cache;
- the refusals: over the 25 MB cap a 413 before the body is read, no
  Content-Length a 411, an empty body a 400, an unmounted root a 503, and
  Number One's, the crew's and the steward's logins a 403;
- POST /chat and /ask with attachments, claude stood in for by a script that
  keeps its argv and stdin: one "Attached file: <absolute path> (<name>,
  <mime>, <size>)" line per file after the time header and before the
  words, the size the file's own; files alone are a message; the Read tool
  given, allowed on <root>/media/chat/** alone and denied in the working
  directory; a path outside media/chat/, a dot-name, a "..", a missing file,
  a directory and too many files each a 400 with claude never started;
- the server's sockets (the listener, a connection held open) all
  close-on-exec, and claude and engineer.py started holding none;
- POST /engineer/<name>/say with attachments, the script a stub: say
  <name> --json with the message and the checked files (the file's own
  size, a name with no newline in it); without files the plain say as
  before; a bad path a 400.

A scratch server is built from the lcars-release compile line (to a temp
path, never ./lcars) and run on an empty database and temp directories;
nothing here touches lcars.db, the NAS, claude or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import killclean  # noqa: E402 - its scratch goes when the run is killed
from caldav import build, free_port  # noqa: E402

MAIN = ("t", "t")
NO1 = ("no1", "no1-password-0123456789")
CREW = ("crew", "crew-password-0123456789")
STEWARD = ("steward", "steward-password-0123456789")
KEY = "k" * 24
CAP = 25 * 1024 * 1024

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


# claude: keeps what it was given, prints one stream-json line (or, for
# /ask, the result object)
# Both stand-ins also note the sockets they were started holding: none of
# the server's may reach a child (cloexec_checks).
SOCKETS = """
def sockets():
    held = []
    for fd in os.listdir("/proc/self/fd"):
        try:
            if os.readlink("/proc/self/fd/" + fd).startswith("socket:"):
                held.append(int(fd))
        except OSError:
            pass
    return held
"""
CLAUDE = """#!/usr/bin/env python3
import json, os, sys
""" + SOCKETS + """
out = os.environ["STUB_OUT"]
data = sys.stdin.read()
with open(out, "w") as f:
    json.dump({"argv": sys.argv[1:], "stdin": data, "sockets": sockets()}, f)
if "json" in sys.argv and "stream-json" not in sys.argv:
    print(json.dumps({"type": "result", "result": "seen", "session_id": "0a1b2c3d-0000"}))
else:
    print(json.dumps({"type": "assistant", "text": "seen"}))
"""
ENGINEER = """#!/usr/bin/env python3
import json, os, sys
""" + SOCKETS + """
with open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "engineer-sockets.json"), "w") as f:
    json.dump(sockets(), f)
print(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}))
"""


class Server:
    def __init__(self, binary, tmp, root):
        self.port = free_port()
        self.stub_out = tmp / "claude.json"
        claude = tmp / "claude"
        claude.write_text(CLAUDE)
        claude.chmod(0o755)
        eng = tmp / "engineer.py"
        eng.write_text(ENGINEER)
        eng.chmod(0o755)
        (tmp / "home").mkdir()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="1", LCARS_CLAUDE_BIN=str(claude),
                   LCARS_OWNER="Ana", LCARS_VOICE_HINTS='"zana" is Ana',
                   LCARS_CHAT_DIR=str(tmp / "home"), STUB_OUT=str(self.stub_out),
                   LCARS_MEDIA_ROOT=str(root), LCARS_MEDIA_CACHE=str(tmp / "cache"),
                   LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1],
                   LCARS_NO1_USER=NO1[0], LCARS_NO1_PASS=NO1[1],
                   LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
                   LCARS_STEWARD_USER=STEWARD[0], LCARS_STEWARD_PASS=STEWARD[1],
                   LCARS_ENGINEER="1", LCARS_ENGINEER_KEY=KEY, LCARS_ENGINEER_SCRIPT=str(eng))
        for k in ("LCARS_ENGINEER_LOGIN", "LCARS_CHAT_LOCATION"):
            env.pop(k, None)
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("chat_media: the scratch server did not come up; see " + str(tmp / "server.log"))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()
        self.log.close()

    def req(self, method, path, body=None, login=MAIN, ctype="application/json", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Authorization": "Basic " + base64.b64encode(f"{login[0]}:{login[1]}".encode()).decode()}
        if body is not None:
            h["Content-Type"] = ctype
        h.update(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, {k.lower(): v for k, v in r.getheaders()}, json.loads(data)
        except ValueError:
            return r.status, {k.lower(): v for k, v in r.getheaders()}, data

    def raw(self, head):
        """Headers only, the body never sent: what a refusal before the body
        is read answers."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(head.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return int(data.split(b" ", 2)[1]) if data else 0

    def claude_saw(self):
        try:
            d = json.loads(self.stub_out.read_text())
        except (OSError, ValueError):
            return None
        self.stub_out.unlink()
        return d


def upload(s, name, data, ctype="application/octet-stream", login=MAIN):
    q = urllib.request.quote(name)
    return s.req("POST", f"/chat/media?name={q}", data, login=login, ctype=ctype)


def upload_checks(s, root):
    print("-- POST /chat/media: the store and the answer --")
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40
    st, _, a = upload(s, "IMG 2041 (copy).PNG", png, "image/png")
    check(st == 201, "a photo: 201 (%s)" % st)
    p = a.get("path", "")
    parts = p.split("/")
    check(len(parts) == 5 and parts[:2] == ["media", "chat"] and len(parts[2]) == 4 and len(parts[3]) == 2,
          "media/chat/YYYY/MM/<file>: %s" % p)
    check(parts[-1].startswith("img-2041-copy-") and parts[-1].endswith(".png"), "<slug>-<id>.png: %s" % parts[-1])
    check(a.get("url") == "/" + p and a.get("name") == "IMG 2041 (copy).PNG" and a.get("mime") == "image/png"
          and a.get("bytes") == len(png), "the answer: %s" % a)
    f = root / p
    check(f.is_file() and f.read_bytes() == png, "byte for byte on the NAS")
    check(not [x for x in f.parent.iterdir() if x.name.startswith(".")], "no .part left behind")

    st, h, body = s.req("GET", "/" + p)
    check(st == 200 and body == png and h.get("content-type") == "image/png", "GET /media/<path> serves it")
    time.sleep(0.5)  # the cache's copy is made beside the upload's answer
    st, h, body = s.req("GET", "/" + p)
    check(st == 200 and body == png and h.get("x-lcars-media") == "cache", "and from the cache after: %s"
          % h.get("x-lcars-media"))

    st, _, pdf = upload(s, "Plan.pdf", b"%PDF-1.4\n%%EOF\n")
    check(st == 201 and pdf["path"].endswith(".pdf") and pdf["mime"] == "application/pdf",
          "a PDF by its name: %s %s" % (pdf.get("path"), pdf.get("mime")))
    st, _, html = upload(s, "page.html", b"<script>alert(1)</script>", "text/html")
    check(st == 201 and html["path"].endswith(".bin") and html["mime"] == "application/octet-stream",
          "HTML is stored as .bin, a download: %s" % html.get("path"))
    st, _, blob = upload(s, "", b"hello", "text/plain")
    check(st == 201 and "/file-" in blob["path"] and blob["name"] == blob["path"].rsplit("/", 1)[1],
          "no name: slug 'file', the stored name answered: %s" % blob)
    st, _, txt = upload(s, "notes.txt", b"line one\nline two\n", "text/plain")
    check(st == 201 and txt["path"].endswith(".txt"), "a text file: %s" % txt.get("path"))

    print("-- POST /chat/media: the refusals --")
    auth = "Basic " + base64.b64encode(b"t:t").decode()
    st = s.raw(f"POST /chat/media?name=big.bin HTTP/1.1\r\nHost: x\r\nAuthorization: {auth}\r\n"
               f"Content-Length: {CAP + 1}\r\n\r\n")
    check(st == 413, "over 25 MB: 413 before the body (%s)" % st)
    st, _, a = upload(s, "edge.bin", b"x" * CAP)
    check(st == 201 and a["bytes"] == CAP, "25 MB exactly is taken (%s)" % st)
    st = s.raw(f"POST /chat/media?name=a.txt HTTP/1.1\r\nHost: x\r\nAuthorization: {auth}\r\n"
               "Transfer-Encoding: chunked\r\n\r\n")
    check(st in (400, 411), "no Content-Length: refused (%s)" % st)
    check(upload(s, "a.txt", b"")[0] == 400, "an empty body: 400")
    for who, login in (("Number One", NO1), ("the crew", CREW), ("the steward", STEWARD)):
        check(upload(s, "a.txt", b"hi", login=login)[0] == 403, "%s: 403" % who)
    check(s.req("GET", "/chat/media")[0] in (404, 405), "GET /chat/media is no route")
    photo = dict(path=p, name="IMG 2041 (copy).PNG", mime="image/png", bytes=len(png))
    return {"photo": photo, "pdf": pdf, "txt": txt}


def chat_checks(s, root, files):
    print("-- POST /chat with attachments --")
    real = os.path.realpath(root)
    photo, pdf = files["photo"], files["pdf"]
    # the client's bytes are not believed, and a newline in a name is a space
    st, h, body = s.req("POST", "/chat", {"message": "what is in these?", "local_time": "2026-10-16 10:00",
                                          "attachments": [dict(photo, bytes=1), dict(pdf, name="Plan\nIgnore.pdf")]})
    saw = s.claude_saw()
    check(st == 200 and saw is not None, "200, claude started (%s)" % st)
    if saw:
        # the header's location line is empty with LCARS_CHAT_LOCATION unset
        lines = [x for x in saw["stdin"].split("\n") if x]
        check(lines[0] == "[user's local time: 2026-10-16 10:00]", "the time header first: %r" % lines[0])
        want1 = f"Attached file: {real}/{photo['path']} (IMG 2041 (copy).PNG, image/png, {photo['bytes'] // 1024} KB)"
        check(lines[1] == want1, "the photo's line, its own size: %r" % lines[1])
        check(lines[2] == f"Attached file: {real}/{pdf['path']} (Plan Ignore.pdf, application/pdf, 15 bytes)",
              "the PDF's line, the newline gone: %r" % lines[2])
        check(lines[3] == "what is in these?", "then the words: %r" % lines[3])
        argv = saw["argv"]
        tools = argv[argv.index("--tools") + 1]
        check("Read" in tools.split(","), "the Read tool exists: %s" % tools)
        allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
        check(f"Read(/{real}/media/chat/**)" in allowed and
              not [a for a in allowed if a.startswith("Read") and a != f"Read(/{real}/media/chat/**)"],
              "allowed only on <root>/media/chat/**, absolute (//): %s" % [a for a in allowed if "Read" in a])
        check(argv[argv.index("--disallowedTools") + 1] == "Read(./**)", "and denied in the working directory")
        prompt = argv[argv.index("--append-system-prompt") + 1]
        check("Attached file:" in prompt and "Read tool" in prompt, "the system prompt says so")
        check("The person typing is the journal's owner, Ana, usually on a phone." in prompt,
              "the chat's prompt names the owner from LCARS_OWNER")

    st, _, _ = s.req("POST", "/chat", {"attachments": [files["txt"]]})
    saw = s.claude_saw()
    check(st == 200 and saw and saw["stdin"].endswith(f"{files['txt']['path']} (notes.txt, text/plain, 18 bytes)\n"),
          "files alone are a message")
    st, _, _ = s.req("POST", "/chat", {"message": "plain", "attachments": []})
    saw = s.claude_saw()
    check(st == 200 and saw and "Attached file" not in saw["stdin"], "[] is no files")
    check(s.req("POST", "/chat", {"message": ""})[0] == 400, "neither words nor files: 400")
    check(s.claude_saw() is None, "and claude not started")

    print("-- POST /chat: the path check --")
    (root / "media" / "elsewhere.txt").write_text("not a chat's")
    (root / "media" / "chat" / "adir").mkdir()
    d = files["txt"]["path"].rsplit("/", 1)[0]
    (root / d / ".hidden.txt").write_text("x")
    bad = [("media/elsewhere.txt", "outside media/chat/"), ("media/reports/x.html", "a report"),
           ("media/chat/../elsewhere.txt", "a .."), (f"{d}/.hidden.txt", "a dot-name"),
           ("/" + files["txt"]["path"], "a leading /"), (f"{real}/{files['txt']['path']}", "an absolute path"),
           (f"{d}/missing.txt", "a missing file"), ("media/chat/adir", "a directory"), ("", "no path"),
           ("media/chat/a b.txt", "a space")]
    for path, why in bad:
        st, _, j = s.req("POST", "/chat", {"message": "x", "attachments": [{"path": path, "name": "x"}]})
        check(st == 400 and s.claude_saw() is None, "%s: 400, claude not started (%s %s)"
              % (why, st, j.get("error", "") if isinstance(j, dict) else ""))
    for body, why in (({"message": "x", "attachments": "media/chat/x"}, "not a list"),
                      ({"message": "x", "attachments": [files["txt"]] * 21}, "21 files"),
                      ({"message": "x", "attachments": ["media/chat/x"]}, "a bare string item")):
        check(s.req("POST", "/chat", body)[0] == 400 and s.claude_saw() is None, "%s: 400" % why)
    st, _, _ = s.req("POST", "/chat", {"message": "x", "attachments": [files["txt"]] * 20})
    check(st == 200 and s.claude_saw()["stdin"].count("Attached file:") == 20, "20 files are taken")

    print("-- POST /ask --")
    st, _, j = s.req("POST", "/ask", {"message": "read it", "attachments": [files["txt"]]})
    saw = s.claude_saw()
    check(st == 200 and saw and f"Attached file: {real}/{files['txt']['path']}" in saw["stdin"]
          and "Read tool" in saw["argv"][saw["argv"].index("--append-system-prompt") + 1],
          "the voice route puts the lines in and says so too")
    vp = saw["argv"][saw["argv"].index("--append-system-prompt") + 1]
    check(vp.startswith("You are the voice of the LCARS journal: Ana talks to you through an iOS Shortcut")
          and 'Speech recognition is noisy ("zana" is Ana). Interpret it' in vp,
          "the voice prompt: the owner from LCARS_OWNER, the hints from LCARS_VOICE_HINTS")
    check(s.req("POST", "/ask", {"message": "x", "attachments": [{"path": "media/x.txt"}]})[0] == 400,
          "and checks the path")
    st, _, j = s.req("POST", "/chat", {"message": "x", "attachments": [files["txt"]]}, login=NO1)
    check(st == 200 and s.claude_saw() is not None, "a limited login may still send a chat file it was given")


def engineer_checks(s, files):
    print("-- POST /engineer/<name>/say with attachments --")
    h = {"X-LCARS-Engineer-Key": KEY}
    st, _, j = s.req("POST", "/engineer/ada/say", {"message": "look", "attachments": [dict(files["pdf"], bytes=7)]},
                     headers=h)
    check(st == 200 and j.get("argv") == ["say", "ada", "--json"], "say <name> --json: %s" % j)
    if st == 200:
        sent = json.loads(j["stdin"])
        check(sent == {"message": "look", "attachments": [{"path": files["pdf"]["path"], "name": "Plan.pdf",
                                                            "mime": "application/pdf", "bytes": 15}]},
              "the message and the checked files: %s" % sent)
    st, _, j = s.req("POST", "/engineer/ada/say", {"attachments": [files["txt"]]}, headers=h)
    check(st == 200 and json.loads(j["stdin"])["message"] == "", "files alone")
    st, _, j = s.req("POST", "/engineer/ada/say", {"message": "plain"}, headers=h)
    check(st == 200 and j == {"argv": ["say", "ada"], "stdin": "plain"}, "no files: the plain say as before")
    st, _, _ = s.req("POST", "/engineer/ada/say", {"message": "x", "attachments": [{"path": "media/x"}]}, headers=h)
    check(st == 400, "a path outside media/chat/: 400")
    check(s.req("POST", "/engineer/ada/say", {"message": ""}, headers=h)[0] == 400, "nothing at all: 400")


def cloexec_checks(s, tmp):
    """The listener and every accepted connection are close-on-exec
    (RunHTTPServer: SOCK_CLOEXEC, accept4), so no child holds one - on
    musl, which has no addclosefrom to fall back on, as on glibc. Asked of
    the server's own fds (/proc/<pid>/fdinfo's flags), with a second
    connection held open while each child starts."""
    print("-- the server's sockets stay out of its children --")
    held = socket.create_connection(("127.0.0.1", s.port), timeout=10)
    held.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n")  # unfinished: the thread waits
    time.sleep(0.2)
    pid = s.proc.pid
    socks, bad = 0, []
    for fd in os.listdir(f"/proc/{pid}/fd"):
        if int(fd) <= 2:
            continue  # stdin/out/err are the test's, inherited
        try:
            if not os.readlink(f"/proc/{pid}/fd/{fd}").startswith("socket:"):
                continue
            flags = next(l for l in open(f"/proc/{pid}/fdinfo/{fd}") if l.startswith("flags:"))
        except (OSError, StopIteration):
            continue
        socks += 1
        if not int(flags.split()[1], 8) & 0o2000000:  # O_CLOEXEC
            bad.append(fd)
    check(socks >= 2 and not bad, f"the server's {socks} sockets (the listener, the held "
                                  f"connection) all O_CLOEXEC: not {bad}")
    st, _, _ = s.req("POST", "/chat", {"message": "hold on", "local_time": "2026-10-16 10:00"})
    saw = s.claude_saw()
    check(st == 200 and saw is not None and saw.get("sockets") == [],
          f"claude started holding no socket: {saw and saw.get('sockets')}")
    st, _, _ = s.req("POST", "/engineer/ada/say", {"message": "hold on"},
                     headers={"X-LCARS-Engineer-Key": KEY})
    try:
        eng = json.loads((tmp / "engineer-sockets.json").read_text())
    except (OSError, ValueError):
        eng = None
    check(st == 200 and eng == [], f"engineer.py started holding no socket: {eng}")
    held.close()


def unmounted_checks(binary, tmp):
    print("-- an unmounted root --")
    root = tmp / "nas2"
    root.mkdir()
    s = Server(binary, tmp / "s2", root)
    try:
        check(upload(s, "a.txt", b"hi")[0] == 503, "503 when <root>/media is missing")
        check(not any(root.iterdir()), "and nothing written")
    finally:
        s.stop()


def png(w, h):
    """A real picture, w x h, an orange-to-blue ramp (zlib, no PIL)."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(c for x in range(w) for c in (255 - x * 255 // w, 120, x * 255 // w)) for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def page_checks(s, root, tmp):
    """The page's half in Chromium against the scratch server: files picked
    through the chat's + (its file input), uploaded with progress, sent with
    no words, stored under media/chat/, shown in the bubble from GET
    /media/, and the lightbox on the stored file."""
    import http.server
    import socketserver
    import threading
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("-- the page in Chromium: skipped, playwright is not installed --")
        return
    print("-- the page in Chromium: +, the upload, the bubble, the lightbox --")
    ui = pathlib.Path(__file__).resolve().parent.parent

    class Static(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ui), **kw)

        def log_message(self, *a):
            pass

    pic = tmp / "Shot 7.png"
    pic.write_bytes(png(96, 48))
    big = tmp / "dump.bin"
    big.write_bytes(os.urandom(6 * 1024 * 1024))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Static) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        origin = "http://127.0.0.1:%d" % srv.server_address[1]
        cfg = json.dumps({"base": f"http://127.0.0.1:{s.port}", "user": MAIN[0], "pass": MAIN[1]})
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            ctx.add_init_script("localStorage.setItem('lcars.cfg', %s);" % json.dumps(cfg))
            page = ctx.new_page()
            page.on("pageerror", lambda e: fails.append("page error: " + str(e)))
            page.goto(origin + "/index.html")
            page.wait_for_function("() => typeof openChat === 'function' && st.all.length >= 0", timeout=15000)
            page.wait_for_timeout(800)
            # every progress event the uploads hear, and the files' states
            page.evaluate("""() => {
              window.__prog = [];
              const real = chatMediaSend;
              chatMediaSend = (blob, name, onprog) => real(blob, name, pct => { window.__prog.push([name, pct]); onprog(pct); });
              openChat();
            }""")
            page.wait_for_selector(".chth .chplus:not([hidden])", timeout=5000)
            check(page.is_visible(".chth .chplus"), "+ beside the box in the full view")
            page.set_input_files(".chth .chpick", [str(pic), str(big)])

            def until(js, ms=15000):
                try:
                    page.wait_for_function(js, timeout=ms, polling=100)
                    return True
                except Exception:
                    return False
            check(until("() => document.querySelectorAll('.chth .chfchip').length === 2", 3000), "a chip per picked file")
            check(until("() => chatShown().att.every(f => f.state === 'done')"), "both uploaded")
            prog = page.evaluate("window.__prog")
            check(any(n == "dump.bin" for n, _ in prog), "progress events heard for the large one (%d)" % len(prog))
            check(any(n == "dump.bin" and pct >= 99.9 for n, pct in prog), "up to 100%")
            att = page.evaluate("chatShown().att.map(f => ({path: f.path, name: f.name, mime: f.mime, bytes: f.bytes}))")
            for a in att:
                f = root / a["path"]
                check(a["path"].startswith("media/chat/") and f.is_file(), "stored under media/chat/: %s" % a["path"])
            if len(att) == 2:
                check((root / att[0]["path"]).read_bytes() == pic.read_bytes(), "the picture byte for byte")
                check(att[0]["mime"] == "image/png" and att[1]["bytes"] == 6 * 1024 * 1024, "type and size as the server answered")
            page.click(".chth .chsend")
            check(until("() => { const u = chatShown().msgs.find(m => m.files); return u && u.state === ''; }"),
                  "sent with no words, and delivered")
            saw = s.claude_saw()
            check(saw is not None and "Attached file:" in saw["stdin"] and "Shot 7.png" in saw["stdin"],
                  "the computer got the files' lines")
            check(until("() => { const i = document.querySelector('.chth .chimgs img'); return i && i.complete && i.naturalWidth === 96; }"),
                  "the bubble's picture loaded from GET /media/ at its own size")
            r = page.evaluate("getComputedStyle(document.querySelector('.chth .chimgs .chimg')).aspectRatio")
            check("2" in r, "its box at the picture's aspect (2:1): %s" % r)
            check(page.is_visible(".chth .chftile a[download]"), "the other file a tile with download")
            page.click(".chth .chimgs .chimg")
            check(until("() => { const i = document.querySelector('#mlight img'); return i && i.complete && i.naturalWidth === 96; }", 5000),
                  "a tap: the lightbox, on the stored file")
            page.keyboard.press("Escape")
            check(until("() => !document.querySelector('#mlight')", 3000), "Esc closes it")
            browser.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp("lcars-media-chat-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = str(tmp / "lcars")
        build(binary)
    root = tmp / "nas"
    (root / "media").mkdir(parents=True)
    (tmp / "s1").mkdir()
    s = Server(binary, tmp / "s1", root)
    try:
        files = upload_checks(s, root)
        chat_checks(s, root, files)
        engineer_checks(s, files)
        cloexec_checks(s, tmp / "s1")
        page_checks(s, root, tmp)
    finally:
        s.stop()
    (tmp / "s2").mkdir()
    unmounted_checks(binary, tmp)
    print(f"\n{checks[0] - len(fails)}/{checks[0]} checks passed")
    if fails:
        print("kept for a look:", tmp)
        sys.exit(1)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
