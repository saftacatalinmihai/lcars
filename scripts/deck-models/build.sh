#!/bin/sh
# Builds the deck's models into lcars-ui/deck/ (docs/design/deck-pipeline.md):
# every room script (scripts/deck-models/<room>.py) and every pack below run
# through Blender headless, then scripts/deck-model-assets.mjs cleans them.
#
#   scripts/deck-models/build.sh            # every room and pack
#   scripts/deck-models/build.sh bridge     # one (or a few)
#
# Niced and ioniced throughout: a bake takes every core it is given, and
# the live server on this box must always get the CPU first (Number One's
# rule, 2026-10-15). Blender gets three threads of the four.
# Downloads (packs) and the cleaner's npm packages are cached in
# ~/.cache/lcars-deck-models; nothing downloaded is committed.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cache=${XDG_CACHE_HOME:-$HOME/.cache}/lcars-deck-models
raw=$(mktemp -d "${TMPDIR:-/tmp}/deck-models.XXXXXX")
trap 'rm -rf "$raw"' EXIT INT TERM
low() { nice -n 19 ionice -c3 "$@"; }
bl() { low blender -b --factory-startup -t 3 -P "$@" 2>&1 | grep -E '^\[deck-models\]|Error|error|Traceback|^  File' || true; }

# What a room needs downloaded: a room script whose props include a pack's
# (Poly Haven's, fetch_polyhaven.py) gets the folder they are fetched into
# as its second argument, and imports them with common.import_pack.
fetch() {
  case $1 in
    readyroom)
      # Poly Haven, CC0: a carved elephant and a brass vase, dressing for the
      # ready room's tea table and desk. (ceramic_vase_01 was the third: it
      # is thin-walled, and decimated its inner wall pokes through the outer;
      # import_pack does not strip interiors - docs/design/deck-pipeline.md)
      low python3 "$here/fetch_polyhaven.py" "$cache/polyhaven" carved_wooden_elephant brass_vase_03 >&2
      src="$cache/packs/readyroom"; rm -rf "$src"; mkdir -p "$src"
      for a in carved_wooden_elephant brass_vase_03; do ln -s "$cache/polyhaven/$a" "$src/$a"; done
      echo "$src" ;;
  esac
}
# The packs: a room made of a downloaded pack alone, through pack.py, and
# the triangle budget of each prop (--tris). None today: the ready room's
# was one until its script joined it (0.217.0).
pack() {
  case $1 in
    *) return 1 ;;
  esac
}
PACKS=""
ROOMS=$(cd "$here" && ls *.py | sed 's/\.py$//' | grep -vxE 'common|pack|fetch_polyhaven')
want=${*:-$ROOMS $PACKS}
for r in $want; do
  echo "== $r"
  if [ -f "$here/$r.py" ]; then bl "$here/$r.py" -- "$raw" $(fetch "$r")
  else pack "$r" || { echo "no room script or pack called $r" >&2; exit 2; }
  fi
  [ -f "$raw/$r.glb" ] || { echo "$r: Blender wrote no glb" >&2; exit 1; }
done
if [ ! -d "$cache/node/node_modules/meshoptimizer" ]; then
  mkdir -p "$cache/node"
  (cd "$cache/node" && low npm i --silent --no-save --no-package-lock @gltf-transform/core@4 @gltf-transform/functions@4 @gltf-transform/extensions@4 sharp meshoptimizer)
fi
# the cleaner resolves its imports from beside itself: lend it the cache's
# (scripts/node_modules is ignored)
ln -sfn "$cache/node/node_modules" "$repo/scripts/node_modules"
low node "$repo/scripts/deck-model-assets.mjs" "$raw" "$repo/lcars-ui/deck/"
