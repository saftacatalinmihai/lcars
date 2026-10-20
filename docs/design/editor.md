# The entry editor — design review

Status: **built** (2026-10-13, Lt. Mendez; walked at
0.177.21, the editor unchanged in 0.178.0). P1, P5 (0.181.0), P2-P4
(0.181.1), P11 and P12 (0.181.2), P6 (0.183.0), P7 (0.183.1), P8 (0.183.2),
P9 and P13 (0.183.3), P10 (0.192.0) are built, each marked below. The captain said no to
P14 (2026-10-14). The mockup
(`lcars-ui/mockups/editor.html`) was deleted in 0.183.3, the review built,
as the chat's was.

The captain finds the editor clunky. This review used it as the captain does: a
scratch server on a synthetic 4000-row journal (`test/synth.py`), headless
Chromium at an iPhone's 390×844 (touch, 2×) and at 1280×860, opening
entries from the list, the reader and the day view, editing, adding,
cancelling, switching, with the slash and tag popups. Chromium cannot raise
an iOS keyboard; what is said about it below follows from the layout and
from 0.161.1's rule (the keyboard is the browser's: iOS pans the page to the
focused field, nothing in the page fits itself to the keys), and is marked
*on the iPhone* where it needs a real device to confirm.

House style kept: `chat.md` §3 (immediate feedback, the table form),
`chat.md` §2.3's point that a tap must not drop the keyboard, 0.161.1 (no
keyboard fitting), `sweep-ui.md` item 8 (the picker → `datetime-local` is
already the captain's call and is not re-argued here).

---

## 1. The editor as it is (0.177.21)

**Ways in.** A list row opens the **reader**, not the editor; Edit is the
right half of a Read/Edit segment in the header (or `e`, a double-click on
the text, "computer, edit"). The day view's rendered text opens the editor
directly with the caret where it was tapped (`dayEditClick` →
`editEntry(id, srcOffsetAt(…))`). `+`/`n`/the FAB's speed dial start a new
entry; Duplicate, Continue and the day page start a pre-filled one.

**The form, top to bottom** (phone, one column, `#edbody` 2120px tall in a
720px pane — three screens):

| y (px) | what | note |
|---|---|---|
| 0 | header: ‹ List, #id, Read/Edit, ↻ | the save mark is a 12px word after the #id |
| 86 | `kind` text field, full width | free text + datalist |
| 160 | `title` | |
| 213 | kind chips (new entries only), 3 wrapped rows | pushes content to y 372 |
| 258 | `content` textarea, ≥44vh | |
| 562 | media ribbon | |
| 639 | `value_int`, `value_float` | raw column names |
| 790 | `state done_bool` Open/Done | |
| 860 | `record deleted` Live/Deleted | the Delete button does the same |
| 931 | `created_at_utc` + its picker, always open (~560px) | |
| 1306 | `last_modified_at_utc` — an editable field | "server-stamped on save"; PUT never sends it |
| 1403 | `start_date` + picker, always open | |
| 1761 | `end_date` + picker, always open | |
| bottom | Dictate · Video · Save · Revert · Dup · ↪ · (Chat) · Delete | 7-8 pills in 390px |

**Saving.** An existing entry autosaves 3s after typing stops (`autosaveMs`);
a new one never does until its first Save. Ctrl+S / Save / Read save at once.
Each save shows `saving` → `✓ saved` (fades) or `not saved` beside the #id.

**Leaving.** ‹ List, ✕, Back, another row, Duplicate, Continue, a new entry
with unsaved text: the browser's own `confirm("Discard unsaved changes to
this entry?")` — OK discards, Cancel stays. There is no "save and go".
`confirmDiscard` is native on purpose (popstate must decide synchronously;
the comment above it says why). Read and Escape save first instead.

## 2. What is clunky, and why

Each point has the step that shows it. **F** marks a miss of the immediate
feedback rule; the full audit is §4.

1. **A stray Chat button on every entry, on a phone.** Open any entry at
   390px: the bar has CHAT between ↪ and Delete, also on a new
   personal_log. `#bCrewChat` is `hidden`, but the phone rule
   `.pill{display:inline-flex}` (index.html ~3082) outranks `[hidden]`.
   Tapping it on a non-crew entry calls `crewChat` → `chatsList()`: it
   leaves the entry for the chat list. A bug, and the bar's 8th pill. **F**
   (a tap that does something nobody asked for).
2. **Leaving with unsaved text asks the wrong question, in the browser's
   voice.** Edit #4999, type, tap ‹ List within 3s: a grey system
   `confirm` — "Discard unsaved changes to this entry?" — whose default
   (OK) throws the text away. The obvious answer, "save it", is not on
   offer: Cancel, Save, ‹ List again. Same on switching rows (desktop),
   Duplicate and Continue while dirty. Meanwhile Read and Escape *do* save
   first, so the doors disagree. **F**.
3. **Revert is one tap from Save, instant and final.** Type, tap Revert
   (next to Save on the phone, same size): the text is gone — no question,
   no Undo, only a click sound. The one destructive button with no way
   back (Delete has a themed question and an Undo toast). **F**.
4. **Three screens of database columns.** Scroll the form: value_int,
   value_float, `done_bool`, `record deleted` Live/Deleted, four timestamps
   with their column names, three full date pickers always open (each
   ~360-560px), an editable `last_modified_at_utc` that the save never
   sends. For a journal entry the captain needs a title and the text; the
   rest is a detail wanted now and then. The Live/Deleted toggle
   duplicates Delete/Restore; the editable last-modified is a field that
   lies.
5. **The kind takes the top of the screen.** The first thing under the
   header, full width, is `kind` — the field changed least (re-kinding a
   saved entry is "rare and deliberate", paintEdKinds' own comment). For a
   new entry, the kind chips then wrap to three rows, so content starts at
   y 372 of 844, and with the keyboard up (~336px) the content box is
   barely on screen.
6. **Save's feedback is a 12px word, and Save then looks disabled.** Tap
   Save: `data-save="saving"` is set in the same frame (good), but it is a
   small word after the #id, and the button itself gets no pressed or busy
   state; when the save lands, Save turns grey (the clean form), which
   reads as "disabled", not "saved". *On the iPhone* the header can be
   panned off the top by the keyboard, and the bar is under the keys: while
   typing there is no save state on screen at all. **F** (partial).
7. **Read with unsaved text looks ignored on a slow link.** Edit, tap
   Read: the save starts (mark `saving`), but the segment stays on Edit
   until the write lands (`setRead` returns early) — on the VPS over 4G
   that is a beat with the tap apparently not taken. **F**.
8. **Getting to the editor takes two taps, and the second is far.** Tap a
   row → reader → reach the top-right Edit (or double-tap). The day view
   already does it in one: tap the text and the caret is there. The reader
   and the day view, showing the same rendered text, answer the same tap
   differently.
9. **‹ List goes to the list, Back goes where you came from.** Open the
   day (READ DAY), tap an entry's text, edit, Save, tap ‹ List: the list
   (`/ui/`). Press Back instead: the day view (`/ui/day/…`). The button
   and the gesture disagree, and the button is labelled for one origin.
10. **A new entry needs a second tap to write.** + opens the form with
    nothing focused (deliberately: "autofocus would fling up the
    keyboard"), so the keyboard needs another tap on the box. For +, the
    intent *is* to write, and iOS allows a focus inside the tap's own
    handler.
11. **A new entry can be saved empty, and is then "HTTP Entry".** +, Save
    at once: a row is created with no text and the server's default title
    "HTTP Entry". Nothing says "write something first".
12. **New entries do not autosave, and leaving one asks the native
    question.** +, type "a thought", wait 4s: still `NEW ENTRY ● UNSAVED`;
    ‹ List → the native discard confirm. The draft is in localStorage and
    is offered back later as a toast — easy to miss, and the captain does
    not know it is there.
13. **Enter after a #tag does not make a new line.** Type `… #home` and
    Enter: the tag popup is open and takes Enter as "insert", so the line
    does not break (`#homex` on the next keystroke). The same for a `[[`
    link whose name is already complete.
14. **The slash menu hides its best commands.** Type `/` at a line start:
    eight rows, all dates (/time /now /date /yesterday /tomorrow /weekday
    /week /day). /todo, /log and /location are only found by typing; `/to`
    ranks /tomorrow over /todo. The footer ("↑↓ move · Tab / ⏎ insert ·
    Esc dismiss") is keyboard help on a phone.
15. **Escape then letters (desk, iPad keyboard).** Typing, Escape saves and
    drops to the reader; the next letters are now commands. In the walk,
    "hello" after an Escape became `e` (edit), `l` (play), `o` (new entry
    after this) — and an empty entry was one Save away.
16. **Desktop: fine at a glance, the same depth below.** At 1280 the first
    screen is kind, title, content, media: good. Under it the same raw
    columns and three open pickers; the bar's eight pills are labelled in
    words and fit. Points 2, 3, 6, 7, 9, 13-15 apply as they are.

## 3. Proposals (mobile first)

Size: **S** an afternoon, one function or CSS rule; **M** a day, a few
functions and their tests; **L** several days or a structural change.
**Captain's call** = it changes a deliberate decision or the look.

**P1. Hide the stray Chat button on phones.** *Built in 0.181.0*
(`[hidden]` beats every display rule, page-wide; `#series`, `#ekchips`
and `#esug` were shown the same way). `.pill[hidden]{display:none}`
(or `display:none!important` for `[hidden]` under the phone media query),
and look for other `hidden` pills the same rule shows. *Why:* point 1; it
also gives the bar back a slot. **S.** Not a call: a bug.

**P2. Leaving saves; nothing asks.** *Built in 0.181.1.* Every door out of an existing entry
with unsaved text — ‹ List, ✕, Back, another row, Duplicate, Continue, a
new entry, the voice "close" — starts the save (the `runSave` queue) and
leaves at once, as Read already means "save first". The row in the list
shows the state where the entry lands: *saving…* in the same frame, then
nothing; a failure marks the row *not saved · Retry* (the text is in the
local draft already, `saveDraft`), and the toast says so. Because nothing
waits on the answer, popstate stays synchronous: the reason
`confirmDiscard` is native goes away with the question. A conflict (the
"Changed on the server" dialog) still asks, after the move, on the row.
*Why:* points 2, 7, 12; one rule for every door. **M.** Not a call for
saved entries (autosave already writes them 3s later; this only stops
asking first). For **new** entries see P8.

**P3. Revert gets an Undo, and moves off the thumb's path.** *Built
in 0.181.1* (and in ⋯ since 0.181.0). Revert
restores the form and raises a toast "reverted — Undo" that puts the edited
text back (the same toast the delete uses). On the phone it moves into ⋯
(P5). *Why:* point 3. **S.**

**P4. One status chip that is also Save.** *Built in 0.181.1.* Replace Save and the header's
12px word with one chip in the header beside the title: *● Editing* (dirty,
autosave armed) → *Saving…* (pressed look, in the tap's frame) → *✓ Saved*
(green, 1.5s, then *Saved* dim) → *✕ Not saved · Retry* (red, stays). A tap
on it saves now. On the phone the chip also rides on the content label's
line (*CONTENT · 42 words · ✓ saved*), which is next to the text and so is
what iOS keeps on screen while typing; *on the iPhone*, check it is. *Why:*
points 6, 7 (the Read segment moves at once, the chip carries the save).
**S-M.**

**P5. A short bar on the phone: Dictate · Video · ⋯.** *Built in
0.181.0* (Save stayed on the bar until P4's chip took its place). The bar keeps what
the thumb wants while editing; ⋯ opens a sheet with Duplicate, Continue,
Revert, Chat (crew entries only), Delete/Restore/Discard (red, last).
Desktop keeps its labelled row. *Why:* 7-8 pills at 46px in 390px, Save
beside Revert beside Dup. **S.**

**P6. Fold the columns into "Details", in words.** *Built in 0.183.0*
(the Scheduled range is two chips, start and end, each its own picker).
Below the media ribbon
one fold, closed by default (a `<details>`, `sweep-ui.md` item 5), summary
line *Written Tue 13 Oct 16:27 · open · unscheduled* so it is readable shut.
Inside, labelled for people:
- **Written** — a one-line chip with the local time; tap opens the picker
  (one picker, the one tapped; the other two stay shut);
- **Scheduled** — *Add a time* / *Thu 15 Oct 09:00 → 10:30*, same picker;
- **Done** — the Open/Done toggle (and as a chip by the title for a task
  kind, where it matters);
- **Number** — one field, shown when the kind carries readings
  (`measureSeries`) or either value is non-zero; value_int and value_float
  stay as they are underneath;
- **Last changed** — plain text, not a field;
- the `record deleted` toggle goes: Delete/Restore is the one way.

The UTC column names stay in each field's tooltip for the captain who wants
them. *Why:* point 4; the form goes from 2120px to about one screen.
**M.** Captain's call (the raw view was a choice; this keeps it one tap
away rather than removing it).

**P7. Kind as a chip in the header line, title as the page's heading.**
*Built in 0.183.1* (the chip sits under the title, where the reader has
its badge: the phone's header has no room for it, see the 430px rule
that hides the head's badge; the picker makes a new kind).
The editor's top becomes the reader's: the kind chip (tap → the kind
picker, `openKindChoice`, which already exists) and the title as a large
borderless field in the reader's `#rd_title` face. The full-width kind
field goes. For a new entry the kind chips are one scrolling row under the
title, not three wrapped rows. *Why:* point 5; Edit looks like Read with a
caret, so switching between them stops being a jump. **M.** Captain's
call (look).

**P8. A new entry is a real draft: focused, autosaved once it has words,
never empty.** *Built in 0.183.2* (a photo counts as words; a scaffold
left untouched is not kept, with a Reopen in the toast; the speed dial's
microphone and camera rows do not raise the keyboard). + focuses the content box inside the tap (keyboard up, one
tap, as a messaging app opens a thread); Save/the chip is *Write something
first* until there is a title or text; once there is, it autosaves like any
entry (the first save creates the row: the url becomes `./entry/<id>`, the
list gets the row). The scaffolds that open full (Duplicate, the day page,
a template) keep today's rule — nothing written until a first edit or Save
— because they are drafts to read over. *Why:* points 10, 11, 12. **M.**
Captain's call: today new entries are deliberately left to the writer
(`armAutosave`'s comment), and the focus is deliberately not taken.

**P9. One tap on the rendered text edits, in the reader too.** *Built in
0.183.3* (the reader's double-click to edit went with it). The reader
answers a tap on its text as the day view does: the editor, caret at the
tapped word (`srcOffsetAt`), with the same exclusions (links, task boxes,
media, folds, a text selection, a scroll). Read/Edit stays for the other
direction. *Why:* point 8; one rule for the same rendered text. **S-M.**
Captain's call: a tap to wake the phone or to stop a scroll could raise the
keyboard; the day view has lived with it.

**P10. Back where you came from.** *Built in 0.192.0* (`edFrom`,
`edBack()` in index.html; the voice's "close" too; from any view but the
day, the board or a search it is ‹ List, as proposed, and ✕ and Escape on
a desk still close to the list). ‹ List is labelled and acts by origin —
*‹ Day* back to the day view at its scroll, *‹ Tasks*, *‹ Search*, *‹ List* —
and is the same step as the Back gesture (history back when the previous
page is the origin). *Why:* point 9. **S-M.**

**P11. Enter makes a line when the popup has nothing to add.** *Built
in 0.181.2.* When the
highlighted suggestion equals what is typed (`#home` → #home, a complete
`[[name]]`), Enter closes the popup and breaks the line; Tab still
inserts. On a phone, a tap on a row is the way to take one. *Why:* point
13. **S.**

**P12. The slash menu leads with what is written most.** *Built in
0.181.2* (a fixed order; ranking by use, kept in localStorage, was not built). An empty `/`
shows /todo, /log, /now, /day, /time, /location first (or by use, kept in
localStorage), dates after; prefix ranking prefers the command used before
(`/to` → /todo); the footer's key help is desk only. *Why:* point 14. **S.**

**P13. Escape lets go before it leaves (desk).** *Built in 0.183.3* (in
any of the form's fields; e, with nothing focused in the editor, is back
into the text, where it used to toggle to the reader). In the textarea, the first
Escape saves and blurs but stays in the editor; a second Escape (or Escape
with nothing focused) goes to the reader. Letters after one Escape are then
harmless (an editor with no focus ignores command letters for 1s and shows
*press e to type*). *Why:* point 15. **S.** Captain's call (it changes a
habit).

**P14. A keyboard accessory row (not proposed now).** *The captain said
no (2026-10-14): the keyboard stays the browser's.* A strip on the
keyboard's top with the chip, `/`, `#`, `[[`, Dictate and Done would make
the phone editor feel native, but it means fitting the page to the
keyboard, which 0.161.1 took out on purpose. Listed so the captain can say
no to it explicitly. **L.** Captain's call.

### The order I would build

1. **P1** (a bug, minutes) together with **P5** — the phone bar becomes
   Dictate · Video · ⋯ and the Chat ghost is gone.
2. **P2 + P4** — leaving saves and the chip shows it; this removes the
   native confirm, the worst moment in the editor, and fixes the
   feedback misses 2, 6, 7 at once. **P3** rides along (Revert's Undo).
3. **P6**, once the captain says yes — the form fits a screen. The
   biggest visible change for the "clunky" feeling, and independent of the
   rest.

Then P8 and P7 once the captain has decided them, P9-P13 as small follow-ups.

## 4. Immediate feedback audit

What each interaction shows at once (same frame, no network), as walked at
0.177.21. ✓ meets the rule, ✗ misses it, ~ partly.

| Act | At once | Later | | Fix |
|---|---|---|---|---|
| Tap a list row | reader opens, sound | body if lazy | ✓ | — |
| Tap Edit | form | — | ✓ | — |
| Tap Read, unsaved | `saving` word; segment stays on Edit | reader when saved | ✗ | P4 |
| Tap Save | `saving` word (12px); button unchanged | `✓ saved`, button greys | ~ | P4 |
| Autosave | `● unsaved` while typing | `✓ saved` | ✓ | P4 (bigger) |
| Tap Revert | text gone, sound | — | ✗ (no Undo) | P3 |
| ‹ List / ✕ / Back, unsaved | browser confirm, OK = discard | — | ✗ | P2 |
| Another row / Dup / Continue, unsaved | browser confirm | — | ✗ | P2 |
| ‹ List, clean | list | — | ✓ | — |
| Tap Delete | themed question | Undo toast | ✓ | — |
| Tap Chat (phone, any entry) | leaves for the chat list | — | ✗ | P1 |
| Tap + | form, nothing focused | — | ~ | P8 (0.183.2: the box focused, keyboard up) |
| Save a blank new entry | `saving` | "HTTP Entry" row | ✗ | P8 (0.183.2: *Write something first*, nothing sent) |
| Type `/` | popup | — | ✓ | P12 |
| Enter after `#tag` | popup inserts, no new line | — | ✗ | P11 |
| Tap a kind chip | field changes, sound | — | ✓ | — |
| Picker chips (±15m, now) | field changes | — | ✓ | — |
| Tap the day view's text | editor, caret placed | — | ✓ | — |
| ↻ Refresh | button disabled while it reads | form | ✓ | — |
| Dictate / Video | pressed (`aria-pressed`) when the engine starts | words | not walked (no microphone headless) | check on the iPhone |
| Escape, typing (desk) | saves, reader | letters become commands | ~ | P13 (0.183.3: saves, lets go, *press e to type*) |
| Tap the reader's text | nothing (double-click: the form) | — | ~ | P9 (0.183.3: editor, caret placed) |

## 5. Questions for the captain

1. **P6:** fold the raw columns into Details, in words? (They stay in
   tooltips and one tap away.)
2. **P7:** the kind as a chip in the header and the title as a heading — the
   editor looking like the reader?
3. **P8:** should a new entry take the keyboard on +, and autosave once it
   has words?
4. **P9:** one tap on the reader's text to edit, as the day view does?
5. **P13:** Escape twice to leave the editor on a keyboard?
6. **P14:** confirm the keyboard stays the browser's in the editor too.
