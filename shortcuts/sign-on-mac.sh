#!/bin/sh
# Sign every unsigned .shortcut in this directory so an iPhone will import it.
# Run on macOS 12+ (the `shortcuts` CLI ships with the OS); iOS 15 and later
# refuse unsigned shortcut files and there is no longer a setting to relax that.
#
# Usage: sh sign-on-mac.sh [outdir]   (default outdir: ./signed)
set -eu

out="${1:-signed}"
mkdir -p "$out"

for f in *.shortcut; do
  case "$f" in
    # Don't re-sign output that was copied back in beside the sources.
    *.signed.shortcut) continue ;;
  esac
  printf 'signing %s\n' "$f"
  # "anyone" is the share-with-anyone signature. "people-who-know-me" would tie
  # the file to contacts, which buys nothing when the destination is your phone.
  shortcuts sign --mode anyone -i "$f" -o "$out/$f"
done

printf '\ndone: %s\n' "$out"
