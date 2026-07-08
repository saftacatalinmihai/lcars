#ifndef LCARS_DB_H
#define LCARS_DB_H

#include "liblcars.h"

static int sqlite_callback(void *state, int argc, char **argv,
                           char **azColName) {
  State *s = (State *)state;
  (void)s;
  int i;
  for (i = 0; i < argc; i++) {
    printf("%s = %s\n", azColName[i], argv[i] ? argv[i] : "NULL");
  }
  printf("\n");
  return 0;
}

static int ExecSQL(State *s, String sql, String successMsg) {
  char *zErrMsg = 0;
  int rc = sqlite3_exec(s->db, sql.data, sqlite_callback, s, &zErrMsg);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error: %s\n", zErrMsg);
    updateNotification(s, StringStatic("SQL error"));
    sqlite3_free(zErrMsg);
  } else {
    if (successMsg.data && successMsg.len > 0) {
      fprintf(stdout, "%s\n", successMsg.data);
      updateNotification(s, successMsg);
    }
  }
  return rc;
}

void InitDB(State *s, bool firstInit) {
  (void)firstInit;
  ExecSQL(s,
          StringStatic("CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY "
                       "AUTOINCREMENT, text TEXT);"),
          StringStatic("Table created successfully"));
  const char *sql_entry_create =
      "CREATE TABLE IF NOT EXISTS entries ("
      "id INTEGER PRIMARY KEY AUTOINCREMENT," // type of thing, 0=log, 1=task,
                                              // 2=event, etc. these are just
                                              // examples.
      "kind TEXT DEFAULT '',"
      "title TEXT,"
      "content TEXT,"
      "value_int INTEGER,"
      "value_float REAL,"
      "value_blob BLOB,"
      "done_bool INTEGER DEFAULT 0,"
      "created_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc')),"
      "last_modified_at_utc TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', "
      "'utc'))"
      ");";
  ExecSQL(s, StringStatic(sql_entry_create),
          StringStatic("Table Entry created successfully"));

  char datename[32];
  struct tm *to;
  time_t t = time(NULL);
  to = localtime(&t);
  strftime(datename, sizeof(datename), "%Y-%m-%d", to);

  char *sql_insert_full = sqlite3_mprintf(
      "INSERT OR IGNORE INTO log (id, text) VALUES (0, '%q Captain log');",
      datename);
  if (sql_insert_full) {
    ExecSQL(s, StringStatic(sql_insert_full),
            StringStatic("Data inserted successfully"));
    sqlite3_free(sql_insert_full);
  }
}

static String GetLogFromDB(State *s) {
  String output;
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(s->db, "SELECT text FROM log where id=?1", -1,
                              &stmt, 0);
  if (rc != SQLITE_OK) {
    updateNotification(s, StringStatic("failure fetching data"));
    output = StringInit(&s->scratch_arena, "");
  } else {
    sqlite3_bind_text(stmt, 1, "0", -1, SQLITE_STATIC);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
      const char *col_text = (const char *)sqlite3_column_text(stmt, 0);
      output = StringInit(&s->scratch_arena, col_text);
    } else {
      output = StringInit(&s->scratch_arena, "");
    }
    sqlite3_finalize(stmt);
  }
  return output;
}

static void UpdateLogInDB(State *s, String newLog) {
  char *sql_update_full =
      sqlite3_mprintf("UPDATE log SET text = (%Q) WHERE id = 0;", newLog.data);
  if (!sql_update_full) {
    updateNotification(s, StringStatic("SQL error"));
    return;
  }
  ExecSQL(s, StringStatic(sql_update_full), StringStatic(""));
  sqlite3_free(sql_update_full);
}

#endif // LCARS_DB_H
