---
title: Science, weekly stats
schedule: Mon *-*-* 04:40
model: sonnet
verbs: today weekstats stats list
budget: 0.30
timeout: 600
notes: today list get stats weekstats
---
Every Monday, the numbers of the week that ended yesterday, against the week before.

1. Run `weekstats` (no argument: the seven days ending yesterday, and the seven before). The arithmetic is done
   there; use its numbers, do not recompute them.
2. Only if a number needs explaining (a gap, an outlier), one or two `list` calls on that day or kind.

Report:
- **Sleep**: the captain's average hours, against last week; the shortest night with its day. Then
  one line from weekstats' bedtime: the average time of the captain's last entry of the evening, beside the sleep, against
  the week before (e.g. "Last entry of the evening 00:45 on average, 7.3h of sleep; the week before 23:50, 7.8h").
  Only what the numbers say: no advice, no "should", no link drawn between the two.
- **Writing**: entries and words, the busiest day, which kinds rose or fell.
- **Driving**: total minutes, if any. The `<kind:drive>` count by kind includes start rows; the drives are
  weekstats' measured ones.
- **Gym**: sessions and total minutes, if any.
- One line: the most notable change, stated as an observation, not advice.
Leave out a section with no data. Never URGENT.
