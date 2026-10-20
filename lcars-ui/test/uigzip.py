#!/usr/bin/env python3
"""gzip for the web UI's files (lcars_ui_files.h), end to end.

Drives scratch builds of the real server over an empty database, with
LCARS_UI_DIR on a scratch copy of a few lcars-ui files, and checks:

  1. deck.html, index.html (and a page url), a glb and a small css come back
     gzipped when gzip is offered: Content-Encoding, Vary, the file's
     Content-Type, the bytes the file's own once inflated; deck.html's wire
     bytes under half; the big ones cached (a Content-Length), the small
     one compressed as it is sent (chunked);
  2. identity, with Vary, when the client does not offer gzip or says q=0,
     and for a HEAD;
  3. a Range on index.html with gzip offered: identity 206, the first 1024
     bytes, as updFetchVersion needs;
  4. a png and a webp never gzipped;
  5. If-Modified-Since with the Last-Modified: a 304 (with Vary) in either form;
  6. a file saved in place - also one put back to its old size and mtime -
     is the new bytes on the next request: never a stale cached form;
     parallel requests across a save all inflate to one version or the other;
  7. with the cache off (LCARS_UI_GZ_BYTES=0) everything is streamed and
     still right, and with a small cache that has to start over (4MB, saves
     cycling deck.html) too;
  8. the embedded copy (-DLCARS_EMBED_UI, a pack scripts/ui-pack.py writes
     to the scratch directory): the start log says so; every shipped file
     byte-equal to its source, with its type and an ETag; 1-5 above against
     it; a 304 by If-None-Match (either form) and by If-Modified-Since, and
     a 200 for another tag; a file not shipped (test/) a 404; and
     LCARS_UI_DIR, when set, winning over it.

    python3 test/uigzip.py            # builds two servers first (~40s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/uigzip.py   # 8 builds its own

Nothing here touches the journal, lcars-ui/ or a running server.
"""
import concurrent.futures
import http.client
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
import zlib
import killclean  # its scratch goes when the run is killed

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build  # noqa: E402
from metrics import Server  # noqa: E402

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
FILES = ["deck.html", "index.html", "icon-192.png", "deck/bridge.glb",
         "deck/bridge_base.webp", "vendor/leaflet-1.9.4.css"]

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def get(port, path, headers=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    h = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, h, body


GZ = {"Accept-Encoding": "gzip, deflate, br"}


def inflate(b):
    return zlib.decompress(b, 15 + 16)


def scratch_ui(tmp):
    ui = tmp / "ui"
    for f in FILES:
        (ui / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(UI / f, ui / f)
    return ui


def start(binary, tmp, name, budget=None):
    d = tmp / name
    d.mkdir()
    os.environ["LCARS_UI_DIR"] = str(scratch_ui(d))
    if budget is None:
        os.environ.pop("LCARS_UI_GZ_BYTES", None)
    else:
        os.environ["LCARS_UI_GZ_BYTES"] = str(budget)
    return Server(binary, d), d / "ui"


def gz_ok(port, ui, rel, path=None, framing=None, ctype=None):
    want = (ui / rel).read_bytes()
    st, h, body = get(port, path or "/ui/" + rel, GZ)
    good = st == 200 and h.get("content-encoding") == "gzip" and \
        h.get("vary") == "Accept-Encoding"
    try:
        good = good and inflate(body) == want
    except zlib.error:
        good = False
    if ctype:
        good = good and h.get("content-type", "").startswith(ctype)
    how = "chunked" if h.get("transfer-encoding") == "chunked" else \
        "length" if "content-length" in h else "?"
    if framing:
        good = good and how == framing
    check(good, f"{path or rel}: gzip, Vary, {h.get('content-type')}, inflates to the "
                f"file ({len(want)} -> {len(body)} bytes, {how})")
    return len(want), len(body)


def basics(port, ui):
    print("\ngzip when offered")
    raw, wire = gz_ok(port, ui, "deck.html", framing="length", ctype="text/html")
    check(wire * 2 < raw, f"deck.html's wire bytes under half: {wire} of {raw} "
                          f"({100 - 100 * wire // raw}% off)")
    gz_ok(port, ui, "index.html", framing="length", ctype="text/html")
    gz_ok(port, ui, "index.html", path="/ui/tasks", framing="length", ctype="text/html")
    gz_ok(port, ui, "index.html", path="/ui/", framing="length", ctype="text/html")
    gz_ok(port, ui, "deck/bridge.glb", ctype="model/gltf-binary")
    gz_ok(port, ui, "vendor/leaflet-1.9.4.css", framing="chunked", ctype="text/css")

    t = time.perf_counter()
    get(port, "/ui/index.html", GZ)
    hit = (time.perf_counter() - t) * 1000
    print(f"  ..   index.html from the cache: {hit:.1f}ms")

    print("\nidentity when not offered")
    for hdrs, what in (({}, "no Accept-Encoding"),
                       ({"Accept-Encoding": "gzip;q=0, identity"}, "gzip;q=0"),
                       ({"Accept-Encoding": "br"}, "br only")):
        st, h, body = get(port, "/ui/deck.html", hdrs)
        check(st == 200 and "content-encoding" not in h and
              h.get("vary") == "Accept-Encoding" and
              body == (ui / "deck.html").read_bytes() and
              h.get("content-length") == str(len(body)),
              f"deck.html with {what}: identity, Vary, Content-Length ({st})")
    st, h, body = get(port, "/ui/index.html", GZ, method="HEAD")
    check(st == 200 and "content-encoding" not in h and h.get("vary") == "Accept-Encoding"
          and h.get("content-length") == str((ui / "index.html").stat().st_size),
          f"HEAD index.html: identity headers, Vary ({st})")

    print("\na Range is identity")
    st, h, body = get(port, "/ui/index.html", dict(GZ, Range="bytes=0-1023"))
    check(st == 206 and "content-encoding" not in h and len(body) == 1024 and
          body == (ui / "index.html").read_bytes()[:1024] and
          h.get("content-range", "").startswith("bytes 0-1023/") and
          h.get("vary") == "Accept-Encoding",
          f"index.html bytes=0-1023 with gzip offered: 206, identity, 1024 bytes ({st})")

    print("\nnever gzipped")
    for rel, ctype in (("icon-192.png", "image/png"), ("deck/bridge_base.webp", "image/webp")):
        st, h, body = get(port, "/ui/" + rel, GZ)
        check(st == 200 and "content-encoding" not in h and h.get("content-type") == ctype
              and body == (ui / rel).read_bytes() and h.get("vary") == "Accept-Encoding",
              f"{rel} with gzip offered: identity {ctype}, Vary ({st})")

    print("\na 304 is a 304")
    for hdrs, what in ((GZ, "gzip"), ({}, "identity")):
        _, h, _ = get(port, "/ui/deck.html", hdrs)
        st, h2, body = get(port, "/ui/deck.html", dict(hdrs, **{
            "If-Modified-Since": h["last-modified"]}))
        check(st == 304 and body == b"" and h2.get("vary") == "Accept-Encoding",
              f"deck.html If-Modified-Since its Last-Modified ({what}): 304, Vary ({st})")


def saves(port, ui, rounds=3):
    print("\na saved file is never served stale")
    f = ui / "deck.html"
    for i in range(rounds):
        with open(f, "ab") as w:  # in place: same inode
            w.write(f"<!-- save {i} -->".encode())
        gz_ok(port, ui, "deck.html")
    # the same size and mtime as a cached form: only ctime tells them apart
    gz_ok(port, ui, "index.html")
    p = ui / "index.html"
    old = p.stat()
    data = bytearray(p.read_bytes())
    data[-20:] = b"X" * 20
    with open(p, "r+b") as w:
        w.write(data)
    os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))
    check(p.stat().st_size == old.st_size and p.stat().st_mtime_ns == old.st_mtime_ns,
          "index.html rewritten with its old size and mtime")
    gz_ok(port, ui, "index.html")
    # replaced by rename: a new inode
    tmpf = ui / "index.html.new"
    tmpf.write_bytes(bytes(data) + b"<!-- renamed -->")
    os.replace(tmpf, p)
    gz_ok(port, ui, "index.html")

    print("\nparallel requests across a save")
    before = p.read_bytes()
    after = before + b"<!-- parallel -->"

    cut, empty = [0], [0]

    def one(_):
        # A get that meets the save mid-read (write_bytes truncates in place)
        # may be cut off - a failed transfer, which no cache keeps. What it
        # must never be is a whole answer of neither version.
        try:
            st, h, body = get(port, "/ui/index.html", GZ)
        except http.client.IncompleteRead:
            cut[0] += 1
            return True
        if st == 200 and "content-encoding" not in h and body == b"":
            # met the instant write_bytes had truncated it: the file was
            # empty then (under 1KB, so identity) - true, if unlucky
            empty[0] += 1
            return True
        try:
            whole = st == 200 and inflate(body) in (before, after)
        except zlib.error:
            whole = False
        if not whole:
            print(f"  ..   not whole: {st} {h.get('content-encoding')} "
                  f"{h.get('content-length') or h.get('transfer-encoding')} {len(body)} bytes")
        return whole
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(one, i) for i in range(12)]
        p.write_bytes(after)
        futs += [ex.submit(one, i) for i in range(12)]
        results = [x.result() for x in futs]
    check(all(results), f"24 parallel gets of index.html: each one version, whole "
                        f"({sum(results)}/24, {cut[0]} cut off, {empty[0]} empty)")
    gz_ok(port, ui, "index.html")


def build_embedded(out, pack):
    """The lcars-release line with the UI in it: the pack written to
    scratch, never build/ui.pack, so the check is of this tree as it is."""
    r = subprocess.run([sys.executable, str(REPO / "scripts/ui-pack.py"), str(pack)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("uigzip: ui-pack failed\n" + r.stderr)
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-release"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next(l for l in plan.splitlines()
                if l.startswith("cc ") and " -o lcars lcars.c" in l)
    line = line.replace(" -o lcars ", f" -o {shlex.quote(str(out))} ", 1)
    line += " -DLCARS_EMBED_UI " + shlex.quote(f'-DLCARS_UI_PACK="{pack}"')
    print("building a scratch server with the UI embedded ...", flush=True)
    r = subprocess.run(line, shell=True, cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0 or "warning" in r.stderr:
        sys.exit("uigzip: the embedded build failed or warned\n" + r.stderr[-3000:])


def start_embedded(binary, tmp, name, ui_dir=None):
    d = tmp / name
    d.mkdir()
    os.environ.pop("LCARS_UI_GZ_BYTES", None)
    if ui_dir:
        os.environ["LCARS_UI_DIR"] = str(ui_dir)
    else:
        os.environ.pop("LCARS_UI_DIR", None)
    return Server(binary, d), d / "server.log"


def embedded(binary, tmp, servers):
    print("\n== the embedded copy")
    s, log = start_embedded(binary, tmp, "embedded")
    servers.append(s)
    shipped = subprocess.run([sys.executable, str(REPO / "scripts/ui-pack.py"), "--list"],
                             capture_output=True, text=True, check=True).stdout.split()
    said = [l for l in log.read_text().splitlines() if l.startswith("UI:")]
    check(len(said) == 1 and said[0].startswith(f"UI: embedded, {len(shipped)} files,"),
          f"the start log: {said}")
    check(not (log.parent / "lcars-ui").exists(), "no lcars-ui/ where it runs")

    print(f"\nevery shipped file, byte-equal ({len(shipped)})")
    bad = []
    for p in shipped:
        rel = p[len("lcars-ui/"):]
        st, h, body = get(s.port, "/ui/" + rel)
        if st != 200 or body != (REPO / p).read_bytes() or \
                not h.get("etag", "").startswith('W/"') or "last-modified" not in h:
            bad.append(f"{rel} ({st}, {len(body)} bytes, {h.get('etag')})")
    check(not bad, f"{len(shipped) - len(bad)}/{len(shipped)} as their source, with an "
                   f"ETag and Last-Modified" + (f": {bad[:5]}" if bad else ""))
    _, h, _ = get(s.port, "/ui/deck/bridge.glb")
    check(h.get("content-type") == "model/gltf-binary", f"a glb's type: {h.get('content-type')}")
    st2, _, _ = get(s.port, "/ui/test/run.sh")
    check(st2 == 404, f"test/ is not shipped: 404 ({st2})")

    basics(s.port, UI)

    print("\nthe ETag")
    for hdrs, what in ((GZ, "gzip"), ({}, "identity")):
        _, h, _ = get(s.port, "/ui/index.html", hdrs)
        tag = h.get("etag", "")
        st, h2, body = get(s.port, "/ui/index.html", dict(hdrs, **{"If-None-Match": tag}))
        check(st == 304 and body == b"" and h2.get("etag") == tag and
              h2.get("vary") == "Accept-Encoding",
              f"index.html If-None-Match {tag} ({what}): 304 with the tag ({st})")
        st, _, _ = get(s.port, "/ui/index.html", dict(hdrs, **{
            "If-None-Match": tag[2:]}))
        check(st == 304, f"the tag without W/ ({what}): 304 ({st})")
        st, _, _ = get(s.port, "/ui/index.html", dict(hdrs, **{
            "If-None-Match": '"0000000000000000"',
            "If-Modified-Since": h["last-modified"]}))
        check(st == 200, f"another tag, If-Modified-Since its own ({what}): 200, "
                         f"the tag decides ({st})")
    _, h1, _ = get(s.port, "/ui/index.html")
    _, h2, _ = get(s.port, "/ui/deck.html")
    check(h1.get("etag") != h2.get("etag"), "two files, two tags")

    print("\nLCARS_UI_DIR wins")
    d = tmp / "mine"
    d.mkdir()
    (d / "index.html").write_bytes(b"<!doctype html><title>mine</title>" + b"x" * 4000)
    s2, log2 = start_embedded(binary, tmp, "dir", ui_dir=d)
    servers.append(s2)
    said = [l for l in log2.read_text().splitlines() if l.startswith("UI:")]
    check(len(said) == 1 and "the embedded copy unused" in said[0] and str(d) in said[0],
          f"the start log: {said}")
    st, h, body = get(s2.port, "/ui/")
    check(st == 200 and body == (d / "index.html").read_bytes() and "etag" not in h,
          f"/ui/ is the directory's index.html, no ETag ({st}, {len(body)} bytes)")
    st, _, _ = get(s2.port, "/ui/deck.html")
    check(st == 404, f"a file only the embedded copy has: 404 ({st})")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-uigzip-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    ebinary = tmp / "lcars-embedded"
    build_embedded(ebinary, tmp / "ui.pack")
    servers = []
    try:
        print("\n== the default cache")
        s, ui = start(binary, tmp, "default")
        servers.append(s)
        basics(s.port, ui)
        saves(s.port, ui)

        print("\n== the cache off (LCARS_UI_GZ_BYTES=0)")
        s, ui = start(binary, tmp, "off", 0)
        servers.append(s)
        gz_ok(s.port, ui, "deck.html", framing="chunked", ctype="text/html")
        gz_ok(s.port, ui, "index.html", framing="chunked", ctype="text/html")
        st, h, _ = get(s.port, "/ui/index.html", dict(GZ, Range="bytes=0-1023"))
        check(st == 206 and "content-encoding" not in h, f"a Range: identity 206 ({st})")
        saves(s.port, ui, rounds=1)

        print("\n== a 4MB cache, started over by saves")
        s, ui = start(binary, tmp, "small", 4 * 1024 * 1024)
        servers.append(s)
        # deck.html fits (a quarter of the budget), index.html is streamed
        gz_ok(s.port, ui, "deck.html", framing="length")
        gz_ok(s.port, ui, "index.html", framing="chunked")
        saves(s.port, ui, rounds=16)  # ~290KB a save: past 4MB twice

        embedded(ebinary, tmp, servers)

        for sv in servers:
            check(sv.proc.poll() is None, "the server is still up")
    finally:
        for sv in servers:
            sv.proc.terminate()
            try:
                sv.proc.wait(10)
            except Exception:
                sv.proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{checks[0] - len(fails)}/{checks[0]} checks passed")
    if fails:
        print("FAILED:\n  " + "\n  ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
