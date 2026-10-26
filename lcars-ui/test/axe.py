#!/usr/bin/env python3
# test/axe.py (~40s, no server): axe-core (vendor/axe-core, WCAG 2.2 A and
# AA tags) on the console's screens in headless Chromium against perf.py's
# fake API (docs/design/ui-rules.md, "axe finds nothing"; the analysis of
# 0.321.0, finding 7). The phone's screens at an iPhone's size with touch
# (targets.py's: the list, the reader, the editor, the ⋯ sheet, the filters
# drawer, the month) and the desk's views at 1280x800 (those, a new entry,
# Tasks, Statistics, the chats, the help, the palette, Reports, the graph).
# Every violation fails, but AXE_LEFT's, each named with why it is left; one
# of those that no longer shows fails too (drop it from the list), so the
# list only shrinks. --json FILE writes every screen's violations.
import sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import perf
from playwright.sync_api import sync_playwright

AXE = (HERE.parent.parent / "vendor" / "axe-core" / "axe.min.js").read_text()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
# label in name (WCAG 2.5.3, ui-rules.md "Label in name") is axe's experimental
# rule, off by default: on here, so the names the script sets are held too
RUN = """(tags) => axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations'],
    rules: {'label-content-name-mismatch': {enabled: true}}})
  .then(r => r.violations.map(v => ({id: v.id, impact: v.impact,
    nodes: v.nodes.map(n => n.target.join(' ') + '  ' + n.html.slice(0, 80))})))"""

# (axe rule, a piece of the node's selector or its markup's start) -> why
# it is left, on every screen; any other node breaking that rule still fails
AXE_LEFT = {
    ("list", "#rd_content > ul"): "the outline puts a branch in the <ul> after its <li>, not inside it, "
        "so a fold is one sibling rule (renderMd); moving it into the <li> is TODO.md's",
    ("list", "<ul>"): "the same outline in the Day view's entries (its .dbody is the reader's render): a "
        "bare <ul>, the renderer's only one with no class; the same TODO.md item",
    ("label-content-name-mismatch", '<div class="item'): "a list row is a card: its name is its "
        "title, kind and date, never the snippet it also shows (the rule wants every word of it)",
    ("label-content-name-mismatch", '<button type="button" class="chrow'): "a chat's row, the same "
        "card: its name is the chat's, not the avatar's letter, the time and the last line",
    ("label-content-name-mismatch", '<button type="button" class="mcd'): "a month's day shows two "
        "numerals, the date and the count; its name says them as \"Tue 22 Sep 2026 - 7 entries\"",
}

fails, seen, out = [], set(), {}
def ok(c, msg):
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails.append(msg)

def check(pg, name):
    if not pg.evaluate("typeof axe !== 'undefined'"):
        pg.add_script_tag(content=AXE)
    vs = pg.evaluate(RUN, TAGS)
    out[name] = vs
    bad = 0
    for v in vs:
        left, new = 0, []
        for node in v["nodes"]:
            key = next((k for k in AXE_LEFT if k[0] == v["id"] and k[1] in node), None)
            if key:
                seen.add(key)
                left += 1
            else:
                new.append(node)
        if left:
            print(f"left {v['id']} ({left} nodes, AXE_LEFT)")
        if new:
            bad += len(new)
            print(f"       {v['id']} ({v['impact']}, {len(new)}): {', '.join(new[:4])}")
    ok(not bad, f"rule:axe on {name}: no violation but AXE_LEFT's ({bad} nodes)")

def page(b, vp, touch):
    ctx = b.new_context(viewport=vp, has_touch=touch, is_mobile=touch, device_scale_factor=2 if touch else 1)
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(perf.PAGE)
    pg.wait_for_selector("#list .item")
    pg.wait_for_timeout(1000)
    return pg

def ev(pg, js, ms=600):
    pg.evaluate(js)
    pg.wait_for_timeout(ms)

rows = perf.journal(400)
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    # the phone's six screens, walked as targets.py walks them
    pg = page(b, perf.PHONE, True)
    check(pg, "the phone's list")
    ev(pg, "select(st.view[0].id)", 700)
    check(pg, "the phone's reader")
    pg.click("#rwmode button[data-v=edit]")
    pg.wait_for_timeout(500)
    check(pg, "the phone's editor")
    ev(pg, "closeEditor()", 400)
    pg.click("#bMore")
    pg.wait_for_timeout(500)
    check(pg, "the phone's ⋯ sheet")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(400)
    pg.click("#bFilters")
    pg.wait_for_timeout(500)
    check(pg, "the phone's filters drawer")
    ev(pg, "closeDrawer()", 300)
    ev(pg, "calOpen('month', dayKey(st.all[0].created_at_utc))", 500)
    check(pg, "the phone's month")
    # the design pass's slice 4: the week and the day in the month's pattern
    ev(pg, "calOpen('week', dayKey(st.all[0].created_at_utc))", 500)
    check(pg, "the phone's week")
    ev(pg, "calOpen('day', dayKey(st.all[0].created_at_utc))", 500)
    check(pg, "the phone's day")
    ev(pg, "closeOv()", 300)
    # the design pass's slice 5: select mode, its actions in the foot
    ev(pg, "pickMode(true); pickToggle(st.view[0].id); pickToggle(st.view[1].id)", 400)
    check(pg, "the phone's select mode")
    ev(pg, "pickMode(false)", 300)

    # the desk's views
    pg = page(b, {"width": 1280, "height": 800}, False)
    check(pg, "the desk's list")
    ev(pg, "select(st.view[0].id)", 700)
    check(pg, "the desk's reader")
    pg.click("#rwmode button[data-v=edit]")
    pg.wait_for_timeout(500)
    check(pg, "the desk's editor")
    for name, js, ms in (("new entry", "closeEditor(); newEntry()", 700),
                         ("month", "closeEditor(); calOpen('month', dayKey(st.all[0].created_at_utc))", 600),
                         ("Tasks", "openTasks()", 900), ("Statistics", "openStats()", 1200),
                         ("chats", "chatsOpen()", 900), ("help", "openHelp()", 700),
                         ("palette", "openPalette()", 500), ("Reports", "openReports()", 900),
                         ("graph", "openGraph()", 1500),
                         ("Day view", "openDay(dayKey(st.view[0].created_at_utc))", 900),
                         ("select mode", "closeOv(); pickMode(true); pickToggle(st.view[0].id); pickToggle(st.view[1].id)", 400)):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        ev(pg, js, ms)
        check(pg, f"the desk's {name}")
    b.close()

for k in sorted(set(AXE_LEFT) - seen):
    ok(False, f"AXE_LEFT's {k} no longer shows: drop it from the list")
ok(not errs, f"no page errors: {errs[:3]}")
if "--json" in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, indent=1))
n = sum(len(v["nodes"]) for vs in out.values() for v in vs)
print(f"axe: {sum(len(vs) for vs in out.values())} violations, {n} nodes on {len(out)} screens")
print(f"axe: {len(fails)} failures")
sys.exit(1 if fails else 0)
