---
title: Blog shares
schedule: *-*-* 02,08,14,20:10
kind: script
script: shares
min_free_mb: 100
lock_wait: 900
timeout: 300
---
No model. scripts/crew.py run_shares, scripts/shares.py: every six hours, the numbers of each place the blog
post was shared. The post's URL (`post:` in this front matter, which crew/context.local.md sets, or
LCARS_SHARES_POST in ~/.env) is needed only for the Cloudflare views. The captain keeps one entry of kind `share`
per place: the first URL in its content is the share, its title the place ("r/ClaudeAI"), created when the captain
posted it. Reddit (OAuth, app-only:
LCARS_REDDIT_CLIENT_ID/LCARS_REDDIT_SECRET in ~/.env), HN (Algolia) and Mastodon are read from their APIs; X,
LinkedIn and anything else from the newest line of numbers in the entry ("12 likes, 3 reposts, 800 views"),
which also stands in when an API fails. Views of the post by referer site come from Cloudflare Web Analytics
when LCARS_CF_ANALYTICS_TOKEN and LCARS_CF_SITE_TAG are in ~/.env (LCARS_CF_ACCOUNT_ID optional).

Writes a reading per share, kind `crew_share_<share id>`, and the run's own entry, kind `crew_shares`, the
global reading: value_int the main count (the sum), content a short JSON.
