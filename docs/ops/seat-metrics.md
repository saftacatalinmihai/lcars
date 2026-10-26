# The seat's and the job line's metrics

How long a task takes, and where the time goes, in Grafana: the crew's
seat, the heavy-job line and the deploys, exported through `GET /metrics`
beside the journal's readings, scraped by the Grafana Alloy on the VPS
(`scripts/metrics-setup.sh`, job `lcars`) and sent to Grafana Cloud.

## How it works

- `scripts/eng_metrics.py` keeps the counters and histogram buckets in
  `~/.local/state/lcars-eng/metrics/state.json` (cumulative, never reset:
  the file is their memory across restarts) and renders
  `metrics/metrics.prom` beside it, atomically, at every event. One writer at
  a time (`metrics/lock`). A metric never fails its caller.
- `engineer.py` and `seat.py` feed it: an order given (`cmd_say`), the seat
  taken (`seat_move`), a turn's start (the `UserPromptSubmit` hook,
  `turn-began`) and end (`seat-turn-ended`), a relieve, a job's end
  (`job_finish`, `job-cancel`), a deploy's or rollback's end, an inbox row
  typed in (`seat_deliver`, `no1-flush`). Every write of the seat entry
  refreshes the seat and job gauges; reap, every five minutes, takes a
  census (on duty, working, each one's context, a deploy running, Number
  One's inbox) and rewrites the file, so its mtime is a heartbeat.
- `lcars_metrics.h` appends the file to `/metrics` as it stands (as
  node_exporter's textfile collector does), after
  `lcars_eng_metrics_timestamp_seconds`, the file's mtime. No file (a box
  without the crew): nothing appended, no timestamp. The path:
  `$LCARS_ENG_METRICS`, else `$LCARS_ENG_STATE/metrics/metrics.prom`, else
  `~/.local/state/lcars-eng/metrics/metrics.prom`; `LCARS_ENG_METRICS=` (empty)
  turns it off.

## The metrics

Gauges (what the last event or census saw):

| metric | meaning |
|---|---|
| `lcars_seat_queue_length` | engineers and roles waiting in the seat's line |
| `lcars_seat_held` | 1 while someone holds the seat |
| `lcars_seat_waiting_answer` | engineers whose turn ended waiting on an answer |
| `lcars_engineers_on_duty` | running sessions (Number One included) |
| `lcars_engineers_working` | sessions at work |
| `lcars_jobs_queued`, `lcars_jobs_running` | the heavy-job line |
| `lcars_deploy_running` | 1 while a deploy or rollback runs |
| `lcars_no1_inbox_pending` | notes for Number One not yet typed to it |
| `lcars_engineer_ctx_tokens{name}` | each running engineer's context size |
| `lcars_eng_metrics_timestamp_seconds` | when the file was written (the server's) |

Counters:

| metric | labels |
|---|---|
| `lcars_orders_total` | - (the captain's and Number One's messages to an engineer) |
| `lcars_seat_turns_total{outcome}` | `report` (yielded), `question` (ended without a yield), `job` (yielded to a queued heavy job), `stuck` (relieved: no sign of work, or a question left 30 minutes), `stopped` (the captain's relieve) |
| `lcars_jobs_total{outcome}` | `passed`, `failed`, `timeout`, `died` (OOM, a reboot), `refused` (the tree moved), `cancelled` |
| `lcars_deploys_total{outcome}` | `done`, `failed` |
| `lcars_rollbacks_total` | rollbacks that went live |

Histograms, in seconds, buckets 10, 30, 60, 120, 300, 600, 900, 1200, 1800,
2700, 3600, 5400, 7200 (+Inf):

| metric | from - to |
|---|---|
| `lcars_task_seconds` | an order (the first of a task, queued or typed) to the report: the turn that yields. A question keeps the task open; a fresh order starts a new one |
| `lcars_seat_wait_seconds` | a place in the seat's line to the seat |
| `lcars_seat_turn_seconds` | a turn's first prompt to its end (or its relieve) |
| `lcars_job_wait_seconds` | a job submitted to started |
| `lcars_job_run_seconds{outcome}` | a job's run |
| `lcars_deploy_seconds{outcome}` | a deploy's run, its wait for the engineer's turn included |
| `lcars_inbox_delivery_seconds` | a crew_inbox row written to typed into its session |

Cardinality stays low: a name label only on the context gauge, outcomes a
fixed set (anything else is `other`), every outcome's series there from 0.

Departures from the order, and why: a `job` turn outcome (a turn that ends
by queuing a heavy job is not a report, and counting it as one would close
the task early); a `died` job outcome (an OOM kill is not a test failure);
a 10 s bucket below the 30 s one (an inbox note to an idle engineer lands
in seconds; without it every delivery is in the first bucket).

## PromQL for the captain's questions

A histogram's quantile is interpolated inside its bucket: with a few tasks a
day, read p50/p90 as "within this bucket", and the mean (sum over count) as
the exact figure.

- Task time, p50 and p90 over a day:
  `histogram_quantile(0.5, sum by (le) (increase(lcars_task_seconds_bucket{job="lcars"}[1d])))`
  and the same with `0.9`; the mean:
  `increase(lcars_task_seconds_sum{job="lcars"}[1d]) / increase(lcars_task_seconds_count{job="lcars"}[1d])`
- Time waiting for the seat: p50/p90 as above with
  `lcars_seat_wait_seconds`; the total waited in a day:
  `increase(lcars_seat_wait_seconds_sum{job="lcars"}[1d])`
- Queue length over time: `lcars_seat_queue_length{job="lcars"}` (and
  `max_over_time(lcars_seat_queue_length{job="lcars"}[1h])` for the peaks;
  `lcars_jobs_queued` for the job line)
- Job outcomes: `sum by (outcome) (increase(lcars_jobs_total{job="lcars"}[1d]))`;
  run time p90 by outcome:
  `histogram_quantile(0.9, sum by (le, outcome) (increase(lcars_job_run_seconds_bucket{job="lcars"}[1d])))`
- Deploy time: `histogram_quantile(0.9, sum by (le) (increase(lcars_deploy_seconds_bucket{job="lcars",outcome="done"}[7d])))`;
  deploys per day: `sum by (outcome) (increase(lcars_deploys_total{job="lcars"}[1d]))`
- Is it alive: `time() - lcars_eng_metrics_timestamp_seconds{job="lcars"}`
  over 600 means reap has not run for two rounds.

## The dashboard

`docs/ops/grafana-seat-dashboard.json`: Dashboards, New, Import, upload
it, and pick the Grafana Cloud Prometheus data source. Fifteen panels: task
time p50/p90, seat wait, the file's age, task and seat-wait time over a
rolling day, the seat line, the job line, job outcomes, job wait and run,
deploy time, deploys and rollbacks, turns by outcome, turn and delivery
time, context per engineer.

Tests: `lcars-ui/test/metrics.py` (the file appended, missing, stale, over
the cap, off) and `scripts/test_metrics_eng.py` (the state and the events).
