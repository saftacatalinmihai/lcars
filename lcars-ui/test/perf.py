#!/usr/bin/env python3
"""Frame budget for the journal UI: 60 fps at the 99th percentile.

The QuickJS suite (test/run.sh) proves what the page does; it has no layout and
no frames, so it cannot say how long anything takes. This boots the page in
headless Chromium against a stubbed API holding a synthetic journal the size of
the real one (and then some), drives each interaction one step per frame the
way a finger would, and traces it.

    python3 test/perf.py              # every scenario; exit 1 if any is over
    python3 test/perf.py scroll rail  # just those
    python3 test/perf.py --profile    # and the heaviest functions of each
    python3 test/perf.py --rows 6000  # a bigger journal
    python3 test/perf.py --throttle 4 # a CPU slowed 4x, to stand in for an
                                        old phone on a fast laptop
    python3 test/perf.py --jobs 1     # one scenario at a time
    python3 test/perf.py --base HEAD  # compare what is over with the last commit
    python3 test/perf.py --fresh      # measure the baseline again, kept numbers or not

What is measured, and why not frames per second. The budget is 16.7ms of the
renderer's main thread per frame: script, style, layout and paint — everything
this page's code decides. It is read from a Chrome trace as *thread CPU time*
(`tdur`) of the main thread's tasks, grouped into frames at each task that runs
the animation-frame callbacks (the recorder below keeps one in every frame).
Wall-clock frame intervals are printed too, but not judged: on the VPS
this runs on, the main thread shares the cores with the software rasterizer,
the GPU process, the browser, the Playwright driver and the other scenarios,
which a phone does not — so there an interval measures the box, not the page.
CPU time cares much less who else wanted the core (it is not immune: on the
one-core box the same frames cost 20-30% more, docs/ops/engineer-time.md).

Pass: in every scenario, the 99th-percentile frame's main-thread time is at
most FRAME_BUDGET_MS. A frame over it is a frame a phone drops. A scenario
over it is run three more times and judged by their median, and if that is
over too, against the same scenario on the baseline page (main's, by
default), run in turn with it: over budget but no slower than the baseline passes,
named as such, since the change under test did not do it (see "judging"
below). A scenario over budget that the change cannot reach (test/changed.py)
is not run again, and the baseline's numbers are reused where this box has
measured them (see "the comparison's cost"); the output says which. --once
judges one run by the budget alone.

Nothing here touches the real journal: every request is answered by serve().
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PAGE = (HERE.parent / "index.html").as_uri()
BASE = "https://lcars.test"     # the server the file:// page is pointed at (its lcars.cfg)

FRAME_BUDGET_MS = 1000 / 60                 # main-thread CPU per frame, at p99
PHONE = {"width": 390, "height": 844}       # an iPhone's viewport
DESKTOP = {"width": 1440, "height": 900}

# ---------- a synthetic journal ----------
# Shaped like the real one: dense recent years, a long sparse tail of imported
# daily journals back to 2020, a handful of kinds, bodies with markdown in them.
KINDS = ["personal_log", "work_log", "task", "sleep_log", "page", "idea",
         "logseq_journal", "wake_log"]
BODY = ("- Morning review of the [[LCARS UI]] plan and **arena sizing**\n"
        "  - follow up on `HTTP_MAX_BODY_BYTES` with a [link](https://example.com)\n"
        "- TODO water the plants #home\n"
        "> a quote that wraps over a couple of lines on a phone, to make rows tall\n")


def journal(n):
    rows, now = [], datetime.datetime(2026, 9, 25, 14, 0)
    for i in range(n):
        hours = i * 3 if i < n * 0.6 else n * 0.6 * 3 + (i - n * 0.6) * 26
        stamp = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        body = BODY * (1 + i % 4)
        rows.append({
            "id": n + 1000 - i, "kind": KINDS[i % len(KINDS)],
            "title": f"Entry {i} about arena sizing and the garden",
            "content": body, "content_length": len(body.encode()),
            "value_int": 0, "value_float": 6.5 if i % 8 == 3 else 0,
            "done_bool": 1 if i % 11 == 0 else 0, "deleted": 0,
            "created_at_utc": stamp, "last_modified_at_utc": stamp,
            "start_date": "", "end_date": "",
        })
    return rows


def embeddings(rows, dim=384, topics=24):
    """One int8 vector per row, base64, in the /embeddings shape: `topics`
    random directions, each row one of them plus noise - the cluster
    structure a real journal gives the star chart to find."""
    import base64
    import random
    rnd = random.Random(11)
    centres = [[rnd.gauss(0, 1) for _ in range(dim)] for _ in range(topics)]
    out = []
    for i, r in enumerate(rows):
        c = centres[i % topics]
        v = [c[t] + rnd.gauss(0, 0.9) for t in range(dim)]
        m = max(abs(x) for x in v) or 1
        q = bytes((int(round(x / m * 127)) & 255) for x in v)
        out.append([r["id"], base64.b64encode(q).decode()])
    return {"model": "perf@1", "dim": dim, "live": len(rows), "done": len(rows),
            "rows": out, "mark": "2026-09-25 14:00:00"}


_FIXTURES = {}


def serve(rows):
    # built once per journal, not once per scenario: the vectors alone are
    # 1.5M random draws, most of a second each time
    key = (len(rows), rows[0]["id"] if rows else 0)
    if key not in _FIXTURES:
        _FIXTURES[key] = ({r["id"]: r for r in rows}, embeddings(rows),
                          [{k: v for k, v in r.items() if k != "content"} for r in rows])
    by_id, emb, meta = _FIXTURES[key]

    def handle(route):
        url = route.request.url
        if route.request.method != "GET":
            return route.fulfill(json={"ok": True, "id": 1})
        if "/embeddings" in url:
            # everything once, nothing new after: a chart opened twice
            return route.fulfill(json=emb if "since=" not in url else dict(emb, rows=[]))
        if "/stats" in url:
            return route.fulfill(json={"count": len(rows),
                                       "newest_created_at_utc": rows[0]["created_at_utc"]})
        m = re.search(r"/entries/(\d+)(/media)?", url)
        if m:
            if m.group(2):
                return route.fulfill(json=[])
            hit = by_id.get(int(m.group(1)))
            return route.fulfill(json=hit) if hit else route.fulfill(status=404, json={})
        if "/entries" in url:
            q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&") if "=" in p)
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
            src = meta if q.get("content") == "0" else rows
            return route.fulfill(json=src[off:off + lim])
        # no /dump, no /kinds: the paged sweep an older server gets
        return route.fulfill(status=404, json={"error": "not found"})
    return handle


# ---------- the in-page frame recorder ----------
RECORDER = """
window.__perf = {
  gen: 0, t: [],
  // a scenario may restart the clock after its setup; the generation retires
  // the old loop, or two loops would log every frame twice
  start() {
    this.t = [];
    console.timeStamp("perf-start");      // the trace's window opens here
    const g = ++this.gen;
    const loop = ts => { if (g !== this.gen) return; this.t.push(ts); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  },
  stop() {
    this.gen++;
    console.timeStamp("perf-stop");
    const d = [];
    for (let i = 1; i < this.t.length; i++) d.push(this.t[i] - this.t[i - 1]);
    return d;
  },
};
"""


def stats(d, over):
    s = sorted(d)
    if not s:
        return {"frames": 0, "p50": 0, "p99": 0, "max": 0, "over": 0}
    pick = lambda q: s[min(len(s) - 1, int(q * len(s)))]
    return {"frames": len(s), "p50": pick(.5), "p99": pick(.99), "max": s[-1],
            "over": sum(1 for x in s if x > over)}


# RunTask is toplevel's; FireAnimationFrame and TimeStamp are devtools.timeline.
# The disabled-by-default detail (every layer and paint chunk) is left out: it
# made a ten-second scenario's trace too big to read back on the 2GB box the VPS was.
TRACE_CATS = ["toplevel", "devtools.timeline"]


KEEP = {"thread_name", "TimeStamp", "ThreadControllerImpl::RunTask", "FireAnimationFrame"}


class Trace:
    """A trace streamed over CDP, keeping only the events frame_work() reads.

    Streamed (transferMode ReportEvents) and filtered as it arrives rather than
    fetched whole at the end: a ten-second drag is tens of megabytes of trace,
    and reading that back in one piece failed on the 2GB box the VPS was."""

    def __init__(self, browser):
        self.cdp = browser.new_browser_cdp_session()
        self.events, self.done = [], False
        self.cdp.on("Tracing.dataCollected",
                    lambda m: self.events.extend(e for e in m["value"] if e.get("name") in KEEP))
        self.cdp.on("Tracing.tracingComplete", lambda m: setattr(self, "done", True))
        self.cdp.send("Tracing.start", {"transferMode": "ReportEvents",
                                        "traceConfig": {"includedCategories": TRACE_CATS}})

    def stop(self, page):
        self.cdp.send("Tracing.end")
        while not self.done:
            page.wait_for_timeout(50)
        return self.events


def frame_work(ev):
    """Main-thread CPU ms per frame, between the perf-start and perf-stop marks."""
    names = {(e["pid"], e["tid"]): e["args"]["name"] for e in ev
             if e.get("ph") == "M" and e.get("name") == "thread_name"}
    # the page's renderer: the main thread that saw the marks
    marks = [e for e in ev if e.get("name") == "TimeStamp"
             and str((e.get("args") or {}).get("data", {}).get("message", "")).startswith("perf-")]
    t0 = max((e["ts"] for e in marks if e["args"]["data"]["message"] == "perf-start"), default=None)
    t1 = max((e["ts"] for e in marks if e["args"]["data"]["message"] == "perf-stop"), default=None)
    if t0 is None or t1 is None:
        raise SystemExit("perf.py: the trace has no perf-start/perf-stop marks")
    main = next((e["pid"], e["tid"]) for e in marks)
    assert names.get(main, "CrRendererMain") == "CrRendererMain", names.get(main)
    on = lambda e: (e.get("pid"), e.get("tid")) == main
    # every top-level task on the thread (the bare "RunTask" twin of this only
    # appears with the verbose categories, nested inside it)
    tasks = sorted((e for e in ev if on(e) and e.get("name") == "ThreadControllerImpl::RunTask"
                    and e.get("ph") == "X"
                    and t0 <= e["ts"] <= t1), key=lambda e: e["ts"])
    raf = sorted(e["ts"] for e in ev if on(e) and e.get("name") == "FireAnimationFrame")
    # a frame opens at each task that runs animation-frame callbacks
    starts, j = [], 0
    for t in tasks:
        while j < len(raf) and raf[j] < t["ts"]:
            j += 1
        if j < len(raf) and raf[j] <= t["ts"] + t["dur"]:
            starts.append(t["ts"])
    frames, k = [], -1
    for t in tasks:
        while k + 1 < len(starts) and starts[k + 1] <= t["ts"]:
            k += 1
            frames.append(0.0)
        if k >= 0:
            frames[k] += t.get("tdur", t["dur"]) / 1000
    return frames[:-1] if len(frames) > 1 else frames    # the last one is cut off by the stop


# ---------- scenarios ----------
# Each one runs between __perf.start() and __perf.stop(); `page` is booted,
# with the journal fully loaded and the list at the top.

def s_idle(page):
    page.wait_for_timeout(3000)


def s_scroll(page):
    # a steady finger-speed scroll down through ~1500 rows' worth, then back
    page.evaluate("""() => new Promise(done => {
      const l = $("#list"); let n = 0;
      const step = () => {
        if (n++ < 360) { l.scrollTop += 90; requestAnimationFrame(step); } else done();
      };
      requestAnimationFrame(step);
    })""")


def s_scroll_up(page):
    # from a jump deep into the past, back up: the window filling its spacer
    page.evaluate("railGo(Math.floor(rail.groups.length * 0.7))")
    page.wait_for_timeout(300)
    page.evaluate("__perf.start()")     # the jump itself is s_rail's business
    page.evaluate("""() => new Promise(done => {
      const l = $("#list"); let n = 0;
      const step = () => {
        if (n++ < 300) { l.scrollTop -= 90; requestAnimationFrame(step); } else done();
      };
      requestAnimationFrame(step);
    })""")


def s_rail(page):
    # press on the rail and drag the whole length down and back, slowly enough
    # that the list follows month by month
    box = page.evaluate("(() => { const r = $('#rail').getBoundingClientRect();"
                        " return [r.left + r.width / 2, r.top, r.height]; })()")
    x, top, h = box
    page.mouse.move(x, top + 2)
    page.mouse.down()
    for y in list(range(0, int(h), 10)) + list(range(int(h), 0, -10)):
        page.mouse.move(x, top + y)
        page.wait_for_timeout(16)
    page.mouse.up()


def s_search(page):
    # type a query the way a person does, a key every 120ms, then clear it;
    # three of them, so the p99 is a percentile and not one unlucky frame
    page.click("#q")
    for query in ("arena garden", "entry 12", "sizing"):
        for ch in query:
            page.keyboard.type(ch)
            page.wait_for_timeout(120)
        page.wait_for_timeout(500)
        page.fill("#q", "")
        page.dispatch_event("#q", "input")
        page.wait_for_timeout(500)


def s_open(page):
    # j/k through the list with the reader open: an entry every 150ms
    page.evaluate("select(st.view[0].id)")
    page.wait_for_timeout(300)
    page.evaluate("__perf.start()")
    for _ in range(40):
        page.evaluate("move(1)")
        page.wait_for_timeout(150)


def s_morph(page):
    # the view transitions (docs/design/motion.md): a row tapped open, the
    # pane growing out of it; closed again (its row lit); a dialog swept
    # in and sunk away by Escape - the frames counted through the motion
    close = "#bBack" if page.viewport_size["width"] <= 820 else "#bClose"
    page.evaluate("__perf.start()")
    for i in range(6):
        page.click(f"#list .item >> nth={i % 4}")
        page.wait_for_timeout(350)
        page.click(close)
        page.wait_for_timeout(300)
    for _ in range(2):
        page.keyboard.press("p")
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)


def s_type(page):
    # typing into an open entry's body, a key every 80ms
    page.evaluate("st.read = false; select(st.view[0].id, true)")
    page.wait_for_timeout(400)
    page.click("#edbody")
    page.evaluate("__perf.start()")
    for ch in "the quick brown fox jumps over the lazy dog ":
        page.keyboard.type(ch)
        page.wait_for_timeout(80)


def s_palette(page):
    # open, type, close — four times, the first of which is the cold one
    for query in ("view log", "sort len", "kind task", "alog"):
        page.keyboard.press("p")
        page.wait_for_timeout(200)
        for ch in query:
            page.keyboard.type(ch)
            page.wait_for_timeout(120)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)


def s_stars_chart(page):
    # the star chart laid out from scratch over the whole journal: the layout
    # works a slice a frame, and the half-settled stars are drawn every frame
    page.evaluate("openStars()")
    page.wait_for_function("sc.job", timeout=60000)
    page.evaluate("__perf.start()")
    t0 = page.evaluate("performance.now()")
    page.wait_for_function("!sc.job && sc.lay && sc.lay.labels.length", timeout=120000,
                           polling=100)
    ms = page.evaluate("performance.now()") - t0
    NOTES.append(f"       charting {page.evaluate('sc.lay.ids.length')} stars took {ms / 1000:.1f}s "
                 f"into {page.evaluate('sc.lay.labels.length')} constellations")


def s_stars_pan(page):
    # a finger dragging the finished chart about, then pinch-free zooming
    page.evaluate("openStars()")
    page.wait_for_function("!sc.job && sc.lay && sc.lay.labels.length", timeout=120000,
                           polling=100)
    page.wait_for_timeout(300)
    page.evaluate("__perf.start()")
    page.evaluate("""() => new Promise(done => {
      let n = 0;
      const step = () => {
        if (n < 120) { sc.tx += n < 60 ? 6 : -6; sc.ty += 3 * Math.sin(n / 9); starDraw(); }
        else if (n < 200) starZoom(n < 160 ? 1.04 : 1 / 1.04, sc.w / 2, sc.h / 2);
        else return done();
        n++;
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    })""")


def s_course_zoom_setup(page):
    # the course map with stops and places heaped on a few spots, zoomed out
    # (the stops overlap and are spread, crsSpread; the places stay on their
    # spot) and in again, then panned: the stops are measured again at every
    # zoomend and moveend.
    # 40 places and 13 stops: Leaflet's own zoom costs ~12ms here plus
    # ~0.06ms a marker, spread or not, and is over budget by itself from
    # about 90 markers (TODO.md). Nothing leaves the machine: tiles,
    # routing and the weather are refused.
    page.route(re.compile(r"^https?://(?!lcars\.test/)"), lambda r: r.abort())
    page.evaluate("""() => {
      const pts = [];
      for (let i = 0; i < 12; i++)
        pts.push({ name: "P" + i, lat: 45.6 + (i % 4) * 0.0004, lon: 25.5 + (i >> 2) * 0.0004, stay: 0 });
      pts.push(Object.assign({}, pts[0], { name: "back" }));
      crsOpen({ id: 987654, kind: "trip", title: "perf", deleted: 0,
                content: JSON.stringify({ v: 1, depart: "2026-10-12T08:00", points: pts,
                                          legs: pts.slice(1).map(() => ({ mode: "foot_hiking" })) }) });
    }""")
    page.wait_for_function("crs.map && crs.map._loaded && crsPoiS.layer", timeout=30000)
    page.evaluate("""() => {
      crsPoiS.on.clear();
      const found = [];
      for (let i = 0; i < 40; i++)
        found.push({ lat: 45.6 + (i % 7) * 0.0003 + (i % 3) * 0.00001, lon: 25.5 + (i % 5) * 0.0003,
                     name: "place " + i, c: CRS_POI[i % CRS_POI.length] });
      crsPoiDraw(found);
      crs.map.setView([45.6006, 25.5006], 15, { animate: false });
    }""")
    page.wait_for_timeout(500)


def s_course_zoom(page):
    s_course_zoom_setup(page)
    NOTES.append("       %d markers, %d spread at zoom 15" % tuple(page.evaluate(
        "[document.querySelectorAll('.leaflet-marker-icon').length,"
        " [crs.marks, crsPoiS.layer].flatMap(l => l.getLayers()).filter(m => m._crsOff).length]")))
    page.evaluate("__perf.start()")
    # Counted in frames, not timed: Leaflet's animated zoom runs on the clock
    # (a CSS transition and a 250ms timer), so on a loaded box a run had
    # 130-250 frames, a different mix each time, and its p99 was noise. Each
    # step is a pinch instead, the way TouchZoom moves the map under a
    # finger: PINCH frames at fractional zooms (every marker placed again
    # each frame), then the snap to the whole zoom (_resetView, zoomend: the
    # spread measured again) and SETTLE frames before the next. The heavy
    # frames are the snaps and the spreads, two a step, so p99 is an order
    # statistic of those: 12 steps made it the 3rd worst of 24, which
    # swung 17-25ms on the same page. The round three times, then 20 pans:
    # 668 frames every run, p99 the 7th worst of 72.
    page.evaluate("""() => new Promise(done => {
      const map = crs.map, ZS = [14, 13, 12, 13, 14, 15, 16, 17, 18, 17, 16, 15];
      const zs = ZS.concat(ZS, ZS), PINCH = 8, SETTLE = 10, c = map.getCenter();
      let k = 0, f = 0, z0 = map.getZoom();
      const step = () => {
        if (k < zs.length) {
          if (f < PINCH) map._move(c, z0 + (zs[k] - z0) * (f + 1) / (PINCH + 1), { pinch: true, round: false });
          else if (f === PINCH) map.setView(c, zs[k], { animate: false });
          if (++f === PINCH + SETTLE) { z0 = zs[k++]; f = 0; }
        } else if (f < 20) { f++; map.panBy([f % 2 ? 60 : -60, 25], { animate: false }); }
        else return done();
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    })""")


def s_course_turn(page):
    # the same map turning heading-up (crsTurn) after a compass that swings
    # round 6 degrees a frame: every frame turns the tiles and lines, and
    # moves every upright marker and the spread (crsSpread)
    s_course_zoom_setup(page)
    page.evaluate("__perf.start()")
    page.evaluate("""() => new Promise(done => {
      meLoc.on = true; crs.north = crs.free = false;
      let k = 0;
      const step = () => {
        if (k++ > 150) { meLoc.on = false; meLoc.head = null; return done(); }
        meLoc.head = (k * 6) % 360;
        crsTurnSoon();
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    })""")


NOTES = []      # a scenario's own lines, printed before its result

def s_chat_thread(page):
    # a 200-message thread: opened, scrolled through and back, then an
    # answer streamed into its end a few words a frame, as /chat does
    page.evaluate("""() => {
      const md = i => 'Here is **what you logged** on day ' + i + ':\\n\\n- a run of ' + (i % 9 + 2) + ' km (#' + (1000 + i) +
        ')\\n- `lcars-cli` found ' + i + ' rows\\n\\n| kind | n |\\n|---|---|\\n| run | ' + i + ' |\\n\\nAnd a closing sentence, a little longer.';
      chat.msgs = [];
      // a third of the questions carry a grid of pictures (chat-dock.md 2.9):
      // three 1200x900 photos each, one picture behind them all
      const cv = document.createElement('canvas'); cv.width = 1200; cv.height = 900;
      const cx = cv.getContext('2d'), gr = cx.createLinearGradient(0, 0, 1200, 900);
      gr.addColorStop(0, '#f90'); gr.addColorStop(1, '#39f'); cx.fillStyle = gr; cx.fillRect(0, 0, 1200, 900);
      const pic = cv.toDataURL('image/jpeg', 0.8);
      const grid = i => [0, 1, 2].map(k => ({ name: 'IMG_' + i + k + '.jpg', mime: 'image/jpeg', bytes: 2400000, state: 'done',
                                               path: 'media/chat/2026/10/p' + i + k + '.jpg', url: pic }));
      for (let i = 0; i < 100; i++) {
        chat.msgs.push(Object.assign({ role: 'user', text: 'what did I do on day ' + i + '?' }, i % 3 ? {} : { files: grid(i) }));
        chat.msgs.push({ role: 'asst', parts: [{ t: 'text', s: 'Let me look.' },
          { t: 'tool', id: 't' + i, name: 'Bash', input: { command: 'lcars-cli search day ' + i }, state: 'ok' },
          { t: 'text', s: md(i) }], meta: 'claude-sonnet-5 · 4.2s · $0.012' });
      }
      openChat();
    }""")
    page.wait_for_timeout(600)
    page.evaluate("__perf.start()")
    page.evaluate("""() => new Promise(done => {
      const l = document.querySelector('.chth .chlog') || document.querySelector('#chatlog');
      l.scrollTop = 0; let n = 0;
      const step = () => {
        if (n++ < 240) { l.scrollTop += n <= 120 ? 160 : -160; requestAnimationFrame(step); } else done();
      };
      requestAnimationFrame(step);
    })""")
    page.evaluate("""() => new Promise(done => {
      const l = document.querySelector('.chth .chlog') || document.querySelector('#chatlog');
      l.scrollTop = l.scrollHeight;
      chat.msgs.push({ role: 'user', text: 'and the whole month?' });
      const m = { role: 'asst', parts: [], live: true };
      chat.msgs.push(m); chat.busy = true;
      chatEvent(m, { type: 'stream_event', event: { type: 'content_block_start', content_block: { type: 'text', text: '' } } });
      let n = 0;
      const step = () => {
        if (n++ < 300) {
          for (let k = 0; k < 3; k++)
            chatEvent(m, { type: 'stream_event', event: { type: 'content_block_delta',
                           delta: { type: 'text_delta', text: (n % 40 ? 'word ' : '\\n\\n- a point ') } } });
          chatPaint(); requestAnimationFrame(step);
        } else { m.live = false; chat.busy = false; chatPaint(); done(); }
      };
      requestAnimationFrame(step);
    })""")


def s_eng_thread(page):
    # an engineer's 200-message transcript on screen, a poll's worth of new
    # lines folded in and drawn every frame (deb's page had no such thread:
    # there it only waits)
    if not page.evaluate("typeof engThread === 'function'"):
        page.wait_for_timeout(4000)
        return
    page.evaluate("""() => {
      const t = engThread('perf-a1b', 'Lieutenant Perf'), evs = [];
      for (let i = 0; i < 100; i++) {
        evs.push({ r: 'me', t: 'change number ' + i + ', please' });
        evs.push({ r: 'tool', t: 'Read lcars-ui/index.html' }, { r: 'tool', t: '$ make check' });
        evs.push({ r: 'text', t: 'Done: **change ' + i + '** is in, built clean.\\n\\n- the list\\n- the thread\\n\\n`run.sh` passed.' });
      }
      engFold(t.eng, evs);
      t.eng.off = 1; t.eng.st = { status: 'working' };
      chatsOpen(t.id);
      engStop();          // no server here: the frames below are the poll's
    }""")
    page.wait_for_timeout(600)
    page.evaluate("__perf.start()")
    page.evaluate("""() => new Promise(done => {
      const l = document.querySelector('.chth .chlog'); l.scrollTop = 0; let n = 0;
      const step = () => {
        if (n++ < 240) { l.scrollTop += n <= 120 ? 160 : -160; requestAnimationFrame(step); } else done();
      };
      requestAnimationFrame(step);
    })""")
    page.evaluate("""() => new Promise(done => {
      const t = chat, l = document.querySelector('.chth .chlog'); l.scrollTop = l.scrollHeight; let n = 0;
      const step = () => {
        if (n++ < 200) {
          engFold(t.eng, n % 5 ? [{ r: 'text', t: 'a line ' + n }] : [{ r: 'tool', t: '$ step ' + n }]);
          chatDraw(); requestAnimationFrame(step);
        } else done();
      };
      requestAnimationFrame(step);
    })""")


# the chat dock (docs/design/chat-dock.md 1.11): three windows up at a desk -
# two computer threads of 200 messages and an engineer's 200-message
# transcript. deb's page before the dock has none: there only the page part runs.
DOCK_SETUP = """() => {
  if (typeof dockOpen !== 'function' || !dockAllowed()) return false;
  const md = i => 'Here is **what you logged** on day ' + i + ':\\n\\n- a run of ' + (i % 9 + 2) + ' km (#' + (1000 + i) +
    ')\\n- `lcars-cli` found ' + i + ' rows\\n\\nAnd a closing sentence, a little longer.';
  const mk = () => {
    const t = chatNewThread();
    for (let i = 0; i < 100; i++) {
      t.msgs.push({ role: 'user', text: 'what did I do on day ' + i + '?' });
      t.msgs.push({ role: 'asst', parts: [{ t: 'text', s: 'Let me look.' },
        { t: 'tool', id: 't' + i, name: 'Bash', input: { command: 'lcars-cli search day ' + i }, state: 'ok' },
        { t: 'text', s: md(i) }], meta: 'claude-sonnet-5 · 4.2s · $0.012' });
    }
    t.at = Date.now();
    return t;
  };
  const a = mk(), b = mk(), e = engThread('perf-a1b', 'Lieutenant Perf'), evs = [];
  for (let i = 0; i < 100; i++) {
    evs.push({ r: 'me', t: 'change number ' + i + ', please' });
    evs.push({ r: 'text', t: 'Done: **change ' + i + '** is in, built clean.\\n\\n- the list\\n- the thread' });
  }
  engFold(e.eng, evs);
  e.eng.off = 1; e.eng.st = { status: 'working' };
  dock.wins = [{ id: a.id, min: false }, { id: b.id, min: false }, { id: e.id, min: false }];
  dock.focus = [a.id, b.id, e.id];
  dockSave(); dockSync(); dockRender();
  engStop();          // no server here: the frames below are the polls'
  window.__dock = { a, b, e };
  return document.querySelectorAll('#dock .dkwin').length;
}"""

PAGE_SCROLL = """() => new Promise(done => {
  const l = $("#list"); let n = 0;
  const step = () => {
    if (n++ < 360) { l.scrollTop += 90; requestAnimationFrame(step); } else done();
  };
  requestAnimationFrame(step);
})"""


def s_dock_stream(page):
    # 300 deltas into each computer window, interleaved, the engineer's
    # repainted by three polls, and the page under the dock scrolled
    n = page.evaluate(DOCK_SETUP)
    NOTES.append("       dock windows up: %s" % (n or "none (no dock on this page)"))
    page.wait_for_timeout(600)
    page.evaluate("__perf.start()")
    page.evaluate("""() => new Promise(done => {
      const l = $("#list"), d = window.__dock;
      const ms = d ? [d.a, d.b].map(t => {
        t.msgs.push({ role: 'user', text: 'and the whole month?' });
        const m = { role: 'asst', parts: [], live: true };
        t.msgs.push(m); t.busy = true;
        chatEvent(m, { type: 'stream_event', event: { type: 'content_block_start', content_block: { type: 'text', text: '' } } }, t);
        return [t, m];
      }) : [];
      let n = 0;
      const step = () => {
        if (n++ < 300) {
          for (const [t, m] of ms) {
            for (let k = 0; k < 3; k++)
              chatEvent(m, { type: 'stream_event', event: { type: 'content_block_delta',
                             delta: { type: 'text_delta', text: (n % 40 ? 'word ' : '\\n\\n- a point ') } } }, t);
            chatPaint(t);
          }
          if (d && n % 100 === 50) { engFold(d.e.eng, [{ r: 'text', t: 'a line ' + n }, { r: 'tool', t: '$ step ' + n }]); chatDraw(d.e); dockPaint(); }
          l.scrollTop += n <= 150 ? 60 : -60;
          requestAnimationFrame(step);
        } else {
          for (const [t, m] of ms) { m.live = false; t.busy = false; chatPaint(t); }
          done();
        }
      };
      requestAnimationFrame(step);
    })""")


def s_dock_scroll(page):
    # the scroll scenario with the three windows up and idle: the dock's
    # layer must not be repainted by it
    n = page.evaluate(DOCK_SETUP)
    NOTES.append("       dock windows up: %s" % (n or "none (no dock on this page)"))
    page.wait_for_timeout(600)
    page.evaluate("__perf.start()")
    page.evaluate(PAGE_SCROLL)


SCENARIOS = [
    ("idle", s_idle, PHONE),
    ("idle-desktop", s_idle, DESKTOP),     # the ambient animations, at rest
    ("scroll", s_scroll, PHONE),
    ("scroll-up", s_scroll_up, PHONE),
    ("rail", s_rail, PHONE),
    ("search", s_search, PHONE),
    ("open", s_open, PHONE),
    ("morph", s_morph, PHONE),
    ("morph-desktop", s_morph, DESKTOP),
    ("type", s_type, PHONE),
    ("palette", s_palette, DESKTOP),
    ("scroll-desktop", s_scroll, DESKTOP),
    ("stars-chart", s_stars_chart, PHONE),
    ("stars-pan", s_stars_pan, PHONE),
    ("course-zoom", s_course_zoom, PHONE),
    ("course-turn", s_course_turn, PHONE),
    ("chat-thread", s_chat_thread, PHONE),
    ("eng-thread", s_eng_thread, PHONE),
    ("dock-stream", s_dock_stream, DESKTOP),
    ("dock-scroll", s_dock_scroll, DESKTOP),
]


def hot(prof, top=12):
    """Self time per function over the scenario, heaviest first."""
    nodes = {n["id"]: n["callFrame"] for n in prof["nodes"]}
    acc = {}
    for sid, dt in zip(prof["samples"], prof["timeDeltas"]):
        f = nodes[sid]
        k = f"{f['functionName'] or '(anonymous)'}:{f['lineNumber'] + 1}"
        acc[k] = acc.get(k, 0) + dt / 1000
    return sorted(acc.items(), key=lambda kv: -kv[1])[:top]


def run(p, name, fn, viewport, rows, throttle, profile=False, url=PAGE):
    browser = p.chromium.launch(headless=True)
    try:
        ctx = browser.new_context(viewport=viewport, has_touch=viewport is PHONE,
                                  is_mobile=viewport is PHONE)
        ctx.route(BASE + "/**", serve(rows))
        ctx.add_init_script(
            "localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));"
            % BASE + RECORDER)
        page = ctx.new_page()
        if throttle > 1:
            ctx.new_cdp_session(page).send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        page.goto(url)
        page.wait_for_function("st.all.length >= %d && !st.loading && !st.bodies" % len(rows),
                               timeout=120000)
        page.wait_for_timeout(1000)          # the boot's own tail (heatmap, sync)
        cdp = ctx.new_cdp_session(page)
        if profile:
            cdp.send("Profiler.enable")
            cdp.send("Profiler.setSamplingInterval", {"interval": 200})
            cdp.send("Profiler.start")
        trace = Trace(browser)
        page.evaluate("__perf.start()")
        del NOTES[:]
        fn(page)
        wall = page.evaluate("__perf.stop()")
        work = frame_work(trace.stop(page))
        r = stats(work, FRAME_BUDGET_MS)
        r["wall"] = stats(wall, 1000 / 60 * 1.5)
        r["work"] = work
        r["nodes"] = page.evaluate("document.getElementsByTagName('*').length")
        r["notes"] = list(NOTES)
        if profile:
            r["hot"] = hot(cdp.send("Profiler.stop")["profile"])
        return r
    finally:
        browser.close()


def one(job):
    """A scenario in a process of its own (--jobs): its own driver, its own
    Chromium, the same journal (journal() is deterministic)."""
    name, nrows, throttle, profile, url = job
    fn, vp = next((f, v) for n, f, v in SCENARIOS if n == name)
    with sync_playwright() as p:
        return run(p, name, fn, vp, journal(nrows), throttle, profile, url)


# ---------- judging: the box's noise, and a baseline ----------
# One run's p99 is about the 4th-worst of 300 frames, and on the VPS
# the heaviest frames of scroll-up, scroll-desktop and course-zoom (a window
# of rows going in above, Leaflet's zoom) cost 14-20ms of CPU run to run on
# one core, 12-19 on four, on the very same page: memory pressure, swap and whatever else the box is
# doing move them all together. The budget line runs through that spread, so
# an unchanged page failed most runs and every engineer had to prove it was
# not theirs. Two things keep the verdict about the page:
#
# - a scenario over budget is run REPEAT more times and judged by the median
#   of their p99s: one unlucky run does not fail it (and the run that was
#   over is not counted, being picked for coming out high);
# - between those runs the same scenario runs REPEAT times on the baseline
#   page (lcars-ui/ as committed at the merge-base with main, where an
#   engineer's work lands; --base or PERF_BASE to choose), so both see the
#   same box. Over budget, and no slower than the baseline by more than
#   SLOWER and SLOWER_MS, passes and is named as over on the baseline too:
#   that is not this change's doing (TODO.md tracks those). Slower fails.
#
# The budget itself is not raised: a scenario in it on the baseline fails as
# soon as a change takes it over, by the median of three; and where every
# scenario is in budget with room (a laptop), nothing is run twice.
REPEAT = 3
# The page against itself (6 runs of each of the three, every split into 3
# and 3, VPS, 2026-10-11): medians of p99 differed by up to 14%; through
# this very comparison (--compare --base HEAD), scroll-up and scroll-desktop
# by up to 7%. A change must cost more than that and a millisecond more to
# be blamed - on a 17ms scenario, about 21%.
SLOWER = 1.15
SLOWER_MS = 1.0
INVALID = float("inf")      # a run that measured nothing (frames < 20)


def score(r):
    return r["p99"] if r["frames"] >= 20 else INVALID


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


def base_ref(ref):
    """The baseline commit: (label, sha), or (why not, None)."""
    import subprocess
    root = HERE.parent.parent
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    for want in ([ref] if ref else ["main", "origin/main", "HEAD"]):
        mb = git("merge-base", "HEAD", want)
        if mb.returncode == 0:
            break
    else:
        return f"no baseline: {ref or 'main'} is not a commit here", None
    sha = mb.stdout.strip()
    return (want if git("rev-parse", want).stdout.strip() == sha else f"{want} ({sha[:8]})"), sha


def base_page(sha):
    """lcars-ui/ at sha, unpacked into a temp dir: (the index.html url, the
    dir), or (None, why not)."""
    import shutil
    import subprocess
    import killclean  # its scratch goes when the run is killed
    root = HERE.parent.parent
    d = killclean.mkdtemp(prefix="lcars-perf-base-")
    arc = subprocess.Popen(["git", "-C", str(root), "archive", sha, "lcars-ui"], stdout=subprocess.PIPE)
    ok = subprocess.run(["tar", "-x", "-C", d, "--exclude", "lcars-ui/test"], stdin=arc.stdout).returncode == 0
    arc.stdout.close()
    if arc.wait() != 0 or not ok:
        shutil.rmtree(d, ignore_errors=True)
        return None, f"no baseline: git archive {sha[:8]} failed"
    return (pathlib.Path(d) / "lcars-ui" / "index.html").as_uri(), d


# ---------- the comparison's cost: what need not be run again ----------
# A scenario over budget costs REPEAT runs of the page and REPEAT of the
# baseline, ~3 minutes on the one-core VPS (~1 on 4 cores); course-zoom was over on deb
# every run, and scroll-up, scroll-desktop and eng-thread often, so half a
# full run's perf could be comparisons (docs/ops/engineer-time.md). Two
# things are not run again, and the output says which:
#
# - a scenario this change cannot reach, by test/changed.py's map from the
#   page's sections to the scenarios (the same map as run.sh --changed): it
#   is over budget on the baseline's code, not this change's, so it is
#   named as such and not judged. One the change can reach is always run
#   again, page and baseline, and judged as before.
# - the baseline's own numbers, when this box has measured that same
#   baseline (lcars-ui/'s tree at the commit), with this perf.py, journal
#   size, throttle, Chromium and core count, in the last BASE_KEEP_DAYS:
#   then only the page runs again. The ABBA order is lost for those - the
#   baseline was measured at another time - so the reused numbers are said
#   with their age; --fresh (PERF_FRESH=1) measures both again.
BASE_CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache") / "lcars-perf" / "baseline.json"
BASE_KEEP_DAYS = 7


def reachable(ref):
    """The scenarios the change against ref can reach (test/changed.py), or
    None for all of them (or when that cannot be told)."""
    try:
        sys.path.insert(0, str(HERE))
        import changed
        _, ch = changed.worktree_changes(ref or "main")
        st, only, _, _ = changed.select(ch, (HERE.parent / "index.html").read_text(encoding="utf-8").split("\n"))
    except Exception:  # noqa: BLE001 - no git, no main: every scenario is reachable
        return None
    if not st["perf"]:
        return set()
    return set(only) if only else None


def base_key(sha, rows, throttle):
    import hashlib
    import importlib.metadata
    import subprocess
    tree = subprocess.run(["git", "-C", str(HERE.parent.parent), "rev-parse", f"{sha}:lcars-ui"],
                          capture_output=True, text=True).stdout.strip()
    if not tree:
        return None
    me = hashlib.sha1(pathlib.Path(__file__).read_bytes()).hexdigest()[:12]
    return f"{tree}/perf {me}/rows {rows}/throttle {throttle}/playwright {importlib.metadata.version('playwright')}" \
           f"/{os.cpu_count()} cores/{os.uname().nodename}"


def base_cache():
    try:
        c = json.loads(BASE_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    now = datetime.datetime.now().timestamp()
    return {k: v for k, v in c.items() if now - v.get("at", 0) < BASE_KEEP_DAYS * 86400}


def base_known(key, name):
    """(the baseline's kept scores of scenario name, when) or None"""
    e = base_cache().get(key) if key else None
    runs = (e or {}).get("runs", {}).get(name)
    return (runs, e["runs_at"][name]) if runs and len(runs) >= REPEAT else None


def base_keep(key, name, scores):
    if not key or not scores or INVALID in scores:
        return
    c = base_cache()
    e = c.setdefault(key, {"runs": {}, "runs_at": {}})
    now = datetime.datetime.now().timestamp()
    e["at"], e["runs"][name], e["runs_at"][name] = now, scores, now
    try:
        BASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BASE_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(c))
        tmp.replace(BASE_CACHE)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*")
    ap.add_argument("--rows", type=int, default=4000)
    ap.add_argument("--throttle", type=float, default=1)
    # Scenarios at once, each in its own Chromium. What is judged is main-
    # thread CPU time, which other processes on other cores do not add to: 4
    # at once gave p99s inside the spread of two sequential runs, and the same
    # frame counts. Two cores a scenario: the 4-core VPS runs two at a time.
    ap.add_argument("--jobs", type=int, default=max(1, min(4, (os.cpu_count() or 1) // 2)),
                    help="scenarios run at once, each in its own Chromium (default: cores/2, at most 4)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--profile", action="store_true",
                    help="print each scenario's heaviest functions (line = index.html's script)")
    ap.add_argument("--base", default=os.environ.get("PERF_BASE", ""),
                    help="the commit a scenario over budget is compared with (default: the merge-base "
                         "with main); 'none' judges by the budget alone")
    ap.add_argument("--compare", action="store_true",
                    help="judge every scenario as if it were over budget: repeats and the baseline "
                         "(to see the comparison itself, or the noise of a page against itself)")
    ap.add_argument("--once", action="store_true",
                    help="one run a scenario, judged by the budget alone (no repeats, no baseline)")
    ap.add_argument("--fresh", action="store_true", default=os.environ.get("PERF_FRESH") == "1",
                    help="measure the baseline again even when its numbers are kept, and rerun a scenario "
                         "over budget even when this change cannot reach it (PERF_FRESH=1)")
    a = ap.parse_args()
    rows = journal(a.rows)
    picked = [s for s in SCENARIOS if not a.only or s[0] in a.only]
    out, over, excused, unreached = {}, [], [], []

    def measure(jobs, profile=False):
        """[(scenario, page url)] -> their results, in that order."""
        if a.jobs > 1 and len(jobs) > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(min(a.jobs, len(jobs))) as pool:
                return list(pool.map(one, [(n, a.rows, a.throttle, profile, u) for n, u in jobs]))
        res = []
        with sync_playwright() as p:
            for n, u in jobs:
                fn, vp = next((f, v) for m, f, v in SCENARIOS if m == n)
                res.append(run(p, n, fn, vp, rows, a.throttle, profile, u))
        return res

    def line(name, r, verdict):
        wl = r["wall"]
        print(f"{verdict:4s} {name:15s} frames={r['frames']:4d} "
              f"main-thread p50={r['p50']:5.1f} p99={r['p99']:6.1f} max={r['max']:6.1f}ms "
              f"over={r['over']} elements={r['nodes']}  |  wall p99={wl['p99']:5.1f} dropped={wl['over']}",
              flush=True)

    first = measure([(n, PAGE) for n, _, _ in picked], a.profile)
    again = []
    for (name, _, _), r in zip(picked, first):
        out[name] = r
        for ln in r.get("notes", []):
            print(ln, flush=True)
        # a scenario that measured nothing has proved nothing
        bad = score(r) > FRAME_BUDGET_MS
        line(name, r, ("OVER" if a.once else "over") if bad else "ok")
        for fnm, ms in r.get("hot", []):
            print(f"       {ms:8.1f}ms  {fnm}")
        if bad and a.once:
            over.append(name)
        elif bad or a.compare:
            again.append(name)

    base, tmp, key, label, kept = None, None, None, "no baseline (--base none)", {}
    if again:
        sha = None
        if a.base != "none":
            label, sha = base_ref(a.base)
        if sha and not a.compare and not a.fresh:
            reach = reachable(a.base)
            unreached = [n for n in again if reach is not None and n not in reach]
            again = [n for n in again if n not in unreached]
            key = base_key(sha, a.rows, a.throttle)
            kept = {n: k for n in again if (k := base_known(key, n))}
        elif sha:
            key = base_key(sha, a.rows, a.throttle)
        for n in unreached:
            print(f"ok   {n:15s} p99 {score(out[n]):.1f}ms, over budget once; this change does not reach it "
                  f"(test/changed.py): not run again, not judged", flush=True)
        if sha and any(n not in kept for n in again):
            base, tmp = base_page(sha)
            if not base:
                label = tmp
                tmp = None
        if again:
            said = []
            if kept:
                said.append(f"{label}'s numbers kept for {', '.join(kept)}")
            if base and any(n not in kept for n in again):
                said.append(f"against {label}'s page run as often, in turn")
            print(f"again: {', '.join(again)}{'' if a.compare else ' over budget once'}; {REPEAT} more runs each, judged by the median"
                  + (", " + "; ".join(said) if said else f" ({label})"), flush=True)
    try:
        for name in again:
            # REPEAT fresh runs of each, page and baseline in the order
            # ABBA ABBA..., so neither always runs first, right after the
            # other's Chromium has gone, and a box that slows down or speeds
            # up over the minutes this takes moves both the same way. The
            # first run is not one of them: it is here because it came out
            # high, and counting it put the page above itself (an unchanged
            # page was once judged 43% slower than deb). With the
            # baseline's numbers kept, only the page runs.
            known = kept.get(name)
            order = [(PAGE, base), (base, PAGE)] if base and not known else [(PAGE,)]
            jobs = [(name, u) for k in range(REPEAT) for u in order[k % len(order)]]
            res = measure(jobs)
            mine_r = [r for (_, u), r in zip(jobs, res) if u == PAGE]
            theirs_s = [score(r) for (_, u), r in zip(jobs, res) if u != PAGE]
            if theirs_s:
                base_keep(key, name, theirs_s)
            mine = median([score(r) for r in mine_r])
            ps = " ".join(f"{score(r):.1f}" for r in mine_r)
            src = ""
            if known:
                theirs_s = known[0]
                age = (datetime.datetime.now().timestamp() - known[1]) / 3600
                src = f", kept from {age:.0f}h ago" if age >= 1 else f", kept from {age * 60:.0f}min ago"
            out[name] = dict(out[name], first=score(out[name]), runs=[score(r) for r in mine_r],
                             base=theirs_s, base_kept=bool(known))
            theirs = median(theirs_s) if theirs_s else None
            bs = " ".join(f"{x:.1f}" for x in theirs_s) + src
            if mine <= FRAME_BUDGET_MS:
                print(f"ok   {name:15s} p99 median {mine:.1f}ms of {ps}: in budget"
                      + (f" ({label} {theirs:.1f}ms of {bs})" if theirs_s else ""), flush=True)
                continue
            if theirs is None:
                print(f"OVER {name:15s} p99 median {mine:.1f}ms of {ps}", flush=True)
                over.append(name)
                continue
            if mine <= theirs * SLOWER + SLOWER_MS:
                print(f"ok   {name:15s} p99 median {mine:.1f}ms of {ps}: over budget, as on {label} "
                      f"({theirs:.1f}ms of {bs}): not this change", flush=True)
                excused.append(name)
            else:
                print(f"OVER {name:15s} p99 median {mine:.1f}ms of {ps}: slower than {label} "
                      f"({theirs:.1f}ms of {bs}) by {(mine / theirs - 1) * 100:.0f}%", flush=True)
                over.append(name)
    finally:
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    print(f"budget: p99 main-thread <= {FRAME_BUDGET_MS:.1f}ms per frame"
          + (f"; over it on {label} as well, so not judged by it: {', '.join(excused)}" if excused else "")
          + (f"; over it once and not reached by this change, so not judged: {', '.join(unreached)}"
             if unreached else ""))
    print("RESULT:", "FAIL (" + ", ".join(over) + ")" if over else "PASS")
    sys.exit(1 if over else 0)


if __name__ == "__main__":
    main()
