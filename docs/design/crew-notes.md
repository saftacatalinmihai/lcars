# Crew notes: `@yeoman …` inside an entry — design

Status: **built**. §1, §2, §4 and §5 read-only in 0.195.0 (2026-10-15,
Chief Reyes; ARCHITECTURE.md "Crew notes"); §3, the write path, in
0.196.0 to the captain's narrower rule (create and append only). As built, beside this page: the note hash is FNV-1a,
not a sha (the page computes it without crypto.subtle, absent on plain
http); a role answers with a note brief of its own, not its scheduled
orders; ./notes is a page of its own, reached from a Crew notes row in the
Chats list's Reports (the Reports view became the Chats list in 0.162).

The captain writes, in any entry of his, a line such as
`@yeoman make a sleep entry from 23:10 to 07:05 last night`. That role
answers it as a conversation, queued like every crew run, with the entry as
context and the journal to search; it creates or edits his entries only
when the note asks. The answer shows where he left the note, and he can
reply. Built on: the crew runner (`scripts/crew.py`, ARCHITECTURE.md
"Scheduled crew roles"), `crew_tool.py`, the linker's hash-checked splice
(`lcars_linker.py apply`), `/events`, the limited logins (`lcars_logins.h`),
and 0.155.0's "talk a role over in the Ask chat".

## 1. The note, and how it is found

- **Syntax.** A line whose first non-blank characters are `@<role>` and a
  space, then the order: `@yeoman log a gym session`. `<role>` is a
  `crew/<role>.md` that opts in with a front-matter key `notes:` (its verbs
  for a note run; §3). So `@yeoman`, `@historian`, `@science`, `@counselor`,
  `@ops`; not `ship`, `qa` (no model), `yeoman-linker`, `historian-monthly`.
  An unknown `@word`, one mid-sentence (an email, "@home"), one inside a
  code fence or a `>` quote: not a note, never touched. The order runs to
  the end of the line; indented lines right under it belong to it.
- **Which entries.** The captain's own kinds only: never `crew_*`, `no1_*`,
  `task_crew`, `task_no1` (a role's answer quoting `@yeoman` must not loop)
  or the frozen imports (`logseq_journal`, `capacities_journal`,
  `noteplan_journal`).
- **Found by `/events`, not a timer.** A small watcher, `crew.py notes
  watch` (a user service, `lcars-crew-notes.service`, Restart=always, idle
  I/O), holds `GET /events` as the crew login (GET is allowed). On each
  `seq` it asks `GET /dump?modified_since=<mark>` and scans only what
  changed; the mark (the newest `last_modified_at_utc` seen) is kept in
  `STATE/notes.mark`, so a restart or a missed `seq` catches up exactly,
  and nothing reads the whole journal. It uses one of the 8 stream slots.
- **Not while he types.** A note is taken once its entry has been quiet
  for 20s (no newer `last_modified`): the editor autosaves mid-sentence,
  and `@yeoman log a gy` must not run. The watcher re-checks when the
  quiet period ends (one timer for the earliest ripe entry, not polling).
- **Once.** A note's identity is (entry id, role, sha of its normalised
  text). A note already in a thread (§2) is never taken again; editing its
  text makes a new note; deleting the line leaves the thread.

## 2. Where the answer goes, and replies — a linked thread

**Recommendation: a thread row, never a splice into his entry.** One entry
of kind `crew_note` per (entry, role): `value_int` = his entry's id, title
`Yeoman · #1234 <his title>`, content the conversation as Markdown turns
(`### Captain · 23:14`, `### Yeoman · 23:15`), each captain turn carrying
its note's sha. It is the crew login's own kind, so the server already
lets the runner write it and nothing else of his.

Why not splice the answer under the note, linker-style: the linker can
splice because it adds four characters at a scanned offset at 23:12 when
he is asleep; an answer is paragraphs, written seconds after he typed, into
the entry most likely open in his editor. The page keeps a dirty row
(deltaSync skips it), so his next autosave would wipe the answer, or the
hash check would refuse it and it would be lost; and crew prose would land
in his search, embeddings and Logseq export as his words. The thread row
has one writer at a time and leaves his text byte-identical.

- **State lives in the thread** (the journal rule): the watcher creates the
  row at once with his note and `status: queued`; the runner sets
  `working`, then appends the answer and `answered` (`done_bool=1`), or
  `failed: <why>` with a Retry. A restart resumes from queued rows: the
  queue is the journal.
- **Replies.** Either in the card (§4), which appends a captain turn to
  the thread and sets `queued`, or a new `@yeoman …` line in the same entry
  (same thread, by entry and role). The runner re-reads the thread just
  before writing and appends to what is there (append-only, so a reply
  landing mid-run is kept and taken next).
- **Context per turn, no session kept.** Each run gets the role's brief,
  his entry (title, kind, dates, text), and the thread so far; crew runs
  stay `--no-session-persistence`, so a thread survives restarts and a
  long one is cut to its last turns plus the first.
- **Queued like the crew, but not in the seat.** A note run is `crew.py
  note <thread id>`: the same `crew.lock`, memory wait and `/health`, one
  at a time. It does not take the engineers' seat (0.226.0; until then
  it queued as `crew:note-<role>`): the captain is waiting on it, a turn
  is seconds of sonnet, and the seat is an engineer's for most of the
  day - a note of 2026-10-16 sat behind one turn for hours. Model and budget from the role's front matter
  (`note_budget`, default $0.30; timeout 300s).

## 3. The write path — create, append, title, end, set, replace, delete and restore (built in 0.196.0; titles 0.205.0; ends 0.227.0; the rest 0.230.0)

**Set, replace, delete and restore, 0.230.0.** The captain's yes
(2026-10-16, through Number One), stage B of the order whose stage A
widened the chat path (below): the notes may change any aspect of an
entry of his. Four verbs, each with `at=` the row's last_modified as read:
`set #id at=… <field>=…` (title, kind, start, end, done, value_int,
value_float, created_at; dates in his local time, "" takes a start or end
off), `replace #id at=… text=…` (the whole new text, `\n` for a new line;
only for an edit he asks of his text, and it may not add an @role line his
text did not have), `delete #id at=…` (soft) and `restore #id at=…`. The
runner reads the row first (the quiet rule, the kind: never `crew_*`,
`no1_*`, the task kinds or the imports, nor a set moving a row into one)
and keeps its old values; the steward then sends a PATCH (`deleted: 0`
for a restore) or a DELETE with `if_modified`, which the server compares
in the UPDATE's own WHERE - 412 when the row moved, 409 a deleted row (a
restore: a live one), 403 on a kind not the captain's or without
`if_modified` (`StewardAllowed`). Five a turn, a question only proposes,
order words now include set, change, edit, fix, delete and restore. Each
is listed under the answer with an Undo (`{op: "set", id, old, new}`,
`{op: "replace", id, old_text, text}`, `{op: "delete"|"restore", id,
kind, title}`): fields or text put back only if still the crew's, a
delete restored, a restore deleted again. Every one is a line in
notes-writes.jsonl. The scheduled runs stay append-only.


**The chat path widened, 2026-10-16 (0.229.0).** The captain's order:
the yeoman may edit any aspect of an entry, look through old entries and
look things up on the internet. The role chat (`crewRoleContext`), which
writes as his own login, now may, on his word in so many words, set any
field of an entry of his (title, kind, start, end, done, the values,
`created_at`), delete and restore it (soft), and replace his text only
when he asks for an edit of it; append stays the way to add, a create is
marked as now, and every change is named `#id`, old and new, so he can
ask for it back. The walls stay: a question only proposes, never the
crew's, Number One's or the imports' kinds, never a secret written out.
The notes' write path was widened the same way in 0.230.0 (above),
behind the steward's gate. A note turn gains reading: any entry of any
date (`list --search`, `--since`/`--until`, already passed through to
lcars-cli by `crew_tool.py`, so no new verb), and WebSearch, a note
turn's only (`note_fm` sets `search`; the scheduled runs never search).

**Ends, 0.227.0.** The captain's word (2026-10-16, through Number One):
the crew may close an open entry of his - a sleep or a drive with a start
and no end. A fourth verb, `end #id at=<last_modified as read>
end=<his local time, YYYY-MM-DD HH:MM>`, applied by the steward through
`POST /entries/<id>/end {end (UTC), if_modified}` (`HandleEndEntry`: the
end and the stamp, nothing else; 412 when the row moved, 409 deleted or
already ended, 400 a bad stamp, no start or an end not after it, 403 on a
kind not the captain's). An end already set is never moved: the runner
refuses it before asking, and the route would 409. Orders: "close", "end"
and "finish" count. Listed `closed #id at <his time>`; the fence line is
`{op: "end", id, old_end: "", end, at}`, and its Undo PUTs the empty end
back as the captain, only if the row still holds the one set. The role
chat may do the same (`lcars-cli set <id> --end`, on a row with no end).
The nightly yeoman stays read-only and has no end shape in its proposals:
it would need its hygiene pass to find open entries first.

**An answer carries the order (0.227.0).** crew_note #7453: "make the
drive entry"; the yeoman asked when and where; his answer, "I left from
home at 9:50 and arrived at work at 11:12", had no order word, so the
create was only proposed. `ordered_by` (crew_notes.py): a plain turn of
his - no order word, no question mark, no refusal - answering a turn of
the role's that asked something (a `?`, or "I need", "tell me", …) takes
the order from his latest earlier turn that was one, looking back through
the thread until a refusal ("no", "stop", "forget it") ends the look. A
question of his is never an order.

**Titles, 0.205.0.** The captain widened the rule the same day: the
yeoman may set an entry's title as well - the title only, never the
body. A third verb, `title #id at=<last_modified as read> text=<the new
title>` (one line, at most 120 characters; a blank one refused), applied
by the steward through `POST /entries/<id>/title {title, if_modified}`
(`HandleTitleEntry`: the title and the stamp, nothing else; 412 when the
row moved, 409 deleted, 403 on a kind not the captain's), under the same
rules as append below: his turn asks for it ("title this", "name this
entry", "rename this to …"), five at most, not while he types. The
answer lists it `titled #id: "old" → "new"`; the fence line is `{op:
"title", id, old_title, title}`, and its Undo PUTs the old title back as
the captain, on a fresh read, only if the title is still the crew's
(else "the title has moved on"). `notes-writes.jsonl` records each with
`old` and `new`. The nightly yeoman stays read-only, and may propose
"title <id> to <title>" for an untitled or badly titled row, which he
can put in a note. What follows is the 0.196.0 rule, title aside.

The captain's rule (2026-10-15, through Number One), narrower than the
first draft: **the crew may only create new entries and append to an
existing one. It never changes, replaces or removes any existing text,
title, kind, dates or done** - no edit verb at all, not even an exact
span. Everything the crew adds is shown as the crew's.

**The agent never writes.** It reads (its `notes:` verbs), and its answer
may end with a block the runner parses and applies:

```
CHANGES
create kind=sleep title="Sleep" start="2026-10-14 23:10" end="2026-10-15 07:05" text="7h55m"
append #4321 at="2026-10-15 20:01:02" text="Plus 20 minutes rowing."
```

- **Two verbs.** `create` (kind, title, text, start, end; times in the
  captain's zone) and `append` (#id, `at` = the row's
  `last_modified_at_utc` as the role read it with `get <id> --json`, or as
  the order gives it for the note's own entry; text). Any other verb
  (edit, replace, delete, set, …), any other key, a `deleted` or an `id`
  on a create, text holding an `@role` line: refused, line by line.
- **The steward login** (`LCARS_STEWARD_USER/PASS`, a third limited login
  in `lcars_logins.h`), used only by the runner, never the agent: `POST
  /entries` of a kind of the captain's (not `crew_*`, `no1_*`,
  `steward_*`, `task_crew*`, `task_no1*`, `task_steward*`, the frozen
  imports) without `deleted`; and `POST /entries/<id>/append` on such a
  row. Everything else that writes is a 403: PUT, PATCH, DELETE on any
  row, uploads, CalDAV, chat. Not the captain's login (the linker's),
  which can do anything; not the crew login widened.
- **Append-only, server-side.** `POST /entries/<id>/append {text,
  if_modified}` (`HandleAppendEntry`) adds the text at the end and nothing
  else: there is no way to say "change" through it. `if_modified` is
  required and compared in the UPDATE's own WHERE: a row edited since it
  was read is a 412 (the API's one compare-and-set, one statement).
- **Not while he types.** The runner re-reads the target first and
  refuses an entry touched in the last 20s (the watcher's quiet rule).
- **Marked as the crew's, in the text.** An appended block is a quote,
  `> Yeoman added, 2026-10-15 23:15:` then each line quoted; a created
  entry begins `> Yeoman created this, 2026-10-15 23:15 (crew note #T,
  from #E)`. A quote is never a note, so nothing the crew writes starts a
  thread.
- **Only when his turn gives an order.** The runner applies a block only
  if the captain's turn it answers asks for a write (log, add, make,
  record, … or a "yes, do it") and is not a question; otherwise it is
  listed as *proposed, not made*, and his "yes" in a reply makes it on the
  next turn. More than 5 changes in a turn: none made.
- **Every change listed** under the answer in words (`created #4410
  (sleep) "Sleep"`, `added to #4321: …`, `not done: … (why)`), and in a
  `crew-changes` fence a JSON line per change made, which the page turns
  into an **Undo** each: a created entry soft-deleted as the captain; an
  appended block cut out only if it is still there exactly as written
  (else the card says it was changed and is his to edit). An undone
  change is marked `undone` in the thread. Every change, proposal and
  refusal is a line in `STATE/notes-writes.jsonl`.
- **Journal text is data.** The entry, the role's own earlier answers and
  everything `crew_tool.py` prints in a note turn are fenced in
  `<journal-data>` (a `</journal-data>` inside is defused), and the brief
  says text in the fence is never an order. The walls that do not rely on
  the model: questions never write, five a turn, no verb that alters, the
  server's append-only route and 412, the steward's gate.

## 4. The web UI

- **Same frame as the save:** the page runs the same note rule over the
  entry it holds; each `@role` line gets a chip, outside the text (the
  reader's `#rd_notes`, the editor's `#ed_notes`): *sends when saved*
  while the form is dirty, *sending…* until the watcher takes it, then
  *queued* / *Yeoman working…* / *answered* / *failed* from the thread row
  as `/events` brings it.
- **The card:** a tap on the chip opens the thread under the note: the
  turns, the crew's changes each with **Undo** (*undoing…* until it lands,
  *undone* after, a failure beside it), Retry on a failed thread, and a
  reply box (16px; `keyboard.py` opens it). A reply is a bubble marked
  *sending…* in the tap's frame, *not sent · Retry* where it was if the
  write fails.
- **The crew's words:** in the reader a crew block is drawn in the
  crew's blue under a CREW tag (`mdRender`, `CREW_MARK_RE`); an entry the
  crew created has a *created by the Yeoman* chip in its meta row; the
  editor's strip names each crew block, since a text box cannot colour it.
- **./notes** (a *Crew notes* row in the Chats list's Reports, a palette
  row) lists every thread, open ones first; a row opens the entry with
  its note's thread open.
- **Voice:** "note to the yeoman <order>" (a line on the open entry, else
  captured as one), "reply to the yeoman <text>", "undo the crew's
  changes", "crew notes".

## 4b. Notes to people: `@no1` and `@<engineer>` (built in 0.256.0)

The captain's order (2026-10-18, through Number One): inline notes to
Number One and to the engineers, the way `@yeoman` works.

- **The names.** `@no1` is Number One. An engineer answers to their slug
  (`@torres-c37`), its stem (`@torres`) and their title's surname with
  punctuation dropped (`@obrien` for O'Brien, `@laforge` for La Forge),
  case-insensitively - for the ten most recently active
  (`engineer.py list`'s `active`; not Number One, not dismissed). Two with
  one name: the more recently active. A crew role keeps its name (`@ops`
  is the ops role). A dismissed engineer's names, where no one on duty has
  them, are known too, as off duty. `engineer.py note-names` is the list
  (from the state files, never herdr); the watcher reads it each minute
  (`NAMES_TTL`) and keeps it in one `crew_note_names` row, which is the
  page's copy (chips, card, `@` popup, voice). Any other `@word` is not a
  note, as before.
- **Same rule, same thread.** Everything in §1 holds (first word, not in a
  fence or a quote, the captain's kinds, 20s quiet, once per hash), and a
  `crew_note` thread per (entry, alias), titled `<their title> (@alias) ·
  #<id> <his title>` (the alias in the title, since `@jake` and `@sisko`
  are one engineer and the page keys threads by it). The header adds
  `to: <engineer>` and `sent: <n>`, the captain's turns typed to them.
- **The order is typed, not run.** The watcher's worker types the turns
  not yet sent, as `[captain] A note to you, written in the captain's journal entry
  #E "<title>" (crew note #T): <words>` ("More in a note to you" for a
  reply), with a line saying the turn's last message is the answer: to
  Number One through its inbox (`engineer.py no1-send`: a `crew_inbox`
  entry from the captain, delivered by the flusher, which wakes it unless
  dismissed), to an engineer as the captain's word through the seat
  (`engineer.py say <name>`: typed if seated, else queued in their inbox
  and first in line; never `--fresh`). `sent` moves first and back on a
  failure, so a restart never types one twice; a question on their screen
  is tried again in a minute; any other failure is `failed: not
  delivered…` with Retry. Status `queued` while it waits in an inbox.
- **The answer is their turn's last words**, however long the turn: no
  lock or runner is held. When engineer.py types the order into their
  session (`say`, the seat's delivery, Number One's flusher), `note_typed`
  records the thread in their state with the transcript's size, and sets
  it `working`. Their Stop hook spawns `engineer.py note-answer <name>
  <last_assistant_message>`, which appends it to each recorded thread
  whose `(crew note #T)` mark is in a user line of the transcript past
  that size (a turn that ended before reading it waits for the next), as
  their turn after the last captain turn sent, then `answered` (or
  `queued` if he replied meanwhile, which is sent next).
- **Off duty.** A dismissed engineer's note is answered in place: the
  thread says they are off duty and who is on (`Chief Miles O'Brien
  (@obrien, @obrien-c33)`); nothing is started, and `say` - which would
  recall them - is never called.
- **Restart.** The watcher is `lcars-crew-notes.service`, which a deploy
  does not restart: until it is restarted, it knows no `@no1` or engineer
  names and publishes none, and the page shows no chips for them.

## 5. Tests

- `scripts/test_crew_notes.py`, notes to people (0.256.0): the table with
  `@no1`, `@Torres`, a slug, an unknown name, an email and `@home`; the
  names row published once and edited when the list changes; both
  dispatches against a stand-in engineer.py (`no1-send`, `say <name>`,
  never `--fresh`; once, not after a restart; a reply sent as more); a
  question on screen and a failure; a dismissed name answered in place;
  `note_typed` to working, the turn's end to answered only once the mark
  is in the transcript, a reply meanwhile kept after it; the Stop hook's
  spawn; the names rule (`note_aliases`, `note_names`: ten, the more recent
  wins, the dismissed off); `--real`: the crew login writes the names row
  and a person's thread through to answered.
- `scripts/test_crew_notes.py` (stand-in server and clock, as test_crew;
  `--real` against a scratch build): the note rule's table, run in node on
  the page's copy too; the kinds never read; the watcher's first start,
  quiet period, mark across a restart, once per hash; threads queued to
  answered, a reply mid-turn kept, failed and Retry, the lock, the
  fences; CHANGES lines allowed and refused (every altering verb), the
  block cut from the answer, which turns ask for writes, the marks; whole
  turns: create and append made, marked and listed with their undo
  record, by the steward and nothing else; a question, a planted order,
  six changes, a stale, busy, crew or frozen target, no steward login -
  each writing nothing.
- `test/logins.py`: the steward's table - creates only the captain's
  kinds, never naming `deleted`; append at the end only, 412 when the row
  moved, 409 deleted, 403 on crew and frozen rows, a content or title in
  its body ignored; every PUT, PATCH, DELETE, upload and chat refused, the
  row byte for byte as it was.
- QuickJS suite: chips through every state, the card, reply and its
  failure, Retry, the voice orders and their collisions, ./notes and the
  Chats row; the crew's blocks drawn as the crew's, the created-by chip,
  the editor strip, Undo of an append and of a create, an edited block
  left alone, the spoken undo. `keyboard.py`: the reply box.
