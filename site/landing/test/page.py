#!/usr/bin/env python3
"""The landing page in headless Chromium, at an iPhone's size (393x852) and a
desktop's (1280x800), against preview.mjs (the worker with an in-memory D1):

    python3 site/landing/test/page.py            # ~15 s
    python3 site/landing/test/page.py --shots DIR  # also keep the pictures

Checked: the pitch and the form above the fold on the phone; no page wider
than the screen; every field 16px or more (iOS zooms into a smaller one);
the form's feedback - an empty send refused on the page with no request, a
good one "Sending..." in the same frame and the button busy, then the thanks
on both forms; a server error and a cut network said where the button is,
the text kept; the no-script path's ?signup=ok; the demo and repo links; the explainer
- nothing of it loaded until play is tapped, the tap the player in the same
frame with the licensed cut (the preview's /video/explainer.mp4 where the
tree says __EXPLAINER__: R2's URL at a deploy, deploy.py; sound on), 2:24 long, never an
<audio>; the feature rows' loops muted, loaded only near the screen, and
not at all with reduced motion;
the share card's absolute URLs, the privacy note naming who keeps the list,
nothing loaded from another origin, and no script error.
"""
import pathlib
import socket
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
args = sys.argv[1:]
SHOTS = pathlib.Path(args[args.index("--shots") + 1]) if "--shots" in args else None
FAILS = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def wait(page, js, ms=5000):
    """page.wait_for_function evals a string, which the page's CSP refuses;
    so poll with evaluate (a function, which CDP runs without eval)."""
    end = time.time() + ms / 1000
    while time.time() < end:
        if page.evaluate(f"() => !!({js})"):
            return True
        time.sleep(0.05)
    raise TimeoutError(js)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


port = free_port()
srv = subprocess.Popen(["node", str(ROOT / "preview.mjs"), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
URL = f"http://127.0.0.1:{port}/"
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)

SIZES = [("phone", 393, 852, 3, True), ("desktop", 1280, 800, 1, False)]

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, w, h, scale, mobile in SIZES:
            print(f"-- {name} {w}x{h}")
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, is_mobile=mobile, has_touch=mobile)
            page = ctx.new_page()
            errors, foreign, posts, reqs = [], [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # the 500 and the cut network below are the test's own: the browser logs
            # each as a failed load, which is not the page's error
            page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append(m.text))
            page.on("request", lambda r: (not r.url.startswith(URL)) and foreign.append(r.url))
            page.on("request", lambda r: r.method == "POST" and posts.append(r.url))
            page.on("request", lambda r: reqs.append(r.url))
            page.goto(URL)
            page.wait_for_load_state("networkidle")

            # above the fold: the line, the email box and the button
            for sel, what in [("h1", "the pitch"), (".hero .signup input[type=email]", "the email box"), (".hero .signup .go", "the button")]:
                r = page.locator(sel).bounding_box()
                check(r is not None and r["y"] >= 0 and r["y"] + r["height"] <= h, f"{what} is above the fold ({r and round(r['y'] + r['height'])} <= {h})")
            check(page.evaluate("document.documentElement.scrollWidth") <= w, f"no wider than the screen ({page.evaluate('document.documentElement.scrollWidth')})")
            small = page.evaluate("""[...document.querySelectorAll('input[type=email],input[type=text]')]
              .filter(i => i.offsetParent && parseFloat(getComputedStyle(i).fontSize) < 16).length""")
            check(small == 0, "every visible field is 16px or more")
            check(page.evaluate("getComputedStyle(document.querySelector('h1')).fontFamily").startswith('"Antonio"') or "Antonio" in page.evaluate("getComputedStyle(document.querySelector('h1')).fontFamily"), "the face is Antonio")
            check(page.evaluate("document.fonts.check('500 40px Antonio')"), "Antonio has loaded")
            check(page.locator("audio").count() == 0, "no audio element")
            play = page.locator(".player a.play")
            check(play.get_attribute("href") == "/video/explainer.mp4" and page.locator(".player[data-video='/video/explainer.mp4']").count() == 1,
                  "the explainer's placeholder filled in, the link and the player alike")
            check("· 2:24 ·" in page.inner_text(".player figcaption"), "the explainer's length is the 0.296.1 cut's, 2:24")
            check(page.locator(".player video").count() == 0 and not any("/video/explainer" in u for u in reqs),
                  "the explainer is a poster, nothing of it loaded")
            if mobile:
                check(not any("/video/loop-crew" in u for u in reqs), "a phone loads no loop of a row far below")
            check(page.locator("a[href='https://public.mihai-safta.dev/lcars-demo/index.html']").count() >= 1, "Try the demo links to the demo")
            check(page.locator("a[href='https://github.com/saftacatalinmihai/lcars']").count() >= 1, "the repo is linked")
            check("Not affiliated with Paramount" in page.inner_text("footer"), "the not-affiliated line")
            check("MIT" in page.text_content(".plans") and "Coming" in page.text_content(".plans"), "self-host (MIT) beside hosted, coming")
            check("$" not in page.inner_text("body") and "€" not in page.inner_text("body"), "no price")
            check(page.locator(".signup").count() == 2, "the form again at the end")
            check("lcars@127.0.0.1" not in page.inner_text(".privacy"), "the deletion address is not made from an IP")
            ctl = page.locator(".privacy a[href='https://blog.mihaisafta.com/posts/lcars_journal/']")
            check(ctl.count() == 1 and "author of LCARS" in ctl.inner_text() and "controller" in page.inner_text(".privacy"), "the privacy note names who keeps the list, linked")
            meta = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('meta[property^="og:"],meta[name^="twitter:"]')]
              .map(m => [m.getAttribute('property') || m.getAttribute('name'), m.content]))""")
            check(meta.get("og:image") == URL + "og-card.jpg" and meta.get("twitter:image") == URL + "og-card.jpg" and meta.get("og:url") == URL
                  and meta.get("twitter:card") == "summary_large_image", f"the share card's URLs are absolute (the preview's origin) ({meta.get('og:image')})")
            check(page.request.get(URL + "og-card.jpg").headers.get("content-type") == "image/jpeg", "the card is served as a JPEG")
            if SHOTS:
                SHOTS.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(SHOTS / f"{name}-fold.png"))
                page.screenshot(path=str(SHOTS / f"{name}-full.png"), full_page=True)

            # the explainer: the tap is the player in the same frame, the licensed cut, sound on
            got = page.evaluate("""() => { document.querySelector('.player a.play').click();
              const v = document.querySelector('.player video');
              return v && {src: new URL(v.src).pathname, muted: v.muted, controls: v.controls, poster: new URL(v.poster).pathname}; }""")
            check(got == {"src": "/video/explainer.mp4", "muted": False, "controls": True, "poster": "/shots/explainer.webp"},
                  f"a tap on the poster is the licensed cut playing with sound, in the same frame ({got})")
            # the loops: each a muted inline video once its row is near the screen
            for n in ("bridge", "crew"):
                page.locator(f".shots[data-loop='/video/loop-{n}.mp4']").scroll_into_view_if_needed()
                wait(page, f"document.querySelector(\".shots[data-loop='/video/loop-{n}.mp4'] video\")")
                lv = page.evaluate(f"""() => {{ const v = document.querySelector(".shots[data-loop='/video/loop-{n}.mp4'] video");
                  return v && [new URL(v.src).pathname, v.muted, v.loop, v.playsInline, v.controls]; }}""")
                check(lv == [f"/video/loop-{n}.mp4", True, True, True, False], f"the {n} loop plays muted and inline on its row ({lv})")
            check(page.locator("audio").count() == 0 and page.locator("video").count() == 3, "three videos (the cut, two loops), no audio")
            page.evaluate("scrollTo(0, 0)")

            f = page.locator(".hero .signup")
            # an empty send: refused on the page, no request
            f.locator(".go").click()
            check(f.locator(".status").inner_text().startswith("Enter your email"), "an empty send says what is missing")
            check(page.evaluate("document.activeElement.name") == "email", "and focuses the email box")
            f.locator("input[name=email]").fill("pat@example.org")
            f.locator(".go").click()
            check("Tick the box" in f.locator(".status").inner_text(), "no consent: asked to tick the box")
            check(posts == [], "neither sent anything")

            # a server error: said where the button is, the text kept
            page.route("**/api/signup", lambda r: r.fulfill(status=500, content_type="application/json", body='{"ok":false,"error":"server","message":"x"}'))
            f.locator("input[name=use]").fill("a work log")
            f.locator("input[name=consent]").check()
            f.locator(".go").click()
            wait(page, "document.querySelector('.hero .signup .status').classList.contains('err')")
            check("wrong on our side" in f.locator(".status").inner_text() and f.locator(".go-t").inner_text().lower() == "try again", "a 500 is said at the button, Try again")
            check(f.locator("input[name=email]").input_value() == "pat@example.org" and f.locator("input[name=use]").input_value() == "a work log", "the text is kept")
            page.unroute("**/api/signup")
            # the network cut
            page.route("**/api/signup", lambda r: r.abort())
            f.locator(".go").click()
            wait(page, "document.querySelector('.hero .signup .status').textContent.includes('reach')")
            check(True, "a cut network: could not reach the server")
            page.unroute("**/api/signup")

            # a good send: Sending... in the same frame, then the thanks on both forms
            sent = page.evaluate("""() => { const f = document.querySelector('.hero .signup');
              f.querySelector('.go').click();
              return [f.classList.contains('sending'), f.querySelector('.go').disabled, f.querySelector('.go-t').textContent]; }""")
            check(sent[0] and sent[1] and sent[2].startswith("Sending"), f"the tap shows Sending… in the same frame ({sent})")
            wait(page, "document.querySelector('.hero .signup').classList.contains('done')")
            check("on the list" in f.locator(".status").inner_text(), "then the thanks")
            check(page.locator("#join2 .signup.done").count() == 1, "the form at the end says it too")

            # the no-script answer
            page.goto(URL + "?signup=ok#join")
            check(page.locator(".signup.done").count() == 2 and "signup=" not in page.url, "?signup=ok is said, and taken off the url")
            page.goto(URL + "?signup=email_invalid#join")
            check("does not look right" in page.locator(".hero .status").inner_text(), "?signup=<error> is said")
            check(page.request.get(URL + "nope").status == 404, "a missing page is a 404")

            # reduced motion: the loops stay pictures
            rm = b.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
            rp = rm.new_page()
            rp.goto(URL)
            for n in ("bridge", "crew"):
                rp.locator(f".shots[data-loop='/video/loop-{n}.mp4']").scroll_into_view_if_needed()
                rp.wait_for_timeout(300)
            check(rp.locator(".shots video").count() == 0, "reduced motion: the loops stay pictures")
            rm.close()

            check(errors == [], f"no script error ({errors[:2]})")
            check(foreign == [], f"nothing loaded from another origin ({foreign[:3]})")
            ctx.close()
        b.close()
finally:
    srv.terminate()
    out = srv.communicate(timeout=5)[0].decode(errors="replace")

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
if FAILS:
    print(out[-2000:])
sys.exit(1 if FAILS else 0)
