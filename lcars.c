#include <stdio.h>
#ifdef __EMSCRIPTEN__
#endif
#include "lcars_lib.h"
#include "raylib.h"
#include "rlgl.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>
#include "voice_rec.h"
#include "resources_download.h"

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#else 
typedef void (*Fn_Update)(State *s);
typedef void (*Fn_Init  )(State *s, bool firstInit);
typedef void (*Fn_Reload)(State *s, bool reset);
#endif
// 1

int main(void) {

    State *s = (State*)calloc(10, sizeof(State)); // Reserve some more space just in case we add more fields... hack
    
    CheckAndDownloadResources();
    
    VoiceRec_Init("./resources/model");
    static VoiceRecApi voiceApi = {
        .Init = VoiceRec_Init,
        .Shutdown = VoiceRec_Shutdown,
        .StartRecording = VoiceRec_StartRecording,
        .StopRecording = VoiceRec_StopRecording,
        .IsRecording = VoiceRec_IsRecording,
        .PollResult = VoiceRec_PollResult,
        .PollPartial = VoiceRec_PollPartial
    };
    s->voiceApi = &voiceApi;

    
    
#ifdef __EMSCRIPTEN__
    SetConfigFlags(FLAG_WINDOW_RESIZABLE);
    InitWindow(800, 500, "LCARS Custom Elbow");
    Init(s, true);
    // Let browser control frame rate
    emscripten_set_main_loop_arg((em_arg_callback_func)UpdateDrawFrame, s, 0, 1);
#else
    SetConfigFlags(FLAG_WINDOW_RESIZABLE);
    InitWindow(1600, 900, "LCARS ");
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
    SetTargetFPS(240);
    while (!WindowShouldClose()) {

        //Hot code reload library on 'R' key press
        if (IsKeyDown(KEY_LEFT_CONTROL) && IsKeyDown(KEY_LEFT_SHIFT) && IsKeyPressed(KEY_R)) {
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
                updateNotification(s, "LCARS reloaded successfully!");
            }

        }
        Update(s);
    }
#endif

    VoiceRec_Shutdown();

    CloseWindow();
    return 0;
}
