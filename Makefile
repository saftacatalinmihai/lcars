RAYLIB_CFLAGS = $(shell pkg-config --cflags raylib)
RAYLIB_LIBS   = $(shell pkg-config --libs raylib)

CFLAGS = -std=c11 -ggdb -g -Wall -Wextra -pedantic -fsanitize=address $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lpthread -lm -framework Cocoa -framework IOKit -framework CoreVideo
# CFLAGS = -std=c11 $(RAYLIB_CFLAGS) $(RAYLIB_LIBS) -lpthread -lm

# Web build settings (Emscripten)
RAYLIB_WEB = raylib-web/src
WEB_CFLAGS = -Os -Wall -std=c11 -DPLATFORM_WEB -I$(RAYLIB_WEB)
WEB_LDFLAGS = -s USE_GLFW=3 -s ASYNCIFY -s TOTAL_MEMORY=67108864 -s ALLOW_MEMORY_GROWTH=1 \
              --preload-file style_cyber.rgs

compile_commands.json: Makefile
	bear -- make -B lcars

lcars: lcars.c
	cc $(CFLAGS) -o lcars lcars.c -ldl

lcars-lib: lcars_lib.h lcars_lib.c
	cc $(CFLAGS) -fPIC -shared -std=c11 $(RAYLIB_CFLAGS) $(RAYLIB_LIBS)  -o lcars-lib.so lcars_lib.c -ggdb -g -O0

# Web build targets
lcars-web: lcars.c style_cyber.rgs $(RAYLIB_WEB)/libraylib.web.a
	emcc lcars_lib.c lcars.c -o lcars.js $(WEB_CFLAGS) $(WEB_LDFLAGS) $(RAYLIB_WEB)/libraylib.web.a

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

.PHONY: run clean lcars-web serve setup-emsdk setup-raylib-web setup-web

