# Detect architecture automatically, can be overridden with: make ARCH=mac or make ARCH=linux
UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
	ARCH ?= mac
else
	ARCH ?= linux
endif

RAYLIB_CFLAGS = $(shell pkg-config --cflags raylib)
RAYLIB_LIBS   = $(shell pkg-config --libs raylib)

# Architecture-specific linker flags for dynamic/hot-reload build. Raylib
# itself is linked via RAYLIB_LIBS (from pkg-config, folded into CFLAGS_DYN
# below) - these are the extra system frameworks/libs raylib needs on top
# of that.
ifeq ($(ARCH),mac)
	LDFLAGS_DYN := -framework Cocoa -framework IOKit -framework CoreVideo -framework CoreAudio -framework AudioToolbox -lm
	RPATH_FLAGS := -Wl,-rpath,resources/ -Wl,-rpath,@executable_path/resources/
	SHARED_FLAGS := -undefined dynamic_lookup
	STATIC_LIBS_DESKTOP := -framework Cocoa -framework IOKit -framework CoreVideo -framework CoreAudio -framework AudioToolbox -lcurl -lsqlite3 -lm -lpthread -ldl
else ifeq ($(ARCH),linux)
	LDFLAGS_DYN := -lm
	RPATH_FLAGS := -Wl,-rpath,resources/
	SHARED_FLAGS :=
	STATIC_LIBS_DESKTOP := -lcurl -lsqlite3 -lX11 -lGL -lrt -lm -lpthread -ldl
else
	$(error Unknown ARCH: $(ARCH). Use 'mac' or 'linux')
endif

# Toggle AddressSanitizer on debug/dynamic builds without editing this
# file: make SANITIZE=0 lcars
SANITIZE ?= 1
ifeq ($(SANITIZE),1)
	SANITIZE_FLAGS := -fsanitize=address
else
	SANITIZE_FLAGS :=
endif

# Base CFLAGS (excluding RAYLIB_LIBS and LDFLAGS to avoid dynamic linking in static target)
BASE_CFLAGS = -std=c11 -Wall -Wextra -pedantic -Wshadow -DHYPERMEDIA -Ivendor -Ivendor/raylib-web/src $(RAYLIB_CFLAGS)
CFLAGS_DEBUG = $(BASE_CFLAGS) -ggdb -g $(SANITIZE_FLAGS)
CFLAGS_RELEASE = $(BASE_CFLAGS) -O3

# For the dynamic/hot-reloaded development target:
CFLAGS_DYN = $(BASE_CFLAGS) -ggdb -g $(SANITIZE_FLAGS) $(RAYLIB_LIBS) -lpthread $(LDFLAGS_DYN)

# Web build settings (Emscripten)
RAYLIB_WEB = vendor/raylib-web/src
WEB_CFLAGS = -Os -std=c11 -DPLATFORM_WEB -DHYPERMEDIA -I$(RAYLIB_WEB)
WEB_LDFLAGS = -s USE_GLFW=3 -s ASYNCIFY -s TOTAL_MEMORY=67108864 -s ALLOW_MEMORY_GROWTH=1 \
              -s FETCH \
              --preload-file resources/earth.png \
              --preload-file resources/earth.jpg \
              --preload-file resources/style_cyber.rgs

# Every lcars_*.h is part of the same unity translation unit, so a change to
# any of them invalidates every binary - listing only a couple of them (as
# lcars-lib.so used to) means Ctrl+Shift+R can "succeed" and reload code that
# was never rebuilt.
LCARS_HEADERS := $(wildcard lcars_*.h) liblcars.h

compile_commands.json: Makefile
	bear -- make -B lcars

# Helper to download missing resources before building (needed for libvosk.so linking)
RESOURCE_HELPER = /tmp/lcars-download-resources
$(RESOURCE_HELPER): lcars_resources_download_main.c lcars_resources_download.c lcars_resources_download.h
	$(CC) -std=c11 -g lcars_resources_download_main.c lcars_resources_download.c -lcurl -o $@

ensure-resources: $(RESOURCE_HELPER)
	@$(RESOURCE_HELPER)

# Target to build static raylib if missing
vendor/libraylib.a:
	@if [ ! -d "vendor/raylib-web" ]; then \
		git clone https://github.com/raysan5/raylib.git vendor/raylib-web; \
	fi
	@echo "Building static raylib for desktop..."
	$(MAKE) -C vendor/raylib-web/src PLATFORM=PLATFORM_DESKTOP -B
	cp vendor/raylib-web/src/libraylib.a vendor/libraylib.a
	$(MAKE) -C vendor/raylib-web/src clean

# Target to build static miniaudio if missing
vendor/libminiaudio.a: vendor/miniaudio.c
	@echo "Building static miniaudio..."
	cc -std=c11 -O2 -c vendor/miniaudio.c -o vendor/miniaudio.o
	ar rcs vendor/libminiaudio.a vendor/miniaudio.o
	rm vendor/miniaudio.o

# Static targets
lcars: lcars.c $(LCARS_HEADERS) vendor/libraylib.a vendor/libminiaudio.a ensure-resources
	cc $(CFLAGS_DEBUG) -DSTATIC_BUILD -o lcars lcars.c vendor/libraylib.a vendor/libminiaudio.a $(STATIC_LIBS_DESKTOP)

lcars-release: lcars.c $(LCARS_HEADERS) vendor/libraylib.a vendor/libminiaudio.a ensure-resources
	cc $(CFLAGS_RELEASE) -DSTATIC_BUILD -o lcars lcars.c vendor/libraylib.a vendor/libminiaudio.a $(STATIC_LIBS_DESKTOP)

# Dynamic targets
lcars-dynamic: lcars.c $(LCARS_HEADERS) lcars-lib.so vendor/libminiaudio.a ensure-resources
	cc $(CFLAGS_DYN) -o lcars lcars.c vendor/libminiaudio.a -lcurl -lsqlite3 -ldl -Lresources/ -lvosk $(RPATH_FLAGS)

lcars-lib.so: liblcars.c $(LCARS_HEADERS)
	cc $(CFLAGS_DYN) -fPIC -shared $(SHARED_FLAGS) -lsqlite3 -ldl -lcurl -o lcars-lib.so liblcars.c

run: lcars
	./lcars

run-dynamic: lcars-lib.so lcars-dynamic
	./lcars

# docker run --rm -v $$(pwd):/workspace -w /workspace debian:11-slim sh -c "
lcars-portable:
	docker run -v $$(pwd):/workspace -w /workspace debian:11-slim sh -c "\
		apt-get update && \
		apt-get install -y build-essential git libcurl4-openssl-dev libsqlite3-dev libx11-dev libglu1-mesa-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev libasound2-dev pkg-config && \
		rm -f vendor/libraylib.a && \
		make -C vendor/raylib-web/src clean && \
		make lcars-release && \
		chown $(shell id -u):$(shell id -g) lcars"

# Web build targets
lcars-web: lcars.c $(LCARS_HEADERS) $(RAYLIB_WEB)/libraylib.web.a
	emcc lcars.c vendor/sqlite3.c -ldl -o lcars.js $(WEB_CFLAGS) $(WEB_LDFLAGS) $(RAYLIB_WEB)/libraylib.web.a

serve: lcars-web
	@echo "Starting server at http://localhost:8080/lcars.html"
	python3 -m http.server 8080

# Setup targets for dependencies
setup-emsdk:
	@if [ ! -d "emsdk" ]; then \
		git clone https://github.com/emscripten-core/emsdk.git && \
		cd emsdk && ./emsdk install latest && ./emsdk activate latest; \
	else \
		echo "emsdk already exists"; \
	fi

setup-raylib-web: setup-emsdk
	@if [ ! -d "vendor/raylib-web" ]; then \
		git clone https://github.com/raysan5/raylib.git vendor/raylib-web && \
		cd vendor/raylib-web/src && \
		. ../../../emsdk/emsdk_env.sh && \
		make PLATFORM=PLATFORM_WEB -B; \
	else \
		echo "raylib-web already exists"; \
	fi

setup-web: setup-emsdk setup-raylib-web
	@echo "Web build dependencies ready!"
	@echo "Run 'source emsdk/emsdk_env.sh' then 'make lcars-web'"

run-web: lcars-web
	@echo "Starting server at http://localhost:8080/lcars.html"
	python3 -m http.server 8080
	
clean:
	rm -f lcars lcars-lib.so lcars.js lcars.wasm lcars.data vendor/libminiaudio.a

.PHONY: run clean lcars-web serve setup-emsdk setup-raylib-web setup-web lcars-portable
