/* LCARS journal — app-shell cache.

   Stale-while-revalidate for the shell: a boot paints from cache immediately,
   and the fresh copy fetched alongside it lands on the next visit. The API is
   deliberately never cached — the database is the source of truth, and a stale
   entry list would be a lie rather than a saving.

   A changed index.html therefore reaches an installed client on the visit
   after the one that fetched it — no version bump needed — or at once, when
   the page asks for it ("refresh" below: its Update button). Changing CACHE is the
   bigger hammer: it drops everything at once, which is what a change to SHELL
   itself needs, or a shell already cached in a state worth abandoning.       */
const CACHE = "lcars-shell-v2";
const TILE_HOSTS = /^(api\.mapy\.com|tile\.openstreetmap\.org|tile\.opentopomap\.org|tile\.waymarkedtrails\.org)$/;
const SHELL = ["./", "./index.html", "./icon-192.png", "./icon-512.png",
               "./apple-touch-icon.png", "./manifest.webmanifest"];

self.addEventListener("install", ev => {
  ev.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting()));
});

self.addEventListener("activate", ev => {
  ev.waitUntil(
    caches.keys()
      // "lcars-keep-*" are a course's offline map and routes (index.html,
      // "offline"): the page's to keep and to drop, never a stale shell
      .then(ks => Promise.all(ks.filter(k => k !== CACHE && !k.startsWith("lcars-keep-")).map(k => caches.delete(k))))
      .then(() => self.clients.claim()));
});

/* "refresh": the page's Update and Reload (index.html, updApply). The shell
   is fetched again past the browser's own cache, every file before any is
   stored, so a failure halfway leaves the old shell whole rather than half of
   each. A deep path the fetch below cached as a navigation (/ui/tasks,
   /ui/entry/123) is the page too, and would be answered before "./": those
   are dropped, and fall back to the fresh "./" until they are fetched anew.
   The answer goes back on the message's port: {ok} or {ok:false, error}. */
async function refreshShell() {
  const scope = self.registration.scope;
  const urls = SHELL.map(u => new URL(u, scope).href);
  const got = await Promise.all(urls.map(u => fetch(new Request(u, { cache: "reload" })).then(res => {
    if (!res.ok) throw new Error(new URL(u).pathname + " answered " + res.status);
    return res;
  })));
  const c = await caches.open(CACHE);
  for (const req of await c.keys()) {
    if (urls.includes(req.url)) continue;
    const hit = await c.match(req);
    if (hit && /^text\/html/.test(hit.headers.get("content-type") || "")) await c.delete(req);
  }
  await Promise.all(got.map((res, i) => c.put(urls[i], res)));
}
self.addEventListener("message", ev => {
  const port = ev.ports && ev.ports[0];
  if (!port || !ev.data || ev.data.type !== "refresh") return;
  ev.waitUntil(refreshShell().then(() => port.postMessage({ ok: true }),
                                   e => port.postMessage({ ok: false, error: String((e && e.message) || e) })));
});

self.addEventListener("fetch", ev => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Map tiles kept for a course offline are answered from that cache; every
  // other tile, and everything else from another origin, is the network's.
  if (url.origin !== location.origin) {
    if (TILE_HOSTS.test(url.host) && /\/\d+\/\d+\/\d+/.test(url.pathname)) {
      ev.respondWith(caches.open("lcars-keep-tiles").then(c => c.match(req.url)).then(hit => hit || fetch(req)));
    }
    return;                                                 // fonts, anything else
  }
  // Only the page's own files. The API is the same origin (tailscale serve
  // puts it at /), so a test on a few route names was all that kept the
  // journal itself out of this cache — and /dump, /kinds and the rest were
  // not on the list: a boot's full load could be answered by a stale cached
  // dump. Whatever is not under this worker's scope is the server's.
  if (!url.pathname.startsWith(new URL(self.registration.scope).pathname)) return;
  if (/^\/(entries|stats)\b/.test(url.pathname)) return;   // always live
  // Attachments: photos and video off the NAS. Too big to keep a second copy
  // of in the cache, and a <video>'s Range requests would be answered with a
  // cached whole file (or a cached 206) — both of which break seeking.
  // The bare /media is the list of them (the media view), live data like
  // /entries.
  if (/^\/media(\/|$)/.test(url.pathname) || req.headers.has("range")) return;

  // Opening the app is a navigation, and it may carry a query (the share
  // target, the Capture shortcut): with no network those must still find the
  // cached page, which is stored without one.
  const nav = req.mode === "navigate";
  ev.respondWith(caches.match(req, { ignoreSearch: nav })
    .then(hit => hit || (nav ? caches.match("./") : undefined))
    .then(hit => {
      const net = fetch(req).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    }));
});
