#!/bin/sh
# Builds lcars-ui/crew/ (the deck's crew, docs/design/deck-pipeline.md) from
# scratch: fetches Quaternius's CC0 packs into the model cache
# (deck-crew-fetch.py), makes the three hair styles and the two idles they
# lack in Blender (deck-crew-hair.py, deck-crew-poses.py), and cleans the
# lot into the webp, glbs and clips the page loads (deck-crew-assets.mjs).
#
#   scripts/deck-crew-build.sh [--preview]   # --preview: Blender's renders kept in $cache/crew-made
#
# Niced and ioniced throughout, as build.sh: the live server on this box
# gets the CPU first. Nothing downloaded or made on the way is committed.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
cache=${XDG_CACHE_HOME:-$HOME/.cache}/lcars-deck-models
packs=$cache/quaternius made=$cache/crew-made
low() { nice -n 19 ionice -c3 "$@"; }
bl() { low blender -b --factory-startup -t 3 -P "$@" 2>&1 | grep -E '^\[deck-crew\]|Traceback|^  File|Error: [^C]' || true; }

low python3 "$here/deck-crew-fetch.py" "$packs"
rm -rf "$made"; mkdir -p "$made"
bl "$here/deck-crew-hair.py" -- "$packs/Universal Base Characters[Standard]" "$made" "$@"
bl "$here/deck-crew-poses.py" -- "$packs/Universal Animation Library[Standard]/Unreal-Godot/UAL1_Standard.glb" "$made" "$@"
for f in Hair_Short.glb Hair_Bob.glb Hair_Ponytail.glb poses.glb; do
  [ -f "$made/$f" ] || { echo "Blender wrote no $f" >&2; exit 1; }
done
if [ ! -d "$cache/node/node_modules/@gltf-transform/functions" ] || [ ! -d "$cache/node/node_modules/meshoptimizer" ]; then
  mkdir -p "$cache/node"
  (cd "$cache/node" && low npm i --silent --no-save --no-package-lock @gltf-transform/core@4 @gltf-transform/functions@4 @gltf-transform/extensions@4 sharp meshoptimizer@1.3.0)
fi
# the script resolves its imports from beside itself (scripts/node_modules is ignored)
ln -sfn "$cache/node/node_modules" "$repo/scripts/node_modules"
low node "$here/deck-crew-assets.mjs" "$packs" "$made" "$repo/lcars-ui/crew/"
du -sh "$repo/lcars-ui/crew"
