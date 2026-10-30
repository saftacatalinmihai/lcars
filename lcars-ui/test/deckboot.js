// Does deck.html's script start? Run by test/run.sh, under node.
//
//   node test/deckboot.js [deck.html]
//
// The deck cannot be booted in headless Chromium on the VPS (a WebGL scene
// in SwiftShader needs more memory than the box has), and 0.119.0 shipped a
// variable read before its `let` (crewReal, in buildCrew), which stopped the
// whole module on every device. That class of error — a name used before its
// declaration, a typo'd identifier, a call on something that is not a
// function in our own code — happens as the top level runs, whatever three.js
// and the browser answer. So the module is run in node's `vm` with a catch-all
// stand-in for both: every property of it is another stand-in, callable and
// constructible, so the ship, the crew and the rest are "built" out of
// nothing and only the deck's own code is really exercised. Then the boot
// runs on the demo journal (`?demo`), and the frame loop for a few frames.
//
// What it cannot see: anything that depends on real values (geometry, maths
// on three.js results, what the GPU makes of a shader). It is a smoke test
// of the script's own wiring, not of the scene.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const file = process.argv[2] || path.join(__dirname, "..", "deck.html");
const html = fs.readFileSync(file, "utf8");
const m = html.match(/<script type="module">([\s\S]*?)<\/script>/);
if (!m) { console.log("   FAIL: no <script type=\"module\"> in " + file); process.exit(1); }
let src = m[1]
  .replace(/^import \* as THREE from "three";/m, "const THREE = __stub('THREE');")
  .replace(/^import \{([^}]*)\} from "three";/m, "const {$1} = __stub('addons');")
  // a vendored module imported when needed (meshopt's decoder, at boot with
  // the crew's glbs): a vm script has no dynamic import, so a stand-in module
  .replace(/\bimport\("\.\/vendor\//g, '__import("./vendor/');

const problems = [];
const loops = [];
// The stand-in. `name` is the property it was reached by, which is what lets
// the few calls worth watching be told apart.
function stub(name) {
  const f = function () {}, kept = new Map();
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.iterator) return function* () {};
      if (k === Symbol.toPrimitive) return () => 0;
      if (k === "then") return undefined;          // not a promise: `await stub` is the stub
      // nothing is anyone's child unless made so: a walk up the parents
      // (finishCell's, for a room built later) must end; nor owned by a
      // room unless registered so (disown's test reads `o.own` first)
      if (k === "parent" && !kept.has(k)) return null;
      if (k === "own" && !kept.has(k)) return undefined;
      if (!kept.has(k)) kept.set(k, stub(String(k)));
      return kept.get(k);
    },
    set(t, k, v) { kept.set(k, v); return true; },
    has() { return true; },
    apply(t, self, args) {
      // the frame loop, to be run by hand below
      if (name === "setAnimationLoop" && typeof args[0] === "function") loops.push(args[0]);
      // the boot's own catch writes what went wrong into #status
      for (const a of args) if (typeof a === "string" && /^Could not load the journal: /.test(a)) problems.push("boot: " + a);
      // pixel buffers are real arrays: the deck fills 512x512 textures a
      // byte at a time, and as stand-in properties every byte was a Map entry
      // (10s of a 13s run, for nothing the check looks at)
      if (name === "createImageData" || name === "getImageData") {
        const w = Number(args[name === "createImageData" ? 0 : 2]) || 0, h = Number(args[name === "createImageData" ? 1 : 3]) || 0;
        return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) };
      }
      return stub(name + "()");
    },
    construct() { return stub("new " + name); },
  });
}

const timers = [];
const ctx = {
  __stub: stub, __import: () => Promise.resolve(stub("module")), console: { log() {}, info() {}, debug() {}, warn() {}, error() {} },
  Math, JSON, Date, Map, Set, WeakMap, WeakSet, Promise, Array, Object, Number, String, Boolean, Symbol, Error, TypeError, RangeError,
  RegExp, Proxy, Reflect, BigInt, Intl, Float32Array, Float64Array, Uint8Array, Uint8ClampedArray, Uint16Array, Uint32Array, Int8Array,
  Int16Array, Int32Array, ArrayBuffer, DataView, Infinity, NaN, isNaN, isFinite, parseInt, parseFloat, encodeURIComponent,
  decodeURIComponent, URLSearchParams, TextDecoder, TextEncoder, AbortController,
  setTimeout: (fn, ms) => { timers.push(fn); return timers.length; }, clearTimeout() {},
  setInterval: () => 0, clearInterval() {}, requestAnimationFrame: () => 0, queueMicrotask,
  performance: { now: () => Date.now() },
  location: { search: "?demo", hash: "", href: "http://deck.test/deck.html?demo", origin: "http://deck.test", pathname: "/deck.html" },
};
for (const n of ["document", "window", "navigator", "localStorage", "sessionStorage", "matchMedia", "indexedDB", "speechSynthesis",
                 "addEventListener", "removeEventListener", "fetch", "Image", "Worker", "Blob", "URL", "AudioContext",
                 "SpeechSynthesisUtterance", "getComputedStyle", "screen", "history", "visualViewport", "OffscreenCanvas", "ImageData",
                 "DeviceOrientationEvent", "btoa", "atob", "crypto", "XMLHttpRequest", "Event", "CustomEvent", "HTMLElement",
                 "ResizeObserver", "structuredClone", "innerWidth", "innerHeight", "devicePixelRatio", "prompt", "alert", "confirm"])
  ctx[n] = stub(n);
ctx.globalThis = ctx; ctx.self = ctx;
vm.createContext(ctx);

// The module's top level, as one async function, so its awaits and its
// errors both come back here.
let done = false;
try {
  vm.runInContext("(async () => {\n" + src + "\n})().then(() => { __done(); }, e => { __fail(e); })", Object.assign(ctx, {
    __done() { done = true; },
    __fail(e) { problems.push("module: " + e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 4).join("\n      ")); done = true; },
  }), { filename: "deck.html <script type=module>" });
} catch (e) {
  problems.push("does not parse: " + e.message);
  done = true;
}

// Let the boot's awaits settle (the stand-ins answer at once), run the frame
// loop a few times, then report.
(async () => {
  for (let i = 0; i < 50 && !done; i++) await new Promise(r => setImmediate(r));
  if (!done) problems.push("the module's top level never finished");
  for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r));
  if (!loops.length && !problems.length) problems.push("no frame loop was started (renderer.setAnimationLoop)");
  for (const f of loops) {
    for (let k = 1; k <= 3; k++) {
      try { f(k * 16.7); } catch (e) { problems.push("frame " + k + ": " + e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 4).join("\n      ")); break; }
    }
  }
  if (!problems.length) readers();
  if (!problems.length) await bakedClips();
  if (!problems.length) walkers();
  if (!problems.length) roomPeople();
  if (!problems.length) voiceKeys();
  if (!problems.length) padFaces();
  if (!problems.length) dressCull();
  if (!problems.length) await architect();
  if (!problems.length) socialFlash();
  if (!problems.length) crouching();
  if (!problems.length) nightWatching();
  if (!problems.length) announcing();
  if (problems.length) {
    for (const p of problems) console.log("   FAIL " + p);
    process.exit(1);
  }
  console.log("   ok (top level, demo boot, " + loops.length * 3 + " frames, " + reading + "; " + baked + "; " + walked + "; " + peopled + "; " + spoken + "; " + faced + "; " + culled + "; " + patched + "; " + socialed + "; " + crouchd + "; " + nightd + "; " + announced + ")");
})();

// The crouch (Z, the Crouch pill, "crouch"): the eye eases down to
// CROUCH_EYE and back to EYE, a step is half a pace, Space while crouched
// rises and does not jump, a seat ends it and standing from one is standing,
// and the spoken orders reach it by their words, as the console's vMatch
// would (each a whole phrase of one order).
let crouchd = "";
function crouching() {
  const D = ctx.window.__deck, fail = m => problems.push("crouch: " + m);
  try {
    const settle = () => { for (let i = 0; i < 60; i++) D.tickBody(1 / 30); return D.body().eye; };
    const near = (a, b) => Math.abs(a - b) < 0.01;
    // the stand-in renderer is "in a headset" (any stub is truthy): a crouch is nothing there
    D.crouch();
    if (D.body().crouched) return fail("a crouch in a headset crouched");
    D.renderer.xr.isPresenting = false;
    if (D.body().seated) D.standUp();
    if (!near(settle(), D.EYE)) return fail("standing, the eye is " + D.body().eye + ", not EYE " + D.EYE);
    const pace = D.walkPace();
    D.crouch();
    if (!D.body().crouched) return fail("the toggle did not crouch");
    if (!near(settle(), D.CROUCH_EYE)) return fail("crouched, the eye is " + D.body().eye + ", not " + D.CROUCH_EYE);
    if (!(D.CROUCH_EYE > 0.6 && D.CROUCH_EYE < D.EYE * 0.65)) return fail("CROUCH_EYE " + D.CROUCH_EYE + " does not read as a crouch");
    if (Math.abs(D.walkPace() / pace - 0.5) > 1e-9) return fail("crouched, the pace is " + D.walkPace() + " of " + pace + ", not half");
    D.crouch();
    if (D.body().crouched || !near(settle(), D.EYE) || D.walkPace() !== pace) return fail("the toggle again did not stand up to EYE at the full pace");
    D.crouch(); D.jump();
    if (D.body().crouched) return fail("Space while crouched did not stand up");
    if (typeof D.jumping !== "boolean") return fail("__deck.jumping is gone: the jump cannot be checked");
    D.tickBody(1 / 30);
    if (D.jumping || D.body().jumpY > 0) return fail("Space while crouched jumped as well as standing up");
    // a seat ends it, and standing from the seat is standing
    D.crouch();
    // three.js is a stand-in here, so the seat is a plain record far from the crew
    const M = new D.THREE.Matrix4(), seat = { matrix: M, matrixWorld: M, userData: { seat: { pts: [[0, 0]], h: 0.45, dir: 1 } } };
    D.sitDown({ object: seat, point: { x: 0, y: 0.45, z: 0 } });
    if (!D.body().seated) return fail("could not sit to check the seat ends the crouch");
    if (D.body().crouched) return fail("sitting did not end the crouch");
    D.standUp();
    if (D.body().crouched || !near(settle(), D.EYE)) return fail("standing from a seat is not standing (crouched " + D.body().crouched + ", eye " + D.body().eye + ")");
    // the spoken orders, by their words
    const order = said => D.DVCMDS.filter(c => c.fn && [c.say, ...(c.alias || [])].includes(said));
    for (const w of ["crouch", "get down", "duck"]) {
      const o = order(w);
      if (o.length !== 1) return fail("\"" + w + "\" is " + o.length + " orders, not one");
      o[0].fn({});
      if (!D.body().crouched) return fail("\"" + w + "\" did not crouch");
      o[0].fn({});
      if (!D.body().crouched) return fail("\"" + w + "\" said twice stood up: an order says what it wants, it is no toggle");
      const up = order("stand up");
      if (up.length !== 1) return fail("\"stand up\" is not one order");
      up[0].fn({});
      if (D.body().crouched) return fail("\"stand up\" did not end the crouch");
    }
    settle();
    crouchd = "crouch: the eye to " + D.CROUCH_EYE + " and back, half a pace, Space and a seat stand up, 3 orders and stand up";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// The bridge at night watch (U, the Night pill, "night watch"/"day watch";
// bridge-redesign.md direction 3): the bridge's two pooled lights cut and
// given back exactly, the fill scaled on the bridge alone, the state kept in
// localStorage, and the two orders each saying what they want (no toggle).
let nightd = "";
function nightWatching() {
  const D = ctx.window.__deck, fail = m => problems.push("night watch: " + m);
  try {
    // the demo boot has no saved watch: the clock's, the device's zone
    if (!D.NIGHT.clock) return fail("the clock off by default");
    if (D.NIGHT.on !== D.watchAt(Date.now()).night) return fail("the boot at " + new Date().toString() + " left the watch " + (D.NIGHT.on ? "night" : "day") + ", not the clock's");
    D.nightWatch(false, true);
    const pools = D.NIGHT.pools || [], day = pools.map(s => s.intensity);
    if (pools.length !== 2 || day[0] !== 9 || day[1] !== 5) return fail("the bridge's two pooled lights are " + day + ", not 9 and 5");
    const order = said => D.DVCMDS.filter(c => c.fn && [c.say, ...(c.alias || [])].includes(said));
    for (const [w, on] of [["night watch", true], ["dim the lights", true], ["day watch", false], ["lights up", false]]) {
      const o = order(w);
      if (o.length !== 1) return fail("\"" + w + "\" is " + o.length + " orders, not one");
      o[0].fn({}); o[0].fn({});
      if (D.NIGHT.on !== on) return fail("\"" + w + "\" twice left the watch " + (D.NIGHT.on ? "night" : "day"));
      const kept = ctx.localStorage.getItem("lcars.deck.night");
      if (kept !== String(on)) return fail("\"" + w + "\" kept " + kept + " in localStorage");
      if (on && !pools.every((s, i) => s.intensity < day[i] * 0.3)) return fail("at night the pools are " + pools.map(s => s.intensity));
      if (!on && !pools.every((s, i) => s.intensity === day[i])) return fail("by day the pools are " + pools.map(s => s.intensity) + ", not " + day);
    }
    // By the clock, the hour stood in, in the captain's zone (EET, UTC+2,
    // from 25 Oct 2026): 23:30 is night, 07:30 day, a choice by hand holds
    // until the next change of watch, the switch off leaves it alone.
    const at = (d, h, m) => Date.UTC(2026, 9, d, h - 2, m), real = D.NIGHT.now;
    D.NIGHT.zone = "Europe/Athens"; ctx.localStorage.removeItem("lcars.deck.nighthand");
    const tick = (t, want, what) => { D.NIGHT.now = () => t; D.nightTick(); if (D.NIGHT.on !== want) throw new Error(what + " left the watch " + (D.NIGHT.on ? "night" : "day")); };
    try {
      tick(at(30, 22, 59), false, "22:59");
      tick(at(30, 23, 30), true, "23:30");
      if (!pools.every((s, i) => s.intensity < day[i] * 0.3)) return fail("night by the clock, the pools are " + pools.map(s => s.intensity));
      tick(at(31, 6, 59), true, "06:59");
      tick(at(31, 7, 30), false, "07:30");
      // by hand at 23:30: day, held through the night, the clock's again at 23:00 next
      D.NIGHT.now = () => at(31, 23, 30); order("day watch")[0].fn({});
      tick(at(31, 23, 50), false, "a day watch by hand at 23:30, at 23:50,");
      tick(at(32, 2, 0), false, "a day watch by hand at 23:30, at 02:00,");
      tick(at(32, 7, 30), false, "07:30 after the hand's day");
      tick(at(32, 23, 30), true, "the next night's 23:30");
      // by hand at noon: night, held until 23:00 (night still), gone at 07:00
      D.NIGHT.now = () => at(33, 12, 0); order("night watch")[0].fn({});
      tick(at(33, 18, 0), true, "a night watch by hand at noon, at 18:00,");
      tick(at(34, 7, 30), false, "07:30 after the hand's night");
      // the switch: off leaves it alone, kept; on takes the clock at once
      const off = order("watch by hand"), on = order("watch by the clock");
      if (off.length !== 1 || on.length !== 1) return fail("the clock's orders are " + off.length + " and " + on.length + ", not one each");
      off[0].fn({});
      if (D.NIGHT.clock || ctx.localStorage.getItem("lcars.deck.nightclock") !== "false") return fail("\"watch by hand\" left the clock " + D.NIGHT.clock + ", kept " + ctx.localStorage.getItem("lcars.deck.nightclock"));
      tick(at(34, 23, 30), false, "the clock off, 23:30");
      tick(at(35, 7, 30), false, "the clock off, 07:30");
      D.NIGHT.now = () => at(35, 23, 30); order("day watch")[0].fn({});
      on[0].fn({});
      if (!D.NIGHT.clock || !D.NIGHT.on) return fail("\"watch by the clock\" at 23:30 left the clock " + D.NIGHT.clock + ", the watch " + (D.NIGHT.on ? "night" : "day"));
      // the hint of a change by itself: on the bridge, none in Ten Forward
      if (D.deck() !== 8) D.switchDeck(8);
      const P = D.player.position, was = [P.x, P.z], clockHint = () => /by the clock/.test(D.lastHint);
      try {
        P.x = 10; P.z = -20;
        if (D.onBridge()) return fail("Ten Forward (10, -20) is the bridge");
        D.NIGHT.now = () => at(36, 12, 0); order("day watch")[0].fn({});
        tick(at(36, 23, 30), true, "in Ten Forward, 23:30");
        if (clockHint()) return fail("in Ten Forward the change of watch said \"" + D.lastHint + "\"");
        P.x = 0; P.z = -38;
        if (!D.onBridge()) return fail("(0, -38) is not the bridge");
        tick(at(37, 7, 30), false, "on the bridge, 07:30");
        if (!clockHint()) return fail("on the bridge the change of watch said \"" + D.lastHint + "\", not the clock's hint");
      } finally { [P.x, P.z] = was; }
    } catch (e) { return fail(e.message); }
    finally { D.NIGHT.now = real; D.NIGHT.zone = null; D.nightWatch(false, true); ctx.localStorage.removeItem("lcars.deck.nighthand"); }
    nightd = "night watch: the pools " + day + " cut and back, kept, 4 orders; by the clock 23:30 night, 07:30 day, the hand held a watch, the switch, the hint on the bridge only";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// The announcements (the captain's order of 2026-10-23): off by default, a
// switch of their own with two orders that each say what they want, kept;
// the deck has no road to POST /say any more (sayAloud gone).
let announced = "";
function announcing() {
  const D = ctx.window.__deck, fail = m => problems.push("announcements: " + m);
  try {
    if (D.announceOn !== false) return fail("on by default");
    if ("sayAloud" in D) return fail("the deck still has sayAloud, the server's voice");
    const order = said => D.DVCMDS.filter(c => c.fn && [c.say, ...(c.alias || [])].includes(said));
    for (const [w, on] of [["announcements on", true], ["announcements off", false], ["make announcements", true], ["no announcements", false]]) {
      const o = order(w);
      if (o.length !== 1) return fail("\"" + w + "\" is " + o.length + " orders, not one");
      o[0].fn({}); o[0].fn({});
      if (D.announceOn !== on) return fail("\"" + w + "\" twice left them " + (D.announceOn ? "on" : "off"));
      const kept = ctx.localStorage.getItem("lcars.deck.announce");
      if (kept !== String(on)) return fail("\"" + w + "\" kept " + kept + " in localStorage");
    }
    announced = "announcements: off by default, 4 orders, kept, no /say";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// Seated PADD readers (readsSeated): on deck 8 as built, someone seated
// reads, a third of the seated at most, nobody at the bridge's conn or ops,
// no two within 3 m. Decided per person, with or without a body.
let reading = "";
function readers() {
  try {
    const sat = ctx.window.__deck.crew.filter(c => c.deck === 8 && c.spec.sit != null), rd = sat.filter(c => c.reads);
    if (!rd.length) problems.push("seated readers: nobody seated on deck 8 reads a PADD");
    if (rd.length * 3 > sat.length) problems.push("seated readers: " + rd.length + " of " + sat.length + " seated on deck 8, over a third");
    if (rd.some(c => c.spec.helm)) problems.push("seated readers: someone at the conn or ops reads a PADD");
    for (const a of rd) for (const b of rd) if (a !== b && Math.hypot(a.x - b.x, a.z - b.z) < 3) problems.push("seated readers: two within 3 m");
    reading = rd.length + " of " + sat.length + " seated on deck 8 reading";
  } catch (e) { problems.push("seated readers: " + e.message); }
}

// The crew's baked clips (scripts/deck-crew-poses.py, through the crew
// pipeline into crew/clips.glb): the seated read and the weight shift are
// there, by the names the page plays them by (READ_CLIP, SHIFT_CLIP), 5 s
// and 7.5 s; the read moves the arms and the head, the shift carries the
// pelvis 1-4 cm to each side; and a seated reader's clip is the baked one
// (dressCrew's act[READ_CLIP]), none made at load any more. The glb is
// meshopt-compressed (deck-crew-assets.mjs): its views decoded with the
// page's own decoder.
let baked = "";
async function bakedClips() {
  try {
    const D = ctx.window.__deck, f = path.join(path.dirname(file), "crew", "clips.glb"), b = fs.readFileSync(f);
    const jl = b.readUInt32LE(12), j = JSON.parse(b.slice(20, 20 + jl).toString()), bin = 20 + jl + 8;
    const { MeshoptDecoder } = await import(require("url").pathToFileURL(path.join(path.dirname(file), "vendor", "meshopt_decoder-1.3.0.mjs")).href);
    await MeshoptDecoder.ready;
    const views = j.bufferViews.map(v => {
      const m = v.extensions && v.extensions.EXT_meshopt_compression;
      if (!m) return b.subarray(bin + (v.byteOffset || 0), bin + (v.byteOffset || 0) + v.byteLength);
      const out = new Uint8Array(m.count * m.byteStride);
      MeshoptDecoder.decodeGltfBuffer(out, m.count, m.byteStride, b.subarray(bin + (m.byteOffset || 0), bin + (m.byteOffset || 0) + m.byteLength), m.mode, m.filter);
      return Buffer.from(out.buffer);
    });
    const acc = i => { const a = j.accessors[i], n = { SCALAR: 1, VEC3: 3, VEC4: 4 }[a.type];
      if (a.componentType !== 5126) return null;
      const vb = views[a.bufferView], o = a.byteOffset || 0, out = [];
      for (let k = 0; k < a.count * n; k++) out.push(vb.readFloatLE(o + k * 4));
      return { n, out, max: a.max }; };
    const anim = name => j.animations.find(a => a.name === name);
    const node = ch => j.nodes[ch.target.node].name;
    const rd = anim(D.READ_CLIP), sh = anim(D.SHIFT_CLIP);
    if (!rd) problems.push("baked clips: no " + D.READ_CLIP + " in crew/clips.glb");
    if (!sh) problems.push("baked clips: no " + D.SHIFT_CLIP + " in crew/clips.glb");
    if (!rd || !sh) return;
    const len = a => Math.max(...a.channels.map(ch => acc(a.samplers[ch.sampler].input).max[0]));
    if (Math.abs(len(rd) - 5) > 0.05) problems.push("baked clips: the seated read is " + len(rd) + " s, not 5");
    if (Math.abs(len(sh) - 7.5) > 0.05) problems.push("baked clips: the shift is " + len(sh) + " s, not 7.5");
    // a bone the read takes over: its first key turned more than ~10
    // degrees from the plain sitting idle's
    const sit = anim("Sitting_Idle_Loop");
    const first = (a, bone) => { const ch = a.channels.find(c => node(c) === bone && c.target.path === "rotation"); const v = ch && acc(a.samplers[ch.sampler].output); return v && v.out.slice(0, 4); };
    for (const bone of ["upperarm_l", "lowerarm_r", "Head"]) {
      const q1 = first(rd, bone), q0 = sit && first(sit, bone);
      if (!q1 || !q0 || Math.abs(q1[0] * q0[0] + q1[1] * q0[1] + q1[2] * q0[2] + q1[3] * q0[3]) > Math.cos(0.087)) problems.push("baked clips: the seated read leaves " + bone + " as the sitting idle has it");
    }
    const pv = sh.channels.find(ch => node(ch) === "pelvis" && ch.target.path === "translation");
    const xs = pv && acc(sh.samplers[pv.sampler].output);
    const span = xs ? Math.max(...xs.out.filter((_, k) => k % 3 === 0)) - Math.min(...xs.out.filter((_, k) => k % 3 === 0)) : 0;
    if (span < 0.02 || span > 0.08) problems.push("baked clips: the shift moves the pelvis " + (span * 100).toFixed(1) + " cm side to side, not 2-8");
    if (/new THREE\.AnimationClip\("Sitting_PADD_Loop"/.test(src) || !/act\[READ_CLIP\]/.test(src)) problems.push("baked clips: a seated reader's clip is not the baked one");
    baked = "baked: " + D.READ_CLIP + " " + len(rd).toFixed(1) + " s, " + D.SHIFT_CLIP + " " + len(sh).toFixed(1) + " s, the pelvis " + (span * 100).toFixed(1) + " cm across";
  } catch (e) { problems.push("baked clips: " + e.message); }
}

// Making way (crewStep): walkCrew is plain maths on the real floor plan
// (walkable() is the deck's own, from its zones and blocks, whatever three.js
// answers), so it can be run here frame by frame. On deck 8's Ten Forward
// door, a 1.25 m gap: two walkers sent through it head-on, then a third who
// stands in the way of one, then the two again with the stander, each for
// 25 s of 60 fps; and one walking at you, who must stop. Nobody may come
// within 0.5 m of anyone, and each walker must get to the far end (the door
// is not simply blocked for good). A real boot is out of the box's reach
// (above), so this is the deck's own walking code on stand-in people.
let walked = "";
function walkers() {
  const D = ctx.window.__deck, crew = D.crew, kept = crew.splice(0);
  D.player.position.x = 60; D.player.position.z = 60;     // you, out of the way
  const there = [[0.6, -16], [0.6, -18.2], [1.6, -19], [3.4, -19], [4.2, -19.4], [8, -19.4]];
  const back = there.slice().reverse();
  const walker = (rt, n) => ({ spec: { route: rt.map((w, i) => i === rt.length - 1 ? [w[0], w[1], 1e6] : w) }, x: rt[0][0], z: rt[0][1], yaw: 0, v: 0, vs: 0, side: 0,
                               speed: 1.25, deck: D.deck(), i: 1, pause: 0, phase: 0, n, walkW: 0 });
  const stander = (x, z, n) => ({ spec: {}, x, z, yaw: Math.PI / 2, v: 0, deck: D.deck(), n });
  const runs = [["head-on at the door", [walker(there, 1), walker(back, 2)]], ["round one standing", [walker(there, 1), stander(3.0, -19.0, 0)]],
                ["head-on, one standing", [walker(back, 1), walker(there, 2), stander(5.6, -19.4, 3)]]];
  try {
    for (const [what, ppl] of runs) {
      crew.splice(0, crew.length, ...ppl);
      let min = Infinity;
      for (let f = 0; f < 25 * 60; f++) {
        for (const c of ppl) if (c.spec.route) D.walkCrew(c, 1 / 60);
        for (let a = 0; a < ppl.length; a++) for (let b = a + 1; b < ppl.length; b++) min = Math.min(min, Math.hypot(ppl[a].x - ppl[b].x, ppl[a].z - ppl[b].z));
      }
      if (min < 0.5) problems.push("crew " + what + ": two came within " + min.toFixed(2) + " m of each other");
      for (const c of ppl) {
        if (!c.spec.route) continue;
        const end = c.spec.route[c.spec.route.length - 1], left = Math.hypot(end[0] - c.x, end[1] - c.z);
        if (left > 0.2) problems.push("crew " + what + ": a walker stuck " + left.toFixed(1) + " m short, at " + c.x.toFixed(2) + "," + c.z.toFixed(2));
      }
      walked += (walked ? ", " : "crew ") + what + " " + min.toFixed(2) + " m";
    }
    // and you are still stopped for, not stepped round (walkCrew's own test)
    const w = walker(there, 1);
    crew.splice(0, crew.length, w);
    D.player.position.x = 3.0; D.player.position.z = -19.0;
    let you = Infinity;
    for (let f = 0; f < 10 * 60; f++) { D.walkCrew(w, 1 / 60); you = Math.min(you, Math.hypot(w.x - 3.0, w.z + 19.0)); }
    if (you < 0.5 || w.x > 3.0) problems.push("crew: a walker came within " + you.toFixed(2) + " m of you, or past you");
    walked += ", you " + you.toFixed(2) + " m";
  } catch (e) { problems.push("crew walkers: " + e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
  crew.splice(0, crew.length, ...kept);
}

// People in a generated deck's rooms (roomCrew): deck 12 built, and every
// room its seed staffs built twice over, taken down between. Each time the
// same people (pid, division, seated or standing, which place), at most three
// a room and DECK_ROOM_CREW a deck, those within a built room's reach of any
// spot on its streets (DROP_R) no more than CAP_NEAR; each seated one on a
// seat the room registered (seatable), no two on one place; each standing
// one at one of its work spots. And one sent off on an order is not made
// again by the room, comes back to their place, and goes with the room then.
let peopled = "";
function roomPeople() {
  const D = ctx.window.__deck, CAP_NEAR = D.ROOM_CREW_NEAR, DROP_R = 42;
  try {
    D.switchDeck(12);
    const recs = D.genRooms.filter(r => r.rm.deck === 12), staffed = recs.filter(r => r.staff);
    const total = staffed.reduce((n, r) => n + r.staff, 0);
    if (!staffed.length) { problems.push("room crew: nobody in deck 12's rooms"); return; }
    if (total > D.DECK_ROOM_CREW) problems.push("room crew: " + total + " on deck 12, over " + D.DECK_ROOM_CREW);
    for (const r of staffed) if (r.staff > 3 || !D.ROOM_CREW[r.rm.type]) problems.push("room crew: " + r.staff + " in " + r.rm.name + " (" + r.rm.type + ")");
    const dist = ([a, b, c, d], x, z) => Math.hypot(Math.max(a - x, 0, x - c), Math.max(b - z, 0, z - d));
    let near = 0;
    for (let x = -66; x <= 66; x += 0.5) for (const z of [-26, 0, 26]) near = Math.max(near, staffed.reduce((n, r) => n + (dist(r.rect, 6000 + x, z) < DROP_R ? r.staff : 0), 0));
    for (let z = -26; z <= 26; z += 0.5) for (const x of [-66, -33, 33, 66]) near = Math.max(near, staffed.reduce((n, r) => n + (dist(r.rect, 6000 + x, z) < DROP_R ? r.staff : 0), 0));
    if (near > CAP_NEAR) problems.push("room crew: " + near + " within " + DROP_R + " m of one spot, over " + CAP_NEAR);
    const mine = r => D.crew.filter(c => c.spec.home && c.spec.home.name === r.rm.name);
    const look = r => {
      const seats = D.roomSeats(r), recsOf = [...new Set(seats.map(q => q.seat))], spots = D.workSpots.filter(w => w.own === r.own);
      const taken = new Set();
      return mine(r).map(c => {
        let where = "?";
        if (c.spec.sit != null) {
          const q = c.spec.seat, i = recsOf.indexOf(q && q.seat);
          if (i < 0 || !q.seat.pts[q.k]) problems.push("room crew: someone in " + r.rm.name + " seated on no registered seat");
          where = "seat " + i + "." + (q && q.k);
          if (taken.has(where)) problems.push("room crew: two on " + where + " in " + r.rm.name);
          taken.add(where);
        } else if (c.spec.work) {
          const i = spots.findIndex(w => w.x === c.spec.at[0] && w.z === c.spec.at[1]);
          if (i < 0) problems.push("room crew: someone in " + r.rm.name + " standing at no work spot");
          where = "spot";
        }
        return c.spec.pid + " " + c.spec.uni + " " + where;
      }).join(", ");
    };
    // a cabin's occupant is who its door says, rank and all (personaOf)
    let cabins = 0;
    const named = r => {
      if (r.rm.type !== "quarters") return;
      for (const c of mine(r)) {
        cabins++;
        const door = r.rm.name.replace(/'s quarters$/, ""), p = D.personaOf(c);
        if (p.name !== door) problems.push("room crew: " + r.rm.name + "'s occupant is " + p.name + ", not " + door);
        if (!p.who.includes(door.split(" ").pop())) problems.push("room crew: " + door + "'s brief does not give their name");
      }
    };
    let n = 0;
    for (const r of staffed) {
      D.buildRoom(r); const one = look(r); n += mine(r).length; named(r); D.unbuildRoom(r);
      if (mine(r).length) problems.push("room crew: " + r.rm.name + "'s people stayed after it was taken down");
      D.buildRoom(r); const two = look(r);
      if (one !== two) problems.push("room crew: " + r.rm.name + " made other people the second time: " + one + " / " + two);
      if (r !== staffed[0]) D.unbuildRoom(r);
    }
    // an order: away, not made again; home, and gone with the room
    const r = staffed[0], c = mine(r)[0], pid = c.spec.pid, k = mine(r).length;
    c.order = { o: "stay" };
    D.unbuildRoom(r);
    if (!D.crew.includes(c)) problems.push("room crew: someone under an order went with their room");
    D.buildRoom(r);
    if (D.crew.filter(o => o.spec.pid === pid).length !== 1 || mine(r).length !== k) problems.push("room crew: the room made again someone away on an order");
    c.order = null;
    D.unbuildRoom(r);
    if (D.crew.some(o => o.spec.home)) problems.push("room crew: someone back at their place stayed after the room was taken down");
    // and "as you were" while their room is down: ended, to be made again
    D.buildRoom(r);
    const c2 = mine(r)[0];
    c2.order = { o: "stay" };
    D.unbuildRoom(r);
    D.homeCrew(c2);
    if (D.crew.includes(c2)) problems.push("room crew: someone sent home to a room not built stayed aboard");
    D.buildRoom(r);
    if (!D.crew.some(o => o.spec.pid === c2.spec.pid)) problems.push("room crew: the room did not make again someone sent home while it was down");
    D.unbuildRoom(r);
    if (!cabins) problems.push("room crew: no cabin on deck 12 has its occupant");
    peopled = "deck 12: " + total + " in " + staffed.length + " of " + recs.length + " rooms, " + near + " near one spot, " + n + " made twice alike, " + cabins + " cabins' occupants by their doors";
    // The rooms staffed since 0.252.0 (gyms, schools, hydroponics,
    // holodecks), on the decks that have them: a staffed one of each type
    // has all its people, each on a seat or at a spot it registered, and
    // the caps hold on every deck looked at (the same streets on every deck).
    const want = { gym: null, school: null, hydroponics: null, holodeck: null }, seen = [];
    for (const dn of [10, 5, 11, 22, 25, 17, 26, 23]) {
      if (Object.values(want).every(Boolean)) break;
      D.switchDeck(dn);
      const st = D.genRooms.filter(q => q.rm.deck === dn && q.staff), tot = st.reduce((m, q) => m + q.staff, 0);
      if (tot > D.DECK_ROOM_CREW) problems.push("room crew: " + tot + " on deck " + dn + ", over " + D.DECK_ROOM_CREW);
      for (const q of st) if (q.staff > 3) problems.push("room crew: " + q.staff + " in " + q.rm.name + " on deck " + dn);
      // (along this deck's own streets, every half metre: a deck's plan
      // moves them, so deck 12's lines above over-read another's)
      let nr = 0;
      for (const sg of D.planDeck(dn, 6000).segs) for (let u = 0; u <= 1; u += 0.5 / Math.max(1, sg.x1 - sg.x0 + sg.z1 - sg.z0)) {
        const x = sg.axis === "x" ? sg.x0 + u * (sg.x1 - sg.x0) : (sg.x0 + sg.x1) / 2, z = sg.axis === "x" ? (sg.z0 + sg.z1) / 2 : sg.z0 + u * (sg.z1 - sg.z0);
        nr = Math.max(nr, st.reduce((m, q) => m + (dist(q.rect, x, z) < DROP_R ? q.staff : 0), 0));
      }
      if (nr > CAP_NEAR) problems.push("room crew: " + nr + " within " + DROP_R + " m of one spot on deck " + dn + ", over " + CAP_NEAR);
      const of = {};
      for (const q of D.genRooms.filter(q => q.rm.deck === dn && q.rm.type in want)) { const o = of[q.rm.type] = of[q.rm.type] || [0, 0]; o[1]++; if (q.staff) o[0]++; }
      seen.push(dn + " (" + tot + ", " + nr + " near; " + Object.entries(of).map(([t, [a, b]]) => t + " " + a + "/" + b).join(", ") + ")");
      for (const q of st) {
        if (!(q.rm.type in want) || want[q.rm.type]) continue;
        D.buildRoom(q);
        const who = look(q), k = mine(q).length;
        if (k !== q.staff) problems.push("room crew: " + q.rm.name + " on deck " + dn + " has " + k + " of its " + q.staff);
        if (/ \?(,|$)/.test(who)) problems.push("room crew: someone in " + q.rm.name + " neither seated nor at a spot: " + who);
        D.unbuildRoom(q);
        want[q.rm.type] = q.rm.type + " " + who.replace(/\d+ /g, "");
      }
    }
    for (const [t, v] of Object.entries(want)) if (!v) problems.push("room crew: no staffed " + t + " on the decks looked at: " + seen.join("; "));
    D.switchDeck(12);
    peopled += "; decks " + seen.join("; ") + ": " + Object.values(want).join(" / ");
  } catch (e) { problems.push("room crew: " + e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

/* Every key has a spoken order (CLAUDE.md: every UI feature gets one), as
   tests.js checks the console's KEYS against VCMDS. The deck has no key
   table: its keys are the branches of its keydown handler and of the touch
   pills' handler, so each branch's line is read for the key it tests and the
   calls it makes (bar the guards and the feedback), and one of those calls,
   must be something a DVCMDS order calls, or one it calls in turn (so "put
   it down"'s putAway counts as the Q key's renderHand). A key that cycles
   where speech names the setting is in VOICE_SAME; the exemptions say why
   voice cannot. */
let spoken = "";
const VOICE_EXEMPT = {
  y: "the microphone itself: it cannot be opened by speaking into it",
  voice: "the same, as the Voice pill",
  "Escape/Enter/Space (paused)": "back into the pointer lock, which a browser grants only to a real gesture",
};
// a key that cycles, where speech says which: the orders call what it cycles through
const VOICE_SAME = { cycleSound: ["setSound"] };
const GUARDS = new Set(["anySheet", "holoHere", "playing", "locked", "preventDefault", "stopPropagation", "$", "contains", "toggle",
  "test", "includes", "closest", "toLowerCase", "add", "delete", "sayEsc", "flashHint", "sfx", "markDirty", "startAmbience",
  "lock", "if", "indexOf", "hereLift"]);
function voiceKeys() {
  try {
    const D = ctx.window.__deck, cmds = D.DVCMDS;
    const callsIn = t => [...String(t).matchAll(/([A-Za-z_$][\w$]*)\s*\(/g)].map(m => m[1]).filter(n => !GUARDS.has(n));
    // a function's body, by brace count from its declaration (or an arrow const's)
    const body = name => {
      const m = new RegExp("(?:^|\\n)(?:async )?function " + name.replace(/\$/g, "\\$") + "\\(|(?:^|\\n)const " + name + " = ").exec(src);
      if (!m) return "";
      let i = src.indexOf("{", m.index), d = 0, j = i;
      if (i < 0) return "";
      for (; j < src.length; j++) { if (src[j] === "{") d++; else if (src[j] === "}" && !--d) break; }
      return src.slice(i, j + 1);
    };
    const deep = (names, n) => { const out = new Set(names); let front = [...names];
      for (let k = 0; k < n; k++) { const next = []; for (const f of front) for (const c of callsIn(body(f))) if (!out.has(c)) { out.add(c); next.push(c); } front = next; }
      return out; };
    const reach = new Set();
    let orders = 0;
    for (const c of cmds) {
      if (!c.fn) continue;
      orders++;
      for (const n of deep(callsIn(c.fn), 1)) reach.add(n);
    }
    // the two handlers' branch lines
    const handler = (from, to) => { const i = src.indexOf(from), j = src.indexOf(to, i); return i < 0 || j < 0 ? "" : src.slice(i, j); };
    const keyH = handler('addEventListener("keydown", ev => {\n  if (ev.target.closest', 'addEventListener("keyup"');
    const tapH = handler('for (const b of tbtns.querySelectorAll("[data-t]"))', "\n  };\n");
    if (!keyH || !tapH) { problems.push("voice keys: the keydown or the touch pills' handler was not found"); return; }
    const branches = [];
    for (const line of keyH.split("\n")) {
      const ks = [...line.matchAll(/(?:\bk|ev\.key|ev\.code) === "([^"]+)"/g)].map(m => m[1]);
      if (/\[1-9\]/.test(line)) ks.push("1-9");
      if (/\["Escape", "Enter", " "\]/.test(line)) ks.push("Escape/Enter/Space (paused)");
      if (ks.length) branches.push({ key: ks.join("/"), calls: callsIn(line.replace(/^[^{]*?\)\s*(?=\{|[A-Za-z_$])/, "")) });
    }
    for (const line of tapH.split("\n")) {
      const m = /w === "([^"]+)"/.exec(line);
      if (m) branches.push({ key: m[1], calls: callsIn(line) });
    }
    let n = 0;
    for (const b of branches) {
      const ex = Object.keys(VOICE_EXEMPT).find(k => b.key === k || b.key.split("/").includes(k));
      if (ex) continue;
      n++;
      if (process.env.VK_DEBUG) console.log("   " + b.key + ": " + b.calls.join(", "));
      if (!b.calls.some(c => reach.has(c) || (VOICE_SAME[c] || []).some(h => reach.has(h))))
        problems.push(`voice keys: ${b.key} (${b.calls.join(", ") || "no call"}) has no spoken order in DVCMDS - add one, or an exemption saying why not`);
    }
    // and no phrase is two orders'
    const seen = new Map();
    for (const c of cmds) if (c.fn) for (const p of [c.say, ...(c.alias || [])]) {
      if (seen.has(p) && seen.get(p) !== c) problems.push("voice keys: \"" + p + "\" belongs to two orders");
      seen.set(p, c);
    }
    spoken = orders + " spoken orders cover " + n + " keys and pills";
  } catch (e) { problems.push("voice keys: " + e.message); }
}

// A pad's face in its markdown shape (padFace, padBody): the deck's own
// drawing onto a 2D context that records what it is asked to do, one entry
// holding every construct. The face is checked by its calls, the way the
// canvas would receive them: which text, in what font and colour, where, and
// the pills, bars, underlines and strikes drawn under and through it.
let faced = "";
function padFaces() {
  const D = ctx.window.__deck;
  const rec = () => {
    const g = { ops: [], font: "", fillStyle: "", textBaseline: "", path: null };
    const px = () => Number((/(\d+)px/.exec(g.font) || [0, 20])[1]);
    g.measureText = t => ({ width: String(t).length * px() * 0.5 });
    g.fillText = (t, x, y) => g.ops.push({ op: "text", t: String(t), x, y, font: g.font, fill: g.fillStyle });
    g.fillRect = (x, y, w, h) => g.ops.push({ op: "rect", x, y, w, h, fill: g.fillStyle });
    g.beginPath = () => { g.path = []; };
    g.moveTo = g.lineTo = g.arcTo = (x, y) => g.path && g.path.push([x, y]);
    g.closePath = () => {};
    g.fill = () => { const xs = (g.path || []).map(q => q[0]), ys = (g.path || []).map(q => q[1]); g.ops.push({ op: "fill", x: Math.min(...xs), y: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys), fill: g.fillStyle }); };
    return g;
  };
  const md = [
    "# Mission heading", "Plain **boldword** and *italword* and ~~gone~~ then `codeword` and [linkword](https://x.test/a).",
    "- top item", "\t- nested item", "3. third", "4. fourth",
    "- DONE finished thing", "- TODO open thing", "NOW worked thing", "WAITING parked thing", "LATER someday thing", "DOING busy thing",
    "> quoted words", "![alt-of-image](media/2026/10/16/x.jpg)", "type:: hidden-property",
    "```", "fencedcode()", "```", "after fence",
  ].join("\n");
  const row = { id: 9001, kind: "work_log", title: "Face test", content: md, created_at_utc: "2026-10-16 09:00:00", last_modified_at_utc: "2026-10-16 09:00:00", deleted: 0 };
  const fail = m => problems.push("pad face: " + m);
  try {
    const g = rec();
    D.padFace(g, 600, 840, row, row.id);
    const T = g.ops.filter(o => o.op === "text"), text = t => T.find(o => o.t === t);
    const under = (o, pred) => g.ops.some(r => r !== o && pred(r));
    const col = D.kindColor ? D.kindColor("work_log") : (text("Mission") || {}).fill;
    const need = ["Mission", "heading", "boldword", "italword", "gone", "codeword", "linkword", "top", "nested", "third", "fourth",
                  "finished", "open", "worked", "parked", "someday", "busy", "quoted", "fencedcode()", "after", "fence"];
    for (const w of need) if (!text(w)) fail("'" + w + "' was not drawn");
    if (problems.length) return;
    const body = text("Plain"), px = o => Number(/(\d+)px/.exec(o.font)[1]);
    if (!(px(text("Mission")) > px(body))) fail("a heading is not larger than the text (" + text("Mission").font + ")");
    if (text("Mission").fill !== text("heading").fill || text("Mission").fill === body.fill) fail("a heading is not in the kind's colour");
    if (!/^700 /.test(text("boldword").font)) fail("bold is not the bold weight: " + text("boldword").font);
    if (!/^italic /.test(text("italword").font)) fail("italic is not the italic style: " + text("italword").font);
    const strike = o => under(o, r => r.op === "rect" && r.h <= 3 && r.x <= o.x + 1 && r.y > o.y + 5 && r.y < o.y + px(o) - 5);
    const uline = o => under(o, r => r.op === "rect" && r.h <= 3 && r.x <= o.x + 1 && r.y >= o.y + px(o) - 1 && r.y <= o.y + px(o) + 4);
    if (!strike(text("gone"))) fail("~~strike~~ is not struck through");
    const code = text("codeword");
    if (!/monospace/.test(code.font)) fail("inline code is not monospace: " + code.font);
    if (!under(code, r => r.op === "fill" && r.x < code.x && r.x1 > code.x && r.y <= code.y && r.y1 >= code.y + 10)) fail("inline code has no pill under it");
    if (!uline(text("linkword"))) fail("a link is not underlined");
    if (text("Plain").x !== text("Mission").x) fail("a paragraph does not start at the text's margin");
    const dot = T.filter(o => o.t === "•");
    if (dot.length < 3) fail("list items have no dots (" + dot.length + ")");
    else if (!(dot[0].x < text("top").x && dot[1].x > dot[0].x && text("nested").x > text("top").x)) fail("a nested item is not indented past its parent");
    const n3 = text("3."), n4 = text("4.");
    if (!n3 || !n4 || !(n3.x < text("third").x)) fail("a numbered item does not hang off its number");
    const TASK = { DONE: "#99cc66", TODO: "#ffcc66", NOW: "#ff9900", WAITING: "#99ccff", LATER: "#ffcc66", DOING: "#ff9900" };
    for (const [w, c] of Object.entries(TASK)) {
      const o = text(w);
      if (!o) { fail("no " + w + " chip"); continue; }
      if (!/Antonio/.test(o.font) || o.fill !== "#000") fail(w + " is not a chip's lettering: " + o.font + " " + o.fill);
      if (!under(o, r => r.op === "fill" && r.fill === c && r.x <= o.x && r.x1 > o.x)) fail(w + "'s chip is not " + c);
    }
    if (!strike(text("finished"))) fail("a DONE task's text is not struck through");
    if (strike(text("open"))) fail("an open task's text is struck through");
    if (text("finished").x <= text("DONE").x) fail("a task's text is not after its chip");
    const qt = text("quoted");
    if (!under(qt, r => r.op === "rect" && r.w <= 6 && r.h >= 20 && r.x < qt.x && r.y <= qt.y + 4)) fail("a quote has no bar");
    if (/[>]/.test(qt.t) || T.some(o => o.t.startsWith(">"))) fail("a quote's > was drawn");
    const fc = text("fencedcode()");
    if (!/monospace/.test(fc.font)) fail("fenced code is not monospace");
    if (!under(fc, r => r.op === "rect" && r.w > 300 && r.y <= fc.y && r.y + r.h >= fc.y + 15)) fail("fenced code has no block behind it");
    if (T.some(o => o.t.includes("```"))) fail("a fence was drawn");
    if (T.some(o => /alt-of-image|!\[|hidden-property|type::/.test(o.t))) fail("an image or a property line was drawn");
    if (T.some(o => /\*\*|`|~~|\]\(/.test(o.t))) fail("markdown punctuation was drawn: " + T.filter(o => /\*\*|`|~~|\]\(/.test(o.t)).map(o => o.t).join(" "));
    if (T.some(o => o.x + o.t.length * px(o) * 0.5 > 600 - 14)) fail("text runs off the face");
    // a full face: the amber ellipsis, and nothing below it
    const g2 = rec();
    D.padFace(g2, 600, 840, { ...row, content: Array.from({ length: 80 }, (_, i) => "- TODO line " + i + " **of** many").join("\n") }, row.id);
    const T2 = g2.ops.filter(o => o.op === "text"), ell = T2.find(o => o.t === "…");
    if (!ell || ell.fill !== "#ffcc66") fail("a full face has no amber ellipsis");
    else if (T2.some(o => o.y > ell.y && o.y < 840 - 64)) fail("text was drawn below the ellipsis");
    if (!problems.length) faced = "pad face: " + T.length + " runs, " + need.length + " constructs";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// Graphics low's dressing (placeModels, tickDressing; deck-style.md part 4):
// a room's placements merge into two meshes, the dressing (DRESSING) apart,
// and on low that one is hidden past DRESS_R of its box and shown within;
// on high always. The glb is a stand-in, so the box is set by hand after.
// A dressing prop's contact patch is the dressing mesh's (its child: it
// goes with it), the furniture's the room's. The code-built dressing
// (dressGroup) is cut out of its merges by drawRange (dressOrder, dressCut);
// and a merged mesh left all collapsed stand-ins is hidden (hideStandin).
let culled = "";
// The code-built dressing: three groups' meshes in one material and some
// that are no group's, ordered and merged, then seen from near and far.
function codeDress(D, fail) {
  const rec = () => { let g; D.dressGroup({ add(x) { g = x; } }); return g.userData.dress; };
  const A = rec(), B = rec(), C = rec(), rest = { userData: {}, parent: null };
  const grp = d => ({ userData: { dress: d }, parent: null });
  const ga = grp(A), gb = grp(B), gc = grp(C);
  const mk = (p, n) => ({ parent: p, n });
  const list = [mk(rest, 6), mk(ga, 3), mk(gb, 9), mk(rest, 12), mk(ga, 6), mk(gc, 3), mk(gb, 3)];
  const con = ctx.console, warn = con.warn; let warned = 0; con.warn = () => warned++;
  let o;
  try { o = D.dressOrder(list, null); } finally { con.warn = warn; }
  const ns = o.list.map(x => x.n);
  if (o.list.length !== list.length) return fail("dressOrder lost or doubled a mesh");
  if (ns.join() !== "3,6,6,12,3,9,3") return fail("dressOrder's order " + ns.join() + ", not the first group's, the rest (a third group's among them), the second's");
  if (!warned) fail("a third group in one material was not warned of");
  const m = { userData: {}, geometry: { attributes: { position: { count: 42 } }, setDrawRange(a, c) { this.r = [a, c]; } } };
  D.dressCut(m, o.cut, ns);
  if (!A.cuts.includes(m) || !B.cuts.includes(m) || C.cuts.includes(m)) return fail("dressCut did not hand the merged mesh to its head's and tail's records alone");
  A.userData.box = [0, 0, 0, 1, 1, 1]; B.userData.box = [100, 0, 0, 101, 1, 1]; C.userData.box = [200, 0, 0, 201, 1, 1];
  for (const d of [A, B, C]) D.dressing.add(d);
  const range = (x, low = true) => { D.tickDressing({ x, y: 0.5, z: 0.5 }, low); return m.geometry.r.join(); };
  try {
    if (range(0.5) !== "0,30") fail("near the head's group, not it drawn and the tail's cut: " + m.geometry.r + " (0,30)");
    if (range(100.5) !== "9,33") fail("near the tail's group, the head not cut: " + m.geometry.r + " (9,33)");
    if (range(50) !== "9,21") fail("near neither, not both cut: " + m.geometry.r + " (9,21)");
    if (A.group.visible !== false || B.group.visible !== false || A.visible) fail("a group far off is still shown (its unmerged parts would draw)");
    if (range(50, false) !== "0,42" || A.group.visible !== true) fail("on high, a group's parts left out");
    // a group with a room is drawn from anywhere in it, however far its box
    A.userData.room = [-20, -20, 60, 20];
    if (range(50) !== "0,30") fail("on low, a group hidden from inside its own room: " + m.geometry.r + " (0,30)");
    A.userData.room = null;
  } finally { for (const d of [A, B, C]) D.dressing.delete(d); }
  // hideStandin: a merged mesh whose every range is collapsed is hidden
  const pos = { array: new Float32Array(36), count: 12, addUpdateRange() {} };
  const mm = { visible: true, userData: {}, geometry: { attributes: { position: pos } } };
  const s1 = { userData: { standin: [[mm, 0, 6]] } }, s2 = { userData: { standin: [[mm, 6, 6]] } };
  D.hideStandin(s1); D.hideStandin(s1);
  if (!mm.visible) fail("a merged mesh half collapsed (or one stand-in hidden twice) was hidden");
  D.hideStandin(s2);
  if (mm.visible) fail("a merged mesh of nothing but collapsed stand-ins is still drawn (the deck 25 mess's 21-23 k)");
}
function dressCull() {
  const D = ctx.window.__deck, fail = m => problems.push("dressing: " + m);
  try {
    const added = [], before = new Set(D.dressing);
    const parent = { updateWorldMatrix() {}, matrixWorld: stub("matrixWorld"), add(m) { added.push(m); } };
    const at = () => ({ updateWorldMatrix() {}, matrixWorld: stub("matrixWorld"), userData: {} });
    const [dr] = [...D.DRESSING][0].split("/");
    const places = [{ room: dr, prop: "a_furniture_prop", g: at(), rot: 0, scale: [1, 1, 1], standin: false, shadow: true, frame: parent },
                    ...[...D.DRESSING].filter(k => k.startsWith(dr + "/")).map(k => ({ room: dr, prop: k.split("/")[1], g: at(), rot: 0, scale: [1, 1, 1], standin: false, shadow: true, frame: parent }))];
    if (!D.placeModels({ doc: { scene: stub("scene") }, mat: stub("mat") }, places, parent, false)) return fail("placeModels placed nothing");
    const mine = [...D.dressing].filter(m => !before.has(m));
    if (added.length !== 3) return fail("a room's placements made " + added.length + " meshes, not three (the rest, the dressing, the rest's contact patches)");
    if (mine.length !== 1 || !added.includes(mine[0])) return fail("the room's dressing is not one mesh of its own in `dressing` (" + mine.length + ")");
    const m = mine[0], R = D.DRESS_R;
    // (the stand-in meshes share one userData: read it before anything else sets it)
    const patch = m.userData.patch;
    if (!patch || added.includes(patch)) return fail("the dressing's contact patches are not a mesh of the dressing's own (a hidden prop's shadow would stay)");
    m.userData.box = [0, 0, 0, 2, 1, 1];
    const look = (x, low) => { D.tickDressing({ x, y: 1.6, z: 0.5 }, low); return m.visible; };
    if (look(1, true) !== true) fail("on low, hidden from inside its box");
    if (look(2 + Math.sqrt(R * R - 0.36) - 0.05, true) !== true) fail("on low, hidden within " + R + " m");
    if (look(2 + R + 0.1, true) !== false) fail("on low, shown past " + R + " m");
    if (look(-R - 0.1, true) !== false) fail("on low, shown past " + R + " m on the other side");
    if (look(60, false) !== true) fail("on high, hidden at 60 m");
    D.dressing.delete(m);
    codeDress(D, fail);
    if (!problems.length) culled = "dressing: its own mesh and its patches, hidden on low past " + R + " m; code-built, cut by drawRange; a collapsed merge hidden";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// The social watch's notice (task_crew_social, takeRows): an open one is
// said on the HUD once, as Number One's are, and kept as said on the device
// (lcars.deck.socialSeen) so a reload does not say it again; a done one, a
// deleted one, or the same row taken again (the mirror, then /dump) is not.
// Runs after architect(), which gave the context a real localStorage.
let socialed = "";
function socialFlash() {
  const D = ctx.window.__deck, fail = m => problems.push("social notice: " + m);
  try {
    const row = { id: 990001, kind: "task_crew_social", title: "2 new comments: HN 1, GitHub 1", content: "", done_bool: 0, deleted: 0,
                  created_at_utc: "2026-10-21 09:00:00", last_modified_at_utc: "2026-10-21 09:00:00" };
    D.takeRows([row]);
    if (D.lastHint !== "New comments: 2 new comments: HN 1, GitHub 1") return fail("a new one was not said (" + D.lastHint + ")");
    const kept = JSON.parse(ctx.localStorage.getItem("lcars.deck.socialSeen") || "[]");
    if (!kept.includes(990001)) return fail("the one said was not kept for the next boot (" + JSON.stringify(kept) + ")");
    const said = () => D.lastHint;
    // flash something else, then the same row again, a done one and a deleted one: none said
    D.takeRows([{ id: 990002, kind: "task_no1", title: "marker", done_bool: 0, deleted: 0 }]);
    D.takeRows([Object.assign({}, row, { last_modified_at_utc: "2026-10-21 09:05:00" }), Object.assign({}, row, { id: 990003, done_bool: 1 }), Object.assign({}, row, { id: 990004, deleted: 1 })]);
    if (said() !== "Number One asks: marker") return fail("said again, or a done or deleted one said (" + said() + ")");
    for (const id of [990001, 990002, 990003, 990004]) D.rows.delete(id);
    socialed = "social notice: said once, kept across a boot, not when done or deleted";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 3).join("\n      ")); }
}

// The architect's patches (lcarsDeckPatch, patchSync, deckApi;
// docs/design/architect.md): a patch applied, switched off and applied
// again leaves the deck's own arrays and the values it changed as they were
// each time; a revision of the first of two re-applies the second after
// it; one that throws part-way leaves everything as it was and says on
// which line; and the design's section 9 is DECK_API_DOC, line for line,
// each verb it names there on the object a patch is handed. ?demo keeps
// patches in localStorage: a real one for this, after the boot.
let patched = "";
async function architect() {
  const D = ctx.window.__deck, P = ctx.window.lcarsDeckPatch, fail = m => problems.push("architect: " + m);
  try {
    const mem = new Map();
    ctx.localStorage = { getItem: k => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) };
    const api = D.deckApi({ id: "probe", undo: [], pending: [], names: new Set() });
    let room = "", light = "";
    for (const zn of D.zones) {
      try { const l = api.room("8/" + zn.name).lights(); if (l.length) { room = "8/" + zn.name; light = l[0]; break; } } catch (e) {}
    }
    if (!light) return fail("no room on deck 8 has a light by deckApi's names");
    const snap = () => JSON.stringify({ n: [D.lightSpots.length, D.pinnable.length, D.blocks.length, D.zones.length, D.patchObjs.size],
                                        li: D.lightSpots.map(s => [s.intensity, s.dist]), fill: D.ROOM_FILL });
    const ids = () => D.patchLive.map(l => l.id + (l.ps ? "" : "!")).join(",");
    const R = JSON.stringify(room), L = JSON.stringify(light);
    const code = k => `deck.light(${L}).intensity(${k}).range(4);\ndeck.fill(${R}).level(0.5);\nawait deck.add("thing", new deck.three.Mesh());\ndeck.onUndo(() => { globalThis.__undone = (globalThis.__undone || 0) + 1; });`;
    const s0 = snap();
    let r = await P({ id: "t-1", code: code(2), title: "brighter", room });
    if (!r.ok) return fail("a patch did not apply: " + r.err + " (line " + r.line + ")");
    const s1 = snap();
    if (s1 === s0) return fail("an applied patch changed nothing the check can see");
    r = await P({ id: "t-1" }, "off");
    if (!r.ok || snap() !== s0) return fail("a patch switched off left the deck changed");
    if (ctx.__undone !== 1) return fail("deck.onUndo's function ran " + (ctx.__undone || 0) + " times on an undo, not once");
    r = await P({ id: "t-1" }, "apply");
    if (!r.ok || snap() !== s1) return fail("a patch switched on again is not as it was applied the first time");
    r = await P({ id: "t-2", code: `deck.fill(${R}).level(2);`, title: "fuller" });
    const s2 = snap();
    r = await P({ id: "t-1", code: code(3) });
    if (!r.ok || ids() !== "t-1,t-2") return fail("a revision of the first of two did not leave both applied in order (" + ids() + ")");
    if (snap() === s2) return fail("a revision changed nothing");
    const s3 = snap();
    r = await P({ id: "t-3", code: `deck.light(${L}).intensity(5);\nthrow new Error("boom");` });
    if (r.ok || r.err !== "boom") return fail("a throwing patch was not refused with its error (" + JSON.stringify(r) + ")");
    if (r.line !== 2) return fail("a throwing patch's error is on line " + r.line + ", not 2");
    if (snap() !== s3 || ids() !== "t-1,t-2") return fail("a throwing patch left the deck changed, or itself in the list (" + ids() + ")");
    if (JSON.parse(mem.get("lcars.deck.patches") || "[]").some(c => c.id === "t-3")) return fail("a patch that failed was kept");
    await P({ id: "t-2" }, "off"); await P({ id: "t-1" }, "off");
    if (snap() !== s0) return fail("every patch off does not leave the deck as it booted");
    if (JSON.parse(mem.get("lcars.deck.patches") || "[]").length !== 2) return fail("?demo did not keep its two patches (off) in localStorage");
    // phase 2's verbs, each undone with its patch: a tick in the frame's
    // list, the sky, a fog, the room's dressing cleared, a material of its own
    const nTick = D.tickers.length, sky0 = D.skyNow(), offs = () => [...D.dressing].map(d => d.userData.off === true ? 1 : 0).join("");
    const off0 = offs();
    r = await P({ id: "t-4", room, code: `deck.tick((t, dt) => { globalThis.__ticks = (globalThis.__ticks || 0) + 1; });\ndeck.sky("nebula");\ndeck.fog("#405060", 0.05);\ndeck.dress(${R}).clear();\n` +
      `const m = new deck.three.Mesh(new deck.three.BoxGeometry(1, 1, 1), new deck.three.MeshStandardMaterial());\nawait deck.add("box", m);\ndeck.obj(deck.id + "/box").material({ color: "#ff0000", roughness: 0.2 });` });
    if (!r.ok) return fail("phase 2's verbs did not apply: " + r.err + " (line " + r.line + ")");
    if (D.tickers.length !== nTick + 1 || D.skyNow() !== "nebula" || D.patchFogs.length !== 1) return fail("deck.tick, deck.sky or deck.fog did nothing (" + [D.tickers.length - nTick, D.skyNow(), D.patchFogs.length] + ")");
    D.tickers[D.tickers.length - 1](1);
    if (ctx.__ticks !== 1) return fail("a patch's tick was not called by the frame's list");
    r = await P({ id: "t-4" }, "off");
    if (!r.ok || D.tickers.length !== nTick || D.skyNow() !== sky0 || D.patchFogs.length || offs() !== off0 || snap() !== s0)
      return fail("phase 2's verbs switched off left the deck changed (ticks " + (D.tickers.length - nTick) + ", sky " + D.skyNow() + ", fogs " + D.patchFogs.length + ")");
    r = await P({ id: "t-5", code: `deck.tick(() => { throw new Error("tock"); });` });
    D.tickers[D.tickers.length - 1](1);
    if (D.tickers.length !== nTick) return fail("a tick that throws was not stopped");
    await P({ id: "t-5" }, "off");
    // (a code-built prop by name, lifted with its footprint: test/architect.py,
    // in Chromium - the stand-ins here hold no geometry to lift)
    // a generated room's patch: applied once the room is built, undone as it
    // is dropped, applied again when it is built again (the deck 8 wings')
    const rec = D.genRooms.find(x => x.rm.deck === 8 && !x.g);
    if (!rec) return fail("no deck 8 wing room is left unbuilt to build");
    const key = rec.rm.deck + "/" + rec.rm.name, wl = () => D.lightSpots.filter(s => s.own === rec.own).map(s => s.intensity).join(",");
    r = await P({ id: "t-7", room: key, code: `deck.light(${JSON.stringify(key)}).intensity(3);` });
    if (!r.ok) return fail("a patch for an unbuilt room was refused: " + r.err);
    if (D.patchScope({ room: key }) !== "room:" + key) return fail("a wing room's patch is not in its room's scope (" + D.patchScope({ room: key }) + ")");
    D.buildRoom(rec);
    await rec.g.userData.placed; await new Promise(res => setTimeout(res, 0)); await D.patchIdle();
    const lit = (D.patchScopes.get("room:" + key) || []).map(x => x.id + (x.ps ? "" : "!")).join(",");
    if (lit !== "t-7") return fail("the room built did not apply its patch (" + lit + ")");
    const w1 = wl();
    D.unbuildRoom(rec);
    if (D.patchScopes.has("room:" + key)) return fail("the room dropped kept its patch live");
    D.buildRoom(rec);
    await rec.g.userData.placed; await new Promise(res => setTimeout(res, 0)); await D.patchIdle();
    if (wl() !== w1) return fail("the room built again is not as its patch left it the first time (" + wl() + " / " + w1 + ")");
    await P({ id: "t-7" }, "off");
    if (D.patchScopes.get("room:" + key).length) return fail("a room's patch switched off is still applied");
    D.unbuildRoom(rec);
    // the reference
    const md = fs.readFileSync(path.join(path.dirname(file), "..", "docs", "design", "architect.md"), "utf8");
    const sec = /## 9\.[^\n]*\n[\s\S]*?```\n([\s\S]*?)\n```/.exec(md);
    if (!sec) return fail("docs/design/architect.md has no section 9 with the reference in a fence");
    const doc = sec[1].split("\n").map(l => l.trimEnd()), mine = D.DECK_API_DOC.map(l => l.trimEnd());
    if (doc.join("\n") !== mine.join("\n")) {
      const i = doc.findIndex((l, k) => l !== mine[k]);
      return fail("the design's section 9 and DECK_API_DOC differ at line " + (i + 1) + ":\n        " + doc[i] + "\n        " + mine[i]);
    }
    // and the architect's brief (crew/architect.md) carries the same, verbatim:
    // the fence under "The deck API, v1"
    const brief = fs.readFileSync(path.join(path.dirname(file), "..", "crew", "architect.md"), "utf8");
    const bsec = /^The deck API, v\d+[^\n]*\n+```\n([\s\S]*?)\n```$/m.exec(brief);
    if (!bsec) return fail("crew/architect.md has no plain fence holding the API reference");
    const bdoc = bsec[1].split("\n").map(l => l.trimEnd());
    if (bdoc.join("\n") !== mine.join("\n")) {
      const i = bdoc.findIndex((l, k) => l !== mine[k]);
      return fail("crew/architect.md's reference and DECK_API_DOC differ at line " + (i + 1) + ":\n        " + bdoc[i] + "\n        " + mine[i]);
    }
    for (const l of mine) for (const m of l.matchAll(/^deck\.(\w+)|, deck\.(\w+)/g)) {
      const v = m[1] || m[2];
      if (!(v in api)) fail("DECK_API_DOC names deck." + v + ", which a patch is not handed");
    }
    patched = "architect: applied, off, on, revised in order, a throw refused at its line; tick, sky, fog, dress, material undone; a wing room's patch with its room; " + mine.length + " reference lines, the design's and the brief's";
  } catch (e) { fail(e.message + "\n      " + String(e.stack || "").split("\n").slice(1, 4).join("\n      ")); }
}
