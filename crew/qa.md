---
title: QA, nightly suite
schedule: *-*-* 01:40
kind: script
script: qa
min_free_mb: 1000
timeout: 1200
---
No model. scripts/crew.py run_qa: the web suite (`PERF=0 KB=0 lcars-ui/test/run.sh`) on the committed tree of
the live checkout, unpacked into a scratch directory, against a copy of the newest hourly backup. The keyboard
and frame-budget stages need Chromium with playwright, which the box does not have, and skip themselves.
URGENT when the suite fails.
