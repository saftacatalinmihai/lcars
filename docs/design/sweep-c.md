# Simplification sweep of the C (survey, 2026-10-13, 0.174.12)

The C is 31k lines across `lcars.c`, the `lcars_*.h` modules, `lcars_cli.c`,
`lcars_voice_rec.c` and `lcars_resources_download.c`, plus the Makefile.
This is the survey of where it can get smaller. Round 1 (0.174.12) did only
the deletions with no behaviour change. Round 2 (0.175.0-0.177.4) did every
ranked item below, or made it moot: see its table. The rest of this file is
the survey as it was written, kept for its reasoning.

## How dead code was looked for

- **Functions:** both programs were linked with `-Dinline= -O0
  -fkeep-static-functions -ffunction-sections -Wl,--gc-sections
  -Wl,--print-gc-sections`. The linker drops every function nothing
  reachable calls, however indirectly, so this catches functions that are
  only called from dead code, which `-Wunused-function` misses. In the
  desktop build only `ForgetPendingSave` and `NetHttpForgetAsync` went. Both
  are called only from `FlushPendingSavesForUnload`, under `__EMSCRIPTEN__`,
  so they go with item 2. The CLI keeps nothing dead of its own: the
  `lcars_string.h`/`lcars_arena.h`/`lcars_json.h` helpers it does not call
  are the app's.
- **Struct fields:** a script counted reads and writes of every field of
  every struct. `State.textBoxEditMode` (never touched), `State.lcarsColor`
  (written, never read) and `VoiceRecApi.Init`/`.Shutdown` (filled in and
  never called through) were the only ones. All four are gone.
- **Defines, enum values, file-scope globals, typedefs:** each one is used
  at least once outside its own definition. `CALDAV_COL_COUNT` is a
  sentinel, so it stays.
- **Prototypes with no body:** none.

## Round 1 (done, 0.174.12)

| What | Where | Lines |
|---|---|---|
| Four copies of the JSON string escaper became one byte table, `json_escape_byte`. `StringJsonEscape`, `json_escape_buf`, `jsonbuf_append_json_string` and `cli_buf_append_json_string` all call it | `lcars_string.h`, `lcars_http.h`, `lcars_cli.h` | -80 |
| `caldav_header` and `EngineerHeader` were the same function. They became one, `CopyHeaderValue`, beside `find_header_value` | `lcars_http.h`, `lcars_caldav.h`, `lcars_engineer.h` | -40 |
| `State.lcarsColor`, `State.textBoxEditMode`, `VoiceRecApi.Init`/`.Shutdown` | `lcars_types.h`, `liblcars.h`, `lcars_voice_rec.h`, `lcars.c` | -7 |
| An empty `#ifdef __EMSCRIPTEN__`/`#endif`, and a comment sending the reader to the wrong REFACTORING.md task | `lcars.c` | -2 |
| `run-web` was a copy of `serve`. It now depends on it | `Makefile` | -3 |
| ARCHITECTURE.md: the voice section and the deck's contract still described the deck's own talk sheet, `#talksay`, `engSay`/`engSpeak`, `talkSend` and the deck's hold-to-talk, all of which 0.172 removed; `openEng`/the Eng button/`W` in the console; `crsqlite` in `vendor/`. `GET /metrics` and `lcars_metrics.h` were missing. The build-variants table now says which variants nothing builds | `ARCHITECTURE.md` | edited |

`State` lost two fields, so a running hot-reload session has to be
restarted, not reloaded. That build does not compile anyway (item 3).

## Round 2 (0.175.0 on)

The captain's orders on the ranked list below: the desktop app goes
(recoverable from tag `desktop-raylib-last`, `04872fd`), `/transcribe`
moves to Deepgram, `lcars-cli` goes HTTP only; then items 7, 9, 10, 11.

| Item | Version | Own C + Makefile |
|---|---|---|
| 1, with 2 and 3: the desktop app, the Emscripten build, hot reload | 0.175.0 | +150 -11,058 (and -381,864 vendored) |
| 5: `/transcribe` on Deepgram, Vosk gone | 0.176.0 | +195 -600 (and -361 vendored), plus `test/transcribe.py` |
| 4 (and 6, moot): `lcars-cli` HTTP only; `lcars_string.h` folded into `lcars_json.h` | 0.177.0 | +96 -886 |
| 7: request bodies through `lcars_json.h` (fixes `\n`/`\u00e9` in titles) | 0.177.1 | +136 -176 |
| 9: date math on `timegm`/`gmtime_r` | 0.177.2 | +58 -96 |
| 10: one growable buffer, `JSONBuf` in `lcars_json.h` | 0.177.3 | +281 -338 |
| 11: `HeaderForLog` over `CopyHeaderValue` | 0.177.4 | +9 -15 |

Items 6 (one entries query builder) and 8 (one client HTTP call for the
CLI and the desktop's remote backend) are moot: the CLI's SQL and the
desktop's client are gone. Nothing asked for could not be removed.

## Ranked

The score is lines saved ÷ risk, with risk 1 = nothing uses it or nothing
changes, 2 = behaviour changes or a path in daily use is touched, and 3 = a
feature goes. The line counts are measured spans of the code, rounded.

| # | Item | Lines | Risk | Score | Needs |
|---|---|---|---|---|---|
| 1 | Retire the raylib desktop app | ~10,000 | 3 | 3300 | the captain |
| 2 | Drop the Emscripten build | ~800 | 1 | 800 | an order |
| 3 | Drop hot reload | ~170 | 1 | 170 | an order |
| 4 | `lcars-cli` HTTP only (drop `--db`) | ~700 | 2 | 350 | the captain |
| 5 | `/transcribe` on Deepgram, Vosk gone | ~1,100 + 70MB | 3 | 370 | the captain, after 1 |
| 6 | One entries query builder for server and CLI | ~250 | 2 | 125 | an order (moot after 4) |
| 7 | Request bodies through `lcars_json.h` | ~105 | 2 | 52 | an order. Also a bug fix |
| 8 | One client HTTP call for the CLI and the desktop remote | ~90 | 2 | 45 | an order (moot after 1) |
| 9 | Date math on `timegm`/`gmtime_r` | ~80 | 2 | 40 | an order |
| 10 | One growable buffer (`CliBuf` = `JSONBuf`) | ~70 | 2 | 35 | an order |
| 11 | `HeaderForLog` over `CopyHeaderValue` | ~8 | 1 | 8 | an order |

### 1. Retire the raylib desktop app

- **Today:** `liblcars.h` (2230), `lcars_ui.h`, `lcars_text.h`,
  `lcars_gap_buffer.h`, `lcars_inspector.h`, `lcars_context_menu.h`,
  `lcars_hypermedia.h`, `lcars_hypermedia_controls.h`,
  `lcars_doc_writer.h`, `lcars_login.h`, `lcars_db_remote.h`,
  `lcars_net.h`, the editor half of `lcars_db.h` (caches, debounced saves,
  `make_entry_list`), the recording thread in `lcars_voice_rec.c`, and
  `pages/`. That is ~10k lines, plus raylib, raygui and miniaudio in
  `vendor/`. The VPS runs `--http-only`. The captain works in the web
  console and the deck.
- **Instead:** `lcars` is the server: `InitDBMinimal` + `RunHTTPServer`.
- **Risk 3:** a feature goes. CI's xvfb smoke-run is a raylib test and goes
  with it.
- **Tests:** the functional tests all run the server, and stay.

### 2. Drop the Emscripten build

- **Today:** 679 lines inside `#ifdef __EMSCRIPTEN__` branches:
  `lcars_net.h`'s `fetch()` transport (283), `lcars_voice_rec.c` (164),
  `lcars.c` (86), `lcars_db_remote.h` (64), `liblcars.h` (48),
  `lcars_resources_download.c` (34). Then `FlushPendingSavesForUnload`,
  `ForgetPendingSave`, `NetHttpForgetAsync` (~60), and the Makefile's
  `WEB_*`, `sqlite3.web.o`, `lcars-web`, `serve`, `run-web` and `setup-*`
  targets (~50). `vendor/sqlite3.c` is used only by `sqlite3.web.o`. No
  checkout has `emsdk/`, so nothing builds any of it, and the web console
  replaced it long ago.
- **Instead:** nothing.
- **Risk 1.**
- **Tests:** release and lib build clean.

### 3. Drop hot reload

- **Today:** `lcars.c`'s `LoadAppLibrary` and its reload loop (~110), the
  `Fn_*` pointer types, `CreateAppState`'s 10x over-allocation and its
  comment, and the `VoiceRecApi` table with `s->voiceApi` in three places
  of `liblcars.h` (~30). Also the Makefile's `lcars-dynamic`/`run-dynamic`,
  CLAUDE.md's hot-reload paragraph, and ARCHITECTURE.md's "Hot reload
  mechanics". **The host TU does not compile on deb** (`isalnum`
  undeclared in `lcars_http.h`, plus `-Wshadow` and unused-function
  warnings), so nobody has used it for a while.
- **Instead:** the static build only. `liblcars.c`/`lcars-lib.so` can stay
  as the quick compile check, or `make lcars-release` can replace it.
- **Risk 1.**
- **Tests:** release and lib build clean.

### 4. `lcars-cli` over HTTP only

- **Today:** `lcars_cli.h` 818-1450 (`CliDbOpen`, `cli_sql_*`,
  `CliDbBuildFilter`, `CliReadEntryStmt`, `CliDbList`/`Get`/`Create`/
  `Update`/`Delete`/`Kinds`/`Stats`), plus the `--db`/`--db-path` option
  handling and the backend switch in each `Cli*` wrapper. This is a second
  implementation of the server's `/entries`. `no1.py` and `crew_tool.py`
  already refuse `--db`.
- **Instead:** the HTTP backend only.
- **Risk 2:** the captain loses the CLI with the server down. It is also a
  second writer to `lcars.db`, which is a reason to drop it.
- **Tests:** `scripts/test_no1.py`, `test_crew.py`, and a CLI round trip
  against a scratch server.

### 5. `/transcribe` on Deepgram, Vosk gone

- **Today:** `lcars_voice_rec.c` (828), `lcars_resources_download.c/.h/_main.c`
  (270), the `ensure-resources` step, and ~70MB of `resources/`
  (libvosk.so, the model). Once item 1 is done, the only user is
  `POST /transcribe`, for the G2 glasses. The server already holds
  `DEEPGRAM_API_KEY`.
- **Instead:** `/transcribe` sends the PCM to Deepgram's
  `/v1/listen?encoding=linear16&sample_rate=16000`, about 60 lines in
  `lcars_say.h`'s style.
- **Risk 3:** offline speech recognition becomes cloud.
- **Tests:** a new `/transcribe` check with a stand-in Deepgram, like
  `ptt.py`'s.

### 6. One entries query builder

- **Today:** the server has `filter_*` (95), `NormalizeTimestamp`,
  `BuildLikePattern`, `ResolveOrderBy` and `BuildEntryFilter`. The CLI has
  copies of each: `cli_sql_*` (87), `CliNormalizeTimestamp`,
  `CliLikePattern`, `CliOrderColumn`/`CliValidOrder`, `CliDbBuildFilter`.
- **Instead:** one `static inline` header that both TUs include, the way
  `lcars_json.h` is shared.
- **Risk 2.**
- **Tests:** `test/dates.sh` (the date bounds), `logins.py`, and CLI
  `list` filters against a scratch DB.

### 7. Request bodies through `lcars_json.h`

- **Today:** `json_get_string`, `json_get_string_arena`, `json_get_int`
  and `json_get_float` in `lcars_http.h` (156 lines, ~40 call sites across
  `lcars_http.h`, chat, say, engineer, logins, caldav, embed). They find a
  key with `strstr`, so a string *value* containing `"kind"` is taken for
  the key. `json_get_string` copies the byte after a backslash, so a
  title's `\n`, `\t` or `é` arrive as `n`, `t`, `u00e9`. Python's
  `json.dumps` writes non-ASCII as `\u` escapes by default, so this happens
  to real clients (seen in this sweep's smoke test). The arena variant
  decodes `\n`/`\t` but not `\u`.
- **Instead:** keep the four signatures over `json_member` +
  `json_span_string`/`_long`/`_double`, which already decode `\u` (~50
  lines).
- **Risk 2:** every POST/PUT body goes through this.
- **Tests:** `logins.py`, `caldav.py`, `metrics.py`, plus a new round trip
  of a title with `\n`, `é` and an embedded `"kind"`.

### 8. One client HTTP call

- **Today:** `CliHttpRequest` + `CliCurlWrite` (`lcars_cli.h`) and
  `NetHttpRequest` + `CurlWriteMemoryCallback` (`lcars_net.h`). The two
  write callbacks are the same code. The CLI's copy exists only because
  `NetHttpRequest` cannot send credentials.
- **Instead:** one `NetHttpRequest` with an auth header argument, in a
  header both TUs include.
- **Risk 2.**
- **Tests:** a CLI round trip, and `--remote` against a scratch server.

### 9. Date math on libc

- **Today:** `caldav_days_from_civil`/`caldav_civil_from_days`/
  `caldav_epoch*` (`lcars_caldav.h`), `logseq_civil_to_days`/
  `logseq_day_from_days` (`lcars_logseq.h`), and `MetricsParseUtc`
  (`lcars_metrics.h`). They are three hand-rolled UTC calendar
  conversions.
- **Instead:** `timegm`/`gmtime_r` (glibc, `_DEFAULT_SOURCE`). The CalDAV
  zone rules (TZif) stay hand-rolled; see "Considered and kept".
- **Risk 2.**
- **Tests:** `caldav.py`, `metrics.py`, `test/dates.sh`, and a logseq
  export dry run.

### 10. One growable buffer

- **Today:** `CliBuf` (`cli_buf_*`, 74 lines) and `JSONBuf` (`jsonbuf_*`,
  93) are both arena-backed append buffers. `JSONBuf` also has an overflow
  flag and a cap.
- **Instead:** one, in `lcars_string.h`.
- **Risk 2:** the server's overflow-to-500 path must survive.
- **Tests:** `logins.py`, and the CLI.

### 11. `HeaderForLog` over `CopyHeaderValue`

- **Today:** `HeaderForLog` copies a header value the same way
  `CopyHeaderValue` does, then defangs it.
- **Instead:** call `CopyHeaderValue`, then defang.
- **Risk 1.** Not done in round 1 because the trimming differs:
  `CopyHeaderValue` trims trailing blanks and `HeaderForLog` does not, so
  the request log would change.

## Considered and kept

- **The CalDAV TZif reader** (`caldav_be32` … `caldav_default_zone`, ~380
  lines). libc's zones are process-global (`TZ` + `tzset`), and the server
  answers on many threads at once.
- **The CalDAV XML reader** (`xml_*`, ~270 lines). No XML library is
  linked. libxml2 would add a dependency to save fewer lines than it costs
  to wire in.
- **`base64_encode` (`lcars_json.h`) and `base64_decode` (`lcars_http.h`).**
  Folding them saves nothing: they are each other's inverse, not copies.
- **`lcars_json.h`**: already the shared scanner. Items 7 and 8 build on it.

## ARCHITECTURE.md

Fixed in round 1: see the table above. Everything else checked against the
code still holds: every backticked identifier in ARCHITECTURE.md is
searched for in the tree, and every C route is in its table. The
exceptions are names the text deliberately describes as gone (`wallView`)
or as outside the repo (`lcars-fw`, `tailscale0`, llama.cpp's
`output_reserve`). Items 1-3 each remove a section when they are done:
"Build variants", "Hot reload mechanics", the module map's rows, and
"Hypermedia documents" for item 1.
