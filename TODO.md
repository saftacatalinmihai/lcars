# TODO

Open backlog: new features, bugs, and refactoring ideas. Unlike `REFACTORING.md`
(a **completed**, closed audit — history and rationale, don't undo it), this file
is a living list — add to it, check items off, delete what's no longer relevant.
Prose TODOs belong here, not as inline code comments; the `TODO` macro in
`lcars_types.h` is a different thing entirely — a runtime abort for genuinely
unimplemented/unreachable paths, not a marker for future work.

## Features

- [ ] **Real-time hypermedia document editor.** An editor that edits the
  underlying `.html` hypermedia document itself (ideally live), not just entry
  content. This is the long-term "LCARS as a hypermedia client" direction
  described in `ARCHITECTURE.md`'s Hypermedia documents section.
- [ ] **Hypermedia controls beyond GET-style navigation.** Today the format only
  supports navigation (`action="load_hypermedia"` + `href`, or the URL-bar/GO
  button) — the hypermedia equivalent of a GET link. There's no declarative way
  for a document to POST/mutate entries (form-style controls), which is the
  natural next step toward the editor idea above. Inspiration from HTMX, DataStar etc...
- [ ] **Decide the fate of elbow orientations 1/2 (top-right/bottom-right
  corners).** `DrawElbow` (`lcars_ui.h`) only ever implemented 0/3;
  `lcars_hypermedia.h`'s orientation parsing rejects 1/2 at parse time and falls
  back to 0 (see `REFACTORING.md` F4). Either implement the corner geometry for
  real, or drop the unused orientation values from the enum/parser.

## Bugs & robustness

- [ ] **Line-start tracking caps out at 1024 lines.** `GetLines`
  (`lcars_text.h`) stops recording line starts past `LINE_STARTS_MAX`, so in an
  entry with more than 1024 lines the Up/Down/Home/End handling in `liblcars.h`
  treats everything after line 1024 as one long line. Bounds-safe (it just
  drops the extras), but wrong. Now reachable in practice since editor content
  is no longer capped — size the array from the actual line count
  (scratch_arena) instead of a fixed stack array.
- [ ] **Hot reload has no layout/size safety check.** `lcars-lib.so` reloads
  into the host's pre-allocated `State` with no verification that the host and
  the freshly-rebuilt `.so` agree on struct layout — `CreateAppState`'s 10x
  over-allocation (`lcars.c`) is a crash cushion, not a fix (see
  `REFACTORING.md` H1). A real fix needs an explicit layout version/size check
  on reload, with a clear "please restart" failure mode instead of relying on
  the cushion silently absorbing drift.

## Refactoring & cleanup

- [ ] **Vendor all libs; static-link the final binary.** Even the "static"
  desktop build (`lcars` / `lcars-release`) still dynamically links libcurl,
  sqlite3, X11/GL, etc. (`STATIC_LIBS_DESKTOP` in the Makefile) — only
  raylib and miniaudio are actually vendored as `.a` archives.
  `vendor/sqlite3.c` is already vendored as source and used by the web build,
  but not compiled into the desktop build.
- [ ] **Resolve the dead word-wrap path in `DrawTextBoxedSelectable`.**
  `DrawTextBoxed`, its only caller, always passes `wordWrap=false`, so the
  `MEASURE_STATE`/`DRAW_STATE` backtracking machinery (and the stale "multiple
  Unicode space types" comment at `lcars_text.h:243`) never actually runs
  (confirmed in `REFACTORING.md` F1). Either wire up real word-wrapping and
  make it earn its keep, or delete the dead path.
- [ ] **Add an `ArenaTemp` begin/end scope helper.** For temporary
  sub-allocations within `scratch_arena`/`doc_arena` that don't need to survive
  to the next full `arena_reset`. Raised but not implemented during the arena
  OOM-policy pass (`REFACTORING.md` I3) since it's new functionality, not a
  consistency fix.

## Done

- [x] Spaces at the start of a line in the text editor were invisible and the
  cursor didn't move (the bytes were really in the gap buffer — deleting them
  worked). `DrawTextBoxedSelectable` inherited raylib's "avoid leading spaces"
  rule, which suppresses the advance of a space sitting at `textOffsetX == 0`.
  That's a *word-wrap* rule (don't indent a line with the space that caused the
  automatic break) but it was applied unconditionally, so in the
  character-wrap mode the editor actually uses, every typed space at a line
  start advanced 0px — and since `textOffsetX` then stayed 0, so did each
  space after it. Now gated on `wordWrap`, with the same fix in
  `GetCharIndexAtMouse` so hit-testing keeps agreeing with the draw pass.
- [x] Text editor silently stopped accepting input past 1024 characters
  (`MAX_INPUT_CHARS`, which only ever gated typed keys — paste, Enter and voice
  input always bypassed it). Removing the cap also required fixing what it was
  masking: `ReconstructText` allocated a fresh doc_arena buffer on every
  keystroke (O(n²) over a session, an arena OOM abort at ~8k chars), and
  `LoadEntryIntoEditor` truncated DB content to the gap buffer's old capacity
  while memcpy'ing it into an `Element.text` buffer sized for the previous
  entry.
- [x] HTML-like hypermedia format for LCARS UI components.
- [x] Hypermedia navigation (GET-style `href` / `action="load_hypermedia"`,
  with URL-bar fallback).
- [x] HTTP API reachable over the internet — VPS deployment, Apple Shortcuts
  etc. POST entries to it (see `ARCHITECTURE.md` Deployment & ops).
