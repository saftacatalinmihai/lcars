#!/bin/sh
# Publish the landing page: the captain's, by hand (never an engineer's).
# Needs, in the environment and never in the tree:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   (set -a; . ~/.env; set +a)
#   LCARS_LANDING_D1_ID   the D1 database's id (README.md, "Publishing", step 1)
#   LCARS_LANDING_HOST    the custom domain, e.g. lcars.<the zone>
#   LCARS_LANDING_EXPLAINER_URL  the explainer's licensed cut, an https URL
#                         ending .mp4 on the captain's public R2 bucket (its
#                         music is licensed, not MIT, so it is off the tree;
#                         and a Worker asset answers no byte ranges, which
#                         Safari needs to play an mp4). README.md, "The
#                         explainer", says how a new cut goes up.
# What is uploaded is a staged copy of public/ with __SITE__ in its pages
# replaced by https://$LCARS_LANDING_HOST (the share card's absolute URLs)
# and __EXPLAINER__ by $LCARS_LANDING_EXPLAINER_URL,
# and a copy of wrangler.toml with the database id, the custom domain and
# that staged folder filled in. The custom domain makes its own DNS record
# and certificate. --dry-run builds the bundle and uploads nothing;
# LCARS_LANDING_STAGE=DIR stages there and keeps it (test/deploy.py).
set -eu
cd "$(dirname "$0")"
: "${LCARS_LANDING_D1_ID:?set LCARS_LANDING_D1_ID}"
: "${LCARS_LANDING_HOST:?set LCARS_LANDING_HOST}"
: "${LCARS_LANDING_EXPLAINER_URL:?set LCARS_LANDING_EXPLAINER_URL (the explainer mp4 on R2)}"
case "$LCARS_LANDING_HOST" in
*/* | *:* | "" | *[!A-Za-z0-9.-]*) echo "deploy: LCARS_LANDING_HOST is a bare host name, not a URL" >&2; exit 2 ;;
esac
site="https://$LCARS_LANDING_HOST"
# An https URL of an mp4, of the characters a URL path needs and no more:
# it goes into sed's replacement (no # or &) and an HTML attribute (no quote)
case "$LCARS_LANDING_EXPLAINER_URL" in
https://*.mp4) ;;
*) echo "deploy: LCARS_LANDING_EXPLAINER_URL is an https URL ending .mp4" >&2; exit 2 ;;
esac
case "$LCARS_LANDING_EXPLAINER_URL" in
*[!A-Za-z0-9.:/_~-]*) echo "deploy: LCARS_LANDING_EXPLAINER_URL has a character a plain URL path does not" >&2; exit 2 ;;
esac
if [ -n "${LCARS_LANDING_STAGE:-}" ]; then
  stage="$LCARS_LANDING_STAGE"
  rm -rf "$stage/public"
  mkdir -p "$stage"
else
  stage=$(mktemp -d "${TMPDIR:-/tmp}/lcars-landing-XXXXXX")
  trap 'rm -rf "$stage"' EXIT
fi
cp -R public "$stage/public"
# a local copy for the preview (ignored) is never uploaded: the page plays R2's
rm -f "$stage/public/video/explainer.mp4"
for f in "$stage"/public/*.html; do
  sed -e "s#__SITE__#$site#g" -e "s#__EXPLAINER__#$LCARS_LANDING_EXPLAINER_URL#g" "$f" >"$f.new" && mv "$f.new" "$f"
done
if grep -l -e "__SITE__" -e "__EXPLAINER__" "$stage"/public/*.html >/dev/null 2>&1; then
  echo "deploy: a placeholder left in a page" >&2
  exit 1
fi
cfg="$stage/wrangler.toml"
{
  sed -e "s#LCARS_LANDING_D1_ID#$LCARS_LANDING_D1_ID#" \
    -e "s#^main = .*#main = \"$PWD/src/worker.js\"#" \
    -e "s#^directory = .*#directory = \"$stage/public\"#" wrangler.toml
  printf '\n[[routes]]\npattern = "%s"\ncustom_domain = true\n' "$LCARS_LANDING_HOST"
} >"$cfg"
WRANGLER_SEND_METRICS=false npx --yes wrangler@3 deploy -c "$cfg" "$@"
