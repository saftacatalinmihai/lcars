# One chat — design

Status: **built** (design 2026-10-11, Lt. Mendez), in the stages of
`docs/design/chat-refactor.md`, 0.156.0-0.172.0 (the deck's talk sheet the
last). §1 is the survey as it was at 0.155.0; the keyboard fit it and §2.3
describe was taken out in 0.161.1 (the browser's own keyboard handling). The mockup was `lcars-ui/mockups/chat.html`,
deleted when the engineers moved in (0.159.0; it is in the git history).

The captain talks to five things in the web console today, through four
different screens, each with its own idea of what a message, a Send button and
an iPhone keyboard are. This document surveys them and designs one messaging
interface — a list of conversations and a thread, as in Messages or WhatsApp
— that all of them, and later real people, live in.

---

## 1. Survey: the chats as they are (0.155.0)

### 1.1 At a glance

| | **Ask** (the computer) | **Role chat** (a crew role's reports and the talk about them) | **Engineers** (Crew view) | **Number One** | **Navigator** (a course) |
|---|---|---|---|---|---|
| Opened by | header Ask, `A`, palette, `/ui/ask`, "ask {…}" | a role's row on the Chats list (its report, or its thread), the day's ops pin, "crew report {role}", `/ui/crew/<role>`; an entry's *Chat with the …* button, "chat with the writer", "talk to the yeoman" — all the thread, never a report dialog (0.178.0) | header Crew, `W`, `/ui/engineers/<name>`, "talk to {…}", "engineer {…}" | Crew view's *Number One*, header *No.1 asks*, "number one {…}" | course sheet's *Navigator* tab, `n` in a course, "navigator {…}" |
| Code | `openChat`, `chatSend`, `chatPost`, `chatEvent`, `chatMsgHtml` | `crewOpen`/`crewChat` → `crewRoleChat` → the thread with `chat.role`/`chat.pre`; `crewLog` puts the reports in its log | `openEng`, `engOpen`, `engPoll`, `engSay`, `engPaint` | `engNo1`, `engNo1Refresh` + the engineer screen | `navSend`, `navDraw`, `crsNavBrief`, `crsRevise` |
| Who answers | Claude via `POST /chat` (lcars skill, lcars-cli only) | same, primed as the role (brief + report as first-message context) | a Claude Code session in a git worktree (`engineer.py`) | same, the engineer named `number-one` | `POST /chat`, primed as navigator; **no history** — every order is a new conversation with the plan |
| Transport | `fetch` + SSE read by hand; streams token by token | same | engineer routes, **polled** every 1.5 s (`?off=` bytes) | same | same as Ask |
| Thread kept | one thread, `localStorage lcars.chat`, last 40 messages, Claude `session_id` | **replaces the Ask thread** (`chatNew`) | the server's transcript; earlier pages on scroll-up | same | per course, `localStorage lcars.nav`, 40 messages, read-only history |
| Model | picker (Sonnet/Haiku/Opus/Fable), takes effect next message | the Ask picker | **none**: `engineer.py` starts every session with `LCARS_ENG_MODEL` (default opus) | none | silently whatever Ask's picker says |
| Send button | *Send* ↔ *Stop* (red) while streaming | same | *Say*; *Stop* (sends Esc) while working **and the box is empty** | same + *Refresh context* | *Send* ↔ *Stop*; keeps the box focused on tap (0.148.0) |
| What a reply shows | markdown, `#123` → entry link, tool chips (`$ lcars-cli …`, amber running / red failed), blinking ▮ *working*, error line, meta `model · 4.2s · $0.012` | same | markdown, tool chips, *working ▮* while status is working | same | same as Ask, plus *"The new plan is #N; the old one is kept"* and a toast with Undo |
| Optimistic message | user bubble at once | same | pending bubble at 60 % opacity until the transcript has it | same | user bubble at once |
| States shown | working, streaming, error, stopped | same | status line: working / idle / done / **waiting on your answer** / **queued for the seat** (#n in line) / off duty / out of reach; git line; deploy state; preview link | same | tab gets a *busy* mark when folded away |
| Special | spoken question → working burble, spoken answer, first cited entry opens behind; answered while closed → toast *Open* | the reports are the role's messages in the log, oldest first, each before the first of the captain's words sent after it (newest 10, *earlier reports* above); context rides on the first message only | **blocked**: their screen + a button per numbered answer + ↑ ↓ Enter Esc; Deploy (confirm), Roll back; Add / Dismiss / Bring back; the seat (holder, queue, waiting) | header badge *No.1 asks · n* from open `task_no1` entries; started on demand ("reporting… up to a minute") | answer may end in a ```json trip fence → new entry, old soft-deleted, Undo |
| Voice | "ask {…}" (answer spoken) | "chat with the writer" | "talk to {…}", "engineer {…}", "new engineer {…}", "dismiss / bring back engineer {…}", "earlier messages" | "number one", "number one {…}", "refresh number one" | "navigator {…}" (answer spoken) |
| Keyboard (iPhone) | generic `keyboardFit`: `#ov` fitted to `--vvtop/--vvh`, `#chatlog` scrolled to the end | same | same (re-uses the `#chatlog` id so the fit finds it) | same | **its own rules**: the sheet goes full height, grip/summary/footer hidden (`html[data-kb] #dlg.course …`); Send `preventDefault`s pointerdown so the keyboard stays |

Out of scope but related: the **deck's talk sheet** (`deck.html`, `talkSend`,
`#talkq`) — crew personas via `/chat`, 12 messages per person, its own
keyboard fit (0.118.2) and its own engineer screen. Phase 5 below.

### 1.2 The keyboard, fixed five times

| Version | What broke | Fix |
|---|---|---|
| 0.118.2 | deck sheets under the keys | deck follows `visualViewport` |
| 0.121.1 | Ask and Engineering boxes under the keys | `keyboardFit` for console dialogs, `--vvtop/--vvh` |
| 0.126.1 | one-line `<input>`s (engineer name) still covered | detect "visible part much shorter", not "bottom hidden" |
| 0.128.1 | a field tapped while data loads lost the keyboard | `fieldFocused()` guard; `test/keyboard.py` |
| 0.148.0 | navigator Send closed the keyboard, tap lost | pointerdown `preventDefault` on Send — **navigator only** |

Each chat inherited a *different subset* of these. Ask and engineers still
lose the keyboard when Send is tapped; the navigator's full-height trick lives
in course-only CSS. One component fixes it once.

### 1.3 What is wrong with having four

1. **No inbox.** Nothing says "Reyes answered", "Number One asks", "the
   navigator is done" in one place; each is a toast, a header badge, or nothing.
2. **One Ask thread.** A role chat throws the current Ask thread away.
3. **Three renderers** (`chatMsgHtml`, `engPaint`'s loop, the deck's
   `paintTalkLog`) and two meanings of `#chatlog`.
4. **Model choice is uneven**: Ask has it, the navigator borrows it unseen,
   engineers cannot change theirs at all.
5. **Feedback is uneven**: Ask shows a bubble at once; Say on an engineer
   shows a faded bubble but the *queued for the seat* answer arrives as a
   toast that then vanishes; Deploy shows nothing until the dialog reopens.
6. **Labels differ** for the same act: Send / Say / Stop / Esc.

---

## 2. The design

### 2.1 Model: conversations, participants, messages

Nothing below assumes the other side is an AI. Tools, models and streaming
are *capabilities* a conversation may have.

```
Participant { id, name, kind: captain|computer|role|engineer|no1|navigator|person,
              colour, initials, subtitle }
Conversation {
  id,                       // "computer:<n>", "role:crew_ops", "eng:reyes-x1z",
                            // "eng:number-one", "nav:<entry id>", "person:<handle>"
  title, with: [participant ids],
  transport: "chat" | "engineer" | "person",
  caps: { stream, stop, model, context, attach, questions, deploy, earlier, voiceReply },
  model?,                   // per conversation, changeable at any time
  context?: [ContextItem],  // pinned: a brief, a report, a course plan, an entry
  status,                   // see 2.6
  unread, lastAt, pinned, archived
}
Message {
  id, conv, from,           // a participant id
  at, parts: [ text(md) | tool | attachment | question | system ],
  state,                    // see 2.6
  meta?: { model, seconds, cost }
}
```

**Transports** are adapters with one interface — `send(conv, text, attachments)`,
`stop(conv)`, `setModel(conv, m)`, `answer(conv, key)`, `poll/stream →
onMessage/onStatus`:

- `chat` — `POST /chat` (today's `chatPost`); Ask, role chats, the navigator.
  The navigator's adapter keeps its rule: every order a fresh session with the
  brief and the plan (`sid` dropped).
- `engineer` — the engineer routes (today's `engApi`); engineers, Number One.
- `person` — later. Messages as journal entries of a `msg_*` kind (the journal
  is where state the captain should see lives — CLAUDE.md), or a `/messages`
  route; delivery receipts instead of streaming. The list, thread and composer
  need no change for it.

Conversations are persisted per device as today (`localStorage`), except
engineer transcripts, which stay the server's. The **list** is built from
both: local computer/role/navigator threads, plus `GET /engineer`.

### 2.2 Screens (phone first)

The chat is a **full-screen view**, not a bottom-sheet dialog: route
`/ui/chats` (list) and `/ui/chats/<id>` (thread). `/ui/ask` and
`/ui/engineers/<name>` keep working and land in the matching thread.
At ≥ 900 px wide it is a split: list left (320 px), thread right.

**List (Chats)** — LCARS header bar *CHATS* with an elbow, a search field,
then sections:

1. **Pinned** — *Computer* (the newest Ask thread) and *Number One*.
2. **Crew** — engineers, newest activity first; dismissed ones folded under
   *Dismissed (n)* as today.
3. **Reports** — a role appears once it has a report unread or a thread.
4. **Courses** — navigators of courses that have messages.
5. **People** — later.

A row: a coloured LCARS pill avatar (initials; colour by kind — computer
orange, roles purple, engineers blue, Number One gold, navigator green,
people salmon), name, one-line preview of the last message (*"You: deploy
it"*), time, and **one** state badge, the most urgent:

| Badge | Meaning |
|---|---|
| red pill **ANSWER** | waiting on your answer (blocked / a `task_no1` question) |
| amber animated **• • •** | working / streaming |
| dim **#2 SEAT** | your message is queued for the seat |
| orange count | unread messages |
| dim *off* | off duty |

The seat line (holder · next · waiting) sits under the header as one dim
mono strip, tappable to expand — today's `engseat`.

A `+` in the header: *New computer chat*, *New engineer…*, *Talk to a role…*.
Swipe a row left: *Dismiss* (engineer) / *Archive* (computer thread); right:
*Mark read*. Every swipe action is also in the thread's ⋯ menu (voice and
desktop reach it there).

**Thread** — header: back chevron (`‹ Chats`, with the unread total), avatar,
name, status line under it (*working · eng/mendez-c35 · 2 to deploy*),
right side the **model chip** (`OPUS ▾`) and **⋯** (New thread, Deploy, Roll
back, Refresh context, Earlier messages, Dismiss, Open the map / back to the report in the log).

Then the log:

- **Captain's bubbles** right, `--panel2`, rounded 18/18/4/18, the delivery
  mark under the last one: `sending…` → `✓ delivered` → `✓✓ read` (person) /
  `⏳ queued · #2 for the seat` / `✕ not sent · tap to retry`.
- **Their bubbles** left, black with a 4 px left bar in their colour
  (today's `.cm.a`), markdown, `#123` as a link chip to the entry.
- **Tool steps** collapsed to one chip per turn: `⚙ 6 steps` (amber while one
  runs, red if one failed); tap to expand into today's mono chips.
- **Meta** under a finished answer in dim mono: `sonnet · 4.2s · $0.012`.
- **System lines**, centred, dim: day separators, *Model → Sonnet from here*,
  *Deploy under way…* → *Deployed ✓ 0.156.0*, *New plan #812 (old #807 kept)
  · Undo*.
- **Context card**, pinned at the top of a thread that has one: *Context:
  Ops brief #771 · role brief* — tap to read it. It is sent with the first
  message (as `chat.pre` is today) and stays visible so the captain knows what
  the other side was told.
- **Question card** (engineer blocked / Number One asks): sticky above the
  composer, their screen in mono, a chip per numbered answer, plus ↑ ↓ ⏎ Esc
  in a row of minis. Answering it collapses the card into a captain bubble
  (*"Answered: 1. Yes"*).

**Composer** — one row: `+` (attach), the text box (pill, grows 1–6 lines,
16 px so iOS does not zoom, `enterkeyhint="send"`), the mic, and **Send**.
While the other side works and the box is empty, Send *becomes* Stop (red
square); typing turns it back into Send (queues the next message — for an
engineer that is today's behaviour, for `/chat` it stops and sends).

### 2.3 The composer above the iOS keyboard — once

The thread is a column: header (fixed height), log (`flex:1; min-height:0;
overflow-y:auto`), cards, composer (auto height). The column is
`position:fixed; top:var(--vvtop); height:var(--vvh)` — the variables
`keyboardFit` already maintains (and reads from the deck's window when
framed). With the keyboard down they are `0` / `100dvh` and the composer pads
`env(safe-area-inset-bottom)`; with it up the composer's foot *is* the
keyboard's top, nothing else moves, and the log keeps its newest line in view
if it was at the end.

Rules the component carries, so no chat needs its own:

1. Send, Stop, the answer chips and the model chip `preventDefault` on
   `pointerdown` when the box has focus — the keyboard never drops on a tap
   (the navigator's fix, for everyone).
2. The text box is a `<textarea>` (iOS does not scroll the page to it).
3. No late `.focus()` without `fieldFocused()`; on a phone the box is **not**
   focused when a thread opens (the keyboard would hide the conversation one
   came to read); on a desk it is.
4. The log is "stuck to the end" only when the reader was at the end (60 px),
   as `chatDraw` does.
5. `test/keyboard.py` gets one line per *mount* (view and navigator embed),
   not one per chat.

### 2.4 Model picker

The chip in the thread header names the model that will answer the **next**
message. Tap → a small sheet (pressed state at once): Fable, Opus, Sonnet,
Haiku, each with a one-line *what it is for*, the current one ticked.
Choosing one:

- closes the sheet, changes the chip **immediately**, and posts a system line
  *Model → Sonnet from here*; the thread goes on — nothing is reset;
- `chat` transport: stored on the conversation, sent as `model` with the next
  `POST /chat` (the server's `g_chat_models` is the menu, as today);
- `engineer` transport (needs server work, phase 3): `POST
  /engineer/<name>/model {model}` → `engineer.py model <name> <model>`, which
  types `/model <model>` into their Claude Code session when they are idle (or
  queues it before the next message), and records it so a restart starts with
  `--model <model>`. The chip shows `SONNET ⋯` (pending) until the engineer's
  status reports the model, then `SONNET ▾`; a refusal reverts it with a red
  system line;
- the navigator gets **its own** model (per course conversation, default the
  last one used), no longer Ask's in secret;
- a person has no chip.

Each answer's meta line names the model that actually ran, so a switch is
visible in the history.

### 2.5 The navigator, embedded

The course sheet's *Navigator* tab mounts the same thread component in
**embedded mode**: no list, no back chevron; its header shrinks to a single
line (status · model chip · ⋯) under the sheet's tabs; log, cards and composer
are identical. When its box takes focus on a phone, the component asks its
host to go full height (`onWantFull`), which the course sheet does — the same
outcome as today's course-only CSS, but the rule lives with the chat.

The conversation id is `nav:<entry id>` and follows the course through a
revision (`crsNavFollow`). In the Chats list a course with messages has a
row; opening it shows the thread full-screen with a context card *Course
"Retezat loop" #812 · Open the map*, and sending from there works the same —
the plan is read from the entry (saved first, as `navSend` does).

### 2.6 States

**Conversation status** (one at a time, the badge in the list, the line in
the header):

| State | From | Shown |
|---|---|---|
| idle | default | nothing, or *idle · 3m ago* |
| starting | engineer being started (≤ 1 min) | *reporting for duty…* with the ▮ blink |
| working | stream open / engineer status working | amber • • • ; header *working* ; Send→Stop |
| streaming | text arriving | the bubble grows; ▮ at its end |
| queued | engineer not in the seat | *#2 in line for the seat · after Reyes* |
| needs answer | blocked / open `task_no1` | red ANSWER; question card |
| off | off duty | dim *off duty — a message brings them back* |
| unreachable | engineer's host asleep | dim *out of reach* |
| deploying | deploy queued/running | system line with ▮; ⋯ Deploy disabled |
| error | last request failed | red line under the bubble, Retry |

**Message state** (captain's): `sending → delivered → (queued) → answered`,
or `failed`. Theirs: `live → done | stopped | error`.

### 2.7 Context and attachments

What exists today is kept and shown: a role chat's brief and report, a
navigator's plan, the *"About your report …"* prefill (now a context card,
not text in the box). New, through `+`:

- **This entry** — the entry open behind the chat, as `#id` context;
- **An entry…** — the palette's entry search;
- **Photo / file** (phase 4) — upload as an attachment of a scratch entry,
  referenced by id. A file picker needs a tap (iOS), so it has no voice order;
  say so in the commit and TODO.md, per CLAUDE.md.

Attached items appear as chips above the box (× to drop) and as a card in the
sent bubble.

### 2.8 Voice orders

Every action above has a `VCMDS` line calling the same function as the
button. Existing orders keep working and open the new screens. New:

| Order (aliases) | Does |
|---|---|
| "chats" ("show the chats", "messages", "the inbox") | the list |
| "next unread" ("unread messages") | opens the next conversation with unread, or *nothing unread* |
| "back to the chats" ("back to the list") | thread → list |
| "new chat" ("new computer chat", "start a new chat") | a new computer thread |
| "send it" ("send the message") | sends what dictation typed into the box |
| "stop the answer" ("stop answering", "stop working") | Stop |
| "switch model to {*}" ("model {*}", "use model {*}") | the model picker's choice, by name |
| "which model" | says and toasts the current model |
| "answer {n}" ("option {n}", "choose {n}") | presses a numbered answer on a question card |
| "read the last message" ("read it out") | speaks the newest reply |
| "attach this entry" | the open entry as context |
| "deploy {*}" (existing deploy flow) | the ⋯ Deploy of that engineer, with its confirm |
| "earlier messages" (exists) | the page before |
| "mark read" / "archive this chat" / "dismiss engineer {*}" (exists) | the swipe actions |

Collision checks for phase 1 (`vMatch`, longest phrase wins, whole utterance
with dictation paused): "stop" alone is the timer's alias — hence *stop the
answer*; "use …" collides with *use the suggested kind/title*, hence *use
model …*; "chat with {*}" and "talk to {*}" already open a thread by name and
stay. A spoken message gets a spoken answer (today's `chatAnswered`) in every
conversation whose caps include `voiceReply`.

### 2.9 Look

LCARS, not iMessage: black ground; the header an orange LCARS bar with an
elbow and the title in Antonio caps; pills for buttons; colour carries who is
who (left bar of a reply, avatar pill); mono for meta, tools and status;
the only rounded-blob shapes are the bubbles, because that shape *is* the
messaging idiom on a phone. No gradients, no shadows beyond the existing glow
on headings. `prefers-reduced-motion` turns the ▮ and • • • into still marks.

### 2.10 Quoting (0.182.0)

Answering a part of an earlier message — anyone's, in any thread — or
pointing at a piece of it.

- **Taking a quote.** *Quote* takes the words selected in one message of the
  log, or the whole message when none are; *Reply* takes it whole (its own
  quotes left out). On a desk a floating *Quote* sits by the selection, and
  Quote · Reply show on a message's hover. On a phone iOS owns the
  selection's callout, so a message's own row (Quote · Reply) shows while
  words in it are selected, or after a tap on it; Quote there takes the
  selection the tap itself may just have cleared (`chatSelLast`, 1.5 s).
  Voice "quote that" and the key `>`: the selection, else the last answer.
- **In the box.** The quote goes in as markdown `> ` lines — trimmed, blank
  runs closed up, cut on a word past ~300 characters with an ellipsis —
  after what is typed, then a blank line with the caret on it: the answer
  goes under it, the next quote under that, as often as one likes. The box
  is focused in the tap (the keyboard comes up, or stays). Its quotes show
  as chips above it (`#chquotes`, × takes one out); what is sent stays the
  plain markdown, so an engineer's session and the computer read it as is.
- **In the log.** A quote is a purple bar and dimmer words (the captain's
  bubble draws its `> ` lines so; an answer's markdown already did). A tap
  on one scrolls to the earlier message holding those words (matched on
  letters and digits only, so the markdown's marks and what was selected on
  screen agree), flashed amber; when it is not in the log (an engineer's
  older page), a toast says so.
- **One block** (0.184.0). A paragraph, a list item, a heading, a code
  block or a table row of a message — the nearest block of its rendered
  markdown, an answer's or a crew report's; the captain's plain bubble
  whole — is quoted by itself: on a phone by a swipe right on it (the
  house row swipe's rule: past 10px, mostly sideways, else the log's
  scroll; the block follows the finger, a ❝ comes up in the space it
  leaves, amber past 56px, and it springs back), on a desk by the ❝ handle
  in its margin while the mouse is on it. A list item is itself and its
  children (mdRender puts a branch in the `<ul>` after its `<li>`), never
  its siblings. Each block picked goes under the last with its own answer
  line, what is typed under the others untouched, the caret on the new
  one; the log does not move, so the next bullet is swiped from where one
  is. The same words twice add nothing: a toast, and the caret to their
  answer. A tap on a chip puts the caret on that quote's answer (a line
  made for it when there is none). The swipe's listeners are passive, so
  the log's scroll never waits on them; a bubble's `touch-action: pan-y`
  keeps a sideways move from being a pan. Key help: "swipe →".
- **A selection over several blocks** quotes the words selected, a line
  per block, as Quote always did.
- **The keyboard** (2.3 rule 1): Quote, Reply, × and a chip are kept-focus taps,
  and so is a tap on a message's words while the box has the focus
  (`chatMsgKeepKb`): its pointerdown is prevented and the tap done on its
  pointerup, unless the finger moved (a scroll, a swipe) or held (a
  selection). A swipe moves, so it takes no focus and drops no keyboard.


---

## 3. Immediate feedback (the captain's standing rule)

> **Every interaction gives immediate visible feedback** — within the frame,
> before any network — even when the real work is async and answers later.

In the chat that means:

| Act | At once (≤ 100 ms, no network) | Later |
|---|---|---|
| Tap any button | pressed state (`:active` + a `.pressing` class held until the action settles, so a slow one does not look untouched) | — |
| Send | box clears, bubble appears with *sending…*, Send→Stop if the other side will work, list row jumps to the top with the preview | *delivered* / *queued #2* / *✕ not sent, Retry* (text put back in the box) |
| Stop | button shows *stopping…*, ▮ stops blinking | *stopped* on the bubble |
| Pick a model | chip changes, sheet closes, system line | engineer: *⋯* pending → confirmed, or reverted with a reason |
| Answer a question chip | chip pressed, card collapses into *Answered: 1. Yes* | the status line moves on |
| Deploy | confirm → system line *Deploy queued…* with ▮ | *Deployed ✓ / failed: …* |
| New engineer | row appears at once, *reporting for duty…* | the thread opens when they are up |
| Open a thread | the screen slides in with what is cached, status *…* | fresh transcript replaces it |
| Pull to refresh the list | indicator | rows update |

The rule is written into CLAUDE.md's conventions for all UI, not only chat.

---

## 4. Phases

1. **The component, and Ask on it.** `chatUi` (list, thread, composer,
   states, the keyboard rules of 2.3, the model chip for the `chat`
   transport) and the `chat` adapter; Ask and role chats move in; role chats
   get their own threads (several computer threads). `/ui/chats`. Voice:
   chats, new chat, send it, stop the answer, switch model to, read the last
   message. `keyboard.py`, `buttons.py`, a perf scenario for a 200-message
   thread, QuickJS checks for the list and states.
2. **Engineers and Number One** on the `engineer` adapter; the seat strip;
   question card; deploy as system lines; *No.1 asks* badge becomes the
   ANSWER badge on Number One's row (the header keeps a single *Chats · n*
   button). Voice: answer {n}, next unread, deploy {*}.
3. **Model per engineer** — server route + `engineer.py model` (§2.4).
   **Navigator embed** (§2.5) with its own model; the course-only keyboard
   CSS removed.
4. **Attachments** (this entry, an entry, photo/file).
5. **The deck's talk sheet** opens the same thread (framed console, or the
   component loaded into the deck), so a crew persona's talk is in the list.
6. **People** — the `person` transport, delivery/read marks.

Each phase is a minor version and ends with the old screen removed, not kept
beside the new one.

## 5. Open questions for the captain

1. Should the header keep *Ask* and *Crew* as buttons, or become one *Chats*
   button (with the unread count)? The mockup shows one.
2. Several computer threads, or one plus role threads? (Design: several, like
   ChatGPT's list, newest first, archive by swipe.)
3. A message typed to a *working* engineer: queue it (today) or interrupt?
   Design keeps queue; Stop is the interrupt.
4. Changing an engineer's model mid-turn: wait for the turn to end (design) or
   interrupt and switch?
