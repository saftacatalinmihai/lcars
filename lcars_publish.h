#ifndef LCARS_PUBLISH_H
#define LCARS_PUBLISH_H

// /publish - the Share sheet's Post (docs/design/social-publish.md, 3.1 and
// 3.8, slice 2). The posting itself is scripts/publish.py's; these routes
// run it with fixed argv and hand its one JSON object back:
//
//   POST /publish/<id>      {networks: ["mastodon", ...], dry_run?: bool}
//                           `publish.py post <id> --networks a,b --by tap
//                           [--dry-run]`: one result per network (posted,
//                           dry, already, capped, invalid, unconfigured,
//                           refused, failed), 60 s at most
//   POST /publish/card      {url}: `publish.py card <url>`, a link's og:
//                           title, description, picture and site, 20 s at
//                           most. A body, not ?url=: a request target is
//                           cut at 255 bytes (HTTPRequestLine), and a
//                           shortened link would read another page's card
//
// The guard, because a post goes out under the captain's name:
//   1. The owner's login only. Every limited login (Number One, the crew,
//      the steward) is refused by LimitedAllowed before this is reached,
//      and again here.
//   2. From the pages only: X-LCARS-Client, as the patch kinds and
//      `social_post` itself (PatchKindAllowed). lcars-cli sends none, so a
//      chat agent - whose only Bash is lcars-cli - cannot post, and cannot
//      write the drafts a post is made of either.
//   3. One run at a time (a 429): two taps at once cannot both pass
//      publish.py's once-per-text check before either has written its
//      record.
//   4. `id` is digits and each network a short lowercase word, checked
//      here before anything runs; the card's url is http(s), one line, at
//      most PUBLISH_URL_MAX bytes, and publish.py refuses one that is not on
//      the public internet (the box must not be a way into the tailnet).
// Nothing of the post's text goes through the server's argv or its log:
// publish.py reads it from the entry, and the log line names the id, the
// networks and the outcome.
//
// publish.py's environment is the server's (the unit sourced ~/.env, so it
// holds LCARS_PUB_* and the crew login it writes its records with) less the
// engineer key, with LCARS_URL aimed back at this server. The script is
// $LCARS_PUBLISH_SCRIPT, else scripts/publish.py under the working
// directory (the unit's is the live checkout). The exit status picks the
// HTTP one as the engineers' does (EngineerStatus: 2 a 400, 4 a 404).
//
// A module of lcars_http.h, included from inside its implementation block
// after lcars_engineer.h, whose ScriptExec and EngineerStatus it uses.

static bool IsPublishPath(const char *path);
static int HandlePublish(int client_fd, Arena *arena, const char *method,
                         const char *path, const char *req_buf,
                         const char *body, const char *content_type);

#ifdef LCARS_PUBLISH_IMPLEMENTATION

#define PUBLISH_POST_SECONDS 60
#define PUBLISH_CARD_SECONDS 20
#define PUBLISH_URL_MAX 2048
#define PUBLISH_NETWORKS_MAX 8
#define PUBLISH_NETWORK_MAX 16

static atomic_int g_publish_active = 0;

static bool IsPublishPath(const char *path) {
  assert(path != NULL);
  return strcmp(path, "/publish") == 0 || strncmp(path, "/publish/", 9) == 0;
}

// The script's path, or false with the client answered.
static bool PublishScript(int client_fd, char *out, size_t out_size,
                          int *status) {
  assert(out != NULL && out_size > 64 && status != NULL);
  const char *s = getenv("LCARS_PUBLISH_SCRIPT");
  if (s != NULL && s[0] != '\0') {
    snprintf(out, out_size, "%s", s);
  } else if (getcwd(out, out_size - 32) != NULL) {
    strcat(out, "/scripts/publish.py");
  } else {
    *status = SendJSONError(client_fd, 500, "cannot find scripts/publish.py");
    return false;
  }
  if (access(out, R_OK) != 0) {
    *status = SendJSONError(client_fd, 503, "%s is missing", out);
    return false;
  }
  return true;
}

// The server's environment less the engineer key and anything that says
// "nested in Claude Code", LCARS_URL this server.
static char **PublishEnv(Arena *arena) {
  assert(arena_valid(arena));
  size_t count = 0;
  while (environ[count] != NULL) {
    count++;
  }
  char **env = (char **)arena_alloc(arena, (count + 2) * sizeof(char *));
  size_t n = 0;
  for (size_t i = 0; i < count; i++) {
    const char *e = environ[i];
    if (strncmp(e, "LCARS_URL=", 10) == 0 ||
        strncmp(e, "LCARS_ENGINEER_KEY=", 19) == 0 ||
        strncmp(e, "CLAUDECODE=", 11) == 0 ||
        strncmp(e, "CLAUDE_CODE_ENTRYPOINT=", 23) == 0) {
      continue;
    }
    env[n++] = (char *)e;
  }
  char *url = (char *)arena_alloc(arena, 64);
  snprintf(url, 64, "LCARS_URL=http://127.0.0.1:%d",
           g_http_port > 0 ? g_http_port : 8080);
  env[n++] = url;
  env[n] = NULL;
  assert(n <= count + 1);
  return env;
}

// How long a run may take: the route's own, or $LCARS_PUBLISH_TIMEOUT
// seconds when shorter (test/publish.py's timeout case, not a setting).
static int PublishTimeout(int dflt) {
  const char *t = getenv("LCARS_PUBLISH_TIMEOUT");
  int v = t != NULL ? atoi(t) : 0;
  return v > 0 && v < dflt ? v : dflt;
}

// One run of publish.py, the client answered with what it printed.
static int PublishRun(int client_fd, Arena *arena, const char *const *args,
                      int timeout_s, const char *what) {
  char script[1024];
  int status = 0;
  if (!PublishScript(client_fd, script, sizeof(script), &status)) {
    return status;
  }
  if (atomic_fetch_add(&g_publish_active, 1) >= 1) {
    atomic_fetch_sub(&g_publish_active, 1);
    return SendJSONError(client_fd, 429, "a post is already being sent");
  }
  char *out = NULL;
  size_t len = 0;
  int code = 0;
  double start = GetTimeSeconds();
  int sent = ScriptExec(client_fd, arena, "publish.py", script, args, "", 0,
                        PublishTimeout(timeout_s), PublishEnv(arena), &out,
                        &len, &code);
  atomic_fetch_sub(&g_publish_active, 1);
  int ms = (int)((GetTimeSeconds() - start) * 1000);
  if (sent != 0) {
    printf("HTTP publish: %s -> %d %dms\n", what, sent, ms);
    return sent;
  }
  printf("HTTP publish: %s -> exit %d %dms\n", what, code, ms);
  return SendJSON(client_fd, EngineerStatus(code), out, len);
}

// A network's name as publish.py takes it: a short lowercase word.
static bool PublishNetworkOk(const char *s, size_t len) {
  if (len == 0 || len > PUBLISH_NETWORK_MAX) {
    return false;
  }
  for (size_t i = 0; i < len; i++) {
    if (s[i] < 'a' || s[i] > 'z') {
      return false;
    }
  }
  return true;
}

// POST /publish/<id>: the body's networks joined by commas into `out`.
static bool PublishNetworks(const char *body, char *out, size_t out_size) {
  assert(body != NULL && out != NULL && out_size > 0);
  out[0] = '\0';
  JsonSpan arr;
  if (!json_body_member(body, "networks", &arr) || arr.len < 2 ||
      arr.data[0] != '[') {
    return false;
  }
  const char *p = arr.data + 1, *end = arr.data + arr.len - 1;
  size_t used = 0;
  int n = 0;
  while (p < end) {
    while (p < end &&
           (*p == ' ' || *p == ',' || *p == '\n' || *p == '\t' || *p == '\r')) {
      p++;
    }
    if (p >= end) {
      break;
    }
    if (*p != '"') {
      return false;
    }
    const char *q = memchr(p + 1, '"', (size_t)(end - p - 1));
    if (q == NULL) {
      return false;
    }
    size_t len = (size_t)(q - p - 1);
    if (!PublishNetworkOk(p + 1, len) || ++n > PUBLISH_NETWORKS_MAX ||
        used + len + 2 > out_size) {
      return false;
    }
    if (used > 0) {
      out[used++] = ',';
    }
    memcpy(out + used, p + 1, len);
    used += len;
    out[used] = '\0';
    p = q + 1;
  }
  return n > 0;
}

static bool PublishDryRun(const char *body) {
  JsonSpan v;
  return json_body_member(body, "dry_run", &v) && v.len == 4 &&
         memcmp(v.data, "true", 4) == 0;
}

static int HandlePublish(int client_fd, Arena *arena, const char *method,
                         const char *path, const char *req_buf,
                         const char *body, const char *content_type) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL && path != NULL && req_buf != NULL);
  if (g_conn_login != NULL) {
    return SendJSONError(client_fd, 403,
                         "%s may not post: the owner's login only",
                         g_conn_login->who);
  }
  if (find_header_value(req_buf, "X-LCARS-Client:") == NULL) {
    return SendJSONError(client_fd, 403,
                         "posting is the LCARS pages' only (X-LCARS-Client): "
                         "tap Post in the Share sheet");
  }

  if (strcmp(path, "/publish/card") == 0) {
    if (strcmp(method, "POST") != 0) {
      return SendJSONError(client_fd, 405,
                           "Method %s not allowed on /publish/card", method);
    }
    char *url = NULL;
    if (content_type == NULL ||
        strncasecmp(content_type, "application/json", 16) != 0 ||
        body == NULL || !json_get_string_arena(arena, body, "url", &url) ||
        url[0] == '\0') {
      return SendJSONError(client_fd, 400, "Body must be JSON: {\"url\": ...}");
    }
    bool ok =
        strncmp(url, "http://", 7) == 0 || strncmp(url, "https://", 8) == 0;
    for (const char *c = url; ok && *c; c++) {
      ok = (unsigned char)*c > ' ' && *c != 0x7f;
    }
    if (!ok || strlen(url) > PUBLISH_URL_MAX) {
      return SendJSONError(client_fd, 400,
                           "\"url\" must be one http(s) link, %d bytes at most",
                           PUBLISH_URL_MAX);
    }
    const char *args[] = {"card", url, NULL};
    return PublishRun(client_fd, arena, args, PUBLISH_CARD_SECONDS, "card");
  }

  const char *id = path + 9; // after "/publish/"
  size_t id_len = strncmp(path, "/publish/", 9) == 0 ? strlen(id) : 0;
  bool digits = id_len > 0 && id_len <= 10;
  for (size_t i = 0; digits && i < id_len; i++) {
    digits = id[i] >= '0' && id[i] <= '9';
  }
  if (!digits) {
    return SendJSONError(client_fd, 404, "No route for %s %s", method, path);
  }
  if (strcmp(method, "POST") != 0) {
    return SendJSONError(client_fd, 405, "Method %s not allowed on %s", method,
                         path);
  }
  if (content_type == NULL ||
      strncasecmp(content_type, "application/json", 16) != 0) {
    return SendJSONError(client_fd, 415,
                         "Body must be JSON: {\"networks\": [...]}");
  }
  char nets[PUBLISH_NETWORKS_MAX * (PUBLISH_NETWORK_MAX + 1) + 1];
  if (body == NULL || !PublishNetworks(body, nets, sizeof(nets))) {
    return SendJSONError(client_fd, 400,
                         "\"networks\": 1 to %d names, lowercase letters",
                         PUBLISH_NETWORKS_MAX);
  }
  bool dry = PublishDryRun(body);
  const char *args[] = {
      "post", id, "--networks", nets, "--by", "tap", dry ? "--dry-run" : NULL,
      NULL};
  char what[sizeof(nets) + 48];
  snprintf(what, sizeof(what), "post #%s %s%s", id, nets, dry ? " dry" : "");
  return PublishRun(client_fd, arena, args, PUBLISH_POST_SECONDS, what);
}

#endif // LCARS_PUBLISH_IMPLEMENTATION
#endif // LCARS_PUBLISH_H
