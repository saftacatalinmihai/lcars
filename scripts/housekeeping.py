#!/usr/bin/env python3
"""The box's housekeeping: what holds memory, swap, /tmp and the disk, and
the known, old scratch deleted (crew/housekeeping.md, four times a day).

    housekeeping.py [--dry-run] [--json]

Run by the crew runner as the `housekeeping` role (crew.py run_housekeeping),
which posts the journal entry and the notice for Number One; run by hand it
prints the same report and writes nothing to the journal. --dry-run deletes
nothing and says what it would have; --json prints the whole record.

Why: /tmp is a tmpfs on the VPS (RAM, then swap), and what a killed run or a
tool leaves there stays until someone looks - 1.66GB of Remotion bundles had
filled the 1GB swap by 2026-10-22. engineer.py's reap (every five minutes)
already deletes the scratch it knows; this pass measures the rest, deletes a
few more kinds that are known and old, and names what nobody knows.

What it may delete, and nothing else:
- what engineer.py's reap knows: killed test runs' scratch (reap_test_tmp),
  by its own rules, asked with dry=True and each removed here, through the
  guard below; and Claude sessions' scratch, ended or an idle engineer's,
  which reap_scratch takes itself (the regenerable deleted, the rest moved
  to the owner's research folder: docs/design/job-queue.md, "As built:
  the scratchpads");
- deploy logs older than DEPLOY_LOG_KEEP_DAYS and job logs older than the
  job line's JOB_KEEP_DAYS (engineer.py's state dir);
- Playwright browser builds no installed Playwright names (its .links), and
  never the newest of each browser, untouched for PLAYWRIGHT_KEEP_DAYS;
- npx's cache of a package untouched for NPX_KEEP_DAYS;
- crash dumps (core, core.<pid>, *.dmp) of ours older than a day.

The guard (`refusal`), on every one of them: never a path inside or above
the captain's data (`paths()["protected"]`: any journal file,
~/lcars-personal.db, the media root ($LCARS_MEDIA_ROOT) and everything under
/mnt and /media, the Logseq graph, the landing's and the blog's media), the production checkout or a worktree (anything under a .git'd
directory), never one a process of ours has open, runs from or sits in,
never a tree with a database file in it (*.db, its -wal, -shm, .gz: reap
takes a test's scratch journal, by its own rule), never a symlink or what
another user owns: nothing here needs root. Swap cannot be emptied without
root (swapoff): the report names the cgroups that hold it instead.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

HOME = os.path.expanduser("~")
TMP = "/tmp"
PROC = "/proc"
MB = 1 << 20
DAY = 86400
DEPLOY_LOG_KEEP_DAYS = 30
PLAYWRIGHT_KEEP_DAYS = 7
NPX_KEEP_DAYS = 30
CORE_KEEP_DAYS = 1
# Past these, the run raises a notice to Number One (the order of
# 2026-10-22): memory at rest, swap, either disk, and /tmp's unknown files.
MEM_LOW_MB = 2048
SWAP_HIGH_PCT = 60
DISK_HIGH_PCT = 80
TMP_UNKNOWN_HIGH_MB = 1024
DB_RE = re.compile(r".*\.db(-wal|-shm|-journal|\.gz|\.prev.*)?$")
CORE_RE = re.compile(r"core(\.\d+)?|.*\.dmp")


def paths():
    """Where things are; a function so a test's HOME and TMP take effect."""
    env = read_env(os.path.join(HOME, ".env"))
    media = os.environ.get("LCARS_MEDIA_ROOT") or env.get("LCARS_MEDIA_ROOT") or ""
    return {
        "cache": os.path.join(HOME, ".cache"),
        "playwright": os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(HOME, ".cache", "ms-playwright"),
        "npm": os.path.join(HOME, ".npm"),
        "npx": os.path.join(HOME, ".npm", "_npx"),
        "eng_logs": os.path.join(os.environ.get("LCARS_ENG_STATE") or os.path.join(HOME, ".local/state/lcars-eng"),
                                 "logs"),
        "worktrees": os.path.join(HOME, "lcars-eng"),
        "protected": [p for p in (
            os.path.join(HOME, "lcars"), os.path.join(HOME, "lcars-eng"), os.path.join(HOME, "lcars-public"),
            os.path.join(HOME, "lcars-personal.db"), os.path.join(HOME, "Documents", "LogSeqCloud2"),
            os.path.join(HOME, "lcars-landing-media"), os.path.join(HOME, "blog-media"),
            # every mount a NAS or a disk may be on, whatever the media
            # root is called: the box's own names are not this file's
            "/mnt", "/media", media) if p],
    }


def read_env(path):
    env = {}
    try:
        with open(path) as f:
            for ln in f:
                m = re.match(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)", ln)
                if m:
                    env[m[1]] = m[2].strip().strip("'\"")
    except OSError:
        pass
    return env


# ---- the guard ----------------------------------------------------------------

def in_use():
    """Every path a process of ours holds: its cwd, its binary, its root and
    its open files. Others' processes are not readable, and not ours to mind:
    we cannot delete their files either."""
    held, me = set(), os.getuid()
    try:
        pids = [d for d in os.listdir(PROC) if d.isdigit()]
    except OSError:
        return held
    for pid in pids:
        d = os.path.join(PROC, pid)
        try:
            if os.stat(d).st_uid != me:
                continue
            links = [os.path.join(d, x) for x in ("cwd", "exe", "root")]
            links += [os.path.join(d, "fd", f) for f in os.listdir(os.path.join(d, "fd"))]
        except OSError:
            continue
        for ln in links:
            try:
                t = os.readlink(ln)
            except OSError:
                continue
            if t.startswith("/"):
                held.add(t.removesuffix(" (deleted)"))
    return held


def within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def git_tree(path):
    """Whether path lies in a git checkout (a .git file or directory above it)."""
    d = os.path.dirname(path)
    while d and d != "/":
        if os.path.lexists(os.path.join(d, ".git")):
            return True
        d = os.path.dirname(d)
    return False


def refusal(path, held, protected):
    """Why `path` must not be deleted, or "" when it may."""
    if not os.path.isabs(path):
        return "not an absolute path"
    real = os.path.realpath(path)
    try:
        st = os.lstat(path)
    except OSError:
        return "gone"
    if os.path.islink(path):
        return "a symlink"
    if st.st_uid != os.getuid():
        return "not ours"
    for root in protected:
        r = os.path.realpath(root)
        if within(real, r) or within(r, real) or within(path, root) or within(root, path):
            return f"the captain's or production's ({root})"
    if real in (HOME, "/", TMP) or within(HOME, real):
        return "a home or system directory"
    if git_tree(real) or os.path.lexists(os.path.join(real, ".git")):
        return "in a git checkout"
    if any(within(h, real) for h in held):
        return "in use by a running process"
    if os.path.isdir(real):
        for top, dirs, files in os.walk(real):
            for n in files + dirs:
                if DB_RE.fullmatch(n):
                    return "holds a database file"
                if n == ".git":
                    return "holds a git checkout"
    elif DB_RE.fullmatch(os.path.basename(real)):
        return "a database file"
    return ""


def size_of(path):
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_blocks * 512
    n = 0
    for top, dirs, files in os.walk(path):
        for f in files + dirs:
            try:
                n += os.lstat(os.path.join(top, f)).st_blocks * 512
            except OSError:
                pass
    return n


def newest(path):
    t = os.lstat(path).st_mtime
    if os.path.isdir(path) and not os.path.islink(path):
        for top, dirs, files in os.walk(path):
            for n in dirs + files:
                try:
                    t = max(t, os.lstat(os.path.join(top, n)).st_mtime)
                except OSError:
                    pass
    return t


# ---- the candidates -------------------------------------------------------------

def reap_known():
    """[(path, why)]: the killed test runs' scratch engineer.py's reap would
    delete now, asked dry. Sessions' scratch is reap_scratch's own (sweep)."""
    import engineer as E
    out = []
    gone, _ = E.reap_test_tmp(dry=True)
    out += [(g, "a killed test run's scratch") for g in gone]
    return out


def old_logs(p, now):
    import engineer as E
    out = []
    try:
        names = sorted(os.listdir(p["eng_logs"]))
    except OSError:
        return out
    for n in names:
        f = os.path.join(p["eng_logs"], n)
        keep = DEPLOY_LOG_KEEP_DAYS if re.fullmatch(r"deploy-\d{8}-\d{6}\.log", n) else \
            E.JOB_KEEP_DAYS if re.fullmatch(r"job-.+\.log", n) else None
        try:
            if keep is not None and os.path.isfile(f) and now - os.lstat(f).st_mtime > keep * DAY:
                out.append((f, f"a {n.split('-')[0]} log past {keep} days"))
        except OSError:
            pass
    return out


def playwright_needed(root):
    """{"chromium-1243", ...}: the builds every installed Playwright names.
    Each install leaves a file in .links holding its package's path, whose
    browsers.json lists its revisions (Playwright's own cleanup reads the
    same). None when one cannot be read: then nothing is judged stale."""
    need = set()
    links = os.path.join(root, ".links")
    try:
        names = os.listdir(links)
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(links, n)) as f:
                pkg = f.read().strip()
        except OSError:
            return None
        if not os.path.isdir(pkg):
            continue   # an uninstalled package's link: it needs nothing
        try:
            with open(os.path.join(pkg, "browsers.json")) as f:
                bj = json.load(f)
        except (OSError, ValueError):
            return None
        for b in bj.get("browsers") or []:
            if b.get("name") and b.get("revision"):
                need.add(f"{b['name'].replace('-', '_')}-{b['revision']}")
    return need


def stale_playwright(p, now):
    root = p["playwright"]
    need = playwright_needed(root)
    if need is None:
        return []
    builds = {}
    for n in os.listdir(root) if os.path.isdir(root) else []:
        m = re.fullmatch(r"([a-z_]+)-(\d+)", n)
        if m:
            builds.setdefault(m[1], []).append((int(m[2]), n))
    out = []
    for name, revs in builds.items():
        revs.sort()
        for _, n in revs[:-1]:   # the newest of each browser always stays
            d = os.path.join(root, n)
            if n not in need and now - newest(d) > PLAYWRIGHT_KEEP_DAYS * DAY:
                out.append((d, "a Playwright build no installed Playwright names"))
    return out


def old_npx(p, now):
    out = []
    root = p["npx"]
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        d = os.path.join(root, n)
        try:
            if os.path.isdir(d) and now - newest(d) > NPX_KEEP_DAYS * DAY:
                out.append((d, f"npx's cache of a package unused for {NPX_KEEP_DAYS} days"))
        except OSError:
            pass
    return out


def crash_dumps(p, now):
    out = []
    for root in (HOME, TMP, os.path.join(HOME, ".config", "chromium", "Crash Reports", "completed")):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            f = os.path.join(root, n)
            try:
                if CORE_RE.fullmatch(n) and os.path.isfile(f) and now - os.lstat(f).st_mtime > CORE_KEEP_DAYS * DAY:
                    out.append((f, "a crash dump"))
            except OSError:
                pass
    return out


def sweep(dry, now=None):
    """Every candidate judged by the guard, and deleted unless dry:
    {"freed": [(path, bytes, why)], "kept": [(path, refusal)], "bytes": n}."""
    now = now or time.time()
    p = paths()
    held = in_use()
    cands = []
    for f in (lambda: reap_known(), lambda: old_logs(p, now), lambda: stale_playwright(p, now),
              lambda: old_npx(p, now), lambda: crash_dumps(p, now)):
        try:
            cands += f()
        except OSError:
            pass
    freed, kept, seen = [], [], set()
    moved = scratch(dry, now, freed)
    for path, why in cands:
        if path in seen:
            continue
        seen.add(path)
        no = refusal(path, held, p["protected"])
        if no:
            kept.append((path, no))
            continue
        size = size_of(path)
        if not dry:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError as e:
                kept.append((path, f"failed: {e.strerror}"))
                continue
        freed.append((path, size, why))
    return {"freed": freed, "kept": kept, "bytes": sum(s for _, s, _ in freed), "moved": moved}


def scratch(dry, now, freed):
    """Claude sessions' scratch, taken by engineer.py's reap_scratch itself
    rather than deleted here: it splits a session's files (the regenerable
    deleted, the rest moved to the owner's research folder), which the
    guard's whole-tree delete cannot, and its own rules keep what a
    process, a job or an engineer's turn still needs. Each taken directory
    goes on `freed`; returns [(from, to, bytes)] for the files moved."""
    import engineer as E
    moved, why, sizes = [], {}, {}
    try:
        gone, _ = E.reap_scratch(now, dry=dry, moved=moved, why=why, sizes=sizes)
    except OSError:
        return []
    for g in gone:
        n = sum(1 for m in moved if m[0].startswith(os.path.join(E.CLAUDE_TMP, g) + os.sep))
        freed.append((os.path.join(E.CLAUDE_TMP, g), sizes.get(g, 0),
                      "Claude Code's old edit diffs" if g.startswith(E.BASH_DIFF + "/")
                      else why.get(g, "taken").replace("taken: ", "a Claude session's scratch, ")
                      + (f"; {n} files moved to research" if n else "")))
    return moved


# ---- the measurements -------------------------------------------------------------

def meminfo():
    m = {}
    try:
        with open(os.path.join(PROC, "meminfo")) as f:
            for ln in f:
                k, v = ln.split(":", 1)
                m[k] = int(v.split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        return {}
    swap = m.get("SwapTotal", 0) - m.get("SwapFree", 0)
    return {"total_mb": m.get("MemTotal", 0), "available_mb": m.get("MemAvailable", 0),
            "swap_total_mb": m.get("SwapTotal", 0), "swap_used_mb": swap,
            "swap_pct": swap * 100 // m["SwapTotal"] if m.get("SwapTotal") else 0,
            "shmem_mb": m.get("Shmem", 0)}


def swap_holders(top=8):
    """Swap by cgroup and by process, from every /proc/<pid>/status's VmSwap
    (world-readable): what holds the swap, since only root can empty it."""
    groups, procs = {}, []
    try:
        pids = [d for d in os.listdir(PROC) if d.isdigit()]
    except OSError:
        return {"cgroups": [], "processes": [], "process_mb": 0}
    for pid in pids:
        try:
            with open(os.path.join(PROC, pid, "status")) as f:
                st = dict(ln.split(":", 1) for ln in f if ":" in ln)
            kb = int(st.get("VmSwap", "0 kB").split()[0])
            if not kb:
                continue
            with open(os.path.join(PROC, pid, "cgroup")) as f:
                cg = f.read().strip().splitlines()[-1].split(":", 2)[-1]
        except (OSError, ValueError, IndexError):
            continue
        groups[cg] = groups.get(cg, 0) + kb
        procs.append((kb, int(pid), st.get("Name", "?").strip()))
    procs.sort(reverse=True)
    return {"cgroups": [(g.rstrip("/").rsplit("/", 1)[-1] or "/", kb // 1024)
                        for g, kb in sorted(groups.items(), key=lambda x: -x[1])[:top]],
            "processes": [(name, pid, kb // 1024) for kb, pid, name in procs[:top]],
            "process_mb": sum(kb for kb, _, _ in procs) // 1024}


def disk(path):
    try:
        s = os.statvfs(path)
    except OSError:
        return None
    total, avail = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
    used = total - s.f_bfree * s.f_frsize
    return {"path": path, "total_mb": total // MB, "used_mb": used // MB, "free_mb": avail // MB,
            # as df counts it: used of what a user may fill
            "pct": used * 100 // max(used + avail, 1), "dev": os.stat(path).st_dev}


def tmp_entries(known):
    """/tmp's top entries, each known (reap's rules, Claude Code's own
    scratch, a test's or Remotion's by name) or unknown."""
    import engineer as E
    known = {os.path.realpath(k) for k in known}
    out = []
    try:
        names = os.listdir(TMP)
    except OSError:
        return out
    for n in names:
        f = os.path.join(TMP, n)
        size = size_of(f)
        if os.path.realpath(f) in known or E.TEST_TMP_RE.fullmatch(n) or E.REMOTION_TMP_RE.fullmatch(n):
            kind = "test scratch (reap's)"
        elif n == f"claude-{os.getuid()}":
            kind = "Claude Code's scratch (reap's, by session)"
        else:
            kind = "unknown"
        out.append({"path": f, "mb": round(size / MB, 1), "kind": kind})
    out.sort(key=lambda e: -e["mb"])
    return out


def du(paths_, timeout=300):
    """{path: bytes} by du -xs, one filesystem each, at idle I/O."""
    paths_ = [x for x in paths_ if os.path.lexists(x)]
    if not paths_:
        return {}
    try:
        r = subprocess.run(["ionice", "-c3", "nice", "-n19", "du", "-xs", "--block-size=1", "--", *paths_],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for ln in r.stdout.splitlines():
        b, _, path = ln.partition("\t")
        if b.isdigit():
            out[path] = int(b)
    return out


def journald():
    out = {}
    for who, argv in (("system", ["journalctl", "--disk-usage"]), ("user", ["journalctl", "--user", "--disk-usage"])):
        try:
            r = subprocess.run(argv + ["-q"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"take up ([\d.]+)([KMGT])", r.stdout)
        if m:
            out[who] = round(float(m[1]) * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1 << 20}[m[2]])
    if len(out) == 2 and out["system"] == out["user"]:
        # outside adm, both see the same files: one number, not two
        out = {"all": out["system"]}
    return out


def worktree_outputs(p):
    """{worktree: MB} of what git ignores in each (builds, test bundles):
    measured, never deleted - an engineer's checkout is theirs."""
    out = {}
    root = p["worktrees"]
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        wt = os.path.join(root, n)
        try:
            r = subprocess.run(["git", "-C", wt, "ls-files", "-z", "-o", "-i", "--exclude-standard", "--directory"],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode:
            continue
        names = [x for x in r.stdout.decode(errors="replace").split("\0") if x]
        out[n] = round(sum(size_of(os.path.join(wt, x.rstrip("/"))) for x in names) / MB, 1)
    return out


def measure(p, known):
    m = {"mem": meminfo(), "swap": swap_holders(), "load": os.getloadavg(), "cpus": os.cpu_count() or 1}
    m["disks"] = []
    for d in ("/", HOME):
        x = disk(d)
        if x and all(x["dev"] != y["dev"] for y in m["disks"]):
            m["disks"].append(x)
    t = disk(TMP) or {}
    m["tmp"] = {"used_mb": t.get("used_mb", 0), "total_mb": t.get("total_mb", 0), "entries": tmp_entries(known)}
    m["tmp"]["unknown_mb"] = round(sum(e["mb"] for e in m["tmp"]["entries"] if e["kind"] == "unknown"), 1)
    try:
        home = [os.path.join(HOME, n) for n in os.listdir(HOME)]
    except OSError:
        home = []
    sizes = du(home)
    m["home"] = sorted(((k, v // MB) for k, v in sizes.items()), key=lambda x: -x[1])[:10]
    # one du each: du counts a directory once per run, so a cache inside
    # ~/.cache, asked with it, would come back empty
    m["caches"] = {}
    for k in ("cache", "playwright", "npm", "npx", "pip"):
        path = p[k] if k in p else os.path.join(p["cache"], k)
        m["caches"][k] = (sizes.get(path) if path in sizes else du([path]).get(path, 0)) // MB
    m["journald"] = journald()
    m["worktrees"] = worktree_outputs(p)
    logs = []
    try:
        logs = [os.path.join(p["eng_logs"], n) for n in os.listdir(p["eng_logs"])]
    except OSError:
        pass
    m["logs"] = {"count": len(logs), "mb": round(sum(size_of(x) for x in logs) / MB, 1)}
    return m


def alarms(m):
    """The thresholds crossed: [str], for Number One's notice."""
    out = []
    mem = m["mem"]
    # memory "at rest": with the cores busy (a test run, a build) a low
    # reading is the work's, not a leak, and is only reported
    at_rest = m["load"][0] < m["cpus"] / 2
    if mem and mem["available_mb"] < MEM_LOW_MB and at_rest:
        out.append(f"memory at rest {mem['available_mb']}MB available, under {MEM_LOW_MB}MB")
    if mem and mem["swap_pct"] > SWAP_HIGH_PCT:
        who = ", ".join(f"{g} {mb}MB" for g, mb in m["swap"]["cgroups"][:3])
        rest = mem["swap_used_mb"] - m["swap"]["process_mb"]
        out.append(f"swap {mem['swap_pct']}% used ({mem['swap_used_mb']}MB): {who}"
                   + (f", tmpfs and shared memory {rest}MB" if rest > 0 else ""))
    for d in m["disks"]:
        if d["pct"] > DISK_HIGH_PCT:
            out.append(f"disk {d['path']} {d['pct']}% full, {d['free_mb'] // 1024}GB free")
    if m["tmp"]["unknown_mb"] > TMP_UNKNOWN_HIGH_MB:
        big = [e for e in m["tmp"]["entries"] if e["kind"] == "unknown"][:5]
        out.append(f"/tmp holds {m['tmp']['unknown_mb'] / 1024:.1f}GB of unknown files, not deleted: "
                   + ", ".join(f"{e['path']} {e['mb']:.0f}MB" for e in big))
    return out


def run(dry):
    """One pass: the sweep first, so the numbers are what is left."""
    s = sweep(dry)
    p = paths()
    m = measure(p, [x for x, _, _ in s["freed"]] if dry else [])
    return {"dry": dry, "sweep": s, "m": m, "alarms": alarms(m)}


def report(r):
    """The journal entry's body, Markdown, short enough for a phone."""
    m, s = r["m"], r["sweep"]
    mem = m["mem"]
    verb = "Would free" if r["dry"] else "Freed"
    lines = [f"**{verb} {s['bytes'] / MB:.0f}MB** in {len(s['freed'])} item{'s' if len(s['freed']) != 1 else ''}."
             if s["freed"] else "Nothing old enough to delete.", ""]
    if r["alarms"]:
        lines += ["**Past a threshold:**"] + [f"- {a}" for a in r["alarms"]] + [""]
    if mem:
        lines.append(f"- memory {mem['available_mb']}MB available of {mem['total_mb']}MB "
                     f"(load {m['load'][0]:.2f} on {m['cpus']})")
        lines.append(f"- swap {mem['swap_used_mb']}MB of {mem['swap_total_mb']}MB ({mem['swap_pct']}%)"
                     + (": " + ", ".join(f"{g} {mb}MB" for g, mb in m["swap"]["cgroups"][:4]) if m["swap"]["cgroups"] else ""))
        rest = mem["swap_used_mb"] - m["swap"]["process_mb"]
        if rest > 0:
            # a process's VmSwap counts only its private pages: the rest is
            # shared memory and tmpfs (/tmp), which only freeing them empties
            lines.append(f"  - {rest}MB of it no process holds: tmpfs (/tmp) and shared memory")
    t = m["tmp"]
    lines.append(f"- /tmp {t['used_mb']}MB of {t['total_mb']}MB, unknown {t['unknown_mb']:.0f}MB")
    for e in t["entries"][:5]:
        lines.append(f"  - {e['path']} {e['mb']:.0f}MB, {e['kind']}")
    for d in m["disks"]:
        lines.append(f"- disk {d['path']} {d['pct']}% used, {d['free_mb'] // 1024}GB free")
    lines.append("- home: " + ", ".join(f"{os.path.basename(k)} {v}MB" for k, v in m["home"][:6]))
    c = m["caches"]
    lines.append(f"- caches: ~/.cache {c['cache']}MB, Playwright {c['playwright']}MB, npm {c['npm']}MB "
                 f"(npx {c['npx']}MB), pip {c['pip']}MB")
    if m["journald"]:
        lines.append("- journald: " + ", ".join(f"{k} {v}MB" for k, v in m["journald"].items()))
    if m["worktrees"]:
        big = sorted(m["worktrees"].items(), key=lambda x: -x[1])
        lines.append(f"- worktrees' build outputs {sum(m['worktrees'].values()):.0f}MB (kept): "
                     + ", ".join(f"{k} {v:.0f}MB" for k, v in big[:4]))
    lines.append(f"- engineer logs {m['logs']['count']} files, {m['logs']['mb']:.0f}MB")
    if s["freed"]:
        lines += ["", f"**{'Would delete or move' if r['dry'] else 'Deleted or moved'}:**"]
        lines += [f"- {path} {size / MB:.1f}MB, {why}" for path, size, why in s["freed"][:15]]
        if len(s["freed"]) > 15:
            lines.append(f"- and {len(s['freed']) - 15} more")
    if s.get("moved"):
        to = sorted({os.path.basename(m[1].split("/scratch-")[0]) for m in s["moved"]})
        lines += ["", f"**{'Would move' if r['dry'] else 'Moved'} {len(s['moved'])} files** "
                  f"({sum(m[2] for m in s['moved']) / MB:.1f}MB) of sessions' scratch, not regenerable, to "
                  + "research/{" + ",".join(to) + "}/scratch-<date>/"]
    if s["kept"]:
        lines += ["", "**Kept (the guard):**"] + [f"- {path}: {why}" for path, why in s["kept"][:10]]
    return "\n".join(lines)


def title(r):
    mb = r["sweep"]["bytes"] / MB
    head = "Housekeeping" + (" · dry run" if r["dry"] else "")
    return head + (f": {'would free' if r['dry'] else 'freed'} {mb:.0f}MB" if r["sweep"]["freed"] else "") \
        + (" · attention" if r["alarms"] else "")


def main(a):
    if a and a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    bad = set(a) - {"--dry-run", "--json"}
    if bad:
        print(f"housekeeping.py: unknown {' '.join(sorted(bad))} (--help)", file=sys.stderr)
        return 2
    r = run("--dry-run" in a)
    if "--json" in a:
        print(json.dumps(dict(r, title=title(r)), indent=1, default=str))
    else:
        print(f"# {title(r)}\n\n{report(r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
