#!/bin/bash
# Back up the LCARS journal into Logseq, one journal page per day.
#
# `lcars-cli logseq export` only ever *adds* `HH:MM [kind] text` blocks that
# the day's page does not already have, so this script is safe to run as
# often as you like: a day that is already up to date costs a few queries and
# writes nothing. That is what makes it a cron job rather than a chore.
#
# Two days are exported on every run, not one:
#   - today, for everything written so far;
#   - yesterday, because an entry made just before local midnight can still
#     be arriving (or being edited) after the day rolled over, and the run
#     that covered "today" already happened.
#
# Requires: Logseq running with its HTTP API server enabled (Settings ->
# Features -> HTTP APIs -> Server), and an API token created there.
#
#   LOGSEQ_TOKEN=... scripts/logseq-export.sh
#
# Reads .env (LCARS_URL, LCARS_AUTH_USER, LCARS_AUTH_PASS) if present, so by
# default it pulls entries from whichever server that file points at - the
# VPS. Reading production is what the backup is *for*; nothing here writes to
# it. Override with LCARS_URL=http://127.0.0.1:8080 for a local run.
#
# Install as a user timer (runs every 30 minutes while you are logged in):
#
#   systemd-run --user --on-calendar='*:0/30' --unit=lcars-logseq-export \
#       --setenv=LOGSEQ_TOKEN="$LOGSEQ_TOKEN" \
#       ~/Workspace/lcars/scripts/logseq-export.sh
#
# ...or add it to crontab -e:
#
#   */30 * * * * LOGSEQ_TOKEN=... ~/Workspace/lcars/scripts/logseq-export.sh >> ~/.local/state/lcars-logseq.log 2>&1

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$REPO_DIR/lcars-cli"

if [ -f "$REPO_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_DIR/.env"
  set +a
fi

if [ ! -x "$CLI" ]; then
  echo "logseq-export: $CLI not built - run 'make lcars-cli'" >&2
  exit 1
fi

if [ -z "${LOGSEQ_TOKEN:-}" ]; then
  echo "logseq-export: LOGSEQ_TOKEN is not set (Logseq Settings -> Features -> HTTP APIs)" >&2
  exit 1
fi

TODAY="$(date +%F)"
YESTERDAY="$(date -d yesterday +%F)"

echo "[$(date +'%F %T')] exporting $YESTERDAY..$TODAY to Logseq"
exec "$CLI" logseq export --since "$YESTERDAY" --until "$TODAY" "$@"
