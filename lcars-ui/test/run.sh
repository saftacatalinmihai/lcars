#!/bin/sh
# Every check that stands behind the UI, in the order that fails fastest.
#
#   ./test/run.sh             every stage: before a hand-over, and what a deploy runs
#   ./test/run.sh --changed   only the stages this branch's change needs, by the
#                             files and page sections it touches against deb
#                             (test/changed.py; docs/ops/engineer-time.md)
#
# esbuild parses the page script, QuickJS runs it against a DOM shim small
# enough to fit (test/shim.js) and a fake API backed by real rows read out of
# $LCARS_TEST_DB (default: the checkout's lcars.db, see test/gen.py; with
# none, a synthetic journal from test/synth.py).  The
# database is opened read-only and immutable; nothing here can write to it.
set -e
cd "$(dirname "$0")/.."
T=test

# --changed: test/changed.py sets SEL_* from the diff against deb
# (CHANGED_BASE: another ref, the deploy's live branch); the full
# run leaves them all on. A stage left out says so where it would have run.
SEL_DECK=1 SEL_AUDIT=1 SEL_BEHAVIOUR=1 SEL_KB=1 SEL_PERF=1 SEL_PERF_ONLY=
if [ "${1:-}" = --changed ]; then
  echo "== what the change needs (--changed, against deb) =="
  eval "$(python3 "$T/changed.py" --shell --base "${CHANGED_BASE:-deb}")"
fi
off() { echo "   skipped (--changed: not touched)"; }

echo "== javascript parses =="
python3 - index.html > "$T/page.js" <<'PY'
import re, sys
s = open("index.html", encoding="utf-8").read()
sys.stdout.write("\n".join(re.findall(r"<script>(.*?)</script>", s, re.S)))
PY
"$T/esbuild" --log-level=warning --target=es2020 "$T/page.js" > /dev/null
"$T/esbuild" --log-level=warning --target=es2020 sw.js > /dev/null
echo "   ok ($(wc -l < "$T/page.js") lines)"
rm -f "$T/page.js"

echo "== structure (ids, balance, markup) =="
python3 "$T/check.py" index.html

# the selector itself, on sample diffs (a second)
echo "== --changed picks the stages (test/test_changed.py) =="
if out=$(python3 "$T/test_changed.py"); then
  echo "$out" | grep -E "^(  note|test_changed:)"
else
  echo "$out" | grep -E "^(  FAIL|test_changed:)"
  exit 1
fi

# The three slow stages below (deck boot, behaviour, keyboard) need nothing
# from each other, so they start together, each into a file of its own, and
# are printed in this order as each one finishes: the same lines as running
# them one after another, in about the time of the slowest. A stage that
# fails stops the run where it would have stopped, after its own output.
tmp=$(mktemp -d "${TMPDIR:-/tmp}/lcars-run.XXXXXX")
pids=""
trap 'kill $pids 2>/dev/null || :; rm -rf "$tmp"' EXIT
# a shell runs its EXIT trap on exit, not when a signal ends it: the tool's
# timeout (SIGTERM) or a closed terminal left the stages' outputs in /tmp,
# which is RAM on the VPS. Exiting on them runs the trap (128 + the signal).
trap 'exit 143' TERM
trap 'exit 129' HUP
start() { name=$1; shift; "$@" > "$tmp/$name" 2>&1 & eval "pid_$name=\$!"; pids="$pids $!"; }
finish() {
  eval "pid=\$pid_$1"
  if wait "$pid"; then cat "$tmp/$1"; else rc=$?; cat "$tmp/$1"; exit $rc; fi
}

# The deck cannot be booted in headless Chromium here, so its script is run
# in node against stand-ins for three.js and the DOM: a name used before its
# declaration (0.119.0's crewReal) stopped it loading on every device.
deck() {
  if [ "$SEL_DECK" = 0 ]; then
    off
  elif command -v node > /dev/null; then
    node "$T/deckboot.js" deck.html
  else
    echo "   skipped: node is not installed"
  fi
}

# QuickJS exits 0 whatever the suite found (failures are only printed), and
# a pipe's status is its last command's, so the verdict is read from the
# output: a pass is a RESULT: PASS line and no FAIL, THREW or TIMED line.
behaviour() {
  [ "$SEL_BEHAVIOUR" = 0 ] && { off; return; }
  python3 "$T/gen.py" > /dev/null || return
  rc=0
  "$T/qjs" "$T/run.js" > "$tmp/qjs.out" 2>&1 || rc=$?
  # the bundle embeds real journal rows as a fixture; it is rebuilt every run
  rm -f "$T/run.js"
  grep -E "^(section|TOTAL|RESULT|  FAIL|SUITE|TIMED)" "$tmp/qjs.out" || :
  [ $rc = 0 ] || { echo "   FAIL: qjs exited $rc"; tail -5 "$tmp/qjs.out"; return 1; }
  grep -q "^RESULT: PASS" "$tmp/qjs.out" || { echo "   FAIL: no RESULT: PASS line"; return 1; }
  ! grep -qE "^(  FAIL|SUITE .* THREW|TIMED)" "$tmp/qjs.out"
}

# Every text field at a phone's size, in every view, palette row, the editor
# and the reader: reachable, 16px or more (no iOS zoom), its focus kept
# (test/keyboard.py, ~15s in parallel shards, stubbed API). KB=0 skips it.
keyboard() {
  if [ "$SEL_KB" = 0 ]; then
    off
  elif [ "${KB:-1}" = 0 ]; then
    echo "   skipped (KB=0)"
  elif ! python3 -c "import playwright" 2>/dev/null; then
    echo "   skipped: playwright is not installed"
  else
    # keyboard.py's own exit status is the verdict, not grep's
    rc=0
    python3 "$T/keyboard.py" > "$tmp/kb.out" 2>&1 || rc=$?
    grep -E "^(keyboard:|  FAIL)" "$tmp/kb.out" || :
    return $rc
  fi
}

# A fresh clone has no journal: the behaviour suite then runs on a synthetic
# one (test/synth.py, which it must pass on too), made for this run, unless
# $LCARS_TEST_DB names a copy.
if [ "$SEL_BEHAVIOUR" != 0 ] && [ -z "${LCARS_TEST_DB:-}" ] && [ ! -f ../lcars.db ]; then
  echo "== no lcars.db: the suite on a synthetic journal (test/synth.py) =="
  python3 "$T/synth.py" "$tmp/synth.db" > /dev/null
  export LCARS_TEST_DB="$tmp/synth.db"
fi

start deck deck
start behaviour behaviour
start keyboard keyboard

echo "== deck.html starts (top level, demo boot, frames) =="
finish deck

# CHANGELOG.md is the version's home; the page carries a copy to show it
echo "== version matches CHANGELOG.md =="
log=$(grep -m1 -oE '^## [0-9]+\.[0-9]+\.[0-9]+' ../CHANGELOG.md | cut -c4-)
page=$(grep -m1 -oE 'const APP_VERSION = "[^"]+"' index.html | cut -d'"' -f2)
if [ -z "$log" ] || [ "$log" != "$page" ]; then
  echo "   FAIL: CHANGELOG.md says ${log:-nothing}, index.html APP_VERSION says ${page:-nothing}"
  exit 1
fi
echo "   ok ($page)"

# audit.py's exit status is the verdict (it was once piped to tail, whose
# status hid a failing check for a release)
echo "== static audit (fonts, aria, contrast, constraints) =="
if [ "$SEL_AUDIT" = 0 ]; then
  off
elif out=$(python3 "$T/audit.py"); then
  echo "$out" | tail -1
else
  echo "$out" | grep "FAIL"
  echo "$out" | tail -1
  exit 1
fi

echo "== behaviour =="
finish behaviour

echo "== text fields on a phone: no zoom, focus kept =="
finish keyboard

# The frame budget: 60 fps at p99, in headless Chromium against a synthetic
# journal the size of the real one (see test/perf.py for what is measured and
# why). Its scenarios run four at a time on a laptop (~30s), two at a time
# on the 4-core VPS (~90s; ~1 minute more for each scenario over budget
# that is run again against deb's page); it starts only once the stages
# above are done, so they do not share the cores. PERF=0 skips it while
# iterating; run it before committing a page change.
echo "== frame budget (p99 main-thread <= 16.7ms) =="
if [ "$SEL_PERF" = 0 ]; then
  off
elif [ "${PERF:-1}" = 0 ]; then
  echo "   skipped (PERF=0)"
elif ! python3 -c "import playwright" 2>/dev/null; then
  echo "   skipped: playwright is not installed"
else
  out=$(mktemp)
  status=0
  [ -n "$SEL_PERF_ONLY" ] && echo "   only: $SEL_PERF_ONLY"
  # word-split on purpose: the scenario names
  # shellcheck disable=SC2086
  python3 "$T/perf.py" $SEL_PERF_ONLY > "$out" 2>&1 || status=$?
  grep -E "^(ok|OVER|over|again|budget|RESULT)" "$out" || tail -20 "$out"
  rm -f "$out"
  exit $status
fi
