#!/usr/bin/env python3
"""Check the uploaded demo from where the world sees it (docs/design/demo-static.md).

    python3 lcars-ui/demo/live_check.py [--base URL] [--version X.Y.Z]

BASE is the folder's public URL ending in "/" (default $LCARS_DEMO_URL;
this box's is in CLAUDE.local.md), VERSION what the pages must say
(default the APP_VERSION of the build in ~/blog-media/lcars-demo/out).
Headless Chromium at a phone's size: index.html opens on the made-up
journal at that version, demo.js asked for by its hash, GET /kinds/roles
answered in the page, the version mark clear of the strip with an entry,
a view and the drawer open, an edit saved in the console and seen on the
deck, the deck's glbs served as model/gltf-binary and its rooms and crew
loaded, no page errors, no failed response, nothing asked of a host but
the folder (and Cloudflare's own beacon). Writes nothing but the edit, in
this browser's storage, which the run throws away.
"""
import argparse
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

OUT = pathlib.Path.home() / "blog-media" / "lcars-demo" / "out"
ROWS = "typeof st!=='undefined'&&st.all&&st.all.length>300&&!st.loading"
TITLE = "Seen on the deck"
MARK = """() => { const m = document.querySelector('#verMark'), r = m.getBoundingClientRect(),
  over = el => { const q = el.getBoundingClientRect(); return r.left < q.right && q.left < r.right && r.top < q.bottom && q.top < r.bottom; };
  return { shown: getComputedStyle(m).display !== 'none' && r.height > 0, top: Math.round(r.top),
           onText: over(document.querySelector('#demobar span')), onReset: over(document.querySelector('#demoReset')) }; }"""


def built_version():
    m = re.search(r'const APP_VERSION = "([\d.]+)"', (OUT / "index.html").read_text()) if (OUT / "index.html").is_file() else None
    return m and m.group(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=os.environ.get("LCARS_DEMO_URL"))
    ap.add_argument("--version", default=built_version())
    a = ap.parse_args()
    if not a.base or not a.version:
        sys.exit("live_check: needs --base (or $LCARS_DEMO_URL) and --version (or a build in " + str(OUT) + ")")
    base = a.base if a.base.endswith("/") else a.base + "/"
    res = []

    def ck(ok, what):
        res.append(bool(ok))
        print(("  ok   " if ok else "  FAIL ") + what, flush=True)

    def mark_clear(pg, when):
        m = pg.evaluate(MARK)
        ck(m["shown"] and not m["onText"] and not m["onReset"], f"{when}: the version mark is clear of the strip {m}")

    with sync_playwright() as p:
        br = p.chromium.launch(args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
        pg = ctx.new_page()
        errs, reqs, bad, glb = [], [], [], []
        pg.on("request", lambda r: reqs.append(r.url))
        pg.on("response", lambda r: (r.status >= 400 and bad.append(f"{r.status} {r.url}"),
                                     ".glb" in r.url and glb.append((r.status, r.headers.get("content-type")))))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))

        pg.goto(base + "index.html")
        pg.wait_for_function(ROWS, timeout=90000)
        ck(pg.evaluate("APP_VERSION") == a.version, f"index.html says {a.version}")
        dj = [u for u in reqs if "/demo.js" in u]
        ck(dj and all("?v=" in u for u in dj), f"demo.js asked for by its hash {dj}")
        kr = pg.evaluate("fetch(LCARS_DEMO.base + '/kinds/roles').then(r => r.json().then(j => [r.status, (j.roles || []).length]))")
        ck(kr[0] == 200 and kr[1] > 0, f"GET /kinds/roles answered in the page (status {kr[0]}, {kr[1]} roles)")
        newest = pg.evaluate("st.all.filter(e=>!e.deleted).map(e=>e.created_at_utc).sort().pop()")
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        ck(newest <= now, f"the newest entry {newest} is not after now {now} (UTC)")

        # not a Secret row: the demo has one, the lowest id, and it cannot be
        # edited without its password
        eid = pg.evaluate("st.all.filter(e => !e.deleted && !clsSecret(e) && e.kind === 'personal_log').map(e => e.id).sort((x, y) => x - y)[0]")
        pg.evaluate(f"select({eid})")
        pg.wait_for_timeout(800)
        mark_clear(pg, "an entry open")
        pg.evaluate("openTasks()")
        pg.wait_for_timeout(500)
        mark_clear(pg, "a view open")
        pg.evaluate("closeOv()")
        pg.wait_for_timeout(300)
        pg.evaluate("openDrawer()")
        pg.wait_for_timeout(500)
        mark_clear(pg, "the filters drawer open")
        pg.evaluate("closeDrawer()")
        pg.wait_for_timeout(300)

        pg.click("#rwmode button[data-v=edit]")
        # the body arrives after the row: until then the box is read-only (setForm)
        pg.wait_for_function("!document.querySelector('#content').readOnly", timeout=10000)
        pg.fill("#content", TITLE)
        pg.wait_for_timeout(100)
        pg.click("#edchip")
        pg.wait_for_function("document.querySelector('#edchip').dataset.s === 'saved'", timeout=10000)
        ck(pg.evaluate(f"st.byId.get({eid}).content") == TITLE, f"entry {eid} edited and saved in the console")

        pg.goto(base + "deck.html", wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_function("window.__deck && window.__deck.crewReady()", timeout=300000)
        pg.wait_for_timeout(2000)
        t = pg.evaluate(f"(window.__deck.rows.get({eid})||{{}}).content")
        ck(t == TITLE, f"the deck has the edit ({t!r})")
        d = pg.evaluate("""() => { const d = window.__deck; let n = 0; d.scene.traverse(o => { if (o.isMesh) n++; });
            return {rows: d.rows.size, pins: d.place.pins.length, crew: (typeof d.crew === 'function' ? d.crew() : d.crew).length, meshes: n}; }""")
        ck(d["crew"] > 5 and d["pins"] >= 6 and d["meshes"] > 50, f"the deck's rooms and crew loaded {d}")
        ck(glb and all(g == (200, "model/gltf-binary") for g in glb), f"{len(glb)} glbs, all 200 model/gltf-binary")
        ck(not errs, f"no page errors {errs[:3]}")
        ck(not bad, f"no failed responses {bad[:3]}")
        ck(all(u.startswith(base) or u.startswith(("data:", "blob:")) or "cloudflareinsights" in u or "/cdn-cgi/rum" in u
               for u in reqs), "nothing asked of a host but the folder (and Cloudflare's beacon)")
        br.close()
    print(f"live_check: {sum(res)}/{len(res)} checks passed")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
