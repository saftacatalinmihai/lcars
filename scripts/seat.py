#!/usr/bin/env python3
"""The seat: one crew Claude Code at a time on this box.

The VPS has 4 cores and 8GB (since 2026-10-14; it had one and 2GB) for the
server, the embedder, the chat and the crew. Memory would now hold several
Claude Codes (200-400MB each), but an engineer's test runs fill the cores:
the full web suite takes all four, and two engineers testing at once would
each run at half speed (docs/ops/engineer-time.md; two seats want 8 cores).
So production's crew take turns in one seat: the deck's engineers (interactive sessions, engineer.py)
and the scheduled roles (`claude -p`, crew.py) alike. Number One is the
exception, always on outside it, so the captain can always reach him.

How the seat moves:

- Whoever is seated works until their turn ends. A message for someone not
  seated waits in their inbox (a crew_inbox entry) and puts them in the
  queue; they are started (resuming their conversation) when the seat comes
  to them, and handed their messages.
- A turn that ends with others queued hands the seat on: the one seated is
  stopped (their conversation, worktree and branch stay) and the next in line
  is started. With nobody queued they keep it, idle, until reap stops them,
  so the loop goes on with the same crew while no one else has work.
- `engineer.py yield <name> [<to>]`: done; the seat passes when this turn
  ends, to <to> (who gets the message on stdin) or whoever is next.
- A turn that ends without a yield leaves them waiting on an answer (a
  question, a report), but one that only answered the ship's note (a
  deploy's outcome, a rollback) is done: nobody asked them anything.
- Nobody is cut off mid-turn for someone else's work: a turn runs to its
  end, however long, and the seat passes then. The captain's message puts
  its engineer first in line, and Number One's queue like anyone's.
- Except on the captain's explicit order: `engineer.py seat-relieve
  [<name>]` (or "preempt": "<name>" set in the entry's JSON block) has the
  one seated interrupted (Esc) and stopped, and back in the queue with a
  note to carry on; <name>, or whoever is first, takes the seat.
- And a holder that is stuck, with others waiting: at a question on screen
  for SLICE (30 minutes), or "working" with no word in its transcript for
  SLICE (a hung tool, a dead process herdr still shows), is relieved the
  same way. One that is working never is. One that is gone ("off") frees
  the seat at once.
- A scheduled role waits its turn in the queue as `crew:<role>` and is never
  cut short: its own timeout bounds it.
- The captain (the console's Queue view) and Number One (`no1.py crew
  queue`) may reorder the line (`move`) and take one out of it (`remove`:
  their undelivered messages cancelled, kept for `restore`, the undo).
  Checked against the line as the editor read it (`Changed`: a 409), and
  only the line: never the one seated, never a turn.

The state is the journal's, not a file's: one entry of kind crew_seat whose
text says who is seated, who is queued and who waits on an answer, over a
JSON block that is the state itself. The captain can read it, and edit the
block (reorder the queue, drop someone); the next move reads it back. A block
that does not parse stops the seat (and says so) rather than being guessed
at. Messages are crew_inbox entries, ticked done when delivered, so a message
can be read, edited or cancelled before it lands. Both kinds are the crew
login's (lcars_logins.h), the same login the scheduled roles post with.

What stays a file, on purpose: the locks. The entries API has no
compare-and-swap, so two hooks firing together would both read "the seat is
free"; every read-modify-write of the entry happens under seat.lock here, and
one mover at a time under seat.run. And the journal is not reachable while
lcars.service restarts (a deploy): a move that meets that fails quietly and
the next one (every five minutes, reap) does it.

This module is the state and the decisions (`step` is pure); engineer.py
gathers the facts and carries the moves out.
"""

import contextlib
import copy
import datetime as dt
import fcntl
import json
import os
import re
import sys
import time
import urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crew_tool as T  # noqa: E402 - the crew login and its HTTP

SEAT_KIND = "crew_seat"
INBOX_KIND = "crew_inbox"
SLICE = int(os.environ.get("LCARS_SEAT_SLICE_MIN") or 30) * 60
LOG_MAX = 20
CREW_PREFIX = "crew:"
# who queues the ship's notes (a deploy finished or failed, a rollback): the
# `by` of their place in line, and the holder's `turn` while answering one
SHIP = "report"


class Down(Exception):
    """The journal did not answer (a restart, a deploy): try again later."""


class Broken(Exception):
    """The seat entry's JSON block does not parse: the captain's to fix."""


class Changed(Exception):
    """The queue is not what the caller saw (a handoff, a new order, another
    edit came first): nothing was changed; read it again."""


# the removals kept for an undo (restore), newest last
REMOVED_MAX = 10


def empty():
    return {"holder": None, "queue": [], "waiting": {}, "preempt": None, "note": "", "log": [], "removed": []}


def is_crew(name):
    return name.startswith(CREW_PREFIX)


# ---- the decisions --------------------------------------------------------------

def log(s, now, text):
    s["log"] = (s.get("log") or [])[-(LOG_MAX - 1):] + [[int(now), text]]


def want(s, name, by, now, pid=None):
    """`name` has work: queue them, unless they hold the seat. The captain's
    word (and a handover) goes to the front; it does not cut the turn of
    the one seated (relieve does, on the captain's order)."""
    s["waiting"].pop(name, None)
    h = s.get("holder")
    if h and h["name"] == name:
        if pid:
            h["pid"] = pid
        # what this turn is for: a person's order outranks the ship's note,
        # whichever came first, so a turn is the ship's only when nothing
        # else was asked of it
        if by != SHIP or not h.get("turn"):
            h["turn"] = by
        return
    q = [e for e in s["queue"] if e["name"] != name]
    e = {"name": name, "t": int(now), "by": by}
    if pid:
        e["pid"] = pid
    if by in ("captain", "handover"):
        q.insert(0, e)
    else:
        # someone already queued keeps their place
        old = next((x for x in s["queue"] if x["name"] == name), None)
        if old:
            return
        q.append(e)
    s["queue"] = q
    log(s, now, f"{name} queued ({by})")


def relieve(s, name, now):
    """The captain's explicit order: cut the turn of the one seated now and
    seat `name` (queued first), or whoever is first in line. False when
    there is nobody to seat."""
    if name:
        want(s, name, "captain", now)
        h = s.get("holder")
        if h and h["name"] == name:
            return False
    if not s["queue"]:
        return False
    s["preempt"] = name or s["queue"][0]["name"]
    log(s, now, f"the captain relieves the seat for {s['preempt']}")
    return True


def drop(s, name, now, why="left the queue"):
    n = len(s["queue"])
    s["queue"] = [e for e in s["queue"] if e["name"] != name]
    if s.get("preempt") == name:
        s["preempt"] = None
    if len(s["queue"]) != n:
        log(s, now, f"{name} {why}")


# The captain's edits of the line, from the Queue view or Number One's
# `crew queue`: the same as editing the block by hand, but checked against
# the line the editor saw. `expect` is that line (names, in order), or None
# not to check: a seat moved on, or another order queued someone, between
# the reading and the press, and the press would land on a line nobody saw.
# Only the queue is touched: the one seated, and their turn, never are.

def _at(s, name, expect):
    if expect is not None and [e["name"] for e in s["queue"]] != list(expect):
        raise Changed("the queue changed since it was read")
    i = next((i for i, e in enumerate(s["queue"]) if e["name"] == name), None)
    if i is None:
        raise Changed(f"{name} is not in the queue (seated, or gone)")
    return i


def move(s, name, to, now, expect=None):
    """`name` one place up or down the line, or to its front. False when
    they are already there."""
    i = _at(s, name, expect)
    j = {"up": i - 1, "down": i + 1, "first": 0}[to]
    j = max(0, min(j, len(s["queue"]) - 1))
    if j == i:
        return False
    s["queue"].insert(j, s["queue"].pop(i))
    log(s, now, f"{name} moved {to} the queue, to #{j + 1}")
    return True


def remove(s, name, now, orders, expect=None):
    """`name` out of the line, and a record of it for restore: where they
    were, their entry, and `orders` - the inbox rows ({id, title}) the
    caller cancels, which a restore makes live again."""
    i = _at(s, name, expect)
    e = s["queue"].pop(i)
    if s.get("preempt") == name:
        s["preempt"] = None
    rec = {"name": name, "at": i, "entry": e, "orders": list(orders), "t": int(now)}
    s["removed"] = (s.get("removed") or [])[-(REMOVED_MAX - 1):] + [rec]
    log(s, now, f"{name} taken out of the queue" + (f", {len(orders)} order{'s' * (len(orders) != 1)} cancelled"
                                                    if orders else ""))
    return rec


def restore(s, name, now):
    """Undo the latest removal (of `name`, or anyone's): back where they
    were in the line - unless an order queued them again meanwhile, which
    moves them there, or they hold the seat. The record, for the caller to
    make its orders live again."""
    rs = s.get("removed") or []
    k = next((k for k in range(len(rs) - 1, -1, -1) if not name or rs[k]["name"] == name), None)
    if k is None:
        raise Changed(f"no removal of {name} to undo" if name else "no removal to undo")
    rec = rs.pop(k)
    n = rec["name"]
    if (s.get("holder") or {}).get("name") != n:
        old = next((e for e in s["queue"] if e["name"] == n), None)
        s["queue"] = [e for e in s["queue"] if e["name"] != n]
        s["queue"].insert(min(rec["at"], len(s["queue"])), old or rec["entry"])
    log(s, now, f"{n} put back in the queue")
    return rec


def turn_ended(s, name, now):
    """The one seated finished a turn. Unless they yielded, they are waiting
    on an answer (a question, a report) - which is what the entry shows.
    Except after a turn that only answered the ship's note (a deploy
    finished or failed, a rollback: `turn` is SHIP): nobody asked them a
    thing, and the line they type is their report, so the turn is over as
    if they had yielded - the next move stands them down and the seat is
    free. A turn after a person's order keeps the rule: ended without a
    yield is how Number One sees a question."""
    h = s.get("holder")
    if not h or h["name"] != name:
        return
    h["idle"] = int(now)
    turn = h.pop("turn", None)
    if h.get("yielded"):
        return
    if turn == SHIP:
        h["yielded"] = int(now)
        s["waiting"].pop(name, None)
        log(s, now, f"{name} is done, a ship's note answered")
        return
    s["waiting"][name] = int(now)


def yielded(s, name, to, now):
    h = s.get("holder")
    if h and h["name"] == name:
        h["yielded"] = int(now)
        s["waiting"].pop(name, None)
        log(s, now, f"{name} is done" + (f", handing over to {to}" if to else ""))
    if to and to != name:
        want(s, to, "handover", now)


def step(s, facts, now):
    """One move: (the new state, the actions to carry out). `facts` maps a
    name to "working", "blocked", "idle" or "off" for an engineer, "alive" or
    "off" for a scheduled role; a name it lacks is off. "stuck" is an
    engineer herdr calls working whose transcript has said nothing for
    SLICE. Actions:
    ("stop", name) - their turn is over, close them; ("relieve", name, why) -
    interrupt a turn, then close them; ("start", name) - start an engineer
    and hand them their inbox; ("grant", name) - a waiting scheduled role
    may run. Pure: the caller does the doing."""
    s = copy.deepcopy(s)
    acts = []
    # scheduled roles that stopped waiting (killed, timed out) leave the queue
    for e in list(s["queue"]):
        if is_crew(e["name"]) and facts.get(e["name"], "off") == "off":
            drop(s, e["name"], now, "gave up waiting")
    h = s.get("holder")
    if h and facts.get(h["name"]) in ("working", "stuck"):
        # at it again (a message, the captain in the Claude app): not idle,
        # not waiting on anyone
        h.pop("idle", None)
        s["waiting"].pop(h["name"], None)
    # since when the one seated has sat at a question: the clock for
    # calling them stuck, which only a move every few minutes (reap) reads
    if h and facts.get(h["name"]) == "blocked":
        h.setdefault("blocked", int(now))
    elif h:
        h.pop("blocked", None)
    if h and facts.get(h["name"], "off") == "off":
        log(s, now, f"{h['name']} left the seat")
        s["holder"] = h = None
    if h and h.get("yielded") and not is_crew(h["name"]) and facts.get(h["name"]) == "idle":
        acts.append(("stop", h["name"]))
        log(s, now, f"{h['name']} stood down, done")
        s["holder"] = h = None
    if not s["queue"]:
        return s, acts
    if h:
        f = facts.get(h["name"])
        if is_crew(h["name"]):
            return s, acts  # a scheduled run is never cut; its timeout bounds it
        if f == "idle":
            acts.append(("stop", h["name"]))
            log(s, now, f"{h['name']} stood down for {s['queue'][0]['name']}")
        elif s.get("preempt") or f == "stuck" or (f == "blocked" and now - h["blocked"] >= SLICE):
            why = (f"the captain's order, for {s['preempt']}" if s.get("preempt")
                   else f"no sign of work for {SLICE // 60} minutes" if f == "stuck"
                   else f"at a question for {(now - h['blocked']) // 60:.0f} minutes")
            acts.append(("relieve", h["name"], why))
            log(s, now, f"{h['name']} relieved mid-turn: {why}")
            # back in line, to carry on where they stopped
            s["queue"].append({"name": h["name"], "t": int(now), "by": "relieved"})
        else:
            return s, acts
        s["waiting"].pop(h["name"], None)
        s["holder"] = None
    nxt = s["queue"].pop(0)
    if s.get("preempt") == nxt["name"]:
        s["preempt"] = None
    s["waiting"].pop(nxt["name"], None)
    s["holder"] = {"name": nxt["name"], "since": int(now), "by": nxt.get("by", ""), "turn": nxt.get("by", "")}
    if nxt.get("pid"):
        s["holder"]["pid"] = nxt["pid"]
    acts.append(("grant" if is_crew(nxt["name"]) else "start", nxt["name"]))
    log(s, now, f"{nxt['name']} seated ({nxt.get('by', '')})")
    return s, acts


def normal(s):
    """A state read back from the entry, which the captain may have edited:
    every field present and of its type, the queue without duplicates or
    the holder."""
    if not isinstance(s, dict):
        raise Broken("the JSON block is not an object")
    out = empty()
    h = s.get("holder")
    if isinstance(h, dict) and isinstance(h.get("name"), str) and h["name"]:
        out["holder"] = dict(h, since=int(h.get("since") or time.time()))
    seen = {out["holder"]["name"]} if out["holder"] else set()
    for e in s.get("queue") or []:
        if isinstance(e, str):
            e = {"name": e}
        if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"] and e["name"] not in seen:
            seen.add(e["name"])
            out["queue"].append(dict(e, t=int(e.get("t") or time.time()), by=str(e.get("by") or "captain")))
    w = s.get("waiting")
    out["waiting"] = {k: int(v) for k, v in w.items() if isinstance(v, (int, float))} if isinstance(w, dict) else {}
    p = s.get("preempt")
    out["preempt"] = p if isinstance(p, str) and any(e["name"] == p for e in out["queue"]) else None
    out["note"] = str(s.get("note") or "")
    out["log"] = [x for x in (s.get("log") or []) if isinstance(x, list) and len(x) == 2][-LOG_MAX:]
    out["removed"] = [r for r in (s.get("removed") or []) if isinstance(r, dict) and isinstance(r.get("name"), str)
                      and isinstance(r.get("entry"), dict) and isinstance(r.get("at"), int)
                      and isinstance(r.get("orders"), list)][-REMOVED_MAX:]
    return out


# ---- the entry -----------------------------------------------------------------

BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def when(t):
    """A time in the captain's zone, as the crew reports give it."""
    return dt.datetime.fromtimestamp(t, T.TZ).strftime("%a %H:%M")


def render(s, now, host=""):
    """(title, content) of the seat entry: what a person reads, then the
    state as a JSON block, which is what is read back."""
    h = s.get("holder")
    q = s.get("queue") or []
    if h:
        title = f"Seat: {h['name']}" + (f" · {len(q)} waiting" if q else "")
    else:
        title = "Seat: empty" + (f" · {len(q)} waiting" if q else "")
    lines = [f"The crew's one Claude Code seat{' on ' + host if host else ''}: they take turns in it, and Number "
             "One is always on, outside it. To change the queue, edit the JSON block at the bottom; the next "
             "move reads it back.", ""]
    if h:
        mins = max(0, int(now - h["since"]) // 60)
        st = "done, standing down" if h.get("yielded") else "between turns" if h.get("idle") else "working"
        lines.append(f"- **Seated:** {h['name']}, since {when(h['since'])} ({mins} min), {st}")
    else:
        lines.append("- **Seated:** nobody")
    if q:
        lines.append("- **Queue:** " + " · ".join(f"{i + 1}. {e['name']} ({e.get('by', '')}, {when(e['t'])})"
                                                   for i, e in enumerate(q)))
    if s.get("waiting"):
        lines.append("- **Waiting on an answer:** " + ", ".join(f"{k} (since {when(v)})"
                                                               for k, v in sorted(s["waiting"].items())))
    if s.get("note"):
        lines.append(f"- **Note:** {s['note']}")
    if s.get("log"):
        lines += ["", "Recent:"] + [f"- {when(t)} {x}" for t, x in reversed(s["log"][-10:])]
    lines += ["", "```json", json.dumps(s, indent=1, ensure_ascii=False), "```"]
    return title, "\n".join(lines)


def _http(method, path, body=None):
    status, text = T.http(method, path, body, timeout=20)
    if status == 0 or status >= 500:
        raise Down(f"{method} {path.split('?')[0]}: {status or text[:200]}")
    if status >= 300:
        raise RuntimeError(f"{method} {path.split('?')[0]}: {status} {text[:300]}")
    try:
        return json.loads(text)
    except ValueError:
        return None


def read():
    """(entry id or None, state). The oldest crew_seat entry is the seat; a
    deleted one is simply made again."""
    rows = _http("GET", "/entries?" + urllib.parse.urlencode(
        {"kind": SEAT_KIND, "order": "id", "dir": "asc", "limit": 1, "content": 1}))
    if not rows:
        return None, empty()
    row = rows[0]
    m = BLOCK_RE.findall(row.get("content") or "")
    if not m:
        raise Broken(f"the seat entry #{row['id']} has no ```json block")
    try:
        return row["id"], normal(json.loads(m[-1]))
    except ValueError as e:
        raise Broken(f"the seat entry #{row['id']}'s JSON block does not parse: {e}")


def write(rid, s, now, host=""):
    title, content = render(s, now, host)
    if rid is None:
        r = _http("POST", "/entries", {"kind": SEAT_KIND, "title": title, "content": content})
        return (r or {}).get("id")
    _http("PUT", f"/entries/{rid}", {"title": title, "content": content})
    return rid


# ---- the inbox -----------------------------------------------------------------

FRESH = " [fresh]"


def inbox_title(to, sender, text, fresh=False):
    first = (text.strip().splitlines() or [""])[0]
    return f"{to} ← {sender}{FRESH if fresh else ''}: {first[:90]}"


def inbox_add(to, sender, text, fresh=False):
    """A message for `to`. `fresh`: an order for a new task, delivered into a
    cleared conversation - marked on the title (the content is what is
    typed), where the captain can see it and take it off."""
    r = _http("POST", "/entries", {"kind": INBOX_KIND, "title": inbox_title(to, sender, text, fresh),
                                   "content": text})
    return (r or {}).get("id")


def inbox_fresh(row):
    """Whether an inbox row asks for a cleared conversation: the mark is on
    the sender, before the title's first ": " (the text after it may say
    anything)."""
    t = row.get("title") or ""
    head = t[t.find(" ← ") + 3:].split(": ", 1)[0] if " ← " in t else ""
    return head.endswith(FRESH)


def inbox_all():
    """Every undelivered message, oldest first: crew_inbox rows not done."""
    rows = _http("GET", "/entries?" + urllib.parse.urlencode(
        {"kind": INBOX_KIND, "done": 0, "order": "id", "dir": "asc", "limit": 200, "content": 1})) or []
    return [r for r in rows if not r.get("deleted")]


def inbox_delivered(limit=300):
    """The latest delivered messages, newest first (titles and times, no
    content): when an order was given, for the Queue view's times."""
    rows = _http("GET", "/entries?" + urllib.parse.urlencode(
        {"kind": INBOX_KIND, "done": 1, "order": "id", "dir": "desc", "limit": limit})) or []
    return [r for r in rows if not r.get("deleted")]


def inbox_to(row):
    """(to, sender) from an inbox row's title, "to ← sender[ [fresh]]: …"."""
    t = row.get("title") or ""
    if " ← " not in t:
        return "", ""
    to, rest = t.split(" ← ", 1)
    sender = rest.split(": ", 1)[0]
    return to, sender[:-len(FRESH)] if sender.endswith(FRESH) else sender


# The mark a sender's message is typed with, so the one it reaches knows whose
# word it is (Number One's orders put them under its watch, engineer.py)
MARKS = {"No.1": "[No.1]"}


def inbox_text(row):
    """What delivery types for an inbox row: its content as the entry holds
    it now, read at delivery (inbox_all), never a copy from when it was
    queued - the captain may have edited the order in the meantime (the
    console's Inbox, Open). A mark his edit took off is put back."""
    text = (row.get("content") or "").strip()
    mark = MARKS.get(inbox_to(row)[1], "")
    if text and mark and not text.startswith(mark):
        text = mark + " " + text
    return text


def inbox(to):
    """`to`'s undelivered messages, oldest first: crew_inbox rows not done
    whose title names them."""
    pre = to + " ← "
    return [r for r in inbox_all() if (r.get("title") or "").startswith(pre)]


def inbox_done(rid):
    _http("PUT", f"/entries/{rid}", {"done_bool": 1})


# A cancelled message: ticked done, never delivered, and its title marked
# so - before the name, so inbox_to no longer reads it as theirs (the Queue
# view's times count delivered orders)
CANCELLED = "[cancelled] "


def inbox_cancel(row):
    _http("PUT", f"/entries/{row['id']}", {"done_bool": 1, "title": CANCELLED + row["title"]})


def inbox_uncancel(row):
    """`row` as inbox_cancel had it: {id, title} before the mark."""
    _http("PUT", f"/entries/{row['id']}", {"done_bool": 0, "title": row["title"]})


# ---- the locks -----------------------------------------------------------------

@contextlib.contextmanager
def locked(state_dir, which="seat.lock"):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, which), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


@contextlib.contextmanager
def changing(state_dir, host=""):
    """Read the entry, let the caller change the state, write it back if it
    changed - all under the lock. Yields the state (a dict to mutate)."""
    with locked(state_dir):
        rid, s = read()
        before = json.dumps(s, sort_keys=True)
        yield s
        if json.dumps(s, sort_keys=True) != before or rid is None:
            write(rid, s, time.time(), host)
