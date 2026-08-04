#ifndef LCARS_GAP_BUFFER_H
#define LCARS_GAP_BUFFER_H

#include "lcars_types.h"

// GapBufferValid()/GapTextLen() - the invariant asserted throughout this
// file - live in lcars_types.h next to the struct, because lcars_db.h and
// liblcars.h's make_text_editor() are both compiled before this header is
// included and assert against it too.

static bool IsWordChar(char c);
static int FindWordBoundary(String text, int from, int dir);
static void MoveGap(GapBuffer *gap, int index);
static void GapInsertChar(Arena *arena, GapBuffer *gap, char c);
static void GapDeleteBack(GapBuffer *gap);
static void GapDeleteForward(GapBuffer *gap);
static void ReconstructText(Arena *arena, GapBuffer *gap, String *text,
                            int *textLen);
static bool DeleteSelection(GapBuffer *gap, Selection *sel);
static void StartTextSelection(GapBuffer *gap, Selection *sel, bool shiftDown);
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
  assert(StringValid(text));
  assert(dir == -1 || dir == 1);
  assert(from >= 0);

  int limit = (dir < 0) ? 0 : text.len;
  // `from` is the caller's cursor (gap.gapStart), and Element.text is only
  // re-flattened once per frame at the end of the edit block - so within a
  // frame that both inserted text and moved the cursor (Ctrl+V then
  // Ctrl+Right, or Enter while Ctrl+Arrow auto-repeats) the cursor can
  // legitimately sit past the end of this now-stale text. Clamping is not
  // cosmetic: with dir == 1 and from > text.len, `target != limit` is true
  // and target only moves further away, so the loops below would read off
  // the end of the allocation without ever terminating.
  int target = from > text.len ? text.len : from;
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

  assert(target >= 0 && target <= text.len);
  return target;
}

static void MoveGap(GapBuffer *gap, int index) {
  assert(GapBufferValid(gap));
  int lenBefore = GapTextLen(gap);
  (void)lenBefore; // read only by the postcondition assert below

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

  assert(GapBufferValid(gap));
  // Moving the gap relocates the cursor without adding or removing anything.
  assert(gap->gapStart == index);
  assert(GapTextLen(gap) == lenBefore);
}

static void GapInsertChar(Arena *arena, GapBuffer *gap, char c) {
  assert(GapBufferValid(gap));
  int lenBefore = GapTextLen(gap);
  (void)lenBefore; // read only by the postcondition assert below

  if (gap->gapStart == gap->gapEnd) {
    int newCapacity = gap->capacity * 2;
    if (newCapacity < GAP_BUFFER_MIN_GROWN_CAPACITY)
      newCapacity = GAP_BUFFER_MIN_GROWN_CAPACITY;
    // Doubling an int capacity wraps negative somewhere past 1GB. doc_arena
    // is 32MB so this is unreachable through the arena, but a wrapped
    // capacity would be handed to arena_alloc as a size and to memcpy as a
    // length, so it must never pass silently.
    assert(newCapacity > gap->capacity);
    char *newBuf = arena_alloc(arena, newCapacity + 1);

    memcpy(newBuf, gap->buffer, gap->gapStart);
    int afterGapLen = gap->capacity - gap->gapEnd;
    int newGapEnd = newCapacity - afterGapLen;
    assert(afterGapLen >= 0);
    // The two halves must still fit either side of the (now larger) gap.
    assert(newGapEnd >= gap->gapStart && newGapEnd <= newCapacity);
    memcpy(newBuf + newGapEnd, gap->buffer + gap->gapEnd, afterGapLen);

    // Old gap->buffer was allocated in the arena and is reclaimed when the
    // arena is reset
    gap->buffer = newBuf;
    gap->gapEnd = newGapEnd;
    gap->capacity = newCapacity;

    assert(GapBufferValid(gap));
    assert(GapTextLen(gap) == lenBefore); // growing must not lose characters
  }

  // The branch above guarantees a non-empty gap, so this write lands inside
  // it rather than on top of a live character.
  assert(gap->gapStart < gap->gapEnd);
  gap->buffer[gap->gapStart] = c;
  gap->gapStart++;

  assert(GapBufferValid(gap));
  assert(GapTextLen(gap) == lenBefore + 1);
}

static void GapDeleteBack(GapBuffer *gap) {
  assert(GapBufferValid(gap));
  int lenBefore = GapTextLen(gap);
  (void)lenBefore; // read only by the postcondition assert below

  if (gap->gapStart > 0) {
    gap->gapStart--;
  }

  assert(GapBufferValid(gap));
  // A backspace at the very start of the buffer is a legal no-op.
  assert(GapTextLen(gap) == lenBefore || GapTextLen(gap) == lenBefore - 1);
}

static void GapDeleteForward(GapBuffer *gap) {
  assert(GapBufferValid(gap));
  int lenBefore = GapTextLen(gap);
  (void)lenBefore; // read only by the postcondition assert below

  if (gap->gapEnd < gap->capacity) {
    gap->gapEnd++;
  }

  assert(GapBufferValid(gap));
  // Delete at the very end of the buffer is a legal no-op.
  assert(GapTextLen(gap) == lenBefore || GapTextLen(gap) == lenBefore - 1);
}

// Flattens the gap buffer into gap->text and points *text at it. Callers run
// this after every edit, so it must not allocate on the common path: the
// flatten buffer is grown geometrically and then reused in place, which is
// why *text is only ever a view into gap->text and must not be held across
// later edits (nothing does — Element.text is re-read every frame).
static void ReconstructText(Arena *arena, GapBuffer *gap, String *text,
                            int *textLen) {
  assert(GapBufferValid(gap));
  assert(text != NULL && textLen != NULL);

  int beforeLen = gap->gapStart;
  int afterLen = gap->capacity - gap->gapEnd;
  int totalLen = beforeLen + afterLen;
  // Both halves are non-negative under GapBufferValid; this restates it at
  // the point where they become memcpy lengths, which is where a broken gap
  // would do its damage.
  assert(beforeLen >= 0 && afterLen >= 0);
  assert(totalLen == GapTextLen(gap));

  if (!gap->text || totalLen + 1 > gap->textCapacity) {
    int newCapacity = gap->textCapacity > 0 ? gap->textCapacity
                                            : GAP_BUFFER_MIN_GROWN_CAPACITY;
    while (newCapacity < totalLen + 1) {
      newCapacity *= 2;
      assert(newCapacity > 0); // int overflow on a runaway document
    }
    gap->text = arena_alloc(arena, newCapacity);
    gap->textCapacity = newCapacity;
  }

  // The flatten buffer must have room for the contents *and* the
  // terminator written below.
  assert(gap->text != NULL && totalLen + 1 <= gap->textCapacity);

  memcpy(gap->text, gap->buffer, beforeLen);
  memcpy(gap->text + beforeLen, gap->buffer + gap->gapEnd, afterLen);
  gap->text[totalLen] = '\0';
  text->data = gap->text;
  text->len = totalLen;
  text->is_static = false;
  *textLen = totalLen;

  assert(StringValid(*text));
  assert(text->len == *textLen);
}

static bool DeleteSelection(GapBuffer *gap, Selection *sel) {
  assert(GapBufferValid(gap));
  assert(sel != NULL);

  if (sel->start >= 0 && sel->end != sel->start) {
    int selStart = sel->length > 0 ? sel->start : sel->start + sel->length;
    int selLength = sel->length > 0 ? sel->length : -sel->length;
    assert(selLength > 0);

    // A Selection can outlive the text it indexes: nothing resets it when
    // plain Backspace/Delete shortens the buffer (only DeleteSelection
    // itself and LoadEntryIntoEditor clear it), so a shift-arrow afterwards
    // can hand us an anchor past the current end. Clamping here rather than
    // asserting because that sequence is ordinary user input, not a bug -
    // but it must be clamped, since `gapEnd += selLength` below would
    // otherwise push the gap past capacity and hand ReconstructText a
    // negative memcpy length.
    int textLen = GapTextLen(gap);
    if (selStart > textLen)
      selStart = textLen;
    if (selStart < 0)
      selStart = 0;
    if (selStart + selLength > textLen)
      selLength = textLen - selStart;

    MoveGap(gap, selStart);
    assert(gap->gapStart == selStart);
    // The characters being swallowed must all lie after the gap.
    assert(selLength <= gap->capacity - gap->gapEnd);
    gap->gapEnd += selLength;
    sel->length = 0;
    sel->start = -1;
    sel->end = -1;

    assert(GapBufferValid(gap));
    assert(GapTextLen(gap) == textLen - selLength);
    return true;
  }

  assert(GapBufferValid(gap));
  return false;
}

static void StartTextSelection(GapBuffer *gap, Selection *sel, bool shiftDown) {
  assert(GapBufferValid(gap));
  assert(sel != NULL);

  if (shiftDown) {
    if (sel->start == -1) {
      sel->start = gap->gapStart;
    }
  } else {
    sel->start = -1;
    sel->end = -1;
    sel->length = 0;
  }

  // Either there is an anchor, or the selection is fully cleared.
  assert(sel->start >= 0 || (sel->end == -1 && sel->length == 0));
}

static void EndTextSelection(GapBuffer *gap, Selection *sel, bool shiftDown) {
  assert(GapBufferValid(gap));
  assert(sel != NULL);

  if (shiftDown) {
    // StartTextSelection() runs first on every shift-extend path, so an
    // anchor is always set by the time we get here.
    assert(sel->start >= 0);
    sel->end = gap->gapStart;
    sel->length = sel->end - sel->start;
    assert(sel->length == sel->end - sel->start);
  }
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_GAP_BUFFER_H
