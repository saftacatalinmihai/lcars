#!/bin/sh
# The waiting list, read-only: every signup, newest first, from the remote
# D1 database. Needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in the
# environment (set -a; . ~/.env; set +a) and LCARS_LANDING_D1_ID as for
# deploy.sh. Writes nothing: one SELECT.
#   site/landing/list-signups.sh            # a table
#   site/landing/list-signups.sh --json     # wrangler's JSON
#   site/landing/list-signups.sh --count
set -eu
cd "$(dirname "$0")"
: "${LCARS_LANDING_D1_ID:?set LCARS_LANDING_D1_ID (the database's id, from the dashboard or wrangler d1 list)}"
cfg=$(mktemp "${TMPDIR:-/tmp}/lcars-landing-XXXXXX.toml")
trap 'rm -f "$cfg"' EXIT
sed "s/LCARS_LANDING_D1_ID/$LCARS_LANDING_D1_ID/" wrangler.toml | sed 's#"src/worker.js"#"'"$PWD"'/src/worker.js"#; s#"./public"#"'"$PWD"'/public"#' >"$cfg"
case "${1:-}" in
--count) sql="SELECT COUNT(*) AS signups FROM signups" ;;
*) sql="SELECT created, email, COALESCE(use, '') AS use FROM signups ORDER BY created DESC" ;;
esac
json=""
[ "${1:-}" = "--json" ] && json="--json"
WRANGLER_SEND_METRICS=false exec npx --yes wrangler@3 d1 execute lcars-landing --remote -c "$cfg" $json --command "$sql"
