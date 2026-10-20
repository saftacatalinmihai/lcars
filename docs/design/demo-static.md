# The public demo, as static files

LCARS on a made-up journal, for anyone: the console and the deck, read,
edited, searched and walked, with no server behind them. Hosted as plain
files on the captain's public bucket (its host is in CLAUDE.local.md), under `/lcars-demo/`
(Cloudflare R2: no server, no rewrites, no index document for a folder, one
origin). The captain chose it knowing it publishes the pages' source.

## Build

```sh
python3 lcars-ui/demo/static.py            # -> ~/blog-media/lcars-demo/out/
python3 lcars-ui/demo/static.py OUT        # anywhere outside the repo
python3 lcars-ui/test/demo_static.py       # build, serve, drive it (~1 min)
```

The build remakes the folder whole (it refuses one it did not write: no
`.lcars-demo` in it), then prints its size and its biggest files. About
8 MB: the console (1.9 MB), three.js, the deck page, the deck's rooms and
the crew's models.

| in the folder | what it is |
| --- | --- |
| `index.html`, `deck.html` | the pages, with `demo.js` loaded first and the face from `fonts/` |
| `demo.js` | `demo/static.js`: the server in the page, and the demo's only switch |
| `journal.json` | `demo/fixture.py`'s `public()`, the vectors, the media list |
| `api/media/demo/*.png` | the two pictures, drawn by the build |
| `vendor/`, `deck/`, `crew/` | as in `lcars-ui/` |
| `fonts/` | Antonio, from `demo/assets/` |
| `manifest.webmanifest`, icons | a manifest whose start is `index.html` |

No service worker: a worker would go on serving a visitor an old build long
after the folder is replaced, and the demo has no offline use.

## Upload (Jake's, with the bucket's token)

Upload the folder's contents under `lcars-demo/`, replacing what is there,
with the types a static host needs (`.mjs` as `text/javascript`, `.glb` as
`model/gltf-binary`, `.webp`, `.woff2`, `.webmanifest`):

```sh
rclone sync ~/blog-media/lcars-demo/out r2:<bucket>/lcars-demo --exclude .lcars-demo
```

Then open `<the bucket>/lcars-demo/index.html` (the
file, not the folder: R2 serves no index document) and the deck from its
Deck button. A link to the demo names `index.html`.

## How it works

**The switch.** `demo.js` sets `window.LCARS_DEMO`, and the pages read it
(`DEMO` in index.html, `STATIC` in deck.html). Only the build loads that
file, so no url the live app answers can put it in demo mode.

**The API, in the page.** The pages are unchanged where they talk to the
server: `api()` fetches `cfg.base + path`, and in the demo `cfg.base` is
the folder's `api` (`LCARS_DEMO.base`), with the login "visitor". `demo.js`
wraps `fetch` and answers everything under it from `journal.json` and this
browser's edits: `/entries` and `/dump` with the server's filters, a row's
GET, PUT, PATCH and DELETE (soft), POST with its idempotency key,
`append` and `title`, `/stats`, `/media`, `/embeddings`. Edits are rows in
localStorage (`lcars.demo.edits`), over the fixture, so a reload keeps
them; the console's mirror, outbox and star cache work as they do against
a server. The one request that reaches the host is a picture,
`api/media/<path>`: a real file there, since an `<img>` never comes
through `fetch`.

**The dates.** The fixture is written relative to the day it was built; the
page moves every row on by the days since (`built` in `journal.json`), so
its newest entry is today's - or yesterday's, when today's move would
stamp rows later than now (they are at 16:20 of the fixture's day): a row
in the future would carry the change feed's mark past the stamp of an
edit made now, and the deck would never see it. When the move changes,
the mirror, which holds the old dates, is emptied before the page opens it.

**Routing.** The live page gives each view a path (`/ui/entry/123`), which
the server answers with index.html; a bucket answers it with a 404. In the
demo the route is the hash, `index.html#entry/123`: `writeState` writes it,
`curRel` and the head's router read it, so every reload, Back and shared
link lands on the one file.

**Reset.** The strip above the header (`demoBanner`) says it is a demo on a
made-up journal whose edits stay in this browser, and carries Reset
("computer, reset the demo"): this browser's edits, the pages' settings
(`lcars.*`) and the three IndexedDB stores go, and the page reloads.
On a phone the reader, the editor, the filters and the views are fixed
panels over the screen; in the demo they start under the strip
(`body.demo`, `--demoh`), so Reset is there whatever is open.
The version mark (`#verMark`) goes under the strip too, at any size.

**What is off, and says so.** What needs the server answers with a note
where the feature would be, not an error: the computer, the navigator and
the crew's chat get a reply saying why (`/chat`); search by meaning, an
upload, a tape, CalDAV, the engineers and their queue, and the course (its
maps and navigator) a one-line note. The deck has no Promote, plays the
holodeck's canned program, and starts a phone on medium graphics. The
update check is off.

**Nothing of ours.** The pages carry no host of ours (since 0.263.1 a
`file://` page has no fallback server: it asks in Config). The build reads
every text file it wrote for a tailnet host, the VPS's address, the captain's name, an
Anthropic or Mapy key, a login or the engineers' key, and deletes the
folder if it finds one. The fixture is the reel's made-up journal.

**Every cached file by its content.** The host (the bucket's,
behind Cloudflare) caches `.js`, `.css`, fonts and pictures for four hours
(max-age 14400), HTML and JSON not at all, and nobody of ours can purge
it: an upload once ran the new `index.html` on the old `demo.js` until
the cache let go. So the build names every file of the folder with
`?v=<10 hex of its SHA-256>`, the pages last, once everything they name
is written: each quoted name in the pages (`demo.js`, the icons, the
manifest, `fonts/antonio.css`, three.js and the meshopt decoder, Leaflet),
the woff2s in `antonio.css`, and the icons in the manifest. The deck
builds its models' and textures' names as it runs (`DECK_MODELS + room +
".glb"`), so built `deck.html` carries a table, `LCARS_DEMO_V` (path to
hash, for `deck/` and `crew/`), and hands `LCARS_DEMO_ASSET` to three.js's
`DefaultLoadingManager.setURLModifier`, which every loader of the deck
goes through. The journal's pictures carry the hash in their names
(`e2400-1-<hash>.png`), since the console builds their urls from the
journal's paths. A changed file is a new url the moment the new page is;
an unchanged one keeps its url and its cached copy. Only the build does
this: `lcars-ui/` itself is unchanged. `test/demo_static.py` checks the
pages' names, a rebuild with another `demo.js`, and that Chromium asked
for no script, style, font, model or picture without its hash.

## Next

A visitor's own key for the computer and search by meaning; the course on
OpenStreetMap's tiles (no key) with a fixture trip; the engineers as a
replay of a staged thread, marked a recording. TODO.md has them.
