#ifndef LCARS_TEXT_H
#define LCARS_TEXT_H

#include "liblcars.h"

static int GetLines(String text, int *lineStarts, int maxLines) {
  int count = 0;
  lineStarts[count++] = 0;
  int len = text.len;
  for (int i = 0; i < len; i++) {
    if (text.data && text.data[i] == '\n') {
      if (count < maxLines) {
        lineStarts[count++] = i + 1;
      }
    }
  }
  return count;
}

static int GetLineForIndex(int index, const int *lineStarts, int numLines) {
  for (int i = 0; i < numLines - 1; i++) {
    if (index >= lineStarts[i] && index < lineStarts[i + 1]) {
      return i;
    }
  }
  return numLines - 1;
}

static int GetCharIndexAtMouse(const State *s, Font font, String text,
                               Vector2 textPos, float fontSize, float spacing,
                               Vector2 mousePos, float recWidth) {
  (void)s;
  if (text.data == NULL)
    return 0;
  int length = text.len;

  float textOffsetY = 0.0f;
  float textOffsetX = 0.0f;

  float scaleFactor = fontSize / (float)font.baseSize;
  float lineHeight = (font.baseSize + (float)font.baseSize / 2) * scaleFactor;

  int bestIndex = 0;
  float bestYDist = 1e30f;
  float bestXDist = 1e30f;

  // Evaluate initial position (before the first character)
  {
    float absX = textPos.x + textOffsetX;
    float absY = textPos.y + textOffsetY;

    float yDist = 0.0f;
    if (mousePos.y < absY) {
      yDist = absY - mousePos.y;
    } else if (mousePos.y > absY + lineHeight) {
      yDist = mousePos.y - (absY + lineHeight);
    } else {
      yDist = 0.0f;
    }

    float xDist = fabsf(mousePos.x - absX);
    bestYDist = yDist;
    bestXDist = xDist;
    bestIndex = 0;
  }

  for (int i = 0; i < length;) {
    int codepointByteCount = 0;
    int codepoint = GetCodepoint(&text.data[i], &codepointByteCount);
    int index = GetGlyphIndex(font, codepoint);

    if (codepoint == 0x3f)
      codepointByteCount = 1;

    float glyphWidth = 0.0f;
    if (codepoint != '\n') {
      glyphWidth = (font.glyphs[index].advanceX == 0)
                       ? font.recs[index].width * scaleFactor
                       : font.glyphs[index].advanceX * scaleFactor;
      if (i + codepointByteCount < length)
        glyphWidth = glyphWidth + spacing;
    }

    if (codepoint == '\n') {
      textOffsetY += lineHeight;
      textOffsetX = 0.0f;
    } else {
      if ((textOffsetX + glyphWidth) > recWidth) {
        textOffsetY += lineHeight;
        textOffsetX = 0.0f;
      }
      if ((textOffsetX != 0.0f) || (codepoint != ' ')) {
        textOffsetX += glyphWidth;
      }
    }

    i += codepointByteCount;

    // Evaluate candidate boundary position after the current codepoint
    {
      float absX = textPos.x + textOffsetX;
      float absY = textPos.y + textOffsetY;

      float yDist = 0.0f;
      if (mousePos.y < absY) {
        yDist = absY - mousePos.y;
      } else if (mousePos.y > absY + lineHeight) {
        yDist = mousePos.y - (absY + lineHeight);
      } else {
        yDist = 0.0f;
      }

      float xDist = fabsf(mousePos.x - absX);

      if (yDist < bestYDist) {
        bestYDist = yDist;
        bestXDist = xDist;
        bestIndex = i;
      } else if (yDist == bestYDist) {
        if (xDist < bestXDist) {
          bestXDist = xDist;
          bestIndex = i;
        }
      }
    }
  }

  return bestIndex;
}

static void DrawTextBoxedSelectable(State *s, Element *e, Font font,
                                    String text, Rectangle rec, float fontSize,
                                    float spacing, bool wordWrap, Color tint,
                                    int selectStart, int selectLength,
                                    Color selectTint, Color selectBackTint,
                                    float *outTextHeight, float *outCursorY,
                                    int cursorIndex) {
  int length = text.len;
  (void)s;

  float textOffsetY = 0;    // Offset between lines (on line break '\n')
  float textOffsetX = 0.0f; // Offset X to next character to draw

  float scaleFactor =
      fontSize / (float)font.baseSize; // Character rectangle scaling factor
  float lineHeight = (font.baseSize + (float)font.baseSize / 2) * scaleFactor;

  // Word/character wrapping mechanism variables
  enum { MEASURE_STATE = 0, DRAW_STATE = 1 };
  int state = wordWrap ? MEASURE_STATE : DRAW_STATE;

  int startLine = -1; // Index where to begin drawing (where a line begins)
  int endLine = -1;   // Index where to stop drawing (where a line ends)
  int lastk = -1;     // Holds last value of the character position

  float maxTextOffsetY = 0.0f;
  float cursorY = 0.0f;

  float cursorX_screen = rec.x;
  float cursorY_screen = rec.y - e->scrollY;
  bool cursorPositionFound = false;

  for (int i = 0, k = 0; i < length; i++, k++) {
    int charByteIndex = i;
    // Track cursor position
    if (charByteIndex == cursorIndex) {
      cursorX_screen = rec.x + textOffsetX;
      cursorY_screen = rec.y + textOffsetY - e->scrollY;
      cursorY = textOffsetY;
      cursorPositionFound = true;
    }

    // Get next codepoint from byte string and glyph index in font
    int codepointByteCount = 0;
    int codepoint =
        text.data ? GetCodepoint(&text.data[i], &codepointByteCount) : 0;
    int index = GetGlyphIndex(font, codepoint);

    // NOTE: Normally we exit the decoding sequence as soon as a bad byte is
    // found (and return 0x3f) but we need to draw all of the bad bytes using
    // the '?' symbol moving one byte
    if (codepoint == 0x3f)
      codepointByteCount = 1;
    i += (codepointByteCount - 1);

    float glyphWidth = 0;
    if (codepoint != '\n') {
      glyphWidth = (font.glyphs[index].advanceX == 0)
                       ? font.recs[index].width * scaleFactor
                       : font.glyphs[index].advanceX * scaleFactor;

      if (i + 1 < length)
        glyphWidth = glyphWidth + spacing;
    }

    // NOTE: When wordWrap is ON we first measure how much of the text we can
    // draw before going outside of the rec container We store this info in
    // startLine and endLine, then we change states, draw the text between those
    // two variables and change states again and again recursively until the end
    // of the text (or until we get outside of the container) When wordWrap is
    // OFF we don't need the measure state so we go to the drawing state
    // immediately and begin drawing on the next line before we can get outside
    // the container
    if (state == MEASURE_STATE) {
      // TODO: There are multiple types of spaces in UNICODE, maybe it's a good
      // idea to add support for more Ref: http://jkorpela.fi/chars/spaces.html
      if ((codepoint == ' ') || (codepoint == '\t') || (codepoint == '\n'))
        endLine = i;

      if ((textOffsetX + glyphWidth) > rec.width) {
        endLine = (endLine < 1) ? i : endLine;
        if (i == endLine)
          endLine -= codepointByteCount;
        if ((startLine + codepointByteCount) == endLine)
          endLine = (i - codepointByteCount);

        state = !state;
      } else if ((i + 1) == length) {
        endLine = i;
        state = !state;
      } else if (codepoint == '\n')
        state = !state;

      if (state == DRAW_STATE) {
        textOffsetX = 0;
        i = startLine;
        glyphWidth = 0;

        // Save character position when we switch states
        int tmp = lastk;
        lastk = k - 1;
        k = tmp;
      }
    } else {
      if (codepoint == '\n') {
        if (!wordWrap) {
          textOffsetY += lineHeight;
          textOffsetX = 0;
        }
      } else {
        if (!wordWrap && ((textOffsetX + glyphWidth) > rec.width)) {
          textOffsetY += lineHeight;
          textOffsetX = 0;
        }

        if (textOffsetY > maxTextOffsetY)
          maxTextOffsetY = textOffsetY;

        bool isVisible =
            (textOffsetY - e->scrollY + (float)font.baseSize * scaleFactor >=
             0) &&
            (textOffsetY - e->scrollY < rec.height);

        // Draw selection background
        bool isGlyphSelected = false;
        if ((selectStart >= 0) && (charByteIndex >= selectStart) &&
            (charByteIndex < (selectStart + selectLength))) {
          if (isVisible) {
            DrawRectangleRec((Rectangle){rec.x + textOffsetX - 1,
                                         rec.y + textOffsetY - e->scrollY,
                                         glyphWidth,
                                         (float)font.baseSize * scaleFactor},
                             selectBackTint);
          }
          isGlyphSelected = true;
        }

        // Draw current character glyph
        if ((codepoint != ' ') && (codepoint != '\t')) {
          if (isVisible) {
            DrawTextCodepoint(font, codepoint,
                              (Vector2){rec.x + textOffsetX,
                                        rec.y + textOffsetY - e->scrollY},
                              fontSize, isGlyphSelected ? selectTint : tint);
          }
        }
      }

      if (wordWrap && (i == endLine)) {
        textOffsetY += lineHeight;
        textOffsetX = 0;
        startLine = endLine;
        endLine = -1;
        glyphWidth = 0;
        selectStart += lastk - k;
        k = lastk;

        state = !state;
      }
    }

    if ((textOffsetX != 0) || (codepoint != ' '))
      textOffsetX += glyphWidth; // avoid leading spaces
  }

  if (textOffsetY > maxTextOffsetY)
    maxTextOffsetY = textOffsetY;

  if (!cursorPositionFound && cursorIndex >= length) {
    cursorX_screen = rec.x + textOffsetX;
    cursorY_screen = rec.y + textOffsetY - e->scrollY;
    cursorY = textOffsetY;
  }

  // Draw the cursor if focused
  if (e->isFocused) {
    if (e->textSelectedFramesCounter / 40 % 2 == 0) {
      DrawRectangleRec((Rectangle){cursorX_screen, cursorY_screen, 2.0f,
                                   (float)font.baseSize * scaleFactor},
                       RED);
    }
  }

  if (outTextHeight)
    *outTextHeight = maxTextOffsetY + lineHeight;
  if (outCursorY)
    *outCursorY = cursorY;
}

static void DrawTextBoxed(State *s, Element *e, Font font, String text,
                          Rectangle rec, float fontSize, float spacing,
                          bool wordWrap, Color tint, float *outTextHeight,
                          float *outCursorY, int cursorIndex) {
  if (s->debug)
    DrawText(TextFormat("Selection start: %d, end: %d, length: %d",
                        e->selectTextStart, e->selectTextEnd,
                        e->selectTextLength),
             rec.x, rec.y - 20, 10, RED);

  int selStart = e->selectTextLength > 0
                     ? e->selectTextStart
                     : e->selectTextStart + e->selectTextLength;
  int selLength =
      e->selectTextLength > 0 ? e->selectTextLength : -e->selectTextLength;
  DrawTextBoxedSelectable(s, e, font, text, rec, fontSize, spacing, wordWrap,
                          tint, selStart, selLength, BLACK, LCARS_RED_ORANGE,
                          outTextHeight, outCursorY, cursorIndex);
}

#endif // LCARS_TEXT_H
