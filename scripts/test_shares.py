#!/usr/bin/env python3
"""Unit tests for the shares role (scripts/shares.py, crew.py run_shares).
No network, no journal: the adapters read saved responses
(scripts/testdata/shares/: hn_item.json and mastodon_status.json are real
answers, trimmed; reddit's and Cloudflare's are made to their documented
shape, as the box cannot reach either without the captain's credentials),
and a whole run posts to a stand-in server.

    python3 scripts/test_shares.py
"""

import datetime as dt
import http.server
import io
import json
import os
import sys
import threading
import unittest
import urllib.parse
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["LCARS_ENG_SEAT"] = "0"
os.environ["LCARS_CREW_TZ"] = "Europe/Helsinki"  # the captain's zone, never the box's
import crew as C  # noqa: E402
import crew_tool as T  # noqa: E402
import shares as S  # noqa: E402
from test_crew import Base  # noqa: E402

DATA = os.path.join(HERE, "testdata", "shares")
AT = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc)
REDDIT = "https://www.reddit.com/r/ClaudeAI/comments/1o9xk2q/i_built_a_star_trek_journal/"


def sample(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def share(i, url, title, created="2026-10-18T09:00:00Z", extra=""):
    return {"id": i, "kind": "share", "title": title, "content": f"{url}\n{extra}", "created_at_utc": created,
            "deleted": 0}


class Samples:
    """A stand-in for shares._get answering from the saved responses, and
    recording what it was asked."""

    def __init__(self, reddit_status=200, block=False):
        self.asked, self.reddit_status, self.block = [], reddit_status, block

    def __call__(self, url, headers=None, data=None, timeout=20):
        self.asked.append((url, dict(headers or {}), data))
        if "access_token" in url:
            return 200, sample("reddit_token.json"), ""
        if "oauth.reddit.com" in url:
            if self.block:
                return 403, None, "<!doctype html><html><head><title>Blocked</title>"
            return self.reddit_status, sample("reddit_info.json"), ""
        if "hn.algolia.com" in url:
            return 200, sample("hn_item.json"), ""
        if "/api/v1/statuses/" in url:
            return 200, sample("mastodon_status.json"), ""
        if url.startswith(S.CF_GRAPHQL):
            return 200, sample("cf_rum.json"), ""
        if "/client/v4/accounts" in url:
            return 200, {"result": [{"id": "acct123"}]}, ""
        return 404, None, "not here"


ENV = {"LCARS_REDDIT_CLIENT_ID": "cid", "LCARS_REDDIT_SECRET": "sec", "LCARS_CF_ANALYTICS_TOKEN": "cft",
       "LCARS_CF_SITE_TAG": "site1", "LCARS_SHARES_POST": "https://blog.example/posts/lcars_journal/"}


class Adapters(unittest.TestCase):
    def test_urls_pick_their_adapter(self):
        self.assertEqual(S.adapter(REDDIT), "reddit")
        self.assertEqual(S.adapter("https://old.reddit.com/r/x/comments/abc/t/"), "reddit")
        self.assertEqual(S.adapter("https://news.ycombinator.com/item?id=8863"), "hn")
        self.assertEqual(S.adapter("https://mastodon.social/@Gargron/1"), "mastodon")
        self.assertEqual(S.adapter("https://hachyderm.io/users/me/statuses/123"), "mastodon")
        for u in ("https://x.com/me/status/123", "https://www.linkedin.com/posts/me-123", "https://example.com/a"):
            self.assertIsNone(S.adapter(u), u)
        self.assertEqual(S.reddit_id(REDDIT), "1o9xk2q")
        self.assertEqual(S.reddit_id("https://redd.it/1o9xk2q"), "1o9xk2q")
        self.assertIsNone(S.reddit_id("https://www.reddit.com/r/ClaudeAI/s/3ipqdN8Lbi"))
        self.assertEqual(S.hn_id("https://news.ycombinator.com/item?id=8863"), "8863")
        self.assertEqual(S.mastodon_id("https://mastodon.social/@Gargron/1"), "1")

    def test_reddit_app_only_oauth(self):
        get = Samples()
        f = S.Fetcher(ENV, get)
        n, why = f.numbers(S.parse_share(share(1, REDDIT, "r/ClaudeAI")))
        self.assertIsNone(why)
        self.assertEqual(n, {"main": "score", "score": 312, "upvote_ratio": 0.94, "comments": 47, "crossposts": 2,
                             "source": "reddit"})
        (tok_url, tok_h, tok_body), (info_url, info_h, _) = get.asked
        self.assertEqual(tok_url, "https://www.reddit.com/api/v1/access_token")
        self.assertEqual(tok_body, b"grant_type=client_credentials")
        self.assertEqual(tok_h["Authorization"], "Basic Y2lkOnNlYw==")       # cid:sec
        self.assertIn("lcars-shares", tok_h["User-Agent"])
        self.assertEqual(info_url, "https://oauth.reddit.com/api/info?id=t3_1o9xk2q&raw_json=1")
        self.assertTrue(info_h["Authorization"].startswith("bearer eyJ"))
        f.numbers(S.parse_share(share(2, "https://redd.it/1o9xk2q", "again")))
        self.assertEqual(sum("access_token" in u for u, _, _ in get.asked), 1)    # one token a run

    def test_reddit_refusals_say_why(self):
        s = S.parse_share(share(1, REDDIT, "r/ClaudeAI"))
        self.assertIn("no LCARS_REDDIT_CLIENT_ID", S.Fetcher({}, Samples()).numbers(s)[1])
        self.assertIn("reddit blocks this box", S.Fetcher(ENV, Samples(block=True)).numbers(s)[1])
        short = S.parse_share(share(1, "https://www.reddit.com/r/ClaudeAI/s/3ipqdN8Lbi", "r/ClaudeAI"))
        self.assertIn("full /comments/ URL", S.Fetcher(ENV, Samples()).numbers(short)[1])
        self.assertIn("no such post", str(self.raises(S.reddit_numbers, {"data": {"children": []}})))

    def raises(self, fn, *a):
        with self.assertRaises(ValueError) as cm:
            fn(*a)
        return cm.exception

    def test_hn_points_and_the_comment_tree(self):
        n, why = S.Fetcher(ENV, Samples()).numbers(S.parse_share(share(1, "https://news.ycombinator.com/item?id=8863", "HN")))
        self.assertEqual(n, {"main": "points", "points": 104, "comments": 5, "source": "hn"})
        self.raises(S.hn_numbers, {"type": "comment"})

    def test_mastodon_public_status(self):
        get = Samples()
        n, _ = S.Fetcher(ENV, get).numbers(S.parse_share(share(1, "https://mastodon.social/@Gargron/1", "Mastodon")))
        self.assertEqual(n, {"main": "favourites", "favourites": 1152, "reposts": 602, "comments": 65, "quotes": 11,
                             "source": "mastodon"})
        self.assertEqual(get.asked[0][0], "https://mastodon.social/api/v1/statuses/1")

    def test_cloudflare_views_by_referer(self):
        get = Samples()
        rows = S.Fetcher(ENV, get).cf_views("/posts/lcars_journal/", dt.date(2026, 8, 1), dt.date(2026, 10, 20))
        self.assertEqual(len([u for u, _, _ in get.asked if u == S.CF_GRAPHQL]), 3)     # 80 days in 30-day spans
        self.assertEqual(get.asked[0][0], "https://api.cloudflare.com/client/v4/accounts?per_page=5")
        q = json.loads(get.asked[1][2])
        self.assertEqual(q["variables"], {"acct": "acct123", "site": "site1", "path": "/posts/lcars_journal/",
                                          "from": "2026-08-01T00:00:00Z", "to": "2026-08-31T00:00:00Z"})
        self.assertEqual(get.asked[1][1]["Authorization"], "Bearer cft")
        self.assertIn(("2026-10-18", "www.reddit.com", 120), rows)
        self.assertEqual(S.site_of("out.reddit.com"), "reddit.com")
        self.assertEqual(S.site_of("t.co"), "x.com")
        self.assertEqual(S.site_of("lnkd.in"), "linkedin.com")
        get = Samples()
        S.Fetcher(dict(ENV, LCARS_CF_ACCOUNT_ID="mine"), get).cf_views("/p/", dt.date(2026, 10, 1), dt.date(2026, 10, 2))
        self.assertEqual(json.loads(get.asked[0][2])["variables"]["acct"], "mine")


class Manual(unittest.TestCase):
    def test_the_captains_line(self):
        self.assertEqual(S.parse_numbers("12 likes, 3 reposts, 800 views"), {"likes": 12, "reposts": 3, "views": 800})
        self.assertEqual(S.parse_numbers("- 1.2k views · 40 Likes · 2 replies"),
                         {"views": 1200, "likes": 40, "comments": 2})
        self.assertEqual(S.parse_numbers("1,204 impressions; 9 reactions"), {"views": 1204, "likes": 9})
        for no in ("Posted this at 9 am", "12 likes and counting", "https://x.com/me/status/1", "", "likes 12"):
            self.assertIsNone(S.parse_numbers(no), no)

    def test_the_newest_line_counts(self):
        text = "https://x.com/me/status/1\n5 likes, 1 repost\nsome words\n12 likes, 3 reposts, 800 views\nthanks all"
        self.assertEqual(S.manual_line(text), {"likes": 12, "reposts": 3, "views": 800})
        self.assertEqual(S.manual_main({"views": 800, "reposts": 3}), "reposts")
        self.assertIsNone(S.manual_line("https://x.com/me/status/1"))

    def test_the_first_url_is_the_share(self):
        s = S.parse_share(share(9, "see https://x.com/me/status/1.", "X", extra="https://blog.example/posts/x/"))
        self.assertEqual(s["url"], "https://x.com/me/status/1")
        self.assertIsNone(S.parse_share({"id": 1, "title": "no link", "content": "nothing yet"}))
        # saved from the Shares view with a link alone: the server's placeholder title is no name
        self.assertEqual(S.parse_share(share(3, REDDIT, "HTTP Entry"))["title"], REDDIT)


class Readings(unittest.TestCase):
    def setUp(self):
        self.shares = [S.parse_share(r) for r in (
            share(11, REDDIT, "r/ClaudeAI", "2026-10-18T09:00:00Z"),
            share(12, "https://www.reddit.com/r/selfhosted/comments/zzz111/t/", "r/selfhosted", "2026-10-19T08:00:00Z"),
            share(13, "https://news.ycombinator.com/item?id=8863", "HN", "2026-10-19T07:00:00Z"),
            share(14, "https://x.com/me/status/1", "X", extra="12 likes, 3 reposts, 800 views"),
            share(15, "https://www.linkedin.com/posts/me-1", "LinkedIn"))]
        self.views = S.cf_rows(sample("cf_rum.json"))

    def test_one_reading_per_share_and_the_global_sum(self):
        fetched = {11: ({"main": "score", "score": 312, "comments": 47, "source": "reddit"}, None),
                   12: ({"main": "score", "score": 20, "comments": 4, "source": "reddit"}, None),
                   13: ({"main": "points", "points": 104, "comments": 5, "source": "hn"}, None),
                   14: (None, "no API for this site"), 15: (None, "no API for this site")}
        per, (title, total, content) = S.readings(self.shares, fetched, {}, self.views, AT)
        self.assertEqual([p[0] for p in per], ["share_11", "share_12", "share_13", "share_14"])
        self.assertEqual([p[2] for p in per], [312, 20, 104, 12])
        self.assertEqual(per[0][1], "312 score · r/ClaudeAI")      # the number first, as /log titles a reading
        r = json.loads(per[0][3])
        self.assertEqual((r["share"], r["source"], r["main"], r["value"], r["comments"], r["fetched_at"]),
                         (11, "reddit", "score", 312, 47, "2026-10-19T12:00:00Z"))
        # reddit's views since each share's day: both subreddits carry the site's, and say so
        self.assertEqual((r["blog_views"], r["blog_views_site"], r["blog_views_shared"]), (165, "reddit.com", [12]))
        self.assertEqual(json.loads(per[1][3])["blog_views"], 30)
        self.assertEqual(json.loads(per[2][3])["blog_views"], 200)
        x = json.loads(per[3][3])
        self.assertEqual((x["source"], x["main"], x["likes"], x["views"], x["blog_views"]), ("manual", "likes", 12, 800, 9))
        self.assertNotIn("error", x)                               # X has no API: the line is not a fallback
        self.assertEqual((title, total), ("448 · blog post, 5 shares", 448))
        g = json.loads(content)
        self.assertEqual((g["value"], g["comments"], g["shares"], g["blog_views"], g["blog_views_from_shares"]),
                         (448, 56, 5, 423, 374))
        self.assertEqual(g["blog_views_by_site"]["(none)"], 40)
        self.assertEqual(g["missing"], [15])
        self.assertEqual(g["by_share"], {"11": 312, "12": 20, "13": 104, "14": 12})

    def test_a_failed_api_falls_back_then_carries_the_last(self):
        shares = [S.parse_share(share(11, REDDIT, "r/ClaudeAI", extra="300 upvotes, 40 comments")),
                  S.parse_share(share(13, "https://news.ycombinator.com/item?id=8863", "HN"))]
        fetched = {11: (None, "reddit: 403, reddit blocks this box"), 13: (None, "hn: HTTP 500")}
        per, (_, total, content) = S.readings(shares, fetched, {13: {"value": 90, "comments": 7}}, None, AT)
        self.assertEqual([(p[0], p[2]) for p in per], [("share_11", 300)])   # no repeated reading for HN
        r = json.loads(per[0][3])
        self.assertEqual((r["source"], r["main"], r["error"]), ("manual", "score", "reddit: 403, reddit blocks this box"))
        self.assertNotIn("blog_views", r)                              # no token: no views field at all
        g = json.loads(content)
        self.assertEqual((total, g["stale"], g["comments"]), (390, [13], 47))
        self.assertEqual(set(g["errors"]), {"11", "13"})

    def test_cloudflare_failing_is_said_once(self):
        _, (_, _, content) = S.readings(self.shares[:1], {11: (None, "x")}, {}, "cloudflare graphql: HTTP 403", AT)
        self.assertEqual(json.loads(content)["blog_views_error"], "cloudflare graphql: HTTP 403")


class Journal(http.server.BaseHTTPRequestHandler):
    """GET /entries by kind from `rows`, POST /entries recorded."""
    rows, posts = [], []

    def log_message(self, *a):
        pass

    def reply(self, body):
        b = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if self.path == "/health":
            return self.reply({"status": "ok"})
        kind = q.get("kind", [""])[0]
        if int(q.get("offset", ["0"])[0]):
            return self.reply([])
        self.reply([r for r in self.rows if r["kind"] == kind])

    def do_POST(self):
        self.posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.reply({"id": 500 + len(self.posts)})


class Run(Base):
    def setUp(self):
        super().setUp()
        Journal.posts = []
        Journal.rows = [share(11, REDDIT, "r/ClaudeAI"), share(13, "https://news.ycombinator.com/item?id=8863", "HN"),
                        share(14, "https://x.com/me/status/1", "X", extra="12 likes"),
                        {"id": 15, "kind": "share", "title": "deleted", "content": REDDIT, "deleted": 1},
                        {"id": 900, "kind": "crew_share_13", "title": "", "content": '{"value": 1}'}]
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Journal)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        os.environ["LCARS_URL"] = f"http://127.0.0.1:{self.httpd.server_port}"
        with open(os.path.join(os.path.dirname(HERE), "crew", "shares.md")) as f:
            self.role("shares", f.read().replace("lock_wait: 900", "lock_wait: 0\nmem_wait: 0"))
        self.get = Samples()
        self.p = mock.patch.object(S, "_get", self.get)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def go(self, *a):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = C.run("shares", *a)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def test_the_role_loads_as_a_script(self):
        fm, _ = C.load("shares")
        self.assertEqual((fm["kind"], fm["script"], fm["posts"]), ("script", "shares", "shares"))

    def test_a_run_posts_the_readings_then_the_global(self):
        with mock.patch.object(T, "read_env", lambda path=None: dict(ENV, LCARS_CREW_USER="crew", LCARS_CREW_PASS="p")):
            rc, _ = self.go()
        self.assertEqual(rc, 0)
        kinds = [(p["kind"], p.get("value_int")) for p in Journal.posts]
        self.assertEqual(kinds, [("crew_share_11", 312), ("crew_share_13", 104), ("crew_share_14", 12),
                                 ("crew_shares", 428)])
        g = Journal.posts[-1]
        self.assertTrue(g["title"].startswith("428 · blog post, 3 shares · "))
        self.assertEqual(json.loads(g["content"])["value"], 428)      # plain JSON, no runner footer
        self.assertEqual(json.loads(Journal.posts[0]["content"])["blog_views"], 165)
        run = C.read_runs()[-1]
        self.assertEqual((run["status"], run["entry"], run["readings"]), ("posted", 504, [501, 502, 503]))

    def test_no_post_url_no_views(self):
        """With no `post:` and no LCARS_SHARES_POST, Cloudflare is not asked:
        the readings go out without the post's views."""
        env = {k: v for k, v in ENV.items() if k != "LCARS_SHARES_POST"}
        with mock.patch.object(T, "read_env", lambda path=None: dict(env, LCARS_CREW_USER="crew", LCARS_CREW_PASS="p")), \
                mock.patch.object(C, "local_context", lambda role=None, crew_dir=None: ({}, "")):
            rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual(Journal.posts[-1]["kind"], "crew_shares")
        self.assertNotIn("blog_views", json.loads(Journal.posts[0]["content"]))

    def test_no_post_and_dry_run_write_nothing(self):
        with mock.patch.object(T, "read_env", lambda path=None: dict(ENV, LCARS_CREW_USER="crew", LCARS_CREW_PASS="p")):
            rc, out = self.go(False, True)
            self.assertEqual(rc, 0)
            self.assertIn("[would post crew_share_11: 312 score · r/ClaudeAI = 312]", out)
            rc, out = self.go(True)
        self.assertEqual(rc, 0)
        self.assertIn("Would write 3 share readings", out)
        self.assertEqual(Journal.posts, [])

    def test_no_shares_writes_nothing(self):
        Journal.rows = []
        with mock.patch.object(T, "read_env", lambda path=None: dict(ENV, LCARS_CREW_USER="crew", LCARS_CREW_PASS="p")):
            rc, _ = self.go()
        self.assertEqual((rc, Journal.posts), (0, []))
        self.assertEqual(C.read_runs()[-1]["status"], "nothing")
        self.assertEqual(self.get.asked, [])

    def test_without_credentials_the_line_and_the_last_reading_stand_in(self):
        with mock.patch.object(T, "read_env", lambda path=None: {"LCARS_CREW_USER": "crew", "LCARS_CREW_PASS": "p"}):
            rc, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertEqual([p["kind"] for p in Journal.posts], ["crew_share_13", "crew_share_14", "crew_shares"])
        g = json.loads(Journal.posts[-1]["content"])
        self.assertEqual(g["missing"], [11])
        self.assertNotIn("blog_views", g)
        self.assertIn("no LCARS_REDDIT_CLIENT_ID", g["errors"]["11"])
        self.assertFalse(any("cloudflare" in u for u, _, _ in self.get.asked))


if __name__ == "__main__":
    unittest.main(verbosity=1)
