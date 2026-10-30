# Shorts: thirty scripts, one per feature

The scripts of the short demo videos, one feature each, for the social plan
(Number One's "Short-form demo content: a plan, one short per feature",
28 October 2026, in Reports; its sections 1, 3 and 6 are this note's
source). Each short is filmed by `video/explainer/film_console.py` (the
console) or `film.py` (the deck), framed by the Short composition, and
rendered from a props file in `video/explainer/shorts/NN.json`. Nothing
here is posted; posting is the captain's, by hand.

## 1. The rules

**The shape.** 15 to 28 seconds, one feature, one idea. 9:16, 1080x1920,
30 fps; the console at a phone's size (390x844 at 3x) in the middle, the
LCARS elbow and a title bar above, a caption plate below. Five beats:

| Beat | Time | What |
|---|---|---|
| Setup | 0-3 s | two plain sentences on screen and spoken: the app, then the feature |
| Hook | 3-5 s | one sentence on screen and spoken: what the feature answers |
| Show | 5 s to the punch | the real console doing it, taps marked, text typed live |
| Punch | 3 s | one line on screen and spoken |
| Card | 2 s | "LCARS. Open source. One binary." and the demo link; "on your own server" when the feature is off in the demo; the synthetic-voice notice |

**Sound.** Captions burned in, always: most feeds play muted. The ship's
voice (Deepgram Aura-2 athena, the explainer's) reads the setup, the hook
and the punch. The licensed music bed, low, or none where the platform adds its own.

**Screens.** The made-up journal only, never the captain's: shots.py's
(`lcars-ui/test/shots.py`), which `film_console.py` loads into its scratch
server - the "Log for …" days, "Renew passport", the "Sleep" rows with
the hours slept, "German course", "HTTP arena sizing notes", the old
entries ("The arena, as first sized", "Why the journal is one file"),
"Log for today" and its crew note, the Secret "Doctor, Thursday", the
course "The Amalfi coast". The crew shorts need the made-up crew of
`site/manual/shots_crew.py` (Chief Reyes, Lt. Okafor, the calendar room,
Number One's question) put in the page as the manual's pictures do. The
deck short uses `deck.html?demo`. Each short names the rows it uses.

**The setup.** Before the hook, so a viewer in a feed knows what app and
what feature is on screen. Its first sentence is the same in all thirty, so
a feed teaches the name: "LCARS is my journal, on my own server." The
second names the feature ("This is quick capture."), with a few words on
what it is where the name alone does not say. It never says what the hook
or the punch says.

**The lines.** The blog's voice: plain, first person, a little dry. The
punch is a fact, not a claim ("Encrypted in the browser", never "totally
private"). No emoji, no arrows, no superlatives, no "game-changer".

**Self-contained.** Every short assumes the viewer knows nothing: not the
app, not the last short. A word that is the app's own (a kind, a reading,
resurface, the crew, a room, the seat, the deck, red alert, Secret, a
course, the graph, ambient mode, hold to talk) or a standard's (CalDAV,
GPX) is explained in a few plain words in the same line, or replaced by
the plain word: "a personal log or a sleep log", not "the kind". Where the
setup already says what it is, the hook and the punch may use it. "Entry"
needs no explaining: the setup has said it is a journal. The crew are "the
AI agents" on first mention and "the agents" after.

**The pace.** The feature is on screen from the first frame, under the setup. Real taps and
real typing at a person's speed, a tap mark at each touch, no darting
cursor, at most one tap a second: a viewer is reading the captions.

**Real, every step.** Every label tapped and every phrase said is the
console's own, checked against the user manual (`site/manual/pages/`, and
its appendix of every spoken phrase, made from `VCMDS`). A label in
**bold** below is on screen as written; a phrase in quotes is said after
"computer,". A step a film cannot do on the test server says what it needs
(**Needs**), and that short's card says "on your own server".

**Never.** Nothing from the live journal. Nothing posted from a short: the
share short uses **Dry run**. No short of a feature the demo lacks without
the card saying so.

## 2. The thirty

Tier 1 (1-8) is what no other journal does, Tier 2 (9-22) the daily use,
Tier 3 (23-30) the finish. Each entry is the short as filmed: its props
file is the truth, and this note follows it. Lengths are as rendered, the
whole short, card included.

### 1. The crew

- **Setup:** LCARS is my journal, on my own server. This is the crew: the AI agents that work on the app.
- **Hook:** I don't write the code for this app anymore. I give the orders.
- **Journal:** shots.py's, and shots_crew.py's made-up crew (Number One, Chief Reyes, Lt. Okafor, the seat, the calendar room).
- **Filmed with:** `film.crew`; `eng` steps for Number One's turn.
- **Show:**
  1. Tap **Chats**. The Crew section: **Number One**, Chief Reyes, **Rooms**.
  2. Say "computer, number one, the week view should show each day's tasks as dots". It goes into his conversation; he is working on "the calendar's week view".
  3. His answer: "Aye, Captain. A room for it: Calendar week view. Chief Reyes has the seat and takes it; Lt. Okafor is next."
  4. Say "computer, rooms", then "computer, open the calendar room": the room's messages.
- **Punch:** One agent plans, a few write the code, and they take turns. All Claude Code.
- **Needs:** the crew (stood in: no real engineer runs).
- **Length:** 26.9 s.

### 2. Deploy from the phone

- **Setup:** LCARS is my journal, on my own server. This is an update going live, ordered from my phone.
- **Hook:** I shipped this from the sofa.
- **Journal:** shots_crew.py's crew; Chief Reyes idle on eng/reyes-c12, 3 commits ahead of main, his report "done" (`film.eng`).
- **Filmed with:** `film.crew`, `film.eng`; `eng` steps for the deploy's progress.
- **Show:**
  1. Tap **Chats**, then **Chief Reyes**: his order and his report.
  2. Tap **⋯** (`.chmore`), then **Deploy**. The question, with the branch and its commits: tap **Deploy**.
  3. The deploy's steps in the conversation: "rebasing eng/reyes-c12 onto main", "running the web suite (PERF=0)", "C changed: rebuilding and restarting the server".
  4. "deployed reyes-c12 as 1.4.3: 6 files".
- **Punch:** Tested, rebuilt, restarted. It rolls back by itself if the server doesn't answer.
- **Needs:** the crew (stood in: no real deploy).
- **Length:** 27.7 s.

### 3. "Computer, ..."

- **Setup:** LCARS is my journal, on my own server. This is its voice control.
- **Hook:** My journal answers to "computer".
- **Journal:** shots.py's.
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Tap **Voice**.
  2. Say "computer, show only task". The list is the tasks.
  3. Say "computer, last seven days". This week's.
  4. Say "computer, clear filters". Everything again.
  5. Say "computer, new entry called book the dentist". The entry, titled.
  6. Say "computer, help". The list of phrases.
- **Punch:** Nearly every button has a phrase. "Computer, help" lists them.
- **Needs:** a browser with speech recognition (the page's voice path, the recogniser stood in).
- **Length:** 23.5 s.

### 4. The deck

- **Setup:** LCARS is my journal, on my own server. This is the deck: the journal as a ship in 3D.
- **Hook:** My journal has a starship, and I can walk around it.
- **Journal:** `deck.html?demo`.
- **Filmed with:** `film.py --short` and `film.shots`, not film_console.py: filmed upright at the phone's shape.
- **Show:**
  1. Walk onto the Main bridge (film.py's `bridge-in`, 4 s).
  2. Down the starboard side to the officer at a console (`bridge-tour` on the short's own path, 5 s).
- **Punch:** The ship is the interface. The journal is the data.
- **Length:** 24.3 s.

### 5. Secret entries

- **Setup:** LCARS is my journal, on my own server. This is a Secret entry, one only my password opens.
- **Hook:** This entry is encrypted before the server sees it.
- **Journal:** shots.py's, and the short's row "Notes for the doctor" (the cough, the blood test, the allergy list).
- **Filmed with:** `film.before`: a made-up password set in Config off camera (**Set a password…**, the recovery code kept).
- **Show:**
  1. Tap "Notes for the doctor", then **Edit**.
  2. Tap **Unclassified**: the entry is made Secret.
  3. Say "computer, lock". The row keeps its kind and date only.
  4. Tap the lock chip (`#edcls`), type the password, tap **Unlock**. The text is back.
- **Punch:** The AI chat can't read it, and neither can a copy of the database.
- **Needs:** a password set before the film (`film.before`).
- **Length:** 27.6 s.

### 6. Plot a course

- **Setup:** LCARS is my journal, on my own server. This is plot a course, for planning a trip.
- **Hook:** Four stops, and the weather at each when I get there.
- **Journal:** shots.py's.
- **Filmed with:** `film.before` hides the maps' feature notes; the network live.
- **Show:**
  1. Press **O**: **Course**.
  2. Say "computer, plot a course to Sorrento", then Positano, Amalfi and Ravello the same way. Each stop gets its number and its weather on the map.
  3. Say "computer, best time to leave". The departures.
- **Punch:** The forecast is for when I arrive, not for now.
- **Needs:** the network (the map's tiles, the route and the weather are fetched live).
- **Length:** 25.6 s.

### 7. Stars

- **Setup:** LCARS is my journal, on my own server. These are the stars, a map of my entries.
- **Hook:** Every entry I've written, placed by what it's about.
- **Journal:** shots.py's, every row's vector made before the film.
- **Filmed with:** `film.embed`.
- **Show:**
  1. Press **S**: **Stars**. The starfield draws itself (3 s).
  2. Say "computer, chart German course". It flies to the stars near it, and holds.
- **Punch:** Search finds my words. This finds what's close in meaning.
- **Needs:** the embeddings (`film.embed`: the box's own embedder).
- **Length:** 25.1 s.

### 8. Themes

- **Setup:** LCARS is my journal, on my own server. These are its themes.
- **Hook:** Forty-one themes, and the one I pick follows me to every device.
- **Journal:** shots.py's.
- **Filmed with:** a `cli` step: `lcars-cli` run for real against the scratch server, in a terminal panel at the foot of the screen.
- **Show:**
  1. Say "computer, choose a theme". The picker.
  2. **↓** twice: the console wears each theme as the cursor reaches it. **Enter** keeps the one on screen.
  3. The terminal: `lcars-cli theme set nord`. A second later the console is nord.
- **Punch:** The theme is saved in the journal itself, so every device wears it.
- **Length:** 25.8 s.

### 9. Quick capture

- **Setup:** LCARS is my journal, on my own server. This is quick capture.
- **Hook:** One line, and no editor to open.
- **Journal:** shots.py's.
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Press **q**. **Quick capture**.
  2. Type "called the garage, Friday". Tap **Capture**. The row is at the top of the list.
  3. Press **q** again. Type `/log weight 72.4`. **Capture**.
- **Punch:** It remembers which log it goes in, a personal log or weight. And a number is ready to chart.
- **Length:** 26.4 s.

### 10. Offline

- **Setup:** LCARS is my journal, on my own server. This is the app with no network.
- **Hook:** I lost the signal in the tunnel. I kept writing.
- **Journal:** shots.py's.
- **Filmed with:** `net` steps: the browser offline, the server still up.
- **Show:**
  1. The link drops. The header says **offline**.
  2. Press **n**, type "the tunnel, no signal", **Escape**, back to the list. Again: "still writing". The header: 2 waiting.
  3. The link comes back. The count goes to nothing by itself.
- **Punch:** What I write waits on the phone and sends itself.
- **Length:** 26.6 s.

### 11. Search by meaning

- **Setup:** LCARS is my journal, on my own server. This is search by meaning.
- **Hook:** I didn't remember a single word I'd written.
- **Journal:** shots.py's, and the short's row "One file, on purpose" (June: why the app is one page and one file), every row's vector made before the film.
- **Filmed with:** `film.embed`.
- **Show:**
  1. Say "computer, search for why I kept the app in a single page".
  2. Tap **Match**, then **Meaning**. "One file, on purpose" comes up first.
- **Punch:** Closest in meaning first, even when no word matches.
- **Needs:** the embeddings (`film.embed`).
- **Length:** 19.6 s.

### 12. Tasks and reminders

- **Setup:** LCARS is my journal, on my own server. These are tasks and reminders.
- **Hook:** A TODO in a note is a task. A task is a reminder on my phone.
- **Journal:** shots.py's without its task lines (`film.todos: false`), and the short's three: "Renew passport", "Weekend" (call the plumber), "Car" (the winter tyres).
- **Filmed with:** `film.todos: false`.
- **Show:**
  1. Press **q**, type "TODO return the library books", pick **Task**, tap **Capture**.
  2. Press **t**. The task board has it beside the other three. Tap **Open it**.
  3. Say "computer, reminders": the due date, the alerts, the repeat.
  4. Say "computer, due friday at 5 pm", then "computer, remind me when it is due".
- **Punch:** They sync the way a calendar does, so the phone's own Reminders app has them.
- **Length:** 27.5 s.

### 13. The calendar

- **Setup:** LCARS is my journal, on my own server. This is the calendar: every entry on its day.
- **Hook:** I moved it to Thursday.
- **Journal:** shots.py's.
- **Filmed with:** `film.desk` (840x1212, a mouse) and `drag` steps; shown in the Short's wide panel, the one short not at a phone's size: the phone's week and day have no drag.
- **Show:**
  1. Press **M**. Tap **Week**.
  2. Drag "Renew passport" from Tuesday onto Thursday.
  3. Tap **Day**. Drag from 14:00 to 16:00 on the empty hours, type "dentist", **Enter**: a new entry at that time.
  4. Drag its bottom edge down half an hour.
- **Punch:** Dragging it changes when it was written. Undo is right there.
- **Length:** 27.9 s.

### 14. Chats with the journal

- **Setup:** LCARS is my journal, on my own server. This is a chat with my journal.
- **Hook:** I asked my journal what I did in March.
- **Journal:** shots.py's, and the short's four March rows: "Lisbon, three days", "The server moved to the VPS", "Half marathon, 1:52", "Repainted the hallway".
- **Filmed with:** `film.chat`: the box's own claude, against the scratch journal only.
- **Show:**
  1. Press **A**, then **+**.
  2. Type "what did I do in March?" in **ask about the journal**. Say "computer, send it".
  3. The answer is written as it comes, and held.
- **Punch:** It's Claude, on my server, reading my journal.
- **Needs:** Claude on the server (`film.chat`).
- **Length:** 27.4 s.

### 15. Hold to talk

- **Setup:** LCARS is my journal, on my own server. This is hold to talk: I hold a button and speak.
- **Hook:** A conversation with my own notes.
- **Journal:** the short's four tasks only (`film.todos: false`, `film.tasks: false`): "Book the car's MOT", "Reply to the landlord about the boiler", "Renew the passport" open, "Send Ana the Lisbon photos" done.
- **Filmed with:** `film.chat`, `film.speech`, a `press` step.
- **Show:**
  1. Press **A**, then **+**. Tap **Voice**.
  2. Hold **Hold to talk**: "What's still open from last week?" (a second voice, fed to the page's real Deepgram socket). Let go.
  3. The reply is spoken in the computer's voice while its text is written.
- **Punch:** Or say "start conversation", and the microphone stays open until "end conversation".
- **Needs:** Claude and a voice on the server (`film.chat`, `film.speech`).
- **Length:** 27.7 s.

### 16. Select and Join

- **Setup:** LCARS is my journal, on my own server. This is select and join, for merging entries.
- **Hook:** Five scraps, one note.
- **Journal:** shots.py's, and the short's five ideas: "Lisbon: tram 28", "Lisbon: pastéis", "Lisbon: miradouro", "Lisbon: fado", "Lisbon: Sintra".
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Tap **Select**.
  2. Tap the five Lisbon rows, one a second.
  3. Tap **Join**. The question: tap its **Join** (`#lcOk`). One entry.
- **Punch:** Up to two hundred at once. Nothing is destroyed.
- **Length:** 24.0 s.

### 17. Saved views

- **Setup:** LCARS is my journal, on my own server. These are saved views, kept under a name.
- **Hook:** The filters I set every morning, in one tap.
- **Journal:** shots.py's.
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Tap **Filters**. Say "computer, show only task", then "computer, last seven days".
  2. Press **V**, type "this week", **Enter**: the view is saved.
  3. Press **c**: every filter off. Tap the "this week" chip: it all comes back. Tap **Done**.
- **Punch:** Views are kept in the journal, so the phone and the desk have the same ones.
- **Length:** 27.8 s.

### 18. The share sheet

- **Setup:** LCARS is my journal, on my own server. This is the share sheet, for posting an entry.
- **Hook:** One entry, a different text for each network.
- **Journal:** shots.py's, "Log for Oct 29".
- **Filmed with:** `film.publish`: Bluesky's **Post** and **Dry run** on, every run dry, a made-up account.
- **Show:**
  1. Tap "Log for Oct 29". Press **F**: **Share**.
  2. Say "computer, share on hacker news", then "share on reddit" and "share on bluesky": a card each, its own text.
  3. On the Bluesky card, its text replaced: "Morning review of the LCARS UI plan."
  4. Say "computer, dry run". The card says the post was built and nothing sent.
- **Punch:** It posts only when I tap Post. Everywhere else it fills the text in and I press the button.
- **Length:** 27.2 s. Never **Post**: a short publishes nothing.

### 19. Read aloud

- **Setup:** LCARS is my journal, on my own server. This is read aloud.
- **Hook:** The version for the walk to work.
- **Journal:** shots.py's, its third row opened before the film.
- **Filmed with:** `film.before` (the entry opened), `film.speech`: the reading heard under the clip, no caption.
- **Show:**
  1. The entry. Press **a**: it is read aloud.
  2. Say "computer, pause reading". It stops.
  3. Say "computer, go on reading". It carries on, and is heard for six seconds.
- **Punch:** Any entry, read aloud in the computer's voice.
- **Length:** 26.1 s.

### 20. Crew notes

- **Setup:** LCARS is my journal, on my own server. These are crew notes, for the AI agents that build the app.
- **Hook:** I leave orders for the crew in my notes.
- **Journal:** shots.py's, and the short's "Log for today" (a slow morning, the garage).
- **Filmed with:** `crew` steps: the yeoman's rows written mid-film as crew_notes.py's runner writes them, no role run.
- **Show:**
  1. Tap "Log for today", **Edit**, and type on a new line `@yeoman log my run this morning, 5 km`. Tap **Read**.
  2. The note is queued. The yeoman answers: a gym entry "Run, 5 km", and beside the line "Logged: a 5 km run this morning, 07:40, as #…".
  3. Tap the note's chip, then the link: the entry "Run, 5 km".
- **Punch:** The agents read my entries for orders, and answer beside the line.
- **Needs:** the crew (stood in by `crew` steps).
- **Length:** 27.8 s.

### 21. Open questions

- **Setup:** LCARS is my journal, on my own server. These are open questions, from the AI agents to me.
- **Hook:** The agents ask, and I tick a box.
- **Journal:** shots_crew.py's crew and Number One's question.
- **Filmed with:** `film.crew`.
- **Show:**
  1. Press **!**. **Open questions**: Number One's question and its choices.
  2. Tap A, then No.
  3. Tap **Send**.
- **Punch:** They wait on me. I don't wait on them.
- **Needs:** the crew (stood in).
- **Length:** 22.6 s.

### 22. What did I miss

- **Setup:** LCARS is my journal, on my own server. This is the list of what's new.
- **Hook:** What came in since Tuesday?
- **Journal:** shots.py's, the last visit seeded before its newest rows (`lcars.seen`) and the crew's rows shown (`lcars.crew`).
- **Filmed with:** `film.seed`.
- **Show:**
  1. The full list.
  2. Press **u**. The list is only what arrived since the last visit.
- **Punch:** Each device remembers when I last looked.
- **Length:** 17.3 s.

### 23. The red alert

- **Setup:** LCARS is my journal, on my own server. This is the red alert, for tasks past their date.
- **Hook:** When the app goes red, it means I'm late.
- **Journal:** shots.py's, and the short's two tasks due in the past: "Call the plumber about the boiler", "Return the library books".
- **Filmed with:** `film.before` waits for the red alert.
- **Show:**
  1. The header in red alert.
  2. Say "computer, show the overdue tasks". The sheet: the most overdue first, how late each is.
  3. Tap the first. Its task opens.
- **Punch:** Yellow is a save still sending. Red is me.
- **Length:** 21.1 s.

### 24. Readings

- **Setup:** LCARS is my journal, on my own server. These are readings, the numbers in my journal.
- **Hook:** Three weeks of sleep, and no spreadsheet.
- **Journal:** shots.py's (each "Sleep" entry holds the hours slept).
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Press **E**. **Readings**. Tap **show**: the sleep series.
  2. Tap **avg/week**, then **bars**.
- **Punch:** A number in an entry is a reading. The chart is already there.
- **Length:** 22.6 s.

### 25. Resurface

- **Setup:** LCARS is my journal, on my own server. This is resurface, one old entry at a time.
- **Hook:** Something I wrote months ago and never read again.
- **Journal:** shots.py's old entries.
- **Filmed with:** `film.before` pins the draw (Math.random low), so each **R** takes the newest old entry left.
- **Show:**
  1. Press **R**. "The arena, as first sized".
  2. Press **R**. "Why the journal is one file".
  3. Press **R**. "First week of the [[German course]]".
- **Punch:** Most of what I write, I never read twice. Now I do.
- **Length:** 24.0 s.

### 26. The graph

- **Setup:** LCARS is my journal, on my own server. This is the link graph: the pages my notes link to.
- **Hook:** Every page I've ever linked, on one map.
- **Journal:** shots.py's ([[LCARS UI]], [[German course]], [[link graph]], [[coffee]]).
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Press **v**: **Graph**.
  2. Type "German", **Enter**: German course and its neighbourhood alone.
  3. Tap **Open**: its page.
- **Punch:** The links I type in a note are the structure. The map is the table of contents.
- **Length:** 23.8 s.

### 27. The map of the day

- **Setup:** LCARS is my journal, on my own server. This is the map of the day.
- **Hook:** Where I was, next to what I wrote there.
- **Journal:** shots.py's, and the short's course "The Amalfi coast" (Sorrento, Positano, Amalfi, Ravello, from tomorrow 09:00) and two entries placed in Amalfi: "Lunch on the harbour", "The Duomo steps".
- **Filmed with:** `film.geo` (the harbour) and a `walk` step up to the Duomo; the network live.
- **Show:**
  1. Tap "The Amalfi coast". Say "computer, show it on the map", then "computer, show my location".
  2. Say "computer, record the track". The dot walks from the harbour up through the town.
  3. Say "computer, stop the track", then "computer, show the map of the day": a pin for each place written that day, and the track.
- **Punch:** The route walked is kept with the trip, as a file any map app opens.
- **Needs:** the network, and a stood-in position (`film.geo`).
- **Length:** 27.0 s.

### 28. Ambient mode

- **Setup:** LCARS is my journal, on my own server. This is ambient mode, for a phone left idle.
- **Hook:** What the phone shows when I leave it on the desk.
- **Journal:** shots.py's old entries.
- **Filmed with:** `film.before` pins the memory (Math.random low): "The arena, as first sized", of July.
- **Show:**
  1. Press **z**. The clock, the numbers and a memory, alone on screen; held four seconds.
  2. Say "computer, wake up". The list.
- **Punch:** A clock that reminds me what I wrote last summer.
- **Length:** 20.9 s.

### 29. Plan an hour and the timer

- **Setup:** LCARS is my journal, on my own server. This is plan an hour, with its timer.
- **Hook:** Computer, plan an hour.
- **Journal:** shots.py's.
- **Filmed with:** nothing but the steps.
- **Show:**
  1. Say "computer, plan an hour". Today's next free hour, named in place: type "German, unit 10", **Enter**.
  2. Tap it on the day's grid. Say "computer, start the timer". It counts.
  3. Say "computer, stop the timer", then "computer, show details": **Scheduled** holds the start and the end.
- **Punch:** The start and the end are written into the entry.
- **Length:** 27.6 s.

### 30. One binary

- **Setup:** LCARS is my journal, on my own server. This is the install.
- **Hook:** Download it, init it, run it.
- **Journal:** a new one, made in the short.
- **Filmed with:** release v0.347.2 (30 Oct, Latest on GitHub), its x86_64 tarball fetched off camera from the release page and checked against SHA256SUMS; `film.terminal` and `film.desk`: the commands typed and run for real in a scratch HOME under the run's temp, the server on a free scratch port (never 8080), stopped and the scratch removed when the film ends.
- **Show:**
  1. A terminal: `tar xzf lcars-0.347.2-linux-x86_64.tar.gz && cd lcars-0.347.2-linux-x86_64/` (Tab completing the names).
  2. `./lcars init ~/journal`. It prints the login.
  3. `./lcars --data ~/journal --port <the scratch port>`. The start log.
  4. The console at that address: its Connection dialog, the login typed in, **Connect**: the empty journal, v0.347.2 beside **LCARS**.
- **Punch:** A C server, SQLite, and the app inside. Nothing else to install.
- **Length:** 27.7 s.

## 3. The props files

One file per short, `video/explainer/shorts/NN-<slug>.json`, the shape
`film_console.py` reads; its docstring and video/explainer/README.md
("The props file") are the reference, this is the list once. Top level:
`id`, `title`, `setup`, `hook`, `punch`, `voice` (what the ship's voice
says: the setup, the hook and the punch, word for word as on screen),
`clip`, and `film`.

**The steps** (`film.steps`, played in order; `hold` after any step
overrides its pause):

| Step | What it does |
|---|---|
| `tap` | a finger's tap on a label as it is on screen, or on a selector |
| `type` | typed into the focused field at a person's speed (`cps`) |
| `key` | a key press, shown as a keycap chip |
| `say` | an order through the page's own voice path, written without "computer," |
| `wait` | hold, seconds |
| `drag` | the mouse carried `to` a target or `by` dx, dy (a desk's) |
| `net` | the network cut (`off`) or back (`on`), the server still up |
| `walk` | the stood-in position carried along points over `secs` |
| `press` | a finger held on a target while `speak`'s words are said, then let go |
| `crew` | the made-up crew's rows written mid-film (a POST, or a PATCH by `of`) |
| `eng` | an engineer's conversation, status, task, git or deploy set mid-film |
| `until` | frames until a page expression holds (`max` s), as a chat's answer streams |
| `cli` | `lcars-cli` run for real against the scratch server, in a terminal panel |

**The switches** (`film`'s other fields, each in a few words):

| Switch | What it does |
|---|---|
| `path` | the console's route at boot ("" the list) |
| `lead`, `tail` | seconds held before the first step and after the last |
| `seed` | localStorage set before the page boots |
| `rows` | the short's own made-up entries, after shots.py's; one with `trip` is a course from tomorrow 09:00 |
| `before` | done off camera before the first frame: eval, fill, check, click, wait_for |
| `todos`, `tasks` | `false` drops shots.py's task lines, or its task rows |
| `desk` | a desk's console (840x1212, a mouse), shown in a wide panel |
| `publish` | the Share sheet's Bluesky **Post** and **Dry run** on, every run dry |
| `embed` | the scratch server's embeddings on, every vector made before the film |
| `chat` | the scratch server's chat open to the box's own claude |
| `speech` | what the console reads aloud voiced for real, laid under the clip |
| `crew` | shots_crew.py's made-up crew in the console, and their rows |
| `eng` | the made-up engineers' conversations and deploy at the start |
| `geo` | the position granted and stood in for, the compass too |
| `shots` | the deck's short only: film.py's shots, by name or a path of its own |

The network itself is a step (`net`), not a switch. Three fields are this
note's, for whoever films: `length` (the target, in seconds), `needs`
(what a scratch server lacks, said in the entry's **Needs**) and `notes`
(how a short departs from `film_console.py`). The setup, the hook and the
punch in a props file are this note's, word for word: change them here
first. The steps and the switches are the props file's: a film that
changes them changes this note's entry after it.

## 4. Left out on purpose

The social watch (it would put other people's comments on screen) and the
public demo's **Reset** (a feature of the demo, not the app).
