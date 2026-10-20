# One chat — the refactor plan (phase 0)

**History.** Every stage is built (0.156.0-0.172.0); kept for the why of each step, not as a plan.

Status: **plan, approved** (2026-10-11, Lt. Cdr. La Forge; §7 decided by
Number One for the captain: §4 signed off, Number One may not switch an
engineer's model, Reports fold into Chats at stage 3, the deck after
stages 1-5). Stage 1 is 0.156.0, stage 2 0.157.0, stage 3 0.159.0 (0.158.0 is O'Brien's backend), stage 4 0.159.1, stage 5's page half 0.160.0, stage 6 (the deck's talk sheet) 0.161.0.
The captain then had the keyboard made native (0.161.1): no keyboard fit
anywhere in the page (§2.3 of the design and the fit rows below are
history), and stage 6 taken back out, the deck's talk sheet its own again;
0.172.0 put stage 6 back, with no keyboard fit (the deck's `fitKeyboard`
went too) and the voice the console's (0.169.0). Every stage is built: this
plan is history now.
It turns `docs/design/chat.md` (the design the captain approved; mockup
`lcars-ui/mockups/chat.html`) into code: what exists, what each piece
becomes, what goes, and the order to build it in, as stages that each
deploy on their own.

Settled by the captain (2026-10-11), and assumed throughout:

- a **model picker per conversation**, engineers included, changeable
  mid-conversation; for an engineer the switch takes effect **when their
  turn ends**;
- a message to a working engineer is **queued**; **Stop** interrupts;
- **one Chats header button** replaces Ask and Crew;
- **several computer threads**;
- **the back gesture** (iOS swipe from the left edge, Android back, the
  browser's Back) in an open thread goes back to **the chat list**, and
  from the list it leaves the chats: list and thread are history entries;
- every interaction gives **immediate visible feedback** (CLAUDE.md).

Line numbers are `lcars-ui/index.html` at 0.155.1 unless another file is
named; counts are rough (± 10 %).

---

## 1. The map: every chat code path today

### 1.1 `lcars-ui/index.html` — script

| Area | Lines | Functions (≈ lines) | Notes |
|---|---|---|---|
| **The computer (Ask)** | 26083–26446 (364) | `chat` state + `chatSave` (25), `chatLocalTime` (9), `chatRefs` (3), `chatToolLabel` (6), **`chatMsgHtml`** (24), **`chatDraw`** (22) + `chatPaint`, **`chatEvent`** (62), `chatWork`/`chatSpoken`/`chatCites`/`chatAnswered` (55), **`chatSend`** (38), **`chatPost`** (52), `chatStop` (1), `chatNew` (9), **`openChat`** (40) | one thread in `lcars.chat` (40 msgs, `sid`, `model`, `role`, `pre`); streams `POST /chat` SSE by hand; `chatPost` is already shared with the navigator |
| **Navigator** | 29837–30055 (219) | `crsNavLoad` (6), `navSave` (8), **`navDraw`** (21) + `navPaint`, `crsNavBrief` (18), `crsNavState` (20), **`navSend`** (41), `navStop` (1), `crsNavPlan` (10), `crsRevise` (38), `crsNavFollow` (14), `crsUnrevise` (11), `navNew` (7), `navAsk` (9) | renders with `chatMsgHtml` but draws its own log; model silently `chat.model`; per course in `lcars.nav`, 40 msgs, 30 courses |
| Course sheet's nav tab | 27020–27030, 27100–27104, 27146–27155, 27161–27180 (≈ 40) | markup `#crsNav/#navlog/#navq/#navsend/#navsid/#navnew`, `crsKey`'s Enter, Send's `pointerdown` `preventDefault`, `crsTab`'s nav branch | the only chat whose Send keeps the keyboard |
| **Crew reports** | 30056–30302 (247) | `crewReports`/`crewRead`/`crewUnread*`/`crewFind`/`crewHead` (60), **`openCrew`** (37, the list), `crewRole` (48, one report), `crewAuthor` (11), `crewChatPaint`/`crewChatLabel`/`crewChatSaid` (16), **`crewChat`** (18), `crewBrief` (9), `crewRoleContext` (12), **`crewRoleChat`** (11), `crewPin`/`crewPinPaint` (22) | a role chat *is* the Ask dialog with `chat.role`/`chat.pre`, and throws the Ask thread away (`chatNew`) |
| **Engineers + Number One** | 30303–30814 (512) | `eng` state, `ENG_STATUS`, `engKeyAsk` (11), `engApi` (6), `engStop` (1), `engGitLine` (5), **`openEng`** (55, list dialog), `engFind` (9), `engRole` (6), `engSeatName` (7), **`engSeatPaint`** (13), `engAgo` (6), **`engListPaint`** (35), `engDismiss` (16), `engNo1` (14), `engNo1Refresh` (9), `no1Cap` (8), `engNewSlug` (10), `engAdd` (25), **`engOpen`** (46), **`engPoll`** (29), `engEarlier` (22), **`engPaintSend`** (7), **`engPaint`** (64), **`engSay`** (25), `engKeyPress` (4), `engDeploy` (11), `engRollback` (9) | polled transcript (`?off=` bytes, 1.5 s); a second renderer inside `engPaint`; reuses the id `#chatlog` so `keyboardFit` finds it |
| Keyboard | 19103–19159 (57) | `fieldFocused` (5), `keyboardFit` (50) | generic; scrolls `#chatlog` (whichever chat owns the id) |
| Routing / history | 7990–8160 | `ROUTES.ask/engineers/crew`, `routeAs`, `pushes`, `writeState`, `applyPage`, `popstate` | `pushes()` never pushes between two urls of one kind, so `engineers` → `engineers/<name>` *replaces*: Back from a conversation leaves the crew altogether — the bug the new requirement names |
| Close | 8979–9005 | `closeOv` calls `engStop()`, clears `crewAt` | |
| Voice | 24067–24103 (≈ 40) | `VCMDS`: navigator {*}, ask {*}, crew reports [{*}], show the crew, talk to {*}, chat with the writer, engineers, new / dismiss / bring back engineer {*}, number one [{*}], refresh number one, engineer {*}, earlier messages | |
| Keys / palette | 30876–30880, 23499–23502, 18792 | `A` Ask, `W` Crew, `B` Reports; palette rows; the `crew` deep link | |
| Header | 3194, 3209–3216, 3572–3573, 7117 | `#hNo1` (*No.1 asks · n*), `#bChat`, `#bEng`, `#bCrew`, the reader's `#bCrewChat` | |

### 1.2 `lcars-ui/index.html` — style

| Area | Lines |
|---|---|
| `.dlg.chat`, `#chatlog`, `.cm` (u/a/live), `.ctools/.ctool`, `.cmeta`, `.cerr`, `.cwait`, `#chatempty`, `.chatin`, `#chatmodel`, `#chatq` | 2047–2082 (36) |
| `#crsNav`, `#navlog`, `#navq`, `#navsend`, `.cnavfoot`, `.ctab.busy` | 2163–2177 (15) |
| course-only keyboard: `html[data-kb] #dlg.course …` | 2299–2305 (7) |
| engineers: `.englist`, `.engrow`, `.engline`, `.engoff`, `.engnew`, `.engst.*`, `.engwho`, `.engseat`, `#engwho`, `#engscreen`, `.engkeys` | 2306–2337 (32) |
| crew reports: `.crewlist`, `.crewrow`, `.crewout`, `.crewhist` | 2339–2360 (22) |
| generic keyboard fit: `html[data-kb] #ov/.dlg`, `*:has(:focus)` | 2396–2409 (stays) |

### 1.3 `lcars-ui/deck.html`

| Area | Lines | Functions |
|---|---|---|
| Keyboard | 440–466 (27) | `fitKeyboard` — its own (`body.kb`, `--vvt/--vvh`, `#talklog`) |
| Crew you can talk to | 10490–10826 (337) | `personaOf`, `personaPrompt`, `openTalk`, `endTalk`, `logScroll`, **`paintTalk`**, **`paintTalkLog`** (a third renderer), `talkSave` (12 msgs/person), `talkVoice`, `talkSay`, `talkAnim`, **`talkSend`** (its own `/chat` SSE reader), orders (`paintOrders`, `crewOrder`, …) |
| Engineers | 10827–11120 (294) | its own `eng` state, `engApi`, `engOpen`, `engPoll`, `engTake`, `engEarlier`, `engDeployNews`, **`paintEng`**, **`paintEngLog`** (a fourth renderer), `engSay`, `engKeyPress`, `engPromote`, `engMakeNo1`, `engDeploy`, `engRollback`, `engClear`, `engRefresh`, `engRelieve` |

### 1.4 Server and scripts

| File | What | Lines |
|---|---|---|
| `lcars_chat.h` | `POST /chat`: claude as a subprocess, stream-json → SSE; `g_chat_models` (sonnet, haiku, opus, fable) is the menu; `model` per request | 1013 — **no change** |
| `lcars_engineer.h` | `/engineer[/<name>[/<verb>]]` → `engineer.py <verb> <name>`; verbs: (GET) poll, brief; (POST) start, say, key, stop, deploy, dismiss, recall, refresh; `/engineer/rollback` | 456 |
| `scripts/engineer.py` | `MODEL = $LCARS_ENG_MODEL or "opus"` (l. 99), passed as `--model` by `cmd_start` (l. 836) to every session; `cmd_say` (seat queue), `cmd_poll` (transcript events), `cmd_list`, `cmd_hook` (turn-ended → seat) | 3076 |

### 1.5 Tests

| File | Chat coverage |
|---|---|
| `test/tests.js` (QuickJS) | the computer out loud (6515–6600: SSE stub, spoken answers, cites), a role chat (6601–6650: brief behind the key, context on the first message only), the navigator (8105–8160+: fresh session per order, revisions, follow), engineers (8505–8600: slug, list order, dismissed, `vMatch` orders), crew reports (8600–8680) — ≈ 400 lines |
| `test/keyboard.py` | Ask (via routes), `an_engineer` (`engOpen`), the race (`engineer` in `the_race`), stubs for `/engineer` and `/chat` |
| `test/buttons.py` | `("ask", "#bChat", "ask")`; skips `#navsend` |
| `test/perf.py` | no chat scenario |
| `test/deckboot.js` | wiring only |

---

## 2. What is duplicated, and what each piece becomes

The component is plain functions in one block of `index.html` ("one chat"),
in the codebase's own idiom — no framework, no class hierarchy. Names below
are proposals; `chats…` avoids the existing `openThread` (an entry's thread
view, route `thread`).

| Piece | Today (duplicates) | Becomes |
|---|---|---|
| **Conversation store** | `chat` + `lcars.chat`; `crs.nav` + `lcars.nav`; `eng` (server transcript); deck `talk*` | `convs`: `Map<id, Conversation>` (design §2.1). Local ones (`computer:<n>`, `role:<kind>`, `nav:<entry id>`) persisted in **one** key `lcars.chats` (40 msgs each, 30 threads, migration from `lcars.chat` and `lcars.nav` on first load). Engineer ones hold only the poll cursor; the transcript stays the server's. |
| **Renderer** | `chatMsgHtml`, `engPaint`'s loop, deck `paintTalkLog`, deck `paintEngLog` | `chatsMsgHtml(conv, msg)`: bubble, markdown with `#123` chips (`chatRefs`), one collapsed tool chip per turn (`⚙ n steps`), meta, error + Retry, system lines, delivery mark. Engineer events (`{r:"me"|"tool"|…}`) are mapped to `Message` by the adapter, so there is one renderer. **Keyed**: each message's HTML is cached by `(id, version)`; while streaming only the live bubble is redrawn (today `chatDraw` rebuilds the whole log every frame — see perf, §5). |
| **Thread** | `openChat`'s dialog, `engOpen`'s dialog, the nav tab's markup, deck sheet | `chatsMount(el, conv, {embedded})` → header (back chevron, avatar, name, status line, model chip, ⋯), context card, log, question card, composer. `chatsPaint(conv)` repaints whatever mount shows it (rAF-batched, as `chatPaint`/`navPaint` are). |
| **Composer** | `#chatq`+`#chatsend`, `#chatq`+`#engsay` (Say/Stop), `#navq`+`#navsend` | one `<textarea>` + Send↔Stop, `enterkeyhint="send"`, 16 px, 1–6 lines; Enter sends on a desk; Send/Stop/chips `preventDefault` on `pointerdown` while the box has focus (the navigator's 0.148.0 fix, for all); text kept as a per-conversation draft. |
| **Keyboard fit** | `keyboardFit` + `#chatlog` scroll; the course's `html[data-kb] #dlg.course` rules; deck `fitKeyboard` | the thread column is `position:fixed; top:var(--vvtop,0); height:var(--vvh,100dvh)`; `keyboardFit` scrolls `.chlog[data-stick]` (any mount) instead of `#chatlog`. The embedded mount calls `onWantFull` and the course sheet goes full height; its seven course-only rules go. |
| **List** | `openEng`+`engListPaint`+`engSeatPaint`, `openCrew` list, the header badge | `chatsList()`: search, sections Pinned / Crew / Reports / Courses, one row renderer, one badge (ANSWER / • • • / #n SEAT / unread / off), the seat strip, `+` menu, Dismissed folded. Row swipe actions also in the thread's ⋯. |
| **Model picker** | `#chatmodel` select (Ask); nothing elsewhere | the chip + a sheet (`CHAT_MODELS` + a line each); `conv.model`; system line *Model → X from here*; adapter's `setModel`. |
| **Adapters** | `chatSend`/`chatPost`/`chatStop`/`chatNew`; `navSend`/`navStop`; `engSay`/`engPoll`/`engKeyPress`/`engEarlier`/… | one interface `{send, stop, setModel, answer, earlier, open, close}`: **`chatAdapter`** (wraps the kept `chatPost` + `chatEvent`; computer, role, navigator variants differ only in `prefix(conv)` — role context on the first message, navigator brief + plan on every one with `sid` dropped — and `after(conv, m)` — `crsNavPlan`/`crsRevise` for the navigator); **`engAdapter`** (wraps the kept `engApi`, `engPoll`, `engEarlier`, `engKeyPress`, `engDeploy`, `engRollback`, `engNo1*`, `engAdd`, `engDismiss`; maps status → conversation status; `queued` reply → the bubble's `⏳ queued · #2 for the seat` instead of a toast). |
| **States** | `chat.busy`; `crs.nav.busy` + tab dot; `ENG_STATUS` + `engPaintSend` | `conv.status` (design §2.6) drives the list badge, the header line, Send↔Stop, the nav tab dot. |
| **History / back** | `routeAs("ask")`, `routeAs("engineers", name)` replacing each other | routes `chats` and `chats/<id>`; `pushes()` gains one rule: `chats` → `chats/<id>` **pushes**, `chats/<a>` → `chats/<b>` replaces (split view on a desk), so Back from a thread is the list and Back from the list is whatever was under it. Opening a thread from outside (voice "talk to Reyes", a report's *Chat with*, `/ui/ask`, `/ui/engineers/<n>`, a deep link) writes the list entry under it first (replace-or-push `chats`, then push `chats/<id>`). The thread's `‹ Chats` is `history.back()` when the entry below is the list, else a replace to it. Old routes `ask`, `engineers` stay as aliases into `chats`. In the deck (framed) every write is a replace (`inDeck`), so there `‹` is in-page only. |
| **Voice** | ≈ 15 orders spread over three blocks | the existing orders call the new openers; new ones per design §2.8, added in the stage that builds what they reach. |
| **Feedback** | per chat, uneven | in the component: `.pressing` on any button until its promise settles; optimistic bubble *sending…*; list row moves at once; model chip changes at once; question card collapses at once; deploy as a system line with ▮. |

What is **kept as is** (moved, not rewritten): `chatEvent`, `chatPost`,
`chatLocalTime`, `chatRefs`, `chatToolLabel`, `chatWork`/`chatSpoken`/
`chatCites`/`chatAnswered`, `crsNavBrief`, `crsNavState`, `crsNavPlan`,
`crsRevise`, `crsNavFollow`, `crsUnrevise`, `crewRoleContext`, `crewBrief`,
`crewAuthor`, `engKeyAsk`, `engApi`, `engFind`, `engRole`, `engNewSlug`,
`engGitLine`, `engAgo`, the crew report view `crewRole` (a document
reader, not a chat; its *Chat with* opens the role's thread).

---

## 3. Code to delete

By the stage that removes it (each stage ends with the old screen gone, not
kept beside the new one):

| Stage | Deleted | ≈ lines |
|---|---|---|
| 1 | `openChat` (the dialog), `chatDraw`, `chatPaint`, the `#chatmodel` select, `.dlg.chat`/`#chatlog`/`#chatempty`/`.chatin`/`#chatmodel`/`#chatq` CSS (the `.cm`/`.ctool`/`.cmeta`/`.cwait` rules are renamed into the component's) | 90 |
| 2 | `chat` singleton + `chatSave`/`chatNew`/`chatSend`'s panel code (now `chatAdapter`), `chat.role`/`chat.pre` (now `conv.context`), `crewRoleChat`'s `chatNew()`, `#bChat` | 70 |
| 3 | `openEng`, `engListPaint`, `engSeatPaint`, `engOpen`, `engPaint`, `engPaintSend`, `engSay`'s DOM code, `engStop` in `closeOv`, `no1Cap` + `#hNo1` (→ ANSWER badge on Number One's row and the *Chats · n* count), `#bEng`, the `.eng*` CSS, `openCrew`'s list (its rows are the list's Reports section; `crewRole` stays), the mockup `lcars-ui/mockups/chat.html` (783, not counted) | 300 |
| 4 | `crsNavLoad`, `navSave`, `navDraw`, `navPaint`, `navSend`'s UI half, `navStop`, `navNew`, the nav tab's markup and wiring, `#navlog/#navq/#navsend/.cnavfoot` CSS, the seven `html[data-kb] #dlg.course` rules, `lcars.nav` (migrated) | 110 |
| 6 | deck: `paintTalkLog`, `talkSend`'s SSE reader, `talkSave`, `paintEng`, `paintEngLog`, the deck's `eng*` transport, `fitKeyboard` (the sheet becomes the framed console's thread) | 350 |

---

## 4. Server and `engineer.py` changes — **need the captain's sign-off**

Only the model per engineer needs them; everything else is the page.

1. **`lcars_engineer.h`**: a verb `model`: `POST /engineer/<name>/model
   {"model": "sonnet"}` → `engineer.py model <name> <model>`. The model is
   checked against the same four names as `g_chat_models` (argv stays sane;
   the script holds the real whitelist). ≈ +15 C lines; `test/logins.py`
   gains: the crew's and Number One's logins may not call it (the captain's
   choice), like `deploy`. *(Should Number One be allowed to change an
   engineer's model? Proposed: no.)*
2. **`engineer.py model <name> <model>`** (≈ +60 Python):
   - records `st["model"] = model` (state file), so `cmd_start` starts and
     resumes with `--model st.get("model") or MODEL` — a restart, a seat
     hand-over and a resume keep it;
   - idle (in the seat, `agent_status` idle/done): types `/model <model>`
     into their Claude Code session at once (`herdr agent prompt`, then
     `submit_if_left`);
   - working: stores `st["model_pending"]` and returns `{"pending": true}`;
     `cmd_hook turn-ended` applies it (types `/model …`) before the seat or
     anything else gets the turn's end — "takes effect when the turn ends";
   - not seated / off: recorded only; the next start uses it;
   - blocked (a question on screen): refused, 409, as `say` is.
3. **`cmd_poll` and `cmd_list`** report `model` (the recorded one) and
   `model_pending`, and `model_used` — the `message.model` of the last
   assistant line in the transcript — so the chip can go from `SONNET ⋯`
   to `SONNET ▾` when the model actually answering changes, and each answer's
   meta names what ran.
4. Tests: `scripts/test_engineer_model.py` (new, stub herdr + claude as
   `test_seat.py` does): idle → typed at once; working → applied by the
   turn-ended hook, once; off → only recorded, and `cmd_start` passes it;
   a bad name refused; blocked refused.

**Not** changed: `lcars_chat.h` (the computer's model is already per
request), the seat (`seat.py`), the deck's promote/relieve.

Open point for the captain: Claude Code's `/model` typed while a turn runs
may be read as a queued message rather than a command; that is why the plan
applies it from the turn-ended hook instead. To be confirmed against the
installed Claude Code before stage 5 is built.

---

## 5. Build order — stages that each deploy

Every stage: `make check` clean (C stages; the quickest full-warning check), `lcars-ui/test/run.sh`
in full (QuickJS, deckboot, keyboard.py, perf.py), plus the tests named;
CHANGELOG + `APP_VERSION`; TODO.md updated; voice orders for whatever it
adds. Net lines are code only (index.html/deck.html/C/Python), tests
separately.

### Stage 1 — the thread component, Ask on it (0.156.0)
- `chatsMount` (thread: header, log, keyed renderer, composer, Send↔Stop,
  model chip + sheet, states, `.pressing`), `chatAdapter` (computer).
- Ask opens a **full-screen** thread (route `chats/computer:1`; `/ui/ask`
  lands there); one computer thread still, kept in `lcars.chat` as today.
- The keyboard rules of design §2.3 in the component; `keyboardFit` scrolls
  any `.chlog`.
- Voice: *send it*, *stop the answer*, *switch model to {*}* / *use model
  {*}*, *which model*, *read the last message*; `ask {*}` unchanged.
- Tests: QuickJS (renderer: markdown, `#123`, tool chip collapse, meta,
  error; states; Send→Stop→Send; model chip → next POST carries it and a
  system line is shown; `vMatch` collisions: *stop the answer* vs the
  timer's *stop*, *use model* vs *use the suggested …*); keyboard.py: the
  thread mount; buttons.py: `#bChat` → `chats/…`; **perf.py: a 200-message
  thread** — open it, scroll it, stream 300 deltas into it, all at p99 ≤
  16.7 ms.
- Net: **≈ +180** (component +270, deleted 90). Tests +150.

### Stage 2 — the list, history and back, several threads (0.157.0)
- `chatsList` (Pinned, Reports, Courses for now; search; row badge; `+`
  New chat), split view ≥ 900 px.
- History: `chats` / `chats/<id>` entries, the `pushes()` rule, the list
  entry written under a thread opened from outside; `‹ Chats`.
- Several computer threads (`computer:<n>`, archive by swipe and ⋯),
  `lcars.chat` → `lcars.chats` migration; **role chats get their own
  threads** with a context card (no longer replace Ask's).
- One **Chats** header button with the unread count replaces **Ask**
  (Crew stays until stage 3, so nothing is lost meanwhile).
- Voice: *chats*, *new chat*, *back to the chats*, *next unread*, *mark
  read*, *archive this chat*.
- Tests: **back-gesture test** (new, in buttons.py or its own
  `test/back.py`, Chromium at phone size): main → Chats → a thread →
  `history.back()` lands on the list with the thread's row on screen →
  `history.back()` lands on the main view; a deep link `/ui/chats/<id>` →
  back → the list → back → leaves; `/ui/ask` and a report's *Chat with*
  the same; the QuickJS history checks (`history._st`) for the same walk;
  keyboard.py: the list's search field; buttons.py: the list's buttons,
  phone and desk; QuickJS: migration, role thread kept apart from Ask's,
  context sent on the first message only (the 0.155.0 checks, moved).
- Net: **≈ +220**. Tests +180.

### Stage 3 — engineers and Number One in the list (0.158.0)
- `engAdapter`; Crew section (newest first, Dismissed folded), Number One
  pinned; the seat strip; question card (answer chips, ↑ ↓ ⏎ Esc); deploy /
  roll back as system lines; *queued #n for the seat* as the bubble's mark;
  *reporting for duty…* row on `+ New engineer`; earlier messages on scroll
  up; ANSWER badge from open `task_no1` and `blocked`.
- **Crew** header button and `#hNo1` go; `W` and `B` open the list (B at
  Reports). `/ui/engineers/<n>` and `/ui/crew` land in the list/thread.
- Voice: *answer {n}*, *deploy {*}*; the existing engineer and Number One
  orders reach the new screens.
- Tests: QuickJS (event mapping, status → badge, queued mark, pending
  bubble cleared by the transcript, the session-changed reset, dismiss /
  bring back, the existing 8505–8680 checks moved); keyboard.py: an
  engineer thread and the race; buttons.py: Crew rows, ⋯ menu, question
  card; perf: a 200-message engineer transcript repainted by a poll.
- Net: **≈ −150** (adapter +150, deleted 300). Tests +60.

### Stage 4 — the navigator embedded (0.158.x, patch: no new feature)
- The course sheet's Navigator tab is `chatsMount(el, nav:<id>,
  {embedded:true, onWantFull})`; its own model (default the last used);
  Courses section rows; `crsNavFollow` moves `nav:<old>` to `nav:<new>`.
- Tests: QuickJS (the navigator checks at 8105–8160 against the adapter;
  its POST carries its own model, not Ask's); keyboard.py: the embed, phone
  size, sheet full height with the keyboard up; buttons.py: `#navsend` is
  the component's Send (still skipped — it would run claude);
  `test/dates.sh` not needed.
- Net: **≈ −60** (+50, −110). Tests ±0.

### Stage 5 — model per engineer (0.159.0) — **server, needs sign-off**
- §4 above, and the chip for engineer threads (`⋯` pending → confirmed /
  reverted with a red system line).
- Tests: `scripts/test_engineer_model.py` (new), `test/logins.py`,
  QuickJS (chip states); `make check` and a scratch server.
- Net: **≈ +110** (Python 60, C 15, page 35). Tests +120.

### Stage 6 — the deck's talk sheet (0.160.0)
- The deck's talk sheet frames the console's thread (`/ui/chats/<id>` in
  the deck's existing console frame) for engineers; a crew persona's talk
  becomes a `role`-like computer thread `person:<key>` with its persona as
  context. Its spoken answers use the `voiceReply` cap.
- Tests: deckboot.js (wiring), keyboard.py in the deck frame (the console
  already reads `visualViewport` from the top window), a manual check on
  the phone.
- Net: **≈ −300**. Tests +30.

### Totals

| Stage | Version | Code net | Tests |
|---|---|---|---|
| 1 thread + Ask | 0.156.0 | +180 (built: +413, the navigator's renderer folded in and the sheets) | +150 (built: +170) |
| 2 list + back + threads | 0.157.0 | +220 | +180 |
| 3 engineers + Number One | 0.158.0 | −150 | +60 |
| 4 navigator embed | 0.158.1 | −60 | 0 |
| 5 model per engineer (server) | 0.159.0 | +110 | +120 |
| 6 deck talk sheet | 0.160.0 | −300 | +30 |
| **all** | | **≈ 0** | **≈ +540** |

After stages 1–4 (the console alone) the page is ≈ +190 lines with one
renderer, one composer, one keyboard rule set and one transport per kind
instead of four of each; stage 6 takes the deck's copies away. Attachments
(design phase 4) and people (phase 6) are not in this refactor; they need
no change to the list, thread or composer.

---

## 6. Risks

1. **The back gesture on iOS.** Safari's edge swipe walks same-document
   `pushState` entries (popstate), but shows a snapshot of the previous
   entry during the swipe; if the list was not painted when the thread
   opened, the snapshot is stale. Mitigation: the list stays mounted under
   the thread (hidden, not removed). `writeState`'s `backPending` /
   `history.back()` logic in `closeOv` must not pop two entries at once —
   the back test walks it at phone size. The deck frame only replaces, so
   inside the deck Back is not available (as today).
2. **Perf of a long thread.** Today's renderers rebuild the whole log on
   every frame of a stream (`chatDraw`) or every poll (`engPaint`), each
   time re-rendering markdown. With 200 messages that is the frame budget
   gone. The keyed renderer (only the live bubble redrawn) is required in
   stage 1, and the perf scenario holds it; an engineer transcript of
   thousands of events is windowed to the newest 200 with *earlier
   messages* above.
3. **Migration of `lcars.chat` / `lcars.nav`.** A thread in flight across a
   reload, a phone and a laptop each with their own; migration must be
   idempotent and keep the old keys until stage 4 lands.
4. **`#chatlog` assumptions.** `keyboardFit` and keyboard.py look for
   `#chatlog`; renaming it without moving both breaks the iOS fit
   silently. Stage 1 changes both together.
5. **Voice collisions.** *stop* (the timer), *use …* (suggested
   kind/title), *talk to {*}* already resolving to engineers and roles,
   *next* (calendar). Each new order is checked with `vMatch` in QuickJS
   in the stage that adds it.
6. **Claude Code's `/model` mid-turn** (stage 5): behaviour of a slash
   command typed while working is not documented for our version; applying
   it from the turn-ended hook avoids relying on it, but the hook must not
   run for a turn the seat ends by relieving (it is a turn end too — fine)
   and must not type into a blocked screen.
7. **The two id spaces.** Local thread ids are per device; engineer ids are
   the server's. A thread id in a url opened on another device (computer
   thread) may not exist there: the list opens with a toast, not an empty
   thread.
8. **Two Crew screens during stages 2–3.** Kept to one release: stage 3
   should follow stage 2 closely, or the header carries Chats and Crew
   side by side.
9. **Test time.** buttons.py (≈ 6 min) and keyboard.py grow with the list
   and thread mounts; the back test is new. Run them per stage, not per
   edit.
10. **`openThread` name clash** with the entry-thread view (route `thread`):
    the component uses the `chats` prefix throughout.

## 7. Decisions wanted from the captain

1. Sign-off on §4 (the `model` route and `engineer.py model`), and whether
   Number One's login may switch an engineer's model (proposed: no).
2. The **Reports** header button (`#bCrew`, `B`): keep it, or fold it into
   Chats (its rows are the list's Reports section)? Proposed: fold it in at
   stage 3; the report reader (`crewRole`) stays.
3. Stage 6 (the deck) now, or after the console has settled?
