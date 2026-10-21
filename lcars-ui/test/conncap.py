#!/usr/bin/env python3
"""The connection cap, end to end: idle keep-alives give way, a refusal is logged.

The server serves at most HTTP_MAX_CONCURRENT_CONNECTIONS (64) connections at
once. Before 0.278.5 that was 32, and a connection past it was an instant 503
- even when every slot was a kept-alive connection doing nothing: a phone's
burst of media range requests held them for 15s, and the 0.275.1 deploy's
/health polls were all refused. This drives a scratch build of the real
server over an empty database on raw sockets and checks:

  1. every slot filled with idle keep-alive connections (each has had one
     answer and is waiting for its next request): a new connection is
     answered, and the longest-idle of them is the one closed;
  2. every slot but one mid-request (half a header sent), the last idle: a
     new connection is answered, and the idle one is the one given up;
  3. every slot mid-request: a new connection is a 503, and the log says
     so in one line with a count - and a second refusal straight after
     writes no second line (rate limited);
  4. once those let go, the server answers again.

    python3 test/conncap.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/conncap.py

Nothing here touches the journal or a running server.
"""
import os
import pathlib
import shutil
import socket
import sys
import time
import killclean  # its scratch goes when the run is killed

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build  # noqa: E402
from metrics import Server  # noqa: E402
from framing import AUTH  # noqa: E402

CAP = 64  # HTTP_MAX_CONCURRENT_CONNECTIONS in lcars_http.h

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


GET = ("GET /kinds/roles HTTP/1.1\r\nHost: x\r\n" + AUTH +
       "\r\nConnection: keep-alive\r\n\r\n").encode()


def read_response(s):
    """One response's status and its Connection header, or (None, None) if
    the server closed (or said nothing) first."""
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                return None, None
            data += chunk
    except (socket.timeout, ConnectionResetError):
        return None, None
    head, _, rest = data.partition(b"\r\n\r\n")
    n, conn = 0, ""
    for line in head.split(b"\r\n")[1:]:
        k, _, v = line.partition(b":")
        if k.strip().lower() == b"content-length":
            n = int(v)
        if k.strip().lower() == b"connection":
            conn = v.strip().decode().lower()
    while len(rest) < n:
        chunk = s.recv(65536)
        if not chunk:
            break
        rest += chunk
    return int(head[9:12]), conn


def idle_conn(port):
    """A connection that has been answered once and is kept alive."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(GET)
    st, conn = read_response(s)
    assert st == 200 and conn == "keep-alive", (st, conn)
    return s


def busy_conn(port):
    """A connection mid-request: half a header, the rest never sent."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /kinds/roles HTTP/1.1\r\nHost: x\r\n")
    return s


def closed_by_server(s, wait=3):
    s.settimeout(wait)
    try:
        return s.recv(1) == b""
    except (socket.timeout, BlockingIOError):
        return False
    except ConnectionResetError:
        return True


def fresh_request(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(GET)
    st, _ = read_response(s)
    s.close()
    return st


def refusal_lines(log):
    return [l for l in log.read_text().splitlines() if "HTTP: refused" in l]


def drain(socks):
    for s in socks:
        s.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-conncap-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    log = tmp / "server.log"
    try:
        print("1. every slot an idle keep-alive")
        idle = [idle_conn(s.port)]
        time.sleep(0.05)  # the first is the longest idle by a clear margin
        idle += [idle_conn(s.port) for _ in range(CAP - 1)]
        st = fresh_request(s.port)
        check(st == 200, f"a new connection past {CAP} idle keep-alives is answered ({st})")
        check(closed_by_server(idle[0]), "the longest-idle keep-alive is the one closed")
        check(not closed_by_server(idle[1], wait=0.3),
              "the next-longest is still open")
        idle[1].sendall(GET)
        st, _ = read_response(idle[1])
        check(st == 200, f"and still answers a request ({st})")
        drain(idle)
        time.sleep(0.3)

        print("2. every slot mid-request but one idle")
        busy = [busy_conn(s.port) for _ in range(CAP - 1)]
        time.sleep(0.2)
        one = idle_conn(s.port)
        st = fresh_request(s.port)
        check(st == 200, f"a new connection past {CAP - 1} mid-request and one idle is answered ({st})")
        check(closed_by_server(one), "the idle one is given up for it")
        check(not any(closed_by_server(b, wait=0.01) for b in busy[:5]),
              "no connection mid-request is closed")

        print("3. every slot mid-request")
        busy.append(busy_conn(s.port))
        time.sleep(0.2)
        before = len(refusal_lines(log))
        st = fresh_request(s.port)
        check(st == 503, f"a new connection past {CAP} mid-request is a 503 ({st})")
        time.sleep(0.2)
        lines = refusal_lines(log)
        check(len(lines) == before + 1 and "refused 1 connection " in lines[-1]
              and f"all {CAP} slots" in lines[-1],
              f"the refusal is one line in the log ({lines[-1:]})")
        st = fresh_request(s.port)
        time.sleep(0.2)
        check(st == 503 and len(refusal_lines(log)) == before + 1,
              f"a second refusal straight after is a 503 and no second line ({st})")
        drain(busy)
        time.sleep(0.3)

        print("4. after")
        st = fresh_request(s.port)
        check(st == 200, f"the server answers once they let go ({st})")
        check(s.proc.poll() is None, "the server is still up")
    finally:
        s.stop()
    if fails:
        print(f"\nconncap: {len(fails)} of {checks[0]} checks failed; server log in {tmp}")
        sys.exit(1)
    print(f"\nconncap: all {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
