#ifndef LCARS_DB_H
#define LCARS_DB_H

#include "lcars_arena.h"
#include "lcars_string.h"
#include "lcars_types.h"
#include "vendor/sqlite3.h"
#include <time.h>

static inline int sqlite_callback(void *state, int argc, char **argv,
                                  char **azColName);
static inline int ExecSQL(State *s, String sql, String successMsg);
static inline bool StepAndFinalize(State *s, sqlite3_stmt *stmt,
                                   String successMsg);
static void InitDB(State *s, bool firstInit);
static inline void GetTodayDateString(char *buf, size_t bufSize);
static inline int CreateNewEntry(State *s, const char *kind,
                                 const char *title, String content);
static inline String GetEntryContentFromDB(State *s, int id);
static inline void UpdateEntryContentInDB(State *s, int id, String content);
static inline void DeleteEntryFromDB(State *s, int id);
static KindList GetAllKindsFromDB(State *s);
static inline void EnsureKindListCache(State *s, Element *e);
static inline void InvalidateKindListCache(Element *e);
static inline int GetEntriesByKind(State *s, const char *kind,
                                   EntryListItem *items, int maxItems);
static inline void EnsureEntryListCache(State *s, Element *e);
static inline void InvalidateEntryListCache(Element *e);
static inline int GetDefaultEntryId(State *s);
static inline String GetLogFromDB(State *s);
static inline void UpdateLogInDB(State *s, String newLog);
static inline void LoadEntryIntoEditor(Element *e, String dbLog);
static inline void MarkContentDirty(Element *e);
static inline void FlushEntryContent(State *s, Element *e);
static inline void SwitchToEntry(State *s, Element *e, int newEntryId);
static inline void make_entry_list(Arena *doc_arena, Element *e, State *s);

#ifdef LCARS_IMPLEMENTATION

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

static inline void GetTodayDateString(char *buf, size_t bufSize) {
  time_t t = time(NULL);
  struct tm *to = localtime(&t);
  strftime(buf, bufSize, "%Y-%m-%d", to);
}

// Steps a prepared statement expected to produce no result rows (INSERT/
// UPDATE/DELETE), reports any error via notification, and finalizes it
// either way. Returns true on success. Callers prepare the statement and
// bind its parameters before calling this.
static inline bool StepAndFinalize(State *s, sqlite3_stmt *stmt,
                                   String successMsg) {
  int rc = sqlite3_step(stmt);
  bool ok = (rc == SQLITE_DONE);
  if (!ok) {
    fprintf(stderr, "SQL error: %s\n", sqlite3_errmsg(s->db));
    updateNotification(s, StringStatic("SQL error"));
  } else if (successMsg.data && successMsg.len > 0) {
    updateNotification(s, successMsg);
  }
  sqlite3_finalize(stmt);
  return ok;
}

// Inserts a new entry with the given kind/title/content and returns its id
// (0 if the insert failed).
static inline int CreateNewEntry(State *s, const char *kind,
                                 const char *title, String content) {
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db, "INSERT INTO entries (kind, title, content) VALUES (?1, ?2, ?3);",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    updateNotification(s, StringStatic("SQL error"));
    return 0;
  }
  sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 3, content.data ? content.data : "", -1,
                    SQLITE_TRANSIENT);
  if (!StepAndFinalize(s, stmt, StringStatic("New entry created"))) {
    return 0;
  }
  return (int)sqlite3_last_insert_rowid(s->db);
}

static void InitDB(State *s, bool firstInit) {
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
  GetTodayDateString(datename, sizeof(datename));

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db,
      "INSERT INTO entries (kind, title, content) "
      "SELECT ?1, 'Captain Log', ?2 || ' Captain log' "
      "WHERE NOT EXISTS (SELECT 1 FROM entries WHERE kind = ?1);",
      -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, DEFAULT_ENTRY_KIND, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, datename, -1, SQLITE_STATIC);
    StepAndFinalize(s, stmt, StringStatic("Data inserted successfully"));
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
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db,
      "UPDATE entries SET content = ?1, last_modified_at_utc = "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?2;",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    updateNotification(s, StringStatic("SQL error"));
    return;
  }
  sqlite3_bind_text(stmt, 1, content.data ? content.data : "", -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 2, id);
  StepAndFinalize(s, stmt, StringStatic(""));
}

static inline void DeleteEntryFromDB(State *s, int id) {
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db, "UPDATE entries SET deleted = 1 WHERE id = ?1;", -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    updateNotification(s, StringStatic("SQL error"));
    return;
  }
  sqlite3_bind_int(stmt, 1, id);
  StepAndFinalize(s, stmt, StringStatic("Entry deleted"));
}

static KindList GetAllKindsFromDB(State *s) {
  KindList kindList = {0};
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db,
      "SELECT DISTINCT kind FROM entries WHERE deleted IS NULL OR "
      "deleted = 0 ORDER BY kind ASC",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error failure fetching kinds: %s\n",
            sqlite3_errmsg(s->db));
  } else {
    while (sqlite3_step(stmt) == SQLITE_ROW && kindList.count < MAX_KINDS) {
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

// Populates e->kindList from the DB if the cache isn't already valid.
// Callers read e->kindList after calling this instead of calling
// GetAllKindsFromDB() directly, so the distinct-kinds list (and the
// doc_arena allocation it makes for each kind's String) is only refetched
// when something actually changed, not on every click in the list panel.
static inline void EnsureKindListCache(State *s, Element *e) {
  if (e->kindListCacheValid) {
    return;
  }
  e->kindList = GetAllKindsFromDB(s);
  e->kindListCacheValid = true;
}

// Marks the cached kind list stale. Call after anything that could add or
// remove a distinct kind: creating an entry (possibly in a new kind) or
// deleting one (possibly the last entry of its kind).
static inline void InvalidateKindListCache(Element *e) {
  e->kindListCacheValid = false;
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

// Populates e->cachedEntries/cachedEntryCount from the DB if the cache
// isn't already valid (fresh element, or invalidated by
// InvalidateEntryListCache since the last call). Callers read
// e->cachedEntries/cachedEntryCount after calling this instead of calling
// GetEntriesByKind() directly, so the list of entries for the currently
// selected kind is only re-queried when something actually changed rather
// than on every frame.
static inline void EnsureEntryListCache(State *s, Element *e) {
  if (e->entryListCacheValid) {
    return;
  }
  e->cachedEntryCount = GetEntriesByKind(s, e->selectedKind.data,
                                         e->cachedEntries, MAX_LIST_ITEMS);
  e->entryListCacheValid = true;
}

// Marks the cached entry list stale. Call after anything that changes
// which entries exist for the selected kind or their displayed fields:
// creating/deleting an entry, editing the displayed entry's content (which
// updates last_modified_at_utc), or switching selectedKind.
static inline void InvalidateEntryListCache(Element *e) {
  e->entryListCacheValid = false;
}

static inline int GetDefaultEntryId(State *s) {
  sqlite3_stmt *stmt;
  int id = 1;
  if (sqlite3_prepare_v2(
          s->db,
          "SELECT id FROM entries WHERE kind=?1 AND (deleted IS "
          "NULL OR deleted = 0) ORDER BY ID DESC LIMIT 1",
          -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, DEFAULT_ENTRY_KIND, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      id = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }
  return id;
}

static inline String GetLogFromDB(State *s) {
  int id = GetDefaultEntryId(s);
  return GetEntryContentFromDB(s, id);
}

static inline void UpdateLogInDB(State *s, String newLog) {
  int id = GetDefaultEntryId(s);
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

// Marks an editor's in-memory text as changed but not yet persisted.
// Content edits call this instead of writing to the DB immediately;
// FlushEntryContent() (called on an idle timeout and at every point that
// switches away from the entry) does the actual save.
static inline void MarkContentDirty(Element *e) {
  e->contentDirty = true;
  e->lastEditTime = GetTime();
}

// Persists an editor's content if it has unsaved changes (a no-op
// otherwise, e.g. switching between entries without typing). Routes to
// UpdateEntryContentInDB for ELEM_ENTRY_LIST or UpdateLogInDB for a plain
// ELEM_TEXT_EDITOR, matching the two editor "modes" this app has.
static inline void FlushEntryContent(State *s, Element *e) {
  if (!e->contentDirty) {
    return;
  }
  if (e->kind == ELEM_ENTRY_LIST) {
    UpdateEntryContentInDB(s, e->selectedEntryId, e->text);
    InvalidateEntryListCache(e);
  } else {
    UpdateLogInDB(s, e->text);
  }
  e->contentDirty = false;
}

// Switches an entry-list editor to display a different entry: fetches its
// content and loads it into the (gap-buffer-backed) editor. Does NOT flush
// the currently-displayed entry's content first — callers that need that
// (switching away from an entry the user was editing) call
// FlushEntryContent() themselves before this, since callers that are
// switching away from an entry that's being deleted must not save it.
static inline void SwitchToEntry(State *s, Element *e, int newEntryId) {
  e->selectedEntryId = newEntryId;
  String newText = GetEntryContentFromDB(s, newEntryId);
  LoadEntryIntoEditor(e, newText);
  StringFree(&newText);
}

static inline void make_entry_list(Arena *doc_arena, Element *e, State *s) {
  e->kind = ELEM_ENTRY_LIST;
  e->listCollapsed = false;
  e->selectedEntryId = GetDefaultEntryId(s);
  EnsureKindListCache(s, e);
  e->selectedKind = e->kindList.count > 0 ? e->kindList.kinds[0]
                                          : StringStatic(DEFAULT_ENTRY_KIND);

  String content = GetEntryContentFromDB(s, e->selectedEntryId);
  make_text_editor(doc_arena, e, content);
  e->kind = ELEM_ENTRY_LIST;
  StringFree(&content);
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_DB_H
