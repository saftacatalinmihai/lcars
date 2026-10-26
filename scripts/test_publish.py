#!/usr/bin/env python3
"""Unit tests for the publisher (scripts/publish.py, scripts/publish_net/;
docs/design/social-publish.md 3.10, slice 2: Mastodon). No network: the
provider reads recorded answers in scripts/testdata/publish/ (Mastodon's
own shapes, trimmed, the names made up), a stand-in journal holds the
entries, and one whole run goes through the command line against a
stand-in server on 127.0.0.1 that is both the journal and the instance.
Nothing is ever posted anywhere.

    python3 scripts/test_publish.py
"""

import datetime as dt
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["LCARS_CREW_TZ"] = "Europe/Helsinki"   # the captain's zone (UTC+3 in October), never the box's
os.environ["LCARS_CREW_ENV"] = os.devnull         # never the box's ~/.env
import publish as P  # noqa: E402
import publish_net as N  # noqa: E402
from publish_net import bluesky as B  # noqa: E402
from publish_net import mastodon as M  # noqa: E402

DATA = os.path.join(HERE, "testdata", "publish")
TOKEN = "masto-SECRET-standin-0001"
CREW_PASS = "crew-SECRET-standin-0002"
ENV = {"LCARS_PUB_MASTODON": "example.social:" + TOKEN, "LCARS_PUB_DRY": "0"}
AT = dt.datetime(2026, 10, 23, 12, 0, tzinfo=dt.timezone.utc)
APP_PASS = "bsky-APPPASS-standin-0005"
BENV = {"LCARS_PUB_BLUESKY": "captain.example.social:" + APP_PASS, "LCARS_PUB_DRY": "0"}
SECRETS = (TOKEN, CREW_PASS, APP_PASS, "bsky-ACCESS-standin-0003", "bsky-REFRESH-standin-0004")


def sample(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return f.read()


class Instance:
    """A stand-in for publish._http: the recordings, every request kept
    with its headers and body. `status` answers a status a code."""

    def __init__(self, status_code=200, media_code=200):
        self.asked, self.status_code, self.media_code = [], status_code, media_code

    def __call__(self, method, url, headers=None, data=None, timeout=20):
        self.asked.append((method, url, dict(headers or {}), data))
        path = url.split("example.social", 1)[-1]
        if path == "/api/v2/instance":
            return 200, json.loads(sample("mastodon_instance.json")), ""
        if path == "/api/v1/accounts/verify_credentials":
            return 200, json.loads(sample("mastodon_verify.json")), ""
        if path == "/api/v2/media":
            return self.media_code, json.loads(sample("mastodon_media.json")), ""
        if path == "/api/v1/statuses":
            if self.status_code != 200:
                return self.status_code, json.loads(sample("mastodon_422.json")), ""
            return 200, json.loads(sample("mastodon_status.json")), ""
        if path == "TIMEOUT":
            return 0, None, "timed out"
        return 404, {"error": "Not found"}, ""

    def sent(self, path):
        return [a for a in self.asked if a[1].endswith(path) and a[0] == "POST"]


class Sky:
    """A stand-in Bluesky PDS for publish._http: the recordings, every
    request kept. `expire` answers the next N authenticated calls with
    ExpiredToken; `feed` has the lost post in getAuthorFeed."""

    def __init__(self, expire=0, record_code=200):
        self.asked, self.expire, self.record_code = [], expire, record_code

    def __call__(self, method, url, headers=None, data=None, timeout=20):
        self.asked.append((method, url, dict(headers or {}), data))
        path = url.split("bsky.social", 1)[-1].split("?", 1)[0]
        auth = (headers or {}).get("Authorization", "")
        if path == "/xrpc/com.atproto.server.createSession":
            body = json.loads(data)
            if body.get("password") != APP_PASS:
                return 401, {"error": "AuthenticationRequired", "message": "Invalid identifier or password"}, ""
            return 200, json.loads(sample("bluesky_session.json")), ""
        if path == "/xrpc/com.atproto.server.refreshSession":
            return 200, json.loads(sample("bluesky_session.json")), ""
        if self.expire and auth:
            self.expire -= 1
            return 400, json.loads(sample("bluesky_expired.json")), ""
        if path == "/xrpc/com.atproto.server.getSession":
            return 200, json.loads(sample("bluesky_getsession.json")), ""
        if path == "/xrpc/com.atproto.repo.uploadBlob":
            return 200, json.loads(sample("bluesky_blob.json")), ""
        if path == "/xrpc/app.bsky.feed.getAuthorFeed":
            return 200, json.loads(sample("bluesky_feed.json")), ""
        if path == "/xrpc/com.atproto.repo.createRecord":
            if self.record_code != 200:
                return self.record_code, {"error": "InternalServerError", "message": "down"}, ""
            return 200, json.loads(sample("bluesky_record.json")), ""
        return 404, {"error": "XRPCNotSupported"}, ""

    def calls(self, path):
        return [a for a in self.asked if path in a[1]]


class Journal:
    """A stand-in for publish.Journal: rows in a list, writes appended."""

    def __init__(self, rows=None, media=None):
        self.rows, self.media_files, self.written = list(rows or []), media or {}, []

    def get(self, eid):
        for r in self.rows:
            if r["id"] == eid:
                return r
        raise P.Fail(f"no entry #{eid}", 4)

    def records(self):
        return [r for r in self.rows if r["kind"] == P.RECORD]

    def write(self, title, content):
        rid = 1000 + len(self.written)
        self.written.append({"id": rid, "kind": P.RECORD, "title": title, "content": content})
        self.rows.append(self.written[-1])
        return rid

    def media(self, path):
        if path not in self.media_files:
            raise P.Fail("the picture is not in the journal's media: attach it by hand", 2)
        return self.media_files[path]


def drafts(eid=7, text="Software for One\n\nI built a journal for one person.", link="https://example.com/blog/one",
           img="", alt="", own=None):
    nets = {"mastodon": {"own": own is not None, "text": own if own is not None else text}}
    return {"id": eid, "kind": "social_post", "title": "Share · Software for One",
            "content": json.dumps({"v": 1, "from": 3, "link": link, "img": img, "alt": alt, "text": text,
                                   "on": ["mastodon"], "nets": nets})}


def args(eid=7, networks="mastodon", dry_run=False, by="tap"):
    return types.SimpleNamespace(id=eid, networks=networks, dry_run=dry_run, by=by)


class Counting(unittest.TestCase):
    """3.10 item 2: the limits table's texts, counted as the page counts them."""

    def test_the_tables_cases(self):
        bad = []
        for c in N.LIMITS["cases"]:
            for k, n in N.LIMITS["networks"].items():
                want = c["link23"] if n["link"] and c.get("link23") is not None else c[n["counts"]]
                if N.count(k, c["text"]) != want:
                    bad.append(f"{k} {c['text']!r}: {N.count(k, c['text'])} not {want}")
        self.assertEqual(bad, [])

    def test_graphemes(self):
        self.assertEqual(len(N.clusters("a\r\nb")), 3)
        self.assertEqual(len(N.clusters("🇷🇴🇬🇧")), 2)

    def test_the_body_takes_the_link_once(self):
        self.assertEqual(N.body("hello", "https://x.example/a"), "hello\n\nhttps://x.example/a")
        self.assertEqual(N.body("see https://x.example/a", "https://x.example/a"), "see https://x.example/a")
        self.assertEqual(N.body("", "https://x.example/a"), "https://x.example/a")


class Mastodon(unittest.TestCase):
    """3.10 item 1 and 8: the provider's requests, its credential, its hand URL."""

    def test_the_credential(self):
        self.assertEqual(M.creds({"LCARS_PUB_MASTODON": "example.social:abc"}), ("https://example.social", "abc"))
        self.assertEqual(M.creds({"LCARS_PUB_MASTODON": "https://example.social/:abc"}), ("https://example.social", "abc"))
        self.assertEqual(M.creds({"LCARS_PUB_MASTODON": "http://127.0.0.1:8123:abc"}), ("http://127.0.0.1:8123", "abc"))
        self.assertIsNone(M.creds({"LCARS_PUB_MASTODON": "http://example.social:abc"}), "plain http only to a stand-in")
        self.assertIsNone(M.creds({"LCARS_PUB_MASTODON": "abc"}))
        self.assertIn("no LCARS_PUB_MASTODON", M.configured({}))
        self.assertIn("not <instance host>:<access token>", M.configured({"LCARS_PUB_MASTODON": "nonsense"}))
        self.assertIsNone(M.configured(ENV))

    def test_the_instance_limit(self):
        net = P.Net(Instance())
        self.assertEqual(M.limit(net, ENV), 500)
        self.assertEqual(M.validate({"text": "a" * 501}, 500), ["1 over the instance's 500"])
        self.assertEqual(M.validate({"text": "a" * 476 + " https://example.com/" + "x" * 200}, 500), [],
                         "a link counts 23 whatever its length")
        self.assertEqual(M.validate({"text": " "}, 500), ["nothing to post"])
        self.assertIn("alt text", M.validate({"text": "hi", "image": b"x", "alt": ""}, 500)[0])

    def test_a_status_with_its_picture_and_key(self):
        inst = Instance()
        post = {"text": "hello", "image": b"\xff\xd8jpeg", "image_name": "bridge.jpg", "alt": "the bridge",
                "hash": P.text_hash("hello")}
        out = M.send(P.Net(inst), ENV, post, dry=False)
        self.assertEqual(out, {"url": "https://example.social/@captain/113401234567890123", "id": "113401234567890123"})
        (media,), (status,) = inst.sent("/api/v2/media"), inst.sent("/api/v1/statuses")
        self.assertEqual(media[2]["Authorization"], "Bearer " + TOKEN)
        self.assertIn(b'name="description"\r\n\r\nthe bridge', media[3])
        self.assertIn(b'filename="bridge.jpg"\r\nContent-Type: image/jpeg', media[3])
        self.assertEqual(status[2]["Idempotency-Key"], P.text_hash("hello"), "the text's hash is the key")
        self.assertEqual(json.loads(status[3]), {"status": "hello", "visibility": "public", "media_ids": ["22348641"]})

    def test_a_refusal_is_the_instances_words(self):
        with self.assertRaises(RuntimeError) as e:
            M.send(P.Net(Instance(status_code=422)), ENV, {"text": "x", "hash": "h"}, dry=False)
        self.assertEqual(str(e.exception), "Mastodon refused the status: 422, Validation failed: Text character limit of 500 exceeded")

    def test_a_dry_run_sends_nothing_and_hides_the_token(self):
        inst = Instance()
        out = M.send(P.Net(inst), ENV, {"text": "hi", "image": b"abc", "image_name": "a.png", "alt": "a", "hash": "h"}, dry=True)
        self.assertEqual(inst.asked, [])
        self.assertEqual([r["url"] for r in out["request"]],
                         ["https://example.social/api/v2/media", "https://example.social/api/v1/statuses"])
        self.assertNotIn(TOKEN, json.dumps(out))
        self.assertEqual(out["request"][1]["headers"]["Authorization"], "Bearer …")

    def test_check_reads_and_never_posts(self):
        inst = Instance()
        self.assertEqual(M.check(P.Net(inst), ENV), {"ok": True, "account": "@captain@example.social"})
        self.assertEqual([a[0] for a in inst.asked], ["GET"])
        self.assertEqual(M.check(P.Net(inst), {}), {"ok": False, "error": "Mastodon: no LCARS_PUB_MASTODON in ~/.env"})

    def test_the_hand_url(self):
        self.assertEqual(M.hand_url(ENV, {"text": "a b"}), "https://example.social/share?text=a%20b")


class Bluesky(unittest.TestCase):
    """3.10 item 1: the record, its facets at UTF-8 byte offsets, the card,
    the picture; the session kept between runs and refreshed; check."""

    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="lcars-test-publish-")
        self.env = dict(BENV, LCARS_PUB_STATE_DIR=self.state)

    def test_the_credential(self):
        self.assertEqual(B.creds(BENV), ("captain.example.social", APP_PASS, "https://bsky.social"))
        self.assertEqual(B.creds({"LCARS_PUB_BLUESKY": "@a.bsky.social:x-y"})[0], "a.bsky.social")
        self.assertIsNone(B.creds({"LCARS_PUB_BLUESKY": "nohandle"}))
        self.assertIsNone(B.creds(dict(BENV, LCARS_PUB_BLUESKY_PDS="http://pds.example")), "plain http only to a stand-in")
        self.assertIn("no LCARS_PUB_BLUESKY", B.configured({}))
        self.assertIsNone(B.configured(BENV))

    def test_facets_by_byte_offsets(self):
        text = "Ce faci? ștergem 🚀 https://example.com/a. And (https://b.example/x)"
        f = B.facets(text)
        raw = text.encode("utf-8")
        got = [raw[x["index"]["byteStart"]:x["index"]["byteEnd"]].decode() for x in f]
        self.assertEqual(got, ["https://example.com/a", "https://b.example/x"], "the trailing . and ) left out")
        self.assertEqual(f[0]["index"]["byteStart"], len("Ce faci? ștergem 🚀 ".encode()), "ș and 🚀 count as their bytes")
        self.assertEqual(f[0]["index"]["byteStart"], 23, "9 + 9 (ș is two bytes) + 5 (🚀 four)")
        self.assertEqual(f[0]["features"], [{"$type": "app.bsky.richtext.facet#link", "uri": "https://example.com/a"}])

    def test_the_limit(self):
        self.assertEqual(B.validate({"text": "👨‍👩‍👧" * 300}), [], "300 graphemes, a family emoji one")
        self.assertEqual(B.validate({"text": "a" * 301}), ["1 over Bluesky's 300"])
        self.assertIn("1 MB", B.validate({"text": "a", "image": b"x" * 1000001, "alt": "a"})[0])

    def test_a_post_with_its_card_and_the_session_kept(self):
        sky = Sky()
        post = {"text": "Read it https://example.com/blog/one", "image": None, "hash": "h",
                "card": {"url": "https://example.com/blog/one", "title": "One", "description": "Words", "thumb": b"\xff\xd8x"}}
        out = B.send(P.Net(sky), self.env, post, dry=False)
        self.assertEqual(out, {"url": "https://bsky.app/profile/captain.example.social/post/3m4abcdefgh2k",
                               "id": "at://did:plc:standin7captain/app.bsky.feed.post/3m4abcdefgh2k"})
        (rec,) = sky.calls("createRecord")
        body = json.loads(rec[3])
        self.assertEqual((body["repo"], body["collection"]), ("did:plc:standin7captain", "app.bsky.feed.post"))
        r = body["record"]
        self.assertEqual(r["text"], post["text"])
        self.assertRegex(r["createdAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.000Z$")
        self.assertEqual(r["facets"][0]["index"], {"byteStart": 8, "byteEnd": 36})
        self.assertEqual(r["embed"]["$type"], "app.bsky.embed.external")
        self.assertEqual(r["embed"]["external"]["thumb"]["ref"], {"$link": "bafkreistandinblob"})
        self.assertEqual(rec[2]["Authorization"], "Bearer bsky-ACCESS-standin-0003")
        self.assertEqual(len(sky.calls("createSession")), 1)
        mode = os.stat(B.state_path(self.env)).st_mode & 0o777
        self.assertEqual(mode, 0o600, "the session file is 0600")
        B.send(P.Net(sky), self.env, dict(post, hash="h2"), dry=False)
        self.assertEqual(len(sky.calls("createSession")), 1, "the session is kept between runs")

    def test_an_expired_token_is_refreshed(self):
        sky = Sky()
        B.session(P.Net(sky), self.env)
        sky.expire = 1
        B.send(P.Net(sky), self.env, {"text": "hi", "image": None, "hash": "h"}, dry=False)
        self.assertEqual(len(sky.calls("refreshSession")), 1)
        self.assertEqual(sky.calls("refreshSession")[0][2]["Authorization"], "Bearer bsky-REFRESH-standin-0004")
        self.assertEqual(len(sky.calls("createRecord")), 2, "refused once, then sent")
        self.assertEqual(len(sky.calls("createSession")), 1)

    def test_a_picture_with_alt_text(self):
        sky = Sky()
        B.send(P.Net(sky), self.env, {"text": "hi", "image": b"\x89PNG\r\n\x1a\nxx", "image_name": "a.png",
                                      "alt": "the bridge", "hash": "h"}, dry=False)
        (up,) = sky.calls("uploadBlob")
        self.assertEqual(up[2]["Content-Type"], "image/png")
        r = json.loads(sky.calls("createRecord")[0][3])["record"]
        self.assertEqual(r["embed"]["$type"], "app.bsky.embed.images")
        self.assertEqual(r["embed"]["images"][0]["alt"], "the bridge")

    def test_a_dry_run_makes_no_session(self):
        sky = Sky()
        out = B.send(P.Net(sky), self.env, {"text": "hi https://a.example/", "image": None, "hash": "h"}, dry=True)
        self.assertEqual(sky.asked, [])
        self.assertFalse(os.path.exists(B.state_path(self.env)))
        self.assertEqual(out["request"][-1]["json"]["record"]["facets"][0]["index"], {"byteStart": 3, "byteEnd": 21})
        self.assertNotIn(APP_PASS, json.dumps(out))

    def test_a_retry_finds_the_lost_post(self):
        sky = Sky()
        text = "Software for One\n\nI built a journal for one person.\n\nhttps://example.com/blog/one"
        out = B.send(P.Net(sky), self.env, {"text": text, "image": None, "hash": "h", "retry": True}, dry=False)
        self.assertEqual(out["url"], "https://bsky.app/profile/captain.example.social/post/3m4lost")
        self.assertEqual(sky.calls("createRecord"), [], "found, not posted again")

    def test_check(self):
        sky = Sky()
        self.assertEqual(B.check(P.Net(sky), self.env), {"ok": True, "account": "@captain.example.social"})
        self.assertFalse([a for a in sky.asked if "createRecord" in a[1] or "uploadBlob" in a[1]])
        bad = dict(self.env, LCARS_PUB_BLUESKY="captain.example.social:wrong")
        self.assertEqual(B.check(P.Net(Sky()), dict(bad, LCARS_PUB_STATE_DIR=tempfile.mkdtemp(prefix="lcars-test-publish-"))),
                         {"ok": False, "error": "Bluesky refused the app password: 401, Invalid identifier or password"})

    def test_the_hand_url(self):
        self.assertEqual(B.hand_url(BENV, {"text": "a b"}), "https://bsky.app/intent/compose?text=a%20b")


class Posting(unittest.TestCase):
    """3.10 items 3, 5, 6 and 7: a whole post, once per text, dry, the cap."""

    def run_post(self, j, inst=None, env=None, now=AT, **kw):
        inst = inst or Instance()
        return P.cmd_post(args(**kw), env=dict(ENV, **(env or {})), journal=j, net=P.Net(inst), now=now), inst

    def test_a_post_and_its_record(self):
        j = Journal([drafts()])
        out, inst = self.run_post(j)
        (r,) = out["results"]
        self.assertEqual((r["status"], r["url"], out["dry"]), ("posted", "https://example.social/@captain/113401234567890123", False))
        (status,) = inst.sent("/api/v1/statuses")
        self.assertEqual(json.loads(status[3])["status"],
                         "Software for One\n\nI built a journal for one person.\n\nhttps://example.com/blog/one")
        (rec,) = j.written
        self.assertEqual(rec["title"], "Mastodon · posted: Software for One")
        f = P.record_fields(rec["content"])
        self.assertEqual({k: f[k] for k in ("network", "status", "post", "by", "at")},
                         {"network": "mastodon", "status": "posted", "post": "#7", "by": "tap", "at": "2026-10-23T12:00:00Z"})
        self.assertEqual(f["hash"], P.text_hash(json.loads(status[3])["status"]))
        self.assertEqual(f["id"], "113401234567890123")

    def test_once_per_text(self):
        j = Journal([drafts()])
        self.run_post(j)
        out, inst = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "already")
        self.assertEqual(out["results"][0]["url"], "https://example.social/@captain/113401234567890123")
        self.assertEqual(inst.sent("/api/v1/statuses"), [], "the second sends nothing")
        self.assertEqual(len(j.written), 1)
        j.rows[0] = drafts(own="Another text")
        out, inst = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "posted", "another text is another post")

    def test_a_failure_is_recorded_and_a_retry_posts_once(self):
        j = Journal([drafts()])
        out, _ = self.run_post(j, inst=Instance(status_code=503))
        self.assertEqual(out["results"][0]["status"], "failed")
        self.assertEqual(P.record_fields(j.written[0]["content"])["status"], "failed")
        self.assertIn("503", P.record_fields(j.written[0]["content"])["error"])
        out, inst = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "posted", "a failed one does not count as posted")
        self.assertEqual(inst.sent("/api/v1/statuses")[0][2]["Idempotency-Key"], out["results"][0]["hash"],
                         "the retry carries the same key: the instance posts it once")

    def test_dry_is_the_default(self):
        j = Journal([drafts()])
        out, inst = self.run_post(j, env={"LCARS_PUB_DRY": ""})
        self.assertEqual((out["dry"], out["dry_by"], out["results"][0]["status"]), (True, "switch", "dry"))
        self.assertEqual([a[0] for a in inst.asked], ["GET"], "only the instance's limit was read")
        self.assertEqual(P.record_fields(j.written[0]["content"])["status"], "dry")
        self.assertEqual(out["results"][0]["request"][0]["url"], "https://example.social/api/v1/statuses")
        for v in ("1", "yes", "true"):
            self.assertTrue(P.is_dry({"LCARS_PUB_DRY": v}, False))
        self.assertTrue(P.is_dry({}, False))
        self.assertFalse(P.is_dry({"LCARS_PUB_DRY": "0"}, False))
        self.assertTrue(P.is_dry({"LCARS_PUB_DRY": "0"}, True), "--dry-run is dry whatever the switch")
        out, inst = self.run_post(j, dry_run=True)
        self.assertEqual((out["dry_by"], inst.sent("/api/v1/statuses")), ("asked", []))
        out, _ = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "posted", "a dry run is not a post")

    def test_the_cap(self):
        j = Journal([drafts()])
        for i in range(P.DAILY_CAP):
            j.write("x", P.record_text({"network": "mastodon", "status": "posted", "hash": str(i),
                                        "at": "2026-10-23T06:00:00Z"}))
        j.write("x", P.record_text({"network": "mastodon", "status": "posted", "hash": "y", "at": "2026-10-22T20:00:00Z"}))
        out, inst = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "capped")
        self.assertIn("5 posted today", out["results"][0]["error"])
        self.assertEqual(inst.sent("/api/v1/statuses"), [])
        out, _ = self.run_post(j, now=AT + dt.timedelta(hours=12))
        self.assertEqual(out["results"][0]["status"], "posted", "the captain's next day (00:00 Helsinki is 21:00 UTC)")

    def test_bluesky_whole_with_the_card(self):
        st = tempfile.mkdtemp(prefix="lcars-test-publish-")
        j = Journal([drafts()])
        j.rows[0]["content"] = j.rows[0]["content"].replace('"nets": {"mastodon"', '"nets": {"bluesky"')
        seen = []
        cards = lambda u: seen.append(u) or {"url": u, "title": "One", "description": "Words", "thumb": None}  # noqa: E731
        sky = Sky(record_code=503)
        env = dict(BENV, LCARS_PUB_STATE_DIR=st)
        out = P.cmd_post(args(networks="bluesky"), env=env, journal=j, net=P.Net(sky), now=AT, cards=cards)
        self.assertEqual(out["results"][0]["status"], "failed")
        self.assertEqual(seen, ["https://example.com/blog/one"], "the link's card read")
        sky.record_code = 200
        out = P.cmd_post(args(networks="bluesky"), env=env, journal=j, net=P.Net(sky), now=AT, cards=cards)
        self.assertEqual(out["results"][0]["status"], "posted")
        self.assertEqual(out["results"][0]["url"], "https://bsky.app/profile/captain.example.social/post/3m4lost",
                         "after a failure, his feed is read first: it went out after all")
        self.assertEqual(len(sky.calls("createRecord")), 1, "the one failed attempt only")
        out = P.cmd_post(args(networks="bluesky"), env=env, journal=j, net=P.Net(sky), now=AT, cards=cards)
        self.assertEqual(out["results"][0]["status"], "already")

    def test_refusals(self):
        j = Journal([drafts(), {"id": 8, "kind": "personal", "title": "x", "content": "{}"}])
        with self.assertRaises(P.Fail) as e:
            self.run_post(j, eid=8)
        self.assertEqual(e.exception.code, 2)
        with self.assertRaises(P.Fail) as e:
            self.run_post(j, eid=9)
        self.assertEqual(e.exception.code, 4)
        with self.assertRaises(P.Fail):
            self.run_post(j, networks="Mastodon;rm")
        out, _ = self.run_post(j, networks="mastodon,x,hn")
        self.assertEqual([r["status"] for r in out["results"]], ["posted", "refused", "refused"])
        self.assertIn("hand route", out["results"][1]["error"])
        out, _ = self.run_post(Journal([drafts(own="a" * 600)]))
        self.assertEqual(out["results"][0]["status"], "invalid")
        out, _ = self.run_post(Journal([drafts()]), env={"LCARS_PUB_MASTODON": ""})
        self.assertEqual(out["results"][0]["status"], "unconfigured")

    def test_the_picture_from_the_journals_media(self):
        j = Journal([drafts(img="media/2026/bridge.jpg", alt="the bridge")], media={"media/2026/bridge.jpg": b"\xff\xd8x"})
        out, inst = self.run_post(j)
        self.assertEqual(out["results"][0]["status"], "posted")
        self.assertEqual(len(inst.sent("/api/v2/media")), 1)
        out, _ = self.run_post(Journal([drafts(img="https://elsewhere.example/a.jpg", alt="a")]))
        self.assertEqual(out["results"][0]["status"], "invalid")
        self.assertIn("not in the journal's media", out["results"][0]["error"])
        with self.assertRaises(P.Fail):
            P.Journal.media(types.SimpleNamespace(), "media/../../etc/passwd")


class Card(unittest.TestCase):
    """POST /publish/card's reader: og: tags, and only public links."""

    def test_the_tags(self):
        c = P.cmd_card(types.SimpleNamespace(url="https://blog.example/one/"),
                       fetch=lambda u: (200, sample("card.html"), ""), public=lambda h: True)["card"]
        self.assertEqual(c, {"url": "https://blog.example/one/", "title": "Software for One: my Star Trek computer",
                             "description": "I built a journal for one person & its ship.",
                             "image": "https://blog.example/images/bridge.jpg", "site": "A Blog"})
        c = P.parse_card("https://b.example/", "<title> Just a\n title </title>")
        self.assertEqual((c["title"], c["image"], c["site"]), ("Just a title", "", "b.example"))

    def test_only_public_links_and_redirects_checked(self):
        no = lambda h: h != "intranet.example"  # noqa: E731
        for url in ("file:///etc/passwd", "ftp://a.example/", "https://intranet.example/"):
            with self.assertRaises(P.Fail):
                P.cmd_card(types.SimpleNamespace(url=url), fetch=lambda u: (200, "", ""), public=no)
        hops = {"https://a.example/": (301, "", "https://intranet.example/x")}
        with self.assertRaises(P.Fail) as e:
            P.cmd_card(types.SimpleNamespace(url="https://a.example/"), fetch=lambda u: hops.get(u, (200, "", "")), public=no)
        self.assertIn("not on the public internet", str(e.exception))
        self.assertFalse(P.public_host("127.0.0.1"))
        self.assertFalse(P.public_host("10.1.2.3"))
        self.assertFalse(P.public_host("100.100.1.1"), "the tailnet's CGNAT range")
        self.assertFalse(P.public_host("169.254.169.254"))


class StandIn(http.server.BaseHTTPRequestHandler):
    """The journal and the instance on one port: what the CLI run talks to."""
    rows, asked = [], []

    def log_message(self, *a):
        pass

    def answer(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        StandIn.asked.append(("GET", self.path, dict(self.headers)))
        if self.path == "/entries/7":
            return self.answer(200, drafts())
        if self.path.startswith("/entries?"):
            return self.answer(200, [r for r in StandIn.rows if r["kind"] == P.RECORD])
        if self.path == "/api/v2/instance":
            return self.answer(200, json.loads(sample("mastodon_instance.json")))
        if self.path == "/api/v1/accounts/verify_credentials":
            return self.answer(200, json.loads(sample("mastodon_verify.json")))
        self.answer(404, {"error": "no"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        StandIn.asked.append(("POST", self.path, dict(self.headers), data))
        if self.path == "/entries":
            b = json.loads(data)
            b["id"] = 500 + len(StandIn.rows)
            StandIn.rows.append(b)
            return self.answer(201, {"id": b["id"]})
        if self.path == "/api/v1/statuses":
            return self.answer(200, json.loads(sample("mastodon_status.json")))
        self.answer(404, {"error": "no"})


class CommandLine(unittest.TestCase):
    """A whole run as the server starts it: argv, the environment, one
    JSON object out; no secret in anything it prints or writes."""

    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.state = tempfile.mkdtemp(prefix="lcars-test-publish-")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_cli(self, *argv, **env):
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.state, "LCARS_CREW_ENV": os.devnull,
             "LCARS_CREW_STATE": self.state, "LCARS_CREW_TZ": "Europe/Helsinki", "LCARS_URL": self.base,
             "LCARS_CREW_USER": "crew", "LCARS_CREW_PASS": CREW_PASS,
             "LCARS_PUB_MASTODON": f"{self.base}:{TOKEN}", **env}
        p = subprocess.run([sys.executable, os.path.join(HERE, "publish.py"), *argv], env=e,
                           capture_output=True, text=True, timeout=30)
        for s in SECRETS:
            self.assertNotIn(s, p.stdout + p.stderr)
        return p.returncode, p.stdout

    def test_a_dry_run_then_a_post(self):
        StandIn.rows, StandIn.asked = [], []
        code, out = self.run_cli("post", "7", "--networks", "mastodon")
        self.assertEqual(code, 0, out)
        j = json.loads(out)
        self.assertEqual((j["dry"], j["results"][0]["status"]), (True, "dry"), "LCARS_PUB_DRY unset: dry")
        self.assertFalse([a for a in StandIn.asked if a[1] == "/api/v1/statuses"])
        code, out = self.run_cli("post", "7", "--networks", "mastodon", LCARS_PUB_DRY="0")
        j = json.loads(out)
        self.assertEqual(j["results"][0]["status"], "posted")
        (st,) = [a for a in StandIn.asked if a[1] == "/api/v1/statuses"]
        self.assertEqual(st[2]["Authorization"], "Bearer " + TOKEN)
        crew = [a for a in StandIn.asked if a[1] == "/entries"]
        self.assertEqual(len(crew), 2)
        self.assertTrue(all(a[2]["Authorization"].startswith("Basic ") for a in crew))
        for r in StandIn.rows:
            for s in SECRETS:
                self.assertNotIn(s, json.dumps(r))
        with open(os.path.join(self.state, "runs.jsonl")) as f:
            runs = [json.loads(ln) for ln in f]
        self.assertEqual([(r["role"], r["status"]) for r in runs[-2:]], [("publish", "dry"), ("publish", "posted")])
        code, out = self.run_cli("post", "7", "--networks", "mastodon", LCARS_PUB_DRY="0")
        self.assertEqual(json.loads(out)["results"][0]["status"], "already")

    def test_check(self):
        code, out = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("Mastodon: ok, @captain@127.0.0.1", out)
        self.assertIn("dry run: on", out)
        code, out = self.run_cli("check", "--json", LCARS_PUB_MASTODON="")
        self.assertEqual(json.loads(out)["networks"]["mastodon"]["ok"], False)

    def test_exit_codes(self):
        self.assertEqual(self.run_cli("post", "9", "--networks", "mastodon")[0], 4)
        self.assertEqual(self.run_cli("card", "file:///etc/passwd")[0], 2)
        self.assertEqual(self.run_cli("post", "7", "--networks", "mastodon", LCARS_CREW_PASS="")[0], 1)


if __name__ == "__main__":
    unittest.main()
