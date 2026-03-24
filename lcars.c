
#include <stdio.h>
#define RAYGUI_IMPLEMENTATION
#include "raygui.h"
#include "raylib.h"
#include "rlgl.h"

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#endif

// Static buffers to avoid memory leaks from sprintf_alloc
static char sliderText[10][32 * 1024];

char* sprintf_static(int index, const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(sliderText[index], sizeof(sliderText[index]), fmt, args);
    va_end(args);
    return sliderText[index];
}

#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MIN(a,b) ((a) < (b) ? (a) : (b))

void DrawElbow(int posX, int posY, int columnWidth, int columnHeight, int barWidth, int barHeight, int innerRadius,  Color color, bool debug) {
    if (columnWidth >= barHeight + innerRadius) {
        DrawRectangle(posX, posY + barHeight + innerRadius,columnWidth,columnHeight, color); // Vertical bar
        DrawRectangle(posX + columnWidth, posY, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
        Vector2 center = { posX + barHeight + innerRadius, posY + barHeight + innerRadius };
        DrawCircleSector(center, innerRadius + barHeight, 180, 270, 0, debug ? BLUE : color); // Elbow curve
        DrawRectangle(posX + barHeight + innerRadius, posY, columnWidth - barHeight - innerRadius, barHeight + innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
        DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + barHeight + innerRadius }, innerRadius, innerRadius + barHeight, 180, 270, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    if (barHeight >= columnWidth + innerRadius) {
        DrawRectangle(posX, posY + barHeight ,columnWidth,columnHeight, color); // Vertical bar
        DrawRectangle(posX + columnWidth + innerRadius, posY, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
        Vector2 center = { posX + columnWidth + innerRadius, posY + columnWidth + innerRadius };
        DrawCircleSector(center, innerRadius + columnWidth, 180, 270, 0, debug ? BLUE : color); // Elbow curve
        DrawRectangle(posX, posY + columnWidth + innerRadius, columnWidth + innerRadius, barHeight - columnWidth -  innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
        DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + barHeight + innerRadius }, innerRadius, innerRadius + columnWidth, 180, 270, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
    }
}

// Global state for UpdateDrawFrame
static Color lcarsColor;
static float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
static bool debug;

static int controllsX = 200;
static int controllsY = 150;
static bool textBoxEditMode;

void UpdateDrawFrame(void) {
    if (IsKeyPressed(KEY_D)) {debug = !debug;}

    BeginDrawing();
        ClearBackground(BLACK);

        DrawElbow(posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius, lcarsColor, debug);

        int i = 0;
        GuiSliderBar((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Col W ", sprintf_static(i, "%.0f", columnWidth) , &columnWidth , 0, 300); i++;
        GuiSliderBar((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Bar H ", sprintf_static(i, "%.0f", barHeight)   , &barHeight   , 0, 300); i++;
        GuiSliderBar((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Radius", sprintf_static(i, "%.0f", innerRadius) , &innerRadius , 0, 50 ); i++;
        GuiSliderBar((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Col H ", sprintf_static(i, "%.0f", columnHeight), &columnHeight, 0, 600); i++;
        GuiSliderBar((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Bar W ", sprintf_static(i, "%.0f", barWidth)    , &barWidth    , 0, 600); i++;
        GuiToggle(   (Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=120, .height=20}, "Debug (d)", &debug); i++;

        char* code = sprintf_static(
                    i, "DrawElbow(%.0f, %.0f, %.0f, %.0f, %.0f, %.0f, %.0f, lcarsColor, %s);", 
                    posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius, debug ? "true" : "false"
                );

        if (GuiTextBox((Rectangle){.x=controllsX, .y=controllsY + i * 30, .width=500, .height=50},
               code,
               22,
               0)) {textBoxEditMode = !textBoxEditMode;} 
        i+=2;

        if (debug) DrawFPS(10, 10);
    EndDrawing();
}

int main(void) {
    /* SetConfigFlags(FLAG_WINDOW_RESIZABLE); */
    /* SetConfigFlags(FLAG_WINDOW_HIGHDPI); */
    InitWindow(800, 450, "LCARS Custom Elbow");

    GuiLoadStyle("style_cyber.rgs");

    // Initialize global state
    lcarsColor = (Color){ 204, 153, 204, 255 }; // Purple
    posX = 40;
    posY = 40;
    columnWidth = 100;
    columnHeight = 200;
    barWidth = 500;
    barHeight = 20;
    innerRadius = 20;

#ifdef __EMSCRIPTEN__
    // Let browser control frame rate
    emscripten_set_main_loop(UpdateDrawFrame, 0, 1);
#else
    SetTargetFPS(120);
    while (!WindowShouldClose()) {
        UpdateDrawFrame();
    }
#endif

    CloseWindow();
    return 0;
}
