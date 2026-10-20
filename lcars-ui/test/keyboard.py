#!/usr/bin/env python3
"""Every text field takes a phone's keyboard the browser's way.

    python3 test/keyboard.py        (~15s in 6 shards, ~70s with KB_JOBS=1;
                                     run by test/run.sh, KB=0 skips it)

The keyboard is the browser's (0.161.1): iOS pans the page up to a focused
field, Android resizes it, and the page does not fit itself to the keys.
What the page still owes it is held here. At a phone's size this opens
everything a person can reach - every page in ROUTES, every row of the
command palette, the editor, the reader, an engineer's conversation, the
navigator - and in each finds every visible text field, scrolls to it, and
checks that it is the thing under the finger and that its font is at least
16px: under that, iOS zooms the page in when the field takes the focus
(and the viewport meta does not forbid zoom, which would also forbid the
pinch). A field added to any view later is found the same way.

Then: a field tapped while a view's data loads keeps the focus when the data
lands (fieldFocused, "the race"), and dropping the keyboard from a long
thread's box leaves the thread where it was scrolled.

Every place starts from home(), which puts the page back as it boots
(sheet, editor, drawer, focus, ambient mode, the microphone), so the places
are independent and are dealt out to parallel shards; the merged report is
the one a single shard would print. A place that left something up (ambient
mode once covered every later place, which then went unchecked) is a hole in
this test: reset it in home().

The API is stubbed (a handful of rows); nothing here touches lcars.db or a
server.
"""
import http.server
import json
import os
import pathlib
import socketserver
import subprocess
import sys
import threading
import time

import killclean  # its shards end with it when the run is killed
from playwright.sync_api import sync_playwright

D = pathlib.Path(__file__).resolve().parent.parent
W, H = 390, 664          # buttons.py's phone
MIN_FONT = 16            # px: under it iOS zooms the page into a focused field

now = time.time()
stamp = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
ROWS = [{
    "id": 500 - i, "kind": k, "title": t, "content": c, "content_length": len(c),
    "value_int": 0, "value_float": v, "done_bool": 0, "deleted": 0,
    "created_at_utc": stamp(now - i * 86400), "last_modified_at_utc": stamp(now - i * 86400),
    "start_date": "", "end_date": "",
} for i, (k, t, c, v) in enumerate([
    ("work_log", "Bridge log", "Met [[Fix the boiler]] today. #ship", 0),
    ("task", "Fix the boiler", "TODO call the plumber", 0),
    ("personal_log", "A day", "Walked by the river.", 0),
    ("weight", "weight", "", 80.0),
    ("weight", "weight", "", 79.6),
    # a course, so the navigator (the one chat's pane, in its sheet) is swept
    ("trip", "Up the Bucegi", json.dumps({"v": 1, "depart": "2026-10-12T08:00", "notes": "",
     "points": [{"name": "Busteni", "lat": 45.41, "lon": 25.53, "stay": 0}, {"name": "Omu", "lat": 45.445, "lon": 25.457, "stay": 0}],
     "legs": [{"mode": "foot_hiking"}]}), 0),
])]
ENGS = [{"name": "moreau-abc", "title": "Ilse Moreau", "task": "a task", "status": "idle",
         "git": {}, "active": int(now) - 60}]

# Before the page's script: the engineers' key, and the network watched
INIT = """
(() => {
  localStorage.setItem("lcars.deck.engkey", JSON.stringify("k"));
  // a slow network on demand, for the race below, and a count of requests
  // still out, so a check waits for a view's data rather than a guess at it
  const f0 = window.fetch;
  window.__netDelay = 0;
  window.__inflight = 0;
  window.fetch = (...a) => {
    window.__inflight++;
    const p = window.__netDelay
      ? new Promise(r => setTimeout(r, window.__netDelay)).then(() => f0(...a)) : f0(...a);
    // the count drops a task after the answer, once the page's own .then ran
    const done = () => setTimeout(() => window.__inflight--, 0);
    p.then(done, done);
    return p;
  };
})();
"""

# Rows of the palette not run: they leave the page or sign out
SKIP_ROWS = ("reload", "sign out", "log out", "deck", "update the app")

FIELDS_JS = """() => {
  const sel = 'input:not([type]),input[type=text],input[type=search],input[type=number],' +
              'input[type=email],input[type=url],input[type=password],input[type=tel],' +
              'input[type=date],input[type=datetime-local],input[type=time],textarea,[contenteditable=""],[contenteditable=true]';
  return [...document.querySelectorAll(sel)].map((el, i) => {
    if (el.disabled || el.readOnly || !el.getClientRects().length) return null;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || +cs.opacity === 0) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { i, ta: el.tagName === 'TEXTAREA', ov: !!el.closest('#ov'), name: el.id ? '#' + el.id : (el.getAttribute('aria-label') || el.placeholder || el.tagName.toLowerCase()) };
  }).filter(Boolean);
}"""

CHECK_JS = """([i]) => {
  const sel = 'input:not([type]),input[type=text],input[type=search],input[type=number],' +
              'input[type=email],input[type=url],input[type=password],input[type=tel],' +
              'input[type=date],input[type=datetime-local],input[type=time],textarea,[contenteditable=""],[contenteditable=true]';
  const el = document.querySelectorAll(sel)[i];
  if (!el) return { gone: true };
  // what a person does first: scroll to the field, and it must be the thing
  // under their finger (a field behind another layer is not tappable at all,
  // which is not this test's question)
  el.scrollIntoView({ block: 'nearest' });
  const q = el.getBoundingClientRect();
  const px = Math.min(Math.max(q.left + 12, 1), innerWidth - 2), py = Math.min(Math.max(q.top + Math.min(q.height, 40) / 2, 1), innerHeight - 2);
  const under = document.elementFromPoint(px, py);
  if (!under || !(under === el || el.contains(under) || under.contains(el) && under.tagName === 'LABEL')) return { gone: true };
  el.focus();
  return { font: parseFloat(getComputedStyle(el).fontSize), focused: document.activeElement === el };
}"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(D), **kw)

    def log_message(self, *a):
        pass


def stub(route):
    url = route.request.url.split("?")[0]
    if url.endswith("/engineer"):
        return route.fulfill(json={"engineers": ENGS, "deploy": {}})
    if "/engineer/" in url:
        return route.fulfill(json={"name": "moreau-abc", "title": "Ilse Moreau", "status": "idle",
                                   "session": "s", "past": [], "git": {}, "deploy": {}, "preview": "",
                                   "events": [], "next": 0, "first": 0})
    if "/stats" in url:
        return route.fulfill(json={"count": len(ROWS), "newest_created_at_utc": ROWS[0]["created_at_utc"]})
    if "/kinds" in url:
        return route.fulfill(json=[])
    if url.endswith("/media") or "/media" in url:
        return route.fulfill(json=[])
    if "/caldav" in url:
        return route.fulfill(status=404, json={"error": "not a task"})
    if "/entries/" in url:
        tail = url.rsplit("/entries/", 1)[1]
        if tail.isdigit():
            hit = next((r for r in ROWS if r["id"] == int(tail)), None)
            return route.fulfill(json=hit) if hit else route.fulfill(status=404, json={"error": "no"})
        return route.fulfill(json=[])
    if "/entries" in url:
        if route.request.method == "POST":
            return route.fulfill(json=dict(ROWS[0], id=900))
        return route.fulfill(json=ROWS)
    if "/dump" in url:
        return route.fulfill(status=404, json={"error": "no dump"})
    if "/embed" in url or "/chat" in url or "/ask" in url:
        return route.fulfill(status=503, json={"error": "off"})
    return route.fulfill(status=404, json={"error": "stub"})


def run(shard, nshards):
    """Run every place whose number % nshards == shard; give back what it saw.

    The places are numbered in one fixed order (the list, the editor, the
    reader, every page, an engineer, the race on every page, every palette
    row), each starting from home(), so a shard needs nothing from the places
    another shard ran. A failure is kept with its place and its order inside
    it, so the merge can print them exactly as one sequential run would."""
    fails, checked, places = [], [0], [0]
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        origin = "http://127.0.0.1:%d" % srv.server_address[1]
        api = origin + "/api"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": W, "height": H}, is_mobile=True, has_touch=True)
            ctx.set_default_timeout(15000)
            ctx.add_init_script(INIT)
            ctx.add_init_script("localStorage.setItem('lcars.cfg', %s);" %
                                json.dumps(json.dumps({"base": api, "user": "u", "pass": "p"})))
            ctx.route(api + "/**", stub)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("dialog", lambda d: d.dismiss())
            page.on("filechooser", lambda f: None)

            def boot():
                page.goto(origin + "/index.html", wait_until="domcontentloaded")
                page.wait_for_function("typeof st !== 'undefined' && st.all.length > 0")
                calm(600)

            def home():
                if "127.0.0.1" not in page.url or not page.evaluate("typeof st !== 'undefined' && st.all.length > 0"):
                    boot()
                page.evaluate("""() => {
                  if (document.body.classList.contains('dirty') && typeof setClean === 'function') setClean();
                  if (document.querySelector('#ov').classList.contains('on')) closeOv();
                  if (st.sel || st.isNew) closeEditor();
                  if (typeof closeDrawer === 'function') closeDrawer();
                  if (typeof setFocus === 'function') setFocus(false);
                  if (typeof ambStop === 'function') ambStop();
                  if (typeof vx !== 'undefined' && vx.on) voiceStop();
                  if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }""")
                page.wait_for_timeout(150)

            def calm(floor):
                """At least `floor` ms, then until no request is out and two
                frames have been drawn: a view's fields are there once its
                data has landed, which on a loaded box is not a fixed time."""
                page.wait_for_timeout(floor)
                try:
                    page.wait_for_function("window.__inflight === 0", timeout=10000, polling=50)
                except Exception:
                    pass        # a request that never ends: sweep what is there
                page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

            def fail(key, msg):
                fails.append((place[0], len(fails), key, msg))

            def sweep(where):
                """Every visible text field now on the page: under the finger, and big enough."""
                places[0] += 1
                for f in page.evaluate(FIELDS_JS):
                    try:
                        r = page.evaluate(CHECK_JS, [f["i"]])
                    except Exception:               # a focus that navigated, say
                        r = {"gone": True}
                    if r.get("gone"):
                        continue
                    checked[0] += 1
                    if r["font"] < MIN_FONT:
                        fail([f["name"], "font"], f"{where}: {f['name']} is {r['font']:g}px, so iOS zooms in when it is tapped")
                    if not r["focused"]:
                        fail([f["name"], "focus"], f"{where}: {f['name']} does not take the focus")
                    page.evaluate("() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }")

            def the_list():
                sweep("the list")

            # the editor (a new entry) and the reader
            def the_editor():
                home()
                page.evaluate("newEntry()")
                calm(400)
                sweep("the editor")

            def the_reader():
                home()
                page.evaluate("select(st.all[0].id)")
                calm(400)
                sweep("the reader")

            # every page
            def a_page(name):
                home()
                page.evaluate("n => { try { ROUTES[n].open(n === 'thread' ? [String(st.all[0].id)] : n === 'trend' ? ['ship'] : n === 'day' ? [] : []); } catch (e) {} }", name)
                calm(600)
                sweep("page " + name)

            # a crew note's thread open under its note in the reader: the
            # reply box is reached only through the note's chip
            def a_crew_note():
                home()
                page.evaluate("""() => {
                  const top = st.all.reduce((m, e) => Math.max(m, e.id), 0) + 1;
                  const at = st.all[0].created_at_utc;
                  const e = { id: top, kind: 'personal_log', title: 'Gym', content: '@yeoman log a gym session',
                              created_at_utc: at, last_modified_at_utc: at, deleted: 0 };
                  const h = noteScan(e.content)[0].hash;
                  const t = { id: top + 1, kind: 'crew_note', title: 'Yeoman · #' + top + ' Gym', value_int: top, deleted: 0,
                              created_at_utc: at, last_modified_at_utc: at, done_bool: 1,
                              content: 'status: answered\\nentry: #' + top + '\\nrole: yeoman\\n\\n### Captain · 2026-10-15 23:14 · note ' + h +
                                       '\\n@yeoman log a gym session\\n\\n### Yeoman · 2026-10-15 23:15\\nLogged.\\n' };
                  for (const r of [e, t]) { st.all.unshift(r); st.byId.set(r.id, r); }
                  select(top); setRead(true);
                  document.querySelector('#rd_notes .ntchip').click(); }""")
                calm(400)
                if not page.evaluate("!!document.querySelector('#rd_notes .ntq')"):
                    fail(["ntq", "missing"], "a crew note: its card has no reply box")
                sweep("a crew note")

            # an engineer's conversation
            def an_engineer():
                home()
                page.evaluate("chatsOpen(engThread('moreau-abc', 'Ilse Moreau').id)")
                calm(500)
                sweep("an engineer")

            # the navigator: the one chat's pane in the course sheet
            def the_navigator():
                home()
                page.evaluate("navOpen(st.all.find(e => e.kind === 'trip').id)")
                calm(900)
                sweep("the navigator")

            # the computer's thread with a log longer than the screen; and the
            # keyboard dropped from its box (a blur) leaves the log where it
            # was scrolled - it once jumped up as the page refitted itself
            def a_long_thread():
                home()
                page.evaluate("""() => { chat.msgs = [];
                  for (let i = 0; i < 60; i++) chat.msgs.push(i % 2 ? { role: 'asst', parts: [{ t: 'text', s: 'an answer, ' + i + ', '.repeat(3) + 'with **some** words in it' }] }
                                                         : { role: 'user', text: 'question ' + i });
                  openChat(); }""")
                calm(400)
                sweep("a long thread")
                for at in ("end", "middle"):
                    moved = page.evaluate("""at => new Promise(res => {
                      const log = document.querySelector('.chth .chlog'), box = document.querySelector('.chth .chbox');
                      if (at === 'middle') log.scrollTop = Math.round(log.scrollHeight / 3);
                      box.focus();
                      const y = log.scrollTop;
                      box.blur();
                      setTimeout(() => res(log.scrollTop - y), 450);
                    })""", at)
                    checked[0] += 1
                    if moved:
                        fail(["blur", at], f"a long thread: dropping the keyboard (scrolled to the {at}) moved the log {moved}px")
                page.evaluate("chat.msgs = []; chatSave()")

            # The race: a view draws its fields before its data lands, and a
            # field tapped in between must keep the focus (and on a phone the
            # keyboard) when it does. The engineers' list took it to a row.
            # Each page again, on a slow network, its first field tapped at once.
            def the_race(name):
                home()
                page.evaluate("window.__netDelay = 700")
                page.evaluate("n => { try { if (n === 'engineer') chatsOpen(engThread('moreau-abc', 'Ilse Moreau').id); else "
                              "ROUTES[n].open(n === 'thread' ? [String(st.all[0].id)] : n === 'trend' ? ['ship'] : []); } catch (e) {} }", name)
                # tapped as soon as the view is up, well inside the 700ms its
                # data is held back: after a fixed 60ms a loaded box may not
                # have drawn the view yet, and the race went unchecked
                try:
                    page.wait_for_function("document.querySelector('#ov').classList.contains('on')",
                                           timeout=500, polling=20)
                except Exception:
                    pass
                got = page.evaluate("""() => {
                  const ov = document.querySelector('#ov');
                  if (!ov.classList.contains('on')) return null;
                  const f = [...ov.querySelectorAll('input[type=text],input[type=search],input:not([type]),textarea')]
                    .find(el => !el.disabled && el.getClientRects().length);
                  if (!f) return null;
                  f.focus(); window.__tapped = f;
                  return f.id || f.getAttribute('aria-label') || f.placeholder || f.tagName; }""")
                if got:
                    # past the delayed answers and what the page did with them
                    calm(900)
                    checked[0] += 1
                    kept = page.evaluate("document.activeElement === window.__tapped")
                    if not kept:
                        took = page.evaluate("(a => a ? a.tagName + (a.id ? '#' + a.id : '') + (a.className ? '.' + a.className : '') : 'nothing')(document.activeElement)")
                        fail(None, f"page {name}: {got}, tapped while the page was loading, lost the focus to {took} when its data landed")
                page.evaluate("window.__netDelay = 0")

            # every row of the command palette, each from the list
            def a_row(label):
                home()
                ran = page.evaluate("""l => { const r = paletteRows().find(r => r.label === l);
                  if (!r) return false; try { r.run(); } catch (e) {} return true; }""", label)
                if not ran:
                    return
                calm(350)
                if "127.0.0.1" not in page.url:
                    boot()
                    return
                sweep("palette › " + label)

            place = [0]
            boot()
            routes = page.evaluate("Object.keys(ROUTES)")
            # the list is swept as the page boots, before anything else ran
            if shard == 0:
                the_list()
            home()
            labels = page.evaluate("paletteRows().map(r => r.label)")
            jobs = [the_list, the_editor, the_reader]
            jobs += [lambda n=n: a_page(n) for n in routes]
            jobs += [an_engineer, a_long_thread, the_navigator, a_crew_note]
            jobs += [lambda n=n: the_race(n) for n in routes + ["engineer"]]
            jobs += [lambda l=l: a_row(l) for l in labels if not any(s in l.lower() for s in SKIP_ROWS)]
            for i, job in enumerate(jobs):
                if i and i % nshards == shard:
                    place[0] = i
                    job()

            browser.close()
    return {"places": places[0], "checked": checked[0], "fails": fails, "errs": errs}


def main():
    # Shards in parallel, each its own Chromium: the places are independent
    # and the run is nearly all waiting on the page (~70s alone). KB_JOBS=1
    # runs them in this process, one after another.
    if len(sys.argv) == 3 and sys.argv[1] == "--shard":
        i, n = map(int, sys.argv[2].split("/"))
        print(json.dumps(run(i, n)))
        return
    n = int(os.environ.get("KB_JOBS") or min(6, os.cpu_count() or 1))
    print("-- every text field at a phone's size: reachable, no zoom, focus kept --", flush=True)
    if n <= 1:
        parts = [run(0, 1)]
    else:
        procs = [killclean.child(subprocess.Popen([sys.executable, __file__, "--shard", f"{i}/{n}"],
                                                   stdout=subprocess.PIPE, text=True))
                 for i in range(n)]
        parts = []
        for pr in procs:
            out, _ = pr.communicate()
            if pr.returncode:
                print(f"  FAIL a shard exited {pr.returncode}")
                sys.exit(1)
            parts.append(json.loads(out.strip().splitlines()[-1]))
    # a sweep's failure is reported once per field and keyboard, the first time
    # it is seen in the sequential order
    seen, fails = set(), []
    for _, _, key, msg in sorted(f for part in parts for f in part["fails"]):
        k = json.dumps(key) if key is not None else None
        if k is not None and k in seen:
            continue
        if k is not None:
            seen.add(k)
        fails.append(msg)
    errs = [e for part in parts for e in part["errs"]]
    print(f"keyboard: {sum(p['places'] for p in parts)} places, {sum(p['checked'] for p in parts)} field checks, {len(fails)} failures")
    for f in fails:
        print("  FAIL " + f)
    if errs:
        print("  (page errors seen, not counted: " + "; ".join(errs[:3]) + ")")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
