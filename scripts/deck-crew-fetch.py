#!/usr/bin/env python3
"""Download the Quaternius packs the deck's crew are built from (CC0, the
free "Standard" zips on itch.io) into the model cache, and unzip them there
side by side, as scripts/deck-crew-assets.mjs reads them:

    python3 scripts/deck-crew-fetch.py [DIR]    # default ~/.cache/lcars-deck-models/quaternius

Nothing here is committed: the zips and what they unzip to stay in the
cache, and lcars-ui/crew/LICENSE.txt names each pack and its page.

itch.io's free downloads need no account, only the page's own steps: the
page's csrf token (with its cookie) posted to /download_url gives a
download page, and the token posted to /file/<upload> on it a signed link
that lives a minute. Each step is one request a few seconds apart: itch.io
answers 429 to anything faster, and a 429 is waited out and retried.
"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# a browser's: itch.io's front door answers a script's own name with a 429
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
# (page slug, the upload's file name): what the crew use of each
PACKS = [
    ("universal-base-characters", "Universal Base Characters[Standard].zip"),
    ("universal-animation-library", "Universal Animation Library[Standard].zip"),
    ("universal-animation-library-2", "Universal Animation Library 2[Standard].zip"),
]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    for attempt in range(6):
        time.sleep(3)
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with opener.open(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            time.sleep(20 * (attempt + 1))


def fetch(root, slug, name):
    zp = os.path.join(root, name)
    if not os.path.exists(zp):
        page = f"https://quaternius.itch.io/{slug}"
        html = get(page).decode()
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        dl = json.loads(get(page + "/download_url", {"csrf_token": csrf}))["url"]
        html = get(dl).decode()
        # the uploads in page order, each a data-upload_id before its name
        ids = re.findall(r'data-upload_id="(\d+)"', html)
        names = re.findall(r'class="name" title="([^"]+)"|title="([^"]+)" class="name"', html)
        names = [a or b for a, b in names]
        if name not in names:
            sys.exit(f"{slug}: no upload called {name} (the page has {names})")
        up = ids[names.index(name)]
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        url = json.loads(get(f"{page}/file/{up}?source=game_download", {"csrf_token": csrf}))["url"]
        part = zp + ".part"
        with open(part, "wb") as w:
            w.write(get(url))
        os.replace(part, zp)  # last, so an interrupted download is fetched again
        print(f"[fetch] {name}: {os.path.getsize(zp) // 1024} kB")
    out = os.path.join(root, name[:-4])
    if not os.path.isdir(out):
        subprocess.run(["unzip", "-q", "-o", zp, "-d", out + ".part"], check=True)
        # a zip holding one folder of its own name unzips to that folder
        inner = os.listdir(out + ".part")
        src = os.path.join(out + ".part", inner[0]) if inner == [name[:-4]] else out + ".part"
        os.rename(src, out)
        if src != out + ".part":
            os.rmdir(out + ".part")
        print(f"[fetch] unzipped {out}")


if __name__ == "__main__":
    cache = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(cache, "lcars-deck-models", "quaternius")
    os.makedirs(root, exist_ok=True)
    for slug, name in PACKS:
        fetch(root, slug, name)
