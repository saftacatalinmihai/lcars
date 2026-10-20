#ifndef LCARS_HTTP_H
#define LCARS_HTTP_H

// Runs the HTTP server on the specified port, blocking the current thread.
void RunHTTPServer(int port);
// Configures Basic Auth credentials.
void SetHTTPServerCredentials(const char *username, const char *password);

#ifdef LCARS_HTTP_IMPLEMENTATION

#include <arpa/inet.h>
#include <ctype.h>
#include <limits.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <zlib.h>

#include "lcars_arena.h"
#include "lcars_base.h"
#include "lcars_json.h"
#include "lcars_curl_ca.h" // a static build's CA bundle

// Every send() below passes MSG_NOSIGNAL: a client that hangs up mid-response
// must not raise SIGPIPE and kill the whole process. lcars.c defines
// _GNU_SOURCE before its first include, which is what declares it under
// -std=c11; 0 just restores the old behaviour on a platform without it
// rather than failing to compile.
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
// What a written timestamp may look like (NormalizeStoredTimestamp), named
// once so every 400 lists the same shapes.
#define HTTP_TIMESTAMP_SHAPES                                                  \
  "YYYY-MM-DD, YYYY-MM-DD HH:MM:SS (UTC) or "                                  \
  "YYYY-MM-DDTHH:MM:SS[.fff] with Z or +HH:MM"

// Max-Age matters more than it looks: a browser treats Authorization and
// Content-Type: application/json as non-simple headers, so every single
// request from the wasm client is preceded by an OPTIONS preflight. Without
// a cache lifetime that is two round trips per call, forever. 86400 is the
// ceiling Chrome honours.
#define HTTP_CORS_HEADERS                                                      \
  "Access-Control-Allow-Origin: *\r\n"                                         \
  "Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\n"   \
  "Access-Control-Allow-Headers: Content-Type, Authorization, "                \
  "X-LCARS-Client, Idempotency-Key\r\n"                                        \
  "Access-Control-Max-Age: 86400\r\n"

// How long a connection that has not yet said anything may sit there. Short
// on purpose: this is the speculative preconnect a browser opens and may
// never use, and until it is closed it occupies one of the
// HTTP_MAX_CONCURRENT_CONNECTIONS slots. A client that has connected and sent
// nothing for five seconds was not about to.
#define HTTP_CONNECT_TIMEOUT_SECONDS 5
// How long a connection that has already served a request may sit idle before
// the server hangs up. Longer, because sitting idle between requests is the
// whole point of keep-alive. Either way it is not tidiness: recv() has no
// timeout of its own, so a silent peer used to park a thread forever - and
// while this server was a serial accept loop, that one socket blocked *every
// other client*, which is what made the API unreachable after a couple of
// page loads.
#define HTTP_IDLE_TIMEOUT_SECONDS 15
// The same guard once a request has started arriving, for a peer that sends
// half a header or stops partway through a body.
#define HTTP_IO_TIMEOUT_SECONDS 10
// Ceiling on requests served over one connection before it is closed anyway.
// Nothing here leaks per request, but an unbounded loop is one fewer thing a
// client can hold open indefinitely.
#define HTTP_MAX_REQUESTS_PER_CONNECTION 100
// Ceiling on connections being served at once. Each costs a thread with a
// 1MB request arena on its stack, so this is the memory bound as much as the
// concurrency one.
#define HTTP_MAX_CONCURRENT_CONNECTIONS 32
// Explicit rather than inherited: HandleHTTPConnection puts a 1MB arena on
// the stack and CalDAV another 512KB below it, which is fine but should not
// depend on whatever the platform's default thread stack happens to be.
#define HTTP_THREAD_STACK_BYTES (4 * 1024 * 1024)

// Whether the connection currently being served will stay open after this
// response. Read by the response helpers so the Connection header can never
// disagree with what the loop actually does. Thread-local because one thread
// serves one connection start to finish.
static _Thread_local bool g_conn_keep_alive = false;

// The socket peer of the connection being served, as text, for the request
// log only. Behind tailscale serve it is always 127.0.0.1, which is why the
// log line also carries the proxy's X-Forwarded-For and Tailscale-User-Login
// - but those are headers any client can send, so nothing may ever decide
// anything on them; auth stays Basic auth alone.
static _Thread_local char g_conn_peer[INET6_ADDRSTRLEN] = "?";

// The Connection (and, when keeping, Keep-Alive) header every response
// carries. Sending nothing at all was the bug: HTTP/1.1 says a connection
// persists unless told otherwise, so a client would pool the socket, the
// server would close it anyway, and the next request paid either a fresh
// handshake or a failed reuse and a retry.
static const char *HTTPConnectionHeader(void) {
  return g_conn_keep_alive ? "Connection: keep-alive\r\n"
                             "Keep-Alive: timeout=15\r\n"
                           : "Connection: close\r\n";
}

static char g_auth_user[128] = {0};
static char g_auth_pass[128] = {0};
static bool g_auth_enabled = false;
// The limited logins (lcars_logins.h): Basic-auth users besides the main
// one that read everything and write only kinds of their own. Number One's
// (LCARS_NO1_USER/LCARS_NO1_PASS) owns no1_*, the crew's
// (LCARS_CREW_USER/LCARS_CREW_PASS: scheduled crew roles, headless agents
// that write reports) owns crew_*. The steward's
// (LCARS_STEWARD_USER/LCARS_STEWARD_PASS: the crew notes' runner, applying
// what a role was asked to add) owns nothing: it creates the captain's own
// kinds and appends to his entries, and changes nothing that is there.
// An empty user is "no such login".
typedef struct {
  const char *who;      // for messages: "Number One"
  const char *env_user; // the environment variables it is read from
  const char *env_pass;
  const char *owner; // its kinds: <owner>_*, task_<owner>, task_<owner>_*
  bool steward;      // the create-and-append rule instead (lcars_logins.h)
  char user[128];
  char pass[128];
} LimitedLogin;
static LimitedLogin g_login_no1 = {
    "Number One", "LCARS_NO1_USER", "LCARS_NO1_PASS", "no1", false, {0}, {0}};
static LimitedLogin g_login_crew = {
    "Crew", "LCARS_CREW_USER", "LCARS_CREW_PASS", "crew", false, {0}, {0}};
static LimitedLogin g_login_steward = {"The steward",
                                       "LCARS_STEWARD_USER",
                                       "LCARS_STEWARD_PASS",
                                       "steward",
                                       true,
                                       {0},
                                       {0}};
static LimitedLogin *const g_limited_logins[] = {&g_login_no1, &g_login_crew,
                                                 &g_login_steward};
#define LIMITED_LOGIN_COUNT                                                    \
  (sizeof(g_limited_logins) / sizeof(g_limited_logins[0]))
// The limited login this request authenticated with, NULL for the main one.
// Per request, like g_conn_accepts_gzip: reset before anything else reads
// it, since a keep-alive connection's next request may carry another login.
static _Thread_local const LimitedLogin *g_conn_login = NULL;
// The port the server bound, for the one thing that needs to call it back:
// the chat subprocess's lcars-cli (lcars_chat.h), via LCARS_URL.
static int g_http_port = 0;

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
  case 206:
    return "Partial Content";
  case 207:
    return "Multi-Status";
  case 301:
    return "Moved Permanently";
  case 304:
    return "Not Modified";
  case 400:
    return "Bad Request";
  case 401:
    return "Unauthorized";
  case 403:
    return "Forbidden";
  case 404:
    return "Not Found";
  case 405:
    return "Method Not Allowed";
  case 409:
    return "Conflict";
  case 411:
    return "Length Required";
  case 412:
    return "Precondition Failed";
  case 413:
    return "Payload Too Large";
  case 414:
    return "URI Too Long";
  case 415:
    return "Unsupported Media Type";
  case 416:
    return "Range Not Satisfiable";
  case 429:
    // the chat's and the event streams' caps; missing here, a third chat at
    // once used to trip the assert below and take the server down
    return "Too Many Requests";
  case 500:
    return "Internal Server Error";
  case 502:
    // POST /say: the text-to-speech provider refused or was unreachable
    return "Bad Gateway";
  case 503:
    return "Service Unavailable";
  case 507:
    return "Insufficient Storage";
  default:
    // Every status this file sends is listed above; a missing one would
    // otherwise go out with a nonsense reason phrase.
    assert(!"unhandled HTTP status code");
    return "Error";
  }
}

// ---------------------------------------------------------------------------
// Streamed (chunked, optionally gzipped) response bodies
// ---------------------------------------------------------------------------
//
// Why this exists: the web UI's cold load was ~30 requests moving 4.8MB of
// uncompressed JSON, and nothing between it and the phone compresses -
// tailscale serve proxies bytes as they come. JSON journal text gzips to a
// third of its size, so compression is most of the fix for the requests that
// are big, and GET /dump (one streamed response instead of 30 pages) is the
// rest.
//
// Chunked rather than Content-Length because neither the compressed size nor
// (for /dump) the raw size is known until the last byte has been produced, and
// the alternative - compress everything first, then send - needs a buffer the
// size of the answer, which is exactly what the 1MB connection arena cannot
// hold. Chunked framing keeps the connection reusable, so keep-alive is
// unaffected.
//
// zlib allocates its state through zalloc; that is routed into an arena on
// the stream's own stack frame (HTTP_GZIP_ZLIB_BYTES), so there is still no
// malloc on the request path and the budget is fixed. deflateInit2 at
// windowBits 15 / memLevel 8 needs 256KB of window+hash plus ~6KB of state;
// the rest is slack. If a zlib ever asked for more, arena_alloc aborts -
// that is a programmer error in the budget, not a runtime condition.

// Gzip only when it pays: a small answer compresses to about the same number
// of packets, and costs a deflate state setup to find that out.
#define HTTP_GZIP_MIN_BYTES 1024
// 5 rather than zlib's default 6: on the one-core VPS the full journal takes
// ~120ms at 1 and ~250ms at 6, for 1.78MB against 1.54MB. The deflate runs
// while earlier chunks are on the wire, so the middle is where the slower of
// "compressing" and "sending to a phone" is smallest.
#define HTTP_GZIP_LEVEL 5
#define HTTP_GZIP_ZLIB_BYTES (320 * 1024)
// Size of each chunk handed to send(). Big enough that the chunk framing is
// noise, small enough to sit on the connection thread's stack.
#define HTTP_STREAM_CHUNK_BYTES (64 * 1024)

// Whether this request's client said it accepts gzip. Set per request by the
// router, before any response helper can run - same shape and reason as
// g_conn_keep_alive.
static _Thread_local bool g_conn_accepts_gzip = false;

typedef struct HTTPBodyStream {
  int fd;
  bool gzip;
  bool failed; // a send() failed or zlib refused; nothing more goes out
  z_stream z;
  Arena zarena;
  size_t raw_bytes;  // body bytes before compression, for the log line
  size_t wire_bytes; // what actually went on the wire, framing excluded
  size_t out_len;    // bytes waiting in out[] (identity streams only)
  unsigned char out[HTTP_STREAM_CHUNK_BYTES];
} HTTPBodyStream;

static voidpf HTTPZAlloc(voidpf opaque, uInt items, uInt size) {
  Arena *arena = (Arena *)opaque;
  assert(arena_valid(arena));
  return arena_alloc(arena, (size_t)items * (size_t)size);
}

static void HTTPZFree(voidpf opaque, voidpf address) {
  // Released with the whole arena when the stream's frame returns.
  (void)opaque;
  (void)address;
}

// One chunk of chunked framing. Failure is sticky: after a client has gone,
// every further write is skipped rather than retried.
static void HTTPStreamSendChunk(HTTPBodyStream *s, const unsigned char *data,
                                size_t n) {
  assert(s != NULL);
  assert(data != NULL || n == 0);
  if (s->failed || n == 0) {
    return;
  }
  char head[32];
  int hn = snprintf(head, sizeof(head), "%zx\r\n", n);
  assert(hn > 0 && hn < (int)sizeof(head));
  if (send(s->fd, head, (size_t)hn, MSG_NOSIGNAL) != hn ||
      send(s->fd, data, n, MSG_NOSIGNAL) != (ssize_t)n ||
      send(s->fd, "\r\n", 2, MSG_NOSIGNAL) != 2) {
    s->failed = true;
    return;
  }
  s->wire_bytes += n;
}

// Sends the status line and headers and readies the body stream. `s` must
// live on the caller's stack for the whole response.
static void HTTPStreamBegin(HTTPBodyStream *s, int fd, int status,
                            const char *content_type, const char *extra_headers,
                            bool gzip, uint8_t *zlib_buf,
                            size_t zlib_buf_size) {
  assert(s != NULL);
  assert(fd >= 0);
  assert(content_type != NULL);
  assert(!gzip || (zlib_buf != NULL && zlib_buf_size > 0));

  s->fd = fd;
  s->gzip = gzip;
  s->failed = false;
  s->raw_bytes = 0;
  s->wire_bytes = 0;
  s->out_len = 0;
  if (gzip) {
    arena_init(&s->zarena, zlib_buf, zlib_buf_size);
    memset(&s->z, 0, sizeof(s->z));
    s->z.zalloc = HTTPZAlloc;
    s->z.zfree = HTTPZFree;
    s->z.opaque = &s->zarena;
    // windowBits 15 + 16 is zlib's spelling of "gzip wrapper, not zlib".
    if (deflateInit2(&s->z, HTTP_GZIP_LEVEL, Z_DEFLATED, 15 + 16, 8,
                     Z_DEFAULT_STRATEGY) != Z_OK) {
      // Only possible on a zlib/header version mismatch; fall back to
      // identity rather than failing the request.
      s->gzip = false;
    }
  }

  char header[1024];
  int header_len = snprintf(
      header, sizeof(header),
      "HTTP/1.1 %d %s\r\n"
      "Content-Type: %s\r\n" HTTP_CORS_HEADERS "%s%s%s"
      "Transfer-Encoding: chunked\r\n"
      "\r\n",
      status, http_status_text(status), content_type, HTTPConnectionHeader(),
      s->gzip ? "Content-Encoding: gzip\r\nVary: Accept-Encoding\r\n" : "",
      extra_headers ? extra_headers : "");
  assert(header_len > 0 && header_len < (int)sizeof(header));
  if (send(fd, header, (size_t)header_len, MSG_NOSIGNAL) != header_len) {
    s->failed = true;
  }
}

// Runs deflate over whatever is in z.next_in, sending each full output
// buffer as a chunk. `flush` is Z_NO_FLUSH while writing and Z_FINISH once.
static void HTTPStreamDeflate(HTTPBodyStream *s, int flush) {
  assert(s != NULL && s->gzip);
  do {
    s->z.next_out = s->out;
    s->z.avail_out = sizeof(s->out);
    int rc = deflate(&s->z, flush);
    assert(rc != Z_STREAM_ERROR); // the state is ours and never shared
    (void)rc;
    HTTPStreamSendChunk(s, s->out, sizeof(s->out) - s->z.avail_out);
  } while (s->z.avail_out == 0 && !s->failed);
}

static void HTTPStreamWrite(HTTPBodyStream *s, const void *data, size_t n) {
  assert(s != NULL);
  assert(data != NULL || n == 0);
  if (s->failed || n == 0) {
    return;
  }
  s->raw_bytes += n;
  if (s->gzip) {
    s->z.next_in = (Bytef *)data;
    s->z.avail_in = (uInt)n;
    assert((size_t)s->z.avail_in == n);
    HTTPStreamDeflate(s, Z_NO_FLUSH);
    assert(s->failed || s->z.avail_in == 0);
    return;
  }
  // Identity: coalesce small writes (one row of /dump is often ~200 bytes)
  // into full chunks rather than framing every one of them.
  const unsigned char *p = (const unsigned char *)data;
  while (n > 0 && !s->failed) {
    size_t room = sizeof(s->out) - s->out_len;
    size_t take = n < room ? n : room;
    memcpy(s->out + s->out_len, p, take);
    s->out_len += take;
    p += take;
    n -= take;
    if (s->out_len == sizeof(s->out)) {
      HTTPStreamSendChunk(s, s->out, s->out_len);
      s->out_len = 0;
    }
  }
  assert(s->out_len <= sizeof(s->out));
}

// Finishes the body. `complete` false means the producer hit an error after
// the 200 had already gone out: the terminating chunk is then *not* sent, so
// the client sees a truncated transfer (an error) rather than a well-formed
// response holding half a JSON document - and the connection is closed,
// because its framing is no longer something the next request can follow.
static void HTTPStreamEnd(HTTPBodyStream *s, bool complete) {
  assert(s != NULL);
  if (complete && !s->failed) {
    if (s->gzip) {
      s->z.next_in = NULL;
      s->z.avail_in = 0;
      HTTPStreamDeflate(s, Z_FINISH);
    } else if (s->out_len > 0) {
      HTTPStreamSendChunk(s, s->out, s->out_len);
      s->out_len = 0;
    }
    if (!s->failed && send(s->fd, "0\r\n\r\n", 5, MSG_NOSIGNAL) != 5) {
      s->failed = true;
    }
  }
  if (s->gzip) {
    deflateEnd(&s->z);
  }
  if (!complete || s->failed) {
    g_conn_keep_alive = false;
  }
}

// Whether a buffered response should go out gzipped instead: the client
// offered it, it is JSON (CalDAV's XML and iCalendar stay as they are - a
// phone's Reminders sync is not what this is for, and not worth the risk),
// and it is big enough to be worth it.
static bool HTTPShouldGzip(const char *content_type, size_t body_len) {
  assert(content_type != NULL);
  return g_conn_accepts_gzip && body_len >= HTTP_GZIP_MIN_BYTES &&
         strncmp(content_type, "application/json", 16) == 0;
}

// The buffered body, streamed through gzip. Kept apart from
// SendHTTPResponseEx so its ~400KB of stack (zlib's arena plus the output
// chunk) is only paid by the responses that take this path.
static int SendHTTPResponseGzip(int client_fd, int status,
                                const char *content_type,
                                const char *extra_headers, const char *body,
                                size_t body_len) {
  assert(client_fd >= 0);
  assert(body != NULL);
  uint8_t zbuf[HTTP_GZIP_ZLIB_BYTES];
  HTTPBodyStream s;
  HTTPStreamBegin(&s, client_fd, status, content_type, extra_headers, true,
                  zbuf, sizeof(zbuf));
  HTTPStreamWrite(&s, body, body_len);
  HTTPStreamEnd(&s, true);
  return status;
}

// Sends a complete response and returns `status`, so handlers can
// `return SendHTTPResponse(...)`. All sends use MSG_NOSIGNAL: a client that
// disappears mid-response must not raise SIGPIPE and kill the process.
// `extra_headers`, when given, is spliced in verbatim ahead of
// Content-Length and must be a CRLF-terminated block - it is how the CalDAV
// module attaches DAV:, Allow: and ETag:.
static int SendHTTPResponseEx(int client_fd, int status,
                              const char *content_type,
                              const char *extra_headers, const char *body,
                              size_t body_len) {
  assert(client_fd >= 0);
  assert(content_type != NULL);
  assert(body != NULL || body_len == 0);

  if (HTTPShouldGzip(content_type, body_len)) {
    return SendHTTPResponseGzip(client_fd, status, content_type, extra_headers,
                                body, body_len);
  }

  char header[1024];
  int header_len = snprintf(
      header, sizeof(header),
      "HTTP/1.1 %d %s\r\n"
      "Content-Type: %s\r\n" HTTP_CORS_HEADERS "%s%sContent-Length: %zu\r\n"
      "\r\n",
      status, http_status_text(status), content_type, HTTPConnectionHeader(),
      extra_headers ? extra_headers : "", body_len);
  assert(header_len > 0 && header_len < (int)sizeof(header));
  send(client_fd, header, (size_t)header_len, MSG_NOSIGNAL);
  if (body_len > 0) {
    send(client_fd, body, body_len, MSG_NOSIGNAL);
  }
  return status;
}

static int SendHTTPResponse(int client_fd, int status, const char *content_type,
                            const char *body, size_t body_len) {
  return SendHTTPResponseEx(client_fd, status, content_type, NULL, body,
                            body_len);
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
  char u[7];
  for (const char *p = src ? src : ""; *p; p++) {
    const char *esc = json_escape_byte((unsigned char)*p, u);
    size_t need = esc ? strlen(esc) : 1;
    if (out + need >= dst_size) {
      break;
    }
    if (esc) {
      memcpy(dst + out, esc, need);
    } else {
      dst[out] = *p;
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

// Request bodies are read with lcars_json.h's scanner: `key` is a member of
// the top-level object, so a key-like run of text inside a string value
// ("content": "... \"kind\": ...") or a nested object is never taken for it,
// and a string's escapes are decoded whole (\n, \t, \u00e9 and surrogate
// pairs - Python's json.dumps writes every non-ASCII character as \u).
// A body that is not a JSON object has no members.
static bool json_body_member(const char *json, const char *key, JsonSpan *out) {
  assert(json != NULL);
  assert(key != NULL);
  assert(out != NULL);
  const char *end = json + strlen(json);
  const char *p = json_skip_ws(json, end);
  JsonSpan top = {p, (size_t)(end - p)};
  return json_member(top, key, out);
}

// A string member, decoded into `out_val` and cut (never mid-character) to
// fit `max_len`. False when it is missing or not a string (null included).
static bool json_get_string(const char *json, const char *key, char *out_val,
                            size_t max_len) {
  assert(out_val != NULL);
  assert(max_len > 0);
  JsonSpan v;
  if (!json_body_member(json, key, &v) || v.len < 2 || v.data[0] != '"') {
    return false;
  }
  json_unescape(v.data + 1, v.data + v.len - 1, out_val, max_len);
  return true;
}

// The same, copied into `arena` at whatever length it has. Entry content is
// a journal entry - it does not fit a fixed buffer, and truncating it to one
// silently loses the tail of what the client sent.
static bool json_get_string_arena(Arena *arena, const char *json,
                                  const char *key, char **out_val) {
  assert(arena_valid(arena));
  assert(out_val != NULL);
  JsonSpan v;
  if (!json_body_member(json, key, &v) || v.len < 2 || v.data[0] != '"') {
    return false;
  }
  *out_val = (char *)json_span_string(arena, v);
  return true;
}

// A number member's text, for strtol/strtof. "1" is taken as well as 1, and
// true/false as 1/0: Shortcuts and shell clients quote everything, and
// rejecting that silently drops the field.
static bool json_get_number_text(const char *json, const char *key, char *out,
                                 size_t out_size) {
  JsonSpan v;
  if (!json_body_member(json, key, &v)) {
    return false;
  }
  if (v.len >= 2 && v.data[0] == '"') {
    v.data++;
    v.len -= 2;
  }
  if (v.len == 4 && memcmp(v.data, "true", 4) == 0) {
    v = (JsonSpan){"1", 1};
  } else if (v.len == 5 && memcmp(v.data, "false", 5) == 0) {
    v = (JsonSpan){"0", 1};
  }
  if (v.len == 0 || v.len >= out_size) {
    return false;
  }
  memcpy(out, v.data, v.len);
  out[v.len] = '\0';
  return true;
}

static bool json_get_int(const char *json, const char *key, int *out_val) {
  assert(out_val != NULL);
  char text[64];
  if (!json_get_number_text(json, key, text, sizeof(text))) {
    return false;
  }
  char *endptr;
  long val = strtol(text, &endptr, 10);
  if (endptr == text) {
    return false;
  }
  *out_val = (int)val;
  return true;
}

static bool json_get_float(const char *json, const char *key, float *out_val) {
  assert(out_val != NULL);
  char text[64];
  if (!json_get_number_text(json, key, text, sizeof(text))) {
    return false;
  }
  char *endptr;
  float val = strtof(text, &endptr);
  if (endptr == text) {
    return false;
  }
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
    // The blank line ends the headers. Past it req_buf holds the body or a
    // pipelined next request, whose own Content-Length (or Authorization)
    // must never be read as this request's.
    if (p && p[0] == '\r' && p[1] == '\n')
      break;
  }
  return NULL;
}

// Request bodies are never this large (the media cap is 1GB); a longer
// Content-Length is kept at this value so it still counts as too large, and
// the parse cannot overflow.
#define HTTP_CONTENT_LENGTH_CAP (1LL << 40)

// The request's Content-Length into *out_len: 0 with no header. False for
// anything but digits (blanks around them aside) - a sign, a fraction, junk
// after the number, an empty value - and for a Transfer-Encoding header,
// which this server does not decode: such a body would be taken as the next
// request. atoi() used to read "-5" as -5 and "5x" as 5; a negative length
// walked req_buf's leftover arithmetic past what was received.
static bool ParseContentLength(const char *req_buf, long long *out_len) {
  assert(req_buf != NULL && out_len != NULL);
  *out_len = 0;
  if (find_header_value(req_buf, "Transfer-Encoding:") != NULL) {
    return false;
  }
  const char *v = find_header_value(req_buf, "Content-Length:");
  if (v == NULL) {
    return true;
  }
  long long n = 0;
  const char *d = v;
  for (; *d >= '0' && *d <= '9'; d++) {
    n = n * 10 + (*d - '0');
    if (n > HTTP_CONTENT_LENGTH_CAP) {
      n = HTTP_CONTENT_LENGTH_CAP;
    }
  }
  if (d == v) {
    return false;
  }
  while (*d == ' ' || *d == '\t') {
    d++;
  }
  if (!(d[0] == '\r' && d[1] == '\n')) {
    return false;
  }
  assert(n >= 0 && n <= HTTP_CONTENT_LENGTH_CAP);
  *out_len = n;
  return true;
}

// Copies a request header's value (to the end of its line, trailing blanks
// trimmed, cut at out_size - 1 bytes) into `out`. False, with `out` empty,
// when the request has no such header.
static bool CopyHeaderValue(const char *headers, const char *name, char *out,
                            size_t out_size) {
  assert(headers != NULL && name != NULL && out != NULL && out_size > 0);
  const char *v = find_header_value(headers, name);
  if (v == NULL) {
    out[0] = '\0';
    return false;
  }
  size_t n = strcspn(v, "\r\n");
  if (n >= out_size) {
    n = out_size - 1;
  }
  memcpy(out, v, n);
  out[n] = '\0';
  while (n > 0 && (out[n - 1] == ' ' || out[n - 1] == '\t')) {
    out[--n] = '\0';
  }
  assert(n < out_size);
  return true;
}

typedef struct HTTPRequestLine {
  char method[16];
  char path[256];
} HTTPRequestLine;

// Bounds how long any single recv/send on this socket may block. Without it
// recv() waits forever, which is what let one silent peer hold a connection
// (and, before this server threaded, the whole API) indefinitely.
static void SetSocketTimeout(int fd, int seconds) {
  assert(fd >= 0);
  assert(seconds > 0);

  struct timeval tv;
  tv.tv_sec = seconds;
  tv.tv_usec = 0;
  // Best-effort: a kernel that refuses these still serves requests, it just
  // loses the guard, so this is logged by its absence rather than fatal.
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
}

// Whether the client is willing to reuse this connection. HTTP/1.1 defaults
// to yes, HTTP/1.0 to no, and an explicit Connection header wins either way.
static bool HTTPWantsKeepAlive(const char *req_buf) {
  assert(req_buf != NULL);

  const char *conn = find_header_value(req_buf, "Connection:");
  if (conn != NULL) {
    // Only the two tokens that matter here; a comma-separated list naming
    // something else falls through to the version default.
    if (strncasecmp(conn, "close", 5) == 0) {
      return false;
    }
    if (strncasecmp(conn, "keep-alive", 10) == 0) {
      return true;
    }
  }
  return strstr(req_buf, "HTTP/1.1") != NULL;
}

// Whether the Accept-Encoding header offers gzip. Only an explicit `q=0`
// refuses it; any other weight is a yes, because gzip is the only coding this
// server has and there is nothing to rank it against.
static bool HTTPAcceptsGzip(const char *req_buf) {
  assert(req_buf != NULL);
  const char *v = find_header_value(req_buf, "Accept-Encoding:");
  if (v == NULL) {
    return false;
  }
  const char *eol = strstr(v, "\r\n");
  size_t n = eol ? (size_t)(eol - v) : strlen(v);
  for (size_t i = 0; i + 4 <= n; i++) {
    if (strncasecmp(v + i, "gzip", 4) != 0) {
      continue;
    }
    // A token, not a substring of one ("x-gzip" is the same coding; nothing
    // else contains the four letters).
    const char *p = v + i + 4;
    const char *end = v + n;
    while (p < end && (*p == ' ' || *p == '\t'))
      p++;
    if (p < end && *p == ';') {
      p++;
      while (p < end && (*p == ' ' || *p == '\t'))
        p++;
      if (end - p >= 3 && strncasecmp(p, "q=0", 3) == 0) {
        const char *q = p + 3;
        bool nonzero = false;
        if (q < end && *q == '.') {
          for (q++; q < end && *q >= '0' && *q <= '9'; q++) {
            if (*q != '0') {
              nonzero = true;
            }
          }
        }
        return nonzero;
      }
    }
    return true;
  }
  return false;
}

// Reads the HTTP request (headers, and any body bytes that happen to
// arrive in the same recv burst) from client_fd into req_buf (must be
// req_buf_size bytes), stopping at the blank line ending headers or when
// req_buf fills up. Parses the request line into *out_line, and reports
// how much was read / where the body starts via the other out-params
// (needed later to know how many body bytes were already buffered before
// the rest are read separately). On failure (missing header-terminator,
// or an unparseable request line), prints a diagnostic and returns false
// - neither failure mode has ever sent an HTTP response before closing
// the connection, and this preserves that. *out_idle distinguishes the third
// case, which is not a failure at all: the peer sent nothing, which is how a
// kept-alive connection normally ends and what an unused preconnect is.
static bool ReadHTTPRequestLine(int client_fd, char *req_buf,
                                size_t req_buf_size, int carry,
                                int idle_timeout_seconds, int *out_total_read,
                                char **out_body_start, int *out_headers_len,
                                HTTPRequestLine *out_line, bool *out_idle) {
  assert(client_fd >= 0);
  assert(req_buf != NULL);
  // req_buf[total_read] = '\0' with total_read bounded by req_buf_size - 1.
  assert(req_buf_size > 1);
  assert(out_total_read != NULL && out_body_start != NULL);
  assert(out_headers_len != NULL && out_line != NULL && out_idle != NULL);

  *out_idle = false;

  // `carry` is what the previous request on this connection read past its own
  // body - a pipelined request, or just the head of the next one arriving in
  // the same segment. It is already at the front of req_buf.
  assert(carry >= 0 && carry < (int)req_buf_size);
  int total_read = carry;
  req_buf[total_read] = '\0';

  // How long to wait for the request to *start* is the caller's call (a
  // never-used connection gets far less patience than one between keep-alive
  // requests); once bytes are arriving it drops to HTTP_IO_TIMEOUT_SECONDS.
  assert(idle_timeout_seconds > 0);
  SetSocketTimeout(client_fd, idle_timeout_seconds);
  bool started = (carry > 0);
  while (total_read < (int)req_buf_size - 1 &&
         strstr(req_buf, "\r\n\r\n") == NULL) {
    int n =
        recv(client_fd, req_buf + total_read, req_buf_size - 1 - total_read, 0);
    if (n <= 0)
      break;
    if (!started) {
      SetSocketTimeout(client_fd, HTTP_IO_TIMEOUT_SECONDS);
      started = true;
    }
    total_read += n;
    req_buf[total_read] = '\0';
  }
  SetSocketTimeout(client_fd, HTTP_IO_TIMEOUT_SECONDS);
  assert(total_read >= 0 && total_read < (int)req_buf_size);
  *out_total_read = total_read;

  char *body_start = strstr(req_buf, "\r\n\r\n");
  if (!body_start) {
    // Nothing arrived at all: a peer that opened a connection and said
    // nothing (a browser preconnect), or one that hung up between requests.
    // Neither is an error, and on a kept-alive connection it is the normal
    // way one ends - so it must not be logged as a parse failure.
    *out_idle = (total_read == carry);
    if (!*out_idle) {
      printf("HTTP Connection Error: Missing end-of-header delimiter\n");
    }
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
// Fills in the Basic auth credentials from the environment (or the
// admin/admin default) if SetHTTPServerCredentials() did not.
//
// Called once from RunHTTPServer before the first connection is accepted,
// which is the point: doing it lazily inside CheckHTTPAuth was fine on a
// serial server, but with a thread per connection two first requests could
// race and one could compare against a half-copied password - failing a
// login that should have succeeded, intermittently.
// One limited login, from its two environment variables. Left off (empty)
// unless both are set, the password is 16 characters or more, and the user
// is neither the main one's nor another limited login's - a shared name
// would make which login a request carried depend on the order of the
// comparisons.
static void LimitedLoginInit(LimitedLogin *l) {
  assert(l != NULL && l->env_user != NULL && l->env_pass != NULL);
  const char *u = getenv(l->env_user);
  const char *p = getenv(l->env_pass);
  bool taken = u != NULL && strcmp(u, g_auth_user) == 0;
  for (size_t i = 0; u != NULL && i < LIMITED_LOGIN_COUNT; i++) {
    const LimitedLogin *o = g_limited_logins[i];
    taken = taken || (o != l && o->user[0] != '\0' && strcmp(u, o->user) == 0);
  }
  if (u == NULL || p == NULL || u[0] == '\0' || strlen(p) < 16 || taken ||
      strlen(u) >= sizeof(l->user) || strlen(p) >= sizeof(l->pass)) {
    if (u != NULL && u[0] != '\0') {
      printf("HTTP: %s set but the login is off (password under 16 "
             "characters, too long, or another login's name)\n",
             l->env_user);
    }
    l->user[0] = l->pass[0] = '\0';
    return;
  }
  snprintf(l->user, sizeof(l->user), "%s", u);
  snprintf(l->pass, sizeof(l->pass), "%s", p);
  assert(l->user[0] != '\0' && strlen(l->pass) >= 16);
}

static void LimitedLoginsInit(void) {
  // cleared first, so a re-read cannot find a login clashing with its own
  // previous value
  for (size_t i = 0; i < LIMITED_LOGIN_COUNT; i++) {
    g_limited_logins[i]->user[0] = g_limited_logins[i]->pass[0] = '\0';
  }
  for (size_t i = 0; i < LIMITED_LOGIN_COUNT; i++) {
    LimitedLoginInit(g_limited_logins[i]);
  }
}

static void EnsureHTTPAuthInit(void) {
  if (g_auth_enabled) {
    LimitedLoginsInit();
    return;
  }
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
  LimitedLoginsInit();

  assert(g_auth_user[0] != '\0');
}

static bool CheckHTTPAuth(int client_fd, const char *req_buf) {
  assert(client_fd >= 0);
  assert(req_buf != NULL);
  // RunHTTPServer already did this before accepting anything; a caller that
  // reached here without it would be comparing against an empty password.
  assert(g_auth_enabled);

  bool authenticated = false;
  g_conn_login = NULL;
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
          for (size_t i = 0; i < LIMITED_LOGIN_COUNT; i++) {
            const LimitedLogin *l = g_limited_logins[i];
            if (l->user[0] != '\0' && strcmp(user, l->user) == 0 &&
                strcmp(pass, l->pass) == 0) {
              authenticated = true;
              g_conn_login = l;
            }
          }
        }
        if (!authenticated) {
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
    // WWW-Authenticate header — except for the web UI's own requests, which
    // say so with X-LCARS-Client. The challenge makes the browser raise its
    // own Basic-auth sheet before the page sees the 401, and on an iPhone's
    // home-screen app what is typed there lasts only until the app is closed:
    // every cold launch asked again, and the page's Connection dialog, which
    // keeps the password, never got the chance to. curl, CalDAV clients and
    // a browser tab opened on the API still get the challenge they need.
    bool page = find_header_value(req_buf, "X-LCARS-Client:") != NULL;
    static const char json[] = "{\"error\":\"Unauthorized\",\"status\":401}";
    char resp[512];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 401 Unauthorized\r\n"
                     "%s"
                     "Content-Type: application/json\r\n" HTTP_CORS_HEADERS "%s"
                     "Content-Length: %zu\r\n\r\n%s",
                     page ? "" : "WWW-Authenticate: Basic realm=\"LCARS\"\r\n",
                     HTTPConnectionHeader(), sizeof(json) - 1, json);
    assert(n > 0 && n < (int)sizeof(resp));
    send(client_fd, resp, (size_t)n, MSG_NOSIGNAL);
    return false;
  }
  return true;
}

// Parses Content-Type from req_buf's headers and reads the content_len
// bytes of body (already-buffered bytes past the headers, plus whatever's
// still arriving) into arena. *out_body is left pointing at a static empty
// string if there's no body. Returns 0, or the status it answered: 413 if
// the client announced more than HTTP_MAX_BODY_BYTES, 400 if fewer bytes
// arrived than it announced.
static int ReadHTTPRequestBody(int client_fd, Arena *arena, const char *req_buf,
                               const char *body_start, int total_read,
                               int headers_len, long long content_len,
                               char **out_body, char *out_content_type,
                               size_t content_type_size) {
  assert(client_fd >= 0);
  assert(arena != NULL);
  assert(req_buf != NULL && body_start != NULL);
  assert(out_body != NULL && out_content_type != NULL);
  assert(content_type_size > 0);
  assert(headers_len >= 0 && headers_len <= total_read);
  assert(body_start >= req_buf); // body_start points into req_buf
  // ParseContentLength's: never negative
  assert(content_len >= 0 && content_len <= HTTP_CONTENT_LENGTH_CAP);

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
  // content_len is attacker-controlled, so it is checked, never asserted:
  // past this cap the allocation below would exhaust the connection's 1MB
  // arena and abort the whole process, UI included.
  if (content_len > HTTP_MAX_BODY_BYTES) {
    printf("HTTP Request Rejected: Content-Length %lld exceeds the %d byte "
           "limit\n",
           content_len, HTTP_MAX_BODY_BYTES);
    return SendJSONError(client_fd, 413, "Request body exceeds %d bytes",
                         HTTP_MAX_BODY_BYTES);
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
    // The peer hung up or went silent short of what it announced: the tail
    // of the allocation was never written, and a handler must not parse it.
    if (body_already_read < content_len) {
      printf("HTTP Request Rejected: body ended at %d of %lld bytes\n",
             body_already_read, content_len);
      return SendJSONError(client_fd, 400,
                           "Body ended at %d of %lld bytes (Content-Length)",
                           body_already_read, content_len);
    }
    body[content_len] = '\0';
    *out_body = body;
  }

  assert(*out_body != NULL);
  return 0;
}

// ---------------------------------------------------------------------------
// Database helpers
// ---------------------------------------------------------------------------

// Opens this connection's own handle on lcars.db. Answers 500 and returns
// false if that fails. The busy timeout matters because the connection
// threads write side by side: without it a write racing another fails
// instantly with SQLITE_BUSY instead of waiting its turn.
static bool OpenHTTPDB(int client_fd, sqlite3 **out_db) {
  assert(client_fd >= 0);
  assert(out_db != NULL);

  sqlite3 *db = NULL;
  int rc = sqlite3_open(LcarsDBPath(), &db);
  if (rc != SQLITE_OK) {
    printf("HTTP Database Error: Failed to open database '%s': %s\n",
           LcarsDBPath(), sqlite3_errstr(rc));
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
// New columns go on the *end*, after length(content): AppendEntryJSON reads
// by position, so inserting one anywhere else silently shifts every index
// after it.
#define HTTP_ENTRY_COLUMNS                                                     \
  "id, kind, title, content, value_int, value_float, done_bool, deleted, "     \
  "created_at_utc, last_modified_at_utc, length(content), start_date, "        \
  "end_date"

static void AppendEntryJSON(JSONBuf *b, sqlite3_stmt *stmt,
                            bool include_content) {
  assert(b != NULL);
  assert(stmt != NULL);

  const char *kind = (const char *)sqlite3_column_text(stmt, 1);
  const char *title = (const char *)sqlite3_column_text(stmt, 2);
  const char *content = (const char *)sqlite3_column_text(stmt, 3);
  const char *created_at = (const char *)sqlite3_column_text(stmt, 8);
  const char *last_modified = (const char *)sqlite3_column_text(stmt, 9);
  const char *start_date = (const char *)sqlite3_column_text(stmt, 11);
  const char *end_date = (const char *)sqlite3_column_text(stmt, 12);

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
  // Always emitted, empty when unset, so a client can tell "not scheduled"
  // from "this server is too old to know about scheduling" - the latter omits
  // the keys entirely.
  jsonbuf_append(b, ",\"start_date\":");
  jsonbuf_append_json_string(b, start_date);
  jsonbuf_append(b, ",\"end_date\":");
  jsonbuf_append_json_string(b, end_date);
  jsonbuf_append(b, "}");
}

// A WHERE clause built from query parameters plus the values to bind into
// it, in order. Nothing the client sends is ever pasted into the SQL text -
// the clauses are fixed literals and the values are always bound.
// Headroom, not a guess. The pre-scheduling filter set already pushed exactly
// 12 with everything combined (kind 1 + q 2 + date 2 + four ranges 4 + done 1
// + min_id/max_id 2), so it was sitting on the assert; the scheduling filters
// below add up to four more.
#define HTTP_MAX_BINDS 24

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
  // filter_where() asserts rather than truncates, so this has to fit every
  // clause at once; scheduled_date's overlap test alone is ~110 characters.
  char where[2048];
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
  // Truncates an over-long value on purpose (query_get's buffers are the same
  // size, so it cannot happen today). memcpy with an explicit length rather
  // than strncpy, whose truncation gcc reports once it can see the sizes.
  size_t n = strnlen(value, sizeof(b->text_val) - 1);
  memcpy(b->text_val, value, n);
  b->text_val[n] = '\0';
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

// Days since 1970-01-01 of a proleptic Gregorian y-m-d, and back (Howard
// Hinnant's civil-day algorithms). Plain integer arithmetic on purpose: the
// zoned stamp below must be turned into UTC on a connection thread, where
// mktime/localtime would read $TZ, and this needs no struct tm at all.
static int64_t HttpDaysFromCivil(int64_t y, int m, int d) {
  y -= m <= 2;
  int64_t era = (y >= 0 ? y : y - 399) / 400;
  int64_t yoe = y - era * 400;                                   // [0, 399]
  int64_t doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1; // [0, 365]
  int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;           // [0, 146096]
  return era * 146097 + doe - 719468;
}

static void HttpCivilFromDays(int64_t z, int64_t *y, int *m, int *d) {
  z += 719468;
  int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  int64_t doe = z - era * 146097;
  int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  int64_t mp = (5 * doy + 2) / 153;
  *d = (int)(doy - (153 * mp + 2) / 5 + 1);
  *m = (int)(mp < 10 ? mp + 3 : mp - 9);
  *y = yoe + era * 400 + (*m <= 2);
}

// Reads exactly `n` digits at *p, advancing past them.
static bool HttpReadDigits(const char **p, int n, int *out) {
  int v = 0;
  for (int i = 0; i < n; i++) {
    char c = (*p)[i];
    if (c < '0' || c > '9') {
      return false;
    }
    v = v * 10 + (c - '0');
  }
  *p += n;
  *out = v;
  return true;
}

// ISO 8601 with a zone: "YYYY-MM-DDTHH:MM:SS", an optional fractional second
// (dropped - the column holds whole seconds), then "Z" or "+HH:MM"/"-HH:MM"
// (or "+HHMM"). This is what an Apple Shortcut's ISO 8601 date format gives:
// it can only format in the phone's local time, so the offset is what makes
// the stamp absolute. Written out as the stored UTC "YYYY-MM-DD HH:MM:SS".
// A stamp without a zone is refused rather than guessed at - a local time
// read as UTC would land the entry hours off with nothing to say so.
static bool ParseZonedTimestamp(const char *in, char *out, size_t out_size) {
  assert(in != NULL);
  assert(out != NULL);
  assert(out_size > HTTP_MAX_TIMESTAMP_LEN);

  const char *p = in;
  int y, mo, d, h, mi, s;
  if (!HttpReadDigits(&p, 4, &y) || *p++ != '-' ||
      !HttpReadDigits(&p, 2, &mo) || *p++ != '-' ||
      !HttpReadDigits(&p, 2, &d) || (*p != 'T' && *p != 't') || !*p++ ||
      !HttpReadDigits(&p, 2, &h) || *p++ != ':' ||
      !HttpReadDigits(&p, 2, &mi) || *p++ != ':' ||
      !HttpReadDigits(&p, 2, &s)) {
    return false;
  }
  if (*p == '.' || *p == ',') {
    p++;
    if (*p < '0' || *p > '9') {
      return false;
    }
    while (*p >= '0' && *p <= '9') {
      p++;
    }
  }
  int offset = 0; // seconds east of UTC
  if (*p == 'Z' || *p == 'z') {
    p++;
  } else if (*p == '+' || *p == '-') {
    int sign = *p++ == '-' ? -1 : 1;
    int oh, om;
    if (!HttpReadDigits(&p, 2, &oh)) {
      return false;
    }
    if (*p == ':') {
      p++;
    }
    if (!HttpReadDigits(&p, 2, &om) || oh > 23 || om > 59) {
      return false;
    }
    offset = sign * (oh * 3600 + om * 60);
  } else {
    return false;
  }
  if (*p != '\0') {
    return false;
  }
  static const int mdays[12] = {31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  bool leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
  if (mo < 1 || mo > 12 || d < 1 || d > mdays[mo - 1] ||
      (mo == 2 && d == 29 && !leap) || h > 23 || mi > 59 || s > 59) {
    return false;
  }
  // Local wall time minus its offset is UTC.
  int64_t t =
      HttpDaysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s - offset;
  int64_t days = t >= 0 ? t / 86400 : (t - 86399) / 86400; // floor
  int64_t secs = t - days * 86400;
  int64_t uy;
  int um, ud;
  HttpCivilFromDays(days, &uy, &um, &ud);
  if (uy < 0 || uy > 9999) {
    return false; // not four digits, so it would not compare as text
  }
  snprintf(out, out_size, "%04d-%02d-%02d %02d:%02d:%02d", (int)uy, um, ud,
           (int)(secs / 3600), (int)(secs / 60 % 60), (int)(secs % 60));
  return true;
}

// The write-side companion to NormalizeTimestamp. An import replaying old
// history (see lcars_logseq.h) has to be able to say *when* an entry was
// written, and the column it lands in is compared as text everywhere else in
// this file - so a bare date is widened to midnight rather than stored 9
// characters short of every other row, and a zoned ISO 8601 stamp
// (ParseZonedTimestamp) is converted to UTC. The query filters keep to
// NormalizeTimestamp's two shapes: in a query string an unescaped "+" is a
// space, so "+03:00" would arrive as " 03:00" and read as nonsense.
static bool NormalizeStoredTimestamp(const char *in, char *out,
                                     size_t out_size) {
  assert(in != NULL);
  assert(out != NULL);
  assert(out_size > HTTP_MAX_TIMESTAMP_LEN);

  char normalized[HTTP_MAX_TIMESTAMP_LEN + 1];
  if (!NormalizeTimestamp(in, false, normalized, sizeof(normalized))) {
    return ParseZonedTimestamp(in, out, out_size);
  }
  if (strlen(normalized) == 10) {
    snprintf(out, out_size, "%s 00:00:00", normalized);
  } else {
    snprintf(out, out_size, "%s", normalized);
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
      snprintf(err, err_size, "Invalid 'deleted' value '%.64s' (0, 1 or all)",
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
      snprintf(err, err_size, "Invalid 'date' value '%.64s' (YYYY-MM-DD)", buf);
      return false;
    }
    filter_where(f, "created_at_utc >= ?");
    filter_push_text(f, stamp);
    if (!NormalizeTimestamp(buf, true, stamp, sizeof(stamp))) {
      snprintf(err, err_size, "Invalid 'date' value '%.64s' (YYYY-MM-DD)", buf);
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
      // Scheduling, on start_date. The `start_date != ''` guard is what keeps
      // unscheduled rows - which hold '' and would compare below every real
      // stamp - out of a "scheduled after X" answer.
      {"scheduled_since", "(start_date != '' AND start_date >= ?)", false},
      {"scheduled_until", "(start_date != '' AND start_date <= ?)", true},
  };
  for (size_t i = 0; i < sizeof(ranges) / sizeof(ranges[0]); i++) {
    if (!query_get(query, ranges[i].param, buf, sizeof(buf))) {
      continue;
    }
    if (!NormalizeTimestamp(buf, ranges[i].upper_bound, stamp, sizeof(stamp))) {
      snprintf(err, err_size,
               "Invalid '%s' value '%.64s' (YYYY-MM-DD or "
               "'YYYY-MM-DD HH:MM:SS')",
               ranges[i].param, buf);
      return false;
    }
    filter_where(f, ranges[i].clause);
    filter_push_text(f, stamp);
  }

  // scheduled_date=YYYY-MM-DD asks "what is on that day", which for a span is
  // an *overlap* test and not an equality one: a block from 23:00 to 01:00
  // belongs to both days it touches, and one running 09:00-17:00 has no end
  // that matches the day it started on either. An entry with a start and no
  // end is treated as an instant, which is what COALESCE(NULLIF(...)) says.
  if (query_get(query, "scheduled_date", buf, sizeof(buf))) {
    char day_start[64], day_end[64];
    if (!NormalizeTimestamp(buf, false, day_start, sizeof(day_start)) ||
        !NormalizeTimestamp(buf, true, day_end, sizeof(day_end))) {
      // %.64s, not %s: `buf` is 512 bytes and `err` is 256, so a long enough
      // query value would truncate the explanation away and leave the client
      // holding half a sentence. The neighbours above still say %s - see
      // TODO.md; this is the shape they should take.
      snprintf(err, err_size,
               "Invalid 'scheduled_date' value '%.64s' (YYYY-MM-DD)", buf);
      return false;
    }
    filter_where(f, "(start_date != '' AND start_date <= ? AND "
                    "COALESCE(NULLIF(end_date, ''), start_date) >= ?)");
    filter_push_text(f, day_end);
    filter_push_text(f, day_start);
  }

  // scheduled=1/0 - "has a start_date at all". No bind: the clause is the
  // whole answer.
  if (query_get(query, "scheduled", buf, sizeof(buf))) {
    if (buf[0] == '\0' || strcasecmp(buf, "1") == 0 ||
        strcasecmp(buf, "true") == 0) {
      filter_where(f, "start_date != ''");
    } else if (strcasecmp(buf, "0") == 0 || strcasecmp(buf, "false") == 0) {
      filter_where(f, "(start_date IS NULL OR start_date = '')");
    } else {
      snprintf(err, err_size, "Invalid 'scheduled' value '%.64s' (0 or 1)",
               buf);
      return false;
    }
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
      // Unscheduled rows hold '', which sorts before every real stamp - so
      // `order=start&dir=asc` leads with everything that has no start date.
      // Pair it with `scheduled=1` to sort a schedule rather than the journal.
      {"start", "start_date"},
      {"start_date", "start_date"},
      {"end", "end_date"},
      {"end_date", "end_date"},
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
               "kind, start, end)",
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

  // Big enough for the whole of SQLFilter.where plus the fixed text around
  // it. It is sized off that buffer deliberately: growing where[] and leaving
  // this at 2048 would let snprintf truncate the statement, which prepares as
  // a syntax error rather than as the query that was asked for.
  char sql[4096];
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

// GET /dump - GET /entries without the page cap: the same filters, `order`/
// `dir` and `content=0`, every matching row in one streamed response. It is
// what the web UI's cold load asks for - the whole journal, bodies included,
// in one round trip instead of ~30 pages - and it is gzipped whenever the
// client offers gzip, which a browser always does.
//
// /entries has a row cap because its answer is built in the 1MB connection
// arena; this one never holds more than one row there. Each row's JSON is
// built at an arena mark, written to the stream and released before the next,
// so the journal's size is not bounded by anything here.
//
// `limit`/`offset` are refused rather than ignored: a client that sent them
// meant a page, and answering with everything would be answering something
// it did not ask.
static int HandleDump(int client_fd, Arena *arena, const char *query) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL);

  char probe[16];
  if (query_get(query, "limit", probe, sizeof(probe)) ||
      query_get(query, "offset", probe, sizeof(probe))) {
    return SendJSONError(client_fd, 400,
                         "/dump takes no limit/offset - use /entries to page");
  }
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
  bool include_content = true;
  if (!query_get_bool(query, "content", &include_content, &ok) && !ok) {
    return SendJSONError(client_fd, 400, "Invalid 'content' value (0 or 1)");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  char sql[4096];
  snprintf(sql, sizeof(sql),
           "SELECT " HTTP_ENTRY_COLUMNS " FROM entries %s %s;", filter.where,
           order_by);
  sqlite3_stmt *stmt;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  filter_bind(stmt, &filter);

  // The statement is read inside one implicit read transaction, so the rows
  // are a consistent snapshot even while another connection writes
  // - which is what lets a client treat this answer as "the journal as of
  // now" and sync forward from it.
  uint8_t zbuf[HTTP_GZIP_ZLIB_BYTES];
  HTTPBodyStream s;
  HTTPStreamBegin(&s, client_fd, 200, "application/json", NULL,
                  g_conn_accepts_gzip, zbuf, sizeof(zbuf));
  HTTPStreamWrite(&s, "[", 1);
  bool first = true, complete = true;
  int rows = 0, rc = SQLITE_DONE;
  while (!s.failed && (rc = sqlite3_step(stmt)) == SQLITE_ROW) {
    ArenaMark mark = arena_mark(arena);
    JSONBuf row;
    jsonbuf_init(&row, arena);
    if (!first) {
      jsonbuf_append(&row, ",");
    }
    first = false;
    AppendEntryJSON(&row, stmt, include_content);
    if (row.overflow) {
      // One row bigger than the whole connection arena. The 200 is already
      // out, so the only honest answer left is a truncated transfer.
      printf("HTTP /dump: entry %d does not fit the connection arena\n",
             sqlite3_column_int(stmt, 0));
      complete = false;
      arena_restore(arena, mark);
      break;
    }
    HTTPStreamWrite(&s, row.data, row.len);
    arena_restore(arena, mark);
    rows++;
  }
  if (complete && !s.failed && rc != SQLITE_DONE) {
    printf("HTTP /dump: step failed after %d rows: %s\n", rows,
           sqlite3_errmsg(db));
    complete = false;
  }
  if (complete) {
    HTTPStreamWrite(&s, "]", 1);
  }
  HTTPStreamEnd(&s, complete);
  printf("HTTP /dump: %d rows, %zu bytes -> %zu on the wire%s\n", rows,
         s.raw_bytes, s.wire_bytes, s.gzip ? " (gzip)" : "");

  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return complete && !s.failed ? 200 : 500;
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
                           const char *content_type, sqlite3_int64 *out_id) {
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
  // Empty means "the client did not say", and the INSERT below falls back to
  // now for whichever of the two is still empty.
  char created_at[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  char modified_at[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  // Unlike the two above, empty here is the *stored* value, not a stand-in
  // for a default: an entry nobody scheduled has no start and no end.
  char start_date[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  char end_date[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};

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

    // Backdating is opt-in and validated: a malformed timestamp is a 400,
    // not a silently-defaulted "now", because an importer that quietly lost
    // every date would be worse than one that stopped.
    char raw_ts[64];
    if (json_get_string(body, "created_at_utc", raw_ts, sizeof(raw_ts)) &&
        raw_ts[0] != '\0') {
      if (!NormalizeStoredTimestamp(raw_ts, created_at, sizeof(created_at))) {
        return SendJSONError(client_fd, 400,
                             "created_at_utc must be " HTTP_TIMESTAMP_SHAPES);
      }
    }
    if (json_get_string(body, "last_modified_at_utc", raw_ts, sizeof(raw_ts)) &&
        raw_ts[0] != '\0') {
      if (!NormalizeStoredTimestamp(raw_ts, modified_at, sizeof(modified_at))) {
        return SendJSONError(
            client_fd, 400,
            "last_modified_at_utc must be " HTTP_TIMESTAMP_SHAPES);
      }
    }

    // Scheduling. Same validation, same 400 on nonsense - but an explicitly
    // empty string is accepted and stored, because "" is how a client says
    // unscheduled rather than how it says nothing.
    //
    // No check that end_date is at or after start_date: a backwards range is
    // user input, which this file handles rather than asserts (AGENTS.md),
    // and a zero-length marker is a legitimate thing to want.
    struct {
      const char *key;
      char *out;
      size_t size;
    } spans[] = {
        {"start_date", start_date, sizeof(start_date)},
        {"end_date", end_date, sizeof(end_date)},
    };
    for (size_t i = 0; i < sizeof(spans) / sizeof(spans[0]); i++) {
      if (!json_get_string(body, spans[i].key, raw_ts, sizeof(raw_ts))) {
        continue;
      }
      if (raw_ts[0] == '\0') {
        continue; // already empty; nothing to normalize
      }
      if (!NormalizeStoredTimestamp(raw_ts, spans[i].out, spans[i].size)) {
        return SendJSONError(client_fd, 400,
                             "%s must be " HTTP_TIMESTAMP_SHAPES " "
                             "(or \"\" for unscheduled)",
                             spans[i].key);
      }
    }
  } else {
    content = body;
    strcpy(title, "HTTP Text Entry");
  }

  // A backdated create with no explicit modification time was last modified
  // when it was written, not when it was replayed into the database.
  if (modified_at[0] == '\0' && created_at[0] != '\0') {
    memcpy(modified_at, created_at, sizeof(modified_at));
  }

  if (title[0] == '\0') {
    strcpy(title, "HTTP Entry");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  sqlite3_stmt *stmt;
  // NULLIF turns the "client said nothing" empty string back into the
  // column's own default, so one statement covers both the normal create and
  // the backdated one without the two drifting apart.
  const char *sql =
      "INSERT INTO entries (kind, title, content, value_int, value_float, "
      "done_bool, created_at_utc, last_modified_at_utc, start_date, end_date) "
      "VALUES (?, ?, ?, ?, "
      "?, ?, COALESCE(NULLIF(?, ''), strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc')), COALESCE(NULLIF(?, ''), strftime('%Y-%m-%d %H:%M:%S', "
      "'now', 'utc')), ?, ?);";
  // The two scheduling columns are bound plainly, with no COALESCE: there is
  // no default to fall back to, and '' is the value meant.
  int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
  int status_code;
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, content, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 4, value_int);
    sqlite3_bind_double(stmt, 5, value_float);
    sqlite3_bind_int(stmt, 6, done_bool);
    sqlite3_bind_text(stmt, 7, created_at, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, modified_at, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, start_date, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, end_date, -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_DONE) {
      sqlite3_int64 insert_id = sqlite3_last_insert_rowid(db);
      if (out_id) {
        *out_id = insert_id;
      }
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

// Why a guarded write (if_modified) changed no row: 404 no such row, 409 the
// row deleted (or, for a restore, live), else 412 the stamp moved. Read
// after the write, so it can only be told apart, never undone: the write
// already changed nothing. Without a guard, a miss is a missing row.
static int GuardedMissAnswer(int client_fd, sqlite3 *db, int id,
                             const char *since, bool restore) {
  assert(client_fd >= 0 && db != NULL && id > 0 && since != NULL);
  if (since[0] == '\0') {
    return SendJSONError(client_fd, 404, "No entry with id %d", id);
  }
  sqlite3_stmt *stmt = NULL;
  bool found = false;
  int deleted = 0;
  char now_stamp[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (sqlite3_prepare_v2(db,
                         "SELECT last_modified_at_utc, deleted FROM entries "
                         "WHERE id = ?1;",
                         -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      const unsigned char *t = sqlite3_column_text(stmt, 0);
      snprintf(now_stamp, sizeof(now_stamp), "%s", t ? (const char *)t : "");
      deleted = sqlite3_column_int(stmt, 1);
      found = true;
    }
  }
  sqlite3_finalize(stmt);
  if (!found) {
    return SendJSONError(client_fd, 404, "No entry with id %d", id);
  }
  if (restore && !deleted) {
    return SendJSONError(client_fd, 409, "entry %d is not deleted", id);
  }
  if (!restore && deleted) {
    return SendJSONError(client_fd, 409, "entry %d is deleted", id);
  }
  return SendJSONError(client_fd, 412,
                       "entry %d changed since it was read (now %s, read %s)",
                       id, now_stamp, since);
}

// PUT/PATCH /entries/<id> - update whichever of kind, title, content,
// value_int, value_float, done_bool, deleted the body mentions. Both verbs
// behave the same (partial update): a PUT that only carries `content` must
// not blank the title, which is the only sane behaviour for a journal.
// Setting `"deleted": 0` is how a soft-deleted entry is restored.
//
// `if_modified` (optional; the steward must send it, lcars_logins.h) is the
// row's last_modified_at_utc as the writer read it, compared in the
// UPDATE's own WHERE as append's is: a row edited since is a 412 and stays
// as it is. With it the row must also be live (409 when deleted), unless
// the body is a restore (`"deleted": 0`), which needs a deleted row (409
// when live): a crew role sets fields on what it read, and a restore of a
// row someone else restored first is not a change of its.
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
  char created_at[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  // Left empty when the client sends "" - which is a real value here, meaning
  // unscheduled, rather than "the client said nothing".
  char start_date[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  char end_date[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  bool has_deleted = false;

  if (is_json) {
    if (json_get_string(body, "if_modified", since, sizeof(since)) &&
        since[0] == '\0') {
      return SendJSONError(client_fd, 400,
                           "if_modified is the row's last_modified_at_utc");
    }
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
      has_deleted = true;
      ADD_SET_COLUMN("deleted");
      filter_push_int(&values, deleted ? 1 : 0);
    }
    // Same reason POST accepts it: an importer replaying history needs to
    // correct a date it got wrong on a first pass without deleting the row.
    // last_modified_at_utc is deliberately *not* settable here - the UPDATE
    // below stamps it, and "when was this row last touched" would stop
    // meaning anything if a client could write it.
    char raw_created[64];
    if (json_get_string(body, "created_at_utc", raw_created,
                        sizeof(raw_created))) {
      if (!NormalizeStoredTimestamp(raw_created, created_at,
                                    sizeof(created_at))) {
        return SendJSONError(client_fd, 400,
                             "created_at_utc must be " HTTP_TIMESTAMP_SHAPES);
      }
      ADD_SET_COLUMN("created_at_utc");
      filter_push_text(&values, created_at);
    }

    // Scheduling. The one difference from every field above: an empty string
    // is a legal value and means "unschedule this", so it is stored rather
    // than rejected - that is the only way a client can take a date back off
    // an entry. Anything else still has to be a real timestamp.
    struct {
      const char *key;
      char *out;
      size_t size;
    } spans[] = {
        {"start_date", start_date, sizeof(start_date)},
        {"end_date", end_date, sizeof(end_date)},
    };
    for (size_t i = 0; i < sizeof(spans) / sizeof(spans[0]); i++) {
      char raw_span[64];
      if (!json_get_string(body, spans[i].key, raw_span, sizeof(raw_span))) {
        continue;
      }
      if (raw_span[0] != '\0' &&
          !NormalizeStoredTimestamp(raw_span, spans[i].out, spans[i].size)) {
        return SendJSONError(client_fd, 400,
                             "%s must be " HTTP_TIMESTAMP_SHAPES " "
                             "(or \"\" to unschedule)",
                             spans[i].key);
      }
      ADD_SET_COLUMN(spans[i].key);
      filter_push_text(&values, spans[i].out);
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
                         "value_int, value_float, done_bool, deleted, "
                         "created_at_utc, start_date, end_date)");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  // The guard: the stamp as read, and the deleted state the change needs
  bool restore = has_deleted && !deleted;
  const char *guard = since[0] == '\0' ? ""
                      : restore
                          ? " AND deleted = 1 AND last_modified_at_utc = ?"
                          : " AND (deleted IS NULL OR deleted = 0) AND "
                            "last_modified_at_utc = ?";
  char sql[1024];
  int sql_len = snprintf(sql, sizeof(sql),
                         "UPDATE entries SET %s, last_modified_at_utc = "
                         "strftime('%%Y-%%m-%%d %%H:%%M:%%S', 'now', 'utc') "
                         "WHERE id = ?%d%s;",
                         set_clause, values.bind_count + 1, guard);
  assert(sql_len > 0 && (size_t)sql_len < sizeof(sql));

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
  if (since[0] != '\0') {
    sqlite3_bind_text(stmt, next_param + 1, since, -1, SQLITE_STATIC);
  }

  int status;
  rc = sqlite3_step(stmt);
  if (rc != SQLITE_DONE) {
    printf("HTTP Database Error: Update failed: %s\n", sqlite3_errmsg(db));
    status =
        SendJSONError(client_fd, 400, "Update failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_changes(db) == 0) {
    status = GuardedMissAnswer(client_fd, db, id, since, restore);
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

// DELETE /entries/<id> - soft delete (deleted = 1), the same thing the web
// UI does. There is deliberately no hard-delete route: this database is a
// personal journal, and `deleted = 0` via PUT is the undo. A JSON body's
// `if_modified` (the steward's, required of it) guards it as PATCH's does:
// 412 when the row moved since it was read, 409 when it is deleted already.
static int HandleDeleteEntry(int client_fd, int id, const char *body,
                             const char *content_type) {
  assert(client_fd >= 0);
  assert(id > 0);
  assert(body != NULL && content_type != NULL);

  char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (strstr(content_type, "application/json") != NULL &&
      json_get_string(body, "if_modified", since, sizeof(since)) &&
      since[0] == '\0') {
    return SendJSONError(client_fd, 400,
                         "if_modified is the row's last_modified_at_utc");
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db,
      "UPDATE entries SET deleted = 1, last_modified_at_utc = "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?1 AND "
      "(deleted IS NULL OR deleted = 0) AND (?2 IS NULL OR "
      "last_modified_at_utc = ?2);",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare delete: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_int(stmt, 1, id);
  if (since[0] != '\0') {
    sqlite3_bind_text(stmt, 2, since, -1, SQLITE_STATIC);
  }

  int status;
  rc = sqlite3_step(stmt);
  if (rc != SQLITE_DONE) {
    status =
        SendJSONError(client_fd, 400, "Delete failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_changes(db) == 0 && since[0] != '\0') {
    status = GuardedMissAnswer(client_fd, db, id, since, false);
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

// POST /entries/<id>/append {"text": "...", "if_modified": "<stamp>"} - the
// text added at the end of the content, and nothing else touched. It exists
// for the crew notes' steward login (lcars_logins.h), whose rule is that the
// crew may add to the captain's entries but never change what is there: a
// PUT carries a whole new content, which the gate could only check by
// comparing prefixes, while this route cannot express a change at all.
// `if_modified` is the row's last_modified_at_utc as the writer read it, and
// the UPDATE's own WHERE compares it, so a row edited since (the captain
// typing in it) is a 412 and stays as he left it: the API's one
// compare-and-set, one statement, no window. Required, so a writer cannot
// forget it. Stamps are whole seconds; the runner adds its own quiet period
// (crew notes take nothing from an entry touched in the last 20s).
#define APPEND_TEXT_MAX (16 * 1024)
static int HandleAppendEntry(int client_fd, Arena *arena, int id,
                             const char *body, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(id > 0);
  assert(body != NULL && content_type != NULL);

  char *text = NULL;
  char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (strstr(content_type, "application/json") == NULL ||
      !json_get_string_arena(arena, body, "text", &text) || text == NULL ||
      text[0] == '\0' ||
      !json_get_string(body, "if_modified", since, sizeof(since)) ||
      since[0] == '\0') {
    return SendJSONError(
        client_fd, 400,
        "append takes a JSON body {\"text\", \"if_modified\"}: "
        "the text to add and the row's last_modified_at_utc");
  }
  if (strlen(text) > APPEND_TEXT_MAX) {
    return SendJSONError(client_fd, 413, "append text over %d bytes",
                         APPEND_TEXT_MAX);
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db,
      "UPDATE entries SET content = COALESCE(content, '') || ?1, "
      "last_modified_at_utc = strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') "
      "WHERE id = ?2 AND (deleted IS NULL OR deleted = 0) AND "
      "last_modified_at_utc = ?3;",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare append: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_text(stmt, 1, text, -1, SQLITE_STATIC);
  sqlite3_bind_int(stmt, 2, id);
  sqlite3_bind_text(stmt, 3, since, -1, SQLITE_STATIC);
  rc = sqlite3_step(stmt);
  bool changed = rc == SQLITE_DONE && sqlite3_changes(db) > 0;
  sqlite3_finalize(stmt);

  // What the row is now: its stamp for the answer, or why nothing was done
  int status = 0;
  char now_stamp[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  int deleted = 0;
  bool found = false;
  if (rc != SQLITE_DONE) {
    status =
        SendJSONError(client_fd, 400, "Append failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_prepare_v2(db,
                                "SELECT last_modified_at_utc, deleted FROM "
                                "entries WHERE id = ?1;",
                                -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      const unsigned char *t = sqlite3_column_text(stmt, 0);
      snprintf(now_stamp, sizeof(now_stamp), "%s", t ? (const char *)t : "");
      deleted = sqlite3_column_int(stmt, 1);
      found = true;
    }
    sqlite3_finalize(stmt);
  }
  sqlite3_close(db);
  if (status != 0) {
    return status;
  }
  if (!found) {
    return SendJSONError(client_fd, 404, "No entry with id %d", id);
  }
  if (changed) {
    char resp[160];
    int n = snprintf(resp, sizeof(resp),
                     "{\"status\":\"appended\",\"id\":%d,"
                     "\"last_modified_at_utc\":\"%s\"}",
                     id, now_stamp);
    assert(n > 0 && n < (int)sizeof(resp));
    return SendJSON(client_fd, 200, resp, (size_t)n);
  }
  if (deleted) {
    return SendJSONError(client_fd, 409, "entry %d is deleted", id);
  }
  return SendJSONError(client_fd, 412,
                       "entry %d changed since it was read (now %s, read %s)",
                       id, now_stamp, since);
}

// POST /entries/<id>/title {"title": "...", "if_modified": "<stamp>"} - the
// title set, last_modified_at_utc moved, and nothing else touched. The
// steward's one change to an existing row (the captain's word, 2026-10-15:
// the yeoman may title his entries, never edit their text), for the same
// reason append is a route of its own: a PUT could carry any column, while
// this one cannot name another. `if_modified` works as append's does, but
// the old title must come back too (old_title, so the caller can offer
// Undo), so the read and the UPDATE share one IMMEDIATE transaction: no
// writer can land between them, and the UPDATE's WHERE still compares the
// stamp itself. The main login may use it as well. A title is one line of
// at most ENTRY_TITLE_MAX bytes - what PUT's 512-byte buffer keeps, which
// is the editor's limit; here an over-long one is refused, not cut.
#define ENTRY_TITLE_MAX 511
static int HandleTitleEntry(int client_fd, Arena *arena, int id,
                            const char *body, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(id > 0);
  assert(body != NULL && content_type != NULL);

  char *title = NULL;
  char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (strstr(content_type, "application/json") == NULL ||
      !json_get_string_arena(arena, body, "title", &title) || title == NULL ||
      !json_get_string(body, "if_modified", since, sizeof(since)) ||
      since[0] == '\0') {
    return SendJSONError(
        client_fd, 400,
        "title takes a JSON body {\"title\", \"if_modified\"}: "
        "the new title and the row's last_modified_at_utc");
  }
  bool blank = true;
  for (const char *c = title; *c; c++) {
    if (*c == '\n' || *c == '\r') {
      return SendJSONError(client_fd, 400, "a title is one line");
    }
    if (!isspace((unsigned char)*c)) {
      blank = false;
    }
  }
  if (blank) {
    return SendJSONError(client_fd, 400, "the title is empty");
  }
  if (strlen(title) > ENTRY_TITLE_MAX) {
    return SendJSONError(client_fd, 400, "a title is at most %d bytes",
                         ENTRY_TITLE_MAX);
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 503, "the journal is busy: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }

  // The row as it stands: its title for old_title, or why nothing is done
  int status = 0;
  char *old_title = NULL;
  char now_stamp[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT title, last_modified_at_utc, deleted FROM "
                         "entries WHERE id = ?1;",
                         -1, &stmt, NULL) != SQLITE_OK) {
    status = SendJSONError(client_fd, 500, "Failed to prepare read: %s",
                           sqlite3_errmsg(db));
  } else {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) != SQLITE_ROW) {
      status = SendJSONError(client_fd, 404, "No entry with id %d", id);
    } else if (sqlite3_column_int(stmt, 2) != 0) {
      status = SendJSONError(client_fd, 409, "entry %d is deleted", id);
    } else {
      const unsigned char *t = sqlite3_column_text(stmt, 0);
      size_t n = t ? strlen((const char *)t) : 0;
      old_title = arena_alloc(arena, n + 1);
      memcpy(old_title, t ? (const char *)t : "", n);
      old_title[n] = '\0';
      const unsigned char *m = sqlite3_column_text(stmt, 1);
      snprintf(now_stamp, sizeof(now_stamp), "%s", m ? (const char *)m : "");
    }
    sqlite3_finalize(stmt);
  }

  if (status == 0) {
    int rc = sqlite3_prepare_v2(
        db,
        "UPDATE entries SET title = ?1, "
        "last_modified_at_utc = strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') "
        "WHERE id = ?2 AND (deleted IS NULL OR deleted = 0) AND "
        "last_modified_at_utc = ?3;",
        -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
      status = SendJSONError(client_fd, 500, "Failed to prepare title: %s",
                             sqlite3_errmsg(db));
    } else {
      sqlite3_bind_text(stmt, 1, title, -1, SQLITE_STATIC);
      sqlite3_bind_int(stmt, 2, id);
      sqlite3_bind_text(stmt, 3, since, -1, SQLITE_STATIC);
      rc = sqlite3_step(stmt);
      sqlite3_finalize(stmt);
      if (rc != SQLITE_DONE) {
        status = SendJSONError(client_fd, 400, "Title failed: %s",
                               sqlite3_errmsg(db));
      } else if (sqlite3_changes(db) == 0) {
        status = SendJSONError(
            client_fd, 412,
            "entry %d changed since it was read (now %s, read %s)", id,
            now_stamp, since);
      }
    }
  }

  // The row as it is now, with the title it had
  JSONBuf out;
  jsonbuf_init(&out, arena);
  if (status == 0 && sqlite3_prepare_v2(db,
                                        "SELECT " HTTP_ENTRY_COLUMNS
                                        " FROM entries WHERE id = ?1;",
                                        -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      AppendEntryJSON(&out, stmt, true);
    }
    sqlite3_finalize(stmt);
  }
  if (status == 0 && (out.len == 0 || out.data[out.len - 1] != '}')) {
    status = SendJSONError(client_fd, 500, "entry %d not read back", id);
  }
  if (status == 0 &&
      sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    status = SendJSONError(client_fd, 500, "Title not committed: %s",
                           sqlite3_errmsg(db));
  }
  if (status != 0) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    sqlite3_close(db);
    return status;
  }
  sqlite3_close(db);
  out.len--; // the row's closing brace, reopened for old_title
  jsonbuf_append(&out, ",\"old_title\":");
  jsonbuf_append_json_string(&out, old_title);
  jsonbuf_append(&out, "}");
  return SendJSONBuf(client_fd, &out);
}

// POST /entries/<id>/end {"end": "<stamp>", "if_modified": "<stamp>"} - an
// open entry closed: its end_date set where it had none, last_modified
// moved, nothing else touched. The steward's second change to an existing
// row (the captain's word, 2026-10-16: the crew may close his open sleep or
// drive), a route of its own for title's reason: it can name no other
// column, and it cannot move an end already set - a row with one is a 409,
// so a crew role can close an entry but never re-date it. The end must be
// after the start, and the row must have a start: an end alone is not a
// span. `end` is UTC like every stored stamp (NormalizeStoredTimestamp; the
// runner converts the captain's local time). The read and the UPDATE share
// one IMMEDIATE transaction, as HandleTitleEntry's do, and the answer is
// the row with old_end_date (always "" today, kept for the Undo record's
// shape). The main login may use it as well.
static int HandleEndEntry(int client_fd, Arena *arena, int id, const char *body,
                          const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(id > 0);
  assert(body != NULL && content_type != NULL);

  char raw_end[64] = {0};
  char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (strstr(content_type, "application/json") == NULL ||
      !json_get_string(body, "end", raw_end, sizeof(raw_end)) ||
      raw_end[0] == '\0' ||
      !json_get_string(body, "if_modified", since, sizeof(since)) ||
      since[0] == '\0') {
    return SendJSONError(client_fd, 400,
                         "end takes a JSON body {\"end\", \"if_modified\"}: "
                         "the end (UTC) and the row's last_modified_at_utc");
  }
  char end[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  if (!NormalizeStoredTimestamp(raw_end, end, sizeof(end))) {
    return SendJSONError(client_fd, 400, "end must be " HTTP_TIMESTAMP_SHAPES);
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 503, "the journal is busy: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }

  // The row as it stands: open, started before `end`, or why nothing is done
  int status = 0;
  char now_stamp[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT start_date, end_date, last_modified_at_utc, "
                         "deleted FROM entries WHERE id = ?1;",
                         -1, &stmt, NULL) != SQLITE_OK) {
    status = SendJSONError(client_fd, 500, "Failed to prepare read: %s",
                           sqlite3_errmsg(db));
  } else {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) != SQLITE_ROW) {
      status = SendJSONError(client_fd, 404, "No entry with id %d", id);
    } else {
      const char *start = (const char *)sqlite3_column_text(stmt, 0);
      const char *old_end = (const char *)sqlite3_column_text(stmt, 1);
      const char *m = (const char *)sqlite3_column_text(stmt, 2);
      snprintf(now_stamp, sizeof(now_stamp), "%s", m ? m : "");
      if (sqlite3_column_int(stmt, 3) != 0) {
        status = SendJSONError(client_fd, 409, "entry %d is deleted", id);
      } else if (old_end && old_end[0]) {
        status = SendJSONError(client_fd, 409,
                               "entry %d has an end already (%s): an end is "
                               "set once, never moved",
                               id, old_end);
      } else if (!start || !start[0]) {
        status = SendJSONError(client_fd, 400,
                               "entry %d has no start: an end closes a span "
                               "that began",
                               id);
      } else if (strcmp(end, start) <= 0) {
        status = SendJSONError(
            client_fd, 400, "the end %s is not after the start %s", end, start);
      }
    }
    sqlite3_finalize(stmt);
  }

  if (status == 0) {
    int rc = sqlite3_prepare_v2(
        db,
        "UPDATE entries SET end_date = ?1, "
        "last_modified_at_utc = strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') "
        "WHERE id = ?2 AND (deleted IS NULL OR deleted = 0) AND "
        "(end_date IS NULL OR end_date = '') AND last_modified_at_utc = ?3;",
        -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
      status = SendJSONError(client_fd, 500, "Failed to prepare end: %s",
                             sqlite3_errmsg(db));
    } else {
      sqlite3_bind_text(stmt, 1, end, -1, SQLITE_STATIC);
      sqlite3_bind_int(stmt, 2, id);
      sqlite3_bind_text(stmt, 3, since, -1, SQLITE_STATIC);
      rc = sqlite3_step(stmt);
      sqlite3_finalize(stmt);
      if (rc != SQLITE_DONE) {
        status =
            SendJSONError(client_fd, 400, "End failed: %s", sqlite3_errmsg(db));
      } else if (sqlite3_changes(db) == 0) {
        status = SendJSONError(
            client_fd, 412,
            "entry %d changed since it was read (now %s, read %s)", id,
            now_stamp, since);
      }
    }
  }

  // The row as it is now
  JSONBuf out;
  jsonbuf_init(&out, arena);
  if (status == 0 && sqlite3_prepare_v2(db,
                                        "SELECT " HTTP_ENTRY_COLUMNS
                                        " FROM entries WHERE id = ?1;",
                                        -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      AppendEntryJSON(&out, stmt, true);
    }
    sqlite3_finalize(stmt);
  }
  if (status == 0 && (out.len == 0 || out.data[out.len - 1] != '}')) {
    status = SendJSONError(client_fd, 500, "entry %d not read back", id);
  }
  if (status == 0 &&
      sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    status = SendJSONError(client_fd, 500, "End not committed: %s",
                           sqlite3_errmsg(db));
  }
  if (status != 0) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    sqlite3_close(db);
    return status;
  }
  sqlite3_close(db);
  out.len--; // the row's closing brace, reopened for old_end_date
  jsonbuf_append(&out, ",\"old_end_date\":\"\"}");
  return SendJSONBuf(client_fd, &out);
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

  // Sized off SQLFilter.where, for the reason given at the /entries SELECT.
  char sql[4096];
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

  // Two literals joined here, not one: C99 promises string literals only up
  // to 4095 characters (-Woverlength-strings), and the list outgrew that.
  static const char head[] =
      "{\"service\":\"lcars\",\"routes\":["
      "{\"method\":\"GET\",\"path\":\"/health\",\"auth\":false,"
      "\"description\":\"liveness probe\"},"
      "{\"method\":\"GET\",\"path\":\"/entries\","
      "\"description\":\"list entries\","
      "\"params\":[\"kind\",\"q\",\"date\",\"since\",\"until\","
      "\"modified_since\",\"modified_until\",\"scheduled\","
      "\"scheduled_date\",\"scheduled_since\",\"scheduled_until\","
      "\"done\",\"deleted\",\"min_id\","
      "\"max_id\",\"order\",\"dir\",\"limit\",\"offset\",\"content\"]},"
      "{\"method\":\"POST\",\"path\":\"/entries\","
      "\"description\":\"create entry (kind,title,content,value_int,"
      "value_float,done_bool,created_at_utc,last_modified_at_utc,"
      "start_date,end_date)\"},"
      "{\"method\":\"GET\",\"path\":\"/entries/{id}\","
      "\"description\":\"one entry\"},"
      "{\"method\":\"PUT|PATCH\",\"path\":\"/entries/{id}\","
      "\"description\":\"partial update (also created_at_utc, start_date, "
      "end_date); deleted=0 restores; \\\"\\\" unschedules; if_modified "
      "guards it (412 moved, 409 deleted)\"},"
      "{\"method\":\"DELETE\",\"path\":\"/entries/{id}\","
      "\"description\":\"soft delete; a JSON body's if_modified guards it\"},"
      "{\"method\":\"GET|PUT\",\"path\":\"/entries/{id}/caldav\","
      "\"description\":\"a task's CalDAV side: the VTODO, its ETag and the "
      "kept lines (DUE, VALARM, RRULE...); PUT {extra_ical, etag} replaces "
      "those lines\"},"
      "{\"method\":\"GET|POST\",\"path\":\"/entries/{id}/media\","
      "\"description\":\"attachments; POST the raw file (any type: its "
      "Content-Type, ?name=original) to store it on the NAS\"},"
      "{\"method\":\"GET\",\"path\":\"/media\","
      "\"description\":\"every live entry's attachments, one list\"},"
      "{\"method\":\"DELETE\",\"path\":\"/entries/{id}/media/{media_id}\","
      "\"description\":\"soft delete an attachment (file kept)\"},"
      "{\"method\":\"POST\",\"path\":\"/tapes/{token}\","
      "\"description\":\"stage a recording slice by slice (?off=<bytes>, "
      "raw body); then POST /entries/{id}/media?tape={token} with no body "
      "attaches it\"},"
      "{\"method\":\"GET|HEAD\",\"path\":\"/media/{path}\","
      "\"description\":\"an attachment's file (a row's path), with Range; "
      "from the VPS's cache when held, else the NAS. No auth from "
      "loopback (tailscale serve)\"},"
      "{\"method\":\"GET\",\"path\":\"/reports\","
      "\"description\":\"the reports scripts/report.py published, newest "
      "first: {path, title, type, bytes, published_utc}; open /{path}\"},"
      "{\"method\":\"POST\",\"path\":\"/transcribe\","
      "\"description\":\"speech to text; body is raw PCM "
      "(16kHz mono s16le), answers {text,bytes,duration_ms}\"},"
      "{\"method\":\"POST\",\"path\":\"/chat\","
      "\"description\":\"ask Claude (lcars skill, lcars-cli only); "
      "body {message,session_id?,model?: sonnet|haiku|opus|fable,"
      "attachments?: [{path,name,mime,bytes}] from /chat/media}, answers a "
      "text/event-stream of claude "
      "stream-json lines ending in {type:lcars_exit}\"},"
      "{\"method\":\"POST\",\"path\":\"/chat/media?name={filename}\","
      "\"description\":\"a file for a chat message; raw body, up to 25 MB, "
      "stored at media/chat/YYYY/MM/; answers {path,url,name,mime,bytes} "
      "for the message's attachments\"},"
      "{\"method\":\"GET\",\"path\":\"/events\","
      "\"description\":\"text/event-stream, data {seq} on connect and on "
      "every change to the database by any writer; then sync with /dump\"},"
      "{\"method\":\"GET|HEAD\",\"path\":\"/ui/...\","
      "\"description\":\"the web UI; any page path (/ui/tasks, "
      "/ui/entry/{id}) answers with the app. No auth from loopback\"},"
      "{\"method\":\"POST\",\"path\":\"/ask\","
      "\"description\":\"the same agent for a voice client (an iOS "
      "Shortcut): body as /chat, answers one JSON {text,session_id,error?} "
      "worded to be spoken\"},"
      "{\"method\":\"GET|POST\",\"path\":\"/engineer/{name}/...\","
      "\"description\":\"deck crew who change LCARS (scripts/engineer.py): "
      "poll, start, say, key, stop, deploy, a role's brief, "
      "/engineer/rollback, /engineer/queue. Off unless "
      "LCARS_ENGINEER=1; tailnet only, and X-LCARS-Engineer-Key\"},"
      "{\"method\":\"GET\",\"path\":\"/embeddings\","
      "\"description\":\"every live entry's vector (int8, base64) for "
      "the star chart; ?since=<mark> for what changed\"},"
      "{\"method\":\"POST\",\"path\":\"/embed\","
      "\"description\":\"one text's vector, same encoding: body {text}\"},"
      "{\"method\":\"POST\",\"path\":\"/say\","
      "\"description\":\"the deck crew's voice: {text, voice} answers "
      "audio/mpeg as it is made; GET says {provider}; GET /say/token a ~30s "
      "Deepgram key for listening\"},";
  static const char tail[] =
      "{\"method\":\"GET\",\"path\":\"/maps\","
      "\"description\":\"the web UI's map settings for plotting a "
      "course: {mapy_key} from $LCARS_MAPY_KEY, or null\"},"
      "{\"method\":\"GET\",\"path\":\"/features\","
      "\"description\":\"what this server can do: {features:[{name,on,"
      "needs,note}]}; needs, the settings an off one lacks (names, never "
      "values). The owner login only\"},"
      "{\"method\":\"GET\",\"path\":\"/dump\","
      "\"description\":\"every entry matching the /entries filters in one "
      "streamed (gzip if accepted) response; no limit/offset\"},"
      "{\"method\":\"GET\",\"path\":\"/metrics\","
      "\"description\":\"Prometheus text: lcars_reading{kind}, its "
      "_timestamp_seconds, lcars_entries_total{kind}. No auth from "
      "loopback\"},"
      "{\"method\":\"GET\",\"path\":\"/kinds\","
      "\"description\":\"distinct kinds with counts\"},"
      "{\"method\":\"GET|PUT\",\"path\":\"/kinds/roles\","
      "\"description\":\"the kind each feature's role writes: {roles:[{role,"
      "what,kind,kinds,default,list,set,name,rows}],entry,error}; PUT "
      "{<role>:{kind,name}|null}, the owner's login only\"},"
      "{\"method\":\"GET\",\"path\":\"/stats\","
      "\"description\":\"totals, accepts the same filters as /entries\"},"
      "{\"method\":\"PROPFIND|REPORT|PUT|DELETE|MOVE|MKCALENDAR|PROPPATCH\","
      "\"path\":\"/caldav/calendars/<list>/\","
      "\"description\":\"CalDAV VTODO lists, one per task/task_* kind "
      "(tasks/ is kind=task); point Apple Reminders at this server\"}"
      "]}";
  char body[sizeof(head) + sizeof(tail)];
  memcpy(body, head, sizeof(head) - 1);
  memcpy(body + sizeof(head) - 1, tail, sizeof(tail));
  return SendJSON(client_fd, 200, body, sizeof(body) - 2);
}

// GET /maps: what the web UI's course plotter needs to draw maps and ask
// for routes. Mapy.com's tiles, routing, geocoding and elevation all want an
// API key on every request, and the page calls them itself (a tile proxy
// would send every map tile through this box's one uplink), so the key is
// handed to a page that has already passed Basic auth rather than written
// into lcars-ui/, which is public in the repo. With no key the page falls
// back to OpenStreetMap tiles and BRouter, which need none. The key is only
// passed on when it is made of the characters Mapy.com issues (base64url), so
// it can be written into the JSON unescaped.
static int HandleMaps(int client_fd) {
  const char *key = getenv("LCARS_MAPY_KEY");
  bool ok = key && key[0] && strlen(key) <= 128;
  for (const char *c = key; ok && *c; c++) {
    ok = isalnum((unsigned char)*c) || *c == '_' || *c == '-';
  }
  char body[256];
  int len = ok ? snprintf(body, sizeof(body), "{\"mapy_key\":\"%s\"}", key)
               : snprintf(body, sizeof(body), "{\"mapy_key\":null}");
  assert(len > 0 && (size_t)len < sizeof(body));
  return SendJSON(client_fd, 200, body, (size_t)len);
}

// Kinds by role: the role table, KindFor, GET/PUT /kinds/roles. Ahead of
// the modules that ask for a role's kind (CalDAV, chat, the logins, Strava).
#define LCARS_KINDS_IMPLEMENTATION
#include "lcars_kinds.h"

// The CalDAV surface is a module of this file rather than a standalone
// header: it builds on the response, buffer and header helpers above, and is
// dispatched from the router below.
#define LCARS_CALDAV_IMPLEMENTATION
#include "lcars_caldav.h"

// POST /chat - Claude Code as a subprocess, streamed back as SSE. A module
// for the same reason CalDAV is one.
#define LCARS_CHAT_IMPLEMENTATION
#include "lcars_chat.h"

// GET /events - "the journal changed", as Server-Sent Events, from a thread
// watching the database. After lcars_chat.h, whose send helper it uses.
#define LCARS_EVENTS_IMPLEMENTATION
#include "lcars_events.h"

// Photos, video and audio attached to entries, stored on the NAS. A module
// for the same reason; its upload route is dispatched ahead of the body read.
#define LCARS_MEDIA_IMPLEMENTATION
#include "lcars_media.h"

// The web UI's own files, every page of it answered with index.html. After
// lcars_media.h, whose loopback test and file sender it uses.
#define LCARS_UI_FILES_IMPLEMENTATION
#include "lcars_ui_files.h"

// Every entry as a vector, for the web UI's star chart and "related". A
// module for the same reason; it also runs the indexer thread.
#define LCARS_EMBED_IMPLEMENTATION
#include "lcars_embed.h"

// Crew in the deck who change LCARS itself: a thin, heavily gated layer over
// scripts/engineer.py. After lcars_media.h, whose loopback test it uses.
#define LCARS_ENGINEER_IMPLEMENTATION
#include "lcars_engineer.h"
#define LCARS_LOGINS_IMPLEMENTATION
#include "lcars_logins.h"

// POST /say - the deck crew's voices, relayed from a text-to-speech service.
// After lcars_chat.h, whose POLLRDHUP it uses.
#define LCARS_SAY_IMPLEMENTATION
#include "lcars_say.h"

// GET /metrics - the readings and counts in Prometheus' text format, for
// the Grafana Alloy on the box. Uses OpenHTTPDB and JSONBuf from above.
#define LCARS_METRICS_IMPLEMENTATION
#include "lcars_metrics.h"

// GET /features - what this server can do and what it lacks, for the web
// UI's notes. After lcars_say.h and lcars_embed.h, whose state it reads.
#define LCARS_FEATURES_IMPLEMENTATION
#include "lcars_features.h"

// ---------------------------------------------------------------------------
// Idempotent creates
// ---------------------------------------------------------------------------

// POST /entries with an Idempotency-Key header: the same key twice is the
// same entry, answered with the id it already got.
//
// The web UI's offline outbox replays a create when the link comes back,
// and the browser can deliver one POST twice beneath anything the page sees
// (Chromium resends a request whose reused connection drops before the
// answer, and a phone changing networks is exactly that). Two identical
// entries in a journal are worse than a lost retry, and nothing in a row
// says which create made it, so the page names each create once - a key
// minted at the first attempt and kept with the outbox op across reloads -
// and the server remembers the last IDEM_SLOTS keys it has seen. In memory
// only: a restart forgets them, which costs only the protection for a
// create in flight across the restart.
//
// The mutex is held across the insert, so a resend that arrives while the
// first is still being written waits for it rather than racing it.
//
// A create with no key gets a weaker guard: twins. The captain's
// quick-capture Shortcut sends no key and sometimes posts one entry twice
// in the same second (the yeoman found a pair a night), so a keyless POST
// whose body is byte for byte one this login had accepted less than
// DEDUPE_WINDOW_S ago is answered with that first row - the same 200 and
// body, plus "X-LCARS-Deduped: 1" - instead of inserting again. The window
// runs from the first insert and is not extended by a twin; after it the
// same body is a new entry, as it always was, because writing the same
// line twice on purpose is legitimate and only a retry lands this fast.
// The login is the Authorization value (hashed; none when auth is off), so
// two logins never answer for each other, and the content type is part of
// the body's hash (the same bytes as text and as JSON are different
// entries). A slot holds 64-bit FNV-1a hashes and the length, not the body:
// a false match needs a hash collision within two seconds. A keyed create
// never looks at these slots - the key rules - and every create now takes
// the mutex, which serializes inserts that SQLite serializes anyway.
#define IDEM_SLOTS 256
#define IDEM_KEY_MAX 64

typedef struct IdemSlot {
  char key[IDEM_KEY_MAX + 1];
  sqlite3_int64 id;
} IdemSlot;
static IdemSlot g_idem[IDEM_SLOTS];
static int g_idem_next = 0;
static pthread_mutex_t g_idem_mu = PTHREAD_MUTEX_INITIALIZER;

#define DEDUPE_SLOTS 32
#define DEDUPE_WINDOW_S 2.0

typedef struct DedupeSlot {
  uint64_t body_hash;  // content type, then the body's bytes
  uint64_t login_hash; // the Authorization header's value
  size_t body_len;
  double at; // GetTimeSeconds() when it was inserted
  sqlite3_int64 id;
} DedupeSlot;
static DedupeSlot g_dedupe[DEDUPE_SLOTS];
static int g_dedupe_next = 0;

static uint64_t Fnv1a(uint64_t h, const char *p, size_t n) {
  assert(p != NULL || n == 0);
  for (size_t i = 0; i < n; i++) {
    h ^= (unsigned char)p[i];
    h *= 1099511628211ULL;
  }
  return h;
}
#define FNV1A_SEED 14695981039346656037ULL

// The line's value up to its CR/LF, or "" for no header.
static uint64_t HeaderHash(const char *req_buf, const char *name) {
  const char *v = find_header_value(req_buf, name);
  size_t n = 0;
  while (v && v[n] && v[n] != '\r' && v[n] != '\n') {
    n++;
  }
  return Fnv1a(FNV1A_SEED, v ? v : "", n);
}

// A keyless create (see above). Called with nothing held.
static int HandlePostEntryDeduped(int client_fd, Arena *arena, const char *body,
                                  const char *content_type,
                                  const char *req_buf) {
  assert(body != NULL && content_type != NULL && req_buf != NULL);
  size_t body_len = strlen(body);
  uint64_t body_hash =
      Fnv1a(FNV1A_SEED, content_type, strlen(content_type) + 1);
  body_hash = Fnv1a(body_hash, body, body_len);
  uint64_t login_hash = HeaderHash(req_buf, "Authorization:");

  pthread_mutex_lock(&g_idem_mu);
  double now = GetTimeSeconds();
  for (int i = 0; i < DEDUPE_SLOTS; i++) {
    const DedupeSlot *d = &g_dedupe[i];
    if (d->id > 0 && now - d->at < DEDUPE_WINDOW_S &&
        d->body_hash == body_hash && d->login_hash == login_hash &&
        d->body_len == body_len) {
      sqlite3_int64 id = d->id;
      pthread_mutex_unlock(&g_idem_mu);
      // Exactly HandlePostEntry's answer: a client that cannot tell the
      // twin from the first must not be handed anything new to parse.
      char resp[128];
      int n = snprintf(resp, sizeof(resp),
                       "{\"status\":\"success\",\"id\":%lld}", (long long)id);
      assert(n > 0 && n < (int)sizeof(resp));
      printf("HTTP: keyless twin of entry %lld answered, not inserted\n",
             (long long)id);
      return SendHTTPResponseEx(client_fd, 200, "application/json",
                                "X-LCARS-Deduped: 1\r\n", resp, (size_t)n);
    }
  }
  sqlite3_int64 id = 0;
  int status = HandlePostEntry(client_fd, arena, body, content_type, &id);
  if (id > 0) {
    DedupeSlot *d = &g_dedupe[g_dedupe_next];
    d->body_hash = body_hash;
    d->login_hash = login_hash;
    d->body_len = body_len;
    d->at = GetTimeSeconds(); // from the insert, not from the arrival
    d->id = id;
    g_dedupe_next = (g_dedupe_next + 1) % DEDUPE_SLOTS;
  }
  assert(g_dedupe_next >= 0 && g_dedupe_next < DEDUPE_SLOTS);
  pthread_mutex_unlock(&g_idem_mu);
  return status;
}

// The header's value, if it is a plausible key ([A-Za-z0-9_-], 8..64);
// anything else is treated as no key rather than refused.
static bool IdemKeyFrom(const char *req_buf, char *out, size_t cap) {
  assert(req_buf != NULL && out != NULL && cap > IDEM_KEY_MAX);
  out[0] = '\0';
  const char *v = find_header_value(req_buf, "Idempotency-Key:");
  if (!v) {
    return false;
  }
  size_t n = 0;
  while (v[n] && v[n] != '\r' && v[n] != '\n') {
    char c = v[n];
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '-' || c == '_';
    if (!ok || n >= IDEM_KEY_MAX) {
      return false;
    }
    n++;
  }
  if (n < 8) {
    return false;
  }
  memcpy(out, v, n);
  out[n] = '\0';
  return true;
}

static int HandlePostEntryKeyed(int client_fd, Arena *arena, const char *body,
                                const char *content_type, const char *req_buf) {
  assert(client_fd >= 0 && req_buf != NULL);
  char key[IDEM_KEY_MAX + 1];
  if (!IdemKeyFrom(req_buf, key, sizeof(key))) {
    return HandlePostEntryDeduped(client_fd, arena, body, content_type,
                                  req_buf);
  }
  pthread_mutex_lock(&g_idem_mu);
  for (int i = 0; i < IDEM_SLOTS; i++) {
    if (g_idem[i].id > 0 && strcmp(g_idem[i].key, key) == 0) {
      sqlite3_int64 id = g_idem[i].id;
      pthread_mutex_unlock(&g_idem_mu);
      char resp[128];
      int n = snprintf(resp, sizeof(resp),
                       "{\"status\":\"success\",\"id\":%lld,\"replayed\":true}",
                       (long long)id);
      assert(n > 0 && n < (int)sizeof(resp));
      return SendJSON(client_fd, 200, resp, (size_t)n);
    }
  }
  sqlite3_int64 id = 0;
  int status = HandlePostEntry(client_fd, arena, body, content_type, &id);
  if (id > 0) {
    IdemSlot *slot = &g_idem[g_idem_next];
    snprintf(slot->key, sizeof(slot->key), "%s", key);
    slot->id = id;
    g_idem_next = (g_idem_next + 1) % IDEM_SLOTS;
  }
  assert(g_idem_next >= 0 && g_idem_next < IDEM_SLOTS);
  pthread_mutex_unlock(&g_idem_mu);
  return status;
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

// "/entries/<id><suffix>", the id extracted
static bool MatchEntrySuffixPath(const char *path, const char *suffix,
                                 int *out_id) {
  assert(path != NULL && suffix != NULL && out_id != NULL);
  const char *prefix = "/entries/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *id_str = path + prefix_len;
  char *end;
  long value = strtol(id_str, &end, 10);
  if (end == id_str || value <= 0 || value > INT_MAX ||
      strcmp(end, suffix) != 0) {
    return false;
  }
  *out_id = (int)value;
  return true;
}

// "/entries/<id>/append", the id extracted (HandleAppendEntry)
static bool MatchEntryAppendPath(const char *path, int *out_id) {
  return MatchEntrySuffixPath(path, "/append", out_id);
}

// "/entries/<id>/title", the id extracted (HandleTitleEntry)
static bool MatchEntryTitlePath(const char *path, int *out_id) {
  return MatchEntrySuffixPath(path, "/title", out_id);
}

// "/entries/<id>/end", the id extracted (HandleEndEntry)
static bool MatchEntryEndPath(const char *path, int *out_id) {
  return MatchEntrySuffixPath(path, "/end", out_id);
}

// A header's value for the request log: CopyHeaderValue's copy, then
// anything outside printable ASCII as '?'. The value is whatever the client
// sent, so it is bounded and defanged before it reaches the journal. Empty
// when the header is absent.
static void HeaderForLog(const char *req_buf, const char *name, char *out,
                         size_t out_size) {
  assert(out != NULL && out_size > 1);
  CopyHeaderValue(req_buf, name, out, out_size);
  for (char *c = out; *c; c++) {
    if ((unsigned char)*c < 0x20 || (unsigned char)*c >= 0x7f) {
      *c = '?';
    }
  }
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

// The patch kinds (docs/design/architect.md 2.2): an entry of kind deck_patch
// or ui_patch is code the captain's pages run with everything they hold (the
// password, the engineer key), so only the pages may write one. A page says
// so with X-LCARS-Client on every request; lcars-cli sends none, and it is
// the only tool of the /chat agents, who write as the captain and read the
// web - a page found by a search must not be able to make the computer write
// one. A write that would create a patch entry (the body's kind), or change
// one (the row's kind: PUT, PATCH, an append, a title, an end, a CalDAV PUT)
// without the header is refused. DELETE is let through: soft, restorable,
// and it only ever takes a patch away. An engineer with curl can still send
// the header; engineers have the shell already. The /caldav collections are
// not looked into: their clients hold the password anyway, and lcars-cli
// speaks no CalDAV.
static bool IsPatchKind(const char *kind) {
  assert(kind != NULL);
  return strcmp(kind, "deck_patch") == 0 || strcmp(kind, "ui_patch") == 0;
}

static int PatchKindRefuse(int client_fd) {
  assert(client_fd >= 0);
  return SendJSONError(client_fd, 403,
                       "deck_patch and ui_patch entries are written by the "
                       "LCARS pages only (X-LCARS-Client), never by lcars-cli "
                       "or a chat agent");
}

// True when the request may go on; false with *status answered
static bool PatchKindAllowed(int client_fd, const char *req_buf,
                             const char *method, const char *path,
                             const char *body, const char *content_type,
                             int *status) {
  assert(req_buf != NULL && method != NULL && path != NULL);
  assert(status != NULL);
  bool writes = strcmp(method, "POST") == 0 || strcmp(method, "PUT") == 0 ||
                strcmp(method, "PATCH") == 0;
  if (!writes || find_header_value(req_buf, "X-LCARS-Client:") != NULL) {
    return true;
  }
  // the kind a create names, or a PUT/PATCH moves a row to: read as the
  // handlers read it (json_get_string into 128 bytes), so the gate and the
  // handler never disagree on what the body says
  char kind[LIMITED_KIND_MAX] = {0};
  if (body != NULL && content_type != NULL &&
      strstr(content_type, "application/json") != NULL &&
      json_get_string(body, "kind", kind, sizeof(kind)) && IsPatchKind(kind)) {
    *status = PatchKindRefuse(client_fd);
    return false;
  }
  int id = 0;
  bool row = MatchEntryIdPath(path, &id) || MatchEntryAppendPath(path, &id) ||
             MatchEntryTitlePath(path, &id) || MatchEntryEndPath(path, &id) ||
             MatchEntryCalDAVPath(path, &id);
  if (!row || id <= 0) {
    return true;
  }
  if (!LimitedRowKind(client_fd, id, kind, sizeof(kind), status)) {
    return false;
  }
  if (IsPatchKind(kind)) {
    *status = PatchKindRefuse(client_fd);
    return false;
  }
  return true;
}

// Serves one request on an already-accepted connection. Returns whether the
// connection may be reused; *out_carry reports how many bytes of the *next*
// request were read along with this one and now sit at the front of req_buf.
//
// `allow_keep_alive` is the server's half of the decision (the loop's request
// budget); HTTPWantsKeepAlive is the client's. Both have to say yes.
static bool ServeHTTPRequest(int client_fd, Arena *arena, char *req_buf,
                             size_t req_buf_size, int carry,
                             int idle_timeout_seconds, bool allow_keep_alive,
                             int *out_carry) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(req_buf != NULL && req_buf_size > 1);
  assert(out_carry != NULL);

  *out_carry = 0;
  double req_start = GetTimeSeconds();

  int total_read;
  char *body_start;
  int headers_len;
  HTTPRequestLine req_line;
  bool idle = false;
  if (!ReadHTTPRequestLine(client_fd, req_buf, req_buf_size, carry,
                           idle_timeout_seconds, &total_read, &body_start,
                           &headers_len, &req_line, &idle)) {
    return false;
  }
  double req_recv = GetTimeSeconds();

  // Settled before any response goes out, because every response helper
  // stamps a Connection header from g_conn_keep_alive - and a header that
  // disagrees with what this function returns is worse than no header at all,
  // which is the bug this whole path exists to fix.
  long long content_len = 0;
  bool length_ok = ParseContentLength(req_buf, &content_len);
  bool client_keep_alive = allow_keep_alive && HTTPWantsKeepAlive(req_buf);

  // Held false until the body has actually been taken off the wire: every
  // early exit below (OPTIONS, /health, 401, 413) answers without reading it,
  // and those undrained bytes would be parsed as the next request. Restored
  // to the client's preference right after ReadHTTPRequestBody succeeds -
  // which is the only place that can promise the wire is clean.
  //
  // It has to be an invariant rather than a flag each early exit sets for
  // itself, because CheckHTTPAuth sends its own 401 before returning: by the
  // time the caller could react, the header has already gone out.
  g_conn_keep_alive = client_keep_alive && length_ok && (content_len == 0);
  // Per request, not per connection: nothing obliges a client to send the
  // same Accept-Encoding twice, and a stale yes would gzip at a client that
  // cannot read it.
  g_conn_accepts_gzip = HTTPAcceptsGzip(req_buf);
  // the routes before the auth check never set it; nothing may read the last
  // request's login
  g_conn_login = NULL;

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

  // Who asked, for the log only (see g_conn_peer): the socket peer, then what
  // tailscale serve says about the real client when it is the one proxying.
  char xff[64], ts_login[96];
  HeaderForLog(req_buf, "X-Forwarded-For:", xff, sizeof(xff));
  HeaderForLog(req_buf, "Tailscale-User-Login:", ts_login, sizeof(ts_login));
  printf("HTTP Request: %s %s%s%s from %s%s%s%s%s\n", method, path,
         query[0] ? "?" : "", query, g_conn_peer, xff[0] ? " xff=" : "", xff,
         ts_login[0] ? " ts=" : "", ts_login);
  int status_code = 0;

  // A body this server cannot frame (see ParseContentLength) is refused
  // before any route, the unauthenticated ones included: with no length to
  // trust, nothing after the headers can be told apart from the next request.
  if (!length_ok) {
    status_code = SendJSONError(client_fd, 400, "Bad Content-Length");
    goto end;
  }

  // OPTIONS answers the browser's CORS preflight and a CalDAV client's
  // "what are you" probe in one response. It is deliberately before the auth
  // check, like /health: iOS sends this one unauthenticated, and the DAV
  // headers give away nothing about the journal.
  if (strcmp(method, "OPTIONS") == 0) {
    char resp[512];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 204 No Content\r\n" HTTP_CORS_HEADERS
                         CALDAV_DAV_HEADER CALDAV_ALLOW_HEADER "%s"
                     "Content-Length: 0\r\n\r\n",
                     HTTPConnectionHeader());
    assert(n > 0 && n < (int)sizeof(resp));
    send(client_fd, resp, (size_t)n, MSG_NOSIGNAL);
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

  // The icons a browser asks the origin's root for on its own, whatever the
  // page's <link rel="icon"> says: /favicon.ico everywhere, and on iOS the
  // two touch icons, on adding to the home screen and on every launch. Behind
  // tailscale serve the root is this API, so they used to meet the auth
  // check, and its WWW-Authenticate header is what makes iOS raise its own
  // Basic-auth sheet — one the page never sees and a home-screen app never
  // remembers, so it came back on every launch. A 404 without a challenge
  // sends the browser to the icons the page declares (lcars-ui/).
  if ((strcmp(method, "GET") == 0 || strcmp(method, "HEAD") == 0) &&
      (PathIs(path, "/favicon.ico") ||
       strncmp(path, "/apple-touch-icon", 17) == 0)) {
    status_code = SendJSONError(client_fd, 404, "no icon here");
    goto end;
  }

  // The media files, before the auth check for loopback only: that is
  // tailscale serve's proxy, whose <img>/<video> clients cannot send the
  // Basic-auth header. From anywhere else this port is the open internet,
  // and the route wants the password like the rest (see HandleMediaFile).
  if ((strcmp(method, "GET") == 0 || strcmp(method, "HEAD") == 0) &&
      MediaIsFilePath(path)) {
    if (!MediaPeerIsLoopback(client_fd) && !CheckHTTPAuth(client_fd, req_buf)) {
      status_code = 401;
      goto end;
    }
    status_code = HandleMediaFile(client_fd, arena, method, path, req_buf);
    goto end;
  }

  // The web UI, by the same rule: loopback (tailscale serve) is let in, the
  // public port wants the password. Any page path answers with the app.
  if ((strcmp(method, "GET") == 0 || strcmp(method, "HEAD") == 0) &&
      UIIsPath(path)) {
    if (!MediaPeerIsLoopback(client_fd) && !CheckHTTPAuth(client_fd, req_buf)) {
      status_code = 401;
      goto end;
    }
    status_code = HandleUIFile(client_fd, arena, method, path, req_buf);
    goto end;
  }

  // The Prometheus scrape, by the same rule: Alloy scrapes it on loopback
  // and has no password to send; the public port wants one (lcars_metrics.h).
  if (PathIs(path, "/metrics")) {
    if (!MediaPeerIsLoopback(client_fd) && !CheckHTTPAuth(client_fd, req_buf)) {
      status_code = 401;
      goto end;
    }
    status_code = HandleMetrics(client_fd, arena, method);
    goto end;
  }

  if (!CheckHTTPAuth(client_fd, req_buf)) {
    status_code = 401;
    goto end;
  }

  // Media uploads are dispatched before the body is read: the body is a
  // photo or a video, far past HTTP_MAX_BODY_BYTES, and is streamed to the
  // NAS by the handler, which also decides keep-alive once it has drained it.
  int media_entry_id = 0;
  int media_id = 0;
  if (strcmp(method, "POST") == 0 &&
      MatchMediaPath(path, &media_entry_id, &media_id) && media_id == 0) {
    if (g_conn_login != NULL) {
      // before the body is read, so the connection ends (keep-alive is
      // still false for a request with a body)
      status_code = LimitedRefuse(client_fd, g_conn_login);
      goto end;
    }
    status_code = HandleMediaUpload(client_fd, arena, media_entry_id, query,
                                    req_buf, body_start, total_read,
                                    headers_len, client_keep_alive);
    goto end;
  }

  // A chat's file: the same, with no entry (lcars_media.h)
  if (strcmp(method, "POST") == 0 && PathIs(path, "/chat/media")) {
    status_code = g_conn_login != NULL
                      ? LimitedRefuse(client_fd, g_conn_login)
                      : HandleChatMediaUpload(client_fd, arena, query, req_buf,
                                              body_start, total_read,
                                              headers_len, client_keep_alive);
    goto end;
  }

  char *body;
  char content_type[128];
  status_code = ReadHTTPRequestBody(client_fd, arena, req_buf, body_start,
                                    total_read, headers_len, content_len, &body,
                                    content_type, sizeof(content_type));
  if (status_code != 0) {
    // 413 and 400 only fire for a request with a body, so the invariant
    // above already has this connection marked as ending - which is right:
    // the oversized body is still on the wire and deliberately not drained.
    assert(!g_conn_keep_alive);
    goto end;
  }
  // The wire is clean now, so the connection may carry another request.
  g_conn_keep_alive = client_keep_alive;

  // A limited login (Number One, the crew) reads everything and writes only
  // its own entries (lcars_logins.h); anything else it asks for is answered
  // here.
  if (g_conn_login != NULL &&
      !LimitedAllowed(client_fd, g_conn_login, method, path, body, content_type,
                      &status_code)) {
    goto end;
  }
  // the patch kinds are the pages' alone (PatchKindAllowed)
  if (!PatchKindAllowed(client_fd, req_buf, method, path, body, content_type,
                        &status_code)) {
    goto end;
  }

  // Router. CalDAV comes first: it claims the WebDAV methods (which the
  // JSON API has no use for) and everything under /caldav, so a PROPFIND on
  // "/" reaches principal discovery instead of the JSON index.
  int entry_id = 0;
  if (IsCalDAVRequest(method, path)) {
    status_code =
        HandleCalDAVRequest(client_fd, arena, method, path, req_buf, body);
  } else if (PathIs(path, "/") || PathIs(path, "")) {
    status_code = strcmp(method, "GET") == 0
                      ? HandleIndex(client_fd)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /", method);
  } else if (PathIs(path, "/entries")) {
    if (strcmp(method, "GET") == 0) {
      status_code = HandleGetEntries(client_fd, arena, query);
    } else if (strcmp(method, "POST") == 0) {
      status_code =
          HandlePostEntryKeyed(client_fd, arena, body, content_type, req_buf);
    } else {
      status_code = SendJSONError(client_fd, 405,
                                  "Method %s not allowed on /entries", method);
    }
  } else if (MatchEntryIdPath(path, &entry_id)) {
    if (strcmp(method, "GET") == 0) {
      status_code = HandleGetEntry(client_fd, arena, entry_id);
    } else if (strcmp(method, "PUT") == 0 || strcmp(method, "PATCH") == 0) {
      status_code =
          HandleUpdateEntry(client_fd, arena, entry_id, body, content_type);
    } else if (strcmp(method, "DELETE") == 0) {
      status_code = HandleDeleteEntry(client_fd, entry_id, body, content_type);
    } else {
      status_code = SendJSONError(
          client_fd, 405, "Method %s not allowed on /entries/<id>", method);
    }
  } else if (MatchEntryAppendPath(path, &entry_id)) {
    status_code =
        strcmp(method, "POST") == 0
            ? HandleAppendEntry(client_fd, arena, entry_id, body, content_type)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /entries/<id>/append",
                            method);
  } else if (MatchEntryTitlePath(path, &entry_id)) {
    status_code =
        strcmp(method, "POST") == 0
            ? HandleTitleEntry(client_fd, arena, entry_id, body, content_type)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /entries/<id>/title",
                            method);
  } else if (MatchEntryEndPath(path, &entry_id)) {
    status_code =
        strcmp(method, "POST") == 0
            ? HandleEndEntry(client_fd, arena, entry_id, body, content_type)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /entries/<id>/end",
                            method);
  } else if (MatchEntryCalDAVPath(path, &entry_id)) {
    status_code =
        HandleEntryCalDAV(client_fd, arena, method, entry_id, req_buf, body);
  } else if (MatchMediaPath(path, &media_entry_id, &media_id)) {
    if (strcmp(method, "GET") == 0 && media_id == 0) {
      status_code = HandleMediaList(client_fd, arena, media_entry_id);
    } else if (strcmp(method, "DELETE") == 0 && media_id > 0) {
      status_code = HandleMediaDelete(client_fd, media_entry_id, media_id);
    } else {
      status_code = SendJSONError(client_fd, 405, "Method %s not allowed on %s",
                                  method, path);
    }
  } else if (PathIs(path, "/reports")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleReportList(client_fd, arena)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /reports",
                            method);
  } else if (PathIs(path, "/" MEDIA_SUBDIR)) {
    // the bare "/media" lists; "/media/<path>" (a file) was served above
    status_code =
        strcmp(method, "GET") == 0
            ? HandleMediaList(client_fd, arena, 0)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /media",
                            method);
  } else if (strncmp(path, "/tapes/", 7) == 0) {
    char tape_token[MEDIA_TAPE_TOKEN_MAX + 8];
    if (!MatchTapePath(path, tape_token, sizeof(tape_token))) {
      status_code = SendJSONError(client_fd, 404, "Not a tape: %s", path);
    } else if (strcmp(method, "POST") != 0) {
      status_code = SendJSONError(client_fd, 405, "Method %s not allowed on %s",
                                  method, path);
    } else {
      status_code =
          HandleTapeAppend(client_fd, tape_token, query, body, content_len);
    }
  } else if (PathIs(path, "/transcribe")) {
    status_code =
        strcmp(method, "POST") == 0
            ? HandleTranscribe(client_fd, arena, body, content_len,
                               content_type)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /transcribe", method);
  } else if (PathIs(path, "/chat")) {
    status_code = strcmp(method, "POST") == 0
                      ? HandleChat(client_fd, arena, body, content_type, false)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /chat", method);
  } else if (PathIs(path, "/events")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleEvents(client_fd)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /events",
                            method);
  } else if (PathIs(path, "/ask")) {
    status_code = strcmp(method, "POST") == 0
                      ? HandleChat(client_fd, arena, body, content_type, true)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /ask", method);
  } else if (IsEngineerPath(path)) {
    status_code =
        HandleEngineer(client_fd, arena, method, path, query, req_buf, body);
  } else if (PathIs(path, "/embeddings")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleEmbeddings(client_fd, arena, query)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /embeddings", method);
  } else if (PathIs(path, "/embed")) {
    status_code =
        strcmp(method, "POST") == 0
            ? HandleEmbed(client_fd, arena, body, content_type)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /embed",
                            method);
  } else if (PathIs(path, "/say/token")) {
    status_code = HandleSayToken(client_fd, arena, method);
  } else if (PathIs(path, "/say")) {
    status_code = HandleSay(client_fd, arena, method, body, content_type);
  } else if (PathIs(path, "/features")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleFeatures(client_fd, arena)
            : SendJSONError(client_fd, 405,
                            "Method %s not allowed on /features", method);
  } else if (PathIs(path, "/maps")) {
    status_code = strcmp(method, "GET") == 0
                      ? HandleMaps(client_fd)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /maps", method);
  } else if (PathIs(path, "/dump")) {
    status_code = strcmp(method, "GET") == 0
                      ? HandleDump(client_fd, arena, query)
                      : SendJSONError(client_fd, 405,
                                      "Method %s not allowed on /dump", method);
  } else if (PathIs(path, "/kinds/roles")) {
    status_code = HandleKindRoles(client_fd, arena, method, body);
  } else if (PathIs(path, "/kinds")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleGetKinds(client_fd, arena, query)
            : SendJSONError(client_fd, 405, "Method %s not allowed on /kinds",
                            method);
  } else if (PathIs(path, "/stats")) {
    status_code =
        strcmp(method, "GET") == 0
            ? HandleGetStats(client_fd, arena, query)
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
  if (!g_conn_keep_alive) {
    return false;
  }
  // Whatever was read past this request's body is the start of the next one.
  // A negative count means the body ran past what was buffered (the rest went
  // straight into the arena), so there is nothing left over.
  assert(content_len >= 0);
  long long leftover = total_read - headers_len - content_len;
  if (leftover > 0) {
    memmove(req_buf, req_buf + headers_len + content_len, (size_t)leftover);
    *out_carry = (int)leftover;
  }
  return true;
}
}

static void HandleHTTPConnection(int client_fd) {
  assert(client_fd >= 0);

  // 1MB request arena on this connection's own thread stack: no malloc, no
  // fragmentation, and it is gone when the thread is. Reset between requests
  // on a kept-alive connection rather than rebuilt.
  uint8_t arena_backing[1024 * 1024];
  Arena arena;
  arena_init(&arena, arena_backing, sizeof(arena_backing));

  char req_buf[8192];
  int carry = 0;
  g_conn_keep_alive = false;

  // Asked of the socket rather than threaded through from accept(): the fd
  // already travels to this thread as a bare pointer (HTTPConnectionThread).
  struct sockaddr_storage peer;
  socklen_t peer_len = sizeof(peer);
  strcpy(g_conn_peer, "?");
  if (getpeername(client_fd, (struct sockaddr *)&peer, &peer_len) == 0) {
    if (peer.ss_family == AF_INET) {
      inet_ntop(AF_INET, &((struct sockaddr_in *)&peer)->sin_addr, g_conn_peer,
                sizeof(g_conn_peer));
    } else if (peer.ss_family == AF_INET6) {
      inet_ntop(AF_INET6, &((struct sockaddr_in6 *)&peer)->sin6_addr,
                g_conn_peer, sizeof(g_conn_peer));
    }
  }

  for (int served = 0; served < HTTP_MAX_REQUESTS_PER_CONNECTION; served++) {
    arena_reset(&arena);
    // The last request of the budget is answered with Connection: close, so
    // the client is told the connection is ending instead of discovering it.
    bool allow_keep_alive = (served + 1 < HTTP_MAX_REQUESTS_PER_CONNECTION);
    // A connection that has never carried a request is a preconnect until
    // proven otherwise, and is given correspondingly little time.
    int idle_timeout = (served == 0) ? HTTP_CONNECT_TIMEOUT_SECONDS
                                     : HTTP_IDLE_TIMEOUT_SECONDS;
    int next_carry = 0;
    if (!ServeHTTPRequest(client_fd, &arena, req_buf, sizeof(req_buf), carry,
                          idle_timeout, allow_keep_alive, &next_carry)) {
      break;
    }
    carry = next_carry;
  }
  close(client_fd);
}

// Connections currently being served, against HTTP_MAX_CONCURRENT_CONNECTIONS.
// Each one owns a thread with a 1MB request arena on its stack, so this is the
// memory ceiling as much as the concurrency one.
static _Atomic int g_http_active_connections = 0;

static void *HTTPConnectionThread(void *arg) {
  // The fd travels as the pointer rather than through an allocation: there is
  // nothing to free on a path that must not fail, and nothing to leak if the
  // thread dies.
  int client_fd = (int)(intptr_t)arg;
  HandleHTTPConnection(client_fd);
  atomic_fetch_sub(&g_http_active_connections, 1);
  return NULL;
}

void RunHTTPServer(int port) {
  assert(port > 0 && port <= 65535);

  // LCARS_BIND picks the listening address; unset means every interface, as
  // it always was (the laptop's app wants phones on the LAN to reach it). The
  // VPS sets 127.0.0.1: tailscale serve is its only way in, and a server that
  // listens publicly is held shut by nothing but the firewall. A value that
  // does not parse refuses to start rather than falling back to "everywhere",
  // which is the one outcome the setting exists to prevent.
  struct in_addr bind_addr;
  bind_addr.s_addr = htonl(INADDR_ANY);
  const char *bind_env = getenv("LCARS_BIND");
  if (bind_env != NULL && bind_env[0] != '\0' &&
      inet_pton(AF_INET, bind_env, &bind_addr) != 1) {
    fprintf(stderr, "LCARS_BIND='%s' is not an IPv4 address; not starting\n",
            bind_env);
    return;
  }

  // Before any connection exists, so no two threads can race to fill these in.
  EnsureHTTPAuthInit();
  g_http_port = port;
  // Reads its configuration here, before any connection can ask for it.
  StartEmbedIndexer();
  SayInit();
  UIGzInit();
  UIInit();

  // Close-on-exec, the listener and every connection (accept4 below): the
  // server spawns children (claude, ffmpeg, engineer.py), and one that
  // inherited a socket would hold a client the server has hung up on
  // connected, or the port itself, for as long as it ran. glibc's spawns
  // also close what is above stderr (addclosefrom_np), but musl has no
  // such call, and an fd that is never inherited needs no closing.
  int server_fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
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
  address.sin_addr = bind_addr;
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

  char bind_text[INET_ADDRSTRLEN];
  inet_ntop(AF_INET, &bind_addr, bind_text, sizeof(bind_text));
  printf("HTTP Server running on %s:%d...\n", bind_text, port);

  // A thread per connection. This used to be a serial loop - accept, serve,
  // close, repeat - which meant a single slow request held up every other
  // client, and a peer that connected and sent nothing held up the server
  // indefinitely, because recv() had no timeout. Browsers open speculative
  // preconnects that do exactly that, so the API became unreachable after a
  // couple of page loads. Keep-alive makes it worse still: a connection is
  // now meant to stay open across requests.
  while (1) {
    int client_fd = accept4(server_fd, NULL, NULL, SOCK_CLOEXEC);
    if (client_fd < 0) {
      continue;
    }

    if (atomic_load(&g_http_active_connections) >=
        HTTP_MAX_CONCURRENT_CONNECTIONS) {
      // Refused rather than queued, so the memory ceiling above is real. A
      // personal journal reaching 32 concurrent connections is a client gone
      // wrong, and 503 tells it so instead of hanging.
      static const char busy[] = "HTTP/1.1 503 Service Unavailable\r\n"
                                 "Connection: close\r\n"
                                 "Content-Length: 0\r\n\r\n";
      send(client_fd, busy, sizeof(busy) - 1, MSG_NOSIGNAL);
      close(client_fd);
      continue;
    }

    pthread_attr_t attr;
    if (pthread_attr_init(&attr) != 0) {
      HandleHTTPConnection(client_fd);
      continue;
    }
    // Explicit rather than inherited: HandleHTTPConnection puts a 1MB arena on
    // the stack and CalDAV another 512KB below it.
    pthread_attr_setstacksize(&attr, HTTP_THREAD_STACK_BYTES);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

    // Counted up before the thread starts, so the ceiling cannot be crossed
    // by connections that have been accepted but not yet begun.
    atomic_fetch_add(&g_http_active_connections, 1);
    pthread_t tid;
    if (pthread_create(&tid, &attr, HTTPConnectionThread,
                       (void *)(intptr_t)client_fd) != 0) {
      // Out of threads: serve it here rather than drop it. Slower, and it
      // blocks the accept loop for the length of one connection - which is
      // exactly the old behaviour, and still better than refusing.
      atomic_fetch_sub(&g_http_active_connections, 1);
      pthread_attr_destroy(&attr);
      HandleHTTPConnection(client_fd);
      continue;
    }
    pthread_attr_destroy(&attr);
  }

  close(server_fd);
}

#endif // LCARS_HTTP_IMPLEMENTATION
#endif // LCARS_HTTP_H
