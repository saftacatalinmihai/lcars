---
title: Social watch
schedule: *-*-* *:20:00
kind: script
script: social
min_free_mb: 100
lock_wait: 900
timeout: 240
hn_user:
github_user:
github_repos:
cf_sites:
---
No model. scripts/crew.py run_social, scripts/social.py (docs/design/social-watch.md): every hour, the new
comments on the captain's accounts and, once a day, their numbers. Read only: nothing is ever posted to a
platform. The names are this front matter's, which crew/context.local.md sets for the box: `hn_user` (Hacker
News, through Algolia's public API), `github_user` and `github_repos` (names, or owner/name; the box's `gh` login,
or LCARS_SOCIAL_GITHUB in ~/.env), `cf_sites` (`name=<site tag>` pairs: Cloudflare Web Analytics, bots excluded,
with LCARS_CF_ANALYTICS_TOKEN, else CLOUDFLARE_API_TOKEN, and LCARS_CF_ACCOUNT_ID or CLOUDFLARE_ACCOUNT_ID). A
platform with none is skipped and said so.

Writes, with the crew login: `crew_social_comment`, one per new comment (its `id:`, link, author and text; done
when the captain has replied), seen in the journal so nothing repeats; `crew_social_<platform>` (hn, github, cf),
one reading a day for the day before, value_int the main count (points, stars, visits); one `task_crew_social`
reminder per run that finds comments the captain has not answered; and the run's own `crew_social`, only when something
happened. A platform failing three runs in a row raises one `task_crew`.
