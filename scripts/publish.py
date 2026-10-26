#!/usr/bin/env python3
"""The publisher: posts what the captain tapped Post on in the Share sheet
(docs/design/social-publish.md, slice 2). No model.

    publish.py post <id> --networks mastodon[,..] [--dry-run] [--by tap]
    publish.py check [--json]          each network's credential, by a free read
    publish.py card <url>              a link's og: title, description, picture

Providers: Mastodon and Bluesky (publish_net/). `post` reads the `social_post` entry <id> (pages-only: the Share sheet's
drafts, which no agent or crew note can write), and for each network:

1. the provider's credential (configured), else "unconfigured";
2. the text as the network gets it, checked against the network's own
   limit (validate), else "invalid";
3. once per text: a `crew_social_post` record with this network, this
   text's SHA-256 and `status: posted` answers "already", with its link,
   and nothing is sent; a retry inside the hour is caught by the network
   too (Mastodon's Idempotency-Key is the hash);
4. the daily cap (DAILY_CAP posted per network in the captain's day),
   else "capped";
5. sent - or, in a dry run, built and not sent, the requests in the answer
   with every secret replaced by "…";
6. one `crew_social_post` record, written with the crew login, for every
   attempt that got this far: posted, failed (with the error) or dry. And
   a line in the crew's runs.jsonl.

A dry run is the default: LCARS_PUB_DRY unset, or anything but 0, is dry
(the captain's word for the first week, 2026-10-23: "whatever ~/.env says
is the switch"). LCARS_PUB_DRY=0 posts.

It prints one JSON object: {"results": [{network, status, url?, error?,
request?, record?}], "dry": bool}. Exit 0 when it ran (each network's
outcome is in its result), 2 a bad argument, 4 no such entry, 1 the
journal not answering.

Who runs it: the server's POST /publish/<id> (lcars_publish.h), the owner's
login from the pages only; and the captain at a terminal. The crew's timer
(slice 3) will run only `due`, which posts only text approved by hash.

The environment first, then ~/.env (LCARS_CREW_ENV): the server passes its
own, which the unit sourced from ~/.env; a terminal has only the file. No
credential is ever printed, written to the journal or put in an argv.
"""

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crew_tool as T  # noqa: E402  read_env, the captain's zone
from publish_net import body as text_body  # noqa: E402
from publish_net import bluesky, mastodon  # noqa: E402

PROVIDERS = {"mastodon": mastodon, "bluesky": bluesky}
POST_KIND = "social_post"
RECORD = "crew_social_post"
DAILY_CAP = 5                     # posted per network per day (the captain's, 2026-10-23)
MEDIA_MAX = 16 * 1024 * 1024      # Mastodon's own ceiling for a picture
CARD_MAX = 512 * 1024             # read of a page for its og: tags
UA = "lcars-publish/1.0"
STATE = os.environ.get("LCARS_CREW_STATE") or os.path.join(os.path.expanduser("~"), ".local", "state", "lcars-crew")
NETWORK_RE = re.compile(r"^[a-z]{1,16}$")


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def settings():
    """The process's environment over ~/.env's lines (never sourced)."""
    env = T.read_env()
    env.update(os.environ)
    return env


def is_dry(env, asked):
    return bool(asked) or (env.get("LCARS_PUB_DRY") or "1").strip() != "0"


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- HTTP to the networks -----------------------------------------------------

def _http(method, url, headers=None, data=None, timeout=20):
    """(status, parsed JSON or None, text); a 4xx/5xx is an answer, no
    answer at all is status 0."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            st, text = r.status, r.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, text = e.code, e.read(65536).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, None, str(getattr(e, "reason", e))
    try:
        return st, json.loads(text), text
    except ValueError:
        return st, None, text


class Net:
    """Every request to a network, recorded (method, url: never a header),
    so a test reads `asked` to prove what went out and what did not."""

    def __init__(self, http=None):
        self.http, self.asked = http or _http, []

    def __call__(self, method, url, headers=None, data=None):
        self.asked.append((method, url))
        return self.http(method, url, dict(headers or {}, **{"User-Agent": UA}), data)


# ---- the journal, as the crew -------------------------------------------------

class Journal:
    """GET and POST /entries with the crew login (LCARS_CREW_USER/PASS),
    at LCARS_URL (the server sets it to itself), else LCARS_CREW_URL."""

    def __init__(self, env):
        self.url = (env.get("LCARS_URL") or env.get("LCARS_CREW_URL") or "http://127.0.0.1:8080").rstrip("/")
        user, pw = env.get("LCARS_CREW_USER"), env.get("LCARS_CREW_PASS")
        if not user or not pw:
            raise Fail("no LCARS_CREW_USER/LCARS_CREW_PASS: the records are the crew's to write")
        import base64
        self.auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()

    def _req(self, method, path, body=None, raw=False, timeout=30):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read(MEDIA_MAX + 1)
                return r.status, b if raw else b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(65536).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            raise Fail(f"the journal at {self.url} did not answer: {getattr(e, 'reason', e)}")

    def get(self, eid):
        st, text = self._req("GET", f"/entries/{int(eid)}")
        if st == 404:
            raise Fail(f"no entry #{eid}", 4)
        if st != 200:
            raise Fail(f"GET /entries/{eid}: {st}")
        return json.loads(text)

    def records(self):
        st, text = self._req("GET", "/entries?" + urllib.parse.urlencode({"kind": RECORD, "limit": 1000}))
        if st != 200:
            raise Fail(f"GET /entries?kind={RECORD}: {st}")
        rows = json.loads(text)
        return rows if isinstance(rows, list) else []

    def write(self, title, content):
        st, text = self._req("POST", "/entries", {"kind": RECORD, "title": title, "content": content})
        if st not in (200, 201):
            raise Fail(f"the record was not written: {st} {text[:120]}")
        return json.loads(text).get("id")

    def media(self, path):
        p = "/" + path.lstrip("/")
        if not p.startswith("/media/") or ".." in p.split("/"):
            raise Fail("the picture is not in the journal's media: attach it by hand", 2)
        st, b = self._req("GET", urllib.parse.quote(p), raw=True)
        if st != 200:
            raise Fail(f"the picture {path}: {st}", 2)
        if len(b) > MEDIA_MAX:
            raise Fail("the picture is over 16 MB", 2)
        return b


# ---- the records -------------------------------------------------------------

def record_fields(content):
    """A record's `key: value` lines."""
    out = {}
    for ln in (content or "").splitlines():
        k, sep, v = ln.partition(": ")
        if sep and re.match(r"^[a-z_]+$", k) and k not in out:
            out[k] = v.strip()
    return out


def record_text(f):
    order = ("network", "status", "url", "id", "post", "hash", "at", "by", "error")
    return "\n".join(f"{k}: {f[k]}" for k in order if f.get(k) not in (None, "")) + "\n"


def posted_before(rows, network, h):
    for r in sorted(rows, key=lambda r: r.get("id", 0)):
        if r.get("deleted"):
            continue
        f = record_fields(r.get("content"))
        if f.get("network") == network and f.get("hash") == h and f.get("status") == "posted":
            return f
    return None


def posted_today(rows, network, now):
    """Posted to `network` in the captain's day of `now`."""
    day, n = now.astimezone(T.TZ).date(), 0
    for r in rows:
        f = record_fields(r.get("content"))
        if r.get("deleted") or f.get("network") != network or f.get("status") != "posted":
            continue
        try:
            at = dt.datetime.fromisoformat(f.get("at", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        n += at.astimezone(T.TZ).date() == day
    return n


def log_run(rec):
    """A line per send in the crew's runs.jsonl (crew.py trims it)."""
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "runs.jsonl"), "a") as f:
            f.write(json.dumps(dict(rec, role="publish")) + "\n")
    except OSError:
        pass


# ---- post --------------------------------------------------------------------

def drafts(row):
    """The Share sheet's social_post, read: {link, img, alt, text, nets}."""
    if row.get("kind") != POST_KIND:
        raise Fail(f"#{row.get('id')} is a {row.get('kind')}, not a {POST_KIND}: only the Share sheet's drafts are posted", 2)
    try:
        j = json.loads(row.get("content") or "")
    except ValueError:
        raise Fail(f"#{row.get('id')} is not the Share sheet's JSON", 2)
    if not isinstance(j, dict):
        raise Fail(f"#{row.get('id')} is not the Share sheet's JSON", 2)
    return j


def resolve(j, key, journal, cards=None):
    """The network's post: its own text or the shared one, the link added,
    the picture's bytes from the journal's media, and for a network that
    draws its own link card (Bluesky) the link's og: card. A card that
    cannot be read is no card, not a failed post."""
    n = (j.get("nets") or {}).get(key) or {}
    text = n.get("text") if n.get("own") and isinstance(n.get("text"), str) else j.get("text") or ""
    full = text_body(text, j.get("link") or "")
    img = (j.get("img") or "").strip()
    post = {"text": full, "image": None, "image_name": "", "alt": (j.get("alt") or "").strip(), "hash": text_hash(full)}
    if img:
        post["image"] = journal.media(img)
        post["image_name"] = img.rsplit("/", 1)[-1]
    link = (j.get("link") or "").strip()
    if getattr(PROVIDERS[key], "WANTS_CARD", False) and link and not img and cards is not None:
        try:
            post["card"] = cards(link)
        except Fail:
            post["card"] = None
    return post


def failed_before(rows, network, h):
    return any(not r.get("deleted") and record_fields(r.get("content")).get("network") == network
               and record_fields(r.get("content")).get("hash") == h
               and record_fields(r.get("content")).get("status") == "failed" for r in rows)


def post_one(key, j, row, journal, net, env, dry, by, rows, now, cards=None):
    prov = PROVIDERS.get(key)
    if prov is None:
        return {"network": key, "status": "refused", "error": f"no publisher for {key}: use its Open (the hand route)"}
    why = prov.configured(env)
    if why:
        return {"network": key, "status": "unconfigured", "error": why}
    try:
        post = resolve(j, key, journal, cards)
    except Fail as e:
        return {"network": key, "status": "invalid", "error": str(e)}
    errs = prov.validate(post, prov.limit(net, env))
    if errs:
        return {"network": key, "status": "invalid", "error": "; ".join(errs)}
    done = posted_before(rows, key, post["hash"])
    if done:
        return {"network": key, "status": "already", "url": done.get("url", ""), "at": done.get("at", ""),
                "hash": post["hash"]}
    if not dry and posted_today(rows, key, now) >= DAILY_CAP:
        return {"network": key, "status": "capped",
                "error": f"{prov.NAME}: {DAILY_CAP} posted today already, the day's cap"}
    # a text whose last attempt failed may have gone out all the same (an
    # answer lost): a network with no idempotency key looks first
    post["retry"] = failed_before(rows, key, post["hash"])
    rec = {"network": key, "post": f"#{row['id']}", "hash": post["hash"], "at": iso(now), "by": by}
    out = {"network": key, "hash": post["hash"]}
    try:
        sent = prov.send(net, env, post, dry)
        if dry:
            rec["status"] = out["status"] = "dry"
            out["request"] = sent["request"]
        else:
            rec.update(status="posted", url=sent["url"], id=sent["id"])
            out.update(status="posted", url=sent["url"], id=sent["id"])
    except RuntimeError as e:
        rec.update(status="failed", error=str(e))
        out.update(status="failed", error=str(e))
    title = f"{prov.NAME} · {rec['status']}: " + (row.get("title") or "").replace("Share · ", "", 1)
    try:
        out["record"] = journal.write(title[:200], record_text(rec))
    except Fail as e:
        # posted and not recorded: the network's own key still holds a
        # retry inside the hour; the answer says so where the tap was
        out["warning"] = str(e)
    log_run({"at": rec["at"], "network": key, "status": out["status"], "post": row["id"],
             "record": out.get("record")})
    return out


def read_card(link):
    """The link's og: card and its picture's bytes (public links only, the
    picture at most bluesky.BLOB_MAX), for a network that draws the card."""
    c = cmd_card(argparse.Namespace(url=link))["card"]
    c["thumb"] = None
    img = c.get("image") or ""
    p = urllib.parse.urlparse(img)
    if p.scheme in ("http", "https") and p.hostname and public_host(p.hostname):
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(urllib.request.Request(img, headers={"User-Agent": UA}), timeout=8) as r:
                b = r.read(bluesky.BLOB_MAX + 1)
                if r.status == 200 and len(b) <= bluesky.BLOB_MAX:
                    c["thumb"] = b
        except (urllib.error.URLError, OSError):
            pass
    return c


def cmd_post(a, env=None, journal=None, net=None, now=None, cards=read_card):
    env = env if env is not None else settings()
    nets = [n.strip() for n in (a.networks or "").split(",") if n.strip()]
    if not nets or not all(NETWORK_RE.match(n) for n in nets):
        raise Fail("--networks: one or more network names, comma-separated", 2)
    journal = journal or Journal(env)
    net = net or Net()
    now = now or now_utc()
    row = journal.get(a.id)
    j = drafts(row)
    dry = is_dry(env, a.dry_run)
    rows = journal.records()
    results = []
    for key in dict.fromkeys(nets):
        r = post_one(key, j, row, journal, net, env, dry, a.by, rows, now, cards)
        results.append(r)
    return {"results": results, "dry": dry, "dry_by": "asked" if a.dry_run else "switch" if dry else ""}


# ---- check -------------------------------------------------------------------

def cmd_check(_a, env=None, net=None):
    env = env if env is not None else settings()
    net = net or Net()
    out = {}
    for key, prov in PROVIDERS.items():
        out[key] = prov.check(net, env)
    return {"networks": out, "dry": is_dry(env, False)}


# ---- card --------------------------------------------------------------------

def public_host(host):
    """True when every address `host` resolves to is a public one: the card
    is fetched by the server's box, which must not be pointed at itself,
    the tailnet or the LAN."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    for fam, *_rest, addr in infos:
        ip = ipaddress.ip_address(addr[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_page(url, timeout=8):
    """(status, text, location): one GET, redirects handed back to the caller."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read(CARD_MAX).decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        return e.code, "", e.headers.get("Location", "") if e.code in (301, 302, 303, 307, 308) else ""
    except (urllib.error.URLError, OSError) as e:
        raise Fail(f"no answer from the link: {getattr(e, 'reason', e)}", 1)


def _meta(html_text, names):
    for n in names:
        for m in re.finditer(r"<meta\b[^>]*>", html_text, re.I):
            tag = m.group(0)
            p = re.search(r"""(?:property|name)\s*=\s*["']([^"']+)["']""", tag, re.I)
            c = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
            if p and c and p.group(1).lower() == n:
                import html
                return html.unescape(c.group(1)).strip()
    return ""


def parse_card(url, html_text):
    import html
    title = _meta(html_text, ("og:title", "twitter:title"))
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    img = _meta(html_text, ("og:image", "twitter:image"))
    if img:
        img = urllib.parse.urljoin(url, img)
        if not img.startswith(("http://", "https://")):
            img = ""
    return {"url": url, "title": title[:300], "description": _meta(html_text, ("og:description", "description",
                                                                            "twitter:description"))[:600],
            "image": img, "site": _meta(html_text, ("og:site_name",))[:100] or urllib.parse.urlparse(url).hostname or ""}


def cmd_card(a, fetch=None, public=None):
    fetch, public = fetch or _fetch_page, public or public_host
    url = a.url
    for _hop in range(4):
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise Fail("a card is read from an http(s) link only", 2)
        if not public(p.hostname):
            raise Fail("that link is not on the public internet", 2)
        st, text, loc = fetch(url)
        if loc:
            url = urllib.parse.urljoin(url, loc)
            continue
        if st != 200:
            raise Fail(f"the link answered {st}", 1)
        return {"card": parse_card(url, text)}
    raise Fail("the link redirects too often", 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="publish.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("post", help="post a social_post's text to networks")
    p.add_argument("id", type=int)
    p.add_argument("--networks", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--by", choices=("tap", "schedule"), default="tap")
    c = sub.add_parser("check", help="each network's credential, by a free read")
    c.add_argument("--json", action="store_true")
    k = sub.add_parser("card", help="a link's og: card")
    k.add_argument("url")
    a = ap.parse_args(argv)
    try:
        out = {"post": cmd_post, "check": cmd_check, "card": cmd_card}[a.cmd](a)
    except Fail as e:
        print(json.dumps({"error": str(e)}))
        return e.code
    if a.cmd == "check" and not a.json:
        for key, r in out["networks"].items():
            print(f"{PROVIDERS[key].NAME}: ok, {r['account']}" if r["ok"] else r["error"])
        print("dry run: " + ("on (LCARS_PUB_DRY is not 0)" if out["dry"] else "off, posts are sent"))
        return 0
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
