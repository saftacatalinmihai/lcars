# The open-source release: the build — design

The captain's order: a downloadable Linux executable that runs the server,
ideally one file holding the server, the CLI and the UI; the media and file
paths configurable (the captain's NAS is a Synology, mounted at the path CLAUDE.local.md names; others will
want something else). This is the build half of O'Brien's
`docs/design/open-source.md` (branch `eng/obrien-c33`, §2a, §4 "What I need
from Torres", §6 step 7); it uses his names (`LCARS_DATA_DIR`, `lcars.env`,
`lcars init`). Nothing here is built yet.

Surveyed on 0.259.0, on the VPS.

## 1. What links today

### 1a. The binaries

| Binary | Built by | Links | Loads / runs at run time |
|---|---|---|---|
| `lcars` (server) | `make lcars` (debug, ASan), `make lcars-release` (-O3), `make lcars-portable` (lcars-release inside `debian:12-slim`, for an older glibc) | `-lcurl -lsqlite3 -lz -lm -lpthread`, all dynamic. On the VPS sqlite is `/usr/local/lib/libsqlite3.so` 3.46.1, built from source on the box; libcurl pulls in ~35 more shared libs (OpenSSL *and* GnuTLS, nghttp2/3, krb5, ldap, ssh2, rtmp, idn2, psl, brotli, zstd) | `lcars-ui/` from disk per request; `/usr/share/zoneinfo/<TZID>` (CalDAV); `claude`, `ffmpeg`, `/usr/bin/python3 scripts/engineer.py` spawned (§1c) |
| `lcars-cli` | `make lcars-cli` | `-lcurl -lm` (no sqlite: it is an HTTP client) | nothing; `$EDITOR`, `LCARS_URL` |
| `lcars-cli` **on the VPS** | until 0.276.2 `~/lcars/lcars-cli/build.sh` — a gitignored directory of *copied* sources with vendored curl headers, linking `libcurl.so.4` by path; since then `~/lcars/bin/lcars-cli`, the one binary's link (the copy retired in 0.279.2, §5c step 4) | same | the hourly linker, Strava timer and the chat's skill run *this* one |

Two things the order expected that are not there:

| Asked about | Fact |
|---|---|
| the crsqlite extension | **Gone.** Not in the tree, no `sqlite3_load_extension` anywhere; ARCHITECTURE.md's build table records it as out (CHANGELOG ~0.175). The server needs plain sqlite3, no extension, no FTS5 (search is LIKE + the embedder's vectors over HTTP). |
| `lcars-lib.so` | **Gone** with the raylib app (0.175.0): it was the desktop hot-reload library. There is no shared object to ship. |

Symbols: compiled separately, `lcars.c` and `lcars_cli.c` share exactly one
global symbol, `main` (checked with `nm -g`); everything else is `static`.
So the two can link into one executable with the CLI's `main` renamed.

### 1b. The UI

| Fact | Where |
|---|---|
| Served from disk, every request, `$LCARS_UI_DIR` or `./lcars-ui` (relative to the working directory) | `UIRoot()`, lcars_ui_files.h:89 |
| Text and meshes gzipped on the fly, with a bounded in-memory cache keyed on size+mtime; Range for index.html (the update check's 206); 304s | `UISendGzip`, test/uigzip.py |
| Not embedded anywhere today | — |
| What would ship: `git ls-files lcars-ui` minus `test/` and `report/` | 82 files, 8.2 MB raw, 4.4 MB as one gzip -9 tar (deck/ 2.7 MB of glb, index.html 2.0 MB, crew/ 1.3 MB, vendor/three 1.2 MB, deck.html 0.8 MB) |

### 1c. What the server spawns or calls out to

| Feature | How | Needs on the host |
|---|---|---|
| The computer, navigator, `/ask` | spawns the `claude` CLI (`LCARS_CLAUDE_BIN`, else PATH, `/usr/local/bin`, `/usr/bin`) with `lcars-cli`'s dir (`LCARS_CLI_DIR`, default `$HOME/lcars/lcars-cli`) first on PATH | `claude` installed and logged in. **There is no Anthropic HTTP call in the binary**, so no API key and no TLS for it |
| Engineers' routes | `/usr/bin/python3 $CWD/scripts/engineer.py` (`LCARS_ENGINEER_SCRIPT`) | python3, the scripts beside it, git, gh |
| Media cuts, posters | `ffmpeg` (`LCARS_FFMPEG_BIN`) | ffmpeg |
| Speech, transcription | libcurl → `https://api.deepgram.com`, ElevenLabs | TLS + CA certificates |
| Embeddings | libcurl → `LCARS_EMBED_URL` (default `http://127.0.0.1:8091`, llama.cpp via `lcars-embed.service`) | the embed service, or `LCARS_EMBED=0` |
| CalDAV | **inbound only**: the server is the CalDAV server; no outbound call | tzdata in `/usr/share/zoneinfo` |
| Strava, Logseq | the CLI, libcurl → https | TLS + CA certificates |
| Inbound TLS | **none**: the server speaks plain HTTP behind `tailscale serve` | a proxy (Tailscale, Caddy, nginx) for anything off-box |

### 1d. The Python pieces — they ship as scripts, not in the binary

| Piece | Runs as | Needs |
|---|---|---|
| `scripts/lcars_linker.py` (hourly linker) | `lcars-crew@` timer | python3 (stdlib only), `lcars-cli` |
| `scripts/crew.py`, `crew_tool.py`, `crew_notes.py`, `crew/*.md` | systemd **user** timers/services | python3, `claude` CLI, `lcars-cli` |
| `scripts/engineer.py`, `seat.py`, `no1.py`, `report.py` | spawned by the server; the engineers' sessions | python3, `claude`, git, gh, a clone with worktrees |
| `scripts/db-prune.py`, `shares.py` | timers | python3 (`sqlite3` module) |
| `lcars-embed.service` | llama.cpp's `llama-server` + a gguf in `resources/` | llama.cpp, the model; optional |
| the Blender scripts (`bpy`) | by hand, to build deck assets | Blender; dev only, never shipped as a tool |

All of `scripts/*.py` import only the standard library. Packing Python into
the C binary would buy nothing and cost a lot; they go in the release
tarball beside the binary, with the unit files.

## 2. One binary

### 2a. The command line

| Invocation | Does | Today's equivalent |
|---|---|---|
| `lcars` / `lcars serve [opts]` / `lcars --port N …` / `lcars -s` | the server | `lcars -s` (the live unit's ExecStart): **a first argument starting with `-`, or none, means serve**, so the unit's line does not change |
| `lcars cli <args>` | the CLI, exactly `lcars-cli <args>` | `lcars-cli` |
| `lcars-cli <args>` (a symlink: argv[0]'s basename) | the same, busybox-style | so the linker, the timers and the chat's skill, which run `lcars-cli` from PATH, work unchanged |
| `lcars init DIR [--port N] [--user U]` | makes DIR, `DIR/media/`, a generated password (getrandom), `DIR/lcars.env` (mode 600, the Start keys set, every feature key commented with its one-line purpose), an empty journal; prints the URL and the login. **Idempotent: never overwrites an existing lcars.env or lcars.db**; says what it left alone | O'Brien's §4 |
| `lcars version` / `--version` | the version, from CHANGELOG at build time (`-DLCARS_VERSION=…`) | none |

Build: two objects, one link —
`cc … -c lcars.c` and `cc … -Dmain=LcarsCliMain -c lcars_cli.c`, linked with
`-DLCARS_ONE_BINARY` so `lcars.c`'s `main` dispatches. No new `.c` file;
`lcars_cli.c` keeps its own `main` for `make lcars-cli`, which stays for
the VPS until step 3's switch.

### 2b. The paths, all at run time

| Setting | Flag | Env | Default | Live service |
|---|---|---|---|---|
| Data directory | `--data DIR` | `LCARS_DATA_DIR` | `.` (the working directory) | unit's `WorkingDirectory=~/lcars` → unchanged |
| Database | `--db FILE` | `LCARS_DB_PATH` | `$DATA/lcars.db` | `~/lcars/lcars.db`, as now |
| Config file | — | — | `$DATA/lcars.env`, read at start if present; **the real environment wins** | there is none in `~/lcars`, so nothing is read; `~/.env` keeps coming from the unit |
| Media root | — | `LCARS_MEDIA_ROOT` | today the NAS's mount compiled in; proposed `$DATA/media` | **`~/.env` does not set it (checked): the live server relies on the compiled default.** Changing the default without first adding `LCARS_MEDIA_ROOT=<the mount>` to `~/.env` puts new uploads on the VPS's disk and the NAS's files out of reach |
| UI | — | `LCARS_UI_DIR` | disk `./lcars-ui` if the build has no embedded UI (every build the VPS makes); the embedded copy in a release build | unchanged: the VPS build is not the embedded one |
| CLI dir for the chat | — | `LCARS_CLI_DIR` | `$HOME/lcars/lcars-cli`; one-binary: a `lcars-cli` symlink to the running binary in `$DATA/bin/`, made at start | unchanged |
| Chat sessions dir | — | `LCARS_CHAT_DIR` | `$HOME` | unchanged |
| Media cache | — | `LCARS_MEDIA_CACHE` | `~/.cache/lcars-media` | unchanged |
| engineer.py | — | `LCARS_ENGINEER_SCRIPT` | `$CWD/scripts/engineer.py`; python3 hard-coded as `/usr/bin/python3` → take it from PATH | unchanged |

`--data` does **not** `chdir`: every relative default above is spelled out
against it, so a forgotten relative path cannot quietly land elsewhere.

### 2c. What changes in which files

| File | Change |
|---|---|
| `lcars_db.h:17` | `#define LCARS_DB_PATH "lcars.db"` → `const char *LcarsDBPath(void)`, set once in `main` before any thread starts |
| `lcars.c` | `InitDBMinimal`; argument parsing for `--data`, `--db`, `serve`/`cli`/`init`/`version`; the argv[0] dispatch; reading `lcars.env`; **logs the absolute db path and its row count at start** |
| `lcars_http.h:1386`, `lcars_caldav.h:4458`, `lcars_embed.h:677` | `sqlite3_open(LcarsDBPath(), …)`, the error messages likewise |
| `lcars_events.h:77,81,92` | the same, and `LCARS_DB_PATH "-wal"` (string-literal concatenation) becomes an `snprintf` into a buffer made once |
| `lcars_media.h:107,162` | the media root default (a separate step, §5) |
| `lcars_ui_files.h` | an embedded table beside `UIRoot()` (§2d) |
| `lcars_chat.h`, `lcars_engineer.h` | the CLI dir symlink; python3 from PATH |
| `lcars_cli.c` | none for `-Dmain=`; `lcars init` lives in `lcars.c` (it needs no HTTP) |
| `Makefile` | §5's targets |

### 2d. The embedded UI

| Choice | Why |
|---|---|
| A build step (`scripts/ui-pack.py`) writes one blob of the shipped set (§1b) with an index (path, offset, size, a content hash for the ETag) and `.incbin`s it into the binary; only under `-DLCARS_EMBED_UI` | `xxd -i` of 8 MB is a 50 MB C file and a slow compile; `.incbin` is one line, works with gcc and clang on x86_64 and arm64 |
| Stored raw, not pre-gzipped | the existing gzip cache (`UISendGzip`) already compresses on first request and keeps it; the update check's Range on index.html needs the raw bytes anyway. ~8 MB of the binary |
| `LCARS_UI_DIR`, when set, wins over the embedded copy | a user can edit their own UI; the dev loop stays "save and reload" |
| mtime = the build time, ETag = the content hash | 304s and the service worker's update check keep working |

### 2e. The risk to the live service, and its guard

A path change that resolves to a different file **starts the server on an
empty journal**: `InitDB` makes the schema (and, since 0.273.0, no row), `/health`
answers, `vps-rebuild.sh` sees a healthy server, and the captain's phone
syncs against nothing (the outbox and mirror then hold the only copy of new
entries). So:

| Guard | Where |
|---|---|
| The default stays `./lcars.db`, byte for byte the same file | §2b |
| `~/.env` sets none of `LCARS_DATA_DIR`, `LCARS_DB_PATH` (checked, names only) | — |
| The start log names the absolute db path and its entry count | `lcars.c` |
| `vps-rebuild.sh` reads the entry count (authenticated `/entries?limit=1` or a count route) before and after the swap, and rolls back if it fell to one row or none | step 1 |
| **Step 1 deploys only on the captain's word**, not on Number One's, and he watches the first restart | §5 |

## 3. Portable

| Option | Verdict |
|---|---|
| glibc, dynamic (today's `lcars-portable`) | needs libcurl4 and libsqlite3 of compatible versions on the host; not "download and run" |
| glibc, static | glibc warns that `getaddrinfo`/NSS in a static binary loads the host's shared NSS modules anyway; curl's DNS breaks on mismatches. No |
| **musl, fully static, built in Alpine** (recommended) | Alpine ships `curl-static`, `openssl-libs-static`, `nghttp2-static`, `zlib-static`, `sqlite-static` (and brotli/zstd/idn2/psl static libs curl wants); `-static` gives one ELF that runs on any Linux ≥ 3.2 |

| Concern under musl | State | Work |
|---|---|---|
| Thread stacks (musl's default is 128 KB; each connection keeps a 1 MB arena on its stack) | already set explicitly: 4 MB (`HTTP_THREAD_STACK_BYTES`), the embedder's and events' too | none |
| `posix_spawn_file_actions_addclosefrom_np`, `pipe2`, `addchdir_np` | gated on glibc ≥ 2.34 (`CHAT_HAVE_GNU`); musl takes the fallback, which **does not close the server's sockets in `claude`/`ffmpeg`/engineer.py children** | accept with `accept4(…, SOCK_CLOEXEC)` and `SOCK_CLOEXEC` on the listener (right on glibc too); enable `pipe2`/`addchdir_np` on musl (both exist there) |
| musl's malloc under threads | slower than glibc's; the request path allocates from the arena, sqlite is the main malloc user | measure with `test/perf.py`'s server-side numbers; mimalloc is the fallback, not planned |
| CA certificates (Deepgram, ElevenLabs, Strava, Logseq over https) | a static curl looks at its compiled-in path only | probe the usual bundles at start (`/etc/ssl/certs/ca-certificates.crt` Debian/Ubuntu/Arch/Alpine, `/etc/pki/tls/certs/ca-bundle.crt` Fedora/RHEL, `/etc/ssl/ca-bundle.pem` SUSE) and set `CURLOPT_CAINFO`; `SSL_CERT_FILE` wins; if none, those features say "no CA bundle" (embedding Mozilla's 220 KB bundle is the alternative; it goes stale) |
| DNS | musl's resolver: no NSS, so no mDNS/`.local`; Tailscale MagicDNS works (it is a nameserver) | document |
| tzdata | CalDAV reads `/usr/share/zoneinfo`; present on every distro but minimal containers | document; a zone it cannot read is UTC today |

| Size (estimate, x86_64, stripped) | |
|---|---|
| server + CLI code | ~0.5 MB |
| sqlite | ~1.3 MB |
| curl + OpenSSL + nghttp2 + the rest | ~5 MB |
| the UI | ~8.2 MB |
| **total** | **~15 MB; ~7 MB as the release's .tar.gz** |

What a user must have: **nothing** to run the server and the CLI. Optional,
per feature (O'Brien §2b): `claude`, `ffmpeg`, python3 + git + gh for the
crew and engineers, llama.cpp for embeddings, a TLS proxy for off-box use.

arm64: **cheap.** GitHub's `ubuntu-24.04-arm` runners are free for public
repos and run the same Alpine container natively; no cross-compiler. The
only arch-specific line is `.incbin`, which both assemblers take.

## 4. The release workflow

| Piece | Design |
|---|---|
| Trigger | a tag `v*` (`v0.260.0`); the existing `c-cpp.yml` stays for pushes and PRs |
| Base | `c-cpp.yml`'s steps: build, start on an empty dir, `/health`, an authenticated `/kinds/roles` (a new journal is empty since 0.273.0, docs/design/kinds.md: no seed row to find) |
| Jobs | matrix `{x86_64: ubuntu-24.04, arm64: ubuntu-24.04-arm}`, each in `alpine:3.20`: `apk add build-base python3 curl-dev curl-static openssl-libs-static nghttp2-static zlib-static sqlite-static …`, `make lcars-static` |
| Version | `make` reads the top `## X.Y.Z` of CHANGELOG.md into `-DLCARS_VERSION`; the job **fails if the tag ≠ that version** (and run.sh already checks `APP_VERSION` against it) |
| Checks before attaching | `file lcars` says statically linked; `ldd` finds nothing; `lcars --version` = the tag; `lcars init $tmp`, `lcars --data $tmp` serves `/health`, `/ui/` (the embedded index.html, byte-equal to the source) and a gzipped deck.html; `lcars cli stats` and the `lcars-cli` symlink against it; and once in a bare `debian:stable-slim` and `fedora` container (no curl, no sqlite installed) |
| Artifacts | `lcars-X.Y.Z-linux-x86_64.tar.gz` and `-arm64`: `lcars`, `lcars-cli` → `lcars`, `scripts/` (the shipped ones), `crew/`, the unit files, README, LICENSE, the third-party notices; plus `SHA256SUMS` |
| Publish | `gh release create "$TAG" --notes-from` the CHANGELOG entry, with the files; `permissions: contents: write` on that job only |
| Where | the public repo (O'Brien's export carries the workflow); here it can run on a tag too, as the dry run |

## 5. Make targets, tests, and the order of the work

### 5a. Make targets

| Target | State |
|---|---|
| `lcars`, `lcars-release`, `check`, `lcars-cli` | unchanged (the tests' scratch builds read lcars-release's command line: it stays one `cc … -o lcars lcars.c …` line) |
| `lcars-portable` | dropped once `lcars-static` exists (it is the glibc-in-docker answer to the same question) |
| `lcars-one` (new) | the one binary, dynamic, the host's libs: `lcars.o` + `lcars_cli.o`, UI from disk. What the VPS could run later |
| `ui-pack` (new) | `scripts/ui-pack.py` → `build/ui.pack` |
| `lcars-static` (new) | `lcars-one` + `-DLCARS_EMBED_UI` + `-static`, in Alpine (CI, or `docker run alpine` locally; the VPS has no docker) |

### 5b. Tests

| Test | Change |
|---|---|
| `test/api.py` | no seed: a new journal stays empty, under `--data DIR` and `--db FILE` as well as the cwd |
| `test/onebin.py` (new, ~40s) | `serve`/`cli`/`init`/`version` and the argv[0] symlink; `init` idempotent (a second run changes no byte); `lcars.env` read and the environment winning; the start log's path; `--data` never touching the cwd |
| `test/uigzip.py` | a second pass against an embedded build: every shipped file byte-equal to the source, gzip, 304, index.html's Range, `LCARS_UI_DIR` winning |
| `test/chat_media.py`, `recording.py`, `reports.py` | rerun after the media-root default moves |
| CI | the release job's checks (§4) |
| `scripts/vps-rebuild.sh` | the entry-count guard (§2e) |

### 5c. The order — each step deploys on its own

| # | Step | Live effect | Deploys on | Size |
|---|---|---|---|---|
| 1 | Runtime db path: `LcarsDBPath()`, `--data`/`--db`/`LCARS_DATA_DIR`/`LCARS_DB_PATH`, the start log, `vps-rebuild.sh`'s count guard, test/api.py | none if right; an empty journal if wrong | **the captain's word**, watching the restart | 1 order, ~30 min |
| 2 | `lcars.env` read at start; `lcars init`; `lcars version` | none (no lcars.env in ~/lcars) | Number One | 1 order, ~30 min |
| 3 | One binary: `lcars cli`, argv[0] dispatch, `lcars-one`, test/onebin.py | none until the VPS switches (0.276.2: `vps-rebuild.sh` builds `lcars-one`, the server's own `bin/lcars-cli` link replaces the copied build; the steps are below the table) — **the captain's**, it retires build.sh | Number One; the switch the captain | 1 order, ~25 min |
| 4 | Embedded UI: `ui-pack`, `-DLCARS_EMBED_UI`, uigzip.py's second pass | none (the VPS build does not embed) | Number One | 1 order, ~40 min |
| 5 | musl: `SOCK_CLOEXEC`, `CHAT_HAVE_GNU` on musl, python3 from PATH, the CA probe; `lcars-static` | `SOCK_CLOEXEC` is a live change (harmless; test/chat_media.py) | Number One | 1 order, ~40 min, most of it CI round trips |
| 6 | Release workflow (§4), first tag here as the dry run | none | the captain (a tag publishes) | 1 order, ~30 min |
| 7 | Media root default → `$DATA/media` | **needs `LCARS_MEDIA_ROOT=<the mount>` in `~/.env` first**, or uploads land on the VPS disk | the captain's word, after he adds the line | a fix, ~10 min |

Steps 2–4 can follow in any order after 1; 5 needs 3 and 4; 6 needs 5.

**Step 3 on the VPS: the switch** (0.276.2). How `lcars-cli` reached its
users before it: nothing put it on PATH (no `~/.local/bin` link, no PATH
entry in `~/.profile` or `~/.zshrc`, nothing in `~/.env`); each user named
the copied build by its path, `~/lcars/lcars-cli/lcars-cli` -
`lcars_chat.h`'s `ChatCliDir` default (`~/lcars/lcars-cli`, put first on
the chat's PATH), `lcars_linker.py` and `lcars-link.sh` (the hourly cron
and the yeoman), `lcars-strava.service`, `db-slots.sh`, `crew_tool.py`,
`no1.py`, and the lcars skill's text (`~/.claude/skills/lcars/SKILL.md`,
outside the repo). The switch is **the argv[0] link the server makes
itself**: `vps-rebuild.sh` builds `make lcars-one` (the UI still from
`lcars-ui/` on disk) and swaps it in as `./lcars`; started by the unit in
`~/lcars` with no `--data`, it makes `~/lcars/bin/lcars-cli -> ~/lcars/lcars`
and sets `LCARS_CLI_DIR` to `~/lcars/bin` for the chat. No PATH entry, no
`~/.local/bin` link, no unit `Environment=` line and no `LCARS_CLI_DIR` in
`~/.env` (which would stop the link being made). Every script looks for
`~/lcars/bin/lcars-cli` first and the copied build second (until step 4), so the order is:

1. The deploy of 0.276.2 (it touches C, so it runs the new
   `vps-rebuild.sh`): the one binary is `./lcars`, the old `lcars-release`
   build `lcars.prev`; the start log has `CLI: ~/lcars/bin/lcars-cli
   -> ~/lcars/lcars`. From then on the chat, the linker,
   `crew_tool.py` and `no1.py` run it.
   (Its first try, as 0.275.1, left the one binary live with the old
   scripts: the rollback it attempted failed on "Text file busy". So the
   retry keeps that one binary as `lcars.prev`, and the 0.275.0 release
   build is no longer the way back - which is the state step 4 waits for.)
2. The Strava unit reinstalled from the repo (`scripts/crew.py unit
   lcars-strava.service > ~/.config/systemd/user/lcars-strava.service`,
   `systemctl --user daemon-reload`): its `ExecStart` looks in `bin/` first.
3. The skill's text pointed at `~/lcars/bin/lcars-cli`, its build.sh line
   dropped.
4. After the next deploy that rebuilds C (so `lcars.prev` is a one binary
   too, and a rollback cannot need the copy): `rm -r ~/lcars/lcars-cli`
   (`build.sh`, the copied sources, the vendored curl headers, `lcars-cli`,
   `lcars-cli.prev`), and a patch drops the scripts' fallback to it.
   Done in 0.279.2: `lcars_linker.py`, `lcars-link.sh`,
   `lcars-strava.service`, `db-slots.sh`, `crew_tool.py` and `no1.py` look
   only at `~/lcars/bin/lcars-cli` (and `$LCARS_CLI`; `crew_tool.py` and
   `no1.py` also a checkout's own `make lcars-cli`, then PATH).

A rollback to a binary without the CLI (`vps-rebuild.sh --rollback`, or
its own rollback after a failed restart) removes `bin/lcars-cli`, which
would otherwise answer every timer "no CLI in this build". With the copy
retired, the scripts then have no CLI until a one binary is back; since
`lcars.prev` became a one binary, no rollback leads there.
O'Brien's `/features` (his §2a) is a separate order and fits after 2.

## 6. What the captain decides

| Question | Recommendation |
|---|---|
| musl static (one file, ~15 MB) or a glibc build with a dependency list | musl static |
| arm64 in the first release | yes; it costs a matrix line |
| Step 1 and step 7 deploys | his word, each; the captain adds `LCARS_MEDIA_ROOT=<the mount>` to `~/.env` before 7 |
| The VPS running the one binary (retiring `~/lcars/lcars-cli/build.sh`) | done: switched in 0.276.2, the copy retired in 0.279.2 |
| A tag on this repo as the release dry run | yes, before the public repo exists |
