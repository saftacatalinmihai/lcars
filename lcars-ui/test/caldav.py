#!/usr/bin/env python3
"""CalDAV, end to end: what Apple Reminders (or any client) can do to the lists.

lcars_caldav.h turns entry kinds into Reminders lists and a reminder's due
date into the entry's schedule. None of that has a test anywhere else - the
QuickJS suite fakes /entries/<id>/caldav - so this drives the real server
the way a client does, with raw WebDAV:

  1. a scratch build of the server (`make -n lcars-release`, compiled to a
     temp path - never `make` itself, which on the VPS would overwrite the
     live binary), on an empty database in a temp directory;
  2. discovery: the home lists the task kind and every task_* kind;
  3. lists: MKCALENDAR, PROPPATCH (name, colour, a refused property),
     DELETE (hidden, entries kept) and a MKCALENDAR that brings it back;
  4. tasks: PUT with Reminders' own shapes (TZID, DATE, absolute alarms),
     GET, DELETE, a move by PUT under the same UID and by MOVE;
  5. the schedule: DUE -> start_date/end_date, a reschedule in the journal
     -> DTSTART/DUE and the alarm moved, all-day both ways, a zone past the
     end of its transition table;
  6. sync-collection: tokens, what changed, what left, a bad token;
     calendar-query's open-tasks filter.

    python3 test/caldav.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/caldav.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.request

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
USER, PASS = "t", "t"
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

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


def build(out):
    """The release compile line, pointed at `out` instead of ./lcars."""
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-release"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and " -o lcars lcars.c" in l), None)
    if not line:
        sys.exit("caldav: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("caldav: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS, LCARS_CALDAV_LOG="0")
        env.pop("LCARS_TZ", None)
        env.pop("LCARS_TASK_KIND", None)
        self.log = open(tmp / "server.log", "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("caldav: the scratch server did not come up; see " + str(tmp / "server.log"))

    def req(self, method, path, body=None, headers=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": AUTH}
        if ctype:
            h["Content-Type"] = ctype
        h.update(headers or {})
        data = body.encode() if isinstance(body, str) else body
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read().decode()
        c.close()
        return out

    def json(self, method, path, obj=None):
        st, _, body = self.req(method, path, json.dumps(obj) if obj is not None else None,
                               ctype="application/json")
        return st, (json.loads(body) if body.strip().startswith(("{", "[")) else body)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


HOME = "/caldav/calendars/"
PROPFIND = """<?xml version="1.0" encoding="UTF-8"?>
<A:propfind xmlns:A="DAV:"><A:prop><A:displayname/><A:sync-token/>
<B:getctag xmlns:B="http://calendarserver.org/ns/"/></A:prop></A:propfind>"""


def vtodo(uid, summary, lines="", vcal=""):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Apple Inc.//iPhone OS 26.0//EN\r\n"
            + vcal +
            f"BEGIN:VTODO\r\nUID:{uid}\r\nDTSTAMP:20261007T090000Z\r\nCREATED:20261007T090000Z\r\n"
            f"SUMMARY:{summary}\r\n{lines}END:VTODO\r\nEND:VCALENDAR\r\n")


def responses(xml):
    """(href, status-or-200, body) for each <D:response>."""
    out = []
    for r in re.findall(r"<D:response>(.*?)</D:response>", xml, re.S):
        h = re.search(r"<D:href>([^<]*)</D:href>", r).group(1)
        st = re.search(r"HTTP/1.1 (\d+)", r)
        out.append((h, int(st.group(1)) if st else 0, r))
    return out


def lists(s):
    st, _, body = s.req("PROPFIND", HOME, PROPFIND, {"Depth": "1"}, "application/xml")
    found = {}
    for h, _, r in responses(body):
        name = re.search(r"<D:displayname>([^<]*)</D:displayname>", r)
        if h != HOME and name:
            found[h] = name.group(1)
    return st, found


def token_of(s, coll):
    _, _, body = s.req("PROPFIND", coll, PROPFIND, {"Depth": "0"}, "application/xml")
    m = re.search(r"<D:sync-token>([^<]*)</D:sync-token>", body)
    return m.group(1) if m else ""


def sync(s, coll, token):
    body = ('<?xml version="1.0" encoding="utf-8"?><D:sync-collection xmlns:D="DAV:">'
            f'<D:sync-token>{token}</D:sync-token><D:sync-level>1</D:sync-level>'
            '<D:prop><D:getetag/></D:prop></D:sync-collection>')
    st, _, xml = s.req("REPORT", coll, body, {"Depth": "1"}, "application/xml")
    m = re.search(r"<D:sync-token>([^<]*)</D:sync-token>\s*</D:multistatus>", xml)
    return st, responses(xml), (m.group(1) if m else "")


def entry(s, id_):
    return s.json("GET", f"/entries/{id_}")[1]


def find_id(s, title):
    st, rows = s.json("GET", "/entries?deleted=all&limit=1000")
    return next((r["id"] for r in rows if r.get("title") == title), 0)


def run(s):
    print("discovery")
    st, _, body = s.req("PROPFIND", "/.well-known/caldav", PROPFIND, {"Depth": "0"},
                        "application/xml")
    check(st == 207 and "calendar-home-set" in body, "/.well-known/caldav names the home")
    s.json("POST", "/entries", {"kind": "task_personal", "title": "Water the plants"})
    s.json("POST", "/entries", {"kind": "taskforce", "title": "not a list"})
    st, found = lists(s)
    check(st == 207 and found.get(HOME + "tasks/") == "LCARS Tasks",
          "the task kind is the list at /tasks/ even with no tasks")
    check(found.get(HOME + "task_personal/") == "Personal", "task_personal is a list named Personal")
    check(not any("taskforce" in h for h in found), "a kind that merely starts with 'task' is not")
    st, _, body = s.req("OPTIONS", HOME)
    check("MKCALENDAR" in body or "MKCALENDAR" in str(_), "OPTIONS advertises MKCALENDAR")

    print("lists: MKCALENDAR, PROPPATCH, DELETE")
    mk = """<?xml version="1.0" encoding="UTF-8"?>
<B:mkcalendar xmlns:B="urn:ietf:params:xml:ns:caldav"><A:set xmlns:A="DAV:"><A:prop>
<B:supported-calendar-component-set><B:comp name="VTODO"/></B:supported-calendar-component-set>
<A:displayname>Groceries</A:displayname>
<D:calendar-color xmlns:D="http://apple.com/ns/ical/">#34C759FF</D:calendar-color>
</A:prop></A:set></B:mkcalendar>"""
    g = HOME + "9F1D0C1E-1111-4C5B-9E0D-ABCDEF012345/"
    st, _, _ = s.req("MKCALENDAR", g, mk, ctype="application/xml")
    check(st == 201, f"MKCALENDAR creates a list (got {st})")
    st, _, _ = s.req("MKCALENDAR", g, mk, ctype="application/xml")
    check(st == 405, f"a second MKCALENDAR at the same URL is refused (got {st})")
    st, found = lists(s)
    check(found.get(g) == "Groceries", "the new list is at the client's URL, under its name")
    ev = mk.replace('name="VTODO"', 'name="VEVENT"')
    st, _, _ = s.req("MKCALENDAR", HOME + "events/", ev, ctype="application/xml")
    check(st == 403, "a calendar of events is refused")

    pp = """<?xml version="1.0" encoding="UTF-8"?>
<A:propertyupdate xmlns:A="DAV:"><A:set><A:prop>
<A:displayname>Market &amp; Groceries</A:displayname>
<B:calendar-color xmlns:B="http://apple.com/ns/ical/">#FF2D55FF</B:calendar-color>
<C:default-alarm-vevent-date xmlns:C="urn:ietf:params:xml:ns:caldav">x</C:default-alarm-vevent-date>
</A:prop></A:set></A:propertyupdate>"""
    st, _, body = s.req("PROPPATCH", g, pp, ctype="application/xml")
    check(st == 207 and "200 OK" in body and "403 Forbidden" in body,
          "PROPPATCH stores the name and colour, refuses the rest per property")
    check('X:default-alarm-vevent-date xmlns:X="urn:ietf:params:xml:ns:caldav"' in body,
          "the refused property is echoed in its own namespace")
    _, _, body = s.req("PROPFIND", g, PROPFIND, {"Depth": "0"}, "application/xml")
    check("<D:displayname>Market &amp; Groceries</D:displayname>" in body and "#FF2D55FF" in body,
          "the rename and the colour stick")

    print("tasks and the schedule")
    madrid = ("DTSTART;TZID=Europe/Madrid:20261010T150000\r\nDUE;TZID=Europe/Madrid:20261010T150000\r\n"
              "PRIORITY:9\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\n"
              "TRIGGER;VALUE=DATE-TIME:20261010T130000Z\r\nUID:A1\r\nX-WR-ALARMUID:A1\r\nEND:VALARM\r\n"
              "X-APPLE-SORT-ORDER:12\r\n")
    milk = g + "AAAA-milk.ics"
    st, hd, _ = s.req("PUT", milk, vtodo("UID-MILK", "Milk", madrid), {"If-None-Match": "*"},
                      "text/calendar")
    check(st == 201, f"PUT creates a task (got {st})")
    check("etag" not in hd, "and answers no ETag, because the stored object is rewritten")
    mid = find_id(s, "Milk")
    e = entry(s, mid)
    check(e.get("kind") == "task_groceries", f"its kind is the list's: {e.get('kind')}")
    check(e.get("start_date") == "2026-10-10 13:00:00" and e.get("end_date") == "2026-10-10 13:00:00",
          f"DUE 15:00 Madrid is 13:00 UTC in both columns: {e.get('start_date')} / {e.get('end_date')}")
    st, hd, ics = s.req("GET", milk)
    check(st == 200 and "DUE;TZID=Europe/Madrid:20261010T150000" in ics,
          "GET gives the DUE back as it was written")
    check(ics.index("X-APPLE-SORT-ORDER") < ics.index("BEGIN:VALARM"),
          "properties come before the VALARM, as RFC 5545's grammar has it")
    etag = hd.get("etag", "")
    st, _, _ = s.req("PUT", milk, vtodo("UID-MILK", "Milk!", madrid), {"If-Match": '"0-0"'},
                     "text/calendar")
    check(st == 412, "a PUT with a stale If-Match is refused")
    st, _, _ = s.req("PUT", milk, vtodo("UID-MILK", "Milk", madrid), {"If-Match": etag},
                     "text/calendar")
    check(st == 204, "a PUT with the current If-Match goes through")

    tok = token_of(s, g)
    check(tok.startswith("http://"), "the list has a sync-token, a URI")
    st, rs, tok2 = sync(s, g, tok)
    check(st == 207 and rs == [] and tok2 == tok, "a sync with the current token reports nothing")

    s.json("PUT", f"/entries/{mid}", {"start_date": "2026-10-11 09:00:00",
                                      "end_date": "2026-10-11 09:00:00"})
    _, _, ics = s.req("GET", milk)
    check("DTSTART:20261011T090000Z" in ics and "DUE:20261011T090000Z" in ics,
          "a reschedule in the journal rewrites DTSTART/DUE")
    check("TZID=Europe/Madrid:20261010" not in ics, "and drops the stale ones")
    check("TRIGGER;VALUE=DATE-TIME:20261011T090000Z" in ics,
          "and moves the absolute alarm by as much")
    st, rs, tok3 = sync(s, g, tok)
    check(st == 207 and [h for h, _, _ in rs] == [milk] and rs[0][1] == 200 and tok3 != tok,
          "sync-collection reports the rescheduled task, with a new token")
    _, view = s.json("GET", f"/entries/{mid}/caldav")
    check(view.get("synced") is True and view.get("list") == "Market & Groceries",
          "the JSON view knows the list")
    check("DUE:20261011T090000Z" in view.get("extra_ical", ""),
          "and hands the page the rewritten lines, not the stale ones")
    # The page edits those lines and PUTs them back: the schedule follows.
    lines = view["extra_ical"].replace("DUE:20261011T090000Z", "DUE:20261011T100000Z")
    st, _ = s.json("PUT", f"/entries/{mid}/caldav", {"extra_ical": lines, "etag": view["etag"]})
    e = entry(s, mid)
    check(st == 200 and e.get("start_date") == "2026-10-11 09:00:00"
          and e.get("end_date") == "2026-10-11 10:00:00",
          f"a DUE edited in the panel moves end_date: {e.get('start_date')} / {e.get('end_date')}")

    # A client that edits only the title must not undo the reschedule.
    st, _, _ = s.req("PUT", milk, vtodo("UID-MILK", "Oat milk", view["extra_ical"]),
                     ctype="text/calendar")
    e = entry(s, mid)
    check(e.get("title") == "Oat milk" and e.get("start_date") == "2026-10-11 09:00:00",
          "a client PUT with unchanged dates leaves the schedule alone")

    _, _, ics = s.req("GET", milk)
    check("URL" not in ics, "no link back to the journal for a client on a plain host")
    _, _, ics = s.req("GET", milk, headers={"Host": "box.tail1234.ts.net"})
    check(f"URL;VALUE=URI:https://box.tail1234.ts.net/ui/#e={mid}" in ics,
          "through tailscale serve, a task links back to its entry in the web UI")
    _, _, ics = s.req("GET", milk, headers={"Host": "evil\".ts.net"})
    check("URL" not in ics, "a Host that is not a plain name gets no link")

    print("all day")
    bread = g + "BBBB-bread.ics"
    s.req("PUT", bread, vtodo("UID-BREAD", "Bread",
                              "DTSTART;VALUE=DATE:20261012\r\nDUE;VALUE=DATE:20261012\r\n"),
          ctype="text/calendar")
    bid = find_id(s, "Bread")
    e = entry(s, bid)
    check(e.get("start_date") == "2026-10-11 22:00:00" and e.get("end_date") == "2026-10-12 22:00:00",
          f"an all-day DUE is the day, midnight to midnight in the learnt zone (Madrid): "
          f"{e.get('start_date')} / {e.get('end_date')}")
    s.json("PUT", f"/entries/{bid}", {"start_date": "2026-10-12 22:00:00",
                                      "end_date": "2026-10-13 22:00:00"})
    _, _, ics = s.req("GET", bread)
    check("DUE;VALUE=DATE:20261013" in ics and "BEGIN:VALARM" not in ics,
          "moved a whole day in the journal, it is still an all-day DATE, with no alarm added")

    print("zones")
    ny = g + "CCCC-ny.ics"
    s.req("PUT", ny, vtodo("UID-NY", "Far future",
                           "DUE;TZID=America/New_York:20400701T120000\r\n"), ctype="text/calendar")
    e = entry(s, find_id(s, "Far future"))
    check(e.get("start_date") == "2040-07-01 16:00:00",
          f"2040 in New York is EDT, past the transition table: {e.get('start_date')}")
    s.req("PUT", ny, vtodo("UID-NY", "Far future", "DUE;TZID=../../etc/passwd:20400701T120000\r\n"),
          ctype="text/calendar")
    check(s.proc.poll() is None, "a TZID naming a path is read as UTC, not opened")

    print("a task scheduled in the journal")
    st, made = s.json("POST", "/entries", {"kind": "task", "title": "Call the bank",
                                           "start_date": "2026-10-14 08:30:00",
                                           "end_date": "2026-10-14 08:30:00"})
    cid = made.get("id") if isinstance(made, dict) else find_id(s, "Call the bank")
    _, _, ics = s.req("GET", HOME + f"tasks/lcars-{cid}.ics")
    check("DUE:20261014T083000Z" in ics and "TRIGGER;VALUE=DATE-TIME:20261014T083000Z" in ics,
          "goes out with its DUE and an alert at it")

    print("moves")
    tok_g = token_of(s, g)
    tok_t = token_of(s, HOME + "tasks/")
    # Reminders moves a task by writing it into the new list, then deleting
    # it from the old one.
    st, _, _ = s.req("PUT", HOME + "tasks/DDDD-moved.ics", vtodo("UID-BREAD", "Bread"),
                     ctype="text/calendar")
    check(st == 201 and entry(s, bid).get("kind") == "task",
          "a PUT of the same UID into another list moves the entry, not a copy")
    check(find_id(s, "Bread") == bid, "the entry keeps its id")
    st, _, _ = s.req("DELETE", bread)
    check(st == 404 and not entry(s, bid).get("deleted"), "the old list's DELETE then finds nothing to delete")
    _, rs, _ = sync(s, g, tok_g)
    check((bread, 404) in [(h, st) for h, st, _ in rs], "the old list's sync reports it gone")
    _, rs, _ = sync(s, HOME + "tasks/", tok_t)
    check(HOME + "tasks/DDDD-moved.ics" in [h for h, _, _ in rs], "the new list's sync reports it arrived")
    # A kind change in the journal is a move too.
    tok_t = token_of(s, HOME + "tasks/")
    s.json("PUT", f"/entries/{cid}", {"kind": "task_personal"})
    _, rs, _ = sync(s, HOME + "tasks/", tok_t)
    check((HOME + f"tasks/lcars-{cid}.ics", 404) in [(h, st) for h, st, _ in rs],
          "a kind changed in the journal is reported gone from the old list")
    st, _, _ = s.req("MOVE", HOME + f"task_personal/lcars-{cid}.ics",
                     headers={"Destination": f"http://x{g}EEEE-moved.ics"})
    check(st == 201 and entry(s, cid).get("kind") == "task_groceries", "MOVE re-kinds the task")
    st, _, _ = s.req("GET", g + "EEEE-moved.ics")
    check(st == 200, "and it answers at its new name")

    print("deletes, queries, tokens")
    st, _, _ = s.req("DELETE", milk)
    check(st == 204 and entry(s, mid).get("deleted") == 1, "DELETE of a task is a soft delete")
    s.req("PUT", g + "FFFF-done.ics", vtodo("UID-DONE", "Done thing", "STATUS:COMPLETED\r\n"),
          ctype="text/calendar")
    q = """<?xml version="1.0" encoding="UTF-8"?>
<B:calendar-query xmlns:B="urn:ietf:params:xml:ns:caldav"><A:prop xmlns:A="DAV:"><A:getetag/></A:prop>
<B:filter><B:comp-filter name="VCALENDAR"><B:comp-filter name="VTODO">
<B:prop-filter name="COMPLETED"><B:is-not-defined/></B:prop-filter>
</B:comp-filter></B:comp-filter></B:filter></B:calendar-query>"""
    _, _, body = s.req("REPORT", g, q, {"Depth": "1"}, "application/xml")
    check("FFFF-done" not in body and "EEEE-moved" in body,
          "calendar-query with COMPLETED is-not-defined leaves out the done tasks")
    _, _, body = s.req("REPORT", g, q.replace("<B:is-not-defined/>", ""), {"Depth": "1"},
                       "application/xml")
    check("FFFF-done" in body, "and without that filter they are there")
    st, _, body = s.req("REPORT", g, sync_body := (
        '<D:sync-collection xmlns:D="DAV:"><D:sync-token>bogus</D:sync-token>'
        '<D:prop><D:getetag/></D:prop></D:sync-collection>'), {"Depth": "1"}, "application/xml")
    check(st == 403 and "valid-sync-token" in body, "a token that is not ours is a valid-sync-token error")
    st, rs, _ = sync(s, g, "")
    check(st == 207 and all(c == 200 for _, c, _ in rs) and len(rs) >= 3,
          "an empty token is an initial sync of every live task")
    mg = ('<?xml version="1.0"?><C:calendar-multiget xmlns:D="DAV:" '
          'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop>'
          f'<D:href>{g}EEEE-moved.ics</D:href><D:href>{HOME}tasks/nope.ics</D:href></C:calendar-multiget>')
    _, _, body = s.req("REPORT", g, mg, {"Depth": "1"}, "application/xml")
    check("BEGIN:VTODO" in body and "404 Not Found" in body, "multiget answers data and a 404")

    print("deleting and reviving a list")
    st, _, _ = s.req("DELETE", g)
    check(st == 204, "DELETE of a list")
    _, found = lists(s)
    check(g not in found, "hides it")
    check(entry(s, cid).get("deleted") == 0 and entry(s, cid).get("kind") == "task_groceries",
          "and every entry in it stays as it was")
    st, _, _ = s.req("GET", g + "EEEE-moved.ics")
    check(st == 404, "its tasks are no longer published")
    g2 = HOME + "NEW-UUID/"
    st, _, _ = s.req("MKCALENDAR", g2, mk,
                     ctype="application/xml")
    _, found = lists(s)
    check(st == 201 and found.get(g2) == "Groceries", "a new list of the same name brings it back")
    st, _, _ = s.req("GET", g2 + "EEEE-moved.ics")
    check(st == 200, "with its tasks")
    st, _, _ = s.req("MKCALENDAR", HOME + "OTHER/", mk,
                     ctype="application/xml")
    _, found = lists(s)
    check(st == 201 and HOME + "OTHER/" in found, "a second list of that name gets a kind of its own")
    _, kinds = s.json("GET", "/kinds")
    names = [k["kind"] for k in kinds] if isinstance(kinds, list) else []
    check("task_groceries" in names, "the list's kind is in /kinds")

    print("a Secret task (lcars_vault.h) leaves the lists as a deleted one does")
    tasks = HOME + "tasks/"
    st, row = s.json("POST", "/entries", {"kind": "task", "title": "Secret errand"})
    sid = row["id"]
    href = f"{tasks}lcars-{sid}.ics"
    check(s.req("GET", href)[0] == 200, "the task is published")
    before = token_of(s, tasks)
    tok = "ab" * 32
    # a vault keeps exactly one password wrap (lcars_vault.h, 0.287.0)
    wrap = {"type": "password", "kdf": "PBKDF2-SHA256", "iter": 600000,
            "salt": "c2FsdA", "iv": "aXY", "wrapped": "d3JhcHBlZA"}
    st, _ = s.json("PUT", "/vault", {"vault": {"v": 1, "wraps": [wrap]}, "token": tok, "version": 0})
    check(st == 200, f"the vault is set ({st})")
    st, _, _ = s.req("PATCH", f"/entries/{sid}", json.dumps({"classification": 2, "sealed": "lcs1.aGk.aGk"}),
                     {"X-LCARS-Vault": tok}, "application/json")
    check(st == 200, f"raised to Secret ({st})")
    check(s.req("GET", href)[0] == 404, "its object is gone")
    st, resp, _ = sync(s, tasks, before)
    gone = [r for r in resp if r[0] == href]
    check(st == 207 and gone and gone[0][1] == 404, f"a sync from before names it removed ({gone})")
    _, _, body = s.req("PROPFIND", tasks, PROPFIND, {"Depth": "1"}, "application/xml")
    check(href not in body and "Secret errand" not in body, "the collection lists it no longer")
    st, _, _ = s.req("PUT", href, vtodo(f"lcars-{sid}@lcars", "Secret errand, edited"), {}, "text/calendar")
    got = entry(s, sid)
    check(got.get("title") == "" and got.get("classification") == 2,
          f"a stale client's PUT writes no title into it ({st})")
    check(s.proc.poll() is None, "the server is still up")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-caldav-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    try:
        run(s)
    finally:
        s.stop()
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server log: {tmp / 'server.log'}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
