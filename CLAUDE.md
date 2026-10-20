# CLAUDE.md — agent quickstart for lcars

LCARS is a Star Trek-style personal journal: one SQLite file, an HTTP API
server written in C11, and the web console (`lcars-ui/index.html`) and the 3D
deck (`lcars-ui/deck.html`) that the server serves, plus `lcars-cli`, a
terminal client of the API. Single user (the journal's owner), on a box of
their own. (The raylib desktop app was removed in 0.175.0; ARCHITECTURE.md,
"Builds", says how to bring it back.)
Code style is in @AGENTS.md; the system map, and the why behind it, in
@ARCHITECTURE.md.

## Build & verify

```sh
make check            # fastest full-warning compile of the server (nothing written)
make lcars            # debug server + ASan
make SANITIZE=0 lcars # same without AddressSanitizer
make lcars-release    # -O3 server
make lcars-cli        # terminal client + Logseq bridge (libcurl only)
make lcars-one        # the server with the CLI in it: lcars-one cli ARGS, or named lcars-cli
make ui-pack          # build/ui.pack: the shipped lcars-ui/ in one blob (scripts/ui-pack.py)
make lcars-embed      # lcars-one with that blob in it: /ui/ with no lcars-ui/ beside it
make lcars-static     # the release binary: lcars-embed, -static, musl - in Alpine/CI only
./lcars --port 8080   # serve ./lcars.db (--http-only is accepted, and ignored)
./lcars init DIR      # a data directory: lcars.env, media/, a journal (lcars --data DIR)
./lcars-cli --help    # CLI usage (a client of the HTTP API, nothing else)
```

- **After every edit, compile.** Warning flags are `-Wall -Wextra -pedantic -Wshadow`
  and the code builds clean — keep it that way. `make check` is the
  quickest full-warning check of the server; `make lcars-cli` for the CLI.
- `resources/` (ignored) holds a box's own large files, the embedder's gguf
  on the VPS. Don't delete it.
- **The C code has no unit tests**; its behaviour is covered by the
  functional tests below, each against a scratch server. CI
  (`.github/workflows/c-cpp.yml`, on `main`) builds the server and the CLI
  and asks a started server `/health`. `static.yml`, on every push to deb
  (each deploy; main in the public repo) and pull request, builds
  `lcars-static` in Alpine for x86_64 and arm64 (arm64 may fail without
  failing the run: the private clone's arm64 runners are metered) and
  runs `scripts/release/check.sh` on it, also in bare Debian and Fedora; `release.yml` does the same on a `v*` tag and
  publishes the tarballs (`scripts/release/package.sh`) - a tag is the
  captain's. `LCARS_CHECK_DYNAMIC=1 scripts/release/check.sh ./lcars-embed`
  runs the checks that need no static link here.
- **The web UI does:** `lcars-ui/test/run.sh` runs, fastest failure first,
  the QuickJS behaviour suite (the page against a DOM shim and a fake API
  over real rows, read-only from `$LCARS_TEST_DB`, default the checkout's `lcars.db`,
  else (a fresh clone) one `test/synth.py OUT.db` writes for the run: a check
  must pass on both; the kinds' mapping is that journal's `kinds` entry, or
  `$LCARS_TEST_KINDS`, a mapping file, and a check must pass on the defaults
  and on a set one: docs/design/kinds.md),
  `test/deckboot.js` (node: the deck's script against stand-ins for three.js
  and the DOM — catches wiring errors, not rendering), `test/keyboard.py`
  (`KB=0` skips it) and `test/perf.py`, the frame budget: every interaction
  must hold 60 fps at p99 (≤16.7ms of main-thread time per frame) against a
  4000-row synthetic journal in headless Chromium (`PERF=0` skips it while
  iterating; run it in full before committing a page change;
  `perf.py --profile <scenario>` names the heavy functions; a scenario
  over budget is rerun and compared with deb's page, and passes if deb is
  as slow - see "judging" in perf.py; one this change cannot reach, by
  `test/changed.py`, is not rerun, and deb's numbers measured on this box
  are reused - the output says which, `--fresh` measures again). It also fails if
  `APP_VERSION` and `CHANGELOG.md` disagree. The slow stages run in
  parallel (~18s with `PERF=0`, ~50s in full on the laptop); `KB_JOBS=1`
  and `perf.py --jobs 1` run one at a time.
- **`run.sh --changed`** runs only what this branch's change needs, from
  its diff against deb (worktree included; `python3 test/changed.py` says
  what it would pick, and why): parse, structure and the version check
  always; `deck.html` the deck; `index.html` the audit, behaviour and
  keyboard, and perf only for the scenarios whose sections moved (the map
  is in `test/changed.py`; a hunk that only bumps `APP_VERSION` does not
  count); docs, `scripts/` or C alone, none of the slow stages. It names
  the Chromium checks outside `run.sh` the touched sections call for.
  Use it while iterating. On the VPS (4 cores since 2026-10-14) the full
  run is ~2-3 minutes (perf ~1.5 of them, ~5 when three scenarios are
  compared with deb) and `PERF=0` ~40s, inside one tool call's 10
  minutes (docs/ops/engineer-time.md). **The full `run.sh` is still
  required** once before you report a page change done (with perf if a
  measured view's code moved, which `--changed` tells you), whenever a
  change touches shared code (`helpers`, `state`, `load`, the markup, the
  phone CSS: `--changed` then runs everything anyway), and it is what a
  deploy runs.
- Functional tests outside `run.sh`, each against a scratch server built
  from the `lcars-release` compile line to a temp path (never `./lcars`), an
  empty database and temp directories. Run the one matching what you touched:
  - `test/dates.sh` (6-15 min, no server): the behaviour suite as of the
    days a "today" check breaks (`LCARS_TEST_NOW`, test/gen.py) - after
    touching dates, the calendar, the rail or the day bars.
  - `test/recording.py` (~40s): `lcars_media.h`, the tape code in the page —
    fragmented MP4s, WebM, cuts, streamed tapes, `GET /media/` and its cache,
    audio and video dictation in Chromium through to playback.
    `test/e2e.py` is its browser-only half (stubbed API) for voice typing.
  - `test/demo_static.py` (~1 min, no server): the public demo -
    `demo/static.py` builds the folder (and its audit for anything of
    ours), http.server serves it under `/lcars-demo/`, and Chromium boots
    the console in demo mode, edits, reloads, resets and loads the deck,
    with every request off the folder refused and counted. After touching
    `demo/static.js`, `static.py`, `fixture.py`, or the pages' `DEMO` paths.
  - `test/reports.py` (~40s): hosted reports - `scripts/report.py`
    publish/list on a scratch media root, `GET /reports`, and the headers
    `/media/reports/` is served with (the CSP sandbox, nosniff, from the
    NAS and the cache), the refusals, and in Chromium that an HTML
    report's script cannot read the origin's localStorage.
  - `test/offline.py` (~30s): the outbox, `api()`, the mirror or `sw.js` —
    Chromium with the network cut.
  - `test/buttons.py` (~6 min): dialogs, the header, the phone layout or
    the page routing — every view opens from its button, gets its url and
    closes by Close, Escape and Back, every button is pressed at desktop and
    phone size, and a phone page is never wider than the screen.
  - `test/update.py` (~40s): the app's own update - `sw.js`'s
    "refresh", the check (one ranged GET of index.html, 206) and Update:
    the new shell in the worker's cache, one reload, nothing offline.
  - `test/back.py` (~40s): the chats, the page routing or `writeState` —
    Back from a chat thread is the list, from the list out of the chats,
    at a phone's size, a cold deep link included.
  - `test/deckvoice.py` (~2 min, no server): the deck's spoken orders
    (`DVCMDS` in deck.html, `lcarsDeckVoice` in index.html) - deck.html?demo
    in headless Chromium with a stand-in recogniser in every frame: Y opens
    the console's microphone for the deck, and each order said is checked
    against the deck's state (the room and deck, the hand, the pins, the
    sheets, the settings, a refusal's hint). `deckboot.js` (in run.sh)
    checks every deck key and touch pill has an order.
  - `test/architect.py` (~10 min; `--no-server` ~5, `--round-trip` ~5):
    the architect (docs/design/architect.md) - deck.html?demo in headless
    Chromium, a patch handed to `lcarsDeckPatch` lifting a Ten Forward
    model: +1 draw call, kept in localStorage, replayed after a reload,
    revised, off, skipped after a hang, `?nopatch`, the sheet (I),
    `lcarsDeckSees` and `lcarsDeckShot` (`--out DIR` keeps the before and
    after pictures). Then the round trip on a scratch server with claude
    stood in for, streaming a fenced patch: the console's `arch` thread in
    the deck's frame, the context and the picture sent, the patch applied
    before the answer ends, the `deck_patch` entry written by the page,
    replayed from it on a reload, the sheet's switch kept by a guarded
    PATCH, a failing patch's automatic second turn. deckboot.js holds the
    undo and the reference (the design's section 9 and crew/architect.md).
  - `test/editor.py` (~2 min): the entry editor in Chromium at 390px and
    1280px - the phone's bar and its ⋯ sheet, nothing `hidden` shown, and
    (docs/design/editor.md) every door out of an edited entry saving
    as it leaves, a failed save on its row, the save chip; Details, the
    kind chip and the title's face; a new entry focused, never empty,
    autosaved; a tap on the reader's text; Escape letting go first.
  - `test/chat_media.py` (~40s): a chat's files - `POST /chat/media`
    (the store, the answer, the cap, the 403s, an unmounted root),
    `attachments` on `/chat`, `/ask` and `/engineer/<name>/say` (the path
    check, the lines in the message, the Read rule) with claude and
    engineer.py stood in for; and the server's sockets all close-on-exec
    (`/proc/<pid>/fdinfo`), the stand-ins started holding none.
  - `test/turn.py` (~20s, no server): the course map's turning
    (`crsTurnable`) in headless Chromium against perf.py's fake API - a
    faked compass turns it, every marker upright on its spot, the needle,
    a fit on a turned map, a drag, a pinch that does not turn, a two-finger
    turn about the fingers' middle, a long press's stop, shift and the
    wheel, an upright popup, a stop dragged. After touching "plot a course".
  - `test/caldav.py` (~40s): `lcars_caldav.h`, with raw WebDAV.
  - `test/api.py` (~30s): the timestamps `POST /entries` and
    `PUT`/`PATCH /entries/<id>` take (`NormalizeStoredTimestamp` in
    `lcars_http.h`) - ISO 8601 with Z or an offset converted to UTC across
    midnight, a month, a year and a leap day; a malformed one a 400. And
    `InitDB` (`lcars_db.h`) planting no seed: a new journal, or one
    emptied by hand, stays empty.
  - `test/config.py` (~30s): `lcars_config.h` - the version (`lcars
    version`, the start log), `lcars.env` found by `--data`,
    `$LCARS_DATA_DIR` or the working directory, its format, the real
    environment winning, `LCARS_PORT`, the start log's `Config:` line;
    `lcars init` (what it makes, a server started on it, a second run
    changing no byte, the refusals).
  - `test/onebin.py` (~60s): `make lcars-one` - serving from `--data`
    (the start log, `D/bin/lcars-cli` made and found by the chat's
    claude, the working directory untouched), `lcars-one cli`, the
    `lcars-cli` symlink and one of the user's own answering exactly as the
    separate `lcars-cli` does, the link kept, replaced or left alone, init
    and version through it; `lcars-release` refusing `cli`.
  - `test/dedupe.py` (~15s): the keyless twin guard on `POST /entries`
    (`HandlePostEntryDeduped` in `lcars_http.h`) - twins in 2s one row
    and `X-LCARS-Deduped: 1`, another body, after the window, a keyed
    create, two logins, twins at once.
  - `test/strava.py` (~15s): `lcars_strava.h`, `lcars-cli strava`, against
    a stand-in Strava (`LCARS_STRAVA_API`) and a temp HOME: the grant, a
    refresh with rotation, two pages, a re-pull, a 429.
  - `test/transcribe.py` (~40s): `POST /transcribe` in `lcars_say.h`,
    against a stand-in Deepgram (`LCARS_DEEPGRAM_URL`): what is sent, the
    answer's contract, the refusals, Deepgram failing, no key.
  - `test/ptt.py` (~30s, no server): the chats' push-to-talk block and
    its conversation mode, cut from `index.html` into a bare page in
    Chromium with a fake microphone and a stand-in Deepgram; `--real`
    opens the real socket with `DEEPGRAM_API_KEY` from `.env` (never printed).
  - `test/speech.py` (~10s, no server): the chats' speech queue block,
    cut from `index.html` into a bare page in Chromium with a stand-in
    `/say` - sentences cut, played in order back to back with one fetch
    ahead, a stop ending the whole run, the fallback to speechSynthesis,
    a run reopened for an engineer's next message.
  - `test/kinds.py` (~40s): `lcars_kinds.h`, kinds by role
    (docs/design/kinds.md) - `GET /kinds/roles` on a new, empty journal
    (no seed row), `PUT` (a role and its name, a list role, null back to
    the default, the `settings` entry it writes), its refusals (not a
    slug, the app's own kinds, the wrong shape, one bad role of several:
    nothing written), the entry edited by hand (a role unknown kept, a
    bad value's `error`, not JSON: a 409), the lowest id winning, and the
    logins (read, never write); then the server following the roles:
    CalDAV's task kind (`$LCARS_TASK_KIND` still winning), the logins'
    `<task>_<owner>`, the steward and the `imported` role, the computer's
    prompts (a stand-in claude); and `lcars-cli roles` (list, `--json`,
    set, reset, the refusals, a server older than the route).
  - `test/features.py` (~40s): `lcars_features.h`, `GET /features` - a
    bare server (every feature off but CalDAV, each naming exactly what
    it lacks), a full one with stand-ins (every feature on, no value, path
    or port in the answer), embeddings with nothing answering; the owner's
    login only (the limited logins 403), and the media root going away.
    `test/features_ui.py` (~40s) is the page's side: in Chromium against
    a bare one, each door's note in its view (`featureOff`, `featNote`),
    Config's Server section, `W` and "what is off", and a limited login
    (403) losing nothing - after touching those or a door they guard.
  - `test/questions_ui.py` (~40s): Open questions (`openQuestions`) at a
    phone's size against a scratch server - a task_no1 written by Number
    One's login and a task_crew, the Chats button's count and row, the
    cards, a Later draft across a reload, Answer and close (the real
    PATCH with `if_modified`: the answer at the top, done 1) and Undo.
  - `test/metrics.py` (~40s): `lcars_metrics.h`, `GET /metrics` - the
    readings by the UI's rule, the text format, who may read it.
  - `test/framing.py` (~40s): Content-Length and the header lookup in
    `lcars_http.h` — what a malformed, huge, chunked or short body is
    answered, and pipelined requests on one connection.
  - `test/uigzip.py` (~40s): gzip for `/ui/` (`lcars_ui_files.h`) - deck.html,
    index.html, a glb and a css gzipped with Vary and their types, the cache
    (Content-Length) and the streamed form (chunked), identity without
    gzip offered, for a HEAD and an index.html Range (206), never a png or a
    webp, a 304, a saved file never stale (same size and mtime included),
    parallel gets across a save; the cache off and a small one starting over.
    Then an embedded build (`-DLCARS_EMBED_UI`, its pack in scratch): the
    start log's `UI:` line, every shipped file byte-equal to its source, the
    same checks, a 304 by ETag, `LCARS_UI_DIR` winning. After touching
    `scripts/ui-pack.py` too.
  - `test/logins.py` (~40s): `lcars_logins.h` or the auth in `lcars_http.h`
    — what Number One's and the crew's logins may and may not write; the
    steward's create, append and title rule, `POST /entries/<id>/append`
    and `POST /entries/<id>/title`; the patch kinds (`deck_patch`,
    `ui_patch`) written only with `X-LCARS-Client`, a scratch lcars-cli's
    writes of one refused.
  - `test/db_swap.py` (~20s): `scripts/db-swap.sh`, `db-filter.sh`,
    `db-slots.sh`, with every path overridden (`LCARS_SWAP_*`): two
    scratch journals, a stand-in systemctl driving a scratch server, a
    temp deploy lock - the refusals, a rename failing part-way, a swap and
    back, /health failing; the filter (side rows, counts, .prev, refused
    with the copy live) and `fresh` from either slot.
  - `python3 scripts/test_prune.py` (~1s; `--real` ~40s, a scratch build
    and the page in Chromium): `scripts/db-prune.py`, the weekly
    `crew_inbox` prune - only done slips untouched for seven days go, with
    their side-table rows; the dry run changes no byte; the refusals; and
    the page's one full load after it, then a sync from the mirror.
  - `python3 scripts/test_db_merge_window.py` (~10s, a scratch build;
    `LCARS_TEST_BIN` skips it): `scripts/db-merge-window.py`, a swap's
    rows copied back through the API - NEW, MOVED, CONFLICT, MISSING,
    SKIPPED, a second `--apply` writing nothing, the copy's bytes unchanged.
  - `python3 scripts/test_crew.py` (~5s): `scripts/crew.py`, `crew_tool.py`,
    `crew/*.md` - the scheduled crew runner, with a stub claude and server;
    and `lcars_roles.py`, the crew's kinds by role. It, test_crew_notes.py
    and test_linker.py run on the roles' defaults, or on
    `LCARS_KINDS_FILE=<mapping>`'s kinds (run each once both ways after
    touching a role).
  - `python3 scripts/test_shares.py` (~2s): the shares role
    (`scripts/shares.py`, `crew/shares.md`) - the reddit, HN, Mastodon
    and Cloudflare adapters on saved responses (`scripts/testdata/shares/`),
    the captain's numbers line, the readings and their sums, and a run
    against a stand-in server (what is posted, a run with no shares).
  - `python3 scripts/test_linker.py` (~1s): `lcars_linker.py measure`, the
    hourly pass - start/end pairing (a mis-tapped start, an orphan end, out
    of range, creation order), the stopwatch's one-row spans counted once,
    gym sessions, ownership, and that `--dry-run` writes nothing.
  - `python3 scripts/test_crew_notes.py` (~2s; `--real` ~40s against a
    scratch build): crew notes - `scripts/crew_notes.py`, `crew.py notes
    watch` and `note`: the note rule (and the page's copy, in node), the
    watcher's mark, quiet period and once-per-hash, threads queued to
    answered, a reply mid-turn, the lock, the fences; the write path's
    CHANGES (create, append and title only), applied by the steward or refused.
  - `python3 scripts/test_seat.py` (~7s): `scripts/seat.py` and the seat's
    use in `engineer.py`/`crew.py` - the crew's one Claude Code at a time.
  - `python3 scripts/test_reap.py` (~5s): `engineer.py`'s `reap_scratch`,
    which deletes ended Claude sessions' scratch, never a running one's;
    `reap_test_tmp`, killed test runs' scratch, and `reap_test_servers`,
    their scratch servers; and that a test killed by SIGTERM takes its
    scratch and its server with it (`test/killclean.py`, run.sh's traps).
    A new test's scratch dir: make it with `killclean.mkdtemp`, named so
    `TEST_TMP_RE` in engineer.py knows it; a process it starts (a scratch
    server), give to `killclean.child`.
  - `python3 scripts/test_no1_inbox.py` (~20s): Number One's inbox
    (`no1_send`, `no1-flush`, `no1-send`: `crew_inbox` entries, against
    test_seat's stand-in server) - each note typed once, even when what
    started the flusher ends or it is stopped mid-note; one sent while the
    journal is down is written when it is back.
  - `python3 scripts/test_engineer_model.py` (~40s; `LCARS_TEST_BIN`
    skips the build, `SKIP_ROUTE=1` the server): the model per engineer -
    `engineer.py model`/`model-apply` and `POST /engineer/<name>/model`;
    and the poll's earlier conversations (`?past=<session>`).
  - `python3 scripts/test_queue.py` (~1s): `engineer.py queue`, the Queue
    view's route - the seat with each one's order, the deploy history with
    versions, headlines and outcomes, seeded once from the logs' failures;
    each item's time - the activity classifier, the tasks cut from a sample
    transcript, a deploy tied to its task, the cache, the work under way;
    and the estimate (`engineer.py eta`): its revisions, its end with the
    turn, its fields in list and the queue, a shipped item's own.
  - `python3 scripts/test_deploy_suite.py` (~3s): the deploy's web suite
    (`web_suite`, `suite_scope`): a page deploy runs the full `PERF=0`
    run.sh, a deck-, test- or docs-only one `run.sh --changed` (an
    `APP_VERSION` bump is not a page change), and the log says why.
  - `python3 scripts/test_vps_rebuild.py` (~1s): `scripts/vps-rebuild.sh`
    in a scratch checkout with make, systemctl and curl stood in for - the
    one binary (`make lcars-one`) built and swapped in, one without the CLI
    or a failed build refused with `./lcars` untouched, another journal's
    count rolled back, and the `bin/lcars-cli` link dropped when the binary
    put back has no CLI in it.
  - `python3 scripts/test_brief.py` (~1s): `engineer.py brief`, a role's
    `crew/<role>.md` for the console's chat - a slug, never a path.
  - `python3 scripts/test_events.py` (~1s): `engineer.py`'s `events_of`,
    a transcript line made into the console chat's bubbles - a
    `<pasted_content>` message (a quote reply, a line the ship types in)
    unwrapped and shown, a slash-command echo or system-reminder dropped.
  - `python3 scripts/test_ctx.py` (~1s): the context gauge -
    `engineer.py`'s `context_tokens` on a sample session file, and the
    turn-ended hook's handover line for Number One, once per crossing.
  - `python3 scripts/test_export.py` (~1s): `scripts/export-public.py`,
    the public release's export, on a fixture repo with made-up patterns:
    the exclusions (`*.local.*` included), the badge's substitution, the
    public CHANGELOG and TODO, an audit hit by file:line and rule, a rule
    narrowed by glob, the dirty tree and a bad DEST refused,
    `--audit-only`'s groups.
  - `python3 scripts/test_no1.py` (~4s): `no1.py journal` - which
    lcars-cli it runs, with Number One's login, and that lcars-cli has no
    `--db` at all; the refresh (its log, the Stop hook's clear), and
    `launched_bare`, a session herdr relaunched without its hooks.
- The on-screen keyboard is the browser's: nothing in the page fits the
  layout to it (iOS pans to the field, Android resizes). `test/keyboard.py`
  opens every view, palette row, the editor and the reader at a phone's size
  and focuses every visible text field; it fails if one is under 16px (iOS
  zooms into it), or a field focused while data loads loses focus when it
  lands (guard a late `.focus()` with `fieldFocused()`). A field reached only
  through a button inside a view needs a line there.
- Run `clang-format` (config in `.clang-format`, LLVM-based, 2-space) on files you edit.
- `compile_commands.json` is generated via `bear` (`make compile_commands.json`);
  `.clangd` adds the `LCARS_IMPLEMENTATION` etc. defines so clangd sees function bodies.

## Local rules

**`CLAUDE.local.md`, when it exists, holds this deployment's own rules (where
production is, its danger zones): read it before any work.** @CLAUDE.local.md

## Danger zones — do not touch without being asked

- `lcars.db` is **live personal data** (journal entries). Never delete, overwrite, or
  experiment on it. Use a copy in scratch space if you need a DB to test against.
  `lcars-cli` only talks to a server: point it (`--url`) at a scratch one
  when trying things out.
  `lcars_bkp.db` is a backup snapshot. Both are gitignored.
- `vendor/` is vendored deps — don't reformat or "clean up".
- **Reports for the captain** (an HTML page, a PDF, a chart, a CSV) go
  through `scripts/report.py publish FILE --title T` (Number One:
  `no1.py report`), which puts them in the media store and prints the
  link to give the captain. Never commit one, or leave it elsewhere on the box.

## Architecture in one paragraph

Unity build: `lcars.c` is the server's only translation unit; `lcars_cli.c`
is the CLI's. All code lives in single-header libraries (`lcars_*.h`):
declarations always visible, function bodies inside `#ifdef
LCARS_IMPLEMENTATION` (`LCARS_HTTP_IMPLEMENTATION` for the server's).
`lcars_http.h` is the server (sockets, auth, the router, the `/entries`
routes) and includes its route modules (`lcars_caldav.h`, `lcars_chat.h`,
`lcars_media.h`, …) from inside its implementation block; `lcars_db.h` is the
schema. Each connection is a thread with its own sqlite handle and a 1MB
on-stack arena for its request; arena OOM aborts by design. `lcars_json.h`
is the JSON scanner both programs share.

## Conventions & gotchas

- New route module = new `lcars_foo.h` following the same shape, included
  from inside `lcars_http.h`'s implementation block. Don't create new `.c`
  files.
- Functions are PascalCase (`HandleGetEntries`), the arena API is snake_case
  (`arena_alloc`). Prose TODOs go in TODO.md.
- Comments in this codebase explain *constraints and why*, and are unusually
  thorough. Match that: when you write non-obvious code, say why it must be so.
- **Every interaction gives immediate visible feedback** (the captain's
  standing rule, all UI). A tap, a key or a voice order shows *something*
  in the same frame, before any network: a pressed state, a pending or
  sending mark, the optimistic result (a sent message as a bubble marked
  "sending…", a new row saying "reporting for duty…", a model chip already
  changed). The real answer replaces it when it lands, and a failure says
  so where the optimistic result was (with Retry, the text given back),
  not only in a toast. A button that starts something slow stays visibly
  pressed or busy until it settles. Never leave a tap looking ignored.
  docs/design/chat.md §3 has the table for the chat.
- **Every web UI feature gets a voice order.** Anything a person can
  trigger in `lcars-ui/index.html` (a key, a button, a palette row) must
  also be reachable by speech: add a line to `VCMDS` (the "computer, …"
  table — the help panel is built from it) calling the same function the
  button calls, plus a key in `KEYS`/a palette row as usual. The QuickJS
  suite fails when a `KEYS` entry has no order. `run …` reaches palette rows
  by name, which is a fallback, not a substitute for a natural phrase. If
  voice truly cannot do it (a browser that only allows it from a tap: file
  pickers, the camera, the share sheet), say so in the commit and TODO.md.
  Check alias collisions with `vMatch` — longest phrase wins, and with
  dictation paused an order must match the whole utterance.
- **State the captain or the crew should see lives in the journal**, as
  entries of a kind the writer's login owns (`crew_*` for the crew,
  `no1_*` for Number One), not in files on the box: he can read and edit
  it, and a crew member can work with it. Files only for locks (the API
  has no compare-and-swap), secrets, and what a deploy needs while the
  server is down. The seat (`crew_seat`, `crew_inbox`) is the model.
- **`CHANGELOG.md` holds the version.** Every commit that adds a feature bumps
  the minor (fix/polish/internal: the patch), adds a dated entry at the top, and
  sets `APP_VERSION` in `lcars-ui/index.html` to match — the web UI shows it
  beside the LCARS badge so a stale cached page is visible.
- Commit style: short imperative summary, e.g.
  `Harden the TODO macro: fprintf+newline to stderr, abort() (I2)`.
- **`TODO.md` is the living backlog** (features, bugs, refactoring ideas) — check it
  when picking a task. Keep it current as part of the task: remove items you
  finish (CHANGELOG records them), add anything new worth tracking.
  `REFACTORING.md` is a **closed** audit — history and rationale, not a to-do list.
