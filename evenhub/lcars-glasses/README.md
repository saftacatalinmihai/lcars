# LCARS on Even Realities G2

Browse, read, create, complete and delete LCARS journal entries from the
glasses. An [Even Hub](https://hub.evenrealities.com) app — the third-party app
platform Even Realities opened for the G2 in April 2026.

It is a client of the LCARS HTTP API, exactly as `lcars-cli` and the web build
are. Every CRUD route it uses already existed; the one addition on the server
side is `POST /transcribe`, speech to text so the glasses can write by voice
(see `ARCHITECTURE.md` → "Transcription").

## What it is, mechanically

An Even Hub app is **a web app that does not render itself**. Your HTML/CSS/JS
runs in a WebView inside the iPhone Even App; the SDK bridge relays a
*container* model (lists, text, menus) over Bluetooth LE to the glasses, and
relays input back. So:

- `src/main.ts` drives the glasses: a list you scroll with the R1 ring or the
  temple touchpad, a contextual menu of named actions, and the dictation flow.
- `src/settings.ts` + `index.html` are what the **phone** shows. That split is
  forced, not stylistic: the G2 has no keyboard. Journal text can be spoken, but
  a URL and a password have to be typed somewhere, and this is that somewhere.
- `src/lcars.ts` is the API client, and is the only part that knows about
  journals.

## Screens

| Screen | List shows | Menu |
|---|---|---|
| Entries | titles for the current kind, newest first; tasks get `[ ]` / `[x]` | Dictate, New, Kind, Refresh, Older, Newest, Exit |
| Dictate | — (recording) | Stop, Cancel |
| Confirm | the transcript | Save, Again, Discard |
| Entry | the body, paged | Back, Page, Mark done/undone, Delete |
| Kind | every kind, plus "(all kinds)" | Back |
| New | your quick captures | Back |

A long press anywhere is Back — the one gesture bound, because it is reachable
from both the ring and the temple.

## The input model, which is not what you would guess

Verified against the Even Hub simulator; all of it shapes the design above.

- **Scrolling emits no event.** `up`/`down` move the highlight *inside the
  firmware* and the app is never told. There is no way to track the cursor —
  only to learn where it was at the moment something was clicked.
- **A click carries no `eventType`.** `CLICK_EVENT` is `0`, and the zero value
  is omitted on the wire, so `eventType === OsEventTypeList.CLICK_EVENT` is
  never true. A `listEvent` arriving *is* the click.
- **`currentSelectItemIndex` is absent for row 0**, same reason. Read it as
  `?? 0`; treating absent as "unchanged" opens the wrong entry every time row 0
  is clicked after the highlight has been elsewhere.
- Long press, double click and foreground enter/exit arrive as `sysEvent`
  (`9`, `10`, `3`, `4`, `5`). Opening the contextual menu fires foreground
  exit/enter around it.

The first two together are why **the list menu carries no per-entry verbs**.
"Delete the highlighted row" cannot be implemented: the app does not know which
row is highlighted. Done and Delete live on the detail screen, where the entry
is unambiguous because you opened it.

The list footer is a static hint for the same reason — a row id there would be
stale the moment you scrolled.

## Firmware limits worth knowing

| Limit | Value | What happens if you exceed it |
|---|---|---|
| List items | 20 | the whole page is rejected — `list item count 25 exceeds limit of 20` |
| List item text | 63 UTF-8 bytes | truncated |
| Text container content | 999 bytes | rejected |
| Containers per page | 12, of which ≤8 text | rejected |
| Menu items | 10, ids non-zero and unique | rejected |
| Menu item name | 32 UTF-8 bytes | rejected |

`src/glasses.ts` clamps the list ones rather than trusting callers: a rejected
page is not a visual glitch, it is a screen that silently keeps showing the
*previous* page while still delivering input against it — which reads as a
frozen app that occasionally does the wrong thing.

The 20-item cap is why the journal is browsed a page at a time (`Older` /
`Newest`) instead of scrolled.

**A startup page can only be created once.** `createStartUpPageContainer` is
refused if the glasses already hold a page — which is the normal state after a
relaunch that did not shut its page down, and after every hot reload. `GlassesUI`
falls back to `rebuildPageContainer` and adopts the existing page; without that
the app retries `create` forever and every screen it draws is dropped.

## CRUD, and what the API actually does

| Verb | Route | Note |
|---|---|---|
| Create | `POST /entries` | answers `{status,id}` — **not** the new row |
| Read | `GET /entries?kind=…&content=0` | bodies omitted; the server builds each response in a 1MB arena, so a page of entries *with* content 500s on a real journal |
| Read one | `GET /entries/<id>` | this is where the body comes from |
| Update | `PATCH /entries/<id>` | partial: toggling `done` cannot blank a title |
| Delete | `DELETE /entries/<id>` | **soft** — the row survives |

The write routes all return an acknowledgement rather than the updated entry,
which is why the app applies changes to its own copy instead of replacing it
with the response.

Delete being soft is the only reason a single menu tap is allowed to do it with
no confirmation step. `restore` is the undo, and there is deliberately no
hard-delete route anywhere in LCARS.

## Setup

```sh
npm install
npm run dev          # http://localhost:5173 - the settings form, in a browser
npm run typecheck
npm run build        # tsc --noEmit && vite build -> dist/
npm run pack         # dist/ + app.json -> lcars-glasses.ehpk
```

Then `evenhub login` and submit the `.ehpk` through Even Hub. `npm run simulate`
points the official simulator at the dev server.

### Two things that will bite you

**1. The API host must be in `app.json`.** Even Hub apps declare a network
permission with an explicit whitelist:

```json
"permissions": [
  { "name": "network",
    "desc": "…",
    "whitelist": ["https://your-host.your-tailnet.ts.net"] }
]
```

`app.json` ships with a `REPLACE-ME` placeholder. A URL you type into the
settings form but never whitelisted is blocked by the WebView *before* the
request is made — which looks exactly like the server being down. The app
reports that case as "check the tailnet, and that the host is in app.json's
network whitelist" for that reason.

**2. It has to be https.** The WebView page is served over https, so it cannot
fetch a plain `http://<address>:8080` — the browser blocks it as mixed content
before the request exists. Use the `tailscale serve --bg 8080` hostname, which
is the same constraint (and the same fix) the LCARS web build already has.

## Testing

```sh
# in a scratch directory holding a COPY of lcars.db - never the real one
lcars --http-only --port 8099 --user test --password test

npm test
```

`test/crud.test.ts` runs the full create → list → read → update → soft-delete →
restore cycle plus the error mappings against a live server, and writes only
under kind `hyper_test`. `LCARS_TEST_URL` / `LCARS_TEST_USER` /
`LCARS_TEST_PASS` point it elsewhere.

### The glasses half, in the simulator

The official simulator renders the real container model and exposes an HTTP
automation API, which is enough to drive the whole app without hardware:

```sh
npm run dev                                   # vite on :5173
npm run simulate                              # or, with automation:
npx evenhub-simulator \
  'http://127.0.0.1:5173/?api=http://127.0.0.1:8099&user=test&pass=test&debug=1' \
  --automation-port 9898
```

```sh
curl -XPOST localhost:9898/api/input -d '{"action":"click"}'   # up|down|click|
                                                               # double_click|
                                                               # long_press|
                                                               # long_press_release|
                                                               # context_menu
curl localhost:9898/api/screenshot/glasses -o frame.png        # 576x288 RGBA
curl localhost:9898/api/console                                # webview console
```

`?debug=1` traces every event the app receives to that console, which is the
only way to see what the glasses actually sent.

Driving it this way is what turned up every item in "The input model" above —
none of it is visible to the typechecker, and the SDK docs do not mention it.

Query parameters (`?api=`, `?user=`, `?pass=`, `?kind=`, `?limit=`, `?debug=`)
layer over stored settings and are never persisted. They exist because the
simulator loads a URL and has no way to type into the phone form; they mirror
the `?api=` the LCARS web build already accepts.

Hardware is still the final word — the simulator's own README says so, and its
list-scrolling behaviour in particular is a re-implementation rather than the
firmware.

## Dictation

Speech to text goes through **your own LCARS server**, which relays the audio
to Deepgram (`POST /transcribe`; since LCARS 0.176.0 — before that the server
ran an offline Vosk model, and the audio never left it). The key stays on the
server; the glasses only ever talk to LCARS.

Menu → **Dictate** → speak → click to stop → check what it heard → **Save**.

The confirm step is not politeness. Recognition is wrong sometimes, and an entry
you cannot edit from the glasses is one you would have to fix somewhere else.

| | |
|---|---|
| Format | 16 kHz mono s16le, straight from `AudioEvent.audioPcm` — the server tells Deepgram exactly that, so nothing resamples |
| Chunks | 3200 bytes (100 ms) per event |
| Limit | `MAX_AUDIO_BYTES` (500KB) and `MAX_RECORD_MS` (15 s), both under the server's 512KB body cap |
| Needs | `DEEPGRAM_API_KEY` on the server, or the route answers 503 |

**Cap by bytes, not just by time.** `MAX_RECORD_MS` assumes audio arrives at
real time and nothing guarantees that: the simulator's `alsa:null` device is not
rate-limited and delivered 6MB in 8 seconds of wall clock — twenty-two times
real time — which came back 413 with the note lost. The byte cap holds whatever
the source does.

Quick captures remain for the notes you log often enough to not want to say out
loud.

## Not part of the C build

This is a separate npm project. The `Makefile`, the unity build and
`compile_commands.json` do not know it exists, and nothing here is compiled into
`lcars`, `lcars-cli` or the wasm bundle.

Written against Even Hub SDK `0.0.15` / Even App `2.2.10`.
