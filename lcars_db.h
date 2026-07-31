#ifndef LCARS_DB_H
#define LCARS_DB_H

#include "lcars_arena.h"
#include "lcars_string.h"
#include "liblcars.h"
#include "vendor/sqlite3.h"

static inline int sqlite_callback(void *state, int argc, char **argv,
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

static inline int ExecSQL(State *s, String sql, String successMsg) {
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
      "INSERT INTO entries (kind, title, content) "
      "SELECT 'architect_log', 'Captain Log', '%q Captain log' "
      "WHERE NOT EXISTS (SELECT 1 FROM entries WHERE kind = 'architect_log');",
      datename);
  if (sql_insert_full) {
    ExecSQL(s, StringStatic(sql_insert_full),
            StringStatic("Data inserted successfully"));
    sqlite3_free(sql_insert_full);
  }
}

static inline String GetEntryContentFromDB(State *s, int id) {
  String output;
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(s->db, "SELECT content FROM entries WHERE id=?1",
                              -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error failure fetching entry content: %s\n",
            sqlite3_errmsg(s->db));
    output = StringInit(&s->scratch_arena, "");
  } else {
    sqlite3_bind_int(stmt, 1, id);
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
      const char *col_text = (const char *)sqlite3_column_text(stmt, 0);
      output = StringInit(&s->scratch_arena, col_text ? col_text : "");
    } else {
      output = StringInit(&s->scratch_arena, "");
    }
    sqlite3_finalize(stmt);
  }
  return output;
}

static inline void UpdateEntryContentInDB(State *s, int id, String content) {
  char *sql_update_full = sqlite3_mprintf(
      "UPDATE entries SET content = (%Q), last_modified_at_utc = "
      "strftime('%%Y-%%m-%%d %%H:%%M:%%S', 'now', 'utc') WHERE id = %d;",
      content.data, id);
  if (!sql_update_full) {
    updateNotification(s, StringStatic("SQL error"));
    return;
  }
  ExecSQL(s, StringStatic(sql_update_full), StringStatic(""));
  sqlite3_free(sql_update_full);
}

static inline void DeleteEntryFromDB(State *s, int id) {
  char *sql_delete =
      sqlite3_mprintf("UPDATE entries SET deleted = 1 WHERE id = %d;", id);
  if (!sql_delete) {
    updateNotification(s, StringStatic("SQL error"));
    return;
  }
  ExecSQL(s, StringStatic(sql_delete), StringStatic("Entry deleted"));
  sqlite3_free(sql_delete);
}

static KindList GetAllKindsFromDB(State *s) {
  KindList kindList = {0};
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db, "SELECT DISTINCT kind FROM entries WHERE deleted IS NULL OR "
              "deleted = 0 ORDER BY kind ASC",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error failure fetching kinds: %s\n",
            sqlite3_errmsg(s->db));
  } else {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *col_text = (const char *)sqlite3_column_text(stmt, 0);
      if (col_text) {
        kindList.kinds[kindList.count] = StringInit(&s->doc_arena, col_text);
        kindList.count++;
      }
    }
    sqlite3_finalize(stmt);
  }
  return kindList;
}

static inline int GetEntriesByKind(State *s, const char *kind,
                                   EntryListItem *items, int maxItems) {
  sqlite3_stmt *stmt;
  int count = 0;
  int rc = sqlite3_prepare_v2(
      s->db,
      "SELECT id, title, created_at_utc, last_modified_at_utc FROM entries "
      "WHERE kind=?1 AND (deleted IS NULL OR deleted = 0) ORDER BY id DESC",
      -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_STATIC);
    while (sqlite3_step(stmt) == SQLITE_ROW && count < maxItems) {
      items[count].id = sqlite3_column_int(stmt, 0);
      const char *t = (const char *)sqlite3_column_text(stmt, 1);
      const char *c = (const char *)sqlite3_column_text(stmt, 2);
      const char *m = (const char *)sqlite3_column_text(stmt, 3);

      strncpy(items[count].title, t ? t : "", sizeof(items[count].title) - 1);
      items[count].title[sizeof(items[count].title) - 1] = '\0';

      strncpy(items[count].created_at, c ? c : "",
              sizeof(items[count].created_at) - 1);
      items[count].created_at[sizeof(items[count].created_at) - 1] = '\0';

      strncpy(items[count].last_modified, m ? m : "",
              sizeof(items[count].last_modified) - 1);
      items[count].last_modified[sizeof(items[count].last_modified) - 1] = '\0';

      count++;
    }
    sqlite3_finalize(stmt);
  } else {
    fprintf(stderr, "SQL error fetching entries by kind: %s\n",
            sqlite3_errmsg(s->db));
  }
  return count;
}

static inline int GetFirstPersonalLogId(State *s) {
  sqlite3_stmt *stmt;
  int id = 1;
  if (sqlite3_prepare_v2(
          s->db,
          "SELECT id FROM entries WHERE kind='architect_log' AND (deleted IS "
          "NULL OR deleted = 0) ORDER BY ID DESC LIMIT 1",
          -1, &stmt, NULL) == SQLITE_OK) {
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      id = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }
  return id;
}

static inline String GetLogFromDB(State *s) {
  int id = GetFirstPersonalLogId(s);
  return GetEntryContentFromDB(s, id);
}

static inline void UpdateLogInDB(State *s, String newLog) {
  int id = GetFirstPersonalLogId(s);
  UpdateEntryContentInDB(s, id, newLog);
}

static inline void LoadEntryIntoEditor(Element *e, String dbLog) {
  int textLen = dbLog.data ? (int)strlen(dbLog.data) : 0;
  if (textLen > e->textCapacity) {
    textLen = e->textCapacity;
  }
  if (e->gapBuffer && dbLog.data) {
    memcpy(e->gapBuffer, dbLog.data, textLen);
  }
  e->gapStart = textLen;
  e->gapEnd = e->textCapacity;

  if (e->text.data && dbLog.data) {
    memcpy(e->text.data, dbLog.data, textLen);
    e->text.data[textLen] = '\0';
  }
  e->text.len = textLen;
  e->textLen = textLen;
  e->scrollY = 0.0f;
  e->cursorY = 0.0f;
  e->snapToCursor = 2;
}

static inline void make_entry_list(Arena *doc_arena, Element *e, State *s) {
  e->kind = ELEM_ENTRY_LIST;
  e->listCollapsed = false;
  e->selectedEntryId = GetFirstPersonalLogId(s);
  e->kindList = GetAllKindsFromDB(s);
  e->selectedKind = e->kindList.count > 0 ? e->kindList.kinds[0] : StringStatic("architect_log");

  String content = GetEntryContentFromDB(s, e->selectedEntryId);
  make_text_editor(doc_arena, e, content);
  e->kind = ELEM_ENTRY_LIST;
  StringFree(&content);
}

#endif // LCARS_DB_H
