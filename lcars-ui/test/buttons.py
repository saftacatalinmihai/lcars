#!/usr/bin/env python3
"""Every button, pressed: the views open from their buttons, close from theirs,
and nothing a press reaches throws.

    python3 test/buttons.py        (~6 min; LCARS_TEST_BIN=<binary> skips the build)

Since 0.121.0 every view is a page (./tasks, ./readings, …) and closing one is
a history step, so a Close button is no longer just `closeOv` in a browser's
eyes. The QuickJS suite (tests.js, "pages") holds the url rules against a fake
history; this is the rest, in Chromium at a desktop and at a phone's size:

- each view is opened by pressing what a person presses (the header button;
  on a phone, the tile in the ⋯ sheet, since the header hides them), gets its
  url, and is closed by its own Close button — then reopened and closed by
  Escape, and by the browser's Back;
- a view is reopened from a cold load of its url, and Close still closes it
  (the step below is then another document's: Close is a cross-document Back);
- every other button inside every view is pressed once, the view reopened
  before each, and any page error fails the run, as does a dialog left on
  screen that its Close button cannot take down;
- the same for every visible button in the main page and the reader.

A scratch server is built from the lcars-release compile line (to a temp path,
never ./lcars), serves lcars-ui/ at /ui/ like production, and runs on an
empty database the test fills; nothing here touches lcars.db.
"""
import json
import os
import pathlib
import shutil
import sys
import killclean  # its scratch goes when the run is killed
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import offline as rig  # the scratch build and server  # noqa: E402

UI = rig.UI
check, fails, checks = rig.check, rig.fails, rig.checks

# view -> (the button a desktop presses, the url it lands on)
VIEWS = [
    ("tasks", "#bTasks", "tasks"),
    ("calendar", "#bMonth", "calendar/"),
    ("stats", "#bStats", "stats"),
    ("readings", "#bExplore", "readings"),
    ("media", "#bMedia", "media"),
    ("reports", "#bReports", "reports"),
    ("graph", "#bGraph", "graph"),
    ("stars", "#bStars", "stars"),
    ("chats", "#bChat", "chats"),
    ("course", "#bCourse", "course"),
]
# Pressed nowhere: they leave the page (the deck, a reload) or are the ⋯ sheet
# itself, which has its own pass. Matched against id, then label.
SKIP_IDS = {"bDeck", "bReload", "bMore", "hRetry"}
SKIP_TEXT = ("deck", "reload", "sign out", "log out")


def seed(srv):
    day = 86400
    now = time.time()
    stamp = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
    for i in range(14):
        t = now - i * day
        srv.json("POST", "/entries", {"kind": "weight", "title": "weight", "content": "",
                                      "value_float": 80 - i * 0.3, "created_at_utc": stamp(t)})
        srv.json("POST", "/entries", {"kind": "sleep", "title": "sleep", "content": "",
                                      "value_float": 7 + (i % 3) * 0.5, "created_at_utc": stamp(t)})
    srv.json("POST", "/entries", {"kind": "task", "title": "Fix the boiler",
                                  "content": "TODO call the plumber\nDONE buy a part"})
    srv.json("POST", "/entries", {"kind": "work_log", "title": "Bridge log",
                                  "content": "Met [[Fix the boiler]] today. #ship"})
    srv.json("POST", "/entries", {"kind": "personal_log", "title": "A day",
                                  "content": "Walked by the river with [[Bridge log]]."})
    # an ops brief, pinned over today's day reader (a fold: see day_pin)
    srv.json("POST", "/entries", {"kind": "crew_ops", "title": "Ops brief",
                                  "content": "## Today\n- " + "\n- ".join(f"item {i}" for i in range(30))})
    # a course with two points, so its view has a leg, a stop and their buttons
    srv.json("POST", "/entries", {"kind": "trip", "title": "Up the Bucegi", "content": json.dumps({
        "v": 1, "depart": "2026-10-12T08:00", "notes": "",
        "points": [{"name": "Busteni", "lat": 45.4148, "lon": 25.5355, "stay": 0},
                   {"name": "Babele", "lat": 45.4067, "lon": 25.4823, "stay": 30},
                   {"name": "Omu", "lat": 45.4456, "lon": 25.4563, "stay": 0}],
        "legs": [{"mode": "foot_hiking"}, {"mode": "foot_hiking"}]})})
    # the blog post's shares (made up): two shares, their readings and two
    # runs, one share stale and in error, so the Shares view has every part
    sh = [srv.json("POST", "/entries", {"kind": "share", "title": t, "content": u, "created_at_utc": stamp(now - d * day)})["id"]
          for t, u, d in (("r/ClaudeAI", "https://www.reddit.com/r/ClaudeAI/comments/abc/my_post/", 3),
                          ("", "https://news.ycombinator.com/item?id=42", 2))]
    for i, (d, v) in enumerate(((2.5, 10), (1.5, 40), (0.5, 52))):
        srv.json("POST", "/entries", {"kind": f"crew_share_{sh[0]}", "title": f"{v} score · r/ClaudeAI", "value_int": v,
                                      "created_at_utc": stamp(now - d * day), "content": json.dumps(
                                          {"share": sh[0], "value": v, "main": "score", "source": "reddit",
                                           "comments": i * 3, "blog_views": 40 * i})})
    srv.json("POST", "/entries", {"kind": f"crew_share_{sh[1]}", "title": "5 points · HN", "value_int": 5,
                                  "created_at_utc": stamp(now - 1.5 * day), "content": json.dumps(
                                      {"share": sh[1], "value": 5, "main": "points", "source": "hn", "points": 5})})
    for d, v, extra in ((1.5, 45, {}), (0.5, 57, {"stale": [sh[1]], "errors": {str(sh[1]): "HTTP 503 from Algolia"}})):
        srv.json("POST", "/entries", {"kind": "crew_shares", "title": f"{v} · blog post, 2 shares", "value_int": v,
                                      "created_at_utc": stamp(now - d * day), "content": json.dumps(dict(
                                          {"value": v, "comments": 6, "shares": 2, "blog_views": 300 + v}, **extra))})


def ov_on(page):
    return page.evaluate("document.querySelector('#ov').classList.contains('on')")


def until(page, js, ms=5000):
    """Wait for `js` to hold, up to `ms`; whether it did. A check read after a
    fixed sleep is a race the page loses whenever the box is busy (its cores
    shared with the crew), so the checks below wait for what they check and
    fail only when it never comes."""
    try:
        page.wait_for_function(js, timeout=ms, polling=50)
        return True
    except Exception:
        return False


OV_ON = "document.querySelector('#ov').classList.contains('on')"
OV_OFF = "!" + OV_ON


def rel(page, base):
    return "/" + page.url.replace(base, "").lstrip("/").split("?")[0]


SHOTS = pathlib.Path(__file__).resolve().parent / "shots"


def tap(page, sel, what):
    """A real tap. A button something else is drawn over cannot be tapped,
    which is the failure this file exists to catch: say what covers it."""
    try:
        page.click(sel, timeout=5000)
        return True
    except Exception:
        info = page.evaluate("""s => { const b = document.querySelector(s); if (!b) return 'gone';
          const q = b.getBoundingClientRect(), e = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
          const d = document.querySelector('#dlg').getBoundingClientRect();
          return `button at ${Math.round(q.top)}-${Math.round(q.bottom)}, dialog ${Math.round(d.top)}-${Math.round(d.bottom)} of ${innerHeight}; covered by ${e ? e.outerHTML.slice(0, 80) : 'nothing'}`; }""", sel)
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / ("covered-" + what.replace(" ", "-").replace(":", "") + ".png")))
        check(False, f"{what}: cannot be tapped — {info}" + (f" (after {last[0]})" if last[0] else ""))
        return False


def fits(page, size, when):
    """A page wider than a phone's screen is zoomed out to fit, and the
    bottom of the layout — every sheet's Close row — leaves the screen."""
    w = page.evaluate("[document.documentElement.scrollWidth, innerWidth, innerHeight]")
    check(w[0] <= w[1] and w[1] <= 391 and w[2] <= 665,
          f"{size}: the page is as wide as the phone {when}  (scroll {w[0]}, layout {w[1]}x{w[2]})")


def press_view(page, mobile, sel):
    """What a person presses to open a view."""
    if mobile:
        # a press can leave the phone in the editor layer, the filter drawer or
        # focus mode, each of which covers the header: back to the list first
        page.evaluate("""() => { if (document.body.classList.contains('dirty')) setClean();
          if (st.sel || st.isNew) closeEditor(); if (typeof closeDrawer === 'function') closeDrawer();
          if (typeof setFocus === 'function') setFocus(false);
          if (document.body.classList.contains('fdon')) fdClose(); }""")
        page.wait_for_timeout(150)
        # a button the phone's header carries (0.125.0: the reader's choice) is
        # pressed where it is; the ⋯ sheet leaves out what the header holds
        if page.evaluate("s => typeof quick !== 'undefined' && quick.includes(s)", sel):
            tap(page, sel, f"phone header {sel}")
            until(page, OV_ON)
            page.wait_for_timeout(200)
            return
        if not tap(page, "#bMore", f"phone ⋯ (to open {sel})"):
            return
        page.wait_for_selector("#dlg .shtile")
        i = page.evaluate("s => MORE_TILES.findIndex(t => t[0] === s)", sel)
        if i < 0:
            page.evaluate("s => document.querySelector(s).click()", sel)
        else:
            tap(page, f'#dlg .shtile[data-i="{i}"]', f"phone ⋯ tile for {sel}")
    elif sel == "#bChat" and page.evaluate("dockAllowed()"):
        # a desk with the chat dock: the header's Chats is the dock's door
        # (UI review slice 5, rule:headers), and the list's ⤢ the full view
        # (a tap on it shuts the list when it is already open)
        if not page.is_visible('#dock .dklist [data-dk="list-full"]'):
            tap(page, sel, "desktop #bChat (the dock's list)")
        page.wait_for_selector('#dock .dklist [data-dk="list-full"]')
        tap(page, '#dock .dklist [data-dk="list-full"]', "the dock list's full view")
    else:
        tap(page, sel, f"desktop {sel}")
    until(page, OV_ON)
    page.wait_for_timeout(200)         # its first draw, before anything inside is pressed


def close_button(page):
    return page.evaluate("""() => {
      const bs = [...document.querySelectorAll('#dlg button')].filter(b => b.offsetParent);
      const b = bs.find(b => /^close$/i.test(b.textContent.trim())) ||
                bs.find(b => /close$/i.test(b.id));
      return b ? (b.id ? '#' + b.id : null) : null; }""")


def force_close(page):
    for _ in range(3):
        if not ov_on(page):
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    page.evaluate("closeOv()")
    page.wait_for_timeout(200)


def buttons_in(page, scope):
    """Every visible, enabled button under `scope`, as a way to find it again."""
    return page.evaluate("""([scope, skipIds, skipText]) => {
      const out = [];
      const all = [...document.querySelectorAll(scope + ' button')];
      all.forEach((b, i) => {
        if (!b.offsetParent || b.disabled) return;
        const t = (b.textContent || b.getAttribute('aria-label') || '').trim().toLowerCase();
        if (skipIds.includes(b.id) || skipText.some(s => t.includes(s))) return;
        out.push({ i, id: b.id, cls: b.className || '', t: t.slice(0, 30) });
      });
      return out; }""", [scope, list(SKIP_IDS), list(SKIP_TEXT)])


def press_nth(page, scope, n):
    page.evaluate("""([scope, n]) => {
      const b = document.querySelectorAll(scope + ' button')[n];
      if (b) b.click(); }""", [scope, n])
    page.wait_for_timeout(250)


# The version (0.183.5, the design pass): the header's #appVer always while
# the main page is up; #verMark, top centre over whatever covers the header,
# only while the page is stale (a newer version on the server), so a current
# page's covered screens show none. Seen means: the page's version, inside
# the screen, and the topmost thing at its centre (it lets taps through, so
# it is asked with pointer-events on). Stale, exactly one of the two, so no
# screen shows it twice.
VER_SEEN = """() => { const want = 'v' + APP_VERSION;
  const seen = el => { if (!el) return false; const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0 ||
        r.top < 0 || r.left < 0 || r.bottom > innerHeight || r.right > innerWidth) return false;
    const pe = el.style.pointerEvents; el.style.pointerEvents = 'auto';
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    el.style.pointerEvents = pe;
    // the header's reads "0.327.4 · live 0.327.5" while the server's differs
    return (el.textContent === want || el.textContent.startsWith(APP_VERSION + ' · live ')) &&
           !!top && (top === el || el.contains(top)); };
  return [seen(document.querySelector('#appVer')), seen(document.querySelector('#verMark'))]; }"""


def ver_seen(page, size, where, stale):
    hv, mk = page.evaluate(VER_SEEN)
    if stale:
        check(hv != mk, f"{size}: {where}, stale, shows the version once (header {hv}, mark {mk})")
    else:
        check(not mk, f"{size}: {where}, current, shows no floating mark (header {hv}, mark {mk})")


# the screens that are not a header button's view, each opened as the page
# opens it, and how it is left (the views' own loop checks theirs)
VER_SCREENS = [
    ("the ⋯ sheet", "openMore()", "closeOv()"),
    ("the settings", "openCfg()", "closeOv()"),
    ("the help", "openHelp()", "closeOv()"),
    ("the queue", "void openQueue()", "closeOv()"),
    ("a chat thread", "openChat()", "closeOv()"),
    ("a course", "openCourse(st.all.find(e => e.kind === 'trip').id)", "closeOv()"),
    ("the reader", "select(st.all.find(e => e.kind === 'work_log').id)", "closeEditor()"),
    ("the editor", "newEntry()", "setClean(); closeEditor()"),
    ("the filter drawer", "openDrawer()", "closeDrawer()"),
    ("ambient mode", "ambStart()", "ambStop()"),
    ("a photo held up", "mediaLight('data:image/gif;base64,R0lGODlhAQABAAAAACw=')", "mediaUnlight()"),
]


# a newer version on the server, as updCheck leaves it (no fetch), and back;
# Later on, to show it does not hide the mark (only the offer)
STALE_ON = """() => { const v = APP_VERSION.split('.'); v[2] = +v[2] + 1;
  upd.server = v.join('.'); lsSetStr('lcars.updLater', upd.server); updPaint(); }"""
STALE_OFF = """() => { upd.server = APP_VERSION; localStorage.removeItem('lcars.updLater'); updPaint(); }"""


def ver_pass(page, size):
    for stale in (False, True):
        page.evaluate(STALE_ON if stale else STALE_OFF)
        hv, _ = page.evaluate(VER_SEEN)
        check(hv, f"{size}: the main page shows its version under the clock (stale {stale})")
        for what, open_js, close_js in VER_SCREENS:
            page.evaluate(f"() => {{ {open_js}; }}")
            page.wait_for_timeout(400)
            ver_seen(page, size, what, stale)
            page.evaluate(f"() => {{ try {{ {close_js}; }} catch (e) {{}} }}")
            force_close(page)
            page.wait_for_timeout(300)
        ver_seen(page, size, "the main page again", stale)
    page.evaluate(STALE_OFF)


last = [""]          # the button pressed last, for a failure that shows up later


def day_pin(page, size):
    """The ops brief over today's day reader is a fold, closed by default so a
    phone still sees the day: one line closed; a tap on its summary opens and
    closes it in place (no thread, no fetch) and is remembered on the device;
    its Thread button is what opens the ops role's thread."""
    page.evaluate("localStorage.removeItem('lcars.ops-pin'); closeOv(); "
                  "openDay(dayKey(new Date().toISOString().slice(0, 19).replace('T', ' ')))")
    if not until(page, "!document.querySelector('#daypin').hidden"):
        check(False, f"{size}: today's day reader carries the ops brief")
        force_close(page)
        return
    url = rel(page, page.url.split("/ui/")[0])
    h = page.evaluate("[document.querySelector('#daypin').getBoundingClientRect().height,"
                      " document.querySelector('#crewpind').open]")
    check(not h[1] and h[0] < 40, f"{size}: the ops brief is folded to one line by default  ({h[0]:.0f}px)")
    tap(page, "#crewpinh", f"{size} ops brief summary")
    ok = until(page, "document.querySelector('#crewpind').open", 1000)
    tall = page.evaluate("document.querySelector('#daypin').getBoundingClientRect().height")
    check(ok and tall > 60, f"{size}: a tap on its summary unfolds it  ({tall:.0f}px)")
    check(rel(page, page.url.split("/ui/")[0]) == url and ov_on(page),
          f"{size}: and stays on the day, no thread  ({rel(page, page.url.split('/ui/')[0])})")
    # the toggle event is queued, not fired in the tap's own task
    check(until(page, "localStorage.getItem('lcars.ops-pin') === 'true'", 1000), f"{size}: remembered on the device")
    tap(page, "#crewpinh", f"{size} ops brief summary again")
    check(until(page, "!document.querySelector('#crewpind').open", 1000), f"{size}: a second tap folds it")
    tap(page, "#crewpinh", f"{size} ops brief summary, third")
    if tap(page, "#crewpinthr", f"{size} ops brief Thread"):
        check(until(page, "location.pathname.includes('/chats')"), f"{size}: its Thread button opens the ops thread  ({page.url})")
    page.evaluate("localStorage.removeItem('lcars.ops-pin')")
    force_close(page)


def shares_view(page, size, mobile, srv, errs):
    """The blog post's shares (./shares): no header button of its own, so it
    is reached as a person reaches it, Stats then its Shares button; its url,
    Close, Escape and Back; every button in it pressed (+ Share, Entry; the
    links to a share open a tab and are not buttons); the phone's fit."""
    def open_it():
        press_view(page, mobile, "#bStats")
        if not until(page, "!!document.querySelector('#s_shares')"):
            check(False, f"{size}: Stats has a Shares button")
            return False
        tap(page, "#s_shares", f"{size} Stats › shares")
        return until(page, "location.pathname.endsWith('/shares')")
    # from the list, not over an entry (day_pin's thread leaves one open on a
    # desktop, and a view closes back to the entry it covered)
    force_close(page)
    page.evaluate("() => { if (document.body.classList.contains('dirty')) setClean(); if (st.sel || st.isNew) closeEditor(); }")
    until(page, "/\\/ui\\/?$/.test(location.pathname)", 2000)
    ok = open_it()
    check(ok, f"{size}: the shares open from Stats, at ./shares  ({rel(page, srv.base)})")
    n = page.evaluate("document.querySelectorAll('#shrows .shcard').length")
    check(n == 2, f"{size}: a card per share  ({n})")
    if mobile:
        fits(page, size, "on the shares")
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / "shares-phone.png"))
    tap(page, "#sh_close", f"{size} shares Close")
    until(page, OV_OFF)
    until(page, "/\\/ui\\/?$/.test(location.pathname)", 2000)
    check(not ov_on(page) and rel(page, srv.base) in ("/ui/", "/ui"),
          f"{size}: the shares' Close closes them, to the list  ({rel(page, srv.base)})")
    force_close(page)
    open_it()
    page.keyboard.press("Escape")
    check(until(page, OV_OFF, 1500), f"{size}: Escape closes the shares")
    force_close(page)
    open_it()
    page.go_back()
    check(until(page, "!location.pathname.endsWith('/shares')", 2000), f"{size}: Back leaves the shares  ({rel(page, srv.base)})")
    force_close(page)
    open_it()
    todo = buttons_in(page, "#dlg")
    force_close(page)
    before = len(errs)
    for b in todo:
        open_it()
        press_nth(page, "#dlg", b["i"])
        last[0] = f"shares › {b['id'] or b['t']}"
        page.evaluate("() => { if (document.body.classList.contains('dirty')) setClean(); if (st.isNew || st.sel) closeEditor(); }")
        force_close(page)
    check(len(todo) >= 3 and len(errs) == before, f"{size}: {len(todo)} buttons in the shares pressed, no error"
          + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))


def share_view(page, size, mobile, srv, errs):
    """The Share sheet (./share/<id>, social-publish.md 3.2): opened from an
    entry as a person opens it - its tile in the editor's ⋯ sheet, at both
    sizes since research slice C; its url, Close, Escape and Back; every
    button in it pressed (the chips, Schedule…, Save link, Mastodon's Save;
    each Open is a link to a network and is not); the phone's fit."""
    def open_it():
        force_close(page)
        page.evaluate("() => { if (document.body.classList.contains('dirty')) setClean(); "
                      "select(st.all.find(e => e.kind === 'work_log').id); }")
        page.wait_for_timeout(300)
        if not tap(page, "#bEdMore", f"{size} the editor's ⋯ (for Share)"):
            return False
        page.wait_for_selector("#dlg .shtile")
        i = page.evaluate("[...document.querySelectorAll('#dlg .shtile')].findIndex(t => /Share/.test(t.textContent))")
        if i < 0:
            check(False, f"{size}: the editor's ⋯ sheet has a Share tile")
            return False
        tap(page, f'#dlg .shtile[data-i="{i}"]', f"{size} ⋯ › Share")
        return until(page, "/\\/share\\/\\d+$/.test(location.pathname) && !!document.querySelector('#soc_cards')")
    page.evaluate("localStorage.removeItem('lcars.soc.mastodon'); localStorage.removeItem('lcars.soc.nets'); shx = null")
    ok = open_it()
    check(ok, f"{size}: the Share sheet opens from the entry, at ./share/<id>  ({rel(page, srv.base)})")
    n = page.evaluate("document.querySelectorAll('#soc_cards .soccard').length")
    check(n == 7, f"{size}: a card per network  ({n})")
    if mobile:
        fits(page, size, "on the Share sheet")
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / "share-phone.png"), full_page=False)
    tap(page, "#soc_close", f"{size} Share Close")
    check(until(page, OV_OFF) and until(page, "!/\\/share\\//.test(location.pathname)", 2000),
          f"{size}: the Share sheet's Close closes it  ({rel(page, srv.base)})")
    open_it()
    page.keyboard.press("Escape")
    if not until(page, OV_OFF, 1500):        # the link field had the focus: Escape left it first
        page.keyboard.press("Escape")
    check(until(page, OV_OFF, 1500), f"{size}: Escape closes the Share sheet")
    open_it()
    page.go_back()
    check(until(page, "!/\\/share\\//.test(location.pathname)", 2000), f"{size}: Back leaves the Share sheet  ({rel(page, srv.base)})")
    force_close(page)
    open_it()
    todo = buttons_in(page, "#dlg")
    force_close(page)
    before = len(errs)
    for b in todo:
        if not open_it():
            break
        press_nth(page, "#dlg", b["i"])
        last[0] = f"share › {b['id'] or b['t']}"
        force_close(page)
    check(len(todo) >= 10 and len(errs) == before, f"{size}: {len(todo)} buttons in the Share sheet pressed, no error"
          + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))
    # Schedule… shows the reminder row, and its Set reminder makes one (the
    # chips reset: the pass above pressed X's off, and that is kept per device)
    page.evaluate("localStorage.removeItem('lcars.soc.nets'); shx = null")
    open_it()
    page.evaluate("document.querySelector('#soc_cards [data-sched=\"x\"]').click()")
    check(until(page, "!!document.querySelector('#soc_cards [data-remind=\"x\"]')"), f"{size}: Schedule… shows its reminder row")
    if tap(page, '#soc_cards [data-remind="x"]', f"{size} Set reminder"):
        check(until(page, "/reminder #\\d+/.test(document.querySelector('#socst_x').textContent)", 5000),
              f"{size}: Set reminder makes one  ({page.evaluate('document.querySelector(\"#socst_x\").textContent')})")
    force_close(page)
    page.evaluate("() => { if (document.body.classList.contains('dirty')) setClean(); if (st.sel || st.isNew) closeEditor(); }")


def rooms_view(page, size, srv, errs):
    """The Rooms page (docs/design/rooms.md 6): no header button of its own;
    its doors are the Chats list's Rooms row and the palette's row. From the
    chats its ‹, Escape and Back go back to the chats; from the journal they
    close it. Then every button in the list and in a room, pressed once.
    The engineer routes are stood in for (the scratch server has none), and
    the engineers feature taken as on."""
    base = srv.base + "/ui/"
    engs = {"engineers": [{"name": "number-one", "title": "Number One", "status": "idle", "active": 1},
                          {"name": "obrien-x", "title": "Chief O'Brien", "status": "idle", "active": 2}],
            "deploy": {}, "seat": None}
    page.route("**/engineer**", lambda r: r.fulfill(json=engs if r.request.url.split("?")[0].endswith("/engineer")
                                                    else {"ok": True, "status": "idle", "events": [], "next": 0, "first": 0}))
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("st.all.length > 0")
    # the server's features first: set while /features was still on its way
    # (a mirror paints the list before it answers), the answer landed after
    # and put the engineers back off ("The engineers is off on this server")
    until(page, "!!feat.map && !feat.ask", 10000)
    page.evaluate("""() => { localStorage.setItem('lcars.deck.engkey', JSON.stringify('k-test-key-0123456789'));
      if (feat.map) feat.map.set('engineers', { on: true, needs: [] }); }""")
    page.wait_for_timeout(300)
    in_chats = "!document.querySelector('#rmpage') && !!document.querySelector('#chrows')"

    def door():
        force_close(page)
        # a close from the chats is a history step (writeState's go back):
        # it lands before the chats open again, or they open into its popstate
        until(page, "/\\/ui\\/?$/.test(location.pathname)", 2000)
        page.wait_for_timeout(300)
        page.evaluate("chatsUp(); chatsList(); engListFetch(true)")
        until(page, "!!document.querySelector('#chrows [data-rooms]')")
        tap(page, "#chrows [data-rooms]", f"{size} the Chats list's Rooms row")
        # drawn at once, its url written on the next turn: a Back before
        # that would be the step under the chats
        return until(page, "!!document.querySelector('#rmlist') && location.pathname === '/ui/rooms'")
    check(door() and rel(page, srv.base) == "/ui/rooms", f"{size}: rooms opens from the Chats list's row, at ./rooms  ({rel(page, srv.base)})")
    if tap(page, "#rmback", f"{size} rooms ‹"):
        check(until(page, in_chats), f"{size}: rooms' ‹ goes back to the chats")
    door()
    page.keyboard.press("Escape")
    check(until(page, in_chats), f"{size}: Escape from rooms is the chats")
    door()
    page.go_back()
    check(until(page, in_chats), f"{size}: Back from rooms is the chats")
    force_close(page)
    ran = page.evaluate("() => { const r = paletteRows().find(r => /^view · rooms/.test(r.label)); if (r) r.run(); return !!r; }")
    check(ran and until(page, "!!document.querySelector('#rmlist')"), f"{size}: and from its palette row")
    if tap(page, "#rmback", f"{size} rooms ‹ (Close)"):
        check(until(page, OV_OFF), f"{size}: from the journal, its ‹ closes it")
    for how in ("escape", "back"):
        page.evaluate("openRooms()")
        until(page, "!!document.querySelector('#rmlist')")
        page.wait_for_timeout(200)
        if how == "escape":
            page.keyboard.press("Escape")
        else:
            page.go_back()
        check(until(page, OV_OFF), f"{size}: {how} closes rooms opened from the journal")
    # every button of the list and of a room (Number One's), pressed once
    before = len(errs)
    for where in ("", "main"):
        js = f"openRooms({where!r})"
        page.evaluate(js)
        until(page, "!!document.querySelector('#rmpage')")
        page.wait_for_timeout(300)
        todo = [b for b in buttons_in(page, "#dlg") if b["id"] != "rmsend"]   # Send would say to the stand-in: no row
        force_close(page)
        for b in todo:
            page.evaluate(js)
            until(page, "!!document.querySelector('#rmpage')")
            page.wait_for_timeout(200)
            press_nth(page, "#dlg", b["i"])
            last[0] = f"rooms {where or 'list'} › {b['id'] or b['t']}"
            force_close(page)
    check(len(errs) == before, f"{size}: the buttons in rooms pressed, no error" + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))
    # Archive (rooms.md 17): a crew room's ⋯ has it alone; the row goes under
    # the Archived fold, whose Restore puts it back; a long press (here its
    # contextmenu, which a desk's right click is too) shows a row's Archive
    force_close(page)
    # the close is a history step: let it land before opening again (door's wait)
    until(page, "/\\/ui\\/?$/.test(location.pathname)", 2000)
    page.wait_for_timeout(300)
    page.evaluate("openRooms('main')")
    until(page, "!!document.querySelector('#rmmore') && location.pathname === '/ui/rooms/main'")
    if tap(page, "#rmmore", f"{size} rooms ⋯") and tap(page, "[data-rmarchone]", f"{size} rooms ⋯ Archive"):
        check(until(page, "!!document.querySelector('#rmlist details[data-rmarchd] [data-rm=main]')"), f"{size}: the ⋯'s Archive: the room under Archived")
        tap(page, "#rmlist details[data-rmarchd] summary", f"{size} rooms' Archived fold")
        if tap(page, "#rmlist details[data-rmarchd] [data-rmunarch=main]", f"{size} rooms' Restore"):
            check(until(page, "!document.querySelector('#rmlist details[data-rmarchd]') && !rm.arch.size"), f"{size}: Restore: back on the list")
    page.evaluate("document.querySelector('#rmlist [data-rm=main]')?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))")
    if until(page, "!!document.querySelector('#rmlist .rmheld [data-rmarch=main]')") and \
            tap(page, "#rmlist .rmheld [data-rmarch=main]", f"{size} rooms' long-press Archive"):
        check(until(page, "!!document.querySelector('#rmlist details[data-rmarchd] [data-rm=main]') && !rm.arch.size"),
              f"{size}: a long press's Archive: the room under Archived")
        page.evaluate("rmArchive('main', false)")
        until(page, "!document.querySelector('#rmlist details[data-rmarchd]') && !rm.arch.size")
    else:
        check(False, f"{size}: a long press shows the row's Archive")
    force_close(page)
    page.unroute("**/engineer**")


def run(p, srv, mobile):
    size = "phone" if mobile else "desktop"
    print(f"-- {size} --", flush=True)
    browser = p.chromium.launch(headless=True, args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    ctx = browser.new_context(
        viewport={"width": 390, "height": 664} if mobile else {"width": 1300, "height": 860},
        is_mobile=mobile, has_touch=mobile)
    ctx.set_default_timeout(30000)
    cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
    ctx.add_init_script("localStorage.setItem('lcars.cfg', %s);" % repr(__import__("json").dumps(cfg)))
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("dialog", lambda d: d.dismiss())      # confirm()/prompt(): say no
    page.on("filechooser", lambda f: None)        # Attach/Camera: choose nothing
    base = srv.base + "/ui/"
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("st.all.length > 0")
    page.wait_for_timeout(800)
    if mobile:
        page.wait_for_timeout(3500)              # past the header's first glint (2s, ~2.5s long)
        fits(page, size, "after load")

    # ---- each view: its button opens it, its Close closes it, then Escape, Back
    for name, sel, url in VIEWS:
        press_view(page, mobile, sel)
        check(ov_on(page) and rel(page, srv.base).startswith("/ui/" + url),
              f"{size}: {name} opens from its button, at ./{url}  ({rel(page, srv.base)})")
        ver_seen(page, size, name, page.evaluate("document.body.dataset.stale === 'on'"))
        cb = close_button(page)
        check(cb is not None, f"{size}: {name} has a Close button")
        if cb and tap(page, cb, f"{size} {name} Close"):
            until(page, OV_OFF)
            until(page, "/\\/ui\\/?$/.test(location.pathname)", 2000)
            check(not ov_on(page), f"{size}: {name}'s Close closes it")
            check(rel(page, srv.base) in ("/ui/", "/ui"), f"{size}: and the url is the list again")
        force_close(page)
        press_view(page, mobile, sel)
        page.keyboard.press("Escape")
        if not until(page, OV_OFF, 1500):        # a field had the focus: Escape left it first
            page.keyboard.press("Escape")
            until(page, OV_OFF)
        check(not ov_on(page), f"{size}: Escape closes {name}")
        force_close(page)
        press_view(page, mobile, sel)
        page.go_back()
        until(page, OV_OFF)
        check(not ov_on(page), f"{size}: Back closes {name}")
        force_close(page)
        if mobile:
            fits(page, size, f"after {name}")

    # ---- the version on every other screen
    ver_pass(page, size)

    # ---- a cold load of a view's url, then Close: a Back into another document
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("st.all.length > 0")
    press_view(page, mobile, "#bExplore")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("document.querySelector('#ov').classList.contains('on')")
    check("readings" in page.url, f"{size}: a reload of ./readings opens it again")
    cb = close_button(page)
    if cb and tap(page, cb, f"{size} reloaded readings Close"):
        # a Back into the document before the reload: wait for it to boot
        page.wait_for_timeout(500)
        page.wait_for_function("typeof st !== 'undefined' && st.all.length > 0")
        until(page, OV_OFF)
        check(not ov_on(page), f"{size}: and its Close still closes it after the reload")
    force_close(page)

    # ---- every button inside every view, pressed once
    for name, sel, _ in VIEWS:
        press_view(page, mobile, sel)
        todo = buttons_in(page, "#dlg")
        force_close(page)
        before = len(errs)
        for b in todo:
            press_view(page, mobile, sel)
            if not ov_on(page):
                break
            press_nth(page, "#dlg", b["i"])
            force_close(page)
            last[0] = f"{name} › {b['id'] or b['t']}"
            if ov_on(page):
                check(False, f"{size}: {name} › {b['id'] or b['t']} left a dialog nothing closes")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_function("st.all.length > 0")
        check(len(errs) == before, f"{size}: {len(todo)} buttons in {name} pressed, no error"
              + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))

    # ---- every button inside a course (its view is opened from the list's row)
    open_course = "openCourse(st.all.find(e => e.kind === 'trip').id)"
    page.evaluate(open_course)
    until(page, "location.pathname.includes('/ui/course/')")
    page.wait_for_timeout(300)
    check(rel(page, srv.base).startswith("/ui/course/"), f"{size}: a course has a url of its own  ({rel(page, srv.base)})")
    todo = [b for b in buttons_in(page, "#dlg") if "chsend" not in b["cls"].split()]    # the navigator's Send would run claude
    force_close(page)
    before = len(errs)
    for b in todo:
        page.evaluate(open_course)
        page.wait_for_timeout(400)
        if not ov_on(page):
            break
        press_nth(page, "#dlg", b["i"])
        force_close(page)
        last[0] = f"course › {b['id'] or b['t']}"
    check(len(errs) == before, f"{size}: {len(todo)} buttons in a course pressed, no error"
          + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))

    day_pin(page, size)
    rooms_view(page, size, srv, errs)
    shares_view(page, size, mobile, srv, errs)
    share_view(page, size, mobile, srv, errs)

    # ---- the main page and the reader
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("st.all.length > 0")
    page.evaluate("select(st.all.find(e => e.kind === 'work_log').id)")
    page.wait_for_timeout(400)
    todo = buttons_in(page, "body > :not(#ov)")
    before = len(errs)
    for b in todo:
        if ov_on(page):
            force_close(page)
        if b["id"]:
            ok = page.evaluate("id => { const b = document.getElementById(id); "
                               "if (!b || !b.offsetParent || b.disabled) return false; b.click(); return true; }",
                               b["id"])
        else:
            ok = True
            press_nth(page, "body > :not(#ov)", b["i"])
        page.wait_for_timeout(250)
        force_close(page)
        if not page.evaluate("typeof st !== 'undefined' && !!st.all.length"):
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("st.all.length > 0")
        if "/ui/" not in page.url:
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("st.all.length > 0")
        page.evaluate("if (!st.sel) { const e = st.all.find(e => e.kind === 'work_log'); if (e) select(e.id); }")
    check(len(errs) == before, f"{size}: {len(todo)} buttons on the page and the reader pressed, no error"
          + ("" if len(errs) == before else ": " + "; ".join(errs[before:before + 3])))
    if mobile:
        check(not page.query_selector("#dock"), f"{size}: no chat dock at a phone's size")
    files_pass(page, size, mobile)
    check(not errs, f"{size}: no page error at all" + ("" if not errs else ": " + errs[0]))
    browser.close()


# Files in the chat (chat-dock.md 2.9): + in the composer, tappable at both
# sizes and opening the browser's picker (which is answered with nothing);
# a file given to the input is a chip whose × takes it out; a picture in a
# bubble opens the lightbox, Esc closes it; the chips row keeps a phone's fit.
PIC = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def files_pass(page, size, mobile):
    force_close(page)
    # a toast the passes before left up (the reader's last press: "no
    # templates yet", with its action, stays a while) sits over the chip's
    # row on a phone: gone before the chat is opened, as it would be
    page.evaluate("hideToast()")
    page.evaluate("openChat()")
    until(page, "!!document.querySelector('.chth .chplus:not([hidden])')")
    chose = []
    page.on("filechooser", lambda f: chose.append(f))
    if tap(page, ".chth .chplus", f"{size} chat +"):
        page.wait_for_timeout(300)
        check(len(chose) >= 1, f"{size}: + in a chat opens the file picker ({len(chose)})")
    page.set_input_files(".chth .chpick", files=[{"name": "note.txt", "mimeType": "text/plain", "buffer": b"hello"}])
    check(until(page, "document.querySelectorAll('.chth .chfchip').length === 1"), f"{size}: a picked file is a chip")
    if mobile:
        fits(page, size, "with a file chip above the box")
    if tap(page, ".chth .chfchip .chfx", f"{size} chip x"):
        check(until(page, "!document.querySelector('.chth .chfchip') && document.querySelector('.chth .chfiles').hidden"),
              f"{size}: the chip's × takes it out")
    page.evaluate("""pic => { chat.msgs.push({ role: 'user', text: 'a picture', files: [{ name: 'p.png', mime: 'image/png',
                                state: 'done', path: 'media/chat/p.png', url: pic, bytes: 70 }] }); chatDraw(); }""", PIC)
    sel = ".chth .chm:last-child .chimg"
    until(page, f"!!document.querySelector('{sel}')")
    page.evaluate(f"document.querySelector('{sel}').scrollIntoView()")
    if tap(page, sel, f"{size} chat picture"):
        check(until(page, "!!document.querySelector('#mlight')"), f"{size}: a picture in a bubble opens the lightbox")
        page.keyboard.press("Escape")
        check(until(page, "!document.querySelector('#mlight')") and ov_on(page),
              f"{size}: Esc closes the lightbox, and only it")
    page.evaluate("chat.msgs.pop(); chatDraw(); chatSave()")
    force_close(page)


# The chat dock (docs/design/chat-dock.md 1.12): at a desk the pill, every
# button of the list panel, a window's ─ ⤢ ×, a tab, the overflow menu, each
# pressed for real (a covered one is a failure); none in the deck's frame.
DOCK_THREADS = {"seq": 4, "model": "sonnet", "list": [
    {"id": "computer-%d" % i, "at": i, "msgs": [{"role": "user", "text": "thread %d" % i}]} for i in range(1, 5)]}
DOCK_STATE = {"list": "pill", "wins": [{"id": "computer-1"}, {"id": "computer-2"}, {"id": "computer-3"},
                                       {"id": "computer-4", "min": True}],
              "focus": ["computer-1", "computer-2", "computer-3", "computer-4"]}


def dock_pass(p, srv):
    print("-- the chat dock --", flush=True)
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1300, "height": 860})
    ctx.set_default_timeout(30000)
    cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
    ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) {"
                        f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.chats', {json.dumps(json.dumps(DOCK_THREADS))});"
                        f"localStorage.setItem('lcars.dock', {json.dumps(json.dumps(DOCK_STATE))}); }}")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(srv.base + "/ui/", wait_until="domcontentloaded")
    page.wait_for_function("st.all.length > 0 && dock.shown")
    page.wait_for_timeout(500)
    W = '#dock .dkwin[data-id="%s"]'
    check(not page.query_selector("#dock .dkpill"), "dock: no pill floats at the lower right (the header's Chats is its door)")
    check(page.is_visible("#dock .dkovf"), "dock: three windows and a tab at 1300px: the overflow tab")
    if tap(page, "#dock .dkovf .dkmore", "dock overflow tab"):
        check(page.is_visible("#dock .dkmenu"), "dock: the overflow tab opens its menu")
        if tap(page, "#dock .dkmenu .dkmrow .dktabo", "dock overflow pick"):
            picked = page.evaluate("dock.focus[0]")
            check(page.is_visible(W % picked), f"dock: a pick opens its window ({picked})")
    tab = page.evaluate("(document.querySelector('#dock .dktab') || {}).dataset?.tab || ''")
    if tab and tap(page, f'#dock .dktab[data-tab="{tab}"] .dktabo', "dock tab"):
        check(page.is_visible(W % tab), "dock: a tab opens its window")
    cur = page.evaluate("dock.focus[0]")
    if tap(page, (W % cur) + " .dkmin", "dock window minimise"):
        check(page.is_visible(f'#dock .dktab[data-tab="{cur}"]'), "dock: ─ minimises the window to a tab")
    cur = page.evaluate("[...document.querySelectorAll('#dock .dkwin')].map(e => e.dataset.id)[0]")
    if tap(page, (W % cur) + " .dkx", "dock window close"):
        check(not page.query_selector(W % cur), "dock: × closes the window")
        undo = page.query_selector("#toast.on button")
        check(undo is not None and undo.text_content().strip() == "Undo", "dock: Closed · Undo")
    cur = page.evaluate("[...document.querySelectorAll('#dock .dkwin')].map(e => e.dataset.id)[0]")
    if tap(page, (W % cur) + " .dkfull", "dock window full view"):
        page.wait_for_timeout(300)
        check(page.evaluate("chatUp() && document.querySelector('#dock').hidden"), "dock: ⤢ is the full view, the dock hidden")
        page.keyboard.press("Escape"); page.wait_for_timeout(200)
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        check(page.evaluate("!chatUp() && dock.shown"), "dock: and back when it closes")
    if tap(page, "#bChat", "header Chats (the dock's door)"):
        check(page.is_visible("#dock .dklist"), "dock: the header's Chats opens the list panel")
    for b in page.evaluate("[...document.querySelectorAll('#dock .dklist .chhdr button')].map(b => b.dataset.dk)"):
        if not page.is_visible("#dock .dklist"):
            page.evaluate("dockExpand(false)"); page.wait_for_timeout(200)
        if not tap(page, f'#dock .dklist [data-dk="{b}"]', f"dock list {b}"):
            continue
        page.wait_for_timeout(300)
        if b == "list-full":
            check(page.evaluate("chatUp()"), "dock: the list's ⤢ is the full Chats list")
        elif b == "collapse":
            check(not page.is_visible("#dock .dklist"), "dock: the list's ─ shuts it")
        elif b == "new":
            check(page.evaluate("!!dockFm()"), "dock: the list's + is a new computer thread, in a window")
        page.evaluate("if (chatUp()) closeOv()"); page.wait_for_timeout(300)
    page.evaluate("dockExpand(false)"); page.wait_for_timeout(200)
    if tap(page, '#dock .dkrows .chrow[data-id="computer-2"]', "dock list row"):
        check(page.is_visible(W % "computer-2"), "dock: a row of the list opens its window")
    check(not errs, "dock: no page error" + ("" if not errs else ": " + errs[0]))
    # in the deck's frame: none (a context of its own, without the service
    # worker, which would answer deck.html itself and pass the route by)
    ctx.close()
    ctx = browser.new_context(viewport={"width": 1300, "height": 860}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.dock', {json.dumps(json.dumps(DOCK_STATE))});")
    ctx.route("**/ui/deck.html", lambda r: r.fulfill(content_type="text/html",
              body='<!doctype html><iframe src="/ui/" style="width:1280px;height:800px"></iframe>'))
    page = ctx.new_page()
    page.goto(srv.base + "/ui/deck.html")
    fr = None
    for _ in range(100):
        fr = next((f for f in page.frames if f != page.main_frame and f.url.rstrip("/").endswith("/ui")), None)
        if fr and fr.evaluate("typeof dock !== 'undefined' && typeof st !== 'undefined' && st.all.length > 0"):
            break
        page.wait_for_timeout(200)
    page.wait_for_timeout(600)
    got = fr.evaluate("[inDeck(), !!document.querySelector('#dock'), dock.shown]") if fr else "no frame"
    check(got == [True, False, False], f"dock: none in the deck's frame  (in the deck, a #dock, shown: {got})")
    browser.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-btn-", dir=os.path.expanduser("~/.cache")))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        rig.build(binary)
    os.environ["LCARS_UI_DIR"] = str(UI)       # served at /ui/, as in production
    srv = rig.Server(binary, tmp)
    try:
        seed(srv)
        with sync_playwright() as p:
            run(p, srv, False)
            dock_pass(p, srv)
            run(p, srv, True)
    finally:
        srv.stop()
    print(f"\nbuttons: {checks[0]} checks, {len(fails)} failures")
    for f in fails:
        print("  - " + f)
    if fails:
        print(f"server log kept in {tmp}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
