#ifndef LCARS_HTTP_H
#define LCARS_HTTP_H

// Starts the HTTP server on the specified port in a separate thread.
void StartHTTPServer(int port);
// Runs the HTTP server on the specified port, blocking the current thread.
void RunHTTPServer(int port);
// Configures Basic Auth credentials.
void SetHTTPServerCredentials(const char *username, const char *password);

#ifdef LCARS_HTTP_IMPLEMENTATION

#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <limits.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <unistd.h>

#include "lcars_arena.h"
#include "lcars_base.h"

// Every send() below passes MSG_NOSIGNAL: a client that hangs up mid-response
// must not raise SIGPIPE and kill the whole process (the UI runs in it too).
// The unity build reaches features.h long before this file's _GNU_SOURCE, so
// under -std=c11 the constant can be missing; 0 just restores the old
// behaviour on such a platform rather than failing to compile.
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

// A request body larger than this is refused with 413 rather than handed to
// the connection's 1MB stack arena, where arena OOM is a deliberate abort()
// - i.e. one oversized (or malicious) request would take the whole process
// down, UI included. Content-Length is attacker-controlled, so this is a
// runtime condition to handle, not something to assert.
#define HTTP_MAX_BODY_BYTES (512 * 1024)
// Defaults and ceiling for GET /entries pagination. The ceiling exists for
// the same reason as the body cap: the whole response is built in the
// connection arena, so an unbounded row count is an abort waiting to happen.
#define HTTP_DEFAULT_LIMIT 200
#define HTTP_MAX_LIMIT 1000
// Widest timestamp the date filters accept: "YYYY-MM-DD HH:MM:SS".
#define HTTP_MAX_TIMESTAMP_LEN 19

#define HTTP_CORS_HEADERS                                                      \
  "Access-Control-Allow-Origin: *\r\n"                                         \
  "Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\n"   \
  "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"

static char g_auth_user[128] = {0};
static char g_auth_pass[128] = {0};
static bool g_auth_enabled = false;

void SetHTTPServerCredentials(const char *username, const char *password) {
  if (username) {
    strncpy(g_auth_user, username, sizeof(g_auth_user) - 1);
    g_auth_user[sizeof(g_auth_user) - 1] = '\0';
  }
  if (password) {
    strncpy(g_auth_pass, password, sizeof(g_auth_pass) - 1);
    g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
  }
  g_auth_enabled = true;
}

static int base64_decode(const char *in, char *out, int out_max) {
  assert(in != NULL);
  assert(out != NULL);
  // out[len] = '\0' below is only bounded by out_max - 1, so a zero-sized
  // output buffer writes out[-1].
  assert(out_max > 0);

  static const int table[] = {
      -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
      -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
      -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 62, -1, -1, -1, 63,
      52, 53, 54, 55, 56, 57, 58, 59, 60, 61, -1, -1, -1, 0,  -1, -1,
      -1, 0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10, 11, 12, 13, 14,
      15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, -1, -1, -1, -1, -1,
      -1, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
      41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, -1, -1, -1, -1, -1};
  int len = 0;
  int val = 0;
  int valb = -8;
  for (int i = 0; in[i] != '\0'; i++) {
    unsigned char c = in[i];
    if (c > 127 || table[c] == -1) {
      if (c == '=')
        break;
      continue;
    }
    val = (val << 6) + table[c];
    valb += 6;
    if (valb >= 0) {
      if (len < out_max - 1) {
        out[len++] = (char)((val >> valb) & 0xFF);
      }
      valb -= 8;
    }
    if (valb == -8) {
      val = 0;
    }
  }
  assert(len >= 0 && len < out_max); // the terminator must fit
  out[len] = '\0';
  return len;
}

// ---------------------------------------------------------------------------
// Responses
// ---------------------------------------------------------------------------

static const char *http_status_text(int status) {
  switch (status) {
  case 200:
    return "OK";
  case 201:
    return "Created";
  case 204:
    return "No Content";
  case 400:
    return "Bad Request";
  case 401:
    return "Unauthorized";
  case 404:
    return "Not Found";
  case 405:
    return "Method Not Allowed";
  case 413:
    return "Payload Too Large";
  case 500:
    return "Internal Server Error";
  default:
    // Every status this file sends is listed above; a missing one would
    // otherwise go out with a nonsense reason phrase.
    assert(!"unhandled HTTP status code");
    return "Error";
  }
}

// Sends a complete response and returns `status`, so handlers can
// `return SendHTTPResponse(...)`. All sends use MSG_NOSIGNAL: a client that
// disappears mid-response must not raise SIGPIPE and kill the process.
static int SendHTTPResponse(int client_fd, int status, const char *content_type,
                            const char *body, size_t body_len) {
  assert(client_fd >= 0);
  assert(content_type != NULL);
  assert(body != NULL || body_len == 0);

  char header[512];
  int header_len = snprintf(
      header, sizeof(header),
      "HTTP/1.1 %d %s\r\n"
      "Content-Type: %s\r\n" HTTP_CORS_HEADERS "Content-Length: %zu\r\n"
      "\r\n",
      status, http_status_text(status), content_type, body_len);
  assert(header_len > 0 && header_len < (int)sizeof(header));
  send(client_fd, header, (size_t)header_len, MSG_NOSIGNAL);
  if (body_len > 0) {
    send(client_fd, body, body_len, MSG_NOSIGNAL);
  }
  return status;
}

static int SendJSON(int client_fd, int status, const char *body,
                    size_t body_len) {
  return SendHTTPResponse(client_fd, status, "application/json", body,
                          body_len);
}

// Escapes `src` into a fixed buffer for the one place a JSON string has to
// be built without an arena: error messages (mostly sqlite3_errmsg text).
// Truncates rather than overflowing - never at a half-written escape, so the
// result is always a valid JSON string body.
static void json_escape_buf(char *dst, size_t dst_size, const char *src) {
  assert(dst != NULL);
  assert(dst_size > 0);

  size_t out = 0;
  for (const char *p = src ? src : ""; *p; p++) {
    const char *esc = NULL;
    char unicode[7];
    unsigned char c = (unsigned char)*p;
    switch (c) {
    case '"':
      esc = "\\\"";
      break;
    case '\\':
      esc = "\\\\";
      break;
    case '\n':
      esc = "\\n";
      break;
    case '\r':
      esc = "\\r";
      break;
    case '\t':
      esc = "\\t";
      break;
    case '\b':
      esc = "\\b";
      break;
    case '\f':
      esc = "\\f";
      break;
    default:
      if (c < 0x20) {
        snprintf(unicode, sizeof(unicode), "\\u%04x", c);
        esc = unicode;
      }
      break;
    }
    size_t need = esc ? strlen(esc) : 1;
    if (out + need >= dst_size) {
      break;
    }
    if (esc) {
      memcpy(dst + out, esc, need);
    } else {
      dst[out] = (char)c;
    }
    out += need;
  }
  assert(out < dst_size);
  dst[out] = '\0';
}

static int SendJSONError(int client_fd, int status, const char *fmt, ...) {
  assert(client_fd >= 0);
  assert(fmt != NULL);

  char msg[512];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(msg, sizeof(msg), fmt, ap);
  va_end(ap);

  char escaped[1024];
  json_escape_buf(escaped, sizeof(escaped), msg);

  char body[1200];
  int len = snprintf(body, sizeof(body), "{\"error\":\"%s\",\"status\":%d}",
                     escaped, status);
  assert(len > 0);
  if (len >= (int)sizeof(body)) {
    len = (int)sizeof(body) - 1;
  }
  return SendJSON(client_fd, status, body, (size_t)len);
}

// ---------------------------------------------------------------------------
// Arena-backed growable JSON buffer
// ---------------------------------------------------------------------------

// Rows are appended straight into this instead of being formatted through a
// fixed stack buffer first, which is what used to truncate any entry over
// ~4KB in the middle of its JSON string. Growth is checked against the
// arena's remaining space rather than left to arena_alloc, because the arena
// aborts on OOM and "the client asked for more rows than fit in 1MB" is a
// request to reject, not a programmer error.
typedef struct JSONBuf {
  Arena *arena;
  char *data;
  size_t len;
  size_t cap;
  bool overflow;
} JSONBuf;

static void jsonbuf_init(JSONBuf *b, Arena *arena) {
  assert(b != NULL);
  assert(arena_valid(arena));
  b->arena = arena;
  b->data = NULL;
  b->len = 0;
  b->cap = 0;
  b->overflow = false;
}

static bool jsonbuf_reserve(JSONBuf *b, size_t extra) {
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
  if (offset_after > b->arena->capacity) {
    b->overflow = true;
    return false;
  }

  b->data = (char *)arena_realloc(b->arena, b->data, b->cap, new_cap);
  b->cap = new_cap;
  assert(b->len + 1 <= b->cap);
  return true;
}

static void jsonbuf_append_len(JSONBuf *b, const char *s, size_t n) {
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

static void jsonbuf_append(JSONBuf *b, const char *s) {
  jsonbuf_append_len(b, s, strlen(s));
}

// Only ever formats numbers and short fixed literals - the unbounded text
// (titles, content) goes through jsonbuf_append_json_string instead, so the
// 512-byte scratch here cannot be overrun by user data.
static void jsonbuf_appendf(JSONBuf *b, const char *fmt, ...) {
  assert(b != NULL);
  assert(fmt != NULL);
  char tmp[512];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
  va_end(ap);
  assert(n >= 0 && n < (int)sizeof(tmp));
  jsonbuf_append_len(b, tmp, (size_t)n);
}

// Appends `s` as a quoted, fully escaped JSON string of any length.
static void jsonbuf_append_json_string(JSONBuf *b, const char *s) {
  assert(b != NULL);
  jsonbuf_append_len(b, "\"", 1);
  for (const char *p = s ? s : ""; *p; p++) {
    unsigned char c = (unsigned char)*p;
    switch (c) {
    case '"':
      jsonbuf_append_len(b, "\\\"", 2);
      break;
    case '\\':
      jsonbuf_append_len(b, "\\\\", 2);
      break;
    case '\n':
      jsonbuf_append_len(b, "\\n", 2);
      break;
    case '\r':
      jsonbuf_append_len(b, "\\r", 2);
      break;
    case '\t':
      jsonbuf_append_len(b, "\\t", 2);
      break;
    case '\b':
      jsonbuf_append_len(b, "\\b", 2);
      break;
    case '\f':
      jsonbuf_append_len(b, "\\f", 2);
      break;
    default:
      if (c < 0x20) {
        // Any other control byte is illegal raw inside a JSON string.
        char unicode[7];
        snprintf(unicode, sizeof(unicode), "\\u%04x", c);
        jsonbuf_append_len(b, unicode, 6);
      } else {
        jsonbuf_append_len(b, (const char *)&c, 1);
      }
      break;
    }
  }
  jsonbuf_append_len(b, "\"", 1);
}

// Sends the buffer, or a 500 if it ran out of arena mid-build (a partial
// JSON document must never go out as if it were the whole answer).
static int SendJSONBuf(int client_fd, JSONBuf *b) {
  assert(client_fd >= 0);
  assert(b != NULL);
  if (b->overflow) {
    return SendJSONError(client_fd, 500,
                         "Response too large for the connection buffer; "
                         "narrow the query (limit/offset/content=0)");
  }
  return SendJSON(client_fd, 200, b->data ? b->data : "", b->len);
}

// ---------------------------------------------------------------------------
// Request parsing helpers
// ---------------------------------------------------------------------------

// Simple JSON extraction helpers. NOTE: the key is found with strstr, so a
// string *value* that happens to contain "\"kind\"" can be mistaken for the
// key. Fine for this API's clients (Shortcuts, curl, the app itself); a real
// parser is the fix if that ever bites.
static bool json_get_string(const char *json, const char *key, char *out_val,
                            size_t max_len) {
  assert(json != NULL);
  assert(key != NULL);
  assert(out_val != NULL);
  // `len < max_len - 1` underflows into a huge size_t when max_len is 0.
  assert(max_len > 0);

  char pattern[128];
  assert(strlen(key) + 3 <= sizeof(pattern)); // quotes plus terminator
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p)
    return false;
  p += strlen(pattern);
  while (*p &&
         (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
    p++;
  }
  if (*p == '"') {
    p++;
    size_t len = 0;
    while (*p && *p != '"' && len < max_len - 1) {
      if (*p == '\\' && *(p + 1)) {
        p++;
      }
      out_val[len++] = *p++;
    }
    assert(len < max_len); // the terminator must fit
    out_val[len] = '\0';
    return true;
  }
  return false;
}

// Same lookup, but the value is copied into `arena` at whatever length it
// has. Entry content is a journal entry - it does not fit a fixed buffer,
// and truncating it to one silently loses the tail of what the client sent.
// \uXXXX is passed through verbatim (no client of this API emits it).
static bool json_get_string_arena(Arena *arena, const char *json,
                                  const char *key, char **out_val) {
  assert(arena_valid(arena));
  assert(json != NULL);
  assert(key != NULL);
  assert(out_val != NULL);

  char pattern[128];
  assert(strlen(key) + 3 <= sizeof(pattern));
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p)
    return false;
  p += strlen(pattern);
  while (*p &&
         (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
    p++;
  }
  if (*p != '"') {
    return false;
  }
  p++;
  // Escapes only ever shrink, so what is left of the body bounds the decoded
  // value. The + 2 covers the unterminated-string case (a malformed body,
  // i.e. runtime input): the loop then consumes every remaining byte and
  // still has room for the terminator.
  size_t max_len = strlen(p) + 2;
  char *out = (char *)arena_alloc(arena, max_len);
  size_t len = 0;
  while (*p && *p != '"') {
    char c = *p;
    if (c == '\\' && *(p + 1)) {
      p++;
      switch (*p) {
      case 'n':
        c = '\n';
        break;
      case 'r':
        c = '\r';
        break;
      case 't':
        c = '\t';
        break;
      case 'b':
        c = '\b';
        break;
      case 'f':
        c = '\f';
        break;
      default:
        c = *p; // \" \\ \/ and anything unrecognized: take the byte as-is
        break;
      }
    }
    assert(len < max_len - 1);
    out[len++] = c;
    p++;
  }
  out[len] = '\0';
  *out_val = out;
  return true;
}

static bool json_get_int(const char *json, const char *key, int *out_val) {
  assert(json != NULL);
  assert(key != NULL);
  assert(out_val != NULL);

  char pattern[128];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p)
    return false;
  p += strlen(pattern);
  while (*p &&
         (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
    p++;
  }
  // Accept "1"/"0" as well as 1/0: Shortcuts and shell clients quote
  // everything, and rejecting that silently drops the field.
  if (*p == '"') {
    p++;
  }
  char *endptr;
  long val = strtol(p, &endptr, 10);
  if (p == endptr)
    return false;
  *out_val = (int)val;
  return true;
}

static bool json_get_float(const char *json, const char *key, float *out_val) {
  assert(json != NULL);
  assert(key != NULL);
  assert(out_val != NULL);

  char pattern[128];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p)
    return false;
  p += strlen(pattern);
  while (*p &&
         (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ':')) {
    p++;
  }
  if (*p == '"') {
    p++;
  }
  char *endptr;
  float val = strtof(p, &endptr);
  if (p == endptr)
    return false;
  *out_val = val;
  return true;
}

static int hex_digit_value(char c) {
  if (c >= '0' && c <= '9')
    return c - '0';
  if (c >= 'a' && c <= 'f')
    return 10 + (c - 'a');
  if (c >= 'A' && c <= 'F')
    return 10 + (c - 'A');
  return -1;
}

// Percent-decodes `src` (up to src_len bytes, '+' meaning space) into `dst`,
// truncating at dst_size - 1 bytes. Returns the decoded length.
static size_t url_decode(char *dst, size_t dst_size, const char *src,
                         size_t src_len) {
  assert(dst != NULL);
  assert(dst_size > 0);
  assert(src != NULL || src_len == 0);

  size_t out = 0;
  for (size_t i = 0; i < src_len && out < dst_size - 1; i++) {
    char c = src[i];
    if (c == '+') {
      c = ' ';
    } else if (c == '%' && i + 2 < src_len) {
      int hi = hex_digit_value(src[i + 1]);
      int lo = hex_digit_value(src[i + 2]);
      if (hi >= 0 && lo >= 0) {
        c = (char)((hi << 4) | lo);
        i += 2;
      }
    }
    dst[out++] = c;
  }
  assert(out < dst_size);
  dst[out] = '\0';
  return out;
}

// Looks `key` up in a raw `a=1&b=2` query string, percent-decoding the value
// into `out`. Returns false when the key isn't present at all; a valueless
// key ("?foo") yields an empty string and true, which is what makes
// "?content=" and flag-style parameters work.
static bool query_get(const char *query, const char *key, char *out,
                      size_t out_size) {
  assert(query != NULL);
  assert(key != NULL);
  assert(out != NULL);
  assert(out_size > 0);

  size_t key_len = strlen(key);
  assert(key_len > 0);

  const char *p = query;
  while (*p) {
    const char *amp = strchr(p, '&');
    const char *end = amp ? amp : p + strlen(p);
    const char *eq = memchr(p, '=', (size_t)(end - p));
    size_t name_len = (size_t)((eq ? eq : end) - p);
    if (name_len == key_len && strncmp(p, key, key_len) == 0) {
      const char *val = eq ? eq + 1 : end;
      url_decode(out, out_size, val, (size_t)(end - val));
      return true;
    }
    if (!amp) {
      break;
    }
    p = amp + 1;
  }
  return false;
}

// Reads an integer query parameter. Returns false if absent; sets *out_ok to
// false if present but not a number, so callers can answer 400 instead of
// silently ignoring a typo'd filter.
static bool query_get_int(const char *query, const char *key, int *out_val,
                          bool *out_ok) {
  assert(out_val != NULL);
  assert(out_ok != NULL);

  char buf[64];
  *out_ok = true;
  if (!query_get(query, key, buf, sizeof(buf))) {
    return false;
  }
  char *endptr;
  long val = strtol(buf, &endptr, 10);
  if (endptr == buf || *endptr != '\0' || val < INT_MIN || val > INT_MAX) {
    *out_ok = false;
    return false;
  }
  *out_val = (int)val;
  return true;
}

// Reads a boolean-ish query parameter: 1/true/yes/on vs 0/false/no/off, plus
// the bare "?flag" form (present, empty) meaning true.
static bool query_get_bool(const char *query, const char *key, bool *out_val,
                           bool *out_ok) {
  assert(out_val != NULL);
  assert(out_ok != NULL);

  char buf[32];
  *out_ok = true;
  if (!query_get(query, key, buf, sizeof(buf))) {
    return false;
  }
  if (buf[0] == '\0' || strcasecmp(buf, "1") == 0 ||
      strcasecmp(buf, "true") == 0 || strcasecmp(buf, "yes") == 0 ||
      strcasecmp(buf, "on") == 0) {
    *out_val = true;
    return true;
  }
  if (strcasecmp(buf, "0") == 0 || strcasecmp(buf, "false") == 0 ||
      strcasecmp(buf, "no") == 0 || strcasecmp(buf, "off") == 0) {
    *out_val = false;
    return true;
  }
  *out_ok = false;
  return false;
}

static const char *find_header_value(const char *headers,
                                     const char *header_name) {
  assert(headers != NULL);
  assert(header_name != NULL);
  size_t name_len = strlen(header_name);
  assert(name_len > 0); // strncasecmp of 0 bytes matches everything
  const char *p = headers;
  while (p && *p) {
    if (strncasecmp(p, header_name, name_len) == 0) {
      const char *val = p + name_len;
      while (*val == ' ' || *val == '\t')
        val++;
      return val;
    }
    p = strstr(p, "\r\n");
    if (p)
      p += 2;
  }
  return NULL;
}

typedef struct HTTPRequestLine {
  char method[16];
  char path[256];
} HTTPRequestLine;

// Reads the HTTP request (headers, and any body bytes that happen to
// arrive in the same recv burst) from client_fd into req_buf (must be
// req_buf_size bytes), stopping at the blank line ending headers or when
// req_buf fills up. Parses the request line into *out_line, and reports
// how much was read / where the body starts via the other out-params
// (needed later to know how many body bytes were already buffered before
// the rest are read separately). On failure (missing header-terminator,
// or an unparseable request line), prints a diagnostic and returns false
// - neither failure mode has ever sent an HTTP response before closing
// the connection, and this preserves that.
static bool ReadHTTPRequestLine(int client_fd, char *req_buf,
                                size_t req_buf_size, int *out_total_read,
                                char **out_body_start, int *out_headers_len,
                                HTTPRequestLine *out_line) {
  assert(client_fd >= 0);
  assert(req_buf != NULL);
  // req_buf[total_read] = '\0' with total_read bounded by req_buf_size - 1.
  assert(req_buf_size > 1);
  assert(out_total_read != NULL && out_body_start != NULL);
  assert(out_headers_len != NULL && out_line != NULL);

  int total_read = 0;
  while (total_read < (int)req_buf_size - 1) {
    int n =
        recv(client_fd, req_buf + total_read, req_buf_size - 1 - total_read, 0);
    if (n <= 0)
      break;
    total_read += n;
    req_buf[total_read] = '\0';
    if (strstr(req_buf, "\r\n\r\n")) {
      break;
    }
  }
  assert(total_read >= 0 && total_read < (int)req_buf_size);
  *out_total_read = total_read;

  char *body_start = strstr(req_buf, "\r\n\r\n");
  if (!body_start) {
    printf("HTTP Connection Error: Missing end-of-header delimiter\n");
    return false;
  }
  body_start += 4;
  *out_body_start = body_start;
  *out_headers_len = (int)(body_start - req_buf);
  // ReadHTTPRequestBody() computes `total_read - headers_len` as the count
  // of body bytes already buffered, so the delimiter must lie within what
  // was actually read.
  assert(*out_headers_len > 0 && *out_headers_len <= total_read);

  if (sscanf(req_buf, "%15s %255s", out_line->method, out_line->path) != 2) {
    printf("HTTP Request Parsing Failure: Cannot parse HTTP method/path\n");
    return false;
  }
  return true;
}

// Checks the Authorization header against the configured Basic Auth
// credentials, initializing them from LCARS_AUTH_USER/LCARS_AUTH_PASS (or
// the "admin"/"admin" default) on first call. Sends a 401 response and
// returns false if authentication fails.
static bool CheckHTTPAuth(int client_fd, const char *req_buf) {
  assert(client_fd >= 0);
  assert(req_buf != NULL);

  if (!g_auth_enabled) {
    const char *env_user = getenv("LCARS_AUTH_USER");
    const char *env_pass = getenv("LCARS_AUTH_PASS");
    if (env_user && env_pass) {
      strncpy(g_auth_user, env_user, sizeof(g_auth_user) - 1);
      g_auth_user[sizeof(g_auth_user) - 1] = '\0';
      strncpy(g_auth_pass, env_pass, sizeof(g_auth_pass) - 1);
      g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
    } else {
      strncpy(g_auth_user, "admin", sizeof(g_auth_user) - 1);
      g_auth_user[sizeof(g_auth_user) - 1] = '\0';
      strncpy(g_auth_pass, "admin", sizeof(g_auth_pass) - 1);
      g_auth_pass[sizeof(g_auth_pass) - 1] = '\0';
    }
    g_auth_enabled = true;
  }

  bool authenticated = false;
  const char *auth_val = find_header_value(req_buf, "Authorization:");
  if (auth_val) {
    char val_buf[512] = {0};
    size_t len = 0;
    while (auth_val[len] && auth_val[len] != '\r' && auth_val[len] != '\n' &&
           len < sizeof(val_buf) - 1) {
      val_buf[len] = auth_val[len];
      len++;
    }
    val_buf[len] = '\0';
    while (len > 0 && (val_buf[len - 1] == ' ' || val_buf[len - 1] == '\t')) {
      val_buf[--len] = '\0';
    }
    if (strncasecmp(val_buf, "Basic ", 6) == 0) {
      char decoded[512] = {0};
      base64_decode(val_buf + 6, decoded, sizeof(decoded));
      char *colon = strchr(decoded, ':');
      if (colon) {
        *colon = '\0';
        char *user = decoded;
        char *pass = colon + 1;
        if (strcmp(user, g_auth_user) == 0 && strcmp(pass, g_auth_pass) == 0) {
          authenticated = true;
        } else {
          printf("HTTP Auth Failure: Username or password mismatch for user "
                 "'%s'\n",
                 user);
        }
      } else {
        printf(
            "HTTP Auth Failure: Malformed credentials token (missing colon)\n");
      }
    } else {
      printf("HTTP Auth Failure: Unsupported auth method (expected Basic)\n");
    }
  } else {
    printf("HTTP Auth Failure: Missing Authorization header\n");
  }

  if (!authenticated) {
    // Not SendJSONError: this is the one response that also needs a
    // WWW-Authenticate header.
    static const char json[] = "{\"error\":\"Unauthorized\",\"status\":401}";
    char resp[512];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 401 Unauthorized\r\n"
                     "WWW-Authenticate: Basic realm=\"LCARS\"\r\n"
                     "Content-Type: application/json\r\n" HTTP_CORS_HEADERS
                     "Content-Length: %zu\r\n\r\n%s",
                     sizeof(json) - 1, json);
    assert(n > 0 && n < (int)sizeof(resp));
    send(client_fd, resp, (size_t)n, MSG_NOSIGNAL);
    return false;
  }
  return true;
}

// Parses Content-Length/Content-Type from req_buf's headers and reads the
// body (already-buffered bytes past the headers, plus whatever's still
// arriving) into arena. *out_body is left pointing at a static empty
// string if there's no body. Returns false after answering 413 if the
// client announced more than HTTP_MAX_BODY_BYTES.
static bool ReadHTTPRequestBody(int client_fd, Arena *arena,
                                const char *req_buf, const char *body_start,
                                int total_read, int headers_len,
                                char **out_body, char *out_content_type,
                                size_t content_type_size) {
  assert(client_fd >= 0);
  assert(arena != NULL);
  assert(req_buf != NULL && body_start != NULL);
  assert(out_body != NULL && out_content_type != NULL);
  assert(content_type_size > 0);
  assert(headers_len >= 0 && headers_len <= total_read);
  assert(body_start >= req_buf); // body_start points into req_buf

  const char *cl_val = find_header_value(req_buf, "Content-Length:");
  int content_len = cl_val ? atoi(cl_val) : 0;

  out_content_type[0] = '\0';
  const char *ct_val = find_header_value(req_buf, "Content-Type:");
  if (ct_val) {
    size_t len = 0;
    while (ct_val[len] && ct_val[len] != '\r' && ct_val[len] != '\n' &&
           ct_val[len] != ';' && len < content_type_size - 1) {
      out_content_type[len] = ct_val[len];
      len++;
    }
    out_content_type[len] = '\0';
    while (len > 0 && (out_content_type[len - 1] == ' ' ||
                       out_content_type[len - 1] == '\t')) {
      out_content_type[--len] = '\0';
    }
  }

  *out_body = "";
  // content_len is attacker-controlled (just the Content-Length header run
  // through atoi), so it is checked, never asserted: past this cap the
  // allocation below would exhaust the connection's 1MB arena and abort the
  // whole process, UI included.
  if (content_len > HTTP_MAX_BODY_BYTES) {
    printf("HTTP Request Rejected: Content-Length %d exceeds the %d byte "
           "limit\n",
           content_len, HTTP_MAX_BODY_BYTES);
    SendJSONError(client_fd, 413, "Request body exceeds %d bytes",
                  HTTP_MAX_BODY_BYTES);
    return false;
  }
  if (content_len > 0) {
    char *body = (char *)arena_alloc(arena, (size_t)content_len + 1);
    int body_already_read = total_read - headers_len;
    if (body_already_read > content_len) {
      body_already_read = content_len;
    }
    assert(body_already_read >= 0 && body_already_read <= content_len);
    if (body_already_read > 0) {
      memcpy(body, body_start, body_already_read);
    }
    int body_to_read = content_len - body_already_read;
    while (body_to_read > 0) {
      // Each recv writes at body + body_already_read for body_to_read
      // bytes; together they must stay inside the content_len allocation.
      assert(body_already_read + body_to_read == content_len);
      int n = recv(client_fd, body + body_already_read, body_to_read, 0);
      if (n <= 0)
        break;
      body_already_read += n;
      body_to_read -= n;
    }
    assert(body_already_read <= content_len);
    body[content_len] = '\0';
    *out_body = body;
  }

  assert(*out_body != NULL);
  return true;
}

// ---------------------------------------------------------------------------
// Database helpers
// ---------------------------------------------------------------------------

// Opens the server's own connection to lcars.db (the UI thread has its own).
// Answers 500 and returns false if that fails. The busy timeout matters now
// that the API writes: without it a write racing the UI's debounced save
// fails instantly with SQLITE_BUSY instead of waiting its turn.
static bool OpenHTTPDB(int client_fd, sqlite3 **out_db) {
  assert(client_fd >= 0);
  assert(out_db != NULL);

  sqlite3 *db = NULL;
  int rc = sqlite3_open(LCARS_DB_PATH, &db);
  if (rc != SQLITE_OK) {
    printf("HTTP Database Error: Failed to open database '" LCARS_DB_PATH
           "': %s\n",
           sqlite3_errstr(rc));
    if (db) {
      sqlite3_close(db);
    }
    SendJSONError(client_fd, 500, "Failed to open database");
    return false;
  }
  sqlite3_busy_timeout(db, 2000);
  *out_db = db;
  return true;
}

// The column list every entry-returning query selects, in the order
// AppendEntryJSON reads.
#define HTTP_ENTRY_COLUMNS                                                     \
  "id, kind, title, content, value_int, value_float, done_bool, deleted, "     \
  "created_at_utc, last_modified_at_utc, length(content)"

static void AppendEntryJSON(JSONBuf *b, sqlite3_stmt *stmt,
                            bool include_content) {
  assert(b != NULL);
  assert(stmt != NULL);

  const char *kind = (const char *)sqlite3_column_text(stmt, 1);
  const char *title = (const char *)sqlite3_column_text(stmt, 2);
  const char *content = (const char *)sqlite3_column_text(stmt, 3);
  const char *created_at = (const char *)sqlite3_column_text(stmt, 8);
  const char *last_modified = (const char *)sqlite3_column_text(stmt, 9);

  jsonbuf_appendf(b, "{\"id\":%d,\"kind\":", sqlite3_column_int(stmt, 0));
  jsonbuf_append_json_string(b, kind);
  jsonbuf_append(b, ",\"title\":");
  jsonbuf_append_json_string(b, title);
  if (include_content) {
    jsonbuf_append(b, ",\"content\":");
    jsonbuf_append_json_string(b, content);
  }
  jsonbuf_appendf(b,
                  ",\"content_length\":%d,\"value_int\":%d,\"value_float\":%f,"
                  "\"done_bool\":%d,\"deleted\":%d,\"created_at_utc\":",
                  sqlite3_column_int(stmt, 10), sqlite3_column_int(stmt, 4),
                  sqlite3_column_double(stmt, 5), sqlite3_column_int(stmt, 6),
                  sqlite3_column_int(stmt, 7));
  jsonbuf_append_json_string(b, created_at);
  jsonbuf_append(b, ",\"last_modified_at_utc\":");
  jsonbuf_append_json_string(b, last_modified);
  jsonbuf_append(b, "}");
}

// A WHERE clause built from query parameters plus the values to bind into
// it, in order. Nothing the client sends is ever pasted into the SQL text -
// the clauses are fixed literals and the values are always bound.
#define HTTP_MAX_BINDS 12

typedef enum SQLBindKind {
  SQL_BIND_INT,
  SQL_BIND_REAL,
  SQL_BIND_TEXT,     // copied into the bind slot (short values: kind, dates, …)
  SQL_BIND_TEXT_PTR, // borrowed (entry content, which has no useful maximum)
} SQLBindKind;

typedef struct SQLBind {
  SQLBindKind kind;
  int int_val;
  double real_val;
  const char *text_ptr;
  char text_val[512];
} SQLBind;

typedef struct SQLFilter {
  char where[1024];
  size_t where_len;
  SQLBind binds[HTTP_MAX_BINDS];
  int bind_count;
} SQLFilter;

static void filter_init(SQLFilter *f) {
  assert(f != NULL);
  memset(f, 0, sizeof(*f));
  // "1=1" so every added clause can start with " AND " unconditionally.
  f->where_len = (size_t)snprintf(f->where, sizeof(f->where), "WHERE 1=1");
  assert(f->where_len < sizeof(f->where));
}

static void filter_where(SQLFilter *f, const char *clause) {
  assert(f != NULL);
  assert(clause != NULL);
  int n = snprintf(f->where + f->where_len, sizeof(f->where) - f->where_len,
                   " AND %s", clause);
  // The clauses are all compile-time literals from this file; overflowing
  // the buffer would mean silently dropping a filter (returning rows the
  // client asked to exclude), so it is a programmer error, not input error.
  assert(n > 0 && (size_t)n < sizeof(f->where) - f->where_len);
  f->where_len += (size_t)n;
}

static void filter_push_text(SQLFilter *f, const char *value) {
  assert(f != NULL);
  assert(value != NULL);
  assert(f->bind_count < HTTP_MAX_BINDS); // one push per '?' in the clauses
  SQLBind *b = &f->binds[f->bind_count++];
  b->kind = SQL_BIND_TEXT;
  strncpy(b->text_val, value, sizeof(b->text_val) - 1);
  b->text_val[sizeof(b->text_val) - 1] = '\0';
}

// For values with no sensible fixed maximum (entry content). The pointer is
// borrowed: it must stay alive until filter_bind() runs, which it does -
// everything it is used with lives in the connection arena.
static void filter_push_text_ptr(SQLFilter *f, const char *value) {
  assert(f != NULL);
  assert(value != NULL);
  assert(f->bind_count < HTTP_MAX_BINDS);
  SQLBind *b = &f->binds[f->bind_count++];
  b->kind = SQL_BIND_TEXT_PTR;
  b->text_ptr = value;
}

static void filter_push_int(SQLFilter *f, int value) {
  assert(f != NULL);
  assert(f->bind_count < HTTP_MAX_BINDS);
  SQLBind *b = &f->binds[f->bind_count++];
  b->kind = SQL_BIND_INT;
  b->int_val = value;
}

static void filter_push_real(SQLFilter *f, double value) {
  assert(f != NULL);
  assert(f->bind_count < HTTP_MAX_BINDS);
  SQLBind *b = &f->binds[f->bind_count++];
  b->kind = SQL_BIND_REAL;
  b->real_val = value;
}

// Binds the collected values as parameters 1..bind_count. Returns the next
// free parameter index so the caller can bind LIMIT/OFFSET (or the row id)
// after them.
static int filter_bind(sqlite3_stmt *stmt, const SQLFilter *f) {
  assert(stmt != NULL);
  assert(f != NULL);
  for (int i = 0; i < f->bind_count; i++) {
    const SQLBind *b = &f->binds[i];
    switch (b->kind) {
    case SQL_BIND_INT:
      sqlite3_bind_int(stmt, i + 1, b->int_val);
      break;
    case SQL_BIND_REAL:
      sqlite3_bind_double(stmt, i + 1, b->real_val);
      break;
    case SQL_BIND_TEXT:
      sqlite3_bind_text(stmt, i + 1, b->text_val, -1, SQLITE_TRANSIENT);
      break;
    case SQL_BIND_TEXT_PTR:
      sqlite3_bind_text(stmt, i + 1, b->text_ptr, -1, SQLITE_TRANSIENT);
      break;
    default:
      assert(!"unreachable: unknown SQL bind kind");
      break;
    }
  }
  return f->bind_count + 1;
}

// Accepts "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" (the shape stored in
// created_at_utc / last_modified_at_utc, which compares correctly as text).
// A bare date used as an upper bound is widened to the end of that day so
// `until=2026-08-05` includes everything written that day.
static bool NormalizeTimestamp(const char *in, bool upper_bound, char *out,
                               size_t out_size) {
  assert(in != NULL);
  assert(out != NULL);
  assert(out_size > HTTP_MAX_TIMESTAMP_LEN);

  size_t len = strlen(in);
  if (len != 10 && len != HTTP_MAX_TIMESTAMP_LEN) {
    return false;
  }
  for (size_t i = 0; i < len; i++) {
    char c = in[i];
    bool ok = (c >= '0' && c <= '9') || c == '-' || c == ':' || c == ' ';
    if (!ok) {
      return false;
    }
  }
  if (len == 10 && upper_bound) {
    snprintf(out, out_size, "%s 23:59:59", in);
  } else {
    snprintf(out, out_size, "%s", in);
  }
  return true;
}

// Escapes the LIKE wildcards in a user-supplied search term so a `%` in the
// query means a literal percent sign instead of "match anything", and wraps
// it in %…% for a contains-search. Pairs with `ESCAPE '\'` in the clause.
static void BuildLikePattern(const char *term, char *out, size_t out_size) {
  assert(term != NULL);
  assert(out != NULL);
  assert(out_size > 3);

  size_t o = 0;
  out[o++] = '%';
  for (const char *p = term; *p && o + 2 < out_size - 1; p++) {
    if (*p == '%' || *p == '_' || *p == '\\') {
      out[o++] = '\\';
    }
    out[o++] = *p;
  }
  out[o++] = '%';
  assert(o < out_size);
  out[o] = '\0';
}

// Translates the query string into a WHERE clause. Returns false with a
// message in `err` for anything malformed - a filter the server cannot
// honour must be a 400, not silently ignored (that would answer with rows
// the client explicitly excluded).
static bool BuildEntryFilter(const char *query, SQLFilter *f, char *err,
                             size_t err_size) {
  assert(query != NULL);
  assert(f != NULL);
  assert(err != NULL && err_size > 0);

  filter_init(f);

  char buf[512];
  bool ok = true;

  // deleted: excluded by default (matching what the UI shows), `deleted=1`
  // for only the soft-deleted ones, `deleted=all` for everything.
  if (query_get(query, "deleted", buf, sizeof(buf))) {
    if (strcasecmp(buf, "all") == 0 || strcasecmp(buf, "any") == 0) {
      // no clause
    } else if (buf[0] == '\0' || strcasecmp(buf, "1") == 0 ||
               strcasecmp(buf, "true") == 0) {
      filter_where(f, "deleted = 1");
    } else if (strcasecmp(buf, "0") == 0 || strcasecmp(buf, "false") == 0) {
      filter_where(f, "(deleted IS NULL OR deleted = 0)");
    } else {
      snprintf(err, err_size, "Invalid 'deleted' value '%s' (0, 1 or all)",
               buf);
      return false;
    }
  } else {
    filter_where(f, "(deleted IS NULL OR deleted = 0)");
  }

  if (query_get(query, "kind", buf, sizeof(buf))) {
    filter_where(f, "kind = ?");
    filter_push_text(f, buf);
  }

  if (query_get(query, "q", buf, sizeof(buf)) && buf[0] != '\0') {
    char pattern[512];
    BuildLikePattern(buf, pattern, sizeof(pattern));
    filter_where(f, "(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')");
    filter_push_text(f, pattern);
    filter_push_text(f, pattern);
  }

  // date=YYYY-MM-DD is shorthand for since+until on the same day.
  char stamp[64];
  if (query_get(query, "date", buf, sizeof(buf))) {
    if (!NormalizeTimestamp(buf, false, stamp, sizeof(stamp))) {
      snprintf(err, err_size, "Invalid 'date' value '%s' (YYYY-MM-DD)", buf);
      return false;
    }
    filter_where(f, "created_at_utc >= ?");
    filter_push_text(f, stamp);
    if (!NormalizeTimestamp(buf, true, stamp, sizeof(stamp))) {
      snprintf(err, err_size, "Invalid 'date' value '%s' (YYYY-MM-DD)", buf);
      return false;
    }
    filter_where(f, "created_at_utc <= ?");
    filter_push_text(f, stamp);
  }

  struct {
    const char *param;
    const char *clause;
    bool upper_bound;
  } ranges[] = {
      {"since", "created_at_utc >= ?", false},
      {"until", "created_at_utc <= ?", true},
      {"modified_since", "last_modified_at_utc >= ?", false},
      {"modified_until", "last_modified_at_utc <= ?", true},
  };
  for (size_t i = 0; i < sizeof(ranges) / sizeof(ranges[0]); i++) {
    if (!query_get(query, ranges[i].param, buf, sizeof(buf))) {
      continue;
    }
    if (!NormalizeTimestamp(buf, ranges[i].upper_bound, stamp, sizeof(stamp))) {
      snprintf(err, err_size,
               "Invalid '%s' value '%s' (YYYY-MM-DD or "
               "'YYYY-MM-DD HH:MM:SS')",
               ranges[i].param, buf);
      return false;
    }
    filter_where(f, ranges[i].clause);
    filter_push_text(f, stamp);
  }

  bool flag = false;
  if (query_get_bool(query, "done", &flag, &ok)) {
    filter_where(f, "COALESCE(done_bool, 0) = ?");
    filter_push_int(f, flag ? 1 : 0);
  } else if (!ok) {
    snprintf(err, err_size, "Invalid 'done' value (0 or 1)");
    return false;
  }

  int id_bound = 0;
  if (query_get_int(query, "min_id", &id_bound, &ok)) {
    filter_where(f, "id >= ?");
    filter_push_int(f, id_bound);
  } else if (!ok) {
    snprintf(err, err_size, "Invalid 'min_id' value (integer)");
    return false;
  }
  if (query_get_int(query, "max_id", &id_bound, &ok)) {
    filter_where(f, "id <= ?");
    filter_push_int(f, id_bound);
  } else if (!ok) {
    snprintf(err, err_size, "Invalid 'max_id' value (integer)");
    return false;
  }

  assert(f->bind_count <= HTTP_MAX_BINDS);
  return true;
}

// Maps `order`/`dir` onto a fixed ORDER BY string. Client text is matched
// against this table, never interpolated: an ORDER BY is the one part of
// these queries that cannot be a bound parameter.
static bool ResolveOrderBy(const char *query, char *out_order_by,
                           size_t out_size, char *err, size_t err_size) {
  assert(query != NULL);
  assert(out_order_by != NULL && out_size > 0);
  assert(err != NULL && err_size > 0);

  static const struct {
    const char *name;
    const char *column;
  } columns[] = {
      {"id", "id"},
      {"created", "created_at_utc"},
      {"created_at_utc", "created_at_utc"},
      {"modified", "last_modified_at_utc"},
      {"last_modified_at_utc", "last_modified_at_utc"},
      {"title", "title"},
      {"kind", "kind"},
  };

  const char *column = "id";
  char buf[64];
  if (query_get(query, "order", buf, sizeof(buf)) && buf[0] != '\0') {
    const char *match = NULL;
    for (size_t i = 0; i < sizeof(columns) / sizeof(columns[0]); i++) {
      if (strcasecmp(buf, columns[i].name) == 0) {
        match = columns[i].column;
        break;
      }
    }
    if (!match) {
      snprintf(err, err_size,
               "Invalid 'order' value '%s' (id, created, modified, title, "
               "kind)",
               buf);
      return false;
    }
    column = match;
  }

  bool ascending = false;
  if (query_get(query, "dir", buf, sizeof(buf)) && buf[0] != '\0') {
    if (strcasecmp(buf, "asc") == 0) {
      ascending = true;
    } else if (strcasecmp(buf, "desc") == 0) {
      ascending = false;
    } else {
      snprintf(err, err_size, "Invalid 'dir' value '%s' (asc or desc)", buf);
      return false;
    }
  }

  // The secondary sort on id keeps paging stable when the primary column
  // ties (several entries created in the same second, say).
  int n = snprintf(out_order_by, out_size, "ORDER BY %s %s, id %s", column,
                   ascending ? "ASC" : "DESC", ascending ? "ASC" : "DESC");
  assert(n > 0 && (size_t)n < out_size);
  return true;
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

// GET /entries - the filtered list. Every parameter is optional; see the
// route index in HandleIndex for the full set.
static int HandleGetEntries(int client_fd, Arena *arena, const char *query) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL);

  SQLFilter filter;
  char err[256];
  if (!BuildEntryFilter(query, &filter, err, sizeof(err))) {
    return SendJSONError(client_fd, 400, "%s", err);
  }
  char order_by[128];
  if (!ResolveOrderBy(query, order_by, sizeof(order_by), err, sizeof(err))) {
    return SendJSONError(client_fd, 400, "%s", err);
  }

  bool ok = true;
  int limit = HTTP_DEFAULT_LIMIT;
  if (query_get_int(query, "limit", &limit, &ok)) {
    if (limit <= 0 || limit > HTTP_MAX_LIMIT) {
      return SendJSONError(client_fd, 400, "Invalid 'limit' (1..%d)",
                           HTTP_MAX_LIMIT);
    }
  } else if (!ok) {
    return SendJSONError(client_fd, 400, "Invalid 'limit' (1..%d)",
                         HTTP_MAX_LIMIT);
  }
  int offset = 0;
  if (query_get_int(query, "offset", &offset, &ok)) {
    if (offset < 0) {
      return SendJSONError(client_fd, 400, "Invalid 'offset' (>= 0)");
    }
  } else if (!ok) {
    return SendJSONError(client_fd, 400, "Invalid 'offset' (>= 0)");
  }
  bool include_content = true;
  if (!query_get_bool(query, "content", &include_content, &ok) && !ok) {
    return SendJSONError(client_fd, 400, "Invalid 'content' value (0 or 1)");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  char sql[2048];
  snprintf(sql, sizeof(sql),
           "SELECT " HTTP_ENTRY_COLUMNS " FROM entries %s %s LIMIT ? OFFSET ?;",
           filter.where, order_by);

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    printf("HTTP Database Error: Failed to prepare SELECT query: %s\n",
           sqlite3_errmsg(db));
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  int next_param = filter_bind(stmt, &filter);
  sqlite3_bind_int(stmt, next_param++, limit);
  sqlite3_bind_int(stmt, next_param, offset);

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "[");
  bool first = true;
  while (sqlite3_step(stmt) == SQLITE_ROW && !out.overflow) {
    if (!first) {
      jsonbuf_append(&out, ",");
    }
    first = false;
    AppendEntryJSON(&out, stmt, include_content);
  }
  jsonbuf_append(&out, "]");

  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return SendJSONBuf(client_fd, &out);
}

// GET /entries/<id> - one entry, including soft-deleted ones (a client that
// addressed a specific id wants to know it is there and deleted, not a 404).
static int HandleGetEntry(int client_fd, Arena *arena, int id) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(id > 0);

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db, "SELECT " HTTP_ENTRY_COLUMNS " FROM entries WHERE id = ?1;", -1,
      &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_int(stmt, 1, id);

  int status;
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    JSONBuf out;
    jsonbuf_init(&out, arena);
    AppendEntryJSON(&out, stmt, true);
    status = SendJSONBuf(client_fd, &out);
  } else {
    status = SendJSONError(client_fd, 404, "No entry with id %d", id);
  }
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return status;
}

// POST /entries - create. JSON body (kind, title, content, value_int,
// value_float, done_bool) or a plain-text body, which becomes the content.
static int HandlePostEntry(int client_fd, Arena *arena, const char *body,
                           const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  // Both are strstr'd/strncpy'd unconditionally below;
  // ReadHTTPRequestBody() guarantees a non-NULL body even with no content.
  assert(body != NULL);
  assert(content_type != NULL);

  bool is_json = (strstr(content_type, "application/json") != NULL);

  char kind[128] = {0};
  char title[512] = {0};
  const char *content = "";
  char *parsed_content = NULL;
  int value_int = 0;
  float value_float = 0.0f;
  int done_bool = 0;

  if (is_json) {
    json_get_string(body, "kind", kind, sizeof(kind));
    json_get_string(body, "title", title, sizeof(title));
    // Arena-backed: entry content is a journal entry, and a fixed buffer
    // would silently drop the tail of anything longer.
    if (json_get_string_arena(arena, body, "content", &parsed_content)) {
      content = parsed_content;
    }
    json_get_int(body, "value_int", &value_int);
    json_get_float(body, "value_float", &value_float);
    json_get_int(body, "done_bool", &done_bool);
  } else {
    content = body;
    strcpy(title, "HTTP Text Entry");
  }

  if (title[0] == '\0') {
    strcpy(title, "HTTP Entry");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  sqlite3_stmt *stmt;
  const char *sql = "INSERT INTO entries (kind, title, content, value_int, "
                    "value_float, done_bool) VALUES (?, ?, ?, ?, ?, ?);";
  int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
  int status_code;
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, content, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 4, value_int);
    sqlite3_bind_double(stmt, 5, value_float);
    sqlite3_bind_int(stmt, 6, done_bool);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_DONE) {
      sqlite3_int64 insert_id = sqlite3_last_insert_rowid(db);
      char resp_body[256];
      int resp_len = snprintf(resp_body, sizeof(resp_body),
                              "{\"status\":\"success\",\"id\":%lld}",
                              (long long)insert_id);
      assert(resp_len > 0 && resp_len < (int)sizeof(resp_body));
      status_code = SendJSON(client_fd, 200, resp_body, (size_t)resp_len);
    } else {
      printf("HTTP Database Error: Query execution failed: %s\n",
             sqlite3_errmsg(db));
      status_code = SendJSONError(client_fd, 400, "Execution failed: %s",
                                  sqlite3_errmsg(db));
    }
    sqlite3_finalize(stmt);
  } else {
    printf("HTTP Database Error: Failed to prepare INSERT query: %s\n",
           sqlite3_errmsg(db));
    status_code = SendJSONError(client_fd, 500, "Preparation failed: %s",
                                sqlite3_errmsg(db));
  }
  sqlite3_close(db);
  assert(status_code == 200 || status_code == 400 || status_code == 500);
  return status_code;
}

// PUT/PATCH /entries/<id> - update whichever of kind, title, content,
// value_int, value_float, done_bool, deleted the body mentions. Both verbs
// behave the same (partial update): a PUT that only carries `content` must
// not blank the title, which is the only sane behaviour for a journal.
// Setting `"deleted": 0` is how a soft-deleted entry is restored.
static int HandleUpdateEntry(int client_fd, Arena *arena, int id,
                             const char *body, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(id > 0);
  assert(body != NULL);
  assert(content_type != NULL);

  bool is_json = (strstr(content_type, "application/json") != NULL);

  // Column names in the SET list are fixed literals; every value is bound,
  // in the order it is pushed here.
  char set_clause[512] = {0};
  size_t set_len = 0;
  SQLFilter values; // reused purely as an ordered bind list
  filter_init(&values);

  // Appends "col = ?" to the SET list, with the separator only from the
  // second field on.
#define ADD_SET_COLUMN(col)                                                    \
  do {                                                                         \
    int n = snprintf(set_clause + set_len, sizeof(set_clause) - set_len,       \
                     "%s%s = ?", set_len > 0 ? ", " : "", (col));              \
    assert(n > 0 && (size_t)n < sizeof(set_clause) - set_len);                 \
    set_len += (size_t)n;                                                      \
  } while (0)

  char kind[128] = {0};
  char title[512] = {0};
  char *content = NULL;
  int value_int = 0, done_bool = 0, deleted = 0;
  float value_float = 0.0f;

  if (is_json) {
    if (json_get_string(body, "kind", kind, sizeof(kind))) {
      ADD_SET_COLUMN("kind");
      filter_push_text(&values, kind);
    }
    if (json_get_string(body, "title", title, sizeof(title))) {
      ADD_SET_COLUMN("title");
      filter_push_text(&values, title);
    }
    if (json_get_string_arena(arena, body, "content", &content)) {
      ADD_SET_COLUMN("content");
      // Borrowed, not copied: an entry body does not fit a bind slot.
      filter_push_text_ptr(&values, content);
    }
    if (json_get_int(body, "value_int", &value_int)) {
      ADD_SET_COLUMN("value_int");
      filter_push_int(&values, value_int);
    }
    if (json_get_float(body, "value_float", &value_float)) {
      ADD_SET_COLUMN("value_float");
      filter_push_real(&values, (double)value_float);
    }
    if (json_get_int(body, "done_bool", &done_bool)) {
      ADD_SET_COLUMN("done_bool");
      filter_push_int(&values, done_bool ? 1 : 0);
    }
    if (json_get_int(body, "deleted", &deleted)) {
      ADD_SET_COLUMN("deleted");
      filter_push_int(&values, deleted ? 1 : 0);
    }
  } else if (body[0] != '\0') {
    // A plain-text body is the new content, matching POST's behaviour.
    ADD_SET_COLUMN("content");
    filter_push_text_ptr(&values, body);
  }
#undef ADD_SET_COLUMN

  if (set_len == 0) {
    return SendJSONError(client_fd, 400,
                         "No updatable fields in body (kind, title, content, "
                         "value_int, value_float, done_bool, deleted)");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  char sql[1024];
  snprintf(sql, sizeof(sql),
           "UPDATE entries SET %s, last_modified_at_utc = "
           "strftime('%%Y-%%m-%%d %%H:%%M:%%S', 'now', 'utc') WHERE id = ?%d;",
           set_clause, values.bind_count + 1);

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare update: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  int next_param = filter_bind(stmt, &values);
  sqlite3_bind_int(stmt, next_param, id);

  int status;
  rc = sqlite3_step(stmt);
  if (rc != SQLITE_DONE) {
    printf("HTTP Database Error: Update failed: %s\n", sqlite3_errmsg(db));
    status =
        SendJSONError(client_fd, 400, "Update failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_changes(db) == 0) {
    status = SendJSONError(client_fd, 404, "No entry with id %d", id);
  } else {
    char resp_body[128];
    int resp_len = snprintf(resp_body, sizeof(resp_body),
                            "{\"status\":\"success\",\"id\":%d,\"updated\":%d}",
                            id, sqlite3_changes(db));
    assert(resp_len > 0 && resp_len < (int)sizeof(resp_body));
    status = SendJSON(client_fd, 200, resp_body, (size_t)resp_len);
  }
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return status;
}

// DELETE /entries/<id> - soft delete (deleted = 1), the same thing the UI
// does. There is deliberately no hard-delete route: this database is a
// personal journal, and `deleted = 0` via PUT is the undo.
static int HandleDeleteEntry(int client_fd, int id) {
  assert(client_fd >= 0);
  assert(id > 0);

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db,
      "UPDATE entries SET deleted = 1, last_modified_at_utc = "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?1 AND "
      "(deleted IS NULL OR deleted = 0);",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare delete: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_int(stmt, 1, id);

  int status;
  rc = sqlite3_step(stmt);
  if (rc != SQLITE_DONE) {
    status =
        SendJSONError(client_fd, 400, "Delete failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_changes(db) == 0) {
    // Either no such row, or it was already deleted - both are "nothing to
    // do", and the client can tell which with GET /entries/<id>.
    status = SendJSONError(client_fd, 404,
                           "No live entry with id %d (already deleted?)", id);
  } else {
    char resp_body[128];
    int resp_len = snprintf(resp_body, sizeof(resp_body),
                            "{\"status\":\"deleted\",\"id\":%d}", id);
    assert(resp_len > 0 && resp_len < (int)sizeof(resp_body));
    status = SendJSON(client_fd, 200, resp_body, (size_t)resp_len);
  }
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return status;
}

// GET /kinds - the distinct kinds with per-kind counts and the newest
// timestamp in each. This is what the UI's kind selector shows, and what a
// client needs before it can filter by kind.
static int HandleGetKinds(int client_fd, Arena *arena, const char *query) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL);

  bool ok = true;
  bool include_deleted = false;
  if (!query_get_bool(query, "deleted", &include_deleted, &ok) && !ok) {
    return SendJSONError(client_fd, 400, "Invalid 'deleted' value (0 or 1)");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  const char *sql =
      include_deleted
          ? "SELECT kind, COUNT(*), MAX(last_modified_at_utc) FROM entries "
            "GROUP BY kind ORDER BY kind ASC;"
          : "SELECT kind, COUNT(*), MAX(last_modified_at_utc) FROM entries "
            "WHERE deleted IS NULL OR deleted = 0 GROUP BY kind ORDER BY kind "
            "ASC;";
  sqlite3_stmt *stmt;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "[");
  bool first = true;
  while (sqlite3_step(stmt) == SQLITE_ROW && !out.overflow) {
    if (!first) {
      jsonbuf_append(&out, ",");
    }
    first = false;
    jsonbuf_append(&out, "{\"kind\":");
    jsonbuf_append_json_string(&out,
                               (const char *)sqlite3_column_text(stmt, 0));
    jsonbuf_appendf(&out, ",\"count\":%d,\"last_modified_at_utc\":",
                    sqlite3_column_int(stmt, 1));
    jsonbuf_append_json_string(&out,
                               (const char *)sqlite3_column_text(stmt, 2));
    jsonbuf_append(&out, "}");
  }
  jsonbuf_append(&out, "]");

  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return SendJSONBuf(client_fd, &out);
}

// GET /stats - totals over the whole journal. Cheap to compute, and it is
// what makes pagination usable (how many entries are there to page through)
// without a count on every list response.
static int HandleGetStats(int client_fd, Arena *arena, const char *query) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL);

  SQLFilter filter;
  char err[256];
  if (!BuildEntryFilter(query, &filter, err, sizeof(err))) {
    return SendJSONError(client_fd, 400, "%s", err);
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  char sql[2048];
  snprintf(sql, sizeof(sql),
           "SELECT COUNT(*), COUNT(DISTINCT kind), "
           "SUM(CASE WHEN COALESCE(done_bool,0) = 1 THEN 1 ELSE 0 END), "
           "SUM(COALESCE(length(content), 0)), MIN(created_at_utc), "
           "MAX(created_at_utc), MAX(last_modified_at_utc) FROM entries %s;",
           filter.where);

  sqlite3_stmt *stmt;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  filter_bind(stmt, &filter);

  JSONBuf out;
  jsonbuf_init(&out, arena);
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    jsonbuf_appendf(&out,
                    "{\"count\":%d,\"kinds\":%d,\"done\":%d,"
                    "\"content_bytes\":%lld,\"oldest_created_at_utc\":",
                    sqlite3_column_int(stmt, 0), sqlite3_column_int(stmt, 1),
                    sqlite3_column_int(stmt, 2),
                    (long long)sqlite3_column_int64(stmt, 3));
    jsonbuf_append_json_string(&out,
                               (const char *)sqlite3_column_text(stmt, 4));
    jsonbuf_append(&out, ",\"newest_created_at_utc\":");
    jsonbuf_append_json_string(&out,
                               (const char *)sqlite3_column_text(stmt, 5));
    jsonbuf_append(&out, ",\"last_modified_at_utc\":");
    jsonbuf_append_json_string(&out,
                               (const char *)sqlite3_column_text(stmt, 6));
    jsonbuf_append(&out, "}");
  } else {
    jsonbuf_append(&out, "{\"count\":0,\"kinds\":0,\"done\":0,"
                         "\"content_bytes\":0}");
  }

  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return SendJSONBuf(client_fd, &out);
}

// GET / - the route index. Self-documenting so a client (or a future me
// with a terminal) can discover the filters without reading this file.
static int HandleIndex(int client_fd) {
  assert(client_fd >= 0);

  static const char body[] =
      "{\"service\":\"lcars\",\"routes\":["
      "{\"method\":\"GET\",\"path\":\"/health\",\"auth\":false,"
      "\"description\":\"liveness probe\"},"
      "{\"method\":\"GET\",\"path\":\"/entries\","
      "\"description\":\"list entries\","
      "\"params\":[\"kind\",\"q\",\"date\",\"since\",\"until\","
      "\"modified_since\",\"modified_until\",\"done\",\"deleted\",\"min_id\","
      "\"max_id\",\"order\",\"dir\",\"limit\",\"offset\",\"content\"]},"
      "{\"method\":\"POST\",\"path\":\"/entries\","
      "\"description\":\"create entry (kind,title,content,value_int,"
      "value_float,done_bool)\"},"
      "{\"method\":\"GET\",\"path\":\"/entries/{id}\","
      "\"description\":\"one entry\"},"
      "{\"method\":\"PUT|PATCH\",\"path\":\"/entries/{id}\","
      "\"description\":\"partial update; deleted=0 restores\"},"
      "{\"method\":\"DELETE\",\"path\":\"/entries/{id}\","
      "\"description\":\"soft delete\"},"
      "{\"method\":\"GET\",\"path\":\"/kinds\","
      "\"description\":\"distinct kinds with counts\"},"
      "{\"method\":\"GET\",\"path\":\"/stats\","
      "\"description\":\"totals, accepts the same filters as /entries\"}"
      "]}";
  return SendJSON(client_fd, 200, body, sizeof(body) - 1);
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

// Matches "/entries/<id>" (with an optional trailing slash) and extracts the
// id. Rejects anything non-numeric rather than letting atoi read it as 0.
static bool MatchEntryIdPath(const char *path, int *out_id) {
  assert(path != NULL);
  assert(out_id != NULL);

  const char *prefix = "/entries/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *id_str = path + prefix_len;
  if (*id_str == '\0') {
    return false;
  }
  char *end;
  long value = strtol(id_str, &end, 10);
  if (end == id_str) {
    return false;
  }
  if (*end == '/' && end[1] == '\0') {
    end++;
  }
  if (*end != '\0' || value <= 0 || value > INT_MAX) {
    return false;
  }
  *out_id = (int)value;
  return true;
}

static bool PathIs(const char *path, const char *route) {
  assert(path != NULL);
  assert(route != NULL);
  if (strcmp(path, route) == 0) {
    return true;
  }
  // Tolerate one trailing slash: "/entries/" is "/entries".
  size_t len = strlen(route);
  return strncmp(path, route, len) == 0 && path[len] == '/' &&
         path[len + 1] == '\0';
}

static void HandleHTTPConnection(int client_fd) {
  assert(client_fd >= 0);

  // Allocate 1 MB memory arena on the thread stack.
  // Extremely fast, safe, and avoids malloc fragmentation or memory leaks.
  uint8_t arena_backing[1024 * 1024];
  Arena arena;
  arena_init(&arena, arena_backing, sizeof(arena_backing));

  char req_buf[8192];
  double req_start = GetTimeSeconds();

  int total_read;
  char *body_start;
  int headers_len;
  HTTPRequestLine req_line;
  if (!ReadHTTPRequestLine(client_fd, req_buf, sizeof(req_buf), &total_read,
                           &body_start, &headers_len, &req_line)) {
    close(client_fd);
    return;
  }
  double req_recv = GetTimeSeconds();

  // Split "/entries?kind=task" into path and query string in place.
  char *path = req_line.path;
  char *query = strchr(path, '?');
  if (query) {
    *query = '\0';
    query++;
  } else {
    query = "";
  }
  const char *method = req_line.method;

  printf("HTTP Request: %s %s%s%s\n", method, path, query[0] ? "?" : "", query);
  int status_code = 0;

  // Handle OPTIONS request for CORS preflight
  if (strcmp(method, "OPTIONS") == 0) {
    const char *resp = "HTTP/1.1 204 No Content\r\n" HTTP_CORS_HEADERS
                       "Content-Length: 0\r\n\r\n";
    send(client_fd, resp, strlen(resp), MSG_NOSIGNAL);
    status_code = 204;
    goto end;
  }

  // Liveness probe, deliberately before the auth check: it exposes nothing
  // about the journal and monitoring shouldn't need credentials.
  if (PathIs(path, "/health") && strcmp(method, "GET") == 0) {
    static const char health[] = "{\"status\":\"ok\"}";
    status_code = SendJSON(client_fd, 200, health, sizeof(health) - 1);
    goto end;
  }

  if (!CheckHTTPAuth(client_fd, req_buf)) {
    status_code = 401;
    goto end;
  }

  char *body;
  char content_type[128];
  if (!ReadHTTPRequestBody(client_fd, &arena, req_buf, body_start, total_read,
                           headers_len, &body, content_type,
                           sizeof(content_type))) {
    status_code = 413;
    goto end;
  }

  // Router
  int entry_id = 0;
  if (PathIs(path, "/") || PathIs(path, "")) {
    status_code = strcmp(method, "GET") == 0
                      ? HandleIndex(client_fd)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /", method);
  } else if (PathIs(path, "/entries")) {
    if (strcmp(method, "GET") == 0) {
      status_code = HandleGetEntries(client_fd, &arena, query);
    } else if (strcmp(method, "POST") == 0) {
      status_code = HandlePostEntry(client_fd, &arena, body, content_type);
    } else {
      status_code = SendJSONError(client_fd, 405,
                                  "Method %s not allowed on /entries", method);
    }
  } else if (MatchEntryIdPath(path, &entry_id)) {
    if (strcmp(method, "GET") == 0) {
      status_code = HandleGetEntry(client_fd, &arena, entry_id);
    } else if (strcmp(method, "PUT") == 0 || strcmp(method, "PATCH") == 0) {
      status_code =
          HandleUpdateEntry(client_fd, &arena, entry_id, body, content_type);
    } else if (strcmp(method, "DELETE") == 0) {
      status_code = HandleDeleteEntry(client_fd, entry_id);
    } else {
      status_code = SendJSONError(
          client_fd, 405, "Method %s not allowed on /entries/<id>", method);
    }
  } else if (PathIs(path, "/kinds")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleGetKinds(client_fd, &arena, query)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /kinds",
                            method);
  } else if (PathIs(path, "/stats")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleGetStats(client_fd, &arena, query)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /stats",
                            method);
  } else {
    status_code =
        SendJSONError(client_fd, 404, "No route for %s %s", method, path);
  }

end: {
  double req_end = GetTimeSeconds();
  if (status_code != 0) {
    printf("HTTP Reply: %d (rcv %8.2f ms, proc %8.2f ms)\n", status_code,
           (req_recv - req_start) * 1000.0, (req_end - req_start) * 1000.0);
  }
  close(client_fd);
}
}

void RunHTTPServer(int port) {
  assert(port > 0 && port <= 65535);

  int server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
    perror("Failed to create HTTP socket");
    return;
  }

  int opt = 1;
  if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
    perror("setsockopt SO_REUSEADDR failed");
    close(server_fd);
    return;
  }

  struct sockaddr_in address;
  memset(&address, 0, sizeof(address));
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = INADDR_ANY;
  address.sin_port = htons(port);

  if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
    perror("HTTP bind failed");
    close(server_fd);
    return;
  }

  if (listen(server_fd, 10) < 0) {
    perror("HTTP listen failed");
    close(server_fd);
    return;
  }

  printf("HTTP Server running on port %d...\n", port);

  while (1) {
    int client_fd = accept(server_fd, NULL, NULL);
    if (client_fd >= 0) {
      HandleHTTPConnection(client_fd);
    }
  }

  close(server_fd);
}

static void *HTTPServerThread(void *arg) {
  int port = *(int *)arg;
  free(arg);
  RunHTTPServer(port);
  return NULL;
}

void StartHTTPServer(int port) {
  // Validated where it is parsed (lcars.c); by here it is an internal
  // contract with RunHTTPServer on the new thread.
  assert(port > 0 && port <= 65535);

  int *arg = malloc(sizeof(int));
  if (arg) {
    *arg = port;
    pthread_t thread;
    pthread_create(&thread, NULL, HTTPServerThread, arg);
    pthread_detach(thread);
  }
}

#endif // LCARS_HTTP_IMPLEMENTATION
#endif // LCARS_HTTP_H
