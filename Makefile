# Detect architecture automatically, can be overridden with: make ARCH=mac or make ARCH=linux
UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
	ARCH ?= mac
else
	ARCH ?= linux
endif

RAYLIB_CFLAGS = $(shell pkg-config --cflags raylib)
RAYLIB_LIBS   = $(shell pkg-config --libs raylib)

# Architecture-specific linker flags
ifeq ($(ARCH),mac)
	LDFLAGS := $(RAYLIB_LIB) -framework Cocoa -framework IOKit -framework CoreVideo -lm
else ifeq ($(ARCH),linux)
	LDFLAGS := $(RAYLIB_LIB) -lm
else
	$(error Unknown ARCH: $(ARCH). Use 'mac' or 'linux')
endif

CFLAGS = -std=c11 -ggdb -g -Wall -Wextra -pedantic -fsanitize=address $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lpthread $(LDFLAGS)
CFLAGS_RELEASE = -std=c11 -O3 $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lpthread $(LDFLAGS)
# CFLAGS = -std=c11 -ggdb -g -fsanitize=address $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lpthread $(LDFLAGS)

# Web build settings (Emscripten)
RAYLIB_WEB = raylib-web/src
WEB_CFLAGS = -Os -std=c11 -DPLATFORM_WEB -I$(RAYLIB_WEB)
WEB_LDFLAGS = -s USE_GLFW=3 -s ASYNCIFY -s TOTAL_MEMORY=67108864 -s ALLOW_MEMORY_GROWTH=1 \
              --preload-file resources

compile_commands.json: Makefile
	bear -- make -B lcars

# Helper to download missing resources before building (needed for libvosk.so linking)
RESOURCE_HELPER = /tmp/lcars-download-resources
$(RESOURCE_HELPER): resources_download_main.c resources_download.c resources_download.h
	$(CC) -std=c11 -g resources_download_main.c resources_download.c -lcurl -o $@

ensure-resources: $(RESOURCE_HELPER)
	@$(RESOURCE_HELPER)

lcars: lcars.c voice_rec.c voice_rec.h resources_download.c resources_download.h lcars-lib.so ensure-resources
	cc -DNOTDEV=1 $(CFLAGS) -o lcars lcars.c voice_rec.c resources_download.c -lcurl -ldl -Lresources/ -lvosk -Wl,-rpath,resources/

lcars-release: lcars.c voice_rec.c voice_rec.h resources_download.c resources_download.h lcars-lib.so ensure-resources
	cc -DNOTDEV=1 $(CFLAGS_RELEASE) -o lcars lcars.c voice_rec.c resources_download.c -lcurl -ldl -Lresources/ -lvosk -Wl,-rpath,resources/

lcars-lib.so: lcars_lib.h lcars_lib.c voice_rec.h
	cc -DNOTDEV=1 $(CFLAGS) -fPIC -shared -std=c11 $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lsqlite3 -ldl -o lcars-lib.so lcars_lib.c

run: lcars-lib.so lcars
	./lcars

# Web build targets
lcars-web: lcars.c voice_rec.c resources_download.c $(RAYLIB_WEB)/libraylib.web.a
	emcc -DNOTDEV=1 lcars_lib.c lcars.c voice_rec.c resources_download.c sqlite3.c -ldl -o lcars.js $(WEB_CFLAGS) $(WEB_LDFLAGS) $(RAYLIB_WEB)/libraylib.web.a

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
	@if [ ! -d "raylib-web" ]; then \
		git clone https://github.com/raysan5/raylib.git raylib-web && \
		cd raylib-web/src && \
		. ../../emsdk/emsdk_env.sh && \
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
	
.PHONY: run clean lcars-web serve setup-emsdk setup-raylib-web setup-web

