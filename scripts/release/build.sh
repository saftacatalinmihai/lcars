#!/bin/sh
# make lcars-static in alpine:3.20 (docs/design/open-source-build.md, §4):
# the release binary is linked against musl, which only Alpine packages
# with static curl, OpenSSL and sqlite. Run from the checkout's root on a
# box with docker - CI's runners (.github/workflows/static.yml and
# release.yml); the VPS has no docker. Leaves ./lcars-static, owned by the
# caller.
#
# docker run rather than the workflow's `container:`: GitHub runs its
# JavaScript actions (checkout, upload-artifact) inside an Alpine container
# only on x86_64, so the arm64 runner checks out on the host and builds here.
set -eu
ALPINE=${ALPINE:-alpine:3.20}
# Makefile's lcars-static comment is the list's other copy
PKGS="build-base pkgconf python3 git file \
  curl-dev curl-static openssl-libs-static nghttp2-static zlib-static \
  sqlite-dev sqlite-static brotli-static zstd-static c-ares-static \
  libidn2-static libunistring-static libpsl-static"
docker run --rm -v "$PWD:/w" -w /w -e HOST_IDS="$(id -u):$(id -g)" "$ALPINE" sh -euc "
  apk add --no-cache $PKGS >/dev/null
  # the checkout belongs to the runner's user, not the container's root
  git config --global --add safe.directory /w
  make lcars-static
  chown -R \"\$HOST_IDS\" build lcars-static
"
ls -l lcars-static
