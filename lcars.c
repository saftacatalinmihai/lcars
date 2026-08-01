#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#ifdef __EMSCRIPTEN__
#endif

#include "lcars_base.h"

#if defined(STATIC_BUILD) || defined(__EMSCRIPTEN__)
#define LCARS_IMPLEMENTATION
#define RAYGUI_IMPLEMENTATION
#endif
#include "liblcars.h"

// InitDBMinimal() (below) calls InitDB() directly rather than through the
// dlopen'd library, so this TU needs a real definition of it even in the
// dynamic hot-reload build, where LCARS_IMPLEMENTATION isn't otherwise
// defined (the UI functions come from lcars-lib.so instead). lcars_db.h's
// own include guard makes this a no-op when LCARS_IMPLEMENTATION was
// already defined above (the static/emscripten builds).
#ifndef LCARS_IMPLEMENTATION
#define LCARS_IMPLEMENTATION
#endif
#include "lcars_db.h"
#define LCARS_HTTP_IMPLEMENTATION
#include "lcars_http.h"
#include "lcars_resources_download.h"
#include "lcars_voice_rec.h"
#include "raylib.h"
#include "rlgl.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#else
typedef void (*Fn_Update)(State *s);
typedef void (*Fn_Init)(State *s, bool firstInit);
typedef void (*Fn_Reload)(State *s, bool reset);
typedef void (*Fn_FlushPendingSaves)(State *s);

// Only the true dynamic hot-reload build (neither STATIC_BUILD nor
// __EMSCRIPTEN__) dlopens lcars-lib.so at runtime and calls this.
#ifndef STATIC_BUILD

// Copies lcars-lib.so to a fresh, uniquely-numbered path (a stale mapping
// of the previous load can otherwise keep dlopen from picking up a
// rebuilt .so at the same path), dlopens it, and resolves the four
// functions the hot-reload UI relies on. All-or-nothing: Update/Init/
// Reload are required, and *outUpdate/*outInit/*outReload/
// *outFlushPendingSaves are only written if the whole load succeeds, so a
// failed reload can't leave the caller with a mix of old and new function
// pointers (or worse, a NULL one it then calls). FlushPendingSaves is the
// one optional symbol - if it's missing, the load still succeeds but
// *outFlushPendingSaves comes back NULL, and the caller just won't get
// pending-edit flushing on exit.
static bool LoadAppLibrary(int *reload_counter, Fn_Update *outUpdate,
                           Fn_Init *outInit, Fn_Reload *outReload,
                           Fn_FlushPendingSaves *outFlushPendingSaves) {
  char lib_path[256];
  snprintf(lib_path, sizeof(lib_path), "./lcars-lib_temp_%d.so",
          (*reload_counter)++);
  char cp_cmd[512];
  snprintf(cp_cmd, sizeof(cp_cmd), "cp ./lcars-lib.so %s", lib_path);
  if (system(cp_cmd) != 0) {
    printf("Failed to copy library to %s\n", lib_path);
    return false;
  }

  void *handle = dlopen(lib_path, RTLD_NOW);
  unlink(lib_path);
  if (!handle) {
    printf("Failed to load library: %s\n", dlerror());
    return false;
  }

  Fn_Update update = NULL;
  Fn_Init init = NULL;
  Fn_Reload reload = NULL;
  Fn_FlushPendingSaves flushPendingSaves = NULL;

  *(void **)&update = dlsym(handle, "UpdateDrawFrame");
  if (!update) {
    printf("Failed to load UpdateDrawFrame: %s\n", dlerror());
    return false;
  }
  *(void **)&init = dlsym(handle, "Init");
  if (!init) {
    printf("Failed to load Init: %s\n", dlerror());
    return false;
  }
  *(void **)&reload = dlsym(handle, "Reload");
  if (!reload) {
    printf("Failed to load Reload: %s\n", dlerror());
    return false;
  }
  *(void **)&flushPendingSaves = dlsym(handle, "FlushPendingSaves");
  if (!flushPendingSaves) {
    printf("Warning: failed to load FlushPendingSaves: %s (pending edits "
          "won't be flushed on exit)\n",
          dlerror());
  }

  *outUpdate = update;
  *outInit = init;
  *outReload = reload;
  *outFlushPendingSaves = flushPendingSaves;
  printf("Library loaded successfully.\n");
  return true;
}
#endif // !STATIC_BUILD
#endif // __EMSCRIPTEN__

// Allocates and initializes a fresh State: the struct itself (over-
// allocated - see below) plus its two memory arenas' backing buffers.
// Exits the process on allocation failure, since there's no reasonable
// way to run without either.
//
// The 10x over-allocation is a stopgap for a hot-reload safety gap, not a
// real fix: in the dynamic build, this executable allocates State once at
// startup, but liblcars.so is recompiled and reloaded independently while
// the app keeps running. If Element/State's layout changes and only one
// side gets rebuilt before the next reload, the reloaded code could read
// or write past what was actually allocated for a single State. Extra
// headroom makes that less likely to immediately corrupt something, but
// doesn't detect or prevent the drift - see REFACTORING.md task I3 for
// the real fix (a layout version/size check on reload).
static State *CreateAppState(void) {
  State *s = (State *)calloc(10, sizeof(State));
  if (!s) {
    fprintf(stderr, "Fatal error: Failed to allocate State\n");
    exit(1);
  }

  size_t doc_arena_size = 32 * 1024 * 1024;     // 32 MB
  size_t scratch_arena_size = 16 * 1024 * 1024; // 16 MB
  void *doc_backing = malloc(doc_arena_size);
  void *scratch_backing = malloc(scratch_arena_size);
  if (!doc_backing || !scratch_backing) {
    fprintf(stderr, "Fatal error: Failed to preallocate memory arenas\n");
    exit(1);
  }
  arena_init(&s->doc_arena, doc_backing, doc_arena_size);
  arena_init(&s->scratch_arena, scratch_backing, scratch_arena_size);
  return s;
}

static void InitDBMinimal(void) {
  State *s = CreateAppState();

  sqlite3 *db = NULL;
  int rc = sqlite3_open(LCARS_DB_PATH, &db);
  if (rc) {
    fprintf(stderr, "Can't open database: %s\n", sqlite3_errmsg(db));
    exit(1);
  }
  s->db = db;

  InitDB(s, true);

  sqlite3_close(db);
  free(s->doc_arena.buffer);
  free(s->scratch_arena.buffer);
  free(s);
}

int main(int argc, char **argv) {
  bool http_only = false;
  int port = 8080;
  char *auth_user = NULL;
  char *auth_pass = NULL;
  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--http-only") == 0 || strcmp(argv[i], "-s") == 0 ||
        strcmp(argv[i], "--server") == 0) {
      http_only = true;
    } else if ((strcmp(argv[i], "--port") == 0 || strcmp(argv[i], "-p") == 0) &&
               i + 1 < argc) {
      port = atoi(argv[++i]);
    } else if ((strcmp(argv[i], "--user") == 0 || strcmp(argv[i], "-u") == 0) &&
               i + 1 < argc) {
      auth_user = argv[++i];
    } else if ((strcmp(argv[i], "--password") == 0 ||
                strcmp(argv[i], "--pass") == 0) &&
               i + 1 < argc) {
      auth_pass = argv[++i];
    } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
      printf("Usage: %s [options]\n", argv[0]);
      printf("Options:\n");
      printf("  --http-only, -s, --server  Start only the API HTTP server (no "
             "UI, no voice rec)\n");
      printf("  --port, -p <port>         Specify HTTP server port (default: "
             "8080)\n");
      printf("  --user, -u <username>     Specify Basic Auth username\n");
      printf("  --password, --pass <password> Specify Basic Auth password\n");
      printf("  --help, -h                Show this help message\n");
      return 0;
    }
  }

  if (auth_user || auth_pass) {
    SetHTTPServerCredentials(auth_user, auth_pass);
  }

  if (http_only) {
    InitDBMinimal();
    RunHTTPServer(port);
    return 0;
  }

  State *s = CreateAppState();

  double t_res_start = GetTimeSeconds();
  CheckAndDownloadResources();
  double t_res_end = GetTimeSeconds();
  s->time_resource_download = t_res_end - t_res_start;

  double t_voice_start = GetTimeSeconds();
  VoiceRec_Init("./resources/model");
  double t_voice_end = GetTimeSeconds();
  s->time_voice_init = t_voice_end - t_voice_start;

  static VoiceRecApi voiceApi = {.Init = VoiceRec_Init,
                                 .Shutdown = VoiceRec_Shutdown,
                                 .StartRecording = VoiceRec_StartRecording,
                                 .StopRecording = VoiceRec_StopRecording,
                                 .IsRecording = VoiceRec_IsRecording,
                                 .PollResult = VoiceRec_PollResult,
                                 .PollPartial = VoiceRec_PollPartial};
  s->voiceApi = &voiceApi;

#if defined(__EMSCRIPTEN__) || defined(STATIC_BUILD)
  SetConfigFlags(FLAG_WINDOW_RESIZABLE);
  double t_win_start = GetTimeSeconds();
#ifdef __EMSCRIPTEN__
  InitWindow(800, 500, "LCARS Custom Elbow");
#else
  InitWindow(1600, 900, "LCARS ");
#endif
  double t_win_end = GetTimeSeconds();
  s->time_window_init = t_win_end - t_win_start;
  Init(s, true);
#ifndef __EMSCRIPTEN__
  StartHTTPServer(port);
  SetTargetFPS(240);
  while (!WindowShouldClose()) {
    UpdateDrawFrame(s);
  }
  // Content edits are debounced (see CONTENT_SAVE_DEBOUNCE_SECONDS); flush
  // anything still pending before we exit so the last few edits aren't lost.
  FlushPendingSaves(s);
#else
  // Let browser control frame rate
  emscripten_set_main_loop_arg((em_arg_callback_func)UpdateDrawFrame, s, 0, 1);
#endif
#else
  SetConfigFlags(FLAG_WINDOW_RESIZABLE);
  double t_win_start = GetTimeSeconds();
  InitWindow(1600, 900, "LCARS ");
  double t_win_end = GetTimeSeconds();
  s->time_window_init = t_win_end - t_win_start;
  Fn_Update Update = NULL;
  Fn_Init Init = NULL;
  Fn_Reload Reload = NULL;
  Fn_FlushPendingSaves FlushPendingSaves = NULL;

  int reload_counter = 0;
  if (!LoadAppLibrary(&reload_counter, &Update, &Init, &Reload,
                      &FlushPendingSaves)) {
    return 1;
  }

  // Initialize global state
  Init(s, true);
  StartHTTPServer(port);
  SetTargetFPS(240);
  while (!WindowShouldClose()) {

    // Hot code reload library on 'R' key press
    if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyDown(KEY_LEFT_SHIFT) &&
        IsKeyPressed(KEY_R)) {
      printf("Reloading ...\n");
      if (system("make lcars-lib.so") != 0) {
        // The previously-loaded library is still in place, so this just
        // skips the reload rather than loading stale code and reporting
        // success.
        printf("Build failed, skipping reload.\n");
        UpdateNotification(s, StringStatic("LCARS build failed!"));
      } else if (LoadAppLibrary(&reload_counter, &Update, &Init, &Reload,
                                &FlushPendingSaves)) {
        Reload(s, false);
        printf("Reloaded successfully.\n");
        UpdateNotification(s, StringStatic("LCARS reloaded successfully!"));
      } else {
        UpdateNotification(s, StringStatic("LCARS reload failed!"));
      }
    }
    Update(s);
  }
  if (FlushPendingSaves) {
    FlushPendingSaves(s);
  }
#endif

  VoiceRec_Shutdown();

  CloseWindow();
  return 0;
}

#include "lcars_resources_download.c"
#include "lcars_voice_rec.c"
