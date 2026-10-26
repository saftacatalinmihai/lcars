#!/usr/bin/env python3
"""GET /metrics, end to end: the readings in Prometheus' text format.

lcars_metrics.h answers the Grafana Alloy on the VPS with the latest reading
of each kind, when it was measured, and the live entries per kind. This
drives a scratch build of the real server over an empty database and checks:

  1. a reading is what index.html's reading() calls one: value_float, else
     value_int, else a title opening with a zero; deleted rows and rows
     with no number are not; the latest is the newest created_at_utc;
  2. lcars_reading_timestamp_seconds is that row's created_at_utc;
  3. lcars_entries_total counts live rows of every kind, readings or not;
  4. the text parses as Prometheus' exposition format: label values
     escaped, every metric's samples together under its # TYPE;
  5. loopback needs no password; another address of this box does
     (skipped when it has none), a wrong one is 401; POST is 405;
  6. the crew's file (scripts/eng_metrics.py's metrics.prom) appended as it
     stands under lcars_eng_metrics_timestamp_seconds, its mtime: missing
     (nothing appended, no timestamp), present, stale, without its final
     newline, over the size cap (skipped), LCARS_ENG_METRICS="" (off); and
     a real render of eng_metrics.py passing through intact.

    python3 test/metrics.py            # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/metrics.py

Nothing here touches the journal or a running server.
"""
import base64
import calendar
import http.client
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import killclean  # its scratch goes when the run is killed
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from caldav import build, free_port  # noqa: E402

USER, PASS = "t", "t"

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def lan_address():
    """An address of this box that is not loopback, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET: nothing is sent
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


class Server:
    def __init__(self, binary, tmp, eng=None):
        self.port = free_port()
        # never the box's own crew file (~/.local/state/lcars-eng): a scratch path
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0", LCARS_BIND="0.0.0.0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS,
                   LCARS_ENG_METRICS=str(tmp / "eng.prom") if eng is None else eng)
        for k in ("LCARS_NO1_USER", "LCARS_NO1_PASS", "LCARS_CREW_USER",
                  "LCARS_CREW_PASS", "LCARS_ENGINEER", "DEEPGRAM_API_KEY"):
            env.pop(k, None)
        self.log = open(tmp / "server.log", "a")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--http-only", "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("metrics: the scratch server did not come up; see " + str(tmp / "server.log"))

    def req(self, method, path, body=None, auth=(USER, PASS), host="127.0.0.1"):
        c = http.client.HTTPConnection(host, self.port, timeout=10)
        h = {}
        if auth:
            h["Authorization"] = "Basic " + base64.b64encode(
                f"{auth[0]}:{auth[1]}".encode()).decode()
        if body is not None:
            h["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        ctype = r.getheader("Content-Type", "")
        c.close()
        return r.status, text, ctype

    def make(self, **row):
        st, text, _ = self.req("POST", "/entries", row)
        assert st in (200, 201), (st, text)
        return json.loads(text)["id"]

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{kind="((?:[^"\\\n]|\\[\\"n])*)"\} (\S+)$')


def parse(text):
    """{metric: {kind: value}}, failing a check on any line the text format
    does not allow, or on a metric whose samples are not together."""
    out, seen, current = {}, [], None
    for line in text.splitlines():
        if line.startswith("# HELP "):
            continue
        if line.startswith("# TYPE "):
            _, _, name, typ = line.split(" ", 3)
            check(typ == "gauge", f"{name} is a gauge")
            check(name not in seen, f"{name} has one # TYPE")
            seen.append(name)
            current = name
            out[name] = {}
            continue
        m = LINE.match(line)
        check(m is not None, f"a sample line parses: {line!r}")
        if not m:
            continue
        name, kind, value = m.groups()
        check(name == current, f"{name}'s samples sit under its own # TYPE")
        kind = re.sub(r'\\(.)', lambda g: {"n": "\n"}.get(g.group(1), g.group(1)), kind)
        check(kind not in out.setdefault(name, {}), f"one {name} per kind ({kind!r})")
        out[name][kind] = float(value)
    return out


ENG_TS = "# HELP lcars_eng_metrics_timestamp_seconds"


def journal_part(text):
    """The journal's own numbers: everything before the crew's file."""
    return text.split(ENG_TS, 1)[0]


def eng_part(text):
    """(timestamp, the file as appended) or (None, None) when nothing was."""
    if ENG_TS not in text:
        return None, None
    rest = text.split(ENG_TS, 1)[1].split("\n", 3)
    ok = (len(rest) == 4 and rest[0].endswith("written.")
          and rest[1] == "# TYPE lcars_eng_metrics_timestamp_seconds gauge")
    m = re.match(r"^lcars_eng_metrics_timestamp_seconds (\d+)$", rest[2]) if ok else None
    check(m is not None, "the timestamp: HELP, TYPE gauge, one sample")
    return (int(m.group(1)) if m else None), (rest[3] if m else "")


def eng_checks(s, tmp):
    print("\nthe crew's file")
    eng = tmp / "eng.prom"
    st, text, _ = s.req("GET", "/metrics", auth=None)
    check(st == 200 and ENG_TS not in text and "lcars_eng" not in text,
          "missing: nothing appended, no timestamp")
    body = ("# HELP lcars_seat_held 1 while someone holds the seat.\n# TYPE lcars_seat_held gauge\n"
            "lcars_seat_held 1\n")
    eng.write_text(body)
    stamp = int(time.time()) - 7
    os.utime(eng, (stamp, stamp))
    st, text, _ = s.req("GET", "/metrics", auth=None)
    ts, got = eng_part(text)
    check(st == 200 and ts == stamp, f"present: the timestamp is the file's mtime ({ts} vs {stamp})")
    check(got == body and text.endswith(body), "the file appended verbatim, at the end")
    parse(journal_part(text))  # the journal's part still parses on its own
    old = stamp - 3 * 86400
    os.utime(eng, (old, old))
    ts, got = eng_part(s.req("GET", "/metrics", auth=None)[1])
    check(ts == old and got == body, "stale: its age shows (the old mtime), the values still there")
    eng.write_text(body.rstrip("\n"))
    text = s.req("GET", "/metrics", auth=None)[1]
    check(text.endswith(body), "a file without its last newline is given one")
    eng.write_text("x" * (256 * 1024 + 1))
    st, text, _ = s.req("GET", "/metrics", auth=None)
    check(st == 200 and ENG_TS not in text and "xxx" not in text, "over 256KB: skipped, not cut")
    eng.write_text("y" * (256 * 1024 - 1) + "\n")
    st, text, _ = s.req("GET", "/metrics", auth=None)
    check(st == 200 and text.endswith("y\n") and text.count("y") >= 256 * 1024 - 1,
          "a file at the cap is appended whole")
    eng.unlink()
    check(ENG_TS not in s.req("GET", "/metrics", auth=None)[1], "deleted again: nothing appended")

    # a real render, through the server
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
    import eng_metrics as M
    with M.changing(str(tmp / "state")) as m:
        M.inc(m, "lcars_jobs_total", "passed")
        M.observe(m, "lcars_task_seconds", 1500)
        M.gauge(m, "lcars_engineer_ctx_tokens", {"sato-c31": 120000})
    real = (tmp / "state" / "metrics" / "metrics.prom").read_text()
    eng.write_text(real)
    ts, got = eng_part(s.req("GET", "/metrics", auth=None)[1])
    check(got == real and 'lcars_jobs_total{outcome="passed"} 1\n' in got
          and 'lcars_task_seconds_bucket{le="1800"} 1\n' in got,
          "eng_metrics.py's render passes through intact")
    eng.unlink()


def utc(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-metrics-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build(binary)
    s = Server(binary, tmp)
    try:
        print("\nempty journal")
        eng_checks(s, tmp)

        st, text, ctype = s.req("GET", "/metrics", auth=None)
        check(st == 200, "GET /metrics answers 200 on an empty journal")
        check(ctype.startswith("text/plain; version=0.0.4"), f"the text format's type ({ctype})")
        m = parse(text)
        check(m.get("lcars_reading") == {} and m.get("lcars_reading_timestamp_seconds") == {}
              and "lcars_entries_total" in m, "no readings, but every metric declared")
        # a new database holds no row (InitDB plants no seed)
        seeded = m.get("lcars_entries_total", {})
        check(seeded == {}, f"no row counted on a new journal ({seeded})")

        print("\nreadings")
        s.make(kind="sleep", title="7h 06m", value_float=7.1,
               created_at_utc="2026-10-10 05:00:00")
        s.make(kind="sleep", title="6h 18m", value_float=6.3,
               created_at_utc="2026-10-12 05:30:00")  # the latest
        s.make(kind="sleep", title="5h", value_float=5.0,
               created_at_utc="2026-10-11 05:00:00")  # newer id, older time
        late = s.make(kind="sleep", title="9h", value_float=9.0,
                      created_at_utc="2026-10-13 05:00:00")
        s.req("DELETE", f"/entries/{late}")                # deleted: not a reading
        s.make(kind="vocab", title="perete", value_int=211,
               created_at_utc="2026-10-12 10:00:00")
        s.make(kind="vocab", title="ulei", value_int=212,
               created_at_utc="2026-10-12 10:00:00")       # tie: the higher id
        s.make(kind="coffee", title="0", created_at_utc="2026-10-01 08:00:00")
        s.make(kind="coffee", title="2 cups", value_int=2,
               created_at_utc="2026-09-30 08:00:00")
        s.make(kind="coffee", title="0 today", created_at_utc="2026-10-02 08:00:00")
        s.make(kind="coffee", title="05 o'clock", created_at_utc="2026-10-03 08:00:00")
        s.make(kind="journal", title="no number here")
        s.make(kind="journal", title="0x not a zero reading")
        s.make(kind='we"ird\\kind', title="1", value_int=1,
               created_at_utc="2026-10-05 08:00:00")
        s.make(kind="", title="no kind", value_float=-2.5,
               created_at_utc="2026-10-06 08:00:00")

        st, text, _ = s.req("GET", "/metrics", auth=None)
        check(st == 200, "GET /metrics answers 200")
        m = parse(text)
        r, t, n = m["lcars_reading"], m["lcars_reading_timestamp_seconds"], m["lcars_entries_total"]
        check(r.get("sleep") == 6.3, f"sleep: the newest created_at_utc ({r.get('sleep')})")
        check(t.get("sleep") == utc("2026-10-12 05:30:00"), "sleep: its measurement time")
        check("lcars_reading{kind=\"sleep\"} 6.3\n" in text,
              "a float-stored 6.3 is written 6.3, not 6.300000190734863")
        check(r.get("vocab") == 212, "vocab: value_int, the higher id on a tie")
        check(r.get("coffee") == 0, "coffee: a zero title is a reading of 0")
        check(t.get("coffee") == utc("2026-10-02 08:00:00"),
              "coffee: '0 today' is the latest zero, \"05 o'clock\" is not one")
        check("journal" not in r, "rows with no number are not readings")
        check(r.get('we"ird\\kind') == 1, "a kind with a quote and a backslash, escaped")
        check(r.get("") == -2.5, "a reading with no kind, under kind=\"\"")
        for k, c in seeded.items():
            n[k] = n.get(k, 0) - c
            if n[k] == 0:
                del n[k]
        check(n == {"sleep": 3, "vocab": 2, "coffee": 4, "journal": 2,
                    'we"ird\\kind': 1, "": 1},
              f"lcars_entries_total counts live rows per kind ({n})")

        print("\nwho may read it")
        check(s.req("POST", "/metrics", {})[0] == 405, "POST /metrics is 405")
        lan = lan_address()
        if lan is None:
            print("  skip no address but loopback on this box")
        else:
            check(s.req("GET", "/metrics", auth=None, host=lan)[0] == 401,
                  f"from {lan} without a password: 401")
            check(s.req("GET", "/metrics", auth=(USER, "wrong"), host=lan)[0] == 401,
                  "a wrong password: 401")
            check(s.req("GET", "/metrics", host=lan)[0] == 200, "the password: 200")
    finally:
        s.stop()
    print("\nLCARS_ENG_METRICS set empty")
    (tmp / "eng.prom").write_text("lcars_seat_held 1\n")
    off = Server(binary, tmp, eng="")
    try:
        check(ENG_TS not in off.req("GET", "/metrics", auth=None)[1], "turned off: nothing appended")
    finally:
        off.stop()
    if fails:
        print(f"\nmetrics: {len(fails)} of {checks[0]} checks failed; server log in {tmp}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nmetrics: all {checks[0]} checks passed")


if __name__ == "__main__":
    main()
