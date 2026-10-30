#!/usr/bin/env python3
"""A room's lightmap (docs/design/deck-remodel.md, slice 8, the pilot in Ten
Forward): lcars-ui/deck/lm_<room>.{json,bin,ktx2}.

    python3 scripts/deck-models/lightmap.py [ROOM] [--samples N] [--size 1024] [--keep DIR]

Three steps, each checkable alone:

1. The export. deck.html?demo&touch&lightmap&nopatch in headless Chromium
   (Playwright), the models landed; the page's `lmExport` hands back the
   room's lit triangles as they are drawn (deck 8's merged meshes, one a
   material, and the room's glb mesh), in a glb made by three's own
   GLTFExporter (0.186.1, fetched into the build cache with npm: the page
   ships none), with each triangle's place in its selection (`_tri`), and
   the room's pooled lights.
2. The bake, in Blender (lightmap_bake.py): the room joined, welded,
   unwrapped into one atlas (a second UV set), and Cycles' diffuse bake of
   those lights, direct and indirect, the colour pass off: light only.
   Scaled to three's units, written as a PNG and a UV per corner.
3. The files: the PNG as KTX2, ETC1S in sRGB, mipmapped (KTX-Software's
   `ktx`, build.sh's in the cache); the UVs as unsigned 16-bit pairs, three's
   orientation (v down: a KTX2 is never flipped), each material's at its
   offset; and the JSON naming them (each material's triangle count, which
   the page checks before it applies one: a room changed since the bake is
   left without, with a warning).

Heavy (the export waits for the models in software WebGL, the bake is
Cycles on every core): run it through the job line.
"""
import argparse
import base64
import functools
import http.server
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
UI = REPO / "lcars-ui"
CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "lcars-deck-models"
THREE = "0.186.1"
JSM = CACHE / "three" / "node_modules" / "three" / "examples" / "jsm"
KTX = CACHE / "ktx" / "KTX-Software-4.4.2-Linux-x86_64"

ap = argparse.ArgumentParser()
ap.add_argument("room", nargs="?", default="tenforward")
ap.add_argument("--samples", type=int, default=256)
ap.add_argument("--size", type=int, default=1024)
ap.add_argument("--keep", default="", help="keep the work (the export, the PNG) in DIR")
args = ap.parse_args()


def exporter():
    """three's examples at the page's version, for GLTFExporter."""
    if not (JSM / "exporters" / "GLTFExporter.js").exists():
        (CACHE / "three").mkdir(parents=True, exist_ok=True)
        subprocess.run(["npm", "i", "--silent", "--no-save", "--no-package-lock", f"three@{THREE}"], cwd=CACHE / "three", check=True)


class Serve(http.server.SimpleHTTPRequestHandler):
    """lcars-ui/, and three's examples under /__jsm/."""

    def translate_path(self, path):
        if path.startswith("/__jsm/"):
            return str(JSM / path[len("/__jsm/"):].split("?")[0])
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def export(work):
    from playwright.sync_api import sync_playwright
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Serve, directory=str(UI)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/deck.html?demo&touch&lightmap&nopatch"
    with sync_playwright() as p:
        # as deckshots opens it: a phone, graphics low, first person
        b = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        ctx.add_init_script("""localStorage.setItem("lcars.deck.gfx", JSON.stringify("low"));
                               localStorage.setItem("lcars.deck.view", JSON.stringify("first"));""")
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type in ("warning", "error") and print("[page]", m.text, file=sys.stderr))
        t0 = time.time()
        pg.goto(url)
        pg.wait_for_function("window.__deck && window.__deck.modelsReady()", timeout=300_000, polling=1000)
        print(f"[lightmap] the models in, {time.time() - t0:.0f} s", file=sys.stderr)
        r = pg.evaluate("""async room => {
          const { GLTFExporter } = await import("/__jsm/exporters/GLTFExporter.js");
          return window.__deck.lmExport(room, GLTFExporter);
        }""", args.room)
        b.close()
    srv.shutdown()
    (work / "room.glb").write_bytes(base64.b64decode(r["glb"]))
    if not r["lights"]:
        sys.exit(f"[lightmap] {args.room}: no lights in the room's box")
    meta = {"room": args.room, "counts": r["counts"], "lights": r["lights"], "size": args.size, "samples": args.samples}
    (work / "meta.json").write_text(json.dumps(meta))
    print(f"[lightmap] exported {sum(r['counts'].values())} triangles in {len(r['counts'])} materials, {len(r['lights'])} lights", file=sys.stderr)
    return meta


def main():
    exporter()
    work = pathlib.Path(args.keep) if args.keep else pathlib.Path(tempfile.mkdtemp(prefix="lcars-lightmap-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        meta = export(work)
        t0 = time.time()
        subprocess.run(["blender", "-b", "--factory-startup", "-P", str(REPO / "scripts/deck-models/lightmap_bake.py"), "--", str(work)], check=True)
        print(f"[lightmap] baked, {time.time() - t0:.0f} s", file=sys.stderr)
        out = json.loads((work / "uv.json").read_text())
        # the UVs: each material's corners at its offset (`at`, in corners),
        # 0 where a triangle was not baked (collapsed under its model, or
        # welded away): the atlas's black corner
        meshes, data, at = {}, [], 0
        for key, n in sorted(meta["counts"].items()):
            uv = out["uv"].get(key)
            corners = [0] * (n * 6)
            if uv:
                for t, quad in uv.items():
                    t = int(t)
                    for c in range(3):
                        u, v = quad[c * 2], quad[c * 2 + 1]
                        corners[t * 6 + c * 2] = round(min(max(u, 0), 1) * 65535)
                        corners[t * 6 + c * 2 + 1] = round(min(max(1 - v, 0), 1) * 65535)   # three's v runs down a KTX2
            meshes[key] = {"tris": n, "at": at}
            at += n * 3
            data.extend(corners)
        dst = UI / "deck"
        (dst / f"lm_{args.room}.bin").write_bytes(struct.pack(f"<{len(data)}H", *data))
        env = dict(os.environ, LD_LIBRARY_PATH=str(KTX / "lib"))
        subprocess.run([str(KTX / "bin" / "ktx"), "create", "--format", "R8G8B8_SRGB", "--assign-tf", "srgb",
                        "--encode", "basis-lz", "--clevel", "4", "--qlevel", "255", "--generate-mipmap",
                        str(work / "lm.png"), str(dst / f"lm_{args.room}.ktx2")], check=True, env=env)
        j = {"note": "Ten Forward's lightmap pilot (deck-remodel slice 8): scripts/deck-models/lightmap.py; the page applies it under ?lightmap.",
             "room": args.room, "size": args.size, "samples": args.samples, "scale": out["scale"],
             "lights": meta["lights"], "meshes": meshes, "baked": out["baked"], "welded_away": out["lost"]}
        (dst / f"lm_{args.room}.json").write_text(json.dumps(j, indent=1) + "\n")
        for f in ("json", "bin", "ktx2"):
            print(f"[lightmap] lm_{args.room}.{f}: {(dst / f'lm_{args.room}.{f}').stat().st_size / 1024:.0f} kB", file=sys.stderr)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


main()
