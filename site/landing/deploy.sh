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
#   LCARS_LANDING_PLAUSIBLE  optional: counts visits with Plausible
#                         Analytics. Either the Plausible site's domain (the
#                         script.js tag with data-domain, as the blog's) or
#                         the site's own script URL from its Site
#                         installation page, https://plausible.io/js/pa-<id>.js
#                         (the script since October 2025). Unset: no script,
#                         no Plausible in the CSP, the privacy note says no
#                         analytics.
# What is uploaded is a staged copy of public/ with __SITE__ in its pages
# replaced by https://$LCARS_LANDING_HOST (the share card's absolute URLs)
# and __EXPLAINER__ by $LCARS_LANDING_EXPLAINER_URL; the user manual's page
# (public/manual/, site/manual/build.py's, docs/design/manual.md) with
# __VERSION__ replaced by the console's APP_VERSION, read from
# ../../lcars-ui/index.html ($LCARS_LANDING_APP_PAGE: another copy of it),
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
# Plausible: a tag before </head> in every page, its origin in the CSP, the
# privacy note's line, and the init stub (plausible-init.js, before it in
# document order: both are defer, run in order, landing.js's Signup queued
# until the script is in). Every value is checked to the characters a host or
# a plain path has: it goes into sed's replacement and an attribute.
plausible="${LCARS_LANDING_PLAUSIBLE:-}"
tag=""
case "$plausible" in
"") ;;
https://plausible.io/js/pa-*.js)
  case "${plausible#https://plausible.io/js/}" in
  *[!A-Za-z0-9._-]*) echo "deploy: LCARS_LANDING_PLAUSIBLE is a site's domain or https://plausible.io/js/pa-<id>.js" >&2; exit 2 ;;
  esac
  tag="<script src=\"$plausible\" defer></script>" ;;
*/* | *:* | *[!A-Za-z0-9.-]* | [!A-Za-z0-9]* | *[!A-Za-z0-9])
  echo "deploy: LCARS_LANDING_PLAUSIBLE is a site's domain or https://plausible.io/js/pa-<id>.js" >&2; exit 2 ;;
*.*) tag="<script defer data-domain=\"$plausible\" src=\"https://plausible.io/js/script.js\"></script>" ;;
*) echo "deploy: LCARS_LANDING_PLAUSIBLE is a site's domain or https://plausible.io/js/pa-<id>.js" >&2; exit 2 ;;
esac
NOTE_OFF="No tracking, no cookies, no analytics on this page"
NOTE_ON='No cookies and no tracking: visits are counted by <a href="https://plausible.io/data-policy">Plausible Analytics</a>, which sets no cookie and collects no personal data'
if [ -n "${LCARS_LANDING_STAGE:-}" ]; then
  stage="$LCARS_LANDING_STAGE"
  rm -rf "$stage/public"
  mkdir -p "$stage"
else
  stage=$(mktemp -d "${TMPDIR:-/tmp}/lcars-landing-XXXXXX")
  trap 'rm -rf "$stage"' EXIT
fi
# the version the manual is for: the console's in this checkout, a plain
# X.Y.Z (it goes into sed's replacement)
app_page="${LCARS_LANDING_APP_PAGE:-../../lcars-ui/index.html}"
version=$(sed -n 's/^const APP_VERSION = "\([0-9][0-9.]*\)";$/\1/p' "$app_page" 2>/dev/null | head -n 1)
case "$version" in
[0-9]*.[0-9]*.[0-9]*) case "$version" in *[!0-9.]*) version="" ;; esac ;;
*) version="" ;;
esac
if [ -z "$version" ]; then
  echo "deploy: no APP_VERSION X.Y.Z in $app_page (the manual's version)" >&2
  exit 1
fi
cp -R public "$stage/public"
# a local copy for the preview (ignored) is never uploaded: the page plays R2's
rm -f "$stage/public/video/explainer.mp4"
for f in "$stage"/public/*.html; do
  sed -e "s#__SITE__#$site#g" -e "s#__EXPLAINER__#$LCARS_LANDING_EXPLAINER_URL#g" "$f" >"$f.new" && mv "$f.new" "$f"
done
for f in "$stage"/public/manual/*.html; do
  sed -e "s#__VERSION__#$version#g" "$f" >"$f.new" && mv "$f.new" "$f"
done
if grep -l -e "__SITE__" -e "__EXPLAINER__" -e "__VERSION__" "$stage"/public/*.html "$stage"/public/manual/*.html >/dev/null 2>&1; then
  echo "deploy: a placeholder left in a page" >&2
  exit 1
fi
if [ -n "$tag" ]; then
  for f in "$stage"/public/*.html; do
    sed -e "s#</head>#<script src=\"/plausible-init.js\" defer></script>$tag</head>#" -e "s#$NOTE_OFF#$NOTE_ON#" "$f" >"$f.new" && mv "$f.new" "$f"
  done
  sed -e "/Content-Security-Policy/s#script-src 'self'#script-src 'self' https://plausible.io#" \
    -e "/Content-Security-Policy/s#connect-src 'self'#connect-src 'self' https://plausible.io#" "$stage/public/_headers" >"$stage/_headers.new" &&
    mv "$stage/_headers.new" "$stage/public/_headers"
  if ! grep -q "connect-src 'self' https://plausible.io;" "$stage/public/_headers" || ! grep -q "script-src 'self' https://plausible.io;" "$stage/public/_headers"; then
    echo "deploy: the CSP in _headers was not opened to plausible.io" >&2
    exit 1
  fi
  if grep -q "$NOTE_OFF" "$stage/public/index.html" || ! grep -q "counted by" "$stage/public/index.html"; then
    echo "deploy: the privacy note was not changed for Plausible" >&2
    exit 1
  fi
else
  rm -f "$stage/public/plausible-init.js"
fi
cfg="$stage/wrangler.toml"
{
  sed -e "s#LCARS_LANDING_D1_ID#$LCARS_LANDING_D1_ID#" \
    -e "s#^main = .*#main = \"$PWD/src/worker.js\"#" \
    -e "s#^directory = .*#directory = \"$stage/public\"#" wrangler.toml
  printf '\n[[routes]]\npattern = "%s"\ncustom_domain = true\n' "$LCARS_LANDING_HOST"
} >"$cfg"
WRANGLER_SEND_METRICS=false npx --yes wrangler@3 deploy -c "$cfg" "$@"
