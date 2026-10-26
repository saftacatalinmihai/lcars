#!/usr/bin/env python3
"""Back in the chats goes one step at a time: thread -> list -> out.

    python3 test/back.py            (~40s; a scratch server, an empty journal)

The captain's order (0.157.0): the back gesture in an open chat - the
iPhone's swipe from the left edge, Android's back, the browser's Back - goes
to the chat list, and from the list it leaves the chats. A swipe is the
browser's history.back(), which headless Chromium cannot swipe but can call,
so this walks the history at a phone's size, through every way into a
thread: the list's row, Ask, a voice order, a cold deep link (which also
needs the server to know ./chats as a page: lcars_ui_files.h), and checks
each step lands where it should and that a thread closed some other way
does not come back on the next Back. Threads are seeded into localStorage;
nothing here talks to /chat.
"""
import json
import os
import pathlib
import shutil
import sys
import killclean  # its scratch goes when the run is killed

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import offline as rig  # the scratch build and server  # noqa: E402

UI = rig.UI
check, fails, checks = rig.check, rig.fails, rig.checks

THREADS = {"seq": 3, "model": "sonnet", "list": [
    {"id": "computer-1", "at": 1, "msgs": [{"role": "user", "text": "first thread"}]},
    {"id": "computer-2", "at": 2, "msgs": [{"role": "user", "text": "second thread"}]},
    {"id": "role-crew_ops", "at": 3, "role": {"kind": "crew_ops", "title": "Operations Officer"},
     "msgs": [{"role": "user", "text": "why the disk?"}]},
]}


def run(p, srv):
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True)
    ctx.set_default_timeout(20000)
    cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
    ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) {"
                        f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.chats', {json.dumps(json.dumps(THREADS))}); }}")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    base = srv.base + "/ui/"

    def boot(url=base):
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("typeof st !== 'undefined' && st.all.length >= 0 && typeof chats !== 'undefined'")
        page.wait_for_timeout(700)

    def where():
        """'out', 'list' or 'thread:<id>': what is on screen, and the url."""
        s = page.evaluate("""() => {
          if (!document.querySelector('#ov').classList.contains('on') || !document.querySelector('.chth')) return 'out';
          const p = document.querySelector('.chth');
          return document.querySelector('#dlg').classList.contains('th-open') ? 'thread:' + p.dataset.id : 'list'; }""")
        return s, page.url.replace(srv.base, "").split("?")[0]

    def back(what):
        page.go_back(wait_until="commit")
        page.wait_for_timeout(350)
        return where()

    def expect(got, screen, url, what):
        check(got == (screen, url), f"{what}: {screen} at {url}  (got {got[0]} at {got[1]})")

    boot()
    # the Chats button, a row, then Back twice
    if page.is_visible("#bChat"):
        page.click("#bChat")
    else:
        page.evaluate("chatsList()")
    page.wait_for_timeout(300)
    expect(where(), "list", "/ui/chats", "the Chats button")
    page.click('#chrows .chrow[data-id="computer-1"]')
    page.wait_for_timeout(300)
    expect(where(), "thread:computer-1", "/ui/chats/computer-1", "a row")
    expect(back("thread"), "list", "/ui/chats", "Back from a thread")
    expect(back("list"), "out", "/ui/", "Back from the list")

    # forward and back again, and the thread's own ‹
    page.go_forward(wait_until="commit"); page.wait_for_timeout(350)
    expect(where(), "list", "/ui/chats", "Forward into the list")
    page.go_forward(wait_until="commit"); page.wait_for_timeout(350)
    expect(where(), "thread:computer-1", "/ui/chats/computer-1", "Forward into the thread")
    page.click(".chth .chhdr .chback"); page.wait_for_timeout(350)
    expect(where(), "list", "/ui/chats", "the thread's ‹")
    page.click('#chrows .chrow[data-id="role-crew_ops"]'); page.wait_for_timeout(300)
    expect(where(), "thread:role-crew_ops", "/ui/chats/role-crew_ops", "a role's row")
    page.keyboard.press("Escape"); page.wait_for_timeout(350)
    expect(where(), "list", "/ui/chats", "Escape in a thread")
    page.click("#chclose"); page.wait_for_timeout(350)
    expect(where(), "out", "/ui/", "the list's ‹")

    # Ask and a voice order: the list is put under the thread
    boot()
    page.evaluate("openChat()"); page.wait_for_timeout(350)
    s = where()
    check(s[0].startswith("thread:computer-"), f"Ask opens a computer thread  (got {s})")
    expect(back("ask"), "list", "/ui/chats", "Back from Ask's thread")
    expect(back("ask list"), "out", "/ui/", "and Back from there leaves")
    page.evaluate("VCMDS.find(c => c.say === 'new chat').fn()"); page.wait_for_timeout(350)
    s = where()
    check(s[0].startswith("thread:computer-"), f"\"new chat\" opens a thread  (got {s})")
    expect(back("new chat"), "list", "/ui/chats", "Back from it")
    expect(back("new chat list"), "out", "/ui/", "then out")

    # a thread closed some other way (an entry opened from it): Back does
    # not bring the thread or the list back over the page
    page.evaluate("openChat()"); page.wait_for_timeout(350)
    page.evaluate("closeOv()"); page.wait_for_timeout(350)
    expect(where(), "out", "/ui/", "closing from a thread")
    # both its steps came off: what is under the page is the page before
    # the chats (Ask's "new chat" walk above left the stack there)
    check(page.evaluate("history.state && history.state.prev") in (None, "", "chats"),
          "closing from a thread takes its steps off the stack")

    # a cold deep link: the server has the page, and the list goes under it
    boot(base)
    boot(srv.base + "/ui/chats/computer-2")
    expect(where(), "thread:computer-2", "/ui/chats/computer-2", "a cold load of ./chats/computer-2")
    expect(back("deep"), "list", "/ui/chats", "Back from a deep-linked thread")
    page.go_back(wait_until="commit"); page.wait_for_timeout(900)
    page.wait_for_function("typeof st !== 'undefined'")
    check(page.url.replace(srv.base, "").split("?")[0] == "/ui/", f"and Back from its list leaves the chats  ({page.url})")
    boot(srv.base + "/ui/chats")
    expect(where(), "list", "/ui/chats", "a cold load of ./chats")
    boot(srv.base + "/ui/ask")
    s = where()
    check(s[0].startswith("thread:computer-") and s[1].startswith("/ui/chats/computer-"), f"./ask lands in the computer's thread  (got {s})")

    # Number One's threads (no1-threads.md, section 13): a chip filters the
    # same conversation, not a step - Back is the list, then out.
    # The engineer routes are stood in for (the scratch server has none)
    no1 = {"name": "number-one", "title": "Number One", "status": "idle", "session": "s", "past": [], "git": {},
           "deploy": {}, "events": [], "next": 0, "first": 0,
           "threads": [{"id": "main", "name": "Main"}, {"id": "deck", "name": "Deck redesign"}]}
    page.route("**/engineer**", lambda r: r.fulfill(json=no1 if "/engineer/number-one?" in r.request.url else
                                                    {"engineers": [dict(no1, active=1)], "deploy": {}}))
    boot(base)
    page.evaluate("localStorage.setItem('lcars.deck.engkey', JSON.stringify('k-test-key-0123456789'))")
    page.evaluate("chatsList()"); page.wait_for_timeout(300)
    # opened as the list's row does (engNo1 asks /features first, which a bare server has off)
    page.evaluate("chatsOpen(engThread(NO1, NO1_TITLE).id)"); page.wait_for_timeout(900)
    expect(where(), "thread:eng-number-one", "/ui/chats/eng-number-one", "Number One's conversation")
    check(page.is_visible('.chth .chthr [data-thr="deck"]'), "his threads are chips at a phone's size")
    wide = page.evaluate("() => { const r = document.querySelector('.chth .chthr'); return [r.scrollWidth, r.clientWidth, document.documentElement.scrollWidth]; }")
    check(wide[2] <= 390, f"the chips never widen the page  ({wide})")
    page.click('.chth .chthr [data-thr="deck"]'); page.wait_for_timeout(500)
    check(page.evaluate("chat.eng.thread") == "deck", "a tap shows his deck thread")
    expect(where(), "thread:eng-number-one", "/ui/chats/eng-number-one", "a thread's view keeps the url")
    expect(back("no1 thread"), "list", "/ui/chats", "Back from a thread's filter: the list, not the other thread")
    expect(back("no1 list"), "out", "/ui/", "then out")
    page.unroute("**/engineer**")

    check(not page.query_selector("#dock"), "a phone has no chat dock")
    check(not errs, "no page error" + ("" if not errs else ": " + errs[0]))
    desk(browser, srv, cfg)
    browser.close()


def desk(browser, srv, cfg):
    """The chat dock at a desk (docs/design/chat-dock.md 1.5, 1.12): a window
    opened, minimised and closed changes neither the url nor the history;
    its full view (⤢) then Back is the list, Back again the page under it,
    with the dock as it was."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.set_default_timeout(20000)
    ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) {"
                        f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                        f"localStorage.setItem('lcars.chats', {json.dumps(json.dumps(THREADS))}); }}")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(srv.base + "/ui/", wait_until="domcontentloaded")
    page.wait_for_function("typeof dock !== 'undefined' && dock.shown")
    page.wait_for_timeout(700)
    here = lambda: (page.url.replace(srv.base, "").split("?")[0], page.evaluate("history.length"))
    h0 = here()
    page.click("#bChat"); page.wait_for_timeout(250)
    check(page.is_visible("#dock .dklist"), "the header's Chats opens the dock's list")
    page.click('#dock .dkrows .chrow[data-id="computer-1"]'); page.wait_for_timeout(300)
    check(page.is_visible('#dock .dkwin[data-id="computer-1"]'), "a row opens a window")
    page.click('#dock .dkwin[data-id="computer-1"] .dkmin'); page.wait_for_timeout(250)
    check(page.is_visible('#dock .dktab[data-tab="computer-1"]'), "─ minimises it to a tab")
    page.click('#dock .dktab[data-tab="computer-1"] .dktabo'); page.wait_for_timeout(250)
    check(page.is_visible('#dock .dkwin[data-id="computer-1"]'), "the tab opens it again")
    page.click('#dock .dkwin[data-id="computer-1"] .dkx'); page.wait_for_timeout(250)
    check(not page.query_selector('#dock .dkwin[data-id="computer-1"]'), "× closes it")
    check(here() == h0, f"open, minimise, close: the url and history.length unchanged  ({h0} -> {here()})")
    page.click('#dock .dkrows .chrow[data-id="computer-2"]'); page.wait_for_timeout(300)
    page.click('#dock .dkwin[data-id="computer-2"] .dkfull'); page.wait_for_timeout(400)
    s = page.evaluate("[document.querySelector('#dlg').classList.contains('chats'), document.querySelector('#dock').hidden]")
    check(page.url.replace(srv.base, "").split("?")[0] == "/ui/chats/computer-2" and s == [True, True],
          f"⤢: the full view at ./chats/computer-2, the dock hidden  ({page.url}, {s})")
    page.go_back(wait_until="commit"); page.wait_for_timeout(400)
    check(page.url.replace(srv.base, "").split("?")[0] == "/ui/chats", f"Back from it: the list  ({page.url})")
    page.go_back(wait_until="commit"); page.wait_for_timeout(500)
    check(page.url.replace(srv.base, "").split("?")[0] == "/ui/", f"Back again: the page under it  ({page.url})")
    check(page.is_visible('#dock .dkwin[data-id="computer-2"]') and page.is_visible("#dock .dklist"),
          "with the dock as it was: the window and the list")
    check(not errs, "no page error at a desk" + ("" if not errs else ": " + errs[0]))
    ctx.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-back-", dir=os.path.expanduser("~/.cache")))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        rig.build(binary)
    os.environ["LCARS_UI_DIR"] = str(UI)
    srv = rig.Server(binary, tmp)
    try:
        with sync_playwright() as p:
            run(p, srv)
    finally:
        srv.stop()
    print(f"\nback: {checks[0]} checks, {len(fails)} failures")
    for f in fails:
        print("  - " + f)
    if fails:
        print(f"server log kept in {tmp}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
