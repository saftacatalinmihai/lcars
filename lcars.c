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
typedef void (*Fn_Init  )(State *s, bool firstInit);
typedef void (*Fn_Reload)(State *s, bool reset);
#endif
// 1

int main(void) {

    State *s = (State*)calloc(sizeof(State), 10); // Reserve some more space just in case we add more fields... hack

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

    void *handle = dlopen("./lcars-lib.so", RTLD_NOW);
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

            // Leaking memory - old dl still in mem.
            /* dlclose(handle); */
            handle = dlopen("./lcars-lib.so", RTLD_NOW);
            Update = (Fn_Update)dlsym(handle, "UpdateDrawFrame");
            Init = (Fn_Init)dlsym(handle, "Init");
            Reload = (Fn_Reload)dlsym(handle, "Reload");
            Reload(s, false);
            printf("Reloaded successfully.\n");
            updateNotification(s, "LCARS reloaded successfully!");

        }
        Update(s);
    }
#endif

    CloseWindow();
    return 0;
}
