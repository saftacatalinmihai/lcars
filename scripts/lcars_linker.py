#!/usr/bin/env python3
"""
lcars_linker.py — the deterministic half of the LCARS auto-linker agent.

The agent's job is judgement: "is this occurrence of the word `sent` the
page Sent (a mail folder), or the past tense of `send`?" That question needs a model. But
*applying* the answer must never go through a model, because the only way an LLM
can rewrite an entry body is by retyping it, and retyping the user's journal is
how words quietly change. So the split is:

    scan   -> propose candidate links, each pinned to a character offset
    (agent decides which ids to accept, and writes a Context block)
    apply  -> splice `[[` and `]]` in at those offsets, verbatim otherwise

The user's prose is never regenerated. An accepted candidate can only ever add
four characters around a span the scanner already found; everything else in the
entry is byte-identical, and that is checked with a hash before each write.

Titles are the one composed exception: entries created over the raw HTTP
endpoint arrive as the server placeholder "HTTP Entry", which is nobody's
words. The scan flags those `needs_title`, the agent may send a `title` line
for them, and apply refuses a title for any entry whose title a person chose.

Reads and writes go through lcars-cli against the HTTP API — never ~/lcars/lcars.db.
The server holds the journal in memory and rewrites the file wholesale on a
debounce, so a direct write would silently vanish at the next flush.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

# Moved from ~/.claude/scripts into the repo in 0.143.0 (scripts/lcars-link.sh
# runs it for the yeoman's nightly linker pass, crew/yeoman-linker.md). The
# paths are the VPS's; the env overrides are for a scratch run on a laptop.
# The CLI: the one binary's lcars-cli link the server makes in the checkout
# at start (~/lcars/bin/lcars-cli). The copied build it replaced retired in
# 0.279.2, once lcars.prev was a one binary too: no fallback.
CLI = os.environ.get("LCARS_CLI") or os.path.expanduser("~/lcars/bin/lcars-cli")
LOG_DIR = os.environ.get("LCARS_LINKER_LOG_DIR") or os.path.expanduser("~/lcars/lcars-linker-logs")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lcars_roles  # noqa: E402  (kinds by role, docs/design/kinds.md)

_ROLES = None


def roles():
    """The journal's mapping of roles to kinds, asked once a run through
    `lcars-cli roles --json` (lcars_roles.py: the defaults if it fails)."""
    global _ROLES
    if _ROLES is None:
        def get():
            try:
                return run_cli(["roles", "--json"])
            except SystemExit as e:     # run_cli's way of failing
                raise RuntimeError(str(e)) from None
        _ROLES = lcars_roles.load(get)
    return _ROLES


# Kinds that count as "a page you can link to". Everything else (logs, journals,
# sleep rows) is a record of a moment, not a concept with a name.
TARGET_KINDS = lcars_roles.Lazy(lambda: tuple(roles().kind(r) for r in ("page", "person", "project")), key=lambda: _ROLES)

# Kinds whose bodies we are willing to touch. Imported corpora (the
# `imported` role's kinds) are somebody else's export format and stay
# frozen; image/bookmark/drive rows are payloads, not prose.
EDITABLE_KINDS = lcars_roles.Lazy(lambda: tuple(roles().kind(r) for r in ("log", "work_log", "meeting", "page",
                                                                          "project")), key=lambda: _ROLES)

# The verbatim half of a dictated entry is the record. The skill's rule is that
# it is never tidied, re-ordered or translated — so it is never linked either.
DICTATION_MARKER = "--- dictation ---"

# Titles the server stamps on entries created over the bare HTTP endpoint —
# placeholders nobody chose. These are the only titles the agent may replace:
# anything else was typed by the user and keeps the never-rewrite guarantee.
GENERIC_TITLES = {"", "http entry"}
MAX_TITLE_LEN = 120

# The Context block's first line. Kept byte-identical on every run so it stays
# greppable (`--search 'Context · auto'`) and so re-runs replace rather than
# stack. Changing this string orphans every block already written.
CONTEXT_MARKER = "## Context · auto"
CONTEXT_SEP = "\n\n---\n" + CONTEXT_MARKER + "\n"

# Titles that are never worth proposing: generic containers, scratch pages, and
# strings so short that a match carries no evidence. These are dropped outright
# rather than flagged, because no context makes `[[test]]` the right call.
HARD_BLOCK = {
    "test", "page", "contents", "favorites", "inbox", "templates", "todos",
    "projects", "articles", "books", "ideas", "links", "videos", "tools",
    "people", "profile", "journal", "home", "work", "blog", "travel",
    "cooking", "politics", "process", "health", "computer", "h",
    "all resources", "me", "notes", "misc",
}

# Titles that are real pages but whose spelling collides with ordinary English
# or Romanian. Proposed, but flagged `risky` with a reason so the agent reads
# the sentence before accepting. `ai`/`sent`/`val`/`spot` are the live examples:
# `ai` is Romanian "you have", `sent` is the past tense of send, `val` is a name
# and a common syllable, `spot` is both a channel and a spot.
COMMON_WORD_COLLISIONS = {
    "ai", "sent", "val", "spot", "snow", "strong", "orange", "skin",
    "swift", "lambda", "scala", "cortex", "malt", "relu", "git", "nas",
    "mas", "aws",
}


def load_local_words(path=None):
    """A journal's own titles for the two sets above, from
    lcars_linker.local.txt beside this script: `block: a, b` and `collide:
    c, d` lines, `#` comments. Its page names are the owner's (their work's
    acronyms, their people's short names), so they live in that file, which
    the public export leaves out by its name, not in this list; no file, no
    words."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "lcars_linker.local.txt")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, words = line.split("#", 1)[0].partition(":")
        target = {"block": HARD_BLOCK, "collide": COMMON_WORD_COLLISIONS}.get(key.strip())
        if sep and target is not None:
            target.update(w.strip().lower() for w in words.split(",") if w.strip())


load_local_words()

# Never link inside these: a hostname, a URL, a code span, a markdown link
# target, an email, or a heading line. Each is a place where `[[` would either
# break the thing or link a word that is not prose.
PROTECT_PATTERNS = [
    re.compile(r"```.*?```", re.S),               # fenced code
    re.compile(r"`[^`\n]+`"),                     # inline code
    re.compile(r"\[\[[^\[\]\n]{1,90}\]\]"),       # an existing wiki link
    re.compile(r"\(\(\d+\)\)"),                   # an entry reference
    re.compile(r"#[-\w]+"),                       # a #tag
    re.compile(r"https?://\S+"),                  # a URL
    re.compile(r"\b[\w-]+(?:\.[\w-]+){2,}\b"),    # a dotted hostname / identifier
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),  # an email address
    re.compile(r"\[[^\]\n]*\]\([^)\n]*\)"),       # a markdown link
    re.compile(r"^#{1,6} .*$", re.M),             # a heading line
    re.compile(r"^\s*[-*]\s+(?:DONE|DOING|TODO|LATER|NOW|WAITING|CANCELED)\b",
               re.M),                             # a task keyword
]

MAX_CANDIDATES_PER_ENTRY = 12


def run_cli(args):
    """Call lcars-cli and return parsed JSON. Credentials come from the
    environment the caller already exported (LCARS_AUTH_USER/PASS/URL)."""
    proc = subprocess.run([CLI] + args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            "lcars-cli failed: %s\n%s" % (" ".join(args), proc.stderr.strip())
        )
    out = proc.stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = data.get("entries", data)
    return data


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_targets():
    """Every title that can be the far end of a link, keyed by lowercase title
    (which is exactly how the UI's byTitle() resolves a click)."""
    targets = {}
    for kind in TARGET_KINDS:
        for row in run_cli(["list", "--kind", kind, "--limit", "1000", "--json"]):
            title = (row.get("title") or "").strip()
            key = title.lower()
            if not title or key in HARD_BLOCK:
                continue
            if len(key) < 3 and key not in COMMON_WORD_COLLISIONS:
                continue
            # A date-named page ("2026-09-16") is a journal day, not a concept.
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
                continue
            targets.setdefault(key, {"title": title, "refs": []})
            targets[key]["refs"].append({"kind": kind, "id": row["id"]})
    return targets


def protected_mask(content):
    """A bool per character: True where a match must not be proposed."""
    mask = [False] * len(content)
    for pat in PROTECT_PATTERNS:
        for m in pat.finditer(content):
            for i in range(m.start(), m.end()):
                mask[i] = True
    # The verbatim dictation half, and anything after a Context block we wrote.
    for marker in (DICTATION_MARKER, CONTEXT_MARKER):
        cut = content.find(marker)
        if cut >= 0:
            for i in range(cut, len(content)):
                mask[i] = True
    return mask


def sentence_around(content, start, end):
    """The clause the match sits in — what the agent actually reads to judge."""
    left = max(content.rfind("\n", 0, start), content.rfind(". ", 0, start))
    right = content.find("\n", end)
    dot = content.find(". ", end)
    if dot != -1 and (right == -1 or dot < right):
        right = dot
    if left < 0:
        left = 0
    if right < 0:
        right = len(content)
    return content[left:right].strip()


def scan_entry(entry, targets, pattern):
    content = entry.get("content") or ""
    if not content.strip():
        return []
    mask = protected_mask(content)
    own_title = (entry.get("title") or "").strip().lower()
    body_lower = content.lower()
    out = []
    seen = set()

    for m in pattern.finditer(content):
        key = m.group(1).lower()
        if key in seen or key not in targets:
            continue
        if key == own_title:                       # an entry never links itself
            continue
        # Spans are group 1 — the title alone. Any plural suffix stays outside
        # the brackets, so it must not be masked-checked or spliced over.
        start, end = m.start(1), m.end(1)
        if any(mask[i] for i in range(m.start(), m.end())):
            continue
        # Already linked somewhere else in this entry: the user's convention is
        # to bracket a name once, not on every mention.
        if ("[[" + key) in body_lower:
            seen.add(key)
            continue

        target = targets[key]
        risky, why = False, []
        if key in COMMON_WORD_COLLISIONS:
            risky = True
            why.append("common word / collides with ordinary English or Romanian")
        if len(key) <= 4:
            risky = True
            why.append("very short title — needs the sentence to confirm")
        if target["title"].isupper() and not m.group(1).isupper():
            risky = True
            why.append(
                "page is the acronym %r but the text is lowercase %r"
                % (target["title"], m.group(1))
            )
        if m.group(2):
            why.append(
                "matched as the plural %r — the link would read [[%s]]%s"
                % (m.group(0), m.group(1), m.group(2))
            )
        if len(target["refs"]) > 1:
            why.append(
                "%d entries share this title: %s"
                % (len(target["refs"]),
                   ", ".join("#%d %s" % (r["id"], r["kind"]) for r in target["refs"]))
            )

        seen.add(key)
        out.append({
            "cid": "%d:%s" % (entry["id"], key),
            "surface": m.group(1),
            "target_title": target["title"],
            "target_kind": target["refs"][0]["kind"],
            "target_id": target["refs"][0]["id"],
            "start": start,
            "end": end,
            "risky": risky,
            "notes": why,
            "sentence": sentence_around(content, m.start(), m.end()),
        })
        if len(out) >= MAX_CANDIDATES_PER_ENTRY:
            break
    return out


def cmd_scan(args):
    targets = build_targets()
    keys = sorted(targets, key=len, reverse=True)      # longest title wins
    # A trailing plural is matched but left outside the brackets, so "Kiosk
    # stations" becomes "[[Kiosk station]]s" — the link resolves and the sentence
    # still reads as written.
    pattern = re.compile(
        r"(?<![\w\[])(" + "|".join(re.escape(k) for k in keys) + r")(e?s)?(?![\w\]])",
        re.I,
    )

    entries = run_cli(
        ["list", "--date", args.date, "--limit", "200", "--content", "--json"]
    )
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    payload, skipped = [], []

    for e in entries:
        if e.get("deleted"):
            continue
        title = e.get("title") or ""
        needs_title = title.strip().lower() in GENERIC_TITLES
        editable = e["kind"] in EDITABLE_KINDS
        # A frozen kind still shows up when it wears the placeholder title:
        # titles are metadata, not the body, so any kind may be named. It goes
        # into the scan with no candidates and its body stays untouchable.
        if not editable and not needs_title:
            skipped.append({"id": e["id"], "why": "kind %s is not editable" % e["kind"]})
            continue
        content = e.get("content") or ""
        if not content.strip():
            skipped.append({"id": e["id"], "why": "empty body"})
            continue
        # Don't touch something the user may still be typing into.
        try:
            mod = dt.datetime.strptime(e["last_modified_at_utc"], "%Y-%m-%d %H:%M:%S")
            idle_min = (now - mod).total_seconds() / 60.0
        except (KeyError, ValueError):
            idle_min = 9999
        if idle_min < args.quiet_minutes:
            skipped.append({
                "id": e["id"],
                "why": "modified %.0f min ago (quiet period %d min)"
                       % (idle_min, args.quiet_minutes),
            })
            continue

        payload.append({
            "id": e["id"],
            "kind": e["kind"],
            "title": title,
            "needs_title": needs_title,
            "editable": editable,
            "content_sha": sha(content),
            "content": content,
            "has_context_block": CONTEXT_MARKER in content,
            "candidates": scan_entry(e, targets, pattern) if editable else [],
        })

    json.dump(
        {"date": args.date, "scanned_at_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
         "target_count": len(targets), "entries": payload, "skipped": skipped},
        open(args.out, "w"), indent=1, ensure_ascii=False,
    )
    n_cand = sum(len(e["candidates"]) for e in payload)
    print("scanned %d entries (%d skipped), %d candidates, %d link targets -> %s"
          % (len(payload), len(skipped), n_cand, len(targets), args.out))


def splice(content, accepted):
    """Insert [[ ]] around each accepted span, right to left so earlier offsets
    stay valid. This is the only edit ever made to the user's own sentences."""
    for c in sorted(accepted, key=lambda c: c["start"], reverse=True):
        if content[c["start"]:c["end"]] != c["surface"]:
            raise ValueError("offset drift at %s" % c["cid"])
        content = (content[:c["start"]] + "[[" + c["surface"] + "]]"
                   + content[c["end"]:])
    return content


def apply_context(content, block):
    """Replace an existing auto Context block, or append a new one. Anything the
    user wrote below our marker is not preserved — they should write above it."""
    if not block:
        return content
    block = block.strip()
    if block.startswith(CONTEXT_MARKER):
        block = block[len(CONTEXT_MARKER):].lstrip("\n")
    cut = content.find(CONTEXT_MARKER)
    if cut >= 0:
        head = content[:cut].rstrip()
        head = head[:-3].rstrip() if head.endswith("---") else head
        content = head
    return content.rstrip() + CONTEXT_SEP + block + "\n"


def parse_plan(text):
    """Parse the line-oriented decisions format into the JSON shape.

    JSON cannot reach this script from an unattended agent: the Write tool is
    sandboxed off, and the shell tool rejects any command containing both `{`
    and `"` as expansion obfuscation, which rules out a heredoc too. So the wire
    format is lines, with no braces and no required quoting:

        entry 3557
        title Ledgerly booking latency — sidecar timeout
        accept 3557:ledgerly
        accept 3557:relay api
        context Thread: prod issue ((3465)) — bookings over 3s.
        context Fix in flight: ((3569)).
        entry 3565

    An `entry` with no `accept`, `title` or `context` is a deliberate "looked
    at it, decided nothing" — it shows the work without changing anything.
    `title` is honored only for entries the scan flagged `needs_title` (the
    server's "HTTP Entry" placeholder); the applier drops it otherwise.
    """
    entries, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, rest = line.partition(" ")
        verb, rest = verb.lower(), rest.strip()
        if verb == "entry":
            cur = {"id": int(rest), "accept": [], "context": [], "title": ""}
            entries.append(cur)
        elif cur is None:
            raise ValueError("%r before any 'entry' line" % line)
        elif verb == "accept":
            cur["accept"].append(rest)
        elif verb == "context":
            cur["context"].append(rest)
        elif verb == "title":
            if cur["title"]:
                raise ValueError("two 'title' lines for entry %d" % cur["id"])
            cur["title"] = rest
        else:
            raise ValueError(
                "unknown directive %r (want entry/accept/title/context)" % verb)
    for e in entries:
        e["context"] = "\n".join(e["context"]).strip()
    return {"entries": entries}


def cmd_apply(args):
    scan = json.load(open(args.scan))
    # `--decisions -` reads stdin, in either format: JSON if it starts with a
    # brace or bracket, otherwise the line format above.
    if args.decisions == "-":
        text = sys.stdin.read()
        decisions = (json.loads(text) if text.lstrip()[:1] in "{["
                     else parse_plan(text))
    else:
        decisions = json.load(open(args.decisions))
    by_id = {e["id"]: e for e in scan["entries"]}
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "%s.md" % scan["date"])
    log = ["# LCARS auto-linker — %s" % scan["date"],
           "run at %s UTC%s" % (dt.datetime.now(dt.timezone.utc)
                                .strftime("%Y-%m-%d %H:%M:%S"),
                                "  (DRY RUN)" if args.dry_run else ""), ""]
    changed = 0

    for d in decisions.get("entries", []):
        eid = d["id"]
        src = by_id.get(eid)
        if not src:
            log.append("- **#%d** skipped — not in this scan" % eid)
            continue

        # The journal is live. Re-read and compare against what was scanned; if
        # the user edited in between, their version wins and we skip.
        fresh = run_cli(["get", str(eid), "--json"])
        fresh = fresh[0] if isinstance(fresh, list) else fresh
        current = fresh.get("content") or ""
        if sha(current) != src["content_sha"]:
            log.append("- **#%d** skipped — edited since the scan" % eid)
            continue

        wanted = set(d.get("accept", []))
        accepted = [c for c in src["candidates"] if c["cid"] in wanted]
        block = d.get("context")
        if block and not src.get("editable", True):
            log.append("- **#%d** context dropped — %s bodies are frozen"
                       % (eid, src["kind"]))
            block = None

        # A title is the one thing the agent composes rather than splices, so
        # it gets its own guard rails: only onto the server's placeholder, only
        # if the user has not titled the entry themselves since the scan.
        new_title = " ".join((d.get("title") or "").split()).strip()[:MAX_TITLE_LEN]
        if new_title:
            if not src.get("needs_title"):
                log.append("- **#%d** title dropped — entry already has a real "
                           "title (%r)" % (eid, src["title"]))
                new_title = ""
            elif (fresh.get("title") or "") != src["title"]:
                log.append("- **#%d** title dropped — retitled since the scan "
                           "(%r)" % (eid, fresh.get("title")))
                new_title = ""
        if new_title:
            # Every auto title leads with the day it belongs to, so lists sort
            # and read chronologically. Added here, not by the agent, so it is
            # uniform and never doubled.
            if not new_title.startswith(scan["date"]):
                new_title = "%s - %s" % (scan["date"], new_title)
            new_title = new_title[:MAX_TITLE_LEN]

        if not accepted and not block and not new_title:
            continue

        try:
            new = splice(current, accepted)
        except ValueError as err:
            log.append("- **#%d** skipped — %s" % (eid, err))
            continue
        new = apply_context(new, block)
        content_changed = new != current
        if not content_changed and not new_title:
            continue

        what = ", ".join("`%s` → [[%s]]" % (c["surface"], c["target_title"])
                         for c in accepted)
        if new_title:
            what = ", ".join(filter(None, [what, "titled %r" % new_title]))
        log.append("- **#%d** %s — %s" % (
            eid, src["title"] or "(untitled)", what or "context block only"))
        if block:
            log.append("  - context: %s" % " / ".join(block.strip().splitlines()[:4]))
        if args.verbose:
            log.append("  ```\n%s\n  ```" % new)

        if not args.dry_run:
            cli_args = [CLI, "set", str(eid)]
            if new_title:
                cli_args += ["--title", new_title]
            if content_changed:
                cli_args += ["--file", "-"]
            proc = subprocess.run(cli_args, input=new if content_changed else None,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                log.append("  - **WRITE FAILED**: %s" % proc.stderr.strip())
                continue
        changed += 1

    log.append("")
    log.append("**%d entries %s.**" % (changed, "would change" if args.dry_run
                                       else "updated"))
    with open(log_path, "a") as fh:
        fh.write("\n".join(log) + "\n")
    print("\n".join(log))
    print("\nlog: %s" % log_path)


# ---------------------------------------------------------------- measure --
#
# The web UI draws any kind whose rows carry value_float/value_int as a
# sparkline (lcars-ui/index.html, measureSeries). Several kinds *are* series
# already, just not written as numbers: a `sleep` row says "start" or "end",
# and the duration is the gap between two rows. `measure` does that
# arithmetic. It needs no judgement, so it is not the agent's job — the
# nightly script runs it before the agent, and it is safe to run any time.
#
# Only whole kinds are measured, never a number found in prose: the chart is
# per kind, so a weight pulled out of a log would draw a log line mixing
# weights with whatever else got pulled out.
#
# Ownership: a value is written only when both value fields are zero, or when
# the row still wears the title this command gave it (so a start time moved
# after the fact is re-measured, but a value or title a person set is never
# touched). Writes are diffs; a second run over the same journal writes
# nothing.

# role -> (unit, lo, hi): an end paired with a start further apart than `hi`
# is a missing row, not a measurement; one closer than `lo` is a mis-tap.
# The kinds are the roles' (paired_kinds), so the child's sleep is measured
# under whatever kind the journal keeps it.
PAIRED_ROLES = {
    "sleep":       ("hours",   0.5, 16.0),
    "child_sleep": ("hours",   0.5, 16.0),
    "drive":       ("minutes", 3.0, 360.0),
}


def paired_kinds():
    """kind -> (unit, lo, hi), by the roles; two roles on one kind count once."""
    out = {}
    for role, spec in PAIRED_ROLES.items():
        out.setdefault(roles().kind(role), spec)
    return out


# kind -> value_int is the running count of rows, oldest first: the child's
# vocabulary
COUNTED_KINDS = lcars_roles.Lazy(lambda: (roles().kind("child_vocab"),), key=lambda: _ROLES)
# A gym session is a row of the log role's kind (personal_log), not a kind of its own (#4003 titled "gym",
# #5037 "at gym ."), timed with the reader's stopwatch (0.103.0), so it is
# one row carrying start_date/end_date. Only such a row is measured: the
# word alone is also "Ana is at the gym". Its value_float makes
# the log a chartable series, which is only gym minutes; the title the
# pass gives a placeholder keeps the word, so the explorer's {"gym"} splits
# it. crew_tool.py's weekstats counts these rows by the same is_gym.
GYM = ("minutes", 10.0, 300.0)
GYM_RE = re.compile(r"\bgym\b", re.I)


def is_gym(e, log_kind=None):
    """A log about the gym: the word in its title or first line. log_kind:
    the log role's kind as the caller has it (crew_tool.py's own roles),
    else this module's."""
    first = (e.get("content") or "").strip().split("\n", 1)[0]
    return (e.get("kind") == (log_kind or roles().kind("log"))
            and bool(GYM_RE.search((e.get("title") or "") + "\n" + first)))


def row_word(e):
    """'start' / 'end' from the first word of the body (drive rows follow it
    with an address), else from the title (one child's sleep row was titled
    'start' with the same body)."""
    for text in (e.get("content") or "", e.get("title") or ""):
        m = re.match(r"\s*(start|end)\b", text, re.I)
        if m:
            return m.group(1).lower()
    return None


def fmt_duration(unit, v):
    if unit == "hours":
        mins = int(round(v * 60))
        return "%dh %02dm" % (mins // 60, mins % 60)
    return "%d min" % int(round(v))


def owned(e, auto_title_of):
    """True when this command may write the row's value."""
    vi, vf = int(e.get("value_int") or 0), float(e.get("value_float") or 0)
    if not vi and not vf:
        return True
    return auto_title_of is not None and (e.get("title") or "") == auto_title_of(e)


def list_kind(kind, *extra):
    rows = run_cli(["list", "--kind", kind, "--limit", "1000", "--content",
                    "--order", "created", "--dir", "asc", "--json"] + list(extra))
    if len(rows) >= 1000:
        raise SystemExit("measure: kind %s has 1000+ rows; page it" % kind)
    return [r for r in rows if not r.get("deleted")]


def parse_stamp(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def own_span(r):
    """The row's own (start, end), when it carries one: start_date and
    end_date, the stopwatch's shape since 0.103.0; or, on an end row, a
    start_date alone, ended when the row was written - what an end row with
    no start row before it can carry (set Scheduled's start in the editor's
    Details) to be measured without a start row being made up."""
    try:
        s = parse_stamp(r["start_date"]) if r.get("start_date") else None
        e = parse_stamp(r["end_date"]) if r.get("end_date") else None
        if s and not e and row_word(r) == "end":
            e = parse_stamp(r["created_at_utc"])
    except ValueError:
        return None
    return (s, e) if s and e and e > s else None


def measure_kind(kind, rows, unit, lo, hi, paired=True):
    """[(row, value, note)] and the log lines for one series kind; no I/O.

    The pairing walks the rows by creation time. An end takes the latest
    start before it, except an end under `lo` after it: a start and an end a
    few seconds apart (a child's sleep #830/#831, at waking) is a mis-tap of
    Start before End, so that end takes the start before the mis-tapped one
    (#825, the evening before). Either way the end consumes what is open.
    A row no pairing measured is measured by its own span (own_span), which
    is how every stopwatch-timed row is measured; a start row that an end
    row measured is not, or the one drive would count twice (#4259/#4261)."""
    scale = 3600.0 if unit == "hours" else 60.0
    out, log, used, orphans = [], [], set(), []
    starts = []
    rows = sorted(rows, key=lambda r: (r["created_at_utc"], r["id"]))
    gap = lambda a, b: (parse_stamp(b["created_at_utc"]) - parse_stamp(a["created_at_utc"])).total_seconds() / scale
    for r in rows if paired else ():
        w = row_word(r)
        if w == "start":
            starts.append(r)
            continue
        if w != "end":
            continue
        open_, starts = starts, []      # an end consumes what is open
        if not open_:
            orphans.append((r, "end with no start before it"))
            continue
        s, v, note = open_[-1], gap(open_[-1], r), ""
        if v < lo and len(open_) > 1:
            s, v, note = open_[-2], gap(open_[-2], r), " (start #%d a mis-tap)" % open_[-1]["id"]
        if not lo <= v <= hi:
            orphans.append((r, "%.1f %s since start #%d is out of range" % (v, unit, s["id"])))
            continue
        used.update((r["id"], s["id"]))
        out.append((r, v, "since #%d%s" % (s["id"], note)))
    measured = set(used)
    for r in rows:
        sp = None if r["id"] in used else own_span(r)
        if sp:
            v = (sp[1] - sp[0]).total_seconds() / scale
            if lo <= v <= hi:
                measured.add(r["id"])
                out.append((r, v, "its own span from %s" % r["start_date"][:16]))
            else:
                log.append("- %s #%d: own span of %.1f %s is out of range — left empty" % (kind, r["id"], v, unit))
    for r, why in orphans:
        if r["id"] not in measured:
            log.append("- %s #%d: %s — left empty" % (kind, r["id"], why))
    out.sort(key=lambda t: (t[0]["created_at_utc"], t[0]["id"]))
    return [(r, round(v, 2) if unit == "hours" else round(v), n) for r, v, n in out], log


def plan_values(kind, items, unit, label=""):
    """The writes for measured rows: (row, field, value, title, note), only
    over values and titles the pass owns, and only where they differ."""
    plan = []
    auto = lambda e: label + fmt_duration(unit, float(e.get("value_float") or 0))
    for r, v, note in items:
        if not owned(r, auto):
            continue
        # the title is only ours to set over the placeholder or our own
        t = r.get("title") or ""
        title = label + fmt_duration(unit, v) if (t.strip().lower() in GENERIC_TITLES or t == auto(r)) else None
        if abs(float(r.get("value_float") or 0) - v) < 1e-9 and title in (None, t):
            continue
        plan.append((r, "--value-float", v, title, "%s %s" % (fmt_duration(unit, v), note)))
    return plan


def cmd_measure(args):
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    quiet = dt.timedelta(minutes=args.quiet_minutes)
    plan = []          # (row, field, value, title-or-None, note)
    log = []

    for kind, (unit, lo, hi) in paired_kinds().items():
        items, lines = measure_kind(kind, list_kind(kind), unit, lo, hi)
        log += lines
        plan += plan_values(kind, items, unit)
    # gym: only scheduled log rows can carry a span, a few dozen
    gym = [r for r in list_kind(roles().kind("log"), "--scheduled", "1") if is_gym(r)]
    items, lines = measure_kind("gym", gym, *GYM, paired=False)
    log += lines
    plan += plan_values("gym", items, GYM[0], "gym · ")

    for kind in COUNTED_KINDS:
        rows = sorted(list_kind(kind), key=lambda r: (r["created_at_utc"], r["id"]))
        for n, r in enumerate(rows, 1):
            if int(r.get("value_int") or 0) == n or not owned(r, None):
                continue
            plan.append((r, "--value-int", n, None, "word #%d" % n))

    changed = 0
    for r, field, v, title, note in plan:
        if now - parse_stamp(r["last_modified_at_utc"]) < quiet:
            log.append("- %s #%d: edited in the last %d min — next run"
                       % (r["kind"], r["id"], args.quiet_minutes))
            continue
        log.append("- %s #%d (%s): %s = %s%s" % (
            r["kind"], r["id"], r["created_at_utc"][:16], field[2:], v,
            ", titled %r" % title if title else "") + " — " + note)
        if not args.dry_run:
            cli_args = [CLI, "set", str(r["id"]), field, str(v)]
            if title:
                cli_args += ["--title", title]
            proc = subprocess.run(cli_args, capture_output=True, text=True)
            if proc.returncode != 0:
                log.append("  - **WRITE FAILED**: %s" % proc.stderr.strip())
                continue
        changed += 1

    head = ["# LCARS measure", "run at %s UTC%s" % (now.strftime("%Y-%m-%d %H:%M:%S"),
            "  (DRY RUN)" if args.dry_run else ""), ""]
    tail = ["", "**%d rows %s.**" % (changed, "would change" if args.dry_run else "updated")]
    out = "\n".join(head + log + tail)
    if not args.dry_run and changed:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "measure-%s.md" % now.strftime("%Y-%m-%d")), "a") as fh:
            fh.write(out + "\n")
    print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="propose candidate links for a day")
    s.add_argument("--date", required=True, help="YYYY-MM-DD (user's local day)")
    s.add_argument("--out", required=True)
    s.add_argument("--quiet-minutes", type=int, default=30,
                   help="skip entries modified more recently than this")
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser("apply", help="apply the agent's decisions")
    a.add_argument("--scan", required=True)
    a.add_argument("--decisions", required=True,
                   help="path to the decisions JSON, or '-' to read stdin")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--verbose", action="store_true")
    a.set_defaults(func=cmd_apply)

    m = sub.add_parser("measure", help="fill value fields for series kinds")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--quiet-minutes", type=int, default=30,
                   help="skip rows modified more recently than this")
    m.set_defaults(func=cmd_measure)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
