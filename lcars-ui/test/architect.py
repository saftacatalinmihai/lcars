#!/usr/bin/env python3
"""The architect's patches on the deck (docs/design/architect.md, phase 1).

Serves lcars-ui/ on a local port and opens deck.html?demo in headless
Chromium (graphics low), stands in Ten Forward and hands a patch to
lcarsDeckPatch directly, as the console's architect thread will: the
patch lifts one of the room's models out of its merged mesh and moves it.
Then: one draw call more from the same view, and the picture changed
(--out keeps the two pictures); the patch kept in localStorage (?demo's
store) and applied again after a reload; revised in place; switched off
(the model back in its merged mesh); a patch that froze the last load
skipped; ?nopatch applying none; I opening the architect's sheet with the
patch listed; what the deck tells the architect (lcarsDeckSees) and its
picture (lcarsDeckShot, a JPEG at most 1024 px wide). Phase 2: a
generated room, the first wing lab, walked into (tickRooms builds it):
its code-built chair named, the room's inventory, a patch to the chair
written while the room is down, applied when it is built (the chair lifted
and hidden, its footprint gone, a round stool in its material, two draw
calls), undone when walked away from, replayed after a reload, the
footprint back as built when switched off; Ten Forward's table's footprint
moving with it.

Then the round trip, against a scratch server (built from the lcars-release
line, an empty journal, /ui/ served from --page) with claude stood in for
by a script that streams a fenced patch: the deck (not ?demo) opens the
architect's sheet, the console in its frame sends "move <the model>
nearer" with what the deck sees and its picture attached; the patch
applies while the stand-in still holds the rest of its answer; once the
answer ends the console has written the deck_patch entry (through the API,
as the page); a reload replays it from the entry; the sheet's switch keeps
it off in the entry by a guarded PATCH from a fresh read (a write from
elsewhere in between is kept); and a patch that fails goes back to the
architect by itself, once, as a line of the page's, the fixed one written.

Usage:  nice -n 19 python3 test/architect.py [--page DIR] [--out DIR] [-v]
        LCARS_TEST_BIN=/path/to/lcars python3 test/architect.py   # no build
        python3 test/architect.py --no-server                    # ?demo only
        python3 test/architect.py --round-trip                   # the round trip only
Takes ~4-6 min (the ship in software WebGL, five boots, a build); exits 1
on a failure.
"""
import argparse
import base64
import functools
import http.client
import http.server
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import killclean  # noqa: E402  (its scratch and its server go when the run is killed)
from caldav import build, free_port  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument("--page", default=str(HERE.parent), help="the lcars-ui directory to serve")
ap.add_argument("--out", default="", help="a directory for Ten Forward before and after the patch")
ap.add_argument("-v", action="store_true", help="every check, not only the failures")
ap.add_argument("--no-server", action="store_true", help="the ?demo half only: no scratch server, no round trip")
ap.add_argument("--round-trip", action="store_true", help="the round trip only (iterating on the console's side)")
args = ap.parse_args()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=args.page))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo"

fails = []
n_ok = 0


def check(name, cond, why=""):
    global n_ok
    if cond:
        n_ok += 1
        if args.v:
            print("   ok   " + name)
    else:
        fails.append(name)
        print("   FAIL " + name + (": " + why if why else ""))
    return cond


def ev(js, arg=None):
    return pg.evaluate(js, arg) if arg is not None else pg.evaluate(js)


def wait(js, timeout=30000):
    # polled from here, as deckvoice.py does: wait_for_function starves on the deck
    end = time.time() + timeout / 1000
    while True:
        try:
            if pg.evaluate(js):
                return True
        except Exception:
            pass
        if time.time() > end:
            return False
        pg.wait_for_timeout(200)


def boot(url):
    pg.goto(url, wait_until="domcontentloaded", timeout=120000)
    pg.wait_for_timeout(4000)
    if not wait("window.__deck && window.__deck.rows.size > 0 && window.__deck.modelsReady()", 180000):
        try:
            why = ev("""(() => { const D = window.__deck; return D ? 'rows ' + D.rows.size + ', models ' + D.modelsReady() : 'no __deck: ' +
              (document.querySelector('#status') || {}).textContent + ' at ' + location.href + ' ' + document.title + ' ' + document.body?.textContent.slice(0, 200); })()""")
        except Exception as e:
            why = str(e)
        sys.exit("   FAIL the deck did not boot, or its models never landed: " + str(why)[:300])
    # the patches are applied once the models are in, on the patch queue
    wait("window.__deck.patchLive.length > 0 || window.__deck.NOPATCH || !window.__deck.patchAll().some(c => c.on)", 30000)


# Stand in Ten Forward's middle, looking at the chosen model (`NAME`).
STAND = """name => { const D = window.__deck, p = D.placeByName.get(name), T = D.THREE, w = new T.Vector3();
  (p.lifted ? p.lifted.m : p.g).getWorldPosition(w);
  let x = w.x - 2.2, z = w.z + 2.2;
  for (let k = 0; k < 16 && !D.walkable(x, z); k++) { const a = k * Math.PI / 8; x = w.x + Math.sin(a) * 2.4; z = w.z + Math.cos(a) * 2.4; }
  const dx = w.x - x, dz = w.z - z;
  D.setView(x, z, Math.atan2(-dx, -dz), Math.atan2(w.y + 0.6 - 1.6, Math.hypot(dx, dz)));
  return [x, z]; }"""
# one real frame drawn from the view, and its draw calls
CALLS = """() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(window.__deck.renderer.info.render.calls))))"""
WHERE = "name => { const D = window.__deck, p = D.placeByName.get(name); const w = new D.THREE.Vector3(); (p.lifted ? p.lifted.m : p.g).getWorldPosition(w); return [w.x, w.y, w.z, !!p.lifted]; }"
# the model's own vertices in its room's merged mesh: all zero while lifted
RANGE = "name => { const p = window.__deck.placeByName.get(name), L = p.lift, a = L.mesh.geometry.attributes.position.array; let s = 0; for (let i = L.at * 3; i < (L.at + L.n) * 3; i++) s += Math.abs(a[i]); return s; }"
PATCH = "([c, op]) => window.lcarsDeckPatch(c, op || 'apply')"
# a model of Ten Forward's that stands in the room (a table, a chair)
PICK = """(() => { const D = window.__deck, all = [...D.placeByName.values()].filter(p => p.roomKey === '8/Ten Forward' && p.lift && p.lift.mesh);
  const pick = all.find(p => /table/.test(p.prop)) || all[0]; return pick ? pick.name : ''; })()"""


def shoot(name):
    # the canvas alone, as the architect is shown it (lcarsDeckShot): the
    # start card and the keys' list are the page's, over it
    import base64
    b64 = ev("""async () => { const b = await window.lcarsDeckShot(1024); const r = new FileReader();
      return await new Promise(ok => { r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(b); }); }""")
    (pathlib.Path(args.out) / name).write_bytes(base64.b64decode(b64))

# ---- a generated room (phase 2): the first wing lab on deck 8 ----
# Its patches apply when it is built (buildRoom, once its models are placed)
# and are undone before it is dropped (unbuildRoom), so the room is walked
# into and out of as the captain would: tickRooms builds what is near.
GEN_REC = "window.__deck.genRooms.find(r => r.rm.deck === 8 && r.rm.type === 'lab')"
GO_IN = f"""(() => {{ const D = window.__deck, r = {GEN_REC}, [a, b, c, d] = r.rect; D.setView((a + c) / 2, (b + d) / 2, 0, -0.2); return r.rm.deck + '/' + r.rm.name; }})()"""
GO_OUT = "name => { const D = window.__deck, p = D.placeByName.get(name), w = new D.THREE.Vector3(); p.g.getWorldPosition(w); D.setView(w.x - 2.2, w.z + 2.2, 0, 0); }"
# 1.8 m from the prop toward the room's middle, looking at it
LOOKP = f"""name => {{ const D = window.__deck, p = D.propByName.get(name), r = {GEN_REC}, [a, b, c, d] = r.rect, w = new D.THREE.Vector3();
  p.g.getWorldPosition(w); let ux = (a + c) / 2 - w.x, uz = (b + d) / 2 - w.z; const l = Math.hypot(ux, uz) || 1; ux /= l; uz /= l;
  const x = w.x + ux * 1.8, z = w.z + uz * 1.8; D.setView(x, z, Math.atan2(ux, uz), Math.atan2(0.5 - 1.6, 1.8)); }}"""
BUILT = f"(() => {{ const r = {GEN_REC}; return !!(r.g && r.patchReady); }})()"
GONE = f"!{GEN_REC}.g"
GPATCH = "key => (window.__deck.patchScopes.get('room:' + key) || []).map(l => l.id + (l.ps ? '' : '!')).join()"
# the room's code-built chair (a lab's desk chairs are code only): its name,
# its footprint, whether it is lifted and shown, and the patch's stool
GPROP = """key => { const D = window.__deck, all = [...D.propByName.values()].filter(p => p.roomKey === key && p.blocks.length && p.ranges.some(x => x.length === 4));
  const p = all.find(x => x.kind === 'chair') || all[0]; if (!p) return null;
  return { name: p.name, n: all.length, block: p.blocks[0].slice(), lifted: !!p.lifted, shown: p.lifted ? p.lifted.m.visible : true,
           stool: !!D.patchObjs.get('t-gen/stool'), inScene: !!D.scene.getObjectByName('t-gen/stool') }; }"""
GEN_CODE = """// new: A round stool where the chair was
const o = deck.obj(%s), [x, , z] = o.at();
const top = new deck.three.Mesh(new deck.three.CylinderGeometry(0.28, 0.28, 0.06, 28), o.mat());
const leg = new deck.three.Mesh(new deck.three.CylinderGeometry(0.05, 0.16, 0.44, 12), o.mat());
top.position.y = 0.47; leg.position.y = 0.22;
const g = new deck.three.Group(); g.add(top, leg); g.position.set(x, 0, z);
o.hide();
await deck.add("stool", g);"""
COST = """() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => { const i = window.__deck.renderer.info.render; r([i.calls, i.triangles]); })))"""


def gen_room():
    """Build the wing lab by walking in, name its chair, leave; patch it while
    it is down; walk in: applied, and the cost from one view; walk out:
    undone. Answers the room's key and the chair's name for gen_again."""
    key = ev(GO_IN)
    if not check("a wing lab is built when walked into", wait(BUILT, 60000)):
        return None
    pr = ev(GPROP, key)
    if not check("its code-built props have names (<deck>/<room>/<name>#n)", bool(pr) and pr["name"].startswith(key + "/"), json.dumps(pr)):
        return None
    print(f"   the generated room: {key}, its {pr['n']} code-built props; the prop: {pr['name']}")
    ev(LOOKP, pr["name"])
    c_before = ev(COST)
    if args.out:
        shoot("genroom-before.jpg")
    sees = ev("window.lcarsDeckSees({ library: true })")
    check("the first message in a room carries its inventory", "[Everything named in " + key in sees["text"] and pr["name"][len(key) + 1:] in sees["text"],
          sees["text"][-400:])
    ev(GO_OUT, NAME)
    check("and dropped when walked away from", wait(GONE, 60000))
    r = ev(PATCH, [{"id": "t-gen", "code": GEN_CODE % json.dumps(pr["name"]), "title": "a round stool", "room": key}])
    check("a patch to a room not built is kept, to wait for it", r.get("ok") and not ev(GPATCH, key), json.dumps(r))
    ev(GO_IN)
    wait(BUILT, 60000)
    on = wait(f"({GPATCH})({json.dumps(key)}) === 't-gen'", 30000)
    p1 = ev(GPROP, key)
    check("walked into, the room applies its patch", on and p1["stool"] and p1["inScene"], json.dumps(p1))
    check("the chair lifted and hidden, its footprint gone", p1["lifted"] and not p1["shown"] and p1["block"][0] > 1e8, json.dumps(p1))
    # the cost, from inside the room looking at the stool: with it and without
    ev(LOOKP, pr["name"])
    c_after = ev(COST)
    print(f"   the room from one view: calls {c_before[0]} -> {c_after[0]}, triangles {c_before[1]} -> {c_after[1]} (crew moving in and out of view)")
    if args.out:
        shoot("genroom-after.jpg")
    SV = "v => { window.__deck.patchObjs.get('t-gen/stool').visible = v; }"
    ev(SV, False)
    c_off = ev(COST)
    ev(SV, True)
    c_on = ev(COST)
    # (two meshes, its top and its leg: a call each, nothing else moved)
    check("the stool is two draw calls, its two meshes", c_on[0] == c_off[0] + 2, f"without {c_off}, with {c_on}")
    print(f"   the stool's cost: calls {c_off[0]} -> {c_on[0]}, triangles {c_off[1]} -> {c_on[1]}")
    ev(GO_OUT, NAME)
    wait(GONE, 60000)
    check("walked away from, the patch is undone with the room", not ev(GPATCH, key) and not ev("!!window.__deck.patchObjs.get('t-gen/stool')")
          and not ev("!!window.__deck.scene.getObjectByName('t-gen/stool')"))
    return key, pr


def gen_again(gen):
    """After a reload: the room's patch is replayed when it is built again,
    the chair's footprint back as built once it is switched off."""
    key, pr = gen
    ev(GO_IN)
    wait(BUILT, 60000)
    on = wait(f"({GPATCH})({json.dumps(key)}) === 't-gen'", 30000)
    p2 = ev(GPROP, key)
    check("replayed after a reload when the room is built", on and p2["name"] == pr["name"] and p2["stool"] and not p2["shown"], json.dumps(p2))
    ev(PATCH, [{"id": "t-gen"}, "off"])
    p3 = ev(GPROP, key)
    check("switched off: the chair back, its footprint as built", not p3["lifted"] and not p3["stool"] and p3["block"] == pr["block"], json.dumps([pr, p3]))
    ev(PATCH, [{"id": "t-gen"}, "delete"])
    ev(GO_OUT, NAME)
    wait(GONE, 60000)


# ---- the round trip: the console's architect thread, a scratch server ----
USER, PASS = "t", "t-architect"
# claude, stood in for: keeps each message it is given (call-N.txt), and
# answers in stream-json as `claude -p --output-format stream-json
# --include-partial-messages` does. "move <name> nearer": a patch moving it,
# the closing sentence held until the test drops a file called "go" (so the
# test sees the patch applied while the answer is still coming); "break
# <name>": a patch naming nothing; the page's error turn: the fixed patch.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, sys, time
d = os.environ["STUB_DIR"]
data = sys.stdin.read()
n = len([f for f in os.listdir(d) if f.startswith("call-")]) + 1
open(os.path.join(d, "call-%d.txt" % n), "w").write(data)
def out(o):
    print(json.dumps(o), flush=True)
def text(s):
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": s}}})
out({"type": "system", "subtype": "init", "session_id": "0a1b2c3d-%04d" % n})
out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text", "text": ""}}})
m = re.search(r"move (.+?) nearer", data)
b = re.search(r"break (.+?)$", data, re.M)
if "[Your patch failed:" in data:
    name = open(os.path.join(d, "name")).read()
    text("```js deck-patch\n// new: A warmer table\ndeck.obj(%s).tint(\"#ff8040\", 0.5);\n```\n" % json.dumps(name))
    text("The table is warmer now.")
elif m:
    text("```js deck-patch\n// new: The table nearer\ndeck.obj(%s).move([0, 0, 0.6]);\n```\n" % json.dumps(m.group(1)))
    for _ in range(300):
        if os.path.exists(os.path.join(d, "go")):
            break
        time.sleep(0.1)
    text("The table is nearer now.")
elif b:
    text("```js deck-patch\n// new: A broken one\ndeck.obj(\"8/Ten Forward/nothing#9\").move([1, 0, 0]);\n```\n")
    text("Done.")
else:
    text("Nothing to change.")
out({"type": "result", "subtype": "success", "session_id": "0a1b2c3d-%04d" % n})
'''


class Scratch:
    def __init__(self, tmp):
        binary = os.environ.get("LCARS_TEST_BIN")
        if not binary:
            binary = tmp / "lcars"
            build(binary)
        self.stub = tmp / "stub"
        self.stub.mkdir()
        claude = tmp / "claude"
        claude.write_text(CLAUDE)
        claude.chmod(0o755)
        (tmp / "home").mkdir()
        (tmp / "root" / "media").mkdir(parents=True)
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="1", LCARS_CLAUDE_BIN=str(claude), LCARS_CHAT_DIR=str(tmp / "home"),
                   STUB_DIR=str(self.stub), LCARS_MEDIA_ROOT=str(tmp / "root"), LCARS_MEDIA_CACHE=str(tmp / "cache"),
                   LCARS_UI_DIR=str(pathlib.Path(args.page).resolve()), LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS)
        for k in ("LCARS_ENGINEER", "LCARS_ENGINEER_KEY", "LCARS_NO1_USER", "LCARS_CREW_USER", "LCARS_STEWARD_USER", "LCARS_TZ"):
            env.pop(k, None)
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--port", str(self.port)], cwd=tmp, env=env,
                                                     stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("   FAIL the scratch server did not come up; see " + str(tmp / "server.log"))

    def req(self, method, path, body=None, page=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()}
        if page:
            h["X-LCARS-Client"] = "web"
        if body is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def patches(self):
        st, rows = self.req("GET", "/entries?kind=deck_patch&content=1&limit=50")
        rows = rows if isinstance(rows, list) else (rows or {}).get("entries", []) if isinstance(rows, dict) else []
        return [r for r in rows if not r.get("deleted")]

    def calls(self):
        return sorted(self.stub.glob("call-*.txt"), key=lambda f: int(f.stem.split("-")[1]))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


# the console in the deck's frame: its names read in its own global scope
# (an eval there), since most are const and so not on its window
FR = "window.__fr"
FR_INIT = """window.__fr = new Proxy({}, { get: (_, k) => { const w = document.querySelector('#cframe')?.contentWindow;
  return w && typeof k === 'string' ? w.eval(k) : undefined; } });"""


def say(words):
    # typed into the sheet's box and sent, as Enter does
    ev(f"""w => {{ const f = {FR}, m = f.chatFull(); m.box.value = w; m.box.oninput(); f.chatSend(); }}""", words)


def roundtrip(b, NAME):
    global pg
    print("   the round trip: a scratch server, the console in the deck's frame")
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-architect-"))
    s = Scratch(tmp)
    try:
        base = f"http://127.0.0.1:{s.port}"
        # no service worker: the console in the frame registers sw.js, which
        # would answer the deck's reload with the cached console (caches.match("./"))
        ctx = b.new_context(viewport={"width": 800, "height": 500}, service_workers="block")
        ctx.add_init_script(f"""
          localStorage.setItem("lcars.cfg", JSON.stringify({{ base: "{base}", user: "{USER}", pass: "{PASS}" }}));
          localStorage.setItem("lcars.deck.gfx", JSON.stringify("low"));
          localStorage.setItem("lcars.deck.sound", JSON.stringify("off"));
          localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""" + FR_INIT)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: (errs.append(str(e)), print("   page error: " + str(e)[:300])))
        DECK = base + "/ui/deck.html"
        # one entry: boot() waits for the journal's rows, and an empty one
        # has none to wait for (the deck boots on it all the same)
        s.req("POST", "/entries", {"kind": "note", "title": "architect test", "content": "a row to boot on"}, page=True)
        boot(DECK)
        if not NAME:
            NAME = ev(PICK)
        ev(STAND, NAME)
        w0 = ev(WHERE, NAME)
        (s.stub / "name").write_text(NAME)
        # the sheet, and the console's thread in its frame
        ev("dispatchEvent(new KeyboardEvent('keydown', { key: 'i', code: 'KeyI' }))")
        ok_frame = wait(f"(() => {{ const f = {FR}; return !!(f && f.chatFind && f.chatFind('arch') && f.chatFind('arch').arch && f.chatFull && f.chatFull()); }})()", 60000)
        check("I opens the architect: the console's arch thread in the frame", ok_frame, "" if ok_frame else json.dumps(ev(f"""(() => {{
          const fr = document.querySelector('#cframe'), f = {FR}; let ids = null, t = null;
          try {{ ids = f.chats && f.chats.list.map(x => x.id); t = f.chatFind && f.chatFind('arch'); }} catch (e) {{ ids = String(e); }}
          return {{ talk: !document.querySelector('#talk').classList.contains('hidden'), who: document.querySelector('#talkwho').textContent,
                   note: document.querySelector('#talk').textContent.slice(0, 200), src: fr && fr.src, href: fr && fr.contentWindow.location.href,
                   chatFind: typeof (f && f.chatFind), ids, arch: t && {{ arch: t.arch, person: !!t.person }}, full: !!(f && f.chatFull && f.chatFull()) }}; }})()""")))
        if not ok_frame:
            return
        check("a thread of its own kind, its title", ev(f"{FR}.chatTitle({FR}.chatFind('arch'))") == "The architect")

        # ---- a change: applied while the answer still streams
        say(f"move {NAME} nearer")
        check("the bubble at once, the deck's picture as its file",
              ev(f"(() => {{ const t = {FR}.chatFind('arch'), u = t.msgs[t.msgs.length - 1]; return u.role === 'user' && u.files.length === 1 && u.files[0].shot; }})()"))
        moved = wait(f"(() => {{ const w = ({WHERE})({json.dumps(NAME)}); return w[3] && Math.abs(w[2] - {w0[2]} - 0.6) < 0.01; }})()", 60000)
        check("the patch applied, the model moved 0.6 m", moved)
        check("before the answer ended (the stand-in still holds its last sentence)",
              ev(f"{FR}.chatFind('arch').busy") and not (s.stub / "go").exists())
        check("nothing written yet", not s.patches())
        calls = s.calls()
        first = calls[0].read_text() if calls else ""
        check("the message carried what the deck sees", "[What the captain sees on the deck, now:" in first and "8/Ten Forward" in first, first[:300])
        check("the library, on the first message in a room", "[The model library" in first)
        check("and its picture, attached", "Attached file:" in first and ".jpg (" in first and "image/jpeg" in first)
        check("and the brief (the short one: no engineer key here)", "deck-patch" in first.split("[What the captain sees")[0])
        (s.stub / "go").write_text("1")
        done = wait(f"!{FR}.chatFind('arch').busy", 30000)
        rows = s.patches() if done else []
        wait("false", 1500) if done and not rows else None
        rows = rows or s.patches()
        check("the answer ended: one deck_patch entry, written by the page", done and len(rows) == 1, json.dumps(rows)[:300])
        c = json.loads(rows[0]["content"]) if rows else {}
        pid = c.get("id", "")
        check("its content the patch: id, room, code, on, what it says, no row",
              pid.startswith("arch-") and c.get("room") == "8/Ten Forward" and "move([0, 0, 0.6])" in c.get("code", "")
              and c.get("on") is True and c.get("says") == "The table is nearer now." and "row" not in c, json.dumps(c)[:300])
        check("titled as the patch", rows and rows[0].get("title") == "The table nearer")
        check("the answer says Applied as <id>", ev(f"{FR}.chatMsgText({FR}.chatFind('arch').msgs.slice(-1)[0])").endswith(f"Applied as {pid}."))
        check("with an Undo chip", ev(f"!!{FR}.document.querySelector('[data-patch=\"off\"]')"))

        # ---- replayed after a reload, from the entry
        boot(DECK)
        wait(f"window.__deck.patchLive.some(l => l.id === {json.dumps(pid)} && l.ps)", 30000)
        w1 = ev(WHERE, NAME)
        check("replayed on a reload, from the journal's entry", w1[3] and abs(w1[2] - w0[2] - 0.6) < 0.01, json.dumps([w0, w1]))

        # ---- the sheet's switch: kept off in the entry, from a fresh read
        row = rows[0]["id"]
        c2 = dict(c, asked="said on the laptop")
        st, _ = s.req("PATCH", f"/entries/{row}", {"content": json.dumps(c2)}, page=True)
        check("(a write from elsewhere, after this deck loaded)", st == 200)
        ev("dispatchEvent(new KeyboardEvent('keydown', { key: 'i', code: 'KeyI' }))")
        wait("[...document.querySelectorAll('#talkbtns button')].some(b => b.textContent === '✓ The table nearer')", 20000)
        ev("[...document.querySelectorAll('#talkbtns button')].find(b => b.textContent === '✓ The table nearer').click()")
        off = wait(f"!({WHERE})({json.dumps(NAME)})[3]", 20000)
        check("the switch: off in the scene", off)
        kept = False
        for _ in range(50):
            got = json.loads(s.req("GET", f"/entries/{row}")[1]["content"])
            if got.get("on") is False:
                kept = True
                break
            time.sleep(0.2)
        check("and kept off in the entry, through the API", kept, json.dumps(got)[:200])
        check("the other write kept (a fresh read, not this deck's copy)", got.get("asked") == "said on the laptop")
        check("the sheet's talk line says no failure", "not kept" not in ev("document.querySelector('#talk').textContent"))
        ev("[...document.querySelectorAll('#talkbtns button')].find(b => /The table nearer/.test(b.textContent)).click()")
        wait(f"({WHERE})({json.dumps(NAME)})[3]", 20000)

        # ---- a failing patch: back to the architect by itself, once
        wait(f"(() => {{ const f = {FR}; return !!(f && f.chatFind && f.chatFind('arch') && f.chatFull && f.chatFull()); }})()", 60000)
        n0 = len(s.calls())
        say(f"break {NAME}")
        back = wait(f"(() => {{ const t = {FR}.chatFind('arch'); return !t.busy && t.msgs.some(m => m.role === 'sys' && /Your patch failed/.test(m.text)) && t.msgs.slice(-1)[0].patch && t.msgs.slice(-1)[0].patch.state === 'applied'; }})()", 60000)
        calls = s.calls()
        check("the failing patch went back by itself, and the fix applied", back and len(calls) == n0 + 2, f"{len(calls) - n0} calls")
        second = calls[-1].read_text() if len(calls) >= n0 + 2 else ""
        check("in the design's words, with no new picture",
              "[Your patch failed: " in second and "The scene is unchanged. Fix it.]" in second and "Attached file:" not in second, second[-300:])
        check("shown as the page's line, not the captain's",
              ev(f"{FR}.chatFind('arch').msgs.filter(m => m.role === 'user' && /Your patch failed/.test(m.text)).length") == 0)
        titles = sorted(r.get("title") for r in s.patches())
        check("the fixed one written, the broken one never", titles == ["A warmer table", "The table nearer"], json.dumps(titles))
        check("no page errors (the round trip)", not errs, "; ".join(errs[:3]))
        ctx.close()
    finally:
        s.stop()

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = b.new_context(viewport={"width": 800, "height": 500})
    ctx.add_init_script("""
      localStorage.setItem("lcars.deck.gfx", JSON.stringify("low"));
      localStorage.setItem("lcars.deck.sound", JSON.stringify("off"));
      localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    ev_clear = "localStorage.removeItem('lcars.deck.patches')"

    if args.round_trip:
        roundtrip(b, "")
        b.close()
        print(f"   {n_ok} ok, {len(fails)} failed, {time.time() - t0:.0f}s")
        sys.exit(1 if fails else 0)
    boot(URL)
    ev(ev_clear)
    print(f"   booted in {time.time() - t0:.0f}s")
    # a model of Ten Forward's that stands in the room (a table, a chair)
    NAME = ev(PICK)
    if not check("Ten Forward's models have names (8/Ten Forward/<glb>/<prop>#n)", bool(NAME) and NAME.startswith("8/Ten Forward/")):
        sys.exit(1)
    print("   the model: " + NAME)
    ev(STAND, NAME)
    calls0 = ev(CALLS)
    w0 = ev(WHERE, NAME)
    if args.out:
        pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
        shoot("tenforward-before.jpg")

    # ---- what the architect is told, and its picture
    sees = ev("window.lcarsDeckSees({ library: true })")
    check("lcarsDeckSees names the room", "8/Ten Forward" in sees["text"], sees["text"][:200])
    check("lcarsDeckSees says what is under the crosshair", "Under the crosshair:" in sees["text"])
    check("lcarsDeckSees lists the model in view", NAME in sees["inView"], json.dumps(sees["inView"][:6]))
    check("lcarsDeckSees carries the library on asking", bool(sees["library"]) and "[The model library" in sees["text"])
    shot = ev("""async () => { const b = await window.lcarsDeckShot(); const im = await createImageBitmap(b); return [b.type, b.size, im.width, im.height]; }""")
    check("lcarsDeckShot is a JPEG at most 1024 px wide", shot[0] == "image/jpeg" and shot[1] > 2000 and shot[2] <= 1024, json.dumps(shot))

    # ---- a lifted patch
    code = f"deck.obj({json.dumps(NAME)}).move([0, 0, 0.6]);"
    r = ev(PATCH, [{"id": "t-move", "code": code, "title": "the table nearer", "room": "8/Ten Forward"}])
    check("the patch applies", r.get("ok"), json.dumps(r))
    w1 = ev(WHERE, NAME)
    check("the model moved 0.6 m and is lifted", w1[3] and abs((w1[2] - w0[2]) - 0.6) < 0.01, json.dumps([w0, w1]))
    check("its range in the merged mesh is zeroed", ev(RANGE, NAME) == 0)
    # the crew walk in and out of view between frames, so the lifted
    # model's own cost is measured by drawing the view with it and without
    calls1 = ev(CALLS)
    LM = f"window.__deck.placeByName.get({json.dumps(NAME)}).lifted.m.visible"
    ev(LM + " = false")
    calls_off = ev(CALLS)
    ev(LM + " = true")
    calls_on = ev(CALLS)
    check("one draw call more from the same view (the lifted model)", calls_on == calls_off + 1, f"without {calls_off}, with {calls_on}")
    print(f"   draw calls {calls0} before, {calls1} after; the lifted model {calls_off} -> {calls_on}")
    if args.out:
        shoot("tenforward-after.jpg")
    kept = ev("JSON.parse(localStorage.getItem('lcars.deck.patches') || '[]')")
    check("kept in ?demo's localStorage", [c["id"] for c in kept] == ["t-move"], json.dumps(kept)[:200])
    # a placement over a code-built prop (prop() in the builders): its
    # footprint went with it (phase 2)
    foot = ev(f"""(() => {{ const p = window.__deck.placeByName.get({json.dumps(NAME)}); if (!p.propRec || !p.propRec.blocks.length) return null;
      const r = p.lifted.regs.blocks[0]; return [r[1][1], r[0][1]]; }})()""")
    if foot is not None:
        check("its footprint moved with it", abs(foot[1] - foot[0] - 0.6) < 0.01, json.dumps(foot))

    GEN = gen_room()

    # ---- the sheet
    ev("dispatchEvent(new KeyboardEvent('keydown', { key: 'i', code: 'KeyI' }))")
    check("I opens the architect's sheet", ev("!document.querySelector('#talk').classList.contains('hidden') && document.querySelector('#talkwho').textContent === 'The architect'"))
    check("the sheet lists the patch, on", ev("[...document.querySelectorAll('#talkbtns button')].some(b => b.textContent === '✓ the table nearer')"))
    ev("dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape' }))")

    # ---- the drawing out, for the rest: the logic runs, the frames are cheap
    STUB = """(() => { const D = window.__deck; D.renderer.render = (sc, cam) => { sc.updateMatrixWorld(); if (!cam.parent) cam.updateMatrixWorld(); }; D.renderer.compile = () => {}; })()"""

    # ---- replayed after a reload
    boot(URL)
    ev(STUB)
    w2 = ev(WHERE, NAME)
    check("replayed after a reload: lifted and where the patch put it", w2[3] and abs(w2[2] - w1[2]) < 0.01, json.dumps([w1, w2]))
    check("applied once (patchLive)", ev("window.__deck.patchLive.map(l => l.id + (l.ps ? '' : '!')).join()") == "t-move")
    if GEN:
        gen_again(GEN)

    # ---- revised
    r = ev(PATCH, [{"id": "t-move", "code": code.replace("0.6", "1.2")}])
    w3 = ev(WHERE, NAME)
    check("a revision moves it from where it stood, not from the first move", r.get("ok") and abs((w3[2] - w0[2]) - 1.2) < 0.01, json.dumps([w0, w3, r]))
    # a second patch after it, and a revision of the first re-applies it
    r = ev(PATCH, [{"id": "t-tint", "code": f"deck.obj({json.dumps(NAME)}).tint('#ff8040', 0.5);", "title": "warmer"}])
    r = ev(PATCH, [{"id": "t-move", "code": code}])
    check("a revision of the first of two re-applies the second after it",
          ev("window.__deck.patchLive.map(l => l.id + (l.ps ? '' : '!')).join()") == "t-move,t-tint"
          and ev(f"window.__deck.placeByName.get({json.dumps(NAME)}).lifted.m.material.userData.patch") == "t-tint")

    # ---- a failing patch: refused, nothing changed, not kept
    r = ev(PATCH, [{"id": "t-bad", "code": "deck.obj('8/Ten Forward/nothing#1').move([1, 0, 0]);"}])
    check("a patch naming nothing is refused with its error", not r.get("ok") and "no object" in r.get("err", ""), json.dumps(r))
    check("and not kept", [c["id"] for c in ev("JSON.parse(localStorage.getItem('lcars.deck.patches'))")] == ["t-move", "t-tint"])

    # ---- switched off: back in its merged mesh
    ev(PATCH, [{"id": "t-tint"}, "off"])
    ev(PATCH, [{"id": "t-move"}, "off"])
    w4 = ev(WHERE, NAME)
    check("switched off: not lifted, back where it was built", not w4[3] and abs(w4[2] - w0[2]) < 0.01, json.dumps([w0, w4]))
    check("its range in the merged mesh restored", ev(RANGE, NAME) > 0)

    # ---- a patch that froze the last load is skipped
    ev(PATCH, [{"id": "t-move"}, "apply"])
    ev("sessionStorage.setItem('lcars.deck.patching', 't-move')")
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_timeout(4000)
    wait("window.__deck && window.__deck.modelsReady()", 180000)
    wait("window.__deck.patchSkipped.size > 0", 30000)
    check("a patch running when the last load stopped is skipped", ev("window.__deck.patchSkipped.has('t-move')")
          and not ev(WHERE, NAME)[3])

    # ---- classified entries (index.html's "classified" block): no patch while
    # the console holds the key, and the console told one has run
    check("no patch has run on this load yet", ev("window.lcarsDeckPatched() === false"))
    r0 = ev(PATCH, [{"id": "t-cls0", "code": "deck.obj(" + json.dumps(NAME) + ").move([0, 0.05, 0]);"}, "apply"])
    check("one applies with the console locked", r0["ok"], json.dumps(r0))
    check("and the deck says a patch ran this load", ev("window.lcarsDeckPatched() === true"))
    ev(PATCH, [{"id": "t-cls0"}, "delete"])
    ev("(() => { const w = document.querySelector('#cframe').contentWindow; w.__clsWas = w.lcarsClsUnlocked;"
       " w.lcarsClsUnlocked = () => true; })()")
    r = ev(PATCH, [{"id": "t-cls", "code": "deck.obj(" + json.dumps(NAME) + ").move([0, 0.1, 0]);"}, "apply"])
    check("a patch is refused while the console is unlocked", not r["ok"] and "unlocked" in r.get("err", ""), json.dumps(r))
    ev("(() => { const w = document.querySelector('#cframe').contentWindow; w.lcarsClsUnlocked = w.__clsWas; })()")
    ev(PATCH, [{"id": "t-cls"}, "delete"])

    # ---- ?nopatch
    boot(URL + "&nopatch")
    check("?nopatch applies none", ev("window.__deck.NOPATCH && window.__deck.patchLive.length === 0") and not ev(WHERE, NAME)[3])
    check("and keeps them", len(ev("JSON.parse(localStorage.getItem('lcars.deck.patches'))")) == 2)

    check("no page errors", not errs, "; ".join(errs[:3]))
    if not args.no_server:
        # the ?demo deck stops drawing first: two ships in software WebGL
        # at once starve the second one's boot
        ctx.close()
        roundtrip(b, NAME)
    b.close()

print(f"   {n_ok} ok, {len(fails)} failed, {time.time() - t0:.0f}s")
sys.exit(1 if fails else 0)
