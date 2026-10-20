#!/usr/bin/env python3
"""The limited logins, end to end: what Number One and the crew may write.

lcars_logins.h gives Number One (LCARS_NO1_USER/PASS) and the scheduled crew
roles (LCARS_CREW_USER/PASS) logins that read everything and write only
entries of their own kinds. This drives a scratch build of the real server
with each login and checks every allowed and refused shape:

  1. reads anywhere, but never /engineer or CalDAV;
  2. POST /entries only with its own kind (crew_*, task_crew, task_crew_*),
     never a plain-text body, a lookalike (crewx, task_crewx) or the other
     login's kinds;
  3. PUT/PATCH/DELETE only on its own rows, and never moving one to a
     foreign kind or a foreign one into its own;
  4. uploads (an entry's, a chat's) and /transcribe refused, /chat-type routes let through to
     their handler;
  5. a login whose variables are unset (or whose user is another login's)
     does not exist: 401;
  7. the patch kinds (deck_patch, ui_patch: docs/design/architect.md 2.2)
     are the pages' alone: a write that creates one, or changes one (PUT,
     PATCH, a restore, append, title, end), or moves a row to one, without
     X-LCARS-Client is refused, the main login's too; a DELETE is let
     through; a scratch lcars-cli's `new --kind deck_patch` and `set` are
     refused (and its other writes not);
  6. the steward (LCARS_STEWARD_USER/PASS, the crew notes' runner) creates
     the captain's kinds, appends to his entries through POST
     /entries/<id>/append and sets their titles through POST
     /entries/<id>/title (the old title in the answer), closes an open one
     through POST /entries/<id>/end (never moving an end), and (2026-10-16)
     PATCHes any field, DELETEs (soft) and restores (PATCH deleted 0) the
     captain's rows, each only with if_modified - a stale one a 412, a
     deleted row 409 (a restore: a live one), another login's or an
     import's kind 403, before or after; PUT, a PATCH or DELETE without
     if_modified, `deleted` 1 or as a string, a create naming `deleted`
     are refused, the row left byte for byte as it was.

    python3 test/logins.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/logins.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build, free_port  # noqa: E402
from onebin import build_cli  # noqa: E402

MAIN = ("t", "t")
NO1 = ("no1", "no1-password-0123456789")
CREW = ("crew", "crew-password-0123456789")
STEWARD = ("steward", "steward-password-0123456789")

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Server:
    def __init__(self, binary, tmp, extra):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1])
        for k in ("LCARS_NO1_USER", "LCARS_NO1_PASS", "LCARS_CREW_USER",
                  "LCARS_CREW_PASS", "LCARS_STEWARD_USER", "LCARS_STEWARD_PASS",
                  "LCARS_ENGINEER", "DEEPGRAM_API_KEY"):
            env.pop(k, None)
        env.update(extra)
        tmp.mkdir(parents=True, exist_ok=True)
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("logins: the scratch server did not come up; see " + str(tmp / "server.log"))

    def req(self, login, method, path, body=None, ctype="application/json", page=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": "Basic " + base64.b64encode(
            f"{login[0]}:{login[1]}".encode()).decode()}
        if page:  # what the pages send on every request, and lcars-cli never
            h["X-LCARS-Client"] = "web"
        if body is not None:
            h["Content-Type"] = ctype
            if not isinstance(body, str):
                body = json.dumps(body)
        c.request(method, path, body=body.encode() if body is not None else None, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        c.close()
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def make(self, kind):
        st, row = self.req(MAIN, "POST", "/entries", {"kind": kind, "title": kind})
        assert st in (200, 201), (st, row)
        return row["id"]

    def kind_of(self, id_):
        return self.req(MAIN, "GET", f"/entries/{id_}")[1].get("kind")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def ok(st):
    return st in (200, 201)


def run_login(s, who, login, owner, other):
    """Every rule for one login; `other` is the other login's owner."""
    print(f"\n{who}")
    foreign = s.make("journal")
    others = s.make(f"{other}_log")
    own = s.make(f"{owner}_report")

    # reads
    st, rows = s.req(login, "GET", "/entries")
    check(st == 200 and len(rows) >= 3, "reads the whole journal")
    check(s.req(login, "GET", f"/entries/{foreign}")[0] == 200, "reads a foreign entry")
    check(s.req(login, "GET", "/kinds")[0] == 200, "reads /kinds")
    check(s.req(login, "GET", "/engineer")[0] == 403, "GET /engineer refused")
    check(s.req(login, "POST", "/engineer/x/say", {"text": "hi"})[0] == 403,
          "POST /engineer/<name>/say refused")
    # the model per engineer and a deploy are the captain's
    check(s.req(login, "POST", "/engineer/x/model", {"model": "haiku"})[0] == 403,
          "POST /engineer/<name>/model refused")
    check(s.req(login, "POST", "/engineer/x/deploy", {})[0] == 403,
          "POST /engineer/<name>/deploy refused")
    check(s.req(login, "PROPFIND", "/caldav/calendars/")[0] == 403, "CalDAV refused")
    check(s.req(login, "GET", "/.well-known/caldav")[0] == 403, "CalDAV discovery refused")
    # a Deepgram key, however short-lived, is money: the captain's alone
    check(s.req(login, "GET", "/say/token")[0] == 403, "GET /say/token refused")

    # creates
    for kind in (f"{owner}_report", f"task_{owner}", f"task_{owner}_weekly"):
        st, row = s.req(login, "POST", "/entries", {"kind": kind, "title": "x"})
        check(ok(st) and isinstance(row, dict) and s.kind_of(row.get("id")) == kind,
              f"POST kind {kind} allowed")
    for kind in ("journal", f"{owner}x", f"task_{owner}x", f"{other}_log", "task", ""):
        st, _ = s.req(login, "POST", "/entries", {"kind": kind, "title": "x"})
        check(st == 403, f"POST kind {kind!r} refused")
    check(s.req(login, "POST", "/entries", {"title": "no kind"})[0] == 403,
          "POST without a kind refused")
    check(s.req(login, "POST", "/entries", f'{{"kind":"{owner}_report"}}',
                ctype="text/plain")[0] == 403,
          "POST plain text refused (the handler would store it in the default kind)")

    # edits
    st, _ = s.req(login, "PUT", f"/entries/{own}", {"title": "edited"})
    check(ok(st), "PUT own row allowed")
    st, _ = s.req(login, "PATCH", f"/entries/{own}", {"kind": f"task_{owner}"})
    check(ok(st) and s.kind_of(own) == f"task_{owner}", "PATCH own row to another own kind allowed")
    st, _ = s.req(login, "PUT", f"/entries/{own}", {"kind": "journal"})
    check(st == 403 and s.kind_of(own) == f"task_{owner}", "PUT moving own row to a foreign kind refused")
    st, _ = s.req(login, "PUT", f"/entries/{foreign}", {"title": "mine now"})
    check(st == 403, "PUT foreign row refused")
    st, _ = s.req(login, "PUT", f"/entries/{foreign}", {"kind": f"{owner}_report"})
    check(st == 403 and s.kind_of(foreign) == "journal", "PUT moving a foreign row into its kind refused")
    st, _ = s.req(login, "PATCH", f"/entries/{others}", {"title": "x"})
    check(st == 403, f"PATCH the other login's row ({other}_log) refused")
    check(s.req(login, "DELETE", f"/entries/{foreign}")[0] == 403, "DELETE foreign row refused")
    check(s.req(login, "PUT", "/entries/999999", {"title": "x"})[0] == 404, "PUT missing row is a 404")
    check(ok(s.req(login, "DELETE", f"/entries/{own}")[0]), "DELETE own row allowed")
    st, _ = s.req(login, "PUT", f"/entries/{own}", {"deleted": 0})
    check(ok(st), "restore own row allowed")

    # the rest
    check(s.req(login, "POST", f"/entries/{own}/media?name=a.txt", "hello",
                ctype="text/plain")[0] == 403, "upload refused")
    check(s.req(login, "POST", "/chat/media?name=a.txt", "hello",
                ctype="text/plain")[0] == 403, "a chat's upload refused")
    check(s.req(login, "PUT", f"/entries/{foreign}/caldav", {"extra_ical": ""})[0] == 403,
          "PUT a foreign row's caldav refused")
    # the server runs with LCARS_CHAT=0 and LCARS_EMBED=0, so the handlers
    # answer for themselves; what matters is that the gate did not
    for route, body in (("/chat", {"message": "hi"}), ("/embed", {"text": "hi"})):
        st, ans = s.req(login, "POST", route, body)
        check(st != 401 and "write only" not in str(ans),
              f"POST {route} reaches its handler ({st} {ans.get('error') if isinstance(ans, dict) else ''})")
    check(s.req(login, "POST", "/tapes/abcdef?off=0", "x", ctype="application/octet-stream")[0] == 403,
          "POST /tapes refused")
    # Deepgram is money, and no limited login has a microphone (as /say/token)
    check(s.req(login, "POST", "/transcribe", "\0\0", ctype="application/octet-stream")[0] == 403,
          "POST /transcribe refused")
    check(s.req(MAIN, "GET", f"/entries/{foreign}")[1].get("title") == "journal",
          "the foreign row is untouched")


def run_steward(s):
    """Create, append and title, and nothing else that changes a row."""
    print("\nsteward")
    row = lambda i: s.req(MAIN, "GET", f"/entries/{i}")[1]
    st, ans = s.req(MAIN, "POST", "/entries", {"kind": "journal", "title": "Gym day", "content": "Legs.",
                                              "start_date": "2026-10-15 07:00:00"})
    mine = ans["id"]
    was = row(mine)
    crew = s.make("crew_note")
    no1 = s.make("no1_log")
    frozen = s.make("logseq_journal")
    # the frozen imports are the `imported` role's kinds (lcars_kinds.h): a
    # journal's own list, set by its owner as kinds.local.md does
    st, _ = s.req(MAIN, "PUT", "/kinds/roles",
                  {"imported": {"kind": "logseq_journal,capacities_journal,noteplan_journal"}})
    check(st == 200, f"the owner sets the imported role ({st})")

    check(s.req(STEWARD, "GET", f"/entries/{mine}")[0] == 200, "reads the journal")
    for path in ("/engineer", "/say/token", "/.well-known/caldav"):
        check(s.req(STEWARD, "GET", path)[0] == 403, f"GET {path} refused")
    # creates: the captain's kinds only
    for kind in ("sleep", "journal", "task", "task_home", "crewx"):
        st, ans = s.req(STEWARD, "POST", "/entries", {"kind": kind, "title": "t", "content": "c"})
        check(ok(st) and s.kind_of(ans.get("id")) == kind, f"POST kind {kind} allowed")
    for kind in ("crew_note", "crew_yeoman", "task_crew", "no1_log", "task_no1", "steward_x", "task_steward",
                 "logseq_journal", "capacities_journal", "noteplan_journal", ""):
        st, _ = s.req(STEWARD, "POST", "/entries", {"kind": kind, "title": "t"})
        check(st == 403, f"POST kind {kind!r} refused")
    check(s.req(STEWARD, "POST", "/entries", {"title": "no kind"})[0] == 403, "POST without a kind refused")
    check(s.req(STEWARD, "POST", "/entries", "plain words", ctype="text/plain")[0] == 403, "POST plain text refused")
    for d in (1, 0, "1"):
        st, _ = s.req(STEWARD, "POST", "/entries", {"kind": "sleep", "title": "t", "deleted": d})
        check(st == 403, f"POST naming deleted={d!r} refused")

    # append: the end only, the row as it was read
    st, ans = s.req(STEWARD, "POST", f"/entries/{mine}/append",
                    {"text": "\n\n> Yeoman added:\n> logged", "if_modified": was["last_modified_at_utc"]})
    now = row(mine)
    check(st == 200 and now["content"] == "Legs.\n\n> Yeoman added:\n> logged",
          f"append adds at the end ({st})")
    check(now["title"] == was["title"] and now["kind"] == was["kind"] and now["start_date"] == was["start_date"],
          "and leaves the title, kind and dates")
    check(ans.get("last_modified_at_utc") == now["last_modified_at_utc"], "the answer carries the new stamp")
    # stamps are whole seconds: the captain's edit lands a second later, so
    # the stamp the steward read is stale
    time.sleep(1.1)
    s.req(MAIN, "PUT", f"/entries/{mine}", {"content": now["content"] + " typed"})
    before = row(mine)
    st, _ = s.req(STEWARD, "POST", f"/entries/{mine}/append", {"text": "late", "if_modified": now["last_modified_at_utc"]})
    check(st == 412 and row(mine) == before, f"append to a row edited since it was read is a 412, the row untouched ({st})")
    for body, why in (({"text": "x"}, "without if_modified"), ({"if_modified": before["last_modified_at_utc"]}, "without text"),
                      ({"text": "", "if_modified": before["last_modified_at_utc"]}, "with empty text")):
        check(s.req(STEWARD, "POST", f"/entries/{mine}/append", body)[0] == 400, f"append {why} is a 400")
    check(s.req(STEWARD, "POST", f"/entries/{mine}/append", '{"text":"x","if_modified":"y"}',
                ctype="text/plain")[0] == 400, "append with a plain-text body is a 400")
    st, _ = s.req(STEWARD, "POST", f"/entries/{mine}/append",
                  {"content": "REPLACED", "title": "REPLACED", "text": "!", "if_modified": before["last_modified_at_utc"]})
    after = row(mine)
    check(ok(st) and after["content"] == before["content"] + "!" and after["title"] == before["title"],
          "append takes only its text: a content or title in the body is ignored")
    for target, name in ((crew, "crew_note"), (no1, "no1_log"), (frozen, "logseq_journal")):
        r = row(target)
        st, _ = s.req(STEWARD, "POST", f"/entries/{target}/append", {"text": "x", "if_modified": r["last_modified_at_utc"]})
        check(st == 403 and row(target) == r, f"append to a {name} row refused")
    check(s.req(STEWARD, "POST", "/entries/999999/append", {"text": "x", "if_modified": "2026-01-01 00:00:00"})[0] == 404,
          "append to a missing row is a 404")
    gone = s.make("journal")
    s.req(MAIN, "DELETE", f"/entries/{gone}")
    st, _ = s.req(STEWARD, "POST", f"/entries/{gone}/append",
                  {"text": "x", "if_modified": row(gone)["last_modified_at_utc"]})
    check(st == 409, f"append to a deleted row is a 409 ({st})")
    check(s.req(STEWARD, "GET", f"/entries/{mine}/append")[0] == 405, "GET on append is a 405")

    # title: the title and the stamp, nothing else, the old title answered
    was = row(mine)
    time.sleep(1.1)
    st, ans = s.req(STEWARD, "POST", f"/entries/{mine}/title",
                    {"title": "Legs at the gym", "if_modified": was["last_modified_at_utc"]})
    now = row(mine)
    check(st == 200 and now["title"] == "Legs at the gym", f"the steward sets a title ({st})")
    check({k: v for k, v in now.items() if k not in ("title", "last_modified_at_utc")} ==
          {k: v for k, v in was.items() if k not in ("title", "last_modified_at_utc")},
          "and nothing else of the row but its stamp")
    check(now["last_modified_at_utc"] > was["last_modified_at_utc"], "the stamp moves")
    check(isinstance(ans, dict) and ans.get("old_title") == was["title"] and ans.get("title") == "Legs at the gym"
          and ans.get("id") == mine and ans.get("last_modified_at_utc") == now["last_modified_at_utc"],
          f"the answer is the row with old_title ({ans})")
    st, _ = s.req(STEWARD, "POST", f"/entries/{mine}/title", {"title": "Stale", "if_modified": was["last_modified_at_utc"]})
    check(st == 412 and row(mine) == now, f"a title on a row moved since it was read is a 412, the row untouched ({st})")
    stamp = now["last_modified_at_utc"]
    for body, why in (({"title": "x"}, "without if_modified"), ({"if_modified": stamp}, "without a title"),
                      ({"title": "", "if_modified": stamp}, "with an empty title"),
                      ({"title": "   ", "if_modified": stamp}, "with a blank title"),
                      ({"title": "two\nlines", "if_modified": stamp}, "over two lines"),
                      ({"title": "x" * 512, "if_modified": stamp}, "over 511 bytes")):
        check(s.req(STEWARD, "POST", f"/entries/{mine}/title", body)[0] == 400, f"title {why} is a 400")
    check(s.req(STEWARD, "POST", f"/entries/{mine}/title", '{"title":"x","if_modified":"y"}',
                ctype="text/plain")[0] == 400, "title with a plain-text body is a 400")
    check(row(mine) == now, "and none of those touched the row")
    st, _ = s.req(STEWARD, "POST", f"/entries/{mine}/title",
                  {"title": "x" * 511, "content": "REPLACED", "kind": "sleep", "done_bool": 1, "if_modified": stamp})
    after = row(mine)
    check(ok(st) and after["title"] == "x" * 511 and after["content"] == now["content"] and after["kind"] == now["kind"]
          and after["done_bool"] == now["done_bool"], "title takes only its title (511 bytes fits): the rest is ignored")
    for target, name in ((crew, "crew_note"), (no1, "no1_log"), (frozen, "logseq_journal")):
        r = row(target)
        st, _ = s.req(STEWARD, "POST", f"/entries/{target}/title", {"title": "x", "if_modified": r["last_modified_at_utc"]})
        check(st == 403 and row(target) == r, f"title on a {name} row refused")
    check(s.req(STEWARD, "POST", "/entries/999999/title", {"title": "x", "if_modified": "2026-01-01 00:00:00"})[0] == 404,
          "title on a missing row is a 404")
    st, _ = s.req(STEWARD, "POST", f"/entries/{gone}/title", {"title": "x", "if_modified": row(gone)["last_modified_at_utc"]})
    check(st == 409, f"title on a deleted row is a 409 ({st})")
    check(s.req(STEWARD, "GET", f"/entries/{mine}/title")[0] == 405, "GET on title is a 405")
    for who, login in (("crew", CREW), ("no1", NO1)):
        r = row(mine)
        st, _ = s.req(login, "POST", f"/entries/{mine}/title", {"title": "x", "if_modified": r["last_modified_at_utc"]})
        check(st == 403 and row(mine) == r, f"{who} may not title the captain's row ({st})")

    # end: an open entry closed, the end and the stamp only, never moved
    st, ans = s.req(MAIN, "POST", "/entries", {"kind": "drive", "title": "Drive", "content": "Home to work.",
                                              "start_date": "2026-10-16 06:50:00"})
    drive = ans["id"]
    was = row(drive)
    st, _ = s.req(STEWARD, "POST", f"/entries/{drive}/end", {"end": "2026-10-16 06:00:00",
                                                              "if_modified": was["last_modified_at_utc"]})
    check(st == 400 and row(drive) == was, f"an end before the start is a 400 ({st})")
    st, _ = s.req(STEWARD, "POST", f"/entries/{drive}/end", {"end": "2026-10-16 06:50:00",
                                                              "if_modified": was["last_modified_at_utc"]})
    check(st == 400 and row(drive) == was, f"an end at the start is a 400 ({st})")
    for body, why in (({"end": "2026-10-16 08:12:00"}, "without if_modified"),
                      ({"if_modified": was["last_modified_at_utc"]}, "without an end"),
                      ({"end": "", "if_modified": was["last_modified_at_utc"]}, "with an empty end"),
                      ({"end": "tomorrow", "if_modified": was["last_modified_at_utc"]}, "with a bad stamp")):
        check(s.req(STEWARD, "POST", f"/entries/{drive}/end", body)[0] == 400, f"end {why} is a 400")
    check(s.req(STEWARD, "POST", f"/entries/{drive}/end", '{"end":"2026-10-16 08:12","if_modified":"y"}',
                ctype="text/plain")[0] == 400, "end with a plain-text body is a 400")
    st, _ = s.req(STEWARD, "POST", f"/entries/{drive}/end", {"end": "2026-10-16 08:12:00", "if_modified": "2020-01-01 00:00:00"})
    check(st == 412 and row(drive) == was, f"an end on a row moved since it was read is a 412 ({st})")
    st, ans = s.req(STEWARD, "POST", f"/entries/{drive}/end",
                    {"end": "2026-10-16 08:12:00", "title": "REPLACED", "content": "REPLACED", "start_date": "2026-01-01",
                     "done_bool": 1, "if_modified": was["last_modified_at_utc"]})
    now = row(drive)
    check(st == 200 and now["end_date"] == "2026-10-16 08:12:00", f"the steward closes an open entry ({st}, {now.get('end_date')})")
    check({k: v for k, v in now.items() if k not in ("end_date", "last_modified_at_utc")} ==
          {k: v for k, v in was.items() if k not in ("end_date", "last_modified_at_utc")},
          "and changes nothing else: the rest of the body is ignored")
    check(isinstance(ans, dict) and ans.get("old_end_date") == "" and ans.get("end_date") == "2026-10-16 08:12:00"
          and ans.get("id") == drive, f"the answer is the row with old_end_date ({ans})")
    st, _ = s.req(STEWARD, "POST", f"/entries/{drive}/end", {"end": "2026-10-16 09:00:00", "if_modified": now["last_modified_at_utc"]})
    check(st == 409 and row(drive) == now, f"an end already set is never moved: a 409 ({st})")
    st, ans = s.req(MAIN, "POST", "/entries", {"kind": "journal", "title": "No span", "content": "x"})
    st, _ = s.req(STEWARD, "POST", f"/entries/{ans['id']}/end", {"end": "2026-10-16 09:00:00",
                                                                  "if_modified": row(ans["id"])["last_modified_at_utc"]})
    check(st == 400, f"an end on a row with no start is a 400 ({st})")
    for target, name in ((crew, "crew_note"), (no1, "no1_log"), (frozen, "logseq_journal")):
        r = row(target)
        st, _ = s.req(STEWARD, "POST", f"/entries/{target}/end", {"end": "2030-01-01 00:00:00", "if_modified": r["last_modified_at_utc"]})
        check(st == 403 and row(target) == r, f"end on a {name} row refused")
    check(s.req(STEWARD, "POST", "/entries/999999/end", {"end": "2026-10-16 09:00:00", "if_modified": "2026-01-01 00:00:00"})[0] == 404,
          "end on a missing row is a 404")
    st, _ = s.req(STEWARD, "POST", f"/entries/{gone}/end", {"end": "2030-01-01 00:00:00", "if_modified": row(gone)["last_modified_at_utc"]})
    check(st == 409, f"end on a deleted row is a 409 ({st})")
    check(s.req(STEWARD, "GET", f"/entries/{drive}/end")[0] == 405, "GET on end is a 405")
    for who, login in (("crew", CREW), ("no1", NO1)):
        st, ans = s.req(MAIN, "POST", "/entries", {"kind": "sleep", "title": "Sleep " + who, "start_date": "2026-10-15 20:00:00"})
        r = row(ans["id"])
        st, _ = s.req(login, "POST", f"/entries/{r['id']}/end", {"end": "2026-10-16 04:00:00", "if_modified": r["last_modified_at_utc"]})
        check(st == 403 and row(r["id"]) == r, f"{who} may not close the captain's row ({st})")
        st, _ = s.req(MAIN, "POST", f"/entries/{r['id']}/end", {"end": "2026-10-16T07:00:00+03:00",
                                                                "if_modified": r["last_modified_at_utc"]})
        check(ok(st) and row(r["id"])["end_date"] == "2026-10-16 04:00:00",
              f"the main login may close one, an ISO stamp with an offset taken as UTC ({st})")

    guarded(s, row, mine)

    # every way of altering what is there unguarded: refused, the row as it was
    held = row(mine)
    at = held["last_modified_at_utc"]
    for method, body, what in (("PUT", {"content": "gone"}, "content"), ("PATCH", {"title": "x"}, "title"),
                               ("PATCH", {"kind": "sleep"}, "kind"), ("PUT", {"start_date": ""}, "dates"),
                               ("PATCH", {"done_bool": 1}, "done"), ("PUT", {"deleted": 1}, "deleted"),
                               ("PUT", {"title": "x", "if_modified": at}, "with if_modified (PUT is never)"),
                               ("PATCH", {"title": "x", "if_modified": ""}, "with an empty if_modified"),
                               ("PATCH", {"deleted": 1, "if_modified": at}, "deleted 1 (DELETE is the way)"),
                               ("PATCH", {"deleted": "0", "if_modified": at}, "deleted as a string"),
                               ("PATCH", {"kind": "crew_note", "if_modified": at}, "a kind moved to the crew's"),
                               ("PATCH", {"kind": "logseq_journal", "if_modified": at}, "a kind moved to an import"),
                               ("PATCH", '{"title":"x","if_modified":"' + at + '"}', "a guarded plain-text body"),
                               ("DELETE", {"if_modified": ""}, "an empty if_modified"),
                               ("PUT", "plain words", "content as plain text")):
        st, _ = s.req(STEWARD, method, f"/entries/{mine}", body,
                      ctype="text/plain" if isinstance(body, str) else "application/json")
        check(st == 403, f"{method} {what} refused ({st})")
    check(s.req(STEWARD, "DELETE", f"/entries/{mine}")[0] == 403, "DELETE without if_modified refused")
    check(s.req(STEWARD, "PUT", f"/entries/{mine}/caldav", {"extra_ical": ""})[0] == 403, "PUT caldav refused")
    check(s.req(STEWARD, "POST", f"/entries/{mine}/media?name=a.txt", "hi", ctype="text/plain")[0] == 403,
          "upload refused")
    check(s.req(STEWARD, "POST", "/chat/media?name=a.txt", "hi", ctype="text/plain")[0] == 403,
          "a chat's upload refused")
    for route in ("/chat", "/ask", "/embed"):
        check(s.req(STEWARD, "POST", route, {"message": "hi"})[0] == 403, f"POST {route} refused")
    check(s.req(STEWARD, "PATCH", f"/entries/{crew}", {"title": "x"})[0] == 403, "PATCH a crew row refused too")
    for target, name in ((crew, "crew_note"), (no1, "no1_log"), (frozen, "logseq_journal")):
        r = row(target)
        for method, body in (("PATCH", {"title": "x", "if_modified": r["last_modified_at_utc"]}),
                             ("DELETE", {"if_modified": r["last_modified_at_utc"]})):
            st, _ = s.req(STEWARD, method, f"/entries/{target}", body)
            check(st == 403 and row(target) == r, f"a guarded {method} of a {name} row refused ({st})")
    check(row(mine) == held, "and the captain's row is byte for byte as it was")
    # the captain may append too (the page does not, today)
    st, _ = s.req(MAIN, "POST", f"/entries/{mine}/append", {"text": ".", "if_modified": held["last_modified_at_utc"]})
    check(ok(st) and row(mine)["content"] == held["content"] + ".", "the main login may append")
    # and title (the page's Undo of a crew title is a PUT, as any edit of his)
    held = row(mine)
    st, ans = s.req(MAIN, "POST", f"/entries/{mine}/title", {"title": "Gym day", "if_modified": held["last_modified_at_utc"]})
    check(ok(st) and row(mine)["title"] == "Gym day" and ans.get("old_title") == held["title"], "the main login may title")


def guarded(s, row, mine):
    """The steward's guarded writes (2026-10-16): PATCH any field, DELETE,
    restore, each with if_modified compared in the UPDATE's own WHERE."""
    time.sleep(1.1)
    was = row(mine)
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}",
                  {"kind": "gym", "title": "Legs", "done_bool": 1, "value_int": 8, "value_float": 2.5,
                   "start_date": "2026-10-15 06:00:00", "end_date": "2026-10-15 07:00:00",
                   "created_at_utc": "2026-10-14 06:00:00", "if_modified": was["last_modified_at_utc"]})
    now = row(mine)
    check(ok(st) and (now["kind"], now["title"], now["done_bool"], now["value_int"], now["start_date"],
                      now["end_date"], now["created_at_utc"]) ==
          ("gym", "Legs", 1, 8, "2026-10-15 06:00:00", "2026-10-15 07:00:00", "2026-10-14 06:00:00"),
          f"the steward sets any field with if_modified ({st})")
    check(abs(float(now["value_float"]) - 2.5) < 1e-6 and now["content"] == was["content"], "and the text stays")
    # stale: the captain edited since
    time.sleep(1.1)
    s.req(MAIN, "PUT", f"/entries/{mine}", {"content": now["content"] + " more"})
    held = row(mine)
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"title": "late", "if_modified": now["last_modified_at_utc"]})
    check(st == 412 and row(mine) == held, f"a stale PATCH is a 412, the row untouched ({st})")
    st, _ = s.req(STEWARD, "DELETE", f"/entries/{mine}", {"if_modified": now["last_modified_at_utc"]})
    check(st == 412 and row(mine) == held, f"a stale DELETE is a 412, the row untouched ({st})")
    # replace: the content, guarded
    time.sleep(1.1)
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"content": "Legs, squats.", "if_modified": held["last_modified_at_utc"]})
    now = row(mine)
    check(ok(st) and now["content"] == "Legs, squats." and now["title"] == held["title"], f"a guarded replace ({st})")
    # delete and restore
    st, _ = s.req(STEWARD, "DELETE", f"/entries/{mine}", {"if_modified": now["last_modified_at_utc"]})
    gone = row(mine)
    check(ok(st) and gone["deleted"] == 1 and gone["content"] == now["content"], f"a guarded DELETE, soft ({st})")
    st, _ = s.req(STEWARD, "DELETE", f"/entries/{mine}", {"if_modified": gone["last_modified_at_utc"]})
    check(st == 409 and row(mine) == gone, f"a DELETE of a deleted row is a 409 ({st})")
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"title": "x", "if_modified": gone["last_modified_at_utc"]})
    check(st == 409 and row(mine) == gone, f"a set on a deleted row is a 409 ({st})")
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"content": "x", "if_modified": gone["last_modified_at_utc"]})
    check(st == 409 and row(mine) == gone, f"a replace on a deleted row is a 409 ({st})")
    time.sleep(1.1)
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"deleted": 0, "if_modified": gone["last_modified_at_utc"]})
    back = row(mine)
    check(ok(st) and back["deleted"] == 0 and back["content"] == now["content"], f"a guarded restore ({st})")
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"deleted": 0, "if_modified": back["last_modified_at_utc"]})
    check(st == 409 and row(mine) == back, f"a restore of a live row is a 409 ({st})")
    check(s.req(STEWARD, "PATCH", "/entries/999999", {"title": "x", "if_modified": "2026-01-01 00:00:00"})[0] == 404,
          "a guarded PATCH of a missing row is a 404")
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}", {"kind": "crew_note", "if_modified": back["last_modified_at_utc"]})
    check(st == 403 and row(mine) == back, "never moved into a crew kind")
    # the main login keeps its unguarded writes, and may guard them too
    st, _ = s.req(MAIN, "PATCH", f"/entries/{mine}", {"title": "Gym day", "if_modified": "2020-01-01 00:00:00"})
    check(st == 412, f"the main login's guarded PATCH is guarded too ({st})")
    st, _ = s.req(MAIN, "PATCH", f"/entries/{mine}", {"title": "Gym day"})
    check(ok(st) and row(mine)["title"] == "Gym day", "and unguarded as ever")


def bodies(s):
    """Request bodies are JSON (lcars_json.h's scanner, 0.177.1): a title's
    escapes arrive decoded, and a key is a member of the top-level object,
    never a run of text inside a string or a nested object."""
    print("\nbodies")
    title = "Line one\nline two \u00e9t\u00e9 \"q\" \\ \U0001F596"
    # json.dumps writes the newline as \n and every non-ASCII character as
    # a \u escape (the emoji as a surrogate pair): what Python clients send
    st, row = s.req(MAIN, "POST", "/entries", {"kind": "journal", "title": title,
                                              "content": 'say "kind": "crew_x" here'})
    check(st in (200, 201), f"POST with escapes in the title ({st})")
    got = s.req(MAIN, "GET", f"/entries/{row.get('id')}")[1] if st in (200, 201) else {}
    check(got.get("title") == title, f"the title is stored decoded: {got.get('title')!r}")
    check(got.get("kind") == "journal" and got.get("content") == 'say "kind": "crew_x" here',
          "a \"kind\" inside the content is not the kind")
    raw = '{"title": "caf\\u00e9\\tbar", "done_bool": "1", "value_float": 2.5}'
    st, _ = s.req(MAIN, "PUT", f"/entries/{row.get('id')}", raw)
    got = s.req(MAIN, "GET", f"/entries/{row.get('id')}")[1]
    check(st == 200 and got.get("title") == "caf\u00e9\tbar" and got.get("done_bool") == 1
          and got.get("value_float") == 2.5, f"PUT decodes \\u00e9 and \\t, takes \"1\" for 1 ({got.get('title')!r})")
    st, row = s.req(MAIN, "POST", "/entries",
                    '{"meta": {"kind": "crew_report"}, "kind": "journal", "title": "n"}')
    got = s.req(MAIN, "GET", f"/entries/{row.get('id')}")[1] if st in (200, 201) else {}
    check(got.get("kind") == "journal", "a nested object's kind is not the entry's")
    st, _ = s.req(CREW, "POST", "/entries",
                  '{"meta": {"kind": "crew_report"}, "kind": "journal", "title": "n"}')
    check(st == 403, f"nor the crew login's: a nested crew_ kind does not let a journal row in ({st})")
    # an answer bigger than the connection's 1MB arena is a 500 that says so,
    # never a cut-off document (JSONBuf's overflow, lcars_json.h)
    quotes = '"' * 200000  # 400KB once escaped
    # (titled apart: three identical keyless bodies in 2s are one entry)
    ids = [s.req(MAIN, "POST", "/entries", {"kind": "bulky", "title": f"q{i}", "content": quotes})[1].get("id")
           for i in range(3)]
    st, ans = s.req(MAIN, "GET", "/entries?kind=bulky&content=1")
    check(st == 500 and "too large" in str(ans), f"an answer over the arena is a 500 ({st})")
    st, one = s.req(MAIN, "GET", f"/entries/{ids[0]}")
    check(st == 200 and one.get("content") == quotes, "one of them alone comes back whole")
    for i in ids:
        s.req(MAIN, "DELETE", f"/entries/{i}")


def patches(s, binary_dir):
    """The patch kinds: written by the pages only (PatchKindAllowed)."""
    print("\npatch kinds")
    for kind in ("deck_patch", "ui_patch"):
        st, _ = s.req(MAIN, "POST", "/entries", {"kind": kind, "title": "p", "content": "{}"})
        check(st == 403, f"the main login without X-LCARS-Client creates no {kind} ({st})")
        st, r = s.req(MAIN, "POST", "/entries", {"kind": kind, "title": "p", "content": "{}"}, page=True)
        check(ok(st), f"the page creates a {kind} ({st})")
    st, row = s.req(MAIN, "POST", "/entries", {"kind": "deck_patch", "title": "q", "content": "{\"on\":true}"}, page=True)
    pid = row["id"]
    before = s.req(MAIN, "GET", f"/entries/{pid}")[1]
    stamp = before.get("last_modified_at_utc") or before.get("last_modified_at") or ""
    for method, path, body in (("PUT", f"/entries/{pid}", {"content": "{\"on\":false}"}),
                               ("PATCH", f"/entries/{pid}", {"content": "x", "if_modified": stamp}),
                               ("PATCH", f"/entries/{pid}", {"kind": "journal"}),
                               ("POST", f"/entries/{pid}/append", {"content": "x"}),
                               ("POST", f"/entries/{pid}/title", {"title": "x"}),
                               ("POST", f"/entries/{pid}/end", {})):
        st, _ = s.req(MAIN, method, path, body)
        check(st == 403, f"{method} {path[len('/entries/'):] or path} on a deck_patch without the header: 403 ({st})")
    after = s.req(MAIN, "GET", f"/entries/{pid}")[1]
    check(after == before, "the row is byte for byte as it was")
    jid = s.make("journal")
    st, _ = s.req(MAIN, "PUT", f"/entries/{jid}", {"kind": "deck_patch"})
    check(st == 403 and s.kind_of(jid) == "journal", f"nor is a row moved to deck_patch ({st})")
    st, _ = s.req(MAIN, "PATCH", f"/entries/{jid}", {"title": "fine"})
    check(ok(st), f"a journal row is written without the header as ever ({st})")
    st, _ = s.req(MAIN, "PATCH", f"/entries/{pid}", {"content": "{\"on\":false}", "if_modified": stamp}, page=True)
    check(ok(st) and s.req(MAIN, "GET", f"/entries/{pid}")[1].get("content") == "{\"on\":false}",
          f"the page's guarded PATCH writes it ({st})")
    st, _ = s.req(MAIN, "DELETE", f"/entries/{pid}")
    check(ok(st), f"a DELETE is let through: soft, and only takes a patch away ({st})")
    st, _ = s.req(MAIN, "PATCH", f"/entries/{pid}", {"deleted": 0})
    check(st == 403, f"a restore is a change: refused without the header ({st})")
    st, _ = s.req(MAIN, "PATCH", f"/entries/{pid}", {"deleted": 0}, page=True)
    check(ok(st), f"and the page's goes ({st})")
    st, _ = s.req(NO1, "POST", "/entries", {"kind": "deck_patch", "title": "p"}, page=True)
    check(st == 403, f"Number One writes none even with the header (its own kinds only) ({st})")
    st, _ = s.req(STEWARD, "POST", "/entries", {"kind": "deck_patch", "title": "p"})
    check(st == 403, f"nor the steward ({st})")
    # lcars-cli, the agents' only tool: no X-LCARS-Client, so no patch
    cli = binary_dir / "lcars-cli"
    build_cli(cli)
    env = dict(os.environ, LCARS_URL=f"http://127.0.0.1:{s.port}", LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1])
    def run(*a):
        return subprocess.run([str(cli), *a], env=env, capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL)
    r = run("new", "--kind", "deck_patch", "--title", "from a chat", "--content", "{}")
    check(r.returncode != 0 and ("403" in r.stdout + r.stderr or "pages only" in r.stdout + r.stderr),
          f"lcars-cli new --kind deck_patch is refused: {(r.stdout + r.stderr).strip()[:120]!r}")
    r = run("set", str(pid), "--content", "{}")
    check(r.returncode != 0 and s.req(MAIN, "GET", f"/entries/{pid}")[1].get("content") == "{\"on\":false}",
          f"lcars-cli set on a patch is refused: {(r.stdout + r.stderr).strip()[:120]!r}")
    r = run("new", "--kind", "journal", "--title", "from the cli", "--content", "words")
    check(r.returncode == 0, f"lcars-cli's other writes go ({r.returncode}: {(r.stdout + r.stderr).strip()[:80]!r})")


def kinds_entry(s):
    """The kinds mapping (lcars_kinds.h): every login reads it, only the
    owner's writes it - neither through PUT /kinds/roles nor as the
    `settings` entry titled `kinds` it is kept in."""
    print("\nthe kinds mapping")
    st, ans = s.req(MAIN, "PUT", "/kinds/roles", {"child_sleep": {"kind": "naps", "name": "Ada"}})
    check(st == 200 and ans.get("entry"), f"the owner sets a role ({st})")
    entry = ans["entry"]
    was = s.req(MAIN, "GET", f"/entries/{entry}")[1]
    mine = s.make("journal")
    for who, login in (("crew", CREW), ("Number One", NO1), ("the steward", STEWARD)):
        st, ans = s.req(login, "GET", "/kinds/roles")
        got = {r["role"]: r for r in ans.get("roles", [])} if isinstance(ans, dict) else {}
        check(st == 200 and got.get("child_sleep", {}).get("kind") == "naps", f"{who} reads /kinds/roles")
        st, _ = s.req(login, "PUT", "/kinds/roles", {"child_sleep": {"kind": "elsewhere"}})
        check(st == 403, f"{who}: PUT /kinds/roles refused ({st})")
        st, _ = s.req(login, "POST", "/entries", {"kind": "settings", "title": "kinds", "content": "{}"})
        check(st == 403, f"{who}: a new settings entry refused ({st})")
        st, _ = s.req(login, "PATCH", f"/entries/{entry}",
                      {"content": "{}", "if_modified": was["last_modified_at_utc"]})
        check(st == 403, f"{who}: PATCH the kinds entry refused ({st})")
        st, _ = s.req(login, "POST", f"/entries/{entry}/append",
                      {"text": "x", "if_modified": was["last_modified_at_utc"]})
        check(st == 403, f"{who}: append to the kinds entry refused ({st})")
    # the steward's own doors into a settings entry: a retitle, a move
    now = s.req(MAIN, "GET", f"/entries/{mine}")[1]
    st, _ = s.req(STEWARD, "PATCH", f"/entries/{mine}",
                  {"kind": "settings", "if_modified": now["last_modified_at_utc"]})
    check(st == 403 and s.kind_of(mine) == "journal", f"the steward: a row moved into settings refused ({st})")
    st, _ = s.req(MAIN, "POST", "/entries", {"kind": "settings", "title": "views", "content": "{}"})
    views = st in (200, 201) and _["id"]
    vrow = s.req(MAIN, "GET", f"/entries/{views}")[1]
    st, _ = s.req(STEWARD, "POST", f"/entries/{views}/title",
                  {"title": "kinds", "if_modified": vrow["last_modified_at_utc"]})
    check(st == 403, f"the steward: a settings entry retitled kinds refused ({st})")
    check(s.req(MAIN, "GET", f"/entries/{entry}")[1].get("content") == was["content"],
          "the kinds entry is untouched")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-logins-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    both = {"LCARS_NO1_USER": NO1[0], "LCARS_NO1_PASS": NO1[1],
            "LCARS_CREW_USER": CREW[0], "LCARS_CREW_PASS": CREW[1],
            "LCARS_STEWARD_USER": STEWARD[0], "LCARS_STEWARD_PASS": STEWARD[1]}
    s = Server(binary, tmp / "both", both)
    try:
        check(s.req(MAIN, "POST", "/entries", {"kind": "journal", "title": "x"})[0] in (200, 201),
              "the main login writes anything")
        # past the gate, the handler: no DEEPGRAM_API_KEY here, so no token
        check(s.req(MAIN, "GET", "/say/token")[0] == 503,
              "the main login reaches /say/token (503: no key)")
        bodies(s)
        run_login(s, "crew", CREW, "crew", "no1")
        run_login(s, "Number One", NO1, "no1", "crew")
        run_steward(s)
        kinds_entry(s)
        patches(s, tmp)
        check(s.req(("crew", "wrong-password-0123456"), "GET", "/entries")[0] == 401,
              "a wrong crew password is a 401")
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()

    print("\nlogins off")
    s = Server(binary, tmp / "none", {"LCARS_NO1_USER": NO1[0], "LCARS_NO1_PASS": NO1[1]})
    try:
        check(s.req(CREW, "GET", "/entries")[0] == 401, "crew variables unset: no crew login")
        check(s.req(NO1, "GET", "/entries")[0] == 200, "Number One's still works")
        check(s.req(STEWARD, "GET", "/entries")[0] == 401, "steward variables unset: no steward login")
    finally:
        s.stop()
    s = Server(binary, tmp / "short", {"LCARS_CREW_USER": CREW[0], "LCARS_CREW_PASS": "short"})
    try:
        check(s.req((CREW[0], "short"), "GET", "/entries")[0] == 401,
              "a crew password under 16 characters: no crew login")
    finally:
        s.stop()
    s = Server(binary, tmp / "clash", dict(both, LCARS_CREW_USER=NO1[0]))
    try:
        check(s.req((NO1[0], CREW[1]), "GET", "/entries")[0] == 401,
              "crew user named like Number One's: no crew login")
        st, _ = s.req(NO1, "POST", "/entries", {"kind": "crew_report"})
        check(st == 403, "and Number One stays Number One")
    finally:
        s.stop()

    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server logs under {tmp}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
