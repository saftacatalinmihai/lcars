# Open questions: the shape of an ask

Number One's questions (`task_no1`, `no1.py escalate`) and the crew's
urgent asks (`task_crew`) are answered in the console's Open questions
(`openQuestions`, `./questions`, key `!`). Since 0.279.0 the page splits an
ask written in this shape into its questions, each answered on its own, and
one Send closes it (`oqParse` in `lcars-ui/index.html`).

```
title:   Pins and the old view            (the card's heading)
content:
The deck test is green; Sato built both.  <- shared context: all before Q1
                                             (folded on the card)
Q1: Ship the new pins today?              <- a question begins
The phone check passed on the iPhone.     <- its own context
Options: A) ship now B) wait for the iPad C) drop them
Recommendation: A, it is tested.          <- the default, marked; the line
                                             stays as context (the reason)
Q2: Keep the old view?                    <- no Options: Yes / No
Only the menu used it.
Recommendation: no
```

- A question begins at a line `Q1:` (also `Q1.`, `Q1)`, `**Q1:**`). With
  no Q lines, `1.`/`2.` lines are questions only when they run 1, 2, 3…
  and every one has a `?`, so a numbered list in the context stays context.
- `Options:` lists the choices inline (`A) … B) …`) or on the lines under
  it (`A) …` one per line); letters A to H.
- `Recommendation:` (or `Recommended:`, `My recommendation:`) names a
  letter, `yes` or `no`; anything else marks nothing.
- Every question also has Skip. An ask with no Q lines but an `Options:`
  line is one question, its title the text. Anything else is the old card:
  a box, Answer and close.

## The answer

Send, enabled when every question has a choice or Skip, puts one block at
the top of the content and ticks the entry done, with the guarded PATCH
(`if_modified`):

```
Answer (captain, 2026-10-20 09:14):
Q1: A (ship now); note: after the phone check
Q2: no
Q3: skipped

<the ask as it was>
```

Undo takes the block off (if it is still there as written) and opens the
ask again, the choices back on the card. The choices and notes are kept on
the device per entry and question (`lcars.oqAnswers`) until Send.

`engineer.py`'s `no1_answers` (in `reap`, every five minutes) types each
`task_no1` newly done to Number One as `[captain] ticked off your question
#<id>: …` with its notes; `answer_notes` sends the Answer block whole and
clips only the context under it, so every question's answer arrives.

Voice: "answer question 2 yes, after lunch" (yes, no, a letter, skip or
recommended; the rest is the note) on the top card in the shape, and "send
the answers" for the first ask answered in full.
