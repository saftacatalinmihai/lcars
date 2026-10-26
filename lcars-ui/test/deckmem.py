#!/usr/bin/env python3
"""The deck's memory on a walk: a leak guard, and the ruler behind it.

The captain's phone (an iPhone 14 Pro, 393x852 at 3x, Safari, graphics
low) lagged and then lost the deck's tab after a walk round the ship: on
iOS a tab that dies is memory, the GPU's (textures, buffers, render
targets) or the JS heap. It was the heap (0.295.5): every room taken down
stayed reachable from the placements' names (placeByName), arrays and all.

This serves lcars-ui/ on a local port, opens deck.html?demo&touch in
headless Chromium at a phone's size and pixel ratio, and walks a fixed
route LOOPS times: deck 8's corridor through its wings' generated rooms,
then the lift to other decks and their rooms, and back to deck 8's
concourse, where each loop ends. Every stop records three's
renderer.info (geometries, textures, programs, calls, triangles), the
WebGL memory the page holds (every texture, buffer and renderbuffer it
has made and not deleted, counted at the WebGL calls: init script
WEBGL_COUNT below), the JS heap (performance.memory, precise, after a
collection at a loop's end), the live three.js objects (CDP's
queryObjects on Object3D's prototype: a dropped room still referenced is
thousands of them), the models in and the rooms built. Last, the context
is lost and given back (WEBGL_lose_context): the deck must say so, and
draw again after.

A loop ends where the first did, so what it holds then and what the first
held should be the same: growth from loop to loop that never comes down is
a leak. But a leak by room (that one) is filled by the first loop and
only replaced after (the same rooms, the same names), so the live objects
are measured against the boot too: at the concourse, with every other
deck down, what is alive is the boot's and the two rooms built there.
`--check` fails (exit 1) if a loop's end holds more live objects than the
boot by BOUND["objects3d_over_boot"] (the leak: +20,000; fixed: +280), if
the textures, geometries or GPU bytes at a loop's end exceed the first
loop's end by more than BOUND's (textures by none: a loop ends where the
first did, so one texture more is one made and never disposed - a crew
member's bone texture, +1 a loop until 0.299.3), if a count rises at every
loop's end, or the GL buffers do (a creep under the bounds: `--trace`
names where a texture is made),
if a context was lost on the walk, or if
the deck does not say so and draw again when one is lost and restored.
The heap is reported, not judged: after a collection it still varies
by ~150 MB from run to run (the leak was +680 MB).

Headless Chromium draws in software (SwiftShader): the bytes are what the
page asks WebGL for, which is what a phone's GPU process holds for it (an
iPhone's driver adds its own); the milliseconds are not a phone's.

Usage:  python3 test/deckmem.py [--gfx low|medium|high] [--size 393x852]
        [--scale 3] [--loops 3] [--decks 12,3] [--json OUT] [--check] [--trace]
        [--page DIR]   (~2 min a loop on the VPS; a heavy job)
"""
import argparse
import functools
import http.server
import json
import pathlib
import sys
import threading
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import killclean  # noqa: E402  (a SIGTERM takes the browser with it)

ap = argparse.ArgumentParser()
ap.add_argument("--page", default=str(HERE.parent), help="the lcars-ui directory to serve")
ap.add_argument("--gfx", default="low")
ap.add_argument("--size", default="393x852")
ap.add_argument("--scale", type=float, default=3)
ap.add_argument("--loops", type=int, default=3)
ap.add_argument("--decks", default="12,3", help="the decks visited each loop, besides 8")
ap.add_argument("--json", default="")
ap.add_argument("--check", action="store_true")
ap.add_argument("--trace", action="store_true", help="name where the textures alive at a loop's end were made, and which grew")
args = ap.parse_args()
W, H = map(int, args.size.split("x"))

# What a loop's end may hold over the first's: a little slack for what is
# made once on first need (a program's uniforms, a texture a room's first
# visit makes and every later one shares), none for a room's worth; and the
# live objects over the boot's (two rooms are ~300, a deck's leaked rooms
# were 20,000).
BOUND = {"textures": 0, "geometries": 40, "gpu_mb": 8.0, "objects3d": 100, "objects3d_over_boot": 1500}

# WebGL's own bookkeeping, counted at the context: what three asked for and
# never deleted. Sizes are estimates by format (a mip chain a third more).
# the rooms' models (ms): the KTX2 atlases' transcoder workers wait on the
# main thread between maps, and in headless Chromium's software GL a frame
# takes a second or more, so the boot's 30 maps take ~60 s here (2 s with
# the frame loop held; a phone's frames are milliseconds)
MODELS_WAIT = 180000
WEBGL_COUNT = r"""(() => {
  const M = window.__glmem = { tex: new Map(), buf: new Map(), rb: new Map(), lost: 0, restored: 0 };
  const BPP = { 0x8058: 4, 0x8C43: 4, 0x881A: 8, 0x8814: 16, 0x822F: 4, 0x8230: 8, 0x8229: 1, 0x822B: 2, 0x822D: 2, 0x8D48: 1,
                0x88F0: 4, 0x81A6: 4, 0x8CAC: 4, 0x81A5: 2, 0x8CAD: 8, 0x1908: 4, 0x1907: 3, 0x8C3A: 4, 0x8C3D: 4, 0x8DAB: 4,
                // the compressed formats a KTX2 atlas is transcoded to (bytes a
                // pixel): ASTC 4x4, ETC2 RGB(A), ETC1, S3TC DXT1/DXT5 and BC7,
                // linear and sRGB - without them a texStorage2D of one counted 4
                0x93B0: 1, 0x93D0: 1, 0x9274: 0.5, 0x9275: 0.5, 0x9278: 1, 0x9279: 1, 0x8D64: 0.5,
                0x83F0: 0.5, 0x83F1: 0.5, 0x8C4C: 0.5, 0x8C4D: 0.5, 0x83F3: 1, 0x8C4F: 1, 0x8E8C: 1, 0x8E8D: 1 };
  const bpp = f => BPP[f] || 4;
  for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) {
    if (!C) continue;
    const P = C.prototype, wrap = (n, f) => { const o = P[n]; if (o) P[n] = function (...a) { return f.call(this, o, a); }; };
    const st = gl => gl.__m || (gl.__m = { unit: 0, tex: {}, buf: {}, rb: null });
    const tb = (gl, target) => { const s = st(gl), t = target >= 0x8515 && target <= 0x851A ? 0x8513 : target; return (s.tex[s.unit] || {})[t]; };
    wrap("activeTexture", function (o, a) { st(this).unit = a[0]; return o.apply(this, a); });
    wrap("bindTexture", function (o, a) { const s = st(this); (s.tex[s.unit] || (s.tex[s.unit] = {}))[a[0]] = a[1]; return o.apply(this, a); });
    wrap("deleteTexture", function (o, a) { M.tex.delete(a[0]); return o.apply(this, a); });
    const put = (gl, target, key, bytes) => { const t = tb(gl, target); if (!t) return; const e = M.tex.get(t) || {}; e[key] = bytes; M.tex.set(t, e); };
    wrap("texStorage2D", function (o, a) { put(this, a[0], "s", a[3] * a[4] * bpp(a[2]) * (a[1] > 1 ? 4 / 3 : 1)); return o.apply(this, a); });
    wrap("texStorage3D", function (o, a) { put(this, a[0], "s", a[3] * a[4] * a[5] * bpp(a[2]) * (a[1] > 1 ? 4 / 3 : 1)); return o.apply(this, a); });
    wrap("texImage2D", function (o, a) {
      let w, h;
      if (a.length >= 8) { w = a[3]; h = a[4]; } else { const s = a[5]; w = s && (s.width || s.videoWidth || s.displayWidth) || 0; h = s && (s.height || s.videoHeight || s.displayHeight) || 0; }
      put(this, a[0], a[0] + ":" + a[1], w * h * bpp(a[2])); return o.apply(this, a);
    });
    wrap("texImage3D", function (o, a) { put(this, a[0], a[0] + ":" + a[1], a[3] * a[4] * a[5] * bpp(a[2])); return o.apply(this, a); });
    wrap("compressedTexImage2D", function (o, a) { const d = a[a.length - 1]; put(this, a[0], a[0] + ":" + a[1], d && d.byteLength || 0); return o.apply(this, a); });
    wrap("generateMipmap", function (o, a) { const t = tb(this, a[0]), e = t && M.tex.get(t); if (e && !("s" in e)) e.mip = 1; return o.apply(this, a); });
    wrap("bindBuffer", function (o, a) { st(this).buf[a[0]] = a[1]; return o.apply(this, a); });
    wrap("deleteBuffer", function (o, a) { M.buf.delete(a[0]); return o.apply(this, a); });
    wrap("bufferData", function (o, a) { const b = st(this).buf[a[0]]; if (b) M.buf.set(b, typeof a[1] === "number" ? a[1] : a[1].byteLength); return o.apply(this, a); });
    wrap("bindRenderbuffer", function (o, a) { st(this).rb = a[1]; return o.apply(this, a); });
    wrap("deleteRenderbuffer", function (o, a) { M.rb.delete(a[0]); return o.apply(this, a); });
    wrap("renderbufferStorage", function (o, a) { const r = st(this).rb; if (r) M.rb.set(r, a[2] * a[3] * bpp(a[1])); return o.apply(this, a); });
    wrap("renderbufferStorageMultisample", function (o, a) { const r = st(this).rb; if (r) M.rb.set(r, a[3] * a[4] * bpp(a[2]) * Math.max(1, a[1])); return o.apply(this, a); });
  }
  addEventListener("webglcontextlost", () => M.lost++, true);
  addEventListener("webglcontextrestored", () => M.restored++, true);
  window.__glbytes = () => {
    let tex = 0, buf = 0, rb = 0;
    for (const e of M.tex.values()) { let s = 0; for (const k in e) if (k !== "mip") s += e[k]; tex += e.mip ? s * 4 / 3 : s; }
    for (const v of M.buf.values()) buf += v;
    for (const v of M.rb.values()) rb += v;
    return { tex, buf, rb, ntex: M.tex.size, nbuf: M.buf.size, nrb: M.rb.size, lost: M.lost };
  };
})();"""

SAMPLE = """async () => {
  const d = window.__deck, r = d.renderer, g = window.__glbytes(), mb = x => Math.round(x / 1048576 * 10) / 10;
  // frames: the time between rAFs over half a second (software GL: relative only)
  const ts = []; await new Promise(ok => { const end = performance.now() + 500; const f = t => { ts.push(t); if (t < end) requestAnimationFrame(f); else ok(); }; requestAnimationFrame(f); });
  const dt = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b);
  let objs = 0; d.scene.traverse(() => objs++);
  const cv = r.domElement;
  return { deck: d.deck(), geometries: r.info.memory.geometries, textures: r.info.memory.textures, programs: (r.info.programs || []).length,
           calls: r.info.render.calls, tris: r.info.render.triangles, objects: objs,
           built: d.genRooms.filter(x => x.g).length, models: d.modelsIn(),
           gpu_tex_mb: mb(g.tex), gpu_buf_mb: mb(g.buf), gpu_rb_mb: mb(g.rb), gpu_mb: mb(g.tex + g.buf + g.rb), ntex: g.ntex, nbuf: g.nbuf, nrb: g.nrb,
           lost: g.lost, heap_mb: performance.memory ? mb(performance.memory.usedJSHeapSize) : null,
           canvas: [cv.width, cv.height], pr: r.getPixelRatio(), frame_ms: dt.length ? Math.round(dt[dt.length >> 1] * 10) / 10 : null };
}"""

# --trace: every texture made after the boot, with where it was made (a
# setter on Texture.prototype's uuid, which three's constructor assigns),
# until it is disposed. Held strongly on purpose: three keeps no reference
# of its own to a texture it uploaded (a WeakMap), so one never disposed
# can be collected in JS while its GL copy stays - the leak this looks for.
# That makes the heap meaningless with it on; the counts are not affected.
TRACE = """() => {
  const T = window.__deck.THREE, all = window.__texTrace = new Set();
  Object.defineProperty(T.Texture.prototype, "uuid", { configurable: true,
    get() { return this.__uuid; },
    set(v) {
      this.__uuid = v;
      if (this.__made) return;
      this.__made = (new Error().stack || "").split("\\n").slice(2, 10).map(l => l.trim().replace(/^at /, "").replace(/https?:[/][/][^/]+[/]/, "")).join(" < ");
      all.add(this);
      this.addEventListener("dispose", () => all.delete(this));
    } });
}"""
# the traced textures still alive, uploaded (three's properties hold a GL
# texture for them), by where they were made
TRACE_COUNT = """() => {
  const r = window.__deck.renderer, by = {};
  for (const t of window.__texTrace) {
    const p = r.properties.get(t);
    if (!p.__webglTexture && !p.__webglInit) continue;
    by[t.__made] = (by[t.__made] || 0) + 1;
  }
  return by;
}"""
traced = []

# the walkable point of a room nearest its middle, for a generated room or one of deck 8's
SPOTS = """deck => {
  const d = window.__deck, out = [];
  for (const rec of d.genRooms) {
    if (rec.rm.deck !== deck) continue;
    const [x0, z0, x1, z1] = rec.rect, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
    let best = null, bd = 1e9;
    for (let x = x0; x <= x1; x += 0.5) for (let z = z0; z <= z1; z += 0.5) {
      const zn = d.zoneAt(x, z);
      if (!zn || zn.name !== rec.rm.name || !d.walkable(x, z)) continue;
      const dd = (x - cx) ** 2 + (z - cz) ** 2;
      if (dd < bd) { bd = dd; best = [x, z, rec.rm.name]; }
    }
    if (best) out.push(best);
  }
  return out;
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=args.page))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo&touch"
samples, errs = [], []
t0 = time.time()


def live3d(cdp):
    """The three.js objects alive, reachable or not yet collected."""
    pr = cdp.send("Runtime.evaluate", {"expression": "window.__deck.THREE.Object3D.prototype"})["result"]["objectId"]
    objs = cdp.send("Runtime.queryObjects", {"prototypeObjectId": pr, "objectGroup": "census"})["objects"]["objectId"]
    n = cdp.send("Runtime.callFunctionOn", {"objectId": objs, "functionDeclaration": "function () { return this.length; }",
                                            "returnByValue": True})["result"]["value"]
    cdp.send("Runtime.releaseObjectGroup", {"objectGroup": "census"})
    return n


def stop(pg, where, loop, cdp=None):
    pg.wait_for_timeout(300)
    try:
        pg.wait_for_function("!window.__deck.modelsReady || window.__deck.modelsReady()", timeout=MODELS_WAIT)
    except Exception:
        pass
    s = pg.evaluate(SAMPLE)
    s.update(t=round(time.time() - t0, 1), at=where, loop=loop, objects3d=live3d(cdp) if cdp else None)
    samples.append(s)
    print(f"  {s['t']:6.1f}s L{loop} d{s['deck']:<2} {where[:26]:26s} geo {s['geometries']:5d} tex {s['textures']:4d} prog {s['programs']:3d} "
          f"gpu {s['gpu_mb']:7.1f}MB (tex {s['gpu_tex_mb']:6.1f} buf {s['gpu_buf_mb']:6.1f} rb {s['gpu_rb_mb']:5.1f}) heap {s['heap_mb']}MB "
          f"built {s['built']} models {s['models']}" + (f" live3d {s['objects3d']}" if cdp else "") + f" {s['frame_ms']}ms", flush=True)


def walk(pg, spots, loop, every=1):
    for x, z, name in spots[::every]:
        pg.evaluate("([x, z]) => { const d = window.__deck; d.setView(x, z, 0, -0.05); d.tickRooms(true); d.tickLights(0, true); }", [x, z])
        stop(pg, name, loop)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-precise-memory-info",
                                                "--js-flags=--expose-gc"])
    killclean.child(b)
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=args.scale, has_touch=True, is_mobile=True)
    ctx.add_init_script(WEBGL_COUNT)
    ctx.add_init_script(f"""localStorage.setItem("lcars.deck.gfx", {json.dumps(json.dumps(args.gfx))});
                           localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""")
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, timeout=120000)
    pg.wait_for_function("window.__deck", timeout=120000)
    try:
        pg.wait_for_function("window.__deck.crewReady()", timeout=60000)
    except Exception:
        pass
    pg.evaluate("""() => { const s = document.querySelector('#start'); if (s) s.classList.add('hidden'); }""")
    home = pg.evaluate("""() => { const d = window.__deck;
      for (let x = -10; x <= 10; x += 0.5) for (let z = -10; z <= 30; z += 0.5) { const zn = d.zoneAt(x, z); if (zn && zn.name === 'Concourse' && d.walkable(x, z)) return [x, z]; }
      return [0, 0]; }""")
    pg.evaluate("() => window.gc && window.gc()")
    stop(pg, "boot", 0, cdp)
    if args.trace:
        pg.evaluate(TRACE)
    decks = [int(n) for n in args.decks.split(",") if n.strip()]
    spots8 = pg.evaluate(SPOTS, 8)
    for loop in range(1, args.loops + 1):
        walk(pg, spots8, loop, max(1, len(spots8) // 8))
        for n in decks:
            pg.evaluate("n => window.__deck.switchDeck(n)", n)
            walk(pg, pg.evaluate(SPOTS, n), loop, max(1, len(pg.evaluate(SPOTS, n)) // 6))
        pg.evaluate("n => window.__deck.switchDeck(n)", 8)
        pg.evaluate("([x, z]) => { const d = window.__deck; d.setView(x, z, 0, -0.05); d.tickRooms(true); }", home)
        # as many frames as the far rooms take to go (tickRooms drops them
        # in one pass), then a collection, so the heap is what is held
        pg.wait_for_timeout(500)
        pg.evaluate("() => window.gc && window.gc()")
        stop(pg, "end of loop (concourse)", loop, cdp)
        if args.trace:
            traced.append(pg.evaluate(TRACE_COUNT))
    # the context lost and given back, as a phone's GPU process does: the
    # deck says so, and draws again (calls > 0) once it is back
    lose = pg.evaluate("""async () => {
      const d = window.__deck, ext = d.renderer.getContext().getExtension("WEBGL_lose_context");
      if (!ext) return { skipped: true };
      const frames = n => new Promise(ok => { let k = 0; const f = () => ++k >= n ? ok() : requestAnimationFrame(f); requestAnimationFrame(f); });
      ext.loseContext(); await frames(5);
      const lost = d.glLost, hint = d.hint;
      ext.restoreContext(); await frames(20);
      return { lost, hint, back: !d.glLost, calls: d.renderer.info.render.calls, after: d.hint };
    }""")
    print("context lost and restored:", lose, flush=True)
    b.close()
srv.shutdown()

ends = [s for s in samples if s["at"].startswith("end of loop")]
peak = {k: max(s[k] for s in samples) for k in ("geometries", "textures", "gpu_mb", "heap_mb", "programs")}
out = {"lose": lose, "gfx": args.gfx, "size": args.size, "scale": args.scale, "samples": samples, "ends": ends, "peak": peak, "errors": errs}
if args.json:
    pathlib.Path(args.json).write_text(json.dumps(out, indent=1))
print(f"boot: geo {samples[0]['geometries']} tex {samples[0]['textures']} gpu {samples[0]['gpu_mb']}MB heap {samples[0]['heap_mb']}MB; "
      f"peak: geo {peak['geometries']} tex {peak['textures']} gpu {peak['gpu_mb']}MB heap {peak['heap_mb']}MB")
for e in ends:
    print(f"loop {e['loop']} end: geo {e['geometries']} tex {e['textures']} gpu {e['gpu_mb']}MB heap {e['heap_mb']}MB live3d {e['objects3d']}")
for e in errs:
    print("page error:", e, file=sys.stderr)
# what the traced textures held at each loop's end, by where they were
# made; a place whose count rose from one end to the next is the leak
for i, by in enumerate(traced):
    print(f"traced at loop {i + 1} end: {sum(by.values())} textures made since the boot")
    prev = traced[i - 1] if i else {}
    for k in sorted(by, key=lambda k: -by[k]):
        if i == 0 or by[k] != prev.get(k, 0):
            print(f"  {by[k]:3d}" + (f" ({by[k] - prev.get(k, 0):+d})" if i else "") + f"  {k}")
if args.check:
    bad = []
    if any(s["lost"] for s in samples):
        bad.append("the WebGL context was lost on the walk")
    if not lose.get("skipped") and not (lose["lost"] and "Graphics memory" in (lose["hint"] or "") and lose["back"] and lose["calls"] > 0):
        bad.append(f"a lost context: {lose}")
    first, boot = (ends[0] if ends else None), samples[0]
    for e in ends:
        if e["objects3d"] - boot["objects3d"] > BOUND["objects3d_over_boot"]:
            bad.append(f"loop {e['loop']} ends with {e['objects3d']} live objects, the boot {boot['objects3d']} "
                       f"(+{e['objects3d'] - boot['objects3d']} > {BOUND['objects3d_over_boot']}): rooms taken down are still referenced")
    for e in ends[1:]:
        for k in ("textures", "geometries", "gpu_mb", "objects3d"):
            lim = BOUND[k]
            if e[k] - first[k] > lim:
                bad.append(f"loop {e['loop']} ends with {k} {e[k]}, the first loop {first[k]} (+{round(e[k] - first[k], 1)} > {lim})")
    # a creep too slow for the bounds above: up at every loop's end
    if len(ends) >= 3:
        # nbuf: GL buffers at the context, which three's geometry count
        # misses (an InstancedMesh's instanceMatrix is the mesh's own)
        for k in ("textures", "geometries", "nbuf"):
            if all(ends[i][k] > ends[i - 1][k] for i in range(1, len(ends))):
                bad.append(f"{k} rise at every loop's end ({', '.join(str(e[k]) for e in ends)}): made each loop and never "
                           "disposed (--trace names where)")
    if errs:
        bad.append(f"{len(errs)} page error(s)")
    if bad:
        print("FAIL: " + "; ".join(bad))
        sys.exit(1)
    print("ok: nothing grows from loop to loop")
