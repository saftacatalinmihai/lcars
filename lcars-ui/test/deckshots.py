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
        [--no-hud] [--scale 3] [--tone aces:0.9 --tone agx ...] [--match VIEW]
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
# default (prop:PROP,metres,degrees: that many degrees round from it;
# prop:PROP,metres,degrees,K the Kth placement alone, where a room places
# dozens: chairs, desks); or crew:N[,metres[,degrees]], the Nth of the crew (`__deck.crew()`,
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
# JavaScript evaluated once the looks are taken, its value kept in
# report.json's "dump" (what a look's scene holds, to debug one); repeatable
ap.add_argument("--dump", action="append", default=[])
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
# a look whose draw calls (the most in a frame of its measure) are over N
# fails the run (exit 1), after every look is taken and written; the
# report names each one over (docs/design/deck-remodel.md, slice 2)
ap.add_argument("--max-calls", type=int, default=0)
# where each look's calls go: one frame's draws grouped by the cell they
# are in (a generated room by its name, a corridor cell, the ship built at
# boot), the kind of object (merged mesh, instanced, skinned, sprite...)
# and the material (by its name in M or MX, else its type); printed (the
# top 12) and kept in report.json as "by"
ap.add_argument("--calls-by", action="store_true")
# the tone mapper on trial (deck-remodel.md slice 3): NAME[:EXPOSURE] (aces,
# agx, neutral; the page's setTone), repeatable. Each look is measured once,
# with the first, and shot once per tone as <look>-<name>.png. A tone with no
# exposure has one found by --match.
ap.add_argument("--tone", action="append", default=[])
# a room of ROOMS (Corridor): the exposure of every tone without one is the
# one that gives that room's walls (M.wallCorr, M.wall), seen from its middle
# to the four quarters, the same mean brightness as the first tone's, by
# bisection, on the frame as low draws it (renderer.render, no composer: the
# grade and GTAO would move the mean the same way for every mapper)
ap.add_argument("--match", default="")
# ROOM=I[,J...]: only those of a room's four looks (0 the bow, as YAWS),
# for ROOMS and GEN alike; repeatable
ap.add_argument("--pick", action="append", default=[])
# more of the page's query, "&"-joined after ?demo&touch (e.g. lightmap: the
# lightmap pilot, deck-remodel slice 8)
ap.add_argument("--query", default="")
args = ap.parse_args()
PICK = {k: [int(i) for i in v.split(",")] for k, v in (p.split("=", 1) for p in args.pick)}
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
URL = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo&touch" + ("&" + args.query if args.query else "")

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

# one frame's draws, grouped: cell | kind | material. A cell is the nearest
# ancestor with userData.cell (its label from genRooms, else "cell"), or the
# ship merged at boot; materials named from M and MX when the page hands
# them over (__deck.mats), else by type and a short id
CALLS_BY = """async () => {
  const d = window.__deck, r = d.renderer, names = new Map(), cells = new Map();
  for (const [set, tab] of [["M", d.mats && d.mats.M], ["MX", d.mats && d.mats.MX]]) if (tab) for (const [k, m] of Object.entries(tab)) if (m && m.isMaterial) names.set(m, set + "." + k);
  for (const rec of d.genRooms) if (rec.g) cells.set(rec.g, rec.rm.type + ":" + rec.rm.name);
  const ids = new Map();
  const mname = m => names.get(m) || (m.userData && m.userData.label) || (m.type.replace("Material", "") + "#" + (ids.has(m) ? ids.get(m) : (ids.set(m, ids.size), ids.size - 1)));
  const cellOf = o => { for (let p = o; p; p = p.parent) if (p.userData && p.userData.cell) return cells.get(p) || p.userData.label || "cell"; return "ship"; };
  const kind = o => o.isInstancedMesh ? "inst" : o.isSkinnedMesh ? "skin" : o.isBatchedMesh ? "batch" : o.isSprite ? "sprite" : o.isPoints ? "points" : o.isLine ? "line" : "mesh";
  const by = {};
  const direct = r.renderBufferDirect;
  r.renderBufferDirect = function (cam, sc, geo, mat, obj, ...rest) {
    if (!mat.isMeshDepthMaterial && !mat.isMeshDistanceMaterial) { const k = cellOf(obj) + " | " + kind(obj) + " | " + mname(mat); by[k] = (by[k] || 0) + 1; }
    return direct.call(this, cam, sc, geo, mat, obj, ...rest);
  };
  // the deck draws in its own rAF callback, before ours in the same frame:
  // the first callback clears what came before it, the second ends after
  // exactly one whole frame
  await new Promise(done => requestAnimationFrame(() => { for (const k in by) delete by[k]; requestAnimationFrame(done); }));
  r.renderBufferDirect = direct;
  return by;
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


# the mean display luma (sRGB, Rec. 709 weights) of a room's walls' pixels,
# over the four looks: each look's mask is a grid of rays, kept where the
# first hit is a wall material; each step renders the frame as low does and
# reads it back in the same task (the drawing buffer is not kept past it)
WALL_MEAN = """([name, exposure, at]) => {
  const d = window.__deck, r = d.renderer, gl = r.getContext(), walls = new Set([d.M.wallCorr, d.M.wall]);
  const W = gl.drawingBufferWidth, H = gl.drawingBufferHeight, b = new Uint8Array(W * H * 4);
  // a raycaster does not ask visible: a hidden deck's walls would answer
  const shown = o => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
  const masks = window.__wallMasks || (window.__wallMasks = []);
  d.setTone(name, exposure);
  let s = 0, n = 0;
  at.forEach(([x, z, a, p], k) => {
    // the frame loop turns the player and tips the camera (its child) from
    // setView's yaw and pitch; here, in one task, it is done by hand
    d.setView(x, z, a, p);
    d.player.rotation.y = a; d.camera.rotation.x = p;
    d.player.updateMatrixWorld(true);
    if (!masks[k]) {
      const ray = new d.THREE.Raycaster(), px = [];
      for (let j = 0; j < 40; j++) for (let i = 0; i < 20; i++) {
        const u = (i + 0.5) / 20, v = (j + 0.5) / 40;
        ray.setFromCamera(new d.THREE.Vector2(u * 2 - 1, 1 - v * 2), d.camera);
        const hit = ray.intersectObject(d.scene, true).find(h => h.object.isMesh && shown(h.object) && h.distance > d.camera.near);
        if (!hit) continue;
        const m = Array.isArray(hit.object.material) ? hit.object.material[hit.face.materialIndex] : hit.object.material;
        if (walls.has(m)) px.push([u, 1 - v]);
      }
      masks[k] = px;
    }
    r.setRenderTarget(null);
    r.render(d.scene, d.camera);
    // one read of the frame: a readPixels a pixel is a stall each (0.302's
    // first run spent 40 minutes here)
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, b);
    // the mask in fractions of the frame: the deck steps its pixel ratio
    // down when frames are slow (tickResolution), mid-match included
    for (const [u, v] of masks[k]) { const i = (Math.floor(v * H) * W + Math.floor(u * W)) * 4; s += 0.2126 * b[i] + 0.7152 * b[i + 1] + 0.0722 * b[i + 2]; n++; }
  });
  return { n, mean: n ? s / n : 0 };
}"""


def match_tones(room, x, z):
    at = [[x, z, yaw, -0.08] for yaw in YAWS]
    for v in at:   # each look's rooms built and lit, as look() waits
        pg.evaluate("([x, z, a, p]) => { window.__deck.setView(x, z, a, p); window.__deck.tickRooms(true); window.__deck.tickLights(0, true); }", v)
        pg.wait_for_timeout(600)
    pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=MODELS_WAIT)
    t0, e0 = TONES[0]
    ref = pg.evaluate(WALL_MEAN, [t0, e0, at])
    report["match"] = {"room": room, "pixels": ref["n"], "target": round(ref["mean"], 2), "means": {t0: round(ref["mean"], 2)}}
    print(f"  match in the {room}: {ref['n']} wall pixels over 4 looks, {t0} at {e0}: mean {ref['mean']:.2f}")
    for k, (t, e) in enumerate(TONES):
        if e:
            continue
        lo, hi = 0.2, 4.0
        for _ in range(12):
            mid = (lo + hi) / 2
            if pg.evaluate(WALL_MEAN, [t, mid, at])["mean"] < ref["mean"]:
                lo = mid
            else:
                hi = mid
        e = round((lo + hi) / 2, 3)
        got = pg.evaluate(WALL_MEAN, [t, e, at])["mean"]
        TONES[k] = (t, e)
        report["match"]["means"][t] = round(got, 2)
        print(f"  match: {t} at {e}: mean {got:.2f}")
    pg.evaluate("t => window.__deck.setTone(t[0], t[1])", list(TONES[0]))
    report["tones"] = dict(TONES)


def look(room, i, x, z, yaw, pitch=-0.08):
    pg.evaluate("([x, z, a, p]) => { window.__deck.setView(x, z, a, p); window.__deck.tickRooms(true); window.__deck.tickLights(0, true); }", [x, z, yaw, pitch])
    pg.wait_for_timeout(600)   # rooms built one a frame, lights eased in
    # a room built just now takes its models from the kept glb at once, or
    # when its load lands (a page before 0.220.0 has no cells' models)
    pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=MODELS_WAIT)
    m = pg.evaluate(MEASURE, args.secs)
    # (i: the look's index, or a --view's name; with the pitch, a look can
    # be taken again from the same spot on another page: a prop main lacks)
    v = {"room": room, "yaw": yaw, "at": [x, z], "look": i, "pitch": pitch,
         "p50": round(statistics.median(m["ms"]), 1) if m["ms"] else None, "p99": round(pct(m["ms"], 0.99), 1),
         "calls": max(m["calls"]) if m["calls"] else 0, "tris": max(m["tris"]) if m["tris"] else 0,
         "frames": len(m["ms"]), "shadow_frames": m["shadowFrames"]}
    if args.calls_by:
        by = pg.evaluate(CALLS_BY)
        v["by"] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
        cellsum = {}
        for k, n in by.items():
            c = k.split(" | ")[0]
            cellsum[c] = cellsum.get(c, 0) + n
        v["by_cell"] = dict(sorted(cellsum.items(), key=lambda kv: -kv[1]))
    report["views"].append(v)
    if args.shots and TONES:
        for t, e in TONES:
            pg.evaluate("t => window.__deck.setTone(t[0], t[1])", [t, e])
            # three frames: the programs recompiled, OutputPass's rebuilt
            pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))")
            shot(str(OUT / f"{room.replace(' ', '_').lower()}-{i}-{t}.png"))
        pg.evaluate("t => window.__deck.setTone(t[0], t[1])", list(TONES[0]))
    elif args.shots:
        shot(str(OUT / f"{room.replace(' ', '_').lower()}-{i}.png"))
    if args.calls_by:
        print("      by cell: " + ", ".join(f"{c} {n}" for c, n in list(v["by_cell"].items())[:8]))
        for k, n in list(v["by"].items())[:12]:
            print(f"      {n:4d}  {k}")
    print(f"  {room:20s} {i} p50 {v['p50']:6.1f}ms p99 {v['p99']:6.1f}ms calls {v['calls']:4d} tris {v['tris']:8d} shadow redraws {v['shadow_frames']}/{v['frames']}")


# the rooms' models (ms): the KTX2 atlases' transcoder workers wait on the
# main thread between maps, and in headless Chromium's software GL a frame
# takes a second or more, so the boot's 30 maps take ~60 s here (2 s with
# the frame loop held; a phone's frames are milliseconds)
MODELS_WAIT = 180000
report = {"url": URL, "size": args.size, "gfx": args.gfx, "views": []}
TONES = [(t.split(":")[0], float(t.split(":")[1]) if ":" in t else 0) for t in args.tone]
if TONES and not TONES[0][1]:
    sys.exit("deckshots: the first --tone needs its exposure (aces:0.9): the others are matched to it")
if any(not e for _, e in TONES) and not args.match:
    sys.exit("deckshots: a --tone with no exposure needs --match")
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
    # and the console's errors: a shader three could not compile is one,
    # and only that (its mesh is simply not drawn)
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text[:2000]))
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
        pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=MODELS_WAIT)
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
    if args.match:
        if args.match not in centres:
            sys.exit(f"deckshots: --match {args.match}: no such room of {ROOMS}")
        match_tones(args.match, *centres[args.match])
    report["tones"] = dict(TONES)
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    for room in ROOMS:
        if only and room not in only or only == ["none"]:
            continue
        if room not in centres:
            print(f"  {room}: no zone found", file=sys.stderr)
            continue
        x, z = centres[room]
        for i, yaw in enumerate(YAWS):
            if room in PICK and i not in PICK[room]:
                continue
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
            if room in PICK and i not in PICK[room]:
                continue
            look(room, i, at[0], at[1], yaw)
    if deck != args.views_deck:
        pg.evaluate("n => window.__deck.switchDeck(n)", args.views_deck)
    if any(v.startswith("prop:") for v in args.view):
        pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=MODELS_WAIT)
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
                if len(far) > 2 and k != int(far[2]):
                    continue
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
    report["dump"] = [pg.evaluate(js) for js in args.dump]
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
over = [v for v in vs if args.max_calls and v["calls"] > args.max_calls]
report["max_calls"] = args.max_calls or None
report["over"] = [f"{v['room']} {v['yaw']}: {v['calls']}" for v in over]
(OUT / "report.json").write_text(json.dumps(report, indent=1))
if over:
    print(f"FAIL: {len(over)} look(s) over {args.max_calls} calls: " + "; ".join(report["over"]), file=sys.stderr)
    sys.exit(1)
elif args.max_calls:
    print(f"calls: every look at most {args.max_calls}")
