#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#ifdef __EMSCRIPTEN__
#endif
#include "liblcars.h"
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
#endif

static void InitDBMinimal(void) {
  State *s =
      (State *)calloc(10, sizeof(State)); // Reserve some more space just in
                                          // case we add more fields... hack

  // Preallocate backing buffers for the memory arenas
  size_t doc_arena_size = 32 * 1024 * 1024;     // 32 MB
  size_t scratch_arena_size = 16 * 1024 * 1024; // 16 MB
  void *doc_backing = malloc(doc_arena_size);
  void *scratch_backing = malloc(scratch_arena_size);
  if (!doc_backing || !scratch_backing) {
    fprintf(stderr, "Fatal error: Failed to preallocate memory arenas for "
                    "minimal DB init\n");
    exit(1);
  }
  arena_init(&s->doc_arena, doc_backing, doc_arena_size);
  arena_init(&s->scratch_arena, scratch_backing, scratch_arena_size);

  sqlite3 *db = NULL;
  int rc = sqlite3_open("lcars.db", &db);
  if (rc) {
    fprintf(stderr, "Can't open database: %s\n", sqlite3_errmsg(db));
    exit(1);
  }
  s->db = db;

  InitDB(s, true);

  sqlite3_close(db);
  free(doc_backing);
  free(scratch_backing);
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
    } else if ((strcmp(argv[i], "--password") == 0 || strcmp(argv[i], "--pass") == 0) &&
               i + 1 < argc) {
      auth_pass = argv[++i];
    } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
      printf("Usage: %s [options]\n", argv[0]);
      printf("Options:\n");
      printf("  --http-only, -s, --server  Start only the API HTTP server (no UI, no voice rec)\n");
      printf("  --port, -p <port>         Specify HTTP server port (default: 8080)\n");
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

  State *s =
      (State *)calloc(10, sizeof(State)); // Reserve some more space just in
                                          // case we add more fields... hack

  // Preallocate backing buffers for the memory arenas
  size_t doc_arena_size = 32 * 1024 * 1024;     // 32 MB
  size_t scratch_arena_size = 16 * 1024 * 1024; // 16 MB
  void *doc_backing = malloc(doc_arena_size);
  void *scratch_backing = malloc(scratch_arena_size);
  if (!doc_backing || !scratch_backing) {
    fprintf(stderr, "Fatal error: Failed to preallocate memory arenas\n");
    return 1;
  }
  arena_init(&s->doc_arena, doc_backing, doc_arena_size);
  arena_init(&s->scratch_arena, scratch_backing, scratch_arena_size);

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

  int reload_counter = 0;
  char lib_path[256];
  sprintf(lib_path, "./lcars-lib_temp_%d.so", reload_counter++);
  char cp_cmd[512];
  sprintf(cp_cmd, "cp ./lcars-lib.so %s", lib_path);
  system(cp_cmd);

  void *handle = dlopen(lib_path, RTLD_NOW);
  unlink(lib_path);

  if (handle) {
    Update = (Fn_Update)dlsym(handle, "UpdateDrawFrame");
    if (Update == NULL) {
      printf("Failed to load UpdateDrawFrame: %s\n", dlerror());
      return 1;
    }
    Init = (Fn_Init)dlsym(handle, "Init");
    if (Init == NULL) {
      printf("Failed to load Init: %s\n", dlerror());
      return 1;
    }
    Reload = (Fn_Reload)dlsym(handle, "Reload");
    if (Reload == NULL) {
      printf("Failed to load Reload: %s\n", dlerror());
      return 1;
    }
    printf("Library loaded successfully.\n");
  } else {
    printf("Failed to load library: %s\n", dlerror());
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
      system("make lcars-lib.so");

      sprintf(lib_path, "./lcars-lib_temp_%d.so", reload_counter++);
      sprintf(cp_cmd, "cp ./lcars-lib.so %s", lib_path);
      system(cp_cmd);

      handle = dlopen(lib_path, RTLD_NOW);
      unlink(lib_path);

      if (!handle) {
        printf("dlopen failed: %s\n", dlerror());
      } else {
        Update = (Fn_Update)dlsym(handle, "UpdateDrawFrame");
        Init = (Fn_Init)dlsym(handle, "Init");
        Reload = (Fn_Reload)dlsym(handle, "Reload");
        if (Reload) {
          Reload(s, false);
        }
        printf("Reloaded successfully.\n");
        updateNotification(s, StringStatic("LCARS reloaded successfully!"));
      }
    }
    Update(s);
  }
#endif

  VoiceRec_Shutdown();

  CloseWindow();
  return 0;
}
