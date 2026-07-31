#ifndef LCARS_GAP_BUFFER_H
#define LCARS_GAP_BUFFER_H

#include "liblcars.h"

static bool IsWordChar(char c) {
  return ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_');
}

static void MoveGap(Element *e, int index) {
  if (index < 0)
    index = 0;
  int currentLen = e->gapStart + (e->textCapacity - e->gapEnd);
  if (index > currentLen)
    index = currentLen;

  while (e->gapStart < index) {
    e->gapBuffer[e->gapStart] = e->gapBuffer[e->gapEnd];
    e->gapStart++;
    e->gapEnd++;
  }
  while (e->gapStart > index) {
    e->gapStart--;
    e->gapEnd--;
    e->gapBuffer[e->gapEnd] = e->gapBuffer[e->gapStart];
  }
}

static void GapInsertChar(Arena *arena, Element *e, char c) {
  if (e->gapStart == e->gapEnd) {
    int newCapacity = e->textCapacity * 2;
    if (newCapacity < 1024)
      newCapacity = 1024;
    char *newBuf = arena_alloc(arena, newCapacity + 1);

    memcpy(newBuf, e->gapBuffer, e->gapStart);
    int afterGapLen = e->textCapacity - e->gapEnd;
    int newGapEnd = newCapacity - afterGapLen;
    memcpy(newBuf + newGapEnd, e->gapBuffer + e->gapEnd, afterGapLen);

    // Old e->gapBuffer was allocated in the arena and is reclaimed when the
    // arena is reset
    e->gapBuffer = newBuf;
    e->gapEnd = newGapEnd;
    e->textCapacity = newCapacity;
  }

  e->gapBuffer[e->gapStart] = c;
  e->gapStart++;
}

static void GapDeleteBack(Element *e) {
  if (e->gapStart > 0) {
    e->gapStart--;
  }
}

static void GapDeleteForward(Element *e) {
  if (e->gapEnd < e->textCapacity) {
    e->gapEnd++;
  }
}

static void ReconstructText(Arena *arena, Element *e) {
  int beforeLen = e->gapStart;
  int afterLen = e->textCapacity - e->gapEnd;
  int totalLen = beforeLen + afterLen;

  char *newData = arena_alloc(arena, totalLen + 1);

  if (newData) {
    memcpy(newData, e->gapBuffer, beforeLen);
    memcpy(newData + beforeLen, e->gapBuffer + e->gapEnd, afterLen);
    newData[totalLen] = '\0';
    e->text.data = newData;
    e->text.len = totalLen;
    e->text.is_static = false;
  }
  e->textLen = totalLen;
}

static bool DeleteSelection(Element *e) {
  if (e->selectTextStart >= 0 && e->selectTextEnd != e->selectTextStart) {
    int selStart = e->selectTextLength > 0
                       ? e->selectTextStart
                       : e->selectTextStart + e->selectTextLength;
    int selLength =
        e->selectTextLength > 0 ? e->selectTextLength : -e->selectTextLength;
    MoveGap(e, selStart);
    e->gapEnd += selLength;
    e->selectTextLength = 0;
    e->selectTextStart = -1;
    e->selectTextEnd = -1;
    return true;
  }
  return false;
}

static void StartTextSelection(Element *e, bool shiftDown) {
  if (shiftDown) {
    if (e->selectTextStart == -1) {
      e->selectTextStart = e->gapStart;
    }
  } else {
    e->selectTextStart = -1;
    e->selectTextEnd = -1;
    e->selectTextLength = 0;
  }
}

static void EndTextSelection(Element *e, bool shiftDown) {
  if (shiftDown) {
    e->selectTextEnd = e->gapStart;
    e->selectTextLength = e->selectTextEnd - e->selectTextStart;
  }
  e->snapToCursor = 2;
}

#endif // LCARS_GAP_BUFFER_H
