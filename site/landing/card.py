#!/usr/bin/env python3
"""The share card, public/og-card.jpg: 1200x630, the size LinkedIn, X and
Slack want for a large preview, and a JPEG because their scrapers often
refuse webp. Drawn here as a small page in the landing's own palette and
face over the deck's bridge (public/shots/deck-bridge.webp), photographed
in headless Chromium and encoded by ffmpeg. Run it again after changing
the pitch or the shot:

    python3 site/landing/card.py
"""
import pathlib
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PUB = HERE / "public"

CARD = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:'Antonio';font-weight:100 900;src:url(fonts/antonio-latin.woff2) format('woff2')}
html,body{margin:0;width:1200px;height:630px;background:#000;overflow:hidden}
.bg{position:absolute;inset:0;background:url(shots/deck-bridge.webp) center/cover;opacity:.42}
.fade{position:absolute;inset:0;background:linear-gradient(90deg,#000 0%,rgba(0,0,0,.85) 45%,rgba(0,0,0,.2) 100%)}
.bar{position:absolute;left:48px;right:48px;top:40px;height:56px;display:flex;gap:10px}
.elbow{width:90px;background:#f90;border-radius:28px 0 0 0}
.badge{font:500 46px/56px Antonio;color:#f90;letter-spacing:.04em;padding:0 12px}
.p1{flex:2;height:26px;background:#fc6}.p2{flex:1;height:26px;background:#c9c;border-radius:0 13px 13px 0}
h1{position:absolute;left:48px;top:140px;width:760px;margin:0;font:500 92px/1.0 Antonio;color:#f90;text-transform:uppercase;letter-spacing:.03em}
p{position:absolute;left:52px;top:448px;width:720px;margin:0;font:28px/1.4 "Helvetica Neue",Arial,sans-serif;color:#e8e6e3}
.pill{position:absolute;left:48px;bottom:40px;padding:10px 26px;background:#c9c;color:#000;border-radius:24px;font:500 30px Antonio;text-transform:uppercase;letter-spacing:.05em}
</style></head><body><div class="bg"></div><div class="fade"></div>
<div class="bar"><span class="elbow"></span><span class="badge">LCARS</span><span class="p1"></span><span class="p2"></span></div>
<h1>A Star Trek console for your journal.</h1>
<p>Free and open source to run yourself. Hosted is coming.</p>
<span class="pill">Join the waitlist</span>
</body></html>"""

with tempfile.TemporaryDirectory(prefix="lcars-card-") as tmp:
    page_file = PUB / ".card.html"  # beside fonts/ and shots/, so their relative urls resolve
    png = pathlib.Path(tmp) / "card.png"
    page_file.write_text(CARD)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1200, "height": 630})
            pg.goto(page_file.as_uri())
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(png))
            b.close()
    finally:
        page_file.unlink()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(png), "-q:v", "3", str(PUB / "og-card.jpg")], check=True)
print(PUB / "og-card.jpg")
