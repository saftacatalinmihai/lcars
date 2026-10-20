#!/bin/sh
# The release binary's checks before it is attached (open-source-build.md,
# §4). From the checkout's root:
#
#   scripts/release/check.sh ./lcars-static          on the runner: all of it
#   scripts/release/check.sh /w/lcars-static --bare  in a bare debian or
#                                                    fedora container
#
# All: `file` says statically linked, ldd finds nothing, `lcars version` is
# CHANGELOG's top; then, as --bare does, `lcars init` in a temp dir and
# `lcars --data` serving it, here with curl: /health, /ui/ byte-equal to
# lcars-ui/index.html (the embedded copy), deck.html gzipped and inflating
# to its source. --bare has no curl, file or sqlite (the point: the binary
# needs none of them), so the server is asked through the binary's own CLI:
# `lcars cli stats`, `lcars cli new` (a new journal is empty: no seed row)
# and the lcars-cli symlink the server made, which finds that entry. POSIX sh: debian's is dash.
set -eu
BIN=$1
MODE=${2:-}
case $BIN in /*) ;; *) BIN=$PWD/$BIN ;; esac
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok   $*"; }

# LCARS_CHECK_DYNAMIC=1 skips the three static checks: the rest run against
# lcars-embed on a box without docker, to try this script itself.
if [ "$MODE" != --bare ] && [ "${LCARS_CHECK_DYNAMIC:-}" != 1 ]; then
  file "$BIN" | grep -q "statically linked" || fail "file: $(file "$BIN")"
  ok "file: statically linked"
  if ldd "$BIN" >/dev/null 2>&1; then fail "ldd found libraries: $(ldd "$BIN")"; fi
  ok "ldd: not a dynamic executable"
fi
if [ "$MODE" != --bare ]; then
  want=$(sed -n 's/^## \([0-9][0-9.]*\) .*/\1/p' CHANGELOG.md | head -n 1)
  got=$("$BIN" version)
  [ "$got" = "lcars $want" ] || fail "version: '$got', CHANGELOG says $want"
  ok "version: $got"
fi

TMP=$(mktemp -d)
PID=
trap '[ -n "$PID" ] && kill "$PID" 2>/dev/null; rm -rf "$TMP"' EXIT
PORT=18$(( $$ % 900 + 100 ))
"$BIN" init "$TMP/data" --port "$PORT" >"$TMP/init.log" || fail "init: $(cat "$TMP/init.log")"
[ -f "$TMP/data/lcars.env" ] && [ -f "$TMP/data/lcars.db" ] || fail "init made no lcars.env or lcars.db"
[ -d "$TMP/data/media/media" ] || fail "init made no media/media/ (the store the root needs)"
ok "init: lcars.env, lcars.db, media/media/"
cd "$TMP"  # the working directory has no lcars-ui/ and no journal
env -i PATH=/usr/bin:/bin HOME="$TMP" LCARS_EMBED=0 LCARS_CHAT=0 \
  "$BIN" --data "$TMP/data" >"$TMP/server.log" 2>&1 &
PID=$!
cd - >/dev/null

# the login init wrote; lcars.env is KEY=value, a shell can read it
set -a
. "$TMP/data/lcars.env"
set +a
export LCARS_URL=http://127.0.0.1:$PORT
up=
for _ in $(seq 100); do
  if "$BIN" cli stats >"$TMP/stats" 2>/dev/null; then up=1; break; fi
  sleep 0.1
done
[ -n "$up" ] || fail "the server did not answer: $(cat "$TMP/server.log")"
grep -q "^UI: embedded" "$TMP/server.log" || fail "start log: $(grep '^UI:' "$TMP/server.log")"
ok "serving; the start log: $(grep '^UI:' "$TMP/server.log")"
"$BIN" cli list | grep -qx "no entries" || fail "lcars cli list: a new journal is not empty"
"$BIN" cli new --kind personal_log --title "release check" --content "check.sh" >/dev/null \
  || fail "lcars cli new"
"$BIN" cli roles | grep -q "^log  *personal_log " || fail "lcars cli roles: no log role"
ok "lcars cli: stats, an empty journal, a new entry, the roles"
link=$TMP/data/bin/lcars-cli
[ -L "$link" ] || fail "no $link"
"$link" list --kind personal_log | grep -q "release check" || fail "$link list: no entry"
ok "the lcars-cli symlink: the entry"

if [ "$MODE" != --bare ]; then
  curl -sf "$LCARS_URL/health" >/dev/null || fail "/health"
  ok "/health"
  curl -sf "$LCARS_URL/ui/" | cmp -s - lcars-ui/index.html || fail "/ui/ is not lcars-ui/index.html"
  ok "/ui/: byte-equal to lcars-ui/index.html"
  curl -sf -H "Accept-Encoding: gzip" -D "$TMP/h" -o "$TMP/deck.gz" "$LCARS_URL/ui/deck.html"
  grep -qi "^content-encoding: gzip" "$TMP/h" || fail "deck.html not gzipped"
  gzip -dc "$TMP/deck.gz" | cmp -s - lcars-ui/deck.html || fail "deck.html inflates to something else"
  ok "deck.html: gzipped, inflates to its source"
fi
echo "all checks passed"
