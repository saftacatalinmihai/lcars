#ifndef LCARS_VAULT_H
#define LCARS_VAULT_H

// Classified entries, the server's half (docs/design/confidential-entries.md).
//
// A Secret entry (classification 2) is encrypted in the browser: its title,
// text and numbers are sealed into one envelope (`sealed`, "lcs1.<header>.
// <ciphertext>", AES-256-GCM under the journal's master key) and its own
// columns stay empty, so every reader that knows nothing of classification
// already sees an empty entry. The server never holds the password, the key
// or a Secret entry's plaintext, and has no crypto of its own beyond the
// SHA-256 of the guard below.
//
//   GET /vault                   {"version": n, "vault": {...}|null}
//   PUT /vault {"vault": {...}, "token": "<hex>"[, "new_token": "<hex>"],
//               "version": n}
//
// The vault is the key material: the master key wrapped by a key derived
// from the password (and, later, by a recovery code or a passkey: `wraps` is
// a list). It is a table of its own rather than an entry: it must not be in
// /dump, in the page's mirror, or writable through PATCH /entries, and no
// limited login may read it (a copy is an offline guessing target) or write
// it (lcars_logins.h refuses /vault outright).
//
// The guard. Anyone with the main login's password (and on this box that is
// every agent with a shell: it is in ~/.env) could otherwise replace the
// vault with one wrapping a key of its own, and read every Secret entry
// written after. So the vault, and the classified columns of every entry,
// change only for a request that proves it holds the master key: the page
// derives a token from it (HKDF, "lcars vault token v1"), and the server
// keeps that token's SHA-256 (auth_hash), never the token. The first PUT,
// when there is no vault, is the one write with nothing to prove; it sets
// the hash. After it, PUT /vault needs the token and the version it read
// (a 409 if another device wrote in between), and an entry write that sets
// `classification` or `sealed` needs the token in X-LCARS-Vault
// (HandlePostEntry, HandleUpdateEntry). That last is integrity, not secrecy:
// without it an agent could not read a Secret entry, but could lower it to
// plaintext and so destroy it.
//
// A module of lcars_http.h, included from inside its implementation block.

#include <stdbool.h>

#define CLASSIFIED_SECRET 2
// The envelope's prefix; the page's `clsEnvelope` writes it.
#define CLASSIFIED_ENVELOPE_PREFIX "lcs1."
// The vault's JSON: a few wraps of a 32-byte key, a few hundred bytes each.
#define VAULT_BODY_MAX (16 * 1024)
// A token is 32 bytes as hex.
#define VAULT_TOKEN_HEX 64

static bool ClassifiedEnvelopeValid(const char *s);
static bool ClassifiedLevelKnown(int level);
static int VaultTokenCheck(sqlite3 *db, const char *token);
static void ClassifiedRaiseCleanup(sqlite3 *db, int id);
static void ClassifiedCheckpoint(sqlite3 *db);
static int HandleVault(int client_fd, Arena *arena, const char *method,
                       const char *body, const char *content_type);

#ifdef LCARS_VAULT_IMPLEMENTATION

#define LCARS_SHA256_IMPLEMENTATION
#include "lcars_sha256.h"

// Phase 1 knows two levels. Confidential (1) is designed (phase 2) but its
// skips are not built, so a row may not claim it yet: a level the readers
// do not honour would be a promise nobody keeps.
static bool ClassifiedLevelKnown(int level) {
  return level == 0 || level == CLASSIFIED_SECRET;
}

// An envelope as the page writes it: the prefix, then base64url and dots.
// The server cannot check the ciphertext (it has no key, by design); this
// only refuses plaintext, or anything else, in the envelope's place.
static bool ClassifiedEnvelopeValid(const char *s) {
  assert(s != NULL);
  size_t n = strlen(CLASSIFIED_ENVELOPE_PREFIX);
  if (strncmp(s, CLASSIFIED_ENVELOPE_PREFIX, n) != 0 || s[n] == '\0') {
    return false;
  }
  for (const char *c = s + n; *c; c++) {
    if (!isalnum((unsigned char)*c) && *c != '-' && *c != '_' && *c != '.') {
      return false;
    }
  }
  return true;
}

static void VaultEnsureTable(sqlite3 *db) {
  assert(db != NULL);
  sqlite3_exec(db,
               "CREATE TABLE IF NOT EXISTS vault ("
               "id INTEGER PRIMARY KEY CHECK (id = 1),"
               "body TEXT NOT NULL,"
               "auth_hash TEXT NOT NULL,"
               "version INTEGER NOT NULL,"
               "modified_at_utc TEXT NOT NULL);",
               NULL, NULL, NULL);
}

static bool VaultTokenShaped(const char *t) {
  if (t == NULL || strlen(t) != VAULT_TOKEN_HEX) {
    return false;
  }
  for (const char *c = t; *c; c++) {
    if (!isxdigit((unsigned char)*c)) {
      return false;
    }
  }
  return true;
}

// 1 the token is the vault's, 0 it is not (or is missing), -1 there is no
// vault. The token is hashed as the hex text it is sent as, lowercased, so
// "AB" and "ab" are one token.
static int VaultTokenCheck(sqlite3 *db, const char *token) {
  assert(db != NULL);
  VaultEnsureTable(db);
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(db, "SELECT auth_hash FROM vault WHERE id = 1;", -1,
                         &st, NULL) != SQLITE_OK) {
    return 0;
  }
  int r = -1;
  if (sqlite3_step(st) == SQLITE_ROW) {
    r = 0;
    const char *want = (const char *)sqlite3_column_text(st, 0);
    if (want && VaultTokenShaped(token)) {
      char low[VAULT_TOKEN_HEX + 1];
      for (int i = 0; i < VAULT_TOKEN_HEX; i++) {
        low[i] = (char)tolower((unsigned char)token[i]);
      }
      low[VAULT_TOKEN_HEX] = '\0';
      char got[65];
      Sha256Hex(low, VAULT_TOKEN_HEX, got);
      // Not constant-time, and need not be: what is compared is a hash of
      // the token, so timing tells an attacker about a hash they would
      // still have to invert.
      r = strcmp(got, want) == 0 ? 1 : 0;
    }
  }
  sqlite3_finalize(st);
  return r;
}

// What raising an entry to Secret leaves behind, removed in the writer's own
// transaction: the vector made from its plaintext and its CalDAV row (the
// task leaves the lists; a client's next sync sees it gone). Both tables are
// made on first use, so on a journal without one the DELETE fails with "no
// such table", which is the same as nothing to delete.
static void ClassifiedRaiseCleanup(sqlite3 *db, int id) {
  assert(db != NULL && id > 0);
  static const char *const sqls[] = {
      "DELETE FROM entry_embeddings WHERE entry_id = ?1;",
      "DELETE FROM caldav_tasks WHERE entry_id = ?1;",
  };
  for (size_t i = 0; i < sizeof(sqls) / sizeof(sqls[0]); i++) {
    sqlite3_stmt *st = NULL;
    if (sqlite3_prepare_v2(db, sqls[i], -1, &st, NULL) != SQLITE_OK) {
      continue;
    }
    sqlite3_bind_int(st, 1, id);
    sqlite3_step(st);
    sqlite3_finalize(st);
  }
}

// After a raise has committed: the WAL folded into the file and cut to
// nothing, so the old plaintext's page images in it are gone from the
// file too (secure_delete, set on every connection by OpenHTTPDB, has
// already zeroed what the UPDATE freed in the pages themselves). A reader
// holding an older snapshot keeps the checkpoint from finishing; that is
// logged, and the next raise's checkpoint (or sqlite's own) finishes it.
static void ClassifiedCheckpoint(sqlite3 *db) {
  assert(db != NULL);
  int log = 0, done = 0;
  int rc = sqlite3_wal_checkpoint_v2(db, NULL, SQLITE_CHECKPOINT_TRUNCATE, &log,
                                     &done);
  if (rc != SQLITE_OK) {
    printf("Classified: checkpoint after a raise did not finish (%s): "
           "%d of %d frames\n",
           sqlite3_errstr(rc), done, log);
  }
}

static int HandleVaultGet(int client_fd, Arena *arena, sqlite3 *db) {
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(db, "SELECT body, version FROM vault WHERE id = 1;",
                         -1, &st, NULL) != SQLITE_OK) {
    return SendJSONError(client_fd, 500, "Failed to read the vault: %s",
                         sqlite3_errmsg(db));
  }
  JSONBuf out;
  jsonbuf_init(&out, arena);
  if (sqlite3_step(st) == SQLITE_ROW) {
    // the body was checked to be a JSON object when it was written
    jsonbuf_appendf(&out,
                    "{\"version\":%d,\"vault\":", sqlite3_column_int(st, 1));
    jsonbuf_append(&out, (const char *)sqlite3_column_text(st, 0));
    jsonbuf_append(&out, "}");
  } else {
    jsonbuf_append(&out, "{\"version\":0,\"vault\":null}");
  }
  sqlite3_finalize(st);
  return SendJSONBuf(client_fd, &out);
}

// The wraps a vault must keep: exactly one of type "password". A passkey
// or a recovery code is one more way in, never the only one - a passkey
// lives on a device that can be lost, and the password is the fallback the
// design promises (section 6) - so a vault that drops it, or holds two (which
// would the page rewrap on a change?), is refused here as well as in the page.
static bool VaultPasswordWrapKept(JsonSpan vault) {
  JsonSpan wraps;
  if (!json_member(vault, "wraps", &wraps) || wraps.len < 2 ||
      wraps.data[0] != '[') {
    return false;
  }
  int passwords = 0;
  const char *cursor = NULL;
  JsonSpan w;
  while (json_array_next(wraps, &cursor, &w)) {
    JsonSpan type;
    if (w.len < 2 || w.data[0] != '{' || !json_member(w, "type", &type)) {
      return false; // a wrap with no type: not a vault the page wrote
    }
    if (type.len == 10 && memcmp(type.data, "\"password\"", 10) == 0) {
      passwords++;
    }
  }
  return passwords == 1;
}

static int HandleVaultPut(int client_fd, Arena *arena, sqlite3 *db,
                          const char *body) {
  JsonSpan root = {body, strlen(body)};
  JsonSpan v;
  if (!json_member(root, "vault", &v) || v.len < 2 || v.data[0] != '{') {
    return SendJSONError(client_fd, 400,
                         "PUT /vault takes {\"vault\": {...}, "
                         "\"token\", \"version\"}");
  }
  if (v.len > VAULT_BODY_MAX) {
    return SendJSONError(client_fd, 413, "a vault is at most %d bytes",
                         VAULT_BODY_MAX);
  }
  if (!VaultPasswordWrapKept(v)) {
    return SendJSONError(client_fd, 400,
                         "a vault keeps exactly one password wrap: a passkey "
                         "or a recovery code is never the only way in");
  }
  char token[VAULT_TOKEN_HEX + 2] = {0};
  char new_token[VAULT_TOKEN_HEX + 2] = {0};
  json_get_string(body, "token", token, sizeof(token));
  bool rotate =
      json_get_string(body, "new_token", new_token, sizeof(new_token));
  int version = -1;
  json_get_int(body, "version", &version);
  if (!VaultTokenShaped(token) || (rotate && !VaultTokenShaped(new_token))) {
    return SendJSONError(client_fd, 400, "a token is %d hex characters",
                         VAULT_TOKEN_HEX);
  }

  if (sqlite3_exec(db, "BEGIN IMMEDIATE;", NULL, NULL, NULL) != SQLITE_OK) {
    return SendJSONError(client_fd, 503, "the journal is busy: %s",
                         sqlite3_errmsg(db));
  }
  int status = 0;
  int have = -1; // the stored version, -1 none
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(db, "SELECT version FROM vault WHERE id = 1;", -1, &st,
                         NULL) == SQLITE_OK) {
    if (sqlite3_step(st) == SQLITE_ROW) {
      have = sqlite3_column_int(st, 0);
    }
    sqlite3_finalize(st);
  }
  const char *hash_of = token; // the hash to store: the token's, or the new
  if (have < 0) {
    // The first vault: nothing to prove. version 0 (or none) says the page
    // knew there was none, so two devices setting one at once do not both win.
    if (version > 0) {
      status = SendJSONError(client_fd, 409, "there is no vault (version 0)");
    }
  } else if (VaultTokenCheck(db, token) != 1) {
    status = SendJSONError(client_fd, 403,
                           "the vault's token does not match: unlock first");
  } else if (version != have) {
    status = SendJSONError(client_fd, 409,
                           "the vault changed (version %d, read %d): read it "
                           "again",
                           have, version);
  } else if (rotate) {
    hash_of = new_token;
  }

  char hash[65] = {0};
  if (status == 0) {
    char low[VAULT_TOKEN_HEX + 1];
    for (int i = 0; i < VAULT_TOKEN_HEX; i++) {
      low[i] = (char)tolower((unsigned char)hash_of[i]);
    }
    low[VAULT_TOKEN_HEX] = '\0';
    Sha256Hex(low, VAULT_TOKEN_HEX, hash);
    char *copy = arena_alloc(arena, v.len + 1);
    memcpy(copy, v.data, v.len);
    copy[v.len] = '\0';
    if (sqlite3_prepare_v2(
            db,
            "INSERT INTO vault (id, body, auth_hash, version, modified_at_utc) "
            "VALUES (1, ?1, ?2, ?3, strftime('%Y-%m-%d %H:%M:%S', 'now', "
            "'utc')) ON CONFLICT(id) DO UPDATE SET body = excluded.body, "
            "auth_hash = excluded.auth_hash, version = excluded.version, "
            "modified_at_utc = excluded.modified_at_utc;",
            -1, &st, NULL) != SQLITE_OK) {
      status = SendJSONError(client_fd, 500, "Failed to write the vault: %s",
                             sqlite3_errmsg(db));
    } else {
      sqlite3_bind_text(st, 1, copy, -1, SQLITE_STATIC);
      sqlite3_bind_text(st, 2, hash, -1, SQLITE_STATIC);
      sqlite3_bind_int(st, 3, have < 0 ? 1 : have + 1);
      if (sqlite3_step(st) != SQLITE_DONE) {
        status = SendJSONError(client_fd, 500, "Failed to write the vault: %s",
                               sqlite3_errmsg(db));
      }
      sqlite3_finalize(st);
    }
  }
  if (status == 0 &&
      sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL) != SQLITE_OK) {
    status = SendJSONError(client_fd, 500, "Vault not committed: %s",
                           sqlite3_errmsg(db));
  }
  if (status != 0) {
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return status;
  }
  printf("Classified: the vault %s (version %d)\n",
         have < 0 ? "set"
         : rotate ? "rewritten, new token"
                  : "rewritten",
         have < 0 ? 1 : have + 1);
  char resp[64];
  int n = snprintf(resp, sizeof(resp), "{\"status\":\"ok\",\"version\":%d}",
                   have < 0 ? 1 : have + 1);
  assert(n > 0 && n < (int)sizeof(resp));
  return SendJSON(client_fd, 200, resp, (size_t)n);
}

static int HandleVault(int client_fd, Arena *arena, const char *method,
                       const char *body, const char *content_type) {
  assert(client_fd >= 0 && arena_valid(arena));
  assert(method != NULL && body != NULL && content_type != NULL);
  // lcars_logins.h refuses /vault to the limited logins before this
  assert(g_conn_login == NULL);
  bool get = strcmp(method, "GET") == 0;
  if (!get && strcmp(method, "PUT") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on /vault",
                         method);
  }
  if (!get && strstr(content_type, "application/json") == NULL) {
    return SendJSONError(client_fd, 400, "PUT /vault takes a JSON body");
  }
  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  VaultEnsureTable(db);
  int status = get ? HandleVaultGet(client_fd, arena, db)
                   : HandleVaultPut(client_fd, arena, db, body);
  sqlite3_close(db);
  return status;
}

#endif // LCARS_VAULT_IMPLEMENTATION

#endif // LCARS_VAULT_H
