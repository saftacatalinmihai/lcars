#!/usr/bin/env python3
"""Classified entries end to end (docs/design/confidential-entries.md,
lcars_vault.h; the page's "classified" block).

The server, against a scratch build on an empty journal:

  1. lcars_sha256.h on its own against the NIST vectors;
  2. GET/PUT /vault: none yet, the first PUT, the token guard (403), the
     version (409), a rewrite, a new token; the limited logins refused;
  3. a Secret create and update: the envelope only (400 for a title, text
     or numbers beside it), the token (403 without, 409 with no vault),
     the placeholders a limited login gets (no `sealed`, content_length
     0) against the main login's row; /dump; `q` never matching one;
  4. what a Secret row refuses: append and title (409), an upload (409),
     a limited login's classify (403); and allows: done, kind, dates;
  5. a raise: the plaintext gone from the row, from lcars.db and its WAL
     (the byte scan), the vector and the CalDAV row deleted; a raise of
     an entry with files refused; a lowering, which needs the token;
  6. the embedder, with a stand-in service: a Secret entry's text never
     sent, its vector never stored, the count leaving it out.

The page, in headless Chromium against the same server (skip with
CHROMIUM=0): the password set in Config with its tick-box, a Secret entry
written, the row's placeholder after a lock, unlocked again (a wrong
password told apart), local search finding it only while unlocked, lowered
and raised by the chip, and every request the page made recorded: none
carries the password, the key or a Secret entry's plaintext, and the
mirror (IndexedDB) and localStorage hold none of it either.

    python3 test/classified.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/classified.py
"""
import base64
import http.client
import http.server
import json
import os
import pathlib
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import killclean  # its scratch goes when the run is killed
from api import build, free_port

USER, PASS = "t", "t"
CREW = ("crewuser", "crew-pass-0123456789")
NO1 = ("no1user", "no1-pass-0123456789")


def basic(u, p):
    return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()


MAIN, CREWAUTH, NO1AUTH = basic(USER, PASS), basic(*CREW), basic(*NO1)

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


# --------------------------------------------------------------- the server
class Server:
    def __init__(self, binary, tmp, env_extra=None, log="server.log"):
        self.tmp = tmp
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_CALDAV_LOG="0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS,
                   LCARS_CREW_USER=CREW[0], LCARS_CREW_PASS=CREW[1],
                   LCARS_NO1_USER=NO1[0], LCARS_NO1_PASS=NO1[1],
                   LCARS_MEDIA_ROOT=str(tmp / "media"))
        for k in ("LCARS_STEWARD_USER", "LCARS_STEWARD_PASS", "LCARS_TZ", "LCARS_TASK_KIND",
                  "LCARS_DB_PATH", "LCARS_DATA_DIR"):
            env.pop(k, None)
        env.update(env_extra or {})
        self.log = open(tmp / log, "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(
            pre + [str(binary), "--port", str(self.port)],
            cwd=tmp, env=env, stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                if self.req("GET", "/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        sys.exit("classified: the scratch server did not come up; see " + str(tmp / log))

    def req(self, method, path, body=None, auth=MAIN, headers=None, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Authorization": auth}
        if body is not None:
            h["Content-Type"] = ctype
        h.update(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        c.request(method, path, body=body.encode() if isinstance(body, str) else body, headers=h)
        r = c.getresponse()
        raw = r.read().decode(errors="replace")
        c.close()
        try:
            data = json.loads(raw) if raw.strip()[:1] in ("{", "[") else raw
        except ValueError:
            data = raw
        return r.status, data

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def envelope(tag="x"):
    """What the page's clsEnvelope writes, in shape: the server cannot open
    it and does not try."""
    h = base64.urlsafe_b64encode(json.dumps({"kid": "k1", "alg": "A256GCM", "iv": tag}).encode()).decode().rstrip("=")
    return "lcs1." + h + "." + base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")


VAULT = {"v": 1, "kid": "k1", "wraps": [{"type": "password", "kdf": "PBKDF2-SHA256", "iter": 600000,
                                         "salt": "c2FsdA", "iv": "aXY", "wrapped": "d3JhcHBlZA"}]}


# --------------------------------------------------------------- 1. sha256
def sha_vectors(tmp):
    print("lcars_sha256.h against the NIST vectors")
    src = tmp / "sha.c"
    src.write_text(r'''
#define LCARS_SHA256_IMPLEMENTATION
#include "lcars_sha256.h"
#include <stdio.h>
#include <stdlib.h>
int main(void) {
  char h[65];
  Sha256Hex("", 0, h); puts(h);
  Sha256Hex("abc", 3, h); puts(h);
  const char *m = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
  Sha256Hex(m, strlen(m), h); puts(h);
  /* a million 'a's, fed in uneven pieces: the block buffer's edges */
  static char a[1000000];
  memset(a, 'a', sizeof(a));
  Sha256 s; Sha256Init(&s);
  size_t off = 0, step = 1;
  while (off < sizeof(a)) {
    size_t n = step < sizeof(a) - off ? step : sizeof(a) - off;
    Sha256Update(&s, a + off, n); off += n; step = step * 3 % 191 + 1;
  }
  uint8_t d[32]; Sha256Final(&s, d);
  for (int i = 0; i < 32; i++) printf("%02x", d[i]);
  puts("");
  /* 55 and 56 bytes: the length fits the last block, and does not */
  Sha256Hex(a, 55, h); puts(h);
  Sha256Hex(a, 56, h); puts(h);
  return 0;
}
''')
    exe = tmp / "sha"
    r = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-pedantic", "-Wshadow", "-Werror",
                        "-I", str(REPO), "-o", str(exe), str(src)], capture_output=True, text=True)
    check(r.returncode == 0, "it compiles alone, warning-free" + ("" if r.returncode == 0 else ": " + r.stderr[-400:]))
    if r.returncode != 0:
        return
    out = subprocess.run([str(exe)], capture_output=True, text=True).stdout.split()
    import hashlib
    want = [
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
        "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
        hashlib.sha256(b"a" * 55).hexdigest(),
        hashlib.sha256(b"a" * 56).hexdigest(),
    ]
    names = ["the empty string", '"abc"', "the 448-bit message", "a million a's",
             "55 bytes", "56 bytes"]
    for i, n in enumerate(names):
        check(i < len(out) and out[i] == want[i], f"SHA-256 of {n}")


# --------------------------------------------------------------- 2. the vault
def vault(s):
    print("GET/PUT /vault and its guard")
    st, v = s.req("GET", "/vault")
    check(st == 200 and v == {"version": 0, "vault": None}, f"no vault yet ({st} {v})")
    for who, auth in (("Number One", NO1AUTH), ("the crew", CREWAUTH)):
        st, _ = s.req("GET", "/vault", auth=auth)
        check(st == 403, f"{who} may not read it ({st})")
        st, _ = s.req("PUT", "/vault", {"vault": VAULT, "token": "a" * 64, "version": 0}, auth=auth)
        check(st == 403, f"{who} may not set it ({st})")
    token = secrets.token_hex(32)
    st, _ = s.req("PUT", "/vault", {"vault": VAULT, "token": "zz", "version": 0})
    check(st == 400, f"a token is 64 hex characters ({st})")
    st, _ = s.req("PUT", "/vault", {"token": token, "version": 0})
    check(st == 400, f"a vault is an object ({st})")
    st, r = s.req("PUT", "/vault", {"vault": VAULT, "token": token, "version": 0})
    check(st == 200 and r.get("version") == 1, f"the first PUT sets it, version 1 ({st} {r})")
    st, v = s.req("GET", "/vault")
    check(st == 200 and v.get("version") == 1 and v.get("vault") == VAULT, "GET gives it back as written")
    check("auth_hash" not in json.dumps(v) and token not in json.dumps(v), "with no token and no hash in it")
    other = secrets.token_hex(32)
    st, _ = s.req("PUT", "/vault", {"vault": dict(VAULT, evil=True), "token": other, "version": 1})
    check(st == 403, f"another token cannot replace it ({st})")
    st, _ = s.req("PUT", "/vault", {"vault": dict(VAULT, evil=True), "token": other, "version": 0})
    check(st == 403, f"nor a 'first' PUT once there is one ({st})")
    v2 = dict(VAULT, wraps=VAULT["wraps"] + [{"type": "recovery"}])
    st, _ = s.req("PUT", "/vault", {"vault": v2, "token": token, "version": 0})
    check(st == 409, f"a stale version is a 409 ({st})")
    st, r = s.req("PUT", "/vault", {"vault": v2, "token": token.upper(), "version": 1})
    check(st == 200 and r.get("version") == 2, f"the token (any case) and the version rewrite it ({st} {r})")
    new = secrets.token_hex(32)
    st, r = s.req("PUT", "/vault", {"vault": VAULT, "token": token, "new_token": new, "version": 2})
    check(st == 200 and r.get("version") == 3, f"new_token moves the guard ({st})")
    st, _ = s.req("PUT", "/vault", {"vault": VAULT, "token": token, "version": 3})
    check(st == 403, f"and the old token is refused after ({st})")
    pk = {"type": "passkey", "cred": "Y3JlZA", "prf_salt": "c2FsdA", "iv": "aXY", "wrapped": "d3JhcHBlZA"}
    for wraps, what in (([pk], "only a passkey"), ([], "no wrap"), (VAULT["wraps"] * 2, "two passwords"),
                        (VAULT["wraps"] + [{"iv": "aXY"}], "a wrap with no type")):
        st, _ = s.req("PUT", "/vault", {"vault": dict(VAULT, wraps=wraps), "token": new, "version": 3})
        check(st == 400, f"a vault with {what} is refused: the password wrap is kept ({st})")
    st, r = s.req("PUT", "/vault", {"vault": dict(VAULT, wraps=VAULT["wraps"] + [pk]), "token": new, "version": 3})
    check(st == 200 and r.get("version") == 4, f"the password and a passkey: written ({st} {r})")
    st, r = s.req("PUT", "/vault", {"vault": VAULT, "token": new, "version": 4})
    check(st == 200 and r.get("version") == 5, f"and the passkey removed again ({st} {r})")
    st, _ = s.req("PUT", "/vault", {"vault": "x" * 20000, "token": new, "version": 5})
    check(st == 400, f"a string is not a vault ({st})")
    st, _ = s.req("POST", "/vault", {"vault": VAULT})
    check(st == 405, f"POST is not a method of it ({st})")
    with sqlite3.connect(s.tmp / "lcars.db") as db:
        h = db.execute("SELECT auth_hash FROM vault").fetchone()[0]
    import hashlib
    check(h == hashlib.sha256(new.encode()).hexdigest() and new not in h,
          "the table keeps the token's SHA-256, never the token")
    return new


# --------------------------------------------------------------- 3, 4. rows
def rows(s, token):
    tok = {"X-LCARS-Vault": token}
    print("a Secret create: the envelope only, and the token")
    env = envelope("a")
    base = {"kind": "note", "classification": 2, "sealed": env}
    st, _ = s.req("POST", "/entries", base)
    check(st == 403, f"without the token, refused ({st})")
    st, _ = s.req("POST", "/entries", base, headers={"X-LCARS-Vault": "0" * 64})
    check(st == 403, f"with a wrong one, refused ({st})")
    for extra, what in (({"title": "my plan"}, "a title"), ({"content": "the text"}, "text"),
                        ({"value_int": 7}, "a number"), ({"sealed": "plain words"}, "plaintext as the envelope"),
                        ({"sealed": ""}, "no envelope")):
        st, _ = s.req("POST", "/entries", dict(base, **extra), headers=tok)
        check(st == 400, f"{what} beside or instead of the envelope is a 400 ({st})")
    st, _ = s.req("POST", "/entries", dict(base, classification=1), headers=tok)
    check(st == 400, f"Confidential (1) is not a level yet ({st})")
    st, _ = s.req("POST", "/entries", {"kind": "note", "title": "x", "sealed": env}, headers=tok)
    check(st == 400, f"an envelope on an Unclassified create is a 400 ({st})")
    st, _ = s.req("POST", "/entries", {"kind": "crew_note", "classification": 2, "sealed": env}, auth=CREWAUTH)
    check(st == 403, f"a limited login may not classify, even its own kind ({st})")
    st, r = s.req("POST", "/entries", dict(base, done_bool=1, start_date="2026-10-20 10:00:00"), headers=tok)
    check(st == 200 and r.get("id"), f"the envelope with the token: created ({st} {r})")
    sid = r["id"]
    st, plain = s.req("POST", "/entries", {"kind": "note", "title": "zebra crossing", "content": "plain zebra"})
    pid = plain["id"]

    st, row = s.req("GET", f"/entries/{sid}")
    check(row.get("classification") == 2 and row.get("sealed") == env, "the owner's GET has the level and the envelope")
    check(row.get("title") == "" and row.get("content") == "", "and an empty title and text")
    check(row.get("content_length") == len(env), f"content_length counts the envelope ({row.get('content_length')})")
    check(row.get("done_bool") == 1 and row.get("start_date") == "2026-10-20 10:00:00" and row.get("kind") == "note",
          "kind, done and dates as sent")
    for who, auth in (("Number One", NO1AUTH), ("the crew", CREWAUTH)):
        st, row = s.req("GET", f"/entries/{sid}", auth=auth)
        check(st == 200 and "sealed" not in row and row.get("classification") == 2 and row.get("title") == ""
              and row.get("content_length") == 0, f"{who} gets the placeholder: no envelope, no length")
        st, lst = s.req("GET", "/entries?limit=100", auth=auth)
        check(all("sealed" not in r for r in lst) and any(r["id"] == sid for r in lst),
              f"{who}'s list has the row, and no envelope in it")
        st, d = s.req("GET", "/dump", auth=auth)
        check(isinstance(d, list) and "lcs1." not in json.dumps(d), f"{who}'s /dump carries no envelope")
    st, d = s.req("GET", "/dump")
    check(any(r.get("id") == sid and r.get("sealed") == env for r in d), "the owner's /dump carries it")
    st, d = s.req("GET", "/dump?content=0")
    check(all("sealed" not in r for r in d) and any(r["id"] == sid and r["content_length"] == len(env) for r in d),
          "content=0 leaves it out, its length kept for the body load")
    st, q = s.req("GET", "/entries?q=zebra")
    check([r["id"] for r in q] == [pid], "the server's search finds the plain row")
    st, q = s.req("GET", "/entries?q=lcs1")
    check(q == [], f"and never matches an envelope ({len(q)})")

    print("what a Secret row refuses, and what it allows")
    st, row = s.req("GET", f"/entries/{sid}")
    lm = row["last_modified_at_utc"]
    st, _ = s.req("POST", f"/entries/{sid}/append", {"text": "more", "if_modified": lm})
    check(st == 409, f"append: 409 ({st})")
    st, _ = s.req("POST", f"/entries/{sid}/title", {"title": "named", "if_modified": lm})
    check(st == 409, f"title: 409 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", {"title": "named"})
    check(st == 400, f"a PUT of a title: 400 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", {"content": "words"}, headers=tok)
    check(st == 400, f"a PUT of text, token or not: 400 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", "plain body", ctype="text/plain")
    check(st == 400, f"a plain-text PUT: 400 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", {"sealed": envelope("b")})
    check(st == 403, f"a new envelope without the token: 403 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", {"classification": 0, "title": "gone"})
    check(st == 403, f"a lowering without the token: 403 ({st})")
    st, _ = s.req("PATCH", f"/entries/{sid}", {"classification": 0}, auth=CREWAUTH)
    check(st == 403, f"a limited login's lowering: 403 ({st})")
    st, _ = s.req("PUT", f"/entries/{sid}", {"done_bool": 0, "kind": "journal", "end_date": "2026-10-20 11:00:00"})
    check(st == 200, f"done, kind and dates need nothing ({st})")
    env2 = envelope("c")
    st, _ = s.req("PUT", f"/entries/{sid}", {"sealed": env2, "title": "", "content": ""}, headers=tok)
    check(st == 200, f"a new envelope with the token ({st})")
    st, row = s.req("GET", f"/entries/{sid}")
    check(row.get("sealed") == env2 and row.get("kind") == "journal", "is stored")
    c = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
    c.request("POST", f"/entries/{sid}/media?name=a.jpg", body=b"\xff\xd8\xff" + b"0" * 100,
              headers={"Authorization": MAIN, "Content-Type": "image/jpeg"})
    r = c.getresponse()
    check(r.status == 409, f"an upload to it: 409 ({r.status})")
    r.read()
    c.close()
    return sid, pid


# --------------------------------------------------------------- 5. a raise
MARK = "PLAINTEXT-MARKER-" + secrets.token_hex(6)


def scan(tmp):
    """Every byte of the journal's files, for the marker."""
    found = []
    for n in ("lcars.db", "lcars.db-wal", "lcars.db-shm"):
        p = tmp / n
        if p.exists() and MARK.encode() in p.read_bytes():
            found.append(n)
    return found


def raise_and_lower(s, token, binary, tmp):
    tok = {"X-LCARS-Vault": token}
    print("a raise: the plaintext gone from the row and the files")
    st, r = s.req("POST", "/entries", {"kind": "task", "title": MARK + " title",
                                       "content": (MARK + " body ") * 400, "value_int": 3})
    rid = r["id"]
    s.req("PUT", f"/entries/{rid}", {"content": (MARK + " edited body ") * 300})
    check(scan(tmp) != [], "the marker is in the journal's files before (the scan sees it)")
    # its CalDAV row and a vector, as the embedder and a client would leave
    with sqlite3.connect(tmp / "lcars.db") as db:
        db.execute("CREATE TABLE IF NOT EXISTS entry_embeddings (entry_id INTEGER PRIMARY KEY, model TEXT,"
                   " source_modified TEXT, dim INTEGER, vec BLOB, embedded_at_utc TEXT)")
        db.execute("INSERT OR REPLACE INTO entry_embeddings VALUES (?, 'm', '', 1, x'01', '')", (rid,))
    st, body = s.req("PROPFIND", "/caldav/calendars/tasks/", None, headers={"Depth": "1"})
    check(f"lcars-{rid}.ics" in str(body), "CalDAV lists the task before")
    st, _ = s.req("PATCH", f"/entries/{rid}", {"classification": 2, "sealed": envelope("r")}, headers=tok)
    check(st == 200, f"PATCH classification 2 with the envelope and the token ({st})")
    st, row = s.req("GET", f"/entries/{rid}")
    check(row.get("title") == "" and row.get("content") == "" and row.get("value_int") == 0,
          "title, text and numbers emptied by the server, unasked")
    check(scan(tmp) == [], f"the marker is in no byte of lcars.db or its WAL after ({scan(tmp)})")
    with sqlite3.connect(tmp / "lcars.db") as db:
        n = db.execute("SELECT count(*) FROM entry_embeddings WHERE entry_id = ?", (rid,)).fetchone()[0]
        has_c = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'caldav_tasks'").fetchone()
        nc = db.execute("SELECT count(*) FROM caldav_tasks WHERE entry_id = ?", (rid,)).fetchone()[0] if has_c else 0
    check(n == 0, "its vector deleted")
    check(nc == 0, "its CalDAV row deleted")
    st, body = s.req("PROPFIND", "/caldav/calendars/tasks/", None, headers={"Depth": "1"})
    check(f"lcars-{rid}.ics" not in str(body) and MARK not in str(body), "CalDAV's list no longer has it")
    st, _ = s.req("GET", f"/caldav/calendars/tasks/lcars-{rid}.ics")
    check(st == 404, f"nor answers for it ({st})")
    ical = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:lcars-%d@lcars\r\n"
            "SUMMARY:%s stale\r\nEND:VTODO\r\nEND:VCALENDAR\r\n") % (rid, MARK)
    st, _ = s.req("PUT", f"/caldav/calendars/tasks/lcars-{rid}.ics", ical, ctype="text/calendar")
    st2, row2 = s.req("GET", f"/entries/{rid}")
    check(row2.get("title") == "" and row2.get("classification") == 2,
          f"a stale client's PUT writes nothing into it ({st})")
    check(s.req("POST", f"/entries/{rid}/append", {"text": MARK, "if_modified": row["last_modified_at_utc"]})[0] == 409,
          "nor will it take an append")

    print("raising an entry with files, and lowering")
    st, r = s.req("POST", "/entries", {"kind": "note", "title": "with a photo"})
    fid = r["id"]
    with sqlite3.connect(tmp / "lcars.db") as db:
        db.execute("INSERT INTO entry_media (entry_id, path, mime, bytes, created_at_utc)"
                   " VALUES (?, 'media/x.jpg', 'image/jpeg', 3, '2026-10-20 10:00:00')", (fid,))
    st, _ = s.req("PATCH", f"/entries/{fid}", {"classification": 2, "sealed": envelope("f")}, headers=tok)
    check(st == 409, f"an entry with files is not raised: 409 ({st})")
    st, _ = s.req("PATCH", f"/entries/{rid}", {"classification": 0, "title": "declassified", "content": "back"},
                  headers=tok)
    check(st == 200, f"a lowering with the token ({st})")
    st, row = s.req("GET", f"/entries/{rid}")
    check(row.get("classification") == 0 and "sealed" not in row and row.get("title") == "declassified",
          "is plain again, its envelope gone")
    st, _ = s.req("PATCH", f"/entries/{rid}", {"sealed": envelope("z")}, headers=tok)
    check(st == 400, f"an envelope on a plain row is a 400 ({st})")
    return rid


# --------------------------------------------------------------- 6. embedder
class Embedder(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        texts = body.get("input") or []
        texts = texts if isinstance(texts, list) else [texts]
        Embedder.seen.extend(texts)
        data = [{"index": i, "embedding": [0.1, 0.2, 0.3, 0.4]} for i in range(len(texts))]
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def embedder(binary, tmp, token):
    print("the embedder, with a stand-in service")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Embedder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = "2020-01-01 00:00:00"
    # rows settled long ago (the indexer waits 60s on a fresh edit), written
    # before the server with the embedder starts
    tmp = tmp / "embed"
    tmp.mkdir()
    (tmp / "media").mkdir()
    s = Server(binary, tmp, log="server-a.log")
    # a vault of its own: a new journal
    s.req("PUT", "/vault", {"vault": VAULT, "token": token, "version": 0})
    tok = {"X-LCARS-Vault": token}
    st, r = s.req("POST", "/entries", {"kind": "note", "title": "plain words", "content": "an ordinary day",
                                       "created_at_utc": old, "last_modified_at_utc": old})
    pid = r["id"]
    st, r = s.req("POST", "/entries", {"kind": "note", "classification": 2, "sealed": envelope("e"),
                                       "created_at_utc": old, "last_modified_at_utc": old}, headers=tok)
    sid = r["id"]
    s.stop()
    s = Server(binary, tmp, env_extra={"LCARS_EMBED": "1",
                                       "LCARS_EMBED_URL": f"http://127.0.0.1:{srv.server_port}/v1/embeddings",
                                       "LCARS_EMBED_MODEL": "stand-in"}, log="server-b.log")
    try:
        ids = []
        for _ in range(100):
            st, e = s.req("GET", "/embeddings")
            ids = [v[0] for v in e.get("rows", [])] if isinstance(e, dict) else []
            if pid in ids:
                break
            time.sleep(0.2)
        check(pid in ids, f"the plain row is embedded ({len(Embedder.seen)} texts sent)")
        check(sid not in ids, "the Secret row has no vector")
        check(e.get("live") == 1, f"and is not counted as one to embed (live {e.get('live')})")
        check(not any("lcs1." in t for t in Embedder.seen), "no envelope was sent to the service")
        with sqlite3.connect(tmp / "lcars.db") as db:
            n = db.execute("SELECT count(*) FROM entry_embeddings WHERE entry_id = ?", (sid,)).fetchone()[0]
        check(n == 0, "and none is stored for it")
    finally:
        s.stop()
        srv.shutdown()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-classified-"))
    (tmp / "media").mkdir()
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    sha_vectors(tmp)
    s = Server(binary, tmp)
    try:
        token = vault(s)
        rows(s, token)
        raise_and_lower(s, token, binary, tmp)
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()
    embedder(binary, tmp, token)
    if os.environ.get("CHROMIUM", "1") != "0":
        import classified_ui
        classified_ui.run(binary, tmp, check)
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; logs in {tmp}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
