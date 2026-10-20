// Before the first system header, or features.h has already decided: the
// server wants MSG_NOSIGNAL, strcasestr, timegm and the like, which -std=c11
// hides.
#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

// The server: one translation unit, every module a single header with its
// body under an implementation define. The raylib desktop app that used to
// share this file was removed in 0.175.0; see ARCHITECTURE.md to bring it
// back.
#include "lcars_base.h"
#define LCARS_IMPLEMENTATION
#include "lcars_db.h"
#include "lcars_config.h"
#define LCARS_HTTP_IMPLEMENTATION
#include "lcars_http.h"

// Names the journal the server is about to serve, on stdout (the unit's
// journal), so that a restart shows which file it opened: the absolute path,
// whether it was just made, and how many live entries it holds. The one place
// a wrong path shows before the phone syncs against it - a new journal has
// exactly the seed's one row (see LcarsDBPath).
static void LogDBOpened(sqlite3 *db, bool created) {
  assert(db != NULL);
  char abs[PATH_MAX];
  const char *shown = realpath(LcarsDBPath(), abs) ? abs : LcarsDBPath();
  long long live = -1;
  sqlite3_stmt *stmt = NULL;
  // The same count as /metrics' lcars_entries_total summed over the kinds,
  // which is what vps-rebuild.sh compares across a restart.
  if (sqlite3_prepare_v2(db,
                         "SELECT COUNT(*) FROM entries WHERE deleted IS NULL "
                         "OR deleted = 0;",
                         -1, &stmt, NULL) == SQLITE_OK &&
      sqlite3_step(stmt) == SQLITE_ROW) {
    live = sqlite3_column_int64(stmt, 0);
  }
  sqlite3_finalize(stmt);
  printf("Database: %s (%s, %lld entries)\n", shown,
         created ? "NEW: created just now" : "existing", live);
  fflush(stdout);
}

// Creates the schema (and migrates an older lcars.db) on a handle of its
// own, closed again before the first connection thread opens one.
static void InitDBMinimal(void) {
  struct stat st;
  bool created = stat(LcarsDBPath(), &st) != 0;
  sqlite3 *db = NULL;
  if (sqlite3_open(LcarsDBPath(), &db) != SQLITE_OK) {
    fprintf(stderr, "Can't open database '%s': %s\n", LcarsDBPath(),
            sqlite3_errmsg(db));
    exit(1);
  }
  InitDB(db);
  LogDBOpened(db, created);
  sqlite3_close(db);
}

#ifdef LCARS_ONE_BINARY
// lcars_cli.c's main, renamed by the Makefile's lcars-one line
// (-Dmain=LcarsCliMain on that translation unit only): the CLI is linked in
// whole, its own argument parsing and all, so `lcars cli ARGS` is exactly
// `lcars-cli ARGS`.
int LcarsCliMain(int argc, char **argv);

// The chat runs `lcars-cli` from LCARS_CLI_DIR (lcars_chat.h, ChatCliDir),
// a directory put first on claude's PATH. A one-binary install has no
// lcars-cli file, so the server makes one: <data dir>/bin/lcars-cli, a
// symlink to this very executable, which then runs as the CLI by its name
// (main, below). Replaced by rename when it points elsewhere (a moved
// binary), so the chat never finds it half-made; a real file of that name -
// someone's own build - is left alone. LCARS_CLI_DIR set in the environment
// or lcars.env wins, and nothing is made. Not fatal: the chat's lcars-cli is
// one feature, and its absence is logged.
static void MakeCliLink(const char *data_flag) {
  const char *have = getenv("LCARS_CLI_DIR");
  if (have != NULL && have[0] != '\0') {
    printf("CLI: LCARS_CLI_DIR=%s (as set)\n", have);
    return;
  }
  char exe[PATH_MAX];
  ssize_t n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
  char dir[PATH_MAX];
  if (n <= 0 || realpath(LcarsDataDir(data_flag), dir) == NULL) {
    printf("CLI: cannot find this binary or the data directory; the chat "
           "has no lcars-cli\n");
    return;
  }
  exe[n] = '\0';
  char bin[PATH_MAX + 8], link[PATH_MAX + 32], tmp[PATH_MAX + 48];
  snprintf(bin, sizeof(bin), "%s/bin", dir);
  snprintf(link, sizeof(link), "%s/lcars-cli", bin);
  snprintf(tmp, sizeof(tmp), "%s/.lcars-cli.%ld", bin, (long)getpid());
  if (mkdir(bin, 0700) != 0 && errno != EEXIST) {
    printf("CLI: cannot make %s: %s; the chat has no lcars-cli\n", bin,
           strerror(errno));
    return;
  }
  struct stat st;
  if (lstat(link, &st) == 0 && !S_ISLNK(st.st_mode)) {
    printf("CLI: %s is a file of its own; left alone\n", link);
  } else {
    char cur[PATH_MAX];
    ssize_t c = readlink(link, cur, sizeof(cur) - 1);
    bool same = c == n && memcmp(cur, exe, (size_t)n) == 0;
    if (!same && (symlink(exe, tmp) != 0 || rename(tmp, link) != 0)) {
      printf("CLI: cannot link %s: %s; the chat has no lcars-cli\n", link,
             strerror(errno));
      unlink(tmp);
      return;
    }
    printf("CLI: %s -> %s\n", link, exe);
  }
  setenv("LCARS_CLI_DIR", bin, 1);
  assert(getenv("LCARS_CLI_DIR") != NULL);
}
#endif

static const char *Basename(const char *path) {
  assert(path != NULL);
  const char *slash = strrchr(path, '/');
  return slash ? slash + 1 : path;
}

// Started as the CLI: by the name lcars-cli (argv[0]'s basename - the
// symlink above, or one a user makes), or as `lcars cli ARGS`. In a build
// without the CLI linked in (lcars-release, what the VPS runs) both say so.
static bool WantsCli(int argc, char **argv) {
  return strcmp(Basename(argv[0]), "lcars-cli") == 0 ||
         (argc >= 2 && strcmp(argv[1], "cli") == 0);
}

static int RunCli(int argc, char **argv) {
#ifdef LCARS_ONE_BINARY
  if (strcmp(Basename(argv[0]), "lcars-cli") == 0) {
    return LcarsCliMain(argc, argv);
  }
  // `lcars cli ...`: the CLI sees "cli" as its argv[0], which it never reads.
  return LcarsCliMain(argc - 1, argv + 1);
#else
  (void)argc;
  (void)argv;
  fprintf(stderr, "lcars: this build has no CLI in it (make lcars-one); "
                  "use the separate lcars-cli\n");
  return 2;
#endif
}

int main(int argc, char **argv) {
  assert(argc >= 1 && argv[0] != NULL);
  if (WantsCli(argc, argv)) {
    return RunCli(argc, argv);
  }
  // The subcommands, before the server's own options; anything else -
  // nothing, or a first argument starting with '-' (the live unit's `-s`) -
  // is the server, as it always was.
  if (argc >= 2 && strcmp(argv[1], "init") == 0) {
    return RunInit(argc - 1, argv + 1);
  }
  if (argc >= 2 &&
      (strcmp(argv[1], "version") == 0 || strcmp(argv[1], "--version") == 0)) {
    printf("lcars %s\n", LCARS_VERSION_STRING);
    return 0;
  }
  int port = 0; // 0: not given; $LCARS_PORT, else 8080, once lcars.env is in
  char *auth_user = NULL;
  char *auth_pass = NULL;
  const char *db_flag = NULL;
  const char *data_flag = NULL;
  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--http-only") == 0 || strcmp(argv[i], "-s") == 0 ||
        strcmp(argv[i], "--server") == 0) {
      // What the desktop app's server mode was called. The systemd unit and
      // every test still pass it; it is the only mode there is now.
    } else if ((strcmp(argv[i], "--port") == 0 || strcmp(argv[i], "-p") == 0) &&
               i + 1 < argc) {
      // Validated here, at the boundary, rather than asserted deeper in:
      // a bad command line is user error, and the server functions assert
      // a usable port on the strength of this check.
      port = atoi(argv[++i]);
      if (port <= 0 || port > 65535) {
        fprintf(stderr, "Invalid port '%s' (expected 1-65535)\n", argv[i]);
        return 1;
      }
    } else if ((strcmp(argv[i], "--user") == 0 || strcmp(argv[i], "-u") == 0) &&
               i + 1 < argc) {
      auth_user = argv[++i];
    } else if ((strcmp(argv[i], "--password") == 0 ||
                strcmp(argv[i], "--pass") == 0) &&
               i + 1 < argc) {
      auth_pass = argv[++i];
    } else if (strcmp(argv[i], "--db") == 0 && i + 1 < argc) {
      db_flag = argv[++i];
    } else if (strcmp(argv[i], "--data") == 0 && i + 1 < argc) {
      data_flag = argv[++i];
    } else if (strcmp(argv[i], "--version") == 0) {
      printf("lcars %s\n", LCARS_VERSION_STRING);
      return 0;
    } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
      printf("Usage: %s [options]\n"
             "       %s init DIR [--port N] [--user U]   make a data "
             "directory\n"
             "       %s cli ARGS   the CLI, as lcars-cli ARGS (lcars-one "
             "builds)\n"
             "       %s version\n",
             argv[0], argv[0], argv[0], argv[0]);
      printf("Serves a journal (lcars.db in the working directory unless "
             "told otherwise) over HTTP.\n");
      printf("Options:\n");
      printf("  --db <file>               The journal's sqlite file "
             "(env LCARS_DB_PATH)\n");
      printf("  --data <dir>              A data directory: <dir>/lcars.db "
             "(env LCARS_DATA_DIR);\n"
             "                            must exist, never chdir'd into\n");
      printf("  --port, -p <port>         HTTP port (env LCARS_PORT, "
             "default: 8080)\n");
      printf("  --user, -u <username>     Basic Auth username\n");
      printf("  --password, --pass <password> Basic Auth password\n");
      printf("  --http-only, -s, --server Accepted and ignored (the server "
             "is all there is)\n");
      printf("  --help, -h                Show this help message\n");
      printf("Environment: LCARS_BIND=<ipv4> listens on that address only "
             "(default: all)\n");
      printf("Settings: <data dir>/lcars.env, KEY=value lines read at "
             "start; the real\nenvironment wins over it.\n");
      return 0;
    }
  }

  printf("LCARS %s\n", LCARS_VERSION_STRING);
  // lcars.env first, before anything reads a variable (the journal's path
  // included: the file may set LCARS_DB_PATH) and before any thread exists:
  // setenv is not safe beside another thread's getenv.
  if (!LoadEnvFile(data_flag)) {
    return 2;
  }
  if (port == 0) {
    const char *env_port = getenv("LCARS_PORT");
    port = 8080;
    if (env_port && env_port[0]) {
      port = atoi(env_port);
      if (port <= 0 || port > 65535) {
        fprintf(stderr, "Invalid LCARS_PORT '%s' (expected 1-65535)\n",
                env_port);
        return 1;
      }
    }
  }
  assert(port > 0 && port <= 65535);

#ifdef LCARS_ONE_BINARY
  MakeCliLink(data_flag); // a setenv, so before any thread too
#endif
  MediaDefaultRoot(LcarsDataDir(data_flag)); // and this

  // Before anything that could start a thread or open the journal: every
  // opener reads the path without a lock on the strength of this order.
  char db_err[256];
  if (!SetLcarsDBPath(db_flag, data_flag, db_err, sizeof(db_err))) {
    fprintf(stderr, "lcars: %s\n", db_err);
    return 2;
  }

  if (auth_user || auth_pass) {
    SetHTTPServerCredentials(auth_user, auth_pass);
  }
  InitDBMinimal();
  RunHTTPServer(port);
  // It serves forever; coming back means the socket could not be set up
  // (port taken, a bad LCARS_BIND), and systemd should see a failure.
  return 1;
}
