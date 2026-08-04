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
| `lcars_hypermedia.h` | Parses `<lcars>` documents (table-driven tag/color/action mapping), loads them from file/HTTP via libcurl |
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
  immediately (`FlushPendingSaves`).

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

- `GET /entries` → all entries as JSON array
- `POST /entries` → create entry (JSON body: `kind`, `content`, …)
- `OPTIONS *` → CORS preflight (allows `*`)
- everything else → 404

Each connection is handled with an on-stack arena; the server opens its own SQLite
connection (see `lcars_http.h`).

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
falls back to the text typed in the element with `id="url_input"` (the URL bar).

Navigation = "the browser": GO button / href buttons load a new document over the
running State. This is the long-term direction (see TODO.md): LCARS as a hypermedia
client, entries editable as documents.

## Keyboard & mouse

- `Super+D` debug overlay, `Super+E` edit mode (drag/resize elements, handles
  drawn per element), `Super+R` reset layout, `Ctrl+Shift+R` hot reload (dev build).
- Text editor: standard cursor movement with key-repeat, shift-selection,
  Ctrl/Super+arrow word jumps, Ctrl/Super+C/V clipboard, mouse drag selection,
  scrollbar drag.
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
