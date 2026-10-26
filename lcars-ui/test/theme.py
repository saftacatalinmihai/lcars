#!/usr/bin/env python3
"""The console's theme in the journal (lcars_theme.h, docs/design/theming.md
5 and 6), end to end against a scratch server.

  1. a new journal: GET /theme is lcars, no entry;
  2. PUT /theme: a built-in by name (the settings entry titled `theme`
     made, then rewritten in place), omarchy's colors.toml and a btop file
     as a raw text/plain body with ?name=, the same as JSON {name, text},
     lcars back to the default;
  3. the refusals, each writing nothing: a built-in that is not shipped, a
     name that climbs or is too long, a text of neither format, a control
     byte, a body over 64 KB (413), JSON of the wrong shape, an empty body;
  4. the entry by hand: not JSON is lcars with `error`, and a PUT refused
     (409) rather than overwriting it; the lowest live id winning;
  5. who may: the crew and the steward read and may not write (403), no
     login 401, POST 405, GET / lists the route;
  6. `lcars-cli theme`: show, set, load (a colors.toml named for its
     folder, --name, stdin), reset, --json, the refusals (exit 1), usage
     errors (exit 2), a limited login's 403, a server older than the route;
  7. omarchy's hook (scripts/omarchy/lcars-theme-set) in a scratch HOME:
     colors.toml preferred over btop.theme, btop.theme alone, the login
     from ~/.config/lcars/env, and every failure (no server, no
     lcars-cli, no theme folder) one line on stderr, exit 0, at once.

The server is a scratch build (kinds.py's: `make -n lcars-release`
compiled to a temp path, never `make` itself) on an empty database,
serving this checkout's lcars-ui/ (LCARS_UI_DIR) so the built-ins are the
shipped files.

    python3 test/theme.py               # builds the server and lcars-cli (~40s)
    LCARS_TEST_BIN=/path/to/lcars LCARS_TEST_CLI=/path/to/lcars-cli python3 test/theme.py

Nothing here touches the journal or a running server.
"""
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time

import killclean  # its scratch and servers go when the run is killed
import kinds as K
from kinds import CREW, MAIN, STEWARD, check

UI = K.UI
REPO = K.REPO
HOOK = REPO / "scripts" / "omarchy" / "lcars-theme-set"

TOML = ('mode = "light"\naccent = "#286983"\nbackground = "#faf4ed"\nforeground = "#575279"\n'
        "red = '#b4637a'\nyellow = \"#ea9d34\"\n# a comment\n")
BTOP = (UI / "themes" / "nord.theme").read_text()


def server(binary, cwd):
    return K.Server(binary, cwd, env={"LCARS_UI_DIR": str(UI)})


def theme_of(s, login=MAIN):
    return s.req("GET", "/theme", login=login)


def put(s, body, path="/theme", ctype="application/json", login=MAIN):
    return s.req("PUT", path, body, login=login, ctype=ctype)


def entries(s):
    return [e for e in s.req("GET", "/entries?kind=settings&deleted=all")[1] if e["title"] == "theme"]


def routes(s):
    print("a new journal: lcars, no entry")
    st, doc = theme_of(s)
    check(st == 200 and doc == {"name": "lcars", "fmt": "builtin", "text": "", "entry": None, "error": ""},
          f"GET /theme: lcars, no entry (got {st}, {doc})")

    print("PUT: a built-in, a file's text either way, lcars")
    st, doc = put(s, {"name": "nord"})
    eid = doc.get("entry") if isinstance(doc, dict) else None
    check(st == 200 and doc.get("name") == "nord" and doc.get("fmt") == "builtin" and eid,
          f"{{name: nord}}: answered as GET, with the entry (got {st}, {doc})")
    row = s.entry(eid) if eid else {}
    check(row.get("kind") == "settings" and row.get("title") == "theme"
          and json.loads(row.get("content") or "null") == {"v": 1, "name": "nord", "fmt": "builtin", "text": ""},
          f"the entry: settings, theme, {{v,name,fmt,text}} (got {row})")
    st, doc = put(s, TOML, path="/theme?name=rose%20pine%20dawn", ctype="text/plain")
    check(st == 200 and doc.get("name") == "rose pine dawn" and doc.get("fmt") == "omarchy" and doc.get("text") == TOML
          and doc.get("entry") == eid, f"a colors.toml as text/plain, ?name=: omarchy, the same entry (got {st}, {doc})")
    st, doc = put(s, BTOP, path="/theme", ctype="text/plain")
    check(st == 200 and doc.get("name") == "custom" and doc.get("fmt") == "btop" and doc.get("text") == BTOP,
          f"a btop file with no name: custom, btop (got {st}, {doc.get('name')}, {doc.get('fmt')})")
    st, doc = put(s, {"name": "mine", "text": TOML})
    check(st == 200 and doc.get("name") == "mine" and doc.get("fmt") == "omarchy",
          f"JSON {{name, text}} the same (got {st}, {doc.get('fmt')})")
    check(len(entries(s)) == 1, "still one theme entry")
    st, doc = put(s, {"name": "lcars"})
    check(st == 200 and doc.get("name") == "lcars" and doc.get("text") == "", f"lcars: the default again (got {doc})")
    put(s, {"name": "gruvbox_dark"})

    print("the refusals write nothing")
    before = s.entry(eid)["content"]
    for body, ctype, path, code, word in (
            ({"name": "nosuch"}, "application/json", "/theme", 400, "no built-in theme nosuch"),
            ({"name": "../index"}, "application/json", "/theme", 400, "name"),
            ({"name": "x" * 65}, "application/json", "/theme", 400, "name"),
            ({"name": ".hidden"}, "application/json", "/theme", 400, "name"),
            ({"name": "a", "text": "hello there"}, "application/json", "/theme", 400, "not a theme file"),
            ({"name": "a", "text": 'red = "#b4637a"\x01'}, "application/json", "/theme", 400, "not a theme file"),
            ({"name": "a", "text": 5}, "application/json", "/theme", 400, "text is a string"),
            ({"text": TOML}, "application/json", "/theme", 400, "the body is"),
            ("[1]", "application/json", "/theme", 400, "the body is"),
            ("just words", "text/plain", "/theme", 400, "not a theme file"),
            ("", "text/plain", "/theme", 400, "no theme in the body"),
            (TOML, "text/plain", "/theme?name=..%2Fx", 400, "name"),
            (TOML + "#" * (64 * 1024), "text/plain", "/theme", 413, "64"),
    ):
        st, doc = put(s, body, path=path, ctype=ctype)
        err = doc.get("error", "") if isinstance(doc, dict) else str(doc)
        check(st == code and word in err, f"{code}: {str(body)[:40]!r} ({st}, {err[:90]!r})")
    check(s.entry(eid)["content"] == before and theme_of(s)[1]["name"] == "gruvbox_dark", "nothing written by any")

    print("the entry by hand: not JSON, the lowest id")
    s.req("PUT", f"/entries/{eid}", {"content": "my own words"})
    st, doc = theme_of(s)
    check(st == 200 and doc["name"] == "lcars" and doc["entry"] == eid and "not a JSON object" in doc["error"],
          f"not JSON: lcars, the error said (got {doc})")
    st, doc = put(s, {"name": "nord"})
    check(st == 409 and s.entry(eid)["content"] == "my own words", f"and a PUT refused, not overwriting it ({st})")
    s.req("PUT", f"/entries/{eid}", {"content": json.dumps({"v": 1, "name": "nord", "fmt": "builtin", "text": ""})})
    st, doc = s.req("POST", "/entries", {"kind": "settings", "title": "theme",
                                         "content": json.dumps({"v": 1, "name": "dracula", "text": ""})})
    check(theme_of(s)[1]["name"] == "nord", "a second entry: the lowest live id wins")
    s.req("DELETE", f"/entries/{eid}")
    check(theme_of(s)[1]["name"] == "dracula", "the lowest deleted: the next one")
    s.req("PUT", f"/entries/{eid}", {"deleted": 0})

    print("who may")
    for login in (CREW, STEWARD):
        st, doc = theme_of(s, login=login)
        check(st == 200 and doc["name"] == "nord", f"{login[0]} reads it ({st})")
        st, doc = put(s, {"name": "dracula"}, login=login)
        check(st == 403 and theme_of(s)[1]["name"] == "nord", f"{login[0]} may not write it ({st})")
        st, doc = put(s, TOML, path="/theme?name=x", ctype="text/plain", login=login)
        check(st == 403, f"{login[0]}: nor as text/plain ({st})")
    st, doc = s.req("GET", "/theme", login=None)
    check(st == 401, f"no login: 401 ({st})")
    st, doc = s.req("POST", "/theme", {"name": "nord"})
    check(st == 405, f"POST: 405 ({st})")
    st, doc = s.req("GET", "/")
    check(st == 200 and any(r.get("path") == "/theme" for r in doc.get("routes", doc.get("endpoints", []))),
          "GET / lists /theme")


def cli_theme(binary, cli, tmp):
    print("lcars-cli theme")
    s = server(binary, tmp / "cli")

    def run(*args, login=MAIN, url=None, stdin=None):
        env = dict(os.environ, LCARS_URL=url or f"http://127.0.0.1:{s.port}",
                   LCARS_AUTH_USER=login[0], LCARS_AUTH_PASS=login[1])
        r = subprocess.run([str(cli), *args], env=env, capture_output=True, text=True, timeout=30, input=stdin)
        return r.returncode, r.stdout, r.stderr

    try:
        rc, out, err = run("theme")
        check(rc == 0 and out.strip() == "lcars (the default)", f"theme: lcars ({rc}, {out!r})")
        rc, out, err = run("theme", "set", "nord")
        check(rc == 0 and out.splitlines()[0] == "nord" and "settings entry #" in out, f"set nord ({rc}, {out!r})")
        folder = tmp / "rose-pine-dawn"
        folder.mkdir()
        (folder / "colors.toml").write_text(TOML)
        rc, out, err = run("theme", "load", str(folder / "colors.toml"))
        check(rc == 0 and out.startswith(f"rose-pine-dawn (omarchy, {len(TOML)} bytes)"),
              f"load a colors.toml: named for its folder ({rc}, {out!r}, {err!r})")
        (tmp / "my.theme").write_text(BTOP)
        rc, out, err = run("theme", "load", str(tmp / "my.theme"))
        check(rc == 0 and out.startswith("my (btop,"), f"load a btop file: named for it ({out!r})")
        rc, out, err = run("theme", "load", str(folder / "colors.toml"), "--name", "Dawn")
        check(rc == 0 and out.startswith("Dawn (omarchy"), f"--name ({out!r})")
        rc, out, err = run("theme", "load", "-", stdin=TOML)
        check(rc == 0 and out.startswith("custom (omarchy"), f"load - reads stdin ({out!r})")
        rc, out, err = run("--json", "theme")
        doc = json.loads(out) if rc == 0 else {}
        check(doc.get("name") == "custom" and doc.get("text") == TOML, "--json: the server's answer")
        rc, out, err = run("theme", "reset")
        check(rc == 0 and out.startswith("lcars (the default)"), f"reset ({out!r})")
        rc, out, err = run("theme", "set", "nosuch")
        check(rc == 1 and "no built-in theme nosuch" in err and "HTTP 400" in err, f"the server's refusal, exit 1 ({err.strip()!r})")
        (tmp / "words.txt").write_text("not colours")
        rc, out, err = run("theme", "load", str(tmp / "words.txt"))
        check(rc == 1 and "not a theme file" in err, f"a file of neither format, exit 1 ({err.strip()!r})")
        rc, out, err = run("theme", "load", str(tmp / "missing.toml"))
        check(rc == 1 and out == "", f"a missing file, exit 1 ({err.strip()!r})")
        for args in (("theme", "set"), ("theme", "frob"), ("theme", "reset", "x"), ("theme", "set", "nord", "--name", "x")):
            rc, out, err = run(*args)
            check(rc == 2 and out == "", f"{' '.join(args)}: a usage error, exit 2 ({rc}, {err.strip()!r})")
        rc, out, err = run("theme", login=CREW)
        check(rc == 0 and out.startswith("lcars"), "the crew's login shows it")
        rc, out, err = run("theme", "set", "nord", login=CREW)
        check(rc == 1 and "403" in err, f"and may not set it, exit 1 ({err.strip()!r})")
        rc, out, err = run("--help")
        check("theme" in out and "theme load <file>" in out, "--help names it")
    finally:
        s.stop()

    class Old(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"error":"No route","status":404}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    old = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Old)
    threading.Thread(target=old.serve_forever, daemon=True).start()
    try:
        rc, out, err = run("theme", url=f"http://127.0.0.1:{old.server_address[1]}")
        check(rc == 1 and "has no /theme" in err, f"an older server: said so, exit 1 ({err.strip()!r})")
    finally:
        old.shutdown()


def hook(binary, cli, tmp):
    print("omarchy's hook")
    s = server(binary, tmp / "hook")
    home = tmp / "home"
    cur = home / ".local" / "state" / "omarchy" / "current" / "theme"
    cur.mkdir(parents=True)

    def run(*args, env=None, login=True, port=None):
        e = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LCARS_CLI": str(cli)}
        if login:
            e.update(LCARS_URL=f"http://127.0.0.1:{port or s.port}", LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1])
        e.update(env or {})
        t0 = time.monotonic()
        p = subprocess.Popen(["sh", str(HOOK), *args], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        rc = p.wait(10)
        took = time.monotonic() - t0
        out, err = p.communicate(timeout=20)  # the background request's line, when it has one
        return rc, took, out, err

    def landed(name, fmt):
        for _ in range(50):
            doc = theme_of(s)[1]
            if doc.get("name") == name and doc.get("fmt") == fmt:
                return True
            time.sleep(0.1)
        return False

    try:
        (cur / "colors.toml").write_text(TOML)
        (cur / "btop.theme").write_text(BTOP)
        rc, took, out, err = run("rose-pine-dawn")
        check(rc == 0 and took < 2 and landed("rose-pine-dawn", "omarchy") and err == "",
              f"colors.toml preferred, under the name omarchy gives, quietly ({rc}, {took:.2f}s, {err!r})")
        (cur / "colors.toml").unlink()
        rc, took, out, err = run("old-one")
        check(rc == 0 and landed("old-one", "btop"), f"btop.theme when there is no colors.toml ({rc}, {err!r})")
        (cur / "colors.toml").write_text(TOML)
        conf = home / ".config" / "lcars"
        conf.mkdir(parents=True)
        (conf / "env").write_text(f"LCARS_URL=http://127.0.0.1:{s.port}\nLCARS_AUTH_USER={MAIN[0]}\n"
                                  f"LCARS_AUTH_PASS={MAIN[1]}\n")
        rc, took, out, err = run("from-env-file", login=False)
        check(rc == 0 and landed("from-env-file", "omarchy"), f"the login from ~/.config/lcars/env ({err!r})")
        (conf / "env").unlink()

        dead = K.free_port()
        rc, took, out, err = run("nowhere", port=dead)
        check(rc == 0 and took < 2 and len(err.strip().splitlines()) == 1
              and err.startswith("lcars-theme-set: the LCARS server did not take nowhere"),
              f"no server: exit 0 at once, one line on stderr ({rc}, {took:.2f}s, {err!r})")
        rc, took, out, err = run("x", env={"LCARS_CLI": str(tmp / "no-such-cli")})
        check(rc == 0 and len(err.strip().splitlines()) == 1 and "not found" in err, f"no lcars-cli: one line ({err!r})")
        rc, took, out, err = run("x", login=False, env={"LCARS_CLI": str(cli)})
        check(rc == 0 and len(err.strip().splitlines()) == 1, f"no login: one line ({err!r})")
        shutil.rmtree(cur)
        rc, took, out, err = run("x")
        check(rc == 0 and len(err.strip().splitlines()) == 1 and "no colors.toml or btop.theme" in err,
              f"no theme folder: one line ({err!r})")
        check(theme_of(s)[1]["name"] == "from-env-file", "and none of the failures wrote anything")
        sh = subprocess.run(["sh", "-n", str(HOOK)], capture_output=True, text=True)
        check(sh.returncode == 0, f"plain sh parses it ({sh.stderr!r})")
        if shutil.which("dash"):
            sh = subprocess.run(["dash", "-n", str(HOOK)], capture_output=True, text=True)
            check(sh.returncode == 0, f"and dash ({sh.stderr!r})")
        check(os.access(HOOK, os.X_OK), "the hook is executable")
    finally:
        s.stop()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-theme-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        K.build(binary)
    s = server(binary, tmp / "one")
    try:
        routes(s)
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()
    cli = os.environ.get("LCARS_TEST_CLI")
    if not cli:
        cli = tmp / "lcars-cli"
        K.build(cli, "lcars-cli", "lcars_cli.c", "lcars-cli")
    cli_theme(binary, cli, tmp)
    hook(binary, cli, tmp)
    if K.fails:
        print(f"\n{len(K.fails)} of {K.checks[0]} checks failed; server logs under {tmp}")
        sys.exit(1)
    print(f"\ntheme: all {K.checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
