# LCARS Refactoring Task List

Independently executable tasks, grouped by theme. Within each group, tasks are roughly ordered so earlier ones unblock later ones. File references point at the current code.

## A. Dead code & build health (do these first — they shrink everything else)

- [x] **A1. Decide the fate of the non-HYPERMEDIA legacy path — it currently cannot compile.** The Makefile always defines `-DHYPERMEDIA`, and the `#ifndef HYPERMEDIA` code has bit-rotted: `Init()` references timing variables that are never declared (`t_editor_start`, `t_media_start`, `t_model_start`, `t_style_start`, `t_render_texture_start` — liblcars.h:564-573), and `ReLayout()` assigns `(iVec2){...}` to `Element.position` which is a `Vector2` (lcars_ui.h:23,54,64,...). Either delete `ReLayout`, `AddBarSegment`, the static layout variables and all `#ifndef HYPERMEDIA` blocks, or fix and CI-build both configurations. Deleting simplifies tasks A2, C4, D3 below.
- [x] **A2. Remove the duplicated static layout variables.** `w600/h400/w300/h300/w[4]/h100/h200_60_250/halfBarHeight/buttonHeight/w210` are defined both in liblcars.h:420-433 and lcars_ui.h:7-18. In a unity build these are duplicate file-scope statics with initializers — a redefinition error the moment HYPERMEDIA is undefined. (Subsumed by A1 if the legacy path is deleted.)
- [x] **A3. Remove verified-dead fields:** `Element.textLines` (never touched), `Element.textLineLen` (written twice, never read), `State.controllsX/controllsY` (written in Init, never read — also a typo), `State.ray`/`State.collision` (never used), `iVec2` typedef (only used by dead ReLayout). `Element.textLen` duplicates `e->text.len` — pick one and delete the other (it's assigned in every constructor and in `ReconstructText`).
- [x] **A4. Deduplicate `NOTIFICATION_MAX_LEN`** — defined in liblcars.h:167 and again in lcars_ui.h:220.
- [x] **A5. Consolidate feature-test macros.** `_POSIX_C_SOURCE` is defined in liblcars.h:3 *after* lcars.c has already included headers; `#define _ISOC99_SOURCE` sits mid-file at liblcars.h:29 after `<stdio.h>` etc. are already in. Move them to the build flags (Makefile `BASE_CFLAGS`) or the very top of the translation unit only.
- [x] **A6. Add a `.clang-format` and do a one-time reformat.** Indentation is mixed 2-space/4-space, sometimes within one function (liblcars.h:752-786, liblcars.h:163, lcars_ui.h switch bodies). One commit, no logic changes.
- [x] **A7. Enable `-Wshadow` and fix shadowing.** `mPos` is re-declared in nested scopes inside `Update()` (liblcars.h:876, 998, 1142), as is `vapi` (liblcars.h:847). Shadowing in a 900-line function is how bugs get in.
- [x] **A8. Delete stale debug noise:** commented-out code (liblcars.h:1594, 1627-1628), `printf`s of clipboard contents and "Make entry list element" (liblcars.h:1183, 1196, 1209, 1215; lcars_hypermedia.h:321). Route what's worth keeping through `TraceLog`/notification.

## B. Header architecture (unblocks working on modules in isolation)

- [x] **B1. Extract shared types into `lcars_types.h`.** `Element`, `State`, `ElemKind`, `ButtonAction`, `KindList`, `EntryListItem`, the color/limit macros. Today lcars_db.h/lcars_gap_buffer.h/lcars_text.h/lcars_ui.h/lcars_hypermedia.h all `#include "liblcars.h"` which includes them back — the circular includes only work because of guard ordering. After this task each module includes `lcars_types.h` (+ what it actually uses) and is order-independent.
- [x] **B2. Give each `lcars_*.h` the single-header shape AGENTS.md prescribes:** declarations always visible, function bodies under `#ifdef LCARS_IMPLEMENTATION`. Today lcars_db.h, lcars_gap_buffer.h, lcars_text.h, lcars_ui.h, lcars_hypermedia.h have bare definitions that only link because they're included exactly once from inside liblcars.h's implementation section. This also makes the big forward-declaration block in liblcars.h:192-249 unnecessary — each module declares its own API.
- [x] **B3. Type `State.voiceApi` as `VoiceRecApi *` instead of `void *`.** lcars_voice_rec.h is already included by liblcars.h; the cast is repeated at every use site (liblcars.h:386, 619, 847; lcars_ui.h:183).

## C. Break up the god-functions

- [x] **C1. Extract a key-repeat helper.** The pattern `if (!e->isMovingX) e->moveXStartTime = GetTime(); ... IsKeyPressed(K) || (GetTime() - start > delay && frameCounter % N == 0)` is hand-rolled six times (left/right/up/down at liblcars.h:1230-1356, backspace/delete at 1454-1481), each with its own bool+float pair in `Element`. A `KeyRepeat` struct (held flag + start time) and one `KeyRepeatFired(KeyRepeat *, int key, float delay, int nFrames, int counter)` collapse ~150 lines and 12 Element fields into 6 structs.
- [x] **C2. Extract word-boundary search.** The Ctrl+arrow word-jump logic is mirrored, near-identical code for left (liblcars.h:1241-1257) and right (1278-1297). One `int FindWordBoundary(String text, int from, int dir)` used by both.
- [x] **C3. Split `Update()` (liblcars.h:617-1532, ~915 lines) into per-concern functions:** `UpdateVoiceInput`, `UpdateDragResize`, `HandleElementClick` (the on_click switch), `UpdateTextEditor(State*, Element*)`, `UpdateEntryListPanel(State*, Element*)`, `UpdateScrollbarInput(State*, Element*)`. The `ELEM_TEXT_EDITOR/ELEM_ENTRY_LIST` case alone is ~640 lines. Depends on C1/C2 for the editor part to come out clean.
- [x] **C4. Split `UpdateDrawFrame()` (liblcars.h:1534-1993):** per-kind `DrawElementX()` functions (entry-list panel, text editor chrome, sphere + its debug text), plus `DrawEditHandles`, `DrawDebugOverlay`, `DrawNotification`. Move the global keyboard shortcuts (Ctrl+D/R/H/E/Space, Super+S at 1535-1554) into an input function in `Update` — they don't belong in the draw entry point. Also deduplicate the startup-timing printf block in `Init()` (liblcars.h:549-606 — the two `#ifdef` branches share ~15 identical lines).
- [x] **C5. Unify scrollbar geometry into one module.** The scrollbar rects (x/y/width/height, up/down buttons, track, handle height, scroll range, handle Y) are computed independently — and must match — in input handling (liblcars.h:966-1093 and 1103-1126) and drawing (1820-1867). Extract `ScrollbarLayout ComputeScrollbar(...)` + `ScrollbarHandleInput()` + `DrawScrollbar()`.
- [x] **C6. Unify entry-list panel geometry — this hides a real bug.** List width (collapsed 30 / expanded 350), 45px header, 90px item stride, 80px item height are re-derived in at least three places (liblcars.h:873-960, 1641-1768; lcars_text.h:306-312). lcars_text.h:308 uses **220.0f** where everywhere else uses **350.0f**, so the cursor-hide hit-test disagrees with the actual panel. One `EntryListLayout ComputeEntryListLayout(const Element *)` used by update, draw, and text code.
- [x] **C7. Name the magic numbers** once C5/C6 exist: scroll speed 30.0f, repeat delays 0.4f/0.5f, min handle heights 20/15, max 32 list entries, 4096 initial gap-buffer capacity, editor padding 5, handle sizes 16/8, etc.

## D. Data model

- [ ] **D1. Restructure the `Element` god-struct (~45 fields).** Group per-kind state into sub-structs — `TextEditorState` (gap buffer, selection, scroll, key-repeat), `EntryListState` (listCollapsed, listScrollY, selectedEntryId, kindList, selectedKind), `SphereState` (model, camera, renderTexture, rotation) — ideally in a union since kinds are exclusive. Shared: kind, position, size, colors, text, on_click, drag/resize state. Do after C-tasks so field moves touch small functions, not the monoliths.
- [ ] **D2. Extract a standalone `GapBuffer` struct.** lcars_gap_buffer.h functions take `Element *` but only touch `gapBuffer/gapStart/gapEnd/textCapacity` + selection fields. A self-contained `GapBuffer` (plus a `Selection` struct reused by DeleteSelection/Start/EndTextSelection) makes the editor core testable without raylib. Pairs with D1.
- [ ] **D3. Replace `float *width, *height` with plain floats.** The pointer indirection existed for the legacy shared-layout variables; the hypermedia path already allocates a private float per element (lcars_hypermedia.h:289-294). Blocked on A1 (legacy path removal); `make_text`'s NULL width/height convention needs an explicit "auto-size" flag instead.
- [ ] **D4. Add element `id`s to hypermedia and a `FindElementById()`, then remove positional hacks:** URL input hardcoded as `s->elements[0]` (liblcars.h:813-815, commented "Hack"), sphere status rectangle located by matching position (0,4) (liblcars.h:325-332), voice button located by scanning for its action (liblcars.h:393-400 — acceptable, but id makes it uniform).

## E. Database layer

- [x] **E1. Extract `SwitchToEntry(State *, Element *, int id)`.** The sequence "save current entry → set selectedEntryId → GetEntryContentFromDB → LoadEntryIntoEditor → StringFree" is repeated four times: NavigateEntryList (liblcars.h:468-472), new-entry click (918-922), item click (944-950), delete fallback (1027-1031).
- [x] **E2. Extract `CreateNewEntry(State *, kind, title) → int id`.** The strftime-datename + `INSERT INTO entries ...` + `sqlite3_last_insert_rowid` block is duplicated at liblcars.h:903-922 and 1012-1027, and near-duplicated in `InitDB` (lcars_db.h:58-73).
- [x] **E3. Fix the kind-mismatch bug while doing E1/E2:** the delete-fallback queries hardcoded `"personal_log"` (liblcars.h:1008) but everything else uses `e->selectedKind`, and `GetFirstPersonalLogId` actually queries `'architect_log'` (lcars_db.h:189). Deleting the last entry of any other kind silently jumps kinds. Introduce one `DEFAULT_ENTRY_KIND` and use `selectedKind` consistently; rename `GetFirstPersonalLogId`.
- [x] **E4. Stop querying the DB every frame.** `GetEntriesByKind` runs inside the draw loop (liblcars.h:1687) and again in several input paths (884, 927, 458) — with a fresh `EntryListItem items[32]` stack buffer each time. Cache the list in the entry-list element and invalidate on create/delete/edit/kind-switch.
- [ ] **E5. Debounce content writes.** `UpdateEntryContentInDB`/`UpdateLogInDB` execute an UPDATE on every keystroke (liblcars.h:1483-1490) and every voice chunk (654-659). Save after an idle interval and on blur/entry-switch instead.
- [ ] **E6. Use prepared statements everywhere.** Reads already use `sqlite3_prepare_v2`; writes go through `sqlite3_mprintf` + `ExecSQL` (`UpdateEntryContentInDB`, `DeleteEntryFromDB`, InitDB insert). One bind-and-step helper removes the format-string style split.
- [ ] **E7. Bounds-check `KindList`.** `GetAllKindsFromDB` writes `kinds[kindList.count++]` with no `MAX_KINDS` check (lcars_db.h:134-140) — 33 distinct kinds overflow the array. Also note it allocates into `doc_arena` on every list click (liblcars.h:926), growing the arena until the next document load; cache per E4.

## F. Text & rendering

- [ ] **F1. Deduplicate glyph-advance iteration.** `GetCharIndexAtMouse` (lcars_text.h:29-129) and `DrawTextBoxedSelectable` (131-325) each reimplement the codepoint/advance/wrap walk; if wrap rules change in one, hit-testing diverges from rendering. Extract a shared per-glyph layout iterator both consume.
- [ ] **F2. Remove entry-list knowledge from the text renderer.** `DrawTextBoxedSelectable` computes its own `isMouseOverList` with its own (wrong — see C6) list width to decide cursor visibility (lcars_text.h:306-313). Pass a `bool drawCursor` from the caller instead.
- [ ] **F3. Compute line starts once per frame.** `int lineStarts[1024]; GetLines(...)` is executed on the stack in three separate key-handling blocks (liblcars.h:1359-1362, 1391-1394, 1399-1401). Compute once per editor per frame (or maintain incrementally in the gap buffer, per D2).
- [ ] **F4. Close the `IsHoveringElement` UB hole and finish elbow orientations.** For `ELEM_ELBOW` with an orientation outside 0/3 the function falls off the end without a return (lcars_ui.h:274-318) — undefined behavior; orientations 1/2 hit `TODO` (exit). `DrawElbow` silently draws nothing for 1/2 (lcars_ui.h:367-370). Add a default return, then either implement 1/2 or reject them at parse time.

## G. Hypermedia module

- [ ] **G1. Make tag/color/action parsing table-driven.** Three if-chains — tag_name→ElemKind (lcars_hypermedia.h:220-235), `ParseColor` (30-54), `ParseAction` (56-72) — become static `{name, value}` arrays with one lookup helper. Adding a component then touches one table row.
- [ ] **G2. Fix `GetAttributeValue` matching and API.** `strstr(tag, "x=")` also matches `max=`/`_x=` (lcars_hypermedia.h:12-14) — require a preceding space/quote boundary. Return `bool` instead of a dead `const char *`. Decide and document behavior for unquoted values (currently silently NULL).
- [ ] **G3. Give `ACTION_LOAD_HYPERMEDIA` a real `href` attribute** stored on the Element, replacing the elements[0]-as-URL-input hack (see D4) and the inline URL sniffing at liblcars.h:816-819. Extract `bool IsDocumentURL(const char *)` shared with `LoadDocumentContent`.
- [ ] **G4. Split `LoadDocumentContent` into `LoadFromHTTP` / `LoadFromFile`,** and split the tag-attribute-extraction + element-construction body of `LoadHypermediaDocument` (lcars_hypermedia.h:237-330) into `ParseElementTag(...)` so the scan loop stays one screen tall.

## H. App shell (lcars.c, lcars_http.h)

- [ ] **H1. Extract `CreateAppState()`.** The `calloc(10, sizeof(State))` + arena mallocs + `arena_init` block is duplicated in `InitDBMinimal` (lcars.c:34-49) and `main` (110-124). Revisit the "×10 just in case" hack — it papers over hot-reload struct-size drift; at minimum centralize and document it.
- [ ] **H2. Extract `LoadAppLibrary()`** for the copy-so/dlopen/dlsym/unlink boilerplate duplicated between startup (lcars.c:176-206) and hot-reload (220-238), including the error handling that the reload path currently skips.
- [ ] **H3. Split the 445-line `HandleHTTPConnection`** (lcars_http.h:207-652) into request parsing, auth check, and per-route handlers (`HandleGetEntries`, `HandlePostEntry`); hoist the thrice-hardcoded `"lcars.db"` path into one constant shared with liblcars.
- [ ] **H4. Check `system()` return values** (`./scripts/db-push.sh` at liblcars.h:1553; `make`/`cp` in lcars.c:181,218-222) and surface failure via notification instead of ignoring it.

## I. Conventions & small hygiene

- [ ] **I1. Naming sweep.** Mixed `make_rectangle` / `updateNotification` / `ToggleVoiceRecording` / `clickOrHoverNotification`; pick one convention per category (e.g., PascalCase functions, snake_case for constructors is fine if consistent) and align. Fix `controlls` typo if the fields survive A3.
- [ ] **I2. Harden the `TODO` macro:** `fprintf(stderr, "...\n")` + `abort()` instead of `printf` without newline + `exit(1)` (liblcars.h:38), so it can't vanish into buffered stdout.
- [ ] **I3. Define an arena OOM policy.** `GapInsertChar` memcpys into an unchecked `arena_alloc` result (lcars_gap_buffer.h:35-40); other sites NULL-check inconsistently. Decide (probably: log + abort for the fixed-size arenas) and apply uniformly. Consider `ArenaTemp` begin/end scopes for scratch use instead of relying solely on end-of-frame reset.
- [ ] **I4. Clarify the String API.** `StringFree` only NULLs pointers (arena owns memory) — the name lies; rename to `StringClear` or drop it. Document that `StringDup` of a static string aliases the same data. Both are footguns for new code.
- [ ] **I5. Makefile touch-up:** `RAYLIB_LIB` is referenced in `LDFLAGS_DYN` but never defined; sanitizer flags ride inside `CFLAGS_DYN` while release uses a commented-out line — separate `SANITIZE ?= 1` style toggles.

## Suggested order

A (1-3 especially) → B1/B2 → C1-C7 → E1-E7 → D1-D4 → F, G, H, I in any order. A and B are prerequisites that make every later diff smaller; C and E remove the bulk of duplication; D is the deepest structural change and benefits from the code already being in small functions.
