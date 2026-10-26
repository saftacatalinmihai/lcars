#ifndef LCARS_METRICS_H
#define LCARS_METRICS_H

// GET /metrics - the journal's numbers in Prometheus' text format, for the
// Grafana Alloy on the VPS (scripts/metrics-setup.sh) to scrape and send on
// to Grafana Cloud beside node_exporter's.
//
//   lcars_reading{kind}                    the latest reading of each kind
//   lcars_reading_timestamp_seconds{kind}  when it was measured (unix time)
//   lcars_entries_total{kind}              live entries of each kind
//   (and the crew's, below)
//
// A reading is exactly what the web UI's reading()/measureSeries() call one
// (index.html): a live row whose value_float is non-zero, else whose
// value_int is non-zero, else whose title opens with a zero as /log types it
// ("/log coffee 0"); and whose created_at_utc parses, since that is when it
// was measured. The latest is the newest created_at_utc, the higher id on a
// tie - the last point of the UI's series. A kind with one reading is
// exported too: Grafana draws one point, where the UI's chips wait for two.
//
// Keyed on kind alone, not kind and title. A reading's title is its own
// label as /log typed it ("7h 06m", "25 min", a word learned that day), so
// it is different on nearly every row: a series per title would be hundreds
// of one-sample series, each gone stale the scrape after, and no line at all.
//
// The time a reading was measured is a second gauge rather than the sample's
// own timestamp. A sample stamped with when it was measured (yesterday's
// sleep) would arrive at Grafana Cloud hours or days behind the series' head
// and be refused as out of bounds past Mimir's out-of-order window, and
// Prometheus treats a target's explicit timestamps as never going stale; the
// _timestamp_seconds idiom keeps every sample "now" and the measurement time
// still queryable (time() - lcars_reading_timestamp_seconds is its age).
// History before the exporter was installed is not sent: Grafana Cloud refuses
// samples older than ~2h (the backfill script, in git before 0.174.6).
//
// lcars_entries_total is a gauge despite the _total the order named it by:
// a deleted row makes it go down, which a counter may not.
//
// And the crew's numbers - the seat, the job line, the deploys
// (scripts/eng_metrics.py, docs/ops/seat-metrics.md): engineer.py renders
// them at each event into a Prometheus text file, and this appends that file
// as it stands, as node_exporter's textfile collector does, after
//
//   lcars_eng_metrics_timestamp_seconds    the file's mtime (unix time)
//
// so a file nobody has written lately shows its age in Grafana (time() -
// it) rather than a flat line of last week's values; reap rewrites it every
// five minutes. The file is $LCARS_ENG_METRICS, else metrics/metrics.prom
// under $LCARS_ENG_STATE, else under ~/.local/state/lcars-eng (engineer.py's
// own rule); LCARS_ENG_METRICS set empty turns it off. A box with no crew
// has no file, and /metrics is the journal's alone: no timestamp either, so
// absent() tells the two apart. The file is ours, rendered whole and renamed
// into place, so it is passed through unparsed - only bounded in size
// (METRICS_ENG_MAX: an arena's request must not be one file's to fill) and
// given its final newline.
//
// Who may read it: the rule of the web UI and the media files - loopback
// (Alloy on the box, and tailscale serve) without a password, the public
// port with Basic auth. No secret ever goes in the URL.
//
// A module of lcars_http.h, included from inside its
// LCARS_HTTP_IMPLEMENTATION block (SendHTTPResponse, OpenHTTPDB, JSONBuf).

static int HandleMetrics(int client_fd, Arena *arena, const char *method);

#ifdef LCARS_METRICS_IMPLEMENTATION

#include <float.h>
#include <math.h>

// "YYYY-MM-DD HH:MM[:SS]" (or a T between), UTC, as unix seconds - the
// shapes index.html's parseUtc takes. false for anything else, which the
// caller skips as the UI does: a row without a date is not on a timeline.
static bool MetricsParseUtc(const char *s, int64_t *out) {
  assert(out != NULL);
  if (s == NULL) {
    return false;
  }
  while (*s == ' ' || *s == '\t') {
    s++;
  }
  int y, mo, d, h, mi, sec = 0, n = 0;
  char sep;
  if (sscanf(s, "%4d-%2d-%2d%c%2d:%2d%n", &y, &mo, &d, &sep, &h, &mi, &n) !=
          6 ||
      (sep != ' ' && sep != 'T')) {
    return false;
  }
  s += n;
  if (*s == ':') {
    int m = 0;
    if (sscanf(s, ":%2d%n", &sec, &m) != 1) {
      return false;
    }
    s += m;
  }
  while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') {
    s++;
  }
  if (*s != '\0' || mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 ||
      sec > 60 || y < 1 || h < 0 || mi < 0 || sec < 0) {
    return false;
  }
  // timegm, not mktime: UTC whatever the server's TZ (glibc, _GNU_SOURCE)
  struct tm tm = {.tm_year = y - 1900,
                  .tm_mon = mo - 1,
                  .tm_mday = d,
                  .tm_hour = h,
                  .tm_min = mi,
                  .tm_sec = sec};
  *out = (int64_t)timegm(&tm);
  return true;
}

// index.html's ZERO_TITLE: /^[+-]?(?:0+(?:[.,]0*)?|[.,]0+)(?:\s|$)/
static bool MetricsZeroTitle(const char *t) {
  if (t == NULL) {
    return false;
  }
  if (*t == '+' || *t == '-') {
    t++;
  }
  if (*t == '0') {
    while (*t == '0') {
      t++;
    }
    if (*t == '.' || *t == ',') {
      t++;
      while (*t == '0') {
        t++;
      }
    }
  } else if (*t == '.' || *t == ',') {
    t++;
    if (*t != '0') {
      return false;
    }
    while (*t == '0') {
      t++;
    }
  } else {
    return false;
  }
  // JS's \s, as far as a title can hold it in ASCII
  return *t == '\0' || *t == ' ' || *t == '\t' || *t == '\n' || *t == '\r' ||
         *t == '\f' || *t == '\v';
}

// The length of the valid UTF-8 sequence at p, or 0 when it is not one
// (a stray continuation byte, a truncated or overlong sequence, a surrogate).
static size_t MetricsUtf8Len(const unsigned char *p) {
  if (p[0] < 0x80) {
    return 1;
  }
  size_t n;
  uint32_t cp;
  if ((p[0] & 0xE0) == 0xC0) {
    n = 2;
    cp = p[0] & 0x1F;
  } else if ((p[0] & 0xF0) == 0xE0) {
    n = 3;
    cp = p[0] & 0x0F;
  } else if ((p[0] & 0xF8) == 0xF0) {
    n = 4;
    cp = p[0] & 0x07;
  } else {
    return 0;
  }
  for (size_t i = 1; i < n; i++) {
    if ((p[i] & 0xC0) != 0x80) { // also stops at the terminator
      return 0;
    }
    cp = (cp << 6) | (p[i] & 0x3F);
  }
  static const uint32_t min[5] = {0, 0, 0x80, 0x800, 0x10000};
  if (cp < min[n] || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
    return 0;
  }
  return n;
}

// A label value: backslash, double quote and newline escaped, as the text
// format wants. A kind is free text, and Prometheus refuses the whole scrape
// over one label that is not UTF-8, so a byte that is not part of a valid
// sequence goes out as U+FFFD rather than as itself.
static void MetricsAppendLabel(JSONBuf *b, const char *s) {
  assert(b != NULL);
  const unsigned char *p = (const unsigned char *)(s ? s : "");
  while (*p) {
    size_t n = MetricsUtf8Len(p);
    if (n == 0) {
      jsonbuf_append(b, "\xEF\xBF\xBD");
      p++;
    } else if (*p == '\\') {
      jsonbuf_append(b, "\\\\");
      p++;
    } else if (*p == '"') {
      jsonbuf_append(b, "\\\"");
      p++;
    } else if (*p == '\n') {
      jsonbuf_append(b, "\\n");
      p++;
    } else {
      jsonbuf_append_len(b, (const char *)p, n);
      p += n;
    }
  }
}

// A sample value. %.17g round-trips any double, but the journal's floats
// went through a float on their way in (the UI's and the API's parsers), so
// 6.3 is stored as 6.300000190734863 - true to the bit and wrong to the eye
// in every Grafana legend. A value that is exactly a float is printed in the
// fewest digits that come back as that same float ("6.3"); anything else in
// full. %g prints infinities as "inf", which the text format spells +Inf.
static void MetricsAppendValue(JSONBuf *b, double v) {
  assert(b != NULL);
  if (isinf(v)) {
    jsonbuf_append(b, v > 0 ? "+Inf" : "-Inf");
    return;
  }
  if (isnan(v)) {
    jsonbuf_append(b, "NaN");
    return;
  }
  if (fabs(v) <= FLT_MAX && (double)(float)v == v) {
    char tmp[32];
    for (int prec = 1; prec <= 9; prec++) {
      snprintf(tmp, sizeof(tmp), "%.*g", prec, v);
      if ((float)strtod(tmp, NULL) == (float)v) {
        jsonbuf_append(b, tmp);
        return;
      }
    }
  }
  jsonbuf_appendf(b, "%.17g", v);
}

typedef struct MetricsLatest {
  bool have;
  double value;
  int64_t at;
  int64_t id;
} MetricsLatest;

// Longest kind exported, in bytes. A kind is a short slug; the bound lets
// the one being gathered sit in a fixed buffer rather than the arena (whose
// exhaustion aborts), and a row with a longer one is skipped, not fatal.
#define METRICS_KIND_MAX 256

static void MetricsEmitReading(JSONBuf *b, bool stamps, const char *kind,
                               const MetricsLatest *l) {
  assert(l != NULL);
  if (!l->have) {
    return;
  }
  jsonbuf_append(b, stamps ? "lcars_reading_timestamp_seconds{kind=\""
                           : "lcars_reading{kind=\"");
  MetricsAppendLabel(b, kind);
  jsonbuf_append(b, "\"} ");
  if (stamps) {
    jsonbuf_appendf(b, "%lld", (long long)l->at);
  } else {
    MetricsAppendValue(b, l->value);
  }
  jsonbuf_append(b, "\n");
}

// One pass over the candidate rows (ordered by kind), appending each kind's
// latest reading - its value, or with `stamps` its time. Run twice rather
// than holding every kind's result: the text format wants each metric's
// samples together, and one buffer growing in place is all the arena holds.
static bool MetricsReadings(sqlite3_stmt *rs, JSONBuf *b, bool stamps) {
  assert(rs != NULL);
  sqlite3_reset(rs);
  char kind[METRICS_KIND_MAX];
  bool have_kind = false;
  MetricsLatest latest = {0};
  int rc;
  while ((rc = sqlite3_step(rs)) == SQLITE_ROW) {
    const char *k = (const char *)sqlite3_column_text(rs, 0);
    if (k == NULL) {
      k = "";
    }
    size_t len = strlen(k);
    if (len >= sizeof(kind)) {
      continue;
    }
    if (!have_kind || strcmp(kind, k) != 0) {
      if (have_kind) {
        MetricsEmitReading(b, stamps, kind, &latest);
      }
      memcpy(kind, k, len + 1);
      have_kind = true;
      latest = (MetricsLatest){0};
    }
    // reading(e): value_float, else value_int, else a zero title
    double v = sqlite3_column_double(rs, 3);
    if (v == 0) {
      v = (double)sqlite3_column_int64(rs, 2);
    }
    if (v == 0 && !MetricsZeroTitle((const char *)sqlite3_column_text(rs, 1))) {
      continue;
    }
    int64_t at;
    if (!MetricsParseUtc((const char *)sqlite3_column_text(rs, 4), &at)) {
      continue;
    }
    int64_t id = sqlite3_column_int64(rs, 5);
    if (!latest.have || at > latest.at || (at == latest.at && id > latest.id)) {
      latest = (MetricsLatest){true, v, at, id};
    }
  }
  if (have_kind) {
    MetricsEmitReading(b, stamps, kind, &latest);
  }
  return rc == SQLITE_DONE;
}

// The crew's metrics file, at most this many bytes; a bigger one is skipped
// (and said in the log) rather than cut, since a cut line breaks the scrape.
// eng_metrics.py's whole render is ~30KB.
#define METRICS_ENG_MAX (256 * 1024)

// The path of the crew's file into buf, or false when it is turned off or
// does not fit.
static bool MetricsEngPath(char *buf, size_t n) {
  assert(buf != NULL && n > 0);
  const char *p = getenv("LCARS_ENG_METRICS");
  int w;
  if (p != NULL) {
    if (*p == '\0') {
      return false;
    }
    w = snprintf(buf, n, "%s", p);
  } else if ((p = getenv("LCARS_ENG_STATE")) != NULL && *p != '\0') {
    w = snprintf(buf, n, "%s/metrics/metrics.prom", p);
  } else if ((p = getenv("HOME")) != NULL && *p != '\0') {
    w = snprintf(buf, n, "%s/.local/state/lcars-eng/metrics/metrics.prom", p);
  } else {
    return false;
  }
  return w > 0 && (size_t)w < n;
}

// Appends the crew's file, under its timestamp, when there is one to read.
static void MetricsAppendEng(JSONBuf *out) {
  assert(out != NULL);
  char path[PATH_MAX];
  if (!MetricsEngPath(path, sizeof(path))) {
    return;
  }
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return; // no crew here, or not yet: the journal's numbers alone
  }
  struct stat sb;
  if (fstat(fd, &sb) != 0 || !S_ISREG(sb.st_mode)) {
    close(fd);
    return;
  }
  if (sb.st_size > METRICS_ENG_MAX) {
    fprintf(stderr, "metrics: %s is %lld bytes, over %d: skipped\n", path,
            (long long)sb.st_size, METRICS_ENG_MAX);
    close(fd);
    return;
  }
  jsonbuf_append(out, "# HELP lcars_eng_metrics_timestamp_seconds When the "
                      "crew's metrics file was last written.\n"
                      "# TYPE lcars_eng_metrics_timestamp_seconds gauge\n");
  jsonbuf_appendf(out, "lcars_eng_metrics_timestamp_seconds %lld\n",
                  (long long)sb.st_mtime);
  // read to the end, bounded: the file is replaced by rename, never
  // rewritten in place, so this descriptor's bytes are one whole render
  char chunk[16384];
  size_t total = 0;
  char last = '\n';
  ssize_t r;
  while (total < METRICS_ENG_MAX &&
         (r = read(fd, chunk,
                   sizeof(chunk) < METRICS_ENG_MAX - total
                       ? sizeof(chunk)
                       : METRICS_ENG_MAX - total)) != 0) {
    if (r < 0) {
      if (errno == EINTR) {
        continue;
      }
      break;
    }
    jsonbuf_append_len(out, chunk, (size_t)r);
    total += (size_t)r;
    last = chunk[r - 1];
  }
  close(fd);
  if (last != '\n') {
    jsonbuf_append(out, "\n");
  }
}

static int HandleMetrics(int client_fd, Arena *arena, const char *method) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL);

  if (strcmp(method, "GET") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on /metrics",
                         method);
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }

  // The readings: SQL narrows to rows that could be one (a non-zero column,
  // or a title opening as a zero might), C applies the exact rule.
  sqlite3_stmt *rs = NULL;
  sqlite3_stmt *cs = NULL;
  int rc = sqlite3_prepare_v2(
      db,
      "SELECT COALESCE(kind, ''), title, value_int, value_float, "
      "created_at_utc, id "
      "FROM entries WHERE (deleted IS NULL OR deleted = 0) AND "
      "(value_float <> 0 OR value_int <> 0 OR title GLOB '[-+.,0]*') "
      "ORDER BY 1;",
      -1, &rs, NULL);
  if (rc == SQLITE_OK) {
    rc = sqlite3_prepare_v2(
        db,
        "SELECT COALESCE(kind, ''), COUNT(*) FROM entries WHERE deleted IS "
        "NULL OR deleted = 0 GROUP BY 1 ORDER BY 1;",
        -1, &cs, NULL);
  }
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_finalize(rs);
    sqlite3_close(db);
    return status;
  }

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "# HELP lcars_reading The latest reading of each kind "
                       "(value_float, else value_int).\n"
                       "# TYPE lcars_reading gauge\n");
  bool ok = MetricsReadings(rs, &out, false);
  jsonbuf_append(&out, "# HELP lcars_reading_timestamp_seconds When the "
                       "latest reading of each kind was measured.\n"
                       "# TYPE lcars_reading_timestamp_seconds gauge\n");
  ok = ok && MetricsReadings(rs, &out, true);
  jsonbuf_append(&out, "# HELP lcars_entries_total Live (not deleted) "
                       "entries of each kind.\n"
                       "# TYPE lcars_entries_total gauge\n");
  while (ok && (rc = sqlite3_step(cs)) == SQLITE_ROW) {
    jsonbuf_append(&out, "lcars_entries_total{kind=\"");
    MetricsAppendLabel(&out, (const char *)sqlite3_column_text(cs, 0));
    jsonbuf_appendf(&out, "\"} %lld\n", (long long)sqlite3_column_int64(cs, 1));
  }
  ok = ok && rc == SQLITE_DONE;
  if (ok) {
    MetricsAppendEng(&out);
  }

  int status;
  if (!ok) {
    status = SendJSONError(client_fd, 500, "Metrics query failed: %s",
                           sqlite3_errmsg(db));
  } else if (out.overflow) {
    status = SendJSONError(client_fd, 500, "Metrics too large to send");
  } else {
    status = SendHTTPResponse(client_fd, 200,
                              "text/plain; version=0.0.4; charset=utf-8",
                              out.data ? out.data : "", out.len);
  }
  sqlite3_finalize(rs);
  sqlite3_finalize(cs);
  sqlite3_close(db);
  return status;
}

#endif // LCARS_METRICS_IMPLEMENTATION
#endif // LCARS_METRICS_H
