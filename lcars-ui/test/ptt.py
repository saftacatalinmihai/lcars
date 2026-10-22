#!/usr/bin/env python3
"""The chats' hold-to-talk (the console's, and so the deck's talk sheet's),
in headless Chromium with a fake microphone.

This runs index.html's "hold to talk" block - cut verbatim from the page
between its markers - in a bare page with a stand-in talk form and
stand-ins for what it calls (talkHost, sayStop, sayFetch's server), so
neither the console nor the deck has to boot. The browser side is real:
getUserMedia on Chromium's fake device, the AudioWorklet, WebSocket.

  1. holding the pill: a token from /say/token, one socket to Deepgram's
     /v1/listen with it as a bearer (nova-3, linear16, interim results),
     audio flowing, the interim words live in the box and the pill lit;
     letting go sends CloseStream and the final words go through talkSend;
  2. Space held in an empty box does the same; with words in the box it is
     a space;
  3. a reply being spoken is stopped by the press (sayStop); a press that
     stopped one and sent nothing (a tap) is a fumble (talkHost.fumble,
     the hush lifted), one that sends words is not;
  4. a new press while the last is finishing: never two sockets at once;
  4b. let go while an iPhone's slow AudioContext.resume() is still waking:
     no "null is not an object" toast, nothing sent, the pill at rest; and
     a conversation ended in the same wait the same;
  5. no key on the server (503), a refused microphone, a refused socket:
     a toast, nothing sent, the box still takes typing;
  6. conversation mode: one socket held open (vad_events, endpointing,
     utterance_end_ms), an utterance sent by itself on UtteranceEnd, noise
     of one word not sent, an engineer's with the answer-first note;
     barge-in - words while a reply plays stop it, SpeechStarted alone or
     "um" do not (an echo or the room would hush the rest of a turn) - and
     the mute mode, which sends no audio while one plays (KeepAlive
     instead); a dropped socket reopened with a fresh token; End, the page
     hidden and a failure each close the socket and the microphone.

Deepgram itself is stood in for by Playwright's WebSocket routing. With
--real (or LCARS_PTT_REAL=1) it is not: /say/token answers with
DEEPGRAM_API_KEY (from the environment or ../.env) - a long-lived key, sent
as a token rather than a bearer, since a key without a Member role cannot
mint short-lived ones - and the check is that the real socket opens, takes
the audio and closes cleanly on CloseStream. The key goes only to the page
on 127.0.0.1 and is never printed.

    python3 test/ptt.py [--real]
"""
import http.server
import json
import os
import pathlib
import re
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
PAGE_SRC = (HERE.parent / "index.html").read_text()
REAL = "--real" in sys.argv or os.environ.get("LCARS_PTT_REAL") == "1"

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def block():
    m = re.search(r"/\* =+ hold to talk =+.*?/\* =+ end hold to talk =+ \*/", PAGE_SRC, re.S)
    if not m:
        sys.exit("ptt: the hold-to-talk markers are not in index.html")
    return m.group(0)


# the pills and the box, as a thread's pane has them (chatPaneHtml)
FORM = ('<form id="talkform"><button id="talkptt" type="button"><span id="pttl">Hold to talk</span></button>'
        '<button id="talkconv" type="button"><span id="convl">Start conversation</span><small id="convst"></small></button>'
        '<button id="talkout" type="button" hidden>Speaker</button>'
        '<input id="talkq" autocomplete="off" placeholder="say something"><button id="talksend">Say</button></form>')


PAGE = """<!doctype html><meta charset=utf-8><body>
<div id="talk" class="sheet">%s</div><div id="toast" class="hidden"></div>
<style>.hidden{display:none}</style>
<script>
// what the block calls, stood in for
const $ = s => document.querySelector(s);
const DEMO = false;
const cfg = { base: "", user: "", pass: "" };
const eng = { name: "" }, talk = { busy: false, ac: null };
const lsGet = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; } catch (e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
// the speech queue: say.run.shown is "playing" while a reply is said
const say = { run: null };
window.sent = []; window.notes = []; window.stops = 0; window.tokens = 0;
window.sockets = { made: 0, open: 0, max: 0, protos: [], urls: [], codes: [] };
function sayStop() { window.stops++; say.run = null; }
// the voice orders' device test and settle (index.html), and the speech
// queue's gate after a capture is let go: counted
const V_IOS = false, V_HOLD_SETTLE = 350;
window.quiets = 0;
function sayQuiet(ms) { window.quiets++; }
function talkSend(note) { const q = $("#talkq").value.trim(); if (q) { window.sent.push(q); window.notes.push(note || ""); } $("#talkq").value = ""; }
function sayFetch(method, body, signal, sub = "") { if (sub === "/token") window.tokens++; return fetch("/say" + sub, { method }); }
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.remove("hidden"); }
// the page's side of the block (talkHost in index.html), stood in for
const talkHost = {
  box: () => $("#talkq"), get: () => $("#talkq").value, put: v => { $("#talkq").value = v; },
  hint: t => { $("#talkq").placeholder = t || "say something"; },
  up: () => !$("#talk").classList.contains("hidden"), space: true, hold() {}, toast,
  fumble() { window.fumbles = (window.fumbles || 0) + 1; },
  async clear() {}, send: conv => talkSend(conv && eng.name ? CONV_NOTE : undefined),
};
$("#talkform").addEventListener("submit", ev => { ev.preventDefault(); talkSend(); });
// every socket the page makes, and how many are alive at once
{
  const WS = window.WebSocket;
  window.WebSocket = function (url, protos) {
    const ws = new WS(url, protos), s = window.sockets;
    s.made++; s.urls.push(url); s.protos.push(protos[0]);
    s.open++; s.max = Math.max(s.max, s.open);
    let gone = false;
    const end = ev => { if (!gone) { gone = true; s.open--; s.codes.push(ev.code); } };
    ws.addEventListener("close", end);
    ws.addEventListener("open", () => { s.opened = (s.opened || 0) + 1; });
    const close = ws.close.bind(ws);
    ws.close = (...a) => { end({ code: "client" }); return close(...a); };
    return ws;
  };
  window.WebSocket.prototype = WS.prototype;
  Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
}
</script>
<script>%s
talkWire();</script>
"""


class State:
    token_status = 200
    token_delay = 0
    token = "aaaa.bbbb.cccc"


def serve(page):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/say/token":
                time.sleep(State.token_delay)
                if State.token_status != 200:
                    body = json.dumps({"error": "No listening on this server", "status": State.token_status})
                else:
                    body = json.dumps({"access_token": State.token, "expires_in": 30})
                code = State.token_status
            else:
                body, code = page, 200
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json" if self.path != "/" else "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class FakeDeepgram:
    """Playwright's stand-in for wss://api.deepgram.com/v1/listen."""

    def __init__(self):
        self.audio = 0
        self.closestream = 0
        self.hold = False   # answer CloseStream but keep the socket open

    def __call__(self, ws):
        state = {"interim": False}

        def on(msg):
            if isinstance(msg, bytes):
                self.audio += len(msg)
                if not state["interim"]:
                    state["interim"] = True
                    ws.send(json.dumps({"type": "Results", "is_final": False,
                                        "channel": {"alternatives": [{"transcript": "hello"}]}}))
                return
            if json.loads(msg).get("type") == "CloseStream":
                self.closestream += 1
                ws.send(json.dumps({"type": "Results", "is_final": True,
                                    "channel": {"alternatives": [{"transcript": "Hello, crew."}]}}))
                if not self.hold:
                    ws.close(code=1000)

        ws.on_message(on)


def env_key():
    k = os.environ.get("DEEPGRAM_API_KEY")
    if k:
        return k
    for p in (HERE.parent.parent / ".env", pathlib.Path.home() / "lcars" / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("DEEPGRAM_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


def main():
    from playwright.sync_api import sync_playwright

    srv = serve(PAGE % (FORM, block()))
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(permissions=["microphone"])
        page = ctx.new_page()
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        if REAL:
            real(page, url)
        else:
            fake(page, url)
            conversation(page, url)
        check(not errors, "no script errors" + (": " + "; ".join(errors[:3]) if errors else ""))
        browser.close()
    srv.shutdown()
    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nptt: all passed")


def sockets(page):
    return page.evaluate("window.sockets")


def fake(page, url):
    dg = FakeDeepgram()
    page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), dg)
    page.goto(url)
    pill = page.locator("#talkptt")

    print("hold the pill")
    box = pill.bounding_box()
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    check(page.evaluate("$('#talkptt').classList.contains('on')"), "the pill is lit while held")
    page.wait_for_function("$('#pttl').textContent === 'Listening…'", timeout=8000)
    check(True, "listening once the socket is open")
    page.wait_for_function("$('#talkq').value === 'hello'", timeout=8000)
    check(True, "the interim words are live in the box")
    check(page.evaluate("$('#talkq').placeholder") == "listening…", "the box says listening")
    page.wait_for_timeout(400)
    page.mouse.up()
    page.wait_for_function("window.sent.length === 1", timeout=8000)
    s = sockets(page)
    check(page.evaluate("window.sent[0]") == "Hello, crew.", "the final words went through talkSend")
    check(dg.closestream == 1, "CloseStream on release")
    check(dg.audio > 8000, f"audio went to the socket ({dg.audio} bytes)")
    check(s["made"] == 1 and s["protos"] == ["bearer"], "one socket, the token as a bearer")
    q = dict(re.findall(r"[?&]([^=]+)=([^&]*)", s["urls"][0]))
    check(q.get("model") == "nova-3" and q.get("encoding") == "linear16" and
          q.get("interim_results") == "true" and q.get("smart_format") == "true" and
          q.get("sample_rate", "").isdigit(), "nova-3, linear16, interim results, smart format")
    check(page.evaluate("window.stops") >= 1, "the press stopped a reply being spoken (sayStop)")
    check(not page.evaluate("$('#talkptt').classList.contains('on')") and
          page.evaluate("$('#pttl').textContent") == "Hold to talk", "the pill is back to rest")

    print("a fumble: the voice stopped, nothing sent")
    page.evaluate("window.fumbles = 0; say.run = { shown: 'playing' }")
    pill.click()
    page.wait_for_function("!ptt.cur", timeout=8000)
    check(page.evaluate("window.fumbles") == 1 and page.evaluate("window.sent.length") == 1,
          "a tap stopped the voice and sent nothing: the hush lifted (talkHost.fumble)")
    page.evaluate("say.run = { shown: 'playing' }")
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    page.wait_for_function("$('#talkq').value === 'hello'", timeout=8000)
    page.wait_for_timeout(400)
    page.mouse.up()
    page.wait_for_function("window.sent.length === 2", timeout=8000)
    check(page.evaluate("window.fumbles") == 1, "a press that sent its words: no fumble, the hush stays for them to lift")
    page.evaluate("window.sent.pop(); window.notes.pop()")
    page.evaluate("say.run = null")
    pill.click()
    page.wait_for_function("!ptt.cur", timeout=8000)
    check(page.evaluate("window.fumbles") == 1, "a tap with nothing speaking: nothing to lift")

    print("Space in the box")
    page.focus("#talkq")
    page.keyboard.down(" ")
    page.wait_for_function("$('#talkq').value === 'hello'", timeout=8000)
    check(True, "Space held in an empty box listens")
    page.wait_for_timeout(300)
    page.keyboard.up(" ")
    page.wait_for_function("window.sent.length === 2", timeout=8000)
    check(page.evaluate("window.sent[1]") == "Hello, crew.", "letting go of Space sends")
    # a tap of Space in the empty box is not a press: no key minted, no
    # microphone, nothing typed (QA 2026-10-13 #13)
    made = sockets(page)["made"]
    page.keyboard.press(" ")
    page.wait_for_timeout(500)
    check(sockets(page)["made"] == made and not page.evaluate("ptt.cur") and page.evaluate("$('#talkq').value") == ""
          and not page.evaluate("$('#talkptt').classList.contains('on')"),
          "a tap of Space in the empty box opens nothing")
    page.keyboard.type("go to")
    page.keyboard.press(" ")
    check(page.evaluate("$('#talkq').value") == "go to " and sockets(page)["made"] == made,
          "with words in the box, Space is a space")
    page.fill("#talkq", "")

    print("one socket at a time")
    # the first one still finishing (Deepgram slow to close) when the next
    # press comes: that one is ended, and its words sent, first
    dg.hold = True
    for _ in range(2):
        page.mouse.down()
        page.wait_for_function("$('#pttl').textContent === 'Listening…'", timeout=8000)
        page.wait_for_timeout(300)
        page.mouse.up()
        page.wait_for_timeout(100)
    page.wait_for_function("window.sent.length >= 4", timeout=8000)
    s = sockets(page)
    check(s["max"] == 1, f"never more than one socket open (max {s['max']})")
    dg.hold = False
    page.wait_for_function("window.sockets.open === 0", timeout=8000)

    print("let go before the socket is open")
    State.token_delay = 1.2
    n, heard = len(page.evaluate("window.sent")), dg.audio
    page.mouse.down()
    page.wait_for_timeout(700)
    page.mouse.up()
    check(page.evaluate("$('#pttl').textContent") == "Hearing…", "released: the pill says hearing")
    page.wait_for_function(f"window.sent.length === {n + 1}", timeout=8000)
    check(page.evaluate("window.sent").pop() == "Hello, crew.",
          "released mid-handshake: still sent")
    check(dg.audio - heard > 2 * 48000 * 0.5,
          f"the audio held for the handshake reached Deepgram ({dg.audio - heard} bytes)")
    State.token_delay = 0

    print("let go while the context wakes (an iPhone's slow resume)")
    # a context that starts suspended and takes 600ms to resume, as Safari's
    # does; the release lands in the middle of it, and closes the context
    page.evaluate("""(() => {
      const AC = window.AudioContext;
      window.realAC = AC; window.resumes = 0;
      window.AudioContext = class extends AC {
        get state() { return this.woke ? super.state : "suspended"; }
        resume() { window.resumes++; return new Promise(r => setTimeout(() => { this.woke = true; r(super.resume()); }, 600)); }
      };
    })()""")
    n, made = len(page.evaluate("window.sent")), sockets(page)["made"]
    page.evaluate("$('#toast').classList.add('hidden'); $('#toast').textContent = ''")
    page.mouse.down()
    page.wait_for_function("window.resumes === 1", timeout=4000)
    page.mouse.up()
    page.wait_for_timeout(1500)
    t = page.evaluate("$('#toast').classList.contains('hidden') ? '' : $('#toast').textContent")
    check(t == "" or t == "Nothing heard", f"a quick hold: no error toast ({t!r})")
    check(page.evaluate("$('#pttl').textContent") == "Hold to talk" and page.evaluate("ptt.cur") is None, "the pill at rest")
    check(len(page.evaluate("window.sent")) == n and sockets(page)["made"] == made, "nothing sent, no socket")
    page.click("#talkconv")
    page.wait_for_function("window.resumes === 2", timeout=4000)
    page.click("#talkconv")
    page.wait_for_timeout(1200)
    check(page.evaluate("$('#toast').classList.contains('hidden')"), "a conversation ended while it woke: no toast")
    check(page.evaluate("conv.cur") is None and page.evaluate("$('#convl').textContent") == "Start conversation",
          "and the pill at rest")
    page.evaluate("window.AudioContext = window.realAC; 0")
    box = page.locator("#talkptt").bounding_box()
    page.mouse.move(box["x"] + 10, box["y"] + 10)

    print("failures")
    State.token_status = 503
    n = len(page.evaluate("window.sent"))
    made = sockets(page)["made"]
    page.mouse.down()
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=8000)
    page.mouse.up()
    check("No listening" in page.evaluate("$('#toast').textContent"), "no key on the server: a toast")
    check(sockets(page)["made"] == made and len(page.evaluate("window.sent")) == n, "no socket, nothing sent")
    page.fill("#talkq", "typed instead")
    page.press("#talkq", "Enter")
    check(page.evaluate("window.sent").pop() == "typed instead", "the box still takes typing")
    State.token_status = 200

    page.evaluate("$('#toast').classList.add('hidden');"
                  "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('no', 'NotAllowedError')); 0")
    page.mouse.down()
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=8000)
    page.mouse.up()
    check("microphone was refused" in page.evaluate("$('#toast').textContent"), "a refused microphone: a toast")
    check(page.evaluate("$('#pttl').textContent") == "Hold to talk", "and the pill at rest")

    page = page.context.new_page()
    page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), lambda ws: ws.on_message(lambda m: ws.close(code=4001, reason="no")))
    page.goto(url)
    box = page.locator("#talkptt").bounding_box()
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=8000)
    page.mouse.up()
    t = page.evaluate("$('#toast').textContent")
    check("Deepgram" in t, f"a refused socket: a toast ({t!r})")
    page.wait_for_function("$('#pttl').textContent === 'Hold to talk'", timeout=8000)
    check(page.evaluate("window.sent.length") == 0, "nothing sent")


class FakeConv:
    """Deepgram for a conversation: the test says what it hears."""

    def __init__(self):
        self.ws = []
        self.audio = 0
        self.texts = []

    def __call__(self, ws):
        self.ws.append(ws)

        def on(msg):
            if isinstance(msg, bytes):
                self.audio += len(msg)
            else:
                self.texts.append(json.loads(msg).get("type"))

        ws.on_message(on)

    def say(self, *msgs):
        for m in msgs:
            self.ws[-1].send(json.dumps(m))


def res(t, final):
    return {"type": "Results", "is_final": final, "speech_final": final,
            "channel": {"alternatives": [{"transcript": t}]}}


def conversation(page, url):
    dg = FakeConv()
    page = page.context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), dg)
    page.goto(url)
    st = "$('#convst').textContent"

    print("conversation: start")
    page.click("#talkconv")
    check(page.evaluate("$('#talkconv').classList.contains('on')") and
          page.evaluate("$('#convl').textContent") == "End conversation", "the pill is on at once, End conversation")
    page.wait_for_function(f"{st} === 'listening'", timeout=8000)
    check(True, "listening once the socket is open")
    check(page.evaluate("$('#talkptt').disabled"), "Hold to talk is off meanwhile")
    s = sockets(page)
    q = dict(re.findall(r"[?&]([^=]+)=([^&]*)", s["urls"][-1]))
    check(q.get("vad_events") == "true" and q.get("endpointing") == "500" and q.get("utterance_end_ms") == "1200"
          and q.get("interim_results") == "true", "vad_events, endpointing 500, utterance_end_ms 1200, interim results")

    print("conversation: an utterance")
    dg.say(res("what is on", False))
    page.wait_for_function("$('#talkq').value === 'what is on'", timeout=4000)
    check(page.evaluate(st) == "hearing…", "the interim words in the box, the pill says hearing")
    dg.say(res("What is on the deck today?", True))
    page.wait_for_timeout(300)
    check(page.evaluate("window.sent.length") == 0, "not sent at the endpoint")
    dg.say({"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 1", timeout=4000)
    check(page.evaluate("window.sent[0]") == "What is on the deck today?" and page.evaluate("window.notes[0]") == "",
          "sent by itself on UtteranceEnd, no note for the crew")
    check(page.evaluate(st) == "listening" and page.evaluate("$('#talkq').value") == "", "listening again, the box empty")
    dg.say(res("Um.", True), {"type": "UtteranceEnd"})
    page.wait_for_timeout(300)
    check(page.evaluate("window.sent.length") == 1 and page.evaluate("$('#talkq').value") == "", "one word of noise: not sent")
    dg.say(res("...", True), {"type": "UtteranceEnd"})
    page.wait_for_timeout(300)
    check(page.evaluate("window.sent.length") == 1, "no letters at all: not sent")
    dg.say(res("Yes.", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 2", timeout=4000)
    check(page.evaluate("window.sent[1]") == "Yes.", "one real word is an answer: \"Yes.\" is sent")
    page.evaluate("window.sent.pop(); window.notes.pop()")
    page.evaluate("eng.name = 'hale-c12'")
    dg.say(res("Make the pill blue.", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 2", timeout=4000)
    check(page.evaluate("window.notes[1]").startswith("[conversation] Answer in one or two spoken sentences first"),
          "an engineer's gets the answer-first note")
    page.evaluate("eng.name = ''")

    print("conversation: barge-in")
    stops = page.evaluate("window.stops")
    page.evaluate("say.run = { shown: 'playing' }")
    dg.say({"type": "SpeechStarted"})
    page.wait_for_timeout(300)
    check(page.evaluate("say.run") is not None and page.evaluate("window.stops") == stops,
          "SpeechStarted alone (the room, the speaker's echo) does not stop a reply")
    dg.say(res("um", False))
    page.wait_for_timeout(300)
    check(page.evaluate("window.stops") == stops, "nor a filler")
    dg.say(res("wait", False))
    page.wait_for_function(f"window.stops === {stops + 1}", timeout=4000)
    check(page.evaluate("say.run") is None, "words while a reply plays stop it")
    dg.say(res("wait, not that one.", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 3", timeout=4000)
    check(page.evaluate("window.sent[2]") == "wait, not that one.", "and the words come through")
    page.evaluate("say.run = null")
    dg.say({"type": "SpeechStarted"})
    page.wait_for_timeout(200)
    check(page.evaluate("window.stops") == stops + 1, "nothing playing: nothing stopped")

    print("conversation: mute while they speak")
    page.evaluate("convSetMode('mute'); say.run = { shown: 'playing' }")
    page.wait_for_function(f"{st} === 'muted'", timeout=3000)
    page.wait_for_timeout(300)
    a0 = dg.audio
    page.wait_for_timeout(1000)
    check(dg.audio == a0, "no audio sent while a reply plays")
    dg.say({"type": "SpeechStarted"})
    page.wait_for_timeout(200)
    check(page.evaluate("say.run") is not None, "and no barge-in")
    t0 = time.time()
    while "KeepAlive" not in dg.texts and time.time() - t0 < 8:
        page.wait_for_timeout(250)
    check("KeepAlive" in dg.texts, "KeepAlive keeps the muted socket")
    page.evaluate("say.run = null")
    page.wait_for_timeout(800)
    check(dg.audio > a0, "the audio flows again once they stop")
    page.evaluate("convSetMode('barge')")

    print("conversation: the phone, the voice through the speaker")
    check(page.evaluate("$('#talkout').hidden"), "the output pill is not offered off a phone")
    page.evaluate("convHoldForTts = true; convSetOutput('speaker'); window.__gum = 0;"
                  "{ const g = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);"
                  "  navigator.mediaDevices.getUserMedia = c => { window.__gum++; return g(c); }; } 0")
    check(not page.evaluate("$('#talkout').hidden") and page.evaluate("$('#talkout').textContent") == "Speaker",
          "on a phone it is: Speaker")
    page.evaluate("window.__tracks = conv.cur.stream.getTracks(); window.quiets = 0;"
                  "say.run = { shown: 'pending' }; convSay(true)")
    check(page.evaluate("conv.cur.stream === null && conv.cur.src === null && conv.cur.held"),
          "a reply begun: the capture is let go")
    check(page.evaluate("window.__tracks.every(t => t.readyState === 'ended')"), "its tracks stopped, not muted")
    check(page.evaluate("window.quiets") >= 1, "and the reply's first sound waits for the switch (sayQuiet)")
    check(page.evaluate(st) == "mic off", "the pill says mic off")
    page.wait_for_timeout(300)
    a0 = dg.audio
    page.wait_for_timeout(800)
    check(dg.audio == a0, "no audio meanwhile")
    k0 = dg.texts.count("KeepAlive")
    t0 = time.time()
    while dg.texts.count("KeepAlive") == k0 and time.time() - t0 < 8:
        page.wait_for_timeout(250)
    check(dg.texts.count("KeepAlive") > k0, "the socket kept with KeepAlive")
    made = sockets(page)["made"]
    page.evaluate("say.run = null; convSay(false)")
    page.wait_for_timeout(150)
    check(page.evaluate("conv.cur.stream") is None, "the run over: not taken again before the settle")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    check(page.evaluate("window.__gum") == 1 and page.evaluate("conv.cur.held") is False, "taken again after it")
    page.wait_for_timeout(600)
    check(dg.audio > a0 and sockets(page)["made"] == made, "the audio flows again, on the same socket")
    dg.say(res("Next question.", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 4", timeout=4000)
    check(page.evaluate("window.sent[3]") == "Next question.", "and the next utterance is heard")
    page.evaluate("window.sent.pop(); window.notes.pop()")

    print("conversation: the phone, an engineer's lines across a tool gap (the run lingers)")
    # the run's states as the speech queue gives them to chatSayRun's
    # onState (convSay(!!v)): pending, playing, linger in the gap, playing, end
    page.evaluate("window.__gum = 0; window.__drops = 0;"
                  "{ const d = convDrop; convDrop = c => { window.__drops++; return d(c); }; } 0")
    page.evaluate("say.run = { shown: 'pending' }; convSay(true); say.run.shown = 'playing'; convSay(true);"
                  "say.run.shown = 'linger'; convSay(true)")
    page.wait_for_timeout(2000)
    check(page.evaluate("conv.cur.held && conv.cur.stream === null && window.__gum === 0"),
          "2s into the gap the capture is still let go, not taken again")
    page.evaluate("say.run.shown = 'playing'; convSay(true); say.run.shown = 'linger'; convSay(true)")
    page.evaluate("say.run = null; convSay(false)")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    check(page.evaluate("window.__drops === 1 && window.__gum === 1"), "two lines 2s apart: dropped once, taken back once")
    page.evaluate("say.run = { shown: 'playing' }; convSay(true); say.run.shown = 'linger'; convSay(true)")
    page.wait_for_timeout(300)
    page.evaluate("say.run = null; convSay(false)")   # a 6s gap: the linger (4s) ran out
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    check(page.evaluate("$('#convst').textContent") == "listening", "a longer gap ends the run: the microphone back, listening")
    page.evaluate("say.run = { shown: 'playing' }; convSay(true)")
    check(page.evaluate("window.__drops === 3 && window.__gum === 2"), "and the next line drops it again")
    page.evaluate("say.run = null; convSay(false)")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    print("conversation: mute, a word in a gap")
    page.evaluate("convHoldForTts = false; convSetMode('mute'); say.run = { shown: 'linger' }")
    page.wait_for_function(f"{st} === 'listening'", timeout=3000)
    dg.say(res("Also the deck.", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 4", timeout=4000)
    check(page.evaluate("window.sent[3]") == "Also the deck.", "the run lingering between lines: not muted, a word in the gap is sent")
    page.evaluate("window.sent.pop(); window.notes.pop(); say.run = null; convSetMode('barge'); convHoldForTts = true")

    print("conversation: the phone, the earpiece")
    page.click("#talkout")
    check(page.evaluate("$('#talkout').textContent") == "Earpiece" and page.evaluate("conv.out") == "earpiece"
          and page.evaluate("JSON.parse(localStorage.getItem('lcars.deck.convout'))") == "earpiece",
          "a tap: Earpiece at once, remembered")
    page.evaluate("window.__gum = 0; say.run = { shown: 'playing' }; convSay(true)")
    check(page.evaluate("!!conv.cur.stream && !conv.cur.held"), "a reply begun: the capture stays open")
    page.evaluate("convSetOutput('speaker')")
    check(page.evaluate("conv.cur.stream === null && conv.cur.held"), "switched to the speaker mid-reply: let go at once")
    page.evaluate("convSetOutput('earpiece')")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    check(page.evaluate("!conv.cur.held && window.__gum === 1"), "and back to the earpiece: taken again at once")
    page.evaluate("say.run = null; convSay(false)")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)

    print("conversation: the phone's audio session (navigator.audioSession)")
    # Safari's API stood in for: each type set is recorded, and the type
    # getUserMedia was called under
    page.evaluate("window.__as = []; window.__gumAs = [];"
                  "navigator.audioSession = { _t: 'auto', get type() { return this._t; },"
                  "  set type(v) { this._t = v; window.__as.push(v); } };"
                  "{ const g = navigator.mediaDevices.getUserMedia;"
                  "  navigator.mediaDevices.getUserMedia = c => { window.__gumAs.push(navigator.audioSession.type); return g(c); }; }"
                  "convSess.type = ''; convSetOutput('speaker')")
    check(page.evaluate("navigator.audioSession.type") == "play-and-record", "listening: play-and-record")
    page.evaluate("say.run = { shown: 'pending' }; convSay(true)")
    check(page.evaluate("navigator.audioSession.type") == "playback" and page.evaluate("conv.cur.held"),
          "a reply with the speaker: the capture let go and the session playback (the loudspeaker)")
    page.click("#talkout")
    check(page.evaluate("navigator.audioSession.type") == "play-and-record" and page.evaluate("$('#talkout').textContent") == "Earpiece",
          "tapped to Earpiece mid-reply: play-and-record and the pill's label in the same task")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    page.click("#talkout")
    check(page.evaluate("navigator.audioSession.type") == "playback" and page.evaluate("conv.cur.stream === null")
          and page.evaluate("$('#talkout').textContent") == "Speaker", "and back to Speaker: playback at once")
    page.evaluate("say.run = null; convSay(false)")
    check(page.evaluate("navigator.audioSession.type") == "auto", "the reply over: auto until the microphone is asked for")
    page.wait_for_function("!!conv.cur.stream", timeout=3000)
    check(page.evaluate("navigator.audioSession.type") == "play-and-record"
          and page.evaluate("window.__gumAs.every(t => t === 'play-and-record')") and page.evaluate("window.__gumAs.length") >= 2,
          "every getUserMedia asked under play-and-record, never playback")
    page.evaluate("convHoldForTts = false; convSetOutput('speaker')")

    print("conversation: a dropped socket")
    made, toks = sockets(page)["made"], page.evaluate("window.tokens")
    dg.ws[-1].close(code=1011)
    page.wait_for_function(f"window.sockets.made === {made + 1} && $('#convst').textContent === 'listening'", timeout=8000)
    check(page.evaluate("window.tokens") == toks + 1, "opened again with a fresh token")
    dg.say(res("Still there?", True), {"type": "UtteranceEnd"})
    page.wait_for_function("window.sent.length === 4", timeout=4000)
    check(True, "and still sends")

    print("conversation: ending")
    dg.say(res("half a", False))
    page.wait_for_function("$('#talkq').value === 'half a'", timeout=4000)
    page.click("#talkconv")
    page.wait_for_function("window.sockets.open === 0", timeout=4000)
    check(not page.evaluate("$('#talkconv').classList.contains('on')") and page.evaluate("$('#convl').textContent") == "Start conversation",
          "End conversation: the socket closed, the pill at rest")
    check(page.evaluate("window.sent.length") == 4 and not page.evaluate("$('#talkptt').disabled"),
          "nothing sent, Hold to talk back")
    check(page.evaluate("conv.cur") is None and page.evaluate("ptt.cur") is None, "the microphone released")
    page.click("#talkconv")
    page.wait_for_function(f"{st} === 'listening'", timeout=8000)
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });"
                  "document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("window.sockets.open === 0", timeout=4000)
    check(page.evaluate("conv.cur") is None, "the page hidden ends it")
    page.evaluate("delete document.hidden")

    print("conversation: failures")
    page.click("#talkconv")
    page.wait_for_function(f"{st} === 'listening'", timeout=8000)
    # the reopened socket is closed at once too: no second try
    page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"),
                          lambda ws: ws.on_message(lambda m: ws.close(code=4001, reason="no")))
    dg.ws[-1].close(code=1011)
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=8000)
    t = page.evaluate("$('#toast').textContent")
    check("conversation has ended" in t and page.evaluate("conv.cur") is None, f"a socket dropped twice: a toast, and it ends ({t!r})")
    page.evaluate("$('#toast').classList.add('hidden')")
    # a socket that never opens (a stand-in that stays connecting; a route
    # cannot hold one so without blocking Playwright): a failure after
    # CONV_OPEN_MS, not a hang
    page.evaluate("window.__WS = window.WebSocket; window.WebSocket = function () {"
                  " return { readyState: 0, send() {}, close() { window.stuckClosed = true; } }; }; 0")
    page.click("#talkconv")
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=12000)
    t = page.evaluate("$('#toast').textContent")
    check("did not answer" in t and page.evaluate("conv.cur") is None and page.evaluate("window.stuckClosed"),
          f"a socket that never opens: a toast, closed, and it ends ({t!r})")
    page.evaluate("window.WebSocket = window.__WS; $('#toast').classList.add('hidden')")
    page.evaluate("$('#toast').classList.add('hidden')")
    State.token_status = 503
    page.click("#talkconv")
    page.wait_for_function("!$('#toast').classList.contains('hidden')", timeout=8000)
    check("No listening" in page.evaluate("$('#toast').textContent") and page.evaluate("conv.cur") is None
          and page.evaluate("$('#convl').textContent") == "Start conversation", "no token: a toast, and it ends")
    State.token_status = 200

    print("hold to talk: the phone's audio session")
    # the stand-in that answers again (the failures' one closes every socket)
    page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), dg)
    page.evaluate("convHoldForTts = true; convSess.type = ''; window.__gumAs = []; convSetOutput('speaker'); pttDown()")
    page.wait_for_function("!!(ptt.cur && ptt.cur.stream)", timeout=8000)
    check(page.evaluate("navigator.audioSession.type") == "play-and-record" and page.evaluate("window.__gumAs") == ["play-and-record"],
          "held: the microphone asked for under play-and-record")
    page.evaluate("pttUp()")
    check(page.evaluate("navigator.audioSession.type") == "auto", "let go: auto")
    page.evaluate("say.run = { shown: 'pending' }; convSay(true)")
    check(page.evaluate("navigator.audioSession.type") == "playback", "the reply, with the speaker chosen: playback (no conversation needed)")
    page.click("#talkout")
    check(page.evaluate("navigator.audioSession.type") == "play-and-record" and page.evaluate("$('#talkout').textContent") == "Earpiece",
          "the pill tapped: the earpiece's play-and-record at once")
    page.click("#talkout")
    check(page.evaluate("navigator.audioSession.type") == "playback", "and the speaker again")
    page.evaluate("say.run = null; convSay(false)")
    check(page.evaluate("navigator.audioSession.type") == "auto", "the reply over: auto")
    page.evaluate("convHoldForTts = false; delete navigator.audioSession")
    check(not errors, "no script errors in the conversation" + (": " + "; ".join(errors[:3]) if errors else ""))


def real(page, url):
    key = env_key()
    if not key:
        sys.exit("ptt --real: no DEEPGRAM_API_KEY in the environment or .env")
    State.token = key
    page.goto(url)
    print("the real Deepgram, with the long-lived key as the token")
    pill = page.locator("#talkptt")
    box = pill.bounding_box()
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    page.wait_for_function("$('#pttl').textContent === 'Listening…'", timeout=10000)
    check(sockets(page).get("opened") == 1, "the socket to wss://api.deepgram.com/v1/listen opened")
    page.wait_for_timeout(2000)
    page.mouse.up()
    page.wait_for_function("window.sockets.codes.length === 1", timeout=10000)
    s = sockets(page)
    check(s["codes"] == [1000], f"Deepgram closed it cleanly after CloseStream (codes {s['codes']})")
    check(s["protos"] == ["token"], "a plain key goes as a token")
    toast = page.evaluate("$('#toast').classList.contains('hidden') ? '' : $('#toast').textContent")
    # Chromium's fake microphone is a beep: nothing to transcribe
    check(toast in ("", "Nothing heard"), f"no failure toast ({toast!r})")


if __name__ == "__main__":
    main()
