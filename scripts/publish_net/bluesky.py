"""Bluesky (docs/design/social-publish.md 1.2): a post record with its link
facets (UTF-8 byte offsets) and the link's card (app.bsky.embed.external,
its thumbnail uploaded as a blob), or a picture with alt text; 300
graphemes.

The credential is LCARS_PUB_BLUESKY=<handle>:<app password>, an app
password from Settings, Privacy and security, App passwords, made without
"allow direct messages". It is used for com.atproto.server.createSession
only when there is no session to reuse: the session's tokens are kept in
~/.config/lcars/publish-bluesky.json (0600, LCARS_PUB_STATE_DIR in the
tests), refreshed with refreshSession when the access token expires, since
createSession is limited to 30 per 5 minutes and 300 a day. The PDS is
https://bsky.social unless LCARS_PUB_BLUESKY_PDS names another (https, or
a stand-in on 127.0.0.1).

Bluesky has no idempotency key: a retry of a text whose last attempt
failed first reads his latest posts (getAuthorFeed, free) and answers the
one with this text, if it went out after all, instead of posting again.
"""

import datetime as dt
import json
import os
import re
import urllib.parse

from . import LINK_RE, count

KEY, NAME, VAR = "bluesky", "Bluesky", "LCARS_PUB_BLUESKY"
DEFAULT_LIMIT = 300
PDS = "https://bsky.social"
BLOB_MAX = 1000000                 # Bluesky's ceiling for an image blob
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)
LOCAL_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):\d+$")
WANTS_CARD = True                  # publish.py reads the link's og: tags for it
TRAIL = ".,;:!?)]}'\""


def creds(env):
    """(handle, app password, pds), or None."""
    v = (env.get(VAR) or "").strip()
    handle, _, pw = v.partition(":")
    handle, pw = handle.strip().lstrip("@"), pw.strip()
    if not HANDLE_RE.match(handle) or not pw:
        return None
    pds = (env.get("LCARS_PUB_BLUESKY_PDS") or PDS).strip().rstrip("/")
    if not (LOCAL_RE.match(pds) or re.match(r"^https://[a-z0-9.-]+\.[a-z]{2,}$", pds, re.I)):
        return None
    return handle, pw, pds


def configured(env):
    if not (env.get(VAR) or "").strip():
        return f"Bluesky: no {VAR} in ~/.env"
    if creds(env) is None:
        return f"Bluesky: {VAR} is not <handle>:<app password>"
    return None


def limit(net, env):
    return DEFAULT_LIMIT


def validate(post, lim=DEFAULT_LIMIT):
    errs = []
    t = post.get("text") or ""
    if not t.strip():
        errs.append("nothing to post")
    n = count(KEY, t)
    if n > lim:
        errs.append(f"{n - lim} over Bluesky's {lim}")
    if post.get("image") is not None:
        if not (post.get("alt") or "").strip():
            errs.append("the picture needs its alt text")
        if len(post["image"]) > BLOB_MAX:
            errs.append("the picture is over Bluesky's 1 MB")
    return errs


def facets(text):
    """A link facet per URL in the text, by UTF-8 byte offsets."""
    out = []
    for m in LINK_RE.finditer(text):
        url = m.group(0).rstrip(TRAIL)
        start = len(text[:m.start()].encode("utf-8"))
        out.append({"index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
                    "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
    return out


# ---- the session, kept between runs --------------------------------------------

def state_path(env):
    d = env.get("LCARS_PUB_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".config", "lcars")
    return os.path.join(d, "publish-bluesky.json")


def load_session(env, handle):
    try:
        with open(state_path(env)) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return None
    return s if isinstance(s, dict) and s.get("handle") == handle and s.get("accessJwt") and s.get("did") else None


def save_session(env, s):
    """0600 from its first byte: the tokens are as good as the app password."""
    p = state_path(env)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _json(net, method, url, body=None, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        h.setdefault("Content-Type", "application/json")
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    return net(method, url, h, data)


def _keep(env, handle, j):
    s = {"handle": handle, "did": j.get("did"), "accessJwt": j.get("accessJwt"), "refreshJwt": j.get("refreshJwt")}
    save_session(env, s)
    return s


def session(net, env, fresh=False):
    handle, pw, pds = creds(env)
    s = None if fresh else load_session(env, handle)
    if s:
        return s
    st, j, text = _json(net, "POST", pds + "/xrpc/com.atproto.server.createSession",
                        {"identifier": handle, "password": pw})
    if st != 200 or not isinstance(j, dict) or not j.get("accessJwt") or not j.get("did"):
        raise RuntimeError(_said("the app password", st, j, text))
    return _keep(env, handle, j)


def _expired(st, j):
    return st in (400, 401) and isinstance(j, dict) and j.get("error") in ("ExpiredToken", "InvalidToken")


def call(net, env, method, path, body=None, headers=None):
    """An authenticated XRPC call: the kept session, refreshed once when
    its access token has expired, a new one when the refresh is refused."""
    handle, _pw, pds = creds(env)
    s = session(net, env)
    st, j, text = _json(net, method, pds + path, body, s["accessJwt"], headers)
    if not _expired(st, j):
        return st, j, text, s
    st2, j2, _t = _json(net, "POST", pds + "/xrpc/com.atproto.server.refreshSession", None, s.get("refreshJwt"))
    s = _keep(env, handle, j2) if st2 == 200 and isinstance(j2, dict) and j2.get("accessJwt") \
        else session(net, env, fresh=True)
    st, j, text = _json(net, method, pds + path, body, s["accessJwt"], headers)
    return st, j, text, s


# ---- the post --------------------------------------------------------------------

def _ctype(name, data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


def post_url(handle, uri):
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def record(post, now=None):
    """The post record, its embed's blobs as placeholders the send fills."""
    rec = {"$type": "app.bsky.feed.post", "text": post["text"],
           "createdAt": (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    f = facets(post["text"])
    if f:
        rec["facets"] = f
    card = post.get("card") or {}
    if post.get("image") is not None:
        rec["embed"] = {"$type": "app.bsky.embed.images",
                        "images": [{"alt": post.get("alt") or "", "image": "<the picture's blob>"}]}
    elif card.get("url") and (card.get("title") or card.get("description")):
        ext = {"uri": card["url"], "title": card.get("title") or "", "description": card.get("description") or ""}
        if card.get("thumb") is not None:
            ext["thumb"] = "<the thumbnail's blob>"
        rec["embed"] = {"$type": "app.bsky.embed.external", "external": ext}
    return rec


def _blob(net, env, data, name):
    st, j, text, _s = call(net, env, "POST", "/xrpc/com.atproto.repo.uploadBlob", data,
                           {"Content-Type": _ctype(name, data)})
    if st != 200 or not isinstance(j, dict) or not isinstance(j.get("blob"), dict):
        raise RuntimeError(_said("the picture", st, j, text))
    return j["blob"]


def _sent_already(net, env, text):
    """His latest posts, for this text: a retry after a lost answer."""
    s = session(net, env)
    st, j, _t, s = call(net, env, "GET", "/xrpc/app.bsky.feed.getAuthorFeed?" +
                        urllib.parse.urlencode({"actor": s["did"], "limit": 10, "filter": "posts_no_replies"}))
    for item in (j or {}).get("feed", []) if st == 200 and isinstance(j, dict) else []:
        p = item.get("post") or {}
        if (p.get("record") or {}).get("text") == text and p.get("uri"):
            return {"url": post_url(s["handle"], p["uri"]), "id": p["uri"]}
    return None


def send(net, env, post, dry):
    handle, _pw, pds = creds(env)
    rec = record(post)
    reqs = []
    if post.get("image") is not None or (post.get("card") or {}).get("thumb") is not None:
        reqs.append({"method": "POST", "url": pds + "/xrpc/com.atproto.repo.uploadBlob",
                     "headers": {"Authorization": "Bearer …"}})
    reqs.append({"method": "POST", "url": pds + "/xrpc/com.atproto.repo.createRecord",
                 "headers": {"Authorization": "Bearer …"},
                 "json": {"repo": "<his did>", "collection": "app.bsky.feed.post", "record": rec}})
    if dry:
        return {"request": reqs}
    if post.get("retry"):
        found = _sent_already(net, env, post["text"])
        if found:
            return found
    if post.get("image") is not None:
        rec["embed"]["images"][0]["image"] = _blob(net, env, post["image"], post.get("image_name") or "")
    elif "embed" in rec and "thumb" in rec["embed"]["external"]:
        try:
            rec["embed"]["external"]["thumb"] = _blob(net, env, post["card"]["thumb"], "thumb")
        except RuntimeError:
            del rec["embed"]["external"]["thumb"]   # a card without its picture beats no post
    s = session(net, env)
    st, j, text, s = call(net, env, "POST", "/xrpc/com.atproto.repo.createRecord",
                          {"repo": s["did"], "collection": "app.bsky.feed.post", "record": rec})
    if st != 200 or not isinstance(j, dict) or not j.get("uri"):
        raise RuntimeError(_said("the post", st, j, text))
    return {"url": post_url(handle, j["uri"]), "id": j["uri"]}


def check(net, env):
    """The credential proved by getSession (a session made first if none is
    kept), which posts nothing."""
    why = configured(env)
    if why:
        return {"ok": False, "error": why}
    try:
        st, j, text, s = call(net, env, "GET", "/xrpc/com.atproto.server.getSession")
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if st == 200 and isinstance(j, dict) and j.get("handle"):
        return {"ok": True, "account": "@" + j["handle"]}
    return {"ok": False, "error": _said("the session", st, j, text)}


def hand_url(env, post):
    return "https://bsky.app/intent/compose?text=" + urllib.parse.quote(post.get("text") or "")


def _said(what, st, j, text):
    msg = ""
    if isinstance(j, dict):
        msg = j.get("message") or j.get("error") or ""
    if not msg:
        msg = re.sub(r"<[^>]+>|\s+", " ", text or "")[:120].strip()
    return f"Bluesky refused {what}: {st}" + (f", {msg}" if msg else "") if st else f"Bluesky: no answer ({msg})"
