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
- [ ] **Local `GET /entries` list route.** The in-process control routes cover
  one entry at a time (`GET/PUT/DELETE /entries/<id>`, `POST /entries`) but
  there is no way to ask for the list. The interesting version isn't JSON: it
  is a route that *renders* an `<lcars>` document (a button per entry) so
  `lc-get="/entries" lc-swap="document"` builds a screen out of the DB —
  hypermedia all the way down, no C-side list widget required.
- [ ] **Query-string fields for GET controls.** `lc-vals`/`lc-include` are only
  sent on POST/PUT/DELETE; a GET carries no body and this format has no syntax
  for putting the fields in the URL, so a control can't parameterize a GET yet.
- [ ] **Auth for remote controls.** `lc-post="https://…"` against the deployed
  API gets a 401: the HTTP API wants Basic auth and a control has no way to
  supply credentials. Needs somewhere for them to live that isn't the document
  (an `LCARS_REMOTE_USER`/`PASS` env pair, say) before this is usable against
  the VPS.
- [ ] **More triggers than click/load/enter.** `lc-trigger` understands `click`,
  `load` and `enter`. `changed`/`keyup` (fire when an editor's text settles) and
  `every Ns` (polling) are the two that would earn their keep — a
  live-updating panel is impossible today.
- [ ] **`lc-from` fires exactly one control.** A button delegates to one element's
  request; there is no way to say "fire all of these" (a form with two fields that
  each own a request) and no way to chain, since an element carrying `lc-from`
  declares no control of its own. Fine for the URL bar, thin for anything bigger.
- [ ] **`lc-vals` can't express a value containing `,` or `=`.** It is a flat
  `name=value,name=value` list on purpose (a 20-line parser instead of a JSON
  one), but there is no escaping, so those two characters are unusable in a
  literal value. `lc-include` has no such limit.
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
- [ ] **`GET /entries` truncates any entry longer than ~4KB mid-JSON.**
  `HandleGetEntries` (`lcars_http.h`) formats each row into a 4096-byte stack
  `row_buf`; `snprintf` truncates, and the response ends up with a row cut off
  in the middle of a string literal, so the whole payload fails to parse. (The
  memory-safety half of this is fixed: `row_len` is now clamped to what was
  actually written, because `snprintf` returns the *would-be* length and the
  following `memcpy` was reading up to that far past the end of the stack
  array.) Real fix: build each row straight into the arena-backed response
  buffer instead of a fixed stack buffer.
- [ ] **`json_escape` doesn't escape `\b` and `\f`.** (`lcars_http.h`) The
  measuring pass counts them as two bytes but the writing pass emits the raw
  control byte, which is invalid inside a JSON string. Over-allocates, so it's
  memory-safe, but the response can be unparseable for content containing
  either character.
- [ ] **A large `Content-Length` aborts the whole API server.**
  `ReadHTTPRequestBody` (`lcars_http.h`) passes the client-supplied length
  straight to `arena_alloc` on the connection's 1MB stack arena, and arena OOM
  is a deliberate `abort()` — so one oversized (or malicious) request takes the
  process down, UI included. Needs an explicit size cap with a 413 response
  before it ever reaches the arena.
- [ ] **`UpdateNotification` can be handed a dangling stack buffer.**
  `StringDup` returns static Strings by alias rather than copying, so
  `UpdateNotification(s, StringStatic(localBuf))` leaves `s->notification`
  pointing at a dead stack frame. `UpdateVoiceInput` (`liblcars.h`) does exactly
  this with its `fullNotify[300]`; the banner is only rendered in debug mode,
  which is why it hasn't shown up. Either `StringFormat` into `scratch_arena`
  at that call site, or make `UpdateNotification` always copy.
- [ ] **Stale `Selection` outlives the text it indexes.** Nothing resets
  `Element.selection` when plain Backspace/Delete shortens the buffer, so the
  anchor can end up past the end and a later shift-extend produces a range
  outside the text. Both consumers now clamp (`DeleteSelection` in
  `lcars_gap_buffer.h`, the Ctrl+C copy in `liblcars.h`) — before that the
  former pushed `gapEnd` past `capacity` and handed `ReconstructText` a
  negative `memcpy` length. Clamping is a guard, not the fix: the selection
  should be invalidated (or clamped) at the point the text shrinks.
- [ ] **`Element.text` is only re-flattened once per frame.** A frame that both
  inserts and moves the cursor (Ctrl+V then Ctrl+Right, or Enter while
  Ctrl+Arrow auto-repeats) runs the cursor logic against a stale
  `Element.text`, so `gap.gapStart` can exceed `text.len`. `FindWordBoundary`
  now clamps for this (it previously walked off the end of the allocation
  without terminating in the forward direction), but the real fix is to
  reconstruct as soon as the gap changes, before any cursor handling reads it.
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

- [x] **Hypermedia controls beyond GET-style navigation.** The format now has
  the other verbs: `lc-get`/`lc-post`/`lc-put`/`lc-delete` with `lc-target`,
  `lc-swap`, `lc-trigger`, `lc-vals` and `lc-include` (HTMX/DataStar-inspired,
  no scripting language). A path URL is served in-process against `lcars.db`,
  an `http(s)://` URL goes out over the network as flat JSON matching this
  app's own HTTP API, and `file://…` documents keep working through `lc-get`.
  See `lcars_hypermedia_controls.h`, the `Hypermedia controls` section of
  `ARCHITECTURE.md`, and `controls.html` for a worked example.
- [x] A plain `<lcars-text-editor>` overwrote the newest default-kind entry
  with whatever was typed into it, because `FlushEntryContent` routed every
  non-entry-list editor to `UpdateLogInDB`. That made the URL bar in
  `main.html` a journal-corrupting input (type a URL, wait 1s, lose the
  content of the newest `architect_log` entry) and would have made every
  form field in a document do the same. Persisting is now opt-in per element
  via `bind="log"`.
- [x] A click that loaded a new document kept iterating the element array it
  had just replaced (`Update`/`UpdateElement`/`HandleElementClick`), so the
  same still-held mouse press could be delivered a second time to whatever
  the new document put under the cursor — and `UpdateElement`'s own
  `i < s->numElements` precondition could trip when the new document had
  fewer elements. All three now stop on a `State.documentGeneration` change.
- [x] `LoadHypermediaDocument` fetched through its `source` argument *after*
  resetting `doc_arena` — and `source` is normally an element's `href` or the
  URL bar's text, i.e. memory that reset just released. It survived only
  because nothing allocated from that arena in between. The source is copied
  to the stack before the reset now.
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
