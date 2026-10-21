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
# iOS Safari ignores autocomplete="off": its own form classifier (Safari's,
# not WebKit's open source - WebKit only carries the autocomplete tokens and
# the AutoFill button Safari asks for, _WKFormInputSession's
# accessoryViewCustomButtonTitle) reads a field's id, name, placeholder,
# aria-label and the label or text before it, and one field it takes for a
# contact's (a job "title", a "name") makes the formless page a contact form:
# the keyboard then offers AutoFill Contact, the captain's own name, instead of
# word prediction on every text field, the entry's body included (0.241.1,
# 0.256.1). So no field the page can render may carry one of these words in
# any of them. Every <input> and <textarea> in the file is read, the script's
# templates included; a ${...} counts by the string literals in it.
CONTACT = ("name nick first last surname given family middle honorific title job "
           "company organisation organization org department email mail phone tel "
           "telephone mobile cell fax address street city town zip postal postcode "
           "province state country region birthday bday sex gender contact location").split()
# inside an id or a name words run together (cpname): the unmistakable ones
# are looked for anywhere in it
CONTACT_IN = ("name title email phone address street city country company organi "
              "postal zip surname birth contact").split()
NOT_TEXT = {"checkbox", "radio", "file", "range", "hidden", "button", "color", "submit", "reset", "image"}

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

label_for = {m.group(1): m.group(2) for m in
             re.finditer(r'<label\b[^>]*\bfor="([^"]+)"[^>]*>(.*?)</label>', src, re.S)}
fields = 0
for m in re.finditer(r"<(input|textarea)\b(?:[^>\"]|\"(?:[^\"$]|\$\{[^}]*\})*\")*>", src):
    tag, at = m.group(0), src.count("\n", 0, m.start()) + 1
    if re.match(r"<input\b", tag) and attr(tag, "type").lower() in NOT_TEXT:
        continue
    fields += 1
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
            "label": contact_hits(label_for.get(fid, "") + " " + near)}
    bad = [f"{k} ({', '.join(v)})" for k, v in seen.items() if v]
    if bad:
        problems.append(f"line {at}: a text field with a contact word, which iOS reads as a contact form: "
                        + "; ".join(bad) + " - " + " ".join(tag.split())[:120])
# a field made by createElement: what its next lines give it
for m in re.finditer(r'(\w+) = document\.createElement\("(?:input|textarea)"\);', src):
    v, at = m.group(1), src.count("\n", 0, m.start()) + 1
    body = "\n".join(src[m.end():].split("\n")[1:16])
    said = re.findall(r'\b' + v + r'\.(?:id|name|placeholder)\s*=\s*"([^"]*)"', body)
    said += re.findall(r'\b' + v + r'\.setAttribute\("(?:id|name|placeholder|aria-label)",\s*"([^"]*)"', body)
    hits = sorted({w for x in said for w in contact_hits(x, True)})
    fields += 1
    if hits:
        problems.append(f"line {at}: a field made in the script with a contact word ({', '.join(hits)}), "
                        "which iOS reads as a contact form")

# ---------- the page's connect-src names every outside service it calls ----------
# (the "csp" block in the head): a fetch, a WebSocket or a tile kept offline
# to a host not in CSP_CONNECT is refused by the browser, so a new service
# must be named there. Hosts only linked to (an attribution, a placeholder)
# are listed here as such.
LINK_ONLY = {"fonts.googleapis.com", "fonts.gstatic.com", "www.rainviewer.com", "www.openstreetmap.org",
             "www.google.com", "waymarkedtrails.org", "opentopomap.org", "mapy.com", "your-journal-server",
             "lcars.offline"}
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
