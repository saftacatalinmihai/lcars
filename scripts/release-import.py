#!/usr/bin/env python3
"""Every deployed version as a journal entry (docs/design/release-entries.md),
so the console can show what changed.

    release-import.py [--apply] [--json]   make the entries for every version
                                           in CHANGELOG.md that has none (a dry
                                           run, listing them, without --apply)

A release entry: kind "release", title the version alone ("0.323.5"),
created_at the deploy's time, and content

    release:: 0.323.5 2026-10-24       the version and its CHANGELOG section's date

    <that section's text exactly as CHANGELOG.md holds it>

The deploy writes one per version it numbered (engineer.py, land_commits
-> write_deployed), after the merge and the push; a write that fails does
not fail the deploy, it is named in [deploy finished], and this import
catches it up. The import is idempotent: a version whose first line an
entry already has (a deleted one counted: a release the captain deleted
stays deleted) is left alone. It writes oldest first, so the ids run in
the versions' order, and created_at is the section's date at 12:00 in the
captain's zone (LCARS_TZ, the environment then ~/.env): the CHANGELOG
holds no time of day.

Written as the captain's login, through journal_api.py (report.py's).
"""

import datetime
import json
import os
import re
import sys
import urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from journal_api import api, env_file_value  # noqa: E402

KIND = "release"
CHANGELOG = os.path.join(os.path.dirname(HERE), "CHANGELOG.md")
# a numbered section's heading: "## 0.323.5 — 2026-10-24" (the dash an em
# dash, as version-stamp.py writes it; a hyphen accepted), or a backported
# one with its commit after the date: "## 0.54.0 — 2026-09-27 · `2ed4664`"
SECTION_RE = re.compile(r"^## (\d+\.\d+\.\d+) [—-] (\d{4}-\d{2}-\d{2})(?:\s.*)?$", re.M)
HEAD_RE = re.compile(r"^release:: (\d+\.\d+\.\d+)\b")
NOON = datetime.time(12, 0)


class Refused(Exception):
    pass


def sections(text):
    """[(version, date, body)] of every numbered section, top (newest) first;
    body the text between its heading and the next `## `, outer blank lines
    dropped. A placeholder (`## next patch`) or a heading of another shape
    is not a release, and ends the section above it all the same."""
    heads = list(re.finditer(r"^## .*$", text, re.M))
    out = []
    for i, h in enumerate(heads):
        m = SECTION_RE.match(h.group(0))
        if not m:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((m.group(1), m.group(2), text[h.end():end].strip("\n")))
    return out


def content(v, date, body):
    return f"release:: {v} {date}\n\n{body}"


def entry(v, date, body, created_utc):
    """The POST /entries body for version v."""
    return {"kind": KIND, "title": v, "content": content(v, date, body), "created_at_utc": created_utc}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def noon_utc(date):
    """date (YYYY-MM-DD, the captain's day) at 12:00 in LCARS_TZ, in UTC; the
    box's own zone when that is unset or unknown."""
    tzname = os.environ.get("LCARS_TZ") or env_file_value("LCARS_TZ")
    tz = None
    if tzname:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tzname)
        except Exception:  # noqa: BLE001 - an unknown zone is the box's own
            tz = None
    local = datetime.datetime.combine(datetime.date.fromisoformat(date), NOON)
    local = local.replace(tzinfo=tz) if tz else local.astimezone()
    return local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def release_entries():
    """{version: entry id} of the journal's release entries, deleted ones
    included (the lowest id for a version held twice). Read through GET
    /dump, as report.py reads its own. Refused when it cannot be read."""
    q = {"kind": KIND, "order": "id", "dir": "asc", "deleted": "all"}
    st, rows = api("GET", "/dump?" + urllib.parse.urlencode(q), timeout=30)
    if st != 200 or not isinstance(rows, list):
        raise Refused(f"the journal's release entries could not be read ({st}): " + json.dumps(rows)[:200])
    have = {}
    for e in rows:
        m = HEAD_RE.match(e.get("content") or "")
        if m and m.group(1) not in have:
            have[m.group(1)] = e.get("id")
    return have


def post(body):
    """The new entry's id, or Refused saying why."""
    st, j = api("POST", "/entries", body, timeout=30)
    eid = j.get("id") if isinstance(j, dict) else None
    if st not in (200, 201) or not eid:
        raise Refused(f"{st}: " + json.dumps(j)[:200])
    return eid


def write_deployed(changelog, versions, now=None):
    """The deploy's write: an entry for each of versions (strings, any
    order) from the CHANGELOG text, created now, oldest first. Never raises:
    [(version, id or None, error or "")]. A version the journal has already
    is answered with that entry's id, not written twice."""
    secs = {v: (d, b) for v, d, b in sections(changelog)}
    order = sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))
    try:
        have = release_entries()
    except Refused as e:
        return [(v, None, str(e)) for v in order]
    created = now or utc_now()
    out = []
    for v in order:
        if v in have:
            out.append((v, have[v], ""))
        elif v not in secs:
            out.append((v, None, "no section for it in CHANGELOG.md"))
        else:
            try:
                out.append((v, post(entry(v, *secs[v], created)), ""))
            except Refused as e:
                out.append((v, None, str(e)))
    return out


def outcome(written):
    """write_deployed's answer as the line [deploy finished] carries."""
    ok = [f"{v} #{i}" for v, i, err in written if i]
    bad = [f"{v} ({err})" for v, i, err in written if not i]
    s = ("release entries: " + ", ".join(ok)) if ok else ""
    if bad:
        s += ("; " if s else "") + ("release entries NOT written: " + "; ".join(bad)
                                    + " - release-import.py --apply catches them up")
    return s


def import_releases(changelog, apply=False):
    """The import's plan, oldest first: {"create": [...], "have": [...],
    "failed": [...]}, each {version, date, created_at_utc[, id][, why]};
    written only when apply."""
    have = release_entries()
    out = {"create": [], "have": [], "failed": []}
    for v, date, body in reversed(sections(changelog)):
        row = {"version": v, "date": date, "created_at_utc": noon_utc(date)}
        if v in have:
            out["have"].append(dict(row, id=have[v]))
            continue
        if apply:
            try:
                row["id"] = post(entry(v, date, body, row["created_at_utc"]))
            except Refused as e:
                out["failed"].append(dict(row, why=str(e)))
                continue
            have[v] = row["id"]   # a version twice in the file: written once
        out["create"].append(row)
    return out


def main(argv):
    apply, as_json = "--apply" in argv, "--json" in argv
    rest = [a for a in argv if a not in ("--apply", "--json")]
    if rest:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    with open(os.environ.get("LCARS_CHANGELOG") or CHANGELOG, encoding="utf-8") as f:
        text = f.read()
    try:
        plan = import_releases(text, apply)
    except Refused as e:
        print("release-import: " + str(e), file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(dict(plan, applied=apply)))
    else:
        verb = "made" if apply else "would make"
        for r in plan["create"]:
            print(f"{verb} {r['version']} ({r['date']} 12:00 local = {r['created_at_utc']} UTC)"
                  + (f" #{r['id']}" if r.get("id") else ""))
        for r in plan["failed"]:
            print(f"FAILED {r['version']}: {r['why']}")
        print(f"{len(plan['create'])} {verb}, {len(plan['have'])} already in the journal, "
              f"{len(plan['failed'])} failed" + ("" if apply else " (a dry run: --apply writes them)"))
    return 1 if plan["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
