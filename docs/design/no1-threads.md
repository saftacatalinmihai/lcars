# Number One's threads: several conversations, one session

**Superseded in full by docs/design/rooms.md** (the captain's decisions
of 2026-10-23: rooms, a header line per message, every message a journal
row), section 13 included, as of rooms slice 4 (0.309.x): `[thread <id>]`
is read as `room:: <id>` for a release and no longer written, and `no1.py
thread` is the old name of `no1.py room`. This document is history.

**Superseded in 0.285.0 by section 13, "Threads v2: tags, not sessions"**
(the captain's decision of 2026-10-21): a thread is a label on the
messages of one conversation, not a Claude Code session. Sections 1 to 9
are the first design, kept for its reasons; where they speak of
`/resume`, switching, holding, unread counts, `fork`, per-thread
sessions, notices or the six-thread cap, section 13 replaces them. What
still stands from them: the thread ids (`NAME_RE`), each cause
remembering its thread (section 3's table), the inbox's `#thread` mark,
and decision 7 (after a reboot the one session is resumed).

Status: designed in 0.281.3; the captain's answers to section 9 taken
(all as recommended) and slice 0, the spike, done in 0.281.4 (section
2a); slice 1 built in 0.282.0 (section 10), slice 2 in 0.284.0 (section
11), slice 3 in 0.284.1 (section 12). Written against `scripts/engineer.py` and
`scripts/no1.py` as of 0.281.2, and Claude Code 2.1.280 as installed on
the VPS.

## 0. What the captain asked for

Several threads of conversation with Number One at once, like tabs: a main
thread, plus (say) a deck-redesign thread and a web-app thread. Each keeps
its own history, and none leaks into another's context. The captain
switches between them from the deck, the console's No1 chat and the Claude
app. A new thread can be started from the main one, and a thread can be
branched off an existing one later.

"One Claude Code session" here means one process: one herdr tab, one
Remote Control name, one Stop hook, one place outside the crew's
seat. Inside it, Claude Code moves between conversations (session ids,
transcripts) with `/clear`, `/resume <id>` and `/branch`. **A thread is a
Claude Code conversation (a session id), and a switch is a `/resume <id>`
typed into the one process**, the way `clear_session` already types
`/clear`. Nothing talks to Claude Code's internals; herdr types, the
transcript is read.

Why not one process per thread: each is 200-400MB and its own herdr tab,
Remote Control entry and hooks; the captain would be choosing among
several Number Ones in the app, and the inbox, refresh and wake logic all
assume one. The cost of one process is that only one thread is live at a
time (section 4), which is also what keeps the reports from crossing.

## 1. The thread list and its commands

### State

Number One's state file (`~/.local/state/lcars-eng/number-one.json`)
already has `session` (the conversation in use) and `past` (conversations
left by a clear: `{name, session, at}`). Threads extend it:

```json
"threads": [
  {"id": "main", "name": "Main", "session": "<uuid>", "at": 1760900000,
   "used": 1760990000, "from": null},
  {"id": "deck", "name": "Deck redesign", "session": "<uuid>", "at": ...,
   "used": ..., "from": {"thread": "main", "how": "new"}},
  {"id": "web", "name": "Web app", "session": "<uuid>", "at": ...,
   "used": ..., "from": {"thread": "deck", "how": "fork"}}
],
"thread": "deck",
"switch": {"to": "web", "at": 1760990100, "by": "captain"}
```

- `id` is a slug (`[a-z][a-z0-9-]{0,23}`, `NAME_RE`), stable, what routes
  carry and the inbox marks; `name` is free text, what the pickers show,
  renamed at will. `main` always exists and cannot be closed.
- `thread` names the current one, and `st["session"]` stays what it is
  today, the current thread's session: everything that reads it (poll,
  start's `--resume`, `ctx_of`, `note_typed`, `last_words`) keeps working
  unchanged. The invariant: `session == threads[thread].session`, restored
  by `follow_session` whenever herdr reports a move.
- `switch` is a switch asked for and not yet done (section 4).
- A thread's old sessions (a refresh or a clear inside it) go to `past`
  with `"thread": "<id>"`, so the console's Earlier conversations can
  group them by thread. `past` entries with no thread are main's.
- A thread closed moves to `closed` (same shape) with its session kept:
  reopening is a switch to it.

Why the state file and not the journal (CLAUDE.md: state the captain
should see lives in the journal): the list is the plumbing of one box's
session files, as `session` and `past` already are, and the captain sees
it through the poll and the pickers. What the captain should read - the
held reports and the log - is in the journal (crew_inbox rows, no1_log),
section 3 and 5.

### Commands

`engineer.py thread <verb>` (the route's), and `no1.py thread <verb>` for
Number One (its permissions already allow no1.py; the verbs it may run are
the same, held in no1.py):

| verb | what it does |
|---|---|
| `thread list` | the threads, current, each one's held count (unread), `ctx`, last used |
| `thread new <id> ["<name>"] [--from <thread>]` | `/clear` typed (old session stays the from-thread's), the new session recorded as `<id>`, made current; the seed message typed (below) |
| `thread switch <id>` | `/resume <session>` typed; current = `<id>`; its held notes delivered (section 3) |
| `thread fork <id> ["<name>"]` | `/branch <name>` typed from the current thread's end; the branch is `<id>`, made current (section 6) |
| `thread rename <id> "<name>"` | the name only; `/rename` typed too if it is current, so `/resume` in a terminal finds it |
| `thread close <id>` | to `closed`; its held notes moved to main, marked with where they came from; refused for main and the current one (switch away first) |

`new`, `switch` and `fork` all type into the session and so are serialised
and wait for idle (section 4). `list`, `rename` of a thread not current and
`close` only touch state.

A new thread starts empty: no history, so the order that opens it must
carry what it needs. `thread new deck --from main` types, as the new
conversation's first message:

> [thread] This is thread "Deck redesign" (deck), opened from main. Threads
> are separate conversations: you remember nothing of main here. The
> captain's opening order follows.

and then the captain's text (the say that asked for it). If the captain
asks Number One, in main, to "open a deck thread with what we said",
Number One writes the brief itself: `no1.py thread new deck --from main
"<summary>"` with the summary as the seed. That is cheap (a fresh context
of the summary's size); `fork` is the expensive full copy (section 7).

## 2. Where the captain switches

The rule all three share: **viewing a thread is free; sending into one
switches.** The poll can read any thread's transcript without a switch (it
already reads `past=` sessions read-only), so the pickers show a thread's
history the moment it is chosen; only a message sent into a thread that is
not current types `/resume`.

### The say and poll routes

- `POST /engineer/number-one/say {message, attachments?, thread?}`.
  `lcars_engineer.h` checks `thread` against `NAME_RE`'s shape and passes it
  as `say number-one --thread <id>` (or in the `--json` body). No thread,
  or the current one: typed as today. Another: section 4's switch, then
  typed. An unknown id is a 404 (`{"error": "no such thread"}`); a closed
  one is reopened.
- `GET /engineer/number-one?off=&thread=<id>`: that thread's transcript,
  read-only if it is not current (as `past=` is), status still the
  process's. The answer gains `threads` (the list with `unread` and
  `current`) and `thread` (the one being shown).
- `POST /engineer/number-one/thread {op, id, name?, from?}` for new, fork,
  rename and close, from the pickers. It answers at once with the
  optimistic state (`pending: true` for a switch-like op) and the poll
  shows it land.

The route stays a thin layer: every rule is in engineer.py, so everything
can be run by hand.

### The console's No1 chat

A row of chips under the chat header (Main · Deck redesign 2 · Web app ·
+), the unread count on each, the current one marked. A tap shows that
thread's history at once (the poll with `thread=`) and the composer says
"to Deck redesign"; the first Send switches, with the bubble marked
"switching to Deck redesign…" then "sending…" (CLAUDE.md's immediate
feedback; chat.md §3). `+` opens a small sheet: New (name, an opening
order) or Branch this thread. Rename and Close from a long press on a
chip. The phone shows the chips scrolling sideways, never wrapping.

Voice orders (VCMDS): "number one, threads" (the sheet), "switch to
<name> thread", "new thread <name>", "branch this thread as <name>",
"close the <name> thread". Keys and palette rows as usual.

### The deck

The chat sheet's header gets the same chips (the deck's chat is the
console's frame); the deck's spoken orders (`DVCMDS`) get "switch thread to
<name>". A held report for a thread not shown lights the No1 pill's badge
with the thread's name.

### The Claude app and a terminal

These type straight into the process: nothing of ours sits between, so
there is no selector to add. They show whatever conversation the process
is in. Two ways to switch from there:

1. Ask Number One: "switch to the deck thread". Its brief says to run
   `no1.py thread switch deck`, which cannot `/resume` inside its own turn
   (the text would be typed into the turn under way); it records the
   switch, and the Stop hook does it when the turn ends (as refresh-go
   does the clear). The app shows the new conversation then.
2. Type `/resume <id>` (or pick from `/resume`'s list) by hand. herdr
   reports the new session (its SessionStart hook: the spike saw it for
   `/resume`), `follow_session` sees it, and the thread whose session it
   is becomes current. A session that is no thread's (an old conversation
   from `past`, or a `/clear` typed by hand) is taken by the current
   thread, as a clear is today, and the session it left goes to `past`
   tagged with the thread, so nothing is lost. (The first draft adopted
   it as a new thread; telling a resumed old conversation from a fresh
   `/clear` by the transcript alone is guesswork, and a thread the captain
   did not ask for is worse than one that moved.)

### 2a. What the spike found (slice 0, 2026-10-20)

A scratch Claude Code 2.1.280 (haiku) in a herdr workspace of its own, in a
throwaway git repo under the session's scratchpad, with Remote Control on
and a Stop hook given by `--settings`; torn down after (workspace closed,
repo and its transcripts deleted). Everything typed with `herdr agent
prompt`, as engineer.py types.

- **`/resume <id>` works, typed.** The switch lands in under two seconds,
  and the conversation is the resumed one (asked what it had said, the
  model answered from the resumed thread, not the one left). herdr's
  `agent_session` follows it, as it followed `/clear` in this run.
- **`/branch <name>` stays in the branch, and herdr does not see it.**
  The screen says: `Branched conversation "forked-x". You are now in the
  new branch (session <new id>). Use /resume <old id> ("<old name>") to
  return to the original…`. A new transcript appears beside the old,
  carrying the whole conversation, every line's `sessionId` rewritten and
  marked `forkedFrom: {sessionId, messageUuid}`; but herdr's
  `agent_session` stays on the parent. So a fork is followed by the new
  transcript (or the id on the screen), never by herdr.
- **The transcript folder**: `/clear` makes a new file; `/resume` writes
  to the file it resumes from the next message on (and a `bridge-session`
  record into the one it left); `/branch` a new file with the history
  copied. `/clear <name>` names the session being *left* (the spike's
  `/clear thread-a` showed later as `/resume <id> ("thread-a")`), which is
  how `clear_session` uses it; `/rename <name>` names the current one, and
  the name shows in the input box's border.
- **The Stop hook follows the switch.** Hooks are the process's
  (`--settings`), and after `/resume` the hook fired with the resumed
  session's `session_id` and its own last words: a turn's end always says
  which conversation it was in.
- **Remote Control: one bridge for the process.** Every conversation the
  process visited recorded the same `bridgeSessionId` (`cse_…`), and a
  restart with `--resume` kept it. So the Claude app has one entry for
  Number One whatever the thread, and it is the process's conversation
  that it bridges. Whether the app's open view redraws to the resumed
  conversation's history, or only shows what follows, the spike could not
  see (no phone here): **for the captain to look at** once slice 1 is live.
- **The resume question.** Its text, from 2.1.280: "This session is <age>
  old and <n> tokens. Resuming the full session will consume a
  substantial portion of your usage limits. We recommend resuming from a
  summary." Options: "Resume from summary (recommended)", "Resume full
  session as-is", "Don't ask me again". It is asked on a `/resume` (not a
  `/branch`) when the conversation's last message is at least
  `CLAUDE_CODE_RESUME_THRESHOLD_MINUTES` old (default 70) and it is over
  `CLAUDE_CODE_RESUME_TOKEN_THRESHOLD` (default 100k) tokens, behind
  feature flags; on this account it is asked only when a summary has
  been precomputed, and the spike could not make it appear (thresholds set
  to 0 and 1). The captain chose the full conversation always (decision
  6), so Number One's tab is started with
  `CLAUDE_CODE_RESUME_THRESHOLD_MINUTES=5256000` (ten years): the question
  is never asked. If it is ever on screen anyway (a later version), the
  switch sees `blocked` with "Resume full session as-is" on the screen and
  picks it (Down, Enter: the second option). "Don't ask me again" is never
  pressed: it is `~/.claude.json`'s, every session's on the box.

## 3. Routing: who gets a report

This is the real decision. Today every note for Number One goes through
one inbox (crew_inbox rows titled `number-one ← <sender>: …`) and is typed
into whatever conversation is open. With threads, a report must reach the
thread that caused it.

### Each cause remembers its thread

| cause | where the thread is recorded | who reads it |
|---|---|---|
| `no1.py crew say <eng>` (an order) | the engineer's state: `no1_thread` = Number One's current thread, set on every order (beside `under_no1`) | `cmd_hook` turn-ended and attention: `[crew]` reports |
| `no1.py crew deploy <eng>` | `deploy.json`: `by_thread` | `cmd_deploy`'s `[deploy finished]` / `[deploy failed]` |
| a deploy started by the captain (console) | none: the engineer's `no1_thread` | the same |
| `no1.py crew rollback` | `deploy.json`: `by_thread` | `[rollback]` |
| `no1.py escalate` (an ask) | state: `asks: {"<entry id>": "<thread>"}`, from the POST's answer | `no1_answers`: `[captain] ticked off…` |
| a crew note `@no1 …` | main, unless it names one: `@no1 #deck …` (open question 2) | `crew_notes.py`'s no1-send |
| `[refresh]` | the current thread at the time asked | refresh-go |
| the captain's say with `thread` | that thread | section 4 |

`notify_no1(about, text)` gains `thread` and passes it to `no1_send`; the
inbox row carries it on the sender, as `[fresh]` is carried today:
`number-one ← crew#deck: [crew] …`. `inbox_to` strips it, a new
`inbox_thread(row)` reads it; a row with no `#` is main's when threads are
on (and every row is deliverable as today until they are, slice 1).

An engineer given orders from two threads: the latest order's thread owns
their reports from then on (it is the order they are working). `crew say`
answers with a warning when it takes an engineer from another thread with
work under way ("obrien was working for thread web; their reports now go
to deck"), and the brief tells Number One to prefer another engineer.

### A thread that is not open: hold (recommended)

The flusher (`cmd_no1_flush`) delivers, in order, only rows of the current
thread (and threadless ones). Rows of other threads stay in the journal,
undelivered, and are that thread's unread count. On a switch, once the
`/resume` has landed, they are typed in, oldest first, as one turn's input
(a single message joined by blank lines, so that a thread with five
reports pays for one turn, not five), prefixed with "(held since … while
you were in thread <x>)" as `held_since` does for off duty.

Weighed against delivering to the active thread with a tag
(`[crew @deck] …`):

- **Hold.** Each thread's context holds only its own work, which is the
  captain's requirement ("none leaking"). Nothing costs tokens until the
  captain goes to it. The cost: a deploy that failed sits unread until
  someone opens the thread. The pickers show the count, the deck's pill
  badges it, and a `[deploy failed]` or an engineer's question waiting
  (attention) also makes a ship's notice in the console (the existing
  notice path), so it is not silent.
- **Deliver with a tag.** Nothing waits, but main's context fills with
  the deck's reviews, Number One acts on them in the wrong conversation
  (and later cannot find, in the deck thread, what it decided), and the
  captain reads deck chatter in main. That is the leak the captain asked
  to be rid of.

Recommendation: hold. An engineer whose report waits is not blocked on
the box (the seat passes when their turn ends regardless); only Number
One's review waits, which is what the captain chose by being elsewhere.
Open question 1 asks whether some notes (a failed deploy) should instead
pull the captain's attention harder.

The captain's questions (`task_no1`) are the journal's, not a thread's:
`no1.py asks` lists them all, in every thread, each with the thread that
asked it; the answer goes to that thread.

## 4. Switching, serialised

A switch is typed text, like a note, so it must never interleave with one:
a note typed between `/resume` and its landing would go into the thread
being left, or be eaten by the resume dialog. So **every switch takes the
flusher's lock** (`no1-flush.lock`, the one `cmd_no1_flush` holds), and the
flusher reads the current thread under it. One writer to the input box at
a time, as the seat has one mover at a time.

`thread switch` (and new, fork), under the lock:

1. Number One is idle (`seat_status(info) == "idle"`) and not at a
   question. Otherwise record `st["switch"]` and return `pending` (below).
2. A refresh pending (`refresh_pending`) refuses it: the refresh's clear
   belongs to the thread that asked; the switch is retried after it.
3. Mark the state `switching` (so a poll's `follow_session` meanwhile
   does not take the half-made move for a hand-typed one), type `/resume
   <session>` (`/clear`, `/branch <name>`), then `submit_if_left`.
4. Wait up to ten seconds for the session to change: herdr's report for
   `/resume` and `/clear` (seen in the spike), else the transcript (a new
   file beside the old since the command was typed: always for `/branch`,
   which herdr does not report).
5. A long conversation resumed could put the resume question on the
   screen (section 2a: kept off by the environment). If herdr shows
   `blocked` with "Resume full session as-is" on screen, that option is
   chosen (decision 6). Anything else on screen, or no move seen: the
   switch fails, its error in the answer and the log, `st["thread"]`
   unchanged.
6. Record `thread` and `used`; type the `[thread]` line: "[thread] You are
   in thread Deck redesign (deck). Your other threads: Main (main), Web
   app (web, 2 held)." Then deliver that thread's held rows (section 3)
   and the captain's message that asked for the switch, if any, joined
   into the same input so it is one turn.
7. Release the lock.

**Mid-turn.** A switch asked while Number One is working is recorded
(`st["switch"]`), and the captain's message for that thread goes into the
inbox as a held row of that thread (`number-one ← captain#deck: …`), with
the bubble saying "waiting for Number One to finish in Main". The Stop
hook does the switch when the turn ends (`spawn("thread-go")`, as
refresh-go), then delivers. A second switch asked before then replaces the
first (the last word wins; the held message still waits in its own
thread, and its unread count shows it). The captain may also press Stop
(Esc, `crew key number-one esc`) to cut the turn and switch now: nothing
cuts a turn by itself.

The order of operations at a turn's end is: refresh-go first (if noted),
then a pending switch, then the flusher for the (possibly new) current
thread. All three under the same lock.

## 5. The log, handover and refresh, per thread

- **One log**, `no1_log`, with the thread in the title: `[deck] Deployed
  obrien-c33: …`; main's have no tag, so today's log reads the same.
  `no1.py log` adds the tag from the current thread; `no1.py logs [n]
  [--thread <id>|--all]` reads the current thread's by default (the tag
  matched), `--all` the whole. The console's log view gets a thread filter.
- **Handover per thread.** `[refresh]` is asked of the current thread (the
  console's refresh button names it). The handover entry is titled
  `[deck] Handover`; `refresh_noted` matches the title after the tag.
  refresh-go clears into a new session which replaces the thread's
  `session` (the old to `past`, tagged), and the fresh one is told to read
  `no1.py logs 5 --thread deck`. A refresh of one thread leaves the others
  alone. The context gauge (`ctx_of`, the handover mark at
  `ENG_CTX_HANDOVER`) is per thread: `thread list` gives each one's.
- **The brief** (`brief_no1`) is the process's and cannot name a thread:
  it is written once at start and every thread reads it. It gains a
  paragraph: what threads are; that the `[thread]` line typed at each
  switch says which one it is in; that it remembers nothing of the others
  (`no1.py thread list` names them, `logs --thread <id>` reads their log);
  that a report always belongs to the thread it arrives in; and that an
  order to an engineer should come from the thread whose work it is.

## 6. Branching: only from a thread's end

Claude Code 2.1.280 has `/branch [name]`: "Create a branch of the current
conversation at this point". Typed through herdr like `/clear`, it makes a
new session that carries the whole conversation so far, and the process
carries on in it; the original stays on disk, resumable. `claude --resume
<id> --fork-session` is the same from the command line, but needs a
process restart, so the slash command is the one used.

**A branch is cut at the thread's end, never from the middle.** Claude
Code can fork from an earlier message (the rewind menu's "Fork
conversation from here", Esc Esc), but only by picking the message in an
interactive list; driving that through herdr's keys, blind, is not
reliable, and none of our surfaces could show which message is which. So
`thread fork deck` forks the deck thread as it stands now; to branch an
older thread, switch to it first (a switch then a fork, one lock). A
"branch from here" on a message in the console is not offered.

The branch inherits every report and decision of its parent up to the cut,
and from then on is its own: orders given in it, and their reports, are
its.

After cutting, `/branch` leaves the process in the branch (section 2a),
and herdr does not report the move: the fork is followed by the new
transcript beside the parent's, whose lines carry `forkedFrom`.

## 7. Cost and failure

- **A cold cache on every switch.** The prompt cache is per conversation
  prefix and lives minutes. A switch into a thread whose cache has expired
  pays its whole context again on the first turn: at a 150k-token thread,
  a full uncached read of 150k input tokens, against the few thousand a
  warm turn costs. Switching back and forth inside the cache's life is
  cheap; a thread left for an hour is not. Hence: held notes are delivered
  in one turn (section 3); the pickers show each thread's `ctx`; the
  handover mark applies per thread; and the brief asks Number One not to
  switch on its own initiative.
- **A fork doubles a context**: the branch starts as big as its parent.
  `new` with a written summary is the cheap way to open a thread.
- **A thread whose session file is gone** (deleted, the projects folder
  cleaned, another box): `transcript(session)` is None. The switch refuses
  ("thread deck's conversation is gone"), the thread is marked `lost`, and
  the picker offers "Start it again from its log": a `thread new` with the
  thread's latest `[deck] Handover`, or its last log lines, as the seed.
  `reap_scratch` never touches transcripts, so this is a rare case.
- **A switch that does not land** (no session change in ten seconds, or an
  unknown dialog): `thread` is left as it was, the poll says "the switch
  to deck did not happen", the held rows stay held, the captain's message
  stays in the inbox. Nothing is typed into the wrong thread.
- **After a reboot** (or `no1_wake`, or `model-apply`'s restart): the
  process is started with `--resume st["session"]`, which is the current
  thread's: Number One comes back in the thread it was in, and the
  `[thread]` line is typed first so it knows which. `follow_newest`
  (the newest transcript in its worktree's project folder) must then pick
  among threads, not around them: a session that is a thread's is never
  pushed to `past` as "earlier conversation"; the newest of all is the
  current thread only if it is one of the list (otherwise adopted, as
  section 2's hand-typed `/resume`). herdr's own restore (`launched_bare`)
  resumes the same session and reap restarts it with hooks, as today.
- **A switch during a deploy**: allowed. The deploy's outcome is routed by
  `by_thread`, not by what is open.

## 8. Tests and slices

### Tests

- `scripts/test_no1_threads.py` (~1s, no server; slice 1's half built), on
  test_no1_inbox.py's stand-ins (herdr, the journal's inbox): the state's
  invariant through new, switch, fork, rename, close; a switch typed as
  `/resume <id>` and the session followed (by herdr's report, and by the
  transcript fallback); mid-turn switches recorded and done by the Stop
  hook, the last winning; the lock (a note and a switch at once: the note
  lands in exactly one thread, and the right one); held rows per thread,
  delivered once on the switch, joined into one input; a `/resume` typed
  by hand adopted; a lost session refused; the resume dialog answered;
  `follow_newest` after a restart.
- `scripts/test_no1_inbox.py`: the `#thread` mark on rows and `inbox_to`.
- `scripts/test_no1.py`: `no1.py thread` verbs, `log`'s tag and `logs
  --thread`; the brief's paragraph.
- The routing: `cmd_hook` (`[crew]` to the order's thread), the deploy and
  rollback's `by_thread`, `no1_answers`' asks map - in test_no1_threads.py
  with the existing mocks (test_ctx.py's pattern).
- The page: the QuickJS suite for the chips, the "view free, send
  switches" rule against the fake API, the voice orders (the suite fails a
  KEYS entry without one); `test/back.py` for Back from a thread's view;
  `test/keyboard.py` for the new sheet's fields; deckboot.js for the
  deck's order.
- A live check by hand before slice 1 ships: a real Claude Code in a
  scratch herdr tab (slice 0).

### Slices, smallest shippable first

0. **Spike, nothing shipped** (~30 min): a scratch Claude Code 2.1.280 in
   a herdr tab, a throwaway worktree. Type `/resume <id>` and `/branch x`
   through `herdr agent prompt`; record what herdr reports
   (`agent_session`), what the transcript folder shows, whether Remote
   Control's app view follows, what `/branch` leaves current, and the
   resume dialog's text and keys on a long session. The findings go into
   this doc's sections 2, 4 and 6.
1. **Threads in state, switched by Number One.** `engineer.py thread`
   and `no1.py thread` verbs (list, new, switch, rename, close), the lock,
   the idle rule, the `[thread]` line, `follow_session`/`follow_newest`
   kept straight, the brief's paragraph. No routing yet: notes go to the
   current thread as today, tagged with the thread that caused them
   (`[crew @deck]`), so nothing is lost. Usable at once from the app
   ("switch to the deck thread"). test_no1_threads.py's state and lock
   half.
2. **Routing and holding.** Each cause records its thread (section 3);
   the inbox's `#thread` mark; the flusher holds other threads' rows; the
   switch delivers them; the mid-turn switch by the Stop hook; asks per
   thread. This is where "none leaking" becomes true.
3. **The console.** The poll's `thread=` and `threads`, the say route's
   `thread`, `POST …/thread`; the chips, the unread counts, the sheet,
   the voice orders, Earlier conversations grouped by thread.
4. **The deck.** The chat sheet's chips, the pill's badge, the spoken
   order.
5. **Fork, and per-thread refresh and log.** `/branch`, `[x] Handover`,
   `logs --thread`, the console log's filter.
6. **Failure polish.** Lost threads restarted from their log; the
   picker's ctx and cache hint.

Slices 1 and 2 are scripts only (no page change, no server change); 3
touches `lcars_engineer.h` (a field passed through) and the page.

## 9. Decisions (the captain, 2026-10-20)

The eight open questions, answered all as recommended (through Number
One):

1. **Held, with a notice.** Reports for a thread not open wait there as
   unread. A failed deploy or an engineer stuck on a question also raises
   a console/deck notice naming the thread; Number One is never switched
   to it automatically.
2. **`@no1` notes go to main**, unless the note names a thread: `@no1
   #deck …`.
3. **Number One switches only when asked** (by the captain, or a switch
   the captain asked it to make). It may say that a thread has held
   reports.
4. **Up to 6 open threads**, none closed automatically. `thread new`
   refuses a seventh; closing one makes room.
5. **A new thread is a summary seed** (`thread new`, empty plus what
   Number One writes for it); a branch (`thread fork`, the full copy) is
   a separate verb, never the default.
6. **The full conversation on resume, always**: the resume question kept
   off by the environment, and answered "full" if it appears (section 2a).
7. **After a reboot, back in the same thread**: the process resumes
   `st["session"]`, the current thread's.
8. **The latest order's thread owns an engineer's reports**, with a
   warning to Number One when an order takes an engineer from another
   thread.

## 10. Slice 1 as built (0.282.0)

- State: `threads`, `thread`, `closed`, `switch`, `switching` in Number
  One's state file; with no `threads` the state is read as one thread,
  main, on `session`, so an existing Number One needs no migration (the
  list is written at the first thread verb).
- `engineer.py thread number-one <list|new|switch|rename|close> …` and
  `thread-go number-one` (the Stop hook's); `no1.py thread …` the same
  verbs for Number One. `new` takes its seed on stdin (no1.py: the third
  argument). `fork` waits for slice 5.
- Every typing verb runs under `no1-flush.lock`. Asked while Number One
  is working (always so when Number One runs it itself, in its turn) it is
  recorded as `switch` and returns `pending`; the Stop hook spawns
  `thread-go`, which waits for idle (up to two minutes) and does it, after
  a refresh's clear if one is noted. The last switch asked wins.
- The `[thread]` line is typed after every switch, joined with the new
  thread's seed. `clear_session` (a refresh, a clear) moves the current
  thread to the new session, the old one into `past` tagged with the
  thread. `follow_session` and `follow_newest` map a session that is a
  thread's to that thread, and never push a thread's session to `past`.
- Number One's tab gets `CLAUDE_CODE_RESUME_THRESHOLD_MINUTES`.
- No holding yet (slice 2): every note is typed into the thread open, and
  once there is more than one thread its tag names the thread that caused
  it, `[crew @deck] …`: an engineer's report and deploy by the thread of
  the order Number One gave them (`no1_thread` in their state, set at each
  `crew say`; an order taking them from another thread with work under
  way answers with a warning), an answered ask by the thread that asked
  (`asks` in Number One's state, written by `no1.py escalate`).

## 11. Slice 2 as built (0.284.0)

- The mark: `seat.inbox_title`/`inbox_add` take `thread`, written on the
  sender before `[fresh]` (`number-one ← crew#deck: …`); `inbox_to` strips
  it, `inbox_thread` reads it. Every cause of section 3's table records
  its thread (a refresh's at `refresh.thread`; a deploy's `by_thread` set
  by `detach` when `LCARS_THREAD_BY=no1`, which `no1.py crew deploy` and
  `rollback` now set). A crew note's thread is its first captain turn's
  leading `#<id>` (`crew_notes.no1_thread_of`), else main, passed as
  `no1-send --thread <id>`.
- Unlike section 3's first draft, a row with no mark is not main's but
  anyone's: the flusher types it into whichever thread is open (the ship's
  own notes, a failed switch's). Everything that knows its thread marks it,
  main included. A row marked with a thread closed since, or never known,
  is main's and typed with "(for thread deck, closed since)": closing
  moves nothing in the journal, so reopening a thread gets its notes back.
- `cmd_no1_flush` reads the inbox under its lock and types only
  `thread_deliverable` (the open thread's and the unmarked); its answer
  adds `held`. `thread list` gives each thread's `unread` (None when the
  journal does not answer).
- A switch (thread_do) types the `[thread]` line (other threads' held
  counts in it), the thread's held rows (`thread_held_text`: one "(held
  since … while you were in thread <left>)" line, then each row; a
  captain's row marked `[captain]` among the reports) and the captain's
  message as one input, then ticks the rows done. Threadless rows waiting
  start the flusher after it. The journal down, the line goes alone and
  the flusher types the held rows one by one once it is back.
- `say number-one --thread <id>` (and `thread` in `say --json`): another
  thread than the open one is a switch carrying the message; an unknown
  id exits 4 (the route's 404), checked before anything is recorded. Mid-
  turn the message becomes a held `captain#<id>` row and the answer's
  note is "waiting for Number One to finish in <name>"; only when the
  journal cannot take it does it ride on `st["switch"]`.
- Notices (decision 1): `no1_send(…, notice=True)` from a failed deploy and
  an engineer's `attention`, when the thread is not the open one and there
  are threads, posts the crew's urgent kind (`task_crew`: the console's
  Open questions and the deck's notice) titled "Held for Number One in
  thread <name>: <first line>", saying how to open it.
- The brief says reports wait in their thread and arrive held; the
  `[crew @deck]` tags are gone (`thread_tag` removed).

## 12. Slice 3 as built (0.284.1)

- **The routes** (`lcars_engineer.h`): the say's `thread` (NAME_RE's shape,
  else a 400) goes to the script as `say number-one --thread <id>` (after
  `--json` when files come); the poll's `&thread=` as a sixth argv
  (`-` for none); `POST /engineer/number-one/thread` hands its body to
  `engineer.py thread-req` on stdin. The script's exit 4 is now a 404 (no
  such thread), so the route stays a pass-through.
- **The script**: `cmd_poll(…, thread)` reads that thread's transcript,
  read-only when it is not the open one, and Number One's answer carries
  `threads` (id, name, unread, current, ctx, used), `thread` (the one
  shown) and `switch` (one waiting for his turn's end). `thread-req`
  checks the order and answers at once: rename and close are done in it;
  new and switch are spawned (`thread number-one new <id> <name> --seed
  <order>`: `--seed` because spawn hands on no stdin) and answered
  `pending`, a new one's row in the list marked `pending: true`. Fork
  answers a 409, "comes with slice 5" (decision: no `/branch` until its
  slice).
- **The console** (index.html, "Number One's threads"): `.chthr`, a row of
  chips under the header of his conversation (every mount: the full view,
  a dock window, the deck's frame), scrolling sideways, never wrapping;
  the open thread dotted, the shown one lit, the held count a badge. A tap
  is `engThreadView`: the chip lit and the log emptied to a line at once,
  then the poll with `&thread=`; Back is not a step (it stays one
  conversation: Back goes to the list). Away from his thread the status
  line and the box say so ("to Deck redesign — sending moves Number One
  there"). `engSend` carries `thread`; the bubble is `switching to …`
  until the poll reports him in it, then `sending…`, then delivered, or
  queued with the script's note mid-turn. `+` (and `U`, and "number one
  threads") is the sheet: each thread, New (what to call it, the opening
  order: a slug of the name is its id) and Branch (slice 5's answer). A
  long press or right click on a chip: Rename, Show, Close (off for main
  and the open one). Each change is shown at once (a pending chip, a name
  changed, a chip gone) with a live line in the log, the answer replacing
  it, a failure undoing the change and saying why there.
- **Voice**: "number one threads", "switch to <name> thread" (a real
  switch, `op: switch`: the captain said switch; a tap only views),
  "new thread <name>", "close the <name> thread". For the two with the
  name inside the phrase, `vTry` now takes a `{*}` followed by words of
  the phrase: it ends at the next of them.
- **Earlier conversations** are grouped under each thread's name once a
  kept one is tagged with a thread other than main.
- Not built here: the deck's chips and pill badge (slice 4), `/branch`
  (slice 5); a held message's bubble in a thread it was held for shows as
  queued only in the session that sent it (the inbox row is the record).

## 13. Threads v2: tags, not sessions (0.285.0)

**Superseded in full by docs/design/rooms.md** (slices 1-4): the tag is
the `room::` header, the labels are rooms (`no1.py room`), and every
message is a `crew_msg` row.

The captain's decision of 2026-10-21. A thread as a Claude Code session
blocked the others: a report for a thread not open waited, held, until
the captain switched (Zimmerman's report sat an hour while Number One was
idle in main), and Number One could not see across threads (a version
collision between two engineers was caught only because both reports
landed in one place). So: **one conversation, one context window, one
session; a thread is a label on messages**, and the console separates
them visually. Section 0's "none leaks into another's context" is
dropped, knowingly.

### The label

- **State**: Number One's state file keeps `threads`, a list of
  `{id, name, at}` (and `closed`, the epoch seconds, on one closed). No
  session, no "current" thread, no `switch`. A state from 0.282-0.284 is
  read as this on its first save (`thread_norm`): the old `closed` list
  merged in, the per-thread fields dropped, and a thread's session other
  than the one in use put into `past`, so its conversation stays readable
  under Earlier conversations. `main` always exists, cannot be closed.
- **Verbs** (`engineer.py thread number-one`, `no1.py thread`): `list`,
  `new <id> [<name>]` (a closed one of that id is reopened), `rename <id>
  <name>`, `close <id>`. All four only touch state; nothing is typed.
  No cap on how many.
- **The tag line**: a message for a thread other than main is typed with
  `[thread <id>]` as its first line. An untagged message is main's.
  `THREAD_TAG_RE` in engineer.py is the one parser.

### Delivery never holds

`cmd_no1_flush` types every inbox row, oldest first, as before threads;
a row marked `#<id>` (`seat.inbox_thread`), other than main, is typed
with its tag line first (then the off-duty "(held since …)" if any). Every
cause still records its thread (section 3's table: the engineer's
`no1_thread`, `deploy.json`'s `by_thread`, the `asks` map, `@no1 #deck`
notes, the refresh's). A row tagged with a closed thread is typed with its
tag all the same: the label says where it belongs.

The captain's say with `thread` (the route's parameter, `say number-one
--thread <id>`) prefixes the tag line and is typed as any say; an unknown
id is still a 404, a closed one is reopened.

### Which thread a reply is in

The transcript is the record: `thread_marks` walks a chunk of events and
gives each its thread. A message from the captain or the inbox is its tag
line's (stripped from the text shown), or main's. An assistant message,
and its tool lines, belong to the thread of the message before it: the
message that started the turn. A paragraph of Number One's that begins
`[thread <id>]` moves what follows to that thread, until the next
message comes in, so Number One can speak into another thread without
any discipline otherwise; engineers need nothing.

A poll reads from a byte offset, so the thread in force where a chunk
starts is found by reading backwards to the last message or override
(`thread_at`, at most THREAD_SCAN_BYTES). Every event of Number One's
poll carries `th`; `thread=<id>` filters the events to that thread (the
offsets still the transcript's). The same rule names **the turn's
thread** (`thread_now`: the thread in force at the transcript's end),
which is what an order to an engineer, an ask, a deploy or a refresh
records - so a report comes back tagged with the thread whose message
caused it.

### The console and the deck

The chips under Number One's header are **All** plus one per open
thread. A tap filters the conversation in place (the page has every
event and its `th`; no fetch), and the selected chip tags what is sent
(All: main). `+` (and `U`, and "number one threads") is the sheet: each
thread to show, and New (a name and an opening message: the thread is
made, selected, and the message sent into it as a normal send). A long
press on a chip: Rename, Close. The deck's chat sheet is the same frame.
Earlier conversations are one list again.

Voice: "number one threads", "switch to <name> thread" (the chip
selected), "all threads", "new thread <name>", "close the <name> thread".

### Removed

The `/resume` switch and `thread switch`, `thread-go` and the Stop
hook's mid-turn switch, the pending switch and `switching`, the
`[thread]` line typed at a switch, held rows and their delivery as one
input (`thread_deliverable`, `thread_held_text`, `thread_from`,
`thread_unread`, `thread_of_row`), the notice for a held report
(`thread_notice`), `fork` and its 409, per-thread sessions
(`thread_sync`, `thread_owner`, `past_add`'s thread tag), unread counts,
`THREADS_MAX`, the resume dialog's answer (`RESUME_FULL`), the thread
lock, the Stop hook following `session_id`, Earlier conversations by
thread, and the poll's `switch`, `current`, `unread` and per-thread
`ctx`. `RESUME_ENV` stays: it keeps the resume question off the restart's
`--resume` of the one session (decision 7).

### Cost

One context holds every thread, so it fills faster and the handover mark
comes sooner; a refresh clears all threads at once (their labels stay).
