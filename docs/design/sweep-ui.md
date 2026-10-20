# The web UI's simplification sweep — survey

Status: **survey** (2026-10-13, Lt. Cdr. La Forge, for Number One and the
captain). Round 1 (dead code, duplicate helpers, stale docs; no behaviour
change) is 0.173.1; round 2 (items 1, 2, 6, 7) is 0.174.0. Items 3-5 wait
for the captain's phone checks of 0.172.0; 8-10 are the captain's call;
11 is not to be done.

The goal: less code and less complexity in `lcars-ui/index.html` (33.4k
lines) and `lcars-ui/deck.html` (11.8k), by letting the browser do what the
page does by hand, as the native keyboard replaced `keyboardFit` in
0.161.1. Line numbers are `index.html` at 0.173.1 unless a file is named.
"iOS" means iPhone Safari, standalone (home-screen) included: it is the
captain's phone and the floor for every platform feature here.

How dead code was looked for: esbuild's tree-shaking over each page's
script (what it drops, nothing reaches), a token count of every top-level
name (defined once, used nowhere), every CSS class, id and custom property
against the markup and scripts, every camelCase name in a comment or doc
against the code, and the QuickJS shim's stand-ins against the page. The
page is tight: a handful of dead functions, no dead CSS rules. The large
savings are in the ranked list, and they change behaviour.

## Ranked list

Ranked by lines saved per unit of risk (risk 1 low, 2 medium, 3 high).

| # | What | Saves | Risk |
|---|------|------:|:----:|
| 1 | The deck's copy of the speech queue → a one-shot announcement | ~270 | 1 |
| 2 | `test/audit.py`'s source-string checks the suites already cover | ~150-250 | 1 |
| 3 | The overlay (`#ov`/`#dlg`) → `<dialog>` + `showModal()` | ~60 | 2 |
| 4 | Menus and the speed dial → the Popover API | ~40 | 2 |
| 5 | Folds by hand → `<details>`/`<summary>` | ~40-60 | 2 |
| 6 | `copyText`'s execCommand fallback → the Clipboard API only | ~12 | 1 |
| 7 | Hand-made debounce timers → the existing `deb()` | ~30-50 | 1-2 |
| 8 | The date + time picker → native `datetime-local` | ~120-200 | 3 |
| 9 | Row swipe actions → CSS scroll-snap rows | ~120 | 3 |
| 10 | The reader's page turn (`swipeTurn`) → scroll-snap | ~60 | 3 |
| 11 | Day and month names by hand → `Intl.DateTimeFormat` | ~15 | 2 |

Looked at and **not** worth doing (no platform feature does it, or it saves
nothing): see "Kept, and why" at the end.

### 1. The deck's speech queue → one fetch per announcement (~270 lines, risk 1)

**By hand today.** `deck.html` 9038-9335, the "speech queue" block, ~297
lines: runs, sentence cutting (`sayCut`), reopening (`sayReopen`), PCM
streamed a tenth of a second at a time into `AudioBuffer`s, one request
ahead, the speechSynthesis fallback. It is a byte-for-byte copy of
`index.html`'s (27595-27892), kept in step by `test/speech.py`. Since
0.172.0 the deck's talk sheet is the console's chat in a frame, which has
its own copy, so the deck uses two of the block's functions: `sayAloud` for
the computer's random announcements (`announce`, deck 9023) and `sayStop`
(sound off). esbuild's tree-shaking drops `sayCut`, `sayReopen`,
`SAY_MIN_SENTENCE` and `SAY_ABBR` from the deck as unreachable.

**Instead.** An announcement is one short line every four to eight minutes,
where streaming buys nothing: `fetch("/say")` whole (mp3, the server's
default), `decodeAudioData` on the deck's already-unlocked `actx`, one
`AudioBufferSourceNode`; `announceSynth` stays the fallback. ~25 lines.
`test/speech.py` then cuts its block from `index.html` (the copy that
streams replies) and its byte-for-byte check goes; ARCHITECTURE.md's "one
code in two pages" goes with it.

**Check on the iPhone.** Sound on in the deck: an announcement is heard
(after the first tap, which unlocks `actx`); sound off stops one mid-line.

### 2. `test/audit.py` (~150-250 lines, risk 1, tests only)

**Today.** 455 lines of static checks on the page's source text: a font is
linked, a selector exists, `"function openMonth(" in src`. Some guard real
constraints no runtime test can see (fonts, contrast, aria on the header);
many assert a function or class by name, which the behaviour suite and
`buttons.py` already exercise for real (round 1 found one asserting a
function nothing called, `monthIndex`).

**Instead.** Keep the checks no test can make (fonts, contrast, aria
labels, constraints on CSS); drop the "this name exists" ones a runtime
suite covers. Each needs a look; the estimate is a third to a half.

**Check.** Nothing on a phone. `run.sh` still green.

### 3. The overlay → `<dialog>` (~60 lines, risk 2)

**By hand today.** One panel, `#ov` > `#dlg` (markup 3742), that some
forty dialogs take turns in: `openDialog`/`openOv`/`closeOv` (9106-9153),
the Tab focus trap over `FOCUSABLE` (9094-9096, 9353-9362), giving focus
back (`ovReturn`), the scrim click (23144), Escape routed through the key
handler, `ovResolve` so a question closed by any route answers "no", and
`#ov`'s CSS (2504-2522: fixed, full screen, z-index, the scrim colour).

**Instead.** `<dialog id="dlg">` and `showModal()`: the top layer, `inert`
everything behind it (no focus trap to write: Tab cannot leave), Escape as
the `cancel` event, focus handed back by the browser on `close()`,
`::backdrop` for the scrim (a click on the dialog's own box outside its
content is the scrim click). `closeOv`'s tidy-up list stays, run from the
`close` event. iOS 15.4+.

**Risk.** The toast must stay above an open dialog: in the top layer only
another top-layer element is, so the toast becomes a `popover="manual"`
(also 17+). The chats' full-screen sheet (`.dlg.chats`) and the deck's
framed console must look the same. The QuickJS shim needs `showModal`,
`close`, `open` and the events. `test/buttons.py` and `test/back.py` cover
open/close by Close, Escape and Back.

**Check on the iPhone.** Every dialog opens and closes; the keyboard over
a dialog's field (Connection, a question) still pans to it; a toast shows
over a dialog; Back from the chats.

### 4. Menus and the speed dial → popovers (~40 lines, risk 2)

**By hand today.** The task-word menu (`taskSwitch`, 19869-20002:
`openMenu`/`closeMenu`, `place()` measuring the chip and the screen, its
own outside-tap and Escape), the FAB's speed dial (18702-18842: `fdOpen`,
`fdClose`, Escape at 18812), the chat's context gauge menu (`#chctx`,
27251, 27316, 27372).

**Instead.** `popover="auto"`: light dismiss (a tap outside), Escape and
the top layer for free; `showPopover()`/`hidePopover()` and the `toggle`
event replace the open/close bookkeeping. The press-hold-slide gestures
stay hand-made (no platform has them). `place()` would go with CSS anchor
positioning, but that is Safari 26 only: not yet. iOS 17+.

**Check on the iPhone.** Hold the FAB and slide to a row; tap outside an
open menu closes it without pressing what is under the finger.

### 5. Folds → `<details>`/`<summary>` (~40-60 lines, risk 2)

**By hand today.** Buttons with `aria-expanded` and a click handler each:
the markdown's foldable branches (`mdRender` 5808, the delegated handler
19740-19764 with its own label and count), the chat's tool-call rows
(`.chtools`, 26379-26381 and their handler), the reader's backlink groups
(`blhead`, 12018-12032), the media fold (4500).

**Instead.** `<details>` with a `<summary>`: open/closed state,
`aria-expanded` and keyboard handling are the browser's; the `toggle`
event keeps the sound and the count. iOS: long supported.

**Risk.** `mdRender`'s output changes shape (the suite, perf at 4000
rows); a markdown branch is an `<li>` with its child list, which has to
become the `<details>` body without changing the reading layout.

**Check on the iPhone.** Fold and unfold a branch in the reader; tap
target size; no selection or zoom on a double tap.

### 6. `copyText` (~12 lines, risk 1)

**By hand today.** 9523-9544: the Clipboard API, and when it is absent (a
plain-http page on the LAN) a throwaway textarea and
`document.execCommand("copy")`.

**Instead.** `navigator.clipboard.writeText` only; plain http then says it
could not copy. Every deployed URL is https; worth asking whether the
plain-http LAN case is still used before dropping it.

**Check on the iPhone.** Copy a day, copy an entry: in the clipboard.

### 7. Debounce timers (~30-50 lines, risk 1-2)

**Today.** 56 `clearTimeout(` sites, many a hand-written debounce
(`x._t = setTimeout(…)` after a `clearTimeout(x._t)`); `deb()` (18640) is
already the page's helper, one timer per control.

**Instead.** `deb()` at each site that is a plain debounce. Per site a
small change; it needs reading each one, since some are not debounces
(cancellable delays, timeouts with a meaning).

**Check.** `run.sh` (the suite drives timers); nothing phone-specific.

### 8. The date + time picker → `datetime-local` (~120-200 lines, risk 3, the captain's call)

**By hand today.** "the date + time pickers" (10843-11099, ~255 lines plus
CSS): one template for created, start and end, invisible native `<select>`s
laid over the hour and minute digits, a quadratic fine slider an hour
either side of an anchor (`pickFine`), offset chips (±15m, 1h, 3h, 24h).
The CalDAV dialog and the stopwatch already use plain `datetime-local`.

**Instead.** `<input type="datetime-local">` per field, the phone's own
wheel; the offset chips can stay (a few lines). The slider and the overlay
selects go.

**Risk.** It is a deliberate design (the comment at 10861 says why the
slider exists: a stamp is usually minutes off); the captain decides.
`test/dates.sh` covers the picker's dates.

**Check on the iPhone.** Set a time to the minute; clear start/end
("unscheduled"); a DST edge.

### 9. Row swipe actions → scroll-snap (~120 lines, risk 3)

**By hand today.** 19265-19450: touch tracking, the release mark, the
spring back, `swipeAte` to swallow the click after a drag.

**Instead.** Each row a horizontal scroller with `scroll-snap-type: x`,
the action panels either side, the action on `scrollend`. Native momentum
and rubber band.

**Risk.** A scroller per row in a windowed list of 4000 (perf.py), the
list's vertical scroll and pull-to-sync competing, iOS's `scrollend`
(Safari 26 only: an IntersectionObserver on the panels instead).

### 10. The reader's page turn → scroll-snap (~60 lines, risk 3)

`swipeTurn` (19075-19172): the page follows the finger, a capsule names
where it lands, springs back at the ends. Scroll-snap would need the
previous and next entries rendered either side; a view transition for the
turn is Safari 18+. High risk to a gesture used daily.

### 11. Day and month names → `Intl.DateTimeFormat` (~15 lines, risk 2)

`WD`/`WDFULL`/`MO`/`MOFULL` (3848-3851) and the builders over them
(`dayWords`, `dayLabel`, `#ambdate`, 26210, the explorer's labels).
`Intl.DateTimeFormat("en-GB", …)` would do it, but current ICU writes
September "Sept" in en-GB, QuickJS has no full Intl (the suite's shim
would need one), and the strings are tested. Not recommended.

## Kept, and why

- **Pull to sync** (`pullSync`, 19197-19263): iOS has no pull-to-refresh
  for an inner scroller, and none in a standalone app; `overscroll-behavior`
  can only switch the browser's off. It stays unless the captain drops the
  gesture.
- **The edge swipe and the drawer swipe** (`flickShut`): a standalone iOS
  app has no back gesture of its own.
- **Where the caret is** (`wikiMirror`, 20475-20652): no API gives a
  textarea caret's coordinates, and anchor positioning cannot anchor to it.
- **The toast's dodging** (`placeToast`, `TOAST_DODGE`): nothing native.
- **Resize and scroll listeners** (23110, 17271, 5425; the chat's
  load-earlier `onscroll`, 27323): a ResizeObserver or an
  IntersectionObserver sentinel would be about as long; not a saving.
- **The phone CSS** (3015-3776): nesting and container queries would
  reorganise it, not shrink it.
- **The History API** (`saveState`, `popstate`, the routes): already the
  platform's, used as it is.

## Round 1 (0.173.1): what went, no behaviour change

- **Dead code.** `monthIndex` (nothing called it; `audit.py` asserted it
  existed, now `calIndex`); the deck's `toast()`, its `#toast` element and
  CSS (left from the talk sheet before 0.172.0); the deck's unused
  `--bg`/`--green`/`--salmon`; an unused local in the list's scroll
  handler; a second, identical `.chstat.working` rule; the QuickJS shim's `createDocumentFragment` and
  `releasePointerCapture`, which the page no longer calls.
- **Duplicates folded.** Five local zero-padders (`p`, `p2`, `crsPad`) into
  `pad2`; the local day, minute and file-name stamps built by hand in eight
  places into `isoDay`, `localInput` (was `crsLocalIso` too) and
  `fileStamp`; the "UTC+03:00" offset built twice into `utcOffset`; "Tue 13
  Oct 2026" built three times into `dayWords`; the edge swipe and the drawer
  swipe, two copies of one handler, into `flickShut`.
- **Stale docs.** ARCHITECTURE.md's voice section still described the
  deck's own talk sheet (`talkSend`, `engSay`, `engSpeak`, `#talksay`,
  hold to talk "in two pages"), and the engineers' `openEng`: now the
  console's chat and its names. `docs/design/chat.md`'s status (built,
  0.156.0-0.172.0); `chat-refactor.md` and TODO.md gave 0.170.0 for the
  deck's talk sheet, which is 0.172.0. Comments naming `fabGo` and
  `swipeBack` name what is there now.
- **Left as they are.** `backlinks()` and `related()` are one-line wrappers
  only the suite calls (its way into the resumable jobs); the deck's
  `sayCut`/`sayReopen` are dead in the deck but must stay while the block
  is a byte-for-byte copy (item 1 ends that).

## Round 2 (0.174.0)

One commit each, so any can be dropped:

- **Item 1.** The deck's `sayAloud` fetches an announcement whole and plays
  one buffer; its copy of the speech queue is gone (deck.html -253 net).
  `test/speech.py` runs the console's block; no byte-for-byte check.
- **Item 7.** Four sites were plain debounces and use `deb()` (now a
  function declaration, so debounces made at load above it can use it):
  `pushSoon`, `noteQuery`, the outbox's kick, the planner's place search.
  The other 50-odd `clearTimeout`s are cancelled from elsewhere (a stop, a
  teardown, a save), vary their delay or carry an argument, and stay. The
  survey's 30-50 lines was high: -7 net.
- **Item 6.** `copyText` is `navigator.clipboard.writeText` only (-14).
- **Item 2.** `audit.py` dropped 46 name checks (-85 net); 156 remain.

