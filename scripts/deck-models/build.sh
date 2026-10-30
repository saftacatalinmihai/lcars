#!/bin/sh
# Builds the deck's models into lcars-ui/deck/ (docs/design/deck-pipeline.md):
# every room script (scripts/deck-models/<room>.py) and every pack below run
# through Blender headless, then scripts/deck-model-assets.mjs cleans them.
#
#   scripts/deck-models/build.sh            # every room and pack
#   scripts/deck-models/build.sh bridge     # one (or a few)
#   scripts/deck-models/build.sh --ktx2 [ROOM ...]  # the KTX2 alone, from the webps
#   scripts/deck-models/build.sh --ktx2 maps        # the bridge's tiles and skylight alone
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
    bridge)
      # The captain's chair and the conn's and ops' chair made by image-to-3D
      # (Tripo, bridge-redesign.md 8c and section 9's slice 4), already fitted
      # to their stand-ins: 2.3-2.8 MB each, so kept in the media store
      # (MEDIA/deck-models/<prop>/, with its LICENSE.txt), not in git, and
      # copied into the cache, one folder each under the one the room
      # imports (kept there for a build while the NAS is away). A prop in
      # neither (the public repo, a box without the NAS) is not passed, and
      # bridge.py builds its scripted one; with neither chair, nothing is.
      generated bridge captain_chair conn_chair ;;
    quarters)
      # The sofa and the double bed by gen.py (deck-remodel.md slice 9, on
      # the captain's word 2026-10-30), fitted by fit.py: as the bridge's
      # chairs, kept in the media store; without them quarters.py builds
      # its scripted ones.
      generated quarters quarters_sofa quarters_bed ;;
  esac
}
# generated ROOM PROP...: each PROP's fitted glb and LICENSE.txt from the
# media store (MEDIA/media/deck-models/<prop>/; the root from the
# environment, else ~/.env's line) copied into the cache, one folder each
# under the one the room imports (kept there for a build while the NAS is
# away), and that folder printed when it holds any. A prop in neither (the
# public repo, a box without the NAS) is not passed, and the room script
# builds its scripted one.
generated() {
  src="$cache/generated/$1"; shift
  root=${LCARS_MEDIA_ROOT:-$(sed -n 's/^\(export \)\{0,1\}LCARS_MEDIA_ROOT=["'\'']\{0,1\}\([^"'\'']*\).*/\2/p' "$HOME/.env" 2>/dev/null | tail -n 1)}
  for p in "$@"; do
    if [ -n "$root" ] && [ -f "$root/media/deck-models/$p/$p.glb" ]; then
      mkdir -p "$src/$p"
      cp -p "$root/media/deck-models/$p/$p.glb" "$root/media/deck-models/$p/LICENSE.txt" "$src/$p/"
    fi
  done
  if ls "$src"/*/*.glb >/dev/null 2>&1; then echo "$src"; fi
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
ROOMS=$(cd "$here" && ls *.py | sed 's/\.py$//' | grep -vxE 'common|pack|fetch_polyhaven|gen|fit')
ktx2only=; [ "${1:-}" = --ktx2 ] && { ktx2only=1; shift; }
want=${*:-$ROOMS $PACKS}
[ -n "$ktx2only" ] && want=
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
# KTX-Software's ktx, which writes the atlases' KTX2 (deck-model-assets.mjs):
# its release's x86_64 tarball, checked against its sha1, unpacked in the
# cache. Elsewhere (arm64, no network) the cleaner writes webp alone, and
# the page loads those.
KTXV=4.4.2 KTXSHA=c6b08c817f8c8dd299deccae4f2fbb8d55e9acd2
ktxd="$cache/ktx/KTX-Software-$KTXV-Linux-x86_64"
if [ ! -x "$ktxd/bin/ktx" ] && [ "$(uname -m)" = x86_64 ]; then
  mkdir -p "$cache/ktx"
  t="$cache/ktx/KTX-Software-$KTXV-Linux-x86_64.tar.bz2"
  curl -fsSL -o "$t" "https://github.com/KhronosGroup/KTX-Software/releases/download/v$KTXV/KTX-Software-$KTXV-Linux-x86_64.tar.bz2" &&
    echo "$KTXSHA  $t" | sha1sum -c --quiet && tar xjf "$t" -C "$cache/ktx" || echo "ktx: not fetched, KTX2 skipped" >&2
fi
if [ -x "$ktxd/bin/ktx" ]; then
  export KTX="$ktxd/bin/ktx" LD_LIBRARY_PATH="$ktxd/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# the cleaner resolves its imports from beside itself: lend it the cache's
# (scripts/node_modules is ignored)
ln -sfn "$cache/node/node_modules" "$repo/scripts/node_modules"
if [ -n "$ktx2only" ]; then low node "$repo/scripts/deck-model-assets.mjs" --ktx2 "$repo/lcars-ui/deck/" "$@"
else low node "$repo/scripts/deck-model-assets.mjs" "$raw" "$repo/lcars-ui/deck/"
fi
