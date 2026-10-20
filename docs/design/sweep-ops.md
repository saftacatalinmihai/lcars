# Simplification sweep: the scripts and the working documents

Status: **done** (2026-10-13, Chief O'Brien). Round 1 (0.174.1) made the
deletion-only cuts listed at the end; the captain approved the rest, built
in 0.174.2-0.174.11 (see "Outcome", last). The ranking below is the survey
as it was.

What was looked at: `scripts/*.py`, `scripts/*.sh`, `crew/*.md`, the hooks
(`crew_settings`/`no1_settings` in `engineer.py`), CLAUDE.md, AGENTS.md,
TODO.md, ARCHITECTURE.md's ops sections, `docs/`. Sizes today: `engineer.py`
3372 lines, `crew_tool.py` 832, `crew.py` 807, `lcars_linker.py` 683,
`seat.py` 410, `no1.py` 286; the script tests 2343.

What was **not** found: no dead functions (every `def` in `scripts/` has a
caller outside the tests) and no dead verbs (every `engineer.py` verb is
called by the server, a hook, a unit or another verb). Every saving below
comes from removing a feature nobody uses any more, or from folding copies
into one.

## Ranked: lines saved per unit of risk

Risk is low (a path nobody runs, or a pure refactor the tests cover),
medium (a path in use, partly covered) or high. **Captain** marks what
round 1 was told to leave alone: the seat, the deploy path, the hooks,
Number One's powers.

| # | What | Saves | Risk | Captain |
|---|------|------:|------|:-:|
| 1 | Satellites (engineers on the laptop) | ~550 | low | yes |
| 2 | The laptop's ops scripts | ~170 | low | yes |
| 3 | `metrics-backfill.py`, if the history is given up | 234 | none | yes |
| 4 | `main()` as a table | ~50 | low | |
| 5 | One HTTP/env helper for crew_tool and no1; no `no1.env` | ~50 | low | |
| 6 | Number One's refresh as a clear with a handover | ~120 | medium | yes |
| 7 | One `spawn()` for the detached children | ~25 | low | yes |
| 8 | The hooks' "started by an older engineer.py" shims | ~25 | low | yes |
| 9 | Number One's inbox file into the journal | ~60 | medium | yes |
| 10 | crew.py's laptop knobs (`LCARS_SEAT`, `LCARS_CLAUDE_BIN`) | ~10 | low | yes |
| 11 | CLAUDE.md "Where production is" | ~6 | none | with 2 |

### 1. Satellites: engineers on another machine (~550 lines, low)

**Today.** `engineer.py` lets engineers live on the laptop, with production
proxying every verb over ssh. That takes 18 functions, 405 lines:
`remotes`, `satellite`, `remember_prod`, `host_of`, `remote_call`, `proxy`,
`ssh_entry`, `strip_prod_flags`, `prod_ssh`, `brief_satellite` (78),
`do_deploy_satellite`, `land_commits`, `sync_live`, `sync_satellites`,
`cmd_land`, `cmd_home`, `where_to_start`, `no1_env_here`. On top of that come
56 `satellite()`/`host_of()` branches spread through start, say, list,
reap, rollback and the seat; the `--ssh` entry with `SSH_VERBS`; the
"Satellites" block of the module docstring; `no1.py`'s `satellite_only`;
seat.py's laptop paragraph; ARCHITECTURE.md's three satellite bullets and
`home` (~40 lines); and the state files `remotes.json` and `satellite.json`.

**Now.** All 20 engineer records in `~/.local/state/lcars-eng` have no
`host`, so everyone is on the VPS. But `remotes.json` still names the
laptop as `default`, so **every new engineer's start still tries the laptop
over ssh first** (`where_to_start`: up to 6s to connect, 20s budget). If the
laptop ever answers, the new engineer starts *there*. Deleting this is the
biggest cut and also removes that surprise.

**Replaces it.** Nothing. `host_of` and `satellite` go, and so does every branch
that tests them. `cmd_land` goes too, and with it the deploy's second
half on production.

**Tests.** Almost none: `test_seat.py` has one `satellite` mock, and the
satellite deploy only ever ran against scratch repos. That is why the risk
is low but not none: what goes was never tested, and what stays (start,
say, deploy, rollback) is covered by `test_seat`, `test_engineer_model`,
`test_no1_inbox` and a real deploy. It touches the deploy path and Number
One's start rule, hence the captain's call. **Decide:** are laptop engineers
gone for good? If yes, delete `remotes.json` on the box as well.

### 2. The laptop's ops scripts (~170 lines, low)

**Today.** `deploy.sh` (119; builds in a Debian 12 container on the laptop
and ships to the VPS), `db-push.sh` (24), `db-pull.sh` (23),
`copy_remote_to_local.sh` (1), and `tailscale_up.sh` (5, a note whose
command is misspelt `tailscale loging`, so it would fail). Engineers deploy
only through `engineer.py deploy`, which uses `vps-rebuild.sh` on the box.

**Replaces it.** Nothing, if the captain no longer deploys or moves the
database from the laptop. CLAUDE.md's danger-zone line and "From the
laptop, `scripts/deploy.sh`…" go with them (item 11). These are the
captain's own tools, and they are danger zones, so only on the captain's word.

### 3. `metrics-backfill.py` (234 lines, no risk)

**Today.** A one-off that sends the readings' history to Grafana Cloud. It
has waited since 0.170.0 on Grafana support widening the out-of-order
window (TODO.md, Grafana). **Decide:** keep waiting, or drop the history
and delete the script with its TODO sentence.

### 4. `main()` as a table (~50 lines, low)

**Today.** `main()` is 128 lines of `if verb == …` with per-verb argument
picking (`rest[1] if len(rest) > 1 else ""`, 15 times). **Replaces it.** A
dict from verb to `(function, needs-a-name, arity)`. argparse is the wrong
tool here: every verb prints one JSON object and uses fixed exit codes
(0/2/3), and argparse prints usage text and exits 2. Shrinks further after
item 1, since the proxy branch goes. **Tests:** every script test goes
through `main`.

### 5. One HTTP/env helper; no `no1.env` (~50 lines, low)

**Today.** `crew_tool.py:http` and `no1.py:http` are the same 15 lines,
with one difference that is a bug: no1's sends `json.dumps(body)` with
`ensure_ascii` on, so a "·" from Number One reaches the server as the
letters `u00b7`. crew_tool's comment records exactly this. There are two env
readers (`crew_tool.read_env`, no1's loop over `no1.env`) and two copies
of `mem_available_mb` (`engineer.py`, `crew.py`). `no1.env` copies
`LCARS_NO1_USER/PASS` out of `~/.env`. It exists because Number One once
lived on the laptop (`no1_env_here` makes it on the VPS).

**Replaces it.** `no1.py` uses `crew_tool.http` with its own pair, read from
`~/.env` the way crew_tool reads the crew's. `no1.env` and `no1_env_here`
go. **Tests:** `test_no1`, `test_crew`. This also fixes the escaping bug,
so check the captain's view of a Number One entry with a "·" in it.

### 6. Number One's refresh as a clear with a handover (~120 lines, medium)

**Today.** `refresh` (146 lines: `refresh_text`, `cmd_refresh`,
`refresh_seen`, `refresh_off`, `refresh_try`, `cmd_refresh_wait`, the
`refresh-go`/`refresh-wait` verbs, `number-one.refresh.lock`). Number One
is asked for a handover note, a Stop hook or a 15-minute watchdog checks
that a turn ran `no1.py log`, then it is cleared and told to read the log
back. **Replaces it.** Since 0.173.0 the context gauge already tells Number
One at 200k to write a handover. What remains is "clear, then give it its
log", which is `clear_session` plus `say --fresh` (the seat's path). The
token, the transcript scan and the watchdog go. **Tests:** none today
(TODO: only tried against a stubbed herdr). These are Number One's powers.

### 7. One `spawn()` for the detached children (~25 lines, low)

**Today.** Nine copies of `subprocess.Popen([sys.executable, __file__,
verb, …], stdin/stdout/stderr=DEVNULL, start_new_session=True,
close_fds=True)` and three `systemd-run --user --collect` calls.
**Replaces it.** `spawn(verb, *args, inp=None)`, always through
`systemd-run`. That also closes TODO.md's "detached children can die with
a unit" in one place. **Tests:** `test_no1_inbox` (its flusher outliving
the unit), `test_seat`. It touches the hooks and the seat.

### 8. The hooks' compatibility shims (~25 lines, low)

**Today.** `cmd_say` reads the engineer's settings file to report
`hooks`, and `no1.py` warns when an engineer "has no reporting hooks
(started by an older engineer.py)". The refresh watchdog covers "a session
started before it had" a Stop hook. Six records have no settings file
(esposito-c28, geordy-2py, moreau-c19, moreau-c29, pruner, swift). All are
old and off, and any start writes the file. **Replaces it.** A start always
writes settings, so the check and the warning go. Dismiss or delete those six
records first.

### 9. Number One's inbox into the journal (~60 lines, medium)

**Today.** `no1-inbox.json` with `.lock` and `.flush`, plus
`no1-answers.json` (160 lines in `engineer.py`; `test_no1_inbox.py` 143).
This breaks CLAUDE.md's rule that state lives in the journal, and TODO.md's
refactoring item already names it. **Replaces it.** `crew_inbox`-style
entries through `seat.py`'s journal block, which already does compare,
write and tick. Saves less than it looks, because the once-only delivery is
the hard part and stays. Number One's powers.

### 10. crew.py's laptop knobs (~10 lines, low)

`LCARS_SEAT=1` ("the laptop has no seat") and `LCARS_CLAUDE_BIN` ("the
laptop sets it") exist only for running the crew on the laptop. With item 1
the seat is always on here. `test_crew` patches `CLAUDE_BIN` itself, not
the variable, so both can go. Touches the seat.

### 11. CLAUDE.md (~6 lines, none)

"From the laptop, `scripts/deploy.sh` builds in a Debian 12 container…"
goes with item 2. "`git pull` before starting and push when done, or the
checkouts drift" is not true for engineers: the seat moves a clean branch to deb,
and the deploy rebases and pushes. Say that instead. The rest of
CLAUDE.md matches the scripts: every test it names exists, and so does
every environment knob it names.

## Also seen, not ranked

- **ARCHITECTURE.md** is 2114 lines. Its engineer section (605-808) shrinks
  by ~40 with item 1. The rest is outside this sweep.
- **TODO.md** "Plot a course" is a 50-line record of observations, not a
  to-do list. It could be cut to the four things not built, with the rest
  moved to ARCHITECTURE.md's course section.
- **The state directory** holds 20 engineer records, most of them
  long-dismissed. They cost nothing but `list`'s time, so it is not code.
- `lcars_linker.py`'s env overrides for "a scratch run on a laptop" are what
  its tests use. Keep them.

## Round 1 (0.174.1): the deletion-only cuts

- **TODO.md** (-54 lines). Removed what is done: the crew login (it is on,
  and the crew roles are built), the VPS on 127.0.0.1 (it listens there now;
  what is left is the clients outside the repo), the `LCARS_MAPY_KEY` step
  (set), Grafana's "scraped once deployed" (it is), the crew install steps
  and the Counselor's install (every role's timer is on), Number One's
  set-up steps (Number One runs on the VPS), and "an earlier conversation is
  reachable only by `/resume`" (0.162.0 built Earlier conversations).
  Removed what is dead: "Engineers on the laptop" (nobody is there; item
  1), and the satellite sentences in Number One's and the session names'
  items.
- **docs/**: `design/chat-refactor.md` and `qa/chat.md` are marked
  history in one line each (`design/chat.md` already says built). Every stage is built
  (0.156.0-0.172.0), and TODO.md references them, so they are kept.
- No code changed: there was no dead function or verb to delete.

## Outcome (0.174.2-0.174.11)

One commit per item. Lines are each commit's own diff, tests and docs included.

| # | Version | +/- | What it became |
|---|---------|-----|----------------|
| 4 | 0.174.2 | +98 -95 | `VERBS`: verb -> (function, needs a name, arity). Small on its own: most of `main()` was the proxy, which went with item 1. Extra arguments are now refused (exit 2) |
| 5 | 0.174.3 | +54 -86 | `crew_tool.http(login=)`, `NO1_LOGIN` from `~/.env`, one `mem_available_mb`; no `no1.env`, no `no1_env_here`. Fixed Number One's `\u` escapes |
| 1 | 0.174.4 | +101 -648 | Satellites gone from engineer.py, no1.py, seat.py, ARCHITECTURE.md and the page's engineer row; `remotes.json` deleted on the box |
| 2, 11 | 0.174.5 | +35 -162 | `deploy.sh`, `tailscale_up.sh`, `copy_remote_to_local.sh` gone; CLAUDE.md's laptop paragraph rewritten. `make lcars-portable` kept |
| 3 | 0.174.6 | +14 -240 | `metrics-backfill.py` gone; TODO.md and `lcars_metrics.h`'s comment say the history stays out |
| 6 | 0.174.7 | +152 -138 | `log "Handover"` marks a refresh, his Stop hook clears; no token, transcript scan or watchdog. engineer.py -66; the rest is new tests (none existed) |
| 7 | 0.174.8 | +60 -81 | `spawn()`: every detached child in a user unit of its own (closed a TODO bug); `notify-no1` verb gone |
| 8 | 0.174.9 | +20 -21 | `hooks` answer and its warning gone; `mcp.json` no longer listed as an engineer |
| 9 | 0.174.10 | +161 -66 | Number One's notes are `crew_inbox` entries; `no1-send` covers a journal restart. **Adds** lines: the restart retry and a test suite against a stand-in server |
| 10 | 0.174.11 | +30 -18 | `LCARS_SEAT` and `LCARS_CLAUDE_BIN` gone from crew.py; test_crew sets `LCARS_ENG_SEAT=0` |

After the deploy, on the box: delete `no1.env`, `no1-inbox.json` and its
`.lock`/`.flush` from `~/.local/state/lcars-eng`; nothing reads them now.

