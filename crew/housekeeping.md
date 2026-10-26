---
title: Housekeeping
schedule: *-*-* 00,06,12,18:00
kind: script
script: housekeeping
min_free_mb: 0
mem_wait: 0
lock_wait: 900
timeout: 600
---
No model. scripts/crew.py run_housekeeping, scripts/housekeeping.py: four times a day, the box's memory, swap
(and the cgroups holding it), /tmp (a tmpfs: RAM, then swap) and its biggest entries, both disks, the biggest
directories in home, journald, the caches and the worktrees' build outputs, measured; and only known, old
scratch deleted - what engineer.py's reap knows (Claude sessions' scratch split by reap_scratch: the
regenerable deleted, the rest moved to research/<engineer>/scratch-<date>/), engineer logs past their keep time, Playwright builds no
installed Playwright names, npx's cache unused for 30 days, crash dumps - through a guard that never touches
the captain's data, a checkout, a database file or anything a process holds. `min_free_mb: 0`: a box short of
memory is when it is wanted most.

Writes the run's own entry, kind `crew_housekeeping`, value_int the MemAvailable MB after the sweep. Past a
threshold (memory at rest under 2GB, swap over 60%, a disk over 80%, /tmp over 1GB of unknown files) it also
tells Number One, naming the biggest unknown items without deleting them. `crew.py run housekeeping --dry-run`,
or `scripts/housekeeping.py --dry-run`, deletes nothing.
