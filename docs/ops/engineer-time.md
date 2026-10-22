# Where an engineer's time goes, and what hardware is enough

Chief O'Brien, 2026-10-14, at deb `7ed5589` (0.184.0), on the VPS, with
Number One and one seated engineer (me) running, the live server serving.
Every stage was run on its own, one after another, against the synthetic
journal (`test/synth.py`, 4000 rows), while a sampler read `/proc` once a
second: CPU (`/proc/stat`), memory and swap (`/proc/meminfo`, `vmstat`),
disk (`/proc/diskstats`), and pressure stall (`/proc/pressure/*`, the
share of the wall time something was waiting on that resource). The
deploys' own timings are from `~/.local/state/lcars-eng/logs` (96 logs,
Oct 7-14). Nothing was deployed and `lcars.db` was not touched.

The box was resized the same evening to 4 vCPU / 8 GB; **"Measured on
4 vCPU / 8 GB"** below has the same stages measured again, and where
these estimates were wrong. Everything above it is the one-core box.

## The box (before the resize)

| | |
|---|---|
| CPU | **1 vCPU**, Intel Xeon (Cascade Lake), KVM. Steal 0% in every sample |
| RAM | **1.9 GiB**; 650-1000 MB available at rest |
| Swap | 975 MB, **440-760 MB in use** throughout (idle pages of the Claude Codes and llama-server) |
| Disk | 24 GB virtio, 75% used (5.7 GB free); 280 MB/s direct writes, 1.9 GB/s reads |
| `/tmp` | tmpfs (RAM-backed), 300 MB in use, ~156 MB of it test dirs left by killed runs |

What is resident beside the tests:

| process | RSS | CPU |
|---|---|---|
| Claude Code, the seated engineer | 270-350 MB (+40 MB swapped) | 7-27% while it writes, ~0 waiting |
| Claude Code, Number One | 265-325 MB (+50 MB swapped) | ~1.6% over 3 days |
| llama-server (the embedder, on demand, stops after 10 idle min) | **550 MB** awake, 136 MB of it swapped | woken by writes, e.g. a deploy's |
| alloy, node_exporter, tailscaled, journald, herdr, 2× fff-mcp | ~300 MB together | herdr ~1.5% |
| `lcars` (the live server) | 15-20 MB | ~0 |

At rest the box idles at 65-70%: a third of the one core goes to the two
Claude Codes and the agents beside them before any test starts.

## The stages, one at a time

`wall` in seconds; CPU as a share of the core over the stage; `avail` the
lowest MemAvailable seen; PSI the share of the wall time with a task
stalled on CPU / memory / IO.

| stage | wall | user | sys | iowait | idle | avail MB | swap in/out MB | PSI cpu/mem/io |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| javascript parses (extract + esbuild) | ~1 | 65 | 21 | 1 | 13 | 672 | 0/0 | 68/0/3 |
| structure (`check.py`) | ~1 | 54 | 6 | 0 | 40 | 657 | 0/0 | 13/0/0 |
| deck boot (`deckboot.js`, node) | 8 | 84 | 9 | 0 | 7 | 574 | 3/0 | 71/1/1 |
| static audit (`audit.py`) | ~1 | 58 | 13 | 0 | 29 | 672 | 0/0 | 59/0/0 |
| behaviour: `gen.py` (the bundle) | ~1 | 51 | 8 | 1 | 40 | 638 | 0/0 | 30/0/0 |
| behaviour: QuickJS (`qjs run.js`, 3531 assertions) | **67** | 94 | 6 | 0 | 0 | 392 | 0/67 | 51/1/0 |
| keyboard (`keyboard.py`, 1 shard) | **87** | 62 | 11 | 0 | 27 | 493 | 1/37 | 57/1/1 |
| perf (`perf.py`, all 16 + course-zoom's comparison) | **653** | 81 | 12 | 0 | 7 | 382 | 7/9 | 83/0/0 |
| **run.sh, PERF=0** (the deploy's suite) | **124** | 90 | 10 | 0 | 0 | 506 | 6/0 | 81/0/0 |
| **run.sh, full** | **997** | 81 | 12 | 0 | 7 | 432 | 7/21 | 82/0/0 |
| `offline.py` | 19 | 87 | 11 | 0 | 2 | 601 | 0/28 | 67/1/0 |
| `back.py` | 30 | 72 | 11 | 0 | 16 | 576 | 1/42 | 57/2/0 |
| `qa_chat.py` (failed its scroll-back check, below) | **246** | 65 | 11 | 0 | 23 | 492 | 35/63 | 56/0/0 |
| `buttons.py` | **361** | 66 | 10 | 0 | 24 | 689 | 160/0 | 63/0/1 |
| `make check` | ~1 | 50 | 14 | 2 | 34 | 876 | 0/0 | 35/0/5 |
| `make lcars` (ASan) | 5 | 78 | 15 | 1 | 7 | 784 | 0/0 | 59/0/2 |
| `make lcars-release` (-O3) | 11 | 88 | 6 | 0 | 7 | 786 | 0/0 | 50/0/0 |
| `make lcars-cli` | 4 | 82 | 6 | 0 | 12 | 844 | 0/0 | 42/0/0 |

(The sampler's resolution is one second; "~1" is under it.)

Inside those: a Chromium starts in 0.2-0.5 s (it is cached under
`~/.cache/ms-playwright`, 1.3 GB), and a 4000-row page boots to loaded in
3.6-5.2 s (1.3-1.8 s with 1000 rows). A perf scenario is ~26-33 s on this
box: launch, boot, a second's settle, then 10-20 s of driving that runs in
real time (a finger's speed, frame by frame), then the trace. QuickJS
peaks at 327 MB. A Chromium with its Playwright driver is ~500-600 MB
across its processes.

The full run's perf stage was 870 s of its 997: 16 scenarios, then
scroll-desktop, course-zoom and eng-thread over the line once, so each ran
3 more times on the page and 3 times on deb's (34 runs, not 16). The
standalone perf run had only course-zoom over (22 runs, 653 s). **Half of
perf's time can be the comparison runs**, and how many there are is luck:
scroll-up, scroll-desktop and eng-thread sit at 14-17 ms, either side of
the 16.7 ms line.

### Deploys (from the logs)

There is no `scripts/deploy.sh`: the deploy is `engineer.py deploy`
(`cmd_deploy`/`do_deploy`/`web_suite`/`land_commits`). Its steps: wait for
the engineer's turn to end, pull deb into `~/lcars`, rebase the branch,
`run.sh` with `PERF=0` against the live journal **only if a file under
`lcars-ui/` changed**, fast-forward `~/lcars`, `vps-rebuild.sh` if C
changed (an 11 s -O3 build, a swap and a restart, healthy in ~2 s), push.
The logs have no per-step times; total = the log's mtime less its name.

| deploys | n | median | range |
|---|---:|---:|---|
| with the web suite, no C | 48 | **105 s** | 83-175 |
| with the web suite and a rebuild | 13 | 124 s | 104-229 |
| no `lcars-ui/` change (no suite) | 2 | 4 s | |
| waited for the engineer's turn first | 18 | 43 s | 6-267 |
| failed | 29 | 9 s | 0-577 |

The suite is ~90-100 s of a deploy; the rest is git and the push. Of the
29 failures, 12 were the suite (behaviour checks where the log says,
often against the live journal's rows; one perf, from when deploys ran
it), 11 rebase conflicts (CHANGELOG.md and index.html, every engineer bumping the same lines), 2 an
engineer still working.

## Findings

- **Everything is CPU-bound.** iowait is 0-2% and steal 0% in every
  stage; IO pressure under 5%. The disk does not matter.
- **Memory is tight but not the bottleneck.** Memory pressure stalls were
  0-5% of any stage; available memory never fell below 270 MB. Swap holds
  ~500 MB of idle pages (the Claude Codes', llama-server's) and pages them
  back in when they wake (`buttons.py` read 160 MB back), which costs
  little now and would cost more with a second engineer.
- **The browser stages wait as much as they work**: keyboard, buttons,
  qa_chat and back are 16-30% idle. That is fixed `wait()`s and real-time
  animations, not IO or a browser start: Chromium starts in under half a
  second. Two keyboard shards fill the gap (85 s → 55 s alone, 3 shards
  51 s with available memory down to 270 MB), but inside run.sh keyboard
  already runs beside QuickJS and the block is at 0% idle, so there it
  gains nothing.
- **QuickJS is the floor of the pre-perf block**: 65 s of one thread.
  Nothing on one core shortens it; sections in parallel processes would on
  more cores.
- **The full run.sh is 16.6 minutes here**, of which perf is 11-14.
  `PERF=0` is 2 minutes. No single tool call fits the full run.
- **course-zoom over budget is the code, not the box.** perf judges
  main-thread *CPU* time, which other processes do not add to. Measured:
  course-zoom p99 18.4 / 18.2 / 19.4 ms with the box as it is, and
  18.0 / 17.7 / 16.8 ms with a busy loop competing for the core the whole
  time (its wall time went from 66 s to 91 s, its p99 did not move). It is
  over on deb by the same amount (deb 18.2-20.0 ms in the comparisons).
  TODO.md has the cause: Leaflet's own zoom, ~12 ms plus ~0.06 ms a
  marker, 53 markers here. scroll-up behaved the same way (14.0-18.6 ms
  either way): noise in the code's own cost, not the neighbours.
- **qa_chat's engineer scroll-back flake is the box**: nine drags 700 ms
  apart, each paging in 20 events through the fake fetch and a render, ran
  out before both earlier conversations were reached when the core was
  shared (it failed in the timed run above). It now drags until both are
  reached, at most 24 (4 of 4 green, 43-46 s for `--only engineer`).
- **The static audit's verdict was ignored**: run.sh piped `audit.py`
  through `tail -1`, whose exit status is the pipe's, so a failing audit
  printed "1 failed" and passed. One check had been failing since 0.183.5
  (it read the first `@media (max-width:820px)` block, which became a
  one-line rule). Both fixed.
- **Test leftovers in RAM**: `/tmp` is tmpfs, and runs killed by the tool
  timeout leave their temp dirs: 21 perf baseline pages (`lcars-perf-base-*`,
  108 MB), 36 `lcars-seat-test-*`, 30 `lcars-model-test-*`, ~156 MB of a
  1.9 GB box.

## Hardware: the recommendation

The work is CPU, single-threaded where it cannot be split (QuickJS) and
parallel where it can (perf runs `cores/2` scenarios at once, at most 4;
keyboard `min(6, cores)` shards). Estimates from the measurements above,
not measured on such a box (the box got 4 vCPU / 8 GB / 1 GB swap; the
next section measures it):

| | one seated engineer + server + Number One | two engineers at once |
|---|---|---|
| vCPU | **4** | **8** |
| RAM | **4 GB** (8 GB if the price step is small) | **8 GB** |
| swap | 2 GB | 4 GB |
| disk | 40 GB (24 GB is 75% full now) | 60 GB |
| full run.sh | ~5-6 min (pre-perf ~70 s, bound by QuickJS; perf 2 at a time, ~22 runs × ~25 s / 2 ≈ 4.5 min) | the same each, if both do not run perf at once; ~8-10 min if they do |
| PERF=0 / a deploy's suite | ~70-80 s | |

Why these: on 4 vCPU the Claude Codes and the server stop taking a third
of the test's core, perf runs two scenarios at once by its own rule, and
keyboard runs 4 shards beside QuickJS on its own core. 2 vCPU is not
enough: perf would still run one scenario at a time (`cores/2` = 1), which
is ~9-10 minutes on its own. 4 GB holds the two Claude Codes (~700 MB),
llama-server awake (550 MB), the services (~300 MB), two Chromiums for
perf (~1.2 GB) and QuickJS (330 MB) without swapping a working set; 8 GB
leaves room for the page cache and a second engineer's Claude Code. A
second engineer at once needs its own 4 cores for its own test runs, so
8 vCPU / 8 GB; less than that makes the two queue for the core, which is
what the seat does now anyway. The disk is a matter of space, not speed.

## What a change must run (implemented: `run.sh --changed`)

`test/changed.py` reads this branch's change against its merge-base with
deb (committed, staged, unstaged and untracked), and for `index.html`
finds the top-level section each hunk falls in (a `/* ===== name` header
in the script, `/* ----- name` in the style; the markup and `<head>` are
their own). `run.sh --changed` runs what it picks; `run.sh` with no
argument is the full run, unchanged, and is what a deploy runs.

| the change touches | runs | skips | says to run by hand |
|---|---|---|---|
| docs, CHANGELOG, TODO only | parse, structure, version (~3 s) | everything slow | |
| `scripts/` only | the same | everything slow | the `scripts/test_*.py` for that script |
| C only | the same | everything slow | `make check`, `make lcars-cli`, the module's functional test (framing/logins for `lcars_http.h`, caldav, transcribe, metrics, recording) |
| `deck.html`, `deckboot.js`, `crew/` | + deck (~10 s) | | |
| `sw.js` | parse | | `offline.py` |
| `index.html`, an area no perf scenario measures (calendar, stats, task board, series, crew reports, link graph, speech queue...) | + audit, behaviour, keyboard (~2 min) | perf | `dates.sh` for the calendar, `speech.py`, ... |
| `index.html`, a measured area | + perf for its scenarios only: the course → course-zoom, course-turn; the chats → chat-thread, eng-thread; the engineers → eng-thread; the editor → open, type; the list → scroll, scroll-up, scroll-desktop, rail, search, open; the star chart → stars-*; the palette → palette | the other scenarios | `editor.py`, `qa_chat.py`, `back.py`, `offline.py`, `buttons.py` by area |
| `index.html` shared code (constants, state, helpers, load, api, kinds, pages, wiring, the markup, header/layout/phone CSS) | everything, all of perf | | |
| a test file | its own stage (`tests.js`/`shim.js`/`api.js`/`gen.py` → behaviour, `keyboard.py`, `audit.py`, `perf.py`/`synth.py` → all of perf) | the rest | a check outside run.sh (`qa_chat.py`, `buttons.py`...): itself |
| `run.sh`, `changed.py`, `test_changed.py`, `esbuild`, `qjs`, an unknown UI file | the full run | | |

A hunk that only changes `APP_VERSION` is not counted (every commit has
one). The map from sections to perf scenarios is kept by hand in
`changed.py`; a section it does not know runs all of perf and says so.
**Perf runs only when a measured view's code moved.** Measured on sample
changes in a scratch clone: docs only 3 s; a calendar line 118 s; an
engineers line 133 s (perf: eng-thread only); against 997 s for the full
run. `test/test_changed.py` (in every run, ~1 s) checks the picks on 24
sample changes and on a scratch git repo.

**The full run is still required** before reporting a page change done,
whenever the change reaches shared code (`--changed` then runs it anyway),
and on every deploy.

## Proposals

The captain approved the /tmp sweep, perf's comparison reuse and the
scoped deploy suite on 2026-10-14; each is marked with the version it
landed in.

| proposal | saving | note |
|---|---|---|
| **Done 2026-10-14**: the hardware above, 4 vCPU / 8 GB | full run 16.6 min → 132 s measured (estimate ~5-6 min) | the full run is well inside the 10-minute tool limit |
| **Done in 0.184.5.** perf doesn't rerun a scenario over budget that the change cannot reach (changed.py's map), and keeps deb's comparison numbers per baseline tree (with perf.py, rows, Chromium, cores, host; 7 days) instead of rerunning deb's page each time; `--fresh` measures both | measured: course-zoom over budget, unreached 58 s against ~4 min; reached with deb's numbers kept 3.5 min against 6.2 | the judging rule stays: a scenario the change reaches is still rerun and judged; only deb's side is reused, and said with its age |
| course-zoom: the markers to one canvas layer, or hide them during the zoom animation (TODO.md) | ~3 min of every full run (its comparison runs), and it is a real dropped frame on phones | code, not test |
| scroll-up / scroll-desktop / eng-thread sit at 14-17 ms; bringing them under ~14 would stop the random comparison runs | 0-9 min a run, ~3 min typical | code (TODO.md has scroll-up) |
| **Done in 0.184.6.** The deploy's suite chooses stages with `changed.py --base <live branch>` (`web_suite`, `suite_scope`): a page deploy (index.html beyond its APP_VERSION) runs the full PERF=0 suite as before; a deck-only, test-only or docs-under-`lcars-ui/` deploy runs `run.sh --changed`, skipping QuickJS and keyboard; the deploy log's step line names the stages and why; anything changed.py cannot read is the full suite | ~90 s on those deploys; nothing on page deploys, which stay full | `scripts/test_deploy_suite.py` |
| QuickJS: its sections in parallel processes | 40 s → ~15 s on 4 cores (measured 40 s alone now) | now the floor of PERF=0 and the deploy's suite (TODO.md) |
| **Done in 0.184.4.** The tests remove their temp dirs on SIGTERM/SIGHUP too (`lcars-ui/test/killclean.py` for the Chromium and server tests, the same in test_seat/test_engineer_model, which also never removed theirs at a normal exit; run.sh traps TERM/HUP, and names its dir `lcars-run.*`), and `engineer.py reap` (every 5 min) deletes test scratch untouched for 24 h under /tmp and ~/.cache (`reap_test_tmp`; a SIGKILL's leftovers) | ~150 MB of RAM back now, and on every killed run | `scripts/test_reap.py` covers the sweep and the kills |
| `KB_JOBS=2` when running keyboard.py alone on one core | 85 → 55 s alone; nothing inside run.sh | already an env var |
| a smaller synthetic journal for perf | ~3 s a scenario, ~1.5 min a run | **not recommended**: perf's point is a journal the real one's size |
| a cached Chromium | none | already cached; it starts in 0.2-0.5 s |
| CHANGELOG/APP_VERSION conflicts (11 of 29 failed deploys) | a round trip each | out of this task's scope: e.g. the deploy bumping the version itself |

## Measured on 4 vCPU / 8 GB

Chief O'Brien, 2026-10-14 evening, at deb `37981bf` (0.186.2), after the
captain resized the VPS: **4 vCPU** (the same Xeon Cascade Lake, KVM),
**7.9 GiB** RAM, **975 MB** swap, a 102 GB disk (17% used), `/tmp` a
3.9 GB tmpfs. Same method as above: each stage on its own against the
synthetic journal (4000 rows), sampled once a second by a script reading
`/proc/stat`, `/proc/meminfo`, `/proc/vmstat` and `/proc/pressure/*`, and
counting the Chromiums alive at once (their main processes). CPU is a share
of all four cores now: 25% is one core busy. Number One and one seated
engineer (me) ran beside it, and the live server; nothing else seated.
At rest MemAvailable was **6.7 GB**, swap 0 in use.

| stage | wall | was (1 vCPU) | user | sys | idle | avail MB | swap in/out MB | PSI cpu/mem/io | Chromiums at once |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| deck boot | 3 | 8 | 31 | 3 | 64 | 6691 | 0/0 | 1/0/0 | |
| behaviour: QuickJS (3612 assertions) | **40** | 67 | 31 | 2 | 66 | 5925 | 0/0 | 0/0/0 | |
| keyboard (default: 4 shards) | **22** | 87 (1 shard) | 34 | 6 | 58 | 5115 | 0/0 | 13/0/0 | **4** |
| keyboard, `KB_JOBS=1` | 75 | 87 | 10 | 2 | 87 | 6005 | 0/0 | 0/0/0 | 1 |
| perf (default: 2 at once; eng-thread over once, unreached) | **89** | 653 | 44 | 7 | 48 | 5311 | 0/0 | 16/0/0 | **2** |
| perf `--fresh` (none over) | 90 | | 43 | 6 | 49 | 5161 | 0/0 | 16/0/0 | 2 |
| perf `--compare --fresh` scroll-desktop, course-zoom, eng-thread (3 + 18 comparison runs) | 168 | | 47 | 6 | 45 | 4730 | 0/0 | 20/0/0 | 2 |
| **run.sh, full** | **132** | 997 | 44 | 6 | 49 | **4770** | 0/0 | 15/0/0 | 4 |
| **run.sh, PERF=0** | **42** | 124 | 47 | 5 | 46 | 4736 | 0/0 | 15/0/0 | 4 |
| run.sh PERF=0 against the live journal (the deploy's suite, read-only) | **40** | ~90-100 in a deploy | 47 | 4 | 47 | 4711 | 0/0 | 15/0/0 | 4 |
| run.sh `--changed`, a docs/scripts-only change | **1** | 3 | 33 | 6 | 60 | 6210 | 0/0 | 2/0/0 | 0 |
| `offline.py` | 9 | 19 | 29 | 4 | 65 | 5874 | 0/0 | 2/0/0 | 1 |
| `back.py` | 21 | 30 | 19 | 3 | 76 | 5869 | 0/0 | 1/0/0 | 1 |
| `qa_chat.py` (243 checks, green) | 179 | 246 | 14 | 2 | 82 | 5544 | 0/0 | 1/0/0 | 1 |
| `buttons.py` (192 checks, green) | 295 | 361 | 15 | 2 | 82 | 5786 | 0/0 | 1/0/0 | 1 |
| `make check` | ~0.5 | ~1 | | | | | | | |
| `make lcars` (ASan) | 2 | 5 | | | | | | | |
| `make lcars-release` (-O3) | 6 | 11 | | | | | | | |
| `make lcars-cli` | 2 | 4 | | | | | | | |
| **two full run.sh at once** (this worktree and a scratch clone) | **153 / 163** | | 70 | 9 | 20 | **3027** | 0/0 | 43/0/0 | 8 |

Every run above was green. The parallel rules hold: perf ran **2**
scenarios at once (`cores/2`) and keyboard **4** shards (`min(6, cores)`),
counted, not read from the code.

**Where the estimate was wrong:**

- **The full run is 132 s, not ~5-6 min.** The estimate scaled the one
  core's per-scenario time (~25 s) and assumed ~22 perf runs. Both were
  too high: a scenario's own CPU cost fell, and with nothing over budget
  that the change reaches, perf ran only its 16. With three scenarios
  compared against deb (the study's worst full run) it is ~4.5 min
  (132 + ~150 s), which is where the estimate's ~5-6 lands.
- **PERF=0 is 42 s, not ~70-80.** The estimate took QuickJS's 65 s on one
  core as the floor; on its own core it is 40 s, and it is still the floor:
  keyboard (22 s) and the deck (3 s) finish under it.
- **"Main-thread CPU time does not depend on the box" was wrong.** The
  one-core study found a busy loop beside course-zoom did not move its p99,
  and concluded course-zoom's 18-20 ms was the code. On four cores the same
  page measures 12-15 ms (deb 12.8-14.4 ms in the comparison above), under
  budget: Chromium's own rasterizer, GPU process and driver, sharing the one
  core with the main thread, cost the main thread 20-30% in preemption and
  cold caches, which a busy loop at a lower share did not add to. scroll-up
  (12.2 ms) and eng-thread (13.6 ms median) moved the same way;
  scroll-desktop (15.4-18.0 ms) still sits on the line. The Leaflet cost in
  TODO.md is real (it is a phone's frame too), but no longer fails runs here.
- **Memory was over-estimated as a need and under-estimated as a gift.** The
  full run takes ~2 GB at its lowest point (6.7 → 4.7 GB available), not the
  ~1.5 GB summed from its parts; and with 8 GB nothing touched swap in any
  stage, against 440-760 MB swapped at rest before.
- The deploy's suite should now be ~40 s of a deploy instead of ~90-100 s;
  measured as a run, not yet from a deploy's log.

The Chromium checks outside run.sh (`qa_chat`, `buttons`, `back`) are
75-82% idle: they run one Chromium at a time through fixed waits and
real-time animations, so the cores barely help them (buttons 361 → 295 s).
Sharding them as keyboard is would be the next saving.

**What was retuned for it (0.186.3):**

| rule | was | now | why |
|---|---|---|---|
| `LCARS_ENG_MIN_FREE_MB` (an engineer's start) | 500 | 2500 | a Claude Code (~400 MB) and its full run (~2 GB), measured |
| `lcars-crew@.service` MemoryHigh / MemoryMax | 600M / 800M | 1G / 1500M | the qa suite peaked at 540 MB, just under the old MemoryHigh |
| crew.py default `min_free_mb`, qa's | 450, 400 | 1000, 1000 | the unit's MemoryHigh: a run starts only into room to grow to it |
| the seat's, crew.py's, reap's, the briefs' reasons | "2GB and one core", "memory for one" | the cores for one session's tests | memory is no longer what limits the seat |
| CLAUDE.md, run.sh, perf.py | "past one tool call's 10 minutes", one at a time | the measured times | |

Not changed: the global crew lock and the one seat (Number One's order);
llama-server's `-t 1` (it is Nice 19 background indexing; `-t 2` would
index faster at the tests' expense); C comments that cite the one core
(`lcars_http.h`'s gzip level, `lcars_media.h`'s no re-encode), whose
choices still hold on four.

### Swap: 1 GB, against the 2 GB asked

It does not matter at 8 GB. No stage swapped a page in or out, the
two-runs-at-once test included (3.0 GB still available at its lowest), and
swap stayed at 0 MB in use throughout. Swap was holding ~500 MB before only
because 1.9 GB could not keep two Claude Codes and llama-server resident.
1 GB is enough for what it is for now: room for idle pages before the OOM
killer. It would matter again with three or more engineers at once.

### A second seat: feasible on 4 vCPU / 8 GB

Measured, not estimated: two full run.sh at once took **153 and 163 s**
each, against 132 s alone (+16-23%), with 20% of the cores still idle and
3.0 GB available at the lowest. A second engineer adds its Claude Code
(~400 MB), so ~2.6 GB would be left with both running full suites: enough,
without swap. The study's "two needs 8 vCPU" was wrong for the same reason
as the 5-6 minutes: the stages are smaller here than one core made them.

What it would cost:

- **Run times**: a full run ~2.5-3 min instead of 2.2 while both test;
  PERF=0 ~50 s; with comparisons (a page change reaching an over-budget
  scenario) ~5-6 min. Most of the time only one is testing, at full speed.
- **Perf noise**: with both running perf, scroll-up came out over budget
  (16.7 and 19.2 ms, against 12.2 alone) in both runs: CPU contention does
  raise main-thread time. Unreached it is not judged; reached, it costs
  comparison runs, and a borderline verdict gets less reliable. A perf
  stage that waits for the other's to finish (a flock in perf.py) would
  remove that, for ~90 s of waiting at most.
- **Deploys**: a deploy's suite (~40 s) beside an engineer's full run is
  the same contention; the deploy already runs one at a time.
- **Rebase conflicts**: two engineers landing at once is more of the
  CHANGELOG/APP_VERSION conflicts that were 11 of 29 failed deploys.

(Since 0.286.1 the job line, docs/design/job-queue.md, is the answer
taken instead: one heavy run on the cores at a time, the seat passing on
while it runs; an engineer's heavy commands go through `engineer.py job`.)

Recommendation: a second seat is now feasible, at about a fifth longer
test runs while both test; it is the captain's decision (TODO.md). If it
is taken, take it with perf serialised across seats, and keep
`LCARS_ENG_MIN_FREE_MB` at 2500 as the guard for a third.

(2026-10-22: the hour measured again for an adaptive seat and job line,
with more engineers and the explainer and deckshots in the line, is in
docs/design/job-queue.md, "More than one".)
