#!/usr/bin/env python3
"""Screenshots and cost of the 3D deck, at a phone's size, in its rooms.

An eyeball harness and a ruler, not an assertion suite (docs/design/deck-models.md):
it serves lcars-ui/ on a local port, opens deck.html?demo&touch (a phone:
graphics "low", no composer, the phone's light pool) in headless Chromium at
390x844, stands in the middle of each room of deck 8 (and a wing's lab and deck 12's
sickbay, generated rooms: GEN) looking each way, and
for each view writes a PNG and measures the frames: main-thread milliseconds
per frame (p50, p99) over a couple of seconds, three's draw calls and
triangles, and how many of the frames redrew the shadow maps (meant to be
drawn once; each redraw is the four spots' depth passes, a hitch on a phone). It also times the boot: navigation to the ship built, and to the
crew's models loaded.

Headless Chromium draws WebGL in software (SwiftShader), so the milliseconds
are the CPU's and a software GPU's, not a phone's: compare a run with one
made the same way on main (`--page` another checkout's lcars-ui), never with
a phone's own. Draw calls and triangles carry over as they are.

Usage:  python3 test/deckshots.py [OUT_DIR] [--page DIR] [--gfx low|medium|high]
        [--size 390x844] [--only Bridge,Ten\\ Forward] [--secs 2] [--no-models]
        [--no-hud] [--scale 3]
"""
import argparse
import functools
import http.server
import json
import math
import pathlib
import statistics
import sys
import threading
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("out", nargs="?", default=str(HERE / "deckshots"))
ap.add_argument("--page", default=str(HERE.parent), help="the lcars-ui directory to serve")
ap.add_argument("--gfx", default="low")
ap.add_argument("--size", default="390x844")
ap.add_argument("--only", default="")
ap.add_argument("--secs", type=float, default=2.0)
ap.add_argument("--shots", action=argparse.BooleanOptionalAction, default=True)
# a close look at one thing (a model, docs/design/deck-pipeline.md): NAME,x,z,yaw[,pitch],
# stood at (x, z) looking yaw (0 the bow, as above), or prop:PROP[,metres], a
# placed model (`model()` in the page) seen from its front, 1.4 m off by
# default (prop:PROP,metres,degrees: that many degrees round from it); or crew:N[,metres[,degrees]], the Nth of the crew (`__deck.crew()`,
# in buildCrew's order) seen from their front, or that many degrees round
# from it, crew:N,metres,degrees,height looking at that height, 1.3 m by
# default (the chest; 1.62 the face), or crew:ROOM the first of a generated
# room's people (built by a --gen look; --views-deck its deck); measured and shot as view-NAME.png.
# Repeatable; --only none for no rooms.
ap.add_argument("--view", action="append", default=[])
# JavaScript run in the page once it is up, before the rooms and the --view
# looks (e.g. "__deck.blinkHold(true)", every eye shut; "__deck.gtao.enabled
# = false"); repeatable, in order
ap.add_argument("--eval", action="append", default=[])
# another generated room to measure, DECK:TYPE[:K] (the Kth of that type
# on that deck, 0 the first, as GEN's), named "Deck N type" (or "Deck N
# type K") in --only; repeatable
ap.add_argument("--gen", action="append", default=[])
# the deck the --view looks are taken on (prop: finds the placements of the
# rooms built there; a generated room is built when the view comes near it)
ap.add_argument("--views-deck", type=int, default=8)
# the rooms' glbs refused (deck/<room>.glb, not the crew's): the deck as it
# is offline or before its models land, its code-built stand-ins only
ap.add_argument("--no-models", action="store_true")
# the deck's own buttons and labels hidden (the HUD, the pills, the FPS
# readout, a notice): only the 3D canvas in the picture - stills for a
# video or a page, where the deck's chrome would sit under captions
ap.add_argument("--no-hud", action="store_true")
# the device pixel ratio: 3 is a phone's (the default, what the budgets
# are measured at); a 1920x1080 still for video wants 1 or 2 (3 there is
# 5760x3240 drawn in software)
ap.add_argument("--scale", type=float, default=3)
args = ap.parse_args()
OUT = pathlib.Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
W, H = map(int, args.size.split("x"))

# the rooms of deck 8 and where to look from: each one's middle (found from
# the deck's own zones), looking to the four quarters. Yaw 0 looks toward -z,
# the bow.
ROOMS = ["Main bridge", "Corridor", "Ready room", "Observation lounge", "Ten Forward", "Arboretum", "Concourse",
         "Stellar sciences", "Sickbay"]
# and two generated rooms, built in a cell when you come near (buildRoom,
# finishCell: the other path a model takes into the page): [deck, type], the
# first room of that type on the deck. Deck 8's wings have labs; the
# sickbays of the medical deck are deck 12's, built when the view goes there
# (and deck 8 again after it). Named in --only as here.
# "corridor" is the street outside the deck's first sickbay, stood in
# mid-corridor before its door (the generated corridors' dressing, 0.222.0).
GEN = {"Wing lab": [8, "lab"], "Deck 12 sickbay": [12, "sickbay"], "Deck 12 corridor": [12, "corridor"]}
# DECK:TYPE[:K], the Kth room of that type on the deck (0, the first)
for g in args.gen:
    dn, kind, *k = g.split(":")
    GEN[f"Deck {dn} {kind}" + (f" {k[0]}" if k else "")] = [int(dn), kind, int(k[0]) if k else 0]
YAWS = [0, 1.5708, 3.1416, -1.5708]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=args.page))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo&touch"

# frames: rAF deltas would be the 60Hz clock in headless; the time inside
# the deck's own frame callback is what a slower machine would feel
MEASURE = """async secs => {
  const r = window.__deck.renderer;
  const ms = [], calls = [], tris = [];
  // a frame that drew a MeshDepthMaterial redrew the shadow maps
  let depth = false, shadowFrames = 0;
  const direct = r.renderBufferDirect;
  r.renderBufferDirect = function (cam, sc, geo, mat, ...rest) { if (mat.isMeshDepthMaterial) depth = true; return direct.call(this, cam, sc, geo, mat, ...rest); };
  let t0 = 0;
  const end = performance.now() + secs * 1000;
  await new Promise(done => {
    const tick = () => {
      const now = performance.now();
      if (t0) { ms.push(now - t0); if (depth) shadowFrames++; }
      depth = false;
      t0 = now;
      calls.push(r.info.render.calls); tris.push(r.info.render.triangles);
      if (now < end) requestAnimationFrame(tick); else done();
    };
    requestAnimationFrame(tick);
  });
  r.renderBufferDirect = direct;
  return { ms, calls, tris, shadowFrames };
}"""


def pct(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(len(a) * p))] if a else 0


# every element that neither is nor holds a canvas, hidden; run again before
# each shot, since the deck adds its notices and labels as it goes
NO_HUD = """() => {
  for (const el of document.body.querySelectorAll('*')) {
    if (el.tagName === 'CANVAS' || el.querySelector('canvas')) continue;
    el.style.setProperty('visibility', 'hidden', 'important');
  }
}"""


def shot(path):
    if args.no_hud:
        pg.evaluate(NO_HUD)
    # the concourse's views (1.3 M triangles, ~3 s a frame in software)
    # outlast playwright's 30 s for a screenshot at 3x
    pg.screenshot(path=path, timeout=180000)


def look(room, i, x, z, yaw, pitch=-0.08):
    pg.evaluate("([x, z, a, p]) => { window.__deck.setView(x, z, a, p); window.__deck.tickRooms(true); window.__deck.tickLights(0, true); }", [x, z, yaw, pitch])
    pg.wait_for_timeout(600)   # rooms built one a frame, lights eased in
    # a room built just now takes its models from the kept glb at once, or
    # when its load lands (a page before 0.220.0 has no cells' models)
    pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=60000)
    m = pg.evaluate(MEASURE, args.secs)
    v = {"room": room, "yaw": yaw, "at": [x, z],
         "p50": round(statistics.median(m["ms"]), 1) if m["ms"] else None, "p99": round(pct(m["ms"], 0.99), 1),
         "calls": max(m["calls"]) if m["calls"] else 0, "tris": max(m["tris"]) if m["tris"] else 0,
         "frames": len(m["ms"]), "shadow_frames": m["shadowFrames"]}
    report["views"].append(v)
    if args.shots:
        shot(str(OUT / f"{room.replace(' ', '_').lower()}-{i}.png"))
    print(f"  {room:20s} {i} p50 {v['p50']:6.1f}ms p99 {v['p99']:6.1f}ms calls {v['calls']:4d} tris {v['tris']:8d} shadow redraws {v['shadow_frames']}/{v['frames']}")


report = {"url": URL, "size": args.size, "gfx": args.gfx, "views": []}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=args.scale, has_touch=True, is_mobile=True)
    ctx.add_init_script(f"""localStorage.setItem("lcars.deck.gfx", {json.dumps(json.dumps(args.gfx))});
                           localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""")
    if args.no_models:
        ctx.route("**/deck/*.glb", lambda r: r.abort())
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    t = time.time()
    pg.goto(URL, timeout=120000)   # (a loaded 4-core box can take over 30 s)
    pg.wait_for_function("window.__deck", timeout=120000)
    report["boot_ms"] = round((time.time() - t) * 1000)
    try:
        pg.wait_for_function("window.__deck.crewReady()", timeout=60000)
        report["crew_ms"] = round((time.time() - t) * 1000)
    except Exception:
        report["crew_ms"] = None
    # the prop library's models (a page before 0.214.0 has none: no wait)
    try:
        pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=60000)
        report["models_ms"] = round((time.time() - t) * 1000)
        report["models_in"] = pg.evaluate("window.__deck.modelsIn ? window.__deck.modelsIn() : 0")
    except Exception:
        report["models_ms"] = None
    pg.evaluate("""() => { const s = document.querySelector('#start'); if (s) s.classList.add('hidden');
                          for (const id of ['#help', '#touchnote', '#topnote']) { const e = document.querySelector(id); if (e) e.classList.add('hidden'); } }""")
    # the floors' baked occlusion (bakeAO): ms at boot, deck 8's and
    # the cells built with it
    report["ao_boot_ms"] = pg.evaluate("window.__deck.aoStats ? Math.round(window.__deck.aoStats.ms * 10) / 10 : null")
    for js in args.eval:
        pg.evaluate(js)
    centres = pg.evaluate("""rooms => {
      const d = window.__deck, acc = {};
      for (let x = -40; x <= 40; x += 0.5) for (let z = -50; z <= 40; z += 0.5) {
        const zn = d.zoneAt(x, z);
        if (!zn || !rooms.includes(zn.name) || !d.walkable(x, z)) continue;
        const a = acc[zn.name] || (acc[zn.name] = [0, 0, 0, []]);
        a[0] += x; a[1] += z; a[2]++; a[3].push([x, z]);
      }
      const out = {};
      for (const [k, [sx, sz, n, pts]] of Object.entries(acc)) {
        // the walkable point nearest the centroid: a ring room's centroid is in its well
        const cx = sx / n, cz = sz / n;
        let best = pts[0], bd = 1e9;
        for (const q of pts) { const dd = (q[0] - cx) ** 2 + (q[1] - cz) ** 2; if (dd < bd) { bd = dd; best = q; } }
        out[k] = best;
      }
      return out;
    }""", ROOMS)
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    for room in ROOMS:
        if only and room not in only or only == ["none"]:
            continue
        if room not in centres:
            print(f"  {room}: no zone found", file=sys.stderr)
            continue
        x, z = centres[room]
        for i, yaw in enumerate(YAWS):
            look(room, i, x, z, yaw)
    deck = 8
    for room, (dn, kind, *kth) in GEN.items():
        if only and room not in only or only == ["none"]:
            continue
        if dn != deck:
            pg.evaluate("n => window.__deck.switchDeck(n)", dn)
            deck = dn
        # the walkable point of the room's own zone nearest its middle; the
        # zones are there before the room is built (genRoom)
        at = pg.evaluate("""([dn, kind, kth]) => {
          const d = window.__deck, rec = d.genRooms.filter(r => r.rm.deck === dn && r.rm.type === (kind === "corridor" ? "sickbay" : kind))[kth];
          if (!rec) return null;
          if (kind === "corridor") {
            // the corridor's middle (CW, 2.2 from its wall) before the door
            const rm = rec.rm, s = rm.door === "-z" ? -1 : 1, z = (s < 0 ? rm.z0 : rm.z1) + s * 2.2;
            return d.walkable(rm.at, z) ? [rm.at, z, "the corridor outside " + rm.name] : null;
          }
          const [x0, z0, x1, z1] = rec.rect, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
          let best = null, bd = 1e9;
          for (let x = x0; x <= x1; x += 0.25) for (let z = z0; z <= z1; z += 0.25) {
            const zn = d.zoneAt(x, z);
            if (!zn || zn.name !== rec.rm.name || !d.walkable(x, z)) continue;
            const dd = (x - cx) ** 2 + (z - cz) ** 2;
            if (dd < bd) { bd = dd; best = [x, z, rec.rm.name]; }
          }
          return best;
        }""", [dn, kind, kth[0] if kth else 0])
        if not at:
            print(f"  {room}: no {kind} on deck {dn}", file=sys.stderr)
            continue
        print(f"  {room}: {at[2]}")
        for i, yaw in enumerate(YAWS):
            look(room, i, at[0], at[1], yaw)
    if deck != args.views_deck:
        pg.evaluate("n => window.__deck.switchDeck(n)", args.views_deck)
    if any(v.startswith("prop:") for v in args.view):
        pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=60000)
    for spec in args.view:
        if spec.startswith("prop:"):
            name, *far = spec[5:].split(",")
            d = float(far[0]) if far else 1.4
            # degrees round from its front (a bed whose foot faces a wall)
            a = math.radians(float(far[1])) if len(far) > 1 else 0
            spots = [q for q in pg.evaluate("window.__deck.modelSpots()") if q["prop"] == name]
            if not spots:
                print(f"  prop {name}: not placed", file=sys.stderr)
            for k, q in enumerate(spots):
                fx = q["fx"] * math.cos(a) + q["fz"] * math.sin(a)
                fz = q["fz"] * math.cos(a) - q["fx"] * math.sin(a)
                x, z = q["x"] + fx * d, q["z"] + fz * d
                yaw = math.atan2(fx, fz)     # looking back along the front: -f
                # eye 1.6 m: down at the prop's middle, ~0.2 m over its base
                look("view", f"{name}-{k}" + (f"-{far[1]}" if len(far) > 1 else ""), x, z, yaw, -math.atan2(1.6 - q["y"] - 0.2, d))
            continue
        if spec.startswith("crew:"):
            n, *rest = spec[5:].split(",")
            d = float(rest[0]) if rest else 1.4
            a = math.radians(float(rest[1])) if len(rest) > 1 else 0
            # (or crew:ROOM, the first of a generated room's people: its
            # name as its door has it, the room built by a --gen look first)
            q = pg.evaluate("""n => { const d = window.__deck, all = typeof d.crew === 'function' ? d.crew() : d.crew;
              const c = typeof n === 'number' ? all[n] : all.find(o => o.spec.home && o.spec.home.name === n);
              return c && { x: c.x, z: c.z, yaw: c.yaw }; }""", int(n) if n.isdigit() else n)
            if not q:
                print(f"  crew {n}: nobody", file=sys.stderr)
                continue
            ya = q["yaw"] + a
            # eye 1.6 m, down at the chest (~1.3 m), or at the height given
            at = float(rest[2]) if len(rest) > 2 else 1.3
            look("view", f"crew{n}-{rest[1] if len(rest) > 1 else 0}" + (f"-{rest[2]}" if len(rest) > 2 else ""),
                 q["x"] + math.sin(ya) * d, q["z"] + math.cos(ya) * d, ya, -math.atan2(1.6 - at, d))
            continue
        name, *nums = spec.split(",")
        x, z, yaw, *pitch = map(float, nums)
        look("view", name, x, z, yaw, pitch[0] if pitch else -0.08)
    report["errors"] = errs
    b.close()
srv.shutdown()

vs = report["views"]
if vs:
    report["all"] = {"p50": round(statistics.median([v["p50"] for v in vs]), 1), "p99max": max(v["p99"] for v in vs),
                     "calls_max": max(v["calls"] for v in vs), "tris_max": max(v["tris"] for v in vs),
                     "frames": sum(v["frames"] for v in vs), "shadow_frames": sum(v["shadow_frames"] for v in vs)}
print(f"boot {report['boot_ms']}ms (occlusion bake {report.get('ao_boot_ms')}ms), crew {report['crew_ms']}ms, models {report.get('models_ms')}ms ({report.get('models_in')} rooms); views p50 {report.get('all', {}).get('p50')}ms, "
      f"worst p99 {report.get('all', {}).get('p99max')}ms, most calls {report.get('all', {}).get('calls_max')}, "
      f"most triangles {report.get('all', {}).get('tris_max')}, "
      f"shadow redraws {report.get('all', {}).get('shadow_frames')} of {report.get('all', {}).get('frames')} frames")
for e in errs:
    print("  page error:", e, file=sys.stderr)
(OUT / "report.json").write_text(json.dumps(report, indent=1))
