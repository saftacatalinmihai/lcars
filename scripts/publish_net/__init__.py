"""The publisher's networks (docs/design/social-publish.md 3.3): one module
per network in the provider shape, and what they share - the limits table
(limits.json, which the page's SOC_NETS is held equal to) and counting as
each network counts, the same rules as the page's socCount.

A provider module has:

    KEY, NAME, VAR               "mastodon", "Mastodon", its ~/.env variable
    configured(env) -> str|None  None, or what is missing (the card's note)
    validate(post, limit) -> [errors]   the preview's checks, the page's too
    limit(net, env) -> int       the network's own limit (an instance's)
    send(net, env, post, dry) -> {"url", "id"} | {"request"} (dry)
    check(net, env) -> {"ok", "account"|"error"}   a free read, never a post
    hand_url(env, post) -> str   the network's composer, filled in

`post` is resolved before a provider sees it: {"text", "image": bytes or
None, "image_name", "alt", "hash"}. `net` is publish.py's Net, which
records every request; nothing here opens a socket of its own.
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "limits.json"), encoding="utf-8") as _f:
    LIMITS = json.load(_f)

LINK_RE = re.compile(r"https?://[^\s<>\"]+")


def _ext(c):
    """A code point that joins the grapheme before it (the page's list)."""
    return (0x300 <= c <= 0x36f or 0x1ab0 <= c <= 0x1aff or 0x1dc0 <= c <= 0x1dff or 0x20d0 <= c <= 0x20ff
            or 0xfe00 <= c <= 0xfe0f or 0xfe20 <= c <= 0xfe2f or 0x1f3fb <= c <= 0x1f3ff
            or 0xe0020 <= c <= 0xe007f or 0xe0100 <= c <= 0xe01ef or c == 0x200d)


def clusters(s):
    """Graphemes as the page's fallback joins them (socClusters): combining
    marks, variation selectors, skin tones, tags, ZWJ sequences, a flag's
    two regional indicators, CR LF. Python has no Intl.Segmenter; the cases
    in limits.json hold the two equal on what a post meets."""
    out, prev, ri = [], 0, False
    for ch in str(s or ""):
        c = ord(ch)
        is_ri = 0x1f1e6 <= c <= 0x1f1ff
        join = bool(out) and (_ext(c) or prev == 0x200d or (prev == 13 and c == 10) or (is_ri and ri))
        if join:
            out[-1] += ch
        else:
            out.append(ch)
        ri = is_ri and not (join and ri)
        prev = c
    return out


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _light(c):
    return c <= 0x10ff or 0x2000 <= c <= 0x200d or 0x2010 <= c <= 0x201f or 0x2032 <= c <= 0x2037


def weighted(s):
    import unicodedata
    n = 0
    for g in clusters(unicodedata.normalize("NFC", str(s or ""))):
        if EMOJI_RE.search(g):
            n += 2
            continue
        n += sum(1 if _light(ord(ch)) else 2 for ch in g)
    return n


def count(key, s):
    """A text's length on network `key`, every link as the table says."""
    n = LIMITS["networks"][key]
    s, links = str(s or ""), 0
    if n["link"]:
        s, links = LINK_RE.subn("", s)
    base = len(clusters(s)) if n["counts"] == "graphemes" else weighted(s) if n["counts"] == "weighted" else len(s)
    return base + links * (n["link"] or 0)


def body(text, link):
    """What a text network is sent: the text, the link after a blank line
    unless the text has it already (the page's socBody)."""
    t, l = str(text or "").strip(), str(link or "").strip()
    if not l or l in t:
        return t
    return (t + "\n\n" if t else "") + l
