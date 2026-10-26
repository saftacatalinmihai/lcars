// lcars-cli - the command-line surface over the entries table.
//
// This file is the terminal client's "host": argument parsing, the command
// table and main(). Everything it calls - the requests, the JSON scanner,
// the renderers - lives in lcars_cli.h, the same
// declarations-then-#ifdef-LCARS_IMPLEMENTATION shape as every other module
// here. It links libcurl and nothing else.
//
//   lcars-cli list --kind work_log --limit 20
//   lcars-cli get 42 --raw > entry.md
//   lcars-cli new --kind task --title "Write the CLI" --edit
//   lcars-cli edit 42
//   lcars-cli rm 42 && lcars-cli restore 42
//   lcars-cli set 42 --start "2026-10-07 06:00" --end "2026-10-07 07:00"
//   lcars-cli due 42 "2026-10-09 14:00" --alarm   # Apple Reminders' due
//   lcars-cli strava pull --dry-run               # workouts from Strava
//
// mkstemp/unlink/isatty are POSIX, and this TU is compiled -std=c11
// -pedantic like the rest, so the feature macro has to come before any
// system header.
#define _POSIX_C_SOURCE 200809L
// timegm/gmtime_r (lcars_logseq.h's day arithmetic) are not POSIX.
#define _DEFAULT_SOURCE 1

#define LCARS_IMPLEMENTATION
#include "lcars_cli.h"
#include "lcars_logseq.h"
#include "lcars_strava.h"

#include <errno.h>
#include <limits.h>

#define CLI_ARENA_SIZE (32 * 1024 * 1024)

// The default server: this machine, the port lcars.c listens
// on. LCARS_URL overrides it (that is how the VPS gets addressed).
#define CLI_DEFAULT_URL "http://127.0.0.1:8080"

static void PrintUsage(FILE *out) {
  fprintf(out,
          "lcars-cli - read and write LCARS journal entries\n"
          "\n"
          "Usage: lcars-cli [global options] <command> [options]\n"
          "\n"
          "Commands:\n"
          "  list                 List entries (filters below)\n"
          "  get <id>             Show one entry (--raw prints the content "
          "only)\n"
          "  new                  Create an entry\n"
          "  set <id>             Update the fields you name (partial)\n"
          "  append <id>          Add --content/--file text at the end of\n"
          "                       the content, nothing else touched; a\n"
          "                       blank line before it. Refused if the\n"
          "                       entry changes between read and write\n"
          "  edit <id>            Open the entry's content in $EDITOR\n"
          "  rm <id>              Soft delete (deleted = 1)\n"
          "  restore <id>         Undo a soft delete\n"
          "  done <id>            Mark done; `undone <id>` clears it\n"
          "  due <id> [<when>]    A task's due date in Apple Reminders:\n"
          "                       show it, set it (UTC date[ time]; a\n"
          "                       bare date is all day), or \"\" to clear.\n"
          "                       --alarm adds an alert at the due time\n"
          "  kinds                Distinct kinds with counts\n"
          "  roles                The kind each feature writes, by role:\n"
          "                       `roles set <role> <kind> [--name N]`,\n"
          "                       `roles reset <role>` (back to the\n"
          "                       default); --json for the server's answer\n"
          "  theme                The console's theme: `theme set <name>`\n"
          "                       (a built-in), `theme load <file>\n"
          "                       [--name N]` (a btop *.theme or an\n"
          "                       omarchy colors.toml; '-' is stdin),\n"
          "                       `theme reset` (lcars); --json\n"
          "  stats                Totals; takes the same filters as list\n"
          "  logseq <sub>         Sync with a Logseq graph "
          "(`logseq --help`)\n"
          "  strava <sub>         Pull Strava activities in as workouts "
          "(`strava --help`)\n"
          "\n"
          "Global options:\n"
          "  --url <url>          API base URL (default %s, env LCARS_URL)\n"
          "  --user <name>        Basic auth user (env LCARS_AUTH_USER)\n"
          "  --password <pass>    Basic auth password (env LCARS_AUTH_PASS)\n"
          "  --timeout <seconds>  HTTP timeout (default 30)\n"
          "  --json               Emit the API's JSON instead of a table\n"
          "  --help, -h           This message\n"
          "\n"
          "list/stats filters:\n"
          "  --kind, -k <kind>          --search, -q <text>\n"
          "  --date <YYYY-MM-DD>        --since / --until <date[ time]>\n"
          "  --modified-since <date>    --modified-until <date>\n"
          "  --done <0|1>               --deleted <0|1|all>  (default 0)\n"
          "  --min-id <n>               --max-id <n>\n"
          "  --scheduled-date <date>    Scheduled on that day (overlap)\n"
          "  --scheduled <0|1>          Has a start date at all\n"
          "  --order <id|created|modified|title|kind|start|end>\n"
          "  --dir <asc|desc>\n"
          "  --limit, -n <1..%d>        --offset <n>\n"
          "  --content                  Fetch entry bodies too (list omits\n"
          "                             them by default: the table does not\n"
          "                             show them and the server builds each\n"
          "                             response in a 1MB arena)\n"
          "\n"
          "new/set fields:\n"
          "  --kind, -k <kind>          --title, -t <title>\n"
          "  --content, -c <text>       --file, -f <path>  ('-' is stdin)\n"
          "  --edit, -e                 Compose the content in $EDITOR\n"
          "  --value-int <n>            --value-float <f>\n"
          "  --done <0|1>               --deleted <0|1>  (set only)\n"
          "  --created-at <date[ time]>  Backdate the entry (UTC). `set`\n"
          "  --modified-at <date[ time]> takes --created-at only: it stamps\n"
          "                             last_modified_at_utc itself\n"
          "  --start / --end <date[ time]>  Schedule it (UTC); \"\" "
          "unschedules\n"
          "\n"
          "kinds options:\n"
          "  --deleted                  Count soft-deleted entries too\n"
          "\n"
          "Deletes are soft everywhere in LCARS: `rm` sets deleted = 1 and\n"
          "`restore` puts it back. There is no hard delete, here or in the\n"
          "API - this database is a personal journal.\n",
          CLI_DEFAULT_URL, CLI_MAX_LIMIT);
}

// ---------------------------------------------------------------------------
// Argument helpers
// ---------------------------------------------------------------------------

static bool ArgMatch(const char *arg, const char *long_name,
                     const char *short_name) {
  assert(arg != NULL);
  assert(long_name != NULL);

  if (strcmp(arg, long_name) == 0) {
    return true;
  }
  return short_name != NULL && strcmp(arg, short_name) == 0;
}

// Consumes the value that follows a flag. Missing values are usage errors,
// not asserts: a truncated command line is user error.
static const char *ArgValue(int argc, char **argv, int *i, char *err,
                            size_t err_size) {
  assert(argv != NULL);
  assert(i != NULL && *i < argc);

  if (*i + 1 >= argc) {
    CliFail(err, err_size, "%s needs a value", argv[*i]);
    return NULL;
  }
  *i += 1;
  return argv[*i];
}

static bool ParseInt(const char *text, int *out, char *err, size_t err_size) {
  assert(text != NULL);
  assert(out != NULL);

  char *end = NULL;
  errno = 0;
  long value = strtol(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || value < INT_MIN ||
      value > INT_MAX) {
    return CliFail(err, err_size, "'%s' is not a number", text);
  }
  *out = (int)value;
  return true;
}

static bool ParseDouble(const char *text, double *out, char *err,
                        size_t err_size) {
  assert(text != NULL);
  assert(out != NULL);

  char *end = NULL;
  errno = 0;
  double value = strtod(text, &end);
  if (errno != 0 || end == text || *end != '\0') {
    return CliFail(err, err_size, "'%s' is not a number", text);
  }
  *out = value;
  return true;
}

static bool ParseBoolFlag(const char *text, int *out, char *err,
                          size_t err_size) {
  assert(text != NULL);
  assert(out != NULL);

  if (strcmp(text, "1") == 0 || strcasecmp(text, "true") == 0 ||
      strcasecmp(text, "yes") == 0) {
    *out = 1;
    return true;
  }
  if (strcmp(text, "0") == 0 || strcasecmp(text, "false") == 0 ||
      strcasecmp(text, "no") == 0) {
    *out = 0;
    return true;
  }
  return CliFail(err, err_size, "'%s' is not 0 or 1", text);
}

// Returns 1 if the flag was a global one and was consumed, 0 if it is not a
// global flag (the caller tries its own), -1 on error.
static int ParseGlobalFlag(int argc, char **argv, int *i, CliOptions *opts,
                           char *err, size_t err_size) {
  assert(argv != NULL);
  assert(i != NULL && *i < argc);
  assert(opts != NULL);

  const char *arg = argv[*i];
  const char *value = NULL;

  if (ArgMatch(arg, "--url", "-U")) {
    value = ArgValue(argc, argv, i, err, err_size);
    if (!value) {
      return -1;
    }
    opts->base_url = value;
    return 1;
  }
  if (ArgMatch(arg, "--user", "-u")) {
    value = ArgValue(argc, argv, i, err, err_size);
    if (!value) {
      return -1;
    }
    opts->user = value;
    return 1;
  }
  if (ArgMatch(arg, "--password", "-P") || strcmp(arg, "--pass") == 0) {
    value = ArgValue(argc, argv, i, err, err_size);
    if (!value) {
      return -1;
    }
    opts->pass = value;
    return 1;
  }
  if (strcmp(arg, "--timeout") == 0) {
    value = ArgValue(argc, argv, i, err, err_size);
    if (!value) {
      return -1;
    }
    int seconds = 0;
    if (!ParseInt(value, &seconds, err, err_size)) {
      return -1;
    }
    if (seconds <= 0) {
      CliFail(err, err_size, "--timeout must be positive");
      return -1;
    }
    opts->timeout_seconds = seconds;
    return 1;
  }
  if (strcmp(arg, "--json") == 0) {
    opts->json = true;
    return 1;
  }
  if (strcmp(arg, "--raw") == 0) {
    opts->raw = true;
    return 1;
  }
  return 0;
}

// A trailing "--user without --password" is the one combination worth
// catching early: curl would send an empty password and the server would
// answer 401, which reads as "wrong credentials" rather than "you forgot
// half of them".
static void WarnIncompleteCredentials(const CliOptions *opts) {
  assert(opts != NULL);

  if (opts->user && !opts->pass) {
    fprintf(stderr, "lcars-cli: warning: --user without --password\n");
  }
}

// ---------------------------------------------------------------------------
// Filter and field flags
// ---------------------------------------------------------------------------

static void FiltersInit(CliFilters *f) {
  assert(f != NULL);

  memset(f, 0, sizeof(*f));
  f->done = -1; // tristate: -1 unset, 0 and 1 are real filters
  f->limit = CLI_DEFAULT_LIMIT;
  // Bodies are not fetched unless asked for. The table never shows them,
  // and the server builds every response inside a 1MB connection arena - a
  // default of "200 entries with content" answers 500 on a journal with any
  // real writing in it.
  f->include_content = false;
}

// 1 = consumed, 0 = not a filter flag, -1 = error.
static int ParseFilterFlag(Arena *arena, int argc, char **argv, int *i,
                           CliFilters *f, char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(argv != NULL && i != NULL && *i < argc);
  assert(f != NULL);

  const char *arg = argv[*i];
  const char *value = NULL;

#define CLI_TAKE_VALUE()                                                       \
  do {                                                                         \
    value = ArgValue(argc, argv, i, err, err_size);                            \
    if (!value) {                                                              \
      return -1;                                                               \
    }                                                                          \
  } while (0)

  if (ArgMatch(arg, "--kind", "-k")) {
    CLI_TAKE_VALUE();
    f->kind = value;
    return 1;
  }
  if (ArgMatch(arg, "--search", "-q")) {
    CLI_TAKE_VALUE();
    f->q = value;
    return 1;
  }
  if (strcmp(arg, "--date") == 0) {
    CLI_TAKE_VALUE();
    const char *normalized = NULL;
    if (!CliNormalizeTimestamp(arena, value, false, &normalized, err,
                               err_size)) {
      return -1;
    }
    if (strlen(value) != 10) {
      CliFail(err, err_size, "--date takes YYYY-MM-DD");
      return -1;
    }
    f->date = normalized;
    return 1;
  }

  static const struct {
    const char *flag;
    size_t offset;
    bool upper_bound;
  } ranges[] = {
      {"--since", offsetof(CliFilters, since), false},
      {"--until", offsetof(CliFilters, until), true},
      {"--modified-since", offsetof(CliFilters, modified_since), false},
      {"--modified-until", offsetof(CliFilters, modified_until), true},
  };
  for (size_t r = 0; r < sizeof(ranges) / sizeof(ranges[0]); r++) {
    if (strcmp(arg, ranges[r].flag) != 0) {
      continue;
    }
    CLI_TAKE_VALUE();
    const char *normalized = NULL;
    if (!CliNormalizeTimestamp(arena, value, ranges[r].upper_bound, &normalized,
                               err, err_size)) {
      return -1;
    }
    *(const char **)((char *)f + ranges[r].offset) = normalized;
    return 1;
  }

  if (strcmp(arg, "--done") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseBoolFlag(value, &f->done, err, err_size)) {
      return -1;
    }
    return 1;
  }
  if (strcmp(arg, "--scheduled-date") == 0) {
    CLI_TAKE_VALUE();
    const char *normalized = NULL;
    if (strlen(value) != 10 ||
        !CliNormalizeTimestamp(arena, value, false, &normalized, err,
                               err_size)) {
      CliFail(err, err_size, "--scheduled-date takes YYYY-MM-DD");
      return -1;
    }
    f->scheduled_date = value;
    return 1;
  }
  if (strcmp(arg, "--scheduled") == 0) {
    CLI_TAKE_VALUE();
    if (strcmp(value, "0") != 0 && strcmp(value, "1") != 0) {
      CliFail(err, err_size, "--scheduled takes 0 or 1");
      return -1;
    }
    f->scheduled = value;
    return 1;
  }
  if (strcmp(arg, "--deleted") == 0) {
    CLI_TAKE_VALUE();
    if (strcasecmp(value, "all") != 0 && strcmp(value, "0") != 0 &&
        strcmp(value, "1") != 0) {
      CliFail(err, err_size, "--deleted takes 0, 1 or all");
      return -1;
    }
    f->deleted = value;
    return 1;
  }
  if (strcmp(arg, "--min-id") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseInt(value, &f->min_id, err, err_size)) {
      return -1;
    }
    return 1;
  }
  if (strcmp(arg, "--max-id") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseInt(value, &f->max_id, err, err_size)) {
      return -1;
    }
    return 1;
  }
  if (strcmp(arg, "--order") == 0) {
    CLI_TAKE_VALUE();
    // Validated here, so a bad value fails before a request rather than as
    // the server's 400.
    if (!CliValidOrder(value)) {
      CliFail(err, err_size,
              "--order takes id, created, modified, title, kind, start or "
              "end");
      return -1;
    }
    f->order = value;
    return 1;
  }
  if (strcmp(arg, "--dir") == 0) {
    CLI_TAKE_VALUE();
    if (strcasecmp(value, "asc") != 0 && strcasecmp(value, "desc") != 0) {
      CliFail(err, err_size, "--dir takes asc or desc");
      return -1;
    }
    f->dir = value;
    return 1;
  }
  if (ArgMatch(arg, "--limit", "-n")) {
    CLI_TAKE_VALUE();
    if (!ParseInt(value, &f->limit, err, err_size)) {
      return -1;
    }
    if (f->limit < 1 || f->limit > CLI_MAX_LIMIT) {
      CliFail(err, err_size, "--limit must be 1..%d", CLI_MAX_LIMIT);
      return -1;
    }
    return 1;
  }
  if (strcmp(arg, "--offset") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseInt(value, &f->offset, err, err_size)) {
      return -1;
    }
    if (f->offset < 0) {
      CliFail(err, err_size, "--offset must be >= 0");
      return -1;
    }
    return 1;
  }
  if (strcmp(arg, "--content") == 0) {
    f->include_content = true;
    return 1;
  }
  if (strcmp(arg, "--no-content") == 0) {
    f->include_content = false;
    return 1;
  }
#undef CLI_TAKE_VALUE
  return 0;
}

// Where an entry's content is coming from on a create/update. Resolved
// after parsing, because --edit wants the *current* content as its starting
// point and that is only known once the id is.
typedef struct CliContentSource {
  const char *text; // --content
  const char *file; // --file / --stdin
  bool edit;        // --edit
} CliContentSource;

// Takes an arena because --created-at / --modified-at are normalized here,
// the same way the filter flags are (a bare minute completed, which the
// server would refuse).
static int ParseFieldFlag(Arena *arena, int argc, char **argv, int *i,
                          CliFields *f, CliContentSource *src, char *err,
                          size_t err_size) {
  assert(arena_valid(arena));
  assert(argv != NULL && i != NULL && *i < argc);
  assert(f != NULL && src != NULL);

  const char *arg = argv[*i];
  const char *value = NULL;

#define CLI_TAKE_VALUE()                                                       \
  do {                                                                         \
    value = ArgValue(argc, argv, i, err, err_size);                            \
    if (!value) {                                                              \
      return -1;                                                               \
    }                                                                          \
  } while (0)

  if (ArgMatch(arg, "--kind", "-k")) {
    CLI_TAKE_VALUE();
    f->has_kind = true;
    f->kind = value;
    return 1;
  }
  if (ArgMatch(arg, "--title", "-t")) {
    CLI_TAKE_VALUE();
    f->has_title = true;
    f->title = value;
    return 1;
  }
  if (ArgMatch(arg, "--content", "-c")) {
    CLI_TAKE_VALUE();
    src->text = value;
    return 1;
  }
  if (ArgMatch(arg, "--file", "-f")) {
    CLI_TAKE_VALUE();
    src->file = value;
    return 1;
  }
  if (strcmp(arg, "--stdin") == 0) {
    src->file = "-";
    return 1;
  }
  if (ArgMatch(arg, "--edit", "-e")) {
    src->edit = true;
    return 1;
  }
  if (strcmp(arg, "--value-int") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseInt(value, &f->value_int, err, err_size)) {
      return -1;
    }
    f->has_value_int = true;
    return 1;
  }
  if (strcmp(arg, "--value-float") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseDouble(value, &f->value_float, err, err_size)) {
      return -1;
    }
    f->has_value_float = true;
    return 1;
  }
  if (strcmp(arg, "--done") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseBoolFlag(value, &f->done_bool, err, err_size)) {
      return -1;
    }
    f->has_done = true;
    return 1;
  }
  if (strcmp(arg, "--deleted") == 0) {
    CLI_TAKE_VALUE();
    if (!ParseBoolFlag(value, &f->deleted, err, err_size)) {
      return -1;
    }
    f->has_deleted = true;
    return 1;
  }
  if (strcmp(arg, "--created-at") == 0) {
    CLI_TAKE_VALUE();
    const char *normalized = NULL;
    if (!CliNormalizeTimestamp(arena, value, false, &normalized, err,
                               err_size)) {
      return -1;
    }
    f->has_created_at = true;
    f->created_at = normalized;
    return 1;
  }
  if (strcmp(arg, "--modified-at") == 0) {
    CLI_TAKE_VALUE();
    const char *normalized = NULL;
    if (!CliNormalizeTimestamp(arena, value, false, &normalized, err,
                               err_size)) {
      return -1;
    }
    f->has_modified_at = true;
    f->modified_at = normalized;
    return 1;
  }
  if (strcmp(arg, "--start") == 0 || strcmp(arg, "--end") == 0) {
    bool start = strcmp(arg, "--start") == 0;
    CLI_TAKE_VALUE();
    // "" is a value: it unschedules, the way the API takes it.
    const char *normalized = "";
    if (value[0] != '\0' &&
        !CliNormalizeTimestamp(arena, value, false, &normalized, err,
                               err_size)) {
      return -1;
    }
    if (start) {
      f->has_start = true;
      f->start_date = normalized;
    } else {
      f->has_end = true;
      f->end_date = normalized;
    }
    return 1;
  }
#undef CLI_TAKE_VALUE
  return 0;
}

// --content, --file and --edit are three answers to the same question, so
// naming two of them is a mistake worth reporting rather than silently
// picking one. Checked separately from ResolveContent because it is a
// *usage* error (exit 2), while a missing file is a runtime one (exit 1).
static bool ValidateContentSource(const CliContentSource *src, char *err,
                                  size_t err_size) {
  assert(src != NULL);

  int sources = (src->text ? 1 : 0) + (src->file ? 1 : 0) + (src->edit ? 1 : 0);
  if (sources > 1) {
    return CliFail(err, err_size,
                   "use only one of --content, --file/--stdin and --edit");
  }
  return true;
}

// Resolves whichever source was named into fields->content. `initial` seeds
// the editor (the entry's current content on an edit, empty on a create).
static bool ResolveContent(Arena *arena, const CliContentSource *src,
                           const char *initial, CliFields *fields, char *err,
                           size_t err_size) {
  assert(arena_valid(arena));
  assert(src != NULL && fields != NULL);

  int sources = (src->text ? 1 : 0) + (src->file ? 1 : 0) + (src->edit ? 1 : 0);
  assert(sources <= 1); // ValidateContentSource() rejected the rest
  if (sources == 0) {
    return true;
  }

  if (src->text) {
    fields->has_content = true;
    fields->content = src->text;
    return true;
  }
  if (src->file) {
    const char *text = CliReadFile(arena, src->file, err, err_size);
    if (!text) {
      return false;
    }
    fields->has_content = true;
    fields->content = text;
    return true;
  }

  const char *edited = NULL;
  if (!CliEditText(arena, initial, &edited, err, err_size)) {
    return false;
  }
  fields->has_content = true;
  fields->content = edited;
  return true;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

static void Die(const char *err) {
  assert(err != NULL);
  fprintf(stderr, "lcars-cli: %s\n", err);
}

static void DieUnknown(const char *arg) {
  assert(arg != NULL);
  fprintf(stderr, "lcars-cli: unknown option '%s' (try --help)\n", arg);
}

// Every command parses its own flags, falls back to the global ones, and
// treats the first bare word as its positional argument - so `lcars-cli get
// --json 42` and `lcars-cli get 42 --json` are the same command.
static int CmdList(Arena *arena, CliOptions *opts, int argc, char **argv,
                   int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  CliFilters filters;
  FiltersInit(&filters);
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    int rc = ParseFilterFlag(arena, argc, argv, &i, &filters, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 1) {
      continue;
    }
    rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }

  WarnIncompleteCredentials(opts);
  EntryRows rows;
  if (!CliListEntries(arena, opts, &filters, &rows, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  CliPrintEntries(arena, opts, &rows);
  return 0;
}

static int CmdStats(Arena *arena, CliOptions *opts, int argc, char **argv,
                    int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  CliFilters filters;
  FiltersInit(&filters);
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    int rc = ParseFilterFlag(arena, argc, argv, &i, &filters, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 1) {
      continue;
    }
    rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }

  WarnIncompleteCredentials(opts);
  StatsRow stats;
  if (!CliGetStats(arena, opts, &filters, &stats, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  CliPrintStats(opts, &stats);
  return 0;
}

static int CmdKinds(Arena *arena, CliOptions *opts, int argc, char **argv,
                    int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  bool include_deleted = false;
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    if (strcmp(argv[i], "--deleted") == 0) {
      include_deleted = true;
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }

  WarnIncompleteCredentials(opts);
  KindRows kinds = {0};
  if (!CliListKinds(arena, opts, include_deleted, &kinds, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  CliPrintKinds(arena, opts, &kinds);
  return 0;
}

// The roles' table: one line a role, a set one marked, its live rows and
// name; the entry and any error the server read in it after.
static void PrintRoles(Arena *arena, const CliOptions *opts, JsonSpan body) {
  assert(arena_valid(arena) && opts != NULL);
  if (opts->json) {
    printf("%.*s\n", (int)body.len, body.data);
    return;
  }
  JsonSpan roles, item, v;
  json_member(body, "roles", &roles);
  int width = 4;
  const char *cursor = NULL;
  while (json_array_next(roles, &cursor, &item)) {
    if (json_member(item, "kind", &v)) {
      int len = (int)strlen(json_span_string(arena, v));
      width = len > width ? len : width;
    }
  }
  width = width > 48 ? 48 : width;
  printf("%-15s   %-*s  %6s  NAME\n", "ROLE", width, "KIND", "ROWS");
  int set_count = 0;
  cursor = NULL;
  while (json_array_next(roles, &cursor, &item)) {
    const char *role =
        json_member(item, "role", &v) ? json_span_string(arena, v) : "";
    const char *kind =
        json_member(item, "kind", &v) ? json_span_string(arena, v) : "";
    const char *name =
        json_member(item, "name", &v) ? json_span_string(arena, v) : "";
    bool set = json_member(item, "set", &v) && json_span_long(v) != 0;
    long rows = json_member(item, "rows", &v) ? json_span_long(v) : 0;
    set_count += set;
    printf("%-15s %s %-*s  %6ld%s%s\n", role, set ? "*" : " ", width,
           cli_one_line(arena, kind, width), rows, name[0] ? "  " : "", name);
  }
  if (json_member(body, "entry", &v) && v.data[0] != 'n') {
    printf("* %d set in the journal's settings entry #%ld; the rest are "
           "their defaults\n",
           set_count, json_span_long(v));
  } else {
    printf("every role its default (no settings entry titled kinds)\n");
  }
  const char *error =
      json_member(body, "error", &v) ? json_span_string(arena, v) : "";
  if (error[0] != '\0') {
    fprintf(stderr, "lcars-cli: %s\n", error);
  }
}

// roles [list] | roles set <role> <kind> [--name N] | roles reset <role>
static int CmdRoles(Arena *arena, CliOptions *opts, int argc, char **argv,
                    int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  const char *words[4] = {0};
  int n_words = 0;
  const char *name = NULL;
  char err[CLI_ERR_SIZE] = {0};
  for (int i = start; i < argc; i++) {
    if (strcmp(argv[i], "--name") == 0) {
      if (i + 1 >= argc) {
        Die("--name needs a value (\"\" for none)");
        return 2;
      }
      name = argv[++i];
      continue;
    }
    if (argv[i][0] != '-') {
      if (n_words == 4) {
        CliFail(err, sizeof(err), "unexpected argument '%s'", argv[i]);
        Die(err);
        return 2;
      }
      words[n_words++] = argv[i];
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }
  const char *sub = n_words > 0 ? words[0] : "list";
  bool list = strcmp(sub, "list") == 0 && n_words <= 1;
  bool set = strcmp(sub, "set") == 0 && n_words == 3;
  bool reset = strcmp(sub, "reset") == 0 && n_words == 2;
  if (!list && !set && !reset) {
    Die("usage: roles [list] | roles set <role> <kind> [--name N] | "
        "roles reset <role>");
    return 2;
  }
  if (name != NULL && !set) {
    Die("--name goes with `roles set`");
    return 2;
  }

  WarnIncompleteCredentials(opts);
  JsonSpan body;
  if (!CliRolesRequest(arena, opts, "GET", NULL, &body, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (set || reset) {
    // a set without --name keeps the name the role has
    if (set && name == NULL) {
      JsonSpan roles, item, v;
      const char *cursor = NULL;
      json_member(body, "roles", &roles);
      while (json_array_next(roles, &cursor, &item)) {
        if (json_member(item, "role", &v) &&
            strcmp(json_span_string(arena, v), words[1]) == 0 &&
            json_member(item, "name", &v)) {
          name = json_span_string(arena, v);
        }
      }
    }
    JSONBuf req;
    jsonbuf_init_strict(&req, arena);
    jsonbuf_append(&req, "{");
    jsonbuf_append_json_string(&req, words[1]);
    if (reset) {
      jsonbuf_append(&req, ":null}");
    } else {
      jsonbuf_append(&req, ":{\"kind\":");
      jsonbuf_append_json_string(&req, words[2]);
      if (name != NULL && name[0] != '\0') {
        jsonbuf_append(&req, ",\"name\":");
        jsonbuf_append_json_string(&req, name);
      }
      jsonbuf_append(&req, "}}");
    }
    if (!CliRolesRequest(arena, opts, "PUT", req.data, &body, err,
                         sizeof(err))) {
      Die(err);
      return 1;
    }
  }
  PrintRoles(arena, opts, body);
  return 0;
}

// GET or PUT /theme (lcars_theme.h); false with err set unless a 200 with
// the answer's shape
static bool CliThemeRequest(Arena *arena, const CliOptions *opts,
                            const char *method, const char *body, JsonSpan *out,
                            char *err, size_t err_size) {
  assert(arena_valid(arena) && opts != NULL && out != NULL);
  long status = 0;
  if (!CliHttpRequest(arena, opts, method, "/theme", body, out, &status, err,
                      err_size)) {
    return false;
  }
  if (status == 404) {
    return CliFail(err, err_size,
                   "this server has no /theme (it is older than the "
                   "theme's journal entry)");
  }
  if (status != 200) {
    return CliHttpStatusError(arena, *out, status, err, err_size);
  }
  JsonSpan v;
  if (out->len == 0 || out->data[0] != '{' || !json_member(*out, "name", &v)) {
    return CliFail(err, err_size, "expected {\"name\":...}, got: %.*s",
                   (int)(out->len < 120 ? out->len : 120), out->data);
  }
  return true;
}

// The name a file is loaded under when --name is not given: its own name
// less the extension, or for omarchy's colors.toml and btop.theme (the
// same name in every theme) the directory it is in
static const char *CliThemeNameOf(Arena *arena, const char *path) {
  assert(arena_valid(arena) && path != NULL);
  if (strcmp(path, "-") == 0) {
    return "custom";
  }
  size_t n = strlen(path);
  while (n > 1 && path[n - 1] == '/') {
    n--;
  }
  size_t b = n;
  while (b > 0 && path[b - 1] != '/') {
    b--;
  }
  const char *base = path + b;
  size_t blen = n - b;
  if ((blen == 11 && strncmp(base, "colors.toml", 11) == 0) ||
      (blen == 10 && strncmp(base, "btop.theme", 10) == 0)) {
    size_t e = b > 0 ? b - 1 : 0;
    size_t s = e;
    while (s > 0 && path[s - 1] != '/') {
      s--;
    }
    if (e > s) {
      base = path + s;
      blen = e - s;
    }
  } else {
    const char *dot = memchr(base, '.', blen);
    for (const char *d = dot; d && d < base + blen;
         d = memchr(d + 1, '.', (size_t)(base + blen - d - 1))) {
      dot = d; // the last dot
    }
    if (dot && dot > base) {
      blen = (size_t)(dot - base);
    }
  }
  if (blen == 0) {
    return "custom";
  }
  char *out = (char *)arena_alloc(arena, blen + 1);
  memcpy(out, base, blen);
  out[blen] = '\0';
  return out;
}

static void PrintTheme(Arena *arena, const CliOptions *opts, JsonSpan body) {
  assert(arena_valid(arena) && opts != NULL);
  if (opts->json) {
    printf("%.*s\n", (int)body.len, body.data);
    return;
  }
  JsonSpan v;
  const char *name =
      json_member(body, "name", &v) ? json_span_string(arena, v) : "";
  const char *fmt =
      json_member(body, "fmt", &v) ? json_span_string(arena, v) : "";
  const char *text =
      json_member(body, "text", &v) ? json_span_string(arena, v) : "";
  if (strcmp(fmt, "builtin") == 0) {
    printf("%s%s\n", name, strcmp(name, "lcars") == 0 ? " (the default)" : "");
  } else {
    printf("%s (%s, %zu bytes)\n", name, fmt, strlen(text));
  }
  if (json_member(body, "entry", &v) && v.data[0] != 'n') {
    printf("in the journal's settings entry #%ld\n", json_span_long(v));
  }
  const char *error =
      json_member(body, "error", &v) ? json_span_string(arena, v) : "";
  if (error[0] != '\0') {
    fprintf(stderr, "lcars-cli: %s\n", error);
  }
}

// theme [show] | theme set <name> | theme load <file> [--name N] | theme reset
static int CmdTheme(Arena *arena, CliOptions *opts, int argc, char **argv,
                    int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  const char *words[3] = {0};
  int n_words = 0;
  const char *name = NULL;
  char err[CLI_ERR_SIZE] = {0};
  for (int i = start; i < argc; i++) {
    if (strcmp(argv[i], "--name") == 0) {
      if (i + 1 >= argc) {
        Die("--name needs a value");
        return 2;
      }
      name = argv[++i];
      continue;
    }
    // "-" is stdin's name for load, not a flag
    if (argv[i][0] != '-' || strcmp(argv[i], "-") == 0) {
      if (n_words == 3) {
        CliFail(err, sizeof(err), "unexpected argument '%s'", argv[i]);
        Die(err);
        return 2;
      }
      words[n_words++] = argv[i];
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }
  const char *sub = n_words > 0 ? words[0] : "show";
  bool show = strcmp(sub, "show") == 0 && n_words <= 1;
  bool set = strcmp(sub, "set") == 0 && n_words == 2;
  bool load = strcmp(sub, "load") == 0 && n_words == 2;
  bool reset = strcmp(sub, "reset") == 0 && n_words == 1;
  if (!show && !set && !load && !reset) {
    Die("usage: theme [show] | theme set <name> | theme load <file> "
        "[--name N] | theme reset");
    return 2;
  }
  if (name != NULL && !load) {
    Die("--name goes with `theme load`");
    return 2;
  }

  WarnIncompleteCredentials(opts);
  JsonSpan body;
  if (show) {
    if (!CliThemeRequest(arena, opts, "GET", NULL, &body, err, sizeof(err))) {
      Die(err);
      return 1;
    }
    PrintTheme(arena, opts, body);
    return 0;
  }
  JSONBuf req;
  jsonbuf_init_strict(&req, arena);
  jsonbuf_append(&req, "{\"name\":");
  if (load) {
    const char *text = CliReadFile(arena, words[1], err, sizeof(err));
    if (text == NULL) {
      Die(err);
      return 1;
    }
    jsonbuf_append_json_string(&req,
                               name ? name : CliThemeNameOf(arena, words[1]));
    jsonbuf_append(&req, ",\"text\":");
    jsonbuf_append_json_string(&req, text);
  } else {
    jsonbuf_append_json_string(&req, reset ? "lcars" : words[1]);
  }
  jsonbuf_append(&req, "}");
  if (!CliThemeRequest(arena, opts, "PUT", req.data, &body, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  PrintTheme(arena, opts, body);
  return 0;
}

// Collects the id every single-entry command needs, plus the global flags.
// `extra` lets a command claim a flag of its own before the fallback.
static int ParseEntryCommandArgs(int argc, char **argv, int start,
                                 CliOptions *opts, int *out_id, char *err,
                                 size_t err_size) {
  assert(argv != NULL);
  assert(opts != NULL && out_id != NULL);

  const char *id_text = NULL;
  for (int i = start; i < argc; i++) {
    if (argv[i][0] != '-') {
      if (id_text) {
        CliFail(err, err_size, "unexpected argument '%s'", argv[i]);
        return 2;
      }
      id_text = argv[i];
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, err_size);
    if (rc < 0) {
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }
  if (!id_text) {
    CliFail(err, err_size, "an entry id is required");
    return 2;
  }
  if (!ParseInt(id_text, out_id, err, err_size)) {
    return 2;
  }
  if (*out_id <= 0) {
    CliFail(err, err_size, "entry ids start at 1");
    return 2;
  }
  return 0;
}

static int CmdGet(Arena *arena, CliOptions *opts, int argc, char **argv,
                  int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  char err[CLI_ERR_SIZE] = {0};
  int id = 0;
  int rc =
      ParseEntryCommandArgs(argc, argv, start, opts, &id, err, sizeof(err));
  if (rc != 0) {
    if (err[0]) {
      Die(err);
    }
    return rc;
  }

  WarnIncompleteCredentials(opts);
  EntryRow row;
  if (!CliGetEntry(arena, opts, id, &row, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  CliPrintEntry(arena, opts, &row);
  return 0;
}

static int CmdNew(Arena *arena, CliOptions *opts, int argc, char **argv,
                  int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  CliFields fields;
  memset(&fields, 0, sizeof(fields));
  CliContentSource source;
  memset(&source, 0, sizeof(source));
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    int rc = ParseFieldFlag(arena, argc, argv, &i, &fields, &source, err,
                            sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 1) {
      continue;
    }
    rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }

  if (!ValidateContentSource(&source, err, sizeof(err))) {
    Die(err);
    return 2;
  }
  // Piped input with no content flag is unambiguous: `echo hi | lcars-cli
  // new` should store "hi" rather than create an empty entry.
  if (!source.text && !source.file && !source.edit && !isatty(STDIN_FILENO)) {
    source.file = "-";
  }
  if (!ResolveContent(arena, &source, "", &fields, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  // The server would default an empty title to "HTTP Entry"; this one says
  // where the entry came from.
  if (!fields.has_title) {
    fields.has_title = true;
    fields.title = "CLI Entry";
  }

  WarnIncompleteCredentials(opts);
  int id = 0;
  if (!CliCreateEntry(arena, opts, &fields, &id, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"created\",\"id\":%d}\n", id);
  } else {
    printf("created entry %d\n", id);
  }
  return 0;
}

// `set` and `edit` are the same command; `edit` just presumes --edit, which
// is the difference between changing a field and rewriting the body.
static int CmdSet(Arena *arena, CliOptions *opts, int argc, char **argv,
                  int start, bool force_editor) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  CliFields fields;
  memset(&fields, 0, sizeof(fields));
  CliContentSource source;
  memset(&source, 0, sizeof(source));
  const char *id_text = NULL;
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    if (argv[i][0] != '-') {
      if (id_text) {
        Die("unexpected extra argument");
        return 2;
      }
      id_text = argv[i];
      continue;
    }
    int rc = ParseFieldFlag(arena, argc, argv, &i, &fields, &source, err,
                            sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 1) {
      continue;
    }
    rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }

  if (!ValidateContentSource(&source, err, sizeof(err))) {
    Die(err);
    return 2;
  }
  int id = 0;
  if (!id_text) {
    Die("an entry id is required");
    return 2;
  }
  if (!ParseInt(id_text, &id, err, sizeof(err)) || id <= 0) {
    Die(err[0] ? err : "entry ids start at 1");
    return 2;
  }
  if (force_editor && !source.text && !source.file) {
    source.edit = true;
  }

  WarnIncompleteCredentials(opts);

  // The editor starts from what is stored, so an edit is a revision rather
  // than a replacement typed from memory. Fetching also fails early on a
  // bad id, before $EDITOR has taken over the terminal.
  const char *current = "";
  bool have_current = false;
  EntryRow row;
  if (source.edit) {
    if (!CliGetEntry(arena, opts, id, &row, err, sizeof(err))) {
      Die(err);
      return 1;
    }
    current = row.content ? row.content : "";
    have_current = true;
  }
  if (!ResolveContent(arena, &source, current, &fields, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (have_current && fields.has_content &&
      strcmp(fields.content, current) == 0) {
    fields.has_content = false; // nothing changed; do not bump last_modified
  }

  if (!fields.has_kind && !fields.has_title && !fields.has_content &&
      !fields.has_value_int && !fields.has_value_float && !fields.has_done &&
      !fields.has_deleted && !fields.has_created_at && !fields.has_start &&
      !fields.has_end) {
    printf("entry %d unchanged\n", id);
    return 0;
  }
  if (!CliUpdateEntry(arena, opts, id, &fields, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"updated\",\"id\":%d}\n", id);
  } else {
    printf("updated entry %d\n", id);
  }
  return 0;
}

// `append` is add-only: the text goes to the end through POST
// /entries/<id>/append, which cannot express any other change, rather than
// through `set --content`, which would send the whole body back and lose
// whatever the entry gained between the read and the write. The stamp just
// read is the route's if_modified, so an entry edited in that window is
// refused, not overwritten. This is how the chat's crew roles add to the
// captain's entries: their rule is that his text is never rewritten.
static int CmdAppend(Arena *arena, CliOptions *opts, int argc, char **argv,
                     int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  CliFields fields;
  memset(&fields, 0, sizeof(fields));
  CliContentSource source;
  memset(&source, 0, sizeof(source));
  const char *id_text = NULL;
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    if (argv[i][0] != '-') {
      if (id_text) {
        Die("unexpected extra argument");
        return 2;
      }
      id_text = argv[i];
      continue;
    }
    int rc = ParseFieldFlag(arena, argc, argv, &i, &fields, &source, err,
                            sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 1) {
      continue;
    }
    rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }
  // Only the text: a field flag here would read as if it were applied
  if (fields.has_kind || fields.has_title || fields.has_value_int ||
      fields.has_value_float || fields.has_done || fields.has_deleted ||
      fields.has_created_at || fields.has_modified_at || fields.has_start ||
      fields.has_end) {
    Die("append takes only the text (--content, --file or --edit); "
        "use `set` for other fields");
    return 2;
  }
  if (!ValidateContentSource(&source, err, sizeof(err))) {
    Die(err);
    return 2;
  }
  int id = 0;
  if (!id_text) {
    Die("an entry id is required");
    return 2;
  }
  if (!ParseInt(id_text, &id, err, sizeof(err)) || id <= 0) {
    Die(err[0] ? err : "entry ids start at 1");
    return 2;
  }
  if (!source.text && !source.file && !source.edit && !isatty(STDIN_FILENO)) {
    source.file = "-";
  }
  if (!ResolveContent(arena, &source, "", &fields, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (!fields.has_content || !fields.content[0]) {
    Die("nothing to append: give --content or --file");
    return 2;
  }

  WarnIncompleteCredentials(opts);
  EntryRow row;
  if (!CliGetEntry(arena, opts, id, &row, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  // A blank line between what is there and what is added, unless one of
  // them already brings the break: the added text is a block of its own
  const char *have = row.content ? row.content : "";
  size_t n = strlen(have);
  const char *sep = "";
  if (n > 0 && fields.content[0] != '\n') {
    sep = have[n - 1] != '\n'              ? "\n\n"
          : (n > 1 && have[n - 2] == '\n') ? ""
                                           : "\n";
  }
  size_t len = strlen(sep) + strlen(fields.content) + 1;
  char *text = arena_alloc(arena, len);
  snprintf(text, len, "%s%s", sep, fields.content);
  if (!CliAppendEntry(arena, opts, id, text, row.last_modified_at_utc, err,
                      sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"appended\",\"id\":%d}\n", id);
  } else {
    printf("appended to entry %d\n", id);
  }
  return 0;
}

static int CmdDelete(Arena *arena, CliOptions *opts, int argc, char **argv,
                     int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  char err[CLI_ERR_SIZE] = {0};
  int id = 0;
  int rc =
      ParseEntryCommandArgs(argc, argv, start, opts, &id, err, sizeof(err));
  if (rc != 0) {
    if (err[0]) {
      Die(err);
    }
    return rc;
  }

  WarnIncompleteCredentials(opts);
  if (!CliDeleteEntry(arena, opts, id, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"deleted\",\"id\":%d}\n", id);
  } else {
    printf("deleted entry %d (soft; `lcars-cli restore %d` puts it back)\n", id,
           id);
  }
  return 0;
}

// restore/done/undone are one-field updates, and share everything but which
// field they set.
static int CmdFieldShortcut(Arena *arena, CliOptions *opts, int argc,
                            char **argv, int start, const char *what) {
  assert(arena_valid(arena));
  assert(opts != NULL);
  assert(what != NULL);

  char err[CLI_ERR_SIZE] = {0};
  int id = 0;
  int rc =
      ParseEntryCommandArgs(argc, argv, start, opts, &id, err, sizeof(err));
  if (rc != 0) {
    if (err[0]) {
      Die(err);
    }
    return rc;
  }

  CliFields fields;
  memset(&fields, 0, sizeof(fields));
  if (strcmp(what, "restore") == 0) {
    fields.has_deleted = true;
    fields.deleted = 0;
  } else {
    fields.has_done = true;
    fields.done_bool = (strcmp(what, "done") == 0) ? 1 : 0;
  }

  WarnIncompleteCredentials(opts);
  if (!CliUpdateEntry(arena, opts, id, &fields, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"%s\",\"id\":%d}\n", what, id);
  } else {
    printf("%s: entry %d\n", what, id);
  }
  return 0;
}

// `due <id> [<when>] [--alarm]` - see "A task's CalDAV side" in
// lcars_cli.h. With no <when> it prints the DUE line as stored.
static int CmdDue(Arena *arena, CliOptions *opts, int argc, char **argv,
                  int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  char err[CLI_ERR_SIZE] = {0};
  const char *id_text = NULL;
  const char *when = NULL;
  bool alarm = false;
  for (int i = start; i < argc; i++) {
    if (argv[i][0] != '-') {
      if (!id_text) {
        id_text = argv[i];
      } else if (!when) {
        when = argv[i];
      } else {
        Die("unexpected extra argument");
        return 2;
      }
      continue;
    }
    if (strcmp(argv[i], "--alarm") == 0) {
      alarm = true;
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      return 2;
    }
  }
  int id = 0;
  if (!id_text) {
    Die("an entry id is required");
    return 2;
  }
  if (!ParseInt(id_text, &id, err, sizeof(err)) || id <= 0) {
    Die(err[0] ? err : "entry ids start at 1");
    return 2;
  }

  // The new DUE line, from a UTC "YYYY-MM-DD[ HH:MM[:SS]]", before anything
  // is fetched, so a bad value fails without a request.
  char due_line[64] = {0};
  char due_value[32] = {0};
  bool all_day = false;
  if (when && when[0] != '\0') {
    const char *norm = NULL;
    if (!CliNormalizeTimestamp(arena, when, false, &norm, err, sizeof(err))) {
      Die(err);
      return 2;
    }
    all_day = strlen(norm) == 10;
    assert(all_day || strlen(norm) == CLI_MAX_TIMESTAMP_LEN);
    if (all_day) {
      snprintf(due_value, sizeof(due_value), "%.4s%.2s%.2s", norm, norm + 5,
               norm + 8);
      snprintf(due_line, sizeof(due_line), "DUE;VALUE=DATE:%s", due_value);
    } else {
      snprintf(due_value, sizeof(due_value), "%.4s%.2s%.2sT%.2s%.2s%.2sZ", norm,
               norm + 5, norm + 8, norm + 11, norm + 14, norm + 17);
      snprintf(due_line, sizeof(due_line), "DUE:%s", due_value);
    }
  }
  if (alarm && (!when || when[0] == '\0' || all_day)) {
    Die("--alarm needs a due time to ring at (a date and a time)");
    return 2;
  }

  WarnIncompleteCredentials(opts);
  CliCaldav cd = {0};
  if (!CliGetCaldav(arena, opts, id, &cd, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  size_t cur_len = 0;
  const char *cur = CliIcalTopValue(cd.extra_ical, "DUE", &cur_len);
  if (!when) {
    if (opts->json) {
      printf("{\"id\":%d,\"due\":\"%.*s\"}\n", id, (int)cur_len,
             cur ? cur : "");
    } else if (cur) {
      printf("entry %d due %.*s\n", id, (int)cur_len, cur);
    } else {
      printf("entry %d has no due date\n", id);
    }
    return 0;
  }

  // The same VALARM the page adds for "remind me when it is due".
  char alarm_block[256] = {0};
  if (alarm) {
    snprintf(alarm_block, sizeof(alarm_block),
             "BEGIN:VALARM\nUID:%lld\nACTION:DISPLAY\nDESCRIPTION:Reminder\n"
             "TRIGGER;VALUE=DATE-TIME:%s\nEND:VALARM\n",
             (long long)time(NULL) * 1000, due_value);
  }
  bool clear = when[0] == '\0';
  const char *next =
      CliIcalSetDue(arena, cd.extra_ical, clear ? NULL : due_line,
                    clear ? NULL : due_value, alarm ? alarm_block : NULL);
  if (!CliPutCaldav(arena, opts, id, next, cd.etag, err, sizeof(err))) {
    Die(err);
    return 1;
  }
  if (opts->json) {
    printf("{\"status\":\"updated\",\"id\":%d,\"due\":\"%s\"}\n", id,
           due_value);
  } else if (clear) {
    printf("entry %d: due date cleared\n", id);
  } else {
    printf("entry %d due %s%s\n", id, due_value,
           alarm ? ", with an alert" : "");
  }
  return 0;
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// The Logseq bridge
// ---------------------------------------------------------------------------

// The import reads one Logseq page at a time into this, resetting between
// pages (see LogseqImport). It has to hold the largest single page's
// markdown plus the JSON it arrived in, not the whole 6MB graph.
#define CLI_LOGSEQ_SCRATCH_SIZE (16 * 1024 * 1024)

// How far back `logseq status` looks when no range is given. Two weeks is
// about as much as fits on a terminal and covers "did the backup run".
#define CLI_LOGSEQ_STATUS_DAYS 14

static void PrintLogseqUsage(FILE *out) {
  fprintf(out,
          "lcars-cli logseq - sync entries with a Logseq graph\n"
          "\n"
          "Usage: lcars-cli [global options] logseq <subcommand> [options]\n"
          "\n"
          "Subcommands:\n"
          "  pages                List the graph's journals and pages\n"
          "  show <page|path>     Print one page's markdown\n"
          "  import               Logseq -> lcars (backdated entries)\n"
          "  export               lcars -> Logseq (journal blocks)\n"
          "  status               Per-day entry counts on both sides\n"
          "\n"
          "Logseq options:\n"
          "  --logseq-url <url>   API base (default %s, env LOGSEQ_URL)\n"
          "  --logseq-token <t>   Bearer token (env LOGSEQ_TOKEN)\n"
          "\n"
          "import options:\n"
          "  --journals           Import journals only (default: both)\n"
          "  --pages              Import pages only\n"
          "  --since <YYYY-MM-DD> --until <YYYY-MM-DD>\n"
          "                       Journal day bounds. --until defaults to the\n"
          "                       day before lcars started (%d), because from\n"
          "                       then on the journals are copies of entries\n"
          "                       this database already has\n"
          "  --limit <n>          Stop after n entries created\n"
          "  --kind <kind>        Kind for journals (default the\n"
          "                       logseq_journal role's, `lcars-cli roles`,\n"
          "                       itself '%s' by default; pages land in the\n"
          "                       page role's, '%s' by default)\n"
          "  --dry-run, -v        Show what would happen / be verbose\n"
          "\n"
          "export options:\n"
          "  --today              Today's entries (the default)\n"
          "  --date <YYYY-MM-DD>  One day\n"
          "  --since / --until    A range of days\n"
          "  --kind <kind>        Only this kind. Without it, entries the\n"
          "                       import created (the two roles' kinds,\n"
          "                       by default '%s', '%s')\n"
          "                       are left out: they came from Logseq, and\n"
          "                       sending them back would be a loop\n"
          "  --dry-run, -v\n"
          "\n"
          "Days are local: an entry stamped 20:46 UTC was written at 23:46 in\n"
          "a UTC+3 zone and is exported under that day's journal. Export adds\n"
          "'HH:MM [kind] text' blocks and never removes or rewrites one, so a\n"
          "day already filled in by hand in that format is left alone.\n",
          LOGSEQ_DEFAULT_URL, LOGSEQ_LCARS_FIRST_DAY - 1, LOGSEQ_JOURNAL_KIND,
          LOGSEQ_PAGE_KIND, LOGSEQ_JOURNAL_KIND, LOGSEQ_PAGE_KIND);
}

static bool ParseDayFlag(const char *text, int *out, char *err,
                         size_t err_size) {
  assert(text != NULL);
  assert(out != NULL);

  int day = LogseqDayFromISO(text);
  if (day == 0) {
    return CliFail(err, err_size, "'%s' is not a YYYY-MM-DD date", text);
  }
  *out = day;
  return true;
}

// Everything the five subcommands can be told, parsed by one loop. They
// share a flag vocabulary on purpose - --since/--until/--dry-run mean the
// same thing whichever verb they follow.
typedef struct CliLogseqArgs {
  bool only_journals;
  bool only_pages;
  int since_day;
  int until_day;
  bool today;
  int limit;
  bool dry_run;
  bool verbose;
  const char *kind;
  const char *target; // the positional `show` takes
} CliLogseqArgs;

static void PrintSyncStats(const char *what, const LogseqSyncStats *st,
                           bool dry_run) {
  assert(what != NULL && st != NULL);

  fflush(stdout); // --dry-run's per-item lines go to stdout; keep them first
  fprintf(stderr,
          "%s: %d considered, %d %s, %d already there, %d empty, %d failed\n",
          what, st->considered, st->written, dry_run ? "to write" : "written",
          st->skipped_existing, st->skipped_empty, st->failed);
}

static int CmdLogseqPages(Arena *arena, const LogseqOptions *ls,
                          const CliLogseqArgs *args, char *err,
                          size_t err_size) {
  assert(arena_valid(arena));
  assert(ls != NULL && args != NULL);

  LogseqPages pages;
  if (!LogseqListPages(arena, ls, &pages, err, err_size)) {
    Die(err);
    return 1;
  }
  if (pages.count > 1) {
    qsort(pages.items, (size_t)pages.count, sizeof(LogseqPage),
          logseq_compare_pages);
  }

  int shown = 0;
  for (int i = 0; i < pages.count; i++) {
    const LogseqPage *page = &pages.items[i];
    if (page->is_journal ? args->only_pages : args->only_journals) {
      continue;
    }
    if (page->is_journal) {
      if (args->since_day && page->journal_day < args->since_day) {
        continue;
      }
      if (args->until_day && page->journal_day > args->until_day) {
        continue;
      }
    }
    if (args->limit && shown >= args->limit) {
      break;
    }
    printf("%-8s  %-12s  %-40s  %s\n", page->is_journal ? "journal" : "page",
           page->journal_day ? LogseqISOFromDay(arena, page->journal_day) : "-",
           page->original_name, page->file_path);
    shown++;
  }
  fflush(stdout); // the summary is on stderr; keep it after the rows
  fprintf(stderr, "%d of %d pages\n", shown, pages.count);
  return 0;
}

// Accepts what the user is likely to have in hand: a file path, a journal
// date, or a page name in either the display or the lowercased form.
static int CmdLogseqShow(Arena *arena, const LogseqOptions *ls,
                         const CliLogseqArgs *args, char *err,
                         size_t err_size) {
  assert(arena_valid(arena));
  assert(ls != NULL && args != NULL);

  if (!args->target) {
    Die("logseq show needs a page name, a date or a file path");
    return 2;
  }

  const char *file_path = NULL;
  if (strchr(args->target, '/') != NULL) {
    file_path = args->target;
  } else {
    LogseqPages pages;
    if (!LogseqListPages(arena, ls, &pages, err, err_size)) {
      Die(err);
      return 1;
    }
    int wanted_day = LogseqDayFromISO(args->target);
    for (int i = 0; i < pages.count; i++) {
      const LogseqPage *page = &pages.items[i];
      if ((wanted_day != 0 && page->journal_day == wanted_day) ||
          strcasecmp(page->original_name, args->target) == 0 ||
          strcasecmp(page->name, args->target) == 0) {
        file_path = page->file_path;
        break;
      }
    }
    if (!file_path) {
      fprintf(stderr, "lcars-cli: no logseq page matching '%s'\n",
              args->target);
      return 1;
    }
  }

  const char *markdown = NULL;
  if (!LogseqFileContent(arena, ls, file_path, &markdown, err, err_size)) {
    Die(err);
    return 1;
  }
  fputs(markdown, stdout);
  if (markdown[0] != '\0' && markdown[strlen(markdown) - 1] != '\n') {
    fputc('\n', stdout);
  }
  return 0;
}

static int CmdLogseqImport(Arena *arena, const CliOptions *opts,
                           const LogseqOptions *ls, const CliLogseqArgs *args,
                           char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && ls != NULL && args != NULL);

  LogseqImportOptions imp = {0};
  imp.journals = !args->only_pages;
  imp.pages = !args->only_journals;
  imp.since_day = args->since_day;
  // The default upper bound is the day before lcars started keeping the
  // record itself. Past that point the journals are a hand-made copy of
  // these very entries, so importing them would duplicate the database into
  // itself. --until says otherwise if that is really what is wanted.
  imp.until_day = args->until_day ? args->until_day
                                  : LogseqDayAdd(LOGSEQ_LCARS_FIRST_DAY, -1);
  imp.limit = args->limit;
  imp.dry_run = args->dry_run;
  imp.verbose = args->verbose;
  // the kinds the server's roles say (lcars_kinds.h), so an owner who calls
  // them something else gets the import there; --kind still wins for the
  // journals
  imp.journal_kind = args->kind
                         ? args->kind
                         : CliRoleKind(arena, opts, "logseq_journal",
                                       LOGSEQ_JOURNAL_KIND, err, err_size);
  imp.page_kind =
      imp.journal_kind
          ? CliRoleKind(arena, opts, "page", LOGSEQ_PAGE_KIND, err, err_size)
          : NULL;
  if (imp.journal_kind == NULL || imp.page_kind == NULL) {
    Die(err);
    return 1;
  }

  void *backing = malloc(CLI_LOGSEQ_SCRATCH_SIZE);
  if (!backing) {
    Die("out of memory allocating the import scratch arena");
    return 1;
  }
  Arena scratch;
  arena_init(&scratch, backing, CLI_LOGSEQ_SCRATCH_SIZE);

  fprintf(stderr, "importing journals up to %s%s\n",
          LogseqISOFromDay(arena, imp.until_day),
          imp.dry_run ? " (dry run)" : "");

  LogseqSyncStats stats;
  bool ok =
      LogseqImport(arena, &scratch, opts, ls, &imp, &stats, err, err_size);
  free(backing);
  if (!ok) {
    Die(err);
    return 1;
  }
  PrintSyncStats("import", &stats, imp.dry_run);
  return stats.failed > 0 ? 1 : 0;
}

static int CmdLogseqExport(Arena *arena, const CliOptions *opts,
                           const LogseqOptions *ls, const CliLogseqArgs *args,
                           char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && ls != NULL && args != NULL);

  int today = LogseqToday();
  if (today == 0) {
    Die("cannot read the local date");
    return 1;
  }
  int first = args->since_day ? args->since_day : today;
  int last = args->until_day ? args->until_day : first;
  if (args->today || (!args->since_day && !args->until_day)) {
    first = today;
    last = today;
  }
  if (first > last) {
    Die("--since is after --until");
    return 2;
  }

  LogseqExportOptions exp = {0};
  exp.kind = args->kind;
  if (exp.kind == NULL) {
    // the import's kinds, left out of an export of everything: the roles'
    exp.journal_kind = CliRoleKind(arena, opts, "logseq_journal",
                                   LOGSEQ_JOURNAL_KIND, err, err_size);
    exp.page_kind =
        exp.journal_kind
            ? CliRoleKind(arena, opts, "page", LOGSEQ_PAGE_KIND, err, err_size)
            : NULL;
    if (exp.journal_kind == NULL || exp.page_kind == NULL) {
      Die(err);
      return 1;
    }
  }
  exp.dry_run = args->dry_run;
  exp.verbose = args->verbose;

  // Each day is independent, so the arena is rewound between them: a year's
  // export otherwise accumulates every day's entries and every refetched
  // block list at once.
  size_t mark = arena->curr_offset;
  LogseqSyncStats stats = {0};
  int status = 0;
  for (int day = first; day <= last; day = LogseqDayAdd(day, 1)) {
    arena->curr_offset = mark;
    arena->prev_offset = mark;
    if (!LogseqExportDay(arena, opts, ls, day, &exp, &stats, err, err_size)) {
      Die(err);
      status = 1;
      break;
    }
  }
  PrintSyncStats("export", &stats, exp.dry_run);
  return status != 0 ? status : (stats.failed > 0 ? 1 : 0);
}

// Side-by-side counts, so "is the backup current?" is one command. The
// Logseq column counts only blocks in the export format: a day the user
// wrote freehand shows 0 there and a non-zero total, which is exactly the
// case where an export is about to add to a page rather than fill it.
static int CmdLogseqStatus(Arena *arena, const CliOptions *opts,
                           const LogseqOptions *ls, const CliLogseqArgs *args,
                           char *err, size_t err_size) {
  assert(arena_valid(arena));
  assert(opts != NULL && ls != NULL && args != NULL);

  int today = LogseqToday();
  if (today == 0) {
    Die("cannot read the local date");
    return 1;
  }
  int last = args->until_day ? args->until_day : today;
  int first = args->since_day
                  ? args->since_day
                  : LogseqDayAdd(last, -(CLI_LOGSEQ_STATUS_DAYS - 1));
  if (first > last) {
    Die("--since is after --until");
    return 2;
  }

  printf("%-12s %7s %7s %7s  %s\n", "day", "lcars", "synced", "blocks",
         "journal");
  size_t mark = arena->curr_offset;
  for (int day = first; day <= last; day = LogseqDayAdd(day, 1)) {
    arena->curr_offset = mark;
    arena->prev_offset = mark;

    char from[24], to[24];
    if (!LogseqDayUTCRange(day, from, sizeof(from), to, sizeof(to))) {
      continue;
    }
    CliFilters filters = {0};
    filters.kind = args->kind;
    filters.since = from;
    filters.until = to;
    filters.done = -1;
    filters.limit = CLI_MAX_LIMIT;
    EntryRows rows = {0};
    if (!CliListEntries(arena, opts, &filters, &rows, err, err_size)) {
      Die(err);
      return 1;
    }

    const char *page_name = NULL;
    if (!LogseqFindJournal(arena, ls, day, &page_name, err, err_size)) {
      Die(err);
      return 1;
    }
    LogseqBlocks blocks = {0};
    if (page_name &&
        !LogseqPageBlocks(arena, ls, page_name, &blocks, err, err_size)) {
      Die(err);
      return 1;
    }
    int synced = 0;
    for (int b = 0; b < blocks.count; b++) {
      if (blocks.items[b].hhmm >= 0) {
        synced++;
      }
    }
    printf("%-12s %7d %7d %7d  %s\n", LogseqISOFromDay(arena, day), rows.count,
           synced, blocks.count, page_name ? page_name : "-");
  }
  return 0;
}

static int CmdLogseq(Arena *arena, CliOptions *opts, int argc, char **argv,
                     int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  LogseqOptions ls;
  ls.base_url = getenv("LOGSEQ_URL");
  if (!ls.base_url || ls.base_url[0] == '\0') {
    ls.base_url = LOGSEQ_DEFAULT_URL;
  }
  ls.token = getenv("LOGSEQ_TOKEN");
  ls.timeout_seconds = opts->timeout_seconds;

  CliLogseqArgs args = {0};
  const char *subcommand = NULL;
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    const char *arg = argv[i];
    if (arg[0] != '-') {
      if (!subcommand) {
        subcommand = arg;
      } else if (!args.target) {
        args.target = arg;
      } else {
        DieUnknown(arg);
        return 2;
      }
      continue;
    }
    if (ArgMatch(arg, "--help", "-h")) {
      PrintLogseqUsage(stdout);
      return 0;
    }
    if (strcmp(arg, "--logseq-url") == 0 ||
        strcmp(arg, "--logseq-token") == 0) {
      const char *value = ArgValue(argc, argv, &i, err, sizeof(err));
      if (!value) {
        Die(err);
        return 2;
      }
      if (arg[8] == 'u') {
        ls.base_url = value;
      } else {
        ls.token = value;
      }
      continue;
    }
    if (strcmp(arg, "--journals") == 0) {
      args.only_journals = true;
      continue;
    }
    if (strcmp(arg, "--pages") == 0) {
      args.only_pages = true;
      continue;
    }
    if (strcmp(arg, "--today") == 0) {
      args.today = true;
      continue;
    }
    if (strcmp(arg, "--dry-run") == 0) {
      args.dry_run = true;
      continue;
    }
    if (ArgMatch(arg, "--verbose", "-v")) {
      args.verbose = true;
      continue;
    }
    if (strcmp(arg, "--since") == 0 || strcmp(arg, "--until") == 0 ||
        strcmp(arg, "--date") == 0) {
      const char *value = ArgValue(argc, argv, &i, err, sizeof(err));
      if (!value) {
        Die(err);
        return 2;
      }
      int day = 0;
      if (!ParseDayFlag(value, &day, err, sizeof(err))) {
        Die(err);
        return 2;
      }
      if (strcmp(arg, "--since") == 0) {
        args.since_day = day;
      } else if (strcmp(arg, "--until") == 0) {
        args.until_day = day;
      } else {
        args.since_day = day; // --date is a one-day range
        args.until_day = day;
      }
      continue;
    }
    if (ArgMatch(arg, "--limit", "-n")) {
      const char *value = ArgValue(argc, argv, &i, err, sizeof(err));
      if (!value) {
        Die(err);
        return 2;
      }
      if (!ParseInt(value, &args.limit, err, sizeof(err)) || args.limit < 0) {
        Die(err[0] ? err : "--limit must be >= 0");
        return 2;
      }
      continue;
    }
    if (ArgMatch(arg, "--kind", "-k")) {
      const char *value = ArgValue(argc, argv, &i, err, sizeof(err));
      if (!value) {
        Die(err);
        return 2;
      }
      args.kind = value;
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(arg);
      return 2;
    }
  }

  if (args.only_journals && args.only_pages) {
    Die("--journals and --pages are mutually exclusive");
    return 2;
  }
  if (!subcommand) {
    PrintLogseqUsage(stderr);
    return 2;
  }

  WarnIncompleteCredentials(opts);

  if (strcmp(subcommand, "pages") == 0 || strcmp(subcommand, "ls") == 0) {
    return CmdLogseqPages(arena, &ls, &args, err, sizeof(err));
  }
  if (strcmp(subcommand, "show") == 0 || strcmp(subcommand, "cat") == 0) {
    return CmdLogseqShow(arena, &ls, &args, err, sizeof(err));
  }
  if (strcmp(subcommand, "import") == 0) {
    return CmdLogseqImport(arena, opts, &ls, &args, err, sizeof(err));
  }
  if (strcmp(subcommand, "export") == 0) {
    return CmdLogseqExport(arena, opts, &ls, &args, err, sizeof(err));
  }
  if (strcmp(subcommand, "status") == 0) {
    return CmdLogseqStatus(arena, opts, &ls, &args, err, sizeof(err));
  }
  if (strcmp(subcommand, "help") == 0) {
    PrintLogseqUsage(stdout);
    return 0;
  }
  fprintf(stderr, "lcars-cli: unknown logseq subcommand '%s'\n", subcommand);
  return 2;
}

// ---------------------------------------------------------------------------
// The Strava bridge
// ---------------------------------------------------------------------------

static void PrintStravaUsage(FILE *out) {
  fprintf(
      out,
      "lcars-cli strava - Strava activities as workout entries\n"
      "\n"
      "Usage: lcars-cli [global options] strava <subcommand> [options]\n"
      "\n"
      "Subcommands:\n"
      "  auth                 Print the URL that grants this box access\n"
      "  auth <code|url>      Trade the code from the http://localhost/?"
      "code=...\n"
      "                       redirect (or that whole address) for tokens\n"
      "  pull                 Create or update one entry per activity\n"
      "                       since the last pull, of the workout role's\n"
      "                       kind (`lcars-cli roles`; default '%s')\n"
      "  status               Who is connected, the last pull, the "
      "entries\n"
      "\n"
      "pull options:\n"
      "  --since <YYYY-MM-DD> Start there instead of the last pull\n"
      "                       (which is looked back on by %d days)\n"
      "  --dry-run            Say what would be written, write nothing\n"
      "  --verbose, -v        Name the unchanged activities too\n"
      "\n"
      "Environment: LCARS_STRAVA_CLIENT_ID, LCARS_STRAVA_CLIENT_SECRET (the\n"
      "API application at https://www.strava.com/settings/api), and\n"
      "LCARS_STRAVA_API (default %s). Tokens: ~/%s/%s.\n"
      "Strava allows 100 requests per 15 minutes and 1000 a day; a pull\n"
      "that reaches the limit stops, and the next one carries on.\n",
      STRAVA_KIND, STRAVA_OVERLAP_SECONDS / 86400, STRAVA_DEFAULT_API,
      STRAVA_TOKEN_DIR, STRAVA_TOKEN_FILE);
}

static int CmdStravaAuth(Arena *arena, const StravaOptions *so,
                         const char *input, char *err, size_t err_size) {
  if (!so->client_id || so->client_id[0] == '\0') {
    Die("set LCARS_STRAVA_CLIENT_ID (and LCARS_STRAVA_CLIENT_SECRET) from "
        "https://www.strava.com/settings/api first");
    return 1;
  }
  if (!input) {
    printf("%s\n", StravaAuthorizeURL(arena, so));
    fprintf(stderr,
            "Open that, authorize, and copy the address the browser lands "
            "on\n(http://localhost/?...&code=..., a page that does not load). "
            "Then:\n  lcars-cli strava auth '<that address or its code>'\n");
    return 0;
  }
  const char *scope = NULL;
  const char *code = StravaCodeFromInput(arena, input, &scope);
  if (!code || code[0] == '\0') {
    Die("no code= in that address");
    return 2;
  }
  if (scope && !strstr(scope, STRAVA_SCOPE)) {
    fprintf(stderr,
            "lcars-cli: warning: the grant's scope is '%s', without %s: "
            "private activities will be missing\n",
            scope, STRAVA_SCOPE);
  }
  StravaToken tok;
  if (!StravaLoadToken(arena, so, &tok, err, err_size) ||
      !StravaExchangeCode(arena, so, code, &tok, err, err_size)) {
    Die(err);
    return 1;
  }
  printf("connected: %s (athlete %lld); tokens in %s\n",
         tok.athlete_name[0] ? tok.athlete_name : "?", tok.athlete_id,
         so->token_path);
  return 0;
}

static int CmdStravaPull(Arena *arena, const CliOptions *opts,
                         const StravaOptions *so, long long since_epoch,
                         bool dry_run, bool verbose, char *err,
                         size_t err_size) {
  StravaToken tok;
  if (!StravaLoadToken(arena, so, &tok, err, err_size) ||
      !StravaEnsureFresh(arena, so, &tok, err, err_size)) {
    Die(err);
    return 1;
  }
  StravaPullOptions po = {0};
  po.kind = CliRoleKind(arena, opts, "workout", STRAVA_KIND, err, err_size);
  if (po.kind == NULL) {
    Die(err);
    return 1;
  }
  po.dry_run = dry_run;
  po.verbose = verbose;
  if (since_epoch > 0) {
    po.after = since_epoch;
  } else if (tok.last_pull_epoch > STRAVA_OVERLAP_SECONDS) {
    po.after = tok.last_pull_epoch - STRAVA_OVERLAP_SECONDS;
  }
  // Taken before the first request: an activity uploaded while this pull
  // runs is the next one's.
  long long started = (long long)time(NULL);

  StravaPullStats st;
  bool ok = StravaPull(arena, opts, so, &tok, &po, &st, err, err_size);
  fflush(stdout); // the per-activity lines first, then the summary
  if (!ok) {
    Die(err);
  }

  // The cursor. A clean pull moves it to when it started. One that stopped
  // (a 429, an error) moves it to the newest activity it finished - the list
  // is oldest first, so everything before that is in - and never back. One
  // with a failed activity leaves it, so the next pull tries that again.
  // --dry-run never moves it.
  long long cursor = tok.last_pull_epoch;
  if (!dry_run && st.failed == 0) {
    long long reached = ok && !st.rate_limited ? started : st.newest_done_epoch;
    if (reached > cursor) {
      cursor = reached;
    }
  }
  if (cursor != tok.last_pull_epoch) {
    tok.last_pull_epoch = cursor;
    char save_err[CLI_ERR_SIZE] = {0};
    if (!StravaSaveToken(arena, so, &tok, save_err, sizeof(save_err))) {
      Die(save_err);
      ok = false;
    }
  }

  fprintf(stderr,
          "strava pull%s: %d activities, %d %s, %d %s, %d unchanged, "
          "%d deleted here, %d failed; %d Strava requests\n",
          dry_run ? " (dry run)" : "", st.seen, st.created,
          dry_run ? "to create" : "created", st.updated,
          dry_run ? "to update" : "updated", st.unchanged, st.deleted,
          st.failed, st.requests);
  if (st.rate_limited) {
    fprintf(stderr,
            "strava pull: Strava's rate limit (HTTP 429) - stopped; the next "
            "pull carries on from %s\n",
            cursor ? StravaUTC(arena, cursor) : "the start");
  }
  return ok && st.failed == 0 ? 0 : 1;
}

static int CmdStravaStatus(Arena *arena, const CliOptions *opts,
                           const StravaOptions *so, char *err,
                           size_t err_size) {
  StravaToken tok;
  if (!StravaLoadToken(arena, so, &tok, err, err_size)) {
    Die(err);
    return 1;
  }
  if (!tok.present) {
    printf("not connected - run `lcars-cli strava auth`\n");
    return 1;
  }
  int rc = 0;
  long long athlete_id = 0;
  const char *name = "";
  bool rate_limited = false;
  if (!StravaEnsureFresh(arena, so, &tok, err, err_size) ||
      !StravaGetAthlete(arena, so, &tok, &athlete_id, &name, &rate_limited, err,
                        err_size)) {
    if (rate_limited) {
      // The grant is fine, the hour's requests are spent (a backfill does
      // that every hour): a note, not a failure, or a monitor reads broken.
      printf("connected:  %s (athlete %lld, from the token file; the lookup "
             "was rate-limited, HTTP 429)\n",
             tok.athlete_name, tok.athlete_id);
    } else {
      Die(err);
      rc = 1;
    }
  } else {
    printf("connected:  %s (athlete %lld)\n", name, athlete_id);
  }
  printf("last pull:  %s\n",
         tok.last_pull_epoch ? StravaUTC(arena, tok.last_pull_epoch) : "never");

  const char *kind =
      CliRoleKind(arena, opts, "workout", STRAVA_KIND, err, err_size);
  if (kind == NULL) {
    Die(err);
    return 1;
  }
  CliFilters f;
  FiltersInit(&f);
  f.kind = kind;
  f.q = "strava.com/activities/";
  StatsRow stats;
  if (!CliGetStats(arena, opts, &f, &stats, err, err_size)) {
    Die(err);
    return 1;
  }
  printf("entries:    %d %s from Strava", stats.count, kind);
  if (stats.count > 0) {
    printf(", %.10s to %.10s", stats.oldest_created_at_utc,
           stats.newest_created_at_utc);
  }
  printf("\n");
  return rc;
}

static int CmdStrava(Arena *arena, CliOptions *opts, int argc, char **argv,
                     int start) {
  assert(arena_valid(arena));
  assert(opts != NULL);

  const char *subcommand = NULL;
  const char *target = NULL;
  long long since_epoch = 0;
  bool dry_run = false;
  bool verbose = false;
  char err[CLI_ERR_SIZE] = {0};

  for (int i = start; i < argc; i++) {
    const char *arg = argv[i];
    if (arg[0] != '-') {
      if (!subcommand) {
        subcommand = arg;
      } else if (!target) {
        target = arg;
      } else {
        DieUnknown(arg);
        return 2;
      }
      continue;
    }
    if (ArgMatch(arg, "--help", "-h")) {
      PrintStravaUsage(stdout);
      return 0;
    }
    if (strcmp(arg, "--dry-run") == 0) {
      dry_run = true;
      continue;
    }
    if (ArgMatch(arg, "--verbose", "-v")) {
      verbose = true;
      continue;
    }
    if (strcmp(arg, "--since") == 0) {
      const char *value = ArgValue(argc, argv, &i, err, sizeof(err));
      if (!value) {
        Die(err);
        return 2;
      }
      int day = 0;
      if (!ParseDayFlag(value, &day, err, sizeof(err))) {
        Die(err);
        return 2;
      }
      since_epoch = logseq_day_epoch(day, 0);
      continue;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(arg);
      return 2;
    }
  }
  if (!subcommand) {
    PrintStravaUsage(stderr);
    return 2;
  }

  StravaOptions so;
  if (!StravaOptionsFromEnv(arena, &so, opts->timeout_seconds, err,
                            sizeof(err))) {
    Die(err);
    return 1;
  }
  WarnIncompleteCredentials(opts);

  if (strcmp(subcommand, "auth") == 0) {
    return CmdStravaAuth(arena, &so, target, err, sizeof(err));
  }
  if (target) {
    DieUnknown(target);
    return 2;
  }
  if (strcmp(subcommand, "pull") == 0) {
    return CmdStravaPull(arena, opts, &so, since_epoch, dry_run, verbose, err,
                         sizeof(err));
  }
  if (strcmp(subcommand, "status") == 0) {
    return CmdStravaStatus(arena, opts, &so, err, sizeof(err));
  }
  if (strcmp(subcommand, "help") == 0) {
    PrintStravaUsage(stdout);
    return 0;
  }
  fprintf(stderr, "lcars-cli: unknown strava subcommand '%s'\n", subcommand);
  return 2;
}

int main(int argc, char **argv) {
  // One arena for the whole run, freed by exiting. Sized for the largest
  // thing this tool holds at once: a full 1000-row listing with bodies.
  void *backing = malloc(CLI_ARENA_SIZE);
  if (!backing) {
    fprintf(stderr, "lcars-cli: out of memory\n");
    return 1;
  }
  Arena arena;
  arena_init(&arena, backing, CLI_ARENA_SIZE);

  CliOptions opts;
  memset(&opts, 0, sizeof(opts));
  opts.base_url = getenv("LCARS_URL");
  if (!opts.base_url || opts.base_url[0] == '\0') {
    opts.base_url = CLI_DEFAULT_URL;
  }
  opts.user = getenv("LCARS_AUTH_USER");
  opts.pass = getenv("LCARS_AUTH_PASS");
  opts.timeout_seconds = 30;

  // A trailing slash on the base URL would produce "…//entries", which some
  // proxies rewrite and some do not.
  size_t url_len = strlen(opts.base_url);
  if (url_len > 0 && opts.base_url[url_len - 1] == '/') {
    char *trimmed = (char *)arena_alloc(&arena, url_len);
    memcpy(trimmed, opts.base_url, url_len - 1);
    trimmed[url_len - 1] = '\0';
    opts.base_url = trimmed;
  }

  char err[CLI_ERR_SIZE] = {0};
  const char *command = NULL;
  int command_index = argc;
  for (int i = 1; i < argc; i++) {
    if (argv[i][0] != '-') {
      command = argv[i];
      command_index = i;
      break;
    }
    if (ArgMatch(argv[i], "--help", "-h")) {
      PrintUsage(stdout);
      free(backing);
      return 0;
    }
    int rc = ParseGlobalFlag(argc, argv, &i, &opts, err, sizeof(err));
    if (rc < 0) {
      Die(err);
      free(backing);
      return 2;
    }
    if (rc == 0) {
      DieUnknown(argv[i]);
      free(backing);
      return 2;
    }
  }

  if (!command) {
    PrintUsage(stderr);
    free(backing);
    return 2;
  }

  curl_global_init(CURL_GLOBAL_DEFAULT);

  int start = command_index + 1;
  int status;
  if (strcmp(command, "list") == 0 || strcmp(command, "ls") == 0) {
    status = CmdList(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "get") == 0 || strcmp(command, "show") == 0 ||
             strcmp(command, "cat") == 0) {
    status = CmdGet(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "new") == 0 || strcmp(command, "add") == 0 ||
             strcmp(command, "create") == 0) {
    status = CmdNew(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "set") == 0 || strcmp(command, "update") == 0) {
    status = CmdSet(&arena, &opts, argc, argv, start, false);
  } else if (strcmp(command, "append") == 0) {
    status = CmdAppend(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "edit") == 0) {
    status = CmdSet(&arena, &opts, argc, argv, start, true);
  } else if (strcmp(command, "rm") == 0 || strcmp(command, "delete") == 0 ||
             strcmp(command, "del") == 0) {
    status = CmdDelete(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "restore") == 0) {
    status = CmdFieldShortcut(&arena, &opts, argc, argv, start, "restore");
  } else if (strcmp(command, "done") == 0) {
    status = CmdFieldShortcut(&arena, &opts, argc, argv, start, "done");
  } else if (strcmp(command, "undone") == 0) {
    status = CmdFieldShortcut(&arena, &opts, argc, argv, start, "undone");
  } else if (strcmp(command, "due") == 0) {
    status = CmdDue(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "kinds") == 0) {
    status = CmdKinds(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "roles") == 0) {
    status = CmdRoles(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "theme") == 0) {
    status = CmdTheme(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "stats") == 0) {
    status = CmdStats(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "logseq") == 0) {
    status = CmdLogseq(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "strava") == 0) {
    status = CmdStrava(&arena, &opts, argc, argv, start);
  } else if (strcmp(command, "help") == 0) {
    PrintUsage(stdout);
    status = 0;
  } else {
    fprintf(stderr, "lcars-cli: unknown command '%s' (try --help)\n", command);
    status = 2;
  }

  curl_global_cleanup();
  free(backing);
  assert(status == 0 || status == 1 || status == 2);
  return status;
}
