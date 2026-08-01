#ifndef LCARS_GAP_BUFFER_H
#define LCARS_GAP_BUFFER_H

#include "lcars_types.h"

static bool IsWordChar(char c);
static int FindWordBoundary(String text, int from, int dir);
static void MoveGap(GapBuffer *gap, int index);
static void GapInsertChar(Arena *arena, GapBuffer *gap, char c);
static void GapDeleteBack(GapBuffer *gap);
static void GapDeleteForward(GapBuffer *gap);
static void ReconstructText(Arena *arena, GapBuffer *gap, String *text,
                            int *textLen);
static bool DeleteSelection(GapBuffer *gap, Selection *sel);
static void StartTextSelection(GapBuffer *gap, Selection *sel,
                               bool shiftDown);
static void EndTextSelection(GapBuffer *gap, Selection *sel, bool shiftDown);

#ifdef LCARS_IMPLEMENTATION

static bool IsWordChar(char c) {
  return ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_');
}

// Finds the next word boundary in `text` starting at `from`, searching
// left (dir == -1) or right (dir == 1). Mirrors typical editor Ctrl+Arrow
// behavior: a newline immediately adjacent to `from` stops the jump right
// there, otherwise it skips any run of non-word characters and then the
// following run of word characters.
static int FindWordBoundary(String text, int from, int dir) {
  int limit = (dir < 0) ? 0 : text.len;
  int target = from;
  if (target == limit) {
    return target;
  }

  char adjacent = (dir < 0) ? text.data[target - 1] : text.data[target];
  if (adjacent == '\n') {
    return target + dir;
  }

  while (target != limit) {
    char c = (dir < 0) ? text.data[target - 1] : text.data[target];
    if (IsWordChar(c) || c == '\n') {
      break;
    }
    target += dir;
  }
  while (target != limit) {
    char c = (dir < 0) ? text.data[target - 1] : text.data[target];
    if (!IsWordChar(c)) {
      break;
    }
    target += dir;
  }
  return target;
}

static void MoveGap(GapBuffer *gap, int index) {
  if (index < 0)
    index = 0;
  int currentLen = gap->gapStart + (gap->capacity - gap->gapEnd);
  if (index > currentLen)
    index = currentLen;

  while (gap->gapStart < index) {
    gap->buffer[gap->gapStart] = gap->buffer[gap->gapEnd];
    gap->gapStart++;
    gap->gapEnd++;
  }
  while (gap->gapStart > index) {
    gap->gapStart--;
    gap->gapEnd--;
    gap->buffer[gap->gapEnd] = gap->buffer[gap->gapStart];
  }
}

static void GapInsertChar(Arena *arena, GapBuffer *gap, char c) {
  if (gap->gapStart == gap->gapEnd) {
    int newCapacity = gap->capacity * 2;
    if (newCapacity < GAP_BUFFER_MIN_GROWN_CAPACITY)
      newCapacity = GAP_BUFFER_MIN_GROWN_CAPACITY;
    char *newBuf = arena_alloc(arena, newCapacity + 1);

    memcpy(newBuf, gap->buffer, gap->gapStart);
    int afterGapLen = gap->capacity - gap->gapEnd;
    int newGapEnd = newCapacity - afterGapLen;
    memcpy(newBuf + newGapEnd, gap->buffer + gap->gapEnd, afterGapLen);

    // Old gap->buffer was allocated in the arena and is reclaimed when the
    // arena is reset
    gap->buffer = newBuf;
    gap->gapEnd = newGapEnd;
    gap->capacity = newCapacity;
  }

  gap->buffer[gap->gapStart] = c;
  gap->gapStart++;
}

static void GapDeleteBack(GapBuffer *gap) {
  if (gap->gapStart > 0) {
    gap->gapStart--;
  }
}

static void GapDeleteForward(GapBuffer *gap) {
  if (gap->gapEnd < gap->capacity) {
    gap->gapEnd++;
  }
}

static void ReconstructText(Arena *arena, GapBuffer *gap, String *text,
                            int *textLen) {
  int beforeLen = gap->gapStart;
  int afterLen = gap->capacity - gap->gapEnd;
  int totalLen = beforeLen + afterLen;

  char *newData = arena_alloc(arena, totalLen + 1);

  memcpy(newData, gap->buffer, beforeLen);
  memcpy(newData + beforeLen, gap->buffer + gap->gapEnd, afterLen);
  newData[totalLen] = '\0';
  text->data = newData;
  text->len = totalLen;
  text->is_static = false;
  *textLen = totalLen;
}

static bool DeleteSelection(GapBuffer *gap, Selection *sel) {
  if (sel->start >= 0 && sel->end != sel->start) {
    int selStart = sel->length > 0 ? sel->start : sel->start + sel->length;
    int selLength = sel->length > 0 ? sel->length : -sel->length;
    MoveGap(gap, selStart);
    gap->gapEnd += selLength;
    sel->length = 0;
    sel->start = -1;
    sel->end = -1;
    return true;
  }
  return false;
}

static void StartTextSelection(GapBuffer *gap, Selection *sel,
                               bool shiftDown) {
  if (shiftDown) {
    if (sel->start == -1) {
      sel->start = gap->gapStart;
    }
  } else {
    sel->start = -1;
    sel->end = -1;
    sel->length = 0;
  }
}

static void EndTextSelection(GapBuffer *gap, Selection *sel,
                             bool shiftDown) {
  if (shiftDown) {
    sel->end = gap->gapStart;
    sel->length = sel->end - sel->start;
  }
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_GAP_BUFFER_H
