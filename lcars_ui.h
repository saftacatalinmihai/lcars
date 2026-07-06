#ifndef LCARS_UI_H
#define LCARS_UI_H

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
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {*x_cursor + gap, y},
                                            .width = width,
                                            .height = height,
                                            .color = color,
                                            .originalColor = color};
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
  s->elements[s->numElements++] = (Element){.kind = ELEM_ELBOW,
                                            .elbowOrientation = 3,
                                            .position = {s->posX, yu - gap},
                                            .width = &s->columnWidth,
                                            .height = &s->columnHeight,
                                            .color = LCARS_BLUE};
  yu -= gap;
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_RECTANGLE,
                .position = {s->posX, yu - 100 - gap},
                .width = &s->columnWidth,
                .height = &h100,
                .color = LCARS_PURPLE,
                .text = temp[1].text,
                .textSize = temp[1].textSize};
  yu -= 100;

  int xu = s->posX + s->columnWidth + s->barWidth;
  int yu_bar = s->posY - s->barHeight - gap;
  AddBarSegment(s, &xu, yu_bar, &w[0], &s->barHeight, LCARS_ORANGE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[1], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &xu, yu_bar, &w[3], &s->barHeight, LCARS_RED_ORANGE, gap);

  // Lower elbo
  s->elements[s->numElements++] = (Element){.kind = ELEM_ELBOW,
                                            .position = {s->posX, s->posY},
                                            .width = &s->columnWidth,
                                            .height = &s->columnHeight,
                                            .color = LCARS_RED_ORANGE,
                                            .text = StringStatic("03-975883"),
                                            .textSize = 20};
  int y = s->posY + s->columnHeight + s->barHeight + s->innerRadius;

  h200_60_250[0] = 200;
  h200_60_250[1] = 60;
  h200_60_250[2] = 250;

  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[0],
                                            .color = LCARS_RED_ORANGE,
                                            .text = StringStatic("04-785466"),
                                            .on_click = ACTION_PRINT_DB,
                                            .textSize = 20};
  y = y + 200 + gap;
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[1],
                                            .color = LCARS_ORANGE,
                                            .text = StringStatic("05-423512"),
                                            .textSize = 20};
  y = y + 60 + gap;
  s->elements[s->numElements++] = (Element){.kind = ELEM_RECTANGLE,
                                            .position = {s->posX, y + gap},
                                            .width = &s->columnWidth,
                                            .height = &h200_60_250[2],
                                            .color = LCARS_ORANGE,
                                            .text = StringStatic("06-572983"),
                                            .textSize = 20};
  y = y + 250 + gap;

  int x = s->posX + s->columnWidth + s->barWidth;
  halfBarHeight = s->barHeight / 2;
  AddBarSegment(s, &x, s->posY, &w[0], &s->barHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[1], &halfBarHeight, LCARS_YELLOW, gap);
  AddBarSegment(s, &x, s->posY, &w[2], &s->barHeight, LCARS_PURPLE, gap);
  AddBarSegment(s, &x, s->posY, &w[3], &s->barHeight, LCARS_ORANGE, gap);

  buttonHeight = 50;
  w210 = 210;
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_BUTTON,
                .on_click = ACTION_DEBUG,
                .position = {x - 220, s->posY - 20 - s->barHeight -
                                          2 * buttonHeight - 10},
                .width = &w210,
                .height = &buttonHeight,
                .color = LCARS_ORANGE,
                .text = StringStatic("(LC+d)ebug 9888-24"),
                .textSize = 20};
  s->elements[s->numElements++] =
      (Element){.kind = ELEM_BUTTON,
                .on_click = ACTION_EDIT,
                .position = {x - 220 - 220, s->posY - 20 - s->barHeight -
                                                2 * buttonHeight - 10},
                .width = &w210,
                .height = &buttonHeight,
                .color = LCARS_BLUE,
                .text = StringStatic("(LC+e)edit 0129-86"),
                .textSize = 20};
  s->elements[s->numElements++] = (Element){
      .kind = ELEM_BUTTON,
      .on_click = ACTION_RESET,
      .position = {x - 220, s->posY - 20 - s->barHeight - buttonHeight},
      .width = &w210,
      .height = &buttonHeight,
      .color = LCARS_BLUE,
      .text = StringStatic("(LC+r)eset 7232-83"),
      .textSize = 20};

  VoiceRecApi *vapi = (VoiceRecApi *)s->voiceApi;
  bool isRecording = (vapi && vapi->IsRecording());
  s->elements[s->numElements++] = (Element){
      .kind = ELEM_BUTTON,
      .on_click = ACTION_VOICE_INPUT,
      .position = {x - 220 - 220, s->posY - 20 - s->barHeight - buttonHeight},
      .width = &w210,
      .height = &buttonHeight,
      .color = isRecording ? RED : LCARS_BLUE,
      .originalColor = LCARS_BLUE,
      .text = StringStatic(isRecording ? TEXT_RECORDING : TEXT_VOICE_INPUT),
      .textSize = 20};

  s->elements[s->numElements++] =
      (Element){.kind = ELEM_BUTTON,
                .on_click = ACTION_LOAD_HYPERMEDIA,
                .position = {x - 220 - 220 - 220,
                             s->posY - 20 - s->barHeight - buttonHeight},
                .width = &w210,
                .height = &buttonHeight,
                .color = LCARS_YELLOW,
                .originalColor = LCARS_YELLOW,
                .text = StringStatic("http://localhost:8000/main.html"),
                .textSize = 20};

  s->elements[s->numElements++] =
      (Element){.kind = ELEM_TEXT,
                .position = {x - 220 - 220 - 20, yu},
                .color = LCARS_YELLOW,
                .textSize = 48,
                .text = StringStatic("LCARS ACCESS 441")};
}
#endif

static void clickOrHoverNotification(State *s, int i, String elem_pretty_name) {
  if (IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ||
      s->notificationOnElemIdx != i) {
    String buf = {0};
    const char *action =
        IsMouseButtonPressed(MOUSE_LEFT_BUTTON) ? "Clicked" : "Hovering";
    StringFormat(&s->scratch_arena, &buf, "[%s %s %d] %s", action,
                 elem_pretty_name.data ? elem_pretty_name.data : "", i,
                 s->elements[i].text.data ? s->elements[i].text.data : "");
    updateNotification(s, buf);
    StringFree(&buf);
    s->notificationOnElemIdx = i;
  }
}

static Rectangle GetElementBoundingBox(const Element *e) {
  float w = 0;
  float h = 0;
  if (e->kind == ELEM_TEXT) {
    if (e->width == NULL)
      w = MeasureText(e->text.data ? e->text.data : "", e->textSize);
    if (e->height == NULL)
      h = e->textSize;
  } else {
    w = e->width != NULL ? *e->width : 0;
    h = e->height != NULL ? *e->height : 0;
  }
  return (Rectangle){(float)e->position.x, (float)e->position.y, w, h};
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
