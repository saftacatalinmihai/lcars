#!/usr/bin/env python3
# test/turn.py (~20s, no server): the course map's own turning (crsTurnable)
# in headless Chromium, against perf.py's fake API: a faked compass turns
# it, markers stand upright where their spot is, a fit holds turned, two
# fingers turn it about their middle, a drag and a long press land under the
# finger, shift+wheel turns a desk's map.
import sys, math, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import perf
from playwright.sync_api import sync_playwright

fails = []
def ok(c, msg):
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails.append(msg)

SCREEN_OF = """(ll) => { const m = crs.map, r = m.getContainer().getBoundingClientRect();
  const p = crsToScreen(m, m.latLngToContainerPoint(ll)); return [r.left + p.x, r.top + p.y]; }"""
LL_AT = """([x, y]) => { const m = crs.map, r = m.getContainer().getBoundingClientRect();
  const ll = m.containerPointToLatLng(crsToMap(m, L.point(x - r.left, y - r.top))); return [ll.lat, ll.lng]; }"""
# each marker's net turn on the screen (its own and every ancestor's), and
# its anchor's distance from where its spot is
MARKS = """() => {
  const m = crs.map, r = m.getContainer().getBoundingClientRect(), out = [];
  const angle = el => { let a = 0; for (let e = el; e && e !== document.body; e = e.parentElement) {
      const t = getComputedStyle(e).transform; if (t && t !== 'none') { const x = new DOMMatrix(t); a += Math.atan2(x.b, x.a) * 180 / Math.PI; } }
    return a; };
  [crs.marks, crsPoiS.layer].forEach(g => g.eachLayer(mk => {
    if (!mk._icon) return;
    const el = mk._icon, an = mk.options.icon.options.iconAnchor || [0, 0], q = el.getBoundingClientRect();
    const sp = crsToScreen(m, m.latLngToContainerPoint(mk.getLatLng()));
    const o = mk._crsOff || [0, 0];
    out.push({ ang: ((angle(el) % 360) + 540) % 360 - 180, w: q.width, ow: el.offsetWidth, h: q.height, oh: el.offsetHeight,
               dx: q.left + an[0] - (r.left + sp.x + o[0]), dy: q.top + an[1] - (r.top + sp.y + o[1]) });
  }));
  return out; }"""

def touch(cdp, typ, pts):
    cdp.send("Input.dispatchTouchEvent", {"type": typ, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})

with sync_playwright() as p:
    rows = perf.journal(200)
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport=perf.PHONE, has_touch=True, is_mobile=True)
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE + perf.RECORDER)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(perf.PAGE)
    page.wait_for_function("st.all.length >= 200 && !st.loading", timeout=120000)
    perf.s_course_zoom_setup(page)
    page.evaluate("crs.map.setZoom(14, {animate:false})")
    page.wait_for_timeout(300)
    ok(page.evaluate("crs.map.getBearing()") == 0 and page.evaluate("getComputedStyle(crs.map._crsTurn).transform") == "none",
       "north up: no turn, the box is the view")
    ok(page.evaluate("crs.map.getSize().x === crsView(crs.map).x"), "north up: Leaflet's size is the view's")
    # the compass: facing east, east goes up (bearing -90)
    page.evaluate("meLoc.on = true; meLoc.saw = true; crs.north = crs.free = false; meLoc.head = 90; crsTurnSoon()")
    page.wait_for_function("Math.abs(crs.map.getBearing() + 90) < 0.01", timeout=5000)
    ok(True, "a faked compass at 90 turns the map to -90 (east up)")
    ok("rotate(-90deg)" in page.evaluate("crs.map._crsTurn.style.transform"), "the turn is the box's CSS transform")
    sz = page.evaluate("[crs.map.getSize().x, crsView(crs.map).x, crsView(crs.map).y]")
    ok(sz[0] == math.ceil(math.hypot(sz[1], sz[2])), "turned: Leaflet's size is the view's diagonal square %s" % sz)
    page.wait_for_timeout(200)
    for bearing in (-90, 37):
        if bearing != -90:
            page.evaluate("meLoc.on = false; crs.free = true; crs.map.setBearing(%d)" % bearing)
            page.wait_for_timeout(200)
        ms = page.evaluate(MARKS)
        ok(len(ms) > 20 and all(abs(m["ang"]) < 0.5 for m in ms), "at %d: %d markers upright (net turn %.2f max)" % (bearing, len(ms), max(abs(m["ang"]) for m in ms)))
        ok(all(abs(m["w"] - m["ow"]) < 1 and abs(m["h"] - m["oh"]) < 1 for m in ms), "at %d: their boxes unturned on the screen" % bearing)
        worst = max(math.hypot(m["dx"], m["dy"]) for m in ms)
        ok(worst < 1.5, "at %d: each anchor on its spot, spread included (worst %.2fpx)" % (bearing, worst))
        # the needle: north on the screen
        ok(abs(page.evaluate("parseFloat(document.querySelector('#crsNorth').firstElementChild.style.transform.slice(7))") - bearing) < 0.2,
           "at %d: the compass needle follows" % bearing)
    # the fit on a turned map
    page.evaluate("crs.map.setZoom(10, {animate:false}); crs.map.panBy([300, 200], {animate:false})")
    page.wait_for_timeout(200)
    page.evaluate("crsFit()")
    page.wait_for_timeout(600)
    ok(page.evaluate("crs.map.getBearing()") == 37, "a fit keeps the bearing")
    ok(page.evaluate("crs.t.points.every(p => crsSees([p.lat, p.lon], crsSeen(), 4))"), "a fit on a turned map shows every stop in what can be seen")
    ok(page.evaluate("crs.map.getZoom()") >= 15, "and zooms in as far as it holds (zoom %s)" % page.evaluate("crs.map.getZoom()"))
    cdp = ctx.new_cdp_session(page)
    page.evaluate("crs.map.setZoom(13, {animate:false})")
    page.wait_for_timeout(300)
    # a drag: the place under the finger follows it
    a, z = (120, 300), (260, 380)
    ll0 = page.evaluate(LL_AT, list(a))
    touch(cdp, "touchStart", [a])
    for k in range(1, 11):
        touch(cdp, "touchMove", [(a[0] + (z[0] - a[0]) * k / 10, a[1] + (z[1] - a[1]) * k / 10)])
    page.wait_for_timeout(50)
    s = page.evaluate(SCREEN_OF, ll0)
    touch(cdp, "touchEnd", [])
    page.wait_for_timeout(600)
    ok(math.hypot(s[0] - z[0], s[1] - z[1]) < 3, "turned, a drag keeps the place under the finger (off %.1fpx)" % math.hypot(s[0] - z[0], s[1] - z[1]))
    # two fingers: a pinch that does not twist zooms and does not turn
    page.evaluate("crs.free = true")
    b0, z0 = page.evaluate("crs.map.getBearing()"), page.evaluate("crs.map.getZoom()")
    c = (150, 330)
    def fingers(r, th):
        t = math.radians(th)
        return [(c[0] - r * math.cos(t), c[1] - r * math.sin(t)), (c[0] + r * math.cos(t), c[1] + r * math.sin(t))]
    touch(cdp, "touchStart", fingers(50, 0))
    for k in range(1, 11):
        touch(cdp, "touchMove", fingers(50 + 6 * k, k * 0.8))
    touch(cdp, "touchEnd", [])
    page.wait_for_timeout(700)
    ok(page.evaluate("crs.map.getBearing()") == b0 and page.evaluate("crs.map.getZoom()") > z0,
       "a pinch twisting 8° zooms (%.2f -> %.2f) and does not turn" % (z0, page.evaluate("crs.map.getZoom()")))
    # a twist of 75° turns by 60 (the first 15 wait), about the fingers' middle
    page.evaluate("crs.map.setBearing(0)")
    page.wait_for_timeout(300)
    llc = page.evaluate(LL_AT, list(c))
    touch(cdp, "touchStart", fingers(80, 0))
    for k in range(1, 26):
        touch(cdp, "touchMove", fingers(80, k * 3))
    mid = page.evaluate(SCREEN_OF, llc)
    touch(cdp, "touchEnd", [])
    page.wait_for_timeout(700)
    bt = page.evaluate("crs.map.getBearing()")
    ok(abs(bt - 60) < 4, "two fingers twisting 75° turn the map %.1f° (60 expected)" % bt)
    ok(math.hypot(mid[0] - c[0], mid[1] - c[1]) < 4, "the place between the fingers stays between them (off %.1fpx)" % math.hypot(mid[0] - c[0], mid[1] - c[1]))
    ok(page.evaluate("crs.free") is True, "and the map is then the hand's")
    # a long press puts the stop under the finger
    n0 = page.evaluate("crs.t.points.length")
    h = (200, 250)
    llh = page.evaluate(LL_AT, list(h))
    touch(cdp, "touchStart", [h])
    page.wait_for_timeout(700)
    touch(cdp, "touchEnd", [])
    page.wait_for_timeout(300)
    ok(page.evaluate("crs.t.points.length") == n0 + 1, "a long press on the turned map adds a stop")
    np_ = page.evaluate("(() => { const q = crs.t.points.find(p => p.auto); return q ? [q.lat, q.lon] : null })()")
    ok(np_ and abs(np_[0] - llh[0]) < 2e-5 and abs(np_[1] - llh[1]) < 2e-5, "under the finger %s %s" % (np_, llh))
    # north again: the box is the view again
    page.evaluate("crs.free = false; meLoc.on = false; crs.north = true; crsTurnSoon()")
    page.wait_for_timeout(1500)
    page.evaluate("crsTurnSoon()")     # a pan's animation (the stop's fit) held the turn off
    page.wait_for_function("crs.map.getBearing() === 0", timeout=5000)
    ok(page.evaluate("getComputedStyle(crs.map._crsTurn).transform") == "none" and page.evaluate("crs.map.getSize().x === crsView(crs.map).x"),
       "north up again: the square is gone")
    ok(not errs, "no page errors %s" % errs[:3])
    ctx.close()
    # a desk: shift and the wheel turn about the pointer
    ctx = b.new_context(viewport=perf.DESKTOP)
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE + perf.RECORDER)
    page = ctx.new_page()
    page.goto(perf.PAGE)
    page.wait_for_function("st.all.length >= 200 && !st.loading", timeout=120000)
    perf.s_course_zoom_setup(page)
    z0 = page.evaluate("crs.map.getZoom()")
    w = (900, 450)
    llw = page.evaluate(LL_AT, list(w))
    page.mouse.move(*w)
    page.keyboard.down("Shift")
    for _ in range(4): page.mouse.wheel(0, 100); page.wait_for_timeout(50)
    page.keyboard.up("Shift")
    page.wait_for_timeout(400)
    ok(page.evaluate("crs.map.getBearing()") == 20 and page.evaluate("crs.map.getZoom()") == z0, "shift and the wheel turn a desk's map 20° and do not zoom")
    s = page.evaluate(SCREEN_OF, llw)
    ok(math.hypot(s[0] - w[0], s[1] - w[1]) < 2, "about the pointer (off %.1fpx)" % math.hypot(s[0] - w[0], s[1] - w[1]))
    # a click on a stop opens its popup, upright over it
    page.evaluate("crs.map.setView([45.6006, 25.5006], 17, {animate:false})")
    page.wait_for_timeout(300)
    page.evaluate("L.popup().setLatLng([45.6006, 25.5006]).setContent('<b>a popup</b> with a line of text').openOn(crs.map)")
    page.wait_for_timeout(300)
    pa = page.evaluate("""(() => { const c = document.querySelector('.leaflet-popup'); if (!c) return null;
      let a = 0; for (let e = c; e && e !== document.body; e = e.parentElement) { const t = getComputedStyle(e).transform; if (t && t !== 'none') { const x = new DOMMatrix(t); a += Math.atan2(x.b, x.a) * 180 / Math.PI; } } return a; })()""")
    ok(pa is not None and abs(pa) < 0.5, "a popup stands upright (net turn %s)" % pa)
    tip = page.evaluate("(() => { const t = document.querySelector('.leaflet-popup-tip').getBoundingClientRect(); return [t.left + t.width / 2, t.bottom]; })()")
    sp = page.evaluate(SCREEN_OF, [45.6006, 25.5006])
    ok(abs(tip[0] - sp[0]) < 2 and abs(tip[1] - sp[1]) < 12, "its tip over its spot %s %s" % (tip, sp))
    # a stop dragged on the turned map follows the pointer, upright
    page.evaluate("crs.map.closePopup(); crs.map.setView([45.6006, 25.5004], 18, {animate:false})")
    page.wait_for_timeout(400)
    st = page.evaluate("""(() => { const m = crs.marks.getLayers().find(m => m._icon && m.dragging && !m._crsOff); if (!m) return null;
      window.__dm = m; const r = m._icon.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()""")
    if st:
        page.mouse.move(*st)
        page.mouse.down()
        for k in range(1, 9): page.mouse.move(st[0] + 10 * k, st[1] + 5 * k)
        r = page.evaluate("(() => { const r = __dm._icon.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2, r.width, __dm._icon.offsetWidth]; })()")
        page.mouse.up()
        ok(abs(r[0] - st[0] - 80) < 2 and abs(r[1] - st[1] - 40) < 2 and abs(r[2] - r[3]) < 1,
           "a stop dragged on a turned map follows the pointer, upright %s" % r)
    else:
        ok(False, "no draggable stop to drag")
    b.close()
print("%d failed" % len(fails) if fails else "all passed")
sys.exit(1 if fails else 0)
