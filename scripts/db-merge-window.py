#!/usr/bin/env python3
"""Copies into the live journal what was written to the personal copy while
the copy was live: the rows a db-swap left behind.

    scripts/db-merge-window.py                    # dry run: the plan, nothing written
    scripts/db-merge-window.py --report           # the same, published as Markdown (report.py)
    scripts/db-merge-window.py --apply            # do the writes
    scripts/db-merge-window.py --since '2026-10-16 11:32:23' --until '2026-10-16 12:04:52' [--copy PATH]

Why it is needed: db-swap.sh exchanges ~/lcars/lcars.db (the full journal)
and ~/lcars-personal.db (db-filter.sh's copy) by renames, so from the first
swap the two files diverge - whatever the server, the crew and Number One
wrote while the copy was live is in the copy only (ARCHITECTURE.md,
Deployment & ops). Its ids mean nothing in the full journal: the full one
went on handing out the same ids after the swap back.

How it reads and writes, and why so:
- The copy is opened read-only (sqlite URI mode=ro), never written. It is
  the captain's personal data, so nothing of a row beyond its id, kind,
  title and stamps is printed or put in the report.
- The live journal is never opened: everything about it is asked of the
  server, and every write goes through the API as the captain's login
  (LCARS_AUTH_USER/PASS, from the environment or ~/.env as lcars-cli has
  them). The server's own rules then hold - the stamps normalised, the
  page's mirrors hearing of it through /events - and the file is never
  raced.
- Refuses (exit 75) when the state file says the copy is the live journal:
  then the API would be writing into the very file being read.

The window. Default: from the state file's (~/.local/state/lcars/
db-swap.json) filtered_at to its swapped_at. db-swap.sh fresh filters and
swaps the new copy in straight after, so nothing was written to the copy
before filtered_at, and swapped_at is the last swap, the one back. When
that does not hold (a plain swap of an older copy, or the copy still live),
give --since and --until; each takes UTC "YYYY-MM-DD HH:MM:SS".

Every copy row created or last modified in the window is one of:
- SKIPPED: crew_inbox and crew_seat (the seat's machinery, stale by now)
  and task_no1 (Number One raised its questions again): listed, not copied.
- NEW: created in the window, and no live row of the same kind with the
  same created_at_utc and the same title (or, the yeoman having retitled
  it since, the same content): inserted with its kind, title, content,
  created and modified stamps, start/end, value_int, value_float and
  done_bool, then soft-deleted if the copy's is - a new id.
- PRESENT: created in the window and already in the live journal by that
  match - what makes a second --apply write nothing.
- MOVED: older than the window, changed in it, and the live row of the
  same id and kind is unchanged since the window began: PATCHed with the
  copy's fields that differ.
- SAME: older, and the live row already holds the copy's fields (a MOVED
  one after --apply).
- CONFLICT: older, and the live row changed after the window began too:
  listed, never written - a person decides.
- MISSING: older, and the live journal has no row of that id and kind:
  listed, never written.
The copy's entry_media rows of the window are listed as a finding: their
files are in the NAS's media store whichever journal was live, but a NEW
row's attachment is not re-attached by this.

Secret entries (docs/design/confidential-entries.md) are copied as they
are: `classification` and `sealed`, the envelope, verbatim - the script
never sees their text, and needs none. The server takes a write of either
only with the vault's token (X-LCARS-Vault), which this sends from
LCARS_VAULT_TOKEN in the environment (Config's Classified section copies
it while unlocked); without it such a write fails with the server's 403,
in the plan's result, and nothing of the row is written.

What the API cannot carry, said rather than hidden: a NULL value_int or
value_float is written as 0 (POST binds 0; the two compare equal here);
value_float goes through the server's float (single precision); a title is
kept to 511 bytes.

Overrides, for scripts/test_db_merge_window.py: LCARS_URL (the server),
LCARS_MERGE_STATE (the state file), LCARS_MERGE_ENV (the env file),
LCARS_REPORT_PY (the publisher).
"""

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("LCARS_MERGE_STATE") or os.path.expanduser("~/.local/state/lcars/db-swap.json")
ENV_FILE = os.environ.get("LCARS_MERGE_ENV") or os.path.expanduser("~/.env")
DEFAULT_COPY = os.path.expanduser("~/lcars-personal.db")
SKIP_KINDS = {"crew_inbox": "the seat's delivery slips, stale",
              "crew_seat": "the seat's state, stale",
              "task_no1": "Number One's questions, raised again since"}
# Compared, and written on a MOVED row; created_at_utc only on a NEW one
# (it is the match key, so a MOVED row's is equal by construction or a
# person changed it, which is a CONFLICT's business).
FIELDS = ("title", "content", "value_int", "value_float", "done_bool", "deleted", "start_date", "end_date",
          "classification", "sealed")
# the two a write of carries the vault's token for (the server's guard)
CLASSIFIED = ("classification", "sealed")
CLASSES = ("NEW", "MOVED", "CONFLICT", "MISSING", "SKIPPED", "PRESENT", "SAME")
WRITES = ("NEW", "MOVED")


def die(msg, code=1):
    print(f"db-merge-window: {msg}", file=sys.stderr)
    sys.exit(code)


def read_env(path):
    """KEY=VALUE lines (an `export ` prefix allowed), parsed, never sourced
    - crew_tool.py's rule."""
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                k, eq, v = line.partition("=")
                if eq and k and not k.startswith("#"):
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def stamp(s):
    """UTC "YYYY-MM-DD HH:MM:SS" from that or ISO with a Z, as stored."""
    s = (s or "").strip().replace("T", " ").rstrip("Z")
    if len(s) != 19 or s[4] != "-" or s[10] != " ":
        die(f"not a UTC stamp: {s!r} (want YYYY-MM-DD HH:MM:SS)", 2)
    return s


class API:
    def __init__(self, url, user, pw):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Authorization": self.auth, "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(text)
            except ValueError:
                return e.code, text

    def get(self, path, **q):
        st, body = self.call("GET", path + ("?" + urllib.parse.urlencode(q) if q else ""))
        return st, body


def norm(field, v):
    """A field as the two sides are compared: NULL text as "", NULL numbers
    as 0 (what POST stores for one not given), the float rounded past what
    single precision keeps."""
    if field in ("value_int", "done_bool", "deleted", "classification"):
        return int(v or 0)
    if field == "value_float":
        return float("%.6g" % float(v or 0))
    return v if v is not None else ""


def differs(copy, live):
    return [f for f in FIELDS if norm(f, copy.get(f)) != norm(f, live.get(f))]


def copy_rows(path, since, until):
    """The copy's rows created or modified in the window, and its media rows
    of the window, read-only."""
    if not os.path.isfile(path):
        die(f"{path}: not a file", 75)
    db = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    # a copy made before classified entries has neither column: 0 and ''
    cols = {r[1] for r in db.execute("PRAGMA table_info(entries)")}
    classified = ("ifnull(classification, 0) AS classification" if "classification" in cols
                  else "0 AS classification") + ", " + \
                 ("ifnull(sealed, '') AS sealed" if "sealed" in cols else "'' AS sealed")
    rows = [dict(r) for r in db.execute(
        "SELECT id, kind, title, content, value_int, value_float, done_bool, deleted, created_at_utc,"
        " last_modified_at_utc, start_date, end_date, " + classified + " FROM entries"
        " WHERE (created_at_utc >= ? AND created_at_utc <= ?)"
        " OR (last_modified_at_utc >= ? AND last_modified_at_utc <= ?) ORDER BY id",
        (since, until, since, until))]
    media = []
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'entry_media'").fetchone():
        media = [dict(r) for r in db.execute(
            "SELECT m.id, m.entry_id, m.mime, m.bytes, m.created_at_utc, m.deleted, e.kind, e.title"
            " FROM entry_media m LEFT JOIN entries e ON e.id = m.entry_id"
            " WHERE m.created_at_utc >= ? AND m.created_at_utc <= ? ORDER BY m.id", (since, until))]
    db.close()
    return rows, media


def live_match(api, r):
    """The live row this in-window copy row already is, or None: same kind
    and created_at_utc, and the same title or (retitled since) content."""
    st, rows = api.get("/entries", kind=r["kind"], since=r["created_at_utc"], until=r["created_at_utc"],
                       deleted="all", limit=1000)
    if st != 200:
        die(f"GET /entries for #{r['id']}: {st} {rows}")
    if r.get("classification"):
        # a Secret row's title is sealed (empty): its envelope is the match
        for lv in rows:
            if norm("sealed", lv.get("sealed")) == norm("sealed", r.get("sealed")):
                return lv
        return None
    for lv in rows:
        if norm("title", lv.get("title")) == norm("title", r["title"]):
            return lv
    for lv in rows:
        if norm("content", lv.get("content")) == norm("content", r["content"]) and r["content"]:
            return lv
    return None


def classify(api, rows, since):
    plan = []
    for r in rows:
        item = {"copy": r, "live_id": None, "fields": [], "note": ""}
        if r["kind"] in SKIP_KINDS:
            item["class"], item["note"] = "SKIPPED", SKIP_KINDS[r["kind"]]
        elif r["created_at_utc"] >= since:
            lv = live_match(api, r)
            if lv:
                item["class"], item["live_id"] = "PRESENT", lv["id"]
            else:
                item["class"] = "NEW"
        else:
            st, lv = api.get(f"/entries/{r['id']}")
            if st == 404 or (st == 200 and lv.get("kind") != r["kind"]):
                item["class"] = "MISSING"
                item["note"] = "no live row" if st == 404 else f"live #{r['id']} is a {lv.get('kind')}"
            elif st != 200:
                die(f"GET /entries/{r['id']}: {st} {lv}")
            else:
                item["live_id"] = lv["id"]
                item["live"] = lv
                item["fields"] = differs(r, lv)
                if not item["fields"]:
                    item["class"] = "SAME"
                elif lv["last_modified_at_utc"] >= since:
                    item["class"] = "CONFLICT"
                    item["note"] = f"live changed {lv['last_modified_at_utc']}"
                else:
                    item["class"] = "MOVED"
        plan.append(item)
    return plan


def save_undo(path, plan):
    """The live rows a MOVED PATCH will overwrite, as they are now, so an
    undo by hand (a PATCH back) is possible. Written before any write, and
    never over an earlier file: that one holds the older truth."""
    rows = [{k: it["live"].get(k) for k in ("id", "kind", "title", "last_modified_at_utc", "content", *it["fields"])}
            for it in plan if it["class"] == "MOVED"]
    if os.path.exists(path):
        die(f"{path} exists: not overwriting an earlier undo file", 2)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return len(rows)


def vault_headers(fields):
    """X-LCARS-Vault for a write that carries a classified column."""
    tok = os.environ.get("LCARS_VAULT_TOKEN", "")
    return {"X-LCARS-Vault": tok} if tok and any(f in CLASSIFIED for f in fields) else {}


def apply(api, plan):
    """The writes, NEW then MOVED. Each NEW create carries an
    Idempotency-Key from the copy row, so a retried request is the same
    row; a second run finds it PRESENT either way. Each PATCH carries
    if_modified, the live row's stamp as classify read it, compared in the
    server's UPDATE itself (0.230.0): a row edited since is a 412 and left
    as it is."""
    for it in plan:
        r = it["copy"]
        if it["class"] == "NEW":
            body = {k: r[k] for k in ("kind", "title", "content", "created_at_utc", "last_modified_at_utc")}
            body.update(value_int=int(r["value_int"] or 0), value_float=float(r["value_float"] or 0),
                        done_bool=int(r["done_bool"] or 0))
            for k in ("start_date", "end_date"):
                if r[k]:
                    body[k] = r[k]
            if r.get("classification"):
                body.update(classification=int(r["classification"]), sealed=r.get("sealed") or "")
            body = {k: ("" if v is None else v) for k, v in body.items()}
            key = "merge-" + hashlib.sha1(f"{r['kind']}|{r['created_at_utc']}|{r['id']}".encode()).hexdigest()[:32]
            st, got = api.call("POST", "/entries", body, {"Idempotency-Key": key, **vault_headers(body)})
            if st not in (200, 201) or not isinstance(got, dict) or not got.get("id"):
                it["result"] = f"failed: {st} {got}"
                continue
            it["live_id"] = got["id"]
            it["result"] = "inserted"
            if r["deleted"]:
                st, got = api.call("DELETE", f"/entries/{it['live_id']}")
                it["result"] = "inserted, deleted" if st == 200 else f"inserted, delete failed: {st} {got}"
        elif it["class"] == "MOVED":
            body = {f: norm(f, r.get(f)) for f in it["fields"]}
            if any(f in CLASSIFIED for f in body):
                # the level and the envelope go together: the server judges
                # an envelope by the level it lands with
                body.update(classification=norm("classification", r.get("classification")),
                            sealed=norm("sealed", r.get("sealed")))
            body["if_modified"] = it["live"]["last_modified_at_utc"]
            st, got = api.call("PATCH", f"/entries/{r['id']}", body, vault_headers(body))
            it["result"] = "patched" if st == 200 else f"failed: {st} {got}"


def md_cell(v):
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")[:120]


def render(plan, media, since, until, copy_path, applied):
    counts = {}
    for it in plan:
        counts.setdefault(it["copy"]["kind"], {}).setdefault(it["class"], 0)
        counts[it["copy"]["kind"]][it["class"]] += 1
    out = ["# Rows lost to a db-swap: the merge plan" + (" (applied)" if applied else " (dry run)"), "",
           f"Copy `{copy_path}`, window {since} to {until} UTC. "
           "Copy rows created or modified in the window, against the live journal through the API. "
           "Only ids, kinds, titles and stamps are shown.", "",
           "## Counts by kind", "", "| kind | " + " | ".join(CLASSES) + " |",
           "|---|" + "---|" * len(CLASSES)]
    for kind in sorted(counts):
        out.append(f"| {kind} | " + " | ".join(str(counts[kind].get(c, 0) or "") for c in CLASSES) + " |")
    tot = {c: sum(1 for it in plan if it["class"] == c) for c in CLASSES}
    out.append("| **all** | " + " | ".join(str(tot[c] or "") for c in CLASSES) + " |")
    out += ["", "NEW is inserted and MOVED patched by `--apply`; nothing else is written.", "",
            "## Rows", "", "| class | copy id | kind | created | modified | title | live id | fields / note |"
            + (" result |" if applied else ""), "|---|---|---|---|---|---|---|---|" + ("---|" if applied else "")]
    for it in sorted(plan, key=lambda i: (CLASSES.index(i["class"]), i["copy"]["id"])):
        r = it["copy"]
        extra = ", ".join(it["fields"]) + ("; " if it["fields"] and it["note"] else "") + it["note"]
        line = (f"| {it['class']} | {r['id']} | {r['kind']} | {r['created_at_utc']} | {r['last_modified_at_utc']}"
                f" | {md_cell(r['title'])} | {it['live_id'] or ''} | {md_cell(extra)} |")
        if applied:
            line += f" {md_cell(it.get('result', ''))} |"
        out.append(line)
    out += ["", "## Media of the window", ""]
    if media:
        out += ["Files in the media store either way; a NEW row's attachment is not re-attached.", "",
                "| media id | entry id | kind | title | mime | bytes | created | deleted |", "|---|---|---|---|---|---|---|---|"]
        out += [f"| {m['id']} | {m['entry_id']} | {m['kind'] or ''} | {md_cell(m['title'])} | {m['mime']} | {m['bytes']}"
                f" | {m['created_at_utc']} | {m['deleted']} |" for m in media]
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--copy", help="the copy's path (default the state file's alt_slot, else ~/lcars-personal.db)")
    ap.add_argument("--since", help="window start, UTC (default the state file's filtered_at)")
    ap.add_argument("--until", help="window end, UTC (default the state file's swapped_at)")
    ap.add_argument("--apply", action="store_true", help="do the writes (default: a dry run)")
    ap.add_argument("--undo", metavar="FILE", help="with --apply: save the live rows MOVED overwrites to FILE first"
                    " (not in a state directory's top level: engineer.py reads every *.json there)")
    ap.add_argument("--report", action="store_true", help="publish the plan as Markdown through report.py")
    ap.add_argument("--markdown", metavar="FILE", help="write the plan's Markdown to FILE")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON, not text")
    a = ap.parse_args()

    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE))
        except ValueError:
            die(f"{STATE}: not JSON")
    copy_path = a.copy or state.get("alt_slot") or DEFAULT_COPY
    alt_name = os.path.basename(state.get("alt_slot") or DEFAULT_COPY)
    if state.get("in_live_slot") == alt_name:
        die(f"the state file says {alt_name} is the live journal: swap the full one back first", 75)
    since = stamp(a.since or state.get("filtered_at") or die("no --since and no filtered_at in the state file", 2))
    until = stamp(a.until or state.get("swapped_at") or die("no --until and no swapped_at in the state file", 2))
    if until <= since:
        die(f"the window is empty ({since} to {until}): give --since and --until", 2)

    env = read_env(ENV_FILE)
    user = os.environ.get("LCARS_AUTH_USER") or env.get("LCARS_AUTH_USER")
    pw = os.environ.get("LCARS_AUTH_PASS") or env.get("LCARS_AUTH_PASS")
    url = os.environ.get("LCARS_URL") or "http://127.0.0.1:8080"
    if not user or not pw:
        die("no LCARS_AUTH_USER/LCARS_AUTH_PASS in the environment or " + ENV_FILE, 2)
    api = API(url, user, pw)
    try:
        urllib.request.urlopen(url.rstrip("/") + "/health", timeout=5).read()
    except OSError as e:
        die(f"{url}/health does not answer ({e}); nothing done", 75)

    rows, media = copy_rows(copy_path, since, until)
    plan = classify(api, rows, since)
    if a.apply:
        if a.undo:
            save_undo(a.undo, plan)
        apply(api, plan)
    md = render(plan, media, since, until, copy_path, a.apply)

    if a.json:
        print(json.dumps({"since": since, "until": until, "copy": copy_path, "applied": a.apply,
                          "rows": [{"class": it["class"], "copy_id": it["copy"]["id"], "kind": it["copy"]["kind"],
                                    "live_id": it["live_id"], "fields": it["fields"],
                                    "result": it.get("result")} for it in plan],
                          "media": [{"id": m["id"], "entry_id": m["entry_id"]} for m in media]}))
    else:
        print(md, end="")
    if a.markdown:
        with open(a.markdown, "w") as f:
            f.write(md)
    if a.report:
        sys.stdout.flush()  # the plan before report.py's link, not after
        fd, path = tempfile.mkstemp(prefix="db-merge-window-", suffix=".md")
        with os.fdopen(fd, "w") as f:
            f.write(md)
        try:
            publisher = os.environ.get("LCARS_REPORT_PY") or os.path.join(HERE, "report.py")
            title = "db-swap merge " + ("applied" if a.apply else "plan") + f", {since[:10]}"
            subprocess.run([sys.executable, publisher, "publish", path, "--title", title], check=True)
        finally:
            os.unlink(path)
    failed = [it for it in plan if str(it.get("result", "")).startswith("failed") or "failed" in str(it.get("result", ""))]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
