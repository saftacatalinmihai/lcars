# The chat dock, and attachments in the chat — design

Status: **design** (2026-10-16, Lt. Mendez), for the captain's approval. §0, the mount, built 0.229.1 (`chatsMount`); Part 1, the dock, built 0.233.0 (`dock*` in index.html).
Part 2, attachments, built 0.234.0 (`chatFile*`, `chatFiles*` in index.html; the server's transport 0.231.0); what it left is in TODO.md ("One chat: the rest"). It builds on the one chat (`docs/design/chat.md`,
built 0.156.0-0.172.0, and `docs/design/chat-refactor.md`, how): the
Chats list, the thread pane, its composer, its states. Line numbers are
`lcars-ui/index.html` at 0.226.1.

The captain's words, 2026-10-16:

> (a) make the chat also available like Facebook Messenger or LinkedIn or
> other web apps: a smaller overlay on top of the existing window, with a
> chat list and individual chat windows opened at the lower right of the
> screen; he should be able to minimise, close and open them.
> (b) let him upload images or other files in the chat, the same as on the
> Claude web app, and show the image inline if he uploads one, or if a
> crew agent generates images.

Part 1 is the dock (a), Part 2 attachments (b). They are independent:
either can be built first. Each part ends with what it asks of the tests.

---

## 0. What exists, and the one thing in the way

What the dock re-uses, unchanged in what it shows:

| Piece | Where | Used by the dock as |
|---|---|---|
| the list's rows and sections (Computer, Crew with Number One, the queue and the seat, Aboard, Reports, Courses, Archived) | `chatRows` (29957), `chatRowHtml` (29994), `engRowsHtml`, `chatListPaint` (30008) | the dock's list panel, the same rows and search |
| the badge count | `chatBadge` (30030): `chatUnreadTotal() + engAnswerCount()` | the pill's count — the same number as the header's *Chats · n* |
| the thread pane | `chatPaneHtml` (30632), `chatPaneWire`, `chatPaneShow` (30813), `chatDraw` (29839), `chatChrome` | each window's body: header (cut down), log, question card, quotes, composer |
| the message renderer | `chatMsgHtml` (29377), `mdRender` (6298), `mdMedia` (6157) | unchanged; images in markdown already inline |
| the lightbox | `mediaLight` (5610), the page-wide click on `.mdmedia img[data-light]` (5650) | a tap on an image in any window or bubble |
| the media upload | `mediaUploadSend` (5251): XHR with `upload.onprogress`, `POST /entries/<id>/media` | Part 2's progress, whatever the engineers make the target |
| kept-focus taps | `keepKbTaps`, `chatMsgKeepKb` | the window's buttons (the box keeps the focus on a desk too) |

**The thing in the way: the thread pane is one of a kind.** The comment
over `chatPaneHtml` says so — "one of them is up at a time (there is one
dialog), so the ids are the same and everything that draws a thread draws
whichever it is." `#chth`, `#chlog`, `#chq`, `#chsend`, `#chqcard`; the
global `chat` is *the* conversation on screen; `chatDraw` paints only it;
`engStop`/`engPoll` keep one engineer's transcript polled (`eng.timer`).
Three windows side by side need three of each. So the dock's first stage,
before anything visible, is the engineers' refactor of the pane into a
**mount**: `chatsMount(el, conv, {mode})` returning an object that holds its
own elements (classes scoped to the mount instead of ids), its own
conversation, its own paint and poll; the full view and the course sheet's
Navigator become mounts like the dock's windows. `chat` stays as "the
conversation of the focused mount", so the voice orders and keys that act
on "the chat on screen" keep their meaning (§1.9). This is the engineers'
plan to write; the design only requires that a window is the same
component as the full view, never a second renderer (chat.md §1.3 point 3,
the reason the one chat exists).

---

# Part 1 — the dock

## 1.1 Where it is, and where it is not

- **A desk only**: the split view's width and above (`min-width: 900px`,
  the breakpoint at line 2324) **and** a fine pointer (`hover: hover`). An
  iPad in landscape is 1024 wide but a touch screen whose keyboard covers
  the lower half — exactly where the dock lives — so it keeps the full
  Chats, as the phone does.
- **The phone keeps the full-screen Chats as it is**: the header's Chats
  button, the list, a thread, Back to the list. No pill, no windows. A
  window open on the desk's dock means nothing to the phone: the dock's
  state is per device (§1.6).
- **Not in the deck's framed console** (`inDeck()`, 12676). The deck has
  its own talk sheet (the thread, solo), and the framed console is a panel
  in a 3D room, not a desk: a second layer of windows over it would cover
  the console's own content. Its talk sheet stays the way to talk there.
- **A browser window narrowed below 900px** (a desk with two windows side by
  side): the dock folds away — windows and pill gone, their state kept — and
  comes back as it was when the window is widened again.

## 1.2 The pieces

```
                                                         ┌─────────────────────┐
                                                         │ ◆ CHATS        + ⤢ ─│ ← list panel, expanded
                                                         │ [search the chats ] │
                                                         │ seat: Reyes · 2 wait│
                                                         │ COMPUTER            │
  ┌──────────────────────┐ ┌──────────────────────┐      │ ◖CO Computer  2m  ● │
  │◖RE Reyes · working ▮ │ │◖CO Computer  SONNET▾ │      │ CREW                │
  │       OPUS▾  ─ ⤢ ×   │ │ idle         ─ ⤢ ×   │      │ ◖N1 Number One ANSW │
  │                      │ │                      │      │ ◖RE Reyes      • • •│
  │  log …               │ │  log …               │      │ …                   │
  │                      │ │                      │      │                     │
  │ [question card]      │ │                      │      │                     │
  │ [+][your message][➤] │ │ [+][your message][➤] │      │                     │
  └──────────────────────┘ └──────────────────────┘      └─────────────────────┘
 ┌────────────┐┌───────────────┐
 │ +2 more  ▴ ││◖N1 Number One ●│  ← minimised tabs and the overflow tab sit on the
 └────────────┘└───────────────┘    bottom edge, left of the open windows
```

(A window's header is one line; the sketch wraps it for width.)

The layer is `#dock`, a fixed box at the lower right, outside `#ov`
(z-index 48: above the page, under `#ov`'s 50, so a dialog covers it; the
lightbox `#mlight` at 200 is above everything, so an image opened from a
window is never under it).

**The pill** (list collapsed): a 44px-high LCARS pill at the bottom right,
16px from the edges, *◆ CHATS* in Antonio caps, and the count when there is
one (`◆ CHATS · 3`, orange ground when something waits, as `#bChat.hot`).
A red dot on it when the count includes an ANSWER (a question waits). One
click expands it.

**The list panel** (expanded): 340px wide (the split view's list width),
`min(600px, 100vh − 120px)` high, anchored to the bottom right. Its header
is the Chats list's (*CHATS*, the status line *n waiting*, `+` new chat)
with **─** (collapse to the pill) instead of the full view's ‹ close, and
**⤢** (the full Chats view). Then the search field, the seat strip, the
rows — the same `chatRowHtml` rows, sections and badges, the same row
actions (Archive, Dismiss, Mark read: on a desk as today, on the row's
hover). The new engineer's name field at its foot, as in the full list.

**A window**: 340 wide × `min(520px, 100vh − 120px)` high, bottom-anchored,
standing left of the list panel (or of the pill when the list is
collapsed), 8px apart. Its header is **one line**, 40px:

| Avatar | Name | Status | Model chip | ─ | ⤢ | × |
|---|---|---|---|---|---|---|
| the kind's pill colour, initials (`chatInitials`) | `chatTitle`, ellipsis | the status line's text, dim, ellipsis (*working ▮*, *#2 for the seat*, *waiting on your answer* in red) | `OPUS ▾`, opens the model sheet inside the window | minimise | the full view at `chats/<id>` | close |

A click on the header's empty part (name, status) toggles minimise, as in
Messenger. The Voice toggle, the context gauge and ⋯ are **not** in the
window: there is no room in 340px, and what ⋯ holds (New thread, Deploy,
Roll back, Refresh context, Earlier messages, Archive) is one ⤢ away; every
one of them is also a voice order, which acts on the focused window
(§1.9). The rest of the window is the thread, mounted: context card
(collapsed to its one line), log, question card, quote chips, composer.
The talk row (Hold to talk, conversation) is not shown either: a window is
for typing; the full view has it.

**A minimised window**: a tab on the bottom edge, 200 × 36: avatar, name,
and the row's one badge (ANSWER / • • • / unread count / ● marked). A click
opens it again.

**The overflow tab**: when the open windows and tabs no longer fit between
the left edge (16px margin, and clear of the voice HUD `#vhud` at the
bottom left when it is up) and the list, the **least recently focused**
ones fold into one tab, *+2 more ▴*, whose badge is the sum of theirs (red
if any of them has an ANSWER). A click lists them in a small menu above it
(avatar, name, badge, ×); picking one opens it in place of the least
recently focused open window, which folds in its stead. At 1280px wide that
is two open windows and two or three tabs; at 1920, four windows.

The tape deck (`#tdeck`, bottom centre) and the toast (bottom centre) are
counted as taken width: the windows' row never runs under them. When the
tape deck is up and leaves too little, a window folds into the overflow
before it covers the deck.

## 1.3 Acts

| Act | What happens |
|---|---|
| click the pill | the list panel expands, the search field focused |
| ─ on the list, or Esc in it | collapses to the pill; the windows stay |
| a row of the list | that conversation's window opens (or comes back from a tab, or out of the overflow) and is focused, its box focused; the list **stays open** (several can be opened in a row, as in Messenger) |
| a row whose window is open | that window is focused (it flashes its header once); not a second window |
| `+` on the list | a new computer thread, in a window |
| ─ on a window, or a click on its header | minimised to a tab; its draft kept |
| a tab | open again, focused |
| × on a window or a tab | closed: gone from the dock; the conversation itself is untouched (still on the list, its draft kept — the draft is the conversation's, not the window's) |
| ⤢ on a window | the full view, `chats/<id>` (§1.5) |
| ⤢ on the list | the full view's list, `chats` |
| a message arrives in an open window | it paints there as in the full view; read at once if the window is focused and scrolled to the end, else unread on its header (a count beside the name) until it is |
| a message arrives in a minimised one | the tab's badge counts it; the pill's count too |
| a message arrives in a closed conversation | the pill's count and its row on the list; **never opens a window by itself** (the captain's rule) |
| an engineer asks a question (blocked, or Number One's `task_no1`) | ANSWER on their row, their tab or window header, and the red dot on the pill; the question card in their window when it is open |
| a deploy line, a seat change | a system line in that engineer's log as today; a deploy ending in a minimised window is unread (a ✓ or ✕ on the tab for 10 s, then its count) |

A conversation the captain is reading in a focused window is "on screen"
for the unread rules exactly as in the full view (`chatPaneShow` clears
`unread`; an engineer's `engSeen`). A minimised or unfocused window is not:
three windows streaming at once would otherwise all count as read.

## 1.4 The engineers' parts in a window

- **The question card** is in the window above the composer, as in the full
  view, its chips and ↑ ↓ ⏎ Esc minis; it is what the captain most needs
  to reach quickly, and the reason the dock is useful for the crew.
- **Deploy lines** are system lines in the log; Deploy itself is the voice
  order or ⤢ then ⋯ (the confirm it needs reads badly in 340px).
- **The seat strip** lives once, on the list panel under its header, as on
  the full list; an engineer's window says their own place in its status
  (*#2 for the seat · after Reyes*).
- **Earlier messages**: scrolled to the top, the page before, as today.

## 1.5 The dock and the full Chats view

- **A window changes no route.** Opening, minimising, closing a window or
  expanding the list writes nothing to the url or the history: the page
  under it (the day, an entry, the map) keeps its route, and Back is still
  that page's Back. A window is furniture, not a place.
- **⤢ goes to `chats/<id>`** through `chatsOpen`, so the full view's history
  rules are unchanged (the list put under the thread; Back from the thread
  is the list, from the list out of the chats).
- **The full view hides the dock** — my call. Reasons: at a desk the full
  view is the whole screen (`.dlg.chats` is 100vw × 100vh) with the list
  already at its left, so the dock would only cover its composer; the same
  conversation in a window and in the full view would be two boxes for one
  draft and two places the unread rule must agree on; and it gives ⤢ a clear
  meaning: *bigger*, not *another copy*. When the full view closes (Close,
  Esc from the list, Back out of the chats), the dock comes back as it was:
  the same windows, tabs and list state, read marks updated by what was read
  in the full view.
- **Other dialogs** (the queue, the report viewer, settings, the palette)
  are above the dock and cover it; its windows go on streaming under them.
  The entry editor and the reader are in the page: the dock floats over
  their lower right, as Messenger floats over Facebook's feed. The editor's
  own controls are at the top and on the left, so nothing of it is reached
  only through the dock's corner; a window can be minimised in one click
  when it covers what is being read.
- **Opening a chat from elsewhere on a desk** (`talk to {*}`, a report's
  *Chat with*, the reader's *Chat with the …*, `/ui/ask`): **unchanged**,
  the full view, because those are deliberate "go and talk" acts and a
  deep link must work alone. A setting in the list panel's header could
  later send them to a window instead; not in this design (open question 2).

## 1.6 Kept across reloads

`localStorage lcars.dock`, per device, written on every change:

```
{ list: "pill" | "open",
  wins: [ { id: "eng-reyes-x1z", min: false }, … ],  // left to right
  focus: [ ids, most recently focused first ]        // decides what overflows
}
```

On load the dock is drawn from it in the first frame after the list's data
(the chats are local; the engineers' rows appear when `engListFetch`
answers, their windows showing *…* until then). An id no longer found (an
archived and forgotten thread, a removed engineer) is dropped without a
word. Nothing of the dock goes to the journal: it is screen furniture, per
device, like the split view's state — not something the captain or the
crew need to read (CLAUDE.md's rule is for state they should see).

## 1.7 The list's freshness while the dock is up

Today the engineers' list is fetched when the Chats list is painted
(`chatsShow` → `engListFetch`, at most every 4 s), and one engineer's
transcript is polled while their thread is on screen. With the dock the
pill must count a reply in a closed conversation while the captain is in
the journal, so:

- while the dock is shown (pill or list), `engListFetch` runs every 10 s,
  every 4 s while the list panel is open, paused while the tab is hidden
  (`visibilitychange`), at once when it becomes visible;
- an **open** engineer window polls its transcript as the full view does
  (1.5 s) when it is focused, every 5 s when not; a **minimised** one is
  not polled — its tab's badge comes from the list's status and `engUnread`;
- computer, role and navigator threads stream only answers the captain
  asked for, so they need no poll: a stream keeps running in a minimised
  or unfocused window and lands in the conversation as it does now when the
  full view is closed mid-answer.

## 1.8 The keyboard

- **The dock is a focus zone.** While the focus is in it, the page's single
  keys do not fire (as in any field today, `fieldFocused`), and the dock's
  own do:
  - in a window's box: **Enter** sends, **Shift+Enter** a new line (as
    `chatPaneWire`'s `onkeydown`); **Esc** takes the focus out of the box
    to the window (its header), the draft kept; a sheet (the model) or a
    quote's floating button first, as `chatEscape` has it;
  - on a window (focus on its header): **Esc** minimises it and moves the
    focus to the next window to its right, or the list, or the pill;
    **Enter** back into its box; **←** / **→** the neighbouring window,
    tab or the list; **x** closes it; **f** is ⤢;
  - on the list panel: as the full list (↑ ↓ through the rows, Enter
    opens the row's window), **Esc** collapses it to the pill and gives the
    focus back to the page.
- **`B`** (free in `KEYS` today) from the page: into the dock — the last
  focused window, or the list expanded with its search focused. `B` again
  (from outside a field) gives the focus back to the page. It gets a voice
  order and a palette row, as every key must.
- Tab moves through a window's controls in order and then on to the next
  window: the dock's DOM order is left to right, so Tab follows the eye.
- A window's box is focused when the window is opened by a click or a key
  (a desk: chat.md §2.3 rule 3); one restored on a reload is not (the page
  under it has the focus it had).

## 1.9 Voice

Every act gets an order calling the function the button calls. "The chat
window" means the focused one, else the most recently opened.

| Order (aliases) | Does |
|---|---|
| "open the chat window for {*}" ("chat window for {*}", "chat window {*}", "pop out {*}", "dock {*}") | the window for that conversation by name, as `chatTalkTo` resolves names (Reyes, Number One, the yeoman, the computer) — the dock's version of *talk to* |
| "minimise the chat" ("minimize the chat", "minimise it", "minimize it", "minimise the window", "minimize the window", "minimise the chat window", "minimize the chat window") | the focused window to its tab |
| "close the chat window" ("close the window", "close the chat") | the focused window closed |
| "restore the chat" ("open the chat again", "restore the window", "unminimise the chat", "unminimize the chat") | the most recently minimised tab open again |
| "expand the chat" ("full screen chat", "chat full screen", "open it full", "expand the window") | the focused window's ⤢ |
| "show the dock" ("open the dock", "show the chat dock", "the dock", "dock") | the list panel expanded (and the dock back, if hidden by "hide the dock") |
| "hide the dock" ("close the dock", "fold the dock", "collapse the dock", "hide the chat dock") | the list panel to its pill; said again with it a pill already, the whole dock hidden until "show the dock" (kept so in `lcars.dock`) |
| "next chat window" ("next window", "switch window") | focus to the window to the right (the key →) |
| "close all chat windows" ("close all the windows", "close all chats windows") | every window and tab closed |

Spelling: Chrome's and Safari's recognisers are en-US and write
*minimize*; both spellings are aliases.

Checked against `VCMDS` (26675-…), with `vMatch`'s rules (longest phrase
wins; with dictation paused, the whole utterance must match):

- **"close the chat"** is today an alias of *close the chats* (`closeOv`).
  With the dock, *close the chats* keeps "close the chats", "close chats",
  "leave the chats"; "close the chat" moves to *close the chat window*, and
  its function decides: the full view up → `closeOv` (as now); else the
  focused window. Nothing the captain says today stops working.
- **"close the conversation"** is *end conversation* (the microphone), so no
  dock order uses *conversation*.
- **"open {*}"** (pinned entries, 26903) would catch "open the chat window
  for Reyes" if the longer phrase did not win; it does (five fixed words
  against one), and the QuickJS check must prove it. Same for "open the
  dock" against "open {*}", and "show the dock" against "show only {*}".
- **"dismiss"** alone is *close the dialog*: no dock order is "dismiss".
- **"talk to {*}" / "chat with {*}" / "open a chat with {*}"** keep opening
  the full view; the dock's own verb is *chat window* / *pop out* / *dock*.
- **"next unread"** stays the full view's; in the dock it opens the next
  unread conversation's window when the full view is not up (one function,
  two hosts).
- **"hide the list"** / "show the list" (the entries' list) do not collide
  with *the dock*; "the dock" and "dock" alone are new single phrases, and
  no existing order is *dock*.
- The orders that act on "the chat on screen" (*send it*, *stop the
  answer*, *switch model to {*}*, *quote that*, *answer {n}*, *deploy {*}*,
  *archive this chat*, *mark read*) act on the focused window when the full
  view is not up — `chat` is the focused mount's conversation (§0).

## 1.10 Immediate feedback

| Act | At once (same frame, no network) | Later |
|---|---|---|
| click the pill | the list panel grows out of the pill (motion.md's `openOut`, 160 ms; none with reduced motion), rows from what is cached | the engineers' rows refresh when `engListFetch` answers |
| open a window from a row | the window grows out of the row, its header and the cached log drawn, status *…* for an engineer; the row marked as open (a thin bar in its colour on its left) | the fresh transcript replaces the cached one |
| a row whose window is open | that window's header flashes amber once | — |
| minimise | the window shrinks into its tab (the tab is there in the same frame) | — |
| restore a tab | the tab grows into the window, the box focused | an engineer's poll resumes and repaints |
| close | the window and its tab gone; the row's open bar gone; a toast *Closed · Undo* for 4 s (the same window back, where it was) | — |
| ⤢ | the window's header pressed, the full view slides in over it (the dock hidden in the same frame) | — |
| send in a window | as the full view (chat.md §3): box cleared, bubble *sending…*, Send→Stop; the list row jumps to the top | *delivered* / *queued #2* / *✕ not sent, Retry* in that window |
| a message in a closed conversation | — | the pill's count goes up with a single pulse (none with reduced motion); the row's badge |
| a question waits | — | the red dot on the pill, ANSWER on the tab or header |
| a voice order | the act's own feedback above, plus the HUD's echo of the order | — |
| a click on the overflow tab | its menu, at once | — |
| a name not found ("chat window for Worf") | a toast *no chat with Worf* | — |

## 1.11 Performance

Two or three windows streaming at once must hold the frame budget (60 fps
at p99, ≤ 16.7 ms main-thread per frame). What makes it so, for the
engineers:

- **one rAF for all mounts**: a stream marks its mount dirty; one frame
  callback paints every dirty mount, and in each only the live bubble
  (the keyed renderer of chat-refactor.md §2, which the full view has);
- the dock is `contain: layout paint` and each window `contain: strict`,
  so a window's growing bubble re-lays out that window only, never the page
  under it; the page's scroll does not repaint the dock (its own layer);
- a minimised window paints nothing but its badge; an engineer's transcript
  is not fetched while minimised (§1.7);
- the list panel repaints on `engListFetch` only when it is expanded; the
  pill only its count.

**Scenario to add to `test/perf.py`: `dock-stream`** (desk, 1440 × 900,
the 4000-row synthetic journal): the dock restored with three windows open
— two computer threads of 200 messages each and an engineer's 200-message
transcript — then 300 deltas streamed into each computer thread,
interleaved, while the engineer's transcript is repainted by three polls
and the page under the dock is scrolled; p99 ≤ 16.7 ms. And
**`dock-scroll`**: the existing `scroll` scenario with the same three
windows up and idle, which must cost what `scroll` costs (the dock's layer
is not repainted). `test/changed.py` maps the dock's block to both.

## 1.12 What the tests need (Part 1)

- `test/buttons.py`: at desk size the pill, every list-panel button, a
  window's ─ ⤢ ×, a tab, the overflow menu; at phone size no `#dock` at all;
  in the deck frame none.
- `test/back.py`: a window opened, minimised and closed changes neither
  `location` nor `history.length`; ⤢ then Back is the list, Back again the
  page that was under it, with the dock as it was.
- QuickJS: `lcars.dock` restored (open, minimised, order, an unknown id
  dropped); overflow by least recent focus; a message to a closed
  conversation counts on the pill and opens nothing; unread in an
  unfocused window; the voice orders of §1.9 and their collisions with
  `vMatch`; `B` has its order.
- `test/keyboard.py`: nothing new on a phone (no dock); the dock's box is
  16px like the full view's, so a tablet that does get it does not zoom.
- `test/perf.py`: §1.11.

---

# Part 2 — attachments

Chat.md §2.7 is the base: attached items as chips above the box (× to
drop) and as a card in the sent bubble; *This entry* and *An entry…* as
context; a photo or a file through `+`; a picker needs a tap, so no voice
order for it. This part designs the files.

## 2.1 Which conversations take files

A conversation shows `+` only when its other side can receive a file
(`caps.attach`, chat.md §2.1): the computer's threads, a role's thread, an
engineer, Number One, a person later. The navigator (embedded in its
course sheet) and the deck's crew personas do not, until their adapters
carry it. The captain never picks a file only to be told afterwards that it
cannot go.

## 2.2 Getting a file in

- **`+`**, left of the box (the composer's one row, chat.md §2.2: `+`, the
  box, Send). A tap opens the browser's file picker **at once**, with
  `multiple` and no `accept` filter: on an iPhone its own sheet already
  offers *Photo Library*, *Take Photo or Video* and *Choose File*, and
  Android's chooser offers the camera too — so the camera needs no button
  of ours, and the common case is one tap, not two. (§2.7's *This entry* /
  *An entry…* do not sit behind `+`, which would make every photo two taps:
  see the suggestion chip below, and `#123` typed in the box, which is a
  link chip in the bubble already.)
- **The picker needs a tap.** iOS opens a file input only inside a user's
  gesture, so `+` is a plain button, not a kept-focus one (`keepKbTaps`
  presses on pointerup, which is still a gesture on a touch, but the
  picker takes the focus anyway and the keyboard goes down regardless).
  **No voice order opens the picker**; this is said in the help panel
  (the attachments line: "files: tap +, paste or drop — a picker cannot be
  opened by voice") and goes into the commit and TODO.md per CLAUDE.md.
- **Paste** (desk, and a phone's paste too): an image or a file on the
  clipboard, pasted into the box, becomes a chip; pasted text stays text.
- **Drag and drop** (desk): a file dragged over the full view's thread, or
  over a dock window, lights that pane with an amber dashed inset and
  *Drop to send to Reyes*; dropped, it is a chip in that conversation's box.
  Dragged over a minimised tab for 600 ms, the tab opens (as a Finder
  folder springs open) so the drop lands in its window. Dropped anywhere
  else in the page, nothing happens (the page has no drop of its own
  today; over the dock the browser's default, opening the file in the
  tab, is prevented, so a near miss does not leave the app).
- **This entry**: when an entry is open behind the chat (the reader, the
  editor), a dim suggestion chip sits above the box, *＋ #812 Retezat loop*;
  a tap makes it a real context chip. Voice: "attach this entry" (chat.md
  §2.8, not yet built), and it is the only attachment a voice order makes.

## 2.3 Before it is sent: the chips

Above the box, in the row the quote chips use (`#chquotes`), one chip per
file, in the order added:

```
 ┌──────┐ ┌──────────────────────┐ ┌──────┐
 │[img] │ │ 📄 plan.pdf  1.2 MB  │ │[img] │
 │ ▓▓▓░ ×│ │ ▓▓▓▓▓▓░░░░        × │ │  ⚠  ×│ ← too big: red, says why on hover/tap
 └──────┘ └──────────────────────┘ └──────┘
```

- an **image**: a 56 × 56 thumbnail (cover-cropped, from the file itself on
  the device, before any upload), × in its corner;
- **any other file**: an icon by type (document, sheet, audio, video,
  archive, other), its name (ellipsis in the middle, so the extension
  shows), its size;
- **the upload starts when the chip appears**, not on Send: by the time
  the message is typed the file is usually there. A thin bar along the
  chip's foot fills with progress (`upload.onprogress`, as
  `mediaUploadSend` does); done, it disappears.
- × drops a chip at once (its upload aborted, or what was uploaded let go —
  the engineers' matter).
- Send is enabled with only files and no words: an image alone is a message.

## 2.4 States

| State | On the chip | On the bubble (if already sent) |
|---|---|---|
| uploading | progress bar, the thumbnail at 60 % | the tile with the same bar; the bubble's mark *sending… · uploading 2 of 3* |
| done | plain | the tile plain; the mark moves on to *delivered* when the message goes |
| failed | red edge, *failed · Retry* (a tap retries the upload) | the bubble *✕ not sent: plan.pdf did not upload · Retry*; Retry retries the file, then sends |
| too big | red edge, ⚠, *too big · 25 MB at most* (the limit is open question 5); never uploaded | — (a too-big chip blocks Send, which says *remove plan.pdf* in its title) |
| offline | dim, *waits for the network* | the message waits with it: *offline · goes when back*, kept in the outbox as the entries' media are (`obQueueMedia`); sent, in order, when the network is back |
| a type the other side cannot read | the chip plain; under the bubble's tile, once delivered, a dim line *Reyes gets the file; this kind only as a file* | — |

**Send while uploading**: the message is sent from the captain's side at
once (bubble *sending…*, the box clear, the chips gone into the bubble as
tiles with their bars), and goes to the other side when its last file is
up. A failed file does not lose the words: they are in the bubble with
Retry, and given back to the box if the captain cancels.

## 2.5 After it is sent: the bubble

- **Images** inline in the captain's bubble, above its words: one image at
  its own aspect, up to 320 px high in the full view, 220 in a dock window,
  never wider than the bubble; two to four as a grid of squares; more than
  four, three and a *+n* square. A tap opens the lightbox the entries' images
  use (`mediaLight`; Esc closes it, as today; new: from a grid, ← →
  step through the bubble's images). The full-size file is loaded only by the
  lightbox; the bubble shows a thumbnail-sized one when the server makes
  them (open question 6), the file itself `loading="lazy"` until then.
- **Video and audio** play inline as markdown media do (`mdMedia`).
- **Any other file**: a tile — the type's icon, the name, the size, and
  ↓ (download) / ↗ (open in a new tab: a PDF in the browser's viewer).
- **Delivered**: the bubble's mark is the chat's own (*delivered*, *queued
  #2 for the seat*); the file needs no mark of its own beyond its tile
  being plain. What the agent *did* with it shows in the answer, as every
  tool step does: a chip in the turn's *⚙ n steps* (e.g. *looked at
  IMG_2041.jpg*, *read plan.pdf*). The captain sees the file went, and that
  it was opened, without a second protocol.
- **What the agent can do with it** is said once, before the first file is
  sent in a conversation, as the `+` button's tooltip on a desk and a dim
  line in the chip row the first time on a phone: *the computer sees
  images and reads documents* / *Reyes gets the file in the worktree:
  images, documents, code*. The exact wording waits for what the engineers
  find each side can do.

## 2.6 Images the other side sends

An answer's images show inline as an answer's markdown does already
(`mdRender` → `mdMedia`, `.mdmedia img[data-light]`, a tap opens the
lightbox). What counts as an image in an answer:

1. markdown `![alt](src)`, when `src` is under the media root or an
   https URL (`mdMediaSrc`) — **already so**;
2. a markdown link `[text](src)` to an image, video or audio — **already
   so** (it plays in place, the text its caption);
3. **new: a bare media path or URL on a line of its own** (`/media/…/x.png`,
   or the page's own `https://…/media/…`): shown as if written `![](…)`.
   An agent that writes "saved to /media/chat/plot.png" in a sentence gets
   a link, not a picture: only the line by itself is the picture, so prose
   that mentions a file is not broken up;
4. **new: an engineer's published report** (`report.py publish` prints its
   link): a **report card** — the report's title, its type (HTML, PDF,
   chart, CSV), *Open* (the report viewer, `reportView`, as a report link
   in markdown already does) — instead of a bare link. A chart published
   as an image is case 3 and shows itself;
5. **not**: an image URL on another site written bare (the page would fetch
   from a stranger on its own; markdown `![…](https://…)` is the agent
   choosing to, and is kept), and a path outside the media root (a
   worktree's `/tmp/plot.png`): the page cannot fetch it. An agent that
   makes an image publishes it under the media root (a report, or however
   the engineers let a chat agent put a file there) and links it.

Where an answer's image is too big to load, or gone, `mdMediaBroken`'s
link-out stays the fallback.

## 2.7 Voice

- The picker: **none**, a browser rule (§2.2). Paste and drop are a hand's
  acts too.
- "attach this entry" (chat.md §2.8): the entry open behind as context.
- "drop the attachments" ("remove the attachments", "clear the
  attachments", "no attachments"): every chip in the focused box gone.
- "show the picture" ("open the picture", "show the image", "open the
  image"): the newest image in the conversation on screen in the
  lightbox; ← → through the thread's images from there.
- Collisions: "dismiss" and "close …" are taken (dialogs, the chats); *drop*
  and *picture* are not used by `VCMDS` today; "show the image" must be
  checked against "show only {*}" (longer literal phrase wins).

## 2.8 Immediate feedback

| Act | At once | Later |
|---|---|---|
| tap `+` | pressed; the picker opens (the browser's) | — |
| files picked, pasted or dropped | a chip per file with its thumbnail or icon, at 60 %, bar at 0 | the bar fills; plain when up |
| drag over a pane | the amber dashed inset and *Drop to send to …* | — |
| × on a chip | the chip gone | — |
| too big | the chip red with the limit, before any upload | — |
| Send with files | bubble with the tiles and their bars, *sending… · uploading 1 of 2* | *delivered*; or *✕ not sent* with Retry on the bubble |
| Retry | the tile's bar back at its last point, *sending…* | as Send |
| offline | the chip dim *waits for the network*; a sent bubble *offline · goes when back* | sent when the network is back |
| tap an image | the lightbox, with the thumbnail already there, full size when it loads | — |
| an answer with an image | the image's box reserved at once (from `width`/`height` when known), so the log does not jump when it loads | the picture |

## 2.9 What the tests need (Part 2)

- QuickJS: the chip states (uploading, done, failed, too big, offline)
  against a fake upload; Send with only files; the bubble's grid for 1, 2,
  4, 6 images; the bare-media-line and report-card rules of §2.6 (and that
  a path mid-sentence stays a link); the voice orders of §2.7.
- `test/offline.py`: a file picked offline waits, and goes in order.
- `test/buttons.py`: `+` at both sizes (the picker itself is not pressed),
  a chip's ×, an image's lightbox and Esc.
- `test/recording.py` or its own: a real upload through the scratch
  server, the progress events, and the lightbox on the stored file.
- `test/perf.py`: the `chat-thread` scenario with a third of its messages
  holding an image grid (the log's scroll must not decode full-size files).

---

## 3. Build order (a proposal for the engineers)

1. **The mount** (§0): the pane as `chatsMount`, several at once, the
   full view and the navigator on it. No visible change; patch version.
2. **The dock** (Part 1): pill, list panel, windows, tabs, overflow,
   `lcars.dock`, the list's background fetch, keys and voice, the perf
   scenarios. Minor version.
3. **Attachments, the captain's side** (Part 2 §2.2-2.5, 2.7-2.8) with the
   file transport of the computer's threads first, then engineers. Minor.
4. **Images from the other side** (§2.6's new cases 3 and 4). Patch or
   minor, whichever it turns out.

Steps 3-4 do not need step 2: attachments could ship first in the full
view.

## 4. Open questions for the captain

1. **The full view hides the dock** (§1.5). Agreed, or should the windows
   stay over the full view as they do on Facebook?
2. **"Talk to Reyes" on a desk**: the full view (as now, designed), or a
   dock window? A setting could choose.
3. **Esc on a window minimises it** (designed: nothing is lost). Messenger
   closes it. Which?
4. **An iPad**: no dock (designed, its keyboard covers the corner), or the
   dock in landscape with a hardware keyboard?
5. **The size limit per file**: 25 MB proposed for the chat (the server
   takes up to 1 GB per media file; a phone on a cell link and the agents'
   own limits argue small). Videos larger?
6. **Thumbnails**: should the server make small copies of images (a bubble
   loading a 12 MP photo per image costs a phone), or is a lazy full image
   enough for now?
7. **Where a chat's files live** in the journal (§2.7 of chat.md proposed a
   scratch entry per upload): the engineers' to propose, but the captain may
   want them findable among his media, or kept apart.
