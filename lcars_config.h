#ifndef LCARS_CONFIG_H
#define LCARS_CONFIG_H

// The server's start-up configuration beyond its flags: the version it was
// built as, the data directory's lcars.env, and `lcars init`, which makes a
// data directory to start from. Step 2 of docs/design/open-source-build.md.
//
// lcars.env is KEY=value lines with the same names as the environment
// (LCARS_AUTH_USER, DEEPGRAM_API_KEY, ...), read once in main before
// anything reads a variable or starts a thread, and put into the process's
// environment with setenv - so every getenv in the server, and every child
// it spawns (claude, ffmpeg, engineer.py), sees the file's values exactly as
// it sees the unit's ~/.env today. The real environment wins: a key already
// set is left as it is. The file is optional, and the live checkout has
// none, so the live server reads nothing and runs on ~/.env as before.
//
// Where it is looked for: --data DIR, else $LCARS_DATA_DIR, else the working
// directory - the directory the journal defaults into (lcars_db.h), so a
// data directory holds both. LCARS_DATA_DIR inside the file is ignored (the
// file cannot move the directory it was found in); LCARS_DB_PATH there is
// honoured, being read before the journal's path is resolved.
//
// The format, deliberately a subset of what both bash's `source` and
// systemd's EnvironmentFile accept, so one file can serve all three:
//   # a comment, and blank lines
//   KEY=value
//   export KEY=value
//   KEY="value with spaces"   or 'value' - one pair of matching quotes is
//                             stripped; nothing inside them is unescaped
// No inline comments (`KEY=a # b` is the value "a # b"), no ${expansion}.
// A line that is none of these is skipped with a warning naming its number,
// never its text (it may hold a secret).

#include <stdbool.h>
#include <stddef.h>

// The version, from CHANGELOG.md's top entry: the Makefile passes it as a
// bare pp-number (-DLCARS_VERSION=0.260.1) and it is made a string here, so
// no shell quoting has to survive `make -n` into the tests' scratch builds.
#define LCARS_STR_(x) #x
#define LCARS_STR(x) LCARS_STR_(x)
#ifdef LCARS_VERSION
#define LCARS_VERSION_STRING LCARS_STR(LCARS_VERSION)
#else
#define LCARS_VERSION_STRING "unknown"
#endif

#define LCARS_ENV_FILE "lcars.env"

// The data directory: --data DIR, else $LCARS_DATA_DIR, else "." - where
// lcars.env is looked for, and (one binary) bin/lcars-cli made. The journal
// has its own, longer order (SetLcarsDBPath), which --db and LCARS_DB_PATH
// can take out of this directory.
static const char *LcarsDataDir(const char *data_flag);

// Reads <dir>/lcars.env, dir being data_flag, else $LCARS_DATA_DIR, else
// ".", and setenv()s each key not already in the environment. Logs one
// "Config:" line saying which file was read and how many keys it set, or
// that there was none. False only if the file exists and cannot be read.
static bool LoadEnvFile(const char *data_flag);

// `lcars init DIR [--port N] [--user U]`: argv[0] is "init". Returns the
// process's exit code.
static int RunInit(int argc, char **argv);

#ifdef LCARS_IMPLEMENTATION

#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>

static bool EnvKeyIsValid(const char *k, size_t n) {
  assert(k != NULL);
  if (n == 0 || !(isalpha((unsigned char)k[0]) || k[0] == '_')) {
    return false;
  }
  for (size_t i = 1; i < n; i++) {
    if (!(isalnum((unsigned char)k[i]) || k[i] == '_')) {
      return false;
    }
  }
  return true;
}

// One line, cut in place into key and value. 1 a pair, 0 a comment or
// blank, -1 malformed.
static int ParseEnvLine(char *line, char **key, char **value) {
  assert(line != NULL && key != NULL && value != NULL);
  size_t n = strlen(line);
  while (n > 0 && isspace((unsigned char)line[n - 1])) {
    line[--n] = '\0'; // the newline, a \r from a file written on Windows
  }
  char *p = line;
  while (*p == ' ' || *p == '\t') {
    p++;
  }
  if (*p == '\0' || *p == '#') {
    return 0;
  }
  if (strncmp(p, "export", 6) == 0 && (p[6] == ' ' || p[6] == '\t')) {
    p += 6;
    while (*p == ' ' || *p == '\t') {
      p++;
    }
  }
  char *eq = strchr(p, '=');
  if (eq == NULL || !EnvKeyIsValid(p, (size_t)(eq - p))) {
    return -1;
  }
  *eq = '\0';
  char *v = eq + 1;
  size_t vn = strlen(v);
  if (vn >= 2 && (v[0] == '"' || v[0] == '\'') && v[vn - 1] == v[0]) {
    v[vn - 1] = '\0';
    v++;
  }
  *key = p;
  *value = v;
  return 1;
}

static const char *LcarsDataDir(const char *data_flag) {
  const char *env_data = getenv("LCARS_DATA_DIR");
  return (data_flag && data_flag[0]) ? data_flag
         : (env_data && env_data[0]) ? env_data
                                     : ".";
}

static bool LoadEnvFile(const char *data_flag) {
  const char *dir = LcarsDataDir(data_flag);
  char path[PATH_MAX];
  int pn = snprintf(path, sizeof(path), "%s/%s", dir, LCARS_ENV_FILE);
  if (pn <= 0 || (size_t)pn >= sizeof(path)) {
    fprintf(stderr, "Config: the path of %s in '%s' is too long\n",
            LCARS_ENV_FILE, dir);
    return false;
  }
  char abs[PATH_MAX];
  FILE *f = fopen(path, "r");
  if (f == NULL) {
    if (errno == ENOENT) {
      const char *shown = realpath(dir, abs) ? abs : dir;
      printf("Config: no %s in %s (the environment only)\n", LCARS_ENV_FILE,
             shown);
      fflush(stdout);
      return true;
    }
    fprintf(stderr, "Config: cannot read %s: %s\n", path, strerror(errno));
    return false;
  }
  const char *shown = realpath(path, abs) ? abs : path;
  struct stat st;
  // fopen opens a directory for reading without complaint, and getline then
  // reads nothing: a settings file that is silently empty is the one thing
  // this must not be.
  if (fstat(fileno(f), &st) != 0 || !S_ISREG(st.st_mode)) {
    fprintf(stderr, "Config: cannot read %s: not a regular file\n", shown);
    fclose(f);
    return false;
  }
  if ((st.st_mode & 077) != 0) {
    printf("Config: warning: %s is readable by others (mode %03o); it "
           "holds the password - chmod 600 it\n",
           shown, (unsigned)(st.st_mode & 0777));
  }

  int set = 0, kept = 0, skipped = 0, lineno = 0;
  char *line = NULL;
  size_t cap = 0;
  while (getline(&line, &cap, f) != -1) {
    lineno++;
    char *key = NULL, *value = NULL;
    int r = ParseEnvLine(line, &key, &value);
    if (r == 0) {
      continue;
    }
    if (r < 0) {
      printf("Config: %s line %d is not KEY=value; skipped\n", shown, lineno);
      skipped++;
      continue;
    }
    if (strcmp(key, "LCARS_DATA_DIR") == 0) {
      printf("Config: %s line %d: LCARS_DATA_DIR is ignored in the file "
             "it names\n",
             shown, lineno);
      skipped++;
      continue;
    }
    if (getenv(key) != NULL) {
      kept++; // the real environment wins
      continue;
    }
    if (setenv(key, value, 0) != 0) {
      fprintf(stderr, "Config: setenv %s failed: %s\n", key, strerror(errno));
      free(line);
      fclose(f);
      return false;
    }
    assert(getenv(key) != NULL);
    set++;
  }
  bool failed = ferror(f) != 0;
  free(line);
  fclose(f);
  if (failed) {
    fprintf(stderr, "Config: reading %s failed after line %d\n", shown, lineno);
    return false;
  }
  printf("Config: read %s: %d set, %d already in the environment, %d "
         "skipped\n",
         shown, set, kept, skipped);
  fflush(stdout);
  return true;
}

// --- lcars init ------------------------------------------------------------

// mkdir -p, each new directory 0700: a data directory holds the journal and
// the password, nobody else's business.
static bool InitMkdirs(const char *path, bool *made) {
  assert(path != NULL && made != NULL);
  char buf[PATH_MAX];
  int n = snprintf(buf, sizeof(buf), "%s", path);
  if (n <= 0 || (size_t)n >= sizeof(buf)) {
    return false;
  }
  *made = false;
  for (char *p = buf + 1;; p++) {
    if (*p == '/' || *p == '\0') {
      char c = *p;
      *p = '\0';
      if (mkdir(buf, 0700) == 0) {
        *made = true;
      } else if (errno != EEXIST) {
        fprintf(stderr, "lcars init: cannot make %s: %s\n", buf,
                strerror(errno));
        return false;
      }
      *p = c;
      if (c == '\0') {
        break;
      }
    }
  }
  struct stat st;
  if (stat(path, &st) != 0 || !S_ISDIR(st.st_mode)) {
    fprintf(stderr, "lcars init: %s is not a directory\n", path);
    return false;
  }
  return true;
}

// 18 random bytes as 24 characters of URL-safe base64: 144 bits, and no
// character a shell, an env file or a Basic-auth header has to quote.
static bool InitPassword(char out[25]) {
  static const char abc[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  unsigned char raw[18];
  size_t got = 0;
  while (got < sizeof(raw)) {
    ssize_t r = getrandom(raw + got, sizeof(raw) - got, 0);
    if (r < 0) {
      if (errno == EINTR) {
        continue;
      }
      return false;
    }
    got += (size_t)r;
  }
  for (int i = 0; i < 6; i++) {
    unsigned v = ((unsigned)raw[3 * i] << 16) |
                 ((unsigned)raw[3 * i + 1] << 8) | raw[3 * i + 2];
    out[4 * i] = abc[(v >> 18) & 63];
    out[4 * i + 1] = abc[(v >> 12) & 63];
    out[4 * i + 2] = abc[(v >> 6) & 63];
    out[4 * i + 3] = abc[v & 63];
  }
  out[24] = '\0';
  return true;
}

// A user name for Basic auth and the env file: no ':' (the header's
// separator), nothing to quote.
static bool InitUserIsValid(const char *u) {
  size_t n = strlen(u);
  if (n == 0 || n > 64) {
    return false;
  }
  for (size_t i = 0; i < n; i++) {
    char c = u[i];
    if (!(isalnum((unsigned char)c) || c == '.' || c == '_' || c == '-')) {
      return false;
    }
  }
  return true;
}

// The template: the Start keys set, every feature's commented out with what
// it is for (docs/design/open-source.md, section 2b).
static void InitWriteEnv(FILE *f, const char *dir_abs, int port,
                         const char *user, const char *pass) {
  fprintf(f,
          "# LCARS settings, read by `lcars --data %s` at start.\n"
          "# KEY=value, the same names as the environment; a variable set "
          "in the\n"
          "# real environment wins over this file. No inline comments.\n"
          "\n"
          "# --- Start ---\n"
          "# The login (HTTP Basic auth) the console asks for.\n"
          "LCARS_AUTH_USER=%s\n"
          "LCARS_AUTH_PASS=%s\n"
          "# The port, and the address to listen on: 127.0.0.1 is this "
          "machine only;\n"
          "# put a TLS proxy (Tailscale serve, Caddy, nginx) in front for "
          "anything else.\n"
          "LCARS_PORT=%d\n"
          "LCARS_BIND=127.0.0.1\n"
          "# Photos, tapes and files (a NAS mount works: "
          "/mnt/<nas>/lcars).\n"
          "LCARS_MEDIA_ROOT=%s/media\n"
          "\n"
          "# --- Features: uncomment what you use ---\n"
          "# The computer and the navigator run the `claude` CLI, installed "
          "and logged in\n"
          "# (not an API key). Where it is, if not on PATH; 0 turns the chat "
          "off.\n"
          "# LCARS_CLAUDE_BIN=/usr/local/bin/claude\n"
          "# LCARS_CHAT=0\n"
          "# Media cuts and posters need ffmpeg; where it is, if not on "
          "PATH.\n"
          "# LCARS_FFMPEG_BIN=/usr/bin/ffmpeg\n"
          "# Transcription, live voice and spoken replies (Deepgram).\n"
          "# DEEPGRAM_API_KEY=\n"
          "# Spoken replies: deepgram (the default with a key), elevenlabs, "
          "or off.\n"
          "# LCARS_TTS=off\n"
          "# ELEVENLABS_API_KEY=\n"
          "# Maps and routing in the course view (Mapy.com); without it, "
          "OpenStreetMap tiles.\n"
          "# LCARS_MAPY_KEY=\n"
          "# Semantic search: an OpenAI-compatible embeddings endpoint "
          "(llama.cpp works);\n"
          "# LCARS_EMBED=0 turns it off and search stays lexical.\n"
          "# LCARS_EMBED=0\n"
          "# LCARS_EMBED_URL=http://127.0.0.1:8091/v1/embeddings\n"
          "# LCARS_EMBED_MODEL=\n"
          "# LCARS_EMBED_KEY=\n"
          "# Strava: an API application's id and secret, then `lcars-cli "
          "strava auth`.\n"
          "# LCARS_STRAVA_CLIENT_ID=\n"
          "# LCARS_STRAVA_CLIENT_SECRET=\n"
          "# The Logseq bridge (lcars-cli logseq): its HTTP API's address "
          "and token.\n"
          "# LOGSEQ_URL=http://127.0.0.1:12315\n"
          "# LOGSEQ_TOKEN=\n"
          "# The zone dates without one are read in (CalDAV), e.g. "
          "Europe/London.\n"
          "# LCARS_TZ=\n"
          "# The engineers (scripts/engineer.py, python3, git, gh, claude): "
          "1 turns their\n"
          "# routes on; the key is what their calls in carry.\n"
          "# LCARS_ENGINEER=1\n"
          "# LCARS_ENGINEER_KEY=\n"
          "# The limited logins: Number One, the crew, the steward "
          "(scripts/crew.py).\n"
          "# LCARS_NO1_USER=\n"
          "# LCARS_NO1_PASS=\n"
          "# LCARS_CREW_USER=\n"
          "# LCARS_CREW_PASS=\n"
          "# LCARS_STEWARD_USER=\n"
          "# LCARS_STEWARD_PASS=\n"
          "# Where the media cache lives, and its size in MB (0 turns it "
          "off).\n"
          "# LCARS_MEDIA_CACHE=\n"
          "# LCARS_MEDIA_CACHE_MB=\n",
          dir_abs, user, pass, port, dir_abs);
}

static int RunInit(int argc, char **argv) {
  assert(argc >= 1 && strcmp(argv[0], "init") == 0);
  const char *dir = NULL;
  int port = 8080;
  const char *user = getenv("USER");
  if (user == NULL || !InitUserIsValid(user)) {
    user = "captain";
  }
  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
      port = atoi(argv[++i]);
      if (port <= 0 || port > 65535) {
        fprintf(stderr, "lcars init: invalid port '%s' (1-65535)\n", argv[i]);
        return 2;
      }
    } else if (strcmp(argv[i], "--user") == 0 && i + 1 < argc) {
      user = argv[++i];
      if (!InitUserIsValid(user)) {
        fprintf(stderr,
                "lcars init: user '%s': letters, digits, '.', '_' and '-' "
                "only\n",
                user);
        return 2;
      }
    } else if (argv[i][0] != '-' && dir == NULL) {
      dir = argv[i];
    } else {
      fprintf(stderr, "Usage: lcars init DIR [--port N] [--user U]\n");
      return 2;
    }
  }
  if (dir == NULL || dir[0] == '\0') {
    fprintf(stderr, "Usage: lcars init DIR [--port N] [--user U]\n");
    return 2;
  }

  bool made = false;
  if (!InitMkdirs(dir, &made)) {
    return 1;
  }
  char dir_abs[PATH_MAX];
  if (realpath(dir, dir_abs) == NULL) {
    fprintf(stderr, "lcars init: %s: %s\n", dir, strerror(errno));
    return 1;
  }
  printf("%s %s\n", made ? "made     " : "left alone", dir_abs);

  char path[PATH_MAX + 32];
  // The media root lcars.env names is <dir>/media, and the server stores
  // under its media/ (MEDIA_SUBDIR), which it never makes itself - an
  // absent one reads as an unmounted NAS (MediaCheckMounted) - so init
  // makes both, or media would start off.
  snprintf(path, sizeof(path), "%s/media/media", dir_abs);
  bool media_made = false;
  if (!InitMkdirs(path, &media_made)) {
    return 1;
  }
  printf("%s %s\n", media_made ? "made     " : "left alone", path);

  // O_EXCL: an existing lcars.env - its password, the user's own edits - is
  // never written over, not even truncated by a race with a second init.
  snprintf(path, sizeof(path), "%s/%s", dir_abs, LCARS_ENV_FILE);
  char pass[25] = {0};
  bool env_made = false;
  int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  if (fd >= 0) {
    if (!InitPassword(pass)) {
      fprintf(stderr, "lcars init: getrandom failed: %s\n", strerror(errno));
      close(fd);
      unlink(path);
      return 1;
    }
    FILE *f = fdopen(fd, "w");
    if (f == NULL) {
      close(fd);
      unlink(path);
      return 1;
    }
    InitWriteEnv(f, dir_abs, port, user, pass);
    if (fclose(f) != 0) {
      fprintf(stderr, "lcars init: writing %s failed\n", path);
      unlink(path);
      return 1;
    }
    env_made = true;
    printf("made      %s (mode 600)\n", path);
  } else if (errno == EEXIST) {
    printf("left alone %s (its login and port stand)\n", path);
  } else {
    fprintf(stderr, "lcars init: cannot write %s: %s\n", path, strerror(errno));
    return 1;
  }

  // The journal, through the same SetLcarsDBPath and InitDB the server
  // uses, so a made one is exactly what a first start would make. One that
  // exists is not opened at all: init only ever adds.
  char err[256];
  if (!SetLcarsDBPath(NULL, dir_abs, err, sizeof(err))) {
    fprintf(stderr, "lcars init: %s\n", err);
    return 1;
  }
  struct stat st;
  if (stat(LcarsDBPath(), &st) == 0) {
    printf("left alone %s\n", LcarsDBPath());
  } else {
    sqlite3 *db = NULL;
    if (sqlite3_open(LcarsDBPath(), &db) != SQLITE_OK) {
      fprintf(stderr, "lcars init: cannot make %s: %s\n", LcarsDBPath(),
              sqlite3_errmsg(db));
      sqlite3_close(db);
      return 1;
    }
    InitDB(db);
    sqlite3_close(db);
    printf("made      %s\n", LcarsDBPath());
  }

  printf("\nStart it:  lcars --data %s\n", dir_abs);
  if (env_made) {
    printf("Open:      http://127.0.0.1:%d/ui/\n", port);
    printf("Login:     %s / %s\n", user, pass);
  } else {
    printf("Open:      http://127.0.0.1:<LCARS_PORT>/ui/ - the login is "
           "LCARS_AUTH_USER/LCARS_AUTH_PASS in %s/%s\n",
           dir_abs, LCARS_ENV_FILE);
  }
  return 0;
}

#endif // LCARS_IMPLEMENTATION

#endif // LCARS_CONFIG_H
