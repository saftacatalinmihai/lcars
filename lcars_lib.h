#include <stdio.h>
#include "raygui.h"
#include "raylib.h"
#include "rlgl.h"

#define LCARS_PURPLE (Color){ 206, 153, 205, 255 }
#define LCARS_RED_ORANGE (Color){ 204, 102, 102, 255 }
#define LCARS_ORANGE (Color){ 255, 154, 102, 255 }
#define LCARS_YELLOW (Color){ 255, 205, 154, 255 }
#define LCARS_BLUE (Color){ 155, 155, 255, 255 }

#define MAX_ELEMENTS 100
typedef struct iVec2 {
    int x, y;
} iVec2;

typedef enum ElemKind {
    ELEM_RECTANGLE = 0,
    ELEM_ELBOW,
    ELEM_BUTTON,
} ElemKind;

typedef struct Element {
    ElemKind kind;
    iVec2 position;
    float width, height;
    Color color;
    int elbowOrientation; // Only used if kind == ELBOW
    char* text; // Text on button  - optional
} Element;

// Static buffers to avoid memory leaks from sprintf_alloc
static char sliderText[10][32 * 1024];
typedef struct State {
    Element elements[MAX_ELEMENTS];
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

#define LCARS_IMPLEMENTATION // TEMP
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
            DrawRectangle(posX, posY, columnWidth, columnHeight, color); // Vertical bar
            DrawRectangle(posX + columnWidth , posY + columnHeight + innerRadius, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
            Vector2 center = { posX + barHeight + innerRadius, posY + columnHeight };
            DrawCircleSector(center, innerRadius + barHeight, 90, 180, 0, debug ? BLUE : color); // Elbow curve
            DrawRectangle(posX + barHeight + innerRadius, posY + columnHeight, columnWidth - barHeight - innerRadius, barHeight + innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
            DrawRing((Vector2){ posX + columnWidth + innerRadius, posY + columnHeight }, innerRadius, innerRadius + barHeight, 90, 180, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        }
        // if (barHeight >= columnWidth + innerRadius) {
        //     DrawRectangle(posX, posY,columnWidth,columnHeight, color); // Vertical bar
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight, barWidth, barHeight, debug ? GREEN : color); // Horizontal bar
        //     Vector2 center = { posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - barHeight };
        //     DrawCircleSector(center, innerRadius + columnWidth, 90, 180, 0, debug ? BLUE : color); // Elbow curve
        //     DrawRectangle(posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius - columnWidth, columnWidth + innerRadius - barHeight, barHeight - columnWidth - innerRadius, debug ? ORANGE : color); // Fill the gap between the curve and the bars
        //     DrawRing((Vector2){ posX + columnWidth - innerRadius - barHeight, posY + columnHeight - innerRadius }, innerRadius, innerRadius + columnWidth, 90, 180, 0, debug ? MAGENTA : color); // Decorative ring around the elbow
        // }
        break;
    }
}


float w[4] = {40, 140, 400, 40};

void Resize(State *s) {
    int elem_index = 0;

    int gap = 6;

    // Upper elbow
    int yu = s->posY - s->columnHeight - s->innerRadius - s->barHeight;

    s->elements[elem_index++] = (Element){ .kind = ELEM_ELBOW, .elbowOrientation = 3, .position = {s->posX, yu - gap}, .width = s->columnWidth, .height = s->columnHeight, .color = LCARS_BLUE }; yu -= gap;
    s->elements[elem_index++] = (Element){ .position = {s->posX, yu - 100 - gap}, .width = s->columnWidth, .height = 100, .color = LCARS_PURPLE }; yu -= 100;

    int xu = s->posX + s->columnWidth + s->barWidth;
    s->elements[elem_index++] = (Element){ .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[0], .height = s->barHeight, .color = LCARS_ORANGE }; xu += 40 + gap;
    s->elements[elem_index++] = (Element){ .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[1], .height = s->barHeight, .color = LCARS_PURPLE }; xu += 140 + gap;
    s->elements[elem_index++] = (Element){ .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[2], .height = s->barHeight, .color = LCARS_PURPLE }; xu += 400 + gap;
    s->elements[elem_index++] = (Element){ .position = {xu + gap, s->posY - s->barHeight - gap}, .width = w[3], .height = s->barHeight, .color = LCARS_RED_ORANGE }; xu += 40 + gap;

    // Lower elbow
    s->elements[elem_index++] = (Element){ .kind = ELEM_ELBOW, .position = {s->posX, s->posY}, .width = s->columnWidth, .height = s->columnHeight, .color = LCARS_RED_ORANGE, .text="03-975883"};
    int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;
    s->elements[elem_index++] = (Element){ .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 200, .color = LCARS_RED_ORANGE, .text="04-785466" }; y = y + 200 + gap;
    s->elements[elem_index++] = (Element){ .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 60, .color = LCARS_ORANGE, .text="05-423512" }; y = y + 60 + gap;
    s->elements[elem_index++] = (Element){ .position = {s->posX, y + gap}, .width = s->columnWidth, .height = 250, .color = LCARS_ORANGE, .text="06-572983" }; y = y + 250 + gap;

    int x = s->posX + s->columnWidth + s->barWidth;
    s->elements[elem_index++] = (Element){ .position = {x + gap, s->posY}, .width = w[0], .height = s->barHeight, .color = LCARS_YELLOW, }; x = x + 40 + gap;
    s->elements[elem_index++] = (Element){ .position = {x + gap, s->posY}, .width = w[1], .height = s->barHeight / 2, .color = LCARS_YELLOW }; x = x + 140 + gap;
    s->elements[elem_index++] = (Element){ .position = {x + gap, s->posY}, .width = w[2], .height = s->barHeight, .color = LCARS_PURPLE }; x = x + 400 + gap;
    s->elements[elem_index++] = (Element){ .position = {x + gap, s->posY}, .width = w[3], .height = s->barHeight, .color = LCARS_ORANGE }; x = x + 40 + gap;

    int buttonHeight = 50;
    s->elements[elem_index++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 210      , s->posY - 20 - s->barHeight - 2 * buttonHeight - 10 }, .width = 200, .height = buttonHeight, .color = LCARS_ORANGE, .text="9888-234" };
    s->elements[elem_index++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 210 - 210, s->posY - 20 - s->barHeight - 2 * buttonHeight - 10 }, .width = 200, .height = buttonHeight, .color = LCARS_BLUE, .text="0128-838" };
    s->elements[elem_index++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 210      , s->posY - 20 - s->barHeight - buttonHeight  }, .width = 200, .height = buttonHeight, .color = LCARS_BLUE, .text="7232-838" };
    s->elements[elem_index++] = (Element){ .kind=ELEM_BUTTON, .position = { x - 210 - 210, s->posY - 20 - s->barHeight - buttonHeight  }, .width = 200, .height = buttonHeight, .color = LCARS_ORANGE, .text="1014-819" };
}

void Init(State *s) {
    s->debug = false;
    s->hide_controlls = false;
    s->controllsX = 600;
    s->controllsY = 370;
    s->lcarsColor = (Color){ 204, 153, 204, 255 }; // Purple
    s->posX = 40;
    s->posY = 250;
    s->columnWidth = 200;
    s->columnHeight = 40;
    s->barWidth = 400;
    s->barHeight = 20;
    s->innerRadius = 40;

    Resize(s);
    
    GuiLoadStyle("style_cyber.rgs");
}
void Reload(State *s, bool reset) {
    if (reset){
        Init(s);
    } else {
        GuiLoadStyle("style_cyber.rgs");
    }
}

void Update(State *s) {
    Resize(s);
    for (int i = 0; i < MAX_ELEMENTS; i++) {
        switch (s->elements[i].kind) {
            case ELEM_RECTANGLE:
                if (CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width ? s->elements[i].width : 0, .height = s->elements[i].height})) {
                    s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
                        printf("Clicked element %d\n", i);
                    }
                }
                break;
            case ELEM_ELBOW:
                if (
                    CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height + s->barHeight + s->innerRadius}) ||
                    CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->columnWidth + s->barWidth, .height = s->barHeight})
                ) {
                    s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
                        printf("Clicked elbow element %d\n", i);
                    }
                }
                break;
            case ELEM_BUTTON:
                if (CheckCollisionPointRec(GetMousePosition(), (Rectangle){.x=s->elements[i].position.x, .y=s->elements[i].position.y, .width = s->elements[i].width, .height = s->elements[i].height})) {
                    s->elements[i].color = ColorBrightness(s->elements[i].color, 0.2f);
                    if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON)) {
                        printf("Clicked button element %d\n", i);
                    }
                }
                break;
            default:
                continue; // Skip uninitialized elements
        }
    }
}

void UpdateDrawFrame(State *s) {
    if (IsKeyPressed(KEY_D)) {s->debug = !s->debug;}
    if (IsKeyPressed(KEY_H)) {s->hide_controlls = !s->hide_controlls;}

    Update(s);

    BeginDrawing();
        ClearBackground(BLACK);
        for (int i = 0; i < MAX_ELEMENTS; i++) {
            Element *e = &s->elements[i];
            if (e->color.a == 0) continue; // Skip uninitialized elements
            switch (e->kind) {
                case ELEM_RECTANGLE:
                    DrawRectangle(e->position.x, e->position.y, e->width, e->height, e->color);
                    break;
                case ELEM_ELBOW:
                    DrawElbow(e->position.x, e->position.y, e->width, e->height, s->barWidth, s->barHeight, s->innerRadius, e->color, e->elbowOrientation, s->debug);
                    break;
                case ELEM_BUTTON:
                    DrawRectangleRounded((Rectangle){.x=e->position.x, .y=e->position.y, .width=e->width, .height=e->height}, 0.9f, 4, e->color);
                    break;
            }

            if (e->text) {
                int textWidth = MeasureText(e->text, 20);
                if (e->kind == ELEM_ELBOW) {
                    DrawText(e->text, e->position.x + 3 * (e->width - textWidth) / 4, e->position.y + s->barHeight + s->innerRadius + (e->height - 20) / 2, 20, BLACK);
                } else {
                    DrawText(e->text, e->position.x + 3 * (e->width - textWidth) / 4, e->position.y + (e->height - 20) / 2 + 10, 20, BLACK);
                }
            }
        }

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
