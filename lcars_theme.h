#ifndef LCARS_THEME_H
#define LCARS_THEME_H

// The console's theme (docs/design/theming.md 5 and 6): which palette the
// web console wears, on every device, set from the page, from lcars-cli or
// from a tool outside (omarchy's theme-set hook, scripts/omarchy/).
//
// The choice lives in the journal, as the one `settings` entry titled
// `theme` (the lowest live id, as with `kinds` and `views`):
//
//   {"v":1,"name":"nord","fmt":"builtin","text":""}
//   {"v":1,"name":"rose-pine","fmt":"omarchy","text":"accent = \"#...\"\n…"}
//
// A built-in is a name alone: one of the page's own btop files,
// lcars-ui/themes/<name>.theme, which must be there (on disk or in the
// embedded pack) for a PUT to take it; `lcars` is the default, :root as
// written. Any other theme is carried whole: the file's text, btop's
// `*.theme` or omarchy's `colors.toml`, as it was handed in. This server
// checks only its size and its shape (a `theme[` line, or a `key = "#hex"`
// line, the two tests themeParse in the page starts from); the parsing and
// the mapping onto the tokens are the page's alone, so there is one table
// and it is in one place. The page follows the entry as it follows any
// row (GET /events, the delta sync), so a theme set here reaches an open
// console in a second or two.
//
//   GET /theme   {"name":"nord","fmt":"builtin","text":"","entry":<id or
//                null>,"error":""}; no entry is lcars. `error` says what in
//                the entry could not be read (it is then lcars).
//   PUT /theme   the owner's login only. Either a JSON object
//                {"name":"nord"} (a built-in) or {"name":"N","text":"…"} (a
//                file's text), or the file itself as a non-JSON body
//                (text/plain) with ?name=N (default "custom"). Answers as
//                GET. {"name":"lcars"} is back to the default.
//
// The limited logins read it (a crew script may want to know) and may not
// write it: PUT falls to LimitedAllowed's refusal, as every route it does
// not name does, and the steward writes no `settings` entry at all.
//
// A module of lcars_http.h, included from inside its implementation block
// after lcars_ui_files.h, whose UIOpenSrc says whether a built-in exists.

#include <sqlite3.h>
#include <stdbool.h>
#include <stddef.h>

// The settings entry that holds the choice
#define THEME_ENTRY_KIND "settings"
#define THEME_ENTRY_TITLE "theme"
// A theme file's text, at most: btop's are 3-4 KB, omarchy's under 1 KB
#define THEME_TEXT_MAX (64 * 1024)
// A theme's name with its NUL
#define THEME_NAME_MAX 65

static int HandleTheme(int client_fd, Arena *arena, const char *method,
                       const char *query, const char *body,
                       const char *content_type);

#ifdef LCARS_THEME_IMPLEMENTATION

#include <string.h>

// A name: 1 to THEME_NAME_MAX-1 bytes of letters, digits, '-', '_', '.' and
// spaces, not starting with a dot or a space. It is a file's name for a
// built-in (so nothing that climbs a directory), and shown in the picker.
static bool ThemeNameOK(const char *name) {
  assert(name != NULL);
  size_t n = strlen(name);
  if (n == 0 || n >= THEME_NAME_MAX || name[0] == '.' || name[0] == ' ') {
    return false;
  }
  for (size_t i = 0; i < n; i++) {
    char c = name[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' ||
          c == ' ')) {
      return false;
    }
  }
  return true;
}

// A built-in: lcars, or a file the page can fetch from themes/
static bool ThemeIsBuiltin(const char *name) {
  assert(name != NULL);
  if (strcmp(name, "lcars") == 0) {
    return true;
  }
  if (!ThemeNameOK(name) || strchr(name, ' ') != NULL) {
    return false;
  }
  char rel[THEME_NAME_MAX + 16], full[1024];
  snprintf(rel, sizeof(rel), "themes/%s.theme", name);
  UISrc src;
  if (!UIOpenSrc(rel, full, sizeof(full), &src)) {
    return false;
  }
  UISrcClose(&src);
  return true;
}

// The file's format by its shape, or NULL when it is no theme file: btop's
// when a line starts `theme[`, else omarchy's when a line is `key = "#…"`
// (or single quotes) - themeParse's own first tests, so what this takes
// the page can read. Control bytes but tab, CR and LF refuse it: a file of
// colours has none, and this text is shown in the editor.
static const char *ThemeTextFmt(const char *text) {
  assert(text != NULL);
  for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
    if ((*p < 0x20 && *p != '\t' && *p != '\r' && *p != '\n') || *p == 0x7f) {
      return NULL;
    }
  }
  bool omarchy = false;
  for (const char *line = text; line && *line;) {
    const char *p = line;
    while (*p == ' ' || *p == '\t') {
      p++;
    }
    if (strncmp(p, "theme[", 6) == 0) {
      return "btop";
    }
    const char *k = p;
    while ((*p >= 'a' && *p <= 'z') || *p == '_') {
      p++;
    }
    if (p > k) {
      while (*p == ' ' || *p == '\t') {
        p++;
      }
      if (*p == '=') {
        p++;
        while (*p == ' ' || *p == '\t') {
          p++;
        }
        if ((*p == '"' || *p == '\'') && p[1] == '#' &&
            ((p[2] >= '0' && p[2] <= '9') || (p[2] >= 'a' && p[2] <= 'f') ||
             (p[2] >= 'A' && p[2] <= 'F'))) {
          omarchy = true; // a btop line later still makes it btop's
        }
      }
    }
    line = strchr(line, '\n');
    line = line ? line + 1 : NULL;
  }
  return omarchy ? "omarchy" : NULL;
}

// The entry, as read: its id (0: none), and what it says, unescaped into
// the arena. A missing or unreadable entry is lcars, with `error` for the
// latter.
typedef struct ThemeEntry {
  int id;
  bool json; // the content is a JSON object (a PUT may rewrite it)
  const char *name, *fmt, *text;
  char error[160];
} ThemeEntry;

static bool ThemeRead(sqlite3 *db, Arena *arena, ThemeEntry *e) {
  assert(db != NULL && e != NULL);
  memset(e, 0, sizeof(*e));
  e->name = "lcars";
  e->fmt = "builtin";
  e->text = "";
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT id, content FROM entries WHERE kind = ?1 AND "
                         "title = ?2 AND (deleted IS NULL OR deleted = 0) "
                         "ORDER BY id LIMIT 1;",
                         -1, &st, NULL) != SQLITE_OK) {
    sqlite3_finalize(st);
    return false;
  }
  sqlite3_bind_text(st, 1, THEME_ENTRY_KIND, -1, SQLITE_STATIC);
  sqlite3_bind_text(st, 2, THEME_ENTRY_TITLE, -1, SQLITE_STATIC);
  int rc = sqlite3_step(st);
  if (rc != SQLITE_ROW) {
    sqlite3_finalize(st);
    return rc == SQLITE_DONE;
  }
  e->id = sqlite3_column_int(st, 0);
  const char *c = (const char *)sqlite3_column_text(st, 1);
  size_t len = (size_t)sqlite3_column_bytes(st, 1);
  const char *end = c ? c + len : NULL;
  const char *start = c ? json_skip_ws(c, end) : NULL;
  const char *after = start ? json_scan_value(start, end) : NULL;
  JsonSpan v;
  if (len > THEME_TEXT_MAX * 2) {
    snprintf(e->error, sizeof(e->error), "the theme entry #%d is over %d bytes",
             e->id, THEME_TEXT_MAX * 2);
  } else if (!after || *start != '{' || json_skip_ws(after, end) != end) {
    snprintf(e->error, sizeof(e->error),
             "the theme entry #%d is not a JSON object", e->id);
  } else {
    e->json = true;
    JsonSpan obj = {start, (size_t)(after - start)};
    const char *name = json_member(obj, "name", &v) && v.data[0] == '"'
                           ? json_span_string(arena, v)
                           : "";
    const char *text = json_member(obj, "text", &v) && v.data[0] == '"'
                           ? json_span_string(arena, v)
                           : "";
    const char *fmt = text[0] ? ThemeTextFmt(text) : "builtin";
    if (!ThemeNameOK(name)) {
      snprintf(e->error, sizeof(e->error),
               "the theme entry #%d: name is not a theme's name", e->id);
    } else if (fmt == NULL) {
      snprintf(e->error, sizeof(e->error),
               "the theme entry #%d: text is not a btop or omarchy theme",
               e->id);
    } else {
      e->name = name;
      e->fmt = fmt;
      e->text = text;
    }
  }
  sqlite3_finalize(st);
  return true;
}

static int ThemeAnswer(int client_fd, Arena *arena, sqlite3 *db) {
  assert(client_fd >= 0 && db != NULL);
  ThemeEntry e;
  if (!ThemeRead(db, arena, &e)) {
    return SendJSONError(client_fd, 500, "Failed to read the theme entry: %s",
                         sqlite3_errmsg(db));
  }
  JSONBuf b;
  jsonbuf_init(&b, arena);
  jsonbuf_append(&b, "{\"name\":");
  jsonbuf_append_json_string(&b, e.name);
  jsonbuf_append(&b, ",\"fmt\":");
  jsonbuf_append_json_string(&b, e.fmt);
  jsonbuf_append(&b, ",\"text\":");
  jsonbuf_append_json_string(&b, e.text);
  if (e.id > 0) {
    jsonbuf_appendf(&b, ",\"entry\":%d,\"error\":", e.id);
  } else {
    jsonbuf_append(&b, ",\"entry\":null,\"error\":");
  }
  jsonbuf_append_json_string(&b, e.error);
  jsonbuf_append(&b, "}");
  if (b.overflow) {
    return SendJSONError(client_fd, 500, "the theme does not fit");
  }
  return SendJSONBuf(client_fd, &b);
}

// PUT /theme: the name and the text taken from either body, checked, then
// the entry written (or made) in one transaction.
static int ThemePut(int client_fd, Arena *arena, sqlite3 *db, const char *query,
                    const char *body, const char *content_type) {
  assert(client_fd >= 0 && db != NULL && content_type != NULL);
  const char *b = body ? body : "";
  size_t blen = strlen(b);
  if (blen > THEME_TEXT_MAX) {
    return SendJSONError(client_fd, 413, "a theme is at most 64 KB (%d bytes)",
                         THEME_TEXT_MAX);
  }
  const char *name = "custom", *text = "";
  if (strstr(content_type, "application/json") != NULL) {
    const char *end = b + blen;
    const char *start = json_skip_ws(b, end);
    const char *after = json_scan_value(start, end);
    JsonSpan obj, v;
    if (!after || *start != '{' || json_skip_ws(after, end) != end ||
        !json_member(obj = (JsonSpan){start, (size_t)(after - start)}, "name",
                     &v) ||
        v.data[0] != '"') {
      return SendJSONError(client_fd, 400,
                           "the body is {\"name\":\"…\"} (a built-in) or "
                           "{\"name\":\"…\",\"text\":\"…\"} (a theme file)");
    }
    name = json_span_string(arena, v);
    if (json_member(obj, "text", &v) && v.data[0] == '"') {
      text = json_span_string(arena, v);
    } else if (json_member(obj, "text", &v) &&
               !(v.len == 4 && memcmp(v.data, "null", 4) == 0)) {
      return SendJSONError(client_fd, 400, "text is a string");
    }
  } else {
    char q[THEME_NAME_MAX * 3 + 1];
    if (query && query_get(query, "name", q, sizeof(q)) && q[0] != '\0') {
      char *n = (char *)arena_alloc(arena, strlen(q) + 1);
      memcpy(n, q, strlen(q) + 1);
      name = n;
    }
    text = b;
    if (text[0] == '\0') {
      return SendJSONError(client_fd, 400,
                           "no theme in the body: a btop *.theme or an "
                           "omarchy colors.toml, or JSON {\"name\":\"…\"}");
    }
  }
  if (!ThemeNameOK(name)) {
    return SendJSONError(
        client_fd, 400,
        "a theme's name is 1 to %d letters, digits, '-', '_', '.' or "
        "spaces, not starting with a dot or a space",
        THEME_NAME_MAX - 1);
  }
  const char *fmt = "builtin";
  if (text[0] == '\0') {
    if (!ThemeIsBuiltin(name)) {
      return SendJSONError(client_fd, 400,
                           "no built-in theme %s (hand in its file's text "
                           "for one of your own)",
                           name);
    }
  } else if ((fmt = ThemeTextFmt(text)) == NULL) {
    return SendJSONError(client_fd, 400,
                         "not a theme file: neither btop's theme[key]=\"…\" "
                         "lines nor omarchy's key = \"#rrggbb\" ones");
  }

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"v\":1,\"name\":");
  jsonbuf_append_json_string(&out, name);
  jsonbuf_append(&out, ",\"fmt\":");
  jsonbuf_append_json_string(&out, fmt);
  jsonbuf_append(&out, ",\"text\":");
  jsonbuf_append_json_string(&out, text);
  jsonbuf_append(&out, "}");
  if (out.overflow) {
    return SendJSONError(client_fd, 500, "the theme does not fit");
  }

  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    return SendJSONError(client_fd, 503, "the journal is busy: %s",
                         sqlite3_errmsg(db));
  }
  ThemeEntry e;
  if (!ThemeRead(db, arena, &e)) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return SendJSONError(client_fd, 500, "Failed to read the theme entry");
  }
  if (e.id > 0 && !e.json) {
    // not JSON: the owner's own text, never overwritten by a machine
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return SendJSONError(client_fd, 409, "%s: fix or delete it first", e.error);
  }
  sqlite3_stmt *st = NULL;
  const char *sql =
      e.id > 0 ? "UPDATE entries SET content = ?1, last_modified_at_utc = "
                 "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?2;"
               : "INSERT INTO entries (kind, title, content) VALUES (?3, ?4, "
                 "?1);";
  bool ok = sqlite3_prepare_v2(db, sql, -1, &st, NULL) == SQLITE_OK;
  if (ok) {
    sqlite3_bind_text(st, 1, out.data, (int)out.len, SQLITE_STATIC);
    if (e.id > 0) {
      sqlite3_bind_int(st, 2, e.id);
    } else {
      sqlite3_bind_text(st, 3, THEME_ENTRY_KIND, -1, SQLITE_STATIC);
      sqlite3_bind_text(st, 4, THEME_ENTRY_TITLE, -1, SQLITE_STATIC);
    }
    ok = sqlite3_step(st) == SQLITE_DONE;
  }
  sqlite3_finalize(st);
  if (!ok || sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to write the theme: %s",
                               sqlite3_errmsg(db));
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return status;
  }
  return ThemeAnswer(client_fd, arena, db);
}

static int HandleTheme(int client_fd, Arena *arena, const char *method,
                       const char *query, const char *body,
                       const char *content_type) {
  assert(client_fd >= 0 && arena_valid(arena) && method != NULL);
  bool get = strcmp(method, "GET") == 0;
  if (!get && strcmp(method, "PUT") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on /theme",
                         method);
  }
  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  int status = get ? ThemeAnswer(client_fd, arena, db)
                   : ThemePut(client_fd, arena, db, query, body,
                              content_type ? content_type : "");
  sqlite3_close(db);
  return status;
}

#endif // LCARS_THEME_IMPLEMENTATION
#endif // LCARS_THEME_H
