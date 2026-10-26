#!/usr/bin/env python3
# test/acplace.py (~20s, no server): where the editor's autocomplete popup
# (#wikiac: @crew, [[link]], #tag, /command) lands, in headless Chromium
# against perf.py's fake API, measured against the browser's own layout of
# the textarea rather than the page's mirror of it: caretPositionFromPoint
# (Chromium 128+ answers inside a text field) finds the anchor's line, and
# the column under the box's left edge must be the anchor's own. A desk and
# a phone; a line deep in a long entry, flipped above, the list narrowing
# under it (the @yeoman report, 0.311.2), a wrapped line, focus mode, the
# editor and the field scrolled. Then WebKit at a phone's size: the mirror's
# caret against the field's (no caretPositionFromPoint into a textarea
# there, so the mirror's whole height against scrollHeight - one wrap off
# and they differ - and the box against the mirror's caret).
import os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import perf
from playwright.sync_api import sync_playwright

fails = []
def ok(c, msg):
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails.append(msg)

# the anchor's line top by the browser's layout (stepping down the field
# until a point lands on that line), the column under the box's left edge,
# and the gap between the box and the line on the side it is on
PROBE = """() => {
  const el = wac.el, b = $('#wikiac').getBoundingClientRect(), at = wac.start;
  const lh = parseFloat(getComputedStyle(el).lineHeight);
  const ls = el.value.lastIndexOf(String.fromCharCode(10), at - 1) + 1;
  const er = el.getBoundingClientRect(), x0 = er.left + parseFloat(getComputedStyle(el).paddingLeft) + 2;
  let ty = null;
  for (let y = Math.max(0, er.top); y < Math.min(er.bottom, innerHeight); y += 0.5) {
    const q = document.caretPositionFromPoint(x0, y);
    if (!q || q.offsetNode !== el || q.offset > at) continue;
    if (q.offset >= ls) { ty = y; break; }
  }
  // a wrapped line's first row is not the anchor's: walk the rows down
  let col = null;
  if (ty != null) for (let y = ty + lh / 2; y < er.bottom; y += lh) {
    const r = document.caretPositionFromPoint(b.left + 1, y);
    if (r && r.offset >= at) { col = r.offset - at; ty = y - lh / 2; break; }
  }
  return { on: $('#wikiac').classList.contains('on'), above: wac.above, col,
           gap: ty == null ? null : (wac.above ? ty - b.bottom : b.top - (ty + lh)),
           h: b.height, w: b.width, left: b.left, vw: innerWidth };
}"""

def check(page, what):
    r = page.evaluate(PROBE)
    good = r["on"] and r["col"] == 0 and r["gap"] is not None and 0 <= r["gap"] <= 8
    ok(good, "%s: the box at the anchor's column, %s its line (col %s, gap %s, %s)"
       % (what, "above" if r["above"] else "below", r["col"], None if r["gap"] is None else round(r["gap"], 1),
          "%dx%d at %d" % (r["w"], r["h"], r["left"])))
    return r

def boot(b, vp, mobile, rows):
    ctx = b.new_context(viewport=vp, has_touch=mobile, is_mobile=mobile)
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(perf.PAGE)
    page.wait_for_function("st.all.length >= 50 && !st.loading", timeout=60000)
    page.evaluate("newEntry()")
    page.wait_for_timeout(300)
    page.focus("#content")
    return ctx, page, errs

def fill(page, text):
    page.evaluate("""t => { const c = $('#content'); c.value = t; c.selectionStart = c.selectionEnd = t.length;
      c.dispatchEvent(new Event('input')); }""", text)
    page.wait_for_timeout(400)      # autoGrow's timer and caretReveal's frame

LONG = "\n".join("line %d of a long entry, with a few words on it" % i for i in range(60)) + "\n"
WRAP = "intro\n" + "a long paragraph that wraps " * 30 + "\n"

with sync_playwright() as p:
    rows = perf.journal(50)
    b = p.chromium.launch(headless=True)
    for name, vp, mobile in (("desk", perf.DESKTOP, False), ("phone", perf.PHONE, True)):
        ctx, page, errs = boot(b, vp, mobile, rows)
        fill(page, LONG)
        page.keyboard.type("  - @")
        page.wait_for_timeout(100)
        r0 = check(page, name + ", a line deep in a long entry")
        page.keyboard.type("yeo")
        page.wait_for_timeout(100)
        r1 = check(page, name + ", the list narrowed to @yeo")
        ok(r1["h"] < r0["h"] and r1["above"] == r0["above"], "%s: shorter, and on the same side" % name)
        page.evaluate("wikiClose()")
        fill(page, WRAP)
        page.keyboard.type("@")
        page.wait_for_timeout(100)
        check(page, name + ", after a wrapped paragraph")
        page.evaluate("wikiClose()")
        # an "@" already there when the field is filled, the name typed after it
        fill(page, LONG + "@")
        page.keyboard.type("y")
        page.wait_for_timeout(100)
        check(page, name + ", a name typed after a set value")
        page.evaluate("wikiClose()")
        # an "@" typed at the head of a line in the middle of the entry, then
        # the field's own scroll (the phone's fixed box) and the editor's moved
        # under it, by less than keeps the line in sight
        fill(page, LONG)
        page.evaluate("""() => { const c = $('#content'), i = c.value.indexOf('line 30 ');
          c.selectionStart = c.selectionEnd = i; c.dispatchEvent(new Event('click')); }""")
        page.keyboard.type("@")
        page.wait_for_timeout(100)
        check(page, name + ", a line in the middle of the entry")
        for sc, what in (("#content", "the field"), ("#edbody", "the editor")):
            # toward the middle of the field, so the line stays in sight
            moved = page.evaluate("""s => { const e = $(s), was = e.scrollTop, p = wac.p;
              const d = p.y > (p.box.top + p.box.bottom) / 2 ? 40 : -40;
              e.scrollTop = was + d; if (e.scrollTop === was) e.scrollTop = was - d;
              return e.scrollTop - was; }""", sc)
            page.wait_for_timeout(100)
            if moved: check(page, "%s, %s scrolled %dpx under it" % (name, what, moved))
        if not mobile:
            page.evaluate("wikiClose(); setFocus(true)")
            page.wait_for_timeout(200)
            page.focus("#content")
            fill(page, LONG[:LONG.index("line 9 ")])
            page.keyboard.type("@")
            page.wait_for_timeout(100)
            r = check(page, name + ", focus mode")
            ok(page.evaluate("document.body.dataset.focus") == "on", "focus mode was on")
        ok(not errs, "%s: no page errors %s" % (name, errs[:2]))
        ctx.close()
    b.close()

    # WebKit at a phone's size. Playwright's build wants libraries a bare box
    # may lack: $LCARS_WEBKIT names a launcher that supplies them, and one that
    # cannot start is said and skipped rather than failed
    try:
        exe = os.environ.get("LCARS_WEBKIT")
        wk = p.webkit.launch(headless=True, **({"executable_path": exe} if exe else {}))
    except Exception as e:
        print("skip webkit: it did not start (%s)" % str(e).split("\n")[0][:120])
        print("%d failed" % len(fails) if fails else "all ok")
        sys.exit(1 if fails else 0)
    ctx, page, errs = boot(wk, perf.PHONE, True, rows)
    for what, text in (("a long entry", LONG), ("a wrapped paragraph", WRAP)):
        fill(page, text)
        page.keyboard.type("@")
        page.wait_for_timeout(100)
        r = page.evaluate("""() => {
          const el = $('#content'), st = el.scrollTop, cs = getComputedStyle(el), m = wikiMirror(el, cs, false);
          m.textContent = el.value; const h = m.offsetHeight;
          const p = wikiCaretXY(el, wac.start), b = $('#wikiac').getBoundingClientRect();
          return { h, sh: el.scrollHeight, px: p.x, py: p.y, lh: p.lh, left: b.left, top: b.top, bottom: b.bottom,
                   above: wac.above, st, kept: wac.p.y, on: $('#wikiac').classList.contains('on') }; }""")
        ok(abs(r["h"] - r["sh"]) <= 2, "webkit, %s: the mirror wraps as the field does (%d vs %d)" % (what, r["h"], r["sh"]))
        gap = (r["py"] - r["bottom"]) if r["above"] else (r["top"] - r["py"] - r["lh"])
        ok(r["on"] and abs(r["left"] - r["px"]) <= 1 and 0 <= gap <= 8,
           "webkit, %s: the box at the mirror's caret (x %d vs %d, gap %.1f; %s)" % (what, r["left"], r["px"], gap, r))
        page.evaluate("wikiClose()")
    # headless WebKit has no sound card, and the page's beeps say so
    errs = [e for e in errs if "audio device" not in e]
    ok(not errs, "webkit: no page errors %s" % errs[:2])
    ctx.close()
    wk.close()

print("%d failed" % len(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
