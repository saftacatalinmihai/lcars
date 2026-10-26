# The landing page: hosted LCARS's waiting list

One Cloudflare Worker: `public/` is the page, served as static assets, and
`src/worker.js` answers `POST /api/signup` into a D1 table (`schema.sql`).
No mail is sent from it; the list is read with `list-signups.sh` when
hosted LCARS opens. Nothing account-specific is in this folder: the account
and token come from the environment, the database id and the custom domain
from `LCARS_LANDING_D1_ID` and `LCARS_LANDING_HOST` when deploying.

| file | what |
| --- | --- |
| `public/index.html`, `landing.css`, `landing.js` | the page: the pitch and the form above the fold, the explainer, Try the demo, the features with real shots, self-host beside hosted, the form again, the privacy note |
| `public/_headers` | the CSP (scripts and connections to the page's own origin only), nosniff, the caches |
| `public/plausible-init.js` | Plausible's queue and init stub, staged and named in the pages only with `LCARS_LANDING_PLAUSIBLE` (below, "Visits") |
| `public/video/` | the deck and crew loops (the explainer is on R2, below; a local copy here, ignored, plays in the preview) |
| `public/shots/` | console shots from the public demo (`lcars-ui/demo/static.py`, made-up entries), the deck's from `docs/bridge.webp` and the explainer's stills |
| `public/fonts/` | Antonio (OFL, `OFL.txt` beside it), as the console uses |
| `src/worker.js` | the signup route: validation, the honeypot, a per-address rate limit, closed CORS |
| `schema.sql` | `signups` (email unique, use, consent, created) and `rate` (a salted hash of the address and a time, kept an hour) |
| `preview.mjs` | a local preview with nothing installed (node, an in-memory D1) |
| `public/og-card.jpg` | the share card, 1200x630 (`card.py` draws it again) |
| `deploy.sh`, `list-signups.sh` | the captain's, by hand: publish, and read the list |

## What a signup is

`POST /api/signup`, JSON (`{email, use, consent, website}`) or a plain form
(the page without its script: answered by a 303 back to `/?signup=<outcome>#join`).

- **email**: required, trimmed, lower-cased, at most 254 characters, one
  `@` and a dotted domain. Unique: a second signup of an address is answered
  exactly like the first (no one learns who is on the list) and keeps the
  first line.
- **use**: optional, at most 280 characters, control and bidi characters
  taken out.
- **consent**: must be ticked.
- **website**: the honeypot, hidden from people. Filled, the answer is
  `{ok: true}` and nothing is written.
- **Origin**: a browser's POST from another origin is a 403; no
  `Access-Control-*` header is ever sent.
- **Rate**: five signups from one address in ten minutes, then a 429 with
  `Retry-After`. The address is kept only as `sha256(RATE_SALT|ip)`, for
  an hour (`RATE_SALT` a Worker secret; a constant without one).
- Bodies over 4 KB are a 413, another content type a 415.

## Preview and tests

```sh
node site/landing/preview.mjs            # http://127.0.0.1:8790/
node --test site/landing/test/           # the worker's contract (~1 s)
python3 site/landing/test/page.py        # the page in Chromium at 393x852 and 1280x800 (~15 s)
python3 site/landing/test/page.py --shots DIR
python3 site/landing/test/deploy.py      # deploy.sh --dry-run with npx stood in for (~2 s)
LCARS_TEST_WRANGLER=<wrangler 3 bin> python3 site/landing/test/deploy.py   # wrangler's own dry run
```

The share card's tags (`og:url`, `og:image`, `twitter:image`, the
canonical link) must be absolute for the scrapers, and the host must stay
out of the tree: the pages say `__SITE__`, which `deploy.sh` replaces with
`https://$LCARS_LANDING_HOST` in the staged copy it uploads, and the
preview with its own origin. The explainer's address the same way:
`__EXPLAINER__`, `$LCARS_LANDING_EXPLAINER_URL` at a deploy, the local
`/video/explainer.mp4` in the preview.

The real runtime and a local D1 (wrangler 3: the box's Node is 20, and
wrangler 4 wants 22). A copy of the config with any id stands in:

```sh
cd site/landing
sed s/LCARS_LANDING_D1_ID/00000000-0000-0000-0000-000000000000/ wrangler.toml > .wrangler.deploy.toml
npx wrangler@3 d1 execute lcars-landing --local -c .wrangler.deploy.toml --file schema.sql
npx wrangler@3 dev --local -c .wrangler.deploy.toml
```

## Publishing (the captain's)

Never an engineer's: a deploy, a database or DNS is the captain's call.

```sh
set -a; . ~/.env; set +a                                   # CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
cd site/landing
npx wrangler@3 d1 create lcars-landing                     # 1. prints the database_id
export LCARS_LANDING_D1_ID=<that id>  LCARS_LANDING_HOST=lcars.<the zone>
export LCARS_LANDING_EXPLAINER_URL=<the licensed cut's https URL on R2: "The explainer", below>
sed s/LCARS_LANDING_D1_ID/$LCARS_LANDING_D1_ID/ wrangler.toml > .wrangler.deploy.toml
npx wrangler@3 d1 execute lcars-landing --remote -c .wrangler.deploy.toml --file schema.sql   # 2. the tables
npx wrangler@3 secret put RATE_SALT -c .wrangler.deploy.toml   # 3. any long random string (after the first deploy, or it makes the worker)
./deploy.sh                                                # 4. the worker, its assets, the custom domain (again for a new cut)
./list-signups.sh                                          # the list, read-only
```

The custom domain (`custom_domain = true` on the route `deploy.sh` adds)
makes the DNS record and the certificate itself; the zone must have no
record of that name already.

## Visits

Off unless a deploy is given `LCARS_LANDING_PLAUSIBLE`, which counts them
with Plausible Analytics (no cookie, no personal data kept: its data
policy) - never Cloudflare Web Analytics, whose injected beacon the CSP
refuses. Its value is either the Plausible site's domain (the classic
`https://plausible.io/js/script.js` with `data-domain`) or the site's own
script URL from Plausible's Site installation page,
`https://plausible.io/js/pa-<id>.js` (the script since October 2025; the
snippet's inline init is `plausible-init.js`, the CSP having no
`'unsafe-inline'`). With it, `deploy.sh`'s staged copy has, before every
page's `</head>`, the stub and the tag (both `defer`, after `landing.js`);
`script-src` and `connect-src` in `_headers` with `https://plausible.io`
added, nothing else; and the privacy note's "No tracking, no cookies, no
analytics" replaced by a line naming Plausible. A successful signup sends
a `Signup` custom event (the name and the page, nothing typed); Plausible
counts it once a `Signup` goal is added to the site. Without the variable
the stub is not uploaded and nothing of Plausible is in a page or the CSP.

```sh
# Plausible: add the site (Sites, + Add website: the landing's host), then Goals, + Add goal, custom event "Signup"
echo 'LCARS_LANDING_PLAUSIBLE=lcars.<the zone>' >> ~/.env   # or that site's https://plausible.io/js/pa-<id>.js
set -a; . ~/.env; set +a; site/landing/deploy.sh
# Cloudflare: the zone's Web Analytics (Analytics & Logs), the host's automatic setup off
```

## The explainer

The figure plays the licensed cut (the captain's Suno Pro track). It is
not in the tree - its music is licensed, the repo MIT - and not a Worker
asset either: Cloudflare's static assets answer a Range request with the
whole file (200), and Safari plays an mp4 only from a server that answers
206, so the iPhone would show a dead player. It is served from the
captain's public R2 bucket (the demo's), which answers ranges, under a
name carrying its hash so a new cut never meets an old one in a cache:

```sh
set -a; . ~/.env; set +a
h=$(sha256sum CUT.mp4 | cut -c1-8)
npx wrangler@3 r2 object put test/lcars-landing/explainer-$h.mp4 --file CUT.mp4 --content-type video/mp4
u=<the bucket's public base, the demo's host>/lcars-landing/explainer-$h.mp4
curl -sI "$u"                          # 200 video/mp4, accept-ranges: bytes
curl -s -o /dev/null -D - -r 0-1 "$u"  # 206, content-range: bytes 0-1/<size>
LCARS_LANDING_EXPLAINER_URL=$u site/landing/deploy.sh   # or that line in ~/.env
```

`deploy.sh` refuses a URL that is not https, does not end `.mp4` or has a
character a plain path does not; the page's CSP already allows it
(`media-src 'self' https:`). A copy at `public/video/explainer.mp4`
(ignored, never uploaded) plays in the preview. The page loads none of it
until play is tapped. The cut with the free-tier music bed must never be
used here.

The deck and crew rows' loops (`public/video/loop-*.mp4`, silent, 960x540)
are Kim's hero loops made small; landing.js loads each when its row nears
the screen, plays it muted and inline, and pauses it off screen.
