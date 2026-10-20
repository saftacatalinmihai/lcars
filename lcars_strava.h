#ifndef LCARS_STRAVA_H
#define LCARS_STRAVA_H

// lcars_strava.h - the Strava bridge: lcars-cli's third half, beside the
// Logseq bridge.
//
// One direction only, Strava -> lcars: each activity becomes an entry of
// the `workout` role's kind (the server's /kinds/roles; default `workout`),
// backdated to the activity's start, so the captain's runs and rides
// land in the journal on their own (an hourly user timer runs
// `lcars-cli strava pull`, scripts/lcars-strava.{service,timer}).
//
// Everything is an outbound pull from the box. The server listens on
// loopback behind tailscale serve, so there is nothing Strava could call
// back: no webhook subscription, no OAuth callback URL. The one-time grant
// uses redirect_uri=http://localhost, a page that does not load, and the
// captain copies the `code` out of its address bar (`strava auth <code>`).
// That is also why this is client work and not a server module.
//
// The identity of an activity in the journal is one line of the entry's
// content, `strava: https://www.strava.com/activities/<id>` - no column, no
// side table, the same "the content is the marker" choice the Logseq import
// made with titles. A pull looks each activity up by that line (the API's
// `q`, then an exact line compare: `q` is a substring match, and
// .../activities/12 is a prefix of .../activities/123) and creates or
// updates; a second pull over the same activities writes nothing. The
// entry's attachments (the GPS track, a later slice) go in the media side
// table, so they will not touch the content either.
//
// Strava rotates the refresh token on every refresh, so the tokens live in
// a writable file (~/.lcars-strava/token.json, 0600 in a 0700 directory),
// rewritten whole through a rename after every refresh: a crash between the
// refresh and the write would otherwise lose the only refresh token that
// still works, and the captain would have to grant access again.
//
// Rate limits are 100 requests per 15 minutes and 1000 a day. The list
// costs one request per 200 activities; the detail (`GET
// /api/v3/activities/<id>`, the only place the description and calories
// are) one per activity created or changed. A backfill of years is
// therefore mostly detail requests, and it *will* meet a 429: the pull
// stops there, says so, and keeps its place (StravaPull), and the next run
// carries on. It never waits or retries inside a run.
//
// Shape follows every other module: declarations first, bodies under
// LCARS_IMPLEMENTATION. Included from lcars_cli.c after lcars_logseq.h, and
// builds on lcars_cli.h's arena, JSON scanner, curl write callback and
// entry requests.

#include "lcars_cli.h"

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <sys/stat.h>
#include <time.h>

// ---------------------------------------------------------------------------
// Tuning
// ---------------------------------------------------------------------------

// Where the API and the OAuth pages are. LCARS_STRAVA_API overrides it, which
// is how test/strava.py stands a stub in.
#define STRAVA_DEFAULT_API "https://www.strava.com"

// The identity line's URL. Always the real site, whatever LCARS_STRAVA_API
// says: it is a link the captain can open, and an id is an id.
#define STRAVA_ACTIVITY_URL "https://www.strava.com/activities/"
#define STRAVA_LINE_PREFIX "strava: "

// The workout role's default: the kind on a server older than the roles
// (CliRoleKind). Otherwise the pull asks the server, so an owner who calls
// workouts something else gets them there - and finds them there: a pull
// matches an activity to its entry within that kind only, so moving the
// role to a new kind starts the workouts over in it (the old rows stay).
#define STRAVA_KIND "workout"

// activity:read_all includes the activities only he can see; without it a
// private run would silently be missing from the journal.
#define STRAVA_SCOPE "activity:read_all"
#define STRAVA_REDIRECT_URI "http://localhost"

// Strava's maximum page size: fewest list requests.
#define STRAVA_PER_PAGE 200

// Refresh an access token this close to its expiry (they last six hours).
#define STRAVA_REFRESH_MARGIN_SECONDS 60

// A pull without --since starts this far before the last one. Strava's
// `after` filters by when an activity *started*, not when it was uploaded,
// so a watch synced two days late would otherwise fall behind the cursor
// for good. The overlap costs one journal lookup per activity in it and no
// Strava request unless something changed (StravaPull).
#define STRAVA_OVERLAP_SECONDS (7 * 24 * 3600)

#define STRAVA_TOKEN_DIR ".lcars-strava"
#define STRAVA_TOKEN_FILE "token.json"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

typedef struct StravaOptions {
  const char *api_base; // scheme://host[:port], no trailing slash
  const char *client_id;
  const char *client_secret;
  const char *token_dir;  // ~/.lcars-strava
  const char *token_path; // ~/.lcars-strava/token.json
  long timeout_seconds;
} StravaOptions;

// The token file, field for field. `present` is false when there is no file
// yet (no grant): the other fields are then empty.
typedef struct StravaToken {
  bool present;
  const char *access_token;
  const char *refresh_token;
  long long expires_at; // epoch seconds
  long long athlete_id;
  const char *athlete_name;
  long long last_pull_epoch; // the `after` cursor; 0 = never pulled
} StravaToken;

// What the journal needs of an activity. The list's SummaryActivity fills
// all but `description` and `calories`, which only the detail has.
typedef struct StravaActivity {
  long long id;
  const char *name;
  const char *sport_type;
  const char *start_utc; // "YYYY-MM-DD HH:MM:SS", the entry's created_at_utc
  long long start_epoch;
  double distance_m;
  int moving_s;
  int elapsed_s;
  double elevation_m;
  double average_speed; // m/s
  double average_hr;    // 0 when the activity has no heart rate
  double max_hr;
  double calories; // 0 when absent
  const char *description;
} StravaActivity;

typedef struct StravaPullOptions {
  const char *kind; // the workout role's kind on this journal (CliRoleKind)
  long long after;  // epoch seconds
  bool dry_run;
  bool verbose;
} StravaPullOptions;

typedef struct StravaPullStats {
  int seen;
  int created;
  int updated;
  int unchanged;
  int deleted; // soft-deleted in the journal: left alone, never revived
  int failed;
  int requests; // to Strava
  bool rate_limited;
  // The start of the newest activity handled completely, for the cursor of
  // a pull that stopped early.
  long long newest_done_epoch;
} StravaPullStats;

// ---------------------------------------------------------------------------
// Declarations
// ---------------------------------------------------------------------------

static inline bool StravaOptionsFromEnv(Arena *arena, StravaOptions *so,
                                        long timeout_seconds, char *err,
                                        size_t err_size);
static inline bool StravaLoadToken(Arena *arena, const StravaOptions *so,
                                   StravaToken *tok, char *err,
                                   size_t err_size);
static inline bool StravaSaveToken(Arena *arena, const StravaOptions *so,
                                   const StravaToken *tok, char *err,
                                   size_t err_size);
static inline const char *StravaAuthorizeURL(Arena *arena,
                                             const StravaOptions *so);
static inline const char *StravaCodeFromInput(Arena *arena, const char *input,
                                              const char **out_scope);
static inline bool StravaExchangeCode(Arena *arena, const StravaOptions *so,
                                      const char *code, StravaToken *tok,
                                      char *err, size_t err_size);
static inline bool StravaEnsureFresh(Arena *arena, const StravaOptions *so,
                                     StravaToken *tok, char *err,
                                     size_t err_size);
static inline bool StravaGetAthlete(Arena *arena, const StravaOptions *so,
                                    const StravaToken *tok, long long *out_id,
                                    const char **out_name, bool *rate_limited,
                                    char *err, size_t err_size);
static inline const char *
StravaEntryContent(Arena *arena, const StravaActivity *a, const char *tail);
static inline bool StravaPull(Arena *arena, const CliOptions *opts,
                              const StravaOptions *so, const StravaToken *tok,
                              const StravaPullOptions *po,
                              StravaPullStats *stats, char *err,
                              size_t err_size);
static inline long long StravaEpochFromUTC(const char *iso);
static inline const char *StravaUTC(Arena *arena, long long epoch);

#ifdef LCARS_IMPLEMENTATION

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

// Strava ids are past 2^32 already; `long` is 64-bit here, but say so.
static inline long long strava_span_ll(JsonSpan v) {
  char tmp[32];
  size_t n = v.len < sizeof(tmp) - 1 ? v.len : sizeof(tmp) - 1;
  memcpy(tmp, v.data, n);
  tmp[n] = '\0';
  return strtoll(tmp, NULL, 10);
}

static inline bool strava_span_null(JsonSpan v) {
  return v.len == 4 && memcmp(v.data, "null", 4) == 0;
}

// The member as a number, 0 when absent or null (an activity without a heart
// rate monitor has no average_heartrate member at all).
static inline double strava_num(JsonSpan obj, const char *key) {
  JsonSpan v;
  if (!json_member(obj, key, &v) || strava_span_null(v)) {
    return 0;
  }
  return json_span_double(v);
}

// "2024-05-01T06:12:33Z" (or the already-converted "2024-05-01 06:12:33") to
// epoch seconds, 0 when it does not parse.
static inline long long StravaEpochFromUTC(const char *iso) {
  assert(iso != NULL);

  struct tm tm;
  memset(&tm, 0, sizeof(tm));
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  if (sscanf(iso, "%4d-%2d-%2d%*c%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &s) != 6) {
    return 0;
  }
  tm.tm_year = y - 1900;
  tm.tm_mon = mo - 1;
  tm.tm_mday = d;
  tm.tm_hour = h;
  tm.tm_min = mi;
  tm.tm_sec = s;
  return (long long)timegm(&tm);
}

static inline const char *StravaUTC(Arena *arena, long long epoch) {
  assert(arena_valid(arena));

  time_t t = (time_t)epoch;
  struct tm tm;
  gmtime_r(&t, &tm);
  char *out = (char *)arena_alloc(arena, CLI_MAX_TIMESTAMP_LEN + 1);
  strftime(out, CLI_MAX_TIMESTAMP_LEN + 1, "%Y-%m-%d %H:%M:%S", &tm);
  return out;
}

// One blocking request to Strava: GET, or a form POST when `form` is given,
// with a bearer token when `bearer` is. Like CliHttpRequest, true means the
// transport worked; the status is the caller's to judge (a 429 is an answer,
// not a failure of this function).
static inline bool StravaRequest(Arena *arena, const StravaOptions *so,
                                 const char *path, const char *form,
                                 const char *bearer, JsonSpan *out_body,
                                 long *out_status, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && path != NULL && path[0] == '/');
  assert(out_body != NULL && out_status != NULL);

  out_body->data = "";
  out_body->len = 0;
  *out_status = 0;

  JSONBuf url;
  jsonbuf_init_strict(&url, arena);
  jsonbuf_append(&url, so->api_base);
  jsonbuf_append(&url, path);

  CURL *curl = curl_easy_init();
  if (!curl) {
    return CliFail(err, err_size, "curl_easy_init() failed");
  }
  LcarsCurlCA(curl); // a static build's CA bundle (lcars_curl_ca.h)

  struct CliCurlBuf chunk;
  chunk.arena = arena;
  chunk.data = (char *)arena_alloc(arena, 1);
  chunk.data[0] = '\0';
  chunk.size = 0;

  struct curl_slist *headers = NULL;
  if (bearer) {
    JSONBuf auth;
    jsonbuf_init_strict(&auth, arena);
    jsonbuf_append(&auth, "Authorization: Bearer ");
    jsonbuf_append(&auth, bearer);
    headers = curl_slist_append(headers, auth.data);
  }
  if (form) {
    headers = curl_slist_append(
        headers, "Content-Type: application/x-www-form-urlencoded");
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, form);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(form));
  }
  curl_easy_setopt(curl, CURLOPT_URL, url.data);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, CliCurlWrite);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, so->timeout_seconds);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "lcars-cli/1.0");

  CURLcode res = curl_easy_perform(curl);
  if (res == CURLE_OK) {
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, out_status);
  }
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);
  if (res != CURLE_OK) {
    // The path only: the URL of a token request carries nothing secret, but
    // the form does, and it is not printed either.
    return CliFail(err, err_size, "strava %s: %s", path,
                   curl_easy_strerror(res));
  }
  out_body->data = chunk.data;
  out_body->len = chunk.size;
  return true;
}

// A non-2xx answer as the message the captain sees. Strava answers errors as
// {"message":…,"errors":[…]}; the first 200 bytes say enough.
static inline bool strava_status_error(const char *what, JsonSpan body,
                                       long status, char *err,
                                       size_t err_size) {
  if (status == 401) {
    return CliFail(err, err_size,
                   "%s: Strava refused the token (HTTP 401) - grant access "
                   "again with `lcars-cli strava auth`",
                   what);
  }
  return CliFail(err, err_size, "%s: HTTP %ld: %.*s", what, status,
                 (int)(body.len < 200 ? body.len : 200), body.data);
}

// ---------------------------------------------------------------------------
// Options and the token file
// ---------------------------------------------------------------------------

static inline bool StravaOptionsFromEnv(Arena *arena, StravaOptions *so,
                                        long timeout_seconds, char *err,
                                        size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL);

  memset(so, 0, sizeof(*so));
  so->timeout_seconds = timeout_seconds;
  const char *api = getenv("LCARS_STRAVA_API");
  if (!api || api[0] == '\0') {
    api = STRAVA_DEFAULT_API;
  }
  size_t len = strlen(api);
  char *trimmed = (char *)arena_alloc(arena, len + 1);
  memcpy(trimmed, api, len + 1);
  while (len > 0 && trimmed[len - 1] == '/') {
    trimmed[--len] = '\0';
  }
  so->api_base = trimmed;
  so->client_id = getenv("LCARS_STRAVA_CLIENT_ID");
  so->client_secret = getenv("LCARS_STRAVA_CLIENT_SECRET");

  const char *home = getenv("HOME");
  if (!home || home[0] == '\0') {
    return CliFail(err, err_size, "HOME is not set: nowhere for %s/%s",
                   STRAVA_TOKEN_DIR, STRAVA_TOKEN_FILE);
  }
  JSONBuf dir;
  jsonbuf_init_strict(&dir, arena);
  jsonbuf_appendf(&dir, "%s/%s", home, STRAVA_TOKEN_DIR);
  JSONBuf path;
  jsonbuf_init_strict(&path, arena);
  jsonbuf_appendf(&path, "%s/%s", dir.data, STRAVA_TOKEN_FILE);
  so->token_dir = dir.data;
  so->token_path = path.data;
  return true;
}

static inline bool StravaLoadToken(Arena *arena, const StravaOptions *so,
                                   StravaToken *tok, char *err,
                                   size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && tok != NULL);

  memset(tok, 0, sizeof(*tok));
  tok->access_token = "";
  tok->refresh_token = "";
  tok->athlete_name = "";
  if (access(so->token_path, F_OK) != 0) {
    return true; // no grant yet: present = false
  }
  const char *text = CliReadFile(arena, so->token_path, err, err_size);
  if (!text) {
    return false;
  }
  JsonSpan obj = {text, strlen(text)};
  JsonSpan v;
  if (obj.len == 0 || obj.data[0] != '{' ||
      !json_member(obj, "refresh_token", &v)) {
    return CliFail(err, err_size,
                   "%s is not a token file - delete it and run "
                   "`lcars-cli strava auth` again",
                   so->token_path);
  }
  tok->present = true;
  tok->refresh_token = json_span_string(arena, v);
  if (json_member(obj, "access_token", &v)) {
    tok->access_token = json_span_string(arena, v);
  }
  if (json_member(obj, "expires_at", &v)) {
    tok->expires_at = strava_span_ll(v);
  }
  if (json_member(obj, "athlete_id", &v)) {
    tok->athlete_id = strava_span_ll(v);
  }
  if (json_member(obj, "athlete_name", &v)) {
    tok->athlete_name = json_span_string(arena, v);
  }
  if (json_member(obj, "last_pull_epoch", &v)) {
    tok->last_pull_epoch = strava_span_ll(v);
  }
  return true;
}

// Written to a temp file beside it, then renamed over it: the file is either
// the old tokens or the new ones, never half of each. Created 0600 (it holds
// a credential to his whole activity history) in a 0700 directory.
static inline bool StravaSaveToken(Arena *arena, const StravaOptions *so,
                                   const StravaToken *tok, char *err,
                                   size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && tok != NULL);

  if (mkdir(so->token_dir, 0700) != 0 && errno != EEXIST) {
    return CliFail(err, err_size, "mkdir %s: %s", so->token_dir,
                   strerror(errno));
  }
  chmod(so->token_dir, 0700); // an older, looser directory is tightened

  JSONBuf body;
  jsonbuf_init_strict(&body, arena);
  jsonbuf_append(&body, "{\"access_token\":");
  jsonbuf_append_json_string(&body, tok->access_token);
  jsonbuf_append(&body, ",\"refresh_token\":");
  jsonbuf_append_json_string(&body, tok->refresh_token);
  jsonbuf_appendf(&body, ",\"expires_at\":%lld,\"athlete_id\":%lld",
                  tok->expires_at, tok->athlete_id);
  jsonbuf_append(&body, ",\"athlete_name\":");
  jsonbuf_append_json_string(&body, tok->athlete_name);
  jsonbuf_appendf(&body, ",\"last_pull_epoch\":%lld}\n", tok->last_pull_epoch);

  JSONBuf tmp;
  jsonbuf_init_strict(&tmp, arena);
  jsonbuf_appendf(&tmp, "%s.tmp", so->token_path);
  int fd = open(tmp.data, O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (fd < 0) {
    return CliFail(err, err_size, "open %s: %s", tmp.data, strerror(errno));
  }
  fchmod(fd, 0600); // O_CREAT's mode does not apply to a leftover temp file
  size_t len = strlen(body.data);
  size_t off = 0;
  while (off < len) {
    ssize_t n = write(fd, body.data + off, len - off);
    if (n < 0) {
      if (errno == EINTR) {
        continue;
      }
      close(fd);
      unlink(tmp.data);
      return CliFail(err, err_size, "write %s: %s", tmp.data, strerror(errno));
    }
    off += (size_t)n;
  }
  if (fsync(fd) != 0 || close(fd) != 0) {
    unlink(tmp.data);
    return CliFail(err, err_size, "write %s: %s", tmp.data, strerror(errno));
  }
  if (rename(tmp.data, so->token_path) != 0) {
    unlink(tmp.data);
    return CliFail(err, err_size, "rename to %s: %s", so->token_path,
                   strerror(errno));
  }
  return true;
}

// ---------------------------------------------------------------------------
// OAuth
// ---------------------------------------------------------------------------

static inline const char *StravaAuthorizeURL(Arena *arena,
                                             const StravaOptions *so) {
  assert(arena_valid(arena));
  assert(so != NULL && so->client_id != NULL);

  JSONBuf url;
  jsonbuf_init_strict(&url, arena);
  jsonbuf_append(&url, so->api_base);
  jsonbuf_append(&url, "/oauth/authorize");
  bool first = true;
  cli_url_param(&url, &first, "client_id", so->client_id);
  cli_url_param(&url, &first, "redirect_uri", STRAVA_REDIRECT_URI);
  cli_url_param(&url, &first, "response_type", "code");
  cli_url_param(&url, &first, "approval_prompt", "auto");
  cli_url_param(&url, &first, "scope", STRAVA_SCOPE);
  return url.data;
}

// The value of query parameter `key` in `url`, or NULL. Undecoded: a code
// and a scope list are [A-Za-z0-9,:_] and need none, bar the comma, which a
// browser may show as %2C.
static inline const char *strava_query_value(Arena *arena, const char *url,
                                             const char *key) {
  size_t key_len = strlen(key);
  const char *q = strchr(url, '?');
  for (const char *p = q; p && *p; p = strchr(p + 1, '&')) {
    const char *name = p + 1;
    if (strncmp(name, key, key_len) == 0 && name[key_len] == '=') {
      const char *v = name + key_len + 1;
      size_t n = strcspn(v, "&#");
      char *out = (char *)arena_alloc(arena, n + 1);
      memcpy(out, v, n);
      out[n] = '\0';
      return out;
    }
  }
  return NULL;
}

// What the captain pastes: the bare code, or the whole address the redirect
// left in the browser (http://localhost/?state=&code=…&scope=read,…), which
// is easier to copy whole. `out_scope` is the granted scope when the URL
// says, else NULL.
static inline const char *StravaCodeFromInput(Arena *arena, const char *input,
                                              const char **out_scope) {
  assert(arena_valid(arena));
  assert(input != NULL && out_scope != NULL);

  *out_scope = NULL;
  if (!strchr(input, '?')) {
    return input;
  }
  *out_scope = strava_query_value(arena, input, "scope");
  return strava_query_value(arena, input, "code");
}

// The token endpoint's answer, for both grants. Only the authorization_code
// answer carries the athlete; a refresh leaves those fields as they were.
static inline bool strava_parse_token_answer(Arena *arena, JsonSpan body,
                                             StravaToken *tok, char *err,
                                             size_t err_size) {
  JsonSpan access, refresh, expires;
  if (body.len == 0 || body.data[0] != '{' ||
      !json_member(body, "access_token", &access) ||
      !json_member(body, "refresh_token", &refresh) ||
      !json_member(body, "expires_at", &expires)) {
    return CliFail(err, err_size, "strava token answer without tokens: %.*s",
                   (int)(body.len < 200 ? body.len : 200), body.data);
  }
  tok->present = true;
  tok->access_token = json_span_string(arena, access);
  tok->refresh_token = json_span_string(arena, refresh);
  tok->expires_at = strava_span_ll(expires);

  JsonSpan athlete, v;
  if (json_member(body, "athlete", &athlete) && athlete.len > 0 &&
      athlete.data[0] == '{') {
    if (json_member(athlete, "id", &v)) {
      tok->athlete_id = strava_span_ll(v);
    }
    const char *first = "", *last = "";
    if (json_member(athlete, "firstname", &v)) {
      first = json_span_string(arena, v);
    }
    if (json_member(athlete, "lastname", &v)) {
      last = json_span_string(arena, v);
    }
    JSONBuf name;
    jsonbuf_init_strict(&name, arena);
    jsonbuf_appendf(&name, "%s%s%s", first, first[0] && last[0] ? " " : "",
                    last);
    tok->athlete_name = name.data;
  }
  return true;
}

static inline bool strava_need_client(const StravaOptions *so, char *err,
                                      size_t err_size) {
  if (!so->client_id || !so->client_id[0] || !so->client_secret ||
      !so->client_secret[0]) {
    return CliFail(err, err_size,
                   "set LCARS_STRAVA_CLIENT_ID and LCARS_STRAVA_CLIENT_SECRET "
                   "(https://www.strava.com/settings/api)");
  }
  return true;
}

static inline bool strava_token_post(Arena *arena, const StravaOptions *so,
                                     const char *grant, const char *field,
                                     const char *value, StravaToken *tok,
                                     char *err, size_t err_size) {
  if (!strava_need_client(so, err, err_size)) {
    return false;
  }
  JSONBuf form;
  jsonbuf_init_strict(&form, arena);
  jsonbuf_append(&form, "client_id=");
  cli_url_encode(&form, so->client_id);
  jsonbuf_append(&form, "&client_secret=");
  cli_url_encode(&form, so->client_secret);
  jsonbuf_append(&form, "&grant_type=");
  cli_url_encode(&form, grant);
  jsonbuf_appendf(&form, "&%s=", field);
  cli_url_encode(&form, value);

  JsonSpan body;
  long status = 0;
  if (!StravaRequest(arena, so, "/oauth/token", form.data, NULL, &body, &status,
                     err, err_size)) {
    return false;
  }
  if (status != 200) {
    // A 400 here is a used or expired code, or a revoked grant; the 401
    // wording ("grant access again") is right for both.
    return CliFail(err, err_size,
                   "strava %s: HTTP %ld: %.*s - grant access again with "
                   "`lcars-cli strava auth`",
                   grant, status, (int)(body.len < 200 ? body.len : 200),
                   body.data);
  }
  if (!strava_parse_token_answer(arena, body, tok, err, err_size)) {
    return false;
  }
  return StravaSaveToken(arena, so, tok, err, err_size);
}

static inline bool StravaExchangeCode(Arena *arena, const StravaOptions *so,
                                      const char *code, StravaToken *tok,
                                      char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && code != NULL && tok != NULL);

  // A new grant keeps the old cursor: re-authorizing must not re-pull (and
  // re-detail, against the rate limit) every activity since 2010.
  long long cursor = tok->last_pull_epoch;
  if (!strava_token_post(arena, so, "authorization_code", "code", code, tok,
                         err, err_size)) {
    return false;
  }
  if (cursor != tok->last_pull_epoch) {
    tok->last_pull_epoch = cursor;
    return StravaSaveToken(arena, so, tok, err, err_size);
  }
  return true;
}

// Refreshes when the access token is within STRAVA_REFRESH_MARGIN_SECONDS of
// expiring. The answer's refresh token replaces the old one, which Strava
// has just invalidated, so it is on disk before this returns.
static inline bool StravaEnsureFresh(Arena *arena, const StravaOptions *so,
                                     StravaToken *tok, char *err,
                                     size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && tok != NULL);

  if (!tok->present) {
    return CliFail(err, err_size,
                   "not connected to Strava - run `lcars-cli strava auth`");
  }
  long long now = (long long)time(NULL);
  if (tok->access_token[0] != '\0' &&
      tok->expires_at - now > STRAVA_REFRESH_MARGIN_SECONDS) {
    return true;
  }
  return strava_token_post(arena, so, "refresh_token", "refresh_token",
                           tok->refresh_token, tok, err, err_size);
}

// A 429 is false with *rate_limited set: during a backfill the hour's
// budget is spent every hour, and status must tell that from a broken
// grant (a 401), so the caller can fall back on the token file's athlete.
static inline bool StravaGetAthlete(Arena *arena, const StravaOptions *so,
                                    const StravaToken *tok, long long *out_id,
                                    const char **out_name, bool *rate_limited,
                                    char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(so != NULL && tok != NULL && out_id != NULL && out_name != NULL);
  assert(rate_limited != NULL);

  *rate_limited = false;
  JsonSpan body;
  long status = 0;
  if (!StravaRequest(arena, so, "/api/v3/athlete", NULL, tok->access_token,
                     &body, &status, err, err_size)) {
    return false;
  }
  if (status == 429) {
    *rate_limited = true;
  }
  if (status != 200) {
    return strava_status_error("strava athlete", body, status, err, err_size);
  }
  JsonSpan v;
  *out_id = json_member(body, "id", &v) ? strava_span_ll(v) : 0;
  const char *first =
      json_member(body, "firstname", &v) ? json_span_string(arena, v) : "";
  const char *last =
      json_member(body, "lastname", &v) ? json_span_string(arena, v) : "";
  JSONBuf name;
  jsonbuf_init_strict(&name, arena);
  jsonbuf_appendf(&name, "%s%s%s", first, first[0] && last[0] ? " " : "", last);
  *out_name = name.data;
  return true;
}

// ---------------------------------------------------------------------------
// An activity, and the entry made of it
// ---------------------------------------------------------------------------

// Both the list's summaries and the detail: the same names, the detail has
// two more.
static inline void strava_parse_activity(Arena *arena, JsonSpan obj,
                                         StravaActivity *a) {
  memset(a, 0, sizeof(*a));
  a->name = "";
  a->description = "";
  JsonSpan v;
  if (json_member(obj, "id", &v)) {
    a->id = strava_span_ll(v);
  }
  if (json_member(obj, "name", &v)) {
    a->name = json_span_string(arena, v);
  }
  // sport_type (2022-) is the finer one (TrailRun, not Run); `type` is the
  // fallback for an answer without it.
  a->sport_type = "Workout";
  if ((json_member(obj, "sport_type", &v) || json_member(obj, "type", &v)) &&
      !strava_span_null(v)) {
    a->sport_type = json_span_string(arena, v);
  }
  const char *start = "";
  if (json_member(obj, "start_date", &v)) {
    start = json_span_string(arena, v);
  }
  a->start_epoch = StravaEpochFromUTC(start);
  a->start_utc = a->start_epoch ? StravaUTC(arena, a->start_epoch) : "";
  a->distance_m = strava_num(obj, "distance");
  a->moving_s = (int)strava_num(obj, "moving_time");
  a->elapsed_s = (int)strava_num(obj, "elapsed_time");
  a->elevation_m = strava_num(obj, "total_elevation_gain");
  a->average_speed = strava_num(obj, "average_speed");
  a->average_hr = strava_num(obj, "average_heartrate");
  a->max_hr = strava_num(obj, "max_heartrate");
  a->calories = strava_num(obj, "calories");
  if (json_member(obj, "description", &v)) {
    a->description = json_span_string(arena, v); // null -> ""
  }
}

// The entry's numbers: value_float the distance in km to the metre,
// value_int the moving time in whole minutes. The web UI's reading() takes
// value_float first, so a workout with a distance reads as kilometres.
static inline double strava_km(const StravaActivity *a) {
  return round(a->distance_m) / 1000.0;
}

static inline int strava_minutes(const StravaActivity *a) {
  return (a->moving_s + 30) / 60;
}

static inline void strava_append_duration(JSONBuf *b, int seconds) {
  if (seconds >= 3600) {
    jsonbuf_appendf(b, "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60,
                    seconds % 60);
  } else {
    jsonbuf_appendf(b, "%d:%02d", seconds / 60, seconds % 60);
  }
}

// "TrailRun" -> "Trail run": the words of Strava's enum, as a sentence.
static inline void strava_append_sport(JSONBuf *b, const char *sport) {
  for (size_t i = 0; sport[i]; i++) {
    char c = sport[i];
    bool upper = c >= 'A' && c <= 'Z';
    if (i > 0 && upper && sport[i - 1] >= 'a' && sport[i - 1] <= 'z') {
      jsonbuf_append(b, " ");
    }
    if (i > 0 && upper) {
      c = (char)(c - 'A' + 'a');
    }
    jsonbuf_append_len(b, &c, 1);
  }
}

static inline bool strava_is_run(const char *sport) {
  return strcmp(sport, "Run") == 0 || strcmp(sport, "TrailRun") == 0 ||
         strcmp(sport, "VirtualRun") == 0;
}

static inline const char *strava_identity_line(Arena *arena, long long id) {
  JSONBuf line;
  jsonbuf_init_strict(&line, arena);
  jsonbuf_appendf(&line, "%s%s%lld", STRAVA_LINE_PREFIX, STRAVA_ACTIVITY_URL,
                  id);
  return line.data;
}

// Where `line` is, as a whole line of `content`, or NULL.
static inline const char *strava_find_line(const char *content,
                                           const char *line) {
  size_t len = strlen(line);
  for (const char *p = strstr(content, line); p; p = strstr(p + 1, line)) {
    bool starts = p == content || p[-1] == '\n';
    bool ends = p[len] == '\0' || p[len] == '\n' || p[len] == '\r';
    if (starts && ends) {
      return p;
    }
  }
  return NULL;
}

// The content: a line of facts, the description if there is one, and the
// identity line - each part a paragraph, so the reader shows them apart.
// `tail` is whatever followed the identity line in the entry already (a
// note the captain added under it), kept as it was: an update rewrites
// only what came from Strava.
static inline const char *
StravaEntryContent(Arena *arena, const StravaActivity *a, const char *tail) {
  assert(arena_valid(arena));
  assert(a != NULL);

  JSONBuf b;
  jsonbuf_init_strict(&b, arena);
  const char *sep = " \xC2\xB7 "; // " · "
  strava_append_sport(&b, a->sport_type);
  if (a->distance_m > 0) {
    jsonbuf_appendf(&b, "%s%.2f km", sep, a->distance_m / 1000.0);
  }
  if (a->moving_s > 0) {
    jsonbuf_appendf(&b, "%smoving ", sep);
    strava_append_duration(&b, a->moving_s);
  }
  if (a->elapsed_s > 0) {
    jsonbuf_appendf(&b, "%selapsed ", sep);
    strava_append_duration(&b, a->elapsed_s);
  }
  if (a->elevation_m >= 1) {
    jsonbuf_appendf(&b, "%s%.0f m up", sep, a->elevation_m);
  }
  if (a->average_hr > 0) {
    jsonbuf_appendf(&b, "%sHR %.0f avg", sep, a->average_hr);
    if (a->max_hr > 0) {
      jsonbuf_appendf(&b, " / %.0f max", a->max_hr);
    }
  }
  if (a->average_speed > 0 && a->distance_m > 0) {
    if (strava_is_run(a->sport_type)) {
      int pace = (int)lround(1000.0 / a->average_speed); // seconds per km
      jsonbuf_appendf(&b, "%s%d:%02d /km", sep, pace / 60, pace % 60);
    } else {
      jsonbuf_appendf(&b, "%s%.1f km/h", sep, a->average_speed * 3.6);
    }
  }
  if (a->calories > 0) {
    jsonbuf_appendf(&b, "%s%.0f kcal", sep, a->calories);
  }
  jsonbuf_append(&b, "\n\n");
  if (a->description[0] != '\0') {
    jsonbuf_append(&b, a->description);
    jsonbuf_append(&b, "\n\n");
  }
  jsonbuf_append(&b, strava_identity_line(arena, a->id));
  if (tail) {
    jsonbuf_append(&b, tail);
  }
  return b.data;
}

// ---------------------------------------------------------------------------
// The pull
// ---------------------------------------------------------------------------

// The journal's entry for activity `id`, soft-deleted ones included (a
// workout he threw away must not come back on the next pull). `found` is
// false when there is none.
static inline bool strava_find_entry(Arena *arena, const CliOptions *opts,
                                     const char *kind, long long id,
                                     EntryRow *out, bool *found, char *err,
                                     size_t err_size) {
  char q[96];
  snprintf(q, sizeof(q), "strava.com/activities/%lld", id);
  CliFilters f;
  memset(&f, 0, sizeof(f));
  f.kind = kind;
  f.q = q;
  f.done = -1;
  f.deleted = "all";
  f.order = "id";
  f.dir = "asc";
  f.limit = 20; // the prefix matches: .../12 finds .../123 too
  f.include_content = true;

  EntryRows rows = {0};
  if (!CliListEntries(arena, opts, &f, &rows, err, err_size)) {
    return false;
  }
  const char *line = strava_identity_line(arena, id);
  *found = false;
  for (int i = 0; i < rows.count; i++) {
    if (rows.items[i].content &&
        strava_find_line(rows.items[i].content, line)) {
      *out = rows.items[i];
      *found = true;
      return true;
    }
  }
  return true;
}

// What follows the identity line in an entry's content, or "".
static inline const char *strava_tail(const char *content, long long id,
                                      Arena *arena) {
  const char *line = strava_identity_line(arena, id);
  const char *at = strava_find_line(content, line);
  return at ? at + strlen(line) : "";
}

// One page of the list, or a 429 (rate_limited, true returned, no items).
static inline bool strava_list_page(Arena *arena, const StravaOptions *so,
                                    const StravaToken *tok, long long after,
                                    int page, JsonSpan *out_items,
                                    StravaPullStats *stats, char *err,
                                    size_t err_size) {
  JSONBuf path;
  jsonbuf_init_strict(&path, arena);
  jsonbuf_appendf(&path,
                  "/api/v3/athlete/activities?after=%lld&page=%d"
                  "&per_page=%d",
                  after, page, STRAVA_PER_PAGE);
  JsonSpan body;
  long status = 0;
  stats->requests++;
  if (!StravaRequest(arena, so, path.data, NULL, tok->access_token, &body,
                     &status, err, err_size)) {
    return false;
  }
  out_items->data = "[]";
  out_items->len = 2;
  if (status == 429) {
    stats->rate_limited = true;
    return true;
  }
  if (status != 200) {
    return strava_status_error("strava activities", body, status, err,
                               err_size);
  }
  if (body.len == 0 || body.data[0] != '[') {
    return CliFail(err, err_size, "strava activities: not a list: %.*s",
                   (int)(body.len < 200 ? body.len : 200), body.data);
  }
  *out_items = body;
  return true;
}

// The detail of one activity, over `a` (the summary's fields are kept where
// the detail lacks them). A 429 sets rate_limited and returns true.
static inline bool strava_detail(Arena *arena, const StravaOptions *so,
                                 const StravaToken *tok, StravaActivity *a,
                                 StravaPullStats *stats, char *err,
                                 size_t err_size) {
  char path[96];
  snprintf(path, sizeof(path), "/api/v3/activities/%lld", a->id);
  JsonSpan body;
  long status = 0;
  stats->requests++;
  if (!StravaRequest(arena, so, path, NULL, tok->access_token, &body, &status,
                     err, err_size)) {
    return false;
  }
  if (status == 429) {
    stats->rate_limited = true;
    return true;
  }
  if (status != 200) {
    return strava_status_error("strava activity", body, status, err, err_size);
  }
  StravaActivity d;
  strava_parse_activity(arena, body, &d);
  if (d.id != a->id || d.start_epoch == 0) {
    return CliFail(err, err_size, "strava activity %lld: odd answer: %.*s",
                   a->id, (int)(body.len < 200 ? body.len : 200), body.data);
  }
  *a = d;
  return true;
}

static inline void strava_print_activity(const char *verb,
                                         const StravaActivity *a, int entry) {
  printf("%-9s %.16s  %-28.28s %7.2f km %4d min  strava %lld", verb,
         a->start_utc, a->name, strava_km(a), strava_minutes(a), a->id);
  if (entry > 0) {
    printf("  #%d", entry);
  }
  printf("\n");
}

// One activity from the list: look it up, and create, update or leave it.
// The detail is fetched only when something will be written - a new
// activity, or one whose name, distance or moving time no longer match the
// entry - so an hourly pull over the overlap costs Strava nothing when
// nothing happened. (A description edited alone on Strava is therefore not
// followed; a rename is, and brings the description with it.)
// Returns false only on a journal failure; a Strava failure for this one
// activity (bar a 429) is counted and the pull goes on.
static inline bool strava_pull_one(Arena *arena, const CliOptions *opts,
                                   const StravaOptions *so,
                                   const StravaToken *tok,
                                   const StravaPullOptions *po,
                                   StravaActivity *a, StravaPullStats *stats,
                                   char *err, size_t err_size) {
  EntryRow row;
  bool found = false;
  if (!strava_find_entry(arena, opts, po->kind, a->id, &row, &found, err,
                         err_size)) {
    return false;
  }
  if (found && row.deleted) {
    stats->deleted++;
    if (po->verbose) {
      strava_print_activity("deleted", a, row.id);
    }
    return true;
  }
  if (found && strcmp(row.title, a->name) == 0 &&
      fabs(row.value_float - strava_km(a)) < 0.0005 &&
      row.value_int == strava_minutes(a)) {
    stats->unchanged++;
    if (po->verbose) {
      strava_print_activity("unchanged", a, row.id);
    }
    return true;
  }
  if (po->dry_run) {
    found ? stats->updated++ : stats->created++;
    strava_print_activity(found ? "update" : "create", a, found ? row.id : 0);
    return true;
  }

  char detail_err[CLI_ERR_SIZE] = {0};
  if (!strava_detail(arena, so, tok, a, stats, detail_err,
                     sizeof(detail_err))) {
    fprintf(stderr, "lcars-cli: %s\n", detail_err);
    stats->failed++;
    return true;
  }
  if (stats->rate_limited) {
    return true;
  }

  CliFields f;
  memset(&f, 0, sizeof(f));
  f.has_title = true;
  f.title = a->name;
  f.has_content = true;
  f.content = StravaEntryContent(
      arena, a,
      found && row.content ? strava_tail(row.content, a->id, arena) : NULL);
  f.has_value_float = true;
  f.value_float = strava_km(a);
  f.has_value_int = true;
  f.value_int = strava_minutes(a);
  if (found) {
    // Never created_at_utc: it was set from the start once, and he may have
    // moved it since.
    if (strcmp(row.title, f.title) == 0 &&
        strcmp(row.content ? row.content : "", f.content) == 0 &&
        fabs(row.value_float - f.value_float) < 0.0005 &&
        row.value_int == f.value_int) {
      stats->unchanged++;
      return true;
    }
    if (!CliUpdateEntry(arena, opts, row.id, &f, err, err_size)) {
      return false;
    }
    stats->updated++;
    strava_print_activity("updated", a, row.id);
    return true;
  }
  f.has_kind = true;
  f.kind = po->kind;
  f.has_created_at = true;
  f.created_at = a->start_utc;
  int id = 0;
  if (!CliCreateEntry(arena, opts, &f, &id, err, err_size)) {
    return false;
  }
  stats->created++;
  strava_print_activity("created", a, id);
  return true;
}

// Lists every activity started after `po->after`, page by page until an
// empty one, and writes each into the journal (strava_pull_one). Stops at
// the first 429 with stats->rate_limited set and true returned: that is
// the expected end of a long backfill, not an error. With `after` the list
// comes oldest first, so newest_done_epoch is a place to resume from.
// Each page and each activity is built in the arena and released after it:
// a backfill of thousands of activities must fit in a run's 32MB.
static inline bool StravaPull(Arena *arena, const CliOptions *opts,
                              const StravaOptions *so, const StravaToken *tok,
                              const StravaPullOptions *po,
                              StravaPullStats *stats, char *err,
                              size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && so != NULL && tok != NULL && po != NULL);
  assert(stats != NULL);

  memset(stats, 0, sizeof(*stats));
  for (int page = 1;; page++) {
    ArenaMark page_mark = arena_mark(arena);
    JsonSpan items;
    if (!strava_list_page(arena, so, tok, po->after, page, &items, stats, err,
                          err_size)) {
      return false;
    }
    if (stats->rate_limited) {
      return true;
    }
    const char *cursor = NULL;
    JsonSpan item;
    int on_page = 0;
    while (json_array_next(items, &cursor, &item)) {
      on_page++;
      ArenaMark mark = arena_mark(arena);
      StravaActivity a;
      strava_parse_activity(arena, item, &a);
      if (a.id <= 0 || a.start_epoch == 0) {
        fprintf(stderr, "lcars-cli: skipping a strava activity without an id "
                        "or a start date\n");
        stats->failed++;
        arena_restore(arena, mark);
        continue;
      }
      stats->seen++;
      if (!strava_pull_one(arena, opts, so, tok, po, &a, stats, err,
                           err_size)) {
        return false;
      }
      if (stats->rate_limited) {
        return true;
      }
      if (stats->failed == 0 && a.start_epoch > stats->newest_done_epoch) {
        stats->newest_done_epoch = a.start_epoch;
      }
      arena_restore(arena, mark);
    }
    arena_restore(arena, page_mark);
    if (on_page == 0) {
      return true;
    }
  }
}

#endif // LCARS_IMPLEMENTATION
#endif // LCARS_STRAVA_H
