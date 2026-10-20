#!/usr/bin/env python3
"""The web UI packed into one blob, for a binary that carries it.

    ui-pack.py OUT          write the pack (make ui-pack: build/ui.pack)
    ui-pack.py --list       the files it would take, one per line

docs/design/open-source-build.md, §2d. The shipped set is `git ls-files
lcars-ui` minus test/ and report/ (§1b), each read from the working tree as
it is now, so a build carries what is saved, committed or not. A build with
-DLCARS_EMBED_UI .incbins OUT (lcars_ui_files.h, "The embedded copy") and
serves /ui/ from it when LCARS_UI_DIR is not set.

The format, read by UIEmbedInit in C; text up to the data so `head` shows
what a pack holds:

    LCARS-UI-PACK 1 <count> <data offset> <build time>\\n
    <offset> <size> <hash> <path>\\n          count lines, paths sorted
    NUL padding to <data offset>, a multiple of 64
    the files' bytes, each at <data offset> + <offset>, 64-byte aligned

<path> is relative to lcars-ui/ ("deck/bridge.glb"); <hash> the first 16
hex digits of the file's SHA-256, its ETag; <build time> the Unix seconds
every file's Last-Modified says ($SOURCE_DATE_EPOCH if set, so a rebuild
of the same tree can be byte-identical). The files are stored raw: the
server gzips on first request and keeps the result (UISendGzip), and the
update check's Range on index.html needs the raw bytes anyway.

The pack is written to a temporary name and renamed into place, so a make
interrupted mid-write never leaves a short one for the next link to embed.
"""
import hashlib
import os
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
LEFT_OUT = ("lcars-ui/test/", "lcars-ui/report/")
ALIGN = 64
MAX_FILES = 512  # UI_EMBED_MAX in lcars_ui_files.h


def shipped():
    out = subprocess.run(["git", "ls-files", "-z", "lcars-ui"], cwd=REPO,
                         capture_output=True, check=True).stdout
    files = sorted(p for p in out.decode().split("\0")
                   if p and not p.startswith(LEFT_OUT))
    for p in files:
        # the index is space- and line-separated; the C side refuses a
        # dot-segment anyway (UIRelIsSafe), so such a file could never be
        # served
        rel = p[len("lcars-ui/"):]
        if any(c in rel for c in " \n\r\t\\") or \
                any(s.startswith(".") for s in rel.split("/")):
            sys.exit(f"ui-pack: {p}: a name the pack cannot hold")
    return files


def pad(n):
    return (ALIGN - n % ALIGN) % ALIGN


def pack(out):
    files = shipped()
    if not files:
        sys.exit("ui-pack: git ls-files lcars-ui found nothing")
    if len(files) > MAX_FILES:
        sys.exit(f"ui-pack: {len(files)} files, over the {MAX_FILES} the server takes")
    built = int(os.environ.get("SOURCE_DATE_EPOCH") or time.time())
    lines, blobs, off = [], [], 0
    for p in files:
        data = (REPO / p).read_bytes()
        lines.append(f"{off} {len(data)} {hashlib.sha256(data).hexdigest()[:16]} "
                     f"{p[len('lcars-ui/'):]}\n")
        blobs.append(data + b"\0" * pad(len(data)))
        off += len(data) + pad(len(data))
    # The header names the data offset, which depends on the header's own
    # length: grow it until it holds still.
    data_off = 0
    while True:
        head = f"LCARS-UI-PACK 1 {len(files)} {data_off} {built}\n" + "".join(lines)
        want = len(head) + pad(len(head))
        if want == data_off:
            break
        data_off = want
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name("." + out.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(head.encode() + b"\0" * pad(len(head)))
        for b in blobs:
            f.write(b)
    os.replace(tmp, out)
    print(f"ui-pack: {out}: {len(files)} files, {data_off + off} bytes")


def main():
    if sys.argv[1:] == ["--list"]:
        print("\n".join(shipped()))
    elif len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        pack(sys.argv[1])
    else:
        sys.exit(__doc__.split("\n\n")[1])


if __name__ == "__main__":
    main()
