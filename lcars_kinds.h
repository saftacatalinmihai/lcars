#ifndef LCARS_KINDS_H
#define LCARS_KINDS_H

// Kinds by role (docs/design/kinds.md): what a feature writes and reads is
// a role, and the journal's owner says which kind each role is.
//
// A feature that needs a kind (where the nap chip writes, what CalDAV
// publishes as tasks, what the Strava pull files workouts under) names a
// role from the table below, never the kind itself. Each role has a plain
// default, the kind a new journal uses; the owner may point a role at a
// kind of their own - the captain's journal keeps the names it always had,
// and no row is ever renamed for it.
//
// The mapping lives in the journal, as the one `settings` entry titled
// `kinds` (the lowest live id, as with the page's `views` entry):
//
//   {"v":1,"roles":{"child_sleep":{"kind":"naps","name":"Ada"},
//                   "imported":{"kind":"logseq_journal,other_journal"}}}
//
// A role it does not name is its default. `name` is the words a feature
// says for the role (the nap chip's "<name>'s nap"). A list role (`imported`)
// holds its kinds comma-joined. A role this build does not know is kept as
// it is on every write, so a newer build's mapping survives an older one.
//
// It is read on every use, never cached: these routes are rare (a CalDAV
// sync, a Strava pull, a chat turn, a boot of the page), the scan is one
// SELECT over a few thousand rows (entries has no index on kind), and an
// entry edited by hand applies on the next request.
//
//   GET /kinds/roles   every role in the table's order:
//     {"roles":[{"role":"child_sleep","what":"…","kind":"child_sleep",
//                "kinds":["child_sleep"],"default":"child_sleep","list":false,
//                "set":false,"name":"","rows":0},…],
//      "entry":<id or null>,"error":""}
//     `error` says what in the entry this server could not read; a role it
//     touches is its default (the entry not JSON: every role).
//   PUT /kinds/roles   the owner's login only: {"<role>":{"kind":"…",
//     "name":"…"}, "<role>":null, …}, null back to the default. All or
//     nothing; answers as GET.
//
// The limited logins read the mapping (the crew's scripts need it) and may
// not write it: PUT falls to LimitedAllowed's refusal, and the steward may
// write no `settings` entry at all (StewardMayWriteKind), so no crew role
// can redirect where the captain's rows go.
//
// The app's own kinds (`settings`, which holds this, `space`,
// `holo_program`, and the logins' namespaces) are not roles and no role may
// be pointed at one (KindIsAppOwn): they are the app's protocol, and a
// mapping onto a login's kind would hand it the owner's rows.
//
// A module of lcars_http.h, included from inside its implementation block
// ahead of the modules that read a role (CalDAV, the logins, Strava, chat).

#include <sqlite3.h>
#include <stdbool.h>
#include <stddef.h>

// The settings entry that holds the mapping
#define KINDS_ENTRY_KIND "settings"
#define KINDS_ENTRY_TITLE "kinds"
// A kind's bytes with its NUL: the handlers read `kind` into 128
#define KIND_MAX 128
// A list role's kinds, comma-joined, with the NUL
#define KIND_LIST_MAX 1024
// A role's name (the words a feature says for it), with the NUL
#define KIND_NAME_MAX 64

typedef struct KindRole {
  const char *role; // the slug features name
  const char *def;  // the kind a new journal uses
  const char *what; // what the role is for, for the Config page and the CLI
  bool list;        // several kinds, comma-joined
} KindRole;

// The roles, in the order GET /kinds/roles answers them. The page keeps a
// copy for its first paint (docs/design/kinds.md 3.2); a test holds the two
// equal.
static const KindRole g_kind_roles[] = {
    {"log", "personal_log",
     "a new entry: the editor, the calendar, quick capture, the computer",
     false},
    {"work_log", "work_log",
     "a second log read as the first: read-aloud's date, the linker", false},
    {"task", "task",
     "tasks: CalDAV's lists (<kind>_<list>), the Task button, the computer",
     false},
    {"sleep", "sleep", "sleep: the linker's hours, the stats, counsel", false},
    {"child_sleep", "child_sleep",
     "a child's sleep: the nap chip, the linker, the stats", false},
    {"child_vocab", "child_vocab",
     "a child's new words: the linker's count, the stats", false},
    {"drive", "drive", "drives: the day map, the linker, the trip retros",
     false},
    {"trip", "trip", "trips: the courses, the agenda's weather, the retros",
     false},
    {"workout", "workout", "workouts: the Strava pull", false},
    {"counter", "counter", "counters: \"log a diaper\", the stats", false},
    {"share", "share", "shares: the shares role's places", false},
    {"page", "page", "pages: the Logseq import, wiki links, the linker", false},
    {"person", "person", "people: the linker, the stats", false},
    {"project", "project", "projects: the linker", false},
    {"meeting", "meeting", "meetings: the linker, the crew's prose", false},
    {"template", "template", "templates: the template picker", false},
    {"logseq_journal", "logseq_journal", "the Logseq import's journal days",
     false},
    {"imported", "logseq_journal",
     "kinds only an import writes: frozen for the crew", true},
};
#define KIND_ROLE_COUNT (sizeof(g_kind_roles) / sizeof(g_kind_roles[0]))

static const KindRole *KindRoleNamed(const char *role);
static bool KindIsAppOwn(const char *kind);
static bool KindFor(sqlite3 *db, const char *role, char *out, size_t size);
static int HandleKindRoles(int client_fd, Arena *arena, const char *method,
                           const char *body);

#ifdef LCARS_KINDS_IMPLEMENTATION

#include <string.h>

// The entry's content past this is not read: a mapping is a few hundred
// bytes, and the request arena is 1MB.
#define KINDS_CONTENT_MAX (64 * 1024)

static const KindRole *KindRoleNamed(const char *role) {
  assert(role != NULL);
  for (size_t i = 0; i < KIND_ROLE_COUNT; i++) {
    if (strcmp(g_kind_roles[i].role, role) == 0) {
      return &g_kind_roles[i];
    }
  }
  return NULL;
}

// `kind` is the app's own (docs/design/kinds.md 2.3): the settings that
// hold this mapping, the deck's, and every limited login's namespace -
// <o>_* and task_<o>[_*] for the three owners, whether or not the login is
// configured on this box (it may be tomorrow, and find its kinds taken).
static bool KindIsAppOwn(const char *kind) {
  assert(kind != NULL);
  static const char *const fixed[] = {KINDS_ENTRY_KIND, "space",
                                      "holo_program"};
  static const char *const owners[] = {"crew", "no1", "steward"};
  for (size_t i = 0; i < sizeof(fixed) / sizeof(fixed[0]); i++) {
    if (strcmp(kind, fixed[i]) == 0) {
      return true;
    }
  }
  for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) {
    size_t n = strlen(owners[i]);
    const char *k = kind;
    if (strncmp(k, "task_", 5) == 0) {
      k += 5;
    }
    if (strncmp(k, owners[i], n) == 0 && (k[n] == '\0' || k[n] == '_')) {
      return true;
    }
  }
  return false;
}

// `kind` is <task>_<o> or <task>_<o>_* for a login's owner <o>: the
// reminders a limited login owns (lcars_logins.h, LimitedOwnsKind) under
// the task kind `task`. KindIsAppOwn covers the default task kind; this,
// whatever the mapping makes it.
static bool KindIsLoginTask(const char *task, const char *kind, size_t len) {
  assert(task != NULL && kind != NULL);
  static const char *const owners[] = {"crew", "no1", "steward"};
  size_t t = strlen(task);
  if (len <= t || strncmp(kind, task, t) != 0 || kind[t] != '_') {
    return false;
  }
  for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) {
    size_t n = strlen(owners[i]);
    if (len >= t + 1 + n && strncmp(kind + t + 1, owners[i], n) == 0 &&
        (len == t + 1 + n || kind[t + 1 + n] == '_')) {
      return true;
    }
  }
  return false;
}

// One kind: [a-z0-9_], 1 to KIND_MAX-1 bytes, not the app's own. On a
// refusal `why` says which rule, for the 400.
static bool KindSlugOK(const char *kind, size_t len, char *why,
                       size_t why_size) {
  assert(kind != NULL && why != NULL && why_size > 0);
  if (len == 0 || len >= KIND_MAX) {
    snprintf(why, why_size, "a kind is 1 to %d bytes", KIND_MAX - 1);
    return false;
  }
  for (size_t i = 0; i < len; i++) {
    char c = kind[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) {
      snprintf(why, why_size, "a kind is lowercase letters, digits and _");
      return false;
    }
  }
  char k[KIND_MAX];
  memcpy(k, kind, len);
  k[len] = '\0';
  if (KindIsAppOwn(k)) {
    snprintf(why, why_size, "%.48s is the app's own kind", k);
    return false;
  }
  return true;
}

// A role's kind as stored: one slug, or for a list role slugs joined by
// commas (no empty item, no spaces).
static bool KindValueOK(const KindRole *r, const char *v, char *why,
                        size_t why_size) {
  assert(r != NULL && v != NULL);
  size_t total = strlen(v);
  if (total >= (r->list ? KIND_LIST_MAX : KIND_MAX)) {
    snprintf(why, why_size, "too long");
    return false;
  }
  if (!r->list) {
    return KindSlugOK(v, total, why, why_size);
  }
  const char *p = v;
  for (;;) {
    const char *comma = strchr(p, ',');
    size_t len = comma ? (size_t)(comma - p) : strlen(p);
    if (!KindSlugOK(p, len, why, why_size)) {
      return false;
    }
    if (!comma) {
      return true;
    }
    p = comma + 1;
  }
}

// A name: up to KIND_NAME_MAX-1 bytes of text with no control byte (it is
// shown, and the page builds a pattern from it - escaping there).
static bool KindNameOK(const char *name, char *why, size_t why_size) {
  assert(name != NULL);
  if (strlen(name) >= KIND_NAME_MAX) {
    snprintf(why, why_size, "a name is at most %d bytes", KIND_NAME_MAX - 1);
    return false;
  }
  for (const unsigned char *p = (const unsigned char *)name; *p; p++) {
    if (*p < 0x20 || *p == 0x7f) {
      snprintf(why, why_size, "a name has no control characters");
      return false;
    }
  }
  return true;
}

// The mapping entry, as read: its id (0: none), and its `roles` object when
// the content is one this server can read. The spans point into the
// statement's row, so they live until KindsClose.
typedef struct KindsEntry {
  sqlite3_stmt *stmt;
  int id;
  JsonSpan content;
  JsonSpan roles; // len 0: no roles object (no entry, or `error` says why)
  char error[160];
} KindsEntry;

static void KindsClose(KindsEntry *e) {
  assert(e != NULL);
  sqlite3_finalize(e->stmt);
  e->stmt = NULL;
}

// Reads the mapping entry. False only when the query itself fails (the
// database's fault); a missing or unreadable entry is true, with `error`.
static bool KindsOpen(sqlite3 *db, KindsEntry *e) {
  assert(db != NULL && e != NULL);
  memset(e, 0, sizeof(*e));
  if (sqlite3_prepare_v2(db,
                         "SELECT id, content FROM entries WHERE kind = ?1 AND "
                         "title = ?2 AND (deleted IS NULL OR deleted = 0) "
                         "ORDER BY id LIMIT 1;",
                         -1, &e->stmt, NULL) != SQLITE_OK) {
    sqlite3_finalize(e->stmt);
    e->stmt = NULL;
    return false;
  }
  sqlite3_bind_text(e->stmt, 1, KINDS_ENTRY_KIND, -1, SQLITE_STATIC);
  sqlite3_bind_text(e->stmt, 2, KINDS_ENTRY_TITLE, -1, SQLITE_STATIC);
  int rc = sqlite3_step(e->stmt);
  if (rc == SQLITE_DONE) {
    return true;
  }
  if (rc != SQLITE_ROW) {
    KindsClose(e);
    return false;
  }
  e->id = sqlite3_column_int(e->stmt, 0);
  const char *c = (const char *)sqlite3_column_text(e->stmt, 1);
  size_t len = (size_t)sqlite3_column_bytes(e->stmt, 1);
  const char *end = c ? c + len : NULL;
  const char *start = c ? json_skip_ws(c, end) : NULL;
  const char *after = start ? json_scan_value(start, end) : NULL;
  JsonSpan roles = {0};
  if (len > KINDS_CONTENT_MAX) {
    snprintf(e->error, sizeof(e->error), "the kinds entry #%d is over %d bytes",
             e->id, KINDS_CONTENT_MAX);
  } else if (!after || *start != '{' || json_skip_ws(after, end) != end) {
    snprintf(e->error, sizeof(e->error),
             "the kinds entry #%d is not a JSON object", e->id);
  } else {
    e->content = (JsonSpan){start, (size_t)(after - start)};
    if (json_member(e->content, "roles", &roles) && roles.len > 0 &&
        roles.data[0] == '{') {
      e->roles = roles;
    } else if (json_member(e->content, "roles", &roles)) {
      snprintf(e->error, sizeof(e->error),
               "the kinds entry #%d: roles is not an object", e->id);
    } // no roles at all: an empty mapping, not an error
  }
  return true;
}

// Copies a JSON string span's text into out; false if it is not a string
// or does not fit.
static bool KindsSpanText(JsonSpan v, char *out, size_t size) {
  assert(out != NULL && size > 0);
  out[0] = '\0';
  if (v.len < 2 || v.data[0] != '"') {
    return false;
  }
  // json_unescape writes at most the source's bytes, so a source that fits
  // is a result that fits
  if (v.len - 2 >= size) {
    return false;
  }
  json_unescape(v.data + 1, v.data + v.len - 1, out, size);
  return true;
}

// One role as the entry sets it. *set says the entry names the role and
// what it says is good; otherwise kind is the default and name empty, and
// a bad value is said in err (if given).
static void KindsLookup(const KindsEntry *e, const KindRole *r, char *kind,
                        size_t kind_size, char *name, size_t name_size,
                        bool *set, char *err, size_t err_size) {
  assert(e != NULL && r != NULL && kind != NULL && set != NULL);
  *set = false;
  snprintf(kind, kind_size, "%s", r->def);
  if (name) {
    name[0] = '\0';
  }
  JsonSpan v;
  if (e->roles.len == 0 || !json_member(e->roles, r->role, &v) ||
      (v.len == 4 && memcmp(v.data, "null", 4) == 0)) {
    return;
  }
  char k[KIND_LIST_MAX], n[KIND_NAME_MAX], why[96] = "";
  JsonSpan ks, ns;
  bool ok = v.len > 0 && v.data[0] == '{';
  if (!ok) {
    snprintf(why, sizeof(why), "not an object");
  } else if (!json_member(v, "kind", &ks)) {
    snprintf(k, sizeof(k), "%s", r->def); // a name alone: the default kind
  } else if (!KindsSpanText(ks, k, sizeof(k))) {
    ok = false;
    snprintf(why, sizeof(why), "kind is not a string that fits");
  } else {
    ok = KindValueOK(r, k, why, sizeof(why));
  }
  n[0] = '\0';
  if (ok && json_member(v, "name", &ns) &&
      !(ns.len == 4 && memcmp(ns.data, "null", 4) == 0)) {
    if (!KindsSpanText(ns, n, sizeof(n))) {
      ok = false;
      snprintf(why, sizeof(why), "name is not a string that fits");
    } else {
      ok = KindNameOK(n, why, sizeof(why));
    }
  }
  if (!ok) {
    if (err && err[0] == '\0') {
      snprintf(err, err_size, "the kinds entry #%d: %s: %s", e->id, r->role,
               why);
    }
    return;
  }
  *set = true;
  snprintf(kind, kind_size, "%s", k);
  if (name) {
    snprintf(name, name_size, "%s", n);
  }
}

// The kind `role` is on this journal: the mapping's, else the default.
// True when the mapping set it. A role not in the table is a programmer
// error. A database that cannot be read gives the default: the features
// asking would rather write where a new journal writes than nowhere.
static bool KindFor(sqlite3 *db, const char *role, char *out, size_t size) {
  assert(db != NULL && out != NULL && size > 0);
  const KindRole *r = KindRoleNamed(role);
  assert(r != NULL && "a role not in g_kind_roles");
  KindsEntry e;
  if (!KindsOpen(db, &e)) {
    snprintf(out, size, "%s", r->def);
    return false;
  }
  bool set = false;
  KindsLookup(&e, r, out, size, NULL, 0, &set, NULL, 0);
  KindsClose(&e);
  return set;
}

// The live rows of each kind, to say beside a role how much it holds
typedef struct KindCount {
  char kind[KIND_MAX];
  int rows;
} KindCount;

static int KindRows(const KindCount *counts, int n, const char *kind,
                    size_t len) {
  for (int i = 0; i < n; i++) {
    if (strlen(counts[i].kind) == len &&
        memcmp(counts[i].kind, kind, len) == 0) {
      return counts[i].rows;
    }
  }
  return 0;
}

static int KindsAnswer(int client_fd, Arena *arena, sqlite3 *db) {
  assert(client_fd >= 0 && db != NULL);
  KindsEntry e;
  if (!KindsOpen(db, &e)) {
    return SendJSONError(client_fd, 500, "Failed to read the kinds entry: %s",
                         sqlite3_errmsg(db));
  }
  // the counts, for the role kinds only: at most every kind of every role
  enum { COUNTS_MAX = 256 };
  KindCount *counts =
      (KindCount *)arena_alloc(arena, sizeof(KindCount) * COUNTS_MAX);
  int n_counts = 0;
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(db,
                         "SELECT kind, COUNT(*) FROM entries WHERE deleted IS "
                         "NULL OR deleted = 0 GROUP BY kind;",
                         -1, &st, NULL) == SQLITE_OK) {
    while (sqlite3_step(st) == SQLITE_ROW && n_counts < COUNTS_MAX) {
      const char *k = (const char *)sqlite3_column_text(st, 0);
      if (k && strlen(k) < KIND_MAX) {
        snprintf(counts[n_counts].kind, KIND_MAX, "%s", k);
        counts[n_counts].rows = sqlite3_column_int(st, 1);
        n_counts++;
      }
    }
  }
  sqlite3_finalize(st);

  char error[160];
  snprintf(error, sizeof(error), "%s", e.error);
  JSONBuf b;
  jsonbuf_init(&b, arena);
  jsonbuf_append(&b, "{\"roles\":[");
  for (size_t i = 0; i < KIND_ROLE_COUNT; i++) {
    const KindRole *r = &g_kind_roles[i];
    char kind[KIND_LIST_MAX], name[KIND_NAME_MAX];
    bool set = false;
    KindsLookup(&e, r, kind, sizeof(kind), name, sizeof(name), &set, error,
                sizeof(error));
    jsonbuf_append(&b, i ? ",{\"role\":" : "{\"role\":");
    jsonbuf_append_json_string(&b, r->role);
    jsonbuf_append(&b, ",\"what\":");
    jsonbuf_append_json_string(&b, r->what);
    jsonbuf_append(&b, ",\"kind\":");
    jsonbuf_append_json_string(&b, kind);
    jsonbuf_append(&b, ",\"kinds\":[");
    int rows = 0;
    for (const char *p = kind, *comma; p; p = comma ? comma + 1 : NULL) {
      comma = strchr(p, ',');
      size_t len = comma ? (size_t)(comma - p) : strlen(p);
      char one[KIND_MAX];
      snprintf(one, sizeof(one), "%.*s", (int)len, p);
      jsonbuf_append(&b, p == kind ? "" : ",");
      jsonbuf_append_json_string(&b, one);
      rows += KindRows(counts, n_counts, p, len);
    }
    jsonbuf_append(&b, "],\"default\":");
    jsonbuf_append_json_string(&b, r->def);
    jsonbuf_appendf(&b, ",\"list\":%s,\"set\":%s,\"name\":",
                    r->list ? "true" : "false", set ? "true" : "false");
    jsonbuf_append_json_string(&b, name);
    jsonbuf_appendf(&b, ",\"rows\":%d}", rows);
  }
  if (e.id > 0) {
    jsonbuf_appendf(&b, "],\"entry\":%d,\"error\":", e.id);
  } else {
    jsonbuf_append(&b, "],\"entry\":null,\"error\":");
  }
  jsonbuf_append_json_string(&b, error);
  jsonbuf_append(&b, "}");
  KindsClose(&e);
  return SendJSONBuf(client_fd, &b);
}

// PUT /kinds/roles: the body's roles checked, every one, before anything is
// written; then the entry's roles object rebuilt - the table's roles in its
// order (set ones only), then whatever else the entry held, as it was - and
// written back, or a new entry made when there is none. One transaction, so
// two writers cannot each keep half.
static int KindsPut(int client_fd, Arena *arena, sqlite3 *db,
                    const char *body) {
  assert(client_fd >= 0 && db != NULL);
  const char *b = body ? body : "";
  const char *end = b + strlen(b);
  const char *start = json_skip_ws(b, end);
  const char *after = json_scan_value(start, end);
  if (!after || *start != '{' || json_skip_ws(after, end) != end) {
    return SendJSONError(
        client_fd, 400,
        "the body is a JSON object of roles: "
        "{\"<role>\":{\"kind\":\"…\",\"name\":\"…\"} or null}");
  }
  JsonSpan req = {start, (size_t)(after - start)};
  const char *cur = NULL;
  JsonSpan k, v;
  int n = 0;
  while (json_object_next(req, &cur, &k, &v)) {
    char role[48];
    snprintf(role, sizeof(role), "%.*s", (int)(k.len < 47 ? k.len : 47),
             k.data);
    const KindRole *r = k.len < 47 ? KindRoleNamed(role) : NULL;
    if (r == NULL) {
      return SendJSONError(client_fd, 400, "no role %s (GET /kinds/roles)",
                           role);
    }
    n++;
    if (v.len == 4 && memcmp(v.data, "null", 4) == 0) {
      continue;
    }
    // a one-member mapping run through the reader's own checks, so what
    // PUT takes is exactly what GET will read back
    KindsEntry one = {0};
    one.roles = req;
    char kind[KIND_LIST_MAX], err[160] = "";
    bool set = false;
    JsonSpan ks;
    if (v.len == 0 || v.data[0] != '{' || !json_member(v, "kind", &ks)) {
      return SendJSONError(client_fd, 400,
                           "%s: {\"kind\":\"…\",\"name\":\"…\"} or null", role);
    }
    KindsLookup(&one, r, kind, sizeof(kind), NULL, 0, &set, err, sizeof(err));
    if (!set) {
      const char *why = strstr(err, ": ");
      return SendJSONError(client_fd, 400, "%s", why ? why + 2 : role);
    }
  }
  if (n == 0) {
    return SendJSONError(client_fd, 400, "no role to set");
  }

  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    return SendJSONError(client_fd, 503, "the journal is busy: %s",
                         sqlite3_errmsg(db));
  }
  KindsEntry e;
  if (!KindsOpen(db, &e)) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return SendJSONError(client_fd, 500, "Failed to read the kinds entry");
  }
  if (e.id > 0 && e.content.len == 0) {
    // not JSON: the owner's own text, never overwritten by a machine
    int status =
        SendJSONError(client_fd, 409, "%s: fix or delete it first", e.error);
    KindsClose(&e);
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return status;
  }

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"v\":1,\"roles\":{");
  bool first = true;
  for (size_t i = 0; i < KIND_ROLE_COUNT; i++) {
    const char *role = g_kind_roles[i].role;
    JsonSpan nv;
    bool in_req = json_member(req, role, &nv);
    if (!in_req && !(e.roles.len > 0 && json_member(e.roles, role, &nv))) {
      continue; // neither sets it
    }
    if (nv.len == 4 && memcmp(nv.data, "null", 4) == 0) {
      continue; // back to the default: not stored
    }
    jsonbuf_append(&out, first ? "" : ",");
    first = false;
    jsonbuf_append_json_string(&out, role);
    if (!in_req) {
      jsonbuf_append(&out, ":");
      jsonbuf_append_len(&out, nv.data, nv.len); // the entry's, as it was
      continue;
    }
    // the request's, written plainly: what was checked, nothing else it held
    KindsEntry asked = {0};
    asked.roles = req;
    char kind[KIND_LIST_MAX], name[KIND_NAME_MAX];
    bool set = false;
    KindsLookup(&asked, &g_kind_roles[i], kind, sizeof(kind), name,
                sizeof(name), &set, NULL, 0);
    assert(set); // checked above
    jsonbuf_append(&out, ":{\"kind\":");
    jsonbuf_append_json_string(&out, kind);
    if (name[0] != '\0') {
      jsonbuf_append(&out, ",\"name\":");
      jsonbuf_append_json_string(&out, name);
    }
    jsonbuf_append(&out, "}");
  }
  // what this build does not know, kept
  cur = NULL;
  while (e.roles.len > 0 && json_object_next(e.roles, &cur, &k, &v)) {
    char role[48];
    snprintf(role, sizeof(role), "%.*s", (int)(k.len < 47 ? k.len : 47),
             k.data);
    if (k.len < 47 && KindRoleNamed(role) != NULL) {
      continue;
    }
    jsonbuf_append(&out, first ? "\"" : ",\"");
    first = false;
    jsonbuf_append_len(&out, k.data, k.len); // still escaped as it was
    jsonbuf_append(&out, "\":");
    jsonbuf_append_len(&out, v.data, v.len);
  }
  jsonbuf_append(&out, "}}");
  int id = e.id;
  KindsClose(&e);
  if (out.overflow) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return SendJSONError(client_fd, 500, "the mapping does not fit");
  }
  // the mapping as it will be: no role's kind among a login's reminders
  // under the task kind it makes (a task kind changed by this PUT, or a
  // role moved under the one already set)
  KindsEntry made = {0};
  JsonSpan whole = {out.data, out.len};
  json_member(whole, "roles", &made.roles);
  char task[KIND_MAX];
  bool task_set = false;
  KindsLookup(&made, KindRoleNamed("task"), task, sizeof(task), NULL, 0,
              &task_set, NULL, 0);
  for (size_t i = 0; i < KIND_ROLE_COUNT; i++) {
    char kind[KIND_LIST_MAX];
    bool set = false;
    KindsLookup(&made, &g_kind_roles[i], kind, sizeof(kind), NULL, 0, &set,
                NULL, 0);
    for (const char *p = kind, *comma; p; p = comma ? comma + 1 : NULL) {
      comma = strchr(p, ',');
      size_t len = comma ? (size_t)(comma - p) : strlen(p);
      if (KindIsLoginTask(task, p, len)) {
        sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
        return SendJSONError(client_fd, 400,
                             "%s: %.*s is a login's reminders under the task "
                             "kind %s",
                             g_kind_roles[i].role, (int)len, p, task);
      }
    }
  }

  sqlite3_stmt *st = NULL;
  const char *sql =
      id > 0 ? "UPDATE entries SET content = ?1, last_modified_at_utc = "
               "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?2;"
             : "INSERT INTO entries (kind, title, content) VALUES (?3, ?4, "
               "?1);";
  bool ok = sqlite3_prepare_v2(db, sql, -1, &st, NULL) == SQLITE_OK;
  if (ok) {
    sqlite3_bind_text(st, 1, out.data, (int)out.len, SQLITE_STATIC);
    if (id > 0) {
      sqlite3_bind_int(st, 2, id);
    } else {
      sqlite3_bind_text(st, 3, KINDS_ENTRY_KIND, -1, SQLITE_STATIC);
      sqlite3_bind_text(st, 4, KINDS_ENTRY_TITLE, -1, SQLITE_STATIC);
    }
    ok = sqlite3_step(st) == SQLITE_DONE;
  }
  sqlite3_finalize(st);
  if (!ok || sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    int status = SendJSONError(
        client_fd, 500, "Failed to write the mapping: %s", sqlite3_errmsg(db));
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return status;
  }
  return KindsAnswer(client_fd, arena, db);
}

static int HandleKindRoles(int client_fd, Arena *arena, const char *method,
                           const char *body) {
  assert(client_fd >= 0 && arena_valid(arena) && method != NULL);
  bool get = strcmp(method, "GET") == 0;
  if (!get && strcmp(method, "PUT") != 0) {
    return SendJSONError(client_fd, 405,
                         "Method %s not allowed on "
                         "/kinds/roles",
                         method);
  }
  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  int status = get ? KindsAnswer(client_fd, arena, db)
                   : KindsPut(client_fd, arena, db, body);
  sqlite3_close(db);
  return status;
}

#endif // LCARS_KINDS_IMPLEMENTATION
#endif // LCARS_KINDS_H
