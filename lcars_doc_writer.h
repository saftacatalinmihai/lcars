#ifndef LCARS_DOC_WRITER_H
#define LCARS_DOC_WRITER_H

// Writing the running layout back into the hypermedia document it came from.
//
// Edit mode (Ctrl+E and the corner handles, or Super+drag / Super+right-drag
// anywhere) moves and resizes elements in memory. Without this module those
// edits die with the process: the document on disk still says where
// everything used to be, so the next load puts it all back. This is the
// other half — the x/y/w/h the user dragged to, written into the .html.
//
// It is a *patch*, not a serializer. The document's own bytes are kept at
// load time (State.documentSource) along with the byte range of every
// element's opening tag (Element.srcTagStart/srcTagEnd), and saving replaces
// nothing but the four geometry attribute *values* inside those ranges.
// Comments, indentation, attribute order, whitespace, even tags this parser
// doesn't recognize — all of it comes back out byte for byte. Regenerating
// the document from the element array instead would be a third of the code
// and would throw every one of those away on the first drag; the documents
// in this repo are hand-written and heavily commented, so that trade is not
// available.
//
// Two consequences worth knowing:
//   - An attribute is only rewritten when its text would actually change, so
//     saving a document nobody dragged writes the file back identical to
//     itself.
//   - Only documents read from a local file are writable. An http(s)
//     document isn't ours to change and a body swapped in by a control
//     (HYPER_SWAP_DOCUMENT) has no file behind it at all;
//     State.documentWritable records which case is running.
//
// Saves are debounced exactly like editor content saves (a drag is hundreds
// of frames, each save is a whole-file rewrite) — see MarkLayoutDirty() /
// UpdateLayoutPersistence() and LAYOUT_SAVE_DEBOUNCE_SECONDS.

#include "lcars_types.h"

#include <ctype.h>
#include <math.h>

static void MarkLayoutDirty(State *s);
static bool SaveDocumentLayout(State *s);
static void FlushLayoutChanges(State *s);
static void UpdateLayoutPersistence(State *s);

#ifdef LCARS_IMPLEMENTATION

// The geometry attributes one tag can carry, and therefore the most edits a
// single tag rewrite can queue up.
#define MAX_TAG_EDITS 4
// Worst-case bytes one inserted attribute costs: ' name="-1234567.89"' is 19,
// rounded well up so the output-buffer sizing below can't be wrong.
#define MAX_GEOMETRY_ATTR_BYTES 48

// One pending change inside a tag: replace the bytes [start, start + len) of
// it with `text`. An insertion is the same thing with len == 0.
typedef struct TagEdit {
  int start;
  int len;
  char text[MAX_GEOMETRY_ATTR_BYTES];
} TagEdit;

// Append-only cursor over the document being built. The buffer is sized up
// front from the source plus a worst case per element, so every append is a
// bounds assert rather than a growth check — and an assert failure here means
// that sizing is wrong, which is a programmer error, not bad input.
typedef struct DocWriteBuf {
  char *data;
  int len;
  int capacity;
} DocWriteBuf;

static void DocWriteBytes(DocWriteBuf *buf, const char *bytes, int len) {
  assert(buf != NULL);
  assert(buf->data != NULL);
  assert(buf->len >= 0 && buf->len <= buf->capacity);
  assert(len >= 0);
  assert(bytes != NULL || len == 0);
  assert(buf->len + len <= buf->capacity);

  if (len > 0) {
    memcpy(buf->data + buf->len, bytes, (size_t)len);
    buf->len += len;
  }

  assert(buf->len <= buf->capacity);
}

// Formats one geometry value the way this document format writes them: whole
// numbers as plain integers (which is all the shipped documents use, and all
// the (int) casts in UpdateDragAndResize can produce), anything else with two
// decimals and the trailing zeros trimmed. The fractional case only shows up
// via the Super+drag "move everything" path, which adds a float mouse delta —
// but it also means a hand-written w="12.5" that nobody touched still reads
// 12.5 after a save instead of being rounded to 13.
static void FormatLayoutValue(char *dest, size_t destSize, float value) {
  assert(dest != NULL);
  // Sized for "-1234567.89" and its terminator many times over; the callers
  // all pass a 32-byte buffer.
  assert(destSize >= 32);

  // Past ~1e7 a float can't represent the integer part exactly anyway, and
  // the (int) cast would overflow well before that; fall through to the
  // decimal form rather than print garbage.
  if (value == floorf(value) && fabsf(value) < 1.0e7f) {
    snprintf(dest, destSize, "%d", (int)value);
    assert(strlen(dest) > 0);
    return;
  }

  snprintf(dest, destSize, "%.2f", value);
  // "%.2f" always emits a '.' followed by exactly two digits, so walking back
  // over the zeros can only stop at that '.' or at a real fractional digit —
  // it can never eat into the integer part.
  size_t len = strlen(dest);
  while (len > 0 && dest[len - 1] == '0') {
    dest[--len] = '\0';
  }
  if (len > 0 && dest[len - 1] == '.') {
    dest[--len] = '\0';
  }

  assert(strlen(dest) > 0);
}

// Appends `tag` — one element's original opening tag, `tagLen` bytes, NUL
// terminated — to `out` with x/y/w/h updated to what `e` currently says.
// Everything else in the tag is copied through untouched.
static void WriteTagWithGeometry(DocWriteBuf *out, const char *tag, int tagLen,
                                 const Element *e) {
  assert(out != NULL);
  assert(tag != NULL);
  assert(tagLen >= 2); // at minimum "<>"
  assert((int)strlen(tag) == tagLen);
  assert(e != NULL);

  const struct {
    const char *name;
    float value;
    // What ParseElementTag() assumes when the tag omits this attribute.
    float omittedValue;
    // Whether the attribute means anything for this element at all.
    bool applies;
  } geometry[] = {
      // x/y are rounded because ParseElementTag() reads them back with
      // atoi(): writing "12.5" would round-trip to 12 on the next load and
      // then rewrite itself to "12" on the save after that, so the document
      // would keep changing while the layout stood still. w/h go through
      // atof() and really can be fractional.
      {"x", roundf(e->position.x), (float)ELEM_DEFAULT_X, true},
      {"y", roundf(e->position.y), (float)ELEM_DEFAULT_Y, true},
      // An ELEM_TEXT sizes itself from its own text (make_text sets
      // autoSize) and GetElementBoundingBox never reads width/height for it,
      // so a resize drag changes numbers nothing draws from. Writing them
      // out would put misleading dimensions in the document.
      {"w", e->width, ELEM_DEFAULT_W, !e->autoSize},
      {"h", e->height, ELEM_DEFAULT_H, !e->autoSize},
  };
  const int geometryCount = (int)(sizeof(geometry) / sizeof(geometry[0]));
  assert(geometryCount <= MAX_TAG_EDITS);

  // Where an attribute the tag doesn't carry gets inserted: immediately after
  // the tag name, so "<lcars-rect y=..." becomes "<lcars-rect x="12" y=...".
  // Anywhere further along would risk landing inside another attribute's
  // quoted value.
  int nameEnd = 1;
  while (nameEnd < tagLen && !isspace((unsigned char)tag[nameEnd]) &&
         tag[nameEnd] != '>' && tag[nameEnd] != '/') {
    nameEnd++;
  }
  assert(nameEnd > 1 && nameEnd <= tagLen);

  TagEdit edits[MAX_TAG_EDITS];
  int editCount = 0;

  for (int i = 0; i < geometryCount; i++) {
    if (!geometry[i].applies) {
      continue;
    }

    char formatted[32];
    FormatLayoutValue(formatted, sizeof(formatted), geometry[i].value);
    int formattedLen = (int)strlen(formatted);

    int valStart = 0;
    int valLen = 0;
    if (FindAttributeValueSpan(tag, geometry[i].name, &valStart, &valLen)) {
      // Compare the bytes rather than the numbers: identical text means the
      // document already says exactly this, so the tag is left alone. That
      // is what makes a save with nothing dragged reproduce the file
      // verbatim, and it also preserves however the author chose to write a
      // value this code would otherwise reformat.
      if (valLen == formattedLen &&
          memcmp(tag + valStart, formatted, (size_t)valLen) == 0) {
        continue;
      }
      assert(editCount < MAX_TAG_EDITS);
      edits[editCount].start = valStart;
      edits[editCount].len = valLen;
      snprintf(edits[editCount].text, sizeof(edits[editCount].text), "%s",
               formatted);
      editCount++;
    } else {
      // Absent from the tag, so the parser fell back to a default. It only
      // needs writing out if the element no longer sits at that default —
      // otherwise a save would sprinkle x="0" over every tag that was happy
      // to leave it unsaid.
      char omitted[32];
      FormatLayoutValue(omitted, sizeof(omitted), geometry[i].omittedValue);
      if (strcmp(formatted, omitted) == 0) {
        continue;
      }
      assert(editCount < MAX_TAG_EDITS);
      edits[editCount].start = nameEnd;
      edits[editCount].len = 0;
      snprintf(edits[editCount].text, sizeof(edits[editCount].text),
               " %s=\"%s\"", geometry[i].name, formatted);
      editCount++;
    }
  }

  // Emitting in ascending order is what keeps the copy-through cursor below
  // monotonic. Insertion sort because there are at most four of them, and
  // because it is stable: several insertions all land at nameEnd and stay in
  // x/y/w/h order rather than coming out shuffled.
  for (int i = 1; i < editCount; i++) {
    TagEdit key = edits[i];
    int j = i - 1;
    while (j >= 0 && edits[j].start > key.start) {
      edits[j + 1] = edits[j];
      j--;
    }
    edits[j + 1] = key;
  }

  int cursor = 0;
  for (int i = 0; i < editCount; i++) {
    // Ascending, non-overlapping and inside the tag - anything else would
    // mean the span finder and this loop disagree about the same bytes.
    assert(edits[i].start >= cursor);
    assert(edits[i].len >= 0);
    assert(edits[i].start + edits[i].len <= tagLen);
    DocWriteBytes(out, tag + cursor, edits[i].start - cursor);
    DocWriteBytes(out, edits[i].text, (int)strlen(edits[i].text));
    cursor = edits[i].start + edits[i].len;
  }
  DocWriteBytes(out, tag + cursor, tagLen - cursor);
}

// Rewrites the document behind State.currentDocument with the layout the
// elements currently have. Returns whether the file on disk was actually
// replaced; the caller reports the outcome.
static bool SaveDocumentLayout(State *s) {
  assert(s != NULL);
  assert(arena_valid(&s->scratch_arena));
  assert(StringValid(s->documentSource));
  assert(s->numElements >= 0 && s->numElements <= MAX_ELEMENTS);

  if (!s->documentWritable || s->documentSource.data == NULL) {
    return false;
  }

  const char *path = s->currentDocument;
  if (strncmp(path, "file://", 7) == 0) {
    path += 7;
  }
  if (path[0] == '\0') {
    return false;
  }

  const char *src = s->documentSource.data;
  int srcLen = s->documentSource.len;

  // Worst case is every element gaining all four attributes it never had.
  int capacity =
      srcLen + s->numElements * MAX_TAG_EDITS * MAX_GEOMETRY_ATTR_BYTES + 1;
  DocWriteBuf out;
  out.data = arena_alloc(&s->scratch_arena, (size_t)capacity);
  out.len = 0;
  out.capacity = capacity;

  int cursor = 0;
  for (int i = 0; i < s->numElements; i++) {
    const Element *e = &s->elements[i];
    if (e->srcTagStart < 0) {
      // Not from this document's text. Nothing builds such an element today
      // (every element comes out of the parser), but if something ever does
      // it simply has no tag to patch.
      continue;
    }
    // Elements are appended in the order their tags were parsed, so the
    // spans only ever move forward - which is what makes one pass over the
    // source enough.
    assert(e->srcTagStart >= cursor);
    assert(e->srcTagEnd > e->srcTagStart);
    assert(e->srcTagEnd <= srcLen);

    DocWriteBytes(&out, src + cursor, e->srcTagStart - cursor);

    // FindAttributeValueSpan() works on a C string, and the tag inside
    // documentSource is not terminated at its '>'. Terminated copies come
    // from scratch_arena, which is reset at the end of this frame anyway.
    int tagLen = e->srcTagEnd - e->srcTagStart;
    char *tag = arena_alloc(&s->scratch_arena, (size_t)tagLen + 1);
    memcpy(tag, src + e->srcTagStart, (size_t)tagLen);
    tag[tagLen] = '\0';
    WriteTagWithGeometry(&out, tag, tagLen, e);

    cursor = e->srcTagEnd;
  }
  DocWriteBytes(&out, src + cursor, srcLen - cursor);

  // Write beside the target and rename over it. A crash, a full disk or a
  // short write then leaves the previous document intact instead of a
  // half-written one - and this file *is* the UI, so a truncated main.html
  // means an app that comes back up blank with no way to click anything.
  char tmpPath[sizeof(s->currentDocument) + 16];
  snprintf(tmpPath, sizeof(tmpPath), "%s.tmp", path);

  FILE *f = fopen(tmpPath, "wb");
  if (!f) {
    printf("Layout save failed: cannot open %s for writing\n", tmpPath);
    return false;
  }
  size_t written = fwrite(out.data, 1, (size_t)out.len, f);
  bool ok = (written == (size_t)out.len);
  if (!ok) {
    printf("Layout save failed: wrote %zu of %d bytes to %s\n", written,
           out.len, tmpPath);
  }
  // fclose is where a buffered write actually fails, so its result matters
  // as much as fwrite's.
  if (fclose(f) != 0) {
    printf("Layout save failed: error closing %s\n", tmpPath);
    ok = false;
  }
  if (ok && rename(tmpPath, path) != 0) {
    printf("Layout save failed: cannot rename %s onto %s\n", tmpPath, path);
    ok = false;
  }
  if (!ok) {
    remove(tmpPath);
    return false;
  }
  return true;
}

static void MarkLayoutDirty(State *s) {
  assert(s != NULL);
  s->layoutDirty = true;
  s->layoutLastEditTime = (float)GetTime();
}

// Persists a pending layout edit right now, if there is one. The dirty flag
// is cleared even when the save fails on purpose: the alternative is retrying
// the same failing write on every single frame for the rest of the session.
static void FlushLayoutChanges(State *s) {
  assert(s != NULL);
  if (!s->layoutDirty) {
    return;
  }
  s->layoutDirty = false;

  if (!s->documentWritable) {
    // Nowhere to write back to - an http(s) document, or a control's
    // response body. The move still applies on screen, it just won't
    // survive the process.
    UpdateNotification(s, StringStatic("LAYOUT NOT SAVED: READ-ONLY DOC"));
    return;
  }
  if (SaveDocumentLayout(s)) {
    UpdateNotification(s, StringStatic("LAYOUT SAVED"));
  } else {
    UpdateNotification(s, StringStatic("LAYOUT SAVE FAILED"));
  }
}

// Called once per frame from Update(). Waits for the layout to sit still
// before writing, so a drag produces one file rewrite when the mouse stops
// rather than one per frame while it moves.
static void UpdateLayoutPersistence(State *s) {
  assert(s != NULL);
  if (!s->layoutDirty) {
    return;
  }
  if ((float)GetTime() - s->layoutLastEditTime < LAYOUT_SAVE_DEBOUNCE_SECONDS) {
    return;
  }
  FlushLayoutChanges(s);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_DOC_WRITER_H
