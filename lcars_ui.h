#ifndef LCARS_UI_H
#define LCARS_UI_H

#include "liblcars.h"

#ifndef HYPERMEDIA
// Shared layout static variables
static float w600 = 600;
static float h400 = 400;
static float w300 = 300;
static float h300 = 300;

static float w[4];
static float h100;
static float h200_60_250[3];
static float halfBarHeight;
static float buttonHeight;
static float w210;

static void AddBarSegment(State *s, int *x_cursor, int y, float *width,
                          float *height, Color color, int gap) {
  Element e = {0};
  e.position = (iVec2){*x_cursor + gap, y};
  e.width = width;
  e.height = height;
  e.color = color;
  e.originalColor = color;
  make_rectangle(&e);
  s->elements[s->numElements++] = e;
  *x_cursor += (int)*width + gap;
}

static void ReLayout(State *s) {
  // Clone elements to preserve manually adjusted layouts and other elements
  Element temp[MAX_ELEMENTS];
  for (int i = 0; i < MAX_ELEMENTS; i++) {
    temp[i] = s->elements[i];
  }

  s->numElements =
      0; // Clear existing elements before re-adding them with new layout
  int gap = 6;

  w[0] = 40;
  w[1] = 140;
  w[2] = 400;
  w[3] = 40;

  // Upper elbow
  int yu = s->posY - s->columnHeight - s->innerRadius - s->barHeight;

  h100 = 100;
  Element e = {0};
  e.position = (iVec2){s->posX, yu - gap};
  e.width = &s->columnWidth;
  e.height = &s->columnHeight;
  e.color = LCARS_BLUE;
  e.originalColor = LCARS_BLUE;
  make_elbow(&e, 3);
  s->elements[s->numElements++] = e;

  yu -= gap;
  e = (Element){0};
  e.position = (iVec2){s->posX, yu - 100 - gap};
  e.width = &s->columnWidth;
  e.height = &h100;
  e.color = LCARS_PURPLE;
  e.originalColor = LCARS_PURPLE;
  e.text = temp[1].text;
  e.textSize = temp[1].textSize;
  make_rectangle(&e);
  s->elements[s->numElements++] = e;
  yu -= 100;

  int xu = s->posX + s->columnWidth + s->barWidth;
  int yu_bar = s->posY - s->barHeight - gap;
  AddBarSegment(s, &xu, yu_bar, &w[0], &s->barHeight, LCARS_ORANGE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[1], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[3], &s->barHeight, LCARS_RED_ORANGE, gap);

  // Lower elbo
  e = (Element){0};
  e.position = (iVec2){s->posX, s->posY};
  e.width = &s->columnWidth;
  e.height = &s->columnHeight;
  e.color = LCARS_RED_ORANGE;
  e.originalColor = LCARS_RED_ORANGE;
  e.text = StringStatic("03-975883");
  e.textSize = 20;
  make_elbow(&e, 0);
  s->elements[s->numElements++] = e;

  int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;

  h200_60_250[0] = 200;
  h200_60_250[1] = 60;
  h200_60_250[2] = 250;

  e = (Element){0};
  e.position = (iVec2){s->posX, y + gap};
  e.width = &s->columnWidth;
  e.height = &h200_60_250[0];
  e.color = LCARS_RED_ORANGE;
  e.originalColor = LCARS_RED_ORANGE;
  e.text = StringStatic("04-785466");
  e.on_click = ACTION_PRINT_DB;
  e.textSize = 20;
  make_rectangle(&e);
  s->elements[s->numElements++] = e;

  y = y + 200 + gap;
  e = (Element){0};
  e.position = (iVec2){s->posX, y + gap};
  e.width = &s->columnWidth;
  e.height = &h200_60_250[1];
  e.color = LCARS_ORANGE;
  e.originalColor = LCARS_ORANGE;
  e.text = StringStatic("05-423512");
  e.textSize = 20;
  make_rectangle(&e);
  s->elements[s->numElements++] = e;

  y = y + 60 + gap;
  e = (Element){0};
  e.position = (iVec2){s->posX, y + gap};
  e.width = &s->columnWidth;
  e.height = &h200_60_250[2];
  e.color = LCARS_ORANGE;
  e.originalColor = LCARS_ORANGE;
  e.text = StringStatic("06-572983");
  e.textSize = 20;
  make_rectangle(&e);
  s->elements[s->numElements++] = e;

  y = y + 250 + gap;

  int x = s->posX + s->columnWidth + s->barWidth;
  halfBarHeight = s->barHeight / 2;
  AddBarSegment(s, &x, s->posY, &w[0], &s->barHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[1], &halfBarHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &x, s->posY, &w[3], &s->barHeight, LCARS_ORANGE, gap);

  buttonHeight = 50;
  w210 = 210;
  e = (Element){0};
  e.position = (iVec2){x - 220, s->posY - 20 - s->barHeight - 2 * buttonHeight - 10};
  e.width = &w210;
  e.height = &buttonHeight;
  e.color = LCARS_ORANGE;
  e.originalColor = LCARS_ORANGE;
  e.text = StringStatic("(LC+d)ebug 9888-24");
  e.on_click = ACTION_DEBUG;
  e.textSize = 20;
  make_button(&e);
  s->elements[s->numElements++] = e;

  e = (Element){0};
  e.position = (iVec2){x - 220 - 220, s->posY - 20 - s->barHeight - 2 * buttonHeight - 10};
  e.width = &w210;
  e.height = &buttonHeight;
  e.color = LCARS_BLUE;
  e.originalColor = LCARS_BLUE;
  e.text = StringStatic("(LC+e)edit 0129-86");
  e.on_click = ACTION_EDIT;
  e.textSize = 20;
  make_button(&e);
  s->elements[s->numElements++] = e;

  e = (Element){0};
  e.position = (iVec2){x - 220, s->posY - 20 - s->barHeight - buttonHeight};
  e.width = &w210;
  e.height = &buttonHeight;
  e.color = LCARS_BLUE;
  e.originalColor = LCARS_BLUE;
  e.text = StringStatic("(LC+r)eset 7232-83");
  e.on_click = ACTION_RESET;
  e.textSize = 20;
  make_button(&e);
  s->elements[s->numElements++] = e;

  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  bool isRecording = (vapi && vapi->IsRecording());
  e = (Element){0};
  e.position = (iVec2){x - 220 - 220, s->posY - 20 - s->barHeight - buttonHeight};
  e.width = &w210;
  e.height = &buttonHeight;
  e.color = isRecording ? RED : LCARS_BLUE;
  e.originalColor = LCARS_BLUE;
  e.text = StringStatic(isRecording ? TEXT_RECORDING : TEXT_VOICE_INPUT);
  e.on_click = ACTION_VOICE_INPUT;
  e.textSize = 20;
  make_button(&e);
  s->elements[s->numElements++] = e;

  e = (Element){0};
  e.position = (iVec2){x - 220 - 220 - 220, s->posY - 20 - s->barHeight - buttonHeight};
  e.width = &w210;
  e.height = &buttonHeight;
  e.color = LCARS_YELLOW;
  e.originalColor = LCARS_YELLOW;
  e.text = StringStatic("http://localhost:8000/main.html");
  e.on_click = ACTION_LOAD_HYPERMEDIA;
  e.textSize = 20;
  make_button(&e);
  s->elements[s->numElements++] = e;

  e = (Element){0};
  e.position = (iVec2){x - 220 - 220 - 20, yu};
  e.color = LCARS_YELLOW;
  e.originalColor = LCARS_YELLOW;
  e.text = StringStatic("LCARS ACCESS 441");
  e.textSize = 48;
  make_text(&e);
  s->elements[s->numElements++] = e;
}
#endif

#define NOTIFICATION_MAX_LEN 48

static void clickOrHoverNotification(State *s, int i, String elem_pretty_name) {
  if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ||
      s->notificationOnElemIdx != i) {
    String buf = {0};
    const char *action =
        IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ? "Clicked" : "Hovering";
    StringFormat(&s->scratch_arena, &buf, "[%s %s %d] %.*s", action,
                 elem_pretty_name.data ? elem_pretty_name.data : "", i,
                 NOTIFICATION_MAX_LEN, s->elements[i].text.data ? s->elements[i].text.data : "");
    updateNotification(s, buf);
    StringFree(&buf);
    s->notificationOnElemIdx = i;
  }
}

static Rectangle GetElementBoundingBox(State* s, Element *e) {
  float w = 0;
  float h = 0;
    if (ELEM_TOTAL_KINDS != 8) {
        // If new element kinds are added, update this function to handle them.
        TODO;
    }
    switch (e->kind) {
        case ELEM_TEXT:
            if (e->width == NULL)
                w = MeasureText(e->text.data ? e->text.data : "", e->textSize);
            if (e->height == NULL)
                h = e->textSize;
            break;
        case ELEM_ELBOW:
            w = e->width != NULL ? *e->width + s->barWidth : 0;
            h = e->height != NULL ? *e->height + s->columnHeight + s->barHeight : 0;
            break;
        default:
            w = e->width != NULL ? *e->width : 0;
            h = e->height != NULL ? *e->height : 0;
            break;
    }
  return (Rectangle){(float)e->position.x, (float)e->position.y, w, h};
}

static bool IsHoveringElement(State *s, Element *e) {
  switch (e->kind) {
        case ELEM_RECTANGLE:
        case ELEM_BUTTON:
        case ELEM_TEXT:
        case ELEM_TEXT_EDITOR:
        case ELEM_ENTRY_LIST:
        case ELEM_SPHERE: {
            return CheckCollisionPointRec(GetMousePosition(), GetElementBoundingBox(s, e));
        }

        case ELEM_ELBOW:
            // For elbows, we might want to expand the bounding box slightly to
            // account for the elbow curve. This is a simple approximation.
            switch (e->elbowOrientation) {
                case 0:
                    return CheckCollisionPointRec(
                        GetMousePosition(),
                        (Rectangle){.x = e->position.x,
                            .y = e->position.y,
                            .width = *(e->width),
                            .height = *(e->height) + s->barHeight +
                            s->innerRadius}) ||
                    CheckCollisionPointRec(
                        GetMousePosition(),
                        (Rectangle){.x = e->position.x,
                            .y = e->position.y,
                            .width = s->columnWidth + s->barWidth,
                            .height = s->barHeight});
                case 1:
                case 2:
                    TODO;
                    return false;
                    break;
                case 3:
                    return CheckCollisionPointRec(
                        GetMousePosition(),
                        (Rectangle){.x = e->position.x,
                            .y = e->position.y,
                            .width = *(e->width),
                            .height = *(e->height) + s->barHeight +
                            s->innerRadius}) ||
                    CheckCollisionPointRec(
                        GetMousePosition(),
                        (Rectangle){.x = e->position.x,
                            .y = e->position.y + s->columnHeight +
                            s->innerRadius,
                            .width = s->columnWidth + s->barWidth,
                            .height = s->barHeight});
            };
            break;
        case ELEM_NOTHING:
        case ELEM_TOTAL_KINDS:
            return false;
            break;
    }
}

// Orientation: 0 - corner at top-left, 1 - corner at top-right, 2 - corner at
// bottom-right, 3 - corner at bottom-left
static void DrawElbow(int posX, int posY, int columnWidth, int columnHeight,
                      int barWidth, int barHeight, int innerRadius, Color color,
                      int orientation, bool debug) {
  switch (orientation) {
  case 0:
    if (columnWidth >= barHeight + innerRadius) {
      DrawRectangle(posX, posY + barHeight + innerRadius, columnWidth,
                    columnHeight, color); // Vertical bar
      DrawRectangle(posX + columnWidth, posY, barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + barHeight + innerRadius,
                        posY + barHeight + innerRadius};
      DrawCircleSector(center, innerRadius + barHeight, 180, 270, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX + barHeight + innerRadius, posY,
          columnWidth - barHeight - innerRadius, barHeight + innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius,
                         posY + barHeight + innerRadius},
               innerRadius, innerRadius + barHeight, 180, 270, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    if (barHeight >= columnWidth + innerRadius) {
      DrawRectangle(posX, posY + barHeight, columnWidth, columnHeight,
                    color); // Vertical bar
      DrawRectangle(posX + columnWidth + innerRadius, posY, barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + columnWidth + innerRadius,
                        posY + columnWidth + innerRadius};
      DrawCircleSector(center, innerRadius + columnWidth, 180, 270, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX, posY + columnWidth + innerRadius, columnWidth + innerRadius,
          barHeight - columnWidth - innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius,
                         posY + barHeight + innerRadius},
               innerRadius, innerRadius + columnWidth, 180, 270, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    break;
  case 1:
    break;
  case 2:
    break;
  case 3:
    if (columnWidth >= barHeight + innerRadius) {
      DrawRectangle(posX, posY, columnWidth, columnHeight,
                    color); // Vertical bar
      DrawRectangle(posX + columnWidth, posY + columnHeight + innerRadius,
                    barWidth, barHeight,
                    debug ? GREEN : color); // Horizontal bar
      Vector2 center = {posX + barHeight + innerRadius, posY + columnHeight};
      DrawCircleSector(center, innerRadius + barHeight, 90, 180, 0,
                       debug ? BLUE : color); // Elbow curve
      DrawRectangle(
          posX + barHeight + innerRadius, posY + columnHeight,
          columnWidth - barHeight - innerRadius, barHeight + innerRadius,
          debug ? ORANGE
                : color); // Fill the gap between the curve and the bars
      DrawRing((Vector2){posX + columnWidth + innerRadius, posY + columnHeight},
               innerRadius, innerRadius + barHeight, 90, 180, 0,
               debug ? MAGENTA : color); // Decorative ring around the elbow
    }
    break;
  }
}

#endif // LCARS_UI_H
