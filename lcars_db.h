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
static inline int CreateNewEntry(State *s, const char *kind, const char *title,
                                 String content);
static inline bool EntryExistsInDB(State *s, int id);
static inline String GetEntryContentFromDB(State *s, int id);
static inline void UpdateEntryContentInDB(State *s, int id, String content);
static inline void UpdateEntryTitleInDB(State *s, int id, String title);
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
static inline void LoadEntryIntoEditor(Arena *doc_arena, Element *e,
                                       String dbLog);
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
  assert(s != NULL);
  assert(s->db != NULL); // InitDB()/Init() must have opened it first
  assert(StringValid(sql));
  assert(StringValid(successMsg));
  assert(sql.data != NULL); // sqlite3_exec() dereferences this unconditionally

  char *zErrMsg = 0;
  int rc = sqlite3_exec(s->db, sql.data, sqlite_callback, s, &zErrMsg);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "SQL error: %s\n", zErrMsg);
    UpdateNotification(s, StringStatic("SQL error"));
    sqlite3_free(zErrMsg);
  } else {
    if (successMsg.data && successMsg.len > 0) {
      fprintf(stdout, "%s\n", successMsg.data);
      UpdateNotification(s, successMsg);
    }
  }
  return rc;
}

static inline void GetTodayDateString(char *buf, size_t bufSize) {
  assert(buf != NULL);
  // "YYYY-MM-DD" plus the terminator. strftime writes nothing at all (and
  // leaves buf untouched, not even terminated) if the result doesn't fit.
  assert(bufSize >= 11);

  time_t t = time(NULL);
  struct tm *to = localtime(&t);
  assert(to != NULL);
  size_t written = strftime(buf, bufSize, "%Y-%m-%d", to);
  (void)written; // read only by the postcondition assert below
  assert(written == 10);
}

// Steps a prepared statement expected to produce no result rows (INSERT/
// UPDATE/DELETE), reports any error via notification, and finalizes it
// either way. Returns true on success. Callers prepare the statement and
// bind its parameters before calling this.
static inline bool StepAndFinalize(State *s, sqlite3_stmt *stmt,
                                   String successMsg) {
  assert(s != NULL);
  assert(s->db != NULL);
  // Callers only reach here after sqlite3_prepare_v2 returned SQLITE_OK, so
  // a NULL statement means an unchecked prepare slipped through.
  assert(stmt != NULL);
  assert(StringValid(successMsg));

  int rc = sqlite3_step(stmt);
  bool ok = (rc == SQLITE_DONE);
  if (!ok) {
    fprintf(stderr, "SQL error: %s\n", sqlite3_errmsg(s->db));
    UpdateNotification(s, StringStatic("SQL error"));
  } else if (successMsg.data && successMsg.len > 0) {
    UpdateNotification(s, successMsg);
  }
  sqlite3_finalize(stmt);
  return ok;
}

// Inserts a new entry with the given kind/title/content and returns its id
// (0 if the insert failed).
static inline int CreateNewEntry(State *s, const char *kind, const char *title,
                                 String content) {
  assert(s != NULL);
  assert(s->db != NULL);
  // Bound with SQLITE_TRANSIENT and length -1, which means sqlite runs
  // strlen on them - a NULL here binds SQL NULL and silently creates an
  // entry no kind filter will ever find again.
  assert(kind != NULL);
  assert(title != NULL);
  assert(StringValid(content));

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db, "INSERT INTO entries (kind, title, content) VALUES (?1, ?2, ?3);",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    UpdateNotification(s, StringStatic("SQL error"));
    return 0;
  }
  sqlite3_bind_text(stmt, 1, kind, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 2, title, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 3, content.data ? content.data : "", -1,
                    SQLITE_TRANSIENT);
  if (!StepAndFinalize(s, stmt, StringStatic("New entry created"))) {
    return 0;
  }
  int newId = (int)sqlite3_last_insert_rowid(s->db);
  // The table's id is INTEGER PRIMARY KEY AUTOINCREMENT, so a successful
  // insert always produces a positive rowid. Callers pass the result
  // straight to SwitchToEntry(), where 0 means "the insert failed".
  assert(newId > 0);
  return newId;
}

static void InitDB(State *s, bool firstInit) {
  assert(s != NULL);
  assert(s->db != NULL);
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

// Whether `id` names a live (not soft-deleted) row. Callers that address an
// entry by id from outside the UI - hypermedia controls, which can be handed
// any number a document cares to write - need to tell "empty content" apart
// from "no such entry"; GetEntryContentFromDB answers "" for both.
static inline bool EntryExistsInDB(State *s, int id) {
  assert(s != NULL);
  assert(s->db != NULL);

  sqlite3_stmt *stmt;
  if (sqlite3_prepare_v2(s->db,
                         "SELECT 1 FROM entries WHERE id = ?1 AND (deleted IS "
                         "NULL OR deleted = 0);",
                         -1, &stmt, NULL) != SQLITE_OK) {
    fprintf(stderr, "SQL error checking entry %d: %s\n", id,
            sqlite3_errmsg(s->db));
    return false;
  }
  sqlite3_bind_int(stmt, 1, id);
  bool exists = (sqlite3_step(stmt) == SQLITE_ROW);
  sqlite3_finalize(stmt);
  return exists;
}

static inline String GetEntryContentFromDB(State *s, int id) {
  assert(s != NULL);
  assert(s->db != NULL);
  // NOTE: id is not asserted positive - CreateNewEntry() returns 0 on
  // failure and callers hand that straight through, where it correctly
  // matches no row and yields empty content.

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

  // Every path above assigns, including both failure paths - the caller
  // (SwitchToEntry) feeds this straight into the editor.
  assert(StringValid(output));
  return output;
}

static inline void UpdateEntryContentInDB(State *s, int id, String content) {
  assert(s != NULL);
  assert(s->db != NULL);
  assert(StringValid(content));

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db,
      "UPDATE entries SET content = ?1, last_modified_at_utc = "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?2;",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    UpdateNotification(s, StringStatic("SQL error"));
    return;
  }
  sqlite3_bind_text(stmt, 1, content.data ? content.data : "", -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 2, id);
  StepAndFinalize(s, stmt, StringStatic(""));
}

// Renames an entry. Only reachable from a hypermedia control today
// (PUT /entries/<id> with a `title` field) - the UI itself has no rename
// path, and titles are otherwise set once at creation time.
static inline void UpdateEntryTitleInDB(State *s, int id, String title) {
  assert(s != NULL);
  assert(s->db != NULL);
  assert(StringValid(title));

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db,
      "UPDATE entries SET title = ?1, last_modified_at_utc = "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc') WHERE id = ?2;",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    UpdateNotification(s, StringStatic("SQL error"));
    return;
  }
  sqlite3_bind_text(stmt, 1, title.data ? title.data : "", -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int(stmt, 2, id);
  StepAndFinalize(s, stmt, StringStatic(""));
}

static inline void DeleteEntryFromDB(State *s, int id) {
  assert(s != NULL);
  assert(s->db != NULL);
  // Guarded by `selectedEntryId != 0` at the only call site: a soft-delete
  // with a bogus id would silently mark nothing, hiding the failure.
  assert(id > 0);

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      s->db, "UPDATE entries SET deleted = 1 WHERE id = ?1;", -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    UpdateNotification(s, StringStatic("SQL error"));
    return;
  }
  sqlite3_bind_int(stmt, 1, id);
  StepAndFinalize(s, stmt, StringStatic("Entry deleted"));
}

static KindList GetAllKindsFromDB(State *s) {
  assert(s != NULL);
  assert(s->db != NULL);

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

  // The step loop is bounded by MAX_KINDS; drawing walks `count` over the
  // fixed-size kinds[] array.
  assert(kindList.count >= 0 && kindList.count <= MAX_KINDS);
  return kindList;
}

// Populates e->entryList->kindList from the DB if the cache isn't already
// valid. Callers read e->entryList->kindList after calling this instead of
// calling GetAllKindsFromDB() directly, so the distinct-kinds list (and the
// doc_arena allocation it makes for each kind's String) is only refetched
// when something actually changed, not on every click in the list panel.
static inline void EnsureKindListCache(State *s, Element *e) {
  assert(s != NULL);
  assert(e != NULL);
  assert(e->entryList != NULL);

  if (e->entryList->kindListCacheValid) {
    return;
  }
  e->entryList->kindList = GetAllKindsFromDB(s);
  e->entryList->kindListCacheValid = true;

  assert(e->entryList->kindListCacheValid);
}

// Marks the cached kind list stale. Call after anything that could add or
// remove a distinct kind: creating an entry (possibly in a new kind) or
// deleting one (possibly the last entry of its kind).
static inline void InvalidateKindListCache(Element *e) {
  assert(e != NULL);
  assert(e->entryList != NULL);
  e->entryList->kindListCacheValid = false;
}

static inline int GetEntriesByKind(State *s, const char *kind,
                                   EntryListItem *items, int maxItems) {
  assert(s != NULL);
  assert(s->db != NULL);
  // Bound with length -1, so sqlite strlen()s it.
  assert(kind != NULL);
  assert(items != NULL);
  assert(maxItems > 0);

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

  // Becomes cachedEntryCount, which both the click hit-test and the draw
  // loop use to walk cachedEntries[MAX_LIST_ITEMS].
  assert(count >= 0 && count <= maxItems);
  return count;
}

// Populates e->entryList->cachedEntries/cachedEntryCount from the DB if the
// cache isn't already valid (fresh element, or invalidated by
// InvalidateEntryListCache since the last call). Callers read
// e->entryList->cachedEntries/cachedEntryCount after calling this instead of
// calling GetEntriesByKind() directly, so the list of entries for the
// currently selected kind is only re-queried when something actually
// changed rather than on every frame.
static inline void EnsureEntryListCache(State *s, Element *e) {
  assert(s != NULL);
  assert(e != NULL);
  assert(e->entryList != NULL);
  assert(StringValid(e->entryList->selectedKind));

  if (e->entryList->entryListCacheValid) {
    return;
  }
  e->entryList->cachedEntryCount =
      GetEntriesByKind(s, e->entryList->selectedKind.data,
                       e->entryList->cachedEntries, MAX_LIST_ITEMS);
  e->entryList->entryListCacheValid = true;

  assert(e->entryList->cachedEntryCount >= 0 &&
         e->entryList->cachedEntryCount <= MAX_LIST_ITEMS);
}

// Marks the cached entry list stale. Call after anything that changes
// which entries exist for the selected kind or their displayed fields:
// creating/deleting an entry, editing the displayed entry's content (which
// updates last_modified_at_utc), or switching selectedKind.
static inline void InvalidateEntryListCache(Element *e) {
  assert(e != NULL);
  assert(e->entryList != NULL);
  e->entryList->entryListCacheValid = false;
}

static inline int GetDefaultEntryId(State *s) {
  assert(s != NULL);
  assert(s->db != NULL);

  sqlite3_stmt *stmt;
  int id = 1;
  if (sqlite3_prepare_v2(s->db,
                         "SELECT id FROM entries WHERE kind=?1 AND (deleted IS "
                         "NULL OR deleted = 0) ORDER BY ID DESC LIMIT 1",
                         -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, DEFAULT_ENTRY_KIND, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      id = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }

  // Falls back to 1 when the query fails or the table is empty, so this is
  // always a usable row id rather than 0/"no entry".
  assert(id > 0);
  return id;
}

static inline String GetLogFromDB(State *s) {
  assert(s != NULL);
  int id = GetDefaultEntryId(s);
  return GetEntryContentFromDB(s, id);
}

static inline void UpdateLogInDB(State *s, String newLog) {
  assert(s != NULL);
  assert(StringValid(newLog));
  int id = GetDefaultEntryId(s);
  UpdateEntryContentInDB(s, id, newLog);
}

// Replaces an editor's contents with `dbLog` (which lives in scratch_arena
// and is gone next frame, so everything here is copied into doc_arena).
static inline void LoadEntryIntoEditor(Arena *doc_arena, Element *e,
                                       String dbLog) {
  assert(doc_arena != NULL);
  assert(e != NULL);
  assert(e->kind == ELEM_TEXT_EDITOR || e->kind == ELEM_ENTRY_LIST);
  assert(StringValid(dbLog));

  int textLen = dbLog.data ? (int)strlen(dbLog.data) : 0;

  // The gap buffer is sized for whatever entry the editor held before, and
  // the entry being loaded can be arbitrarily longer — grow to fit rather
  // than truncating the content to the old capacity (which silently dropped
  // the tail of long entries) or copying past the end of the allocation.
  if (textLen > e->gap.capacity) {
    int newCapacity =
        e->gap.capacity > 0 ? e->gap.capacity : GAP_BUFFER_INITIAL_CAPACITY;
    while (newCapacity < textLen) {
      newCapacity *= 2;
    }
    assert(newCapacity >= textLen); // loop must not have overflowed
    e->gap.buffer = (char *)arena_alloc(doc_arena, newCapacity + 1);
    e->gap.capacity = newCapacity;
  }
  // The whole point of the growth above: the copy must fit.
  assert(textLen <= e->gap.capacity);
  if (e->gap.buffer && dbLog.data) {
    memcpy(e->gap.buffer, dbLog.data, textLen);
  }
  e->gap.gapStart = textLen;
  e->gap.gapEnd = e->gap.capacity;
  assert(GapBufferValid(&e->gap));
  assert(GapTextLen(&e->gap) == textLen);

  // Fresh copy rather than a memcpy into e->text's existing buffer: that
  // buffer was allocated for the previous (possibly much shorter) entry.
  // ReconstructText() takes over from here on the first edit.
  e->text = StringInitLen(doc_arena, dbLog.data, textLen);
  e->textLen = textLen;
  // The selection indexes the entry we just replaced; leaving it set would
  // let the next edit delete a range that no longer exists.
  e->selection.start = -1;
  e->selection.end = -1;
  e->selection.length = 0;
  e->scrollY = 0.0f;
  e->cursorY = 0.0f;
  e->snapToCursor = 2;

  // The editor now shows exactly this entry: text, cached length and gap
  // all agree, and no selection survives from the previous entry.
  assert(StringValid(e->text));
  assert(e->textLen == textLen && e->text.len == textLen);
  assert(e->selection.start == -1 && e->selection.end == -1 &&
         e->selection.length == 0);
}

// Marks an editor's in-memory text as changed but not yet persisted.
// Content edits call this instead of writing to the DB immediately;
// FlushEntryContent() (called on an idle timeout and at every point that
// switches away from the entry) does the actual save.
static inline void MarkContentDirty(Element *e) {
  assert(e != NULL);
  assert(e->kind == ELEM_TEXT_EDITOR || e->kind == ELEM_ENTRY_LIST);
  e->contentDirty = true;
  e->lastEditTime = GetTime();
}

// Persists an editor's content if it has unsaved changes (a no-op
// otherwise, e.g. switching between entries without typing). Routes to
// UpdateEntryContentInDB for ELEM_ENTRY_LIST or UpdateLogInDB for a plain
// ELEM_TEXT_EDITOR, matching the two editor "modes" this app has.
static inline void FlushEntryContent(State *s, Element *e) {
  assert(s != NULL);
  assert(e != NULL);
  // Only the two editor kinds carry content to persist; FlushPendingSaves()
  // and the debounce path both filter on kind before calling.
  assert(e->kind == ELEM_TEXT_EDITOR || e->kind == ELEM_ENTRY_LIST);
  // This is what actually gets written to lcars.db - a String whose len and
  // terminator disagree would persist a truncated or over-long entry.
  assert(StringValid(e->text));

  if (!e->contentDirty) {
    return;
  }
  if (e->kind == ELEM_ENTRY_LIST) {
    assert(e->entryList != NULL);
    UpdateEntryContentInDB(s, e->entryList->selectedEntryId, e->text);
    InvalidateEntryListCache(e);
  } else if (e->bindsToLog) {
    UpdateLogInDB(s, e->text);
  }
  // Anything else - a URL bar, a form field, any editor the document didn't
  // bind to an entry - is scratch text that belongs to the document, not to
  // the journal. It still clears the dirty flag: nothing is going to persist
  // it, so leaving it set would just re-run this every frame. Documents that
  // want typed text stored say so with a control (lc-put="/entries/...").
  e->contentDirty = false;

  assert(!e->contentDirty);
}

// Switches an entry-list editor to display a different entry: fetches its
// content and loads it into the (gap-buffer-backed) editor. Does NOT flush
// the currently-displayed entry's content first — callers that need that
// (switching away from an entry the user was editing) call
// FlushEntryContent() themselves before this, since callers that are
// switching away from an entry that's being deleted must not save it.
static inline void SwitchToEntry(State *s, Element *e, int newEntryId) {
  assert(s != NULL);
  assert(e != NULL);
  assert(e->kind == ELEM_ENTRY_LIST);
  assert(e->entryList != NULL);

  e->entryList->selectedEntryId = newEntryId;
  String newText = GetEntryContentFromDB(s, newEntryId);
  LoadEntryIntoEditor(&s->doc_arena, e, newText);
  StringClear(&newText);

  assert(e->entryList->selectedEntryId == newEntryId);
  // Every caller either flushes first or deliberately discards (the delete
  // path). A still-dirty editor here means the *previous* entry's unsaved
  // edits would be written out under the new entry's id on the next flush.
  assert(!e->contentDirty);
}

static inline void make_entry_list(Arena *doc_arena, Element *e, State *s) {
  assert(doc_arena != NULL);
  assert(e != NULL);
  assert(s != NULL);
  assert(s->db != NULL);

  e->kind = ELEM_ENTRY_LIST;
  e->entryList = arena_alloc(doc_arena, sizeof(EntryListState));
  e->entryList->listCollapsed = false;
  e->entryList->selectedEntryId = GetDefaultEntryId(s);
  EnsureKindListCache(s, e);
  e->entryList->selectedKind = e->entryList->kindList.count > 0
                                   ? e->entryList->kindList.kinds[0]
                                   : StringStatic(DEFAULT_ENTRY_KIND);

  String content = GetEntryContentFromDB(s, e->entryList->selectedEntryId);
  make_text_editor(doc_arena, e, content);
  // make_text_editor() sets ELEM_TEXT_EDITOR; restore the real kind.
  e->kind = ELEM_ENTRY_LIST;
  StringClear(&content);

  assert(e->kind == ELEM_ENTRY_LIST);
  assert(e->entryList != NULL);
  assert(StringValid(e->entryList->selectedKind));
  assert(GapBufferValid(&e->gap)); // the editor half must be usable too
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_DB_H
