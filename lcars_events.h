#ifndef LCARS_EVENTS_H
#define LCARS_EVENTS_H

// GET /events - the journal changed: a Server-Sent Events stream that says so.
//
// The web UI holds the whole journal in IndexedDB and catches up with two
// small /dump questions (deltaSync). What it lacked was a reason to ask: it
// only did on boot, on coming back to the front and on a five-minute probe,
// so an entry written by the CLI, a background Claude, a Shortcut, Reminders
// or the desktop app sat unseen in an open tab. This stream is that reason.
//
// It does not say *what* changed - the client's own sync already knows how to
// find out, from its mark, and does it in one round trip. So the source of the
// signal can be the database itself rather than the write paths of this
// server: a watcher thread reads the file's change counter once a second
// (EventsDbSignature - deliberately not through SQLite), which every commit
// moves. That covers every writer there is - this server's connection
// threads, sqlite3 by hand - without each
// having to remember to announce itself.
//
// One event per change of version, carrying a sequence number:
//   data: {"seq":12}
// sent once on connect (so a client can tell a reconnect from a change) and
// again on every change. A comment every EVENTS_HEARTBEAT_SECONDS keeps
// tailscale serve from timing the stream out, and lets a send notice a client
// that has gone. The stream ends after EVENTS_MAX_SECONDS; the client
// reconnects, which bounds what a connection that never says goodbye costs.
//
// Each stream holds a connection thread and one of the server's
// HTTP_MAX_CONCURRENT_CONNECTIONS slots, so they are capped too.
//
// A module of lcars_http.h, after lcars_chat.h (POLLRDHUP).

static int HandleEvents(int client_fd);

#ifdef LCARS_EVENTS_IMPLEMENTATION

#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pthread.h>
#include <time.h>

#define EVENTS_POLL_MS 1000
#define EVENTS_HEARTBEAT_SECONDS 15
#define EVENTS_MAX_SECONDS (30 * 60)
// Tabs and devices at once. A phone, a laptop, a deck and a spare.
#define EVENTS_MAX_STREAMS 8

static pthread_mutex_t g_events_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_events_cv = PTHREAD_COND_INITIALIZER;
static unsigned long g_events_seq = 1; // under g_events_mu
static int g_events_streams = 0;       // under g_events_mu
static pthread_once_t g_events_once = PTHREAD_ONCE_INIT;
static bool g_events_watching = false; // set once, by the once

// What the database file says about its last commit, read without SQLite.
// An open connection doing the reading - even only `PRAGMA data_version` once
// a second - was seen holding a SHARED lock between polls, and in rollback
// mode (which lcars.db is) that is every other writer refused with "database
// is locked". So: the header's file change counter (bytes 24-27, bumped by
// every commit in rollback mode), plus the -wal file's size and mtime for a
// database in WAL mode, where the header does not move until a checkpoint.
//
// The file is opened once and **never closed**. POSIX drops every lock a
// process holds on a file when *any* of its descriptors to that file is
// closed, so a close() here would silently release the locks this server's
// own SQLite connections hold mid-transaction (SQLite works around that for
// its own descriptors; it cannot for ours). A database swapped in place
// (db-pull) is a new inode: the old descriptor is leaked, not closed.
static int g_events_db_fd = -1;
static ino_t g_events_db_ino = 0;

static unsigned long long EventsDbSignature(void) {
  struct stat st;
  if (stat(LcarsDBPath(), &st) != 0) {
    return 0;
  }
  if (g_events_db_fd < 0 || st.st_ino != g_events_db_ino) {
    g_events_db_fd = open(LcarsDBPath(), O_RDONLY | O_CLOEXEC);
    g_events_db_ino = st.st_ino;
  }
  unsigned long long sig = (unsigned long long)st.st_ino;
  unsigned char hdr[4];
  if (g_events_db_fd >= 0 &&
      pread(g_events_db_fd, hdr, sizeof(hdr), 24) == (ssize_t)sizeof(hdr)) {
    sig = sig * 1000003ULL + (((unsigned long long)hdr[0] << 24) |
                              ((unsigned long long)hdr[1] << 16) |
                              ((unsigned long long)hdr[2] << 8) | hdr[3]);
  }
  if (stat(LcarsDBWalPath(), &st) == 0) {
    sig = sig * 1000003ULL + (unsigned long long)st.st_size;
    sig = sig * 1000003ULL + (unsigned long long)st.st_mtim.tv_sec;
    sig = sig * 1000003ULL + (unsigned long long)st.st_mtim.tv_nsec;
  }
  return sig;
}

static void *EventsWatcherThread(void *arg) {
  (void)arg;
  unsigned long long last = EventsDbSignature();
  for (;;) {
    // tv_nsec must stay under a second: {0, 1000 * 1000000} is EINVAL, and
    // nanosleep returning at once made this loop spin a core (0.121.0)
    struct timespec ts = {EVENTS_POLL_MS / 1000,
                          (EVENTS_POLL_MS % 1000) * 1000000L};
    nanosleep(&ts, NULL);
    unsigned long long now = EventsDbSignature();
    if (now != last) {
      last = now;
      pthread_mutex_lock(&g_events_mu);
      g_events_seq++;
      pthread_cond_broadcast(&g_events_cv);
      pthread_mutex_unlock(&g_events_mu);
    }
  }
  return NULL;
}

static void EventsStartWatcher(void) {
  pthread_attr_t attr;
  if (pthread_attr_init(&attr) != 0) {
    return;
  }
  pthread_attr_setstacksize(&attr, 256 * 1024);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
  pthread_t tid;
  g_events_watching =
      pthread_create(&tid, &attr, EventsWatcherThread, NULL) == 0;
  pthread_attr_destroy(&attr);
  if (!g_events_watching) {
    printf("Events: cannot start the database watcher\n");
  }
}

// The client hung up: a stream has nothing to read, so a hangup (or any
// byte at all, which no client sends) is all poll() can report.
static bool EventsClientGone(int fd) {
  assert(fd >= 0);
  struct pollfd p = {fd, POLLIN | POLLRDHUP, 0};
  return poll(&p, 1, 0) > 0 &&
         (p.revents & (POLLRDHUP | POLLHUP | POLLERR | POLLIN));
}

static int HandleEvents(int client_fd) {
  assert(client_fd >= 0);
  pthread_once(&g_events_once, EventsStartWatcher);
  if (!g_events_watching) {
    return SendJSONError(client_fd, 503, "The database watcher is not running");
  }
  pthread_mutex_lock(&g_events_mu);
  bool room = g_events_streams < EVENTS_MAX_STREAMS;
  if (room) {
    g_events_streams++;
  }
  unsigned long seq = g_events_seq;
  pthread_mutex_unlock(&g_events_mu);
  if (!room) {
    return SendJSONError(client_fd, 429, "Too many event streams open");
  }

  // Open-ended, so the connection ends with it (see HandleChat).
  g_conn_keep_alive = false;
  char buf[512];
  int n = snprintf(buf, sizeof(buf),
                   "HTTP/1.1 200 OK\r\n"
                   "Content-Type: text/event-stream; charset=utf-8\r\n"
                   "Cache-Control: no-cache, no-transform\r\n"
                   "X-Accel-Buffering: no\r\n" HTTP_CORS_HEADERS "%s"
                   "\r\n"
                   "retry: 5000\n\ndata: {\"seq\":%lu}\n\n",
                   HTTPConnectionHeader(), seq);
  assert(n > 0 && n < (int)sizeof(buf));
  bool ok = ChatSendAll(client_fd, buf, (size_t)n);
  time_t start = time(NULL);
  while (ok && time(NULL) - start < EVENTS_MAX_SECONDS) {
    struct timespec until;
    clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += EVENTS_HEARTBEAT_SECONDS;
    pthread_mutex_lock(&g_events_mu);
    while (g_events_seq == seq) {
      if (pthread_cond_timedwait(&g_events_cv, &g_events_mu, &until) != 0) {
        break; // the heartbeat's turn
      }
    }
    unsigned long now = g_events_seq;
    pthread_mutex_unlock(&g_events_mu);
    if (EventsClientGone(client_fd)) {
      break;
    }
    if (now != seq) {
      seq = now;
      n = snprintf(buf, sizeof(buf), "data: {\"seq\":%lu}\n\n", seq);
      assert(n > 0 && n < (int)sizeof(buf));
      ok = ChatSendAll(client_fd, buf, (size_t)n);
    } else {
      ok = ChatSendAll(client_fd, ": ping\n\n", 8);
    }
  }
  pthread_mutex_lock(&g_events_mu);
  g_events_streams--;
  assert(g_events_streams >= 0);
  pthread_mutex_unlock(&g_events_mu);
  return 200;
}

#endif // LCARS_EVENTS_IMPLEMENTATION
#endif // LCARS_EVENTS_H
