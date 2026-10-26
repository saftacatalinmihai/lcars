#!/usr/bin/env python3
"""Open questions (openQuestions in index.html), in headless Chromium at a
phone's size against a scratch server with Number One's login:

  1. Number One asks (a task_no1 written with his own login, as no1.py
     escalate does) and the crew asks (a task_crew); the Chats button
     counts them and the Chats list's top row opens the view, a card each,
     newest first, the context folded with more;
  2. a draft typed and left by Later survives a reload;
  3. Answer and close: the server's row has the answer at the top of its
     content and done 1 (the real PATCH and its if_modified), the card
     leaves; Undo puts the content back and opens it again;
  4. the answer box is 16px (no iOS zoom), the page no wider than the phone;
  5. a question's references to entries are links: a bare #id in its title
     and its context, [[a title]] and ((id)) each open the entry, and Back
     (the browser's, the reader's ‹, Escape) brings the questions again with
     the card scrolled into view as it was and its typed draft in its box; a
     #id the journal does not hold is drawn gone, says so, and goes nowhere;
  6. Later snoozes one (0.299.0): its choices, the card gone and the Chats
     button's count down at once, kept across a reload in the Later row,
     opened there to answer, Now bringing it back.

    python3 test/questions_ui.py               # builds the server first (~30s)
    python3 test/questions_ui.py --shots DIR   # and keeps the snooze's phone screenshots
    LCARS_TEST_BIN=/path/to/lcars python3 test/questions_ui.py

Nothing here touches the journal or a running server.
"""
import json
import os
import pathlib
import re
import shutil
import sys

import killclean  # its scratch and servers go when the run is killed
import features as F

UI = F.UI
NO1 = ("no1-test", "n" * 20)
check, fails, checks = F.check, F.fails, F.checks
DRAFT = "Ship it, after the phone check."


def post(srv, login, body):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    c.request("POST", "/entries", json.dumps(body), {"Authorization": F.auth(*login), "Content-Type": "application/json"})
    r = c.getresponse()
    doc = json.loads(r.read().decode() or "{}")
    c.close()
    if r.status not in (200, 201):
        sys.exit(f"questions_ui: POST {body['kind']} answered {r.status}: {doc}")
    return doc["id"]


def row(srv, i):
    st, body = srv.get(f"/entries/{i}")
    return json.loads(body) if st == 200 else {}


def run(b, srv, qa, qb):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": F.USER, "pass": F.PASS}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    try:
        p.goto(cfg["base"] + "/ui/")
        p.wait_for_function("typeof oqCount === 'function' && st.all.length >= 2 && oqCount() === 2", timeout=20000)
        check("2" in p.inner_text("#bChat"), f"the Chats button counts both ({p.inner_text('#bChat')!r})")
        p.evaluate("chatsUp(); chatsList()")
        p.wait_for_selector("#chrows [data-oqv]", timeout=3000)
        first = p.evaluate("document.querySelector('#chrows .chrow').dataset.oqv")
        check(first == "1", "the Chats list's first row is Open questions")
        p.tap("#chrows [data-oqv]")
        p.wait_for_selector("#oqrows .oqcard", timeout=3000)
        check(p.text_content("#dlgh") == "Open questions" and "/questions" in p.url + p.evaluate("location.hash"),
              f"the view, with its url ({p.url})")
        ids = p.eval_on_selector_all("#oqrows .oqcard", "els => els.map(e => +e.dataset.oqid)")
        check(ids == [qb, qa], f"a card each, newest first (got {ids})")
        ca = f'#oqrows [data-oqid="{qa}"]'
        check("Number One" in p.inner_text(ca + " .oqmeta"), "Number One's says who asks")
        check(p.query_selector(ca + " .oqctx.fold") is not None, "a long context folded")
        p.tap(ca + " [data-oqmore]")
        check(p.query_selector(ca + " .oqctx.fold") is None, "more unfolds it")
        fs = p.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{ca} .oqa')).fontSize)")
        check(fs >= 16, f"the answer box is 16px or more ({fs})")
        w = p.evaluate("document.documentElement.scrollWidth")
        check(w <= 390, f"no wider than the phone ({w})")

        p.fill(ca + " .oqa", DRAFT)
        p.tap(ca + " [data-oqlater]")
        p.reload()
        p.wait_for_function("typeof oqCount === 'function' && oqCount() === 2", timeout=20000)
        p.evaluate("openQuestions()")
        p.wait_for_selector(ca + " .oqa", timeout=3000)
        check(p.input_value(ca + " .oqa") == DRAFT, "Later: the draft survives a reload")

        p.tap(ca + " [data-oqdone]")
        p.wait_for_function(f"!document.querySelector('{ca}')", timeout=5000)
        r = row(srv, qa)
        c = r.get("content", "")
        check(re.match(r"Answer \(captain, \d{4}-\d\d-\d\d \d\d:\d\d\): " + re.escape(DRAFT) + "\n\n", c) is not None,
              f"the server's row: the answer first ({c[:70]!r})")
        check(c.endswith("My recommendation: ship.\n" + "more\n" * 8), "the context kept under it")
        check(r.get("done_bool") == 1, "and done")
        check(p.evaluate("oqCount()") == 1, "the count drops")
        p.wait_for_selector("#toast.on .tact", timeout=3000)
        check(p.text_content("#toast .tact").strip() == "Undo", "a toast with Undo")
        p.click("#toast .tact")
        p.wait_for_selector(ca, timeout=5000)
        r = row(srv, qa)
        check(r.get("done_bool") == 0 and r.get("content") == "Sato built them.\nMy recommendation: ship.\n" + "more\n" * 8,
              "Undo: open again, the content as it was")
        check(p.input_value(ca + " .oqa") == DRAFT, "the answer back in its box")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def snooze(b, srv, qd, shots):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": F.USER, "pass": F.PASS}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    cd = f'#oqrows .oqcard[data-oqid="{qd}"]'
    shot = lambda name: shots and p.screenshot(path=str(pathlib.Path(shots) / f"{name}.png"))
    badge = lambda: p.evaluate("chatUnreadTotal() + engAnswerCount()")
    try:
        p.goto(cfg["base"] + "/ui/")
        p.wait_for_function(f"typeof oqCount === 'function' && st.byId.has({qd})", timeout=20000)
        n0, b0 = p.evaluate("oqCount()"), badge()
        p.evaluate("openQuestions()")
        p.wait_for_selector(cd, timeout=5000)
        p.evaluate(f"document.querySelector('{cd}').scrollIntoView({{block: 'start'}})")
        p.tap(cd + " [data-oqlater]")
        check(p.query_selector(f'[data-oqsnz="{qd}:am"]') is not None, "Later: its choices under the card")
        p.evaluate(f"document.querySelector('{cd} .oqpickl').scrollIntoView({{block: 'end'}})")
        shot("1-later-choices")
        p.tap(f'[data-oqsnz="{qd}:3h"]')
        check(p.query_selector(cd) is None, "a choice: the card leaves the list")
        check(p.evaluate("oqCount()") == n0 - 1 and badge() == b0 - 1, "out of the count and the Chats button's")
        check("later, until" in p.inner_text("#toast"), "a toast says until when, with Undo")
        p.evaluate("document.querySelector('#oqrows').scrollTop = 1e6")
        shot("2-snoozed-toast")
        p.reload()
        p.wait_for_function(f"typeof oqCount === 'function' && st.byId.has({qd})", timeout=20000)
        check(p.evaluate("oqCount()") == n0 - 1, "still snoozed after a reload")
        p.evaluate("openQuestions()")
        p.wait_for_selector("#oqrows .oqlrow", timeout=5000)
        check("Later" in p.text_content("#oqrows .oqlrow") and p.text_content("#oqrows .oqlrow .oqlc") == "1",
              "the Later row at the bottom, its count a fact of its own")
        p.tap("#oqrows [data-oqlrow]")
        p.tap(f'#oqrows [data-oqpeek="{qd}"]')
        p.wait_for_selector(f'.oqlrow .oqcard[data-oqid="{qd}"] [data-oqc]', timeout=3000)
        check(p.evaluate("oqCount()") == n0 - 1, "opened in the Later row, still snoozed")
        p.evaluate("document.querySelector('#oqrows .oqlrow').scrollIntoView({block: 'start'})")
        shot("3-later-row-open")
        w = p.evaluate("document.documentElement.scrollWidth")
        check(w <= 390, f"no wider than the phone ({w})")
        p.tap(f'#oqrows [data-oqwake="{qd}"]')
        check(p.query_selector(cd) is not None and p.evaluate("oqCount()") == n0, "Now: back in the list, counted")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def links(b, srv, qc, target):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": F.USER, "pass": F.PASS}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    cc = f'#oqrows [data-oqid="{qc}"]'
    try:
        p.goto(cfg["base"] + "/ui/")
        p.wait_for_function(f"typeof oqCount === 'function' && st.byId.has({qc}) && st.byId.has({target})", timeout=20000)
        p.evaluate("openQuestions()")
        p.wait_for_selector(cc + " .oqctx", timeout=5000)
        check(p.query_selector(cc + " .oqmeta a") is None, "the card's own #id stays plain")
        check(p.query_selector(f'{cc} .oqq a.eref[data-id="{target}"]') is not None, "the title's #id is an entry link")
        n = p.eval_on_selector_all(f'{cc} .oqctx a.eref[data-id="{target}"]', "l => l.length")
        check(n == 2, f"the context's #id and ((id)) are entry links ({n})")
        check(p.query_selector(cc + " .oqctx a.wiki") is not None, "[[a title]] a wiki link")
        check(p.query_selector(cc + ' .oqctx a.eref.gone[data-id="999999999"]') is not None, "a #id not in the journal drawn gone")
        p.fill(cc + " .oqa", DRAFT)

        def leave(sel, how, nth=0):
            p.evaluate(f"document.querySelector('{cc}').scrollIntoView()")
            top = p.evaluate("$('#oqrows').scrollTop")
            p.locator(sel).nth(nth).tap()
            p.wait_for_function(f"st.sel && st.sel.id === {target} && !$('#ov').classList.contains('on')", timeout=5000)
            check(True, f"{sel.split(' ', 2)[-1]}: the entry opens")
            if how == "back":
                p.go_back()
            elif how == "button":
                check(p.text_content("#bBack").strip() == "‹ Questions", f"the reader's ‹ says Questions ({p.text_content('#bBack')!r})")
                p.tap("#bBack")
            else:
                p.keyboard.press("Escape")
            p.wait_for_selector(cc + " .oqa", timeout=5000)
            p.wait_for_timeout(300)
            back = p.evaluate("$('#oqrows').scrollTop")
            check(top > 0 and abs(back - top) <= 2, f"{how}: the questions again, scrolled as left ({back} of {top})")
            check(p.input_value(cc + " .oqa") == DRAFT, f"{how}: the draft still in its box")
            check("/questions" in p.url, f"{how}: the questions' url ({p.url})")

        leave(f'{cc} .oqq a.eref[data-id="{target}"]', "back")
        leave(f'{cc} .oqctx a.eref[data-id="{target}"]', "button")
        leave(f'{cc} .oqctx a.eref[data-id="{target}"]', "escape", 1)  # the ((id))
        leave(f"{cc} .oqctx a.wiki", "back")

        u = p.url
        p.tap(cc + ' .oqctx a.eref.gone')
        p.wait_for_selector("#toast.on", timeout=3000)
        check("not in the journal" in p.inner_text("#toast"), f"the gone link toasts ({p.inner_text('#toast')!r})")
        check(p.url == u and p.query_selector(cc) is not None, "and goes nowhere")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
    if shots:
        pathlib.Path(shots).mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("questions_ui: playwright is needed")
    # "lcars-features-": the name engineer.py's TEST_TMP_RE reaps when killed
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-features-oq"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        F.build(binary)
    d = tmp / "srv"
    (d / "home").mkdir(parents=True)
    (d / "bin").mkdir()
    env = {"HOME": str(d / "home"), "PATH": str(d / "bin"), "LCARS_EMBED": "0", "LCARS_CHAT": "0",
           "LCARS_MEDIA_ROOT": str(d / "nowhere"), "LCARS_CLAUDE_BIN": str(d / "no-claude"),
           "LCARS_UI_DIR": str(UI), "LCARS_NO1_USER": NO1[0], "LCARS_NO1_PASS": NO1[1]}
    srv = F.Server(binary, d, env)
    try:
        qa = post(srv, NO1, {"kind": "task_no1", "title": "Ship the deck's new pins?", "created_at_utc": "2026-10-19 08:00:00",
                             "content": "Sato built them.\nMy recommendation: ship.\n" + "more\n" * 8})
        qb = post(srv, (F.USER, F.PASS), {"kind": "task_crew", "title": "The NAS is 95% full: prune the tapes?",
                                          "created_at_utc": "2026-10-19 09:00:00", "content": "ops found it"})
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            run(b, srv, qa, qb)
            # the links' part: a page to name, asks enough to scroll, the oldest linking
            target = post(srv, (F.USER, F.PASS), {"kind": "note", "title": "Deck pins plan", "content": "the plan",
                                                  "created_at_utc": "2026-10-18 07:00:00"})
            qc = post(srv, NO1, {"kind": "task_no1", "title": f"Pins as in #{target}?", "created_at_utc": "2026-10-18 08:00:00",
                                 "content": f"See #{target}, [[Deck pins plan]] and (({target})).\nNot #999999999."})
            for i in range(4):
                post(srv, (F.USER, F.PASS), {"kind": "task_crew", "title": f"Filler ask {i}?",
                                             "created_at_utc": f"2026-10-18 1{i}:00:00", "content": "line\n" * 3})
            links(b, srv, qc, target)
            qd = post(srv, NO1, {"kind": "task_no1", "title": "Rename the lounge on deck 10?", "created_at_utc": "2026-10-19 10:00:00",
                                 "content": "Ten Forward's sign reads Lounge.\nQ1: Rename it Ten Forward?\nOptions: A) yes, now B) after the refit\n"
                                            "Recommendation: A\nQ2: Light the windows at night?"})
            snooze(b, srv, qd, shots)
            b.close()
    finally:
        srv.stop()
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; the server's log under {d}")
        sys.exit(1)
    print(f"\nquestions_ui: all {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
