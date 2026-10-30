#!/usr/bin/env python3
"""Upload the built demo to R2 (docs/design/demo-static.md, "Upload").

    python3 lcars-ui/demo/r2_sync.py [OUT] [--bucket test] [--prefix lcars-demo/]   # the plan
    python3 lcars-ui/demo/r2_sync.py [OUT] --apply                                  # do it

OUT is static.py's folder (default ~/blog-media/lcars-demo/out). Without
--apply it only lists the bucket (read-only, r2_list.py) and prints the
plan: what it would put (changed by MD5, or new), how many are the same,
what it would delete. With --apply it puts each changed and new file with
`npx wrangler@3 r2 object put` and the type its extension names, the pages
last (everything they name is there before they are), then deletes the
objects under the prefix that are not in the build - and nothing outside
it. `.lcars-demo` (the build's own mark) never goes up.

Wrangler 3 because the box has Node 20; it is run through npx, nothing
installed, with telemetry off. The credentials come from the environment
only (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID), as for r2_list.py.
"""
import argparse
import hashlib
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import r2_list  # noqa: E402

DEFAULT_OUT = pathlib.Path.home() / "blog-media" / "lcars-demo" / "out"
MARK = ".lcars-demo"
# What a static host needs to serve each file as itself (the doc's list):
# a file of a type not here stops the run before anything is written.
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".glb": "model/gltf-binary",
    ".webp": "image/webp", ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8",
    # the deck's KTX2 textures and their transcoder (0.302.5; a wasm must be
    # application/wasm for instantiateStreaming), the themes' btop files
    # (0.335.0), and their LICENSE and NOTICE, the build's only files with
    # no extension: licence texts
    ".ktx2": "image/ktx2", ".wasm": "application/wasm",
    ".theme": "text/plain; charset=utf-8", "": "text/plain; charset=utf-8",
    # Ten Forward's baked lightmap's uvs (lm_<room>.bin, the deck remodel)
    ".bin": "application/octet-stream",
}


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def plan(out, remote, prefix):
    """(put, same, delete): keys to put (sorted, pages last), the count
    unchanged, keys to delete."""
    local = {}
    for f in sorted(out.rglob("*")):
        rel = f.relative_to(out).as_posix()
        if f.is_file() and rel.split("/")[0] != MARK:
            local[prefix + rel] = f
    put, same = [], 0
    for k, f in local.items():
        if remote.get(k, {}).get("etag") == md5(f):
            same += 1
        else:
            put.append(k)
    put.sort(key=lambda k: (k.endswith(".html"), k))
    gone = sorted(k for k in remote if k not in local and k.startswith(prefix))
    return local, put, same, gone


def wrangler(*args):
    env = dict(os.environ, WRANGLER_SEND_METRICS="false")
    subprocess.run(["npx", "--yes", "wrangler@3", "r2", "object", *args],
                   env=env, check=True, stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?", default=str(DEFAULT_OUT))
    ap.add_argument("--bucket", default=r2_list.BUCKET)
    ap.add_argument("--prefix", default=r2_list.PREFIX)
    ap.add_argument("--apply", action="store_true", help="put and delete (default: print the plan only)")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    prefix = a.prefix if a.prefix.endswith("/") else a.prefix + "/"
    if prefix == "/" or not (out / "index.html").is_file():
        sys.exit(f"r2_sync: refused: {'an empty prefix' if prefix == '/' else f'no index.html in {out}'}")
    remote = r2_list.list_objects(a.bucket, prefix)
    local, put, same, gone = plan(out, remote, prefix)
    print(f"{a.bucket}/{prefix}: {len(remote)} objects; put {len(put)} "
          f"(new {sum(k not in remote for k in put)}), same {same}, delete {len(gone)}")
    for k in put:
        print("  put   ", k)
    for k in gone:
        print("  delete", k)
    untyped = [k for k in put if pathlib.Path(k).suffix not in TYPES]
    if untyped:
        sys.exit(f"r2_sync: no content type for {untyped}: add it to TYPES")
    if not a.apply:
        print("(the plan only: --apply to upload)")
        return
    for k in put:
        wrangler("put", f"{a.bucket}/{k}", "--file", str(local[k]),
                 "--content-type", TYPES[pathlib.Path(k).suffix])
        print("  put    done", k, flush=True)
    for k in gone:
        wrangler("delete", f"{a.bucket}/{k}")
        print("  deleted     ", k, flush=True)


if __name__ == "__main__":
    main()
