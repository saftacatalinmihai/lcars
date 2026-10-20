#ifndef LCARS_MEDIA_H
#define LCARS_MEDIA_H

// Photos, video, audio - and any other file - attached to entries.
//
// The bytes live as plain files under $LCARS_MEDIA_ROOT - a NAS's NFS mount
// on the captain's box, by default <data dir>/media (MediaDefaultRoot); the
// database holds only where each one is, as a path relative to that root:
//
//   media/2026/09/24/e1234-134502-9f3c1a2b.jpg
//
// That relative path is also the URL path: GET /media/<path> (HandleMediaFile)
// serves it, so the web UI shows a file by putting "<base>/" in front of the
// stored path. It answers Range requests (a <video> needs them) and asks no
// password of tailscale serve's proxy (an <img> cannot send one), and it
// serves from a cache on the VPS's disk before the NAS, whose uplink is slow.
//
//   POST   /entries/<id>/media?name=<original filename>   raw body, one file
//          [&cut=<ms>]   audio or video: keep the first <ms> of it (see below)
//   GET    /entries/<id>/media                            the entry's files
//   GET    /media                         every live entry's files (the view)
//   DELETE /entries/<id>/media/<media id>                 soft delete
//   GET    /media/<path>                 the file itself, Range and all
//   GET    /reports                      the published reports, newest first
//   POST   /tapes/<token>?off=<bytes>    append a slice of a recording that
//          is still going on; then POST /entries/<id>/media?tape=<token>
//          with no body attaches what was staged (see HandleTapeAppend)
//
// The upload body is the file itself, not JSON and not multipart, and it is
// streamed from the socket to the NAS in chunks: a phone video is hundreds of
// megabytes against a 1MB connection arena, so it can never go through
// ReadHTTPRequestBody. That is why the router dispatches the POST *before*
// the body is read, and why the handler owns the keep-alive decision for it.
//
// `entry_media` is a side table, created on the first media request - the
// same shape as CalDAV's caldav_tasks: the entries schema is untouched, and a
// database that never sees a photo never grows it. Deletes are soft, and the
// file is never removed from the NAS by this server: the NAS is the archive.
//
// A module of lcars_http.h, like lcars_caldav.h and lcars_chat.h: it uses that
// file's response helpers and is included from inside its
// LCARS_HTTP_IMPLEMENTATION block.
//
// Photos, video and audio are the types this server knows (g_media_types);
// everything else - a PDF, a spreadsheet, a zip - is stored too, as a
// "file" (ResolveFileType). The difference is only in what the web UI draws
// for it and in how carefully the extension is chosen, because /media/ is
// served from the same origin as the web UI itself (see ResolveFileType).

// True for "/entries/<id>/media" and "/entries/<id>/media/<media id>";
// *out_media_id is 0 for the former.
static bool MatchMediaPath(const char *path, int *out_entry_id,
                           int *out_media_id);
static int HandleMediaUpload(int client_fd, Arena *arena, int entry_id,
                             const char *query, const char *req_buf,
                             const char *body_start, int total_read,
                             int headers_len, bool client_keep_alive);
static int HandleMediaList(int client_fd, Arena *arena, int entry_id);
// POST /chat/media, a file for a chat message (no entry, no row).
static int HandleChatMediaUpload(int client_fd, Arena *arena, const char *query,
                                 const char *req_buf, const char *body_start,
                                 int total_read, int headers_len,
                                 bool client_keep_alive);
static bool MatchTapePath(const char *path, char *out_token, size_t cap);
static int HandleTapeAppend(int client_fd, const char *token, const char *query,
                            const char *body, int body_len);
static int HandleMediaDelete(int client_fd, int entry_id, int media_id);
// GET/HEAD /media/<path>, the files themselves (see HandleMediaFile).
static bool MediaPeerIsLoopback(int client_fd);
static bool MediaIsFilePath(const char *path);
static int HandleMediaFile(int client_fd, Arena *arena, const char *method,
                           const char *path, const char *req_buf);
// Reports: files published by scripts/report.py, not attached to an entry
// (see "Reports" below). GET /reports lists them.
static bool MediaIsReportPath(const char *path);
static int HandleReportList(int client_fd, Arena *arena);
// The send half of HandleMediaFile, shared with the web UI's files
// (lcars_ui_files.h): Range, HEAD, the body. Takes ownership of fd.
static int MediaSendOpenFile(int client_fd, Arena *arena, const char *method,
                             const char *req_buf, int fd, const struct stat *st,
                             const char *mime, const char *extra_headers);
// The same for bytes in memory (the web UI's embedded copy): st gives the
// size and Last-Modified, mem the st_size bytes.
static int MediaSendMemory(int client_fd, Arena *arena, const char *method,
                           const char *req_buf, const uint8_t *mem,
                           const struct stat *st, const char *mime,
                           const char *extra_headers);

#ifdef LCARS_MEDIA_IMPLEMENTATION

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/sendfile.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/wait.h>
#include <time.h>

extern char **environ;

static void MediaCacheAdmit(const char *rel);

// Ceiling on one upload. Well above a few minutes of 4K phone video, and kept
// below INT_MAX because the router's leftover-bytes arithmetic is int.
#define MEDIA_MAX_BYTES (1024LL * 1024 * 1024)
// How much of the body is carried per recv/write. Taken from the connection
// arena, which is otherwise idle during an upload.
#define MEDIA_CHUNK_BYTES (256 * 1024)
// The root when LCARS_MEDIA_ROOT is unset: this directory under the data
// directory, made absolute and put into the environment at start
// (MediaDefaultRoot), so ffmpeg, claude and report.py see the same one. It
// was a NAS mount compiled in until 0.269.2.
#define MEDIA_DEFAULT_DIR "media"
// Subdirectory of the root that holds everything this server writes, and the
// prefix of every stored path. It must already exist: an unmounted NAS
// leaves an empty mount point behind, and writing into *that* would fill
// the VPS's own disk with files the NAS never sees.
#define MEDIA_SUBDIR "media"
// Ceiling on one ffmpeg run. Minutes of speech convert in about a second and
// a video is only ever remuxed (copied, never re-encoded), which is bound by
// the NAS's throughput; this only exists so a wedged ffmpeg cannot hold the
// connection.
#define MEDIA_TRANSCODE_TIMEOUT_SECONDS 120
// What /media/ maps extensions to Content-Types from - HandleMediaFile now,
// tailscaled's Go file server before it, and the files were named for that
// (see ResolveFileType): an extension this server keeps is one with a
// known, inert type.
#define MEDIA_MIME_TYPES_PATH "/etc/mime.types"
// The extension a file is stored under when its own cannot be trusted to be
// served inertly; mime.types maps it to application/octet-stream.
#define MEDIA_OPAQUE_EXT "bin"
#define MEDIA_OPAQUE_MIME "application/octet-stream"
// Below <root>/media, so that attaching a staged tape is a rename on the same
// filesystem rather than a copy across the NFS mount.
#define MEDIA_TAPE_DIR ".tapes"
// report.py's SLUG_MAX, for the chat's files (CHAT_MEDIA_DIR, lcars_chat.h)
#define CHAT_MEDIA_SLUG_MAX 48
#define MEDIA_TAPE_TOKEN_MIN 16
#define MEDIA_TAPE_TOKEN_MAX 64

// Content types this server will store, with the extension each is saved
// under. The extension matters more than it looks: /media/ picks the
// Content-Type it answers with from it, and Safari will not play a video
// served as application/octet-stream. (HandleMediaFile looks here first,
// then in /etc/mime.types, as tailscaled did when it served them - which is
// why audio/webm is saved as .webm, not .weba: mime.types knows only the
// former, as video/webm, which an <audio> plays happily.)
typedef struct MediaType {
  const char *mime;
  const char *ext;
} MediaType;

static const MediaType g_media_types[] = {
    {"image/jpeg", "jpg"},       {"image/png", "png"},
    {"image/heic", "heic"},      {"image/heif", "heif"},
    {"image/webp", "webp"},      {"image/gif", "gif"},
    {"image/avif", "avif"},      {"video/mp4", "mp4"},
    {"video/quicktime", "mov"},  {"video/webm", "webm"},
    {"video/x-matroska", "mkv"}, {"audio/mp4", "m4a"},
    {"audio/x-m4a", "m4a"},      {"audio/aac", "aac"},
    {"audio/mpeg", "mp3"},       {"audio/ogg", "ogg"},
    {"audio/wav", "wav"},        {"audio/x-wav", "wav"},
    {"audio/webm", "webm"},      {"audio/flac", "flac"},
};
#define MEDIA_TYPE_COUNT (sizeof(g_media_types) / sizeof(g_media_types[0]))

static const char *MediaRoot(void) {
  const char *root = getenv("LCARS_MEDIA_ROOT");
  // Only unset if MediaDefaultRoot could not resolve the data directory:
  // relative, then, to the working directory, which is the data directory
  // unless --data or LCARS_DATA_DIR moved it.
  return (root && root[0]) ? root : MEDIA_DEFAULT_DIR;
}

// LCARS_MEDIA_ROOT unset (the environment and lcars.env both read): sets it
// to <data dir>/media, absolute. A setenv, so main calls it before any thread
// exists. The directory is not made: an absent <root>/media already reads as
// "not mounted" (MediaCheckMounted), and `lcars init` makes both.
static void MediaDefaultRoot(const char *data_dir) {
  assert(data_dir != NULL);
  const char *have = getenv("LCARS_MEDIA_ROOT");
  if (have != NULL && have[0] != '\0') {
    printf("Media: LCARS_MEDIA_ROOT=%s\n", have);
    return;
  }
  char dir[PATH_MAX], root[PATH_MAX + 16];
  if (realpath(data_dir, dir) == NULL) {
    printf("Media: cannot resolve the data directory '%s' (%s); the root is "
           "./" MEDIA_DEFAULT_DIR "\n",
           data_dir, strerror(errno));
    return;
  }
  snprintf(root, sizeof(root), "%s/" MEDIA_DEFAULT_DIR, dir);
  setenv("LCARS_MEDIA_ROOT", root, 1);
  printf("Media: %s (the default; LCARS_MEDIA_ROOT moves it)\n", root);
}

static bool MatchMediaPath(const char *path, int *out_entry_id,
                           int *out_media_id) {
  assert(path != NULL);
  assert(out_entry_id != NULL && out_media_id != NULL);

  const char *prefix = "/entries/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *p = path + prefix_len;
  char *end;
  long entry_id = strtol(p, &end, 10);
  if (end == p || entry_id <= 0 || entry_id > INT_MAX) {
    return false;
  }
  if (strncmp(end, "/media", 6) != 0) {
    return false;
  }
  p = end + 6;
  long media_id = 0;
  if (*p == '/' && p[1] >= '0' && p[1] <= '9') {
    media_id = strtol(p + 1, &end, 10);
    if (media_id <= 0 || media_id > INT_MAX) {
      return false;
    }
    p = end;
  }
  if (*p == '/') {
    p++;
  }
  if (*p != '\0') {
    return false;
  }
  *out_entry_id = (int)entry_id;
  *out_media_id = (int)media_id;
  return true;
}

static bool EnsureMediaTable(sqlite3 *db) {
  assert(db != NULL);
  const char *sql =
      "CREATE TABLE IF NOT EXISTS entry_media ("
      "id INTEGER PRIMARY KEY AUTOINCREMENT,"
      "entry_id INTEGER NOT NULL,"
      "path TEXT NOT NULL,"
      "mime TEXT NOT NULL DEFAULT '',"
      "bytes INTEGER NOT NULL DEFAULT 0,"
      "name TEXT NOT NULL DEFAULT '',"
      "created_at_utc TEXT NOT NULL,"
      "deleted INTEGER NOT NULL DEFAULT 0);"
      "CREATE INDEX IF NOT EXISTS entry_media_entry ON entry_media(entry_id);";
  char *err = NULL;
  if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
    printf("Media: cannot create entry_media: %s\n", err ? err : "?");
    sqlite3_free(err);
    return false;
  }
  return true;
}

// The stored type for a request: its Content-Type if that is one of ours,
// else whatever the original filename's extension says (Safari hands HEIC
// and some recordings over with an empty or octet-stream type). NULL means
// "not a photo, video or recording": ResolveFileType decides the rest.
static const MediaType *ResolveMediaType(const char *content_type,
                                         const char *name) {
  assert(content_type != NULL && name != NULL);
  for (size_t i = 0; i < MEDIA_TYPE_COUNT; i++) {
    if (strcasecmp(content_type, g_media_types[i].mime) == 0) {
      return &g_media_types[i];
    }
  }
  const char *dot = strrchr(name, '.');
  if (dot && dot[1]) {
    const char *ext = dot + 1;
    // A few spellings that are not the canonical extension above.
    if (strcasecmp(ext, "jpeg") == 0) {
      ext = "jpg";
    }
    for (size_t i = 0; i < MEDIA_TYPE_COUNT; i++) {
      if (strcasecmp(ext, g_media_types[i].ext) == 0) {
        return &g_media_types[i];
      }
    }
  }
  return NULL;
}

// True for a Content-Type a browser would render as an active document
// (running its scripts) when navigated to: HTML, XHTML, SVG and every other
// XML type, XSLT, JavaScript. Exact matches and suffixes rather than a
// substring search, because "openxmlformats" is in every .docx's type.
static bool MediaTypeIsActive(const char *mime) {
  assert(mime != NULL);
  static const char *const exact[] = {
      "text/html",
      "application/xhtml+xml",
      "text/xml",
      "application/xml",
      "text/xsl",
      "application/xslt+xml",
      "text/javascript",
      "application/javascript",
      "application/ecmascript",
      "text/ecmascript",
      "application/x-javascript",
  };
  for (size_t i = 0; i < sizeof(exact) / sizeof(exact[0]); i++) {
    if (strcasecmp(mime, exact[i]) == 0) {
      return true;
    }
  }
  size_t len = strlen(mime);
  return len >= 4 && strcasecmp(mime + len - 4, "+xml") == 0;
}

// One pass over mime.types: the type `ext` is served as (when `ext` is
// given), else the first extension listed for `mime`. Fills whichever of
// out_mime/out_ext is not the key and answers whether a line matched.
static bool MediaMimeTypesFind(const char *ext, const char *mime,
                               char *out_mime, size_t mime_cap, char *out_ext,
                               size_t ext_cap) {
  assert((ext != NULL) != (mime != NULL));
  assert(out_mime != NULL && mime_cap > 0 && out_ext != NULL && ext_cap > 0);
  FILE *f = fopen(MEDIA_MIME_TYPES_PATH, "r");
  if (!f) {
    return false;
  }
  bool found = false;
  char line[1024];
  while (!found && fgets(line, sizeof(line), f)) {
    if (line[0] == '#') {
      continue;
    }
    char *save = NULL;
    char *type = strtok_r(line, " \t\r\n", &save);
    if (!type) {
      continue;
    }
    if (mime && strcasecmp(type, mime) != 0) {
      continue;
    }
    for (char *tok = strtok_r(NULL, " \t\r\n", &save); tok;
         tok = strtok_r(NULL, " \t\r\n", &save)) {
      if (mime || strcasecmp(tok, ext) == 0) {
        snprintf(out_mime, mime_cap, "%s", type);
        snprintf(out_ext, ext_cap, "%s", mime ? tok : ext);
        found = true;
        break;
      }
    }
  }
  fclose(f);
  return found;
}

// The stored type and extension for a file that is not a photo, video or
// recording. Nothing is refused; what is chosen is the extension, because
// that decides what tailscale serves the file as - and /media/ shares an
// origin with /ui/, so a file served as text/html would run its scripts
// with the web UI's localStorage (the API password) in reach. A saved web
// page attached to an entry is not an attack, but it would behave like one.
//
// So the original extension is kept only when mime.types knows it (Go
// *sniffs* the bytes of an unknown one, and happily finds HTML or XML) and
// the type it maps to is inert. Anything else is stored as .bin, served as
// application/octet-stream - a download, which the web UI names after the
// original file. The row's mime is the type the stored file is served as,
// so what the UI draws for it matches what the URL will actually return.
static void ResolveFileType(const char *content_type, const char *name,
                            char *out_mime, size_t mime_cap, char *out_ext,
                            size_t ext_cap) {
  assert(content_type != NULL && name != NULL);
  assert(out_mime != NULL && mime_cap > 0 && out_ext != NULL && ext_cap > 0);

  // The name's extension, lowercased; only [a-z0-9], since it lands in a
  // path. "report.tar.gz" is "gz", which is what it is served as anyway.
  char ext[16] = {0};
  const char *dot = strrchr(name, '.');
  if (dot && dot[1]) {
    size_t len = strlen(dot + 1);
    bool clean = len < sizeof(ext);
    for (size_t i = 0; clean && i < len; i++) {
      char c = (char)tolower((unsigned char)dot[1 + i]);
      clean = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
      ext[i] = c;
    }
    if (!clean) {
      ext[0] = '\0';
    }
  }

  char mime[128];
  char found_ext[16];
  bool known = false;
  if (ext[0]) {
    known = MediaMimeTypesFind(ext, NULL, mime, sizeof(mime), found_ext,
                               sizeof(found_ext));
  } else if (content_type[0]) {
    // No usable name ("blob"): the client's type can still pick one.
    known = MediaMimeTypesFind(NULL, content_type, mime, sizeof(mime),
                               found_ext, sizeof(found_ext));
  }
  if (known && !MediaTypeIsActive(mime) &&
      strcmp(found_ext, MEDIA_OPAQUE_EXT) != 0) {
    snprintf(out_mime, mime_cap, "%s", mime);
    snprintf(out_ext, ext_cap, "%s", found_ext);
  } else {
    snprintf(out_mime, mime_cap, "%s", MEDIA_OPAQUE_MIME);
    snprintf(out_ext, ext_cap, "%s", MEDIA_OPAQUE_EXT);
  }
  assert(out_mime[0] != '\0' && out_ext[0] != '\0');
}

// mkdir -p for the date directories below <root>/media. `path` is modified
// in place and restored.
static bool MediaMakeDirs(char *path, size_t from) {
  assert(path != NULL);
  for (size_t i = from; path[i]; i++) {
    if (path[i] != '/') {
      continue;
    }
    path[i] = '\0';
    int rc = mkdir(path, 0775);
    int err = errno;
    path[i] = '/';
    if (rc != 0 && err != EEXIST) {
      return false;
    }
  }
  return true;
}

static uint32_t MediaRandom(void) {
  uint32_t r = 0;
  int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
  if (fd >= 0) {
    if (read(fd, &r, sizeof(r)) != (ssize_t)sizeof(r)) {
      r = 0;
    }
    close(fd);
  }
  // Only a uniqueness hint: O_EXCL below is what actually refuses a clash.
  return r ^ (uint32_t)time(NULL) ^ ((uint32_t)getpid() << 16);
}

// Audio that some player in this household cannot play gets a second copy
// as AAC in MP4 (.m4a), which every one of them can.
//
// The case that forced it: a MediaRecorder recording. Safari records
// AAC/MP4, but Chromium on Linux and Firefox can only record WebM/Opus, and
// the WebM a MediaRecorder writes has no duration and no cues - Safari will
// not play it at all (a spinner), and Chrome shows 0:00. So an iPhone could
// not play a recording made on the desktop. Ogg/Opus has the Safari half of
// the same problem. Everything else in g_media_types plays everywhere.
static bool MediaNeedsTranscode(const MediaType *type) {
  assert(type != NULL);
  return strcmp(type->mime, "audio/webm") == 0 ||
         strcmp(type->mime, "audio/ogg") == 0;
}

// What ffmpeg is asked to write, after `-i src [-t keep]`. Each ends in an
// explicit muxer (-f), because ".part" gives ffmpeg no extension to pick one
// from.
//
// Audio becomes AAC in MP4 (-f ipod: .m4a). -vn drops any cover-art/video
// stream a container carried. The copy remuxes the AAC as it is instead of
// re-encoding it: what an iPhone tape (already AAC) needs to be cut, and the
// difference between the link appearing at once and a long dictation being
// encoded all over again while the page waits.
static const char *const g_ffmpeg_m4a_copy[] = {
    "-vn", "-c:a", "copy", "-movflags", "+faststart", "-f", "ipod", NULL};
static const char *const g_ffmpeg_m4a_encode[] = {
    "-vn",       "-c:a",       "aac", "-b:a", "128k",
    "-movflags", "+faststart", "-f",  "ipod", NULL};
// Video is only ever remuxed, every stream copied: re-encoding minutes of
// video would hold the VPS's one core for longer than the recording took.
// Remuxing is still worth a second file. A cut is a -t, and a MediaRecorder's
// own output is written as it goes - WebM with no duration and no cues,
// fragmented MP4 - which ffmpeg rewrites whole, with the index at the front
// (+faststart), so it seeks.
static const char *const g_ffmpeg_mp4_copy[] = {
    "-c", "copy", "-movflags", "+faststart", "-f", "mp4", NULL};
static const char *const g_ffmpeg_mov_copy[] = {
    "-c", "copy", "-movflags", "+faststart", "-f", "mov", NULL};
static const char *const g_ffmpeg_webm_copy[] = {"-c", "copy", "-f", "webm",
                                                 NULL};
static const char *const g_ffmpeg_mkv_copy[] = {"-c", "copy", "-f", "matroska",
                                                NULL};

// Runs `ffmpeg -i src [-t keep] <out_args> dst` and waits for it. argv, not a
// shell: the paths are ours, but nothing about them needs quoting this way.
// The output goes to "<dst>.part" and is renamed on success, so a killed or
// failed ffmpeg never leaves a truncated file behind. $LCARS_FFMPEG_BIN
// overrides the binary; otherwise PATH (the systemd unit's reaches /usr/bin).
// keep_ms > 0 keeps only that much of the start (`-t`), which is how a
// dictation tape loses the spoken order that ended it; 0 keeps everything.
static bool MediaFfmpeg(const char *src, const char *dst, int keep_ms,
                        const char *const *out_args) {
  assert(src != NULL && dst != NULL && out_args != NULL);
  assert(keep_ms >= 0);

  char part[PATH_MAX];
  int n = snprintf(part, sizeof(part), "%s.part", dst);
  if (n < 0 || n >= (int)sizeof(part)) {
    return false;
  }
  const char *bin = getenv("LCARS_FFMPEG_BIN");
  if (!bin || !bin[0]) {
    bin = "ffmpeg";
  }
  char keep[32];
  snprintf(keep, sizeof(keep), "%d.%03d", keep_ms / 1000, keep_ms % 1000);
  char *argv[24];
  int argc = 0;
  argv[argc++] = (char *)bin;
  argv[argc++] = "-nostdin";
  argv[argc++] = "-loglevel";
  argv[argc++] = "error";
  argv[argc++] = "-y";
  argv[argc++] = "-i";
  argv[argc++] = (char *)src;
  if (keep_ms > 0) {
    // an output option, so after -i: stop writing at that point
    argv[argc++] = "-t";
    argv[argc++] = keep;
  }
  for (int i = 0; out_args[i]; i++) {
    assert(argc < 20);
    argv[argc++] = (char *)out_args[i];
  }
  argv[argc++] = part;
  argv[argc] = NULL;
  assert(argc < (int)(sizeof(argv) / sizeof(argv[0])));

  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  posix_spawn_file_actions_addopen(&fa, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
  posix_spawn_file_actions_addopen(&fa, STDOUT_FILENO, "/dev/null", O_WRONLY,
                                   0);
#if CHAT_HAVE_CLOSEFROM
  // The server's sockets are CLOEXEC; this keeps anything else left open
  // without it out of ffmpeg for as long as it runs.
  posix_spawn_file_actions_addclosefrom_np(&fa, STDERR_FILENO + 1);
#endif
  pid_t pid;
  int rc = posix_spawnp(&pid, bin, &fa, NULL, argv, environ);
  posix_spawn_file_actions_destroy(&fa);
  if (rc != 0) {
    printf("Media: cannot run %s: %s\n", bin, strerror(rc));
    return false;
  }

  int status = 0;
  bool exited = false;
  time_t deadline = time(NULL) + MEDIA_TRANSCODE_TIMEOUT_SECONDS;
  while (!exited) {
    pid_t w = waitpid(pid, &status, WNOHANG);
    if (w == pid) {
      exited = true;
    } else if (w < 0 && errno != EINTR) {
      break;
    } else if (time(NULL) > deadline) {
      kill(pid, SIGKILL);
      waitpid(pid, &status, 0);
      printf("Media: ffmpeg timed out on %s\n", src);
      unlink(part);
      return false;
    } else {
      // nanosleep, not usleep: the latter is not declared under -std=c11
      struct timespec ts = {0, 50 * 1000 * 1000};
      nanosleep(&ts, NULL);
    }
  }
  if (!exited || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    printf("Media: ffmpeg failed on %s\n", src);
    unlink(part);
    return false;
  }
  chmod(part, 0644);
  if (rename(part, dst) != 0) {
    unlink(part);
    return false;
  }
  return true;
}

// True when the file is a fragmented MP4 (a 'moof' box at the top level),
// which is what an iPhone's MediaRecorder writes: its header says the movie
// lasts 0 seconds, the samples are listed fragment by fragment, and iOS
// Safari's player shows "--:--" for it (and was seen not to play one at
// all). Remuxed
// (stream copy, +faststart), it is one ordinary MP4 with its duration up
// front. Only the box headers are read; a dozen reads of 8 bytes.
static bool MediaIsFragmentedMP4(const char *path) {
  assert(path != NULL);
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return false;
  }
  bool frag = false;
  long long off = 0;
  for (int i = 0; i < 64; i++) {
    unsigned char h[16];
    if (pread(fd, h, 8, (off_t)off) != 8) {
      break;
    }
    long long size =
        ((long long)h[0] << 24) | (h[1] << 16) | (h[2] << 8) | h[3];
    if (memcmp(h + 4, "moof", 4) == 0) {
      frag = true;
      break;
    }
    if (size == 1) {
      if (pread(fd, h + 8, 8, (off_t)(off + 8)) != 8) {
        break;
      }
      size = 0;
      for (int b = 8; b < 16; b++) {
        size = (size << 8) | h[b];
      }
    }
    if (size < 8) {
      break; // 0 means "to the end of the file": nothing after it
    }
    off += size;
  }
  close(fd);
  return frag;
}

static bool WriteAll(int fd, const char *buf, size_t len) {
  while (len > 0) {
    ssize_t n = write(fd, buf, len);
    if (n < 0 && errno == EINTR) {
      continue;
    }
    if (n <= 0) {
      return false;
    }
    buf += n;
    len -= (size_t)n;
  }
  return true;
}

// A tape token is chosen by the client and becomes a file name, so it is
// held to lowercase hex of a sane length: no '/', no '.', nothing to escape.
static bool MediaTapeTokenValid(const char *token) {
  assert(token != NULL);
  size_t len = strlen(token);
  if (len < MEDIA_TAPE_TOKEN_MIN || len > MEDIA_TAPE_TOKEN_MAX) {
    return false;
  }
  for (size_t i = 0; i < len; i++) {
    char c = token[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
      return false;
    }
  }
  return true;
}

static bool MatchTapePath(const char *path, char *out_token, size_t cap) {
  assert(path != NULL && out_token != NULL);
  assert(cap > MEDIA_TAPE_TOKEN_MAX);
  const char *prefix = "/tapes/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *token = path + prefix_len;
  if (strlen(token) >= cap || !MediaTapeTokenValid(token)) {
    return false;
  }
  snprintf(out_token, cap, "%s", token);
  return true;
}

// The mount check: <root>/media is created by hand on the NAS, so its
// absence means the share is not mounted (or LCARS_MEDIA_ROOT is wrong).
// Answers the 503 itself and returns its status; 0 means mounted.
static int MediaCheckMounted(int client_fd) {
  assert(client_fd >= 0);
  char dir[PATH_MAX];
  snprintf(dir, sizeof(dir), "%s/" MEDIA_SUBDIR, MediaRoot());
  struct stat sb;
  if (stat(dir, &sb) == 0 && S_ISDIR(sb.st_mode)) {
    return 0;
  }
  printf("Media: %s is missing - is the NAS mounted?\n", dir);
  return SendJSONError(client_fd, 503,
                       "Media store unavailable (%s not mounted?)", dir);
}

// "<root>/media/.tapes/<token>"; false when that does not fit in `out`.
static bool MediaTapePath(const char *token, char *out, size_t cap) {
  assert(token != NULL && out != NULL && cap > 0);
  int n = snprintf(out, cap, "%s/" MEDIA_SUBDIR "/" MEDIA_TAPE_DIR "/%s",
                   MediaRoot(), token);
  return n > 0 && n < (int)cap;
}

// POST /tapes/<token>?off=<bytes> - one slice of a recording still under way.
//
// The web UI's recordings (dictation's tape, the Record button) used to be
// uploaded whole once they stopped, so the longer the recording, the longer
// the wait before it was attached - and the page had to stay open for all of
// it. Now each second is sent as it is made, and the stop costs one last
// slice and a body-less POST /entries/<id>/media?tape=<token>, which renames
// the staged file into place and goes on exactly as an upload would (cut,
// transcode, row). The staging does not name an entry, so a recording into
// an entry that has not been saved yet streams all the same.
//
// `off` is where the slice starts, and has to be the staged size or below:
// a slice resent after a lost answer overwrites itself (the file is cut back
// to `off` first), and a gap is a 409 carrying the size the server has, so
// the client can resend from there. The answer is the new size. A tape that
// is never attached stays in .tapes on the NAS; nothing here removes it.
static int HandleTapeAppend(int client_fd, const char *token, const char *query,
                            const char *body, int body_len) {
  assert(client_fd >= 0);
  assert(token != NULL && query != NULL && body != NULL);
  assert(body_len >= 0);
  assert(MediaTapeTokenValid(token));

  int off = 0;
  bool off_ok;
  if (!query_get_int(query, "off", &off, &off_ok) || !off_ok || off < 0) {
    return SendJSONError(client_fd, 400,
                         "off must be the byte offset of this slice");
  }
  if ((long long)off + body_len > MEDIA_MAX_BYTES) {
    return SendJSONError(client_fd, 413, "Tape exceeds %lld bytes",
                         MEDIA_MAX_BYTES);
  }
  int mounted = MediaCheckMounted(client_fd);
  if (mounted != 0) {
    return mounted;
  }
  char path[PATH_MAX];
  if (!MediaTapePath(token, path, sizeof(path))) {
    return SendJSONError(client_fd, 500, "LCARS_MEDIA_ROOT is too long");
  }
  if (!MediaMakeDirs(path, strlen(MediaRoot()) + 1)) {
    return SendJSONError(client_fd, 500, "Cannot create " MEDIA_TAPE_DIR ": %s",
                         strerror(errno));
  }

  int fd = open(path, O_WRONLY | O_CREAT | O_CLOEXEC, 0644);
  if (fd < 0) {
    return SendJSONError(client_fd, 500, "Cannot open tape: %s",
                         strerror(errno));
  }
  struct stat st;
  if (fstat(fd, &st) != 0) {
    close(fd);
    return SendJSONError(client_fd, 500, "Cannot stat tape: %s",
                         strerror(errno));
  }
  if ((long long)off > (long long)st.st_size) {
    close(fd);
    char resp[128];
    int n = snprintf(resp, sizeof(resp),
                     "{\"error\":\"Gap before this slice\",\"status\":409,"
                     "\"size\":%lld}",
                     (long long)st.st_size);
    assert(n > 0 && n < (int)sizeof(resp));
    return SendJSON(client_fd, 409, resp, (size_t)n);
  }
  bool ok = true;
  if ((long long)off < (long long)st.st_size && ftruncate(fd, off) != 0) {
    ok = false;
  }
  if (ok && lseek(fd, off, SEEK_SET) != (off_t)off) {
    ok = false;
  }
  if (ok && body_len > 0) {
    ok = WriteAll(fd, body, (size_t)body_len);
  }
  // close() is where NFS reports a refused write, as in the upload above.
  if (close(fd) != 0) {
    ok = false;
  }
  if (!ok) {
    return SendJSONError(client_fd, 500, "Cannot write tape: %s",
                         strerror(errno));
  }
  char resp[64];
  int n = snprintf(resp, sizeof(resp), "{\"size\":%lld}",
                   (long long)off + body_len);
  assert(n > 0 && n < (int)sizeof(resp));
  return SendJSON(client_fd, 200, resp, (size_t)n);
}

static void AppendMediaJSON(JSONBuf *b, sqlite3_stmt *stmt) {
  assert(b != NULL && stmt != NULL);
  jsonbuf_appendf(b, "{\"id\":%d,\"entry_id\":%d,\"path\":",
                  sqlite3_column_int(stmt, 0), sqlite3_column_int(stmt, 1));
  jsonbuf_append_json_string(b, (const char *)sqlite3_column_text(stmt, 2));
  jsonbuf_append(b, ",\"mime\":");
  jsonbuf_append_json_string(b, (const char *)sqlite3_column_text(stmt, 3));
  jsonbuf_appendf(
      b, ",\"bytes\":%lld,\"name\":", (long long)sqlite3_column_int64(stmt, 4));
  jsonbuf_append_json_string(b, (const char *)sqlite3_column_text(stmt, 5));
  jsonbuf_append(b, ",\"created_at_utc\":");
  jsonbuf_append_json_string(b, (const char *)sqlite3_column_text(stmt, 6));
  jsonbuf_append(b, "}");
}

#define MEDIA_COLUMNS "id, entry_id, path, mime, bytes, name, created_at_utc"

// Streams an upload's body into `fd` and closes it: what arrived with the
// headers (`buffered` bytes at body_start) first, then the socket, a chunk
// at a time from the connection arena, until `content_len`. False when the
// peer went or a write failed (*written says how far it got); the caller
// removes the partial file. Shared by the entries' and the chat's uploads.
static bool MediaReceiveBody(int client_fd, Arena *arena, int fd,
                             const char *body_start, int buffered,
                             long long content_len, long long *written) {
  assert(client_fd >= 0 && fd >= 0);
  assert(arena_valid(arena));
  assert(body_start != NULL && written != NULL);
  assert(content_len > 0);
  bool ok = true;
  *written = 0;
  if (buffered > content_len) {
    buffered = (int)content_len;
  }
  if (buffered > 0) {
    ok = WriteAll(fd, body_start, (size_t)buffered);
    *written = buffered;
  }
  char *chunk = (char *)arena_alloc(arena, MEDIA_CHUNK_BYTES);
  while (ok && *written < content_len) {
    long long want = content_len - *written;
    if (want > MEDIA_CHUNK_BYTES) {
      want = MEDIA_CHUNK_BYTES;
    }
    ssize_t n = recv(client_fd, chunk, (size_t)want, 0);
    if (n < 0 && errno == EINTR) {
      continue;
    }
    if (n <= 0) {
      // Peer gone or silent past HTTP_IO_TIMEOUT_SECONDS: a partial file.
      ok = false;
      break;
    }
    if (!WriteAll(fd, chunk, (size_t)n)) {
      ok = false;
      break;
    }
    *written += n;
  }
  assert(*written <= content_len);
  // close() is where NFS reports a write the server refused (quota, a full
  // volume), so its result counts as much as write()'s.
  if (close(fd) != 0) {
    ok = false;
  }
  return ok && *written == content_len;
}

// The request's Content-Type without parameters ("image/png"), or "".
static void MediaRequestType(const char *req_buf, char *out, size_t cap) {
  assert(req_buf != NULL && out != NULL && cap > 0);
  out[0] = '\0';
  const char *ct_val = find_header_value(req_buf, "Content-Type:");
  if (ct_val) {
    size_t len = 0;
    while (ct_val[len] && ct_val[len] != '\r' && ct_val[len] != ';' &&
           ct_val[len] != ' ' && len < cap - 1) {
      out[len] = ct_val[len];
      len++;
    }
    out[len] = '\0';
  }
}

// POST /entries/<id>/media. Called before the body has been read: everything
// up to the first byte written to disk may answer without draining it, which
// leaves g_conn_keep_alive false (the router's invariant) so the connection
// closes rather than parsing a photo as the next request.
static int HandleMediaUpload(int client_fd, Arena *arena, int entry_id,
                             const char *query, const char *req_buf,
                             const char *body_start, int total_read,
                             int headers_len, bool client_keep_alive) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(entry_id > 0);
  assert(query != NULL && req_buf != NULL && body_start != NULL);
  assert(headers_len >= 0 && headers_len <= total_read);

  // ?tape=<token>: no body, the file is what POST /tapes/<token> staged.
  char tape[MEDIA_TAPE_TOKEN_MAX + 8] = {0};
  bool from_tape = query_get(query, "tape", tape, sizeof(tape));
  if (from_tape && !MediaTapeTokenValid(tape)) {
    return SendJSONError(client_fd, 400, "tape is not a tape token");
  }

  // The router has refused a Content-Length that does not parse; this is
  // the one route where it is meant to be large, past HTTP_MAX_BODY_BYTES.
  long long content_len = 0;
  if (!ParseContentLength(req_buf, &content_len)) {
    return SendJSONError(client_fd, 400, "Bad Content-Length");
  }
  if (find_header_value(req_buf, "Content-Length:") == NULL && !from_tape) {
    return SendJSONError(client_fd, 411, "Content-Length required");
  }
  // The router allows keep-alive up front only for a request with no body:
  // anything else is still on the wire until this handler drains it.
  assert(!g_conn_keep_alive || content_len == 0);
  if (from_tape && content_len != 0) {
    return SendJSONError(client_fd, 400, "A tape upload carries no body");
  }
  if (!from_tape && content_len == 0) {
    return SendJSONError(client_fd, 400, "Empty body; expected the file");
  }
  if (content_len > MEDIA_MAX_BYTES) {
    return SendJSONError(client_fd, 413, "File exceeds %lld bytes",
                         MEDIA_MAX_BYTES);
  }

  char content_type[128];
  MediaRequestType(req_buf, content_type, sizeof(content_type));
  char name[256] = {0};
  query_get(query, "name", name, sizeof(name));

  const MediaType *type = ResolveMediaType(content_type, name);
  // Anything else is a plain file. The buffers outlive every use of `type`.
  char file_mime[128];
  char file_ext[16];
  MediaType file_type = {file_mime, file_ext};
  if (!type) {
    ResolveFileType(content_type, name, file_mime, sizeof(file_mime), file_ext,
                    sizeof(file_ext));
    type = &file_type;
  }
  // ?cut=<ms>: keep only the first <ms> of an audio or video upload. The web
  // UI's dictation tape runs until the order that stops it has been *heard*,
  // which is after it was said, so the recording ends with "computer, stop
  // dictation"; the page knows (from the recogniser's word timings) where
  // that order began, and the cut drops everything from there. It is done
  // here because a browser can record but cannot trim. Video dictation is
  // cut the same way.
  int cut_ms = 0;
  {
    bool cut_ok;
    if (query_get_int(query, "cut", &cut_ms, &cut_ok) || !cut_ok) {
      if (!cut_ok || cut_ms <= 0) {
        return SendJSONError(client_fd, 400,
                             "cut must be a positive number of milliseconds");
      }
      if (strncmp(type->mime, "audio/", 6) != 0 &&
          strncmp(type->mime, "video/", 6) != 0) {
        return SendJSONError(client_fd, 400,
                             "cut applies only to audio and video");
      }
    }
  }

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (!EnsureMediaTable(db)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "Cannot create the media table");
  }
  {
    sqlite3_stmt *stmt;
    bool exists = false;
    if (sqlite3_prepare_v2(db, "SELECT 1 FROM entries WHERE id = ?1;", -1,
                           &stmt, NULL) == SQLITE_OK) {
      sqlite3_bind_int(stmt, 1, entry_id);
      exists = (sqlite3_step(stmt) == SQLITE_ROW);
      sqlite3_finalize(stmt);
    }
    if (!exists) {
      sqlite3_close(db);
      return SendJSONError(client_fd, 404, "No entry with id %d", entry_id);
    }
  }

  {
    int mounted = MediaCheckMounted(client_fd);
    if (mounted != 0) {
      sqlite3_close(db);
      return mounted;
    }
  }
  const char *root = MediaRoot();

  time_t now = time(NULL);
  struct tm tm_utc;
  gmtime_r(&now, &tm_utc);
  char rel[256];
  int rel_len = snprintf(
      rel, sizeof(rel), MEDIA_SUBDIR "/%04d/%02d/%02d/e%d-%02d%02d%02d-%08x.%s",
      tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, tm_utc.tm_mday, entry_id,
      tm_utc.tm_hour, tm_utc.tm_min, tm_utc.tm_sec, MediaRandom(), type->ext);
  assert(rel_len > 0 && rel_len < (int)sizeof(rel));
  char full[PATH_MAX];
  char part[PATH_MAX];
  snprintf(full, sizeof(full), "%s/%s", root, rel);
  int part_len = snprintf(part, sizeof(part), "%s.part", full);
  if (part_len < 0 || part_len >= (int)sizeof(part)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "LCARS_MEDIA_ROOT is too long");
  }
  if (!MediaMakeDirs(part, strlen(root) + 1)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "Cannot create directory for %s: %s",
                         rel, strerror(errno));
  }
  long long written = 0;
  if (from_tape) {
    // Nothing on the wire to drain: the connection may carry another request.
    g_conn_keep_alive = client_keep_alive;
    char staged[PATH_MAX];
    struct stat tst;
    if (!MediaTapePath(tape, staged, sizeof(staged)) ||
        stat(staged, &tst) != 0) {
      sqlite3_close(db);
      return SendJSONError(client_fd, 404, "No staged tape %s", tape);
    }
    if (tst.st_size <= 0 || tst.st_size > MEDIA_MAX_BYTES) {
      sqlite3_close(db);
      return SendJSONError(client_fd, 400, "Staged tape is %lld bytes",
                           (long long)tst.st_size);
    }
    // A second attach of the same token finds nothing here and 404s above
    // on its next try, so a tape can never become two rows.
    if (rename(staged, full) != 0) {
      int err = errno;
      sqlite3_close(db);
      return SendJSONError(client_fd, err == ENOENT ? 404 : 500,
                           "Cannot attach tape to %s: %s", rel, strerror(err));
    }
    written = (long long)tst.st_size;
  } else {
    // O_EXCL: two uploads can never land on one name, even across a clash of
    // the random suffix. 0644 so tailscaled (root, squashed to nobody by the
    // NAS) can read what this user wrote.
    int fd = open(part, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0644);
    if (fd < 0) {
      sqlite3_close(db);
      return SendJSONError(client_fd, 500, "Cannot create %s: %s", rel,
                           strerror(errno));
    }

    // From here on the body is consumed.
    bool ok = MediaReceiveBody(client_fd, arena, fd, body_start,
                               total_read - headers_len, content_len, &written);
    if (!ok || written != content_len) {
      unlink(part);
      sqlite3_close(db);
      return SendJSONError(client_fd, 400,
                           "Upload incomplete (%lld of %lld bytes)", written,
                           content_len);
    }
    // The wire is clean; the connection may carry another request.
    g_conn_keep_alive = client_keep_alive;

    if (rename(part, full) != 0) {
      int err = errno;
      unlink(part);
      sqlite3_close(db);
      return SendJSONError(client_fd, 500, "Cannot finalize %s: %s", rel,
                           strerror(err));
    }
  }

  // Audio some player cannot handle is recorded as its .m4a instead, and so
  // is audio with a cut; a video with a cut, or a WebM one (a
  // MediaRecorder's, with no cues), is recorded as its remux. So is any
  // fragmented MP4, audio or video - what an iPhone records, which iOS
  // Safari shows no duration for (MediaIsFragmentedMP4). The original
  // stays beside it on the NAS (the server never deletes a file); only the
  // row points elsewhere. A failed conversion is not a failed upload: the
  // original is stored and recorded as it came, playable at least where it
  // was made. A file that keeps its own extension needs another name than
  // its original: "-cut" or "-remux" before it.
  static const MediaType m4a = {"audio/mp4", "m4a"};
  bool is_video = strncmp(type->mime, "video/", 6) == 0;
  bool is_audio = strncmp(type->mime, "audio/", 6) == 0;
  bool fragmented =
      (strcmp(type->ext, "mp4") == 0 || strcmp(type->ext, "m4a") == 0 ||
       strcmp(type->ext, "mov") == 0) &&
      MediaIsFragmentedMP4(full);
  const MediaType *derived = NULL;
  if (is_video &&
      (cut_ms > 0 || fragmented || strcmp(type->ext, "webm") == 0)) {
    derived = type;
  } else if (is_audio &&
             (MediaNeedsTranscode(type) || cut_ms > 0 || fragmented)) {
    derived = &m4a;
  }
  const MediaType *stored = type;
  long long stored_bytes = written;
  // Set only once a conversion is attempted; the insert's failure paths
  // unlink it along with the original.
  char full_out[PATH_MAX] = {0};
  if (derived) {
    bool same_ext = strcmp(type->ext, derived->ext) == 0;
    char rel_out[sizeof(rel)];
    const char *dot = strrchr(rel, '.');
    assert(dot != NULL);
    int out_len =
        snprintf(rel_out, sizeof(rel_out), "%.*s%s.%s", (int)(dot - rel), rel,
                 !same_ext    ? ""
                 : cut_ms > 0 ? "-cut"
                              : "-remux",
                 derived->ext);
    assert(out_len > 0 && out_len < (int)sizeof(rel_out));
    snprintf(full_out, sizeof(full_out), "%s/%s", root, rel_out);
    bool made;
    if (is_video) {
      const char *const *args =
          strcmp(type->ext, "webm") == 0  ? g_ffmpeg_webm_copy
          : strcmp(type->ext, "mkv") == 0 ? g_ffmpeg_mkv_copy
          : strcmp(type->ext, "mov") == 0 ? g_ffmpeg_mov_copy
                                          : g_ffmpeg_mp4_copy;
      made = MediaFfmpeg(full, full_out, cut_ms, args);
    } else {
      // AAC that only needs cutting is remuxed; should that fail on some
      // recorder's MP4, the encode is still there to fall back on.
      made = (same_ext &&
              MediaFfmpeg(full, full_out, cut_ms, g_ffmpeg_m4a_copy)) ||
             MediaFfmpeg(full, full_out, cut_ms, g_ffmpeg_m4a_encode);
    }
    struct stat mst;
    if (made && stat(full_out, &mst) == 0) {
      printf("Media: converted %s -> %s\n", rel, rel_out);
      memcpy(rel, rel_out, sizeof(rel));
      stored = derived;
      stored_bytes = (long long)mst.st_size;
    }
  }

  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db,
      "INSERT INTO entry_media (entry_id, path, mime, bytes, name, "
      "created_at_utc) VALUES (?1, ?2, ?3, ?4, ?5, "
      "strftime('%Y-%m-%d %H:%M:%S', 'now', 'utc')) RETURNING " MEDIA_COLUMNS
      ";",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    unlink(full);
    if (full_out[0]) {
      unlink(full_out);
    }
    int status = SendJSONError(client_fd, 500, "Failed to prepare insert: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_int(stmt, 1, entry_id);
  sqlite3_bind_text(stmt, 2, rel, -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(stmt, 3, stored->mime, -1, SQLITE_STATIC);
  sqlite3_bind_int64(stmt, 4, stored_bytes);
  sqlite3_bind_text(stmt, 5, name, -1, SQLITE_TRANSIENT);
  int status;
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    JSONBuf out;
    jsonbuf_init(&out, arena);
    AppendMediaJSON(&out, stmt);
    sqlite3_finalize(stmt);
    printf("Media: stored %s (%lld bytes) for entry %d\n", rel, written,
           entry_id);
    // Into the VPS's cache while it is still in the page cache, so the
    // first play does not come from the NAS (see HandleMediaFile).
    MediaCacheAdmit(rel);
    // 201 through SendJSON: SendJSONBuf always answers 200.
    status = SendJSON(client_fd, 201, out.data, out.len);
  } else {
    // A file with no row is invisible, so it is removed rather than left
    // for nobody to find.
    sqlite3_finalize(stmt);
    unlink(full);
    if (full_out[0]) {
      unlink(full_out);
    }
    status = SendJSONError(client_fd, 500, "Failed to record media: %s",
                           sqlite3_errmsg(db));
  }
  sqlite3_close(db);
  return status;
}

// POST /chat/media?name=<filename> - a file for a chat message (Chats,
// "attachments"): the raw body, streamed as an entry's upload is, stored at
//
//   media/chat/YYYY/MM/<slug>-<id>.<ext>
//
// beside the reports, and answered {path, url, name, mime, bytes}. No row is
// written: the file belongs to a message, not to an entry, and the message
// names it - POST /chat, /ask and /engineer/<name>/say take the answer back
// as an `attachments` item, which is how the other side is told the file is
// there (lcars_chat.h, ChatAttachmentsParse). The extension is chosen as an
// entry's is (ResolveMediaType, then ResolveFileType), because the file is
// served the same way, by GET /media/<path>, cache and all; nothing is
// converted (a chat's photo is looked at, not played on every device).
// `url` is the path from the server's root, for the page to put its origin
// in front of; an engineer's message carries the full https URL
// (scripts/engineer.py).
//
// The cap is far below an entry's: what goes into a chat is a photo, a
// screenshot, a PDF or a log for the agent to read, and an agent reads a
// file whole. Called before the body is read, as HandleMediaUpload is, with
// the same keep-alive rule.
static int HandleChatMediaUpload(int client_fd, Arena *arena, const char *query,
                                 const char *req_buf, const char *body_start,
                                 int total_read, int headers_len,
                                 bool client_keep_alive) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(query != NULL && req_buf != NULL && body_start != NULL);
  assert(headers_len >= 0 && headers_len <= total_read);

  long long content_len = 0;
  if (!ParseContentLength(req_buf, &content_len)) {
    return SendJSONError(client_fd, 400, "Bad Content-Length");
  }
  if (find_header_value(req_buf, "Content-Length:") == NULL) {
    return SendJSONError(client_fd, 411, "Content-Length required");
  }
  assert(!g_conn_keep_alive || content_len == 0);
  if (content_len == 0) {
    return SendJSONError(client_fd, 400, "Empty body; expected the file");
  }
  if (content_len > CHAT_MEDIA_MAX_BYTES) {
    return SendJSONError(client_fd, 413, "File exceeds %lld bytes",
                         CHAT_MEDIA_MAX_BYTES);
  }

  char content_type[128];
  MediaRequestType(req_buf, content_type, sizeof(content_type));
  char name[256] = {0};
  query_get(query, "name", name, sizeof(name));
  char mime[128];
  char ext[16];
  const MediaType *type = ResolveMediaType(content_type, name);
  if (type) {
    snprintf(mime, sizeof(mime), "%s", type->mime);
    snprintf(ext, sizeof(ext), "%s", type->ext);
  } else {
    ResolveFileType(content_type, name, mime, sizeof(mime), ext, sizeof(ext));
  }

  // The slug is report.py's: the name without its extension, lowercased,
  // runs of anything but [a-z0-9] one '-', at most CHAT_MEDIA_SLUG_MAX.
  char slug[CHAT_MEDIA_SLUG_MAX + 1];
  {
    const char *dot = strrchr(name, '.');
    size_t end = dot && dot != name ? (size_t)(dot - name) : strlen(name);
    size_t n = 0;
    bool dash = false;
    for (size_t i = 0; i < end && n < CHAT_MEDIA_SLUG_MAX; i++) {
      char c = (char)tolower((unsigned char)name[i]);
      if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
        if (dash && n > 0) {
          if (n + 1 >= CHAT_MEDIA_SLUG_MAX) {
            break; // never ending on the '-'
          }
          slug[n++] = '-';
        }
        dash = false;
        slug[n++] = c;
      } else {
        dash = true;
      }
    }
    slug[n] = '\0';
    if (n == 0) {
      snprintf(slug, sizeof(slug), "file");
    }
  }

  {
    int mounted = MediaCheckMounted(client_fd);
    if (mounted != 0) {
      return mounted;
    }
  }
  const char *root = MediaRoot();
  time_t now = time(NULL);
  struct tm tm_utc;
  gmtime_r(&now, &tm_utc);
  char rel[192];
  int rel_len = snprintf(
      rel, sizeof(rel), CHAT_MEDIA_DIR "/%04d/%02d/%s-%08x.%s",
      tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, slug, MediaRandom(), ext);
  assert(rel_len > 0 && rel_len < (int)sizeof(rel));
  char full[PATH_MAX];
  char part[PATH_MAX];
  snprintf(full, sizeof(full), "%s/%s", root, rel);
  // a dot-name beside it, which /media/ never serves (MediaIsFilePath)
  const char *base = strrchr(full, '/');
  assert(base != NULL);
  int part_len = snprintf(part, sizeof(part), "%.*s/.%s.part",
                          (int)(base - full), full, base + 1);
  if (part_len < 0 || part_len >= (int)sizeof(part)) {
    return SendJSONError(client_fd, 500, "LCARS_MEDIA_ROOT is too long");
  }
  if (!MediaMakeDirs(part, strlen(root) + 1)) {
    return SendJSONError(client_fd, 500, "Cannot create directory for %s: %s",
                         rel, strerror(errno));
  }
  int fd = open(part, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0644);
  if (fd < 0) {
    return SendJSONError(client_fd, 500, "Cannot create %s: %s", rel,
                         strerror(errno));
  }
  long long written = 0;
  if (!MediaReceiveBody(client_fd, arena, fd, body_start,
                        total_read - headers_len, content_len, &written)) {
    unlink(part);
    return SendJSONError(client_fd, 400,
                         "Upload incomplete (%lld of %lld bytes)", written,
                         content_len);
  }
  g_conn_keep_alive = client_keep_alive;
  if (rename(part, full) != 0) {
    int err = errno;
    unlink(part);
    return SendJSONError(client_fd, 500, "Cannot finalize %s: %s", rel,
                         strerror(err));
  }
  printf("Media: stored %s (%lld bytes) for a chat\n", rel, written);
  MediaCacheAdmit(rel);

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "{\"path\":");
  jsonbuf_append_json_string(&out, rel);
  jsonbuf_appendf(&out, ",\"url\":\"/%s\",\"name\":", rel);
  // no name given ("blob"): the stored file's own
  jsonbuf_append_json_string(&out, name[0] ? name : strrchr(rel, '/') + 1);
  jsonbuf_append(&out, ",\"mime\":");
  jsonbuf_append_json_string(&out, mime);
  jsonbuf_appendf(&out, ",\"bytes\":%lld}", written);
  return SendJSON(client_fd, 201, out.data, out.len);
}

// GET /entries/<id>/media - the entry's live attachments, oldest first (the
// order they were captured in). With entry_id 0 it is GET /media: every live
// attachment of every live entry, which is what the web UI's media view
// draws. A row is a few hundred bytes against the 1MB connection arena, so a
// few thousand fit; past that SendJSONBuf answers 500 rather than a
// truncated array, and this will want paging.
static int HandleMediaList(int client_fd, Arena *arena, int entry_id) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(entry_id >= 0);

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (!EnsureMediaTable(db)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "Cannot create the media table");
  }
  // An attachment of a soft-deleted entry is left out of the whole list, as
  // GET /entries leaves the entry out; asked for by id it is what the client
  // named, as GET /entries/<id> answers a deleted row too.
  sqlite3_stmt *stmt;
  int rc = sqlite3_prepare_v2(
      db,
      entry_id > 0 ? "SELECT " MEDIA_COLUMNS " FROM entry_media "
                     "WHERE entry_id = ?1 AND deleted = 0 ORDER BY id;"
                   : "SELECT m.id, m.entry_id, m.path, m.mime, m.bytes, "
                     "m.name, m.created_at_utc FROM entry_media m "
                     "JOIN entries e ON e.id = m.entry_id "
                     "WHERE m.deleted = 0 AND e.deleted = 0 ORDER BY m.id;",
      -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare query: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  if (entry_id > 0) {
    sqlite3_bind_int(stmt, 1, entry_id);
  }
  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "[");
  int n = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    if (n++ > 0) {
      jsonbuf_append(&out, ",");
    }
    AppendMediaJSON(&out, stmt);
  }
  jsonbuf_append(&out, "]");
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return SendJSONBuf(client_fd, &out);
}

// DELETE /entries/<id>/media/<media id> - hides the attachment. The file
// stays on the NAS; `UPDATE entry_media SET deleted = 0` is the undo.
static int HandleMediaDelete(int client_fd, int entry_id, int media_id) {
  assert(client_fd >= 0);
  assert(entry_id > 0 && media_id > 0);

  sqlite3 *db;
  if (!OpenHTTPDB(client_fd, &db)) {
    return 500;
  }
  if (!EnsureMediaTable(db)) {
    sqlite3_close(db);
    return SendJSONError(client_fd, 500, "Cannot create the media table");
  }
  sqlite3_stmt *stmt;
  int rc =
      sqlite3_prepare_v2(db,
                         "UPDATE entry_media SET deleted = 1 "
                         "WHERE id = ?1 AND entry_id = ?2 AND deleted = 0;",
                         -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    int status = SendJSONError(client_fd, 500, "Failed to prepare delete: %s",
                               sqlite3_errmsg(db));
    sqlite3_close(db);
    return status;
  }
  sqlite3_bind_int(stmt, 1, media_id);
  sqlite3_bind_int(stmt, 2, entry_id);
  int status;
  if (sqlite3_step(stmt) != SQLITE_DONE) {
    status =
        SendJSONError(client_fd, 500, "Delete failed: %s", sqlite3_errmsg(db));
  } else if (sqlite3_changes(db) == 0) {
    status = SendJSONError(client_fd, 404, "No live media %d on entry %d",
                           media_id, entry_id);
  } else {
    char resp[96];
    int n = snprintf(resp, sizeof(resp), "{\"status\":\"deleted\",\"id\":%d}",
                     media_id);
    assert(n > 0 && n < (int)sizeof(resp));
    status = SendJSON(client_fd, 200, resp, (size_t)n);
  }
  sqlite3_finalize(stmt);
  sqlite3_close(db);
  return status;
}

// ---------------------------------------------------------------------------
// GET /media/<path> - the files themselves, with a cache on the VPS's disk.
//
// tailscale serve used to map /media/ straight onto the NFS mount, and every
// byte a phone played came from the NAS at home, up the home connection's
// uplink: ~1MB/s, measured cold. A 2.5Mbit/s video then buffers for a long
// while before it plays, and on 4G the bytes go up from home to the VPS and
// back out again. So /media/ is now served here, from a copy on the VPS's
// own disk when there is one ($LCARS_MEDIA_CACHE, default
// ~/.cache/lcars-media, laid out like <root>: <cache>/media/2026/...), and
// from the NAS when not. Every upload is copied in as it is stored, and a
// file served from the NAS is copied in beside the reply, so the second play
// of an old video is local too. The cache is LRU by atime and bounded by
// $LCARS_MEDIA_CACHE_MB (default 4096); its files are copies, so evicting one
// loses nothing. $LCARS_MEDIA_CACHE=0 turns it off.
//
// Unauthenticated from loopback, which is where tailscale serve's proxy
// connects from: an <img> or <video> cannot send the Basic-auth header, and
// the trust boundary is the tailnet, as it was when tailscaled served the
// mount itself. The API's port is also reachable from outside, so from
// anywhere else the route wants the password like every other.

#define MEDIA_CACHE_DEFAULT_MB 4096
// Room left on the VPS's disk after a copy; below it nothing is cached.
#define MEDIA_CACHE_DISK_RESERVE (2LL * 1024 * 1024 * 1024)
// Copies running at once. A miss is retried on the next request for it, so
// a gallery of photos that overflows this is cached over a few views.
#define MEDIA_CACHE_FILLS 4
// A phone that has buffered enough stops reading for a while; the send
// waits that long for it before giving up on the connection.
#define MEDIA_SEND_TIMEOUT_SECONDS 60

static bool MediaPeerIsLoopback(int client_fd) {
  assert(client_fd >= 0);
  struct sockaddr_storage ss;
  socklen_t len = sizeof(ss);
  if (getpeername(client_fd, (struct sockaddr *)&ss, &len) != 0) {
    return false;
  }
  if (ss.ss_family == AF_INET) {
    const struct sockaddr_in *in = (const struct sockaddr_in *)&ss;
    return (ntohl(in->sin_addr.s_addr) >> 24) == 127;
  }
  if (ss.ss_family == AF_INET6) {
    const struct sockaddr_in6 *in6 = (const struct sockaddr_in6 *)&ss;
    if (IN6_IS_ADDR_LOOPBACK(&in6->sin6_addr)) {
      return true;
    }
    return IN6_IS_ADDR_V4MAPPED(&in6->sin6_addr) &&
           in6->sin6_addr.s6_addr[12] == 127;
  }
  return false;
}

// "/media/<segments>", each segment [A-Za-z0-9_-.] and not starting with a
// dot - which is every name this server stores, and rules out "..", the
// staging directory (.tapes) and anything needing a percent-decode.
static bool MediaIsFilePath(const char *path) {
  assert(path != NULL);
  const char *prefix = "/" MEDIA_SUBDIR "/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len) != 0) {
    return false;
  }
  const char *p = path + prefix_len;
  if (*p == '\0') {
    return false;
  }
  bool seg_start = true;
  for (; *p; p++) {
    char c = *p;
    if (c == '/') {
      if (seg_start) {
        return false; // empty segment
      }
      seg_start = true;
      continue;
    }
    if (seg_start && c == '.') {
      return false;
    }
    seg_start = false;
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) {
      return false;
    }
  }
  return !seg_start; // no trailing slash: a directory is not served
}

// The cache directory, or NULL when caching is off. Resolved per call: the
// environment does not change, and this is a handful of bytes of work.
static bool MediaCacheDir(char *out, size_t cap) {
  assert(out != NULL && cap > 0);
  const char *dir = getenv("LCARS_MEDIA_CACHE");
  int n;
  if (dir && strcmp(dir, "0") == 0) {
    return false;
  }
  if (dir && dir[0]) {
    n = snprintf(out, cap, "%s", dir);
  } else {
    const char *home = getenv("HOME");
    if (!home || !home[0]) {
      return false;
    }
    n = snprintf(out, cap, "%s/.cache/lcars-media", home);
  }
  return n > 0 && n < (int)cap;
}

static long long MediaCacheCapBytes(void) {
  const char *mb = getenv("LCARS_MEDIA_CACHE_MB");
  long long v = (mb && mb[0]) ? atoll(mb) : MEDIA_CACHE_DEFAULT_MB;
  if (v <= 0) {
    v = MEDIA_CACHE_DEFAULT_MB;
  }
  return v * 1024 * 1024;
}

// Copies in flight, by relative path, so two requests for one uncached file
// start one copy. Also what bounds them to MEDIA_CACHE_FILLS.
static pthread_mutex_t g_media_fill_mutex = PTHREAD_MUTEX_INITIALIZER;
static char g_media_fill[MEDIA_CACHE_FILLS][256];
// One eviction pass at a time; a copy that finds one running skips its own.
static pthread_mutex_t g_media_evict_mutex = PTHREAD_MUTEX_INITIALIZER;

// Walks the cache: total bytes, and the least recently used file (by atime,
// which a cache hit sets explicitly - the mount may be noatime).
static void MediaCacheScan(char *dir, size_t cap, long long *total,
                           char *oldest, struct timespec *oldest_at) {
  assert(dir != NULL && total != NULL && oldest != NULL && oldest_at != NULL);
  DIR *d = opendir(dir);
  if (!d) {
    return;
  }
  size_t base = strlen(dir);
  struct dirent *de;
  while ((de = readdir(d)) != NULL) {
    if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) {
      continue;
    }
    int n = snprintf(dir + base, cap - base, "/%s", de->d_name);
    if (n <= 0 || (size_t)n >= cap - base) {
      continue;
    }
    struct stat st;
    if (lstat(dir, &st) == 0) {
      if (S_ISDIR(st.st_mode)) {
        MediaCacheScan(dir, cap, total, oldest, oldest_at);
      } else if (S_ISREG(st.st_mode)) {
        *total += (long long)st.st_size;
        if (oldest[0] == '\0' || st.st_atim.tv_sec < oldest_at->tv_sec ||
            (st.st_atim.tv_sec == oldest_at->tv_sec &&
             st.st_atim.tv_nsec < oldest_at->tv_nsec)) {
          snprintf(oldest, PATH_MAX, "%s", dir);
          *oldest_at = st.st_atim;
        }
      }
    }
    dir[base] = '\0';
  }
  closedir(d);
}

// Deletes least recently used copies until the cache fits its cap. A walk
// per deletion: the cache holds hundreds of files, not millions, and this
// runs on a copier's thread, never a request's.
static void MediaCacheEvict(const char *cache_dir) {
  assert(cache_dir != NULL);
  if (pthread_mutex_trylock(&g_media_evict_mutex) != 0) {
    return;
  }
  long long cap = MediaCacheCapBytes();
  for (int pass = 0; pass < 10000; pass++) {
    char dir[PATH_MAX];
    char oldest[PATH_MAX] = {0};
    struct timespec oldest_at = {0, 0};
    long long total = 0;
    snprintf(dir, sizeof(dir), "%s", cache_dir);
    MediaCacheScan(dir, sizeof(dir), &total, oldest, &oldest_at);
    if (total <= cap || oldest[0] == '\0') {
      break;
    }
    if (unlink(oldest) != 0) {
      break;
    }
  }
  pthread_mutex_unlock(&g_media_evict_mutex);
}

// The copier: <root>/<rel> to <cache>/<rel>.part, renamed into place, with
// the original's mtime so Last-Modified is the same whichever answered.
static void *MediaCacheFillThread(void *arg) {
  int slot = (int)(intptr_t)arg;
  assert(slot >= 0 && slot < MEDIA_CACHE_FILLS);
  const char *rel = g_media_fill[slot];
  char cache_dir[PATH_MAX];
  char src[PATH_MAX];
  char dst[PATH_MAX];
  char part[PATH_MAX];
  bool ok = MediaCacheDir(cache_dir, sizeof(cache_dir));
  int n1 = snprintf(src, sizeof(src), "%s/%s", MediaRoot(), rel);
  int n2 = snprintf(dst, sizeof(dst), "%s/%s", cache_dir, rel);
  int n3 = snprintf(part, sizeof(part), "%s.part", dst);
  ok = ok && n1 > 0 && n1 < (int)sizeof(src) && n2 > 0 &&
       n2 < (int)sizeof(dst) && n3 > 0 && n3 < (int)sizeof(part);
  int in = ok ? open(src, O_RDONLY | O_CLOEXEC) : -1;
  struct stat st;
  ok = in >= 0 && fstat(in, &st) == 0 && S_ISREG(st.st_mode);
  // Too big for the cache to hold a few of, or a disk too full to take it:
  // served from the NAS as before.
  struct statvfs vfs;
  // MediaMakeDirs from the first '/' on: the cache directory itself may not
  // exist yet, unlike <root>/media.
  if (ok) {
    ok = (long long)st.st_size <= MediaCacheCapBytes() / 4 &&
         MediaMakeDirs(part, 1) && statvfs(cache_dir, &vfs) == 0 &&
         (long long)vfs.f_bavail * (long long)vfs.f_frsize >
             (long long)st.st_size + MEDIA_CACHE_DISK_RESERVE;
  }
  int out =
      ok ? open(part, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644) : -1;
  ok = ok && out >= 0;
  long long done = 0;
  while (ok && done < (long long)st.st_size) {
    ssize_t n = sendfile(out, in, NULL, (size_t)(st.st_size - done));
    if (n < 0 && errno == EINTR) {
      continue;
    }
    if (n <= 0) {
      ok = false;
      break;
    }
    done += n;
  }
  if (out >= 0) {
    struct timespec times[2] = {{0, UTIME_NOW}, st.st_mtim};
    ok = ok && futimens(out, times) == 0;
    ok = (close(out) == 0) && ok;
    ok = ok && rename(part, dst) == 0;
    if (!ok) {
      unlink(part);
    }
  }
  if (in >= 0) {
    close(in);
  }
  if (ok) {
    printf("Media: cached %s (%lld bytes)\n", rel, (long long)st.st_size);
    MediaCacheEvict(cache_dir);
  }
  pthread_mutex_lock(&g_media_fill_mutex);
  g_media_fill[slot][0] = '\0';
  pthread_mutex_unlock(&g_media_fill_mutex);
  return NULL;
}

// Starts a copy of <root>/<rel> into the cache unless one is running for it
// or every slot is busy. Returns at once; the copy is a detached thread.
static void MediaCacheAdmit(const char *rel) {
  assert(rel != NULL);
  char cache_dir[PATH_MAX];
  if (!MediaCacheDir(cache_dir, sizeof(cache_dir)) ||
      strlen(rel) >= sizeof(g_media_fill[0])) {
    return;
  }
  int slot = -1;
  pthread_mutex_lock(&g_media_fill_mutex);
  for (int i = 0; i < MEDIA_CACHE_FILLS; i++) {
    if (strcmp(g_media_fill[i], rel) == 0) {
      slot = -1;
      break;
    }
    if (slot < 0 && g_media_fill[i][0] == '\0') {
      slot = i;
    }
  }
  if (slot >= 0) {
    snprintf(g_media_fill[slot], sizeof(g_media_fill[slot]), "%s", rel);
  }
  pthread_mutex_unlock(&g_media_fill_mutex);
  if (slot < 0) {
    return;
  }
  pthread_t tid;
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
  if (pthread_create(&tid, &attr, MediaCacheFillThread,
                     (void *)(intptr_t)slot) != 0) {
    pthread_mutex_lock(&g_media_fill_mutex);
    g_media_fill[slot][0] = '\0';
    pthread_mutex_unlock(&g_media_fill_mutex);
  }
  pthread_attr_destroy(&attr);
}

// "bytes=a-b", "bytes=a-" or "bytes=-n" against a file of `size` bytes.
// 1 = a satisfiable range in *first..*last, 0 = no usable Range header (the
// whole file; a multi-range is answered whole too, which RFC 9110 allows),
// -1 = unsatisfiable (416).
static int MediaParseRange(const char *val, long long size, long long *first,
                           long long *last) {
  assert(first != NULL && last != NULL);
  if (!val || strncmp(val, "bytes=", 6) != 0) {
    return 0;
  }
  const char *p = val + 6;
  const char *eol = strpbrk(p, "\r\n");
  const char *comma = strchr(p, ',');
  if (comma && (!eol || comma < eol)) {
    return 0;
  }
  char *end;
  if (*p == '-') {
    long long n = strtoll(p + 1, &end, 10);
    if (end == p + 1 || n <= 0) {
      return -1;
    }
    if (size == 0) {
      return -1;
    }
    *first = n >= size ? 0 : size - n;
    *last = size - 1;
    return 1;
  }
  long long a = strtoll(p, &end, 10);
  if (end == p || a < 0 || *end != '-') {
    return 0;
  }
  p = end + 1;
  long long b = size - 1;
  if (*p >= '0' && *p <= '9') {
    b = strtoll(p, &end, 10);
    if (b < a) {
      return 0;
    }
  }
  if (a >= size) {
    return -1;
  }
  *first = a;
  *last = b >= size ? size - 1 : b;
  return 1;
}

// ---- Reports ----------------------------------------------------------------
//
// A report is a file the captain is handed a link to - an HTML page, a PDF, a
// chart, a CSV - made by Number One or an engineer and published with
// scripts/report.py, which copies it to
//
//   <root>/media/reports/YYYY/MM/<slug>-<id>.<ext>
//
// beside a hidden sidecar, .<slug>-<id>.<ext>.json, holding its title. No row
// in the database: the file and its sidecar are the whole record, and the
// listing is a walk of the directories.
//
// Reports are meant to be read in the browser, not downloaded, so unlike an
// attachment (ResolveFileType) an HTML report keeps its type. That is safe
// only because of the header every report is served with,
// Content-Security-Policy: sandbox: the document gets an opaque origin, so
// its scripts cannot reach the web UI's localStorage (the API password) on
// the /ui origin it shares, nor read anything of that origin. allow-scripts
// lets a report draw its charts; allow-same-origin would undo the whole
// sandbox and must never be added, and allow-forms is left out (a form could
// post to the API with a browser's remembered Basic credentials).
//
// The one exception is PDF: Chromium will not start its PDF viewer in a
// sandboxed document (the page is blocked), and a PDF's own scripts run in
// the viewer's origin, never the page's. With nosniff it is served as
// exactly application/pdf, whatever its bytes say.
#define MEDIA_REPORTS_DIR "reports"
#define REPORT_CSP                                                             \
  "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox "         \
  "allow-downloads"
// Newest first, this many at most: a year of reports is dozens.
#define REPORT_LIST_MAX 500
// A sidecar is a title and a few names; anything bigger is not ours.
#define REPORT_SIDECAR_MAX 4096

static bool MediaIsReportPath(const char *path) {
  assert(path != NULL);
  const char *prefix = "/" MEDIA_SUBDIR "/" MEDIA_REPORTS_DIR "/";
  return MediaIsFilePath(path) && strncmp(path, prefix, strlen(prefix)) == 0;
}

// The type a report is shown as, by its extension; answers whether it gets
// the sandbox. Text of any sort - CSV, Markdown, a log - is text/plain,
// because text/csv and text/markdown are downloads in most browsers and the
// point is to read it. HTML is HTML. The rest is what mime.types says, an
// active type included (SVG, XML): the sandbox holds for those as for HTML.
static bool ReportResolveType(const char *rel, char *mime, size_t cap) {
  assert(rel != NULL && mime != NULL && cap > 0);
  static const char *const text[] = {
      "txt",  "text", "csv",  "tsv", "md",   "markdown", "log",
      "yaml", "yml",  "toml", "ini", "diff", "patch",
  };
  char ext[16] = "";
  const char *dot = strrchr(rel, '.');
  if (dot && strlen(dot + 1) < sizeof(ext)) {
    snprintf(ext, sizeof(ext), "%s", dot + 1);
    for (char *c = ext; *c; c++) {
      *c = (char)tolower((unsigned char)*c);
    }
  }
  for (size_t i = 0; i < sizeof(text) / sizeof(text[0]); i++) {
    if (strcmp(ext, text[i]) == 0) {
      snprintf(mime, cap, "text/plain; charset=utf-8");
      return true;
    }
  }
  if (strcmp(ext, "html") == 0 || strcmp(ext, "htm") == 0) {
    snprintf(mime, cap, "text/html; charset=utf-8");
    return true;
  }
  char found_ext[16];
  if (!ext[0] ||
      !MediaMimeTypesFind(ext, NULL, mime, cap, found_ext, sizeof(found_ext))) {
    snprintf(mime, cap, "%s", MEDIA_OPAQUE_MIME);
  }
  return strcasecmp(mime, "application/pdf") != 0;
}

typedef struct ReportItem {
  char rel[192]; // "media/reports/2026/10/slug-id.ext"
  long long bytes;
  time_t mtime;
} ReportItem;

static int ReportItemNewer(const void *a, const void *b) {
  const ReportItem *x = (const ReportItem *)a;
  const ReportItem *y = (const ReportItem *)b;
  if (x->mtime != y->mtime) {
    return x->mtime < y->mtime ? 1 : -1;
  }
  return strcmp(y->rel, x->rel);
}

// Adds the reports in reports/<year>/<month> to items: the regular files
// GET /media/ would serve (no dot-names, nothing needing a decode, no
// symlinks). Two fixed levels below reports/, so no recursion.
static void ReportScanMonth(const char *root_dir, const char *year,
                            const char *month, ReportItem *items, int *n) {
  char dir[PATH_MAX];
  int dn = snprintf(dir, sizeof(dir), "%s/%s/%s", root_dir, year, month);
  if (dn <= 0 || dn >= (int)sizeof(dir)) {
    return;
  }
  DIR *d = opendir(dir);
  if (!d) {
    return;
  }
  struct dirent *de;
  while (*n < REPORT_LIST_MAX && (de = readdir(d)) != NULL) {
    if (de->d_name[0] == '.') {
      continue; // the sidecars, a publish's .part, "." and ".."
    }
    ReportItem *it = &items[*n];
    int rn = snprintf(it->rel, sizeof(it->rel),
                      MEDIA_SUBDIR "/" MEDIA_REPORTS_DIR "/%s/%s/%s", year,
                      month, de->d_name);
    char url[sizeof(it->rel) + 1];
    snprintf(url, sizeof(url), "/%s", it->rel);
    char full[PATH_MAX];
    int fn = snprintf(full, sizeof(full), "%s/%s", dir, de->d_name);
    struct stat st;
    if (rn <= 0 || rn >= (int)sizeof(it->rel) || !MediaIsFilePath(url) ||
        fn <= 0 || fn >= (int)sizeof(full) || lstat(full, &st) != 0 ||
        !S_ISREG(st.st_mode)) {
      continue; // listed only if GET /media/<rel> would serve it
    }
    it->bytes = (long long)st.st_size;
    it->mtime = st.st_mtim.tv_sec;
    (*n)++;
  }
  closedir(d);
}

// The title from the sidecar beside <root>/<rel>, or NULL when there is none.
static const char *ReportTitle(Arena *arena, const char *rel) {
  const char *slash = strrchr(rel, '/');
  assert(slash != NULL);
  char path[PATH_MAX];
  int pn = snprintf(path, sizeof(path), "%s/%.*s/.%s.json", MediaRoot(),
                    (int)(slash - rel), rel, slash + 1);
  if (pn <= 0 || pn >= (int)sizeof(path)) {
    return NULL;
  }
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return NULL;
  }
  char buf[REPORT_SIDECAR_MAX];
  ssize_t got = read(fd, buf, sizeof(buf));
  close(fd);
  if (got <= 0 || got >= (ssize_t)sizeof(buf)) {
    return NULL;
  }
  JsonSpan obj = {buf, (size_t)got};
  JsonSpan v;
  const char *p = json_skip_ws(buf, buf + got);
  if (p >= buf + got || *p != '{' || !json_member(obj, "title", &v) ||
      v.len < 2 || v.data[0] != '"') {
    return NULL;
  }
  return json_span_string(arena, v);
}

// GET /reports: [{path, title, type, bytes, published_utc}], newest first.
// `path` is relative to the media root like an attachment's, so the page
// opens "<base>/<path>"; `type` is the extension.
static int HandleReportList(int client_fd, Arena *arena) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  int unmounted = MediaCheckMounted(client_fd);
  if (unmounted) {
    return unmounted;
  }
  char root_dir[PATH_MAX];
  int rn = snprintf(root_dir, sizeof(root_dir),
                    "%s/" MEDIA_SUBDIR "/" MEDIA_REPORTS_DIR, MediaRoot());
  if (rn <= 0 || rn >= (int)sizeof(root_dir)) {
    return SendJSONError(client_fd, 500, "LCARS_MEDIA_ROOT is too long");
  }
  ReportItem *items =
      (ReportItem *)arena_alloc(arena, sizeof(ReportItem) * REPORT_LIST_MAX);
  int n = 0;
  // Years and months are named by report.py: four and two digits. Anything
  // else in there is not walked.
  DIR *years = opendir(root_dir); // absent: nothing published yet
  struct dirent *y;
  while (years && n < REPORT_LIST_MAX && (y = readdir(years)) != NULL) {
    if (strlen(y->d_name) != 4 || strspn(y->d_name, "0123456789") != 4) {
      continue;
    }
    char ydir[PATH_MAX];
    int yn = snprintf(ydir, sizeof(ydir), "%s/%s", root_dir, y->d_name);
    DIR *months = yn > 0 && yn < (int)sizeof(ydir) ? opendir(ydir) : NULL;
    struct dirent *m;
    while (months && n < REPORT_LIST_MAX && (m = readdir(months)) != NULL) {
      if (strlen(m->d_name) == 2 && strspn(m->d_name, "0123456789") == 2) {
        ReportScanMonth(root_dir, y->d_name, m->d_name, items, &n);
      }
    }
    if (months) {
      closedir(months);
    }
  }
  if (years) {
    closedir(years);
  }
  qsort(items, (size_t)n, sizeof(ReportItem), ReportItemNewer);

  JSONBuf out;
  jsonbuf_init(&out, arena);
  jsonbuf_append(&out, "[");
  for (int i = 0; i < n; i++) {
    const char *name = strrchr(items[i].rel, '/') + 1;
    const char *dot = strrchr(name, '.');
    const char *title = ReportTitle(arena, items[i].rel);
    char when[32];
    struct tm tm_mod;
    gmtime_r(&items[i].mtime, &tm_mod);
    strftime(when, sizeof(when), "%Y-%m-%d %H:%M:%S", &tm_mod);
    jsonbuf_append(&out, i ? ",{\"path\":" : "{\"path\":");
    jsonbuf_append_json_string(&out, items[i].rel);
    jsonbuf_append(&out, ",\"title\":");
    jsonbuf_append_json_string(&out, title && title[0] ? title : name);
    jsonbuf_append(&out, ",\"type\":");
    jsonbuf_append_json_string(&out, dot ? dot + 1 : "");
    jsonbuf_appendf(&out, ",\"bytes\":%lld,\"published_utc\":\"%s\"}",
                    items[i].bytes, when);
  }
  jsonbuf_append(&out, "]");
  return SendJSONBuf(client_fd, &out);
}

// GET/HEAD /media/<path>: the cached copy when there is one, else the NAS's
// (and a copy is started). Range requests are what a <video> runs on.
static int HandleMediaFile(int client_fd, Arena *arena, const char *method,
                           const char *path, const char *req_buf) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL && req_buf != NULL);
  assert(MediaIsFilePath(path));

  const char *rel = path + 1; // "media/2026/..."
  char full[PATH_MAX];
  char cache_dir[PATH_MAX];
  int fd = -1;
  bool from_cache = false;
  if (MediaCacheDir(cache_dir, sizeof(cache_dir))) {
    int n = snprintf(full, sizeof(full), "%s/%s", cache_dir, rel);
    if (n > 0 && n < (int)sizeof(full)) {
      fd = open(full, O_RDONLY | O_CLOEXEC);
      from_cache = fd >= 0;
    }
  }
  if (fd < 0) {
    int n = snprintf(full, sizeof(full), "%s/%s", MediaRoot(), rel);
    if (n > 0 && n < (int)sizeof(full)) {
      fd = open(full, O_RDONLY | O_CLOEXEC);
    }
  }
  struct stat st;
  if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
    if (fd >= 0) {
      close(fd);
    }
    return SendJSONError(client_fd, 404, "No media file %s", rel);
  }
  if (from_cache) {
    // The LRU clock: atime, set by hand because the disk may be relatime.
    struct timespec times[2] = {{0, UTIME_NOW}, {0, UTIME_OMIT}};
    futimens(fd, times);
  } else {
    MediaCacheAdmit(rel);
  }

  // The type tailscaled used to answer with, from the same mime.types, with
  // two differences on purpose: an unknown or active type is served as an
  // opaque download rather than sniffed, and nosniff says so.
  char mime[128] = MEDIA_OPAQUE_MIME;
  const char *dot = strrchr(rel, '.');
  if (dot && dot[1]) {
    char ext[16];
    snprintf(ext, sizeof(ext), "%s", dot + 1);
    for (char *c = ext; *c; c++) {
      *c = (char)tolower((unsigned char)*c);
    }
    bool found = false;
    for (size_t i = 0; i < MEDIA_TYPE_COUNT && !found; i++) {
      if (strcmp(g_media_types[i].ext, ext) == 0) {
        snprintf(mime, sizeof(mime), "%s", g_media_types[i].mime);
        found = true;
      }
    }
    char found_ext[16];
    if (!found &&
        MediaMimeTypesFind(ext, NULL, mime, sizeof(mime), found_ext,
                           sizeof(found_ext)) &&
        MediaTypeIsActive(mime)) {
      snprintf(mime, sizeof(mime), "%s", MEDIA_OPAQUE_MIME);
    }
  }

  // A report is shown, not downloaded, and may be HTML: its own type and
  // the sandbox that makes that safe (see ReportResolveType).
  bool report = MediaIsReportPath(path);
  bool sandbox = false;
  if (report) {
    sandbox = ReportResolveType(rel, mime, sizeof(mime));
  }

  char extra[256];
  snprintf(extra, sizeof(extra), "X-LCARS-Media: %s\r\n%s",
           from_cache ? "cache" : "nas",
           sandbox ? "Content-Security-Policy: " REPORT_CSP "\r\n" : "");
  return MediaSendOpenFile(client_fd, arena, method, req_buf, fd, &st, mime,
                           extra);
}

// fd's file, or mem's bytes when fd is -1; fd is closed either way.
static int MediaSendBody(int client_fd, Arena *arena, const char *method,
                         const char *req_buf, int fd, const uint8_t *mem,
                         const struct stat *st, const char *mime,
                         const char *extra_headers) {
  assert(client_fd >= 0);
  assert((fd >= 0) != (mem != NULL));
  assert(arena_valid(arena));
  assert(method != NULL && req_buf != NULL && st != NULL);
  assert(mime != NULL && extra_headers != NULL);

  long long size = (long long)st->st_size;
  long long first = 0;
  long long last = size - 1;
  int range = MediaParseRange(find_header_value(req_buf, "Range:"), size,
                              &first, &last);
  char modified[64];
  struct tm tm_mod;
  gmtime_r(&st->st_mtim.tv_sec, &tm_mod);
  strftime(modified, sizeof(modified), "%a, %d %b %Y %H:%M:%S GMT", &tm_mod);
  char head[1024];
  int hn;
  int status;
  if (range < 0) {
    status = 416;
    hn = snprintf(head, sizeof(head),
                  "HTTP/1.1 416 Range Not Satisfiable\r\n"
                  "Content-Range: bytes */%lld\r\n"
                  "Content-Length: 0\r\n%s\r\n",
                  size, HTTPConnectionHeader());
    first = 0;
    last = -1;
  } else {
    status = range > 0 ? 206 : 200;
    char content_range[96] = "";
    if (range > 0) {
      snprintf(content_range, sizeof(content_range),
               "Content-Range: bytes %lld-%lld/%lld\r\n", first, last, size);
    }
    // The headers tailscaled's file server sent, plus nosniff and the
    // caller's (media: the cache/nas marker, and deliberately no
    // Cache-Control - iOS Safari has been seen to mishandle cached partial
    // responses for media).
    hn = snprintf(head, sizeof(head),
                  "HTTP/1.1 %d %s\r\n"
                  "Content-Type: %s\r\n"
                  "Content-Length: %lld\r\n%s"
                  "Accept-Ranges: bytes\r\n"
                  "Last-Modified: %s\r\n"
                  "X-Content-Type-Options: nosniff\r\n"
                  "%s%s\r\n",
                  status, http_status_text(status), mime, last - first + 1,
                  content_range, modified, extra_headers,
                  HTTPConnectionHeader());
  }
  assert(hn > 0 && hn < (int)sizeof(head));
  if (send(client_fd, head, (size_t)hn, MSG_NOSIGNAL) != hn) {
    if (fd >= 0) {
      close(fd);
    }
    g_conn_keep_alive = false;
    return status;
  }
  if (strcmp(method, "HEAD") == 0 || last < first) {
    if (fd >= 0) {
      close(fd);
    }
    return status;
  }

  // pread + send rather than sendfile: sendfile cannot be told MSG_NOSIGNAL,
  // and a phone that closes the player mid-video would SIGPIPE the process.
  struct timeval tv = {MEDIA_SEND_TIMEOUT_SECONDS, 0};
  setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  char *chunk = fd >= 0 ? (char *)arena_alloc(arena, MEDIA_CHUNK_BYTES) : NULL;
  long long off = first;
  bool ok = true;
  while (ok && off <= last) {
    long long want = last - off + 1;
    if (want > MEDIA_CHUNK_BYTES) {
      want = MEDIA_CHUNK_BYTES;
    }
    const char *buf = chunk;
    ssize_t got = (ssize_t)want;
    if (mem) {
      buf = (const char *)mem + off; // sent from where it lies: no copy
    } else {
      got = pread(fd, chunk, (size_t)want, (off_t)off);
    }
    if (got < 0 && errno == EINTR) {
      continue;
    }
    if (got <= 0) {
      ok = false; // the file shrank or the NAS went away: a short body
      break;
    }
    ssize_t sent = 0;
    while (sent < got) {
      ssize_t n =
          send(client_fd, buf + sent, (size_t)(got - sent), MSG_NOSIGNAL);
      if (n < 0 && errno == EINTR) {
        continue;
      }
      if (n <= 0) {
        ok = false; // the player hung up, or stopped reading for a minute
        break;
      }
      sent += n;
    }
    off += got;
  }
  tv.tv_sec = HTTP_IO_TIMEOUT_SECONDS;
  setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  if (fd >= 0) {
    close(fd);
  }
  if (!ok) {
    // A response cut short cannot be followed by another on this socket.
    g_conn_keep_alive = false;
  }
  return status;
}

static int MediaSendOpenFile(int client_fd, Arena *arena, const char *method,
                             const char *req_buf, int fd, const struct stat *st,
                             const char *mime, const char *extra_headers) {
  assert(fd >= 0);
  return MediaSendBody(client_fd, arena, method, req_buf, fd, NULL, st, mime,
                       extra_headers);
}

static int MediaSendMemory(int client_fd, Arena *arena, const char *method,
                           const char *req_buf, const uint8_t *mem,
                           const struct stat *st, const char *mime,
                           const char *extra_headers) {
  assert(mem != NULL);
  return MediaSendBody(client_fd, arena, method, req_buf, -1, mem, st, mime,
                       extra_headers);
}

#endif // LCARS_MEDIA_IMPLEMENTATION
#endif // LCARS_MEDIA_H
