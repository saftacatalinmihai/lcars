# LCARS Architecture

A single-user Star Trek LCARS-style journal in C11: one SQLite file, an HTTP
API server, and the two pages it serves, the web console
(`lcars-ui/index.html`) and the 3D deck (`lcars-ui/deck.html`); plus
`lcars-cli`, a terminal client of the API. This file is the map; style rules
are in AGENTS.md, agent workflow in CLAUDE.md.

## Builds

| Program | Make target | What it is |
|---|---|---|
| Server | `lcars` (debug + ASan) / `lcars-release` (-O3) | `lcars.c`, one translation unit: `InitDB()` (schema and migration) then `RunHTTPServer()`, forever |
| CLI client | `lcars-cli` | `lcars_cli.c`, a separate program: libcurl only, a client of the HTTP API. The example deployment ran a copied build of it (`~/lcars/lcars-cli/`) until 0.276.2 (retired, and its fallback dropped, in 0.279.2); now the one binary's link |
| One binary | `lcars-one` | The server with the CLI linked in (step 3 of docs/design/open-source-build.md): `lcars.c` with `-DLCARS_ONE_BINARY` and `lcars_cli.c` with `-Dmain=LcarsCliMain`, two objects (`build/one/`) and one link, the host's libraries, the UI from disk. `lcars-one cli ARGS` is `lcars-cli ARGS`, and so is the binary run by the name `lcars-cli` (argv[0], busybox-style). Serving, it makes `<data dir>/bin/lcars-cli`, a symlink to itself, and sets `LCARS_CLI_DIR` to that directory for the chat (unless it is set already; a real file there is left alone). Written to `./lcars-one`, never `./lcars` |
| UI pack | `ui-pack` | `scripts/ui-pack.py` → `build/ui.pack` (step 4): the shipped UI (`git ls-files lcars-ui` minus `test/` and `report/`, from the working tree) in one blob, a text index (path, offset, size, a content hash) then the raw files, 64-byte aligned |
| Embedded UI | `lcars-embed` | `lcars-one` with `-DLCARS_EMBED_UI` (objects in `build/embed/`): the assembler's `.incbin` puts `build/ui.pack` in `.rodata` (`LCARS_UI_PACK` names another), and `/ui/` is served from it when `LCARS_UI_DIR` is not set - the same gzip cache, Range, HEAD and 304 as from disk, Last-Modified the pack's time, an ETag of the content hash. The start log's `UI:` line says which source (every build has it). Written to `./lcars-embed`; the VPS's builds do not embed |
| Release binary | `lcars-static` | `lcars-embed` linked `-static` with `-DLCARS_STATIC` (step 5), in Alpine against musl (CI: `.github/workflows/static.yml`; the VPS has neither docker nor musl), the libraries pkg-config's `--static` list; the packages are in the Makefile's comment. `LCARS_STATIC` adds the CA bundle probe (`lcars_curl_ca.h`: `SSL_CERT_FILE`, else the first of the Debian, Fedora/RHEL, SUSE and Alpine paths, as `CURLOPT_CAINFO` on every curl handle); every other build keeps its libcurl's own default. On musl `pipe2` and `addchdir_np` are used and `addclosefrom_np` is not (it has none): the server's sockets are close-on-exec instead (`SOCK_CLOEXEC`, `accept4`), in every build |

CI: `c-cpp.yml` (on `main`) builds `lcars-release` and `lcars-cli` and asks
a started server `/health`. `static.yml` (on pushes to main, so after every
deploy, and on pull requests) is the only place `lcars-static` is built and
proven: `scripts/release/build.sh` runs `make lcars-static` in
`alpine:3.20` by `docker run` (GitHub's JavaScript actions do not run in an
Alpine `container:` on arm64), then `scripts/release/check.sh` - static per
`file` and `ldd`, the version, `lcars init`, serving it, `/health`, `/ui/`
byte-equal to the source, a gzipped deck.html, `lcars cli` and the
`lcars-cli` symlink - and its `--bare` half in `debian:stable-slim` and
`fedora`. x86_64 and arm64; arm64 is `continue-on-error` (its runners are
free for public repos only, so the private clone's may fail or be absent). `release.yml`, on a
`v*` tag equal to CHANGELOG's top, builds and checks the same, packs
`lcars-X.Y.Z-linux-ARCH.tar.gz` (`scripts/release/package.sh`: the binary,
the `lcars-cli` link, the shipped `scripts/` and `crew/`, README, LICENSE,
THIRD_PARTY_NOTICES.md - it refuses without the last two) and publishes
them with SHA256SUMS, the CHANGELOG entry as the notes.

`make check` is the fastest full-warning compile of the server
(`-fsyntax-only`, nothing written). `lcars-portable` builds the release
binary inside a Debian 12 container (glibc 2.36), for a machine older than
the one building it. `lcars-release` has no CLI in it: `lcars cli` and a
`lcars-cli` name are refused there with a pointer to `lcars-one`. The
version (`lcars version`, the start log) is CHANGELOG's top entry, passed by
every server line as `-DLCARS_VERSION`. The example deployment builds on its
own box ("Building on the VPS").

**The raylib desktop app was removed in 0.175.0**, with everything only it
used: the window, the hypermedia documents that declared its UI (`pages/`),
its editor, its remote-database client, its Emscripten web build, hot reload,
and CI's xvfb smoke-run (CI now builds and starts the server). To bring it
back, start from commit `04872fd` (tag `desktop-raylib-last`), the last one
that has it, and the ARCHITECTURE.md there, which describes it.

## Module map (include order ≈ dependency order)

Everything is a single-header library: declarations always visible, bodies
under `#ifdef LCARS_IMPLEMENTATION` (`LCARS_HTTP_IMPLEMENTATION` for the
server's own), which `lcars.c` defines.

| File | Role |
|---|---|
| `lcars_base.h` | Tiny base utils (`GetTimeSeconds`) |
| `lcars_arena.h` | Fixed-size bump arenas. `arena_alloc`/`arena_realloc`/`arena_reset`. OOM = log + `abort()`, deliberately — every arena is a pre-sized budget |
| `lcars_config.h` | Start-up configuration: `LCARS_VERSION_STRING` (CHANGELOG's top entry, `-DLCARS_VERSION` from the Makefile), `LoadEnvFile` (the data directory's `lcars.env`) and `RunInit` (`lcars init`) |
| `lcars_db.h` | The schema: `InitDB` creates `entries` and migrates an older file (`EnsureEntryColumn`); where the file is (`SetLcarsDBPath`/`LcarsDBPath()`, set once in `main`). It plants no row: a new journal is empty |
| `lcars_json.h` | String-aware JSON scanner (spans, not a tree), `json_unescape`, `json_escape_byte` (the one table every JSON writer escapes through), `JSONBuf` (the one growable buffer: overflow-to-500 in the server, abort when full in the CLI) and `base64_encode`. Shared by the server and `lcars_cli.h`, so it depends on nothing but the arena |
| `lcars_http.h` | HTTP API server (raw sockets, Basic auth, tiny JSON helpers). A thread and a 1MB on-stack arena per connection, HTTP/1.1 keep-alive, and read timeouts on every socket |
| `lcars_chat.h` | `POST /chat`: runs `claude -p` (Sonnet, lcars skill, `lcars-cli`-only Bash) as a subprocess and relays its stream-json as Server-Sent Events. A module of `lcars_http.h`, like CalDAV |
| `lcars_engineer.h` | `/engineer/...`: the deck's engineers — crew promoted to Claude Code sessions that change LCARS itself, each in its own git worktree. A thin, heavily gated layer over `scripts/engineer.py`. A module of `lcars_http.h` |
| `lcars_logins.h` | The limited logins: Number One's (`LCARS_NO1_USER`/`LCARS_NO1_PASS`, kinds `no1_*`/`task_no1`) and the scheduled crew roles' (`LCARS_CREW_USER`/`LCARS_CREW_PASS`, kinds `crew_*`/`task_crew`). Each reads everything and writes only its own kinds; `LimitedAllowed` runs before the router for a request that carried one. The third, the steward's (`LCARS_STEWARD_USER`/`LCARS_STEWARD_PASS`, the crew notes' runner), owns no kinds: it creates the captain's kinds, appends to the captain's rows (`POST /entries/<id>/append`), sets their titles (`POST /entries/<id>/title`), closes an open one (`POST /entries/<id>/end`), and (0.230.0) PATCHes, DELETEs and restores (PATCH `deleted: 0`) the captain's rows only with `if_modified` - never PUT, never `deleted: 1` by PATCH, never into or on another login's or an import's kind (`StewardAllowed`). A module of `lcars_http.h` |
| `lcars_embed.h` | Every entry as a vector: an indexer thread keeps the `entry_embeddings` side table current through any OpenAI-compatible `/v1/embeddings` endpoint (by default `lcars-embed.service`, a local llama-server), and `GET /embeddings` / `POST /embed` serve them to the web UI's star chart. A module of `lcars_http.h` |
| `lcars_say.h` | `POST /say`: text to speech for the deck's crew, relayed from Deepgram Aura-2 (the default) or ElevenLabs over curl and streamed back as chunked `audio/mpeg`; `GET /say` names the provider; `GET /say/token` mints a short-lived Deepgram key for the page's own listening socket; `POST /transcribe`, a voice note relayed to Deepgram's `/v1/listen`. A module of `lcars_http.h` |
| `lcars_media.h` | Photos/video/audio attached to entries: `POST /entries/<id>/media` streams the raw file under the media root (`$LCARS_MEDIA_ROOT`, a NAS mount here; unset, `<data dir>/media`, `MediaDefaultRoot`), `entry_media` side table holds the relative path. A module of `lcars_http.h`, dispatched before the body read |
| `lcars_ui_files.h` | `GET /ui/...`: the web UI's files from `$LCARS_UI_DIR`, and `index.html` for any page path (`/ui/tasks`, `/ui/entry/123`). A module of `lcars_http.h`, after `lcars_media.h`, whose loopback test and file sender it uses |
| `lcars_events.h` | `GET /events`: a thread watching the database file's change counter, and the SSE streams that announce it. A module of `lcars_http.h`, after `lcars_chat.h` |
| `lcars_metrics.h` | `GET /metrics`: the latest reading of each kind (by the web UI's `reading()` rule), when it was measured, and live entries per kind, as Prometheus gauges for the Grafana Alloy on the VPS (`scripts/metrics-setup.sh`). A module of `lcars_http.h` |
| `lcars_kinds.h` | Kinds by role (docs/design/kinds.md): the role table (`g_kind_roles`, each role's default kind), the mapping read from the journal's `settings` entry titled `kinds` on every use, `GET`/`PUT /kinds/roles`, and `KindIsAppOwn` (the kinds no role may take). A module of `lcars_http.h`, ahead of the modules that read a role |
| `lcars_features.h` | `GET /features`: each feature on or off and, when off, the names of the settings (or programs) it lacks, with the note the web UI shows at its door - getenv, stat and access(2) only, embeddings from the indexer's last answer (`g_embed_answering`, asked once at start). The owner's login only. A module of `lcars_http.h` |
| `lcars_caldav.h` | CalDAV (RFC 4791) VTODO lists, one per task kind (`task`, `task_*`), so Apple Reminders syncs against the journal DB, due dates included. A module of `lcars_http.h` (included from inside its implementation block), not a standalone header |
| `lcars.c` | The server's `main()`: arguments (`--port`, `--user`, `--password`; `--http-only` is accepted and ignored), `InitDB`, `RunHTTPServer` |
| `lcars_cli.h` | The terminal client's library half: the API requests, the table/JSON renderers, `$EDITOR` plumbing. Includes only `lcars_arena.h`, `lcars_json.h` and libcurl |
| `lcars_cli.c` | `lcars-cli`'s host: argument parsing, the command table, `main()`. Not part of the server's TU |
| `lcars_logseq.h` | The Logseq bridge, `lcars-cli`'s other half: Logseq's local HTTP API, the block/markdown reader, the `HH:MM [kind]` journal-line codec, and the import/export loops. Included from `lcars_cli.c` after `lcars_cli.h`, whose arena, JSON scanner and entry backends it builds on |
| `lcars_strava.h` | The Strava bridge, `lcars-cli`'s third half: the OAuth grant and token file (`~/.lcars-strava/token.json`), the activity list and detail, and the pull that makes each activity a `workout` entry. Included from `lcars_cli.c` after `lcars_logseq.h`, on the same `lcars_cli.h` backends |

## The database

Single SQLite file, `lcars.db` in the server's working directory unless
told otherwise. The path is resolved once in `main`, before any thread, by
`SetLcarsDBPath` (`lcars_db.h`) and read through `LcarsDBPath()` by every
opener; the first given wins: `--db FILE`, `--data DIR` (`DIR/lcars.db`),
`$LCARS_DB_PATH`, `$LCARS_DATA_DIR`, else the relative `lcars.db` - byte
for byte the old compiled-in default, which the live unit relies on (it
sets none of them). `--data` must exist and is never `chdir`'d into. A
wrong path would not fail - sqlite makes the file and `InitDB` seeds a new
journal - so the start log names it: `Database: /abs/path/lcars.db
(existing, N entries)`, or `(NEW: created just now, 1 entries)`; and
`vps-rebuild.sh` compares the live count across a restart (below).

Before the path is resolved, `main` reads the data directory's
`lcars.env` (`--data`, else `$LCARS_DATA_DIR`, else the working directory;
`LoadEnvFile` in `lcars_config.h`), if there is one: `KEY=value` lines with
the environment's names, comments, blank lines, `export` and one pair of
quotes allowed, no inline comments or expansion - a subset bash's `source`
and systemd's `EnvironmentFile` both read. Each key not already in the
environment is `setenv`'d, so the real environment wins, and every
`getenv` in the server and every child it spawns sees the file as it sees
the unit's `~/.env`; `LCARS_DATA_DIR` inside it is ignored, `LCARS_DB_PATH`
honoured. The live checkout has no `lcars.env` (and `.gitignore` keeps one
out of git). The start log's first lines say what happened:

```
LCARS 0.261.0
Config: no lcars.env in /srv/lcars (the environment only)
Database: /srv/lcars/lcars.db (existing, 8234 entries)
```

or `Config: read /data/lcars.env: 5 set, 0 already in the environment, 0
skipped`. `lcars init DIR [--port N] [--user U]` makes such a directory -
`DIR` (700), `DIR/media`, `DIR/lcars.env` (600: a generated password,
`LCARS_PORT`, `LCARS_BIND=127.0.0.1`, `LCARS_MEDIA_ROOT=DIR/media`, every
feature's key commented with what it is for) and a journal through
`InitDB` - and prints the URL and the login; run again it writes nothing
and says what it left alone. `$LCARS_PORT` is the port when `--port` is
not given. `lcars version`/`--version` print the version.

One table:

```sql
entries(id INTEGER PK AUTOINCREMENT, kind TEXT, title TEXT, content TEXT,
        value_int INTEGER, value_float REAL, value_blob BLOB,
        done_bool INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
        created_at_utc TEXT, last_modified_at_utc TEXT,
        start_date TEXT DEFAULT '', end_date TEXT DEFAULT '')
```

`start_date`/`end_date` are **scheduling**, and deliberately not the two stamps
above them: those say when the row was touched, these say what span of time it
is *for*. Same `'YYYY-MM-DD HH:MM:SS'` UTC text, so they compare, range-filter
and order the same way (a zoned ISO 8601 stamp written to any of the four is
converted to it on the way in: `ParseZonedTimestamp` in `lcars_http.h`, plain
day arithmetic, no `$TZ` on a connection thread); `''` means unscheduled, which is what every entry is
until something says otherwise — nothing in this codebase ever defaults them.
They are what the web UI's day view draws blocks from, and what a drag in that
view writes (`lcars-ui/index.html`, `calMoveField`); a drag on any other scale
still moves `created_at_utc`, which is what "put this entry on that day" has
always meant in the month grid.

They arrived after the table did, so `InitDB` carries the repo's only schema
migration: `EnsureEntryColumn` (`lcars_db.h`), a `PRAGMA table_info` scan and an
`ALTER TABLE ... ADD COLUMN` when absent. `CREATE TABLE IF NOT EXISTS` is a
no-op against a database that already has the table, so without it the live
journal would never have seen the columns. A new file holds no row: every
kind is the owner's to name (`lcars_kinds.h`, docs/design/kinds.md), so
there is none a seed could take.

Deletes are soft (`deleted=1`), with one exception: `scripts/db-prune.py`
(Deployment & ops) removes `crew_inbox` rows done and untouched for seven
days, weekly. `kind` partitions entries into lists (a new entry's kind:
the `log` role's, `personal_log` by default; "Kinds by role" below). Side
tables (`entry_media`, `entry_embeddings`, the CalDAV state) belong to the
module that owns them and are created by it.

### Kinds by role (`lcars_kinds.h`, docs/design/kinds.md)

No kind name is the code's to choose: a feature that needs one (where the
nap chip writes, what CalDAV publishes, where a Strava workout lands)
names a **role**, and the journal's owner says which kind each role is.
The captain's journal keeps the names it always had; no row is ever
renamed for a mapping.

- **The roles** (`g_kind_roles`, each with its default): `log`
  (`personal_log`: a new entry, the calendar's, quick capture, the
  computer's, the outbox's fallback, the shortcuts and the glasses),
  `work_log` (a second log read as the first: read-aloud's date, the
  linker), `task` (CalDAV's root list and its `<task>_<list>` lists, the
  Task button; the limited logins' reminders are `<task>_<owner>`),
  `sleep`, `child_sleep` (the nap chip), `child_vocab`, `drive`, `trip`
  (the courses), `workout` (Strava), `counter`, `share`, `page`, `person`,
  `project`, `meeting`, `template`, `logseq_journal` (the import's days),
  and `imported`, a list (the kinds only an import writes, frozen for the
  crew). Each also takes a **name**, the words a feature says for it:
  only `child_sleep`'s is read, as the nap chip's "<name>'s nap" and the
  name a sentence and the voice order match ("the nap" with none).
- **The mapping** is the journal's one `settings` entry titled `kinds`
  (the lowest live id): `{"v":1,"roles":{"child_sleep":{"kind":"naps",
  "name":"Ada"},"imported":{"kind":"a_journal,b_journal"}}}`. A role it
  does not name is its default. It follows the journal (a copy, a backup,
  `db-swap`'s personal copy), and is read on every use, never cached by
  the server: `KindFor(db, role, …)` for the C code (CalDAV's task kind,
  `$LCARS_TASK_KIND` still winning where a box sets it; the logins'
  `<task>_<owner>` and the steward's frozen imports; the computer's
  prompts; the Strava pull), `GET /kinds/roles` for everyone else, every
  role with its kind, default, set or not, name and live rows. `PUT` is
  the owner's alone; no limited login may write a `settings` entry titled
  `kinds`, so no crew role can redirect the captain's rows.
- **The page** (`kindOf(role)`, `kindsOf`, `roleName`) asks
  `GET /kinds/roles` once a boot beside `/features`, keeps the answer per
  server in localStorage (the first paint, offline) and uses `KIND_ROLES`,
  its copy of the C table (the behaviour suite holds the two equal),
  before any answer. Config's **Kinds** section edits it a role a row,
  saved as it changes; "computer, the kinds by role" opens it, "set the
  kind for the child's sleep to naps" sets one.
- **The crew** (`scripts/lcars_roles.py`, its own copy of the table, held
  equal by test_crew.py) ask once a run: crew_tool.py and crew.py over
  HTTP, lcars_linker.py through `lcars-cli roles --json`; the defaults
  when nothing answers. crew/*.md name roles as `<kind:log>` and
  `<kinds:imported>`, filled in at the run (`crew_tool.fill_kinds`), as
  is crew.py's never-write list (`never_write`). `lcars-cli roles` lists,
  sets and resets them; the Logseq import and the Strava pull ask for
  theirs.
- **Conventions**, beside the roles: in the stats view a kind ending
  `_sleep` (or `sleep`) is a sleeper, `drive|drives|trip|trips` a drive,
  one holding `vocab` a vocabulary, `person|people|contact` a person - so
  a second sleeper kind shows with no role of its own - and the roles'
  kinds count too, whatever they are named. A log role's row titled
  "gym" is a gym session (`is_gym`).
- **The app's own kinds are not roles**: `settings` (it holds the
  mapping), `space` and `holo_program` (the deck's), and the logins'
  namespaces `crew_*` and `no1_*` (`crew_note`, `crew_seat`,
  `crew_inbox`, `crew_shares`, `no1_log`, ...). They are the app's
  protocol, as a table name is, and a mapping onto a login's kind would
  hand it the owner's rows: `PUT` refuses a role pointed at one.
- **Tests**: `test/kinds.py` (the route, the server following the roles,
  `lcars-cli roles`); the behaviour suite's fake API answers from the
  journal's own `kinds` entry or `$LCARS_TEST_KINDS` (a mapping file), and
  the crew's tests take `$LCARS_KINDS_FILE`, so either runs on a set
  mapping as on the defaults.

## HTTP API

Runs in the foreground of `lcars`.
Port 8080 by default, on every interface unless `LCARS_BIND` names one
(an IPv4 address; one that does not parse refuses to start rather than
listening everywhere). Each request is logged with its socket peer, plus
`X-Forwarded-For` and `Tailscale-User-Login` when present — for reading only:
anyone can send those headers, so nothing decides anything on them. Basic auth: `--user`/`--password` flags or
`LCARS_AUTH_USER`/`LCARS_AUTH_PASS` env, falling back to `admin`/`admin`.

| Route | What it does |
|---|---|
| `GET /` | Route index (self-documenting JSON: every route and every filter name) |
| `GET /health` | `{"status":"ok"}` — **the one unauthenticated route**, so monitoring needs no credentials. It touches nothing but the socket |
| `GET /entries` | Filtered list (below) as a JSON array |
| `POST /entries` | Create. JSON body (`kind`, `title`, `content`, `value_int`, `value_float`, `done_bool`, `start_date`, `end_date`) or a plain-text body, which becomes the content. `created_at_utc`/`last_modified_at_utc` may be given to backdate a row — that is what lets an importer replay history (see the Logseq bridge below); a malformed one is a 400 rather than a silent "now". Every written stamp (these two and `start_date`/`end_date`, here and on `PUT`/`PATCH`) takes `YYYY-MM-DD` (midnight), `YYYY-MM-DD HH:MM:SS` in UTC, or ISO 8601 with a zone, `YYYY-MM-DDTHH:MM:SS[.fff]` then `Z` or `±HH:MM` (an Apple Shortcut's "ISO 8601" format, in the phone's local time): the fraction is dropped and the offset converted, so the column stays UTC `YYYY-MM-DD HH:MM:SS`. A `T` stamp without a zone is a 400, not a guess. `lcars-ui/test/api.py` covers it. An `Idempotency-Key` header (8-64 of `[A-Za-z0-9_-]`) names the create: a repeat is answered `{id, replayed: true}` with the row it already made (the last 256 keys, in memory; see "Creates are idempotent" below). A keyless create whose body is byte for byte one the same login (the `Authorization` value) had inserted less than 2s ago is answered with that first row - the same 200 and body, plus `X-LCARS-Deduped: 1` - and nothing is inserted: the quick-capture Shortcut's twins. The window runs from the first insert; after it the same body is a new entry. `lcars-ui/test/dedupe.py` covers both |
| `GET /entries/<id>` | One entry, soft-deleted ones included (a client that named an id wants "deleted", not 404) |
| `PUT`/`PATCH` `/entries/<id>` | Partial update — only the fields the body mentions. Both verbs behave identically: a `PUT` carrying just `content` must not blank the title. `{"deleted": 0}` restores a soft-deleted entry. `created_at_utc` is settable (so a bad import can be corrected); `last_modified_at_utc` deliberately is not — the same statement stamps it. `start_date`/`end_date` accept `""`, which is how an entry is *un*scheduled — the only field group where an empty string is a value rather than "the client said nothing". An optional `if_modified` (0.230.0; the steward must send it) is the row's `last_modified_at_utc` as read, compared in the UPDATE's own WHERE: **412** when the row moved, **409** when it is deleted (a restore, `deleted: 0`: when it is live), 404 for none |
| `DELETE /entries/<id>` | Soft delete (`deleted = 1`); 404 when there is no live row. A JSON body's `if_modified` (0.230.0, the steward's) guards it as PATCH's: 412 moved, 409 deleted already |
| `POST /entries/<id>/append` | `{text, if_modified}`: the text added at the end of the content, nothing else touched; `if_modified` (required) is the row's `last_modified_at_utc` as read, compared in the UPDATE itself, so a row changed since is a **412** (the API's one compare-and-set). 409 for a deleted row, 413 past 16KB. Made for the steward login (crew notes), which may change nothing else; the main login may use it too |
| `POST /entries/<id>/title` | `{title, if_modified}`: the title set and `last_modified_at_utc` moved, nothing else touched; `if_modified` (required) compared in the UPDATE itself as append's is (**412** when the row moved), the read of the old title and the UPDATE in one IMMEDIATE transaction. Answers the row plus `old_title`, for Undo. 409 for a deleted row, 404 for none, 400 for a blank title, one over two lines or over 511 bytes (what PUT's buffer keeps). The first of the steward's two changes to an existing row (yeoman titles, crew notes); the main login may use it too |
| `POST /entries/<id>/end` | `{end, if_modified}`: an open entry closed - `end_date` set on a row with a start and no end, `last_modified_at_utc` moved, nothing else touched (0.227.0). `end` is UTC in any stored shape (`NormalizeStoredTimestamp`); `if_modified` as title's, in one IMMEDIATE transaction. Answers the row plus `old_end_date` (""), for Undo. **412** when the row moved; **409** deleted or already ended (an end is set once, never moved); 404 for none; 400 for a bad stamp, no start, or an end not after the start. The steward's second change to a row (the crew closing the captain's sleep or drive); the main login may use it too |
| `DELETE /entries/<id>` | Soft delete (`deleted = 1`), same as the UI. There is deliberately **no hard-delete route** — this DB is a personal journal, and the PUT above is the undo. The one hard delete is a script, not a route: `scripts/db-prune.py` (Deployment & ops) |
| `GET`/`POST` `/entries/<id>/media` | An entry's attachments (photos, video, audio — or any other file), or add one: the body is the **raw file**, streamed to the NAS, with its `Content-Type` and `?name=<original filename>`. Audio and video may add `&cut=<ms>` to keep only the first `<ms>` (dictation, below). Answers the stored row `{id, entry_id, path, mime, bytes, name, created_at_utc}`. See "Media" below |
| `GET /media` | Every live attachment of every live entry, one array of the same rows as above — what the web UI's media view draws. Built in the connection arena, so a few thousand rows before it would want paging |
| `GET`/`PUT` `/entries/<id>/caldav` | A task's CalDAV side as JSON: `{task_kind, list, list_kind, synced, href, uid, etag, extra_ical, extra_vcal, ics}` — the kept lines and the whole VTODO a client would GET. `PUT {extra_ical, etag?}` replaces the kept lines after checking them (see "CalDAV") and stamps the row. What the web UI's reminders panel reads and writes |
| `DELETE /entries/<id>/media/<media_id>` | Soft delete of one attachment; the file stays on the NAS |
| `GET`/`HEAD` `/media/<path>` | The file at a row's `path`, with Range requests — from the VPS's disk cache when it holds a copy, else the NAS. No auth from loopback (tailscale serve's proxy). See "Media" below |
| `GET /reports` | The hosted reports `scripts/report.py` published, newest first: `[{path, title, type, bytes, published_utc}]`, from a walk of `<root>/media/reports/` (no table). 503 when the NAS is not mounted. See "Reports" under "Media" |
| `POST /transcribe` | Speech to text. The body is **raw audio, not JSON**: 16 kHz mono signed 16-bit little-endian PCM. Answers `{"text":…,"bytes":…,"duration_ms":…}`, relayed to Deepgram. 503 with no `DEEPGRAM_API_KEY`, 502 if Deepgram fails |
| `GET /embeddings` | Every live entry's vector, `{model, dim, live, done, rows:[[id, base64 int8]], mark}`, streamed and gzipped; `?since=<mark>` for what was embedded since. `live`/`done` are the indexer's progress. See "Embeddings" below |
| `POST /embed` | One text's vector, same encoding: body `{text}`. What a search by meaning compares against. 503 when the embedding service is off or unreachable |
| `GET`/`POST` `/say` | Text to speech for the deck's crew. `POST {text, voice, format?}` (text up to 2000 bytes, `voice` the provider's name for one) answers `audio/mpeg`, chunked, as the provider makes it, or with `format: "pcm"` raw 16-bit mono 24kHz PCM (`audio/L16;rate=24000;channels=1`); `GET` answers `{provider}`. 503 with no voice configured, 502 when the provider refuses (its message quoted) or cannot be reached. Not for the limited logins. See "Voice for the crew" below |
| `GET /say/token` | A Deepgram key good for about 30 seconds, `{access_token, expires_in}`, minted per request with `/v1/auth/grant` from the server's `DEEPGRAM_API_KEY` (which needs the Member role or above), for the deck's and the console's listening sockets (push-to-talk, conversation, dictation). 503 with no key, 502 when Deepgram refuses or cannot be reached. Refused to the limited logins. See "Voice for the crew" below |
| `GET`/`POST` `/engineer/...` | The deck's engineers: list, poll (status, dialog, transcript since a byte offset), start, say, key, stop, dismiss, recall, deploy, rollback, model (`{model}`: sonnet/haiku/opus/fable, the session restarted on it - at once if idle, at the turn's end if working, at the next start if off; the poll and list say `model`, `model_pending`, `model_used`, and `effort`/`effort_pending`, set by `engineer.py effort` only, no route). Off unless `LCARS_ENGINEER=1`; tailnet only, with a key of its own. See "Engineers" under "Chat" |
| `POST /ask` | The same agent for a voice client (the `LCARS Computer` Shortcut): body as `/chat`, answers one JSON `{text, session_id, error?}` worded to be spoken. See "Voice" under "Chat" |
| `POST /chat` | Ask Claude about the journal, streamed. Body `{session_id?, model?, local_time?, message}`; answers `text/event-stream`, one `data:` event per claude stream-json line, then `{"type":"lcars_exit",…}`. See "Chat" below |
| `POST /tapes/<token>` | One slice of a recording still under way (`?off=<bytes>`, raw body; answers `{size}`, a gap is a 409 with the size held). `POST /entries/<id>/media?tape=<token>` with no body attaches what was staged. See "Media" below |
| `GET`/`HEAD` `/ui/...` | The web UI (`lcars-ui/`), and the app itself for any page path — see "Pages". No auth from loopback |
| `GET /events` | Server push: `text/event-stream`, `data: {"seq":N}` on connect and whenever the database changes, by any writer. See "Server push" |
| `GET /metrics` | Prometheus text format: `lcars_reading{kind}`, `lcars_reading_timestamp_seconds{kind}`, `lcars_entries_total{kind}` (see `lcars_metrics.h`). No auth from loopback (Alloy on the box), Basic auth from anywhere else |
| `GET /maps` | `{mapy_key}` from `$LCARS_MAPY_KEY` (or `null`): the key the web UI's course planner calls Mapy.com with. See "Plot a course" |
| `GET /features` | `{features:[{name,on,needs,note}]}`: media, media_ffmpeg, computer, navigator, maps, transcription, speech, embeddings, caldav, strava, logseq, engineers, number_one, crew, reports. `needs` names what an off one lacks, never a value; the page's one source for what is off (docs/design/open-source.md 2a). The owner's login only: a limited login gets 403 |
| `GET /dump` | Every row matching the `/entries` filters (plus `order`/`dir`/`content=0`) in **one streamed response**, gzipped when the client offers it. No `limit`/`offset` — those are a 400, since a client that sent them meant a page. What the web UI's cold load and boot sync ask for |
| `GET /kinds` | Distinct kinds with `count` and newest `last_modified_at_utc` (`?deleted=1` to count deleted rows too) |
| `GET /kinds/roles` | Each role's kind (`lcars_kinds.h`): `{roles:[{role,what,kind,kinds,default,list,set,name,rows}],entry,error}`. `PUT` `{<role>:{kind,name}\|null}` sets them, the owner's login only (400 on a bad kind, nothing written; 409 when the entry is not JSON) |
| `GET /stats` | Totals — count, distinct kinds, done, content bytes, oldest/newest. Accepts the same filters as `/entries`, so it is also "how many rows does this query have" |
| `OPTIONS *` | CORS preflight (allows `*`), plus the `DAV:`/`Allow:` headers a CalDAV client probes for. Unauthenticated, like `/health` |
| `/.well-known/caldav`, `/caldav/**` | The CalDAV surface (below). WebDAV methods anywhere — `PROPFIND /` included — route there too |
| anything else | 404 / 405, as JSON |

`GET /entries` (and `/stats`) filters, all optional and combinable:

`kind=<exact>`, `q=<substring of title or content>` (LIKE wildcards in the term
are escaped, so `%` means a percent sign), `date=YYYY-MM-DD`,
`since=`/`until=` on `created_at_utc`, `modified_since=`/`modified_until=` on
`last_modified_at_utc` (each takes `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC; a bare
date used as an upper bound widens to the end of that day. Not the zoned
ISO shape the writes take: an unescaped `+` in a query string is a space), `done=0|1`,
`deleted=0|1|all` (**default `0`** — the list excludes soft-deleted entries,
matching the UI; the old behaviour is `deleted=all`), `min_id=`/`max_id=`,
`scheduled=0|1` ("has a `start_date` at all"), `scheduled_since=`/
`scheduled_until=` on `start_date`, `scheduled_date=YYYY-MM-DD` — which is an
*overlap* test rather than an equality one, so a block running 23:00 to 01:00
is returned for both of the days it touches —
`order=id|created|modified|title|kind|start|end` + `dir=asc|desc` (default
`id desc`; note `''` sorts before every real stamp, so an ascending `start`
leads with everything unscheduled),
`limit=` (default 200, max 1000) + `offset=`, and `content=0` to omit entry
bodies from the rows (`content_length` is always there).

Every value the client sends is a **bound parameter**; the only pieces of SQL
built from a request are the fixed clause literals and an `ORDER BY` matched
against a table of allowed column names.

Errors are JSON (`{"error":…,"status":…}`). A filter the server can't honour is
a 400 rather than being ignored — silently dropping `?kind=…` would answer with
rows the client explicitly excluded.

Each connection is served on **its own detached thread**, with a 1MB arena on
that thread's stack (reset between requests, not rebuilt) and its own SQLite
connection (2s busy timeout, so an API write racing the UI's debounced save
waits its turn instead of failing). Consequences of that arena worth knowing,
both handled rather than left to abort: a `Content-Length` over 512KB is refused
with 413 before it ever reaches `arena_alloc`, and a response that would outgrow
the arena mid-build comes back as a 500 telling the client to narrow the query
(`limit`/`offset`/`content=0`) instead of as truncated JSON.

**Compression.** Nothing between the server and a phone compresses —
`tailscale serve` proxies bytes as they come — and journal JSON gzips to a
third of its size, so the server does it itself: any `application/json`
response of 1KB or more goes out gzipped when the request's `Accept-Encoding`
offers it (CalDAV's XML/iCalendar never does). Compressed bodies use
`Transfer-Encoding: chunked`, because the compressed size is not known until
the last byte and buffering it would need a second arena-sized buffer.
Chunked framing keeps keep-alive intact. zlib's ~260KB of deflate state is
allocated from an arena on the sending frame's stack (`HTTPZAlloc`), so there
is still no malloc on the request path. `GET /dump` uses the same stream
(`HTTPBodyStream`) with the rows as its producer, building each row's JSON at
an `arena_mark` and releasing it after the write, which is what lets one
response carry more than the 1MB arena. A failure after the 200 has gone out
omits the terminating chunk and closes the connection, so a client sees a
truncated transfer rather than half a JSON array. Level 5: the whole journal
(4.8MB) is ~1.5MB on the wire and ~200ms of the VPS's one core, overlapped with
sending it.

The web UI's own files are gzipped too (`lcars_ui_files.h`, 0.255.0): html,
js, mjs, css, json, webmanifest, svg, txt, md, wasm, gltf and glb (the
meshopt-packed glbs still lose ~44%), never the images, fonts or audio,
which gain nothing. Never for a `Range` request (the update check's ranged
GET of index.html must stay an identity 206) or a HEAD, and every `/ui/`
answer, a 304 included, says `Vary: Accept-Encoding`; there is no ETag,
Last-Modified is the file's in either form. Compressing index.html takes
~70-100ms and deck.html ~30ms, on every console load and deck boot, so a
file of 32KB or more is compressed once into a fixed region mapped at
startup (`LCARS_UI_GZ_BYTES`, default 16MB, 0 for none) and sent from there
with a Content-Length (<1ms); a smaller one is compressed as it is sent,
chunked. The cache is keyed by the file's device, inode, size, mtime and
ctime read from the fd being sent, so a file saved under `lcars-ui/` is a
miss on its next request: chosen over precompressed `.gz` files, which go
stale with the live, no-build edit and whose "newer than the source" mtime
test `cp -p` or a checkout of an old file can fool. A file changed while it
is read is not cached, and when streamed is cut off rather than sent mixed.
A deck cold boot moves 3.7MB instead of 5.8MB (deck-pipeline.md, "Measured:
gzip for the web UI's files").

Two rules keep one client from stalling the others:

- **`recv()` has no timeout of its own**, and browsers open speculative
  preconnects that connect and say nothing. Every socket carries
  `SO_RCVTIMEO`/`SO_SNDTIMEO`, on a two-tier budget: a connection that has never
  carried a request gets `HTTP_CONNECT_TIMEOUT_SECONDS` (5s — a preconnect until
  proven otherwise, and it occupies a concurrency slot meanwhile), one that has
  gets `HTTP_IDLE_TIMEOUT_SECONDS` (15s, because sitting idle between requests
  is what keep-alive is *for*), and anything mid-request gets
  `HTTP_IO_TIMEOUT_SECONDS`.
- **Every response says `Connection`.** HTTP/1.1 says a connection
  persists unless told otherwise, so a server that closes silently has
  clients reusing dead sockets. Responses carry
  `Connection: keep-alive` (plus `Keep-Alive: timeout=15`) or
  `Connection: close`, and the server means it.

Keep-alive is what makes the header true: `HandleHTTPConnection` loops over
`ServeHTTPRequest`, carrying any bytes read past one request's body forward as
the start of the next (so pipelined requests work), up to
`HTTP_MAX_REQUESTS_PER_CONNECTION`. The invariant that makes it safe is that
**`g_conn_keep_alive` is false until the body has actually been taken off the
wire** — every early exit (`OPTIONS`, `/health`, 401, 413) answers without
reading it, and those undrained bytes would otherwise be parsed as the next
request. It cannot be a flag each early exit sets for itself, because
`CheckHTTPAuth` sends its own 401 before returning.

Concurrency is capped at `HTTP_MAX_CONCURRENT_CONNECTIONS` (64). With every
slot taken, the longest-idle connection (a keep-alive between requests, a
preconnect yet to speak) is shut down and its slot handed to the new one once
its thread has let go (`HTTPSlotAcquire`); only when every slot is
mid-request is a connection answered 503 (logged, rate limited) and closed
rather than queued, which is what makes the memory ceiling real — each thread
costs `HTTP_THREAD_STACK_BYTES` of address space and up to 1.5MB of touched
stack. `pthread_create` failing falls
back to serving that one connection inline.

Shared state must be ready before the first `accept()` or live per thread:
the credentials are filled in by `EnsureHTTPAuthInit()` up front (two
threads racing a lazy init could compare against a half-copied password),
and CalDAV's scratch arena is on the connection thread's stack (below).

### Server push (`GET /events`, `lcars_events.h`)

The web UI catches up with `deltaSync` (two `/dump` questions and
`/stats`); `/events` tells an open tab when to, whoever wrote: the CLI, a
background Claude, a Shortcut or Reminders.

- **The source is the database file, not the write paths.** A watcher thread
  (started by the first stream) reads the SQLite header's file change counter
  (bytes 24–27; every commit in rollback mode moves it) and the `-wal` file's
  size and mtime once a second. So every writer is covered, this server's
  connections or not, without each one announcing itself.
- **Not through SQLite.** A read-only connection polling `PRAGMA
  data_version` was seen keeping a SHARED lock between polls. In rollback mode (which `lcars.db` is), that
  refuses every other writer with "database is locked".
- **And never `close()`.** Closing any descriptor to a file drops every POSIX
  lock the process holds on it, which would release this server's SQLite
  locks mid-transaction. The watcher's descriptor is opened once and kept; a
  database swapped in place is a new inode, and the old descriptor is leaked.
- **The event says when, not what**: `data: {"seq":N}`, once on connect and
  on every change. The client runs its own `deltaSync`, which already knows
  how to ask and skips dirty rows and rows waiting in the outbox. A `seq`
  that differs from the last one seen on reconnect means changes were missed,
  and the client catches up then too.
- **Each stream is a connection thread and a slot**, so there are at most 8
  (`EVENTS_MAX_STREAMS`), a heartbeat every 15s, and an end at 30 minutes,
  after which the client reconnects. A hidden tab drops its stream.
- In the page ("server push": `evStart`, `pushSync`) it is `fetch()`
  streaming, not `EventSource`, which can send neither Basic auth nor
  `X-LCARS-Client`. A server without the route (404) is not asked again.
  Open views (the task board, the calendar) are not redrawn by a push; the
  list, the reader and the counts are.

### Media (`lcars_media.h`)

Entries carry any number of attachments: photos, video, audio, any other
file. The bytes live under the media root (`$LCARS_MEDIA_ROOT`): a local
directory, or, in the example deployment, a Synology NAS NFS-mounted on
the VPS; the database holds only a path
relative to that root, `media/2026/09/24/e1234-134502-9f3c1a2b.jpg` (UTC
date directories, entry id, time, random suffix, an extension chosen from
the content type), in the side table `entry_media` (created on first use,
like `caldav_tasks`).

- **The path is also the URL.** `GET /media/<path>` (`HandleMediaFile`)
  serves it with Range, `HEAD`, the type from the extension (unknown or
  active types are an `octet-stream` download with `nosniff`). An
  `<img>`/`<video>` cannot send Basic auth, so a request from **loopback**
  — tailscale serve's proxy — needs none; from anywhere else it wants the
  password (a second wall: since 2026-10-18 the port is closed to the
  internet, see "Deployment & ops"). Anything on the tailnet can therefore read
  `/media/`, the same trust boundary as the tailnet itself. Dot-names
  (`.tapes`), `..` and directories are 404s.
- **Recent files are served from the VPS's own disk.** Every byte from the
  NAS comes up the home connection's uplink (~1MB/s cold), so a copy is
  kept in `$LCARS_MEDIA_CACHE` (default `~/.cache/lcars-media`, laid out
  like the root; `0` turns it off): every upload is copied in as it is
  stored, and a file served from the NAS is copied in beside the reply. LRU
  by atime, bounded by `$LCARS_MEDIA_CACHE_MB` (default 4096); a file over a
  quarter of that, or one that would leave under 2GB free, is not cached.
  Evicting is the one place the server deletes a media file.
  `X-LCARS-Media: cache|nas` says which answered.
- **Uploads are streamed, not buffered.** A phone video is hundreds of MB
  against the 1MB connection arena, so the router dispatches `POST
  /entries/<id>/media` *before* `ReadHTTPRequestBody`, and the handler
  copies the socket to `<file>.part` in 256KB chunks, checks `close()`
  (where NFS reports a refused write), renames into place, and only then
  inserts the row. A short body unlinks the partial file. Because the
  handler drains the body, it is also what turns keep-alive back on.
- **A chat's files are media without a row.** `POST /chat/media?name=`
  (`HandleChatMediaUpload`) streams the body the same way (the loop is
  `MediaReceiveBody`, shared), up to `CHAT_MEDIA_MAX_BYTES` (25 MB; a 413
  before the body is read), to `media/chat/YYYY/MM/<slug>-<id>.<ext>`
  beside the reports - the slug report.py's, the extension an entry's
  upload's (`ResolveMediaType`, then `ResolveFileType`), nothing
  converted - and answers `{path, url, name, mime, bytes}` (`url` is
  `/<path>`, for the page's origin). No journal row: the message that
  carries it is the record (see Chat). Served by `GET /media/` like any
  file, cache and all. The limited logins get a 403, as for an entry's
  upload.
  Ceiling: `MEDIA_MAX_BYTES` (1GiB).
- **`<root>/media` must already exist** and is never created: an unmounted
  NAS leaves an empty mount point, and writing there would fill the
  VPS's own disk. Its absence is a 503.
- **Media types are a whitelist** (`g_media_types`), from `Content-Type`,
  else from the original name's extension (Safari sends HEIC and some
  recordings as `application/octet-stream`). **Any other file keeps its
  extension only if it is inert** (`ResolveFileType`): `/media/` shares an
  origin with `/ui/`, so a file served as HTML, SVG or XML would run its
  scripts next to the web UI's `localStorage` — the API password. The
  extension is kept only when `/etc/mime.types` maps it to an inert type;
  everything else lands as `.bin`. The row's `mime` is what the stored file
  is served as, and `name` keeps the original filename for the download.
- **Audio is stored as AAC/MP4 whatever recorded it.** Chromium on Linux
  and Firefox record WebM/Opus without duration or cues, which Safari will
  not play, so `audio/webm`/`audio/ogg` is converted with `ffmpeg`
  (`$LCARS_FFMPEG_BIN`, else PATH) to `.m4a` beside the original, and the
  row records the `.m4a`. A failed conversion stores the upload as it came.
- **Video is only ever remuxed**, every stream copied (`MediaFfmpeg` with
  `g_ffmpeg_*_copy`): re-encoding would hold the VPS's one core longer than
  the recording took. A MediaRecorder WebM is rewritten as `…-remux.webm`,
  and so is a **fragmented MP4** (`MediaIsFragmentedMP4`, a top-level
  `moof`) — what an iPhone records, whose header says 0s and which iOS
  Safari was seen not to play.
- **Recordings stream while they are made** (`tapeFeed` in the page, for
  dictation's tape and the Record button alike), so stopping does not wait
  on the whole file: each second goes to `POST
  /tapes/<token>?off=<bytes>`, appended to `<root>/media/.tapes/<token>`. A
  slice resent from the same `off` overwrites itself, and a gap is a 409.
  The stop sends the last slice and `POST
  /entries/<id>/media?tape=<token>` with no body, which moves the staged
  file into place and carries on as an upload. The token names no entry, so
  an unsaved entry can record too. If any of it fails, the page still holds
  the whole recording and uploads it the old way. A slice is capped at
  384KB (`TAPE_SLICE_MAX`), under the body limit. A tape never attached
  stays in `.tapes`.
- **`?cut=<ms>` trims the order that ended a dictation.** "Computer, pause
  dictation" is acted on only once heard, so it is on the tape; the page
  sends the time from the tape's start to that order's "computer" (exact
  from Deepgram's word timings, `dgClock`; estimated for the browser's
  recogniser, `VBROWSER_LAG`), and the server keeps only that much (an
  ffmpeg `-t`, in the same step as any conversion; an iPhone's AAC is cut by
  stream copy). A stop with no time keeps it all.
- **One microphone capture, cloned.** The page opens it once (`vMicTake`)
  and Deepgram, the tape and Record each take a clone, because iOS keeps one
  capture alive and a second one silenced the recogniser. The browser's own
  recogniser captures internally and cannot share, so beside it the tape
  starts once the recogniser is live and is dropped if they clash. Video
  dictation adds the camera (pictures only) to a clone of the same capture.
- **The server never deletes a file.** Deletes are soft; the NAS is the
  archive, and `UPDATE entry_media SET deleted = 0` is the undo.
- **Entry text can show media** (`mdMedia`): `![alt](src)`, or a link
  whose extension is a picture, video or recording, where `src` is a full
  URL or a path relative to the media root — so the text names no host.
- The service worker stays out of `/media/` and every Range request.

#### Reports

A report is a file Number One or an engineer made for the captain to read —
an HTML page, a PDF, a chart, a CSV, Markdown — handed over as a link.
`scripts/report.py publish FILE [--title T]` copies it into the media
store, `media/reports/YYYY/MM/<slug>-<id>.<ext>` (UTC month, 8 hex of
random), and prints `$LCARS_REPORT_BASE/<path>` (the server's URL, from
the environment or `~/.env`; unset, the path alone, which the console
opens); `report.py list` reads them back. `no1.py report
FILE "<title>"` publishes and logs the link as a `no1_log` entry. Reports
are never committed or left anywhere else on the box.

- **Updated in place**: `report.py update <path> FILE` (`no1.py report
  --update <path> FILE`, which logs "Report updated: <title>") writes over
  a report already in the store, atomically and under the same name, so
  the link handed out shows the new content. The sidecar keeps its title
  and gains `updated_utc`; the server's disk-cache copy, which it would
  otherwise go on serving, is deleted. Anything not a report file under
  `media/reports/` (a sidecar, a symlink, a `..`) is refused.
- **No database row.** The title lives in a hidden sidecar,
  `.<name>.json`, beside the file; `GET /reports` (`HandleReportList`)
  walks the two levels of directories, lists what `GET /media/` would
  serve (no dot-names, no symlinks), newest first by mtime. The sidecar is
  written first and the file copied to a dot-name, synced and renamed, so a
  half-copied report is never listed or served.
- **Refused when not mounted**, as an upload is: `report.py` writes nothing
  when `<root>/media` is missing, and the route answers 503.
- **Read in the browser, not downloaded** (`ReportResolveType`): text of
  any sort (CSV, Markdown, logs) is `text/plain; charset=utf-8`, HTML is
  `text/html` — unlike an attachment, whose HTML is a `.bin` download.
- **Every report but a PDF is sandboxed**: `Content-Security-Policy:
  sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox
  allow-downloads` (`REPORT_CSP`), beside `nosniff`, from the disk cache
  and the NAS alike (the headers are chosen by path, after the open). The
  document gets an opaque origin, so its scripts cannot touch the `/ui/`
  origin's `localStorage` (the API password) though it is served from the
  same host; `allow-same-origin` would undo that and must never be added,
  and forms are left out (a form could post with remembered Basic
  credentials). A PDF goes without: Chromium refuses to start its viewer
  in a sandboxed document, and a PDF's scripts run in the viewer's origin
  anyway. `test/reports.py` proves it in Chromium.
- The web UI's **Reports** page (`openReports`, `./reports`) lists them; a
  tap opens an HTML or text one in the **report viewer** (`reportView`,
  0.198.0), a PDF or anything else in a tab of its own. The viewer is a
  layer of its own (`#rview`, not `#ov`, so it comes back to the page it
  covers) with the report in an iframe sandboxed as the CSP is
  (`allow-scripts allow-popups allow-popups-to-escape-sandbox
  allow-downloads`, never `allow-same-origin`): two layers, so a copy served
  without the header (a cache, a proxy) is still kept from the page's
  origin. It HEADs the file through `api()` first (an iframe fires no
  error), then frames it; a timeout covers a load that never ends. It is a
  history step, `./report/YYYY/MM/<file>`, over the page beneath: Back,
  Close and Escape close it. Any markdown link to `/media/reports/` (chat,
  Number One's entries, crew reports, the reader) carries `data-report` and
  opens it, its href kept for a long-press; a chat message holding one gets
  a card under it (`reportCards`).

### Transcription (`POST /transcribe`, `lcars_say.h`)

Speech-to-text over the API, so anything that can record can write to the
journal by voice. The Even Realities G2 app in `evenhub/` is the reason it
exists — the glasses have a microphone and no keyboard — but nothing about
the route is specific to it. Since 0.176.0 it is Deepgram's: the body is
relayed to the pre-recorded `/v1/listen` (`nova-3`, `smart_format`, so the
text comes punctuated) with the server's `DEEPGRAM_API_KEY`, the one the
crew's voice and the console's dictation already use. Until then it was
Vosk, offline, with a 70MB model beside the binary.

- **No resampling anywhere.** The body is 16 kHz mono s16le, exactly what the
  G2 microphone emits, and goes to Deepgram untouched, its shape named in the
  query (`encoding=linear16&sample_rate=16000&channels=1`), since raw PCM has
  no header to say so.
- **512KB of body is about 16 seconds** at 32,000 bytes a second. That is the
  existing `HTTP_MAX_BODY_BYTES`, not a new limit, and it makes this a voice
  note rather than a dictation session. A client should stop before it, by
  bytes and not only by elapsed time — audio does not always arrive at real
  time.
- **It does not create an entry**, deliberately: transcription and creation stay
  separate so the route composes, so the insert path's backdating and validation
  are not duplicated, and above all so a client can show the user what was heard
  before committing it. `POST /entries` with the returned text is the other half.
- The answer is `{text, bytes, duration_ms}` and nothing else of Deepgram's.
  Silence is a success with an empty string, not an error. A body that is not a
  whole number of 16-bit samples is a 400, and `Content-Type: application/json`
  is a 415 — almost certainly a client that meant to post an entry. No key is
  a 503; Deepgram unreachable, refusing or answering without a transcript is a
  502 that says which.
- **The limited logins may not use it** (403): it spends money, as
  `/say/token` does, and none of them has a microphone.

`test/transcribe.py` runs it against a stand-in Deepgram
(`LCARS_DEEPGRAM_URL`, the base `/v1/listen` is asked at).

### Chat (`POST /chat`)

The web UI's *Ask* panel (`A`, or "computer, ask …") is Claude Code on the
server. `lcars_chat.h` spawns `claude -p --model sonnet --output-format
stream-json --include-partial-messages` per message, writes the message to its
stdin and relays stdout unparsed as SSE, so the page sees tokens as they are
generated. The page reads the stream off `fetch()` (EventSource can neither POST
nor send Basic auth) and renders the text, the tool calls as chips and `#123`
citations as entry links.

- **The agent may run `lcars-cli`, search the web and fetch the weather,
  and nothing else.** `--tools Bash,Skill,WebSearch,WebFetch`,
  `--allowedTools "Skill(lcars)" "Bash(lcars-cli:*)" WebSearch` plus the two
  Open-Meteo `WebFetch(domain:…)` rules, `--permission-mode dontAsk`: every other command (the skill's own `set -a; . ~/.env` setup,
  pipes into python3, `cat`) is denied rather than prompted. The child's
  environment is prepared so that is enough: `lcars-cli`'s directory first on
  `PATH` (`$LCARS_CLI_DIR`, which the one binary sets to `<data dir>/bin`, its
  `lcars-cli` link; default `~/lcars/lcars-cli`), `LCARS_URL` pointing
  back at this server's own port, and the unit's Basic-auth variables. What a
  chat can do is therefore what the API password that reached the route could
  already do. `$LCARS_CHAT=0` turns the route off.
- **Files in a message.** `POST /chat` and `/ask` take `attachments`, a
  list of what `POST /chat/media` answered (`{path, name, mime, bytes}`).
  Each path must be a regular file under `media/chat/`
  (`ChatAttachmentsParse`; anything else, or more than 20, is a 400 before
  claude starts); the size is the file's own, the name is made one line.
  One line per file goes at the head of the message, after the time
  header: `Attached file: <absolute path> (<name>, <mime>, <size>)`; the
  files themselves never go on stdin (`CHAT_MAX_STDIN_BYTES` bounds the
  whole). Files alone are a message. The agent opens them with **Read**,
  allowed as `Read(//<root>/media/chat/**)` (`//` is Claude Code's
  absolute path) and nowhere else; `Read(./**)` is denied, because Read in
  the working directory ($HOME, with `~/.env`) needs no rule even under
  dontAsk. `lcars_chat.h`'s head says why that is safe.
  **The page's side** (0.234.0, "files in a message" in `index.html`):
  `+` before the box (a plain button, not a kept-focus one: iOS opens a
  picker only inside the tap), a paste of a file, or a drop on the full
  view's thread or a dock window (an amber dashed inset naming who it
  goes to; a minimised tab springs open after 600 ms; a drop anywhere
  else is prevented and does nothing). Only where the other side takes
  files (`chatTakesFiles`: not a navigator, not the deck's crew). Each
  file is a chip above the box (`.chfiles`, a row of its own:
  `chatQuotesPaint` repaints `.chquotes` from the box text) and its
  upload starts then (`chatMediaSend`, XHR for `upload.onprogress`); the
  pending files are the thread's `t.att`, the bytes and the upload in
  flight in `chatFileRt` (a WeakMap: never saved). States: up, done,
  failed (Retry), big (over 25 MB, never sent, blocks Send), offline
  (waits in memory for `obBack`/`obTry`: `chatFilesWake`), lost (a reload
  took the bytes). Send with files posts the bubble at once with the
  files' bars and sends when the last is up (`chatFilesWait`); a file
  that cannot go fails the message, its words kept in the bubble with
  Retry. The message's `files` (path, url, name, mime, bytes, w, h,
  state) go to `/chat` as `attachments` (`chatPost`) or to engineer say
  (`engSend`); an engineer's transcript's "Attached file:" lines are read
  back into files (`chatFilesFrom`, in `engFold`). The bubble
  (`chatFilesHtml`, above the words): pictures inline, one at its aspect
  (4:3 until it loads, then kept in `f.w`/`f.h`), two to four a grid of
  squares, more three and a +n; a tap is the lightbox (`mediaLight` with
  a list, ← →); video and audio play; anything else a tile with download
  and a new tab. Every picture has its box before it loads, and its load
  (caught in capture on the log) re-arms a dock window's `dockEnd`.
  `chatMsgKey` holds the files' states and progress. In an answer, a bare
  media path or the page's own media URL on a line by itself is the
  picture (`chatBareMedia`, `mdRender`'s `bare` option, the chats only);
  mid-sentence it stays words, and a stranger's bare URL or a path outside
  the media root is never fetched. A dock window's stream settles a
  finished line holding a picture (`dockLiveCut`), so it is not remade
  every frame.
- **The web: search, and the weather only.** `WebSearch` is allowed
  whole; `WebFetch` only for `api.open-meteo.com` and
  `geocoding-api.open-meteo.com`, and dontAsk denies every other URL. The
  agent reads and writes the journal, so an open fetch would be a way out:
  a page found by a search could tell it to put entries into a URL. A
  search query goes only to the search provider. `$LCARS_CHAT_LOCATION`
  (optional) is added to each message's header as the user's location,
  which is where "the weather" means.
- **The entry editor's Tidy dictation asks it too** (`tidyDictation`, the
  ⋯ sheet, "tidy the dictation"): the open entry's text, under a fixed
  instruction (speech-to-text errors, spelling and punctuation only; facts,
  names, numbers, markdown, links, `@` lines and dates kept), through the
  same `chatPost` in a session no thread keeps. The answer is only shown, as
  a word diff (`tidyDiff`, an LCS over words, spaces and marks); Accept puts
  it in the form and saves it as any edit, as the captain, with an Undo, and
  an entry whose text or `last_modified` moved while it was out has the
  answer discarded - the agent's own `lcars-cli` write would be such a move.
- **The model is picked in the panel** (sonnet by default; haiku, opus,
  fable) and sent as `model`. The server takes only the aliases in
  `g_chat_models` — the value becomes an argv element — and 400s anything
  else. Switching model mid-thread is fine: `--resume` carries the
  conversation, `--model` only decides who answers next.
- **Follow-ups are `--resume <session_id>`**, the id claude reported in its
  first event. Sessions live per working directory, so claude always runs in
  `$LCARS_CHAT_DIR` (default `$HOME`, which also keeps it from loading this
  repo's coding-agent CLAUDE.md).
- **The page sends the time.** `date` is denied and the box's clock is seven
  hours off the user's, so each request carries the browser's wall clock and
  zone, which is prepended to the message.
- **A dropped client kills the run.** The relay polls the socket for
  `POLLRDHUP` and signals claude's whole process group (it is spawned with
  `POSIX_SPAWN_SETPGROUP`), so Stop or a closed tab leaves no orphan `lcars-cli`.
  A 15s SSE heartbeat keeps proxies (tailscale serve) from timing out a silent
  tool call; 10 minutes is the hard ceiling; two chats at once, then 429.
- `claude` is found via `$LCARS_CLAUDE_BIN`, else `~/.local/bin`, the mise
  install, then `/usr/local/bin`/`/usr/bin`, because the systemd unit's PATH
  reaches none of the per-user installs.

**A crew role's chat reads everything, and edits on the captain's word** (0.226.0;
widened 0.229.0, the captain's order of 2026-10-16). The role chat is
this agent with the role's context on its first message
(`crewRoleContext`). It may read the whole journal, any date (`lcars-cli
list` with `--search`, `--since`/`--until`, `--kind`, `--done`; `get`,
`stats`, `kinds`), and search the web (WebSearch, the weather through
Open-Meteo, as the route's own prompt allows). Asked in so many words (a
question only proposes), it may create an entry, append with `lcars-cli
append` (the add-only route, so the captain's text is never resent), and change
any aspect of an entry of theirs with `set <id>` - title, kind, start, end, done,
the values, `--created-at` - or `rm`/`restore` it (soft); their text is
replaced (`set --content`) only for an edit they ask of it, the answer
saying exactly what changed. Every change is named `#id`, what it was and
what it is now, so they can ask for it back; what it adds is marked as the
role's (`> Yeoman created this, <time> (from the chat)`, `> Yeoman added,
<time>:`). Never the crew's, Number One's or the imports' kinds, never a
secret written out. It writes as the captain's login, so the rule is the
words, not a gate: the steward's checks are the notes' alone (whose write
path has the same verbs since 0.230.0, each behind the server's guard).

**Voice (`POST /ask`).** The same agent for a client that speaks instead of
rendering: the `LCARS Computer` Shortcut (`shortcuts/README.md`), on the phone
or the Watch. Same body, same session rules (a run of the Shortcut starts with
no `session_id`, so each is a new conversation; its turns resume one), same
tools and permissions. What differs is in `HandleChat`'s `voice` branch:

- **One JSON answer, not a stream.** Get Contents of URL hands over a whole
  body, so claude runs with `--output-format json` and the server answers
  `{"text", "session_id"}` from its result object. The 200 still goes out at
  once, followed by a space every 15s until the answer — whitespace before a
  JSON value is legal, and it keeps tailscale serve from timing out a silent
  response. So a failure after that is a 200 too: `text` is a spoken apology
  and `error` says why. A Shortcut speaks `text` either way.
- **A prompt for the ear** (`g_chat_voice_prompt_*`): one to three plain
  sentences, no Markdown or ids in brackets, dates said the way a person
  says them, orders acted on without asking, and the whole `lcars-cli`
  command set inline so it never spends a turn loading the skill. It maps
  the web console's voice orders onto `lcars-cli` (logging with the
  `SUMMARY:`/`--- dictation ---` shape, tasks, due dates, scheduling,
  continue/add-to) and says which ones are screens only the console has.
  `--effort low`. A turn measured 5–7s on the VPS, reads and writes alike.
- `lcars-cli` grew what the orders needed: `--start`/`--end`,
  `--scheduled-date`, `HH:MM` timestamps, and `due` — the agent writes
  Reminders' due date and alert the way the page does.

### Engineers (`lcars_engineer.h`, `scripts/engineer.py`)

Anyone in the 3D deck can be promoted to engineer (the talk sheet's
*Promote to engineer*). An engineer is the opposite of the journal chat: not
a locked-down `claude -p` that can only run `lcars-cli`, but an interactive
Claude Code session working on this repository, as the captain would at a
terminal — so a feature can be asked for, built, tried and shipped from the
deck. `lcars_engineer.h` is a thin, gated layer over `scripts/engineer.py`,
which does everything; its comments hold the detail.

- **A session herdr runs, with Remote Control on.** `start` opens a tab in
  herdr's `engineers` workspace running `claude --remote-control "<Name> ·
  <task or rank>" --session-id <uuid>` (`--resume` later). One session is
  then reachable three ways: the deck types into it (`herdr agent prompt`)
  and reads its transcript, the Claude app shows it as a Remote Control
  session, and `herdr` attaches to its terminal. Nothing touches Claude
  Code's internals: `-p` ignores `--remote-control`, and the messages that do
  reach a background session travel over an undocumented socket. The tab
  gets mise's Claude Code first on `PATH`, since the shell would otherwise
  find an older `/usr/bin/claude`.
- **Files for an engineer.** `POST /engineer/<name>/say` takes the chat's
  `attachments` (checked by the same `ChatAttachmentsParse`); with any, the
  route runs `say <name> --json` with `{message, attachments}`, and
  engineer.py types the words, then a line per file: its absolute path on
  this box and its https URL (`report.py`'s root and base), for an
  engineer without the NAS mount to fetch with its API auth.
- **One git worktree per engineer**, `~/lcars-eng/<name>` on `eng/<name>`.
  Their brief (`--append-system-prompt-file`; herdr will not type newlines
  into a shell) forbids touching production's checkout.
- **Dialogs come back to the deck.** Engineers start in the captain's
  normal permission mode, so a step can stop at a question; herdr reports
  the agent `blocked`, the poll carries the screen's text, and the deck
  shows a button per answer. `herdr agent prompt` refuses to type over a
  dialog, so a message is never mistaken for an answer.
- **Deploy is a fixed procedure, only on the captain's word** (the deck's
  *Deploy*, or the engineer running the same script). It waits for the
  engineer's turn to end — never rebasing under one mid-edit — refuses a
  dirty worktree, a question on screen or a dirty `~/lcars`, rebases
  `eng/<name>` onto the live branch (a conflict aborts and names the files),
  runs the web suite if `lcars-ui/` changed, fast-forwards `~/lcars`, runs
  `vps-rebuild.sh` if C changed (resetting `~/lcars` if that fails), records
  `{prev, new}` and pushes. *Roll back* reverts the last deploy's range with
  revert commits and rebuilds if it had C. Both run detached in a transient
  user unit (`systemd-run`), because the rebuild restarts `lcars.service`,
  which kills everything in its cgroup, the asking server's child included;
  that unit starts from systemd's environment, so paths are handed to it.
  A run holds `deploy.lock` while it lives, so one killed mid-way is seen at
  once as failed. Each step is written into the deck's chat, and the outcome
  is typed into the engineer's session (`[deploy finished]`, `[deploy
  failed]`, `[rollback]`) for them to report.
- **Security**: these routes are a shell on the VPS, so the API password is
  not enough. `LCARS_ENGINEER=1`, a loopback peer (tailscale serve; nothing
  off the box reaches them directly), `Tailscale-User-Login` equal to
  `LCARS_ENGINEER_LOGIN` when set, and `X-LCARS-Engineer-Key` equal to
  `LCARS_ENGINEER_KEY` — a second secret the deck keeps in `localStorage`,
  stripped from the journal chat's environment (`ChatBuildEnv`) since that
  agent reads the web.
- **Sessions are named after the task** (`retitle`). Run from inside a
  turn, where a typed `/rename` would only queue, it stores `task` and a
  detached waiter (`retitle-wait`) types `/rename` once herdr reports the
  engineer idle; `session_name` puts the task in the next start's
  `--remote-control` too. *Clear conversation* is `/clear`; which session
  an engineer is in is herdr's word (its SessionStart hook).
- **One MCP server: fff.** Every crew session starts with
  `--strict-mcp-config --mcp-config STATE/mcp.json` (`mcp_config`, fff's
  entry copied from `~/.claude.json`). Without it the claude.ai account's
  connectors (Higgsfield, Netlify, Cloudflare, Claude Docs, …) load into
  each one: ~112k tokens of tool definitions for Number One, whose `--tools`
  has no ToolSearch to defer them (a fresh one began at ~126k, ~13k now),
  and ~7k of deferred names and instructions for an engineer (~22k → ~15k).
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` would drop only the connectors, from
  an environment herdr's tab would have to carry; strict also keeps out a
  server added later. The briefs say to search with fff.
- **The console has them too**, as threads in its Chats (`chat.eng`,
  `engSend`, `engPoll`): the same conversation, answers, Deploy and Roll
  back; the deck's talk sheet is that same chat in a frame. Promoting and relieving
  stay the deck's, since who is an engineer is the deck place's `eng` map.
  *Dismiss* only marks `dismissed` in `<name>.json`; nothing is removed.
- **Model and effort are flags, per engineer.** Every start and resume
  passes `--model` and `--effort` from `<name>.json` (`model`, `effort`),
  else the defaults: opus at medium for the crew (`LCARS_ENG_MODEL`,
  `LCARS_ENG_EFFORT`), fable at xhigh for Number One. So the box's
  `~/.claude/settings.json` never decides either. `engineer.py model` and
  `effort` change one by restarting the session resumed, at once or at
  the turn's end (`model-apply`).
- **The cores are the limit, and memory the guard.** Each engineer is a
  200–400MB process whose test runs take ~2GB more at their peak, on an 8GB,
  4-core box that also runs the journal (2GB and one core before
  2026-10-14; docs/ops/engineer-time.md), so `start` refuses below
  `LCARS_ENG_MIN_FREE_MB` (2500) available, and `engineer.py reap`
  (`scripts/lcars-eng-reap.{service,timer}`, every five minutes) closes any
  engineer idle for `LCARS_ENG_IDLE_MIN` (20) minutes, sparing one at a
  question or being deployed. The deck's next message resumes them.
  `reap` also deletes ended Claude sessions' scratch under
  `/tmp/claude-<uid>/` (`reap_scratch`): `/tmp` is a tmpfs there, and what
  piles up in it ends in swap. A session is kept while any process could
  still be its own, and for `LCARS_SCRATCH_KEEP_H` (6) hours after its last
  write. Tests: `python3 scripts/test_reap.py`.
- **One machine.** Engineers could once live on the captain's laptop
  ("satellites", 0.122.0), with the VPS proxying every verb over ssh and a
  deploy split at the merge. Nobody used one by 0.174, and the ops sweep
  took it out (`docs/design/sweep-ops.md`, item 1).
- **Number One** (`NO1` in `engineer.py`, `scripts/no1.py`, `lcars_logins.h`)
  is the engineer whose job is the other engineers: told what is wanted, he
  gives orders, starts engineers, reviews diffs and deploys, and asks the
  captain only what needs the captain (`brief_no1` says when he may deploy
  on his own authority and when he must escalate).
  - He runs `--permission-mode dontAsk` with `no1_settings()`: `no1.py`,
    reading files (fff's three searches too) and read-only git. He makes no edits.
  - His worktree moves only by `no1.py sync` (`sync_no1` in
    `engineer.py`): a fast-forward of `eng/number-one` to the live branch,
    refused if it has tracked changes, commits of its own or another
    branch checked out. The brief has him run it when a report reaches him,
    and every deploy and rollback runs it at its end (`no1_after_land`),
    where a refusal is one line in the outcome, never a failed deploy. No
    git permission of his own is widened for it.
  - Crew verbs go to `engineer.py`. `no1.py` keeps at most
    `NO1_MAX_CREW` (10) on duty. His
    messages are marked `[No.1]`; every brief says to take them as the
    captain's, except deploying.
  - Engineers report to him unasked: each starts with `--settings` carrying
    a Stop hook (`engineer.py turn-ended`) and a Notification hook
    (`attention`), and once a `[No.1]` message has put one under his orders
    (`under_no1`), each turn's end and each question is typed into his
    session as `[crew] …` (`notify_no1`). He is exempt from `reap`'s idle
    stop.
  - **Nothing for him is lost while he is off duty.** Every note for him
    (`tell`/`notify_no1`) is a `crew_inbox` entry addressed `number-one ←
    <sender>`, as every engineer's is, which the captain can read, edit or
    cancel, delivered in order by a detached `no1-flush` and ticked done as
    it is typed, so a hook or a deploy never waits on him. An undelivered
    note stays, and the next note or `reap` retries; one held over two
    minutes arrives marked `(held since …)`. A note that meets the journal
    down (a restart) is written by a `no1-send` unit once it is back.
    Off duty, the flusher starts him (`wake-no1`, resuming his
    conversation), unless he is dismissed. A plain stop does not keep him off;
    dismiss does.
  - **The captain's answers come back to him.** A question is a reminder
    the captain ticks off, perhaps with notes. `reap` also runs
    `no1_answers`, a read-only look at `lcars.db` for `task_no1`/
    `task_no1_*` rows done and not yet told, each typed to him as
    `[captain] ticked off your question #<id>: …`, through his inbox, the
    console's `Answer (captain, …)` block whole (a line per question of an
    ask in docs/design/questions.md's shape) and the rest clipped. What
    was told is `no1-answers.json` in the state directory; one reopened and
    ticked again is told again, and the first run counts everything done
    more than a day before as told.
  - **His own login** (`LCARS_NO1_USER`/`LCARS_NO1_PASS` in `~/.env`)
    reads everything but writes only kinds `no1_*` and `task_no1` (his
    questions, a Reminders list). `LimitedAllowed` checks a POST's kind, and
    an edit's old and new kind, before the router, and refuses the engineer
    routes, CalDAV and uploads. A `/chat` he starts runs `lcars-cli` with
    his login. The console shows open `task_no1` rows as *No.1 asks*.
- **The seat** (`scripts/seat.py`; the moves in `engineer.py`'s "the
  seat"). Production has memory for one crew Claude Code at a time, so its
  engineers and its scheduled roles take turns in one seat; Number One is
  outside it and always on (`reap` starts him unless dismissed).
  - **Turns.** The one seated works until a turn ends. Then, with others
    queued, they are stopped (session, worktree, branch kept) and the next
    is started, resuming, and handed their inbox as one message; with
    nobody queued they keep the seat, idle, until reap's idle stop. A
    message to someone not seated (`say`, a deploy's `tell`) is a
    `crew_inbox` entry and queues them. A turn is never cut for someone
    else's work, however long: the captain's message goes first in line
    and waits for it. Only the captain's explicit order (`seat-relieve
    [<name>]`, or `"preempt"` set in the entry's block) cuts it: the one
    seated gets Esc, is stopped, and is requeued with a `[seat]` note to
    carry on. A stuck holder is relieved the same way when someone waits:
    at a question for `SLICE` (30 min), or "working" with its transcript
    silent for `SLICE`. Number One's orders queue, first come first
    served. `yield <name> [<to> "<msg>"]` ends a holder's tenure at its
    turn's end, handing over first in line. A scheduled role queues as
    `crew:<role>` (by its pid) and is never cut; its timeout bounds it.
    A crew note's turn (`crew.py note`) takes no seat (0.226.0): the
    captain waits on it, it is a sonnet turn of seconds, and queued behind
    an engineer it sat for hours.
  - **Edits of the line** (0.197.0): the Queue view's ↑ ↓ first and
    remove, and `no1.py crew queue`, run `engineer.py queue-move|-remove|
    -restore` (`POST /engineer/queue/<op>`), which change the entry under
    `seat.lock` like any move: a handoff at the same moment lands wholly
    before or after. Each carries the line as the client read it
    (`expect`); a different one is a 409 and nothing is done. A removal
    cancels the engineer's undelivered `crew_inbox` rows (done, titled
    `[cancelled] …`, so nothing counts them as delivered) and records
    where they stood and which rows, in the block's `removed` (the last
    ten); `restore` puts them back there with the rows live again. The one
    seated is never in the line, so never touched.
  - **State in the journal, locks in files.** One `crew_seat` entry: a
    readable summary over a JSON block that is the state, which the
    captain may edit (`normal` tidies it; a block that does not parse stops
    the seat rather than being guessed at). The entries API has no
    compare-and-swap, so every read-modify-write is under `seat.lock` and
    one mover (`seat_move`) runs at a time under `seat.run`. `step` is
    pure: facts in (herdr's status, a role's pid), actions out. A move
    that finds the journal down (a deploy's restart) is retried by the next
    hook or reap. Engineers found running outside the seat (from before
    it, or by hand) are adopted when it is empty, else stopped once idle.
  - `python3 scripts/test_seat.py` (~7s): the decisions, the entry and the
    inbox against a stand-in server, and engineer.py's and crew.py's use
    of them.
- **The crew login** (`LCARS_CREW_USER`/`LCARS_CREW_PASS` in the unit's
  environment) is the same gate for the scheduled crew roles: headless
  agents on the VPS, run from cron, that read the journal and write
  reports. It writes only kinds `crew_*`, `task_crew` and `task_crew_*`.
  Both logins are rows of one table, `g_limited_logins` in `lcars_http.h`
  (who, the two variables, the owner prefix its kinds are named by), and
  share every line of the gate in `lcars_logins.h`; a third is one more
  row. A login whose variables are unset, whose password is under 16
  characters, or whose user is the main one's or another login's, does not
  exist. `lcars-ui/test/logins.py` (~40s with the build) drives a scratch
  server through every allowed and refused request for both.
- State lives in `~/.local/state/lcars-eng/` (`<name>.json`, `deploy.json`,
  `deploys.jsonl`, `logs/`). `deploys.jsonl` is rollback's record of what
  went live and, since 0.180.0, the console's Queue view's history: a failed
  deploy or rollback is a record too (`"outcome": "failed"`, which rollback
  passes over), and a landed one carries its versions and last subject.
  The failures from before were seeded once from `logs/` by the first
  `engineer.py queue` (`GET /engineer/queue`), which marks that it did.
  Since 0.186.0 each item there carries its time (`queue_times`,
  `live_time`): start, end, and the seconds per kind of activity, read from
  the engineer's Claude Code transcripts (a timestamp on every record, the
  tool of every call: the span to a call's result is that call's kind, the
  model's own between them thinking, the wait after a turn for an answer,
  for the seat by the `[seat]` note, a background run by its notice). A
  deploy ties to the tasks its commits' author times fall in; a task runs
  from its order (an order after a yield or a `[deploy finished]`, or one
  that says it is new) to its last record; the order's `crew_inbox` entry
  says when it was given, the deploy log when the deploy began. Shipped
  items are final, so cached in `queue-times.json` (by engineer and deploy
  time, `TIMES_V` the classifier's version); the work under way is read per
  poll from its window's transcripts only (a few tenths of a second).
- **The estimate** (0.204.0): the brief asks each engineer, before their
  first edit, for `engineer.py eta <name> <minutes>`, the whole minutes
  until their report, and again when the picture changes. It is kept in
  their `<name>.json` (`eta_min`, `eta_at`, the revisions in `etas`),
  against `task_started_at`: when an order was typed into them idle (`say`,
  or the seat handing them their inbox; a ship's or seat's note is no
  order), else their first eta. Their turn's end (the Stop hook) ends it:
  estimated against taken goes to `eta_done`, and each landed deploy in
  the queue carries the last one that ended before it and after their
  previous deploy (`"eta": {est, first, actual}`). `list`, `poll` and the
  queue's seat entries carry `eta_min`, `eta_at`, `task_started_at` and
  `elapsed_min` (null when not known), so the console fetches nothing new.
  The page draws it as one bar (`etaBarHtml`) under the working one's line
  in the Queue and at the top of their chat while they work: elapsed over
  the estimate, full and amber past it (red half as long again past it),
  empty and dim with "no estimate yet". A timer once a minute (`etaTick`)
  moves every bar on screen between polls, and stops when none is left.
  Calibrated (0.213.0), because the first nine ran 4 to 8 times long: the
  bar runs against `expected_min`, the latest estimate times the
  engineer's median took over first-said (`eta_ratio`) over their last ten
  `eta_done` records when they have two, else the crew's over every
  record (`ratio_from`: own, crew, none; with none, the estimate as
  before), and says both. The brief carries the record and their own
  median (`eta_record_line`). Each record keeps `model`, `effort`, `turns`;
  an order to them idle that is not fresh, after no clear (a clear marks
  the last record `sealed`), under 12 hours since it closed, sets
  `eta_continues`, and if at the turn's end their task label is still the
  record's, the turn's minutes and estimates go into it (`ends` lists the
  turns' ends, which the queue's deploys match). `engineer.py etas`
  (`no1.py crew etas`) prints them all with the medians, for the next look;
  `scripts/eta-report.py -o F.html` draws them (0.284.5): one
  self-contained page, each record's took-over-said by the day it ended
  on a log scale, the crew's rolling median of 15, the medians' table -
  for `report.py publish`.

### Embeddings (`lcars_embed.h`) and the star chart

The web UI's star chart ("Stellar cartography", `S`) draws every entry as a
star placed by what it is about, and "possibly related" under an entry lists
the entries nearest it in meaning. Both run on one vector per entry.

- **The model is a service, not a library.** Vectors come from any
  OpenAI-compatible `/v1/embeddings` endpoint (`$LCARS_EMBED_URL`, default
  `http://127.0.0.1:8091/v1/embeddings`; `$LCARS_EMBED_MODEL`,
  `$LCARS_EMBED_KEY` for a hosted one; `$LCARS_EMBED=0` turns it all off). By
  default that is `scripts/lcars-embed.service`: llama.cpp's llama-server
  with multilingual-e5-small (384 dimensions), because a journal may be written
  in more than one language, and an English model puts every entry in
  another language in one cluster of its own. e5 expects `passage: ` / `query: ` in front of its text, so a
  model whose name contains `e5` gets them.
- **An indexer thread** (started with the server) polls every 30s for live
  entries with no vector, another model's, or one made from an older
  `last_modified_at_utc`, and embeds 16 at a time. An entry is only picked up
  once it has sat unedited for a minute, or every debounced save would
  re-embed it. A service that cannot be reached is waited out (5 minutes)
  and logged once; a batch it refuses is retried one entry at a time, and an
  entry it still refuses is halved until it fits. Rows too short to mean
  anything get a zero-length vector so they are not asked about again.
- **What is embedded** is the title (not the `HTTP Entry` placeholder) and
  the first 800 bytes of the body, *cleaned*: property lines (`type::`,
  `source::`), `[[`/`]]` brackets, bullets, and every URL but its host are
  dropped. The first pass without that charted the Capacities/Logseq imports
  by their punctuation. The recipe is versioned (`EMBED_RECIPE`) and stored
  with the model name, so changing it re-embeds the journal like a model
  change does.
- **Vectors are int8**, each scaled so its largest component is 127: 384 bytes
  an entry, ~1.4MB for the journal, and the rounding is far below the gap
  between neighbours. `entry_embeddings` is a side table, created on first
  use.
- **The memory trap.** This llama.cpp reserves a vocabulary-sized row of
  logits for every input token even when only embedding (`output_reserve`,
  `has_logits = true`), and e5's vocabulary is 250k tokens: ~1MB a token,
  ~500MB after one long entry, held until the server restarts. Hence one
  slot, `--cache-ram 0`, the 800-byte cap, and **a server that only runs
  while wanted**: `lcars-embed.socket` holds :8091, the first connection
  starts `lcars-embed-proxy.service` (`systemd-socket-proxyd`), which pulls
  llama-server up on :8092 and exits after 10 idle minutes, taking it down
  (`StopWhenUnneeded`). A cold start is ~3s, inside the indexer's and
  `/embed`'s timeouts. `--sleep-idle-seconds` came first, but a "sleeping"
  server was still seen holding ~550MB with the box's swap full.

In the page (`lcars-ui/index.html`, "stellar cartography"):

- The vectors are synced (`starSync`, `?since=`) into their own IndexedDB
  database, `lcars-stars` — not a store in the mirror's, whose version bump
  would block on every other open tab. A boot reads them but only syncs them
  if the device already holds some, so a device that has never opened the
  chart never asks (and the QuickJS suite's boot-request counts stay exact).
- **The layout is UMAP, done in the page**: each star's 12 nearest by cosine
  (searched in the ~√n buckets around pivots nearest it, not all pairs —
  12s became 2s on the VPS), fuzzy neighbourhood weights, a PCA start, 200
  rounds of attract-neighbours/repel-strangers. It runs in a Web Worker
  built from `starLayout`'s own source, posting positions as it goes so the
  chart is watched settling; where a worker cannot be had, the same
  generator runs a slice a frame. Constellations are k-means on the finished
  chart, named by the words most particular to each — the entry's kind split
  at underscores, and its title and text cleaned the way the server cleans
  them.
- **The chart is kept** and new entries are placed where their nearest
  charted neighbours are, so the map is the same map tomorrow. Past 30%
  placed that way it is laid out again; "Re-chart" does it on request.
- **Stars are pixels**: one `ImageData` per frame, put once. Canvas rects
  for 4000 stars cost 6ms a frame to rasterise in the perf harness; pixels
  cost half a millisecond. `perf.py`'s `stars-chart` and `stars-pan` hold
  the chart to the same 16.7ms p99 as everything else.
- **Search by meaning** posts the query to `/embed` and lights the 24 nearest
  stars; with no `/embed` it falls back to the words in the entries.
  **Related by meaning** (`relatedMeaning`) keeps an entry's neighbours
  whose cosine clears its own background (mean over every entry plus 2.2
  standard deviations), because e5's cosines crowd together — unrelated
  entries score ~0.82 — and a fixed floor would only suit one model.
- **The entry list searches by meaning too** (`meaningText`,
  `meaningMatcher`, `meaningRun`): the Match row's Meaning mode, or a
  leading `~`. The query goes to `/embed` once its typing settles, and the
  answer is a set of ids with their closeness (`st.meanHits`, the same
  background rule at 2 standard deviations, 12 to 50 rows), which
  `makeRowFilter` applies — so the calendar and the statistics scope agree
  with the list — and `refresh()` ranks by, above the chosen sort. It is the
  one path that fetches vectors on a device that never charted: the user
  asked a question only they can answer.
- **The editor offers a kind and a title** (`sugRun`, `sugNeighbours`,
  `sugKind`, `sugTitle`): the draft embedded through `/embed` when the typing
  pauses, its 15 nearest among entries of kinds written in the last 30 days
  voting on the kind (each weighted by how far it clears the draft's
  background), and the title made from the draft's first sentence in the
  shape those neighbours are titled. Offered as chips (`#esug`), never
  applied; module state in `sg`, reset by `setForm`.
- **The statistics use the same vectors** (`statTopicsJob`), but only the
  ones this device already holds — a device that never charted gets a button,
  not a download. Topics are spherical k-means after subtracting the
  journal's mean vector: without that, e5's crowding splits clusters on noise.
  Echoes compare recent prose (`log|journal|meeting` kinds) only against
  older prose in the same topic — a twelfth of the work, and the nearest
  neighbour is in the same cluster nearly always. This and the words pass
  (`statWordsJob`) run as sliced jobs after the dialog is up, cached against
  the journal's signature.

### Voice for the crew (`lcars_say.h`, `POST /say`, `GET /say/token`)

The chats speak replies aloud (the console's, and so the deck's talk
sheet, which is a console thread in a frame), and the browser's own
`speechSynthesis` is a robot on Linux. `/say` gives the crew a real voice
without putting a key in the page: the page sends `{text, voice}`, the server
adds the key and relays a streaming request to a hosted text-to-speech
service, passing each chunk of mp3 on as it arrives (straight to the wire, not
through `HTTPStreamWrite`'s 64KB coalescing), so the first audio is with the
page about half a second after the request. Configured from the server's
environment (`~/.env`, which `lcars.service` sources):

- `DEEPGRAM_API_KEY` — **Deepgram Aura-2** (`/v1/speak?model=aura-2-…-en`,
  mp3). Chosen by default whenever this key is set; no `LCARS_TTS` needed.
- `LCARS_TTS=elevenlabs` with `ELEVENLABS_API_KEY` — ElevenLabs'
  `/v1/text-to-speech/<voice>/stream`, model `eleven_flash_v2_5`.
- `LCARS_TTS=off`, or no key — both routes answer 503 and the page speaks
  with `speechSynthesis` as before.

The voice name goes into the provider's URL, so only `[A-Za-z0-9_-]` passes.
Nothing from the provider is trusted: a refusal before any audio is a 502
quoting its status and message; a failure mid-speech ends the chunked body
without its last chunk. A client that hangs up (a newer line, the sheet
closed) ends the relay at once: the socket is polled for `POLLRDHUP` before
every chunk and from curl's progress callback while the provider is still
silent. At most three relays run at once (429 past that) — each is a
connection thread and costs money.

The page (`index.html`, the "speech queue" block) asks `GET /say` once for
the provider and picks voices from `SAY_VOICES`: per provider, four female
and four male voices (a persona keeps one, by a hash of its key), the host,
and the computer for announcements. **Everything a page says goes through
one queue**, so nothing talks over anything: a *run* is one speaker's lines
in order (`sayRun`, `sayAdd`, `sayEnd`; `sayAloud` is a run of one line, for
announcements and the answers to orders). **Each line streams**: Deepgram
makes a sentence only two or three times faster than it plays (a
100-character one is about 7s of speech and takes 2.5s to arrive whole; a
450-character reply's mp3 took 10-18s), so a line fetched whole is heard a
third of its length late. The page asks `POST /say` for `format: "pcm"` - raw 16-bit
PCM, which has no frames to wait for and no decoder - cuts each tenth of a
second into an `AudioBuffer` on the page's `AudioContext` (already unlocked by
a tap, which an `<audio>` made after a fetch is not on iOS) and schedules it
to start the instant the one before ends: no gap, no overlap. From silence a
line waits for a quarter second of itself (`SAY_LEAD`, in about 0.6s after
the request) so a slow stretch of the network does not stutter; measured,
Deepgram's PCM was never less than 0.12s ahead of the voice after that. The next line is asked for only once
this one has begun playing - at most one request ahead of the voice, which
respects the server's three-at-once cap and the bill - and its audio waits,
buffered, until this one is whole. A server that answers mp3 anyway is
decoded whole, as before. (MediaSource on the mp3 was the other way; older
iPhones lack it.) A reply is spoken **a sentence at a time as it streams in**:
`chatSayFeed` cuts the text deltas with `sayCut` (at `. ? ! …` or a newline,
only once more words follow, not under 8 characters, not after "Dr." and
the like or "No." before a digit) and adds each sentence the moment it is
complete, so the first is heard about a second after its text arrives.
Narration before a tool call ("let me look") is dropped from the text and
must not be heard: its last sentence is never cut (nothing follows it
before the tool), and the tool call stops whatever of it was already queued
and starts a fresh run for the answer. That is "speak as you go, discard
what was dropped" - simpler than holding the voice until no tool can come,
which is the end of the reply. A narration of two sentences or more could
start its first before the tool call cuts it off; in practice the tool call
lands before the first sentence's audio does.

`#chsay` in the talk row is a button, marked ■: "voice…" while the
first line is being made, "speaking" from its first sound to the run's last
(the gaps while the reply is still being written included, so it and the
deck's talking lips do not flicker). A tap on it stops the whole run; so
does Esc, a press of Hold to talk, a new question, leaving the thread,
Voice (or the deck's sound) off, and Stop on a reply being written. A run the captain stopped stays stopped for the rest of
that reply. If the server's voice fails, the rest of the run goes on in
`speechSynthesis`, after the audio already scheduled. `test/speech.py`
runs the block in headless Chromium against a stand-in `/say`. The deck's
own voice is only the computer's announcements, one short line every few
minutes: `sayAloud` there fetches it whole (mp3) and plays it as one
buffer on the deck's `actx`, `announceSynth` when the server has none, and
`sayStop` (sound off) ends it mid-fetch or mid-line.

The crew think with **haiku** (`TALK_MODEL` in the deck), the host with
sonnet: a crew member's chatter is short, and their thinking is now the
longest wait before the first word. Measured on a scratch server
(2026-10-13, ten questions alternating): with no tool call, `claude -p`
gives the first sentence in 3.6-4.1s on sonnet and 3.8-6.1s on haiku (its
start-up is most of it, and haiku writes longer replies); with journal
look-ups 17-18s on sonnet and 12s on haiku. The voice then adds 0.55-0.85s.

The captain speaks back by push-to-talk in the same thread (crew and
engineers alike): hold "Hold to talk", or Space in the empty box. The audio
does not pass through the server: the page streams raw 16-bit PCM from one
`getUserMedia` capture (an AudioWorklet, ScriptProcessor before it) straight
to Deepgram's `wss://api.deepgram.com/v1/listen` (nova-3, smart format,
interim results), as the console's dictation (`dgOpen`) does. What it needs from the
server is a key, and the long-lived one stays there: each press asks
`GET /say/token`, which mints a JWT good for about 30 seconds with
`/v1/auth/grant`, and the socket opens with it as a `bearer` subprotocol
(only the handshake needs it valid). Audio heard while the token and the
handshake are on their way is queued. Interim words show live in the box;
on release the capture stops, `CloseStream` brings back the final words
and Deepgram's close, and the text goes through `talkHost.send` exactly as if
typed (so in the deck's sheet the deck's `crewOrderSaid` still catches
orders, an engineer's thread hands it to `engSend`). One socket at a time: a press while the last is still
finishing sends that one first. A press stops a reply being spoken
(`sayStop`). A refused microphone, no key, or a refused socket is a toast,
and typing works as ever. `/v1/auth/grant` wants a key with Member rights;
a usage-only key gets a 403, which the page shows as "No listening token".

**Conversation mode** (the same block, `conv*`) is that socket held open:
*Start conversation* opens the microphone and one stream with
`vad_events`, `endpointing=500` and `utterance_end_ms=1200`, and every
utterance goes through `talkHost.send` by itself. It is sent on Deepgram's
`UtteranceEnd` (about 1.2s with no new words), not at the endpoint's 0.5s
silence: that comes at every pause for thought, and a sentence cut in two
is two questions, each answered. Fewer than `CONV_MIN_WORDS` (1) real
words - with letters, not "um" (`CONV_FILLER`) - is a cough or the room and
is dropped; one is enough, so "Yes." and "No." are answers. For an engineer or Number One, `engSend` prefixes
`CONV_NOTE` ("[conversation] Answer in one or two spoken sentences first;
act or read code after.") so the session's first text block is a spoken
answer, and the thread strips it from the captain's line (`engPlain`); the
crew's /chat has its persona instead. The microphone stays open while a
reply plays, with `echoCancellation` on. `conv.mode` (the deck's Settings,
`lcars.deck.convmode`, set in the frame by `convSetMode`) decides what then: `barge` (the default) stops the
voice at the first word heard (`convBarge`: not at SpeechStarted alone, which
fires at the room or the speaker's echo too) and lets them through as the next
turn, the reply's text left in the sheet; `mute` sends no audio while one
plays - for a phone whose speaker the microphone hears, where barge-in would
stop every reply at its own first word - and keeps the socket with
`KeepAlive` (Deepgram closes one silent for ten seconds). A stream that
drops is reopened with a fresh `/say/token`, once until it hears something
again; a token or microphone refused, a socket refused or not open within
`CONV_OPEN_MS`, ends the conversation with a toast. End conversation, Esc,
leaving the thread, Voice or sound off and the page hidden end it:
microphone off, socket closed, nothing sent. Hold to talk is off meanwhile.

**Where the voice comes out, on a phone** (`conv.out`, `CONV_OUTS`,
`lcars.deck.convout` per device): *speaker* (the default) or *earpiece*,
the captain's words. iOS runs one audio session per page, play-and-record
while any microphone capture is live, with its output in the earpiece; so
with the conversation's capture open every reply came out of the earpiece.
*Speaker* lets go of the capture while a reply is said (`convSay` from the
chats' run, `chatSayRun`): `convDrop` stops the tracks (stopped, not
disabled, or the session stays play-and-record) and keeps the AudioContext,
its worklet and the socket (`KeepAlive`, as mute does), and `convTake`
opens the microphone again into the same graph `V_HOLD_SETTLE` (350 ms)
after the run ends, so the next utterance is heard at the socket's rate.
Talking over a reply cannot work then: on a phone `barge`/`mute` are the
earpiece's. *Earpiece* is the old way: the capture stays open, the reply
private. It applies only where `convHoldForTts` (`V_IOS`; a let the tests
take); elsewhere the setting is not offered (desk and Android keep the
microphone open, as before). It sits in the thread's talk row (a pill,
Speaker/Earpiece, beside Start conversation: where a phone's thumb already
is when the reply is too quiet), the deck's Settings (*Voice output*, set
in the frame by `convSetOutput`), the palette and the orders "voice through
the speaker" / "voice through the earpiece". Whenever a capture is let go
- `convDrop`, `pttRelease` (Hold to talk's release, a conversation's end),
`vHold` (the orders microphone for a reply) - `sayQuiet(V_HOLD_SETTLE)`
schedules the speech queue's next first sound no earlier than the settle,
so the start of a reply is not swallowed while iOS switches the session
back to the loudspeaker.

An engineer's replies come with the poll, a whole message (a transcript
text block) at a time, not streamed: `chatEngSpeak` cuts each into sentences
and adds them to one run, reopened (`sayReopen`) while it still speaks so
the next message follows rather than cuts it off; a long message is said
whole (a line longer than `SAY_MAX_BYTES` is cut at a sentence), code blocks
and tables not at all, and a run the captain
stopped stays stopped until their next line appears in the transcript.
During a conversation the poll is 750ms, not 1.5s. Measured send to first
word (2026-10-13, scratch server, the real key): an engineer on opus,
`claude -p` started cold, 9.9-10.2s with the note and 21.7-24.3s without
(it reads code first); a crew member on haiku 13.4-22.4s, nearly all of it
journal look-ups before the answer, since the narration before a tool call
is not spoken.

**In the console's chats** (`index.html`, "voice in the chats") all of this
is behind a **Voice** toggle in a thread's header, off by default and
remembered (`lcars.chat.voice`): the console is read in public (in the
deck's talk sheet the deck's sound switch stands for it). On, a
reply is spoken - a streamed `/chat` answer (the computer,
a crew role, a navigator) sentence by sentence as `chatPost` brings it
(`chatSayFeed`: only the text after the last tool call, code and tables
not said), an engineer's or Number One's messages from the poll
(`chatEngSpeak`) - and a talk row under the box has
Hold to talk (Space held in the empty box only: elsewhere Space is the
console's), Start conversation and the speaking mark. Who speaks
(`chatWho`): the computer Athena, the host Hera, an engineer as their deck
seat (their slug ends in it, `hale-c12`: the same voice), a crew role by a
hash of its kind. While the talk has the room the console's own microphone
(orders, dictation) is held (`chatMicHold`, `vHold(…, true)`), or what was
said would be typed as well as sent; so "end conversation" said into a
conversation is caught in `talkHost.send` instead. Nothing inside the
speech queue's block names the page: `sayOn`, `sayShow`, `actx` and `DEMO`
are outside it, so `test/speech.py` can run it in a bare page. Hold to talk is the console's alone
(`talkHost` is the box, whether the talk is up, sending, the toast, the
microphone hold; `talkWire()` wires the pills once they exist):
`test/ptt.py` runs it in a bare page, `test/qa_chat.py`'s talk pass at a
phone's size.
The console's dictation (`dgOpen`) asks `/say/token` too, before every
socket and reconnect (`dgToken`), so no long-lived key is in a browser; a
key pasted into Config before 0.169 is used only on a 503.

## The 3D deck (`lcars-ui/deck.html`)

A walkable U.S.S. Enterprise where journal entries are pinned as PADDs on
walls, consoles, desks and windows. three.js 0.186.1 and WebXR. three and
the addons the deck uses are one bundle,
`lcars-ui/vendor/three-0.186.1-r2.min.js`, built from
`scripts/three-bundle-entry.js` with `esbuild --bundle --format=esm
--minify`, so nothing comes from a CDN. **A rebuilt bundle gets a new file
name** (the `-r2`): the service worker serves same-origin files
stale-while-revalidate, so a new deck.html importing a name it added would
otherwise meet the old bundle and fail.

Its contract with the rest of the app:

- **A page of its own, not a view of index.html.** The console holds every
  interaction to 60fps p99 in `perf.py`; a WebGL scene is not that budget's
  to carry, and a phone should not be handed a WebGL context on every boot.
- **It borrows the console's state.** Same origin, so the login is
  `lcars.cfg` in localStorage and the journal is the IndexedDB mirror
  (`lcars` v1), read without a request and caught up with the same two
  `/dump` questions `deltaSync` asks. The deck **never writes the mirror** —
  only index.html does — so the two pages cannot disagree about it.
- **A place is an entry of kind `space`** (content
  `{v, env, pins:[{e, p, q, s, d}], hand, at, names, crew, sky}`). Pins
  therefore sync, soft-delete and restore like any entry and there is no
  schema change; any other state the deck needs is to be an entry of its
  own kind too (holodeck programs are `holo_program`). `loadPlace` migrates
  a version 1 place (the ship before 0.76's rescale, `PORT_OFF`). Saves are
  a debounced `PUT` (1.5s), one in flight, flushed with `keepalive` on
  `pagehide`/`visibilitychange`. A pin's id is an entry id (a number), a
  view (`VIEWS`, a string) or an attachment (`m:<media id>`), so pinning,
  carrying, throwing and shelving are one code path for all three.
- **The console is the reader.** C shows index.html in a frame; a clicked
  PADD opens there in focus mode. The deck calls functions the frame exposes
  (`lcarsDeckRead`, `lcarsDeckView`, `lcarsDeckSel`, `lcarsDeckBack`,
  `lcarsDeckDictate`…) rather than writing its hash, because a parent's hash
  write is a Back step each time, and asks again until one answers true
  (rows still landing, an edit unsaved). The frame never moves in the DOM
  (that would reload it). Framed, the console pushes no history. A headset
  cannot show a DOM frame in an immersive session, hence the wrist PADD in
  TODO.md. Drawing the live frame onto a pad was tried in 0.65 and removed
  (`git show 84e2bb6:lcars-ui/deck.html`, `wallView`): smaller type and
  buttons that could not be pressed.
- **Crew talk, holodecks and navigation use `/chat`.** A crew member's
  thread is the console's (`lcarsDeckChat`), with a persona (`personaOf`,
  seeded from the person's room and uniform) as its context, sent on the
  thread's first message only; `--resume` carries it. Crew
  orders are answered in the page (`crewOrderSaid`), never sent to `/chat`.
  `holoClean` turns whatever a holodeck prompt returns into a recipe the
  deck can build, or refuses it.
- **The desk dictates through the console** (`lcarsDeckDictate` and
  friends): the deck has no microphone code of its own.
- **The architect changes the live scene with patches** (0.271.0,
  docs/design/architect.md; "the architect: live patches" in deck.html).
  A patch is JavaScript against `deck` (`deckApi`, its reference
  `DECK_API_DOC`, which the design's section 9 must match: deckboot.js),
  run by `lcarsDeckPatch` with the API bound to its id; every verb records
  its inverse on the patch's undo list, so `patchSync` can bring the scene
  from the list as applied to the list as wanted by undoing back to the
  first difference and applying on, and a patch that throws leaves nothing
  behind. A model merged into its room's mesh is lifted to change it
  (`patchLift`: its range zeroed as `hideStandin` does, a mesh of its own in
  the atlas, its stand-in's parts in `pinnable` moved with it), so
  `placeModels` records each placement's range, frame and source, and names
  it (`placeName`: `<deck>/<room>/<glb>/<prop>#<n>`, counted in build
  order). Patches are `deck_patch` entries (?demo: localStorage), replayed
  after `loadModels`, by `seq`, never those in `DECK_BAKED`; a hang is
  caught at the next load by the id left in sessionStorage, and
  `?nopatch` applies none. Phase 1 is deck 8 only: a generated room's
  patches wait for `buildRoom` (phase 2). The architect is a sheet (I, a
  pill, "architect"), the console's thread `arch` in the talk sheet's
  frame; `lcarsDeckSees()` and `lcarsDeckShot()` are what the console
  sends it. The deck listens to `GET /events` itself (`deckEvStart`,
  evStart's code), so a patch or any entry written elsewhere reaches it in
  a second or two rather than at the two-minute `refreshJournal`.
  The console's half (0.272.0, "the architect" in index.html): the thread
  `arch` is a kind of its own (`t.arch`), its brief `crew/architect.md`
  (`kind: chat`, so `crew.py` never runs it; its reference is
  `DECK_API_DOC` verbatim, deckboot.js again) through `engineer.py brief`.
  `chatSend` freezes `lcarsDeckSees()` at Send and makes the picture one
  of the message's files; `archWatch`, in the stream's paint, hands the
  first closed ```` ```js deck-patch ```` fence to `lcarsDeckPatch` at
  once; `archAfter` writes the `deck_patch` entry once the answer ends
  (the page's write, never the agent's: **the server refuses a write that
  creates or changes a `deck_patch` or `ui_patch` entry without
  `X-LCARS-Client`**, `PatchKindAllowed`, and lcars-cli sends none), and
  a failed patch is sent back once by itself (`archNext`). A switch, the
  sheet's or the console's Undo, sets `on` in a fresh read of the entry
  and PATCHes it with `if_modified`.

How the ship is built, and why that way:

- **The ship is code**, not a model: rounded boxes, cylinders, canvas
  textures, shaders. Surface textures are generated at boot (`T`), and
  `autoUV` writes texture coordinates in metres over the material's `tile`,
  so a panel is the same size on a short wall and a long one.
- **Props may be models** (0.214.0, docs/design/deck-pipeline.md): a
  room's props are one glb with one atlas in `lcars-ui/deck/`, built by a
  Blender script or converted from a CC0 pack (`scripts/deck-models/`,
  cleaned by `scripts/deck-model-assets.mjs`; committed, so no Blender at
  runtime). A builder wraps its code-built prop in `model()`; the models
  load after the boot (`loadModels`), each room merged into one mesh (one
  draw call), the stand-in's triangles collapsed where `mergeStatic`
  merged them (`standinRanges`). The stand-in keeps its seats, `block()`,
  contact shadow and lights, and stays whole when a glb never comes.
  Only deck 8's hand-built rooms can place models so far: a generated
  room's are built after `loadModels` has run.
- **Deck 8 is built by hand** (`buildShip`); every other deck and deck 8's
  wings are seeded plans (`planDeck`, `planWings`, `ROOM_T`), so a room is
  the same room on every visit and a deck's rooms are known without building
  it (`shipRooms`, the transporter's list). Builders work in a room's local
  frame (`wpt`/`wrect`), and everything registered while `owner` is set can
  be taken out again (`disown`): that is what lets a room or a deck be built
  and dropped. Rooms are built within `BUILD_R`, one a frame, and dropped
  past `DROP_R`; one other deck at a time is built at x = `GEN_X` (beyond the
  far plane) behind the turbolift's fade. Room names given by the user go
  through `shown()` only; the generated name stays the identity.
  A generated deck's rooms have people (0.242.0): `staffDeck`, once a
  deck is built, picks by the deck's seed which rooms of the kinds in
  `ROOM_CREW` (quarters, labs, sickbays, messes, lounges, conference
  rooms, main engineering, first) have one to three, up to
  `DECK_ROOM_CREW` a deck and never more than `ROOM_CREW_NEAR` (12) in the
  rooms within `DROP_R` of any point of its streets: the most that can be
  built at once wherever you walk. `roomCrew` makes them with their room
  (from `buildRoom`, never ahead of `BUILD_R`) and `roomCrewDrop` takes
  them with it: seated on the room's own seats (`roomSeats`, sitDown's sum
  on each `seatable`; one to a place), standing at its `workSpot`s (the
  builders register them, like zones, so they go with `disown`). Each is
  `roomPid(deck, room, place)`, so their looks, name and chat are theirs on
  every visit; someone away on an order keeps their pid, so the room
  leaves their place empty, and `homeCrew` ends them if their room is not
  built, for it to make them again. Deck 8's rooms stay by hand.
- **Draw calls, not pixels, were the cost.** `mergeStatic` merges everything
  that never moves into one mesh per material; the originals stay in
  `pinnable` with their world matrices so the aiming ray still hits single
  walls (`nearPinnable` limits it to its reach). Generated rooms merge per
  room (`finishCell`). Moving things are `userData.dynamic`.
- **Lights are a pool** (`tickLights`, `POOL_N`): every point light costs
  every lit pixel, so `POOL_N` real lights are moved each frame to the
  `lightSpots` that matter where you stand; the count never changes, so
  nothing recompiles. **Shadows are drawn once** (`autoUpdate` off), from
  four spotlights, because a point light's shadow is six renders; again only
  when the pads change (`rebuildPads`) or the deck does. Doors' leaves cast
  none (`noCast`), so that a door moving never redraws them: it used to,
  and the crew passing made it most frames (0.187.1).
- **The sky is one material looked up by direction** (`skyMat`), so every
  window is a hole onto one sky with parallax, and they all merge. **The
  glass is drawn last, at the far plane** (`SKY_FAR`): the walls occlude the
  outside, the outside geometry (`buildSpace`, `ownShip`) fills the depth
  buffer through the openings, and the sky — the black hole's ray-stepping
  above all — is only paid where nothing else is. Stellar cartography's
  walls are the same shader without `SKY_FAR` (`cartoMat`). The helm swaps
  the sky function (`SKIES`, `applySky`) mid-jump, when only the warp
  streaks show.
- **Crew** are Quaternius's CC0 rigged models (`lcars-ui/crew/`, built by
  `scripts/deck-crew-build.sh`: `deck-crew-fetch.py` downloads the three
  packs from itch.io into `~/.cache/lcars-deck-models`, Blender makes three
  more hair styles and two idles (`deck-crew-hair.py`, `deck-crew-poses.py`)
  and `deck-crew-assets.mjs` cleans the lot, meshopt-compressed as the
  rooms' glbs, the decoder fetched at boot with them), with the uniform drawn in the
  shader (`crewBodyMat`, cut by `clothOf`): under the cloth the skin's
  normal map is off and the body's normals are a smoothed copy's
  (`clothNormals`, at load), with a relief of its own (`clothH`: seams,
  elbow and knee folds, ribbed cuffs) and boots pushed 6 mm proud; no
  texture, no extra draw. A stander's idle is one of four by seed
  (`idleOf`, never a neighbour's), a PADD reader carries one on the left
  hand, and a stop lands on a step (`gaitBlend`). Eyes, brows and hair are rebound to the body's
  skeleton at load, because each Skeleton is a bone texture uploaded every
  frame. **Their skin attributes are interleaved**: read them with
  `getComponent`, never `.array`. A person out of sight (`crewRoomsSeen`),
  out of the frustum or past 34m is neither drawn nor animated nor in the
  matrix update — forty people's bones were most of a frame's CPU. Until
  the models load, or if they cannot, the crew are instanced stand-ins.
  They walk fixed routes (`walkCrew`) or an order's A* path
  (`alongPath`, planned at most once a second), and both take each step
  through `crewStep`, which makes way: the nearest person in a lane 0.6-0.7 m
  either side of the way ahead is followed at 0.8 m if going the same way,
  and stepped round sideways (right if walkable, else left, else a wait)
  if standing, or if coming the other way and this walker's `c.n` is the
  lower: one fixed rule, so two never both wait. A last guard refuses a
  step ending within 0.55 m of anyone and nearer than it began. One pass
  over the crew with a box test first, no replanning; the player is
  still waited for, not stepped round. `test/deckboot.js` walks two
  head-on through Ten Forward's door on the real floor plan.
  On the generated decks the rooms' people are made and dropped with their
  rooms (`roomCrew`, below, the big ship): another `person()` each, as a
  stand-in until the bodies land and then `dressCrew` from the one
  `crewKit`; a room person at their place is culled by their room's name,
  not a search of the deck's zones.
- **The arboretum's foliage** (`buildLeaves`, `lawn`) is drawn only while
  the room can be seen (`arbOnly`, ~200k triangles) and kept out of GTAO's
  normal pass (`userData.noAO`), whose override material would draw every
  alpha-tested card as a solid quad.
- **Post-processing is desktop only** (`EffectComposer`: GTAO at half
  resolution, bloom, `gradeMat`); **G** cycles high / medium (no GTAO) / low
  (no composer). A WebXR session always renders directly.
- **Top-down** (`TOP`, V; phones start there) is the same scene from an
  orthographic `topCam` whose near plane is the cut at `CLIP_Y`, not another
  page. Front faces only would show nothing from above, so on the map every
  non-shader material is made two-sided (`topSides`). The first-person
  camera stays on the player, so lights, sound and placement still judge
  from that eye. The switch is a flight (`tickTrans`) with a global clipping
  plane (`clipPlane`) kept at 1e4 otherwise, so adding it never recompiles.
- **Phones** (`TOUCH`) have no pointer lock: `playing()` gates walking; the
  left of the screen is a stick, the rest drags the view, a tap aims once
  (`aimAt`). The gyroscope (`tickGyro`) hands the view the *change* in
  heading each frame, so drags and the sensor compose. iOS grants motion
  and speech only from a gesture, so Engage asks for both.
- **Pins outlive the walls they were on.** `rehomeStrayPins` stands a pin
  with no surface near it on the ready room's shelves, or puts it in the
  hand, so any rebuild of a room keeps its pins.
- **Sound is synthesized** (`startAmbience`): filtered noise and swept
  tones, crossfaded per room; the context starts on the first gesture and
  is suspended while the tab is hidden.
- `?demo` runs on a synthetic 400-entry journal with the place kept in
  localStorage: no server, nothing written anywhere real. `window.__deck`
  exposes handles for headless screenshots.

## Pages: every view is a url (`lcars-ui/index.html`, `lcars_ui_files.h`)

The console is one document, but every view has a path of its own under the
directory it is served from: `./` (the list), `./entry/<id>`, `./new`,
`./tasks`, `./calendar[/<scale>/<date>]`, `./day/<date>`, `./stats[/all]`,
`./readings[/<kind>]`, `./media`, `./graph`, `./stars`, `./ask`,
`./engineers[/<name>]`, `./crew[/<kind>]`, `./thread/<id>`, `./trend/<term>`, `./course[/<id>]`, `./shares`, `./help` — with
the list's filters as the query string on any of them (and `e=<id>` for an
entry open behind a view).

- **The page is hypermedia, not a router library.** A url is the state; the
  views are drawn from data the page already holds (the IndexedDB mirror), so
  following one needs no request, and offline is unchanged.
- **The server answers every page path with `index.html`.** A static file server cannot, which is why this server serves `/ui/` (`lcars_ui_files.h`) rather than tailscale serve's file mapping: files from `$LCARS_UI_DIR` read per
  request, so a saved file is still live at once; a first segment from
  `g_ui_pages` with no file behind it gets the app; `no-cache` plus a 304 on
  `If-Modified-Since`, which is all the service worker's revalidation costs.
  Loopback needs no password, like `/media/`. Offline, `sw.js` answers any navigation in its scope with the cached shell.
- **`<base>` is written by a script at the top of `<head>`**, before any
  relative url: the base is the path before the route (`LCARS_ROUTE_ARGS`
  says how many segments each page takes, which keeps `/eng/stars/` from
  reading as the star chart). Always, since a page that starts at `/ui/`
  and then pushes `/ui/entry/123` would otherwise resolve against the pushed
  url. The server's `g_ui_pages` is the list's other copy.
- **What pushes** (`pushes()`, "pages" in index.html): a different kind of
  page pushes; another of the same kind (the next entry by j/k, the next
  month or day) replaces, unless a click armed `pushNext` (a row, a link);
  going back to the list never pushes, and when the step below is exactly
  where it is going, the close *is* `history.back()` (`backPending` holds
  writes until its popstate lands). A change of page is written on the next
  turn (`saveState`), so `closeOv(); select(id)` is one step, and filters are debounced.
- **Views register themselves**: each opener calls `routeAs(name, …args)`
  once it is up, `closeOv()` clears `st.route`, and `ROUTES` maps a name back
  to its opener for Back/Forward and a bookmark (`applyPage`,
  `openBootRoute` once the rows are in).
- Framed by the deck, nothing pushes (the frame's steps would join the
  deck's history); the deck asks the frame which entry is open
  (`lcarsDeckSel`) rather than reading its hash.
- Old links (`#q=…&e=…`, which CalDAV still writes into each reminder's
  `URL`) are read as the query and rewritten in place.

## Crew reports (`lcars-ui/index.html`, "crew reports")

The scheduled crew roles (Yeoman, Ops brief, Historian, Science, Security,
Librarian, Ship's health, QA, Counselor), run on the server by the runner, post one
report per run as an ordinary journal entry of kind `crew_<role>`
(`crew_yeoman`, `crew_ops`, `crew_ship`, …) with markdown content; a finding
that cannot wait also arrives as a `task_crew` reminder, which the task
board and CalDAV already treat as any `task_*` kind. The console reads the
reports from the rows it holds, so the view needs no endpoint of its own.

- **`./crew`** is a row per role — the runner's table (`CREW_ROLES`) plus any
  other `crew_*` kind found — with its latest report's headline (title, else
  first line), when it came, how many there are and an unread mark.
  **`./crew/<kind>`** is that role's report, rendered, over a strip of its
  history. Reached by **B**, the palette row (which counts the unread), the
  header's Crew button (a ⋯ tile on a phone) and "computer, crew reports" /
  "computer, crew report <role>" (`crewFind`: a kind, a name or a word of it).
- **Read is per device**: localStorage `lcars.crew.read` maps a kind to the
  newest report id read. Ids only grow, so a later report is unread whatever
  its stamp. Showing a role's latest report marks it; an older one from the
  history does not. It is a mark for the reader, not journal data, so it is
  never synced and nothing here writes an entry.
- **The latest `crew_ops`** is pinned over today's day reader (`./day/<today>`,
  `crewPinPaint`): a card above the day's text, outside it, so Copy and
  Select all leave it out. Reading it there marks it read.
- **The deck** has a Crew reports view pad (`VIEWS.crew`, `faceCrew`, in the
  Views list): the roles, their latest time and the same unread marks, read
  from the same localStorage key; clicking it opens `./crew` in the console
  (`DECK_VIEWS.crew`).
- **The yeoman's proposals** (`yeoHtml`, "the yeoman's proposals"): a
  `crew_yeoman` report's lines end with the change as the captain would say it, and
  four shapes of it - `delete N`, `set kind of N to K`, `set due of N to
  <UTC stamp>`, `title N to T` (`YEO_RE`; `crew_tool.py` has the same) - get
  Apply and Dismiss in a box under the report, in the reader and in its
  bubble in the role's chat. Apply is the captain's own write on a fresh
  read of the row (a soft delete, or a PUT of `kind`, `start_date` or
  `title`), refused when the row is gone or its `last_modified_at_utc` is
  past the report's `created_at_utc` (or past our own last write to it): the
  yeoman judged a row that is no longer there. Its toast has Undo, which
  puts back what Apply replaced if the row still holds what Apply set.
  What became of each proposal - applied, undone, dismissed, with UTC
  stamps, the old value and the row's stamp after our write - is a
  `yeoman-ledger` fence in the report itself, written as the captain on a
  fresh read like the crew notes' `crew-changes`, so every device paints
  from it; the reader and the chat do not draw it. `crew_tool.py hygiene`
  prints it back to the yeoman as a ledger over its last 14 days of
  reports, and its brief repeats nothing the captain applied, dismissed or undid,
  and puts what is still pending on one count line.

## Plot a course (`lcars-ui/index.html`, "plot a course")

A trip is an entry of kind `trip`. The Course view draws it on a map
(Leaflet 1.9.4 from `lcars-ui/vendor/`, loaded the first time a course
opens, so the console's boot does not pay for it; the map's turning is
the page's own, `crsTurnable`).

- **The entry is the trip.** The content is a summary to read, then a
  ```json trip fence holding `{v, depart, points:[{name, lat, lon, stay,
  leave?}], legs:[{mode}], notes, calc, tracks}` (`crsParse` also takes the
  bare object, and a point given only as `{q}` is looked up). Times are the
  device's wall clock; `legs[i]` runs from point i to i+1; `calc` is the
  planner's numbers and weather, written back for the navigator to read and
  recomputed on every open; `prev` is the plan a navigator revision replaced. `start_date`/`end_date` are the departure and
  the arrival, so the calendar shows a course.
- **The page calls the services itself**, never through this server: a tile
  proxy would send every tile up the VPS's one uplink. With Mapy.com's key
  (`GET /maps`, from `$LCARS_MAPY_KEY`; it reaches only a page that passed
  Basic auth, and the repo carries none) it uses Mapy.com for tiles,
  routing, geocoding, elevation, places and the static picture; without one,
  OpenStreetMap/OpenTopoMap tiles, BRouter, Nominatim and Overpass. Weather
  is Open-Meteo, in one request for every sample. All of them answer CORS,
  and the service worker leaves cross-origin requests alone except tiles a
  course kept for offline use (`lcars-keep-*` caches, `crsOffline`).
- **The picture names no key.** `crsPicture` uploads the static map as an
  attachment and the summary links its media path, so no key is written
  into the journal.
- **The navigator is `/chat`, not an engineer.** It only needs to read one
  plan and propose another, so it is the computer's locked-down agent.
- **Every order is a fresh conversation.** The navigator's send sends no
  `session_id`: the message is the brief, the thread so far as a transcript
  (both sides, newest kept, 1500 chars a message and 12000 in all, a plan an
  answer ended with folded to a line), the local date and time and where the
  device is as the page knows it (the shared watch's last fix, else the last
  recorded point; it never asks for leave), the captain's recording (each
  track's start, end, numbers, stops and 40 points thinned in time, or "No
  recording"), the course as the planner shows it (times, distances,
  climbs, weather) and the order. Resuming a session would resend every
  earlier plan in full; this sends the current one once. The messages are a
  thread of the one chat (`nav-<id>` in `lcars.chats`).
- **A revision never writes over a plan.** The navigator does not write the
  entry: it ends a change with the whole new course in a ```json trip
  fence, and `crsRevise` POSTs it as a new entry (the old one's kind, title
  and done state, its picture and tracks carried over, `prev` naming the old
  id) and then soft-deletes the old one (`DELETE /entries/<id>`, `deleted =
  1`). The old row keeps its content and attachments; `PUT {deleted: 0}`
  restores it (the toast's Undo, `crsUnrevise`, which also deletes the new
  one). An agent that writes in place anyway is caught (the row moved during
  the answer): its content becomes the new entry and the old content is put
  back before the delete. The view, a recording and the messages follow to
  the new id (`crsNavFollow`). A question gets no fence and writes nothing.
  `crsWatch` stands aside while an answer runs, so what moves then is taken
  only as a revision.
- **Stops do not hide each other** (`crsSpread`, `crsSpreadLayout`).
  The course's numbered stops (`crs.marks`) whose faces overlap at this
  zoom are spread round their middle, a ring or a spiral, with a leader
  back to the true spot. Places, journal pins and forecast bubbles are
  left alone: they always sit on their true spot, with no leader. The spread is screen
  pixels added where Leaflet places a marker (`crsMarkerPos` replaces
  `Marker._setPos`), so the element is where it shows: clicks, popups
  and drags need nothing special, and a zoom's animation carries it. The
  leaders are one SVG path in a pane under the markers, in the map pane's
  coordinates, so a pan rewrites nothing. On a turned map the spread is
  turned back before the map's turn turns it, so it stays the screen's. It is recomputed a frame after
  any marker is added or removed and after every move, and two frames
  after a zoom, so its restyle never lands in the frame where Leaflet
  restyles every marker itself.
- **The map turns; what LCARS draws on it does not.** `crsTurnable`
  (0.275.0; leaflet-rotate, GPL-3.0, before it) leaves Leaflet north up
  and whole, and turns the box its map pane sits in with a CSS transform
  about the view's middle. Turned, the box is a square the view's
  diagonal wide, which is Leaflet's size then, so tiles and lines cover
  every corner at any angle; north up it is the view, a plain Leaflet
  map. Leaflet works on in its unturned frame; what crosses to the
  screen is turned at the crossing (`crsToMap`, `crsToScreen`, `crsRot`):
  the pointer (`mouseEventToContainerPoint`, a drag's offset in
  `L.Draggable`, the arrow keys), and anything the course places in
  screen pixels (`crsCentre`'s offset, the spread, `crsSees`, a fit:
  `crsFitTurned`). Markers and popups are turned back about their
  anchor by the box's `--crsr`, so they stand upright and a turn
  rewrites none of them; the controls sit outside the box. Who sets the bearing:
  the heading with Me on (`crsUp`, eased a frame at a time by
  `crsTurnStep`, only while it is off by a few degrees and no finger is on
  the map), north when held (`crsNorth`, `lcars.crs.north`) or with no
  dot, and two fingers (`crsTwist`, past 15°, about the point between
  them) or shift and the wheel on a desk (about the pointer), which leave
  the map the hand's (`crs.free`) until the compass or Me is pressed.
- **Whoever writes last wins, unless a save is pending.** `crsWatch`
  compares the row with the content this page last saved, every 2.5s; a
  row that moved (another device, the editor) is taken whole and re-routed, unless a save from this page is
  queued or in flight.
- **GPS is never left on.** `crsMe` (`watchPosition` plus the compass) goes
  off with the view (`crsStop`). A track (`crsRec`) holds a wake lock
  instead, since a page cannot track in the background, and is kept in
  localStorage as it grows, then attached as GPX.

## How the web UI loads the journal (`lcars-ui/index.html`)

- **Which server.** Served by the journal's server, the page calls its own
  origin (`DEFAULT_BASE`); Config's base url overrides it. From a file (or
  a native shell) there is no origin and no host of ours to fall back on:
  the base is empty and Config opens at boot saying so (`needsBase`). The
  deck reads the same setting.
- **The mirror.** The whole journal, bodies included, is kept in IndexedDB
  (`idbStore`, database `lcars`, stores `rows` and `meta`), scoped to the
  server URL and user. A boot paints from it with no request at all, then
  `deltaSync` asks two `/dump` questions and `/stats`, in parallel:
  `modified_since=<mark>` (edits and soft deletes — every write path stamps
  `last_modified_at_utc`) and `min_id=<maxId+1>` (new rows, including
  backdated imports, whose stamp can sit far below the mark). An unchanged
  journal is three tiny responses.
- **The mark is a server stamp, never the device's clock**, and only moves
  with rows written in the same IndexedDB transaction: it is the newest
  `last_modified_at_utc` in one snapshot-consistent answer (the `/dump` or the
  first page of a load, the `modified_since` answer of a sync). Anything
  written after that answer was served is stamped no earlier than it, and
  `modified_since` is inclusive, so nothing written after the mark is missed,
  whichever order two tabs' writes land in. The mirror holds server rows
  only — never the objects the page edits.
- **The count is the last check.** Rows are never hard-deleted through the
  API, so `/stats?deleted=all` must equal what is held. A mismatch gets one
  more sync (a row created between the answers), and after that a full load.
  The weekly prune (`scripts/db-prune.py`, old delivered `crew_inbox` rows)
  is the one hard delete, and it takes exactly this path: the server's
  watcher sees the commit, each open page syncs, holds more than the count
  and does one full load, which replaces the mirror; the next boot syncs
  from it as usual (`scripts/test_prune.py --real`). Ids are AUTOINCREMENT,
  so a pruned id is never reused and the mirror's `maxId` stays true.
- **The full load** (first visit, another server, a failed check) races the
  first 1000-row metadata page (~25KB gzipped, paints the list) against one
  `/dump` of everything. The paged sweep it replaced is still there, as the
  fallback for a server without `/dump` (a 404, remembered for the page's
  lifetime) and for a dump that fails partway. A partial load is never
  mirrored.
- A `localStorage` warm cache (300 rows) is written only when the mirror
  cannot be, and deleted when it can.

**Threads** are not stored anywhere but in the bodies: an entry whose first
line is `↪ continues [Title](((id)))` (`THREAD_RE`, `threadParentOf`)
continues that id. `threadIndexJob` reads every row's parent into a map,
rebuilt when the journal's signature moves (the `wikiIndex` rule), and
`threadRows` walks up to the start and back down in creation order. Continue
(`continueEntry`) only writes that first line; the reader's Thread block,
the thread view (`openThread`) and the list's `↪ #id` flag all read it.

The QuickJS suite swaps `mirrorStore` for a Map and turns the fake API's
`/dump` on (`DUMP_ON`) only for the mirror tests, so every older test still
exercises the paged sweep that an older server gets.

### Offline: the outbox

The mirror makes reading work with no network; the outbox ("offline: the
outbox" in `index.html`) does the same for writing. **`api()` is the only
thing that knows about it.** The page has about thirty write paths and none
of them changed: a request to `/entries` or `/entries/<id>` that gets no
answer at all is answered from the device instead (`obRoute`, `obServe`), and
the caller carries on as if the server had replied.

- **One op per entry.** `row` is the entry as this device has it, `fields`
  the columns it changed, `base` the server's row before the first change.
  Ten autosaves are one PUT. A DELETE is a `deleted: 1` edit.
- **Local ids** start at `LOCAL_ID` (2·10⁹): above every real id, so a new
  entry sorts first and never collides. When the create reaches the server,
  the row object on screen takes the real id in place. `ob.remap` sends a
  stale local id held by a closure to the right row, and `obRelink` rewrites
  `((id))`/`#id` links to it in other waiting entries. Creates are sent
  before edits.
- **While an entry has an op, every request about it is answered locally,
  even with the link up**: ops are sent in order, and a read must see what
  is still waiting.
- **Conflicts** are found at send time. The server's row is read again, and
  if its `last_modified_at_utc` is not the base's, the op is merged three
  ways (`obMerge`). A column only one side changed takes that side. A column
  both changed is the question (`obAsk`). For text, `merge3` (line diff3 over
  an LCS match, `lineMatch`) gives the suggestion, which the writer can keep,
  edit, or swap for either side whole.
  - **The base** is the GET of that entry this page last saw (`srvSeen`),
    else the mirror's row (`mirrorGet`) when its stamp agrees. The row on
    screen is the last resort: several paths change a field on the row
    before they send it. Every GET of one entry is also written into the
    mirror (`obSeen`), so the base survives a reload. The mirror still
    holds server rows only: `mirrorWrite` substitutes the base for a row
    with an op, and leaves out local ids.
- **Kept** in its own IndexedDB database, `lcars-outbox` (localStorage
  without the files when there is none), scoped like the mirror, and laid
  over the rows (`obOverlay`) after the mirror's paint, a load and a sync.
  `deltaSync` does not land a row with an op, and its count check leaves
  local ids out.
- **The link** is retried every 20s while anything waits (`obTry`: a flush,
  or `/health` when there is nothing to send), on `online`, and when the tab
  comes back to the front. Coming back runs `bootSync` for what the server
  did meanwhile.
- **Creates are idempotent.** Every `POST /entries` the page makes carries
  an `Idempotency-Key`, named at the first attempt (`api()`, `createKey`) and
  kept with the outbox op across reloads (`op.key`). The server remembers the
  last 256 keys in memory and answers a repeat with the entry it already made
  (`HandlePostEntryKeyed`, `"replayed": true`), holding a mutex across the
  insert so a resend that arrives mid-write waits for it. A create with no key
  (the Shortcut, the CLI) gets the weaker guard in the routes table: the
  same body from the same login within 2s is the first row
  (`HandlePostEntryDeduped`, `X-LCARS-Deduped: 1`). A browser can
  deliver one POST twice beneath anything the page sees (a reused connection
  dropping before the answer), and `test/offline.py` caught an offline create
  landing as two entries about one run in six.
- **Attachments** added offline, or to an entry not yet created, wait as
  blobs in the outbox (`obQueueMedia`) and upload after their entry exists.
- **Passwords.** The Connection dialog opens by itself only on a device
  that holds nothing, or on a page that never stored a password. Every
  request the pages make carries `X-LCARS-Client`, and the server's 401 to
  such a request has no `WWW-Authenticate` — that challenge made the browser
  ask in its own sheet, which an iPhone home-screen app forgets when it is
  closed, so the page never got to ask and keep the answer. With the
  journal on screen and a stored password refused, a 401 shows a *Sign in*
  capsule (`signInCap`), and the writes queue as offline meanwhile.
- **Two tabs** each keep their own outbox in memory and write it whole, so
  edits made offline in two tabs at once can lose one tab's queue (TODO.md).

The service worker keeps to its own scope: the API shares the origin
behind tailscale serve, and must never be cached. A navigation with a
query (the share target, the Capture shortcut) is answered from the cached
page. `test/offline.py` runs all of this in Chromium with the network really
cut, against a scratch server.

### Pins, naps from a sentence, alert conditions (`index.html`)

- **Pins** are entry ids, at most eight (`PIN_MAX`), kept in the same
  `settings`/`views` entry as the saved views, under a `pins` key
  (`viewsDoc`, `pinsParse`), so they travel, merge on a device's first whole
  load and are polled exactly as the views are; localStorage
  (`lcars.pins`) paints them before the journal lands. A deleted or not yet
  loaded entry keeps its pin and shows no chip. They show as chips above
  the list (`pinsPaint`), the reader's ★ and the ⋯ sheet (`#bPin`), a
  palette section, and "computer, open <title>".
- **A child's naps** (`napParse`): a line about the child sleeping, or a
  nap, with two wall-clock times, is offered among the editor's
  suggestions as a row of the child's sleep kind (docs/design/kinds.md) on
  the entry's local day; one tap creates it as the captain (`napLog`), the
  sentence is left as written. A nap whose start already has a live row of
  that kind is not offered, which also keeps a second tap from making two.
- **Alert conditions** (`alertState`, `alertTick`): red when the link is
  down, an outbox op is refused or held, a save failed, or a task kind's
  open entry is past its `start_date` (not the crew's); yellow while a save
  is on the wire or an outbox op waits. Read on a 500ms timer from state
  already in memory (the overdue sweep cached on the rows), and applied
  only after it has held for `ALERT_HOLD_MS` (2s) either way, so an
  autosave never flashes the console. `body[data-alert]` redefines the
  LCARS colours (`--orange`, `--amber`, `--gold`, `--salmon`), never
  `--txt`; `#halert` in the header says why.

### Counters, the map of a day (`index.html`)

- **Counters** (`counterSaid`, `counterLog`): "log a diaper" / "count a
  feed" writes a `counter` row, the thing in the singular as its title
  (`counterThing`), `value_int` 1, no body. One row per count, rather than
  one row a day with a running total, so a count is an append with no
  read-modify-write (two devices counting at once cannot lose one) and
  Undo is a delete. `counterTally` sums them by title for Stats (today and
  the last seven days); `crew_tool.py`'s `week_numbers` does the same for
  weekstats. `measureSeries` leaves the kind out: a line of 1s is no trend.
- **The map of a day** (`dmPaint`, `dmDraw`): there is no geo column; a
  place is what /location types into a body, "Place (lat, lon ±acc m)"
  or bare "lat, lon ±acc m" (`locText`), and `dmPlaces` reads it back,
  wanting three decimals so a number in a sentence is not a place. The
  day page (and `openTripMap` over a trip's days, routed as `places`)
  draws a pin per place, the trips' recorded GPX tracks that ran on those
  days (`crsTrackGet`, shared with the course map) and drive rows' places
  as a line, on the course map's Leaflet and tiles. The map is built only
  when asked for (the choice kept in `lcars.daymap`), so a day page that
  is only read costs one regex over its bodies; a repaint redraws only
  when the pins moved (`dm.sig`), and `closeOv` takes it down.

## CalDAV (Apple Reminders)

`lcars_caldav.h` publishes the task entries as CalDAV collections of VTODOs,
which is what Apple Reminders — and every other calendar client — speaks.
**A list is a kind**: the task kind (the `task` role's, `lcars_kinds.h`,
default `task`; `$LCARS_TASK_KIND` still overrides it, deprecated)
is the list *LCARS Tasks*, and every kind under it — `task_personal`,
`task_work`, … — is a list of its own (*Personal*, *Work*).
It shares the HTTP server, its Basic auth and its per-connection arena;
nothing about it is reachable without credentials except `OPTIONS`.

| URL | What it is |
|---|---|
| `/.well-known/caldav` | Bootstrap. `PROPFIND` here (or on `/`) answers `current-user-principal`, which is all a client needs to find the rest |
| `/caldav/principal/` | The single user principal; carries `calendar-home-set` |
| `/caldav/calendars/` | Calendar home. `Depth: 1` lists every list. `MKCALENDAR` below it makes one |
| `/caldav/calendars/<list>/` | One list: `PROPFIND` (with `CS:getctag` and `DAV:sync-token`), `REPORT` `calendar-query` / `calendar-multiget` / `sync-collection`, `PROPPATCH` (name, colour, order), `DELETE` (hides it). `<list>` is `tasks` for the task kind, the kind's own name for the others, and whatever URL the client chose for a list it made |
| `/caldav/calendars/<list>/<name>.ics` | One task: `GET`, `PUT`, `DELETE`, `MOVE`, each with `ETag` and `If-Match` |

Field mapping, and where everything else goes:

| VTODO | entries |
|---|---|
| the collection | `kind` |
| `SUMMARY` | `title` |
| `DESCRIPTION` | `content` |
| `STATUS` / `COMPLETED` / `PERCENT-COMPLETE` | `done_bool` |
| `DTSTART` / `DUE` | `start_date` / `end_date` (and kept verbatim too, see below) |
| `UID`, resource name | `caldav_tasks.uid` / `.resource_name` |
| `DTSTAMP`, `CREATED`, `LAST-MODIFIED` | regenerated from `created_at_utc` / `last_modified_at_utc` |
| `PRIORITY`, `RRULE`, `VALARM`, `URL`, `X-APPLE-*`, `VTIMEZONE` | kept verbatim in `caldav_tasks.extra_ical` / `.extra_vcal` |
| — | `deleted = 1` removes the task from the collection; the row survives |

The side tables are all created on the first CalDAV request, and nothing
else reads them; a database that never sees one never grows them:

- `caldav_tasks` — per task: resource name, UID, the kept lines (what makes
  the round trip lossless — Reminders can set an alarm or a repeat this
  schema has no column for, and get it back unchanged), and `sync_start`/
  `sync_end`, the schedule those lines last said.
- `caldav_lists` — per list a client made, renamed, recoloured or deleted:
  its URL segment, name, colour, order and `hidden`. A kind with no row is
  published with defaults (the name from the kind, a colour from the LCARS
  palette by the kind's hash).
- `caldav_moves`, filled by a trigger on `UPDATE OF kind ON entries` — the
  list a task left and the name it had there. It is the one change to the
  journal schema (a trigger, no column), and it exists because "this task
  left your list" is the one thing a sync report must say that nothing else
  remembers. Any writer moves a task — Reminders, the web UI, `lcars-cli` —
  so it has to be the database that notices.
- `caldav_meta` — what the server has learnt; today only `zone` (below).

Design notes worth keeping in mind before changing any of it:

- **A list made in Reminders becomes a kind**: `MKCALENDAR` with the name
  *Groceries* makes `task_groceries` (ASCII letters and digits of the name,
  the rest one `_`), at the URL the phone chose. A name whose kind is
  already a list gets `_2`; one whose list is **hidden** brings that list
  back instead. A collection asking for events only is refused (403
  `supported-calendar-component`).
- **A list's name is not its kind.** `PROPPATCH` stores the display name,
  colour and order in `caldav_lists` and never renames the kind: the kind is
  the journal's identity for those tasks. Any other property is refused
  per property (403 inside the 207, echoed in its own namespace) — answering
  200 to a write that went nowhere would show a change that reverts on the
  next sync.
- **Deleting a list hides it.** The collection is gone for every client and
  every entry in it stays exactly as it was; the web UI's reminders panel
  says so on a task of that kind. A `MKCALENDAR` of the same name is the
  undo. The task kind's own list is always published, even empty, and a
  sub-kind stays a list as long as any entry ever had it — deleting a list's
  last reminder must not make the list vanish under the phone.
- **Moving a task between lists re-kinds the one entry.** Reminders moves a
  task by writing it into the new list and deleting it from the old one. A
  `PUT` whose name or UID is a task in another list (or a soft-deleted one)
  is that task (`caldav_find_elsewhere`), so the entry keeps its id, and the
  old list's `DELETE` then finds nothing there. `MOVE` does the same for
  clients that say it.
- **The due date is the schedule.** Reminders writes a dated reminder as
  `DTSTART` and `DUE` with one wall clock and a `TZID`
  (`DUE;TZID=Europe/Madrid:20261007T150000`), an all-day one as two DATEs,
  its alert as an absolute `TRIGGER` at the due instant. A `PUT` reads them
  (`caldav_derive_schedule`) into `start_date`/`end_date`: timed, a block of
  no length at the due time (never an empty end — the web UI reads "start,
  no end" as a running stopwatch); all day, midnight to midnight. The
  columns are written **only when the lines' dates moved since the last
  write** (`sync_start`/`sync_end`), so a phone that edits a title does not
  undo a reschedule made in the journal meanwhile. The other way, while the
  columns still equal the sync values the lines go out verbatim (their
  `TZID` and form survive); once something else moved the task, `DTSTART`/
  `DUE` are rewritten from the columns (`caldav_effective_extra`) — whole
  days of midnights as DATEs, anything else in UTC — and every absolute
  alarm moves by as much as the start did. A task scheduled in the journal
  for the first time gets an alert at its due time, which is what Reminders
  would have made. The JSON view hands the page these effective lines, not
  the stored ones, because those are what it edits and PUTs back.
- **Time zones are read from tzdata by hand.** A `TZID` wall clock needs a
  real conversion, and libc's is `mktime()` under `$TZ` — process-global,
  which a thread per connection cannot set. So `caldav_zone_load` reads
  `/usr/share/zoneinfo/<TZID>` itself (TZif v2: the transitions, then the
  footer's POSIX rule for the years past them, which is all a "slim" tzdata
  has). A name that is not a plain zone path is read as UTC, never opened.
  Dates without a zone (all-day ones) are read in `$LCARS_TZ`, else the zone
  the phone last wrote a `TZID` in (`caldav_meta`), else UTC: the phone knows
  where the user is, and this box, seven hours away, does not.
- **`DTSTAMP` is the row's `last_modified`, not "now"**, so two GETs of an
  unchanged row are byte-identical. The `ETag` is a hash of exactly those bytes,
  and an ETag that moved on its own would make every client re-download
  everything, forever. A `PUT` answers **no** ETag (RFC 4791 5.3.4: the
  server rewrites what it stores — `DTSTAMP`, `PRODID`, the order — so the
  client must fetch it back), and properties are written before the
  `VALARM`s, as RFC 5545's grammar has it.
- **The ctag** (`CS:getctag`) hashes every row of the list — id, stamp,
  completion, deletion, schedule, kept lines — plus the moves out of it and
  the list's name and colour. That is the poll clients use to decide
  whether to re-list.
- **`sync-collection` needs no change log.** The token is the list's newest
  stamp plus its ctag. "Since T" is the rows stamped at or after T (every
  write path stamps, deletes are soft, so a deleted one is a 404) plus a 404
  for every move out of the list after T. Inclusive, so a write in the same
  second as the last answer is never missed (a task reported twice costs the
  client one ETag compare); and if the ctag half still matches, nothing
  changed and the answer is empty. A token that is not ours is a 403
  `valid-sync-token`, which sends a client back to a full listing.
- **`calendar-query` honours "open tasks only"** (`COMPLETED` is-not-defined,
  or `STATUS` not matching `COMPLETED`), so years of finished tasks need not
  be listed. Every other filter is answered with the whole list and the
  client narrows it — the alternative is a filter interpreter for a
  collection that holds one component type.
- **`PROPFIND` bodies are not parsed at all.** Every property this server knows
  about a resource is returned; a property a client asked for and does not see
  reads as absent, which is what it means. What *is* scanned is a `REPORT`
  body (which report, which hrefs, the token, the open-only filter) and the
  `<set>`/`<remove>` blocks of a `PROPPATCH` or `MKCALENDAR`.
- **`DELETE` of a task is the same soft delete** as the UI and the JSON API, so
  a sync accident in Reminders destroys nothing. A later `PUT` of the same
  resource name or UID restores the row rather than inserting a duplicate.
- **The web UI edits the kept lines** (`/entries/<id>/caldav`, the reader's
  *reminders* panel — `openCdav` in `lcars-ui/index.html`). They go in as
  text and are spliced into the VTODO verbatim, so the PUT is checked
  before it is stored (`caldav_check_extra`): every line `NAME[;params]:value`,
  components balanced and never `VTODO`/`VCALENDAR`, and none of the
  properties the row itself writes (`UID`, `SUMMARY`, `DESCRIPTION`,
  `STATUS`, the three stamps) — any of those would go out twice. A PUT
  carrying the `etag` it read is a 412 if Reminders wrote in between. The
  write stamps `last_modified_at_utc`, which moves the task's ETag, the web
  UI's delta sync and the ctag, and a moved `DUE` moves the schedule like a
  CalDAV PUT does. A UI-made task that gets lines gets a side row under the
  name and UID it was already published with (`lcars-<id>.ics`,
  `lcars-<id>@lcars`), so no client sees it move.
- **Every task links back to its entry.** Unless the kept lines carry a
  `URL` of their own, one is written: `<web UI>#e=<id>`, the page's deep
  link. The base is `$LCARS_UI_URL` (`0`: no link), else, for a request that
  came through tailscale serve (a `Host` on `*.ts.net`), `https://<host>/ui/`;
  other clients get none. It is per request, so a task's ETag is per host
  too, which each client sees consistently.
- **`$LCARS_CALDAV_LOG=1`** prints every CalDAV request (method, path,
  Depth, User-Agent, the first 4KB of the body) to the journal. It is how to
  learn what a client really sends; off by default, because the bodies are
  task text.
- One task's iCalendar text is built in a **separate 512KB scratch arena**, not
  the connection arena the response is growing in — that is what lets a
  500-task listing cost one task's worth of scratch. It lives on the connection thread's stack, never in a `static`, because
  connections are served concurrently; the task kind
  (`caldav_load_task_kind`, read from the role at the top of each request)
  and the default zone are `_Thread_local` for the same reason.
- `lcars-ui/test/caldav.py` drives a scratch server through all of the above
  with raw WebDAV (~40s with the build). Run it after touching this file.

What Reminders cannot get from any CalDAV server, this one included: tags,
sections, flags, subtasks shown as subtasks, attachments and smart lists are
iCloud-only (Reminders hides or flattens them on a CalDAV account), and
changes made elsewhere reach the phone only when iOS polls or the list is
pulled down — push needs Apple's own notification service.

Adding the account on iOS/macOS: *Settings → Apps → Calendar → Accounts → Add
Account → Other → Add CalDAV Account*, server = the LCARS host (with the port),
user/password = the HTTP API's Basic auth credentials. The list shows up in
Reminders. **Basic auth over plain HTTP sends those credentials in the clear on
every poll** — put the server behind TLS or on a private network (Tailscale)
before pointing a phone at it over the internet.

## Command-line client (`lcars-cli`)

`make lcars-cli` builds a separate program (`lcars_cli.c` + `lcars_cli.h`) that
reads and writes `entries` from a terminal, **through the HTTP API only**
(`LCARS_URL`, default `http://127.0.0.1:8080`; Basic auth from `--user`/
`--password` or `LCARS_AUTH_USER`/`LCARS_AUTH_PASS`). It links libcurl and
nothing else. Until 0.177.0 a `--db` mode opened `lcars.db` itself with a
second copy of the server's queries; it was a second writer that stepped
around everything the server enforces (the limited logins' kinds, CalDAV's
side tables), and it went. With the server down there is no CLI.

```sh
lcars-cli list --kind work_log --limit 20
lcars-cli get 42 --raw > entry.md
lcars-cli new --kind task --title "Write the CLI" --edit
lcars-cli set 42 --title "Renamed" --done 1
lcars-cli edit 42                 # $EDITOR on the entry's content
lcars-cli append 42 -c "More."    # add-only: POST /entries/42/append
lcars-cli rm 42 && lcars-cli restore 42
lcars-cli logseq import --dry-run # see the Logseq bridge below
```

Commands: `list`, `get`, `new`, `set`, `edit`, `rm`, `restore`, `done`/`undone`,
`due` (a task's due date in Apple Reminders, through `/entries/<id>/caldav`),
`kinds`, `stats`, `logseq` and `strava` (their own subcommand families — see below). `--help` prints the full flag set; every `GET /entries` filter
has a flag (`--kind --search --date --since --until --modified-since
--modified-until --done --deleted --min-id --max-id --scheduled-date
--scheduled --order --dir --limit --offset`) except `scheduled_since`/
`scheduled_until`. `new`/`set` take `--start`/`--end` (`""` unschedules),
and every timestamp flag also accepts `YYYY-MM-DD HH:MM`, completed to
`:00` (`:59` as an upper bound) before the server sees it, which takes only
the other two shapes. Answers are parsed into `EntryRow`s and printed by one
renderer; `--json` rebuilds the API's own JSON from them. Filter validation
lives in the argument parser: an `--order` value the server would 400 on is
rejected before a request.

Things worth knowing before changing it:

- **`list` omits entry bodies unless `--content` is passed.** The table never
  shows them and the server builds each response inside a 1MB connection arena,
  so "200 entries with content" is a default that 500s on a real journal.
- **The JSON reader is a scanner, not a parser** — it walks values and hands
  back spans, but it is string-aware: an entry whose *content* contains the
  text `{"title":` must not be mistaken for structure, and in this journal that
  is not hypothetical. The server reads request bodies with the same scanner
  (`json_get_*` in `lcars_http.h`, since 0.177.1), so a key is always a
  member of the top-level object and a string's escapes, `\u` included, are
  decoded whole.
- **Deletes are soft, and there is no hard delete** — same reasoning as the API:
  `restore` is the undo.
- **`new`/`set` can backdate a row** (`--created-at`, and `--modified-at` on
  `new`). That is not a convenience — it is the reason the Logseq import can
  exist at all, and it is why `POST /entries` grew the same two fields.

## Logseq bridge (`lcars_logseq.h`)

`lcars-cli logseq <sub>` syncs `entries` with a [Logseq](https://logseq.com)
graph in both directions. It exists for two jobs: pulling in the years of
journals written *before* this app existed, and keeping a copy of what it
records *since* — Logseq as the human-readable backup.

```sh
lcars-cli logseq pages                      # what the graph has
lcars-cli logseq show 2021-02-11            # one page's markdown
lcars-cli logseq import --dry-run           # Logseq -> lcars
lcars-cli logseq export --today             # lcars -> Logseq
lcars-cli logseq status                     # per-day counts, both sides
```

Everything goes through Logseq's own local HTTP API (`POST /api`, a bearer
token, `{"method": ..., "args": [...]}`; enable it under *Settings → Features →
HTTP APIs* and create a token there). `LOGSEQ_URL` defaults to
`http://127.0.0.1:12315`, `LOGSEQ_TOKEN` carries the token; `--logseq-url` /
`--logseq-token` override both. The graph directory is **never touched
directly** — Logseq holds unsaved edits in memory and rewrites the files on its
own schedule, so a file written behind its back is a file it will overwrite.

### Import (Logseq → lcars)

One entry per Logseq page. Journals land in kind `logseq_journal` titled with
their ISO date (`2021-02-11`); the standalone pages land in kind `page` titled
with the page name. The content is `:file/content` — the page's markdown byte
for byte, nesting and all, not a re-render of the block tree.

- **`:block/journal-day` is the only timestamp Logseq keeps.** `created-at` /
  `updated-at` are stamped at *re-index* time (every page in a re-indexed graph
  shares one value to the millisecond) and the files inherit the mtime of
  whichever sync last copied them. So a journal is backdated to its own day, at
  00:00:00 UTC, and **a page is not backdated at all** — there is nothing to
  backdate it to, and inventing a date would be worse than admitting the import
  time.
- **Re-running it is a no-op.** The Logseq identity *is* the entry title, so
  "have I imported this?" is one string compare against the titles already under
  that kind — no marker column, no side table. Soft-deleted entries count as
  imported: something thrown away must not come back on the next run.
- **`--until` defaults to the day before lcars started** (`LOGSEQ_LCARS_FIRST_DAY`
  in `lcars_logseq.h`). From that day on the journals are a hand-made copy of
  these very entries, and importing them would duplicate the database into
  itself.
- Pages Logseq materializes for every `[[link]]` and `#tag` — roughly 60% of the
  page table, with no file, no content and no date — are skipped, as are
  whiteboards (`.edn`, a serialized canvas) and pages whose whole body is a bare
  `-` or a `title:` front matter.
- The import reads one page at a time into a **separate 16MB scratch arena**,
  reset between pages. A full graph is ~6MB of markdown across ~1500 pages; the
  budget is sized for the largest page, not for the graph.

### Export (lcars → Logseq)

One block per entry, appended to that day's journal page as
`HH:MM [kind] text` — with the entry's title on the first line instead, when it
is one the user actually typed (everything posted without a title gets
`HTTP Entry`, and repeating that on every line would bury the journal).

- **The time is local wall clock**, because that is what the journals hold. An
  entry stamped `20:46:34` UTC was typed at 23:46 in a UTC+3 zone and belongs
  under that day's page. The day → UTC range conversion goes through `mktime`
  so the two days a year whose local midnights are not 24 hours apart still
  come out right.
- **The skip rule is the whole design.** An entry whose `(HH:MM, kind)` slot is
  already on the page is skipped, so a day that was filled in by hand in that
  format exports as zero writes, and a second export over a day this wrote
  writes nothing either. That is what makes it safe on a timer.
- **Nothing is ever deleted or rewritten.** Blocks that do not parse as an
  export line are the user's own outline; they are not even a landing site for
  an insert. New blocks go in front of the first *export* block older than
  them, which keeps the newest-first order these journals use, and the block
  list is re-read after each insert rather than patched locally.
- **Entries the import created are excluded** unless `--kind` names them.
  They came from Logseq; sending them back would copy 1400 journals into today's
  page. Nothing in an entry records its origin except its kind, so the two
  directions have to be told about each other explicitly.
- `scripts/logseq-export.sh` is the automated form: today plus yesterday (an
  entry written just before local midnight can still arrive after the day
  rolled over), safe to run on a 30-minute timer.

## Strava (`lcars_strava.h`)

`lcars-cli strava <sub>` brings the captain's Strava activities into the
journal, one `workout` entry each, on an hourly user timer
(`scripts/lcars-strava.{service,timer}`). Strava → lcars only.

```sh
lcars-cli strava auth                       # the URL that grants access
lcars-cli strava auth '<code or address>'   # trade the code for tokens
lcars-cli strava pull [--since 2010-01-01] [--dry-run]
lcars-cli strava status                     # who, the last pull, how many
```

**Everything is an outbound pull.** The server listens on loopback behind
tailscale serve, so Strava has nothing to call: no webhook, no OAuth
callback. The grant redirects to `http://localhost` (a page that does not
load), and the code is copied out of the browser's address bar. That is why
this is `lcars-cli` work and not a server module.

**The captain's one-time steps** (the timer is not enabled until they are done):

1. Create the API application at <https://www.strava.com/settings/api>,
   with *Authorization Callback Domain* `localhost`.
2. Put its id and secret in `~/.env` on the VPS:
   `LCARS_STRAVA_CLIENT_ID=…` and `LCARS_STRAVA_CLIENT_SECRET=…`.
3. Rebuild the CLI the timer (and the linker) runs. Since 0.276.2 that is
   `~/lcars/bin/lcars-cli`, the one binary's link, which every deploy that
   rebuilds C rebuilds: nothing to do. Before it (the copy retired in
   0.279.2; this is history),
   `~/lcars/lcars-cli/` was a gitignored directory of *copied* sources with
   vendored curl headers and its own `build.sh` (Debian there has no
   libcurl dev package; its README.md says why). So, on the VPS:
   ```sh
   cd ~/lcars/lcars-cli
   cp lcars-cli lcars-cli.prev       # the way back
   cp ~/lcars/lcars_cli.c ~/lcars/lcars_cli.h ~/lcars/lcars_logseq.h \
      ~/lcars/lcars_strava.h ~/lcars/lcars_arena.h ~/lcars/lcars_json.h .
   # (the README's lcars_string.h is no longer in the repo; the copy there
   # is a leftover nothing includes)
   # once: add -lm to build.sh's cc line (round/lround/fabs in
   # lcars_strava.h); build.sh lives outside the repo
   ./build.sh
   (set -a; . ~/.env; set +a; ./lcars-cli stats)   # the smoke test
   ```
4. `set -a; . ~/.env; set +a; ~/lcars/bin/lcars-cli strava auth`,
   open the URL it prints, authorize (leave *View data about your private
   activities* ticked: the scope is `activity:read_all`), and copy the
   address the browser lands on (`http://localhost/?state=&code=…&scope=…`).
5. `lcars-cli strava auth '<that address>'` (the bare code works too).
6. `lcars-cli strava pull --since 2010-01-01 --dry-run`, read what it would
   create, then the same without `--dry-run`.
7. Enable the timer: `for u in lcars-strava.service lcars-strava.timer; do
   scripts/crew.py unit $u > ~/.config/systemd/user/$u; done &&
   systemctl --user daemon-reload && systemctl --user enable --now
   lcars-strava.timer` (`crew.py unit` writes the unit for this box: its
   `%h/lcars` made `$LCARS_HOME` when that is set).

**The entry.** Kind `workout`; title the activity's name; `created_at_utc`
its `start_date` (UTC); `value_float` the distance in km (to the metre),
`value_int` the moving time in minutes. The web UI's `reading()` takes
`value_float` first, so a workout with a distance charts as kilometres; one
without (a gym session) reads as its minutes, in the same series. The
content is three paragraphs:

```
Run · 10.02 km · moving 52:10 · elapsed 55:03 · 120 m up · HR 148 avg / 172 max · 5:13 /km · 650 kcal

<the activity's description, if any>

strava: https://www.strava.com/activities/9000000002
```

Pace for runs (`Run`, `TrailRun`, `VirtualRun`), km/h for the rest; heart
rate, elevation and calories only when Strava has them.

- **The last line is the identity.** No column, no side table: a pull looks
  each activity up with `list --kind workout -q strava.com/activities/<id>`,
  `--deleted all`, and then compares whole lines (`q` is a substring match,
  and `/activities/12` is a prefix of `/activities/123`). Found: title,
  content and the two numbers are updated, never `created_at_utc`. Not
  found: created. A soft-deleted one is left deleted. Anything written
  **below** the identity line is the captain's and survives an update.
  The GPS track (a later slice) will be an attachment in `entry_media`,
  so it changes nothing here.
- **Details only when writing.** The list (`/api/v3/athlete/activities`,
  200 a page, paged until empty) has everything but the description and
  calories, which take one `GET /api/v3/activities/<id>` each. That request
  is made only for a new activity or one whose name, distance or moving time
  no longer match the entry, so an hourly pull where nothing happened is one
  list request. (A description edited alone on Strava is not followed; a
  rename is, and brings it along.)
- **The cursor.** `after` is `--since`, or the last pull minus 7 days:
  Strava filters by start time, and a watch that syncs late uploads
  activities that started before the last pull. A clean pull sets
  `last_pull_epoch` to when it began; one that stopped early to the newest
  activity it finished (the list is oldest first); `--dry-run`, or a failed
  activity, leaves it.
- **Rate limits** (100 requests / 15 min, 1000 / day): a 429 ends the pull
  there, cleanly, with a line saying so and exit 0. Nothing waits or
  retries. A backfill of years is mostly detail requests, so it meets the
  limit after ~100 activities and the hourly timer finishes it over a day
  or two.
- **Tokens.** Strava rotates the refresh token on every refresh, so they
  live in a writable file, `~/.lcars-strava/token.json` (0600, directory
  0700): access and refresh token, `expires_at`, the athlete's id and name,
  `last_pull_epoch`. Refreshed when within 60 s of expiry, and written back
  through a temp file and a rename before anything else, so a crash can
  never leave only the invalidated refresh token on disk. Re-running
  `strava auth` keeps the cursor.
- `LCARS_STRAVA_API` (default `https://www.strava.com`) moves the OAuth
  pages and the API, which is how `lcars-ui/test/strava.py` stands in a
  stub for Strava: the grant, a refresh with rotation, two pages, a re-pull
  that creates nothing and follows a rename, a 429 on the list and on a
  detail. Its identity lines always name www.strava.com.

## Deployment & ops

The example here is the author's deployment; README.md has the short
version, and how to run your own.

- The VPS runs the server on `127.0.0.1:8080`
  (`LCARS_BIND=127.0.0.1` in `~/.env`), as the systemd **user** unit
  `lcars.service` (`lcars -s`, so `systemctl --user`, not the system manager).
  The only way in from outside is `tailscale serve` (`https://<host>.ts.net`
  proxies to `http://127.0.0.1:8080`); everything on the box itself — crew,
  cron, the chat's `lcars-cli`, the deploy health checks — already speaks to
  `127.0.0.1`. The `lcars-fw` nft table (8080 from `lo` and `tailscale0`
  only) predates the bind and is now a second lock, not the only one.
  Since 2026-10-18 the VPS's public IP is blocked at the firewall by the
  captain and not used: nothing reaches the port from the public internet,
  everything comes over the tailnet. The password check for a request not
  from loopback stays, as a further wall.
- A deploy is `scripts/engineer.py deploy` on the box (see "Engineers"),
  which rebuilds with `scripts/vps-rebuild.sh` when C changed.
- **TLS on the API.** An https page cannot fetch an http URL — the browser
  blocks it as mixed content before the request is made, and being publicly
  reachable is irrelevant. `tailscale serve --bg 8080` on the VPS is the
  cheapest fix: a real Let's Encrypt certificate on the node's
  `<host>.<tailnet>.ts.net` name, no DNS record, no open port, and Basic auth
  stops travelling in the clear. It is tailnet-only; `tailscale funnel 8080`
  is the same endpoint exposed publicly.
- `scripts/logseq-export.sh` mirrors the journal into Logseq on a timer. It reads
  `.env`, so by default it *reads* the VPS — nothing in it writes there, but it
  does write into the local Logseq graph.
- The example deployment's own journal tools - pulling and pushing the
  database, swapping the live journal for a filtered copy - are the
  author's, kept out of the public tree with their notes
  (`ARCHITECTURE.local.md`).
- `scripts/db-merge-window.py` brings back what a swap left behind: the
  rows written to a copy of the journal while it was live (the
  example deployment's swap), which the full
  journal never got (its ids reused since). It reads the copy read-only
  (`mode=ro`) and never opens the live file: it asks the server, and
  writes through the API as the captain's login. The window defaults to
  the state file's `filtered_at` to `swapped_at` (`db-swap.sh fresh`
  swaps the new copy in straight after filtering), or `--since`/`--until`.
  Each copy row created or modified in it is NEW (no live row of its
  kind, `created_at_utc` and title, or content when the yeoman retitled
  it: inserted with its stamps, a new id), MOVED (an older row, the live
  one unchanged since the window: PATCHed with `if_modified`, the rows
  first saved by `--undo FILE`), CONFLICT (the live one changed
  too: listed only), MISSING, SKIPPED (`crew_inbox`, `crew_seat`,
  `task_no1`: machinery, or raised again), or PRESENT/SAME (already there:
  what makes a second `--apply` write nothing). The window's
  `entry_media` rows are a finding, not re-attached. A dry run by default,
  `--report` publishes the plan (ids, kinds, titles, stamps, never
  content) through `report.py`; `--apply` writes. It refuses while the
  state file says the copy is live. `scripts/test_db_merge_window.py`.
- `scripts/db-prune.py` is the journal's one hard delete, on purpose
  narrow: `crew_inbox` rows (the seat's delivery slips, `scripts/seat.py`)
  done and untouched for seven days - no1_log keeps what mattered, and the
  slips grew ten times faster than the captain's entries. It opens the live
  `lcars.db` directly (the API has no hard delete, by design) in one
  IMMEDIATE transaction with a busy timeout, and deletes them with their
  rows in every side table with an `entry_id` column (found in
  `sqlite_master`, so a new side table is covered); a slip with media is kept. A dry
  run by default (opened read-only), `--apply` deletes; it refuses when
  `/health` does not answer or the path is not a file, and logs each run to
  `~/.local/state/lcars-eng/prune.jsonl`. `lcars-prune.timer` runs
  `--apply` on Sundays at 05:10 in the captain's zone (Nice 15, idle I/O). After it,
  open pages do one full load (above, "The count is the last check"); the
  Queue view's order times for shipped work are cached when worked out,
  so only a recomputation (a `TIMES_V` bump) finds an older order's slip
  gone, and then counts from the seat's log or the task's start.
- CI (on `main`): build the server and the CLI on ubuntu, start the server
  and ask it `/health` and one entry.

### Scheduled crew roles (`scripts/crew.py`, `crew/`)

Unattended jobs on the VPS that each leave one journal entry a run: the
ops brief at 06:30, the historian (daily, and the month on the 1st), the
science officer's weekly numbers, the yeoman's hygiene list, the security
audit, the librarian's docs-against-code check, the counselor's Sunday
reading of the week's personal logs, and three with no model, the
ship's health, the nightly web suite and the blog post's shares. A role is a file, `crew/<role>.md`:
front matter (schedule, model, the verbs it may run, WebFetch domains,
budget, timeout) and the prompt. `crew.py list` shows them.

**The captain's own context** is not in the role files: who the people in
the journal are, the languages it is written in, a page the science
officer keeps (`writes: append #<id>`), the blog post's URL. It is
`crew/context.local.md` (tracked here, left out of the public tree by its
export, docs/design/open-source.md): its text before the first `## `
heading goes to every role, after its orders, and to a note turn; a
`## <role>` section to that role alone, and may open with a `---` block
of front matter laid over the role's own (`local_context` in crew.py).
Without the file every role runs on its generic orders. The owner's name
in every brief is `LCARS_OWNER` (the environment, then `~/.env`, as
`crew_tool.owner` reads it); unset, a brief says "the captain's" alone.
The engineers' and Number One's (`owner_is` in engineer.py) and the
computer's (`ChatSystemPrompt`, `ChatVoicePrompt` in lcars_chat.h) take it
the same way, and the voice prompt's mishearings (the names the recogniser gets wrong) are
`LCARS_VOICE_HINTS`. CLAUDE.md likewise keeps the rules of any checkout;
this deployment's (where production is, its danger zones) are
`CLAUDE.local.md`, which it imports.

**The captain's zone.** The box may run in another zone than its owner
(the VPS runs America/New_York, seven hours behind), so every day, time
and schedule of the crew's is the captain's: `crew_tool.crew_zone()` is
`LCARS_CREW_TZ` (the tests'), else `LCARS_TZ` from the environment or
`~/.env` (a timer's unit does not source it; the server reads the same
name for CalDAV's all-day dates), else the box's own zone (`/etc/timezone`,
the `/etc/localtime` link), and a name zoneinfo does not know is the
box's, said on stderr. `lcars-link.sh today` reads it the same way, in sh.
The drop-ins and units are written with it at `crew.py install`/`unit`,
so a changed `LCARS_TZ` reaches the timers only at the next install.

**How a run goes.** `lcars-crew@<role>.timer` (a template; each role's
`OnCalendar` is a drop-in that `crew.py install` writes from the front
matter, in the captain's zone; the units
themselves it writes through `crew.py unit`, as every user unit in
`scripts/` is installed: their `%h/lcars` becomes `$LCARS_HOME` when that
is set, every `OnCalendar=` gets the zone put after it, and the embeddings unit takes llama.cpp's and the model's paths
from `LCARS_LLAMA_DIR`/`LCARS_EMBED_GGUF`, ~/.config/lcars/embed.env) starts
`lcars-crew@<role>.service`, which runs `crew.py run <role>`: Nice 15, idle
I/O, `MemoryHigh=1G`, `MemoryMax=1500M`. The runner takes a global flock
(one crew run at a time: a run's claude or qa suite wants the cores the
seated engineer tests on), waits for `min_free_mb` (default 1000, the
MemoryHigh) of MemAvailable, checks `/health`, then runs `claude -p`
from an empty temporary directory with `--setting-sources project` (the
user's own allowlist, the linker's and the sysadmin's, is not inherited),
`--tools` naming only what the role uses, `--allowedTools` naming each
`crew_tool.py` verb it may run, `--permission-mode dontAsk`, no MCP, no
skills, no session kept, and `--max-budget-usd`. One claude binary,
`/usr/bin/claude` (what the linker's cron job ran too). Exit 75 is "skipped" (lock, memory, server),
logged and not a unit failure.

**The wrapper.** `scripts/crew_tool.py` is the agent's only command, the
same shape as the linker's `lcars-link.sh`: it reads `LCARS_CREW_USER`/
`LCARS_CREW_PASS` from `~/.env` itself, so no password is in an argv or the
agent's environment; it passes `list|get|stats|kinds` to lcars-cli as the
crew login and refuses `--url` and the credential flags (and `--db`, which
lcars-cli no longer has); and it has
helpers that fetch and count in Python (`agenda`, `onthisday`, `month`,
`weekstats`, `counsel`, `hygiene`, `trip`, `audit`, `docs`), because arithmetic is not
judgement and every tool call is a turn that re-reads the conversation. The
same goes for a choice with a rule: `agenda` names the morning brief's
weather place and why (a trip running today; else the newest trip of the
last three days if it has not ended; else home, a `home` key in a `settings`
entry, or the city of the captain's zone; none for a zone with no city,
and then no forecast), since a model left to it took the newest trip and
never asked whether it had ended (0.202.0). `hygiene` opens with
secrets: token- and key-shaped strings in the captain's own kinds (known
prefixes, JWTs, Bearer values, `password:`-style lines, long random runs),
each as the entry, a masked preview (first characters and length) and what
it looks like - the value itself is never printed, and is masked in the
other sections too; the yeoman reports them first, the one finding that may
be URGENT. `trip` lists the trips ended since the historian's last post, and
`trip <id>` lays one out planned against actual (its stops and legs; the
drive legs, entries, places, attachments and money lines of its days, in
the zone it was planned in) for the historian's retro. Its
one write, `post`, is the runner's: the agent's final answer becomes one
entry of kind `crew_<role>` (a footer gives turns, tokens and cost), and a
line `URGENT: ...` in it one `task_crew` (the Crew list in Reminders). The
agent is never allowlisted for `post`, `post` refuses under
`CREW_IN_AGENT`, and the server lets the crew login write only `crew_*` and
`task_crew`. A failed run posts a short failure entry instead. Every run is
a line in `~/.local/state/lcars-crew/runs.jsonl`, which the ship's health
report reads back.

**Folded in (0.143.0): the linker and the sysadmin check.** Both were cron
jobs running agents from `~/.claude`; their scripts and prompts now live
here and run under the crew timers, with `brief: own` (the old agent's
prompt stands alone) and a `pre:` script whose output heads the entry:

- `crew/yeoman-linker.md` (23:12, the old cron time, over that local day)
  posts a `crew_yeoman` entry: `measure` first, then the linker agent.
  It keeps its own write path: `scripts/lcars-link.sh` (moved from
  `~/.claude/scripts`) sources the **captain's** login from `~/.env`,
  allows `cli list|get|stats|kinds`, `scan`, `measure` and `apply`, and
  `scripts/lcars_linker.py apply` splices `[[`/`]]` by offset, checks each
  entry's hash before writing and logs every change to
  `~/lcars/lcars-linker-logs/<date>.md`. The agent is allowlisted for that
  one script and for reading its scan files in `~/.lcars-linker/`; the crew
  login is not used for it and stays limited to `crew_*`. The hourly
  `lcars-link.sh measure` stays a cron line, pointed at the repo's copy.
- `crew/ship.md` (06:05) is the ship's checks (`pre: ship`) and then the
  sysadmin agent's patch report, with the same read-only command allowlist
  it had in `~/.claude/settings.json`.

Their old cron lines are commented out, with a date, once a timer run has
worked; `~/.claude/agents` and `~/.claude/scripts` are left in place. Tests:
`python3 scripts/test_crew.py` (stub claude, stand-in server). A run's
working directory and Claude's scratch for it go when it ends, failed or
not; a run killed outright leaves them to the next run's sweep.

**The blog post's shares (`crew/shares.md`, `scripts/shares.py`, 0.258.0).**
The captain shares a blog post (the role's `post:`) in several places and
keeps one journal entry of kind **`share`** per place, written from their
phone: the first URL in its content is the share (the reddit thread, the HN
item, the toot, the tweet), the title names the place (`r/ClaudeAI`), and
it is created when they posted. A template (kind `template`) whose body is
`kind:: share` and a line for the URL makes one in a tap. Every six hours
(02:10, 08:10, 14:10, 20:10) the role reads them with the crew login and
writes, with no model:

- a reading per share, kind `crew_share_<id of the share entry>`: value_int
  the main count (reddit's score, HN's points, Mastodon's favourites, a
  manual line's likes), the title that number first (`312 score ·
  r/ClaudeAI`, as `/log` titles a reading), the content a short JSON
  (`share`, `title`, `url`, `source`, `main`, `value`, what the source gave:
  `score`, `upvote_ratio`, `comments`, `points`, `favourites`, `reposts`,
  `views`..., `blog_views` with `blog_views_site` and `blog_views_shared`,
  `fetched_at`, an `error` when an API failed and the line stood in);
- the run's own entry, kind `crew_shares`, the global reading: value_int the
  sum of the shares' main counts, the content JSON (`value`, `comments`,
  `shares`, `by_share`, `blog_views`, `blog_views_by_site`,
  `blog_views_from_shares`, `stale`, `missing`, `errors`), no footer.

A kind per share because the Stats view charts every kind with two numbers
or more as one series (`measureSeries`): one kind for all would be one line
zig-zagging between reddit and HN. `crew_*` because the crew login writes
only those - no server rule changed. Sources: reddit's OAuth API with
app-only credentials (`client_credentials` at
`www.reddit.com/api/v1/access_token`, then `oauth.reddit.com/api/info`;
`LCARS_REDDIT_CLIENT_ID`/`LCARS_REDDIT_SECRET` in `~/.env`), as the box is
refused reddit's `.json` pages; a share link (`/r/x/s/<code>`) cannot be
resolved from here, so the entry needs the `/comments/<id>/` URL. HN through
Algolia (`hn.algolia.com/api/v1/items/<id>`, comments counted over the
tree), Mastodon through the instance's public `/api/v1/statuses/<id>`. X
and LinkedIn have no API: the captain adds a line of numbers to the share
entry (`12 likes, 3 reposts, 800 views`; `1.2k`, `·` and `;` are fine), and
the newest such line is the reading; it stands in when an API fails too. A
share with neither gets no reading that run (a repeated old number would
draw a flat line it never had), but its last known value still counts in
the global sum, listed as `stale`. Views of the post come from Cloudflare
Web Analytics (`LCARS_CF_ANALYTICS_TOKEN` with Account Analytics Read,
`LCARS_CF_SITE_TAG`, `LCARS_CF_ACCOUNT_ID` or the token's first account):
page loads of the post's path by referer host, since the share's day, in
30-day queries back at most 180 days. A referer is a site, not a thread:
`www.`/`old.`/`out.reddit.com` are reddit, `t.co` is X, `lnkd.in`
LinkedIn, and **two shares on one site (two subreddits) each carry the
whole site's views**, naming the other in `blog_views_shared`; a Mastodon
reader arrives from their own instance, so only the share's instance is
counted. With no share entries a run writes nothing (run status
`nothing`). Tests: `scripts/test_shares.py`, on saved responses.

**The view (`./shares`, `openShares` in index.html, 0.259.0,
docs/design/shares.md).** Drawn from the rows the page holds, like Stats:
the latest `crew_shares` run as a headline (total, comments, blog views,
shares, when) over a chart of the runs, then a card per `share` entry with
its latest numbers, its readings' chart, Open (the URL) and Entry, marked
stale or missing as the latest run lists it and its error said in words.
`sharesData(rows)` is the model. **+ Share** opens the editor on a new
`share` entry with the body focused for the link. Reached from Stats (its
Blog shares line), "computer, blog shares" and the palette. Stats'
Measurements, the crew's list and the deck's Crew pad leave the readings'
kinds out (`isShareReading`); the demo shows the empty state only.

### Crew notes (`scripts/crew_notes.py`, docs/design/crew-notes.md)

A line of the captain's whose first word, after an optional bullet, is
`@<role>` (a role whose front matter has `notes:`: yeoman, historian,
science, counselor, ops) is a note to that role; lines indented under it
belong to it, and a code fence, a `>` quote or a mid-sentence `@` are not
notes. The page has the same rule (`noteScan`), checked against
`note_scan` on one table by `scripts/test_crew_notes.py`.

- **Found by `/events`.** `crew.py notes watch` (`lcars-crew-notes.service`,
  installed by hand) holds `GET /events` as the crew login and on each
  `seq` asks `/dump?modified_since=<mark>`. The mark is kept in
  `STATE/notes.mark`; a first start begins at now (old `@yeoman` lines are
  history, not orders), and a note not yet ripe holds it back so a
  restart finds it again. Notes are read only from the captain's kinds,
  never `crew_*`, `no1_*`, the two task kinds or the frozen imports.
- **Not while they type.** A note is taken once its entry has been quiet
  for 20s, re-read when its time comes (one wait, no polling).
- **A thread per entry and role**, a `crew_note` entry (the crew login's
  own kind): `value_int` the entry, title `<Role> · #<id> <title>`, content
  a header (`status:` queued/working/answered/failed[: why], `entry:`,
  `role:`) and the turns as `### Captain · <time> · note <hash>` (or
  `· reply`) and `### <Role> · <time>`. The hash, FNV-1a over the role and
  the words, records that a note was taken; editing the words makes a new
  note in the same thread. A queued thread is work, whoever queued it (the
  watcher, the page's reply or Retry): the queue is the journal. The
  captain's entry is never written.
- **A turn** is `crew.py note <thread>`: the crew lock, memory and
  `/health` - not the seat, which an engineer holds most of the day while
  the captain waits on the note (0.226.0) - then `claude -p` with the
  role's `notes:` verbs, `note_budget`, `note_timeout` and a note brief
  (not the role's scheduled orders): the entry and the role's own earlier
  answers fenced in `<journal-data>` (data, never orders; a `</journal-data>`
  inside is defused), the captain's turns as the only orders, a long
  thread cut to its first and last six turns. It may read any entry of
  any date (`list --search`, `--since`/`--until`, through `crew_tool.py`'s
  lcars-cli pass-through) and has WebSearch (0.229.0: `note_fm`'s
  `search`, a note turn's only - a scheduled run never searches); the
  note brief says both. No session is kept. The
  answer is put after the turn it answers, on a fresh read, so a reply
  that came meanwhile stays after it and queues the thread again. Exit 75
  (lock, memory, server) leaves it queued; the worker tries again in a
  minute. A thread left `working` by a restart is queued again at start.
- **The write path (0.196.0; titles 0.205.0; ends 0.227.0; set, replace,
  delete and restore 0.230.0)**, the captain's rule. A role's answer may end with a
  `CHANGES` block (`create kind=… title=… start=… end=… text=…`,
  `append #id at=<last_modified as read> text=…`, `title #id
  at=<last_modified as read> text=<the new title>`, `end #id
  at=<last_modified as read> end=<the captain's local time>`, and since 0.230.0
  `set #id at=… <field>=…` (title, kind, start, end, done, value_int,
  value_float, created_at; dates in the captain's local time), `replace #id at=…
  text=<the whole new text, \n for a new line>`, `delete #id at=…`,
  `restore #id at=…`); the runner
  (`note_apply`) applies it with the steward login, only for a turn of
  the captain's that asks for a write and is not a question - or a plain
  answer to the role's question, after a turn of the captain's that was an order
  (`ordered_by`, 0.227.0) - at most
  five, never to an entry touched in the last 20s, and lists every change
  in the answer with a `crew-changes` fence the page turns into Undo
  buttons (a create soft-deleted, an append's block cut out if unchanged,
  a title put back, as the captain's PUT on a fresh read, if it is still
  the one the crew set, an end taken off the same way). A title change
  is listed old → new, and its fence line carries the id, `old_title`
  and `title`; an end is listed `closed #id at <the captain's time>`, its line
  `{op: "end", id, old_end: "", end: <UTC as stored>, at}`. A set is
  listed field by field old → new, its line `{op: "set", id, old, new}`
  (columns to values, the old from the runner's read just before, which
  the stamp guard makes exact); a replace lists the lines that changed,
  its line `{op: "replace", id, old_text, text}`; a delete and a restore
  `{op, id, kind, title}`. Their Undo puts each field or the text back
  if still the crew's, restores a delete and deletes a restore again.
  A replace may not bring an @role line the captain's text did not have. What the crew adds
  is marked in the text: an appended block is a quote headed `> Yeoman
  added, <time>:`, a created entry begins `> Yeoman created this, …`.
  Every change, proposal and refusal is a line in
  `STATE/notes-writes.jsonl` (a title's with `old` and `new`). The
  steward's server gate and the routes are the walls that do not rely on
  the model: every change to an existing row is guarded by the stamp as
  read (412), none touches another login's or an import's kind or moves
  a row into one, a delete is soft, and a PATCH or DELETE without
  `if_modified` is a 403.
- **A scheduled run's one write (0.211.0): append only, declared.** The
  crew runner (`crew.py run`) takes a `CHANGES` block off a scheduled
  role's answer too, but a run is nobody's order, so the rule is
  narrower: the role's front matter names what it may write (`writes:
  append #<id>`; `writer:` the name its block is headed with), and
  `scheduled_apply` makes only an append, only to those ids, at most one
  a run. It reuses the notes' `parse_change`, `apply_change` and
  `quote_block` (the steward login, the 20s quiet rule, `if_modified`
  from the runner's own fresh read, the block quoted under `> Science
  officer added, <time>:`); a create, a title, another entry or a second
  append is refused, and a role with no `writes:` writes nothing. Every
  line, made or refused, is in `notes-writes.jsonl` (with `run`, the day)
  and in the report, which carries the `crew-changes` fence; the page
  (`repChangesHtml`, `repUndo`) gives it a Changes box with Undo under
  the report, in the reader and its bubble in the role's chat, cutting
  the block out only if it is still there exactly, as the captain on a
  fresh read, and marking it undone in the report. The science officer's
  Monday block on a child's page is the one use so far.
- **The page** (`lcars-ui/index.html`, "crew notes"): a chip beside each
  note, outside the text (`#rd_notes` under the reader's text, `#ed_notes`
  under the editor's content), its thread in a card under it with a reply
  box; `./notes` lists the threads. A reply is appended on a fresh read
  (`noteWrite`) and queues the thread. `mdRender` draws the crew's quoted
  blocks in the crew's blue (`CREW_MARK_RE`), the reader's meta row says
  *created by the Yeoman*, the editor's strip names each crew block.
  An `@` where a note can start (the head of a body line, after an indent
  and a bullet, outside a fence or a quote; never the title) opens the
  editor's completion popup on the roles (`noteTrigger`/`noteRank`,
  yeoman first, each with its `NOTE_HINTS` line), and accepting one
  writes `@role ` so the order follows: the watcher takes only an exact
  name.
- **Notes to people (0.256.0): `@no1`, `@torres`.** Besides the crew
  roles, a note may go to Number One (`@no1`) or to one of the ten
  engineers most recently active (not Number One, not dismissed), by
  their slug, its stem (`obrien` for `obrien-c33`) or their title's
  surname with punctuation dropped (`obrien` for O'Brien, `laforge` for La
  Forge); two sharing a name, the more recently active has it, and a
  crew role keeps its own. `engineer.py note-names` is that list, from
  the state files (no herdr); the watcher reads it every minute and
  publishes it in one `crew_note_names` row (a ```json block, `{alias:
  {to, title, off?}}`), which is how the page's chips, card, `@` popup and
  voice know the same names (`noteDirect`, `noteRoles`). The role is
  matched without case from 0.256.0, for every note. Same rule, quiet
  period, hash and thread per (entry, alias), but no crew turn: the
  thread's header adds `to:` (the engineer) and `sent:` (how many of the
  captain's turns were typed to them), its title is `<Their title>
  (@alias) · #<id> …`, and the watcher's worker (`send_direct`) types the
  unsent turns as the captain's - `[captain] A note to you, written in
  the captain's journal entry #E "…" (crew note #T): …` - through `engineer.py
  no1-send` (Number One's inbox; the flusher wakes it unless dismissed)
  or `engineer.py say <name>` (the seat: their inbox and first in line if
  not seated; never `--fresh`). `sent` moves before the send, back on a
  failure (`failed: not delivered…`; a question on screen is a skip, tried
  again in a minute), so a restart never types one twice. Status `queued`
  while in an inbox; `working` once typed into the session (`note_typed`,
  wherever engineer.py types: `say`, `tell`, `no1_deliver`, which records
  it in their state with the transcript's size then); `answered` when the
  turn that took it ends: their Stop hook spawns `engineer.py note-answer`
  with `last_assistant_message`, which appends it (`note_answer`) as their
  turn after the last captain turn sent - only for notes whose mark is in
  a user line of the transcript past that size, so a turn that ended
  before reading the order is not its answer. Nothing holds the crew lock
  or a runner for the turn. A dismissed engineer's name is answered in
  place (off duty, who is on), nothing started; any other `@word` is not
  a note.

### Two checkouts, one repo

An example deployment, the author's: one way to run LCARS where the box
that serves it is also where it is developed.

The VPS's `~/lcars` **is a checkout of this repository**, on the same branch as
the laptop. Both machines are full working copies: the C server and the web UI
can be edited on either, and git is what carries the change across.

That directory was a working directory long before it was a repo, and it could
not move to become one. Two things pin it:

- the systemd unit's `WorkingDirectory=~/lcars` and
  `ExecStart=~/lcars/lcars` (absolute paths in the unit), and
- `tailscale serve`, which maps `/` to the API on `:8080` — and the server
  reads the web UI from `./lcars-ui` (`$LCARS_UI_DIR`, relative to that
  working directory) and serves it at `/ui/`, and `/media/` from the NAS (see "Media").

So the repo was adopted *in place* — `git init` in `~/lcars`, then a checkout
over the existing files — rather than cloned beside it and symlinked. Three
paths line up for free as a result, which is the whole reason this works:
`./lcars` is the binary the unit executes (since 0.276.2 the one binary,
`vps-rebuild.sh`'s `lcars-one` swapped in, whose `bin/lcars-cli` link beside
it is the CLI everything on the box runs), `./lcars.db` is the
live database, and `./lcars-ui` is the directory `/ui/` is read from. A file saved
under `lcars-ui/` on the VPS is live on the next page load, with no build and
no deploy step.

- **The ignore rules are split by audience.** `.gitignore` carries what is true
  of the project everywhere (`lcars`, `*.db`, `resources/`, `lcars-ui/test/shots/`
  …). The VPS's own clutter — `llama.cpp`, a 1.1GB gguf, `lcars.prev`,
  `lcars_backups/`, the linker's logs — is listed in `.git/info/exclude` on that
  machine instead, because it is a fact about one box and not about the
  codebase. `git status` there is clean.
- **`resources/` is ignored, and nothing in it is tracked**: it is where a
  box keeps its own large files, the embedder's gguf on the VPS
  (`lcars-embed.service`). Its `model/` and `libvosk.so` were Vosk's, for
  `POST /transcribe` before 0.176.0, and nothing reads them now.
- **`origin` fetches over HTTPS and pushes over SSH.** Pushing uses a write-enabled *deploy
  key* generated on that box (`~/.ssh/id_ed25519`), which is scoped to this one
  repository rather than to the GitHub account.

**Building on the VPS.** `scripts/vps-rebuild.sh` builds on the box
itself: no container and no glibc check, since it compiles against the
glibc it runs on. It builds the one binary, `make lcars-one` (its own
output name, so the unit's `ExecStart`, `./lcars`, is never written in
place), copies it to `lcars.new`, refuses one that does not answer
`version` and `cli --help`, keeps `lcars.prev`, swaps by rename, restarts,
polls `/health`, and rolls back if
the new binary does not come up - or comes up on another journal: it reads
the live entry count off `/metrics` (loopback, no password;
`lcars_entries_total` summed over the kinds, the start log's count) before
the restart and after, and rolls back if it fell from more than one to one
or none (a journal it did not mean to open: a new one is empty), or the
new server will not say. Healthy is not enough: a
binary that resolved the path otherwise would answer `/health` on an empty
journal. Putting back a binary without the CLI in it (a rollback to one from
before 0.276.2) also removes `bin/lcars-cli`, rather than leave a link that
answers "no CLI in this build"; the scripts' fallback to the copied build
went with the copy in 0.279.2, so they then find no CLI and say so.
`scripts/test_vps_rebuild.py` covers it, with stand-ins for make, systemctl
and curl.

## The public release (`scripts/export-public.py`)

The public repo is never edited by hand: each release is a **snapshot** of
this tree at a commit, made by `scripts/export-public.py DEST`
(docs/design/open-source.md, section 5), where DEST is a clone of the
public repo. The code is made public here (owner, hosts, paths from the
environment), so the export's own job is small, which is what keeps the
two trees from drifting:

- **It refuses a dirty tree** (untracked files included): a release is a
  commit's, and the files are read from the worktree.
- **Exclusion:** `git ls-files` minus `EXCLUDE` in the script, the one
  list (the box's deploy and journal swaps, the Grafana stack, the signed
  shortcuts, the reports and QA runs on real data, CHANGELOG.md and
  TODO.md), and every file whose name holds `.local.`: `CLAUDE.local.md`,
  `crew/context.local.md`, the pattern file. A box's own file is kept out
  by its name, needing no line in the list.
- **Substitution:** `SUBST`, generic regexes only (today the README's CI
  badge to `--repo OWNER/NAME`, by default the public repo,
  `saftacatalinmihai/lcars`),
  since the script ships and must not spell what it replaces. A rule that
  matches nothing stops the export: its file changed under it.
- **The public CHANGELOG and TODO:** DEST's own CHANGELOG.md with one
  entry on top for this release (`APP_VERSION`, so run.sh's version check
  holds there; `--notes` for its line, else the first release's
  (`FIRST_NOTES`) or a snapshot's; a version released once is refused),
  and DEST's TODO.md, or a fresh one with the release's open items
  (`FRESH_TODO`). DEST is otherwise cleared
  to the snapshot (`.git` kept), so a file only the public repo has must
  come from here.
- **The audit**, over every file as it would be written (text by line,
  binaries read as latin-1): the rules in `scripts/export-audit.local.txt`,
  `name :: regex [:: globs]` a line, outside the public tree because they
  *are* the private names (hosts, the VPS, the family, the NAS, home
  paths, key shapes; the globs narrow a rule, as the owner-as-"he" one is
  to the prompts). Any hit stops the export before a byte is written and
  names `file:line` and the rule. Without the file the export refuses: an
  audit of nothing passes anything. demo/static.py's audit takes its
  private rules (hosts, the VPS, the name) from the same file.
- **Then in DEST:** `make check`, `lcars-ui/test/run.sh` (no `lcars.db`
  there, so a synthetic journal; `PERF=0`, since perf compares with main),
  every `scripts/test_*.py`; a failure commits nothing (`--no-tests` skips
  them). The suite's `test/esbuild` and `test/qjs` are ignored binaries no
  clone has, so the run borrows this checkout's by symlink and removes
  them after. On 0.264.0 the whole public tree passed this way in a
  scratch repo (~2.5 minutes). Then one commit, "Release X.Y.Z". **Pushing is not the script's**:
  a separate `git -C DEST push`, after reading the result.
- **`--audit-only`** (`--dry-run`) writes nothing: the hits over the files
  that would ship, grouped by rule with their files and lines, on the tree
  as it is, dirty or not. It is how the remaining sweep is measured
  (exit 1 while anything hits). `scripts/test_export.py` tests it all on a
  fixture repo with made-up patterns.

## History

The codebase went through a full 46-task refactoring audit in July–August 2026 —
`REFACTORING.md` records every task (A dead code → B header architecture → C
god-function splits → D data model → E database → F text/render → G hypermedia →
H app shell → I conventions), all completed, with commit-per-task history on the
`refactor` branch. Read it for the *why* behind the current shape before undoing
any of its decisions.

Most of what it shaped — the desktop app, its documents, its editor and its
renderer — was removed in 0.175.0 (see "Builds"); the server and the CLI are
what remain of it.
