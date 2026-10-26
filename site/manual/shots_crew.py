#!/usr/bin/env python3
"""The manual's pictures of the crew (the chats, a room, open questions),
which lcars-ui/test/shots.py does not frame: perf.py's stubbed API (made-up
rows) with made-up crew (Chief Reyes, Lt. Okafor) put in the page. Never a
real server: every request to lcars.test is the stub's, the rest aborted.

    python3 site/manual/shots_crew.py OUT    # three PNGs into OUT, ~15s
pictures.sh runs it; see README.md."""
import sys, re, pathlib
T = pathlib.Path(__file__).resolve().parent.parent.parent / "lcars-ui" / "test"
sys.path.insert(0, str(T))
import perf  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
if len(sys.argv) != 2:
    sys.exit("usage: shots_crew.py OUT")
OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
rows = perf.journal(300)

SETUP = r"""async () => {
  localStorage.setItem('lcars.deck.engkey', JSON.stringify('k'));
  if (typeof feat !== 'undefined' && feat.map) { feat.map.set('engineers', { on: true, needs: [] }); feat.map.set('computer', { on: true, needs: [] }); }
  const now = Date.now() / 1000;
  eng.list = [
    { name: 'number-one', title: 'Number One', status: 'idle', active: now - 600, task: 'reviewing the day planner' },
    { name: 'reyes-c12', title: 'Chief Reyes', status: 'working', active: now - 30, task: 'add a week view to the calendar' },
    { name: 'okafor-c14', title: 'Lt. Okafor', status: 'queued', active: now - 900, task: 'tidy the search options' },
  ];
  eng.seat = { holder: 'reyes-c12', queue: ['okafor-c14'] };
  eng.at = Date.now() + 1e9;
  const top = st.all.reduce((m, e) => Math.max(m, e.id), 0), at = '2026-10-25 09:00:00', R = [];
  R.push({ id: top + 1, kind: 'crew_room', title: 'Calendar week view', content: 'id:: calendar\nby:: captain', done_bool: 0, deleted: 0, created_at_utc: at, last_modified_at_utc: at });
  const msgs = [
    ['captain', 'no1', 'room:: calendar\nThe week view should show each day\'s tasks as dots.'],
    ['no1', 'reyes-c12', 'to:: reyes-c12\nAdd dots for open tasks to each day of the week strip. Keep the month as it is.'],
    ['reyes-c12', '', 'room:: calendar\nReport: done. Each day in the week strip has a dot per open task, three at most. Built and tested; committed on my branch.'],
    ['ship', '', 'room:: calendar\n[deploy finished] reyes-c12: deployed as 1.4.2'],
  ];
  msgs.forEach(([f, to, c], i) => R.push({ id: top + 2 + i, kind: 'crew_msg', title: f + ' → ' + (to ? to + ' ' : '') + '#calendar: ' + c.split('\n')[1].slice(0, 80),
    content: c, done_bool: 1, deleted: 0, created_at_utc: '2026-10-25 09:0' + (i + 1) + ':00', last_modified_at_utc: at }));
  R.push({ id: top + 10, kind: 'task_no1', title: 'The week view', done_bool: 0, deleted: 0, created_at_utc: at, last_modified_at_utc: at,
    content: 'Reyes has the week view ready on a branch.\nQ1: Ship the week view today?\nThe phone check passed.\nOptions: A) ship now B) wait for a tablet check C) drop it\nRecommendation: A, it is tested.\nQ2: Keep the old month strip as well?\nRecommendation: no' });
  for (const r of R) st.byId.set(r.id, r);
  st.all = R.slice().reverse().concat(st.all);
  if (typeof rm !== 'undefined') rm.gen++;
}"""

def shot(page, name, js, wait=900):
    try:
        page.evaluate("try{closeOv()}catch(e){}")
        page.wait_for_timeout(300)
        page.evaluate(js)
        page.wait_for_timeout(wait)
        page.screenshot(path=str(OUT / name))
        print(name, "ok")
    except Exception as e:
        print(name, "FAILED", str(e)[:300])

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2, is_mobile=True, has_touch=True)
    ctx.route(re.compile(r"^https?://(?!lcars\.test/)"), lambda r: r.abort())
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
    page = ctx.new_page()
    page.goto(perf.PAGE)
    page.wait_for_function("typeof st !== 'undefined' && st.all && st.all.length > 100", timeout=30000)
    page.wait_for_timeout(1500)
    page.evaluate(SETUP)
    shot(page, "phone-chats.png", "chatsOpen()")
    shot(page, "phone-room.png", "(async()=>{await openRooms('calendar'); try{rmStop()}catch(e){}})()", 1500)
    shot(page, "phone-questions.png", "openQuestions()")
    b.close()
