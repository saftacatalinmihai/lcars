#!/usr/bin/env python3
"""Structural sanity checks for the single-file LCARS UI."""
import re, sys
from html.parser import HTMLParser

path = sys.argv[1] if len(sys.argv) > 1 else "index.html"
src = open(path, encoding="utf-8").read()
problems = []

# ---------- pull out the blocks ----------
style = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
script = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))
markup = re.sub(r"<style>.*?</style>", "", src, flags=re.S)
markup = re.sub(r"<script>.*?</script>", "", markup, flags=re.S)

# ---------- JS: strip literals, then balance ----------
PREV_REGEX_OK = set("(,=:[!&|?{};+-*%~^<>") | {"return","typeof","instanceof","in","of","new",
                                               "delete","void","case","do","else","yield","await"}
def strip_js(s):
    out, i, n = [], 0, len(s)
    prev_sig = ""      # last significant token
    while i < n:
        c = s[i]
        if c == "/" and i + 1 < n and s[i+1] == "/":
            j = s.find("\n", i); i = n if j < 0 else j; continue
        if c == "/" and i + 1 < n and s[i+1] == "*":
            j = s.find("*/", i + 2); i = n if j < 0 else j + 2; out.append(" "); continue
        if c in "\"'":
            q, j = c, i + 1
            while j < n:
                if s[j] == "\\": j += 2; continue
                if s[j] == q: break
                j += 1
            if j >= n: problems.append(f"JS: unterminated {q} string near offset {i}")
            i = j + 1; out.append('""'); prev_sig = '""'; continue
        if c == "`":
            j, depth = i + 1, 0
            while j < n:
                if s[j] == "\\": j += 2; continue
                if s[j] == "$" and j + 1 < n and s[j+1] == "{":
                    # recurse through the interpolation so its braces still count
                    k, d = j + 2, 1
                    while k < n and d:
                        if s[k] == "{": d += 1
                        elif s[k] == "}": d -= 1
                        elif s[k] in "\"'`":
                            q2 = s[k]; k += 1
                            while k < n and s[k] != q2:
                                if s[k] == "\\": k += 1
                                k += 1
                        k += 1
                    out.append("(" + strip_js(s[j+2:k-1]) + ")")
                    j = k; continue
                if s[j] == "`": break
                j += 1
            if j >= n: problems.append(f"JS: unterminated template literal near offset {i}")
            i = j + 1; out.append('""'); prev_sig = '""'; continue
        if c == "/":
            # regex literal only where a value may start.  Only the last token
            # before the slash decides that, so walk back just far enough to
            # hold one -- joining the whole output here made the scan quadratic.
            buf, got = [], 0
            for k in range(len(out) - 1, -1, -1):
                buf.append(out[k])
                got += len(out[k].strip())
                if got >= 24: break
            tail = "".join(reversed(buf)).rstrip()
            m = re.search(r"[A-Za-z_$]+$", tail)
            last = m.group(0) if m else (tail[-1] if tail else "(")
            if last in PREV_REGEX_OK or (tail and tail[-1] in "(,=:[!&|?{};+-*%~^<>"):
                j, inclass = i + 1, False
                while j < n:
                    if s[j] == "\\": j += 2; continue
                    if s[j] == "[": inclass = True
                    elif s[j] == "]": inclass = False
                    elif s[j] == "/" and not inclass: break
                    elif s[j] == "\n": break
                    j += 1
                if j < n and s[j] == "/":
                    i = j + 1
                    while i < n and s[i].isalpha(): i += 1
                    out.append("R"); continue
        out.append(c); i += 1
    return "".join(out)

bare = strip_js(script)
pairs = {")": "(", "]": "[", "}": "{"}
stack, line = [], 1
for idx, ch in enumerate(bare):
    if ch == "\n": line += 1
    elif ch in "([{": stack.append((ch, line))
    elif ch in ")]}":
        if not stack or stack[-1][0] != pairs[ch]:
            problems.append(f"JS: unbalanced '{ch}' at script line ~{line}")
            break
        stack.pop()
if stack:
    problems.append(f"JS: {len(stack)} unclosed {[f'{c} @~{l}' for c, l in stack[-5:]]}")

# ---------- CSS balance ----------
css = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
if css.count("{") != css.count("}"):
    problems.append(f"CSS: {css.count('{')} '{{' vs {css.count('}')} '}}'")

# ---------- ids: declared vs referenced ----------
declared = set(re.findall(r'\bid="([^"]+)"', src))
declared |= set(re.findall(r"\.id\s*=\s*[\"']([^\"']+)[\"']", script))
referenced = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', script))
referenced |= set(re.findall(r'getElementById\("([^"]+)"\)', script))
missing = sorted(referenced - declared)
if missing:
    problems.append("JS references ids never declared: " + ", ".join(missing))

# ---------- css id selectors that exist nowhere ----------
css_ids = set(re.findall(r"#([A-Za-z][A-Za-z0-9_-]*)", css))
orphan = sorted(i for i in css_ids - declared if not re.fullmatch(r"[0-9a-fA-F]{3,8}", i))
if orphan:
    problems.append("CSS selects ids never declared: " + ", ".join(orphan))

# ---------- markup balance ----------
VOID = {"area","base","br","col","embed","hr","img","input","link","meta","source","track","wbr"}
class P(HTMLParser):
    def __init__(self): super().__init__(); self.stack = []
    def handle_starttag(self, tag, attrs):
        if tag not in VOID: self.stack.append((tag, self.getpos()[0]))
    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack: problems.append(f"HTML: stray </{tag}>"); return
        if self.stack[-1][0] != tag:
            problems.append(f"HTML: </{tag}> closes <{self.stack[-1][0]}> opened line {self.stack[-1][1]}")
            return
        self.stack.pop()
p = P(); p.feed(markup)
if p.stack: problems.append("HTML: unclosed " + str(p.stack[-5:]))

# ---------- duplicate ids ----------
# only static markup: #dlg.innerHTML is rewritten per dialog, so the same id in
# two different dialog templates is one id at a time, not a duplicate
all_ids = re.findall(r'\bid="([^"]+)"', markup)
dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
if dupes: problems.append("duplicate id attributes: " + ", ".join(dupes))

# ---------- no contact words on a text field (iOS AutoFill Contact) ----------
# iOS Safari ignores autocomplete="off" and classifies the page's fields
# itself. The classifier is Safari's own, not WebKit's open source; what WebKit
# hands it for the focused field is its <label>'s text, title, aria-label,
# placeholder, value and autocomplete token (FocusedElementInformation, filled
# in WebPageIOS.mm's focusedElementInformation), and its injected bundle reads
# the rest of the DOM. One field it takes for a contact's (a job "title", a
# "name", a phone's "number" or "call", a message's "to <someone>") makes the
# formless page a contact form, and the keyboard then offers AutoFill Contact
# (the captain's own card) instead of word prediction on every text field, the
# entry's body included (0.241.1, 0.256.3, again in 0.311: Rooms' composer).
# A dialog's markup stays in the page after it closes (closeOv), so a field
# anywhere in the file counts, open or not. So, for every <input> and
# <textarea> the file can render (the script's templates included; a ${...}
# counts by the string literals in it), and every one made by createElement:
#  1. no contact word in its id, name, placeholder, aria-label, title or the
#     label or text before it - the whole class: a person's names and titles,
#     an organisation, the ways to reach one (mail, phone, number, call), an
#     address, a birthday, an account or a recipient;
#  2. no placeholder, aria-label or title addressing someone: "to ${who}",
#     "Reply to " + who, a placeholder set in the script to "to " + a name -
#     a message box with its recipient is a contact field to Safari;
#  3. the opt-out Safari is known to honour: a name starting "search" with no
#     dash in it (a dashed name is a phone field to Safari) on every text
#     field. There is no <form>, so the name is sent nowhere.
# A login's fields are the exception, and say so: autocomplete="username" or
# a password token.
# docs/design/editor.md, "AutoFill Contact", has the sources.
CONTACT = ("name nick first last surname given family middle honorific title job "
           "company organisation organization org department email mail phone tel "
           "telephone mobile cell fax number call caller sms address street city town zip postal postcode "
           "province state country region birthday bday sex gender contact location "
           "user username login account member person people recipient sender addressee cc bcc").split()
# inside an id or a name words run together (cpname): the unmistakable ones
# are looked for anywhere in it
CONTACT_IN = ("name title email phone address street city country company organi "
              "postal zip surname birth contact call number user login account person recipient").split()
NOT_TEXT = {"checkbox", "radio", "file", "range", "hidden", "button", "color", "submit", "reset", "image"}
# what the name rule (3) covers: the keyboard's text fields, not the pickers
NAMED = {"", "text", "search", "url"}
CREDENTIAL = {"username", "current-password", "new-password", "one-time-code"}
# a literal that ends addressing someone, the name to follow: "to " + who, `to ${who}`
ADDRESSED = re.compile(r"\bto\s*(?:\$\{|\"\s*\+|'\s*\+)", re.I)

def lits(v):
    return re.sub(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
                  lambda m: " ".join(re.findall(r'"([^"]*)"', m.group(1))), v)

def words(v):
    v = re.sub(r"([a-z])([A-Z])", r"\1 \2", lits(v)).lower()
    return re.findall(r"[a-z]+", v)

def contact_hits(v, joined=False):
    ws = words(v)
    hit = {w for w in CONTACT for x in ws if x == w or (len(w) > 3 and x.startswith(w))}
    if joined:
        hit |= {w for w in CONTACT_IN for x in ws if w in x}
    return sorted(hit)

def attr(tag, a):
    m = re.search(r'\s' + a + r'\s*=\s*"((?:[^"$]|\$\{[^}]*\})*)"', tag)
    return m.group(1) if m else ""

def search_name(v):
    return bool(re.fullmatch(r"search[A-Za-z0-9_]*(?:\$\{[^}]*\}[A-Za-z0-9_]*)*", v))

# a field written in a comment (a "<input capture>" in prose) is no field
quiet = [m.span() for m in re.finditer(r"<!--.*?-->|/\*.*?\*/|^\s*//[^\n]*", src, re.S | re.M)]
def in_comment(at):
    return any(a <= at < b for a, b in quiet)

label_for = {m.group(1): m.group(2) for m in
             re.finditer(r'<label\b[^>]*\bfor="([^"]+)"[^>]*>(.*?)</label>', src, re.S)}
fields = 0
for m in re.finditer(r"<(input|textarea)\b(?:[^>\"]|\"(?:[^\"$]|\$\{[^}]*\})*\")*>", src):
    tag, at = m.group(0), src.count("\n", 0, m.start()) + 1
    kind = attr(tag, "type").lower() if tag.startswith("<input") else ""
    if kind in NOT_TEXT or in_comment(m.start()):
        continue
    fields += 1
    # a login's own fields say so (Config's basic auth): WebKit takes them for
    # credentials (AutofillElements), the Passwords key, not a contact
    if attr(tag, "autocomplete") in CREDENTIAL:
        continue
    fid = attr(tag, "id")
    # the text a person reads beside it: its <label for>, the label it sits
    # in, or the text just before it, back to the last tag that is no label
    before = src[max(0, m.start() - 300):m.start()]
    before = re.sub(r"<!--.*?-->|^(?:(?!<!--).)*?-->", " ", before, flags=re.S)
    # back to the last other field, the end of a block or of a template (a `)
    before = re.split(r"<(?:input|textarea|button|select)\b[^>]*>|</(?:button|select|textarea|h2|div|p|section|summary)>|`|;\n",
                      before)[-1]
    near = re.sub(r"<[^>]*>", " ", re.sub(r"\$\{[^}]*\}", lambda x: lits(x.group(0)), before))[-120:]
    seen = {"id": contact_hits(fid, True), "name": contact_hits(attr(tag, "name"), True),
            "placeholder": contact_hits(attr(tag, "placeholder")),
            "aria-label": contact_hits(attr(tag, "aria-label")),
            "title": contact_hits(attr(tag, "title")),
            "label": contact_hits(label_for.get(fid, "") + " " + near)}
    bad = [f"{k} ({', '.join(v)})" for k, v in seen.items() if v]
    bad += [f"{k} addresses someone" for k in ("placeholder", "aria-label", "title")
            if ADDRESSED.search(attr(tag, k))]
    if kind in NAMED and not search_name(attr(tag, "name")):
        bad.append(f'no name="search…" (got {attr(tag, "name") or "none"!r})')
    if bad:
        problems.append(f"line {at}: a text field iOS may read as a contact form: "
                        + "; ".join(bad) + " - " + " ".join(tag.split())[:120])
# a field made by createElement: what its next lines give it
for m in re.finditer(r'(\w+) = document\.createElement\("(input|textarea)"\);', src):
    v, at = m.group(1), src.count("\n", 0, m.start()) + 1
    if in_comment(m.start()):
        continue
    body = "\n".join(src[m.end():].split("\n")[1:16])
    said = re.findall(r'\b' + v + r'\.(?:id|name|placeholder|title)\s*=\s*"([^"]*)"', body)
    said += re.findall(r'\b' + v + r'\.setAttribute\("(?:id|name|placeholder|aria-label|title)",\s*"([^"]*)"', body)
    hits = sorted({w for x in said for w in contact_hits(x, True)})
    named = re.search(r'\b' + v + r'\.name\s*=\s*"([^"]*)"', body)
    kind = re.search(r'\b' + v + r'\.type\s*=\s*"([^"]*)"', body)
    fields += 1
    bad = [f"a contact word ({', '.join(hits)})"] if hits else []
    if (kind.group(1) if kind else "") in NAMED and not (named and search_name(named.group(1))):
        bad.append('no name="search…"')
    if bad:
        problems.append(f"line {at}: a field made in the script iOS may read as a contact form: " + "; ".join(bad))
# a placeholder the script sets later (a box's "to <whoever>"): every one in
# the file, whichever field it lands on - fields are all a placeholder is for
for m in re.finditer(r'\.placeholder\s*=\s*([^;\n]+)|setAttribute\("placeholder",\s*([^;\n]+)', script):
    v = m.group(1) or m.group(2)
    at = src.count("\n", 0, src.find(m.group(0))) + 1
    hits = sorted({w for x in re.findall(r'"([^"]*)"', v) for w in contact_hits(x)})
    bad = ([f"a contact word ({', '.join(hits)})"] if hits else []) + (["addresses someone"] if ADDRESSED.search(v) else [])
    if bad:
        problems.append(f"line {at}: a placeholder set in the script iOS may read as a contact field: "
                        + "; ".join(bad) + " - " + m.group(0).strip()[:100])

# ---------- the page's connect-src names every outside service it calls ----------
# (the "csp" block in the head): a fetch, a WebSocket or a tile kept offline
# to a host not in CSP_CONNECT is refused by the browser, so a new service
# must be named there. Hosts only linked to (an attribution, a placeholder)
# are listed here as such.
LINK_ONLY = {"fonts.googleapis.com", "fonts.gstatic.com", "www.rainviewer.com", "www.openstreetmap.org",
             "www.google.com", "waymarkedtrails.org", "opentopomap.org", "mapy.com", "your-journal-server",
             "lcars.offline",
             # the Share sheet's composers (social-publish.md 1.11): tabs opened by a tap, never fetched
             "news.ycombinator.com", "www.reddit.com", "x.com", "bsky.app", "www.linkedin.com", "www.threads.net"}
csp = re.search(r"const CSP_CONNECT = \[(.*?)\];", src, re.S)
if path.endswith("index.html"):
    if not csp:
        problems.append("the csp block's CSP_CONNECT list is missing from the head")
    else:
        allowed = set(re.findall(r'"(?:https|wss)://([^"/]+)"', csp.group(1)))
        used = set(re.findall(r"(?:https|wss)://([a-zA-Z0-9.-]*[a-zA-Z])", src))
        for h in sorted(used - allowed - LINK_ONLY):
            problems.append(f"{h}: called by the page but not in the csp block's CSP_CONNECT "
                            "(add it there, or to check.py's LINK_ONLY if it is only a link)")

if problems:
    print("FAIL")
    for x in problems: print("  •", x)
    sys.exit(1)
print(f"PASS  ({len(script.splitlines())} js lines, {len(css.splitlines())} css lines, "
      f"{len(declared)} ids, {len(referenced)} referenced, {fields} text fields)")
