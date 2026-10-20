#!/usr/bin/env python3
"""The server's start-up configuration (lcars_config.h), end to end against
scratch builds and temp directories:

  1. the version: `lcars version`, `--version` and the start log's first
     line name CHANGELOG.md's top entry;
  2. lcars.env: none is read when there is none (the start log says so);
     one in --data, $LCARS_DATA_DIR or the working directory is read -
     comments, blank lines, `export`, both quotes, a \\r, a malformed line
     and LCARS_DATA_DIR skipped - and seen by the server (its login and
     port come from it), and the real environment wins over it; the start
     log's "Config: read <path>: N set, M already in the environment, K
     skipped"; a file others can read is warned about; LCARS_DB_PATH in
     it places the journal;
  3. `lcars init DIR`: the directory, media/, lcars.env (mode 600, the
     Start keys set, the feature keys commented), a journal through InitDB,
     the URL and the login printed; a server started on it with nothing
     else answers on that port with that login; a second init changes no
     byte and says what it left alone; the refusals.

    python3 test/config.py               # builds the server first (~30s)
    LCARS_TEST_BIN=/path/to/lcars python3 test/config.py

Nothing here touches the journal or a running server.
"""
import base64
import http.client
import hashlib
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import api  # noqa: E402  (build, free_port, check)
import killclean  # noqa: E402

check = api.check
CHANGELOG = (api.REPO / "CHANGELOG.md").read_text()
VERSION = re.search(r"^## (\d+\.\d+\.\d+) ", CHANGELOG, re.M).group(1)


def base_env(**extra):
    """The environment with no LCARS_* of the caller's (an engineer's shell
    may carry the live login), the embedder and the chat off."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LCARS_", "DEEPGRAM_"))}
    env.update(LCARS_EMBED="0", LCARS_CHAT="0", LCARS_CALDAV_LOG="0")
    env.update(extra)
    return env


class Run:
    """A scratch server started with `args` in `cwd`; up once /health
    answers on `port`."""

    def __init__(self, binary, cwd, args, env, port, log):
        self.port = port
        self.log_path = log
        self.log = open(log, "w")
        pre = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        self.proc = killclean.child(subprocess.Popen(pre + [str(binary), *args], cwd=cwd, env=env,
                                                     stdout=self.log, stderr=subprocess.STDOUT))
        for _ in range(100):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                c.request("GET", "/health")
                c.getresponse().read()
                c.close()
                return
            except OSError:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
        self.stop()
        sys.exit(f"config: the scratch server did not come up on {port}; see {log}:\n{log.read_text()}")

    def status(self, user, pw):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
        c.request("GET", "/entries?limit=1", headers={"Authorization": "Basic " + auth})
        st = c.getresponse().status
        c.close()
        return st

    def lines(self):
        return self.log_path.read_text().splitlines()

    def line(self, prefix):
        return next((l for l in self.lines() if l.startswith(prefix)), "")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def version(binary, tmp):
    print("the version")
    for arg in ("version", "--version"):
        r = subprocess.run([str(binary), arg], capture_output=True, text=True, timeout=10, cwd=tmp)
        check(r.returncode == 0 and r.stdout.strip() == f"lcars {VERSION}",
              f"`lcars {arg}` says lcars {VERSION} (got {r.returncode}, {r.stdout.strip()!r})")
    check(not (tmp / "lcars.db").exists(), "`lcars version` opens no journal")


def envfile(binary, tmp):
    base = tmp / "env"
    base.mkdir()

    print("no lcars.env: nothing read, and the start log says so")
    d = base / "none"
    d.mkdir()
    port = api.free_port()
    s = Run(binary, d, ["--port", str(port)], base_env(LCARS_AUTH_USER="u", LCARS_AUTH_PASS="p"), port,
            d / "server.log")
    try:
        check(s.lines()[:1] == [f"LCARS {VERSION}"], f"the start log's first line is LCARS {VERSION} (got {s.lines()[:1]})")
        check(s.line("Config: ") == f"Config: no lcars.env in {d.resolve()} (the environment only)",
              f"no file: said (got {s.line('Config: ')!r})")
        check(s.status("u", "p") == 200, "the environment's login stands")
        want = f"Media: {d.resolve()}/media (the default; LCARS_MEDIA_ROOT moves it)"
        check(s.line("Media: ") == want, f"no LCARS_MEDIA_ROOT: <data dir>/media, absolute (got {s.line('Media: ')!r})")
    finally:
        s.stop()

    def write(d, port, mode=0o600, extra=""):
        p = d / "lcars.env"
        p.write_text(
            "# a comment\n"
            "\n"
            "   # an indented comment\n"
            "export LCARS_AUTH_USER=fileuser\n"
            'LCARS_AUTH_PASS="file pass # not a comment"\n'
            f"LCARS_PORT='{port}'\r\n"
            "LCARS_TZ=Europe/London\n"
            "this is not a pair\n"
            "1BAD=x\n"
            "LCARS_DATA_DIR=/nonexistent\n" + extra)
        os.chmod(p, mode)
        return p

    pw = "file pass # not a comment"
    for how in ("--data", "LCARS_DATA_DIR", "the working directory"):
        print(f"lcars.env found by {how}, read, and the server runs on it")
        d = base / how.replace(" ", "-").replace("--", "")
        (d / "data").mkdir(parents=True)
        port = api.free_port()
        f = write(d / "data", port)
        args, env, cwd = [], base_env(), d
        if how == "--data":
            args = ["--data", str(d / "data")]
        elif how == "LCARS_DATA_DIR":
            env["LCARS_DATA_DIR"] = str(d / "data")
        else:
            cwd = d / "data"
        s = Run(binary, cwd, args, env, port, d / "server.log")
        try:
            check(s.status("fileuser", pw) == 200,
                  f"{how}: its port and its login, export and quotes stripped, # kept in a value")
            check(s.status("fileuser", "wrong") == 401, f"{how}: a wrong password still refused")
            got = s.line("Config: read")
            check(got == f"Config: read {f.resolve()}: 4 set, 0 already in the environment, 3 skipped",
                  f"{how}: the start log names the file and its counts (got {got!r})")
            bad = [l for l in s.lines() if "is not KEY=value" in l]
            check(len(bad) == 2 and all("line 8" in l or "line 9" in l for l in bad)
                  and not any("not a pair" in l for l in s.lines()),
                  f"{how}: a malformed line named by number, never its text (got {bad})")
            check(any("LCARS_DATA_DIR is ignored" in l for l in s.lines()),
                  f"{how}: LCARS_DATA_DIR in the file is ignored, and said")
            check(s.line("Database: ").startswith(f"Database: {(d / 'data' / 'lcars.db').resolve()} "),
                  f"{how}: the journal is beside the file (got {s.line('Database: ')!r})")
            check(not any("readable by others" in l for l in s.lines()), f"{how}: no warning on a 600 file")
        finally:
            s.stop()

    print("the real environment wins over the file")
    d = base / "wins"
    d.mkdir()
    port = api.free_port()
    f = write(d, port, mode=0o644)
    s = Run(binary, d, [], base_env(LCARS_AUTH_PASS="envpass", LCARS_TZ="UTC"), port, d / "server.log")
    try:
        check(s.status("fileuser", "envpass") == 200, "the environment's password, the file's user")
        check(s.status("fileuser", pw) == 401, "the file's password refused")
        got = s.line("Config: read")
        check(got == f"Config: read {f.resolve()}: 2 set, 2 already in the environment, 3 skipped",
              f"the counts say so (got {got!r})")
        check(any("readable by others (mode 644)" in l for l in s.lines()), "a 644 file is warned about")
    finally:
        s.stop()

    print("--port wins over LCARS_PORT, and LCARS_DB_PATH in the file places the journal")
    d = base / "dbpath"
    d.mkdir()
    port = api.free_port()
    write(d, api.free_port(), extra="LCARS_DB_PATH=j.db\n")
    s = Run(binary, d, ["--port", str(port)], base_env(), port, d / "server.log")
    try:
        check(s.status("fileuser", pw) == 200, "the flag's port")
        check(s.line("Database: ").startswith(f"Database: {(d / 'j.db').resolve()} (NEW"),
              f"the journal is the file's LCARS_DB_PATH (got {s.line('Database: ')!r})")
        check(not (d / "lcars.db").exists(), "and no lcars.db beside it")
    finally:
        s.stop()

    print("refused: an unreadable lcars.env, a bad LCARS_PORT")
    d = base / "refused"
    d.mkdir()
    (d / "lcars.env").mkdir()  # a directory: exists, cannot be read as a file
    r = subprocess.run([str(binary)], cwd=d, env=base_env(), capture_output=True, text=True, timeout=10)
    check(r.returncode == 2 and "cannot read" in r.stderr and not (d / "lcars.db").exists(),
          f"an unreadable lcars.env: exit 2, no journal (got {r.returncode}, {r.stderr.strip()!r})")
    (d / "lcars.env").rmdir()
    r = subprocess.run([str(binary)], cwd=d, env=base_env(LCARS_PORT="99999"), capture_output=True,
                       text=True, timeout=10)
    check(r.returncode == 1 and "Invalid LCARS_PORT" in r.stderr, f"LCARS_PORT=99999 refused (got {r.returncode})")


def digest(d):
    """Every file under d: its bytes' hash and its mode."""
    return {str(p.relative_to(d)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode)
            for p in sorted(d.rglob("*")) if p.is_file()}


def init(binary, tmp):
    print("lcars init: a data directory to start from")
    d = tmp / "init" / "deep" / "data"
    port = api.free_port()
    r = subprocess.run([str(binary), "init", str(d), "--port", str(port), "--user", "kirk"],
                       cwd=tmp, env=base_env(), capture_output=True, text=True, timeout=20)
    check(r.returncode == 0, f"exit 0 (got {r.returncode}, {r.stderr.strip()!r})")
    out = r.stdout
    check(d.is_dir() and (d / "media" / "media").is_dir(),
          "the directory (and its parents) and media/media/ (the root, and the store in it) made")
    check(stat.S_IMODE(d.stat().st_mode) == 0o700, "the directory is 700")
    env = d / "lcars.env"
    check(env.is_file() and stat.S_IMODE(env.stat().st_mode) == 0o600, "lcars.env, mode 600")
    text = env.read_text() if env.is_file() else ""
    m = re.search(r"^LCARS_AUTH_PASS=([A-Za-z0-9_-]{24})$", text, re.M)
    check(m is not None, "a generated 24-character password")
    pw = m.group(1) if m else ""
    for want in ("LCARS_AUTH_USER=kirk", f"LCARS_PORT={port}", "LCARS_BIND=127.0.0.1",
                 f"LCARS_MEDIA_ROOT={d.resolve()}/media"):
        check(re.search(rf"^{re.escape(want)}$", text, re.M) is not None, f"lcars.env sets {want}")
    for key in ("LCARS_CLAUDE_BIN", "DEEPGRAM_API_KEY", "LCARS_MAPY_KEY", "LCARS_EMBED_URL",
                "LCARS_STRAVA_CLIENT_ID", "LOGSEQ_TOKEN", "LCARS_ENGINEER_KEY", "LCARS_NO1_USER",
                "LCARS_FFMPEG_BIN", "LCARS_TTS"):
        check(re.search(rf"^# {key}=", text, re.M) is not None, f"{key} there, commented out")
    commented = [l for l in text.splitlines() if re.match(r"# [A-Z_]+=", l)]
    check(all(text.splitlines()[text.splitlines().index(l) - 1].startswith("#") for l in commented),
          "every feature key under a comment line")
    con = sqlite3.connect(d / "lcars.db")
    rows = con.execute("SELECT kind, title FROM entries").fetchall()
    con.close()
    check(rows == [], f"a journal through InitDB, empty: no seed row (got {rows})")
    check(f"http://127.0.0.1:{port}/ui/" in out and f"kirk / {pw}" in out and f"lcars --data {d.resolve()}" in out,
          "the URL, the login and how to start it printed")
    check(out.count("made") == 4, f"four things made, each said (got {out.count('made')})")

    print("a server started on it with nothing else")
    s = Run(binary, tmp, ["--data", str(d)], base_env(), port, tmp / "init.log")
    try:
        check(s.status("kirk", pw) == 200, "answers on init's port with init's login")
        check(s.status("kirk", "x") == 401, "and refuses another password")
        check(s.line("Database: ").startswith(f"Database: {(d / 'lcars.db').resolve()} (existing, 0 entries)"),
              f"on init's journal (got {s.line('Database: ')!r})")
        check(s.line("Config: read").endswith(": 5 set, 0 already in the environment, 0 skipped"),
              f"the five Start keys read (got {s.line('Config: read')!r})")
        check(s.line("Media: ") == f"Media: LCARS_MEDIA_ROOT={d.resolve()}/media",
              f"the media root init wrote (got {s.line('Media: ')!r})")
    finally:
        s.stop()

    print("init again: nothing written, everything left alone")
    before = digest(d)
    r = subprocess.run([str(binary), "init", str(d), "--port", "1", "--user", "spock"],
                       cwd=tmp, env=base_env(), capture_output=True, text=True, timeout=20)
    check(r.returncode == 0, f"exit 0 (got {r.returncode})")
    check(digest(d) == before, "no byte and no mode changed")
    check(r.stdout.count("left alone") == 4 and "made" not in r.stdout and pw not in r.stdout,
          f"four things left alone, no password printed (got {r.stdout!r})")

    print("init refused")
    for args, says in [([], "Usage"), ([str(tmp / "x"), "--user", "a:b"], "letters"),
                       ([str(tmp / "x"), "--port", "0"], "invalid port"),
                       ([str(tmp / "x"), "--bogus"], "Usage")]:
        r = subprocess.run([str(binary), "init", *args], cwd=tmp, env=base_env(), capture_output=True,
                           text=True, timeout=10)
        check(r.returncode == 2 and says in r.stderr, f"init {args}: exit 2, {says!r} (got {r.returncode})")
    check(not (tmp / "x").exists(), "nothing made by a refused init")
    f = tmp / "afile"
    f.write_text("")
    r = subprocess.run([str(binary), "init", str(f)], cwd=tmp, env=base_env(), capture_output=True,
                       text=True, timeout=10)
    check(r.returncode == 1 and f.read_text() == "", f"init on a file: exit 1, the file untouched (got {r.returncode})")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-config-"))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars"
        api.build(binary)
    version(binary, tmp)
    envfile(binary, tmp)
    init(binary, tmp)
    if api.fails:
        print(f"\n{len(api.fails)} of {api.checks[0]} checks failed; scratch: {tmp}")
        sys.exit(1)
    print(f"\nall {api.checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
