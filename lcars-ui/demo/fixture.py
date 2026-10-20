#!/usr/bin/env python3
"""The journal the demo video films.

test/shots.py has a fixture too, but it is built for screenshots: eighty rows
of the same two lines, which is all an eyeball harness needs. A demo that ends
up on a front page is read, not glanced at — every line that survives a pause
is a line somebody will actually read — so this one is written out: four months
of a journal that could belong to somebody, with links that mean something and
a couple of long entries worth stopping on.

Shape of a row is the server's, verbatim (see FIELDS in index.html):
    id kind title content content_length value_int value_float
    done_bool deleted created_at_utc last_modified_at_utc

Anything here can be rewritten without touching demo.py, with one catch: the
scenes open entries by id, so the IDs block below is the contract between the
two files.
"""
import datetime
import json
import os
import random

# ---------------------------------------------------------------- the clock
# Anchored to "now" so the top of the list says today / yesterday — a journal
# whose newest entry is three weeks old reads as abandoned. The time of day is
# pinned so two runs in the same afternoon cut identically.
#
# Set LCARS_DEMO_NOW=YYYY-MM-DD to pin it: the title card prints a stardate and
# every row is dated relative to this, so without a pin two builds of the same
# cut do not match.
_pin = os.environ.get("LCARS_DEMO_NOW")
NOW = (datetime.datetime.fromisoformat(_pin) if _pin else datetime.datetime.now())
NOW = NOW.replace(hour=16, minute=20, second=0, microsecond=0)
DAYS = 126                      # how far back the journal goes


# ------------------------------------------------------------------- the ids
# demo.py opens these by id. Keep them if you rewrite the prose.
class IDS:
    SHOWCASE = 2400             # the long markdown entry the reader scene opens
    PAGE_LCARS = 2399           # the [[LCARS UI]] page — backlinks scene
    ARENA = 2398                # the entry the search scene lands on
    # The generated rows count down from SHOWCASE and land somewhere near
    # 2150, so the hand-placed block at the bottom starts well under that.
    TEMPLATE = 1500             # the template the "new entry" scene starts from
    PINNED_TASK = 1490          # the open tasks that lead the task view


# ------------------------------------------------------------- the long ones
# Written by hand, because these are the ones the camera rests on.
#
# None of them opens with a heading that repeats its own title: the reader
# prints the title above the body already, and on camera the pair reads as a
# bug. It also wastes the list snippet, which is the first line of the body.
SHOWCASE = """\
- Spent the morning on [[link graph]] and it is finally not a hairball.
- The fix was not the force calculation at all — it was that every node
  started at the same point, so the first tick had nothing to push apart.
  - seed them on a circle, `theta = i / n * TAU`
  - DONE ship it
  - TODO write this down in [[LCARS UI]] before I forget why
- Read the [Fruchterman-Reingold](https://example.com/fr) paper properly
  instead of skimming the Wikipedia summary. The temperature schedule is the
  whole trick and I had been ignoring it.

> Nodes repel, edges pull, and the whole thing cools. That is it. That is
> the algorithm.

```js
function tick(alpha) {
  for (const n of nodes) { n.vx *= DAMP; n.vy *= DAMP; }
  return alpha * 0.975;          // the cooling schedule
}
```

- The grid bucketing keeps it linear enough to run on a phone, which was the
  actual constraint — see [[Bajor NAS]] for why this has to work offline.
- notes:: layout, graphs, #journal
"""

ARENA = """\
- Settled on 1MB. Every page size in the client is derived from that number,
  so it is worth writing down why.
- The halving on a 413 is the part I nearly left out, and it is the only
  thing standing between one long entry and a wall of failed requests.
  - request 150 rows, get a 413, ask for 75, then 37
  - DONE the retry loop
  - DOING a test that actually trips it
- The worst case is not the 224KB entry. The worst case is a hundred and
  fifty of them in one page, which is a thing that happens the week you
  import old notes.
- See [[LCARS UI]] for where the number surfaces, and [[link graph]] for the
  one view that ignores it entirely.
"""

PAGE_LCARS = """\
The single-file journal client. One HTML file, no build step, no bundler.

- Works over `file://`, over plain http on the LAN, and over https.
- Every dependency is a thing that can be unavailable on the evening you
  actually want to write something down — so there are none.
- The cost is that the file is long. The benefit is that it still opens in
  ten years.

- Things it has to keep doing:
  - DONE survive a phone with no network
  - DONE render markdown without a markdown library
  - DOING stay under a second to first paint on the old iPad
  - TODO a proper offline queue for writes

- Related:: [[link graph]], [[arena sizing]], [[Bajor NAS]]
"""

PAGE_GRAPH = """\
Force-directed view of every `[[link]]` in the journal.

- Nodes are pages, edges are mentions. Double-click opens one.
- Clustered by whatever you actually write about, which turns out to be a
  more honest table of contents than one you would write on purpose.
- The [[LCARS UI]] page has the layout notes.
"""

PAGE_GERMAN = """\
- Unit 12. The vocabulary is fine; the word order is still not.
- `der Termin`, `die Rechnung`, `das Angebot` — the three I keep losing.
- Half an hour before work, not after it. After it never happens.
- Tracking it here because [[link graph]] makes the gaps obvious.
"""

PAGE_NAS = """\
- The box everything is backed up to. Mounts at `/mnt/bajor`.
- Nightly rsync of the journal db, plus the exports.
- This is the reason [[LCARS UI]] has to work with no network: the NAS is
  frequently the only thing on the other end.
"""


# ------------------------------------------------------- the generated rest
# Pools, not templates: a fixture that repeats reads as a fixture the moment
# two rows land on screen together.
PERSONAL = [
    "- Walked to the market before it got hot. Bought too many tomatoes.\n"
    "- Read a chapter of the [[Reading list]] book on the bench by the canal.\n"
    "- DONE call the plumber\n",

    "- Long call with M about the move. Nothing decided, which is fine.\n"
    "- TODO actually look at flights\n"
    "- The [[German course]] homework is two units behind now.\n",

    "- Quiet day. Cooked, read, did not open the laptop until four.\n"
    "- Finished the essay collection — the middle third is the good part.\n"
    "- notes:: rest\n",

    "- Cycled the long way home along the river. 24km, legs fine.\n"
    "- Stopped at the hardware shop for the shelf brackets I keep forgetting.\n"
    "- DOING the shelf\n",

    "- Rain all afternoon, so: [[German course]] unit 9 and a pot of coffee.\n"
    "- The listening exercises are getting easier. The speaking is not.\n",

    "- Dinner at the place with the bad lighting and the very good bread.\n"
    "- Talked about [[LCARS UI]] for far too long. They were polite about it.\n",

    "- Cleared the desk properly for the first time in a month.\n"
    "- TODO put the cables in the box\n"
    "- Found the notebook I thought I had lost in April.\n",

    "- Swim in the morning, 40 lengths. Slow but the whole way.\n"
    "- Spent the evening on [[Bajor NAS]] — the nightly sync had been\n"
    "  failing quietly since Tuesday.\n",
]

ARCHITECT = [
    "- Moved the search off the server. It is 2k rows; the client can do it.\n"
    "- `filter()` over the whole set is under 4ms, which is faster than the\n"
    "  round trip was.\n"
    "- See [[LCARS UI]].\n",

    "- The sync loop was doing a full sweep on every keystroke. Now it is\n"
    "  debounced at 250ms and the fan stopped.\n"
    "- DONE debounce\n"
    "- TODO the same treatment for the [[link graph]] relayout\n",

    "- Read the SQLite WAL docs again. The journal is one writer, so none of\n"
    "  the interesting parts apply, which is the good outcome.\n"
    "- Backups go to [[Bajor NAS]] nightly.\n",

    "- Spent an hour on a bug that was a timezone. It is always a timezone.\n"
    "- Everything stored UTC, rendered local, and the boundary is now in one\n"
    "  function instead of nine.\n"
    "- DONE `isoDay()` is the only place that knows\n",

    "- Split the render path: the list builds from a metadata sweep, the\n"
    "  reader fetches the body. First paint dropped by about 600ms.\n"
    "- The [[arena sizing]] note explains the page splitting underneath it.\n",

    "- Tried three markdown libraries, kept none of them. The subset that\n"
    "  this journal actually writes is about 200 lines of `mdRender`.\n"
    "- DOING fold/unfold on nested lists\n",

    "- The service worker was serving a stale shell after every deploy.\n"
    "  Versioned cache name, skipWaiting, done.\n"
    "- TODO a visible 'new version, reload' pill instead of the silent swap\n",

    "- Profiled the [[link graph]] on the phone. 35 pages is fine, 400 is not.\n"
    "- Grid bucketing for the repulsion pass gets 400 back to interactive.\n",
]

IDEAS = [
    "- A heatmap per kind, not just the total. The sleep column would be a\n"
    "  straight line and the [[German course]] one would be embarrassing.\n",
    "- Resurface: open something old at random, once a day. Most of what is\n"
    "  in here I have never read twice.\n",
    "- Let a `[[link]]` carry a date range, so [[German course]] could show\n"
    "  only the weeks I actually did it.\n",
    "- A day page that writes itself: everything logged today, grouped by\n"
    "  kind, links intact. See [[LCARS UI]].\n",
    "- Dictation that understands 'computer, new task' without a wake-word\n"
    "  server. The browser already has the recogniser.\n",
    "- Export a month as one markdown file for the [[Reading list]] archive.\n",
]

TASKS = [
    ("Renew the passport", "- The appointment is the slow part, not the form.\n"
                           "- TODO book the [[Termin]]\n"),
    ("Book the dentist", "- Six months was in March.\n"),
    ("Shelf brackets", "- 4x, 25cm, the dark ones.\n- See [[Bajor NAS]] —\n"
                       "  the shelf is for the drives.\n"),
    ("Back up the old laptop", "- Before the disk gets any louder.\n"
                               "- Target: [[Bajor NAS]]\n"),
    ("German unit 10", "- Vocabulary, then the listening.\n- [[German course]]\n"),
    ("Replace the bike light", "- The rear one. It flickers on bumps.\n"),
    ("Pay the Rechnung", "- Due the 28th.\n- [[German course]] vocabulary,\n"
                         "  unexpectedly practical.\n"),
    ("Tidy the exports folder", "- Four months of them. Keep one a month.\n"),
    ("Read the WAL paper", "- The one from the [[Reading list]].\n"),
    ("Fix the nightly sync alert", "- It fails silently. See [[Bajor NAS]].\n"),
]

SLEEP = [
    "- Woke twice. Back down quickly both times.\n",
    "- Straight through. The blackout blind is doing its job.\n",
    "- Late to bed after the [[LCARS UI]] layout pass. Worth it, probably.\n",
    "- Short but solid. Awake before the alarm.\n",
    "- Broken. Too much coffee after four.\n",
    "- Long one. First proper weekend sleep in a while.\n",
]

READING = """\
- DOING *Seeing Like a State* — slow, worth it
- DONE *The Soul of a New Machine*
- TODO the WAL paper, properly, with a pen
- TODO the Fruchterman-Reingold one again now that [[link graph]] works
"""


# ------------------------------------------------------------------ assembly
def _row(rid, kind, title, content, day, *, done=0, deleted=0,
         vi=0, vf=0.0):
    stamp = day.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": rid, "kind": kind, "title": title, "content": content,
        "content_length": len(content.encode()),
        "value_int": vi, "value_float": vf,
        "done_bool": done, "deleted": deleted,
        "created_at_utc": stamp, "last_modified_at_utc": stamp,
    }


def build():
    """The journal, newest first — the order the list sweep hands back."""
    rnd = random.Random(1701)           # deterministic: two runs cut the same
    rows = []
    rid = IDS.SHOWCASE

    def add(kind, title, content, day, **kw):
        nonlocal rid
        rows.append(_row(rid, kind, title, content, day, **kw))
        rid -= 1

    # --- today, at the top, in the order they will be read ---------------
    add("work_log", "The layout pass, finally", SHOWCASE,
        NOW - datetime.timedelta(hours=2))
    add("page", "LCARS UI", PAGE_LCARS, NOW - datetime.timedelta(hours=5))
    add("work_log", "Sizing the response arena", ARENA,
        NOW - datetime.timedelta(hours=8))

    # --- the pages the graph clusters around -----------------------------
    pages = [
        ("link graph", PAGE_GRAPH, 9),
        ("German course", PAGE_GERMAN, 23),
        ("Bajor NAS", PAGE_NAS, 41),
        ("Reading list", READING, 12),
        ("arena sizing", "- 1MB, halving on 413.\n"
                         "- The why is in [[LCARS UI]].\n", 55),
    ]
    for name, body, age in pages:
        add("page", name, body, NOW - datetime.timedelta(days=age, hours=3))

    # --- the four months behind them -------------------------------------
    # Roughly two or three entries a day, with gaps: a journal with no empty
    # days looks generated, and the heatmap is more interesting with holes.
    for d in range(1, DAYS):
        day = NOW - datetime.timedelta(days=d)
        if rnd.random() < 0.18:                     # a day nothing was written
            continue

        # sleep, most mornings
        if rnd.random() < 0.72:
            hours = round(rnd.uniform(5.4, 8.6), 1)
            add("sleep_log", f"Sleep {day:%m-%d}", rnd.choice(SLEEP),
                day.replace(hour=7, minute=rnd.randint(0, 59)),
                vf=hours, vi=int(hours))

        # the day's log
        if rnd.random() < 0.80:
            add("personal_log", f"Log for {day:%b %d}", rnd.choice(PERSONAL),
                day.replace(hour=rnd.randint(18, 22), minute=rnd.randint(0, 59)))

        # work notes, on weekdays mostly
        if day.weekday() < 5 and rnd.random() < 0.62:
            add("work_log",
                rnd.choice(["Search, client side", "Debounce the sweep",
                            "WAL, again", "A timezone, of course",
                            "Split the render path", "No markdown library",
                            "Stale shell after deploy", "Graph on the phone"]),
                rnd.choice(ARCHITECT),
                day.replace(hour=rnd.randint(10, 17), minute=rnd.randint(0, 59)))

        if rnd.random() < 0.13:
            add("idea", rnd.choice(["Heatmap per kind", "Resurface",
                                    "Dated links", "The day page writes itself",
                                    "Voice without a server", "Month as markdown"]),
                rnd.choice(IDEAS),
                day.replace(hour=rnd.randint(9, 23), minute=rnd.randint(0, 59)))

        if rnd.random() < 0.10:
            title, body = rnd.choice(TASKS)
            add("task", title, body,
                day.replace(hour=rnd.randint(9, 20), minute=rnd.randint(0, 59)),
                done=1 if rnd.random() < 0.45 else 0)

        # the occasional deleted row, so "live + deleted" has something to show
        if rnd.random() < 0.03:
            add("personal_log", f"Log for {day:%b %d}",
                "- started this and thought better of it\n",
                day.replace(hour=23, minute=50), deleted=1)

    # --- a few open tasks guaranteed at the top of the task list ---------
    # Oldest first is how the task view sorts, so these are dated back far
    # enough to lead it, and none of them are done.
    for n, (title, body) in enumerate(TASKS[:5]):
        rows.append(_row(IDS.PINNED_TASK - n, "task", title, body,
                         NOW - datetime.timedelta(days=100 + n * 4)))

    # --- templates, on the end ------------------------------------------
    # Ids below everything else: the picker reads them by kind, and putting
    # them here keeps them out of the top of the list.
    templates = [
        ("Weekly review {week}",
         "kind:: work_log\n\n## Week {week} — {date}\n\n"
         "- what shipped\n  - {cursor}\n- what is stuck\n- next week\n"),
        ("Standup {date}",
         "kind:: personal_log\n\n- yesterday:: \n- today:: {cursor}\n- blocked:: \n"),
        ("Book note",
         "kind:: page\n\n## {cursor}\n\n- author::\n- started::\n"
         "- the argument, in one line::\n\n> \n\n- See [[Reading list]]\n"),
    ]
    for n, (t, c) in enumerate(templates):
        rows.append(_row(IDS.TEMPLATE - n, "template", t, c,
                         NOW - datetime.timedelta(days=60 + n)))

    # The generated block counts down into open space; if it ever grows far
    # enough to reach the hand-placed ids, two rows share one id and the app
    # quietly renders whichever it saw last. Cheaper to catch here.
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids — move the hand-placed block down"

    return rows


ROWS = build()


# ------------------------------------------------------- the public demo's
# demo/static.py serves this journal to anyone (docs/design/demo-static.md):
# build()'s rows and what the reel never needed - readings for the metrics
# and the chart, the deck's place with entries pinned, two pictures. Its own
# ids (below the hand-placed block) and its own random, so build() and the
# reel's cut stay exactly as they were.
READINGS_FROM = 1400            # counts down; the hand-placed block ends at 1486

# The pictures static.py draws (no camera roll in a made-up journal), each
# on the entry its id names: (media id, entry id, file name, what it shows).
MEDIA = [
    (1, IDS.SHOWCASE, "graph-settled.png", "graph"),
    (2, IDS.PAGE_LCARS, "canal-dusk.png", "dusk"),
]


def public():
    rows = build()
    rnd = random.Random(2364)
    rid = READINGS_FROM

    def add(kind, title, content, day, **kw):
        nonlocal rid
        rows.append(_row(rid, kind, title, content, day, **kw))
        rid -= 1

    # a weight most mornings, drifting down with the noise a scale has; a
    # run now and then, longer as the months go: two series worth a chart
    weight = 81.6
    for d in range(DAYS - 1, 0, -1):
        day = NOW - datetime.timedelta(days=d)
        weight += rnd.uniform(-0.32, 0.26)
        if rnd.random() < 0.7:
            w = round(weight, 1)
            add("weight", str(w), "", day.replace(hour=7, minute=rnd.randint(5, 40)), vf=w)
        if rnd.random() < 0.3:
            km = round(rnd.uniform(4.0, 7.0) + (DAYS - d) / DAYS * 4, 1)
            add("run", f"Run {km} km",
                rnd.choice(["- Along the river and back.\n", "- Hills. Slow, on purpose.\n",
                            "- Easy pace, the long loop past the market.\n"]),
                day.replace(hour=18, minute=rnd.randint(0, 59)), vf=km)

    # The deck's place (deck.html, "the place"): entries on the wall and in
    # the hand. Their spots are left to the deck - a pin it cannot find a
    # wall for is stood on the ready room's shelves at boot (rehomeStrayPins),
    # which is where a visitor should find them.
    pinned = [IDS.SHOWCASE, IDS.PAGE_LCARS, IDS.ARENA, IDS.PINNED_TASK, IDS.TEMPLATE,
              IDS.PINNED_TASK - 1, IDS.PAGE_LCARS - 1, IDS.PAGE_LCARS - 2]
    place = {"v": 2, "env": "enterprise",
             "pins": [{"e": e, "p": [0, -40, 0], "q": [0, 0, 0, 1], "s": 1} for e in pinned],
             "hand": [IDS.SHOWCASE, IDS.PINNED_TASK]}
    rows.append(_row(rid, "space", "U.S.S. Enterprise (deck)", json.dumps(place),
                     NOW - datetime.timedelta(days=1)))
    rid -= 1

    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids in the public journal"
    assert min(r["id"] for r in rows if r["id"] <= READINGS_FROM) > 0
    return rows

if __name__ == "__main__":
    from collections import Counter
    print(f"{len(ROWS)} rows, ids {ROWS[-1]['id']}..{ROWS[0]['id']}")
    print(Counter(r["kind"] for r in ROWS).most_common())
    print("days covered:", len({r["created_at_utc"][:10] for r in ROWS}))
