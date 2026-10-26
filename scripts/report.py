#!/usr/bin/env python3
"""Hosted reports: a file handed to the captain as a link he taps.

    report.py publish FILE [--title T] [--json]   copy FILE into the media store,
                                                  print its URL
    report.py update REL FILE [--json]            write FILE over the report at REL
                                                  (media/reports/YYYY/MM/<name>, as list
                                                  gives it): same name, same URL
    report.py list [n] [--json]                   the newest n (20), newest first
    report.py import [--apply] [--json]           every report in the store made an
                                                  entry (once; a dry run without --apply)

Number One and the engineers publish reports here - HTML, PDF, PNG, CSV,
Markdown, anything - and never commit them or leave them elsewhere on the
box. A report lives in the NAS's media store, beside the attachments, at

    $LCARS_MEDIA_ROOT/media/reports/YYYY/MM/<slug>-<id>.<ext>

with a hidden sidecar .<slug>-<id>.<ext>.json holding its title, and GET
/media/<path> serves it to be read in the browser (HTML in a sandbox:
lcars_media.h, "Reports").

Each report is also a journal entry (docs/design/reports-as-entries.md), so
the console finds it like any entry, with no read of the NAS: kind
"report", the report's title, created_at its publish time, and content

    report:: <type> <rel>          html|md|txt|csv|pdf|png|zip|other, the path

    <the whole text, for html, md, txt and csv; nothing more for the rest>

An html/md/txt/csv entry with nothing after its first line is a report too
big to embed (its entry over the journal's cap, HTTP_MAX_BODY_BYTES, 512
KiB, less 4 KiB for the row): the file is published all the same, and the
console shows the entry as a link. Nothing is refused for its size but
the store's own MAX_BYTES.

written after the file is in place, as the captain's login (LCARS_AUTH_USER
and _PASS, the environment then ~/.env; the server at LCARS_URL, else
~/.env's LCARS_CREW_URL, else http://127.0.0.1:8080). An update refreshes
the entry whose first line names the report (or makes one, for a report
from before). If the entry fails after the copy, the link is printed
all the same, the failure on stderr, exit 3; `import --apply` writes it.
--json adds the entry's "id" (null, and an "error", when it failed).

`import` makes the entries for reports published before that, created_at
each sidecar's published_utc: a dry run printing what it would make unless
--apply; a report whose first line an entry already has, a deleted one
included, is left alone, so it can run any number of times.

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
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the captain's login and the API, shared with release-import.py
from journal_api import api, env_file_value, journal_login  # noqa: E402,F401



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
    """Copies path into the store, then writes its journal entry; answers
    {url, path, title, bytes, id} - id the entry's, None with an "error"
    when the file is published and the entry is not (import writes it)."""
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
    name = f"{slugify(title)}-{secrets.token_hex(4)}.{extension(path)}"
    assert NAME_RE.match(name), name
    rel = f"{rel_dir}/{name}"
    published = now.strftime("%Y-%m-%d %H:%M:%S")
    # the entry built first: a file that cannot be read fails before the copy
    entry = entry_body(rel, path, title, published)
    # below <root>/media only: that one exists, so this never creates it
    d = os.path.join(media, REPORTS, f"{now:%Y}", f"{now:%m}")
    os.makedirs(d, exist_ok=True)
    side = {"title": title, "source": os.path.basename(path),
            "published_utc": published,
            "by": os.environ.get("LCARS_REPORT_BY") or os.environ.get("USER") or ""}
    # the title first, so the report is listed with it the moment it appears
    write_atomic(os.path.join(d, "." + name + ".json"), [json.dumps(side).encode()])
    write_atomic(os.path.join(d, name), read_chunks(path))
    r = {"url": f"{base()}/{rel}", "path": rel, "title": title, "bytes": size}
    return with_entry(r, rel, entry)


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
    side = read_sidecar(dst)
    side.setdefault("title", name)
    rel = rel.strip().lstrip("/")
    # the published time, for an entry made now for a report from before
    # reports were entries (created_at is when it was first published)
    entry = entry_body(rel, path, side["title"], side.get("published_utc") or mtime_utc(dst))
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
    r = {"url": f"{base()}/{rel}", "path": rel, "title": side["title"], "bytes": size,
         "updated_utc": side["updated_utc"]}
    return with_entry(r, rel, entry)


def read_sidecar(full):
    """The report's sidecar (.<name>.json beside it) as a dict, {} if none."""
    d, name = os.path.split(full)
    try:
        with open(os.path.join(d, "." + name + ".json")) as f:
            side = json.load(f)
    except (OSError, ValueError):
        return {}
    return side if isinstance(side, dict) else {}


def mtime_utc(full):
    return datetime.datetime.fromtimestamp(os.stat(full).st_mtime,
                                           datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---- the journal entry (docs/design/reports-as-entries.md) ------------------
#
# Every report is also an entry of kind "report": its title the report's,
# created_at its publish time, and its content
#
#     report:: <type> <rel>
#
#     <the file's whole text, for html, md, txt and csv; nothing for the rest>
#
# so the console finds reports as it finds any entry, with no read of the
# NAS. The file stays where it was: every link handed out keeps working.
# Written as the captain's own login (LCARS_AUTH_USER/PASS, as lcars-cli and
# the timers write), since the reports are his.

ENTRY_KIND = "report"
TEXT_TYPES = ("html", "md", "txt", "csv")
TYPE_OF = {"html": "html", "htm": "html", "md": "md", "markdown": "md", "txt": "txt",
           "csv": "csv", "pdf": "pdf", "png": "png", "zip": "zip"}
HTTP_MAX_BODY_BYTES = 512 * 1024   # lcars_http.h: a request body over it is a 413
# The entry's whole JSON body stops 4 KiB short of the server's cap: GET
# /dump (the console's cold load) builds each row in the connection's 1MB
# arena by doubling, so a row's JSON must stay under 512 KiB, and the row
# carries ~250 bytes of fields the POST body does not. Measured on a scratch
# server: a 523,313-byte body of HTML round-trips through POST, GET, /dump
# and PATCH; 531,676 is refused.
ENTRY_BODY_MAX = HTTP_MAX_BODY_BYTES - 4096
# Control characters other than tab and newline: the server's JSON reader
# keeps a \u escape as its letters, and a NUL would end the C string.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def report_type(rel):
    ext = os.path.splitext(rel)[1][1:].lower()
    return TYPE_OF.get(ext, "other")


def entry_head(rel):
    """The entry's first line, which names its report: how it is found."""
    return f"report:: {report_type(rel)} {rel}"


def entry_body(rel, path, title, created):
    """The POST /entries body for the report at rel whose bytes are at path.
    A text report whose entry the journal could not hold gets the first line
    alone, as a binary one does: huge text stays a file, the entry is the
    link (an html/md/txt/csv entry with nothing after its first line means
    just that, and the console shows it as a link). Never refused."""
    head = entry_head(rel)
    body = {"kind": ENTRY_KIND, "title": title, "content": head, "created_at_utc": created}
    # its bytes alone over the cap: over it escaped too, so not read
    if report_type(rel) in TEXT_TYPES and os.path.getsize(path) <= ENTRY_BODY_MAX:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
        text = CONTROL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
        full = dict(body, content=head + "\n\n" + text)
        if len(json.dumps(full, ensure_ascii=False).encode()) <= ENTRY_BODY_MAX:
            return full
    return body


def embedded(body):
    """Whether the entry carries the report's text (not the link alone)."""
    return "\n" in body["content"]


def report_entries(q=None, deleted=False):
    """{first line: entry id} of the journal's report entries (the lowest id
    for a line held twice), those whose text has q if given. Read from GET
    /dump, which streams one row at a time: every report's text at once
    would not fit /entries' answer. Refused when it cannot be read."""
    query = {"kind": ENTRY_KIND, "order": "id", "dir": "asc"}
    if q:
        query["q"] = q
    if deleted:
        query["deleted"] = "all"
    st, rows = api("GET", "/dump?" + urllib.parse.urlencode(query))
    if st != 200 or not isinstance(rows, list):
        raise Refused(f"the journal's report entries could not be read ({st}): "
                      + json.dumps(rows)[:200])
    have = {}
    for e in rows:
        line = (e.get("content") or "").split("\n", 1)[0].strip()
        if line.startswith("report:: ") and line not in have:
            have[line] = e.get("id")
    return have


def with_entry(r, rel, body):
    """r, with the id of the report's entry, made or refreshed: the live one
    whose first line names rel gets the new title and text, else one is
    made. A failure is an "error" in r, not raised: the file is published
    by then, and `import --apply` writes the entry later."""
    try:
        eid = report_entries(q=rel).get(entry_head(rel))
    except Refused as e:
        return dict(r, id=None, error=f"published, but its journal entry was not written: {e}; "
                    "report.py import --apply writes it")
    if eid:
        st, j = api("PATCH", f"/entries/{eid}", {"title": body["title"], "content": body["content"]})
    else:
        st, j = api("POST", "/entries", body)
        eid = j.get("id") if isinstance(j, dict) else None
    if st not in (200, 201) or not eid:
        return dict(r, id=None, error=f"published, but its journal entry was not written ({st}): "
                    + json.dumps(j)[:200] + "; report.py import --apply writes it")
    return dict(r, id=eid)


def import_reports(apply=False):
    """Every report in the store as an entry, oldest first: those whose
    first line no entry has (deleted ones counted: a report entry the
    captain deleted stays deleted) are made, with created_at the sidecar's
    published_utc, when apply; else only listed. Answers the plan:
    {"create": [...], "have": [...], "failed": []} - a create's "link_only"
    true when a text report is too big for its text to be embedded."""
    have = report_entries(deleted=True)
    out = {"create": [], "have": [], "failed": []}
    for r in reversed(listing(None)):
        full = os.path.join(root(), *r["path"].split("/"))
        side = read_sidecar(full)
        row = {"path": r["path"], "title": r["title"],
               "published_utc": side.get("published_utc") or r["published_utc"]}
        if entry_head(r["path"]) in have:
            out["have"].append(dict(row, id=have[entry_head(r["path"])]))
            continue
        body = entry_body(r["path"], full, r["title"], row["published_utc"])
        row["link_only"] = report_type(r["path"]) in TEXT_TYPES and not embedded(body)
        if apply:
            st, j = api("POST", "/entries", body)
            if st not in (200, 201) or not isinstance(j, dict) or not j.get("id"):
                out["failed"].append(dict(row, why=f"{st}: " + json.dumps(j)[:200]))
                continue
            row["id"] = j["id"]
        out["create"].append(row)
    return out


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


def done(r, as_json):
    """Prints a published or updated report: its link (the JSON with --json),
    and a failed entry on stderr, exit 3 - the file is published all the same."""
    print(json.dumps(r) if as_json else r["url"])
    if r.get("error"):
        print("report.py: " + r["error"], file=sys.stderr)
        return 3
    return 0


def imported(plan, applied, as_json):
    if as_json:
        print(json.dumps(plan, indent=1))
    else:
        verb = "created" if applied else "would create"
        for r in plan["create"]:
            print(f"{verb}  {r['published_utc'][:16]}  {r['title']}\n    {r['path']}"
                  + ("  (too big to embed: the link alone)" if r.get("link_only") else "")
                  + (f"  (entry {r['id']})" if r.get("id") else ""))
        for r in plan["failed"]:
            print(f"FAILED  {r['published_utc'][:16]}  {r['title']}\n    {r['why']}")
        total = sum(len(v) for v in plan.values())
        links = sum(1 for r in plan["create"] if r.get("link_only"))
        print(f"{total} reports: {len(plan['create'])} {verb} ({links} as the link alone, too big "
              f"to embed), {len(plan['have'])} already entries, {len(plan['failed'])} failed"
              + ("" if applied else " (a dry run: --apply writes them)"))
    return 1 if plan["failed"] else 0


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
            return done(publish(rest[0], title), as_json)
        if a[0] == "update":
            if len(a) != 3:
                raise Refused("update REL FILE (REL: media/reports/YYYY/MM/<name>, as list gives it)")
            return done(update(a[1], a[2]), as_json)
        if a[0] == "import":
            if a[1:] not in ([], ["--apply"]):
                raise Refused("import [--apply]")
            return imported(import_reports(apply=a[1:] == ["--apply"]), a[1:] == ["--apply"], as_json)
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
