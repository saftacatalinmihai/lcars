#ifndef LCARS_STRING_H
#define LCARS_STRING_H

#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lcars_arena.h"

typedef struct String {
  char *data;     // Null-terminated buffer
  int len;        // Length of the string (excluding null terminator)
  bool is_static; // True if it points to static memory and should not be freed
} String;

// The structural invariant every String in this codebase holds: `len` is
// non-negative and `data` is NUL-terminated exactly there, so the two ways
// this code reads a String (bounded by .len, or as a C string) always agree.
// A cleared String (data == NULL, see StringClear) is the one legal
// exception, and it carries len 0. Asserted wherever a String is produced
// or consumed, since a disagreement here is what turns a stale length into
// an out-of-bounds read in the text renderer.
static inline bool StringValid(String s) {
  if (s.data == NULL) {
    return s.len == 0;
  }
  return s.len >= 0 && s.data[s.len] == '\0';
}

static inline String StringInit(Arena *arena, const char *c_str) {
  assert(arena != NULL);

  String s;
  if (c_str == NULL) {
    s.data = arena_alloc(arena, 1);
    s.data[0] = '\0';
    s.len = 0;
    s.is_static = false;
  } else {
    s.len = (int)strlen(c_str);
    s.data = arena_alloc(arena, s.len + 1);
    memcpy(s.data, c_str, s.len + 1);
    s.is_static = false;
  }

  assert(StringValid(s));
  assert(!s.is_static); // it is an arena copy, never an aliased literal
  return s;
}

static inline String StringInitLen(Arena *arena, const char *c_str, int len) {
  assert(arena != NULL);
  // A negative length reaches memcpy as a huge size_t; every caller derives
  // this from strlen or a pointer difference, so it can only be a bug.
  assert(len >= 0);

  String s;
  if (c_str == NULL || len <= 0) {
    s.data = arena_alloc(arena, 1);
    s.data[0] = '\0';
    s.len = 0;
    s.is_static = false;
  } else {
    s.len = len;
    s.data = arena_alloc(arena, s.len + 1);
    memcpy(s.data, c_str, len);
    s.data[len] = '\0';
    s.is_static = false;
  }

  assert(StringValid(s));
  assert(s.len <= len);
  return s;
}

static inline String StringStatic(const char *c_str) {
  String s;
  s.data = (char *)(c_str ? c_str : "");
  s.len = (int)strlen(s.data);
  s.is_static = true;

  assert(StringValid(s));
  assert(s.is_static && s.data != NULL);
  return s;
}

// Resets *s to an empty static String. Despite the arena-based naming
// convention elsewhere in this codebase, this does NOT free or reclaim
// any memory - the arena owns everything a non-static String points to,
// and only arena_reset() ever reclaims it. This just clears the struct
// so *s no longer references the (still-live-until-arena-reset) old
// data, which is what StringAssign*/StringConcat* need before
// overwriting a String that might have held a non-static value.
static inline void StringClear(String *s) {
  assert(s != NULL);
  if (s) {
    s->data = NULL;
    s->len = 0;
    s->is_static = true;
  }
  assert(StringValid(*s));
}

// If src is static, returns src as-is: the copy aliases the same
// pointer, since static data is never mutated or arena-reclaimed anyway.
// Only a non-static src gets a real arena copy. Safe as long as callers
// never mutate a String's data in place (none in this codebase do), but
// a footgun for new code that might.
static inline String StringDup(Arena *arena, String src) {
  assert(StringValid(src));
  if (src.is_static) {
    return src;
  }
  String out = StringInit(arena, src.data);
  assert(StringValid(out));
  return out;
}

static inline void StringAssign(Arena *arena, String *dest, String src) {
  assert(dest != NULL);
  assert(StringValid(src));
  if (dest == &src)
    return;
  StringClear(dest);
  *dest = StringDup(arena, src);
  assert(StringValid(*dest));
}

static inline void StringAssignC(Arena *arena, String *dest,
                                 const char *c_str) {
  assert(dest != NULL);
  StringClear(dest);
  *dest = StringInit(arena, c_str);
  assert(StringValid(*dest));
}

static inline void StringAssignStatic(String *dest, const char *c_str) {
  assert(dest != NULL);
  StringClear(dest);
  *dest = StringStatic(c_str);
  assert(StringValid(*dest) && dest->is_static);
}

static inline void StringConcat(Arena *arena, String *dest, String src) {
  assert(dest != NULL);
  assert(StringValid(*dest));
  assert(StringValid(src));
  if (!src.data || src.len == 0)
    return;

  int oldLen = dest->len;
  (void)oldLen; // read only by the postcondition assert below
  int newLen = dest->len + src.len;
  // Both lengths are already known non-negative (StringValid), so a sum
  // that isn't larger than either part can only be signed overflow.
  assert(newLen >= oldLen && newLen >= src.len);

  char *newData = arena_alloc(arena, newLen + 1);
  if (dest->data && dest->len > 0) {
    memcpy(newData, dest->data, dest->len);
  }
  memcpy(newData + dest->len, src.data, src.len);
  newData[newLen] = '\0';
  StringClear(dest);
  dest->data = newData;
  dest->len = newLen;
  dest->is_static = false;

  assert(StringValid(*dest));
  assert(dest->len == oldLen + src.len);
}

static inline void StringConcatC(Arena *arena, String *dest,
                                 const char *c_str) {
  assert(dest != NULL);
  if (!c_str)
    return;
  String s = StringStatic(c_str);
  StringConcat(arena, dest, s);
}

static inline bool StringEq(String s1, String s2) {
  assert(StringValid(s1));
  assert(StringValid(s2));
  if (s1.len != s2.len)
    return false;
  if (s1.data == s2.data)
    return true;
  if (!s1.data || !s2.data)
    return false;
  return strcmp(s1.data, s2.data) == 0;
}

static inline bool StringEqC(String s, const char *c_str) {
  assert(StringValid(s));
  if (!c_str)
    return s.data == NULL || s.len == 0;
  if (!s.data)
    return false;
  return strcmp(s.data, c_str) == 0;
}

static inline void StringFormat(Arena *arena, String *dest, const char *fmt,
                                ...) {
  assert(arena != NULL);
  assert(dest != NULL);
  assert(fmt != NULL);

  va_list args;
  va_start(args, fmt);
  va_list args_copy;
  va_copy(args_copy, args);
  int needed = vsnprintf(NULL, 0, fmt, args_copy);
  va_end(args_copy);

  // vsnprintf only reports negative on an output/encoding error, which here
  // means a malformed format string. Left unchecked it allocates 0 bytes and
  // publishes a String with len == -1, which breaks every later length
  // check.
  assert(needed >= 0);

  char *buf = arena_alloc(arena, needed + 1);
  int written = vsnprintf(buf, needed + 1, fmt, args);
  (void)written;             // read only by the postcondition assert below
  assert(written == needed); // the measuring pass must agree with the real one
  StringClear(dest);
  dest->data = buf;
  dest->len = needed;
  dest->is_static = false;
  va_end(args);

  assert(StringValid(*dest));
}

#endif // LCARS_STRING_H
