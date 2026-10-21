#!/bin/bash
# Single entry point for the lcars-linker agent: the yeoman's nightly linker
# pass (crew/yeoman-linker.md, run by scripts/crew.py), and the hourly
# `measure` from cron. Moved here from ~/.claude/scripts in 0.143.0.
#
# Two jobs:
#   1. Keep credentials out of the agent's command lines. Sourcing ~/.env is
#      done here, so the agent never writes `set -a; . ~/.env` (which the
#      command analyzer rejects) and never has the password in a visible argv.
#   2. Enforce the rule the agent is also told in prose: it may READ the journal
#      freely, but the only way it can WRITE is `apply`, which splices links by
#      character offset and logs every change. `set`, `rm`, `new` and `restore`
#      are unreachable from here on purpose — an agent cannot retype a body.
#
# This is the captain's login, not the crew's: the linker edits the captain's
# own entries, which the crew login (writes only crew_*) cannot, and must
# not be widened to. crew.py allowlists this file as a single prefix for the
# linker pass (--allowedTools), which is what lets it run headless under
# --permission-mode dontAsk.
set -uo pipefail

# LCARS_LINK_ENV and LCARS_LINK_URL exist for a scratch run on a laptop; on
# the VPS both are unset and this is ~/.env and the local server.
set -a; . "${LCARS_LINK_ENV:-$HOME/.env}"; set +a
export LCARS_URL="${LCARS_LINK_URL:-http://127.0.0.1:8080}"

ENGINE="$(dirname "$(readlink -f "$0")")/lcars_linker.py"
# The one binary's link the server makes at start (the copied build it
# replaced retired in 0.279.2).
CLI="${LCARS_CLI:-$HOME/lcars/bin/lcars-cli}"
SCRATCH="$HOME/.lcars-linker"
mkdir -p "$SCRATCH"

cmd="${1:-}"
shift || true

case "$cmd" in
  health)
    exec curl -sf -m 10 "$LCARS_URL/health"
    ;;
  today)
    # The box may run in another zone than its owner (the VPS is seven hours
    # behind), so a bare `date` is regularly the wrong calendar day: the
    # owner's is LCARS_TZ, from the environment or ~/.env (a timer does not
    # source it), else the box's own - crew_tool.py's crew_zone, in sh.
    tz="${LCARS_TZ:-$(sed -n "s/^\(export \)\{0,1\}LCARS_TZ=[\"']\{0,1\}\([^\"']*\).*/\2/p" "$HOME/.env" 2>/dev/null | tail -n 1)}"
    [ -n "$tz" ] && exec env TZ="$tz" date +%F
    exec date +%F
    ;;
  scan)
    exec python3 "$ENGINE" scan "$@"
    ;;
  apply)
    exec python3 "$ENGINE" apply "$@"
    ;;
  measure)
    # Fills value_float/value_int on series kinds (sleep, drive, gym, vocab) so the
    # web UI can chart them. Arithmetic only; writes only zero or own values.
    exec python3 "$ENGINE" measure "$@"
    ;;
  cli)
    # Read-only subcommands only. Anything that mutates is refused here even if
    # the agent is somehow talked into asking for it.
    sub="${1:-}"
    case "$sub" in
      list|get|stats|kinds) exec "$CLI" "$@" ;;
      *)
        echo "lcars-link.sh: '$sub' is not a read-only subcommand." >&2
        echo "Writes go through 'lcars-link.sh apply' so they are spliced by" >&2
        echo "offset and logged. Allowed: list, get, stats, kinds." >&2
        exit 2
        ;;
    esac
    ;;
  *)
    cat >&2 <<'USAGE'
usage: lcars-link.sh <command>

  health                     is the LCARS server up
  scan  --date D --out F     propose candidate links for a day
  apply --scan F --decisions F [--dry-run] [--verbose]
  measure [--dry-run]        fill value fields on sleep/drive/gym/vocab rows
                             (--dry-run prints each write, makes none)
  cli   list|get|stats|kinds ...   read the journal

Scratch files belong in ~/.lcars-linker/ (scan --out writes there; Read it back).
USAGE
    exit 2
    ;;
esac
