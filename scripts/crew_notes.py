#!/usr/bin/env python3
"""Crew notes: `@yeoman log a gym session`, a line in one of the captain's
entries, answered by that crew role (docs/design/crew-notes.md).

    crew.py notes watch        the watcher (lcars-crew-notes.service)
    crew.py note <thread id>   one turn of a thread, under the crew lock

The pieces, and why each is so:

- **A note** is a line of the captain's whose first word, after an optional
  list bullet, is `@<role>` naming a crew/<role>.md with a `notes:` key,
  then the order; lines indented under it belong to it. Not in a code
  fence, not in a `>` quote (where a role's own appended text lives, and
  where the captain quotes), not mid-sentence. `note_scan` is the rule, and
  the page's `noteScan` is its copy: test_crew_notes checks them on one
  table.
- **A thread** is one crew_note entry per (entry, role): the crew login's
  own kind, so the runner may write it and nothing else of the captain's.
  Its content is a header (`status:`, `entry:`, `role:`) and the turns as
  `### Captain · <time> · note <hash>` / `### <Role> · <time>` sections. A
  note is taken once: its hash (FNV-1a over the role and its words, which
  the page can compute too without crypto.subtle) in a captain turn is the
  record that it was. The state is in the journal, so the queue is too:
  a thread whose status is `queued` is work, whoever wrote it (the watcher,
  or the page's Reply and Retry).
- **The watcher** holds GET /events as the crew login and on every change
  asks /dump?modified_since=<mark>: only what moved, never the whole
  journal. A note is ripe once its entry has been quiet for QUIET seconds
  (the editor autosaves mid-word); an unripe one is re-read when it ripens
  and holds the mark back, so a restart in between finds it again. Runs go
  one at a time to a worker that calls `crew.py note`, which takes the
  crew's lock and seat like any run.
- **A turn** (`run_note`) gives the role its entry and the thread, fenced as
  journal data; only the captain's turns are orders. The answer is put in
  after the turn it answers, so a reply that lands mid-run is kept and
  taken next.
- **@no1 and @<engineer>** (0.256.0) are notes to people, not to a crew
  role: `@no1`, or the stem, slug or surname of one of the ten most
  recently active engineers (`engineer.py note-names`). The watcher does
  not run a turn for them: it types the order to Number One's inbox or the
  engineer's session (`engineer.py no1-send`, `say`), marked `[captain]`
  and carrying `(crew note #<thread>)`, and is done. The answer is the last
  message of the turn that took it, which their own Stop hook appends to
  the thread (`engineer.py note-answer`, `note_answer` here), however long
  the turn. A dismissed engineer's note is answered in place.
"""

import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crew_tool as T  # noqa: E402

KIND = "crew_note"
QUIET = float(os.environ.get("LCARS_NOTES_QUIET") or 20)
# Kinds a note is never read from: the limited logins' own (a role's answer
# quoting "@yeoman" must not start another), their reminders (<task>_crew,
# <task>_no1 and their lists: the task role's, kinds.md 2.3), and the
# frozen imports.
def not_from(k):
    k = k or ""
    if k.startswith(("crew_", "no1_")):
        return True
    for p in (T.roles().ask("crew"), T.roles().ask("no1")):
        if k == p or k.startswith(p + "_"):
            return True
    return False
STATUSES = ("queued", "working", "answered", "failed")
# A turn's cut: the first (what the thread is about) and the last few
KEEP_TURNS = 6
TURN_MAX = 4000
ENTRY_MAX = 12000

# The role is matched without case ("@Torres", a phone's capital at a line's
# start), and is its lower case from then on: the thread's key and the hash
NOTE_RE = re.compile(r"^([ \t]*)(?:[-*+][ \t]+)?@([A-Za-z][A-Za-z0-9-]{0,30})[ \t]+(\S.*)$")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
QUOTE_RE = re.compile(r"^[ \t]*>")
TURN_RE = re.compile(r"^### (.+?) · (\d{4}-\d{2}-\d{2} \d{2}:\d{2})(?: · (note ([0-9a-f]{8})|reply))?[ \t]*$")


def fnv(text):
    """FNV-1a 32 over UTF-8, 8 hex digits: the page computes the same."""
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def _indent(s):
    return len(s.expandtabs(2)) - len(s.expandtabs(2).lstrip())


def note_scan(text, roles):
    """[{role, text, hash, line}] for each note in `text` to a role in `roles`."""
    out, fence = [], False
    lines = (text or "").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if FENCE_RE.match(ln):
            fence = not fence
            continue
        if fence or QUOTE_RE.match(ln):
            continue
        m = NOTE_RE.match(ln)
        role = m.group(2).lower() if m else ""
        if not m or role not in roles:
            continue
        ind, words = _indent(ln), [m.group(3).strip()]
        while i < len(lines) and lines[i].strip() and _indent(lines[i]) > ind \
                and not QUOTE_RE.match(lines[i]) and not FENCE_RE.match(lines[i]):
            words.append(lines[i].strip())
            i += 1
        body = "\n".join(words)
        out.append({"role": role, "text": body, "line": i - len(words),
                    "hash": fnv(role + " " + " ".join(body.split()))})
    return out


def eligible(row):
    k = row.get("kind") or ""
    return not row.get("deleted") and not not_from(k) and k not in T.IMPORTED_KINDS


# ---- threads -----------------------------------------------------------------

def parse_thread(content):
    """{status, why, entry, role, turns: [{who, at, hash, reply, text}]};
    a thread to Number One or an engineer has `to` (their engineer name)
    and `sent` (how many of the captain's turns were typed to them) too."""
    head, _, rest = (content or "").partition("\n\n")
    t = {"status": "", "why": "", "entry": 0, "role": "", "turns": []}
    for ln in head.splitlines():
        k, colon, v = ln.partition(":")
        k, v = k.strip(), v.strip()
        if not colon:
            continue
        if k == "status":
            s, _, why = v.partition(":")
            t["status"], t["why"] = s.strip(), why.strip()
        elif k == "entry":
            t["entry"] = int(v.lstrip("#") or 0) if v.lstrip("#").isdigit() else 0
        elif k == "role":
            t["role"] = v
        elif k == "to":
            t["to"] = v
        elif k == "sent":
            t["sent"] = int(v) if v.isdigit() else 0
    cur = None
    for ln in rest.split("\n"):
        m = TURN_RE.match(ln)
        if m:
            cur = {"who": m.group(1), "at": m.group(2), "hash": m.group(4) or "",
                   "reply": m.group(3) == "reply", "lines": []}
            t["turns"].append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    for x in t["turns"]:
        x["text"] = "\n".join(x.pop("lines")).strip()
    return t


def render_thread(t):
    st = t["status"] + (": " + t["why"] if t.get("why") else "")
    out = [f"status: {st}", f"entry: #{t['entry']}", f"role: {t['role']}"]
    if t.get("to"):
        out += [f"to: {t['to']}", f"sent: {int(t.get('sent') or 0)}"]
    out.append("")
    for x in t["turns"]:
        tag = f" · note {x['hash']}" if x.get("hash") else " · reply" if x.get("reply") else ""
        out += [f"### {x['who']} · {x['at']}{tag}", x["text"], ""]
    return "\n".join(out).rstrip() + "\n"


def captain(x):
    return x["who"] == "Captain"


def next_status(t):
    """queued while a captain turn waits for an answer after the last
    answer, else answered."""
    last = t["turns"][-1] if t["turns"] else None
    return "queued" if last and captain(last) else "answered"


def stamp_now():
    return T.now_local().strftime("%Y-%m-%d %H:%M")


def role_name(fm):
    return fm["title"].split(",")[0].strip() or fm["role"].capitalize()


def get_row(rid):
    s, text = T.http("GET", f"/entries/{int(rid)}")
    if s != 200:
        return None
    try:
        r = json.loads(text)
    except ValueError:
        return None
    return r[0] if isinstance(r, list) and r else r if isinstance(r, dict) else None


def put_thread(rid, t, title=None):
    body = {"content": render_thread(t), "done_bool": 1 if t["status"] == "answered" else 0}
    if title:
        body["title"] = title[:200]
    s, text = T.http("PATCH", f"/entries/{int(rid)}", body)
    if not 200 <= s < 300:
        raise RuntimeError(f"PATCH /entries/{rid}: {s} {text[:200]}")


def post_thread(entry, role, title, turn, **extra):
    t = dict({"status": "queued", "why": "", "entry": entry["id"], "role": role, "turns": [turn]}, **extra)
    head = (entry.get("title") or "").strip()
    body = {"kind": KIND, "title": f"{title} · #{entry['id']}" + (f" {head}" if head else ""),
            "content": render_thread(t), "value_int": int(entry["id"]), "done_bool": int(t["status"] == "answered")}
    body["title"] = body["title"][:200]
    s, text = T.http("POST", "/entries", body)
    if not 200 <= s < 300:
        raise RuntimeError(f"POST /entries ({KIND}): {s} {text[:200]}")
    return int(json.loads(text).get("id") or 0), t


# ---- the watcher -------------------------------------------------------------

def utc_text(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_ts(s):
    t = T.stamp(s)
    return t.timestamp() if t else 0.0


# ---- notes to people: Number One and the engineers ---------------------------

NO1 = "number-one"
# who takes an @name note, published for the page by the watcher (one row,
# the crew login's kind): the page's chips and card know the same names
NAMES_KIND = "crew_note_names"
NAMES_TITLE = "Crew notes: who answers an @name"
NAMES_TTL = float(os.environ.get("LCARS_NOTES_NAMES_TTL") or 60)
ROLE_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
# what a typed order carries, and the Stop hook finds it by
MARK_RE = re.compile(r"\(crew note #(\d+)\)")
ENGINEER_PY = os.environ.get("LCARS_NOTES_ENGINEER") or os.path.join(HERE, "engineer.py")
ANSWER_MAX = 12000


def undelivered(t):
    """How many of the captain's turns have not been typed to them yet."""
    return max(0, sum(1 for x in t["turns"] if captain(x)) - int(t.get("sent") or 0))


def wants_turn(t):
    """A thread with work for the watcher: queued, and for a person's
    thread a turn of the captain's not yet typed to them."""
    return t["status"] == "queued" and (not t.get("to") or undelivered(t) > 0)


def names_content(direct):
    lines = ["Who answers an @name note in an entry, besides the crew roles (scripts/crew_notes.py: the "
             "watcher's list, Number One and the ten engineers most recently active; read by the page).", ""]
    for a, v in sorted(direct.items()):
        lines.append(f"- @{a} \u2192 {v['title']} ({v['to']})" + (", off duty" if v.get("off") else ""))
    blob = {a: {"to": v["to"], "title": v["title"], **({"off": 1} if v.get("off") else {})}
            for a, v in sorted(direct.items())}
    return "\n".join(lines) + "\n\n```json\n" + json.dumps(blob, ensure_ascii=False) + "\n```\n"


def engineer_run(*args, inp=None, timeout=120):
    """(exit status, its JSON answer) of `engineer.py <args>`."""
    try:
        p = subprocess.run([sys.executable, ENGINEER_PY, *args], input=inp, capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, {"error": str(e)}
    try:
        j = json.loads((p.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        j = {"error": (p.stderr or p.stdout).strip()[-300:]}
    return p.returncode, j if isinstance(j, dict) else {}


def note_names():
    """{alias: {to, title, off}} from `engineer.py note-names`, or None."""
    rc, j = engineer_run("note-names", timeout=60)
    if rc != 0:
        raise RuntimeError(f"engineer.py note-names: exit {rc} {j.get('error', '')}")
    names = j.get("names")
    return names if isinstance(names, dict) else None


def engineer_send(to, text):
    """(0 or the exit status, why): an order typed to Number One's inbox or
    an engineer's session, as the captain's (`say`, never --fresh)."""
    rc, j = engineer_run("no1-send", text) if to == NO1 else engineer_run("say", to, inp=text)
    return rc, str(j.get("error") or "")[:200]


def order_text(t, tid, entry, turns):
    """What is typed: [captain], the note, its entry and thread by id, and
    where the answer goes. The mark `(crew note #T)` is what their Stop hook
    finds the thread by."""
    head = json.dumps(((entry or {}).get("title") or "").strip(), ensure_ascii=False)
    first = not any(not captain(x) for x in t["turns"]) and len(turns) == sum(1 for x in t["turns"] if captain(x))
    words = []
    for x in turns:
        w = x["text"]
        if w.lower().startswith("@" + t["role"]):
            w = w[len(t["role"]) + 1:].strip()
        words.append(w)
    what = "A note to you" if first else "More in a note to you"
    return (f"[captain] {what}, written in the captain's journal entry #{t['entry']} {head} (crew note #{tid}): "
            + "\n\n".join(words)
            + "\n\n(The last message of the turn that takes this is your answer: it is put in the note's thread, "
              "under the note in his entry, so make it complete on its own.)")


def note_working(tid):
    """Their session has the order: the thread says they are on it."""
    r = get_row(tid)
    if r is None or r.get("deleted") or r.get("kind") != KIND:
        return False
    t = parse_thread(r.get("content"))
    if t["status"] in ("queued",) and t.get("to"):
        t["status"], t["why"] = "working", ""
        put_thread(tid, t)
    return True


def note_answer(tid, who, text):
    """Their answer into the thread: after the last captain turn that was
    typed to them (a reply written since stays after it, and keeps the
    thread queued), and the status by what is left."""
    r = get_row(tid)
    if r is None or r.get("deleted") or r.get("kind") != KIND:
        return False
    t = parse_thread(r.get("content"))
    text = (text or "").strip() or "(no words at the end of the turn)"
    if len(text) > ANSWER_MAX:
        text = text[:ANSWER_MAX] + f"\n[... {len(text) - ANSWER_MAX} more characters]"
    # at least the first: a thread answered was sent something (a page of
    # before 0.256.0 writing it back may have dropped the count)
    sent, pos, seen = max(1, int(t.get("sent") or 0)), len(t["turns"]), 0
    for i, x in enumerate(t["turns"]):
        if captain(x):
            seen += 1
            if seen > sent:
                pos = i
                break
    t["turns"].insert(pos, {"who": who, "at": stamp_now(), "hash": "", "reply": False, "text": text})
    later = any(captain(x) for x in t["turns"][pos + 1:])
    t["status"] = "answered" if not later else "queued" if undelivered(t) else "working"
    t["why"] = ""
    put_thread(tid, t)
    return True


def thread_who(row):
    """The name a person's thread answers under: its title's, before the alias."""
    head = ((row or {}).get("title") or "").split(" \u00b7 ")[0]
    return re.sub(r"\s*\(@[a-z0-9-]+\)$", "", head).strip() or "Crew"


class Watcher:
    """The notes watcher's state. `roles` maps a crew role to its display
    name; `run` is how a thread's turn is run (crew.py note, a subprocess).
    `names` is who else takes a note ({alias: {to, title, off}}, read again
    every NAMES_TTL seconds; None: nobody), and `send` how an order reaches
    them (`engineer.py`, a subprocess)."""

    def __init__(self, roles, state, run=None, now=time.time, quiet=QUIET, names=None, send=None):
        self.crew, self.state, self.now, self.quiet = dict(roles), state, now, quiet
        self.roles = dict(roles)   # the crew's and the direct ones': what note_scan takes
        self.direct = {}           # alias -> {to, title, off}
        self.names, self.names_at, self.names_row = names, None, None
        self.run = run or self.run_subprocess
        self.send = send or self.send_direct
        self.threads = {}          # (entry id, role) -> {id, hashes, status}
        self.pending = {}          # entry id -> its last_modified (not yet quiet)
        self.queue = queue.Queue()
        self.busy = set()          # thread ids queued or running
        self.lock = threading.Lock()
        self.starting = False
        os.makedirs(state, exist_ok=True)
        self.mark_path = os.path.join(state, "notes.mark")
        try:
            with open(self.mark_path) as f:
                self.mark = f.read().strip()
        except OSError:
            self.mark = ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", self.mark):
            # A first start begins now: every @yeoman ever written is history,
            # not a queue of orders
            self.mark = utc_text(self.now())
            self.save_mark(self.mark)
        self.top = self.mark       # the newest change seen

    def log(self, msg):
        print(f"{utc_text(time.time())} notes: {msg}", flush=True)

    def save_mark(self, mark):
        with open(self.mark_path + ".tmp", "w") as f:
            f.write(mark)
        os.replace(self.mark_path + ".tmp", self.mark_path)

    def dump(self, **q):
        s, text = T.http("GET", "/dump?" + urllib.parse.urlencode(q), timeout=120)
        if s != 200:
            raise RuntimeError(f"GET /dump {q}: {s} {text[:200]}")
        rows = json.loads(text or "[]")
        return rows if isinstance(rows, list) else []

    def load_threads(self):
        self.starting = True
        try:
            self.refresh_names(force=True)
            for r in self.dump(kind=KIND):
                self.see_thread(r)
        finally:
            self.starting = False

    # -- who else takes a note: Number One and the ten engineers
    def refresh_names(self, force=False):
        """Read the names again when NAMES_TTL has passed, and publish them
        for the page (a crew_note_names row) when they changed. A failed
        read keeps the last list: an engineer.py hiccup must not turn every
        @torres into plain text for a minute."""
        if self.names is None or (not force and self.names_at is not None
                                  and self.now() - self.names_at < NAMES_TTL):
            return
        self.names_at = self.now()
        try:
            got = self.names()
        except Exception as e:  # noqa: BLE001 - say so, keep the old list
            self.log(f"note names: {e}")
            return
        if got is None:
            return
        # a crew role keeps its name: @ops is the ops role, whoever else is called that
        direct = {a: v for a, v in got.items() if a not in self.crew and ROLE_RE.fullmatch(a)}
        self.direct = direct
        self.roles = dict(self.crew, **{a: v["title"] for a, v in direct.items()})
        self.publish_names()

    def publish_names(self):
        try:
            if self.names_row is None:
                rows = self.dump(kind=NAMES_KIND)
                live = sorted((r for r in rows if not r.get("deleted")), key=lambda r: r["id"])
                self.names_row = (live[0]["id"], live[0].get("content") or "") if live else (0, "")
            rid, had = self.names_row
            body = names_content(self.direct)
            if body == had:
                return
            if rid:
                s, text = T.http("PATCH", f"/entries/{rid}", {"content": body})
            else:
                s, text = T.http("POST", "/entries", {"kind": NAMES_KIND, "title": NAMES_TITLE, "content": body})
                rid = int(json.loads(text).get("id") or 0) if 200 <= s < 300 else 0
            if not 200 <= s < 300:
                raise RuntimeError(f"{s} {text[:200]}")
            self.names_row = (rid, body)
        except Exception as e:  # noqa: BLE001 - the page then has the last list; the next change tries again
            self.names_row = None
            self.log(f"publishing the note names: {e}")

    def see_thread(self, r):
        if r.get("kind") != KIND:
            return
        t = parse_thread(r.get("content"))
        if not t["entry"] or (t["role"] not in self.roles and not t.get("to")):
            return
        key = (t["entry"], t["role"])
        if r.get("deleted"):
            if self.threads.get(key, {}).get("id") == r["id"]:
                del self.threads[key]
            return
        self.threads[key] = {"id": r["id"], "status": t["status"],
                             "hashes": {x["hash"] for x in t["turns"] if x["hash"]}}
        if t.get("to"):
            # a person's thread is work only while a turn of the captain's
            # has not been typed to them: once it has, the answer is theirs
            # to give (their Stop hook), and a restart must not type it again
            if t["status"] == "queued" and undelivered(t):
                self.enqueue(r["id"])
            return
        # working too: at the watcher's start no turn is running (they are
        # its own children), so a working thread is one a restart cut short
        if t["status"] == "queued" or (t["status"] == "working" and r["id"] not in self.busy and self.starting):
            self.enqueue(r["id"])

    def enqueue(self, tid):
        with self.lock:
            if tid in self.busy:
                return
            self.busy.add(tid)
        self.queue.put(tid)

    def sync(self):
        """What changed since the mark: threads seen, notes taken or held."""
        self.refresh_names()
        rows = self.dump(modified_since=self.mark)
        for r in rows:
            self.top = max(self.top, r.get("last_modified_at_utc") or "")
            if r.get("kind") == KIND:
                self.see_thread(r)
            else:
                self.consider(r)
        self.advance()
        return len(rows)

    def advance(self):
        # an unripe note holds the mark back, so a restart finds it again
        low = min([self.top] + list(self.pending.values()))
        if low != self.mark:
            self.mark = low
            self.save_mark(low)

    def consider(self, r):
        """A changed entry: take its ripe notes, or wait for it to go quiet."""
        if not eligible(r):
            self.pending.pop(r["id"], None)
            return
        notes = [n for n in note_scan(r.get("content"), self.roles)
                 if n["hash"] not in self.threads.get((r["id"], n["role"]), {}).get("hashes", ())]
        if not notes:
            self.pending.pop(r["id"], None)
            return
        lm = r.get("last_modified_at_utc") or ""
        if self.now() - utc_ts(lm) < self.quiet:
            self.pending[r["id"]] = lm
            return
        self.pending.pop(r["id"], None)
        for n in notes:
            self.take(r, n)

    def due(self):
        """Seconds to the next pending entry's ripening (None: none)."""
        if not self.pending:
            return None
        return max(0.0, min(utc_ts(v) for v in self.pending.values()) + self.quiet - self.now())

    def ripen(self):
        """Re-read each pending entry whose quiet period is over."""
        for eid, lm in list(self.pending.items()):
            if self.now() - utc_ts(lm) < self.quiet:
                continue
            r = get_row(eid)
            if r is None:
                self.pending.pop(eid, None)
            else:
                self.consider(r)
        self.advance()

    def take(self, entry, note):
        key = (entry["id"], note["role"])
        turn = {"who": "Captain", "at": stamp_now(), "hash": note["hash"], "reply": False,
                "text": f"@{note['role']} {note['text']}"}
        d = self.direct.get(note["role"]) if note["role"] not in self.crew else None
        # a dismissed engineer's note is answered here and now: nothing started
        turns = [turn, self.off_duty(d)] if d and d.get("off") else [turn]
        status = "answered" if len(turns) > 1 else "queued"
        have = self.threads.get(key)
        if have:
            r = get_row(have["id"])
            if r is not None and not r.get("deleted"):
                t = parse_thread(r.get("content"))
                if note["hash"] in {x["hash"] for x in t["turns"]}:
                    return
                t["turns"] += turns
                t["status"], t["why"] = status, ""
                if d and not d.get("off") and t.get("to") != d["to"]:
                    # the name is someone else's now (a newer @torres): the
                    # turns so far were theirs, this one is the new one's
                    t["to"], t["sent"] = d["to"], sum(1 for x in t["turns"][:-1] if captain(x))
                put_thread(have["id"], t)
                have["hashes"].add(note["hash"])
                self.log(f"#{entry['id']} @{note['role']}: added to thread #{have['id']}")
                if status == "queued":
                    self.enqueue(have["id"])
                return
        extra = {"turns": turns, "status": status}
        if d and not d.get("off"):
            extra.update(to=d["to"], sent=0)
        tid, _ = post_thread(entry, note["role"], self.thread_title(note["role"], d), turn, **extra)
        self.threads[key] = {"id": tid, "status": status, "hashes": {note["hash"]}}
        self.log(f"#{entry['id']} @{note['role']}: thread #{tid}" + (" (off duty)" if status == "answered" else ""))
        if status == "queued":
            self.enqueue(tid)

    def thread_title(self, role, d):
        # a person's thread names the alias too: two names can be one
        # engineer's (@jake, @sisko), and the page keys a thread by the alias
        return f"{d['title']} (@{role})" if d else self.roles[role]

    def off_duty(self, d):
        by = {}
        for a, v in self.direct.items():
            if not v.get("off") and v["to"] != NO1:
                by.setdefault(v["to"], (v["title"], []))[1].append("@" + a)
        on = [f"{title} ({', '.join(sorted(al, key=len))})" for title, al in sorted(by.values())]
        text = (f"{d['title']} is off duty (dismissed), so nothing was started. "
                + (f"On duty: {', '.join(on)}." if on else "Nobody else is on duty.")
                + " A message to them in the console recalls them.")
        return {"who": d["title"], "at": stamp_now(), "hash": "", "reply": False, "text": text}

    # -- the worker: one turn at a time, through crew.py note
    def run_subprocess(self, tid):
        p = subprocess.run([sys.executable, os.path.join(HERE, "crew.py"), "note", str(tid)],
                           capture_output=True, text=True)
        if p.returncode:
            self.log(f"thread #{tid}: crew.py note exit {p.returncode} {(p.stdout + p.stderr).strip()[-300:]}")
        return p.returncode

    def work_one(self, tid):
        try:
            r = get_row(tid)
            to = r is not None and (parse_thread(r.get("content")).get("to") or self.to_of(r))
            rc = self.send(tid) if to else self.run(tid)
        finally:
            with self.lock:
                self.busy.discard(tid)
        # a reply that came while it ran (status queued again) is the next
        # turn; a skip (75: lock, memory, server, a question on screen) is
        # tried again later
        r = get_row(tid)
        if r is not None and wants_turn(parse_thread(r.get("content"))):
            if rc == 75:
                time.sleep(60)
            self.enqueue(tid)

    def to_of(self, r):
        """A person's thread that lost its `to:` (a page from before 0.256.0
        wrote it back without): its alias's engineer now."""
        t = parse_thread(r.get("content"))
        d = self.direct.get(t["role"]) if t["role"] not in self.crew else None
        return d["to"] if d and not d.get("off") else ""

    # -- an order to Number One or an engineer: typed, and that is all
    def send_direct(self, tid):
        """Type the captain's turns not yet sent to the one the thread is
        for: Number One's inbox (its flusher wakes it), or the engineer's
        session through the seat (`say`: queued in their inbox when not
        seated). `sent` moves first, so a restart mid-send never types it
        twice; a failure puts it back. 0 sent (or nothing to), 75 not now."""
        r = get_row(tid)
        if r is None or r.get("deleted"):
            return 0
        t = parse_thread(r.get("content"))
        t["to"] = t.get("to") or self.to_of(r)
        n, was = undelivered(t), int(t.get("sent") or 0)
        if not t["to"] or n <= 0 or t["status"] != "queued":
            return 0
        if any(v["to"] == t["to"] and v.get("off") for v in self.direct.values()) and t["to"] != NO1:
            d = next(v for v in self.direct.values() if v["to"] == t["to"])
            t["turns"].append(self.off_duty(d))
            t["status"], t["why"], t["sent"] = "answered", "", was + n
            put_thread(tid, t)
            return 0
        entry = get_row(t["entry"])
        text = order_text(t, tid, entry, [x for x in t["turns"] if captain(x)][-n:])
        t["sent"] = was + n
        put_thread(tid, t)
        rc, why = engineer_send(t["to"], text)
        self.log(f"thread #{tid}: {n} turn(s) to {t['to']}: " + ("sent" if rc == 0 else f"exit {rc} {why}"))
        if rc == 0:
            return 0
        r = get_row(tid)
        t = parse_thread((r or {}).get("content"))
        t["sent"] = was
        if rc == 3:
            t["status"], t["why"] = "queued", ""
        else:
            t["status"], t["why"] = "failed", f"not delivered to {t.get('to') or 'them'}: {why}"[:200]
        put_thread(tid, t)
        return 75 if rc == 3 else 1

    def worker(self):
        while True:
            self.work_one(self.queue.get())


def events(url_path, signal, stop):
    """GET /events, held: every `data:` line is a nudge to sync. Reconnects
    with a growing pause; a reconnect is a nudge too (changes were missed)."""
    import base64
    import urllib.request
    pause = 1
    while not stop.is_set():
        try:
            url, user, pw = T.creds()
            tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
            req = urllib.request.Request(url + url_path, headers={"Authorization": "Basic " + tok,
                                                                  "X-LCARS-Client": "crew-notes"})
            with urllib.request.urlopen(req, timeout=60) as r:
                pause = 1
                for raw in r:
                    if stop.is_set():
                        return
                    if raw.startswith(b"data:"):
                        signal.put("sync")
        except Exception as e:  # noqa: BLE001 - any failure is a reconnect
            print(f"notes: /events: {e}", file=sys.stderr, flush=True)
        signal.put("sync")
        stop.wait(pause)
        pause = min(pause * 2, 60)


def watch(roles, state):
    w = Watcher(roles, state, names=note_names)
    w.load_threads()
    w.log(f"watching for {', '.join('@' + r for r in sorted(roles))} since {w.mark}")
    threading.Thread(target=w.worker, daemon=True).start()
    signal, stop = queue.Queue(), threading.Event()
    threading.Thread(target=events, args=("/events", signal, stop), daemon=True).start()
    while True:
        try:
            signal.get(timeout=w.due())
            while not signal.empty():
                signal.get_nowait()
            w.sync()
        except queue.Empty:
            pass
        except Exception as e:  # noqa: BLE001 - the server down, a bad row: say so, go on
            w.log(f"sync failed: {e}")
            time.sleep(5)
        try:
            w.ripen()
        except Exception as e:  # noqa: BLE001
            w.log(f"ripen failed: {e}")


# ---- the write path: create, append and title, nothing else ---------------------
#
# The captain's rule (2026-10-15): the crew may create new entries, add to
# the end of his and set an entry's title (his word, later that day: the
# title is the one thing of a row it may change), and (2026-10-16) close an
# open entry of his - set the end of one that has a start and no end; it
# never changes, replaces or removes any text, kind, dates or done of his,
# and never moves a start or an end already set. A role never
# writes itself: its answer may end with a CHANGES block, which the runner
# (note_apply) checks and applies with the steward login - a login the
# server lets do exactly those three things (lcars_logins.h) - and lists in
# the thread with what Undo needs.
#
#   CHANGES
#   create kind=sleep title="Sleep" start="2026-10-14 23:10" end="2026-10-15 07:05" text="7h55m"
#   append #4321 at="2026-10-15 20:01:02" text="Plus 20 minutes rowing."
#   title #4310 at="2026-10-15 20:01:02" text="Rowing, 20 minutes"
#   end #4305 at="2026-10-15 20:01:02" end="2026-10-15 07:05"
#
# Times are the captain's local time; `at` is the row's last_modified_at_utc
# as the role read it (`get <id> --json`), and the server refuses an append
# or a title on a row that moved since (412). A title's Undo needs the old
# one, which the server answers (old_title) and the fence carries; an end's
# Undo puts the empty end back if the row still holds the one set (old_end,
# "", and end, as stored, UTC). Everything the crew adds says it is the
# crew's in the text itself: a created entry starts with a `> <Role>
# created this, …` line, an appended block is a quote headed `> <Role>
# added, <time>:`. A quote is never a note (note_scan), so nothing the crew
# writes can start another thread.

STEWARD_LOGIN = ("LCARS_STEWARD_USER", "LCARS_STEWARD_PASS")
MAX_CHANGES = 5
CREATE_KEYS = {"kind", "title", "text", "start", "end"}
# set's fields (the captain's yes, 2026-10-16) and the columns they are:
# dates in his local time, as create takes them
SET_KEYS = {"title": "title", "kind": "kind", "start": "start_date", "end": "end_date", "done": "done_bool",
            "value_int": "value_int", "value_float": "value_float", "created_at": "created_at_utc"}
SET_DATES = {"start", "end", "created_at"}
TEXT_MAX = 8000
# a replace carries the entry's whole new text: what the role is shown of
# one (ENTRY_MAX), with room
REPLACE_MAX = 32000
# A title is a line: the server takes 511 bytes (HandleTitleEntry), the crew
# a short one
TITLE_MAX = 120
# A turn of the captain's that asks for something to be written, or agrees
# to what was proposed. Not judgement - the brief tells the role the same,
# and this is the wall that does not rely on it: a plain question's changes
# are only proposed.
ORDER_RE = re.compile(r"\b(log|logs|logged|add|added|create|make|record|write|append|enter|put|track|save|jot|note"
                      r"|title|retitle|rename|name|close|end|finish"
                      r"|set|change|edit|fix|correct|replace|update|move|mark|delete|remove|restore|undelete"
                      r"|yes|yep|yeah|ok|okay|sure|go ahead|do it|do that|please do|apply|confirm)\b", re.I)
UNDO_FENCE = "crew-changes"


def asks_for_writes(text):
    """A question is never an order, however it is worded ("what did I
    write last week?", "can you log it?"): its changes are proposed, and a
    "yes" makes them."""
    t = text or ""
    return "?" not in t and bool(ORDER_RE.search(t))


# A turn of the captain's that calls the order off: a no at its start, or a
# cancel anywhere. It ends the scan for a standing order (ordered_by).
REFUSE_RE = re.compile(r"^\W*(no|nope|nah|stop|wait|cancel|don'?t|do not|never ?mind|forget it|leave it)\b"
                       r"|\b(cancel|never ?mind|forget it"
                       r"|don'?t (log|add|make|create|write|do|close|end|change|edit|delete|remove|restore)"
                       r"|do not (log|add|make|create|write|do|close|end|change|edit|delete|remove|restore))\b", re.I)
# A role's turn that asks him for something without a question mark
NEED_RE = re.compile(r"\b(i need|i'll need|i would need|need to know|tell me|let me know|send me|give me"
                     r"|which one|what time)\b", re.I)


def ordered_by(turns):
    """Whether the captain's latest turn (the one being answered) carries
    an order, on its own or standing. On its own: asks_for_writes. Standing
    (2026-10-16, crew_note #7453: "make the drive entry", the yeoman asked
    when and where, and his answer, times and places only, read as no
    order): a plain answer - no order word, no question mark, no refusal -
    to a turn of the role's that asked him something is the earlier order's
    answer, so the order is the latest earlier turn of his that was one,
    looking back through this thread until a refusal ("no", "stop") ends
    the look. A question of his is never an order."""
    caps = [i for i, x in enumerate(turns) if captain(x)]
    if not caps:
        return False
    last = turns[caps[-1]]["text"] or ""
    if asks_for_writes(last):
        return True
    if "?" in last or REFUSE_RE.search(last):
        return False
    before = [x for x in turns[:caps[-1]] if not captain(x)]
    if not before:
        return False
    # the role's words only: not its changes' fence or the runner's footer
    # (`*crew.py note yeoman · sonnet · ? turns ...*`)
    asked = re.sub(r"```" + UNDO_FENCE + r"\n.*?```", "", before[-1]["text"] or "", flags=re.S)
    asked = "\n".join(ln for ln in asked.split("\n") if not ln.startswith("*crew.py "))
    if "?" not in asked and not NEED_RE.search(asked):
        return False
    for i in reversed(caps[:-1]):
        t = turns[i]["text"] or ""
        if REFUSE_RE.search(t):
            return False
        if asks_for_writes(t):
            return True
    return False


def split_changes(result):
    """(the answer without its CHANGES block, [the block's lines]). The
    block is a line `CHANGES` and the lines after it up to a blank line, a
    closing fence or the end; a fence opened just before it goes with it."""
    lines = (result or "").split("\n")
    for i, ln in enumerate(lines):
        if re.fullmatch(r"[ \t]*\**CHANGES\**:?[ \t]*", ln):
            break
    else:
        return (result or "").strip(), []
    lo, hi = i, i + 1
    if lo > 0 and lines[lo - 1].strip().startswith("```"):
        lo -= 1
    got = []
    while hi < len(lines) and lines[hi].strip() and not lines[hi].strip().startswith("```"):
        got.append(lines[hi].strip())
        hi += 1
    if hi < len(lines) and lines[hi].strip().startswith("```"):
        hi += 1
    return "\n".join(lines[:lo] + lines[hi:]).strip(), got


def local_to_utc(s):
    """'YYYY-MM-DD HH:MM' in the captain's zone to the journal's UTC text."""
    s = (s or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            t = dt.datetime.strptime(s, fmt).replace(tzinfo=T.TZ)
            return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"not a time: {s!r} (YYYY-MM-DD HH:MM, the captain's time)")


def parse_change(line, need_at=True):
    """{op, ...} or ValueError saying why the line is not a change the crew
    may make. need_at=False for a scheduled run's append, whose `at` the
    runner takes from its own fresh read (crew.py scheduled_apply)."""
    import shlex
    try:
        words = shlex.split(line)
    except ValueError as e:
        raise ValueError(f"cannot read it ({e})")
    if not words:
        raise ValueError("empty")
    op = words[0].lower()
    if op not in OPS:
        raise ValueError(f"'{op}' is not allowed: the crew creates, appends, titles, ends, sets, replaces, "
                         f"deletes and restores, nothing else")
    c = {"op": op}
    rest = words[1:]
    if op != "create":
        if not rest or not re.fullmatch(r"#?\d+", rest[0]):
            raise ValueError(f"{op} needs the entry, as #<id>")
        c["id"] = int(rest[0].lstrip("#"))
        rest = rest[1:]
    for w in rest:
        k, eq, v = w.partition("=")
        if not eq:
            raise ValueError(f"{w!r} is not key=value")
        c[k.strip().lower()] = v
    if op == "create" and "id" in c:
        raise ValueError("create takes kind, text, title, start, end; not id")
    keys = set(c) - {"op", "id"}
    allowed = CREATE_KEYS if op == "create" else {"at", "end"} if op == "end" \
        else {"at", *SET_KEYS} if op == "set" else {"at"} if op in ("delete", "restore") \
        else {"at", "text"}   # title's text is the title
    if keys - allowed:
        raise ValueError(f"{op} takes {', '.join(sorted(allowed))}; not {', '.join(sorted(keys - allowed))}")
    if not (c.get("text") or "").strip() and op == "append":
        raise ValueError("append needs text")
    if op != "create" and not c.get("at") and need_at:
        raise ValueError(f"{op} needs at=<the entry's last_modified_at_utc, as read>")
    if op == "title":
        c["text"] = " ".join((c.get("text") or "").split())
        if not c["text"]:
            raise ValueError("title needs text=<the new title>")
        if len(c["text"]) > TITLE_MAX:
            raise ValueError(f"a title over {TITLE_MAX} characters")
    if op == "end":
        if not (c.get("end") or "").strip():
            raise ValueError("end needs end=<the captain's local time, YYYY-MM-DD HH:MM>")
        c["end_utc"] = local_to_utc(c["end"])
        c["end"] = " ".join(c["end"].replace("T", " ").split())[:16]
    if op == "set":
        c["fields"] = set_fields(c)
    if op == "replace":
        # a whole text, on one CHANGES line: its new lines come as \n
        c["text"] = (c.get("text") or "").replace("\\n", "\n")
        if not c["text"].strip():
            raise ValueError("replace needs text=<the entry's whole new text>")
        if len(c["text"]) > REPLACE_MAX:
            raise ValueError(f"text over {REPLACE_MAX} characters")
        # his own @role lines may stay in his text; apply_change refuses a new one
        return c
    if op == "create":
        if not (c.get("kind") or "").strip():
            raise ValueError("create needs a kind")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", c["kind"]):
            raise ValueError(f"{c['kind']!r} is not a kind")
        if not (c.get("title") or c.get("text") or "").strip():
            raise ValueError("create needs a title or text")
        for k in ("start", "end"):
            if c.get(k):
                c[k + "_utc"] = local_to_utc(c[k])
    text = (c.get("text") or "") + " " + (c.get("title") or "")
    if len(c.get("text") or "") > TEXT_MAX:
        raise ValueError(f"text over {TEXT_MAX} characters")
    if note_scan(text, _AnyRole()):
        raise ValueError("it holds an @role line: the crew does not write notes to the crew")
    return c


OPS = ("create", "append", "title", "end", "set", "replace", "delete", "restore")


def set_fields(c):
    """A set line's fields as the columns PATCH takes, or ValueError."""
    out = {}
    for k, col in SET_KEYS.items():
        if k not in c:
            continue
        v = c[k]
        if k == "title":
            v = " ".join(v.split())
            if len(v) > TITLE_MAX:
                raise ValueError(f"a title over {TITLE_MAX} characters")
            if note_scan(v, _AnyRole()):
                raise ValueError("it holds an @role line: the crew does not write notes to the crew")
        elif k == "kind":
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", v):
                raise ValueError(f"{v!r} is not a kind")
            if not_from(v) or v in T.IMPORTED_KINDS:
                raise ValueError(f"{v} is not a kind of the captain's: the crew never moves an entry into it")
        elif k in SET_DATES:
            # an empty start or end unschedules; a written-at is always a time
            v = "" if k != "created_at" and not v.strip() else local_to_utc(v)
        elif k == "done":
            if v not in ("0", "1"):
                raise ValueError("done is 0 or 1")
            v = int(v)
        elif k == "value_int":
            try:
                v = int(v)
            except ValueError:
                raise ValueError(f"value_int {v!r} is not a whole number")
        elif k == "value_float":
            try:
                v = float(v)
            except ValueError:
                raise ValueError(f"value_float {v!r} is not a number")
        out[col] = v
    if not out:
        raise ValueError(f"set needs a field: {', '.join(SET_KEYS)}")
    return out


def utc_local(s):
    """The journal's UTC text in the captain's time, for the list."""
    if not s:
        return ""
    t = dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return t.astimezone(T.TZ).strftime("%Y-%m-%d %H:%M")


class _AnyRole:
    """Every role name is one, for the check above: a crew write may not
    hold anything shaped like a note, whichever role it names."""

    def __contains__(self, r):
        return True


def quote_block(who, at, text):
    body = "\n".join("> " + ln if ln.strip() else ">" for ln in text.strip().split("\n"))
    return f"\n\n> {who} added, {at}:\n{body}"


def created_line(who, at, tid, entry_id):
    return f"> {who} created this, {at} (crew note #{tid}, from #{entry_id})"


def steward(method, path, body=None):
    return T.http(method, path, body, login=STEWARD_LOGIN)


def apply_change(c, who, tid, entry_id, now_ts):
    """One change, applied with the steward login: (record, None) or
    (None, why it was not)."""
    at = stamp_now()
    if c["op"] == "create":
        content = created_line(who, at, tid, entry_id) + ("\n\n" + c["text"].strip() if (c.get("text") or "").strip() else "")
        body = {"kind": c["kind"], "title": (c.get("title") or "").strip()[:200], "content": content}
        if c.get("start_utc"):
            body["start_date"] = c["start_utc"]
        if c.get("end_utc"):
            body["end_date"] = c["end_utc"]
        s, text = steward("POST", "/entries", body)
        if not 200 <= s < 300:
            return None, f"the server refused it ({s}: {_err(text)})"
        rid = int(json.loads(text).get("id") or 0)
        return {"op": "create", "id": rid, "kind": c["kind"], "title": body["title"]}, None
    row = get_row(c["id"])
    if c["op"] == "restore":
        if row is None or not row.get("deleted"):
            return None, f"#{c['id']} is not a deleted entry"
        row = dict(row, deleted=0)       # eligible() asks of the kind, below
    if row is None or row.get("deleted"):
        return None, f"#{c['id']} is not a live entry"
    if not eligible(row):
        return None, f"#{c['id']} is {row.get('kind')}, not one of the captain's entries the crew may add to"
    if now_ts - utc_ts(row.get("last_modified_at_utc")) < QUIET:
        return None, f"#{c['id']} is being edited (changed under {int(QUIET)}s ago)"
    if c["op"] in ("set", "replace", "delete", "restore"):
        return guarded_change(c, row)
    if c["op"] == "title":
        s, text = steward("POST", f"/entries/{c['id']}/title", {"title": c["text"], "if_modified": c["at"]})
        if s == 412:
            return None, f"#{c['id']} changed since it was read"
        if not 200 <= s < 300:
            return None, f"the server refused it ({s}: {_err(text)})"
        try:
            old = json.loads(text).get("old_title")
        except (ValueError, AttributeError):
            old = None
        return {"op": "title", "id": c["id"], "old_title": (row.get("title") or "") if old is None else old,
                "title": c["text"]}, None
    if c["op"] == "end":
        if (row.get("end_date") or "").strip():
            return None, f"#{c['id']} has an end already ({row['end_date']} UTC): the crew never moves one"
        s, text = steward("POST", f"/entries/{c['id']}/end", {"end": c["end_utc"], "if_modified": c["at"]})
        if s == 412:
            return None, f"#{c['id']} changed since it was read"
        if not 200 <= s < 300:
            return None, f"the server refused it ({s}: {_err(text)})"
        try:
            ans = json.loads(text)
        except ValueError:
            ans = {}
        return {"op": "end", "id": c["id"], "old_end": ans.get("old_end_date") or "",
                "end": ans.get("end_date") or c["end_utc"], "at": c["end"]}, None
    block = quote_block(who, at, c["text"])
    s, text = steward("POST", f"/entries/{c['id']}/append", {"text": block, "if_modified": c["at"]})
    if s == 412:
        return None, f"#{c['id']} changed since it was read"
    if not 200 <= s < 300:
        return None, f"the server refused it ({s}: {_err(text)})"
    return {"op": "append", "id": c["id"], "text": block}, None


def guarded_change(c, row):
    """set, replace, delete, restore: a PATCH or DELETE with the row's stamp
    as read (`at`, compared by the server: 412 when it moved, 409 a deleted
    row - or, for a restore, a live one). The old values come from the
    fresh read just made: the stamp guard means the write landed on exactly
    that row, so they are what Undo puts back."""
    i, at = c["id"], c["at"]
    if c["op"] == "set":
        body = dict(c["fields"], if_modified=at)
        s, text = steward("PATCH", f"/entries/{i}", body)
        rec = {"op": "set", "id": i, "old": {k: row.get(k) for k in c["fields"]}, "new": c["fields"]}
    elif c["op"] == "replace":
        old = row.get("content") or ""
        mine = {(x["role"], x["text"]) for x in note_scan(old, _AnyRole())}
        new_notes = [x for x in note_scan(c["text"], _AnyRole()) if (x["role"], x["text"]) not in mine]
        if new_notes:
            return None, "the new text holds an @role line his did not: the crew does not write notes to the crew"
        s, text = steward("PATCH", f"/entries/{i}", {"content": c["text"], "if_modified": at})
        rec = {"op": "replace", "id": i, "old_text": old, "text": c["text"]}
    elif c["op"] == "delete":
        s, text = steward("DELETE", f"/entries/{i}", {"if_modified": at})
        rec = {"op": "delete", "id": i, "kind": row.get("kind") or "", "title": row.get("title") or ""}
    else:
        s, text = steward("PATCH", f"/entries/{i}", {"deleted": 0, "if_modified": at})
        rec = {"op": "restore", "id": i, "kind": row.get("kind") or "", "title": row.get("title") or ""}
    if s == 412:
        return None, f"#{i} changed since it was read"
    if s == 409:
        return None, f"#{i} {'is not deleted' if c['op'] == 'restore' else 'is deleted'}"
    if not 200 <= s < 300:
        return None, f"the server refused it ({s}: {_err(text)})"
    return rec, None


def shown_value(col, v):
    if col in ("start_date", "end_date", "created_at_utc"):
        return utc_local(v) or "none"
    if col == "title":
        return title_shown(v)
    return "none" if v is None or v == "" else str(v)


def set_listed(rec):
    """`kind sleep → child_sleep; start 2026-10-15 23:10 → 23:20`"""
    names = {col: k for k, col in SET_KEYS.items()}
    return "; ".join(f"{names.get(col, col)} {shown_value(col, rec['old'].get(col))} \u2192 {shown_value(col, v)}"
                     for col, v in rec["new"].items())


def replace_listed(rec, n=3):
    """The lines that changed, old → new, a few of them: what he reads to
    know what the edit did (the old text itself is in the Undo record)."""
    import difflib
    a, b = rec["old_text"].split("\n"), rec["text"].split("\n")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        old = " / ".join(x.strip() for x in a[i1:i2] if x.strip())[:120] or "(nothing)"
        new = " / ".join(x.strip() for x in b[j1:j2] if x.strip())[:120] or "(nothing)"
        out.append(f"\u201c{old}\u201d \u2192 \u201c{new}\u201d")
    more = f" (and {len(out) - n} more)" if len(out) > n else ""
    return "; ".join(out[:n]) + more if out else "no line changed"


def _err(text):
    try:
        return str(json.loads(text).get("error") or text)[:160]
    except (ValueError, AttributeError):
        return (text or "")[:160]


def now():
    """The clock the quiet rule reads (a test's to move)."""
    return time.time()


def title_shown(t):
    return f"\u201c{t}\u201d" if t else "(untitled)"


def title_detail(c):
    """For the log: a title line's entry, its title now and the new one
    (old is None when the row cannot be read)."""
    if not c or c.get("op") != "title":
        return {}
    row = get_row(c["id"])
    return {"op": "title", "id": c["id"], "old": (row or {}).get("title") if row else None, "new": c["text"]}


def note_apply(lines, who, tid, entry_id, ordered, log):
    """The CHANGES lines of an answer: the text listing them for the thread
    (with the undo record), and the records. Nothing is applied unless the
    captain's turn asked for a change, or when there are more than
    MAX_CHANGES."""
    if not lines:
        return "", []
    out, recs = [], []
    parsed = []
    for ln in lines:
        try:
            parsed.append((ln, parse_change(ln), None))
        except ValueError as e:
            parsed.append((ln, None, str(e)))
    if not ordered:
        out.append("**Proposed, not made** (your message did not ask for a change; reply \"yes, do it\" to have "
                   "them made):")
        out += [f"- `{ln}`" + (f" (would be refused: {why})" if why else "") for ln, _, why in parsed]
        log(dict(thread=tid, entry=entry_id, status="proposed", n=len(lines)))
        for ln, c, _ in parsed:
            if c is not None and c["op"] == "title":
                log(dict(thread=tid, entry=entry_id, status="proposed", line=ln[:300], **title_detail(c)))
        return "\n".join(out), []
    if len(lines) > MAX_CHANGES:
        out.append(f"**Not made**: {len(lines)} changes, over the {MAX_CHANGES} a turn may make. Nothing was written.")
        log(dict(thread=tid, entry=entry_id, status="refused", why="too many", n=len(lines)))
        for ln, c, _ in parsed:
            if c is not None and c["op"] == "title":
                log(dict(thread=tid, entry=entry_id, status="refused", why="too many", line=ln[:300],
                         **title_detail(c)))
        return "\n".join(out), []
    out.append("**Changes**")
    env = T.read_env()
    ready = bool(env.get(STEWARD_LOGIN[0]) and env.get(STEWARD_LOGIN[1]))
    for ln, c, why in parsed:
        if c is not None and not ready:
            rec, why = None, "the steward login is not set up on the server, so the crew cannot write yet"
        elif c is not None:
            rec, why = apply_change(c, who, tid, entry_id, now())
        else:
            rec = None
        if rec:
            recs.append(rec)
            if rec["op"] == "create":
                out.append(f"- created #{rec['id']} ({rec['kind']})" + (f" \u201c{rec['title']}\u201d" if rec["title"] else ""))
            elif rec["op"] == "end":
                out.append(f"- closed #{rec['id']} at {rec['at']}")
            elif rec["op"] == "title":
                out.append(f"- titled #{rec['id']}: {title_shown(rec['old_title'])} \u2192 {title_shown(rec['title'])}")
            elif rec["op"] == "set":
                out.append(f"- set #{rec['id']}: {set_listed(rec)}")
            elif rec["op"] == "replace":
                out.append(f"- edited the text of #{rec['id']}: {replace_listed(rec)}")
            elif rec["op"] in ("delete", "restore"):
                out.append(f"- {rec['op']}d #{rec['id']} ({rec['kind']}) {title_shown(rec['title'])}")
            else:
                first = rec["text"].strip().split("\n")[1:2]
                out.append(f"- added to #{rec['id']}: {first[0].lstrip('> ') if first else ''}")
            log(dict(thread=tid, entry=entry_id, status="applied", **rec,
                     **({"old": rec["old_title"], "new": rec["title"]} if rec["op"] == "title" else {})))
        else:
            out.append(f"- not done: `{ln}` ({why})")
            log(dict(thread=tid, entry=entry_id, status="refused", line=ln[:300], why=why, **title_detail(c)))
    if recs:
        out.append(f"```{UNDO_FENCE}\n" + "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n```")
    return "\n".join(out), recs


# ---- one turn ----------------------------------------------------------------

def fence(text, n):
    text = text or ""
    if len(text) > n:
        text = text[:n] + f"\n[... {len(text) - n} more characters]"
    return "<journal-data>\n" + text.replace("</journal-data>", "</journal-data >") + "\n</journal-data>"


def turn_order(fm, t, entry, now=None):
    """The message a note turn starts with (stdin)."""
    n = now or T.now_local()
    turns = t["turns"]
    shown = turns if len(turns) <= KEEP_TURNS + 1 else [turns[0]] + turns[-KEEP_TURNS:]
    out = [f"It is {n:%A %Y-%m-%d %H:%M} in {T.TZ.key} ({n.astimezone(dt.timezone.utc):%H:%M} UTC)."]
    if entry:
        out.append(f"The captain's entry #{entry['id']}, where he left the note (kind {entry.get('kind') or '-'}, "
                   f"written {entry.get('created_at_utc') or '-'} UTC, "
                   f"last_modified_at_utc {entry.get('last_modified_at_utc') or '-'}"
                   + (f", scheduled {entry.get('start_date')} to {entry.get('end_date') or '-'} UTC"
                      if entry.get("start_date") else "") + f"), titled {json.dumps(entry.get('title') or '')}:\n"
                   + fence(entry.get("content"), ENTRY_MAX))
    else:
        out.append(f"The captain's entry #{t['entry']} is gone; answer from the thread.")
    if len(shown) < len(turns):
        out.append(f"[{len(turns) - len(shown)} earlier turns left out]")
    for x in shown:
        if captain(x):
            out.append(f"The captain ({x['at']}):\n{x['text'][:TURN_MAX]}")
        else:
            out.append(f"You ({x['at']}):\n" + fence(x["text"], TURN_MAX))
    out.append("Answer the captain's last message.")
    return "\n\n".join(out)
