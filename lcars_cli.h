#ifndef LCARS_CLI_H
#define LCARS_CLI_H

// lcars-cli - a terminal client for the `entries` table.
//
// It talks to a running LCARS server (this machine's, or the VPS's) over the
// JSON API in lcars_http.h, and nothing else: the server is the journal's
// one writer, so its checks (the logins' kinds, the change feed, CalDAV's
// side tables) cannot be stepped around. Until 0.177.0 a --db mode opened
// lcars.db directly with a second copy of the server's queries.
//
// Rows come back as `EntryRow` and go out through one renderer; `--json`
// rebuilds the API's own JSON from them.
//
// Deletes are soft (`deleted = 1`), exactly like the API and the UI. There
// is no hard delete in this tool for the same reason there is none in the
// API: this database is a personal journal, and `restore` is the undo.

#include "lcars_arena.h"
#include "lcars_json.h"

#include <curl/curl.h>

#include "lcars_curl_ca.h"
#include <stdarg.h>
#include <strings.h>
#include <unistd.h>

// Mirrors of the HTTP layer's limits (lcars_http.h). Same numbers on
// purpose: a `--limit` this tool accepts must be one the server accepts,
// so a bad one fails here, before a request.
#define CLI_DEFAULT_LIMIT 200
#define CLI_MAX_LIMIT 1000
#define CLI_MAX_TIMESTAMP_LEN 19
#define CLI_ERR_SIZE 512

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

typedef struct CliOptions {
  const char *base_url; // scheme://host:port, no trailing slash
  const char *user;     // Basic auth, NULL for none
  const char *pass;
  bool json; // emit the API's JSON instead of a table
  bool raw;  // `get`: print the content and nothing else
  long timeout_seconds;
} CliOptions;

// One row of `entries`, however it was fetched. `content` is NULL when the
// list was asked for without bodies (--no-content); "" and NULL are
// different answers here ("empty entry" vs "did not ask").
typedef struct EntryRow {
  int id;
  const char *kind;
  const char *title;
  const char *content;
  int content_length;
  int value_int;
  double value_float;
  int done_bool;
  int deleted;
  const char *created_at_utc;
  const char *last_modified_at_utc;
  // Scheduling: when the entry is *for*, "" when unscheduled (see
  // ARCHITECTURE.md, "The local database").
  const char *start_date;
  const char *end_date;
  // 0 Unclassified, 2 Secret: a Secret row's title and text are sealed, so
  // they arrive empty (lcars_vault.h); 0 from a server older than the field.
  int classification;
} EntryRow;

typedef struct EntryRows {
  EntryRow *items;
  int count;
} EntryRows;

typedef struct KindRow {
  const char *kind;
  int count;
  const char *last_modified_at_utc;
} KindRow;

typedef struct KindRows {
  KindRow *items;
  int count;
} KindRows;

typedef struct StatsRow {
  int count;
  int kinds;
  int done;
  long long content_bytes;
  const char *oldest_created_at_utc;
  const char *newest_created_at_utc;
  const char *last_modified_at_utc;
} StatsRow;

// The list/stats filter set. Everything is "unset" by default: NULL for the
// strings, -1 for the tristate ints, 0 for the id bounds. Values land here
// already validated and normalized by the argument parser (see
// CliNormalizeTimestamp).
typedef struct CliFilters {
  const char *kind;
  const char *q;
  const char *date;
  const char *since;
  const char *until;
  const char *modified_since;
  const char *modified_until;
  int done;                   // -1 unset, 0 or 1
  const char *deleted;        // NULL (= live only), "0", "1", "all"
  int min_id;                 // 0 unset
  int max_id;                 // 0 unset
  const char *scheduled_date; // YYYY-MM-DD: an overlap test, not equality
  // NULL unset, "0" or "1" ("has a start_date"). A string like `deleted`
  // rather than a -1 tristate like `done`: every caller that memsets a
  // CliFilters (the logseq bridge among them) then gets "unset" for free.
  const char *scheduled;
  const char *order; // NULL => id
  const char *dir;   // NULL => desc
  int limit;
  int offset;
  bool include_content;
} CliFilters;

// The mutable half of an entry, for create and update. Every field is
// optional; `has_*` is what makes an update *partial* (the same contract as
// PUT/PATCH in lcars_http.h: a body that only carries content must not
// blank the title).
typedef struct CliFields {
  bool has_kind, has_title, has_content;
  bool has_value_int, has_value_float, has_done, has_deleted;
  // Backdating. Only `new` uses has_modified_at: the server stamps
  // last_modified_at_utc on every update, so an update that tried to set it
  // would be overwritten by the same statement that wrote it.
  bool has_created_at, has_modified_at;
  // Scheduling. "" is a value here - it unschedules - which is why these
  // carry their own has_* rather than meaning "unset" when empty.
  bool has_start, has_end;
  const char *kind;
  const char *title;
  const char *content;
  int value_int;
  double value_float;
  int done_bool;
  int deleted;
  const char *created_at;  // "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS", UTC
  const char *modified_at; // same shape
  const char *start_date;  // same shape, or ""
  const char *end_date;
} CliFields;

// ---------------------------------------------------------------------------
// Declarations
// ---------------------------------------------------------------------------

static inline bool CliFail(char *err, size_t err_size, const char *fmt, ...);
static inline bool CliNormalizeTimestamp(Arena *arena, const char *in,
                                         bool upper_bound, const char **out,
                                         char *err, size_t err_size);
static inline bool CliValidOrder(const char *order);
static inline const char *CliReadFile(Arena *arena, const char *path, char *err,
                                      size_t err_size);
static inline bool CliEditText(Arena *arena, const char *initial,
                               const char **out, char *err, size_t err_size);

// The requests - the whole surface the command layer uses.
static inline bool CliListEntries(Arena *arena, const CliOptions *opts,
                                  const CliFilters *filters, EntryRows *out,
                                  char *err, size_t err_size);
static inline bool CliGetEntry(Arena *arena, const CliOptions *opts, int id,
                               EntryRow *out, char *err, size_t err_size);
static inline bool CliCreateEntry(Arena *arena, const CliOptions *opts,
                                  const CliFields *fields, int *out_id,
                                  char *err, size_t err_size);
static inline bool CliUpdateEntry(Arena *arena, const CliOptions *opts, int id,
                                  const CliFields *fields, char *err,
                                  size_t err_size);
static inline bool CliDeleteEntry(Arena *arena, const CliOptions *opts, int id,
                                  char *err, size_t err_size);
// POST /entries/<id>/append: `text` added at the end, nothing else
// touched, and only if the row's last_modified_at_utc is still `if_modified`
// (a 412 otherwise)
static inline bool CliAppendEntry(Arena *arena, const CliOptions *opts, int id,
                                  const char *text, const char *if_modified,
                                  char *err, size_t err_size);
static inline bool CliListKinds(Arena *arena, const CliOptions *opts,
                                bool include_deleted, KindRows *out, char *err,
                                size_t err_size);
static inline bool CliGetStats(Arena *arena, const CliOptions *opts,
                               const CliFilters *filters, StatsRow *out,
                               char *err, size_t err_size);

// Rendering.
static inline bool CliRolesRequest(Arena *arena, const CliOptions *opts,
                                   const char *method, const char *body,
                                   JsonSpan *out, char *err, size_t err_size);
static inline const char *CliRoleKind(Arena *arena, const CliOptions *opts,
                                      const char *role, const char *fallback,
                                      char *err, size_t err_size);
static inline void CliPrintEntries(Arena *arena, const CliOptions *opts,
                                   const EntryRows *rows);
static inline void CliPrintEntry(Arena *arena, const CliOptions *opts,
                                 const EntryRow *row);
static inline void CliPrintKinds(Arena *arena, const CliOptions *opts,
                                 const KindRows *kinds);
static inline void CliPrintStats(const CliOptions *opts, const StatsRow *st);

#ifdef LCARS_IMPLEMENTATION

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

// Always returns false, so a failing path is one line:
//   return CliFail(err, err_size, "no entry with id %d", id);
static inline bool CliFail(char *err, size_t err_size, const char *fmt, ...) {
  assert(err != NULL);
  assert(err_size > 0);
  assert(fmt != NULL);

  va_list args;
  va_start(args, fmt);
  vsnprintf(err, err_size, fmt, args);
  va_end(args);
  return false;
}

// ---------------------------------------------------------------------------
// Validation / normalization, before any request
// ---------------------------------------------------------------------------

// Accepts "YYYY-MM-DD", "YYYY-MM-DD HH:MM" or "YYYY-MM-DD HH:MM:SS" and
// widens a bare date used as an upper bound to the end of that day (and a
// bare minute to the end of that minute) - the same rule
// NormalizeTimestamp applies in lcars_http.h; the minute form is completed
// here because the server takes only the other two.
static inline bool CliNormalizeTimestamp(Arena *arena, const char *in,
                                         bool upper_bound, const char **out,
                                         char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(in != NULL);
  assert(out != NULL);

  size_t len = strlen(in);
  // The minute form is what a person (or a voice agent) writes; the
  // server only takes the other two, so it is completed here.
  if (len != 10 && len != 16 && len != CLI_MAX_TIMESTAMP_LEN) {
    return CliFail(err, err_size,
                   "invalid timestamp '%s' (YYYY-MM-DD or "
                   "'YYYY-MM-DD HH:MM[:SS]')",
                   in);
  }
  for (size_t i = 0; i < len; i++) {
    char c = in[i];
    bool ok = (c >= '0' && c <= '9') || c == '-' || c == ':' || c == ' ';
    if (!ok) {
      return CliFail(err, err_size, "invalid timestamp '%s'", in);
    }
  }

  char *buf = (char *)arena_alloc(arena, CLI_MAX_TIMESTAMP_LEN + 1);
  if (len == 10 && upper_bound) {
    snprintf(buf, CLI_MAX_TIMESTAMP_LEN + 1, "%s 23:59:59", in);
  } else if (len == 16) {
    snprintf(buf, CLI_MAX_TIMESTAMP_LEN + 1, "%s:%s", in,
             upper_bound ? "59" : "00");
  } else {
    snprintf(buf, CLI_MAX_TIMESTAMP_LEN + 1, "%s", in);
  }
  *out = buf;
  return true;
}

// The `order` values the server's ResolveOrderBy accepts, so a bad one is
// refused before a request.
static inline bool CliValidOrder(const char *order) {
  static const char *names[] = {"id",
                                "created",
                                "created_at_utc",
                                "modified",
                                "last_modified_at_utc",
                                "title",
                                "kind",
                                "start",
                                "start_date",
                                "end",
                                "end_date"};
  if (!order || order[0] == '\0') {
    return true;
  }
  for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
    if (strcasecmp(order, names[i]) == 0) {
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

struct CliCurlBuf {
  char *data;
  size_t size;
  Arena *arena;
};

static inline size_t CliCurlWrite(void *contents, size_t size, size_t nmemb,
                                  void *userp) {
  size_t real_size = size * nmemb;
  struct CliCurlBuf *mem = (struct CliCurlBuf *)userp;
  assert(mem != NULL);
  assert(mem->data != NULL); // seeded with a 1-byte allocation before the call

  mem->data = (char *)arena_realloc(mem->arena, mem->data, mem->size,
                                    mem->size + real_size + 1);
  memcpy(mem->data + mem->size, contents, real_size);
  mem->size += real_size;
  mem->data[mem->size] = '\0';
  return real_size;
}

// One blocking request. Like NetHttpRequest in lcars_net.h, the return value
// reports whether the *transport* worked: a 404 is a successful call with
// status 404, and the caller decides what that means. (This does not reuse
// NetHttpRequest because that one has no way to send credentials, and every
// route but /health needs Basic auth.)
static inline bool CliHttpRequest(Arena *arena, const CliOptions *opts,
                                  const char *method, const char *path,
                                  const char *body, JsonSpan *out_body,
                                  long *out_status, char *err,
                                  size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL);
  assert(method != NULL);
  assert(path != NULL && path[0] == '/');
  assert(out_body != NULL && out_status != NULL);

  out_body->data = "";
  out_body->len = 0;
  *out_status = 0;

  JSONBuf url;
  jsonbuf_init_strict(&url, arena);
  jsonbuf_append(&url, opts->base_url);
  jsonbuf_append(&url, path);

  CURL *curl = curl_easy_init();
  if (!curl) {
    return CliFail(err, err_size, "curl_easy_init() failed");
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)

  struct CliCurlBuf chunk;
  chunk.arena = arena;
  chunk.data = (char *)arena_alloc(arena, 1);
  chunk.data[0] = '\0';
  chunk.size = 0;

  struct curl_slist *headers = NULL;
  if (body) {
    headers = curl_slist_append(headers, "Content-Type: application/json");
  }

  curl_easy_setopt(curl, CURLOPT_URL, url.data);
  curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, CliCurlWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, opts->timeout_seconds);
  curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "lcars-cli/1.0");
  if (body) {
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  }
  if (opts->user) {
    curl_easy_setopt(curl, CURLOPT_HTTPAUTH, (long)CURLAUTH_BASIC);
    curl_easy_setopt(curl, CURLOPT_USERNAME, opts->user);
    curl_easy_setopt(curl, CURLOPT_PASSWORD, opts->pass ? opts->pass : "");
  }

  CURLcode res = curl_easy_perform(curl);
  if (res != CURLE_OK) {
    CliFail(err, err_size, "%s %s: %s", method, url.data,
            curl_easy_strerror(res));
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return false;
  }
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, out_status);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  out_body->data = chunk.data;
  out_body->len = chunk.size;
  return true;
}

// Turns a non-2xx response into the message the user sees. The API answers
// errors as {"error":…,"status":…}, so prefer that text over the status
// line - "No entry with id 42" beats "HTTP 404".
static inline bool CliHttpStatusError(Arena *arena, JsonSpan body, long status,
                                      char *err, size_t err_size) {
  assert(arena_valid(arena));

  JsonSpan message;
  if (body.len > 0 && body.data[0] == '{' &&
      json_member(body, "error", &message)) {
    return CliFail(err, err_size, "%s (HTTP %ld)",
                   json_span_string(arena, message), status);
  }
  if (status == 401) {
    return CliFail(err, err_size,
                   "HTTP 401 unauthorized - pass --user/--password or set "
                   "LCARS_AUTH_USER/LCARS_AUTH_PASS");
  }
  return CliFail(err, err_size, "HTTP %ld", status);
}

static inline void cli_url_encode(JSONBuf *b, const char *s) {
  assert(b != NULL);
  assert(s != NULL);

  static const char hex[] = "0123456789ABCDEF";
  for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
    unsigned char c = *p;
    bool unreserved = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || c == '-' || c == '_' ||
                      c == '.' || c == '~';
    if (unreserved) {
      jsonbuf_append_len(b, (const char *)&c, 1);
    } else {
      char esc[3] = {'%', hex[c >> 4], hex[c & 0x0F]};
      jsonbuf_append_len(b, esc, 3);
    }
  }
}

static inline void cli_url_param(JSONBuf *b, bool *first, const char *key,
                                 const char *value) {
  assert(b != NULL);
  assert(first != NULL);
  assert(key != NULL && value != NULL);

  jsonbuf_append_len(b, *first ? "?" : "&", 1);
  *first = false;
  jsonbuf_append(b, key);
  jsonbuf_append_len(b, "=", 1);
  cli_url_encode(b, value);
}

static inline void cli_url_param_int(JSONBuf *b, bool *first, const char *key,
                                     int value) {
  char num[32];
  snprintf(num, sizeof(num), "%d", value);
  cli_url_param(b, first, key, num);
}

// Builds "/entries?…" (or "/stats?…") from the filter set. `deleted` is
// always sent explicitly when the user asked for one, and omitted otherwise
// so the server's own default (live entries only) applies.
static inline const char *CliBuildQueryPath(Arena *arena, const char *route,
                                            const CliFilters *f,
                                            bool with_pagination) {
  assert(arena_valid(arena));
  assert(route != NULL);
  assert(f != NULL);

  JSONBuf path;
  jsonbuf_init_strict(&path, arena);
  jsonbuf_append(&path, route);
  bool first = true;

  if (f->kind) {
    cli_url_param(&path, &first, "kind", f->kind);
  }
  if (f->q) {
    cli_url_param(&path, &first, "q", f->q);
  }
  if (f->date) {
    cli_url_param(&path, &first, "date", f->date);
  }
  if (f->since) {
    cli_url_param(&path, &first, "since", f->since);
  }
  if (f->until) {
    cli_url_param(&path, &first, "until", f->until);
  }
  if (f->modified_since) {
    cli_url_param(&path, &first, "modified_since", f->modified_since);
  }
  if (f->modified_until) {
    cli_url_param(&path, &first, "modified_until", f->modified_until);
  }
  if (f->done >= 0) {
    cli_url_param_int(&path, &first, "done", f->done);
  }
  if (f->deleted) {
    cli_url_param(&path, &first, "deleted", f->deleted);
  }
  if (f->min_id > 0) {
    cli_url_param_int(&path, &first, "min_id", f->min_id);
  }
  if (f->max_id > 0) {
    cli_url_param_int(&path, &first, "max_id", f->max_id);
  }
  if (f->scheduled_date) {
    cli_url_param(&path, &first, "scheduled_date", f->scheduled_date);
  }
  if (f->scheduled) {
    cli_url_param(&path, &first, "scheduled", f->scheduled);
  }
  if (with_pagination) {
    if (f->order) {
      cli_url_param(&path, &first, "order", f->order);
    }
    if (f->dir) {
      cli_url_param(&path, &first, "dir", f->dir);
    }
    cli_url_param_int(&path, &first, "limit", f->limit);
    if (f->offset > 0) {
      cli_url_param_int(&path, &first, "offset", f->offset);
    }
    if (!f->include_content) {
      cli_url_param(&path, &first, "content", "0");
    }
  }
  return path.data;
}

static inline void CliParseEntryObject(Arena *arena, JsonSpan obj,
                                       EntryRow *row) {
  assert(arena_valid(arena));
  assert(row != NULL);

  memset(row, 0, sizeof(*row));
  row->kind = "";
  row->title = "";
  row->content = NULL; // "absent", which --no-content listings really are
  row->created_at_utc = "";
  row->last_modified_at_utc = "";
  row->start_date = "";
  row->end_date = "";

  JsonSpan v;
  if (json_member(obj, "id", &v)) {
    row->id = (int)json_span_long(v);
  }
  if (json_member(obj, "kind", &v)) {
    row->kind = json_span_string(arena, v);
  }
  if (json_member(obj, "title", &v)) {
    row->title = json_span_string(arena, v);
  }
  if (json_member(obj, "content", &v)) {
    row->content = json_span_string(arena, v);
  }
  if (json_member(obj, "content_length", &v)) {
    row->content_length = (int)json_span_long(v);
  }
  if (json_member(obj, "value_int", &v)) {
    row->value_int = (int)json_span_long(v);
  }
  if (json_member(obj, "value_float", &v)) {
    row->value_float = json_span_double(v);
  }
  if (json_member(obj, "done_bool", &v)) {
    row->done_bool = (int)json_span_long(v);
  }
  if (json_member(obj, "deleted", &v)) {
    row->deleted = (int)json_span_long(v);
  }
  if (json_member(obj, "created_at_utc", &v)) {
    row->created_at_utc = json_span_string(arena, v);
  }
  if (json_member(obj, "last_modified_at_utc", &v)) {
    row->last_modified_at_utc = json_span_string(arena, v);
  }
  if (json_member(obj, "start_date", &v)) {
    row->start_date = json_span_string(arena, v);
  }
  if (json_member(obj, "end_date", &v)) {
    row->end_date = json_span_string(arena, v);
  }
  if (json_member(obj, "classification", &v)) {
    row->classification = (int)json_span_long(v);
  }
}

// Two passes over the array: count, allocate, fill. The alternative
// (growing the row array) would leave dead copies behind in a bump arena.
static inline bool CliParseEntryArray(Arena *arena, JsonSpan body,
                                      EntryRows *out, char *err,
                                      size_t err_size) {
  assert(arena_valid(arena));
  assert(out != NULL);

  if (body.len == 0 || body.data[0] != '[') {
    return CliFail(err, err_size, "expected a JSON array, got: %.*s",
                   (int)(body.len < 120 ? body.len : 120), body.data);
  }

  int count = 0;
  const char *cursor = NULL;
  JsonSpan item;
  while (json_array_next(body, &cursor, &item)) {
    count++;
  }

  out->count = count;
  out->items =
      count > 0
          ? (EntryRow *)arena_alloc(arena, sizeof(EntryRow) * (size_t)count)
          : NULL;
  cursor = NULL;
  int i = 0;
  while (json_array_next(body, &cursor, &item) && i < count) {
    CliParseEntryObject(arena, item, &out->items[i]);
    i++;
  }
  assert(i == count);
  return true;
}

// Serializes the fields an update/create carries. Only the `has_*` ones are
// mentioned, which is what makes an update partial on the server side.
static inline const char *CliFieldsToJSON(Arena *arena, const CliFields *f) {
  assert(arena_valid(arena));
  assert(f != NULL);

  JSONBuf body;
  jsonbuf_init_strict(&body, arena);
  jsonbuf_append(&body, "{");
  bool first = true;

#define CLI_JSON_COMMA()                                                       \
  do {                                                                         \
    if (!first) {                                                              \
      jsonbuf_append(&body, ",");                                              \
    }                                                                          \
    first = false;                                                             \
  } while (0)

  if (f->has_kind) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"kind\":");
    jsonbuf_append_json_string(&body, f->kind);
  }
  if (f->has_title) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"title\":");
    jsonbuf_append_json_string(&body, f->title);
  }
  if (f->has_content) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"content\":");
    jsonbuf_append_json_string(&body, f->content);
  }
  if (f->has_value_int) {
    CLI_JSON_COMMA();
    jsonbuf_appendf(&body, "\"value_int\":%d", f->value_int);
  }
  if (f->has_value_float) {
    CLI_JSON_COMMA();
    jsonbuf_appendf(&body, "\"value_float\":%f", f->value_float);
  }
  if (f->has_done) {
    CLI_JSON_COMMA();
    jsonbuf_appendf(&body, "\"done_bool\":%d", f->done_bool ? 1 : 0);
  }
  if (f->has_deleted) {
    CLI_JSON_COMMA();
    jsonbuf_appendf(&body, "\"deleted\":%d", f->deleted ? 1 : 0);
  }
  if (f->has_created_at) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"created_at_utc\":");
    jsonbuf_append_json_string(&body, f->created_at);
  }
  if (f->has_modified_at) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"last_modified_at_utc\":");
    jsonbuf_append_json_string(&body, f->modified_at);
  }
  if (f->has_start) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"start_date\":");
    jsonbuf_append_json_string(&body, f->start_date);
  }
  if (f->has_end) {
    CLI_JSON_COMMA();
    jsonbuf_append(&body, "\"end_date\":");
    jsonbuf_append_json_string(&body, f->end_date);
  }
#undef CLI_JSON_COMMA

  jsonbuf_append(&body, "}");
  return body.data;
}

// ---------------------------------------------------------------------------
// The commands' requests
// ---------------------------------------------------------------------------

static inline bool CliListEntries(Arena *arena, const CliOptions *opts,
                                  const CliFilters *filters, EntryRows *out,
                                  char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && filters != NULL && out != NULL);

  const char *path = CliBuildQueryPath(arena, "/entries", filters, true);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET", path, NULL, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  return CliParseEntryArray(arena, body, out, err, err_size);
}

static inline bool CliGetEntry(Arena *arena, const CliOptions *opts, int id,
                               EntryRow *out, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && out != NULL);
  assert(id > 0);

  char path[64];
  snprintf(path, sizeof(path), "/entries/%d", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET", path, NULL, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  if (body.len == 0 || body.data[0] != '{') {
    return CliFail(err, err_size, "expected a JSON object, got: %.*s",
                   (int)(body.len < 120 ? body.len : 120), body.data);
  }
  CliParseEntryObject(arena, body, out);
  return true;
}

static inline bool CliCreateEntry(Arena *arena, const CliOptions *opts,
                                  const CliFields *fields, int *out_id,
                                  char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && fields != NULL && out_id != NULL);

  const char *body_json = CliFieldsToJSON(arena, fields);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "POST", "/entries", body_json, &body,
                      &status, err, err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  JsonSpan id_span;
  if (!json_member(body, "id", &id_span)) {
    return CliFail(err, err_size, "server did not return an id: %.*s",
                   (int)(body.len < 120 ? body.len : 120), body.data);
  }
  *out_id = (int)json_span_long(id_span);
  return true;
}

static inline bool CliUpdateEntry(Arena *arena, const CliOptions *opts, int id,
                                  const CliFields *fields, char *err,
                                  size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && fields != NULL);
  assert(id > 0);

  const char *body_json = CliFieldsToJSON(arena, fields);
  char path[64];
  snprintf(path, sizeof(path), "/entries/%d", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "PUT", path, body_json, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  return true;
}

static inline bool CliDeleteEntry(Arena *arena, const CliOptions *opts, int id,
                                  char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL);
  assert(id > 0);

  char path[64];
  snprintf(path, sizeof(path), "/entries/%d", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "DELETE", path, NULL, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  return true;
}

static inline bool CliAppendEntry(Arena *arena, const CliOptions *opts, int id,
                                  const char *text, const char *if_modified,
                                  char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && text != NULL && if_modified != NULL);
  assert(id > 0);

  JSONBuf req;
  jsonbuf_init_strict(&req, arena);
  jsonbuf_append(&req, "{\"text\":");
  jsonbuf_append_json_string(&req, text);
  jsonbuf_append(&req, ",\"if_modified\":");
  jsonbuf_append_json_string(&req, if_modified);
  jsonbuf_append(&req, "}");
  char path[64];
  snprintf(path, sizeof(path), "/entries/%d/append", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "POST", path, req.data, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  return true;
}

static inline bool CliListKinds(Arena *arena, const CliOptions *opts,
                                bool include_deleted, KindRows *out, char *err,
                                size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && out != NULL);

  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET",
                      include_deleted ? "/kinds?deleted=1" : "/kinds", NULL,
                      &body, &status, err, err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  if (body.len == 0 || body.data[0] != '[') {
    return CliFail(err, err_size, "expected a JSON array, got: %.*s",
                   (int)(body.len < 120 ? body.len : 120), body.data);
  }

  int count = 0;
  const char *cursor = NULL;
  JsonSpan item;
  while (json_array_next(body, &cursor, &item)) {
    count++;
  }
  out->count = count;
  out->items =
      count > 0 ? (KindRow *)arena_alloc(arena, sizeof(KindRow) * (size_t)count)
                : NULL;
  cursor = NULL;
  int i = 0;
  while (json_array_next(body, &cursor, &item) && i < count) {
    JsonSpan v;
    out->items[i].kind =
        json_member(item, "kind", &v) ? json_span_string(arena, v) : "";
    out->items[i].count =
        json_member(item, "count", &v) ? (int)json_span_long(v) : 0;
    out->items[i].last_modified_at_utc =
        json_member(item, "last_modified_at_utc", &v)
            ? json_span_string(arena, v)
            : "";
    i++;
  }
  return true;
}

// GET or PUT /kinds/roles (the server's lcars_kinds.h): the answer's JSON
// object, {"roles":[...],"entry":...,"error":...}. A 404 is a server older
// than the roles, said as such.
static inline bool CliRolesRequest(Arena *arena, const CliOptions *opts,
                                   const char *method, const char *body,
                                   JsonSpan *out, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && method != NULL && out != NULL);
  long status = 0;
  if (!CliHttpRequest(arena, opts, method, "/kinds/roles", body, out, &status,
                      err, err_size)) {
    return false;
  }
  if (status == 404) {
    return CliFail(err, err_size,
                   "this server has no /kinds/roles (it is older than "
                   "LCARS 0.273.0)");
  }
  if (status != 200) {
    return CliHttpStatusError(arena, *out, status, err, err_size);
  }
  JsonSpan roles;
  if (out->len == 0 || out->data[0] != '{' ||
      !json_member(*out, "roles", &roles) || roles.len == 0 ||
      roles.data[0] != '[') {
    return CliFail(err, err_size, "expected {\"roles\":[...]}, got: %.*s",
                   (int)(out->len < 120 ? out->len : 120), out->data);
  }
  return true;
}

// The kind `role` is on the server's journal, for a command that writes
// one (the Logseq import, the Strava pull). A server older than the roles
// has none to say: then `fallback` - the role's default, which is what such
// a server's journal always used - with a note on stderr. NULL (err set)
// when the server cannot be asked at all, or does not know the role.
static inline const char *CliRoleKind(Arena *arena, const CliOptions *opts,
                                      const char *role, const char *fallback,
                                      char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && role != NULL && fallback != NULL);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET", "/kinds/roles", NULL, &body, &status,
                      err, err_size)) {
    return NULL;
  }
  if (status == 404) {
    fprintf(stderr,
            "lcars-cli: the server has no /kinds/roles; the %s role is its "
            "default, %s\n",
            role, fallback);
    return fallback;
  }
  if (status != 200) {
    CliHttpStatusError(arena, body, status, err, err_size);
    return NULL;
  }
  JsonSpan roles, item, v;
  if (body.len > 0 && body.data[0] == '{' &&
      json_member(body, "roles", &roles)) {
    const char *cursor = NULL;
    while (json_array_next(roles, &cursor, &item)) {
      if (json_member(item, "role", &v) &&
          strcmp(json_span_string(arena, v), role) == 0 &&
          json_member(item, "kind", &v)) {
        const char *kind = json_span_string(arena, v);
        if (kind[0] != '\0') {
          return kind;
        }
      }
    }
  }
  CliFail(err, err_size, "the server's /kinds/roles has no %s role", role);
  return NULL;
}

static inline bool CliGetStats(Arena *arena, const CliOptions *opts,
                               const CliFilters *filters, StatsRow *out,
                               char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && filters != NULL && out != NULL);

  const char *path = CliBuildQueryPath(arena, "/stats", filters, false);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET", path, NULL, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }

  memset(out, 0, sizeof(*out));
  out->oldest_created_at_utc = "";
  out->newest_created_at_utc = "";
  out->last_modified_at_utc = "";
  JsonSpan v;
  if (json_member(body, "count", &v)) {
    out->count = (int)json_span_long(v);
  }
  if (json_member(body, "kinds", &v)) {
    out->kinds = (int)json_span_long(v);
  }
  if (json_member(body, "done", &v)) {
    out->done = (int)json_span_long(v);
  }
  if (json_member(body, "content_bytes", &v)) {
    out->content_bytes = json_span_long(v);
  }
  if (json_member(body, "oldest_created_at_utc", &v)) {
    out->oldest_created_at_utc = json_span_string(arena, v);
  }
  if (json_member(body, "newest_created_at_utc", &v)) {
    out->newest_created_at_utc = json_span_string(arena, v);
  }
  if (json_member(body, "last_modified_at_utc", &v)) {
    out->last_modified_at_utc = json_span_string(arena, v);
  }
  return true;
}

// ---------------------------------------------------------------------------
// A task's CalDAV side: the due date Apple Reminders shows
// ---------------------------------------------------------------------------
//
// `lcars-cli due` is the CLI's half of the web UI's "due friday at 5 pm".
// The due date is not an entries column: it is one of the VTODO lines kept
// verbatim for Reminders (caldav_tasks.extra_ical), which the server serves
// and checks at /entries/<id>/caldav. So this reads those lines, swaps the
// one DUE property, and writes them back with the ETag it read - a 412 if
// Reminders wrote in between, which is reported rather than overwritten.
// The lines are written the way the page writes them (cdavSet, cdavDateVal
// in lcars-ui/index.html): DUE in UTC with a Z, so it needs no VTIMEZONE,
// or a VALUE=DATE for an all-day one, placed after the last property and
// before the first component. HTTP only: the side table and its checks live
// in the server.

typedef struct CliCaldav {
  const char *extra_ical; // the kept lines, '\n'-separated
  const char *etag;
} CliCaldav;

static inline bool CliGetCaldav(Arena *arena, const CliOptions *opts, int id,
                                CliCaldav *out, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && out != NULL);
  assert(id > 0);

  char path[64];
  snprintf(path, sizeof(path), "/entries/%d/caldav", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "GET", path, NULL, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  JsonSpan v;
  out->extra_ical =
      json_member(body, "extra_ical", &v) ? json_span_string(arena, v) : "";
  out->etag = json_member(body, "etag", &v) ? json_span_string(arena, v) : "";
  return true;
}

static inline bool CliPutCaldav(Arena *arena, const CliOptions *opts, int id,
                                const char *extra_ical, const char *etag,
                                char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && extra_ical != NULL && etag != NULL);
  assert(id > 0);

  JSONBuf req;
  jsonbuf_init_strict(&req, arena);
  jsonbuf_append(&req, "{\"extra_ical\":");
  jsonbuf_append_json_string(&req, extra_ical);
  if (etag[0] != '\0') {
    jsonbuf_append(&req, ",\"etag\":");
    jsonbuf_append_json_string(&req, etag);
  }
  jsonbuf_append(&req, "}");

  char path[64];
  snprintf(path, sizeof(path), "/entries/%d/caldav", id);
  JsonSpan body;
  long status = 0;
  if (!CliHttpRequest(arena, opts, "PUT", path, req.data, &body, &status, err,
                      err_size)) {
    return false;
  }
  if (status != 200) {
    return CliHttpStatusError(arena, body, status, err, err_size);
  }
  return true;
}

// Is `line` the property `name` (followed by ';' or ':')? Case-insensitive,
// as iCalendar names are.
static inline bool CliIcalIs(const char *line, size_t len, const char *name) {
  assert(line != NULL && name != NULL);
  size_t n = strlen(name);
  return len > n && strncasecmp(line, name, n) == 0 &&
         (line[n] == ';' || line[n] == ':');
}

// The value of the top-level property `name` in `ical` (after its ':'), as
// a span into `ical`, or NULL. Inside a component (a VALARM's own
// properties) does not count.
static inline const char *CliIcalTopValue(const char *ical, const char *name,
                                          size_t *out_len) {
  assert(ical != NULL && name != NULL && out_len != NULL);
  int depth = 0;
  const char *p = ical;
  while (*p) {
    const char *eol = strchr(p, '\n');
    size_t len = eol ? (size_t)(eol - p) : strlen(p);
    size_t trimmed = (len > 0 && p[len - 1] == '\r') ? len - 1 : len;
    if (CliIcalIs(p, trimmed, "BEGIN")) {
      depth++;
    } else if (CliIcalIs(p, trimmed, "END")) {
      depth = depth > 0 ? depth - 1 : 0;
    } else if (depth == 0 && CliIcalIs(p, trimmed, name)) {
      const char *colon = memchr(p, ':', trimmed);
      if (colon) {
        *out_len = trimmed - (size_t)(colon + 1 - p);
        return colon + 1;
      }
    }
    if (!eol) {
      break;
    }
    p = eol + 1;
  }
  return NULL;
}

// The kept lines with the top-level DUE replaced by `due_line` (a whole
// "DUE...:value" line), or removed when it is NULL. A DTSTART later than the
// new due is pulled back to it, as the page does - Reminders refuses a start
// after the due. Both must be UTC (…Z) for that comparison, which is what
// this and the page write; any other form is left alone. `alarm_block`, when
// given, is appended whole (a VALARM). Other lines keep their order.
static inline const char *CliIcalSetDue(Arena *arena, const char *ical,
                                        const char *due_line,
                                        const char *due_value,
                                        const char *alarm_block) {
  assert(arena_valid(arena));
  assert(ical != NULL);
  assert((due_line == NULL) == (due_value == NULL));

  JSONBuf out;
  jsonbuf_init_strict(&out, arena);
  bool placed = (due_line == NULL);
  int depth = 0;
  const char *p = ical;
  while (*p) {
    const char *eol = strchr(p, '\n');
    size_t len = eol ? (size_t)(eol - p) : strlen(p);
    size_t trimmed = (len > 0 && p[len - 1] == '\r') ? len - 1 : len;
    bool skip = trimmed == 0;
    if (CliIcalIs(p, trimmed, "BEGIN")) {
      if (depth == 0 && !placed) {
        jsonbuf_append(&out, due_line);
        jsonbuf_append(&out, "\n");
        placed = true;
      }
      depth++;
    } else if (CliIcalIs(p, trimmed, "END")) {
      depth = depth > 0 ? depth - 1 : 0;
    } else if (depth == 0 && CliIcalIs(p, trimmed, "DUE")) {
      skip = true;
    } else if (depth == 0 && due_value != NULL &&
               CliIcalIs(p, trimmed, "DTSTART")) {
      const char *colon = memchr(p, ':', trimmed);
      size_t vlen = colon ? trimmed - (size_t)(colon + 1 - p) : 0;
      size_t due_len = strlen(due_value);
      // "YYYYMMDDTHHMMSSZ" is 16 bytes, and two of them compare as text.
      if (colon && vlen == 16 && due_len == 16 && colon[16] == 'Z' &&
          due_value[15] == 'Z' && strncmp(colon + 1, due_value, 16) > 0) {
        jsonbuf_append(&out, "DTSTART:");
        jsonbuf_append(&out, due_value);
        jsonbuf_append(&out, "\n");
        skip = true;
      }
    }
    if (!skip) {
      jsonbuf_append_len(&out, p, trimmed);
      jsonbuf_append(&out, "\n");
    }
    if (!eol) {
      break;
    }
    p = eol + 1;
  }
  if (!placed) {
    jsonbuf_append(&out, due_line);
    jsonbuf_append(&out, "\n");
  }
  if (alarm_block) {
    jsonbuf_append(&out, alarm_block);
  }
  return out.data;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

// Rebuilds the API's own JSON for a row, from the fields this tool parsed:
// `--json` prints exactly what the table was made from.
static inline void CliAppendEntryJSON(JSONBuf *b, const EntryRow *row) {
  assert(b != NULL);
  assert(row != NULL);

  jsonbuf_appendf(b, "{\"id\":%d,\"kind\":", row->id);
  jsonbuf_append_json_string(b, row->kind);
  jsonbuf_append(b, ",\"title\":");
  jsonbuf_append_json_string(b, row->title);
  if (row->content) {
    jsonbuf_append(b, ",\"content\":");
    jsonbuf_append_json_string(b, row->content);
  }
  jsonbuf_appendf(b,
                  ",\"content_length\":%d,\"value_int\":%d,\"value_float\":%f,"
                  "\"done_bool\":%d,\"deleted\":%d,\"created_at_utc\":",
                  row->content_length, row->value_int, row->value_float,
                  row->done_bool, row->deleted);
  jsonbuf_append_json_string(b, row->created_at_utc);
  jsonbuf_append(b, ",\"last_modified_at_utc\":");
  jsonbuf_append_json_string(b, row->last_modified_at_utc);
  jsonbuf_append(b, ",\"start_date\":");
  jsonbuf_append_json_string(b, row->start_date);
  jsonbuf_append(b, ",\"end_date\":");
  jsonbuf_append_json_string(b, row->end_date);
  jsonbuf_append(b, "}");
}

// Collapses a value to one printable line of at most `max_width` bytes for
// the table view. Titles are user text: they can contain newlines and tabs,
// and one of those in a column would break the whole layout.
static inline const char *cli_one_line(Arena *arena, const char *s,
                                       int max_width) {
  assert(arena_valid(arena));
  assert(max_width > 3);

  if (!s) {
    s = "";
  }
  size_t len = strlen(s);
  char *out = (char *)arena_alloc(arena, (size_t)max_width + 4);
  size_t o = 0;
  for (size_t i = 0; i < len && o < (size_t)max_width; i++) {
    unsigned char c = (unsigned char)s[i];
    out[o++] = (c < 0x20 || c == 0x7F) ? ' ' : (char)c;
  }
  if (len > (size_t)max_width) {
    // Overwrite the tail rather than append: the buffer is sized for the
    // column, and a truncation marker has to fit inside it.
    assert(o >= 3);
    out[o - 3] = '.';
    out[o - 2] = '.';
    out[o - 1] = '.';
  }
  out[o] = '\0';
  return out;
}

static inline void CliPrintEntries(Arena *arena, const CliOptions *opts,
                                   const EntryRows *rows) {
  assert(arena_valid(arena));
  assert(opts != NULL && rows != NULL);

  if (opts->json) {
    JSONBuf out;
    jsonbuf_init_strict(&out, arena);
    jsonbuf_append(&out, "[");
    for (int i = 0; i < rows->count; i++) {
      if (i > 0) {
        jsonbuf_append(&out, ",");
      }
      CliAppendEntryJSON(&out, &rows->items[i]);
    }
    jsonbuf_append(&out, "]");
    printf("%s\n", out.data);
    return;
  }

  if (rows->count == 0) {
    printf("no entries\n");
    return;
  }

  int kind_width = 4;
  for (int i = 0; i < rows->count; i++) {
    int len = (int)strlen(rows->items[i].kind);
    if (len > kind_width) {
      kind_width = len;
    }
  }
  if (kind_width > 20) {
    kind_width = 20;
  }

  printf("%6s  %-*s  %-19s  %6s  %2s  %s\n", "ID", kind_width, "KIND",
         "MODIFIED (UTC)", "BYTES", "FL", "TITLE");
  for (int i = 0; i < rows->count; i++) {
    const EntryRow *row = &rows->items[i];
    // Two flag columns rather than two more headings: `d` = soft-deleted,
    // `x` = done.
    char flags[3];
    flags[0] = row->deleted ? 'd' : '-';
    flags[1] = row->done_bool ? 'x' : '-';
    flags[2] = '\0';
    printf("%6d  %-*s  %-19s  %6d  %2s  %s\n", row->id, kind_width,
           cli_one_line(arena, row->kind, kind_width),
           cli_one_line(arena, row->last_modified_at_utc, 19),
           row->content_length, flags, cli_one_line(arena, row->title, 60));
  }
}

static inline void CliPrintEntry(Arena *arena, const CliOptions *opts,
                                 const EntryRow *row) {
  assert(arena_valid(arena));
  assert(opts != NULL && row != NULL);

  if (opts->json) {
    JSONBuf out;
    jsonbuf_init_strict(&out, arena);
    CliAppendEntryJSON(&out, row);
    printf("%s\n", out.data);
    return;
  }
  if (opts->raw) {
    // Content only, so `lcars-cli get 12 --raw > file` is a usable export.
    printf("%s", row->content ? row->content : "");
    size_t len = row->content ? strlen(row->content) : 0;
    if (len == 0 || row->content[len - 1] != '\n') {
      printf("\n");
    }
    return;
  }

  printf("id           : %d\n", row->id);
  printf("kind         : %s\n", row->kind);
  printf("title        : %s\n", row->title);
  printf("created      : %s\n", row->created_at_utc);
  printf("modified     : %s\n", row->last_modified_at_utc);
  if (row->start_date[0] != '\0' || row->end_date[0] != '\0') {
    printf("scheduled    : %s .. %s\n", row->start_date, row->end_date);
  }
  printf("done         : %d\n", row->done_bool);
  printf("deleted      : %d\n", row->deleted);
  printf("value_int    : %d\n", row->value_int);
  printf("value_float  : %g\n", row->value_float);
  printf("length       : %d\n", row->content_length);
  if (row->content) {
    printf("-----\n%s", row->content);
    size_t len = strlen(row->content);
    if (len == 0 || row->content[len - 1] != '\n') {
      printf("\n");
    }
  }
}

static inline void CliPrintKinds(Arena *arena, const CliOptions *opts,
                                 const KindRows *kinds) {
  assert(arena_valid(arena));
  assert(opts != NULL && kinds != NULL);

  if (opts->json) {
    JSONBuf out;
    jsonbuf_init_strict(&out, arena);
    jsonbuf_append(&out, "[");
    for (int i = 0; i < kinds->count; i++) {
      if (i > 0) {
        jsonbuf_append(&out, ",");
      }
      jsonbuf_append(&out, "{\"kind\":");
      jsonbuf_append_json_string(&out, kinds->items[i].kind);
      jsonbuf_appendf(&out, ",\"count\":%d,\"last_modified_at_utc\":",
                      kinds->items[i].count);
      jsonbuf_append_json_string(&out, kinds->items[i].last_modified_at_utc);
      jsonbuf_append(&out, "}");
    }
    jsonbuf_append(&out, "]");
    printf("%s\n", out.data);
    return;
  }

  if (kinds->count == 0) {
    printf("no kinds\n");
    return;
  }
  int kind_width = 4;
  for (int i = 0; i < kinds->count; i++) {
    int len = (int)strlen(kinds->items[i].kind);
    if (len > kind_width) {
      kind_width = len;
    }
  }
  if (kind_width > 32) {
    kind_width = 32;
  }
  printf("%-*s  %6s  %s\n", kind_width, "KIND", "COUNT", "NEWEST (UTC)");
  for (int i = 0; i < kinds->count; i++) {
    printf("%-*s  %6d  %s\n", kind_width,
           cli_one_line(arena, kinds->items[i].kind, kind_width),
           kinds->items[i].count, kinds->items[i].last_modified_at_utc);
  }
}

static inline void CliPrintStats(const CliOptions *opts, const StatsRow *st) {
  assert(opts != NULL && st != NULL);

  if (opts->json) {
    printf("{\"count\":%d,\"kinds\":%d,\"done\":%d,\"content_bytes\":%lld,"
           "\"oldest_created_at_utc\":\"%s\",\"newest_created_at_utc\":\"%s\","
           "\"last_modified_at_utc\":\"%s\"}\n",
           st->count, st->kinds, st->done, st->content_bytes,
           st->oldest_created_at_utc, st->newest_created_at_utc,
           st->last_modified_at_utc);
    return;
  }
  printf("entries       : %d\n", st->count);
  printf("kinds         : %d\n", st->kinds);
  printf("done          : %d\n", st->done);
  printf("content bytes : %lld\n", st->content_bytes);
  printf("oldest        : %s\n", st->oldest_created_at_utc);
  printf("newest        : %s\n", st->newest_created_at_utc);
  printf("last modified : %s\n", st->last_modified_at_utc);
}

// ---------------------------------------------------------------------------
// Content sources: a file, stdin, or $EDITOR
// ---------------------------------------------------------------------------

// Reads a whole file (or stdin, for "-") into the arena. Entry bodies have
// no useful maximum, so this grows rather than assuming a size.
static inline const char *CliReadFile(Arena *arena, const char *path, char *err,
                                      size_t err_size) {
  assert(arena_valid(arena));
  assert(path != NULL);

  FILE *f = (strcmp(path, "-") == 0) ? stdin : fopen(path, "rb");
  if (!f) {
    CliFail(err, err_size, "cannot read '%s'", path);
    return NULL;
  }

  JSONBuf buf;
  jsonbuf_init_strict(&buf, arena);
  char chunk[8192];
  size_t n;
  while ((n = fread(chunk, 1, sizeof(chunk), f)) > 0) {
    jsonbuf_append_len(&buf, chunk, n);
  }
  bool read_error = ferror(f) != 0;
  if (f != stdin) {
    fclose(f);
  }
  if (read_error) {
    CliFail(err, err_size, "error reading '%s'", path);
    return NULL;
  }
  return buf.data;
}

// Opens $EDITOR on a temp file seeded with `initial` and returns what came
// back. This is the only sane way to edit a journal entry from a shell -
// --content is fine for one line, hopeless for a paragraph.
static inline bool CliEditText(Arena *arena, const char *initial,
                               const char **out, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(out != NULL);

  const char *editor = getenv("EDITOR");
  if (!editor || editor[0] == '\0') {
    editor = getenv("VISUAL");
  }
  if (!editor || editor[0] == '\0') {
    editor = "vi";
  }

  char path[] = "/tmp/lcars-cli-XXXXXX";
  int fd = mkstemp(path);
  if (fd < 0) {
    return CliFail(err, err_size, "cannot create a temporary file");
  }
  if (initial && initial[0] != '\0') {
    size_t len = strlen(initial);
    if (write(fd, initial, len) != (ssize_t)len) {
      close(fd);
      unlink(path);
      return CliFail(err, err_size, "cannot write the temporary file");
    }
  }
  close(fd);

  // The path is mkstemp's own (no shell metacharacters); the editor command
  // is the user's own environment, and is deliberately passed to the shell
  // so `EDITOR="code -w"` works.
  char command[1024];
  int n = snprintf(command, sizeof(command), "%s %s", editor, path);
  assert(n > 0 && (size_t)n < sizeof(command));
  int rc = system(command);
  if (rc != 0) {
    unlink(path);
    return CliFail(err, err_size, "editor '%s' exited with %d", editor, rc);
  }

  const char *text = CliReadFile(arena, path, err, err_size);
  unlink(path);
  if (!text) {
    return false;
  }
  *out = text;
  return true;
}

#endif // LCARS_IMPLEMENTATION
#endif // LCARS_CLI_H
