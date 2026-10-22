#!/usr/bin/env python3
"""The console's speech queue, in headless Chromium.

This runs index.html's "speech queue" block (the chats' voice, and the
deck's talk sheet's) - cut verbatim from the page between its markers - in
a bare page with a speaking mark and stand-ins for the globals it reads. The browser side is real: fetch, the
AudioContext, decodeAudioData, AudioBufferSourceNode. A stand-in /say
answers each line a moment late, as a provider does - as raw PCM streamed
a tenth of a second at a time (a level of its own per line, so the order
can be read back off the buffers), or as a whole WAV like a server without
{"format":"pcm"} - and logs when each request began and ended.

  1. sayCut: sentences cut where they end, "Dr." and "No. 4" and a
     sentence still being written not;
  2. a run of two sentences, streamed and whole: fetched in order, the
     second only once the first is playing (one request ahead at most),
     every buffer played back to back with no gap and no overlap, all of
     the first before any of the second, the first sound soon; the mark says "voice…", then "speaking"
     across both, then goes; done resolves true;
  3. stop: tapping the mark while the first plays stops it, the second
     (fetched, maybe scheduled) is stopped before its time, the mark goes;
  4. sayAloud while a run is speaking stops the run first;
  5. the server's voice failing (503): a run with an utterance maker goes
     on in speechSynthesis; sayAloud resolves false for its caller;
  6. sayReopen (an engineer's next message, a poll later): an ended run
     still speaking takes another line, played after the first with no cut;
     a finished or stopped one does not;
  7. sayQuiet (a microphone capture just let go of, on a phone): the
     first sound waits until its moment is over, the rest follows it back
     to back; and nothing waits once it has passed;
  8. a lingering run (sayEnd's `linger`, an engineer at work: voice-live-
     narration.md 3.3): reopened across a 2.5s gap it never ends between
     (no "" state, the mark never goes), "linger" in the gap; a gap longer
     than the linger ends it; a stop in the gap ends it at once, and a line
     added after the stop is neither fetched nor played.

    python3 test/speech.py
"""
import http.server
import io
import json
import math
import pathlib
import re
import struct
import sys
import threading
import time
import wave

HERE = pathlib.Path(__file__).resolve().parent
CONSOLE = (HERE.parent / "index.html").read_text()

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def block():
    m = re.search(r"/\* =+ speech queue =+.*?/\* =+ end speech queue =+ \*/", CONSOLE, re.S)
    if not m:
        sys.exit("speech: the speech queue markers are not in index.html")
    return m.group(0)


PAGE = """<!doctype html><meta charset=utf-8><body>
<div id="talk"><button id="talksay" type="button" hidden></button></div>
<script>
// what the block reads, stood in for
const $ = s => document.querySelector(s);
const DEMO = false;
const cfg = { base: "", user: "", pass: "" };
const b64 = s => btoa(s);
let sound = "on", actx = null;
// the page's own, outside the block (index.html's, much simplified)
function sayOn() { return sound !== "off"; }
function sayShow(v) { const el = $("#talksay"); el.hidden = !v; el.textContent = v === "pending" ? "voice…" : "speaking"; }
// every source the queue starts and stops, on the context's clock
window.plays = []; window.marks = [];
{
  const start = AudioBufferSourceNode.prototype.start, stop = AudioBufferSourceNode.prototype.stop;
  AudioBufferSourceNode.prototype.start = function (at) {
    // the stand-in's lines are a constant level each: 1000 for the first...
    this._rec = { at: at || 0, dur: this.buffer.duration, line: Math.round(this.buffer.getChannelData(0)[0] * 32768 / 1000), stopped: false };
    window.plays.push(this._rec);
    if (!window.firstAt) window.firstAt = performance.now();
    return start.apply(this, arguments);
  };
  AudioBufferSourceNode.prototype.stop = function () {
    if (this._rec) this._rec.stopped = true;
    return stop.apply(this, arguments);
  };
}
// the mark, every state it shows
new MutationObserver(() => {
  const el = $("#talksay"), v = el.hidden ? "" : el.textContent;
  if (window.marks[window.marks.length - 1] !== v) window.marks.push(v);
}).observe($("#talksay"), { attributes: true, childList: true, characterData: true, subtree: true });
// speechSynthesis stood in for: it only has to take the lines in order
Object.defineProperty(window, "speechSynthesis", { value: { speak(u) {}, cancel() {} }, configurable: true });
window.utters = [];
window.fakeUtter = text => { window.utters.push(text); return { set onstart(f) {}, set onend(f) { setTimeout(f, 50); }, set onerror(f) {} }; };
</script>
<script>%s</script>
<script>
$("#talksay").addEventListener("click", () => { window.stoppedAt = actx.currentTime; sayStop(); });
</script>
"""


class State:
    say_status = 200
    pcm = True        # answer {"format":"pcm"} as a server with it does
    delay = 0.15
    log = []          # [text, began, ended]
    lines = []        # the run's lines, in the order they are said
    lock = threading.Lock()


def tone(seconds, freq=440, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)))
    return buf.getvalue()


def serve(page):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/say":
                self.reply(200, json.dumps({"provider": "deepgram"}).encode(), "application/json")
            else:
                self.reply(200, page.encode(), "text/html")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n))
            text = req["text"]
            rec = [text, time.monotonic(), None]
            with State.lock:
                State.log.append(rec)
            time.sleep(State.delay)
            try:
                if State.say_status != 200:
                    self.reply(State.say_status, b'{"error":"no voice"}', "application/json")
                elif State.pcm and req.get("format") == "pcm":
                    # 0.6s of a level of its own, a tenth at a time, made a
                    # little faster than it plays, in odd-sized pieces
                    level = 1000 * (State.lines.index(text) + 1 if text in State.lines else 9)
                    data = struct.pack("<h", level) * int(0.6 * 24000)
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/L16;rate=24000;channels=1")
                    self.end_headers()
                    step = 4801
                    for i in range(0, len(data), step):
                        self.wfile.write(data[i:i + step])
                        self.wfile.flush()
                        time.sleep(0.08)
                else:
                    # half a second of tone a line, so a run is quick to hear out
                    self.reply(200, tone(0.5), "audio/wav")
            except (BrokenPipeError, ConnectionResetError):
                pass
            rec[2] = time.monotonic()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def reset(page):
    State.log = []
    State.say_status = 200
    page.evaluate("window.plays = []; window.firstAt = 0; window.marks = []; window.utters = []; sayStop(); window.marks = []")


def overlapping(log):
    """The most /say requests in flight at once."""
    ev = sorted([(r[1], 1) for r in log] + [(r[2] or 1e18, -1) for r in log], key=lambda e: (e[0], e[1]))
    cur = most = 0
    for _, d in ev:
        cur += d
        most = max(most, cur)
    return most


def cuts(page):
    print("sayCut")
    cut = lambda t, f=0: page.evaluate("([t, f]) => sayCut(t, f)", [t, f])
    r = cut("Ask Dr. Crusher about it. No. 4 is next. Yes. Then the last one is still bei")
    check(r["parts"] == ["Ask Dr. Crusher about it.", "No. 4 is next."], f"Dr. and No. 4 stay whole ({r['parts']})")
    check(not any("still bei" in p for p in r["parts"]), "an unfinished sentence is not cut")
    r = cut("I checked the log. ")
    check(r["parts"] == [] and r["next"] == 0, "the last sentence waits for words after it (narration before a tool is never cut)")
    r = cut("First one is here. Second one is here. Th", 0)
    check(r["parts"] == ["First one is here.", "Second one is here."], f"two sentences ({r['parts']})")
    r2 = cut("First one is here. Second one is here. Third arrives now. And", r["next"])
    check(r2["parts"] == ["Third arrives now."], f"from where the last cut ended ({r2['parts']})")
    r = cut("Items:\n- eggs\n- milk\nThat is all")
    check(r["parts"] == ["Items:", "- eggs", "- milk"], f"newlines cut ({r['parts']})")
    r = cut("The ratio is 3.5 today, Captain. Next")
    check(r["parts"] == ["The ratio is 3.5 today, Captain."], f"3.5 does not cut ({r['parts']})")


def two_in_order(page, pcm):
    print("a run of two sentences, " + ("streamed as PCM" if pcm else "from a server that answers mp3 whole"))
    reset(page)
    State.pcm = pcm
    State.lines = ["First sentence, Captain.", "And here is the second."]
    page.evaluate("""() => {
      window.st = [];
      window.run = sayRun("ensign", true, 0.9, v => { window.st.push(v); sayShow(v); });
      window.added = performance.now();
      sayAdd(run, "First sentence, Captain.");
      setTimeout(() => { sayAdd(run, "And here is the second."); sayEnd(run); }, 50);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.ended !== null", timeout=15000)
    log = State.log
    plays = page.evaluate("window.plays")
    check([r[0] for r in log] == State.lines, f"fetched in order ({[r[0] for r in log]})")
    most = overlapping(log)
    check(most <= (2 if pcm else 1), f"at most one request ahead of the voice ({most} at once)")
    check(len(log) == 2 and log[1][1] >= log[0][1] + (0.2 if pcm else State.delay),
          "the second asked for only once the first had begun")
    lines = [p["line"] for p in plays]
    if pcm:
        check(lines == sorted(lines) and set(lines) == {1, 2}, f"all of the first, then all of the second ({lines})")
    gaps = [plays[k]["at"] - (plays[k - 1]["at"] + plays[k - 1]["dur"]) for k in range(1, len(plays))]
    worst = max((abs(g) for g in gaps), default=0)
    check(worst < 0.002, f"back to back, no gap and no overlap over {len(plays)} buffers (worst {worst * 1000:.2f}ms)")
    total = sum(p["dur"] for p in plays)
    want = 1.2 if pcm else 1.0
    check(abs(total - want) < 0.01, f"every sample played ({total:.3f}s of {want})")
    first = page.evaluate("window.firstAt - window.added") / 1000
    check(first < (0.6 if pcm else 2), f"the first sound {first:.2f}s after the line was added")
    st = page.evaluate("window.st")
    check(st == ["pending", "playing", ""], f"pending, then playing across both, then nothing ({st})")
    marks = page.evaluate("window.marks")
    while marks and marks[0] == "":
        marks.pop(0)
    check(marks == ["voice…", "speaking", ""], f"the mark said voice…, speaking, then went ({marks})")
    check(page.evaluate("window.ended") is True, "done resolved true")
    return first


def stop(page):
    print("stop by tapping the mark")
    reset(page)
    State.lines = ["This first one plays.", "This second one never does."]
    page.evaluate("""() => {
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v));
      sayAdd(run, "This first one plays.");
      sayAdd(run, "This second one never does.");
      sayEnd(run);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1 && !$('#talksay').hidden", timeout=10000)
    page.wait_for_timeout(200)
    page.click("#talksay")
    page.wait_for_function("window.ended !== null", timeout=5000)
    page.wait_for_timeout(1500)
    plays = page.evaluate("window.plays")
    at = page.evaluate("window.stoppedAt")
    check(any(p["at"] <= at < p["at"] + p["dur"] and p["stopped"] for p in plays), "the one playing was stopped")
    check(all(p["stopped"] for p in plays if p["at"] + p["dur"] > at), "nothing scheduled after the stop was left to play")
    check(not any(p["line"] == 2 and p["at"] <= at for p in plays), "the second line was never heard")
    check(len(State.log) <= 2, "nothing asked for after the stop")
    check(page.evaluate("$('#talksay').hidden"), "the mark went")
    check(page.evaluate("say.run") is None, "no run left")


def single_over_run(page):
    print("sayAloud while a run speaks")
    reset(page)
    State.lines = ["A long reply is under way."]
    page.evaluate("""() => {
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v));
      sayAdd(run, "A long reply is under way.");
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1", timeout=10000)
    page.evaluate("window.one = null; sayAloud('Attention all hands.', 'computer', 0.5, null).then(ok => { window.one = ok; })")
    page.wait_for_function("window.one !== null", timeout=10000)
    plays = page.evaluate("window.plays")
    nine = [p["at"] for p in plays if p["line"] == 9]
    t9 = min(nine) if nine else 0
    check(page.evaluate("window.ended") is True, "the run ended")
    check(bool(nine) and all(p["stopped"] for p in plays if p["line"] == 1 and p["at"] + p["dur"] > t9),
          "everything of the run that would have played with the line was stopped")
    check(not any(p["line"] == 1 and p["at"] >= t9 for p in plays), "nothing of the run after the line began")


def fallback(page):
    print("no voice on the server")
    reset(page)
    State.say_status = 503
    page.evaluate("say.prov = undefined")
    page.evaluate("""() => {
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v), t => window.fakeUtter(t));
      sayAdd(run, "Spoken by the browser.");
      sayAdd(run, "So is this one.");
      sayEnd(run);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.ended !== null", timeout=10000)
    check(page.evaluate("window.utters") == ["Spoken by the browser.", "So is this one."], "the run went on in speechSynthesis, in order")
    check(len(State.log) == 1, "the server was not asked again after it failed")
    page.evaluate("say.prov = undefined")
    page.evaluate("window.one = null; sayAloud('Red alert.', 'computer', 0.5, null).then(ok => { window.one = ok; })")
    page.wait_for_function("window.one !== null", timeout=10000)
    check(page.evaluate("window.one") is False, "sayAloud resolves false for its caller to fall back")


def reopen(page):
    print("sayReopen: a line for a run still speaking")
    reset(page)
    State.lines = ["The first message is here.", "And the next message follows."]
    page.evaluate("""() => {
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v));
      sayAdd(run, "The first message is here.");
      sayEnd(run);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1", timeout=10000)
    ok = page.evaluate("sayReopen(run) && (sayAdd(run, 'And the next message follows.'), sayEnd(run), true)")
    check(ok, "the run still speaking takes it back")
    page.wait_for_function("window.ended !== null", timeout=10000)
    plays = page.evaluate("window.plays")
    lines = [p["line"] for p in plays]
    check(lines == sorted(lines) and set(lines) == {1, 2} and not any(p["stopped"] for p in plays),
          f"played after the first, nothing cut ({lines})")
    check(page.evaluate("sayReopen(run)") is False, "a finished run is not reopened")
    page.evaluate("window.run2 = sayRun('ensign', false, 0.9, null); sayStop()")
    check(page.evaluate("sayReopen(run2)") is False, "nor a stopped one")


def quiet(page):
    print("sayQuiet: the first sound waits for the session to switch")
    reset(page)
    State.lines = ["The microphone was just let go.", "And this follows it."]
    page.evaluate("""() => {
      window.q0 = actx.currentTime;
      sayQuiet(900);
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v));
      sayAdd(run, "The microphone was just let go.");
      sayAdd(run, "And this follows it.");
      sayEnd(run);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.ended !== null", timeout=15000)
    plays, q0 = page.evaluate("window.plays"), page.evaluate("window.q0")
    first = min(p["at"] for p in plays) - q0 if plays else 0
    check(0.85 <= first < 1.3, f"the first sound {first:.2f}s after the capture went (sayQuiet 0.9s; the fetch alone is {State.delay}s)")
    gaps = [plays[k]["at"] - (plays[k - 1]["at"] + plays[k - 1]["dur"]) for k in range(1, len(plays))]
    check(max((abs(g) for g in gaps), default=0) < 0.002, "the rest back to back after it")
    reset(page)
    State.lines = ["Long after it."]
    page.evaluate("""() => {
      window.q0 = actx.currentTime;
      window.run = sayRun("ensign", false, 0.9, v => sayShow(v));
      sayAdd(run, "Long after it."); sayEnd(run);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1", timeout=10000)
    first = page.evaluate("window.plays[0].at") - page.evaluate("window.q0")
    check(first < 0.6, f"once it has passed, no wait ({first:.2f}s)")
    page.wait_for_function("window.ended !== null", timeout=10000)


def linger(page):
    print("a lingering run: an engineer's lines across a tool gap")
    reset(page)
    State.lines = ["Reading the poll now.", "Found it, editing."]
    page.evaluate("""() => {
      window.st = [];
      window.run = sayRun("ensign", false, 0.9, v => { window.st.push(v); sayShow(v); });
      sayAdd(run, "Reading the poll now."); sayEnd(run, 4000);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.st.includes('linger')", timeout=10000)
    page.wait_for_timeout(2500)
    check(page.evaluate("window.ended") is None and page.evaluate("say.run === run"), "2.5s into the gap the run is still open")
    check(page.evaluate("sayReopen(run)") is True, "and takes the next line")
    page.evaluate("sayAdd(run, 'Found it, editing.'); sayEnd(run, 600)")
    page.wait_for_function("window.ended !== null", timeout=10000)
    st = page.evaluate("window.st")
    check(st == ["pending", "playing", "linger", "playing", "linger", ""], f"one run, no end between the lines ({st})")
    marks = page.evaluate("window.marks")
    while marks and marks[0] == "":
        marks.pop(0)
    check(marks == ["voice…", "speaking", ""], f"the mark never went in the gap ({marks})")
    lines = [p["line"] for p in page.evaluate("window.plays")]
    check(set(lines) == {1, 2} and lines == sorted(lines), f"both lines, in order ({lines})")
    check(page.evaluate("sayReopen(run)") is False, "a gap longer than the linger ended it: not reopened")

    reset(page)
    State.lines = ["Running the tests."]
    page.evaluate("""() => {
      window.st = [];
      window.run = sayRun("ensign", false, 0.9, v => { window.st.push(v); sayShow(v); });
      sayAdd(run, "Running the tests."); sayEnd(run, 4000);
      window.ended = null; run.done.then(ok => { window.ended = ok; });
    }""")
    page.wait_for_function("window.st.includes('linger')", timeout=10000)
    page.click("#talksay")
    page.wait_for_function("window.ended !== null", timeout=2000)
    check(page.evaluate("window.st[window.st.length - 1]") == "" and page.evaluate("$('#talksay').hidden"),
          "a stop in the gap ends the run at once, the mark gone")
    n = len(State.log)
    page.evaluate("sayReopen(run); sayAdd(run, 'A line after the stop.'); sayEnd(run)")
    page.wait_for_timeout(800)
    check(len(State.log) == n and not any(p["line"] == 9 for p in page.evaluate("window.plays")),
          "a line added after the stop: not fetched, not played")


def after(page):
    print("sayRun after: the computer's quick answer, then Number One")
    reset(page)
    State.lines = ["The deploy is four minutes in.", "Number One here, it is nearly done."]
    page.evaluate("""() => {
      window.st = []; window.st2 = [];
      window.a = sayRun("computer", true, 0.9, v => { window.st.push(v); sayShow(v); });
      sayAdd(a, "The deploy is four minutes in."); sayEnd(a);
      window.endedA = null; a.done.then(ok => { window.endedA = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1", timeout=10000)
    page.evaluate("""() => {
      window.b = sayRun("c34", false, 0.9, v => { window.st2.push(v); sayShow(v); }, null, { after: a });
      sayAdd(b, "Number One here, it is nearly done."); sayEnd(b);
      window.endedB = null; b.done.then(ok => { window.endedB = ok; });
    }""")
    check(page.evaluate("say.run === b && sayLive(a)"), "the run speaking is not stopped: the new one follows it")
    page.wait_for_function("window.endedB !== null", timeout=15000)
    plays = page.evaluate("window.plays")
    one = [p for p in plays if p["line"] == 1]
    two = [p for p in plays if p["line"] == 2]
    check(bool(one) and bool(two) and not any(p["stopped"] for p in plays), "both said whole, nothing cut")
    if one and two:
        end1 = max(p["at"] + p["dur"] for p in one)
        start2 = min(p["at"] for p in two)
        check(start2 >= end1 - 0.002, f"the second run's first sound after the first run's last ({start2 - end1:+.3f}s)")
        check(start2 - end1 < 0.05, f"and straight on, no gap ({(start2 - end1) * 1000:.0f}ms)")
    check(page.evaluate("window.endedA") is True and page.evaluate("say.run") is None, "both over, no run left")
    check(page.evaluate("window.st2") == ["playing", ""], f"the second shows nothing until it plays ({page.evaluate('window.st2')})")
    marks = page.evaluate("window.marks")
    while marks and marks[0] == "":
        marks.pop(0)
    check(marks == ["voice…", "speaking", ""], f"the mark stayed across the two speakers ({marks})")

    print("a stop during the first ends both")
    reset(page)
    State.lines = ["The computer says this.", "Number One never says this."]
    page.evaluate("""() => {
      window.a = sayRun("computer", true, 0.9, v => sayShow(v));
      sayAdd(a, "The computer says this."); sayEnd(a);
      window.b = sayRun("c34", false, 0.9, v => sayShow(v), null, { after: a });
      sayAdd(b, "Number One never says this."); sayEnd(b);
      window.endedA = window.endedB = null;
      a.done.then(ok => { window.endedA = ok; }); b.done.then(ok => { window.endedB = ok; });
    }""")
    page.wait_for_function("window.plays.length >= 1 && !$('#talksay').hidden", timeout=10000)
    page.wait_for_timeout(150)
    page.click("#talksay")
    page.wait_for_function("window.endedA !== null && window.endedB !== null", timeout=3000)
    page.wait_for_timeout(1200)
    plays = page.evaluate("window.plays")
    at = page.evaluate("window.stoppedAt")
    check(all(p["stopped"] for p in plays if p["at"] + p["dur"] > at), "the first stopped where it was")
    check(not any(p["line"] == 2 for p in plays), "the second never heard")
    check(page.evaluate("say.run") is None and page.evaluate("$('#talksay').hidden"), "no run left, the mark gone")
    page.evaluate("window.c = sayRun('c34', false, 0.9, null, null, { after: a })")
    check(page.evaluate("say.run === c && !c.after"), "after a run already over: a plain run")
    page.evaluate("sayStop()")


def main():
    from playwright.sync_api import sync_playwright

    srv = serve(PAGE % block())
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        cuts(page)
        two_in_order(page, True)
        two_in_order(page, False)
        State.pcm = True
        stop(page)
        single_over_run(page)
        fallback(page)
        State.say_status = 200
        page.evaluate("say.prov = undefined")
        reopen(page)
        quiet(page)
        linger(page)
        after(page)
        check(not errors, "no script errors" + (": " + "; ".join(errors[:3]) if errors else ""))
        browser.close()
    srv.shutdown()
    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nspeech: all passed")


if __name__ == "__main__":
    main()
