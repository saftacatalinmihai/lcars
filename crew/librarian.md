---
title: Librarian, docs against code
schedule: Sat *-*-* 02:40
model: sonnet
verbs: today docs
read: repo
budget: 0.50
timeout: 900
---
Every Saturday, check that the docs still describe the code. You change nothing; you list what is wrong.

1. Run `docs`. For each doc (CLAUDE.md, AGENTS.md, ARCHITECTURE.md, README.md, TODO.md) it shows when it last
   changed and which code files changed since.
2. Pick the claims most likely to have gone stale: those about the files that changed most since the doc did.
   Check each against the code with Grep first, then Read only the lines you need (offset and limit), never a
   whole long file. At most twelve claims and about twenty tool calls: every call re-reads the conversation.
   Good targets: routes and filters in ARCHITECTURE.md's HTTP table, Makefile targets and test commands in
   CLAUDE.md, module names in the module map, TODO.md items that the CHANGELOG says are done.

Report:
- One line per stale claim: "**ARCHITECTURE.md**, <section>: says X; the code (`file:line`) does Y."
- One line per TODO.md item that is already done, with the CHANGELOG version.
- One line: what you checked and found accurate.
At most fifteen findings. Never URGENT.
