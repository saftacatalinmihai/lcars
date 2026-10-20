#!/usr/bin/env python3
"""Download Poly Haven models (CC0) for pack.py: each ASSET's glTF at one
resolution into DIR/ASSET/ASSET.gltf with its textures, and a LICENSE.txt
naming the licence, the source page and the authors (from the API).

    python3 scripts/deck-models/fetch_polyhaven.py DIR ASSET [ASSET...] [--res 1k]

Nothing here is committed: DIR is a cache (build.sh keeps it in
~/.cache/lcars-deck-packs). Poly Haven's API: https://api.polyhaven.com
(no key; it asks for a User-Agent that names the caller).
"""
import json
import os
import sys
import urllib.request

UA = {"User-Agent": "lcars-deck-models/1 (personal project; scripts/deck-models)"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def fetch(root, asset, res):
    d = os.path.join(root, asset)
    gltf = os.path.join(d, asset + ".gltf")
    if os.path.exists(gltf) and os.path.exists(os.path.join(d, "LICENSE.txt")):
        return
    files = json.loads(get(f"https://api.polyhaven.com/files/{asset}"))
    info = json.loads(get(f"https://api.polyhaven.com/info/{asset}"))
    g = files["gltf"][res]["gltf"]
    os.makedirs(d, exist_ok=True)
    for rel, f in g.get("include", {}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as w:
            w.write(get(f["url"]))
    with open(os.path.join(d, "LICENSE.txt"), "w") as w:
        w.write(f"{info['name']} ({asset}) by {', '.join(info.get('authors', {}))}\n"
                f"https://polyhaven.com/a/{asset}\n"
                "Licence: CC0 1.0 Universal (public domain), https://creativecommons.org/publicdomain/zero/1.0/\n")
    # last, so an interrupted download is fetched again
    with open(gltf, "wb") as w:
        w.write(get(g["url"]))
    print(f"[fetch] {asset}: {len(g.get('include', {})) + 1} files")


if __name__ == "__main__":
    a = sys.argv[1:]
    res = "1k"
    if "--res" in a:
        i = a.index("--res")
        res = a[i + 1]
        del a[i:i + 2]
    if len(a) < 2:
        sys.exit(__doc__)
    for asset in a[1:]:
        fetch(a[0], asset, res)
