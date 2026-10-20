#!/usr/bin/env python3
"""Hosted reports: a file handed to the captain as a link he taps.

    report.py publish FILE [--title T] [--json]   copy FILE into the media store,
                                                  print its URL
    report.py update REL FILE [--json]            write FILE over the report at REL
                                                  (media/reports/YYYY/MM/<name>, as list
                                                  gives it): same name, same URL
    report.py list [n] [--json]                   the newest n (20), newest first

Number One and the engineers publish reports here - HTML, PDF, PNG, CSV,
Markdown, anything - and never commit them or leave them elsewhere on the
box. A report lives in the NAS's media store, beside the attachments, at

    $LCARS_MEDIA_ROOT/media/reports/YYYY/MM/<slug>-<id>.<ext>

with a hidden sidecar .<slug>-<id>.<ext>.json holding its title. No row is
written to the journal: the server's GET /reports lists the directories, the
web UI's Reports page shows that list, and GET /media/<path> serves each file
to be read in the browser (HTML in a sandbox: lcars_media.h, "Reports").

An update keeps the name, so the link already handed out shows the new
content: the file is replaced atomically, its sidecar keeps the title and
gains updated_utc, and the server's disk cache copy of it (which would
otherwise be served, stale, until evicted) is removed. Only a file already
in the reports store can be updated; anything else is Refused.

The copy is atomic: written to a dot-name (which /media/ never serves),
synced, then renamed into place, so a half-copied report is never on show.
A media root that is not mounted is refused: <root>/media is made by hand on
the NAS, and its absence means the share is down - writing then would fill
the VPS's own disk with files the NAS never sees (MediaCheckMounted).

    LCARS_MEDIA_ROOT     the root, as the server's (the environment, then
                         ~/.env; unset: <data dir>/media, as the server's)
    LCARS_REPORT_BASE    the journal server's URL, in front of the path (the
                         environment, then ~/.env; unset: the link is the path
                         alone, /media/reports/..., which the console opens)
    LCARS_MEDIA_CACHE    the server's disk cache, as the server reads it
                         (default ~/.cache/lcars-media; 0: none)
"""

import datetime
import json
import os
import re
import secrets
import sys



# The server's default with LCARS_MEDIA_ROOT unset, MEDIA_DEFAULT_DIR in
# lcars_media.h: this directory under the data directory.
DEFAULT_DIR = "media"
SUBDIR = "media"                       # MEDIA_SUBDIR
REPORTS = "reports"                    # MEDIA_REPORTS_DIR
MAX_BYTES = 1024 ** 3                  # MEDIA_MAX_BYTES: no bigger than an upload
SLUG_MAX = 48
# What the server's MediaIsFilePath accepts in a segment, and the listing
# shows: a name of these and not starting with a dot.
NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")


class Refused(Exception):
    pass


def root():
    """The server's media root: the environment, then ~/.env (an engineer's
    shell, or Number One's, does not source it, and the server's unit does),
    then the server's default, <data dir>/media - the data directory being
    $LCARS_DATA_DIR, else the checkout this script is in (the server's
    working directory on a box that runs from one)."""
    have = os.environ.get("LCARS_MEDIA_ROOT") or env_file_value("LCARS_MEDIA_ROOT")
    if have:
        return have
    data = os.environ.get("LCARS_DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(data, DEFAULT_DIR)


def env_file_value(key):
    """key's value in ~/.env (KEY=value lines, never sourced), or "": an
    engineer's shell, or Number One's, does not source it."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".env")) as f:
            for ln in f:
                k, eq, v = ln.strip().removeprefix("export ").partition("=")
                if eq and k.strip() == key:
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


def base():
    """The server's URL, with no host of ours compiled in: "" when unset, and
    the link is then "/media/reports/...", which resolves on the server."""
    return (os.environ.get("LCARS_REPORT_BASE") or env_file_value("LCARS_REPORT_BASE")).rstrip("/")


def mounted_media():
    """<root>/media, or Refused when it is not there (the NAS is not mounted)."""
    media = os.path.join(root(), SUBDIR)
    if not os.path.isdir(media):
        raise Refused(f"{media} is missing - is the NAS mounted? Nothing was written.")
    return media


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:SLUG_MAX].rstrip("-") or "report"


def extension(path):
    """The file's extension, lowercased, if it is a plain one; else bin (the
    server then serves it as a download, application/octet-stream)."""
    ext = os.path.splitext(path)[1][1:].lower()
    return ext if re.fullmatch(r"[a-z0-9]{1,15}", ext) else "bin"


def write_atomic(dst, chunks):
    """Writes the chunks to a dot-name beside dst, syncs, renames into place."""
    d, name = os.path.split(dst)
    part = os.path.join(d, "." + name + ".part")
    try:
        with open(part, "wb") as f:
            for c in chunks:
                f.write(c)
            f.flush()
            os.fsync(f.fileno())  # NFS reports a refused write here or at close
        os.chmod(part, 0o644)
        os.rename(part, dst)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise


def read_chunks(path, size=1 << 20):
    with open(path, "rb") as f:
        while True:
            b = f.read(size)
            if not b:
                return
            yield b


def publish(path, title=None, now=None):
    """Copies path into the store; answers {url, path, title, bytes}."""
    if not os.path.isfile(path):
        raise Refused(f"{path} is not a file")
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise Refused(f"{path} is {size} bytes; reports stop at {MAX_BYTES}")
    title = (title or "").strip() or os.path.splitext(os.path.basename(path))[0]
    title = " ".join(title.split())[:200]
    media = mounted_media()
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rel_dir = f"{SUBDIR}/{REPORTS}/{now:%Y}/{now:%m}"
    # below <root>/media only: that one exists, so this never creates it
    d = os.path.join(media, REPORTS, f"{now:%Y}", f"{now:%m}")
    os.makedirs(d, exist_ok=True)
    name = f"{slugify(title)}-{secrets.token_hex(4)}.{extension(path)}"
    assert NAME_RE.match(name), name
    side = {"title": title, "source": os.path.basename(path),
            "published_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
            "by": os.environ.get("LCARS_REPORT_BY") or os.environ.get("USER") or ""}
    # the title first, so the report is listed with it the moment it appears
    write_atomic(os.path.join(d, "." + name + ".json"), [json.dumps(side).encode()])
    write_atomic(os.path.join(d, name), read_chunks(path))
    rel = f"{rel_dir}/{name}"
    return {"url": f"{base()}/{rel}", "path": rel, "title": title, "bytes": size}


def cache_dir():
    """The server's disk cache of the media store, as MediaCacheDir resolves
    it, or None when caching is off."""
    d = os.environ.get("LCARS_MEDIA_CACHE")
    if d == "0":
        return None
    if d:
        return d
    home = os.environ.get("HOME")
    return os.path.join(home, ".cache", "lcars-media") if home else None


def stored(rel):
    """The full path of the report at rel (media/reports/YYYY/MM/<name>), or
    Refused. The shape is checked first, then that the real path is a
    regular file inside the reports directory: a symlink or a .. never
    reaches outside it."""
    rel = (rel or "").strip().lstrip("/")
    parts = rel.split("/")
    if (len(parts) != 5 or parts[0] != SUBDIR or parts[1] != REPORTS
            or not re.fullmatch(r"\d{4}", parts[2]) or not re.fullmatch(r"\d{2}", parts[3])
            or not NAME_RE.match(parts[4]) or parts[4].endswith(".part")):
        raise Refused(f"{rel or '(empty)'} is not a report path: media/reports/YYYY/MM/<name>, as list gives it")
    top = os.path.realpath(os.path.join(mounted_media(), REPORTS))
    full = os.path.join(root(), *parts)
    if os.path.islink(full) or not os.path.isfile(full):
        raise Refused(f"no report at {rel}")
    if os.path.commonpath([top, os.path.realpath(full)]) != top:
        raise Refused(f"{rel} is outside the reports store")
    return full


def update(rel, path, now=None):
    """Writes path over the report at rel, keeping its name, so its URL; the
    sidecar keeps its title and gains updated_utc. Answers {url, path,
    title, bytes, updated_utc}."""
    dst = stored(rel)
    if not os.path.isfile(path):
        raise Refused(f"{path} is not a file")
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise Refused(f"{path} is {size} bytes; reports stop at {MAX_BYTES}")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    d, name = os.path.split(dst)
    sidecar = os.path.join(d, "." + name + ".json")
    side = {}
    try:
        with open(sidecar) as f:
            side = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(side, dict):
        side = {}
    side.setdefault("title", name)
    side["updated_utc"] = now.strftime("%Y-%m-%d %H:%M:%S")
    write_atomic(dst, read_chunks(path))
    write_atomic(sidecar, [json.dumps(side).encode()])
    # The server serves its cached copy before the NAS's, with no check that
    # the NAS's changed, so the stale copy goes; the next read refills it.
    # (A fill already running when the file was replaced may still land the
    # old bytes: it read the old file. Rare, and a second update clears it.)
    cd = cache_dir()
    if cd:
        try:
            os.unlink(os.path.join(cd, *rel.strip().lstrip("/").split("/")))
        except OSError:
            pass
    rel = rel.strip().lstrip("/")
    return {"url": f"{base()}/{rel}", "path": rel, "title": side["title"], "bytes": size,
            "updated_utc": side["updated_utc"]}


def listing(n=20):
    """The newest n reports, as GET /reports answers them, plus each url."""
    top = os.path.join(mounted_media(), REPORTS)
    rows = []
    for y in (sorted(os.listdir(top)) if os.path.isdir(top) else []):
        if not re.fullmatch(r"\d{4}", y):
            continue
        for m in sorted(os.listdir(os.path.join(top, y))):
            md = os.path.join(top, y, m)
            if not re.fullmatch(r"\d{2}", m) or not os.path.isdir(md):
                continue
            for name in os.listdir(md):
                full = os.path.join(md, name)
                if not NAME_RE.match(name) or os.path.islink(full) or not os.path.isfile(full):
                    continue
                st = os.stat(full)
                title = name
                try:
                    with open(os.path.join(md, "." + name + ".json")) as f:
                        title = json.load(f).get("title") or name
                except (OSError, ValueError, AttributeError):
                    pass
                rel = f"{SUBDIR}/{REPORTS}/{y}/{m}/{name}"
                rows.append({"path": rel, "title": title, "type": os.path.splitext(name)[1][1:],
                             "bytes": st.st_size, "mtime": st.st_mtime,
                             "url": f"{base()}/{rel}"})
    rows.sort(key=lambda r: (-r["mtime"], r["path"]))
    for r in rows:
        r["published_utc"] = datetime.datetime.fromtimestamp(
            r.pop("mtime"), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return rows[:n]


def main(a):
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        if a[0] == "publish":
            rest, title = a[1:], None
            if "--title" in rest:
                i = rest.index("--title")
                if i + 1 >= len(rest):
                    raise Refused("--title wants a title")
                title = rest[i + 1]
                rest = rest[:i] + rest[i + 2:]
            if len(rest) != 1:
                raise Refused("publish FILE [--title T]")
            r = publish(rest[0], title)
            print(json.dumps(r) if as_json else r["url"])
            return 0
        if a[0] == "update":
            if len(a) != 3:
                raise Refused("update REL FILE (REL: media/reports/YYYY/MM/<name>, as list gives it)")
            r = update(a[1], a[2])
            print(json.dumps(r) if as_json else r["url"])
            return 0
        if a[0] == "list":
            n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 20
            rows = listing(n)
            if as_json:
                print(json.dumps(rows, indent=1))
            else:
                for r in rows:
                    print(f"{r['published_utc'][:16]}  {r['type']:<5} {r['title']}\n    {r['url']}")
                if not rows:
                    print("no reports yet")
            return 0
        raise Refused(f"unknown command {a[0]} (no arguments for the usage)")
    except Refused as e:
        print(json.dumps({"error": str(e)}) if as_json else "report.py: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
