#ifndef LCARS_UI_H
#define LCARS_UI_H

#include "lcars_types.h"

static void clickOrHoverNotification(State *s, int i, String elem_pretty_name);
static Rectangle GetElementBoundingBox(State *s, Element *e);
static bool IsHoveringElement(State *s, Element *e);
static void DrawElbow(int posX, int posY, int columnWidth, int columnHeight,
                      int barWidth, int barHeight, int innerRadius, Color color,
                      int orientation, bool debug);
static ScrollbarLayout ComputeScrollbarLayout(Element *e, float editorX,
                                              float editorWidth);
static EntryListLayout ComputeEntryListLayout(Element *e);

#ifdef LCARS_IMPLEMENTATION

// Computes the geometry of a text editor's vertical scrollbar (bounds,
// up/down buttons, track, and drag handle) from the element's current
// height/textHeight/scrollY. Pure function of `e` and the editor's screen
// position — safe to call from both input handling and drawing, and the
// only place this geometry should be computed so the two can't diverge.
static ScrollbarLayout ComputeScrollbarLayout(Element *e, float editorX,
                                              float editorWidth) {
  ScrollbarLayout sb = {0};
  sb.bounds = (Rectangle){editorX + editorWidth + 25, e->position.y, 24.0f,
                          *e->height};
  sb.upButton =
      (Rectangle){sb.bounds.x, sb.bounds.y, sb.bounds.width, sb.bounds.width};
  sb.downButton = (Rectangle){sb.bounds.x,
                              sb.bounds.y + sb.bounds.height - sb.bounds.width,
                              sb.bounds.width, sb.bounds.width};
  sb.track = (Rectangle){sb.bounds.x, sb.bounds.y + sb.bounds.width + 5,
                         sb.bounds.width,
                         sb.bounds.height - 2 * sb.bounds.width - 10};

  float visibleRatio = *e->height / e->textHeight;
  if (visibleRatio > 1.0f)
    visibleRatio = 1.0f;
  float handleHeight = visibleRatio * sb.track.height;
  if (handleHeight < 20.0f)
    handleHeight = 20.0f;

  sb.scrollRange = e->textHeight - *e->height;
  float handleY = sb.track.y;
  if (sb.scrollRange > 0.0f) {
    handleY += (e->scrollY / sb.scrollRange) * (sb.track.height - handleHeight);
  }
  sb.handle = (Rectangle){sb.bounds.x, handleY, sb.bounds.width, handleHeight};

  return sb;
}

// Computes the geometry of an ELEM_ENTRY_LIST's left-hand panel (width,
// panel/toggle/new-entry button rects, header/item metrics) from the
// element's current position/height/listCollapsed. Pure function of `e` —
// the single source of truth for this panel's layout so input handling,
// drawing, and the text renderer's cursor-visibility check can't disagree
// about it (they previously did: lcars_text.h used a stale 220px width
// where everywhere else used 350px).
static EntryListLayout ComputeEntryListLayout(Element *e) {
  EntryListLayout el = {0};
  el.width = e->listCollapsed ? 30.0f : 350.0f;
  el.panelRec = (Rectangle){e->position.x, e->position.y, el.width, *e->height};
  el.toggleBtn = (Rectangle){e->position.x, e->position.y, 30.0f, 30.0f};
  el.newEntryBtn = (Rectangle){e->position.x + 35.0f, e->position.y,
                               el.width - 50.0f, 30.0f};
  el.headerHeight = 45.0f;
  el.itemStride = 90.0f;
  el.itemHeight = 80.0f;
  el.viewportHeight = *e->height - el.headerHeight;
  return el;
}

static void clickOrHoverNotification(State *s, int i, String elem_pretty_name) {
  if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ||
      s->notificationOnElemIdx != i) {
    String buf = {0};
    const char *action =
        IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ? "Clicked" : "Hovering";
    StringFormat(&s->scratch_arena, &buf, "[%s %s %d] %.*s", action,
                 elem_pretty_name.data ? elem_pretty_name.data : "", i,
                 NOTIFICATION_MAX_LEN,
                 s->elements[i].text.data ? s->elements[i].text.data : "");
    updateNotification(s, buf);
    StringFree(&buf);
    s->notificationOnElemIdx = i;
  }
}

static Rectangle GetElementBoundingBox(State *s, Element *e) {
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
    return CheckCollisionPointRec(GetMousePosition(),
                                  GetElementBoundingBox(s, e));
  }

  case ELEM_ELBOW:
    // For elbows, we might want to expand the bounding box slightly to
    // account for the elbow curve. This is a simple approximation.
    switch (e->elbowOrientation) {
    case 0:
      return CheckCollisionPointRec(GetMousePosition(),
                                    (Rectangle){.x = e->position.x,
                                                .y = e->position.y,
                                                .width = *(e->width),
                                                .height = *(e->height) +
                                                          s->barHeight +
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
      return CheckCollisionPointRec(GetMousePosition(),
                                    (Rectangle){.x = e->position.x,
                                                .y = e->position.y,
                                                .width = *(e->width),
                                                .height = *(e->height) +
                                                          s->barHeight +
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

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_UI_H
