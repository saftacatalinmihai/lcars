# Rooms: the crew's messages, one timeline per room

Status: designed 2026-10-23 (0.305.2); section 12's questions answered by
Number One for the captain the same day (all as recommended: section 12);
slice 1 built (section 15), slice 3 (section 16), slice 2 (section 17),
slice 4 (section 18): the rooms are done. **Supersedes section 13 of
docs/design/no1-threads.md** (threads v2, tags on Number One's one
conversation, live since 0.285.0) from slice 1 on. Written against `scripts/engineer.py`, `scripts/seat.py`,
`scripts/no1.py`, `scripts/crew_notes.py` and `lcars-ui/index.html` as
of 0.305.1.

Section 0 is the captain's decisions of 2026-10-23, verbatim in substance;
everything after it is how they are met. Where the decisions do not settle
something, section 12 asks, each with a recommendation.

## 0. The decisions (the captain, 2026-10-23)

1. Every message between crew (an engineer's report, Number One's order, a
   DM) carries a header as its first line, exactly one: `room:: <id>` or
   `to:: <name>`. Routing: the header first; without one, the room the
   order came from (today's `no1_thread`); without that, Number One's main
   room.
2. Every such message is a journal row (from, to, room, when, the **full**
   text, not a truncated copy), so a room is viewable on its own: a Rooms
   page in the console and the deck's chat sheet show one room as one
   timeline, whoever spoke, whatever conversation it was typed into.
3. Each crew member has a main room: their DMs. `to::` without a room lands
   in the destination's main room. Number One's orders carry `to::
   <engineer>` inside the room; reports carry `room::` back.
4. A turn the captain starts 1:1 with an engineer reports back to that
   engineer's main room, not to Number One's inbox, unless the engineer
   writes `to:: no1`.
5. A captain's message in a project room is typed to Number One only,
   unless `to::` names an engineer.
6. Crew-to-crew DMs are allowed, through the inbox, delivered when the seat
   comes to the addressee, visible to the captain in both main rooms.
7. The captain never types headers: the console and the voice orders set
   the room ("new room motion graphics", "in the deck room, ...").
8. Number One is in every project room by default, and in nobody's main
   room but its own.
9. Rooms are created by the captain (console, voice) or by Number One when
   it sees the need (`no1.py room new/list/rename/close`).
10. Thread ids carry over (main, deck, status-report, rooms-channels); the
    word becomes *room* everywhere; `no1_log` and the asks keep their tags.

## 1. Words

- **Room**: a place messages are kept, with an id (a slug, `NAME_RE`:
  `[a-z][a-z0-9-]{0,23}`) and a name. Two sorts:
  - a **project room** (`deck`, `rooms-channels`): made by the captain or
    Number One; members are the captain and Number One, and whoever is
    addressed in it;
  - a **main room**, one per crew member, implicit (never made, never
    closed): Number One's is `main` (decision 10: today's main thread), an
    engineer's is their name (`obrien-c33`). Its members are the captain
    and its owner.
- **Message**: one row (section 3): who from, who to, which room, when,
  the full text. What is typed into a session is made from it.
- **Member**: who a room's messages are delivered to (typed into their
  session) when no `to::` says otherwise. The captain is a member of every
  room but is never typed to: the captain reads.
- **Delivery**: typing a message into the addressee's Claude Code session,
  through their inbox (`crew_inbox`, unchanged: section 3.3).

An id is unique across both sorts: `room new` refuses a crew member's name
(engineer.py's known names and `NOT_NAMES`), and `crew start` refuses a
name that is a project room's id. `main` stays Number One's alone.

## 2. The protocol and its parser

### 2.1 The header

The first line of a message, alone on it, exactly one of:

```
room:: deck
to:: obrien-c33
```

`room:: <id>`: the message is for that room, delivered to its members
(section 4). `to:: <name>`: for that crew member; the room is the one in
force (section 2.3) if it is a project room, else the addressee's main
room (decision 3). The captain is not a name a crew member writes to:
whatever a crew member says lands in a room the captain reads already.
`no1` and `number-one` both name Number One.

The `::` is Logseq's property form, which the journal already speaks
(`id:: …` lines in entries), so a header is readable in the raw row too.

### 2.2 The parser: one regex, one place

A new module, `scripts/rooms.py`, holds it, and engineer.py, no1.py,
seat.py and crew_notes.py import it (crew_notes.py's copy of the note rule
in node shows the pattern for the page's copy, below):

```python
HEADER_RE = re.compile(
    r"^[ \t]*(?:(room|to)[ \t]*::[ \t]*([a-z][a-z0-9-]{0,23})"
    r"|\[thread ([a-z][a-z0-9-]{0,23})\])[ \t]*(?:\r?\n|$)", re.I)

def header(text):
    """(kind, id, body): kind "room" or "to", or (None, None, text)."""
```

- The keys are matched case-blind and the id lowered (`Room:: Deck` is
  `room:: deck`), spaces around `::` allowed: a model writing the header
  gets it a little wrong more often than badly wrong, and a near miss
  costing a misroute is worse than accepting it.
- `[thread <id>]` (threads v2's tag line) is read as `room:: <id>`, so a
  transcript of before the switch, and any inbox row queued across a
  deploy, is read by the same parser (section 9). Nothing writes it after
  slice 1.
- Only the first line. A `room::` further down is text: an engineer
  quoting the protocol in a report must not reroute it. One exception,
  kept from threads v2 for Number One alone: a paragraph of its reply that
  begins with a header line (the text's start or after a blank line)
  starts a new message from there (section 4.4); `PARA_RE` is
  `HEADER_RE` with `(?m)` and the paragraph test, in the same module.
- `rooms.py` also holds `ROOM_ID_RE` (`NAME_RE`), the title format
  (section 3.1) and its reader: the inbox's `THREAD_MARK`, `THREAD_TAG_RE`
  and `THREAD_OVERRIDE_RE` are deleted from seat.py and engineer.py, and
  `FROM_LEAD_RE` skips a header line instead of a `[thread]` one.
- The page has the same pattern once (`ROOM_HEAD_RE`, beside `engFrom`)
  for drawing a message without its header; `scripts/test_rooms.py` runs
  the page's copy under node against the Python table, as
  test_crew_notes.py does for the note rule.

### 2.3 Routing, in order

For a message from S:

1. **The header.** `room:: R` → R. `to:: N` → the room in force if it is a
   project room, else N's main room; delivered to N.
2. **No header: the room in force.** For an engineer, the room their
   current order came from (`room` in their state, today's `no1_thread`,
   set by every delivered order: section 4.2). For Number One, the room of
   the message that started its turn (today's `thread_now`). For the
   captain, the room the console or the voice order is in (never a guess:
   section 6).
3. **Neither: Number One's main room** (`main`).

A header naming no such room, or no such crew member, is section 10.1.

## 3. The data model

### 3.1 A new kind, `crew_msg`; `crew_inbox` stays the delivery slip

One row per message:

| column | holds |
|---|---|
| `kind` | `crew_msg` |
| `title` | `<from> → <to> #<room>: <first line, 90 chars>`, e.g. `no1 → obrien-c33 #deck: Rebase onto main…`; a message to the room has no `<to>`: `obrien-c33 → #deck: Report: done…` |
| `content` | the full text as sent, its header line first (the row says on its own where it went) |
| `done_bool` | delivered: 1 once typed, or at once when nobody is typed to (the captain reading, a report into a main room); 0 while it waits in an inbox |
| `value_int` | the `crew_inbox` row carrying it, 0 when none |
| `created_at_utc` | when it was sent (the server's) |

`from` is `captain`, `no1`, or an engineer's name; `to` a crew member's
name or empty (the room's members). The title is the index: the Rooms page
and `engineer.py room log` read a room by its `#<room>` mark (section
12, Q1 on a server filter).

**Why a new kind and not crew_inbox generalised:**

- crew_inbox is a delivery slip: `db-prune.py --apply` hard-deletes done
  ones after seven days (the one hard delete there is), and must keep
  doing so; a room's history must not be pruned. Exempting some inbox rows
  would weaken the prune's one rule (done and untouched) into a judgement.
- It carries notes that are no one's message: the seat's, the ship's, a
  job's result, the `[refresh]`. Those stay out of the rooms.
- Its content is what is typed, and the captain may edit or cancel it
  before delivery (the console's Inbox); a report's typed copy may be
  clipped for tokens (section 11). The message row is what was *said*,
  whole.
- Many messages need no delivery at all (anything the captain only reads),
  and would be inbox rows done at birth.

So a message that is delivered is two rows: the `crew_msg` (the record)
and a `crew_inbox` (the slip, its title carrying `#<room>` as today's
`#thread` mark, read by `rooms.py`). The inbox's edit, cancel and restore
in the console update the message's text and state too (value_int is the
link): an edited order is the order said.

**Who writes**: engineer.py, with the seat's login (`crew_tool.py`'s,
`owner crew`), whose own kinds `crew_*` already include `crew_msg` and
`crew_room`: no change to `lcars_logins.h`. Number One's login does not
write them (no1.py goes through engineer.py, as its crew verbs do); the
captain's console does, as the owner.

### 3.2 Rooms: `crew_room` entries

A project room is a row: `kind crew_room`, `title` its name, `content`
`id:: <id>` (and the line `by:: captain|no1`), `done_bool` 1 when closed.
The lowest id of an `id::` wins, as the `settings` and the seat entries
do. In the journal because the captain sees, renames and closes them from
the Rooms page, and a crew member (Number One) works with them (CLAUDE.md:
state the captain should see lives in the journal); Number One's state
file's `threads` list is retired (a cache of the rows may stay in it for
the poll's speed, never the truth).

Main rooms are not rows: they are the crew list (engineer.py's states)
plus `main`.

### 3.3 What stays

- `crew_inbox`, its title format, `inbox_fresh`, the seat's delivery
  (`seat_deliver`), Number One's flusher (`cmd_no1_flush`), its wake and
  retry (`no1-send`). Each gains one thing: the slip it delivers ticks
  its message delivered (`done_bool` 1).
- `no1_log` keeps its tag (decision 10): `thread:: <id>` becomes
  `room:: <id>` in what it writes from slice 1, both read.
- The asks: `asks` in Number One's state maps an ask to its room, as now;
  the `[captain] ticked off …` line is typed with that room's header.
- `@no1 #deck …` crew notes: `#deck` names the room (unchanged syntax).

## 4. Delivery, per sender and addressee

### 4.1 The table

| sender | where | header | the row's room | typed to |
|---|---|---|---|---|
| captain | a project room | none | that room | Number One (decision 5) |
| captain | a project room | `to:: eng` (the console's To chip) | that room | eng; their report comes back to the room, so to Number One too |
| captain | Number One's main room | none | `main` | Number One |
| captain | an engineer's main room (1:1) | none | eng's main room | eng; their report stays in their main room (decision 4) |
| Number One | its turn's room | `to:: eng` (no1.py adds it) | the turn's room if a project room, else eng's main room | eng |
| Number One | its reply to the captain | none, or a paragraph's `room::` | the turn's room (or the paragraph's) | nobody (the captain reads) |
| engineer | report of a No.1-started turn | none / `room:: R` | the order's room / R | Number One, if R is a project room or `main` |
| engineer | report of a captain-started 1:1 turn | none | their main room | nobody (decision 4) |
| engineer | any turn | `to:: no1` | the order's room if a project one, else `main` | Number One |
| engineer | DM | `to:: other` | other's main room (no project room in force) or the project room | other, when the seat comes to them (decision 6) |
| the ship | `[deploy …]`, `[rollback]`, `[job]`, `[seat]`, `[refresh]` | the cause's room (`by_room`) | the cause's room, for deploy and rollback only | as today |

Number One being in every project room (decision 8) means: a message in a
project room with no `to::`, from anyone but Number One, is typed to
Number One. In a main room it is typed to that room's owner only, and
Number One sees nothing of an engineer's main room unless written `to::
no1`.

### 4.2 Which turn reports where

Today `under_no1` (set by any `[No.1]` order, until dismissed) sends the
end of *every* later turn to Number One, the captain's own 1:1 turns
included. Decision 4 replaces it with the turn's cause: each delivery
(seat_deliver, `tell`, `cmd_say` typing directly) records in the
engineer's state `turn: {from, room, at}` from the last message typed, the
latest order owning the reports as threads v2 decided (its decision 8).
The Stop hook (`cmd_hook turn-ended`) then:

1. writes the turn's last message as a `crew_msg`, routed by its header,
   else `turn.room`;
2. delivers it to Number One when that room is a project room or `main`,
   or when the header is `to:: no1`;
3. delivers nothing else: a captain's 1:1 turn ends in the main room,
   where the captain reads it.

`under_no1` stays only for the `attention` hook (a question on screen is
told to Number One if its last order was Number One's), and is renamed
for what it is then. A turn started by a ship's note (a `[job]` result)
keeps the room of the order that queued the job.

### 4.3 What is typed

The header line, then the mark and the text as today:

```
room:: deck
[crew] obrien-c33 (Chief O'Brien) finished a turn. Report: …
```

The addressee reads the room from the first line; an engineer's brief
(section 5) says to answer under the same room. What is typed of a report
is clipped as today (1200 characters) with the row named for the rest:
`… (whole: crew_msg #4812, no1.py room show 4812)`; the row has it all.

### 4.4 Number One speaking into several rooms

Its turn's last message is cut where a paragraph begins with a header
(`PARA_RE`), each part a message of its own: the part before any header
is the turn's room's. That is threads v2's override with the new header,
and it is what lets Number One answer a report from `deck` and tell the
captain in `main` in one turn. Its orders need nothing of the kind:
`no1.py crew say` writes the order's row and its header itself.

### 4.5 DMs between crew

An engineer writes a DM as the last message of a turn with `to:: other`
first; the Stop hook makes it a `crew_msg` and a `crew_inbox` slip for
`other` (`other ← obrien-c33#<room>: …`), and the seat delivers it when it
comes to them (decision 6), as any order. The reply is the addressee's
turn's end; with no header it goes back to the sender, in the room the DM
is in (section 12, Q3). Mid-turn there is
no way to send a DM: a turn's text is only read at its end, and that is
deliberate (one row per turn, no tool to learn).

## 5. The briefs

### 5.1 For engineers (in `brief()`, replacing "Reporting to Number One")

> Rooms: every message between the crew starts with one header line.
> A message you are given begins `room:: <id>` (the room it is in) or
> `to:: <you>`; answer in the same room and you need write nothing: the
> last message of your turn is filed there. To write elsewhere, make the
> first line of your last message `room:: <id>` (a project room) or
> `to:: <name>` (a crew member: `to:: no1` for Number One). A turn the
> captain started with you alone stays in your own room, for the captain
> to read; Number One sees it only if you write `to:: no1`. A message to
> another engineer reaches them when the seat comes to them: use it for
> what they need, not for thanks. If the captain, with you alone, gives
> you an order that changes the task Number One gave you, make the first
> line of that turn's last message `to:: no1` and say in a line what
> changed: the captain's word stands over Number One's.

(The last sentence is the captain's, ordered with slice 3.)

### 5.2 For Number One (in `brief_no1()`, replacing "Threads:")

> Rooms: your conversation is one, and every message in it starts with a
> header line naming its room (`room:: deck`) or you (`to:: no1`); one
> without is `main`, your own room. Your reply is filed in the room of the
> message that started your turn. To speak into another room, begin a
> paragraph with its own line `room:: <id>`. You are in every project
> room; engineers' own rooms are theirs and the captain's. `{n1} crew say`
> files your order in your turn's room, addressed to the engineer; their
> report comes back there. `{n1} room list` names the rooms; `room new
> <id> "<name>"` when a piece of work needs its own (say so to the
> captain), `room rename`, `room close`; `room log <id> [n]` reads a
> room's latest messages, `room show <msg id>` one in full. Keep each
> room's matters in its own room.

## 6. The Rooms page and the deck's sheet

### 6.1 The console (`#rooms`)

Mobile first, at 393px:

- **The list**: project rooms first (open ones, the newest message first),
  then the main rooms (Number One's, then each engineer's by last
  message). Each row: the name, who spoke last and their first line, the
  time, and an unread dot (the newest row id against the last one seen,
  kept in localStorage per room: no server state for a read mark). Closed
  rooms behind a "Closed" row at the bottom. `+` is New room (a name, an
  optional opening message to Number One).
- **A room**: one timeline of its `crew_msg` rows, oldest at the top,
  whoever spoke, each bubble its sender's (the chat's look: the captain on
  the right, crew on the left with the speaker's name, the ship's lines
  small), the header line not drawn but shown as a small `→ obrien-c33`
  where a message was addressed. A long message folded at 12 lines with
  More. A message waiting in an inbox shows "waiting for the seat" (its
  slip not done), as the engineer chats' inbox does.
- **The box**: what the captain writes goes to the room's default
  addressee (Number One in a project room, the owner in a main room); a
  **To** chip beside Send picks another (the room's engineers, those who
  have spoken in it first). The header is the page's, never the
  captain's (decision 7).
- Immediate feedback (CLAUDE.md's rule, chat.md §3): a send is a bubble at
  once, "sending…", then "waiting for the seat" or "delivered"; a failure
  says so on the bubble with Retry and the text given back. New room: the
  row appears at once, "opening…", then the room itself.
- **Reading**: the page polls `GET /entries?kind=crew_msg&min_id=<last>`
  while open (the same 3 s as the chats), and the list on open. Number
  One's and the engineers' conversations stay where they are (the chats,
  with tool lines and all); a room is the messages only, and each bubble
  links to its place in that conversation ("in Number One's
  conversation", the poll's key), where there is one.
- Number One's chat keeps its chips, renamed rooms (`engThreads` →
  `engRooms`), still a filter of its own conversation by header; `+`
  opens the Rooms page's New room.

### 6.2 The deck

The deck's chat sheet is the console's frame already: it opens
`index.html#rooms/<id>` in it (the talk sheet's slot), so the deck needs
only the door: a "Rooms" row in the sheet's ⋯ and the voice orders, and
a key only if one is free among deck.html's (Q6). The sheet at a
phone's size is the page's 393px layout, unchanged.

### 6.3 The voice orders

`VCMDS` (index.html), each calling what the button calls:

| say | does |
|---|---|
| "rooms", "show the rooms" | the list |
| "open the <name> room", "go to the <name> room" | that room |
| "new room <name>" | made and opened, empty |
| "in the <name> room, <message>" | sent there to Number One (decision 5) |
| "in the <name> room, tell <engineer> <message>" | sent there, `to::` them |
| "tell <engineer> <message>" | into their main room (1:1) |
| "rename the <name> room to <new>", "close the <name> room" | as the buttons |
| "my rooms", "unread rooms" | the list, unread first |

`<name>` is matched against the rooms' names and ids by the deck's
`roomNamed` way of comparing spoken names (normalised, longest wins).
The deck's `DVCMDS` already has place orders with "room" in them ("go to
the ready room", "rename this room"): section 10.6.

## 7. Number One's verbs

`no1.py room …`, engineer.py's `room` holding the rules (the route
`POST /engineer/rooms` for the console's buttons, owner only, as the
thread route):

| verb | does |
|---|---|
| `room list` | open rooms (id, name, last message, count); `--closed` |
| `room new <id> ["<name>"]` | a `crew_room` row, `by:: no1`; a closed one of that id reopened; a crew name refused |
| `room rename <id> "<name>"` | the title |
| `room close <id>` | done; not `main`, not a main room |
| `room log <id> [n]` | the latest n (20) messages of a room, clipped per row |
| `room show <msg id>` | one message whole |

`no1.py thread …` stays one release as an alias printing the room verb
to use, then goes.

## 8. Engineer-side names

- `no1_thread` → `room` (and `turn`, section 4.2), read from either.
- `deploy.json`'s `by_thread` → `by_room`, read from either.
- `notify_no1(about, text, thread)` → `room`, `no1_send(text, room)`;
  `thread_tagged` → `rooms.headed(text, room)`; `thread_marks`,
  `thread_at`, `thread_now` → `room_marks`, `room_at`, `room_now`, the
  same walks with the new parser.
- The poll's `th` → `room` (the page reads both for a release).
- `LCARS_THREAD_BY` (no1.py's deploy marker) → `LCARS_ROOM_BY`.

## 9. Migration from threads v2, nothing lost

In slice 1, by `engineer.py rooms-migrate` (a dry run by default, `--apply`
to write, idempotent: run twice writes nothing the second time):

1. **The list**: each thread in Number One's state (open or closed) becomes
   a `crew_room` row of the same id and name (closed ones done), unless a
   row of that id exists. The state's `threads` stays until slice 2's
   deploy, unread.
2. **The history**: Number One's transcripts (the current session and
   `past`) walked with `room_marks`: every message of the captain's, every
   inbox note typed (reports, deploys, answers), and each turn's last
   message of Number One's become `crew_msg` rows in their room, `done`
   1, with the original time in the title's line (`created_at_utc` is the
   server's; the time is kept as `at:: <utc>` in the content's second
   line, which the page shows in place of the row's) and a `src:: <session>
   <key>` line, which is what makes a second run skip them.
3. **What is in flight**: inbox rows marked `#<thread>` are read by the new
   parser as rooms; any `[thread x]` line still to be typed is read as
   `room:: x`. Engineers' `no1_thread` and `by_thread` are read as `room`
   and `by_room`.
4. **Engineers' main rooms** start empty: their 1:1 history is their
   conversations, which stay readable in their chats (section 12, Q4).

Nothing is deleted: the transcripts, the inbox rows and the state are left
as they are; the rows are copies. The dry run prints the count per room
and a sample, and runs on a scratch copy in the test.

## 10. Failure cases

1. **A header mistyped** (an unknown room id, an unknown name): the
   message is filed by the fallback (the room in force, else `main`) with
   `misrouted:: <what it said>` as its second line, delivered as the
   fallback room's would be, and the page shows the bubble marked
   "addressed to deck2, which does not exist". No bounce to the sender: a
   bounce is a seat turn spent on a typo; Number One sees it in its room
   and can resend. A header with a near-miss form (`room: deck`, one colon)
   is text, and the fallback files it in the right room anyway in almost
   every case (the order's).
2. **A room closed**: a crew message into it is filed there all the same
   (the label says where it belongs, as threads v2), delivered to its
   members, and the room's row in the list shows the new message under
   Closed with its dot. The captain's word into it reopens it (as v2);
   Number One's `room new <id>` reopens it; a crew member's word does not.
3. **An engineer cleared mid-order** (`crew clear`, a `--fresh` order, a
   handover): `room` and `turn` are in their state, which a clear keeps,
   so the next report still knows its room. The order itself is in its
   row; Number One's brief already says to `crew say` the whole order
   after a clear, and the re-sent order carries the header again.
4. **An engineer dismissed, or never started**: a DM or an order to them
   waits in their inbox (the seat's rule) and its bubble says "waiting for
   the seat"; `to::` a name nobody has is case 1.
5. **The journal down** (a restart): the Stop hook's write goes to the
   retry unit `no1-send` already uses, now `room-send`, for the row and
   the slip together; delivery of what is already in the inbox is
   unaffected. Delivery never waits on the row.
6. **The word "room" in the deck**: "go to the ready room" and "go to the
   deck room" would meet in `vMatch`. Room orders say the room's name
   *and* the word "room" only after a crew room's name: a spoken name that
   is no crew room falls through to the deck's own orders. Tested in
   deckvoice.py (slice 2).
7. **A DM loop** (two engineers thanking each other): each DM is a seat
   turn. A cap in the Stop hook: an engineer's third DM within an hour to
   the same one, with no word from the captain or Number One between, is
   filed but not delivered, and Number One gets one line saying so.
8. **Two messages delivered as one turn** (`seat_deliver` joins an inbox):
   each keeps its header at its paragraph's start; the turn's room is the
   last one's (the latest order owns the reports).
9. **A long message**: rows hold any length (the server's body cap, 1 MB
   for a request, is far above a turn's text); what is typed is clipped
   (section 4.3), never the row.

## 11. Cost

- **Rows**: one POST per message, two when delivered; ~100-200 a day at
  today's pace, a few KB each: a few tens of MB a year, never pruned.
  Nothing for the server to index: the kind filter and min_id paging.
- **Tokens**: a header is ~5 tokens per message. Reports typed to Number
  One stay clipped as today. The one real saving: the captain's 1:1 turns
  with an engineer are no longer forwarded to Number One (decision 4),
  each of which today costs Number One a turn over its whole context.
- **Seat turns**: a DM is a seat turn of the addressee's (a start of their
  session if they are off, their context read again): the dearest thing
  here, hence the brief's line and section 10.7's cap. A report into a main
  room costs no turn at all.
- **Number One's context**: unchanged in kind (one conversation, every
  room); a room's history no longer *needs* its context, since the page
  reads rows, so a refresh loses nothing the captain can see.

## 12. Decisions on the open questions (Number One, 2026-10-23)

Asked as open questions with a recommendation each; Number One answered
them for the captain, all as recommended.

- **Q1. A server filter for a room: none in slices 1-4.** The rows are
  read by kind with `min_id` paging and filtered by the title's `#room`
  in the script and the page, which keeps what it has read in the
  mirror. Revisited at 20 000 rows (`GET /entries?title_prefix=`, or a
  room mark in a column).
- **Q2. Number One's replies are rows: yes.** Each turn's last message of
  Number One's is a `crew_msg` row too, cut by paragraph headers (4.4),
  not its mid-turn text: a room must show the answers, not only the
  questions.
- **Q3. A DM's reply goes back to its sender.** A delivered DM sets the
  addressee's `turn` to the DM's room with `reply_to: <sender>`, so a
  reply with no header goes back `to:: <sender>` in that room; both main
  rooms show both (decision 6).
- **Q4. No backfill of engineers' 1:1 history.** Their chats keep it, and
  those turns were not written as messages; only Number One's threads,
  the rooms' first form, are migrated (section 9).
- **Q5. Number One is told nothing of 1:1 work** beyond what `crew list`
  shows already (who holds the seat, the queue).
- **Q6. The Rooms page's key: slice 2 decides**, against `KEYS` and the
  deck's keys; the voice order and the palette row are the must.

## 13. Tests

- `scripts/test_rooms.py` (new, ~2s, no server; the stand-in server of
  test_seat for the rows): the parser's table (each form, case, spaces,
  near misses, the legacy tag, only the first line, the paragraph form
  for Number One), and the page's copy under node against it; routing
  for every row of section 4.1's table; the rows written (title, content
  whole, done, value_int) and the slip; the inbox's edit and cancel
  carried to the row; the Stop hook's turn routing (decision 4's case
  and `to:: no1`); the failure cases 10.1, 10.2, 10.5, 10.7, 10.8; the
  migration's dry run (no write) and `--apply` twice (the second writes
  nothing); every test importing engineer.py guarded (testguard).
- `scripts/test_no1_threads.py` becomes the rooms' carry-over checks:
  v2 state, tags and inbox marks read as rooms.
- `scripts/test_no1_inbox.py`, `test_seat.py`, `test_crew_notes.py`,
  `test_queue.py`: unchanged contracts, rerun (they read inbox titles).
- Slice 2: the QuickJS behaviour suite (the list, a room's timeline from
  rows, the To chip's header, the optimistic bubble, Retry, unread dots),
  `test/keyboard.py` lines for the box and New room's fields,
  `test/rooms_ui.py` (new, Chromium at 393x852 against a scratch server: a
  send through to its row, waiting for the seat, a failure, a room made,
  closed and reopened, Back), `buttons.py` (the view's door, Close,
  Escape, Back), `deckvoice.py` (the room orders and 10.6), a perf.py
  scenario for a room of 2000 rows.

## 14. Slices, smallest first

1. **The protocol, the rows and the fallback** (scripts only, patch):
   `rooms.py` (the parser, titles), `crew_msg` and `crew_room` rows from
   every send (no1.py crew say, the captain's say, the Stop hooks, the
   flusher's notes), the routing of section 4.1 *except* decision 4's
   change and DMs (reports still go to Number One as today, so nothing
   changes for anyone yet), the header replacing `[thread]` in what is
   typed, the renames of section 8, the migration, test_rooms.py. The
   console's chips keep working (the poll's `th` kept beside `room`).
2. **The Rooms page and the deck's sheet** (minor): section 6, the voice
   orders, the console's New/Rename/Close on `crew_room` rows, the chips
   renamed.
3. **The DMs** (minor): decision 4 (the captain's 1:1 turns stay in the
   main room: `turn` replaces `under_no1`), decision 6 (crew to crew, the
   cap), the engineers' brief paragraph (5.1).
4. **Number One's room verbs and its brief** (patch): `no1.py room …`,
   5.2, `thread` as an alias for a release, then section 13 of
   no1-threads.md marked superseded in full and the state's `threads`
   dropped.

Slice 1 is a deploy that changes nothing anyone sees but the header line
(`room:: deck` where `[thread deck]` was) and starts the record; every
later slice reads rows that already exist.

## 15. Slice 1 as built

Scripts only (and the page's copy of the header regex); nothing anyone
sees changes but the header line Number One is typed (`room:: deck` where
`[thread deck]` was), and the record starts.

- **`scripts/rooms.py`**: `HEADER_RE` and `PARA_RE` from one pattern
  (section 2.2), `header`, `strip`, `headed`, `typed_for_no1`, `split`
  (threads v2's override, moved here), `title`/`title_parse`, `content`,
  `room_row_id`. index.html's `ROOM_HEAD` is the page's copy, used by
  `engFrom` and `engFromText` in place of the `[thread]` pattern;
  test_rooms.py runs it under node against the table.
- **The rows' I/O is seat.py's** (it has the crew login): `msg_add`,
  `msg_waiting`, `msg_delivered` (a slip delivered ticks its message, and
  an order the captain edited in the inbox before delivery takes the text
  as typed: the console's Inbox writes the slip directly, so delivery is
  where the edit is seen), `msg_cancelled` (from `inbox_cancel` and
  `inbox_uncancel`: queue remove and restore), `msgs_all`, `rooms_rows`,
  `room_put`. engineer.py's `msg_post` and `room_row` never raise: a row
  lost costs nothing but the row.
- **Content's header**: `to:: <name>` for an engineer addressed by name,
  `room:: <room>` for the room's members, a message to Number One
  included (it is in every room, decision 8); the title carries both.
- **Where the rows come from**:
  - `cmd_say` (`say_msg`): the captain's to Number One in the say's room
    (else main); Number One's `[No.1]` order in the project room it gave
    it in, or (from main) the engineer's main room (decision 3); the
    captain's to an engineer in their main room. Typed: delivered at
    once; queued: `done` 0 and `value_int` the slip (`seat_want`'s
    `slips`). A slash command is none.
  - The engineer's Stop hook: under Number One's orders (`under_no1`,
    unchanged in this slice), the turn's last words whole, routed by
    their header (`msg_route`: a known room, `to:: no1`, or a misroute
    filed in the fallback with its `misrouted::` line), else the order's
    room, as the report's message beside its slip, whose typed text
    stays clipped at 1200. Not under its orders (the captain's turn):
    one row in their main room, delivered, nothing told to Number One
    (as before). A question on screen is a notice, no row.
  - Number One's Stop hook (Q2): the room its turn began in
    (`room_turn`: the last message typed into it, its own overrides left
    out) read at once, then `msg-turn` spawned with the text in a spool
    file (`STATE/msgs/`), which `no1_turn_msgs` cuts by room lines into
    rows. Spawned, not inline: the hook has 10 s and the journal may be
    slow, and the room is read first because the flusher may type the
    next note the moment the turn is over.
  - The notes to Number One (`no1_send`'s `msg`): a deploy's or a
    rollback's outcome (from `ship`) and the captain's words carried (an
    ask ticked off, a journal note) are rows; the seat's, a job's, a
    refresh's and a `[crew]` notice are not (`MSG_NOT_TAGS`). The retry
    unit (`no1-send`) carries `--from` and the whole text in a spool file
    (`--full`), and takes `--room` beside `--thread`.
  - The labels: `thread new/rename/close` (and a say reopening a closed
    room) keep a `crew_room` row each, `by:: captain` from the console's
    route, `by:: no1` otherwise. The state's `threads` stays the truth
    until slice 2.
- **The renames of section 8, read from either**: the engineer's `room`
  (`no1_thread` read by `eng_room`, dropped on the next order),
  deploy.json's `by_room` (`deploy_room`), `LCARS_ROOM_BY` beside
  `LCARS_THREAD_BY`, `seat.inbox_room` (`inbox_thread` an alias), the
  poll's events' `room` beside `th` and its `rooms` beside `threads`.
  The function names `thread_*` stay for now (slice 4 renames them with
  the verbs).
- **Engineers are typed nothing new**: their orders still begin
  `[No.1]`; the header reaches them in slice 3, with their brief's
  paragraph. Number One's brief says `room:: <id>` now, and that the
  older `[thread <id>]` means the same.
- **`engineer.py rooms-migrate [--apply] [--sample N]`** (section 9): the
  threads as `crew_room` rows, Number One's conversations (the current
  one and `past`) walked with the marks into rows - every message typed
  into it but the seat's, a job's and a refresh's plumbing and a
  question's notice, and each turn's last text of Number One's, whole
  (`events_of`'s clip lifted) - each with `at::` (the transcript's time)
  and `src:: <session> <key>`, by which a second `--apply` writes
  nothing. A dry run only reads.
- **Tests**: `scripts/test_rooms.py` (the parser's table and the page's
  copy under node, split, titles; every source of rows, delivery, the
  inbox edit and a cancel, the routing and a misroute, the retry, the
  room rows; the carry-over names; the migration's dry run and two
  applies), `test_no1_threads.py` and `test_no1_inbox.py` on the new
  header line.

## 16. Slice 3 as built

Scripts only (engineer.py; the page untouched: the Rooms page, slice 2,
is built on the same rows).

- **The turn** (4.2): `turn_set(name, from, room[, reply_to])` writes
  `turn: {from, room, at}` into the engineer's state before a message is
  typed (a turn may end before herdr answers): `cmd_say` typing directly
  (`say_turn`: Number One's order in the room it gave it in, `main`
  included, the captain's in the engineer's own room), and `seat_deliver`
  from its slips (`slip_turn`: the slip's sender, `No.1`, `captain`, or an
  engineer with a `#<room>` mark, a DM; the ship's, the seat's, a job's
  and a handover's record nothing, so the turn keeps the room of the order
  before them; of several slips the last person's wins, 10.8). `tell`
  itself types only the ship's notes and records nothing. A state from
  before (no `turn`) is read by `turn_of` as slice 1 did: Number One's
  under `under_no1`, in its order's room, else the captain's.
- **The Stop hook** (`cmd_hook turn-ended`, `turn_route`): the last words
  routed by their header (`msg_route`), else the turn's room; then
  - `no1`: the room is `main` or a project room (`room_project`: one of
    Number One's, not a crew member's own), or the header is `to:: no1`
    (from a 1:1 turn filed in `main`): its inbox slip and the row, as
    slice 1 sent every report under its orders;
  - `dm`: `to:: <engineer>`, or no header in a turn a DM started
    (`reply_to`): `dm_send`;
  - `room`: a main room, typed to nobody: the `msg-turn` row only.
  A misrouted header falls back as in slice 1 and is never a DM.
- **`under_no1` keeps its name** (the states on the box hold it, and
  test_seat's and test_engineer_model's unchanged contracts read it) but
  has one use left, read through `questions_to_no1`: a question on screen
  is told to Number One once it has given the engineer an order, until
  they are dismissed.
- **DMs** (4.5, decision 6, Q3): `dm_send` writes the row (`<from> → <to>
  #<room>`, done 0, `value_int` its slip) and a slip `<to> ← <from>#<room>:`
  through `seat_want(..., by="dm", room=)` (its new `room` marks the
  slip), typed as `room:: <room>` then `[DM from <name> (<title>)] <text>`
  (clipped at 6000 characters; the row whole). The room is the project
  room in force, else the addressee's main room (decision 3); a reply
  with no header stays in the DM's room. Delivery sets the addressee's
  turn `{from: <sender>, room, reply_to: <sender>}`. With no seat (a
  laptop) it is typed at once if they are on duty, as a ship's note is.
  **The page** shows a DM in both main rooms by its title: a main room
  `X`'s timeline is its own `#X` rows plus those whose `<from>` or `<to>`
  is `X` filed in a main room (slice 2's filter, `rmIndex`: section 17).
- **The cap** (10.7): the sender's state keeps `dms: [{to, at}]` for the
  hour; a third to the same one is filed with `held:: the DM cap` on its
  second line, done 1 and no slip, and Number One gets one `[crew]` line
  (no row) naming the row. Any delivery from the captain or Number One to
  the sender (`turn_set`) empties the count.
- **The brief** (5.1, with the captain's `to:: no1` line): `brief()`'s
  "Rooms:" paragraph, its opening worded for what engineers are typed
  today (Number One's orders still begin `[No.1]`, no header: below); "Reporting to Number One" keeps only what a report
  holds and the handover, its first sentence now the turn's rule.
- **Left out**: a DM that meets the journal down is lost (the hook's
  `seat_want` fails; no retry unit like `no1-send`'s). The orders typed to
  engineers still begin `[No.1]` with no header line before them: a
  report's room comes from the turn, not from the text.
- **Tests**: test_rooms.py's `Turns` (9): a No.1 order's report from a
  project room and from main, the captain's 1:1 turn after a No.1 order
  (nothing to Number One, the question flag kept), `to:: no1` from a 1:1
  turn, delivery setting the turn and a `[job]` keeping it, a DM filed,
  slipped, delivered and answered back, one from a 1:1 turn in the
  addressee's room, the cap (and another addressee, the captain's word,
  the hour), the brief.

## 17. Slice 2 as built

The Rooms page, its doors and voice orders; the rows the truth for the
rooms' labels.

- **The page** (`openRooms` in index.html, the route `rooms` and
  `rooms/<id>`, a room a step over the list as a chat thread is over the
  chats). It reads no rows of its own on opening: every `crew_msg` and
  `crew_room` row is already in `st.all` (the load and the mirror bring
  every kind), and `rmIndex` groups them by the title's `#room`
  (`ROOM_TITLE`, rooms.py's `TITLE_RE` copied; test_rooms.py runs it under
  node against it). While it is up, `rmPoll` asks every 3 s for
  `kind=crew_msg&min_id=<newest held + 1>` and the `crew_room` rows, and
  for the open room's waiting rows `kind=crew_msg&done=0` (one gone from it
  is read by id: delivered or cancelled), and lands them in `st.all` as the
  sync does (`rmLand`). A row's `at::` is its time, `src::` and
  `misrouted::` are not drawn (the latter marks the bubble); a long one is
  folded at 12 lines or 900 characters, only its head drawn until More; the
  newest 60 rows are drawn, Earlier adds 60.
- **Sending** goes through the say route with the room: `thread` is the
  project room's id, on Number One's route or (the To chip) an engineer's.
  engineer.py's `cmd_say` now takes a room for an engineer too: the row is
  filed in that project room `to::` them, and the turn it starts is that
  room's (`say_turn` takes the room; a queued say marks its slip with it,
  read by `slip_turn` at delivery), so `turn_route` types their report to
  Number One there (4.1, row 2). What is typed to them has no header line.
  Their own room as the room is a plain say; `main` or an unknown room a
  404.
- **A main room's timeline** (`rmIndex`): its own `#X` rows, and every row
  filed in another main room whose sender or addressee is X (section 16's
  rule): a DM is in both engineers' rooms; Number One's order given from
  main, filed in the engineer's room, is in Number One's too.
- **The labels**: New, Rename, Close and Reopen (`new` on a closed id) go
  through `POST /engineer/number-one/thread`, as the chips did. engineer.py's
  `threads_from_rows` brings Number One's `threads` into step with the
  `crew_room` rows on every thread op and on a say into an unknown room:
  the rows are the truth, the state the poll's cache. A new room's id that
  is a crew member's name is refused (section 1).
- **Unread**: `lcars.rooms.seen` (room -> the newest row id seen) in
  localStorage; a room first met is taken as read; the captain's own rows
  never make one unread.
- **The doors**: the Chats list's Rooms row (under the queue's), a palette
  row, the ⋯ sheet of every thread (so the deck's talk sheet has it, and
  its ‹ goes back to the thread: `lcarsDeckChat`), Number One's chips' `+`
  (New room). A room order said in the deck opens the console sheet at it
  (`lcarsDeckConsoleUp`). **Q6: no key** - KEYS has no free letter that
  says rooms (r and R are taken, as in the deck).
- **Voice** (`VCMDS`): rooms, unread rooms (my rooms), open/go to/show the
  <name> room, new room <name>, in the <name> room [tell <engineer>]
  <message>, tell <engineer> <message>, rename the <name> room to <new>,
  close/reopen the <name> room. 10.6 is a `when` on a VCMDS order (vMatch
  skips a phrase whose `when` says no): a room order stands only when
  `rmSaid` finds a crew room by the name, so "go to the ready room" falls
  through to the deck's "go to {*}"; vTry now keeps each `{*}`'s words
  (`arg.parts`) for the two-hole phrases.
- **rooms-migrate** refuses `--apply` once live rows exist (no `src::`)
  unless `--until <utc>` names the cutoff; the dry run says `live_rows`.
- **Tests**: the behaviour suite (the list, a room from rows, the To chip,
  the optimistic bubble and Retry, unread, New/Rename/Close, the orders),
  `test/rooms_ui.py` (new: the stand-in engineer.py writes the rows),
  keyboard.py (New room's fields, the box, Rename), buttons.py
  (`rooms_view`: the doors, ‹, Escape, Back, every button), deckvoice.py
  (10.6 and the console sheet), perf.py's `rooms-room` (2000 rows).

## 18. Slice 4 as built

Number One's verbs and brief, and section 8's renames, on top of slice 2.

- **Number One's verbs** (section 7): `engineer.py room number-one <op>`
  (`cmd_room`), which `no1.py room` calls, as its crew verbs do:
  - `list [--closed]`: main, then the project rooms, each with its id,
    name, count and last message (from, time, first line) from the
    `crew_msg` rows; a room's `crew_room` row's name and state win over
    the state's list;
  - `new <id> [name]`, `rename <id> <name>`, `close <id>`: `room_op`, the
    one rule both `room` and `thread` use: the state's list and the
    `crew_room` row (`by:: no1`, or `captain` from the console's route), a
    closed one of that id reopened by `new`; `new` refuses a crew member's
    name (an engineer's state, `number-one`, `NOT_NAMES`: section 1's one
    namespace - `thread new` refuses it too now), `close` refuses main and
    a crew member's own room;
  - `log <id> [n]`: a room's latest n (20, at most 200) messages, the
    header off, each clipped at 600 characters, with its id, time (a
    migrated row's `at::`), from, to and delivered; a crew member's own
    room is a room here;
  - `show <msg id>`: one `crew_msg` row whole (`seat.msg_get`, `GET
    /entries/<id>`), another kind or none a 4.
  The rows are read by kind in pages of 500 and filtered by the title's
  `#<room>` (12, Q1).
- **`no1.py thread`** stays this release: `list`, `new`, `rename`, `close`
  as before (the console's chips still use `thread-req`), each answer
  carrying `use`, the room verb to use instead.
- **`brief_no1`**: section 5.2's paragraph in place of "Rooms (threads
  until now)", saying `[thread <id>]` is read and never written, that a
  captain's 1:1 turn reaches Number One only by `to:: no1` (slice 3), and
  that an ask or a deploy is the turn's room's. no1.py's usage names the
  room verbs.
- **The state's `threads` list is not dropped**: it is the poll's cache
  of the `crew_room` rows (slice 2's `threads_from_rows`), never the
  truth, in place of the design's "dropped" (section 14, item 4):
  `room_op` and every `room` verb bring it into step with the rows first,
  and `room_op` writes the row beside it.
- **The renames of section 8**, each old name read beside the new for a
  release and only the new written:
  - the engineer's `no1_thread` → `room` (`eng_room`; `thread_take`
    drops the old key), deploy.json's `by_thread` → `by_room`
    (`deploy_room`), `LCARS_THREAD_BY` → `LCARS_ROOM_BY`, Number One's
    `refresh: {thread}` → `{room}` (refresh-go reads either);
  - `notify_no1(about, text, room=)`, `no1_send(text, room=)`;
    `thread_marks`, `thread_split`, `thread_at`, `thread_now` →
    `room_marks`, `room_split`, `room_at`, `room_now`, no aliases (no
    script outside engineer.py called them);
  - `thread_tagged` → `rooms.typed_for_no1`, not `rooms.headed`: what is
    typed to Number One leaves main's untagged (its brief: a message with
    no header is main's), which `headed` would mark `room:: main`;
  - the poll: its events carry `room` (not `th`) and Number One's answer
    `rooms` (not `threads`). The page reads both at one place,
    `engRoomNames` in `engApi`, which copies the new names onto the old
    ones it uses (the behaviour suite checks both forms).
  Kept as they are: the CLI flags (`say --thread`, `no1-send --thread`,
  `--room` beside it), the poll route's `&thread=` query, the inbox's
  `#<room>` mark and `seat.inbox_add(thread=)`, `thread-req` and the
  console's chips' `threads` answers (`cmd_thread`), and `thread_take`,
  `thread_ask`, `thread_find`, `threads_of`: not in section 8's list, and
  the first three are contracts other scripts and the C route hold.
- **Tests**: test_rooms.py's `Verbs` (5): new, rename, close, reopen and
  list; every refusal; list, log and show over rows (counts, the last,
  clipping, a migrated time, whole); `thread` doing the same; no1.py's
  `room` and the alias's `use`. test_no1_threads.py's brief check reads
  the new paragraph (its stand-in journal answers `GET /entries/<id>`);
  test_brief.py checks 5.2's words. The renames: test_rooms.py's
  `CarryOver` (the old names read, the new written, a refresh under
  either), test_no1_threads.py and test_events.py on the new names, the
  behaviour suite's `engRoomNames` checks.

## 19. Archive (the captain's order, 2026-10-23)

"Let me dismiss or archive a room from the UI, to reduce clutter, but be
able to bring it back if needed."

- **What it is**: the captain's own view of the list, nothing else. Close
  stays the room's state for everyone (the crew and Number One's CLI see
  it, a project room's only); Archive is any room's, a project room or a
  crew member's own, and changes nothing for routing, delivery or the
  crew. Both may hold at once (an archived room is under Archived, closed
  or not).
- **Where the mark lives**: one `settings` entry titled `rooms`, content
  `{"v":1,"archived":["deck","kim"]}` (other keys kept), the lowest id
  winning, as the views entry (`VIEWS_KIND`) does. Why this and not a mark
  on the room's row: a crew member's room has no row (it is the rows
  filed under their name, section 16), and the `crew_room` rows are the
  crew's, written through Number One's route, which the captain's own view
  should not move. A settings entry is the owner's, syncs, restores and is
  editable by hand like any row, and needs no schema or route. It is held
  in `st.all` like every row (the load brings it); `rmPoll` asks for the
  `settings` rows once each time the page opens, so another device's
  Archive is there when the page is. A save reads the entry afresh, makes
  its one change and PUTs it (no compare-and-swap: two devices in the same
  second lose one of the two at worst); the saves go one at a time.
- **The page**: Archive in the room's ⋯ (a crew room's ⋯ has it alone;
  Unarchive once archived) and in a list row's actions, shown by a long
  press (550 ms, or a right click; a desk's hover shows them too).
  Archived rooms leave the list for an "Archived (n)" fold below Closed,
  each row with Restore; a new message keeps the room archived, its dot on
  the row and on the fold's summary; the Chats list's Rooms row does not
  count it. A tap changes the list at once (`rm.arch`, a room's state until
  its save lands); a failed save puts it back and says so in a toast. The
  unread rule (`lcars.rooms.seen`) is unchanged.
- **Voice**: "archive the <name> room", "restore / unarchive the <name>
  room" (the `when` of the other room orders: a crew room by that name),
  "archived rooms" (the list with the fold open).
- **Tests**: the behaviour suite (Archive from a row and the ⋯, the fold,
  Restore, a message into an archived room, a failed save, the mark read
  back from the journal, the orders), buttons.py's `rooms_view` (the ⋯'s
  Archive, Restore, a long press), rooms_ui.py's step 5b (the entry on a
  scratch server).

## 20. The chats' shell, one level down (the captain's order, 2026-10-23)

"It should look like the main chat, just the rooms on the left and
conversations on the right, most of the screen. So it is like switching
one directory down and replacing the left sidebar, but the UI stays the
same." The Rooms page is the chats' dialog with the rooms in it: one
`.dlg.chshell` (the class the chats' two-pane layout now hangs on, the
chats dialog `chats chshell`, the rooms `rmview chshell`) holding a list
pane (`.chpane.chlistp`, 340px with its border on a desk: the rooms'
header with ‹ and +, New room's fields, `#rmlist`) and a thread pane
(`.chpane.chth`: the room's `.chhdr` with ‹, its `.chav`, name, status
and ⋯, the sheet, the `.chlog` of bubbles, the To picker and the
`.chcomp` box with the To chip). `th-open` on the dialog says a room is
open, as it says a thread is: on a phone one pane at a time, the chats'
own CSS; at 900px and wider both, the right pane "pick a room" until one
is. A row's tap (`rmShow`) redraws the right pane and repaints the list,
whose open room's row is marked `.on` as the chats mark theirs; the list
is drawn only when its HTML changed, so a poll costs a room nothing. The
room's ‹ on a desk is up a level, to the chats (`rmUp`, the list's ‹),
on a phone back to the list (`rmBack`); Escape and Back stay history
steps (a room, the list, out), and a leave from a room by the steps that
led in is taken back off the stack as the chats' is (writeState). In the
deck's talk sheet (`solo`) the page stays one pane at any width.
Shared: the dialog, both panes and their CSS, the header's markup,
`chatRowBtn`, the sections, the dots, the log's bubble classes, the
box. Not shared: the thread's mount (`chatsMount`): it is a conversation
object's (a transcript poll, the model chip, voice, the context card),
where a room is rows of `crew_msg`; so the room keeps `rmLogPaint` and
its own handlers, drawn in the mount's classes. Files are shared since
section 22.

## 21. An order for a project's room (the captain's order, 2026-10-24)

"A report should go to the room for that project or feature; if Number
One makes a room before ordering an engineer, the order goes as if from
that room; if a room exists but he chats with Number One 1:1 about the
feature, that room is used when messaging engineers." Before, an order
was the room of Number One's turn (4.2) and nothing else. Now
`no1.py crew say <name> [--fresh] --room <id> "<order>"` and
`no1.py crew deploy <name> --room <id>` name it. no1.py checks the room
(`room_check`: main or an open project room; a closed one, an unknown
one and a crew member's name refused with a line naming `room list` or
`room new`, exit 4) and hands it to engineer.py as `LCARS_ROOM_AT`,
which `room_given` reads where the turn's room was read: `thread_take`
(the engineer's `room`, so the order's row, its turn, a queued slip's
turn and the report all follow, as from a turn started there) and
`detach` (the deploy's `by_room`, so `[deploy finished]`/`[deploy
failed]` go there). Number One's own turn, its asks and its refreshes
keep their room. Tests: test_no1.py's `CrewRoom` (the flag, the
refusals), test_rooms.py's `Turns` (typed and queued, `room_check`) and
`CarryOver` (the deploy).

## 22. Files in a room (the captain's order, 2026-10-24)

A room's box takes files as the chat's does (architect.md 1.3): its +
(`#rmattach`, the picker `#rmpick` with no `accept`, so an iPhone offers
the photo library, the camera and Files), a paste into the box, a drop
on the pane. The chat's pieces do the work, keyed by the room: the chips
(`chatFilesTake` into `rm.att`, room id -> files, keyed `rm:<room>` so
`chatFileTouch` repaints the room; `chatChipsHtml`), the upload
(`chatFileUp`, `chatMediaSend` to `POST /chat/media`, its bar at once),
waking when the link is back (`chatFilesWake`), the wait
(`chatFilesWait`) and `chatAttachments`. Send puts the bubble up at once
with its pictures and "sending… uploading 1 of 2", waits for the
uploads, then says with `attachments`: engineer.py's `say --json` writes
an "Attached file: <root>/media/chat/… (<name>, <mime>, <size>) - Read
that path; … fetch <URL>" line per file after the words, into the
session typed to (Number One, or the engineer the To chip names) and
into the `crew_msg` row alike. A row's bubble is drawn from those lines
(`chatFilesFrom`): the pictures or file tiles above the words
(`chatFilesHtml`), the lines hidden, a tap on a picture the lightbox. A
file that fails marks the bubble "not sent" with Retry, which uploads it
again. "drop the attachments" clears a room's chips when a room is open.
