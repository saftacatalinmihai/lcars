#!/usr/bin/env python3
"""Request framing, end to end: what the server takes as a request's length.

The body of a request is Content-Length bytes after the headers, and
whatever follows on a kept-alive connection is the next request. This drives
a scratch build of the real server over an empty database on raw sockets
(http.client will not send a malformed header) and checks:

  1. a Content-Length that is not a plain number (-5, +5, 5x, 1.5, abc,
     empty) is a 400 and the connection ends - on every route, the ones
     before the password included; atoi() used to read -5 as a length;
  2. a huge one is a 413, not an overflow;
  3. Transfer-Encoding (which the server does not decode) is a 400;
  4. a body that ends short of its Content-Length is a 400, not a request
     with a tail of stale bytes;
  5. a request without a body does not take the Content-Length of the
     pipelined request behind it (header lookup stops at the blank line),
     and both are answered on one connection;
  6. the server is still up at the end.

    python3 test/framing.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/framing.py

Nothing here touches the journal or a running server.
"""
import base64
import json
import os
import pathlib
import shutil
import socket
import sys
import killclean  # its scratch goes when the run is killed

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build  # noqa: E402
from metrics import USER, PASS, Server  # noqa: E402

AUTH = "Authorization: Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def exchange(port, raw, shut=False, wait=5):
    """Sends `raw`, reads until the server closes or goes quiet. Returns
    (statuses in order, bodies, closed by the server)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    s.sendall(raw)
    if shut:
        s.shutdown(socket.SHUT_WR)
    data, closed = b"", False
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                closed = True
                break
            data += chunk
    except socket.timeout:
        pass
    s.close()
    statuses, bodies = [], []
    rest = data
    while rest.startswith(b"HTTP/1.1 "):
        head, _, rest = rest.partition(b"\r\n\r\n")
        statuses.append(int(head[9:12]))
        n = 0
        for line in head.split(b"\r\n")[1:]:
            k, _, v = line.partition(b":")
            if k.strip().lower() == b"content-length":
                n = int(v)
        bodies.append(rest[:n].decode(errors="replace"))
        rest = rest[n:]
    return statuses, bodies, closed


def req(method, path, headers=(), body=b"", auth=True):
    lines = [f"{method} {path} HTTP/1.1", "Host: x"]
    if auth:
        lines.append(AUTH)
    lines += list(headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-framing-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    p = s.port
    try:
        print("\na Content-Length that is not a length")
        body = b'{"kind":"journal","title":"framing"}'
        for bad in ("-5", "-1", "+5", "5x", "1.5", "abc", "", "0x10", "5 5"):
            st, _, closed = exchange(p, req("POST", "/entries",
                                            ["Content-Type: application/json",
                                             f"Content-Length: {bad}"], body))
            check(st == [400] and closed,
                  f"POST /entries with Content-Length {bad!r}: 400, connection closed ({st})")
        st, _, closed = exchange(p, req("GET", "/health", ["Content-Length: -5"], auth=False))
        check(st == [400] and closed, f"GET /health (no password) with -5: 400 ({st})")
        st, _, closed = exchange(p, req("OPTIONS", "/entries", ["Content-Length: -5"],
                                        auth=False))
        check(st == [400] and closed, f"OPTIONS with -5: 400 ({st})")
        st, _, closed = exchange(p, req("POST", "/entries/1/media",
                                        ["Content-Type: image/png", "Content-Length: -5"],
                                        b"x" * 5))
        check(st == [400] and closed, f"a media upload with -5: 400 ({st})")
        st, _, _ = exchange(p, req("POST", "/entries",
                                   ["Content-Type: application/json",
                                    "Content-Length: 99999999999999999999999"], body))
        check(st == [413], f"a 23-digit Content-Length: 413, not an overflow ({st})")
        st, _, _ = exchange(p, req("POST", "/entries",
                                   ["Content-Type: application/json",
                                    f"Content-Length:  {len(body)} "], body))
        check(st == [201] or st == [200], f"blanks round a good length are fine ({st})")

        print("\nTransfer-Encoding")
        st, _, closed = exchange(p, req("POST", "/entries",
                                        ["Content-Type: application/json",
                                         "Transfer-Encoding: chunked"],
                                        b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n"))
        check(st == [400] and closed, f"a chunked body: 400, connection closed ({st})")

        print("\na body short of its Content-Length")
        st, bodies, closed = exchange(p, req("POST", "/entries",
                                             ["Content-Type: application/json",
                                              f"Content-Length: {len(body) + 40}"], body),
                                      shut=True)
        check(st == [400] and closed, f"40 bytes missing, the peer done: 400 ({st} {bodies})")

        print("\npipelined requests")
        st, bodies, _ = exchange(p, req("POST", "/entries",
                                        ["Content-Type: application/json",
                                         f"Content-Length: {len(body)}"], body))
        eid = json.loads(bodies[0])["id"] if st and st[0] in (200, 201) else 0
        check(eid > 0, f"an entry to read ({st})")
        second = req("POST", "/entries", ["Content-Type: application/json",
                                          f"Content-Length: {len(body)}",
                                          "Connection: close"], body)
        st, bodies, _ = exchange(p, req("GET", f"/entries/{eid}") + second)
        check(len(st) == 2 and st[0] == 200 and st[1] in (200, 201),
              f"a GET with no body, then a POST in the same segment: both answered ({st})")
        check(len(bodies) > 0 and f'"id":{eid}' in bodies[0].replace(" ", ""),
              "the GET is its own entry, not cut short by the POST's length")

        print("\nstill up")
        check(s.proc.poll() is None, "the server process is alive")
        st, _, _ = exchange(p, req("GET", "/health", auth=False))
        check(st == [200], f"GET /health: 200 ({st})")
    finally:
        s.stop()
    if fails:
        print(f"\nframing: {len(fails)} of {checks[0]} checks failed; server log in {tmp}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nframing: all {checks[0]} checks passed")


if __name__ == "__main__":
    main()
