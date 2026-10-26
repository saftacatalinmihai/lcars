#!/usr/bin/env python3
"""The public demo, built and served as the bucket will serve it
(docs/design/demo-static.md): demo/static.py writes the folder, python's
http.server serves it under /lcars-demo/ (no rewrites, no index document),
and headless Chromium boots the console, edits an entry, reloads and finds
the edit, resets, and walks onto the deck. No server of ours, and the
browser may ask nothing of anyone but the folder: every other request is
refused and counted.

    python3 test/demo_static.py          # ~1 min
"""
import functools
import hashlib
import http.server
import importlib.util
import json
import re
import pathlib
import shutil
import subprocess
import sys
import threading
import time

T = pathlib.Path(__file__).resolve().parent
UI = T.parent
sys.path.insert(0, str(T))
import killclean  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

checks, fails = [], []


def check(ok, what):
    checks.append(what)
    if not ok:
        fails.append(what)
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)


tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-demo-"))
out = tmp / "lcars-demo"
b = subprocess.run([sys.executable, str(UI / "demo" / "static.py"), str(out)], capture_output=True, text=True)
print(b.stdout.splitlines()[0] if b.stdout else b.stderr, flush=True)
check(b.returncode == 0, "the build writes the folder and finds nothing of ours in it")
if b.returncode:
    sys.exit(1)

# ---- every cached file asked for by its content ----
# The host's CDN keeps scripts, styles, fonts and pictures for hours, with
# no purge: a page must name each by a hash of its bytes, or a new
# index.html runs on an old demo.js.
ver = lambda f: hashlib.sha256((out / f).read_bytes()).hexdigest()[:10]
pages = {n: (out / n).read_text(encoding="utf-8") for n in ("index.html", "deck.html")}
for n, html in pages.items():
    check(f'<script src="demo.js?v={ver("demo.js")}"></script>' in html, f"{n} loads demo.js by its hash ({ver('demo.js')})")
dk = pages["deck.html"]
check(f'"./vendor/three-0.186.1-r2.min.js?v={ver("vendor/three-0.186.1-r2.min.js")}"' in dk and
      f'"deck/bridge_base.webp":"{ver("deck/bridge_base.webp")}"' in dk and
      "DefaultLoadingManager.setURLModifier(window.LCARS_DEMO_ASSET)" in dk,
      "the deck's three.js by its hash, and its models' and textures' in its table, through three's loaders")
css = (out / "fonts" / "antonio.css").read_text()
check(f"antonio-latin.woff2?v={ver('fonts/antonio-latin.woff2')}" in css and
      f'fonts/antonio.css?v={ver("fonts/antonio.css")}' in pages["index.html"], "the face's files by their hashes, in a css by its own")
pics = [m["path"] for m in json.loads((out / "journal.json").read_text())["media"]]
check(pics and all(re.fullmatch(r"media/demo/e\d+-\d+-([0-9a-f]{10})\.png", m)[1] ==
                   hashlib.sha256((out / "api" / m).read_bytes()).hexdigest()[:10] for m in pics),
      f"the journal's pictures carry their hash in their names ({pics[0] if pics else None})")
# a changed demo.js, a new url; what did not change, the same
spec = importlib.util.spec_from_file_location("lcars_demo_static", UI / "demo" / "static.py")
st2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st2)
alt = tmp / "alt-src"
alt.mkdir()
(alt / "static.js").write_text((UI / "demo" / "static.js").read_text() + "\n// another build\n")
(alt / "assets").symlink_to(UI / "demo" / "assets")
st2.HERE = alt
out2 = tmp / "lcars-demo-2"
st2.build(out2)
dk2 = (out2 / "deck.html").read_text(encoding="utf-8")
v2 = hashlib.sha256((out2 / "demo.js").read_bytes()).hexdigest()[:10]
check(v2 != ver("demo.js") and f'demo.js?v={v2}"' in dk2 and f'demo.js?v={v2}"' in (out2 / "index.html").read_text(encoding="utf-8"),
      f"a changed demo.js is a new url in both pages ({ver('demo.js')} -> {v2})")
check(f'"deck/bridge_base.webp":"{ver("deck/bridge_base.webp")}"' in dk2 and f'three-0.186.1-r2.min.js?v={ver("vendor/three-0.186.1-r2.min.js")}"' in dk2,
      "and an unchanged file keeps its url, so its cached copy")
shutil.rmtree(out2)

served = []                               # (path, status), every request the folder got
asked = []                                # the same, with its query


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def log_request(self, code="-", size="-"):
        served.append((self.path.split("?")[0], int(code) if str(code).isdigit() else 0))
        asked.append(self.path)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
HOST = f"http://127.0.0.1:{srv.server_address[1]}"
URL = HOST + "/lcars-demo/"

ROWS = "typeof st !== 'undefined' && st.all && st.all.length > 300 && !st.loading"
EID = 2398                                # fixture.IDS.ARENA
TEXT = "an edit the visitor made, kept in this browser"

with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = br.new_context(viewport={"width": 1280, "height": 800})
    away = []

    def gate(route):
        if route.request.url.startswith(HOST):
            return route.continue_()
        away.append(route.request.url)
        return route.abort()
    ctx.route("**/*", gate)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("dialog", lambda d: (errs.append("a browser dialog: " + d.message), d.dismiss()))

    # ---- the console boots on the made-up journal ----
    page.goto(URL + "index.html")
    page.wait_for_function(ROWS, timeout=60000)
    check(page.evaluate("DEMO === true && cfg.base === window.LCARS_DEMO.base"), "the console is in demo mode, its API the page's own")
    bar = page.inner_text("#demobar") if page.query_selector("#demobar") else ""
    check("made-up journal" in bar.lower() and "this browser" in bar.lower(), f"the banner says what it is ({bar.strip()[:70]!r})")
    check(page.evaluate("st.byId.get(2400).title") == "The layout pass, finally", "the fixture's rows are in")
    page.wait_for_function("kindMap.map !== null", timeout=10000)
    check(page.evaluate("kindMap.map.size === KIND_ROLES.length && kindOf('log') === 'personal_log' && "
                        "kindMap.map.get('work_log').rows > 0"),
          "GET /kinds/roles is the demo's own: every role its default, the work log's rows counted")
    newest = page.evaluate("st.all.filter(e => !e.deleted).map(e => e.created_at_utc).sort().pop()")
    yday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    check(newest[:10] >= yday, f"the journal's newest entry is today's or yesterday's ({newest})")
    utcnow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    check(newest <= utcnow, f"and never later than now, or the change feed's mark would hide new edits ({newest} vs {utcnow})")

    # ---- the route is the hash: a reload lands on the one file ----
    page.evaluate(f"select({EID})")
    page.wait_for_function(f"location.hash === '#entry/{EID}'", timeout=5000)
    check(page.evaluate("location.pathname") == "/lcars-demo/index.html", "an entry's url is index.html#entry/<id>, the path unchanged")

    # ---- an edit, saved in the browser ----
    page.click("#rwmode button[data-v=edit]")
    page.fill("#content", TEXT)
    page.wait_for_timeout(50)
    page.click("#edchip")
    page.wait_for_function("document.querySelector('#edchip').dataset.s === 'saved'", timeout=8000)
    kept = page.evaluate(f"(JSON.parse(localStorage.getItem('lcars.demo.edits')).rows[{EID}] || {{}}).content")
    check(kept == TEXT, "the save is kept in this browser's storage")

    # ---- views that work on the fixture ----
    for name, js in [("tasks", "openTasks()"), ("the month", "openMonth()"), ("the star chart", "openStars()"),
                     ("the link graph", "openGraph()"), ("the media view", "openMediaView()"),
                     ("the readings", "openExplore('weight')"), ("the chats", "openChat()")]:
        try:
            page.evaluate(js)
            page.wait_for_timeout(600)
            check(page.evaluate("document.querySelector('#ov').classList.contains('on')"), f"{name} opens")
        except Exception as e:
            check(False, f"{name} opens ({str(e)[:100]})")
        page.evaluate("closeOv()")
        page.wait_for_timeout(200)
    check(page.evaluate("measureSeries().has('weight') && measureSeries().has('run')"), "the fixture's readings make series (weight, run)")
    stars = page.evaluate("sv.vec.size")
    check(stars > 300, f"the star chart has the build's vectors ({stars})")
    media = page.evaluate(f"fetch(mediaUrl('{pics[-1]}')).then(r => r.status + ' ' + r.headers.get('content-type'))")
    check(media == "200 image/png", f"a picture is a file of the folder's ({media})")

    # ---- what needs a server: a note, not an error ----
    page.evaluate("openCourse()")
    page.wait_for_timeout(200)
    t = page.inner_text("#toast")
    check("needs the journal's server" in t and not page.evaluate("document.querySelector('#ov').classList.contains('on')"),
          f"the course is a note ({t.strip()[:60]!r})")
    reply = page.evaluate("fetch(LCARS_DEMO.base + '/chat', {method: 'POST', body: '{}'}).then(r => r.text())")
    check("made-up journal" in reply and "lcars_exit" in reply, "the computer's chat answers with why it cannot")
    q = page.evaluate("api('/embed', {method: 'POST', body: {text: 'x'}}).then(() => 'answered', e => e.http + ' ' + e.message)")
    check(q.startswith("503 Search by meaning needs"), f"search by meaning says it needs the server ({q[:60]!r})")

    # ---- the Secret entry: sealed in the browser, opened by the printed password ----
    sec = page.evaluate("(st.all.find(e => clsSecret(e)) || {}).id")
    check(bool(sec), f"the fixture's Secret entry is in, as Secret ({sec})")
    if sec:
        check(page.evaluate(f"st.byId.get({sec}).title === '' && String(st.byId.get({sec}).sealed).startsWith('lcs1.')"),
              "sealed by demo.js: its columns empty, an envelope instead")
        check(page.evaluate("[...sv.vec.keys()].indexOf(%d) < 0" % sec), "and it has no vector")
        page.evaluate("clsUnlockAsk()")
        page.wait_for_selector("#clsPw", timeout=5000)
        check("make it so" in page.text_content("#dlg"), "the unlock dialog prints the demo's password")
        page.fill("#clsPw", page.evaluate("LCARS_DEMO.password"))
        page.click("#clsGo")
        page.wait_for_function(f"clsOn() && st.byId.get({sec}).title.length > 0", timeout=20000)
        check("birthday" in page.evaluate(f"st.byId.get({sec}).title"), "and it opens the Secret entry")
        page.evaluate("clsLock()")
        page.wait_for_function("!clsOn()", timeout=5000)

    # ---- a reload keeps the edit, and the route ----
    page.reload()
    page.wait_for_function(ROWS, timeout=60000)
    page.wait_for_function(f"st.sel && st.sel.id === {EID}", timeout=10000)
    check(page.evaluate(f"st.byId.get({EID}).content") == TEXT, "after a reload the edit is there, and the entry open")

    # ---- the strip over an open entry: under it on the desktop, and on a phone ----
    # A phone's reader and editor are a fixed panel over the whole screen,
    # which once buried the strip, and Reset could be tapped from the list only.
    HIT = """() => { const b = document.querySelector('#demoReset'), r = b.getBoundingClientRect(),
      bar = document.querySelector('#demobar').getBoundingClientRect(),
      pane = document.querySelector('#editpane').getBoundingClientRect(),
      head = document.querySelector('#edhead').getBoundingClientRect();
      return { hit: document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b,
               h: r.height, barBottom: bar.bottom, paneTop: pane.top, headTop: head.top, paneW: pane.width }; }"""
    MARK = """() => { const m = document.querySelector('#verMark'), r = m.getBoundingClientRect(),
      over = el => { const q = el.getBoundingClientRect();
        return r.left < q.right && q.left < r.right && r.top < q.bottom && q.top < r.bottom; };
      return { shown: getComputedStyle(m).display !== 'none' && r.height > 0, top: Math.round(r.top),
               text: over(document.querySelector('#demobar span')), reset: over(document.querySelector('#demoReset')) }; }"""

    # the demo is never stale (no update check), so the mark shows only as
    # a stale page would show it: placed by the same rules
    def mark_clear(where):
        page.evaluate("document.body.dataset.stale = 'on'")
        m = page.evaluate(MARK)
        page.evaluate("delete document.body.dataset.stale")
        check(m["shown"] and not m["text"] and not m["reset"], f"{where}: the version mark is off the strip's text and Reset ({m})")

    d = page.evaluate(HIT)
    check(d["hit"] and d["paneTop"] >= d["barBottom"] - 0.5, f"desktop: the reader sits under the strip, Reset on top ({d})")
    page.evaluate("openTasks()")
    page.wait_for_timeout(400)
    mark_clear("desktop, a view open")
    page.evaluate("closeOv()")
    page.wait_for_timeout(200)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    check(page.evaluate("document.body.dataset.pane") == "edit", "phone: the entry is open in the reader")
    mark_clear("phone, an entry open")
    page.evaluate("openTasks()")
    page.wait_for_timeout(400)
    mark_clear("phone, a view open")
    page.evaluate("closeOv()")
    page.wait_for_timeout(200)
    page.evaluate("openDrawer()")
    page.wait_for_timeout(400)
    mark_clear("phone, the filters drawer open")
    page.evaluate("closeDrawer()")
    page.wait_for_timeout(300)
    check(page.evaluate("document.body.dataset.pane") == "edit", "phone: the entry still open after the view and the drawer")
    d = page.evaluate(HIT)
    check(d["hit"] and d["h"] > 10, f"phone: with an entry open, Reset is visible and nothing covers it ({d})")
    check(d["paneTop"] >= d["barBottom"] - 0.5 and d["headTop"] >= d["barBottom"] - 0.5 and d["paneW"] == 390,
          f"phone: the reader starts under the strip, its head uncovered, the screen's width ({d})")
    page.click("#demoReset", timeout=3000)   # actionability: visible, stable, the topmost at its point
    page.wait_for_selector("#lcOk", state="visible", timeout=3000)
    ok_hit = page.evaluate("(() => { const b = document.querySelector('#lcOk'), r = b.getBoundingClientRect();"
                           " return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b; })()")
    check(ok_hit, "phone: Reset's confirm is on screen, its button tappable")

    # ---- Reset: the fixture back (tapped from the phone's reader) ----
    page.click("#lcOk")
    page.wait_for_url("**/lcars-demo/index.html", timeout=15000)
    page.wait_for_function(ROWS, timeout=60000)
    page.wait_for_timeout(300)
    back = page.evaluate(f"st.byId.get({EID}).content")
    check(back != TEXT and back.startswith("- Settled on 1MB"), "Reset puts the made-up journal back")
    check(page.evaluate("localStorage.getItem('lcars.demo.edits')") is None, "and empties this browser's edits")
    page.set_viewport_size({"width": 1280, "height": 800})

    # ---- the deck, on the same journal ----
    page.evaluate(f"api('/entries/{EID}', {{method: 'PUT', body: {{title: 'Seen on the deck'}}}})")
    page.goto(URL + "deck.html", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_function("window.__deck && window.__deck.crewReady()", timeout=180000)
    page.wait_for_timeout(1500)
    d = page.evaluate(f"""() => {{ const d = window.__deck;
      return {{ rows: d.rows.size, title: (d.rows.get({EID}) || {{}}).title, pins: d.place.pins.length,
               crew: (typeof d.crew === 'function' ? d.crew() : d.crew).length, gfx: d.gfx,
               leave: document.querySelector('#leaveDeck').getAttribute('href') }}; }}""")
    check(d["rows"] > 300 and d["title"] == "Seen on the deck", f"the deck reads the console's journal, edits included ({d['rows']} rows)")
    check(d["pins"] >= 6, f"the fixture's entries are pinned on the ship ({d['pins']})")
    check(d["crew"] > 5, f"the crew are aboard ({d['crew']})")
    lv = d["leave"]
    check(lv == "index.html", f"Leave deck goes to index.html, not the folder ({lv})")

    check(not errs, f"no page errors ({errs[:3]})")
    check(not away, f"nothing asked of anyone but the folder ({away[:3]})")
    br.close()

srv.shutdown()
api = [s for s in served if s[0].startswith("/lcars-demo/api/") and not s[0].startswith("/lcars-demo/api/media/")]
check(not api, f"the API never reached the host: it is answered in the page ({api[:3]})")
outside = [s for s in served if not s[0].startswith("/lcars-demo/")]
check(not outside, f"every file asked for is in the folder ({outside[:3]})")
missing = sorted({s[0] for s in served if s[1] >= 400})
CACHED = (".js", ".mjs", ".css", ".png", ".webp", ".woff2", ".glb", ".webmanifest")
bare = sorted({a for a in asked if a.split("?")[0].endswith(CACHED) and "?v=" not in a and "/api/media/" not in a})
check(not bare, f"every script, style, font, model and picture was asked for by its hash ({bare[:4]})")
check(any("deck/bridge_base.webp?v=" in a or "_base.webp?v=" in a for a in asked) and any("crew/male.glb?v=" in a for a in asked),
      "the deck's textures and the crew's models went through the table")
check(not missing, f"every file asked for is there ({missing[:5]})")

shutil.rmtree(tmp, ignore_errors=True)
print(f"demo_static: {len(checks) - len(fails)}/{len(checks)} checks passed")
sys.exit(1 if fails else 0)
