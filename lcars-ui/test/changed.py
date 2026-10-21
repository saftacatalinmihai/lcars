#!/usr/bin/env python3
"""Which of run.sh's stages a change needs: the files it touches against main,
and for index.html the sections its hunks fall in (docs/ops/engineer-time.md).

    python3 test/changed.py            # what to run, said in words
    python3 test/changed.py --shell    # the same as SEL_* assignments, for run.sh --changed
    python3 test/changed.py --base HEAD~1
    python3 test/changed.py --json     # for engineer.py's deploy: stages, why, page

The change is the worktree (committed, staged, unstaged and untracked)
against its merge-base with main, so it is what this branch would deploy.

Stages: parse, structure and the version check always run (seconds). deck
runs for deck.html; audit, behaviour and keyboard for index.html; perf only
for the scenarios whose code moved: each top-level section of the page (a
`/* ===== name` header in the script, `/* ----- name` in the style) is
mapped below to the scenarios that exercise it, SHARED ones to all of them.
A section missing from the map runs all of perf, and says so: the map is
kept by hand, so a new section is measured until someone places it.

A hunk that only moves APP_VERSION is the version check's business, not the
page's: every commit bumps it, and it would otherwise cost the whole suite.

This narrows what an engineer runs while working. It never stands in for
the full run before a hand-over, nor for the deploy's (see CLAUDE.md).
"""
import argparse
import json
import os
import re
import subprocess
import sys

UI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(UI)

LIST = ["scroll", "scroll-up", "scroll-desktop", "rail"]
IDLE = ["idle", "idle-desktop"]
EDIT = ["open", "type", "morph", "morph-desktop"]
CHAT = ["chat-thread", "eng-thread"]
DOCK = ["dock-stream", "dock-scroll"]
ALL = "*"

# section name -> the perf scenarios it can slow down (ALL: every one; []:
# none measures it). The script's top-level sections first, then the style's.
PERF = {
    # the script
    "constants": ALL, "storage": ALL, "state": ALL, "helpers": ALL, "config / api": ALL,
    "markdown (a deliberately small subset)": ALL, "load": ALL, "kinds": ALL, "kinds by role": ALL,
    "shareable state": ALL, "pages": ALL, "wiring": ALL, "go": ALL,
    "sound": [], "media": [], "the mirror": [], "offline: the outbox": [],
    "the other writers": IDLE, "server push": IDLE, "the cheap catch-up": IDLE,
    "what arrived while you were away": LIST, "activity heatmap": ["idle-desktop", "scroll-desktop"],
    "filter + search": ["search"] + LIST, "day view + dialogs": [], "the list": LIST + ["search", "open", "morph", "morph-desktop"],
    "date scrubber": LIST, "picking several entries": [], "editor": EDIT, "drafts": EDIT,
    "stats": [], "the task board": [], "the media view": [], "the reports": [], "the server's features": [], "the blog post's shares": [], "the calendar": [],
    "topic trends": [], "templates": [], "measurements": [], "the series explorer": [],
    "quick capture": [], "saved views": [], "ambient mode": IDLE,
    "the rail's numbers": IDLE + ["rail"], "config dialog": [], "the app's own updates": [], "row swipe actions": LIST,
    "the stack": ["idle-desktop", "scroll-desktop", "open"], "moving a task on": [],
    "[[link]] autocomplete": ["type"], "#tag autocomplete": ["type"], "/command autocomplete": ["type"],
    "@role autocomplete": ["type"],
    "link graph": [], "stellar cartography": ["stars-chart", "stars-pan", "open"],
    "pickers": ["palette"], "voice": [], "reading aloud": [], "the computer": CHAT + DOCK,
    "the chat dock": DOCK, "voice in the chats": ["chat-thread"], "speech queue": [], "hold to talk": ["chat-thread"],
    "plot a course": ["course-zoom", "course-turn"], "crew reports": [], "crew notes": [], "open questions": CHAT, "crew notes, the rule": [], "the yeoman's proposals": [], "engineers": ["eng-thread"],
    "alert conditions": IDLE,
    # Secret entries: its row flag and placeholder are drawn by the list, its chip by the editor
    "classified": LIST + EDIT,
    "keyboard": ["palette", "open"],
    # the style
    "scrollbars": ALL, "header": ALL, "layout": ALL, "collapsible columns": ALL, "focus mode": ALL,
    "motion": ALL, "overlay": ALL, "phones / small tablets": ALL,
    "sidebar controls": ["idle-desktop", "scroll-desktop", "search"], "result list": LIST + ["search"],
    "[[link]] autocomplete (css)": ["type"], "rendered markdown": EDIT + CHAT + DOCK, "the chat dock (css)": DOCK, "outline folding": EDIT,
    "the task state table": EDIT, "read pane": EDIT, "the stopwatch": EDIT, "a task's CalDAV side": EDIT,
    "backlinks": EDIT, "media & files": EDIT, "editor action bar": EDIT, "date + time picker": EDIT,
    "the stack: side panels": ["idle-desktop", "scroll-desktop", "open"], "confirm dialog": [],
    "keyboard cheat sheet": [], "task board": [], "the calendar (css)": [],
    "one entry, anywhere in the calendar": [], "the year: twelve small months": [],
    "the week: seven columns of entries": [], "the day: twenty-four hours": [], "the schedule lane": [],
    "the computer's marks, shared": CHAT, "one chat": CHAT, "search bar (above the results, both layouts)": ["search"],
    # the page outside the sections: <head> with its early script, the markup,
    # and each block's lines before its first header (:root's variables)
    "<head>": ALL, "markup": ALL, "<style>": ALL, "<script>": ALL,
}
# names the style shares with the script, told apart where they map differently
CSS_ALIAS = {"[[link]] autocomplete": "[[link]] autocomplete (css)", "the calendar": "the calendar (css)"}

# The Chromium checks outside run.sh that a section's change calls for
# (CLAUDE.md lists them): said, not run - each builds a scratch server.
ADVICE = {
    "editor": ["test/editor.py"], "drafts": ["test/editor.py"], "editor action bar": ["test/editor.py"],
    "read pane": ["test/editor.py"],
    "plot a course": ["test/turn.py"],
    "classified": ["test/classified.py"],
    "the computer": ["test/back.py", "test/qa_chat.py"], "one chat": ["test/qa_chat.py"],
    "engineers": ["test/back.py", "test/qa_chat.py"], "voice in the chats": ["test/qa_chat.py"],
    "the computer's marks, shared": ["test/qa_chat.py"],
    "speech queue": ["test/speech.py"], "hold to talk": ["test/ptt.py"],
    "the mirror": ["test/offline.py"], "offline: the outbox": ["test/offline.py"], "config / api": ["test/offline.py"],
    "the other writers": ["test/offline.py"], "server push": ["test/offline.py"],
    "the cheap catch-up": ["test/offline.py"], "the app's own updates": ["test/update.py"],
    "the server's features": ["test/features_ui.py"],
    "media": ["test/recording.py", "test/e2e.py"], "media & files": ["test/recording.py"],
    "voice": ["test/e2e.py"],
    "pages": ["test/buttons.py", "test/back.py"], "shareable state": ["test/back.py"], "wiring": ["test/buttons.py"],
    "header": ["test/buttons.py"], "phones / small tablets": ["test/buttons.py"], "overlay": ["test/buttons.py"],
    "confirm dialog": ["test/buttons.py"], "markup": ["test/buttons.py"],
    "the calendar": ["test/dates.sh"], "the calendar (css)": ["test/dates.sh"], "date scrubber": ["test/dates.sh"],
    "the rail's numbers": ["test/dates.sh"],
}
FILE_ADVICE = [
    (r"^lcars-ui/sw\.js$", ["test/offline.py", "test/update.py"]),
    (r"^lcars_media\.h$", ["test/recording.py"]), (r"^lcars_caldav\.h$", ["test/caldav.py"]),
    (r"^lcars_say\.h$", ["test/transcribe.py"]), (r"^lcars_metrics\.h$", ["test/metrics.py"]),
    (r"^lcars_ui_files\.h$", ["test/uigzip.py"]),
    (r"^lcars_http\.h$", ["test/framing.py", "test/logins.py", "test/api.py"]), (r"^lcars_logins\.h$", ["test/logins.py"]),
    (r"\.(c|h)$|^Makefile$", ["make check", "make lcars-cli"]),
    (r"^scripts/(crew|crew_tool)\.py$|^crew/", ["scripts/test_crew.py"]),
    (r"^scripts/seat\.py$", ["scripts/test_seat.py"]),
    (r"^scripts/engineer\.py$", ["scripts/test_seat.py", "scripts/test_reap.py", "scripts/test_no1_inbox.py",
                                 "scripts/test_engineer_model.py", "scripts/test_queue.py",
                                 "scripts/test_brief.py", "scripts/test_ctx.py", "scripts/test_deploy_suite.py",
                                 "scripts/test_events.py"]),
    (r"^scripts/no1\.py$", ["scripts/test_no1.py"]),
]

HEADER = re.compile(r"/\* (?:={5,}|-{5,}) (.*?)(?: (?:={3,}|-{3,}).*)?(?: \*/)?$")


def sections(lines):
    """index.html's lines (1-based list index + 1) -> the top-level section
    each one is in. In the style a `/* -----` header is top level; in the
    script those are subsections, and only `/* =====` counts. `end NAME`
    closes NAME and resumes what was open before it (speech queue inside
    voice in the chats)."""
    out, cur, region, opened = [], "<head>", "head", {}
    for ln in lines:
        s = ln.strip()
        if region == "head" and s == "<style>":
            region, cur = "css", "<style>"
        elif region == "css" and s == "</style>":
            region, cur = "markup", "markup"
        elif region == "markup" and s == "<script>":
            region, cur = "js", "<script>"
        m = HEADER.match(ln)
        if m and (region == "css" or (region == "js" and ln.startswith("/* ====="))):
            name = m.group(1)
            if region == "css":
                name = CSS_ALIAS.get(name, name)
            if name.startswith("end ") and name[4:] in opened:
                cur = opened[name[4:]]
            else:
                opened[name] = cur
                cur = name
        out.append(cur)
    return out


def select(changes, page_lines=None):
    """changes: {path from the repo root: [(first, last) new-file line ranges]
    or None (the whole file, or a file gone)} -> (stages {name: bool},
    perf scenarios [] for all, reasons [str], advice [str])."""
    st = dict(deck=False, audit=False, behaviour=False, keyboard=False, perf=False)
    scen, why, adv, full = set(), [], [], None
    page = sections(page_lines) if page_lines is not None else None

    def need(*names, reason):
        for n in names:
            st[n] = True
        why.append(reason)

    for path, ranges in sorted(changes.items()):
        for pat, tests in FILE_ADVICE:
            if re.search(pat, path):
                adv.extend(tests)
        if path in ("lcars-ui/test/run.sh", "lcars-ui/test/changed.py", "lcars-ui/test/test_changed.py",
                    "lcars-ui/test/esbuild", "lcars-ui/test/qjs"):
            full = path
        # crew/architect.md carries DECK_API_DOC verbatim, which deckboot.js checks
        elif path in ("lcars-ui/deck.html", "lcars-ui/test/deckboot.js", "crew/architect.md") or path.startswith(("lcars-ui/vendor/three", "lcars-ui/crew/")):
            need("deck", reason=f"{path}: deck")
        elif path in ("lcars-ui/test/tests.js", "lcars-ui/test/shim.js", "lcars-ui/test/api.js", "lcars-ui/test/gen.py"):
            need("behaviour", reason=f"{path}: behaviour")
        elif path == "lcars-ui/test/keyboard.py":
            need("keyboard", reason=f"{path}: keyboard")
        elif path == "lcars-ui/test/audit.py":
            need("audit", reason=f"{path}: audit")
        elif path in ("lcars-ui/test/perf.py", "lcars-ui/test/synth.py"):
            need("perf", reason=f"{path}: all of perf")
            scen.add(ALL)
        elif path == "lcars-ui/index.html":
            if ranges is None or page is None:
                need("audit", "behaviour", "keyboard", "perf", reason=f"{path}: the whole page")
                scen.add(ALL)
                continue
            names = []
            for lo, hi in ranges:
                for i in range(max(lo, 1), min(hi, len(page)) + 1):
                    if page[i - 1] not in names:
                        names.append(page[i - 1])
            if not names:
                continue
            need("audit", "behaviour", "keyboard", reason=f"{path}: " + ", ".join(names))
            for n in names:
                adv.extend(ADVICE.get(n, []))
                p = PERF.get(n)
                if p is None:
                    why.append(f"section {n!r} is not in changed.py's map: all of perf")
                    p = ALL
                if p == ALL:
                    scen.add(ALL)
                else:
                    scen.update(p)
        elif path == "lcars-ui/test/killclean.py":
            adv.append("scripts/test_reap.py")
            why.append(f"{path}: the tests' scratch on a kill; test_reap.py checks it")
        elif re.match(r"lcars-ui/test/[^/]+\.(py|sh)$", path):
            # a Chromium or server check outside run.sh: itself, by hand
            adv.append(path[len("lcars-ui/"):])
            why.append(f"{path}: not a run.sh stage")
        elif path == "lcars-ui/sw.js":
            why.append(f"{path}: parsed with the page; offline.py and update.py test it")
        elif path.startswith("lcars-ui/") and path.endswith((".html", ".js")) and "/test/" not in path:
            # a page or script of the UI no stage knows by name: everything
            full = path
    if full:
        st = {k: True for k in st}
        return st, [], [f"{full}: the full run"], sorted(set(adv))
    if scen:
        st["perf"] = True
    return st, ([] if ALL in scen else sorted(scen)), why, sorted(set(adv), key=adv.index)


def git(*args, root=None):
    return subprocess.run(["git", *args], cwd=root or ROOT, capture_output=True, text=True, check=True).stdout


def worktree_changes(base, root=None):
    """{path: ranges or None} for the worktree against base, untracked
    files included. Hunks that only change the APP_VERSION line are dropped."""
    mb = git("merge-base", base, "HEAD", root=root).strip()
    changes = {}
    path, hunk, lines = None, None, []

    def close():
        nonlocal hunk, lines
        if hunk and not all("const APP_VERSION = " in ln for ln in lines):
            changes.setdefault(path, []).append(hunk)
        hunk, lines = None, []

    for ln in git("diff", "-U0", "--no-color", "--no-renames", mb, "--", root=root).splitlines():
        if ln.startswith("diff --git "):
            close()
            path = ln.split(" b/", 1)[1]
            if path != "lcars-ui/index.html":
                changes[path] = []  # only the page is looked into by line
        elif ln.startswith("@@"):
            close()
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", ln)
            first, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            # a pure deletion (n == 0) sits after line `first`: that line's section
            hunk = (first, first + n - 1) if n else (max(first, 1), max(first, 1))
        elif hunk and ln[:1] in "+-":
            lines.append(ln[1:])
    close()
    for p in git("ls-files", "--others", "--exclude-standard", root=root).splitlines():
        changes[p] = None
    return mb, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    ap.add_argument("--shell", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    say = (lambda s: print(s, file=sys.stderr)) if a.shell else (lambda s: None) if a.json else print
    try:
        mb, changes = worktree_changes(a.base)
    except (subprocess.CalledProcessError, OSError) as e:
        say(f"   cannot diff against {a.base} ({e}): the full run")
        if a.shell:
            print("SEL_DECK=1 SEL_AUDIT=1 SEL_BEHAVIOUR=1 SEL_KB=1 SEL_PERF=1 SEL_PERF_ONLY=''")
        if a.json:
            print(json.dumps({"full": True, "why": [f"cannot diff against {a.base}: {e}"]}))
        return
    with open(os.path.join(UI, "index.html"), encoding="utf-8") as f:
        page = f.read().split("\n")
    st, only, why, adv = select(changes, page)
    say(f"   {len(changes)} files changed since {a.base} ({mb[:8]})")
    for w in why:
        say("   " + w)
    on = [k for k, v in st.items() if v]
    say("   runs: parse, structure, version" + "".join(", " + k for k in on)
        + (f" ({' '.join(only)})" if st["perf"] and only else ""))
    if adv:
        say("   also run by hand: " + ", ".join(adv))
    if a.json:
        # page: index.html changed beyond APP_VERSION; full: every stage on
        print(json.dumps({"base": mb, "files": len(changes), "page": "lcars-ui/index.html" in changes,
                          "full": all(st.values()), "runs": ["parse", "structure", "version"] + on,
                          "perf_only": only, "why": why}))
    if a.shell:
        print(" ".join(f"SEL_{k.upper() if k != 'keyboard' else 'KB'}={int(v)}" for k, v in st.items())
              + " SEL_PERF_ONLY='" + " ".join(only) + "'")


if __name__ == "__main__":
    main()
