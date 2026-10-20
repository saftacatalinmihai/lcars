#ifndef LCARS_CALDAV_H
#define LCARS_CALDAV_H

// CalDAV (RFC 4791) task lists served straight out of the `entries` table,
// so Apple Reminders - or any other CalDAV client - reads and writes the same
// tasks the LCARS UI shows.
//
// URL space:
//   /.well-known/caldav               bootstrap; answers PROPFIND like /caldav/
//   /caldav/principal/                the single user principal
//   /caldav/calendars/                the calendar home: one collection per
//   list /caldav/calendars/<list>/         one VTODO collection (a Reminders
//   list) /caldav/calendars/<list>/X.ics    one task
//
// A list is an entry kind. The task kind (the `task` role's, default "task";
// $LCARS_TASK_KIND overrides it)
// is the list at /caldav/calendars/tasks/, and every kind under it -
// task_personal, task_work, ... - is a list of its own, at a URL
// named after the kind. A list made in Reminders (MKCALENDAR) becomes a new
// kind, "task_" plus its name; its name, colour and order (PROPPATCH) live
// in the side table `caldav_lists`, and deleting it in Reminders hides it
// from CalDAV without touching a single entry.
//
// Inside a list: title <-> SUMMARY, content <-> DESCRIPTION, done_bool <->
// STATUS, `deleted` takes the row out, and the due date is the entry's
// schedule: DTSTART/DUE <-> start_date/end_date, which is what puts a
// reminder on the web UI's day view and a block drawn there into Reminders.
// Every other iCalendar property a client sends (PRIORITY, RRULE, VALARM,
// URL, X-APPLE-SORT-ORDER, whole VTIMEZONE components) is kept verbatim in
// the side table `caldav_tasks`, so a round trip through this server does
// not lose what the entries schema has no column for. The side tables are
// created on first use and nothing outside this file reads them - the
// journal schema is deliberately left alone, apart from one trigger that
// remembers which list a task left when its kind changes (caldav_moves),
// because that is the one change a sync-collection report cannot otherwise
// see.
//
// This is a module of lcars_http.h, not a standalone header: it uses that
// file's response, buffer and header-parsing helpers and is included from
// inside its LCARS_HTTP_IMPLEMENTATION block.

// Whether this request belongs to the CalDAV surface: any WebDAV method
// (which the JSON API has no use for), or any path under /caldav.
static bool IsCalDAVRequest(const char *method, const char *path);

// Handles one CalDAV request and returns the HTTP status it sent. `headers`
// is the raw request-header block (for Depth/If-Match/If-None-Match) and
// `body` the already-read entity body ("" when there is none).
static int HandleCalDAVRequest(int client_fd, Arena *arena, const char *method,
                               const char *path, const char *headers,
                               const char *body);

// "/entries/<id>/caldav": the JSON view of one task's CalDAV side - its
// list, resource name, UID, the full VTODO a client would GET, and the
// property lines kept verbatim (DUE, VALARM, RRULE, ...) - which is how the
// web UI shows and edits what Reminders set without speaking WebDAV itself.
static bool MatchEntryCalDAVPath(const char *path, int *out_id);

// GET answers that view; PUT {"extra_ical": "...", "etag": "..."} replaces
// the kept lines (the columns stay the columns' to change, except the
// schedule, which DTSTART/DUE are) and answers the view again. Returns the
// HTTP status it sent.
static int HandleEntryCalDAV(int client_fd, Arena *arena, const char *method,
                             int id, const char *headers, const char *body);

#ifdef LCARS_CALDAV_IMPLEMENTATION

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

#define CALDAV_WELL_KNOWN "/.well-known/caldav"
#define CALDAV_PRINCIPAL_PATH "/caldav/principal/"
#define CALDAV_HOME_PATH "/caldav/calendars/"
// The task kind's own list keeps the URL it had when it was the only one,
// so an account set up before lists existed sees no move.
#define CALDAV_BASE_SEGMENT "tasks"
#define CALDAV_DISPLAY_NAME "LCARS Tasks"
#define CALDAV_PRODID "-//lcars//CalDAV tasks//EN"
// Resource names are client-chosen (Reminders sends a UUID plus ".ics").
// Anything longer than this is refused rather than truncated into a name
// that would collide with a different task's.
#define CALDAV_MAX_NAME 160
#define CALDAV_MAX_UID 256
#define CALDAV_MAX_KIND 128
// Lists are loaded whole onto the stack; past this many the rest are not
// published (and the log says so). A Reminders account with 32 lists is
// not this journal.
#define CALDAV_MAX_LISTS 32
// Advertised as CALDAV:max-resource-size; matches the HTTP body cap.
#define CALDAV_MAX_RESOURCE_SIZE HTTP_MAX_BODY_BYTES
// A sync-token must be a URI (RFC 6578 3.2); what follows the prefix is the
// newest stamp the answer saw and the list's ctag.
#define CALDAV_SYNC_PREFIX "http://lcars.local/ns/sync/"

#define CALDAV_DAV_HEADER "DAV: 1, 2, 3, calendar-access\r\n"
#define CALDAV_ALLOW_HEADER                                                    \
  "Allow: OPTIONS, GET, HEAD, PUT, DELETE, MOVE, PROPFIND, PROPPATCH, "        \
  "REPORT, MKCALENDAR\r\n"

// The columns every task query selects, in the order the readers below
// expect them. The LEFT JOIN keeps entries that were created in the UI (and
// so have no CalDAV side row) visible to the client.
#define CALDAV_TASK_COLUMNS                                                    \
  "e.id, e.title, e.content, e.done_bool, e.created_at_utc, "                  \
  "e.last_modified_at_utc, c.resource_name, c.uid, c.extra_ical, "             \
  "c.extra_vcal, e.kind, e.start_date, e.end_date, c.sync_start, "             \
  "c.sync_end, e.deleted"
#define CALDAV_TASK_FROM                                                       \
  " FROM entries e LEFT JOIN caldav_tasks c ON c.entry_id = e.id "

typedef enum CalDAVColumn {
  CALDAV_COL_ID = 0,
  CALDAV_COL_TITLE,
  CALDAV_COL_CONTENT,
  CALDAV_COL_DONE,
  CALDAV_COL_CREATED,
  CALDAV_COL_MODIFIED,
  CALDAV_COL_NAME,
  CALDAV_COL_UID,
  CALDAV_COL_EXTRA,
  CALDAV_COL_EXTRA_VCAL,
  CALDAV_COL_KIND,
  CALDAV_COL_START,
  CALDAV_COL_END,
  CALDAV_COL_SYNC_START,
  CALDAV_COL_SYNC_END,
  CALDAV_COL_DELETED,
  CALDAV_COL_COUNT
} CalDAVColumn;

typedef enum CalDAVPathKind {
  CALDAV_PATH_NONE = 0,
  CALDAV_PATH_ROOT,       // "/", "/caldav/", "/.well-known/caldav"
  CALDAV_PATH_PRINCIPAL,  // "/caldav/principal/"
  CALDAV_PATH_HOME,       // "/caldav/calendars/"
  CALDAV_PATH_COLLECTION, // "/caldav/calendars/<list>/"
  CALDAV_PATH_RESOURCE    // "/caldav/calendars/<list>/<name>"
} CalDAVPathKind;

// One published list: an entry kind, and how CalDAV shows it.
typedef struct CalDAVList {
  char kind[CALDAV_MAX_KIND];
  char segment[CALDAV_MAX_NAME]; // the URL path segment, unescaped
  char name[128];                // DAV:displayname
  char color[16];                // "#RRGGBBAA", what Apple's clients send
  int order;
  bool hidden; // deleted in a client: no longer published
  bool stored; // has a caldav_lists row (else every field is a default)
} CalDAVList;

// Copies `src` into a fixed buffer, truncating rather than overrunning and
// always terminating. Written with memcpy rather than strncpy because the
// truncating form of the latter is exactly what -Wstringop-truncation
// objects to, and the intent here is truncation.
static void caldav_copy_str(char *dst, size_t dst_size, const char *src) {
  assert(dst != NULL);
  assert(dst_size > 0);

  size_t len = src ? strlen(src) : 0;
  if (len > dst_size - 1) {
    len = dst_size - 1;
  }
  if (len > 0) {
    memcpy(dst, src, len);
  }
  dst[len] = '\0';
}

// The entry kind CalDAV tasks live under: the `task` role's
// (lcars_kinds.h), so a journal that calls them something else ("todo",
// say) syncs once its owner says so. Its sub-kinds ("<kind>_<list>") are the
// other lists. $LCARS_TASK_KIND, when set, still wins - deprecated, kept so
// a box that set it before the roles keeps its lists (docs/design/kinds.md,
// choice D).
//
// Thread-local, and loaded by caldav_load_task_kind at the top of each
// request that opens the journal (both CalDAV handlers), never cached past
// it: a role set between two syncs applies to the second. Per thread, so
// two connections cannot read each other's half-written value; a call
// before the load is a programmer error.
static _Thread_local char caldav_task_kind_buf[CALDAV_MAX_KIND];

static void caldav_load_task_kind(sqlite3 *db) {
  assert(db != NULL);
  const char *env = getenv("LCARS_TASK_KIND");
  char role[KIND_MAX];
  if (env == NULL || env[0] == '\0') {
    KindFor(db, "task", role, sizeof(role));
    env = role;
  }
  // room for the "_" the sub-kinds add
  caldav_copy_str(caldav_task_kind_buf, sizeof(caldav_task_kind_buf) - 2, env);
}

static const char *caldav_task_kind(void) {
  assert(caldav_task_kind_buf[0] != '\0' && "caldav_load_task_kind first");
  return caldav_task_kind_buf;
}

// Whether a kind is one CalDAV publishes as a list: the task kind or one of
// its "<kind>_..." sub-kinds. (Hidden lists still answer true; whether one
// is published right now is caldav_list_by_kind's question.)
static bool caldav_kind_is_tasks(const char *kind) {
  if (!kind) {
    return false;
  }
  const char *base = caldav_task_kind();
  size_t n = strlen(base);
  if (strncmp(kind, base, n) != 0) {
    return false;
  }
  return kind[n] == '\0' || (kind[n] == '_' && kind[n + 1] != '\0');
}

// The SQL form of the test above, with the task kind bound as ?1.
#define CALDAV_SQL_TASKISH(col)                                                \
  "(" col " = ?1 OR (substr(" col ", 1, length(?1) + 1) = ?1 || '_' AND "      \
  "length(" col ") > length(?1) + 1))"

// ---------------------------------------------------------------------------
// Small utilities
// ---------------------------------------------------------------------------

// FNV-1a. Used for ETags and the collection ctag, where all that matters is
// that the value changes whenever the bytes behind it do.
static uint64_t caldav_hash_bytes(uint64_t hash, const void *data, size_t len) {
  assert(data != NULL || len == 0);
  const unsigned char *p = (const unsigned char *)data;
  for (size_t i = 0; i < len; i++) {
    hash ^= (uint64_t)p[i];
    hash *= 1099511628211ULL;
  }
  return hash;
}

static uint64_t caldav_hash_str(uint64_t hash, const char *s) {
  // The terminator is hashed too, so ("ab", "c") and ("a", "bc") differ.
  return s ? caldav_hash_bytes(hash, s, strlen(s) + 1)
           : caldav_hash_bytes(hash, "", 1);
}

#define CALDAV_HASH_SEED 1469598103934665603ULL

// "YYYY-MM-DD HH:MM:SS" (how the entries table stores UTC) -> the iCalendar
// basic form "YYYYMMDDTHHMMSSZ". Anything unparseable yields the epoch,
// which is wrong but harmless - never a malformed property value.
static void caldav_ts_to_ical(const char *sql_ts, char *out, size_t out_size) {
  assert(out != NULL);
  assert(out_size >= 17);

  int y = 1970, mo = 1, d = 1, h = 0, mi = 0, s = 0;
  if (sql_ts && sscanf(sql_ts, "%4d-%2d-%2d %2d:%2d:%2d", &y, &mo, &d, &h, &mi,
                       &s) != 6) {
    y = 1970;
    mo = 1;
    d = 1;
    h = 0;
    mi = 0;
    s = 0;
  }
  int n =
      snprintf(out, out_size, "%04d%02d%02dT%02d%02d%02dZ", y, mo, d, h, mi, s);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// Sakamoto's method: 0 = Sunday. Done by hand rather than through timegm(),
// which is not in C11 or POSIX and whose availability here depends on which
// feature-test macros the unity build happened to reach first.
static int caldav_day_of_week(int y, int m, int d) {
  static const int t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
  assert(m >= 1 && m <= 12);
  if (m < 3) {
    y -= 1;
  }
  return (y + y / 4 - y / 100 + y / 400 + t[m - 1] + d) % 7;
}

// "YYYY-MM-DD HH:MM:SS" -> the RFC 1123 date DAV:getlastmodified wants.
static void caldav_ts_to_http_date(const char *sql_ts, char *out,
                                   size_t out_size) {
  assert(out != NULL);
  assert(out_size >= 30);

  static const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
  static const char *months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  int y = 1970, mo = 1, d = 1, h = 0, mi = 0, s = 0;
  if (sql_ts && sscanf(sql_ts, "%4d-%2d-%2d %2d:%2d:%2d", &y, &mo, &d, &h, &mi,
                       &s) != 6) {
    y = 1970;
    mo = 1;
    d = 1;
    h = 0;
    mi = 0;
    s = 0;
  }
  // Timestamps come out of SQLite, but a hand-edited row could still hold
  // anything; clamp rather than index the tables out of bounds.
  if (mo < 1 || mo > 12) {
    mo = 1;
  }
  if (d < 1 || d > 31) {
    d = 1;
  }
  int dow = caldav_day_of_week(y, mo, d);
  if (dow < 0 || dow > 6) {
    dow = 0;
  }
  int n = snprintf(out, out_size, "%s, %02d %s %04d %02d:%02d:%02d GMT",
                   days[dow], d, months[mo - 1], y, h, mi, s);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// ---------------------------------------------------------------------------
// Instants and time zones
//
// A due date arrives as a zone's wall clock ("DUE;TZID=Europe/Madrid:
// 20261007T150000" is what Reminders sends) and the entries table holds UTC,
// so the schedule mapping needs a real zone conversion. libc's is mktime()
// under $TZ, which is process-global state - not something a thread per
// connection can set. So the zone's TZif file is read here instead, which
// is what libc would have read anyway: thread-safe, and exact for every
// year its transitions cover, with the POSIX rule in its footer for the
// years after (a "slim" tzdata build has nothing but that rule).
// ---------------------------------------------------------------------------

// A UTC calendar time as seconds since the epoch, and back: timegm and
// gmtime_r (glibc; lcars.c defines _GNU_SOURCE). Neither reads $TZ, so they
// are safe on any connection thread - unlike mktime/localtime, the reason
// for the TZif reader below. Out-of-range fields roll over (day 32 is the
// 1st of the next month), which the day arithmetic here relies on.
static int64_t caldav_epoch(int y, int mo, int d, int h, int mi, int s) {
  struct tm tm = {.tm_year = y - 1900,
                  .tm_mon = mo - 1,
                  .tm_mday = d,
                  .tm_hour = h,
                  .tm_min = mi,
                  .tm_sec = s};
  return (int64_t)timegm(&tm);
}

static void caldav_epoch_split(int64_t t, int *y, int *mo, int *d, int *h,
                               int *mi, int *s) {
  assert(y != NULL && mo != NULL && d != NULL);
  time_t tt = (time_t)t;
  struct tm tm;
  gmtime_r(&tt, &tm);
  *y = tm.tm_year + 1900;
  *mo = tm.tm_mon + 1;
  *d = tm.tm_mday;
  *h = tm.tm_hour;
  *mi = tm.tm_min;
  *s = tm.tm_sec;
}

// The date `delta` days from y-m-d, in place.
static void caldav_add_days(int *y, int *m, int *d, int delta) {
  int h, mi, s;
  caldav_epoch_split(caldav_epoch(*y, *m, *d + delta, 0, 0, 0), y, m, d, &h,
                     &mi, &s);
}

// "YYYY-MM-DD HH:MM:SS" -> seconds since the epoch. False for "" (an
// unscheduled entry) and for anything that is not that shape.
static bool caldav_sql_to_epoch(const char *ts, int64_t *out) {
  assert(out != NULL);
  int y, mo, d, h, mi, s;
  if (!ts ||
      sscanf(ts, "%4d-%2d-%2d %2d:%2d:%2d", &y, &mo, &d, &h, &mi, &s) != 6) {
    return false;
  }
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 60) {
    return false;
  }
  *out = caldav_epoch(y, mo, d, h, mi, s);
  return true;
}

static void caldav_epoch_to_sql(int64_t t, char *out, size_t out_size) {
  assert(out != NULL && out_size >= 20);
  int y, mo, d, h, mi, s;
  caldav_epoch_split(t, &y, &mo, &d, &h, &mi, &s);
  int n = snprintf(out, out_size, "%04d-%02d-%02d %02d:%02d:%02d", y, mo, d, h,
                   mi, s);
  assert(n == 19);
  (void)n;
}

static void caldav_epoch_to_ical(int64_t t, char *out, size_t out_size) {
  assert(out != NULL && out_size >= 17);
  int y, mo, d, h, mi, s;
  caldav_epoch_split(t, &y, &mo, &d, &h, &mi, &s);
  int n =
      snprintf(out, out_size, "%04d%02d%02dT%02d%02d%02dZ", y, mo, d, h, mi, s);
  assert(n == 16);
  (void)n;
}

#define CALDAV_TZ_MAX_TRANS 1200
#define CALDAV_TZ_MAX_TYPES 32

// One POSIX "Mm.w.d/time" rule date.
typedef struct CalDAVTzRuleDate {
  int month, week, wday; // week 5 = the last
  int32_t secs;          // local time of day the change happens at
} CalDAVTzRuleDate;

typedef struct CalDAVZone {
  int ntrans;
  int64_t trans[CALDAV_TZ_MAX_TRANS];
  uint8_t idx[CALDAV_TZ_MAX_TRANS];
  int ntypes;
  int32_t type_off[CALDAV_TZ_MAX_TYPES];
  bool type_dst[CALDAV_TZ_MAX_TYPES];
  // The footer rule, for instants past the last transition.
  bool has_rule;
  bool rule_has_dst;
  int32_t std_off, dst_off; // seconds east of UTC
  CalDAVTzRuleDate start, end;
} CalDAVZone;

static int32_t caldav_be32(const unsigned char *p) {
  return (int32_t)((uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
                   (uint32_t)p[2] << 8 | (uint32_t)p[3]);
}

static int64_t caldav_be64(const unsigned char *p) {
  return (int64_t)((uint64_t)(uint32_t)caldav_be32(p) << 32 |
                   (uint64_t)(uint32_t)caldav_be32(p + 4));
}

// Zone names come from the request (a TZID parameter), so this is what
// keeps one from naming a file outside the zoneinfo tree.
static bool caldav_zone_name_ok(const char *name) {
  if (!name || name[0] == '\0' || name[0] == '/' || strlen(name) >= 64 ||
      strstr(name, "..") != NULL) {
    return false;
  }
  for (const char *p = name; *p; p++) {
    char c = *p;
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '+' ||
              c == '/';
    if (!ok) {
      return false;
    }
  }
  return true;
}

// POSIX TZ pieces: a name (alphabetic, or <quoted>), and an offset
// [+-]hh[:mm[:ss]]. Each returns where it stopped, NULL on a malformed one.
static const char *caldav_tz_skip_name(const char *p) {
  if (*p == '<') {
    const char *close = strchr(p, '>');
    return close ? close + 1 : NULL;
  }
  const char *start = p;
  while ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')) {
    p++;
  }
  return p - start >= 3 ? p : NULL;
}

static const char *caldav_tz_parse_secs(const char *p, int32_t *out) {
  int sign = 1;
  if (*p == '+' || *p == '-') {
    sign = *p == '-' ? -1 : 1;
    p++;
  }
  if (*p < '0' || *p > '9') {
    return NULL;
  }
  int32_t parts[3] = {0, 0, 0};
  for (int i = 0; i < 3; i++) {
    int32_t v = 0;
    int digits = 0;
    while (*p >= '0' && *p <= '9' && digits < 3) {
      v = v * 10 + (*p - '0');
      p++;
      digits++;
    }
    parts[i] = v;
    if (*p != ':' || i == 2) {
      break;
    }
    p++;
  }
  *out = sign * (parts[0] * 3600 + parts[1] * 60 + parts[2]);
  return p;
}

static const char *caldav_tz_parse_date(const char *p, CalDAVTzRuleDate *out) {
  // Only the "Mm.w.d" form: every zone tzdata ships uses it. The Julian
  // forms make the whole rule unusable, and the transitions table is then
  // all there is.
  if (*p != 'M') {
    return NULL;
  }
  int m = 0, w = 0, d = 0, used = 0;
  if (sscanf(p, "M%d.%d.%d%n", &m, &w, &d, &used) != 3 || m < 1 || m > 12 ||
      w < 1 || w > 5 || d < 0 || d > 6) {
    return NULL;
  }
  p += used;
  out->month = m;
  out->week = w;
  out->wday = d;
  out->secs = 2 * 3600;
  if (*p == '/') {
    p = caldav_tz_parse_secs(p + 1, &out->secs);
  }
  return p;
}

static void caldav_tz_parse_rule(const char *s, CalDAVZone *z) {
  assert(s != NULL && z != NULL);
  z->has_rule = false;
  const char *p = caldav_tz_skip_name(s);
  int32_t std_west = 0;
  if (!p || !(p = caldav_tz_parse_secs(p, &std_west))) {
    return;
  }
  z->std_off = -std_west; // POSIX counts west of Greenwich as positive
  z->dst_off = z->std_off;
  z->rule_has_dst = false;
  if (*p == '\0' || *p == '\n') {
    z->has_rule = true;
    return;
  }
  if (!(p = caldav_tz_skip_name(p))) {
    return;
  }
  z->dst_off = z->std_off + 3600;
  if (*p != ',' && *p != '\0' && *p != '\n') {
    int32_t dst_west = 0;
    if (!(p = caldav_tz_parse_secs(p, &dst_west))) {
      return;
    }
    z->dst_off = -dst_west;
  }
  if (*p != ',' || !(p = caldav_tz_parse_date(p + 1, &z->start)) || *p != ',' ||
      !(p = caldav_tz_parse_date(p + 1, &z->end))) {
    return;
  }
  z->rule_has_dst = true;
  z->has_rule = true;
}

// Loads a zone. "UTC" and its aliases need no file. False when the name is
// unusable or the file is missing or malformed - the caller then treats the
// time as UTC, which is wrong by hours but never by days.
static bool caldav_zone_load(const char *name, CalDAVZone *z) {
  assert(z != NULL);
  memset(z, 0, sizeof(*z));
  z->ntypes = 1; // offset 0
  if (name &&
      (strcasecmp(name, "UTC") == 0 || strcasecmp(name, "Etc/UTC") == 0 ||
       strcasecmp(name, "GMT") == 0 || strcasecmp(name, "Z") == 0)) {
    return true;
  }
  if (!caldav_zone_name_ok(name)) {
    return false;
  }
  char path[128];
  snprintf(path, sizeof(path), "/usr/share/zoneinfo/%s", name);
  FILE *f = fopen(path, "rb");
  if (!f) {
    return false;
  }
  // A fat New York is 3.5KB; nothing in tzdata comes near this.
  static const size_t cap = 64 * 1024;
  unsigned char buf[64 * 1024];
  size_t len = fread(buf, 1, cap, f);
  fclose(f);
  if (len < 44 || memcmp(buf, "TZif", 4) != 0) {
    return false;
  }

  // Header: six big-endian counts at offset 20.
  const unsigned char *h = buf;
  int64_t isut = caldav_be32(h + 20), isstd = caldav_be32(h + 24),
          leap = caldav_be32(h + 28), timecnt = caldav_be32(h + 32),
          typecnt = caldav_be32(h + 36), charcnt = caldav_be32(h + 40);
  int tsize = 4;
  size_t at = 44;
  if (buf[4] >= '2') {
    // Version 2+: skip the 32-bit block, read the 64-bit one and its footer.
    size_t v1 =
        (size_t)(timecnt * 5 + typecnt * 6 + charcnt + leap * 8 + isstd + isut);
    at = 44 + v1;
    if (at + 44 > len || memcmp(buf + at, "TZif", 4) != 0) {
      return false;
    }
    h = buf + at;
    isut = caldav_be32(h + 20);
    isstd = caldav_be32(h + 24);
    leap = caldav_be32(h + 28);
    timecnt = caldav_be32(h + 32);
    typecnt = caldav_be32(h + 36);
    charcnt = caldav_be32(h + 40);
    tsize = 8;
    at += 44;
  }
  if (timecnt < 0 || timecnt > CALDAV_TZ_MAX_TRANS || typecnt < 1 ||
      typecnt > CALDAV_TZ_MAX_TYPES || charcnt < 0 || leap < 0 || isstd < 0 ||
      isut < 0) {
    return false;
  }
  size_t body = (size_t)(timecnt * (tsize + 1) + typecnt * 6 + charcnt +
                         leap * (tsize + 4) + isstd + isut);
  if (at + body > len) {
    return false;
  }
  const unsigned char *p = buf + at;
  z->ntrans = (int)timecnt;
  for (int i = 0; i < z->ntrans; i++) {
    z->trans[i] = tsize == 8 ? caldav_be64(p) : caldav_be32(p);
    p += tsize;
  }
  for (int i = 0; i < z->ntrans; i++) {
    z->idx[i] = p[i] < typecnt ? p[i] : 0;
  }
  p += z->ntrans;
  z->ntypes = (int)typecnt;
  for (int i = 0; i < z->ntypes; i++) {
    z->type_off[i] = caldav_be32(p);
    z->type_dst[i] = p[4] != 0;
    p += 6;
  }
  if (tsize == 8) {
    const char *footer = (const char *)(buf + at + body);
    size_t rest = len - (at + body);
    if (rest > 2 && footer[0] == '\n') {
      char rule[128];
      size_t n = 0;
      while (n + 1 < rest && n < sizeof(rule) - 1 && footer[1 + n] != '\n') {
        rule[n] = footer[1 + n];
        n++;
      }
      rule[n] = '\0';
      caldav_tz_parse_rule(rule, z);
    }
  }
  return true;
}

// The UTC instant a POSIX rule date falls on in `year`, given the offset in
// force just before it.
static int64_t caldav_tz_rule_instant(const CalDAVTzRuleDate *r, int year,
                                      int32_t off_before) {
  static const int mdays[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  int dim = mdays[r->month - 1];
  if (r->month == 2 &&
      ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) {
    dim = 29;
  }
  int first_dow = caldav_day_of_week(year, r->month, 1);
  int day = 1 + (r->wday - first_dow + 7) % 7 + (r->week - 1) * 7;
  while (day > dim) {
    day -= 7;
  }
  return caldav_epoch(year, r->month, day, 0, 0, 0) + r->secs - off_before;
}

// Seconds east of UTC in force at instant `t`.
static int32_t caldav_zone_offset(const CalDAVZone *z, int64_t t) {
  assert(z != NULL);
  bool past_table = z->ntrans == 0 || t >= z->trans[z->ntrans - 1];
  if (past_table && z->has_rule) {
    if (!z->rule_has_dst) {
      return z->std_off;
    }
    int y, mo, d, h, mi, s;
    caldav_epoch_split(t + z->std_off, &y, &mo, &d, &h, &mi, &s);
    int64_t start = caldav_tz_rule_instant(&z->start, y, z->std_off);
    int64_t end = caldav_tz_rule_instant(&z->end, y, z->dst_off);
    bool dst = start < end ? (t >= start && t < end) : !(t >= end && t < start);
    return dst ? z->dst_off : z->std_off;
  }
  if (z->ntrans == 0 || t < z->trans[0]) {
    // Before the first transition: the first standard-time type.
    for (int i = 0; i < z->ntypes; i++) {
      if (!z->type_dst[i]) {
        return z->type_off[i];
      }
    }
    return z->type_off[0];
  }
  int lo = 0, hi = z->ntrans - 1; // last transition <= t
  while (lo < hi) {
    int mid = (lo + hi + 1) / 2;
    if (z->trans[mid] <= t) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return z->type_off[z->idx[lo]];
}

// A wall-clock time in a zone as a UTC instant. Guess that the wall clock
// was UTC, ask the zone what that reads as, correct by the difference - and
// once more, for the hour a change of offset moves.
static int64_t caldav_zone_to_utc(const CalDAVZone *z, int64_t wall) {
  int64_t t = wall - caldav_zone_offset(z, wall);
  t = wall - caldav_zone_offset(z, t);
  return t;
}

// The zone dates without one are read in: $LCARS_TZ, else the zone the
// phone last wrote a TZID in (it knows where the user is; this box, seven
// hours away, does not), else UTC. Learnt per request and kept per thread.
// The learnt zone is remembered in caldav_meta rather than looked for in
// the kept lines, because a task rescheduled in the journal goes back out
// in UTC, and the client's next PUT of it carries no TZID any more.
static _Thread_local char g_caldav_zone[64];

static void caldav_tzid_of(const char *text, char *out, size_t out_size) {
  assert(out != NULL && out_size > 0);
  out[0] = '\0';
  const char *p = text ? strstr(text, "TZID=") : NULL;
  if (!p) {
    return;
  }
  p += 5;
  if (*p == '"') {
    p++;
  }
  size_t n = 0;
  while (p[n] && p[n] != ':' && p[n] != ';' && p[n] != '"' && p[n] != '\n' &&
         n < out_size - 1) {
    out[n] = p[n];
    n++;
  }
  out[n] = '\0';
}

static void caldav_init_zone(sqlite3 *db) {
  assert(db != NULL);
  g_caldav_zone[0] = '\0';
  const char *env = getenv("LCARS_TZ");
  if (env && env[0] != '\0') {
    caldav_copy_str(g_caldav_zone, sizeof(g_caldav_zone), env);
    return;
  }
  // Remembered, else (a side table from before caldav_meta) the newest kept
  // line with one: INSERT OR REPLACE gives a rewritten row a new rowid, so
  // the highest one is the most recent write.
  static const char *sql[] = {
      "SELECT value FROM caldav_meta WHERE key = 'zone';",
      "SELECT extra_ical FROM caldav_tasks WHERE extra_ical LIKE '%TZID=%' "
      "ORDER BY rowid DESC LIMIT 1;"};
  for (int i = 0; i < 2 && g_caldav_zone[0] == '\0'; i++) {
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql[i], -1, &stmt, NULL) != SQLITE_OK) {
      continue;
    }
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *v = (const char *)sqlite3_column_text(stmt, 0);
      if (i == 0) {
        caldav_copy_str(g_caldav_zone, sizeof(g_caldav_zone), v);
      } else {
        caldav_tzid_of(v, g_caldav_zone, sizeof(g_caldav_zone));
      }
    }
    sqlite3_finalize(stmt);
  }
}

// Remembers the zone a client's dates are written in, when they name one.
static void caldav_remember_zone(sqlite3 *db, const char *zone) {
  assert(db != NULL);
  CalDAVZone tz;
  if (!zone || strcmp(zone, g_caldav_zone) == 0 ||
      !caldav_zone_load(zone, &tz)) {
    return; // already known, or not a zone this box has
  }
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db,
                         "INSERT INTO caldav_meta (key, value) VALUES ('zone', "
                         "?1) ON CONFLICT(key) DO UPDATE SET value = "
                         "excluded.value;",
                         -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, zone, -1, SQLITE_TRANSIENT);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }
  caldav_copy_str(g_caldav_zone, sizeof(g_caldav_zone), zone);
}

static const char *caldav_default_zone(void) {
  return g_caldav_zone[0] != '\0' ? g_caldav_zone : "UTC";
}

// Where the web UI is, as this request reached the server: every task goes
// out with a URL to its own entry there (`<base>#e=<id>`), so a reminder
// is one tap from the journal entry it is. $LCARS_UI_URL names the page
// ("0" turns the link off); without it, a request that came through
// tailscale serve (a Host on *.ts.net, which is always https) implies
// "https://<host>/ui/", the path that serve publishes. Anything else gets
// no link. Per request, since it is what this client can reach.
static _Thread_local char g_caldav_ui_base[256];

static void caldav_init_ui_base(const char *headers) {
  assert(headers != NULL);
  g_caldav_ui_base[0] = '\0';
  const char *env = getenv("LCARS_UI_URL");
  if (env && env[0] != '\0') {
    if (strcmp(env, "0") != 0 && strncmp(env, "http", 4) == 0) {
      caldav_copy_str(g_caldav_ui_base, sizeof(g_caldav_ui_base), env);
    }
    return;
  }
  char host[160];
  if (!CopyHeaderValue(headers, "Host:", host, sizeof(host))) {
    return;
  }
  char *colon = strchr(host, ':');
  if (colon) {
    *colon = '\0';
  }
  size_t n = strlen(host);
  if (n > 7 && strcasecmp(host + n - 7, ".ts.net") == 0 &&
      strspn(host, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                   "0123456789.-") == n) {
    snprintf(g_caldav_ui_base, sizeof(g_caldav_ui_base), "https://%s/ui/",
             host);
  }
}

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

// Appends `s` XML-escaped. Everything the client sent comes back out through
// here, so a title containing "<" cannot break the multistatus document.
static void caldav_append_xml(JSONBuf *b, const char *s) {
  assert(b != NULL);
  for (const char *p = s ? s : ""; *p; p++) {
    switch (*p) {
    case '&':
      jsonbuf_append_len(b, "&amp;", 5);
      break;
    case '<':
      jsonbuf_append_len(b, "&lt;", 4);
      break;
    case '>':
      jsonbuf_append_len(b, "&gt;", 4);
      break;
    case '"':
      jsonbuf_append_len(b, "&quot;", 6);
      break;
    case '\'':
      jsonbuf_append_len(b, "&apos;", 6);
      break;
    default:
      jsonbuf_append_len(b, p, 1);
      break;
    }
  }
}

// Percent-encodes one path segment into `out`: everything but the RFC 3986
// unreserved characters. A Reminders UUID passes through unchanged, which
// is why hrefs did not move when this started encoding them.
static void caldav_escape_segment(const char *s, char *out, size_t out_size) {
  assert(s != NULL && out != NULL && out_size > 0);
  static const char hex[] = "0123456789ABCDEF";
  size_t o = 0;
  for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
    bool plain = (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
                 (*p >= '0' && *p <= '9') || *p == '-' || *p == '.' ||
                 *p == '_' || *p == '~';
    if (plain) {
      if (o + 1 >= out_size) {
        break;
      }
      out[o++] = (char)*p;
    } else {
      if (o + 3 >= out_size) {
        break;
      }
      out[o++] = '%';
      out[o++] = hex[*p >> 4];
      out[o++] = hex[*p & 15];
    }
  }
  out[o] = '\0';
}

// An iCalendar output stream that folds as it writes (RFC 5545 3.1): no
// line over 75 octets, continuations introduced by a single space, and never
// a break in the middle of a UTF-8 sequence. Folding while writing rather
// than in a second pass keeps a task's text out of the arena twice - which
// matters here, because the response buffer is growing in the same arena.
typedef struct IcsWriter {
  JSONBuf *out;
  size_t col;
} IcsWriter;

static void ics_init(IcsWriter *w, JSONBuf *out) {
  assert(w != NULL);
  assert(out != NULL);
  w->out = out;
  w->col = 0;
}

// Writes `len` raw octets of the current content line, folding as needed.
// Must not be handed a line break - use ics_endline() for that.
static void ics_write_len(IcsWriter *w, const char *s, size_t len) {
  assert(w != NULL);
  assert(s != NULL || len == 0);

  for (size_t i = 0; i < len; i++) {
    unsigned char c = (unsigned char)s[i];
    assert(c != '\n' && c != '\r'); // callers escape or split first
    bool continuation_byte = (c & 0xC0) == 0x80;
    if (w->col >= 74 && !continuation_byte) {
      jsonbuf_append_len(w->out, "\r\n ", 3);
      w->col = 1;
    }
    jsonbuf_append_len(w->out, (const char *)&c, 1);
    w->col++;
  }
}

static void ics_write(IcsWriter *w, const char *s) {
  ics_write_len(w, s, s ? strlen(s) : 0);
}

static void ics_endline(IcsWriter *w) {
  assert(w != NULL);
  jsonbuf_append_len(w->out, "\r\n", 2);
  w->col = 0;
}

// Writes a whole property line whose value needs no escaping (timestamps,
// enumerated keywords).
static void ics_write_line(IcsWriter *w, const char *name, const char *value) {
  assert(name != NULL);
  assert(value != NULL);
  ics_write(w, name);
  ics_write_len(w, ":", 1);
  ics_write(w, value);
  ics_endline(w);
}

// Writes `s` as an iCalendar TEXT value (RFC 5545 3.3.11): backslash,
// semicolon and comma escaped, and real newlines emitted as the literal
// two-character sequence "\n".
static void ics_write_text(IcsWriter *w, const char *s) {
  assert(w != NULL);
  for (const char *p = s ? s : ""; *p; p++) {
    switch (*p) {
    case '\\':
      ics_write_len(w, "\\\\", 2);
      break;
    case ';':
      ics_write_len(w, "\\;", 2);
      break;
    case ',':
      ics_write_len(w, "\\,", 2);
      break;
    case '\r':
      break; // a CRLF in the DB contributes one "\n", not two
    case '\n':
      ics_write_len(w, "\\n", 2);
      break;
    default:
      ics_write_len(w, p, 1);
      break;
    }
  }
}

// Copies an iCalendar TEXT value into the arena with those escapes undone.
static char *caldav_unescape_ical_text(Arena *arena, const char *s) {
  assert(arena_valid(arena));
  assert(s != NULL);

  size_t len = strlen(s);
  char *out = (char *)arena_alloc(arena, len + 1);
  size_t o = 0;
  for (size_t i = 0; i < len; i++) {
    if (s[i] == '\\' && i + 1 < len) {
      char next = s[i + 1];
      i++;
      switch (next) {
      case 'n':
      case 'N':
        out[o++] = '\n';
        break;
      case '\\':
        out[o++] = '\\';
        break;
      case ';':
        out[o++] = ';';
        break;
      case ',':
        out[o++] = ',';
        break;
      default:
        out[o++] = next;
        break;
      }
    } else {
      out[o++] = s[i];
    }
  }
  assert(o <= len);
  out[o] = '\0';
  return out;
}

// Undoes RFC 5545 line folding and normalizes every line ending to '\n', so
// the parser below can work one line at a time. Returns an arena copy.
static char *caldav_unfold(Arena *arena, const char *body, size_t *out_len) {
  assert(arena_valid(arena));
  assert(body != NULL);
  assert(out_len != NULL);

  size_t len = strlen(body);
  char *out = (char *)arena_alloc(arena, len + 1);
  size_t o = 0;
  for (size_t i = 0; i < len; i++) {
    char c = body[i];
    if (c == '\r' || c == '\n') {
      size_t nl_end = i;
      if (c == '\r' && i + 1 < len && body[i + 1] == '\n') {
        nl_end = i + 1;
      }
      char next = (nl_end + 1 < len) ? body[nl_end + 1] : '\0';
      if (next == ' ' || next == '\t') {
        i = nl_end + 1; // fold: drop the break and its leading whitespace
        continue;
      }
      out[o++] = '\n';
      i = nl_end;
      continue;
    }
    out[o++] = c;
  }
  assert(o <= len);
  out[o] = '\0';
  *out_len = o;
  return out;
}

// Whether `line` is the iCalendar property named `name` - i.e. the name is
// followed by a parameter list or the value separator, not just a prefix
// ("DUE" must not match "DUE-SOMETHING", and SUMMARY;LANGUAGE=en: must).
static bool caldav_line_is(const char *line, const char *name) {
  assert(line != NULL);
  assert(name != NULL);
  size_t n = strlen(name);
  if (strncasecmp(line, name, n) != 0) {
    return false;
  }
  return line[n] == ':' || line[n] == ';';
}

// The value of an iCalendar content line: everything after the first colon
// that is not inside a quoted parameter value.
static const char *caldav_line_value(const char *line) {
  assert(line != NULL);
  bool in_quotes = false;
  for (const char *p = line; *p; p++) {
    if (*p == '"') {
      in_quotes = !in_quotes;
    } else if (*p == ':' && !in_quotes) {
      return p + 1;
    }
  }
  return line + strlen(line);
}

// Walks a block of '\n'-separated kept lines. Each call yields the next
// non-empty line (not terminated - `len` says how long) and the component
// depth it sits at: 0 for a VTODO property, >0 inside a VALARM. A BEGIN
// line reports the depth outside it, its END line the same.
typedef struct CalDAVLineIter {
  const char *p;
  int depth;
} CalDAVLineIter;

static bool caldav_next_line(CalDAVLineIter *it, const char **line, size_t *len,
                             int *depth) {
  assert(it != NULL && line != NULL && len != NULL && depth != NULL);
  while (it->p && *it->p) {
    const char *start = it->p;
    const char *nl = strchr(start, '\n');
    size_t n = nl ? (size_t)(nl - start) : strlen(start);
    it->p = nl ? nl + 1 : start + n;
    while (n > 0 && (start[n - 1] == '\r' || start[n - 1] == ' ')) {
      n--;
    }
    if (n == 0) {
      continue;
    }
    *line = start;
    *len = n;
    if (n > 6 && strncasecmp(start, "BEGIN:", 6) == 0) {
      *depth = it->depth;
      it->depth++;
    } else if (n > 4 && strncasecmp(start, "END:", 4) == 0) {
      if (it->depth > 0) {
        it->depth--;
      }
      *depth = it->depth;
    } else {
      *depth = it->depth;
    }
    return true;
  }
  return false;
}

// The head of a line as a terminated string, enough to classify it by name
// or (for the short date lines) to parse it whole.
static void caldav_line_head(const char *line, size_t len, char *out,
                             size_t out_size) {
  assert(out != NULL && out_size > 0);
  size_t n = len < out_size - 1 ? len : out_size - 1;
  memcpy(out, line, n);
  out[n] = '\0';
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

// Adds a column to a side table that predates it - the same PRAGMA scan and
// ALTER as EnsureEntryColumn, because CREATE TABLE IF NOT EXISTS is a no-op
// against a table that already exists.
static bool caldav_ensure_column(sqlite3 *db, const char *table,
                                 const char *column, const char *decl) {
  assert(db != NULL && table != NULL && column != NULL && decl != NULL);
  char sql[256];
  snprintf(sql, sizeof(sql), "PRAGMA table_info(%s);", table);
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    return false;
  }
  bool found = false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *name = (const char *)sqlite3_column_text(stmt, 1);
    if (name && strcmp(name, column) == 0) {
      found = true;
    }
  }
  sqlite3_finalize(stmt);
  if (found) {
    return true;
  }
  snprintf(sql, sizeof(sql), "ALTER TABLE %s ADD COLUMN %s %s;", table, column,
           decl);
  char *err = NULL;
  if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
    printf("CalDAV Database Error: %s: %s\n", sql, err ? err : "?");
    sqlite3_free(err);
    return false;
  }
  return true;
}

// The side tables. They are created here rather than in InitDB() on purpose:
// nothing but CalDAV reads them, the journal schema stays exactly as it was,
// and a database that never sees a CalDAV request never grows them.
//
// caldav_tasks: resource_name is the client-chosen URL segment (Reminders
// sends "<uuid>.ics"), uid the VTODO's UID, and the two extra_* columns hold
// the iCalendar text this schema has nowhere else to put - property lines
// from inside the VTODO, and whole calendar-level components (VTIMEZONE).
// sync_start/sync_end are the schedule those lines last said, in the
// columns' own form: when start_date/end_date no longer match them,
// something other than a CalDAV client moved the task, and the lines are
// rewritten from the columns on the way out.
//
// caldav_lists: a list's URL segment, name, colour and order, for the kinds
// a client named, renamed or deleted (hidden = 1). A kind without a row is
// published with defaults.
//
// caldav_meta: what this server has learnt, by key. "zone" is the time
// zone the phone last wrote a TZID in (see caldav_init_zone).
//
// caldav_moves, with its trigger: the list a task left when its kind
// changed - by Reminders moving it, the web UI, lcars-cli, anything - and
// the resource name it had there. A sync-collection report must tell the
// old list's client the task is gone, and nothing else remembers where it
// was.
static bool caldav_ensure_schema(sqlite3 *db) {
  assert(db != NULL);

  char *err = NULL;
  int rc = sqlite3_exec(
      db,
      "CREATE TABLE IF NOT EXISTS caldav_tasks ("
      "entry_id INTEGER PRIMARY KEY,"
      "resource_name TEXT NOT NULL UNIQUE,"
      "uid TEXT NOT NULL,"
      "extra_ical TEXT,"
      "extra_vcal TEXT,"
      "sync_start TEXT,"
      "sync_end TEXT);"
      "CREATE TABLE IF NOT EXISTS caldav_lists ("
      "kind TEXT PRIMARY KEY,"
      "segment TEXT NOT NULL UNIQUE,"
      "displayname TEXT,"
      "color TEXT,"
      "sort_order INTEGER,"
      "hidden INTEGER NOT NULL DEFAULT 0);"
      "CREATE TABLE IF NOT EXISTS caldav_moves ("
      "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
      "entry_id INTEGER NOT NULL,"
      "old_kind TEXT,"
      "old_name TEXT,"
      "at TEXT NOT NULL);"
      "CREATE INDEX IF NOT EXISTS caldav_moves_kind ON caldav_moves(old_kind, "
      "at);"
      "CREATE TABLE IF NOT EXISTS caldav_meta (key TEXT PRIMARY KEY, value "
      "TEXT);"
      "CREATE TRIGGER IF NOT EXISTS caldav_kind_moved AFTER UPDATE OF kind ON "
      "entries WHEN OLD.kind IS NOT NEW.kind BEGIN "
      "INSERT INTO caldav_moves (entry_id, old_kind, old_name, at) VALUES "
      "(OLD.id, OLD.kind, (SELECT resource_name FROM caldav_tasks WHERE "
      "entry_id = OLD.id), strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')); END;",
      NULL, NULL, &err);
  if (rc != SQLITE_OK) {
    printf("CalDAV Database Error: cannot create the side tables: %s\n",
           err ? err : sqlite3_errstr(rc));
    sqlite3_free(err);
    return false;
  }
  // caldav_tasks predates the schedule mapping on the live journal.
  return caldav_ensure_column(db, "caldav_tasks", "sync_start", "TEXT") &&
         caldav_ensure_column(db, "caldav_tasks", "sync_end", "TEXT");
}

// The resource name a task is published under: whatever the client PUT it
// as, or a name derived from the row id for tasks created in the UI.
static void caldav_resource_name(int id, const char *stored, char *out,
                                 size_t out_size) {
  assert(id > 0);
  assert(out != NULL);
  assert(out_size > 32);

  if (stored && stored[0] != '\0') {
    caldav_copy_str(out, out_size, stored);
    return;
  }
  int n = snprintf(out, out_size, "lcars-%d.ics", id);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

static void caldav_uid(int id, const char *stored, char *out, size_t out_size) {
  assert(id > 0);
  assert(out != NULL);
  assert(out_size > 32);

  if (stored && stored[0] != '\0') {
    caldav_copy_str(out, out_size, stored);
    return;
  }
  int n = snprintf(out, out_size, "lcars-%d@lcars", id);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// The reverse of caldav_resource_name() / caldav_uid() for UI-created tasks:
// "lcars-42.ics" (or "lcars-42@lcars") -> 42. Returns 0 for any other shape,
// which is the signal to look the name up in the side table instead.
static int caldav_id_from_generated(const char *name, const char *suffix) {
  assert(name != NULL && suffix != NULL);
  const char *prefix = "lcars-";
  size_t prefix_len = strlen(prefix);
  if (strncmp(name, prefix, prefix_len) != 0) {
    return 0;
  }
  const char *digits = name + prefix_len;
  char *end = NULL;
  long value = strtol(digits, &end, 10);
  if (end == digits || value <= 0 || value > INT_MAX) {
    return 0;
  }
  if (strcasecmp(end, suffix) != 0) {
    return 0;
  }
  return (int)value;
}

static int caldav_id_from_generated_name(const char *name) {
  return caldav_id_from_generated(name, ".ics");
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------

// What a kind without a caldav_lists row is published as. "task_personal"
// reads "Personal"; the colours are the LCARS palette, picked by the kind's
// hash so a list keeps its colour on every device.
static void caldav_list_defaults(const char *kind, CalDAVList *l) {
  assert(kind != NULL && l != NULL);
  static const char *palette[] = {"#CC99CCFF", "#9999FFFF", "#FF9966FF",
                                  "#CC6666FF", "#99CCFFFF", "#FFCC66FF",
                                  "#66CC99FF", "#FF6699FF"};
  const char *base = caldav_task_kind();
  memset(l, 0, sizeof(*l));
  caldav_copy_str(l->kind, sizeof(l->kind), kind);
  if (strcmp(kind, base) == 0) {
    caldav_copy_str(l->segment, sizeof(l->segment), CALDAV_BASE_SEGMENT);
    caldav_copy_str(l->name, sizeof(l->name), CALDAV_DISPLAY_NAME);
    caldav_copy_str(l->color, sizeof(l->color), "#FF9900FF");
    return;
  }
  caldav_copy_str(l->segment, sizeof(l->segment), kind);
  const char *rest = kind;
  size_t base_len = strlen(base);
  if (strncmp(kind, base, base_len) == 0 && kind[base_len] == '_') {
    rest = kind + base_len + 1;
  }
  caldav_copy_str(l->name, sizeof(l->name), rest);
  for (char *p = l->name; *p; p++) {
    if (*p == '_') {
      *p = ' ';
    }
  }
  if (l->name[0] >= 'a' && l->name[0] <= 'z') {
    l->name[0] = (char)(l->name[0] - 'a' + 'A');
  }
  uint64_t h = caldav_hash_str(CALDAV_HASH_SEED, kind);
  caldav_copy_str(l->color, sizeof(l->color),
                  palette[h % (sizeof(palette) / sizeof(palette[0]))]);
}

// Every list: the task kind's (always, even empty - the account's first
// collection must not come and go), each sub-kind any entry has ever had,
// deleted ones included (deleting a list's last reminder must not make the
// list itself vanish), and every list a client created or touched. Hidden
// ones only when asked for. Returns the count.
static int caldav_load_lists(sqlite3 *db, CalDAVList *out, int cap,
                             bool include_hidden) {
  assert(db != NULL && out != NULL && cap > 0);
  sqlite3_stmt *stmt = NULL;
  const char *sql =
      "SELECT k.kind, l.segment, l.displayname, l.color, l.sort_order, "
      "COALESCE(l.hidden, 0), l.kind IS NOT NULL FROM ("
      "SELECT ?1 AS kind UNION SELECT DISTINCT kind FROM entries "
      "WHERE " CALDAV_SQL_TASKISH(
          "kind") " UNION SELECT kind FROM caldav_lists) k LEFT JOIN "
                  "caldav_lists l ON l.kind = k.kind ORDER BY CASE WHEN "
                  "k.kind = ?1 THEN 0 ELSE 1 END, k.kind;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: %s\n", sqlite3_errmsg(db));
    return 0;
  }
  sqlite3_bind_text(stmt, 1, caldav_task_kind(), -1, SQLITE_STATIC);
  int count = 0;
  int position = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *kind = (const char *)sqlite3_column_text(stmt, 0);
    if (!kind || kind[0] == '\0') {
      continue;
    }
    position++;
    bool hidden = sqlite3_column_int(stmt, 5) != 0;
    if (hidden && !include_hidden) {
      continue;
    }
    if (count == cap) {
      printf("CalDAV: more than %d lists; '%s' and later are not published\n",
             cap, kind);
      break;
    }
    CalDAVList *l = &out[count++];
    caldav_list_defaults(kind, l);
    l->order = position;
    l->hidden = hidden;
    l->stored = sqlite3_column_int(stmt, 6) != 0;
    const char *seg = (const char *)sqlite3_column_text(stmt, 1);
    const char *name = (const char *)sqlite3_column_text(stmt, 2);
    const char *color = (const char *)sqlite3_column_text(stmt, 3);
    if (seg && seg[0] != '\0') {
      caldav_copy_str(l->segment, sizeof(l->segment), seg);
    }
    if (name && name[0] != '\0') {
      caldav_copy_str(l->name, sizeof(l->name), name);
    }
    if (color && color[0] != '\0') {
      caldav_copy_str(l->color, sizeof(l->color), color);
    }
    if (sqlite3_column_type(stmt, 4) != SQLITE_NULL) {
      l->order = sqlite3_column_int(stmt, 4);
    }
  }
  sqlite3_finalize(stmt);
  assert(count <= cap);
  return count;
}

static bool caldav_list_by_segment(sqlite3 *db, const char *segment,
                                   CalDAVList *out) {
  assert(db != NULL && segment != NULL && out != NULL);
  CalDAVList lists[CALDAV_MAX_LISTS];
  int n = caldav_load_lists(db, lists, CALDAV_MAX_LISTS, false);
  for (int i = 0; i < n; i++) {
    if (strcmp(lists[i].segment, segment) == 0) {
      *out = lists[i];
      return true;
    }
  }
  return false;
}

static bool caldav_list_by_kind(sqlite3 *db, const char *kind, CalDAVList *out,
                                bool include_hidden) {
  assert(db != NULL && out != NULL);
  if (!caldav_kind_is_tasks(kind)) {
    // Only reachable for a client-made list, whose kind is always a
    // sub-kind, so this is not a list.
    return false;
  }
  CalDAVList lists[CALDAV_MAX_LISTS];
  int n = caldav_load_lists(db, lists, CALDAV_MAX_LISTS, include_hidden);
  for (int i = 0; i < n; i++) {
    if (strcmp(lists[i].kind, kind) == 0) {
      *out = lists[i];
      return true;
    }
  }
  return false;
}

static bool caldav_list_save(sqlite3 *db, const CalDAVList *l) {
  assert(db != NULL && l != NULL);
  assert(l->kind[0] != '\0' && l->segment[0] != '\0');
  sqlite3_stmt *stmt = NULL;
  const char *sql =
      "INSERT INTO caldav_lists (kind, segment, displayname, color, "
      "sort_order, hidden) VALUES (?1, ?2, ?3, ?4, ?5, ?6) ON CONFLICT(kind) "
      "DO UPDATE SET segment = excluded.segment, displayname = "
      "excluded.displayname, color = excluded.color, sort_order = "
      "excluded.sort_order, hidden = excluded.hidden;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: %s\n", sqlite3_errmsg(db));
    return false;
  }
  sqlite3_bind_text(stmt, 1, l->kind, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, l->segment, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 3, l->name, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 4, l->color, -1, SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 5, l->order);
  sqlite3_bind_int(stmt, 6, l->hidden ? 1 : 0);
  bool ok = sqlite3_step(stmt) == SQLITE_DONE;
  if (!ok) {
    printf("CalDAV Database Error: list write failed: %s\n",
           sqlite3_errmsg(db));
  }
  sqlite3_finalize(stmt);
  return ok;
}

static void caldav_collection_href(const CalDAVList *l, char *out,
                                   size_t out_size) {
  assert(l != NULL && out != NULL);
  char seg[CALDAV_MAX_NAME * 3];
  caldav_escape_segment(l->segment, seg, sizeof(seg));
  int n = snprintf(out, out_size, CALDAV_HOME_PATH "%s/", seg);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// The absolute path a task is published at, for <D:href>.
static void caldav_task_href(const CalDAVList *l, const char *name, char *out,
                             size_t out_size) {
  assert(l != NULL && name != NULL && out != NULL);
  char coll[CALDAV_MAX_NAME * 3 + 32];
  char seg[CALDAV_MAX_NAME * 3];
  caldav_collection_href(l, coll, sizeof(coll));
  caldav_escape_segment(name, seg, sizeof(seg));
  int n = snprintf(out, out_size, "%s%s", coll, seg);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// Resolves a resource name in one list to an entry id, whether the task was
// created here (generated name) or by a client (name in the side table).
// Returns 0 when no such task exists. `include_deleted` is for PUT, which
// resurrects a soft-deleted row rather than inserting a duplicate.
static int caldav_lookup_entry_id(sqlite3 *db, const char *kind,
                                  const char *name, bool include_deleted) {
  assert(db != NULL);
  assert(kind != NULL && name != NULL);

  int id = caldav_id_from_generated_name(name);
  if (id > 0) {
    // The name only claims to be a task; confirm the row is one, and that
    // it is not a side-table task whose client-chosen name happens to look
    // generated.
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        include_deleted
            ? "SELECT e.id FROM entries e LEFT JOIN caldav_tasks c ON "
              "c.entry_id = e.id WHERE e.id = ?1 AND e.kind = ?2 AND "
              "c.resource_name IS NULL;"
            : "SELECT e.id FROM entries e LEFT JOIN caldav_tasks c ON "
              "c.entry_id = e.id WHERE e.id = ?1 AND e.kind = ?2 AND "
              "c.resource_name IS NULL AND (e.deleted IS NULL OR e.deleted "
              "= 0);";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
      return 0;
    }
    sqlite3_bind_int(stmt, 1, id);
    sqlite3_bind_text(stmt, 2, kind, -1, SQLITE_TRANSIENT);
    int found =
        (sqlite3_step(stmt) == SQLITE_ROW) ? sqlite3_column_int(stmt, 0) : 0;
    sqlite3_finalize(stmt);
    if (found > 0) {
      return found;
    }
  }

  sqlite3_stmt *stmt = NULL;
  const char *sql =
      include_deleted
          ? "SELECT e.id FROM caldav_tasks c JOIN entries e ON e.id = "
            "c.entry_id WHERE c.resource_name = ?1 AND e.kind = ?2;"
          : "SELECT e.id FROM caldav_tasks c JOIN entries e ON e.id = "
            "c.entry_id WHERE c.resource_name = ?1 AND e.kind = ?2 AND "
            "(e.deleted IS NULL OR e.deleted = 0);";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    return 0;
  }
  sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, kind, -1, SQLITE_TRANSIENT);
  int found =
      (sqlite3_step(stmt) == SQLITE_ROW) ? sqlite3_column_int(stmt, 0) : 0;
  sqlite3_finalize(stmt);
  return found;
}

// A task in *another* list (or soft-deleted) that a PUT is about: by its
// resource name, else by its UID. This is how a reminder moved between
// lists stays one entry - a client moves it by writing it into the new
// collection and deleting it from the old one, and whichever arrives
// first, the row is found, re-kinded and kept. Returns 0 when it is new.
static int caldav_find_elsewhere(sqlite3 *db, const char *name,
                                 const char *uid) {
  assert(db != NULL && name != NULL && uid != NULL);
  const char *task_kind = caldav_task_kind();
  int id = 0;
  sqlite3_stmt *stmt = NULL;

  // Client-chosen names and UIDs, in the side table.
  const char *by_side =
      "SELECT c.entry_id FROM caldav_tasks c JOIN entries e ON e.id = "
      "c.entry_id WHERE (c.resource_name = ?2 OR (?3 <> '' AND c.uid = ?3)) "
      "AND " CALDAV_SQL_TASKISH("e.kind") " ORDER BY c.resource_name = ?2 "
                                          "DESC, (e.deleted IS NULL OR "
                                          "e.deleted = 0) DESC, c.entry_id "
                                          "DESC LIMIT 1;";
  if (sqlite3_prepare_v2(db, by_side, -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, task_kind, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, uid, -1, SQLITE_TRANSIENT);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      id = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }
  if (id > 0) {
    return id;
  }
  // A UI-made task travels under its generated name and UID.
  int generated = caldav_id_from_generated_name(name);
  if (generated == 0) {
    generated = caldav_id_from_generated(uid, "@lcars");
  }
  if (generated == 0) {
    return 0;
  }
  const char *by_id =
      "SELECT e.id FROM entries e LEFT JOIN caldav_tasks c ON c.entry_id = "
      "e.id WHERE e.id = ?2 AND c.entry_id IS NULL AND " CALDAV_SQL_TASKISH(
          "e.kind") ";";
  if (sqlite3_prepare_v2(db, by_id, -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, task_kind, -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 2, generated);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      id = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }
  return id;
}

// ---------------------------------------------------------------------------
// The schedule: DTSTART/DUE <-> start_date/end_date
//
// Reminders writes a dated reminder as DTSTART and DUE with the same wall
// clock and a TZID ("DTSTART;TZID=Europe/Madrid:20261007T150000"), an
// all-day one as two DATEs, and an alarm as an absolute TRIGGER at the due
// instant. The columns are UTC text, and a block's end. So:
//
//   timed:   start = DTSTART (else DUE), end = DUE (else DTSTART) - a
//            reminder is a block of no length at its due time. Never an
//            empty end: the web UI reads "start set, end empty" as a
//            running stopwatch, and an overdue task is not one.
//   all day: start = the date's midnight in the zone, end = the next
//            midnight after the last date.
//
// Back the other way, only when the columns have moved since a client last
// wrote the lines (sync_start/sync_end): a block that is whole days of
// midnights goes out as DATEs, anything else as UTC, and the absolute
// alarms move by however far the start did.
// ---------------------------------------------------------------------------

typedef struct CalDAVWhen {
  bool present;
  bool all_day;
  int y, m, d;   // the date, for an all-day value
  int64_t t;     // the instant (UTC), for a timed one
  char tzid[64]; // the TZID it was written in, "" for UTC/floating/date
} CalDAVWhen;

// Parses a DTSTART/DUE line (terminated). Dates without a zone, and
// floating times, are read in `zone`.
static bool caldav_parse_when(const char *line, const char *zone,
                              CalDAVWhen *out) {
  assert(line != NULL && zone != NULL && out != NULL);
  memset(out, 0, sizeof(*out));
  const char *value = caldav_line_value(line);
  // The parameters: between the name and the value's colon.
  size_t params_len = (size_t)(value - line);
  char params[192];
  caldav_line_head(line, params_len, params, sizeof(params));
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  char z = '\0';
  int got =
      sscanf(value, "%4d%2d%2dT%2d%2d%2d%c", &y, &mo, &d, &h, &mi, &s, &z);
  if (got < 3 || mo < 1 || mo > 12 || d < 1 || d > 31) {
    return false;
  }
  out->present = true;
  out->y = y;
  out->m = mo;
  out->d = d;
  if (got == 3) {
    out->all_day = true;
    return true;
  }
  if (got < 6 || h > 23 || mi > 59 || s > 60) {
    out->present = false;
    return false;
  }
  int64_t wall = caldav_epoch(y, mo, d, h, mi, s);
  if (got == 7 && (z == 'Z' || z == 'z')) {
    out->t = wall;
    return true;
  }
  caldav_tzid_of(params, out->tzid, sizeof(out->tzid));
  CalDAVZone tz;
  const char *use = out->tzid[0] != '\0' ? out->tzid : zone;
  if (!caldav_zone_load(use, &tz)) {
    printf("CalDAV: unknown time zone '%s'; reading it as UTC\n", use);
    caldav_zone_load("UTC", &tz);
  }
  out->t = caldav_zone_to_utc(&tz, wall);
  return true;
}

// The midnight a date starts at, in a zone, as UTC.
static int64_t caldav_date_start(int y, int m, int d, const char *zone) {
  CalDAVZone tz;
  if (!caldav_zone_load(zone, &tz)) {
    caldav_zone_load("UTC", &tz);
  }
  return caldav_zone_to_utc(&tz, caldav_epoch(y, m, d, 0, 0, 0));
}

// The zone a task's dates live in: the TZID on its own DTSTART/DUE when it
// has one, else the default.
static void caldav_lines_zone(const char *extra, char *out, size_t out_size) {
  assert(out != NULL && out_size > 0);
  out[0] = '\0';
  CalDAVLineIter it = {extra ? extra : "", 0};
  const char *line;
  size_t len;
  int depth;
  while (caldav_next_line(&it, &line, &len, &depth)) {
    char head[256];
    caldav_line_head(line, len, head, sizeof(head));
    if (depth == 0 &&
        (caldav_line_is(head, "DTSTART") || caldav_line_is(head, "DUE"))) {
      char params[192];
      caldav_line_head(head, (size_t)(caldav_line_value(head) - head), params,
                       sizeof(params));
      caldav_tzid_of(params, out, out_size);
      if (out[0] != '\0') {
        return;
      }
    }
  }
  caldav_copy_str(out, out_size, caldav_default_zone());
}

// Reads the schedule the kept lines say into the columns' form. Both out
// buffers are "" when the task has no date.
static void caldav_derive_schedule(const char *extra, char *s_out,
                                   char *e_out) {
  assert(s_out != NULL && e_out != NULL);
  s_out[0] = '\0';
  e_out[0] = '\0';
  char zone[64];
  caldav_lines_zone(extra, zone, sizeof(zone));

  CalDAVWhen start, due;
  memset(&start, 0, sizeof(start));
  memset(&due, 0, sizeof(due));
  CalDAVLineIter it = {extra ? extra : "", 0};
  const char *line;
  size_t len;
  int depth;
  while (caldav_next_line(&it, &line, &len, &depth)) {
    if (depth != 0 || len >= 256) {
      continue;
    }
    char head[256];
    caldav_line_head(line, len, head, sizeof(head));
    if (caldav_line_is(head, "DTSTART")) {
      caldav_parse_when(head, zone, &start);
    } else if (caldav_line_is(head, "DUE")) {
      caldav_parse_when(head, zone, &due);
    }
  }
  if (!start.present && !due.present) {
    return;
  }
  const CalDAVWhen *first = start.present ? &start : &due;
  const CalDAVWhen *last = due.present ? &due : &start;
  int64_t s, e;
  if (last->all_day || first->all_day) {
    // A date is a whole day; a timed start before an all-day due keeps its
    // time and runs to the end of that day.
    s = first->all_day ? caldav_date_start(first->y, first->m, first->d, zone)
                       : first->t;
    if (last->all_day) {
      int ny = last->y, nm = last->m, nd = last->d;
      caldav_add_days(&ny, &nm, &nd, 1);
      e = caldav_date_start(ny, nm, nd, zone);
    } else {
      e = last->t;
    }
  } else {
    s = first->t;
    e = last->t;
  }
  if (e < s) {
    e = s;
  }
  caldav_epoch_to_sql(s, s_out, 20);
  caldav_epoch_to_sql(e, e_out, 20);
}

// Whether an instant is a midnight in a zone, and that date.
static bool caldav_is_midnight(const CalDAVZone *tz, int64_t t, int *y, int *m,
                               int *d) {
  int64_t wall = t + caldav_zone_offset(tz, t);
  int h, mi, s;
  caldav_epoch_split(wall, y, m, d, &h, &mi, &s);
  return h == 0 && mi == 0 && s == 0;
}

static void caldav_append_line(JSONBuf *out, const char *line, size_t len) {
  jsonbuf_append_len(out, line, len);
  jsonbuf_append_len(out, "\n", 1);
}

// The DTSTART/DUE lines for a schedule held in the columns.
static void caldav_append_schedule_lines(JSONBuf *out, int64_t s, bool has_e,
                                         int64_t e, const char *zone,
                                         bool *out_all_day) {
  CalDAVZone tz;
  if (!caldav_zone_load(zone, &tz)) {
    caldav_zone_load("UTC", &tz);
  }
  int sy, sm, sd, ey, em, ed;
  if (has_e && e > s && caldav_is_midnight(&tz, s, &sy, &sm, &sd) &&
      caldav_is_midnight(&tz, e, &ey, &em, &ed)) {
    // Whole days: the last one is the day before the end's midnight.
    int ly = ey, lm = em, ld = ed;
    caldav_add_days(&ly, &lm, &ld, -1);
    jsonbuf_appendf(out, "DTSTART;VALUE=DATE:%04d%02d%02d\n", sy, sm, sd);
    jsonbuf_appendf(out, "DUE;VALUE=DATE:%04d%02d%02d\n", ly, lm, ld);
    *out_all_day = true;
    return;
  }
  char a[20], b[20];
  caldav_epoch_to_ical(s, a, sizeof(a));
  caldav_epoch_to_ical(has_e && e >= s ? e : s, b, sizeof(b));
  jsonbuf_appendf(out, "DTSTART:%s\nDUE:%s\n", a, b);
  *out_all_day = false;
}

// The kept lines as a client should see them now: verbatim while the
// columns still say what the lines said, else with DTSTART/DUE rewritten
// from the columns and the absolute alarms moved with them. Property lines
// first, components after, as RFC 5545's grammar has it.
static void caldav_effective_extra(int id, const char *extra, const char *s,
                                   const char *e, const char *ss,
                                   const char *se, bool done, JSONBuf *out) {
  assert(id > 0 && out != NULL);
  extra = extra ? extra : "";
  s = s ? s : "";
  e = e ? e : "";
  ss = ss ? ss : "";
  se = se ? se : "";
  bool moved = strcmp(s, ss) != 0 || strcmp(e, se) != 0;

  int64_t ts = 0, te = 0, tss = 0;
  bool has_s = moved && caldav_sql_to_epoch(s, &ts);
  bool has_e = moved && caldav_sql_to_epoch(e, &te);
  bool had_s = caldav_sql_to_epoch(ss, &tss);
  bool shift = has_s && had_s && ts != tss;
  char zone[64];
  caldav_lines_zone(extra, zone, sizeof(zone));

  // Pass 0: properties; pass 1: components.
  bool saw_alarm = false;
  for (int pass = 0; pass < 2; pass++) {
    CalDAVLineIter it = {extra, 0};
    const char *line;
    size_t len;
    int depth;
    bool in_comp = false;
    while (caldav_next_line(&it, &line, &len, &depth)) {
      char head[256];
      caldav_line_head(line, len, head, sizeof(head));
      bool begin = depth == 0 && caldav_line_is(head, "BEGIN");
      if (begin) {
        in_comp = true;
        if (strncasecmp(caldav_line_value(head), "VALARM", 6) == 0) {
          saw_alarm = true;
        }
      }
      bool component_line = in_comp;
      if (depth == 0 && caldav_line_is(head, "END")) {
        in_comp = false;
      }
      if ((pass == 0) == component_line) {
        continue;
      }
      if (moved && !component_line &&
          (caldav_line_is(head, "DTSTART") || caldav_line_is(head, "DUE"))) {
        continue; // rewritten from the columns below
      }
      if (shift && component_line && len < 256 &&
          caldav_line_is(head, "TRIGGER") && strstr(head, "DATE-TIME")) {
        CalDAVWhen at;
        if (caldav_parse_when(head, zone, &at) && !at.all_day) {
          char v[20];
          caldav_epoch_to_ical(at.t + (ts - tss), v, sizeof(v));
          jsonbuf_appendf(out, "TRIGGER;VALUE=DATE-TIME:%s\n", v);
          continue;
        }
      }
      caldav_append_line(out, line, len);
    }
    if (pass == 0 && has_s) {
      bool all_day = false;
      caldav_append_schedule_lines(out, ts, has_e, te, zone, &all_day);
      // Scheduled from the journal for the first time: Reminders pairs a
      // timed due date with an alert, so the task gets one too.
      if (!had_s && !all_day && !done && !saw_alarm) {
        char v[20];
        caldav_epoch_to_ical(has_e && te >= ts ? te : ts, v, sizeof(v));
        // Written after the properties pass, i.e. with the components.
        saw_alarm = true;
        jsonbuf_appendf(out,
                        "BEGIN:VALARM\nACTION:DISPLAY\nDESCRIPTION:Reminder\n"
                        "TRIGGER;VALUE=DATE-TIME:%s\nUID:lcars-alarm-%d\n"
                        "X-WR-ALARMUID:lcars-alarm-%d\nEND:VALARM\n",
                        v, id, id);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// iCalendar serialization
// ---------------------------------------------------------------------------

// True when a stored extra line is one of the completion properties, which
// are only emitted while the task is actually done - the client owns their
// values, but done_bool owns whether they appear at all (a task completed in
// Reminders and reopened in the LCARS UI must not keep its COMPLETED line).
static bool caldav_is_completion_line(const char *line) {
  return caldav_line_is(line, "COMPLETED") ||
         caldav_line_is(line, "PERCENT-COMPLETE");
}

// Writes back stored iCalendar text exactly as it came in, one '\n'-separated
// line per content line.
static void caldav_write_verbatim_lines(IcsWriter *w, const char *text) {
  assert(w != NULL);
  for (const char *p = text ? text : ""; *p;) {
    const char *nl = strchr(p, '\n');
    size_t line_len = nl ? (size_t)(nl - p) : strlen(p);
    if (line_len > 0) {
      ics_write_len(w, p, line_len);
      ics_endline(w);
    }
    if (!nl) {
      break;
    }
    p = nl + 1;
  }
}

// Writes the kept lines - the properties this schema has no column for -
// in one of two passes: 0 the VTODO's own properties (skipping the
// completion ones while the task is open, and reporting which it emitted),
// 1 the components (VALARM). Properties must all come before the first
// component; this used to write the synthesized COMPLETED after a VALARM.
static void caldav_write_extra_lines(IcsWriter *w, const char *extra, bool done,
                                     int pass, bool *out_saw_completed,
                                     bool *out_saw_percent) {
  assert(w != NULL);
  assert(pass == 0 || pass == 1);
  assert(out_saw_completed != NULL && out_saw_percent != NULL);

  CalDAVLineIter it = {extra ? extra : "", 0};
  const char *line;
  size_t len;
  int depth;
  bool in_comp = false;
  while (caldav_next_line(&it, &line, &len, &depth)) {
    char head[64];
    caldav_line_head(line, len, head, sizeof(head));
    if (depth == 0 && caldav_line_is(head, "BEGIN")) {
      in_comp = true;
    }
    bool component_line = in_comp;
    if (depth == 0 && caldav_line_is(head, "END")) {
      in_comp = false;
    }
    if ((pass == 1) != component_line) {
      continue;
    }
    if (!component_line && caldav_is_completion_line(head)) {
      if (!done) {
        continue;
      }
      if (caldav_line_is(head, "COMPLETED")) {
        *out_saw_completed = true;
      } else {
        *out_saw_percent = true;
      }
    }
    ics_write_len(w, line, len);
    ics_endline(w);
  }
}

// Whether the kept lines carry a VTODO property of this name (not one
// inside a VALARM).
static bool caldav_has_prop(const char *extra, const char *name) {
  CalDAVLineIter it = {extra ? extra : "", 0};
  const char *line;
  size_t len;
  int depth;
  while (caldav_next_line(&it, &line, &len, &depth)) {
    char head[64];
    caldav_line_head(line, len, head, sizeof(head));
    if (depth == 0 && caldav_line_is(head, name)) {
      return true;
    }
  }
  return false;
}

// Builds the full iCalendar object for one task row (a statement positioned
// on a row selected with CALDAV_TASK_COLUMNS) into `out`, folded and CRLF
// terminated.
//
// DTSTAMP is the row's last_modified rather than "now" on purpose: two
// requests that see the same row must produce byte-identical text, because
// the ETag is a hash of exactly this output.
static void caldav_build_ics(sqlite3_stmt *stmt, JSONBuf *out) {
  assert(stmt != NULL);
  assert(out != NULL);

  int id = sqlite3_column_int(stmt, CALDAV_COL_ID);
  const char *title = (const char *)sqlite3_column_text(stmt, CALDAV_COL_TITLE);
  const char *content =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_CONTENT);
  bool done = sqlite3_column_int(stmt, CALDAV_COL_DONE) != 0;
  const char *created =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_CREATED);
  const char *modified =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_MODIFIED);
  const char *stored_uid =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_UID);
  const char *extra_vcal =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_EXTRA_VCAL);
  assert(id > 0);

  // The kept lines as they stand now, built first so they sit below the
  // object in the arena rather than inside it.
  JSONBuf extra;
  jsonbuf_init(&extra, out->arena);
  caldav_effective_extra(
      id, (const char *)sqlite3_column_text(stmt, CALDAV_COL_EXTRA),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_START),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_END),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_SYNC_START),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_SYNC_END), done,
      &extra);
  if (extra.overflow) {
    out->overflow = true;
    return;
  }
  const char *extra_text = extra.data ? extra.data : "";

  char uid[CALDAV_MAX_UID];
  caldav_uid(id, stored_uid, uid, sizeof(uid));
  char created_ical[24];
  char modified_ical[24];
  caldav_ts_to_ical(created, created_ical, sizeof(created_ical));
  caldav_ts_to_ical(modified, modified_ical, sizeof(modified_ical));

  IcsWriter w;
  ics_init(&w, out);

  ics_write_line(&w, "BEGIN", "VCALENDAR");
  ics_write_line(&w, "VERSION", "2.0");
  ics_write_line(&w, "PRODID", CALDAV_PRODID);
  ics_write_line(&w, "CALSCALE", "GREGORIAN");
  // Calendar-level components the client sent (VTIMEZONE), which the TZID
  // parameters inside the VTODO below may refer to.
  caldav_write_verbatim_lines(&w, extra_vcal);

  ics_write_line(&w, "BEGIN", "VTODO");
  ics_write(&w, "UID:");
  ics_write_text(&w, uid);
  ics_endline(&w);
  ics_write_line(&w, "DTSTAMP", modified_ical);
  ics_write_line(&w, "CREATED", created_ical);
  ics_write_line(&w, "LAST-MODIFIED", modified_ical);
  ics_write(&w, "SUMMARY:");
  ics_write_text(&w, (title && title[0] != '\0') ? title : "Untitled");
  ics_endline(&w);
  if (content && content[0] != '\0') {
    ics_write(&w, "DESCRIPTION:");
    ics_write_text(&w, content);
    ics_endline(&w);
  }
  ics_write_line(&w, "STATUS", done ? "COMPLETED" : "NEEDS-ACTION");

  bool saw_completed = false;
  bool saw_percent = false;
  caldav_write_extra_lines(&w, extra_text, done, 0, &saw_completed,
                           &saw_percent);
  if (done && !saw_completed) {
    ics_write_line(&w, "COMPLETED", modified_ical);
  }
  if (done && !saw_percent) {
    ics_write_line(&w, "PERCENT-COMPLETE", "100");
  }
  // The way back to the journal, unless the client set a URL of its own.
  if (g_caldav_ui_base[0] != '\0' && !caldav_has_prop(extra_text, "URL")) {
    char url[320];
    snprintf(url, sizeof(url), "%s#e=%d", g_caldav_ui_base, id);
    ics_write_line(&w, "URL;VALUE=URI", url);
  }
  caldav_write_extra_lines(&w, extra_text, done, 1, &saw_completed,
                           &saw_percent);
  ics_write_line(&w, "END", "VTODO");
  ics_write_line(&w, "END", "VCALENDAR");
}

// The ETag for a task: a hash of the exact bytes GET would return, so it
// changes when, and only when, the representation does. `scratch` is the
// per-item arena (never the one the response is being built in - this
// resets it).
static void caldav_etag_for(Arena *scratch, sqlite3_stmt *stmt, char *out,
                            size_t out_size) {
  assert(arena_valid(scratch));
  assert(stmt != NULL);
  assert(out != NULL);
  assert(out_size >= 32);

  arena_reset(scratch);
  JSONBuf ics;
  jsonbuf_init(&ics, scratch);
  caldav_build_ics(stmt, &ics);
  uint64_t hash =
      caldav_hash_bytes(CALDAV_HASH_SEED, ics.data ? ics.data : "", ics.len);
  // An ETag that hashed a truncated body would claim two different tasks
  // were the same; ics.overflow means the scratch arena was too small, and
  // the id keeps such a value at least unique per row.
  int n = snprintf(out, out_size, "\"%d-%016llx%s\"",
                   sqlite3_column_int(stmt, CALDAV_COL_ID),
                   (unsigned long long)hash, ics.overflow ? "-partial" : "");
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// A list's ctag and its newest stamp - the two halves of its sync-token.
// The ctag hashes every row's identity and mutation markers, deleted ones
// included, so any create, edit, completion, reschedule or delete moves it,
// plus the tasks that have left the list and the list's own name and
// colour. Clients poll this to decide whether to re-list at all.
//
// The kept lines are hashed whole, not just stamped: the web UI edits them
// (/entries/<id>/caldav) and stamps the row, but a stamp has one-second
// resolution, and a due date moved twice in that second must still move
// the ctag.
static void caldav_collection_state(sqlite3 *db, const CalDAVList *l,
                                    char *ctag, size_t ctag_size, char *mark,
                                    size_t mark_size) {
  assert(db != NULL && l != NULL);
  assert(ctag != NULL && ctag_size >= 24);
  assert(mark != NULL && mark_size >= 20);

  uint64_t hash = CALDAV_HASH_SEED;
  hash = caldav_hash_str(hash, l->name);
  hash = caldav_hash_str(hash, l->color);
  caldav_copy_str(mark, mark_size, "1970-01-01 00:00:00");
  sqlite3_stmt *stmt = NULL;
  const char *sql =
      "SELECT e.id, e.last_modified_at_utc, e.done_bool, e.deleted, "
      "length(e.title), length(e.content), e.start_date, e.end_date, "
      "c.extra_ical FROM entries e LEFT JOIN caldav_tasks c ON c.entry_id = "
      "e.id WHERE e.kind = ?1 ORDER BY e.id;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, l->kind, -1, SQLITE_TRANSIENT);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *lm = (const char *)sqlite3_column_text(stmt, 1);
      char row[192];
      int n = snprintf(row, sizeof(row), "%d|%s|%d|%d|%d|%d|%s|%s;",
                       sqlite3_column_int(stmt, 0), lm ? lm : "",
                       sqlite3_column_int(stmt, 2), sqlite3_column_int(stmt, 3),
                       sqlite3_column_int(stmt, 4), sqlite3_column_int(stmt, 5),
                       (const char *)sqlite3_column_text(stmt, 6)
                           ? (const char *)sqlite3_column_text(stmt, 6)
                           : "",
                       (const char *)sqlite3_column_text(stmt, 7)
                           ? (const char *)sqlite3_column_text(stmt, 7)
                           : "");
      if (n > 0) {
        hash = caldav_hash_bytes(
            hash, row, (size_t)n < sizeof(row) ? (size_t)n : sizeof(row) - 1);
      }
      const void *extra = sqlite3_column_blob(stmt, 8);
      int extra_len = sqlite3_column_bytes(stmt, 8);
      if (extra && extra_len > 0) {
        hash = caldav_hash_bytes(hash, extra, (size_t)extra_len);
      }
      if (lm && strcmp(lm, mark) > 0) {
        caldav_copy_str(mark, mark_size, lm);
      }
    }
    sqlite3_finalize(stmt);
  }
  if (sqlite3_prepare_v2(db,
                         "SELECT max(seq), max(at) FROM caldav_moves WHERE "
                         "old_kind = ?1;",
                         -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, l->kind, -1, SQLITE_TRANSIENT);
    if (sqlite3_step(stmt) == SQLITE_ROW &&
        sqlite3_column_type(stmt, 0) != SQLITE_NULL) {
      char moved[32];
      snprintf(moved, sizeof(moved), "moves:%lld",
               (long long)sqlite3_column_int64(stmt, 0));
      hash = caldav_hash_str(hash, moved);
      const char *at = (const char *)sqlite3_column_text(stmt, 1);
      if (at && strcmp(at, mark) > 0) {
        caldav_copy_str(mark, mark_size, at);
      }
    }
    sqlite3_finalize(stmt);
  }
  int n = snprintf(ctag, ctag_size, "%016llx", (unsigned long long)hash);
  assert(n > 0 && n < (int)ctag_size);
  (void)n;
}

static void caldav_sync_token(const char *ctag, const char *mark, char *out,
                              size_t out_size) {
  assert(ctag != NULL && mark != NULL && out != NULL);
  int y = 1970, mo = 1, d = 1, h = 0, mi = 0, s = 0;
  sscanf(mark, "%4d-%2d-%2d %2d:%2d:%2d", &y, &mo, &d, &h, &mi, &s);
  int n =
      snprintf(out, out_size, CALDAV_SYNC_PREFIX "%04d%02d%02d%02d%02d%02d-%s",
               y, mo, d, h, mi, s, ctag);
  assert(n > 0 && n < (int)out_size);
  (void)n;
}

// The other way: a token's stamp as "YYYY-MM-DD HH:MM:SS" and its ctag.
// False when it is not one of ours (RFC 6578: answer valid-sync-token).
static bool caldav_parse_sync_token(const char *token, char *mark,
                                    size_t mark_size, char *ctag,
                                    size_t ctag_size) {
  assert(token != NULL && mark != NULL && ctag != NULL);
  size_t plen = strlen(CALDAV_SYNC_PREFIX);
  if (strncmp(token, CALDAV_SYNC_PREFIX, plen) != 0) {
    return false;
  }
  int y, mo, d, h, mi, s;
  char tag[32];
  if (sscanf(token + plen, "%4d%2d%2d%2d%2d%2d-%31[0-9a-f]", &y, &mo, &d, &h,
             &mi, &s, tag) != 7) {
    return false;
  }
  snprintf(mark, mark_size, "%04d-%02d-%02d %02d:%02d:%02d", y, mo, d, h, mi,
           s);
  caldav_copy_str(ctag, ctag_size, tag);
  return true;
}

// ---------------------------------------------------------------------------
// iCalendar parsing (PUT)
// ---------------------------------------------------------------------------

typedef struct CalDAVParsedTask {
  bool has_vtodo;
  char uid[CALDAV_MAX_UID];
  const char *summary;     // never NULL; "" when the VTODO had none
  const char *description; // never NULL
  bool done;
  JSONBuf extra;      // VTODO property lines this schema has no column for
  JSONBuf extra_vcal; // whole calendar-level components (VTIMEZONE)
} CalDAVParsedTask;

// Parses the iCalendar object a client PUT.
//
// The four fields the entries table can hold (UID, SUMMARY, DESCRIPTION,
// completion) are pulled out; DTSTAMP/CREATED/LAST-MODIFIED are dropped
// because they are regenerated from the row's own timestamps. Everything
// else - DUE, DTSTART, PRIORITY, RRULE, CATEGORIES, RELATED-TO, VALARM
// blocks, X-APPLE-* - is copied verbatim so the next GET gives the client
// back what it sent (DTSTART/DUE are kept as well as read into the
// schedule, so their TZID and form survive). Only the first VTODO in the
// object is stored: a recurrence override (a second VTODO with
// RECURRENCE-ID) is dropped, which is the one thing this bridge cannot
// represent.
//
// Returns false only when the body contains no VTODO at all.
static bool caldav_parse_ics(Arena *arena, const char *body,
                             CalDAVParsedTask *out) {
  assert(arena_valid(arena));
  assert(body != NULL);
  assert(out != NULL);

  memset(out, 0, sizeof(*out));
  out->summary = "";
  out->description = "";
  jsonbuf_init(&out->extra, arena);
  jsonbuf_init(&out->extra_vcal, arena);

  size_t len = 0;
  char *text = caldav_unfold(arena, body, &len);

  bool in_vtodo = false;
  bool vtodo_done = false; // the first VTODO has already been consumed
  int nested = 0;          // component depth inside the VTODO (VALARM)
  int in_vtimezone = 0;
  int in_other = 0;
  bool saw_status = false;
  bool status_done = false;
  bool completion_hint = false;

  char *line = text;
  while (line < text + len) {
    char *nl = strchr(line, '\n');
    if (nl) {
      *nl = '\0';
    }
    // Trailing whitespace would end up inside stored property values.
    size_t line_len = strlen(line);
    while (line_len > 0 &&
           (line[line_len - 1] == '\r' || line[line_len - 1] == ' ')) {
      line[--line_len] = '\0';
    }

    if (line_len == 0) {
      // nothing to do
    } else if (in_vtodo) {
      if (nested > 0) {
        jsonbuf_append(&out->extra, line);
        jsonbuf_append_len(&out->extra, "\n", 1);
        if (strncasecmp(line, "BEGIN:", 6) == 0) {
          nested++;
        } else if (strncasecmp(line, "END:", 4) == 0) {
          nested--;
        }
      } else if (strncasecmp(line, "END:VTODO", 9) == 0) {
        in_vtodo = false;
        vtodo_done = true;
      } else if (strncasecmp(line, "BEGIN:", 6) == 0) {
        nested = 1;
        jsonbuf_append(&out->extra, line);
        jsonbuf_append_len(&out->extra, "\n", 1);
      } else if (caldav_line_is(line, "UID")) {
        caldav_copy_str(out->uid, sizeof(out->uid), caldav_line_value(line));
      } else if (caldav_line_is(line, "SUMMARY")) {
        out->summary =
            caldav_unescape_ical_text(arena, caldav_line_value(line));
      } else if (caldav_line_is(line, "DESCRIPTION")) {
        out->description =
            caldav_unescape_ical_text(arena, caldav_line_value(line));
      } else if (caldav_line_is(line, "STATUS")) {
        saw_status = true;
        status_done = strncasecmp(caldav_line_value(line), "COMPLETED", 9) == 0;
      } else if (caldav_line_is(line, "DTSTAMP") ||
                 caldav_line_is(line, "CREATED") ||
                 caldav_line_is(line, "LAST-MODIFIED")) {
        // Regenerated from the row's timestamps on the way out.
      } else {
        if (caldav_line_is(line, "COMPLETED") ||
            (caldav_line_is(line, "PERCENT-COMPLETE") &&
             atoi(caldav_line_value(line)) >= 100)) {
          completion_hint = true;
        }
        jsonbuf_append(&out->extra, line);
        jsonbuf_append_len(&out->extra, "\n", 1);
      }
    } else if (in_vtimezone > 0) {
      jsonbuf_append(&out->extra_vcal, line);
      jsonbuf_append_len(&out->extra_vcal, "\n", 1);
      if (strncasecmp(line, "BEGIN:", 6) == 0) {
        in_vtimezone++;
      } else if (strncasecmp(line, "END:", 4) == 0) {
        in_vtimezone--;
      }
    } else if (in_other > 0) {
      if (strncasecmp(line, "BEGIN:", 6) == 0) {
        in_other++;
      } else if (strncasecmp(line, "END:", 4) == 0) {
        in_other--;
      }
    } else if (strncasecmp(line, "BEGIN:VTODO", 11) == 0) {
      if (vtodo_done) {
        in_other = 1; // a recurrence override; not representable here
      } else {
        in_vtodo = true;
        out->has_vtodo = true;
      }
    } else if (strncasecmp(line, "BEGIN:VTIMEZONE", 15) == 0) {
      in_vtimezone = 1;
      jsonbuf_append(&out->extra_vcal, line);
      jsonbuf_append_len(&out->extra_vcal, "\n", 1);
    } else if (strncasecmp(line, "BEGIN:VCALENDAR", 15) == 0) {
      // The wrapper itself; its properties (VERSION/PRODID/CALSCALE) are
      // ours to write.
    } else if (strncasecmp(line, "BEGIN:", 6) == 0) {
      in_other = 1; // VEVENT, VJOURNAL, VFREEBUSY: not a task
    }

    if (!nl) {
      break;
    }
    line = nl + 1;
  }

  out->done = saw_status ? status_done : completion_hint;
  return out->has_vtodo;
}

// ---------------------------------------------------------------------------
// Minimal XML scanning (REPORT, PROPPATCH and MKCALENDAR bodies)
// ---------------------------------------------------------------------------

// The local part of an element name: "D:href" -> "href".
static const char *xml_local_name(const char *qname, size_t qname_len,
                                  size_t *out_len) {
  assert(qname != NULL);
  assert(out_len != NULL);
  const char *colon = (const char *)memchr(qname, ':', qname_len);
  if (colon) {
    *out_len = qname_len - (size_t)(colon + 1 - qname);
    return colon + 1;
  }
  *out_len = qname_len;
  return qname;
}

// Scans forward for the next start tag whose local name is `name`, ignoring
// namespace prefixes. Returns a pointer just past its '>' (NULL if there is
// none) and, when `out_self_closing` is given, whether the tag was empty.
// This is deliberately not an XML parser: the only bodies it sees are the
// requests of calendar clients, and all that is needed from them is which
// report was asked for, which hrefs it named and a few property values.
static const char *xml_find_start_tag(const char *xml, const char *name,
                                      bool *out_self_closing) {
  assert(xml != NULL);
  assert(name != NULL);
  size_t name_len = strlen(name);

  for (const char *p = strchr(xml, '<'); p != NULL; p = strchr(p + 1, '<')) {
    const char *q = p + 1;
    if (*q == '/' || *q == '?' || *q == '!') {
      continue;
    }
    const char *end = q;
    while (*end && *end != '>' && *end != ' ' && *end != '\t' && *end != '\r' &&
           *end != '\n' && *end != '/') {
      end++;
    }
    size_t local_len = 0;
    const char *local = xml_local_name(q, (size_t)(end - q), &local_len);
    if (local_len != name_len || strncasecmp(local, name, name_len) != 0) {
      continue;
    }
    const char *close = strchr(end, '>');
    if (!close) {
      return NULL;
    }
    if (out_self_closing) {
      *out_self_closing = (close > end && close[-1] == '/');
    }
    return close + 1;
  }
  return NULL;
}

static bool xml_has_element(const char *xml, const char *name) {
  return xml_find_start_tag(xml, name, NULL) != NULL;
}

// Given the first byte of an element's content (just past its start tag),
// returns where that content ends - the '<' of the matching end tag - by
// counting nested elements. NULL when the document ends first.
static const char *xml_content_end(const char *content) {
  assert(content != NULL);
  int depth = 1;
  for (const char *p = strchr(content, '<'); p != NULL;
       p = strchr(p + 1, '<')) {
    if (p[1] == '?' || p[1] == '!') {
      continue;
    }
    const char *close = strchr(p, '>');
    if (!close) {
      return NULL;
    }
    if (p[1] == '/') {
      if (--depth == 0) {
        return p;
      }
    } else if (close[-1] != '/') {
      depth++;
    }
    p = close;
  }
  return NULL;
}

// Iterates the child elements of [*cursor, end): each one's qualified name
// and the raw text of its content ("" for an empty element). Returns false
// when there are no more.
static bool xml_next_child(const char **cursor, const char *end, char *qname,
                           size_t qname_size, const char **text,
                           size_t *text_len) {
  assert(cursor != NULL && end != NULL && qname != NULL && qname_size > 0);
  assert(text != NULL && text_len != NULL);
  const char *p = *cursor;
  while (p && p < end) {
    p = memchr(p, '<', (size_t)(end - p));
    if (!p) {
      return false;
    }
    if (p[1] == '?' || p[1] == '!') {
      p++;
      continue;
    }
    if (p[1] == '/') {
      return false;
    }
    const char *n = p + 1;
    const char *n_end = n;
    while (n_end < end && *n_end != '>' && *n_end != ' ' && *n_end != '/' &&
           *n_end != '\t' && *n_end != '\r' && *n_end != '\n') {
      n_end++;
    }
    caldav_line_head(n, (size_t)(n_end - n), qname, qname_size);
    const char *close = memchr(n_end, '>', (size_t)(end - n_end));
    if (!close) {
      return false;
    }
    if (close[-1] == '/') {
      *text = close;
      *text_len = 0;
      *cursor = close + 1;
      return true;
    }
    const char *content = close + 1;
    const char *content_end = xml_content_end(content);
    if (!content_end || content_end > end) {
      return false;
    }
    *text = content;
    *text_len = (size_t)(content_end - content);
    const char *after = strchr(content_end, '>');
    *cursor = after ? after + 1 : end;
    return true;
  }
  return false;
}

// The content span of the first <set>/<remove> block's <prop>, in a
// PROPPATCH or MKCALENDAR body. False when there is none.
static bool xml_prop_block(const char *body, const char *section,
                           const char **start, const char **end) {
  assert(body != NULL && section != NULL && start != NULL && end != NULL);
  bool empty = false;
  const char *sec = xml_find_start_tag(body, section, &empty);
  if (!sec || empty) {
    return false;
  }
  const char *sec_end = xml_content_end(sec);
  const char *prop = xml_find_start_tag(sec, "prop", &empty);
  if (!prop || empty || (sec_end && prop > sec_end)) {
    return false;
  }
  const char *prop_end = xml_content_end(prop);
  if (!prop_end) {
    return false;
  }
  *start = prop;
  *end = prop_end;
  return true;
}

// The namespace URI an element's prefix is bound to, searched for anywhere
// in the body (Apple's clients declare it on the element itself). "" when
// it cannot be found.
static void xml_namespace_of(const char *body, const char *qname, char *out,
                             size_t out_size) {
  assert(body != NULL && qname != NULL && out != NULL && out_size > 0);
  out[0] = '\0';
  char needle[80];
  const char *colon = strchr(qname, ':');
  if (colon) {
    snprintf(needle, sizeof(needle), "xmlns:%.*s=\"", (int)(colon - qname),
             qname);
  } else {
    snprintf(needle, sizeof(needle), "xmlns=\"");
  }
  const char *p = strstr(body, needle);
  if (!p) {
    return;
  }
  p += strlen(needle);
  const char *q = strchr(p, '"');
  if (q) {
    caldav_line_head(p, (size_t)(q - p), out, out_size);
  }
}

// Decodes the five predefined XML entities into `out`.
static void xml_unescape(const char *src, size_t src_len, char *out,
                         size_t out_size) {
  assert(src != NULL || src_len == 0);
  assert(out != NULL);
  assert(out_size > 0);

  static const struct {
    const char *entity;
    char ch;
  } entities[] = {{"&amp;", '&'},
                  {"&lt;", '<'},
                  {"&gt;", '>'},
                  {"&quot;", '"'},
                  {"&apos;", '\''}};
  size_t o = 0;
  for (size_t i = 0; i < src_len && o < out_size - 1; i++) {
    if (src[i] == '&') {
      bool matched = false;
      for (size_t e = 0; e < sizeof(entities) / sizeof(entities[0]); e++) {
        size_t elen = strlen(entities[e].entity);
        if (src_len - i >= elen &&
            strncmp(src + i, entities[e].entity, elen) == 0) {
          out[o++] = entities[e].ch;
          i += elen - 1;
          matched = true;
          break;
        }
      }
      if (matched) {
        continue;
      }
    }
    out[o++] = src[i];
  }
  assert(o < out_size);
  out[o] = '\0';
}

// The text of an element, unescaped and trimmed.
static void xml_text(const char *text, size_t len, char *out, size_t out_size) {
  assert(out != NULL && out_size > 0);
  while (len > 0 &&
         (*text == ' ' || *text == '\n' || *text == '\r' || *text == '\t')) {
    text++;
    len--;
  }
  while (len > 0 && (text[len - 1] == ' ' || text[len - 1] == '\n' ||
                     text[len - 1] == '\r' || text[len - 1] == '\t')) {
    len--;
  }
  xml_unescape(text, len, out, out_size);
}

// Iterates the text content of every <href> element in `*cursor`, advancing
// it past each one. Returns false when there are no more.
static bool xml_next_href(const char **cursor, char *out, size_t out_size) {
  assert(cursor != NULL && *cursor != NULL);
  assert(out != NULL);
  assert(out_size > 0);

  bool self_closing = false;
  const char *content = xml_find_start_tag(*cursor, "href", &self_closing);
  if (!content) {
    return false;
  }
  if (self_closing) {
    *cursor = content;
    out[0] = '\0';
    return true;
  }
  const char *end = strchr(content, '<');
  if (!end) {
    end = content + strlen(content);
  }
  xml_text(content, (size_t)(end - content), out, out_size);
  *cursor = end;
  return true;
}

// ---------------------------------------------------------------------------
// WebDAV multistatus responses
// ---------------------------------------------------------------------------

static void dav_multistatus_begin(JSONBuf *b) {
  assert(b != NULL);
  jsonbuf_append(b, "<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n"
                    "<D:multistatus xmlns:D=\"DAV:\" "
                    "xmlns:C=\"urn:ietf:params:xml:ns:caldav\" "
                    "xmlns:CS=\"http://calendarserver.org/ns/\" "
                    "xmlns:A=\"http://apple.com/ns/ical/\">\r\n");
}

static void dav_multistatus_end(JSONBuf *b) {
  assert(b != NULL);
  jsonbuf_append(b, "</D:multistatus>\r\n");
}

// Opens a <D:response> and its one "these properties are present" propstat.
// Everything this server knows about a resource is reported as found; a
// property a client asked for and is not listed here is simply absent, which
// is how calendar clients read a missing prop anyway.
static void dav_response_begin(JSONBuf *b, const char *href) {
  assert(b != NULL);
  assert(href != NULL);
  jsonbuf_append(b, "<D:response><D:href>");
  caldav_append_xml(b, href);
  jsonbuf_append(b, "</D:href><D:propstat><D:prop>");
}

static void dav_response_end(JSONBuf *b) {
  assert(b != NULL);
  jsonbuf_append(b, "</D:prop><D:status>HTTP/1.1 200 OK</D:status>"
                    "</D:propstat></D:response>\r\n");
}

// The "you asked about this href and it is gone" response multiget and
// sync-collection need.
static void dav_response_not_found(JSONBuf *b, const char *href) {
  assert(b != NULL);
  assert(href != NULL);
  jsonbuf_append(b, "<D:response><D:href>");
  caldav_append_xml(b, href);
  jsonbuf_append(b, "</D:href><D:status>HTTP/1.1 404 Not Found</D:status>"
                    "</D:response>\r\n");
}

static void caldav_emit_root(JSONBuf *b, const char *href) {
  dav_response_begin(b, href);
  jsonbuf_append(b, "<D:resourcetype><D:collection/></D:resourcetype>"
                    "<D:displayname>LCARS</D:displayname>"
                    "<D:current-user-principal><D:href>" CALDAV_PRINCIPAL_PATH
                    "</D:href></D:current-user-principal>"
                    "<D:principal-URL><D:href>" CALDAV_PRINCIPAL_PATH
                    "</D:href></D:principal-URL>"
                    "<C:calendar-home-set><D:href>" CALDAV_HOME_PATH
                    "</D:href></C:calendar-home-set>");
  dav_response_end(b);
}

static void caldav_emit_principal(JSONBuf *b) {
  dav_response_begin(b, CALDAV_PRINCIPAL_PATH);
  jsonbuf_append(
      b, "<D:resourcetype><D:collection/><D:principal/></D:resourcetype>"
         "<D:displayname>LCARS</D:displayname>"
         "<D:current-user-principal><D:href>" CALDAV_PRINCIPAL_PATH
         "</D:href></D:current-user-principal>"
         "<D:principal-URL><D:href>" CALDAV_PRINCIPAL_PATH
         "</D:href></D:principal-URL>"
         "<C:calendar-home-set><D:href>" CALDAV_HOME_PATH
         "</D:href></C:calendar-home-set>"
         "<C:calendar-user-address-set><D:href>" CALDAV_PRINCIPAL_PATH
         "</D:href></C:calendar-user-address-set>");
  dav_response_end(b);
}

// The home. bind/unbind in its privileges are what tell a client it may
// create and delete lists here (MKCALENDAR, DELETE on a collection).
static void caldav_emit_home(JSONBuf *b) {
  dav_response_begin(b, CALDAV_HOME_PATH);
  jsonbuf_append(b,
                 "<D:resourcetype><D:collection/></D:resourcetype>"
                 "<D:displayname>LCARS</D:displayname>"
                 "<D:current-user-principal><D:href>" CALDAV_PRINCIPAL_PATH
                 "</D:href></D:current-user-principal>"
                 "<D:owner><D:href>" CALDAV_PRINCIPAL_PATH "</D:href></D:owner>"
                 "<D:current-user-privilege-set>"
                 "<D:privilege><D:read/></D:privilege>"
                 "<D:privilege><D:write/></D:privilege>"
                 "<D:privilege><D:bind/></D:privilege>"
                 "<D:privilege><D:unbind/></D:privilege>"
                 "</D:current-user-privilege-set>");
  dav_response_end(b);
}

// One list. supported-calendar-component-set is what tells Reminders this
// is a task list and Calendar to leave it alone; getctag and sync-token are
// what clients poll to decide whether to re-list, and sync-collection is
// how they then ask for only what changed.
static void caldav_emit_collection(JSONBuf *b, const CalDAVList *l,
                                   const char *ctag, const char *token) {
  assert(l != NULL && ctag != NULL && token != NULL);
  char href[CALDAV_MAX_NAME * 3 + 32];
  caldav_collection_href(l, href, sizeof(href));
  dav_response_begin(b, href);
  jsonbuf_append(b, "<D:resourcetype><D:collection/><C:calendar/>"
                    "</D:resourcetype><D:displayname>");
  caldav_append_xml(b, l->name);
  jsonbuf_append(
      b, "</D:displayname>"
         "<C:calendar-description>Tasks from the LCARS entries database"
         "</C:calendar-description>"
         "<C:supported-calendar-component-set>"
         "<C:comp name=\"VTODO\"/>"
         "</C:supported-calendar-component-set>"
         "<C:supported-calendar-data>"
         "<C:calendar-data content-type=\"text/calendar\" version=\"2.0\"/>"
         "</C:supported-calendar-data>"
         "<D:supported-report-set>"
         "<D:supported-report><D:report><C:calendar-query/></D:report>"
         "</D:supported-report>"
         "<D:supported-report><D:report><C:calendar-multiget/></D:report>"
         "</D:supported-report>"
         "<D:supported-report><D:report><D:sync-collection/></D:report>"
         "</D:supported-report>"
         "</D:supported-report-set>"
         "<D:current-user-privilege-set>"
         "<D:privilege><D:read/></D:privilege>"
         "<D:privilege><D:write/></D:privilege>"
         "<D:privilege><D:write-content/></D:privilege>"
         "<D:privilege><D:write-properties/></D:privilege>"
         "<D:privilege><D:bind/></D:privilege>"
         "<D:privilege><D:unbind/></D:privilege>"
         "</D:current-user-privilege-set>"
         "<D:current-user-principal><D:href>" CALDAV_PRINCIPAL_PATH
         "</D:href></D:current-user-principal>"
         "<D:owner><D:href>" CALDAV_PRINCIPAL_PATH "</D:href></D:owner>"
         "<A:calendar-color>");
  caldav_append_xml(b, l->color);
  jsonbuf_appendf(b,
                  "</A:calendar-color><A:calendar-order>%d"
                  "</A:calendar-order>",
                  l->order);
  jsonbuf_appendf(b, "<C:max-resource-size>%d</C:max-resource-size>",
                  CALDAV_MAX_RESOURCE_SIZE);
  jsonbuf_append(b, "<CS:getctag>");
  caldav_append_xml(b, ctag);
  jsonbuf_append(b, "</CS:getctag><D:sync-token>");
  caldav_append_xml(b, token);
  jsonbuf_append(b, "</D:sync-token>");
  dav_response_end(b);
}

static void caldav_emit_list(JSONBuf *b, sqlite3 *db, const CalDAVList *l) {
  char ctag[32], mark[20], token[96];
  caldav_collection_state(db, l, ctag, sizeof(ctag), mark, sizeof(mark));
  caldav_sync_token(ctag, mark, token, sizeof(token));
  caldav_emit_collection(b, l, ctag, token);
}

// One task. `ics`/`ics_len` are the calendar data to inline (REPORT) or NULL
// (PROPFIND, where CALDAV:calendar-data is not a live property).
static void caldav_emit_task(JSONBuf *b, const char *href, const char *etag,
                             const char *modified_sql, const char *ics,
                             size_t ics_len) {
  assert(href != NULL);
  assert(etag != NULL);

  dav_response_begin(b, href);
  jsonbuf_append(b, "<D:resourcetype/><D:getcontenttype>text/calendar; "
                    "charset=utf-8; component=vtodo</D:getcontenttype>"
                    "<D:getetag>");
  caldav_append_xml(b, etag);
  jsonbuf_append(b, "</D:getetag>");
  if (modified_sql) {
    char http_date[40];
    caldav_ts_to_http_date(modified_sql, http_date, sizeof(http_date));
    jsonbuf_append(b, "<D:getlastmodified>");
    caldav_append_xml(b, http_date);
    jsonbuf_append(b, "</D:getlastmodified>");
  }
  if (ics) {
    jsonbuf_appendf(b, "<D:getcontentlength>%zu</D:getcontentlength>", ics_len);
    jsonbuf_append(b, "<C:calendar-data>");
    caldav_append_xml(b, ics);
    jsonbuf_append(b, "</C:calendar-data>");
  }
  dav_response_end(b);
}

// Sends a built multistatus document, or a 507 if it outgrew the connection
// arena mid-build - half a multistatus must never go out looking whole.
static int caldav_send_multistatus(int client_fd, JSONBuf *b) {
  assert(client_fd >= 0);
  assert(b != NULL);

  if (b->overflow) {
    static const char body[] =
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n"
        "<D:error xmlns:D=\"DAV:\"><D:number-of-matches-within-limits/>"
        "</D:error>\r\n";
    printf("CalDAV Error: response outgrew the connection arena\n");
    return SendHTTPResponseEx(client_fd, 507, "application/xml; charset=utf-8",
                              CALDAV_DAV_HEADER, body, sizeof(body) - 1);
  }
  return SendHTTPResponseEx(client_fd, 207, "application/xml; charset=utf-8",
                            CALDAV_DAV_HEADER, b->data ? b->data : "", b->len);
}

// A bodiless status answer (204, 404, 412, ...), always carrying the DAV
// headers so a client that only ever sees an error still learns what this
// server is.
static int caldav_send_status(int client_fd, int status,
                              const char *extra_headers) {
  assert(client_fd >= 0);
  char headers[512];
  int n = snprintf(headers, sizeof(headers), "%s%s", CALDAV_DAV_HEADER,
                   extra_headers ? extra_headers : "");
  assert(n > 0 && n < (int)sizeof(headers));
  (void)n;
  return SendHTTPResponseEx(client_fd, status, "text/plain; charset=utf-8",
                            headers, "", 0);
}

// A precondition failure with its DAV:error body.
static int caldav_send_error(int client_fd, int status, const char *element) {
  assert(client_fd >= 0 && element != NULL);
  char body[512];
  int n = snprintf(body, sizeof(body),
                   "<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n"
                   "<D:error xmlns:D=\"DAV:\" "
                   "xmlns:C=\"urn:ietf:params:xml:ns:caldav\">%s</D:error>\r\n",
                   element);
  assert(n > 0 && n < (int)sizeof(body));
  return SendHTTPResponseEx(client_fd, status, "application/xml; charset=utf-8",
                            CALDAV_DAV_HEADER, body, (size_t)n);
}

// ---------------------------------------------------------------------------
// Request plumbing
// ---------------------------------------------------------------------------

// Matches `path` against `route`, tolerating one trailing slash either way.
static bool caldav_path_is(const char *path, const char *route) {
  assert(path != NULL);
  assert(route != NULL);

  size_t path_len = strlen(path);
  size_t route_len = strlen(route);
  if (path_len > 0 && path[path_len - 1] == '/') {
    path_len--;
  }
  if (route_len > 0 && route[route_len - 1] == '/') {
    route_len--;
  }
  return path_len == route_len && strncmp(path, route, path_len) == 0;
}

// Classifies a request path and percent-decodes the list segment (and, for
// a resource, its name) into the out buffers. A segment that does not fit
// is reported as NONE (404) rather than truncated into some other task's
// name. Whether the list exists is the handler's question.
static CalDAVPathKind caldav_classify(const char *path, char *out_segment,
                                      size_t segment_size, char *out_name,
                                      size_t name_size) {
  assert(path != NULL);
  assert(out_segment != NULL && segment_size > 1);
  assert(out_name != NULL && name_size > 1);

  out_segment[0] = '\0';
  out_name[0] = '\0';
  if (path[0] == '\0' || caldav_path_is(path, "/") ||
      caldav_path_is(path, "/caldav") ||
      caldav_path_is(path, CALDAV_WELL_KNOWN)) {
    return CALDAV_PATH_ROOT;
  }
  if (caldav_path_is(path, CALDAV_PRINCIPAL_PATH)) {
    return CALDAV_PATH_PRINCIPAL;
  }
  if (caldav_path_is(path, CALDAV_HOME_PATH)) {
    return CALDAV_PATH_HOME;
  }
  size_t prefix_len = strlen(CALDAV_HOME_PATH);
  if (strncmp(path, CALDAV_HOME_PATH, prefix_len) != 0) {
    return CALDAV_PATH_NONE;
  }
  const char *seg = path + prefix_len;
  const char *slash = strchr(seg, '/');
  size_t seg_len = slash ? (size_t)(slash - seg) : strlen(seg);
  if (seg_len == 0) {
    return CALDAV_PATH_NONE;
  }
  size_t decoded = url_decode(out_segment, segment_size, seg, seg_len);
  if (decoded == 0 || decoded >= segment_size - 1 ||
      strchr(out_segment, '/') != NULL) {
    out_segment[0] = '\0';
    return CALDAV_PATH_NONE;
  }
  const char *rest = slash ? slash + 1 : "";
  if (rest[0] == '\0') {
    return CALDAV_PATH_COLLECTION;
  }
  if (strchr(rest, '/') != NULL) {
    return CALDAV_PATH_NONE;
  }
  decoded = url_decode(out_name, name_size, rest, strlen(rest));
  if (decoded == 0 || decoded >= name_size - 1) {
    out_name[0] = '\0';
    return CALDAV_PATH_NONE;
  }
  return CALDAV_PATH_RESOURCE;
}

// The Depth header, defaulting to the RFC's "infinity" for PROPFIND. This
// server has no resource deeper than one level below a collection, so
// infinity and 1 are the same answer.
static int caldav_depth(const char *headers) {
  assert(headers != NULL);
  char value[32];
  if (!CopyHeaderValue(headers, "Depth:", value, sizeof(value))) {
    return 1;
  }
  if (strcasecmp(value, "0") == 0) {
    return 0;
  }
  return 1;
}

// Whether an If-Match / If-None-Match header value covers `etag`. Entity
// tags are compared as opaque strings, with a weak-comparison prefix
// ignored; "*" matches anything.
static bool caldav_etag_matches(const char *header_value, const char *etag) {
  assert(header_value != NULL);
  assert(etag != NULL);
  if (strcmp(header_value, "*") == 0) {
    return true;
  }
  const char *bare = etag;
  if (strncmp(bare, "W/", 2) == 0) {
    bare += 2;
  }
  return strstr(header_value, bare) != NULL;
}

// One task by id, live, in list `kind`.
static sqlite3_stmt *caldav_task_stmt_by_id(sqlite3 *db, int id,
                                            const char *kind) {
  assert(db != NULL);
  assert(id > 0 && kind != NULL);

  sqlite3_stmt *stmt = NULL;
  const char *sql = "SELECT " CALDAV_TASK_COLUMNS CALDAV_TASK_FROM
                    "WHERE e.id = ?1 AND e.kind = ?2 AND (e.deleted IS NULL "
                    "OR e.deleted = 0);";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: %s\n", sqlite3_errmsg(db));
    return NULL;
  }
  sqlite3_bind_int(stmt, 1, id);
  sqlite3_bind_text(stmt, 2, kind, -1, SQLITE_TRANSIENT);
  return stmt;
}

// Every live task of a list; `open_only` leaves out the completed ones.
static sqlite3_stmt *caldav_task_stmt_all(sqlite3 *db, const char *kind,
                                          bool open_only) {
  assert(db != NULL && kind != NULL);

  sqlite3_stmt *stmt = NULL;
  const char *sql =
      open_only ? "SELECT " CALDAV_TASK_COLUMNS CALDAV_TASK_FROM
                  "WHERE e.kind = ?1 AND (e.deleted IS NULL OR e.deleted = "
                  "0) AND (e.done_bool IS NULL OR e.done_bool = 0) ORDER BY "
                  "e.id;"
                : "SELECT " CALDAV_TASK_COLUMNS CALDAV_TASK_FROM
                  "WHERE e.kind = ?1 AND (e.deleted IS NULL OR e.deleted = "
                  "0) ORDER BY e.id;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: %s\n", sqlite3_errmsg(db));
    return NULL;
  }
  sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
  return stmt;
}

// Emits the <D:response> for the task the statement is positioned on.
// `scratch` holds the iCalendar text while it is hashed (and, when
// `with_data` is set, copied into the response), so a long listing costs one
// task's worth of scratch rather than the whole collection's.
static void caldav_emit_task_row(JSONBuf *b, Arena *scratch, sqlite3_stmt *stmt,
                                 const CalDAVList *l, bool with_data) {
  assert(b != NULL);
  assert(arena_valid(scratch));
  assert(stmt != NULL && l != NULL);

  int id = sqlite3_column_int(stmt, CALDAV_COL_ID);
  const char *stored_name =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_NAME);
  const char *modified =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_MODIFIED);
  char name[CALDAV_MAX_NAME];
  char href[CALDAV_MAX_NAME * 6 + 64];
  caldav_resource_name(id, stored_name, name, sizeof(name));
  caldav_task_href(l, name, href, sizeof(href));

  char etag[64];
  caldav_etag_for(scratch, stmt, etag, sizeof(etag));

  if (!with_data) {
    caldav_emit_task(b, href, etag, modified, NULL, 0);
    return;
  }
  // caldav_etag_for() reset the scratch arena; rebuild the text there now
  // that the hash is out.
  arena_reset(scratch);
  JSONBuf ics;
  jsonbuf_init(&ics, scratch);
  caldav_build_ics(stmt, &ics);
  if (ics.overflow) {
    b->overflow = true;
    return;
  }
  caldav_emit_task(b, href, etag, modified, ics.data ? ics.data : "", ics.len);
}

// ---------------------------------------------------------------------------
// Method handlers
// ---------------------------------------------------------------------------

static int caldav_handle_propfind(int client_fd, Arena *arena, Arena *scratch,
                                  sqlite3 *db, CalDAVPathKind kind,
                                  const char *path, const CalDAVList *list,
                                  const char *name, int depth) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(arena_valid(scratch));
  assert(db != NULL);
  assert(path != NULL && name != NULL);

  JSONBuf b;
  jsonbuf_init(&b, arena);
  dav_multistatus_begin(&b);

  switch (kind) {
  case CALDAV_PATH_ROOT:
    caldav_emit_root(&b, path);
    if (depth > 0) {
      caldav_emit_principal(&b);
      caldav_emit_home(&b);
    }
    break;
  case CALDAV_PATH_PRINCIPAL:
    caldav_emit_principal(&b);
    break;
  case CALDAV_PATH_HOME: {
    caldav_emit_home(&b);
    if (depth > 0) {
      CalDAVList lists[CALDAV_MAX_LISTS];
      int n = caldav_load_lists(db, lists, CALDAV_MAX_LISTS, false);
      for (int i = 0; i < n; i++) {
        caldav_emit_list(&b, db, &lists[i]);
      }
    }
    break;
  }
  case CALDAV_PATH_COLLECTION: {
    assert(list != NULL);
    caldav_emit_list(&b, db, list);
    if (depth > 0) {
      sqlite3_stmt *stmt = caldav_task_stmt_all(db, list->kind, false);
      if (!stmt) {
        return caldav_send_status(client_fd, 500, NULL);
      }
      while (sqlite3_step(stmt) == SQLITE_ROW) {
        caldav_emit_task_row(&b, scratch, stmt, list, false);
      }
      sqlite3_finalize(stmt);
    }
    break;
  }
  case CALDAV_PATH_RESOURCE: {
    assert(list != NULL);
    int id = caldav_lookup_entry_id(db, list->kind, name, false);
    if (id <= 0) {
      return caldav_send_status(client_fd, 404, NULL);
    }
    sqlite3_stmt *stmt = caldav_task_stmt_by_id(db, id, list->kind);
    if (!stmt) {
      return caldav_send_status(client_fd, 500, NULL);
    }
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      caldav_emit_task_row(&b, scratch, stmt, list, false);
    }
    sqlite3_finalize(stmt);
    break;
  }
  case CALDAV_PATH_NONE:
  default:
    // The router only dispatches known paths here.
    assert(!"unreachable");
    return caldav_send_status(client_fd, 404, NULL);
  }

  dav_multistatus_end(&b);
  return caldav_send_multistatus(client_fd, &b);
}

// The href of a task that has left a list, for a sync report's 404.
static void caldav_gone_href(const CalDAVList *l, int id, const char *name,
                             char *out, size_t out_size) {
  char resource[CALDAV_MAX_NAME];
  caldav_resource_name(id, name, resource, sizeof(resource));
  caldav_task_href(l, resource, out, out_size);
}

// REPORT sync-collection (RFC 6578): what changed in a list since a token.
//
// There is no change log, and none is needed. Every write path stamps
// last_modified_at_utc, deletes are soft, and a task that left the list is
// in caldav_moves - so "since T" is the list's rows stamped at or after T
// (inclusive, so a write in the same second as the last answer is never
// missed; a task reported twice costs one ETag compare), the deleted ones as
// 404s, plus a 404 for every task that moved out. The token's ctag half is
// the shortcut: if it still matches, nothing at all changed.
static int caldav_handle_sync(int client_fd, Arena *arena, Arena *scratch,
                              sqlite3 *db, const CalDAVList *l,
                              const char *body) {
  assert(l != NULL && body != NULL);

  char since[20] = "";
  char since_ctag[32] = "";
  bool empty = false;
  const char *tok = xml_find_start_tag(body, "sync-token", &empty);
  if (tok && !empty) {
    const char *tok_end = strchr(tok, '<');
    char token[160];
    xml_text(tok, tok_end ? (size_t)(tok_end - tok) : strlen(tok), token,
             sizeof(token));
    if (token[0] != '\0' &&
        !caldav_parse_sync_token(token, since, sizeof(since), since_ctag,
                                 sizeof(since_ctag))) {
      return caldav_send_error(client_fd, 403, "<D:valid-sync-token/>");
    }
  }
  bool want_data = xml_has_element(body, "calendar-data");

  char ctag[32], mark[20], token[96];
  caldav_collection_state(db, l, ctag, sizeof(ctag), mark, sizeof(mark));
  caldav_sync_token(ctag, mark, token, sizeof(token));

  JSONBuf b;
  jsonbuf_init(&b, arena);
  dav_multistatus_begin(&b);
  bool initial = since[0] == '\0';
  if (initial || strcmp(since_ctag, ctag) != 0) {
    sqlite3_stmt *stmt = NULL;
    if (initial) {
      stmt = caldav_task_stmt_all(db, l->kind, false);
    } else if (sqlite3_prepare_v2(db,
                                  "SELECT " CALDAV_TASK_COLUMNS CALDAV_TASK_FROM
                                  "WHERE e.kind = ?1 AND "
                                  "e.last_modified_at_utc >= ?2 ORDER BY e.id;",
                                  -1, &stmt, NULL) == SQLITE_OK) {
      sqlite3_bind_text(stmt, 1, l->kind, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 2, since, -1, SQLITE_TRANSIENT);
    }
    if (!stmt) {
      return caldav_send_status(client_fd, 500, NULL);
    }
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      if (sqlite3_column_int(stmt, CALDAV_COL_DELETED) != 0) {
        char href[CALDAV_MAX_NAME * 6 + 64];
        caldav_gone_href(
            l, sqlite3_column_int(stmt, CALDAV_COL_ID),
            (const char *)sqlite3_column_text(stmt, CALDAV_COL_NAME), href,
            sizeof(href));
        dav_response_not_found(&b, href);
      } else {
        caldav_emit_task_row(&b, scratch, stmt, l, want_data);
      }
    }
    sqlite3_finalize(stmt);

    if (!initial &&
        sqlite3_prepare_v2(
            db,
            "SELECT m.entry_id, m.old_name FROM caldav_moves m JOIN entries e "
            "ON e.id = m.entry_id WHERE m.old_kind = ?1 AND m.at >= ?2 AND "
            "e.kind IS NOT ?1 ORDER BY m.seq;",
            -1, &stmt, NULL) == SQLITE_OK) {
      sqlite3_bind_text(stmt, 1, l->kind, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 2, since, -1, SQLITE_TRANSIENT);
      while (sqlite3_step(stmt) == SQLITE_ROW) {
        char href[CALDAV_MAX_NAME * 6 + 64];
        caldav_gone_href(l, sqlite3_column_int(stmt, 0),
                         (const char *)sqlite3_column_text(stmt, 1), href,
                         sizeof(href));
        dav_response_not_found(&b, href);
      }
      sqlite3_finalize(stmt);
    }
  }
  jsonbuf_append(&b, "<D:sync-token>");
  caldav_append_xml(&b, token);
  jsonbuf_append(&b, "</D:sync-token>\r\n");
  dav_multistatus_end(&b);
  return caldav_send_multistatus(client_fd, &b);
}

// Whether a calendar-query's filter asks only for tasks not yet completed -
// the two ways clients say it: COMPLETED is-not-defined, or STATUS not
// matching COMPLETED. Every other filter is answered with the whole list,
// which clients then narrow themselves.
static bool caldav_query_open_only(const char *body) {
  assert(body != NULL);
  for (const char *p = xml_find_start_tag(body, "prop-filter", NULL); p;
       p = xml_find_start_tag(p, "prop-filter", NULL)) {
    // The tag's own text, back to its '<', holds the name attribute.
    const char *tag = p - 1; // p is past the '>', maybe on the next '<'
    while (tag > body && *tag != '<') {
      tag--;
    }
    char head[160];
    caldav_line_head(tag, (size_t)(p - tag), head, sizeof(head));
    const char *end = xml_content_end(p);
    size_t span = end ? (size_t)(end - p) : 0;
    char inner[512];
    caldav_line_head(p, span, inner, sizeof(inner));
    bool completed = strstr(head, "\"COMPLETED\"") != NULL;
    bool status = strstr(head, "\"STATUS\"") != NULL;
    if (completed && xml_has_element(inner, "is-not-defined")) {
      return true;
    }
    if (status && strstr(inner, "negate-condition=\"yes\"") &&
        strstr(inner, ">COMPLETED<")) {
      return true;
    }
  }
  return false;
}

// REPORT. Three reports are supported: calendar-multiget (the client names
// the hrefs it wants), calendar-query (the list, or its open tasks) and
// sync-collection (what changed since a token).
static int caldav_handle_report(int client_fd, Arena *arena, Arena *scratch,
                                sqlite3 *db, CalDAVPathKind kind,
                                const CalDAVList *list, const char *name,
                                const char *body) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(arena_valid(scratch));
  assert(db != NULL);
  assert(name != NULL && body != NULL);

  if (xml_has_element(body, "sync-collection")) {
    if (kind != CALDAV_PATH_COLLECTION || !list) {
      return caldav_send_error(client_fd, 403, "<D:supported-report/>");
    }
    return caldav_handle_sync(client_fd, arena, scratch, db, list, body);
  }

  bool want_data = xml_has_element(body, "calendar-data");
  bool multiget = xml_has_element(body, "calendar-multiget");

  JSONBuf b;
  jsonbuf_init(&b, arena);
  dav_multistatus_begin(&b);

  if (multiget) {
    const char *cursor = body;
    char href[CALDAV_MAX_NAME * 3 + 128];
    while (xml_next_href(&cursor, href, sizeof(href))) {
      // Each href names its own list; a multiget may cross them.
      char seg[CALDAV_MAX_NAME];
      char decoded[CALDAV_MAX_NAME];
      const char *path = strstr(href, CALDAV_HOME_PATH);
      CalDAVList l;
      if (!path ||
          caldav_classify(path, seg, sizeof(seg), decoded, sizeof(decoded)) !=
              CALDAV_PATH_RESOURCE ||
          !caldav_list_by_segment(db, seg, &l)) {
        if (href[0] != '\0' && href[strlen(href) - 1] != '/') {
          dav_response_not_found(&b, href);
        }
        continue;
      }
      int id = caldav_lookup_entry_id(db, l.kind, decoded, false);
      if (id <= 0) {
        dav_response_not_found(&b, href);
        continue;
      }
      sqlite3_stmt *stmt = caldav_task_stmt_by_id(db, id, l.kind);
      if (!stmt) {
        return caldav_send_status(client_fd, 500, NULL);
      }
      if (sqlite3_step(stmt) == SQLITE_ROW) {
        caldav_emit_task_row(&b, scratch, stmt, &l, want_data);
      } else {
        dav_response_not_found(&b, href);
      }
      sqlite3_finalize(stmt);
    }
  } else if (kind == CALDAV_PATH_RESOURCE) {
    assert(list != NULL);
    int id = caldav_lookup_entry_id(db, list->kind, name, false);
    if (id <= 0) {
      return caldav_send_status(client_fd, 404, NULL);
    }
    sqlite3_stmt *stmt = caldav_task_stmt_by_id(db, id, list->kind);
    if (!stmt) {
      return caldav_send_status(client_fd, 500, NULL);
    }
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      caldav_emit_task_row(&b, scratch, stmt, list, want_data);
    }
    sqlite3_finalize(stmt);
  } else if (kind == CALDAV_PATH_COLLECTION) {
    assert(list != NULL);
    sqlite3_stmt *stmt =
        caldav_task_stmt_all(db, list->kind, caldav_query_open_only(body));
    if (!stmt) {
      return caldav_send_status(client_fd, 500, NULL);
    }
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      caldav_emit_task_row(&b, scratch, stmt, list, want_data);
    }
    sqlite3_finalize(stmt);
  }

  dav_multistatus_end(&b);
  return caldav_send_multistatus(client_fd, &b);
}

static int caldav_handle_get(int client_fd, Arena *arena, Arena *scratch,
                             sqlite3 *db, const CalDAVList *list,
                             const char *name) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(arena_valid(scratch));
  assert(db != NULL && list != NULL);
  assert(name != NULL);

  int id = caldav_lookup_entry_id(db, list->kind, name, false);
  if (id <= 0) {
    return caldav_send_status(client_fd, 404, NULL);
  }
  sqlite3_stmt *stmt = caldav_task_stmt_by_id(db, id, list->kind);
  if (!stmt) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  if (sqlite3_step(stmt) != SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return caldav_send_status(client_fd, 404, NULL);
  }

  // The ETag is hashed in the scratch arena, not this one: caldav_etag_for()
  // resets whichever arena it is handed, and the body being sent lives here.
  char etag[64];
  caldav_etag_for(scratch, stmt, etag, sizeof(etag));
  JSONBuf ics;
  jsonbuf_init(&ics, arena);
  caldav_build_ics(stmt, &ics);
  sqlite3_finalize(stmt);

  if (ics.overflow) {
    return caldav_send_status(client_fd, 507, NULL);
  }
  char headers[256];
  int n = snprintf(headers, sizeof(headers), CALDAV_DAV_HEADER "ETag: %s\r\n",
                   etag);
  assert(n > 0 && n < (int)sizeof(headers));
  (void)n;
  return SendHTTPResponseEx(client_fd, 200, "text/calendar; charset=utf-8",
                            headers, ics.data ? ics.data : "", ics.len);
}

// Reads a task's synced schedule (what its lines said when last written).
static void caldav_read_sync(sqlite3 *db, int id, char *ss, char *se) {
  assert(db != NULL && ss != NULL && se != NULL);
  ss[0] = '\0';
  se[0] = '\0';
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT sync_start, sync_end FROM caldav_tasks WHERE "
                         "entry_id = ?1;",
                         -1, &stmt, NULL) != SQLITE_OK) {
    return;
  }
  sqlite3_bind_int(stmt, 1, id);
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    caldav_copy_str(ss, 20, (const char *)sqlite3_column_text(stmt, 0));
    caldav_copy_str(se, 20, (const char *)sqlite3_column_text(stmt, 1));
  }
  sqlite3_finalize(stmt);
}

// Writes a parsed VTODO to the database: an UPDATE when the task already
// exists (in this list, in another - a move - or soft-deleted, which this
// restores), an INSERT otherwise, plus the side row holding the resource
// name, the client's UID and every property the entries schema cannot
// express. The schedule columns are written only when the lines' dates
// moved since they were last written: a client that edited the title must
// not undo a reschedule made in the journal meanwhile. Both statements run
// in one transaction so a task can never end up with its extras missing.
static bool caldav_store_task(sqlite3 *db, const char *kind, const char *name,
                              const CalDAVParsedTask *task, int existing_id,
                              int *out_id) {
  assert(db != NULL);
  assert(kind != NULL && name != NULL);
  assert(task != NULL);
  assert(out_id != NULL);
  assert(existing_id >= 0);

  const char *title =
      (task->summary && task->summary[0] != '\0') ? task->summary : "Untitled";
  const char *description = task->description ? task->description : "";
  const char *extra = task->extra.data ? task->extra.data : "";
  // A TZID on the task's own dates is where the user is now; learn it
  // before the dates are read, so an all-day one beside it agrees.
  char tzid[64];
  caldav_lines_zone(extra, tzid, sizeof(tzid));
  if (strcmp(tzid, caldav_default_zone()) != 0) {
    caldav_remember_zone(db, tzid);
  }
  char s[20], e[20];
  caldav_derive_schedule(extra, s, e);

  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: cannot begin transaction: %s\n",
           sqlite3_errmsg(db));
    return false;
  }

  int id = existing_id;
  sqlite3_stmt *stmt = NULL;
  bool ok = true;
  if (existing_id > 0) {
    char ss[20], se[20];
    caldav_read_sync(db, existing_id, ss, se);
    bool reschedule = strcmp(s, ss) != 0 || strcmp(e, se) != 0;
    const char *sql =
        "UPDATE entries SET kind = ?5, title = ?1, content = ?2, done_bool = "
        "?3, deleted = 0, start_date = CASE WHEN ?6 THEN ?7 ELSE start_date "
        "END, end_date = CASE WHEN ?6 THEN ?8 ELSE end_date END, "
        "last_modified_at_utc = strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') "
        "WHERE id = ?4;";
    ok = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK;
    if (ok) {
      sqlite3_bind_text(stmt, 1, title, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 2, description, -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(stmt, 3, task->done ? 1 : 0);
      sqlite3_bind_int(stmt, 4, existing_id);
      sqlite3_bind_text(stmt, 5, kind, -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(stmt, 6, reschedule ? 1 : 0);
      sqlite3_bind_text(stmt, 7, s, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 8, e, -1, SQLITE_TRANSIENT);
      ok = sqlite3_step(stmt) == SQLITE_DONE;
    }
  } else {
    const char *sql = "INSERT INTO entries (kind, title, content, done_bool, "
                      "start_date, end_date) VALUES (?1, ?2, ?3, ?4, ?5, ?6);";
    ok = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK;
    if (ok) {
      sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 3, description, -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(stmt, 4, task->done ? 1 : 0);
      sqlite3_bind_text(stmt, 5, s, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 6, e, -1, SQLITE_TRANSIENT);
      ok = sqlite3_step(stmt) == SQLITE_DONE;
      if (ok) {
        sqlite3_int64 rowid = sqlite3_last_insert_rowid(db);
        assert(rowid > 0 && rowid <= INT_MAX);
        id = (int)rowid;
      }
    }
  }
  if (!ok) {
    printf("CalDAV Database Error: entry write failed: %s\n",
           sqlite3_errmsg(db));
  }
  sqlite3_finalize(stmt);
  stmt = NULL;

  if (ok) {
    char uid[CALDAV_MAX_UID];
    caldav_uid(id, task->uid[0] != '\0' ? task->uid : NULL, uid, sizeof(uid));
    const char *sql =
        "INSERT OR REPLACE INTO caldav_tasks (entry_id, resource_name, uid, "
        "extra_ical, extra_vcal, sync_start, sync_end) VALUES (?1, ?2, ?3, "
        "?4, ?5, ?6, ?7);";
    ok = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK;
    if (ok) {
      sqlite3_bind_int(stmt, 1, id);
      sqlite3_bind_text(stmt, 2, name, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 3, uid, -1, SQLITE_TRANSIENT);
      // Borrowed, not copied: the extras are arena text that outlives the
      // step below.
      sqlite3_bind_text(stmt, 4, extra, (int)task->extra.len, SQLITE_STATIC);
      sqlite3_bind_text(stmt, 5,
                        task->extra_vcal.data ? task->extra_vcal.data : "",
                        (int)task->extra_vcal.len, SQLITE_STATIC);
      sqlite3_bind_text(stmt, 6, s, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 7, e, -1, SQLITE_TRANSIENT);
      ok = sqlite3_step(stmt) == SQLITE_DONE;
    }
    if (!ok) {
      printf("CalDAV Database Error: side-table write failed: %s\n",
             sqlite3_errmsg(db));
    }
    sqlite3_finalize(stmt);
  }

  if (!ok) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return false;
  }
  if (sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: commit failed: %s\n", sqlite3_errmsg(db));
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return false;
  }
  assert(id > 0);
  *out_id = id;
  return true;
}

// The ETag of a task as it now stands, for an If-Match check.
static bool caldav_current_etag(sqlite3 *db, Arena *scratch, int id,
                                const char *kind, char *out, size_t out_size) {
  sqlite3_stmt *stmt = caldav_task_stmt_by_id(db, id, kind);
  bool found = false;
  if (stmt && sqlite3_step(stmt) == SQLITE_ROW) {
    caldav_etag_for(scratch, stmt, out, out_size);
    found = true;
  }
  if (stmt) {
    sqlite3_finalize(stmt);
  }
  return found;
}

// PUT. The answer carries no ETag: RFC 4791 5.3.4 forbids one when the
// stored object differs from what was sent, and this server always
// rewrites DTSTAMP, PRODID and the property order - so the client fetches
// the task back, which is one small GET per edit.
static int caldav_handle_put(int client_fd, Arena *arena, Arena *scratch,
                             sqlite3 *db, const CalDAVList *list,
                             const char *name, const char *headers,
                             const char *body) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(arena_valid(scratch));
  assert(db != NULL && list != NULL);
  assert(name != NULL && headers != NULL && body != NULL);

  if (strlen(name) >= CALDAV_MAX_NAME) {
    return caldav_send_status(client_fd, 414, NULL);
  }

  CalDAVParsedTask task;
  if (!caldav_parse_ics(arena, body, &task)) {
    // Only VTODO belongs in this collection, and the collection says so in
    // supported-calendar-component-set; name the precondition it broke.
    printf("CalDAV Rejected: PUT %s carried no VTODO\n", name);
    return caldav_send_error(client_fd, 403,
                             "<C:supported-calendar-component/>");
  }
  if (task.extra.overflow || task.extra_vcal.overflow) {
    return caldav_send_status(client_fd, 413, NULL);
  }

  // include_deleted: a client that deletes and re-creates the same UID must
  // land back on the same row rather than leave a tombstone in the way of
  // its own resource name.
  int existing_id = caldav_lookup_entry_id(db, list->kind, name, true);
  bool exists_live = existing_id > 0 &&
                     caldav_lookup_entry_id(db, list->kind, name, false) > 0;
  if (existing_id == 0) {
    // Not here: perhaps a task moving in from another list.
    existing_id = caldav_find_elsewhere(db, name, task.uid);
  }
  // "lcars-<id>.ics" is the name reserved for tasks created in the UI, which
  // have no side row to look up. Letting a client claim one that does not
  // resolve to that task would publish two resources at the same href.
  int generated_for = caldav_id_from_generated_name(name);
  if (generated_for > 0 && existing_id != generated_for) {
    printf("CalDAV Rejected: PUT %s claims a reserved resource name\n", name);
    return caldav_send_status(client_fd, 409, NULL);
  }

  char if_none_match[256];
  if (CopyHeaderValue(headers, "If-None-Match:", if_none_match,
                      sizeof(if_none_match)) &&
      strcmp(if_none_match, "*") == 0 && exists_live) {
    return caldav_send_status(client_fd, 412, NULL);
  }

  char if_match[256];
  if (CopyHeaderValue(headers, "If-Match:", if_match, sizeof(if_match)) &&
      if_match[0] != '\0') {
    char etag[64];
    if (!exists_live ||
        !caldav_current_etag(db, scratch, existing_id, list->kind, etag,
                             sizeof(etag)) ||
        !caldav_etag_matches(if_match, etag)) {
      return caldav_send_status(client_fd, 412, NULL);
    }
  }

  int id = 0;
  if (!caldav_store_task(db, list->kind, name, &task, existing_id, &id)) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  return caldav_send_status(client_fd, exists_live ? 204 : 201, NULL);
}

// DELETE of a task is the same soft delete the UI and the JSON API do: the
// row keeps its content and its side row, so the task can come back (and so
// a sync mistake in Reminders cannot destroy anything).
static int caldav_handle_delete(int client_fd, Arena *scratch, sqlite3 *db,
                                const CalDAVList *list, const char *name,
                                const char *headers) {
  assert(client_fd >= 0);
  assert(arena_valid(scratch));
  assert(db != NULL && list != NULL);
  assert(name != NULL && headers != NULL);

  int id = caldav_lookup_entry_id(db, list->kind, name, false);
  if (id <= 0) {
    return caldav_send_status(client_fd, 404, NULL);
  }

  char if_match[256];
  if (CopyHeaderValue(headers, "If-Match:", if_match, sizeof(if_match)) &&
      if_match[0] != '\0') {
    char etag[64];
    if (!caldav_current_etag(db, scratch, id, list->kind, etag, sizeof(etag)) ||
        !caldav_etag_matches(if_match, etag)) {
      return caldav_send_status(client_fd, 412, NULL);
    }
  }

  sqlite3_stmt *stmt = NULL;
  const char *sql = "UPDATE entries SET deleted = 1, last_modified_at_utc = "
                    "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = "
                    "?1;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: %s\n", sqlite3_errmsg(db));
    return caldav_send_status(client_fd, 500, NULL);
  }
  sqlite3_bind_int(stmt, 1, id);
  bool ok = sqlite3_step(stmt) == SQLITE_DONE;
  sqlite3_finalize(stmt);
  if (!ok) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  return caldav_send_status(client_fd, 204, NULL);
}

// MOVE of a task to another list (or another name): the row is re-kinded
// and keeps everything else. Clients mostly move by PUT and DELETE, which
// caldav_handle_put() turns into the same thing; this is for those that
// say MOVE.
static int caldav_handle_move(int client_fd, sqlite3 *db,
                              const CalDAVList *list, const char *name,
                              const char *headers) {
  assert(db != NULL && list != NULL && name != NULL && headers != NULL);
  int id = caldav_lookup_entry_id(db, list->kind, name, false);
  if (id <= 0) {
    return caldav_send_status(client_fd, 404, NULL);
  }
  char dest[512];
  if (!CopyHeaderValue(headers, "Destination:", dest, sizeof(dest))) {
    return caldav_send_status(client_fd, 400, NULL);
  }
  const char *path = strstr(dest, CALDAV_HOME_PATH);
  char seg[CALDAV_MAX_NAME], dest_name[CALDAV_MAX_NAME];
  CalDAVList to;
  if (!path ||
      caldav_classify(path, seg, sizeof(seg), dest_name, sizeof(dest_name)) !=
          CALDAV_PATH_RESOURCE ||
      !caldav_list_by_segment(db, seg, &to)) {
    return caldav_send_status(client_fd, 409, NULL);
  }
  int clash = caldav_lookup_entry_id(db, to.kind, dest_name, false);
  if (clash > 0 && clash != id) {
    char overwrite[8];
    if (CopyHeaderValue(headers, "Overwrite:", overwrite, sizeof(overwrite)) &&
        (overwrite[0] == 'F' || overwrite[0] == 'f')) {
      return caldav_send_status(client_fd, 412, NULL);
    }
    // Overwriting another task would destroy it; this server never does.
    return caldav_send_status(client_fd, 409, NULL);
  }
  if (caldav_id_from_generated_name(dest_name) > 0 &&
      caldav_id_from_generated_name(dest_name) != id) {
    return caldav_send_status(client_fd, 409, NULL);
  }
  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  bool ok = true;
  sqlite3_stmt *stmt = NULL;
  ok = sqlite3_prepare_v2(
           db,
           "UPDATE entries SET kind = ?2, last_modified_at_utc = "
           "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?1;",
           -1, &stmt, NULL) == SQLITE_OK;
  if (ok) {
    sqlite3_bind_int(stmt, 1, id);
    sqlite3_bind_text(stmt, 2, to.kind, -1, SQLITE_TRANSIENT);
    ok = sqlite3_step(stmt) == SQLITE_DONE;
  }
  sqlite3_finalize(stmt);
  stmt = NULL;
  if (ok) {
    char uid[CALDAV_MAX_UID];
    caldav_uid(id, NULL, uid, sizeof(uid));
    ok = sqlite3_prepare_v2(
             db,
             "INSERT INTO caldav_tasks (entry_id, resource_name, uid, "
             "extra_ical, extra_vcal) VALUES (?1, ?2, ?3, '', '') ON "
             "CONFLICT(entry_id) DO UPDATE SET resource_name = "
             "excluded.resource_name;",
             -1, &stmt, NULL) == SQLITE_OK;
    if (ok) {
      sqlite3_bind_int(stmt, 1, id);
      sqlite3_bind_text(stmt, 2, dest_name, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 3, uid, -1, SQLITE_TRANSIENT);
      ok = sqlite3_step(stmt) == SQLITE_DONE;
    }
    sqlite3_finalize(stmt);
  }
  if (!ok || sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    printf("CalDAV Database Error: move failed: %s\n", sqlite3_errmsg(db));
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return caldav_send_status(client_fd, 500, NULL);
  }
  return caldav_send_status(client_fd, clash > 0 ? 204 : 201, NULL);
}

// A list's display name, colour or order from a client's property value.
// Returns true when the property is one a list keeps.
static bool caldav_apply_list_prop(CalDAVList *l, const char *local,
                                   const char *value, bool remove) {
  CalDAVList defaults;
  caldav_list_defaults(l->kind, &defaults);
  if (strcmp(local, "displayname") == 0) {
    caldav_copy_str(l->name, sizeof(l->name),
                    remove || value[0] == '\0' ? defaults.name : value);
    return true;
  }
  if (strcmp(local, "calendar-color") == 0) {
    bool ok = !remove && value[0] == '#' && strlen(value) < sizeof(l->color);
    caldav_copy_str(l->color, sizeof(l->color), ok ? value : defaults.color);
    return true;
  }
  if (strcmp(local, "calendar-order") == 0) {
    if (!remove) {
      l->order = atoi(value);
    }
    return true;
  }
  return false;
}

// PROPPATCH on a list: its name, colour and order are stored (in
// caldav_lists, never by renaming the kind - a kind is the journal's
// identity for these tasks, the name only how a client shows them). Any
// other property is refused, per property, with 403: answering 200 to a
// write that went nowhere would show a change that reverts on the next
// sync.
static int caldav_handle_proppatch(int client_fd, Arena *arena, sqlite3 *db,
                                   const CalDAVList *list, const char *body) {
  assert(db != NULL && list != NULL && body != NULL);
  CalDAVList l = *list;

  JSONBuf ok_props, bad_props;
  jsonbuf_init(&ok_props, arena);
  jsonbuf_init(&bad_props, arena);
  static const char *sections[] = {"set", "remove"};
  for (int s = 0; s < 2; s++) {
    const char *start, *end;
    if (!xml_prop_block(body, sections[s], &start, &end)) {
      continue;
    }
    const char *cursor = start;
    char qname[96];
    const char *text;
    size_t text_len;
    while (
        xml_next_child(&cursor, end, qname, sizeof(qname), &text, &text_len)) {
      size_t local_len;
      const char *local = xml_local_name(qname, strlen(qname), &local_len);
      char value[256];
      xml_text(text, text_len, value, sizeof(value));
      char ns[160];
      xml_namespace_of(body, qname, ns, sizeof(ns));
      JSONBuf *into = caldav_apply_list_prop(&l, local, value, s == 1)
                          ? &ok_props
                          : &bad_props;
      jsonbuf_append(into, "<X:");
      caldav_append_xml(into, local);
      jsonbuf_append(into, " xmlns:X=\"");
      caldav_append_xml(into, ns);
      jsonbuf_append(into, "\"/>");
    }
  }
  if (ok_props.len > 0 && !caldav_list_save(db, &l)) {
    return caldav_send_status(client_fd, 500, NULL);
  }

  JSONBuf b;
  jsonbuf_init(&b, arena);
  char href[CALDAV_MAX_NAME * 3 + 32];
  caldav_collection_href(&l, href, sizeof(href));
  jsonbuf_append(&b, "<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n"
                     "<D:multistatus xmlns:D=\"DAV:\"><D:response><D:href>");
  caldav_append_xml(&b, href);
  jsonbuf_append(&b, "</D:href>");
  if (ok_props.len > 0) {
    jsonbuf_append(&b, "<D:propstat><D:prop>");
    jsonbuf_append_len(&b, ok_props.data, ok_props.len);
    jsonbuf_append(&b, "</D:prop><D:status>HTTP/1.1 200 OK</D:status>"
                       "</D:propstat>");
  }
  if (bad_props.len > 0) {
    jsonbuf_append(&b, "<D:propstat><D:prop>");
    jsonbuf_append_len(&b, bad_props.data, bad_props.len);
    jsonbuf_append(&b, "</D:prop><D:status>HTTP/1.1 403 Forbidden</D:status>"
                       "</D:propstat>");
  }
  jsonbuf_append(&b, "</D:response></D:multistatus>\r\n");
  return caldav_send_multistatus(client_fd, &b);
}

// "Groceries" -> "groceries", "Work / Q4" -> "work_q4": the part of a new
// list's kind that comes after "task_".
static void caldav_slug(const char *name, char *out, size_t out_size) {
  assert(name != NULL && out != NULL && out_size > 1);
  size_t o = 0;
  bool gap = false;
  for (const unsigned char *p = (const unsigned char *)name;
       *p && o < out_size - 1; p++) {
    char c = (char)*p;
    if (c >= 'A' && c <= 'Z') {
      c = (char)(c - 'A' + 'a');
    }
    bool word = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    if (!word) {
      // A run of anything else is one underscore; UTF-8 letters (ă, ñ) are
      // anything else too, which keeps kinds plain ASCII.
      gap = o > 0;
      continue;
    }
    if (gap && o < out_size - 2) {
      out[o++] = '_';
    }
    gap = false;
    out[o++] = c;
  }
  out[o] = '\0';
  if (o == 0) {
    caldav_copy_str(out, out_size, "list");
  }
}

// MKCALENDAR: a list made in a client becomes a kind, "<task kind>_<slug of
// its name>", at the URL the client chose. A kind of that name that is
// already a list gets a number after it; one that was hidden (its list
// deleted in a client) is brought back instead, which is how a list
// deleted by mistake returns with its tasks.
static int caldav_handle_mkcalendar(int client_fd, sqlite3 *db,
                                    const char *segment, const char *body) {
  assert(db != NULL && segment != NULL && body != NULL);
  CalDAVList existing;
  if (caldav_list_by_segment(db, segment, &existing)) {
    return caldav_send_error(client_fd, 405, "<D:resource-must-be-null/>");
  }
  if (strlen(segment) >= CALDAV_MAX_NAME - 1) {
    return caldav_send_status(client_fd, 414, NULL);
  }

  char name[128] = "";
  char color[16] = "";
  int order = -1;
  bool comp_set = false, wants_todo = false;
  const char *start, *end;
  if (xml_prop_block(body, "set", &start, &end)) {
    const char *cursor = start;
    char qname[96];
    const char *text;
    size_t text_len;
    while (
        xml_next_child(&cursor, end, qname, sizeof(qname), &text, &text_len)) {
      size_t local_len;
      const char *local = xml_local_name(qname, strlen(qname), &local_len);
      char value[256];
      if (strcmp(local, "supported-calendar-component-set") == 0) {
        comp_set = true;
        char comps[512];
        caldav_line_head(text, text_len, comps, sizeof(comps));
        wants_todo = strstr(comps, "\"VTODO\"") != NULL;
        continue;
      }
      xml_text(text, text_len, value, sizeof(value));
      if (strcmp(local, "displayname") == 0) {
        caldav_copy_str(name, sizeof(name), value);
      } else if (strcmp(local, "calendar-color") == 0 && value[0] == '#') {
        caldav_copy_str(color, sizeof(color), value);
      } else if (strcmp(local, "calendar-order") == 0) {
        order = atoi(value);
      }
    }
  }
  if (comp_set && !wants_todo) {
    // A calendar of events: this server has nowhere to put them.
    return caldav_send_error(client_fd, 403,
                             "<C:supported-calendar-component/>");
  }

  char slug[48];
  caldav_slug(name[0] != '\0' ? name : "list", slug, sizeof(slug));
  CalDAVList lists[CALDAV_MAX_LISTS];
  int n = caldav_load_lists(db, lists, CALDAV_MAX_LISTS, true);
  char kind[CALDAV_MAX_KIND];
  CalDAVList l;
  bool revived = false;
  for (int attempt = 1; attempt < 100; attempt++) {
    if (attempt == 1) {
      snprintf(kind, sizeof(kind), "%.64s_%.47s", caldav_task_kind(), slug);
    } else {
      snprintf(kind, sizeof(kind), "%.64s_%.47s_%d", caldav_task_kind(), slug,
               attempt);
    }
    int found = -1;
    for (int i = 0; i < n; i++) {
      if (strcmp(lists[i].kind, kind) == 0) {
        found = i;
      }
    }
    if (found < 0) {
      caldav_list_defaults(kind, &l);
      l.order = n + 1;
      break;
    }
    if (lists[found].hidden) {
      l = lists[found];
      revived = true;
      break;
    }
    kind[0] = '\0';
  }
  if (kind[0] == '\0') {
    return caldav_send_status(client_fd, 409, NULL);
  }
  caldav_copy_str(l.segment, sizeof(l.segment), segment);
  if (name[0] != '\0') {
    caldav_copy_str(l.name, sizeof(l.name), name);
  }
  if (color[0] != '\0') {
    caldav_copy_str(l.color, sizeof(l.color), color);
  }
  if (order >= 0) {
    l.order = order;
  }
  l.hidden = false;
  if (!caldav_list_save(db, &l)) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  printf("CalDAV: list '%s' is kind '%s'%s\n", l.name, l.kind,
         revived ? " (brought back)" : "");
  return caldav_send_status(client_fd, 201, NULL);
}

// DELETE of a list hides it: the collection is gone for every client, and
// every entry in it stays exactly as it is in the journal. A MKCALENDAR of
// the same name brings it back.
static int caldav_handle_delete_list(int client_fd, sqlite3 *db,
                                     const CalDAVList *list) {
  assert(db != NULL && list != NULL);
  CalDAVList l = *list;
  l.hidden = true;
  if (!caldav_list_save(db, &l)) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  printf("CalDAV: list '%s' (kind '%s') hidden by a client\n", l.name, l.kind);
  return caldav_send_status(client_fd, 204, NULL);
}

// ---------------------------------------------------------------------------
// The JSON view of one task (/entries/<id>/caldav)
// ---------------------------------------------------------------------------

static bool MatchEntryCalDAVPath(const char *path, int *out_id) {
  assert(path != NULL);
  assert(out_id != NULL);

  const char *prefix = "/entries/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *digits = path + prefix_len;
  char *end = NULL;
  long value = strtol(digits, &end, 10);
  if (end == digits || value <= 0 || value > INT_MAX) {
    return false;
  }
  if (strcmp(end, "/caldav") != 0 && strcmp(end, "/caldav/") != 0) {
    return false;
  }
  *out_id = (int)value;
  return true;
}

// The properties the entries columns own. caldav_build_ics() writes them
// from the row, so a kept copy would go out twice - and the second SUMMARY
// would be a title the journal does not have.
static const char *const g_caldav_owned_props[] = {
    "UID",     "SUMMARY",       "DESCRIPTION", "STATUS",
    "DTSTAMP", "LAST-MODIFIED", "CREATED",
};

// Checks text the page wants kept as the task's extra lines and writes the
// normalized form (unfolded, '\n'-separated, blank lines dropped) to `out`.
// This is HTTP input, so every way it can be wrong is an answer, not an
// assert: `err` names the line. What it guards is the shape
// caldav_build_ics() splices verbatim into the VTODO - a stray END:VTODO
// would end the task early, and an unbalanced BEGIN:VALARM would swallow it.
static bool caldav_check_extra(Arena *arena, const char *text, JSONBuf *out,
                               char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(text != NULL);
  assert(out != NULL);
  assert(err != NULL && err_size > 0);

  size_t len = 0;
  char *unfolded = caldav_unfold(arena, text, &len);
  char stack[8][32]; // component names open inside the VTODO (VALARM)
  int depth = 0;
  int line_no = 0;

  char *line = unfolded;
  while (line < unfolded + len) {
    char *nl = strchr(line, '\n');
    if (nl) {
      *nl = '\0';
    }
    line_no++;
    size_t line_len = strlen(line);
    while (line_len > 0 && (line[line_len - 1] == ' ')) {
      line[--line_len] = '\0';
    }

    if (line_len > 0) {
      // NAME [;param]* : value, the name letters, digits and dashes.
      size_t name_len = strspn(line, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                                     "abcdefghijklmnopqrstuvwxyz0123456789-");
      // caldav_line_value() answers the end of the line when there is no
      // separator outside quotes; a real one leaves its ':' just behind.
      const char *value = caldav_line_value(line);
      bool has_value = value > line && value[-1] == ':';
      if (name_len == 0 || (line[name_len] != ':' && line[name_len] != ';') ||
          !has_value) {
        snprintf(err, err_size, "line %d is not NAME:value: %.60s", line_no,
                 line);
        return false;
      }
      if (caldav_line_is(line, "BEGIN") || caldav_line_is(line, "END")) {
        bool begin = caldav_line_is(line, "BEGIN");
        if (strcasecmp(value, "VTODO") == 0 ||
            strcasecmp(value, "VCALENDAR") == 0) {
          snprintf(err, err_size, "line %d: %s:%s belongs to the server",
                   line_no, begin ? "BEGIN" : "END", value);
          return false;
        }
        if (begin) {
          if (depth == (int)(sizeof(stack) / sizeof(stack[0]))) {
            snprintf(err, err_size, "line %d: components nest too deep",
                     line_no);
            return false;
          }
          caldav_copy_str(stack[depth++], sizeof(stack[0]), value);
        } else if (depth == 0 || strcasecmp(stack[depth - 1], value) != 0) {
          snprintf(err, err_size, "line %d: END:%s closes nothing open",
                   line_no, value);
          return false;
        } else {
          depth--;
        }
      } else if (depth == 0) {
        for (size_t i = 0;
             i < sizeof(g_caldav_owned_props) / sizeof(g_caldav_owned_props[0]);
             i++) {
          if (caldav_line_is(line, g_caldav_owned_props[i])) {
            snprintf(err, err_size,
                     "line %d: %s comes from the entry itself (title, "
                     "text, done, timestamps)",
                     line_no, g_caldav_owned_props[i]);
            return false;
          }
        }
      }
      jsonbuf_append_len(out, line, line_len);
      jsonbuf_append_len(out, "\n", 1);
    }

    if (!nl) {
      break;
    }
    line = nl + 1;
  }
  if (depth != 0) {
    snprintf(err, err_size, "BEGIN:%s is never ended", stack[depth - 1]);
    return false;
  }
  if (out->overflow) {
    snprintf(err, err_size, "too long");
    return false;
  }
  return true;
}

// The view itself. `synced` says whether the entry is a live task in a
// published list; a row of any other kind is answered too (the page asks
// before it knows) but has no VTODO to show. `extra_ical` is the lines as a
// client sees them now - after a reschedule in the journal, the rewritten
// DTSTART/DUE rather than the stale ones in the table - because those are
// what the page edits and PUTs back.
static int caldav_send_entry_view(int client_fd, Arena *arena, Arena *scratch,
                                  sqlite3 *db, int id) {
  assert(client_fd >= 0);
  assert(arena_valid(arena) && arena_valid(scratch));
  assert(db != NULL);
  assert(id > 0);

  sqlite3_stmt *stmt = NULL;
  const char *sql =
      "SELECT " CALDAV_TASK_COLUMNS CALDAV_TASK_FROM "WHERE e.id = ?1;";
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
    return SendJSONError(client_fd, 500, "Database error: %s",
                         sqlite3_errmsg(db));
  }
  sqlite3_bind_int(stmt, 1, id);
  if (sqlite3_step(stmt) != SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return SendJSONError(client_fd, 404, "No entry %d", id);
  }
  const char *kind = (const char *)sqlite3_column_text(stmt, CALDAV_COL_KIND);
  bool deleted = sqlite3_column_int(stmt, CALDAV_COL_DELETED) != 0;
  CalDAVList list;
  bool listed = caldav_list_by_kind(db, kind, &list, false);
  if (!listed) {
    // Not published: the href it would have in the task kind's list.
    caldav_list_defaults(caldav_task_kind(), &list);
  }
  bool synced = listed && !deleted;
  const char *stored_name =
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_NAME);
  char name[CALDAV_MAX_NAME];
  char href[CALDAV_MAX_NAME * 6 + 64];
  char uid[CALDAV_MAX_UID];
  caldav_resource_name(id, stored_name, name, sizeof(name));
  caldav_task_href(&list, name, href, sizeof(href));
  caldav_uid(id, (const char *)sqlite3_column_text(stmt, CALDAV_COL_UID), uid,
             sizeof(uid));

  JSONBuf extra;
  jsonbuf_init(&extra, arena);
  caldav_effective_extra(
      id, (const char *)sqlite3_column_text(stmt, CALDAV_COL_EXTRA),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_START),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_END),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_SYNC_START),
      (const char *)sqlite3_column_text(stmt, CALDAV_COL_SYNC_END),
      sqlite3_column_int(stmt, CALDAV_COL_DONE) != 0, &extra);

  JSONBuf b;
  jsonbuf_init(&b, arena);
  jsonbuf_appendf(&b, "{\"entry_id\":%d,\"task_kind\":", id);
  jsonbuf_append_json_string(&b, caldav_task_kind());
  jsonbuf_append(&b, ",\"list\":");
  jsonbuf_append_json_string(&b, listed ? list.name : "");
  jsonbuf_append(&b, ",\"list_kind\":");
  jsonbuf_append_json_string(&b, listed ? list.kind : "");
  jsonbuf_appendf(&b, ",\"synced\":%s,\"stored\":%s,\"href\":",
                  synced ? "true" : "false", stored_name ? "true" : "false");
  jsonbuf_append_json_string(&b, href);
  jsonbuf_append(&b, ",\"uid\":");
  jsonbuf_append_json_string(&b, uid);
  jsonbuf_append(&b, ",\"last_modified_at_utc\":");
  jsonbuf_append_json_string(
      &b, (const char *)sqlite3_column_text(stmt, CALDAV_COL_MODIFIED));
  jsonbuf_append(&b, ",\"extra_ical\":");
  jsonbuf_append_json_string(&b, extra.data ? extra.data : "");
  jsonbuf_append(&b, ",\"extra_vcal\":");
  jsonbuf_append_json_string(
      &b, (const char *)sqlite3_column_text(stmt, CALDAV_COL_EXTRA_VCAL));
  sqlite3_finalize(stmt);

  // What a CalDAV client sees: the whole VTODO and its ETag, which a PUT
  // here hands back to say "the version I edited".
  char etag[64] = "";
  sqlite3_stmt *task =
      synced ? caldav_task_stmt_by_id(db, id, list.kind) : NULL;
  if (task && sqlite3_step(task) == SQLITE_ROW) {
    caldav_etag_for(scratch, task, etag, sizeof(etag));
    arena_reset(scratch);
    JSONBuf ics;
    jsonbuf_init(&ics, scratch);
    caldav_build_ics(task, &ics);
    jsonbuf_append(&b, ",\"ics\":");
    jsonbuf_append_json_string(&b, ics.overflow ? "" : ics.data);
  } else {
    jsonbuf_append(&b, ",\"ics\":\"\"");
  }
  if (task) {
    sqlite3_finalize(task);
  }
  jsonbuf_append(&b, ",\"etag\":");
  jsonbuf_append_json_string(&b, etag);
  jsonbuf_append(&b, "}");
  return SendJSONBuf(client_fd, &b);
}

// Replaces the kept lines and stamps the row, in one transaction - and, when
// the lines' DTSTART/DUE moved, the schedule columns with them, which is
// how a due date set in the web UI's reminders panel (or by lcars-cli due)
// lands on the day view. The stamp is what tells everyone else: it moves
// the list's ctag (so Reminders re-lists), the task's DTSTAMP and ETag, and
// the web UI's delta sync.
static bool caldav_store_extra(sqlite3 *db, int id, const char *extra) {
  assert(db != NULL);
  assert(id > 0);
  assert(extra != NULL);

  char s[20], e[20], ss[20], se[20];
  caldav_derive_schedule(extra, s, e);
  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    return false;
  }
  caldav_read_sync(db, id, ss, se);
  bool reschedule = strcmp(s, ss) != 0 || strcmp(e, se) != 0;
  // A task made in the UI has no side row; it gets one under the very name
  // and UID it was already published with, so no client sees it move.
  char name[CALDAV_MAX_NAME];
  char uid[CALDAV_MAX_UID];
  caldav_resource_name(id, NULL, name, sizeof(name));
  caldav_uid(id, NULL, uid, sizeof(uid));
  sqlite3_stmt *stmt = NULL;
  const char *sql =
      "INSERT INTO caldav_tasks (entry_id, resource_name, uid, extra_ical, "
      "extra_vcal, sync_start, sync_end) VALUES (?1, ?2, ?3, ?4, '', ?5, ?6) "
      "ON CONFLICT(entry_id) DO UPDATE SET extra_ical = excluded.extra_ical, "
      "sync_start = excluded.sync_start, sync_end = excluded.sync_end;";
  bool ok = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK;
  if (ok) {
    sqlite3_bind_int(stmt, 1, id);
    sqlite3_bind_text(stmt, 2, name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, uid, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, extra, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, s, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, e, -1, SQLITE_TRANSIENT);
    ok = sqlite3_step(stmt) == SQLITE_DONE;
  }
  sqlite3_finalize(stmt);
  stmt = NULL;
  if (ok) {
    const char *touch =
        "UPDATE entries SET start_date = CASE WHEN ?2 THEN ?3 ELSE start_date "
        "END, end_date = CASE WHEN ?2 THEN ?4 ELSE end_date END, "
        "last_modified_at_utc = strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') "
        "WHERE id = ?1;";
    ok = sqlite3_prepare_v2(db, touch, -1, &stmt, NULL) == SQLITE_OK;
    if (ok) {
      sqlite3_bind_int(stmt, 1, id);
      sqlite3_bind_int(stmt, 2, reschedule ? 1 : 0);
      sqlite3_bind_text(stmt, 3, s, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 4, e, -1, SQLITE_TRANSIENT);
      ok = sqlite3_step(stmt) == SQLITE_DONE;
    }
    sqlite3_finalize(stmt);
  }
  if (!ok) {
    printf("CalDAV Database Error: extra write failed: %s\n",
           sqlite3_errmsg(db));
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return false;
  }
  if (sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return false;
  }
  return true;
}

static int caldav_put_entry_extra(int client_fd, Arena *arena, Arena *scratch,
                                  sqlite3 *db, int id, const char *body) {
  assert(client_fd >= 0);
  assert(arena_valid(arena) && arena_valid(scratch));
  assert(db != NULL && body != NULL);
  assert(id > 0);

  char *extra = NULL;
  if (!json_get_string_arena(arena, body, "extra_ical", &extra)) {
    return SendJSONError(client_fd, 400, "Body needs {\"extra_ical\": ...}");
  }
  // Only a live task in a published list: lines kept for a row CalDAV does
  // not publish would surface, unasked, the day its kind changed.
  char kind[CALDAV_MAX_KIND] = "";
  sqlite3_stmt *k = NULL;
  if (sqlite3_prepare_v2(db, "SELECT kind FROM entries WHERE id = ?1;", -1, &k,
                         NULL) == SQLITE_OK) {
    sqlite3_bind_int(k, 1, id);
    if (sqlite3_step(k) == SQLITE_ROW) {
      caldav_copy_str(kind, sizeof(kind),
                      (const char *)sqlite3_column_text(k, 0));
    }
    sqlite3_finalize(k);
  }
  CalDAVList list;
  char etag[64] = "";
  bool live =
      caldav_list_by_kind(db, kind, &list, false) &&
      caldav_current_etag(db, scratch, id, list.kind, etag, sizeof(etag));
  if (!live) {
    return SendJSONError(client_fd, 409,
                         "Entry %d is not a live task in a published list "
                         "(kind '%s' or '%s_*')",
                         id, caldav_task_kind(), caldav_task_kind());
  }
  // The ETag the page last saw: a client that synced in between (Reminders
  // moving the due date) must not be overwritten by an older view of it.
  char want[64];
  if (json_get_string(body, "etag", want, sizeof(want)) && want[0] != '\0' &&
      strcmp(want, etag) != 0) {
    return SendJSONError(client_fd, 412,
                         "The task changed since it was read; reload it");
  }

  JSONBuf clean;
  jsonbuf_init(&clean, arena);
  char err[160];
  if (!caldav_check_extra(arena, extra, &clean, err, sizeof(err))) {
    return SendJSONError(client_fd, 400, "%s", err);
  }
  if (!caldav_store_extra(db, id, clean.data ? clean.data : "")) {
    return SendJSONError(client_fd, 500, "Database error: %s",
                         sqlite3_errmsg(db));
  }
  return caldav_send_entry_view(client_fd, arena, scratch, db, id);
}

// Side rows written before the schedule mapping existed have no sync_start.
// Their dates are read into the columns once - only where the entry has no
// schedule of its own, which the journal set and which therefore wins - and
// the row is stamped, so the web UI's delta sync sees the new dates. After
// this pass every side row has a sync_start ("" when undated), so it costs
// one indexed-nothing SELECT per request from then on.
static void caldav_backfill_schedule(sqlite3 *db) {
  assert(db != NULL);
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT c.entry_id, c.extra_ical, e.start_date, "
                         "e.end_date FROM caldav_tasks c JOIN entries e ON "
                         "e.id = c.entry_id WHERE c.sync_start IS NULL;",
                         -1, &stmt, NULL) != SQLITE_OK) {
    return;
  }
  int ids[256];
  char starts[256][20], ends[256][20];
  bool fill[256];
  int n = 0;
  while (n < 256 && sqlite3_step(stmt) == SQLITE_ROW) {
    ids[n] = sqlite3_column_int(stmt, 0);
    caldav_derive_schedule((const char *)sqlite3_column_text(stmt, 1),
                           starts[n], ends[n]);
    const char *s = (const char *)sqlite3_column_text(stmt, 2);
    const char *e = (const char *)sqlite3_column_text(stmt, 3);
    fill[n] =
        starts[n][0] != '\0' && (!s || s[0] == '\0') && (!e || e[0] == '\0');
    n++;
  }
  sqlite3_finalize(stmt);
  for (int i = 0; i < n; i++) {
    // Without the fill the columns stay as the journal has them, and the
    // sync values say what the lines said - so the columns win on output.
    if (fill[i] &&
        sqlite3_prepare_v2(db,
                           "UPDATE entries SET start_date = ?2, end_date = ?3, "
                           "last_modified_at_utc = strftime('%Y-%m-%d "
                           "%H:%M:%S', 'now', 'utc') WHERE id = ?1;",
                           -1, &stmt, NULL) == SQLITE_OK) {
      sqlite3_bind_int(stmt, 1, ids[i]);
      sqlite3_bind_text(stmt, 2, starts[i], -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 3, ends[i], -1, SQLITE_TRANSIENT);
      sqlite3_step(stmt);
      sqlite3_finalize(stmt);
    }
    if (sqlite3_prepare_v2(db,
                           "UPDATE caldav_tasks SET sync_start = ?2, sync_end "
                           "= ?3 WHERE entry_id = ?1;",
                           -1, &stmt, NULL) == SQLITE_OK) {
      sqlite3_bind_int(stmt, 1, ids[i]);
      sqlite3_bind_text(stmt, 2, starts[i], -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(stmt, 3, ends[i], -1, SQLITE_TRANSIENT);
      sqlite3_step(stmt);
      sqlite3_finalize(stmt);
    }
  }
  if (n > 0) {
    printf("CalDAV: read the due dates of %d older task(s) into the schedule\n",
           n);
  }
}

// Opens the database for one request, with the side tables in place and the
// thread's default zone learnt. NULL (having logged why) on failure.
static sqlite3 *caldav_open_db(void) {
  sqlite3 *db = NULL;
  int rc = sqlite3_open(LcarsDBPath(), &db);
  if (rc != SQLITE_OK) {
    printf("CalDAV Database Error: cannot open '%s': %s\n", LcarsDBPath(),
           sqlite3_errstr(rc));
    if (db) {
      sqlite3_close(db);
    }
    return NULL;
  }
  // The API writes while the UI may be saving; without this a CalDAV write
  // racing a debounced editor save fails outright instead of waiting.
  sqlite3_busy_timeout(db, 2000);
  if (!caldav_ensure_schema(db)) {
    sqlite3_close(db);
    return NULL;
  }
  caldav_init_zone(db);
  caldav_backfill_schedule(db);
  return db;
}

static int HandleEntryCalDAV(int client_fd, Arena *arena, const char *method,
                             int id, const char *headers, const char *body) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL && headers != NULL && body != NULL);
  assert(id > 0);

  caldav_init_ui_base(headers);
  bool get = strcmp(method, "GET") == 0;
  if (!get && strcmp(method, "PUT") != 0) {
    return SendJSONError(client_fd, 405,
                         "Method %s not allowed on /entries/<id>/caldav",
                         method);
  }
  // Same scratch arrangement as HandleCalDAVRequest, for the same reason:
  // the ETag hash resets whatever arena it is handed.
  uint8_t scratch_backing[512 * 1024];
  Arena scratch;
  arena_init(&scratch, scratch_backing, sizeof(scratch_backing));

  sqlite3 *db = caldav_open_db();
  if (!db) {
    return SendJSONError(client_fd, 500, "Cannot open the database");
  }
  caldav_load_task_kind(db);
  int status;
  if (get) {
    status = caldav_send_entry_view(client_fd, arena, &scratch, db, id);
  } else {
    status = caldav_put_entry_extra(client_fd, arena, &scratch, db, id, body);
  }
  sqlite3_close(db);
  return status;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

static bool caldav_is_dav_method(const char *method) {
  assert(method != NULL);
  return strcmp(method, "PROPFIND") == 0 || strcmp(method, "PROPPATCH") == 0 ||
         strcmp(method, "REPORT") == 0 || strcmp(method, "MKCALENDAR") == 0 ||
         strcmp(method, "MKCOL") == 0 || strcmp(method, "LOCK") == 0 ||
         strcmp(method, "UNLOCK") == 0 || strcmp(method, "MOVE") == 0 ||
         strcmp(method, "COPY") == 0;
}

static bool IsCalDAVRequest(const char *method, const char *path) {
  assert(method != NULL);
  assert(path != NULL);

  if (caldav_is_dav_method(method)) {
    return true;
  }
  // Note that GET / is deliberately not claimed here - that is the JSON
  // API's index. Only the WebDAV methods reach the CalDAV root.
  if (strncmp(path, "/caldav", 7) == 0) {
    return true;
  }
  return caldav_path_is(path, CALDAV_WELL_KNOWN);
}

// $LCARS_CALDAV_LOG=1 prints every CalDAV request's method, path, Depth and
// body (the first 4KB) to the journal. Off by default - the bodies are task
// text - and meant for learning what a client actually sends.
static void caldav_log_request(const char *method, const char *path,
                               const char *headers, const char *body) {
  const char *on = getenv("LCARS_CALDAV_LOG");
  if (!on || strcmp(on, "1") != 0) {
    return;
  }
  char depth[16] = "-";
  CopyHeaderValue(headers, "Depth:", depth, sizeof(depth));
  char agent[96] = "";
  CopyHeaderValue(headers, "User-Agent:", agent, sizeof(agent));
  printf("CalDAV log: %s %s Depth=%s UA=%s\n%.4096s\n", method, path, depth,
         agent, body);
}

static int HandleCalDAVRequest(int client_fd, Arena *arena, const char *method,
                               const char *path, const char *headers,
                               const char *body) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL && path != NULL);
  assert(headers != NULL && body != NULL);

  caldav_log_request(method, path, headers, body);
  caldav_init_ui_base(headers);

  // A second arena, so that building one task's iCalendar text (to hash it
  // for an ETag, or to inline it in a REPORT) never allocates in the middle
  // of the response buffer that is growing in the connection arena - which
  // is what makes it safe to reset between rows.
  //
  // On the stack, not static: RunHTTPServer() now serves each connection on
  // its own thread, so a shared buffer here would be two requests building
  // iCalendar text into the same bytes. That is what HTTP_THREAD_STACK_BYTES
  // is sized for - half a megabyte here on top of the connection's 1MB
  // request arena.
  uint8_t scratch_backing[512 * 1024];
  Arena scratch;
  arena_init(&scratch, scratch_backing, sizeof(scratch_backing));

  char segment[CALDAV_MAX_NAME];
  char name[CALDAV_MAX_NAME];
  CalDAVPathKind kind =
      caldav_classify(path, segment, sizeof(segment), name, sizeof(name));

  if (strcmp(method, "OPTIONS") == 0) {
    return caldav_send_status(client_fd, 200, CALDAV_ALLOW_HEADER);
  }
  if (kind == CALDAV_PATH_NONE) {
    return caldav_send_status(client_fd, 404, NULL);
  }

  // Nothing above this line touches the database, so a probe for a path that
  // does not exist costs no connection.
  sqlite3 *db = caldav_open_db();
  if (!db) {
    return caldav_send_status(client_fd, 500, NULL);
  }
  caldav_load_task_kind(db);

  // A collection or resource path names a list, which must exist - except
  // for MKCALENDAR, whose whole point is that it does not yet.
  CalDAVList list;
  bool has_list = false;
  if (kind == CALDAV_PATH_COLLECTION || kind == CALDAV_PATH_RESOURCE) {
    has_list = caldav_list_by_segment(db, segment, &list);
    bool creating =
        kind == CALDAV_PATH_COLLECTION && strcmp(method, "MKCALENDAR") == 0;
    if (!has_list && !creating) {
      sqlite3_close(db);
      return caldav_send_status(client_fd, 404, NULL);
    }
  }
  const CalDAVList *lp = has_list ? &list : NULL;
  bool on_resource = kind == CALDAV_PATH_RESOURCE;
  bool on_collection = kind == CALDAV_PATH_COLLECTION;

  int status;
  if (strcmp(method, "PROPFIND") == 0) {
    status = caldav_handle_propfind(client_fd, arena, &scratch, db, kind, path,
                                    lp, name, caldav_depth(headers));
  } else if (strcmp(method, "REPORT") == 0) {
    status = caldav_handle_report(client_fd, arena, &scratch, db, kind, lp,
                                  name, body);
  } else if (strcmp(method, "GET") == 0 || strcmp(method, "HEAD") == 0) {
    status = on_resource
                 ? caldav_handle_get(client_fd, arena, &scratch, db, lp, name)
                 : caldav_send_status(client_fd, 405, CALDAV_ALLOW_HEADER);
  } else if (strcmp(method, "PUT") == 0) {
    status = on_resource
                 ? caldav_handle_put(client_fd, arena, &scratch, db, lp, name,
                                     headers, body)
                 : caldav_send_status(client_fd, 405, CALDAV_ALLOW_HEADER);
  } else if (strcmp(method, "DELETE") == 0) {
    if (on_resource) {
      status = caldav_handle_delete(client_fd, &scratch, db, lp, name, headers);
    } else if (on_collection) {
      status = caldav_handle_delete_list(client_fd, db, lp);
    } else {
      status = caldav_send_status(client_fd, 403, NULL);
    }
  } else if (strcmp(method, "MOVE") == 0) {
    status = on_resource ? caldav_handle_move(client_fd, db, lp, name, headers)
                         : caldav_send_status(client_fd, 403, NULL);
  } else if (strcmp(method, "MKCALENDAR") == 0) {
    status = on_collection
                 ? caldav_handle_mkcalendar(client_fd, db, segment, body)
                 : caldav_send_status(client_fd, 403, NULL);
  } else if (strcmp(method, "PROPPATCH") == 0) {
    if (on_collection) {
      status = caldav_handle_proppatch(client_fd, arena, db, lp, body);
    } else {
      // The home, the principal and a task have no writable properties.
      status = caldav_send_error(client_fd, 403,
                                 "<D:cannot-modify-protected-property/>");
    }
  } else {
    status = caldav_send_status(client_fd, 405, CALDAV_ALLOW_HEADER);
  }

  sqlite3_close(db);
  return status;
}

#endif // LCARS_CALDAV_IMPLEMENTATION
#endif // LCARS_CALDAV_H
