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
  and asks a started server `/health`. `static.yml`, on every push to main
  (each deploy, here and in the public repo) and pull request, builds
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
  (`KB=0` skips it), the screens stage (`test/targets.py` and
  `test/axe.py` on every view, the two at once; `SCREENS=0` skips it) and `test/perf.py`, the frame budget: every interaction
  must hold 60 fps at p99 (≤16.7ms of main-thread time per frame) against a
  4000-row synthetic journal in headless Chromium, and its cold load
  through `/dump` with 111 reports within 1.3x of none (`PERF=0` skips it while
  iterating; run it in full before committing a page change;
  `perf.py --profile <scenario>` names the heavy functions; a scenario
  over budget is rerun and compared with main's page, and passes if main is
  as slow - see "judging" in perf.py; one this change cannot reach, by
  `test/changed.py`, is not rerun, and main's numbers measured on this box
  are reused - the output says which, `--fresh` measures again). It also fails if
  `CHANGELOG.md`'s top and `APP_VERSION` disagree, or a fragment in
  `changelog.d/` is malformed (`test/version.py`: a numbered top equal to
  it, fragments beside it, or a retired placeholder on top with `APP_VERSION` left
  at the number below), or the user manual no longer matches the page
  (`site/manual/test/manual.py`, docs/design/manual.md: its landing build
  stale, or an order, a key or a `**label**{ui}` it names gone). The slow stages run in
  parallel (~18s with `PERF=0`, ~50s in full on the laptop); `KB_JOBS=1`
  and `perf.py --jobs 1` run one at a time.
- **`run.sh --changed`** runs only what this branch's change needs, from
  its diff against main (worktree included; `python3 test/changed.py` says
  what it would pick, and why): parse, structure and the version check
  always; `deck.html` the deck; `index.html` the audit, behaviour,
  keyboard and screens, and perf only for the scenarios whose sections moved (the map
  is in `test/changed.py`; a hunk that only bumps `APP_VERSION` does not
  count); docs, `scripts/` or C alone, none of the slow stages. It names
  the Chromium checks outside `run.sh` the touched sections call for.
  Use it while iterating. On the VPS (4 cores since 2026-10-14) the full
  run is ~2-3 minutes (perf ~1.5 of them, ~5 when three scenarios are
  compared with main) and `PERF=0` ~40s, inside one tool call's 10
  minutes (docs/ops/engineer-time.md). **The full `run.sh` is still
  required** once before you report a page change done (with perf if a
  measured view's code moved, which `--changed` tells you), whenever a
  change touches shared code (`helpers`, `state`, `load`, the markup, the
  phone CSS: `--changed` then runs everything anyway), and it is what a
  deploy runs.
- **Heavy commands go through the job line** (docs/design/job-queue.md):
  the cores take one heavy run at a time. Heavy: `run.sh` (full or
  `PERF=0`; `--changed` too when it picks the behaviour, keyboard, screens or perf
  stages), `perf.py`, `buttons.py`, `qa_chat.py`, `keyboard.py`,
  `dates.sh`, `architect.py`, `deckvoice.py`, `editor.py`, `classified.py`,
  `deckshots.py`, `deckmem.py`, `shots.py`, `site/manual/pictures.sh`,
  `scripts/deck-models/build.sh`, and `make
  lcars-release|lcars-one|lcars-embed|lcars-static`. Light, run bare: `make
  check`, `make lcars`, `make lcars-cli`, a `--changed` run of no slow
  stage, one functional test under ~30s, every `scripts/test_*.py`. A
  seated engineer runs a heavy one as `scripts/engineer.py job <name>
  [--label T] -- <command>` (a `PreToolUse` hook refuses it bare): inline
  when nobody waits (its run detached: it outlives your turn and session,
  and a result you did not see is typed to you); "queued" means end the turn at once and edit nothing,
  and the result comes back as a `[job]` message at the head of the seat's
  line. `engineer.py jobs` shows the line, `job-cancel <name>` takes it back.
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
  - `site/landing/` (the hosted waitlist's page and Worker, its README;
    the user manual's built page at `public/manual/`, from `site/manual/`):
    `node --test site/landing/test/` (~1s, the signup route's contract)
    and `python3 site/landing/test/page.py` (~15s, the page in Chromium
    at 393x852 and 1280x800 against `preview.mjs`), `test/deploy.py`
    (~2s, `deploy.sh --dry-run`'s staged copy: the share card's absolute
    URLs). Deploying it, D1 and DNS are the captain's.
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
  - `test/deckmem.py` (~10 min, no server; a heavy job): the deck's
    memory on a walk at an iPhone's 393x852 at 3x (graphics low by
    default, `--gfx high`) - deck 8's wings, the lift to decks 12 and 3,
    back to the concourse, three times; WebGL's textures, buffers and
    renderbuffers counted at the context, the heap, the live three.js
    objects (CDP). `--check` fails if a room taken down is still
    referenced (live objects over the boot's), anything grows from loop
    to loop, or a lost context does not come back. After touching what
    builds or takes down a room or deck (`buildRoom`, `dropCell`,
    `unloadDeck`), or anything that keeps a record of a placement.
  - `test/turn.py` (~20s, no server): the course map's turning
    (`crsTurnable`) in headless Chromium against perf.py's fake API - a
    faked compass turns it, every marker upright on its spot, the needle,
    a fit on a turned map, a drag, a pinch that does not turn, a two-finger
    turn about the fingers' middle, a long press's stop, shift and the
    wheel, an upright popup, a stop dragged. After touching "plot a course".
  - `test/helpopen.py` (~20s, no server): the keyboard help (?) opened
    as a person opens it - a phone upright and on its side, a desk: the
    `? shortcuts` button, the ? key, the palette's row - in headless
    Chromium against perf.py's fake API; the box empty, the rows drawn
    under their headings, the route. After touching `openHelp` or a door to it.
  - `test/targets.py` (~35s, no server; in run.sh since
    slice G, its screens stage, beside axe.py): the phone's tap targets
    (docs/design/ui-rules.md, "Targets") in headless Chromium at an
    iPhone's size with touch, against perf.py's fake API - every control
    on every view (the list, the reader, the editor, the ⋯ sheet, the
    filters drawer, the month, a new entry, Tasks, Statistics, the
    chats, the help, the palette, Reports, the graph) hit over 44px each
    way (its `::before` hit area, a checkbox's label counted), none cut
    short by a neighbour's, a few allowed less by name (`SHORT`, each
    with why); the header's pills 44px tall; the rendered rules and
    320px reflow on the same views. Run it bare after touching a
    control's size or a hit area.
  - `test/axe.py` (~30s, no server; in run.sh's screens stage too):
    axe-core (`vendor/axe-core`, WCAG
    2.2 A and AA, and its label-in-name rule) on the phone's six screens
    and the desk's views in headless Chromium against perf.py's fake API
    (ui-rules.md, "axe finds nothing"): every violation fails but
    `AXE_LEFT`'s, each with why, and one of those no longer seen. After
    touching the markup, a label, a role or an ARIA attribute.
  - `test/acplace.py` (~20s, no server): where the editor's autocomplete
    popup lands (`wikiPlace`, `wikiFit`, `wikiCaretXY`) in headless
    Chromium against perf.py's fake API, measured against the browser's
    own caret (`caretPositionFromPoint` into the textarea): a desk and a
    phone, a deep line, the list narrowing, a wrapped line, focus mode,
    the field and the editor scrolled; then WebKit at a phone's size
    (`LCARS_WEBKIT=<launcher>` where Playwright's build lacks libraries;
    one that cannot start is skipped). After touching the popup.
  - `test/quick.py` (~30s): `POST /quick` (`HandleQuick` in
    `lcars_chat.h`, voice-quick-answer.md 4), claude stood in for - the
    argv (haiku, `--tools ""`, `--system-prompt`, no `--resume`), stdin's
    `<context>` and `<question>` (a tag in either defused), the PASS
    mapping, the caps' 400s, one at a time (429), the 8 s timeout (504,
    the child killed), a closed connection killing it, a failed run's
    502, the limited logins' 403, and a log line with no word of the
    question.
  - `test/publish.py` (~20s): `lcars_publish.h`, `POST /publish/<id>`
    and `POST /publish/card` with publish.py stood in for
    (`LCARS_PUBLISH_SCRIPT`) - the owner from the pages only (the
    limited logins and a missing `X-LCARS-Client` 403), the argv and the
    environment (no engineer key), the refusals before a run, the exit
    status, one at a time (429), the timeout (504, the child killed), the
    log. `python3 scripts/test_publish.py` (~2s) is publish.py itself:
    Mastodon and Bluesky on recordings, dry run, once per text, the cap,
    the card's public-hosts rule, no secret in any output.
  - `test/caldav.py` (~40s): `lcars_caldav.h`, with raw WebDAV.
  - `test/api.py` (~30s): the timestamps `POST /entries` and
    `PUT`/`PATCH /entries/<id>` take (`NormalizeStoredTimestamp` in
    `lcars_http.h`) - ISO 8601 with Z or an offset converted to UTC across
    midnight, a month, a year and a leap day; a malformed one a 400; a
    `report` entry cut to its first line in `/dump` and `report_body=0`,
    whole by id. And
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
  - `test/classified.py` (~1 min; `CHROMIUM=0` the server only): Secret
    entries (docs/design/confidential-entries.md, `lcars_vault.h`, the
    page's "classified" block) - `lcars_sha256.h` against the NIST
    vectors; `GET/PUT /vault` and its token guard; a Secret row's
    envelope-only writes, the limited logins' placeholders, append, title
    and uploads refused; a raise (the plaintext in no byte of lcars.db or
    its WAL, the vector and the CalDAV row gone) and a lowering; the
    embedder with a stand-in service. Then the page in Chromium
    (`classified_ui.py`): the password set, a Secret entry written,
    raised, locked, unlocked, searched, offline, declassified, and every
    request, localStorage and IndexedDB scanned for the password and the
    entry's words; then at localhost with CDP's virtual authenticator
    (hasPrf) the page's CSP, a passkey registered, unlocking, removed, one
    without PRF refused, the recovery code's round trip and a one-wrap
    vault. After touching any of those, or a reader of entries.
  - `test/dedupe.py` (~15s): the keyless twin guard on `POST /entries`
    (`HandlePostEntryDeduped` in `lcars_http.h`) - twins in 2s one row
    and `X-LCARS-Deduped: 1`, another body, after the window, a keyed
    create, two logins, twins at once.
  - `test/strava.py` (~15s): `lcars_strava.h`, `lcars-cli strava`, against
    a stand-in Strava (`LCARS_STRAVA_API`) and a temp HOME: the grant, a
    refresh with rotation, two pages, a re-pull, a 429.
  - `test/say.py` (~40s): `POST /say`'s engines in `lcars_say.h`, against
    a stand-in ElevenLabs and Deepgram (`LCARS_ELEVENLABS_URL`,
    `LCARS_DEEPGRAM_URL`): ElevenLabs' request, Deepgram standing in for
    it (a 5xx, no connection, a slow first byte; each seat's Aura voice,
    the format kept, `X-LCARS-Say`, the log line), a quota and a 429
    remembered, a bad voice still a 502, both failing, no Deepgram key,
    `LCARS_TTS=deepgram`. No real credits spent.
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
  - `test/theme.py` (~40s): `lcars_theme.h`, `GET`/`PUT /theme` - a
    built-in by name, a btop file or omarchy's `colors.toml` as text/plain
    with `?name=` or as JSON, the `settings` entry titled `theme`, the
    refusals (a name, a shape, 64 KB, a control byte), a hand-edited entry
    (409), the lowest id, the logins (read, never write); `lcars-cli
    theme`; and `scripts/omarchy/lcars-theme-set` in a scratch HOME (exit
    0 at once, every failure one line on stderr).
  - `test/features.py` (~40s): `lcars_features.h`, `GET /features` - a
    bare server (every feature off but CalDAV, each naming exactly what
    it lacks), a full one with stand-ins (every feature on, no value, path
    or port in the answer), embeddings with nothing answering; the owner's
    login only (the limited logins 403), and the media root going away.
    `test/features_ui.py` (~40s) is the page's side: in Chromium against
    a bare one, each door's note in its view (`featureOff`, `featNote`),
    Config's Server section, `W` and "what is off", and a limited login
    (403) losing nothing - after touching those or a door they guard.
  - `test/rooms_ui.py` (~40s): the Rooms page (docs/design/rooms.md 6)
    at 393x852 against a scratch server, engineer.py stood in by a script
    writing the rows - the door, a send through to its row, To an
    engineer and waiting for the seat, a failure and Retry, a room made,
    closed and reopened, Back and Escape.
  - `test/questions_ui.py` (~40s): Open questions (`openQuestions`) at a
    phone's size against a scratch server - a task_no1 written by Number
    One's login and a task_crew, the Chats button's count and row, the
    cards, a Later draft across a reload, Answer and close (the real
    PATCH with `if_modified`: the answer at the top, done 1) and Undo.
  - `test/metrics.py` (~40s): `lcars_metrics.h`, `GET /metrics` - the
    readings by the UI's rule, the text format, who may read it; the
    crew's file appended (missing, stale, over its cap, off).
    `python3 scripts/test_metrics_eng.py` (~1s) is the file's writer,
    `scripts/eng_metrics.py`: counters and buckets through the seat's,
    jobs' and deploys' events (docs/ops/seat-metrics.md).
  - `test/conncap.py` (~40s): the connection cap in `lcars_http.h`
    (`HTTPSlotAcquire`) - every slot an idle keep-alive and a new
    connection answered, the longest-idle one closed; every slot
    mid-request a 503 and one rate-limited log line.
  - `test/framing.py` (~40s): Content-Length and the header lookup in
    `lcars_http.h` — what a malformed, huge, chunked or short body is
    answered, and pipelined requests on one connection.
  - `test/uigzip.py` (~40s): gzip for `/ui/` (`lcars_ui_files.h`) - deck.html,
    index.html, a glb and a css gzipped with Vary and their types, the cache
    (Content-Length) and the streamed form (chunked), identity without
    gzip offered, for a HEAD and an index.html Range (206), never a png or a
    webp, a 304, a saved file never stale (same size and mtime included),
    parallel gets across a save; the cache off and a small one starting over;
    the manual at `/ui/manual/` and the 301s of `/manual` to it.
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
  - `python3 scripts/test_social.py` (~6s): the social watch
    (`scripts/social.py`, `crew/social.md`, docs/design/social-watch.md) -
    the HN, GitHub and Cloudflare adapters on recordings
    (`scripts/testdata/social/`: deleted, dead and bots skipped, the
    captain's replies, the day's stars and traffic), the read-only guard, and runs
    against a stand-in journal: a comment written once, the notice naming
    only the new, a later reply PATCHed with `if_modified`, the daily
    readings, no token in any output, a platform failing alone and three
    failures raising one task.
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
  - `python3 scripts/test_housekeeping.py` (~1s): `scripts/housekeeping.py`,
    the crew's `housekeeping` role, on a scratch HOME and /tmp - the
    never-touch list (the journals, the media root, the Logseq graph, the
    checkouts) offered as candidates and none deleted, a tree holding a
    database, a symlink, a directory a process holds; the dry run; reap's
    scratch (an idle engineer's session split, its notes moved to research), the logs, Playwright's builds, npx, crash dumps by age; the
    thresholds and the note to Number One (crew.py's finish).
  - `python3 scripts/test_seat.py` (~7s): `scripts/seat.py` and the seat's
    use in `engineer.py`/`crew.py` - the crew's one Claude Code at a time.
  - `python3 scripts/test_jobs.py` (~60s): the job queue
    (docs/design/job-queue.md) - seat.py's job line (inline or queued,
    held for the turn's end, a deploy first, the result at the head with
    the cap); two at once ("As built: the jobs": the classes, two shared
    together, an exclusive head holding the line, the memory reserve, the
    limit closing and its five minutes to reopen, `LCARS_JOBS_MAX=1` as
    one at a time, `cores.lock` shared and exclusive between two direct
    runners) and engineer.py's `job`, `job-run`,
    `job-cancel` and the runner on scratch state and a stand-in journal,
    `job-run` a direct child (`LCARS_JOB_RUNNER=direct`,
    `LCARS_ENG_SPAWN=0`): the message, a huge log, a timeout, HEAD or the
    tree moved, a runner killed, dismiss; a job the block lost carried
    over (mid-run, and its result), once, never an old one; the wait for
    the cores not run time, and bounded; `heavy_command`; crew.py's
    `heavy: true`; an inline job outliving its waiter (its result typed
    to its engineer); and the watchdog (`engineer.py watch`): a dead job,
    one past its limit, an untold result, a stuck order, the seat free, a
    silent holder, each said to Number One once.
  - `python3 scripts/test_reap.py` (~5s): `engineer.py`'s `reap_scratch`,
    which deletes ended Claude sessions' scratch, never a running one's, a
    /cleared one's once known cleared (an engineer's `past`, no one's
    `session`, no job naming it, old, unheld), an idle engineer's current
    one after a day (its `scratchpad/` kept with a note), each split: the
    regenerable deleted, the rest moved to `research/<engineer>/scratch-<date>/`
    (`salvage`), Number One's never; and Claude Code's
    `bash-edit-diff/` after a day;
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
  - `python3 scripts/test_no1_threads.py` (~1s): Number One's threads
    as tags (docs/design/no1-threads.md, section 13) - `engineer.py
    thread` and `thread-req` (labels: new, rename, close, reopen), the
    session-era state read into labels, the flusher typing every
    thread's notes at once under their `[thread <id>]` line, a say with a
    thread, each event's thread from a transcript (a message's tag, the
    reply after it, a paragraph's override, `room_at` reading back),
    the turn's thread an order, an ask, a deploy and a refresh record,
    the poll's `th` and `thread=` filter, and the Stop hook switching
    nothing. `test_no1.py` has `no1.py thread`. Every test that imports
    engineer.py imports `scripts/testguard.py` first: no live journal.
  - `python3 scripts/test_teststate.py` (~1s): no test reaches the box's
    real engineer state (`scripts/teststate.py`, which testguard.py
    imports): every path engineer.py made when it loaded is a scratch
    one, 0.294.3's leak replayed leaves the real deploy.json alone, a real
    `LCARS_ENG_STATE` is replaced and a test's own kept, and every
    `scripts/test_*.py` that loads engineer.py guards the import first.
  - `python3 scripts/test_engineer_image.py` (~20s, a scratch build): the
    pictures in the chats - engineer.py's `img` events (`events_of`: the
    key, the size, a pasted picture or a sidechain's skipped, no path),
    `engineer.py image` (the key's session and line, the cap, the magic
    bytes, the cache), and `GET`/`HEAD /engineer/<name>/image` on a
    scratch server: the owner's bytes, type and cache header, Number One's
    session and an earlier one, the limited logins and the steward 403,
    the bad keys, the 404s, the 413.
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
  - `python3 scripts/test_release_import.py` (~10s, a scratch build;
    `LCARS_TEST_BIN` skips it): `scripts/release-import.py`, the release
    entries (docs/design/release-entries.md) - CHANGELOG's sections, the
    entry's shape, noon in the captain's zone, and the import on a scratch
    journal twice. The deploy's write is test_version_stamp.py's.
  - `python3 scripts/test_webapp.py` (~3s): `omarchy/bin/lcars-webapp`
    (`scripts/omarchy/lcars-webapp` links to it), the omarchy plugin's
    installer (docs/design/omarchy-plugin.md 2), in a scratch HOME with
    stand-ins for omarchy-webapp-install/-remove, curl, gh, systemctl and
    the release's lcars - `--local` (the release checked, unpacked,
    linked, init, the unit, /health, the env file 0600, the launcher with
    the plugin's icon) and run again ("left alone"), a newer release
    relinked and restarted, a bad checksum, `--remote` and its login,
    another env file's lines kept, `--uninstall` keeping the data,
    `--dry-run` running nothing, the file alone, the refusal off omarchy;
    the theme hook's offer (in a pty: yes, no, none without a terminal,
    found again, unlinked by `--uninstall`); the icon by path, the
    server's fetched with the login on curl's stdin, or empty.
  - `python3 scripts/test_version_stamp.py` (~2s): the version the deploy
    gives (docs/design/version-at-deploy.md) - `scripts/version-stamp.py`'s
    plan (patch, minor, the floor, an old-style number kept or renumbered,
    the refusals), `scripts/changelog-merge.py` (entries stacked on top,
    one-sided edits, a conflict's markers), and `do_deploy` on a scratch
    live checkout and two worktrees: placeholders and fragments landing in
    order (one alone, two, a fragment plus a placeholder, a fragment's
    review fix, a bad one, none left after), TODO.md's union merge, the
    old way colliding, a rolled-back floor, a conflict, a refused stamp or a
    failed suite or rebuild leaving the branch as it was (and a retry landing), the checks, the outcome's number, the
    release entries it writes (one, two, a failed write, none on a failed
    deploy); and the readers under a placeholder: `lcars-ui/test/version.py` (run.sh's
    version check), the explainer's `X.Y.Z+` and `deliver.sh`'s refusal.
  - `python3 scripts/test_deploy_suite.py` (~3s): the deploy's web suite
    (`web_suite`, `suite_scope`): a page deploy runs the full `PERF=0`
    run.sh, a deck-, test- or docs-only one `run.sh --changed` (an
    `APP_VERSION` bump is not a page change), and the log says why; and
    `classified_touches`, the deploy's "CLASSIFIED:" flag (the classified
    block, the CSP block, `sw.js`).
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
  - `python3 scripts/test_omarchy_plugin.py` (~7s, no server): the
    omarchy plugin in `omarchy/` (docs/design/omarchy-plugin.md) where no
    omarchy runs - omarchy's own validator, pinned in
    `scripts/testdata/omarchy/` (its README: the commit, the refresh; with
    no jq, the same checks in Python, said), broken plugins refused, the
    marketplace's rules, `Model.js` in node, BarWidget.qml through qmllint
    when there is one (else a said skip), and `scripts/omarchy-publish.sh`
    on scratch repos (the dry run, a push, an unbumped change refused, a
    fast-forward). After touching `omarchy/` or the publish script.
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

## The web UI

What the page looks like is ruled by `docs/design/ui-rules.md` (read it
before a visual change); every rule there names its check, and
`test/rules.py` holds most of them. How an engineer works on it (the
research of 24 Oct 2026, "Good UIs with Claude Code", in Reports):

1. **Screenshot before and after.** Before a visual change, `shots.py`
   frames (or Playwright) of the touched view at 393x852 and 1280x800, and
   again after: list the differences you see and fix the unintended ones.
2. **Plan first for anything new.** Before code, five lines and an ASCII
   wireframe naming the tokens and classes used, checked against ui-rules.md.
3. **The builder does not grade.** A fresh-context reviewer (a subagent,
   or the crew's critic) gets ui-rules.md, the diff and the screenshots,
   one untouched neighbouring view among them, and flags only rule breaks,
   as Blocker, High, Medium or Nit.
4. **Name tells, never "avoid the AI look".** The reviewer checks a list of
   named tells; a default that slips in is added to the list.
5. **Grade in LCARS's own words.** Criteria quote ui-rules.md: no "bold",
   "premium" or "polished". The brief's own devices (uppercase Antonio,
   the black field, the numbered section bars) are not tells.
6. **frontend-design for its process only.** Its plan, quality floor and
   copy rules apply; its greenfield aesthetics do not: the brief wins.
7. **Show the evidence.** The report links the screenshots the change was
   checked with (`scripts/report.py publish`), and says "not checked on an
   iPhone" when it touches the foot, sheets, the keyboard or safe areas.

A new rule in ui-rules.md ships with its check, or says why none can be
written ("Every rule ships with its check").

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
- **A check on a dialog's or a toast's text compares against the entry's
  own fields with its title taken out**, never against a bare pattern (a
  hash and digits, a spaced middle dot): the deploy's suite reads the live
  journal, whose real titles hold both (the join and bulk-delete checks
  since 0.335.0).
- **The manual follows the console.** A change to the web UI that the user
  manual describes (a label, a step, a key, a spoken order) updates its
  page in `site/manual/pages/` and rebuilds it (`python3
  site/manual/build.py`: the landing's copy and the app's,
  `lcars-ui/manual/` at `/ui/manual/`, both committed with the change); `site/manual/test/manual.py`,
  in run.sh, fails until it does (docs/design/manual.md). A new feature a
  newcomer would look for gets its lines there too.
- **State the captain or the crew should see lives in the journal**, as
  entries of a kind the writer's login owns (`crew_*` for the crew,
  `no1_*` for Number One), not in files on the box: he can read and edit
  it, and a crew member can work with it. Files only for locks (the API
  has no compare-and-swap), secrets, and what a deploy needs while the
  server is down. The seat (`crew_seat`, `crew_inbox`) is the model.
- **A feature keeps its data as journal entries wherever it can**
  (configs, reference data, reports, lists, state): a kind of its own and,
  where needed, a marker line first (`report:: <type> <rel>`). Files are
  for media (images, video, audio, PDFs, zips) and huge text only. Why:
  entries are in memory with the journal, searchable, backed up and shown
  like any entry, where the Reports page read the NAS over NFS and was
  slow. The first instance: docs/design/reports-as-entries.md.
- **`CHANGELOG.md` holds the version, and the deploy gives it**
  (docs/design/version-at-deploy.md). **Never edit CHANGELOG.md**: each
  commit that needs an entry adds one file, `changelog.d/<name>-<slug>.md`
  (`<name>` yours, as in your branch `eng/<name>`; `<slug>` a few lowercase
  words of the change, `[a-z0-9._-]`), its first line the intent, `minor`
  (a feature) or `patch` (fix, polish, internal), then the entry's text
  (`- **web** ...`) as CHANGELOG.md has it; the subject ends `(minor)` or
  `(patch)`. Two branches then never touch one file. **Leave
  `APP_VERSION` alone**: the deploy, in its rebase, numbers each fragment
  above everything deployed so far, puts it on top of CHANGELOG.md as
  `## X.Y.Z — <date>`, deletes it, and writes `APP_VERSION` in
  `lcars-ui/index.html` (the web UI shows it beside the LCARS badge, so a
  stale cached page is visible) and the subject's number. Never pick a
  number yourself; a report before the deploy says "patch, unnumbered",
  after it the number in `[deploy finished]`. Each version it numbers
  becomes a journal entry of kind `release` once the deploy has landed,
  its ids in `[deploy finished]`; a failed write is said there, and
  `scripts/release-import.py --apply` catches it up
  (docs/design/release-entries.md). A review fix edits its
  commit's own fragment. A major is the captain's, by hand. The old
  `## next minor|patch — <date>` placeholder on top of CHANGELOG.md is
  **retired**: still numbered through the transition, never written new.
  `scripts/version-stamp.py` is the deploy's: it runs only inside its rebase.
- Commit style: short imperative summary, e.g.
  `Harden the TODO macro: fprintf+newline to stderr, abort() (I2)`.
- **`TODO.md` is the living backlog** (features, bugs, refactoring ideas) — check it
  when picking a task. Keep it current as part of the task: remove items you
  finish (CHANGELOG records them), add anything new worth tracking.
  It merges with git's `union` driver (`.gitattributes`): when two
  branches add items at the same place, both are kept, with no conflict -
  but their order is not guaranteed, and an edit to one item on both sides
  keeps both versions; read the spot after a rebase, and tidy it if two
  items read wrong together.
  `REFACTORING.md` is a **closed** audit — history and rationale, not a to-do list.
