# LCARS Architecture

A single-user Star Trek LCARS-style journal/notes app in C11. One desktop window
(raylib), one SQLite file, an embedded HTTP API, offline voice-to-text (Vosk), and a
custom HTML-like document format that declares the UI. This file is the map; style
rules are in AGENTS.md, agent workflow in CLAUDE.md.

## Build variants (one codebase, four shapes)

| Variant | Make target | Defines | What runs |
|---|---|---|---|
| Static desktop (default dev) | `lcars` / `lcars-release` | `STATIC_BUILD`, `HYPERMEDIA` | Everything in one binary |
| Hot-reload dev | `lcars-dynamic` + `lcars-lib.so` | `HYPERMEDIA` (host TU compiles *without* `LCARS_IMPLEMENTATION`; the .so *with* it) | Host binary owns window/State/voice; app logic dlopen'd from `lcars-lib.so` |
| Web | `lcars-web` | `PLATFORM_WEB`, `HYPERMEDIA` | Emscripten/WASM, browser drives the main loop, sqlite compiled in |
| Headless API | any binary with `--http-only` | — | `InitDBMinimal()` + `RunHTTPServer()` only; no window, no voice |

`lcars-portable` builds the release binary inside a Debian 11 container for old-glibc
compatibility (this is what the VPS runs).

### Hot reload mechanics

`lcars.c` (host) loads `lcars-lib.so` via `LoadAppLibrary()`: copies the .so to a
uniquely-numbered temp path (defeats dlopen caching), dlopens it, resolves
`UpdateDrawFrame`, `Init`, `Reload` (required) and `FlushPendingSaves` (optional),
all-or-nothing. Ctrl+Shift+R in-app runs `make lcars-lib.so` and reloads on success.

The contract: **the host allocates `State` once at startup and the .so must keep
working against that memory**. So a reload may change *behavior* but not the *layout*
of `State`/`Element`/anything reachable from them. `CreateAppState()` over-allocates
10x as a crash cushion, but a layout change still requires restarting the app.
This is also why voice recognition is passed in as a struct of function pointers
(`VoiceRecApi`) — vosk stays linked into the host, the .so never links it.

## Module map (include order ≈ dependency order)

Everything is a single-header library: declarations always visible, bodies under
`#ifdef LCARS_IMPLEMENTATION`. `liblcars.h` includes all of them; `lcars.c`
(static build) or `liblcars.c` (the .so) defines the implementation macro.

| File | Role |
|---|---|
| `lcars_base.h` | Tiny base utils (`GetTimeSeconds`) |
| `lcars_arena.h` | Fixed-size bump arenas. `arena_alloc`/`arena_realloc`/`arena_reset`. OOM = log + `abort()`, deliberately — every arena is a pre-sized budget |
| `lcars_string.h` | Arena-backed `String {data, len, is_static}`. `StringInit` (copies into arena), `StringStatic` (wraps a literal, no alloc), `StringEqC`, `StringAssign`, … |
| `lcars_types.h` | All shared types (`State`, `Element`, `ElemKind`, `ButtonAction`, layout structs) + tuning constants + LCARS color palette + the aborting `TODO` macro |
| `lcars_gap_buffer.h` | Text-editing core: `GapBuffer` ops, selection, word boundaries. Deliberately raylib-free |
| `lcars_text.h` | Glyph decoding, line wrapping, mouse→char hit-testing. Shared by input and render so they can't diverge |
| `lcars_ui.h` | Geometry + layout helpers (`ComputeScrollbarLayout`, `ComputeEntryListLayout`, `DrawElbow`, bounding boxes) |
| `lcars_db.h` | SQLite layer: schema init, entry CRUD (prepared statements), kind/entry-list caches, debounced content saves |
| `lcars_net.h` | Blocking libcurl HTTP client (`NetHttpRequest`), shared by document loading and hypermedia controls |
| `lcars_hypermedia.h` | Parses `<lcars>` documents (table-driven tag/color/action/control mapping), loads them from file/HTTP or straight from a response body |
| `lcars_hypermedia_controls.h` | The `lc-*` controls: collects request fields, serves local `/entries` routes in-process, issues remote requests, applies the response swap |
| `lcars_doc_writer.h` | The other direction: patches the `x`/`y`/`w`/`h` an edit-mode drag produced back into the document's own bytes and rewrites the file |
| `lcars_http.h` | Threaded HTTP API server (raw sockets, Basic auth, tiny JSON helpers). Per-connection on-stack arena |
| `liblcars.h` | The app core: `Init`/`Reload`/`Update`/`UpdateDrawFrame`, input handling, element constructors (`make_*`), drawing, voice input plumbing |
| `lcars.c` | Host process: CLI args, window creation, hot-reload loop, voice init, `--http-only` mode. `#include`s the two host-only `.c` files at the bottom |
| `lcars_voice_rec.c/.h` | Vosk + miniaudio recording thread behind the `VoiceRecApi` fn-pointer struct (host-only) |
| `lcars_resources_download.c/.h` | First-run downloader for `resources/` (libvosk.so, speech model, textures) (host-only) |
| `vendor/` | raylib (static lib + web build), raygui, sqlite3 amalgamation, miniaudio, vosk API header, crsqlite |

## Runtime model

- **Frame loop**: `UpdateDrawFrame(s)` = `Update(s)` (input/logic) →
  `PreRenderElements` (sphere render-textures) → draw pass over `s->elements` →
  notification/debug overlays → `arena_reset(&s->scratch_arena)` at the very end.
  Target 240 FPS desktop, browser-paced on web.
- **Memory**: `State` owns `doc_arena` (32MB — element text, strings, per-kind state;
  lifetime = loaded document) and `scratch_arena` (16MB — per-frame temporaries,
  reset each frame). No malloc/free in app code; allocating functions take
  `Arena *` first.
- **Elements**: flat array `State.elements[10000]`, each an `Element` tagged by
  `ElemKind` (rectangle, elbow, button, text, text_editor, entry_list, sphere).
  Kind-specific heavy state hangs off pointers (`EntryListState`, `SphereState`)
  allocated on demand into `doc_arena`. Elements are found by hypermedia
  `id="..."` via `FindElementById`.
- **Editor**: gap buffer per text-editor element; `ReconstructText` materializes
  `Element.text` for rendering. Edits mark `contentDirty` and save to the DB after
  1s idle (`CONTENT_SAVE_DEBOUNCE_SECONDS`); switching entries or exiting flushes
  immediately (`FlushPendingSaves`). A plain `<lcars-text-editor>` only persists
  if the document said `bind="log"` — otherwise it is typed input owned by the
  document (a URL bar, a form field), and a control has to store it explicitly.
- **Document generation**: `State.documentGeneration` is bumped by every document
  load, and `State.currentDocument` remembers the source so a control can ask for
  a reload. Loading throws away `doc_arena`, so anything holding an `Element *`
  across a call that might load (`UpdateElement`, `Update`, `FireHyperControl`)
  compares the generation before and after and bails out if it changed.

## Persistence

Single SQLite file `lcars.db` (path in `LCARS_DB_PATH`), one table:

```sql
entries(id INTEGER PK AUTOINCREMENT, kind TEXT, title TEXT, content TEXT,
        value_int INTEGER, value_float REAL, value_blob BLOB,
        done_bool INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
        created_at_utc TEXT, last_modified_at_utc TEXT)
```

Deletes are soft (`deleted=1`). `kind` partitions entries into lists (default kind:
`architect_log`). The UI never queries per frame: entry list and kind list are cached
in `EntryListState` and refreshed only after `Invalidate*Cache()` — any new DB write
path must invalidate the matching cache. Writes go through prepared statements
(`StepAndFinalize` helper).

## HTTP API

Runs in a background thread next to the UI (or foreground with `--http-only`).
Port 8080 by default. Basic auth: `--user`/`--password` flags or
`LCARS_AUTH_USER`/`LCARS_AUTH_PASS` env, falling back to `admin`/`admin`.

| Route | What it does |
|---|---|
| `GET /` | Route index (self-documenting JSON: every route and every filter name) |
| `GET /health` | `{"status":"ok"}` — **the one unauthenticated route**, so monitoring needs no credentials. It touches nothing but the socket |
| `GET /entries` | Filtered list (below) as a JSON array |
| `POST /entries` | Create. JSON body (`kind`, `title`, `content`, `value_int`, `value_float`, `done_bool`) or a plain-text body, which becomes the content |
| `GET /entries/<id>` | One entry, soft-deleted ones included (a client that named an id wants "deleted", not 404) |
| `PUT`/`PATCH` `/entries/<id>` | Partial update — only the fields the body mentions. Both verbs behave identically: a `PUT` carrying just `content` must not blank the title. `{"deleted": 0}` restores a soft-deleted entry |
| `DELETE /entries/<id>` | Soft delete (`deleted = 1`), same as the UI. There is deliberately **no hard-delete route** — this DB is a personal journal, and the PUT above is the undo |
| `GET /kinds` | Distinct kinds with `count` and newest `last_modified_at_utc` (`?deleted=1` to count deleted rows too) |
| `GET /stats` | Totals — count, distinct kinds, done, content bytes, oldest/newest. Accepts the same filters as `/entries`, so it is also "how many rows does this query have" |
| `OPTIONS *` | CORS preflight (allows `*`) |
| anything else | 404 / 405, as JSON |

`GET /entries` (and `/stats`) filters, all optional and combinable:

`kind=<exact>`, `q=<substring of title or content>` (LIKE wildcards in the term
are escaped, so `%` means a percent sign), `date=YYYY-MM-DD`,
`since=`/`until=` on `created_at_utc`, `modified_since=`/`modified_until=` on
`last_modified_at_utc` (each takes `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`; a bare
date used as an upper bound widens to the end of that day), `done=0|1`,
`deleted=0|1|all` (**default `0`** — the list excludes soft-deleted entries,
matching the UI; the old behaviour is `deleted=all`), `min_id=`/`max_id=`,
`order=id|created|modified|title|kind` + `dir=asc|desc` (default `id desc`),
`limit=` (default 200, max 1000) + `offset=`, and `content=0` to omit entry
bodies from the rows (`content_length` is always there).

Every value the client sends is a **bound parameter**; the only pieces of SQL
built from a request are the fixed clause literals and an `ORDER BY` matched
against a table of allowed column names.

Errors are JSON (`{"error":…,"status":…}`). A filter the server can't honour is
a 400 rather than being ignored — silently dropping `?kind=…` would answer with
rows the client explicitly excluded.

Each connection is handled with an on-stack 1MB arena, and the server opens its
own SQLite connection (2s busy timeout, so an API write racing the UI's
debounced save waits its turn instead of failing). Consequences of that arena
worth knowing, both handled rather than left to abort: a `Content-Length` over
512KB is refused with 413 before it ever reaches `arena_alloc`, and a response
that would outgrow the arena mid-build comes back as a 500 telling the client to
narrow the query (`limit`/`offset`/`content=0`) instead of as truncated JSON.

## Hypermedia documents

The UI itself is declared in an HTML-like document (`main.html` is the app shell,
`document.html` a demo page). `LoadHypermediaDocument` clears the element array and
rebuilds it from the document; sources can be `file://...`, `http(s)://...` (fetched
via libcurl), or anything containing `.html`.

Tags (see the table-driven mapping in `lcars_hypermedia.h`):
`<lcars-rectangle>`/`<lcars-rect>`, `<lcars-elbow>`, `<lcars-button>`,
`<lcars-text>`, `<lcars-text-editor>`, `<lcars-entry-list>`, `<lcars-sphere>`.

Attributes: `x y w h` (px), `color` (purple/red/orange/yellow/blue/green/white →
LCARS palette), `size` (text), `orientation` (elbow 0-3; only 0 and 3 are
implemented), `src` (sphere texture), `id` (lookup key), `href` (navigation target),
`action` (none/debug/edit/reset/voice_input/print_db/load_hypermedia). Inner text
becomes the element label/content. `action="load_hypermedia"` follows `href`, or
falls back to the text typed in the element with `id="url_input"`. The shipped
documents no longer use it for the URL bar — that is now expressed with controls
(`lc-get="#url_input"` + `lc-trigger="enter"` + `lc-from`, below) — but `href`
links still do.

### Hypermedia controls (`lc-*`)

Navigation = "the browser": GO button / href buttons load a new document over the
running State. **Controls** are the other verbs — the HTMX/DataStar idea without a
scripting language. Any element can declare a request, where the reply goes and
what makes it fire:

| Attribute | Meaning |
|---|---|
| `lc-get` / `lc-post` / `lc-put` / `lc-delete` | The request; the attribute picks the method. A `#id` URL is an indirection: the named element's text *is* the URL, read at fire time |
| `lc-target` | Element id a text/append swap writes into (a leading `#` is tolerated) |
| `lc-swap` | `none` / `text` / `append` / `document` / `reload`. Default: `text` with a target, else `document` for GET, else `none` |
| `lc-trigger` | `click` (default), `load` (fires once when the document finishes parsing), or `enter` (the focused text editor sees Enter — which then submits instead of inserting a newline) |
| `lc-vals` | Literal fields, `name=value,name=value` (flat, not JSON — so no commas or `=` inside a value) |
| `lc-include` | Ids of elements whose text becomes a field; **the id is the field name** |
| `lc-from` | Not a request: "fire the control declared by *that* element when I'm clicked". Only applies to elements with no `lc-*` method of their own |

Those three — the `#id` URL, `lc-trigger="enter"` and `lc-from` — are what make the
URL bar a document rather than C code. The field says
`lc-get="#url_input" lc-trigger="enter"` (the URL is my own text, Enter submits it)
and the GO button beside it says `lc-from="url_input"`, so one request is declared
once and has two ways to be pressed.

The URL decides the transport:

- `/...` — served in-process against `lcars.db`, no socket involved. Routes:
  `POST /entries` (fields `kind`, `title`, `content`), `GET /entries/<id>` (answers
  with the content as plain text), `PUT /entries/<id>` (fields `content` and/or
  `title`), `DELETE /entries/<id>` (soft delete). `<id>` may be the literal
  `selected`, meaning whatever entry the `<lcars-entry-list>` is showing. Writes
  invalidate the entry-list caches and resync any list displaying that entry.
- `http(s)://...` — a real request through `lcars_net.h`, fields sent as a flat
  JSON object. That is the same shape `lcars_http.h`'s `POST /entries` parses, so
  a document works against this app or against a remote LCARS server unchanged.
  (No auth support yet — see TODO.md.)
- `file://...` / anything with `.html` — GET only; the local-document case
  `action="load_hypermedia"` + `href` has always covered, which makes `lc-get` a
  superset of the old GET-style link.

Requests are blocking and run on the UI thread, exactly as document loading always
has. `controls.html` is the worked example (form-style create, load/save/delete of
the selected entry, a load-triggered fetch); `controls_test.html` is a test bench
with one numbered button per control variant — including the failure cases —
writing into kind `hyper_test` so exercising it leaves the journal alone. This is the long-term direction (see
TODO.md): LCARS as a hypermedia client, entries editable as documents.

### Editing the document back (`lcars_doc_writer.h`)

Edit mode moves and resizes elements; the writer is what makes those edits
outlive the process. It **patches** rather than serializes: `documentSource`
(the document's exact bytes, copied into `doc_arena` at load) plus every
element's `srcTagStart`/`srcTagEnd` (the byte range of its own opening tag) are
enough to replace nothing but the four geometry attribute *values* in place.
Comments, indentation, attribute order and quoting style, tags the parser
doesn't even recognize — all of it survives byte for byte, which a
regenerate-from-`Element[]` serializer could not manage against these
hand-written, heavily commented documents.

- An attribute is only touched when its text would actually change, so saving
  a document nobody dragged rewrites the file to exactly itself. One the
  document omitted is inserted after the tag name, and only if the element has
  moved off the default its absence implies (`ELEM_DEFAULT_*` in
  `lcars_types.h`, shared with the parser for that reason).
- `x`/`y` are written rounded because `ParseElementTag` reads them with
  `atoi`; `w`/`h` go through `atof` and may be fractional. `<lcars-text>` sizes
  itself from its text (`autoSize`), so its `w`/`h` are never written out.
- Saves are debounced (`LAYOUT_SAVE_DEBOUNCE_SECONDS`, the same shape as
  content saves) and flushed by `FlushPendingSaves` on exit and by both
  document loaders before they throw the current document away. The write goes
  to `<path>.tmp` and is `rename`d over the target — a truncated `main.html`
  is an app that comes back up blank.
- Only local-file documents are writable (`State.documentWritable`): an
  `http(s)` document isn't ours, and a control's response body
  (`HYPER_SWAP_DOCUMENT`) has no file behind it. Dragging in one of those still
  works on screen and says `LAYOUT NOT SAVED: READ-ONLY DOC`.

Consequence worth knowing: `Super+R` / `action="reset"` re-`Init`s, which reloads
`main.html` — so "reset layout" now means "reload the saved document", not "go
back to how it shipped".

## Keyboard & mouse

- `Super+D` debug overlay, `Super+E` edit mode (drag/resize elements, handles
  drawn per element), `Super+R` reset layout, `Ctrl+Shift+R` hot reload (dev build).
  Drag/resize — via the handles, `Super+click`, `Super+right-click`, or the
  `Super+drag` whole-document pan — is written back to the document file half a
  second after the mouse stops (see `lcars_doc_writer.h` above).
- Text editor: standard cursor movement with key-repeat, shift-selection,
  Ctrl/Super+arrow word jumps, Ctrl/Super+C/V clipboard, mouse drag selection,
  scrollbar drag. Enter inserts a newline unless the element declares
  `lc-trigger="enter"`, which turns it into a single-line submit field (the URL
  bar) — Enter then fires its control instead.
- Entry list panel: collapse/expand toggle, kind selector, `+ NEW ENTRY`,
  keyboard up/down navigation (`NavigateEntryList`).

## Deployment & ops

- VPS at `185.244.129.231` runs the portable build as an API server on :8080
  (Apple Shortcuts etc. POST entries to it).
- `scripts/db-pull.sh` / `db-push.sh` sync local ↔ remote DB using `sqlite3 .backup`
  + `sqldiff` (safe snapshot, diff-only transfer). `scripts/copy_remote_to_local.sh`
  grabs a full backup copy. **These touch production data.**
- CI: build on ubuntu (raylib via PPA) + xvfb smoke test that launches the app,
  clicks around with xdotool, and expects clean SIGTERM exit.

## History

The codebase went through a full 46-task refactoring audit in July–August 2026 —
`REFACTORING.md` records every task (A dead code → B header architecture → C
god-function splits → D data model → E database → F text/render → G hypermedia →
H app shell → I conventions), all completed, with commit-per-task history on the
`refactor` branch. Read it for the *why* behind the current shape before undoing
any of its decisions.
