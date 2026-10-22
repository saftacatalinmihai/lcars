#!/usr/bin/env python3
"""Unit tests for the social watch (scripts/social.py, crew.py run_social;
docs/design/social-watch.md, section 4, items 1 to 7 for HN, GitHub and
Cloudflare). No network: the adapters read recorded answers in
scripts/testdata/social/ (the APIs' own shapes, trimmed to the fields read,
the names made up so the public tree carries no one's), and whole runs post
to a stand-in journal.

    python3 scripts/test_social.py
"""

import copy
import datetime as dt
import http.server
import io
import json
import os
import re
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
os.environ["LCARS_CREW_TZ"] = "Europe/Helsinki"  # the captain's zone (UTC+3 in October), never the box's
import crew as C  # noqa: E402
import crew_tool as T  # noqa: E402
import social as S  # noqa: E402
from test_crew import Base  # noqa: E402

DATA = os.path.join(HERE, "testdata", "social")
AT = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)      # 12:00 the captain's time: the day before is the 20th
DAY = dt.date(2026, 10, 20)
REPO = "captain-gh/journal"
GH_TOKEN, CF_TOKEN = "gh-SECRET-standin-0001", "cf-SECRET-standin-0002"
FM = {"hn_user": "captain_hn", "github_user": "captain-gh", "github_repos": "journal",
      "cf_sites": "blog=tag111 demo=tag222"}
ENV = {"LCARS_SOCIAL_GITHUB": GH_TOKEN, "LCARS_CF_ANALYTICS_TOKEN": CF_TOKEN, "LCARS_CF_ACCOUNT_ID": "acct1"}


def sample(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


class Samples:
    """A stand-in for social._http answering from the recordings, and
    recording what it was asked. `fail` maps a URL prefix to a status;
    `extra` adds hits to an answer (a new comment for a later run)."""

    def __init__(self, fail=None, extra=None, mine=None):
        self.asked, self.fail, self.extra, self.mine = [], fail or {}, extra or {}, mine

    def __call__(self, method, url, headers=None, data=None, timeout=20):
        self.asked.append((method, url, dict(headers or {}), data))
        for pre, st in self.fail.items():
            if url.startswith(pre):
                return st, None, "<html>Bad gateway</html>"
        j = self.answer(url, data)
        if j is None:
            return 404, None, "not here"
        if isinstance(j, tuple):
            return j
        for key, more in self.extra.items():
            if key in url:
                j = copy.deepcopy(j)
                j["hits"] += more
        return 200, j, json.dumps(j)

    def answer(self, url, data):
        h, g = S.HN_API, S.GH_API + f"/repos/{REPO}"
        if url.startswith(h + "search_by_date?tags=story,author_captain_hn"):
            return sample("hn_stories.json")
        if url.startswith(h + "search_by_date?tags=comment,author_captain_hn"):
            return self.mine if self.mine is not None else sample("hn_mine.json")
        if url.startswith(h + "search_by_date?tags=comment,story_9001"):
            return sample("hn_story_9001.json")
        if url == h + "items/9020":
            return sample("hn_item_9020.json")
        if url.startswith(h + "items/"):
            return {"children": []}
        routes = {"": "gh_repo", "/issues?": "gh_issues", "/issues/comments?": "gh_issue_comments",
                  "/pulls/comments?": "gh_pull_comments", "/stargazers?": "gh_stargazers", "/forks?": "gh_forks",
                  "/traffic/views": "gh_views", "/traffic/clones": "gh_clones", "/traffic/popular/paths": "gh_paths",
                  "/traffic/popular/referrers": "gh_referrers"}
        for tail, name in sorted(routes.items(), key=lambda kv: -len(kv[0])):
            if tail and url.startswith(g + tail) or not tail and url == g:
                return sample(name + ".json")
        if url == S.GH_GRAPHQL:
            return sample("gh_discussions.json")
        if url == S.CF_GRAPHQL:
            return sample("cf_rum.json")
        return None


def fetcher(get=None, env=None, fm=None, run=None):
    return S.Fetcher(dict(ENV if env is None else env), dict(FM, **(fm or {})), S.Net(get or Samples()), run)


class Adapters(unittest.TestCase):
    """Item 1: each adapter on its recordings."""

    def test_hn_stories_replies_and_the_dead(self):
        cs, stats = fetcher().hn(AT, DAY)
        by = {c["id"]: c for c in cs}
        # the captain's own (9010) skipped; 9022 deleted and 9023 flagged skipped
        self.assertEqual(sorted(by), ["hn:9002", "hn:9003", "hn:9004", "hn:9021"])
        self.assertTrue(by["hn:9003"]["replied"])                    # the captain's 9010 is its child
        self.assertFalse(by["hn:9002"]["replied"])
        self.assertEqual(by["hn:9002"]["text"],
                         "Nice write-up, how do you sync it?\n\nAlso see https://example.org/x & that's it.")
        self.assertEqual((by["hn:9002"]["parent"], by["hn:9004"]["parent"]), ("story", "comment #9002"))
        d = by["hn:9021"]                                            # a reply to the captain's comment on another's story
        self.assertEqual((d["parent"], d["author"], d["link"]),
                         ("the captain's comment #9020", "dave", "https://news.ycombinator.com/item?id=9021"))
        self.assertEqual(d["on"], "Show HN: A journal in SQLite (https://news.ycombinator.com/item?id=8000)")
        self.assertEqual(d["at"], "2026-10-20T10:00:00Z")
        self.assertEqual((stats["value"], stats["main"], stats["comments"]), (12, "points", 4))
        self.assertIsNone(fetcher().hn(AT, None)[1])                 # no reading when none is due

    def test_hn_asks_the_windows(self):
        get = Samples()
        fetcher(get).hn(AT, None)
        urls = [u for _, u, _, _ in get.asked]
        self.assertIn(f"created_at_i>{int(AT.timestamp()) - 30 * 86400}", urls[0])
        # only the captain's comments of the last 14 days have their replies read
        self.assertIn(S.HN_API + "items/9020", urls)

    def test_github_comments_issues_and_discussions(self):
        cs, stats = fetcher().github(AT, None)
        self.assertIsNone(stats)
        by = {c["id"]: c for c in cs}
        self.assertEqual(sorted(by), sorted([f"github:{REPO}#5", f"github:{REPO}/c101", f"github:{REPO}/c103",
                                             f"github:{REPO}/r201", f"github:{REPO}/dc301"]))
        # bots (dependabot, actions, giscus's thread), the captain's own and the old issue skipped
        self.assertTrue(by[f"github:{REPO}#5"]["replied"])           # the captain's 102 came after it
        self.assertTrue(by[f"github:{REPO}/c101"]["replied"])
        self.assertFalse(by[f"github:{REPO}/c103"]["replied"])
        self.assertEqual(by[f"github:{REPO}#5"]["parent"], "new issue")
        self.assertEqual(by[f"github:{REPO}#5"]["text"], "Crash on start\n\nIt crashes when the db is empty.")
        self.assertEqual(by[f"github:{REPO}/c103"]["parent"], "issue #2 (comment)")
        self.assertEqual(by[f"github:{REPO}/c103"]["on"],
                         f"{REPO}#2 Old issue (https://github.com/{REPO}/issues/2)")
        self.assertEqual(by[f"github:{REPO}/r201"]["parent"], "pull request #7 (review comment)")
        self.assertEqual((by[f"github:{REPO}/dc301"]["author"], by[f"github:{REPO}/dc301"]["parent"]),
                         ("mallory", "discussion #19"))

    def test_github_daily_stars_forks_and_traffic(self):
        get = Samples()
        _, stats = fetcher(get).github(AT, DAY)
        r = stats["repos"][REPO]
        self.assertEqual((stats["value"], stats["main"], r["stars"], r["forks"]), (3, "stars", 3, 1))
        # the captain's day is 21:00 UTC the 19th to 21:00 the 20th: heidi in, ivan (23:30 UTC) the next day
        self.assertEqual((r["new_stars"], r["new_forks"]), (["heidi"], ["judy"]))
        st = [(u, h) for _, u, h, _ in get.asked if "/stargazers" in u][0]
        self.assertEqual(st[1]["Accept"], "application/vnd.github.star+json")      # starred_at
        # complete UTC days only: the 21st is not over
        self.assertEqual(list(r["traffic_days"])[0], "2026-10-09")     # the 8th had none: taken, not listed
        self.assertEqual(list(r["traffic_days"])[-1], "2026-10-20")
        self.assertEqual((r["views"], r["clones"], r["traffic_through"]), (78, 2, "2026-10-20"))
        self.assertEqual(r["referrers_14d"], [["news.ycombinator.com", 20, 7]])

    def test_github_traffic_refused_without_push(self):
        get = Samples()
        get.answer = (lambda orig: lambda url, data: ((403, {"message": "Must have push access"}, "{}")
                                                      if "/traffic/views" in url else orig(url, data)))(get.answer)
        _, stats = fetcher(get).github(AT, DAY)
        self.assertIn("push access", stats["repos"][REPO]["traffic"])
        self.assertEqual(stats["value"], 3)                          # the rest still read

    def test_github_token_from_gh_when_unset(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout=GH_TOKEN + "\n")
        get = Samples()
        fetcher(get, env={}, run=run).github(AT, None)
        self.assertEqual(calls, [["gh", "auth", "token"]])
        self.assertEqual(get.asked[0][2]["Authorization"], "Bearer " + GH_TOKEN)
        with self.assertRaisesRegex(RuntimeError, "LCARS_SOCIAL_GITHUB unset"):
            fetcher(env={}, run=lambda *a, **k: mock.Mock(returncode=1, stdout="")).github(AT, None)

    def test_cloudflare_by_site_page_and_referrer(self):
        get = Samples()
        cs, stats = fetcher(get).cf(AT, DAY)
        self.assertEqual(cs, [])
        self.assertEqual((stats["value"], stats["views"], stats["main"]), (140, 180, "visits"))   # two sites
        blog = stats["sites"]["blog"]
        self.assertEqual(blog["pages"][0], ["blog.example/posts/one/", 65, 80])
        self.assertEqual(blog["referrers"], [["news.ycombinator.com", 40, 50], ["(none)", 25, 30], ["kagi.com", 5, 10]])
        posts = [(m, u, h, d) for m, u, h, d in get.asked if u == S.CF_GRAPHQL]
        self.assertEqual(len(posts), 2)
        q = json.loads(posts[0][3])
        self.assertIn("bot: 0", q["query"])                          # bots excluded
        self.assertEqual(q["variables"], {"acct": "acct1", "site": "tag111",
                                          "from": "2026-10-19T21:00:00Z", "to": "2026-10-20T21:00:00Z"})
        self.assertEqual(posts[0][2]["Authorization"], "Bearer " + CF_TOKEN)
        self.assertEqual(fetcher(get).cf(AT, None), ([], None))      # no reading due: no request

    def test_cloudflare_falls_back_to_the_box_token(self):
        f = fetcher(env={"CLOUDFLARE_API_TOKEN": "box", "CLOUDFLARE_ACCOUNT_ID": "a2"})
        self.assertEqual((f.cf_token(), f.cf_account()), ("box", "a2"))
        self.assertEqual(fetcher(env={}).configured("cf"), (False, "no LCARS_CF_ANALYTICS_TOKEN or CLOUDFLARE_API_TOKEN"))


class ReadOnlyNet(unittest.TestCase):
    """Item 6: anything but a read to a platform is refused."""

    def test_writes_refused(self):
        S.check_read_only("GET", S.GH_API + "/repos/a/b", None)
        S.check_read_only("POST", S.CF_GRAPHQL, json.dumps({"query": "query { viewer { x } }"}).encode())
        S.check_read_only("POST", S.GH_GRAPHQL, json.dumps({"query": "  query($o: String!) { x }"}).encode())
        for m, u, d in (("POST", S.GH_API + "/repos/a/b/issues/1/comments", b"{}"),
                        ("PATCH", S.GH_API + "/repos/a/b", b"{}"), ("DELETE", S.GH_API + "/repos/a/b", None),
                        ("PUT", S.GH_API + "/user/starred/a/b", None),
                        ("POST", S.GH_GRAPHQL, json.dumps({"query": "mutation { addComment { x } }"}).encode()),
                        ("POST", S.GH_GRAPHQL, b"not json"), ("POST", S.HN_API + "items/1", b"x"),
                        ("GET", S.GH_API + "/repos/a/b", b"body")):
            with self.assertRaises(S.ReadOnly, msg=f"{m} {u}"):
                S.check_read_only(m, u, d)
        get = Samples()
        with self.assertRaises(S.ReadOnly):
            S.Net(get)("POST", S.GH_API + "/repos/a/b/issues", {}, b"{}")
        self.assertEqual(get.asked, [])                              # refused before it left

    def test_a_whole_run_only_reads(self):
        get = Samples()
        f = fetcher(get)
        f.hn(AT, DAY), f.github(AT, DAY), f.cf(AT, DAY)
        for m, u, _, d in get.asked:
            self.assertTrue(m == "GET" or (m == "POST" and u in S.GRAPHQL_ENDPOINTS
                                           and not json.loads(d)["query"].lstrip().startswith("mutation")), (m, u))
        self.assertEqual({urllib.parse.urlsplit(u).hostname for _, u, _, _ in get.asked},
                         {"hn.algolia.com", "api.github.com", "api.cloudflare.com"})


class Pure(unittest.TestCase):
    def test_the_entry_and_its_lines(self):
        c = S.comment("hn", "9002", "https://news.ycombinator.com/item?id=9002", "Software for One (x)", "story",
                      "alice", "2026-10-18T11:00:00Z", "Nice write-up, how do you sync it? " * 4)
        title, content, done = S.comment_entry(c)
        self.assertTrue(title.startswith("HN · alice: Nice write-up, how do you sync it? Nice"))
        self.assertTrue(title.endswith("…"))
        self.assertEqual(done, 0)
        self.assertEqual(content.split("\n")[:8], [
            "id: hn:9002", "platform: hn", "link: https://news.ycombinator.com/item?id=9002",
            "on: Software for One (x)", "parent: story", "author: alice", "at: 2026-10-18T11:00:00Z", "status: new"])
        self.assertEqual(S.seen_ids([{"id": 1, "content": content}]), {"hn:9002": {"id": 1, "content": content}})
        self.assertEqual(S.last_failures("x\n\nfailures: hn=1 github=3 bogus=2"), {"hn": 1, "github": 3})
        self.assertEqual(S.last_failures("failures: none"), {})


class Journal(http.server.BaseHTTPRequestHandler):
    """A stand-in journal: GET /entries by kind (newest first with
    dir=desc), POST /entries kept as rows, PATCH with if_modified (a 412
    when the row moved)."""
    rows, posts, patches = [], [], []

    def log_message(self, *a):
        pass

    def reply(self, body, st=200):
        b = json.dumps(body).encode()
        self.send_response(st)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path != "/entries":
            return self.reply({"error": "no"}, 404)
        if int(q.get("offset", ["0"])[0]):
            return self.reply([])
        got = [r for r in self.rows if r["kind"] == q.get("kind", [""])[0]]
        if q.get("dir") == ["desc"]:
            got = got[::-1]
        self.reply(got[:int(q.get("limit", ["1000"])[0])])

    def body(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

    def do_POST(self):
        b = self.body()
        Journal.posts.append(b)
        row = dict(b, id=500 + len(Journal.rows), last_modified_at_utc="2026-10-21 09:00:00", deleted=0)
        Journal.rows.append(row)
        self.reply({"id": row["id"]})

    def do_PATCH(self):
        b, i = self.body(), int(self.path.rsplit("/", 1)[1])
        Journal.patches.append((i, b))
        row = next(r for r in Journal.rows if r["id"] == i)
        if b.get("if_modified") != row["last_modified_at_utc"]:
            return self.reply({"error": "moved"}, 412)
        row.update({k: v for k, v in b.items() if k != "if_modified"}, last_modified_at_utc="2026-10-21 10:00:00")
        self.reply(row)


SECRETS = (GH_TOKEN, CF_TOKEN, "pass with spaces")


class Run(Base):
    """Items 2, 3, 4, 5 and 7: whole runs against the stand-in journal."""

    def setUp(self):
        super().setUp()
        Journal.rows, Journal.posts, Journal.patches = [], [], []
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Journal)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        os.environ["LCARS_URL"] = f"http://127.0.0.1:{self.httpd.server_port}"
        with open(os.path.join(os.path.dirname(HERE), "crew", "social.md")) as f:
            text = f.read().replace("lock_wait: 900", "lock_wait: 0\nmem_wait: 0")
        for k, v in FM.items():
            text = re.sub(rf"^{k}:.*$", f"{k}: {v}", text, count=1, flags=re.M)
        self.role("social", text)
        self.at = AT
        self.get = Samples()
        self.ps = [mock.patch.object(S, "_http", lambda *a, **k: self.get(*a, **k)),
                   mock.patch.object(S, "now_utc", lambda: self.at),
                   mock.patch.object(T, "read_env", lambda path=None: dict(ENV, LCARS_CREW_USER="crew",
                                                                           LCARS_CREW_PASS="pass with spaces"))]
        for p in self.ps:
            p.start()
        self.out = ""

    def tearDown(self):
        for p in self.ps:
            p.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def go(self, *a):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = C.run("social", *a)
            except SystemExit as e:
                rc = e.code
        self.out += out.getvalue()
        return rc

    def kinds(self, posts=None):
        return [p["kind"] for p in (Journal.posts if posts is None else posts)]

    def test_the_role_loads_as_a_script(self):
        fm, _ = C.load("social")
        self.assertEqual((fm["kind"], fm["script"], fm["posts"], fm["schedule"]),
                         ("script", "social", "social", "*-*-* *:20:00"))

    def test_new_is_new_once(self):
        self.assertEqual(self.go(), 0)
        ks = self.kinds()
        self.assertEqual(ks.count("crew_social_comment"), 9)          # HN 4, GitHub 5
        self.assertEqual(ks[-2:], ["crew_social", "task_crew_social"])
        self.assertEqual([k for k in ks if k.startswith("crew_social_") and k != "crew_social_comment"],
                         ["crew_social_hn", "crew_social_github", "crew_social_cf"])
        n = Journal.posts[-1]
        self.assertEqual(n["title"], "6 new comments: HN 3, GitHub 3")  # the answered three are not in it
        self.assertIn("alice on Software for One", n["content"])
        self.assertNotIn("bob", n["content"])
        ids = {r["id"] for r in Journal.rows if r["kind"] == "crew_social_comment"}
        named = {int(x) for x in re.findall(r"^#(\d+)$", n["content"], re.M)}
        self.assertEqual(len(named), 6)
        self.assertTrue(named <= ids)
        run = Journal.posts[-2]
        self.assertTrue(run["title"].startswith("Social watch: 9 new comments · "))
        self.assertIn("failures: none", run["content"])
        # a second run on the same answers: nothing at all, not even the run's entry
        before = len(Journal.posts)
        self.assertEqual(self.go(), 0)
        self.assertEqual(len(Journal.posts), before)
        self.assertEqual(C.read_runs()[-1]["status"], "nothing")
        # a third with one more comment: one entry, and a notice naming it alone
        self.get.extra = {"story_9001": [{"objectID": "9005", "author": "oscar", "comment_text": "Late to this.",
                                          "created_at_i": int(AT.timestamp()) - 60, "parent_id": 9001,
                                          "story_id": 9001}]}
        self.assertEqual(self.go(), 0)
        new = Journal.posts[before:]
        self.assertEqual(self.kinds(new), ["crew_social_comment", "crew_social", "task_crew_social"])
        self.assertEqual(new[-1]["title"], "1 new comment: HN 1")
        self.assertIn("oscar", new[-1]["content"])
        self.assertNotIn("alice", new[-1]["content"])

    def test_his_reply_marks_the_comment(self):
        self.go()
        bob = next(p for p in Journal.posts if "id: hn:9003" in p.get("content", ""))
        self.assertIn("status: replied", bob["content"])
        self.assertEqual(bob["done_bool"], 1)
        alice = next(p for p in Journal.posts if "id: hn:9002" in p.get("content", ""))
        self.assertEqual((alice["done_bool"], "status: new" in alice["content"]), (0, True))

    def test_a_later_reply_is_seen_by_a_later_run(self):
        """Run 1 before the captain's reply: bob's comment new and in the notice. Run 2
        after it: the entry patched as it was read, replied and done."""
        mine = sample("hn_mine.json")
        self.get.mine = {"hits": [h for h in mine["hits"] if h["objectID"] != "9010"]}
        self.go()
        bob = next(r for r in Journal.rows if "id: hn:9003" in r.get("content", ""))
        self.assertIn("status: new", bob["content"])
        self.assertIn("bob", Journal.posts[-1]["content"])
        self.get.mine = None
        before = len(Journal.posts)
        self.go()
        self.assertEqual(Journal.patches, [(bob["id"], {"content": bob["content"].replace("status: new", "status: replied"),
                                                       "done_bool": 1, "if_modified": "2026-10-21 09:00:00"})])
        self.assertEqual(self.kinds(Journal.posts[before:]), ["crew_social"])   # no notice: nothing unanswered
        self.assertIn(f"#{bob['id']}: answered", Journal.posts[-1]["content"])
        self.assertEqual(C.read_runs()[-1]["patched"], [bob["id"]])

    def test_a_captains_edit_wins_over_the_mark(self):
        mine = sample("hn_mine.json")
        self.get.mine = {"hits": [h for h in mine["hits"] if h["objectID"] != "9010"]}
        self.go()
        bob = next(r for r in Journal.rows if "id: hn:9003" in r.get("content", ""))
        self.get.mine = None
        real = C.T.entries_all

        def moved(**q):        # the captain edits it between the run's read and its patch
            rows = real(**q)
            bob["last_modified_at_utc"] = "2026-10-21 09:30:00"
            return rows
        with mock.patch.object(C.T, "entries_all", moved):
            self.go()
        self.assertEqual(C.read_runs()[-1]["patch_skipped"], [bob["id"]])
        self.assertIn("status: new", bob["content"])

    def test_the_daily_reading(self):
        self.go()
        r = {p["kind"]: p for p in Journal.posts if p["kind"] in ("crew_social_hn", "crew_social_github", "crew_social_cf")}
        self.assertEqual({k: (v["value_int"], v["title"]) for k, v in r.items()},
                         {"crew_social_hn": (12, "12 points · HN"), "crew_social_github": (3, "3 stars · GitHub"),
                          "crew_social_cf": (140, "140 visits · Cloudflare")})
        g = json.loads(r["crew_social_github"]["content"])
        self.assertEqual((g["day"], g["repos"][REPO]["traffic_through"]), ("2026-10-20", "2026-10-20"))
        # an hour later, the same day: no reading again, and Cloudflare not asked
        self.get.asked = []
        self.at = AT + dt.timedelta(hours=1)
        self.go()
        self.assertEqual(sum(1 for p in Journal.posts if p["kind"] == "crew_social_hn"), 1)
        self.assertFalse(any(u == S.CF_GRAPHQL for _, u, _, _ in self.get.asked))
        # the next day: GitHub's traffic only for the day not yet taken
        self.at = AT + dt.timedelta(days=1)
        self.go()
        gh = [json.loads(p["content"]) for p in Journal.posts if p["kind"] == "crew_social_github"]
        self.assertEqual(len(gh), 2)
        self.assertEqual(gh[1]["day"], "2026-10-21")
        self.assertEqual(list(gh[1]["repos"][REPO]["traffic_days"]), ["2026-10-21"])
        self.assertEqual(gh[1]["repos"][REPO]["views"], 13)

    def test_no_secret_anywhere(self):
        self.go()
        self.go(False, True)
        self.go(True)
        dump = json.dumps(Journal.posts) + self.out + json.dumps(C.read_runs())
        for s in SECRETS:
            self.assertNotIn(s, dump)

    def test_failure_costs_one_platform_and_raises_once(self):
        self.get.fail = {S.GH_API: 502}
        self.go()
        ks = self.kinds()
        self.assertIn("crew_social_hn", ks)
        self.assertIn("crew_social_cf", ks)
        self.assertNotIn("crew_social_github", ks)
        run = next(p for p in Journal.posts if p["kind"] == "crew_social")
        self.assertIn("- GitHub: failed, github ", run["content"])
        self.assertIn("HTTP 502 Bad gateway", run["content"])
        self.assertIn("failures: github=1", run["content"])
        self.assertNotIn("task_crew", ks)
        for n in (2, 3, 4):
            self.at += dt.timedelta(hours=1)
            self.go()
            self.assertIn(f"failures: github={n}", Journal.posts[-1]["content"] if Journal.posts[-1]["kind"] == "crew_social"
                          else Journal.posts[-2]["content"])
        tasks = [p for p in Journal.posts if p["kind"] == "task_crew"]
        self.assertEqual(len(tasks), 1)                               # the third run's, not the fourth's
        self.assertTrue(tasks[0]["title"].startswith("The watch cannot read GitHub: github "))
        # back: one line saying so, the count gone
        self.get.fail = {}
        self.at += dt.timedelta(hours=1)
        self.go()
        run = [p for p in Journal.posts if p["kind"] == "crew_social"][-1]
        self.assertIn("GitHub: reading again after 4 failed runs", run["content"])
        self.assertIn("failures: none", run["content"])

    def test_unconfigured_platforms_are_skipped_and_said(self):
        with mock.patch.object(T, "read_env", lambda path=None: {"LCARS_CREW_USER": "crew", "LCARS_CREW_PASS": "p",
                                                                 "LCARS_SOCIAL_GITHUB": GH_TOKEN}):
            self.go()
        run = next(p for p in Journal.posts if p["kind"] == "crew_social")
        self.assertIn("- Cloudflare: not read, no LCARS_CF_ANALYTICS_TOKEN or CLOUDFLARE_API_TOKEN", run["content"])
        self.assertNotIn("crew_social_cf", self.kinds())

    def test_dry_run_and_no_post_write_nothing(self):
        self.assertEqual(self.go(True), 0)
        self.assertIn("[would post 6 new comments: HN 3, GitHub 3 to the social list]", self.out)
        self.assertEqual(self.go(False, True), 0)
        self.assertIn("[would post the social notice: 6 new comments: HN 3, GitHub 3]", self.out)
        self.assertEqual((Journal.posts, Journal.patches), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=1)
