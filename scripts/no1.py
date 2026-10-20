#!/usr/bin/env python3
"""Number One's controls: the captain's first officer runs the engineers.

    no1.py crew list
    no1.py crew etas                            every engineer's estimates against the clock, as JSON
    no1.py crew poll <name>                     status and the tail of their conversation
    no1.py crew say <name> [--fresh] "<order>"  typed into their session as "[No.1] <order>";
                                                --fresh: into a cleared conversation (a new task)
    no1.py crew key <name> <1-9|enter|esc|up|down|tab>
    no1.py crew clear <name>                    a fresh conversation, before a new unrelated task
    no1.py crew start <name> "<Rank Name>" ["<who they are>"]
    no1.py crew diff <name>                     their commits, stat and diff against the live branch
    no1.py crew deploy <name>
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
    no1.py escalate "<question>" ["<context>"]  a reminder in the captain's No1 list (kind task_no1)
    no1.py asks                                 the open ones
    no1.py answered <id>                        close one (the captain ticking one off is
                                                typed to you as "[captain] ...", by reap)
    no1.py journal <lcars-cli arguments>        the journal, read anything, write only no1_*/task_no1
    no1.py ask "<question>" [--session <id>] [--model <m>]
                                                the ship's computer (POST /chat); prints its answer
                                                and the session id to continue it with
    no1.py sync                                 your worktree (eng/number-one) fast-forwarded to the
                                                live branch, so the files you read are what is live;
                                                refused if it has changes or commits of its own.
                                                Every deploy and rollback runs it too

Number One is an engineer session (engineer.py's NO1, started with
brief_no1 and no1_settings), whose permissions allow this script and
nothing that edits. So this file is the whole of what it can do:

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
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# no __pycache__ beside engineer.py: that directory is a live checkout
sys.dont_write_bytecode = True
import engineer as E  # noqa: E402 - the same state and names
import report as R  # noqa: E402 - hosted reports, in the media store
import crew_tool as T  # noqa: E402 - the journal's HTTP, with Number One's login

LOG_KIND = "no1_log"
ASK_KIND = "task_no1"
CREW_VERBS = {"list", "poll", "say", "key", "clear", "start", "diff", "deploy", "deploy-status", "rollback",
              "stop", "dismiss", "recall", "queue", "etas"}
QUEUE_OPS = {"move", "remove", "restore"}


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
            die('crew say <name> [--fresh] "<order>"')
        return engineer("say", name, *(["--fresh"] if fresh else []), inp="[No.1] " + text)
    if verb == "key":
        return engineer("key", name, rest[1] if len(rest) > 1 else "")
    if verb == "clear":
        # the old conversation is kept under its task's name
        code, j = engineer("list")
        task = next((r.get("task") for r in j.get("engineers", []) if r.get("name") == name), "") if code == 0 else ""
        return engineer("clear", name, inp=task or "before a new task")
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
    server makes at start, first. Before it, <live>/lcars-cli is a directory with
    the binary inside it (lcars_chat.h's LCARS_CLI_DIR, crew_tool.py), and
    os.access(dir, X_OK) is true of a directory, so the old lookup handed
    exec a directory: PermissionError. Only a regular executable file counts."""
    for p in (os.environ.get("LCARS_CLI") or "", os.path.join(E.LIVE, "bin", "lcars-cli"),
              os.path.join(E.LIVE, "lcars-cli", "lcars-cli"),
              os.path.join(E.LIVE, "lcars-cli"), shutil.which("lcars-cli") or ""):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def report(a):
    """Publishes the file, then logs its link where the captain reads Number
    One's log. The file is copied first: a log entry pointing at nothing would
    be worse than a report with no entry, which `report.py list` still finds."""
    updating = bool(a) and a[0] == "--update"
    if updating:
        a = a[1:]
    if len(a) < 2:
        die('report --update <rel-path> FILE ["<note>"]' if updating else 'report FILE "<title>" ["<note>"]')
    try:
        r = R.update(a[0], a[1]) if updating else R.publish(a[0], a[1])
    except R.Refused as e:
        die(str(e), 1)
    note = " ".join(a[2:]).strip()
    if updating:
        # one short line: the link was logged when it was published
        title = "Report updated: " + r["title"]
        content = f"[{r['title']}]({r['url']})" + (f" - {note}" if note else "")
    else:
        title = "Report: " + r["title"]
        content = f"[{r['title']}]({r['url']})" + (f"\n\n{note}" if note else "")
    code, j = answer(*http("POST", "/entries", {"kind": LOG_KIND, "title": title[:200], "content": content}))
    out = dict(r, entry_id=j.get("id") if code == 0 else None)
    if code != 0:
        out["error"] = "published, but the log entry failed: " + json.dumps(j)[:300]
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
