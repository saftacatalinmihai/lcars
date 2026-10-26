# The job queue: a heavy job is a yield point

Chief O'Brien, 2026-10-21, at main `b867a45` (0.285.0). The captain's
order through Number One ("make it so"): an engineer who starts a long job
(tests, builds, deckshots) stops and waits while another takes the seat,
and the job's result brings them back. Like a process blocking on I/O: one
Claude Code awake at a time, one heavy job on the cores at a time, the two
overlapping. Design only; nothing built until the captain has read it.
Marked **[captain]**: the three rules that are his to settle.

## Why

`docs/ops/engineer-time.md`: a full `run.sh` is 132 s, `PERF=0` 42 s,
`buttons.py` 295 s and `qa_chat.py` 179 s, the last two 80% idle (one
Chromium, fixed waits). While one runs, the seat holds a Claude Code that
does nothing but wait, and the line behind it waits too. Two full suites at
once took 153/163 s with 3 GB left, perf noisy: so the cores take one heavy
job at a time, and the seat and the job overlap instead.

## The rules

1. **The seat is unchanged.** One engineer session at a time; stop, inbox,
   resume, yield, the 30-minute stuck rule, the captain's `seat-relieve`
   and the line's move/remove/restore all stay as `scripts/seat.py` has them.
2. **The verb.** `engineer.py job <name> [--timeout MIN] [--label TEXT] --
   <command…>`, run by the seated engineer in their worktree. It records
   the job: id (`<name>-<yyyymmdd-hhmmss>`), the command, the worktree,
   `HEAD`, a fingerprint of the tree (`git status --porcelain=v2` and the
   hash of `git diff HEAD`), the label (default: the command, clipped), the
   timeout, the submit time. `engineer.py job-cancel <name> [<id>]` drops a
   queued job or stops a running one; `engineer.py jobs` lists both lines.
3. **Inline when nobody waits.** If the seat's line is empty **and** no job
   is running or queued, the verb runs the command there and then and
   returns its output and exit code (today's behaviour), recorded as the
   running job (`"inline": true`) so the views show it and nothing else
   takes the cores under it. Someone arriving mid-run waits, as today: the
   turn is never cut, and the stuck rule cannot fire (it is working).
   Since 2026-10-25 the run itself is detached, as a queued one's is (see
   "As built: the watchdog"): it outlives the turn and the session.
4. **Otherwise it queues and the turn ends.** The verb prints the job's
   place and "end your turn now: the result will be typed to you"; it marks
   the holder yielded, as `yield` does, so the Stop hook passes the seat.
   Nobody else is seated who could edit the tree (one seat), and the job
   does not **start** until the submitter's turn has ended (the Stop hook
   dispatches it; reap does within five minutes if a hook is lost), the
   way a deploy waits for `wait_until_idle`: nothing edits under a job.
5. **The runner** is no daemon: `job_next()`, under `seat.lock`, starts
   the first queued job when nothing runs, no deploy is queued or running,
   and `MemAvailable ≥ LCARS_ENG_MIN_FREE_MB` (2500). It is called by the
   verb, the Stop hook, a job's own end, a deploy's end, and `reap` (every
   five minutes: the catch-all). A job runs in a transient user unit, as a
   deploy does (`systemd-run --user --collect --unit=lcars-job-<id>
   -p RuntimeMaxSec=<timeout> -p MemoryHigh=3G -p MemoryMax=4G
   --working-directory=<worktree> engineer.py job-run <id>`): it outlives the
   engineer's stopped tab, systemd kills the whole cgroup (its Chromiums and
   scratch servers) on the timeout, and `died_why` already reads an OOM or a
   timeout from the unit's journal. Why not the seat's mover: it runs under
   `seat.run` for seconds, not minutes. Why not a timer: a minute's latency
   on every job for nothing.
6. **The cores lock.** `job-run` holds `STATE/cores.lock` (flock) for the
   command's life; an inline job holds it too. A deploy keeps `deploy.lock`
   as it is and takes `cores.lock` only around its web suite and
   `vps-rebuild.sh`, so a docs deploy never waits; the order is always
   `deploy.lock` then `cores.lock`, and a job never takes `deploy.lock`, so
   they cannot deadlock. **A deploy is the head of the job line:** while one
   is queued or running `job_next()` starts nothing, and a running job is
   waited out (at most its timeout; the deploy's step line says "waiting
   for <id>"). A scheduled role whose run is heavy (front matter `heavy:
   true`, the qa role) takes `cores.lock` for its run the same way.
7. **The result.** `job-run` writes `STATE/jobs/<id>.json` (exit code,
   start, end) and the log, `STATE/logs/job-<id>.log`, **before** touching
   the journal, then puts a message in the engineer's inbox and queues them:
   `[job] <label>: PASSED|FAILED (exit N) in 2m14s on <HEAD7>. Log: <path>`,
   then the log's last 40 lines clipped to 3 KB, failure lines (`FAIL`,
   `Error`, `Traceback`) first when they are further up. The file is kept
   seven days (reap).
8. **Head of the line, with a cap.** A completion is queued as `by: "job"`
   at the front of the seat's line, behind other completions already there
   (first come, first back) and behind the captain's own order. **Except**
   when someone in the line has waited 30 minutes (SLICE): then it goes in
   behind them. Without the cap an engineer who submits a job every turn
   never yields the seat to anyone, and the stuck rule does not catch it
   (they are never stuck). **[captain]**
9. **HEAD moved: refused.** At start, `job-run` compares `HEAD` and the
   fingerprint with the submission's. If either moved (a deploy's rebase,
   the captain's hand), the job does not run; the message says "not run:
   the tree moved since you submitted it (HEAD a1b2 → c3d4)" and the
   engineer is queued at the head, to look and submit again. A result for a
   tree nobody submitted is worse than a lost slot.
10. **Timeout: 20 minutes by default, 60 at most** (`--timeout`). The
    longest measured job is a full run with three perf comparisons, ~5-6
    min, and `buttons.py` 5 min; 20 is three of the worst and still frees
    the cores within one stuck-rule slice. A timed-out job is reported
    `FAILED (timeout after 20m)`. **[captain]**
11. **Scheduled roles are not jobs.** A `crew:<role>` run is itself a
    Claude Code and keeps its place in the seat's line, bounded by its own
    timeout; only its heavy commands take `cores.lock` (rule 6).

## Light and heavy

Light, never queued (under ~30 s or no cores): `make check`, `make lcars`,
`make lcars-cli`, `run.sh --changed` that `changed.py` says runs no slow
stage, one functional test file under ~30 s (`offline.py`, `back.py`,
`speech.py`, every `scripts/test_*.py`), git, reads.

Heavy, always through `engineer.py job`: `lcars-ui/test/run.sh` (full or
`PERF=0`, and `--changed` when it picks QuickJS, keyboard, screens or perf),
`perf.py`, `buttons.py`, `qa_chat.py`, `keyboard.py` and its shards,
`dates.sh`, `architect.py`, `deckvoice.py`, `editor.py`, `classified.py`,
`deckshots.py`, `deckmem.py`, `shots.py`, `scripts/deck-models/build.sh` (the rooms),
`make lcars-release`, `make lcars-one`, `make lcars-embed`. (`back.py` was
on the order's list; at 21 s it is light by its own measure.)

**Enforcement** (built in 0.286.1, "As built: slice 3"): the rule in the brief (`brief_seat`) and CLAUDE.md, and a
`PreToolUse` hook on Bash in `crew_settings` that denies a bare heavy
command with "heavy: run it as `engineer.py job <name> -- <command>`". It
reuses `bash_part_kind`'s parsing; ~50 ms per Bash call. Worth it: a bare
`run.sh` beside a running job is exactly the contention the queue exists
to stop, and a rule in a brief is forgotten mid-task; the verb costs
nothing when idle (rule 3). **[captain]**

## State

The job lines live **in the `crew_seat` entry's JSON block**, a `jobs`
key: `{"running": {…} | null, "queue": [{…}], "recent": [last 5]}`. One
lock (`seat.lock`), one read, one write: a completion moves the job out
and its engineer into the seat's line atomically, which a sibling entry
could not do without a second lock; and the captain reads and edits both
lines where he already does. The entry's text gains `Job running: <name>,
<label>, since 14:02 (3 min)` and `Jobs queued: 1. …`. `normal()` checks
the block like the rest. What stays a file, on purpose: `cores.lock`, the
results (`STATE/jobs/<id>.json`, so a job that ends while the journal is
down is not lost: the next move reconciles from it) and the logs.

## Failure modes

- **Hang:** `RuntimeMaxSec` kills the unit; reported as a timeout.
- **The runner dies** (OOM, a reboot): `running` in the block, no result
  file, `cores.lock` free: the next move calls it failed with `died_why`'s
  reason, messages the engineer, and starts the next.
- **Dismissed** with a job queued or running: the job is cancelled (the
  unit stopped; killclean and the cgroup take its servers), the log kept.
  **Recalled** (a message) while their job waits: they are seated as
  usual, and the delivery says "[job] <id> is #2 in the job line / running
  since 14:02: do not edit; `job-cancel` to take it back, or end your turn".
- **Huge log:** the message is clipped (rule 7); the file is whole.
- **Short of memory:** `job_next()` waits (the entry's note says why) and
  reap retries; never killed for it.
- **Not seated:** refused, exit 2 ("you are not in the seat"); Number One
  is refused. With the seat off (`LCARS_ENG_SEAT=0`) the verb is inline.
- **Journal down** at submit: refused, as `seat_gate_start` is.

## The view

`seat_brief` and `queue_seat` gain `jobs` (running: whose, label, since;
queued: in order, whose, label). `no1.py crew list`'s seat block adds a
`jobs:` line; `crew poll` adds `job: {id, label, state, place}` for the
engineer. The console's Queue view: a "Jobs" block under the seat, the
running one with its elapsed time, the line in order, a Cancel button for
the captain; `queueRowHtml`'s preview adds "· job: <name>"; an engineer's
row (`engRowHtml`) wears a badge "job #2" or "job 3m". Voice: "computer,
show the jobs" (the Queue view at its Jobs block) and "computer, cancel
<engineer>'s job".

## Tests (slice 1)

`scripts/test_jobs.py`, test_seat's pattern: the decisions pure in
`seat.py` (`job_submit`, `job_next`, `job_done`), the verbs against
test_seat's stand-in server, `systemd-run` stood in by a direct child
(`LCARS_JOB_RUNNER=direct`), scratch `STATE`. Cases: inline when both
lines are empty (output and exit code returned, the block shows it while
it runs); queued when either is busy, and the holder yielded; no start
before the submitter's turn ends; one at a time; a completion's message
(pass, fail, timeout, a 10 MB log clipped) and its place at the head,
behind an earlier completion, behind the captain, and behind a 30-minute
waiter; HEAD moved and tree changed: refused and requeued; a deploy queued
holds the line; the runner killed mid-job reconciled; dismiss cancels;
not seated refused; the hook's classifier on the heavy and light lists.

## Slices

| slice | what | estimate |
|---|---|---|
| 1 | `job`, `job-run`, `job-cancel`, `jobs`; the runner, `cores.lock` and the deploy's use of it; the completion message and head-of-line; reconcile in reap; `test_jobs.py`, test_seat and test_deploy_suite still green (patch bump: ops) | 30 min |
| 2 | the views: crew list, poll, the Queue view's Jobs block and Cancel, the badges, the two voice orders; run.sh in full (minor bump) | 30 min |
| 3 | `brief_seat`, the PreToolUse hook (if the captain wants it), CLAUDE.md's heavy list, the engineers' manual, Number One's brief (patch bump) | 15 min |

## As built: slice 1 (0.285.3, `a1b4c0c`)

The handover for whoever builds slices 2 and 3. Slice 1 is deployed;
nobody is told to use it yet (slice 3), so no job has queued live.

**Code.** `scripts/seat.py`, section "the job line": pure decisions on the
seat state - `job_busy`, `job_find(s, name)` → (job, "running" | place
from 1), `job_submit` → "inline" | "queued", `job_release` (called by
`turn_ended`), `job_next(s, facts, now, deploying, mem_ok)` → (job | None,
why), `job_started`, `job_back` (head of the line with the cap: behind
`by` in `JOB_AHEAD` = captain, handover, job, and behind anyone queued ≥
SLICE), `job_done(s, jid, outcome, now, back)`, `jobs_normal`; `render`
writes "Job running" and "Jobs queued" lines. `scripts/engineer.py`,
section "the job queue" (after `cmd_yield`): `tree_print`, `cores`,
`job_exec`, `job_result_write`, `job_tail`, `job_text`, `job_finish`,
`job_settled`, `job_launch`, `job_dispatch`, `cmd_job`, `job_inline`,
`cmd_job_run`, `cmd_job_cancel`, `job_kill`, `cmd_jobs`, `reap_jobs`; and,
near `bash_kind`, `HEAVY_SCRIPTS`, `HEAVY_MAKE`, `heavy_command`,
`HEAVY_DENY`. `scripts/crew.py`: `heavy` in DEFAULTS, `cores_for`;
`crew/qa.md` has `heavy: true`.

**Files** (STATE = `~/.local/state/lcars-eng`, `$LCARS_ENG_STATE`; paths
from `jobs_dir()` at call time):

| file | what |
|---|---|
| `STATE/jobs/<id>.spec` | the job as launched; `job-run` reads it (not the journal) |
| `STATE/jobs/<id>.lock` | flock held by `job-run` / `job_inline` for the job's life; free with no result = died |
| `STATE/jobs/<id>.waiter` | flock held by an inline job's waiter (`job_inline`) while it follows the run; free = the waiter is gone, and the dispatcher tells the engineer |
| `STATE/watchdog.json` | the watchdog's findings already said to Number One, by key, for two days |
| `STATE/jobs/<id>.pid` | the command's process group leader (`job_kill`, cancel) |
| `STATE/jobs/<id>.result` | `{outcome: passed|failed|timeout|refused|died|cancelled, exit, secs, head, why}`, written once (`open(..., "x")`: first writer wins), before the journal is touched |
| `STATE/logs/job-<id>.log` | the command's output (the unit's stdout too) |
| `STATE/cores.lock` | one heavy thing at a time: a job, a deploy's `web_suite` and `rebuild()`, a `heavy: true` crew run; holds the holder's name as text |
| `STATE/jobs.run` | one dispatcher at a time (`job_dispatch`) |
| `STATE/seat.lock` | as before: every read-modify-write of the crew_seat entry |

Job id: `<name>-<yyyymmdd-hhmmss>`. `reap_jobs` deletes job files and
logs older than 7 days.

**The crew_seat block** gains `"jobs": {"running": job|null, "queue":
[job...], "recent": [last 5: {id, name, label, t, started, ended,
outcome}], "note": "why the first is not starting"}`. A job: `id, name,
cmd, label (≤80), wt, head, tree (16-hex fingerprint), t (submitted),
timeout (seconds)`, plus `hold` (the submitter's turn not yet over),
`started`, `unit` (`lcars-job-<id>` or `pid:N` under the direct runner),
`inline`. The result's seat entry is `{name, t, by: "job"}`; its inbox
row's sender is `job` (`ada ← job: [job] ...`), which `seat_deliver` and
`queue_seat` treat like the ship's notes (not a task, not an order).

**Verbs and their callers.**
- `job <name> [--timeout MIN] [--label T] -- <cmd>`: the seated engineer.
  `cmd` is one argument as a shell string, or several `shlex.join`ed; run
  with `bash -c` in the worktree. Refusals exit 2 (not seated, Number
  One, one job each, usage), journal down/broken exit 3. Inline: output
  streamed, then a JSON line, exit = the command's. Queued: JSON with
  `queued`, `place`, `note`.
- `job-run <id>`: only in the job's unit. Checks HEAD and fingerprint
  (refused if moved), waits for `cores`, runs, writes the result, calls
  `job_dispatch` (up to 3 tries 20 s apart if the journal is down).
- `job-next` = `job_dispatch()`: settles the running job (result file →
  `job_finish`; lock free past `JOB_GRACE` 60 s with no result → `died`,
  with the unit's journal reason), then starts the first startable. Called
  from `cmd_seat_turn_ended` (the Stop hook's `seat-turn-ended`), `job-run`'s
  end, `cmd_reap` (every 5 min; its output gains `seat.jobs` and
  `job_files_deleted`), and a deploy's or rollback's end (`atexit` →
  `job_next_later` → `spawn("job-next")`). Holds off while deploy.json says
  running, or queued under 10 minutes, and while MemAvailable <
  `LCARS_ENG_MIN_FREE_MB`.
- `job-cancel <name> [<id>]`: queued → out (no requeue); running → result
  `cancelled`, process group SIGTERM, `systemctl --user stop` the unit,
  then dispatch the next. `cmd_dismiss` does the same for their job.
- `jobs`: the block's `jobs` and `seat_brief`.

**The unit:** `systemd-run --user --collect --quiet
--unit=lcars-job-<id> --working-directory=<wt> -p
RuntimeMaxSec=<timeout+300> -p MemoryHigh=3G -p MemoryMax=4G -p
StandardOutput/StandardError=append:<log> --setenv=LCARS_ENG_DETACHED=1
<unit_env()> python3 engineer.py job-run <id>`. The job's own timeout
(default 20 min, `LCARS_JOB_TIMEOUT_MIN`, max 60) is enforced inside by a
timer: SIGTERM to the group, SIGKILL 10 s later; `RuntimeMaxSec` is the
backstop.

**The tests** (`scripts/test_jobs.py`, 32, ~13 s) run `job-run` as a
direct child (`LCARS_JOB_RUNNER=direct`), and `LCARS_ENG_SPAWN=0` makes
`spawn()` start nothing (it returns "off"). So **unproven live**: a job in
a real systemd unit (its environment from `unit_env`, the log append, the
cgroup kill on cancel and timeout, `died_why`-style reasons from
`journalctl`), the Stop hook → `seat-turn-ended` → dispatch path, and a
deploy actually waiting on `cores.lock`. The first real queued job is the
check: watch `engineer.py jobs` and the log.

**The classifier** (`heavy_command`, not wired): heavy = a part running
`run.sh` (not `--changed`), `perf.py`, `buttons.py`, `qa_chat.py`,
`keyboard.py`, `dates.sh`, `architect.py`, `deckvoice.py`, `editor.py`,
`classified.py`, `deckshots.py`, `deckmem.py`, `shots.py`, `deck-models/build.sh`, or
`make lcars-release|lcars-one|lcars-embed|lcars-static`; never a command
that runs `engineer.py`. The deny text, `HEAVY_DENY.format(what, eng,
name)`: "{what} is a heavy command: run it as `{eng} job {name} -- <the
command>` (inline when nobody waits; else queued, and you end your turn -
docs/design/job-queue.md)".

**Slice 2 touches** (the views; a minor bump, full run.sh):
- `engineer.py seat_brief` (add `jobs`: running {name, label, since},
  queued [{name, label}], and for `name` its job and place) and
  `queue_seat` (the same for the Queue view, with titles); `cmd_list` and
  `cmd_poll` already carry `seat_brief`, so `no1.py crew list` and `crew
  poll` get it through them - check no1.py's printing of the seat block
  and add a `jobs:` line there.
- A route to cancel for the captain: `lcars_engineer.h` maps
  `/engineer/...` verbs; add `job-cancel` (and test it as
  `test_engineer_model.py` does its route).
- `index.html`: the Queue view (`queuePaint`, `queueWorking`,
  `queueQueued`, `queueWho`) gets a Jobs block under the seat with the
  running job's elapsed time and a Cancel (optimistic, per the feedback
  rule); `queueRowHtml`'s preview "· job: <name>"; `engRowHtml` a badge
  "job #2" / "job 3m"; two `VCMDS` lines ("show the jobs", "cancel
  <engineer>'s job") and their `KEYS`/palette rows. Tests: QuickJS
  behaviour checks for the block and badge, `test_queue.py` for
  `queue_seat`, `test/buttons.py` if a button is added.

**Slice 3 touches** (the rules; a patch bump):
- `brief_seat`: the heavy list, "heavy ones go through `job`", end the
  turn after a queued submit, never edit while a job is queued or
  running, `[job]` messages bring you back at the head.
- `crew_settings`: a `PreToolUse` hook (matcher `Bash`) running a new verb
  (e.g. `heavy-check <name>`) that reads the hook's JSON from stdin, calls
  `heavy_command(tool_input.command)`, and answers `{"hookSpecificOutput":
  {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": HEAVY_DENY...}}`; allowed otherwise. Decide
  whether `run.sh --changed` should run `changed.py --json` to tell.
- CLAUDE.md: the light and heavy lists (this doc's "Light and heavy") and
  the rule; the engineers' manual; `brief_no1` (the jobs line in crew list,
  that a `[job]` result is not a report to it).

## As built: slice 2 (0.286.0)

- `engineer.py`: `jobs_brief(s)` (running {id, name, label, t, since,
  elapsed, inline?}, queue [{id, name, label, t, place, hold?}], recent,
  note) and `job_of(jb, name)` ({id, label, state: running|queued, place,
  since}). `seat_brief` always carries `jobs`, and `job` for the name
  asked; `queue_seat` carries `jobs` with titles. `cmd_list`'s rows get
  `job` (their `status` is left as it is: a message to an "off" one must
  still start them); `cmd_poll` gets `job` where it reads the seat (an
  engineer with no live agent, which is what a queued submitter is).
- `lcars_engineer.h`: `POST /engineer/<name>/job-cancel {id?}` →
  `engineer.py job-cancel <name> <id>`; the id checked to `[a-z0-9-]`.
- `index.html`: `queueJobs`/`queueJobCtl` (the Jobs block, `#qjobs`,
  under Queued), `queueJobCancel` (asks in the row, "cancelling…", the
  error on the row), `queueJobTap`, `queueJobsShow` ("show the jobs"),
  `queueJobSaid` ("cancel <name>'s job": the row asks, as the tap does,
  the focus on Keep; only the tap on Cancel the job acts - the page has no
  spoken yes, the queue's removal its own "confirm the removal"), `engJobBadge` on `engRowHtml`, the preview in
  `queueRowHtml`; a palette row for the jobs.
- Tests: tests.js (the block, Cancel, a failure, the orders, the badges),
  `test_queue.py` `test_the_job_lines`, `test_engineer_model.py` the route.

## As built: slice 3 (0.286.1)

- `brief_seat` gains a paragraph "Heavy jobs": the heavy list, the verb,
  inline when nobody waits, "queued" means end the turn at once and edit
  nothing, the `[job]` result at the head of the line, `jobs` and
  `job-cancel`. `brief_no1` one paragraph: the job lines, `crew list`/`crew
  poll` show them, `crew queue` untouched, a `[job]` line is a job's result.
- The hook: `crew_settings(name)` adds `PreToolUse`, matcher `Bash`,
  `engineer.py heavy-check <name>`, only when `seated(name)` (the seat on,
  never Number One, whose settings are `no1_settings`; crew.py's scheduled
  roles never get `crew_settings`). `heavy_check(name, hook_json)` answers
  the deny (`HEAVY_DENY`, the live engineer.py's path) for a heavy Bash
  command, else nothing; `cmd_heavy_check` fails open (any error: allowed).
  `run.sh --changed` is light by `heavy_command`; the brief and CLAUDE.md
  say when it is not. ~0.12 s per Bash call (the import of engineer.py).
  A running session gets the hook at its next start (the settings file is
  written by `cmd_start`).
- CLAUDE.md, the test section: the heavy and light lists and the rule;
  docs/ops/engineer-time.md points at the job line.
- Tests: `test_jobs.py` `test_the_hook_is_wired` (the settings, Number One's
  and the seat off without it, heavy_check's deny and passes, the verb on
  stdin, garbage failing open).

## More than one: an adaptive seat and an adaptive job line

Lieutenant Torres, 2026-10-22, at main `fae274c` (0.296.1). The
captain's order through Number One: let more than one engineer work at
once, and more than one heavy job run at once, when the box has CPU and
RAM to spare. **Design only.** Number One reviews it before anything is
built. Marked **[captain]**: the rules that are his to settle. The
numbers and margins are also in the HTML report published with this
commit.

### What was measured

On the VPS (4 vCPU, 7.9 GiB, 975 MB swap), 2026-10-22 11:15-12:15, a
1 Hz sampler read `/proc/meminfo`, `/proc/stat`, `/proc/loadavg` and
`/proc/pressure/*`, the cgroup of every `lcars-job-*` and
`lcars-eng-deploy-*` unit (`memory.current`, `cpu.stat`), and each
Claude Code, `lcars`, and `llama-server` process (RSS, VmSwap, CPU
ticks). My own three heavy runs went through the job line, one after the
other, with marks. The others are the crew's own jobs from the same hour,
measured where they ran. The box was as it is on a working day: Number
One awake, one to three engineers waking for their turns, the live
server, and llama-server.

| what | wall | memory, its peak | cores, mean / peak over 10 s | box: lowest MemAvailable | CPU pressure (PSI some, mean) |
|---|---:|---:|---|---:|---:|
| `run.sh`, full (perf included) | 184 s | 1.6 GB | 1.7 / 3.0 | 3.0 GB | 22% |
| `run.sh`, `PERF=0` | 70 s | 1.6 GB | 1.7 / 3.2 | 3.3 GB | 11% |
| `buttons.py` (263 checks) | 357 s | 0.54 GB | 0.8 / 1.6 | 4.3 GB | 2% |
| deckshots (zimmerman's, slice 6) | 973 s | 1.4 GB | **3.2 / 3.7** | 3.2 GB | 14% |
| deckshots (okafor's, timed out at 20 min) | 1200 s | 1.5 GB | **3.1 / 3.8** | 3.2 GB | 13% |
| explainer `render.sh` + `deliver.sh` (kim's) | 494 s | **3.1 GB, at MemoryHigh=3G** | **3.1 / 3.7** | **1.8 GB** | **40%**; memory PSI full up to **47%** |
| a deploy with its web suite | ~1200 s, mostly waiting for the cores | 1.8 GB | | | |

| resident, beside the jobs | memory | CPU |
|---|---:|---|
| a Claude Code, awake and working (9 engineers seen) | 300-400 MB RSS (230 MB just started), + its `fff-mcp` 55-95 MB | 16-35% of a core over a turn; p95 0.4-1.1 cores; peaks 1.3 |
| a Claude Code, idle (Number One, 1 h) | 380 MB | 2.4% (busy 9% of the time) |
| `lcars`, the live server | 36-42 MB RSS (its cgroup 117 MB with page cache) | 0.5% |
| llama-server (`lcars-embed`, MemoryMax 800M) | 590 MB, resident all hour | 0.5%, bursts of a core on writes |
| journald, alloy, tailscaled, herdr, node_exporter | ~430 MB | ~2% |
| the timers (`crew@social`, `crew-notes`) | 10-40 MB | ~0 |
| **the box at rest** (no job, 103 s of the hour) | **MemAvailable 4.6 GB** (6.7 GB on 10-14) | 12% busy (median), 30% (p90) |

What this says:

- **The job line was never idle.** A job ran for 57 of the 59 minutes,
  and 2-4 waited behind it the whole hour. That line limits the crew now,
  not the seat. More seats alone mostly make the line longer.
- **Three kinds of job.** *Saturating*: deckshots and the explainer
  render keep 3.1-3.2 of the 4 cores busy for 8-20 minutes. Nothing fits
  beside them, and deckshots measures frame times anyway. *Parallel*:
  run.sh averages 1.7 cores, with peaks of 3 (QuickJS beside the
  keyboard shards, perf's two Chromiums). *One browser*: buttons.py and
  its kind (qa_chat, editor, back, deckvoice) use 0.8 of a core, mostly
  waiting. Two of those, or one beside a `PERF=0` run, fit.
- **A Claude Code is cheap for the box**: ~450 MB with its fff, about a
  quarter of a core while it works, ~0 idle. Three awake cost ~1.4 GB and
  under one core. That is less than one run.sh.
- **Memory is the real limit, and RAM is leaking into /tmp now.** Swap
  is **100% used** (973 of 975 MB). MemAvailable at rest is 4.6 GB,
  against 6.7 GB on 10-14. The gap is `/tmp`, a tmpfs: 2.3 GB in use,
  **1.66 GB of it 18 `remotion-webpack-bundle-*` dirs** the explainer
  renders leave behind (96-174 MB each). Nothing reaps them (`reap_test_tmp`
  does not know the name). tmpfs pages are what went to swap: the herdr
  cgroup holds 1.4 GB of shmem and 880 MB of swap, with only 670 MB of
  anon. This must be fixed first (slice 0). Every margin below counts on
  getting that 1.7 GB back.
- **The explainer render is the one job that reaches its cgroup's cap.**
  At MemoryHigh=3G its memory stalls reached 47% of the time
  (throttled), and the box fell to 1.8 GB available. It runs alone, and
  its class gets a higher MemoryHigh (below).
- **Today the OOM killer would not spare the server.** Every process
  here has `oom_score_adj` 200: the server, llama-server, the Claude
  Codes and the Chromiums alike (the user manager's default). The kernel
  would take the largest process first, a Chromium GPU process at 800 MB,
  and the server's 40 MB keeps it low on the list. But nothing
  *guarantees* that. `systemd-oomd` is not running.

The 10-14 numbers still hold for two full suites at once: 153 and 163 s
each, against 132 s alone, with 3.0 GB left and CPU pressure at 43%.
Perf was noisy in both: scroll-up went over budget (16.7 and 19.2 ms,
against 12.2 ms alone).

### The rules

1. **Two limits, opened one step at a time.** `N`, the seats: engineers
   awake at once. Number One is outside them, as now, and a scheduled
   role takes a seat as now. `M`, the cores: heavy jobs running at once.
   Each has a ceiling, `LCARS_SEATS_MAX` (proposed 3) and
   `LCARS_JOBS_MAX` (proposed 2), and a current value from 1 up to it.
   **[captain]** A limit moves only in `step()` (the seat) and
   `job_next()` (the jobs), on the moves that call them now: a turn's
   end, a job's end, a deploy's end, `reap` every 5 minutes. No daemon is
   added.
2. **Opening a seat.** Seat `k+1` opens when all of these hold:
   - MemAvailable ≥ **2.7 GB**: the reserve (1.5 GB, below), plus
     0.5 GB for the Claude Code and its fff, plus 0.7 GB for the bare light
     tests it runs (one Chromium, an ASan build);
   - CPU pressure (PSI `some` avg60) < **20%** (12-22% with one run.sh
     going), and the 1-minute load < 4;
   - at least **3 minutes** since the last seat opened, so that the new
     one's cost shows in the readings before the next step.
   A seat is the line's head being started, as now. The line's order is
   kept: the next seat goes to the first in line, never to someone
   further back.
3. **Starting a second job.** Job `j+1` starts when all of these hold:
   - the job line's head is that job. **FIFO, kept**: a job that cannot
     start yet holds the ones behind it, so a saturating job is never
     starved by small ones. Held jobs (the submitter's turn not over)
     still do not block, as now;
   - the running jobs and this one are all *shared* (below), and their
     core weights sum to ≤ 4 (nproc);
   - MemAvailable less this job's class peak ≥ the **1.5 GB reserve**;
   - CPU pressure avg60 < **25%**;
   - no deploy is queued or running. A deploy still has the cores first.
4. **Closing, and what "close" means.** A limit drops by one (never below
   1) when any of these hold:
   - MemAvailable < 1.0 GB;
   - memory PSI `some` avg60 > 5% (0% in every reading here except the
     explainer at its own cap);
   - swap-in > 2 MB/s for a minute (`pswpin` in `/proc/vmstat`);
   - CPU pressure avg60 > 40% (two full suites at once measured 43%).
   Closing **never cuts a turn and never kills a job**. A seat over the
   limit is given up at its holder's next turn end (they stand down, as
   an idle holder does now, and nobody is seated in their place). A job
   over the limit runs to its end, and the next one waits. A limit opens
   again only after the opening margins hold for 5 minutes (hysteresis),
   so the limits do not flap on one reading.
5. **The jobs that run alone.** A job's class comes from `heavy_command`'s
   parse, which already knows the heavy list:

   | class | jobs | weight (cores) | peak, its unit's MemoryHigh/Max |
   |---|---|---:|---|
   | **exclusive** (measures time, or fills the box) | `perf.py`; `run.sh` without `PERF=0`, and `--changed` when changed.py picks perf; `deckshots.py`, `shots.py`, `deckmem.py`; `video/explainer/render.sh`; `deck-models/build.sh`, `dates.sh` (not measured yet: exclusive until they are); **any command it cannot class** | 4 | as now, 3G / 4G (3.5G / 4G since 2026-10-24); the explainer 3.5G / 4.5G |
   | shared, parallel | `run.sh` with `PERF=0`, or `--changed` without perf; `keyboard.py` | 2 | 1.8 GB; 2.5G / 3G (3.0 GB; 3.5G / 4G since 2026-10-24: "run.sh's memory, again") |
   | shared, one browser | `buttons.py`, `qa_chat.py`, `editor.py`, `architect.py`, `deckvoice.py`, `classified.py` | 1 | 0.7 GB; 1G / 1.5G |
   | shared, a build | `make lcars-release`, `lcars-one`, `lcars-embed` | 1 | 0.3 GB; 1G / 1.5G |

   An exclusive job starts only when nothing else runs. While one is at
   the head of the line, nothing new starts. A job that runs two things
   (`run.sh && buttons.py`) takes the stricter class. **[captain]**: perf
   and deckshots alone is the order's own rule. Running unknown commands
   alone is the safe default.
6. **The cores lock becomes shared and exclusive.** `STATE/cores.lock`
   stays one file. A shared job takes `flock(LOCK_SH)`, an exclusive job
   or a deploy's suite and `vps-rebuild.sh` takes `LOCK_EX`, and so does a
   `heavy: true` crew run. *How many* shared jobs run is `job_next()`'s
   decision, under `seat.lock`. The lock only guarantees that an
   exclusive holder is alone. The order stays `deploy.lock`, then
   `cores.lock`, and a deploy that wants `LOCK_EX` waits out the running
   shared jobs (at most their timeouts, which is today's rule).
7. **The switch.** In `~/.env`, `LCARS_SEATS_MAX=1` and `LCARS_JOBS_MAX=1`
   give exactly today's behaviour. **I propose shipping with both at 1**:
   the code is live, but nothing changes until the captain sets 3 and 2.
   `LCARS_ADAPT_FIXED=1` pins the limits at their ceilings without the
   readings, for testing. **[captain]**
8. **Memory pressure, and keeping the server alive.**
   - *Get the RAM back first* (slice 0). `reap_test_tmp` learns
     `remotion-webpack-bundle-*`, and `render.sh` removes its bundle on
     exit (a trap). That frees ~1.7 GB of RAM and swap now, and it keeps
     the margins honest.
   - *The gate is the main defence*. The 1.5 GB reserve is kept beside
     everything: llama-server waking (~600 MB), a Claude Code growing
     (~100 MB a turn), git and the server's page cache.
   - *The victims are ordered.* Every job unit gets
     `OOMScoreAdjust=900`, and herdr's unit (the Claude Codes) 500.
     Raising it needs no privilege, so the user manager can set both. The
     server keeps 200 and becomes the last choice by far: the kernel adds
     adj × RAM / 1000 to a process's score, so 900 counts as 7 GB. A
     job's Chromium goes first, then a Claude Code, and llama-server is
     restarted on demand anyway. Lowering the server *below* 200 needs
     root (a drop-in on `user@1000.service`), and so does `MemoryLow`
     protection for `lcars.service`, which only takes effect when the
     user slice is protected too. Those are the captain's to add if he
     wants them, and nothing here depends on them.
   - *No systemd-oomd.* It kills a whole cgroup on pressure, and the
     herdr cgroup is every Claude Code at once.
   - *Swap* stays 1 GB. With the /tmp leak gone it holds idle pages only,
     and swap-in is one of the closing signals (rule 4).

### Two engineers at once: what must not collide

- **Worktrees**: each has their own (`~/lcars-eng/<name>`), their own
  branch, their own `STATE/<name>.*`, and their own herdr pane. Scratch
  servers and Chromiums pick free ports, and test scratch is per run
  (`killclean.mkdtemp`). Nothing here is shared.
- **The job line**: as above. Submissions are already one per engineer
  (`job_find`), the line is one list under `seat.lock`, and a completion
  goes to the head of the *seat's* line as now. With N seats it is
  usually seated at once.
- **The tree guard** (rule 9) holds per job. A deploy's rebase only moves
  its own branch.
- **The deploy lock**: deploys stay one at a time (`deploy.lock`,
  deploy.json's queue). With two engineers finishing at once, the second
  rebases onto the first's merge, so **CHANGELOG/APP_VERSION conflicts
  become more frequent** (11 of 29 failed deploys on 10-14 were those).
  The deploy reports the conflict, and the engineer rebases and bumps
  again, as the brief already says. I do not propose an automatic version
  merge here (that is a separate TODO).
- **The bare light tests** of several awake engineers run beside a job
  and outside the line: `make lcars`, a functional test under 30 s,
  `scripts/test_*.py`. That costs a few seconds of CPU each. The opening
  margin's 0.7 GB per seat is for them.
- **Number One gets several reports at once.** Each forwarded last
  message is its own `crew_inbox` note, and the flusher types them
  together under their `[thread …]` lines (test_no1_threads covers
  several at once). The forward already names the sender. `brief_no1`
  gains one line: reports may come in twos or threes, and each is
  answered on its own.
- **The stuck rule** (SLICE, 30 min) fires only when someone waits and
  every open seat is taken. Otherwise the waiter just gets the next seat
  to open.
- **A live server restart** (a deploy rebuilding C) is seen by several
  sessions at once. Their journal calls get `Down` and retry, as one
  does now.

### State and views

- **crew_seat's block**: `holder` becomes `holders: [{name, since, by,
  turn, …}]`, and `normal()` migrates a lone `holder` into it. A new
  `limits: {seats, seats_max, jobs, jobs_max, at, why, opened}`, where
  `why` is the last reading in words ("2 of 3 seats: 3.4 GB free, CPU
  pressure 12%" / "held at 1: memory pressure 7%"). `jobs.running`
  becomes a list. The entry's text: `Seated: torres-c37 since 14:02,
  kim-c32 since 14:10 - 2 of 3 open (3.4 GB free, CPU 12%)` and `Jobs
  running: 2 of 2: …`.
- **`engineer.py jobs` / `crew list` / `crew poll`**: `seat_brief` gains
  `holders` and `limits`, and `jobs.running` is a list. `no1.py crew
  list`'s seat block prints one line per holder and a `limits:` line.
- **The console's Queue view**: the Seated block lists each holder. A
  chip in its header reads "seats 2/3 · cores 1/2", or "seats held at 1:
  memory" when the limit is closed. The Jobs block lists every running
  job with its elapsed time and its Cancel button. "computer, show the
  seats" opens the Queue at that block, the palette has a row for it,
  and the existing "show the jobs" stays.

### Tests

`scripts/test_seat.py` gets the pure decisions: `limits(s, readings,
now)` opening one step and not a second within 3 minutes; a close
cutting nobody and the holder over the limit stood down at their turn's
end; hysteresis; the line's order across two free seats; the stuck rule
only with every seat taken; `LCARS_SEATS_MAX=1` giving today's sequence
exactly (the existing cases unchanged). `scripts/test_jobs.py` gets the
classes from `heavy_command`; two shared jobs together; an exclusive job
at the head holding a shared one behind it; a deploy holding both; the
memory reserve; `LCARS_JOBS_MAX=1` as now; and `LOCK_SH`/`LOCK_EX` on a
scratch `cores.lock` with two direct runners. The readings come in
through `facts` (no `/proc` in the pure code), so the tests feed them.

### What the captain should know it costs

- **His Claude usage goes faster per hour, for the same work.** An
  engineer spends tokens only while working. Three awake at once spend
  them up to three times as fast, so the plan's 5-hour and weekly limits
  arrive up to three times sooner. The total for a piece of work does not
  fall. It only finishes sooner. Number One, which reviews every report,
  spends faster too.
- **Some extra work, too**: more deploy conflicts (above), each a short
  extra turn; and jobs running in twos are each ~15-25% slower (153/163
  s against 132 s, measured on 10-14). That is box time, not tokens.
- **The gain is limited by the job line.** In the hour measured, the
  line was busy 57 of 59 minutes, mostly with exclusive jobs (deckshots,
  the render). Those still run one at a time. More seats help most while
  engineers read, think and edit. Parallel jobs help when the line is
  full of `PERF=0` runs and buttons-like checks.

### Slices (after the captain's review)

| slice | what | estimate |
|---|---|---|
| 0 | the /tmp leak: `reap_test_tmp` learns the remotion bundles, `render.sh` traps its own; `OOMScoreAdjust=900` on job units, 500 on herdr's (patch, ops) | 10 min |
| 1 | the seat: `holders`, `limits()` with the readings in `facts`, the switch, the stuck rule over N, `normal()`'s migration; test_seat (patch, ops) | 30 min |
| 2 | the jobs: classes, `job_next` over a list, shared/exclusive `cores.lock`, the deploy's `LOCK_EX`, per-class MemoryHigh/Max; test_jobs, test_deploy_suite (patch, ops) | 30 min |
| 3 | the views: `seat_brief`, crew list/poll, the Queue view's Seated block, chip and Jobs list, the voice order and palette row; full run.sh (minor) | 30 min |
| 4 | the briefs (`brief_seat`: others may be awake; `brief_no1`: reports in twos), CLAUDE.md, engineer-time.md's "second seat" (patch) | 10 min |

## As built: slice 0 (0.296.4)

Number One's order (on the design's review). It deferred herdr's 500.

- **The leak.** `video/explainer/render.sh` makes `lcars-render-XXXXXXXX`
  under `$TMPDIR` and exports it as `TMPDIR` for the render (Node's
  `os.tmpdir()`, so Remotion's bundle and its Chromium's scratch land in
  it). Traps remove it on exit; TERM, INT and HUP `exit` so that dash runs
  the EXIT trap, which a job's cancel or timeout (SIGTERM to the group)
  needs. `engineer.py`: `REMOTION_TMP_RE` (`remotion-webpack-bundle-`,
  `remotion-v<ver>-assets`, `lcars-render-`), `REMOTION_KEEP_H` (2,
  `$LCARS_REMOTION_KEEP_H`), `remotion_running()`. `reap_test_tmp` judges
  those dirs by the Remotion keep instead of the tests' 24 h, and skips
  them all while a Remotion process of ours runs. The /proc scan happens
  once per sweep, and only if there is such a dir. Why both guards: a
  bundle is written at its render's start and only read after, so its age
  is the render's, and a job runs at most 60 minutes. The process check
  covers a render outside the job line (the studio, a hand-run
  stills.mjs). The scan reads argv words, not a shell's `-c` script, so
  a tool call that only *mentions* remotion does not hold the sweep. Its
  first version did, and caught my own shell.
- **Cleared on 2026-10-22, 12:40**, with no render running (a deckshots
  job was): 18 dirs, 1650 MB. MemAvailable 3285 → 4307 MB; swap in use
  972 → 376 MB; shmem 1461 → 407 MB; /tmp 2323 → 672 MB.
- **OOM.** `JOB_UNIT_PROPS` = MemoryHigh=3G, MemoryMax=4G,
  OOMScoreAdjust=900, passed to `systemd-run`. Checked live on a scratch
  transient unit: `oom_score_adj` 900, `oom_score` 1266, against the
  server's 802 (the kernel's scale, which the adjustment shifts). The
  deploy's own unit (its web suite) is left at 200. It runs alone on the
  cores and is short.
- **Herdr at 500 without a restart: the proposal, not built.**
  `oom_score_adj` is per process and inherited by children, and a process
  may raise its own, or another of its uid's, without privilege. So
  `engineer.py`'s `cmd_start` can write 500 to
  `/proc/<claude pid>/oom_score_adj` once the pane's Claude Code is up
  (the pid `agent_info` already reads), and reap can do the same for the
  sessions already running. Number One's too, by the same path. Neither
  herdr nor a session is restarted. The cost is a few lines and one more
  test. The order is then a job's process (900), a Claude Code (500), and
  llama-server and the server last (200). Worth it only if the box ever
  runs short with the gate in place; the gate (slices 1-2) is the real
  defence.

## As built: the jobs (0.298.6)

The captain's answer (ask 9775, through Number One): parallel heavy jobs,
not more Claude Code sessions. The seat stays one; its slice 1 (holders,
`N`) is dropped. This is the design's slice 2, the views (slice 3) next.

- **The block.** `jobs.running` is a list (`seat.normal` reads the old
  single job into it); `jobs.limit` = `{n, max, why, good_since, at}`.
  A job carries `cls`, set at submit by `engineer.py`'s `job_class`; one
  without (submitted before) is exclusive.
- **Classes** (`seat.JOB_CLASSES`: weight, peak MB): exclusive (4, 3000),
  explainer (4, 3500), parallel (2, 1800; 3000 since 2026-10-24), browser (1, 700), build (1,
  300). `job_class` reads the command as `heavy_command` does (both use
  `cmd_parts`), the strictest part wins, and a command with no part it
  knows is exclusive. `run.sh` is parallel with `PERF=0` (in its own
  words or an earlier `PERF=0`/`export PERF=0`), exclusive without;
  `--changed` asks `test/changed.py --json` at submit whether it picks
  perf (and is exclusive when it cannot tell). `make lcars-static` (Alpine,
  docker) is not a build here: exclusive.
- **`job_limit(s, r, now, jobs_max)`**, pure: the limit opens at the
  ceiling; a bad reading (MemAvailable < 1000 MB, memory PSI > 5%,
  swap-in > 2048 kB/s, CPU PSI > 40%) drops it by one, never below 1, and
  kills nothing; it rises by one after `JOB_REOPEN` (300 s) of readings
  that are none bad and CPU PSI < 25%, the clock restarting on any that
  is not. Readings are taken only at the moves (no daemon), so "5 minutes"
  means the first move after five minutes of good moves.
- **`job_next(s, facts, now, deploying, mem_ok, r)`**: the head is the
  first job not held (a held one does not block). Nothing while a deploy
  is queued or running. With nothing running, the head starts on
  today's rule alone (`mem_ok`: `MIN_FREE_MB`). Beside running jobs:
  fewer than `limit.n`, the head and every running one shared, weights
  ≤ `JOB_CORES` (4), MemAvailable less the head's peak, and less the peaks
  of jobs started under `JOB_FRESH` (90 s) ago (not in the reading yet), ≥
  1500 MB, CPU PSI < 25%. An unknown reading keeps it waiting. An
  exclusive head waits, and holds everything behind it.
- **The readings** (`engineer.py`'s `box_readings`): MemAvailable,
  `/proc/pressure/{cpu,memory}` some avg60, and swap-in from
  `/proc/vmstat`'s `pswpin`, averaged since `STATE/vmstat.json` (renewed
  once a minute old; with none from the last 15 minutes, a one-second
  sample). Taken outside the seat lock, and only with a job in the line.
- **`job_dispatch`** settles every running job that ended, then starts
  heads while `job_next` allows (two at most at `max` 2).
- **`cores.lock`**: `cores(on_wait, who, shared)`. A job takes `LOCK_SH`
  if its class is shared, else `LOCK_EX`; a deploy's suite and rebuild
  and a `heavy: true` crew run, `LOCK_EX` as before. Only an exclusive
  holder writes its name in the file. Order unchanged: `deploy.lock`, then
  `cores.lock`.
- **Units**: `JOB_UNIT_PROPS[cls]`: MemoryHigh/Max exclusive 3G/4G,
  explainer 3.5G/4.5G, parallel 2.5G/3G (exclusive and parallel both
  3.5G/4G since 2026-10-24), browser and build 1G/1.5G;
  `OOMScoreAdjust=900` on all.
- **The switch**: `LCARS_JOBS_MAX` (the environment, then `~/.env`,
  default 2). `LCARS_JOBS_MAX=1` in `~/.env` is the line exactly as
  before; it is read at each dispatch, so no restart is needed.
- **The views until slice B**: `jobs_brief`'s `running` is still the
  first running job (the console and `crew list` show one), and `runs`
  lists them all with each one's class; `limit` gives `n`, `max`, `why`.


## As built: carrying jobs over an upgrade (0.299.2)

What 0.298.6's own deploy did to the jobs in flight: a process of the
code before it (an old `job-run`, or the deploy's) wrote the block back
its own way, which read the new `running` list as no job, so La Forge's
running deckmem dropped out of the block. Its run went on, holding
cores.lock; the line, seeing nothing running, started O'Brien's
demo_static and Zimmerman's all5.sh, whose units waited on that lock
with their wait counted against `RuntimeMaxSec` (O'Brien's died at
~1650 s); and La Forge's result was never reported. Now:

- **The job files are the truth of a job in flight.** `job_dispatch`
  first carries over (`job_strays`, seat.py's `job_adopt`, logged
  "carried over") a launched job (a `.spec`, under 6 h old) that the
  block has lost, not yet reported (no `.told`, which `job_finish`
  writes), whose run holds its lock, or whose result was written after
  this code first looked (`.adopt-since`: older results were reported by
  the code of their day). It is settled and reported as any other.
- **A job-run's next step is the code on disk**: it runs `engineer.py
  job-next` as a fresh process, never its own `job_dispatch`, so a run
  that outlives a deploy hands its result to the new code.
- **Waiting for the cores is not run time.** The job's own timer starts
  once it has the cores (as before); the unit's `RuntimeMaxSec` is now
  timeout + 300 + `JOB_CORES_WAIT` (3600 s, `LCARS_JOB_CORES_WAIT`), and
  the wait itself gives up after that long: `died`, "it waited 60m for
  the cores, held by <holder>".
- **The short functional tests share the box.** A new class, `test`
  (1 core, a 900 MB peak, the unit 1.5/2 GB), for the tests CLAUDE.md
  lists at about two minutes or less (demo_static, recording, reports,
  offline, … deckboot.js) and `scripts/test_*.py`: each on a scratch
  server of its own and at most one Chromium, nothing timed against a
  frame budget. A `bash -c '…'` wrapper's script is read through its
  quote. Before this, those classed exclusive (unknown), so no two jobs
  had ever run together. `run.sh --changed` was already right: parallel
  unless changed.py picks perf.

## As built: the views (slice B)

- **The Queue view's Jobs block** lists every job in `runs` (a server
  before 0.298.6 sends only `running`, which is then the one), each with
  how long it has run and its own Cancel, asked in its row as before. Its
  heading wears a chip from `limit`: "cores 1/2" (running, of `max`), or,
  when `n` is under `max`, "held at 1: <why>" in amber; no chip when the
  server sends no limit. The Queue row's preview names every running one.
- **"Computer, show the cores"** (and a palette row) opens the block and
  says the chip with what runs and waits; "show the jobs" stays. The
  seats' half of the design (holders, "show the seats") was dropped with
  the seat's slice 1.
- **`jobs.line`** (engineer.py's `jobs_line`) is the chip in words, for
  `crew list` and `crew poll`: "cores 2/2: bob run.sh 4m, cy buttons.py
  1m; 1 waiting (dee)", "held at 1 of 2 (memory pressure 7%): ...", "no
  job running (cores 0/2)". The engineers' and Number One's briefs say two
  may run when both share the cores and the box has room.
- **Tests**: the QuickJS suite (two runs listed with their Cancels, the
  chip, held and why, the preview, the order) and test_jobs.py's
  `test_the_views_line`.


## As built: run.sh's memory, again (2026-10-24)

Since UI research slice G (0.327.3), run.sh's screens stage runs
`targets.py` and `axe.py`, two more Chromiums, beside keyboard's shards.
Mendez measured a `PERF=0` run once at **2757 MB** of PSS across 61
processes, 35 s in. Measured again through the job line (alone, the
whole process tree sampled four times a second, a synthetic journal):

| run | wall | peak PSS, when | processes (Chromium's) | /tmp grown | box MemAvailable, start → lowest |
|---|---:|---:|---:|---:|---:|
| `run.sh`, `PERF=0` | 85 s | **2707 MB**, 34 s | 61 (43) | 219-227 MB | 5393 → 2672 MB |
| `run.sh`, full | 212 s | **2764 MB**, 36 s | 61 (43) | 219 MB | 5385 → 2656 MB |

The peak is the screens stage beside keyboard and QuickJS, not perf
(which comes later, alone), so the full run peaks no higher. /tmp is a
tmpfs, so what the run writes there is RAM as well, outside its PSS: a
run.sh takes ~2.9-3.0 GB of the box, against the 1.8 GB its class said.

- **`parallel` is (2, 3000)**: weight 2 as before, peak 3000 MB. The gate
  (MemAvailable less the head's peak ≥ the 1.5 GB reserve) then wants
  4.5 GB free beside running jobs: a `PERF=0` run.sh still starts beside
  a build or a one-test job on a box at rest (~5.4 GB free), and never
  beside another run.sh (~2.7 GB free with one going). Two at once would
  have needed ~6 GB of the 7.9 GB box with the Claude Codes, the server
  and llama-server beside them: past its memory, as Number One feared.
  Not made exclusive: the gate already keeps two apart, and sharing with
  a build or a short test is still safe.
- **The units**: parallel 3.5G / 4G (was 2.5G / 3G, which a 2.6 GB
  cgroup would hit: reclaimed and slowed at MemoryHigh, killed at Max),
  and exclusive, the full run.sh's class, 3.5G / 4G (was 3G / 4G, the
  same margin gone).
- `keyboard.py` alone shares the class and so is over-reserved now (it
  was never measured alone); `--changed` without perf too when it runs
  only the behaviour stage. Both err on the safe side; a class of their
  own, if the line ever waits on them, wants a measurement first.


## As built: the watchdog, and inline jobs that outlive the turn (2026-10-25)

**What happened.** Mendez ran `dates.sh` on the synthetic journal inline
(nobody waiting), twice, as a background command of her session: Claude
Code's Bash stops waiting at 10 minutes and moves a command to the
background, and a background command ends with its session.
`mendez-c35-20261025-072022` hit its own `--timeout 25` at 11:45 UTC
while her session was still up, and Claude Code's task notice brought the
result back to her (it did wake her). `mendez-c35-20261025-083040`
(`--timeout 40`) was submitted at 12:30:37 UTC; her turn ended at 12:31;
reap's idle rule (`IDLE_MINUTES`, 20) closed her tab at 12:54, Claude Code
stopped both background shells ("didn't finish before the previous session
ended"), and the run went with them, 24 minutes in. Its log is empty
because an inline run's output went to her shell (`tee`) and a run killed
with it flushed nothing. The next dispatch found the lock free and wrote
`died`, "its process is gone"; `job_finish` told nobody, because an inline
job's end was by design her own turn's to say. She sat off until Number
One looked at 14:21. Not the line's limit (40 minutes, 24 used), not the
memory: the box's `oom_kill` counter is 1 since its boot on 10-16, and the
only `oom-kill` the user journal holds is a Chromium scope on 10-23 (the
kernel log itself needs the `adm` group, which the crew's user lacks).

**`dates.sh`'s time on the synthetic journal** is past CLAUDE.md's 6-15
minutes: 15 minutes for a run that failed early (`070507`), the 25-minute
timeout hit (`072022`), and 24 minutes not yet done (`083040`). The line's
default `--timeout` is 20 (`JOB_TIMEOUT_MIN`), so a bare `job -- dates.sh`
would be killed by it. Proposed, not changed: a default of 45 minutes for
`dates.sh` (the class's own, or the line's `--timeout` hint in the deny
text), once a full run's time on the 4-core VPS is measured.

**Inline jobs are detached.** With the seat, `job_inline` starts the job
in its own unit exactly as a queued job starts (`job_launch`: the spec,
`job-run`, its lock, the cores, its timeout, its result) and only follows
its log to stdout, holding `<id>.waiter`; at the end it records the result
(`job_finish`, `waited`: nothing typed, its turn has it) and exits with the
command's code. The waiter killed - its session ended - the run goes on;
the dispatcher skips an inline job while its waiter holds the lock, and
once the lock is free settles it like any job and types the `[job]` result
to its engineer, which brings them back. Detaching was chosen over
refusing long inline runs (no one knows a command's length before it runs,
and the box was free) and over "inline ends with your turn" (the brief
would have to teach every engineer the 10-minute rule; the code can keep
the promise instead). With the seat off (`LCARS_ENG_SEAT=0`) inline runs
in-process as before. Each `recent` record now says how its engineer was
told: `told` = `inbox` (a `[job]` message), `turn` (the waiter), `no`
(cancelled).

**The watchdog** (`watch`, `engineer.py watch [--dry-run]`) runs at the
end of every `reap` (`lcars-eng-reap.timer`, every five minutes), after
reap's own seat move and dispatch - so a finding is what those did not
fix. It finds and acts on:

- a running job whose process is gone (lock free, past the grace):
  settled `died` and its engineer told (job_dispatch does this too; the
  watchdog makes sure it is said);
- a running job past its whole limit (its timeout, the wait for the cores
  if its log says it waited, five minutes of the unit's margin, five
  more) whose run still holds its lock: killed, `timeout`, told;
- a job that died or timed out in the last hour: said to Number One with
  how its engineer was told;
- a result only an inline waiter had (`told: turn`) whose engineer is off
  and has written nothing since it ended, five minutes on: typed to them
  as a `[job]` message and queued at the head (`told` becomes `inbox`);
- an order (a `crew_inbox` slip) five minutes old for an engineer who is
  off, not seated and not in the line, not dismissed: queued, the seat
  moved;
- the seat free with its line waiting five minutes: moved;
- the one seated silent (`stuck`) or at a question for the 30-minute
  slice plus ten minutes with someone waiting: the rule did not fire;
  moved again, and said.

Every finding goes to Number One once (keyed in `STATE/watchdog.json`, two
days), one `[watchdog]` note per run with a line each - who, what hung,
since when (UTC), what the watchdog did - into the main room, as a crew
message from the ship. `LCARS_WATCH_IDLE_MIN` (5) sets the waits. Tests:
`test_jobs.py`'s `Watchdog` (a dead job, one past its limit and one within
it, an untold result and one seen in a later turn, a stuck order and a
fresh one, the seat free, a silent holder, a dry run) and `Runner`'s
inline cases (a waiter that dies, a waiter left to report).


## As built: the scratchpads (2026-10-25)

**What happened.** Housekeeping's run of 16:01 found swap 79% full (774
of 975MB), 630MB of it tmpfs, and 737MB of /tmp in `/tmp/claude-1000`,
Claude Code's per-session scratch. Memory was not short (4.8GB
available). reap already deleted an ended session's scratch after six
hours (`SCRATCH_KEEP_H`), but kept an engineer's *current* session
however long untouched, because an engineer's claude is stopped between
turns and resumed on the same session: laforge-c34 (307MB), jake-c38
(192MB) and okafor-c30 (105MB), each idle two days, held 604MB that way
- shots, `before`/`after` frame trees, a fetched site, textures. And the
ended sessions it did take were deleted whole: notes, mocks and drafts
went with the shots.

**The rule** (`reap_scratch`, `salvage` in engineer.py; every five
minutes from reap, and from housekeeping's sweep):

- a session's scratch is *split*, never deleted whole: what can be made
  again (`REGEN_EXT`: pictures, video and sound, fonts, models and
  textures, PDFs, archives, logs and test output, `.pyc`, objects and
  ELF executables; anything under `__pycache__`, `node_modules`,
  `.cache`; a symlink, never what it names) is deleted, and everything
  else - notes, scripts, mocks, HTML drafts and reports, JSON, database
  copies - moved to the owner's research folder,
  `~/.local/state/lcars-eng/research/<engineer>/scratch-<date>/<session>/`,
  with its path in the scratch kept (`other/` for a project that is not
  an engineer's worktree). A name taken there gets a `~`; a file that
  cannot be moved stays where it is.
- an ended session (no process holds it, no job names it, no one's
  current one): after `SCRATCH_KEEP_H` (6) hours, as before; the emptied
  directory goes.
- an engineer's current session: after `SCRATCH_IDLE_H`
  (`LCARS_SCRATCH_IDLE_H`, 24) hours untouched, and only while no
  process holds it and no job names it. Its `scratchpad/` stays, with
  `MOVED.txt` saying where the files went, for the engineer when
  resumed; a scratchpad holding only that note is not taken again.
- Number One's sessions, current and past, are never taken (it is
  always on); nor a project a claude with no session record runs in, nor
  anything when the state or the seat cannot be read.

**Seeing it first.** `engineer.py scratch` lists every session's scratch
with its size and what reap does with it (kept and why, or taken, and
how many files would move where), touching nothing; `--apply` does it
now. housekeeping (`--dry-run` too) reports the taken directories and a
"Moved N files" line naming the research folders; its own guard is not
applied to these, since it can only delete whole trees: reap_scratch's
rules are the guard.

**The first pass** (by hand, this branch's `scratch --apply`,
2026-10-25 16:22 UTC): five idle engineers' current sessions taken
(laforge-c34, jake-c38, okafor-c30, kim-c32, torres-c37), 618MB off the
tmpfs, 381 files (38MB) moved to their research folders; number-one,
mendez-c35 and zimmerman-c39 kept. `/tmp/claude-1000` 738MB to 119MB,
/tmp 741MB to 123MB, swap 772MB to 160MB of 975.

