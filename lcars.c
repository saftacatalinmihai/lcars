
#include <stdio.h>
#ifdef __EMSCRIPTEN__
#endif
#include "lcars_lib.h"
#include "raylib.h"
#include "rlgl.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#else 
typedef void (*Fn_Update)(State *s);
typedef void (*Fn_Init  )(State *s);
typedef void (*Fn_Reload)(State *s, bool reset);
#endif

int main(void) {

    State *s = (State*)calloc(sizeof(State), 1);

#ifdef __EMSCRIPTEN__
    SetConfigFlags(FLAG_WINDOW_RESIZABLE);
    InitWindow(800, 500, "LCARS Custom Elbow");
    // Let browser control frame rate
    Init(s);
    emscripten_set_main_loop_arg((em_arg_callback_func)UpdateDrawFrame, s, 0, 1);
#else
    SetConfigFlags(FLAG_WINDOW_RESIZABLE);
    InitWindow(1600, 900, "LCARS Custom Elbow");
    Fn_Update Update = NULL;
    Fn_Init Init = NULL;
    Fn_Reload Reload = NULL;

    void *handle = dlopen("./lcars-lib.so", RTLD_NOW);
    if (handle) {
        Update = (Fn_Update)dlsym(handle, "UpdateDrawFrame");
        Init = (Fn_Init)dlsym(handle, "Init");
        Reload = (Fn_Reload)dlsym(handle, "Reload");
        printf("Library loaded successfully.\n");
    } else {
        printf("Failed to load library: %s\n", dlerror());
        return 1;
    }

    // Initialize global state
    Init(s);
    SetTargetFPS(120);
    while (!WindowShouldClose()) {

        //Hot code reload library on 'R' key press
        if (IsKeyPressed(KEY_R)) {
            printf("Reloading library...\n");
            system("make lcars-lib.so");

            // Leaking memory - old dl still in mem.
            void *h = dlopen("./lcars-lib.so", RTLD_NOW);
            Update = (Fn_Update)dlsym(h, "UpdateDrawFrame");
            Init = (Fn_Init)dlsym(h, "Init");
            Reload = (Fn_Reload)dlsym(h, "Reload");
            if (IsKeyDown(KEY_LEFT_SHIFT)) {
                Reload(s, false);
                printf("Library reloaded successfully.\n");
            } else {
                Reload(s, true);
                printf("Library reloaded and state reset successfully.\n");
            }
        }
        Update(s);
    }
#endif

    CloseWindow();
    return 0;
}
