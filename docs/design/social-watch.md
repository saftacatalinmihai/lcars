# The social watch: new comments and stats from the captain's accounts

This deployment's own names (the accounts, the hosts, the server's
address for the OAuth page) are in `social-watch.local.md`, kept out of
the public tree.

Status: design (2026-10-21), nothing built. Asked by Number One for the
captain (thread social-login): the ship watches the captain's social
accounts for new comments and stats and tells him, for what can be done;
for what cannot, it says so and what he can do instead.

It grows out of the shares role (`crew/shares.md`, `scripts/shares.py`,
docs/design/shares.md), which reads the numbers of each place one blog post
was shared, every six hours, from `share` entries the captain writes. The
watch is the other half: it reads the captain's **accounts** (every post,
not only the shared links), finds **new comments and replies**, writes each
one into the journal with a reply drafted in his voice, raises a notice,
and keeps one stats reading per platform per day. Nothing is ever posted
to a platform.

## 1. What each platform gives, as of 2026-10-21

Checked against the platforms' docs on 2026-10-21; where a page refused
the box (reddit's own pages answer it 403), that is said and the
secondary source named.

### 1.1 Hacker News: everything, no login

- The official API is Firebase, `https://hacker-news.firebaseio.com/v0/`:
  `user/<id>.json` (`submitted`: every story and comment of his),
  `item/<id>.json` (`kids`: the direct replies, `score`, `descendants`: the
  comment count). "No rate limit", no auth
  ([HackerNews/API](https://github.com/HackerNews/API)).
- Algolia's search API (what shares.py already uses) answers "all comments
  under story X newer than T" in one call:
  `https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_<id>&numericFilters=created_at_i><t>`
  ([hn.algolia.com/api](https://hn.algolia.com/api)). Checked from the box: 200.
- The captain's account and the item it was checked on are in
  `social-watch.local.md` (the role's front matter holds the name).
- **New comments**: on his stories (Algolia, per story of the last 30
  days), and replies to his own comments (the `kids` of each comment of his
  in the last 14 days, Firebase). **Stats**: points and comment counts per
  item. HN has no views.

### 1.2 GitHub: everything, with the token we have

- The box's `gh` login (the captain's account) has a classic OAuth
  token with `repo` scope: it reads traffic today (checked:
  `GET /repos/<owner>/lcars/traffic/views` answered).
- Stars: `GET /repos/{o}/{r}/stargazers` with
  `Accept: application/vnd.github.star+json` gives `starred_at`; forks:
  `GET /repos/{o}/{r}/forks?sort=newest`; issues and their comments:
  `GET /repos/{o}/{r}/issues/comments?since=<iso>` (pull requests too);
  discussions (GraphQL `repository.discussions`; off on lcars today).
- Traffic: `GET /repos/{o}/{r}/traffic/views`, `/clones` (daily or weekly,
  **the last 14 days only**), `/traffic/popular/paths` and
  `/popular/referrers` (top ten, 14 days); it needs write access to the
  repo ([docs.github.com/rest/metrics/traffic](https://docs.github.com/en/rest/metrics/traffic)).
  14 days is why the watch keeps a daily reading: it is the only history
  the ship will have.
- Repos: the account's public ones, listed in the role's front matter.

### 1.3 Cloudflare Web Analytics: already working

- The GraphQL API, `rumPageloadEventsAdaptiveGroups` filtered by `siteTag`,
  `bot: 0` and a datetime window, grouped by `refererHost` and
  `requestPath`; visits are `sum.visits`, page views `count`
  ([developers.cloudflare.com/analytics/graphql-api](https://developers.cloudflare.com/analytics/graphql-api/),
  Number One's log #9112). shares.py's `cf_views` is the code; the watch
  adds the bot filter, visits, and the second site.
- Two sites: the blog (its own domain, the old one and the pages.dev)
  and the public demo (social-watch.local.md has the hosts and tags).
  Zone analytics (#9104) count unique IPs with bots: not used.
- **Stats only**: visits and page views by site, page and referrer. No
  comments here.

### 1.4 Reddit: possible, but the app needs Reddit's approval first

- OAuth 2: an app at `https://www.reddit.com/prefs/apps`, the
  authorization-code flow at `https://www.reddit.com/api/v1/authorize`
  with `duration=permanent` gives a refresh token once, in the browser; the
  token endpoint is `https://www.reddit.com/api/v1/access_token`. The
  redirect URI must match the app's exactly
  ([reddit OAuth2 wiki](https://github.com/reddit-archive/reddit/wiki/OAuth2)).
  No password is stored: only the client id and secret and the refresh
  token.
- Read scopes: `identity` (his name), `history` (his own posts and
  comments: `/user/<name>/submitted`, `/comments`), `read` (a thread's
  comments: `/comments/<id>`, `/api/info` for score and comment counts),
  `privatemessages` (the inbox: `/message/inbox`, `/message/unread`, which
  carry `comment_reply` and `post_reply` items, the cheapest way to see
  every new reply at once). No `submit`, `edit`, `vote`.
- Upvotes: `score` and `upvote_ratio` per post. **Views: no.** The API's
  `view_count` is null; post views and shares are shown only in the reddit
  app's post insights.
- **The catch**: since late 2025 Reddit's Responsible Builder Policy
  requires a request and explicit approval before an app may use the Data
  API, personal scripts included; reports say small personal requests are
  slow or unanswered. (Reddit's own policy page,
  support.reddithelp.com "Responsible Builder Policy", refused the box;
  summarised from [redditapis.com, 2026](https://www.redditapis.com/blogs/reddit-data-api-2026)
  and [replydaddy.com](https://replydaddy.com/blog/reddit-api-pre-approval-2025-personal-projects-crackdown).)
  Free use is 100 queries a minute per client, far above an hourly poll.
  The box is refused reddit's unauthenticated `.json` pages already
  (shares.py, `_refused`), so there is no way round the app. And on
  2026-10-19 `oauth.reddit.com` answered a bad token from the box with
  that same 403 "Blocked" page (TODO.md, the blog shares): whether a good
  token from this VPS's address gets through is not known until one is
  tried. Slice 4's first step is that one call.
- Until approved: reddit emails a reply notice when the captain enables
  it (Settings, Notifications, Email), and the mail route (1.7) can read
  those.

### 1.5 X: the ship can read only with a separate, paid API account

- **X Premium gives no API access.** It gives the in-app analytics (X
  Analytics, `x.com/i/account_analytics`: impressions, engagement rate,
  followers, per-post numbers) and nothing the ship can call. X's help
  pages refused the box; the API's pricing page does not mention Premium
  at all ([docs.x.com pricing](https://docs.x.com/x-api/getting-started/pricing)).
- The API is now pay-per-use, no tiers and no free tier: credits bought in
  the developer console, $0.005 per post read, **$0.001 per resource for
  reads of the account's own data** (same page). "Basic" as a monthly tier
  is gone; the purchase is credits.
- What it would give: his posts (`GET /2/users/{id}/tweets`) with
  `public_metrics` (impressions, likes, reposts, replies, quotes,
  bookmarks) and, in user context, `non_public_metrics` (URL and profile
  clicks, engagements) for posts of the last 30 days
  ([docs.x.com metrics](https://docs.x.com/x-api/fundamentals/metrics));
  replies through `GET /2/users/{id}/mentions`. OAuth 2 with PKCE, scopes
  `tweet.read users.read offline.access` (read only).
- Cost at an hourly poll, his last 20 posts and new mentions: roughly 20
  owned reads and a few others an hour, a few dollars a month. The
  captain's call; the slice is last and optional.
- **Without it**, the captain reads X Analytics in the app and, as today,
  types the numbers into the share entry ("12 likes, 3 reposts, 800
  views"), which shares.py reads.

### 1.6 LinkedIn: no API for a personal post; email is the way

- A personal member's posts, comments and likes need `r_member_social`,
  which is closed: "not accepting access requests at this time". The only
  open permissions are sign-in (`profile`, `email`) and `w_member_social`,
  which writes ([learn.microsoft.com, Getting access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access),
  updated 2026-06-03). The Community Management API is for company pages.
- LinkedIn does email: Settings, Notifications, "Posting and commenting":
  comments on your posts, reactions, mentions, each with an Email switch.
  The mail names who commented, a few words of the comment, and links to
  the post.
- **The ship reads no mail today.** Searched the code (fff, every file
  but vendor/) for imap, IMAP, smtp, maildir, mbox, mailbox, notmuch,
  gmail, sendmail: nothing but a test string. A mail reader is new work:
  section 1.7.
- Stats (impressions) are the in-app analytics only: the manual line in
  the share entry, as now.

### 1.7 Mail (new): Gmail, read only, for LinkedIn and reddit's notices

- The captain's mail is Gmail. The Gmail API with `gmail.readonly` reads
  and cannot send, delete or label. One query a run:
  `from:(linkedin.com OR redditmail.com) newer_than:2d`, the message's
  subject, sender and snippet, never a body beyond what the notice needs
  ([developers.google.com/gmail/api/auth/scopes](https://developers.google.com/gmail/api/auth/scopes)).
- `gmail.readonly` is a restricted scope. An app left in *Testing* has its
  refresh tokens expire after 7 days
  ([developers.google.com/identity/protocols/oauth2](https://developers.google.com/identity/protocols/oauth2#expiration));
  set to *In production* and unverified, it works for its owner behind
  the "unverified app" screen, capped at "100 new users in total", and
  Google asks no verification of an app not launched to the public
  ([support.google.com/cloud/answer/7454865](https://support.google.com/cloud/answer/7454865)).
- Rejected: IMAP with an app password (a stored password with full access
  to the mailbox, send included through SMTP).

### 1.8 The table

| Platform | The ship can | The ship cannot | What the captain does |
|---|---|---|---|
| Hacker News | new comments on his stories, replies to his comments, points, comment counts | views (HN has none) | nothing |
| GitHub | stars, forks, issue and PR comments, discussions, views and clones (14 days, kept daily) | more than 14 days of traffic back | nothing (the gh token works); a read-only fine-grained token if he prefers |
| Cloudflare | visits and page views by site, page and referrer, bots excluded | comments | put the token in ~/.env once (3.4) |
| Reddit | new comments and replies (inbox), score, upvote ratio, comment count | views and shares (app only); anything before Reddit approves the app | make the app, file the approval request, one consent tap; meanwhile turn on reply emails |
| X | nothing with Premium alone; with bought API credits his posts' metrics and replies | read anything through Premium | read X Analytics in the app and type the numbers in the share entry; or buy credits (a few $/month) |
| LinkedIn | comments, through the notification emails (1.7) | comments or stats through an API (closed) | turn on the comment emails; one Gmail consent; type impressions in the share entry |

## 2. The shape

### 2.1 Two crew roles

The counselor (`crew/counselor.md`) is the model of a scheduled role: a
front-matter file in `crew/`, a timer `crew.py install` writes from its
`schedule:`, a run under the crew lock that posts one `crew_<role>` entry
with the crew login. The watch is two roles, so the hourly poll costs no
model:

- **`crew/social.md`, `kind: script`** (like shares: `script: social`,
  `run_social` in crew.py, the I/O in `scripts/social.py`), schedule
  `*-*-* *:20:00`, `timeout: 240`. Front matter, non-secret: the HN user,
  the reddit user, the GitHub repos, the Cloudflare site names and tags, X's
  user id. One adapter per platform, each skipped (and said so in the run's
  entry) when its variable is unset, each failing alone.
- **`crew/social-drafts.md`, an agent role**, `model: sonnet`,
  `budget: 0.20`, schedule `*-*-* *:35:00`, `verbs: social get`, `web:
  <the blog's host> news.ycombinator.com github.com`. It drafts the
  replies (2.4). New in crew.py: **`gate: social`**, a function run before
  claude; when it says there is nothing to do the run is logged
  `nothing` (like shares' first runs) and no model is started, no seat taken.

### 2.2 The journal kinds (all `crew_*`: the crew login writes them)

- **`crew_social_comment`**, one entry per new comment or reply:
  - title: `<platform> · <author>: <first words>` (e.g. `HN · pg: Nice
    write-up, how do you…`), 200 characters;
  - content, line-keyed so the page, the drafter and a person read it:
    ```
    id: hn:9002
    platform: hn
    link: https://news.ycombinator.com/item?id=9002
    on: Software for One: My Star Trek Computer (https://news.ycombinator.com/item?id=9001)
    parent: story                       (story / post / his comment #…)
    author: pg
    at: 2026-10-21T09:14:00Z
    status: new                         (new / drafted / replied / dismissed)

    <the comment's text, as given, HTML unescaped to plain text>

    Suggested reply (draft, not posted):
    <the drafter's text, appended in 2.4>
    ```
  - `done_bool` 1 when he has replied (seen by a later poll: his reply
    among the comment's children) or dismissed it.
- **`crew_social_<platform>`** (`crew_social_hn`, `_github`, `_cf`,
  `_reddit`, `_x`), one per platform per captain's day: `value_int` the
  main count (HN points, GitHub stars, Cloudflare visits, reddit score),
  title the number first as the Stats view reads a reading ("1,231 visits ·
  Cloudflare"), content a short JSON (per item, per site, per referrer).
  A kind per platform for the reason shares.py gives: `measureSeries`
  charts a kind's numbers as one series. Written by the first run after
  midnight in `LCARS_TZ`, for the day before; skipped when that day's
  reading exists (a `list` of the kind, newest first).
- **`crew_social`**, the run's own entry (crew.py's `finish`): only when
  something happened (new comments, a platform failing, a daily reading);
  a quiet hour is logged, not posted (the `nothing` status), so the
  journal is not 24 empty rows a day.

"Seen" lives in the journal, not a file (CLAUDE.md: state the captain
should see): a comment is new when no `crew_social_comment` of the last 60
days has its `id:` line. The run reads them once (`/entries?kind=…`).
The global crew lock already stops two runs at once; nothing else writes
the kind.

Stats and Shares: Stats leaves `crew_social_*` out of Measurements as it
does the share readings (`isShareReading`), and the crew lists skip the
comments; the Shares view (docs/design/shares.md) gains a section per
platform from the daily readings. That is slice 6's page work.

### 2.3 The notice: Number One's escalation path

Number One escalates with `no1.py escalate`: an entry of kind `task_no1`.
That one kind is what reaches the captain everywhere: the console's Open
questions (`openQuestions`, the Chats button's count, `isAskKind`), his
Reminders on the phone through CalDAV, and the deck, whose `takeRows`
flashes `Number One asks: <title>` on the HUD once per new row. The
crew's equivalent is `task_crew` (crew.py's `URGENT:` line,
`crew_tool.post(urgent=True)`), and the crew login may write
`task_crew_<list>` (lcars_logins.h, test/logins.py 2).

So the watch's notice is **one `task_crew_social` reminder per run that
found new comments** (not one per comment: Reminders would fill up):
title `3 new comments: HN 2, GitHub 1`, content one block per comment (its
link, author, first line, `#<id>` of its `crew_social_comment` entry).
`askOf(k, "crew")` already takes the `_social` list, so the console's
Open questions and the count show it unchanged, and CalDAV puts it in a
"social" list in Reminders. When the captain ticks it off, the comments
stay; it is the notice that is done. A later run with more new comments
writes a new reminder rather than editing an open one (no compare-and-swap
in the API; an edit could lose his tick).

Two page changes (slice 2):
- deck.html `takeRows`: the crew's social notice flashed like Number
  One's (`New comments: <title>`, 9 s, once per row).
- index.html Open questions: a `task_crew_social` card lists its comments
  with Open (the link, a tab), the draft when there is one and **Copy
  reply** (the draft to the clipboard, for him to paste on the platform),
  and Dismiss per comment (the comment's `status: dismissed`, done 1).
  Voice: "computer, new comments" opens Open questions at the first
  social card; "copy the reply" copies the top card's first draft (a
  `VCMDS` line each, the same functions the buttons call; the clipboard
  from voice works only where the browser lets a page write it without a
  tap, which the commit and TODO.md must say if it fails on iOS).

### 2.4 The drafted reply: a suggestion, never posted

- `crew_tool.py social` (a new verb, read-only): the `crew_social_comment`
  entries with `status: new`, each with its thread (the parent and the
  post it is on, from the entry), and the captain's voice: his own last
  replies on that platform (the poll keeps his own comments' text in the
  run's JSON for HN, GitHub and reddit, where the API gives them) and
  `crew/social-voice.local.md`, a page of how he writes, kept out of the
  public tree (docs/design/open-source.md's `*.local.*`).
- The prompt: for each, one reply in his voice (short, plain, first
  person, no marketing, no emoji, his own spelling of names), or the line
  `No reply suggested: <why>` for one that needs none (thanks, a bot,
  hostile). It may WebFetch his post to answer a question about it.
- The drafter's output is not posted by the agent (crew agents cannot
  post; their final answer is the runner's). crew.py's `run_social_drafts`
  takes the answer as `#<id>: <draft>` blocks and **appends** each under
  the comment entry's `Suggested reply (draft, not posted):` line with a
  guarded PATCH (`if_modified`; a 412 means the captain edited it: skip,
  the next run tries again), setting `status: drafted`. The run's own
  `crew_social_drafts` entry lists what it drafted.
- Nothing in the watch has a write scope on any platform (3), and the HTTP
  layer of `social.py` refuses any method but GET to a platform host other
  than the token endpoints (a test proves it, 4). The captain posts his
  reply himself.

### 2.5 Failure and quiet

- A platform failing (a 5xx, a 429, a refused token) is a line in the
  run's `crew_social` entry; three runs failing in a row on one platform
  raise one `task_crew` ("The watch cannot read reddit: 401, the consent
  may have been withdrawn"), not one an hour. The count of failures is
  kept in the run's entry, read back by the next run.
- A token refresh failing with `invalid_grant` (consent withdrawn, Google's
  testing expiry) says which step of 3 to redo.
- The ship's health check (crew/ship.md) already sees a role's failed
  runs in runs.jsonl.

## 3. The credentials

One secret variable per platform in `~/.env` (the unit sources it;
read-only scopes only); the non-secret settings are in
`crew/social.md`'s front matter (or `crew/context.local.md`). The OAuth
consents land on one page of the ship's: **`/ui/oauth.html`**, a static
page (served without a login, like /ui/) that shows the `code` and `state`
parameters with a Copy button and nothing else. It sends nothing and
stores nothing; a code is useless without the secret or the PKCE verifier
that stay on the box, and dies in minutes. The captain copies the code
into his chat with Number One (or types `! scripts/social.py consent
<platform> <code>`); `social.py consent` exchanges it and writes the
variable into `~/.env` itself (mode 0600), never printing it. A rotating
refresh token (X's) is kept in `~/.config/lcars/social-x.json` (0600),
seeded from the variable: a file for a secret the API rewrites.

| Platform | Variable | Holds |
|---|---|---|
| HN | none | the user name is in the front matter |
| GitHub | `LCARS_SOCIAL_GITHUB` (optional) | a fine-grained token; unset: `gh auth token` |
| Cloudflare | `LCARS_CF_ANALYTICS_TOKEN` (shares.py's, shared) | Account Analytics: Read |
| Reddit | `LCARS_SOCIAL_REDDIT` | `<client id>:<secret>:<refresh token>` |
| Gmail | `LCARS_SOCIAL_GMAIL` | `<client id>:<secret>:<refresh token>` |
| X | `LCARS_SOCIAL_X` | `<client id>:<refresh token>` (seed) |

shares.py's `LCARS_REDDIT_CLIENT_ID`/`_SECRET` stay as they are; it reads
`LCARS_SOCIAL_REDDIT` when they are unset (slice 4). Neither is set on the
box today (the shares role has no share entries yet).

### The captain's checklist (each on the phone, once)

**3.1 Hacker News.** Nothing.

**3.2 GitHub.** Nothing: the box's gh login reads everything. Only if he
wants a read-only token instead: github.com, Settings, Developer settings,
Personal access tokens, Fine-grained, Generate. Resource owner: you;
Repository access: Public repositories (or the ones to watch);
Repository permissions: Administration Read (traffic), Issues Read,
Pull requests Read, Discussions Read, Metadata Read. Expiry: a year.
Copy the token, send it to Number One in the console's chat (a chat
stays on the box), and ask for it in `~/.env` as `LCARS_SOCIAL_GITHUB`.

**3.3 Cloudflare.** dash.cloudflare.com, My Profile, API Tokens, Create
Token, Custom token. Permissions: Account, Account Analytics, Read.
Account resources: your account. Create, copy, and send to Number One for
`~/.env` as `LCARS_CF_ANALYTICS_TOKEN` (with `LCARS_CF_ACCOUNT_ID` from
the dashboard's URL). (Number One's logs #9104 and #9112 were read with a
token; if that one already has this permission, reuse it.)

**3.4 Reddit** (wait for approval at step 3).
1. reddit.com/prefs/apps (desktop view in the phone's browser), "create
   another app": name `lcars-watch`, type **web app**, redirect uri
   `<the server>/ui/oauth.html`. Create. Note the id
   under the name and the secret.
2. Send both to Number One for the box (not `~/.env` yet: step 4 writes it).
3. File the Data API access request (Reddit's help centre, "Developer
   Platform & API", the Data API request form): personal, non-commercial;
   reads the requester's own inbox, posts and comments hourly to notify
   him; no posting, no other users' data stored beyond comments on his
   posts; scopes identity, history, read, privatemessages. Wait for yes.
4. Ask Number One for the consent link (`social.py consent reddit` prints
   it: authorize with `duration=permanent`, the four scopes, a state).
   Tap it, Allow. The oauth page shows a code: Copy, send it back. Done:
   the next hour's run reads reddit.
5. Meanwhile: reddit app, Settings, Notifications (email): "Comment
   replies", "Post replies" on. The mail route (3.5) reads them.

**3.5 Gmail** (for LinkedIn, and reddit while unapproved).
1. console.cloud.google.com, a new project `lcars-watch`. APIs & Services,
   Library, Gmail API, Enable.
2. OAuth consent screen: External, app name `lcars-watch`, your address
   as support and developer contact; Scopes: add `gmail.readonly`; Test
   users: your address. Then **Publish app** (In production; leave it
   unverified). Not publishing makes the consent last 7 days.
3. Credentials, Create credentials, OAuth client ID, Web application,
   authorised redirect URI `<the server>/ui/oauth.html`.
   Send the client id and secret to Number One.
4. Ask for the consent link (`social.py consent gmail`, with
   `access_type=offline&prompt=consent`), tap, pass the "unverified app"
   screen (Advanced, Go to lcars-watch), Allow, Copy the code, send it.
5. LinkedIn app, Me, Settings, Notifications, Posting and commenting:
   Comments (and Mentions) with Email on.

**3.6 X** (only if he decides to pay).
1. developer.x.com, sign in, create a Project and App; User
   authentication settings: OAuth 2.0, type Web App, callback
   `<the server>/ui/oauth.html`, read-only. Note the
   client id.
2. Buy credits in the developer console (the smallest amount); set a spend
   alert if offered.
3. `social.py consent x` prints the PKCE link (scopes `tweet.read
   users.read offline.access`); tap, Authorize, Copy the code, send it.
Otherwise: X Analytics in the app, and the numbers line in the share entry.

## 4. Tests

`scripts/test_social.py` (seconds, light, no network), in the shape of
`scripts/test_shares.py`: recorded answers in `scripts/testdata/social/`
(one folder per platform; real answers captured once by hand, names and
ids kept as they are public, any token or email address replaced), a
stand-in fetcher, and test_shares' stand-in journal server. It proves:

1. **Each adapter on its recordings**: HN (a user, a story with nested
   replies, a deleted and a dead comment skipped, a reply to his own
   comment), GitHub (stargazers with `starred_at`, issue comments since a
   time, traffic views and clones, a 403 for traffic without push),
   Cloudflare (the RUM answer by site, path, referrer, `bot: 0` in the
   query sent), reddit (the inbox with a `comment_reply` and a
   `post_reply`, `/api/info` score), Gmail (a LinkedIn "commented on your
   post" and a reddit reply notice; a LinkedIn mail of another kind
   ignored), X (tweets with public and non-public metrics, mentions).
2. **New is new once**: a run on the recordings writes one
   `crew_social_comment` per comment and one `task_crew_social`; a second
   run on the same recordings writes nothing; a third with one more
   comment writes one entry and a reminder naming only it.
3. **His own reply marks the comment**: a recording where his reply is a
   child of the comment: `status: replied`, done 1, and no notice.
4. **The daily reading**: written by the first run of a day in `LCARS_TZ`
   (a fixed now), not by the second, the right `value_int` and kind per
   platform; GitHub's 14-day window taken day by day without double counting.
5. **Tokens**: the refresh request's shape per platform (reddit's basic
   auth, Google's form, X's PKCE refresh), X's rotated token written to its
   file, `invalid_grant` a failure that names the checklist step, and no
   token, secret or code in any entry, log line or stdout (grep of all
   output for the stand-in secrets).
6. **Read only**: the fetcher records every request; any method but GET
   to a platform host, other than the token endpoints' POST, fails the
   test; no scope requested beyond section 3's.
7. **Failure**: one platform's 5xx leaves the others' entries written;
   three failing runs make one `task_crew`, the fourth none.
8. **The gate and the drafts**: `gate: social` says nothing with no
   `status: new` comment; `run_social_drafts` on a stand-in claude answer
   appends each draft under its line with `if_modified`, a 412 skipped,
   a `No reply suggested` kept as said.
9. **consent**: the printed links' parameters per platform, the exchange
   against a stand-in token endpoint writing `~/.env` (a temp HOME) with
   0600 and printing no secret.

The page side, in the QuickJS suite (tests.js) and deckboot.js: the deck
flashes a new `task_crew_social` once and not on a reload; the Open
questions card lists the comments, Copy reply copies the draft, Dismiss
sets the status with the guarded PATCH; the voice orders reach the same
functions; Stats leaves the `crew_social_*` kinds out of Measurements.
`python3 scripts/test_crew.py` gains the `gate:` key. No test calls a
platform; a live check is the captain's first real run, read in the
`crew_social` entry.

## 5. The slices, ranked

Each is one engineer's order, built, tested and deployed on its own.

1. **The watch, with what needs no new credential** (~30 min): `crew/social.md`,
   `scripts/social.py` (HN, GitHub with gh's token, Cloudflare with both
   sites and bots excluded), `run_social` in crew.py, the kinds of 2.2,
   seen-in-the-journal, the daily readings, the `task_crew_social` notice
   (2.3's data side), failure counting (2.5), `scripts/test_social.py`
   items 1-7 for these three. ARCHITECTURE.md's crew section and the role
   list. After it, HN and GitHub comments reach Open questions and
   Reminders.
2. **The notice on the deck and in the console** (~20 min): deck.html's
   flash, the Open questions card for `task_crew_social` (comments, Open,
   Copy reply, Dismiss), the two voice orders, Stats and the crew list
   leaving the kinds out; tests.js and deckboot.js; the full run.sh.
3. **The drafts** (~25 min): `gate:` in crew.py, `crew/social-drafts.md`,
   the `social` verb in crew_tool.py, `run_social_drafts`'s guarded append,
   `crew/social-voice.local.md` written from his blog posts and comments
   (the writer's part: Jake), test items 8; test_crew.py.
4. **Reddit** (~25 min, after the captain's approval; buildable before it
   against recordings): `/ui/oauth.html`, `social.py consent` (reddit
   first), the adapter (inbox, his posts' scores), test items 5, 6 and 9
   for reddit; shares.py reading `LCARS_SOCIAL_REDDIT`.
5. **Mail, for LinkedIn and reddit's notices** (~25 min): the Gmail
   adapter and its consent, the LinkedIn and reddit mail parsers (subject
   and snippet), test items 1 and 5 for Gmail. A comment from mail is
   linked to its post; its text is what the mail gives.
6. **The Shares view's platform section** (~15 min): the daily readings
   charted per platform in `./shares`.
7. **X** (~20 min, only if the captain buys credits): the PKCE consent,
   the rotating token file, the adapter, a run counter with a monthly
   read budget in the front matter (the run stops reading X when spent).

Open for the captain: whether to file Reddit's request; whether to pay
for X's API; whether a social reminder should carry a due time (so the
phone alerts on it) or wait silently in the list.
