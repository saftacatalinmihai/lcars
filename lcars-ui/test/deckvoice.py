#!/usr/bin/env python3
"""The deck's spoken orders (DVCMDS in deck.html), phrase in, deck out.

Serves lcars-ui/ on a local port and opens deck.html?demo in headless
Chromium (graphics low, the desktop's keys), with a stand-in for the
browser's SpeechRecognition put into every frame before its scripts run.
Y hands the deck's table to the console in its frame (lcarsDeckVoice),
whose microphone opens on the stand-in; each check then has the stand-in
hear a phrase, as a finished result, and looks at the deck's own state
through window.__deck and its DOM: where you stand and on which deck, the
hand and the pins, the sheets, the settings, the hint a refused order
flashes. So the whole road is walked - the console's recogniser, its wake
word and bare-order rule, its matcher over the two tables, the deck's fn
across the frame - with nothing of the deck's stood in. The demo has no
server, so the console in the frame has no rows: "read it" is the one
check that gives it the entry and a stand-in read-out (ttsAloud).

Usage:  python3 test/deckvoice.py [--page DIR] [-v]
Takes ~1 min (the ship in software WebGL); exits 1 on a failure.
"""
import argparse
import functools
import http.server
import json
import math
import pathlib
import sys
import threading
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--page", default=str(HERE.parent), help="the lcars-ui directory to serve")
ap.add_argument("-v", action="store_true", help="every check, not only the failures")
args = ap.parse_args()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=args.page))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo"

# The stand-in recogniser: start() is a session that opens at once and
# stays open; the live one is window.__rec, which say() below feeds.
FAKE_REC = """
(() => {
  class FakeRec {
    start() { window.__rec = this; setTimeout(() => this.onstart && this.onstart(), 0); }
    stop() { if (window.__rec === this) window.__rec = null; setTimeout(() => this.onend && this.onend(), 0); }
    abort() { if (window.__rec === this) window.__rec = null; }
  }
  window.SpeechRecognition = window.webkitSpeechRecognition = FakeRec;
})();
"""

SAY = """text => {
  const w = document.querySelector("#cframe").contentWindow, r = w.__rec;
  if (!r || !r.onresult) return false;
  const res = [{ transcript: text }]; res.isFinal = true;
  r.onresult({ resultIndex: 0, results: [res] });
  return true;
}"""

fails = []
n_ok = 0


def check(name, cond):
    global n_ok
    if cond:
        n_ok += 1
        if args.v:
            print("   ok   " + name)
    else:
        fails.append(name)
        print("   FAIL " + name)


def ev(js, arg=None):
    return pg.evaluate(js, arg) if arg is not None else pg.evaluate(js)


def wait(js, timeout=30000):
    # polled from here: page.wait_for_function never answered on the deck
    # in headless Chromium (its in-page poller starves), while evaluate does
    end = time.time() + timeout / 1000
    while True:
        try:
            if pg.evaluate(js):
                return True
        except Exception:
            pass
        if time.time() > end:
            return False
        pg.wait_for_timeout(150)


def idle():
    # a lift or a beam under way refuses the next (riding): its fade ends it
    wait("!document.querySelector('#fade').classList.contains('on')", 60000)


def say(text):
    ok = ev(SAY, text)
    if not ok:
        fails.append(f'"{text}": the console was not listening')
        print(f'   FAIL "{text}": the console was not listening')
    return ok


def order(text, js, name=None, timeout=30000):
    """Say it, then wait for the deck to show it."""
    idle()
    say(text)
    got = wait(js, timeout)
    check(name or f'"{text}"', got)
    if not got:
        print("        " + ev("""JSON.stringify({ heard: document.querySelector('#cframe').contentWindow.eval('vx.note'),
          hint: window.__deck.lastHint, hand: window.__deck.place.hand, active: window.__deck.active,
          pins: window.__deck.place.pins.map(q => q.e), aim: window.__deck.aimInfo() })"""))


def hint(text, want):
    # the last hint, not the one on screen: a slow frame can outlast its 1.8 s
    order(text, f"window.__deck.lastHint.includes({json.dumps(want)})", f'"{text}" -> hint "{want}"', 10000)


def look_at(entry):
    """Stand facing the pad pinned for entry, and wait for the aim to find it."""
    ev("""e => { const D = window.__deck, pin = D.place.pins.find(q => q.e === e); if (!pin) return;
      const c = new D.THREE.Vector3(); D.camera.getWorldPosition(c);
      const dx = pin.p[0] - c.x, dy = pin.p[1] - c.y, dz = pin.p[2] - c.z;
      D.setView(D.player.position.x, D.player.position.z, Math.atan2(-dx, -dz), Math.atan2(dy, Math.hypot(dx, dz))); }""", entry)
    wait(f"window.__deck.aimInfo().pad === {entry}", 10000)


def key_y():
    # the keydown the deck listens for on its window: after a sheet the
    # focus may be left in the console's frame, where a key goes to the console
    ev("dispatchEvent(new KeyboardEvent('keydown', { key: 'y', code: 'KeyY' }))")


# Stand a step back from a point on a table top, [x, y, z], looking down at
# it, until the aim is on the table and not on a pad. True if one of 24
# standing places sees it with nothing in the way.
AIM_TABLE = """async at => { const D = window.__deck, T = D.THREE, e = new T.Vector3();
  // the view turns in the frame loop: two frames, and the aim is the new one
  const frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  for (let k = 0; k < 24; k++) {
    const t = k * Math.PI / 4, r = 0.7 + Math.floor(k / 8) * 0.3, x = at[0] + Math.sin(t) * r, z = at[2] + Math.cos(t) * r;
    if (!D.walkable(x, z)) continue;
    D.setView(x, z, 0, 0); await frames(); D.camera.getWorldPosition(e);
    const dx = at[0] - e.x, dy = at[1] - e.y, dz = at[2] - e.z;
    D.setView(x, z, Math.atan2(-dx, -dz), Math.atan2(dy, Math.hypot(dx, dz)));
    await frames();
    const h = D.aimHit();
    if (h && Math.abs(h.point.y - at[1]) < 0.05 && Math.hypot(h.point.x - at[0], h.point.z - at[2]) < 0.1 && !D.aimInfo().pad) return true;
  }
  return false; }"""


ROOM = "(() => { const D = window.__deck, p = D.player.position; return (D.zoneAt(p.x, p.z) || {}).name || ''; })()"
VIS = "!document.querySelector('{}').classList.contains('hidden')"
HID = "document.querySelector('{}').classList.contains('hidden')"

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
                                               "--use-fake-ui-for-media-stream"])
    ctx = b.new_context(viewport={"width": 800, "height": 500})
    ctx.add_init_script(FAKE_REC + """
      localStorage.setItem("lcars.deck.gfx", JSON.stringify("low"));
      localStorage.setItem("lcars.deck.sound", JSON.stringify("off"));
      localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, wait_until="domcontentloaded", timeout=120000)
    # an evaluate sent while the module is still starting never came back:
    # the first question waits until the page has had a moment
    pg.wait_for_timeout(5000)
    if not wait("window.__deck && window.__deck.rows.size > 0", 120000):
        sys.exit("   FAIL the deck did not boot")
    boot = time.time() - t0
    # Nothing here looks at a picture, and a frame of the ship in software
    # WebGL is seconds: the drawing is taken out, the frame loop's logic
    # (the world matrices render() would have updated, the rooms built as you come near, the aim's raycast, the lift's ride,
    # the chip's poll) left running.
    ev("""(() => { const D = window.__deck; D.renderer.render = (sc, cam) => { sc.updateMatrixWorld(); if (!cam.parent) cam.updateMatrixWorld(); }; D.renderer.compile = () => {};
               if (D.composer) D.composer.render = () => {}; })()""")

    # ---- listening: Y opens the console's microphone with the deck's table
    pg.keyboard.press("y")
    check("Y shows the chip at once", ev("!document.querySelector('#vchip').hidden"))
    check("the console in the frame listens for the deck", wait("window.__deck.dv.on && document.querySelector('#cframe').contentWindow.__rec", 60000))
    check("the chip says so", wait("/listening|orders/.test(document.querySelector('#vchip').textContent)", 5000))

    # ---- the panel
    order("help", VIS.format("#vorders"))
    n_orders = ev("window.__deck.DVCMDS.filter(c => c.fn).length")
    check("the panel lists every order", ev("document.querySelectorAll('#vlist kbd').length") == n_orders + 1)
    order("computer close", HID.format("#vorders"), '"computer close" (the wake word) closes it')
    order("show the keys", HID.format("#help"))
    order("the keys", VIS.format("#help"), '"the keys" shows them again')

    # ---- getting about
    for said, room in [("take me to ten forward", "Ten Forward"), ("go to the bridge", "Main bridge"),
                       ("take me to sickbay", "Sickbay"), ("beam me to the ready room", "Ready room"),
                       ("take me to the observation lounge", "Observation lounge"),
                       ("take me to the arboretum", "Arboretum"), ("take me to the concourse", "Concourse")]:
        order(said, f"window.__deck.deck() === 8 && {ROOM} === {json.dumps(room)}", f'"{said}" -> {room}', 60000)
    order("deck twelve", "window.__deck.deck() === 12", '"deck twelve" -> deck 12', 60000)
    order("take me to deck 8", "window.__deck.deck() === 8", '"take me to deck 8" -> deck 8', 60000)
    order("take me to engineering", f"window.__deck.deck() !== 8 && /engineering/i.test({ROOM})",
          '"take me to engineering" -> its deck', 60000)
    hint("take me to the moon", "No room called")
    order("take me to the ready room", f"window.__deck.deck() === 8 && {ROOM} === 'Ready room'", "back to the ready room", 60000)
    idle()
    y0 = ev("window.__deck.yaw")
    say("turn around")
    check('"turn around" turns half a circle', abs(abs(ev("window.__deck.yaw") - y0) - math.pi) < 1e-6)
    ev("(() => { const D = window.__deck, p = D.player.position; D.goTo(p.x + 1.5, p.z); })()")
    has_walk = ev("!!window.__deck.walkTo")
    say("stop")
    check('"stop" ends a walk', has_walk and ev("!window.__deck.walkTo"))
    say("jump")
    check('"jump" jumps', ev("window.__deck.jumping"))
    hint("sit down", "Look at a chair")
    hint("stand up", "Standing already")
    order("map view", "window.__deck.top")
    order("walking view", "!window.__deck.top")
    order("turbolift", VIS.format("#liftsheet"))
    order("close", HID.format("#liftsheet"))
    order("transporter", VIS.format("#transport"))
    order("close that", HID.format("#transport"))
    order("helm", VIS.format("#helm"))
    order("close the console", HID.format("#helm"), '"close the console" closes the helm too')
    order("architect", VIS.format("#talk") + " && document.querySelector('#talkwho').textContent === 'The architect'")
    order("close", HID.format("#talk"), '"close" closes the architect')
    order("warp to the nebula", "window.__deck.warping")
    wait("!window.__deck.warping", 30000)

    # ---- PADDs
    ids = ev("[...window.__deck.rows.keys()].filter(k => typeof k === 'number').slice(0, 4)")
    a, b2 = ids[0], ids[1]
    order(f"hold entry {a}", f"window.__deck.active >= 0 && window.__deck.place.hand[window.__deck.active] === {a}")
    hint("hold entry 99999999", "No entry")
    order("put it down", "window.__deck.active === -1")
    order(f"carry entry {b2}", f"window.__deck.place.hand[window.__deck.active] === {b2}")
    order("pad 2", f"window.__deck.active === 1 && window.__deck.place.hand[1] === {a}", '"pad 2" -> the second slot')
    hint("pad 9", "Nothing in slot 9")
    # aim at the ready room's floor ahead, then pin
    ev("(() => { const D = window.__deck, p = D.player.position; D.setView(p.x, p.z, D.yaw, -0.6); })()")
    wait("window.__deck.aimInfo().aim", 10000)
    pins0 = ev("window.__deck.place.pins.length")
    order("pin it here", f"window.__deck.place.pins.length === {pins0 + 1} && !window.__deck.place.hand.includes({a})")
    look_at(a)
    order("take it", f"window.__deck.place.hand.includes({a}) && window.__deck.place.pins.length === {pins0}")
    order(f"pin entry {b2}", f"window.__deck.place.pins.length === {pins0 + 1} && !window.__deck.place.hand.includes({b2})")
    look_at(b2)
    order("take it down", f"window.__deck.place.pins.length === {pins0}", '"take it down" unpins it')
    ev("window.__deck.setView(window.__deck.player.position.x, window.__deck.player.position.z, window.__deck.yaw, 0)")
    order(f"hold entry {a}", f"window.__deck.place.hand[window.__deck.active] === {a}")
    order("shelve it", f"window.__deck.place.pins.some(q => q.e === {a} && q.f === 1) && !window.__deck.place.hand.includes({a})")
    order(f"hold entry {b2}", f"window.__deck.place.hand[window.__deck.active] === {b2}")
    order("open the pad", VIS.format("#console") + f" && window.__deck.wantRead && window.__deck.wantRead.id === {b2}")
    order("close the console", HID.format("#console"))
    # the frame has no rows in the demo: it is given the entry, and a stand-in read-out
    fw = pg.frame_locator("#cframe")
    ev(f"""(() => {{ const w = document.querySelector('#cframe').contentWindow;
      w.eval("st.sel = {{ id: {b2} }}; window.__aloud = 0; ttsAloud = () => {{ window.__aloud++; }}; window.lcarsDeckRead = () => true;"); }})()""")
    order("read it", VIS.format("#console") + " && document.querySelector('#cframe').contentWindow.__aloud === 1",
          '"read it" opens it and the console reads it out')
    order("close", HID.format("#console"))
    order("throw it", "window.__deck.thrown.length > 0 || window.__deck.place.pins.some(q => q.e === %d)" % b2)
    order(f"hold entry {a}", f"window.__deck.place.hand[window.__deck.active] === {a}")
    order("drop it", f"!window.__deck.place.hand.includes({a})")
    hint("throw it", "Nothing in hand")
    hint("start a log", "Sit at the ready room")
    hint("finish the log", "No log")

    # ---- a pile of PADDs on the ready room's desk: "pin it here" on a
    # lying tablet stacks the one in hand on top of it
    c3, d4 = ids[2], ids[3]
    wait("window.__deck.thrown.length === 0", 15000)
    ev(f"(() => {{ const D = window.__deck; D.place.pins = D.place.pins.filter(q => ![{a}, {b2}, {c3}, {d4}].includes(q.e)); D.rebuildPads(); }})()")
    pile = f"(window.__deck.place.pins.find(q => q.e === {a}) ? window.__deck.pileOf(window.__deck.place.pins.find(q => q.e === {a})) : [])"
    for e in (a, b2, c3):
        order(f"hold entry {e}", f"window.__deck.place.hand[window.__deck.active] === {e}")
        if e == a:
            check("the ready room's desk can be aimed at", ev(AIM_TABLE, ev("window.__deck.deskAt()")))
            order("pin it here", f"window.__deck.place.pins.some(q => q.e === {a})", "a PADD laid on the desk")
        else:
            look_at(a if e == b2 else b2)
            check(f"aiming at the pile with #{e} in hand is a stack", wait(f"window.__deck.aimInfo().stack", 5000))
            order("pin it here", f"{pile}.length === {3 if e == c3 else 2} && window.__deck.lastHint === 'Stacked'",
                  f'"pin it here" on the pile -> {3 if e == c3 else 2} high, hint Stacked')
    PILE = f"""(() => {{ const D = window.__deck, P = {pile}, b = P[0], T = D.THREE;
      const q0 = new T.Quaternion().fromArray(b.q);
      return {{ es: P.map(q => q.e), dy: P.slice(1).map((q, i) => q.p[1] - P[i].p[1]), step: D.PILE_STEP,
               off: P.map(q => Math.hypot(q.p[0] - b.p[0], q.p[2] - b.p[2])),
               yaw: P.map(q => q0.angleTo(new T.Quaternion().fromArray(q.q)) * 180 / Math.PI) }}; }})()"""
    st = ev(PILE)
    check(f"the pile is {a}, {b2}, {c3} from the bottom", st["es"] == [a, b2, c3])
    check("each a tablet's thickness above the one below", all(abs(d - st["step"]) < 0.0015 for d in st["dy"]) or print("        ", st))
    check("centred on the bottom one within 2.5 cm", max(st["off"]) < 0.025 or print("        ", st))
    check("the bottom one's yaw within 2.5 degrees, flat", max(st["yaw"]) < 2.5 or print("        ", st))
    # the middle one taken: the top one comes down a thickness
    ev(f"(() => {{ const D = window.__deck, o = D.padObjs.find(p => p.pin.e === {b2}).obj; D.takePad(o); }})()")
    st = ev(PILE)
    check("taking the middle one leaves two, the top come down", st["es"] == [a, c3] and abs(st["dy"][0] - st["step"]) < 0.0015 or print("        ", st))
    # thrown onto the pile: it lands on top, not through it
    order(f"hold entry {d4}", f"window.__deck.place.hand[window.__deck.active] === {d4}")
    ev(f"""(() => {{ const D = window.__deck, top = D.place.pins.find(q => q.e === {c3});
      D.throwPad(); const t = D.thrown[D.thrown.length - 1];
      t.obj.position.set(top.p[0], top.p[1] + 0.12, top.p[2]); t.v.set(0, 0, 0); t.w.set(0, 0, 0); }})()""")
    check("a PADD thrown onto the pile lands on top of it", wait(f"{pile}.length === 3 && {pile}[2].e === {d4}", 15000) or print("        ", ev(PILE)))
    keep = ev(f"{pile}.map(q => [q.e, q.p[1]])")
    # the place as saved (the demo's is localStorage), for the reload at the end
    wait(f"(JSON.parse(localStorage.getItem('lcars.deck.demo') || '{{}}').pins || []).some(q => q.e === {d4})", 10000)
    saved = ev("localStorage.getItem('lcars.deck.demo')")

    # ---- the ship
    order("open the console", VIS.format("#console"))
    order("back to the deck", HID.format("#console"))
    order("the padd", VIS.format("#menu"))
    order("close", HID.format("#menu"))
    for g in ["medium", "high", "low"]:
        order(f"graphics {g}", f"window.__deck.gfx === '{g}'")
    for s, want in [("sound on", "on"), ("sound quiet", "quiet"), ("mute", "off")]:
        order(s, f"window.__deck.sound === '{want}'")
    hint("call the crew", "reporting")
    # the one called stands in front of you: talked to, or looked past
    order("talk to them", VIS.format("#talk") + " || window.__deck.lastHint.includes('Look at someone')")
    order("close", HID.format("#talk") + " && " + HID.format("#console"))
    hint("run a program", "Stand in a holodeck")
    hint("cancel", "Nothing to cancel")

    # ---- not an order: a sentence said to somebody else moves nothing
    y1 = ev("window.__deck.yaw")
    say("the bridge was lovely today")
    pg.wait_for_timeout(300)
    check("a sentence with no order in it is left alone", ev("window.__deck.yaw") == y1 and ev("window.__deck.deck()") == 8)

    # ---- the console's own orders still work: "stand down" closes it all
    order("stand down", "!window.__deck.dv.want && document.querySelector('#vchip').hidden",
          '"stand down" (the console\'s) ends the deck\'s listening')
    check("and the microphone is closed", ev("!document.querySelector('#cframe').contentWindow.eval('vx.on')"))
    key_y()
    wait("window.__deck.dv.on", 30000)
    key_y()
    check("Y again stops listening", wait("!window.__deck.dv.want && !document.querySelector('#cframe').contentWindow.eval('vx.on')", 5000))
    key_y()
    wait("window.__deck.dv.on", 30000)
    idle()
    say("leave the deck")
    try:
        pg.wait_for_url(lambda u: not u.split("?")[0].endswith("deck.html"), timeout=15000)
        check('"leave the deck" goes to the console\'s page', True)
    except Exception:
        check('"leave the deck" goes to the console\'s page', False)
    check("no page errors", not [e for e in errs if "lcarsDeck" in e or "DVCMDS" in e or "vchip" in e] or print(errs))
    # the pile, after a reload: the same pins at the same heights. A page of
    # its own, given the saved place (the console's page, left for above,
    # keeps its worker on this origin)
    ctx2 = b.new_context(viewport={"width": 800, "height": 500})
    ctx2.add_init_script("""localStorage.setItem("lcars.deck.gfx", JSON.stringify("low"));
      localStorage.setItem("lcars.deck.sound", JSON.stringify("off"));
      localStorage.setItem("lcars.deck.demo", %s);""" % json.dumps(saved))
    pg = ctx2.new_page()
    pg.goto(URL, wait_until="domcontentloaded", timeout=120000)
    pg.wait_for_timeout(5000)
    if wait("window.__deck && window.__deck.rows.size > 0", 120000):
        got = ev(f"{pile}.map(q => [q.e, q.p[1]])")
        check("a reload keeps the pile", [g[0] for g in got] == [k[0] for k in keep] and all(abs(g[1] - k[1]) < 0.0011 for g, k in zip(got, keep)) or print("        ", got, keep))
    else:
        check("the deck boots again for the reload", False)
    b.close()

print(f"   {n_ok} checks ok, {len(fails)} failed; boot {boot:.1f}s, {time.time() - t0:.0f}s in all")
sys.exit(1 if fails else 0)
