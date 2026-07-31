#ifndef LCARS_UI_H
#define LCARS_UI_H

#include "liblcars.h"

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
