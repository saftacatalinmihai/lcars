#ifndef LCARS_LOGINS_H
#define LCARS_LOGINS_H

// The limited logins: read everything, write only their own entries.
//
// Besides the captain's own login, the server knows logins that may read
// anything in the journal but write nothing but entries of their own kinds.
// A rule in an agent's brief would only be a request, so the server holds the
// line: each has a user of its own, read from the environment by
// LimitedLoginsInit in lcars_http.h (g_limited_logins), and a request that
// authenticated with one (g_conn_login) passes through LimitedAllowed before
// the router. When a login's variables are unset the login does not exist.
//
//   Number One   LCARS_NO1_USER/LCARS_NO1_PASS    owner "no1"
//     The captain's first officer (scripts/no1.py, engineer.py's brief_no1):
//     an engineer session that orders the other engineers, reviews their
//     work and deploys it. It keeps its log in no1_log and asks the captain
//     in task_no1, a Reminders list.
//   Crew         LCARS_CREW_USER/LCARS_CREW_PASS  owner "crew"
//     Scheduled crew roles: headless agents on the VPS, run from cron, that
//     read the journal and write reports (crew_*), and tasks for the captain
//     in task_crew.
//
//   The steward  LCARS_STEWARD_USER/LCARS_STEWARD_PASS  owner "steward"
//     The crew notes' runner (scripts/crew.py, note_apply), and nothing
//     else: what a crew role was asked to add to the journal. The captain's
//     rule (2026-10-15): the crew may create new entries, add to the end of
//     his and set an entry's title, and (2026-10-16) close an open entry by
//     setting the end it lacks. Widened (2026-10-16, the captain's yes
//     through Number One): it may set any field of an entry of his, replace
//     its text on an asked edit, delete and restore it - each only on the
//     row as it was read (if_modified), so nothing the captain wrote since
//     is ever overwritten. So it has its own rule, below.
//
// A login's own kinds are, for its owner <o>: `<o>_*`, `<task>_<o>` and
// `<task>_<o>_*`, <task> the `task` role's kind (lcars_kinds.h; "task" by
// default, so task_<o>), since CalDAV publishes <task>_* kinds as lists.
//
//   GET/HEAD anything but /engineer, CalDAV and    allowed
//   /say/token (a Deepgram key: money, and no
//   login of these has a microphone; POST
//   /transcribe is refused for the same reason)
//   POST /entries                                  a JSON body whose kind is
//                                                  its own
//   PUT/PATCH/DELETE /entries/<id>                 a row of its own kind, and
//                                                  a new kind (if any) of its
//                                                  own
//   GET/PUT /entries/<id>/caldav                   a row of its own (a
//                                                  reminder's due date)
//   POST /chat, /ask, /embed                       allowed: they write nothing
//                                                  themselves, and a chat's
//                                                  lcars-cli carries this same
//                                                  login (ChatBuildEnv)
//   (a chat's attachments name only files already
//   under media/chat/, which this login cannot
//   upload)
//   anything else (uploads included: an entry's,   403
//   and a chat's, POST /chat/media)
//
// The steward's rule instead of the table's writes:
//
//   POST /entries                       a JSON body with a kind of the
//                                       captain's (StewardMayWriteKind) and
//                                       no `deleted`: a new entry
//   POST /entries/<id>/append           a row of a kind of the captain's:
//                                       text added at the end, refused if
//                                       the row moved since it was read
//                                       (HandleAppendEntry, 412)
//   POST /entries/<id>/title            a row of a kind of the captain's:
//                                       its title set, and nothing else,
//                                       refused if the row moved since it
//                                       was read (HandleTitleEntry, 412)
//   POST /entries/<id>/end              a row of a kind of the captain's
//                                       with a start and no end: the end
//                                       set, and nothing else; refused if
//                                       it moved (412) or has an end (409)
//                                       (HandleEndEntry)
//   PATCH /entries/<id>                 a row of a kind of the captain's,
//                                       a JSON body with `if_modified`; a
//                                       new kind (if any) of the captain's;
//                                       `deleted` only as 0 (the restore);
//                                       412 moved, 409 deleted (a restore:
//                                       live) (HandleUpdateEntry)
//   DELETE /entries/<id>                a row of a kind of the captain's,
//                                       a JSON body with `if_modified`
//                                       (HandleDeleteEntry: soft, 412, 409)
//   anything else that writes           403: PUT on any row, uploads,
//                                       chat, CalDAV
//
// A kind of the captain's is any but another login's (crew_*, no1_*,
// steward_*, task_crew*, task_no1*, task_steward*), a `settings` entry, and
// the frozen imports (the `imported` role's kinds).
// Append adds and cannot express a change; the title and end routes name
// one column each. PATCH and DELETE can change anything of a row, so for
// this login they are guarded writes only: the runner reads the row, keeps
// its old values for Undo, and the server's own WHERE refuses the write if
// the row moved in between (the captain typing). A kind of another login's
// can neither be touched nor moved into, and a hard delete does not exist.
//
// The kind is read with json_get_string into a buffer of the handlers' own
// size, so the gate and the handler that stores the row read the same kind
// from the same body, whatever else the body says.
//
// The engineer routes are refused outright: Number One works through
// engineer.py on production (scripts/no1.py), not through the HTTP layer,
// and the crew has no business there.
// A module of lcars_http.h, included from inside its implementation block.

static bool LimitedOwnsKind(const LimitedLogin *l, const char *kind);
static int LimitedRefuse(int client_fd, const LimitedLogin *l);
static bool LimitedAllowed(int client_fd, const LimitedLogin *l,
                           const char *method, const char *path,
                           const char *body, const char *content_type,
                           int *status);

#ifdef LCARS_LOGINS_IMPLEMENTATION

// the router's own path tests, defined further down lcars_http.h
static bool PathIs(const char *path, const char *route);
static bool MatchEntryIdPath(const char *path, int *out_id);
static bool MatchEntryAppendPath(const char *path, int *out_id);
static bool MatchEntryTitlePath(const char *path, int *out_id);
static bool MatchEntryEndPath(const char *path, int *out_id);

// The handlers read `kind` into 128 bytes (HandlePostEntry, HandleUpdateEntry)
#define LIMITED_KIND_MAX 128

// The roles a limited login's write is judged by: the task kind its
// reminders are under and the imports nobody may touch. Loaded from the
// journal by LimitedLoadRoles at the top of every write LimitedAllowed
// sees, so a role the owner changes applies to the next request; per
// thread, as each connection is one. Empty: not loaded on this thread yet,
// and the defaults stand (only LimitedRefuse's words can meet that, from
// the router's own refusals ahead of LimitedAllowed).
static _Thread_local struct {
  char task[KIND_MAX];
  char imported[KIND_LIST_MAX];
} limited_roles;

static void LimitedLoadRoles(void) {
  sqlite3 *db = NULL;
  if (sqlite3_open_v2(LcarsDBPath(), &db, SQLITE_OPEN_READONLY, NULL) !=
      SQLITE_OK) {
    // the defaults: a journal the gate cannot read is one the handler
    // cannot write either
    sqlite3_close(db);
    snprintf(limited_roles.task, sizeof(limited_roles.task), "task");
    snprintf(limited_roles.imported, sizeof(limited_roles.imported), "%s",
             KindRoleNamed("imported")->def);
    return;
  }
  sqlite3_busy_timeout(db, 2000);
  KindFor(db, "task", limited_roles.task, sizeof(limited_roles.task));
  KindFor(db, "imported", limited_roles.imported,
          sizeof(limited_roles.imported));
  sqlite3_close(db);
}

static const char *LimitedTaskKind(void) {
  return limited_roles.task[0] ? limited_roles.task
                               : KindRoleNamed("task")->def;
}

static bool LimitedOwnsKind(const LimitedLogin *l, const char *kind) {
  assert(l != NULL && l->owner != NULL && l->owner[0] != '\0');
  assert(kind != NULL);
  size_t n = strlen(l->owner);
  assert(n < 32);
  // <owner>_*
  if (strncmp(kind, l->owner, n) == 0 && kind[n] == '_') {
    return true;
  }
  // <task>_<owner>, <task>_<owner>_*
  const char *task = LimitedTaskKind();
  size_t t = strlen(task);
  if (strncmp(kind, task, t) != 0 || kind[t] != '_' ||
      strncmp(kind + t + 1, l->owner, n) != 0) {
    return false;
  }
  return kind[t + 1 + n] == '\0' || kind[t + 1 + n] == '_';
}

static bool LimitedRowKind(int client_fd, int id, char *out, size_t out_size,
                           int *status);

// The kinds the steward may create, append to, title and close: the captain's
// own, never a limited login's or a frozen import's (the `imported` role's
// kinds, as the linker's are), and no `settings` entry: one titled
// `kinds` says where every feature writes (lcars_kinds.h), and a create,
// a retitle or a PATCH could each make one, so the whole kind is closed.
static bool StewardMayWriteKind(const char *kind) {
  assert(kind != NULL);
  if (kind[0] == '\0' || strcmp(kind, KINDS_ENTRY_KIND) == 0) {
    return false;
  }
  for (size_t i = 0; i < LIMITED_LOGIN_COUNT; i++) {
    if (LimitedOwnsKind(g_limited_logins[i], kind)) {
      return false;
    }
  }
  // the imported role's kinds, comma-joined
  size_t n = strlen(kind);
  for (const char *p = limited_roles.imported; *p;) {
    const char *comma = strchr(p, ',');
    size_t len = comma ? (size_t)(comma - p) : strlen(p);
    if (len == n && memcmp(p, kind, n) == 0) {
      return false;
    }
    if (!comma) {
      break;
    }
    p = comma + 1;
  }
  return true;
}

static int StewardRefuse(int client_fd) {
  assert(client_fd >= 0);
  return SendJSONError(
      client_fd, 403,
      "the steward may create the captain's entries, add to "
      "them (/append, /title, /end), and PATCH or DELETE "
      "one of his with if_modified (deleted only as 0); "
      "never another login's, an import's or a settings entry");
}

// The steward's writes (the rule above); reads were let through already
static bool StewardAllowed(int client_fd, const char *method, const char *path,
                           const char *body, const char *content_type,
                           int *status) {
  assert(method != NULL && path != NULL && status != NULL);
  const char *b = body ? body : "";
  bool is_json = strstr(content_type, "application/json") != NULL;
  char kind[LIMITED_KIND_MAX] = {0};
  int id = 0;
  if (strcmp(method, "POST") == 0 && PathIs(path, "/entries")) {
    // `deleted` read as a number or a string: either way a create that
    // names it is not one this login makes
    char dummy[16];
    int dummy_int = 0;
    if (is_json && json_get_string(b, "kind", kind, sizeof(kind)) &&
        StewardMayWriteKind(kind) && !json_get_int(b, "deleted", &dummy_int) &&
        !json_get_string(b, "deleted", dummy, sizeof(dummy))) {
      return true;
    }
  } else if (strcmp(method, "POST") == 0 &&
             (MatchEntryAppendPath(path, &id) ||
              MatchEntryTitlePath(path, &id) || MatchEntryEndPath(path, &id))) {
    if (!LimitedRowKind(client_fd, id, kind, sizeof(kind), status)) {
      return false;
    }
    if (StewardMayWriteKind(kind)) {
      return true;
    }
  } else if (MatchEntryIdPath(path, &id) &&
             (strcmp(method, "PATCH") == 0 || strcmp(method, "DELETE") == 0)) {
    // the handlers read if_modified, kind and deleted from a JSON body only
    // since in the handlers' own size: a stamp the gate reads, they read
    char since[HTTP_MAX_TIMESTAMP_LEN + 1] = {0};
    char moved[LIMITED_KIND_MAX] = {0}, dummy[16];
    int deleted = 0;
    bool guarded = is_json &&
                   json_get_string(b, "if_modified", since, sizeof(since)) &&
                   since[0] != '\0';
    bool moves = json_get_string(b, "kind", moved, sizeof(moved));
    // `deleted` as a string the handler would not read: refused, not passed
    bool undeletes_only =
        !json_get_string(b, "deleted", dummy, sizeof(dummy)) &&
        (!json_get_int(b, "deleted", &deleted) ||
         (strcmp(method, "PATCH") == 0 && deleted == 0));
    if (guarded && undeletes_only && (!moves || StewardMayWriteKind(moved))) {
      if (!LimitedRowKind(client_fd, id, kind, sizeof(kind), status)) {
        return false;
      }
      if (StewardMayWriteKind(kind)) {
        return true;
      }
    }
  }
  *status = StewardRefuse(client_fd);
  return false;
}

static int LimitedRefuse(int client_fd, const LimitedLogin *l) {
  assert(client_fd >= 0);
  assert(l != NULL && l->who != NULL && l->owner != NULL);
  return SendJSONError(client_fd, 403,
                       "%s may read anything but write only its own entries "
                       "(kinds %s_*, %s_%s)",
                       l->who, l->owner, LimitedTaskKind(), l->owner);
}

// The kind of row `id`; false (with *status answered) when it cannot be read.
static bool LimitedRowKind(int client_fd, int id, char *out, size_t out_size,
                           int *status) {
  assert(id > 0 && out != NULL && out_size > 0 && status != NULL);
  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    *status = 500;
    return false;
  }
  sqlite3_stmt *stmt = NULL;
  bool found = false;
  out[0] = '\0';
  if (sqlite3_prepare_v2(db, "SELECT kind FROM entries WHERE id = ?1;", -1,
                         &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_int(stmt, 1, id);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      const unsigned char *k = sqlite3_column_text(stmt, 0);
      snprintf(out, out_size, "%s", k ? (const char *)k : "");
      found = true;
    }
  }
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  if (!found) {
    *status = SendJSONError(client_fd, 404, "no entry %d", id);
  }
  return found;
}

static bool LimitedAllowed(int client_fd, const LimitedLogin *l,
                           const char *method, const char *path,
                           const char *body, const char *content_type,
                           int *status) {
  assert(l != NULL && l == g_conn_login);
  assert(method != NULL && path != NULL && status != NULL);
  assert(content_type != NULL);
  bool read = strcmp(method, "GET") == 0 || strcmp(method, "HEAD") == 0;
  if (!read) {
    LimitedLoadRoles();
  }
  // /vault: the wrapped key is an offline guessing target, and writing it
  // is the owner's alone (lcars_vault.h)
  if (IsEngineerPath(path) || IsCalDAVRequest(method, path) ||
      PathIs(path, "/say/token") || PathIs(path, "/vault")) {
    *status = LimitedRefuse(client_fd, l);
    return false;
  }
  int id = 0;
  if (MatchEntryCalDAVPath(path, &id)) {
    if (read) {
      return true;
    }
    char kind[LIMITED_KIND_MAX];
    if (!LimitedRowKind(client_fd, id, kind, sizeof(kind), status)) {
      return false;
    }
    if (!LimitedOwnsKind(l, kind)) {
      *status = LimitedRefuse(client_fd, l);
      return false;
    }
    return true;
  }
  if (read) {
    return true;
  }
  if (l->steward) {
    return StewardAllowed(client_fd, method, path, body, content_type, status);
  }
  if (strcmp(method, "POST") == 0 &&
      (PathIs(path, "/chat") || PathIs(path, "/ask") ||
       PathIs(path, "/embed"))) {
    return true;
  }
  const char *b = body ? body : "";
  // the handlers' own test: a kind is read only from a JSON body, and a
  // plain-text one is content in the default kind
  bool is_json = strstr(content_type, "application/json") != NULL;
  char kind[LIMITED_KIND_MAX] = {0};
  if (strcmp(method, "POST") == 0 && PathIs(path, "/entries")) {
    if (is_json && json_get_string(b, "kind", kind, sizeof(kind)) &&
        LimitedOwnsKind(l, kind)) {
      return true;
    }
    *status = LimitedRefuse(client_fd, l);
    return false;
  }
  if (MatchEntryIdPath(path, &id) &&
      (strcmp(method, "PUT") == 0 || strcmp(method, "PATCH") == 0 ||
       strcmp(method, "DELETE") == 0)) {
    char row[LIMITED_KIND_MAX];
    if (!LimitedRowKind(client_fd, id, row, sizeof(row), status)) {
      return false;
    }
    // read whatever the content type, so a body the handler would not
    // take a kind from can only be refused for nothing, never let through
    bool moves = json_get_string(b, "kind", kind, sizeof(kind));
    if (LimitedOwnsKind(l, row) && (!moves || LimitedOwnsKind(l, kind))) {
      return true;
    }
    *status = LimitedRefuse(client_fd, l);
    return false;
  }
  *status = LimitedRefuse(client_fd, l);
  return false;
}

#endif // LCARS_LOGINS_IMPLEMENTATION
#endif // LCARS_LOGINS_H
