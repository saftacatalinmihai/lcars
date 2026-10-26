#!/usr/bin/env python3
"""POST /publish/<id> and POST /publish/card, the Share sheet's Post
(docs/design/social-publish.md 3.1 and 3.8; lcars_publish.h).

    python3 test/publish.py     (~20s; LCARS_TEST_BIN=<binary> skips the build)

scripts/publish.py is stood in for ($LCARS_PUBLISH_SCRIPT) by a script that
keeps its argv, environment and pid and answers as the run's mode file says
(a JSON line, an exit status, a sleep). The real publish.py is
scripts/test_publish.py's; this is the route around it:

- the guard: the owner's login with X-LCARS-Client runs it; a wrong
  password a 401; without the header a 403; Number One's, the crew's and
  the steward's logins a 403, with or without it; the stand-in never started on a refusal;
- the argv: `post <id> --networks a,b --by tap [--dry-run]`, `card <url>`
  (a 2 KB link whole), nothing of a body's other members passed on;
- the environment: LCARS_URL this server, no LCARS_ENGINEER_KEY, the
  LCARS_PUB_* settings passed through;
- the refusals before a run: an id not digits (404), no networks, a name
  not a lowercase word, nine of them (400), not JSON (415), GET (405); the
  card's url missing, not http(s), with a space, over 2 KB (400), sent as
  ?url= (405: a request target is cut at 255 bytes);
- the exit status: 0 its JSON as a 200, 2 a 400, 4 a 404, 1 a 500;
- one at a time: a second while the first runs is a 429;
- the timeout: $LCARS_PUBLISH_TIMEOUT=2 is a 504 and the child killed;
- the log: one "HTTP publish:" line a run, the id and networks and no url.

A scratch server is built from the lcars-release compile line (to a temp
path, never ./lcars) on an empty database and temp directories; nothing
here touches lcars.db, the network or a running server.
"""
import base64
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import killclean  # noqa: E402 - its scratch goes when the run is killed
from caldav import build, free_port  # noqa: E402
from quick import gone  # noqa: E402

MAIN = ("t", "t")
NO1 = ("no1", "no1-password-0123456789")
CREW = ("crew", "crew-password-0123456789")
STEWARD = ("steward", "steward-password-0123456789")

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


STUB = """#!/usr/bin/env python3
import json, os, sys, time
mode = json.load(open(os.environ["STUB_MODE"]))
with open(os.environ["STUB_OUT"], "w") as f:
    json.dump({"argv": sys.argv[1:], "env": dict(os.environ), "pid": os.getpid()}, f)
if mode.get("sleep"):
    time.sleep(mode["sleep"])
print(json.dumps(mode.get("out", {"ok": True})))
sys.exit(mode.get("exit", 0))
"""


class Server:
    def __init__(self, binary, tmp, timeout=None):
        self.port = free_port()
        self.stub_out = tmp / "stub.json"
        self.mode_file = tmp / "mode.json"
        self.mode()
        stub = tmp / "publish.py"
        stub.write_text(STUB)
        env = dict(os.environ, LCARS_EMBED="0", LCARS_PUBLISH_SCRIPT=str(stub),
                   STUB_OUT=str(self.stub_out), STUB_MODE=str(self.mode_file),
                   LCARS_URL="http://elsewhere.invalid:1", LCARS_ENGINEER_KEY="not.for.publish",
                   LCARS_PUB_MASTODON="example.social:stand-in-token", LCARS_PUB_DRY="1",
                   LCARS_MEDIA_ROOT=str(tmp / "nas"), LCARS_MEDIA_CACHE=str(tmp / "cache"),
                   LCARS_AUTH_USER=MAIN[0], LCARS_AUTH_PASS=MAIN[1],
                   LCARS_NO1_USER=NO1[0], LCARS_NO1_PASS=NO1[1],
                   LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
                   LCARS_STEWARD_USER=STEWARD[0], LCARS_STEWARD_PASS=STEWARD[1])
        env.pop("LCARS_PUBLISH_TIMEOUT", None)
        if timeout:
            env["LCARS_PUBLISH_TIMEOUT"] = str(timeout)
        self.log_path = tmp / "server.log"
        self.log = open(self.log_path, "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("publish: the scratch server did not come up; see " + str(self.log_path))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()
        self.log.close()

    def mode(self, **m):
        self.mode_file.write_text(json.dumps(m))

    def req(self, method, path, body=None, login=MAIN, client=True, ctype="application/json", timeout=30):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        h = {"Authorization": "Basic " + base64.b64encode(f"{login[0]}:{login[1]}".encode()).decode()}
        if client:
            h["X-LCARS-Client"] = "test"
        if body is not None:
            h["Content-Type"] = ctype
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def post(self, id_="12", nets=("mastodon",), dry=None, **kw):
        body = {"networks": list(nets)}
        if dry is not None:
            body["dry_run"] = dry
        return self.req("POST", f"/publish/{id_}", body, **kw)

    def card(self, url, **kw):
        return self.req("POST", "/publish/card", {"url": url}, **kw)

    def saw(self):
        try:
            d = json.loads(self.stub_out.read_text())
        except (OSError, ValueError):
            return None
        self.stub_out.unlink()
        return d

    def started(self, secs=5):
        for _ in range(int(secs * 20)):
            try:
                return json.loads(self.stub_out.read_text())
            except (OSError, ValueError):
                time.sleep(0.05)
        return None


def run_checks(s):
    print("-- the guard --")
    s.mode(out={"dry": True, "results": [{"network": "mastodon", "status": "dry"}]})
    st, a = s.post()
    check(st == 200 and a.get("results", [{}])[0].get("status") == "dry", "the owner from the pages: 200, publish.py's answer (%s %s)" % (st, a))
    check(s.saw() is not None, "the stand-in ran")
    st, a = s.post(client=False)
    check(st == 403 and "X-LCARS-Client" in str(a) and s.saw() is None, "the owner without X-LCARS-Client: 403, nothing run (%s)" % st)
    st, _ = s.card("https://example.com/a", client=False)
    check(st == 403 and s.saw() is None, "a card without it: 403 (%s)" % st)
    st, _ = s.post(login=("t", "wrong"))
    st2, _ = s.card("https://example.com/a", login=("t", "wrong"))
    check(st == 401 and st2 == 401 and s.saw() is None, "a wrong password: 401 on both, nothing run (%s %s)" % (st, st2))
    for who, login in (("Number One's", NO1), ("the crew's", CREW), ("the steward's", STEWARD)):
        st, _ = s.post(login=login)
        st2, _ = s.card("https://example.com/a", login=login)
        check(st == 403 and st2 == 403 and s.saw() is None, "%s login: 403 on both, nothing run (%s %s)" % (who, st, st2))

    print("-- the argv and the environment --")
    s.post("4021", ("mastodon", "bluesky"), dry=True)
    d = s.saw() or {}
    check(d.get("argv") == ["post", "4021", "--networks", "mastodon,bluesky", "--by", "tap", "--dry-run"],
          "post <id> --networks a,b --by tap --dry-run (%s)" % d.get("argv"))
    s.req("POST", "/publish/4021", {"networks": ["bluesky"], "dry_run": False, "text": "--by cron", "by": "x"})
    d = s.saw() or {}
    check(d.get("argv") == ["post", "4021", "--networks", "bluesky", "--by", "tap"],
          "dry_run false: no --dry-run, a body's other members not passed on (%s)" % d.get("argv"))
    env = d.get("env", {})
    check(env.get("LCARS_URL") == f"http://127.0.0.1:{s.port}", "LCARS_URL is this server (%s)" % env.get("LCARS_URL"))
    check("LCARS_ENGINEER_KEY" not in env, "no LCARS_ENGINEER_KEY")
    check(env.get("LCARS_PUB_MASTODON") == "example.social:stand-in-token" and env.get("LCARS_PUB_DRY") == "1",
          "the LCARS_PUB_* settings passed through")
    s.card("https://example.com/blog/two?a=1&b=2")
    d = s.saw() or {}
    check(d.get("argv") == ["card", "https://example.com/blog/two?a=1&b=2"], "card <url>, the query kept (%s)" % d.get("argv"))
    long = "https://example.com/" + "a" * 2028
    s.card(long)
    d = s.saw() or {}
    check(d.get("argv") == ["card", long], "a 2048-byte link whole, past the request line's 255 (%s)" % len((d.get("argv") or ["", ""])[1]))

    print("-- the refusals, nothing run --")
    for id_, body, ctype, want, why in (
            ("abc", {"networks": ["mastodon"]}, "application/json", 404, "an id not digits"),
            ("12a", {"networks": ["mastodon"]}, "application/json", 404, "an id with a letter"),
            ("12345678901", {"networks": ["mastodon"]}, "application/json", 404, "an 11-digit id"),
            ("12", {}, "application/json", 400, "no networks"),
            ("12", {"networks": []}, "application/json", 400, "no network named"),
            ("12", {"networks": "mastodon"}, "application/json", 400, "networks not a list"),
            ("12", {"networks": ["Mastodon"]}, "application/json", 400, "a name not lowercase"),
            ("12", {"networks": ["mast odon"]}, "application/json", 400, "a name with a space"),
            ("12", {"networks": ["--dry-run"]}, "application/json", 400, "a name that is a flag"),
            ("12", {"networks": [1]}, "application/json", 400, "a name not a string"),
            ("12", {"networks": ["a"] * 9}, "application/json", 400, "nine networks"),
            ("12", {"networks": ["x" * 17]}, "application/json", 400, "a 17-letter name"),
            ("12", "networks=mastodon", "text/plain", 415, "not JSON")):
        st, _ = s.req("POST", f"/publish/{id_}", body, ctype=ctype)
        check(st == want and s.saw() is None, "%s: %d (%s)" % (why, want, st))
    st, _ = s.req("GET", "/publish/12")
    check(st == 405 and s.saw() is None, "GET /publish/<id>: 405 (%s)" % st)
    st, _ = s.req("GET", "/publish/card?url=https%3A%2F%2Fexample.com%2F")
    check(st == 405 and s.saw() is None, "GET /publish/card: 405, the url in a body only (%s)" % st)
    st, _ = s.req("POST", "/publish", {"networks": ["mastodon"]})
    check(st == 404 and s.saw() is None, "POST /publish: 404 (%s)" % st)
    for body, ctype, why in (({}, "application/json", "no url"), ({"url": 5}, "application/json", "a url not a string"),
                             ("https://example.com/", "text/plain", "not JSON")):
        st, _ = s.req("POST", "/publish/card", body, ctype=ctype)
        check(st == 400 and s.saw() is None, "a card with %s: 400 (%s)" % (why, st))
    for url, why in (("ftp://example.com/a", "not http(s)"), ("file:///etc/passwd", "a file url"),
                     ("https://example.com/a b", "a space"), ("https://example.com/a\nb", "a newline"),
                     ("https://example.com/" + "a" * 2029, "2049 bytes"), ("--help", "a flag")):
        st, _ = s.card(url)
        check(st == 400 and s.saw() is None, "a card's url with %s: 400 (%s)" % (why, st))

    print("-- the exit status --")
    for code, want in ((2, 400), (4, 404), (1, 500)):
        s.mode(out={"error": "said by publish.py"}, exit=code)
        st, a = s.post()
        check(st == want and isinstance(a, dict) and a.get("error") == "said by publish.py",
              "exit %d: %d with its words (%s %s)" % (code, want, st, a))
    s.saw()

    print("-- one at a time --")
    s.mode(out={"results": []}, sleep=2)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=s.post()))
    t.start()
    check(s.started() is not None, "the first run started")
    t0 = time.time()
    st, _ = s.card("https://example.com/a")
    check(st == 429 and time.time() - t0 < 1.5, "a card while a post runs: 429 at once (%s)" % st)
    t.join(10)
    check((first.get("r") or (0,))[0] == 200, "and the first answered (%s)" % (first.get("r"),))
    s.saw()
    s.mode(out={"card": {}})
    st, _ = s.card("https://example.com/a")
    check(st == 200, "the slot free again (%s)" % st)
    s.saw()


def timeout_checks(s):
    print("-- the timeout --")
    s.mode(out={"results": []}, sleep=30)
    t0 = time.time()
    st, _ = s.post()
    took = time.time() - t0
    d = s.saw()
    check(st == 504 and 1.5 < took < 5, "LCARS_PUBLISH_TIMEOUT=2: 504 (%s in %.1fs)" % (st, took))
    check(d is not None and gone(d["pid"]), "and the child is killed")
    s.mode(out={"results": []})
    st, _ = s.post()
    check(st == 200, "and the slot free again (%s)" % st)


def log_checks(s):
    print("-- the log --")
    time.sleep(0.3)
    log = s.log_path.read_text(errors="replace")
    lines = [ln for ln in log.splitlines() if ln.startswith("HTTP publish:")]
    check(any(ln.startswith("HTTP publish: post #4021 mastodon,bluesky dry -> exit 0 ") for ln in lines),
          "a post's line: its id, networks and dry")
    check(any(ln.startswith("HTTP publish: card -> exit 0 ") for ln in lines), "a card's line")
    check("example.com/blog" not in log, "no card url in the log")


def main():
    tmp = pathlib.Path(killclean.mkdtemp("lcars-publish-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = str(tmp / "lcars")
        build(binary)
    (tmp / "s1").mkdir()
    (tmp / "s2").mkdir()
    s = Server(binary, tmp / "s1")
    try:
        run_checks(s)
        log_checks(s)
    finally:
        s.stop()
    s = Server(binary, tmp / "s2", timeout=2)
    try:
        timeout_checks(s)
    finally:
        s.stop()
    print(f"\n{checks[0] - len(fails)}/{checks[0]} checks passed")
    if fails:
        print("kept for a look:", tmp)
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
