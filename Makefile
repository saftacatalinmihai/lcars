# Toggle AddressSanitizer on the debug build without editing this file:
# make SANITIZE=0 lcars
SANITIZE ?= 1
ifeq ($(SANITIZE),1)
	SANITIZE_FLAGS := -fsanitize=address
else
	SANITIZE_FLAGS :=
endif

# The version is CHANGELOG.md's top entry, passed as a bare number
# (-DLCARS_VERSION=0.260.1, made a string in lcars_config.h) so no quoting
# has to survive into the tests' scratch builds, which run the line `make -n`
# prints. `lcars version` and the start log name it.
LCARS_VERSION := $(shell sed -n 's/^\#\# \([0-9][0-9.]*\) .*/\1/p' CHANGELOG.md | head -n 1)
BASE_CFLAGS = -std=c11 -Wall -Wextra -pedantic -Wshadow
VERSION_FLAG = $(if $(LCARS_VERSION),-DLCARS_VERSION=$(LCARS_VERSION))
CFLAGS_DEBUG = $(BASE_CFLAGS) -ggdb -g $(SANITIZE_FLAGS)
CFLAGS_RELEASE = $(BASE_CFLAGS) -O3
SERVER_LIBS = -lcurl -lsqlite3 -lz -lm -lpthread

# Every lcars_*.h is part of the server's one translation unit, so a change
# to any of them rebuilds it.
SERVER_SOURCES := lcars.c $(wildcard lcars_*.h) CHANGELOG.md

compile_commands.json: Makefile
	bear -- make -B lcars

# The server. The test suites build a scratch one from the lcars-release line
# (`make -n -W lcars.c lcars-release`, the `cc ... -o lcars lcars.c` line,
# its output path swapped): keep it one command of that shape.
lcars: $(SERVER_SOURCES)
	cc $(CFLAGS_DEBUG) $(VERSION_FLAG) -o lcars lcars.c $(SERVER_LIBS)

lcars-release: $(SERVER_SOURCES)
	cc $(CFLAGS_RELEASE) $(VERSION_FLAG) -o lcars lcars.c $(SERVER_LIBS)

# The one binary (docs/design/open-source-build.md, step 3): the server with
# the CLI linked in, `lcars cli ARGS` or a lcars-cli symlink to it. Two
# translation units, one link: lcars_cli.c's main is renamed for it, so that
# file keeps its own main for `make lcars-cli`. Dynamic, against the host's
# libraries, and the UI read from disk as ever. Its own output name, never
# ./lcars, which on the VPS is the running binary.
ONE_DIR = build/one
lcars-one: $(SERVER_SOURCES) lcars_cli.c lcars_cli.h lcars_logseq.h \
		lcars_strava.h
	mkdir -p $(ONE_DIR)
	cc $(CFLAGS_RELEASE) $(VERSION_FLAG) -DLCARS_ONE_BINARY -c -o $(ONE_DIR)/lcars.o lcars.c
	cc $(CFLAGS_RELEASE) -Dmain=LcarsCliMain -c -o $(ONE_DIR)/lcars_cli.o lcars_cli.c
	cc -o lcars-one $(ONE_DIR)/lcars.o $(ONE_DIR)/lcars_cli.o $(SERVER_LIBS)

# The web UI in one blob (docs/design/open-source-build.md, step 4): the
# shipped set (git ls-files lcars-ui minus test/ and report/) with its index,
# which -DLCARS_EMBED_UI .incbins (lcars_ui_files.h, "The embedded copy").
# Rewritten whenever a file under lcars-ui/ changes; the script reads the
# working tree, saved or committed alike.
UI_PACK = build/ui.pack
UI_SOURCES := $(shell git ls-files lcars-ui 2>/dev/null | grep -v -e '^lcars-ui/test/' -e '^lcars-ui/report/')
$(UI_PACK): scripts/ui-pack.py $(UI_SOURCES)
	python3 scripts/ui-pack.py $(UI_PACK)
ui-pack: $(UI_PACK)

# lcars-one with the UI inside it: serves /ui/ with no lcars-ui/ beside it
# (LCARS_UI_DIR still wins). Dynamic, the host's libraries; step 5's
# lcars-static is this plus -static, in Alpine. Its own objects, as the
# define changes lcars.o.
EMBED_DIR = build/embed
lcars-embed: $(SERVER_SOURCES) lcars_cli.c lcars_cli.h lcars_logseq.h \
		lcars_strava.h $(UI_PACK)
	mkdir -p $(EMBED_DIR)
	cc $(CFLAGS_RELEASE) $(VERSION_FLAG) -DLCARS_ONE_BINARY -DLCARS_EMBED_UI -c -o $(EMBED_DIR)/lcars.o lcars.c
	cc $(CFLAGS_RELEASE) -Dmain=LcarsCliMain -c -o $(EMBED_DIR)/lcars_cli.o lcars_cli.c
	cc -o lcars-embed $(EMBED_DIR)/lcars.o $(EMBED_DIR)/lcars_cli.o $(SERVER_LIBS)

# The release binary (step 5): lcars-embed linked -static, with
# -DLCARS_STATIC for the CA bundle probe (lcars_curl_ca.h). Built against
# musl in Alpine - glibc's static libcurl is not packaged, and a static glibc
# binary still dlopens NSS - so in CI (.github/workflows/static.yml) or
# `docker run alpine:3.20`, never on the VPS (no docker, no musl). Alpine's
# packages for it:
#   apk add build-base pkgconf python3 git file \
#     curl-dev curl-static openssl-libs-static nghttp2-static zlib-static \
#     sqlite-dev sqlite-static brotli-static zstd-static c-ares-static \
#     libidn2-static libunistring-static libpsl-static
# The link line is pkg-config's --static list, so whatever libcurl was
# built with comes along.
STATIC_DIR = build/static
STATIC_LIBS = $(shell pkg-config --static --libs libcurl sqlite3 zlib) -lm -lpthread
lcars-static: $(SERVER_SOURCES) lcars_cli.c lcars_cli.h lcars_logseq.h \
		lcars_strava.h $(UI_PACK)
	mkdir -p $(STATIC_DIR)
	cc $(CFLAGS_RELEASE) $(VERSION_FLAG) -DLCARS_ONE_BINARY -DLCARS_EMBED_UI -DLCARS_STATIC -c -o $(STATIC_DIR)/lcars.o lcars.c
	cc $(CFLAGS_RELEASE) -DLCARS_STATIC -Dmain=LcarsCliMain -c -o $(STATIC_DIR)/lcars_cli.o lcars_cli.c
	cc -static -o lcars-static $(STATIC_DIR)/lcars.o $(STATIC_DIR)/lcars_cli.o $(STATIC_LIBS)

# The quickest full-warning compile of the server: no code generated, no
# binary written, so it is safe in a checkout whose ./lcars is running.
check:
	cc $(BASE_CFLAGS) -fsyntax-only lcars.c

# Command-line client, a client of the server's HTTP API. Deliberately not
# part of the server's translation unit: it links libcurl only. No AddressSanitizer either, unlike
# the debug server build: this is a tool meant to be run, not stepped through.
CFLAGS_CLI = -std=c11 -Wall -Wextra -pedantic -Wshadow -ggdb -O2

lcars-cli: lcars_cli.c lcars_cli.h lcars_logseq.h lcars_strava.h lcars_arena.h lcars_curl_ca.h \
		lcars_json.h
	cc $(CFLAGS_CLI) -o lcars-cli lcars_cli.c -lcurl -lm

run: lcars
	./lcars

# Portable build: compile inside an older Debian than the target box so the
# binary's glibc requirement stays below the VPS's (Debian 13 / glibc 2.41).
# Bookworm (glibc 2.36) rather than bullseye: bullseye is EOL, its apt
# repositories moved to archive.debian.org, and its security Release file has
# expired, so `apt-get update` on debian:11-slim fails outright. If an even
# older glibc is ever needed, point sources.list at archive.debian.org and add
# -o Acquire::Check-Valid-Until=false, rather than un-expiring the mirror.
# The chown reads the mount's owner rather than `id -u`: this target is run
# under sudo (docker needs it here), so make's own uid is 0 and the built
# binary would come back root-owned.
lcars-portable:
	docker run --rm -v $$(pwd):/workspace -w /workspace debian:12-slim sh -c "\
		apt-get update && \
		apt-get install -y build-essential libcurl4-openssl-dev libsqlite3-dev zlib1g-dev && \
		make lcars-release && \
		chown $$(stat -c '%u:%g' /workspace) lcars"

clean:
	rm -f lcars lcars-cli lcars-one lcars-embed lcars-static
	rm -rf $(ONE_DIR) $(EMBED_DIR) $(STATIC_DIR) $(UI_PACK)

.PHONY: run clean check lcars-portable ui-pack
