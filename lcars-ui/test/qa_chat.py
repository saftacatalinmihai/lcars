#!/usr/bin/env python3
"""QA rig for the chats, by hand turned into a script: the list, a thread,
the swipe, the sheets, an engineer's conversation, voice, at a phone's size.

    python3 test/qa_chat.py                 (~1 min; Chromium, phone + desk)
    python3 test/qa_chat.py --engine webkit (Playwright's WebKit, iPhone 13)
    LCARS_TEST_BIN=<binary> skips the build of the scratch server.

Not part of run.sh: it is Lt. Yar's QA pass (docs/qa/chat.md), kept so it
can be run again. The server is a scratch build (offline.py's rig) with an
empty journal; the chats are seeded into localStorage; /engineer* and /chat
are faked in the browser (page.route): four engineers (Number One, Reyes
with two earlier conversations and 70 events, Mendez working, one
dismissed), paged 20 events at a time as `engineer.py poll` does. Nothing
here touches lcars.db.

Touches. Chromium: CDP Input.dispatchTouchEvent, through the compositor, so
the browser's own scrolling and click-after-tap happen. WebKit has no CDP:
a drag is TouchEvents dispatched from the page (untrusted, so no native
scroll), a tap is Playwright's touchscreen.tap (trusted, with its click).

WebKit on a box without its system libraries (Debian, no root):
    apt-get download <the libraries Playwright names>; dpkg-deb -x each
    into a directory, and point QA_WEBKIT at a wrapper that sets
    LD_LIBRARY_PATH to it and execs ms-playwright's
    webkit-*/minibrowser-wpe/bin/MiniBrowser (its own MiniBrowser script
    overwrites LD_LIBRARY_PATH).
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.parse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import offline as rig  # the scratch build and server  # noqa: E402

check, fails, checks = rig.check, rig.fails, rig.checks
MS = int(time.time() * 1000)
NOW = int(time.time())


def threads():
    long = [{"role": "user", "text": "second thread"}] + [
        m for i in range(30) for m in ({"role": "user", "text": f"question {i}"},
                                       {"role": "asst", "parts": [{"t": "text", "s": f"answer {i} " + "lorem ipsum " * 20}]})]
    ls = [{"id": "computer-1", "at": MS - 3600e3, "unread": 2,
           "msgs": [{"role": "user", "text": "first thread"}, {"role": "asst", "parts": [{"t": "text", "s": "an answer"}]}]},
          {"id": "computer-2", "at": MS - 60e3, "msgs": long},
          {"id": "role-crew_ops", "at": MS - 7200e3, "role": {"kind": "crew_ops", "title": "Operations Officer"},
           "msgs": [{"role": "user", "text": "why the disk?"}]}]
    # enough rows that the list scrolls on a phone
    for i in range(10):
        ls.append({"id": f"computer-{10 + i}", "at": MS - (5 + i) * 86400e3,
                   "msgs": [{"role": "user", "text": f"filler thread {i}"}]})
    return {"seq": 30, "model": "sonnet", "list": ls}


class Fake:
    """/engineer and /chat, answered in the browser."""

    def __init__(self):
        self.eng = {
            "number-one": {"title": "Number One", "status": "idle", "task": "watching", "session": "s-no1", "past": []},
            "reyes-a1": {"title": "Lt. Reyes", "status": "idle", "task": "fix the rail", "session": "s-r3",
                         "past": [{"session": "s-r1", "name": "first job", "at": NOW - 86400 * 2},
                                  {"session": "s-r2", "name": "second job", "at": NOW - 86400}]},
            "mendez-b2": {"title": "Lt. Mendez", "status": "working", "task": "chat design", "session": "s-m1", "past": []},
            "old-c3": {"title": "Ens. Old", "status": "off", "task": "", "session": "s-o1", "past": [], "dismissed": True},
        }
        self.trans = {}
        for sid, n, who in [("s-no1", 6, "no1"), ("s-r1", 50, "r1"), ("s-r2", 50, "r2"), ("s-r3", 70, "r3"),
                            ("s-m1", 8, "m"), ("s-o1", 2, "o")]:
            self.trans[sid] = [{"r": "me", "t": f"{who} order {i}"} if i % 3 == 0 else
                               {"r": "tool", "t": f"$ ls {i}"} if i % 3 == 1 else
                               {"r": "them", "t": f"{who} answer {i} " + "words " * 15} for i in range(n)]
        self.log, self.hold, self.held = [], False, []
        self.say_queued = False

    def say(self, route, request):
        """/say (a voice: three seconds of PCM a line) and /say/token."""
        u = urllib.parse.urlparse(request.url)
        if u.path.endswith("/say/token"):
            self.log.append(("GET", "/say/token", None))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"access_token": "aaaa.bbbb.cccc", "expires_in": 30}))
        if request.method == "GET":
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"provider": "deepgram"}))
        body = json.loads(request.post_data or "{}")
        self.log.append(("POST", "/say", body))
        route.fulfill(status=200, content_type="audio/L16;rate=24000;channels=1", body=b"\x10\x00" * 72000)

    def engineer(self, route, request):
        u = urllib.parse.urlparse(request.url)
        path, q = u.path[len("/engineer"):], dict(urllib.parse.parse_qsl(u.query))
        self.log.append((request.method, path, q))

        def j(o, s=200):
            route.fulfill(status=s, content_type="application/json", body=json.dumps(o))
        if path in ("", "/") and request.method == "GET":
            return j({"engineers": [dict(name=k, title=v["title"], status=v["status"], task=v["task"], active=NOW - i * 600,
                                         dismissed=v.get("dismissed", False), model="opus", ctx=167000)
                                    for i, (k, v) in enumerate(self.eng.items())],
                      "deploy": {}, "seat": {"holder": "mendez-b2", "queue": [], "waiting": []}})
        parts = path.strip("/").split("/")
        st = self.eng.get(parts[0])
        if not st:
            return j({"error": "no such engineer"}, 404)
        if len(parts) == 2:
            body = json.loads(request.post_data or "{}")
            if parts[1] == "say":
                if self.say_queued:
                    return j({"ok": True, "queued": True, "seat": {"position": 2, "holder": "mendez-b2"}})
                self.trans[st["session"]].append({"r": "me", "t": body.get("message", "")})
            elif parts[1] in ("dismiss", "recall"):
                st["dismissed"] = parts[1] == "dismiss"
            return j({"ok": True})
        ev = self.trans[q.get("past") or st["session"]]
        off, before = int(q.get("off", "-1")), int(q.get("before", "-1"))
        if 0 <= before <= len(ev):
            f = max(0, before - 20)
            evs, nxt, first = ev[f:before], off, f
        elif 0 <= off <= len(ev):
            evs, nxt, first = ev[off:], len(ev), 0
        else:
            f = max(0, len(ev) - 20)
            evs, nxt, first = ev[f:], len(ev), f
        return j({"name": parts[0], "title": st["title"], "task": st["task"], "status": st["status"],
                  "session": st["session"], "past": st["past"], "viewing": q.get("past", ""),
                  "git": {"branch": "eng/" + parts[0], "ahead": 1}, "deploy": {}, "preview": "", "model": "opus", "ctx": 167000,
                  "events": evs, "next": nxt, "first": first})

    def chat(self, route, request):
        body = json.loads(request.post_data or "{}")
        self.log.append(("POST", "/chat", body.get("message")))
        if self.hold:
            self.held.append((route, body))
            return
        self.answer(route, body)

    @staticmethod
    def answer(route, body, fail=None, early=False):
        if fail:
            return route.fulfill(status=fail, content_type="application/json", body=json.dumps({"error": "boom"}))
        evs = [{"type": "system", "subtype": "init", "session_id": "sid-1"},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": "Answer to: " + body.get("message", "")[-60:]}]}},
               {"type": "result", "session_id": "sid-1", "duration_ms": 1200, "total_cost_usd": 0.01,
                "result": "Answer to: " + body.get("message", "")[-60:]},
               {"type": "lcars_exit", "code": 0}]
        if early:
            evs = evs[:1]
        route.fulfill(status=200, content_type="text/event-stream",
                      body="".join("data: " + json.dumps(e) + "\n\n" for e in evs))


class Browser:
    def __init__(self, p, srv, engine, phone=True):
        self.engine, self.phone, self.srv = engine, phone, srv
        self.fake = Fake()
        if engine == "webkit":
            exe = os.environ.get("QA_WEBKIT")
            self.browser = p.webkit.launch(**({"executable_path": exe} if exe else {}))
            kw = dict(p.devices["iPhone 13"]) if phone else {"viewport": {"width": 1280, "height": 800}}
            kw.pop("default_browser_type", None)
        else:
            # a fake microphone, allowed without asking: the talk pass holds to talk
            self.browser = p.chromium.launch(headless=True, args=["--use-fake-device-for-media-stream",
                                                                  "--use-fake-ui-for-media-stream"])
            kw = dict(viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True, device_scale_factor=3,
                      user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                                 "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1") \
                if phone else dict(viewport={"width": 1280, "height": 800})
        # page.route does not see what a service worker fetches (sw.js)
        self.ctx = self.browser.new_context(service_workers="block", **kw)
        self.ctx.set_default_timeout(15000)
        cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
        self.ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) {"
                                 f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                                 f"localStorage.setItem('lcars.chats', {json.dumps(json.dumps(threads()))});"
                                 "localStorage.setItem('lcars.deck.engkey', JSON.stringify('k')); }")
        self.page = self.ctx.new_page()
        self.errs = []
        # headless WebKit has no audio device: sfx's AudioContext fails, not the page
        self.page.on("pageerror", lambda e: "audio device" in str(e) or self.errs.append(str(e)))
        self.page.route("**/engineer**", self.fake.engineer)
        self.page.route("**/chat", self.fake.chat)
        # the server's /say and /say/token, not an engineer's /engineer/<name>/say
        self.page.route(re.compile(r"^https?://[^/]+/say(/token)?$"), self.fake.say)
        self.cdp = self.ctx.new_cdp_session(self.page) if phone and engine == "chromium" else None

    def close(self):
        self.browser.close()

    def boot(self, path="chats"):
        self.page.goto(self.srv.base + "/ui/" + path, wait_until="domcontentloaded")
        self.page.wait_for_function("typeof st !== 'undefined' && typeof chats !== 'undefined'")
        self.page.wait_for_timeout(900)

    def ev(self, js, *a):
        return self.page.evaluate(js, *a)

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def mid(self, sel):
        loc = self.page.locator(sel).first
        loc.scroll_into_view_if_needed()
        self.wait(150)
        b = loc.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    # ---- touches ----
    def _js_touch(self, typ, x, y):
        self.ev("""([typ, x, y]) => {
          window.__tt = window.__tt || {};
          if (typ === 'touchstart') __tt.el = document.elementFromPoint(x, y);
          const el = __tt.el; if (!el) return;
          // WebKit, as Safari: Touch is not constructible and TouchEvent takes
          // no touch lists, so the lists the handlers read are laid on
          const pt = { identifier: 1, target: el, clientX: x, clientY: y, pageX: x, pageY: y };
          const on = typ === 'touchend' ? [] : [pt];
          const e = new TouchEvent(typ, { bubbles: true, cancelable: true });
          for (const [k, v] of [['touches', on], ['targetTouches', on], ['changedTouches', [pt]]])
            Object.defineProperty(e, k, { value: v });
          el.dispatchEvent(e); }""", [typ, x, y])

    def drag(self, x0, y0, x1, y1, steps=10, ms=16, mid=None):
        """A finger from (x0,y0) to (x1,y1); `mid` runs before letting go."""
        if self.cdp:
            send = lambda t, pts: self.cdp.send("Input.dispatchTouchEvent",
                                                {"type": t, "touchPoints": [{"x": x, "y": y} for x, y in pts]})
            send("touchStart", [(x0, y0)])
            for i in range(1, steps + 1):
                send("touchMove", [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)])
                self.wait(ms)
            r = mid() if mid else None
            send("touchEnd", [])
        else:
            self._js_touch("touchstart", x0, y0)
            for i in range(1, steps + 1):
                self._js_touch("touchmove", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
                self.wait(ms)
            r = mid() if mid else None
            self._js_touch("touchend", x1, y1)
        self.wait(250)
        return r

    def tap(self, where):
        x, y = self.mid(where) if isinstance(where, str) else where
        if self.cdp:
            for t, pts in (("touchStart", [{"x": x, "y": y}]), ("touchEnd", [])):
                self.cdp.send("Input.dispatchTouchEvent", {"type": t, "touchPoints": pts})
                self.wait(50)
        else:
            self.page.touchscreen.tap(x, y)
        self.wait(350)

    # ---- what is on screen ----
    def url(self):
        return self.page.url.split("/ui/", 1)[1].split("?")[0]

    def swiped(self):
        return self.ev("() => [...document.querySelectorAll('#chrows .chrowl.swiped')].map(x => x.querySelector('.chrow').getAttribute('aria-label'))")

    def toast(self):
        return self.ev("() => { const t = document.querySelector('#toast'); return t && t.classList.contains('on') !== false ? t.textContent : '' }")

    def row(self, key):
        return f'#chrows .chrow[{key}]'

    def last(self, n=3):
        return self.ev(f"() => [...document.querySelectorAll('.chth .chlog > *')].slice(-{n}).map(x => x.className + ': ' + x.textContent.slice(0, 70))")


# ===================== the passes =====================

def swipe_pass(b):
    """The row swipe at a phone's size (docs/qa/chat.md bugs 1-4, 10, 12)."""
    b.boot()
    R1, R2 = b.row('data-id="computer-1"'), b.row('data-id="computer-2"')
    x, y = b.mid(R1)
    # 1: a drag of 60px opens; the actions show while dragging
    shown = b.drag(370, y, 310, y, mid=lambda: b.ev(
        "() => { const a = document.querySelector('#chrows .chrow[data-id=\"computer-1\"]').parentNode.querySelector('.chacts');"
        " return !!a && getComputedStyle(a).display !== 'none' && a.getBoundingClientRect().width > 0 }"))
    check(shown, "swipe: the actions show while the row is dragged")
    check(b.swiped() == ["first thread"], f"swipe: 60px left opens the row (open: {b.swiped()})")
    # tap Archive: archived, the list stays
    b.tap('#chrows .chrowl.swiped .chacts [data-arch]')
    check(b.ev("() => chatFind('computer-1').archived") is True and b.url() == "chats",
          f"swipe: a tap on Archive archives, the list stays (url {b.url()})")
    left_open = b.ev("() => [chatSw.open, [...document.querySelectorAll('#chrows .chrowl.swiped')].length]")
    check(not left_open[0] and not left_open[1], f"swipe: nothing left open after the action ran (chatSw.open={left_open[0]!r}, swiped rows {left_open[1]})")
    # the next tap after an archive does what it says (opening Archived)
    b.tap("#chrows details.chold:not([data-eng-off]) > summary")
    check(b.ev("() => document.querySelector('#chrows details.chold:not([data-eng-off])').open"),
          "swipe: after an Archive, the next tap (Archived's summary) opens Archived")
    b.ev("() => { const d = document.querySelector('#chrows details.chold:not([data-eng-off])'); d.open = true; chats.oldOpen = true; }")
    arch_open = b.swiped()
    check(not arch_open, f"swipe: the archived row is not shown swiped open (open: {arch_open})")
    # Bring back from Archived by swipe (the archive's toast, over the
    # foot of the list, taken away first: a tap there would be its Undo)
    b.ev("() => { const t = document.querySelector('#toast'); if (t) t.style.display = 'none'; }")
    x, y = b.mid(R1)
    b.drag(370, y, 300, y)
    b.tap('#chrows .chrowl.swiped .chacts [data-back]')
    check(b.ev("() => !chatFind('computer-1').archived"), "swipe: Bring back (archived row) brings it back")
    check(b.ev("() => chatFind('computer-1').unread") == 2, "swipe: back from Archived with its unread count")

    # 2: under 40px springs back; 45px opens
    b.boot()
    x, y = b.mid(R2)
    b.drag(370, y, 340, y, steps=4)
    check(b.swiped() == [], f"swipe: 30px does not open (open: {b.swiped()})")
    b.drag(370, y, 325, y, steps=5)
    check(b.swiped() == ["second thread"], f"swipe: 45px opens (open: {b.swiped()})")
    # a touch elsewhere only closes it: another row
    b.tap(R1)
    check(b.url() == "chats" and b.swiped() == [], f"swipe: a tap on another row only closes the open one (url {b.url()}, open {b.swiped()})")
    # the search box
    x, y = b.mid(R2)
    b.drag(370, y, 300, y)
    b.tap("#chfind")
    check(b.swiped() == [], "swipe: a tap on the search closes the open row")
    # the header's ‹
    b.ev("() => document.activeElement.blur()")
    x, y = b.mid(R2)
    b.drag(370, y, 300, y)
    check(b.swiped() == ["second thread"], "swipe: open again")
    b.tap("#chclose")
    check(b.swiped() == [] and b.ev("() => document.querySelector('#ov').classList.contains('on')"),
          "swipe: a tap on ‹ closes the open row and not the chats")
    b.tap("#chclose")
    check(not b.ev("() => document.querySelector('#ov').classList.contains('on')"), "swipe: the next tap on ‹ closes the chats")

    # 3: swipe right marks read; on a read row it marks unread (0.163.0, as Mail)
    b.boot()
    x, y = b.mid(R1)
    under = b.drag(30, y, 110, y, mid=lambda: b.ev("() => document.querySelector('#chrows .chrow[data-id=\"computer-1\"]').parentNode.classList.contains('dr')"))
    check(under, "swipe right: Mark read shows under the row while dragged")
    check(b.ev("() => chatFind('computer-1').unread") == 0, "swipe right: 80px marks the thread read")
    x, y = b.mid(R2)
    rd = b.ev("() => document.querySelector('#chrows .chrow[data-id=\"computer-2\"]').parentNode.dataset.rd")
    b.drag(30, y, 110, y)
    check(rd == "unread" and b.ev("() => chatFind('computer-2').mark"),
          f"swipe right: a read row is marked unread (data-rd {rd!r})")
    check(b.ev("() => /\u2022/.test(document.querySelector('#chrows .chrow[data-id=\"computer-2\"]').textContent)"),
          "swipe right: its row shows the unread dot at once")
    x, y = b.mid(R2)
    b.drag(30, y, 110, y)
    check(not b.ev("() => chatFind('computer-2').mark"), "swipe right: the next one marks it read again")

    # 4: repaints
    b.boot()
    x, y = b.mid(R2)
    b.drag(370, y, 300, y)
    b.ev("() => chatListPaint()")
    check(b.swiped() == ["second thread"], "repaint: an open row stays open")
    b.tap('#chrows .chrowl.swiped .chacts [data-arch]')
    b.ev("() => chatArchive('computer-2', false)")
    b.wait(200)
    x, y = b.mid(R1)
    b.drag(370, y, 300, y, mid=lambda: b.ev("() => chatListPaint()"))
    check(b.swiped() == ["first thread"], f"repaint: a repaint mid-drag does not lose the swipe (open: {b.swiped()})")
    check(b.ev("() => !chatSw.drag && !chatSw.missed"), "repaint: the held repaint ran on letting go")

    # engineers: Dismiss, then Bring back; Number One does not slide
    b.boot()
    x, y = b.mid(b.row('data-eng="reyes-a1"'))
    b.drag(370, y, 300, y)
    b.tap('#chrows .chrowl.swiped .chacts [data-dismiss]')
    b.wait(400)
    check(b.ev("() => !!eng.list.find(x => x.name == 'reyes-a1').dismissed") and b.url() == "chats",
          f"swipe: Dismiss dismisses (url {b.url()})")
    b.tap("#chrows details[data-eng-off] > summary")
    check(b.ev("() => document.querySelector('#chrows details[data-eng-off]').open"),
          "swipe: after a Dismiss, the next tap (Dismissed's summary) opens Dismissed")
    b.ev("() => { const d = document.querySelector('#chrows details[data-eng-off]'); d.open = true; eng.offOpen = true; }")
    x, y = b.mid(b.row('data-eng="reyes-a1"'))
    b.drag(370, y, 300, y)
    b.tap('#chrows .chrowl.swiped .chacts [data-recall]')
    b.wait(400)
    check(b.ev("() => !eng.list.find(x => x.name == 'reyes-a1').dismissed"), "swipe: Bring back (dismissed engineer) brings them back")
    x, y = b.mid(b.row('data-eng="number-one"'))
    moved = b.drag(370, y, 280, y, mid=lambda: b.ev("() => document.querySelector('#chrows .chrow[data-eng=\"number-one\"]').style.transform"))
    check(not moved and b.swiped() == [], f"swipe: Number One (no actions) does not slide ({moved!r})")

    # vertical scroll (Chromium only: WebKit's touches here are synthetic)
    if b.cdp:
        b.boot()
        top0 = b.ev("() => document.querySelector('#chrows').scrollTop")
        x, y = b.mid(R2)
        b.drag(200, 560, 205, 260, steps=12)
        b.wait(500)
        top1 = b.ev("() => document.querySelector('#chrows').scrollTop")
        check(top1 > top0 + 100, f"scroll: a vertical drag over the rows scrolls the list ({top0} -> {top1})")
        check(b.swiped() == [], "scroll: and opens no row")


def thread_pass(b):
    """A computer thread: open, send, Stop, a failure and Retry, sheets, Back."""
    b.boot()
    b.tap(b.row('data-id="computer-2"'))
    check(b.url() == "chats/computer-2", f"thread: a row's tap opens it ({b.url()})")
    check(not b.ev("() => document.activeElement.classList.contains('chbox')"), "thread: the box is not focused on a phone")
    check(b.ev("() => chatTitle(chat)") == "second thread", f"thread: its title is its first question past 40 messages ({b.ev('() => chatTitle(chat)')!r})")
    b.fake.hold = True
    b.tap(".chth .chbox")
    b.page.keyboard.type("hello there")
    b.tap(".chth .chsend")
    check(b.ev("() => document.activeElement.classList.contains('chbox')"), "send: the box keeps the focus through Send")
    check("sending" in b.last(2)[0] and b.ev("() => document.querySelector('.chth .chsend').textContent") == "Stop",
          f"send: the bubble says sending…, Send is Stop ({b.last(2)})")
    b.tap(".chth .chsend")
    b.wait(300)
    check("stopped" in b.last(1)[0], f"stop: the answer ends as stopped ({b.last(1)})")
    b.fake.held.clear()
    b.page.keyboard.type("this one fails")
    b.tap(".chth .chsend")
    route, body = b.fake.held.pop()
    Fake.answer(route, body, fail=500)
    b.wait(500)
    check("not sent" in b.last(1)[0] and b.ev("() => document.querySelector('.chth .chbox').value") == "this one fails",
          f"fail: not sent, Retry, the text back ({b.last(1)})")
    b.fake.hold = False
    b.tap(".chth .chlog .chretry")
    b.wait(800)
    check("Answer to: this one fails" in b.last(1)[0] and b.ev("() => document.querySelector('.chth .chbox').value") == "",
          f"retry: sent again and answered ({b.last(1)})")
    # Enter on a touch screen is a new line
    b.tap(".chth .chbox")
    b.page.keyboard.type("line one")
    b.page.keyboard.press("Enter")
    b.page.keyboard.type("line two")
    check(b.ev("() => document.querySelector('.chth .chbox').value") == "line one\nline two",
          f"enter: a new line on a touch screen ({b.ev('() => document.querySelector(`.chth .chbox`).value')!r})")
    b.ev("() => { document.querySelector('.chth .chbox').value = ''; }")
    b.tap(".chth .chmore")
    check(b.ev("() => !document.querySelector('.chth .chscrim').hidden") and b.ev("() => document.activeElement.classList.contains('chbox')"),
          "sheet: ⋯ opens and the box keeps the focus")
    b.tap((200, 120))
    check(b.ev("() => document.querySelector('.chth .chscrim').hidden"), "sheet: a tap beside it closes it")
    b.tap(".chth .chmodel")
    b.tap('.chth .chsheet button[data-model="opus"]')
    check(b.ev("() => document.querySelector('.chth .chmodel').textContent").lower().startswith("opus") and
          "Opus from here" in b.ev("() => chat.msgs.slice(-1)[0].text || ''"), "model: the chip and the line change at once")
    b.ev("() => document.activeElement.blur()")
    b.tap(".chth .chhdr .chback")
    check(b.url() == "chats", f"back: ‹ is the list ({b.url()})")
    b.page.go_back()
    b.wait(500)
    check(not b.ev("() => document.querySelector('#ov').classList.contains('on')"), "back: Back from the list leaves the chats")
    # a long thread's title survives a reload past CHAT_KEEP
    b.boot()
    check(b.ev("() => chatTitle(chatFind('computer-2'))") == "second thread", "title: kept across a reload")


# .chth .chgauge: its text, inside the viewport, not clipped, the title's width,
# and in the header's first row (level with ⋯, not wrapped under it)
GAUGE = """() => { const g = document.querySelector('.chth .chgauge'), r = g.getBoundingClientRect(), m = document.querySelector('.chth .chmore').getBoundingClientRect();
  return { t: g.textContent.replace(/\\s+/g, ''), in: !g.hidden && r.width > 0 && r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight,
           clip: g.scrollWidth > g.clientWidth + 1, title: Math.round(document.querySelector('.chth .chtitle').getBoundingClientRect().width),
           row1: Math.abs((r.top + r.bottom) / 2 - (m.top + m.bottom) / 2) < 12, w: Math.round(r.width), vw: innerWidth }; }"""


def engineer_pass(b):
    """An engineer's conversation: scroll back, earlier conversations, send, Dismiss."""
    b.boot()
    # their context in the Crew row, beside the when, the name not crowded out
    rc = b.ev("""() => { const r = document.querySelector('.chrow[data-eng="reyes-a1"]'), c = r && r.querySelector('.chrc');
      if (!c) return null; const cr = c.getBoundingClientRect();
      return { t: c.textContent, in: cr.width > 0 && cr.right <= r.getBoundingClientRect().right, name: Math.round(r.querySelector('.chrt b').getBoundingClientRect().width) }; }""")
    check(rc and rc["t"] == "84%" and rc["in"] and rc["name"] >= 120, f"engineer: the Crew row gives their context, 84%, the name keeps its room ({rc})")
    b.tap(b.row('data-eng="reyes-a1"'))
    b.wait(800)
    check(b.url() == "chats/eng-reyes-a1", f"engineer: the row opens their thread ({b.url()})")
    # the status line wraps on a phone, three rows at most
    st = b.ev("""() => { const s = document.querySelector('.chth .chhdr .chstat'), lh = parseFloat(getComputedStyle(s).lineHeight) || 13;
      return { t: s.textContent, rows: Math.round(s.clientHeight / lh), ws: getComputedStyle(s).whiteSpace }; }""")
    check(st["rows"] <= 3 and "ctx" not in st["t"], f"engineer: the status line wraps on a phone, the gauge not in it ({st})")
    # the context gauge, its own figure: on screen with Voice on at a phone's width
    if b.ev("() => document.querySelector('.chth .chvoice').getAttribute('aria-pressed')") != "true":
        b.tap(".chth .chvoice")
    g = b.ev(GAUGE)
    check(g["t"] == "ctx84%" and g["in"] and not g["clip"] and g["title"] >= 80 and g["row1"],
          f"engineer: the context gauge reads 84% (of the 200k handover mark), whole and on screen at 390 with Voice on ({g})")
    # and with the fallback font of a cold start (#14): still one row
    b.ev("() => { const s = document.createElement('style'); s.id = 'nofont';"
         " s.textContent = '.chhdr, .chhdr * { font-family: \"Liberation Sans\", Arial, sans-serif !important }'; document.head.append(s) }")
    g = b.ev(GAUGE)
    b.ev("() => document.querySelector('#nofont').remove()")
    check(g["in"] and not g["clip"] and g["row1"] and g["title"] >= 80, f"engineer: and with the fallback font, the title 80px+ ({g})")
    b.tap(".chth .chvoice")
    # Until both are reached, not a fixed nine drags: each drag pages in 20
    # events through the fake fetch and a render, and on the one-core VPS
    # with a server and two Claude Codes beside it nine drags 700ms apart
    # fell short about one run in four (docs/ops/engineer-time.md).
    for _ in range(24):
        if b.ev("() => chat.eng.olds.length") == 2:
            break
        if b.cdp:
            b.drag(200, 200, 200, 600, steps=8)
        else:
            b.ev("() => { const l = document.querySelector('.chth .chlog'); l.scrollTop = 0; l.dispatchEvent(new Event('scroll')); }")
        b.wait(700)
    first = b.ev("() => document.querySelector('.chth .chlog').firstElementChild.textContent.slice(0, 40)")
    check(b.ev("() => chat.eng.olds.length") == 2, f"engineer: scrolling up reaches both kept conversations (top: {first!r})")
    b.boot("chats/eng-reyes-a1")
    b.wait(800)
    b.tap(".chth .chmore")
    b.tap('.chth .chsheet button[data-act="pastlist"]')
    b.tap('.chth .chsheet button[data-past="s-r1"]')
    b.wait(700)
    check(b.ev("() => chat.eng.view && chat.eng.view.session") == "s-r1" and b.ev("() => document.querySelector('.chth .chbox').disabled"),
          "earlier: one opens read-only")
    b.tap(".chth .chmore")
    acts = b.ev("() => [...document.querySelectorAll('.chth .chsheet button')].map(x => x.dataset.act)")
    check("clear" not in acts and "current" in acts, f"earlier: ⋯ has The current conversation, no Clear ({acts})")
    b.tap('.chth .chsheet button[data-act="current"]')
    b.wait(700)
    check(not b.ev("() => chat.eng.view"), "earlier: back to the current one")
    b.fake.say_queued = True
    b.tap(".chth .chbox")
    b.page.keyboard.type("do the thing")
    b.tap(".chth .chsend")
    b.wait(500)
    check("queued" in " ".join(b.last(2)) or "seat" in " ".join(b.last(2)), f"send: queued for the seat is said ({b.last(2)})")
    b.fake.say_queued = False
    b.ev("() => document.activeElement.blur()")
    b.tap(".chth .chmore")
    b.tap('.chth .chsheet button[data-act="dismiss"]')
    b.wait(600)
    check(b.url() == "chats" and b.ev("() => !!eng.list.find(x => x.name == 'reyes-a1').dismissed"), "⋯ Dismiss: dismissed, back to the list")
    # a desk keeps the status line to one line (last: the resize unsettles the pass)
    b.boot("chats/eng-mendez-b2")
    b.wait(800)
    b.page.set_viewport_size({"width": 820, "height": 1180})
    b.wait(300)
    g = b.ev(GAUGE)
    check(g["t"] == "ctx84%" and g["in"] and not g["clip"] and g["row1"], f"engineer: at 820 the context gauge reads whole, on screen ({g})")
    b.page.set_viewport_size({"width": 1280, "height": 800})
    b.wait(300)
    ws = b.ev("() => getComputedStyle(document.querySelector('.chth .chhdr .chstat')).whiteSpace")
    check(ws == "nowrap", f"engineer: on a desk the status line is one line ({ws})")
    g = b.ev(GAUGE)
    check(g["t"] == "ctx84%" and g["in"] and not g["clip"], f"engineer: on a desk the context gauge reads whole, on screen ({g})")


VOICE = [  # (said, the order expected, or None for no order)
    ("dismiss", "dismiss"), ("dismissed", "stand down"), ("dismiss it", "dismiss {*}"),
    ("dismiss reyes", "dismiss {*}"), ("dismiss engineer reyes", "dismiss engineer {*}"),
    ("dismiss the engineer reyes", "dismiss engineer {*}"), ("close the dialog", "dismiss"), ("cancel that", "dismiss"),
    ("bring back this chat", "bring back this chat"), ("bring back engineer reyes", "bring back engineer {*}"),
    ("mark read", "mark read"), ("mark all read", "mark all read"), ("clear the conversation", "clear the conversation"),
    ("earlier conversation first job", "earlier conversation {*}"), ("earlier conversations", "earlier conversations"),
    ("earlier messages", "earlier messages"), ("current conversation", "current conversation"),
    ("close the chat", "close the chat window"), ("close the chats", "close the chats"), ("read it out", "read aloud"), ("archive this chat", "archive this chat"),
    ("voice on", "voice on"), ("turn the voice off", "voice off"), ("start conversation", "start conversation"),
    ("lets talk", "start conversation"), ("end conversation", "end conversation"), ("stop the conversation", "end conversation"),
    ("stop speaking", "stop reading"),
]


def voice_pass(b):
    """vMatch for the chats' orders, and what some of them do."""
    b.boot("chats/eng-reyes-a1")
    b.wait(600)
    for said, want in VOICE:
        got = b.ev("(s) => { const w = vWords(s), m = vMatch(w, 0); return m ? [m.cmd.say, m.end === w.length] : null }", said)
        ok = (got is None and want is None) or (got and got[0] == want and got[1])
        check(ok, f"voice: {said!r} -> {want!r} (got {got})")

    def say(s):
        b.ev("(s) => voiceHeard(s)", s)
        b.wait(500)
    say("computer earlier conversation first job")
    check(b.ev("() => chat.eng.view && chat.eng.view.name") == "first job", "voice: 'earlier conversation first job' opens it")
    say("computer current conversation")
    say("computer clear the conversation")
    check(b.ev("() => !document.querySelector('.chth .chscrim').hidden && /clear/i.test(document.querySelector('.chth .chsheet').textContent)"),
          "voice: 'clear the conversation' asks, in the sheet")
    b.ev("() => chatSheet('')")
    say("computer dismiss this engineer")
    check(b.ev("() => !!eng.list.find(x => x.name == 'reyes-a1').dismissed"), "voice: 'dismiss this engineer' in their thread dismisses them")
    b.boot("chats/computer-1")
    say("computer mark read")
    say("computer archive this chat")
    say("computer bring back this chat")
    check(b.ev("() => !chatFind('computer-1').archived"), "voice: 'bring back this chat' after an archive brings it back")
    b.ev("() => { chatFind('computer-2').unread = 3; chatSave(); }")
    b.boot("chats")
    say("computer mark read")
    check(b.ev("() => chatFind('computer-2').unread") == 0, "voice: 'mark read' on the list marks every chat read")
    b.boot("chats/computer-1")
    say("computer close the chat")
    check(not b.ev("() => document.querySelector('#ov').classList.contains('on')"), "voice: 'close the chat' closes the chats")
    b.boot("chats")
    say("computer bring back engineer reyes")
    say("computer dismiss reyes")
    check(b.ev("() => !!eng.list.find(x => x.name == 'reyes-a1').dismissed") and b.ev("() => document.querySelector('#ov').classList.contains('on')"),
          "voice: 'dismiss reyes' dismisses, the chats stay")
    # other "dismiss ..." said to a dialog that is up: before 0.162.2 the
    # "dismiss" closed it (the rest left over); "dismiss {*}" now takes them
    for phrase in ("computer dismiss the chats", "computer dismiss the panel", "computer dismiss this", "computer dismiss the dialog", "computer dismiss the sheet"):
        b.boot("chats")
        say(phrase)
        up = b.ev("() => document.querySelector('#ov').classList.contains('on')")
        check(not up, f"voice: {phrase!r} closes the chats (still up: {up}; toast {b.toast()!r})")
    b.boot("")
    b.ev("() => localStorage.removeItem('lcars.deck.engkey')")
    b.boot("chats")
    say("computer dismiss the chats")
    # the prompt is a dialog of its own (lcarsPrompt): up, and saying so; the
    # closed chats' list keeps its "give the engineer key" row in #dlg
    prompt = b.ev("() => document.querySelector('#ov').classList.contains('on') && "
                  "/Engineer key/i.test((document.querySelector('#dlg') || {}).textContent || '')")
    check(not prompt, f"voice: without the engineer key, 'dismiss the chats' does not ask for the key (toast {b.toast()!r})")


class Ears:
    """Deepgram's /v1/listen, stood in for: `final` is said back when the
    socket is asked for its last words (Hold to talk), or at once with an
    UtteranceEnd after it when `utter` is set (a conversation)."""

    def __init__(self):
        self.urls, self.wss, self.utter = [], [], None

    def __call__(self, ws):
        self.urls.append(ws.url)
        self.wss.append(ws)

        def on(msg):
            if isinstance(msg, bytes):
                if self.utter:
                    t, self.utter = self.utter, None
                    ws.send(json.dumps({"type": "Results", "is_final": True, "channel": {"alternatives": [{"transcript": t}]}}))
                    ws.send(json.dumps({"type": "UtteranceEnd"}))
                return
            if json.loads(msg).get("type") == "CloseStream":
                ws.send(json.dumps({"type": "Results", "is_final": True, "channel": {"alternatives": [{"transcript": "Hello there."}]}}))
                ws.close(code=1000)
        ws.on_message(on)


def talk_pass(b):
    """Voice in a thread at a phone's size: the toggle, the talk row's pills,
    a spoken reply and its mark, hold to talk, a conversation."""
    ears = Ears()
    b.page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), ears)
    b.boot("chats/computer-1")
    vis = lambda sel: b.ev(f"() => {{ const e = document.querySelector('{sel}'); return !!(e && e.offsetParent) }}")
    check(vis(".chth .chvoice") and b.ev("() => document.querySelector('.chth .chvoice').getAttribute('aria-pressed')") == "false",
          "talk: Voice is in the header, off by default")
    check(not vis("#chtalk"), "talk: voice off, no talk row")
    b.tap(".chth .chvoice")
    check(b.ev("() => document.querySelector('.chth .chvoice').getAttribute('aria-pressed')") == "true" and vis("#talkptt") and vis("#talkconv"),
          "talk: a tap turns it on at once, and the talk row shows Hold to talk and Start conversation")
    check(b.ev("() => JSON.parse(localStorage.getItem('lcars.chat.voice')).on") is True, "talk: remembered (lcars.chat.voice, with the time)")
    check(not b.ev("() => document.querySelector('#toast').classList.contains('on')"),
          f"talk: no toast over the box, the pill and the row say it ({b.toast()!r})")
    wide = b.ev("() => [document.documentElement.scrollWidth, innerWidth, ...['#talkptt', '#talkconv', '.chth .chvoice', '.chth .chsend']"
                ".map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [Math.round(r.right), Math.round(r.height)] })]")
    check(wide[0] <= wide[1] and all(r <= wide[1] and h >= 32 for r, h in wide[2:]),
          f"talk: on a phone the pills fit the screen, tall enough to press ({wide})")
    # the thread's title stays readable beside the Voice, model and ⋯ pills (#8)
    hdr = b.ev("() => ['.chth .chhdr .chback', '.chth .chhdr .chav', '.chth .chtitle', '.chth .chvoice', '.chth .chmodel', '.chth .chmore'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [s, Math.round(r.left), Math.round(r.width), Math.round(r.top)] })")
    tw = next(w for s_, l, w, t in hdr if s_ == ".chth .chtitle")
    check(tw >= 80 and all(l + w <= 390 for s_, l, w, t in hdr), f"talk: with Voice on the title keeps its room, the pills fit ({hdr})")
    # and before Antonio has loaded (a cold or offline start): the header in
    # Arial's metrics (Liberation Sans here), as iOS's Helvetica Neue
    # fallback, is still one row - ⋯ beside the model, not under back (#14)
    one_row = """() => { const r = s => document.querySelector(s).getBoundingClientRect(), b = r('.chth .chhdr .chback'), m = r('.chth .chmore');
      return [Math.round(m.top), Math.round(b.bottom), Math.round(r('.chth .chtitle').width), Math.round(r('.chth .chhdr').height)] }"""
    b.ev("() => { const s = document.createElement('style'); s.id = 'nofont';"
         " s.textContent = '.chhdr, .chhdr * { font-family: \"Liberation Sans\", Arial, sans-serif !important }'; document.head.append(s) }")
    fb = b.ev(one_row)
    b.ev("() => document.querySelector('#nofont').remove()")
    check(fb[0] < fb[1] and fb[2] >= 80, f"talk: with the fallback font the header is one row, the title 80px+ ([⋯ top, back bottom, title, header] {fb})")
    # the home indicator's inset is under the last row, the talk row (#6);
    # Playwright's is 0, so the rule is read off the padding the CSS gives
    pad = b.ev("() => ['.chcomp', '#chtalk'].map(s => getComputedStyle(document.querySelector(s)).paddingBottom)")
    check(pad == ["0px", "6px"], f"talk: the box row gives up its bottom inset to the talk row under it ({pad})")
    # a reply, said: the computer's voice, the mark a Stop
    n = len(b.fake.log)
    b.page.fill(".chth .chbox", "what did I do today?")
    b.tap(".chth .chsend")
    b.page.wait_for_function("() => !document.querySelector('#chsay').hidden", timeout=8000)
    for _ in range(40):         # the mark is up before the request reaches the route
        said = [x[2] for x in b.fake.log[n:] if x[1] == "/say"]
        if said:
            break
        b.wait(100)
    check(said and said[0]["voice"] == "aura-2-athena-en" and "Answer to" in said[0]["text"] and said[0].get("format") == "pcm",
          f"talk: the answer is spoken in the computer's voice, as PCM ({said[:1]})")
    b.tap("#chsay")
    check(b.ev("() => document.querySelector('#chsay').hidden && !say.run"), "talk: the speaking mark is a Stop")
    # hold to talk: the pill lit while held, the words sent on letting go
    n = len(b.fake.log)
    x, y = b.mid("#talkptt")
    b.cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    b.wait(60)
    check(b.ev("() => document.querySelector('#talkptt').classList.contains('on')"), "talk: Hold to talk lights in the frame it is pressed")
    b.page.wait_for_function("() => ptt.cur && ptt.cur.open", timeout=8000)
    check(b.ev("() => document.querySelector('#pttl').textContent") == "Listening…", "talk: and says Listening… once the socket is open")
    b.cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    b.page.wait_for_function("() => !ptt.cur", timeout=8000)
    b.wait(300)
    asked = [x for x in b.fake.log[n:] if x[1] == "/chat"]
    check(("GET", "/say/token", None) in b.fake.log[n:] and asked and asked[0][2].endswith("Hello there."),
          f"talk: a token per press, and what was heard is sent as typed ({asked[:1]})")
    check(ears.urls and "model=nova-3" in ears.urls[-1], "talk: the words came from Deepgram's nova-3")
    b.ev("() => chatSayStop()")
    # a conversation: the pill on at once, an utterance sent by itself
    b.tap("#talkconv")
    check(b.ev("() => document.querySelector('#talkconv').classList.contains('on') && document.querySelector('#convl').textContent") == "End conversation",
          "talk: Start conversation turns to End conversation in the frame it is tapped")
    b.page.wait_for_function("() => conv.cur && conv.cur.open", timeout=8000)
    check(b.ev("() => document.querySelector('#convst').textContent") in ("listening", "hearing…"), "talk: and says listening")
    check("utterance_end_ms=1200" in ears.urls[-1] and "vad_events=true" in ears.urls[-1], "talk: one socket, told to say when an utterance ends")
    n = len(b.fake.log)
    ears.utter = "Yes."
    b.page.wait_for_function("() => chat.msgs.some(m => m.role === 'user' && m.text === 'Yes.')", timeout=8000)
    check(True, "talk: \"Yes.\" in a conversation is sent by itself, a word is enough")
    # the ⋯ sheet over a conversation: Esc takes the sheet, the talk goes on (QA #7)
    b.tap(".chth .chmore")
    b.wait(200)
    b.page.keyboard.press("Escape")
    b.wait(200)
    check(b.ev("() => document.querySelector('.chth .chscrim').hidden && !!conv.cur"),
          "talk: Esc with the ⋯ sheet up closes the sheet, the conversation goes on")
    b.page.keyboard.press("Escape")
    check(b.ev("() => !conv.cur && !document.querySelector('#talkconv').classList.contains('on')"), "talk: Esc ends the conversation")
    check(b.ev("() => document.querySelector('#ov').classList.contains('on')"), "talk: and leaves the thread up")
    # an engineer's: the hidden note, and their messages spoken as they come
    b.boot("chats/eng-reyes-a1")
    b.page.wait_for_function("() => chat.eng && chat.eng.off > 0", timeout=8000)
    b.tap("#talkconv")
    b.page.wait_for_function("() => conv.cur && conv.cur.open", timeout=8000)
    ears.utter = "Make the rail blue."
    b.page.wait_for_function("() => chat.msgs.some(m => m.role === 'user' && m.text === 'Make the rail blue.')", timeout=8000)
    b.wait(2000)
    sent = [m for m in b.fake.trans["s-r3"] if m["r"] == "me"][-1]["t"]
    check(sent.startswith("[conversation] Answer in one or two spoken sentences first") and sent.endswith("Make the rail blue."),
          "talk: an engineer's conversation carries the answer-first note")
    shown = b.ev("() => chat.msgs.filter(m => m.role === 'user').map(m => m.text).slice(-1)[0]")
    check(shown == "Make the rail blue.", f"talk: the note is not in the captain's bubble ({shown!r})")
    n = len(b.fake.log)
    b.fake.trans["s-r3"].append({"r": "them", "t": "Aye, Captain. Blue it is."})
    b.page.wait_for_function("() => !document.querySelector('#chsay').hidden", timeout=8000)
    for _ in range(40):         # the mark is up before the request reaches the route
        said = [x[2]["text"] for x in b.fake.log[n:] if x[1] == "/say"]
        if said:
            break
        b.wait(100)
    check(said and said[0].startswith("Aye"), f"talk: an engineer's message is spoken as it comes ({said[:2]})")
    # an earlier conversation viewed: the talk row goes, so the conversation
    # ends with it, or what is said would go to the current one (QA 2026-10-13 #5)
    b.ev("() => chatSayStop()")
    if not b.ev("() => !!conv.cur"):
        b.tap("#talkconv")
    b.page.wait_for_function("() => conv.cur && conv.cur.open", timeout=8000)
    b.ev("() => engPast('s-r1')")
    b.wait(300)
    check(b.ev("() => !conv.cur && !ptt.cur && document.querySelector('#chtalk').hidden"),
          "talk: viewing an earlier conversation ends the conversation with its row")
    b.ev("() => engPast('')")
    b.wait(300)
    # voice off: everything stops, the row goes
    b.tap(".chth .chvoice")
    check(not vis("#chtalk") and b.ev("() => !conv.cur && !say.run && document.querySelector('#chsay').hidden"),
          "talk: Voice off ends the conversation, stops the voice and hides the row")


def desk_pass(b):
    b.boot()
    # a hover lays the actions over the row: its title and last words keep
    # their width (an in-flow row of buttons narrowed them, a new ellipsis)
    geo = """() => { const r = document.querySelector('#chrows .chrow[data-id="computer-1"]');
               return [...r.querySelectorAll('.chrt b, .chrp')].map(e => { const q = e.getBoundingClientRect(); return [q.left, q.top, q.width, q.height].map(Math.round); })
                 .concat([...document.querySelectorAll('#chrows .chrowl')].map(e => Math.round(e.getBoundingClientRect().top))); }"""
    before = b.ev(geo)
    # by its avatar: the actions, once shown, cover the row's middle
    b.page.hover(b.row('data-id="computer-1"'), position={"x": 30, "y": 30})
    check(b.ev("() => !!document.querySelector('#chrows .chrowl:hover .chacts').offsetParent"), "desk: a hover shows the row's actions")
    check(b.ev(geo) == before, "desk: and nothing in the row or the list moves for them")
    check(b.ev("""() => { const l = document.querySelector('#chrows .chrowl:hover'), a = l.querySelector('.chacts').getBoundingClientRect(), q = l.getBoundingClientRect();
                   return a.right <= q.right + 1 && a.top >= q.top - 1 && a.bottom <= q.bottom + 1; }"""), "desk: over the row's right end, inside it")
    b.page.click('#chrows .chrowl:hover .chacts button[data-arch]')
    b.wait(300)
    check(b.ev("() => chatFind('computer-1').archived"), "desk: hover, click Archive archives")
    b.page.click("#toast button")
    b.wait(300)
    check(b.ev("() => !chatFind('computer-1').archived && chatFind('computer-1').unread == 2"), "desk: Undo brings it back with its unread")
    b.page.focus(b.row('data-id="computer-2"'))
    b.page.keyboard.press("Enter")
    b.wait(400)
    check(b.url() == "chats/computer-2" and b.ev("() => document.activeElement.classList.contains('chbox')"), "desk: Enter on a row opens it, box focused")
    b.page.keyboard.type("x")
    b.page.keyboard.press("Enter")
    b.wait(300)
    check(b.ev("() => document.querySelector('.chth .chbox').value") == "", "desk: Enter sends")
    b.wait(800)
    b.page.keyboard.press("Escape")
    b.wait(300)
    b.page.keyboard.press("Escape")
    b.wait(300)
    check(not b.ev("() => document.querySelector('#ov').classList.contains('on')"), "desk: Escape, Escape: thread, list, out")
    check(b.ev("() => chatInitials({ eng: { title: 'Number One' } })") == "N1" and b.ev("() => chatInitials({ eng: { title: 'Lt. Reyes' } })") == "R",
          "initials: Number One N1, Lt. Reyes R")


# the words "{word}" in the n-th answer from the end selected, as a finger or
# a mouse leaves them (the selection API: a drag on a phone is a scroll)
SELECT = """([n, word]) => { const bs = [...document.querySelectorAll('.chth .chlog > .chm.them .chbub .md')], md = bs[bs.length - n];
  const w = document.createTreeWalker(md, NodeFilter.SHOW_TEXT); let t;
  while ((t = w.nextNode())) { const i = t.data.indexOf(word); if (i >= 0) { getSelection().setBaseAndExtent(t, i, t, i + word.length); return true; } }
  return false; }"""
BOX = "() => document.querySelector('.chth .chbox').value"


def quote_pass(b):
    """Quoting at a phone's size: a selection, a whole message, two then
    send, the quotes drawn, a tap to the source; the keyboard stays up."""
    b.boot()
    b.tap(b.row('data-id="computer-2"'))
    b.wait(300)
    # a phone: nothing shows a message's row until asked
    check(not b.ev("() => [...document.querySelectorAll('.chth .chlog .chact')].some(x => x.offsetParent)"),
          "quote: no Quote/Reply rows shown at rest on a phone")
    check(b.ev(SELECT, [1, "answer 29"]), "quote: words selected in the last answer")
    b.wait(200)
    check(b.ev("() => { const r = document.querySelector('.chth .chlog > .chm.sel .chact'); return !!(r && r.offsetParent); }"),
          "quote: a selection shows its message's Quote · Reply")
    check(b.ev("() => document.querySelector('.chth .chqsel').hidden"), "quote: no floating Quote on a phone (iOS has its callout)")
    b.tap(".chth .chlog > .chm.sel .chact [data-quote]")
    check(b.ev(BOX) == "> answer 29\n\n", f"quote: the selection, as a quote and a blank line ({b.ev(BOX)!r})")
    check(b.ev("() => document.activeElement.classList.contains('chbox')"), "quote: the box focused (the keyboard up)")
    check(b.ev("() => { const b = document.querySelector('.chth .chbox'); return b.selectionStart === b.value.length; }"), "quote: the caret under it")
    check(b.ev("() => !document.querySelector('.chth .chquotes').hidden && document.querySelectorAll('.chth .chquotes .chqchip').length") == 1,
          "quote: a chip above the box mirrors it")
    b.page.keyboard.type("first answer")
    # the keyboard stays up: a tap on a message shows its row, Reply quotes it whole
    b.ev("() => { window.__blur = 0; document.querySelector('.chth .chbox').addEventListener('blur', () => window.__blur++); }")
    b.ev("() => { const bs = [...document.querySelectorAll('.chth .chlog > .chm.them')]; bs[bs.length - 2].scrollIntoView({block: 'center'}); }")
    b.wait(200)
    x, y = b.ev("""() => { const bs = [...document.querySelectorAll('.chth .chlog > .chm.them')], r = bs[bs.length - 2].querySelector('.chbub').getBoundingClientRect();
                   return [r.left + 30, r.top + 10]; }""")
    b.tap((x, y))
    check(b.ev("() => { const bs = [...document.querySelectorAll('.chth .chlog > .chm.them')]; return bs[bs.length - 2].classList.contains('act'); }"),
          "quote: a tap on a message shows its row")
    b.tap(".chth .chlog > .chm.act .chact [data-reply]")
    v = b.ev(BOX)
    check(v.startswith("> answer 29\n\nfirst answer\n\n> answer 28 lorem") and v.endswith("lorem ipsum\n\n"),
          f"reply: the message whole, after what was typed ({v[:60]!r}…{v[-12:]!r})")
    check(b.ev("() => document.activeElement.classList.contains('chbox')") and b.ev("() => window.__blur") == 0,
          f"reply: the box never lost the focus (blurs: {b.ev('() => window.__blur')})")
    check(b.ev("() => document.querySelectorAll('.chth .chquotes .chqchip').length") == 2, "reply: two quotes, two chips")
    check(b.ev("() => document.querySelector('.chth .chquotes').getBoundingClientRect().right <= innerWidth + 1"), "chips: within the screen")
    b.page.keyboard.type("second answer")
    b.tap(".chth .chsend")
    b.wait(900)
    sent = [m for (meth, path, m) in b.fake.log if path == "/chat"]
    check(sent and sent[-1].startswith("> answer 29\n\nfirst answer\n\n> answer 28") and sent[-1].endswith("second answer"),
          f"send: plain markdown as typed ({(sent or [''])[-1][:50]!r})")
    n = b.ev("() => { const me = [...document.querySelectorAll('.chth .chlog > .chm.me')].pop(); return me.querySelectorAll('.chquote').length; }")
    check(n == 2, f"log: the sent bubble draws its two quotes ({n})")
    check(b.ev("() => { const q = document.querySelector('.chth .chlog > .chm.me:nth-last-child(2) .chquote'), r = q && q.getBoundingClientRect(); "
               "return !!q && getComputedStyle(q).borderLeftWidth === '3px' && r.right <= innerWidth; }"),
          "log: a quote is a bar and within the screen")
    b.ev("() => document.activeElement.blur()")
    b.wait(300)
    b.tap(".chth .chlog > .chm.me:nth-last-child(2) .chquote:nth-of-type(3)")
    b.wait(300)
    check(b.ev("""() => { const bs = [...document.querySelectorAll('.chth .chlog > .chm.them')], el = bs.find(x => x.classList.contains('chflash'));
                   if (!el) return false; const r = el.getBoundingClientRect(), l = document.querySelector('.chth .chlog').getBoundingClientRect();
                   return el.textContent.includes('answer 28') && r.top >= l.top - 1 && r.top < l.bottom; }"""),
          "jump: a tap on the quote scrolls to the message it came from")
    check(b.ev("() => document.documentElement.scrollWidth <= innerWidth"), "phone: nothing wider than the screen")


def quote_desk_pass(b):
    """Quoting on a desk: the floating Quote by a selection, Reply on hover, >."""
    b.boot()
    b.page.click(b.row('data-id="computer-1"'), position={"x": 30, "y": 30})  # by the avatar: a hover's actions cover the middle
    b.wait(400)
    check(b.ev(SELECT, [1, "an answer"]), "desk: words selected")
    b.wait(200)
    vis = b.ev("""() => { const q = document.querySelector('.chth .chqsel'); if (q.hidden) return false;
                   const r = q.getBoundingClientRect(), s = getSelection().getRangeAt(0).getBoundingClientRect();
                   return Math.abs(r.bottom - s.top) < 60 || Math.abs(r.top - s.bottom) < 60; }""")
    check(vis, "desk: a floating Quote by the selection")
    b.page.click(".chth .chqsel")
    check(b.ev(BOX) == "> an answer\n\n" and b.ev("() => document.activeElement.classList.contains('chbox')"), f"desk: Quote fills the box, focused ({b.ev(BOX)!r})")
    check(b.ev("() => document.querySelector('.chth .chqsel').hidden"), "desk: and goes")
    b.page.keyboard.type("yes")
    tops = "() => [...document.querySelectorAll('.chth .chlog > .chm')].map(m => Math.round(m.getBoundingClientRect().top))"
    before = b.ev(tops)
    b.page.hover(".chth .chlog > .chm.me .chbub")
    check(b.ev("() => !!document.querySelector('.chth .chlog > .chm.me .chact').offsetParent"), "desk: a hover shows Quote · Reply")
    check(b.ev(tops) == before, "desk: and nothing in the log moves for it")
    check(b.ev("""() => { const m = document.querySelector('.chth .chlog > .chm.me'), r = m.querySelector('.chact').getBoundingClientRect(),
                   q = m.getBoundingClientRect(); return r.right <= q.right + 1 && r.top < q.top && r.bottom > q.top; }"""),
          "desk: the row over the message's top right corner")
    b.page.click(".chth .chlog > .chm.me .chact [data-reply]")
    check(b.ev(BOX) == "> an answer\n\nyes\n\n> first thread\n\n", f"desk: Reply on the captain's own message ({b.ev(BOX)!r})")
    b.page.click(".chth .chquotes [data-unq='1']")
    check(b.ev(BOX) == "> an answer\n\nyes", f"desk: × takes a quote out ({b.ev(BOX)!r})")
    b.page.keyboard.press("End")
    b.page.keyboard.press("Enter")
    b.wait(900)
    check(b.ev("() => document.querySelectorAll('.chth .chlog > .chm.me .chquote').length") == 1, "desk: sent, the quote drawn")
    b.ev("() => document.activeElement.blur()")
    b.page.keyboard.press(">")
    v = b.ev(BOX)
    check(v.startswith("> Answer to:") and b.ev("() => document.activeElement.classList.contains('chbox')"), f"desk: > quotes the last answer ({v[:30]!r})")
    b.page.click(".chth .chlog > .chm.me .chquote")
    b.wait(300)
    check(b.ev("() => !!document.querySelector('.chth .chlog > .chm.chflash')"), "desk: a click on a quote marks its source")


REPORT = ("Morning report.\n\nThe ship is quiet.\n\n- the **kettle** is due\n- the boiler\n  - its valve\n  - its pump\n"
          "- the dentist\n- the cat")
# the n-th <li> of the report's markdown, and its box
LI = "() => [...__R().querySelectorAll('.md li')].map(l => { const r = l.getBoundingClientRect(); return [l.textContent, r.left, r.top, r.width, r.height]; })"


def blocks_open(b):
    rep = b.srv.json("POST", "/entries", {"kind": "crew_yeoman", "title": "Things due", "content": REPORT})
    # the reports pass's reports are in the same journal: this one, by id
    b.ctx.add_init_script("window.__R = () => document.querySelector('.chth .chlog .chrep[data-rep=\"%d\"]')" % rep["id"])
    b.boot("chats")
    row = '#chrows .chrow[data-id="role-crew_yeoman"], #chrows .chrow[data-report]'
    b.page.wait_for_selector(row, timeout=8000)
    b.page.locator(row).first.click() if not b.phone else b.tap(row)
    b.page.wait_for_function("() => !!__R() && __R().querySelectorAll('.md li').length >= 6", timeout=8000)
    b.wait(300)


def blocks_pass(b):
    """Swipe to quote one block of a crew report at a phone's size: three
    bullets in turn, answered between, the keyboard up, the log still."""
    blocks_open(b)
    b.tap(".chth .chbox")
    # the bullets in the middle of the log: the chips coming up over its
    # foot must not cover the last one picked
    b.ev("() => __R().querySelectorAll('.md li')[2].scrollIntoView({block: 'center'})")
    b.wait(200)
    b.ev("() => { window.__blur = 0; document.querySelector('.chth .chbox').addEventListener('blur', () => window.__blur++); }")
    top0 = b.ev("() => document.querySelector('.chth .chlog').scrollTop")

    def swipe(i, dx=110, dy=0):
        b.wait(200)           # a finger's pause after typing: the layout settled
        li = b.ev(LI)[i]
        x, y = li[1] + 20, li[2] + min(li[4], 30) / 2
        mid = lambda: b.ev("() => { const h = document.querySelector('.chth .chqblk'); return [!h.hidden && h.classList.contains('ready'), "
                           "[...__R().querySelectorAll('.md li')].some(l => /translateX/.test(l.style.transform))]; }")
        return b.drag(x, y, x + dx, y + dy, steps=12, mid=mid)
    seen = swipe(0)
    check(seen and seen[0] and seen[1], f"swipe: the bullet follows the finger, the quote mark ready ({seen})")
    check(b.ev(BOX) == "> the kettle is due\n\n", f"swipe: that bullet quoted, alone ({b.ev(BOX)!r})")
    check(not b.ev("() => [...__R().querySelectorAll('.md li')].some(l => l.style.transform)"), "swipe: it springs back")
    check(b.ev("() => document.activeElement.classList.contains('chbox')") and b.ev("() => window.__blur") == 0, "swipe: the keyboard stays up")
    check(abs(b.ev("() => document.querySelector('.chth .chlog').scrollTop") - top0) < 2, "swipe: the log stays where it was")
    b.page.keyboard.type("answer one")
    swipe(1)
    b.page.keyboard.type("answer two")
    # the chips grew over the log's foot: scrolled to the next bullet, as a
    # captain would, and the log must not move from there
    b.ev("""() => { const l = document.querySelector('.chth .chlog'), r = __R().querySelectorAll('.md li')[4].getBoundingClientRect(),
                     lr = l.getBoundingClientRect(); if (r.bottom > lr.bottom - 8) l.scrollTop += r.bottom - lr.bottom + 40; }""")
    b.wait(200)
    top0 = b.ev("() => document.querySelector('.chth .chlog').scrollTop")
    swipe(4)
    b.page.keyboard.type("answer three")
    want = ("> the kettle is due\n\nanswer one\n\n> the boiler\n> - its valve\n> - its pump\n\nanswer two\n\n"
            "> the dentist\n\nanswer three")
    check(b.ev(BOX) == want, f"swipe: three bullets in turn, each answered under it ({b.ev(BOX)!r})")
    check(b.ev("() => document.querySelectorAll('.chth .chquotes .chqchip').length") == 3, "chips: one per quote")
    check(abs(b.ev("() => document.querySelector('.chth .chlog').scrollTop") - top0) < 2 and b.ev("() => window.__blur") == 0,
          "swipe: the third too, the log still and the keyboard up")
    before = b.ev(BOX)
    swipe(0, dx=12, dy=160)
    check(b.ev(BOX) == before, "swipe: a vertical move is a scroll, not a quote")
    b.ev("() => __R().querySelectorAll('.md li')[2].scrollIntoView({block: 'center'})")
    b.wait(200)
    swipe(0)
    check(b.ev(BOX) == before and "already quoted" in b.toast(), f"swipe: the same bullet twice is no-op, with a toast ({b.toast()!r})")
    b.tap(".chth .chquotes .chqchip:nth-child(2) .chqt")
    check(b.ev("() => document.querySelector('.chth .chbox').selectionStart") == want.index("answer two") + 10 and
          b.ev("() => window.__blur") == 0, "chips: a tap puts the caret on that answer, keyboard up")
    b.tap(".chth .chsend")
    b.wait(900)
    sent = [m for (meth, path, m) in b.fake.log if path == "/chat"]
    check(sent and sent[-1].endswith(want), f"send: the three quotes and answers, in order ({(sent or [''])[-1][-80:]!r})")
    # a selection over several paragraphs and bullets, then Quote
    b.ev("() => document.activeElement.blur()")
    b.ev("""() => { const md = __R().querySelector('.md'), ps = md.querySelectorAll('p'), li = md.querySelectorAll('li')[1];
                const t = document.createTreeWalker(li, NodeFilter.SHOW_TEXT).nextNode();
                getSelection().setBaseAndExtent(ps[0].firstChild, 8, t, 3); }""")
    b.wait(250)
    b.tap(".chth .chlog > .chm.sel .chact [data-quote]")
    v = b.ev(BOX)
    check(v.startswith("> report.") and "> The ship is quiet." in v and "the kettle is due" in v and v.rstrip().endswith("the"),
          f"selection: words over two paragraphs and two bullets quoted as selected ({v!r})")
    check(b.ev("() => document.documentElement.scrollWidth <= innerWidth"), "phone: nothing wider than the screen")


def blocks_desk_pass(b):
    """The ❝ handle in a block's margin on a desk; a selection over blocks."""
    blocks_open(b)
    li = b.ev(LI)[3]
    b.page.mouse.move(li[1] + 30, li[2] + li[4] / 2)
    b.wait(150)
    h = b.ev("() => { const h = document.querySelector('.chth .chqblk'); if (h.hidden) return null; const r = h.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; }")
    check(h is not None and h[1] <= li[1] + 2 and h[2] < li[2] + li[4] and h[3] > li[2],
          f"desk: hovering a bullet shows ❝ in its margin ({h}, li {li[1:]})")
    b.page.mouse.move((h[0] + h[1]) / 2, (h[2] + h[3]) / 2)
    b.wait(100)
    b.page.mouse.click((h[0] + h[1]) / 2, (h[2] + h[3]) / 2)
    check(b.ev(BOX) == "> its pump\n\n" and b.ev("() => document.activeElement.classList.contains('chbox')"), f"desk: the handle quotes that item ({b.ev(BOX)!r})")
    b.page.keyboard.type("ok")
    p = b.ev("() => { const r = __R().querySelector('.md p').getBoundingClientRect(); return [r.left, r.top, r.height]; }")
    b.page.mouse.move(p[0] + 30, p[1] + p[2] / 2)
    b.wait(150)
    b.page.click(".chth .chqblk")
    check(b.ev(BOX) == "> its pump\n\nok\n\n> Morning report.\n\n", f"desk: a paragraph next, under the first answer ({b.ev(BOX)!r})")
    b.ev("() => { const b = document.querySelector('.chth .chbox'); b.value = ''; b.dispatchEvent(new Event('input')); b.blur(); }")
    b.ev("""() => { const md = __R().querySelector('.md'), ps = md.querySelectorAll('p'), li = md.querySelectorAll('li')[2];
                getSelection().setBaseAndExtent(ps[1].firstChild, 0, li.firstChild, 3); }""")
    b.wait(250)
    b.page.click(".chth .chqsel")
    v = b.ev(BOX)
    check(v.startswith("> The ship is quiet.") and "the boiler" in v and v.rstrip().endswith("its"),
          f"desk: a selection over a paragraph and bullets, quoted as selected ({v!r})")


def deck_pass(b):
    """The deck's talk sheet at a phone's size: the console's thread in the
    deck's frame (0.170.0). A crew member: the sheet's layout (who, Done, one
    row of orders, the conversation the rest), a question answered and said
    in their voice with their lips moving, an order said in the box carried
    out by the deck, a cited entry opening in the console sheet, hold to
    talk, Esc; then an engineer's thread with its ⋯, and the person on the
    Chats list. The 3D view is not under test: requestAnimationFrame is
    stubbed to never call back in the deck, as software WebGL (headless)
    spends seconds a frame and starves everything else (the deck took ~150s
    to boot with frames on, ~20s without)."""
    ears = Ears()
    b.page.route_web_socket(re.compile(r"wss://api\.deepgram\.com/.*"), ears)
    entry = b.srv.json("POST", "/entries", {"kind": "personal_log", "title": "Walked by the river", "content": "Cold, clear."})
    b.ctx.add_init_script("if (/deck\\.html/.test(location.pathname)) window.requestAnimationFrame = () => 0;")
    b.page.goto(b.srv.base + "/ui/deck.html", wait_until="commit")
    # __deck names `crew` twice: the array, given last, is the one that holds
    crew = "(window.__deck && (typeof __deck.crew === 'function' ? __deck.crew() : __deck.crew) || [])"
    b.page.wait_for_function(crew + ".length > 1 && __deck.rows.size > 0", timeout=180000, polling=1000)
    b.ev("() => { window.__crew = () => " + crew + "; window.__lips = [];"
         " const l = window.lcarsDeckLips; window.lcarsDeckLips = (id, on) => { __lips.push(on); l(id, on); }; }")
    dv0 = b.ev("() => [document.querySelector('#verMark').textContent, JSON.parse(localStorage.getItem('lcars.ver') || 'null')]")
    # this browser has not booted the console yet: no number rather than a wrong one,
    # until the frame boots it (the talk sheet's check below)
    check(dv0[0] == ("v" + dv0[1] if dv0[1] else ""), f"deck: the deck's mark is the console's lcars.ver, or empty before one ({dv0})")
    b.ev("() => __deck.openTalk(__crew()[0])")
    key = b.ev("() => __deck.personaOf(__crew()[0]).key")
    fr = lambda: next(f for f in b.page.frames if f.parent_frame and "/ui/" in f.url)
    b.page.wait_for_function("() => { try { return document.querySelector('#cframe').contentWindow.chatSolo() } catch (e) { return false } }",
                             timeout=60000, polling=250)
    f = fr()
    fev = lambda js: f.evaluate(js)
    # no slide-in in the sheet: the box is where it stays from the first look (#11)
    first = fev("() => [Math.round(document.querySelector('.chth .chbox').getBoundingClientRect().left), document.querySelector('#dlg').getAnimations().length]")
    check(first[0] <= 16 and first[1] == 0, f"deck: the thread is laid out in place at once, no slide ({first})")
    # the version (0.183.5): the deck's own mark, top centre over the sheet and
    # the frame, the console's APP_VERSION; the frame's mark stays down
    dv = b.ev("""() => { const m = document.querySelector('#verMark'), r = m.getBoundingClientRect(); m.style.pointerEvents = 'auto';
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); m.style.pointerEvents = '';
      return [m.textContent, top === m, r.top >= 0 && r.bottom <= innerHeight && r.width > 0] }""")
    want = "v" + fev("() => APP_VERSION")
    check(dv == [want, True, True], f"deck: the talk sheet shows the version, on top ({dv}, want {want})")
    check(fev("() => getComputedStyle(document.querySelector('#verMark')).display") == "none",
          "deck: the console frame does not show a second one")
    check(fev("() => chat.id") == "person-" + key and fev("() => !!chat.person && chat.model") == "haiku",
          f"deck: the talk sheet is their thread in the console, person-{key}, on haiku")
    # the layout: who and Done; one row of orders; the conversation the rest
    lay = b.ev("""() => { const r = s => document.querySelector(s).getBoundingClientRect(), t = r('#talk'), fr = r('#cframe'), row = r('#talkbtns');
      return { hdr: [...document.querySelectorAll('#talk header button')].map(x => x.textContent.replace(/ · Esc/, '')),
               row: Math.round(row.height), frame: Math.round(fr.height), sheet: Math.round(t.height),
               wide: document.querySelector('#talkbtns').scrollWidth > row.width, inside: fr.top >= row.bottom - 1 && fr.bottom <= t.bottom + 1 } }""")
    check(lay["hdr"] == ["Done"], f"deck: the header is who and Done ({lay['hdr']})")
    check(lay["row"] <= 56 and lay["wide"], f"deck: the orders and Promote are one row that scrolls sideways ({lay['row']}px)")
    check(lay["inside"] and lay["frame"] >= 0.7 * lay["sheet"], f"deck: the conversation has the sheet ({lay['frame']} of {lay['sheet']}px)")
    log_h = fev("() => document.querySelector('.chth .chlog').getBoundingClientRect().height")
    parts = fev("() => ['.chhdr', '.chctx', '.chcomp', '#chtalk'].map(s => Math.round(document.querySelector('.chth ' + s).getBoundingClientRect().height))")
    check(log_h >= 0.55 * lay["frame"], f"deck: the log is most of it ({round(log_h)} of {lay['frame']}px; header, card, box, talk row {parts})")
    check(fev("() => !!document.querySelector('#talkptt').offsetParent && !!document.querySelector('#talkconv').offsetParent && !document.querySelector('.chth .chvoice').offsetParent"),
          "deck: Hold to talk and Start conversation are up; no Voice toggle (the deck's sound is)")
    tr = fev("() => ['#talkptt', '#talkconv', '.chth .chsend'].map(s => document.querySelector(s).getBoundingClientRect()).map(r => [Math.round(r.right), Math.round(r.height)])")
    w = fev("() => innerWidth")
    check(all(r <= w and h >= 32 for r, h in tr), f"deck: Send and the talk pills fit the frame, tall enough to press ({tr}, {w}px)")
    # the empty box is one line, its placeholder too: "say something to Ensign
    # Daniel Okafor" wrapped to two, the box 55px against the console's 45;
    # a longer one than any crew name is clipped, not wrapped
    ph = fev("""() => { const q = document.querySelector('.chth .chbox'), h = () => Math.round(q.getBoundingClientRect().height), p = q.placeholder, a = h();
      q.placeholder = 'say something to Lieutenant Commander Tomas Lindqvist of the Enterprise'; chatGrow(q); const b = h();
      q.placeholder = p; chatGrow(q); return [p, a, b, h()] }""")
    check(ph[0] and ph[1] <= 46 and ph[2] <= 46 and ph[3] == ph[1], f"deck: the empty box and its placeholder are one line ([placeholder, h, a long one's h, h] {ph})")
    # a question: the persona rides on it, the answer said in their voice, lips moving
    n = len(b.fake.log)
    f.fill(".chth .chbox", "hello deck")
    f.click(".chth .chsend")
    f.wait_for_function("() => chat.msgs.some(m => m.role === 'asst' && (m.parts || []).some(p => /Answer to/.test(p.s || '')))", timeout=8000)
    asked = [x[2] for x in b.fake.log[n:] if x[1] == "/chat"]
    check(asked and asked[0].startswith("[Stay in character") and asked[0].endswith("hello deck"),
          f"deck: their persona goes with the first question ({(asked or [''])[0][:40]!r})")
    for _ in range(50):
        said = [x[2] for x in b.fake.log[n:] if x[1] == "/say"]
        if said and b.ev("() => __lips.includes(true)"):
            break
        b.wait(100)
    voice = said[0]["voice"] if said else None
    check(voice and voice != "aura-2-athena-en", f"deck: the answer is said in their voice, not the computer's ({voice})")
    check(b.ev("() => __lips.includes(true)"), "deck: their lips move while it is heard (lcarsDeckLips)")
    fev("() => chatSayStop()")
    # an order said in the box: the deck carries it out, no /chat
    n = len(b.fake.log)
    f.fill(".chth .chbox", "follow me")
    f.click(".chth .chsend")
    b.wait(500)
    check(b.ev("() => (__crew()[0].order || {}).o") == "follow" and not [x for x in b.fake.log[n:] if x[1] == "/chat"],
          "deck: \"follow me\" said in the box is the deck's order, not a question")
    check("Right behind you" in fev("() => document.querySelector('.chth .chlog').textContent"), "deck: and is answered in the thread")
    fev("() => chatSayStop()")
    # hold to talk in the frame: the words heard are sent as typed
    n = len(b.fake.log)
    box = b.page.locator("#cframe").bounding_box()
    r = fev("() => { const r = document.querySelector('#talkptt').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }")
    x, y = box["x"] + r[0], box["y"] + r[1]
    b.cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    f.wait_for_function("() => ptt.cur && ptt.cur.open", timeout=8000)
    b.cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    f.wait_for_function("() => !ptt.cur", timeout=8000)
    b.wait(400)
    asked = [x[2] for x in b.fake.log[n:] if x[1] == "/chat"]
    check(asked and asked[0].endswith("Hello there."), f"deck: hold to talk in the sheet sends what was heard ({asked[:1]})")
    fev("() => chatSayStop()")
    # a cited entry opens in the deck's console sheet
    fev(f"() => lcarsDeckLine(chat.id, 'what did I log?', 'See (({entry['id']})).')")
    fev("() => chatSayStop()")
    f.click(f".chth .chlog a.eref[data-id='{entry['id']}']")
    b.wait(600)
    check(b.ev("() => !document.querySelector('#console').classList.contains('hidden') && document.querySelector('#talk').classList.contains('hidden')"),
          "deck: a cited entry opens in the deck's console sheet")
    check(not fev("() => chatSolo()"), "deck: and the frame's chat has let go of the talk")
    # Esc: a conversation first, then the sheet
    b.ev("() => __deck.openTalk(__crew()[0])")
    b.page.wait_for_function("() => document.querySelector('#cframe').contentWindow.chatSolo()", timeout=8000, polling=250)
    f.click("#talkconv")
    f.wait_for_function("() => conv.cur && conv.cur.open", timeout=8000)
    b.page.focus("#talk header button")
    b.page.keyboard.press("Escape")
    b.wait(300)
    check(fev("() => !conv.cur") and b.ev("() => !document.querySelector('#talk').classList.contains('hidden')"),
          "deck: Esc ends the conversation, the sheet stays")
    b.page.keyboard.press("Escape")
    b.wait(300)
    check(b.ev("() => document.querySelector('#talk').classList.contains('hidden')") and not fev("() => document.querySelector('#ov').classList.contains('on')"),
          "deck: a second Esc closes the sheet and the frame's chat")
    # the person is on the console's Chats list, under Aboard
    aboard = fev("() => chatRows().aboard.map(x => chatTitle(x.t))")
    check(aboard == [b.ev("() => __deck.personaOf(__crew()[0]).name")], f"deck: they are on the Chats list under Aboard ({aboard})")
    # an engineer: their thread, its ⋯, Relieve in the row; a queued message is said
    b.ev("() => { const c = __crew()[1]; __deck.place.eng[__deck.personaOf(c).key] = 'reyes-a1'; __deck.openTalk(c); }")
    b.page.wait_for_function("() => { const w = document.querySelector('#cframe').contentWindow; return w.chatSolo() && w.document.querySelector('.chth').dataset.id === 'eng-reyes-a1' }",
                             timeout=8000, polling=250)
    row = b.ev("() => [...document.querySelectorAll('#talkbtns button')].map(x => x.textContent)")
    check("Relieve of duty" in row and "Promote to engineer" not in row, f"deck: an engineer's row has Relieve ({row})")
    f.click(".chth .chmore")
    b.wait(300)
    acts = fev("() => [...document.querySelectorAll('.chth .chsheet .chopt b')].map(x => x.textContent)")
    check("Deploy" in acts and "Clear conversation" in acts, f"deck: their ⋯ has Deploy and Clear ({acts})")
    fev("() => chatSheet('')")
    b.fake.say_queued = True
    f.fill(".chth .chbox", "deck order")
    f.click(".chth .chsend")
    b.wait(1200)
    text = fev("() => document.querySelector('.chth .chlog').textContent")
    check("deck order" in text and "queued" in text, f"deck: queued for the seat is said ({text[-140:]!r})")
    b.fake.say_queued = False


def deck_desk_pass(b):
    """The deck's talk sheet at a desk (QA 2026-10-13): what is typed into a
    fresh sheet lands in its box, not on the console's keys (#3)."""
    b.ctx.add_init_script("if (/deck\\.html/.test(location.pathname)) window.requestAnimationFrame = () => 0;")
    b.page.goto(b.srv.base + "/ui/deck.html", wait_until="commit")
    crew = "(window.__deck && (typeof __deck.crew === 'function' ? __deck.crew() : __deck.crew) || [])"
    b.page.wait_for_function(crew + ".length > 1", timeout=180000, polling=1000)
    b.ev("() => { window.__crew = () => " + crew + "; }")
    b.ev("() => __deck.openTalk(__crew()[0])")
    b.page.wait_for_function("() => { try { return document.querySelector('#cframe').contentWindow.chatSolo() } catch (e) { return false } }",
                             timeout=60000, polling=250)
    f = next(x for x in b.page.frames if x.parent_frame and "/ui/" in x.url)
    b.wait(300)
    b.page.keyboard.type("hello tab")
    b.wait(300)
    got = f.evaluate("() => [document.querySelector('.chth .chbox').value, location.pathname, chatSolo()]")
    check(got[0] == "hello tab" and got[2], f"deck desk: typing into a fresh talk sheet fills its box, not the console's keys ({got})")
    vis = b.ev("() => getComputedStyle(document.querySelector('#help')).visibility")
    check(vis == "hidden", f"deck desk: the help is hidden while the talk sheet is up ({vis})")
    # Promote failing (the fake knows no such engineer: a 404) says so in the
    # sheet, after the thread is back up (#4)
    b.page.once("dialog", lambda d: d.accept())
    b.page.click("#talkpromote")
    b.page.wait_for_function("() => { try { return document.querySelector('#cframe').contentWindow.chatSolo() } catch (e) { return false } }",
                             timeout=60000, polling=250)
    b.wait(800)
    note = b.ev("() => { const n = document.querySelector('#tnote'); return [n.hidden, n.textContent, document.querySelector('#talkpromote').textContent] }")
    check(not note[0] and "could not promote" in note[1] and note[2] == "Promote to engineer",
          f"deck desk: a Promote that fails says so in the sheet ({note})")


def reports_pass(b):
    """A crew role's report opens as the role's thread, like any chat: no
    report dialog; its reports are the role's messages in the log, among
    the captain's words in the order they came; the role is read."""
    mk = lambda t, c: b.srv.json("POST", "/entries", {"kind": "crew_yeoman", "title": t, "content": c})
    old, new = mk("Two things due", "- the **kettle**"), mk("Three things due", "- the **boiler**\n- the dentist")
    b.boot("chats")
    row = b.row(f'data-report="{new["id"]}"')
    b.page.wait_for_selector(row, timeout=8000)
    check("NEW" in b.ev(f"() => document.querySelector('{row}').textContent"), "reports: an unread report's row says NEW")
    b.tap(row)
    check(b.url() == "chats/role-crew_yeoman", f"reports: the row opens the role's thread ({b.url()})")
    got = b.ev("""() => ({ dlg: !!document.querySelector('#crewout, #crewhist'), th: !!document.querySelector('.chth .chlog') && !!document.querySelector('.chth .chbox'),
      reps: [...document.querySelectorAll('.chth .chlog > .chm.them .chrep')].map(x => [x.dataset.rep, x.querySelector('.md').innerHTML]) })""")
    check(not got["dlg"] and got["th"], f"reports: a thread - log and box - not the report dialog ({got['dlg']}, {got['th']})")
    ids = [r[0] for r in got["reps"]]
    check(ids == [str(old["id"]), str(new["id"])], f"reports: both reports are the role's messages, oldest first ({ids})")
    check(got["reps"] and "<b>boiler</b>" in got["reps"][-1][1], f"reports: the latest rendered as markdown ({got['reps'][-1:]!r})")
    check(b.ev(f"() => !crewUnread('crew_yeoman', st.byId.get({new['id']}))"), "reports: opening the thread marks the role read")
    vis = b.ev(f"""() => {{ const l = document.querySelector('.chth .chlog').getBoundingClientRect(), r = document.querySelector('[data-rep="{new['id']}"]').getBoundingClientRect();
      return r.top >= l.top - 1 && r.top < l.bottom }}""")
    check(vis, "reports: the log is at the report the row named")
    # ⋯ The report: back to it in the log, no dialog
    b.tap(".chth .chmore")
    b.ev("() => document.querySelector('.chth .chlog').scrollTop = 0")
    b.tap('.chth .chsheet button[data-act="report"]')
    check(b.url() == "chats/role-crew_yeoman" and not b.ev("() => !!document.querySelector('#crewout')"),
          f"reports: ⋯ The report stays in the thread ({b.url()})")
    # the captain's words, then a newer report: it comes after them
    b.page.fill(".chth .chbox", "what about the dentist?")
    b.page.click(".chth .chsend")
    b.page.wait_for_function("() => chat.msgs.some(m => m.role === 'asst' && !m.live)", timeout=8000)
    newer = mk("Four things due", "- the cat")
    b.ev("() => syncNew()")
    b.page.wait_for_function(f"() => !!document.querySelector('[data-rep=\"{newer['id']}\"]')", timeout=8000)
    seq = b.ev("() => [...document.querySelectorAll('.chth .chlog > *')].map(k => k.querySelector('.chrep') ? 'R' + k.querySelector('.chrep').dataset.rep : k.classList.contains('me') ? 'me' : k.classList.contains('them') ? 'them' : 'sys')")
    want = ["R" + str(old["id"]), "R" + str(new["id"]), "me", "them", "R" + str(newer["id"])]
    check([x for x in seq if x != "sys"] == want, f"reports: a newer report comes after the talk it followed ({seq})")
    b.tap(".chth .chhdr .chback")
    check(b.url() == "chats" and "NEW" not in b.ev("() => document.querySelector('#chrows .chrow[data-id=\"role-crew_yeoman\"]').textContent"),
          "reports: back on the list, the role is its thread's row, read")


def links_pass(b):
    """#123 in a message is a link to the entry: a real href (a new tab, a
    long-press), a tap opens it through the app's own route, and Back is the
    thread again at the same scroll; in a crew report too."""
    e = b.srv.json("POST", "/entries", {"kind": "personal_log", "title": "The linked one", "content": "Linked."})
    rep = b.srv.json("POST", "/entries", {"kind": "crew_yeoman", "title": "Due", "content": f"- see #{e['id']}"})
    b.boot("chats")
    b.page.wait_for_function(f"() => st.byId.has({e['id']}) && st.byId.has({rep['id']})", timeout=8000)
    # one answer half way up the long thread cites the entry
    b.ev(f"() => {{ chatFind('computer-2').msgs[30].parts[0].s += ' see #{e['id']} for it'; chatSave(); }}")
    b.tap(b.row('data-id="computer-2"'))
    a = ".chth .chlog a.eref"
    href = b.ev(f"() => document.querySelector('{a}') && document.querySelector('{a}').getAttribute('href')")
    check(href and href.endswith(f"entry/{e['id']}"), f"links: #ID is an anchor with the entry's href ({href})")
    full = b.ev(f"() => document.querySelector('{a}').href")
    check(full == b.srv.base + f"/ui/entry/{e['id']}", f"links: the href resolves to the entry's url from a thread's ({full})")
    b.page.locator(a).first.scroll_into_view_if_needed()
    b.wait(200)
    top = b.ev("() => document.querySelector('.chth .chlog').scrollTop")
    end = b.ev("() => { const l = document.querySelector('.chth .chlog'); return l.scrollHeight - l.clientHeight; }")
    check(0 < top < end - 100, f"links: the link is mid-thread, not at the end ({top} of {end})")
    b.ev("() => { window.__boot = performance.timeOrigin; }")
    b.tap(a)
    check(b.url() == f"entry/{e['id']}" and b.ev(f"() => st.sel && st.sel.id") == e["id"],
          f"links: a tap opens the entry ({b.url()})")
    check(b.ev("() => window.__boot === performance.timeOrigin"), "links: through the app, no page load")
    b.page.go_back()
    b.wait(600)
    got = b.ev("() => ({ on: document.querySelector('#ov').classList.contains('on'), top: document.querySelector('.chth .chlog').scrollTop, sel: !!st.sel })")
    check(b.url() == "chats/computer-2" and got["on"] and not got["sel"], f"links: Back is the thread ({b.url()}, {got})")
    check(abs(got["top"] - top) <= 2, f"links: at the same scroll ({got['top']} vs {top})")
    # a #tag in it is a search; Back from that is the thread where it was too
    b.ev("() => { chatFind('computer-2').msgs[40].parts[0].s += ' #riverwalk'; chatSave(); }")
    b.page.go_back()
    b.wait(500)
    check(b.url() == "chats", f"links: Back again is the list ({b.url()})")
    b.tap(b.row('data-id="computer-2"'))
    t = ".chth .chlog a.wiki.tag"
    b.page.locator(t).first.scroll_into_view_if_needed()
    b.wait(200)
    top = b.ev("() => document.querySelector('.chth .chlog').scrollTop")
    b.tap(t)
    check(b.ev("() => document.querySelector('#q').value") == "#riverwalk" and
          not b.ev("() => document.querySelector('#ov').classList.contains('on')"), "links: a #tag searches the journal")
    b.page.go_back()
    b.wait(600)
    got = b.ev("() => document.querySelector('.chth .chlog').scrollTop")
    check(b.url() == "chats/computer-2" and abs(got - top) <= 2, f"links: Back from it is the thread at its scroll ({b.url()}, {got} vs {top})")
    b.ev("() => { document.querySelector('.chth .chhdr .chback').click(); }")
    b.wait(400)
    # a crew report's #ID
    b.tap(b.row(f'data-report="{rep["id"]}"'))
    rh = b.ev(f"() => {{ const x = document.querySelector('.chth .chlog .chrep a.eref'); return x && x.getAttribute('href'); }}")
    check(rh and rh.endswith(f"entry/{e['id']}"), f"links: a report's #ID is a link too ({rh})")
    b.tap(".chth .chlog .chrep a.eref")
    check(b.url() == f"entry/{e['id']}", f"links: a report's link opens the entry ({b.url()})")
    b.page.go_back()
    b.wait(600)
    check(b.url() == "chats/role-crew_yeoman", f"links: Back is the role's thread ({b.url()})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["chromium", "webkit"], default="chromium")
    ap.add_argument("--only", default="", help="comma list: swipe,thread,reports,engineer,voice,talk,desk,quote,quotedesk,blocks,blocksdesk,deck,deckdesk,links")
    o = ap.parse_args()
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-qachat-", dir=os.path.expanduser("~/.cache")))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        rig.build(binary)
    os.environ["LCARS_UI_DIR"] = str(rig.UI)
    srv = rig.Server(binary, tmp)
    passes = [("swipe", swipe_pass, True), ("thread", thread_pass, True), ("reports", reports_pass, True), ("engineer", engineer_pass, True),
              ("voice", voice_pass, True), ("talk", talk_pass, True), ("desk", desk_pass, False),
              ("quote", quote_pass, True), ("quotedesk", quote_desk_pass, False),
              ("blocks", blocks_pass, True), ("blocksdesk", blocks_desk_pass, False), ("deck", deck_pass, True),
              ("deckdesk", deck_desk_pass, False),
              # last: its crew report would be one more in the reports pass's
              ("links", links_pass, True)]
    try:
        with sync_playwright() as p:
            for name, fn, phone in passes:
                if o.only and name not in o.only.split(","):
                    continue
                print(f"--- {name} ({o.engine}, {'phone' if phone else 'desk'})", flush=True)
                b = Browser(p, srv, o.engine, phone)
                try:
                    fn(b)
                except Exception as e:  # a pass that dies is a failure, the others still run
                    check(False, f"{name}: stopped by {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                check(not b.errs, f"{name}: no page errors ({b.errs[:3]})")
                b.close()
    finally:
        srv.stop()
    print(f"\nqa_chat ({o.engine}): {checks[0]} checks, {len(fails)} failures")
    for f in fails:
        print("  - " + f)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
