---
title: Security, weekly audit
schedule: Sun *-*-* 02:40
model: sonnet
verbs: today audit
budget: 0.30
timeout: 600
---
Every Sunday, audit the box's security posture from facts. Read-only: you report, the captain fixes.

1. Run `audit`. It prints file permissions, the backups and whether any leaves the box, cron and timers,
   listening sockets, sshd settings, pending updates, reboot state and the server's auth replies.
2. Judge it. Known and expected: the LCARS server on :8080 behind tailscale serve, the embedder socket,
   tailscaled, sshd. Secrets files must be 600 (owner only). A journal backup that never leaves the box is lost
   with the disk.

Report:
- **Findings**, most serious first, each with the fix as a command the captain can run, e.g.
  `chmod 600 ~/.env`. Include: secrets readable by others, backups with no off-box copy, security updates
  pending (count and the notable packages), reboot pending, a listener you cannot account for, password or root
  ssh login allowed, a jump in 401 replies.
- **Fine**: one line naming what checked out.
URGENT only for something exposed now (a secret readable from outside the owner, an unknown public listener,
password login on ssh). Permissions on ~/.env alone are a finding, not urgent, unless others can log in.
