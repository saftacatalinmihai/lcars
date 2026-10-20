#ifndef LCARS_JSON_H
#define LCARS_JSON_H

// A string-aware JSON *scanner*, shared by lcars-cli and the server.
//
// It walks a value's bytes and hands back spans into the buffer it was
// given rather than building a tree. That is all either caller needs - the
// shapes they consume (the `entries` API's objects and arrays) are fixed and
// known - and it cannot be fooled by structure appearing inside a string:
// an entry whose *content* contains the text {"title": must not be mistaken
// for an object, which for a journal full of pasted JSON is not a
// hypothetical.
//
// Why this is its own header: lcars_cli.h grew the scanner first, and the
// server (lcars_embed.h) needs the same thing to read JSON it is handed.
//
// Why `static inline` rather than this codebase's usual
// #ifdef LCARS_IMPLEMENTATION split: it is included from two programs, and
// `static inline` is correct in both and costs nothing - the compiler drops
// what a TU does not call, and no build has two TUs that could collide.
//
// Everything here works on (data, len) pairs and never assumes NUL
// termination: an HTTP response body is not a C string.

#include "lcars_arena.h"
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>

// A slice of the buffer being scanned. `data` points into that buffer, so a
// span outlives nothing - copy through json_span_string() to keep it.
typedef struct JsonSpan {
  const char *data;
  size_t len;
} JsonSpan;

static inline const char *json_skip_ws(const char *p, const char *end);
static inline const char *json_scan_string(const char *p, const char *end);
static inline const char *json_scan_value(const char *p, const char *end);
static inline bool json_object_next(JsonSpan obj, const char **cursor,
                                    JsonSpan *key, JsonSpan *val);
static inline bool json_array_next(JsonSpan arr, const char **cursor,
                                   JsonSpan *val);
static inline bool json_member(JsonSpan obj, const char *key, JsonSpan *out);
static inline void json_utf8_encode(unsigned int cp, char *out,
                                    size_t *out_len);
static inline unsigned int json_hex4(const char *p);
static inline size_t json_unescape(const char *p, const char *end, char *out,
                                   size_t out_size);
static inline const char *json_span_string(Arena *arena, JsonSpan v);
static inline long json_span_long(JsonSpan v);
static inline double json_span_double(JsonSpan v);
static inline void base64_encode(const unsigned char *in, size_t in_len,
                                 char *out, size_t out_size);
static inline const char *json_escape_byte(unsigned char c, char u[7]);

// The escape byte `c` needs inside a JSON string literal, or NULL when it
// goes in as it is. `u` receives the \u00XX form of a control byte with no
// short escape (any raw control byte is illegal inside a JSON string). Every
// JSON writer in the server and in lcars-cli escapes through this one table, so
// a body the CLI sends and a body the server sends look alike.
static inline const char *json_escape_byte(unsigned char c, char u[7]) {
  switch (c) {
  case '"':
    return "\\\"";
  case '\\':
    return "\\\\";
  case '\n':
    return "\\n";
  case '\r':
    return "\\r";
  case '\t':
    return "\\t";
  case '\b':
    return "\\b";
  case '\f':
    return "\\f";
  default:
    if (c < 0x20) {
      snprintf(u, 7, "\\u%04x", c);
      return u;
    }
    return NULL;
  }
}

static inline const char *json_skip_ws(const char *p, const char *end) {
  while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) {
    p++;
  }
  return p;
}

// `p` points at the opening quote. Returns just past the closing quote, or
// NULL if the string never terminates.
static inline const char *json_scan_string(const char *p, const char *end) {
  assert(p != NULL);
  assert(p < end && *p == '"');

  p++;
  while (p < end) {
    if (*p == '\\') {
      p += 2; // the escaped byte can be a quote; skip both
      continue;
    }
    if (*p == '"') {
      return p + 1;
    }
    p++;
  }
  return NULL;
}

// Returns just past the value starting at `p` (leading whitespace allowed),
// or NULL if it is malformed.
static inline const char *json_scan_value(const char *p, const char *end) {
  assert(p != NULL);

  p = json_skip_ws(p, end);
  if (p >= end) {
    return NULL;
  }
  if (*p == '"') {
    return json_scan_string(p, end);
  }
  if (*p == '{' || *p == '[') {
    int depth = 0;
    while (p < end) {
      char c = *p;
      if (c == '"') {
        p = json_scan_string(p, end);
        if (!p) {
          return NULL;
        }
        continue;
      }
      if (c == '{' || c == '[') {
        depth++;
      } else if (c == '}' || c == ']') {
        depth--;
        p++;
        if (depth == 0) {
          return p;
        }
        continue;
      }
      p++;
    }
    return NULL;
  }
  // A number, true, false or null: ends at the first structural byte.
  const char *start = p;
  while (p < end && *p != ',' && *p != '}' && *p != ']' && *p != ' ' &&
         *p != '\t' && *p != '\n' && *p != '\r') {
    p++;
  }
  return (p > start) ? p : NULL;
}

// Iterates the members of `obj` (which must span a whole {...}). The caller
// initializes *cursor to NULL; `key` excludes its quotes, `val` is the raw
// value span.
static inline bool json_object_next(JsonSpan obj, const char **cursor,
                                    JsonSpan *key, JsonSpan *val) {
  assert(cursor != NULL);
  assert(key != NULL && val != NULL);

  if (obj.len < 2 || obj.data[0] != '{') {
    return false;
  }
  const char *end = obj.data + obj.len;
  const char *p = *cursor ? *cursor : obj.data + 1;

  p = json_skip_ws(p, end);
  if (p < end && *p == ',') {
    p = json_skip_ws(p + 1, end);
  }
  if (p >= end || *p == '}' || *p != '"') {
    return false;
  }
  const char *key_end = json_scan_string(p, end);
  if (!key_end) {
    return false;
  }
  key->data = p + 1;
  key->len = (size_t)(key_end - p) - 2;

  p = json_skip_ws(key_end, end);
  if (p >= end || *p != ':') {
    return false;
  }
  p = json_skip_ws(p + 1, end);
  const char *val_end = json_scan_value(p, end);
  if (!val_end) {
    return false;
  }
  val->data = p;
  val->len = (size_t)(val_end - p);
  *cursor = val_end;
  return true;
}

// Same shape for arrays.
static inline bool json_array_next(JsonSpan arr, const char **cursor,
                                   JsonSpan *val) {
  assert(cursor != NULL);
  assert(val != NULL);

  if (arr.len < 2 || arr.data[0] != '[') {
    return false;
  }
  const char *end = arr.data + arr.len;
  const char *p = *cursor ? *cursor : arr.data + 1;

  p = json_skip_ws(p, end);
  if (p < end && *p == ',') {
    p = json_skip_ws(p + 1, end);
  }
  if (p >= end || *p == ']') {
    return false;
  }
  const char *val_end = json_scan_value(p, end);
  if (!val_end) {
    return false;
  }
  val->data = p;
  val->len = (size_t)(val_end - p);
  *cursor = val_end;
  return true;
}

static inline bool json_member(JsonSpan obj, const char *key, JsonSpan *out) {
  assert(key != NULL);
  assert(out != NULL);

  size_t key_len = strlen(key);
  const char *cursor = NULL;
  JsonSpan k, v;
  while (json_object_next(obj, &cursor, &k, &v)) {
    if (k.len == key_len && memcmp(k.data, key, key_len) == 0) {
      *out = v;
      return true;
    }
  }
  return false;
}

static inline void json_utf8_encode(unsigned int cp, char *out,
                                    size_t *out_len) {
  assert(out != NULL);
  assert(out_len != NULL);

  if (cp < 0x80) {
    out[(*out_len)++] = (char)cp;
  } else if (cp < 0x800) {
    out[(*out_len)++] = (char)(0xC0 | (cp >> 6));
    out[(*out_len)++] = (char)(0x80 | (cp & 0x3F));
  } else if (cp < 0x10000) {
    out[(*out_len)++] = (char)(0xE0 | (cp >> 12));
    out[(*out_len)++] = (char)(0x80 | ((cp >> 6) & 0x3F));
    out[(*out_len)++] = (char)(0x80 | (cp & 0x3F));
  } else {
    out[(*out_len)++] = (char)(0xF0 | (cp >> 18));
    out[(*out_len)++] = (char)(0x80 | ((cp >> 12) & 0x3F));
    out[(*out_len)++] = (char)(0x80 | ((cp >> 6) & 0x3F));
    out[(*out_len)++] = (char)(0x80 | (cp & 0x3F));
  }
}

static inline unsigned int json_hex4(const char *p) {
  assert(p != NULL);

  unsigned int v = 0;
  for (int i = 0; i < 4; i++) {
    char c = p[i];
    unsigned int d;
    if (c >= '0' && c <= '9') {
      d = (unsigned int)(c - '0');
    } else if (c >= 'a' && c <= 'f') {
      d = (unsigned int)(c - 'a') + 10;
    } else if (c >= 'A' && c <= 'F') {
      d = (unsigned int)(c - 'A') + 10;
    } else {
      return 0;
    }
    v = (v << 4) | d;
  }
  return v;
}

// Decodes the escapes of a JSON string's inside (`p` to `end`, quotes not
// included) into `out`, at most `out_size - 1` bytes and always terminated.
// A character that would not fit whole is left out with everything after
// it, so a cut never ends mid UTF-8 sequence. Returns the bytes written.
static inline size_t json_unescape(const char *p, const char *end, char *out,
                                   size_t out_size) {
  assert(p != NULL && end != NULL && p <= end);
  assert(out != NULL && out_size > 0);

  size_t out_len = 0;
  while (p < end) {
    char one = *p;
    if (one != '\\') {
      if (out_len + 1 >= out_size) {
        break;
      }
      out[out_len++] = one;
      p++;
      continue;
    }
    p++;
    if (p >= end) {
      break;
    }
    if (*p == 'u') {
      if (end - p < 5) {
        break;
      }
      unsigned int cp = json_hex4(p + 1);
      const char *next = p + 5;
      // A surrogate pair arrives as two \u escapes; combining them here is
      // what keeps non-BMP text (emoji in a title) intact.
      if (cp >= 0xD800 && cp <= 0xDBFF && end - next >= 6 && next[0] == '\\' &&
          next[1] == 'u') {
        unsigned int lo = json_hex4(next + 2);
        if (lo >= 0xDC00 && lo <= 0xDFFF) {
          cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
          next += 6;
        }
      }
      size_t need = cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
      if (out_len + need >= out_size) {
        break;
      }
      json_utf8_encode(cp, out, &out_len);
      p = next;
      continue;
    }
    switch (*p) {
    case 'n':
      one = '\n';
      break;
    case 't':
      one = '\t';
      break;
    case 'r':
      one = '\r';
      break;
    case 'b':
      one = '\b';
      break;
    case 'f':
      one = '\f';
      break;
    default:
      one = *p; // \" \\ \/ and anything unrecognized: the byte as it is
      break;
    }
    if (out_len + 1 >= out_size) {
      break;
    }
    out[out_len++] = one;
    p++;
  }
  out[out_len] = '\0';
  assert(out_len < out_size);
  return out_len;
}

// Unescapes a JSON string span (quotes included) into `arena`. Every escape
// sequence is at least as long as the bytes it produces, so the source
// length is always a sufficient budget.
static inline const char *json_span_string(Arena *arena, JsonSpan v) {
  assert(arena_valid(arena));

  if (v.len == 4 && memcmp(v.data, "null", 4) == 0) {
    return "";
  }
  if (v.len < 2 || v.data[0] != '"') {
    // A non-string where a string was expected: hand back the raw bytes
    // rather than inventing an error the caller has no use for.
    char *raw = (char *)arena_alloc(arena, v.len + 1);
    memcpy(raw, v.data, v.len);
    raw[v.len] = '\0';
    return raw;
  }
  char *out = (char *)arena_alloc(arena, v.len + 1);
  json_unescape(v.data + 1, v.data + v.len - 1, out, v.len + 1);
  return out;
}

static inline long json_span_long(JsonSpan v) {
  if (v.len == 4 && memcmp(v.data, "true", 4) == 0) {
    return 1;
  }
  if (v.len == 5 && memcmp(v.data, "false", 5) == 0) {
    return 0;
  }
  char tmp[64];
  size_t n = v.len < sizeof(tmp) - 1 ? v.len : sizeof(tmp) - 1;
  memcpy(tmp, v.data, n);
  tmp[n] = '\0';
  return strtol(tmp, NULL, 10);
}

static inline double json_span_double(JsonSpan v) {
  char tmp[64];
  size_t n = v.len < sizeof(tmp) - 1 ? v.len : sizeof(tmp) - 1;
  memcpy(tmp, v.data, n);
  tmp[n] = '\0';
  return strtod(tmp, NULL);
}

// ---------------------------------------------------------------------------
// Arena-backed growable buffer
// ---------------------------------------------------------------------------

// The one append buffer of both programs (request bodies, URLs, answers).
// Rows are appended straight into it instead of being formatted through a
// fixed stack buffer first, which is what used to truncate any entry over
// ~4KB in the middle of its JSON string.
//
// The server's (jsonbuf_init) checks growth against the arena's remaining
// space rather than leaving it to arena_alloc, because the arena aborts on
// OOM and "the client asked for more rows than fit in 1MB" is a request to
// reject, not a programmer error: it sets `overflow`, drops what does not
// fit, and SendJSONBuf answers 500. lcars-cli's (jsonbuf_init_strict) has
// 32MB and no one to answer, so running out aborts like any other
// allocation would - never a silently cut body or output.
typedef struct JSONBuf {
  Arena *arena;
  char *data;
  size_t len;
  size_t cap;
  bool overflow;
  bool strict;
} JSONBuf;

static inline void jsonbuf_init(JSONBuf *b, Arena *arena) {
  assert(b != NULL);
  assert(arena_valid(arena));
  b->arena = arena;
  b->data = NULL;
  b->len = 0;
  b->cap = 0;
  b->overflow = false;
  b->strict = false;
}

static inline bool jsonbuf_reserve(JSONBuf *b, size_t extra) {
  assert(b != NULL);
  assert(arena_valid(b->arena));

  if (b->overflow) {
    return false;
  }
  size_t need = b->len + extra + 1; // + terminator
  if (need <= b->cap) {
    return true;
  }
  size_t new_cap = b->cap > 0 ? b->cap : 4096;
  while (new_cap < need) {
    new_cap *= 2;
  }

  // Where the bump pointer would end up. A buffer that is still the arena's
  // most recent allocation grows in place (arena_realloc's fast path), so it
  // does not cost its old size again; anything else is copied to a fresh
  // block, with room for worst-case alignment padding.
  size_t offset_after;
  if (b->data != NULL && (size_t)((uint8_t *)b->data - b->arena->buffer) ==
                             b->arena->prev_offset) {
    offset_after = b->arena->prev_offset + new_cap;
  } else {
    offset_after = b->arena->curr_offset + sizeof(void *) + new_cap;
  }
  if (offset_after > b->arena->capacity && !b->strict) {
    b->overflow = true;
    return false;
  }

  b->data = (char *)arena_realloc(b->arena, b->data, b->cap, new_cap);
  b->cap = new_cap;
  assert(b->len + 1 <= b->cap);
  return true;
}

static inline void jsonbuf_init_strict(JSONBuf *b, Arena *arena) {
  jsonbuf_init(b, arena);
  b->strict = true;
  // never NULL, so a buffer nothing was appended to is still ""
  jsonbuf_reserve(b, 0);
  b->data[0] = '\0';
}

static inline void jsonbuf_append_len(JSONBuf *b, const char *s, size_t n) {
  assert(b != NULL);
  assert(s != NULL || n == 0);
  if (!jsonbuf_reserve(b, n)) {
    return;
  }
  assert(b->len + n < b->cap);
  memcpy(b->data + b->len, s, n);
  b->len += n;
  b->data[b->len] = '\0';
}

static inline void jsonbuf_append(JSONBuf *b, const char *s) {
  jsonbuf_append_len(b, s, strlen(s));
}

// Only ever formats numbers, timestamps and short fixed literals - the
// unbounded text (titles, content) goes through jsonbuf_append_json_string
// instead, so the scratch here cannot be overrun by user data.
static inline void jsonbuf_appendf(JSONBuf *b, const char *fmt, ...) {
  assert(b != NULL);
  assert(fmt != NULL);
  char tmp[1024];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
  va_end(ap);
  assert(n >= 0 && n < (int)sizeof(tmp));
  jsonbuf_append_len(b, tmp, (size_t)n);
}

// Appends `s` as a quoted, fully escaped JSON string of any length.
static inline void jsonbuf_append_json_string(JSONBuf *b, const char *s) {
  assert(b != NULL);
  jsonbuf_append_len(b, "\"", 1);
  char u[7];
  for (const char *p = s ? s : ""; *p; p++) {
    const char *esc = json_escape_byte((unsigned char)*p, u);
    jsonbuf_append_len(b, esc ? esc : p, esc ? strlen(esc) : 1);
  }
  jsonbuf_append_len(b, "\"", 1);
}

// ---------------------------------------------------------------------------
// Wire encodings
// ---------------------------------------------------------------------------
//
// Not JSON, but they live here for the same reason the scanner does: both
// lcars-cli needs them to talk to the HTTP API. lcars_http.h has
// base64_decode for the server side of Basic auth; this is the client side
// of the same handshake.

// Writes RFC 4648 base64 of `in_len` bytes into `out`, NUL-terminated.
// `out` must hold at least 4 * ((in_len + 2) / 3) + 1 bytes; the assert
// below is the caller's contract, not a runtime check.
static inline void base64_encode(const unsigned char *in, size_t in_len,
                                 char *out, size_t out_size) {
  static const char tbl[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  assert(in != NULL || in_len == 0);
  assert(out != NULL);
  assert(out_size >= 4 * ((in_len + 2) / 3) + 1);

  size_t o = 0;
  size_t i = 0;
  for (; i + 2 < in_len; i += 3) {
    unsigned int v = ((unsigned int)in[i] << 16) |
                     ((unsigned int)in[i + 1] << 8) | (unsigned int)in[i + 2];
    out[o++] = tbl[(v >> 18) & 0x3F];
    out[o++] = tbl[(v >> 12) & 0x3F];
    out[o++] = tbl[(v >> 6) & 0x3F];
    out[o++] = tbl[v & 0x3F];
  }
  // The tail is 0, 1 or 2 bytes; base64 pads the missing ones with '=' so
  // the decoder can tell 1 from 2 without a length.
  if (i < in_len) {
    unsigned int v = (unsigned int)in[i] << 16;
    bool haveTwo = (i + 1 < in_len);
    if (haveTwo) {
      v |= (unsigned int)in[i + 1] << 8;
    }
    out[o++] = tbl[(v >> 18) & 0x3F];
    out[o++] = tbl[(v >> 12) & 0x3F];
    out[o++] = haveTwo ? tbl[(v >> 6) & 0x3F] : '=';
    out[o++] = '=';
  }
  out[o] = '\0';

  assert(o < out_size);
  assert(o % 4 == 0);
}

#endif // LCARS_JSON_H
