#!/usr/bin/env python3
"""run.sh --changed picks the right stages: test/changed.py on sample changes.

    python3 test/test_changed.py      (~1s; run by run.sh)

The page's sections are found by name in the real index.html, so the cases
do not break when lines move; the last case builds a scratch git repo with
a deb branch and checks the diff it reads, APP_VERSION and untracked files
included.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changed  # noqa: E402

UI = changed.UI
PAGE = open(os.path.join(UI, "index.html"), encoding="utf-8").read().split("\n")
SEC = changed.sections(PAGE)
fails = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


def line_in(name, region="js"):
    """a line number inside section `name` (in the script, or the style)"""
    css_end = next(i for i, ln in enumerate(PAGE) if ln.strip() == "</style>")
    for i, s in enumerate(SEC):
        if s == name and (i > css_end) == (region == "js"):
            return i + 2  # the line after its header
    raise KeyError(name)


def stages(changes):
    st, only, why, adv = changed.select(changes, PAGE)
    return {k for k, v in st.items() if v}, only, why, adv


def case(what, changes, want, only=None, advice=()):
    got, o, why, adv = stages(changes)
    check(got == set(want), f"{what}: stages {sorted(got)} (want {sorted(want)})")
    if only is not None:
        check(o == sorted(only), f"{what}: perf scenarios {o or 'all'} (want {sorted(only) or 'all'})")
    for a in advice:
        check(a in adv, f"{what}: says to run {a}")
    return why


case("docs and CHANGELOG only", {"CHANGELOG.md": [], "docs/ops/engineer-time.md": [], "TODO.md": []}, [])
case("scripts only", {"scripts/engineer.py": []}, [], advice=["scripts/test_seat.py", "scripts/test_queue.py"])
case("C only", {"lcars_http.h": [], "lcars.c": []}, [], advice=["make check", "test/framing.py"])
case("the deck", {"lcars-ui/deck.html": []}, ["deck"])
case("the behaviour suite's tests", {"lcars-ui/test/tests.js": []}, ["behaviour"])
case("keyboard.py", {"lcars-ui/test/keyboard.py": []}, ["keyboard"])
case("targets.py", {"lcars-ui/test/targets.py": []}, ["screens"])
case("axe.py", {"lcars-ui/test/axe.py": []}, ["screens"])
case("perf.py", {"lcars-ui/test/perf.py": []}, ["perf", "screens"], only=[])
case("rules.py, whose CASE_OK targets.py reads", {"lcars-ui/test/rules.py": []}, ["audit", "screens"])
case("ui-rules.md", {"docs/design/ui-rules.md": []}, ["audit"])
case("synth.py", {"lcars-ui/test/synth.py": []}, ["perf"], only=[])
case("the course", {"lcars-ui/index.html": [(line_in("plot a course"), line_in("plot a course"))]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=["course-zoom", "course-turn"])
case("the calendar: no frame measured", {"lcars-ui/index.html": [(line_in("the calendar"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens"], advice=["test/dates.sh"])
case("the editor", {"lcars-ui/index.html": [(line_in("editor"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=["morph", "morph-desktop", "open", "type"], advice=["test/editor.py"])
case("a chat's style", {"lcars-ui/index.html": [(line_in("one chat", "css"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=["chat-thread", "eng-thread"], advice=["test/qa_chat.py"])
case("the engineers", {"lcars-ui/index.html": [(line_in("engineers"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=["eng-thread", "rooms-room"], advice=["test/back.py"])
case("the speech queue, inside voice in the chats", {"lcars-ui/index.html": [(line_in("speech queue"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens"], advice=["test/speech.py"])
case("a shared helper: all of perf", {"lcars-ui/index.html": [(line_in("helpers"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=[])
case("two areas at once", {"lcars-ui/index.html": [(line_in("plot a course"),) * 2, (line_in("engineers"),) * 2]},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=["course-zoom", "course-turn", "eng-thread", "rooms-room"])
case("the page and the deck", {"lcars-ui/index.html": [(line_in("stats"),) * 2], "lcars-ui/deck.html": []},
     ["deck", "audit", "behaviour", "keyboard", "screens"])
case("the page, untracked or whole", {"lcars-ui/index.html": None},
     ["audit", "behaviour", "keyboard", "screens", "perf"], only=[])
case("run.sh itself: the full run", {"lcars-ui/test/run.sh": [], "README.md": []},
     ["deck", "audit", "behaviour", "keyboard", "screens", "perf"], only=[])
case("a new UI file nobody knows: the full run", {"lcars-ui/foo.js": None},
     ["deck", "audit", "behaviour", "keyboard", "screens", "perf"], only=[])
case("a check outside run.sh: itself, by hand", {"lcars-ui/test/qa_chat.py": []}, [], advice=["test/qa_chat.py"])
case("the deck's crew models", {"lcars-ui/crew/male.glb": None}, ["deck"])
case("sw.js: the quick checks, and offline.py and update.py by hand", {"lcars-ui/sw.js": []}, [],
     advice=["test/offline.py", "test/update.py"])

# a section the map has never heard of runs all of perf, and says why
fake = PAGE[:]
k = line_in("the calendar")
fake[k - 1] = "/* ===================== a section from tomorrow ====================="
st, only, why, _ = changed.select({"lcars-ui/index.html": [(k + 1, k + 1)]}, fake)
check(st["perf"] and only == [] and any("not in changed.py's map" in w for w in why),
      "an unmapped section: all of perf, said")

# every section of today's page is placed (a warning, not a failure: an
# unplaced one is measured in full, which is safe)
unplaced = sorted({s for s in SEC if s not in changed.PERF})
print(("  ok   every section of the page is in the map" if not unplaced
       else "  note sections not in changed.py's map (all of perf for them): " + ", ".join(unplaced)))

# the diff as git gives it: a scratch repo with a deb branch
tmp = tempfile.mkdtemp()
try:
    def g(*a):
        subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True)
    g("init", "-q", "-b", "deb")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    os.makedirs(os.path.join(tmp, "lcars-ui"))
    shutil.copy(os.path.join(UI, "index.html"), os.path.join(tmp, "lcars-ui", "index.html"))
    open(os.path.join(tmp, "CHANGELOG.md"), "w").write("## 0.1.0\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "eng/x")
    p = os.path.join(tmp, "lcars-ui", "index.html")
    lines = PAGE[:]
    v = next(i for i, ln in enumerate(lines) if "const APP_VERSION = " in ln)
    lines[v] = lines[v].replace("const APP_VERSION = \"", "const APP_VERSION = \"9")
    open(p, "w").write("\n".join(lines))
    open(os.path.join(tmp, "CHANGELOG.md"), "w").write("## 9.1.0\n## 0.1.0\n")
    g("commit", "-qam", "a version bump only")
    _, ch = changed.worktree_changes("deb", root=tmp)
    check(set(ch) == {"CHANGELOG.md"}, f"a version bump: the page is not counted as changed ({sorted(ch)})")
    c = line_in("plot a course")
    lines[c] += " // moved"
    open(p, "w").write("\n".join(lines))  # unstaged, on purpose
    open(os.path.join(tmp, "NOTES.md"), "w").write("new\n")  # untracked
    _, ch = changed.worktree_changes("deb", root=tmp)
    check(ch.get("lcars-ui/index.html") == [(c + 1, c + 1)], f"an unstaged edit: its line ({ch.get('lcars-ui/index.html')})")
    check("NOTES.md" in ch, "an untracked file is counted")
    st, only, _, _ = changed.select(ch, lines)
    check(st["perf"] and only == ["course-turn", "course-zoom"], f"from git: the course's scenarios ({only})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"test_changed: {len(fails)} failures")
sys.exit(1 if fails else 0)
