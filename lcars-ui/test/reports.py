#!/usr/bin/env python3
"""Hosted reports, end to end: scripts/report.py and how the server serves them.

    python3 test/reports.py        (~40s; LCARS_TEST_BIN=<binary> skips the build)

- report.py publish/list against a scratch media root: the layout
  (media/reports/YYYY/MM/<slug>-<id>.<ext>, a hidden sidecar), the URL it
  prints, nothing half-written, and a refusal with nothing written when the
  root is not mounted;
- the journal entry each report is (reports-as-entries.md): publish and
  update write it, one over the size cap the first line alone, the journal down (exit 3),
  `import` dry and applied, twice;
- report.py update: the same name and URL, the sidecar's title kept and
  updated_utc added, a path outside the store, a sidecar, a symlink or a
  missing report Refused; through the server, the new bytes served where
  the disk cache held the old; no1.py report --update's one log line;
- GET /reports: newest first, titles from the sidecars, the auth, a 503
  when unmounted;
- GET /media/reports/...: an HTML report as text/html with
  Content-Security-Policy: sandbox (never allow-same-origin) and nosniff,
  from the NAS and from the disk cache alike; CSV/Markdown as text/plain;
  a PDF as application/pdf without the sandbox; the sidecar, dot-names and
  escapes refused; an attachment served as before (no CSP);
- in Chromium: an HTML report's script runs, and cannot read the
  localStorage of the origin it is served from (where /ui/ keeps the API
  password);
- in Chromium at a phone's size: the web UI's report viewer, from a cold
  ./report/<path> link - the report framed (sandboxed, no
  allow-same-origin), its document's origin null and localStorage out of
  its reach, nothing wider than the screen, Back closing it.

A scratch server is built from the lcars-release compile line (to a temp
path, never ./lcars) and run on an empty database and temp directories;
nothing here touches lcars.db, the NAS or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.request

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
REPORT = REPO / "scripts" / "report.py"
USER, PASS = "t", "t"
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build(out):
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-release"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and " -o lcars lcars.c" in l), None)
    if not line:
        sys.exit("reports: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("reports: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp, root, cache):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_MEDIA_ROOT=str(root), LCARS_MEDIA_CACHE=str(cache),
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS, LCARS_UI_DIR=str(UI))
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + "/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("reports: the scratch server did not come up; see " + str(tmp / "server.log"))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()

    def req(self, method, path, auth=True):
        """(status, headers, body) - errors are answers too. From loopback,
        as tailscale serve's proxy connects: /media/ asks no password."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request(method, path, headers={"Authorization": AUTH} if auth else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, data


JOURNAL = ["http://127.0.0.1:1"]  # the scratch server's, once it is up: never the box's


def report(root, *args, cache=None, base="https://box.example.ts.net", journal=None):
    # the entries go to the scratch server as its login, and HOME is scratch,
    # so no ~/.env of the box's (its login, its server) is ever read
    env = dict(os.environ, LCARS_MEDIA_ROOT=str(root), LCARS_REPORT_BASE=base,
               LCARS_MEDIA_CACHE=str(cache) if cache else "0", HOME=str(root.parent),
               LCARS_URL=journal or JOURNAL[0], LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS)
    if not base:    # and no ~/.env of the box's to find it in
        env.pop("LCARS_REPORT_BASE")
    return subprocess.run([sys.executable, str(REPORT), *args], env=env, capture_output=True, text=True)


def script_checks(tmp, root):
    print("-- report.py: refused when the media root is not mounted --")
    src = tmp / "src"
    src.mkdir()
    (src / "status.html").write_text("<!doctype html><title>t</title><script>"
                                     "let r; try { r = 'read:' + localStorage.getItem('lcars.cfg'); }"
                                     " catch (e) { r = 'blocked'; } document.title = r;</script>")
    r = report(root, "publish", str(src / "status.html"))
    check(r.returncode == 2 and "mounted" in r.stderr, "publish refuses: %r" % r.stderr.strip())
    check(not (root / "media").exists(), "and writes nothing, not even <root>/media")
    r = report(root, "list")
    check(r.returncode == 2 and "mounted" in r.stderr, "list refuses too")

    (root / "media").mkdir(parents=True)
    print("-- report.py publish --")
    r = report(root, "publish", str(src / "status.html"), "--title", "Fleet status: October")
    url = r.stdout.strip()
    check(r.returncode == 0 and url.startswith("https://box.example.ts.net/media/reports/"),
          "prints the link: %r" % url)
    rel = url.split("/", 3)[3]
    r = report(root, "publish", str(src / "status.html"), "--title", "No base", base="")
    check(r.returncode == 0 and r.stdout.strip().startswith("/media/reports/"),
          "with no LCARS_REPORT_BASE the link is the path, no host: %r" % r.stdout.strip())
    nb = root / r.stdout.strip().lstrip("/")
    check(nb.is_file(), "and the report is published")
    nb.unlink()
    for side in nb.parent.glob("." + nb.name + "*"):
        side.unlink()
    f = root / rel
    parts = rel.split("/")
    check(len(parts) == 5 and parts[2].isdigit() and len(parts[2]) == 4 and len(parts[3]) == 2,
          "media/reports/YYYY/MM/<name>: %s" % rel)
    check(parts[4].startswith("fleet-status-october-") and parts[4].endswith(".html"),
          "named <slug>-<id>.<ext>: %s" % parts[4])
    check(f.is_file() and f.read_bytes() == (src / "status.html").read_bytes(), "a byte-for-byte copy")
    side = f.parent / ("." + f.name + ".json")
    check(side.is_file() and json.loads(side.read_text()).get("title") == "Fleet status: October",
          "its title in a hidden sidecar")
    check(not [p for p in f.parent.iterdir() if p.name.endswith(".part")], "no .part left behind")

    (src / "weights.csv").write_text("day,kg\n2026-10-01,80.1\n")
    (src / "notes.md").write_text("# Notes\n\n<script>x</script>\n")
    (src / "chart.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (src / "odd.we!rd").write_bytes(b"\x00\x01")
    out = {}
    for name in ("weights.csv", "notes.md", "chart.pdf", "odd.we!rd"):
        time.sleep(1.05)  # mtime is the order, to the second
        r = report(root, "publish", str(src / name), "--json")
        check(r.returncode == 0, "publish %s" % name)
        out[name] = json.loads(r.stdout)
    check(out["odd.we!rd"]["path"].endswith(".bin"), "an extension that is not plain is stored as .bin")
    check(out["weights.csv"]["title"] == "weights", "no --title: the file's name")
    r = report(root, "publish", str(src / "missing.html"))
    check(r.returncode == 2 and "not a file" in r.stderr, "a missing file is refused")

    print("-- report.py list --")
    r = report(root, "list", "--json")
    rows = json.loads(r.stdout)
    check([x["path"] for x in rows[:2]] == [out["odd.we!rd"]["path"], out["chart.pdf"]["path"]],
          "newest first")
    check(rows[-1]["title"] == "Fleet status: October" and rows[-1]["url"] == url, "titles and links")
    r = report(root, "list", "2")
    check(r.returncode == 0 and r.stdout.count("https://") == 2, "list n")

    print("-- report.py update: refusals --")
    md = out["notes.md"]["path"]
    d, name = md.rsplit("/", 1)
    (src / "notes2.md").write_text("# Notes, revised\n")
    (root / "media" / "elsewhere.md").write_text("not a report")
    (root / d / "link.md").symlink_to(root / "media" / "elsewhere.md")
    for bad, why in ((f"{d}/.{name}.json", "a sidecar"), (f"{d}/missing.md", "a missing report"),
                     ("media/elsewhere.md", "a file outside the store"),
                     (f"media/reports/../elsewhere.md", "a .. path"),
                     (f"{d}/link.md", "a symlink out of the store"),
                     ("/etc/passwd", "an absolute path"), ("", "nothing")):
        before = (root / "media" / "elsewhere.md").read_text()
        r = report(root, "update", bad, str(src / "notes2.md"))
        check(r.returncode == 2 and "report.py:" in r.stderr and
              (root / "media" / "elsewhere.md").read_text() == before, "%s is refused: %r" % (why, r.stderr.strip()))
    (root / d / "link.md").unlink()
    r = report(root, "update", md, str(src / "absent.md"))
    check(r.returncode == 2 and "not a file" in r.stderr, "a missing new file is refused")
    check((root / md).read_text() == "# Notes\n\n<script>x</script>\n", "and the report is as it was")
    return rel, out


def entries(srv, q=None):
    """The scratch journal's report entries, {first line: entry}, whole:
    /dump sends a report's first line alone unless report_body=1."""
    st, _, body = srv.req("GET", "/dump?kind=report&deleted=all&report_body=1")
    rows = json.loads(body) if st == 200 else []
    return {e["content"].split("\n", 1)[0]: e for e in rows}


def entry_checks(srv, tmp):
    """Reports as entries (docs/design/reports-as-entries.md), on a root of
    their own so the listing checks above keep their counts."""
    root = tmp / "root2"
    (root / "media").mkdir(parents=True)
    src = tmp / "src2"
    src.mkdir()
    print("-- report.py publish: the entry --")
    (src / "a.html").write_bytes(b'<h1>"Fleet"</h1>\r\nline\x01two\n')
    (src / "b.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    r = report(root, "publish", str(src / "a.html"), "--title", "Fleet", "--json")
    a = json.loads(r.stdout) if r.returncode == 0 else {}
    e = entries(srv).get(f"report:: html {a.get('path')}")
    check(r.returncode == 0 and e and e["id"] == a.get("id"), "an entry, its id in --json: %r" % r.stdout[:200])
    side = json.loads((root / (a["path"].rsplit("/", 1)[0]) / ("." + a["path"].rsplit("/", 1)[1] + ".json")).read_text())
    check(e and e["kind"] == "report" and e["title"] == "Fleet" and e["created_at_utc"] == side["published_utc"],
          "kind report, the title, created_at the publish time")
    check(e and e["content"] == f"report:: html {a['path']}\n\n<h1>\"Fleet\"</h1>\nlinetwo\n",
          "the first line, a blank, the whole text (CRLF and control bytes gone): %r" % (e or {}).get("content"))
    r = report(root, "publish", str(src / "b.pdf"), "--json")
    b = json.loads(r.stdout) if r.returncode == 0 else {}
    e = entries(srv).get(f"report:: pdf {b.get('path')}")
    check(e and e["content"] == f"report:: pdf {b['path']}", "a PDF's entry is the first line alone")

    print("-- report.py update: the same entry --")
    (src / "a2.html").write_text("<h1>Revised</h1>\n")
    r = report(root, "update", a["path"], str(src / "a2.html"), "--json")
    u = json.loads(r.stdout) if r.returncode == 0 else {}
    e = entries(srv).get(f"report:: html {a['path']}")
    check(u.get("id") == a["id"] and e and e["content"].endswith("\n\n<h1>Revised</h1>\n"),
          "refreshes the entry it made: %r" % (e or {}).get("content"))
    check(len([k for k in entries(srv) if a["path"] in k]) == 1, "and makes no second one")

    print("-- the journal's limit --")
    big = src / "big.csv"
    big.write_text("x,y\n" * 140000)   # 560,000 bytes
    r = report(root, "publish", str(big), "--json")
    j = json.loads(r.stdout) if r.returncode == 0 else {}
    e = entries(srv).get(f"report:: csv {j.get('path')}")
    check(r.returncode == 0 and (root / j["path"]).stat().st_size == 560000,
          "a report over the entry cap is published: %r" % r.stderr.strip()[:160])
    check(e and e["id"] == j.get("id") and e["content"] == f"report:: csv {j['path']}",
          "and its entry is the first line alone, the link: %r" % (e or {}).get("content", "")[:80])
    r = report(root, "update", a["path"], str(big), "--json")
    e = entries(srv).get(f"report:: html {a['path']}")
    check(r.returncode == 0 and (root / a["path"]).stat().st_size == 560000 and e
          and e["content"] == f"report:: html {a['path']}", "an update over it: the file, the entry made the link alone")
    r = report(root, "update", a["path"], str(src / "a2.html"))
    e = entries(srv).get(f"report:: html {a['path']}")
    check(r.returncode == 0 and e and e["content"].endswith("\n\n<h1>Revised</h1>\n"), "and back under it, the text again")
    edge = src / "edge.txt"
    edge.write_text("y" * (520192 - 300))
    r = report(root, "publish", str(edge), "--json")
    p = json.loads(r.stdout).get("path") if r.returncode == 0 else None
    e = entries(srv).get(f"report:: txt {p}")
    check(e and len(e["content"]) > 519000, "one just under it is an entry: %d" % len((e or {}).get("content", "")))
    st, _, _ = srv.req("GET", "/dump")
    check(st == 200, "which the console's cold load (/dump) still reads")

    print("-- the journal down --")
    r = report(root, "publish", str(src / "b.pdf"), "--json", journal="http://127.0.0.1:1")
    j = json.loads(r.stdout) if r.stdout.strip() else {}
    check(r.returncode == 3 and j.get("id") is None and "import --apply" in j.get("error", "") + r.stderr
          and (root / j.get("path", "x")).is_file(), "the report is published, the entry's failure said, exit 3")
    down = j.get("path")

    print("-- report.py import --")
    old = tmp / "old.py"
    # report.py from before it wrote entries: the parent of the commit that
    # made it (main's own copy writes them since that deployed)
    made = subprocess.run(["git", "rev-list", "-1", "--grep=report.py writes them", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    old.write_text(subprocess.run(["git", "show", f"{made}^:scripts/report.py"], cwd=REPO,
                                  capture_output=True, text=True).stdout)
    olds = []
    for name in ("a.html", "b.pdf", "big.csv"):
        o = subprocess.run([sys.executable, str(old), "publish", str(src / name), "--json"], capture_output=True, text=True,
                           env=dict(os.environ, LCARS_MEDIA_ROOT=str(root), LCARS_MEDIA_CACHE="0", HOME=str(tmp),
                                    LCARS_URL=JOURNAL[0], LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS))
        olds.append(json.loads(o.stdout)["path"] if o.returncode == 0 else None)
    (root / olds[1]).with_name("." + olds[1].rsplit("/", 1)[1] + ".json").write_text(
        json.dumps({"title": "Back then", "published_utc": "2026-01-02 03:04:05"}))
    (root / olds[1]).touch()   # its mtime now, the sidecar's time wins
    big2 = json.loads(report(root, "publish", str(src / "a.html"), "--json").stdout)["path"]
    (root / big2.lstrip("/")).write_text("x" * 600000)
    eid = entries(srv)[f"report:: html {big2.lstrip('/')}"]["id"]
    srv_delete = srv.req("DELETE", f"/entries/{eid}")[0]
    before = entries(srv)
    r = report(root, "import", "--json")
    plan = json.loads(r.stdout) if r.returncode == 0 else {}
    tb = olds[-1]
    check([x["path"] for x in plan.get("create", []) if x.get("link_only")] == [tb],
          "one over the cap is made the link alone, and said")
    check(sorted(x["path"] for x in plan.get("create", [])) == sorted(olds + [down]),
          "the dry run names the reports with no entry: %r" % [x["path"] for x in plan.get("create", [])])
    check(entries(srv) == before, "and writes nothing")
    check(len(plan.get("have", [])) == 5 and big2.lstrip("/") in [x["path"] for x in plan["have"]],
          "those with one are left, a deleted one included (%d)" % srv_delete)
    r = report(root, "import", "--apply")
    check(r.returncode == 0 and "4 created (1 as the link alone" in r.stdout, "--apply makes them: %r" % r.stdout.strip().splitlines()[-1:])
    now = entries(srv)
    e = now.get(f"report:: pdf {olds[1]}")
    check(e and e["created_at_utc"] == "2026-01-02 03:04:05" and e["title"] == "Back then",
          "created_at the sidecar's published_utc, the sidecar's title")
    check(now.get(f"report:: csv {tb}", {}).get("content") == f"report:: csv {tb}", "the big one's entry the first line alone")
    check(now.get(f"report:: html {olds[0]}", {}).get("content", "").endswith('<h1>"Fleet"</h1>\nlinetwo\n'),
          "an HTML report's text")
    r = report(root, "import", "--apply")
    check(r.returncode == 0 and "0 created (0 as the link alone, too big to embed), 9 already entries" in r.stdout and entries(srv) == now,
          "a second run writes nothing: %r" % r.stdout.strip().splitlines()[-1:])


def server_checks(srv, root, cache, rel, out):
    print("-- GET /reports --")
    st, _, body = srv.req("GET", "/reports")
    rows = json.loads(body) if st == 200 else []
    check(st == 200 and len(rows) == 5, "lists every report: %d %d" % (st, len(rows)))
    check(rows and rows[0]["path"] == out["odd.we!rd"]["path"] and rows[-1]["path"] == rel, "newest first")
    check(rows and rows[-1]["title"] == "Fleet status: October" and rows[-1]["type"] == "html",
          "title from the sidecar, type from the extension")
    check(all(set(r) == {"path", "title", "type", "bytes", "published_utc"} for r in rows), "the fields")
    check(not any(r["path"].split("/")[-1].startswith(".") for r in rows), "no sidecar is listed")
    st, _, _ = srv.req("GET", "/reports", auth=False)
    check(st == 401, "and it wants the password, from loopback too: %d" % st)
    st, _, _ = srv.req("POST", "/reports")
    check(st == 405, "GET only")

    print("-- GET /media/reports/: an HTML report, sandboxed --")
    st, h, body = srv.req("GET", "/" + rel, auth=False)
    csp = h.get("content-security-policy", "")
    check(st == 200 and h.get("content-type") == "text/html; charset=utf-8",
          "served as HTML: %d %r" % (st, h.get("content-type")))
    check(csp.startswith("sandbox") and "allow-scripts" in csp, "Content-Security-Policy: sandbox: %r" % csp)
    check("allow-same-origin" not in csp and "allow-forms" not in csp, "never allow-same-origin (nor forms)")
    check(h.get("x-content-type-options") == "nosniff", "nosniff")
    check(h.get("x-lcars-media") == "nas", "this one from the NAS: %r" % h.get("x-lcars-media"))
    for _ in range(50):
        if (cache / rel).exists():
            break
        time.sleep(0.1)
    st, h, _ = srv.req("GET", "/" + rel, auth=False)
    check(h.get("x-lcars-media") == "cache", "the second from the disk cache: %r" % h.get("x-lcars-media"))
    check(h.get("content-security-policy") == csp and h.get("x-content-type-options") == "nosniff"
          and h.get("content-type") == "text/html; charset=utf-8", "with the same headers")
    st, h, _ = srv.req("HEAD", "/" + rel, auth=False)
    check(st == 200 and h.get("content-security-policy") == csp, "HEAD too")

    print("-- report.py update, through the server's cache --")
    csv = out["weights.csv"]["path"]
    srv.req("GET", "/" + csv, auth=False)
    for _ in range(50):
        if (cache / csv).exists():
            break
        time.sleep(0.1)
    st, h, body = srv.req("GET", "/" + csv, auth=False)
    check(h.get("x-lcars-media") == "cache" and body.startswith(b"day,kg"), "the old one cached and served")
    (root / "new.csv").write_text("day,kg\n2026-10-01,80.1\n2026-10-02,79.8\n")
    r = report(root, "update", csv, str(root / "new.csv"), "--json", cache=cache)
    j = json.loads(r.stdout) if r.returncode == 0 else {}
    check(r.returncode == 0 and j.get("path") == csv and j.get("url") == "https://box.example.ts.net/" + csv,
          "update answers the same path and URL: %r %r" % (j, r.stderr.strip()))
    check((root / csv).read_text().endswith("79.8\n"), "the new content, under the same name")
    side = json.loads((root / csv).with_name("." + (root / csv).name + ".json").read_text())
    check(side.get("title") == "weights" and side.get("published_utc") and side.get("updated_utc"),
          "the sidecar keeps its title and published_utc, gains updated_utc: %r" % side)
    check(not (cache / csv).exists(), "the cached copy is dropped")
    check(not [p for p in (root / csv).parent.iterdir() if p.name.endswith(".part")], "no .part left behind")
    st, h, body = srv.req("GET", "/" + csv, auth=False)
    check(st == 200 and body.endswith(b"79.8\n") and h.get("x-lcars-media") == "nas",
          "the server serves the new bytes: %r" % h.get("x-lcars-media"))
    st, _, body = srv.req("GET", "/reports")
    rows = json.loads(body) if st == 200 else []
    check(sum(1 for x in rows if x["path"] == csv) == 1 and len(rows) == 5, "still one report, listed once")

    print("-- no1.py report --update --")
    # no1.py with its journal POST stood in for: what it would log
    probe = (
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "import no1\n"
        "sent = []\n"
        "no1.http = lambda m, p, b=None, timeout=60: (sent.append((m, p, b)), (201, json.dumps({'id': 7})))[1]\n"
        "code, out = no1.report(['--update', %r, %r, 'fixed the axis'])\n"
        "print(json.dumps({'code': code, 'out': out, 'sent': sent}))\n"
    ) % (str(REPO / "scripts"), csv, str(root / "new.csv"))
    # report.py's own entry to the scratch server (the environment's login
    # wins over ~/.env's), no1.py's log line stood in for
    env = dict(os.environ, LCARS_MEDIA_ROOT=str(root), LCARS_REPORT_BASE="https://box.example.ts.net",
               LCARS_MEDIA_CACHE="0", LCARS_URL=JOURNAL[0], LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS)
    r = subprocess.run([sys.executable, "-B", "-c", probe], env=env, capture_output=True, text=True)
    j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    sent = j.get("sent") or []
    body = sent[0][2] if len(sent) == 1 else {}
    check(j.get("code") == 0 and j.get("out", {}).get("entry_id") == 7, "no1.py updates and logs: %r" % (r.stderr[-300:],))
    check(len(sent) == 1 and sent[0][:2] == ["POST", "/entries"] and body.get("kind") == "no1_log"
          and body.get("title") == "Report updated: weights", "one no1_log entry, \"Report updated: <title>\"")
    check("https://box.example.ts.net/" + csv in body.get("content", "") and "fixed the axis" in body.get("content", ""),
          "with the link and the note: %r" % body.get("content"))

    print("-- the other types --")
    for name in ("weights.csv", "notes.md"):
        st, h, _ = srv.req("GET", "/" + out[name]["path"], auth=False)
        check(st == 200 and h.get("content-type") == "text/plain; charset=utf-8"
              and h.get("content-security-policy") == csp, "%s: text/plain, sandboxed" % name)
    st, h, _ = srv.req("GET", "/" + out["chart.pdf"]["path"], auth=False)
    check(st == 200 and h.get("content-type") == "application/pdf" and "content-security-policy" not in h
          and h.get("x-content-type-options") == "nosniff",
          "a PDF: application/pdf, nosniff, no sandbox (Chromium's viewer will not start in one)")
    st, h, _ = srv.req("GET", "/" + out["odd.we!rd"]["path"], auth=False)
    check(h.get("content-type") == "application/octet-stream", ".bin: a download")

    print("-- what is refused --")
    d = rel.rsplit("/", 1)[0]
    name = rel.rsplit("/", 1)[1]
    for path in ("/%s/.%s.json" % (d, name), "/media/reports/../reports/" + rel.split("/", 2)[2],
                 "/media/reports/%2e%2e/x", "/media/reports/2026/", "/media/reports/" + rel.split("/", 2)[2] + "/"):
        # not a file /media/ serves: from loopback without a password it
        # falls through to the auth check (401); with one, nothing (404)
        st0, _, _ = srv.req("GET", path, auth=False)
        st, _, _ = srv.req("GET", path)
        check(st0 == 401 and st == 404, "%s: %d, %d" % (path, st0, st))
    (root / "outside.html").write_text("secret")
    st, _, _ = srv.req("GET", "/media/reports/../../outside.html")
    check(st == 404, "an escape above the media root: %d" % st)

    print("-- an attachment, as before --")
    att = root / "media" / "2026" / "10" / "01"
    att.mkdir(parents=True)
    (att / "e1-x.txt").write_text("plain")
    (att / "e1-y.html").write_text("<script>alert(1)</script>")
    st, h, _ = srv.req("GET", "/media/2026/10/01/e1-x.txt", auth=False)
    check(st == 200 and "content-security-policy" not in h and h.get("content-type", "").startswith("text/plain"),
          "a .txt attachment: no sandbox header, its old type: %r" % h.get("content-type"))
    st, h, _ = srv.req("GET", "/media/2026/10/01/e1-y.html", auth=False)
    check(h.get("content-type") == "application/octet-stream", "an .html attachment is still a download")


def browser_checks(srv, rel):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check(False, "playwright is needed for the sandbox check")
        return
    print("-- Chromium: the sandbox holds --")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        # the origin's localStorage, as the web UI at /ui/ would leave it
        page.goto(srv.base + "/health")
        page.evaluate("localStorage.setItem('lcars.cfg', 'the password')")
        page.goto(srv.base + "/" + rel)
        page.wait_for_function("document.title !== 't'", timeout=5000)
        t = page.title()
        check(t == "blocked", "the report's script ran and could not read localStorage: %r" % t)
        check(page.evaluate("origin") == "null", "its origin is opaque")

        print("-- Chromium: the web UI's report viewer, at a phone's size --")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        cfg = {"base": srv.base, "user": USER, "pass": PASS}
        ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) {"
                            f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});"
                            "localStorage.setItem('lcars.secret', 'the password'); }")
        ui = ctx.new_page()
        # a cold link to the report's own page: the server knows ./report as a
        # page (lcars_ui_files.h), the boot opens the viewer over the list
        ui.goto(srv.base + "/ui/report/" + rel.split("/", 2)[2])
        try:
            ui.wait_for_selector("#rview iframe:not(.wait)", state="attached", timeout=15000)
        except Exception as e:
            check(False, "the viewer framed the report: %s" % e)
            ctx.close()
            b.close()
            return
        sb = ui.get_attribute("#rview iframe", "sandbox") or ""
        check("allow-scripts" in sb and "allow-same-origin" not in sb, "the frame is sandboxed: %r" % sb)
        check(ui.is_hidden("#rvnote"), "the loading line went with the load")
        fr = next((f for f in ui.frames if "/media/reports/" in f.url), None)
        check(fr is not None, "the report is a frame of the page")
        if fr:
            fr.wait_for_function("document.title !== 't'", timeout=5000)
            check(fr.evaluate("origin") == "null", "the framed document's origin is null")
            t = fr.evaluate("document.title")
            check(t == "blocked", "and its script could not read the page's localStorage: %r" % t)
            got = fr.evaluate("(() => { try { return String(parent.localStorage.getItem('lcars.secret')); }"
                              " catch (e) { return 'blocked'; } })()")
            check(got == "blocked", "nor the parent's: %r" % got)
        w = ui.evaluate("[document.documentElement.scrollWidth, innerWidth,"
                        " Math.round(document.querySelector('#rview iframe').getBoundingClientRect().right)]")
        check(w[0] <= w[1] and w[2] <= w[1], "nothing wider than the screen: %r" % w)
        ui.go_back()
        ui.wait_for_timeout(300)
        check(ui.locator("#rview").count() == 0, "Back closes the viewer")
        check("/report/" not in ui.url, "and leaves its page: %s" % ui.url)
        ctx.close()
        b.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-reports-"))
    root, cache = tmp / "root", tmp / "cache"
    root.mkdir()
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        build(binary)
    srv = Server(binary, tmp, root, cache)
    JOURNAL[0] = srv.base
    try:
        st, _, _ = srv.req("GET", "/reports")
        check(st == 503, "GET /reports with the media root unmounted: %d" % st)
        rel, out = script_checks(tmp, root)
        server_checks(srv, root, cache, rel, out)
        entry_checks(srv, tmp)
        if os.environ.get("BROWSER", "1") != "0":
            browser_checks(srv, rel)
    finally:
        srv.stop()
    print("\nreports: %d checks, %d failures" % (checks[0], len(fails)))
    if fails:
        print("server log and files kept in", tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
