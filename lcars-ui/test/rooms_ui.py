#!/usr/bin/env python3
"""The Rooms page (docs/design/rooms.md, section 6; openRooms in index.html)
in headless Chromium at an iPhone's 393x852, against a scratch server with
the engineer routes on and engineer.py stood in for: the stand-in writes
each say's crew_msg row and each room's crew_room row through the API, as
the real one does with the seat's login, so the page reads what it sent
back from the journal.

  1. the door: the Chats list's Rooms row opens ./rooms; project rooms
     first, then Number One's and each engineer's;
  2. a send: the bubble at once ("sending…"), then its row in the journal
     (captain → no1 #deck, the header the page's) and the bubble the row's;
  3. the To chip: an engineer picked, their say with the room; one not in
     the seat: "waiting for the seat", the row done 0 until it is delivered;
  2b. a file (rooms.md 22): + and the picker, the chip uploading at once,
     the bubble with its picture, the say's attachments, and the row's
     "Attached file:" line in the journal and its thumbnail in the log;
  4. a failure: "not sent" on the bubble, Retry, the words back in the box;
  5. New room: the room at once, "opening…", then its row; Close (under
     Closed, the row done) and Reopen;
  6. Back: a room to the list, the list out; Escape the same; the page no
     wider than the phone;
  7. at a desk's 1280x800 (rooms.md 20): the chats' two panes, the list
     kept beside a room with its row marked, a row's tap swapping the
     right pane, the room's ‹ a level up to the chats.

    python3 test/rooms_ui.py               # builds the server first (~30s)
    python3 test/rooms_ui.py --shots DIR   # and keeps the phone screenshots
    LCARS_TEST_BIN=/path/to/lcars python3 test/rooms_ui.py

Nothing here touches the journal or a running server.
"""
import json
import os
import pathlib
import shutil
import sys
import time

import killclean  # its scratch and servers go when the run is killed
import features as F

UI = F.UI
REPO = pathlib.Path(__file__).resolve().parents[2]
KEY = "roomsKEY1234567890abcd"
check, fails, checks = F.check, F.fails, F.checks
SAID, MEDIA = [""], [""]   # the stand-in's log of says with files, the media root


def _png(w=400, h=300):
    """a small amber PNG, made here (a picture the browser decodes)"""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\0" + b"\xff\x99\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()
W, H = 393, 852

# The stand-in engineer.py: say, thread-req and list, the rows written with
# rooms.py (the real title and content) through the scratch server's API.
# A message with FAIL in it is refused (exit 3, a 409); kim-x is not in the
# seat, so a say to him is queued (the row done 0, ticked by the test as
# the seat's delivery would). Each answer waits a little, so the page's
# pending states can be seen.
STAND_IN = r'''
import base64, json, os, sys, time, urllib.request
sys.path.insert(0, %(scripts)r)
import rooms as R
BASE, AUTH = %(base)r, "Basic " + base64.b64encode(%(cred)r.encode()).decode()
def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "null")
def out(o, code=0):
    print(json.dumps(o)); sys.exit(code)
ENGS = [{"name": "number-one", "title": "Number One", "status": "idle", "active": 1},
        {"name": "obrien-x", "title": "Chief O'Brien", "status": "idle", "active": 3},
        {"name": "kim-x", "title": "Ensign Kim", "status": "idle", "active": 2}]
a = sys.argv[1:]
if a[:1] == ["list"]:
    out({"engineers": ENGS, "deploy": {}, "seat": {"holder": "obrien-x", "queue": []}})
if a[:1] == ["say"]:
    name, room = a[1], (a[a.index("--thread") + 1] if "--thread" in a else None)
    text = sys.stdin.read().strip()
    if "--json" in a:
        # engineer.py's cmd_say: the words, then a line per file (attachment_lines)
        body = json.loads(text)
        open(%(said)r, "a").write(json.dumps({"name": name, "room": room, **body}) + "\n")
        text = "\n\n".join(x for x in [body.get("message", "").strip()] + [
            "Attached file: %%s/%%s (%%s, %%s, %%d bytes) - Read that path" %% (%(root)r, f["path"], f["name"], f["mime"], f["bytes"])
            for f in body.get("attachments", [])] if x)
    time.sleep(0.6)
    if "FAIL" in text:
        out({"error": "the engineer is waiting on a question on their screen"}, 3)
    if name == "number-one":
        frm, to, rm = "captain", "no1", room or "main"
    else:
        frm, to, rm = "captain", name, room or name
    queued = name == "kim-x"
    api("POST", "/entries", {"kind": R.MSG_KIND, "title": R.title(frm, to, rm, text), "content": R.content(text, rm, to),
                             "done_bool": 0 if queued else 1})
    out({"ok": True, "queued": True, "seat": {"position": 2, "holder": "obrien-x"}} if queued else {"ok": True})
if a[:1] == ["thread-req"]:
    req = json.loads(sys.stdin.read() or "{}")
    time.sleep(0.8)
    rows = [r for r in api("GET", "/entries?kind=crew_room&order=id&dir=asc&limit=500") if not r.get("deleted")]
    row = next((r for r in rows if R.room_row_id(r) == req.get("id")), None)
    if req["op"] == "new" and row is None:
        api("POST", "/entries", {"kind": R.ROOM_KIND, "title": req.get("name") or req["id"],
                                 "content": "id:: %%s\nby:: captain" %% req["id"]})
    elif req["op"] == "new":
        api("PUT", "/entries/%%d" %% row["id"], {"done_bool": 0, **({"title": req["name"]} if req.get("name") else {})})
    elif req["op"] == "rename":
        api("PUT", "/entries/%%d" %% row["id"], {"title": req["name"]})
    elif req["op"] == "close":
        api("PUT", "/entries/%%d" %% row["id"], {"done_bool": 1})
    out({"ok": True, "threads": []})
out({"ok": True, "status": "idle", "events": [], "next": 0, "first": 0, "session": "s", "past": []})
'''


def api(srv, method, path, body=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Authorization": F.auth(F.USER, F.PASS), "Content-Type": "application/json"})
    r = c.getresponse()
    doc = json.loads(r.read().decode() or "null")
    c.close()
    return r.status, doc


def msgs(srv):
    st, rows = api(srv, "GET", "/entries?kind=crew_msg&order=id&dir=asc&limit=500")
    return rows if st == 200 else []


def rooms(srv):
    st, rows = api(srv, "GET", "/entries?kind=crew_room&order=id&dir=asc&limit=500")
    return rows if st == 200 else []


def seed(srv):
    sys.path.insert(0, str(REPO / "scripts"))
    import rooms as R
    api(srv, "POST", "/entries", {"kind": R.ROOM_KIND, "title": "Deck redesign", "content": "id:: deck\nby:: captain"})
    for frm, to, rm, text, done in (("captain", "no1", "deck", "How are the chairs?", 1),
                                    ("no1", "obrien-x", "deck", "[No.1] Fix the chairs, then report.", 1),
                                    ("obrien-x", "", "deck", "Report: done. The chairs are fixed.\n\n" +
                                     "\n".join(f"- step {i}" for i in range(1, 19)), 1),
                                    ("captain", "no1", "main", "Status?", 1),
                                    ("no1", "", "main", "All quiet, Captain.", 1),
                                    ("captain", "obrien-x", "obrien-x", "One question, Chief.", 1)):
        api(srv, "POST", "/entries", {"kind": R.MSG_KIND, "title": R.title(frm, to, rm, text),
                                      "content": R.content(text, rm, to), "done_bool": done})


def run(b, srv, shots):
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, has_touch=True, is_mobile=True)
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": F.USER, "pass": F.PASS}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.deck.engkey', {json.dumps(json.dumps(KEY))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))

    def shot(name):
        if shots:
            p.screenshot(path=str(shots / f"{name}.png"))

    def wide():
        return p.evaluate("document.documentElement.scrollWidth")

    def url():
        return p.url.replace(cfg["base"], "").split("?")[0]
    try:
        p.goto(cfg["base"] + "/ui/")
        p.wait_for_function("typeof openRooms === 'function' && st.all.some(e => e.kind === 'crew_msg')", timeout=20000)
        # 1. the door
        p.evaluate("chatsUp(); chatsList(); engListFetch(true)")
        p.wait_for_selector("#chrows [data-rooms]", timeout=5000)
        p.tap("#chrows [data-rooms]")
        p.wait_for_selector("#rmlist [data-rm]", timeout=5000)
        check(url() == "/ui/rooms", f"the Chats list's Rooms row opens ./rooms ({url()})")
        p.wait_for_function("document.querySelectorAll('#rmlist [data-rm]').length >= 4", timeout=5000)
        order = p.evaluate("[...document.querySelectorAll('#rmlist [data-rm]')].map(b => b.dataset.rm)")
        check(order[:4] == ["deck", "main", "obrien-x", "kim-x"], f"project rooms first, then Number One's, then each engineer's ({order})")
        check(wide() <= W, f"the list no wider than the phone ({wide()})")
        shot("1-list")
        # 2. a room, a send
        p.tap("#rmlist [data-rm=deck]")
        p.wait_for_selector("#rmlog .rmm", timeout=5000)
        check(url() == "/ui/rooms/deck", f"a room: ./rooms/deck ({url()})")
        check(p.text_content("#rmto") == "To No.1", "the box goes to Number One in a project room")
        check(p.evaluate("[...document.querySelectorAll('#rmlog [data-rmfold]')].length") == 1, "the long report folded, with More")
        shot("2-room")
        n0 = len(msgs(srv))
        p.fill("#rmbox", "Check the table too, please.")
        p.tap("#rmsend")
        check("sending" in (p.text_content("#rmlog .rmm:last-child") or ""), "the bubble at once, sending…")
        shot("3-sending")
        p.wait_for_function("rm.pend.length === 0 && [...document.querySelectorAll('#rmlog .rmm.me')].some(m => m.textContent.includes('Check the table too'))",
                            timeout=10000)
        new = msgs(srv)[n0:]
        check(len(new) == 1 and new[0]["title"].startswith("captain → no1 #deck:") and
              new[0].get("content", "").startswith("room:: deck\nCheck the table too"),
              f"its row: captain → no1 #deck, the header the page's ({[(x['title'], x.get('content', '')[:40]) for x in new]})")
        check(p.evaluate("[...document.querySelectorAll('#rmlog .rmm.me')].filter(m => m.textContent.includes('Check the table too')).length") == 1,
              "one bubble: the row's")
        shot("4-sent")
        # 2b. a file: the picker's chip at once, the bubble's picture, the row's line
        n0 = len(msgs(srv))
        check(p.is_visible("#rmattach"), "the room's box has the chat's + for files")
        p.set_input_files("#rmpick", files=[{"name": "deck shot.png", "mimeType": "image/png", "buffer": PNG}])
        check(p.evaluate("!!document.querySelector('#rmfiles:not([hidden]) .chfchip.img img')"), "the chip at once, its thumbnail")
        p.wait_for_function("(rm.att.get('deck') || []).every(f => f.state === 'done')", timeout=10000)
        p.fill("#rmbox", "The chairs, as built.")
        p.tap("#rmsend")
        check(p.evaluate("!!document.querySelector('#rmlog .rmm:last-child .chimg img') && "
                         "document.querySelector('#rmlog .rmm:last-child').textContent.includes('sending')"),
              "the bubble at once with its picture, sending…")
        check(p.evaluate("document.querySelector('#rmfiles').hidden"), "the chips gone from above the box")
        p.wait_for_function("rm.pend.length === 0 && [...document.querySelectorAll('#rmlog .rmm.me')].some(m => m.textContent.includes('The chairs, as built'))",
                            timeout=10000)
        said = [json.loads(l) for l in open(SAID[0]).read().splitlines()]
        att = said[-1].get("attachments") or []
        check(said[-1]["name"] == "number-one" and said[-1]["room"] == "deck" and len(att) == 1 and att[0]["name"] == "deck shot.png" and
              att[0]["path"].startswith("media/chat/") and att[0]["mime"] == "image/png", f"the say carries the file, to No.1 in deck ({said[-1]})")
        new = msgs(srv)[n0:]
        line = f"Attached file: {MEDIA[0]}/{att[0]['path'] if att else ''} (deck shot.png, image/png,"
        check(len(new) == 1 and line in new[0].get("content", ""), f"its crew_msg row has the file's line ({[x.get('content') for x in new]})")
        bub = "[...document.querySelectorAll('#rmlog .rmm.me')].find(m => m.textContent.includes('The chairs, as built'))"
        check(p.evaluate(f"(() => {{ const b = {bub}; const i = b && b.querySelector('.chimg img'); "
                         f"return !!i && i.getAttribute('src').includes({json.dumps(att[0]['path'] if att else 'x')}) && !b.textContent.includes('Attached file'); }})()"),
              "the row's bubble: the picture from the journal's line, the line itself not shown")
        p.wait_for_function(f"(() => {{ const i = {bub}?.querySelector('.chimg img'); return i && i.complete && i.naturalWidth > 0; }})()", timeout=10000)
        check(True, "its picture loads from GET /media/")
        shot("4b-file")
        # 3. To an engineer not in the seat: waiting for the seat
        p.tap("#rmto")
        p.wait_for_selector("#rmtopick [data-rmto=kim-x]", timeout=3000)
        p.tap("#rmtopick [data-rmto=kim-x]")
        check(p.text_content("#rmto") == "To Kim", "the To chip: Ensign Kim picked")
        n0 = len(msgs(srv))
        p.fill("#rmbox", "Run the tests.")
        p.tap("#rmsend")
        p.wait_for_function("[...document.querySelectorAll('#rmlog .rmm.me')].some(m => m.textContent.includes('Run the tests') && m.textContent.includes('waiting for the seat'))",
                            timeout=10000)
        check(True, "to one not in the seat: waiting for the seat")
        p.wait_for_function("rm.pend.length === 0", timeout=10000)
        new = msgs(srv)[n0:]
        check(len(new) == 1 and new[0]["title"].startswith("captain → kim-x #deck:") and new[0]["done_bool"] == 0 and
              new[0].get("content", "").startswith("to:: kim-x\n"), f"its row: to:: kim-x in deck, done 0 ({new})")
        check("waiting for the seat" in p.evaluate("[...document.querySelectorAll('#rmlog .rmm.me')].pop().textContent"),
              "the row still says waiting for the seat")
        shot("5-waiting")
        api(srv, "PATCH", f"/entries/{new[0]['id']}", {"done_bool": 1})  # the seat delivers it
        p.wait_for_function("![...document.querySelectorAll('#rmlog .rmm.me')].pop().textContent.includes('waiting for the seat')",
                            timeout=10000)
        check(True, "delivered: the mark goes")
        # 4. a failure, Retry
        p.fill("#rmbox", "FAIL on purpose")
        p.tap("#rmsend")
        p.wait_for_selector("#rmlog [data-rmresend]", timeout=10000)
        check("not sent" in p.evaluate("[...document.querySelectorAll('#rmlog .rmm.me')].pop().textContent"), "a failure on the bubble")
        check(p.input_value("#rmbox") == "FAIL on purpose", "the words given back to the box")
        shot("6-failed")
        p.fill("#rmbox", "")
        # 5. New room, Close, Reopen; Back
        p.tap("#rmroomback")
        p.wait_for_selector("#rmlist", timeout=3000)
        p.wait_for_function("location.pathname === '/ui/rooms'", timeout=3000)
        check(url() == "/ui/rooms", f"‹: the list ({url()})")
        p.tap("#rmplus")
        p.fill("#rmnewhead", "Motion graphics")
        p.tap("[data-rmnewgo]")
        p.wait_for_function("rm.open === 'motion-graphics'", timeout=2000)
        check("opening" in p.text_content("#rmstat"), "New room: the room at once, opening…")
        shot("7-opening")
        p.wait_for_function("!/opening/.test(document.querySelector('#rmstat').textContent)", timeout=10000)
        made = [r for r in rooms(srv) if "id:: motion-graphics" in (r.get("content") or "")]
        check(len(made) == 1 and made[0]["title"] == "Motion graphics" and not made[0]["done_bool"], f"its row ({made})")
        p.tap("#rmmore")
        p.tap("[data-rmclose]")
        p.wait_for_selector("#rmlist details[data-rmclosed]", timeout=10000)
        p.wait_for_function("!rm.ov.size", timeout=10000)
        made = [r for r in rooms(srv) if "id:: motion-graphics" in (r.get("content") or "")]
        check(made and made[0]["done_bool"] == 1, "Close: its row done, the room under Closed")
        p.tap("#rmlist details[data-rmclosed] summary")
        p.tap("#rmlist details[data-rmclosed] [data-rm=motion-graphics]")
        p.wait_for_selector("#rmmore", timeout=3000)
        p.tap("#rmmore")
        p.tap("[data-rmclose]")
        p.wait_for_function("!rm.ov.size", timeout=10000)
        made = [r for r in rooms(srv) if "id:: motion-graphics" in (r.get("content") or "")]
        check(made and made[0]["done_bool"] == 0, "Reopen: done 0 again")
        check(wide() <= W, f"a room no wider than the phone ({wide()})")
        # 5b. Archive (rooms.md 17): from a crew room's ⋯, kept in the journal
        # (a settings entry titled rooms), the row under Archived; Restore
        p.tap("#rmroomback")
        p.wait_for_selector("#rmlist", timeout=3000)
        p.tap("#rmlist [data-rm=obrien-x]")
        p.wait_for_selector("#rmmore", timeout=3000)
        p.tap("#rmmore")
        p.tap("[data-rmarchone]")
        p.wait_for_selector("#rmlist details[data-rmarchd] [data-rm=obrien-x]", state="attached", timeout=3000)
        check(True, "Archive: the room off the list at once, under Archived")
        p.wait_for_function("!rm.arch.size", timeout=10000)
        st, rows = api(srv, "GET", "/entries?kind=settings&limit=50")
        mark = [r for r in rows if r["title"] == "rooms"] if st == 200 else []
        check(len(mark) == 1 and json.loads(mark[0]["content"]).get("archived") == ["obrien-x"],
              f"the mark in the journal: settings 'rooms', archived [obrien-x] ({[m.get('content') for m in mark]})")
        shot("7b-archived")
        p.tap("#rmlist details[data-rmarchd] summary")
        p.tap("#rmlist details[data-rmarchd] [data-rmunarch=obrien-x]")
        p.wait_for_function("!document.querySelector('#rmlist details[data-rmarchd]') && !rm.arch.size", timeout=10000)
        st, rows = api(srv, "GET", "/entries?kind=settings&limit=50")
        mark = [r for r in rows if r["title"] == "rooms"] if st == 200 else []
        check(mark and json.loads(mark[0]["content"]).get("archived") == [], "Restore: back on the list, out of the entry")
        p.tap("#rmlist [data-rm=deck]")
        p.wait_for_selector("#rmlog", timeout=3000)
        # 6. Back and Escape
        p.tap("#rmroomback")
        p.wait_for_selector("#rmlist", timeout=3000)
        p.tap("#rmlist [data-rm=deck]")
        p.wait_for_selector("#rmlog", timeout=3000)
        p.wait_for_function("location.pathname === '/ui/rooms/deck'", timeout=3000)
        p.go_back()
        p.wait_for_selector("#rmlist", timeout=3000)
        check(url() == "/ui/rooms", f"Back from a room: the list ({url()})")
        p.go_back()
        p.wait_for_function("!location.pathname.startsWith('/ui/rooms') && !document.querySelector('#rmpage')", timeout=3000)
        check(url() == "/ui/chats", f"Back from the list: out of the rooms, to the chats it was opened from ({url()})")
        p.evaluate("openRooms('deck')")
        p.wait_for_selector("#rmlog", timeout=3000)
        p.keyboard.press("Escape")
        p.wait_for_selector("#rmlist", timeout=3000)
        check(True, "Escape: a room to the list")
        p.keyboard.press("Escape")
        p.wait_for_function("!document.querySelector('#rmpage') && !!document.querySelector('#chrows')", timeout=3000)
        check(True, "Escape again: out, to the chats it was opened over")
        p.keyboard.press("Escape")
        p.wait_for_function("!document.querySelector('#ov').classList.contains('on')", timeout=3000)
        p.evaluate("openRooms()")
        p.wait_for_selector("#rmlist", timeout=3000)
        p.keyboard.press("Escape")
        p.wait_for_function("!document.querySelector('#ov').classList.contains('on')", timeout=3000)
        check(True, "opened from the journal: Escape closes it")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def run_desk(b, srv, shots):
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": F.USER, "pass": F.PASS}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.deck.engkey', {json.dumps(json.dumps(KEY))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))

    def box(sel):
        return p.evaluate(f"(() => {{ const r = document.querySelector({sel!r})?.getBoundingClientRect(); return r ? [r.x, r.width] : null; }})()")
    try:
        p.goto(cfg["base"] + "/ui/")
        p.wait_for_function("typeof openRooms === 'function' && st.all.some(e => e.kind === 'crew_msg')", timeout=20000)
        # 7. the desk: the door from the chats, both panes
        p.evaluate("chatsUp(); chatsList(); engListFetch(true)")
        p.wait_for_selector("#chrows [data-rooms]", timeout=5000)
        chats_list = box("#dlg .chlistp")
        p.click("#chrows [data-rooms]")
        p.wait_for_selector("#rmlist [data-rm=deck]", timeout=5000)
        lst, pick = box("#rmpage"), p.evaluate("getComputedStyle(document.querySelector('#rmroom .chnone')).display")
        check(lst and chats_list and lst[0] < 2 and lst[1] == chats_list[1], f"desk: the rooms' list where the chats' list is, its width ({lst} vs {chats_list})")
        check(pick == "block", f"desk: no room open, the right pane says pick one ({pick})")
        p.click("#rmlist [data-rm=deck]")
        p.wait_for_selector("#rmlog .rmm", timeout=5000)
        room = box("#rmroom")
        check(p.is_visible("#rmlist [data-rm=main]") and room and room[1] > 1280 * 0.6,
              f"desk: a room in the right pane, most of the screen ({room}), the list still beside it")
        check(p.evaluate("document.querySelector('#rmlist [data-rm=deck]').classList.contains('on')"), "desk: the open room's row marked")
        check(p.is_visible("#rmto") and p.is_visible("#rmbox"), "desk: the box and its To chip in the room's pane")
        if shots:
            p.screenshot(path=str(shots / "8-desk.png"))
        p.click("#rmlist [data-rm=main]")
        p.wait_for_function("location.pathname === '/ui/rooms/main' && document.querySelector('#rmstat').textContent.includes(\"Number One's room\")",
                            timeout=3000)
        check(p.is_visible("#rmlist [data-rm=deck]") and
              p.evaluate("document.querySelector('#rmlist [data-rm=main]').classList.contains('on') && "
                         "!document.querySelector('#rmlist [data-rm=deck]').classList.contains('on')"),
              "desk: another row swaps the right pane, the list kept, the mark moved")
        p.go_back()
        # one room to another is not a step (the chats' rule): Back is the list
        p.wait_for_function("location.pathname === '/ui/rooms' && !rm.open && !!document.querySelector('#rmroom .chnone')", timeout=3000)
        check(p.is_visible("#rmlist [data-rm=deck]"), "desk: Back from a room is the list (a history step), the list still there")
        p.click("#rmlist [data-rm=deck]")
        p.wait_for_function("location.pathname === '/ui/rooms/deck'", timeout=3000)
        p.click("#rmroomback")
        p.wait_for_function("!document.querySelector('#rmpage') && !!document.querySelector('#chrows') && location.pathname === '/ui/chats'",
                            timeout=3000)
        check(True, "desk: the room's ‹ goes up a level, to the chats")
        check(errs == [], f"desk: no page errors ({errs[:2]})")
    finally:
        ctx.close()


def main():
    shots = None
    if "--shots" in sys.argv:
        shots = pathlib.Path(sys.argv[sys.argv.index("--shots") + 1])
        shots.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("rooms_ui: playwright is not installed")
    # "lcars-features-": the name engineer.py's TEST_TMP_RE reaps when killed
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-features-rooms"))
    try:
        binary = os.environ.get("LCARS_TEST_BIN")
        if not binary:
            binary = str(tmp / "lcars")
            F.build(binary)
        d = tmp / "srv"
        (d / "home").mkdir(parents=True)
        script = d / "engineer.py"
        env = {"HOME": str(d / "home"), "PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin", "LCARS_EMBED": "0",
               "LCARS_CHAT": "0", "LCARS_ENGINEER": "1", "LCARS_ENGINEER_KEY": KEY, "LCARS_ENGINEER_SCRIPT": str(script),
               "LCARS_PYTHON": sys.executable, "LCARS_UI_DIR": str(UI), "LCARS_MEDIA_ROOT": str(d / "media"),
               "LCARS_MEDIA_CACHE": str(d / "cache")}
        (d / "media" / "media").mkdir(parents=True)   # the root's media/, the store's own
        SAID[0], MEDIA[0] = str(d / "said.jsonl"), str(d / "media")
        script.write_text("print('{}')\n")   # there for the server's start; written in full once it has a port
        srv = F.Server(binary, d, env)
        script.write_text(STAND_IN % {"scripts": str(REPO / "scripts"), "base": f"http://127.0.0.1:{srv.port}",
                                      "cred": f"{F.USER}:{F.PASS}", "said": SAID[0], "root": MEDIA[0]})
        try:
            seed(srv)
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                try:
                    run(b, srv, shots)
                    run_desk(b, srv, shots)
                finally:
                    b.close()
        finally:
            srv.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"rooms_ui: {checks[0] - len(fails)} of {checks[0]} checks passed")
    for f in fails:
        print("  FAIL " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
