#ifndef LCARS_FEATURES_H
#define LCARS_FEATURES_H

// GET /features - what this server can do, and what each thing it cannot
// lacks: the web UI's one source for the notes at a feature's door and the
// Server section of Config (docs/design/open-source.md, 2a-2c).
//
//   {"features":[{"name":"maps","on":false,"needs":["LCARS_MAPY_KEY"],
//                 "note":"Plotting a course draws ..."}, ...]}
//
// `needs` names what is missing - a setting, or for a program that has no
// setting of its own (git, gh, python3) the program - and is empty when the
// feature is on. Never a value, and nothing about this box: no path, no
// host, no key's length. `note` is the same words whatever the state, the
// sentence the page shows when the feature is off, so the server is the one
// place the wording lives.
//
// Every check is what a getenv, a stat or an access(2) answers, made when
// the request comes - a setting changed takes a restart anyway, a mount
// can come and go - except embeddings: whether the service answers is a
// network question, so it is not asked here. The indexer asks it once at
// start and with every request it makes after (g_embed_answering in
// lcars_embed.h); this reads its last answer. Until that first answer the
// feature is off, needing LCARS_EMBED_URL.
//
// The owner's login only: a limited login (Number One, the crew) is told
// no, since which features are off says which settings the box lacks.
//
// A module of lcars_http.h, included from inside its
// LCARS_HTTP_IMPLEMENTATION block after lcars_say.h and lcars_embed.h,
// whose start-time state it reads.

static int HandleFeatures(int client_fd, Arena *arena);

#ifdef LCARS_FEATURES_IMPLEMENTATION

#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>

// At most this many names in one feature's needs (the engineers' six).
#define FEATURES_NEEDS_MAX 8

typedef struct Feature {
  const char *name;
  const char *note;
  const char *needs[FEATURES_NEEDS_MAX];
  int n_needs;
} Feature;

static void FeatureNeed(Feature *f, const char *setting) {
  assert(f != NULL && setting != NULL && setting[0] != '\0');
  assert(f->n_needs < FEATURES_NEEDS_MAX);
  f->needs[f->n_needs++] = setting;
}

// A variable that is set to something.
static bool FeatureSet(const char *name) {
  assert(name != NULL);
  const char *v = getenv(name);
  return v != NULL && v[0] != '\0';
}

// `prog` as execvp would find it: an executable file in a PATH directory.
// `extra`, when given, is searched first (the engineers' ~/.local/bin).
static bool FeatureOnPath(const char *prog, const char *extra) {
  assert(prog != NULL && prog[0] != '\0' && strchr(prog, '/') == NULL);
  const char *path = getenv("PATH");
  const char *dirs[2] = {extra, path ? path : "/usr/local/bin:/usr/bin:/bin"};
  for (int d = 0; d < 2; d++) {
    const char *p = dirs[d];
    while (p != NULL && *p != '\0') {
      const char *colon = strchr(p, ':');
      size_t len = colon ? (size_t)(colon - p) : strlen(p);
      char file[PATH_MAX];
      int n = snprintf(file, sizeof(file), "%.*s/%s", (int)len, p, prog);
      struct stat sb;
      if (len > 0 && n > 0 && (size_t)n < sizeof(file) &&
          stat(file, &sb) == 0 && S_ISREG(sb.st_mode) &&
          access(file, X_OK) == 0) {
        return true;
      }
      p = colon ? colon + 1 : NULL;
    }
  }
  return false;
}

// The media store as HandleMediaUpload needs it: <root>/media a directory
// this process may write (MediaCheckMounted's test, and the write).
static bool FeatureMediaRoot(void) {
  char dir[PATH_MAX];
  int n = snprintf(dir, sizeof(dir), "%s/" MEDIA_SUBDIR, MediaRoot());
  struct stat sb;
  return n > 0 && (size_t)n < sizeof(dir) && stat(dir, &sb) == 0 &&
         S_ISDIR(sb.st_mode) && access(dir, W_OK) == 0;
}

// ffmpeg as MediaRunFfmpeg runs it: $LCARS_FFMPEG_BIN, else "ffmpeg" on PATH.
static bool FeatureFfmpeg(void) {
  const char *bin = getenv("LCARS_FFMPEG_BIN");
  if (bin == NULL || bin[0] == '\0') {
    return FeatureOnPath("ffmpeg", NULL);
  }
  return strchr(bin, '/') ? access(bin, X_OK) == 0 : FeatureOnPath(bin, NULL);
}

// The claude CLI as the chat starts it (ChatResolveClaude), or on PATH.
static bool FeatureClaude(void) {
  char bin[PATH_MAX];
  return ChatResolveClaude(bin, sizeof(bin)) ||
         (!FeatureSet("LCARS_CLAUDE_BIN") && FeatureOnPath("claude", NULL));
}

static void FeatureChat(Feature *f) {
  assert(f != NULL);
  const char *chat = getenv("LCARS_CHAT");
  if (chat != NULL && strcmp(chat, "0") == 0) {
    FeatureNeed(f, "LCARS_CHAT");
  }
  if (!FeatureClaude()) {
    FeatureNeed(f, "LCARS_CLAUDE_BIN");
  }
}

// Spoken replies, by SayInit's rule: LCARS_TTS names the provider (unset:
// Deepgram when its key is there), and the provider wants its key.
static void FeatureSpeech(Feature *f) {
  assert(f != NULL);
  if (g_say.provider != SAY_OFF) {
    return;
  }
  const char *tts = getenv("LCARS_TTS");
  if (tts != NULL && tts[0] != '\0' && strcmp(tts, "deepgram") != 0 &&
      strcmp(tts, "elevenlabs") != 0) {
    FeatureNeed(f, "LCARS_TTS"); // "off", or a provider it does not know
  } else if (tts != NULL && strcmp(tts, "elevenlabs") == 0) {
    FeatureNeed(f, "ELEVENLABS_API_KEY");
  } else {
    FeatureNeed(f, "DEEPGRAM_API_KEY");
  }
}

static void FeatureEngineers(Feature *f) {
  assert(f != NULL);
  const char *on = getenv("LCARS_ENGINEER");
  if (on == NULL || strcmp(on, "1") != 0) {
    FeatureNeed(f, "LCARS_ENGINEER");
  }
  const char *key = getenv("LCARS_ENGINEER_KEY");
  if (key == NULL || strlen(key) < ENGINEER_KEY_MIN) {
    FeatureNeed(f, "LCARS_ENGINEER_KEY");
  }
  // the script where EngineerRun looks for it
  char script[PATH_MAX];
  const char *s = getenv("LCARS_ENGINEER_SCRIPT");
  bool found = false;
  if (s != NULL && s[0] != '\0') {
    found = access(s, R_OK) == 0;
  } else if (getcwd(script, sizeof(script) - 32) != NULL) {
    strcat(script, "/scripts/engineer.py");
    found = access(script, R_OK) == 0;
  }
  if (!found) {
    FeatureNeed(f, "LCARS_ENGINEER_SCRIPT");
  }
  char python[PATH_MAX];
  if (!EngineerPython(python, sizeof(python)) ||
      access(python, X_OK) != 0) { // EngineerRun's own rule
    FeatureNeed(f, "python3");
  }
  // EngineerEnv puts ~/.local/bin before the server's PATH
  char local[PATH_MAX];
  const char *home = getenv("HOME");
  snprintf(local, sizeof(local), "%s/.local/bin", home ? home : "");
  if (!FeatureOnPath("git", local)) {
    FeatureNeed(f, "git");
  }
  if (!FeatureOnPath("gh", local)) {
    FeatureNeed(f, "gh");
  }
  if (!FeatureClaude()) {
    FeatureNeed(f, "LCARS_CLAUDE_BIN");
  }
}

// A limited login is on when LimitedLoginInit kept it (both variables set,
// the password long enough, the name its own); else both names are needed.
static void FeatureLogin(Feature *f, const LimitedLogin *l) {
  assert(f != NULL && l != NULL);
  if (l->user[0] == '\0') {
    FeatureNeed(f, l->env_user);
    FeatureNeed(f, l->env_pass);
  }
}

static void FeatureAppend(JSONBuf *b, const Feature *f, bool first) {
  assert(b != NULL && f != NULL && f->name != NULL && f->note != NULL);
  assert(f->n_needs >= 0 && f->n_needs <= FEATURES_NEEDS_MAX);
  jsonbuf_append(b, first ? "{\"name\":" : ",{\"name\":");
  jsonbuf_append_json_string(b, f->name);
  jsonbuf_append(b, f->n_needs == 0 ? ",\"on\":true,\"needs\":["
                                    : ",\"on\":false,\"needs\":[");
  for (int i = 0; i < f->n_needs; i++) {
    if (i > 0) {
      jsonbuf_append(b, ",");
    }
    jsonbuf_append_json_string(b, f->needs[i]);
  }
  jsonbuf_append(b, "],\"note\":");
  jsonbuf_append_json_string(b, f->note);
  jsonbuf_append(b, "}");
}

static int HandleFeatures(int client_fd, Arena *arena) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  if (g_conn_login != NULL) {
    return SendJSONError(client_fd, 403,
                         "%s may not read the server's features: the "
                         "owner's login only",
                         g_conn_login->who);
  }

  Feature fs[] = {
      {"media",
       "Photos, tapes and files are kept in the media store: set "
       "LCARS_MEDIA_ROOT to a directory holding a writable media/ folder, "
       "and restart.",
       {0},
       0},
      {"media_ffmpeg",
       "Cutting tapes and making video posters uses ffmpeg: install it on "
       "the server's PATH, or set LCARS_FFMPEG_BIN, and restart.",
       {0},
       0},
      {"computer",
       "The computer answers through the claude CLI on the server: install "
       "it and log in (or set LCARS_CLAUDE_BIN), and leave LCARS_CHAT unset "
       "or 1.",
       {0},
       0},
      {"navigator",
       "The course's navigator is the computer at work on a course: it "
       "needs the claude CLI on the server (LCARS_CLAUDE_BIN), and "
       "LCARS_CHAT unset or 1.",
       {0},
       0},
      {"maps",
       "Plotting a course draws Mapy.com maps and routes: set LCARS_MAPY_KEY "
       "and restart. Without it the course has OpenStreetMap tiles and no "
       "routing.",
       {0},
       0},
      {"transcription",
       "Transcribing recordings and live voice use Deepgram: set "
       "DEEPGRAM_API_KEY and restart. Without it the browser's own "
       "recogniser listens.",
       {0},
       0},
      {"speech",
       "Spoken replies come from Deepgram or ElevenLabs: set LCARS_TTS and "
       "the provider's key (DEEPGRAM_API_KEY or ELEVENLABS_API_KEY), and "
       "restart. Without it the browser's own voice speaks.",
       {0},
       0},
      {"embeddings",
       "Search by meaning, the star chart and related entries need an "
       "embedding service (LCARS_EMBED_URL, LCARS_EMBED_MODEL, "
       "LCARS_EMBED_KEY) answering, and LCARS_EMBED not 0. Without it "
       "search matches words.",
       {0},
       0},
      {"caldav",
       "Reminders (CalDAV) needs nothing more than the login: point the "
       "client at this server's /caldav/.",
       {0},
       0},
      {"strava",
       "Strava needs an API application's LCARS_STRAVA_CLIENT_ID and "
       "LCARS_STRAVA_CLIENT_SECRET, then lcars-cli strava auth.",
       {0},
       0},
      {"logseq",
       "The Logseq bridge needs LOGSEQ_URL and LOGSEQ_TOKEN (Logseq's API "
       "server).",
       {0},
       0},
      {"engineers",
       "The engineers need LCARS_ENGINEER=1 and LCARS_ENGINEER_KEY, "
       "scripts/engineer.py (LCARS_ENGINEER_SCRIPT), python3, git, gh and "
       "the claude CLI on the server.",
       {0},
       0},
      {"number_one",
       "Number One reads and writes the journal with its own login: set "
       "LCARS_NO1_USER and LCARS_NO1_PASS (16 characters or more), and "
       "restart.",
       {0},
       0},
      {"crew",
       "The crew's roles and notes write with their own logins: set "
       "LCARS_CREW_USER/LCARS_CREW_PASS and "
       "LCARS_STEWARD_USER/LCARS_STEWARD_PASS (passwords of 16 characters "
       "or more), and restart.",
       {0},
       0},
      {"reports",
       "Hosted reports are kept in the media store, under media/reports/: "
       "set LCARS_MEDIA_ROOT to a directory holding a writable media/ "
       "folder.",
       {0},
       0},
  };
  enum { N_FEATURES = sizeof(fs) / sizeof(fs[0]) };

  bool media = FeatureMediaRoot();
  for (int i = 0; i < N_FEATURES; i++) {
    Feature *f = &fs[i];
    const char *n = f->name;
    if (strcmp(n, "media") == 0 || strcmp(n, "reports") == 0) {
      if (!media) {
        FeatureNeed(f, "LCARS_MEDIA_ROOT");
      }
    } else if (strcmp(n, "media_ffmpeg") == 0) {
      if (!FeatureFfmpeg()) {
        FeatureNeed(f, "LCARS_FFMPEG_BIN");
      }
    } else if (strcmp(n, "computer") == 0 || strcmp(n, "navigator") == 0) {
      FeatureChat(f);
    } else if (strcmp(n, "maps") == 0) {
      if (!FeatureSet("LCARS_MAPY_KEY")) {
        FeatureNeed(f, "LCARS_MAPY_KEY");
      }
    } else if (strcmp(n, "transcription") == 0) {
      if (g_say.grant_auth[0] == '\0') { // SayInit kept no usable key
        FeatureNeed(f, "DEEPGRAM_API_KEY");
      }
    } else if (strcmp(n, "speech") == 0) {
      FeatureSpeech(f);
    } else if (strcmp(n, "embeddings") == 0) {
      if (!g_embed.on) {
        FeatureNeed(f, "LCARS_EMBED");
      } else if (atomic_load(&g_embed_answering) != 1) {
        FeatureNeed(f, "LCARS_EMBED_URL");
      }
    } else if (strcmp(n, "caldav") == 0) {
      // always on: it is the journal's own tasks, behind the login
    } else if (strcmp(n, "strava") == 0) {
      if (!FeatureSet("LCARS_STRAVA_CLIENT_ID")) {
        FeatureNeed(f, "LCARS_STRAVA_CLIENT_ID");
      }
      if (!FeatureSet("LCARS_STRAVA_CLIENT_SECRET")) {
        FeatureNeed(f, "LCARS_STRAVA_CLIENT_SECRET");
      }
    } else if (strcmp(n, "logseq") == 0) {
      if (!FeatureSet("LOGSEQ_URL")) {
        FeatureNeed(f, "LOGSEQ_URL");
      }
      if (!FeatureSet("LOGSEQ_TOKEN")) {
        FeatureNeed(f, "LOGSEQ_TOKEN");
      }
    } else if (strcmp(n, "engineers") == 0) {
      FeatureEngineers(f);
    } else if (strcmp(n, "number_one") == 0) {
      FeatureLogin(f, &g_login_no1);
    } else if (strcmp(n, "crew") == 0) {
      FeatureLogin(f, &g_login_crew);
      FeatureLogin(f, &g_login_steward);
    } else {
      assert(!"unreachable: a feature with no check");
    }
  }

  JSONBuf b;
  jsonbuf_init(&b, arena);
  jsonbuf_append(&b, "{\"features\":[");
  for (int i = 0; i < N_FEATURES; i++) {
    FeatureAppend(&b, &fs[i], i == 0);
  }
  jsonbuf_append(&b, "]}");
  assert(b.overflow || (b.len > 0 && b.data[b.len - 1] == '}'));
  return SendJSONBuf(client_fd, &b);
}

#endif // LCARS_FEATURES_IMPLEMENTATION
#endif // LCARS_FEATURES_H
