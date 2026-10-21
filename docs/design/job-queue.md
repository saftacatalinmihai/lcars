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
`PERF=0`, and `--changed` when it picks QuickJS, keyboard or perf),
`perf.py`, `buttons.py`, `qa_chat.py`, `keyboard.py` and its shards,
`dates.sh`, `architect.py`, `deckvoice.py`, `editor.py`, `classified.py`,
`deckshots.py`, `shots.py`, `scripts/deck-models/build.sh` (the rooms),
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
`classified.py`, `deckshots.py`, `shots.py`, `deck-models/build.sh`, or
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
