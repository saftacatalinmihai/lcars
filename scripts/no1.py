#!/usr/bin/env python3
"""Number One's controls: the captain's first officer runs the engineers.

    no1.py crew list
    no1.py crew etas                            every engineer's estimates against the clock, as JSON
    no1.py crew poll <name>                     status and the tail of their conversation
    no1.py crew say <name> [--fresh] [--room <id>] "<order>"
                                                typed into their session as "[No.1] <order>";
                                                --fresh: into a cleared conversation (a new task);
                                                --room: filed in that room (open, or main) and
                                                their report back there, as if your turn had
                                                started in it - a project's room, wherever the
                                                captain talks to you about it (without it: your
                                                turn's room)
    no1.py crew key <name> <1-9|enter|esc|up|down|tab>
    no1.py crew clear <name>                    a fresh conversation, before a new unrelated task
    no1.py crew refresh <name>                  their handover, a clear, the handover typed back to them
    no1.py crew start <name> "<Rank Name>" ["<who they are>"]
    no1.py crew diff <name>                     their commits, stat and diff against the live branch
    no1.py crew deploy <name> [--room <id>]     its [deploy finished]/[deploy failed] to that room
    no1.py crew deploy-status
    no1.py crew rollback                        only on the captain's word
    no1.py crew stop|dismiss|recall <name>
    no1.py crew queue move <name> up|down|first  the seat's line reordered (never the one seated)
    no1.py crew queue remove <name>             out of the line; their undelivered orders cancelled
    no1.py crew queue restore [<name>]          undo the latest removal: their place, their orders live
    no1.py log "<title>" ["<text>"]             an entry of kind no1_log (text from stdin if absent)
    no1.py logs [n]                             the last n of them (10)
    no1.py report FILE "<title>" ["<note>"]     publish FILE as a hosted report (report.py:
                                                the NAS's media store, never the repo) and log
                                                its link as a no1_log entry; prints the link
    no1.py report --update <rel-path> FILE ["<note>"]
                                                write FILE over a published report (rel-path as
                                                report.py list gives it): the same link, and one
                                                no1_log line "Report updated: <title>"
    no1.py report - "<title>" ["<note>"] --as NAME.EXT
    no1.py report --update <rel-path> - --as NAME.EXT ["<note>"]
                                                the same, the report read from stdin (a heredoc;
                                                10 MB at most, not empty) into a private temp file
                                                NAME.EXT, removed after: html, md, csv, txt, json,
                                                svg, xml and the other text types (STDIN_EXTS)
    no1.py escalate "<question>" ["<context>"]  a reminder in the captain's No1 list (kind task_no1)
                                                several in one: context, then "Q1: …" lines, each with
                                                "Options: A) … B) …" and "Recommendation: A" (none: yes/no);
                                                the console answers each (docs/design/questions.md)
    no1.py asks                                 the open ones
    no1.py answered <id>                        close one (the captain ticking one off is
                                                typed to you as "[captain] ...", by reap)
    no1.py journal <lcars-cli arguments>        the journal, read anything, write only no1_*/task_no1
    no1.py ask "<question>" [--session <id>] [--model <m>]
                                                the ship's computer (POST /chat); prints its answer
                                                and the session id to continue it with
    no1.py room list [--closed]                 the rooms (docs/design/rooms.md): id, name, count, last message
    no1.py room new <id> ["<name>"]             a project room (a closed one of that id is reopened;
                                                not a crew member's name: theirs is their own room)
    no1.py room rename <id> "<name>"
    no1.py room close <id>                      not main, not a crew member's own room
    no1.py room log <id> [n]                    a room's latest n (20) messages, each clipped
    no1.py room show <msg id>                   one message whole
    no1.py thread ...                           the old name of room list|new|rename|close, for
                                                this release: does the same, and says the room verb
    no1.py steward <op> ID ...                  a data fix on the captain's word (scripts/steward.py,
                                                its --help): get ID --json first, one change, get
                                                again; recorded as a crew_fix entry in your name
    no1.py steward new kind=K [title=T] [start=..] [end=..] [TEXT... | --file F | -]
                                                a new entry of the captain's, its id printed, recorded the same
    no1.py api METHOD PATH [--file F | -]       any route of the server as the captain's own login
                                                (GET /theme, PUT /kinds/roles, POST /say, ...): the
                                                answer printed with its status; the body from F or
                                                stdin, JSON if it parses, else text/plain. GET and
                                                HEAD free; every other method logged as a no1_log
                                                line (method, path, status). Refused: /vault (the
                                                Secret entries' keys) and /engineer/ (crew verbs)
    no1.py rm [-r] PATH...                      removed for good, only under /tmp and your research
                                                folder (each path resolved first; one outside it and
                                                nothing is removed). Anything else: mv it to
                                                ~/.local/share/no1-trash
    no1.py sync                                 your worktree (eng/number-one) fast-forwarded to the
                                                live branch, so the files you read are what is live;
                                                refused if it has changes or commits of its own.
                                                Every deploy and rollback runs it too

Number One is an engineer session (engineer.py's NO1, started with
brief_no1 and no1_settings), whose permissions allow this script and
the ordinary shell tools, and writes under the home folder, with the
danger zones denied (no1_settings in engineer.py: the lists, and why).
This file is still the whole of what it does to the crew and the journal:

- The crew verbs are engineer.py's. One rule is held here, not left to the
  brief: no more than NO1_MAX_CREW are on duty when one is started (they
  take turns in one seat, scripts/seat.py).
- `sync` is engineer.py's sync_no1, run here in-process: the only git
  that changes anything Number One may cause, and only a fast-forward of
  its own worktree.
- The journal is reached over HTTP with Number One's own login
  (LCARS_NO1_USER/LCARS_NO1_PASS in ~/.env, read as crew_tool.py reads the
  crew's), which the server lets write only kinds no1_* and task_no1
  (lcars_logins.h). The
  captain's own credentials are never handed to lcars-cli from here.
- `api` is the one door with the captain's own login (journal_api.py, the
  login report.py writes with), for the routes lcars-cli has no verb for.
  Each write is recorded as a no1_log line, written with Number One's own
  login, so the captain reads in one place what was done with that login.
  Deletes on the server are soft (HandleDeleteEntry, HandleMediaDelete):
  nothing this verb can send removes a row for good.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# no __pycache__ beside engineer.py: that directory is a live checkout
sys.dont_write_bytecode = True
import engineer as E  # noqa: E402 - the same state and names
import report as R  # noqa: E402 - hosted reports, in the media store
import journal_api as J  # noqa: E402 - the captain's own login, for `api`
import crew_tool as T  # noqa: E402 - the journal's HTTP, with Number One's login

LOG_KIND = "no1_log"
ASK_KIND = "task_no1"
CREW_VERBS = {"list", "poll", "say", "key", "clear", "refresh", "start", "diff", "deploy", "deploy-status", "rollback",
              "stop", "dismiss", "recall", "queue", "etas"}
QUEUE_OPS = {"move", "remove", "restore"}
THREAD_OPS = {"list", "new", "rename", "close"}
ROOM_OPS = THREAD_OPS | {"log", "show"}


def die(msg, code=2):
    print(json.dumps({"error": msg}))
    sys.exit(code)


def engineer(verb, *args, inp=""):
    """engineer.py <verb>; (exit status, its JSON)."""
    p = E.run([sys.executable, os.path.join(HERE, "engineer.py"), verb, *args], inp=inp, timeout=200)
    try:
        return p.returncode, json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 1, {"error": (p.stderr or p.stdout).strip()[-400:] or "no answer"}


def crew(a):
    if not a or a[0] not in CREW_VERBS:
        die("crew " + "|".join(sorted(CREW_VERBS)))
    verb, rest = a[0], a[1:]
    if "--room" in rest:
        # the room the order or the deploy is for, in place of the turn's
        # (engineer.py room_given): a project's report goes to its room
        i = rest.index("--room")
        rid = rest[i + 1] if i + 1 < len(rest) else ""
        if verb not in ("say", "deploy"):
            die("--room is for crew say and crew deploy")
        if not rid or rid.startswith("--"):
            die("--room <id>: a room's id (no1.py room list)")
        err = E.room_check(rid)
        if err:
            die(err, 4)
        rest = rest[:i] + rest[i + 2:]
        os.environ["LCARS_ROOM_AT"] = rid
    if verb in ("deploy", "rollback"):
        # its outcome reports to the turn's room (by_room)
        os.environ["LCARS_ROOM_BY"] = "no1"
    if verb in ("list", "deploy-status", "rollback", "etas"):
        return engineer(verb)
    if verb == "queue":
        # the line as it is when the script reads it: nothing to compare with
        # (engineer.py's <expect> is for a view painted earlier)
        op = rest[0] if rest else ""
        args = rest[1:]
        if op not in QUEUE_OPS or (op == "move" and len(args) != 2) or (op == "remove" and len(args) != 1) \
                or (op == "restore" and len(args) > 1):
            die("crew queue move <name> up|down|first | remove <name> | restore [<name>]")
        return engineer("queue-" + op, *args)
    if not rest or not E.NAME_RE.match(rest[0]) or rest[0] in E.NOT_NAMES:
        die("an engineer name is [a-z][a-z0-9-]{0,23}")
    name = rest[0]
    if name == E.NO1:
        die("that is you")
    if verb == "say":
        fresh = "--fresh" in rest[1:]
        text = " ".join(w for w in rest[1:] if w != "--fresh").strip() or sys.stdin.read().strip()
        if not text:
            die('crew say <name> [--fresh] [--room <id>] "<order>"')
        return engineer("say", name, *(["--fresh"] if fresh else []), inp="[No.1] " + text)
    if verb == "key":
        return engineer("key", name, rest[1] if len(rest) > 1 else "")
    if verb == "clear":
        # the old conversation is kept under its task's name
        code, j = engineer("list")
        task = next((r.get("task") for r in j.get("engineers", []) if r.get("name") == name), "") if code == 0 else ""
        return engineer("clear", name, inp=task or "before a new task")
    if verb == "refresh":
        # their handover as the turn's last message, the clear, the handover
        # typed back into the fresh conversation (engineer.py's refresh)
        return engineer("refresh", name)
    if verb == "poll":
        code, j = engineer("poll", name, "-1")
        # the tail is enough to judge by; the whole page is long
        if isinstance(j, dict) and isinstance(j.get("events"), list):
            j["events"] = j["events"][-25:]
        return code, j
    if verb == "start":
        if len(rest) < 2:
            die('crew start <name> "<Rank Name>" ["<who they are>"]')
        code, j = engineer("list")
        if code != 0:
            return code, j
        rows = j.get("engineers", [])
        known = any(r.get("name") == name for r in rows)
        on = [r["name"] for r in rows if r.get("name") != E.NO1 and not r.get("dismissed")
              and r.get("status") != "off"]
        if not known and len(on) >= E.NO1_MAX_CREW:
            die(f"{len(on)} engineers are on duty ({', '.join(on)}); at most {E.NO1_MAX_CREW}. "
                "Stop or dismiss one first, or give the work to one of them.", 3)
        persona = {"title": rest[1], "who": rest[2] if len(rest) > 2 else rest[1] + ", an engineer of the U.S.S. Enterprise"}
        return engineer("start", name, inp=json.dumps(persona))
    return engineer(verb, name)


def room(a):
    """engineer.py room number-one <op> ...: the rules are held there
    (rooms.md 7). Nothing is typed, nothing switched."""
    if not a or a[0] not in ROOM_OPS:
        die('room list [--closed] | new <id> ["<name>"] | rename <id> "<name>" | close <id> | log <id> [n] '
            '| show <msg id>')
    op, rest = a[0], a[1:]
    if op == "list" and rest not in ([], ["--closed"]):
        die("room list [--closed]")
    elif op == "new" and not 1 <= len(rest) <= 2:
        die('room new <id> ["<name>"] (to speak in it, a "room:: <id>" line opening a paragraph of your reply)')
    elif op in ("close", "show") and len(rest) != 1:
        die(f"room {op} <{'id' if op == 'close' else 'msg id'}>")
    elif op == "rename" and len(rest) < 2:
        die('room rename <id> "<name>"')
    elif op == "log" and not 1 <= len(rest) <= 2:
        die("room log <id> [n]")
    return engineer("room", E.NO1, op, *rest)


def thread(a):
    """The old name of `room`'s list, new, rename and close, for one release
    (rooms.md 7): engineer.py thread number-one <op> ... as before, its
    answer saying the room verb to use."""
    if not a or a[0] not in THREAD_OPS:
        die('thread list | new <id> ["<name>"] | rename <id> "<name>" | close <id>')
    op, rest = a[0], a[1:]
    if op == "new" and not 1 <= len(rest) <= 2:
        die('thread new <id> ["<name>"] (a label: to speak in it, a "[thread <id>]" line in your reply)')
    elif op == "close" and len(rest) != 1:
        die("thread close <id>")
    elif op == "rename" and len(rest) < 2:
        die('thread rename <id> "<name>"')
    code, j = engineer("thread", E.NO1, op, *rest)
    if isinstance(j, dict):
        j["use"] = f"no1.py room {op} ...: thread is the old name, going in the next release"
    return code, j


# ---- any route, as the captain (`api`) ---------------------------------------

API_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
API_READS = {"GET", "HEAD"}
# Not through this door, whatever the method: the vault holds the wraps of
# the Secret entries' key (docs/design/confidential-entries.md), and a write
# there could lock the captain out of them for good; the engineer routes
# are the crew's, through `crew` (deploys reviewed, logged by engineer.py).
API_REFUSED = ("/vault", "/engineer/")
API_BODY_MAX = 512 * 1024  # lcars_http.h's cap on a request body


def api_refusal(method, path):
    """Why METHOD PATH is not sent, or None."""
    if method not in API_METHODS:
        return f"api METHOD PATH: METHOD one of {', '.join(sorted(API_METHODS))}"
    # a path on this server, never a URL: the login must not go elsewhere
    if not path.startswith("/") or path.startswith("//") or "://" in path or any(c in path for c in " \r\n"):
        return f"api: PATH starts with / and is on this server ({path!r})"
    bare = path.split("?", 1)[0].rstrip("/")
    for r in API_REFUSED:
        if bare == r.rstrip("/") or bare.startswith(r.rstrip("/") + "/"):
            return f"api: {r} is not reached from here" + (" (no1.py crew ...)" if r == "/engineer/" else
                                                          " (the Secret entries' keys: the captain's, in the console)")
    return None


def api_send(method, path, data, ctype, timeout=120):
    """(status, text) of METHOD PATH as the captain's login; status 0 when
    the server did not answer."""
    url, user, pw = J.journal_login()
    headers = {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()} if user else {}
    if data is not None:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, json.dumps({"error": f"{url}: {e}"})


def api(a):
    """no1.py api METHOD PATH [--file F | -]: the answer, and for a write
    its no1_log line (Number One's login) - written after the call, since
    the status is what it records; a failed log is said in the answer."""
    body_from = None
    if "--file" in a:
        i = a.index("--file")
        if i + 1 >= len(a):
            die("api METHOD PATH --file F|-")
        body_from, a = a[i + 1], a[:i] + a[i + 2:]
    elif len(a) == 3 and a[2] == "-":
        body_from, a = "-", a[:2]
    if len(a) != 2:
        die("api METHOD PATH [--file F | -]")
    method, path = a[0].upper(), a[1]
    why = api_refusal(method, path)
    if why:
        die(why, 4)
    data = ctype = None
    if body_from is not None:
        if method in API_READS:
            die(f"api: {method} takes no body")
        try:
            if body_from == "-":
                data = sys.stdin.buffer.read(API_BODY_MAX + 1)
            else:
                with open(body_from, "rb") as f:
                    data = f.read(API_BODY_MAX + 1)
        except OSError as e:
            die(f"api --file: {e}")
        if len(data) > API_BODY_MAX:
            die(f"api: the body is over {API_BODY_MAX} bytes (the server's cap)")
        try:
            json.loads(data)
            ctype = "application/json"
        except ValueError:
            ctype = "text/plain; charset=utf-8"
    status, text = api_send(method, path, data, ctype)
    code, j = answer(status, text)
    out = {"status": status, "answer": j}
    if method not in API_READS:
        line = f"api {method} {path} -> {status or 'no answer'}"
        ls, lt = http("POST", "/entries", {"kind": LOG_KIND, "title": line[:200],
                                           "content": f"{line}\n\nAs the captain's login, by Number One"
                                                      + (f"; a {len(data)}-byte {ctype} body" if data is not None else "")})
        if 200 <= ls < 300:
            try:
                out["logged"] = json.loads(lt).get("id")
            except (ValueError, AttributeError):
                out["logged"] = True
        else:
            out["log_error"] = f"the call was made, but its no1_log line failed: {ls} {lt[:200]}"
            code = 1
    return code, out


# ---- rm, where it cannot hurt (`rm`) ------------------------------------------

def rm_roots():
    """Where `no1.py rm` removes: /tmp, and Number One's research folder."""
    return ["/tmp", os.path.realpath(E.research_dir(E.NO1))]


def rm_refusal(path, recursive):
    """Why path is not removed, or None. The path is resolved as rm would
    reach it - ~ expanded, relative to here, every directory above it
    through its symlinks, the last part not followed (rm removes a link,
    not what it points at) - and must be strictly inside a root."""
    full = os.path.abspath(os.path.expanduser(path))
    real = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
    if not os.path.lexists(real):
        return f"{path}: no such file"
    if not any(real.startswith(r.rstrip("/") + "/") for r in rm_roots()):
        return (f"{path}: rm only under {' and '.join(rm_roots())} ({real}); "
                f"anything else is moved, never removed: mv it to {E.NO1_TRASH}")
    if os.path.isdir(real) and not os.path.islink(real) and not recursive:
        return f"{path}: a directory (rm -r)"
    return None


def rm(a):
    recursive = bool(a) and a[0] in ("-r", "-rf", "-R")
    paths = a[1:] if recursive else a
    if not paths or any(p.startswith("-") for p in paths):
        die("rm [-r] PATH...")
    why = [w for w in (rm_refusal(p, recursive) for p in paths) if w]
    if why:
        die("; ".join(why), 4)  # all or nothing: none removed
    gone = []
    for p in paths:
        full = os.path.abspath(os.path.expanduser(p))
        real = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
        if os.path.isdir(real) and not os.path.islink(real):
            shutil.rmtree(real)
        else:
            os.unlink(real)
        gone.append(real)
    return 0, {"removed": gone}


# ---- the journal, as Number One ---------------------------------------------

def http(method, path, body=None, timeout=60):
    return T.http(method, path, body, timeout, login=T.NO1_LOGIN)


def answer(status, text):
    try:
        j = json.loads(text)
    except ValueError:
        j = {"text": text}
    return (0 if 200 <= status < 300 else 1), j


def cli_path():
    """The lcars-cli binary: <live>/bin/lcars-cli, the one binary's link the
    server makes at start, first; then a checkout's own `make lcars-cli`.
    <live>/lcars-cli was once a directory with a copied build inside it
    (retired in 0.279.2, never looked in now), and os.access(dir, X_OK) is
    true of a directory, so the old lookup handed exec a directory:
    PermissionError. Only a regular executable file counts."""
    for p in (os.environ.get("LCARS_CLI") or "", os.path.join(E.LIVE, "bin", "lcars-cli"),
              os.path.join(E.LIVE, "lcars-cli"), shutil.which("lcars-cli") or ""):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


# A report piped in (`report - ... --as NAME.EXT`): Number One's permissions
# let it run this script and write no file, so stdin is how it hands over a
# report it made. Text it can type into a heredoc, so the types the server
# shows as a page to read (ReportResolveType in lcars_media.h: the text
# ones, HTML, and SVG, JSON and XML by mime.types); anything else would be a
# download of something typed, which is a mistake.
STDIN_EXTS = {"html", "htm", "md", "markdown", "csv", "tsv", "txt", "text", "log", "yaml", "yml",
              "toml", "ini", "diff", "patch", "json", "xml", "svg"}
STDIN_MAX = 10 * 1024 * 1024


def stdin_report(name, stream=None):
    """Reads the report from stdin into a private temp directory as name;
    answers (its path, the directory to remove). Refused (die): a name with a
    slash, a dot-dot or a leading dot, an extension not in STDIN_EXTS, an
    empty input or one over STDIN_MAX. The name is what report.py keeps as
    the sidecar's source and the stored file's extension."""
    ext = os.path.splitext(name)[1][1:].lower()
    if not name or "/" in name or "\\" in name or ".." in name or name.startswith(".") \
            or not R.NAME_RE.match(name):
        die(f"--as {name or '(empty)'}: a plain file name, NAME.EXT, with no slash or ..")
    if ext not in STDIN_EXTS:
        die(f"--as {name}: .{ext or '(none)'} is not a report type here ({', '.join(sorted(STDIN_EXTS))})")
    stream = stream or sys.stdin.buffer
    data = stream.read(STDIN_MAX + 1)
    if len(data) > STDIN_MAX:
        die(f"stdin is over {STDIN_MAX} bytes; a report piped in stops there")
    if not data.strip():
        die("stdin is empty: pipe the report in (a heredoc)")
    d = tempfile.mkdtemp(prefix="no1-report-")  # 0700: Number One's alone
    path = os.path.join(d, name)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(data)
    return path, d


def report(a):
    """Publishes the file, then logs its link where the captain reads Number
    One's log. The file is copied first: a log entry pointing at nothing would
    be worse than a report with no entry, which `report.py list` still finds.
    FILE "-" with --as NAME.EXT reads it from stdin (stdin_report); the temp
    file is gone however this ends."""
    updating = bool(a) and a[0] == "--update"
    if updating:
        a = a[1:]
    name = None
    if "--as" in a:
        i = a.index("--as")
        if i + 1 >= len(a):
            die("--as NAME.EXT")
        name, a = a[i + 1], a[:i] + a[i + 2:]
    src = a[1] if updating and len(a) > 1 else (a[0] if a else "")
    if len(a) < 2 or (src == "-") != (name is not None):
        die('report --update <rel-path> FILE|- [--as NAME.EXT] ["<note>"]' if updating
            else 'report FILE|- "<title>" ["<note>"] [--as NAME.EXT]  (- with --as: the report from stdin)')
    tmp = None
    try:
        if name is not None:
            if updating:
                R.stored(a[0])  # a wrong path refused before stdin is read
            src, tmp = stdin_report(name)
        r = R.update(a[0], src) if updating else R.publish(src, a[1])
    except R.Refused as e:
        die(str(e), 1)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    note = " ".join(a[2:]).strip()
    if updating:
        # one short line: the link was logged when it was published
        title = "Report updated: " + r["title"]
        content = f"[{r['title']}]({r['url']})" + (f" - {note}" if note else "")
    else:
        title = "Report: " + r["title"]
        content = f"[{r['title']}]({r['url']})" + (f"\n\n{note}" if note else "")
    code, j = answer(*http("POST", "/entries", {"kind": LOG_KIND, "title": title[:200], "content": content}))
    # r's "id" is the report's own entry (report.py writes it, as the
    # captain's login); entry_id is this log line's
    out = dict(r, entry_id=j.get("id") if code == 0 else None)
    if code != 0:
        out["error"] = "; ".join(filter(None, [r.get("error"), "published, but the log entry failed: "
                                               + json.dumps(j)[:300]]))
    elif r.get("error"):
        code = 1
    return code, out


def journal(a):
    url, user, pw = T.creds(T.NO1_LOGIN)
    cli = cli_path()
    if not cli:
        die("lcars-cli is not built (make lcars-cli in the live checkout)", 1)
    env = dict(os.environ, LCARS_URL=url, LCARS_AUTH_USER=user, LCARS_AUTH_PASS=pw)
    return subprocess.run([cli, *a], env=env).returncode, None


def chat(a):
    session, model, words = "", "", []
    i = 0
    while i < len(a):
        if a[i] == "--session" and i + 1 < len(a):
            session, i = a[i + 1], i + 2
        elif a[i] == "--model" and i + 1 < len(a):
            model, i = a[i + 1], i + 2
        else:
            words.append(a[i])
            i += 1
    msg = " ".join(words).strip() or sys.stdin.read().strip()
    if not msg:
        die('ask "<question>"')
    body = {"message": msg}
    if session:
        body["session_id"] = session
    if model:
        body["model"] = model
    # the answer streams as SSE; only its text and session id are wanted
    status, raw = http("POST", "/chat", body, timeout=660)
    if status != 200:
        return answer(status, raw)
    text, sid, err = [], session, ""
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except ValueError:
            continue
        if ev.get("session_id"):
            sid = ev["session_id"]
        if ev.get("type") == "result":
            text = [ev.get("result") or ""]
            if ev.get("is_error"):
                err = ev.get("result") or "error"
        elif ev.get("type") == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if b.get("type") == "text":
                    text.append(b.get("text", ""))
    out = {"text": "\n".join(t for t in text if t).strip(), "session_id": sid}
    if err:
        out["error"] = err
    return (1 if err else 0), out


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd == "crew":
        code, j = crew(rest)
    elif cmd == "log":
        if not rest:
            die('log "<title>" ["<text>"]')
        text = " ".join(rest[1:]).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
        code, j = answer(*http("POST", "/entries", {"kind": LOG_KIND, "title": rest[0][:200], "content": text}))
        if code == 0 and rest[0].strip().lower().startswith("handover"):
            E.refresh_noted()  # a [refresh] waiting on this note clears when the turn ends
    elif cmd == "logs":
        n = rest[0] if rest and rest[0].isdigit() else "10"
        code, j = answer(*http("GET", f"/entries?kind={LOG_KIND}&limit={n}"))
    elif cmd == "escalate":
        if not rest:
            die('escalate "<question>" ["<context>"]')
        code, j = answer(*http("POST", "/entries", {"kind": ASK_KIND, "title": rest[0][:200],
                                                     "content": " ".join(rest[1:]).strip()}))
        if code == 0 and isinstance(j, dict) and j.get("id"):
            E.thread_ask(j["id"])  # its answer goes to the thread asking
    elif cmd == "asks":
        code, j = answer(*http("GET", f"/entries?kind={ASK_KIND}&done=0&limit=50"))
    elif cmd == "answered":
        if not rest or not rest[0].isdigit():
            die("answered <id>")
        code, j = answer(*http("PUT", "/entries/" + rest[0], {"done_bool": 1}))
    elif cmd == "report":
        code, j = report(rest)
    elif cmd == "journal":
        code, j = journal(rest)
    elif cmd == "ask":
        code, j = chat(rest)
    elif cmd == "room":
        code, j = room(rest)
    elif cmd == "thread":
        code, j = thread(rest)
    elif cmd == "steward":
        # its own process reads the logins; its answer is printed by it
        env = dict(os.environ, LCARS_STEWARD_WHO=E.NO1)
        code, j = subprocess.run([sys.executable, os.path.join(HERE, "steward.py"), *rest], env=env).returncode, None
    elif cmd == "rm":
        code, j = rm(rest)
    elif cmd == "api":
        code, j = api(rest)
    elif cmd == "sync":
        try:
            code, j = 0, E.sync_no1()
        except RuntimeError as e:
            code, j = 1, {"error": str(e)}
    else:
        die("unknown command " + cmd + " (no arguments for the usage)")
    if j is not None:
        print(json.dumps(j, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
