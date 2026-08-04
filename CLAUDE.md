# CLAUDE.md — agent quickstart for lcars

LCARS is a Star Trek-style personal journal/notes app written in C11: raylib UI,
SQLite persistence, Vosk offline voice input, and a custom HTML-like "hypermedia"
format that describes the UI. Single user (Mihai), deployed to a personal VPS.
See @AGENTS.md for code style rules and @ARCHITECTURE.md for the full system map.

## Build & verify

```sh
make lcars            # static debug build + ASan (the default dev build)
make SANITIZE=0 lcars # same without AddressSanitizer
make lcars-lib.so     # hot-reload library only — fastest compile check of app code
make lcars-release    # -O3 static build
make lcars-web        # Emscripten build (needs `source emsdk/emsdk_env.sh` first)
./lcars               # run the UI (starts HTTP API on :8080 too)
./lcars --http-only   # headless API server only
```

- **After every edit, compile.** Warning flags are `-Wall -Wextra -pedantic -Wshadow`
  and the code currently builds clean — keep it that way. `make lcars-lib.so` is the
  quickest full-warning check for anything except `lcars.c` itself.
- First `make lcars` runs `ensure-resources`, which **downloads ~70MB**
  (libvosk.so + speech model) into `resources/`. Don't delete `resources/`.
- **There are no unit tests.** CI (`.github/workflows/c-cpp.yml`) builds and does an
  xvfb smoke-run with simulated clicks. Verification = clean build + run it.
- Run `clang-format` (config in `.clang-format`, LLVM-based, 2-space) on files you edit.
- `compile_commands.json` is generated via `bear` (`make compile_commands.json`);
  `.clangd` adds the `LCARS_IMPLEMENTATION` etc. defines so clangd sees function bodies.

## Danger zones — do not touch without being asked

- `lcars.db` is **live personal data** (journal entries). Never delete, overwrite, or
  experiment on it. Use a copy in scratch space if you need a DB to test against.
  `lcars_bkp.db` is a backup snapshot. Both are gitignored.
- `scripts/db-push.sh` / `db-pull.sh` sync the DB with the **production VPS**
  (185.244.129.231) over ssh. `test.sh` POSTs to production; `perf.sh` load-tests it
  with `wrk`. Never run any of these unprompted.
- `emsdk/` and `vendor/` are vendored toolchain/deps — don't reformat or "clean up".

## Architecture in one paragraph

Unity build: `lcars.c` is the only real TU for the app (`liblcars.c` wraps the same
headers for the hot-reload `.so`). All app code lives in single-header libraries
(`lcars_*.h`): declarations always visible, function bodies inside
`#ifdef LCARS_IMPLEMENTATION`. `liblcars.h` is the app core (frame loop, input,
drawing) and includes all the modules; `lcars_types.h` holds the shared structs
(`State`, `Element`, …) and tuning constants. Memory is arena-only — no malloc/free
in app code; `State` owns `doc_arena` (32MB, document lifetime) and `scratch_arena`
(16MB, reset every frame at the end of `UpdateDrawFrame`). Arena OOM aborts by
design. Strings are the arena-backed `String` type (`lcars_string.h`);
`StringStatic()` wraps literals without allocating.

## Conventions & gotchas

- **Dev workflow is hot reload**: `make run-dynamic`, then Ctrl+Shift+R inside the app
  rebuilds and reloads `lcars-lib.so` while running. Consequence: **changing the
  layout of `State`/`Element` (or anything they embed) breaks live reload sessions** —
  the host `lcars` binary allocated the old layout. That's fine, but mention it:
  the user must restart, not reload. (See the 10x over-allocation note in `lcars.c`.)
- New module = new `lcars_foo.h` following the same shape (declarations on top,
  `#ifdef LCARS_IMPLEMENTATION` bodies), included from `liblcars.h`. Don't create
  new `.c` files; don't add includes to `lcars.c` unless it's host-process-only
  (like voice or resource download).
- Functions are PascalCase (`UpdateNotification`), element constructors are
  `make_*` (`make_text_editor`), arena API is snake_case (`arena_alloc`). Any
  function that allocates takes `Arena *` as its first parameter.
- Element "kinds" that need heavy state get an on-demand-allocated side struct
  (`EntryListState`, `SphereState`) referenced by pointer from `Element` — don't
  fatten `Element` itself (there are `MAX_ELEMENTS` = 10000 of them).
- DB reads are cached (`EnsureEntryListCache`/`EnsureKindListCache`); if you write to
  the DB, call the matching `Invalidate*Cache`. Content saves are debounced
  (`CONTENT_SAVE_DEBOUNCE_SECONDS`) — `FlushPendingSaves` must run before exit.
- **Assert aggressively** (full rules in AGENTS.md): preconditions on entry (non-NULL
  args, index/capacity bounds), postconditions on computed results, and invariant
  checks after mutating a struct (gap buffer, arena offset, element count) — plain
  `assert()` from `<assert.h>`. Nothing defines `NDEBUG`, not even `lcars-release`,
  so asserts are live in every build by design; keep assert expressions side-effect
  free. Assert **programmer errors only** — SQLite failures, HTTP input, missing
  files and malformed hypermedia are runtime conditions and must be handled, not
  asserted.
- The `TODO` macro (lcars_types.h) prints to stderr and **aborts** — it marks
  unimplemented paths, not future work. Prose TODOs go in TODO.md.
- Comments in this codebase explain *constraints and why*, and are unusually
  thorough. Match that: when you write non-obvious code, say why it must be so.
- Commit style: short imperative summary, optionally referencing a REFACTORING.md
  task ID, e.g. `Harden the TODO macro: fprintf+newline to stderr, abort() (I2)`.
- `REFACTORING.md` is a **completed** 46-task audit (all checked) — it's history and
  rationale, not a to-do list. Open ideas live in `TODO.md`.
- **`TODO.md` is the living backlog** (features, bugs, refactoring ideas) — check it
  when picking a task or looking for context on known gaps. Keep it current: check
  off/remove items you finish, and add anything new you notice worth tracking
  (don't let it silently drift out of sync with the code).
- AGENTS.md mentions `fff` MCP tools for search — use them if available in the
  session, otherwise the normal Grep/Glob tools are fine.
