# The console's UI rules

The rules the web console (`lcars-ui/index.html`) is built to, from the
October 2026 review (docs/design/ui-review-2026-10.md, slice 0). Read
them before changing how anything in the page looks. The deck
(`deck.html`) has its own (docs/design/deck-style.md).

The page is LCARS, and that is a pinned brief: a black field, warm
structure and cool data, elbows, capped bars, condensed uppercase labels.
These rules are about what sits inside that frame. What the review said
to keep is listed at the end; do not "fix" it.

Every rule names the check that fails when it is broken (its `Check:`
line, the last rule's subject), most of them `lcars-ui/test/rules.py`'s,
run by `run.sh`. The rules from "No colour literals outside :root" on are
the research's of 24 October 2026 ("Good UIs with Claude Code: what the
research says", in Reports), with the analysis of the console at 0.321.0
that measured the page against them; the briefs' half of that research is
CLAUDE.md's "The web UI".

## Type scale

Six sizes, about 1.2 apart, and nothing else:

| Token | Size | For |
|-------|------|-----|
| `--fs-cap` | 12px | the smallest: chips, counts, a hint under a field |
| `--fs-meta` | 13px | secondary lines: a row's kind and time, a sheet's notes |
| `--fs-body` | 16px | reading on the desk, inputs everywhere (iOS zooms under 16) |
| `--fs-lead` | 17px | reading on the phone (Apple's body size), a row's title there |
| `--fs-title` | 22px | a view's or a sheet's title |
| `--fs-head` | 28px | the one big heading on a screen |

The reader's entry title is the one exception, at 34px on the phone.
Nothing is under 12px: secondary text is set apart by colour (`--dim`)
and weight, not by shrinking it (Refactoring UI). A new size is a change
to this table first.

The tokens are in `:root` (`--fs-reader` is the 34px exception): write
`font-size:var(--fs-meta)`, never a literal size. Code inside text is the
one relative size, `.875em` of the text around it.

Check: `rules.py` [type] (a font-size is a token, an em, or a display
numeral named in `SIZES_NAMED`; none in a style attribute).

## Faces, one role each

- **Antonio** (`--disp`) for chrome: bars, labels, buttons, pills, day
  bars, times in a column. Uppercase and tracked, as LCARS has it.
- **The sans** (`--sans`) for anything read: titles, previews, meta
  lines, the editor's text, the reader.
- **Mono** (`--mono`) only for code: code spans and blocks, regexes,
  raw values (a path, a slug in Details, an id where it is copied). Not
  for labels or prose; a small mono label is the review's "costume".
- Numbers that line up (times, ids, counts) take
  `font-variant-numeric:tabular-nums`, in whichever face.

Check: `rules.py` [faces] (a rule that sets `--mono` is one of `MONO_OK`'s,
the code and raw-value rules) and `audit.py`'s 1.1 lines (the faces' roles).

## Targets

Every control a finger reaches is at least 44x44px (Apple's 44pt;
WCAG 2.5.8's 24px is the floor, not the aim). Where the layout cannot
grow, the hit area grows and the look does not: a transparent `::before`
inset by -8px to -12px around the control (the control `position:relative`),
so taps land without anything moving. Two targets' hit areas do not
overlap. The header pills are 44px tall on the phone. A checkbox's
`<label>` is its hit area (a tap on it toggles the box); a select's is
not (a tap on its label only focuses it), so a select is 44px itself. A
link inside a sentence (an entry's text, Statistics' lines) is WCAG
2.5.8's inline exception. The desk's layout, at a mouse, keeps its
compact controls: the rule is the phone's, at every view it has.

Check: `targets.py` [targets] (every visible control on the list, the reader,
the editor, the ⋯ sheet, the filters drawer, the month, a new entry,
Tasks, Statistics, the chats, the help, the palette, Reports and the
graph, at a phone's size; run.sh's screens stage).

## Icons

One drawn SVG set, one stroke weight (24px box, 1.75px stroke,
`currentColor`), with a short label under the icon on the phone. No
Unicode glyphs standing in for icons (▤ ◉ ◆ ▦ ☑ ✦ …): they come in mixed
weights from whatever font has them, and say nothing on their own.

The set is the `<symbol id="i-NAME">`s at the top of `index.html`'s
body; markup writes `<svg class="ic"><use href="#i-NAME"/></svg>`, the
script `ic("NAME")`. A new icon is a new symbol there, drawn on the 24px
box in strokes only (no fills), round caps and joins. Drawn at another
size, raise `stroke-width` by the same ratio so the stroke still lands
at 1.75px (16px: 2.63, 18px: 2.33, 28px: 1.5). In a pill the icon goes
before its label and the pill is a flex row with a gap, so a label a
phone hides (`.lg`) leaves no space. Left as text on purpose: the small
marks inside a line of text (▾ on a chip, ✓, ×), which are type, not
controls.

A mark that sits inside a line of text and is drawn (the open-elsewhere
arrow, a fold's caret, the find lens) is `ic(name, "inl")`: the text's
own size, `.ic.inl`, and a caret turned open by `.down` or its head's
`aria-expanded`.

Check: `rules.py` [icons] (no glyph of its list in the page's markup or
script, however written: itself, a script's `\u2197` or markup's
`&#8599;`. Slice E drew ↗ ⌕ ▸; the escapes had hidden ten more, pinned
by name in `GLYPHS_LEFT` and expected to fail until a slice of their
own: the chats' ⚒ ◆ ⚙ ✎, the course map's ☰ ◀ ▶, a task's ☑, the
rails' « »).

## Headers

Not every button can be primary (Refactoring UI). On a desk the header
is ranked: the views as one segmented LCARS bar (Graph, Stars, Course,
Deck), then the three primary actions (New, Voice, Chats), then ⋯ for
the rest (Day page, Reload, Sound, Config, and the filters column's
views again). On a phone the reader picks up to four for the header
(`QUICK_MAX`), each an icon over a short label, and ⋯ holds the others.
Every button stays in the DOM wherever it shows, so keys, voice orders
and tests find it, and the ⋯ sheet presses the real button. Nothing
floats over content: the desk's Chats is the chat dock's door, where a
floating pill used to sit over the reader's toolbar.

Check: `rules.py` [headers] (the header's order and `QUICK_MAX`) and
`buttons.py` [headers] (every button opens its view from where it shows).

## The phone's frame

On a phone the list sits in an LCARS elbow frame, as the desk's filters
column does: a bar down the left edge (orange, purple, blue, top to
bottom) joined to the header's strip by a concave fillet, and turning
at the foot into a blue elbow whose bar carries New (`#lfoot`,
`#lnew`). The foot is in the column's flow, so nothing floats over the
rows or the rail and neither needs a berth for a button (WCAG 2.4.11).
New is a 44px pill, its + beside the label, at the thumb. A tap is a
new entry; a hold or a slide up opens the speed dial (`#newdial`: its
options in their own colours, each an icon from the set), and each
option runs from the pointerup or the click, never a timer. A joint is
a radial-gradient fillet at the inner corner, never a border radius on
the content. Whatever else docks to the bottom (the toast, the tape
deck) sits above the foot, and the voice read-out lifts it.

Check: `audit.py` [frame] (the foot, the toast and the tape deck dodge each
other) and `targets.py` [targets] (New's 44px on the list).

## The phone's list row

A row of the phone's list is two lines and at most 64px tall: the
time in the kind's colour over the entry's number on the left; the
title on the first line, cut to one; then the kind's name in its
colour and its flags (a reading, done, scheduled) at the meta size,
then one line of the text in the reading face at the body's, on one
baseline. Eight rows a screen under a day bar, about ten without. The
kind's line takes at most half the row; past that the kind's name gives
way with an ellipsis and the flags never shrink, so the text keeps a
third of its column whatever the kind is called (25-30 characters
after "Personal log"). With a search typed, the text is an excerpt that
opens at the hit, with no "…" before it ("plants a branch"), so the
highlight is on the line, not past the ellipsis: beside a search's date
and flags at 320 wide the line holds about eight characters. The cut is
made in the plain text, never in the source, so a hit inside a link's
text shows no markup or URL (the desk's two lines keep their lead-in). Every row is
still 44px or more. The desk's rows keep three lines (research slice
D, direction A of the mocks, the captain's choice).

Check: `targets.py` [listrow] (every list row on screen at 390 and at
320 wide between 44 and 64px, the title one line; a row with a long
kind name, a reading and done: its flags whole at both widths, its text
a third of the column at 390; with a search typed, each row's
highlight's first letters showing on its line and no link markup, a
hit inside a link's text among them; `tests.js` the same for the
excerpt) and `rules.py`
[listrow] (the phone block cuts the text to one line and keeps the
title unwrapped).

## The phone's month

A grid too small for words carries none: on a phone the month is each
day's number in the display face and up to three dots in its kinds'
colours (the biggest first), today ringed, the chosen day lit orange.
The chosen day (`calAt`) is read under the grid as an agenda, a row per
entry at the list's sizes (time in the kind's colour, name, kind name);
a tap on a day chooses it, a tap on a row opens the entry, and the
agenda's head carries what the cell's tap used to do (Day, In the
list). Every cell and control is 44px. The desk's cells keep naming
their entries. A disabled control (the month after this one) is drawn
dim and unlit, not faded by opacity: off, and still readable at 4.5:1.

Check: `targets.py` [month] (the chosen day lit, its agenda's rows, every
cell and control 44px).

## The phone's week and day

The week and the day read like the month (the design pass's slice 4): on
a phone each is the month's row of dot cells for the week's seven days
(`calStripHtml`, the cells `calCellHtml`'s), the chosen day lit, and the
chosen day read under it as the month's agenda. The week's tap on a cell
chooses a day with entries; the day's chooses any day, past or ahead,
since planning is mostly for the days ahead, and there a cell counts the
day's scheduled blocks as well as what was written (`calSchedIndex`), so
a planned tomorrow does not look empty. On the day a scheduled block is a
row at its start with its end under it, its real times when it crosses
midnight, with the other end's day ("from yesterday", "until tomorrow");
a block with no end takes its own hour only. The hours nothing holds fold
into one row a run ("4 hours free", with a chevron), split at the hour in
hand on today, a "now" line before it. A tap on a run of more than one
hour opens it into one row an hour (with a +); a tap on a one-hour row
schedules that hour through the calendar's own create (`calPlanAt`,
`calCreate`: a start and an end), never the new-entry path, which would
set when the entry was written; the row says "planning" in the tap and,
failing, says so where it was (the row found again if the day was
redrawn meanwhile), itself the Retry. "Plan an hour" takes the next free
hour on today; on another day it opens the day's free hours and asks
which. The new hour is named in its row's place, an empty field asking
"what is it?" (never "name": a contact word, check.py), never the
server's "HTTP Entry". No
drag on a phone: the hints name the taps (an entry's Details: Written on
the week, Start and End on the day). Offline, an amber line says what is
read from the device. Every cell and row is 44px. The desk keeps its
columns and its hour grid.

Check: `tests.js` [weekday] ("the phone's week and day": the strip, the
agenda, a day ahead chosen and its planned dots, the free runs, a run
unfolded and an hour of it planned, a block with no end, across midnight,
the tap's POST with a start and an end and no `created_at_utc`, the
failure on its row and on a redrawn one, offline, "plan an hour" on today
and on another day); targets.py and axe.py walk the week and the day,
targets.py the unfolded hours too.

## Select mode

Select mode's bar (`#pickbar`, the design pass's slice 5) is one line on
top: the count in the display face ("2 picked", "nothing picked"), All
(None once every row the list shows is picked, which is what Clear was:
there is no Clear), and Done, lit. The four actions (`#pkacts`) are Kind,
Schedule, Join and then Delete, set apart and in red; their labels are one
word, the count is on top. On a phone they stand in the list's foot in
New's place, where the thumb is (`pickPlace` moves the same buttons, never
copies); on the desk they sit in the bar between All and Done. Under the
count one line (`#pknote`) says what the bar is doing: the change being
written ("deleting 3…", the actions held), a failure (the picks narrowed
to the rows that did not change, so the same button is the Retry, and it
says which), or that the link is down (the outbox sends the writes when it
is back). A picked row shows its box, no id.

One change at a time: while one is written, every other way to start one
(the bar, J, a voice order, a palette row) is refused with the deny sound
and a toast saying what is still going ("still deleting 3…"), voice told
the same; a Kind or Schedule refused keeps its dialog and what was typed.
An Undo pressed then is never lost: it waits ("undo waits: deleting 3
first") and runs once the write ends, and its toast never takes the Undo
of the write it waited for: with an action toast up its words join that
toast, the action kept, and a Retry of its own waits until that toast is
gone. An Undo skips a row holding something else than the change it
reverses left there (a later change stands), counted ("1 skipped, changed
since"). The join reads the picks again after
its confirm, and writes nothing if they changed. A join whose text landed but some of whose rows would
not delete is half done: the mode stays with only those rows picked, the
line says "Joined; 2 still here. Delete them to finish" (Delete is the
Retry, never Join, which would fold the text in twice), and the toast
keeps an Undo for what landed. The join's Undo brings the rows back before
it takes the text out of the target: with one still out the text stays
(words in two places, never in none), and the toast counts what is still
deleted with a Retry. It puts the text back only over the joined text
itself (read again, then a PATCH with `if_modified`): an edit made since
the join is kept, and said. An Undo's failure is said in the toast
only: it never narrows the picks or writes the bar's line. The toasts
name an entry by its title and a kind by its name, count what failed
("undo left 2 as they were", "kind not changed"), and never show an id.

Check: `tests.js` [select] ("select mode's bar": no Clear, Done lit, the
order, the actions moved to the foot on a phone and back, nothing picked,
one, many, a failure narrowed and retried, offline, a long count, "pick
none"; "select mode's writes": each door refused mid-write, an Undo's
failure leaving new picks, the half join and its Undo, the toasts' words;
"round three": an Undo mid-write waiting and run, a refused Kind keeping
its dialog, the picks changed during the confirm, the join's Undo with a
row still out and its Retry; "round four": a waiting Undo keeping the
other write's Undo, a row changed since skipped, an edit since the join
kept);
targets.py and axe.py walk select mode on the phone, axe.py on the desk
too.

## The Day view

A day is read one way: the Day view (`openDay`, the design pass's slice 3,
the captain's choice A), the same for the header's Today, the list's day
bar, `D`'s "read the day" and a deep link, on the phone and the desk. Its
head is the day ("Today, Sat 24 Oct"), its facts counted under it (how
many, of how many kinds, from when to when, and how many the list's
filters hide), the day's map line (`#dmap`) kept; then each entry by time,
its head the month agenda's row (the time in the kind's colour at
`--fs-lead`, the title, the kind by its name, no id), the kind's colour
down its edge, its text in the reader's own render at `--fs-body`. The
foot is Copy and Save as a page beside Close; the plain-text forms
(Headers, Content), Select all and Copy MD are behind its ⋯. The view
writes nothing of its own (a task chip is the reader's write, as in the
reader): Today opens it, and Save as a page (`dayPage`, "save the
day page", `P`) opens the day's page as a draft in the editor, written
only once it is edited. An empty day says "Nothing written" and offers
no Copy or Save as a page (today: Write one now); offline, an amber line
says what is read from the device. Every control is 44px.

Check: `tests.js` [dayview] ("4.10 the button": Today writes nothing, the
rendering by time, the kind by name and no id, the ⋯, Save as a page
written only on an edit, the voice orders; and "3.4 day view"); targets.py
and axe.py walk "the Day view".

## One control per choice

A choice is offered once, by one control; a second way to the same
choice is a second thing to read, and the two drift apart. The editor's
kind is the kind chip (its picker ranks the likely kinds first), with no
row of kind chips under it. A state is said once, in one place: an
empty draft's "Write something first" is the save chip's face, and what
else needs words (Read, Save) shakes that chip rather than saying it
again in a toast. A view has one primary action, lit and wide, at every
width: in a new or open entry it is Dictate, the wide, lit segment of the
bar, then Video, a plain key, then ⋯, whose sheet holds the rest
(Duplicate, Continue, Pin, Tidy, Share, Revert, Chat, Delete last) and
presses the real buttons; the head keeps Read/Edit and the reading tools
(Aloud, Focus, Refresh). The same on the phone and the desk (research
slice C: the desk's bar was fifteen buttons of one weight, Delete cut off
at 1280), but a desk's Dictate is capped at 320px: a mouse has no use
for a thumb's width, and the spare room stays empty. Nothing covers the
bar: with an entry open the chat dock sits on the bar's top edge, so its
list and windows never hide ⋯. The head's kind badge and date are not repeated over the
title's own line.

Check: `editor.py` [one-control] (a new entry's one kind control, the save
chip's face; the bar Dictate, Video, ⋯ at 390 and at 1280, Dictate lit and
wider than the rest, at most 360px at 1440, the desk's sheet holding the
rest with Delete last; with the dock's list open at 1280 and 1920, the
point at ⋯'s centre is ⋯)
and `rules.py` [one-control] (the bar's ⋯ outside the phone's block).

## The desk reads at the body's size

On a desk (821px and wider) what is read is at `--fs-body`, 16px: a list
row's title and its two lines of text, and the reader's text; a row's
kind and time under the title at `--fs-meta`. The desk read at 13px, the
phone's caption size, where the type scale gives reading on the desk the
body's size (the analysis of 0.321.0, finding 3; research slice C). The
phone keeps its own sizes (its list row, the reader at `--fs-lead`).
The filters column beside it is not read but scanned: on the desk its
hints, kind chips and their counts, readings, view buttons and date
labels are at `--fs-meta`, nothing under it (slice E); the phone's
drawer keeps `--fs-cap`.

Check: `editor.py` [deskread] (at 1280 wide, a list row's title, text and
kind line and the reader's text computed against the tokens, no kind
badge or date in the head, and no text in the filters column under
`--fs-meta`) and `rules.py` [deskread] (the rules outside
the phone's block set the list row's sizes by those tokens).

## Words

Show the captain's words, not the database's: a kind by its name
("Personal log"), not its slug (`personal_log`); the slug
stays for search, filters' values and Details. No raw markdown where
text is read: a preview is plain text. Avoid middle-dot strings as
meta; give each fact its own place.

Where the analysis of 0.321.0 found the database still speaking (its
finding 1), slice A took it off: the editor's kind chip, the reader's
chip and `#id · 241b`, Tasks' slugs and `#1001`s, the Filters drawer's
kind chips and readings. An id stays where it is copied: the list's time
column and Details (the editor's "Number" row). A kind's slug stays in
its chip's tooltip.

The design pass's slice 1 took it off the rest (its top-five item 1): a
date older than a week is the day in words, "Thu 24 Sep, 20:00", the
year only when it is not this one (`relStamp`, `dayShort`), and an age
is words, "5 months ago" (`agoWords`: weeks to 59 days, then at least
"2 months ago", a year's second twelve months "a year ago"), never
`2026-09-24 20:00`; Reports say the title and when ("2 days ago, 18:30",
past a week `relStamp`'s "Thu 24 Sep, 18:30"), the type only when it is
not HTML, no size; Share is titled by the entry ("Share “Bike to
Snagov”"); the palette draws a row by its name and what it does apart
("Personal log" then "filter by kind": `palDraw`, a group `PAL_DOES` does
not name drawing no second word; the label, "kind · personal_log",
stays what is searched and run by name); the kind
pickers draw a kind by its name, the slug its tooltip
(`kindPickDraw`); Statistics, Readings and ambient mode name kinds by
name, Statistics has no byte readout; Resurface's toast says "From 4
months ago, Tue 30 Jun" with Another; Templates show their headings, not
a size; Media's tiles, the stack's panels and select mode's rows carry
no id, and the Join and Delete confirms list each entry by its title,
its kind by name and when (`pickLine`), and say "Deleted entries can be
brought back from the toast.", never `deleted = 1`; Readings' rows add
"+ chart", the dialog's own word; What's new dates a release "Sat 24 Oct"; Match options say "Match
case", "Whole words", "Not matching"; the search says "Search the
journal"; the filters' date section is "Written"; Kinds by role counts
"entries"; the offline capsule's facts are apart. An id stays where it
is copied: Details, and the list's rows outside select mode (the
captain's condition of 0.314.0, which the design pass's report would
have lifted: the captain's to decide).

Tasks follow it too (the design pass's slice 2, its top-five item 2): a
row is a 44px tick (`.tktick`, a ring in the kind's colour, filled green
with a check once done) beside a button that opens the entry; the line at
the body's size, two lines at most, without its marker (the section bar names
it, "To do" with its count apart); the kind by its name in its colour, no
badge; the age in words (`agoWords`), amber from 60 days (`TASK_OLD`),
never a date. The tick writes the reader's own write (`setTaskWord`):
the row is ticked in the tap, the toast says "Done: <line>" with Undo, a
failure rings the row again and says so on it, the tick its Retry (an
unsaved edit in the way: "save or revert your edit first"); a refusal
draws the board again; on a done row it opens the line again. Check: `tests.js` [words] and "the
tick"; `targets.py`, each tick 44px each way and apart from the row's
button.

The version follows the same rule. The one under the clock (`#appVer`)
shows always: a stale cached page must be visible. The floating one
(`#verMark`, top centre over the screens that cover the header) shows
only while the page is stale, `body[data-stale]`, set by `updPaint` when
the server's version is newer, and then amber. Offline, or with the
check failed, it stays hidden. Later puts off the offer (the header's
arrow, the toast, the Later button) for that version; it does not hide
the mark, because being behind is a fact, not an offer.

Check: `tests.js` [words] (a list row names its kind and carries no byte
count; the editor, the reader, Tasks and the filters drawer show no slug,
`#id`, byte count or ISO date outside Details; then Statistics, Share,
Templates, What's new, the stack, ambient mode, Match options, the
search's placeholder, select mode's rows, the Join and Delete confirms
and an old entry's reader;
Reports, Resurface, Media, the palette, the kind pickers, Readings and
the offline capsule where those are tested; `relStamp`'s and
`agoWords`'s forms). The version: `buttons.py`'s version pass (a current
page shows no floating mark on any covered screen, a stale one exactly
one version on each, Later set) and `test/update.py` (the mark lit
amber while stale, hidden after the update and when the check fails).

## Facts apart, never dotted

A line of several facts ("242 entries on 85 days", "busiest 03 Sep with
8", "done") gives each its own span in a `.facts` row, set apart by the
row's gap (`factsHtml`), never one string joined by " · ". A count on a
head or a button is a fact beside its label (`.bln`, a pill's own count),
and a button says what it does ("Show 262", not "Done · 262"). The
analysis of 0.321.0 found the dots on the sidebar, the month and the
drawer (finding 5); slice E split them.

Check: `targets.py` [dots] (no visible text outside an entry's own holds a
middle dot, on every view targets.py walks at the phone and the desk's
list, reader, editor and month; the palette's notes, "kind · task", an
expected failure in `UNTIL`, any other dot there failing). Elsewhere
(tooltips, the chats' threads) the reviewer reads for them.

## Hints by device

A hint is for the device in hand (the review's finding 7). Key hints (⏎,
Tab, ↑ ↓, a letter) are for a screen with a keyboard and a pointer that
hovers; a touch screen gets what a tap or a gesture does instead, or
nothing. Decide by the media query, not the width: a narrow desk window
still has keys, a tablet on its side has none.

- Mark the keyboard's text `class="kbonly"` and the touch screen's
  `class="touchonly"`; the CSS (`@media (hover:none)`) hides the other.
  A picker takes `hint` (the keys) and `touchHint` (the tap).
- In script, `noKeys()` asks the same question. Help opened from a button
  is `helpDoor()`: the keyboard sheet with keys, the gestures and the
  voice orders without. A key, or a row named "keyboard shortcuts", still
  opens the keys: it was asked for by name.
- A view's filters do not stand between the screen's top and its first
  result on a phone: past one row they fold behind one line that names
  what is picked (Tasks' `#tkfold`), so a filter at work is never out
  of sight, only its controls are.

Check: `tests.js` [hints] (the help a button opens on a touch screen, the
pickers' two hints) and `targets.py` [hints] (no key hint shown on a touch
screen outside `.kbonly`).

## Text from outside

A page written from the web (a report's HTML, docs/design/reports-as-entries.md)
is never markup in the console: in the reader it is a `srcdoc` frame with
`sandbox=""` - no script, no same origin, no popups - so nothing in it can
reach the API's password, the classified block or the page's storage; one
that needs its script opens in the report viewer, served under the server's
own sandbox header. In a list it is never its source: a preview names the
type, and `plainPreview` drops a `<style>` or `<script>`'s text with the tags.

Check: `tests.js` [outside] (an HTML report framed in the reader with
`sandbox=""`, its text the frame's document; a list's preview naming the type).

## No colour literals outside :root

A colour is a token: `var(--amber)`, never `#fc6` or `rgba(…)` in a rule.
A new colour is a named token in `:root`, added to `audit.py`'s contrast
list first: 4.5:1 for text, 3:1 for borders and controls (WCAG 1.4.3,
1.4.11). The tokens are where contrast is checked; a literal is a colour
nobody checked.

Slice E brought the 130 literals into `:root`: the neutrals by name
(`--well`, `--panel3`, `--line2`, `--soft`, …), the tinted ones by their
one job (`--heat1`, `--pick`, `--alert-red`, …), and the see-through ones
on a ladder per hue (`--black-70`, `--orange-15`: the number the alpha in
hundredths). `--ink` is the black of text on a lit fill, apart from
`--bg`. A new alpha takes the ladder's nearest step.

Check: `rules.py` [colours] (no hex or rgb() outside `:root`) and [census].

## Radii on the ladder

A radius is a token: `--r2` to `--r28` on even steps, `--rpill` for a
stadium, or 0 or 50%. The page had 58 radii, odd pixels among them (3, 5,
7, 9px beside 4, 6, 8, 10): each a local choice. A shape still combines
them (`0 var(--r10) var(--r10) 0`, a pill's round right end).

Check: `rules.py` [radii] (no length in a radius outside `:root`) and
[census] (the distinct radius values, shapes included, pinned).

## The literal census does not grow

The distinct literal colours, radii, paddings and font weights in the
page are counted, and a change that adds one either reuses a value that is
there or names the new one here with why. One component with 14, 16 and
20px of padding is three sessions each choosing locally: drift.

Check: `rules.py` [census] (each count pinned at today's in `CENSUS`; a
change that lowers one lowers its pin).

## Reuse before building

A new button, chip, sheet, toast or empty state uses the class that is
there (`.pill`, `.kc`, `.dlg`, `#toast`, `.empty`). A new variant is a
change to this file first, saying why the old one would not do.

Check: none can be written: whether a new control should have been an old
class is a judgement. The reviewer names the class each new control uses.

## Every touched view has its states

A view a change touches is drawn in each of its states: empty, loading,
failed (with Retry where it failed), offline, and with a very long title.
The happy path is the one the builder sees; the others are the ones that
go missing.

Check: none yet, in general: a view's states are its own (`test/offline.py`
holds the offline ones, `tests.js` the empty search). The reviewer asks for
`shots.py` frames of each state of the touched view.

## Hover is never the only way

A tap on iOS applies `:hover`, and it stays until the next tap elsewhere:
the last pill pressed looks selected, Delete looks armed. So a `:hover`
that paints a state sits inside `@media (hover:hover)`; pressed feedback is
`:active`, focus `:focus-visible`, and both stay ungated. An action that
appears on hover is visible at rest, or in a ⋯ menu, on touch.

The pattern (slice B): the gate goes round the hover rule where it stands,
so the cascade keeps its order, and the same paint is given to `:active`
outside it, unless the control has a pressed look of its own (`.pill`,
`.kc`, `.seg button`, `.mini`, the list's `.item` on a phone):

    .tkrow:active{background:var(--panel2)}
    @media (hover:hover){ .tkrow:hover{background:var(--panel2)} }

A tap then lights the control while the finger is down (the captain's
"immediate feedback") and lets go of it after; a mouse sees no change.

Check: `rules.py` [hover] (every `:hover` selector inside a
`(hover:hover)` block; and every one that paints, not reveals, has an
`:active` for its element).

## Every drag has a button

Every drag has a way without dragging, and every path or two-finger
gesture a single tap (WCAG 2.5.7 AA, 2.5.1 A). The list, each with what a
tap or a key does instead; a new gesture is a new row:

| Gesture | Its tap |
|---------|---------|
| The calendar: an entry dragged to another day or time | `#e_start_date` (Details' start, in the entry the tap opens) |
| The day grid: a block drawn or its edge dragged | `#e_end_date` (Details' end) |
| The course map: pinch, two-finger turn | `crsNorth` (the needle: upright again; Leaflet's + and −) |
| The course sheet dragged by its head | `crsSheet` (a tap on the head steps it) |
| New: a hold or a slide up for the speed dial | `#edactions` (the new entry's bar: Dictate, Camera, Attach, Record) |
| The rail: a drag through the days | `railGo` (a tap on a day's label) |
| The list: pulled down to sync | `#bReload` |
| A statistics chart: a drag across it to zoom | `xpSetRange` (a tap on a row of its table) |
| The toast: swiped away | `hideToast` (a tap dismisses it) |
| The desk's columns: a grip dragged to a width | none yet (a double click resets it; no key or tap sets a width) |

Check: `rules.py` [drag] (each row's tap exists in the page; a "none yet"
row is expected to fail until it has one).

## A focused field is never covered

After a field takes the focus its box lies inside the visual viewport and
under no fixed or sticky element of the page's own: the foot, the toast,
the tape deck, the action bar (WCAG 2.4.11). iOS pans to the field; the
page must not then cover it.

Check: `keyboard.py` [focus] (every field it focuses at a phone's size:
its middle is the topmost element there, inside `visualViewport`).

## No bare 100vh on a full-height shell

`100vh` is the height with the toolbars hidden, so in a Safari tab the
foot of a full-height shell sits under the toolbar. Write `100dvh` (or
`svh`), with `100vh` before it only as the fallback.

Check: `rules.py` [vh] (no rule with a bare `100vh` whose selector has no
`dvh`/`svh` height, in its body or an `@supports` block; the desk's chat
dock (`#dock`, `.dkwin`) is the one left today: expected to fail until a
slice takes it, unscheduled as yet, the analysis's finding 9; the list is
pinned).

## Reflow at 320px

No sideways scroll at 320 CSS px wide (WCAG 1.4.10): an iPhone SE, or a
phone with the text made larger.

Check: `targets.py` [reflow] (every view it walks at 320x640: the page
no wider than the screen).

## Label in name

A button's `aria-label` starts with the words it shows, so "tap Graph"
by voice control finds the button whose label is "Link graph… " only if
the label begins "Graph" (WCAG 2.5.3).

Every width: the header's pills, the rails, the reader's toolbar and the
list's day bars name themselves "Graph: the link graph", "Read day: Fri
25 Sep 2026 as one text block"; a toggle keeps its one name ("Sound") and
says its state with `aria-pressed`. A key hint shown only to a keyboard
(`.kbonly`) is not part of the label.

Check: `rules.py` [label] (the markup's labelled buttons; `LABEL_OK` leaves
out the classified pill, whose name the classified block sets) and
`axe.py` [axe] (axe's label-content-name-mismatch on the rendered screens,
the script's names included; the list's rows, the chats' rows and the
month's days are cards, named by their title or date, left by name in
`AXE_LEFT`).

## axe finds nothing

axe-core (WCAG 2.2 A and AA) finds no violation on the phone's six screens
and the desk's views: every field and select has a name, nothing hidden
from a reader takes focus (a shut menu is `inert`), every ARIA attribute is
one its role allows, with a valid value.

Check: `axe.py` [axe] (the phone's list, reader, editor, ⋯ sheet, filters
drawer and month at 390x844 with touch; the desk's list, reader, editor, a
new entry, the month, Tasks, Statistics, the chats, the help, the palette,
Reports and the graph at 1280x800; what is left is in `AXE_LEFT`, each
with why, and one no longer seen fails, so the list only shrinks).

## Uppercase only in Antonio

`text-transform:uppercase` is the display face's, the LCARS chrome's. The
sans and the mono are never shouted, and no tracked eyebrow sits above a
heading.

Check: `rules.py` [uppercase] (no uppercase rule that sets the sans or the
mono) and `targets.py` [uppercase] (every visible uppercase text on the
six screens is in Antonio, computed).

## Antonio in one casing

The display face is uppercase, as the brief has it: a pill, a chip, a
label, a section bar. "Select" and "Day" beside SAVE and FILTERS was two
casings (the analysis's finding 5). The captain's own words keep theirs
(an entry's title, a heading in its text, a file's or a crew member's
name), and a numeral or a date has none to shout; each such rule is named
with why in `rules.py`'s `CASE_OK`.

Check: `rules.py` [casing] (every rule that sets `--disp` uppercases it,
but `CASE_OK`'s) and `targets.py` [casing] (no visible text in Antonio
left in lowercase, computed, on the phone's six screens and the desk's
four).

## No entrance motion

Motion answers an action: a sheet rising when it is opened, a saved
chip's pulse, the transporter when an entry is deleted. No fade-up or
slide-in on a view, a row or a load. The one exception is the brief's: the
console's power-up on load (the header's strip, the section bars), once,
behind `prefers-reduced-motion: no-preference`.

Check: `rules.py` [motion] (the animated rules pinned at today's count, a
new one named here with its action; none on a row or a view).

## Buttons say what happens

A button says what it does: "Save", "Delete entry", "Send", never "OK",
"Submit", "Yes". The result keeps the name ("Saved"). An error says what
to do next, with no code and no apology.

Check: `rules.py` [verbs] (every `lcarsConfirm` and `lcarsPrompt` names its
button with `ok:`; no button reads OK, Submit, Yes or No). The reviewer
reads every new string.

## Toolbar tint by background

Safari 26 tints its bars from the page's background and any fixed element
at the very top, not `theme-color` (practitioners' reports; no Apple
source). The `html` and `body` background is the frame's black on
purpose, and so is `theme-color`, so both agree.

Check: `rules.py` [tint] (`html`/`body` painted black, `theme-color` black).
Not checked on an iPhone: Playwright's WebKit has no toolbar.

## Named tells

The defaults a model slips in, by name, for the reviewer to look for; a
new one that slips in is added here. Not tells, because the brief owns
them: uppercase Antonio, the black field, the numbered section bars, the
elbows. Tells: a middle-dot meta string; a Unicode glyph as an icon; a
fade-up on a view; an icon in a tinted square; "→" on a button; a
tracked eyebrow over a heading; one component with three paddings; a
mono label; a hover-only action; a slug or an id where a name belongs.

Check: none of its own: the list is the reviewer's, and each tell a test
can see is a rule above with its check (middle dots outside the screens
`targets.py` walks are the reviewer's to read for).

## Every rule ships with its check

A rule here names the test or audit that fails when it is broken, on a
`Check:` line under its heading, the file and the rule's `[slug]`
(`rule:<slug>` in that file, `[slug]` on rules.py's lines). Where no check
can be written the line says `none` and why. A check that fails on today's
code for a rule a later slice fixes is written anyway and marked expected
to fail until that slice (`until=` in rules.py, `xfail(…)` in tests.js):
it passes the run, and fails as soon as it holds, so the slice removes the
mark. Beside it, what is wrong today is pinned (a count, or the list of
rules or buttons by name), and a change that adds to it fails at once:
the expected failure does not hide a new break until its slice lands. Rules without a check are the ones that leaked (the analysis of
0.321.0: Words, Hints by device, one primary action).

Check: `rules.py` [checked] (every heading here has a Check line, and each
file it names holds the slug).

## Keep

From the review, not to be changed by any slice: the colours and their
contrast (`--dim` on black is 7.2:1), the day bars, the desk sidebar's
elbow and numbered section bars, the coloured bar segments (Media &
files, Camera, Attach, Record), the reader and its Standby pane, the
empty search state, reduced motion, `:focus-visible`, `aria-live`, the
safe areas, tabular numbers, 16px inputs, the immediate-feedback rule
(CLAUDE.md), and the chat lists' structure.

Check: `audit.py` [keep] (the colours' contrast, reduced motion,
`:focus-visible`, `aria-live`, the safe areas, 16px inputs, dvh).

## Way back

The captain may want today's look back, so the review's slices are
built to be reverted, one by one. There is no feature flag: two type
systems in one CSS is what slice 3 removes.

- **The pre-review look is main at `1fc2c5d2` (0.313.2).** Anything the
  review changed can be compared with, or restored from, that commit:
  `git show 1fc2c5d2:lcars-ui/index.html`.
- Each slice is its own commit titled `UI review slice N: ...` (slice 3
  two, one per pass), with nothing else in it, and the deploy
  fast-forwards, so each sits on main as it was built. Find them with
  `git log --oneline --grep='UI review slice' main`.
- To take one slice back: `git revert <its commit>` on an engineer's
  branch, a placeholder CHANGELOG entry (`## next patch`) saying which
  slice was reverted and why, then the usual deploy. Revert later slices
  first when they touch the same lines (slice 3's passes rewrite sizes
  slices 1 and 2 set): `git revert <slice 3b> <slice 3a> <slice 1>`
  undoes them newest first in one go. A conflict in `CHANGELOG.md` is
  resolved by keeping both entries; one in `index.html` means a later
  commit edited the same rule, and the slice's own diff
  (`git show <commit>`) says what the old line was.
- This file, slice 0, stays when slices are reverted: it is the rules,
  not the look. Edit its sections to say what was taken back.

Check: none: a way of working (one commit per slice, reverted newest
first), not a property of the page; `git log --grep` is how it is seen.
