# The keyboard help (?): searched, and run from

The `?` key (`openHelp`, `./help`, the voice orders "keyboard help" and
"find the shortcut for …") opens every line of `KEYS` as a list to learn
from and to run from. Built 2026-10-23 (the captain's order: "searchable, so
I can find shortcuts and learn them, and run them in the help directly,
like the command palette").

## What it does

- A search box on top: focused on a desk, not on a phone (`deskFocus`:
  the keyboard would cover the list a first look is for; the focus starts
  on Close). Every word typed must turn up, as typed, in the key, the help
  text or the section's name (`keyMatch`); the matched run is marked, as
  the palette marks its. Not fuzzy: a subsequence of three letters is in
  nearly every one of these long lines.
- The ranking: a key the query is (case kept: `K` is the kind picker, `k`
  the previous entry), then a key the query is in, then the table's order.
- With an empty query the sections are headings and the list reads as the
  old sheet did; with one, it is flattened to the matches and each row
  says its section.
- A row with a `fn` runs it on Enter or a tap, the help closing first (a
  key that opens a dialog opens its own). A row whose `when` says no is
  dimmed with its `need` ("not now · with an entry open") and is never
  hidden, so it can still be learned; Enter on it runs nothing and the
  read-out under the rows says why. Rows with no `fn` (gestures, chords,
  Esc) are reading rows: dim, and Enter says it is pressed where it applies.
- The palette's keys: ↑ ↓ (and Ctrl N / Ctrl P) move, Enter runs, Esc
  closes. One habit serves both.

## Why this shape

The help is **the palette's picker** (`openPicker`) in a keys mode, not a
dialog of its own. The picker already has the query box, the cursor, the
keys, the marking, the empty state and the close; a second dialog would
have copied all of that and then drifted from it. What a list of keys needs
and a list of names does not came in as optional hooks on the picker -
`match`, `draw`, `heads`, `can`/`cant`, `cls`, `deskFocus` (documented at
the top of "pickers") - and a picker that gives none of them is exactly the
kind picker and the palette as they were.

`KEYS` stays the one table: the rows are built from it on each paint
(`keyRows`), and the only thing added to it is `need`, the words for why a
gated key does not apply, beside the `when` it explains.
