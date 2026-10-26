#ifndef LCARS_ENGINEER_H
#define LCARS_ENGINEER_H

// /engineer - crew in the 3D deck who change LCARS itself.
//
// A crew member promoted in the deck is a Claude Code session working in a
// git worktree of its own, run by herdr with Remote Control on. Everything
// about that - worktrees, herdr, the transcript, deploy and rollback - lives
// in scripts/engineer.py; these routes only run it with fixed argv and hand
// its one JSON object back:
//
//   GET  /engineer                  every engineer, and the deploy state
//   GET  /engineer/queue            the Queue view: the seat, its line with
//                                   each one's order, and every deploy
//                                   (newest first: versions, headlines,
//                                   outcome). "queue" is no engineer's name
//   POST /engineer/queue/move       {name, to: up|down|first, expect}: the
//                                   seat's line reordered
//   POST /engineer/queue/remove     {name, expect}: one out of it, their
//                                   undelivered orders cancelled (kept)
//   POST /engineer/queue/restore    {name?}: the latest removal undone
//                                   `expect` is the line as the client read
//                                   it, names joined by commas: a line that
//                                   changed since (a handoff, a new order)
//                                   is a 409 and nothing is done. Only the
//                                   queue: never the one seated, nor a turn
//   GET  /engineer/<name>?off=<n>   status, the dialog on screen if any, and
//                                   the conversation since byte <n> (-1: tail);
//                                   &before=<b>: the page ending at byte <b>;
//                                   &past=<session>: one of their earlier
//                                   conversations (kept by a clear) instead,
//                                   read-only; &thread=<id>: only the events
//                                   of that thread of Number One's (docs/
//                                   design/no1-threads.md, 13). Number One's
//                                   events each carry `th`, its answer the
//                                   open `threads` (id, name)
//   GET  /engineer/<name>/image?k=<session>:<offset>:<index>
//                                   a picture the session saw, as the poll's
//                                   "img" event keys it: its own type, 8 MB
//                                   at most (a 413), cached privately for a
//                                   year; a key naming none a 404
//   GET  /engineer/<role>/brief     a scheduled role's brief, crew/<role>.md
//                                   (read-only; the console's chat as that
//                                   role)
//   POST /engineer/<name>/start     {title, who}: worktree, herdr tab, session
//   POST /engineer/<name>/say       {message, attachments?, thread?}: typed
//                                   into their session; attachments as POST
//                                   /chat takes them (lcars_chat.h), one line
//                                   each with the file's path and URL.
//                                   `thread`, a room (docs/design/rooms.md):
//                                   to Number One typed under its header; to
//                                   an engineer a project room's, filed
//                                   there to:: them (the Rooms page's To
//                                   chip); an unknown one a 404, a closed
//                                   one reopened
//   POST /engineer/number-one/thread
//                                   {op, id, name?}: new, rename, close -
//                                   labels only, the list in the answer
//   POST /engineer/<name>/key       {key}: answer a dialog (1-9, enter, esc…)
//   POST /engineer/<name>/stop      end the session; worktree and branch stay
//   POST /engineer/<name>/deploy    ship eng/<name> (detached; poll for it)
//   POST /engineer/<name>/model     {model}: sonnet|haiku|opus|fable - their
//                                   session restarted (resumed) on it now if
//                                   idle, at the turn's end if working
//                                   ({pending: true}), at the next start if
//                                   off; a question on screen is a 409. The
//                                   poll and the list say model,
//                                   model_pending and model_used
//   POST /engineer/<name>/job-cancel
//                                   {id?}: their job taken back, out of the
//                                   job line or a running one stopped
//                                   (docs/design/job-queue.md); none is a 409
//   POST /engineer/number-one/refresh
//                                   Number One writes a handover note, is
//                                   cleared, and reads it back (detached)
//   POST /engineer/rollback         undo the last deploy (detached)
//
// The script's exit status picks the HTTP one: 0 is 200, 2 a 400, 3 a 409
// ("not now": busy, at a dialog, a deploy already running), 4 a 404 (no
// such thread), anything else a 500.
//
// Security. This is a shell on the VPS by design - an engineer can do what
// the captain can at a terminal - so the API password is not enough. Every
// route here needs all of:
//   1. LCARS_ENGINEER=1 in the unit's environment; otherwise these routes
//      are a 404, as if they did not exist.
//   2. A loopback peer, which is tailscale serve: the public port never
//      reaches an engineer, whatever password it carries.
//   3. If LCARS_ENGINEER_LOGIN is set, the Tailscale-User-Login header
//      tailscale serve adds must equal it - another tailnet member is not
//      the captain. (Anything on the VPS itself can forge that header, which
//      is what 4 is for.)
//   4. X-LCARS-Engineer-Key equal to LCARS_ENGINEER_KEY (16+ characters), a
//      secret apart from the API password, that the deck asks for once and
//      keeps on the device. It is kept out of the journal chat's claude
//      (ChatBuildEnv), which holds the API password and reads the web, and
//      out of the script's environment. An engineer, being a shell of the
//      captain's own, can read ~/.env like any other; that is not the
//      boundary this guards.
// This is a module of lcars_http.h, included from inside its implementation
// block after lcars_chat.h, whose pipe and spawn helpers it reuses.

static bool IsEngineerPath(const char *path);
static int HandleEngineer(int client_fd, Arena *arena, const char *method,
                          const char *path, const char *query,
                          const char *req_buf, const char *body);

#ifdef LCARS_ENGINEER_IMPLEMENTATION

// Longest the script may take. `start` waits up to 60s for Claude Code to be
// ready; a poll or a say is well under a second.
#define ENGINEER_TIMEOUT_SECONDS 100
// What is read of the script's answer. A poll is capped well below this by
// the script (events and text clipped), and the response is built in the 1MB
// connection arena.
#define ENGINEER_MAX_OUTPUT (384 * 1024)
#define ENGINEER_MAX_INPUT (32 * 1024)
#define ENGINEER_KEY_MIN 16

static bool IsEngineerPath(const char *path) {
  assert(path != NULL);
  return strcmp(path, "/engineer") == 0 || strncmp(path, "/engineer/", 10) == 0;
}

// Equal without an early exit, so the time taken says nothing about how much
// of the key a guess got right.
static bool EngineerKeyEqual(const char *a, const char *b) {
  assert(a != NULL && b != NULL);
  size_t la = strlen(a), lb = strlen(b);
  unsigned char diff = (unsigned char)(la != lb);
  for (size_t i = 0; i < la; i++) {
    diff |= (unsigned char)(a[i] ^ b[i % (lb ? lb : 1)]);
  }
  return diff == 0;
}

// Sends the refusal itself and returns 0 when the request may not reach an
// engineer; returns 1 when it may.
static int EngineerGate(int client_fd, const char *req_buf, int *status) {
  assert(req_buf != NULL && status != NULL);
  const char *on = getenv("LCARS_ENGINEER");
  if (on == NULL || strcmp(on, "1") != 0) {
    *status = SendJSONError(client_fd, 404,
                            "engineers are off on this server "
                            "(LCARS_ENGINEER=1 turns them on)");
    return 0;
  }
  const char *key = getenv("LCARS_ENGINEER_KEY");
  if (key == NULL || strlen(key) < ENGINEER_KEY_MIN) {
    *status = SendJSONError(client_fd, 403,
                            "LCARS_ENGINEER_KEY is not set (or under %d "
                            "characters) on the server",
                            ENGINEER_KEY_MIN);
    return 0;
  }
  if (!MediaPeerIsLoopback(client_fd)) {
    *status = SendJSONError(client_fd, 403,
                            "engineers answer only through tailscale serve");
    return 0;
  }
  char login[256];
  CopyHeaderValue(req_buf, "Tailscale-User-Login:", login, sizeof(login));
  const char *want = getenv("LCARS_ENGINEER_LOGIN");
  if (want != NULL && want[0] != '\0' && strcmp(login, want) != 0) {
    // the login seen is logged (not answered) - it is what to set
    // LCARS_ENGINEER_LOGIN to, on a first setup
    printf("HTTP engineer: refused tailnet login '%s'\n", login);
    *status = SendJSONError(client_fd, 403,
                            "this tailnet login may not reach engineers");
    return 0;
  }
  char given[256];
  if (!CopyHeaderValue(req_buf, "X-LCARS-Engineer-Key:", given,
                       sizeof(given)) ||
      !EngineerKeyEqual(given, key)) {
    *status = SendJSONError(client_fd, 401, "engineer key missing or wrong");
    return 0;
  }
  return 1;
}

// The script's environment: the server's, less the engineer key, with the
// user's own bin first (herdr lives there, and the unit's PATH has none of
// the per-user installs).
static char **EngineerEnv(Arena *arena) {
  assert(arena_valid(arena));
  size_t count = 0;
  while (environ[count] != NULL) {
    count++;
  }
  char **env = (char **)arena_alloc(arena, (count + 2) * sizeof(char *));
  size_t n = 0;
  const char *old_path = "/usr/local/bin:/usr/bin:/bin";
  for (size_t i = 0; i < count; i++) {
    const char *e = environ[i];
    if (strncmp(e, "PATH=", 5) == 0) {
      old_path = e + 5;
      continue;
    }
    if (strncmp(e, "LCARS_ENGINEER_KEY=", 19) == 0 ||
        strncmp(e, "CLAUDECODE=", 11) == 0 ||
        strncmp(e, "CLAUDE_CODE_ENTRYPOINT=", 23) == 0) {
      continue;
    }
    env[n++] = (char *)e;
  }
  const char *home = getenv("HOME");
  size_t len = strlen(old_path) + (home ? strlen(home) : 0) + 32;
  char *path = (char *)arena_alloc(arena, len);
  snprintf(path, len, "PATH=%s/.local/bin:%s", home ? home : "", old_path);
  env[n++] = path;
  env[n] = NULL;
  assert(n <= count + 1);
  return env;
}

// The python3 engineer.py runs under: $LCARS_PYTHON, else the first python3
// on $PATH, as a shell would find it (the VPS's unit PATH reaches
// /usr/bin/python3, what it has always run; a box that keeps it in
// /usr/local/bin or a distro's own place finds that). No PATH at all is
// the default a shell assumes, /usr/bin:/bin. Resolved to a path here
// because posix_spawn does not search PATH. False if there is none.
// lcars_features.h's engineers check asks this too, so /features and the
// route agree on whether there is one.
static bool EngineerPython(char *out, size_t out_size) {
  assert(out != NULL && out_size > 1);
  const char *env = getenv("LCARS_PYTHON");
  if (env != NULL && env[0] != '\0') {
    snprintf(out, out_size, "%s", env);
    return true;
  }
  const char *path = getenv("PATH");
  if (path == NULL || path[0] == '\0') {
    path = "/usr/bin:/bin";
  }
  while (path != NULL && *path != '\0') {
    const char *colon = strchr(path, ':');
    size_t len = colon ? (size_t)(colon - path) : strlen(path);
    if (len > 0 && len + sizeof("/python3") <= out_size) {
      memcpy(out, path, len);
      memcpy(out + len, "/python3", sizeof("/python3"));
      if (access(out, X_OK) == 0) {
        return true;
      }
    }
    path = colon ? colon + 1 : NULL;
  }
  out[0] = '\0';
  return false;
}

static int ScriptExec(int client_fd, Arena *arena, const char *label,
                      const char *script, const char *const *args,
                      const char *input, size_t input_len, int timeout_s,
                      char **env, char **out, size_t *out_len, int *code);

// Runs scripts/engineer.py with argv[] (after the script's path) and `input`
// on stdin. Returns 0 with what it printed (*out, *out_len, trailing
// whitespace off) and its exit status (*code); otherwise it has answered the
// client itself (no script, a timeout, nothing usable) and returns that
// status.
static int EngineerExec(int client_fd, Arena *arena, const char *const *args,
                        const char *input, size_t input_len, char **out,
                        size_t *out_len, int *code) {
  assert(arena_valid(arena));
  assert(args != NULL);
  assert(input_len <= ENGINEER_MAX_INPUT);

  char script[1024];
  const char *s = getenv("LCARS_ENGINEER_SCRIPT");
  if (s != NULL && s[0] != '\0') {
    snprintf(script, sizeof(script), "%s", s);
  } else if (getcwd(script, sizeof(script) - 32) != NULL) {
    // the unit's WorkingDirectory is the live checkout
    strcat(script, "/scripts/engineer.py");
  } else {
    return SendJSONError(client_fd, 500, "cannot find scripts/engineer.py");
  }
  if (access(script, R_OK) != 0) {
    return SendJSONError(client_fd, 503, "%s is missing", script);
  }

  return ScriptExec(client_fd, arena, "engineer.py", script, args, input,
                    input_len, ENGINEER_TIMEOUT_SECONDS, EngineerEnv(arena),
                    out, out_len, code);
}

// Runs `python3 <script> args...` (argv only, no shell) with `input` on
// stdin and `env` as its environment, in a process group of its own so a
// timeout kills all of it. Returns 0 with what it printed (*out, *out_len,
// trailing whitespace off) and its exit status (*code); otherwise it has
// answered the client itself (no python3, a timeout, nothing usable) and
// returns that status. `label` names the script in those answers. The
// engineers' routes and POST /publish (lcars_publish.h) both run this way.
static int ScriptExec(int client_fd, Arena *arena, const char *label,
                      const char *script, const char *const *args,
                      const char *input, size_t input_len, int timeout_s,
                      char **env, char **out, size_t *out_len, int *code) {
  assert(arena_valid(arena));
  assert(label != NULL && script != NULL && args != NULL && env != NULL);
  assert(input_len <= ENGINEER_MAX_INPUT);
  assert(timeout_s > 0);
  char python[1024];
  if (!EngineerPython(python, sizeof(python))) {
    return SendJSONError(client_fd, 503, "no python3 ($PATH or $LCARS_PYTHON)");
  }
  const char *argv[16];
  int argc = 0;
  argv[argc++] = python;
  argv[argc++] = script;
  for (int i = 0; args[i] != NULL; i++) {
    assert(argc < 15);
    argv[argc++] = args[i];
  }
  argv[argc] = NULL;

  int in_pipe[2] = {-1, -1}, out_pipe[2] = {-1, -1};
  if (!ChatPipe(in_pipe) || !ChatPipe(out_pipe)) {
    if (in_pipe[0] >= 0) {
      close(in_pipe[0]);
      close(in_pipe[1]);
    }
    return SendJSONError(client_fd, 500, "pipe failed: %s", strerror(errno));
  }
  posix_spawn_file_actions_t fa;
  posix_spawnattr_t attr;
  posix_spawn_file_actions_init(&fa);
  posix_spawnattr_init(&attr);
  posix_spawn_file_actions_adddup2(&fa, in_pipe[0], STDIN_FILENO);
  posix_spawn_file_actions_adddup2(&fa, out_pipe[1], STDOUT_FILENO);
#if CHAT_HAVE_CLOSEFROM
  posix_spawn_file_actions_addclosefrom_np(&fa, STDERR_FILENO + 1);
#endif
  posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);
  posix_spawnattr_setpgroup(&attr, 0);
  pid_t pid = -1;
  int rc = posix_spawn(&pid, argv[0], &fa, &attr, (char *const *)argv, env);
  posix_spawn_file_actions_destroy(&fa);
  posix_spawnattr_destroy(&attr);
  close(in_pipe[0]);
  close(out_pipe[1]);
  if (rc != 0) {
    close(in_pipe[1]);
    close(out_pipe[0]);
    return SendJSONError(client_fd, 503, "could not run python3: %s",
                         strerror(rc));
  }
  // Below the 64KB a pipe buffers, so this cannot block on a child that has
  // not started reading.
  if (input_len > 0 && write(in_pipe[1], input, input_len) < 0) {
    printf("HTTP %s: stdin write failed: %s\n", label, strerror(errno));
  }
  close(in_pipe[1]);

  char *buf = (char *)arena_alloc(arena, ENGINEER_MAX_OUTPUT + 1);
  size_t len = 0;
  bool timed_out = false;
  time_t deadline = time(NULL) + timeout_s;
  for (;;) {
    int left = (int)(deadline - time(NULL));
    if (left <= 0) {
      timed_out = true;
      break;
    }
    struct pollfd pfd = {.fd = out_pipe[0], .events = POLLIN};
    int pr = poll(&pfd, 1, left * 1000);
    if (pr < 0 && errno == EINTR) {
      continue;
    }
    if (pr <= 0) {
      timed_out = pr == 0;
      break;
    }
    char chunk[16384];
    ssize_t got = read(out_pipe[0], chunk, sizeof(chunk));
    if (got < 0 && errno == EINTR) {
      continue;
    }
    if (got <= 0) {
      break;
    }
    // past the cap the rest is drained and dropped, so the child never
    // blocks on a full pipe
    size_t take = (size_t)got;
    if (len + take > ENGINEER_MAX_OUTPUT) {
      take = ENGINEER_MAX_OUTPUT - len;
    }
    memcpy(buf + len, chunk, take);
    len += take;
  }
  close(out_pipe[0]);
  if (timed_out) {
    kill(-pid, SIGKILL);
  }
  int wstatus = 0;
  while (waitpid(pid, &wstatus, 0) < 0 && errno == EINTR) {
  }
  assert(len <= ENGINEER_MAX_OUTPUT);
  buf[len] = '\0';
  while (len > 0 && (buf[len - 1] == '\n' || buf[len - 1] == ' ')) {
    buf[--len] = '\0';
  }

  if (timed_out) {
    return SendJSONError(client_fd, 504, "%s took over %ds", label, timeout_s);
  }
  if (len == 0 || buf[0] != '{') {
    return SendJSONError(client_fd, 500, "%s answered nothing usable", label);
  }
  *out = buf;
  *out_len = len;
  *code = WIFEXITED(wstatus) ? WEXITSTATUS(wstatus) : 1;
  return 0;
}

// The script's exit status as the HTTP one (see the top).
static int EngineerStatus(int code) {
  return code == 0   ? 200
         : code == 2 ? 400
         : code == 3 ? 409
         : code == 4 ? 404
         : code == 5 ? 413
                     : 500;
}

// EngineerExec, and the client answered with what the script printed.
static int EngineerRun(int client_fd, Arena *arena, const char *const *args,
                       const char *input, size_t input_len) {
  char *buf = NULL;
  size_t len = 0;
  int code = 0;
  int sent =
      EngineerExec(client_fd, arena, args, input, input_len, &buf, &len, &code);
  if (sent != 0) {
    return sent;
  }
  return SendJSON(client_fd, EngineerStatus(code), buf, len);
}

// A picture the session saw is ENGINEER_IMG_MAX at most; engineer.py's
// IMG_MAX is the same, and refuses a bigger one first (exit 5, a 413).
#define ENGINEER_IMG_MAX (8 * 1024 * 1024)

// The image key's shape, <session>:<offset>:<index> ([0-9a-f-]{1,8},
// digits, digits): an argv element, so checked here as well as there.
static bool EngineerImageKey(const char *k) {
  const char *p = k;
  size_t n = 0;
  while (*p && *p != ':') {
    if (!((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f') || *p == '-')) {
      return false;
    }
    p++, n++;
  }
  if (n == 0 || n > 8 || *p++ != ':') {
    return false;
  }
  for (int part = 0; part < 2; part++) {
    size_t d = 0;
    while (*p >= '0' && *p <= '9') {
      p++, d++;
    }
    if (d == 0 || d > (part == 0 ? 12u : 3u) ||
        *p != (part == 0 ? ':' : '\0')) {
      return false;
    }
    if (part == 0) {
      p++;
    }
  }
  return true;
}

// GET /engineer/<name>/image?k=<key>: a picture from their transcript
// (engineer.py's image verb writes it to its cache and names the file).
// The client names a key, never a path; the file named back must be one of
// the four types, a regular file, not a link, and under the cap. Its bytes
// never change for a key (a transcript's lines are not rewritten): cached
// for a year, privately - the engineer key guards it, no shared cache may
// keep it.
static int EngineerImage(int client_fd, Arena *arena, const char *method,
                         const char *name, const char *query,
                         const char *req_buf) {
  char k[48] = "";
  if (query == NULL || !query_get(query, "k", k, sizeof(k)) ||
      !EngineerImageKey(k)) {
    return SendJSONError(client_fd, 400,
                         "k must be an image key, <session>:<offset>:<index>");
  }
  const char *args[] = {"image", name, k, NULL};
  char *buf = NULL;
  size_t len = 0;
  int code = 0;
  int sent = EngineerExec(client_fd, arena, args, NULL, 0, &buf, &len, &code);
  if (sent != 0) {
    return sent;
  }
  if (code != 0) {
    return SendJSON(client_fd, EngineerStatus(code), buf, len);
  }
  char file[1024] = "", mime[32] = "";
  json_get_string(buf, "file", file, sizeof(file));
  json_get_string(buf, "mime", mime, sizeof(mime));
  if (file[0] != '/' || strstr(file, "/../") != NULL ||
      !(strcmp(mime, "image/png") == 0 || strcmp(mime, "image/jpeg") == 0 ||
        strcmp(mime, "image/webp") == 0 || strcmp(mime, "image/gif") == 0)) {
    return SendJSONError(client_fd, 500, "engineer.py named no picture");
  }
  int fd = open(file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  struct stat st;
  if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
    if (fd >= 0) {
      close(fd);
    }
    return SendJSONError(client_fd, 404, "the picture went from the cache");
  }
  if (st.st_size > ENGINEER_IMG_MAX) {
    close(fd);
    return SendJSONError(client_fd, 413, "the picture is over %d MB",
                         ENGINEER_IMG_MAX / (1024 * 1024));
  }
  return MediaSendOpenFile(client_fd, arena, method, req_buf, fd, &st, mime,
                           "Cache-Control: private, max-age=31536000, "
                           "immutable\r\n");
}

// "/engineer/<name>[/<verb>]" -> name and verb (verb "" when absent). The
// name is checked here as well as in the script: it becomes an argv element.
static bool EngineerSplit(const char *path, char *name, size_t name_size,
                          char *verb, size_t verb_size) {
  assert(path != NULL && name != NULL && verb != NULL);
  const char *p = path + 10; // past "/engineer/"
  size_t n = strcspn(p, "/");
  if (n == 0 || n >= name_size || n > 24 || !(p[0] >= 'a' && p[0] <= 'z')) {
    return false;
  }
  for (size_t i = 0; i < n; i++) {
    char c = p[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) {
      return false;
    }
  }
  memcpy(name, p, n);
  name[n] = '\0';
  const char *v = p[n] == '/' ? p + n + 1 : "";
  if (strlen(v) >= verb_size || strchr(v, '/') != NULL) {
    return false;
  }
  snprintf(verb, verb_size, "%s", v);
  return true;
}

// What an edit of the seat's line may pass on as argv: names ([a-z0-9-],
// a scheduled role's "crew:" prefix) and the commas joining `expect`. The
// script holds the real rules; this only keeps argv sane.
static bool EngineerQueueArg(const char *s) {
  for (const char *c = s; *c; c++) {
    if (!((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') || *c == '-' ||
          *c == ':' || *c == ',')) {
      return false;
    }
  }
  return true;
}

// POST /engineer/queue/<op>: engineer.py queue-<op>, see the top
static int EngineerQueueEdit(int client_fd, Arena *arena, const char *op,
                             bool post, const char *body) {
  bool move = strcmp(op, "move") == 0, remove = strcmp(op, "remove") == 0,
       restore = strcmp(op, "restore") == 0;
  if (!move && !remove && !restore) {
    return SendJSONError(client_fd, 404, "no such queue edit: %s", op);
  }
  if (!post) {
    return SendJSONError(client_fd, 405, "POST /engineer/queue/%s", op);
  }
  const char *json = body ? body : "";
  // a line of a few dozen names at most; longer is not a queue
  char name[40] = "", to[8] = "", expect[1024] = "";
  json_get_string(json, "name", name, sizeof(name));
  json_get_string(json, "to", to, sizeof(to));
  json_get_string(json, "expect", expect, sizeof(expect));
  if ((!restore && name[0] == '\0') || (move && to[0] == '\0')) {
    return SendJSONError(client_fd, 400,
                         move ? "body needs {\"name\", \"to\": "
                                "\"up|down|first\", \"expect\"}"
                              : "body needs {\"name\", \"expect\"}");
  }
  if (!EngineerQueueArg(name) || !EngineerQueueArg(to) ||
      !EngineerQueueArg(expect) || strchr(name, ',') != NULL) {
    return SendJSONError(client_fd, 400, "not a name in the queue");
  }
  if (move) {
    const char *args[] = {"queue-move", name, to, expect, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  if (remove) {
    const char *args[] = {"queue-remove", name, expect, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  const char *args[] = {"queue-restore", name, NULL};
  return EngineerRun(client_fd, arena, args, NULL, 0);
}

// A thread id of Number One's, NAME_RE's shape ([a-z][a-z0-9-]{0,23}): an
// argv element, so checked here; whether it exists is the script's (a 404).
static bool EngineerThreadId(const char *t) {
  size_t n = strlen(t);
  if (n == 0 || n > 24 || !(t[0] >= 'a' && t[0] <= 'z')) {
    return false;
  }
  for (const char *c = t; *c; c++) {
    if (!((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') || *c == '-')) {
      return false;
    }
  }
  return true;
}

static int HandleEngineer(int client_fd, Arena *arena, const char *method,
                          const char *path, const char *query,
                          const char *req_buf, const char *body) {
  assert(arena_valid(arena));
  assert(method != NULL && path != NULL && req_buf != NULL);
  int status = 0;
  if (!EngineerGate(client_fd, req_buf, &status)) {
    return status;
  }
  bool get = strcmp(method, "GET") == 0, post = strcmp(method, "POST") == 0;
  if (strcmp(path, "/engineer") == 0) {
    const char *args[] = {"list", NULL};
    return get ? EngineerRun(client_fd, arena, args, NULL, 0)
               : SendJSONError(client_fd, 405, "GET /engineer");
  }
  if (strcmp(path, "/engineer/queue") == 0) {
    const char *args[] = {"queue", NULL};
    return get ? EngineerRun(client_fd, arena, args, NULL, 0)
               : SendJSONError(client_fd, 405, "GET /engineer/queue");
  }
  if (strncmp(path, "/engineer/queue/", 16) == 0) {
    return EngineerQueueEdit(client_fd, arena, path + 16, post, body);
  }
  if (strcmp(path, "/engineer/rollback") == 0) {
    const char *args[] = {"rollback", NULL};
    return post ? EngineerRun(client_fd, arena, args, NULL, 0)
                : SendJSONError(client_fd, 405, "POST /engineer/rollback");
  }
  char name[32], verb[16];
  if (!EngineerSplit(path, name, sizeof(name), verb, sizeof(verb))) {
    return SendJSONError(client_fd, 404,
                         "not an engineer route (names are [a-z][a-z0-9-]*)");
  }
  if (verb[0] == '\0') {
    if (!get) {
      return SendJSONError(client_fd, 405, "GET /engineer/<name>");
    }
    // `before`: the page of the transcript ending at that byte, which is
    // how a client walks back to the start of a long conversation
    char off[24] = "-1", before[24] = "-1", past[48] = "-", thread[32] = "-";
    if (query != NULL) {
      query_get(query, "off", off, sizeof(off));
      query_get(query, "before", before, sizeof(before));
      query_get(query, "past", past, sizeof(past));
      query_get(query, "thread", thread, sizeof(thread));
    }
    if (thread[0] == '\0') {
      strcpy(thread, "-");
    } else if (strcmp(thread, "-") != 0 && !EngineerThreadId(thread)) {
      return SendJSONError(client_fd, 400,
                           "thread must be [a-z][a-z0-9-]{0,23}");
    }
    // a session id (hex and dashes): an argv element, and the script takes
    // only one of the engineer's own earlier ones
    for (const char *c = past; *c; c++) {
      if (!((*c >= '0' && *c <= '9') || (*c >= 'a' && *c <= 'f') ||
            *c == '-')) {
        return SendJSONError(client_fd, 400, "past must be a session id");
      }
    }
    if (past[0] == '\0') {
      strcpy(past, "-");
    }
    // digits and a sign only: they are argv elements
    const char *nums[] = {off, before};
    for (int i = 0; i < 2; i++) {
      for (const char *c = nums[i]; *c; c++) {
        if (!((*c >= '0' && *c <= '9') || (c == nums[i] && *c == '-'))) {
          return SendJSONError(client_fd, 400,
                               "off and before must be numbers");
        }
      }
    }
    const char *args[] = {"poll", name, off, before, past, thread, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  // not an engineer's: <name> is a scheduled role, which the script checks
  // names a file in crew/ (the slug is all this passes on)
  if (strcmp(verb, "image") == 0) {
    return get || strcmp(method, "HEAD") == 0
               ? EngineerImage(client_fd, arena, method, name, query, req_buf)
               : SendJSONError(client_fd, 405,
                               "GET /engineer/<name>/image?k=<key>");
  }
  if (strcmp(verb, "brief") == 0) {
    const char *args[] = {"brief", name, NULL};
    return get ? EngineerRun(client_fd, arena, args, NULL, 0)
               : SendJSONError(client_fd, 405, "GET /engineer/<role>/brief");
  }
  if (!post) {
    return SendJSONError(client_fd, 405, "POST /engineer/<name>/%s", verb);
  }
  const char *json = body ? body : "";
  if (strcmp(verb, "start") == 0) {
    size_t n = strlen(json);
    if (n > ENGINEER_MAX_INPUT) {
      return SendJSONError(client_fd, 413, "persona too long");
    }
    const char *args[] = {"start", name, NULL};
    return EngineerRun(client_fd, arena, args, json, n);
  }
  if (strcmp(verb, "say") == 0) {
    ChatAttachment *files = NULL;
    int file_count = 0;
    int bad = 0;
    if (!ChatAttachmentsParse(client_fd, arena, json, &files, &file_count,
                              &bad)) {
      return bad;
    }
    char *msg = NULL;
    if (!json_get_string_arena(arena, json, "message", &msg) || msg == NULL) {
      msg = "";
    }
    if (msg[0] == '\0' && file_count == 0) {
      return SendJSONError(client_fd, 400, "body needs {\"message\": \"...\"}");
    }
    size_t n = strlen(msg);
    if (n > ENGINEER_MAX_INPUT) {
      return SendJSONError(client_fd, 413, "message over %d bytes",
                           ENGINEER_MAX_INPUT);
    }
    // the room (a thread, Number One's old word): an argv element after
    // --thread, or nothing
    char thread[32] = "";
    if (json_get_string(json, "thread", thread, sizeof(thread)) &&
        thread[0] != '\0' && !EngineerThreadId(thread)) {
      return SendJSONError(client_fd, 400,
                           "thread must be [a-z][a-z0-9-]{0,23}");
    }
    const char *flag = thread[0] ? "--thread" : NULL;
    if (file_count == 0) {
      const char *args[] = {"say", name, flag, thread, NULL};
      return EngineerRun(client_fd, arena, args, msg, n);
    }
    // With files the script is handed JSON (say --json): the message and
    // the files as checked here - the path, the file's own size, a clean
    // name - for it to write each one's line (engineer.py, cmd_say)
    JSONBuf in;
    jsonbuf_init(&in, arena);
    jsonbuf_append(&in, "{\"message\":");
    jsonbuf_append_json_string(&in, msg);
    jsonbuf_append(&in, ",\"attachments\":[");
    for (int i = 0; i < file_count; i++) {
      jsonbuf_append(&in, i ? ",{\"path\":" : "{\"path\":");
      jsonbuf_append_json_string(&in, files[i].path);
      jsonbuf_append(&in, ",\"name\":");
      jsonbuf_append_json_string(&in, files[i].name);
      jsonbuf_append(&in, ",\"mime\":");
      jsonbuf_append_json_string(&in, files[i].mime);
      jsonbuf_appendf(&in, ",\"bytes\":%lld}", files[i].bytes);
    }
    jsonbuf_append(&in, "]}");
    if (in.overflow || in.len > ENGINEER_MAX_INPUT) {
      return SendJSONError(client_fd, 413, "message and files over %d bytes",
                           ENGINEER_MAX_INPUT);
    }
    const char *args[] = {"say", name, "--json", flag, thread, NULL};
    return EngineerRun(client_fd, arena, args, in.data, in.len);
  }
  // the chips' thread labels: the body is handed to the script as it
  // is (stdin, never argv), which checks every field
  if (strcmp(verb, "thread") == 0) {
    size_t n = strlen(json);
    if (n > ENGINEER_MAX_INPUT) {
      return SendJSONError(client_fd, 413, "body over %d bytes",
                           ENGINEER_MAX_INPUT);
    }
    const char *args[] = {"thread-req", name, NULL};
    return EngineerRun(client_fd, arena, args, json, n);
  }
  if (strcmp(verb, "key") == 0) {
    char key[16];
    if (!json_get_string(json, "key", key, sizeof(key))) {
      return SendJSONError(client_fd, 400, "body needs {\"key\": \"1\"}");
    }
    // the script holds the whitelist; this only keeps argv sane
    for (const char *c = key; *c; c++) {
      if (!((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') ||
            *c == '+')) {
        return SendJSONError(client_fd, 400, "not a key: %s", key);
      }
    }
    const char *args[] = {"key", name, key, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  if (strcmp(verb, "model") == 0) {
    char model[16];
    // the chat's allowlist (lcars_chat.h); "" would be its default, which
    // is not a choice here
    if (!json_get_string(json, "model", model, sizeof(model)) ||
        model[0] == '\0' || ChatModelFor(model) == NULL) {
      return SendJSONError(
          client_fd, 400,
          "body needs {\"model\": \"sonnet|haiku|opus|fable\"}");
    }
    const char *args[] = {"model", name, ChatModelFor(model), NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  if (strcmp(verb, "job-cancel") == 0) {
    // the job id is <name>-<yyyymmdd-hhmmss>: an argv element, so only
    // that alphabet; which job it is, and whose, is the script's
    char id[64] = "";
    json_get_string(json, "id", id, sizeof(id));
    for (const char *c = id; *c; c++) {
      if (!((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') ||
            *c == '-')) {
        return SendJSONError(client_fd, 400, "not a job id");
      }
    }
    const char *args[] = {"job-cancel", name, id, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  // dismiss/recall: out of the console's list and back; nothing is removed
  // refresh: the script refuses any engineer but Number One
  if (strcmp(verb, "stop") == 0 || strcmp(verb, "deploy") == 0 ||
      strcmp(verb, "dismiss") == 0 || strcmp(verb, "recall") == 0 ||
      strcmp(verb, "refresh") == 0) {
    const char *args[] = {verb, name, NULL};
    return EngineerRun(client_fd, arena, args, NULL, 0);
  }
  return SendJSONError(client_fd, 404, "no such engineer verb: %s", verb);
}

#endif // LCARS_ENGINEER_IMPLEMENTATION
#endif // LCARS_ENGINEER_H
