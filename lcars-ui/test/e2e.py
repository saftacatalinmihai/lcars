#!/usr/bin/env python3
"""The parts of the page that only a real browser can answer for.

`test/run.sh` boots the page in QuickJS against a DOM shim, which is enough for
almost everything — but a shim answers whatever it was written to answer. The
questions here are about the browser's own behaviour, and a shim cannot be a
witness to them:

  * does `setRangeText` at the caret put the text where the code thinks,
  * does focus move where the code sends it, and does the caret follow,
  * does what voice typed reach the handlers a keystroke would have run
    (the byte count, the dirty flag),
  * and can a programmatic insertion be taken back again.

The last one is here because it was wrong: `execCommand("undo")` does not act
on a form control in Chrome, so "computer undo" did nothing at all, and the
QuickJS suite could not have seen it. Voice now keeps its own before-images.

    python3 test/e2e.py [screenshot.png]

The page is served over http://127.0.0.1 — a secure context, so the microphone
is not refused out of hand — and `SpeechRecognition` is replaced before the page
script runs by a fake that emits the transcripts a recogniser would. Nothing
here touches the real journal: `/entries` and `/stats` are stubbed.
"""
import http.server
import pathlib
import re
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

D = pathlib.Path(__file__).resolve().parent.parent

rows = [{
    "id": 1200 - i, "kind": "personal_log", "title": f"Log {i}",
    "content": "- existing line\n", "content_length": 16,
    "value_int": 0, "value_float": 0.0, "done_bool": 0, "deleted": 0,
    "created_at_utc": "2026-09-17 10:00:00", "last_modified_at_utc": "2026-09-17 10:00:00",
} for i in range(6)]

# A recogniser that says exactly what it is told to, when it is told to.
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(D), **kw)

    def log_message(self, *a):
        pass


def main():
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        origin = "http://127.0.0.1:%d" % srv.server_address[1]
        fails = []
        checks = [0]

        def check(cond, msg):
            checks[0] += 1
            print(("  ok   " if cond else "  FAIL ") + msg)
            if not cond:
                fails.append(msg)

        uploads = []
        tapes = {}

        def handle(route):
            url = route.request.url
            # a recording streams here slice by slice while it is made
            m = re.search(r"/tapes/([0-9a-f]+)\?off=(\d+)", url)
            if m:
                body = route.request.post_data_buffer or b""
                held = tapes.get(m.group(1), b"")[:int(m.group(2))] + body
                tapes[m.group(1)] = held
                return route.fulfill(json={"size": len(held)})
            m = re.search(r"/entries/(\d+)/media", url)
            if m:
                if route.request.method == "POST":
                    # a body-less ?tape= attach stores what was streamed
                    tape = re.search(r"[?&]tape=([0-9a-f]+)", url)
                    uploads.append((route.request.headers.get("content-type"),
                                    len(tapes.get(tape.group(1), b"")) if tape else
                                    len(route.request.post_data_buffer or b""),
                                    "tape" if tape else "whole"))
                    return route.fulfill(json={
                        "id": 90, "entry_id": int(m.group(1)), "bytes": uploads[-1][1],
                        "path": "media/2026/09/24/e%s-dictation.m4a" % m.group(1),
                        "mime": "audio/mp4", "name": "dictation.m4a",
                        "created_at_utc": "2026-09-24 10:00:00"})
                return route.fulfill(json=[])
            if "/stats" in url:
                return route.fulfill(json={"count": len(rows),
                                           "newest_created_at_utc": rows[0]["created_at_utc"]})
            m = re.search(r"/entries/(\d+)", url)
            if m:
                hit = next((r for r in rows if r["id"] == int(m.group(1))), None)
                return route.fulfill(json=hit) if hit else route.fulfill(
                    status=404, json={"error": "no such entry"})
            if "/entries" in url:
                return route.fulfill(json=rows)
            return route.fallback()

        with sync_playwright() as p:
            # a fake microphone, granted without a prompt, for the dictation tape
            browser = p.chromium.launch(headless=True, args=[
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            ctx.add_init_script(FAKE_REC)
            for pat in ("/entries*", "/entries/**", "/stats*", "/tapes/**"):
                ctx.route(origin + pat, handle)
            page = ctx.new_page()
            page.on("pageerror", lambda e: fails.append("page error: " + str(e)))
            page.goto(origin + "/index.html")
            page.wait_for_selector('.item[data-id="1200"]')
            page.wait_for_timeout(300)

            def soon(cond, ms=10000):
                """Poll `cond` (a Python callable) until it holds or `ms`
                pass. What follows an async step (the tape's upload, a
                reload) is waited for, not slept on: on a busy box a fixed
                sleep is a race the page sometimes loses."""
                for _ in range(ms // 50):
                    if cond():
                        return
                    page.wait_for_timeout(50)

            print("-- voice, in a real browser --")
            page.click('.item[data-id="1200"]')
            page.wait_for_timeout(300)
            page.keyboard.press("e")             # into the form
            page.wait_for_timeout(200)
            page.click("#content")
            page.keyboard.press("Control+End")

            page.click("#bVoice")
            page.wait_for_timeout(200)
            check(page.evaluate("() => !!(window.__rec && window.__rec.started)"),
                  "the toggle starts a recognition session")
            check(page.evaluate("() => document.body.dataset.voice") == "on",
                  "the read-out is up")
            check(page.evaluate('() => $("#vmode").textContent') == "orders · no wake word",
                  "and it opens listening for orders, not dictating")
            page.evaluate("() => window.__say('start dictation', true)")
            soon(lambda: page.evaluate('() => $("#vmode").textContent') == "dictation · rec")
            # and the tape's first slice is on the server: a tape stopped with
            # nothing streamed is not attached (the 800ms this replaced was
            # buying that time too)
            soon(lambda: any(tapes.values()))
            check(page.evaluate('() => $("#vmode").textContent') == "dictation · rec",
                  "a bare \"start dictation\" starts typing, and the tape with it")

            page.evaluate("() => window.__say('half a sentence', false)")
            page.wait_for_timeout(100)
            check("half a sentence" in page.evaluate('() => $("#vsaid").textContent'),
                  "an interim transcript reaches the read-out")
            check("half a sentence" not in page.evaluate('() => $("#content").value'),
                  "and is never typed")

            page.evaluate("() => window.__say('we sized the arena at one megabyte period', true)")
            page.wait_for_timeout(150)
            val = page.evaluate('() => $("#content").value')
            check(val.endswith("We sized the arena at one megabyte."),
                  "a final one lands at the caret, capitalised and stopped: " + repr(val[-40:]))
            check(page.evaluate("() => document.body.classList.contains('dirty')"),
                  "the form knows it was edited")
            check("words" in page.evaluate('() => $("#clen").textContent'),
                  "and the byte count was refreshed")

            page.evaluate("() => window.__say('one more thing computer delete last word', true)")
            page.wait_for_timeout(150)
            val = page.evaluate('() => $("#content").value')
            check(val.endswith("One more"),
                  "words land before the order that follows them: " + repr(val[-20:]))

            page.evaluate("() => window.__say('computer edit title a fine day', true)")
            page.wait_for_timeout(150)
            check(page.evaluate("() => document.activeElement.id") == "e_head",
                  "an order moves the focus")
            title = page.evaluate('() => $("#e_head").value')
            check(title == "Log 0 a fine day",
                  "and the rest of the utterance lands there, after what was in it: " + repr(title))

            page.evaluate("() => window.__say('computer undo', true)")
            page.wait_for_timeout(150)
            check(page.evaluate('() => $("#e_head").value') == "Log 0",
                  "a spoken undo takes the insertion back — execCommand cannot, so voice keeps "
                  "its own before-images")

            page.evaluate("() => window.__say('computer pause dictation', true)")
            soon(lambda: uploads and "dictation" in page.evaluate('() => $("#content").value')[-60:])
            check(len(uploads) == 1 and uploads[0][1] > 0 and uploads[0][2] == "tape",
                  "stopping dictation attaches the tape it streamed: %r" % uploads)
            val = page.evaluate('() => $("#content").value')
            check(re.search(r"One more\n\[🎙 dictation \d\d:\d\d\]"
                            r"\(media/2026/09/24/e1200-dictation\.m4a\)\n$", val) is not None,
                  "and links it on the line after the dictated text: " + repr(val[-80:]))
            check(page.evaluate('() => $("#vmode").textContent') == "orders · no wake word",
                  "paused, the read-out says the wake word is optional")
            page.evaluate("() => window.__say('clear the field', true)")
            page.wait_for_timeout(150)
            check(page.evaluate('() => $("#e_head").value') == "",
                  "and a bare order runs")

            page.click("#bVoice")
            page.wait_for_timeout(200)
            check(page.evaluate("() => document.body.dataset.voice") == "off",
                  "the toggle stops it again")
            check(not page.evaluate("() => window.__rec.started"), "and the session is closed")

            print("-- column grips, under a real mouse --")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            width = lambda sel: page.evaluate(
                "s => document.querySelector(s).getBoundingClientRect().width", sel)

            def drag_grip(grip, dx):
                b = page.locator(grip).bounding_box()
                x, y = b["x"], b["y"] + 300
                hit = page.evaluate("([x, y]) => document.elementFromPoint(x, y).id", [x, y])
                check(hit == grip[1:], "the pointer finds %s on the border (got %r)" % (grip, hit))
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(x + dx / 2, y)
                page.mouse.move(x + dx, y)
                page.mouse.up()
                page.wait_for_timeout(50)

            side0, list0 = width("#side"), width("#listpane")
            drag_grip("#sidegrip", 80)
            check(abs(width("#side") - (side0 + 80)) <= 1,
                  "dragging the filters grip widens the column: %r -> %r" % (side0, width("#side")))
            check(abs(width("#listpane") - list0) <= 1, "and leaves the entries column its width")
            drag_grip("#listgrip", -120)
            check(abs(width("#listpane") - (list0 - 120)) <= 1,
                  "the entries grip narrows its column: %r -> %r" % (list0, width("#listpane")))
            check(page.evaluate('() => localStorage.getItem("lcars.listw")') ==
                  str(round(list0 - 120)), "and the width is written down")
            page.reload()
            page.wait_for_selector('.item[data-id="1200"]')
            page.wait_for_timeout(300)
            check(abs(width("#listpane") - (list0 - 120)) <= 1, "a reload keeps it")
            page.dblclick("#listgrip", position={"x": 0, "y": 300}, force=True)
            page.wait_for_timeout(50)
            check(abs(width("#listpane") - list0) <= 1, "double-click puts the default back")

            if len(sys.argv) > 1:
                page.screenshot(path=sys.argv[1])
            browser.close()

        print("\ne2e: %d checks, %d failures" % (checks[0], len(fails)))
        sys.exit(1 if fails else 0)


main()
