# Kinds, generalized: roles, a mapping, an empty journal

Status: **built**, commits 1-7 of section 8 (0.273.0-0.278.2); the
captain's mapping is set by hand (kinds.local.md).
Supersedes the open-source sweep's row 1b on the child's kinds
(open-source.md: rename the two kinds and migrate the rows). The captain's
decisions, which this design takes as given:

- Kinds are generalized, wider than the child's two: no kind name in the
  code or the docs except as an example.
- A new user's journal starts empty; `personal_log` is its one default kind.
- The captain's instance keeps its kind names. No row of the captain's is
  migrated.
- So: each feature that needs a kind names a **role**, a **mapping** gives
  each role its kind, the roles have plain defaults, and the captain's own
  mapping points the child's roles at the kinds the journal already uses.
- The name LCARS stays.

Words used below. A **kind** is the `entries.kind` text. A **role** is a
feature's need for one ("where the nap chip writes"). A **convention** is a
rule over kind names rather than one name (`*_sleep` is a sleeper). The
**app's own kinds** are those the app writes for itself, not the owner
(views, the deck's ship, the crew's reports).

The captain's personal kind names appear in this file only as "the child's
sleep kind" and "the child's vocabulary kind"; their values are in
`docs/design/kinds.local.md`, which the export leaves out (its name holds
`.local.`). This file passes `scripts/export-public.py --audit-only`.

## 1. The inventory

Counted at 174628b (0.265.0) over `git ls-files`, vendor/ left out: lines
naming the kind, per file. A kind with an underscore is matched as a word;
a one-word kind (`task`, `sleep`, `page`) only when quoted or after
`kind=`, `kind:` or `--kind`, so prose ("a page", "sleep well") is not
counted. Where a count still holds a non-kind use, the "where" column says
so. Files the export already leaves out (CHANGELOG.md, TODO.md, reports/,
lcars-ui/report/, open-source.md, db-filter.sh, the `.local.` files) are
listed apart: they need no change for the release.

### 1.1 The default kind: `personal_log` (139 lines, 26 files)

| Where | Lines | What depends on it |
|---|---|---|
| lcars-ui/index.html | 11 | a new entry's kind (`startNew` ~13991, the filtered new ~14524, the template's ~19285), the calendar's new entry (`CAL_NEW_KIND` 17831), quick capture's fallback (~20658, ~20756), the default template's `kind::` line (19343), the palette's fuzzy "per log" (26606), the kind guess (28347) |
| lcars_chat.h | 2 | the computer's prompt: "a new entry, kind personal_log unless they name one" (357), the CLI example (329) |
| lcars_logseq.h | 1 | a comment (53) |
| scripts/crew_tool.py | 6 | `COUNSEL_KINDS` (719), counsel's week and baseline (841-842), prose kinds for weekstats (668), the start/end hygiene check (932) |
| scripts/lcars_linker.py | 9 | `EDITABLE_KINDS` (51), `is_gym`: a gym session is a personal_log titled "gym" (551-553, 689-690) |
| crew/yeoman-linker.md | 2 | the linker's prompt, an example |
| lcars-ui/demo/fixture.py, demo/static.js | 3, 1 | the demo's rows and its new entry |
| tests: tests.js 33, test_crew.py 32, editor.py 7, test_linker.py 7, shots.py 4, keyboard.py 2, offline.py 2, qa_chat.py 2, buttons.py 1, e2e.py 1, perf.py 1 | 92 | fixtures and new-entry checks |
| docs: editor.md 1, REFACTORING.md 1 | 2 | prose |
| left out: TODO.md 3, CHANGELOG.md 2, context.local.md 1, the two reports 4 | 10 | |

### 1.2 The seed and the work log (99 lines, 35 files)

A work-log kind (its name the captain's own: kinds.local.md), and today **the seed**: `DEFAULT_ENTRY_KIND` in
lcars_db.h:42 is what an empty journal's one row ("Captain Log") gets.

| Where | Lines | What depends on it |
|---|---|---|
| lcars_db.h | 2 | the seed (42, 239) |
| lcars_cli.c | 1 | a usage example (9) |
| lcars-ui/index.html | 5 | the outbox's fallback kind for a row with none (`obCreateBody` 7598), read-aloud says the date before a work-log row (29822), palette examples (16765, 26608, 26651) |
| lcars-ui/deck.html | 1 | the demo's made-up rows (612) |
| shortcuts/generate.py, README.md | 2, 2 | "LCARS Log" and "LCARS Share" post this kind (531, 534) |
| evenhub/lcars-glasses/src (config.ts 2, main.ts 2, settings.ts 1), index.html 1 | 6 | the glasses' default list kind and "Log now" |
| scripts/crew_tool.py, lcars_linker.py | 1, 1 | prose kinds (668), `EDITABLE_KINDS` |
| crew/yeoman-linker.md | 1 | an example |
| .github/workflows/c-cpp.yml | 1 | CI greps the seed row out of `/entries?limit=1` |
| lcars-ui/demo/fixture.py | 4 | demo rows and a template |
| tests: tests.js 21, api.py 9 (the seed), db_swap.py 9, shots.py 6, buttons.py 4, deckboot.js 2, config.py 1, keyboard.py 1, perf.py 1 | 54 | fixtures; api.py checks the seed |
| docs: ARCHITECTURE.md 3, CLAUDE.md 1, open-source-build.md 1, REFACTORING.md 1 | 6 | the seed, examples |
| left out: CHANGELOG.md 5, TODO.md 1, db-filter.sh 1, the shortcuts 2, the reports 3 | 12 | |

### 1.3 Tasks: `task` (128 lines, 34 files) and `task_*` (213 lines, 29 files)

`task` is CalDAV's root list and every `task_<list>` is a Reminders list.
Many `task`/`task_*` hits are the engineers' queue, whose "task" is a word,
not a kind: scripts/engineer.py 14+18, test_queue.py 15+25, test_seat.py 2,
crew.py 3, test_engineer_model.py 1. The kind uses:

| Where | Lines | What depends on it |
|---|---|---|
| lcars_caldav.h | 2 + 8 | `CALDAV_DEFAULT_KIND "task"` (79), overridable today by `$LCARS_TASK_KIND` (`caldav_task_kind`, 180): the root list and its `<kind>_<list>` sub-lists, MKCALENDAR's new kinds |
| lcars_logins.h, lcars_http.h | 8, 2+2 | a limited login owns `task_<owner>` and `task_<owner>_*` (`LimitedOwnsKind`, 136) - hard-coded `task_`, not the task role |
| lcars_chat.h | 1 + 2 | the computer's prompt: new task = kind task, or `task_<list>` (361-363) |
| lcars_cli.c | 1 | a usage example (11) |
| lcars-ui/index.html | 14 + 21 | the Task button (`data-fd="task"` 4476, `fdGo` 21726-21733), `cdavKind` learnt from the server (13300), `crewWritten` (`task_crew`, `task_no1`, 9490), Number One's questions (`task_no1`, 39548), the todo chip (12546) |
| lcars-ui/deck.html | 1 + 3 | Number One's questions (`task_no1`, 557, 1518), demo rows (612) |
| shortcuts/generate.py, README.md | 2, 2 | "Open tasks" asks `?kind=task&done=0` (387) |
| evenhub glasses config.ts, main.ts | 1, 1 | "New task" |
| scripts: crew_tool.py 1+7 (`URGENT_KIND "task_crew"` 73, `is_captains` 325, hygiene 919), crew_notes.py 1 (`NOT_FROM` 68), no1.py 1+4, db-merge-window.py 2 | 16 | the crew's and Number One's reminder kinds |
| lcars-ui/demo/fixture.py | 2 | demo tasks |
| tests: tests.js 18+22, editor.py 8, qa_chat.py 6, caldav.py 3+9 (`task_personal`, `task_groceries`), logins.py 2+9, test_crew.py 5+9, test_crew_notes.py 1+8, api.js 4+2, db_swap.py 3, keyboard.py 2, shots.py 2, others 1 each | ~120 | |
| docs: ARCHITECTURE.md 4+19, chat.md 3, crew-notes.md 2, chat-dock.md 1, chat-refactor.md 1 | 30 | |

### 1.4 The crew's and Number One's kinds: `crew_*` (491 lines, 50 files), `no1_*` (117 lines, 24 files)

The limited logins' namespaces (`LimitedOwnsKind`: `<owner>_*`), plus
`task_crew` and `task_no1` above. Names in use: `crew_<role>` for each
scheduled role (`crew_yeoman`, `crew_ops`, `crew_historian`,
`crew_science`, `crew_security`, `crew_librarian`, `crew_ship`, `crew_qa`,
`crew_counselor`: index.html 37955, deck.html 10470, crew_tool.py 1623),
`crew_note` and `crew_note_names` (crew_notes.py 64, 245; index.html
38592, 38653), `crew_seat` and `crew_inbox` (seat.py; engineer.py;
db-prune.py, lcars-prune.service/timer; db-merge-window.py),
`crew_shares` and `crew_share_<id>` (shares.py; index.html 17232),
`no1_log` and `no1_report` (no1.py, engineer.py, lcars_logins.h).

Where: index.html 47+6, tests.js 66+4, crew_tool.py 24+2, crew.py 23+1,
test_crew.py 24+4, test_crew_notes.py 23+6, test_prune.py 18+1,
engineer.py 17+33, logins.py 15+6, seat.py 9, crew_notes.py 8+1,
shares.py 8, test_shares.py 8, no1.py 3+7, test_db_merge_window.py 5+7,
deck.html 5, the units 6, lcars_logins.h 3+2, lcars_http.h 1+1, and the
docs (ARCHITECTURE.md 36+9, crew-notes.md 12+3, sweep-ops.md 11+5,
CLAUDE.md 6+2, shares.md 2, chat.md 1, sweep-c.md 1).

**These are the app's own, not the owner's**: a role here would let a
mapping hand a login another login's rows. They stay fixed (§2.3).

### 1.5 Readings and metrics

`GET /metrics` (lcars_metrics.h) and the page's readings (`reading()`,
`measureSeries()`, the chips) are **kind-agnostic**: a reading is any live
row with a non-zero number, keyed by its kind, whatever it is called.
test/metrics.py uses made-up kinds (`coffee` 8, `sleep` 8, `vocab` 4,
`journal` 4). Nothing to do but keep it so.

What feeds the readings by name is the hourly linker (`lcars_linker.py
measure`): `MEASURE_KINDS` gives `sleep`, the child's sleep kind and `drive`
a value from their start/end pairs (533-535), `COUNTED_KINDS` the child's
vocabulary kind a running count (538), and `is_gym` gym minutes on
personal_log rows. And crew_tool.py's `weekstats` (673-685) and the
stats view (below) read the same kinds.

| Kind | Lines, files | Where (code) |
|---|---|---|
| `sleep` | 80, 21 | crew_tool.py 7 (`NOT_WRITING` 330, skip lists 568, weekstats 616/673, counsel 844, hygiene 928), lcars_linker.py 2, crew.py 3 (a word in prose), crew_notes.py 1, index.html 4 (1 kind: none by name - `statSleep` takes `(^|_)sleep$`; the rest a map category, 35957); tests 50; the sleep word in engineer.py/test_reap.py/test_queue.py/test_seat.py/test_no1.py/test_engineer_model.py is `time.sleep` arguments, not a kind |
| `drive` | 41, 11 | index.html 3 (day map 11091; `statDrives` takes `(^|_)(drive|drives|trip|trips)$`), crew_tool.py 7 (trip retro's legs 1228, skip lists), lcars_linker.py 1, crew/science.md 1, yeoman-linker.md 2; tests 25 |
| `counter` | 20, 6 | index.html 1 (`COUNTER_KIND` 8953: "log a diaper", the counters' stats), crew_tool.py 2 (weekstats 685); tests 15 |
| `gym` | 55, 10 | not a kind: personal_log rows titled "gym" (`GYM_RE`), and a deck room's name (deck.html 7443) |
| `workout` | 14, 7 | lcars_strava.h 2 (`STRAVA_KIND` 69: the Strava pull's rows), lcars_cli.c (2019), crew_tool.py 1, lcars-strava.service 1, test/strava.py 4, test_linker.py 1, ARCHITECTURE.md 4 |
| the child's sleep kind | 61, 14 | index.html 8 (`NAP_KIND` 8831: the nap chip `napOffer`/`napTake`, the voice order "log … nap" 27345, its help 27347, its toasts; `NAP_RE` 8834 also matches the child's *first name* in a sentence), crew_tool.py 4 (`NOT_WRITING`, weekstats 673, hygiene 928), lcars_linker.py 3 (`MEASURE_KINDS`), crew_notes.py 1 (a docstring); tests: tests.js 17, test_crew_notes.py 7, test_linker.py 6, test_crew.py 4; ARCHITECTURE.md 2; left out: TODO.md 3, CHANGELOG.md 2, context.local.md 2, a report 1, open-source.md 1 |
| the child's vocabulary kind | 18, 8 | index.html 1 (a comment: `statVocab` takes any kind holding `vocab`, 15860), crew_tool.py 4 (weekstats' new words and running total 679-705), lcars_linker.py 1 (`COUNTED_KINDS`); tests: test_crew.py 4, tests.js 3; left out: TODO.md 2, context.local.md 2, open-source.md 1 |

So the stats view already works by convention, not by name: sleepers are
`(^|_)sleep$` (index.html 15734), drives `(^|_)(drive|drives|trip|trips)$`
(15824), vocabularies any kind with `vocab` in it (15860). A new user who
names a kind `sleep` or `kid_vocab` gets the view with no mapping at all.

### 1.6 Strava: `workout`

In 1.5. One define, `STRAVA_KIND` (lcars_strava.h:69), used by the pull
(894, 1088) and by the CLI's `strava` (lcars_cli.c:2019).

### 1.7 Shares: `share`, `crew_shares`, `crew_share_<id>`

`share` (32 lines, 9 files): the captain's one entry per place a blog post
was shared (shares.py 4, index.html 8 of which `SHARE_KIND` 17231 is the
kind and the rest the word "share" in a chart's buttons, crew/shares.md 1,
docs/design/shares.md 2, ARCHITECTURE.md 4; tests 11). The two `crew_`
kinds are the shares role's output (1.4).

### 1.8 Imports, pages and the linker

| Kind | Lines, files | Where (code) |
|---|---|---|
| `logseq_journal` | 44, 17 | lcars_logseq.h 2 (`LOGSEQ_JOURNAL_KIND` 54: the import's journals, the CLI's `--kind` default 1542), lcars_logins.h 1 (`StewardMayWriteKind`'s frozen list 150), crew_tool.py 2 (`IMPORTED_KINDS` 78, `COUNSEL_KINDS`), crew.py 1 (the prompt's never-write list 298), index.html 2 (the crew notes' never-write prompt 38337), lcars_linker.py 1, crew/counselor.md 1, crew/yeoman.md 1; tests 24 |
| `capacities_journal` | 12, 10 | the same frozen lists: lcars_logins.h 1, crew_tool.py 2, crew.py 1, index.html 1, lcars_linker.py 1; crew/counselor.md 1, crew/yeoman.md 1 (no importer in the tree: rows from a past import) |
| `noteplan_journal` | 11, 8 | the same lists: lcars_logins.h 1, crew_tool.py 1, crew.py 1, index.html 1 (also no importer) |
| `page` | 54, 23 | lcars_logseq.h 1 (`LOGSEQ_PAGE_KIND` 55), index.html 7 (`PAGE_KIND` 14326: wiki links, the `[[…]]` template, `STAR_KIND_STOP`), lcars_linker.py 4 (`TARGET_KINDS` 46, `EDITABLE_KINDS`), crew_tool.py 2; the rest is the word ("the page") in tests and prose |
| `person`, `project` | 20/12, 6/4 | lcars_linker.py (`TARGET_KINDS`, `EDITABLE_KINDS`), crew_tool.py (skip lists), index.html 3 (`statPeople`'s `person` rows, 15526), crew.py 1 |
| `meeting` | 3, 3 | lcars_linker.py (`EDITABLE_KINDS`), crew_tool.py (prose kinds), deck.html (demo rows) |
| `bookmark` | 2, 2 | crew_tool.py (skip list 568), shares.py 1 (a word) |
| `template` | 15, 8 | index.html 6 (`TEMPLATE_KIND` 19209: the template picker; 3 are `createElement("template")`), crew_tool.py 2 (skip lists), demo build.sh/demo.py/fixture.py 3, shots.py 2 |

### 1.9 The app's own storage

| Kind | Lines, files | What |
|---|---|---|
| `settings` | 27, 11 | the views and pins entry (`VIEWS_KIND` index.html 20826), the brief's home place (`home_place`, crew_tool.py 353); crew_tool skips it in the counts; the glasses' and deck's "settings" hits are words |
| `space` | 23, 6 | the deck's ship (deck.html 13: 667, 737, …), skipped by the courses (`CRS_NOT_JOURNAL` index.html 36774); the demo |
| `holo_program` | 11, 5 | the deck's holodeck programmes (deck.html 7), `CRS_NOT_JOURNAL` |
| `trip` | 52, 12 | the courses (`CRS_KIND` index.html 34287, 13106, the day map 11222-11231), crew_tool.py 13 (`agenda`'s weather place 458, `trip` retros 1308-1323, skip lists), crew/historian.md 2, crew.py 1; tests 17. The owner's, not the app's: in 2.1 |

### 1.10 The personal ones

The child's two kinds (1.5) are the only kinds about the captain's family
the tracked code names. Kinds in the captain's journal that no code names
(one about another person's sleep, one about the child's naps, a cooking
log, a pantry, journals of other apps) need nothing: the design has to
leave them alone, and does. Two **names** in the code that are not kinds
ride along, because the same commits touch them: the child's first name in
`NAP_RE` and in the nap chip's words (index.html, 18 of its 25 audit lines),
and test fixtures and an ARCHITECTURE.md paragraph that say it (§6).

## 2. The roles

A role is a short slug, one per need. Its default is what a new instance
uses until the owner says otherwise.

### 2.1 Roles with a mapping

| Role | Default kind | The features that use it |
|---|---|---|
| `log` | `personal_log` | a new entry's kind, the calendar's new entry, quick capture, the default template, the outbox's fallback, the computer's "new entry", the shortcuts' Log and Share, the glasses' Log now, counsel's week, the linker's editable and gym rows |
| `work_log` | `work_log` | read-aloud's date before the entry (29822), the linker's editable kinds, crew_tool's prose kinds. Only where a second log is treated as the first is |
| `task` | `task` | CalDAV's root list and its `<task>_<list>` lists, the Task button, the computer's "new task", the shortcuts' open tasks, the glasses' New task; the limited logins' reminders are `<task>_<owner>` (2.3) |
| `sleep` | `sleep` | the linker's hours, weekstats, counsel's nights |
| `child_sleep` | `child_sleep` | the nap chip and its voice order, the linker's hours, weekstats |
| `child_vocab` | `child_vocab` | the linker's running count, weekstats' new words |
| `drive` | `drive` | the day map's drives, the linker's minutes, weekstats, the trip retro's legs |
| `trip` | `trip` | the courses, the agenda's weather place, the historian's retros |
| `workout` | `workout` | the Strava pull |
| `counter` | `counter` | "log a diaper", the counters' stats, weekstats |
| `share` | `share` | the shares role's places |
| `page` | `page` | the Logseq import's pages, wiki links, the linker's targets |
| `person` | `person` | the linker's targets, the stats' people |
| `project` | `project` | the linker's targets |
| `meeting` | `meeting` | the linker's editable kinds, crew_tool's prose kinds |
| `template` | `template` | the template picker |
| `logseq_journal` | `logseq_journal` | the Logseq import's journals (the CLI's `--kind` still wins) |
| `imported` | `[logseq_journal]`, a list | the kinds nobody but an import writes: the steward's refusal, the crew's never-write lists, crew_tool's skips |

Each role also takes an optional **name**, the words a feature says for it.
Only `child_sleep` uses one today: the nap chip says "<name>'s nap", and
`NAP_RE` matches "<name> slept 13:35-14:39" as well as "nap from 13:35 to
14:39". With no name the chip says "the nap" and only the second form
matches. (`child_vocab`'s name is free for the stats' heading.)

### 2.2 Conventions, kept

These are rules over names, not names, and stay as they are, documented in
ARCHITECTURE.md beside the roles:

- `(^|_)sleep$` is a sleeper in the stats view, so a second sleeper kind
  (another person's, the child's) shows with no role of its own;
- `(^|_)(drive|drives|trip|trips)$` are drives there; a kind holding
  `vocab` is a vocabulary; `log|journal|meeting` kinds are prose for the
  echoes (ARCHITECTURE.md ~1035);
- a personal_log (the `log` role's kind) titled "gym" is a gym session.

The stats' conventions now also take the roles' kinds, so an owner who maps
`child_sleep` to `nap_times` still gets the sleeper.

### 2.3 The app's own kinds, fixed

Not roles, by design: `settings` (it holds the mapping, so it cannot be
mapped), `space`, `holo_program`, and the logins' namespaces `crew_*`,
`no1_*` with `crew_note`, `crew_note_names`, `crew_seat`, `crew_inbox`,
`crew_shares`, `crew_share_<id>`, `no1_log`, `no1_report`. A mapping that
could rename a login's kinds could also hand it the owner's rows; and
these are the app's protocol, as a table name is, not the owner's words.
They are named in the code as the one place each is defined (a `const`,
a `#define`, a module constant), which the release's rule allows as
"the app's own" - **a choice for the captain** (§8, B).

The logins' reminders follow the task role: `<task>_crew`, `<task>_no1`.
With the default `task`, that is today's `task_crew` and `task_no1`
exactly. `LimitedOwnsKind` reads the role instead of `"task_"`.

## 3. The mapping's home

### 3.1 The three candidates

| | A. A `settings` entry in the journal | B. `lcars.env` keys | C. A file in the data dir |
|---|---|---|---|
| Shape | one entry, kind `settings`, title `kinds`, content `{"v":1,"roles":{"child_sleep":{"kind":"…","name":"…"},…}}` - the views entry's pattern (index.html 20812) | `LCARS_KIND_<ROLE>=…`, 18 keys; `LCARS_TASK_KIND` is one today | `DATA/kinds.json` |
| The server | one `SELECT` on the entries it already owns, when a route needs a role | `getenv` at start | read and parse a file |
| The UI | arrives with the rows every boot fetches, and offline in the mirror | needs a route; read-only | needs a route |
| Edited from the UI | yes: a route writes the entry; the editor can too | no: a restart, a shell | only through a new write route |
| The crew, the CLI | the API they already use | the API (they do not share the server's env) | the API |
| Follows the journal | yes: a copy, a backup, `db-swap`'s personal copy, `db-push`/`pull` | no: per box | no: per data dir |
| CLAUDE.md's rule ("state … lives in the journal") | kept | broken | broken |

### 3.2 Recommendation: A, a `settings` entry, read through one route

- **One place for the defaults and the reading: the server.** A new module,
  `lcars_kinds.h` (the route modules' shape), holds the role table (slug,
  default, what it is for), `KindFor(db, role, out, size)` for the C code,
  and `GET /kinds/roles`: every role with its kind, its default, whether
  the owner set it, its name, and its live row count -
  `{"roles":[{"role":"child_sleep","kind":"child_sleep","default":"child_sleep","set":false,"name":"","rows":0},…],"entry":<id or null>,"error":""}`.
  `error` says when the entry is not JSON the server can read (then every
  role is its default, and the Config page says so).
- **Writing: `PUT /kinds/roles`**, the owner's login only, a body of roles
  to set (`{"child_sleep":{"kind":"…","name":"…"}}`, `null` back to the
  default). It checks a kind is a slug (`[a-z0-9_]`, ≤127 bytes, not one
  of 2.3's), then writes the entry (creates it, the lowest id wins as with
  views). Editing the entry by hand still works: it is read on every use.
  The limited logins may not write a `settings` entry titled `kinds`
  (`StewardMayWriteKind` and `LimitedAllowed` refuse it), so no crew role
  can redirect the nap chip.
- **The C server** reads the role where it needs it, never at start: the
  CalDAV task kind (`caldav_task_kind` today caches `$LCARS_TASK_KIND` per
  thread; it becomes `KindFor`, with `$LCARS_TASK_KIND`, when set, still
  winning, so a box that set it keeps working), the Strava pull's kind,
  the computer's prompt (the `log` and `task` kinds filled in), the logins'
  `<task>_<owner>` and the import list. One `SELECT … WHERE kind='settings'
  AND title='kinds' AND deleted=0 ORDER BY id LIMIT 1`; entries has no index
  on kind, but these routes are rare (a CalDAV sync, a pull, a chat turn)
  and the scan is ~6000 rows. No cache, so a change applies on the next
  request.
- **The UI** asks `GET /kinds/roles` once a boot, beside `/features`, keeps
  the answer in localStorage (it paints before the answer lands, and
  offline), and reads `kindOf("child_sleep")` wherever a literal is today.
  Before any answer it uses the table's defaults (a copy of the C table in
  the page; the behaviour suite checks the two agree, the way it checks
  `noteScan` against crew_notes.py).
- **The crew scripts** (crew_tool.py, lcars_linker.py, crew_notes.py,
  crew.py, shares.py) ask once a run, through the lcars-cli they already
  call: `lcars-cli roles --json`. crew.py writes the kinds into the
  prompts' blocks (the never-write list, "the log kind") instead of names
  in crew/*.md.
- **The CLI**: `lcars-cli roles` (the table), `lcars-cli roles set ROLE
  KIND [--name N]`, `lcars-cli roles reset ROLE`; `logseq import` and
  `strava` ask the server for their role's kind instead of the defines.
- **Config** (`openCfg`, index.html 21499) gets a **Kinds** section: one row
  a role, "child's sleep → [kind ▾] 0 rows", the select offering the
  journal's kinds (`GET /kinds`) and a new one; a set role marked, Reset
  beside it; the change shown in the row at once, "saving…", then the
  server's answer (the standing feedback rule). A voice order, "set the
  child's sleep kind to …", and a palette row "kinds" open it; the KEYS
  check needs no key for a dialog section.

## 4. The seed

**A fresh journal holds nothing.** `InitDB` stops planting "Captain Log"
(lcars_db.h:225-245 and `DEFAULT_ENTRY_KIND` go); the `log` role's default,
`personal_log`, is the kind the first entry gets. No `settings` entry is
made either: every role is its default until the owner sets one.

How each page behaves with no entries of a role's kind:

| View | With none | Change needed |
|---|---|---|
| the list, the calendar, the day view, search | the empty journal's own empty state | a QuickJS case on an empty fake API (today the suite always has rows) |
| the new entry, quick capture, templates | `personal_log`; the template picker shows the built-in one (19343) | none |
| the nap chip | offered only when a sentence tells of a nap; it writes `child_sleep`, which then exists | the words from the role's name, "the nap" without one |
| the vocabulary, sleep, drive, people and counter stats | sections drawn only with data (`x.vocab.length ? …`, a sleeper needs three nights) | none; checked by the empty case |
| the readings' chips | wait for two readings of a kind | none |
| the courses, the day map | no `trip` rows: nothing to draw | to check in the empty case |
| CalDAV | the root list published empty; Reminders' new list makes `task_<name>` | none (test/caldav.py starts empty already) |
| the deck | its rooms come from the kinds present | to check: `deckboot.js` with no rows |
| the crew | weekstats, counsel print zero for a role with no rows | test_crew.py cases with no rows |

## 5. The captain's instance

- **The mapping** lives in the captain's journal, as the one `settings`
  entry titled `kinds`. The values to set (the child's two roles, the work
  log, the import list, the child's name) are in
  `docs/design/kinds.local.md`, the one tracked place that names them;
  the export drops it by its name. Not in this file, not in lcars.env.
- **When it is set**: after commit 1 is deployed (the route exists, nothing
  reads it yet) and before commit 4 (the page reads it). Commands in
  kinds.local.md; one `PUT /kinds/roles`, the owner's login.
- **The proof nothing changes**:
  1. No migration: no commit holds an `UPDATE entries SET kind` or a script
     that renames; the review checks the diff for one.
  2. The same kinds in the rows: before and after the deploys,
     `SELECT kind, count(*) FROM entries GROUP BY kind` on a read-only open
     of the live journal is the same but for the one new `settings` row.
  3. The same views: `test/kinds.py --mapping FILE --db COPY` (generic; the
     mapping given at run time, so nothing personal ships) over a scratch
     copy of the journal with the mapping of kinds.local.md: every mapped
     role's kind has rows, `GET /kinds/roles` names them, and the behaviour
     suite's nap, stats and weekstats cases pass with that mapping as they
     do with the defaults (`LCARS_TEST_DB` is already a copy of the
     journal).
  4. What the captain sees: the nap chip's words and voice order with the
     child's name (the role's name), the stats as today (the conventions
     still match the captain's second sleeper kind), Reminders' lists unchanged
     (`task` stays the task kind).
- The seed change does not touch the captain: a journal with rows was
  never seeded again (lcars_db.h:224), and the captain's has rows.

## 6. The audit

`scripts/export-public.py --audit-only` at 174628b: 102 lines hit in 10
files. The child's-name rule has 101 of them in 9 files; this design
removes all 101:

| File | Hits | Removed by |
|---|---|---|
| lcars-ui/index.html | 25 | `NAP_KIND` → `kindOf("child_sleep")`, `NAP_RE` and the chip's words from the role's name, the comments and the voice order's phrase ("log the nap …"), the palette example (commit 4) |
| lcars-ui/test/tests.js | 34 | fixtures on `child_sleep`/`child_vocab` and a made-up name (commit 4) |
| scripts/test_crew.py | 12 | fixtures, a made-up name (commit 5) |
| scripts/test_crew_notes.py | 8 | fixtures (commit 5) |
| scripts/crew_tool.py | 7 | the roles (commit 5) |
| scripts/test_linker.py | 6 | fixtures (commit 5) |
| scripts/lcars_linker.py | 4 | `MEASURE_KINDS`/`COUNTED_KINDS` from the roles; the comments' ids kept, the name out (commit 5) |
| ARCHITECTURE.md | 4 | the nap paragraph (1735-1739) by role, and 2581's example (commit 7) |
| scripts/crew_notes.py | 1 | the docstring's example (commit 5) |

What stays: **the NAS's name**, lcars_media.h:107 (`MEDIA_DEFAULT_ROOT`),
which open-source-build.md step 7 removes, not this. The kind names left in
the shipped tree are the defaults (each once, in the role table, C and its
page copy), the app's own kinds (2.3), and examples in tests, the demo and
the docs - which the audit does not flag and the release's rule allows.

## 7. What else is touched

- **Tests**: new `test/kinds.py` (~40s, a scratch server): the route's
  answer on an empty journal, `PUT` and its refusals (a bad slug, a 2.3
  kind, a limited login, the steward), a hand-broken entry falling back
  with `error`, CalDAV and the Strava pull following a set role,
  `$LCARS_TASK_KIND` still winning, and no seed row. `test/api.py`'s seed
  check inverted (an empty journal stays empty). tests.js: the empty
  journal case, `kindOf` with a set mapping moving the nap chip's writes,
  the page's table equal to the C table. test_crew.py, test_crew_notes.py,
  test_linker.py: fixtures on the defaults, one run per script with a set
  mapping. `test/logins.py`: the `kinds` entry refused to every limited
  login. deckboot.js: no rows. CI (`c-cpp.yml`): `/health` and
  `/kinds/roles` instead of the seed row.
- **The demo**: `demo/fixture.py` keeps its example kinds but its
  work-log rows become `work_log`; `demo/static.js` answers
  `GET /kinds/roles` with the defaults. test/demo_static.py run.
- **The shortcuts**: generate.py takes `--kind` (default `personal_log`)
  for Log and Share, and the open tasks read the task role; README.md says
  so. The captain's signed files are out of the export and rebuilt with
  the captain's kind.
- **The glasses**: config.ts's defaults become `personal_log` and `task`,
  and read `/kinds/roles` when the server has it.
- **db-filter.sh**: its `KINDS` (the work log and its task list)
  is the captain's filter and is excluded from the export already; no
  change.
- **Docs**: ARCHITECTURE.md gets a "Kinds" section (the roles, the
  conventions, the app's own kinds, the mapping and its route) and the
  route in its table, and loses the seed and the nap paragraph's names;
  CLAUDE.md lists test/kinds.py and corrects api.py's line; open-source.md
  row 1b points here (done in this commit); crew/*.md say "the log kind"
  and take the never-write list from crew.py; open-source-build.md's seed
  line.

## 8. The commits, in order

Each builds clean and passes its tests on its own, and each bumps the
version (CHANGELOG.md, `APP_VERSION`).

| # | Commit | Size | Tests |
|---|---|---|---|
| 1 | `lcars_kinds.h`: the role table, `KindFor`, `GET`/`PUT /kinds/roles`, the `kinds` entry refused to the limited logins; the empty seed; CI (minor) | ~350 lines C, ~200 test | test/kinds.py (new), api.py, logins.py, config.py |
| 2 | The server's kinds from the roles: CalDAV's task kind (`$LCARS_TASK_KIND` still wins), the logins' `<task>_<owner>` and import list, the Strava pull, the computer's prompt (patch) | ~120 C | caldav.py, logins.py, strava.py, chat_media.py |
| 3 | `lcars-cli roles` (list, set, reset, `--json`); logseq import and strava ask for their role (minor) | ~180 C | onebin.py, strava.py, kinds.py |
| — | **Deploy 1-3; the captain's mapping set** (kinds.local.md) | | |
| 4 | The page from the roles: `kindOf`, the literals of 1.1-1.9 replaced, the nap chip's name, Config's Kinds section with its voice order and palette row, the empty journal (minor) | ~250 lines index.html, ~300 tests.js | full run.sh with perf, buttons.py, keyboard.py, editor.py, offline.py |
| 5 | The crew from the roles: crew_tool.py, lcars_linker.py, crew_notes.py, crew.py's blocks, crew/*.md (minor) | ~200 py, ~150 md, ~250 tests | test_crew.py, test_crew_notes.py, test_linker.py, test_shares.py |
| 6 | The shortcuts' `--kind`, the glasses' defaults, the demo's fixture and `/kinds/roles` (patch) | ~80 | demo_static.py, deckboot.js |
| 7 | ARCHITECTURE.md's Kinds section, CLAUDE.md, open-source-build.md; the audit's 101 hits checked gone (`--audit-only`) (patch) | ~150 md | `export-public.py --audit-only` |

About 1-1.5 engineer-hours of builds and tests in all; commit 4 is the
largest and the only one the perf budget measures.

### Choices for the captain

| | Choice | Recommendation |
|---|---|---|
| A | The mapping's home: a journal `settings` entry, lcars.env, or a file | **the journal entry**, read and written through `/kinds/roles` (3.2) |
| B | The app's own kinds (`settings`, `space`, `holo_program`, `crew_*`, `no1_*`): fixed, or roles too | **fixed**: they are protocol, and mapping a login's kinds could hand it the owner's rows |
| C | The fresh journal: empty, or one welcome `personal_log` row | **empty**, as decided; the empty states are tested instead |
| D | `$LCARS_TASK_KIND`: keep as an override of the task role, or drop it | **keep**, documented as deprecated; it costs four lines |
| E | The stats' name conventions (`*_sleep`, `vocab`, `drive|trip`): keep beside the roles, or roles only | **keep**: they show the captain's second sleeper kind with no role, and a new user's own names with no mapping |
| F | `work_log` as a role (read-aloud's date, the linker's editable kinds) or folded into `log` | **a role**: an existing work-log kind keeps its behaviour by one line in the mapping |
| G | The child's name: the role's `name` in the mapping, or a separate `LCARS_CHILD` | **the role's name**: one place, edited in Config with the kind |
