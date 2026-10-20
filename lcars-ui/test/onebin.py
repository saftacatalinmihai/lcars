#!/usr/bin/env python3
"""The one binary (`make lcars-one`, step 3 of
docs/design/open-source-build.md): the server with the CLI linked in, end to
end against scratch builds in a temp directory:

  1. serve: `lcars-one --data D` answers, and its start log names the
     version, D's lcars.env, D/bin/lcars-cli (a symlink to itself, made at
     start, the chat's LCARS_CLI_DIR) and D/lcars.db; the working directory
     is never written;
  2. cli: `lcars-one cli ARGS`, D/bin/lcars-cli ARGS and a symlink of the
     user's own each answer exactly what the separate lcars-cli does -
     help, a write, list, get, stats, an error's text and exit code;
  3. the link: kept when right, replaced when it points elsewhere, a real
     file of that name left alone, nothing made when LCARS_CLI_DIR is set;
  4. init and version through the one binary; init twice changes no byte;
  5. the lcars-release build (what the VPS runs): `lcars cli` and a
     lcars-cli name refused, and no bin/ made by serving.

    python3 test/onebin.py      # builds lcars-one, lcars-cli, lcars (~60s)

Nothing here touches the journal or a running server.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import api  # noqa: E402  (build, free_port, check, REPO)
import config  # noqa: E402  (Run, base_env, digest, VERSION)
import killclean  # noqa: E402

check = api.check
REPO = api.REPO
VERSION = config.VERSION


def build_one(out_dir):
    """lcars-one, from the lines `make -n` prints, its objects and output
    moved into out_dir (never build/ or ./lcars-one in the checkout)."""
    print("building a scratch lcars-one ...", flush=True)
    plan = subprocess.run(["make", "-n", "-W", "lcars.c", "lcars-one"], cwd=REPO,
                          capture_output=True, text=True).stdout
    lines = [l for l in plan.splitlines() if l.startswith("cc ")]
    if len(lines) != 3:
        sys.exit(f"onebin: expected three cc lines from `make -n lcars-one`, got:\n{plan}")
    for line in lines:
        line = line.replace("build/one/", f"{out_dir}/").replace(" -o lcars-one ", f" -o {out_dir}/lcars-one ")
        r = subprocess.run(line, shell=True, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0 or "warning" in r.stderr:
            sys.exit("onebin: lcars-one build failed or warned\n" + r.stderr[-3000:])
    return out_dir / "lcars-one"


def build_cli(out):
    print("building a scratch lcars-cli ...", flush=True)
    plan = subprocess.run(["make", "-n", "-W", "lcars_cli.c", "lcars-cli"], cwd=REPO,
                          capture_output=True, text=True).stdout
    line = next((l for l in plan.splitlines() if l.startswith("cc ") and " -o lcars-cli " in l), None)
    if not line:
        sys.exit("onebin: cannot find the lcars-cli compile line in `make -n`")
    r = subprocess.run(line.replace(" -o lcars-cli ", f" -o {out} ", 1), shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("onebin: lcars-cli build failed\n" + r.stderr[-3000:])


# A stand-in claude for the chat: finds lcars-cli on the PATH the server gave
# it and runs `lcars-cli stats` against the server (LCARS_URL is the chat's,
# the login the server's own, from lcars.env), keeping what it saw.
CLAUDE = """#!/usr/bin/env python3
import json, os, shutil, subprocess, sys
sys.stdin.read()
found = shutil.which("lcars-cli")
r = subprocess.run([found or "lcars-cli", "stats"], capture_output=True, text=True) if found else None
with open(os.environ["STUB_OUT"], "w") as f:
    json.dump({"found": found, "dir": os.environ.get("LCARS_CLI_DIR"),
               "rc": r.returncode if r else None, "out": r.stdout if r else ""}, f)
print(json.dumps({"type": "assistant", "text": "seen"}))
"""


def chat_once(port, user, pw, stub_out):
    """POST /chat and wait for the stand-in to have written what it saw."""
    import base64, http.client, json, time
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    c.request("POST", "/chat", body=json.dumps({"message": "how many entries?"}),
              headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"})
    r = c.getresponse()
    r.read()
    c.close()
    for _ in range(100):
        if stub_out.exists() and stub_out.stat().st_size:
            return r.status, json.loads(stub_out.read_text())
        time.sleep(0.1)
    return r.status, None


def run(argv, env, cwd):
    r = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def serve_and_cli(one, cli, tmp):
    d = tmp / "data"
    cwd = tmp / "cwd"
    cwd.mkdir()
    r = run([one, "init", d, "--port", str(api.free_port()), "--user", "kirk"], config.base_env(), cwd)
    check(r[0] == 0, f"lcars-one init: exit 0 (got {r[0]}, {r[2].strip()!r})")
    env_text = (d / "lcars.env").read_text()
    port = int(next(l for l in env_text.splitlines() if l.startswith("LCARS_PORT=")).split("=")[1])
    pw = next(l for l in env_text.splitlines() if l.startswith("LCARS_AUTH_PASS=")).split("=", 1)[1]

    print("serve: lcars-one --data D, from another directory")
    claude = tmp / "claude"
    claude.write_text(CLAUDE)
    claude.chmod(0o755)
    (tmp / "home").mkdir()
    stub_out = tmp / "claude.json"
    chat_env = config.base_env(LCARS_CHAT="1", LCARS_CLAUDE_BIN=str(claude), LCARS_CHAT_DIR=str(tmp / "home"),
                               STUB_OUT=str(stub_out))
    s = config.Run(one, cwd, ["--data", str(d)], chat_env, port, tmp / "serve.log")
    try:
        exe = str(one.resolve())
        link = (d / "bin" / "lcars-cli").resolve(strict=False)
        lines = s.lines()
        check(lines[:1] == [f"LCARS {VERSION}"], f"the start log's first line (got {lines[:1]})")
        check(s.line("Config: read ").startswith(f"Config: read {(d / 'lcars.env').resolve()}:"),
              f"D's lcars.env read (got {s.line('Config: ')!r})")
        check(s.line("CLI: ") == f"CLI: {d.resolve()}/bin/lcars-cli -> {exe}",
              f"the chat's lcars-cli made and named (got {s.line('CLI: ')!r})")
        check(os.readlink(d / "bin" / "lcars-cli") == exe, "D/bin/lcars-cli is a symlink to the binary")
        check(s.line("Database: ").startswith(f"Database: {(d / 'lcars.db').resolve()} (existing, 0 entries)"),
              f"the start log's journal is D's (got {s.line('Database: ')!r})")
        st, saw = chat_once(port, "kirk", pw, stub_out)
        check(st == 200 and saw is not None, f"the chat ran the stand-in claude (got {st}, {saw})")
        saw = saw or {}
        check(saw.get("found") == f"{d.resolve()}/bin/lcars-cli" and saw.get("dir") == f"{d.resolve()}/bin",
              f"the chat's claude finds D/bin/lcars-cli first on its PATH (got {saw.get('found')})")
        # init's journal is empty (no seed row): stats says 0 entries
        check(saw.get("rc") == 0 and re.search(r"^entries +: 0$", saw.get("out", ""), re.M),
              f"and `lcars-cli stats` through it answers from this server (got {saw.get('rc')}, {saw.get('out', '')[:80]!r})")
        check(sorted(os.listdir(cwd)) == [], f"the working directory untouched (got {os.listdir(cwd)})")

        print("cli: lcars-one cli, the made symlink and one of the user's own, against lcars-cli")
        mine = tmp / "elsewhere" / "lcars-cli"
        mine.parent.mkdir()
        mine.symlink_to(one)
        env = config.base_env(LCARS_URL=f"http://127.0.0.1:{port}", LCARS_AUTH_USER="kirk", LCARS_AUTH_PASS=pw)
        forms = {"lcars-one cli": [one, "cli"], "D/bin/lcars-cli": [d / "bin" / "lcars-cli"],
                 "a symlink of one's own": [mine]}
        r = run([cli, "new", "--kind", "note", "--title", "from the cli", "--content", "hello"], env, cwd)
        check(r[0] == 0, f"lcars-cli new: exit 0 (got {r[0]}, {r[2].strip()!r})")
        cases = [["--help"], ["list", "--kind", "note"], ["get", "2"], ["stats"], ["kinds"], ["roles"],
                 ["--json", "roles"], ["roles", "set", "log", "Not A Slug"],
                 ["--json", "list", "--kind", "note"], ["get", "99999"], ["frobnicate"], []]
        for args in cases:
            want = run([cli, *args], env, cwd)
            for name, pre in forms.items():
                got = run([*pre, *args], env, cwd)
                check(got == want, f"{name} {' '.join(args) or '(nothing)'}: the same exit, stdout and stderr "
                                   f"as lcars-cli (exit {got[0]} vs {want[0]})")
        r = run([one, "cli", "new", "--kind", "note", "--title", "from the one binary", "--content", "x"], env, cwd)
        check(r[0] == 0, f"lcars-one cli new: exit 0 (got {r[0]})")
        r = run([cli, "list", "--kind", "note", "--json"], env, cwd)
        check("from the one binary" in r[1], "its write read back by lcars-cli")
        check(sorted(os.listdir(cwd)) == [], "the working directory still untouched")
    finally:
        s.stop()

    print("the link: kept, replaced, left alone, or not made")
    def start(extra_env=None, log="again.log"):
        s = config.Run(one, cwd, ["--data", str(d)], config.base_env(**(extra_env or {})), port, tmp / log)
        line = s.line("CLI: ")
        s.stop()
        return line
    line = start()
    check(line == f"CLI: {d.resolve()}/bin/lcars-cli -> {exe}", f"a right link kept (got {line!r})")
    (d / "bin" / "lcars-cli").unlink()
    (d / "bin" / "lcars-cli").symlink_to("/nonexistent/lcars")
    line = start(log="moved.log")
    check(os.readlink(d / "bin" / "lcars-cli") == exe and line.endswith(f"-> {exe}"),
          f"a link pointing elsewhere replaced (got {os.readlink(d / 'bin' / 'lcars-cli')})")
    check(not any(p.name.startswith(".lcars-cli.") for p in (d / "bin").iterdir()), "no temp link left behind")
    (d / "bin" / "lcars-cli").unlink()
    (d / "bin" / "lcars-cli").write_text("#!/bin/sh\necho mine\n")
    line = start(log="file.log")
    check("is a file of its own; left alone" in line and (d / "bin" / "lcars-cli").read_text() == "#!/bin/sh\necho mine\n",
          f"a real file left alone (got {line!r})")
    (d / "bin" / "lcars-cli").unlink()
    line = start({"LCARS_CLI_DIR": "/opt/cli"}, log="set.log")
    check(line == "CLI: LCARS_CLI_DIR=/opt/cli (as set)" and not (d / "bin" / "lcars-cli").exists(),
          f"LCARS_CLI_DIR set: nothing made (got {line!r})")

    print("init and version through the one binary")
    r = run([one, "version"], config.base_env(), cwd)
    check(r[0] == 0 and r[1].strip() == f"lcars {VERSION}", f"lcars-one version (got {r[1].strip()!r})")
    r = run([one, "--version"], config.base_env(), cwd)
    check(r[1].strip() == f"lcars {VERSION}", "lcars-one --version")
    before = config.digest(d)
    r = run([one, "init", d, "--port", "1"], config.base_env(), cwd)
    check(r[0] == 0 and config.digest(d) == before and "made" not in r[1],
          f"init again: exit 0, no byte changed, nothing made (got {r[0]})")
    check(sorted(os.listdir(cwd)) == [], "the working directory untouched at the end")


def release_has_no_cli(release, tmp):
    print("the lcars-release build: no CLI in it, and no bin/ made")
    d = tmp / "rel"
    d.mkdir()
    r = run([release, "cli", "stats"], config.base_env(), d)
    check(r[0] == 2 and "no CLI in it" in r[2], f"lcars cli refused (got {r[0]}, {r[2].strip()!r})")
    named = d / "lcars-cli"
    named.symlink_to(release)
    r = run([named, "stats"], config.base_env(), d)
    check(r[0] == 2 and "no CLI in it" in r[2], f"a lcars-cli name refused (got {r[0]})")
    named.unlink()
    port = api.free_port()
    s = config.Run(release, d, ["--port", str(port)], config.base_env(), port, tmp / "rel.log")
    try:
        check(s.line("CLI: ") == "", "no CLI line in its start log")
    finally:
        s.stop()
    check(not (d / "bin").exists(), "no bin/ made")


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-onebin-"))
    one = build_one(tmp)
    cli = tmp / "lcars-cli-separate"
    build_cli(cli)
    release = tmp / "lcars"
    api.build(release)
    serve_and_cli(one, cli, tmp)
    release_has_no_cli(release, tmp)
    if api.fails:
        print(f"\n{len(api.fails)} of {api.checks[0]} checks failed; scratch: {tmp}")
        sys.exit(1)
    print(f"\nall {api.checks[0]} checks passed")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
