#include <stdio.h>
#include "raygui.h"
#include "raylib.h"
#include "rlgl.h"

#define LCARS_PURPLE (Color){ 206, 153, 205, 255 }
#define LCARS_RED_ORANGE (Color){ 204, 102, 102, 255 }
#define LCARS_ORANGE (Color){ 255, 154, 102, 255 }
#define LCARS_YELLOW (Color){ 255, 205, 154, 255 }

// Static buffers to avoid memory leaks from sprintf_alloc
static char sliderText[10][32 * 1024];
typedef struct State {
    Color lcarsColor;
    float posX, posY, columnWidth, columnHeight, barWidth, barHeight, innerRadius;
    bool debug;
    bool hide_controlls;
    int controllsX;
    int controllsY;
    bool textBoxEditMode;
} State;

void UpdateDrawFrame(State *s);
void Init(State *s);

// #define LCARS_IMPLEMENTATION // TEMP
#ifdef LCARS_IMPLEMENTATION
char* sprintf_static(int index, const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(sliderText[index], sizeof(sliderText[index]), fmt, args);
    va_end(args);
    return sliderText[index];
}

#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MIN(a,b) ((a) < (b) ? (a) : (b))

// Orientation: 0 - corner at top-left, 1 - corner at top-right, 2 - corner at bottom-right, 3 - corner at bottom-left
void DrawElbow(int posX, int posY, int columnWidth, int columnHeight, int barWidth, int barHeight, int innerRadius,  Color color, int orientation, bool debug) {
    switch (orientation) {
        case 0:
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
            break;
    case 1:
        break;
    case 2:
        break;
    case 3:
        if (columnWidth >= barHeight + innerRadius) {
            DrawRectangle(posX, posY,columnWidth,columnHeight, color); // Vertical bar
            DrawRectangle(posX + columnWidth + innerRadius , posY + columnHeight + innerRadius, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
            Vector2 center = { posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - barHeight };
            DrawCircleSector(center, innerRadius + barHeight, 0, 90, 0, debug ? BLUE : color); // Elbow curve
            DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - barHeight, columnWidth - barHeight - innerRadius, barHeight + innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
            DrawRing((Vector2){ posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius }, innerRadius, innerRadius + barHeight, 0, 90, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        }
        // if (barHeight >= columnWidth + innerRadius) {
        //     DrawRectangle(posX, posY,columnWidth,columnHeight, color); // Vertical bar
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
        //     Vector2 center = { posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - barHeight };
        //     DrawCircleSector(center, innerRadius + columnWidth, 0, 90, 0, debug ? BLUE : color); // Elbow curve
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - columnWidth, columnWidth + innerRadius - barHeight, barHeight - columnWidth - innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
        //     DrawRing((Vector2){ posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius }, innerRadius, innerRadius + columnWidth, 0, 90, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        // }
        break;
    }
}

void Init(State *s) {
    s->debug = false;
    s->hide_controlls = false;
    s->controllsX = 400;
    s->controllsY = 470;
    s->lcarsColor = (Color){ 204, 153, 204, 255 }; // Purple
    s->posX = 40;
    s->posY = 250;
    s->columnWidth = 200;
    s->columnHeight = 40;
    s->barWidth = 400;
    s->barHeight = 20;
    s->innerRadius = 40;

    GuiLoadStyle("style_cyber.rgs");
}

void Reload(State *s, bool reset) {
    if (reset){
        Init(s);
    } else {
        GuiLoadStyle("style_cyber.rgs");
    }
}

void UpdateDrawFrame(State *s) {
    if (IsKeyPressed(KEY_D)) {s->debug = !s->debug;}
    if (IsKeyPressed(KEY_H)) {s->hide_controlls = !s->hide_controlls;}

    BeginDrawing();
        ClearBackground(BLACK);

        DrawElbow(s->posX, 0, s->columnWidth, s->columnHeight, s->barWidth, s->barHeight, s->innerRadius, LCARS_PURPLE, 3, s->debug);
        DrawElbow(s->posX, s->posY, s->columnWidth, s->columnHeight, s->barWidth, s->barHeight, s->innerRadius, LCARS_RED_ORANGE, 0, s->debug);
        int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;
        DrawRectangle(s->posX, y + 3, s->columnWidth, 200, LCARS_RED_ORANGE); y = y + 200 + 3;
        DrawRectangle(s->posX, y + 3, s->columnWidth, 60, LCARS_ORANGE); y = y + 60 + 3;
        DrawRectangle(s->posX, y + 3, s->columnWidth, 250, LCARS_ORANGE); y = y + 250 + 3;

        int x = s->posX + s->columnWidth + s->barWidth;
        DrawRectangle(x + 3, s->posY, 40, s->barHeight, LCARS_YELLOW); x = x + 40 + 3;
        DrawRectangle(x + 3, s->posY, 140, s->barHeight / 2, LCARS_YELLOW); x = x + 140 + 3;
        DrawRectangle(x + 3, s->posY, 400, s->barHeight, LCARS_PURPLE); x = x + 400 + 3;
        DrawRectangle(x + 3, s->posY, 40, s->barHeight, LCARS_ORANGE); x = x + 40 + 3;

        if (!s->hide_controlls) {
        int i = 0;
        GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Col W ", sprintf_static(i, "%.0f", s->columnWidth) ,         &s->columnWidth , 0, 300); i++;
        GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Bar H ", sprintf_static(i, "%.0f", s->barHeight)   , &s->barHeight   , 0, 300); i++;
        GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Radius", sprintf_static(i, "%.0f", s->innerRadius) , &s->innerRadius , 0, 50 ); i++;
        GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Col H ", sprintf_static(i, "%.0f", s->columnHeight), &s->columnHeight, 0, 600); i++;
        GuiSliderBar((Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Bar W ", sprintf_static(i, "%.0f", s->barWidth)    , &s->barWidth    , 0, 600); i++;
        GuiToggle(   (Rectangle){.x=s->controllsX,       .y=s->controllsY + i * 30, .width=120, .height=20}, "Debug (d)", &s->debug); i++;
        GuiToggle(   (Rectangle){.x=s->controllsX + 130, .y=s->controllsY + (i - 1) * 30, .width=120, .height=20}, "Hide controlls (h)",&s->hide_controlls);

        char* code = sprintf_static(
                    i, "DrawElbow(%.0f, %.0f, %.0f, %.0f, %.0f, %.0f, %.0f, lcarsColor, %s);", 
                    s->posX, s->posY, s->columnWidth, s->columnHeight, s->barWidth, s->barHeight, s->innerRadius, s->debug ? "true" : "false"
                );

       if (GuiTextBox((Rectangle){.x=s->controllsX, .y=s->controllsY + i * 30, .width=500, .height=50},
               code,
               22,
               0)) {s->textBoxEditMode = !s->textBoxEditMode;} 
        i+=2;

        if (s->debug) DrawFPS(10, 10);
    }
    EndDrawing();
}
#endif // LCARS_IMPLEMENTATION
