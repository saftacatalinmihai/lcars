#!/usr/bin/env python3
# test/helpopen.py (~20s, no server): the keyboard help (?) opened the ways a
# person opens it (on a touch screen the side pane's button is the gestures
# and the voice orders instead, the review's finding 7), in headless Chromium against perf.py's fake API - an
# iPhone on its side (852x393: past the phone layout's 820, so the side
# pane's "? shortcuts" is on screen) tapped; upright (393x852), where the
# drawer hides that button, its click() (the browser's own event, which is
# what reached openHelp) and the palette's row; on a desk the ? key and the
# button clicked. Each time the search box must be empty
# and the rows drawn: 0.312.0 handed the tap's event to openHelp(query), and
# the iPhone opened it on "[object PointerEvent]", nothing matching.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import perf
from playwright.sync_api import sync_playwright

fails = []
def ok(c, msg):
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails.append(msg)

STATE = """() => ({ on: document.querySelector('#ov').classList.contains('on'),
  q: (document.querySelector('#pkq') || {}).value, rows: document.querySelectorAll('#pkrows .pkr').length,
  empty: !!document.querySelector('#pkrows .pkempty'), heads: document.querySelectorAll('#pkrows .pkh').length,
  route: st.route && st.route.v })"""

def touch_help(page, size, how):
    """On a touch screen (hover:none) the side pane's button is the help by
    device (the review's finding 7): the gestures and the voice orders, not
    the keyboard sheet."""
    page.wait_for_function("document.querySelector('#ov').classList.contains('on')", timeout=5000)
    s = page.evaluate("""() => ({ kb: !!document.querySelector('#pkq'), hover: matchMedia('(hover:none)').matches,
      g: (el => !!el && el.getClientRects().length > 0)(document.querySelector('#v_gest .kg')),
      head: document.querySelector('#dlgh').innerText.trim() })""")
    ok(s["hover"], f"{size}: the browser says there is no hover (a touch screen)")
    ok(not s["kb"], f"{size}: {how}: not the keyboard sheet")
    ok(s["g"] and s["head"].lower() == "help", f"{size}: {how}: the help, its gestures on screen  ({s['head']!r})")
    page.evaluate("closeOv()")
    page.wait_for_function("!document.querySelector('#ov').classList.contains('on')", timeout=5000)

def opened(page, size, how):
    page.wait_for_function("document.querySelector('#ov').classList.contains('on') && !!document.querySelector('#pkq')", timeout=5000)
    s = page.evaluate(STATE)
    ok(s["q"] == "", f"{size}: {how}: the search box is empty  ({s['q']!r})")
    ok(s["rows"] > 20 and not s["empty"], f"{size}: {how}: the rows are drawn  ({s['rows']})")
    ok(s["heads"] >= 3, f"{size}: {how}: under their section headings  ({s['heads']})")
    ok(s["route"] == "help", f"{size}: {how}: at its route, help")
    page.keyboard.press("Escape")
    if page.evaluate(STATE)["on"]:            # a desk's focus was in the box: Escape lets go first
        page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('#ov').classList.contains('on')", timeout=5000)

with sync_playwright() as p:
    rows = perf.journal(200)
    b = p.chromium.launch(headless=True)
    for size, vp, mob in (("phone", {"width": 393, "height": 852}, True), ("phone on its side", {"width": 852, "height": 393}, True),
                          ("desk", {"width": 1280, "height": 800}, False)):
        ctx = b.new_context(viewport=vp, has_touch=mob, is_mobile=mob)
        ctx.route(perf.BASE + "/**", perf.serve(rows))
        ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(perf.PAGE)
        page.wait_for_function("st.all.length >= 200 && !st.loading", timeout=120000)
        if size == "phone":
            page.evaluate("document.querySelector('#bHelp').click()")
            touch_help(page, size, "the side pane's help, its click()")
        elif mob:
            page.tap("#bHelp")
            touch_help(page, size, "the side pane's help tapped")
        else:
            page.keyboard.press("?")
            opened(page, size, "the ? key")
            page.click("#bHelp")
            opened(page, size, "the side pane's ? shortcuts clicked")
        page.evaluate("openPalette()")
        page.fill("#pkq", "keyboard shortcuts")
        page.keyboard.press("Enter")
        opened(page, size, "the palette's row")
        ok(not errs, f"{size}: no page error  {errs[:2]}")
        ctx.close()
    b.close()

print(f"helpopen: {len(fails)} failures")
sys.exit(1 if fails else 0)
