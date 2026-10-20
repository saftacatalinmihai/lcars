#!/usr/bin/env python3
"""The blog post's shares, read for their numbers (crew/shares.md, no model).

The captain posts a link to his blog post in several places and keeps one
journal entry of kind `share` per place: the first URL in its content is the
share (the reddit thread, the HN item, the toot), the title names the place
("r/ClaudeAI"), and it is created when he posted. Each run of the crew role
reads them all and writes, with the crew login:

- one reading per share, kind `crew_share_<id of the share entry>`:
  value_int its main count (score, points, favourites, likes), the title
  that number first ("312 score · r/ClaudeAI", as /log titles a reading),
  the content a short JSON of everything the source gave;
- one global reading, kind `crew_shares` (the run's own entry, crew.py's
  finish): value_int the sum of the shares' main counts, content the sums.

A kind per share because the Stats view charts any kind with two or more
numbers as one series (measureSeries in index.html): one kind for every
share would be one zig-zag line through r/ClaudeAI and HN alike. crew_*
because that is what the crew login may write (lcars_logins.h); and
crew_tool.own_kind keeps crew_* out of what the crew read as the captain's
own writing.

Where the numbers come from (`adapter`): reddit's OAuth API (app-only
credentials LCARS_REDDIT_CLIENT_ID/LCARS_REDDIT_SECRET in ~/.env - the box
is refused reddit's .json pages), HN's Algolia API, a Mastodon instance's
public status API. X and LinkedIn have none: there the captain writes the
latest numbers as a line in the share entry ("12 likes, 3 reposts, 800
views"), and the newest such line is the reading. A share whose adapter
fails this run falls back to that line too.

Views of the post by where the reader came from are Cloudflare Web
Analytics' (LCARS_CF_ANALYTICS_TOKEN, LCARS_CF_SITE_TAG, and
LCARS_CF_ACCOUNT_ID or the token's first account): page loads of the post's
path by referer host, since the share was made. A referer is a host, not a
thread, so two shares on one site (two subreddits) both carry that site's
views, and say with which (`blog_views_shared`).

The I/O is in `collect`; what is made of it (`readings`) is pure, and is
what scripts/test_shares.py checks on saved responses.
"""

import base64
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

# the share role's kind (kinds.md): T.roles().kind("share"), at the run
READING_PREFIX = "share_"       # crew_share_<id>, through crew_tool.post's crew_ prefix
UA = "linux:lcars-shares:1.0 (personal blog stats; by /u/{user})"
CF_GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"
CF_DAYS_PER_QUERY = 30          # one RUM query's span stays inside what the free plan answers
CF_MAX_DAYS = 180               # its retention; views older than that are not counted
URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the share entries -------------------------------------------------------

def first_url(text):
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?") if m else ""


def parse_share(row):
    """A share entry as the run needs it, or None when it names no URL."""
    url = first_url(row.get("content"))
    if not url:
        return None
    # an entry saved with a link and no title is given the server's
    # placeholder (lcars_http.h): that names no place, the link does
    title = (row.get("title") or "").strip()
    if title == "HTTP Entry":
        title = ""
    return {"id": int(row["id"]), "title": title or url, "url": url,
            "created": row.get("created_at_utc") or "", "manual": manual_line(row.get("content"))}


# "12 likes, 3 reposts, 800 views", "1.2k views · 40 likes": the captain's
# numbers for a share with no API, as he types them on a phone
_PAIR = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([km])?\s+([a-z]+)", re.I)
_SEP = re.compile(r"^[\s,;·|/+-]*$")
WORDS = {"like": "likes", "reaction": "likes", "heart": "likes", "favourite": "favourites", "favorite": "favourites",
         "fav": "favourites", "star": "favourites", "repost": "reposts", "retweet": "reposts", "rt": "reposts",
         "boost": "reposts", "share": "reposts", "reshare": "reposts", "quote": "quotes", "view": "views",
         "impression": "views", "comment": "comments", "reply": "comments", "replie": "comments",
         "bookmark": "bookmarks", "save": "bookmarks", "upvote": "score", "point": "points", "score": "score",
         "vote": "score", "click": "clicks", "follower": "followers"}
# which of a manual line's numbers is the share's main count
MAIN_ORDER = ("likes", "score", "points", "favourites", "reposts", "views")


def _word(w):
    w = w.lower()
    for cut in (w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w):
        if cut in WORDS:
            return WORDS[cut]
    return None


def parse_numbers(line):
    """A line that is wholly `<number> <word>` pairs -> {field: int}, else None."""
    s = line.strip().lstrip("-*•").strip()
    out, pos = {}, 0
    for m in _PAIR.finditer(s):
        if not _SEP.match(s[pos:m.start()]):
            return None
        field = _word(m.group(3))
        if field is None:
            return None
        n = float(m.group(1).replace(",", ""))
        n *= {"k": 1000, "m": 1000000}.get((m.group(2) or "").lower(), 1)
        out[field] = out.get(field, 0) + int(round(n))
        pos = m.end()
    if not out or not _SEP.match(s[pos:]):
        return None
    return out


def manual_line(text):
    """The newest numbers line in a share entry (the last one), or None."""
    for ln in reversed((text or "").splitlines()):
        got = parse_numbers(ln)
        if got:
            return got
    return None


def manual_main(nums):
    for f in MAIN_ORDER:
        if f in nums:
            return f
    return next(iter(nums))


# ---- adapters: (source, url) -> the source's numbers ------------------------

def host_of(url):
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def reddit_id(url):
    """The post id of a reddit link: /comments/<id>/, redd.it/<id>; None for
    a share link (/s/<code>), which only reddit's own redirect can resolve."""
    u = urllib.parse.urlsplit(url)
    if host_of(url) == "redd.it":
        m = re.match(r"/([a-z0-9]+)", u.path, re.I)
        return m.group(1).lower() if m else None
    m = re.search(r"/comments/([a-z0-9]+)", u.path, re.I)
    return m.group(1).lower() if m else None


def hn_id(url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    v = (q.get("id") or [""])[0]
    return v if v.isdigit() else None


def mastodon_id(url):
    """https://<instance>/@user/<id> or /users/<user>/statuses/<id>."""
    m = re.match(r"/(?:@[^/]+|users/[^/]+/statuses)/(\d+)/?$", urllib.parse.urlsplit(url).path)
    return m.group(1) if m else None


def adapter(url):
    """Which API a share's URL is read from, or None (the manual line)."""
    h = host_of(url)
    if h == "redd.it" or h == "reddit.com" or h.endswith(".reddit.com"):
        return "reddit"
    if h == "news.ycombinator.com":
        return "hn"
    if h in ("x.com", "twitter.com", "linkedin.com", "lnkd.in") or h.endswith(".linkedin.com"):
        return None
    if mastodon_id(url):
        return "mastodon"
    return None


def reddit_numbers(info):
    """/api/info's Listing -> the post's numbers."""
    kids = ((info or {}).get("data") or {}).get("children") or []
    if not kids:
        raise ValueError("reddit has no such post (removed, or a wrong id)")
    d = kids[0].get("data") or {}
    out = {"main": "score", "score": int(d.get("score") or 0), "upvote_ratio": d.get("upvote_ratio"),
           "comments": int(d.get("num_comments") or 0), "crossposts": int(d.get("num_crossposts") or 0)}
    if d.get("view_count") is not None:
        out["views"] = int(d["view_count"])
    if d.get("removed_by_category"):
        out["removed"] = d["removed_by_category"]
    return out


def hn_numbers(item):
    """Algolia's item (the story with its comment tree) -> points and comments."""
    def count(kids):
        return sum((1 if k.get("type") == "comment" and (k.get("text") or k.get("children")) else 0)
                   + count(k.get("children") or []) for k in kids)
    if not item or item.get("type") != "story":
        raise ValueError("HN item is not a story")
    return {"main": "points", "points": int(item.get("points") or 0), "comments": count(item.get("children") or [])}


def mastodon_numbers(status):
    if not status or "favourites_count" not in status:
        raise ValueError("not a Mastodon status")
    out = {"main": "favourites", "favourites": int(status.get("favourites_count") or 0),
           "reposts": int(status.get("reblogs_count") or 0), "comments": int(status.get("replies_count") or 0)}
    if status.get("quotes_count") is not None:
        out["quotes"] = int(status["quotes_count"])
    return out


# ---- HTTP ----------------------------------------------------------------------

def _get(url, headers=None, data=None, timeout=20):
    """(status, parsed JSON or None, text) - a 4xx/5xx is an answer, not a raise."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            st, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, text = e.code, e.read().decode("utf-8", "replace")
    try:
        return st, json.loads(text), text
    except ValueError:
        return st, None, text


def _refused(what, st, text):
    # reddit answers a box it blocks with a 403 HTML page titled "Blocked"
    if st == 403 and "<title>Blocked" in text:
        return RuntimeError(f"{what}: 403, reddit blocks this box")
    plain = re.sub(r"<[^>]+>|\s+", " ", text)[:120].strip()
    return RuntimeError(f"{what}: HTTP {st} {plain}")


class Fetcher:
    """The adapters' I/O, one per run: reddit's app token is asked for once."""

    def __init__(self, env, get=None):
        # _get looked up now, not bound as a default: a test stands in for it
        self.env, self.get, self.token = env, get or _get, None

    def ua(self):
        return UA.format(user=self.env.get("LCARS_REDDIT_USER") or "lcars")

    def reddit(self, url):
        cid, sec = self.env.get("LCARS_REDDIT_CLIENT_ID"), self.env.get("LCARS_REDDIT_SECRET")
        if not cid or not sec:
            raise RuntimeError("no LCARS_REDDIT_CLIENT_ID/LCARS_REDDIT_SECRET in ~/.env")
        pid = reddit_id(url)
        if not pid:
            raise RuntimeError("a reddit share link (/s/...): put the post's full /comments/ URL in the entry")
        if self.token is None:
            basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
            st, j, text = self.get("https://www.reddit.com/api/v1/access_token",
                                   {"Authorization": "Basic " + basic, "User-Agent": self.ua(),
                                    "Content-Type": "application/x-www-form-urlencoded"},
                                   b"grant_type=client_credentials")
            if st != 200 or not (j or {}).get("access_token"):
                raise _refused("reddit token", st, text)
            self.token = j["access_token"]
        st, j, text = self.get(f"https://oauth.reddit.com/api/info?id=t3_{pid}&raw_json=1",
                               {"Authorization": "bearer " + self.token, "User-Agent": self.ua()})
        if st != 200 or j is None:
            raise _refused("reddit api/info", st, text)
        return reddit_numbers(j)

    def hn(self, url):
        iid = hn_id(url)
        if not iid:
            raise RuntimeError("an HN link names its item: news.ycombinator.com/item?id=N")
        st, j, text = self.get(f"https://hn.algolia.com/api/v1/items/{iid}", {"User-Agent": self.ua()})
        if st != 200 or j is None:
            raise _refused("hn.algolia.com", st, text)
        return hn_numbers(j)

    def mastodon(self, url):
        u = urllib.parse.urlsplit(url)
        st, j, text = self.get(f"https://{u.hostname}/api/v1/statuses/{mastodon_id(url)}", {"User-Agent": self.ua()})
        if st != 200 or j is None:
            raise _refused(u.hostname, st, text)
        return mastodon_numbers(j)

    def numbers(self, share):
        """(numbers with "source", None) or (None, why)."""
        src = adapter(share["url"])
        if src is None:
            return None, "no API for this site: its numbers are the entry's own line"
        try:
            return dict(getattr(self, src)(share["url"]), source=src), None
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as e:
            return None, f"{src}: {e}"

    # -- Cloudflare Web Analytics --

    def cf_ready(self):
        return bool(self.env.get("LCARS_CF_ANALYTICS_TOKEN") and self.env.get("LCARS_CF_SITE_TAG"))

    def cf_account(self):
        acct = self.env.get("LCARS_CF_ACCOUNT_ID")
        if acct:
            return acct
        st, j, text = self.get("https://api.cloudflare.com/client/v4/accounts?per_page=5", self.cf_headers())
        res = (j or {}).get("result") or []
        if st != 200 or not res:
            raise RuntimeError(f"cloudflare accounts: HTTP {st} {text[:120]} (set LCARS_CF_ACCOUNT_ID)")
        return res[0]["id"]

    def cf_headers(self):
        return {"Authorization": "Bearer " + self.env["LCARS_CF_ANALYTICS_TOKEN"], "Content-Type": "application/json"}

    def cf_views(self, path, since, until):
        """[(day, referer host, page loads)] for `path` from `since` (a date) to
        `until` (exclusive), in spans of CF_DAYS_PER_QUERY days."""
        acct, rows, day = self.cf_account(), [], since
        while day < until:
            end = min(day + dt.timedelta(days=CF_DAYS_PER_QUERY), until)
            body = json.dumps({"query": CF_QUERY, "variables": {
                "acct": acct, "site": self.env["LCARS_CF_SITE_TAG"], "path": path,
                "from": day.isoformat() + "T00:00:00Z", "to": end.isoformat() + "T00:00:00Z"}}).encode()
            st, j, text = self.get(CF_GRAPHQL, self.cf_headers(), body)
            if st != 200 or j is None or j.get("errors"):
                raise RuntimeError(f"cloudflare graphql: HTTP {st} {json.dumps((j or {}).get('errors') or text)[:200]}")
            rows += cf_rows(j)
            day = end
        return rows


CF_QUERY = """query($acct: String!, $site: String!, $path: String!, $from: Time!, $to: Time!) {
  viewer { accounts(filter: {accountTag: $acct}) {
    rumPageloadEventsAdaptiveGroups(limit: 5000, orderBy: [date_ASC],
      filter: {siteTag: $site, requestPath: $path, datetime_geq: $from, datetime_lt: $to}) {
      count dimensions { date refererHost } } } } }"""


def cf_rows(answer):
    out = []
    for acct in (((answer or {}).get("data") or {}).get("viewer") or {}).get("accounts") or []:
        for g in acct.get("rumPageloadEventsAdaptiveGroups") or []:
            d = g.get("dimensions") or {}
            out.append((d.get("date") or "", (d.get("refererHost") or "").lower(), int(g.get("count") or 0)))
    return out


def site_of(host):
    """A referer host, or a share URL's, as the site it is: www/old/out/m. of
    reddit are reddit, t.co is X, lnkd.in LinkedIn. A Mastodon reader comes
    from their own instance, so only the share's instance is matched."""
    h = (host or "").lower()
    h = re.sub(r"^(www|old|new|out|m|np|i|mobile)\.", "", h)
    if h in ("reddit.com", "redd.it") or h.endswith(".reddit.com"):
        return "reddit.com"
    if h in ("t.co", "x.com", "twitter.com"):
        return "x.com"
    if h in ("lnkd.in", "linkedin.com") or h.endswith(".linkedin.com"):
        return "linkedin.com"
    return h


# ---- the readings (pure) -------------------------------------------------------

def readings(shares, fetched, last, views, at):
    """What a run writes, from what it read:

    shares   parse_share's, oldest first
    fetched  {share id: (numbers or None, why not)}  the adapters' answers
    last     {share id: the newest crew_share_<id> row's JSON}  for a share
             with nothing this run, so the global sum does not dip
    views    [(day, referer host, page loads)] or None (no Cloudflare token),
             or a string (Cloudflare failed: why)
    at       the run's time (UTC)

    -> (per-share [(role, title, value_int, content)], global (title, value_int, content)).
    A share with no fresh numbers (no API answer and no line of its own) gets
    no reading: a repeated old number would draw as a flat line the share
    never had. Its last known one still counts in the global sum, marked stale.
    """
    at_s = iso(at)
    per, by_share, errors, stale, missing = [], {}, {}, [], []
    comments = 0
    site_shares = {}
    for s in shares:
        site_shares.setdefault(site_of(host_of(s["url"])), []).append(s["id"])
    have_views = isinstance(views, list)
    for s in shares:
        nums, why = fetched.get(s["id"], (None, "not fetched"))
        if nums is None and s["manual"]:
            nums = dict(s["manual"], main=manual_main(s["manual"]), source="manual")
            if why and adapter(s["url"]):
                errors[s["id"]] = why          # an API that failed, the line standing in
        elif nums is None:
            errors[s["id"]] = why
        if have_views:
            site = site_of(host_of(s["url"]))
            day0 = (s["created"] or "")[:10]
            bv = sum(n for d, h, n in views if h and site_of(h) == site and d >= day0)
        if nums is None:
            prev = last.get(s["id"])
            if prev and isinstance(prev.get("value"), int):
                by_share[s["id"]] = prev["value"]
                comments += int(prev.get("comments") or 0)
                stale.append(s["id"])
            else:
                missing.append(s["id"])
            continue
        main = nums["main"]
        value = int(nums.get(main) or 0)
        body = {"share": s["id"], "title": s["title"], "url": s["url"], "source": nums["source"], "main": main,
                "value": value}
        body.update({k: v for k, v in nums.items() if k not in ("main", "source")})
        if have_views:
            body["blog_views"] = bv
            body["blog_views_site"] = site
            others = [i for i in site_shares[site] if i != s["id"]]
            if others:
                body["blog_views_shared"] = others
        body["fetched_at"] = at_s
        if s["id"] in errors:
            body["error"] = errors[s["id"]]
        per.append((READING_PREFIX + str(s["id"]), f"{value} {main} · {s['title']}"[:200], value,
                    json.dumps(body, ensure_ascii=False)))
        by_share[s["id"]] = value
        comments += int(nums.get("comments") or 0)
    total = sum(by_share.values())
    g = {"fetched_at": at_s, "shares": len(shares), "value": total, "comments": comments,
         "by_share": {str(k): v for k, v in by_share.items()}}
    if have_views:
        g["blog_views"] = sum(n for _, _, n in views)
        g["blog_views_by_site"] = {}
        for _, h, n in views:
            k = site_of(h) or "(none)"
            g["blog_views_by_site"][k] = g["blog_views_by_site"].get(k, 0) + n
        g["blog_views_from_shares"] = sum(v for k, v in g["blog_views_by_site"].items() if k in site_shares)
    elif isinstance(views, str):
        g["blog_views_error"] = views
    if stale:
        g["stale"] = stale
    if missing:
        g["missing"] = missing
    if errors:
        g["errors"] = {str(k): v for k, v in errors.items()}
    title = f"{total} · blog post, {len(shares)} share{'s' if len(shares) != 1 else ''}"
    return per, (title, total, json.dumps(g, ensure_ascii=False))


# ---- one run ---------------------------------------------------------------------

def collect(T, fm, fetcher=None, at=None):
    """Read the share entries, their last readings and the sources (crew_tool
    as T, for the journal); -> readings()'s answer and a summary for the run
    log. Writes nothing: crew.py's finish posts what this returns."""
    at = at or now_utc()
    env = T.read_env()
    f = fetcher or Fetcher(env)
    rows = [r for r in T.entries_all(kind=T.roles().kind("share")) if not r.get("deleted")]
    shares = sorted(filter(None, map(parse_share, rows)), key=lambda s: (s["created"], s["id"]))
    fetched = {s["id"]: f.numbers(s) for s in shares}
    last = {}
    for s in shares:
        if fetched[s["id"]][0] is None:
            got = T.entries(kind="crew_" + READING_PREFIX + str(s["id"]), order="created", dir="desc", limit=1)
            try:
                last[s["id"]] = json.loads(got[0].get("content") or "{}") if got else None
            except ValueError:
                last[s["id"]] = None
    views = None
    # the post: the role's `post:` (crew/context.local.md lays it over
    # crew/shares.md) or LCARS_SHARES_POST; with neither, no views
    post = fm.get("post") or env.get("LCARS_SHARES_POST")
    if shares and post and f.cf_ready():
        path = urllib.parse.urlsplit(post).path or "/"
        today = at.date()
        since = max(min(dt.date.fromisoformat(s["created"][:10]) for s in shares if s["created"][:10]
                        ) if any(s["created"][:10] for s in shares) else today, today - dt.timedelta(days=CF_MAX_DAYS))
        try:
            views = f.cf_views(path, since, today + dt.timedelta(days=1))
        except (RuntimeError, OSError, ValueError, KeyError) as e:
            views = str(e)[:200]
    return shares, readings(shares, fetched, last, views, at)
