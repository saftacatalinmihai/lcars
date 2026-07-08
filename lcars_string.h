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

static inline String StringInit(Arena *arena, const char *c_str) {
  String s;
  if (c_str == NULL) {
    s.data = arena_alloc(arena, 1);
    if (s.data)
      s.data[0] = '\0';
    s.len = 0;
    s.is_static = false;
  } else {
    s.len = (int)strlen(c_str);
    s.data = arena_alloc(arena, s.len + 1);
    if (s.data) {
      memcpy(s.data, c_str, s.len + 1);
    }
    s.is_static = false;
  }
  return s;
}

static inline String StringInitLen(Arena *arena, const char *c_str, int len) {
  String s;
  if (c_str == NULL || len <= 0) {
    s.data = arena_alloc(arena, 1);
    if (s.data)
      s.data[0] = '\0';
    s.len = 0;
    s.is_static = false;
  } else {
    s.len = len;
    s.data = arena_alloc(arena, s.len + 1);
    if (s.data) {
      memcpy(s.data, c_str, len);
      s.data[len] = '\0';
    }
    s.is_static = false;
  }
  return s;
}

static inline String StringStatic(const char *c_str) {
  String s;
  s.data = (char *)(c_str ? c_str : "");
  s.len = (int)strlen(s.data);
  s.is_static = true;
  return s;
}

static inline void StringFree(String *s) {
  if (s) {
    s->data = NULL;
    s->len = 0;
    s->is_static = true;
  }
}

static inline String StringDup(Arena *arena, String src) {
  if (src.is_static) {
    return src;
  }
  return StringInit(arena, src.data);
}

static inline void StringAssign(Arena *arena, String *dest, String src) {
  if (dest == &src)
    return;
  StringFree(dest);
  *dest = StringDup(arena, src);
}

static inline void StringAssignC(Arena *arena, String *dest, const char *c_str) {
  StringFree(dest);
  *dest = StringInit(arena, c_str);
}

static inline void StringAssignStatic(String *dest, const char *c_str) {
  StringFree(dest);
  *dest = StringStatic(c_str);
}

static inline void StringConcat(Arena *arena, String *dest, String src) {
  if (!src.data || src.len == 0)
    return;
  int newLen = dest->len + src.len;
  char *newData = arena_alloc(arena, newLen + 1);
  if (newData) {
    if (dest->data && dest->len > 0) {
      memcpy(newData, dest->data, dest->len);
    }
    memcpy(newData + dest->len, src.data, src.len);
    newData[newLen] = '\0';
  }
  StringFree(dest);
  dest->data = newData;
  dest->len = newLen;
  dest->is_static = false;
}

static inline void StringConcatC(Arena *arena, String *dest, const char *c_str) {
  if (!c_str)
    return;
  String s = StringStatic(c_str);
  StringConcat(arena, dest, s);
}

static inline bool StringEq(String s1, String s2) {
  if (s1.len != s2.len)
    return false;
  if (s1.data == s2.data)
    return true;
  if (!s1.data || !s2.data)
    return false;
  return strcmp(s1.data, s2.data) == 0;
}

static inline bool StringEqC(String s, const char *c_str) {
  if (!c_str)
    return s.data == NULL || s.len == 0;
  if (!s.data)
    return false;
  return strcmp(s.data, c_str) == 0;
}

static inline void StringFormat(Arena *arena, String *dest, const char *fmt, ...) {
  va_list args;
  va_start(args, fmt);
  va_list args_copy;
  va_copy(args_copy, args);
  int needed = vsnprintf(NULL, 0, fmt, args_copy);
  va_end(args_copy);

  char *buf = arena_alloc(arena, needed + 1);
  if (buf) {
    vsnprintf(buf, needed + 1, fmt, args);
    StringFree(dest);
    dest->data = buf;
    dest->len = needed;
    dest->is_static = false;
  }
  va_end(args);
}

#endif // LCARS_STRING_H
