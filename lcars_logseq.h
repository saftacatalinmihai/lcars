#ifndef LCARS_LOGSEQ_H
#define LCARS_LOGSEQ_H

// lcars_logseq.h - the Logseq bridge: the other half of lcars-cli.
//
// Two directions, one file:
//
//   import   Logseq -> lcars. The journals written before this app existed
//            (and the standalone pages beside them) become `entries` rows,
//            backdated to the day Logseq says they belong to.
//   export   lcars -> Logseq. Today's entries are appended to today's
//            journal page as `HH:MM [kind] text` blocks - the exact shape
//            these journals were already being filled in by hand, so an
//            export over a day that was done manually is a no-op.
//
// Everything goes through Logseq's local HTTP API (`POST /api`, a bearer
// token, `{"method": ..., "args": [...]}`). The graph directory is never
// touched directly: Logseq holds the file contents in memory and rewrites
// them on its own schedule, so a file written behind its back is a file it
// will overwrite. `:file/content` in a datascript query is the same bytes
// on disk, read the supported way.
//
// Timestamps are the whole point of the import, and Logseq has exactly one
// trustworthy one. `:block/created-at` / `:block/updated-at` are stamped at
// *re-index* time (every page in a re-indexed graph shares a single
// timestamp to the millisecond), and the files inherit the mtime of
// whatever sync last copied them. What survives is `:block/journal-day` -
// 20210211 - because it is derived from the page's name. So a journal is
// backdated to its own day and a page, which has no day at all, is not
// backdated; see LogseqImportPages.
//
// Shape follows every other module here: declarations first, bodies under
// LCARS_IMPLEMENTATION. Included from lcars_cli.c, after lcars_cli.h -
// this file builds on that one's arena, JSON scanner, JSONBuf and entry
// requests, and reaches nothing else.

#include "lcars_cli.h"

#include <time.h>

// ---------------------------------------------------------------------------
// Tuning
// ---------------------------------------------------------------------------

// Logseq's HTTP API server, as configured in Settings -> Features -> HTTP
// APIs. LOGSEQ_URL / LOGSEQ_TOKEN override, --logseq-url / --logseq-token
// override those.
#define LOGSEQ_DEFAULT_URL "http://127.0.0.1:12315"

// Imported journals and pages get their own kinds so the imported history
// stays separable from what lcars recorded itself - a bad import is one
// `DELETE FROM entries WHERE kind = '<the journal kind>'` away from gone,
// which would not be true if this merged into the log. They are the
// `logseq_journal` and `page` roles' kinds, asked of the server (CliRoleKind);
// these are the roles' defaults, for a server older than the roles.
#define LOGSEQ_JOURNAL_KIND "logseq_journal"
#define LOGSEQ_PAGE_KIND "page"

// The day lcars started recording (its oldest created_at_utc). From here on
// the Logseq journals are copies of lcars entries rather than the original
// record, so importing them would duplicate what is already in the database.
// The import stops the day before unless --until says otherwise.
#define LOGSEQ_LCARS_FIRST_DAY 20260711

// Entry titles the app itself writes when a client did not supply one.
// Carrying them into a Logseq block would put "HTTP Entry" in front of
// every line of the journal.
#define LOGSEQ_GENERIC_TITLE "HTTP Entry"
#define LOGSEQ_GENERIC_TEXT_TITLE "HTTP Text Entry"

// Pages whose file lives under this prefix are journals; everything else is
// a page. Taken from the file path rather than :block/journal-day so a
// journal whose day failed to parse is still classified correctly.
#define LOGSEQ_JOURNALS_DIR "journals/"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

typedef struct LogseqOptions {
  const char *base_url; // scheme://host:port, no trailing slash
  const char *token;    // bearer token, NULL for none
  long timeout_seconds;
} LogseqOptions;

// One Logseq page that has a file behind it. Pages without a file are the
// stubs Logseq creates for every [[link]] and #tag ever typed - there are
// hundreds of them in a real graph and none of them has content.
typedef struct LogseqPage {
  const char *name;          // lowercased lookup key, e.g. "feb 11th, 2021"
  const char *original_name; // display name, e.g. "Feb 11th, 2021"
  const char *file_path;     // "journals/2021_02_11.md"
  int journal_day;           // 20210211, or 0 for a non-journal page
  bool is_journal;
} LogseqPage;

typedef struct LogseqPages {
  LogseqPage *items;
  int count;
} LogseqPages;

// One top-level block of a page, as the export side sees it: `hhmm` and
// `kind` are filled in when the block's first line parses as an lcars
// export line, and are -1/NULL when it is something the user wrote by hand.
typedef struct LogseqBlock {
  const char *uuid;
  const char *content;
  int hhmm; // minutes-of-day 0..1439, -1 when not an export line
  const char *kind;
} LogseqBlock;

typedef struct LogseqBlocks {
  LogseqBlock *items;
  int count;
} LogseqBlocks;

// What an import or export did, for the summary line and for --dry-run
// (which fills the same counters without writing anything).
typedef struct LogseqSyncStats {
  int considered;
  int written;
  int skipped_existing;
  int skipped_empty;
  int failed;
} LogseqSyncStats;

// ---------------------------------------------------------------------------
// Declarations
// ---------------------------------------------------------------------------

static inline bool LogseqCall(Arena *arena, const LogseqOptions *opts,
                              const char *method, const char *args_json,
                              JsonSpan *out_result, char *err, size_t err_size);
static inline bool LogseqQuery(Arena *arena, const LogseqOptions *opts,
                               const char *datascript, JsonSpan *out_result,
                               char *err, size_t err_size);
static inline bool LogseqListPages(Arena *arena, const LogseqOptions *opts,
                                   LogseqPages *out, char *err,
                                   size_t err_size);
static inline bool LogseqFileContent(Arena *arena, const LogseqOptions *opts,
                                     const char *file_path,
                                     const char **out_markdown, char *err,
                                     size_t err_size);
static inline bool LogseqPageBlocks(Arena *arena, const LogseqOptions *opts,
                                    const char *page_name, LogseqBlocks *out,
                                    char *err, size_t err_size);
static inline bool LogseqAppendBlock(Arena *arena, const LogseqOptions *opts,
                                     const char *page_name, const char *content,
                                     char *err, size_t err_size);
static inline bool LogseqInsertBefore(Arena *arena, const LogseqOptions *opts,
                                      const char *block_uuid,
                                      const char *content, char *err,
                                      size_t err_size);
static inline bool LogseqFindJournal(Arena *arena, const LogseqOptions *opts,
                                     int day, const char **out_page_name,
                                     char *err, size_t err_size);
static inline bool LogseqEnsureJournal(Arena *arena, const LogseqOptions *opts,
                                       int day, const char **out_page_name,
                                       char *err, size_t err_size);

static inline int LogseqDayFromISO(const char *iso); // "2021-02-11"
static inline const char *LogseqISOFromDay(Arena *arena, int day);
static inline const char *LogseqJournalTitle(Arena *arena, int day);
static inline bool LogseqLocalSlot(const char *utc_ts, int *out_day,
                                   int *out_hhmm);
static inline bool LogseqDayUTCRange(int day, char *from, size_t from_size,
                                     char *to, size_t to_size);
static inline bool LogseqParseExportLine(Arena *arena, const char *content,
                                         int *out_hhmm, const char **out_kind);
static inline const char *
LogseqFormatExportBlock(Arena *arena, const EntryRow *row, int hhmm);

#ifdef LCARS_IMPLEMENTATION

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

// One call into Logseq's API. The transport half mirrors CliHttpRequest -
// it does not reuse it because that one speaks Basic auth against a
// CliOptions, and this one needs a bearer token against a different server.
//
// Logseq reports failures two different ways: a non-200 status, and a 200
// carrying {"error": "..."}. Both land here as false with err filled in,
// because a caller that had to remember the second one would eventually
// forget and treat an error object as an empty result.
static inline bool LogseqCall(Arena *arena, const LogseqOptions *opts,
                              const char *method, const char *args_json,
                              JsonSpan *out_result, char *err,
                              size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && opts->base_url != NULL);
  assert(method != NULL);
  assert(out_result != NULL);

  out_result->data = "";
  out_result->len = 0;

  JSONBuf body;
  jsonbuf_init_strict(&body, arena);
  jsonbuf_append(&body, "{\"method\":");
  jsonbuf_append_json_string(&body, method);
  if (args_json && args_json[0] != '\0') {
    jsonbuf_append(&body, ",\"args\":");
    jsonbuf_append(&body, args_json);
  }
  jsonbuf_append(&body, "}");

  JSONBuf url;
  jsonbuf_init_strict(&url, arena);
  jsonbuf_append(&url, opts->base_url);
  jsonbuf_append(&url, "/api");

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

  struct curl_slist *headers =
      curl_slist_append(NULL, "Content-Type: application/json");
  char auth[512];
  if (opts->token && opts->token[0] != '\0') {
    int n =
        snprintf(auth, sizeof(auth), "Authorization: Bearer %s", opts->token);
    assert(n > 0);
    if ((size_t)n < sizeof(auth)) {
      headers = curl_slist_append(headers, auth);
    }
  }

  curl_easy_setopt(curl, CURLOPT_URL, url.data);
  curl_easy_setopt(curl, CURLOPT_POST, 1L);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.data);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body.data));
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, CliCurlWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, opts->timeout_seconds);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "lcars-cli/1.0");

  CURLcode res = curl_easy_perform(curl);
  long status = 0;
  if (res == CURLE_OK) {
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
  }
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  if (res != CURLE_OK) {
    return CliFail(err, err_size,
                   "logseq %s: %s (is the HTTP API server enabled at %s?)",
                   method, curl_easy_strerror(res), opts->base_url);
  }

  JsonSpan result;
  result.data = chunk.data;
  result.len = chunk.size;

  if (status == 401 || status == 403) {
    return CliFail(err, err_size,
                   "logseq %s: HTTP %ld - check --logseq-token / LOGSEQ_TOKEN",
                   method, status);
  }
  if (status != 200) {
    return CliFail(err, err_size, "logseq %s: HTTP %ld: %.*s", method, status,
                   (int)(result.len < 200 ? result.len : 200), result.data);
  }

  JsonSpan error_span;
  if (result.len > 0 && result.data[0] == '{' &&
      json_member(result, "error", &error_span)) {
    return CliFail(err, err_size, "logseq %s: %s", method,
                   json_span_string(arena, error_span));
  }

  *out_result = result;
  return true;
}

static inline bool LogseqQuery(Arena *arena, const LogseqOptions *opts,
                               const char *datascript, JsonSpan *out_result,
                               char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(datascript != NULL);

  JSONBuf args;
  jsonbuf_init_strict(&args, arena);
  jsonbuf_append(&args, "[");
  jsonbuf_append_json_string(&args, datascript);
  jsonbuf_append(&args, "]");
  return LogseqCall(arena, opts, "logseq.DB.datascriptQuery", args.data,
                    out_result, err, err_size);
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

// Midnight UTC of a YYYYMMDD day, in seconds since the epoch: timegm,
// which reads no zone (lcars_cli.c asks for it with _DEFAULT_SOURCE), and
// rolls an out-of-range day over into the next month.
static inline long long logseq_day_epoch(int day, int delta) {
  struct tm tm = {.tm_year = day / 10000 - 1900,
                  .tm_mon = (day / 100) % 100 - 1,
                  .tm_mday = day % 100 + delta};
  return (long long)timegm(&tm);
}

static inline int LogseqDayFromISO(const char *iso) {
  assert(iso != NULL);

  // "YYYY-MM-DD", optionally with a time after it.
  if (strlen(iso) < 10 || iso[4] != '-' || iso[7] != '-') {
    return 0;
  }
  for (int i = 0; i < 10; i++) {
    if (i == 4 || i == 7) {
      continue;
    }
    if (iso[i] < '0' || iso[i] > '9') {
      return 0;
    }
  }
  int year = (iso[0] - '0') * 1000 + (iso[1] - '0') * 100 +
             (iso[2] - '0') * 10 + (iso[3] - '0');
  int month = (iso[5] - '0') * 10 + (iso[6] - '0');
  int day = (iso[8] - '0') * 10 + (iso[9] - '0');
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return 0;
  }
  return year * 10000 + month * 100 + day;
}

static inline const char *LogseqISOFromDay(Arena *arena, int day) {
  assert(arena_valid(arena));
  assert(day >= 10000101 && day <= 99991231);

  char *out = (char *)arena_alloc(arena, 11);
  int n = snprintf(out, 11, "%04d-%02d-%02d", day / 10000, (day / 100) % 100,
                   day % 100);
  assert(n == 10);
  (void)n;
  return out;
}

// The page name Logseq gives a journal, e.g. 20260815 -> "Aug 15th, 2026".
// That is this graph's :journal/page-title-format ("MMM do, yyyy"), which
// is also Logseq's default. LogseqEnsureJournal only falls back to this for
// a day that has no page yet: an existing journal is always addressed by
// the name the graph itself reports, so a graph configured differently
// still exports correctly to every day it already has.
static inline const char *LogseqJournalTitle(Arena *arena, int day) {
  assert(arena_valid(arena));
  assert(day >= 10000101 && day <= 99991231);

  static const char *months[12] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  int year = day / 10000;
  int month = (day / 100) % 100;
  int mday = day % 100;
  assert(month >= 1 && month <= 12);

  // 11th/12th/13th are the exceptions every ordinal-suffix routine gets
  // wrong the first time.
  const char *suffix = "th";
  if (mday < 11 || mday > 13) {
    switch (mday % 10) {
    case 1:
      suffix = "st";
      break;
    case 2:
      suffix = "nd";
      break;
    case 3:
      suffix = "rd";
      break;
    default:
      break;
    }
  }

  char *out = (char *)arena_alloc(arena, 32);
  int n =
      snprintf(out, 32, "%s %d%s, %d", months[month - 1], mday, suffix, year);
  assert(n > 0 && n < 32);
  (void)n;
  return out;
}

// "YYYY-MM-DD HH:MM:SS" (UTC, the shape every entries timestamp has) to the
// local day and minute-of-day it falls on. The export writes local wall
// clock because that is what the hand-written journals hold: an entry
// stamped 20:46:34 UTC was typed at 23:46 at UTC+3 and belongs under
// that day's page, not the next one.
static inline bool LogseqLocalSlot(const char *utc_ts, int *out_day,
                                   int *out_hhmm) {
  assert(utc_ts != NULL);
  assert(out_day != NULL && out_hhmm != NULL);

  int day = LogseqDayFromISO(utc_ts);
  if (day == 0) {
    return false;
  }
  int hour = 0, minute = 0, second = 0;
  if (strlen(utc_ts) >= 19) {
    hour = (utc_ts[11] - '0') * 10 + (utc_ts[12] - '0');
    minute = (utc_ts[14] - '0') * 10 + (utc_ts[15] - '0');
    second = (utc_ts[17] - '0') * 10 + (utc_ts[18] - '0');
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 ||
        second > 60) {
      return false;
    }
  }

  time_t epoch =
      (time_t)(logseq_day_epoch(day, 0) + hour * 3600 + minute * 60 + second);
  struct tm local;
  if (!localtime_r(&epoch, &local)) {
    return false;
  }
  *out_day =
      (local.tm_year + 1900) * 10000 + (local.tm_mon + 1) * 100 + local.tm_mday;
  *out_hhmm = local.tm_hour * 60 + local.tm_min;

  assert(*out_hhmm >= 0 && *out_hhmm < 24 * 60);
  return true;
}

// The inverse, for selecting a day's entries: the *inclusive* UTC range
// [from, to] that covers local day `day`. Inclusive because that is what
// `since`/`until` mean to the server (>= and <=), and a half-open
// bound would need the same subtraction repeated at every call site.
// mktime is the right tool here - it is the one libc function that maps
// local wall clock back to an epoch, DST included (tm_isdst = -1 asks it to
// work that out), which matters twice a year for the two days whose local
// midnight is not 24 hours from the next one's.
static inline bool LogseqDayUTCRange(int day, char *from, size_t from_size,
                                     char *to, size_t to_size) {
  assert(day >= 10000101 && day <= 99991231);
  assert(from != NULL && to != NULL);
  assert(from_size >= 20 && to_size >= 20);

  struct tm start = {0};
  start.tm_year = day / 10000 - 1900;
  start.tm_mon = (day / 100) % 100 - 1;
  start.tm_mday = day % 100;
  start.tm_isdst = -1;
  time_t start_epoch = mktime(&start);
  if (start_epoch == (time_t)-1) {
    return false;
  }

  struct tm end = {0};
  end.tm_year = start.tm_year;
  end.tm_mon = start.tm_mon;
  end.tm_mday = start.tm_mday + 1; // mktime normalizes the month rollover
  end.tm_isdst = -1;
  time_t end_epoch = mktime(&end);
  if (end_epoch == (time_t)-1) {
    return false;
  }
  end_epoch -= 1; // inclusive: the last second that is still this local day

  struct tm gm;
  if (!gmtime_r(&start_epoch, &gm) ||
      strftime(from, from_size, "%Y-%m-%d %H:%M:%S", &gm) == 0) {
    return false;
  }
  if (!gmtime_r(&end_epoch, &gm) ||
      strftime(to, to_size, "%Y-%m-%d %H:%M:%S", &gm) == 0) {
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// The export line format
// ---------------------------------------------------------------------------

// Recognizes "HH:MM [kind] ..." at the start of a block. This is the format
// the journals were already being written in by hand, and matching it is
// what makes an export idempotent: a day that was copied over manually is
// recognized as already exported and left alone.
//
// Returns false for anything else - a free-form bullet - which is the
// signal to leave that block untouched.
static inline bool LogseqParseExportLine(Arena *arena, const char *content,
                                         int *out_hhmm, const char **out_kind) {
  assert(arena_valid(arena));
  assert(content != NULL);
  assert(out_hhmm != NULL && out_kind != NULL);

  *out_hhmm = -1;
  *out_kind = NULL;

  const char *p = content;
  while (*p == ' ' || *p == '\t' || *p == '-') {
    p++;
  }
  if (!(p[0] >= '0' && p[0] <= '9') || !(p[1] >= '0' && p[1] <= '9') ||
      p[2] != ':' || !(p[3] >= '0' && p[3] <= '9') ||
      !(p[4] >= '0' && p[4] <= '9')) {
    return false;
  }
  int hour = (p[0] - '0') * 10 + (p[1] - '0');
  int minute = (p[3] - '0') * 10 + (p[4] - '0');
  if (hour > 23 || minute > 59) {
    return false;
  }
  p += 5;
  while (*p == ' ') {
    p++;
  }
  if (*p != '[') {
    return false;
  }
  const char *kind_start = ++p;
  while (*p != '\0' && *p != ']' && *p != '\n') {
    p++;
  }
  if (*p != ']') {
    return false;
  }

  size_t kind_len = (size_t)(p - kind_start);
  char *kind = (char *)arena_alloc(arena, kind_len + 1);
  memcpy(kind, kind_start, kind_len);
  kind[kind_len] = '\0';

  *out_hhmm = hour * 60 + minute;
  *out_kind = kind;
  assert(*out_hhmm >= 0 && *out_hhmm < 24 * 60);
  return true;
}

// The other direction. `hhmm` is the local minute-of-day LogseqLocalSlot
// worked out; the caller has it already and passing it in keeps this
// function from re-deriving a time it might derive differently.
//
// A title only makes it into the block when it is one the user actually
// typed: everything posted to the HTTP API without a title gets "HTTP
// Entry", and repeating that on every line would bury the journal.
static inline const char *
LogseqFormatExportBlock(Arena *arena, const EntryRow *row, int hhmm) {
  assert(arena_valid(arena));
  assert(row != NULL);
  assert(hhmm >= 0 && hhmm < 24 * 60);

  const char *kind = (row->kind && row->kind[0]) ? row->kind : "entry";
  bool has_title = row->title != NULL && row->title[0] != '\0' &&
                   strcmp(row->title, LOGSEQ_GENERIC_TITLE) != 0 &&
                   strcmp(row->title, LOGSEQ_GENERIC_TEXT_TITLE) != 0;
  const char *content = row->content ? row->content : "";

  JSONBuf b;
  jsonbuf_init_strict(&b, arena);
  jsonbuf_appendf(&b, "%02d:%02d [%s]", hhmm / 60, hhmm % 60, kind);
  if (has_title) {
    jsonbuf_append(&b, " ");
    jsonbuf_append(&b, row->title);
    if (content[0] != '\0') {
      jsonbuf_append(&b, "\n");
      jsonbuf_append(&b, content);
    }
  } else if (content[0] != '\0') {
    jsonbuf_append(&b, " ");
    jsonbuf_append(&b, content);
  }
  return b.data;
}

// ---------------------------------------------------------------------------
// Reading the graph
// ---------------------------------------------------------------------------

// Every page that has a file behind it, in one query.
//
// `[?p :block/file ?f]` is the filter that matters: Logseq materializes a
// page entity for every [[link]] and #tag ever written, and in this graph
// that is roughly 60% of the page table. Those have no file, no content and
// no date - importing them would create hundreds of empty entries named
// after words.
static inline bool LogseqListPages(Arena *arena, const LogseqOptions *opts,
                                   LogseqPages *out, char *err,
                                   size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && out != NULL);

  out->items = NULL;
  out->count = 0;

  JsonSpan result;
  if (!LogseqQuery(arena, opts,
                   "[:find (pull ?p [:block/name :block/original-name "
                   ":block/journal-day {:block/file [:file/path]}]) "
                   ":where [?p :block/file ?f]]",
                   &result, err, err_size)) {
    return false;
  }
  if (result.len == 0 || result.data[0] != '[') {
    return CliFail(err, err_size, "logseq page query returned no array");
  }

  // Two passes so the array can be a single allocation: datascript answers
  // with [[{...}], [{...}], ...] - one-element tuples wrapping the pull.
  int count = 0;
  const char *cursor = NULL;
  JsonSpan tuple;
  while (json_array_next(result, &cursor, &tuple)) {
    count++;
  }
  if (count == 0) {
    return true;
  }

  LogseqPage *items =
      (LogseqPage *)arena_alloc(arena, sizeof(LogseqPage) * (size_t)count);
  int n = 0;
  cursor = NULL;
  while (json_array_next(result, &cursor, &tuple) && n < count) {
    const char *inner = NULL;
    JsonSpan page;
    if (!json_array_next(tuple, &inner, &page)) {
      continue;
    }

    LogseqPage *item = &items[n];
    JsonSpan field;
    item->name =
        json_member(page, "name", &field) ? json_span_string(arena, field) : "";
    item->original_name = json_member(page, "original-name", &field)
                              ? json_span_string(arena, field)
                              : item->name;
    item->journal_day = json_member(page, "journal-day", &field)
                            ? (int)json_span_long(field)
                            : 0;
    item->file_path = "";
    JsonSpan file;
    if (json_member(page, "file", &file) && json_member(file, "path", &field)) {
      item->file_path = json_span_string(arena, field);
    }
    item->is_journal = strncmp(item->file_path, LOGSEQ_JOURNALS_DIR,
                               sizeof(LOGSEQ_JOURNALS_DIR) - 1) == 0;

    // A path is required (there is nothing to read without one) and it has
    // to be markdown: a graph also stores whiteboards as .edn, which is a
    // serialized canvas, not text anybody wants as a journal entry.
    size_t path_len = strlen(item->file_path);
    if (path_len < 4 || strcmp(item->file_path + path_len - 3, ".md") != 0) {
      continue;
    }
    n++;
  }

  out->items = items;
  out->count = n;
  assert(out->count <= count);
  return true;
}

// The page's markdown, exactly as it sits on disk. Read through
// :file/content rather than off the filesystem: Logseq keeps unsaved edits
// in memory, and this is the copy it would write.
static inline bool LogseqFileContent(Arena *arena, const LogseqOptions *opts,
                                     const char *file_path,
                                     const char **out_markdown, char *err,
                                     size_t err_size) {
  assert(arena_valid(arena));
  assert(file_path != NULL && file_path[0] != '\0');
  assert(out_markdown != NULL);

  *out_markdown = "";

  // The path goes into a datascript literal, so it needs the same escaping
  // a JSON string does - a page called `he said "hi"` is unusual but not
  // impossible, and an unescaped quote would end the clause early.
  JSONBuf query;
  jsonbuf_init_strict(&query, arena);
  jsonbuf_append(&query, "[:find ?content :where [?f :file/path ");
  jsonbuf_append_json_string(&query, file_path);
  jsonbuf_append(&query, "] [?f :file/content ?content]]");

  JsonSpan result;
  if (!LogseqQuery(arena, opts, query.data, &result, err, err_size)) {
    return false;
  }

  const char *cursor = NULL;
  JsonSpan tuple, value;
  if (!json_array_next(result, &cursor, &tuple)) {
    return true; // no file row: an empty page, not an error
  }
  const char *inner = NULL;
  if (!json_array_next(tuple, &inner, &value)) {
    return true;
  }
  *out_markdown = json_span_string(arena, value);
  return true;
}

// The top-level blocks of a page, each tagged with whether it parses as an
// export line. Nested children are not walked: the export only ever writes
// top-level blocks, so those are the only ones it has to match against.
static inline bool LogseqPageBlocks(Arena *arena, const LogseqOptions *opts,
                                    const char *page_name, LogseqBlocks *out,
                                    char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(page_name != NULL);
  assert(out != NULL);

  out->items = NULL;
  out->count = 0;

  JSONBuf args;
  jsonbuf_init_strict(&args, arena);
  jsonbuf_append(&args, "[");
  jsonbuf_append_json_string(&args, page_name);
  jsonbuf_append(&args, "]");

  JsonSpan result;
  if (!LogseqCall(arena, opts, "logseq.Editor.getPageBlocksTree", args.data,
                  &result, err, err_size)) {
    return false;
  }
  if (result.len == 0 || result.data[0] != '[') {
    return true; // page exists but has no blocks yet
  }

  int count = 0;
  const char *cursor = NULL;
  JsonSpan block;
  while (json_array_next(result, &cursor, &block)) {
    count++;
  }
  if (count == 0) {
    return true;
  }

  LogseqBlock *items =
      (LogseqBlock *)arena_alloc(arena, sizeof(LogseqBlock) * (size_t)count);
  int n = 0;
  cursor = NULL;
  while (json_array_next(result, &cursor, &block) && n < count) {
    JsonSpan field;
    items[n].uuid = json_member(block, "uuid", &field)
                        ? json_span_string(arena, field)
                        : "";
    items[n].content = json_member(block, "content", &field)
                           ? json_span_string(arena, field)
                           : "";
    LogseqParseExportLine(arena, items[n].content, &items[n].hhmm,
                          &items[n].kind);
    n++;
  }

  out->items = items;
  out->count = n;
  return true;
}

// ---------------------------------------------------------------------------
// Writing the graph
// ---------------------------------------------------------------------------

static inline bool LogseqAppendBlock(Arena *arena, const LogseqOptions *opts,
                                     const char *page_name, const char *content,
                                     char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(page_name != NULL && content != NULL);

  JSONBuf args;
  jsonbuf_init_strict(&args, arena);
  jsonbuf_append(&args, "[");
  jsonbuf_append_json_string(&args, page_name);
  jsonbuf_append(&args, ",");
  jsonbuf_append_json_string(&args, content);
  jsonbuf_append(&args, "]");

  JsonSpan ignored;
  return LogseqCall(arena, opts, "logseq.Editor.appendBlockInPage", args.data,
                    &ignored, err, err_size);
}

// Inserts as the previous sibling of `block_uuid`. This is what keeps a
// day's blocks in the newest-first order the existing journals use without
// rewriting the page: the caller finds the first block older than the entry
// it is adding and puts the new one in front of it.
static inline bool LogseqInsertBefore(Arena *arena, const LogseqOptions *opts,
                                      const char *block_uuid,
                                      const char *content, char *err,
                                      size_t err_size) {
  assert(arena_valid(arena));
  assert(block_uuid != NULL && block_uuid[0] != '\0');
  assert(content != NULL);

  JSONBuf args;
  jsonbuf_init_strict(&args, arena);
  jsonbuf_append(&args, "[");
  jsonbuf_append_json_string(&args, block_uuid);
  jsonbuf_append(&args, ",");
  jsonbuf_append_json_string(&args, content);
  jsonbuf_append(&args, ",{\"before\":true,\"sibling\":true}]");

  JsonSpan ignored;
  return LogseqCall(arena, opts, "logseq.Editor.insertBlock", args.data,
                    &ignored, err, err_size);
}

// The page name for a journal day, or NULL if the graph has no page for it.
//
// The lookup is by :block/journal-day rather than by a generated title
// because the title depends on :journal/page-title-format, which the user
// can change: an existing day must be found whatever it is called.
static inline bool LogseqFindJournal(Arena *arena, const LogseqOptions *opts,
                                     int day, const char **out_page_name,
                                     char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(day >= 10000101 && day <= 99991231);
  assert(out_page_name != NULL);

  *out_page_name = NULL;

  JSONBuf query;
  jsonbuf_init_strict(&query, arena);
  jsonbuf_appendf(&query,
                  "[:find ?name :where [?p :block/journal-day %d] "
                  "[?p :block/original-name ?name]]",
                  day);

  JsonSpan result;
  if (!LogseqQuery(arena, opts, query.data, &result, err, err_size)) {
    return false;
  }
  const char *cursor = NULL;
  JsonSpan tuple, value;
  if (json_array_next(result, &cursor, &tuple)) {
    const char *inner = NULL;
    if (json_array_next(tuple, &inner, &value)) {
      *out_page_name = json_span_string(arena, value);
    }
  }
  return true;
}

// The same lookup, but a day with no page at all gets one created under the
// default title format.
static inline bool LogseqEnsureJournal(Arena *arena, const LogseqOptions *opts,
                                       int day, const char **out_page_name,
                                       char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(day >= 10000101 && day <= 99991231);
  assert(out_page_name != NULL);

  if (!LogseqFindJournal(arena, opts, day, out_page_name, err, err_size)) {
    return false;
  }
  if (*out_page_name != NULL) {
    return true;
  }

  const char *title = LogseqJournalTitle(arena, day);
  JSONBuf args;
  jsonbuf_init_strict(&args, arena);
  jsonbuf_append(&args, "[");
  jsonbuf_append_json_string(&args, title);
  // createFirstBlock false: an empty first block would be exported back as a
  // stray bullet, and redirect false keeps the running app where it is.
  jsonbuf_append(&args, ",{},{\"journal\":true,\"createFirstBlock\":false,"
                        "\"redirect\":false}]");

  JsonSpan created;
  if (!LogseqCall(arena, opts, "logseq.Editor.createPage", args.data, &created,
                  err, err_size)) {
    return false;
  }
  *out_page_name = title;
  return true;
}

// ---------------------------------------------------------------------------
// Day arithmetic
// ---------------------------------------------------------------------------

static inline int LogseqDayAdd(int day, int delta) {
  assert(day >= 10000101 && day <= 99991231);

  // Through midnight UTC, so no zone and no DST moves the day.
  time_t t = (time_t)logseq_day_epoch(day, delta);
  struct tm tm;
  gmtime_r(&t, &tm);
  return (tm.tm_year + 1900) * 10000 + (tm.tm_mon + 1) * 100 + tm.tm_mday;
}

static inline int LogseqToday(void) {
  time_t now = time(NULL);
  struct tm local;
  if (!localtime_r(&now, &local)) {
    return 0;
  }
  return (local.tm_year + 1900) * 10000 + (local.tm_mon + 1) * 100 +
         local.tm_mday;
}

// ---------------------------------------------------------------------------
// Import: Logseq -> lcars
// ---------------------------------------------------------------------------

// The titles already present under one kind. The import writes the Logseq
// identity into the entry title - the ISO day for a journal, the page name
// for a page - so "have I imported this already?" is answered without a
// second table or a schema change, and re-running the import is a no-op.
typedef struct LogseqTitleSet {
  const char **items;
  int count;
} LogseqTitleSet;

typedef struct LogseqImportOptions {
  bool journals;
  bool pages;
  int since_day; // 0 = no lower bound
  int until_day; // 0 = no upper bound
  int limit;     // 0 = no limit
  bool dry_run;
  bool verbose;
  const char *journal_kind;
  const char *page_kind;
} LogseqImportOptions;

typedef struct LogseqExportOptions {
  const char *kind;         // NULL = every kind except the imported ones:
  const char *journal_kind; // the import's kinds, left out when kind is
  const char *page_kind;    // NULL (the roles': CmdLogseqExport)
  bool dry_run;
  bool verbose;
} LogseqExportOptions;

static inline bool LogseqLoadTitles(Arena *arena, const CliOptions *opts,
                                    const char *kind, LogseqTitleSet *out,
                                    char *err, size_t err_size);
static inline bool LogseqTitleSetHas(const LogseqTitleSet *set,
                                     const char *title);
static inline bool LogseqImport(Arena *arena, Arena *scratch,
                                const CliOptions *cli, const LogseqOptions *ls,
                                const LogseqImportOptions *imp,
                                LogseqSyncStats *stats, char *err,
                                size_t err_size);
static inline bool LogseqExportDay(Arena *arena, const CliOptions *cli,
                                   const LogseqOptions *ls, int day,
                                   const LogseqExportOptions *exp,
                                   LogseqSyncStats *stats, char *err,
                                   size_t err_size);

// Every live *and* deleted title under `kind`, paged out of the server. Deleted
// ones count: an entry the user imported and then threw away must not come back
// on the next run.
static inline bool LogseqLoadTitles(Arena *arena, const CliOptions *opts,
                                    const char *kind, LogseqTitleSet *out,
                                    char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && kind != NULL && out != NULL);

  out->items = NULL;
  out->count = 0;

  int capacity = 256;
  const char **items =
      (const char **)arena_alloc(arena, sizeof(char *) * (size_t)capacity);
  int count = 0;

  for (int offset = 0;; offset += CLI_MAX_LIMIT) {
    CliFilters filters = {0};
    filters.kind = kind;
    filters.done = -1;
    filters.deleted = "all";
    filters.order = "id";
    filters.dir = "asc";
    filters.limit = CLI_MAX_LIMIT;
    filters.offset = offset;
    filters.include_content = false;

    EntryRows rows = {0};
    if (!CliListEntries(arena, opts, &filters, &rows, err, err_size)) {
      return false;
    }
    for (int i = 0; i < rows.count; i++) {
      const char *title = rows.items[i].title;
      if (!title || title[0] == '\0') {
        continue;
      }
      if (count == capacity) {
        int grown = capacity * 2;
        items = (const char **)arena_realloc(arena, (void *)items,
                                             sizeof(char *) * (size_t)capacity,
                                             sizeof(char *) * (size_t)grown);
        capacity = grown;
      }
      items[count++] = title;
    }
    if (rows.count < CLI_MAX_LIMIT) {
      break;
    }
  }

  out->items = items;
  out->count = count;
  assert(out->count <= capacity);
  return true;
}

static inline bool LogseqTitleSetHas(const LogseqTitleSet *set,
                                     const char *title) {
  assert(set != NULL);
  assert(title != NULL);

  for (int i = 0; i < set->count; i++) {
    if (strcmp(set->items[i], title) == 0) {
      return true;
    }
  }
  return false;
}

// Whitespace-and-bullets only. Logseq leaves a bare "-" behind on every
// journal page the user opened and did not write in, and this graph has
// dozens of them; importing those would be importing nothing, dozens of
// times.
//
// The YAML front matter Logseq writes on some pages is skipped first,
// because its one property is `title:` - a restatement of the page name,
// which the entry already carries. A page whose whole body is that header
// is as empty as one with nothing in it.
static inline bool logseq_markdown_is_empty(const char *markdown) {
  assert(markdown != NULL);

  const char *p = markdown;
  if (strncmp(p, "---\n", 4) == 0) {
    const char *end = strstr(p + 4, "\n---");
    if (end) {
      p = end + 4;
      while (*p == '\n' || *p == '\r') {
        p++;
      }
    }
  }
  for (; *p != '\0'; p++) {
    if (*p != '-' && *p != ' ' && *p != '\t' && *p != '\n' && *p != '\r') {
      return false;
    }
  }
  return true;
}

static int logseq_compare_pages(const void *a, const void *b) {
  const LogseqPage *pa = (const LogseqPage *)a;
  const LogseqPage *pb = (const LogseqPage *)b;

  // Journals first, oldest day first; then pages by name. Chronological
  // order is what makes a partial import (--limit, or one interrupted
  // halfway) resumable: everything before the point it stopped is done.
  if (pa->is_journal != pb->is_journal) {
    return pa->is_journal ? -1 : 1;
  }
  if (pa->is_journal) {
    if (pa->journal_day != pb->journal_day) {
      return pa->journal_day < pb->journal_day ? -1 : 1;
    }
  }
  return strcmp(pa->original_name, pb->original_name);
}

// Walks the graph and creates one entry per Logseq page.
//
// `arena` holds what outlives a single page (the page list, the dedup title
// sets); `scratch` is reset before every page, because a full import reads
// ~6MB of markdown across 1500 pages and holding all of it at once would
// need an arena sized for the graph rather than for its largest page.
static inline bool LogseqImport(Arena *arena, Arena *scratch,
                                const CliOptions *cli, const LogseqOptions *ls,
                                const LogseqImportOptions *imp,
                                LogseqSyncStats *stats, char *err,
                                size_t err_size) {
  assert(arena_valid(arena));
  assert(arena_valid(scratch));
  assert(cli != NULL && ls != NULL && imp != NULL && stats != NULL);
  assert(imp->journal_kind != NULL && imp->page_kind != NULL);

  memset(stats, 0, sizeof(*stats));

  LogseqPages pages;
  if (!LogseqListPages(arena, ls, &pages, err, err_size)) {
    return false;
  }
  if (pages.count > 1) {
    qsort(pages.items, (size_t)pages.count, sizeof(LogseqPage),
          logseq_compare_pages);
  }

  LogseqTitleSet journal_titles = {0};
  LogseqTitleSet page_titles = {0};
  if (imp->journals && !LogseqLoadTitles(arena, cli, imp->journal_kind,
                                         &journal_titles, err, err_size)) {
    return false;
  }
  if (imp->pages && !LogseqLoadTitles(arena, cli, imp->page_kind, &page_titles,
                                      err, err_size)) {
    return false;
  }

  for (int i = 0; i < pages.count; i++) {
    const LogseqPage *page = &pages.items[i];
    if (page->is_journal ? !imp->journals : !imp->pages) {
      continue;
    }
    if (page->is_journal) {
      if (page->journal_day == 0) {
        continue; // a file under journals/ whose name Logseq could not parse
      }
      if (imp->since_day != 0 && page->journal_day < imp->since_day) {
        continue;
      }
      if (imp->until_day != 0 && page->journal_day > imp->until_day) {
        continue;
      }
    }
    if (imp->limit != 0 && stats->written >= imp->limit) {
      break;
    }

    arena_reset(scratch);
    stats->considered++;

    const char *kind = page->is_journal ? imp->journal_kind : imp->page_kind;
    const LogseqTitleSet *seen =
        page->is_journal ? &journal_titles : &page_titles;
    const char *title = page->is_journal
                            ? LogseqISOFromDay(scratch, page->journal_day)
                            : page->original_name;

    if (LogseqTitleSetHas(seen, title)) {
      stats->skipped_existing++;
      if (imp->verbose) {
        fprintf(stderr, "  skip (exists)  %-14s %s\n", kind, title);
      }
      continue;
    }

    const char *markdown = NULL;
    if (!LogseqFileContent(scratch, ls, page->file_path, &markdown, err,
                           err_size)) {
      stats->failed++;
      fprintf(stderr, "  FAILED %s: %s\n", page->file_path, err);
      continue;
    }
    if (logseq_markdown_is_empty(markdown)) {
      stats->skipped_empty++;
      if (imp->verbose) {
        fprintf(stderr, "  skip (empty)   %-14s %s\n", kind, title);
      }
      continue;
    }

    CliFields fields = {0};
    fields.has_kind = true;
    fields.kind = kind;
    fields.has_title = true;
    fields.title = title;
    fields.has_content = true;
    fields.content = markdown;
    // Only journals can be backdated: journal-day is the one timestamp
    // Logseq did not lose (see the header comment). A page keeps the
    // import's own time, which is at least honest about when this database
    // learned of it.
    if (page->is_journal) {
      JSONBuf ts;
      jsonbuf_init_strict(&ts, scratch);
      jsonbuf_appendf(&ts, "%s 00:00:00", title);
      fields.has_created_at = true;
      fields.created_at = ts.data;
      fields.has_modified_at = true;
      fields.modified_at = ts.data;
    }

    if (imp->dry_run) {
      stats->written++;
      printf("would import %-14s %-28s %6d bytes\n", kind, title,
             (int)strlen(markdown));
      continue;
    }

    int new_id = 0;
    if (!CliCreateEntry(scratch, cli, &fields, &new_id, err, err_size)) {
      stats->failed++;
      fprintf(stderr, "  FAILED %s: %s\n", title, err);
      continue;
    }
    stats->written++;
    if (imp->verbose) {
      fprintf(stderr, "  imported #%-6d %-14s %s\n", new_id, kind, title);
    }
  }

  arena_reset(scratch);
  return true;
}

// ---------------------------------------------------------------------------
// Export: lcars -> Logseq
// ---------------------------------------------------------------------------

// Writes one local day's entries into that day's Logseq journal as
// `HH:MM [kind] text` blocks, skipping every entry whose (time, kind) slot
// is already on the page.
//
// That skip rule is the whole design: it is the format the journals were
// already being filled in by hand, so the first automated export over a day
// that was copied manually writes nothing, and a second export over a day
// this function wrote writes nothing either. Nothing is ever deleted or
// rewritten - blocks the user typed themselves are not even looked at
// beyond failing to parse as an export line.
//
// Entries the *import* created are excluded unless --kind asks for them by
// name. They are Logseq's own pages, and an import followed by an export
// would otherwise copy 1400 journals back into the graph as blocks of
// today's journal - a loop the two directions have to be told about, since
// nothing in an entry says where it came from except its kind.
static inline bool LogseqExportDay(Arena *arena, const CliOptions *cli,
                                   const LogseqOptions *ls, int day,
                                   const LogseqExportOptions *exp,
                                   LogseqSyncStats *stats, char *err,
                                   size_t err_size) {
  assert(arena_valid(arena));
  assert(cli != NULL && ls != NULL && exp != NULL && stats != NULL);
  assert(day >= 10000101 && day <= 99991231);

  char from[24], to[24];
  if (!LogseqDayUTCRange(day, from, sizeof(from), to, sizeof(to))) {
    return CliFail(err, err_size, "cannot map %d to a UTC range", day);
  }

  CliFilters filters = {0};
  filters.kind = exp->kind;
  filters.since = from;
  filters.until = to;
  filters.done = -1;
  filters.order = "created";
  filters.dir = "asc";
  filters.limit = CLI_MAX_LIMIT;
  filters.include_content = true;

  EntryRows rows = {0};
  if (!CliListEntries(arena, cli, &filters, &rows, err, err_size)) {
    return false;
  }
  if (rows.count == 0) {
    return true;
  }

  // Counted after the round-trip filter below, so `considered` means "rows
  // this export had an opinion about".
  bool exclude_imported = (exp->kind == NULL);

  const char *page_name = NULL;
  if (exp->dry_run) {
    if (!LogseqFindJournal(arena, ls, day, &page_name, err, err_size)) {
      return false;
    }
  } else if (!LogseqEnsureJournal(arena, ls, day, &page_name, err, err_size)) {
    return false;
  }

  LogseqBlocks blocks = {0};
  if (page_name &&
      !LogseqPageBlocks(arena, ls, page_name, &blocks, err, err_size)) {
    return false;
  }

  for (int i = 0; i < rows.count; i++) {
    const EntryRow *row = &rows.items[i];
    if (exclude_imported && row->kind &&
        (strcmp(row->kind, exp->journal_kind) == 0 ||
         strcmp(row->kind, exp->page_kind) == 0)) {
      continue;
    }
    stats->considered++;

    int row_day = 0, hhmm = 0;
    if (!row->created_at_utc ||
        !LogseqLocalSlot(row->created_at_utc, &row_day, &hhmm)) {
      stats->failed++;
      fprintf(stderr, "  FAILED #%d: unreadable created_at_utc '%s'\n", row->id,
              row->created_at_utc ? row->created_at_utc : "(null)");
      continue;
    }
    // The UTC range is derived from this same local day, so a row landing
    // on a different one would mean the two conversions disagree.
    assert(row_day == day);

    const char *kind = (row->kind && row->kind[0]) ? row->kind : "entry";
    bool present = false;
    for (int b = 0; b < blocks.count; b++) {
      if (blocks.items[b].hhmm == hhmm && blocks.items[b].kind &&
          strcmp(blocks.items[b].kind, kind) == 0) {
        present = true;
        break;
      }
    }
    if (present) {
      stats->skipped_existing++;
      continue;
    }

    const char *content = LogseqFormatExportBlock(arena, row, hhmm);
    if (exp->dry_run) {
      stats->written++;
      printf("%s | would add: %s\n", LogseqISOFromDay(arena, day), content);
      continue;
    }

    // The journals run newest-first, so the new block goes in front of the
    // first export block older than it. Free-form blocks (hhmm == -1) are
    // never a landing site: putting a timed line in the middle of someone's
    // hand-written outline would be worse than putting it at the end.
    const char *before_uuid = NULL;
    for (int b = 0; b < blocks.count; b++) {
      if (blocks.items[b].hhmm >= 0 && blocks.items[b].hhmm < hhmm &&
          blocks.items[b].uuid[0] != '\0') {
        before_uuid = blocks.items[b].uuid;
        break;
      }
    }

    bool ok =
        before_uuid
            ? LogseqInsertBefore(arena, ls, before_uuid, content, err, err_size)
            : LogseqAppendBlock(arena, ls, page_name, content, err, err_size);
    if (!ok) {
      stats->failed++;
      fprintf(stderr, "  FAILED #%d: %s\n", row->id, err);
      continue;
    }
    stats->written++;
    if (exp->verbose) {
      fprintf(stderr, "  added %s %s\n", page_name, content);
    }

    // Re-read rather than patch the local copy: the insert changed the
    // page's block order, and the next entry's landing site is decided
    // against that new order. A day is a couple of dozen entries against a
    // loopback socket, so the round trip is cheaper than the class of bug
    // that a stale list produces.
    if (!LogseqPageBlocks(arena, ls, page_name, &blocks, err, err_size)) {
      return false;
    }
  }
  return true;
}

#endif // LCARS_IMPLEMENTATION
#endif // LCARS_LOGSEQ_H
