"""Mastodon (docs/design/social-publish.md 1.1): a status, its picture with
alt text, once per text by Idempotency-Key; the instance's own limit.

The credential is LCARS_PUB_MASTODON=<instance host>:<access token>, a
token from the instance's Preferences, Development, New application, with
the scopes write:statuses write:media and profile (`check`'s
verify_credentials needs it; read:accounts on a Mastodon older than 4.3),
and read:notifications for the watch's slice 4. A stand-in instance for
the tests is http://127.0.0.1:<port>:<token>; plain http is refused for any other host.
"""

import json
import re
import time
import urllib.parse

from . import body as _body, count, LIMITS

KEY, NAME, VAR = "mastodon", "Mastodon", "LCARS_PUB_MASTODON"
DEFAULT_LIMIT = LIMITS["networks"][KEY]["limit"]
HOST_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I)
LOCAL_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):\d+$")
MEDIA_WAIT = 5            # polls of a picture still processing (202), a second apart


def creds(env):
    """(base url, token), or None when the variable is missing or not the shape."""
    v = (env.get(VAR) or "").strip()
    if not v:
        return None
    host, _, token = v.rpartition(":")
    token = token.strip()
    if not token or not re.match(r"^[A-Za-z0-9_\-.~+/=]+$", token):
        return None
    host = host.strip().rstrip("/")
    if LOCAL_RE.match(host):
        return host, token
    host = re.sub(r"^https://", "", host, flags=re.I)
    return ("https://" + host, token) if HOST_RE.match(host) else None


def configured(env):
    if not (env.get(VAR) or "").strip():
        return f"Mastodon: no {VAR} in ~/.env"
    if creds(env) is None:
        return f"Mastodon: {VAR} is not <instance host>:<access token>"
    return None


def _auth(token):
    return {"Authorization": "Bearer " + token}


def limit(net, env):
    """The instance's configuration.statuses.max_characters (500 on most);
    the table's when the instance does not say."""
    c = creds(env)
    if not c:
        return DEFAULT_LIMIT
    st, j, _ = net("GET", c[0] + "/api/v2/instance")
    try:
        n = int(j["configuration"]["statuses"]["max_characters"]) if st == 200 else 0
    except (KeyError, TypeError, ValueError):
        n = 0
    return n if n > 0 else DEFAULT_LIMIT


def validate(post, lim=DEFAULT_LIMIT):
    errs = []
    t = post.get("text") or ""
    if not t.strip():
        errs.append("nothing to post")
    n = count(KEY, t)
    if n > lim:
        errs.append(f"{n - lim} over the instance's {lim}")
    if post.get("image") is not None and not (post.get("alt") or "").strip():
        errs.append("the picture needs its alt text")
    return errs


def _multipart(name, data, alt):
    """POST /api/v2/media's form: the file and its description."""
    b = "lcarsform" + str(int(time.time() * 1000))
    ctype = "image/png" if name.lower().endswith(".png") else "image/webp" if name.lower().endswith(".webp") \
        else "image/gif" if name.lower().endswith(".gif") else "image/jpeg"
    safe = re.sub(r'["\r\n\\]', "_", name or "picture")
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="description"\r\n\r\n'.encode() + alt.encode() + b"\r\n",
             f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
             f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n",
             f"--{b}--\r\n".encode()]
    return b"".join(parts), "multipart/form-data; boundary=" + b


def send(net, env, post, dry):
    """The status, posted; or in a dry run the requests it would make, each
    secret replaced by "…". Raises RuntimeError with the instance's words."""
    base, token = creds(env)
    status = {"status": post["text"], "visibility": "public"}
    reqs = []
    if post.get("image") is not None:
        reqs.append({"method": "POST", "url": base + "/api/v2/media",
                     "headers": {"Authorization": "Bearer …"},
                     "form": {"file": f"{post.get('image_name') or 'picture'} ({len(post['image'])} bytes)",
                              "description": post.get("alt") or ""}})
    reqs.append({"method": "POST", "url": base + "/api/v1/statuses",
                 "headers": {"Authorization": "Bearer …", "Idempotency-Key": post["hash"]},
                 "json": dict(status, **({"media_ids": ["<the picture's id>"]} if post.get("image") is not None else {}))})
    if dry:
        return {"request": reqs}
    if post.get("image") is not None:
        form, ctype = _multipart(post.get("image_name") or "picture", post["image"], post.get("alt") or "")
        st, j, text = net("POST", base + "/api/v2/media", dict(_auth(token), **{"Content-Type": ctype}), form)
        if st not in (200, 202) or not isinstance(j, dict) or not j.get("id"):
            raise RuntimeError(_said("the picture", st, j, text))
        mid = str(j["id"])
        # a 202 is still processing: a status naming it would be refused
        for _ in range(MEDIA_WAIT if st == 202 else 0):
            time.sleep(1)
            st2, j2, _t = net("GET", base + "/api/v1/media/" + urllib.parse.quote(mid), _auth(token))
            if st2 == 200 and isinstance(j2, dict) and j2.get("url"):
                break
        status["media_ids"] = [mid]
    st, j, text = net("POST", base + "/api/v1/statuses",
                      dict(_auth(token), **{"Content-Type": "application/json", "Idempotency-Key": post["hash"]}),
                      json.dumps(status, ensure_ascii=False).encode())
    if st != 200 or not isinstance(j, dict) or not j.get("id"):
        raise RuntimeError(_said("the status", st, j, text))
    return {"url": j.get("url") or j.get("uri") or "", "id": str(j["id"])}


def check(net, env):
    """The credential proved by GET verify_credentials, which posts nothing."""
    why = configured(env)
    if why:
        return {"ok": False, "error": why}
    base, token = creds(env)
    st, j, text = net("GET", base + "/api/v1/accounts/verify_credentials", _auth(token))
    if st == 200 and isinstance(j, dict) and j.get("acct"):
        host = urllib.parse.urlparse(base).hostname or ""
        return {"ok": True, "account": "@" + j["acct"] + ("" if "@" in j["acct"] else "@" + host)}
    return {"ok": False, "error": _said("the token", st, j, text)}


def hand_url(env, post):
    c = creds(env)
    return (c[0] + "/share?text=" + urllib.parse.quote(post.get("text") or "")) if c else ""


def _said(what, st, j, text):
    """The instance's error in a line: its `error` member, else the status."""
    msg = j.get("error") if isinstance(j, dict) else ""
    if not msg:
        msg = re.sub(r"<[^>]+>|\s+", " ", text or "")[:120].strip()
    return f"Mastodon refused {what}: {st}" + (f", {msg}" if msg else "") if st else f"Mastodon: no answer ({msg})"


def build(text, link):
    """The status text from the sheet's card: shared by publish.py and the tests."""
    return _body(text, link)
