#!/usr/bin/env python3
"""The social watch: new comments and the daily numbers of the captain's
accounts (crew/social.md, no model; docs/design/social-watch.md).

Every hour the role reads, with no credential of its own beyond the box's:

- Hacker News, through Algolia's public API (hn.algolia.com): the
  comments under the captain's stories of the last 30 days, and the direct
  replies to their comments of the last 14; points and comment counts per story.
- GitHub, with the box's `gh` login (LCARS_SOCIAL_GITHUB, a fine-grained
  token, when set): new issues and pull requests by others, their
  comments and review comments, discussions where a repo has them; stars,
  forks, and the traffic API's views, clones, paths and referrers.
- Cloudflare Web Analytics (LCARS_CF_ANALYTICS_TOKEN, else the box's
  CLOUDFLARE_API_TOKEN): visits and page views by site, page and referrer,
  bots excluded. Stats only.

and writes, with the crew login (crew.py's finish):

- `crew_social_comment`, one entry per new comment, line-keyed (`id:`,
  `platform:`, `link:`, `on:`, `parent:`, `author:`, `at:`, `status:`, then
  the text): `done_bool` 1 when the captain has replied (their comment a
  child of it), seen on the first read or by a later run;
- `crew_social_<platform>`, one reading per platform per captain's day,
  written by the first run after the captain's midnight for the day before;
- `task_crew_social`, one notice per run that found comments the captain has
  not answered (not one per comment: Reminders would fill up);
- `crew_social`, the run's own entry, only when something happened.

Seen lives in the journal: a comment is new when no `crew_social_comment`
of the last 60 days has its `id:` line. A platform failing is a line in
the run's entry, which carries the count of runs in a row it has failed
(`failures:`), read back by the next run; the third raises one task_crew.

Read only: every request goes through `Net`, which refuses any method but
GET, save a POST of a GraphQL query (not a mutation) to Cloudflare's or
GitHub's GraphQL endpoint. Nothing is ever posted to a platform.

The names (the HN user, the repos, the Cloudflare sites) are the role's
front matter, which crew/context.local.md fills in for this box.
"""

import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

HN_API = "https://hn.algolia.com/api/v1/"
GH_API = "https://api.github.com"
GH_GRAPHQL = GH_API + "/graphql"
CF_API = "https://api.cloudflare.com/client/v4"
CF_GRAPHQL = CF_API + "/graphql"
PLATFORMS = ("hn", "github", "cf")
NAMES = {"hn": "HN", "github": "GitHub", "cf": "Cloudflare"}
COMMENT = "social_comment"        # crew_social_comment, through crew_tool.post's crew_ prefix
NOTICE_LIST = "social"            # <task>_crew_social: the crew's reminders, its own list
SEEN_DAYS = 60
HN_STORY_DAYS, HN_REPLY_DAYS, GH_DAYS = 30, 14, 14
FAIL_RAISE = 3                    # runs in a row a platform fails before one task_crew
UA = "lcars-social-watch/1.0 (read only)"
# The only writes a platform may see: none in this slice. The OAuth token
# endpoints of the later slices (reddit, Google, X) go here, and only here.
TOKEN_ENDPOINTS = ()
GRAPHQL_ENDPOINTS = (CF_GRAPHQL, GH_GRAPHQL)


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return dt.datetime.fromisoformat((s or "").replace("Z", "+00:00"))


# ---- HTTP: read only -----------------------------------------------------------

class ReadOnly(RuntimeError):
    """A request the watch must never make: a write to a platform."""


def _http(method, url, headers=None, data=None, timeout=20):
    """(status, parsed JSON or None, text) - a 4xx/5xx is an answer, not a raise."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            st, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, text = e.code, e.read().decode("utf-8", "replace")
    try:
        return st, json.loads(text), text
    except ValueError:
        return st, None, text


def check_read_only(method, url, data):
    """Raise ReadOnly for anything but a read: GET, or a GraphQL query
    POSTed to the two GraphQL endpoints (their reads are POSTs), or a
    token endpoint's POST. A GraphQL body that is a mutation is a write."""
    if method == "GET" and data is None:
        return
    base = url.split("?", 1)[0]
    if method == "POST" and base in TOKEN_ENDPOINTS:
        return
    if method == "POST" and base in GRAPHQL_ENDPOINTS:
        try:
            q = json.loads(data or b"{}").get("query") or ""
        except (ValueError, AttributeError):
            q = ""
        if q and not re.match(r"\s*mutation\b", q):
            return
    raise ReadOnly(f"the watch only reads: {method} {base} refused")


class Net:
    """Every request of a run, checked and recorded (method, url): the test
    reads `asked` to prove nothing but reads went out."""

    def __init__(self, http=None):
        # _http looked up now, not bound as a default: a test stands in for it
        self.http, self.asked = http or _http, []

    def __call__(self, method, url, headers=None, data=None):
        check_read_only(method, url, data)
        self.asked.append((method, url))
        return self.http(method, url, dict(headers or {}, **{"User-Agent": UA}), data)


def _refused(what, st, text):
    plain = re.sub(r"<[^>]+>|\s+", " ", text or "")[:120].strip()
    return RuntimeError(f"{what}: HTTP {st} {plain}".rstrip())


# ---- text --------------------------------------------------------------------------

def plain(text):
    """A platform's HTML (HN's comment_text, GitHub's is markdown already)
    as plain text: paragraphs kept, a link's address kept, entities undone."""
    t = text or ""
    t = re.sub(r"<a\s[^>]*href=\"([^\"]*)\"[^>]*>.*?</a>", lambda m: html.unescape(m.group(1)), t, flags=re.S | re.I)
    t = re.sub(r"<p>|<br\s*/?>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\r\n", "\n")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def first_words(text, n=60):
    s = re.sub(r"\s+", " ", text or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def comment(platform, cid, link, on, parent, author, at, text, replied=False):
    return {"id": f"{platform}:{cid}", "platform": platform, "link": link, "on": on, "parent": parent,
            "author": author or "?", "at": at, "text": text, "replied": bool(replied)}


# ---- Hacker News -------------------------------------------------------------------

DEAD = {"[dead]", "[flagged]", "[deleted]"}


def hn_link(i):
    return f"https://news.ycombinator.com/item?id={i}"


def hn_alive(author, text):
    """A deleted comment has no author or text; a dead one is [dead]/[flagged]."""
    return bool(author) and bool((text or "").strip()) and plain(text) not in DEAD


class Fetcher:
    """One run's reads, per platform; each raises RuntimeError on a failure,
    which costs that platform alone."""

    def __init__(self, env, fm, net=None, run=None):
        self.env, self.fm = env, fm
        self.net = net or Net()
        # `gh auth token` looked up now: a test stands in for it
        self.run = run or subprocess.run
        self._gh_token = None

    def configured(self, p):
        """(ready, why not) for a platform: what it needs, said once."""
        if p == "hn":
            return (True, "") if self.fm.get("hn_user") else (False, "no hn_user in the role's front matter")
        if p == "github":
            return (True, "") if self.repos() else (False, "no github_repos in the role's front matter")
        if p == "cf":
            if not self.cf_sites():
                return False, "no cf_sites in the role's front matter"
            return (True, "") if self.cf_token() else (False, "no LCARS_CF_ANALYTICS_TOKEN or CLOUDFLARE_API_TOKEN")
        return False, "unknown"

    def json(self, what, url, headers=None, data=None, method="GET"):
        st, j, text = self.net(method, url, headers, data)
        if st != 200 or j is None:
            raise _refused(what, st, text)
        return j

    # -- HN --

    def hn(self, at, daily):
        """(comments, stats or None). Algolia only: one host, and its hits
        carry the story's title, which Firebase's items do not."""
        u = self.fm["hn_user"]
        t_story = int((at - dt.timedelta(days=HN_STORY_DAYS)).timestamp())
        t_reply = int((at - dt.timedelta(days=HN_REPLY_DAYS)).timestamp())
        q = HN_API + "search_by_date?tags={tags}&numericFilters=created_at_i>{t}&hitsPerPage={n}"
        stories = self.json("hn stories", q.format(tags=f"story,author_{u}", t=t_story, n=100)).get("hits") or []
        mine = self.json("hn comments", q.format(tags=f"comment,author_{u}", t=t_story, n=1000)).get("hits") or []
        # the captain's reply to a comment is their comment whose parent it is
        replied = {str(h.get("parent_id")) for h in mine}
        own = {str(h["objectID"]) for h in mine}
        titles = {str(s["objectID"]): s.get("title") or "" for s in stories}
        titles.update({str(h.get("story_id")): h.get("story_title") or "" for h in mine})
        found = {}

        def add(cid, author, text, at_i, parent_id, story_id):
            cid, parent_id, story_id = str(cid), str(parent_id), str(story_id)
            if author == u or not hn_alive(author, text) or ("hn:" + cid) in found:
                return
            parent = ("story" if parent_id == story_id else
                      f"the captain's comment #{parent_id}" if parent_id in own else f"comment #{parent_id}")
            on = f"{titles.get(story_id) or 'story ' + story_id} ({hn_link(story_id)})"
            at_s = iso(dt.datetime.fromtimestamp(int(at_i or 0), dt.timezone.utc))
            found["hn:" + cid] = comment("hn", cid, hn_link(cid), on, parent, author, at_s, plain(text),
                                         cid in replied)

        for s in stories:
            sid = s["objectID"]
            hits = self.json("hn story comments", HN_API + f"search_by_date?tags=comment,story_{sid}&hitsPerPage=1000")
            for h in hits.get("hits") or []:
                add(h["objectID"], h.get("author"), h.get("comment_text"), h.get("created_at_i"), h.get("parent_id"),
                    h.get("story_id") or sid)
        for c in mine:
            if int(c.get("created_at_i") or 0) <= t_reply:
                continue
            item = self.json("hn item", HN_API + f"items/{c['objectID']}")
            for k in item.get("children") or []:
                add(k.get("id"), k.get("author"), k.get("text"), k.get("created_at_i"), k.get("parent_id"),
                    k.get("story_id") or c.get("story_id"))
        stats = None
        if daily:
            items = [{"id": int(s["objectID"]), "title": s.get("title") or "", "points": int(s.get("points") or 0),
                      "comments": int(s.get("num_comments") or 0)} for s in stories]
            stats = {"value": sum(i["points"] for i in items), "main": "points",
                     "comments": sum(i["comments"] for i in items), "items": items}
        return list(found.values()), stats

    # -- GitHub --

    def repos(self):
        return (self.fm.get("github_repos") or "").split()

    def gh_user(self):
        return self.fm.get("github_user") or ""

    def gh_token(self):
        if self._gh_token is None:
            tok = self.env.get("LCARS_SOCIAL_GITHUB") or ""
            if not tok:
                try:
                    p = self.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
                    tok = p.stdout.strip() if p.returncode == 0 else ""
                except (OSError, subprocess.TimeoutExpired):
                    tok = ""
            if not tok:
                raise RuntimeError("no GitHub token: LCARS_SOCIAL_GITHUB unset and `gh auth token` gave none")
            self._gh_token = tok
        return self._gh_token

    def gh_headers(self, accept="application/vnd.github+json"):
        return {"Authorization": "Bearer " + self.gh_token(), "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}

    def gh(self, path, accept="application/vnd.github+json", ok=(200,)):
        st, j, text = self.net("GET", GH_API + path, self.gh_headers(accept))
        if st not in ok or j is None:
            raise _refused("github " + path.split("?")[0], st, text)
        return st, j

    def gh_repo(self, full):
        """The owner/name a front matter line gives: a bare name is the user's."""
        return full if "/" in full else f"{self.gh_user()}/{full}"

    def github(self, at, daily, last=None):
        since = iso(at - dt.timedelta(days=GH_DAYS))
        me, found, stats = self.gh_user().lower(), {}, {}
        for full in map(self.gh_repo, self.repos()):
            _, meta = self.gh(f"/repos/{full}")
            _, issues = self.gh(f"/repos/{full}/issues?state=all&since={since}&per_page=100")
            _, ic = self.gh(f"/repos/{full}/issues/comments?since={since}&per_page=100")
            _, rc = self.gh(f"/repos/{full}/pulls/comments?since={since}&per_page=100")
            by_num = {int(i["number"]): i for i in issues}
            # the captain's comments by thread, for "replied": a later one there
            mine_at = {}
            for c in ic + rc:
                if (c.get("user") or {}).get("login", "").lower() == me:
                    mine_at.setdefault(gh_number(c), []).append(c.get("created_at") or "")

            def thread(n):
                i = by_num.get(n) or {}
                what = "pull request" if i.get("pull_request") or not i else "issue"
                return what, f"{full}#{n} {i.get('title') or ''}".strip() + f" ({i.get('html_url') or ''})"

            for i in issues:
                u = i.get("user") or {}
                if u.get("login", "").lower() == me or u.get("type") == "Bot" or (i.get("created_at") or "") < since:
                    continue
                n = int(i["number"])
                what = "pull request" if i.get("pull_request") else "issue"
                text = (i.get("title") or "") + ("\n\n" + i["body"] if i.get("body") else "")
                found[f"github:{full}#{n}"] = comment(
                    "github", f"{full}#{n}", i.get("html_url"), f"{full} ({meta.get('html_url') or ''})",
                    f"new {what}", u.get("login"), i.get("created_at"), text.strip(),
                    any(t > (i.get("created_at") or "") for t in mine_at.get(n, [])))
            for c in ic + rc:
                u = c.get("user") or {}
                if u.get("login", "").lower() == me or u.get("type") == "Bot":
                    continue
                n = gh_number(c)
                what, on = thread(n)
                kind = "review comment" if "pull_request_review_id" in c else "comment"
                cid = f"{full}/{'r' if kind == 'review comment' else 'c'}{c['id']}"
                found["github:" + cid] = comment(
                    "github", cid, c.get("html_url"), on, f"{what} #{n} ({kind})", u.get("login"),
                    c.get("created_at"), (c.get("body") or "").strip(),
                    any(t > (c.get("created_at") or "") for t in mine_at.get(n, [])))
            if meta.get("has_discussions"):
                for c in self.gh_discussions(full, since):
                    found[c["id"]] = c
            if daily:
                stats[full] = self.gh_daily(full, meta, daily, (last or {}).get(full) or {}, at)
        if not daily:
            return list(found.values()), None
        stars = sum(r["stars"] for r in stats.values())
        return list(found.values()), {"value": stars, "main": "stars", "forks": sum(r["forks"] for r in stats.values()),
                                      "views": sum(r.get("views", 0) for r in stats.values()),
                                      "clones": sum(r.get("clones", 0) for r in stats.values()), "repos": stats}

    def gh_discussions(self, full, since):
        owner, name = full.split("/", 1)
        q = ("query($o: String!, $n: String!) { repository(owner: $o, name: $n) { "
             "discussions(first: 20, orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { "
             "number title url createdAt bodyText author { login __typename } "
             "comments(last: 50) { nodes { databaseId url createdAt bodyText author { login __typename } } } } } } }")
        j = self.json("github graphql", GH_GRAPHQL, self.gh_headers(), json.dumps(
            {"query": q, "variables": {"o": owner, "n": name}}).encode(), method="POST")
        if j.get("errors"):
            raise RuntimeError("github graphql: " + json.dumps(j["errors"])[:200])
        me, out = self.gh_user().lower(), []
        nodes = ((((j.get("data") or {}).get("repository") or {}).get("discussions") or {}).get("nodes")) or []
        for d in nodes:
            on = f"{full} discussion #{d['number']} {d.get('title') or ''} ({d.get('url') or ''})"
            cs = (d.get("comments") or {}).get("nodes") or []
            mine_at = [c.get("createdAt") or "" for c in cs if ((c.get("author") or {}).get("login") or "").lower() == me]
            who = ((d.get("author") or {}).get("login") or "")
            # giscus (the blog's comments) opens a discussion per post as a
            # Bot: the thread is no one's comment, its comments are readers'
            if who.lower() != me and not is_bot(d) and (d.get("createdAt") or "") >= since:
                out.append(comment("github", f"{full}/d{d['number']}", d.get("url"), f"{full}", "new discussion", who,
                                   d.get("createdAt"), ((d.get("title") or "") + "\n\n" + (d.get("bodyText") or "")).strip(),
                                   any(t > d.get("createdAt", "") for t in mine_at)))
            for c in cs:
                who = ((c.get("author") or {}).get("login") or "")
                if who.lower() == me or is_bot(c) or (c.get("createdAt") or "") < since:
                    continue
                out.append(comment("github", f"{full}/dc{c['databaseId']}", c.get("url"), on,
                                   f"discussion #{d['number']}", who, c.get("createdAt"),
                                   (c.get("bodyText") or "").strip(), any(t > c.get("createdAt", "") for t in mine_at)))
        return out

    def gh_daily(self, full, meta, day, last, at):
        """A repo's numbers for the captain's `day`: stars and forks now, who
        starred and forked that day, and the traffic API's days not yet in a
        reading (UTC days, complete ones only, after the last reading's
        `traffic_through`: the 14 days it keeps are taken once each)."""
        lo, hi = day_bounds(day)
        out = {"stars": int(meta.get("stargazers_count") or 0), "forks": int(meta.get("forks_count") or 0),
               "issues_open": int(meta.get("open_issues_count") or 0)}
        if out["stars"]:
            # newest last: the last page holds the day's
            page = (out["stars"] - 1) // 100 + 1
            _, sg = self.gh(f"/repos/{full}/stargazers?per_page=100&page={page}", "application/vnd.github.star+json")
            out["new_stars"] = [(s.get("user") or {}).get("login") for s in sg
                                if lo <= parse_iso(s.get("starred_at")) < hi]
        if out["forks"]:
            _, fk = self.gh(f"/repos/{full}/forks?sort=newest&per_page=30")
            out["new_forks"] = [(f.get("owner") or {}).get("login") for f in fk
                                if lo <= parse_iso(f.get("created_at")) < hi]
        today_utc = iso(at)[:10]       # its day is not over: never a part-day
        through = last.get("traffic_through") or ""
        st, v = self.gh(f"/repos/{full}/traffic/views", ok=(200, 403))
        if st == 403:
            out["traffic"] = "refused: the token needs push access to read traffic"
            return out
        _, c = self.gh(f"/repos/{full}/traffic/clones")
        days = {}
        for kind, rows in (("views", v.get("views") or []), ("clones", c.get("clones") or [])):
            for r in rows:
                d = (r.get("timestamp") or "")[:10]
                if through < d < today_utc:
                    days.setdefault(d, {})[kind] = [int(r.get("count") or 0), int(r.get("uniques") or 0)]
        # the days taken, kept as through; only the ones with a visit listed
        out["traffic_days"] = {d: x for d, x in sorted(days.items()) if any(v[0] for v in x.values())}
        out["views"] = sum(x.get("views", [0])[0] for x in days.values())
        out["clones"] = sum(x.get("clones", [0])[0] for x in days.values())
        out["traffic_through"] = max(days) if days else through
        _, paths = self.gh(f"/repos/{full}/traffic/popular/paths")
        _, refs = self.gh(f"/repos/{full}/traffic/popular/referrers")
        out["paths_14d"] = [[p.get("path"), int(p.get("count") or 0), int(p.get("uniques") or 0)] for p in paths]
        out["referrers_14d"] = [[r.get("referrer"), int(r.get("count") or 0), int(r.get("uniques") or 0)] for r in refs]
        return out

    # -- Cloudflare --

    def cf_token(self):
        return self.env.get("LCARS_CF_ANALYTICS_TOKEN") or self.env.get("CLOUDFLARE_API_TOKEN") or ""

    def cf_sites(self):
        """`cf_sites: blog=<tag> demo=<tag>` -> [(name, tag)]."""
        return [tuple(x.split("=", 1)) for x in (self.fm.get("cf_sites") or "").split() if "=" in x]

    def cf_headers(self):
        return {"Authorization": "Bearer " + self.cf_token(), "Content-Type": "application/json"}

    def cf_account(self):
        acct = self.env.get("LCARS_CF_ACCOUNT_ID") or self.env.get("CLOUDFLARE_ACCOUNT_ID")
        if acct:
            return acct
        res = self.json("cloudflare accounts", CF_API + "/accounts?per_page=5", self.cf_headers()).get("result") or []
        if not res:
            raise RuntimeError("cloudflare accounts: none (set LCARS_CF_ACCOUNT_ID)")
        return res[0]["id"]

    def cf(self, at, daily):
        if not daily:
            return [], None
        lo, hi = day_bounds(daily)
        acct, sites = self.cf_account(), {}
        for name, tag in self.cf_sites():
            body = json.dumps({"query": CF_QUERY, "variables": {"acct": acct, "site": tag, "from": iso(lo),
                                                                 "to": iso(hi)}}).encode()
            j = self.json("cloudflare graphql", CF_GRAPHQL, self.cf_headers(), body, method="POST")
            if j.get("errors"):
                raise RuntimeError("cloudflare graphql: " + json.dumps(j["errors"])[:200])
            sites[name] = cf_site(j)
        return [], {"value": sum(s["visits"] for s in sites.values()), "main": "visits",
                    "views": sum(s["views"] for s in sites.values()), "sites": sites}


CF_QUERY = """query($acct: String!, $site: String!, $from: Time!, $to: Time!) {
  viewer { accounts(filter: {accountTag: $acct}) {
    rumPageloadEventsAdaptiveGroups(limit: 5000,
      filter: {siteTag: $site, bot: 0, datetime_geq: $from, datetime_lt: $to}) {
      count sum { visits } dimensions { requestHost requestPath refererHost } } } } }"""


def cf_site(answer, top=10):
    """One site's RUM groups -> visits, page views, and the top pages and
    referrers by visits ("(none)": typed in, a bookmark, an app)."""
    pages, refs, visits, views = {}, {}, 0, 0
    for acct in (((answer or {}).get("data") or {}).get("viewer") or {}).get("accounts") or []:
        for g in acct.get("rumPageloadEventsAdaptiveGroups") or []:
            d, n, v = g.get("dimensions") or {}, int(g.get("count") or 0), int((g.get("sum") or {}).get("visits") or 0)
            visits, views = visits + v, views + n
            p = (d.get("requestHost") or "") + (d.get("requestPath") or "")
            r = (d.get("refererHost") or "").lower() or "(none)"
            pages[p] = [pages.get(p, [0, 0])[0] + v, pages.get(p, [0, 0])[1] + n]
            refs[r] = [refs.get(r, [0, 0])[0] + v, refs.get(r, [0, 0])[1] + n]

    def best(m):
        return [[k] + m[k] for k in sorted(m, key=lambda k: (-m[k][0], -m[k][1], k))[:top]]
    return {"visits": visits, "views": views, "pages": best(pages), "referrers": best(refs)}


def is_bot(node):
    return ((node.get("author") or {}).get("__typename") or "") == "Bot"


def gh_number(c):
    """An issue or review comment's thread number, from its issue/PR url."""
    u = c.get("issue_url") or c.get("pull_request_url") or ""
    m = re.search(r"/(\d+)$", u)
    return int(m.group(1)) if m else 0


def day_bounds(day):
    """The captain's local day as UTC datetimes [lo, hi)."""
    import crew_tool as T
    lo = dt.datetime.combine(day, dt.time(), T.TZ)
    hi = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), T.TZ)
    return lo.astimezone(dt.timezone.utc), hi.astimezone(dt.timezone.utc)


# ---- what a run writes (pure) ------------------------------------------------------

def seen_ids(rows):
    """{comment id: row} of the crew_social_comment rows read back."""
    out = {}
    for r in rows:
        m = re.search(r"^id: (\S+)$", r.get("content") or "", re.M)
        if m and not r.get("deleted"):
            out[m.group(1)] = r
    return out


def comment_entry(c):
    """(title, content, done) of one crew_social_comment."""
    title = f"{NAMES[c['platform']]} · {c['author']}: {first_words(c['text'])}"[:200]
    status = "replied" if c["replied"] else "new"
    content = (f"id: {c['id']}\nplatform: {c['platform']}\nlink: {c['link']}\non: {c['on']}\n"
               f"parent: {c['parent']}\nauthor: {c['author']}\nat: {c['at']}\nstatus: {status}\n\n{c['text']}\n")
    return title, content, 1 if c["replied"] else 0


def last_failures(text):
    """The `failures: hn=1 github=3` line of the last run's entry -> {p: n}."""
    m = re.search(r"^failures: (.*)$", text or "", re.M)
    out = {}
    for part in (m.group(1).split() if m else []):
        k, _, v = part.partition("=")
        if k in PLATFORMS and v.isdigit():
            out[k] = int(v)
    return out


def reading(p, day, stats, at):
    """(role, title, value_int, content) of one daily crew_social_<p>."""
    value = int(stats["value"])
    unit = stats["main"] if value != 1 else stats["main"][:-1]
    body = dict(stats, day=day.isoformat(), fetched_at=iso(at))
    return (f"social_{p}", f"{value:,} {unit} · {NAMES[p]}", value, json.dumps(body, ensure_ascii=False))


def plan(found, seen, failed, prev_fail, daily_done, stats, day, at):
    """What a run writes, from what it read:

    found       {platform: [comment]}  this run's comments (a failed platform absent)
    seen        seen_ids()'s map       the comments already in the journal
    failed      {platform: why}
    prev_fail   {platform: n}          the last run's counts
    daily_done  {platform: bool}       the day's reading already in the journal
    stats       {platform: stats}      this run's daily numbers (None: not due or failed)

    -> {"comments": [(title, content, done, comment)], "patches": [(row, content)],
        "readings": [...], "failures": {p: n}, "raise": [p], "lines": [str], "notice": [comment]}
    """
    new, patches = [], []
    for p in PLATFORMS:
        for c in found.get(p) or []:
            row = seen.get(c["id"])
            if row is None:
                new.append(c)
            elif c["replied"] and re.search(r"^status: new$", row.get("content") or "", re.M):
                # the captain's reply seen by a later poll: the comment is answered
                patches.append((row, re.sub(r"^status: new$", "status: replied", row["content"], count=1, flags=re.M)))
    new.sort(key=lambda c: (c["at"], c["id"]))
    fails = {p: (prev_fail.get(p, 0) + 1 if p in failed else 0) for p in PLATFORMS}
    lines = []
    for p in PLATFORMS:
        if p in failed:
            n = fails[p]
            lines.append(f"- {NAMES[p]}: failed, {failed[p]}" + (f" ({n} runs in a row)" if n > 1 else ""))
            continue
        k = sum(1 for c in new if c["platform"] == p)
        if k:
            lines.append(f"- {NAMES[p]}: {k} new comment{'s' if k != 1 else ''}")
        if prev_fail.get(p):
            lines.append(f"- {NAMES[p]}: reading again after {prev_fail[p]} failed run{'s' if prev_fail[p] != 1 else ''}")
    readings = []
    for p in PLATFORMS:
        if stats.get(p) is not None and not daily_done.get(p):
            r = reading(p, day, stats[p], at)
            readings.append(r)
            lines.append(f"- {NAMES[p]}: {day.isoformat()}'s reading, {r[1]}")
    for row, _ in patches:
        lines.append(f"- #{row['id']}: answered, marked replied")
    notice = [c for c in new if not c["replied"]]
    return {"comments": [comment_entry(c) + (c,) for c in new], "patches": patches, "readings": readings,
            "failures": fails, "raise": [p for p in PLATFORMS if fails[p] == FAIL_RAISE], "lines": lines,
            "notice": notice, "recovered": [p for p in PLATFORMS if prev_fail.get(p) and p not in failed]}


def notice_title(cs):
    by = {}
    for c in cs:
        by[NAMES[c["platform"]]] = by.get(NAMES[c["platform"]], 0) + 1
    n = len(cs)
    return f"{n} new comment{'s' if n != 1 else ''}: " + ", ".join(f"{k} {v}" for k, v in by.items())


def notice_body(cs, ids):
    """One block per comment: its link, author, first line, and its entry."""
    out = []
    for c, i in zip(cs, ids):
        out.append(f"{NAMES[c['platform']]} · {c['author']} on {c['on']}\n{first_words(c['text'], 140)}\n"
                   f"{c['link']}" + (f"\n#{i}" if i else ""))
    return "\n\n".join(out)


# ---- one run -----------------------------------------------------------------------

def collect(T, fm, fetcher=None, at=None):
    """Read the journal's side (seen comments, the last run's failures, the
    day's readings) and the platforms; -> plan()'s answer, plus "day" and
    "secs". Writes nothing: crew.py's run_social and finish post it."""
    at = at or now_utc()
    env = dict(T.read_env())
    f = fetcher or Fetcher(env, fm)
    today = at.astimezone(T.TZ).date()
    day = today - dt.timedelta(days=1)
    since = (today - dt.timedelta(days=SEEN_DAYS)).isoformat()
    seen = seen_ids(T.entries_all(kind="crew_" + COMMENT, since=since))
    last = T.entries(kind="crew_social", order="created", dir="desc", limit=1)
    prev_fail = last_failures(last[0].get("content") if last else "")
    found, failed, stats, daily_done, skipped, last_stats = {}, {}, {}, {}, {}, {}
    for p in PLATFORMS:
        ok, why = f.configured(p)
        if not ok:
            skipped[p] = why
            continue
        got = T.entries(kind="crew_social_" + p, order="created", dir="desc", limit=1)
        try:
            last_stats[p] = json.loads(got[0].get("content") or "{}") if got else {}
        except ValueError:
            last_stats[p] = {}
        daily_done[p] = last_stats[p].get("day") == day.isoformat()
        due = None if daily_done[p] else day
        try:
            if p == "github":
                found[p], stats[p] = f.github(at, due, last_stats[p].get("repos"))
            else:
                found[p], stats[p] = getattr(f, p)(at, due)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as e:
            failed[p] = str(e)[:200]
    out = plan(found, seen, failed, prev_fail, daily_done, stats, day, at)
    out.update(day=day, skipped=skipped, failed_why=failed, asked=len(getattr(f.net, "asked", [])))
    return out
