#!/usr/bin/env python3
"""The Strava bridge, end to end: `lcars-cli strava auth|pull|status`.

lcars_strava.h pulls Strava activities into the journal as `workout`
entries. Strava itself cannot be in a test, so a small stand-in answers in
its place at LCARS_STRAVA_API (the OAuth token endpoint, the athlete, the
activity list and the detail), and the CLI runs against:

  1. a scratch build of the server (the lcars-release compile line, to a
     temp path - never `make` itself, which on the VPS would overwrite the
     live binary), on an empty database in a temp directory;
  2. a scratch build of lcars-cli (the `make -n lcars-cli` line, likewise),
     with HOME a temp directory, so the token file is a test's own;
  3. the grant: the authorize URL, a code (and the whole redirect address)
     traded for tokens, the file's modes, a refused code;
  4. a pull through an access token about to expire: refreshed, and the
     rotated refresh token is the one on disk;
  5. two pages of activities become entries - backdated, the numbers, the
     content's facts, description and identity line;
  6. a second pull creates nothing, and follows a rename (keeping a note the
     captain added); a deleted entry stays deleted;
  7. a 429 from the list and from a detail ends the pull cleanly, and the
     next one carries on without duplicates;
  8. status: the athlete and the count, a 429 on the athlete a note (exit
     0), a 401 a failure.

    python3 test/strava.py            # builds both first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/strava.py

Nothing here touches the journal, a running server or Strava.
"""
import base64
import calendar
import http.server
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import killclean  # its scratch goes when the run is killed

UI = pathlib.Path(__file__).resolve().parent.parent
REPO = UI.parent
USER, PASS = "t", "t"
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
CLIENT_ID, CLIENT_SECRET = "4242", "s3cret"
URL_LINE = "strava: https://www.strava.com/activities/{}"

fails = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def compile_line(target, source, out_name):
    """`make -n`'s compile line for `target`, writing `out` instead."""
    plan = subprocess.run(["make", "-n", "-W", source, target], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines()
                 if l.startswith("cc ") and f" -o {out_name} {source}" in l), None)
    if not line:
        sys.exit(f"strava: cannot find the {target} compile line in `make -n`")
    return line


def build(target, source, out_name, out):
    print(f"building a scratch {out_name} ...", flush=True)
    line = compile_line(target, source, out_name)
    r = subprocess.run(line.replace(f" -o {out_name} ", f" -o {out} ", 1), shell=True,
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("strava: build failed\n" + r.stderr[-3000:])


class Server:
    def __init__(self, binary, tmp):
        self.port = free_port()
        env = dict(os.environ, LCARS_EMBED="0", LCARS_CHAT="0",
                   LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS, LCARS_CALDAV_LOG="0")
        env.pop("LCARS_TZ", None)
        self.log = open(tmp / "server.log", "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), "--port", str(self.port)],
                                                     cwd=tmp, env=env, stdout=self.log,
                                                     stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        sys.exit("strava: the scratch server did not come up; see " + str(tmp / "server.log"))

    def json(self, method, path, obj=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(obj).encode() if obj is not None else None,
                                     headers={"Authorization": AUTH,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def workouts(self, deleted="0"):
        return self.json("GET", f"/entries?kind=workout&deleted={deleted}&limit=1000&order=id&dir=asc")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


# ---------------------------------------------------------------------------
# The stand-in Strava
# ---------------------------------------------------------------------------

def epoch_of(iso_):
    return calendar.timegm(time.strptime(iso_, "%Y-%m-%dT%H:%M:%SZ"))


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


NOW = int(time.time())
DAY = 86400


def activity(id_, name, sport, start, km, moving, elapsed, elev, speed, hr=None, desc="",
             kcal=0):
    a = {"id": id_, "name": name, "sport_type": sport, "type": sport, "start_date": iso(start),
         "distance": km * 1000, "moving_time": moving, "elapsed_time": elapsed,
         "total_elevation_gain": elev, "average_speed": speed, "max_speed": speed * 1.5,
         "has_heartrate": hr is not None, "_desc": desc, "_kcal": kcal}
    if hr:
        a["average_heartrate"], a["max_heartrate"] = hr
    return a


class Strava:
    """State and rules of the stand-in. Pages are PAGE long whatever
    per_page asks, so five activities are two pages and an empty third."""
    PAGE = 3

    def __init__(self):
        self.lock = threading.Lock()
        self.reset_tokens()
        # Ids 12 and 123: a `q` of .../activities/12 finds both.
        self.acts = [
            activity(12, "Old trail", "TrailRun", NOW - 4000 * DAY, 21.1, 7200, 7900, 840, 2.93,
                     hr=(151.4, 178), desc="Ridge loop.\nMud.", kcal=1500),
            activity(123, "Commute", "Ride", NOW - 3000 * DAY, 12.4, 1800, 2000, 60, 6.9),
            activity(9000000001, "Lunch swim", "Swim", NOW - 400 * DAY, 1.5, 2400, 2700, 0, 0.62),
            activity(9000000002, "Morning Run", "Run", NOW - 2 * DAY, 10.02, 3130, 3303, 120,
                     3.2, hr=(148, 172), desc="Easy.", kcal=650),
            activity(9000000003, "Gym", "WeightTraining", NOW - DAY, 0, 3600, 3900, 0, 0),
        ]
        self.calls = []
        self.limit_after = None  # a 429 to every request past this many
        self.limit_paths = ()

    def reset_tokens(self):
        self.gen = 0
        self.access = None
        self.refresh = None
        self.expires_at = 0

    def issue(self):
        self.gen += 1
        self.access, self.refresh = f"A{self.gen}", f"R{self.gen}"
        self.expires_at = int(time.time()) + 6 * 3600
        return {"token_type": "Bearer", "access_token": self.access,
                "refresh_token": self.refresh, "expires_at": self.expires_at,
                "expires_in": 6 * 3600}

    def handle(self, method, path, query, form, headers):
        with self.lock:
            self.calls.append((method, path, query, form))
            if self.limit_after is not None and path.startswith(self.limit_paths):
                if self.limit_after <= 0:
                    return 429, {"message": "Rate Limit Exceeded"}
                self.limit_after -= 1
            if path == "/oauth/token" and method == "POST":
                if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
                    return 401, {"message": "Bad Request", "errors": [{"field": "client_id"}]}
                if form.get("grant_type") == "authorization_code":
                    if form.get("code") != "good-code":
                        return 400, {"message": "Bad Request",
                                     "errors": [{"field": "code", "code": "invalid"}]}
                    out = self.issue()
                    out["athlete"] = {"id": 777, "firstname": "Ana", "lastname": "P"}
                    return 200, out
                if form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") != self.refresh:
                        return 400, {"message": "Bad Request",
                                     "errors": [{"field": "refresh_token", "code": "invalid"}]}
                    return 200, self.issue()
                return 400, {"message": "Bad Request"}
            if headers.get("Authorization") != f"Bearer {self.access}" or not self.access:
                return 401, {"message": "Authorization Error"}
            if time.time() >= self.expires_at:
                return 401, {"message": "Authorization Error", "errors": [{"code": "expired"}]}
            if path == "/api/v3/athlete":
                return 200, {"id": 777, "firstname": "Ana", "lastname": "P"}
            if path == "/api/v3/athlete/activities":
                after = int(query.get("after", "0"))
                page = int(query.get("page", "1"))
                rows = sorted((a for a in self.acts if epoch_of(a["start_date"]) > after),
                    key=lambda a: a["start_date"])
                rows = rows[(page - 1) * self.PAGE: page * self.PAGE]
                return 200, [{k: v for k, v in a.items() if not k.startswith("_")} for a in rows]
            m = re.fullmatch(r"/api/v3/activities/(\d+)", path)
            if m:
                a = next((a for a in self.acts if a["id"] == int(m.group(1))), None)
                if not a:
                    return 404, {"message": "Resource Not Found"}
                d = {k: v for k, v in a.items() if not k.startswith("_")}
                d["description"] = a["_desc"] or None
                d["calories"] = a["_kcal"]
                return 200, d
            return 404, {"message": "Resource Not Found"}

    def count(self, prefix):
        return sum(1 for c in self.calls if c[1].startswith(prefix))


def stub_server(strava):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def go(self):
            u = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(u.query))
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode() if n else ""
            form = dict(urllib.parse.parse_qsl(raw)) if raw else {}
            st, obj = strava.handle(self.command, u.path, query, form, self.headers)
            body = json.dumps(obj).encode()
            self.send_response(st)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = go

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

class Cli:
    def __init__(self, binary, server, stub_port, home):
        self.binary = binary
        self.home = home
        self.env = dict(os.environ, HOME=str(home), LCARS_URL=f"http://127.0.0.1:{server.port}",
                        LCARS_AUTH_USER=USER, LCARS_AUTH_PASS=PASS,
                        LCARS_STRAVA_API=f"http://127.0.0.1:{stub_port}/",
                        LCARS_STRAVA_CLIENT_ID=CLIENT_ID,
                        LCARS_STRAVA_CLIENT_SECRET=CLIENT_SECRET)

    def __call__(self, *args):
        r = subprocess.run([str(self.binary), "strava", *args], env=self.env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    @property
    def token_path(self):
        return self.home / ".lcars-strava" / "token.json"

    def token(self):
        return json.loads(self.token_path.read_text())


def content_of(rows, sid):
    line = URL_LINE.format(sid)
    hits = [r for r in rows if line in (r.get("content") or "").split("\n")]
    return hits


def run(s, cli, strava):
    print("before the grant")
    rc, out, err = cli("status")
    check(rc == 1 and "not connected" in out, "status says not connected")
    rc, out, err = cli("pull")
    check(rc == 1 and "strava auth" in err, "pull asks for `strava auth`")
    rc, out, err = cli("pull", "--since", "2010-13-01")
    check(rc == 2, "a bad --since is a usage error")

    print("the grant")
    rc, out, err = cli("auth")
    url = out.strip()
    u = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    check(rc == 0 and u.path == "/oauth/authorize" and url.startswith(cli.env["LCARS_STRAVA_API"].rstrip("/")),
          "auth prints the authorize URL on LCARS_STRAVA_API")
    check(q == {"client_id": CLIENT_ID, "redirect_uri": "http://localhost",
                "response_type": "code", "approval_prompt": "auto",
                "scope": "activity:read_all"}, f"with every parameter: {q}")
    rc, out, err = cli("auth", "bad-code")
    check(rc == 1 and "400" in err and not cli.token_path.exists(),
          "a refused code fails and writes no token file")
    rc, out, err = cli("auth", "http://localhost/?state=&code=good-code&scope=read,activity:read_all")
    tok = cli.token() if cli.token_path.exists() else {}
    check(rc == 0 and "Ana P" in out and tok.get("refresh_token") == "R1"
          and tok.get("access_token") == "A1" and tok.get("athlete_id") == 777
          and tok.get("athlete_name") == "Ana P" and tok.get("last_pull_epoch") == 0,
          "the redirect's whole address is traded for tokens, and they are on disk")
    ex = [c for c in strava.calls if c[1] == "/oauth/token"][-1][3]
    check(ex.get("grant_type") == "authorization_code" and ex.get("code") == "good-code",
          "the exchange sends the code and grant type")
    check(stat.S_IMODE(cli.token_path.stat().st_mode) == 0o600, "token.json is 0600")
    check(stat.S_IMODE(cli.token_path.parent.stat().st_mode) == 0o700, "~/.lcars-strava is 0700")
    rc, out, err = cli("auth", "http://localhost/?state=&code=good-code&scope=read")
    check(rc == 0 and "private activities will be missing" in err,
          "a grant without activity:read_all is warned about")
    check(cli.token()["refresh_token"] == "R2", "and is the grant in the file")

    print("refresh with rotation")
    t = cli.token()
    t["expires_at"] = int(time.time()) + 30  # inside the 60 s margin
    cli.token_path.write_text(json.dumps(t))
    strava.expires_at = int(time.time()) + 30
    rc, out, err = cli("pull", "--dry-run")
    tok = cli.token()
    check(rc == 0 and tok["refresh_token"] == "R3" and tok["access_token"] == "A3",
          "an access token within 60 s of expiry is refreshed, the rotated refresh token saved")
    rf = [c for c in strava.calls if c[1] == "/oauth/token"][-1][3]
    check(rf.get("grant_type") == "refresh_token" and rf.get("refresh_token") == "R2",
          "with the refresh token it had")
    check(stat.S_IMODE(cli.token_path.stat().st_mode) == 0o600, "token.json is still 0600 after the rewrite")

    print("dry run")
    check(out.count("create ") == 5 and "5 to create" in err, f"--dry-run names 5 to create: {err.strip()}")
    check(s.workouts("all") == [] and tok["last_pull_epoch"] == 0,
          "and writes no entry and no cursor")
    check(strava.count("/api/v3/activities/") == 0, "and asks for no detail")

    print("first pull: two pages")
    n_list = strava.count("/api/v3/athlete/activities")
    rc, out, err = cli("pull")
    rows = s.workouts()
    check(rc == 0 and len(rows) == 5 and "5 created" in err, f"5 entries created: {err.strip()}")
    lists = [c for c in strava.calls if c[1] == "/api/v3/athlete/activities"][n_list:]
    check([c[2].get("page") for c in lists] == ["1", "2", "3"]
          and all(c[2].get("per_page") == "200" and c[2].get("after") == "0" for c in lists),
          "the list is paged (per_page=200, after=0) until an empty page")
    check(strava.count("/api/v3/activities/") == 5, "one detail per new activity")
    tok = cli.token()
    check(abs(tok["last_pull_epoch"] - time.time()) < 60, "the cursor is the pull's start")
    by = {a["id"]: content_of(rows, a["id"]) for a in strava.acts}
    check(all(len(v) == 1 for v in by.values()), "each activity is exactly one entry (12 vs 123 apart)")
    run_e = by[9000000002][0]
    check(run_e["title"] == "Morning Run" and run_e["kind"] == "workout", "titled with the name, kind workout")
    check(run_e["created_at_utc"] == iso(NOW - 2 * DAY).replace("T", " ").rstrip("Z"),
          f"backdated to the start: {run_e['created_at_utc']}")
    check(abs(run_e["value_float"] - 10.02) < 1e-6 and run_e["value_int"] == 52,
          f"value_float km, value_int moving minutes: {run_e['value_float']}, {run_e['value_int']}")
    first, *rest = run_e["content"].split("\n")
    check(first == "Run · 10.02 km · moving 52:10 · elapsed 55:03 · 120 m up · "
                   "HR 148 avg / 172 max · 5:13 /km · 650 kcal", f"the facts line: {first}")
    check(run_e["content"].endswith("\n\nEasy.\n\n" + URL_LINE.format(9000000002)),
          "then the description, then the identity line")
    trail = by[12][0]["content"]
    check(trail.startswith("Trail run · 21.10 km · moving 2:00:00 · elapsed 2:11:40 · 840 m up · "
                           "HR 151 avg / 178 max · 5:41 /km · 1500 kcal\n\nRidge loop.\nMud.\n\n"),
          f"a trail run: hours, pace, a two-line description: {trail.splitlines()[0]}")
    ride = by[123][0]["content"]
    check(ride.splitlines()[0] == "Ride · 12.40 km · moving 30:00 · elapsed 33:20 · 60 m up · 24.8 km/h"
          and "\n\n" + URL_LINE.format(123) in ride,
          f"a ride: km/h, no heart rate, no description: {ride.splitlines()[0]}")
    gym = by[9000000003][0]
    check(gym["content"].splitlines()[0] == "Weight training · moving 1:00:00 · elapsed 1:05:00"
          and gym["value_float"] == 0 and gym["value_int"] == 60,
          f"no distance: no km, no speed, 60 minutes: {gym['content'].splitlines()[0]}")

    print("second pull")
    swim = by[9000000001][0]
    s.json("PUT", f"/entries/{run_e['id']}",
           {"content": run_e["content"] + "\nFelt strong. [[Riverside]]"})
    s.json("DELETE", f"/entries/{swim['id']}")
    strava.acts[3]["name"] = "Morning Run in the rain"
    strava.acts[3]["_desc"] = "Easy, wet."
    details = strava.count("/api/v3/activities/")
    rc, out, err = cli("pull")
    lists = [c for c in strava.calls if c[1] == "/api/v3/athlete/activities"]
    after = int(lists[-1][2]["after"])
    check(abs(after - (tok["last_pull_epoch"] - 7 * DAY)) == 0,
          "without --since it starts 7 days before the last pull")
    rows = s.workouts()
    check(rc == 0 and len(rows) == 4 and "0 created" in err and "1 updated" in err,
          f"nothing created, the renamed one updated: {err.strip()}")
    check(strava.count("/api/v3/activities/") == details + 1, "one detail: the changed activity's")
    e = next(r for r in rows if r["id"] == run_e["id"])
    check(e["title"] == "Morning Run in the rain", "the rename followed")
    check(e["created_at_utc"] == run_e["created_at_utc"], "created_at_utc untouched")
    check("\n\nEasy, wet.\n\n" + URL_LINE.format(9000000002) + "\nFelt strong. [[Riverside]]"
          in e["content"], "the new description, and the captain's note under the line kept")
    rc, out, err = cli("pull", "--since", "2010-01-01")
    rows = s.workouts()
    check(rc == 0 and len(rows) == 4 and "0 created" in err and "0 updated" in err
          and "1 deleted here" in err, f"--since 2010: nothing new, the deleted swim stays deleted: {err.strip()}")
    check(strava.count("/api/v3/activities/") == details + 1, "and no detail asked for")
    check(len(s.workouts("1")) == 1, "the swim is still the one deleted entry")

    print("rate limits")
    for i in range(4):
        strava.acts.append(activity(9100000000 + i, f"Easy {i}", "Run", NOW - 3600 * (20 - i), 5, 1500,
                                    1600, 10, 3.33))
    strava.limit_after, strava.limit_paths = 0, ("/api/v3/athlete/activities",)
    before = cli.token()["last_pull_epoch"]
    rc, out, err = cli("pull")
    check(rc == 0 and "429" in err and "0 created" in err, f"a 429 on the list ends the pull: {err.strip()}")
    check(cli.token()["last_pull_epoch"] == before, "and leaves the cursor")
    strava.limit_after, strava.limit_paths = 2, ("/api/v3/activities/",)
    details = strava.count("/api/v3/activities/")
    rc, out, err = cli("pull", "--since", "2010-01-01")
    rows = s.workouts()
    check(rc == 0 and "429" in err and "2 created" in err and len(rows) == 6,
          f"a 429 on a detail stops after the two it got: {err.strip()}")
    check(strava.count("/api/v3/activities/") - details == 3,
          "the 429 is the last request: no retry, no next activity")
    cur = cli.token()["last_pull_epoch"]
    check(cur == before, "a cursor already past the stop is not moved back")
    strava.limit_after = None
    rc, out, err = cli("pull")
    rows = s.workouts()
    check(rc == 0 and "2 created" in err and len(rows) == 8, f"the next pull carries on: {err.strip()}")
    check(all(len(content_of(rows, a["id"])) == 1 for a in strava.acts if a["id"] != 9000000001),
          "no activity twice")

    print("a first pull cut short keeps its place")
    for t_ in (cli.token_path,):
        t = cli.token()
        t["last_pull_epoch"] = 0
        t_.write_text(json.dumps(t))
    strava.acts.append(activity(9200000000, "Late upload", "Run", NOW - 3600, 5, 1500, 1600, 10, 3.33))
    strava.limit_after, strava.limit_paths = 0, ("/api/v3/activities/",)
    rc, out, err = cli("pull")
    t = cli.token()
    newest_done = max(epoch_of(a["start_date"]) for a in strava.acts if a["id"] != 9200000000)
    check(rc == 0 and "429" in err and t["last_pull_epoch"] == newest_done,
          f"the cursor is the newest activity it finished: {t['last_pull_epoch']} vs {newest_done}")
    strava.limit_after = None

    print("status")
    rc, out, err = cli("status")
    check(rc == 0 and "Ana P (athlete 777)" in out and "last pull:" in out
          and "8 workout from Strava" in out, f"status: {out.strip()!r}")
    s.json("POST", "/entries", {"kind": "workout", "title": "by hand", "content": "pushups"})
    rc, out, err = cli("status")
    check("8 workout from Strava" in out, "a workout typed by hand is not counted")
    strava.limit_after, strava.limit_paths = 0, ("/api/v3/athlete",)
    rc, out, err = cli("status")
    strava.limit_after = None
    check(rc == 0 and "Ana P (athlete 777, from the token file" in out and "429" in out
          and "last pull:" in out and "8 workout from Strava" in out,
          f"a 429 on the athlete is a note, from the token file, exit 0: {out.strip()!r} {err.strip()!r}")
    t = cli.token()
    cli.token_path.write_text(json.dumps(dict(t, access_token="revoked")))
    rc, out, err = cli("status")
    check(rc == 1 and "401" in err and "8 workout from Strava" in out,
          f"a 401 on the athlete is still a failure: {err.strip()!r}")
    cli.token_path.write_text(json.dumps(t))

    print("the workout role (lcars_kinds.h): the pull and status ask the server for the kind")
    ans = s.json("PUT", "/kinds/roles", {"workout": {"kind": "training"}})  # raises on a non-2xx
    check(any(r["role"] == "workout" and r["kind"] == "training" for r in ans["roles"]),
          "the owner sets the workout role to training")
    strava.acts.append(activity(9300000000, "Evening Ride", "Ride", NOW - 1800, 20, 3000, 3200, 50, 6.6))
    today = time.strftime("%Y-%m-%d", time.gmtime(NOW))
    rc, out, err = cli("pull", "--since", today)
    # what the pull asked for, however it reads the date: the list's `after`
    since = int([q for m, p, q, f in strava.calls if p == "/api/v3/athlete/activities"][-1]["after"])
    want = sorted(a["id"] for a in strava.acts if epoch_of(a["start_date"]) > since)
    rows = s.json("GET", "/entries?kind=training&limit=1000")
    got = sorted(int(re.search(r"activities/(\d+)", r["content"]).group(1)) for r in rows)
    check(rc == 0 and got == want and 9300000000 in got,
          f"the pull writes training rows, matched within that kind ({got} vs {want}): {err.strip()}")
    check(len(s.workouts()) == 9, "the workout rows are left as they were (the by-hand one included)")
    rc, out, err = cli("status")
    check(f"{len(want)} training from Strava" in out, f"status counts the training kind: {out.strip()!r}")
    s.json("PUT", "/kinds/roles", {"workout": None})
    check(s.proc.poll() is None, "the server is still up")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-strava-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        build("lcars-release", "lcars.c", "lcars", binary)
    cli_bin = tmp / "lcars-cli"
    build("lcars-cli", "lcars_cli.c", "lcars-cli", cli_bin)
    home = tmp / "home"
    home.mkdir()
    strava = Strava()
    stub = stub_server(strava)
    s = Server(binary, tmp)
    try:
        run(s, Cli(cli_bin, s, stub.server_address[1], home), strava)
    finally:
        s.stop()
        stub.shutdown()
    if fails:
        print(f"\n{len(fails)} of {checks[0]} checks failed; server log: {tmp / 'server.log'}")
        sys.exit(1)
    print(f"\nall {checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
