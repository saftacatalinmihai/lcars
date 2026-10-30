# A context refresh, for Number One and any engineer

*As built in the change that added `engineer.py refresh <name>` for every
engineer (it was Number One's alone).*

A crew member's conversation grows with every turn and costs tokens on
each; past the handover mark (`ENG_CTX_HANDOVER`, 200k, the console's
context gauge) it is time for a fresh one. A plain clear forgets what they
were doing. A refresh is the three steps in one: a handover, the clear, the
handover carried into the fresh conversation.

## One flow (scripts/engineer.py)

- `refresh <name>` (also `POST /engineer/<name>/refresh`, `no1.py crew
  refresh <name>`, the console) refuses what clear refuses: not on duty, a
  question on their screen. It records `refresh: {at, ...}` in their state
  and types the `[refresh] (refresh #<at>) ...` line (`refresh_text`).
- An engineer **out of the seat** (on the seat's roster, not running) gets
  the line in their inbox, as `say` queues an order (`seat_want`); the
  answer says so (`queued: true`). It lapses after 12 hours, not 15
  minutes: the line can be long.
- The **Stop hook** of a turn ends in a clear only if that turn wrote the
  handover. Number One's handover is an entry in its log titled Handover
  (`no1.py log` calls `refresh_noted`). An engineer has no log: theirs is
  the last message of the turn that read the `[refresh]` line - its mark,
  `(refresh #<at>)`, in a message of the transcript, read as `room_marks`
  reads one (`refresh_seen`). A turn already under way that never read it
  ends as any turn does, with no clear.
- **refresh-go** (detached) files an engineer's handover as the turn's
  message, as the hook would have (`turn_deliver`, synchronously, for its
  `crew_msg` id), waits up to two minutes for them to be idle, clears
  (`clear_session`, the old conversation named after its task) and types
  the fresh one: Number One, "read your log"; an engineer, the handover
  itself (`refresh_handover_text`), its row's id, cut at 6000 characters
  with the pointer when longer. The fresh turn holds the seat on; if the
  clear or the typing fails, Number One is told and the seat moves on
  (`refresh_seat_on`).
- Every step is a line in `logs/refresh.log`.

What a fresh engineer is typed:

> [refresh] Your conversation was cleared for a fresh context. Below is
> the handover you wrote at the end of the last one. It is kept whole in
> crew_msg #N (`.../engineer.py room number-one show N`). Carry on from it;
> if it says the work is done, answer in one line and start nothing new.
>
> *(the handover)*

The old manual way (ask for a handover, `crew clear`, `crew say` it back)
still works.

## The console

`engRefresh(name)` is the one door, for Number One and every engineer: the
thread's ⋯ *Refresh context* (greyed at a question; for Number One also
off duty, for an engineer only when dismissed: one off duty gets it in
their inbox), the context gauge past the mark (a control then, asked first
in the sheet), "refresh number one" and "refresh engineer {name}" /
"refresh this engineer". The thread says "Refreshing the context…" at once,
then the script's note or why not.

Tests: `scripts/test_no1.py` (`Refresh`, `EngineerRefresh`), the behaviour
suite (the sheet row, the gauge, the orders).
