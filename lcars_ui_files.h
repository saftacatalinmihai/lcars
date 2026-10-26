#ifndef LCARS_UI_FILES_H
#define LCARS_UI_FILES_H

// GET/HEAD /ui/... - the web UI (lcars-ui/), served by this server.
//
// tailscale serve used to map /ui/ straight onto the directory, which was
// enough while the page was one url. Now every view is a page of its own
// (/ui/tasks, /ui/entry/123, /ui/calendar/month/2026-10-01 - "pages" in
// lcars-ui/index.html), and a bookmark or a reload of one has to come back
// with index.html: there is no file called tasks. A static file server cannot
// say that, so tailscale serve proxies /ui/ here with the rest of the API.
// Offline the service worker answers those paths from its cache the same way;
// this is what makes the first visit and a cold reload work.
//
// The files are read from disk on every request ($LCARS_UI_DIR, default
// lcars-ui under the working directory - the unit's is ~/lcars), so saving a
// file under lcars-ui/ is still live on the next load with no build. A
// binary built with -DLCARS_EMBED_UI carries a copy of its own instead
// ("The embedded copy" below), used when LCARS_UI_DIR is not set; the VPS's
// builds do not embed.
//
// Auth is /media/'s rule: none from loopback (tailscale serve's proxy, whose
// trust boundary is the tailnet), the password from anywhere else.
//
// Text and meshes go out gzipped when the client offers it (UISendGzip
// below); everything else, a ranged request and a HEAD as they are on disk.
//
// A module of lcars_http.h, after lcars_media.h, whose loopback test and
// file sender it uses.

static bool UIIsPath(const char *path);
static void UIGzInit(void);
// Before the first connection: the embedded copy's index, and the start
// log's "UI:" line saying where /ui/ is served from.
static void UIInit(void);
static int HandleUIFile(int client_fd, Arena *arena, const char *method,
                        const char *path, const char *req_buf);

#ifdef LCARS_UI_FILES_IMPLEMENTATION

#include <fcntl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

// The first path segments that are pages rather than files. index.html's
// <head> script (LCARS_ROUTE_ARGS) is the list's other copy; a page added
// there and not here works from inside the app and offline, and 404s on a
// cold load.
static const char *const g_ui_pages[] = {
    "entry", "new",   "tasks",  "calendar", "day",       "stats",  "readings",
    "media", "graph", "stars",  "ask",      "engineers", "crew",   "thread",
    "trend", "help",  "course", "chats",    "reports",   "report", "shares",
};
#define UI_PAGE_COUNT (sizeof(g_ui_pages) / sizeof(g_ui_pages[0]))

typedef struct UIType {
  const char *ext;
  const char *mime;
  bool gzip; // worth compressing: measured on lcars-ui/ at level 5
} UIType;
static const UIType g_ui_types[] = {
    {"html", "text/html; charset=utf-8", true},
    {"js", "text/javascript; charset=utf-8", true},
    {"mjs", "text/javascript; charset=utf-8", true},
    {"css", "text/css; charset=utf-8", true},
    {"json", "application/json", true},
    {"webmanifest", "application/manifest+json", true},
    {"png", "image/png", false},
    {"jpg", "image/jpeg", false},
    {"jpeg", "image/jpeg", false},
    {"webp", "image/webp", false},
    {"gif", "image/gif", false},
    {"svg", "image/svg+xml", true},
    {"ico", "image/x-icon", false},
    {"glb", "model/gltf-binary", true},
    {"gltf", "model/gltf+json", true},
    {"bin", "application/octet-stream", false},
    // the deck's atlases (deck-model-assets.mjs): Basis data, already
    // compressed (ETC1S's own coding, UASTC's zstd)
    {"ktx2", "image/ktx2", false},
    {"wasm", "application/wasm", true},
    {"woff2", "font/woff2", false},
    {"txt", "text/plain; charset=utf-8", true},
    {"md", "text/markdown; charset=utf-8", true},
    {"mp3", "audio/mpeg", false},
    {"ogg", "audio/ogg", false},
    {"wav", "audio/wav", false},
};
#define UI_TYPE_COUNT (sizeof(g_ui_types) / sizeof(g_ui_types[0]))

// The paths answered with a redirect, and where to: a directory without its
// slash (relative urls in a page resolve against the directory, so the
// directory is what has to be in the address bar), and /manual, the user
// manual's short link (docs/design/manual.md), whose copy is lcars-ui/manual/.
// A query is dropped: none of these pages reads one.
static const char *UIRedirectFor(const char *path) {
  assert(path != NULL);
  size_t n = strcspn(path, "?#");
  static const struct {
    const char *from, *to;
  } moves[] = {
      {"/ui", "/ui/"},
      {"/manual", "/ui/manual/"},
      {"/manual/", "/ui/manual/"},
      {"/ui/manual", "/ui/manual/"},
  };
  for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
    if (strlen(moves[i].from) == n && strncmp(path, moves[i].from, n) == 0) {
      return moves[i].to;
    }
  }
  return NULL;
}

static bool UIIsPath(const char *path) {
  assert(path != NULL);
  return strcmp(path, "/ui") == 0 || strncmp(path, "/ui/", 4) == 0 ||
         UIRedirectFor(path) != NULL;
}

static const char *UIRoot(void) {
  const char *r = getenv("LCARS_UI_DIR");
  return r && r[0] ? r : "lcars-ui";
}

// What one answer is read from: a file on disk (fd), or an embedded file's
// bytes (mem, fd -1). st is the file's, or one made up for the embedded
// copy (UIEmbedOpen) whose identity and stamps key the gzip cache the same
// way. etag is the embedded file's content hash, NULL on disk.
typedef struct UISrc {
  int fd;
  const uint8_t *mem;
  struct stat st;
  const char *etag;
} UISrc;

static ssize_t UISrcRead(const UISrc *src, uint8_t *buf, size_t n, off_t pos) {
  assert(src != NULL && buf != NULL);
  if (src->mem == NULL) {
    return pread(src->fd, buf, n, pos);
  }
  if (pos >= src->st.st_size) {
    return 0;
  }
  size_t left = (size_t)(src->st.st_size - pos);
  size_t take = n < left ? n : left;
  memcpy(buf, src->mem + pos, take);
  return (ssize_t)take;
}

static void UISrcClose(UISrc *src) {
  assert(src != NULL);
  if (src->fd >= 0) {
    close(src->fd);
    src->fd = -1;
  }
}

// Nothing that climbs out of the root or names a hidden file: "..", ".git",
// empty segments, a backslash. rel is the path after "/ui/".
static bool UIRelIsSafe(const char *rel) {
  assert(rel != NULL);
  if (strchr(rel, '\\') || strstr(rel, "//")) {
    return false;
  }
  const char *seg = rel;
  while (*seg) {
    if (seg[0] == '.') {
      return false; // ".", "..", and every dot-name
    }
    const char *slash = strchr(seg, '/');
    if (!slash) {
      break;
    }
    seg = slash + 1;
  }
  return true;
}

static bool UIRelIsPage(const char *rel) {
  assert(rel != NULL);
  size_t n = strcspn(rel, "/");
  for (size_t i = 0; i < UI_PAGE_COUNT; i++) {
    if (strlen(g_ui_pages[i]) == n && strncmp(rel, g_ui_pages[i], n) == 0) {
      return true;
    }
  }
  return false;
}

static const UIType *UITypeFor(const char *file) {
  assert(file != NULL);
  const char *slash = strrchr(file, '/');
  const char *dot = strrchr(slash ? slash : file, '.');
  if (dot && dot[1]) {
    for (size_t i = 0; i < UI_TYPE_COUNT; i++) {
      if (strcasecmp(g_ui_types[i].ext, dot + 1) == 0) {
        return &g_ui_types[i];
      }
    }
  }
  return NULL;
}

static const char *UIMimeFor(const char *file) {
  const UIType *t = UITypeFor(file);
  return t ? t->mime : MEDIA_OPAQUE_MIME;
}

// ---------------------------------------------------------------------------
// gzip
// ---------------------------------------------------------------------------
//
// Nothing between the server and a phone compresses (tailscale serve passes
// the bytes through), and a deck boot fetches deck.html (~860KB), the three
// bundle (~900KB) and a dozen glbs; at level 5 html and js come to a third,
// the meshopt-packed glbs to ~56%. webp, png, woff2 and audio are compressed
// already and gain nothing (the `gzip` column of g_ui_types).
//
// A ranged request is always identity: index.html's first kilobyte is
// fetched with Range by the update check (updFetchVersion) and must be the
// file's own bytes with a 206, and a range of a gzip stream means nothing to
// a browser anyway. A HEAD is identity too (no body to save). Every answer
// carries Vary: Accept-Encoding, so no cache between keys one form for both.
// From disk there is no ETag (the embedded copy has one: below);
// Last-Modified is the file's in either form, and a 304 stays a 304.
//
// The cost: deflate at level 5 takes ~35ms for deck.html and ~100ms for
// index.html on the VPS, paid on every deck boot and every console load. So
// a big file's compressed form is kept in memory (the cache below) and sent
// with a Content-Length; a small one (under UI_GZ_CACHE_MIN_BYTES, well
// under a millisecond) is compressed as it is sent, chunked, through
// HTTPBodyStream.
//
// In memory rather than precompressed .gz files beside the sources: the
// files are edited live with no build, and a .gz is only as fresh as the
// last run of whatever wrote it - "newer than the source" by mtime is
// fooled by cp -p, a git checkout of an old file or a clock step. Here the
// key is the file's identity and stamps (device, inode, size, mtime and
// ctime to the nanosecond; ctime cannot be set from user space), read from
// the very fd whose bytes are compressed, so a saved file is a miss on its
// next request and a stale form is never sent. Nothing to deploy, nothing
// on disk to go wrong.
//
// The memory rule holds: one region of a fixed size, mapped once at startup
// (UIGzInit, $LCARS_UI_GZ_BYTES, default 16MB; 0 turns the cache off and
// every gzip is done per request), and bump-allocated. A changed file's old
// form is dead space until the region is full; then, when nobody is sending
// from it, the whole region starts over. If somebody is (a phone mid-way
// through index.html), the file is compressed per request this once.
// Fills are one at a time (the fill lock), which is what lets a fill
// reserve the space at the end of the region and keep only what it used;
// a second request for the same file waits for the first one's fill and
// then hits. Lookups and releases take only the table lock, briefly.

#define UI_GZ_CACHE_MIN_BYTES (32 * 1024)
#define UI_GZ_DEFAULT_BUDGET (16u * 1024u * 1024u)
#define UI_GZ_SLOTS 64

typedef struct UIGzEntry {
  dev_t dev;
  ino_t ino;
  off_t size;
  struct timespec mtime, ctime;
  size_t off, len; // the gzip bytes, in g_uigz.mem
  int refs;        // senders using off..off+len, and a fill in progress
  bool valid;      // looked up; false for a stale or half-filled form
} UIGzEntry;

static struct {
  pthread_mutex_t lock; // the table, used and refs
  pthread_mutex_t fill; // one compression into the region at a time
  uint8_t *mem;
  size_t cap, used;
  UIGzEntry e[UI_GZ_SLOTS];
} g_uigz = {.lock = PTHREAD_MUTEX_INITIALIZER,
            .fill = PTHREAD_MUTEX_INITIALIZER};

// Before the first connection: the region is never resized.
static void UIGzInit(void) {
  size_t cap = UI_GZ_DEFAULT_BUDGET;
  const char *env = getenv("LCARS_UI_GZ_BYTES");
  if (env && env[0]) {
    char *end = NULL;
    unsigned long long v = strtoull(env, &end, 10);
    cap = (end && *end == '\0') ? (size_t)v : UI_GZ_DEFAULT_BUDGET;
  }
  if (cap == 0) {
    return;
  }
  // Untouched pages cost nothing: the resident size is what has been filled.
  void *mem = mmap(NULL, cap, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
  if (mem == MAP_FAILED) {
    fprintf(stderr,
            "ui gzip: no %zu-byte cache (%s); compressing per "
            "request\n",
            cap, strerror(errno));
    return;
  }
  g_uigz.mem = (uint8_t *)mem;
  g_uigz.cap = cap;
}

static bool UIGzSameFile(const UIGzEntry *e, const struct stat *st) {
  assert(e != NULL && st != NULL);
  return e->dev == st->st_dev && e->ino == st->st_ino;
}

static bool UIGzSameStamps(const UIGzEntry *e, const struct stat *st) {
  assert(e != NULL && st != NULL);
  return e->size == st->st_size && e->mtime.tv_sec == st->st_mtim.tv_sec &&
         e->mtime.tv_nsec == st->st_mtim.tv_nsec &&
         e->ctime.tv_sec == st->st_ctim.tv_sec &&
         e->ctime.tv_nsec == st->st_ctim.tv_nsec;
}

// Whether the file still has the stamps it was opened with: an editor that
// saves in place (truncate, write) changes the bytes under a reader. The
// embedded copy never changes.
static bool UIFileUnchanged(const UISrc *src) {
  assert(src != NULL);
  if (src->mem) {
    return true;
  }
  const struct stat *st = &src->st;
  struct stat now;
  return fstat(src->fd, &now) == 0 && now.st_size == st->st_size &&
         now.st_mtim.tv_sec == st->st_mtim.tv_sec &&
         now.st_mtim.tv_nsec == st->st_mtim.tv_nsec &&
         now.st_ctim.tv_sec == st->st_ctim.tv_sec &&
         now.st_ctim.tv_nsec == st->st_ctim.tv_nsec;
}

// Under g_uigz.lock. The slot holding this file as it is now, with a
// reference taken, or -1; a form of an older version is retired.
static int UIGzFindLocked(const struct stat *st) {
  assert(st != NULL);
  for (int i = 0; i < UI_GZ_SLOTS; i++) {
    UIGzEntry *e = &g_uigz.e[i];
    if (!e->valid || !UIGzSameFile(e, st)) {
      continue;
    }
    if (UIGzSameStamps(e, st)) {
      e->refs++;
      return i;
    }
    e->valid = false;
  }
  return -1;
}

static void UIGzRelease(int slot) {
  assert(slot >= 0 && slot < UI_GZ_SLOTS);
  pthread_mutex_lock(&g_uigz.lock);
  assert(g_uigz.e[slot].refs > 0);
  g_uigz.e[slot].refs--;
  pthread_mutex_unlock(&g_uigz.lock);
}

// Under both locks. A free slot with `need` bytes at the end of the region,
// starting the region over if it must and may; -1 if neither.
static int UIGzReserveLocked(size_t need) {
  assert(need > 0);
  assert(g_uigz.mem != NULL && g_uigz.used <= g_uigz.cap);
  for (int pass = 0; pass < 2; pass++) {
    if (g_uigz.cap - g_uigz.used >= need) {
      for (int i = 0; i < UI_GZ_SLOTS; i++) {
        if (!g_uigz.e[i].valid && g_uigz.e[i].refs == 0) {
          return i;
        }
      }
    }
    if (pass == 1) {
      break;
    }
    for (int i = 0; i < UI_GZ_SLOTS; i++) {
      if (g_uigz.e[i].refs > 0) {
        return -1; // a sender is reading the region: not now
      }
    }
    memset(g_uigz.e, 0, sizeof(g_uigz.e));
    g_uigz.used = 0;
  }
  return -1;
}

// Compresses fd's file into the region and returns its slot with a
// reference taken, or -1 (no room, a read failed, the file changed while it
// was read): the caller then compresses as it sends. Its own frame holds
// zlib's arena, so the stack is only paid on a miss.
static int UIGzFill(Arena *arena, const UISrc *src) {
  assert(arena_valid(arena));
  assert(src != NULL);
  assert(g_uigz.mem != NULL);
  const struct stat *st = &src->st;
  pthread_mutex_lock(&g_uigz.fill);
  pthread_mutex_lock(&g_uigz.lock);
  int slot = UIGzFindLocked(st); // filled while this one waited
  pthread_mutex_unlock(&g_uigz.lock);
  if (slot >= 0) {
    pthread_mutex_unlock(&g_uigz.fill);
    return slot;
  }

  uint8_t zbuf[HTTP_GZIP_ZLIB_BYTES];
  Arena zarena;
  arena_init(&zarena, zbuf, sizeof(zbuf));
  z_stream z;
  memset(&z, 0, sizeof(z));
  z.zalloc = HTTPZAlloc;
  z.zfree = HTTPZFree;
  z.opaque = &zarena;
  if (deflateInit2(&z, HTTP_GZIP_LEVEL, Z_DEFLATED, 15 + 16, 8,
                   Z_DEFAULT_STRATEGY) != Z_OK) {
    pthread_mutex_unlock(&g_uigz.fill);
    return -1;
  }
  // The most deflate can produce for this input (gzip wrapper included),
  // reserved whole so the output never has to stop for room.
  size_t bound = (size_t)deflateBound(&z, (uLong)st->st_size);

  pthread_mutex_lock(&g_uigz.lock);
  slot = UIGzReserveLocked(bound);
  size_t off = g_uigz.used;
  if (slot >= 0) {
    g_uigz.e[slot].refs = 1; // held: not free, and not yet valid
  }
  pthread_mutex_unlock(&g_uigz.lock);
  if (slot < 0) {
    deflateEnd(&z);
    pthread_mutex_unlock(&g_uigz.fill);
    return -1;
  }

  ArenaMark mark = arena_mark(arena);
  uint8_t *chunk = (uint8_t *)arena_alloc(arena, MEDIA_CHUNK_BYTES);
  z.next_out = g_uigz.mem + off;
  z.avail_out = (uInt)bound;
  off_t pos = 0;
  bool ok = true;
  while (ok) {
    ssize_t got = UISrcRead(src, chunk, MEDIA_CHUNK_BYTES, pos);
    if (got < 0 && errno == EINTR) {
      continue;
    }
    if (got < 0) {
      ok = false;
      break;
    }
    pos += got;
    z.next_in = chunk;
    z.avail_in = (uInt)got;
    int rc = deflate(&z, got == 0 ? Z_FINISH : Z_NO_FLUSH);
    if (got == 0) {
      ok = rc == Z_STREAM_END;
      break;
    }
    ok = rc == Z_OK && z.avail_in == 0;
  }
  size_t len = (size_t)z.total_out;
  deflateEnd(&z);
  arena_restore(arena, mark);
  // Written in place while it was read: the bytes may be half of each.
  ok = ok && pos == st->st_size && UIFileUnchanged(src);

  pthread_mutex_lock(&g_uigz.lock);
  UIGzEntry *e = &g_uigz.e[slot];
  if (ok) {
    assert(g_uigz.used == off); // only a fill moves it, and fills are serial
    assert(len <= bound);
    e->dev = st->st_dev;
    e->ino = st->st_ino;
    e->size = st->st_size;
    e->mtime = st->st_mtim;
    e->ctime = st->st_ctim;
    e->off = off;
    e->len = len;
    e->valid = true; // refs stays 1: the caller's
    g_uigz.used = off + len;
  } else {
    e->refs = 0;
    slot = -1;
  }
  pthread_mutex_unlock(&g_uigz.lock);
  pthread_mutex_unlock(&g_uigz.fill);
  return slot;
}

// The headers both gzip forms share; `framing` is the Content-Length or
// Transfer-Encoding line, `validators` Last-Modified (and an ETag), each
// ending in CRLF.
static int UIGzHead(char *out, size_t cap, const char *mime,
                    const char *validators, const char *framing) {
  assert(out != NULL && cap > 0);
  assert(mime != NULL && validators != NULL && framing != NULL);
  int n = snprintf(out, cap,
                   "HTTP/1.1 200 OK\r\n"
                   "Content-Type: %s\r\n"
                   "Content-Encoding: gzip\r\n"
                   "Vary: Accept-Encoding\r\n"
                   "%s"
                   "%s"
                   "Cache-Control: no-cache\r\n"
                   "X-Content-Type-Options: nosniff\r\n"
                   "%s\r\n",
                   mime, framing, validators, HTTPConnectionHeader());
  assert(n > 0 && (size_t)n < cap);
  return n;
}

static bool UISendAll(int client_fd, const uint8_t *p, size_t n) {
  assert(client_fd >= 0);
  assert(p != NULL || n == 0);
  while (n > 0) {
    ssize_t sent = send(client_fd, p, n, MSG_NOSIGNAL);
    if (sent < 0 && errno == EINTR) {
      continue;
    }
    if (sent <= 0) {
      return false;
    }
    p += sent;
    n -= (size_t)sent;
  }
  return true;
}

// A cached form, with a Content-Length. Holds the slot's reference until
// the last byte is out, so the region is not started over beneath it.
static int UISendCached(int client_fd, int slot, const char *mime,
                        const char *validators) {
  assert(client_fd >= 0);
  assert(slot >= 0 && slot < UI_GZ_SLOTS);
  assert(mime != NULL && validators != NULL);
  const UIGzEntry *e = &g_uigz.e[slot]; // immutable while referenced
  char framing[64];
  snprintf(framing, sizeof(framing), "Content-Length: %zu\r\n", e->len);
  char head[1024];
  int hn = UIGzHead(head, sizeof(head), mime, validators, framing);
  struct timeval tv = {MEDIA_SEND_TIMEOUT_SECONDS, 0};
  setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  bool ok = UISendAll(client_fd, (const uint8_t *)head, (size_t)hn) &&
            UISendAll(client_fd, g_uigz.mem + e->off, e->len);
  tv.tv_sec = HTTP_IO_TIMEOUT_SECONDS;
  setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  UIGzRelease(slot);
  if (!ok) {
    g_conn_keep_alive = false;
  }
  return 200;
}

// Compressed as it is read and sent, chunked: a small file, or a big one the
// cache could not take this time.
static int UISendStreamed(int client_fd, Arena *arena, const UISrc *src,
                          const char *mime, const char *validators) {
  assert(client_fd >= 0 && src != NULL);
  assert(arena_valid(arena));
  assert(mime != NULL && validators != NULL);
  char extra[256];
  int n = snprintf(extra, sizeof(extra),
                   "%s"
                   "Cache-Control: no-cache\r\n"
                   "X-Content-Type-Options: nosniff\r\n",
                   validators);
  assert(n > 0 && n < (int)sizeof(extra));
  uint8_t zbuf[HTTP_GZIP_ZLIB_BYTES];
  HTTPBodyStream s;
  HTTPStreamBegin(&s, client_fd, 200, mime, extra, true, zbuf, sizeof(zbuf));
  ArenaMark mark = arena_mark(arena);
  uint8_t *chunk = (uint8_t *)arena_alloc(arena, MEDIA_CHUNK_BYTES);
  off_t pos = 0;
  bool ok = true;
  while (!s.failed) {
    ssize_t got = UISrcRead(src, chunk, MEDIA_CHUNK_BYTES, pos);
    if (got < 0 && errno == EINTR) {
      continue;
    }
    if (got <= 0) {
      ok = got == 0;
      break;
    }
    pos += got;
    HTTPStreamWrite(&s, chunk, (size_t)got);
  }
  arena_restore(arena, mark);
  // A file saved in place mid-send would arrive whole-looking and mixed;
  // left unterminated it is a failed transfer instead, which no cache keeps
  // (the identity sender's short body is the same).
  HTTPStreamEnd(&s, ok && pos == src->st.st_size && UIFileUnchanged(src));
  return 200;
}

// Whether this answer goes out gzipped: see "gzip" above.
static bool UIWantsGzip(const char *method, const char *req_buf,
                        const char *full, const struct stat *st) {
  assert(method != NULL && req_buf != NULL);
  assert(full != NULL && st != NULL);
  const UIType *t = UITypeFor(full);
  return g_conn_accepts_gzip && t && t->gzip && strcmp(method, "GET") == 0 &&
         st->st_size >= HTTP_GZIP_MIN_BYTES &&
         find_header_value(req_buf, "Range:") == NULL;
}

// Closes src.
static int UISendGzip(int client_fd, Arena *arena, UISrc *src, const char *mime,
                      const char *validators) {
  assert(client_fd >= 0 && src != NULL);
  assert(arena_valid(arena));
  assert(mime != NULL && validators != NULL);
  const struct stat *st = &src->st;
  int slot = -1;
  if (g_uigz.mem && st->st_size >= UI_GZ_CACHE_MIN_BYTES &&
      (size_t)st->st_size <= g_uigz.cap / 4) {
    pthread_mutex_lock(&g_uigz.lock);
    slot = UIGzFindLocked(st);
    pthread_mutex_unlock(&g_uigz.lock);
    if (slot < 0) {
      slot = UIGzFill(arena, src);
    }
  }
  int status = slot >= 0
                   ? UISendCached(client_fd, slot, mime, validators)
                   : UISendStreamed(client_fd, arena, src, mime, validators);
  UISrcClose(src);
  return status;
}

// ---------------------------------------------------------------------------
// The embedded copy
// ---------------------------------------------------------------------------
//
// docs/design/open-source-build.md, §2d. A release binary is one file a
// person downloads and runs, with no lcars-ui/ beside it, so under
// -DLCARS_EMBED_UI it carries the shipped set: scripts/ui-pack.py writes
// build/ui.pack (its format is in that script's docstring) and the
// assembler's .incbin puts it in .rodata as it is. Not `xxd -i`, which
// makes 8MB into a 50MB C file and a slow compile; .incbin is one directive
// that gcc's and clang's assemblers take on x86_64 and arm64 alike. Its
// path is the assembler's, relative to where cc runs: LCARS_UI_PACK, a
// string, default the Makefile's build/ui.pack.
//
// The files are stored raw: the gzip cache above compresses one on its
// first request and keeps it, as it does a file on disk, and the update
// check's Range on index.html needs the raw bytes anyway. Each is served
// from where it lies in the binary's mapping: nothing is copied at start,
// and the kernel pages in only what is asked for.
//
// Last-Modified is the pack's build time for every file, and the ETag
// (weak: one tag names both the gzip and identity forms, which If-None-Match
// compares weakly anyway) the file's content hash. A browser that kept a
// file from an older build of the same bytes gets its 304 by the ETag
// though the build time moved; the service worker's revalidation and the
// update check work as they do against the disk.
//
// LCARS_UI_DIR, when set, wins: a user can serve a UI of their own, and the
// dev loop stays "save and reload". Without the define the table is empty
// and every path below is the disk's, exactly as before; the code is
// compiled in every build, so the warnings see it.
//
// The identity a made-up stat gives the gzip cache (st_dev 0, st_ino the
// index + 1) cannot meet a real file's: one process serves either the
// embedded copy or a directory, never both (UIInit decides, once).

#define UI_EMBED_MAX 512 // MAX_FILES in scripts/ui-pack.py
#define UI_EMBED_MAGIC "LCARS-UI-PACK 1 "

#ifndef LCARS_UI_PACK
#define LCARS_UI_PACK "build/ui.pack"
#endif

#ifdef LCARS_EMBED_UI
// .rodata, 64-byte aligned like the files in it. pushsection/popsection
// leave the compiler's own section as it was. Hidden: lcars-one links two
// objects, and the blob is nobody else's.
__asm__(".pushsection .rodata\n"
        ".balign 64\n"
        ".globl lcars_ui_pack\n"
        ".hidden lcars_ui_pack\n"
        "lcars_ui_pack:\n"
        ".incbin \"" LCARS_UI_PACK "\"\n"
        ".globl lcars_ui_pack_end\n"
        ".hidden lcars_ui_pack_end\n"
        "lcars_ui_pack_end:\n"
        ".popsection\n");
extern const uint8_t lcars_ui_pack[] __attribute__((visibility("hidden")));
extern const uint8_t lcars_ui_pack_end[] __attribute__((visibility("hidden")));
#endif

typedef struct UIEmbedFile {
  const char *path; // into the pack's index, not NUL-terminated
  size_t path_len;
  const uint8_t *data;
  off_t size;
  char etag[24]; // W/"<16 hex>"
} UIEmbedFile;

// Written by UIInit before any thread, read-only after.
static struct {
  bool use; // serving from it: there is one, and LCARS_UI_DIR is not set
  int count;
  size_t bytes;
  time_t built;
  UIEmbedFile f[UI_EMBED_MAX];
} g_ui_embed;

#ifdef LCARS_EMBED_UI // the pack's reader; the rest is in every build
// One unsigned decimal and the separator after it, within [*p, end).
static bool UIPackNumber(const char **p, const char *end, char sep,
                         unsigned long long *out) {
  assert(p != NULL && *p != NULL && end != NULL && out != NULL);
  const char *q = *p;
  unsigned long long v = 0;
  while (q < end && *q >= '0' && *q <= '9') {
    if (v > (ULLONG_MAX - 9) / 10) {
      return false;
    }
    v = v * 10 + (unsigned long long)(*q - '0');
    q++;
  }
  if (q == *p || q >= end || *q != sep) {
    return false;
  }
  *out = v;
  *p = q + 1;
  return true;
}

// The pack's index into g_ui_embed; a reason it is not a pack, or NULL.
// Every offset is checked against the blob's real length, so a pack cut
// short or written by another version is refused, never read past.
static const char *UIEmbedParse(const uint8_t *blob, size_t len) {
  assert(blob != NULL || len == 0);
  const char *p = (const char *)blob;
  const char *end = p + len;
  size_t magic = strlen(UI_EMBED_MAGIC);
  if (len < magic || memcmp(p, UI_EMBED_MAGIC, magic) != 0) {
    return "no LCARS-UI-PACK 1 header";
  }
  p += magic;
  unsigned long long count, data_off, built;
  if (!UIPackNumber(&p, end, ' ', &count) ||
      !UIPackNumber(&p, end, ' ', &data_off) ||
      !UIPackNumber(&p, end, '\n', &built)) {
    return "a malformed header";
  }
  if (count == 0 || count > UI_EMBED_MAX) {
    return "a file count of 0 or over 512";
  }
  if (data_off > len) {
    return "a data offset past its end";
  }
  const char *index_end = (const char *)blob + data_off;
  for (unsigned long long i = 0; i < count; i++) {
    unsigned long long off, size;
    if (!UIPackNumber(&p, index_end, ' ', &off) ||
        !UIPackNumber(&p, index_end, ' ', &size)) {
      return "a malformed index line";
    }
    const char *hash = p;
    if (index_end - p < 17 || p[16] != ' ') {
      return "a malformed hash";
    }
    p += 17;
    const char *nl = memchr(p, '\n', (size_t)(index_end - p));
    if (nl == NULL || nl == p) {
      return "a malformed path";
    }
    if (off > len - data_off || size > len - data_off - off) {
      return "a file past its end";
    }
    UIEmbedFile *f = &g_ui_embed.f[i];
    f->path = p;
    f->path_len = (size_t)(nl - p);
    f->data = blob + data_off + off;
    f->size = (off_t)size;
    int n = snprintf(f->etag, sizeof(f->etag), "W/\"%.16s\"", hash);
    assert(n > 0 && (size_t)n < sizeof(f->etag));
    g_ui_embed.bytes += (size_t)size;
    p = nl + 1;
  }
  g_ui_embed.count = (int)count;
  g_ui_embed.built = (time_t)built;
  return NULL;
}

#endif // LCARS_EMBED_UI

static void UIInit(void) {
  const char *dir = getenv("LCARS_UI_DIR");
  bool dir_set = dir && dir[0];
  const char *how = dir_set ? "LCARS_UI_DIR" : "from disk";
#ifdef LCARS_EMBED_UI
  const char *why =
      UIEmbedParse(lcars_ui_pack, (size_t)(lcars_ui_pack_end - lcars_ui_pack));
  if (why) {
    memset(&g_ui_embed, 0, sizeof(g_ui_embed));
    printf("UI: the embedded copy is unreadable (%s); serving from disk\n",
           why);
  } else if (dir_set) {
    how = "LCARS_UI_DIR; the embedded copy unused";
  } else {
    g_ui_embed.use = true;
    char when[32];
    struct tm tm_built;
    gmtime_r(&g_ui_embed.built, &tm_built);
    strftime(when, sizeof(when), "%Y-%m-%d %H:%M UTC", &tm_built);
    printf("UI: embedded, %d files, %zu bytes, packed %s (LCARS_UI_DIR "
           "serves a directory instead)\n",
           g_ui_embed.count, g_ui_embed.bytes, when);
    fflush(stdout); // the start log, read before the first request
    return;
  }
#endif
  char abs[PATH_MAX];
  if (realpath(UIRoot(), abs) == NULL) {
    printf("UI: %s not found (%s); /ui/ will answer 404\n", UIRoot(), how);
  } else {
    printf("UI: %s (%s)\n", abs, how);
  }
  fflush(stdout);
}

// The embedded file at rel, as UIOpen opens one on disk: a directory's
// index.html included ("" and "deck/" both). false if there is none.
static bool UIEmbedOpen(const char *rel, char *full, size_t cap, UISrc *src) {
  assert(rel != NULL && full != NULL && src != NULL);
  assert(g_ui_embed.use);
  size_t n = strlen(rel);
  const char *const tries[] = {"", "index.html", "/index.html"};
  for (size_t t = 0; t < 3; t++) {
    // a name ending in '/' (or none) is only ever a directory
    bool dir_form = n == 0 || rel[n - 1] == '/';
    if ((t == 0 && dir_form) || (t == 1 && !dir_form) || (t == 2 && dir_form)) {
      continue;
    }
    int w = snprintf(full, cap, "%s%s", rel, tries[t]);
    if (w <= 0 || (size_t)w >= cap) {
      return false;
    }
    for (int i = 0; i < g_ui_embed.count; i++) {
      const UIEmbedFile *f = &g_ui_embed.f[i];
      if (f->path_len != (size_t)w || memcmp(f->path, full, (size_t)w) != 0) {
        continue;
      }
      memset(src, 0, sizeof(*src));
      src->fd = -1;
      src->mem = f->data;
      src->st.st_dev = 0;
      src->st.st_ino = (ino_t)i + 1;
      src->st.st_mode = S_IFREG | 0444;
      src->st.st_size = f->size;
      src->st.st_mtim.tv_sec = g_ui_embed.built;
      src->st.st_ctim.tv_sec = g_ui_embed.built;
      src->etag = f->etag;
      return true;
    }
  }
  return false;
}

// Opens root/rel as a regular file, a directory's index.html included.
static int UIOpen(const char *rel, char *full, size_t cap, struct stat *st) {
  assert(rel != NULL && full != NULL && st != NULL);
  int n = snprintf(full, cap, "%s/%s", UIRoot(), rel);
  if (n <= 0 || (size_t)n >= cap) {
    return -1;
  }
  int fd = open(full, O_RDONLY | O_CLOEXEC);
  if (fd >= 0 && fstat(fd, st) == 0 && S_ISDIR(st->st_mode)) {
    close(fd);
    const char *sep = (n > 0 && full[n - 1] == '/') ? "" : "/";
    n = snprintf(full, cap, "%s/%s%sindex.html", UIRoot(), rel, sep);
    if (n <= 0 || (size_t)n >= cap) {
      return -1;
    }
    fd = open(full, O_RDONLY | O_CLOEXEC);
    if (fd >= 0 && fstat(fd, st) != 0) {
      close(fd);
      fd = -1;
    }
  } else if (fd >= 0 && (fstat(fd, st) != 0 || !S_ISREG(st->st_mode))) {
    close(fd);
    fd = -1;
  }
  return fd;
}

// rel from the embedded copy when this process serves it, else from disk.
static bool UIOpenSrc(const char *rel, char *full, size_t cap, UISrc *src) {
  assert(rel != NULL && full != NULL && src != NULL);
  if (g_ui_embed.use) {
    return UIEmbedOpen(rel, full, cap, src);
  }
  memset(src, 0, sizeof(*src));
  src->fd = UIOpen(rel, full, cap, &src->st);
  return src->fd >= 0;
}

// Whether the client's copy is this one. If-None-Match, when there is an
// ETag to compare and the client sent one, decides alone (RFC 9110 13.2.2:
// a rebuild moves Last-Modified, the content hash stays); otherwise
// If-Modified-Since is compared with Last-Modified as it was sent.
static bool UINotModified(const char *req_buf, const UISrc *src,
                          const char *modified) {
  assert(req_buf != NULL && src != NULL && modified != NULL);
  const char *inm = find_header_value(req_buf, "If-None-Match:");
  if (src->etag && inm) {
    // weak comparison: the opaque tag, with or without W/, anywhere in the
    // list; "*" is any
    const char *tag = src->etag + 2; // past W/
    size_t line = strcspn(inm, "\r\n");
    for (const char *q = inm; q < inm + line; q++) {
      if (*q == '*' || (strncmp(q, tag, strlen(tag)) == 0 &&
                        (size_t)(q - inm) + strlen(tag) <= line)) {
        return true;
      }
    }
    return false;
  }
  const char *ims = find_header_value(req_buf, "If-Modified-Since:");
  return ims && strncmp(ims, modified, strlen(modified)) == 0;
}

static int HandleUIFile(int client_fd, Arena *arena, const char *method,
                        const char *path, const char *req_buf) {
  assert(client_fd >= 0);
  assert(arena_valid(arena));
  assert(method != NULL && req_buf != NULL);
  assert(UIIsPath(path));

  const char *move = UIRedirectFor(path);
  if (move) {
    char resp[256];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 301 Moved Permanently\r\n"
                     "Location: %s\r\n"
                     "Content-Length: 0\r\n%s\r\n",
                     move, HTTPConnectionHeader());
    assert(n > 0 && n < (int)sizeof(resp));
    send(client_fd, resp, (size_t)n, MSG_NOSIGNAL);
    return 301;
  }

  // the query never names a file: /ui/?q=hike is the page
  char rel[256];
  snprintf(rel, sizeof(rel), "%s", path + 4);
  rel[strcspn(rel, "?#")] = '\0';
  if (!UIRelIsSafe(rel)) {
    return SendJSONError(client_fd, 404, "Not found");
  }

  char full[PATH_MAX];
  UISrc src;
  if (!UIOpenSrc(rel, full, sizeof(full), &src) &&
      !(UIRelIsPage(rel) &&
        // a page: the app, which reads where it is from the address bar
        UIOpenSrc("index.html", full, sizeof(full), &src))) {
    return SendJSONError(client_fd, 404, "No file %s in the web UI", rel);
  }

  // The service worker revalidates every file behind its cached copy on each
  // visit, so no-cache (store, but ask first) and a 304 for an unchanged
  // file keep that to a header's worth of traffic. Without Cache-Control a
  // browser may answer the worker's revalidation from its own heuristic
  // cache, and a saved file would take days to arrive.
  char modified[64];
  struct tm tm_mod;
  gmtime_r(&src.st.st_mtim.tv_sec, &tm_mod);
  strftime(modified, sizeof(modified), "%a, %d %b %Y %H:%M:%S GMT", &tm_mod);
  char etag_line[64] = "";
  if (src.etag) {
    snprintf(etag_line, sizeof(etag_line), "ETag: %s\r\n", src.etag);
  }
  if (UINotModified(req_buf, &src, modified)) {
    UISrcClose(&src);
    char resp[320];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 304 Not Modified\r\n"
                     "Last-Modified: %s\r\n"
                     "%s"
                     "Vary: Accept-Encoding\r\n"
                     "Cache-Control: no-cache\r\n%s\r\n",
                     modified, etag_line, HTTPConnectionHeader());
    assert(n > 0 && n < (int)sizeof(resp));
    send(client_fd, resp, (size_t)n, MSG_NOSIGNAL);
    return 304;
  }
  if (UIWantsGzip(method, req_buf, full, &src.st)) {
    char validators[160];
    snprintf(validators, sizeof(validators), "Last-Modified: %s\r\n%s",
             modified, etag_line);
    return UISendGzip(client_fd, arena, &src, UIMimeFor(full), validators);
  }
  char extra[160];
  snprintf(extra, sizeof(extra),
           "Cache-Control: no-cache\r\n"
           "Vary: Accept-Encoding\r\n"
           "%s",
           etag_line);
  if (src.mem) {
    return MediaSendMemory(client_fd, arena, method, req_buf, src.mem, &src.st,
                           UIMimeFor(full), extra);
  }
  return MediaSendOpenFile(client_fd, arena, method, req_buf, src.fd, &src.st,
                           UIMimeFor(full), extra);
}

#endif // LCARS_UI_FILES_IMPLEMENTATION
#endif // LCARS_UI_FILES_H
