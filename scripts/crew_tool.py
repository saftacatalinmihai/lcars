#!/usr/bin/env python3
"""The one command a scheduled crew role has (scripts/crew.py runs them).

    crew_tool.py today                       the date and time in the captain's zone
    crew_tool.py list|get|stats|kinds ...    lcars-cli, read-only, as the crew login
    crew_tool.py agenda [YYYY-MM-DD]         the day: weather place, scheduled, notes, tasks, trips
    crew_tool.py onthisday [YYYY-MM-DD]      the same day in every earlier year
    crew_tool.py month [YYYY-MM]             a month: counts per kind, the titles
    crew_tool.py weekstats [YYYY-MM-DD]      the seven days ending then, with numbers
    crew_tool.py counsel [day] [weeks] [--part N]  a week's personal logs, sleep, the weeks before
    crew_tool.py hygiene [days]              secret-shaped strings (masked), candidate duplicates,
                                             kinds, dates, stale tasks; the ledger of the
                                             yeoman's earlier proposals
    crew_tool.py trip [<id>]                 trips ended since the historian last posted; with
                                             an id, one trip planned against actual
    crew_tool.py audit                       security facts about this box (read-only)
    crew_tool.py docs                        the docs, and the code changed since each
    crew_tool.py post --title T [--urgent]   the runner's, never the agent's (body on stdin)

It is the same shape as ~/.claude/scripts/lcars-link.sh, the linker's
wrapper, for the same two reasons:

- The credentials stay out of the agent's command lines. They are read here
  from ~/.env (LCARS_CREW_USER, LCARS_CREW_PASS), so an agent never sees a
  password in an argv and never needs `. ~/.env`, which the permission
  checker refuses anyway.
- The agent is allowlisted for this file's read verbs one by one
  (`Bash(<this file> agenda:*)`, ...), so a run under --permission-mode
  dontAsk cannot reach anything else, and cannot stop at a prompt nobody is
  there to answer.

Writing is `post`, and only the runner calls it: it posts the agent's final
answer as one crew_<role> entry, and a line starting "URGENT:" as one
task_crew. The agent is never allowlisted for `post`, and it refuses to run
under CREW_IN_AGENT (set for the claude child) as a second wall. A third is
the server's: the crew login can write only crew_* and task_crew kinds.

The helpers (agenda, hygiene, weekstats, ...) do the fetching and the
arithmetic in Python. Counting sleep hours or finding twin rows is not
judgement, a model gets sums wrong, and every lcars-cli call an agent makes
is a turn - a turn re-reads the whole conversation. One call that prints a
page of facts is what keeps a run to a few cents.
"""

import base64
import datetime as dt
import glob
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOME = os.path.expanduser("~")
sys.path.insert(0, HERE)
from lcars_linker import is_gym  # noqa: E402  (what the measure pass counts as gym)
import lcars_roles  # noqa: E402  (kinds by role, docs/design/kinds.md)
ENV_FILE = os.environ.get("LCARS_CREW_ENV") or os.path.join(HOME, ".env")
READ_CLI = {"list", "get", "stats", "kinds"}
# lcars-cli options that would leave the server (or the crew login) behind
CLI_REFUSED = ("--db", "--db-path", "--url", "--user", "--password", "--edit", "-e")
# The task role's kind and its lists (<task>_<list>); the crew's urgent
# asks are <task>_crew (urgent_kind)
# Titles the server gives a row posted with no title: the linker's to fix, so
# the yeoman leaves them alone (see crew/yeoman.md).
PLACEHOLDER_TITLES = {"", "http entry"}
# Kinds that are someone else's export and stay frozen (the linker's list
# too): the `imported` role's
IMPORTED_KINDS = lcars_roles.Lazy(lambda: roles().kinds("imported"), key=lambda: _ROLES)
_ROLES = None


def roles():
    """The journal's mapping of roles to kinds, asked once a run
    (GET /kinds/roles with the crew's login; lcars_roles.py)."""
    global _ROLES
    if _ROLES is None:
        def get():
            status, text = http("GET", "/kinds/roles")
            if status != 200:
                raise RuntimeError(f"GET /kinds/roles: {status} {text[:80]}")
            return json.loads(text)
        _ROLES = lcars_roles.load(get)
    return _ROLES


def task_kind():
    """The task role's kind: Reminders' root list, and <kind>_<list> its lists."""
    return roles().kind("task")


# A prompt's kinds (crew/*.md, crew.py's blocks): <kind:log> is the log
# role's kind, <kinds:imported> a list role's, comma-joined. The prompts
# name roles, and the journal's own kinds are filled in at the run.
KIND_TOKEN = re.compile(r"<(kind|kinds):([a-z_]+)>")


def fill_kinds(text):
    if "<kind" not in text:
        return text
    return KIND_TOKEN.sub(lambda m: roles().kind(m[2]) if m[1] == "kind" else ", ".join(roles().kinds(m[2])), text)


def never_write():
    """The kinds no crew member writes: the logins' own, their reminders,
    and the imports' frozen ones (the crew's prompts say this list)."""
    return ", ".join(("crew_*", "no1_*", roles().ask("crew"), roles().ask("no1"), *IMPORTED_KINDS))


def urgent_kind():
    """Where an urgent finding goes: the crew's reminders, <task>_crew."""
    return roles().ask("crew")


def die(msg, code=2):
    print("crew_tool.py: " + msg, file=sys.stderr)
    sys.exit(code)


# ---- credentials and the server ---------------------------------------------

def read_env(path=None):
    """KEY=VALUE lines (an `export ` prefix allowed), parsed, never sourced."""
    env = {}
    try:
        with open(path or ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                k, eq, v = line.partition("=")
                if eq and k and not k.startswith("#"):
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def system_zone():
    """The box's own zone by name (/etc/timezone, else the /etc/localtime
    link's zoneinfo path), or UTC when it has none to give."""
    try:
        with open("/etc/timezone") as f:
            name = f.read().strip()
        if name:
            return name
    except OSError:
        pass
    link = os.path.realpath("/etc/localtime")
    return link.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in link else "UTC"


def crew_zone():
    """The captain's zone: LCARS_CREW_TZ (a test's), else LCARS_TZ from the
    environment or ENV_FILE (a timer's unit does not source ~/.env), else
    the box's own. The box may live in another zone than its owner (the
    VPS runs seven hours behind), and a bare `date` there is then the wrong
    calendar day half the evening, so every day here is the captain's. A
    name zoneinfo does not know falls back to the box's, said on stderr."""
    name = (os.environ.get("LCARS_CREW_TZ") or os.environ.get("LCARS_TZ") or read_env().get("LCARS_TZ")
            or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ValueError, KeyError, OSError):  # ZoneInfoNotFoundError is a KeyError
            print(f"crew: LCARS_TZ={name!r} is no zone; the box's own is used", file=sys.stderr)
    try:
        return ZoneInfo(system_zone())
    except (ValueError, KeyError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return ZoneInfo("UTC")


TZ = crew_zone()


def owner():
    """The journal owner's name, LCARS_OWNER (the environment first, then
    ENV_FILE: a timer's unit does not source ~/.env), or "" - a prompt then
    says only "the captain". Kept out of the code so the public tree names
    nobody (docs/design/open-source.md)."""
    return (os.environ.get("LCARS_OWNER") or read_env().get("LCARS_OWNER") or "").strip()


def owners(fallback="the captain's"):
    """The owner's name in the possessive, for a prompt: "the captain's
    (Ana's)", or fallback alone when no name is set."""
    n = owner()
    return f"{fallback} ({n}'s)" if n else fallback


# a limited login's pair of keys in ENV_FILE (lcars_logins.h): the crew's,
# or Number One's (no1.py)
CREW_LOGIN = ("LCARS_CREW_USER", "LCARS_CREW_PASS")
NO1_LOGIN = ("LCARS_NO1_USER", "LCARS_NO1_PASS")


def creds(login=CREW_LOGIN):
    env = read_env()
    user, pw = env.get(login[0]), env.get(login[1])
    if not user or not pw:
        die(f"no {login[0]}/{login[1]} in {ENV_FILE}", 1)
    url = os.environ.get("LCARS_URL") or env.get("LCARS_CREW_URL") or "http://127.0.0.1:8080"
    return url.rstrip("/"), user, pw


def http(method, path, body=None, timeout=60, login=CREW_LOGIN):
    url, user, pw = creds(login)
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    # raw UTF-8, not \u escapes: the server's JSON reader keeps "\u00b7" as
    # the letters "u00b7" (seen on a scratch server), so "·" must go as bytes
    req = urllib.request.Request(url + path, method=method,
                                 data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Authorization": "Basic " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, json.dumps({"error": str(e)})


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


def entries(**q):
    """GET /entries with these filters; a list of rows, or die."""
    q.setdefault("limit", 1000)
    status, text = http("GET", "/entries?" + urllib.parse.urlencode(q))
    if status != 200:
        die(f"GET /entries {q}: {status} {text[:200]}", 1)
    rows = json.loads(text)
    return rows if isinstance(rows, list) else []


def entries_all(**q):
    """Every row of a filter, paged. The server builds a response in a 1MB
    arena and answers 500 past it, so a page with bodies is a few hundred
    rows, and halves again when a page of long ones still does not fit."""
    size = 200 if q.get("content", 1) else 1000
    rows, off = [], 0
    while True:
        status, text = http("GET", "/entries?" + urllib.parse.urlencode(dict(q, limit=size, offset=off)))
        if status == 500 and "too large" in text and size > 10:
            size //= 2
            continue
        if status != 200:
            die(f"GET /entries {q}: {status} {text[:200]}", 1)
        page = json.loads(text)
        rows += page
        off += len(page)
        if len(page) < size or off >= 20000:
            return rows


def kinds():
    status, text = http("GET", "/kinds")
    if status != 200:
        die(f"GET /kinds: {status} {text[:200]}", 1)
    j = json.loads(text)
    rows = j if isinstance(j, list) else j.get("kinds", [])
    return {r["kind"]: r.get("count", 0) for r in rows if isinstance(r, dict) and "kind" in r}


# ---- days and stamps ---------------------------------------------------------

def now_local():
    return dt.datetime.now(TZ)


def parse_day(s, default):
    if not s:
        return default
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        die(f"not a date: {s} (YYYY-MM-DD)")


def utc_window(day, days=1):
    """The captain's local day(s) as UTC 'YYYY-MM-DD HH:MM:SS' bounds."""
    start = dt.datetime.combine(day, dt.time(), TZ)
    end = start + dt.timedelta(days=days) - dt.timedelta(seconds=1)
    f = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return f(start), f(end)


def stamp(s):
    """A journal UTC stamp as an aware datetime, or None."""
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def local(s, fmt="%a %d %b %H:%M"):
    t = stamp(s)
    return t.astimezone(TZ).strftime(fmt) if t else "-"


def snippet(text, n=160):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def line(r, extra=""):
    t = (r.get("title") or "").strip() or "(untitled)"
    return f"#{r['id']} [{r.get('kind', '')}] {snippet(t, 90)}{extra}"


# ---- verbs -------------------------------------------------------------------

def cmd_today(_a):
    n = now_local()
    print(f"local: {n:%A %Y-%m-%d %H:%M} ({TZ.key})")
    print(f"utc:   {n.astimezone(dt.timezone.utc):%Y-%m-%d %H:%M}")
    return 0


def cmd_cli(verb, a):
    for x in a:
        if x in CLI_REFUSED or any(x.startswith(o + "=") for o in CLI_REFUSED):
            die(f"{x} is not allowed: the journal is read through the server, as the crew login")
    url, user, pw = creds()
    cli = os.environ.get("LCARS_CLI") or next(
        (p for p in (os.path.join(REPO, "bin", "lcars-cli"), os.path.join(REPO, "lcars-cli", "lcars-cli"),
                     os.path.join(REPO, "lcars-cli"),
                     shutil.which("lcars-cli") or "") if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)
    if not cli:
        die("lcars-cli is not built (make lcars-cli)", 1)
    env = dict(os.environ, LCARS_URL=url, LCARS_AUTH_USER=user, LCARS_AUTH_PASS=pw)
    if os.environ.get("CREW_FENCE"):
        p = subprocess.run([cli, verb, *a], env=env, stdout=subprocess.PIPE, text=True)
        sys.stdout.write(p.stdout)
        return p.returncode
    return subprocess.run([cli, verb, *a], env=env).returncode


TRIP_RECENT_DAYS = 3
STALE_TASK_DAYS = 14


def own_kind(k):
    """A kind the captain writes: not the crew's or Number One's
    (crew_*, <task>_crew, no1_*, <task>_no1)."""
    k = k or ""
    return not (k.startswith(("crew_", "no1_")) or k in (roles().ask("crew"), roles().ask("no1")))


# kinds whose stamp is not a moment the captain was writing: series a tap or a sync
# makes (the child's included), imports, and the page's own settings
NOT_WRITING = lcars_roles.Lazy(lambda: (*(roles().kind(r) for r in ("sleep", "child_sleep", "drive", "workout",
                                                                       "child_vocab", "counter", "template")),
                                        "settings", *IMPORTED_KINDS), key=lambda: _ROLES)


def trip_first_stop(r):
    """(name, lat, lon) of a trip's first stop: the trip block's points[0]
    (the page's trip planner writes it), else its "1. <stop> — hh:mm" line,
    else the title."""
    m = re.search(r"```json trip\s*\n(.*?)\n```", r.get("content") or "", re.S)
    if m:
        try:
            p = (json.loads(m.group(1)).get("points") or [None])[0]
        except (ValueError, AttributeError):
            p = None
        if isinstance(p, dict) and (p.get("name") or "").strip():
            return p["name"].strip(), p.get("lat"), p.get("lon")
    for ln in (r.get("content") or "").splitlines():
        m = re.match(r"\s*1\.\s+(.+?)(?:\s+—\s+\d{1,2}:\d\d.*)?$", ln)
        if m:
            return m.group(1).strip(), None, None
    return (r.get("title") or "").strip() or None, None, None


def home_place(settings_rows):
    """The captain's home, for the weather: a "home" key in a settings entry
    holding JSON (the views entry's shape), or a settings entry titled
    "home" whose text is the place; the lowest id wins, as with views. Else
    the city of the captain's zone (America/New_York: "New York"), or None
    for a zone with no city (UTC): the brief then has no forecast at home."""
    for r in sorted(settings_rows, key=lambda r: r.get("id") or 0):
        if r.get("deleted"):
            continue
        text = (r.get("content") or "").strip()
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, dict) and isinstance(d.get("home"), str) and d["home"].strip():
            return d["home"].strip()
        if (r.get("title") or "").strip().lower() == "home" and not isinstance(d, (dict, list)):
            first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            if first:
                return first
    return zone_city(TZ.key)


def zone_city(key):
    """The city an IANA zone is named for, or None (UTC, Etc/GMT+2)."""
    if "/" not in key or key.startswith("Etc/"):
        return None
    return key.rsplit("/", 1)[1].replace("_", " ")


def weather_place(trips, day, now_utc, home):
    """Where the morning brief's forecast is for, and why, as
    (place, lat, lon, why). The rule (crew/ops.md step 3):
      1. a trip running on `day` (it starts that day, or started before and
         its end_date is that day or later): its first stop;
      2. else the newest trip started in the last three days, if it has not
         ended (end_date empty, or still ahead) - the newest only: a later
         trip is where the captain went next, so an older one left open is not;
      3. else home.
    Ties on the start go to the higher id, the later save of the trip."""
    lo, hi = utc_window(day)
    since = utc_window(day - dt.timedelta(days=TRIP_RECENT_DAYS))[0]
    now = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    by_new = sorted((r for r in trips if r.get("start_date") and not r.get("deleted")),
                    key=lambda r: (r["start_date"], r.get("id") or 0), reverse=True)
    for r in by_new:
        s, e = r["start_date"], r.get("end_date") or ""
        if lo <= s <= hi or (s <= hi and e >= lo):
            name, lat, lon = trip_first_stop(r)
            if name:
                return name, lat, lon, f"trip #{r['id']} running today"
    recent = [r for r in by_new if since <= r["start_date"] <= now]
    if recent:
        r = recent[0]
        e = r.get("end_date") or ""
        if not e or e > now:
            name, lat, lon = trip_first_stop(r)
            if name:
                return name, lat, lon, f"trip #{r['id']} started {local(r['start_date'], '%a %d %b')}, not ended"
        return home, None, None, f"home: trip #{r['id']} ended {local(e, '%a %d %b %H:%M')}"
    return home, None, None, "home: no trip in the last three days"


TOMORROW_RE = re.compile(r"^\s*(?:[-*+]\s*)?(?:\[[ xX]?\]\s*)?(for tomorrow\b|tomorrow\s*:|todo\b)\s*[-:–—]?\s*(.*)$", re.I)


def tomorrow_lines(rows, tasks):
    """(entry id, text) of the lines in yesterday's own entries meant for
    today: "for tomorrow ...", "tomorrow: ...", or a "TODO ..." no task
    entry already holds (its text and a task's title, one inside the other).
    Only the captain's own kinds (own_kind): never a crew or Number One row."""
    titles = [_norm(t.get("title") or "") for t in tasks]
    titles = [t for t in titles if len(t) >= 3]
    out = []
    for r in sorted(rows, key=lambda r: (r.get("created_at_utc") or "", r.get("id") or 0)):
        if not own_kind(r.get("kind")) or r.get("deleted"):
            continue
        for ln in (r.get("content") or "").splitlines():
            m = TOMORROW_RE.match(ln)
            if not m or not m.group(2).strip():
                continue
            text = m.group(2).strip()
            if m.group(1).lower() == "todo":
                n = _norm(text)
                if any(t in n or n in t for t in titles):
                    continue
            out.append((r["id"], text))
    return out


def stale_tasks(tasks, now_utc):
    """The open tasks with no due date, opened more than two weeks ago: the
    brief puts them on one line, not one each, every morning."""
    cut = (now_utc - dt.timedelta(days=STALE_TASK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    return [r for r in tasks if not r.get("start_date") and not r.get("done_bool")
            and (r.get("created_at_utc") or "9") < cut]


def cmd_agenda(a):
    day = parse_day(a[0] if a else "", now_local().date())
    lo, hi = utc_window(day)
    now_utc = dt.datetime.now(dt.timezone.utc)
    print(f"Agenda for {day:%A %Y-%m-%d} ({TZ.key}; times below are local)")
    # the weather's place first: the role fetches the forecast for it, and
    # does not decide it (crew/ops.md step 3)
    trips = entries(kind=roles().kind("trip"), order="start", dir="desc", limit=20, content=1)
    place, lat, lon, why = weather_place(trips, day, now_utc, home_place(entries(kind="settings", content=1)))
    at = f" (lat {lat}, lon {lon})" if lat is not None and lon is not None else ""
    if place is None:
        # a zone with no city and no "home" settings entry: nothing to ask for
        print(f"\nWeather place: none - {why}, and no home (a settings entry titled \"home\")")
    else:
        print(f"\nWeather place: {place}{at} - {why}")
    # scheduled_date is a UTC-day overlap test; the local day touches two
    seen, sched = set(), []
    for d in sorted({lo[:10], hi[:10]}):
        for r in entries(scheduled_date=d, order="start", dir="asc", content=0):
            s, e = r.get("start_date") or "", r.get("end_date") or r.get("start_date") or ""
            if r["id"] not in seen and s <= hi and e >= lo:
                seen.add(r["id"])
                sched.append(r)
    print(f"\nScheduled today ({len(sched)}):")
    for r in sorted(sched, key=lambda r: r.get("start_date") or ""):
        end = f"–{local(r['end_date'], '%H:%M')}" if r.get("end_date") and r["end_date"] != r["start_date"] else ""
        done = " (done)" if r.get("done_bool") else ""
        print(f"  {local(r['start_date'], '%H:%M')}{end}  {line(r)}{done}")
    if not sched:
        print("  nothing")
    tk = sorted(k for k in kinds() if k == task_kind() or k.startswith(task_kind() + "_"))
    open_ = [r for k in tk for r in entries(kind=k, done=0, order="created", dir="asc", content=0)]
    ylo = utc_window(day - dt.timedelta(days=1))[0]
    notes = tomorrow_lines(entries_all(since=ylo, until=utc_window(day - dt.timedelta(days=1))[1], order="created",
                                       dir="asc", content=1),
                           open_ + [r for k in tk for r in entries(kind=k, since=ylo, content=0)])
    print(f"\nFor today, from yesterday's notes ({len(notes)}):")
    for i, text in notes:
        print(f"  #{i}: {snippet(text, 200)}")
    if not notes:
        print("  none")
    stale = stale_tasks(open_, now_utc)
    stale_ids = {r["id"] for r in stale}
    print("\nOpen tasks:")
    n = 0
    for r in open_:
        if r["id"] in stale_ids:
            continue
        due = f", due {local(r['start_date'])}" if r.get("start_date") else ""
        overdue = " OVERDUE" if r.get("start_date") and (r.get("end_date") or r["start_date"]) < lo else ""
        print(f"  {line(r)} (since {local(r.get('created_at_utc'), '%d %b')}{due}){overdue}")
        n += 1
    if not n:
        print("  none")
    if stale:
        print(f"\nOlder tasks, open over {STALE_TASK_DAYS} days with no due date ({len(stale)}; one line in the brief):")
        print("  " + ", ".join(f"#{r['id']} {snippet((r.get('title') or '').strip() or '(untitled)', 40)}"
                               f" (since {local(r.get('created_at_utc'), '%d %b')})" for r in stale))
        if day.weekday() == 0:
            print("  Monday: ask once whether these still matter.")
    recent = [r for r in trips if (r.get("start_date") or "") and r["start_date"] >= utc_window(day - dt.timedelta(days=14))[0]]
    print("\nTrips, the last two weeks and ahead (the newest first):")
    for r in recent[:6]:
        end = f" → {local(r['end_date'], '%a %d %b %H:%M')}" if r.get("end_date") else " (no end)"
        print(f"  {local(r['start_date'], '%a %d %b %H:%M')}{end}  {line(r)}  first stop: {trip_first_stop(r)[0] or '-'}")
    if not recent:
        print("  none")
    return 0


def cmd_onthisday(a):
    day = parse_day(a[0] if a else "", now_local().date())
    oldest = entries(order="created", dir="asc", limit=1, content=0)
    first = int((oldest[0].get("created_at_utc") or str(day.year))[:4]) if oldest else day.year
    print(f"On this day, {day:%d %B}, in earlier years (local days, newest year first)")
    any_ = False
    for y in range(day.year - 1, first - 1, -1):
        try:
            d = day.replace(year=y)
        except ValueError:      # 29 February
            continue
        lo, hi = utc_window(d)
        rows = entries(since=lo, until=hi, order="created", dir="asc", limit=40, content=1)
        if not rows:
            continue
        any_ = True
        print(f"\n{y} ({len(rows)} entries):")
        for r in rows[:15]:
            print(f"  {local(r.get('created_at_utc'), '%H:%M')}  {line(r)}: {snippet(r.get('content'), 220)}")
        if len(rows) > 15:
            print(f"  ... and {len(rows) - 15} more (crew_tool.py list --date {d} for all)")
    if not any_:
        print("  nothing in earlier years")
    return 0


def cmd_month(a):
    today = now_local().date()
    if a:
        try:
            y, m = map(int, a[0].split("-"))
        except ValueError:
            die("month YYYY-MM")
    else:   # the month that has just ended
        prev = today.replace(day=1) - dt.timedelta(days=1)
        y, m = prev.year, prev.month
    start = dt.date(y, m, 1)
    days = ((start + dt.timedelta(days=32)).replace(day=1) - start).days
    lo, hi = utc_window(start, days)
    rows = entries_all(since=lo, until=hi, order="created", dir="asc", content=0)
    print(f"{start:%B %Y}: {len(rows)} entries")
    c = Counter(r.get("kind", "") for r in rows)
    print("by kind: " + ", ".join(f"{k} {n}" for k, n in c.most_common()))
    per_week = Counter(stamp(r["created_at_utc"]).astimezone(TZ).isocalendar()[1] for r in rows if stamp(r.get("created_at_utc")))
    print("by ISO week: " + ", ".join(f"w{w} {n}" for w, n in sorted(per_week.items())))
    # the rows that say what happened; pages and people are the wiki, and the
    # series rows are numbers - both counted above, not listed
    skip = {*(roles().kind(x) for x in ("sleep", "child_sleep", "drive", "child_vocab", "page", "person", "template")),
            "bookmark", "settings", *IMPORTED_KINDS}
    keep = [r for r in rows if r.get("kind") not in skip]
    print(f"\nTitles ({len(keep)}; series rows, pages, people and bookmarks are counted above, not listed):")
    for r in keep[:300]:
        print(f"  {local(r.get('created_at_utc'), '%d %b')}  {line(r)}")
    if len(keep) > 300:
        print(f"  ... {len(keep) - 300} more")
    return 0


def _week(end, days=7):
    """The week's rows, and the small hours after it: the last evening's
    late entries are its bedtime (week_numbers counts only the week)."""
    lo, hi = utc_window(end - dt.timedelta(days=days - 1), days)
    tail = (dt.datetime.combine(end + dt.timedelta(days=1), dt.time(EVENING_ENDS), TZ)
            .astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    return entries_all(since=lo, until=tail, order="created", dir="asc", content=1)


# an evening runs from 18:00 to 04:00 the next morning, local; its last own
# entry is the nearest the journal has to a bedtime
EVENING_STARTS, EVENING_ENDS = 18, 4


def _evening(t):
    """The local day whose evening a moment belongs to, or None by day."""
    t = t.astimezone(TZ)
    if t.hour >= EVENING_STARTS:
        return t.date()
    if t.hour < EVENING_ENDS:
        return t.date() - dt.timedelta(days=1)
    return None


def _clock(minutes):
    """Minutes after the evening's midnight-before (24:30 is 00:30) as HH:MM."""
    m = int(round(minutes)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _night_hours(rows):
    """Each night's sleep, by the evening it began: a row's span (the
    stopwatch's start_date/end_date, which measure also turns into its
    value_float), else a measured end row's hours (value_float, written at
    waking, so the evening before). The span first: a span row is written
    in the evening, and its measured value is not the next night's."""
    out = {}
    for r in rows:
        if r.get("kind") != roles().kind("sleep"):
            continue
        v = float(r.get("value_float") or 0)
        s, e = stamp(r.get("start_date")), stamp(r.get("end_date"))
        if s and e and e > s:
            v, ev = v or (e - s).total_seconds() / 3600, _evening(s)
        elif v > 0:
            w = stamp(r.get("created_at_utc"))
            ev = w.astimezone(TZ).date() - dt.timedelta(days=1) if w else None
        else:
            continue
        if ev and 0 < v < 20:
            out.setdefault(ev, round(v, 1))
    return out


def bedtimes(rows, days=None):
    """The last own entry of each evening (local), with the night's sleep
    beside it; and their average clock time, after-midnight ones counted
    past 24:00 so 23:30 and 00:30 average to midnight."""
    last = {}
    for r in rows:
        t = stamp(r.get("created_at_utc"))
        if not t or not own_kind(r.get("kind")) or r.get("kind") in NOT_WRITING or r.get("deleted"):
            continue
        ev = _evening(t)
        if ev is None or (days is not None and ev not in days):
            continue
        lt = t.astimezone(TZ)
        m = (lt.date() - ev).days * 24 * 60 + lt.hour * 60 + lt.minute
        if m > last.get(ev, -1):
            last[ev] = m
    sleep = _night_hours(rows)
    nights = [(ev, _clock(m), sleep.get(ev)) for ev, m in sorted(last.items())]
    avg = _clock(sum(last.values()) / len(last)) if last else None
    hrs = [h for _, _, h in nights if h]
    return {"n": len(nights), "avg": avg, "nights": nights,
            "sleep_avg": round(sum(hrs) / len(hrs), 1) if hrs else None}


def week_numbers(rows, days=None):
    """The arithmetic of a week of rows, as a dict (unit-tested). With days
    (the week's local dates), rows past them count only towards bedtimes."""
    bed = bedtimes(rows, days)
    if days is not None:
        rows = [r for r in rows if stamp(r.get("created_at_utc")) and stamp(r["created_at_utc"]).astimezone(TZ).date() in days]
    out = {"entries": len(rows), "by_kind": Counter(r.get("kind", "") for r in rows),
           "by_day": Counter(), "words": 0, "series": {}}
    prose = {roles().kind(x) for x in ("log", "work_log", "meeting", "page", "project")}
    for r in rows:
        t = stamp(r.get("created_at_utc"))
        if t:
            out["by_day"][t.astimezone(TZ).strftime("%a %d")] += 1
        if r.get("kind") in prose:
            out["words"] += len((r.get("content") or "").split())
    # sleep and drive end rows, and stopwatch-timed rows, carry the measured
    # value (lcars-link.sh measure); a gym session is a row of the log
    # role's kind the measure pass recognises by is_gym, and only a timed
    # one has a value. Keyed by the kind, as the journal names it.
    for kind, unit in ((roles().kind("sleep"), "h"), (roles().kind("child_sleep"), "h"),
                       (roles().kind("drive"), "min"), ("gym", "min")):
        is_kind = (lambda r: is_gym(r, roles().kind("log"))) if kind == "gym" else (lambda r, k=kind: r.get("kind") == k)
        v = [float(r.get("value_float") or 0) for r in rows if is_kind(r) and float(r.get("value_float") or 0) > 0]
        if v:
            out["series"][kind] = {"unit": unit, "n": len(v), "total": round(sum(v), 2), "avg": round(sum(v) / len(v), 2),
                                   "min": round(min(v), 2), "max": round(max(v), 2)}
    vocab = [r for r in rows if r.get("kind") == roles().kind("child_vocab")]
    out["vocab"] = [(r.get("title") or "").strip() for r in vocab]
    out["vocab_total"] = max([int(r.get("value_int") or 0) for r in vocab] or [0])
    # counter rows ("log a diaper" in the page): one of a thing each, by title
    out["counters"] = Counter()
    for r in rows:
        if r.get("kind") == roles().kind("counter") and not r.get("deleted"):
            out["counters"][(r.get("title") or "").strip().lower() or "?"] += int(r.get("value_int") or 0) or 1
    out["bedtime"] = bed
    return out


def _print_week(label, n):
    print(f"{label}: {n['entries']} entries, {n['words']} words written in logs and pages")
    print("  by kind: " + ", ".join(f"{k} {c}" for k, c in n["by_kind"].most_common()))
    print("  by day:  " + ", ".join(f"{d} {c}" for d, c in n["by_day"].items()))
    for k, s in n["series"].items():
        print(f"  {k}: {s['n']} measured, avg {s['avg']}{s['unit']}, min {s['min']}, max {s['max']}, total {s['total']}{s['unit']}")
    b = n["bedtime"]
    if b["n"]:
        sl = f", sleep {b['sleep_avg']}h avg" if b["sleep_avg"] else ""
        print(f"  bedtime (last own entry of the evening): avg {b['avg']} over {b['n']} evenings{sl}; "
              + ", ".join(f"{ev:%a} {c}" + (f" {h}h" if h else "") for ev, c, h in b["nights"]))
    if n["counters"]:
        print("  counted: " + ", ".join(f"{t} {c}" for t, c in n["counters"].most_common()))
    if n["vocab"]:
        print(f"  {roles().kind('child_vocab')}: {len(n['vocab'])} new ({', '.join(n['vocab'][:40])}); word #{n['vocab_total']} so far")


def cmd_weekstats(a):
    end = parse_day(a[0] if a else "", now_local().date() - dt.timedelta(days=1))
    span = lambda e: {e - dt.timedelta(days=i) for i in range(7)}
    pend = end - dt.timedelta(days=7)
    this, prev = week_numbers(_week(end), span(end)), week_numbers(_week(pend), span(pend))
    _print_week(f"Week {end - dt.timedelta(days=6):%a %d %b} – {end:%a %d %b %Y}", this)
    print()
    _print_week(f"Week before ({end - dt.timedelta(days=13):%d %b} – {end - dt.timedelta(days=7):%d %b})", prev)
    return 0


# the log role's kind and the imports' (past years were written elsewhere)
COUNSEL_KINDS = lcars_roles.Lazy(lambda: (roles().kind("log"), *IMPORTED_KINDS), key=lambda: _ROLES)
# A week's log is read whole up to this; past it, `get <id>` has the rest.
# Most are a dictated paragraph; the cap keeps one long night from being
# the whole run's input.
COUNSEL_FULL_CHARS = 2500
# Baseline weeks listed log by log; the older ones get a line a day
COUNSEL_DETAIL_WEEKS = 4
# One page of `counsel`: under what Claude Code shows of a Bash result
COUNSEL_PAGE_CHARS = 24000


def _plain(text):
    """A log as words: images and URLs out, [[links]] unbracketed. They are
    tokens the counselor pays for on every turn and reads nothing in."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", text or "")
    text = re.sub(r"https?://\S+", "[link]", text)
    return text.replace("[[", "").replace("]]", "")


def _title(r):
    """The linker's title, without the date it starts with; "" for none."""
    t = re.sub(r"^\d{4}-\d{2}-\d{2}\s*-?\s*", "", (r.get("title") or "").strip())
    return "" if t.lower() in PLACEHOLDER_TITLES else _plain(t)


def _local_day(r, field="created_at_utc"):
    t = stamp(r.get(field))
    return t.astimezone(TZ).date() if t else None


def counsel_digest(end, week, base, sleep, past, weeks):
    """The counselor's reading, as lines (unit-tested): the week ending on
    `end` in full, the nights' sleep, the `weeks` before it as numbers and
    one line per log, and the same week in earlier years from `past`
    (personal logs and the imported journals). Rows are GET /entries rows;
    `sleep` holds the sleep rows of the whole span."""
    words = lambda rs: sum(len((r.get("content") or "").split()) for r in rs)
    live = lambda rs: [r for r in rs if not r.get("deleted")]
    week, base, past = live(week), live(base), live(past)
    # a night belongs to the day it ends on: the end row carries its hours
    nights = defaultdict(float)
    for r in live(sleep):
        v, d = float(r.get("value_float") or 0), _local_day(r)
        if v > 0 and d:
            nights[d] += v
    start = end - dt.timedelta(days=6)
    out = [f"Personal logs, {start:%a %d %b} – {end:%a %d %b %Y} ({TZ.key}; times local): "
           f"{len(week)} logs, {words(week)} words"]
    for r in sorted(week, key=lambda r: r.get("created_at_utc") or ""):
        body = _plain(r.get("content")).strip()
        more = (f"\n  [... {len(body) - COUNSEL_FULL_CHARS} more chars: get {r['id']}]"
                if len(body) > COUNSEL_FULL_CHARS else "")
        title = f" {snippet(_title(r), 90)}" if _title(r) else ""
        out.append(f"\n#{r['id']} {local(r.get('created_at_utc'), '%a %d %b %H:%M')}{title}\n"
                   + body[:COUNSEL_FULL_CHARS] + more)
    if not week:
        out.append("  none this week")
    out.append("\nSleep, by the day each night ended (hours):")
    days = [start + dt.timedelta(days=i) for i in range(7)]
    out.append("  " + ", ".join(f"{d:%a %d} {nights[d]:.1f}" if d in nights else f"{d:%a %d} -" for d in days))
    wk = [nights[d] for d in days if d in nights]
    if wk:
        out.append(f"  this week: avg {sum(wk) / len(wk):.1f}h over {len(wk)} nights, min {min(wk):.1f}, max {max(wk):.1f}")
    # the baseline, newest week first: what "usual" is lately. A line per
    # log for the nearest weeks; further back a line per day, ids first, as
    # a week runs to a hundred short logs and every line is re-read each turn
    out.append(f"\nBaseline, the {weeks} weeks before (newest first): logs, words, sleep; a line per log "
               f"(its title, or its first words) for the first {COUNSEL_DETAIL_WEEKS}, then a line per day")
    gist = lambda r, n: snippet(_title(r), n) or snippet(_plain(r.get("content")), n)
    for i in range(1, weeks + 1):
        w_end = end - dt.timedelta(days=7 * i)
        w_start = w_end - dt.timedelta(days=6)
        rows = sorted((r for r in base if (d := _local_day(r)) and w_start <= d <= w_end),
                      key=lambda r: r.get("created_at_utc") or "")
        sl = [nights[w_start + dt.timedelta(days=j)] for j in range(7) if w_start + dt.timedelta(days=j) in nights]
        s = f", sleep avg {sum(sl) / len(sl):.1f}h ({len(sl)} nights)" if sl else ", sleep not recorded"
        out.append(f"\nweek {w_start:%d %b} – {w_end:%d %b}: {len(rows)} logs, {words(rows)} words{s}")
        if i <= COUNSEL_DETAIL_WEEKS:
            for r in rows:
                # the title is the linker's one-line summary: a twelfth of the body
                out.append(f"  #{r['id']} {local(r.get('created_at_utc'), '%a %d %H:%M')}: {gist(r, 110)}")
            continue
        by_day = defaultdict(list)
        for r in rows:
            by_day[_local_day(r)].append(r)
        for d in sorted(by_day):
            out.append(snippet(f"  {d:%a %d}: " + " · ".join(f"#{r['id']} {gist(r, 40)}" for r in by_day[d]), 260))
    if past:
        out.append("\nThe same days in earlier years (personal logs and the imported journals):")
        for r in sorted(past, key=lambda r: r.get("created_at_utc") or "", reverse=True):
            out.append(f"  #{r['id']} [{r.get('kind')}] {local(r.get('created_at_utc'), '%d %b %Y')}: "
                       f"{snippet(_title(r) or _plain(r.get('content')), 240)}")
    return out


def pages(lines, size):
    """Lines in pages of at most `size` characters, never splitting a line
    (a long log is one line here); a line longer than a page is its own."""
    out, cur, n = [], [], 0
    for ln in lines:
        if cur and n + len(ln) + 1 > size:
            out.append(cur)
            cur, n = [], 0
        cur.append(ln)
        n += len(ln) + 1
    return out + [cur] if cur else out or [[]]


def cmd_counsel(a):
    part = 1
    if "--part" in a:
        i = a.index("--part")
        try:
            part = int(a[i + 1])
        except (IndexError, ValueError):
            die("counsel [YYYY-MM-DD] [weeks] [--part N]")
        a = a[:i] + a[i + 2:]
    end = parse_day(a[0] if a else "", now_local().date() - dt.timedelta(days=1))
    weeks = int(a[1]) if len(a) > 1 and a[1].isdigit() else 12
    weeks = max(1, min(weeks, 26))
    lo, hi = utc_window(end - dt.timedelta(days=6), 7)
    b_lo, _ = utc_window(end - dt.timedelta(days=7 * weeks + 6))
    week = entries_all(kind=roles().kind("log"), since=lo, until=hi, order="created", dir="asc", content=1)
    base = entries_all(kind=roles().kind("log"), since=b_lo, until=lo, order="created", dir="asc", content=1)
    base = [r for r in base if (r.get("created_at_utc") or "") < lo]
    sleep = entries_all(kind=roles().kind("sleep"), since=b_lo, until=hi, order="created", dir="asc", content=0)
    past = []
    for years in (1, 2, 3):
        try:
            p_end = end.replace(year=end.year - years)
        except ValueError:      # 29 February
            p_end = end.replace(year=end.year - years, day=28)
        p_lo, p_hi = utc_window(p_end - dt.timedelta(days=6), 7)
        for k in COUNSEL_KINDS:
            past += entries_all(kind=k, since=p_lo, until=p_hi, order="created", dir="asc", content=1)
    # Claude Code keeps a Bash result to ~30k characters and puts the rest
    # in a file this role cannot read: a week of logs is several times that
    ps = pages(counsel_digest(end, week, base, sleep, past, weeks), COUNSEL_PAGE_CHARS)
    if not 1 <= part <= len(ps):
        die(f"--part is 1 to {len(ps)}")
    print(f"[part {part} of {len(ps)}]")
    print("\n".join(ps[part - 1]))
    if part < len(ps):
        print(f"\n[part {part} of {len(ps)}: read on with counsel --part {part + 1}]")
    return 0


def _norm(s):
    return re.sub(r"[^\w]+", " ", (s or "").lower()).strip()


def _edits(a, b):
    """Levenshtein distance, for kinds a typo away from a common one."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def hygiene_findings(rows, all_kinds, today):
    """Candidate problems in `rows` (the last weeks of the journal, with
    content, and every open task). Each finding is (section, line). The
    yeoman judges them; this only finds."""
    out = []
    live = [r for r in rows if not r.get("deleted") and r.get("kind") not in IMPORTED_KINDS]
    # twins: the same kind and text within ten minutes (a double tap, an outbox
    # replay), or the same long body under two ids at any distance
    by_key, twins = defaultdict(list), set()
    for r in live:
        body = _norm(r.get("content"))
        title = _norm(r.get("title"))
        if title in PLACEHOLDER_TITLES and not body:
            continue
        by_key[(r.get("kind"), title, body[:200])].append(r)
    for group in by_key.values():
        group.sort(key=lambda r: r.get("created_at_utc") or "")
        for a_, b_ in zip(group, group[1:]):
            ta, tb = stamp(a_.get("created_at_utc")), stamp(b_.get("created_at_utc"))
            if ta and tb and (tb - ta) <= dt.timedelta(minutes=10):
                twins |= {a_["id"], b_["id"]}
                out.append(("duplicates", f"#{a_['id']} and #{b_['id']} [{a_.get('kind')}] same text "
                                          f"{int((tb - ta).total_seconds())}s apart: {snippet(a_.get('title') or a_.get('content'), 70)}"))
    by_body = defaultdict(list)
    for r in live:
        body = _norm(r.get("content"))
        if len(body) >= 80:
            by_body[body].append(r)
    for group in by_body.values():
        # a pair already reported as twins above is not reported twice
        if len(group) > 1 and not {r["id"] for r in group} <= twins:
            ids = ", ".join(f"#{r['id']} [{r.get('kind')}]" for r in group)
            out.append(("duplicates", f"{ids}: identical body ({snippet(group[0].get('content'), 60)})"))
    # kinds used once or twice that look like a slip for a common one
    common = [k for k, n in all_kinds.items() if n >= 10]
    for k, n in all_kinds.items():
        if n > 2 or k in common:
            continue
        # task_<list> kinds are Reminders lists, made on purpose and small
        if k.startswith(task_kind() + "_"):
            continue
        near = [c for c in common if _norm(k).replace(" ", "") == _norm(c).replace(" ", "")
                or k.rstrip("s") == c or c.rstrip("s") == k or _edits(k, c) <= (1 if len(k) < 8 else 2)]
        if near:
            out.append(("kinds", f"kind '{k}' ({n} rows) looks like '{near[0]}' ({all_kinds[near[0]]} rows)"))
    paired = {roles().kind(x) for x in ("sleep", "child_sleep", "drive")}
    for r in live:
        k = r.get("kind")
        if k in paired and not re.match(r"\s*(start|end)\b",
                                                                     (r.get("content") or "") + " " + (r.get("title") or ""), re.I):
            out.append(("kinds", f"{line(r)}: a {k} row whose body is not start/end - "
                                 f"{snippet(r.get('content'), 80)}"))
        if k == roles().kind("log") and re.fullmatch(r"\s*(start|end)\s*", r.get("content") or "", re.I):
            out.append(("kinds", f"{line(r)}: body is a bare '{(r.get('content') or '').strip()}' - a sleep/drive row under the wrong kind?"))
    # dates: a task that names a when but is not scheduled; schedules that end
    # before they start
    when = re.compile(r"\b(tomorrow|tonight|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                      r"maine|poimaine|diseara|azi|luni|marti|miercuri|joi|vineri|sambata|duminica|"
                      r"\d{1,2}:\d{2}|\d{1,2} ?(am|pm))\b", re.I)
    for r in live:
        k = r.get("kind") or ""
        s, e = r.get("start_date") or "", r.get("end_date") or ""
        is_task = k == task_kind() or k.startswith(task_kind() + "_")
        if is_task and not r.get("done_bool") and not s and when.search((r.get("title") or "") + " " + (r.get("content") or "")[:200]):
            out.append(("dates", f"{line(r)}: names a time ('{when.search((r.get('title') or '') + ' ' + (r.get('content') or '')[:200]).group(0)}') but has no due date"))
        if s and e and e < s:
            out.append(("dates", f"{line(r)}: ends {e} before it starts {s}"))
        # (meetings are notes of a meeting, most imported without a time:
        # only a trip, which is a plan, must have one)
        if k == roles().kind("trip") and not s:
            out.append(("dates", f"{line(r)}: a trip with no start date"))
    # stale: open tasks untouched for a month, or past due by a week
    now = dt.datetime.combine(today, dt.time(), TZ).astimezone(dt.timezone.utc)
    for r in live:
        k = r.get("kind") or ""
        if not (k == task_kind() or k.startswith(task_kind() + "_")) or r.get("done_bool"):
            continue
        m = stamp(r.get("last_modified_at_utc")) or stamp(r.get("created_at_utc"))
        due = stamp(r.get("end_date") or r.get("start_date"))
        if due and now - due > dt.timedelta(days=7):
            out.append(("stale", f"{line(r)}: due {local(r.get('start_date'), '%d %b %Y')}, still open"))
        elif m and now - m > dt.timedelta(days=30):
            out.append(("stale", f"{line(r)}: open, untouched since {local(r.get('last_modified_at_utc'), '%d %b %Y')}"))
    return out


# ---- the yeoman's ledger -----------------------------------------------------
# The yeoman ends each finding with the change as the captain would say it, and
# the page gives four shapes of it Apply and Dismiss (index.html, "the yeoman's
# proposals"), recording what became of each in the report itself, a
# yeoman-ledger fence of JSON lines {change, applied, undone, dismissed}. The
# same shapes here, so a change reads the same on both sides: change one,
# change both (YEO_RE in index.html).
YEO_RE = re.compile(
    r"\b(?:(delete) #?(\d+)|(set kind) of #?(\d+) to ([a-z][a-z0-9_]*)|"
    r"(set due) of #?(\d+) to (\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?Z?)|(title) #?(\d+) to (.+?))"
    r"(?=[\s.;,!]*[\"”`*]|[\s.;!]*$)", re.I)
YEO_FENCE_RE = re.compile(r"\n*```yeoman-ledger\n([\s\S]*?)\n```\n?")
YEO_DAYS = 14


def _yeo_stamp(s):
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?", s)
    return f"{m.group(1)} {m.group(2)}{m.group(3) or ':00'}"


def yeo_proposals(text):
    """The changes a report proposes, as the page names them, once each in
    order; code fences (the ledger's own JSON names changes) are not findings."""
    out, fence = [], False
    for ln in YEO_FENCE_RE.sub("\n", text or "").split("\n"):
        if re.match(r"\s*```", ln):
            fence = not fence
            continue
        if fence:
            continue
        for m in YEO_RE.finditer(ln):
            if m.group(1):
                c = f"delete {int(m.group(2))}"
            elif m.group(3):
                c = f"set kind of {int(m.group(4))} to {m.group(5).lower()}"
            elif m.group(6):
                c = f"set due of {int(m.group(7))} to {_yeo_stamp(m.group(8))}"
            else:
                t = re.sub(r"^[\"“‘']+|[\"”’']+$", "", m.group(11).strip()).strip()
                if not t:
                    continue
                c = f"title {int(m.group(10))} to {t}"
            if c not in out:
                out.append(c)
    return out


def yeo_marks(text):
    """change -> its record in the report's ledger fence."""
    m, by = YEO_FENCE_RE.search(text or ""), {}
    for ln in (m.group(1).split("\n") if m else []):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("change"):
            by[r["change"]] = r
    return by


def yeoman_ledger(reports):
    """Every change the reports proposed, oldest report first: {change: {first,
    last (report ids), nights, state, at}}. The state is the newest mark any
    report's ledger holds for it - applied, undone (applied, then put back),
    dismissed - or pending."""
    led = {}
    for r in sorted(reports, key=lambda x: (x.get("created_at_utc") or "", x["id"])):
        if r.get("deleted"):
            continue
        marks = yeo_marks(r.get("content"))
        for c in yeo_proposals(r.get("content")):
            x = led.setdefault(c, {"first": r["id"], "last": r["id"], "nights": 0, "state": "pending", "at": ""})
            x["last"], x["nights"] = r["id"], x["nights"] + 1
        for c, mk in marks.items():
            x = led.get(c)
            if not x:
                continue
            # as the page reads a record (yeoState): a re-apply drops "undone"
            state = ("dismissed" if mk.get("dismissed") else "applied" if mk.get("applied") and not mk.get("undone")
                     else "undone" if mk.get("undone") else "")
            at = max(str(mk.get(k) or "") for k in ("applied", "undone", "dismissed"))
            if state and at >= x["at"]:
                x["state"], x["at"] = state, at
    return led


def ledger_lines(reports, days=YEO_DAYS):
    led = yeoman_ledger(reports)
    out = [f"\nledger: what became of your proposals in the last {days} days ({len(reports)} reports)"]
    if not led:
        return out + ["  none"]
    labels = (("pending", "pending (proposed before, neither applied nor dismissed)"), ("applied", "applied"),
              ("undone", "undone (applied, then put back by the captain)"), ("dismissed", "dismissed"))
    for state, label in labels:
        items = [(c, x) for c, x in led.items() if x["state"] == state]
        out.append(f"  {label} ({len(items)}):")
        for c, x in items[:60]:
            nights = f"{x['nights']} report{'s' if x['nights'] != 1 else ''}"
            out.append(f"    {c}  - in {nights}, first #{x['first']}, last #{x['last']}"
                       + (f", {state} {x['at']} UTC" if x["at"] else ""))
        if len(items) > 60:
            out.append(f"    ... {len(items) - 60} more")
    return out


# ---- trips ------------------------------------------------------------------
# A trip entry is the page's trip planner's: a title, start_date (the
# departure, UTC), end_date (the arrival, once planned), the stops as
# "1. <stop> — hh:mm" lines and a ```json trip block (points with their
# stays, calc with each leg's metres and seconds). What happened is in other
# rows: drive start/end rows (an end's value_float is the leg's minutes; the
# body is the address), the entries written those days with "Place (lat,
# lon ±n m)" in them, and their attachments. `trip <id>` lays both out so
# the historian compares, and does not count.

TRIP_BLOCK_RE = re.compile(r"```json trip\s*\n(.*?)\n```", re.S)
PLACE_RE = re.compile(r"([^\n()]{0,60}?)\s*\((-?\d{1,3}\.\d+),\s*(-?\d{1,3}\.\d+)\s*(?:±\s*\d+\s*m)?\)")
MONEY_RE = re.compile(r"[€$£]|\b\d+(?:[.,]\d+)?\s*(?:eur|euro|euros|lei|ron|usd)\b|\b(?:paid|pay|bought|buy|cost|costs|"
                      r"price|spent|ticket|tickets|cumparat|cumpărat|platit|plătit|bilet|bilete)\b", re.I)
TRIP_SKIP_KINDS = lcars_roles.Lazy(lambda: (roles().kind("trip"), *NOT_WRITING), key=lambda: _ROLES)
TRIP_ENTRY_TEXT = 400


def trip_block(r):
    m = TRIP_BLOCK_RE.search(r.get("content") or "")
    if not m:
        return {}
    try:
        j = json.loads(m.group(1))
    except ValueError:
        return {}
    return j if isinstance(j, dict) else {}


def trip_zone(r):
    """The zone the trip was planned in: the block's depart is its wall
    clock, start_date the same moment in UTC, so their difference is the
    offset (a trip's +2 while the captain's zone is +3). Else the captain's TZ."""
    s, dep = stamp(r.get("start_date")), trip_block(r).get("depart")
    try:
        wall = dt.datetime.strptime(str(dep)[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return TZ
    if not s:
        return TZ
    off = round((wall - s).total_seconds() / 900) * 900
    if off == TZ.utcoffset(s.replace(tzinfo=None)).total_seconds() or abs(off) > 14 * 3600:
        return TZ
    return dt.timezone(dt.timedelta(seconds=off))


def zone_name(tz):
    if isinstance(tz, ZoneInfo):
        return tz.key
    h = tz.utcoffset(None).total_seconds() / 3600
    return f"UTC{h:+g}, the trip's own"


def trip_plan(r):
    """(stops, legs, metres, seconds): the planned stops as [(name, "hh:mm"
    or "", the rest of its line: ", stay 15m", ", leave 13:45")], the legs as their lines ("drive · 54 km · 43m"),
    and the planned totals from the block's calc (None when it has none)."""
    body = r.get("content") or ""
    j = trip_block(r)
    stops, legs = [], []
    for ln in body.split("```")[0].splitlines():
        m = re.match(r"\s*\d+\.\s+(.+?)(?:\s+—\s+(\d{1,2}:\d\d)(.*))?$", ln)
        if m:
            stops.append([m.group(1).strip(), m.group(2) or "", (m.group(3) or "").strip(" ,")])
            continue
        m = re.match(r"\s*↓\s*(.+)$", ln)
        if m:
            legs.append(m.group(1).strip())
    pts = [p for p in (j.get("points") or []) if isinstance(p, dict)]
    if not stops and pts:
        stops = [[(p.get("name") or "?").strip(), "", f"stay {p['stay']}m" if p.get("stay") else ""] for p in pts]
    calc = [c for c in (j.get("calc") or []) if isinstance(c, dict)]
    metres = sum(c.get("len") or 0 for c in calc) if calc else None
    secs = sum(c.get("dur") or 0 for c in calc) if calc else None
    return stops, legs, metres, secs


def trip_end(r):
    """The trip's end as an aware UTC datetime: end_date, else the departure
    plus the planned legs and stays (its last stop), else the departure."""
    e = stamp(r.get("end_date"))
    if e:
        return e
    s = stamp(r.get("start_date"))
    if not s:
        return None
    j = trip_block(r)
    secs = sum((c.get("dur") or 0) for c in (j.get("calc") or []) if isinstance(c, dict))
    stays = sum((p.get("stay") or 0) for p in (j.get("points") or []) if isinstance(p, dict)
                and isinstance(p.get("stay"), (int, float)))
    return s + dt.timedelta(seconds=secs, minutes=stays)


def trip_days(r, tz=None):
    """The local days (in the trip's zone) the trip spans, first to last."""
    tz = tz or trip_zone(r)
    s, e = stamp(r.get("start_date")), trip_end(r)
    if not s:
        return []
    a, b = s.astimezone(tz).date(), (e or s).astimezone(tz).date()
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)] if b >= a else [a]


def drive_legs(rows):
    """[(from, to, minutes, km)] from a day's drive rows, oldest first: a
    "start" row opens a leg, an "end" closes it with its value_float minutes.
    km only when a body says it (the Shortcut that writes them does not)."""
    legs, open_ = [], None
    first = lambda t: re.sub(r"^\s*(start|end)\b\s*", "", (t or "").strip().split("\n")[0], flags=re.I).strip()
    for r in sorted(rows, key=lambda r: r.get("created_at_utc") or ""):
        body = r.get("content") or ""
        km = re.search(r"(\d+(?:[.,]\d+)?)\s*km\b", body)
        km = float(km.group(1).replace(",", ".")) if km else None
        if re.match(r"\s*start\b", body, re.I):
            open_ = r
        elif re.match(r"\s*end\b", body, re.I):
            mins = r.get("value_float") or 0
            legs.append((first(open_.get("content")) if open_ else "?", first(body), mins, km))
            open_ = None
    return legs


def zone_window(day, tz, days=1):
    """utc_window in another zone."""
    start = dt.datetime.combine(day, dt.time(), tz)
    end = start + dt.timedelta(days=days) - dt.timedelta(seconds=1)
    f = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return f(start), f(end)


def trip_report(trip, rows, media):
    """The lines of `trip <id>`: trip is the trip row, rows every row created
    on its days (any kind), media {entry id: [mime, ...]}. Pure, so a test
    gives it fixed rows. Times are the trip's own zone's (trip_zone)."""
    out = []
    tz = trip_zone(trip)
    at = lambda s, fmt="%H:%M": stamp(s).astimezone(tz).strftime(fmt) if stamp(s) else "-"
    days = trip_days(trip, tz)
    stops, legs, metres, secs = trip_plan(trip)
    end = trip_end(trip)
    out.append(f"Trip #{trip['id']}: {(trip.get('title') or '').strip() or '(untitled)'}")
    out.append(f"  departs {at(trip.get('start_date'), '%a %d %b %Y %H:%M')}, "
               + (f"ends {at(trip.get('end_date'), '%a %d %b %H:%M')}" if trip.get("end_date")
                  else f"no end set; last stop due {end.astimezone(tz):%a %d %b %H:%M}" if end else "no end")
               + f" (times: {zone_name(tz)}); days: {', '.join(f'{d:%a %d %b}' for d in days) or '-'}")
    out.append(f"\nPlanned ({len(stops)} stops):")
    for i, (name, when, rest) in enumerate(stops, 1):
        out.append(f"  {i}. {name}" + (f" at {when}" if when else "") + (f", {rest}" if rest else ""))
        if i - 1 < len(legs) and i < len(stops):
            out.append(f"     ↓ {legs[i - 1]}")
    if metres is not None:
        out.append(f"  planned total: {metres / 1000:.1f} km, {round(secs / 60)} min on the move")
    tot = Counter()
    for d in days:
        lo, hi = zone_window(d, tz)
        day_rows = [r for r in rows if lo <= (r.get("created_at_utc") or "") <= hi and not r.get("deleted")]
        out.append(f"\n{d:%A %d %B %Y}:")
        dl = drive_legs([r for r in day_rows if r.get("kind") == roles().kind("drive")])
        mins = sum(m for _, _, m, _ in dl)
        kms = [k for _, _, _, k in dl if k is not None]
        tot["legs"] += len(dl)
        tot["minutes"] += mins
        tot["km"] += sum(kms)
        tot["km_legs"] += len(kms)
        out.append(f"  drives ({len(dl)} legs, {round(mins)} min" + (f", {sum(kms):.1f} km" if kms else "") + "):")
        for a_, b_, m, k in dl:
            out.append(f"    {snippet(a_, 50)} → {snippet(b_, 50)}: {round(m)} min" + (f", {k:g} km" if k is not None else ""))
        others = [r for r in day_rows if r.get("id") != trip["id"] and r.get("kind") == roles().kind("trip")]
        if others:
            out.append("  other trip plans this day: " + ", ".join(f"#{r['id']} {snippet(r.get('title'), 40)}" for r in others))
        written = [r for r in day_rows if own_kind(r.get("kind")) and r.get("kind") not in TRIP_SKIP_KINDS]
        skipped = Counter(r.get("kind") for r in day_rows if r.get("kind") in NOT_WRITING and r.get("kind") != roles().kind("drive"))
        out.append(f"  entries ({len(written)}):")
        for r in sorted(written, key=lambda r: r.get("created_at_utc") or ""):
            body = r.get("content") or ""
            places = [(p.strip(" -•\t") or "?", la, lo_) for p, la, lo_ in PLACE_RE.findall(body)]
            ms = media.get(r["id"], [])
            photos = sum(1 for m in ms if m.startswith("image/"))
            videos = sum(1 for m in ms if m.startswith("video/"))
            other = len(ms) - photos - videos
            tot["entries"] += 1
            tot["located"] += bool(places)
            tot["photos"] += photos
            tot["videos"] += videos
            tot["files"] += other
            att = ", ".join(f"{n} {w}" for n, w in ((photos, "photos"), (videos, "videos"), (other, "other files")) if n)
            out.append(f"    {at(r.get('created_at_utc'))} {line(r)}" + (f" [{att}]" if att else ""))
            for p, la, lo_ in places[:4]:
                out.append(f"      at {snippet(p, 50)} ({la}, {lo_})")
            text = PLACE_RE.sub("", body)
            if text.strip():
                out.append(f"      {snippet(text, TRIP_ENTRY_TEXT)}")
            for sent in re.split(r"(?<=[.!?\n])\s+", body):
                if MONEY_RE.search(sent):
                    tot["money"] += 1
                    out.append(f"      money: {snippet(sent, 160)}")
        if not written:
            out.append("    none")
        if skipped:
            out.append("  also: " + ", ".join(f"{n} {k}" for k, n in sorted(skipped.items())))
    out.append(f"\nTotals: {tot['legs']} drive legs, {round(tot['minutes'])} min driving, "
               + (f"{tot['km']:.1f} km recorded on {tot['km_legs']} legs" if tot["km_legs"] else "km not recorded in the drive rows")
               + (f" (planned {metres / 1000:.1f} km, {round(secs / 60)} min)" if metres is not None else "")
               + f"; {tot['entries']} entries, {tot['located']} with a location; {tot['photos']} photos, "
               f"{tot['videos']} videos, {tot['files']} other files; {tot['money']} lines about money")
    return out


def ended_trips(trips, since, now):
    """The live trips whose end (trip_end) falls in (since, now], oldest end first."""
    got = [(trip_end(r), r) for r in trips if not r.get("deleted")]
    return [r for e, r in sorted(((e, r) for e, r in got if e and since < e <= now), key=lambda x: x[0])]


def media_by_entry(ids):
    """{entry id: [mime, ...]} for these entries: GET /media in one call,
    else (a list too long for the server's arena) one call per entry."""
    out = defaultdict(list)
    status, text = http("GET", "/media")
    if status == 200:
        for m in json.loads(text):
            if m.get("entry_id") in ids:
                out[m["entry_id"]].append(m.get("mime") or "")
        return out
    for i in ids:
        status, text = http("GET", f"/entries/{i}/media")
        if status == 200:
            out[i] = [m.get("mime") or "" for m in json.loads(text)]
    return out


def cmd_trip(a):
    now = dt.datetime.now(dt.timezone.utc)
    if not a:
        # since the historian's last post, else the last two days
        last = entries(kind="crew_historian", order="created", dir="desc", limit=1, content=0)
        since = (stamp(last[0].get("created_at_utc")) if last else None) or now - dt.timedelta(days=2)
        trips = entries(kind=roles().kind("trip"), order="start", dir="desc", limit=60, content=1)
        got = ended_trips(trips, since, now)
        print(f"Trips ended since {since.astimezone(TZ):%a %d %b %H:%M} (the historian's last post, local time): {len(got)}")
        for r in got:
            print(f"  {line(r)}: {local(r.get('start_date'))} → {trip_end(r).astimezone(TZ):%a %d %b %H:%M}"
                  f"{'' if r.get('end_date') else ' (no end set: its last stop)'} - `trip {r['id']}` for its retro")
        if not got:
            print("  none: no retro today")
        return 0
    if not a[0].isdigit():
        die("trip [<id>]")
    status, text = http("GET", f"/entries/{a[0]}")
    if status != 200:
        die(f"GET /entries/{a[0]}: {status} {text[:200]}", 1)
    trip = json.loads(text)
    if trip.get("kind") != roles().kind("trip"):
        die(f"#{a[0]} is a {trip.get('kind')} entry, not a trip")
    tz = trip_zone(trip)
    days = trip_days(trip, tz)
    rows = []
    if days:
        lo, _ = zone_window(days[0], tz)
        _, hi = zone_window(days[-1], tz)
        rows = entries_all(since=lo, until=hi, order="created", dir="asc", content=1)
    ids = {r["id"] for r in rows if own_kind(r.get("kind")) and r.get("kind") not in TRIP_SKIP_KINDS}
    print("\n".join(trip_report(trip, rows, media_by_entry(ids) if ids else {})))
    return 0


# ---- secrets ------------------------------------------------------------------
# A token or key pasted into an entry (#4824: a Grafana Cloud token, 13 Oct
# 2026). Found here so the yeoman can say "rotate it, then delete or edit";
# the value itself is never printed - not by hygiene, not in the yeoman's
# report, not by a test - only mask()'s first characters and length.

SECRET_PREFIXES = (
    (r"glc_[A-Za-z0-9+/=_-]{20,}", "a Grafana Cloud token"),
    (r"glsa_[A-Za-z0-9_]{20,}", "a Grafana service account token"),
    (r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}", "an API secret key (sk-, OpenAI or Anthropic style)"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "a GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{30,}", "a GitHub fine-grained token"),
    (r"(?:AKIA|ASIA)[0-9A-Z]{16}", "an AWS access key id"),
    (r"xox[abposr]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"AIza[0-9A-Za-z_-]{35}", "a Google API key"),
    (r"ya29\.[0-9A-Za-z_-]{20,}", "a Google OAuth access token"),
    (r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", "a JWT"),
)
SECRET_PREFIX_RE = [(re.compile(r"(?<![A-Za-z0-9_])" + p), what) for p, what in SECRET_PREFIXES]
BEARER_RE = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})")
# "password: x", "token = x", "api key: x" - the label starts its line (after
# a bullet or a word or two), so prose that merely mentions a token is not one
LABELED_RE = re.compile(r"(?im)^[\s>*-]*(?:[\w.]+[ _-]){0,2}?(password|passwd|pwd|pass|token|api[ _-]?key|apikey|"
                        r"secret|client[ _-]?secret|access[ _-]?key|private[ _-]?key|parola|cheie)\s*[:=]\s*(\S+)")
LONG_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9+/=_-])")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+|\]\([^)\s]*\)|\S*media/\d{4}/\S+", re.I)


def mask(value):
    """What may be shown of a secret: its first four characters and its
    length. A short one (a password) shows fewer, so a preview is never
    most of it."""
    n = len(value)
    keep = 4 if n >= 16 else max(1, n // 4)
    return f"{value[:keep]}… ({n} chars)"


def _mixed(run):
    """A run that looks random, not a word, a path or an identifier: hex
    with letters and digits; else base64ish with digits and both cases, a
    stretch of 24 or more between separators (Some_Name-v2_Final is words
    joined, a key is one long stretch) and under 45% of it in words (runs of
    three or more lowercase). Measured on the live journal in October 2026:
    this kept keys, signatures and data: URIs, and dropped file names, paths
    and identifiers."""
    if re.fullmatch(r"[0-9a-fA-F]+", run):
        return bool(re.search(r"[0-9]", run)) and bool(re.search(r"[a-fA-F]", run))
    if len(re.findall(r"[0-9]", run)) < 3 or not re.search(r"[a-z]", run) or not re.search(r"[A-Z]", run):
        return False
    if max(len(seg) for seg in re.split(r"[_=/+.-]", run)) < 24:
        return False
    wordy = sum(len(w) for w in re.findall(r"[A-Z]?[a-z]{3,}|[A-Z]{4,}", run))
    return wordy < 0.45 * len(run)


def find_secrets(text):
    """[(value, what)] of the secret-shaped strings in text, each value once,
    the most specific name first (a JWT is not also reported as a long run)."""
    text = text or ""
    found, seen = [], set()

    def add(v, what):
        v = v.strip().rstrip(".,;:)]}'\"`")
        if len(v) >= 6 and not any(v in s or s in v for s in seen):
            seen.add(v)
            found.append((v, what))

    for rx, what in SECRET_PREFIX_RE:
        for m in rx.finditer(text):
            add(m.group(0), what)
    for m in BEARER_RE.finditer(text):
        add(m.group(1), "a Bearer token")
    for m in LABELED_RE.finditer(text):
        v = m.group(2)
        # "token: none", "password: same as before": a lone lowercase word
        # is a remark, not a value
        if re.fullmatch(r"[a-z]+[.,;:!]?", v) or re.fullmatch(r"<[^>]*>|\.\.\.|…|\*+|x+", v, re.I):
            continue
        add(v, f"a value after '{m.group(1).lower()}:'")
    plain = URL_RE.sub(" ", UUID_RE.sub(" ", text))
    for m in LONG_RUN_RE.finditer(plain):
        run = m.group(0)
        if _mixed(run):
            hexy = re.fullmatch(r"[0-9a-fA-F]+", run)
            add(run, "a long hex run (a key, or a hash?)" if hexy else "a long random-looking run (base64?)")
    return found


def secret_findings(rows):
    """("secrets", line) for each secret-shaped string in the captain's own
    rows - never the crew's, Number One's or the frozen imports. A line names
    the entry, the masked value and what it looks like, and whether the entry
    holds other words (then edit it out; else delete the entry)."""
    out = []
    for r in rows:
        k = r.get("kind") or ""
        if r.get("deleted") or not own_kind(k) or k in IMPORTED_KINDS:
            continue
        title, body = r.get("title") or "", r.get("content") or ""
        hits = find_secrets(title + "\n" + body)
        if not hits:
            continue
        rest = body
        for v, _ in hits:
            rest = rest.replace(v, " ")
        words = len(re.findall(r"[^\W\d_]{2,}", rest))
        where = f"#{r['id']} [{k}] {local(r.get('created_at_utc'), '%d %b %Y')}"
        # one line per entry and kind of find: an imported page of signed
        # URLs is one finding, not twenty
        by_what = defaultdict(list)
        for v, what in hits:
            by_what[what + (" (in the title)" if v in title else "")].append(v)
        for what, vs in by_what.items():
            shown = ", ".join(mask(v) for v in vs[:3]) + (f" and {len(vs) - 3} more" if len(vs) > 3 else "")
            out.append(("secrets", f"{where}: {shown} - {what}; the entry has {words} other words"))
    return out


def redact(text, values):
    """text with every value replaced by its mask, for anything printed."""
    for v in sorted(values, key=len, reverse=True):
        text = text.replace(v, mask(v))
    return text


def cmd_hygiene(a):
    today = now_local().date()
    days = int(a[0]) if a and a[0].isdigit() else 45
    lo, _ = utc_window(today - dt.timedelta(days=days))
    rows = entries_all(modified_since=lo, order="id", dir="asc", content=1)
    seen = {r["id"] for r in rows}
    ks = kinds()
    for k in ks:
        if k == task_kind() or k.startswith(task_kind() + "_"):
            rows += [r for r in entries_all(kind=k, done=0, content=1) if r["id"] not in seen]
    found = secret_findings(rows) + hygiene_findings(rows, ks, today)
    # the other sections quote titles and bodies: a secret in one is masked there too
    secret_values = {v for r in rows if own_kind(r.get("kind")) and r.get("kind") not in IMPORTED_KINDS
                     for v, _ in find_secrets((r.get("title") or "") + "\n" + (r.get("content") or ""))}
    print(f"Hygiene candidates: entries modified in the last {days} days ({len(rows)} rows read) and every open task.")
    print("Placeholder titles ('HTTP Entry'), [[links]] and Context blocks are the linker's, and not looked at.")
    print("Secrets are shown masked (first characters and length); the value is never printed.")
    for sec in ("secrets", "duplicates", "kinds", "dates", "stale"):
        items = [redact(t, secret_values) for s, t in found if s == sec]
        print(f"\n{sec} ({len(items)}):")
        for t in items[:40]:
            print("  " + t)
        if len(items) > 40:
            print(f"  ... {len(items) - 40} more")
        if not items:
            print("  none")
    lo, _ = utc_window(today - dt.timedelta(days=YEO_DAYS))
    reports = [r for r in entries_all(kind="crew_yeoman", content=1) if (r.get("created_at_utc") or "") >= lo]
    for t in ledger_lines(reports):
        print(t)
    return 0


def _mode(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return stat.S_IMODE(st.st_mode)


def _run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"({e})"


def audit_files(home, lcars_home):
    """(path, mode, finding) for the files whose permissions matter."""
    out = []
    checks = [(os.path.join(home, ".env"), "secrets: the server's, No.1's and the crew's passwords"),
              (os.path.join(home, ".claude", ".credentials.json"), "Claude login"),
              (os.path.join(lcars_home, "lcars.db"), "the journal"),
              (os.path.join(lcars_home, "lcars_backups"), "journal backups"),
              (os.path.join(home, ".ssh"), "ssh"),
              (os.path.join(home, ".ssh", "authorized_keys"), "ssh keys allowed in")]
    for p, what in checks:
        m = _mode(p)
        if m is None:
            out.append((p, "-", f"missing ({what})"))
            continue
        loose = m & 0o077 if p.endswith((".env", ".credentials.json", "authorized_keys", ".ssh")) else m & 0o007
        out.append((p, f"{m:o}", f"{what}: " + ("OPEN to group/others" if loose else "ok")))
    return out


def backup_facts(lcars_home, crontab_text):
    """What the backups are and whether any copy leaves the box."""
    out = []
    bdir = os.path.join(lcars_home, "lcars_backups")
    for tier in ("hourly", "daily", "weekly", "monthly"):
        files = sorted(glob.glob(os.path.join(bdir, tier, "*.db.gz")))
        if files:
            age = (dt.datetime.now().timestamp() - os.path.getmtime(files[-1])) / 3600
            out.append(f"{tier}: {len(files)} copies, newest {os.path.basename(files[-1])} ({age:.1f}h old)")
        else:
            out.append(f"{tier}: none")
    off = [ln for ln in crontab_text.splitlines() if re.search(r"\b(rsync|rclone|restic|borg|scp|s3|b2)\b", ln)
           and not ln.lstrip().startswith("#")]
    cfg = [p for p in ("~/.config/rclone/rclone.conf", "~/.config/restic", "~/.config/borg") if os.path.exists(os.path.expanduser(p))]
    out.append("off-box copy: " + ("; ".join(off + cfg) if off or cfg else
                                   "NONE found (no rsync/rclone/restic/borg/scp job, no rclone/restic/borg config): "
                                   "every backup is on the same disk as the journal"))
    return out


def cmd_audit(_a):
    lh = os.environ.get("LCARS_HOME") or os.path.join(HOME, "lcars")
    print(f"Security facts, {now_local():%Y-%m-%d %H:%M} {TZ.key}. Read-only; nothing here needs root.")
    print("\nFile permissions:")
    for p, m, f in audit_files(HOME, lh):
        print(f"  {m:>4}  {p}  {f}")
    cron = _run(["crontab", "-l"])
    print("\nBackups:")
    for f in backup_facts(lh, cron):
        print("  " + f)
    print("\nUser crontab:")
    print("\n".join("  " + ln for ln in cron.splitlines() if ln.strip() and not ln.startswith("#")) or "  empty")
    print("\nUser timers:")
    print("\n".join("  " + ln for ln in _run(["systemctl", "--user", "list-timers", "--no-pager", "--no-legend"]).splitlines()) or "  none")
    print("\nListening sockets (tcp):")
    print("\n".join("  " + ln for ln in _run(["ss", "-tlnH"]).splitlines()) or "  (ss unavailable)")
    print("\nsshd settings (from /etc/ssh/sshd_config and its .d, as written):")
    conf = []
    for p in ["/etc/ssh/sshd_config", *sorted(glob.glob("/etc/ssh/sshd_config.d/*.conf"))]:
        try:
            conf += [f"{os.path.basename(p)}: {ln.strip()}" for ln in open(p)
                     if re.match(r"\s*(PasswordAuthentication|PermitRootLogin|PubkeyAuthentication|Port|KbdInteractiveAuthentication)\b", ln)]
        except OSError as e:
            conf.append(f"{p}: unreadable ({e.strerror})")
    print("\n".join("  " + c for c in conf) or "  nothing set explicitly (Debian defaults)")
    up = _run(["apt", "list", "--upgradable"], timeout=60).splitlines()
    sec = [ln.split("/")[0] for ln in up if "-security" in ln]
    print(f"\nPending updates: {max(len(up) - 1, 0)}, of them security: {len(sec)}" + (f" ({', '.join(sec[:30])})" if sec else ""))
    print("Reboot required: " + ("yes - " + _run(["cat", "/var/run/reboot-required.pkgs"]).replace("\n", ", ")
                                 if os.path.exists("/var/run/reboot-required") else "no"))
    print(f"Kernel: {_run(['uname', '-r'])}")
    print("\nServer auth (lcars.service log, last 7 days):")
    log = _run(["journalctl", "--user", "-u", "lcars", "--since", "-7d", "--no-pager", "-o", "cat"], timeout=60)
    codes = Counter(m.group(1) for m in re.finditer(r"HTTP Reply: (\d{3})", log))
    print(f"  replies by status: {dict(sorted(codes.items()))}")
    print(f"  401s: {codes.get('401', 0)}, 403s: {codes.get('403', 0)}")
    return 0


DOCS = ("CLAUDE.md", "AGENTS.md", "ARCHITECTURE.md", "README.md", "TODO.md", "lcars-cli/README.md")


def cmd_docs(_a):
    repo = os.environ.get("LCARS_HOME") or REPO
    git = ["git", "-C", repo]
    print(f"Docs in {repo} and the code committed since each was last touched (read with Read/Grep/Glob):")
    for d in DOCS:
        if not os.path.exists(os.path.join(repo, d)):
            continue
        last = _run(git + ["log", "-1", "--format=%cs %h", "--", d])
        rev = last.split()[1] if len(last.split()) == 2 else ""
        changed = Counter()
        if rev:
            for f in _run(git + ["log", f"{rev}..HEAD", "--name-only", "--format="]).splitlines():
                if f and f not in DOCS and not f.startswith(("CHANGELOG", "reports/")):
                    changed[f] += 1
        print(f"\n{d} ({sum(1 for _ in open(os.path.join(repo, d)))} lines), last changed {last or '?'}")
        print("  code changed since: " + (", ".join(f"{f} ({n})" for f, n in changed.most_common(25)) or "none"))
    print("\nRecent commits:")
    print("\n".join("  " + ln for ln in _run(git + ["log", "-25", "--format=%cs %h %s"]).splitlines()))
    return 0


# ---- the runner's one write --------------------------------------------------

def post(role, title, content, urgent=False, value_int=None):
    """One crew_<role> entry, or <task>_crew for an urgent finding; its id.
    value_int makes it a reading (the shares role's)."""
    if os.environ.get("CREW_IN_AGENT"):
        die("post is the runner's: an agent's report is its final answer", 3)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", role or ""):
        die(f"bad role {role!r}")
    kind = urgent_kind() if urgent else "crew_" + role
    body = {"kind": kind, "title": title[:200], "content": content}
    if value_int is not None:
        body["value_int"] = int(value_int)
    status, text = http("POST", "/entries", body)
    if not 200 <= status < 300:
        raise RuntimeError(f"POST /entries ({kind}): {status} {text[:300]}")
    try:
        return int(json.loads(text).get("id") or 0)
    except (ValueError, AttributeError):
        return 0


def cmd_post(a):
    title, urgent = "", False
    i = 0
    while i < len(a):
        if a[i] == "--title" and i + 1 < len(a):
            title, i = a[i + 1], i + 2
        elif a[i] == "--urgent":
            urgent, i = True, i + 1
        else:
            die(f"post: unknown argument {a[i]}")
    role = os.environ.get("CREW_ROLE", "")
    if not title:
        die("post --title T [--urgent] (body on stdin)")
    try:
        print(json.dumps({"id": post(role, title, sys.stdin.read(), urgent)}))
    except RuntimeError as e:
        die(str(e), 1)
    return 0


VERBS = {"today": cmd_today, "agenda": cmd_agenda, "onthisday": cmd_onthisday, "month": cmd_month,
         "weekstats": cmd_weekstats, "counsel": cmd_counsel, "hygiene": cmd_hygiene, "trip": cmd_trip, "audit": cmd_audit, "docs": cmd_docs, "post": cmd_post}


def fenced(fn, *args):
    """Run a verb with what it prints fenced as journal data, for a crew note
    turn (CREW_FENCE, crew.py note): the agent is told text in the fence is
    never an order, and a fence the journal's text tries to close is
    defused, so an entry cannot speak as the captain."""
    import io
    real, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        rc = fn(*args)
    except SystemExit as e:
        rc = e.code
    finally:
        sys.stdout = real
    text = buf.getvalue().replace("</journal-data>", "</journal-data >")
    print("<journal-data>\n" + text.rstrip("\n") + "\n</journal-data>")
    return rc


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    verb, rest = a[0], a[1:]
    if os.environ.get("CREW_FENCE") and verb != "post":
        if verb in READ_CLI:
            return fenced(cmd_cli, verb, rest)
        if verb in VERBS:
            return fenced(VERBS[verb], rest)
    if verb in READ_CLI:
        return cmd_cli(verb, rest)
    if verb in VERBS:
        return VERBS[verb](rest)
    die(f"'{verb}' is not a verb here. Read: today, {', '.join(sorted(READ_CLI))}, "
        "agenda, onthisday, month, weekstats, counsel, hygiene, trip, audit, docs.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
