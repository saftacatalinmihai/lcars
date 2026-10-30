#!/usr/bin/env python3
"""Offline, end to end: the page with no network at all.

    python3 test/offline.py        (~30s; LCARS_TEST_BIN=<binary> skips the build)

The QuickJS suite (tests.js, "offline: writes are kept on this device") covers
the outbox's logic against a fake API. This is the part only a real browser can
show: that the page itself comes up with the network gone (the service worker's
shell), paints the journal from IndexedDB, keeps the writes made meanwhile in
IndexedDB across a reload, and sends them to a real server when the network
comes back, merging an entry that was edited on both sides.

A scratch server is built from the lcars-release compile line (to a temp path,
never ./lcars) and run on an empty database; nothing here touches lcars.db.
"""
import base64
import http.server
import json
import os
import pathlib
import shutil
import socket
import socketserver
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import threading
import time
import urllib.request

from playwright.sync_api import sync_playwright

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
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
        sys.exit("offline: cannot find the lcars-release compile line in `make -n`")
    print("building a scratch server ...", flush=True)
    r = subprocess.run(line.replace(" -o lcars ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("offline: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp, extra=None):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_MEDIA_CACHE="0",
                   LCARS_MEDIA_ROOT=str(tmp), LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS)
        env.update(extra or {})  # a caller's own (film_console.py: the embedder on)
        self.log = open(tmp / "server.log", "w")
        self.proc = killclean.child(subprocess.Popen([str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + "/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("offline: the scratch server did not come up")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()

    def json(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        rq = urllib.request.Request(self.base + path, data=data, method=method,
                                    headers={"Authorization": AUTH,
                                             "Content-Type": "application/json"})
        with urllib.request.urlopen(rq, timeout=10) as r:
            return json.loads(r.read() or b"null")


class Static(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI), **kw)

    def log_message(self, *a):
        pass


def put(page, sel, value):
    """A field's value, as typing would leave it; the reader hides the editor."""
    page.evaluate("([s, v]) => { document.querySelector(s).value = v; }", [sel, value])


def page_checks(srv, eid):
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Static) as ui:
        threading.Thread(target=ui.serve_forever, daemon=True).start()
        origin = "http://127.0.0.1:%d" % ui.server_address[1]
        cfg = json.dumps({"base": srv.base, "user": USER, "pass": PASS})
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            # only on the first visit: a later one must find what the page kept
            ctx.add_init_script("if (!localStorage.getItem('lcars.cfg')) "
                                "localStorage.setItem('lcars.cfg', %s);" % json.dumps(cfg))
            page = ctx.new_page()
            page.on("pageerror", lambda e: fails.append("page error: " + str(e)))
            if os.environ.get("LCARS_TEST_CONSOLE"):
                page.on("console", lambda m: print("  console:", m.text))
            row = f'.item[data-id="{eid}"]'

            print("-- online: the shell and the journal are kept --")
            page.goto(origin + "/")
            page.wait_for_selector(row, timeout=15000)
            page.evaluate("navigator.serviceWorker.ready")
            page.reload()                       # now under the worker, and mirrored
            page.wait_for_selector(row, timeout=15000)
            page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=10000)
            # the mirror write after the load: waited for, not slept on (a
            # fixed 1.5s can lose the race on a busy box, and the offline reload
            # below then had nothing to show)
            page.wait_for_function(f"mirrorRead().then(g => !!g && g.rows.some(r => r.id === {eid}))",
                                   timeout=15000, polling=200)

            print("-- the network goes --")
            ctx.set_offline(True)
            page.reload()
            page.wait_for_selector(row, timeout=15000)
            check(True, "the page comes up with no network, the entry on screen")
            page.wait_for_function("!document.querySelector('#hq').hidden", timeout=15000)
            # innerText follows the pill's text-transform (Antonio, upper case)
            check("offline" in page.inner_text("#hq").lower(), "the header says offline")
            check(not page.evaluate("document.querySelector('#ov').classList.contains('on')"),
                  "and no password is asked for")

            page.evaluate(f"select({eid})")
            put(page, "#content", "first line\nsecond line\nadded offline")
            page.evaluate("markDirty(); save()")
            page.wait_for_function(f"ob.ops.has({eid}) && !document.body.classList.contains('dirty')",
                                   timeout=10000)
            check(True, "an edit is saved on the device")
            page.evaluate("newEntry()")
            put(page, "#e_kind", "personal_log")
            put(page, "#e_head", "written on a plane")
            put(page, "#content", "no network at all")
            page.evaluate("markDirty(); save()")
            page.wait_for_function("st.sel && isLocalId(st.sel.id)", timeout=10000)
            check(True, "a new entry is created on the device")

            # someone else, meanwhile, edits the same entry on the server
            srv.json("PUT", f"/entries/{eid}", {"content": "server's own line\nfirst line\nsecond line"})

            page.reload()
            page.wait_for_selector(row, timeout=15000)
            page.wait_for_function("ob.ops.size === 2", timeout=10000)
            check(True, "both survive a reload with no network")
            check(page.evaluate("st.all[0].title") == "written on a plane",
                  "the new entry is back in the list, on top")
            check("added offline" in page.evaluate(f"st.byId.get({eid}).content"),
                  "the edit is back on its row")

            print("-- the network comes back --")
            ctx.set_offline(False)
            page.evaluate("obTry()")
            page.wait_for_selector("#obt0", timeout=20000)
            merged = page.input_value("#obt0")
            check("server's own line" in merged and "added offline" in merged,
                  "the entry edited on both sides is offered merged: " + json.dumps(merged))
            page.click("#obKeep")
            page.wait_for_function("ob.ops.size === 0 && document.querySelector('#hq').hidden",
                                   timeout=20000)
            rows = srv.json("GET", "/entries?limit=50")
            made = [r for r in rows if r["title"] == "written on a plane"]
            check(len(made) == 1, "the new entry is on the server, once")
            check(srv.json("GET", f"/entries/{eid}")["content"] == merged,
                  "and the merged text")
            if made:
                check(page.evaluate("st.all[0].id") == made[0]["id"],
                      "the row on screen took the server's id")
            browser.close()


def main():
    scratch = pathlib.Path(os.environ.get("LCARS_TEST_TMP") or pathlib.Path.home() / ".cache")
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-off-", dir=scratch))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        build(binary)
    srv = Server(binary, tmp)
    try:
        eid = srv.json("POST", "/entries", {"kind": "personal_log", "title": "on the server",
                                            "content": "first line\nsecond line"})["id"]
        page_checks(srv, eid)
    finally:
        srv.stop()
    print("\noffline: %d checks, %d failures" % (checks[0], len(fails)))
    for f in fails:
        print("  - " + f)
    if fails:
        print("server log kept in", tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
