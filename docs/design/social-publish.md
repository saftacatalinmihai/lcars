# Social publishing: the ship posts for the captain, on his tap

This deployment's own names (the server's address for the OAuth page,
the accounts, the blog post plan's dates) are in
`social-publish.local.md`, kept out of the public tree.

Status: slice 1 built (0.296.0, 2026-10-22): the Share sheet with the
hand route, `social_post` pages-only, the limits table in
`scripts/publish_net/limits.json`. Slices 2 on wait on the captain's
accounts (section 6). Design 2026-10-21. Asked by Number One for the
captain (thread social-login): "a way to automate posting to x, reddit,
linkedin, HN, mastodon, bluesky, and any other platforms that you think
would be useful for us".

It is the writing half of the social watch (docs/design/social-watch.md,
slices 1 and 2 live: the ship reads comments and stats hourly and never
posts). The watch's rule stays true of the watch; this is a separate
program with its own credentials, and it posts **only** what the captain
tapped Post on, or a schedule he approved with a tap. Every post becomes
a journal entry with its URL, which the watch and the shares role then
read for comments and numbers: one loop, written once, read back.

## 1. What each platform gives, as of 2026-10-21

Checked against the platforms' own docs where the box could read them,
2026-10-21; where only a secondary source had it, that source is named.
"Reply" means a reply to a comment on his post, the case the watch's
drafted replies (social-watch.md 2.4) would use.

### 1.1 Mastodon: everything, free, a token from his own settings

- `POST /api/v1/statuses` with `write:statuses`: `status`, `media_ids[]`,
  `in_reply_to_id` (a reply), `visibility`, `language`, and
  `scheduled_at` ("at least 5 minutes in the future": the instance itself
  can hold a scheduled post). An **`Idempotency-Key`** header is kept "up
  to 1 hour": a retried request posts once
  ([docs.joinmastodon.org/methods/statuses](https://docs.joinmastodon.org/methods/statuses/)).
- Images: `POST /api/v2/media` (`write:media`), with a description (alt
  text). The length limit is the instance's own,
  `configuration.statuses.max_characters` from `GET /api/v2/instance`
  (500 on mastodon.social); a link counts 23 characters whatever its length.
- Limits: 300 requests per 5 minutes per account, media uploads 30 per
  30 minutes ([docs.joinmastodon.org/api/rate-limits](https://docs.joinmastodon.org/api/rate-limits/)),
  far above a person's posting.
- Login: no OAuth dance needed. In his instance's Preferences,
  Development, New application, scopes `write:statuses write:media
  read:notifications` (the last for the watch, 3.5), and the page shows
  "Your access token". alexandru/social-publish does the same (2.1).
- Terms: an instance's own rules; automated posting of one's own posts is
  normal on Mastodon (the bot flag is for accounts that are *only*
  automated, which his is not).

### 1.2 Bluesky: everything, free, an app password

- A post is a record: `com.atproto.repo.createRecord` with
  `app.bsky.feed.post`, `text` and `createdAt`; **300 graphemes**; a link
  is clickable only through a *facet* (UTF-8 byte offsets); a link card is
  `app.bsky.embed.external`, its title, description and thumbnail fetched
  by the poster (the og: tags) and the thumbnail uploaded as a blob; up to
  4 images by `com.atproto.repo.uploadBlob`, each at most 1,000,000 bytes,
  with alt text; a reply carries `reply.root` and `reply.parent` (each a
  uri and a cid) ([atproto.com/blog/create-post](https://atproto.com/blog/create-post)).
- Login: an **app password** (Settings, Privacy and security, App
  passwords) and `com.atproto.server.createSession`. Bluesky recommends
  OAuth for apps with their own users and app passwords for
  "single-purpose applications such as bots or command-line tools"
  ([upload-post.com, Bluesky API guide](https://www.upload-post.com/bluesky-api/)).
  OAuth is out of reach anyway: its `client_id` is a URL to a metadata
  document the authorization server must fetch from the public web, and
  PAR, PKCE and DPoP are all required
  ([docs.bsky.app, OAuth client](https://docs.bsky.app/docs/advanced-guides/oauth-client));
  our server is on the tailnet. (It could be hosted on the public demo's
  bucket; not worth it for one account.) An app password cannot change
  the account's password or email, and one made without "allow direct
  messages" cannot read DMs.
- Limits: 5,000 points an hour, a create costs 3; `createSession` 30 per
  5 minutes and 300 a day per account, so the session's tokens are kept
  between runs, not made per post
  ([publishq.com](https://publishq.com/blog/bluesky-api-post-limits),
  [atproto discussion #697](https://github.com/bluesky-social/atproto/discussions/697)).
- No cost, no review, no developer account.

### 1.3 LinkedIn: posts and comments on his profile, free; 60-day tokens

- The self-serve product **Share on LinkedIn** grants `w_member_social`
  with no review: "Post, comment, and like posts on behalf of an
  authenticated member"
  ([Posts API, updated 2026-05-13](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api)).
  `POST https://api.linkedin.com/rest/posts` with headers
  `LinkedIn-Version: YYYYMM` and `X-Restli-Protocol-Version: 2.0.0`;
  author `urn:li:person:<id>` (from OpenID's `sub`, scope `openid
  profile`); the new post's URN in the `x-restli-id` header. Versions are
  sunset after about a year (202511 on 2026-11-16, same page): the
  version is a setting, and a test pins it.
- A link: LinkedIn does **not** scrape the URL. An article post sets
  `content.article` with `source`, `title`, `description` and a
  `thumbnail` image URN uploaded first through the Images API (same
  page). So the publisher reads the blog post's og: tags, as for Bluesky.
- An image: the Images API's upload, then `content.media.id`.
- A reply: `POST /rest/socialActions/<post or comment URN>/comments`
  with `actor`, `message.text` and, nested, `parentComment`
  ([Comments API, updated 2026-04-30](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api)).
  But **reading** his posts' comments needs `r_member_social`,
  restricted to approved developers (same pages; social-watch.md 1.6):
  the ship knows a LinkedIn comment only from the notification email, so
  a reply can be posted only when that mail carries the comment's URN.
  Until the mail route (watch slice 5) shows it does, LinkedIn replies
  are by hand.
- Login: OAuth 2 authorization code, redirect URI on our tailnet page
  (3.7). The access token lasts **60 days**; refresh tokens are "for all
  approved Marketing Developer Platform (MDP) partners" only
  ([Refresh Tokens, updated 2025-10-08](https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens)).
  So a personal app re-consents every 60 days (one tap; the ship reminds
  him at day 50). alexandru/social-publish's README says it refreshes
  with a one-year refresh token: that holds only for an app LinkedIn
  made an MDP partner, which ours will not be.
- Making the app: the developer portal asks for a **LinkedIn Page** to
  associate it with, verified by a Page admin, even for posts to a
  personal profile ([upload-post.com, LinkedIn API guide](https://www.upload-post.com/linkedin-api/));
  a page for the blog does.
- Limits: 150 requests per member per day
  ([Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin)).
  Free.

### 1.4 X: posts, paid per post; replies mostly refused

- Pay-per-use credits, no free tier: **creating a post $0.015 a
  request; a post that contains a URL $0.20 a request**; new developers
  get $20 of credits and a matched first recharge up to $50; a spending
  limit can be set that blocks requests once reached
  ([docs.x.com, pricing](https://docs.x.com/x-api/getting-started/pricing)).
  The URL price went from $0.01 to $0.20 on 2026-04-20
  ([upload-post.com, X API pricing](https://www.upload-post.com/x-api-pricing/)).
  So the blog post's link on X is 20 cents a post; a text post with the
  link in a reply to it is two requests, the reply being a post with a
  URL too. Cheapest honest form: one post with the link, $0.20.
- `POST /2/tweets`: text (280 characters, a link counts 23), up to 4
  images (`media.write`), a quote, a poll. OAuth 2 with PKCE, scopes
  `tweet.read tweet.write users.read media.write offline.access`; without
  `offline.access` the token lives two hours
  ([docs.x.com, OAuth 2.0](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)).
- **Replies**: since 2026-02-23 a programmatic reply is allowed "only if
  the original author @ mentions you or quotes your post", on every tier
  but Enterprise
  ([@XDevelopers](https://x.com/XDevelopers/status/2026084506822730185),
  [docs.x.com, manage posts](https://docs.x.com/x-api/posts/manage-tweets/introduction)).
  A reply to someone who replied to him is mostly refused (they did not
  mention him, the reply's @ is automatic but X counts the summons from
  the *original* author). Replies on X stay by hand.
- X Premium gives no API (social-watch.md 1.5).

### 1.5 Reddit: posts and replies, free, but only after Reddit approves

- `POST /api/submit` (scope `submit`: `sr`, `kind=link|self`, `title`
  up to 300 characters, `url` or `text`, `flair_id`) and `POST
  /api/comment` (scope `submit`, a reply by `thing_id`), OAuth 2 with
  `duration=permanent` for a refresh token
  ([reddit OAuth2 wiki](https://github.com/reddit-archive/reddit/wiki/OAuth2),
  [reddit API](https://www.reddit.com/dev/api/), which refuses the box).
  The redirect URI must match the app's exactly; the tailnet page works
  because his own browser follows it.
- **The gate**: since 2025-11-11 every new app needs Reddit's explicit
  approval under the Responsible Builder Policy, personal scripts
  included, and it forbids "automated posts ... including posting
  identical or substantially similar content across subreddits"
  ([Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy),
  which refused the box; summarised from
  [redditapis.com, 2026](https://www.redditapis.com/blogs/reddit-data-api-2026)
  and [replydaddy.com](https://replydaddy.com/blog/reddit-api-pre-approval-2025-personal-projects-crackdown)).
  The watch's own request (social-watch.md 3.4) is read-only; posting
  would be one request asking for `submit` too, or a second. Reports say
  personal requests are slow or unanswered.
- The box: `oauth.reddit.com` answered a bad token from this VPS with a
  403 "Blocked" page on 2026-10-19 (TODO.md); whether a good token gets
  through is unknown until one is tried.
- Subreddits have their own self-promotion rules (r/threejs's included);
  the ship cannot know them all, so a Reddit post always shows the
  subreddit's rules link in the preview.
- Until approved, and probably for good: **the hand route** (1.10).

### 1.6 Hacker News: no posting API, and the rules say not to automate

- The official API is read-only (Firebase) and Algolia is search. There
  is no write API.
- The guidelines: "please don't put generated text in HN posts ... HN is
  for sharing between humans. For the same reason, please don't
  automate posting." Also "Don't solicit upvotes, comments, or
  submissions" ([newsguidelines.html](https://news.ycombinator.com/newsguidelines.html)).
- Show HN "is for something you've made that other people can play
  with"; "blog posts, sign-up pages, newsletters, lists, and other
  reading material ... can't be Show HNs"
  ([showhn.html](https://news.ycombinator.com/showhn.html)). So Tuesday's
  Show HN must link the thing (the public demo or the repo), with the blog
  post as his first comment, not the blog post itself.
- The options:
  1. **A form login with his password**, the ship filling HN's forms. It
     breaks the guideline above, stores the one secret that gives the
     whole account away, and HN's captcha and rate limits catch scripts.
     Refused, as Number One said.
  2. **A draft he submits with a tap**: HN's own bookmarklet URL,
     `https://news.ycombinator.com/submitlink?u=<url>&t=<title>`
     ([bookmarklet.html](https://news.ycombinator.com/bookmarklet.html)),
     opens HN's submit form already filled in, in his browser, logged in
     as himself; he presses submit. The first comment (the Show HN text)
     is copied to the clipboard by the same tap, to paste once the story
     is up.
  3. **A reminder at the planned time**: a `task_crew_social` with a due
     time, so the phone alerts him; its card has the tap of option 2.
- **Recommended: 2 and 3 together.** The ship prepares, times and
  reminds; the captain's hand submits. That is what HN asks, and it costs
  nothing. After he submits, he pastes the item's URL into the post's
  card (or the watch finds it: his `submitted` list, social-watch.md
  1.1), and it is recorded like any other post (3.5).

### 1.7 Threads: possible, free, worth it later

- Publishing is a two-step container (`/me/threads` then
  `threads_publish`), text up to 500 characters; "250 API-published
  posts within a 24-hour moving period", 1,000 replies; scopes
  `threads_basic`, `threads_content_publish`, and
  `threads_manage_replies` for replies
  ([developers.facebook.com/docs/threads](https://developers.facebook.com/docs/threads/overview)).
- Login: a Meta app; one's own account works as an app tester without
  Meta's App Review ([social-api.ai](https://social-api.ai/blog/threads-api-publishing-posts-developer-guide)),
  long-lived tokens of 60 days that the app itself may refresh.
- Recommendation: **not now**. Worth it only if he is on Threads and
  his readers are; the provider shape (3.3) makes it one adapter later.

### 1.8 Lemmy: easy, small audience

- `POST /api/v3/post` with a JWT from `POST /api/v3/user/login`
  (username and password), rate limits per IP, posts 6 per period by
  default ([join-lemmy.org, API](https://join-lemmy.org/docs/contributors/04-api.html)).
  No app password and no OAuth: the account's own password would be
  stored. Recommendation: **no**, unless he uses a Lemmy community
  (programming.dev has a few) and makes a separate account for it.

### 1.9 dev.to (and Hashnode): syndication of the blog's posts

- dev.to's Forem API: `POST /api/articles` with an `api-key` header (made
  in Settings, Extensions), `title`, `body_markdown`, `published`
  (default false: a **draft**), up to 4 `tags`, `canonical_url` pointing
  at the blog so search engines credit the original
  ([developers.forem.com/api/v1](https://developers.forem.com/api/v1)).
  Free.
- This is the one network where the ship sends the whole post, not a
  link. Recommendation: **yes, as a draft**: the publisher posts the
  Hugo post's Markdown with `published: false` and the canonical URL; the
  captain looks at it on dev.to and presses Publish there. Front matter
  and Hugo shortcodes need converting (images to absolute URLs); that is
  the slice's work.
- Hashnode has a GraphQL API with a personal token; not checked today.
  One syndication target is enough to start; dev.to's audience is the
  closer fit.

### 1.10 Discord, Telegram: only for a channel of his own

- A Discord channel's webhook takes a message in one request, no bot or
  OAuth, 5 requests per 2 seconds; a Telegram bot posts to a channel
  where it is an admin (`sendMessage`, a link preview)
  ([core.telegram.org/bots/api](https://core.telegram.org/bots/api),
  [inventivehq.com, Discord webhooks](https://inventivehq.com/blog/discord-webhooks-guide)).
  Both trivial.
- Recommendation: **no**, unless he starts a channel for LCARS (a
  Discord for its users after the open-source release would make one
  worth it). Posting to other people's servers is not something to
  automate.

### 1.11 Every network: the hand route, no API at all

Each network has a URL that opens its own composer, filled in, in his
browser where he is logged in. No credential, no cost, no approval, and
nothing posted until he presses the network's own button:

| Network | URL |
|---|---|
| HN | `news.ycombinator.com/submitlink?u=<url>&t=<title>` |
| Reddit | `www.reddit.com/r/<sub>/submit?url=<url>&title=<title>` (or `type=TEXT&text=`) |
| X | `x.com/intent/post?text=<text>&url=<url>` |
| LinkedIn | `www.linkedin.com/sharing/share-offsite/?url=<url>` (text pasted from the clipboard) |
| Bluesky | `bsky.app/intent/compose?text=<text>` |
| Mastodon | `<instance>/share?text=<text>` |
| Threads | `www.threads.net/intent/post?text=<text>` |

These are the networks' long-standing share links, not APIs; a network
may change one, so each is a setting with a test of its shape, and a
broken one is seen as a wrong page, nothing worse. The phone opens the
app when it is installed. The ship then learns the post's URL the way
the hand route allows: he pastes it, or the watch finds it.

### 1.12 The table

| Network | Text | Link | Image | Reply | Login | Cost | Approval | Limits, terms | The captain, once |
|---|---|---|---|---|---|---|---|---|---|
| Mastodon | yes, instance's limit (500) | yes, 23 chars | yes, alt text | yes | a token from his settings | free | none | 300 req / 5 min; normal | make the token (3 scopes) |
| Bluesky | yes, 300 graphemes | yes, facet + card | 4, 1 MB each, alt | yes | app password | free | none | 5,000 points/h; normal | make an app password |
| LinkedIn | yes, 3,000 | yes, card set by us | yes | API yes, but the comment's URN only from mail | OAuth, redirect to the tailnet page | free | none (Share on LinkedIn is self-serve) | 150/day; 60-day token, no refresh | a Page, the app, a consent tap every 60 days |
| X | yes, 280 | yes, 23 chars | 4 | only if summoned: by hand | OAuth 2 PKCE | $0.015 a post, **$0.20 with a URL** | developer account | spend cap in console | dev account, credits, a cap, a consent tap |
| Reddit | yes (self post) | yes, title 300 | yes | yes | OAuth, permanent refresh | free | **Reddit's approval** | no near-identical posts across subs; each sub's rules | the app, the request, a consent tap |
| Hacker News | - | **by hand** | - | by hand | none | free | - | "please don't automate posting" | nothing; he presses submit |
| Threads | yes, 500 | yes | yes | yes | Meta app, tester | free | none as tester | 250 posts/day | later, if he uses it |
| dev.to | the whole post | canonical URL | cover | - | api-key | free | none | draft first | make the key |
| Lemmy, Discord, Telegram | | | | | | | | | not recommended now |

## 2. What others do

### 2.1 alexandru/social-publish (AGPL-3.0: read, nothing copied)

A self-hosted server for one person that posts to X, Mastodon, Bluesky
and LinkedIn from one form: text, images with alt text (an LLM can
write the alt text), and an RSS feed of what was posted
([github.com/alexandru/social-publish](https://github.com/alexandru/social-publish)).
Taken from it, as ideas only:

- **One settings page per network**, on the account page, instead of
  environment variables per network: a card per network with "connect",
  its state, and the scopes it asks. Ours is the Share sheet's network
  chips plus Config's Server section (`featureOff`, 3.7), since our
  secrets stay in `~/.env` (the order's rule, and the watch's).
- Mastodon's token with only `write:statuses` and `write:media`; Bluesky
  by app password; LinkedIn and X by OAuth with a callback URL on the
  server.
- LinkedIn's refresh: it refreshes with a one-year refresh token. As
  1.3 says, LinkedIn gives those to MDP partners only; ours plans the
  60-day re-consent instead, with a reminder.
- No scheduling: posting is immediate. Ours adds approved schedules.

### 2.2 Postiz (AGPL-3.0: the shape only)

Postiz's providers each implement one interface
([social.integrations.interface.ts](https://github.com/gitroomhq/postiz-app/blob/main/libraries/nestjs-libraries/src/integrations/social/social.integrations.interface.ts)):
`generateAuthUrl`, `authenticate`, `refreshToken` (the OAuth side);
`post`, `comment` (a reply); `maxLength()`, `checkValidity()` (the
preview's checks before anything is sent); `scopes`; `analytics` and
`postAnalytics` (the watch's side, here). Ours is the same split in a
Python module per network (3.3), much smaller: no multi-user, no
browser-extension cookies, no queue server.

## 3. The design

### 3.1 The pieces

- **`social_post`**, an entry of the captain's: the text to post and
  where. Written by the console's Share sheet. **A pages-only kind**,
  like `deck_patch` and `ui_patch`: the server refuses a create or change
  of it without `X-LCARS-Client` (`PatchKindAllowed`, lcars_http.h), the
  main login's too, and the steward may not write it
  (`StewardMayWriteKind`). So no chat agent through lcars-cli, and no
  crew note, can write or approve a post.
- **`POST /publish/<id>`**, a server route (a new `lcars_publish.h`),
  the owner's login with `X-LCARS-Client` only (every limited login
  403): runs `scripts/publish.py post <id> --networks a,b [--dry-run]`
  by `posix_spawn` (argv only, no shell, as the chat runs claude),
  waits up to 60 seconds, and answers its JSON: one result per network.
- **`scripts/publish.py`**, the publisher, no model: one module per
  network in the provider shape (3.3); reads the entry through the API
  (`/entries/<id>`), posts, and writes the record (3.5) with the crew
  login. Also `publish.py due` (the schedule, 3.4), `publish.py consent
  <network>` (the OAuth links and exchange, as the watch's design has
  it), `publish.py check` (each network's credentials, by a read that
  costs nothing).
- **`crew/publish.md`**, `kind: script`, `script: publish`: the timer
  for scheduled posts (3.4).
- **`crew_social_post`**, the record: one per network per post (3.5).

The publisher is not the watch: `social.py`'s `check_read_only` stays as
it is, and its test still proves the watch writes nothing. The
publisher has its own guard (3.8).

### 3.2 The Share sheet

From an entry (the editor's ⋯ sheet "Share…", the palette's "share this
entry", voice "computer, share this", and a key in `KEYS` chosen when
built), a sheet over the entry:

1. **What**: the link (the entry's first URL, else the blog post's,
   else none), the image (the entry's first photo, with its alt text from
   the entry's caption, editable), and the base text (the entry's
   title and first paragraph, editable). For a blog post the link's og:
   title, description and image are fetched once by the server (`GET
   /publish/card?url=`, the same reader the publisher uses) and shown as
   the card each network will show.
2. **Where**: a chip per network. A network whose credentials are set is
   a toggle; one without is greyed with its note ("Mastodon: no token in
   ~/.env", the `featureOff` style) and still offers its hand route.
   HN and Reddit (until approved) are hand-route chips.
3. **A preview per network**, one card each, the text editable per
   network (a change makes that network's text its own): its counter
   against that network's limit as the network counts (Mastodon's
   instance limit with links as 23; Bluesky's 300 graphemes,
   `Intl.Segmenter`; LinkedIn 3,000; X 280 with links as 23; a Reddit
   title's 300 with the subreddit and flair fields; HN's title 80), red
   and Post disabled over it; X's card says "$0.20 (contains a link)";
   Reddit's shows the subreddit's rules link.
4. **The buttons**: **Post** on each card and **Post to N** for all
   checked; **Schedule…** (a date and time in his zone); **Dry run**
   (everything but the send, 3.9); and on a hand-route card **Open**
   (the network's composer, filled; the first comment copied).

Feedback, by the standing rule: a tap marks the card "posting…" in the
same frame; each network's result replaces it as the route's answer
lands: "Posted" with the post's link, or the error in the card ("Bluesky:
401, the app password was revoked") with Retry. A network posted already
for this text shows "Posted 10:02 · link" and no Post button (3.8).

Voice: "computer, share this" (the sheet), "post it" (Post to all
checked, with the sheet open: the same function the button calls),
"schedule it" (the time picker), "dry run" (Dry run). A post said by
voice still goes through the sheet: the voice opens and presses, it does
not skip the preview.

The demo has the sheet with every network a hand route and nothing
posted (its `DEMO` path).

### 3.3 The providers

`scripts/publish_net/<network>.py`, each with:

```
NAME, LIMIT, COUNTS          # "Bluesky", 300, "graphemes"
configured(env) -> str|None  # None, or what is missing (the chip's note)
validate(post) -> [errors]   # the preview's checks, the page has a copy
send(http, env, post, dry) -> {"url", "id", "raw"}
reply(http, env, target, text, dry) -> {"url", "id"}   # where possible
hand_url(post) -> str        # the hand route
consent_url(env, state) / exchange(env, code)          # OAuth networks only
```

`post` is the network's text, link, card and image, already resolved.
The page's counter and `validate` agree by a shared test table (3.10).

### 3.4 Scheduled posts

The sheet's Schedule writes, in the `social_post` entry, `at:` (the time
in UTC) and **`approved:`**, the time of his tap and a SHA-256 of each
network's text as it was approved. `crew/publish.md`'s timer
(`*-*-* *:0/5`, no model, a few seconds) runs `publish.py due`: the
`social_post` entries with an `at:` at or before now and no record yet
for a network, and for each network posts **only if the text's hash is
the approved one**. An edit after approval changes the hash: that
network is not posted, and one `task_crew_social` says so ("Bluesky's
text changed after you approved it: tap Post or Schedule again"). A
schedule more than 6 hours late (the box was down) is not posted either;
the reminder asks.

Only the page can write `approved:` (the kind is pages-only, 3.1). On a
network that holds its own schedule (Mastodon's `scheduled_at`) the ship
still posts at the time itself: one path, one record, a cancel that
works the same everywhere (delete the `at:`, or the entry).

The hand route's schedule is a reminder: a `task_crew_social` with a
due time (the phone alerts), its card the network's Open. That is HN's
Tuesday.

### 3.5 The record, and the watch reading it back

Each network's send writes one **`crew_social_post`** entry with the
crew login (the publisher's runs are the crew's, like the watch):

```
title: Bluesky · posted: Software for One: my Star Trek computer
network: bluesky
url: https://bsky.app/profile/<handle>/post/<rkey>
id: at://did:plc:…/app.bsky.feed.post/<rkey>
post: #<social_post id>
hash: <sha256 of the text sent>
at: 2026-10-23T15:00:04Z
by: tap | schedule | hand
status: posted | failed | dry
```

- A failure is a record too (`status: failed`, the error), so the log of
  every attempt is the journal, readable and searchable (CLAUDE.md:
  state the captain should see).
- A hand-route post is recorded when he pastes its URL into the card
  (`by: hand`), written by the page with his login as a `share` entry
  (below), since the crew login is not his.
- **The watch reads it back**: shares.py takes `crew_social_post`
  entries with `status: posted` as shares, as it takes `share` entries
  (the URL is the share, the network the place). The watch's own
  adapters gain Mastodon (`GET /api/v1/notifications?types[]=mention`,
  `read:notifications`) and Bluesky
  (`app.bsky.notification.listNotifications`, the same app password):
  new replies to the posts become `crew_social_comment` entries like
  HN's, with drafted replies (watch slice 3).
- The `share` kind stays the captain's: the Share sheet's hand route
  writes one per hand post with its URL, so the Shares view
  (docs/design/shares.md) shows the hand posts and the ship's alike.

### 3.6 Replies

The watch's comment cards (Open questions, `task_crew_social`) gain
**Post reply** beside Copy reply where the network allows a reply by API
and the ship has a credential: Mastodon, Bluesky, Reddit once approved,
LinkedIn when the comment's URN is known. The draft is shown in an
editable box first; Post reply sends that text through `POST
/publish/reply` (same guard as 3.1), records a `crew_social_post` with
`reply_to:`, and marks the comment `status: replied`. X and HN keep Copy
reply and Open: X refuses unsummoned replies (1.4), HN asks for humans
(1.6).

### 3.7 Credentials

As the watch's: one variable per network in `~/.env` (the unit and the
timers source it), never in the repo or the journal. The OAuth consents
land on the watch's `/ui/oauth.html` (social-watch.md 3, built with its
reddit slice or the first of these that needs it), which shows the code
to copy; `publish.py consent <network> <code>` exchanges it and writes
the variable itself (0600), never printing it. A token a network rotates
or renews (X's refresh token, LinkedIn's 60-day token) is kept in
`~/.config/lcars/publish-<network>.json` (0600), seeded from the
variable.

| Network | Variable | Holds |
|---|---|---|
| Mastodon | `LCARS_PUB_MASTODON` | `<instance host>:<access token>` |
| Bluesky | `LCARS_PUB_BLUESKY` | `<handle>:<app password>` |
| LinkedIn | `LCARS_PUB_LINKEDIN` | `<client id>:<secret>`; the token in its file |
| X | `LCARS_PUB_X` | `<client id>:<secret>`; the tokens in their file |
| Reddit | `LCARS_PUB_REDDIT` | `<client id>:<secret>:<refresh token>` (the watch's app, with `submit` added) |
| dev.to | `LCARS_PUB_DEVTO` | the api-key |

Separate from the watch's variables on purpose: a write credential is
never what a read-only program loads. Config's Server section lists each
as set or not (`GET /features` gains `publish_<network>`: on, or what is
missing; never a value).

**Agents and the secrets.** Every crew and chat agent runs as the same
Unix user as the server, so a file mode does not keep `~/.env` from them;
their Claude Code settings deny `Read(~/.env)`,
`Read(~/.config/lcars/**)` and the matching Bash, which the publisher's
slice adds and test_crew.py checks. That is a rule the agent's harness
enforces, not the kernel. The stronger fence is the secrets phases
(docs/design/confidential-entries.md): with phase 2's own login for the
chat's Claude, the server can refuse it `/publish` and the pages-only
kinds outright, not only by header; and phase 3's write-only door is
where a token could later be sealed so that only the publisher, asked by
the vault's holder, opens it. Until then the write tokens carry the same
exposure as the watch's read tokens, with less at stake per token than
the captain's mail would be: each is revocable from its network's
settings in a minute, and 3.11 says where.

### 3.8 The guardrails

1. **No post without his tap or his approved schedule.** The route is
   the owner's login from the pages; a schedule is approved text by hash;
   the kind is pages-only; nothing else calls `publish.py post` (the crew
   timer runs only `due`, which posts only approved hashes).
2. **One post per network per text.** Before sending, the publisher
   looks for a `crew_social_post` with the same network and hash and
   `status: posted`: if found, it answers "already posted" with the link
   and sends nothing. A Retry after a timeout first asks the network
   (Mastodon's `Idempotency-Key`, the hash as key, kept an hour; the
   others: a read of his latest posts for that text, free on each but X's
   $0.001) before posting again.
3. **A log of every post**: the `crew_social_post` entries, failures
   and dry runs included, and a line per send in the crew's runs.jsonl.
4. **A daily cap per network** in the front matter (`cap: 5`) and a
   monthly spend cap for X (`x_budget_usd: 5`, counted from the records'
   prices), both refusing past it with a reminder.
5. **Reddit**: never the same text in two subreddits (the policy, 1.5);
   the sheet allows one subreddit per post.
6. **No platform's account password** is ever stored (HN's, Lemmy's,
   LinkedIn's): app passwords, tokens and OAuth only.

### 3.9 Dry run

- `publish.py post <id> --dry-run`, the sheet's **Dry run**, and
  `LCARS_PUB_DRY=1` in `~/.env` (everything dry, for the first week if he
  wants): the whole path runs (the entry read, the card fetched, the
  checks, the request built), the send is not made, and the answer shows
  each network's request (headers' secrets replaced by `…`). The record
  is written with `status: dry`, so the sheet and the log show what would
  have gone.
- Per network, `publish.py check` proves a credential by a free read
  (`GET /api/v1/accounts/verify_credentials`, `getSession`,
  `/v2/userinfo`, X's `/2/users/me` at $0.001), never by posting.

### 3.10 Tests

`scripts/test_publish.py` (seconds, light, no network), in the shape of
`test_social.py`: recorded answers in `scripts/testdata/publish/`, a
stand-in HTTP layer recording every request, the stand-in journal.

1. Each provider builds the right request on recordings: Mastodon's
   status with media and an Idempotency-Key; Bluesky's record with link
   facets at the right UTF-8 byte offsets (an emoji and a Romanian
   diacritic before the link), the external card, a reply's root and
   parent; LinkedIn's `/rest/posts` article with its headers and
   version; X's `/2/tweets`; Reddit's `/api/submit`; dev.to's draft
   with the canonical URL.
2. The limits table: each network's count of the same texts, shared
   with tests.js (the page's counter) from one JSON file.
3. Once per text: a second post of the same hash sends nothing; a
   timeout then Retry posts once.
4. Schedules: due at the time, not before; an edit after approval not
   posted and one reminder; six hours late not posted.
5. Dry run sends nothing and writes `status: dry`.
6. Secrets: no token, password or code in any record, answer or output
   (all output grepped for the stand-in secrets); consent writes 0600.
7. Caps: the sixth post of a day refused; X's budget.
8. The hand URLs' shapes.

Server: `test/publish.py` (~40s, a scratch build): `POST /publish/<id>`
for the owner with and without `X-LCARS-Client`, every limited login a
403, the spawn with a stand-in `publish.py`, its timeout; `social_post`
pages-only in `test/logins.py` (the steward refused). The page:
tests.js (the sheet from an entry, the previews, the counters, the
feedback states, the voice orders, the hand route's URL and clipboard),
`test/buttons.py` and `test/keyboard.py` for the sheet's fields. No test
posts to a network; the first real post is the captain's, through Dry
run first.

## 4. The first uses: the blog post plan

The plan's two steps this applies to first (dates in
`social-publish.local.md`):

- **Thursday, r/threejs.** Reddit's approval will not have come; this is
  the hand route: the sheet's Reddit card with the title, `url` and the
  subreddit, a reminder at the planned time, Open, his submit, the URL
  pasted back (a `share` entry). The ship's part: the text, the timing,
  the reminder, the record, the watch. Read r/threejs's rules for
  self-promotion first; a project post with the demo link and a short
  how-it-was-made is the usual welcome form there.
- **Tuesday, Show HN.** By hand, always (1.6): the title `Show HN: …`
  with the demo or repo URL (the blog post is not a Show HN), the first
  comment drafted in his voice and copied by the Open tap, the reminder
  at the time he picks.

So slice 1 below is what both need, and needs no credential.

## 5. The slices, smallest first

Each is one engineer's order, built, tested and deployed on its own.

1. **The Share sheet with the hand route** (~30 min): `social_post`
   (pages-only, the steward refused), the sheet (what, where, previews
   with the limits table, counters), every network's Open and the
   clipboard, a hand post's URL saved as a `share` entry, a scheduled
   hand post as a `task_crew_social` with a due time; the voice orders;
   tests.js, logins.py, buttons.py, keyboard.py. Nothing is posted by
   the ship. Ready for Thursday and Tuesday.
2. **The publisher, Mastodon and Bluesky** (~40 min): `scripts/publish.py`
   with the provider shape, the two providers, `check`, dry run, the
   records, once-per-text, caps; `lcars_publish.h`'s `POST /publish/<id>`
   and `GET /publish/card`; the sheet's Post buttons and their states;
   `GET /features` entries; the agents' deny rules; test_publish.py,
   test/publish.py. After it he posts to both with a tap.
3. **Scheduled posts** (~25 min): `approved:` with hashes, `crew/publish.md`
   and `publish.py due`, the edited-after-approval and late refusals with
   their reminder; tests 4.
4. **Replies back** (~30 min): the watch's Mastodon and Bluesky adapters
   (new comments on his posts), shares.py reading `crew_social_post`,
   Post reply on a comment's card (`POST /publish/reply`).
5. **LinkedIn** (~35 min, after he makes the Page and the app):
   `/ui/oauth.html` if not built yet, consent, the article card with its
   thumbnail upload, the 60-day token file and the day-50 reminder.
6. **dev.to drafts** (~25 min): the Hugo post's Markdown converted
   (front matter out, shortcodes and image paths resolved), posted as a
   draft with the canonical URL.
7. **X** (~25 min, only if he buys credits): PKCE consent, the rotating
   token file, the provider, the price on the card and the monthly
   budget.
8. **Reddit** (~25 min, only after Reddit approves): the `submit` scope,
   the provider, one subreddit per text; the hand route stays the
   fallback.

HN has no slice: it is the hand route of slice 1, for good. Threads,
Lemmy, Discord and Telegram wait for a reason (1.7, 1.8, 1.10).

## 6. The captain's decisions

1. **The networks**: which accounts he has and wants. Mastodon: which
   instance and handle? Bluesky: which handle? (Neither is known to the
   ship; the watch has none.)
2. **Slice 1 first** (the hand route, no credentials), so Thursday's
   r/threejs and Tuesday's Show HN have the sheet and the reminders?
3. **X**: pay for posting? A post with the blog's link is $0.20; a $5
   monthly cap is 25 such posts. Or the hand route on X (free).
4. **Reddit**: ask Reddit for `submit` as well as the watch's read
   scopes in one request, or keep posting to Reddit by hand?
5. **LinkedIn**: make a LinkedIn Page for the blog (the app needs one),
   and accept a consent tap every 60 days?
6. **dev.to**: syndicate the blog's posts as drafts there?
7. **Dry run for the first week** (`LCARS_PUB_DRY=1`), or live from the
   first tap?
8. **The daily cap** per network (5 proposed) and whether scheduled
   posts need a second confirmation the morning they go out (proposed:
   no; the approval's hash is the confirmation).
9. **HN**: confirmed by hand only, with the prepared form and a reminder
   (recommended, and what HN's guidelines ask)?
