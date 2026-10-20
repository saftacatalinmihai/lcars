#!/usr/bin/env python3
"""The web UI's side of GET /features (featureOff, featNote, Config's
Server section, "what is off"), in headless Chromium against a bare scratch
server - every optional setting missing, as test/features.py's first
server - serving this checkout's lcars-ui/:

  1. the owner's login: the page reads /features once, and the doors say
     the server's note in the view - Reports, the course's list, the queue
     (a dialog of its own), the chats' engineers (the list's slot), the
     editor's attach and record, a computer thread, the voice notes with
     Voice on; Config's Server section lists every feature, the off ones
     with their settings' names; W and "what is off" open the list;
  2. Number One's login (a limited one, 403): nothing is taken as off, no
     note at any door, and the Server section says it could not be read.

    python3 test/features_ui.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/features_ui.py

Nothing here touches the journal or a running server.
"""
import json
import os
import pathlib
import shutil
import sys

import killclean  # its scratch and servers go when the run is killed
import features as F

UI = F.UI
NO1 = ("no1-test", "n" * 20)
check, fails, checks = F.check, F.fails, F.checks


def page_for(browser, srv, login, phone=False):
    ctx = browser.new_context(viewport={"width": 390, "height": 844} if phone else {"width": 1280, "height": 900})
    cfg = {"base": f"http://127.0.0.1:{srv.port}", "user": login[0], "pass": login[1]}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(cfg["base"] + "/ui/")
    p.wait_for_function("typeof feat === 'object' && !feat.ask && feat.key !== ''", timeout=20000)
    return ctx, p, errs


def owner(b, srv):
    print("the owner's login: the doors say what the server lacks")
    ctx, p, errs = page_for(b, srv, (F.USER, F.PASS))
    try:
        check(p.evaluate("feat.map && feat.map.size") == 15 and p.evaluate("feat.err") == "",
              "GET /features read: 15 features")
        off = p.evaluate("featOffNames()")
        check(off == [n for n in F.ALL if n not in ("caldav", "number_one")],
              f"all off but CalDAV and Number One, whose login is given (got {off})")
        n = p.evaluate("performance.getEntriesByType('resource').filter(r => /\\/features$/.test(r.name)).length")
        check(n == 1, f"asked once (got {n})")

        p.evaluate("openReports()")
        t = p.inner_text("#dlg .featoff[data-feat=reports]")
        check("LCARS_MEDIA_ROOT" in t and "media store" in t, f"Reports: the server's note and setting in the view ({t[:60]!r})")
        p.evaluate("closeOv()")

        p.evaluate("openCourse()")
        check(p.is_visible("#dlg .featoff[data-feat=maps]") and p.is_visible("#dlg .featoff[data-feat=navigator]"),
              "the course: maps and the navigator said, the list open")
        check("LCARS_MAPY_KEY" in p.inner_text("#dlg .featoff[data-feat=maps]"), "maps names LCARS_MAPY_KEY")
        p.evaluate("closeOv()")

        p.evaluate("openQueue()")
        p.wait_for_selector("#dlg .featoff[data-feat=engineers]", timeout=3000)
        check(p.text_content("#dlgh") == "Off on this server", "the queue: a dialog of its own")
        check("LCARS_ENGINEER_KEY" in p.inner_text("#dlg .featoff"), "with the engineers' settings")
        check("off on this server" in p.inner_text("#toast"), "and a toast")
        p.click("#fo_cfg")
        p.wait_for_selector("#c_srvl .featrow", timeout=3000)
        check(True, "Server settings opens Config")
        rows = p.eval_on_selector_all("#c_srvl .featrow", "els => els.map(e => [e.classList.contains('off'), e.textContent])")
        check(len(rows) == 15 and sum(1 for o, _ in rows if o) == 13, f"the Server section: 15 rows, 13 off (got {len(rows)})")
        txt = p.inner_text("#c_srvl")
        check("13 of 15 off" in txt and "LCARS_STRAVA_CLIENT_SECRET" in txt and "LOGSEQ_TOKEN" in txt,
              "it counts and names the settings")
        check(p.is_visible("#c_vengoff .featoff[data-feat=transcription]"), "the recogniser's field: Deepgram is off")
        p.click("#c_srvr")
        check(p.inner_text("#c_srvr") in ("reading…", "Read again"), "Read again answers at once")
        p.wait_for_function("document.querySelector('#c_srvr').textContent === 'Read again'", timeout=5000)
        check("13 of 15 off" in p.inner_text("#c_srvl"), "and reads it again")
        p.evaluate("closeOv()")

        p.evaluate("chatsUp(); chatsList()")
        p.evaluate("engKeyAsk()")
        p.wait_for_selector("#dlg .featbox .featoff[data-feat=engineers]", timeout=3000)
        check(p.text_content("#dlgh") == "Chats", "the chats: the engineers' note in the list, the chats still up")
        p.evaluate("chatsOpen(chatNewThread().id)")
        p.wait_for_selector(".chfeat:not([hidden]) .featoff[data-feat=computer]", timeout=3000)
        check("LCARS_CHAT" in p.inner_text(".chfeat"), "a computer thread: the computer's note above the log")
        p.evaluate("chatVoiceSet ? chatVoiceSet(true) : null")
        p.wait_for_selector(".chfeat .featoff[data-feat=speech]", timeout=3000)
        check(p.is_visible(".chfeat .featoff[data-feat=transcription]"), "Voice on: the voices' notes too")
        p.evaluate("chatVoiceSet(false); closeOv()")

        p.evaluate("newEntry('', '', false)")
        p.evaluate("mediaRecToggle()")
        p.wait_for_selector("#ed_mfield .featoff[data-feat=media]", timeout=3000)
        check(p.evaluate("!media.rec"), "record: refused, the note in the editor's media")
        p.evaluate("leaveEntry()")

        p.keyboard.press("Escape")
        p.evaluate("closeOv(); document.activeElement && document.activeElement.blur()")
        p.keyboard.press("Shift+W")
        p.wait_for_selector("#dlg .featoff[data-feat=maps]", timeout=3000)
        check(p.text_content("#dlgh") == "Off on this server", "W: what is off")
        p.evaluate("closeOv()")
        p.evaluate("vMatch(vWords('what is off'), 0).cmd.fn()")
        p.wait_for_selector("#dlg .featoff[data-feat=strava]", timeout=3000)
        check(p.eval_on_selector_all("#dlg .featoff", "e => e.length") == 13, "'what is off': the 13, each with its note")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def limited(b, srv):
    print("Number One's login (403): everything taken as on, and said")
    ctx, p, errs = page_for(b, srv, NO1, phone=True)
    try:
        check(p.evaluate("feat.map") is None and "owner" in p.evaluate("feat.err"), "no map, the owner's login only")
        check(p.evaluate("featOffNames().length === 0 && !featureOff('media') && !featureOff('engineers')"),
              "no door shut")
        p.evaluate("openReports()")
        check(p.query_selector("#dlg .featoff") is None, "Reports: no note")
        p.evaluate("closeOv(); openCfg()")
        t = p.inner_text("#c_srvl")
        check("could not be read" in t and "owner" in t, f"the Server section says why ({t[:80]!r})")
        check(p.query_selector("#c_srvl .featrow") is None, "and lists nothing")
        w = p.evaluate("document.documentElement.scrollWidth")
        check(w <= 390, f"the phone's page no wider than the screen ({w})")
        check(errs == [], f"no page errors ({errs[:2]})")
    finally:
        ctx.close()


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("features_ui: playwright is needed")
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-features-ui"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        F.build(binary)
    d = tmp / "bare"
    (d / "home").mkdir(parents=True)
    (d / "bin").mkdir()
    env = {"HOME": str(d / "home"), "PATH": str(d / "bin"), "LCARS_EMBED": "0", "LCARS_CHAT": "0",
           "LCARS_MEDIA_ROOT": str(d / "nowhere"), "LCARS_CLAUDE_BIN": str(d / "no-claude"),
           "LCARS_UI_DIR": str(UI), "LCARS_NO1_USER": NO1[0], "LCARS_NO1_PASS": NO1[1]}
    srv = F.Server(binary, d, env)
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            owner(b, srv)
            limited(b, srv)
            b.close()
    finally:
        srv.stop()
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; the server's log under {d}")
        sys.exit(1)
    print(f"\nfeatures_ui: all {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
