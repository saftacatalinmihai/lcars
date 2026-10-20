#ifndef LCARS_EMBED_H
#define LCARS_EMBED_H

// Embeddings: every entry as a vector, so the web UI can chart the journal
// by meaning (the star chart) and find "related" entries by what they are
// about rather than by the words they happen to share.
//
//   GET  /embeddings[?since=<stamp>]   every live entry's vector, int8, base64
//   POST /embed  {"text": "..."}       one query's vector, same encoding
//
// The model is not in this process. Vectors come from any OpenAI-compatible
// /v1/embeddings endpoint: by default a llama-server on this box
// (lcars-embed.service, multilingual-e5-small - the journal is English and
// Romanian, and an English-only model puts every Romanian entry in one
// cluster of its own), and just as well OpenAI or any hosted service:
//
//   LCARS_EMBED=0          off: no indexer, both routes answer 503
//   LCARS_EMBED_URL        default http://127.0.0.1:8091/v1/embeddings
//   LCARS_EMBED_MODEL      default multilingual-e5-small; sent as "model",
//                          and stored per row, so changing it re-embeds
//                          the whole journal in the background
//   LCARS_EMBED_KEY        a bearer token, for a hosted service
//
// The e5 family was trained with "passage: " and "query: " in front of the
// text and is measurably worse without them, so a model whose name contains
// "e5" gets them; nothing else does.
//
// An indexer thread keeps `entry_embeddings` (a side table, created on
// first use like entry_media and caldav_tasks) in step with the entries: it
// polls for rows with no vector, a vector from another model, or one made
// from an older last_modified_at_utc, and embeds them a batch at a time. A
// row is only picked up once it has sat unedited for EMBED_SETTLE_SECONDS,
// or a debounced save a second would re-embed an entry for every sentence
// typed into it.
//
// Vectors are stored and served as int8 - each one scaled so its largest
// component is 127. A 384-dimension vector is then 384 bytes rather than
// 1536, the whole journal about 1.4MB, and the cosine error of the rounding
// is well under the gap between an entry's nearest neighbour and its tenth.
// Cosine does not care about the scale, so nothing is lost by the client
// not knowing it.
//
// A module of lcars_http.h, like lcars_media.h: it uses that file's response
// helpers and is included from inside its LCARS_HTTP_IMPLEMENTATION block.

static void StartEmbedIndexer(void);
static int HandleEmbeddings(int client_fd, Arena *arena, const char *query);
static int HandleEmbed(int client_fd, Arena *arena, const char *body,
                       const char *content_type);

#ifdef LCARS_EMBED_IMPLEMENTATION

#include <ctype.h>
#include <curl/curl.h>
#include <math.h>
#include <time.h>

#include "lcars_json.h"

#define EMBED_DEFAULT_URL "http://127.0.0.1:8091/v1/embeddings"
#define EMBED_DEFAULT_MODEL "multilingual-e5-small"
// How an entry is turned into text (EmbedEntryText). Stored with the model's
// name, so a change to the recipe re-embeds the journal the same way a
// change of model does.
#define EMBED_RECIPE "3"
// The widest vector accepted. OpenAI's text-embedding-3-large is 3072.
#define EMBED_MAX_DIM 4096
// Entries per request. llama-server takes them as one batch; more than this
// and a single slow request holds the indexer for longer than it is worth.
#define EMBED_BATCH 16
// How much of an entry is embedded, in bytes. e5-small reads 512 tokens and
// no more, and Romanian runs about 2.5 bytes a token against English's
// four. But the tighter limit is memory: llama-server reserves a vocabulary-
// sized row of logits for every token it is given, even when it only
// embeds, and this model's vocabulary is 250,000 tokens - a megabyte a
// token, held until the server next sleeps. 800 bytes is at most ~350
// tokens, so ~350MB at the peak on a 2GB box; markdown-heavy text that
// tokenizes worse than that is caught by EmbedOne's halving. The start of an
// entry is also what it is about: a 200KB paste is not about its last
// paragraph.
#define EMBED_TEXT_BYTES 800
// Characters of content read from the database per row, which is more than
// EMBED_TEXT_BYTES can keep even when every character is one byte.
#define EMBED_CONTENT_CHARS 1400
// A text shorter than this is not embedded; a row still gets a dim-0 vector,
// which records "looked at, nothing to say" so it is not asked about again.
#define EMBED_MIN_TEXT_BYTES 3
// How long a row must sit unedited before it is embedded.
#define EMBED_SETTLE_SECONDS 60
// Poll interval when there is nothing to do, and the wait after the service
// could not be reached - long enough that a laptop without one does not
// spend its log on saying so.
#define EMBED_IDLE_SECONDS 30
#define EMBED_BACKOFF_SECONDS 300
#define EMBED_TIMEOUT_SECONDS 120
// A query sent to POST /embed.
#define EMBED_QUERY_BYTES 2000
// The indexer's arena, on its own thread's stack: one batch's request body
// and response (16 x 384 floats as JSON is ~140KB; 16 x 3072 ~1.1MB).
#define EMBED_ARENA_BYTES (4 * 1024 * 1024)
#define EMBED_THREAD_STACK_BYTES (EMBED_ARENA_BYTES + 2 * 1024 * 1024)
// Cap on one embeddings response read into an arena: a whole batch for the
// indexer, and one vector for POST /embed, whose arena is the connection's
// 1MB (one 4096-dimension vector is ~90KB of JSON).
#define EMBED_BATCH_RESPONSE_MAX (2 * 1024 * 1024)
#define EMBED_QUERY_RESPONSE_MAX (256 * 1024)
// A log line about a failed request: room for the whole configured URL
// (EmbedConfig.url) and curl's or the service's own message after it.
#define EMBED_ERR_BYTES 800

typedef struct EmbedConfig {
  bool on;
  bool e5; // prefixes "passage: " / "query: "
  char url[512];
  char model[128];
  char key[160];  // model + EMBED_RECIPE: what a stored vector is tagged with
  char auth[320]; // "Authorization: Bearer <key>", or empty
} EmbedConfig;

// Filled once by StartEmbedIndexer, before the indexer thread and before the
// server accepts its first connection, and never written again - so every
// thread reads it without a lock.
static EmbedConfig g_embed;
// Whether the service answered the last request made of it: 1 it did (with
// vectors or a refusal, an answer either way), -1 it could not be reached,
// 0 not asked yet. GET /features reads it (lcars_features.h) rather than
// asking the network itself; the indexer asks once at start, so it is
// known within a request's time of the server coming up.
static atomic_int g_embed_answering;

static void EmbedConfigInit(void) {
  const char *on = getenv("LCARS_EMBED");
  g_embed.on = !(on && strcmp(on, "0") == 0);
  const char *url = getenv("LCARS_EMBED_URL");
  const char *model = getenv("LCARS_EMBED_MODEL");
  const char *key = getenv("LCARS_EMBED_KEY");
  snprintf(g_embed.url, sizeof(g_embed.url), "%s",
           (url && url[0]) ? url : EMBED_DEFAULT_URL);
  snprintf(g_embed.model, sizeof(g_embed.model), "%s",
           (model && model[0]) ? model : EMBED_DEFAULT_MODEL);
  g_embed.auth[0] = '\0';
  if (key && key[0]) {
    snprintf(g_embed.auth, sizeof(g_embed.auth), "Authorization: Bearer %s",
             key);
  }
  g_embed.e5 = strstr(g_embed.model, "e5") != NULL;
  snprintf(g_embed.key, sizeof(g_embed.key), "%s@" EMBED_RECIPE,
           g_embed.model);
}

static bool EnsureEmbedTable(sqlite3 *db) {
  assert(db != NULL);
  // entry_id is the key: one vector per entry, replaced when it goes stale.
  // source_modified is the entry's last_modified_at_utc the vector was made
  // from - comparing the two is the whole staleness test.
  const char *sql = "CREATE TABLE IF NOT EXISTS entry_embeddings ("
                    "entry_id INTEGER PRIMARY KEY,"
                    "model TEXT NOT NULL,"
                    "source_modified TEXT NOT NULL,"
                    "dim INTEGER NOT NULL,"
                    "vec BLOB NOT NULL,"
                    "embedded_at_utc TEXT NOT NULL);"
                    "CREATE INDEX IF NOT EXISTS entry_embeddings_at "
                    "ON entry_embeddings(embedded_at_utc);";
  char *err = NULL;
  if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
    printf("Embed: cannot create entry_embeddings: %s\n", err ? err : "?");
    sqlite3_free(err);
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// The embedding service
// ---------------------------------------------------------------------------

typedef struct EmbedResponse {
  char *data;
  size_t len;
  size_t cap;
  bool overflow;
} EmbedResponse;

static size_t EmbedCurlWrite(char *ptr, size_t size, size_t nmemb, void *ud) {
  EmbedResponse *r = (EmbedResponse *)ud;
  assert(r != NULL && r->data != NULL);
  size_t n = size * nmemb;
  if (r->len + n + 1 > r->cap) {
    // Returning short makes curl fail the transfer, which is what an
    // answer bigger than any batch could produce deserves.
    r->overflow = true;
    return 0;
  }
  memcpy(r->data + r->len, ptr, n);
  r->len += n;
  r->data[r->len] = '\0';
  assert(r->len < r->cap);
  return n;
}

// What a failed request was, which decides what the caller does next: a
// service that is not there is waited out, a request it refused is split up.
typedef enum EmbedFail {
  EMBED_OK = 0,
  EMBED_UNREACHABLE, // no connection, a timeout, or a 5xx other than 500
  EMBED_REFUSED,     // an answer that said no: too long, bad input, a 500
} EmbedFail;

// Embeds `count` texts. On success *out_dim is the model's dimension and
// `out` (count * EMBED_MAX_DIM floats) holds the vectors, row i at
// out + i * dim. `err` gets a line for the log either way.
static EmbedFail EmbedRequest(Arena *arena, const char *const *texts, int count,
                              bool query, size_t resp_cap, float *out,
                              int *out_dim, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(texts != NULL && count > 0 && count <= EMBED_BATCH);
  assert(resp_cap >= 4096 && resp_cap <= EMBED_BATCH_RESPONSE_MAX);
  assert(out != NULL && out_dim != NULL);
  assert(err != NULL && err_size > 0);

  err[0] = '\0';
  *out_dim = 0;
  ArenaMark mark = arena_mark(arena);

  JSONBuf req;
  jsonbuf_init(&req, arena);
  jsonbuf_append(&req, "{\"model\":");
  jsonbuf_append_json_string(&req, g_embed.model);
  jsonbuf_append(&req, ",\"encoding_format\":\"float\",\"input\":[");
  for (int i = 0; i < count; i++) {
    assert(texts[i] != NULL);
    if (i > 0) {
      jsonbuf_append(&req, ",");
    }
    // e5's prefix is part of the text it was trained on, so it goes inside
    // the string rather than beside it.
    const char *pre = !g_embed.e5 ? "" : (query ? "query: " : "passage: ");
    size_t pl = strlen(pre), tl = strlen(texts[i]);
    char *t = arena_alloc(arena, pl + tl + 1);
    memcpy(t, pre, pl);
    memcpy(t + pl, texts[i], tl + 1);
    jsonbuf_append_json_string(&req, t);
  }
  jsonbuf_append(&req, "]}");
  if (req.overflow) {
    snprintf(err, err_size, "request does not fit the arena");
    arena_restore(arena, mark);
    return EMBED_REFUSED;
  }

  EmbedResponse resp;
  resp.cap = resp_cap;
  resp.data = arena_alloc(arena, resp.cap);
  resp.len = 0;
  resp.overflow = false;
  resp.data[0] = '\0';

  CURL *curl = curl_easy_init();
  if (!curl) {
    snprintf(err, err_size, "curl_easy_init failed");
    arena_restore(arena, mark);
    return EMBED_UNREACHABLE;
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)
  struct curl_slist *headers =
      curl_slist_append(NULL, "Content-Type: application/json");
  if (g_embed.auth[0]) {
    headers = curl_slist_append(headers, g_embed.auth);
  }
  curl_easy_setopt(curl, CURLOPT_URL, g_embed.url);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, req.data);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)req.len);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, EmbedCurlWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)EMBED_TIMEOUT_SECONDS);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 5L);
  // Threads and signals: curl's DNS timeout uses SIGALRM unless told not
  // to, and this runs on threads that are not the main one.
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  CURLcode rc = curl_easy_perform(curl);
  long http = 0;
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);

  EmbedFail fail = EMBED_OK;
  if (rc != CURLE_OK) {
    snprintf(err, err_size, "%s: %s", g_embed.url, curl_easy_strerror(rc));
    fail = resp.overflow ? EMBED_REFUSED : EMBED_UNREACHABLE;
  } else if (http != 200) {
    // llama-server answers 500 for an input over its batch size, which is
    // this request's fault rather than the service's; 502-504 are a proxy
    // in front of a service that is not there.
    JsonSpan top = {resp.data, resp.len}, e, m;
    const char *msg = "";
    if (json_member(top, "error", &e) && json_member(e, "message", &m)) {
      msg = json_span_string(arena, m);
    }
    snprintf(err, err_size, "HTTP %ld %s", http, msg);
    fail = (http >= 502 || http == 429) ? EMBED_UNREACHABLE : EMBED_REFUSED;
  }
  atomic_store(&g_embed_answering, fail == EMBED_UNREACHABLE ? -1 : 1);
  if (fail != EMBED_OK) {
    arena_restore(arena, mark);
    return fail;
  }

  // {"data":[{"index":0,"embedding":[...]}, ...]} - in index order from
  // every service seen, but placed by "index" regardless.
  JsonSpan top = {resp.data, resp.len}, data, item;
  if (!json_member(top, "data", &data)) {
    snprintf(err, err_size, "answer has no \"data\"");
    arena_restore(arena, mark);
    return EMBED_REFUSED;
  }
  int dim = 0, got = 0;
  const char *cur = NULL;
  while (json_array_next(data, &cur, &item)) {
    JsonSpan idx, emb, num;
    if (!json_member(item, "index", &idx) ||
        !json_member(item, "embedding", &emb)) {
      continue;
    }
    long i = json_span_long(idx);
    if (i < 0 || i >= count) {
      continue;
    }
    int n = 0;
    const char *nc = NULL;
    float *row = out + (size_t)i * EMBED_MAX_DIM;
    while (json_array_next(emb, &nc, &num) && n < EMBED_MAX_DIM) {
      row[n++] = (float)json_span_double(num);
    }
    if (n == 0 || (dim != 0 && n != dim)) {
      snprintf(err, err_size, "vector %ld has %d dimensions", i, n);
      arena_restore(arena, mark);
      return EMBED_REFUSED;
    }
    dim = n;
    got++;
  }
  arena_restore(arena, mark);
  if (got != count) {
    snprintf(err, err_size, "asked for %d vectors, got %d", count, got);
    return EMBED_REFUSED;
  }
  assert(dim > 0 && dim <= EMBED_MAX_DIM);
  *out_dim = dim;
  return EMBED_OK;
}

// int8, scaled so the largest component is 127 (see the header comment).
static void EmbedQuantize(const float *v, int dim, int8_t *q) {
  assert(v != NULL && q != NULL);
  assert(dim > 0 && dim <= EMBED_MAX_DIM);
  float m = 0.0f;
  for (int i = 0; i < dim; i++) {
    float a = fabsf(v[i]);
    if (a > m) {
      m = a;
    }
  }
  float s = m > 0.0f ? 127.0f / m : 0.0f;
  for (int i = 0; i < dim; i++) {
    long x = lrintf(v[i] * s);
    q[i] = (int8_t)(x > 127 ? 127 : (x < -127 ? -127 : x));
  }
}

// ---------------------------------------------------------------------------
// The indexer
// ---------------------------------------------------------------------------

// Whether a line is a property - Logseq's and Capacities' `key:: value` -
// which says how an entry was filed rather than what it is about.
static bool EmbedIsProperty(const char *p, const char *end) {
  assert(p != NULL && end != NULL && p <= end);
  const char *q = p;
  while (q < end && (isalnum((unsigned char)*q) || *q == '_' || *q == '-')) {
    q++;
  }
  return q > p && q + 1 < end && q[0] == ':' && q[1] == ':';
}

// Appends one body line to `out`, cleaned of the notation that carries no
// meaning: outline bullets, the brackets of [[links]] and ((refs)), and
// every URL but its host. Left in, those are most of what a short imported
// page consists of, and e5 charted the imports by their punctuation - every
// "- [[Name]] -" page beside every other, whatever the name.
static size_t EmbedCleanLine(char *out, size_t n, const char *p,
                             const char *end) {
  assert(out != NULL && p != NULL && end != NULL && p <= end);
  while (p < end && (*p == ' ' || *p == '\t' || *p == '\r')) {
    p++;
  }
  if (end - p >= 2 && (p[0] == '-' || p[0] == '*') && p[1] == ' ') {
    p += 2;
  }
  if (p >= end || EmbedIsProperty(p, end)) {
    return n;
  }
  size_t start = n;
  while (p < end) {
    if (end - p >= 2 && ((p[0] == '[' && p[1] == '[') ||
                         (p[0] == ']' && p[1] == ']') ||
                         (p[0] == '(' && p[1] == '(') ||
                         (p[0] == ')' && p[1] == ')'))) {
      p += 2;
      continue;
    }
    if ((end - p > 8 && strncmp(p, "https://", 8) == 0) ||
        (end - p > 7 && strncmp(p, "http://", 7) == 0)) {
      p += (p[4] == 's') ? 8 : 7; // past the scheme
      while (p < end && *p != '/' && *p != ' ' && *p != ')' && *p != ']') {
        out[n++] = *p++;
      }
      while (p < end && *p != ' ' && *p != ')' && *p != ']') {
        p++;
      }
      continue;
    }
    out[n++] = *p++;
  }
  // a bullet with nothing left in it is not a line
  if (n == start) {
    return n;
  }
  out[n++] = '\n';
  return n;
}

// The text an entry is embedded as: its title - unless it is the placeholder
// every untitled POST gets, which would make them all alike - then its body,
// cleaned (EmbedCleanLine) and cut at EMBED_TEXT_BYTES on a character
// boundary.
static const char *EmbedEntryText(Arena *arena, const char *title,
                                  const char *content) {
  assert(arena_valid(arena));
  if (!title || strcmp(title, "HTTP Entry") == 0) {
    title = "";
  }
  if (!content) {
    content = "";
  }
  size_t tl = strlen(title), cl = strlen(content);
  // cleaning only ever removes bytes, so this is the most it can need
  char *s = arena_alloc(arena, tl + 1 + cl + 2);
  size_t n = 0;
  memcpy(s, title, tl);
  n = tl;
  if (tl) {
    s[n++] = '\n';
  }
  const char *p = content, *end = content + cl;
  while (p < end && n < EMBED_TEXT_BYTES) {
    const char *nl = memchr(p, '\n', (size_t)(end - p));
    const char *le = nl ? nl : end;
    n = EmbedCleanLine(s, n, p, le);
    p = nl ? nl + 1 : end;
  }
  while (n > 0 && s[n - 1] == '\n') {
    n--;
  }
  if (n > EMBED_TEXT_BYTES) {
    n = EMBED_TEXT_BYTES;
    // back off a UTF-8 continuation byte, so no character is cut in half
    while (n > 0 && ((unsigned char)s[n] & 0xC0) == 0x80) {
      n--;
    }
  }
  s[n] = '\0';
  assert(n <= EMBED_TEXT_BYTES);
  return s;
}

static bool EmbedTextWorthIt(const char *s) {
  size_t n = 0;
  for (; *s; s++) {
    if (*s != ' ' && *s != '\n' && *s != '\t' && *s != '\r') {
      n++;
    }
  }
  return n >= EMBED_MIN_TEXT_BYTES;
}

static bool EmbedStore(sqlite3 *db, sqlite3_stmt *ins, int id,
                       const char *source_modified, const int8_t *q, int dim) {
  assert(db != NULL && ins != NULL);
  assert(id > 0 && dim >= 0 && dim <= EMBED_MAX_DIM);
  sqlite3_reset(ins);
  sqlite3_bind_int(ins, 1, id);
  sqlite3_bind_text(ins, 2, g_embed.key, -1, SQLITE_STATIC);
  sqlite3_bind_text(ins, 3, source_modified ? source_modified : "", -1,
                    SQLITE_TRANSIENT);
  sqlite3_bind_int(ins, 4, dim);
  // a zero-length blob, not NULL: the column is NOT NULL
  sqlite3_bind_blob(ins, 5, dim ? (const void *)q : "", dim, SQLITE_TRANSIENT);
  if (sqlite3_step(ins) != SQLITE_DONE) {
    printf("Embed: storing entry %d failed: %s\n", id, sqlite3_errmsg(db));
    return false;
  }
  return true;
}

// One text on its own, cut in half up to three times while the service
// says it is too long. Returns the dimension, 0 for "gave up on this one",
// -1 for "the service went away".
static int EmbedOne(Arena *arena, const char *text, float *vec, char *err,
                    size_t err_size) {
  assert(arena_valid(arena));
  assert(text != NULL && vec != NULL);
  size_t len = strlen(text);
  char *cut = arena_alloc(arena, len + 1);
  memcpy(cut, text, len + 1);
  for (int tries = 0; tries < 4; tries++) {
    const char *one[1] = {cut};
    int dim = 0;
    EmbedFail f = EmbedRequest(arena, one, 1, false, EMBED_BATCH_RESPONSE_MAX,
                               vec, &dim, err, err_size);
    if (f == EMBED_OK) {
      return dim;
    }
    if (f == EMBED_UNREACHABLE) {
      return -1;
    }
    len /= 2;
    while (len > 0 && ((unsigned char)cut[len] & 0xC0) == 0x80) {
      len--;
    }
    cut[len] = '\0';
    if (len < EMBED_MIN_TEXT_BYTES) {
      break;
    }
  }
  return 0;
}

// One batch of stale rows. Returns how many rows were settled, 0 when there
// was nothing to do, -1 when the service could not be reached.
static int EmbedIndexBatch(Arena *arena, sqlite3 *db, float *vecs,
                           int8_t *q) {
  assert(arena_valid(arena));
  assert(db != NULL && vecs != NULL && q != NULL);

  sqlite3_stmt *sel = NULL;
  int rc = sqlite3_prepare_v2(
      db,
      "SELECT e.id, e.title, substr(e.content, 1, ?3), "
      "ifnull(e.last_modified_at_utc, '') FROM entries e "
      "LEFT JOIN entry_embeddings m ON m.entry_id = e.id "
      "WHERE e.deleted = 0 AND (m.entry_id IS NULL OR m.model <> ?1 "
      "OR m.source_modified <> ifnull(e.last_modified_at_utc, '')) "
      "AND ifnull(e.last_modified_at_utc, '') <= "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', ?4) "
      "ORDER BY e.id DESC LIMIT ?2;",
      -1, &sel, NULL);
  if (rc != SQLITE_OK) {
    printf("Embed: cannot prepare the stale-row query: %s\n",
           sqlite3_errmsg(db));
    return -1;
  }
  char settle[32];
  snprintf(settle, sizeof(settle), "-%d seconds", EMBED_SETTLE_SECONDS);
  sqlite3_bind_text(sel, 1, g_embed.key, -1, SQLITE_STATIC);
  sqlite3_bind_int(sel, 2, EMBED_BATCH);
  sqlite3_bind_int(sel, 3, EMBED_CONTENT_CHARS);
  sqlite3_bind_text(sel, 4, settle, -1, SQLITE_TRANSIENT);

  int ids[EMBED_BATCH];
  const char *stamps[EMBED_BATCH];
  const char *texts[EMBED_BATCH];
  bool worth[EMBED_BATCH];
  int n = 0;
  while (n < EMBED_BATCH && sqlite3_step(sel) == SQLITE_ROW) {
    ids[n] = sqlite3_column_int(sel, 0);
    texts[n] = EmbedEntryText(arena, (const char *)sqlite3_column_text(sel, 1),
                              (const char *)sqlite3_column_text(sel, 2));
    const char *m = (const char *)sqlite3_column_text(sel, 3);
    size_t ml = m ? strlen(m) : 0;
    char *copy = arena_alloc(arena, ml + 1);
    memcpy(copy, m ? m : "", ml + 1);
    stamps[n] = copy;
    worth[n] = EmbedTextWorthIt(texts[n]);
    n++;
  }
  sqlite3_finalize(sel);
  if (n == 0) {
    return 0;
  }

  // The rows worth a request go in one batch; the rest are stored as dim 0.
  const char *batch[EMBED_BATCH];
  int slot[EMBED_BATCH];
  int m = 0;
  for (int i = 0; i < n; i++) {
    slot[i] = -1;
    if (worth[i]) {
      slot[i] = m;
      batch[m++] = texts[i];
    }
  }
  char err[EMBED_ERR_BYTES];
  int dim = 0;
  int dims[EMBED_BATCH];
  if (m > 0) {
    EmbedFail f = EmbedRequest(arena, batch, m, false, EMBED_BATCH_RESPONSE_MAX,
                               vecs, &dim, err, sizeof(err));
    if (f == EMBED_UNREACHABLE) {
      printf("Embed: %s\n", err);
      return -1;
    }
    for (int j = 0; j < m; j++) {
      dims[j] = dim;
    }
    if (f == EMBED_REFUSED) {
      // Something in the batch was refused. Asked one at a time, the rest
      // go through and the one at fault is cut down or given up on.
      printf("Embed: batch refused (%s); retrying one at a time\n", err);
      for (int j = 0; j < m; j++) {
        dims[j] = EmbedOne(arena, batch[j], vecs + (size_t)j * EMBED_MAX_DIM,
                           err, sizeof(err));
        if (dims[j] < 0) {
          printf("Embed: %s\n", err);
          return -1;
        }
      }
    }
  }

  sqlite3_stmt *ins = NULL;
  rc = sqlite3_prepare_v2(
      db,
      "INSERT OR REPLACE INTO entry_embeddings (entry_id, model, "
      "source_modified, dim, vec, embedded_at_utc) VALUES (?1, ?2, ?3, ?4, "
      "?5, strftime('%Y-%m-%d %H:%M:%S', 'now'));",
      -1, &ins, NULL);
  if (rc != SQLITE_OK) {
    printf("Embed: cannot prepare the insert: %s\n", sqlite3_errmsg(db));
    return -1;
  }
  sqlite3_exec(db, "BEGIN;", NULL, NULL, NULL);
  int stored = 0;
  for (int i = 0; i < n; i++) {
    int d = slot[i] >= 0 ? dims[slot[i]] : 0;
    if (d > 0) {
      EmbedQuantize(vecs + (size_t)slot[i] * EMBED_MAX_DIM, d, q);
    }
    if (EmbedStore(db, ins, ids[i], stamps[i], q, d)) {
      stored++;
    }
  }
  sqlite3_exec(db, stored ? "COMMIT;" : "ROLLBACK;", NULL, NULL, NULL);
  sqlite3_finalize(ins);
  // Nothing stored is a database that refuses writes: waiting it out beats
  // asking the service for the same vectors in a tight loop.
  return stored > 0 ? stored : -1;
}

static void EmbedSleep(int seconds) {
  assert(seconds > 0);
  struct timespec ts = {seconds, 0};
  while (nanosleep(&ts, &ts) != 0) {
  }
}

static void *EmbedIndexerThread(void *arg) {
  (void)arg;
  // The arena lives on this thread's stack, like a connection's does.
  uint8_t backing[EMBED_ARENA_BYTES];
  Arena arena;
  arena_init(&arena, backing, sizeof(backing));
  // One batch of float vectors and one quantized row. Static rather than on
  // the stack: this is the only thread that touches them, and 256KB of
  // floats is not worth the stack.
  static float vecs[EMBED_BATCH * EMBED_MAX_DIM];
  static int8_t q[EMBED_MAX_DIM];

  // One request at start, so GET /features knows whether the service
  // answers even when every entry is already charted and the loop below
  // would ask it nothing; its vector is thrown away.
  {
    const char *probe[1] = {"lcars"};
    int dim = 0;
    char err[EMBED_ERR_BYTES];
    (void)EmbedRequest(&arena, probe, 1, false, EMBED_QUERY_RESPONSE_MAX, vecs,
                       &dim, err, sizeof(err));
    arena_reset(&arena);
  }

  sqlite3 *db = NULL;
  bool reachable = true; // so the first failure is logged, and only it
  int done = 0;
  for (;;) {
    if (!db) {
      if (sqlite3_open(LcarsDBPath(), &db) != SQLITE_OK) {
        printf("Embed: cannot open %s\n", LcarsDBPath());
        sqlite3_close(db);
        db = NULL;
        EmbedSleep(EMBED_BACKOFF_SECONDS);
        continue;
      }
      sqlite3_busy_timeout(db, 5000);
      if (!EnsureEmbedTable(db)) {
        sqlite3_close(db);
        db = NULL;
        EmbedSleep(EMBED_BACKOFF_SECONDS);
        continue;
      }
    }
    arena_reset(&arena);
    int n = EmbedIndexBatch(&arena, db, vecs, q);
    if (n < 0) {
      if (reachable) {
        printf("Embed: indexer waiting %ds for the embedding service (%s)\n",
               EMBED_BACKOFF_SECONDS, g_embed.url);
      }
      reachable = false;
      EmbedSleep(EMBED_BACKOFF_SECONDS);
      continue;
    }
    if (!reachable) {
      printf("Embed: embedding service is back\n");
    }
    reachable = true;
    if (n == 0) {
      if (done > 0) {
        printf("Embed: indexed %d entries; the journal is charted\n", done);
        done = 0;
      }
      EmbedSleep(EMBED_IDLE_SECONDS);
      continue;
    }
    done += n;
  }
  return NULL;
}

static void StartEmbedIndexer(void) {
  EmbedConfigInit();
  if (!g_embed.on) {
    printf("Embed: off (LCARS_EMBED=0)\n");
    return;
  }
  // Before any thread can call curl_easy_init, which would otherwise do
  // this lazily - and not thread-safely - itself.
  curl_global_init(CURL_GLOBAL_DEFAULT);
  pthread_attr_t attr;
  if (pthread_attr_init(&attr) != 0) {
    return;
  }
  pthread_attr_setstacksize(&attr, EMBED_THREAD_STACK_BYTES);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
  pthread_t tid;
  if (pthread_create(&tid, &attr, EmbedIndexerThread, NULL) != 0) {
    printf("Embed: cannot start the indexer thread\n");
  } else {
    printf("Embed: indexing with %s via %s\n", g_embed.model, g_embed.url);
  }
  pthread_attr_destroy(&attr);
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// Appends `dim` int8 components as base64, in quotes.
static void EmbedAppendB64(HTTPBodyStream *s, JSONBuf *b, const void *vec,
                           int dim) {
  assert(vec != NULL && dim > 0 && dim <= EMBED_MAX_DIM);
  char enc[4 * ((EMBED_MAX_DIM + 2) / 3) + 1];
  base64_encode((const unsigned char *)vec, (size_t)dim, enc, sizeof(enc));
  if (s) {
    HTTPStreamWrite(s, "\"", 1);
    HTTPStreamWrite(s, enc, strlen(enc));
    HTTPStreamWrite(s, "\"", 1);
  } else {
    assert(b != NULL);
    jsonbuf_append(b, "\"");
    jsonbuf_append(b, enc);
    jsonbuf_append(b, "\"");
  }
}

// GET /embeddings[?since=<embedded_at_utc>] -
//   {"model":..., "dim":384, "live":3700, "done":3650,
//    "rows":[[id,"<base64 int8>"], ...], "mark":"<stamp>"}
// `live` and `done` are the indexer's progress: live entries, and how many
// of them have a current vector (or were found to have nothing to embed).
// `mark` is the newest embedded_at_utc in the answer, what the next ?since=
// asks from; since is inclusive, so a row stamped in the same second as the
// mark is sent twice rather than never. Only the current model's vectors are
// served, so a client whose cache holds another model's starts over.
static int HandleEmbeddings(int client_fd, Arena *arena, const char *query) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL);

  if (!g_embed.on) {
    return SendJSONError(client_fd, 503, "Embeddings are off on this server");
  }
  char since[32] = "";
  query_get(query, "since", since, sizeof(since));

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (!EnsureEmbedTable(db)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "Cannot create the embeddings table");
  }

  int live = 0, done = 0, dim = 0;
  sqlite3_stmt *st = NULL;
  if (sqlite3_prepare_v2(
          db,
          "SELECT (SELECT count(*) FROM entries WHERE deleted = 0), "
          "(SELECT count(*) FROM entry_embeddings m JOIN entries e "
          " ON e.id = m.entry_id WHERE e.deleted = 0 AND m.model = ?1 "
          " AND m.source_modified = ifnull(e.last_modified_at_utc, '')), "
          "(SELECT ifnull(max(dim), 0) FROM entry_embeddings "
          " WHERE model = ?1);",
          -1, &st, NULL) == SQLITE_OK) {
    sqlite3_bind_text(st, 1, g_embed.key, -1, SQLITE_STATIC);
    if (sqlite3_step(st) == SQLITE_ROW) {
      live = sqlite3_column_int(st, 0);
      done = sqlite3_column_int(st, 1);
      dim = sqlite3_column_int(st, 2);
    }
  }
  sqlite3_finalize(st);

  if (sqlite3_prepare_v2(db,
                         "SELECT m.entry_id, m.vec, m.embedded_at_utc "
                         "FROM entry_embeddings m JOIN entries e "
                         "ON e.id = m.entry_id WHERE e.deleted = 0 "
                         "AND m.model = ?1 AND m.dim = ?2 "
                         "AND m.embedded_at_utc >= ?3 ORDER BY m.entry_id;",
                         -1, &st, NULL) != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_text(st, 1, g_embed.key, -1, SQLITE_STATIC);
  sqlite3_bind_int(st, 2, dim);
  sqlite3_bind_text(st, 3, since, -1, SQLITE_TRANSIENT);

  uint8_t zbuf[HTTP_GZIP_ZLIB_BYTES];
  HTTPBodyStream s;
  HTTPStreamBegin(&s, client_fd, 200, "application/json", NULL,
                  g_conn_accepts_gzip, zbuf, sizeof(zbuf));
  char head[512];
  JSONBuf model;
  jsonbuf_init(&model, arena);
  jsonbuf_append_json_string(&model, g_embed.key);
  int hn = snprintf(head, sizeof(head),
                    "{\"model\":%s,\"dim\":%d,\"live\":%d,\"done\":%d,"
                    "\"rows\":[",
                    model.data ? model.data : "\"\"", dim, live, done);
  assert(hn > 0 && hn < (int)sizeof(head));
  HTTPStreamWrite(&s, head, (size_t)hn);
  char mark[32] = "";
  int rows = 0, rc = SQLITE_DONE;
  while (!s.failed && (rc = sqlite3_step(st)) == SQLITE_ROW) {
    const void *vec = sqlite3_column_blob(st, 1);
    if (!vec || sqlite3_column_bytes(st, 1) != dim) {
      continue;
    }
    char id[24];
    int in = snprintf(id, sizeof(id), "%s[%d,", rows ? "," : "",
                      sqlite3_column_int(st, 0));
    HTTPStreamWrite(&s, id, (size_t)in);
    EmbedAppendB64(&s, NULL, vec, dim);
    HTTPStreamWrite(&s, "]", 1);
    const char *at = (const char *)sqlite3_column_text(st, 2);
    if (at && strcmp(at, mark) > 0) {
      snprintf(mark, sizeof(mark), "%s", at);
    }
    rows++;
  }
  bool complete = !s.failed && rc == SQLITE_DONE;
  if (complete) {
    // An answer with no rows keeps the caller's own mark.
    char tail[64];
    int tn = snprintf(tail, sizeof(tail), "],\"mark\":\"%s\"}",
                      mark[0] ? mark : since);
    HTTPStreamWrite(&s, tail, (size_t)tn);
  }
  HTTPStreamEnd(&s, complete);
  printf("HTTP /embeddings: %d rows (%d of %d live charted), %zu bytes -> "
         "%zu on the wire\n",
         rows, done, live, s.raw_bytes, s.wire_bytes);
  sqlite3_finalize(st);
  sqlite3_close(db);
  return complete ? 200 : 500;
}

// POST /embed {"text": "..."} - {"model":..., "dim":..., "vec":"<b64>"}.
// A search by meaning: the page compares this against the vectors it holds.
static int HandleEmbed(int client_fd, Arena *arena, const char *body,
                       const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));

  if (!g_embed.on) {
    return SendJSONError(client_fd, 503, "Embeddings are off on this server");
  }
  if (!content_type || strncmp(content_type, "application/json", 16) != 0) {
    return SendJSONError(client_fd, 415, "POST /embed takes JSON: {\"text\"}");
  }
  char *text = NULL;
  if (!body || !json_get_string_arena(arena, body, "text", &text) || !text ||
      !EmbedTextWorthIt(text)) {
    return SendJSONError(client_fd, 400, "Missing 'text'");
  }
  size_t n = strlen(text);
  if (n > EMBED_QUERY_BYTES) {
    n = EMBED_QUERY_BYTES;
    while (n > 0 && ((unsigned char)text[n] & 0xC0) == 0x80) {
      n--;
    }
    text[n] = '\0';
  }
  // One vector's floats, from the connection arena rather than the stack.
  float *vec = arena_alloc(arena, sizeof(float) * EMBED_MAX_DIM);
  int8_t q[EMBED_MAX_DIM];
  char err[EMBED_ERR_BYTES];
  int dim = 0;
  const char *one[1] = {text};
  EmbedFail f = EmbedRequest(arena, one, 1, true, EMBED_QUERY_RESPONSE_MAX, vec,
                               &dim, err, sizeof(err));
  if (f != EMBED_OK) {
    printf("Embed: /embed failed: %s\n", err);
    return SendJSONError(client_fd, f == EMBED_UNREACHABLE ? 503 : 502,
                         "Embedding service: %s", err);
  }
  EmbedQuantize(vec, dim, q);
  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"model\":");
  jsonbuf_append_json_string(&out, g_embed.key);
  jsonbuf_appendf(&out, ",\"dim\":%d,\"vec\":", dim);
  EmbedAppendB64(NULL, &out, q, dim);
  jsonbuf_append(&out, "}");
  return SendJSONBuf(client_fd, &out);
}

#endif // LCARS_EMBED_IMPLEMENTATION
#endif // LCARS_EMBED_H
