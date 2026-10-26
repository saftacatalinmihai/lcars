#!/usr/bin/env python3
"""The seat's and the job line's metrics, for Grafana (docs/ops/seat-metrics.md).

engineer.py and seat.py call this at each event - an order given, the seat
taken, a turn's end, a job's end, a deploy's, an inbox row delivered - and
it keeps the counters and histogram buckets in a small state file and
renders them, with the latest gauges, as a Prometheus text file:

    <engineer state>/metrics/state.json    the memory: cumulative, never reset
    <engineer state>/metrics/metrics.prom  what GET /metrics appends
    <engineer state>/metrics/lock          one writer at a time

lcars_metrics.h appends metrics.prom to the journal's own numbers, as
node_exporter's textfile collector does, with its mtime as
lcars_eng_metrics_timestamp_seconds, so a file nobody has rendered for a
while shows as stale in Grafana instead of as a flat line. Gauges are what
the last event (or reap, every five minutes) saw.

Why a file and not the journal, as the crew's state usually is: these are
counters a scrape reads every minute, written at every seat move; an entry
per move would be noise in the captain's journal, and the server must read
it without a database query. Counters survive restarts because the file is
their memory; a state file that does not parse is moved aside and they
start again from zero, which Prometheus' rate() reads as a counter reset.

Cardinality is kept low on purpose: a name label only on the gauge of each
engineer's context, outcomes a fixed set (an unknown one is "other"), and
no labels on histograms but an outcome where the order asked for one.
Every metric is declared, with HELP and TYPE, even before its first event,
and every outcome's counter starts at 0, so rate() and increase() see the
first one.

Nothing here may break what calls it: every entry point swallows its own
errors (record), since a metric is never worth a lost seat move.
"""

import calendar
import contextlib
import fcntl
import json
import math
import os
import sys
import time

# seconds: from a quick delivery to a long task; this box's turns run 2 to
# 30 minutes, a three-feature task an hour or two, a deploy 3 to 10 minutes
BUCKETS = (10, 30, 60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200)

TURN_OUTCOMES = ("report", "question", "job", "stuck", "stopped")
JOB_OUTCOMES = ("passed", "failed", "timeout", "died", "refused", "cancelled")
DEPLOY_OUTCOMES = ("done", "failed")

# name: (help, label, the label's fixed values or None)
COUNTERS = {
    "lcars_orders_total": ("Orders given to the crew (the captain's and Number One's messages to an engineer).",
                           None, None),
    "lcars_seat_turns_total": ("Turns in the seat ended, by how: report (yielded), question (ended without a "
                               "yield), job (yielded to a heavy job queued), stuck (relieved for no sign of work), stopped (the captain's relieve).",
                               "outcome", TURN_OUTCOMES),
    "lcars_jobs_total": ("Heavy jobs ended, by outcome.", "outcome", JOB_OUTCOMES),
    "lcars_deploys_total": ("Deploys ended, by outcome.", "outcome", DEPLOY_OUTCOMES),
    "lcars_rollbacks_total": ("Rollbacks that went live.", None, None),
}
HISTOGRAMS = {
    "lcars_seat_wait_seconds": ("From a place in the seat's line to the seat.", None, None),
    "lcars_seat_turn_seconds": ("One turn in the seat, from its prompt to its end.", None, None),
    "lcars_job_wait_seconds": ("A heavy job from submitted to started.", None, None),
    "lcars_job_run_seconds": ("A heavy job's run, by outcome.", "outcome", JOB_OUTCOMES),
    "lcars_task_seconds": ("A task, from its order to the engineer's report (the turn that yields).", None, None),
    "lcars_deploy_seconds": ("A deploy, from its start to its end, by outcome.", "outcome", DEPLOY_OUTCOMES),
    "lcars_inbox_delivery_seconds": ("A crew_inbox message from written to typed into its session.", None, None),
}
GAUGES = {
    "lcars_seat_queue_length": ("Engineers and roles waiting in the seat's line.", None),
    "lcars_seat_held": ("1 while someone holds the seat.", None),
    "lcars_seat_waiting_answer": ("Engineers whose turn ended waiting on an answer.", None),
    "lcars_engineers_on_duty": ("Engineers with a running session (Number One included).", None),
    "lcars_engineers_working": ("Engineers whose session is at work.", None),
    "lcars_jobs_queued": ("Heavy jobs waiting in the job line.", None),
    "lcars_jobs_running": ("Heavy jobs running.", None),
    "lcars_deploy_running": ("1 while a deploy or rollback runs.", None),
    "lcars_no1_inbox_pending": ("Notes for Number One not yet typed to it.", None),
    "lcars_engineer_ctx_tokens": ("Each running engineer's context size in tokens.", "name"),
}

STATE_V = 1


def dir_of(state_dir):
    return os.path.join(state_dir, "metrics")


def empty():
    return {"v": STATE_V, "counters": {}, "hist": {}, "gauges": {}}


def load(d):
    """The state in `d`, or an empty one; a file that does not parse is kept
    aside (state.json.bad) rather than written over unread."""
    p = os.path.join(d, "state.json")
    try:
        with open(p) as f:
            s = json.load(f)
        if isinstance(s, dict) and s.get("v") == STATE_V:
            for k in ("counters", "hist", "gauges"):
                if not isinstance(s.get(k), dict):
                    s[k] = {}
            return s
    except FileNotFoundError:
        return empty()
    except (OSError, ValueError):
        pass
    with contextlib.suppress(OSError):
        os.replace(p, p + ".bad")
    return empty()


def write_atomic(path, text):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def label_value(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def num(v):
    if isinstance(v, float) and not math.isfinite(v):
        return "+Inf" if v > 0 else "-Inf" if v < 0 else "NaN"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(int(v))


def fixed(value, allowed):
    """An outcome from the fixed set, else "other": an outcome is never free text."""
    return value if value in allowed else "other"


def render(s):
    """The text format: every declared metric, HELP and TYPE first, its
    samples together; series sorted, so an unchanged state renders the
    same bytes."""
    out = []
    for name, (help_, label, values) in COUNTERS.items():
        out += [f"# HELP {name} {help_}", f"# TYPE {name} counter"]
        have = s["counters"].get(name) or {}
        if label is None:
            out.append(f"{name} {num(have.get('', 0))}")
            continue
        for v in sorted(set(values) | set(have)):
            out.append(f'{name}{{{label}="{label_value(v)}"}} {num(have.get(v, 0))}')
    for name, (help_, label, values) in HISTOGRAMS.items():
        out += [f"# HELP {name} {help_}", f"# TYPE {name} histogram"]
        have = s["hist"].get(name) or {}
        keys = [""] if label is None else sorted(set(values) | set(have))
        for v in keys:
            h = have.get(v) or {}
            counts = h.get("b") or [0] * len(BUCKETS)
            lab = f'{label}="{label_value(v)}",' if label else ""
            for le, c in zip(BUCKETS, counts):
                out.append(f'{name}_bucket{{{lab}le="{le}"}} {num(c)}')
            out.append(f'{name}_bucket{{{lab}le="+Inf"}} {num(h.get("count", 0))}')
            base = f"{{{lab[:-1]}}}" if lab else ""
            out.append(f"{name}_sum{base} {num(float(h.get('sum', 0)))}")
            out.append(f"{name}_count{base} {num(h.get('count', 0))}")
    for name, (help_, label) in GAUGES.items():
        out += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
        have = s["gauges"].get(name)
        if label is None:
            out.append(f"{name} {num(have if isinstance(have, (int, float)) else 0)}")
            continue
        for v, x in sorted((have or {}).items()):
            out.append(f'{name}{{{label}="{label_value(v)}"}} {num(x)}')
    return "\n".join(out) + "\n"


def inc(s, name, outcome=None, by=1):
    _, label, values = COUNTERS[name]
    key = "" if label is None else fixed(outcome, values)
    c = s["counters"].setdefault(name, {})
    c[key] = c.get(key, 0) + by


def observe(s, name, secs, outcome=None):
    """One sample into a histogram. A negative duration (a clock stepped
    back, a stale start) is not a measurement: dropped."""
    _, label, values = HISTOGRAMS[name]
    if secs is None or secs < 0 or not math.isfinite(secs):
        return
    key = "" if label is None else fixed(outcome, values)
    h = s["hist"].setdefault(name, {}).setdefault(key, {"b": [0] * len(BUCKETS), "sum": 0.0, "count": 0})
    if len(h.get("b") or []) != len(BUCKETS):
        h["b"] = [0] * len(BUCKETS)  # a state from another bucket set: its counts are not these
    for i, le in enumerate(BUCKETS):
        if secs <= le:
            h["b"][i] += 1
    h["sum"] = float(h.get("sum", 0)) + float(secs)
    h["count"] = h.get("count", 0) + 1


def gauge(s, name, value):
    """A gauge's value now: a number, or for a labelled one {label value: number}
    (which replaces every series: an engineer gone off duty drops out)."""
    _, label = GAUGES[name]
    s["gauges"][name] = dict(value) if label else value


@contextlib.contextmanager
def changing(state_dir):
    """The state under the lock, written back and rendered when the caller is done."""
    d = dir_of(state_dir)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        s = load(d)
        yield s
        write_atomic(os.path.join(d, "state.json"), json.dumps(s, sort_keys=True))
        write_atomic(os.path.join(d, "metrics.prom"), render(s))


def record(state_dir, fn):
    """Run fn(state) under the lock; never raises (a metric lost is logged)."""
    try:
        with changing(state_dir) as s:
            fn(s)
    except Exception as e:  # noqa: BLE001 - see the module's last paragraph
        print(f"eng_metrics: {type(e).__name__}: {e}", file=sys.stderr)


def seat_gauges(s, seat):
    """The gauges a seat state (seat.py's block) holds."""
    j = seat.get("jobs") or {}
    gauge(s, "lcars_seat_queue_length", len(seat.get("queue") or []))
    gauge(s, "lcars_seat_held", 1 if seat.get("holder") else 0)
    gauge(s, "lcars_seat_waiting_answer", len(seat.get("waiting") or {}))
    gauge(s, "lcars_jobs_queued", len(j.get("queue") or []))
    gauge(s, "lcars_jobs_running", len(j.get("running") or []))


def utc_seconds(s):
    """A row's created_at_utc as unix seconds, or None."""
    try:
        return calendar.timegm(time.strptime(s or "", "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None
