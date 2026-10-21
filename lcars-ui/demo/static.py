#!/usr/bin/env python3
"""Build the public demo: the console and the deck on a made-up journal, as
plain files for a static host (docs/design/demo-static.md).

    python3 lcars-ui/demo/static.py [OUT]     # default ~/blog-media/lcars-demo/out

OUT is written whole each time: everything the two pages load (the vendor
scripts, the deck's models and bakes, the crew, the icons, the display face),
the made-up journal as journal.json (demo/fixture.py's public()), its
pictures under api/media/, and demo.js (demo/static.js), the server in the
page, which the build loads first in both pages - that and nothing else is
what puts them in demo mode. No server, no rewrites: every view is reached
from index.html itself (a hash, not a path), so a reload lands on a file.

Every file the host may cache is asked for by its content: the pages name
each one with ?v=<a hash of its bytes> (the deck's models and textures,
whose names the deck builds as it runs, through a table in deck.html and
three.js's URL modifier), and the journal's pictures carry the hash in
their names. The host's CDN keeps scripts, styles, fonts and pictures for
hours and cannot be purged, while HTML and JSON go uncached: so a changed
file is a new URL the moment the new page is, and an unchanged one keeps
its cached copy.

Nothing of ours goes out: the build scrubs the one host name the pages carry
(the fallback for file://, which a demo never takes) and then reads every
text file it wrote for a host, an address, a name or a key, and fails if it
finds one. It never uploads; that is a step of its own, with the bucket's
token (the doc says how).
"""
import base64
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import sys
import zlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
UI = HERE.parent
REPO = UI.parent
sys.path.insert(0, str(HERE))
import fixture  # noqa: E402

DEFAULT_OUT = pathlib.Path.home() / "blog-media" / "lcars-demo" / "out"
MARK = ".lcars-demo"                  # what says a folder is ours to remake
DIRS = ["vendor", "deck", "crew"]     # the pages' assets, whole
FILES = ["icon-192.png", "icon-512.png", "apple-touch-icon.png"]
FONTS = ["antonio-latin.woff2", "antonio-latin-ext.woff2"]

# What must never be in the output: a host on a tailnet, a key, and our
# own addresses and names - those from the export's pattern file
# (scripts/export-audit.local.txt, the private names, so never in this
# file), when this box has one.
FORBIDDEN = [
    (r"\.ts\.net\b", "a tailnet host"),
    (r"sk-ant-[A-Za-z0-9_-]{8}", "an Anthropic key"),
    (r"apikey=[A-Za-z0-9_-]{12}", "a Mapy key"),
    (r"(?i)authorization:\s*basic\s+[A-Za-z0-9+/=]{12}", "a login"),
    (r"LCARS_ENGINEER_KEY\s*=\s*\S", "the engineers' key"),
]
PRIVATE = UI.parent / "scripts" / "export-audit.local.txt"
if PRIVATE.is_file():
    for line in PRIVATE.read_text(encoding="utf-8").splitlines():
        parts = [x.strip() for x in line.split(" :: ")]
        # the ones the demo has always held to; the page still carries
        # the rest (the child kinds, the home town) until they are swept
        if len(parts) >= 2 and parts[0] in ("the tailnet host", "the VPS's address", "the captain's name", "the captain's surname"):
            FORBIDDEN.append((parts[1], parts[0]))


# ------------------------------------------------------------- the pages
TABLE_MARK = "<!-- the deck's versions -->\n"


def page(name, ver):
    """index.html or deck.html, made the demo's: demo.js first, the face
    from the folder rather than Google, no host of ours, and every file of
    the folder it names asked for by its content (ver: path -> hash)."""
    s = (UI / name).read_text(encoding="utf-8")

    def swap(old, new, n=1):
        nonlocal s
        if s.count(old) != n:
            sys.exit(f"static.py: {name} has {s.count(old)} of {old!r}, expected {n}: the page changed under the build")
        s = s.replace(old, new)

    # first in <head>, before the page's own scripts: LCARS_DEMO and the
    # fetch it answers have to exist before anything asks
    swap('<meta charset="utf-8">\n',
         '<meta charset="utf-8">\n<meta name="lcars-demo" content="a made-up journal; edits stay in this browser">\n'
         '<script src="demo.js"></script>\n')
    swap('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Antonio:wght@400;600;700&display=swap">\n',
         '<link rel="stylesheet" href="fonts/antonio.css">\n')
    if name == "deck.html":
        # the deck builds its models' and textures' names as it runs
        # (DECK_MODELS + room + ".glb"), so they cannot be swapped here: the
        # table goes in the page, which is never cached, and every three.js
        # loader (all on the default manager) asks for the versioned URL.
        # A mark for now: the pass below would version the table's own keys.
        swap('<script src="demo.js"></script>\n', TABLE_MARK + '<script src="demo.js"></script>\n')
        swap('import * as THREE from "three";\n',
             'import * as THREE from "three";\nTHREE.DefaultLoadingManager.setURLModifier(window.LCARS_DEMO_ASSET);\n')
    # every other name of a file of ours, quoted whole in the page
    # ("demo.js", "./vendor/three-….js", "vendor/leaflet-1.9.4.css", the icons)
    names = sorted(ver, key=len, reverse=True)
    rx = re.compile(r'(["\'])(\./)?(' + "|".join(map(re.escape, names)) + r')\1')
    s = rx.sub(lambda m: f"{m[1]}{m[2] or ''}{m[3]}?v={ver[m[3]]}{m[1]}", s)
    if name == "deck.html":
        table = {k: v for k, v in ver.items() if k.startswith(("deck/", "crew/"))}
        swap(TABLE_MARK, '<script>window.LCARS_DEMO_V=' + json.dumps(table, separators=(",", ":")) + ';\n'
             'window.LCARS_DEMO_ASSET=function(u){var h=window.LCARS_DEMO_V[String(u).replace(/^\\.\\//,"")];'
             'return h?u+(String(u).indexOf("?")<0?"?":"&")+"v="+h:u;};</script>\n')
    return s


def digest(data):
    """A file's version: 10 hex of its SHA-256, enough to tell builds apart."""
    return hashlib.sha256(data).hexdigest()[:10]


# What the pages are asked for again on every visit (the host caches neither
# HTML nor JSON), and so need no version: the pages, the journal, our mark.
UNVERSIONED = {"index.html", "deck.html", "journal.json", MARK}


FONT_CSS = """/* Antonio (SIL OFL 1.1), the LCARS display face, from the folder rather
   than Google Fonts: the demo asks nothing of anyone else. Variable: one
   file per script covers 400 to 700. */
@font-face{font-family:'Antonio';font-style:normal;font-weight:100 900;font-display:swap;
  src:url(antonio-latin-ext.woff2{ext}) format('woff2');
  unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF}
@font-face{font-family:'Antonio';font-style:normal;font-weight:100 900;font-display:swap;
  src:url(antonio-latin.woff2{latin}) format('woff2');
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
"""

# start_url and the share target are the folder's index.html, not "./": a
# bucket serves no index document for a directory
MANIFEST = {
    "name": "LCARS Journal (demo)", "short_name": "LCARS demo",
    "description": "LCARS, a Star Trek-style personal journal, on a made-up journal.",
    "start_url": "index.html", "scope": "./", "display": "standalone",
    "background_color": "#000000", "theme_color": "#000000",
    "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
}


# ----------------------------------------------------------- the pictures
# Drawn here, so nothing in the demo was ever anyone's photograph.
def png(img):
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].astype(np.uint8).tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def disc(img, cx, cy, r, col):
    h, w, _ = img.shape
    yy, xx = np.ogrid[:h, :w]
    a = np.clip(r + 0.5 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2), 0, 1)[..., None]
    img[:] = img * (1 - a) + np.array(col) * a


def line(img, x0, y0, x1, y1, col, alpha=0.5):
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    xs = np.linspace(x0, x1, n).round().astype(int)
    ys = np.linspace(y0, y1, n).round().astype(int)
    ok = (xs >= 0) & (xs < img.shape[1]) & (ys >= 0) & (ys < img.shape[0])
    img[ys[ok], xs[ok]] = img[ys[ok], xs[ok]] * (1 - alpha) + np.array(col) * alpha


def draw(what, w=800, h=500):
    rnd = np.random.default_rng(1701)
    img = np.zeros((h, w, 3), float)
    if what == "graph":
        # the link graph, settled: clusters of pages and the mentions between
        img[:] = (8, 8, 14)
        centres = [(250, 200), (540, 170), (420, 360), (650, 360)]
        pts = []
        for i, (cx, cy) in enumerate(centres):
            for _ in range(9 + i * 2):
                a, r = rnd.uniform(0, 6.283), rnd.uniform(15, 85)
                pts.append((cx + r * np.cos(a), cy + r * np.sin(a), i))
        for j, (x, y, c) in enumerate(pts):
            for k in rnd.choice(len(pts), 2, replace=False):
                x2, y2, c2 = pts[k]
                if c2 == c or rnd.random() < 0.12:
                    line(img, x, y, x2, y2, (120, 110, 150), 0.35)
        cols = [(255, 153, 0), (204, 153, 204), (153, 204, 255), (255, 204, 102)]
        for x, y, c in pts:
            disc(img, x, y, rnd.uniform(4, 9), cols[c])
    else:
        # the canal at dusk: sky, sun, the far bank, water with the light on it
        t = np.linspace(0, 1, h)[:, None, None]
        sky = (1 - t) * np.array([62, 34, 92]) + t * np.array([250, 150, 70])
        img[:] = sky
        horizon = int(h * 0.62)
        disc(img, w * 0.62, horizon - 30, 38, (255, 224, 160))
        x = 0
        while x < w:
            bw, bh = rnd.integers(30, 90), rnd.integers(30, 120)
            img[horizon - bh:horizon, x:x + bw] = (28, 18, 40)
            x += bw
        water = np.linspace(0, 1, h - horizon)[:, None, None]
        img[horizon:] = (1 - water) * np.array([150, 80, 70]) + water * np.array([30, 20, 50])
        for y in range(horizon + 4, h, 7):
            half = 40 + (y - horizon) * 0.9
            line(img, w * 0.62 - half * rnd.uniform(0.3, 1), y, w * 0.62 + half * rnd.uniform(0.3, 1), y,
                 (255, 210, 150), 0.45)
    return png(np.clip(img, 0, 255))


# --------------------------------------------------------- the star chart
# Vectors of our own for the chart (index.html's "stellar cartography"): a
# hashed bag of words, the kind weighted in, quantised to int8 as the
# server's are. Near enough to meaning for a chart to cluster by subject;
# search by meaning stays off, since a question would need the same model.
DIM = 64


def vector(r):
    words = re.findall(r"[a-z][a-z']{2,}", (r["title"] + " " + r["content"]).lower())
    v = np.zeros(DIM)
    for tok in words + ["kind:" + r["kind"]] * 6:
        d = hashlib.md5(tok.encode()).digest()
        v[d[0] % DIM] += 1 if d[1] & 1 else -1
        v[d[2] % DIM] += 0.5 if d[3] & 1 else -0.5
    n = np.linalg.norm(v) or 1
    return base64.b64encode((v / n * 127).round().clip(-127, 127).astype(np.int8).tobytes()).decode()


# ---------------------------------------------------------------- the build
def build(out):
    out = out.resolve()
    if out == REPO or REPO in out.parents:
        sys.exit(f"static.py: {out} is inside the repo; the demo is built outside it")
    if out.exists():
        if any(out.iterdir()) and not (out / MARK).exists():
            sys.exit(f"static.py: {out} has files the build did not write (no {MARK}); not touching it")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARK).write_text("written by lcars-ui/demo/static.py; remade whole on every build\n")

    shutil.copy(HERE / "static.js", out / "demo.js")
    for d in DIRS:
        shutil.copytree(UI / d, out / d)
    for f in FILES:
        shutil.copy(UI / f, out / f)
    # what names another file carries its version, so is written after it
    q = lambda f: "?v=" + digest((out / f).read_bytes())
    man = dict(MANIFEST, icons=[dict(i, src=i["src"] + q(i["src"])) for i in MANIFEST["icons"]])
    (out / "manifest.webmanifest").write_text(json.dumps(man, indent=1) + "\n")
    (out / "fonts").mkdir()
    for f in FONTS:
        shutil.copy(HERE / "assets" / f, out / "fonts" / f)
    (out / "fonts" / "antonio.css").write_text(FONT_CSS.replace("{ext}", q("fonts/antonio-latin-ext.woff2"))
                                               .replace("{latin}", q("fonts/antonio-latin.woff2")))

    rows = fixture.public()
    built = fixture.NOW.strftime("%Y-%m-%d")
    media = []
    for mid, eid, fname, what in fixture.MEDIA:
        # the name carries the version: the console builds a picture's url
        # from its path (mediaUrl), and the path comes in the uncached journal
        data = draw(what)
        rel = f"media/demo/e{eid}-{mid}-{digest(data)}.png"
        p = out / "api" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        at = next(r for r in rows if r["id"] == eid)["created_at_utc"]
        media.append({"id": mid, "entry_id": eid, "path": rel, "mime": "image/png", "bytes": len(data),
                      "name": fname, "created_at_utc": at})
    # a Secret row has no vector: the demo's sealed one (fixture.py) neither
    live = [r for r in rows if not r["deleted"] and not r.get("seal")]
    mark = max(r["last_modified_at_utc"] for r in rows)
    journal = {"built": built, "rows": rows, "media": media,
               "embeddings": {"model": "demo-bag-of-words", "dim": DIM, "mark": mark,
                              "rows": [[r["id"], vector(r)] for r in live]}}
    (out / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, separators=(",", ":")))

    # the pages last, when every file they name is there to be hashed
    ver = {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob("*"))
           if p.is_file() and p.name not in UNVERSIONED and p.relative_to(out).parts[0] != "api"}
    for name in ("index.html", "deck.html"):
        (out / name).write_text(page(name, ver), encoding="utf-8")
    return journal


def audit(out):
    """Every text file written, read for anything of ours."""
    found = []
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.suffix not in (".html", ".js", ".mjs", ".json", ".css", ".webmanifest", ".txt"):
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        for rx, what in FORBIDDEN:
            m = re.search(rx, s)
            if m:
                found.append(f"{p.relative_to(out)}: {what} ({s[max(0, m.start() - 20):m.end() + 20]!r})")
    return found


def size(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def main():
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    j = build(out)
    bad = audit(out)
    if bad:
        print("static.py: refusing the build, it carries something of ours:", *bad, sep="\n  ", file=sys.stderr)
        shutil.rmtree(out)
        sys.exit(1)
    files = [p for p in out.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f"built {out}: {len(files)} files, {size(total)}; journal {len(j['rows'])} rows "
          f"(built {j['built']}), {len(j['media'])} pictures; nothing of ours found")
    print("biggest:")
    for p in sorted(files, key=lambda p: -p.stat().st_size)[:10]:
        print(f"  {size(p.stat().st_size):>8}  {p.relative_to(out)}")


if __name__ == "__main__":
    main()
