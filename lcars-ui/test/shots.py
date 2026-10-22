#!/usr/bin/env python3
"""Screenshot pass for the LCARS journal UI.

Renders index.html in headless Chromium (Playwright) against a stubbed API —
the live server needs basic auth, and screenshots should be deterministic
anyway — and captures the screens that matter into test/shots/.

Usage:  python3 test/shots.py            # writes test/shots/*.png
        python3 test/shots.py /tmp/out   # writes elsewhere
        python3 test/shots.py /tmp/out --only phone-list.png,phone-tasks.png

A shot whose steps fail (a button moved) is reported as FAILED and the run
goes on to the next, so one stale step costs one picture, not the rest;
the run then exits 1, naming them.

This is an eyeball harness, not an assertion suite: run it after a visual
change and look at the pictures. It found the clipped stats headers and the
flex-collapsed placeholder spaces that motivated it.
"""
import datetime
import json
import math
import pathlib
import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
_args = sys.argv[1:]
ONLY = set()
if "--only" in _args:
    i = _args.index("--only")
    ONLY = set(_args[i + 1].split(","))
    del _args[i:i + 2]
OUT = pathlib.Path(_args[0]) if _args else HERE / "shots"
FAILED = []
PAGE = (HERE.parent / "index.html").as_uri()
BASE = "https://lcars.test"   # the server the file:// page is pointed at (its lcars.cfg)

# ---------- fake journal ----------
KINDS = ["personal_log", "work_log", "task", "sleep_log", "page", "idea"]
MD = """- Morning review of the [[LCARS UI]] plan
- TODO follow up on the [[German course]] homework
  - unit 7 vocabulary, `der Termin`
  - DONE listening exercise
- Watched a talk on **force-directed layouts**
  - the [Fruchterman-Reingold](https://example.com/fr) paper
  - notes:: layout, graphs
> The grid bucketing trick keeps it linear.

```python
def tick(alpha):
    return alpha * 0.975
```
Some closing prose with a #journal tag and a [[link graph]] mention.
"""
SHORT = "- quick note about [[coffee]]\n- DOING water the plants\n"

rows = []
now = datetime.datetime.now().replace(hour=14, minute=30, second=0, microsecond=0)
for i in range(80):
    day = now - datetime.timedelta(hours=7 * i)
    kind = KINDS[i % len(KINDS)]
    content = MD if i % 9 == 0 else SHORT
    rows.append({
        "id": 1200 - i,
        "kind": kind,
        "title": {
            "personal_log": f"Log for {day:%b %d}",
            "work_log": "HTTP arena sizing notes",
            "task": "Renew passport",
            "sleep_log": f"Sleep {day:%m-%d}",
            "page": "German course",
            "idea": "Journal heatmap per kind",
        }[kind],
        "content": content,
        "content_length": len(content.encode()),
        # only the sleep log carries a number, hours slept, which is what a
        # kind that is a series looks like: the readings strip and the
        # statistics' measurements card each draw one line, not six
        "value_int": 0,
        "value_float": round(6.2 + ((i * 7) % 11) * 0.2, 1) if kind == "sleep_log" else 0,
        "done_bool": 1 if i % 7 == 0 else 0,
        "deleted": 1 if i % 23 == 0 and i else 0,
        "created_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
        "last_modified_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
    })


# Two entries of kind `template`, so the template picker and the entry it
# starts have something real behind them. They go on the end of the list, which
# is id order: prepending them would push every other shot's rows down a line.
TEMPLATES = [
    ("Weekly review {week}",
     "kind:: work_log\n\n## Week {week} — {date}\n\n- what shipped\n- what is stuck\n"
     "- next week\n  - {cursor}\n"),
    ("Standup {date}",
     "kind:: personal_log\n\n- yesterday:: \n- today:: \n- blocked:: {cursor}\n"),
]
for n, (t, c) in enumerate(TEMPLATES):
    day = now - datetime.timedelta(days=40 + n)
    rows.append({
        "id": 1119 - n, "kind": "template", "title": t, "content": c,
        "content_length": len(c.encode()),
        "value_int": 0, "value_float": 0.0, "done_bool": 0, "deleted": 0,
        "created_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
        "last_modified_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
    })


# The fixture's 80 rows span about three weeks, which is younger than anything
# resurface() or ambient mode will offer. These are the archive those two exist
# for: old enough to have been forgotten, long enough to be worth re-reading.
OLD = [
    (98, "The arena, as first sized",
     "- Sized the response arena at 1MB today, which is the number every page "
     "size in the client is derived from.\n"
     "- The halving on a 413 was the part I nearly left out — it is the only "
     "thing standing between a long entry and a wall of failed requests.\n"
     "- Worth remembering that the 224KB entry is not the worst case. The worst "
     "case is a hundred and fifty of them in one page.\n"
     "- See also [[LCARS UI]] and the [[link graph]] notes."),
    (211, "Why the journal is one file",
     "- Every dependency is a thing that can be unavailable on the evening you "
     "actually want to write something down.\n"
     "- So: one HTML file, no build, no bundler, works over file://.\n"
     "- The cost is that the file is long. The benefit is that it still opens "
     "in ten years.\n"
     "- [[German course]] notes went in the same day."),
    (402, "First week of the [[German course]]",
     "- Unit 1 and 2 done. The vocabulary is fine; the word order is not.\n"
     "- `der Termin`, `die Rechnung`, `das Angebot` — the three I keep losing.\n"
     "- Set a standing half hour before work rather than after it."),
]
for n, (age, t, c) in enumerate(OLD):
    day = now - datetime.timedelta(days=age)
    rows.append({
        "id": 1100 - n, "kind": "work_log" if n < 2 else "personal_log",
        "title": t, "content": c, "content_length": len(c.encode()),
        "value_int": 0, "value_float": 0.0, "done_bool": 0, "deleted": 0,
        "created_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
        "last_modified_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"),
    })


# Rows one shot adds to the journal (shoot's `extra`), newest first, on top of
# `rows`: a view that needs a Secret entry or a crew note's thread gets them
# without moving any other shot's list by a line.
EXTRA = []

# GET /reports, for the Reports page (made-up titles, the store's shape)
REPORTS = [
    {"path": "reports/2026/10/main-bridge-before-and-after-1a2b3c4d.html", "title": "Main bridge: before and after",
     "type": "html", "bytes": 48213, "published_utc": (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"path": "reports/2026/10/sleep-the-last-ninety-days-5e6f7a8b.png", "title": "Sleep, the last ninety days",
     "type": "png", "bytes": 182044, "published_utc": (now - datetime.timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"path": "reports/2026/10/deck-frame-budget-week-42-9c0d1e2f.html", "title": "Deck frame budget, week 42",
     "type": "html", "bytes": 73410, "published_utc": (now - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"path": "reports/2026/10/german-course-words-learned-3a4b5c6d.csv", "title": "German course: words learned",
     "type": "csv", "bytes": 9120, "published_utc": (now - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"path": "reports/2026/10/ten-forward-models-measured-7e8f9a0b.html", "title": "Ten Forward models, measured",
     "type": "html", "bytes": 61877, "published_utc": (now - datetime.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    {"path": "reports/2026/10/the-arena-sizes-a-year-on-1c2d3e4f.pdf", "title": "The arena's sizes, a year on",
     "type": "pdf", "bytes": 240117, "published_utc": (now - datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")},
]


def xrow(rid, kind, title, content, ago_h=0.5, **more):
    day = now - datetime.timedelta(hours=ago_h)
    r = {"id": rid, "kind": kind, "title": title, "content": content, "content_length": len(content.encode()),
         "value_int": 0, "value_float": 0.0, "done_bool": 0, "deleted": 0,
         "created_at_utc": day.strftime("%Y-%m-%d %H:%M:%S"), "last_modified_at_utc": day.strftime("%Y-%m-%d %H:%M:%S")}
    r.update(more)
    return r


# A Secret entry (docs/design/confidential-entries.md): on the server only
# its envelope, the title and text empty. The envelope is a made-up one of
# the right shape; the page never opens it here (the unlocked shot puts the
# plaintext in memory itself, as an unlock would).
SECRET_ENV = "lcs1.eyJ2IjoxLCJpdiI6IjNxN0Z3aU1rIn0.U2VjcmV0IGJ5IGRlc2lnbjogdGhlIHNlcnZlciBrZWVwcyBvbmx5IHRoaXM"
SECRET_PLAIN = {"title": "Doctor, Thursday", "value_int": 0, "value_float": 0,
                "content": "- Appointment moved to **Thursday, 10:30**.\n- Bring the old results.\n"
                           "- Ask about the dose, and whether the morning one can move to the evening."}
SECRET = [xrow(1301, "personal_log", "", "", classification=2, sealed=SECRET_ENV)]

# A crew note (docs/design/crew-notes.md): an "@yeoman" line in an entry and
# its thread, a crew_note row whose value_int is the entry. The captain's
# turn names the note by its hash, which the page works out from the line
# (noteHash): NOTEHASH is put right in the page before the shot.
NOTE_TEXT = "- Slow morning, coffee on the balcony.\n- @yeoman log my run this morning, 5 km\n- Call the garage about the tyres."
NOTE_ENTRY = xrow(1302, "personal_log", "Log for today", NOTE_TEXT, ago_h=0.4)


def note_thread(status):
    t0 = (now - datetime.timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M")
    t1 = (now - datetime.timedelta(minutes=19)).strftime("%Y-%m-%d %H:%M")
    body = (f"status: {status}\nentry: #1302\nrole: yeoman\n\n"
            f"### Captain · {t0} · note NOTEHASH\nlog my run this morning, 5 km\n")
    if status == "answered":
        body += (f"\n### Yeoman · {t1}\nLogged: a 5 km run this morning, 07:40, as #1304. "
                 "That makes three runs this week.\n\n"
                 "```crew-changes\n" + '{"op": "create", "id": 1304, "kind": "gym", "title": "Run, 5 km"}' + "\n```\n")
    return xrow(1303, "crew_note", "Yeoman · #1302 Log for today", body, ago_h=0.3, value_int=1302,
                done_bool=1 if status == "answered" else 0)


NOTE_SENT = [note_thread("queued"), NOTE_ENTRY]
NOTE_ANSWERED = [xrow(1304, "gym", "Run, 5 km", "> Yeoman created this, from a crew note\n\n- 5 km, 07:40", ago_h=0.3),
                 note_thread("answered"), NOTE_ENTRY]

# A trip (ARCHITECTURE.md, "Plot a course"): a coast by car, leaving
# tomorrow so the weather along it is a forecast. Shot with what the page
# uses with no Mapy.com key: OpenStreetMap's tiles, BRouter's route,
# Open-Meteo's weather - fetched for real, so it wants the network. A box
# may shoot its own trip from shots_trip.local.json beside this file
# ({"title", "points": [{"name", "lat", "lon", "stay"}, ...]}, a loop's
# start repeated at its end): the explainer film's course is measured on
# the captain's, and the public tree has neither (the *.local.* rule).
_dep = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%dT09:00")
_trip = {"title": "The Amalfi coast", "points": [
    {"name": "Sorrento", "lat": 40.6263, "lon": 14.3757, "stay": 0},
    {"name": "Positano", "lat": 40.6281, "lon": 14.4850, "stay": 60},
    {"name": "Amalfi", "lat": 40.6340, "lon": 14.6027, "stay": 45},
    {"name": "Ravello", "lat": 40.6492, "lon": 14.6117, "stay": 90},
    {"name": "Sorrento", "lat": 40.6263, "lon": 14.3757, "stay": 0}]}
if (HERE / "shots_trip.local.json").exists():
    _trip = json.loads((HERE / "shots_trip.local.json").read_text(encoding="utf-8"))
TRIP_PLAN = {"v": 1, "depart": _dep, "points": _trip["points"],
             "legs": [{"mode": "car_fast"}] * (len(_trip["points"]) - 1)}
TRIP = [xrow(1305, "trip", _trip["title"], json.dumps(TRIP_PLAN), ago_h=0.2)]


def meta(r):  # the content=0 sweep: no "content" key at all
    return {k: v for k, v in r.items() if k != "content"}


# Set to an id to make that row come back from a single-entry GET with a later
# last_modified_at_utc than the list handed out — which is exactly what a CLI or
# cron write looks like from here, and the only way to stage the conflict dialog.
CLASH_ID = None


def handle(route):
    url = route.request.url
    if route.request.method != "GET":
        # writes are acknowledged but not applied: a screenshot run has no
        # business mutating even a fixture halfway through a capture
        return route.fulfill(json={"ok": True, "id": 1200})
    every = EXTRA + rows
    if "/stats" in url:
        return route.fulfill(json={"count": len(every),
                                   "newest_created_at_utc": every[0]["created_at_utc"]})
    if url.split("?")[0].endswith("/reports"):
        return route.fulfill(json=REPORTS)
    if url.split("?")[0].endswith("/vault"):
        # a vault with a password set (its wrap's contents never read here):
        # the header's lock shows, and a Secret entry asks to be unlocked
        return route.fulfill(json={"version": 1, "vault": {"v": 1, "wraps": [{"type": "password"}]}})
    m = re.search(r"/entries/(\d+)", url)
    if m:
        rid = int(m.group(1))
        hit = next((r for r in every if r["id"] == rid), None)
        if not hit:
            return route.fulfill(status=404, json={"error": "no such entry"})
        if CLASH_ID is not None and rid == CLASH_ID:
            hit = dict(hit, last_modified_at_utc="2026-09-16 19:45:00",
                       title="a title somebody else typed")
        return route.fulfill(json=hit)
    if "/entries" in url:
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&") if "=" in p)
        off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
        body = q.get("content") != "0"
        sel = [r if body else meta(r) for r in every]
        return route.fulfill(json=sel[off:off + lim])
    return route.fulfill(status=404, json={"error": "not found"})


def shoot(p, width, height, name, prep=None, seed="", query="", extra=()):
    global EXTRA
    if ONLY and name not in ONLY:
        return
    EXTRA = list(extra)
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              device_scale_factor=2)
    # "/**", not "/*": a single star stops at a slash, so /entries/1200 would
    # slip past the stub and reach the real server (which answers 401)
    ctx.route(BASE + "/**", handle)
    # `seed` is for state a previous visit would have left behind — it has to be
    # planted before the page boots, since by the time prep() runs the app has
    # already read it (and, in the water mark's case, written its own).
    ctx.add_init_script(
        "localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));"
        "localStorage.removeItem('lcars.filters');%s" % (BASE, seed))
    page = ctx.new_page()
    # `query` is how a share sheet hands the app a link or a paragraph: a GET
    # share target is nothing but a query string on the app's own url, so the
    # picture is taken by arriving the way the OS would
    try:
        page.goto(PAGE + query)
        page.wait_for_timeout(1200)          # let both sweeps land
        if prep:
            prep(page)
            page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / name))
        print(name, "ok")
    except Exception as e:
        FAILED.append(name)
        print(name, "FAILED:", str(e).splitlines()[0])
    finally:
        browser.close()


def open_entry(page):                    # a markdown-heavy row (i=0 -> id 1200)
    page.click('.item[data-id="1200"]')


def open_edit(page):
    open_entry(page)
    page.wait_for_timeout(300)
    page.keyboard.press("e")


def open_commands(page):
    # the /command popup, on its own fresh line so nothing else is in the way
    open_edit(page)
    page.wait_for_timeout(300)
    page.click("#content")
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("/")


def open_daypage(page):
    page.click("#bDayPage")


def open_daypage_read(page):
    # The draft is what the button hands over, and the form is where it lands;
    # the reader cannot be reached without saving it, which the stub refuses on
    # purpose. So the same text is rendered through the reader's own path — the
    # picture worth having is the links, not the brackets around them.
    page.click("#bDayPage")
    page.wait_for_timeout(300)
    page.evaluate(
        "() => { const t = document.querySelector('#content').value;"
        " document.querySelector('#e_head').value = '';"
        " document.querySelector('#edbody').style.display = 'none';"
        " document.querySelector('#readbody').style.display = 'block';"
        " document.querySelector('#rd_title').textContent = isoDay(new Date());"
        " document.querySelector('#rd_meta').innerHTML = kindBadge('page');"
        " document.querySelector('#rd_content').innerHTML = mdRender(t); }")


def open_stats(page):
    page.click("#bStats")


def open_help(page):
    page.keyboard.press("?")


def open_tasks(page):
    page.click("#bTasks")


# On a phone the filters are a drawer, so everything parked in them — Tasks,
# Statistics, Resurface — is reached by opening it first. There is no `t` key
# down here to shortcut past it.
def open_tasks_phone(page):
    page.click("#bFilters")
    page.wait_for_timeout(300)
    page.click("#bTasks")


# Same reason as open_tasks_phone: on a phone the Month button and the saved
# views live in the drawer, so it has to be opened first.
def open_month_phone(page):
    page.click("#bFilters")
    page.wait_for_timeout(300)
    page.click("#bMonth")


def open_drawer_phone(page):
    page.click("#bFilters")
    page.wait_for_timeout(300)
    page.evaluate("() => { $('#side').scrollTop = 99999; }")


def open_tasks_done(page):
    page.click("#bTasks")
    page.wait_for_timeout(250)
    page.click('#tkscope button[data-v="done"]')


# what the visit before this one had got as far as seeing
SEEN = "localStorage.setItem('lcars.seen', '1195');"


def open_fresh(page):
    page.click("#bFresh")


def open_aloud(page):
    page.click('.item[data-id="1200"]')
    page.wait_for_timeout(300)
    # A stub, so the shot does not depend on the box having a voice installed —
    # headless Chromium has none, and its real synthesiser answers onerror,
    # which (correctly) puts the button straight back to "Aloud". defineProperty
    # rather than assignment: window.speechSynthesis is an accessor with no
    # setter, so `window.speechSynthesis = x` fails silently and the shot would
    # quietly photograph the real one instead.
    page.evaluate("""() => {
      window.SpeechSynthesisUtterance = function (t) { this.text = t; };
      Object.defineProperty(window, "speechSynthesis", {
        configurable: true,
        value: { speak: function () {}, cancel: function () {} },
      });
      ttsAloud();
    }""")


def open_graph(page):
    page.click("#bGraph")
    page.wait_for_timeout(2000)          # let the layout settle


def open_backlinks(page):
    # #1196 is the "German course" page; every MD row writes [[German course]],
    # so this is the entry with something to show. By id, not by text: the name
    # also appears in the snippets, and those rows are not the page.
    page.click('.item[data-id="1196"]')


def open_folded(page):
    open_entry(page)
    page.wait_for_timeout(400)
    page.click("#rd_content li.foldable .fbtn >> nth=0")


def open_voice(page):
    # There is no microphone in headless Chromium and no speech service behind
    # one, so the read-out is driven straight: the picture worth having is of
    # the chrome the dictation puts on screen, not of the recogniser.
    open_edit(page)
    page.wait_for_timeout(300)
    page.evaluate(
        "() => { $('#content').focus();"
        " vx.on = true; vx.live = true; vx.dict = true;"
        " vx.heard = 'and then we sized the arena at one megabyte';"
        " vPaint(); }")


def open_voice_video(page):
    # video dictation: the camera's preview is a canvas stream here, since
    # headless Chromium has no camera; what is worth seeing is where it sits
    open_voice(page)
    page.evaluate(
        "() => { const c = document.createElement('canvas'); c.width = 360; c.height = 480;"
        " const g = c.getContext('2d'); g.fillStyle = '#357'; g.fillRect(0, 0, 360, 480);"
        " g.fillStyle = '#fc6'; g.beginPath(); g.arc(180, 200, 90, 0, 7); g.fill();"
        " vx.tape = { video: true, h: { at: new Date(), cam: c.captureStream(10) } };"
        " vx.dictVideo = true; vPaint(); }")


def open_voice_paused(page):
    # dictation off: nothing is being typed, so orders answer with no wake word
    open_edit(page)
    page.wait_for_timeout(300)
    page.evaluate(
        "() => { $('#content').focus();"
        " vx.on = true; vx.live = true; vx.dict = false;"
        " vNote('not an order · the arena is a megabyte now');"
        " vPaint(); }")


def open_voice_help(page):
    page.evaluate("() => { vx.on = true; vx.live = true; vPaint(); voiceHelp(); }")


def open_pull(page):
    # The real handlers, driven by synthetic touches rather than by setting the
    # classes by hand: the strings and the travel are the page's own, so this
    # picture cannot quietly disagree with what a thumb would get. Stopped just
    # short of touchend, which is where the indicator is fully out and armed.
    page.evaluate(
        "() => { const list = $('#list');"
        " const at = y => [{ clientX: 100, clientY: y }];"
        " const fire = (type, pts) => list.dispatchEvent(Object.assign("
        "   new Event(type, { bubbles: true, cancelable: true }),"
        "   { touches: pts, changedTouches: pts }));"
        " fire('touchstart', at(300)); fire('touchmove', at(460)); }")


def open_config(page):
    # the sound switch and its volume live at the bottom of this panel, and a
    # slider is exactly the kind of control the assertions cannot look at
    page.click("#bCfg")


def open_delete_confirm(page):
    open_entry(page)
    page.wait_for_timeout(300)
    page.click("#bDel")


def open_month(page):
    page.click("#bMonth")


def open_month_prev(page):
    # the fixture writes every seven hours, so a full month back is the one
    # with a cell in every row of the grid rather than a half-filled one
    page.click("#bMonth")
    page.wait_for_timeout(250)
    page.click("#moprev")


def open_year(page):
    page.evaluate("() => calOpen('year', calToday())")


def open_week(page):
    page.evaluate("() => calOpen('week', calToday())")


def open_hours(page):
    page.evaluate("() => calOpen('day', calToday())")


# mid-drag: an entry lifted out of one day with another day lit under it, which
# is the one state of this view no static render would ever reach on its own
def open_month_drag(page):
    page.click("#bMonth")
    page.wait_for_timeout(250)
    page.evaluate("""() => {
      const chip = document.querySelector('#mogrid .mce');
      chip.classList.add('lift');
      const g = chip.cloneNode(true);
      g.className = 'mce calghost';
      const r = chip.getBoundingClientRect();
      g.style.left = (r.left + 150) + 'px';
      g.style.top = (r.top + 96) + 'px';
      document.body.appendChild(g);
      const cells = [...document.querySelectorAll('#mogrid .mcd[data-drop]')];
      const i = cells.indexOf(chip.closest('.mcd'));
      cells[Math.min(cells.length - 1, i + 9)].classList.add('drop');
    }""")


def open_trend(page):
    # "German course" is written by every MD row, so it has a real curve
    page.evaluate("() => openTrend('German course')")


def open_trend_alt(page):
    # the other half of the feature: alt-clicking a [[link]] in the reader
    page.click('.item[data-id="1200"]')
    page.wait_for_timeout(400)
    page.click("#rd_content a.wiki >> nth=0", modifiers=["Alt"])


def open_stack(page):
    # shift-click: the page the link names, pinned beside the entry it was
    # read from rather than opening in place of it. "German course" is the one
    # link in this row that the fixture has an actual page for.
    page.click('.item[data-id="1200"]')
    page.wait_for_timeout(400)
    page.click("#rd_content a.wiki >> text=German course", modifiers=["Shift"])


def open_stack_many(page):
    # the shelf: several pinned at once, one of them open and the rest bars.
    # The first is pinned by the gesture; the others go through the same call
    # the gesture makes, because the rest of the links in this row name pages
    # the fixture does not carry.
    open_stack(page)
    page.wait_for_timeout(250)
    page.evaluate("() => { stackOpen(1199, true); stackOpen(1195, true);"
                  " stackOpen(1191, true); stackFocus(1196); }")


def open_related(page):
    # #1196 is the "German course" page; the MD rows around it share its
    # vocabulary and its links, which is exactly what the block is guessing from
    page.click('.item[data-id="1196"]')
    page.wait_for_timeout(900)          # the vocabulary index builds in slices
    page.evaluate("() => { $('#readbody').scrollTop = 99999; }")


def open_templates(page):
    page.keyboard.press("N")


def open_from_template(page):
    page.evaluate("() => useTemplate(st.byId.get(1119))")


def open_capture_log(page):
    page.keyboard.press("q")
    page.wait_for_timeout(250)
    page.fill("#qc_text", "/log sleep_log 7,25 h woke once")


def open_stats_phone(page):
    page.evaluate("openStats()")


def open_capture(page):
    page.keyboard.press("q")
    page.wait_for_timeout(250)
    page.fill("#qc_text", "the sidecar timeout is 30s, not 5 — check the other two")


# What the OS share sheet sends: title, text and url as a plain query string.
# The picture is taken by arriving the way the OS would, so it exercises the
# real path (shareTarget) rather than a hand-filled box.
SHARE = ("?title=Force-Directed+Graph+Drawing"
         "&text=worth+reading+before+the+next+layout+pass"
         "&url=https%3A%2F%2Fexample.com%2Ffr")


# Three views already pinned, which is what the sidebar looks like once the
# feature has been used rather than on the day it was added.
VIEWS = ("localStorage.setItem('lcars.views', JSON.stringify(["
         "{name:'open tasks',qs:'q=TODO&o=0'},"
         "{name:'work log',qs:'k=work_log'},"
         "{name:'this week',qs:'a=2026-09-14'}]));")


def open_view_applied(page):
    page.click("#views .vcl >> nth=1")


def open_views_saving(page):
    # mid-flight: the name prompt, with the shape of the view printed above it
    page.fill("#q", "arena")
    page.wait_for_timeout(500)
    page.click("#bSaveView")


def open_scrub(page):
    # mid-drag, finger still down two thirds of the way along: the bubble
    # names the month under it and the list is already standing on it
    r = page.eval_on_selector("#rail", "e => { const b = e.getBoundingClientRect();"
                                       " return [b.left + b.width / 2, b.top, b.height]; }")
    page.mouse.move(r[0], r[1] + 8)
    page.mouse.down()
    page.mouse.move(r[0], r[1] + r[2] * 0.7, steps=6)


def open_fuzzy(page):
    # the palette on a query no label carries as typed: "wlog" is w, then
    # l-o-g, so work_log leads with its four letters marked
    page.keyboard.press("p")
    page.wait_for_timeout(200)
    page.keyboard.type("wlog")


def open_fuzzy_kinds(page):
    # the kind picker on "log": the kinds carrying it as typed, then the line
    # Tab stops at, then what only matched letter by letter
    page.keyboard.press("K")
    page.wait_for_timeout(200)
    page.keyboard.type("log")


def open_ambient(page):
    page.evaluate("() => ambStart()")
    page.wait_for_timeout(400)


def open_conflict(page):
    open_entry(page)
    page.wait_for_timeout(300)
    page.keyboard.press("e")             # into the form
    page.wait_for_timeout(200)
    page.fill("#e_head", "a title I typed")
    page.keyboard.press("Control+s")


def open_reports(page):
    page.evaluate("() => openReports()")


def open_secret(page):
    page.click('.item[data-id="1301"]')


def open_secret_unlocked(page):
    # an unlock (clsUnlock) leaves the master key and each envelope's
    # plaintext in memory; this puts them there itself, since the made-up
    # envelope opens with no key: the reader then shows what an unlocked
    # page shows, the header's lock reading Unlocked
    page.evaluate("""p => { cls.key = {}; cls.plain.set(p.env, p.plain);
      clsApply(st.byId.get(1301)); clsPaint(); fillList(); }""", {"env": SECRET_ENV, "plain": SECRET_PLAIN})
    page.wait_for_timeout(200)
    open_secret(page)


def note_prep(page, open_card):
    # the thread's captain turn names the note by its hash, as the watcher
    # writes it: the page's own noteHash of the line, put in its row
    page.evaluate("""open => { const e = st.byId.get(1302), t = st.byId.get(1303);
      t.content = t.content.replace("NOTEHASH", noteScan(e.content)[0].hash);
      if (open) ntState.open.add(noteKey(1302, "yeoman")); }""", open_card)
    page.click('.item[data-id="1302"]')


def open_note_sent(page):
    note_prep(page, False)


def open_note(page):
    note_prep(page, True)


def brouter_stub(route):
    """BRouter's answer for one leg (crsBrouter), made up: brouter.de is a
    volunteer's server and answers an HTML error page when busy, which the
    leg shows as a JSON parse error - not a picture for the explainer. A
    line from stop to stop with a gentle sideways wave (a coast road, more
    or less), its length by the great circle and its time at 45 km/h."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
    (lon0, lat0), (lon1, lat1) = [map(float, p.split(",")) for p in q["lonlats"][0].split("|")]
    n, co = 48, []
    for i in range(n + 1):
        u = i / n
        w = 0.012 * math.sin(u * math.pi * 3) * math.sin(u * math.pi)
        co.append([lon0 + (lon1 - lon0) * u - (lat1 - lat0) * w, lat0 + (lat1 - lat0) * u + (lon1 - lon0) * w, 0])
    m = sum(6371000 * math.hypot(math.radians(b[0] - a[0]) * math.cos(math.radians(a[1])), math.radians(b[1] - a[1]))
            for a, b in zip(co, co[1:]))
    body = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": co},
                                                       "properties": {"track-length": str(round(m)), "total-time": str(round(m / 12.5))}}]}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def open_course(page):
    # the trip opened on its map; the route stood in for (brouter_stub), the
    # weather (Open-Meteo) along it fetched for real, then the map fits it
    page.route("https://brouter.de/**", brouter_stub)
    page.evaluate("() => crsOpen(st.byId.get(1305))")
    page.wait_for_function("crs.map && crs.map._loaded", timeout=30000)
    page.wait_for_timeout(9000)


def main():
    global CLASH_ID
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        shoot(p, 1440, 900, "desktop-list.png")
        shoot(p, 1440, 900, "desktop-reader.png", open_entry)
        shoot(p, 1440, 900, "desktop-backlinks.png", open_backlinks)
        shoot(p, 1440, 900, "desktop-folded.png", open_folded)
        shoot(p, 1440, 900, "desktop-edit.png", open_edit)
        shoot(p, 1440, 900, "desktop-commands.png", open_commands)
        shoot(p, 1440, 900, "desktop-daypage.png", open_daypage)
        shoot(p, 1440, 900, "desktop-daypage-read.png", open_daypage_read)
        shoot(p, 1440, 900, "desktop-stats.png", open_stats)
        shoot(p, 1440, 900, "desktop-tasks.png", open_tasks)
        shoot(p, 1440, 900, "desktop-tasks-done.png", open_tasks_done)
        shoot(p, 1440, 900, "desktop-fresh.png", seed=SEEN)
        shoot(p, 1440, 900, "desktop-fresh-only.png", open_fresh, seed=SEEN)
        shoot(p, 1440, 900, "desktop-aloud.png", open_aloud)
        shoot(p, 1440, 900, "desktop-help.png", open_help)
        shoot(p, 1440, 900, "desktop-voice.png", open_voice)
        shoot(p, 1440, 900, "desktop-voice-paused.png", open_voice_paused)
        shoot(p, 1440, 900, "desktop-voice-video.png", open_voice_video)
        shoot(p, 1440, 900, "desktop-voice-help.png", open_voice_help)
        shoot(p, 1440, 900, "desktop-graph.png", open_graph)
        shoot(p, 1440, 900, "desktop-month.png", open_month)
        shoot(p, 1440, 900, "desktop-month-prev.png", open_month_prev)
        shoot(p, 1440, 900, "desktop-cal-year.png", open_year)
        shoot(p, 1440, 900, "desktop-cal-week.png", open_week)
        shoot(p, 1440, 900, "desktop-cal-day.png", open_hours)
        shoot(p, 1440, 900, "desktop-cal-drag.png", open_month_drag)
        shoot(p, 1440, 900, "desktop-trend.png", open_trend)
        shoot(p, 1440, 900, "desktop-trend-alt.png", open_trend_alt)
        shoot(p, 1440, 900, "desktop-stack.png", open_stack)
        shoot(p, 1440, 900, "desktop-stack-many.png", open_stack_many)
        shoot(p, 1440, 900, "desktop-related.png", open_related)
        shoot(p, 1440, 900, "desktop-templates.png", open_templates)
        shoot(p, 1440, 900, "desktop-from-template.png", open_from_template)
        shoot(p, 1440, 900, "desktop-capture.png", open_capture)
        shoot(p, 1440, 900, "desktop-capture-share.png", query=SHARE)
        shoot(p, 1440, 900, "desktop-capture-log.png", open_capture_log)
        shoot(p, 1440, 900, "desktop-views.png", seed=VIEWS)
        shoot(p, 1440, 900, "desktop-views-applied.png", open_view_applied, seed=VIEWS)
        shoot(p, 1440, 900, "desktop-save-view.png", open_views_saving, seed=VIEWS)
        shoot(p, 1440, 900, "desktop-scrub.png", open_scrub)
        shoot(p, 1440, 900, "desktop-fuzzy.png", open_fuzzy)
        shoot(p, 1440, 900, "desktop-fuzzy-kinds.png", open_fuzzy_kinds)
        shoot(p, 1440, 900, "desktop-ambient.png", open_ambient)
        shoot(p, 1440, 900, "desktop-config.png", open_config)
        shoot(p, 1440, 900, "desktop-reports.png", open_reports)
        shoot(p, 1440, 900, "desktop-secret-locked.png", open_secret, extra=SECRET)
        shoot(p, 1440, 900, "desktop-secret-unlocked.png", open_secret_unlocked, extra=SECRET)
        shoot(p, 1440, 900, "desktop-note-sent.png", open_note_sent, extra=NOTE_SENT)
        shoot(p, 1440, 900, "desktop-note.png", open_note, extra=NOTE_ANSWERED)
        shoot(p, 1440, 900, "desktop-course.png", open_course, extra=TRIP)
        shoot(p, 1440, 900, "desktop-confirm-delete.png", open_delete_confirm)
        CLASH_ID = 1200
        shoot(p, 1440, 900, "desktop-confirm-conflict.png", open_conflict)
        CLASH_ID = None
        shoot(p, 390, 844, "phone-list.png")
        shoot(p, 390, 844, "phone-reader.png", open_entry)
        shoot(p, 390, 844, "phone-confirm.png", open_delete_confirm)
        shoot(p, 390, 844, "phone-voice.png", open_voice)
        shoot(p, 390, 844, "phone-voice-video.png", open_voice_video)
        shoot(p, 390, 844, "phone-tasks.png", open_tasks_phone)
        shoot(p, 390, 844, "phone-fresh.png", seed=SEEN)
        shoot(p, 390, 844, "phone-pull.png", open_pull)
        shoot(p, 390, 844, "phone-capture.png", open_capture)
        shoot(p, 390, 844, "phone-stats.png", open_stats_phone)
        shoot(p, 390, 844, "phone-scrub.png", open_scrub)
        shoot(p, 390, 844, "phone-fuzzy.png", open_fuzzy)
        shoot(p, 390, 844, "phone-stack.png", open_stack)
        shoot(p, 390, 844, "phone-month.png", open_month_phone)
        shoot(p, 390, 844, "phone-course.png", open_course, extra=TRIP)
        shoot(p, 390, 844, "phone-cal-week.png", open_week)
        shoot(p, 390, 844, "phone-cal-year.png", open_year)
        shoot(p, 390, 844, "phone-ambient.png", open_ambient)
        shoot(p, 390, 844, "phone-views.png", open_drawer_phone, seed=VIEWS)
    if FAILED:
        sys.exit(f"shots: {len(FAILED)} failed: {', '.join(FAILED)}")


if __name__ == "__main__":
    main()
