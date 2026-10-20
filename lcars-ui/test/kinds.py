#!/usr/bin/env python3
"""Kinds by role (lcars_kinds.h, docs/design/kinds.md), end to end against a
scratch server.

  1. a new journal: no row at all (no seed), and GET /kinds/roles every
     role of the table in its order at its default, none set, no entry;
  2. PUT /kinds/roles: a role set with a name, the `settings` entry titled
     `kinds` made, the rows counted, a list role, null back to the default,
     the other roles kept;
  3. the refusals, each a 400 that writes nothing: a kind that is not a
     slug, the app's own kinds, a list in a role that is not one, a role
     the table has not, a body or value of the wrong shape, a bad name -
     and one bad role in a body of good ones;
  4. the entry edited by hand: a role this build does not know kept by the
     next PUT; a bad value falling back with `error`; content that is not
     JSON every role's default, and a PUT refused (409) rather than
     overwriting it; the lowest live id winning;
  5. who may: a limited login reads and may not write; no login 401;
     POST 405; GET / lists the route;
  6. the server following the roles (a second server, with the logins and
     a stand-in claude): CalDAV's task kind, the logins' reminders under
     it (<task>_<owner>) and a PUT that would put a role among them
     refused, the steward kept off the `imported` role's kinds, and the
     computer's prompts naming the log and task kinds; then a third with
     $LCARS_TASK_KIND set, which still wins for CalDAV;
  7. `lcars-cli roles`: the table, --json, set (with --name, and keeping
     the name without it), reset, the server's refusal and a usage error,
     a limited login's 403, and a server older than the route.

Each server is a scratch build (`make -n lcars-release`, compiled to a temp
path - never `make` itself, which on the VPS would overwrite the live
binary) on an empty database in a temp directory.

    python3 test/kinds.py               # builds the server and lcars-cli (~40s)
    LCARS_TEST_BIN=/path/to/lcars LCARS_TEST_CLI=/path/to/lcars-cli python3 test/kinds.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import killclean  # its scratch and servers go when the run is killed

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
MAIN = ("t", "t")
CREW = ("crew-test", "c" * 20)
STEWARD = ("steward-test", "s" * 20)

# a stand-in claude for the chat: keeps its argv, answers one line
CLAUDE = """#!/usr/bin/env python3
import json, os, sys
data = sys.stdin.read()
with open(os.environ["STUB_OUT"], "w") as f:
    json.dump({"argv": sys.argv[1:]}, f)
if "json" in sys.argv and "stream-json" not in sys.argv:
    print(json.dumps({"type": "result", "result": "seen", "session_id": "0a1b2c3d-0000"}))
else:
    print(json.dumps({"type": "assistant", "text": "seen"}))
"""

# the table in lcars_kinds.h, in its order: (role, default, list)
ROLES = [("log", "personal_log", False), ("work_log", "work_log", False), ("task", "task", False),
         ("sleep", "sleep", False), ("child_sleep", "child_sleep", False),
         ("child_vocab", "child_vocab", False), ("drive", "drive", False), ("trip", "trip", False),
         ("workout", "workout", False), ("counter", "counter", False), ("share", "share", False),
         ("page", "page", False), ("person", "person", False), ("project", "project", False),
         ("meeting", "meeting", False), ("template", "template", False),
         ("logseq_journal", "logseq_journal", False), ("imported", "logseq_journal", True)]

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build(out, target="lcars-release", source="lcars.c", name="lcars"):
    """The release compile line, pointed at `out` instead of ./lcars (or
    ./lcars-cli)."""
    plan = subprocess.run(["make", "-n", "-W", source, target], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and f" -o {name} " in l), None)
    if not line:
        sys.exit(f"kinds: cannot find the {target} compile line in `make -n`")
    print(f"building a scratch {name} ...", flush=True)
    r = subprocess.run(line.replace(f" -o {name} ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("kinds: build failed\n" + r.stderr[-3000:])


class Server:
    """A scratch server in `cwd` with exactly `env` and the logins."""

    def __init__(self, binary, cwd, env=None):
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "home").mkdir(exist_ok=True)
        self.port = free_port()
        self.cwd = cwd
        full = dict(env or {}, HOME=str(cwd / "home"), PATH=os.environ.get("PATH", "/usr/bin:/bin"),
                    LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1], LCARS_CALDAV_LOG="0",
                    LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
                    LCARS_STEWARD_USER=STEWARD[0], LCARS_STEWARD_PASS=STEWARD[1],
                    LCARS_MEDIA_ROOT=str(cwd / "nowhere"))
        full.setdefault("LCARS_EMBED", "0")
        full.setdefault("LCARS_CHAT", "0")
        self.log = open(cwd / "server.log", "w")
        stdbuf = shutil.which("stdbuf")
        pre = [stdbuf, "-oL", "-eL"] if stdbuf else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--port", str(self.port)],
                                                     cwd=cwd, env=full, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit(f"kinds: the scratch server did not come up; see {cwd / 'server.log'}")

    def req(self, method, path, body=None, login=MAIN, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": "Basic " + base64.b64encode(f"{login[0]}:{login[1]}".encode()).decode()} \
            if login else {}
        if body is not None:
            h["Content-Type"] = ctype
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body)
        c.request(method, path, body=body.encode() if isinstance(body, str) else body, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        c.close()
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def roles(self, login=MAIN):
        st, doc = self.req("GET", "/kinds/roles", login=login)
        return st, doc, {r["role"]: r for r in (doc or {}).get("roles", [])} if isinstance(doc, dict) else {}

    def put(self, body, **kw):
        return self.req("PUT", "/kinds/roles", body, **kw)

    def entry(self, eid):
        return self.req("GET", f"/entries/{eid}")[1]

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


KEYS = {"role", "what", "kind", "kinds", "default", "list", "set", "name", "rows"}


def empty(s):
    print("a new journal: no seed, every role its default")
    st, rows = s.req("GET", "/entries?deleted=all")
    check(st == 200 and rows == [], f"no row at all (got {st}, {rows})")
    st, doc, got = s.roles()
    check(st == 200 and set(doc) == {"roles", "entry", "error"}, f"200, {{roles,entry,error}} (got {st}, {doc})")
    check([r["role"] for r in doc["roles"]] == [r for r, _, _ in ROLES], "every role, in the table's order")
    bad = [r["role"] for r in doc["roles"] if set(r) != KEYS or not isinstance(r["what"], str) or len(r["what"]) < 10]
    check(bad == [], f"each with {sorted(KEYS)} and a `what` (bad: {bad})")
    wrong = [r for r, d, lst in ROLES
             if (got[r]["kind"], got[r]["kinds"], got[r]["default"], got[r]["list"], got[r]["set"],
                 got[r]["name"], got[r]["rows"]) != (d, [d], d, lst, False, "", 0)]
    check(wrong == [], f"each at its default, unset, no name, no rows (wrong: {wrong})")
    check(doc["entry"] is None and doc["error"] == "", f"no entry, no error (got {doc['entry']}, {doc['error']!r})")


def writes(s):
    print("PUT: a role set, the entry made, the rows counted")
    for i in range(2):  # two titles: the twin guard makes one row of twins
        s.req("POST", "/entries", {"kind": "naps", "title": f"nap {i}"})
    st, doc = s.put({"child_sleep": {"kind": "naps", "name": "Ada"}})
    got = {r["role"]: r for r in doc.get("roles", [])} if isinstance(doc, dict) else {}
    cs = got.get("child_sleep", {})
    check(st == 200 and cs.get("kind") == "naps" and cs.get("set") is True and cs.get("name") == "Ada"
          and cs.get("rows") == 2 and cs.get("default") == "child_sleep",
          f"child_sleep -> naps, Ada, 2 rows, answered as GET (got {st}, {cs})")
    eid = doc.get("entry") if isinstance(doc, dict) else None
    row = s.entry(eid) if eid else {}
    check(row.get("kind") == "settings" and row.get("title") == "kinds", f"the entry: settings, kinds (got {row})")
    content = json.loads(row.get("content") or "null")
    check(content == {"v": 1, "roles": {"child_sleep": {"kind": "naps", "name": "Ada"}}},
          f"its content, plainly (got {content})")
    check(s.roles()[2]["child_sleep"]["kind"] == "naps", "GET reads it back")

    print("a list role; a second PUT keeps the first's roles; null resets")
    s.req("POST", "/entries", {"kind": "other_journal", "title": "x"})
    st, doc = s.put({"imported": {"kind": "logseq_journal,other_journal"},
                     "work_log": {"kind": "field_log", "name": None}})
    got = s.roles()[2]
    check(st == 200 and got["imported"]["kinds"] == ["logseq_journal", "other_journal"]
          and got["imported"]["kind"] == "logseq_journal,other_journal" and got["imported"]["rows"] == 1,
          f"imported: two kinds, their rows summed (got {got['imported']})")
    check(got["work_log"]["kind"] == "field_log" and got["work_log"]["name"] == "",
          f"work_log set, a null name is none (got {got['work_log']})")
    check(got["child_sleep"]["kind"] == "naps" and got["child_sleep"]["name"] == "Ada", "child_sleep kept")
    check(s.req("GET", "/entries?kind=settings")[1].__len__() == 1, "still one settings entry")
    st, doc = s.put({"work_log": None})
    got = s.roles()[2]
    check(st == 200 and got["work_log"]["set"] is False and got["work_log"]["kind"] == "work_log",
          f"null: work_log back to its default (got {got['work_log']})")
    check(got["child_sleep"]["set"] and got["imported"]["set"], "and the others kept")
    check("work_log" not in json.loads(s.entry(eid)["content"])["roles"], "a reset role is not stored")
    st, _ = s.put({"task": {"kind": "chores", "name": "Chores"}, "log": {"kind": "journal"}})
    got = s.roles()[2]
    check(st == 200 and got["task"]["kind"] == "chores" and got["log"]["kind"] == "journal",
          "two roles in one PUT")
    s.put({"task": None, "log": None})
    return eid


def refusals(s, eid):
    print("refusals: a 400 each, nothing written")
    before = s.entry(eid)["content"]
    cases = [
        ({"child_sleep": {"kind": "Big Naps"}}, "not a slug (upper case, a space)"),
        ({"child_sleep": {"kind": "nap-times"}}, "not a slug (a hyphen)"),
        ({"child_sleep": {"kind": ""}}, "an empty kind"),
        ({"child_sleep": {"kind": "n" * 128}}, "128 bytes"),
        ({"child_sleep": {"kind": "naps,more"}}, "a list in a role that is not one"),
        ({"imported": {"kind": "a,,b"}}, "an empty item in a list"),
        ({"imported": {"kind": "a, b"}}, "a space in a list"),
        ({"imported": {"kind": "a,settings"}}, "the app's own kind in a list"),
        ({"nosuch": {"kind": "x"}}, "a role the table has not"),
        ({"child_sleep": "naps"}, "a value that is not an object"),
        ({"child_sleep": {"name": "Ada"}}, "no kind"),
        ({"child_sleep": {"kind": 7}}, "a kind that is not a string"),
        ({"child_sleep": {"kind": "naps", "name": "A\u0007da"}}, "a name with a control character"),
        ({"child_sleep": {"kind": "naps", "name": "A" * 64}}, "a name of 64 bytes"),
        ({}, "no role at all"),
        ({"log": {"kind": "journal"}, "child_sleep": {"kind": "Bad"}}, "one bad role among good ones"),
    ]
    for kind in ("settings", "space", "holo_program", "crew_report", "crew", "no1_log", "task_crew",
                 "task_no1_weekly", "steward_x", "task_steward"):
        cases.append(({"log": {"kind": kind}}, f"the app's own kind {kind}"))
    for body, what in cases:
        st, ans = s.put(body)
        msg = ans.get("error", "") if isinstance(ans, dict) else str(ans)
        check(st == 400 and msg, f"{what}: 400 ({st}, {msg!r})")
    for raw, what in (("[]", "an array body"), ("nope", "not JSON"), ('{"log":{"kind":"x"}} x', "trailing bytes")):
        st, _ = s.put(raw)
        check(st == 400, f"{what}: 400 ({st})")
    check(s.entry(eid)["content"] == before, "the entry unchanged by every refusal")
    check(s.roles()[2]["log"]["kind"] == "personal_log", "log still its default")


def by_hand(s, eid):
    print("the entry edited by hand")
    row = s.entry(eid)
    doc = json.loads(row["content"])
    doc["roles"]["future_role"] = {"kind": "later", "extra": [1, 2]}
    s.req("PUT", f"/entries/{eid}", {"content": json.dumps(doc)})
    st, _ = s.put({"sleep": {"kind": "rest"}})
    roles = json.loads(s.entry(eid)["content"])["roles"]
    check(st == 200 and roles.get("future_role") == {"kind": "later", "extra": [1, 2]} and roles["sleep"]["kind"] == "rest",
          f"a role this build does not know is kept by a PUT (got {roles})")

    s.req("PUT", f"/entries/{eid}", {"content": json.dumps(
        {"v": 1, "roles": {"child_sleep": {"kind": "Bad Kind"}, "sleep": {"kind": "rest"}}})})
    st, doc, got = s.roles()
    check(got["child_sleep"]["kind"] == "child_sleep" and not got["child_sleep"]["set"]
          and "child_sleep" in doc["error"] and f"#{eid}" in doc["error"],
          f"a bad value: that role its default, `error` names it (got {got['child_sleep']}, {doc['error']!r})")
    check(got["sleep"]["kind"] == "rest", "the good role still read")

    s.req("PUT", f"/entries/{eid}", {"content": "child_sleep is naps, I think"})
    st, doc, got = s.roles()
    check(doc["entry"] == eid and "not a JSON object" in doc["error"]
          and all(not r["set"] for r in doc["roles"]),
          f"not JSON: every role its default, `error` says so (got {doc['error']!r})")
    st, ans = s.put({"sleep": {"kind": "rest"}})
    check(st == 409 and s.entry(eid)["content"] == "child_sleep is naps, I think",
          f"and a PUT is refused (409), the owner's text kept ({st}, {ans})")

    s.req("PUT", f"/entries/{eid}", {"content": json.dumps({"v": 1, "roles": {"sleep": {"kind": "rest"}}})})
    st, row2 = s.req("POST", "/entries", {"kind": "settings", "title": "kinds",
                                          "content": json.dumps({"v": 1, "roles": {"sleep": {"kind": "other"}}})})
    check(s.roles()[1]["entry"] == eid and s.roles()[2]["sleep"]["kind"] == "rest", "two entries: the lowest id wins")
    s.req("DELETE", f"/entries/{eid}")
    check(s.roles()[1]["entry"] == row2["id"] and s.roles()[2]["sleep"]["kind"] == "other",
          "the first deleted: the next one read")
    s.req("PUT", f"/entries/{eid}", {"deleted": 0})


def who(s):
    print("who may")
    st, doc, got = s.roles(login=CREW)
    check(st == 200 and got.get("sleep", {}).get("kind") == "rest", f"the crew's login reads it ({st})")
    st, _ = s.put({"sleep": {"kind": "elsewhere"}}, login=CREW)
    check(st == 403 and s.roles()[2]["sleep"]["kind"] == "rest", f"and may not write it ({st})")
    check(s.req("GET", "/kinds/roles", login=None)[0] == 401, "no login: 401")
    check(s.req("POST", "/kinds/roles", {})[0] == 405, "POST: 405")
    st, body = s.req("GET", "/")
    check(st == 200 and "/kinds/roles" in json.dumps(body), "GET / lists /kinds/roles")


def caldav(s, eid):
    st, doc = s.req("GET", f"/entries/{eid}/caldav")
    return doc if st == 200 and isinstance(doc, dict) else {}


def follows(binary, tmp):
    print("the server following the roles")
    d = tmp / "two"
    d.mkdir()
    claude = d / "claude"
    claude.write_text(CLAUDE)
    claude.chmod(0o755)
    stub_out = d / "claude.json"
    s = Server(binary, d, {"LCARS_CHAT": "1", "LCARS_CLAUDE_BIN": str(claude), "LCARS_CHAT_DIR": str(d / "home"),
                           "STUB_OUT": str(stub_out)})
    try:
        st, row = s.req("POST", "/entries", {"kind": "chores", "title": "sweep"})
        chore = row["id"]
        st, row = s.req("POST", "/entries", {"kind": "task", "title": "old"})
        task = row["id"]
        got = caldav(s, chore)
        check(got.get("task_kind") == "task" and got.get("list") == "", f"CalDAV: the default task kind ({got})")
        s.put({"task": {"kind": "chores"}})
        got = caldav(s, chore)
        check(got.get("task_kind") == "chores" and got.get("synced") is True,
              f"the task role set: CalDAV's task kind is chores, the row in its list, at the next request ({got})")
        check(caldav(s, task).get("synced") is False, "a row of the old task kind is no longer published")

        print("the logins' reminders follow the task kind")
        st, _ = s.req("POST", "/entries", {"kind": "chores_crew", "title": "for the captain"}, login=CREW)
        check(st in (200, 201), f"the crew writes chores_crew ({st})")
        st, _ = s.req("POST", "/entries", {"kind": "chores_crew_weekly", "title": "x"}, login=CREW)
        check(st in (200, 201), f"and chores_crew_weekly ({st})")
        st, ans = s.req("POST", "/entries", {"kind": "task_crew", "title": "x"}, login=CREW)
        check(st == 403 and "chores_crew" in str(ans), f"task_crew is not its own now, and the refusal says chores_crew ({st}, {ans})")
        st, _ = s.req("POST", "/entries", {"kind": "chores_crew", "title": "x"}, login=STEWARD)
        check(st == 403, f"the steward may not write the crew's chores_crew ({st})")
        st, _ = s.req("POST", "/entries", {"kind": "task_crew", "title": "x"}, login=STEWARD)
        check(st in (200, 201), f"task_crew is a plain kind under the chores task kind: the steward's to write ({st})")

        print("a PUT that would put a role among a login's reminders")
        for body, what in (({"log": {"kind": "chores_crew"}}, "log -> chores_crew"),
                           ({"meeting": {"kind": "chores_no1_x"}}, "meeting -> chores_no1_x"),
                           ({"task": {"kind": "work"}, "log": {"kind": "work_steward"}}, "task -> work and log -> work_steward"),
                           ({"imported": {"kind": "logseq_journal,chores_steward"}}, "chores_steward in the list")):
            st, ans = s.put(body)
            check(st == 400 and "reminders" in str(ans), f"{what}: 400 ({st}, {ans})")
        s.put({"log": {"kind": "work_crew"}})
        st, ans = s.put({"task": {"kind": "work"}})
        check(st == 400 and s.roles()[2]["task"]["kind"] == "chores",
              f"task -> work under a log already work_crew: 400, nothing written ({st}, {ans})")
        s.put({"log": None})

        print("the steward and the imported role")
        st, _ = s.req("POST", "/entries", {"kind": "logseq_journal", "title": "x"}, login=STEWARD)
        check(st == 403, f"the default import, logseq_journal: refused ({st})")
        st, _ = s.req("POST", "/entries", {"kind": "other_journal", "title": "x"}, login=STEWARD)
        check(st in (200, 201), f"other_journal before it is an import: allowed ({st})")
        s.put({"imported": {"kind": "logseq_journal,other_journal"}})
        st, _ = s.req("POST", "/entries", {"kind": "other_journal", "title": "y"}, login=STEWARD)
        check(st == 403, f"other_journal in the imported role: refused at the next request ({st})")
        st, row = s.req("POST", "/entries", {"kind": "journal", "title": "z"})
        now = s.entry(row["id"])
        st, _ = s.req("PATCH", f"/entries/{row['id']}",
                      {"kind": "other_journal", "if_modified": now["last_modified_at_utc"]}, login=STEWARD)
        check(st == 403, f"nor moved into it ({st})")

        print("the computer's prompts name the log and task kinds")
        s.put({"log": {"kind": "journal"}})
        for route, json_out in (("/chat", False), ("/ask", True)):
            if stub_out.exists():
                stub_out.unlink()
            st, _ = s.req("POST", route, {"message": "log that I swept"})
            saw = json.loads(stub_out.read_text()) if stub_out.exists() else {"argv": []}
            argv = saw["argv"]
            prompt = argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else ""
            check(st == 200 and "the log kind is journal" in prompt and "the task kind is chores" in prompt
                  and "chores_<list> is a Reminders list" in prompt and "the work log is work_log" in prompt,
                  f"{route}: the kinds from the roles ({st}, ...{prompt[-220:]!r})")
            check("personal_log" not in prompt and "kind task" not in prompt,
                  f"{route}: no default kind named in the prompt's own words")
    finally:
        s.stop()

    print("$LCARS_TASK_KIND still wins for CalDAV")
    d = tmp / "three"
    s = Server(binary, d, {"LCARS_TASK_KIND": "todo"})
    try:
        st, row = s.req("POST", "/entries", {"kind": "todo", "title": "a"})
        s.put({"task": {"kind": "chores"}})
        got = caldav(s, row["id"])
        check(got.get("task_kind") == "todo" and got.get("synced") is True,
              f"the task role set to chores, CalDAV's task kind is still todo ({got})")
    finally:
        s.stop()


def cli_roles(binary, cli, tmp):
    print("lcars-cli roles")
    s = Server(binary, tmp / "four")

    def run(*args, login=MAIN, url=None):
        env = dict(os.environ, LCARS_URL=url or f"http://127.0.0.1:{s.port}",
                   LCARS_AUTH_USER=login[0], LCARS_AUTH_PASS=login[1])
        r = subprocess.run([str(cli), *args], env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr

    def line(out, role):
        return next((l for l in out.splitlines() if l.split()[:1] == [role]), "")

    try:
        rc, out, err = run("roles")
        check(rc == 0 and out.splitlines()[0].split() == ["ROLE", "KIND", "ROWS", "NAME"]
              and len(out.splitlines()) == len(ROLES) + 2 and line(out, "log").split() == ["log", "personal_log", "0"]
              and "every role its default" in out, f"roles: the table, every role its default ({rc}, {out!r})")
        rc, out, err = run("--json", "roles")
        doc = json.loads(out) if rc == 0 else {}
        check([r["role"] for r in doc.get("roles", [])] == [r for r, _, _ in ROLES], "--json: the server's answer")
        s.req("POST", "/entries", {"kind": "naps", "title": "a nap"})
        rc, out, err = run("roles", "set", "child_sleep", "naps", "--name", "Ada Lovelace")
        check(rc == 0 and line(out, "child_sleep").split() == ["child_sleep", "*", "naps", "1", "Ada", "Lovelace"]
              and "1 set in the journal's settings entry #" in out,
              f"set with --name: marked, its rows and name ({rc}, {line(out, 'child_sleep')!r})")
        rc, out, err = run("roles", "set", "child_sleep", "naptimes")
        check(rc == 0 and line(out, "child_sleep").split() == ["child_sleep", "*", "naptimes", "0", "Ada", "Lovelace"],
              f"set without --name keeps the name ({line(out, 'child_sleep')!r})")
        rc, out, err = run("roles", "set", "child_sleep", "naptimes", "--name", "")
        check(rc == 0 and line(out, "child_sleep").split() == ["child_sleep", "*", "naptimes", "0"],
              f"--name \"\" clears it ({line(out, 'child_sleep')!r})")
        rc, out, err = run("roles", "set", "imported", "logseq_journal,other_journal")
        check(rc == 0 and "logseq_journal,other_journal" in line(out, "imported"), "a list role, comma-joined")
        rc, out, err = run("roles", "reset", "child_sleep")
        check(rc == 0 and line(out, "child_sleep").split() == ["child_sleep", "child_sleep", "0"],
              f"reset: back to its default ({line(out, 'child_sleep')!r})")
        check(s.roles()[2]["imported"]["set"], "and the others kept")
        rc, out, err = run("roles", "set", "log", "Not A Slug")
        check(rc == 1 and "lowercase" in err and "HTTP 400" in err, f"the server's refusal, exit 1 ({rc}, {err.strip()!r})")
        rc, out, err = run("roles", "set", "nosuch", "x")
        check(rc == 1 and "no role nosuch" in err, f"an unknown role, exit 1 ({err.strip()!r})")
        for args in (("roles", "set", "log"), ("roles", "frob"), ("roles", "reset"), ("roles", "--name", "x")):
            rc, out, err = run(*args)
            check(rc == 2 and out == "", f"{' '.join(args)}: a usage error, exit 2 ({rc}, {err.strip()!r})")
        rc, out, err = run("roles", login=CREW)
        check(rc == 0 and line(out, "imported"), "the crew's login lists them")
        rc, out, err = run("roles", "set", "log", "journal", login=CREW)
        check(rc == 1 and "403" in err and s.roles()[2]["log"]["kind"] == "personal_log",
              f"and may not set one, exit 1 ({err.strip()!r})")
    finally:
        s.stop()

    # a server older than the route: every path a 404
    class Old(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"error":"No route","status":404}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    old = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Old)
    threading.Thread(target=old.serve_forever, daemon=True).start()
    try:
        rc, out, err = run("roles", url=f"http://127.0.0.1:{old.server_address[1]}")
        check(rc == 1 and "older than LCARS 0.273.0" in err, f"an older server: said so, exit 1 ({err.strip()!r})")
    finally:
        old.shutdown()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-kinds-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp / "one")
    try:
        empty(s)
        eid = writes(s)
        refusals(s, eid)
        by_hand(s, eid)
        who(s)
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()
    follows(binary, tmp)
    cli = os.environ.get("LCARS_TEST_CLI")
    if not cli:
        cli = tmp / "lcars-cli"
        build(cli, "lcars-cli", "lcars_cli.c", "lcars-cli")
    cli_roles(binary, cli, tmp)
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server logs under {tmp}")
        sys.exit(1)
    print(f"\nkinds: all {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
