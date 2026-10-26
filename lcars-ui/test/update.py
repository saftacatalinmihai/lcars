#!/usr/bin/env python3
"""The app's own update, end to end: a newer version on the server is seen,
fetched into the service worker's cache, and reloaded into, once.

    python3 test/update.py        (~40s; LCARS_TEST_BIN=<binary> skips the build)

The QuickJS suite (tests.js, "the app's own updates") covers the compare, the
mark, the settings row's buttons and the edit saved on the way, with the
fetch and the worker stubbed. This is what only a real browser and the real
server show: that the check is one ranged GET of index.html (206, a
kilobyte) that the worker leaves to the network, that sw.js's "refresh"
puts the new shell in its cache, that the page reloads into it exactly once,
and that offline nothing is asked and nothing is shown.

A scratch server is built from the lcars-release compile line (to a temp path,
never ./lcars), run on an empty database, and serves a copy of lcars-ui/
(LCARS_UI_DIR) whose index.html the test then rewrites as a deploy would.
Nothing here touches lcars.db or the checkout's lcars-ui/.
"""
import json
import os
import pathlib
import re
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

import killclean  # its scratch goes when the run is killed
import offline
from offline import USER, PASS, build, check, checks, fails

UI = pathlib.Path(__file__).resolve().parent.parent
NEW = "9.9.9"
# The floating version (#verMark) over a covered screen: shown only while the
# page is stale (body[data-stale]), and then amber (the design pass, Words)
MARK = """() => { const m = document.querySelector('#verMark'), cs = getComputedStyle(m);
  const p = document.createElement('i'); p.style.color = 'var(--amber)'; document.body.appendChild(p);
  const amber = getComputedStyle(p).color; p.remove();
  return { stale: document.body.dataset.stale === 'on', shown: cs.display !== 'none' && m.getBoundingClientRect().height > 0,
           amber: cs.display !== 'none' && cs.color === amber }; }"""


def page_checks(srv, ui):
    cfg = json.dumps({"base": srv.base, "user": USER, "pass": PASS})
    origin = srv.base + "/ui/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) "
                            "localStorage.setItem('lcars.cfg', %s);" % json.dumps(cfg))
        page = ctx.new_page()
        page.on("pageerror", lambda e: fails.append("page error: " + str(e)))
        if os.environ.get("LCARS_TEST_CONSOLE"):
            page.on("console", lambda m: print("  console:", m.text))
        # every request for the page's file, and every load of the page
        asks, loads = [], []
        page.on("request", lambda r: asks.append(r) if r.url.endswith("/ui/index.html") else None)
        page.on("load", lambda _: loads.append(time.time()))

        print("-- under the service worker --")
        page.goto(origin)
        page.wait_for_function("!st.loading", timeout=20000)
        page.evaluate("navigator.serviceWorker.ready")
        page.reload()
        page.wait_for_function("navigator.serviceWorker.controller !== null && !st.loading",
                               timeout=15000)
        old = page.evaluate("APP_VERSION")

        print("-- the check: one ranged GET --")
        del asks[:]
        with page.expect_response(lambda r: r.url.endswith("/ui/index.html")) as resp:
            page.evaluate("updCheck(true)")
        r = resp.value
        page.wait_for_function("upd.server !== ''", timeout=10000)
        check(page.evaluate("upd.server") == old, "the server's version is read: " + old)
        check(len(asks) == 1, "one request for it (%d)" % len(asks))
        check(asks and asks[0].headers.get("range") == "bytes=0-1023", "a ranged one, the first kilobyte")
        check(r.status == 206, "answered 206 (%d)" % r.status)
        size = int(r.headers.get("content-length") or -1)
        check(0 < size <= 1024, "with 1024 bytes at most (%d)" % size)
        check(not r.from_service_worker, "by the server, not the worker's cache")
        check(not page.evaluate("document.querySelector('#appVer').classList.contains('upd')"),
              "the same version: no mark")
        page.evaluate("openMore()")
        check(page.evaluate(MARK) == {"stale": False, "shown": False, "amber": False},
              "and no floating version over a covered screen (%s)" % page.evaluate(MARK))
        page.evaluate("closeOv()")

        print("-- a deploy: the server has " + NEW + " --")
        html = (ui / "index.html").read_text(encoding="utf-8")
        html = re.sub(r'const APP_VERSION = "[^"]+"', 'const APP_VERSION = "%s"' % NEW, html, count=1)
        (ui / "index.html").write_text(html, encoding="utf-8")
        page.evaluate("updCheck(true)")
        page.wait_for_function("upd.server === %s" % json.dumps(NEW), timeout=10000)
        check(page.evaluate("document.querySelector('#appVer').classList.contains('upd')"),
              "the header's version is marked")
        check(page.evaluate("APP_VERSION") == old, "the page itself is still the old one")
        # stale: the floating mark over a covered screen, amber; Later puts
        # off the offer (the header's arrow) and leaves the mark
        page.evaluate("openMore()")
        check(page.evaluate(MARK) == {"stale": True, "shown": True, "amber": True},
              "stale: the floating version shows, amber (%s)" % page.evaluate(MARK))
        page.evaluate("updLater()")
        check(not page.evaluate("document.querySelector('#appVer').classList.contains('upd')"),
              "Later takes the header's offer off")
        check(page.evaluate(MARK) == {"stale": True, "shown": True, "amber": True},
              "and leaves the mark: behind is a fact (%s)" % page.evaluate(MARK))
        page.evaluate("closeOv()")
        page.evaluate("updOpen()")
        # Update lives in What's new since 0.325.0 (updOpen opens it)
        btn = '#wn_upd [data-act="update"]'
        check(page.text_content(btn).strip() == "Update to v" + NEW, "What's new offers Update to v" + NEW)

        print("-- Update --")
        n = len(loads)
        page.click(btn)
        page.wait_for_function("typeof APP_VERSION === 'string' && APP_VERSION === %s" % json.dumps(NEW),
                               timeout=30000)
        page.wait_for_function("!st.loading", timeout=20000)
        time.sleep(2)                       # a second reload would have started by now
        check(len(loads) - n == 1, "the page reloaded once (%d)" % (len(loads) - n))
        check(page.evaluate("APP_VERSION") == NEW, "into v" + NEW)
        check(page.evaluate("navigator.serviceWorker.controller !== null"), "still under the worker")
        cached = page.evaluate("caches.match('./').then(r => r && r.text())") or ""
        check('const APP_VERSION = "%s"' % NEW in cached, "the worker's cached shell is the new one")
        check(not page.evaluate("document.querySelector('#appVer').classList.contains('upd')"),
              "no mark: nothing newer")
        page.evaluate("updPaint(); openMore()")
        check(page.evaluate(MARK)["shown"] is False, "and no floating version (%s)" % page.evaluate(MARK))
        page.evaluate("closeOv()")

        print("-- offline: nothing --")
        ctx.set_offline(True)
        del asks[:]
        page.evaluate("hideToast(); upd.at = 0; updCheck(false); updCheckSoon()")
        time.sleep(1.5)
        check(not asks, "the server is not asked (%d)" % len(asks))
        check(not page.evaluate("document.querySelector('#toast').classList.contains('on')"),
              "and nothing is said")
        ctx.set_offline(False)
        browser.close()


def main():
    scratch = pathlib.Path(os.environ.get("LCARS_TEST_TMP") or pathlib.Path.home() / ".cache")
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-upd-", dir=scratch))
    ui = tmp / "ui"
    shutil.copytree(UI, ui, ignore=shutil.ignore_patterns("test", "demo", "report"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        build(binary)
    os.environ["LCARS_UI_DIR"] = str(ui)
    srv = offline.Server(binary, tmp)
    try:
        page_checks(srv, ui)
    finally:
        srv.stop()
    print("\nupdate: %d checks, %d failures" % (checks[0], len(fails)))
    for f in fails:
        print("  - " + f)
    if fails:
        print("server log kept in", tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
