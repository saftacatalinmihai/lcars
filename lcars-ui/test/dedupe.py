#!/usr/bin/env python3
"""Keyless twin creates, end to end against a scratch server.

The quick-capture Shortcut posts some entries twice in the same second and
sends no Idempotency-Key. lcars_http.h's HandlePostEntryDeduped answers a
keyless POST /entries whose body is byte for byte one the same login had
inserted less than 2s ago with that first row (the same 200 and body, plus
"X-LCARS-Deduped: 1"). This checks:

  1. twins inside the window: one row, the second answer the first's with
     the header (and the first answer without it);
  2. a different body inside the window: a new row;
  3. the same body after 2.5s: a new row;
  4. a keyed POST is not deduped by its body (the key rules), and its own
     key still replays;
  5. two logins posting the same body do not dedupe each other;
  6. two twins sent at once (threads) still make one row: the mutex.

    python3 test/dedupe.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/dedupe.py

Nothing here touches the journal or a running server: a scratch build of the
release compile line, on an empty database in a temp directory.
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import killclean  # its scratch goes when the run is killed
from api import build, free_port  # the same scratch build as test/api.py

USER, PASS = "t", "t"
CREW = ("crewuser", "crew-pass-0123456789")


def basic(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


MAIN, CREWAUTH = basic(USER, PASS), basic(*CREW)

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Server:
    def __init__(self, binary, tmp):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_CALDAV_LOG="0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS,
                   LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1])
        for k in ("LCARS_NO1_USER", "LCARS_NO1_PASS", "LCARS_STEWARD_USER",
                  "LCARS_STEWARD_PASS", "LCARS_TZ", "LCARS_TASK_KIND"):
            env.pop(k, None)
        self.log = open(tmp / "server.log", "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(
            pre + [str(binary), "--port", str(self.port)],
            cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                if self.post("{}", auth=MAIN, path="/health", method="GET")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        sys.exit("dedupe: the scratch server did not come up; see " + str(tmp / "server.log"))

    def post(self, body, auth=MAIN, key=None, ctype="application/json",
             path="/entries", method="POST"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": auth, "Content-Type": ctype}
        if key:
            h["Idempotency-Key"] = key
        c.request(method, path, body=body.encode() if method == "POST" else None, headers=h)
        r = c.getresponse()
        out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode()
        c.close()
        return out

    def count(self, kind):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", f"/entries?kind={kind}&deleted=all&limit=1000",
                  headers={"Authorization": MAIN})
        rows = json.loads(c.getresponse().read())
        c.close()
        return len(rows)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def body(kind, title):
    return json.dumps({"kind": kind, "title": title, "content": "quick capture"})


def run(s):
    print("twins inside the window: one row")
    b = body("note_a", "twin")
    st1, h1, r1 = s.post(b)
    st2, h2, r2 = s.post(b)
    check(st1 == 200 and "x-lcars-deduped" not in h1, f"the first is a plain 200 ({st1}, {h1.get('x-lcars-deduped')})")
    check(st2 == 200 and r2 == r1, f"the twin is answered with the first's body ({r1!r} / {r2!r})")
    check(h2.get("x-lcars-deduped") == "1", f"the twin carries X-LCARS-Deduped: 1 ({h2.get('x-lcars-deduped')})")
    check(s.count("note_a") == 1, f"one row written ({s.count('note_a')})")
    st3, h3, r3 = s.post(b, ctype="text/plain")
    check(st3 == 200 and r3 != r1 and "x-lcars-deduped" not in h3,
          "the same bytes as text/plain are another entry")

    print("a different body inside the window: a new row")
    st, h, r = s.post(body("note_a", "twin, but not"))
    check(st == 200 and r != r1 and "x-lcars-deduped" not in h, f"a new id ({r!r})")
    # (the text/plain one has no kind)
    check(s.count("note_a") == 2, f"two rows of note_a ({s.count('note_a')})")

    print("the same body after 2.5s: a new row")
    b = body("note_b", "later")
    _, _, first = s.post(b)
    time.sleep(2.5)
    st, h, r = s.post(b)
    check(st == 200 and r != first and "x-lcars-deduped" not in h, f"a new id after the window ({first!r} / {r!r})")
    check(s.count("note_b") == 2, f"two rows of note_b ({s.count('note_b')})")

    print("a keyed POST is not deduped by its body")
    b = body("note_c", "keyed")
    _, _, plain = s.post(b)
    st, h, k1 = s.post(b, key="dedupe-key-0001")
    check(st == 200 and k1 != plain and "x-lcars-deduped" not in h, f"a keyed twin is a new row ({plain!r} / {k1!r})")
    st, h, k2 = s.post(b, key="dedupe-key-0002")
    check(st == 200 and k2 not in (plain, k1), "another key, the same body: another row")
    st, h, k3 = s.post(b, key="dedupe-key-0001")
    check(st == 200 and json.loads(k3).get("id") == json.loads(k1)["id"] and json.loads(k3).get("replayed") is True,
          f"the key still replays its own row ({k3!r})")
    check(s.count("note_c") == 3, f"three rows of note_c ({s.count('note_c')})")

    print("two logins do not dedupe each other")
    b = body("crew_note", "same words")
    st1, h1, r1 = s.post(b, auth=MAIN)
    st2, h2, r2 = s.post(b, auth=CREWAUTH)
    check(st1 == 200 and st2 == 200 and r1 != r2 and "x-lcars-deduped" not in h2,
          f"the crew's is its own row ({st1} {r1!r} / {st2} {r2!r})")
    st3, h3, r3 = s.post(b, auth=CREWAUTH)
    check(st3 == 200 and r3 == r2 and h3.get("x-lcars-deduped") == "1", "and the crew's own twin is deduped")
    check(s.count("crew_note") == 2, f"two rows of crew_note ({s.count('crew_note')})")

    print("twins sent at once: one row")
    b = body("note_d", "racing")
    out = []
    ts = [threading.Thread(target=lambda: out.append(s.post(b))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    ids = {json.loads(r)["id"] for st, _, r in out if st == 200}
    check(len(out) == 4 and len(ids) == 1, f"four at once, one id ({ids})")
    check(sum(1 for _, h, _ in out if h.get("x-lcars-deduped") == "1") == 3, "three of them marked deduped")
    check(s.count("note_d") == 1, f"one row of note_d ({s.count('note_d')})")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-dedupe-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    try:
        run(s)
    finally:
        s.stop()
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server log: {tmp / 'server.log'}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
