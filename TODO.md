# TODO

Open backlog: new features, bugs, and refactoring ideas. Unlike `REFACTORING.md`
(a **completed**, closed audit — history and rationale, don't undo it), this file
is a living list — add to it, check items off, delete what's no longer relevant.
Prose TODOs belong here, not as inline code comments; the `TODO` macro in
`lcars_types.h` is a different thing entirely — a runtime abort for genuinely
unimplemented/unreachable paths, not a marker for future work.

## Features

- [ ] **Real-time hypermedia document editor — the rest of it.** Edit mode now
  persists *geometry* (see the Done entry below), which is the first slice of
  editing the underlying `.html` from inside the app. Still C-only or not
  possible at all: changing an element's `color`, `text`, `size` or any other
  attribute; adding a new element; deleting one; reordering them. The patching
  machinery in `lcars_doc_writer.h` generalizes to attributes (it already
  inserts an attribute a tag never had), but adding and removing *tags* needs
  more than a span rewrite — an element with `srcTagStart == -1` has no tag to
  patch, and a deleted one leaves a hole nothing tracks. The end state is still
  the "LCARS as a hypermedia client" direction in `ARCHITECTURE.md`: the
  document editable as a document.
- [ ] **No undo for layout edits.** A drag is written to the file half a second
  after the mouse stops, and the only way back is `git checkout` on the
  document. `Super+R` used to be that escape hatch — it now reloads the saved
  file, so it restores nothing. Implement a generalized Undo-Redo system that 
  will work on edits of the UI but also on the Text Editors.
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
- [ ] **An HTTP write doesn't reach the running UI.** The API server has its own
  SQLite connection and no access to `State`, so creating/editing/deleting an
  entry over HTTP leaves the UI showing its cached list until something else
  invalidates it (`EnsureEntryListCache` in `lcars_db.h`). The in-process
  hypermedia control routes call `Invalidate*Cache` for exactly this reason;
  the HTTP thread needs an equivalent — a thread-safe "DB changed" flag the
  frame loop polls.
- [ ] **The JSON body parser finds keys with `strstr`.** `json_get_string` /
  `json_get_int` / `json_get_string_arena` (`lcars_http.h`) search for
  `"key"` anywhere in the body, so an entry whose *content* contains
  `"title"` can be read as the title field. Fine for the clients this API has
  (Shortcuts, curl, the app itself); the fix is a real tokenizer, and it should
  come with the `\uXXXX` decoding those functions also skip.
- [ ] **No hard delete, on purpose — but nothing prunes either.** Soft-deleted
  rows accumulate in `lcars.db` forever and there is no route (or UI) to
  actually remove them. If that ever matters, it wants a deliberate,
  awkward-to-trigger purge, not a `DELETE ?hard=1`.
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

- [x] **State editor (Unity-style inspector) in edit mode.** In edit mode,
  clicking an element selects it (`State.selectedElementIdx`) and a right-hand
  panel (`lcars_inspector.h`, built on raygui) shows its authored properties and
  edits them live: `kind`, `id`, `x`/`y`/`w`/`h`, `color` (LCARS palette +
  swatch), `textSize`, elbow `orient`, `on_click` action, `href`, the `text`
  label, and the `autoSize`/`bindsToLog` toggles. The runtime-only Element
  fields (gap buffer, focus/selection, KeyRepeat timers, DB caches) are
  deliberately not shown — they aren't authored properties and hand-editing them
  only corrupts editor/list state. Two known limits, both already tracked as
  separate items above: (1) only `x`/`y`/`w`/`h` persist to the `.html` (via the
  existing `MarkLayoutDirty()` path) — every other edit is session-only until the
  document writer learns non-geometry attributes ("Real-time hypermedia document
  editor — the rest of it"); (2) switching to a kind that needs a side struct it
  doesn't already have (text_editor/entry_list/sphere) is refused rather than
  running a constructor mid-frame against an element missing its inputs.
- [x] **The HTTP API can query and edit, not just list and append.**
  `GET /entries` now filters (`kind`, `q`, `date`, `since`/`until`,
  `modified_since`/`modified_until`, `done`, `deleted`, `min_id`/`max_id`),
  sorts (`order`/`dir`), pages (`limit`/`offset`) and can drop entry bodies
  (`content=0`); `GET /entries/<id>`, `PUT`/`PATCH /entries/<id>` (partial
  update, `deleted=0` restores) and `DELETE /entries/<id>` (soft) cover a
  single entry; `GET /kinds`, `GET /stats`, `GET /health` (unauthenticated)
  and a self-documenting `GET /` round it out. Values are always bound, never
  interpolated, and an unparseable filter is a 400 instead of being ignored.
  See the HTTP API section of `ARCHITECTURE.md`.
- [x] **`GET /entries` truncated any entry longer than ~4KB mid-JSON.** Rows
  are built straight into an arena-backed growable buffer (`JSONBuf` in
  `lcars_http.h`) instead of a 4096-byte stack `row_buf` that `snprintf`
  silently cut in the middle of a string literal.
- [x] **JSON string escaping missed `\b` and `\f`.** The old measuring/writing
  two-pass `json_escape` is gone; `jsonbuf_append_json_string` escapes every
  control byte (`\uXXXX` for the rest) as it streams, so no measuring pass can
  disagree with the writing pass again.
- [x] **A large `Content-Length` aborted the whole API server.** Bodies over
  512KB (`HTTP_MAX_BODY_BYTES`) are refused with 413 before the client-supplied
  length reaches `arena_alloc` on the connection's 1MB stack arena, where OOM
  is a deliberate `abort()`. The response side has the matching guard: a
  response that would outgrow the arena answers 500 "narrow the query" rather
  than aborting or sending half a document. `send` also passes `MSG_NOSIGNAL`
  now — a client hanging up mid-response used to be a SIGPIPE that killed the
  UI process with it.
- [x] **Edit-mode drag/resize survives a restart.** Moving or resizing an
  element now writes `x`/`y`/`w`/`h` back into the `.html` the document was
  loaded from, half a second after the layout stops changing (and immediately
  on exit or before another document loads). It patches the document's own
  bytes rather than regenerating it, so comments, formatting, quoting style and
  unknown attributes survive, and a save with nothing dragged reproduces the
  file exactly. Only local-file documents are writable — `http(s)` documents
  and control response bodies say `LAYOUT NOT SAVED: READ-ONLY DOC`. See
  `lcars_doc_writer.h` and the `Editing the document back` section of
  `ARCHITECTURE.md`.
- [x] **The URL bar is a document now, not a C special case.** Enter in a field
  with `lc-trigger="enter"` fires that element's control instead of inserting a
  newline; a `#id` URL means "the named element's text is the URL"; and
  `lc-from="<id>"` lets a button press another element's control. `main.html`,
  `controls.html` and `controls_test.html` express the URL bar + GO with those
  three instead of `action="load_hypermedia"`, which now only serves `href`
  links. See `ARCHITECTURE.md`'s Hypermedia controls section; tests 13-16 in
  `controls_test.html` are the failure cases.
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
