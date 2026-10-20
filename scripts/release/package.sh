#!/bin/sh
# The release tarball (open-source-build.md, §4). From the checkout's root:
#
#   scripts/release/package.sh ./lcars-static x86_64 dist/
#
# writes dist/lcars-X.Y.Z-linux-ARCH.tar.gz, X.Y.Z CHANGELOG's top:
#
#   lcars-X.Y.Z-linux-ARCH/
#     lcars              the binary (server, CLI, the UI inside)
#     lcars-cli -> lcars the CLI by its own name
#     scripts/           what the binary calls or the crew runs, and the
#                        systemd units beside them; not the tests
#     crew/              the crew's roles
#     README.md LICENSE THIRD_PARTY_NOTICES.md
#
# The files are git's (ls-files), never what else lies in the checkout, and
# *.local.* (a deployment's own) is left out. LICENSE and the third-party
# notices are required: the binary carries vendored code (three.js, leaflet)
# whose licences ask for their notices to travel with it, and nothing ships
# without the project's own - the job fails until both are committed.
set -eu
BIN=$1
ARCH=$2
OUT=$3
VERSION=$(sed -n 's/^## \([0-9][0-9.]*\) .*/\1/p' CHANGELOG.md | head -n 1)
[ -n "$VERSION" ] || { echo "no version at CHANGELOG.md's top" >&2; exit 1; }
for f in README.md LICENSE THIRD_PARTY_NOTICES.md; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 ||
    { echo "release: $f is not committed; a release needs it" >&2; exit 1; }
done
NAME=lcars-$VERSION-linux-$ARCH
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
D=$STAGE/$NAME
mkdir -p "$D"
cp "$BIN" "$D/lcars"
chmod 755 "$D/lcars"
ln -s lcars "$D/lcars-cli"
git ls-files -z scripts crew README.md LICENSE THIRD_PARTY_NOTICES.md |
  tr '\0' '\n' |
  grep -v -e '^scripts/test_' -e '^scripts/testdata/' -e '^scripts/release/' \
    -e '\.local\.' |
  while IFS= read -r f; do
    mkdir -p "$D/$(dirname "$f")"
    cp -p "$f" "$D/$f"
  done
mkdir -p "$OUT"
# owner and order fixed, so the same tree packs the same bytes
tar -C "$STAGE" --owner=0 --group=0 --numeric-owner --sort=name \
  -czf "$OUT/$NAME.tar.gz" "$NAME"
echo "$OUT/$NAME.tar.gz"
