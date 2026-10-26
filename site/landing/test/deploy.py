#!/usr/bin/env python3
"""deploy.sh's staging, as a dry run (~2 s; with a real wrangler ~10 s):

    python3 site/landing/test/deploy.py
    LCARS_TEST_WRANGLER=<path to a wrangler 3 bin> python3 site/landing/test/deploy.py

npx is stood in for by a script on PATH that records its arguments and the
generated config, so nothing is uploaded and no network is used; with
LCARS_TEST_WRANGLER it hands the call to that wrangler, so the dry run is
wrangler's own (`deploy --dry-run`: the bundle built, nothing uploaded).
Checked: the staged index.html has the share card's absolute URLs on the
host given (og:url, og:image, twitter:image, canonical) and no __SITE__
left; the card is a 1200x630 JPEG; the config names the database id, the
custom domain and the staged folder; the tree's public/ is untouched; a
URL for the host is refused; the explainer (on R2, off the tree) played
from $LCARS_LANDING_EXPLAINER_URL in the staged page, no mp4 of it staged
(a preview's local copy included), and the URL refused when missing, not
https, not an .mp4 or with a character a plain path does not have.
Plausible: without LCARS_LANDING_PLAUSIBLE no script of it in any page, no
plausible-init.js staged, the CSP as the tree's and the privacy note's
"no analytics"; with a domain the script.js tag with data-domain, with a
pa-<id>.js URL that tag, in every page after the init stub, the CSP's
script-src and connect-src opened to https://plausible.io alone and the
note naming Plausible; a value that is neither refused. The user manual
(public/manual/): its __VERSION__ the console's APP_VERSION in the staged
copy and kept in the tree's, its pictures staged, and the console's page
missing or without a plain X.Y.Z refused.
"""
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
FAILS = []
HOST = "lcars.example.test"
DBID = "11111111-2222-3333-4444-555555555555"


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def jpeg_size(b):
    """(width, height) from a JPEG's first SOF marker."""
    i = 2
    while i < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    return None


card = (ROOT / "public" / "og-card.jpg").read_bytes()
check(card[:3] == b"\xff\xd8\xff" and jpeg_size(card) == (1200, 630), f"og-card.jpg is a 1200x630 JPEG ({jpeg_size(card)})")
src = (ROOT / "public" / "index.html").read_text()
check(HOST not in src and "__SITE__/og-card.jpg" in src, "the tree's page has the placeholder, no host")
check('data-video="__EXPLAINER__"' in src and 'href="__EXPLAINER__"' in src and "explainer.mp4" not in src and "explainer-" not in src,
      "the tree's page plays __EXPLAINER__, no address of the cut")
CUT_URL = "https://media.example.test/lcars-landing/explainer-e238b4ba.mp4"
# the console's page, whose APP_VERSION the manual's __VERSION__ becomes
APP_PAGE = ROOT.parent.parent / "lcars-ui" / "index.html"
APP_VERSION = re.search(r'^const APP_VERSION = "([0-9.]+)";$', APP_PAGE.read_text(), re.M).group(1)

with tempfile.TemporaryDirectory(prefix="lcars-landing-deploy-") as tmp:
    tmp = pathlib.Path(tmp)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "npx.log"
    real = os.environ.get("LCARS_TEST_WRANGLER", "")
    # the stand-in npx: record, keep the config, then (optionally) run the real wrangler
    (bin_dir / "npx").write_text(f"""#!/bin/sh
printf '%s\\n' "$@" > "{log}"
while [ $# -gt 0 ]; do case "$1" in -c) cp "$2" "{tmp}/config.toml"; shift;; esac; shift; done
if [ -n "{real}" ]; then
  # drop "--yes wrangler@3" and hand the rest to the real one
  set -- $(sed -n '3,$p' "{log}")
  exec "{real}" "$@"
fi
""")
    (bin_dir / "npx").chmod(0o755)
    stage = tmp / "stage"
    # a preview's local copy of the cut, in a copy of the tree's site: never staged
    site_copy = tmp / "site"
    subprocess.run(["cp", "-R", str(ROOT), str(site_copy)], check=True)
    (site_copy / "public" / "video" / "explainer.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4000)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LCARS_LANDING_D1_ID": DBID, "LCARS_LANDING_HOST": HOST,
           "LCARS_LANDING_EXPLAINER_URL": CUT_URL, "LCARS_LANDING_APP_PAGE": str(APP_PAGE),
           "LCARS_LANDING_STAGE": str(stage), "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": "", "WRANGLER_SEND_METRICS": "false"}
    args = ["--dry-run"] + (["--outdir", str(tmp / "out")] if real else [])
    r = subprocess.run(["sh", str(site_copy / "deploy.sh"), *args], env=env, capture_output=True, text=True, timeout=120)
    check(r.returncode == 0, f"deploy.sh --dry-run exits 0 ({r.returncode}: {(r.stderr or r.stdout)[-300:]})")
    argv = log.read_text().split("\n") if log.exists() else []
    check(argv[:4] == ["--yes", "wrangler@3", "deploy", "-c"] and "--dry-run" in argv, f"it runs wrangler 3's deploy with --dry-run ({argv[:6]})")

    page = (stage / "public" / "index.html").read_text()
    site = f"https://{HOST}"
    for prop, val in [('property="og:url"', site + "/"), ('property="og:image"', site + "/og-card.jpg"),
                      ('name="twitter:image"', site + "/og-card.jpg"), ('name="twitter:card"', "summary_large_image")]:
        check(f'<meta {prop} content="{val}">' in page, f"{prop} is {val}")
    check(f'<link rel="canonical" href="{site}/">' in page, "the canonical link is absolute")
    check("__SITE__" not in page, "no placeholder left in the staged page")
    check("__SITE__" in (ROOT / "public" / "index.html").read_text(), "the tree's page is untouched")
    check((stage / "public" / "og-card.jpg").read_bytes() == card, "the card is in the staged folder")
    check(not (stage / "public" / "video" / "explainer.mp4").exists(), "no explainer mp4 staged, the preview's local copy left behind")
    check(f'data-video="{CUT_URL}"' in page and f'href="{CUT_URL}"' in page, "the page plays the cut from LCARS_LANDING_EXPLAINER_URL")
    check("__EXPLAINER__" not in page, "no __EXPLAINER__ left in the staged page")
    check(sorted(p.name for p in (stage / "public" / "video").iterdir()) == ["loop-bridge.mp4", "loop-crew.mp4"], "the video folder is the two loops")

    man = (stage / "public" / "manual" / "index.html").read_text()
    tree_man = (ROOT / "public" / "manual" / "index.html").read_text()
    check(f"For LCARS {APP_VERSION}," in man and "__VERSION__" not in man, f"the manual's version is the console's APP_VERSION ({APP_VERSION})")
    check("__VERSION__" in tree_man and APP_VERSION not in tree_man.split("</header>")[0], "the tree's manual keeps the placeholder")
    check(sorted(p.name for p in (stage / "public" / "manual" / "img").iterdir()) == sorted(p.name for p in (ROOT / "public" / "manual" / "img").iterdir()),
          "the manual's pictures are staged")

    cfg = (tmp / "config.toml").read_text()
    check(f'database_id = "{DBID}"' in cfg, "the config has the database id")
    check(re.search(r'\[\[routes\]\]\s*pattern = "' + re.escape(HOST) + r'"\s*custom_domain = true', cfg) is not None, "and the custom domain")
    check(f'directory = "{stage}/public"' in cfg and f'main = "{site_copy}/src/worker.js"' in cfg, "and the staged folder, the worker by absolute path")
    if real:
        out = tmp / "out"
        check(out.is_dir() and any(out.iterdir()), "the real wrangler built the bundle (nothing uploaded)")

    for what, bad in [("not https", CUT_URL.replace("https:", "http:")), ("not an .mp4", CUT_URL[:-4] + ".webm"),
                      ("with a #", CUT_URL.replace("explainer-", "x#explainer-")), ("with a quote", CUT_URL.replace("explainer-", 'x"explainer-')),
                      ("with an &", CUT_URL + "?a&b.mp4"), ("with a space", CUT_URL.replace("explainer-", "x explainer-"))]:
        r = subprocess.run(["sh", str(ROOT / "deploy.sh"), "--dry-run"], env={**env, "LCARS_LANDING_EXPLAINER_URL": bad}, capture_output=True, text=True)
        check(r.returncode == 2 and "LCARS_LANDING_EXPLAINER_URL" in r.stderr, f"an explainer URL {what} is refused ({r.returncode}: {r.stderr.strip()[-80:]})")
    r = subprocess.run(["sh", str(ROOT / "deploy.sh"), "--dry-run"], env={k: v for k, v in env.items() if k != "LCARS_LANDING_EXPLAINER_URL"}, capture_output=True, text=True)
    check(r.returncode != 0 and "LCARS_LANDING_EXPLAINER_URL" in r.stderr, "no LCARS_LANDING_EXPLAINER_URL is refused")

    # Plausible off (the run above): nothing of it staged
    headers_tree = (ROOT / "public" / "_headers").read_text()
    pages = {p.name: p.read_text() for p in (stage / "public").glob("*.html")}
    check(set(pages) == {"index.html", "404.html"}, f"two pages staged ({sorted(pages)})")
    check(all("plausible" not in t.lower() for t in pages.values()), "no Plausible in a page without LCARS_LANDING_PLAUSIBLE")
    check(not (stage / "public" / "plausible-init.js").exists(), "and no plausible-init.js staged")
    check((stage / "public" / "_headers").read_text() == headers_tree and "plausible" not in headers_tree, "and the CSP is the tree's, no plausible.io")
    check("No tracking, no cookies, no analytics on this page" in pages["index.html"], "and the privacy note says no analytics")
    check((ROOT / "public" / "plausible-init.js").exists() and "plausible" not in src.lower(), "the tree's page names no Plausible, the stub is beside it")

    PA = "https://plausible.io/js/pa-AbC_12-x.js"
    for value, want in [("visits.example.test", '<script defer data-domain="visits.example.test" src="https://plausible.io/js/script.js"></script>'),
                        (PA, f'<script src="{PA}" defer></script>')]:
        r = subprocess.run(["sh", str(site_copy / "deploy.sh"), "--dry-run"], env={**env, "LCARS_LANDING_PLAUSIBLE": value}, capture_output=True, text=True)
        check(r.returncode == 0, f"deploy.sh with LCARS_LANDING_PLAUSIBLE={value} exits 0 ({r.returncode}: {r.stderr[-200:]})")
        for name in ("index.html", "404.html"):
            t = (stage / "public" / name).read_text()
            check(t.count(want) == 1 and t.index('<script src="/plausible-init.js" defer></script>') < t.index(want) < t.index("</head>"),
                  f"{name} has the tag once, after the init stub, in the head ({value})")
            check(all(x not in t for x in ("__SITE__", "__EXPLAINER__")), f"no placeholder left in {name} ({value})")
        t = (stage / "public" / "index.html").read_text()
        check(t.index('src="/landing.js"') < t.index("/plausible-init.js"), "landing.js before the stub (defer order)")
        check("no analytics" not in t and "visits are counted by <a href=\"https://plausible.io/data-policy\">Plausible Analytics</a>, which sets no cookie and collects no personal data" in t,
              "the privacy note says Plausible counts visits")
        check((stage / "public" / "plausible-init.js").read_bytes() == (ROOT / "public" / "plausible-init.js").read_bytes(), "the init stub is staged")
        h = (stage / "public" / "_headers").read_text()
        csp = next(l for l in h.splitlines() if "Content-Security-Policy" in l)
        want_csp = next(l for l in headers_tree.splitlines() if "Content-Security-Policy" in l).replace(
            "script-src 'self';", "script-src 'self' https://plausible.io;").replace("connect-src 'self';", "connect-src 'self' https://plausible.io;")
        check(csp == want_csp, f"the CSP opens script-src and connect-src to https://plausible.io, nothing else ({csp.strip()[:200]})")
        check(h.replace(csp, "") == headers_tree.replace(want_csp.replace(" https://plausible.io", ""), ""), "the rest of _headers is the tree's")
    for bad in ["https://visits.example.test", "visits.example.test/x", "localhost", "a b.test", 'x".test', "x#y.test", "-x.test",
                "https://plausible.io/js/pa-x&y.js", "https://evil.test/js/pa-x.js", "http://plausible.io/js/pa-x.js"]:
        r = subprocess.run(["sh", str(ROOT / "deploy.sh"), "--dry-run"], env={**env, "LCARS_LANDING_PLAUSIBLE": bad}, capture_output=True, text=True)
        check(r.returncode == 2 and "LCARS_LANDING_PLAUSIBLE" in r.stderr, f"LCARS_LANDING_PLAUSIBLE={bad!r} is refused ({r.returncode})")

    for what, page_text in [("missing", None), ("with no APP_VERSION", "<script>const X = 1;</script>"),
                            ("with an odd one", 'const APP_VERSION = "1.2.3#x";\n')]:
        fake = tmp / "app.html"
        if page_text is None:
            fake.unlink(missing_ok=True)
        else:
            fake.write_text(page_text)
        r = subprocess.run(["sh", str(site_copy / "deploy.sh"), "--dry-run"], env={**env, "LCARS_LANDING_APP_PAGE": str(fake)}, capture_output=True, text=True)
        check(r.returncode == 1 and "APP_VERSION" in r.stderr, f"the console's page {what} is refused ({r.returncode}: {r.stderr.strip()[-80:]})")

    env["LCARS_LANDING_HOST"] = "https://" + HOST
    r = subprocess.run(["sh", str(ROOT / "deploy.sh"), "--dry-run"], env=env, capture_output=True, text=True)
    check(r.returncode == 2 and "bare host" in r.stderr, "a URL for the host is refused")

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
