#!/usr/bin/env python3
"""Films the LCARS journal UI — a front-page demo reel.

Drives index.html in headless Chromium against a stubbed API (demo/fixture.py),
records the screen, and lays a title card, lower-third captions and a visible
cursor over the top of it. Output is a webm; build.sh turns that into the mp4
you would upload.

    python3 demo/demo.py                 # the whole reel -> demo/out/
    python3 demo/demo.py --fast          # same cuts, 2.5x, for iterating
    python3 demo/demo.py --only graph    # one scene, to work on its timing
    python3 demo/demo.py --list          # what the scenes are called

The cursor is not Chromium's — headless has none to record. Every move drives
the real mouse (so the app's own hover states fire) and draws a reticle at the
same point, so what you see is the pointer the app is actually reacting to.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fixture
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PAGE = (HERE.parent / "index.html").as_uri()
ASSETS = HERE / "assets"

# The same face index.html asks for, kept locally so a take never depends on
# the network. Antonio is a variable font, so one file covers 400/600/700.
FONT_CSS = """
@font-face {
  font-family: 'Antonio';
  font-style: normal;
  font-weight: 100 900;
  font-display: block;
  src: url('%s') format('woff2');
}
""" % (ASSETS / "antonio-latin.woff2").as_uri()
OUT = HERE / "out"
BASE = "https://lcars.test"    # the server the file:// page is pointed at (its lcars.cfg)

# The app is filmed at 1280x720 and the finished video is 1920x1080, so every
# element lands 1.5x larger in the frame than it would at native 1080p. That is
# the whole point: at 1920 the journal's 14px body text is four or five pixels
# tall on a phone screen and unreadable. The cost is one upscale, and because
# the page is rendered at device_scale_factor 2 — 2560x1440 — and downsampled
# to 1280 before it goes back up, the text survives it well.
#
# 1280 is also comfortably clear of index.html's 1100px breakpoint, so this is
# still the desktop layout and not the tablet one.
W, H = 1280, 720
FINAL_W, FINAL_H = 1920, 1080

# The overlay is authored against a 1920-wide canvas. Rendering it on a
# narrower one and scaling it to fit makes every caption and card
# proportionally larger in the frame: the effective size ends up
# 41px * 1920 / DZ_CANVAS. 1600 gives about a 1.2x lift over the original,
# which is readable on a phone without the lower third eating the picture.
DZ_CANVAS = 1600
DZ_K = W / DZ_CANVAS

# How long the clapperboard holds white at the first paint, in ms. Long enough
# that a screencast starting a frame or two late still catches it; short enough
# to sit well inside the boot black that gets trimmed.
CLAP_MS = 260

# The app asks for a sound at 69 call sites and never makes one here — headless
# Chromium has no audio device, and the AudioContext stays suspended. What it
# does do is call sfx(), so the reel's soundtrack is recovered by writing down
# every one of those asks and rendering them afterwards (see demo/sound.py).
#
# The hook goes in after the app has booted, not as an init script: sfx is a
# plain function declaration, so the page's own definition would land on top of
# anything installed earlier.
# sndPlay, not sfx: sfx() is the *ask*, and a single gesture makes several of
# them. What actually sounds is settled a tick later by rank, and again by the
# 60ms floor between two sounds (SFX_GAP) — so hooking the ask logs chords the
# user would never hear. sndPlay is downstream of both decisions, and takes the
# spec object, which maps back to a name by identity.
SFX_HOOK = """() => {
  window.__dzSfx = [];
  const byspec = new Map(Object.entries(SFX).map(([k, v]) => [v, k]));
  const real = window.sndPlay;
  window.sndPlay = function (spec) {
    window.__dzSfx.push([byspec.get(spec) || "?", performance.now()]);
    return real.apply(this, arguments);
  };
}"""

ROWS = fixture.ROWS
IDS = fixture.IDS


# --------------------------------------------------------------- the server
# Same shape as test/shots.py's stub: the live server wants basic auth, and a
# demo has to cut identically every time anyway.
def handle(route):
    req = route.request
    if req.method != "GET":
        # A write during a take would desync the fixture from the rows already
        # on screen. Acknowledged, not applied — the UI shows what it would.
        return route.fulfill(json={"ok": True, "id": IDS.SHOWCASE + 1})
    url = req.url
    if "/stats" in url:
        return route.fulfill(json={"count": len(ROWS),
                                   "newest_created_at_utc": ROWS[0]["created_at_utc"]})
    m = re.search(r"/entries/(\d+)", url)
    if m:
        hit = next((r for r in ROWS if r["id"] == int(m.group(1))), None)
        return route.fulfill(json=hit) if hit else route.fulfill(
            status=404, json={"error": "no such entry"})
    if "/entries" in url:
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&") if "=" in p)
        off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
        body = q.get("content") != "0"
        sel = [r if body else {k: v for k, v in r.items() if k != "content"}
               for r in ROWS]
        return route.fulfill(json=sel[off:off + lim])
    return route.fulfill(status=404, json={"error": "not found"})


# ---------------------------------------------------------------- the layer
# Injected before the app boots, so the opening black is on screen from the
# first frame rather than after a flash of a half-built journal.
OVERLAY_CSS = """
/* The gap before the overlay exists. #dz cannot be attached until there is a
   body, and until then the half-built app — no fonts, an empty list, the word
   "loading" — is on screen and in the recording. This covers that, from the
   first paint, and DZ takes it off once its own black is up. */
html.dz-pre::before {
  content: ""; position: fixed; inset: 0; background: #000; z-index: 2147483646;
}
/* The clapperboard. The soundtrack is rendered separately and has to be laid
   against the picture, and the page's clock is not the video's clock — so the
   cover starts white for a moment and the flip to black is timestamped. It
   happens at the first paint, which is inside the boot black that build.sh
   trims off, so it never reaches the cut. */
html.dz-pre.dz-clap::before { background: #fff; }

#dz, #dz * { box-sizing: border-box; }
#dz {
  position: fixed; inset: 0; z-index: 2147483000; pointer-events: none;
  --dz-a: #f90;
}
/* ---- the black the reel opens and closes on ---- */
#dz-fade {
  position: absolute; inset: 0; background: #000; opacity: 1;
  transition: opacity .7s ease;
}
#dz-fade.off { opacity: 0; }

/* ---- title / end card ---- */
#dz-card {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  justify-content: center; padding: 0 0 0 150px; opacity: 0;
  background: #000;                    /* opaque: the card is a cut, not a wash */
  transition: opacity .6s ease;
}
#dz-card.on { opacity: 1; }
#dz-card .rule { display: flex; align-items: center; gap: 10px; margin-bottom: 26px; }
#dz-card .rule i {
  height: 26px; border-radius: 13px; background: var(--dz-a);
  transform: scaleX(0); transform-origin: left; animation: dzbar .7s ease forwards;
}
@keyframes dzbar { to { transform: scaleX(1); } }
#dz-card .kick {
  font: 600 19px/1 var(--mono); letter-spacing: .42em; color: #8e8e9c;
  text-transform: uppercase; margin-bottom: 20px;
}
#dz-card h1 {
  font: 700 128px/.92 var(--disp); letter-spacing: .05em; color: var(--dz-a);
  margin: 0 0 22px; text-transform: uppercase;
}
#dz-card h2 {
  font: 400 44px/1.18 var(--disp); letter-spacing: .015em; color: #ececf2;
  margin: 0 0 30px; max-width: 1180px;
}
#dz-card .sub {
  font: 400 21px/1.7 var(--mono); color: #7f7f8d; max-width: 960px;
}
#dz-card .sub b { color: var(--amber); font-weight: 400; }

/* ---- lower third ---- */
#dz-cap {
  position: absolute; left: 0; right: 0; bottom: 0; padding: 92px 64px 40px;
  display: flex; align-items: flex-end; gap: 22px;
  background: linear-gradient(to top, #000 0%, rgba(0,0,0,.94) 52%, rgba(0,0,0,0) 100%);
  opacity: 0; transform: translateY(18px);
  transition: opacity .42s ease, transform .42s ease;
}
#dz-cap.on { opacity: 1; transform: none; }
/* The app keeps its own furniture at the bottom left — the dictation read-out
   lives exactly where the lower third does. Scenes that light it up move the
   caption to the top instead of covering the thing they are describing. */
#dz-cap.top {
  top: 0; bottom: auto; padding: 40px 64px 92px; align-items: flex-start;
  background: linear-gradient(to bottom, #000 0%, rgba(0,0,0,.94) 52%, rgba(0,0,0,0) 100%);
  transform: translateY(-18px);
}
#dz-cap.top.on { transform: none; }
/* Beside the picture rather than under it — the phone plate, where the subject
   is a tall portrait device and the room is all to the right of it. */
#dz-cap.side {
  left: 590px; right: 70px; top: 355px; bottom: auto;
  padding: 0; background: none;
  flex-direction: column; align-items: flex-start; gap: 26px;
}
#dz-cap .cap {
  width: 74px; height: 40px; border-radius: 20px; background: var(--dz-a);
  flex: none; position: relative;
}
#dz-cap .cap b {
  position: absolute; right: 9px; bottom: 5px; color: #000;
  font: 600 12px/1 var(--mono); letter-spacing: .06em;
}
#dz-cap .tx {
  font: 400 41px/1.12 var(--disp); letter-spacing: .015em; color: #fff;
  padding-bottom: 1px; text-wrap: balance;
}
#dz-cap .tx em { color: var(--dz-a); font-style: normal; }
#dz-cap .tx code {
  font: 400 33px/1 var(--mono); color: var(--amber); letter-spacing: -.01em;
}

/* ---- the pointer, and what it does ---- */
#dz-cur {
  position: absolute; left: -100px; top: -100px; width: 26px; height: 26px;
  margin: -13px 0 0 -13px; border-radius: 50%;
  border: 2px solid var(--orange); background: rgba(255,153,0,.12);
  box-shadow: 0 0 14px rgba(255,153,0,.55), inset 0 0 8px rgba(255,153,0,.3);
  opacity: 0;
  /* The travel is the browser's, not Python's: stepping left/top over a CDP
     round trip per frame was both jerkier and slower than the compositor
     doing it. Python only says where and how long. */
  transition: opacity .3s ease,
              left var(--dz-t, .6s) cubic-bezier(.45, .05, .2, 1),
              top  var(--dz-t, .6s) cubic-bezier(.45, .05, .2, 1);
}
#dz-cur::after {
  content: ""; position: absolute; inset: 9px; border-radius: 50%;
  background: var(--orange);
}
#dz-cur.on { opacity: 1; }
.dz-ring {
  position: absolute; width: 26px; height: 26px; margin: -13px 0 0 -13px;
  border-radius: 50%; border: 2px solid var(--orange); pointer-events: none;
  animation: dzring .62s cubic-bezier(.2,.7,.3,1) forwards;
}
@keyframes dzring {
  to { transform: scale(3.4); opacity: 0; border-width: 1px; }
}

/* ---- the keystroke, when the keyboard is doing the work ---- */
#dz-key {
  position: absolute; right: 64px; bottom: 168px; display: flex; gap: 10px;
  opacity: 0; transition: opacity .25s ease;
}
#dz-key.on { opacity: 1; }
#dz-key span {
  min-width: 58px; height: 58px; padding: 0 18px; border-radius: 12px;
  background: #15151b; border: 2px solid var(--orange); color: var(--amber);
  font: 600 26px/54px var(--mono); text-align: center; letter-spacing: .04em;
  box-shadow: 0 6px 22px rgba(0,0,0,.7);
}
"""

# Sized here rather than in the sheet above, because it depends on the viewport
# the reel is filmed at. Overrides the `inset: 0` in the #dz rule: the overlay
# is laid out on a DZ_CANVAS-wide page and scaled down to cover the frame
# exactly, so everything on it grows together.
OVERLAY_CSS += """
#dz {
  left: 0; top: 0; right: auto; bottom: auto;
  width: %dpx; height: %dpx;
  transform: scale(%.6f); transform-origin: 0 0;
}
""" % (DZ_CANVAS, round(H / DZ_K), DZ_K)


OVERLAY_JS = r"""
// DZCSS is the stylesheet, handed in by open_app as a string.
//
// This runs at document_start, where document.documentElement is not reliably
// there yet — touching it unguarded throws, the script dies, and window.DZ
// never gets defined, which shows up much later as "DZ is not defined" on the
// first caption. So the early work is guarded and retried, and it happens
// before nothing: window.DZ is assigned regardless.
(function early() {
  var de = document.documentElement;
  if (!de) { return void setTimeout(early, 1); }
  var s = document.createElement("style");
  s.textContent = DZCSS;
  de.appendChild(s);
  de.classList.add("dz-pre");          // covers the boot, until #dz is up
})();

window.DZ = (function () {
  var el = function (t, id, cls) {
    var n = document.createElement(t);
    if (id) n.id = id; if (cls) n.className = cls; return n;
  };
  var root = el("div", "dz");
  root.innerHTML =
    '<div id="dz-card"></div>' +
    '<div id="dz-cap"><div class="cap"><b></b></div><div class="tx"></div></div>' +
    '<div id="dz-cur"></div>' +
    '<div id="dz-key"></div>' +
    '<div id="dz-fade"></div>';
  var attach = function () {
    document.body.appendChild(root);
    // #dz-fade is opaque at this point, so handing over is not a flash
    document.documentElement.classList.remove("dz-pre");
  };
  if (document.body) attach(); else document.addEventListener("DOMContentLoaded", attach);

  var q = function (s) { return root.querySelector(s); };
  var PAL = { orange: "#f90", amber: "#fc6", purple: "#c9c", blue: "#9cf",
              green: "#9c6", salmon: "#f96", sky: "#79f", gold: "#fc3" };

  return {
    accent: function (name) { root.style.setProperty("--dz-a", PAL[name] || name); },

    fade: function (on) { q("#dz-fade").classList.toggle("off", !on); },

    card: function (o) {
      var c = q("#dz-card");
      var bars = (o.bars || [210, 92, 44]).map(function (w, i) {
        return '<i style="width:' + w + 'px;animation-delay:' + (i * .09) + 's"></i>';
      }).join("");
      c.innerHTML =
        '<div class="rule">' + bars + "</div>" +
        (o.kicker ? '<div class="kick">' + o.kicker + "</div>" : "") +
        (o.title ? "<h1>" + o.title + "</h1>" : "") +
        (o.line ? "<h2>" + o.line + "</h2>" : "") +
        (o.sub ? '<div class="sub">' + o.sub + "</div>" : "");
      c.classList.add("on");
    },
    cardOut: function () { q("#dz-card").classList.remove("on"); },

    cap: function (html, tag, pos) {
      q("#dz-cap .tx").innerHTML = html;
      q("#dz-cap .cap b").textContent = tag || "";
      var c = q("#dz-cap");
      c.classList.toggle("top", pos === "top");
      c.classList.toggle("side", pos === "side");
      c.classList.add("on");
    },
    capOut: function () { q("#dz-cap").classList.remove("on"); },

    /* #dz is a DZ_CANVAS-wide canvas scaled down onto the frame, but every
       coordinate handed in from outside is a real viewport pixel — off a
       bounding box, or the mouse. Undo the scale on the way in. */
    at: function (v) { return v / DZ_K; },

    /* Put it somewhere with no travel, and flush, so that the *next* move
       animates from here instead of flying in from off-screen. */
    place: function (x, y) {
      var c = q("#dz-cur");
      c.style.setProperty("--dz-t", "0s");
      c.style.left = (x / DZ_K) + "px"; c.style.top = (y / DZ_K) + "px";
      void c.offsetWidth;
    },

    cursor: function (x, y, dur) {
      var c = q("#dz-cur");
      c.style.setProperty("--dz-t", (dur || 0) + "s");
      c.style.left = (x / DZ_K) + "px"; c.style.top = (y / DZ_K) + "px";
      c.classList.add("on");
    },
    cursorOff: function () { q("#dz-cur").classList.remove("on"); },

    ring: function (x, y) {
      var r = el("div", null, "dz-ring");
      r.style.left = (x / DZ_K) + "px"; r.style.top = (y / DZ_K) + "px";
      root.appendChild(r);
      setTimeout(function () { r.remove(); }, 700);
    },

    key: function (keys) {
      var k = q("#dz-key");
      k.innerHTML = keys.map(function (s) { return "<span>" + s + "</span>"; }).join("");
      k.classList.add("on");
    },
    keyOff: function () { q("#dz-key").classList.remove("on"); },
  };
})();
"""


# -------------------------------------------------------------- the camera
def ease(t):
    """Ease in-out — a pointer that starts and stops abruptly reads as a jump."""
    return 3 * t * t - 2 * t * t * t


class Director:
    def __init__(self, page, speed=1.0, proof=None):
        self.page = page
        self.speed = speed
        self.proof = proof
        self.scene = "scene"                     # set by the loop, for shot()
        self.cur_on = False
        self.x, self.y = W * 0.5, H * 0.62      # where the pointer waits

    # ---- time -----------------------------------------------------------
    def hold(self, sec):
        self.page.wait_for_timeout(int(sec * 1000 / self.speed))

    # ---- the layer ------------------------------------------------------
    def js(self, expr, *args):
        return self.page.evaluate(expr, *args)

    def accent(self, name):
        self.js("n => DZ.accent(n)", name)

    def cap(self, html, tag="", accent=None, hold=0.7, pos="bottom"):
        """Put a caption up and get out of the way.

        The default beat is short on purpose: the caption is meant to be read
        *while* the thing it describes is happening. Holding for the whole
        reading time before touching anything is what made the first cut play
        like a slideshow.
        """
        if accent:
            self.accent(accent)
        self.js("a => DZ.cap(a[0], a[1], a[2])", [html, tag, pos])
        self.hold(hold)

    def cap_out(self, settle=0.45):
        # A caption comes down at the end of the beat it belongs to, with
        # whatever it was describing still on screen — so this is the moment
        # worth keeping as the scene's proof.
        self.shot(self.scene)
        self.js("() => DZ.capOut()")
        self.hold(settle)

    def card(self, **o):
        self.js("o => DZ.card(o)", o)

    def card_out(self, settle=0.7):
        self.shot(self.scene)                    # same idea, for the two cards
        self.js("() => DZ.cardOut()")
        self.hold(settle)

    def fade(self, on):
        self.js("v => DZ.fade(v)", on)

    # ---- the pointer ----------------------------------------------------
    def _box(self, sel, nth=0, loc=None):
        if loc is None:
            loc = self.page.locator(sel).nth(nth)
        loc.wait_for(state="visible", timeout=8000)
        loc.scroll_into_view_if_needed()
        b = loc.bounding_box()
        if not b:
            raise RuntimeError(f"no box for {sel!r}")
        return b

    def move(self, sel=None, xy=None, nth=0, dur=0.62, dx=0.5, dy=0.5, loc=None):
        if xy is None:
            b = self._box(sel, nth, loc)
            xy = (b["x"] + b["width"] * dx, b["y"] + b["height"] * dy)
        tx, ty = xy
        sx, sy = self.x, self.y
        dur = dur / self.speed
        if not self.cur_on:                      # first move of a scene run
            self.js("p => DZ.place(p[0], p[1])", [sx, sy])
            self.cur_on = True
        # The drawn cursor is handed the whole trip at once and eased by the
        # compositor. The real mouse still walks it, because that is what makes
        # the app's own hover states light up on the way past — but it can do
        # so in a few coarse steps without anyone seeing the difference.
        self.js("p => DZ.cursor(p[0], p[1], p[2])", [tx, ty, round(dur, 3)])
        steps = 10
        for i in range(1, steps + 1):
            t = ease(i / steps)
            self.page.mouse.move(sx + (tx - sx) * t, sy + (ty - sy) * t)
            self.page.wait_for_timeout(int(dur * 1000 / steps))
        self.x, self.y = tx, ty
        return tx, ty

    def click(self, sel=None, xy=None, nth=0, dur=0.62, dx=0.5, dy=0.5,
              settle=0.55, modifiers=None, loc=None):
        x, y = self.move(sel, xy, nth, dur, dx, dy, loc)
        self.hold(0.18)
        self.js("p => DZ.ring(p[0], p[1])", [x, y])
        # Mouse.click takes no modifiers, so they are held around it by hand.
        for m in modifiers or []:
            self.page.keyboard.down(m)
        self.page.mouse.click(x, y)
        for m in reversed(modifiers or []):
            self.page.keyboard.up(m)
        self.hold(settle)

    def cursor_off(self):
        self.js("() => DZ.cursorOff()")
        self.cur_on = False


    def scroll(self, sel, dy, dur=1.0):
        """Ease a scroller through `dy` pixels.

        Not mouse.wheel: the app's list is a plain overflow scroller and a
        wheel event lands in one lump, which on camera looks like a cut. The
        easing runs on rAF inside the page — from out here it was one round
        trip per frame, which capped it well under the frame rate.
        """
        dur = dur / self.speed
        self.js("""a => new Promise(done => {
          const el = document.querySelector(a[0]);
          const from = el.scrollTop, dy = a[1], ms = a[2] * 1000;
          const t0 = performance.now();
          (function step(now) {
            const t = Math.min(1, (now - t0) / ms);
            el.scrollTop = from + dy * (3 * t * t - 2 * t * t * t);
            t < 1 ? requestAnimationFrame(step) : done();
          })(t0);
        })""", [sel, dy, dur])

    # ---- the keyboard ---------------------------------------------------
    def key(self, key, show=None, settle=0.6):
        self.js("k => DZ.key(k)", [show or key.upper()])
        self.hold(0.42)
        self.page.keyboard.press(key)
        self.hold(settle)
        self.js("() => DZ.keyOff()")

    def type(self, text, delay=58, settle=0.5):
        self.page.keyboard.type(text, delay=int(delay / self.speed))
        self.hold(settle)

    def esc(self, settle=0.7):
        """Out of whatever is open. Every overlay in the app takes Escape."""
        self.page.keyboard.press("Escape")
        self.hold(settle)

    def shot(self, name):
        """The frame this scene exists to show, saved straight out of the page.

        Seeking the finished video by wall-clock time does not land where you
        expect — the recording starts a beat after the page does, and the drift
        grows over a couple of minutes. These are taken from the live page at
        the exact moment, so they are what the scene actually looks like.
        """
        if not self.proof:
            return
        # First one wins: a scene that dismisses two captions should be
        # remembered by its first peak, not by whatever was left on screen.
        p = self.proof / f"{name}.png"
        if not p.exists():
            # scale="css": 1920x1080, not the 2x the context renders at. These
            # are for checking a scene, and the big ones cost about a second
            # each of recorded time.
            self.page.screenshot(path=str(p), scale="css")

    def discard(self):
        """Drop the unsaved draft the previous scene left in the form.

        Anything that starts a new entry calls confirmDiscard(), which is a
        native confirm() as soon as the body is `dirty`. There is a dialog
        handler that accepts those, but a modal flashing on camera is still a
        blemish — so the form is put back to clean before it can ask.
        """
        self.js("() => { if (typeof setClean === 'function') setClean();"
                " else document.body.classList.remove('dirty'); }")
        self.hold(0.25)


# ---------------------------------------------------------------- the reel
# Each scene is (name, function). The caption tags are the same motif the app
# puts on its own section labels — 00-101, 01-664 — because they are a nice
# piece of the costume and they cost nothing.
def sc_open(d):
    d.card(kicker="stardate " + fixture.NOW.strftime("%Y.%m%d"),
           title="LCARS",
           line="A journal that runs on one HTML file.",
           sub="no build step &middot; no dependencies &middot; "
               "opens over <b>file://</b> and works offline")
    # Let the card land opaque before lifting the blackout. Crossing the two
    # fades means neither is at full for a moment, and the journal behind them
    # shows through the title — which reads as a bug, not a dissolve.
    d.hold(0.9)
    d.fade(False)
    d.hold(3.6)
    d.card_out()
    d.hold(0.5)


def sc_list(d):
    d.cap("Everything you have written, newest first &mdash; "
          "grouped by the day you wrote it.", "00-101", "orange")
    d.js("() => { $('#list').scrollTop = 0; }")
    # a slow drift down the list, so the day bars and the kind colours read
    d.scroll("#list", 26 * 22, dur=1.15)
    d.hold(1.7)
    d.js("() => { $('#list').scrollTop = 0; }")
    d.hold(0.6)
    d.cap_out()


def sc_search(d):
    d.cap("Search is instant &mdash; the whole journal is already here.",
          "01-664", "sky")
    d.click("#q", settle=0.3)
    d.type("arena", delay=105)
    d.hold(1.5)
    d.cap("Plain text, or <code>/regex/</code>, over titles and bodies.",
          "01-664")
    d.hold(1.8)
    d.cap_out()


def sc_reader(d):
    d.cap("Markdown, rendered. <em>TODO</em> and <em>DONE</em> are just words "
          "you type.", "02-447", "amber", hold=0.35)
    d.click(f'.item[data-id="{IDS.ARENA}"]', dx=0.35, settle=0.9)
    d.hold(3.2)
    d.cap_out()


def sc_links(d):
    d.cap("Every <code>[[link]]</code> is real. Follow one.", "03-190", "purple")
    # the first wiki link in the body is [[LCARS UI]]
    d.click("#rd_content a.wiki", settle=1.1)
    d.hold(1.2)
    d.cap("And every page knows what points back at it.", "03-190", hold=0.4)
    d.js("() => { $('#readbody').scrollTop = 0; }")
    d.scroll("#readbody", 560, dur=1.0)
    d.hold(2.2)
    d.cap_out()


def sc_graph(d):
    # The journal behind the modal should be the whole journal again: the link
    # we followed left "LCARS UI" sitting in the search box.
    d.js("() => { $('#q').value = ''; $('#q').dispatchEvent(new Event('input')); }")
    d.cap("The links, all of them at once.", "04-822", "green", hold=0.4)
    d.click("#bGraph", settle=0.5)
    d.hold(3.4)                                  # let the layout cool
    d.cap("Force-directed, laid out live. Double-click a page to open it.",
          "04-822", hold=3.0)
    d.cap_out()
    d.esc()
    d.cursor_off()


def sc_trend(d):
    d.cap("How often one thing comes up &mdash; over months.", "05-315", "gold",
          hold=0.4)
    d.js("() => openTrend('German course')")
    d.hold(3.4)
    d.cap_out()
    d.esc()


def sc_month(d):
    d.cap("A month at a time, with what every day holds.", "06-118", "blue",
          hold=0.4)
    d.click("#bMonth", settle=1.2)
    d.hold(1.8)
    d.click("#moprev", settle=1.2)
    d.hold(1.7)
    d.cap_out()
    d.esc()
    d.cursor_off()


def sc_tasks(d):
    d.cap("Every open task in the journal, oldest first.", "07-204", "salmon",
          hold=0.4)
    d.click("#bTasks", settle=1.2)
    d.hold(2.6)
    d.cap_out()
    d.esc()
    d.cursor_off()


def sc_stats(d):
    d.cap("What the journal knows about itself.", "08-771", "purple", hold=0.4)
    d.click("#bStats", settle=1.2)
    d.hold(3.2)
    d.cap_out()
    d.esc()
    d.cursor_off()


def sc_daypage(d):
    d.cap("Today: the day's entries by time, and a page that links them all.",
          "09-530", "orange", hold=0.4)
    d.click("#bDayPage", settle=1.3)
    d.hold(1.6)
    d.click("#daypage", settle=1.0)
    d.hold(2.0)
    d.cap_out()
    d.esc()
    d.cursor_off()


def sc_template(d):
    # The day page left a draft in the form; starting something new on top of
    # it would raise the discard confirm mid-shot.
    d.discard()
    d.cap("A new entry can start from a template.", "10-663", "amber", hold=0.4)
    d.key("Shift+N", show=["N"], settle=0.9)
    d.hold(0.5)
    d.type("book", delay=110)
    d.hold(1.1)
    d.click(".pkr", settle=1.2)
    d.cap("Placeholders filled in, cursor already where you would put it.",
          "10-663", hold=0.5)
    d.type("Seeing Like a State", delay=52)
    d.hold(1.8)
    d.cap_out()


def sc_slash(d):
    d.cap("In the editor, <code>/</code> is the command line.", "11-905", "sky",
          hold=0.4)
    d.click("#content", dy=0.22, settle=0.3)
    d.page.keyboard.press("Control+End")
    d.page.keyboard.press("Enter")
    d.hold(0.3)
    d.type("/", delay=120, settle=1.2)
    d.hold(2.2)
    d.cap_out()
    d.esc(settle=0.4)
    d.page.keyboard.press("Backspace")           # the "/" it was typed to open
    d.hold(0.3)


def sc_voice(d):
    # Caption up top: the dictation read-out lands in the bottom-left corner,
    # which is where the lower third would sit right on top of it.
    d.cap("Dictate it &mdash; or say &ldquo;computer, &hellip;&rdquo; "
          "and it takes orders.", "12-447", "green", hold=0.4, pos="top")
    # No microphone in headless Chromium and no speech service behind one, so
    # the read-out is driven straight: what is worth filming is the chrome the
    # dictation puts on screen, not the recogniser underneath it.
    d.js("""() => {
      $('#content').focus();
      vx.on = true; vx.live = true; vx.dict = true;
      vx.heard = 'and then we sized the arena at one megabyte';
      vPaint();
    }""")
    d.hold(3.4)
    d.cap_out()
    # Off again, or the read-out sits in the corner for the rest of the reel.
    d.js("() => { vx.on = false; vx.live = false; vx.dict = false;"
         " vx.heard = ''; vPaint(); }")
    d.hold(0.3)


def sc_capture(d):
    d.esc(settle=0.4)
    d.discard()
    d.cap("Or catch a thought without leaving what you were doing.",
          "13-228", "gold", hold=0.4)
    d.key("q", settle=0.9)
    d.type("the sidecar timeout is 30s, not 5 — check the other two", delay=44)
    d.hold(2.2)
    d.cap_out()
    d.esc()


def sc_close(d):
    d.cursor_off()
    # Back to the journal before the card comes up: the last thing under the
    # end title should be the app at rest, not a half-typed draft.
    d.js("() => { closeOv && closeOv(); }")
    d.discard()
    d.js("() => { $('#bClose').click(); $('#list').scrollTop = 0; }")
    d.hold(1.4)
    # The card is opaque and sits above the app, so showing it *is* the fade to
    # black. The blackout underneath goes on while it is up, so that taking the
    # card away at the end lands on black rather than back on the journal.
    d.card(kicker="one file",
           title="LCARS",
           line="Your journal, in a console that never needed a build step.",
           sub="<b>index.html</b> &mdash; open it from a disk, a LAN, or a phone")
    d.hold(4.0)
    d.shot("close")                              # the card, before the blackout
    d.fade(True)                                 # 0.7s to black, over the card
    d.hold(1.2)
    d.card_out(settle=0.2)
    d.hold(0.6)


SCENES = [
    ("open", sc_open),
    ("list", sc_list),
    ("search", sc_search),
    ("reader", sc_reader),
    ("links", sc_links),
    ("graph", sc_graph),
    ("trend", sc_trend),
    ("month", sc_month),
    ("tasks", sc_tasks),
    ("stats", sc_stats),
    ("daypage", sc_daypage),
    ("template", sc_template),
    ("slash", sc_slash),
    ("voice", sc_voice),
    ("capture", sc_capture),
    ("close", sc_close),
]


# -------------------------------------------------------------------- main
# ------------------------------------------------------------- the phone pass
# Recorded on its own, at a phone's viewport, and dropped into a 1920x1080
# frame by build.sh. It was originally an iframe inside the desktop reel, which
# would have been tidier — but an iframe on a page that has any
# compositing-promoted layer on it (and the caption overlay has several) is not
# composited into a headless capture, and films as a black rectangle. A second
# pass is the thing that actually works.
PHONE_W, PHONE_H = 390, 844

# An 844-tall phone does not fit in a 720-tall frame, so it is shown smaller
# than life and the caption moves beside it rather than under it. That turns
# out better than the old lower-third version anyway: the phone ends up filling
# 89% of the frame height instead of 78%, and the wasted space either side of a
# portrait device is where the words go.
PHONE_SHOW_H = 640
PHONE_SHOW_W = round(PHONE_W * PHONE_SHOW_H / PHONE_H)      # 296
PHONE_AT = (96, 40)         # where build.sh lands the video inside the plate


def phone_reel(d):
    """A short tour at phone size. No captions — they go on the plate."""
    d.fade(False)
    d.hold(1.4)
    d.scroll("#list", 300, dur=1.3)
    d.hold(1.2)
    d.click(f'.item[data-id="{IDS.SHOWCASE}"]', dx=0.5, settle=1.2)
    d.hold(2.0)
    d.scroll("#readbody", 320, dur=1.1)
    d.hold(2.0)
    d.cursor_off()
    d.hold(0.3)
    d.fade(True)
    d.hold(1.0)


# ------------------------------------------------------------- the hero loop
# A short, silent, chrome-free clip for muted autoplay on a front page. A 2:30
# film is the wrong asset there; this is the right one.
#
# It has to come back to where it started, or the loop point shows. So: list at
# top, drift down, drift back, the graph, and home again.
HERO_LEAD = 1.0          # black + fade at the head, which build.sh trims off


def hero_reel(d):
    d.js("() => { $('#list').scrollTop = 0; }")
    d.fade(False)
    d.hold(HERO_LEAD)
    d.scroll("#list", 320, dur=2.6)
    d.hold(0.5)
    d.scroll("#list", -320, dur=2.1)
    d.hold(0.6)
    d.js("() => { $('#bGraph').click(); }")     # no pointer in this one
    d.hold(4.4)
    d.page.keyboard.press("Escape")
    d.hold(1.8)                                  # back exactly where it began


def render_plate(page, out):
    """The 1920x1080 backdrop the phone video is laid into.

    Drawn on the app's own page so the caption picks up the real fonts and
    palette, with the app itself hidden behind it.
    """
    x, y = PHONE_AT
    page.evaluate("""a => {
      document.querySelector('header').style.display = 'none';
      document.querySelector('main').style.display = 'none';
      document.body.style.background = '#000';
      const b = document.createElement('div');
      b.style.cssText = 'position:fixed;left:' + (a[0] - 3) + 'px;top:' + (a[1] - 3)
        + 'px;width:' + (a[2] + 6) + 'px;height:' + (a[3] + 6) + 'px;'
        + 'border:3px solid #f90;border-radius:30px;background:#000;z-index:5;'
        + 'box-shadow:0 0 80px rgba(255,153,0,.22)';
      document.body.appendChild(b);
      DZ.fade(false);
      DZ.accent('sky');
      DZ.cap('It is the same file on a phone.<br>Nothing was rebuilt.',
             '14-016', 'side');
    }""", [x, y, PHONE_SHOW_W, PHONE_SHOW_H])
    page.wait_for_timeout(900)
    page.screenshot(path=str(out), scale="css")


def open_app(p, out, w, h, record=True):
    """A browser on the stubbed journal, with the overlay already installed.

    Returns (browser, context, page) with the app booted and its two sweeps
    landed, so a caller can start filming on the next line.
    """
    browser = p.chromium.launch(headless=True, args=[
        "--force-prefers-reduced-motion=0",
        "--hide-scrollbars",
        "--force-color-profile=srgb",
    ])
    ctx = browser.new_context(
        viewport={"width": w, "height": h},
        device_scale_factor=2,                   # captured at 2x, filmed at 1x
        reduced_motion="no-preference",
        locale="en-GB", timezone_id="UTC",
        **({"record_video_dir": str(out),
            "record_video_size": {"width": w, "height": h}} if record else {}),
    )
    # "/**", not "/*": one star stops at a slash, so /entries/2400 would
    # slip past and reach the real server, which answers 401.
    ctx.route(BASE + "/**", handle)
    # index.html pulls its display face from Google Fonts. Filming over that is
    # a network dependency in the middle of a two-minute take: a blip and the
    # whole reel silently cuts in Arial Narrow, or open_app sits waiting on
    # document.fonts that never arrive. The demo serves its own copy and blocks
    # the remote one, so the take is the same offline as on. The app itself is
    # untouched — this only applies to the recording.
    ctx.route("https://fonts.googleapis.com/**", lambda r: r.abort())
    ctx.route("https://fonts.gstatic.com/**", lambda r: r.abort())
    ctx.add_init_script(
        "localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));"
        "localStorage.removeItem('lcars.filters');"
        "localStorage.removeItem('lcars.views');"
        "localStorage.removeItem('lcars.seen');" % BASE)
    # One script, not two: the stylesheet has to be in force for the very
    # first paint, and the code that installs it is the same code that has to
    # survive running before the document element exists.
    ctx.add_init_script("var DZCSS = %s, DZ_CLAP_MS = %d, DZ_K = %.6f;\n%s"
                        % (_js_str(FONT_CSS + OVERLAY_CSS), CLAP_MS, DZ_K, OVERLAY_JS))

    page = ctx.new_page()
    # Playwright dismisses native dialogs by default, which makes a confirm()
    # read as "no" and quietly cancels whatever the scene was doing. Nothing
    # here writes to a real server, so: always yes.
    page.on("dialog", lambda dlg: dlg.accept())
    page.goto(PAGE)
    # Antonio comes from Google Fonts; filming before it lands would cut from
    # Arial to condensed mid-shot.
    page.wait_for_function(
        "() => document.fonts && document.fonts.status === 'loaded'", timeout=15000)
    page.wait_for_timeout(2000)                  # both API sweeps
    page.wait_for_function(
        "() => document.querySelectorAll('.item').length > 20", timeout=15000)
    page.evaluate(SFX_HOOK)
    return browser, ctx, page


def clap(page):
    """Flash the cover white, then black, and time the flip on the page clock.

    The pair of these — one before the first scene, one after the last — is
    what lets a sound recorded on the page's clock be laid against the picture.
    They are not the same clock: Playwright's screencast only emits a frame
    when the page changes, and under load it drops them, so the recording can
    come out measurably shorter than the wall time it covers.
    """
    return page.evaluate("""async ms => {
      const de = document.documentElement;
      de.classList.add('dz-pre', 'dz-clap');
      await new Promise(r => setTimeout(r, ms));
      de.classList.remove('dz-clap');
      const t = performance.now();
      await new Promise(r => setTimeout(r, 340));   // a black handle to trim to
      de.classList.remove('dz-pre');
      return t;
    }""", CLAP_MS)


def audio_log(page, clap_ms):
    """The clap and every sound that played, both on the page's clock.

    One clap is enough. Measured over a full 123s reel, the page clock and the
    video clock stay within 10ms of each other — the screencast loses about
    450ms during the boot, when the app is busy and frames get dropped, and
    then tracks at 0.99992 of real time, which is a third of a frame over two
    minutes. So the anchor only has to sit after the boot, which is where
    clap() is called from.
    """
    events = page.evaluate("window.__dzSfx || []")
    return {"clap_page_ms": clap_ms, "events": [[n, t] for n, t in events]}


def record_hero(out, speed):
    """The front-page loop. Silent, so no clap is needed beyond the trim."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "hero.webm").unlink(missing_ok=True)
    t0 = time.monotonic()
    with sync_playwright() as p:
        browser, ctx, page = open_app(p, out, W, H)
        clap(page)
        hero_reel(Director(page, speed))
        page.wait_for_timeout(300)
        video = page.video
        ctx.close()
        src = pathlib.Path(video.path())
        browser.close()
    src.rename(out / "hero.webm")
    print(f"{out / 'hero.webm'}  ({time.monotonic() - t0:.0f}s wall)")
    return 0


def record_phone(out, speed):
    """The phone pass, plus the plate build.sh lays it into."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "phone.webm").unlink(missing_ok=True)
    t0 = time.monotonic()
    with sync_playwright() as p:
        browser, ctx, page = open_app(p, out, PHONE_W, PHONE_H)
        clap_ms = clap(page)
        phone_reel(Director(page, speed))
        page.wait_for_timeout(400)
        (out / "phone.audio.json").write_text(
            json.dumps(audio_log(page, clap_ms), indent=2) + "\n")
        video = page.video
        ctx.close()
        src = pathlib.Path(video.path())
        browser.close()

        # the plate is a still, so it does not want to be in the recording
        browser, ctx, page = open_app(p, out, W, H, record=False)
        render_plate(page, out / "plate.png")
        browser.close()

    src.rename(out / "phone.webm")
    print(f"{out / 'phone.webm'} + plate.png  ({time.monotonic() - t0:.0f}s wall)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true", help="2.5x, for iterating")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--only", help="comma-separated scene names")
    ap.add_argument("--list", action="store_true", help="print scene names")
    ap.add_argument("--proof", action="store_true",
                    help="also save each scene's money shot to out/proof/")
    ap.add_argument("--phone", action="store_true",
                    help="record the phone pass (out/phone.webm + out/plate.png)")
    ap.add_argument("--hero", action="store_true",
                    help="record the silent front-page loop (out/hero.webm)")
    ap.add_argument("--name", default="reel",
                    help="basename for the webm and its marks (default: reel)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    if args.list:
        print(" ".join(n for n, _ in SCENES))
        return 0

    speed0 = 2.5 if args.fast else args.speed
    if args.phone:
        return record_phone(pathlib.Path(args.out), speed0)
    if args.hero:
        return record_hero(pathlib.Path(args.out), speed0)

    speed = 2.5 if args.fast else args.speed
    picked = SCENES
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        bad = want - {n for n, _ in SCENES}
        if bad:
            sys.exit(f"no such scene: {', '.join(sorted(bad))}")
        picked = [(n, f) for n, f in SCENES if n in want]

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # Not a wipe of the whole directory: the phone pass writes in here too, and
    # a rebuild of one should not silently delete the other.
    (out / f"{args.name}.webm").unlink(missing_ok=True)
    if args.proof and (out / "proof").exists():
        shutil.rmtree(out / "proof")

    t0 = time.monotonic()
    with sync_playwright() as p:
        t_rec = time.monotonic()                 # ~ when the recording starts
        browser, ctx, page = open_app(p, out, W, H)

        # The anchor for the soundtrack, and the point build.sh trims the head
        # back to. Both jobs, one flash — and trimming to it guarantees the
        # flash itself never reaches the cut.
        clap_ms = clap(page)

        proof = None
        if args.proof:
            proof = out / "proof"
            proof.mkdir(parents=True, exist_ok=True)
        d = Director(page, speed, proof)
        # The reel opens on black and sc_open is what lifts it. Running a
        # scene on its own without that would film a black rectangle.
        if not any(n == "open" for n, _ in picked):
            d.fade(False)
            d.hold(0.8)
        marks = []
        for name, fn in picked:
            mark = time.monotonic()
            d.scene = name
            fn(d)
            now = time.monotonic()
            marks.append({"scene": name, "start": round(mark - t_rec, 2),
                          "end": round(now - t_rec, 2)})
            print(f"  {name:<9} {now - mark:5.1f}s   @{mark - t_rec:6.1f}")

        page.wait_for_timeout(500)
        (out / f"{args.name}.audio.json").write_text(
            json.dumps(audio_log(page, clap_ms), indent=2) + "\n")
        video = page.video
        ctx.close()                              # flushes and finalises the file
        src = pathlib.Path(video.path())         # only answerable while pw is up
        browser.close()

    dst = out / f"{args.name}.webm"
    src.rename(dst)
    # Wall-clock offsets from when the page was created, which is within a
    # frame or two of when the recording starts. Good enough to seek a scene
    # while working on it, and to cut YouTube chapters from.
    (out / f"{args.name}.marks.json").write_text(json.dumps(marks, indent=2) + "\n")
    print(f"\n{dst}  ({dst.stat().st_size / 1e6:.1f} MB, "
          f"{time.monotonic() - t0:.0f}s wall)")
    return 0


def _js_str(s):
    """A Python string as a JS string literal, safe inside add_init_script."""
    return json.dumps(s)


if __name__ == "__main__":
    sys.exit(main())
