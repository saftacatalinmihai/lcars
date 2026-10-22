# Live narration in the chats' voice — design

Status: slices 1 to 5 built (0.291.0, 0.291.9, 0.291.10, 0.292.0, 0.292.1); slice 6 is voice-quick-answer.md; design 0.289.4. Thread `realtime-chat-with-c`, the
captain's go of 2026-10-21. Torres builds slice 1 (the `[spoken]` mark and
the brief's rule); this covers what comes after it.

The captain wants a voice conversation with Number One and the crew that
feels live: hear something within a few seconds of speaking, and keep
hearing what they are doing while they look things up. Today the voice is
quiet for most of a working turn.

## 1. What happens today (read from the code)

There are two speaking paths, and they fall silent for different reasons.

**Engineers and Number One** (`chatEngSpeak`, fed by `engPoll`). The page
polls `GET /engineer/<name>?off=N` every 1.5 s (0.75 s in a conversation,
`ENG_POLL_CONV_MS`). The server reads the Claude Code transcript a whole
line at a time (`poll_forward`), and `events_of` turns each assistant
`text` block into one `{r: "them", t}` event. `chatEngSpeak` cuts each one
into sentences and adds them to one run, reopened (`sayReopen`) while it
still speaks.

So a narration line *is* spoken already, once its block is in the
transcript. Measured on the live transcripts:

- Claude Code writes a text block as its own line about a second before
  the `tool_use` that follows it (Number One, 20:52:05.384 text, 20:52:06.258
  tool). A narration line reaches the page within one poll.
- But of 296 recent turns that called a tool (40 sessions), only 119 (40%)
  wrote any text before their first tool. The other 60% go from thinking
  straight to tools, and the captain hears nothing until the report.
- A block is said only once it is whole: a 1000-character answer is heard
  only after all of it is written.

Most of today's silence is the model, not the page. Torres's slice 1 (a
short spoken answer before any tool) fixes that. The page's gaps are
smaller, and they are covered below: stale lines after a sleep, the
microphone flapping on a phone between lines, a stop that stays on too
long, and nothing shown while a tool runs.

**The computer, crew roles and the navigator** (`chatSayFeed`, a streamed
`/chat`). Here the page cuts sentences as the stream writes them
(`sayCut`). It says only the text after the last tool call, *on purpose*:
narration on the way to a tool is never said, and a tool call stops what
was queued and starts a fresh run. That path does stay silent through
every lookup.

**The deck's talk sheet** is `index.html` in the deck's frame (`chatSolo`),
with the deck's sound switch as Voice. Both paths are the same code there.
The deck adds only the lips (`chatDeckLips`). Nothing in this design needs
deck.html beyond that hook.

## 2. What the captain hears

One rule: **everything they write to the captain is said as it arrives,
once, in order, and nothing is said that is out of date.** Tool calls,
thinking and code are never said.

- **Engineers / Number One.** Each `them` line is said when its poll
  brings it (as now). The whole turn is one run: the run is held open
  through the tool gaps (§3.3), so lines follow each other and the deck's
  mouth and the speaking mark do not flicker.
- **Computer / roles / navigator.** Narration before a tool is said. At a
  tool part, the unfinished tail of the text before it (the sentence
  `sayCut` holds back, waiting for more words) is flushed into the run.
  The run is *not* restarted: the line already playing finishes, and the
  answer after the tool follows it. Code and tables are dropped by
  `chatSayText` as now.
- **Answers only** (the setting in §6) keeps today's behaviour for the
  streamed path: only the text after the last tool is said.

### 2.1 Never twice

- *Engineers.* `e.off` advances with every poll, so an event is handed to
  `chatEngSpeak` once. Two things can still repeat a line, and both are
  closed with a key per line. The key is `session + byte offset of the
  line + index in it`; the server adds it to each event as `k`, since it
  knows the offset. A `Set` per engineer (`e.said`, the last 200 keys)
  guards against:
  - a `/clear` or `?past` reread, which already skips `first` pages but
    not a session switch caught mid-poll;
  - two mounts of one thread (the dock and the sheet): `engPoll` is per
    thread, but the guard costs nothing.
- *Streamed.* `v.said` is the offset into the text after the last tool.
  With narration said, it becomes an offset into the *whole* spoken text
  (every text part, tools dropped), so a new tool no longer resets it to 0.
  Today the reset to 0 is safe only because the old run is thrown away.
- *Two pages.* The console in one tab and the deck in another both
  polling: only a page with the thread on screen and not
  `document.hidden` speaks (as now; hidden pages do not poll). The same
  thread open and visible on two devices speaks on both. That is
  accepted and noted, not solved.

### 2.2 Nothing stale

- *A stop is final for the turn.* After `sayStop` (the mark, Esc, Stop,
  "stop", Hold to talk pressed, words in barge mode), `sayLive` drops every
  queued line and the fetch in flight is aborted, as now. The engineer's
  `e.hush` keeps the rest of that turn quiet. It lifts only on the
  captain's next message, as now. The streamed path already stays
  stopped (`sayLive(v.run)` false).
- *A line from a page that slept.* A phone locked mid-turn, or a hidden
  tab, stops polling. When it comes back, the next poll brings everything
  written meanwhile, and today all of it is said. Each event gets `at` (the
  transcript line's timestamp), and the poll's answer gets `now` (the
  server's clock, so the phone's clock does not matter). A line with
  `now - at > SAY_STALE_S` (20 s) is shown but not said. If the lines
  skipped include the turn's last text and the turn has ended, that one
  line is said, with "Earlier:" in front of it: the report is what the
  captain came back for.
- *A turn over.* Lines that land after the run has finished and the turn
  is `idle` are still said (they are the report). A run is never reopened
  for a message from before the captain's latest one.

## 3. With the controls

### 3.1 Hush, stop, the speaking mark

No change in meaning: a stop silences the rest of the turn, and the
captain's next words lift it. One addition: a stopped turn's thread shows a
small **"voice paused — tap to hear"** line under the last bubble. A tap
lifts the hush and says the *next* line that comes, not the backlog. With
a turn stopped by mistake, the voice is back in one tap, with nothing
stale.

### 3.2 Barge-in (`convBarge`) and mute

- *barge*: as now. Words (not `SpeechStarted`) stop the run. The
  utterance is sent and becomes the next `me` event, which lifts the hush
  once the engineer takes it.
  - Narration makes barging more frequent: there is more voice to talk
    over. That is the point.
  - Echo-cancel leaks that `convWords` counts as words would now cut
    narration more often. Slice 3 measures it with `qa_chat.py` on a phone
    before anything changes.
- *mute*: nothing is sent while a line plays (as now). Between lines (a
  tool gap) the microphone is live again, so the captain can speak in the
  gaps. `convMuted` already follows `convSpeaking(true)`, which is false
  in a gap.

### 3.3 Conversation mode on a phone (speaker output)

With the speaker chosen, the capture is let go for each run (`convSay`) and
taken back `V_HOLD_SETTLE` after it ends. Narration in short lines with
tool gaps would flap the iPhone's audio session at every line:
`getUserMedia`, a route switch, and the first words of the next line lost
to `sayQuiet`. So:

- An engineer's run **lingers** while the engineer is `working`. It stays
  open (`sayReopen` succeeds) and the capture stays dropped for
  `SAY_LINGER_MS` (4 s) after its last line. Most narration comes faster
  than that.
- A gap longer than that ends the run, and the microphone comes back,
  marked "listening". The captain can talk during a long lookup.
- On the desktop and with the earpiece the microphone never drops, so
  there is nothing to tune.

### 3.4 Hold to talk

A press stops the voice, as now (the captain is about to speak). It sets
the hush, and the release sends the words, which lift it. A press with no
words sent (a tap, released at once) lifts the hush again: it was a fumble,
not "be quiet".

### 3.5 Voice off, leaving the thread, the deck's sound off

As now (`chatVoiceSet`, `chatVoiceLeave`, `sayOn`): everything stops, and
nothing is said later. Coming back to the thread does not say the lines
missed. The stale rule would refuse most of them anyway.

## 4. What shows on screen (immediate feedback)

The captain's standing rule: something visible in the same frame. Here the
screen must also say *what the silence means*.

| Moment | At once | Then |
|---|---|---|
| A line starts being fetched | talk row mark "voice…" (as now) | "speaking" |
| A line is spoken | its bubble gets a lit left bar (`.saying`), the deck's lips move (as now) | the bar moves to the next line's bubble, gone at the end |
| A tool runs (engineer `working`, no line playing) | the status line under the thread shows the tool in plain words, from `tool_line`: "reading index.html…", "searching for sayCut…", "running the tests…", with the working pulse | the next line replaces it |
| A tool runs in a conversation, and the voice has been silent 4 s | the same, plus one soft earcon (the LCARS "working" chirp, low, 150 ms), at most every 10 s | — |
| Stop / barge | the mark goes at once, the bar off the bubble; "voice paused — tap to hear" | — |
| Lines skipped as stale | shown as bubbles, with a quiet "not read aloud (earlier)" on the first | — |

- The bubble bar is the cheap, legible link between voice and text on a
  phone: the captain glancing down sees which line is being read. No
  word-level karaoke: PCM from `/say` has no word timings, and the frame
  budget would not like it.
- The tool line already exists in the transcript as `{r: "tool"}` events.
  This only words them for a person: a map `Read`→"reading",
  `Grep`/`mcp__fff__*`→"searching for", `Bash`→its description,
  `Edit`/`Write`→"editing".
- The earcon is for a phone in a pocket (conversation mode, speaker): with
  no voice and no screen, it says "still working, not lost". It never
  plays outside a conversation.

## 5. A voice order

- **"answers only" / "say everything"**: the setting in §6, in `VCMDS` and
  the palette ("chat voice: answers only"), calling `chatNarrateSet`.
- **"go on" / "keep talking"**: lifts the hush (§3.1), the same function
  as the tap. Checked against `vMatch` for collisions with "go to" and
  "keep": the longest phrase wins.
- "stop" / "quiet" stay as they are.

## 6. A setting

`lcars.chat.narrate`: `"all"` (the default once slice 4 lands) or
`"answers"` (only the text after the last tool on the streamed path, and
for engineers only lines when the turn is `idle`, the report). It is set
per device, in Config's chat section and the deck's Settings beside the
voice output, and is said by the orders above. A phone used on a walk wants
all; a desk where the captain reads along may want answers only.

## 7. Tests

- **`test/speech.py`** (the speech queue in a bare page): a run reopened
  across a 3 s gap with `SAY_LINGER_MS` keeps one `onState` "playing" (no
  flicker); `sayStop` mid-line aborts the fetch in flight and no queued
  line plays; a line added after a stop plays nothing.
- **QuickJS behaviour suite** (the page and a fake API):
  - `chatEngSpeak` with events `them, tool, them, tool, them`: three lines
    queued in order, one run.
  - The same events polled twice (same `k`): said once.
  - `at` 30 s before `now`: shown, not said; the turn's last line said
    with "Earlier:".
  - A stop, then more lines: none said; "go on": the next one said, the
    backlog not.
  - `chatSayFeed` with parts `text, tool, text`: the narration's last
    sentence flushed at the tool, the answer after it, `v.said` not reset.
  - `"answers"`: the old behaviour on both paths.
  - `.saying` on the right bubble.
- **`scripts/test_events.py`**: `events_of` gives `at` and `k`; the poll
  answer has `now`.
- **`test/ptt.py`**: conversation mode with the speaker on a faked
  iPhone: two lines 2 s apart drop the capture once and take it back
  once; a 6 s gap takes it back between them. Mute: a word in the gap is
  sent.
- **`test/deckvoice.py`**, if the deck gets the orders (§5) through its
  frame: "answers only" said on the deck sets it.
- **Live check** (`qa_chat.py`, on the phone, by the captain once): a
  real conversation with Number One; does barge cut narration by itself
  (echo)? That decides slice 3's tuning.

## 8. Slices, smallest first

1. *(Torres, under way)* `[spoken]` on dictated messages; the brief's
   rule: a short spoken answer before any tool. Fixes the 60% of turns
   that are silent today.
2. **Nothing stale, nothing twice** (engineers): `at`, `k` and `now` from
   engineer.py; `e.said`; the stale rule and "Earlier:"; tests. Small:
   about 40 lines of page and 10 of Python. A patch bump.
3. **The run lingers, and the phone does not flap**: `SAY_LINGER_MS`,
   `convSay` held across gaps, Hold to talk's fumble lifting the hush;
   `ptt.py` and `speech.py`.
4. **The streamed path says its narration**: `chatSayFeed` flushes at a
   tool and keeps its run; the setting and its two orders (§5, §6). A
   minor bump: the computer and the crew roles start talking through
   their lookups.
5. **The screen while it speaks and works**: `.saying` on the bubble, the
   tool status in plain words, "voice paused — tap to hear", and the
   conversation's earcon. `buttons.py` and `keyboard.py` at phone size;
   perf for the chat scenario (the bar repaints at most once a line).
6. **The quick-answer path** (§9): voice-quick-answer.md.

## 9. Later: the quick-answer path

The captain said yes on 2026-10-22. Its design pass is
[voice-quick-answer.md](voice-quick-answer.md), in three tiers:

1. the page, from what it holds, in under 100 ms;
2. the computer: a tool-less Haiku call, `POST /quick`, about 4 s and
   $0.002 measured, answering in one sentence or PASS;
3. Number One.

Only for Number One's thread, in conversation mode by default. The
computer speaks in its own voice, on a COMPUTER row, and Number One is
told what it said.

## 10. Not in this design

- Streaming a Claude Code text block before it is whole (the transcript
  writes whole blocks). That would take the agent SDK's stream, a server
  change of its own. The gain is a few seconds on long blocks only, now
  that the turn's first line comes before any tool.
- Word-level highlighting. `/say` gives no word timings.
