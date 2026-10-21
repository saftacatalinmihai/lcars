#ifndef LCARS_DB_H
#define LCARS_DB_H

#include <assert.h>
#include <sqlite3.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

// The schema of lcars.db: what the server creates and migrates at start-up,
// before the first connection thread opens its own handle. Everything that
// reads or writes rows lives with its route (lcars_http.h and its modules).

// Where lcars.db is: resolved once by SetLcarsDBPath in main, before any
// thread starts, and never changed after, which is what lets everything that
// opens it - main's InitDB, the HTTP connection threads, CalDAV, the embedder
// and the change watcher - read it through LcarsDBPath() without a lock.
//
// In order, the first one given wins (the command line over the environment,
// and in each a file over a directory):
//   --db FILE, --data DIR (DIR/lcars.db), $LCARS_DB_PATH, $LCARS_DATA_DIR,
//   and else "lcars.db", relative to the working directory.
// That last is byte for byte what this used to be compiled in as, and it is
// what the live unit relies on: it passes neither flag, sets neither
// variable, and its WorkingDirectory is the checkout. A path that resolved
// anywhere else would not fail: sqlite would create the file, InitDB seed a
// new journal, /health answer - the server up on an empty journal. Hence the
// start log naming the absolute path and the entry count, and
// vps-rebuild.sh's count guard. --data DIR must exist (nothing is made
// here; a typo must not become a new directory) and is never chdir'd into:
// every other relative path the server has keeps its meaning.
#define LCARS_DB_FILE "lcars.db"
#define LCARS_DB_PATH_MAX 1024

static bool SetLcarsDBPath(const char *db_flag, const char *data_flag,
                           char *err, size_t err_size);
static const char *LcarsDBPath(void);
static const char *LcarsDBWalPath(void);

static void InitDB(sqlite3 *db);

#ifdef LCARS_IMPLEMENTATION

#include <stdlib.h>
#include <sys/stat.h>

static char g_lcars_db_path[LCARS_DB_PATH_MAX];
// The WAL file's name, which the change watcher stats on every poll: made
// here once rather than formatted per poll, and fixed by the same rule.
static char g_lcars_db_wal[LCARS_DB_PATH_MAX + 4];
static bool g_lcars_db_path_set = false;

static bool SetLcarsDBPath(const char *db_flag, const char *data_flag,
                           char *err, size_t err_size) {
  assert(!g_lcars_db_path_set && "the database path is set once, in main");
  assert(err != NULL && err_size > 0);
  const char *env_db = getenv("LCARS_DB_PATH");
  const char *env_data = getenv("LCARS_DATA_DIR");
  // An empty value counts as not given, flag or variable alike: an unset
  // "LCARS_DB_PATH=" line in an env file must not mean "a file named ''".
  const char *file = NULL;
  const char *dir = NULL;
  if (db_flag && db_flag[0]) {
    file = db_flag;
  } else if (data_flag && data_flag[0]) {
    dir = data_flag;
  } else if (env_db && env_db[0]) {
    file = env_db;
  } else if (env_data && env_data[0]) {
    dir = env_data;
  } else {
    file = LCARS_DB_FILE;
  }

  int n;
  if (dir) {
    struct stat st;
    if (stat(dir, &st) != 0 || !S_ISDIR(st.st_mode)) {
      snprintf(err, err_size, "data directory '%s' does not exist", dir);
      return false;
    }
    size_t len = strlen(dir);
    n = snprintf(g_lcars_db_path, sizeof(g_lcars_db_path), "%s%s%s", dir,
                 dir[len - 1] == '/' ? "" : "/", LCARS_DB_FILE);
  } else {
    struct stat st;
    if (stat(file, &st) == 0 && S_ISDIR(st.st_mode)) {
      snprintf(err, err_size,
               "database '%s' is a directory (--data takes a directory)", file);
      return false;
    }
    n = snprintf(g_lcars_db_path, sizeof(g_lcars_db_path), "%s", file);
  }
  if (n <= 0 || (size_t)n >= sizeof(g_lcars_db_path)) {
    snprintf(err, err_size, "database path too long (over %d bytes)",
             LCARS_DB_PATH_MAX - 1);
    g_lcars_db_path[0] = '\0';
    return false;
  }
  snprintf(g_lcars_db_wal, sizeof(g_lcars_db_wal), "%s-wal", g_lcars_db_path);
  g_lcars_db_path_set = true;

  assert(g_lcars_db_path[0] != '\0');
  assert(strlen(g_lcars_db_wal) == strlen(g_lcars_db_path) + 4);
  return true;
}

static const char *LcarsDBPath(void) {
  assert(g_lcars_db_path_set && "SetLcarsDBPath runs first, in main");
  return g_lcars_db_path;
}

static const char *LcarsDBWalPath(void) {
  assert(g_lcars_db_path_set && "SetLcarsDBPath runs first, in main");
  return g_lcars_db_wal;
}

// Adds a column to `entries` if it isn't there yet. The repo had no migration
// mechanism before this - every schema change so far arrived with the table
// itself - and one column is not worth introducing PRAGMA user_version and a
// version ladder for.
//
// sqlite has no "ADD COLUMN IF NOT EXISTS", so the existence check is a
// PRAGMA table_info scan rather than an ALTER whose error is swallowed: a
// swallowed error would also hide a *real* failure (a locked database, a
// malformed DDL) behind the same silence as the ordinary no-op case.
//
// `name` and `ddl` are compile-time literals from this file - the DDL text is
// pasted into the statement, which is only safe because nothing outside this
// file ever chooses it.
static inline void EnsureEntryColumn(sqlite3 *db, const char *name,
                                     const char *ddl) {
  assert(db != NULL);
  assert(name != NULL);
  assert(ddl != NULL);

  sqlite3_stmt *stmt;
  if (sqlite3_prepare_v2(db, "PRAGMA table_info(entries);", -1, &stmt, NULL) !=
      SQLITE_OK) {
    fprintf(stderr, "SQL error reading entries schema: %s\n",
            sqlite3_errmsg(db));
    return;
  }
  bool present = false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    // table_info's columns are (cid, name, type, notnull, dflt_value, pk).
    const char *col = (const char *)sqlite3_column_text(stmt, 1);
    if (col && strcmp(col, name) == 0) {
      present = true;
      break;
    }
  }
  sqlite3_finalize(stmt);
  if (present) {
    return;
  }

  char sql[256];
  int n = snprintf(sql, sizeof(sql), "ALTER TABLE entries ADD COLUMN %s;", ddl);
  // Both arguments are literals from this file, so a truncated statement
  // would be a programmer error, not bad input.
  assert(n > 0 && (size_t)n < sizeof(sql));
  (void)n;

  char *errMsg = NULL;
  if (sqlite3_exec(db, sql, NULL, NULL, &errMsg) != SQLITE_OK) {
    // A real runtime failure - a locked database, most likely. Report it and
    // carry on: every read path treats a missing value as unset, so the
    // server still runs, and the next start tries again.
    fprintf(stderr, "SQL error adding column %s: %s\n", name,
            errMsg ? errMsg : "(unknown)");
    sqlite3_free(errMsg);
    return;
  }
  fprintf(stdout, "Added entries.%s\n", name);
}

static void InitDB(sqlite3 *db) {
  assert(db != NULL);
  const char *sql_entry_create =
      "CREATE TABLE IF NOT EXISTS entries ("
      "id INTEGER PRIMARY KEY AUTOINCREMENT,"
      "kind TEXT DEFAULT '',"
      "title TEXT,"
      "content TEXT,"
      "value_int INTEGER,"
      "value_float REAL,"
      "value_blob BLOB,"
      "done_bool INTEGER DEFAULT 0,"
      "deleted INTEGER DEFAULT 0,"
      "created_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc')),"
      "last_modified_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc')),"
      // Scheduling, deliberately separate from the two columns above: those
      // say when the row was touched, these say what span of time it is
      // *for*. Nothing ever computes a default for them - an entry is
      // unscheduled until something says otherwise - so '' means unset, and
      // the shape when set is the same 'YYYY-MM-DD HH:MM:SS' UTC text every
      // other timestamp here uses, which is what lets it be compared,
      // range-filtered and ordered as text.
      "start_date TEXT DEFAULT '',"
      "end_date TEXT DEFAULT ''"
      ");";
  char *errMsg = NULL;
  if (sqlite3_exec(db, sql_entry_create, NULL, NULL, &errMsg) != SQLITE_OK) {
    fprintf(stderr, "SQL error: %s\n", errMsg ? errMsg : "(unknown)");
    sqlite3_free(errMsg);
  }

  // CREATE TABLE IF NOT EXISTS is a no-op against a database that already has
  // the table, so a column added to the statement above would never reach an
  // existing lcars.db - and the one that matters is live personal data that
  // predates it. These two calls are what actually migrate it.
  EnsureEntryColumn(db, "start_date", "start_date TEXT DEFAULT ''");
  EnsureEntryColumn(db, "end_date", "end_date TEXT DEFAULT ''");
  // Classified entries (lcars_vault.h): the level, 0 Unclassified and 2
  // Secret, and a Secret row's envelope - its title, text and numbers,
  // encrypted in the browser. Every row there is reads as Unclassified.
  EnsureEntryColumn(db, "classification", "classification INTEGER DEFAULT 0");
  EnsureEntryColumn(db, "sealed", "sealed TEXT DEFAULT ''");

  // A new journal holds nothing: no seed row (docs/design/kinds.md, 4).
  // The page draws an empty journal's own empty states, and the first
  // entry gets the `log` role's kind (lcars_kinds.h). A seed would also
  // have to be of some kind, and every kind is now the owner's to name.
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_DB_H
