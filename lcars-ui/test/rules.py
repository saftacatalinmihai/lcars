#!/usr/bin/env python3
"""The rules in docs/design/ui-rules.md that the page's source can be held to.

Every rule in that file names its check ("Check:" under its heading), and
the analysis of 0.321.0 is why: the rules a test held stayed kept, the ones
without leaked. This file holds the ones a static read of index.html can
see (the stylesheet, the markup, the calls); a rendered page's (sizes,
computed faces, the 320px reflow) are targets.py's, the behaviour suite's
and keyboard.py's. Each line is tagged with its rule's slug, `[hover]`, and
the slug is the one ui-rules.md's Check line names (`rule:hover` in the
other files), so a reader goes from a failure to its rule and back.

A check that fails on today's code for a rule a later slice fixes is kept,
marked with that slice (`until=`): it prints `xfail` and does not fail the
run. When the slice makes it pass it prints XPASS and fails, so the slice
removes the mark and the check holds from then on. Nothing is deleted to
make the run green.

A census (the distinct literal colours, radii, paddings and weights, and
the animated rules) is pinned at today's count: a change may lower it (and
then lowers the pin), never raise it without naming the value in ui-rules.md
and moving the pin there with a reason."""
import html, os, re, sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(D)
src = open(os.path.join(D, "index.html"), encoding="utf-8").read()
rules_md = open(os.path.join(ROOT, "docs/design/ui-rules.md"), encoding="utf-8").read()
STYLE = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
SCRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))
BODY = src[src.index("</head>"):]

ok, bad, xf = [], [], []
SLUGS = set()


def chk(slug, cond, msg, until=None):
    """One check of rule `slug`. `until` names the slice that will make it
    pass: failing then is expected (xfail), passing is XPASS and fails."""
    SLUGS.add(slug)
    line = f"[{slug}] {msg}"
    if until:
        if cond:
            bad.append(line + f" — XPASS: it holds now; remove until={until!r}")
        else:
            xf.append(line + f" (expected to fail until {until})")
    else:
        (ok if cond else bad).append(line)


# ---------------------------------------------------------------- the CSS
def css_rules(css):
    """Flatten the stylesheet into (at-rules around it, selector, body)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, stack, i, n = [], [], 0, len(css)
    buf = ""
    while i < n:
        c = css[i]
        if c == "{":
            head = buf.strip()
            buf = ""
            if head.startswith("@"):
                stack.append(head)
                i += 1
                continue
            j = css.index("}", i)
            out.append((tuple(stack), head, css[i + 1:j]))
            i = j + 1
            continue
        if c == "}":
            if stack:
                stack.pop()
            buf = ""
            i += 1
            continue
        buf += c
        i += 1
    return out


RULES = css_rules(STYLE)
NONROOT = [(at, sel, body) for at, sel, body in RULES if sel.strip() != ":root"]


def decls(body):
    for d in body.split(";"):
        if ":" in d:
            k, v = d.split(":", 1)
            yield k.strip().lower(), v.strip()


def distinct(prop):
    vals = {}
    for at, sel, body in NONROOT:
        for k, v in decls(body):
            if k == prop:
                vals.setdefault(re.sub(r"\s*!important$", "", v), sel)
    return vals


def sels(sel):
    """The selectors of a rule's head, each whole and with one space."""
    return {" ".join(x.split()) for x in sel.split(",")}


def short(sel):
    return " ".join(sel.split())[:60]


# ---------------------------------------------------------------- [type]
# A size is a token, a relative size of the text around it, or a named
# display numeral (a clock, a big count): never a new literal in passing.
SIZES_NAMED = {
    ".wface": "the watch's face, a clock read across a room",
    ".scard b": "Statistics' big counts",
    ".dtread": "the day timer's read-out",
    ".dtread b": "its seconds",
    "#amb .ambt": "ambient mode's clock (clamp, the screen's width)",
}
# the ambient clock's three sizes, by value: a new clamp() is a new size
CLAMPS = {"clamp(54px,13vw,148px)", "clamp(15px,2.6vw,27px)", "clamp(17px,2.4vw,29px)"}
size_bad = []
for at, sel, body in NONROOT:
    for k, v in decls(body):
        if k != "font-size":
            continue
        v = re.sub(r"\s*!important$", "", v)
        if v.startswith("var(--fs-") or re.fullmatch(r"\.?\d*\.?\d+em|inherit|100%", v):
            continue
        if sels(sel) & set(SIZES_NAMED) or v in CLAMPS:
            continue
        size_bad.append(f"{short(sel)} {{font-size:{v}}}")
chk("type", not size_bad,
    "every font-size is a --fs- token, an em of its text, or a named display numeral"
    + (": " + "; ".join(size_bad) if size_bad else ""))
fs_inline = re.findall(r"font-size:\s*\d+px", BODY.split("<script>")[0])
chk("type", not fs_inline, f"no literal font-size in the markup's style attributes ({len(fs_inline)})")

# ---------------------------------------------------------------- [faces]
# mono is for code and raw values only (a path, a regex, a tool's call, the
# raw JSON); each rule that sets it is named
# raw JSON); each rule that sets it is named whole, with what it holds
MONO_OK = {
    ".num": "a number set in a table's column",
    ".featoff code": "a missing feature's variable or path",
    ".edv": "Details' raw values",
    ".md pre.mdcode": "a code block",
    ".md code": "a code span",
    ".md .mdprop": "a property line (key:: value), as written",
    "#cdRaw": "the raw JSON editor",
    ".kbd kbd": "a key in the keyboard sheet",
    ".pkr kbd": "a picker row's key",
    ".xphd .xq": "the statistics query, typed syntax",
    ".ctool": "a tool's call in a chat",
    ".cerr": "an error's raw text",
    ".chqcard pre": "a quoted block in a question card",
    ".chtools": "a chat's tool calls, summed",
    ".rppre": "a text or CSV report, as written",
}
mono = [sel for at, sel, body in NONROOT if "var(--mono)" in body]
mono_new = [s for s in mono if not sels(s) <= set(MONO_OK)]
chk("faces", not mono_new,
    f"--mono only on the code and raw-value rules named here ({len(mono)} rules)"
    + (": new " + ", ".join(map(short, mono_new)) if mono_new else ""))
sans = re.search(r"--sans:[^;]*;", STYLE)
chk("faces", sans and "Antonio" not in sans.group(0) and "mono" not in sans.group(0).lower(),
    "--sans is a reading face, neither Antonio nor a mono")

# ---------------------------------------------------------------- [icons]
# Unicode glyphs standing in for icons; the marks inside a line of text
# (▾ ✓ ×) are type and allowed. Comments are not the page. A glyph is
# found however it is written: as itself, as a script's \u2197 or
# \u{2197}, or as markup's &#8599; (slice E found ten the raw scan missed).
GLYPHS = "▤◉◆▦☑✦⚒⌕↗«»▸◂▶◀☰⚙✎✚⊕⊗"
code = re.sub(r"/\*.*?\*/", "", SCRIPT, flags=re.S)
code = re.sub(r"(?m)^\s*//.*$", "", code)
code = re.sub(r"\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1) or m.group(2), 16)), code)
code = html.unescape(code)
markup = re.sub(r"<!--.*?-->", "", BODY.split("<script>")[0], flags=re.S)
found = sorted(set(c for c in code + html.unescape(markup) if c in GLYPHS))
chk("icons", not found, "no Unicode glyph stands in for a drawn icon"
    + (": " + " ".join(found) if found else ""), until="a slice not yet planned (the glyphs below)")
# Until then no new one: the glyphs left today are pinned, so a new one fails
# now rather than hiding inside the xfail (the critic's finding on slice R).
# Slice E drew ↗ ⌕ ▸ (i-open, i-find, i-next turned); these were hidden
# from the raw scan by their escapes, and are left for a slice of their own:
# the chats' ⚒ ◆ ⚙ ✎, the course map's ☰ ✎ ◀ ▶, a task's ☑, the rails' « ».
GLYPHS_LEFT = set("«»▶◀◆☑☰⚒⚙✎")
chk("icons", set(found) <= GLYPHS_LEFT, f"no glyph beyond today's {''.join(sorted(GLYPHS_LEFT))}"
    + (": new " + " ".join(sorted(set(found) - GLYPHS_LEFT)) if set(found) - GLYPHS_LEFT else ""))
chk("icons", '<symbol id="i-' in src and 'const ic = (name, cls) =>' in SCRIPT,
    "the drawn set is the <symbol id=\"i-…\"> sprite, written by ic()")

# ---------------------------------------------------------------- [colours]
# outside :root a colour is a var(): the tokens are where contrast is checked
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
lit_colours = set()
for at, sel, body in NONROOT:
    for k, v in decls(body):
        if k.startswith("--"):
            continue
        for h in HEX.findall(v):
            lit_colours.add(h.lower())
        for f in re.findall(r"rgba?\([^)]*\)", v):
            lit_colours.add(re.sub(r"\s", "", f))
chk("colours", not lit_colours,
    f"no colour literal outside :root ({len(lit_colours)} distinct)"
    + (": " + " ".join(sorted(lit_colours)[:8]) if lit_colours else ""))

# ---------------------------------------------------------------- [radii]
# a radius is a token (--r2 ... --r28 on the 2px steps, --rpill), 0 or 50%:
# the ladder is :root's, so an odd pixel is a radius nobody chose
rad_bad = sorted(set(f"{short(sel)} {{{k}:{v}}}" for at, sel, body in NONROOT for k, v in decls(body)
                     if k.endswith("radius") and re.search(r"(?<![\w-])\d*\.?\d+(px|em|rem)", v)))
chk("radii", not rad_bad, "every border-radius outside :root is a --r token, 0 or 50%"
    + (": " + "; ".join(rad_bad[:6]) if rad_bad else ""))

# ---------------------------------------------------------------- [census]
# border-radius counts its distinct values, tokens and all: a shape (a pill's
# round right end, "0 var(--r10) var(--r10) 0") is a value of its own
RADII_PIN = 46
# the distinct literals, pinned (lower a pin when a change lowers its count)
CENSUS = {"colour": 0, "border-radius": RADII_PIN, "padding": 157, "font-weight": 4}
counts = {"colour": len(lit_colours)}
for p in ("border-radius", "padding", "font-weight"):
    counts[p] = len(distinct(p))
for k, pin in CENSUS.items():
    n = counts[k]
    chk("census", n <= pin, f"{k}: {n} distinct literal values, pinned at {pin}"
        + (" — lower the pin in rules.py to %d" % n if n < pin else ""))

# ---------------------------------------------------------------- [hover]
# a :hover that paints sticks after a tap on iOS: only under (hover:hover)
naked = [short(sel) for at, sel, body in RULES
         if ":hover" in sel and not any("hover:hover" in a.replace(" ", "") for a in at)]
hov = len([1 for at, sel, body in RULES if ":hover" in sel])
chk("hover", not naked,
    f"every :hover rule is inside @media (hover:hover) ({len(naked)} of {hov} are not)")


def sel_list(sel):
    """A selector list split at its top-level commas (not :not(a,b)'s)."""
    out, d, cur = [], 0, ""
    for ch in sel:
        d += (ch == "(") - (ch == ")")
        if ch == "," and d == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + [cur.strip()]


# what the gate takes from a touch screen comes back as a pressed look: a
# :hover that paints has an :active for the same element (its own, or the
# hover's paint copied; for "a:hover b", a's or b's), shown while the
# finger is down and gone after it.
# A :hover that reveals (display) is not a press; its touch door is a tap,
# a swipe or a selected state (ui-rules.md, the rule's last sentence).
def pbase(x):
    return re.sub(r":not\([^)]*\)", "", x).replace(":active", "").replace(":hover", "").replace(" ", "")


pressed = set(pbase(x) for at, sel, body in RULES for x in sel_list(sel) if ":active" in x)
unpressed = [short(x) for at, sel, body in RULES if "display:" not in body.replace(" ", "")
             for x in sel_list(sel) if ":hover" in x and pbase(x) not in pressed
             and pbase(re.split(r"[ >+~]", x.strip())[-1]) not in pressed]   # or the painted one's own
chk("hover", not unpressed, "every :hover that paints has a pressed look on touch (:active)"
    + (": " + ", ".join(unpressed) if unpressed else ""))

# ---------------------------------------------------------------- [vh]
# a rule whose selector is given a dvh/svh height anywhere (the same body,
# or an @supports (height:100dvh) block after it) has its fallback, and passes
dvh_sels = set(sel.replace(" ", "") for at, sel, body in NONROOT if re.search(r"\d+[sd]vh", body))
vh = [short(sel) for at, sel, body in NONROOT
      for k, v in decls(body) if re.search(r"(?<![\w-])100vh", v)
      and sel.replace(" ", "") not in dvh_sels]
chk("vh", not vh, "no bare 100vh on a shell without an svh/dvh beside it"
    + (": " + ", ".join(vh) if vh else ""), until="a slice not yet planned (the analysis's finding 9)")
VH_LEFT = {"#dock", ".dklist,.dkwin", ".dkwin"}
chk("vh", set(vh) <= VH_LEFT, "no bare 100vh beyond today's rules"
    + (": new " + ", ".join(sorted(set(vh) - VH_LEFT)) if set(vh) - VH_LEFT else ""))

# ---------------------------------------------------------------- [motion]
# Motion answers an action. Each rule that animates is named here with the
# action it answers (or the brief's one power-up on load); a new one is a
# new line here and in ui-rules.md, and an entrance on a view, a row or a
# load is refused.
anim_sels = sorted(set(short(sel) for at, sel, body in NONROOT
                       for k, v in decls(body) if k in ("animation", "animation-name")
                       and v not in ("none", "none!important")))
MOTION_PIN = 38
chk("motion", len(anim_sels) <= MOTION_PIN,
    f"{len(anim_sels)} animated rules, pinned at {MOTION_PIN}: a new one names its action in ui-rules.md")
entr = [s for s in anim_sels if re.search(r"(^|[\s,])(\.item|\.view|#list)\b", s)
        and "beam" not in s]
chk("motion", not entr, "no entrance animation on a row or a view"
    + (": " + ", ".join(entr) if entr else ""))

# ---------------------------------------------------------------- [uppercase]
# uppercase is Antonio's: a rule that shouts in the sans or the mono is refused
up = [short(sel) for at, sel, body in NONROOT
      if "text-transform:uppercase" in body.replace(" ", "")
      and re.search(r"font-family:var\(--(sans|mono)\)", body.replace(" ", ""))]
chk("uppercase", not up, "no text-transform:uppercase on a --sans or --mono rule"
    + (": " + ", ".join(up) if up else ""))

# ---------------------------------------------------------------- [casing]
# Antonio has one casing, uppercase (the brief's; the analysis's finding 5
# found "Select", "Day", "Close" beside uppercase pills). Every rule that sets
# the display face uppercases it, but these, each with why: the captain's own
# words are shown as written, and a numeral, a date or a name has no case to
# shout. targets.py [casing] holds the computed face on the screens it walks.
CASE_OK = {
    "#edtitle": "an entry's title as written", "#e_head": "the same, as a field",
    "#rd_title": "the same, in the reader", ".md h3,.md h4,.md h5,.md h6": "headings in an entry's text",
    ".blrow .bltitle": "a linked entry's title", ".stktitle": "a pinned entry's title",
    ".dayenth .dttl": "the day page's entry titles", ".magt": "the month agenda's titles",
    ".magt small": "a scheduled hour's end, digits", ".magfree b": "a free run's hour, digits",
    ".gcn": "the graph card's entry title", ".mtile .mfile b": "a file's name",
    ".secho em": "the captain's word echoed in Statistics", ".scloud span": "the word cloud's words",
    ".rmto": "a crew member's name, as it is typed",
    ".relv": "a version number", ".clk": "the clock", ".hcount": "a count", ".srv": "a reading",
    "#rail .ry": "a year", ".day .n": "a day's number", ".wface": "the watch's face",
    ".sro b": "a big count", ".scard b": "a big count", ".mhd b": "a month and year",
    ".xtip b": "a reading", ".xcv": "a reading", ".sdc": "a chart's number", ".mcdn": "a day's number",
    ".calch b": "a count", ".ambclock": "the ambient clock", ".ambmt": "the ambient date",
    ".item .id .tm": "a row's time",
}
case_bad = [short(sel) for at, sel, body in NONROOT
            if "var(--disp)" in body.replace(" ", "") and "text-transform:uppercase" not in body.replace(" ", "")
            and " ".join(sel.split()) not in CASE_OK]
chk("casing", not case_bad, "every rule in Antonio is uppercase, but CASE_OK's"
    + (": " + ", ".join(case_bad) if case_bad else ""))

# ---------------------------------------------------------------- [label]
# WCAG 2.5.3: an aria-label starts with the words the button shows
def words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


# left out, each with why
LABEL_OK = {
    # its label is set by clsHeadPaint, in the classified block, which these
    # slices do not touch (Number One's order of 24 Oct 2026): TODO.md's
    "#bCls": "the classified pill: shows Locked, named Unlock the classified entries",
}
lab_bad = []
for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", markup, re.S):
    attrs, inner = m.group(1), m.group(2)
    al = re.search(r'aria-label="([^"]*)"', attrs)
    if not al:
        continue
    vis = re.sub(r"<svg.*?</svg>", "", inner, flags=re.S)
    # a key hint shown only to a keyboard is not the label (the hints rule)
    vis = re.sub(r'<span class="kbonly">.*?</span>', "", vis, flags=re.S)
    vis = re.sub(r"<[^>]+>", " ", vis)
    vis = re.sub(r"&#?\w+;", " ", vis)
    vw = words(vis)
    if not vw:
        continue
    aw = words(al.group(1))
    bid = re.search(r'id="([^"]*)"', attrs)
    bid = "#" + bid.group(1) if bid else re.sub(r"\s+", " ", attrs.strip())[:40]
    if aw[:len(vw)] != vw and bid not in LABEL_OK:
        lab_bad.append(f"{bid}: shows {' '.join(vw)!r}, named {al.group(1)!r}")
chk("label", not lab_bad, "every labelled button's aria-label starts with its visible words"
    + (": " + "; ".join(lab_bad[:8]) + (" …" if len(lab_bad) > 8 else "") if lab_bad else ""))


# ---------------------------------------------------------------- [verbs]
def calls(name):
    """The argument text of every call to `name`, parentheses balanced."""
    out = []
    for m in re.finditer(r"(?<![\w.])" + name + r"\(", code):
        i, depth = m.end(), 1
        while i < len(code) and depth:
            depth += {"(": 1, ")": -1}.get(code[i], 0)
            i += 1
        out.append(code[m.end():i - 1])
    return out


asks = [a for n in ("lcarsConfirm", "lcarsPrompt") for a in calls(n) if a.strip() != "opts"]
no_ok = [a.strip()[:50].replace("\n", " ") for a in asks if not re.search(r"\bok\s*:", a)]
chk("verbs", asks and not no_ok,
    f"every confirm and prompt names its button by what it does ({len(asks)} calls)"
    + (": no ok: in " + "; ".join(no_ok) if no_ok else ""))
lits = re.findall(r">\s*(OK|Ok|Submit|Yes|No)\s*<", markup + code)
chk("verbs", not lits, "no button reads OK, Submit, Yes or No" + (f": {lits}" if lits else ""))

# ---------------------------------------------------------------- [tint]
hb = [body for at, sel, body in RULES if not at and sel.replace(" ", "") in ("html,body", "body", "html")]
bg = "".join(hb).replace(" ", "")
chk("tint", re.search(r"background(-color)?:(var\(--bg\)|#000\b|#000000)", bg) is not None,
    "html and body are painted the frame's black, which Safari 26 tints its bars from")
tc = re.search(r'name="theme-color" content="([^"]*)"', src)
chk("tint", tc and tc.group(1).lower() in ("#000", "#000000"), "theme-color is the same black")

# ---------------------------------------------------------------- [drag]
# ui-rules.md's list: each drag or gesture and the function its one tap
# calls; each must exist in the page
sec = (rules_md.split("## Every drag has a button") + [""])[1].split("\n## ")[0]
pairs = re.findall(r"^\| ([^|]+?) \| `([\w.#]+)`", sec, re.M)
gaps = re.findall(r"^\| ([^|]+?) \| none yet", sec, re.M)
chk("drag", len(pairs) >= 3, f"ui-rules.md lists the drags and gestures ({len(pairs)})")
for what in gaps:
    chk("drag", False, f"{what.strip()}: has a tap or a key of its own", until="a slice not yet planned")
for what, fn in pairs:
    there = (fn.startswith("#") and f'id="{fn[1:]}"' in src) or \
            (not fn.startswith("#") and re.search(r"function\*?\s+%s\(|%s\s*=\s*\(" % (re.escape(fn), re.escape(fn)), src))
    chk("drag", bool(there), f"{what.strip()}: its tap is {fn}, and the page has it")

# ---------------------------------------------------------------- [headers]
# the desk's header ranked: the views as one bar, then New, Voice and
# Chats, then the rest, ⋯ last; a phone's header holds QUICK_MAX of them
hdr = re.search(r"<header\b.*?</header>", markup, re.S)
ids = re.findall(r'id="(b\w+)"', hdr.group(0)) if hdr else []
views = re.search(r'<div class="hviews"(.*?)</div>', hdr.group(0), re.S) if hdr else None
chk("headers", views and re.findall(r'id="(b\w+)"', views.group(1)) == ["bGraph", "bStars", "bCourse", "bDeck"],
    "the desk's views are one segmented bar: Graph, Stars, Course, Deck")
# by order, never by position: a button added to the header moves indexes
prim = [i for i in ids if i in ("bNew", "bVoice", "bChat")]
vlast = max((ids.index(v) for v in ("bGraph", "bStars", "bCourse", "bDeck") if v in ids), default=-1)
rest = [i for i in ids if i not in ("bGraph", "bStars", "bCourse", "bDeck", "bNew", "bVoice", "bChat", "bMore")]
chk("headers", prim == ["bNew", "bVoice", "bChat"] and len(prim) == 3 and ids.index("bNew") > vlast
    and all(ids.index(r) > ids.index("bChat") for r in rest),
    "then the three primary actions, New, Voice, Chats, after the views and before the rest")
chk("headers", ids and ids[-1] == "bMore", "and ⋯ last, holding the others")
qm = re.search(r"const QUICK_MAX = (\d+);", SCRIPT)
chk("headers", qm and int(qm.group(1)) <= 4, "a phone's header carries at most four (QUICK_MAX)")

# ---------------------------------------------------------------- [listrow]
# the phone's list row is two lines (research slice D): the text clamped to
# one line, the title and the kind's line never wrapping. The height itself
# is targets.py's [listrow], measured; this is the source it rests on.
def phone_decl(sel, prop):
    """`prop`'s value on `sel` in the phone's block (max-width:820px), the
    last one written, or None."""
    v = None
    for at, s, body in NONROOT:
        if any("max-width:820px" in a.replace(" ", "") for a in at) and sel in sels(s):
            for k, x in decls(body):
                if k == prop:
                    v = x
    return v
chk("listrow", phone_decl(".item .sn", "white-space") == "nowrap" and phone_decl(".item .sn", "text-overflow") == "ellipsis"
    and phone_decl(".item .sn", "display") == "block",
    "the phone's list row cuts its text to one line (a nowrap block, an ellipsis)")
chk("listrow", phone_decl(".item .t", "white-space") in (None, "nowrap"),
    "the phone's list row keeps its title on one line (no white-space:normal)")
chk("listrow", phone_decl(".item .m", "white-space") == "nowrap",
    "the phone's list row keeps the kind's line unwrapped")

# ---------------------------------------------------------------- [deskread]
# the desk reads at the body's size (research slice C): the list row's
# title and text at --fs-body, its kind line at --fs-meta, in the rules
# outside any media block (the phone's block sets its own). editor.py's
# [deskread] measures it in Chromium; this is the source it rests on.
def base_decl(sel, prop):
    v = None
    for at, s, body in NONROOT:
        if not at and sel in sels(s):
            for k, x in decls(body):
                if k == prop:
                    v = x
    return v
for sel, tok in ((".item .t", "--fs-body"), (".item .sn", "--fs-body"), (".item .m", "--fs-meta")):
    chk("deskread", base_decl(sel, "font-size") == f"var({tok})", f"the desk's list row: {sel} at {tok}")
# rule:one-control at every width: the entry bar's ranking is not the phone's alone
chk("one-control", base_decl("#edactions .edx", "display") == "none" and base_decl("#edactions #bEdMore", "display"),
    "the entry bar's ⋯ holds the rest at every width (outside the phone's block)")

# ---------------------------------------------------------------- [checked]
# every rule in ui-rules.md names its check, and the check exists
T = os.path.dirname(os.path.abspath(__file__))
heads = re.split(r"(?m)^## ", rules_md)[1:]
for h in heads:
    title = h.split("\n", 1)[0].strip()
    m = re.search(r"(?ms)^Check: (.+?)(?:\n\n|\Z)", h)
    if not m:
        chk("checked", False, f"«{title}» names its check (a Check: line)")
        continue
    line = " ".join(m.group(1).split())
    if line.startswith("none"):
        chk("checked", len(line) > 20, f"«{title}»: no check can be written, and the rule says why")
        continue
    refs = re.findall(r"`([\w./]+)` \[([\w-]+)\]", line)
    chk("checked", bool(refs), f"«{title}»: its Check line names a file and a [slug]")
    for f, slug in refs:
        path = os.path.join(T, f) if "/" not in f else os.path.join(ROOT, f)
        if f == "rules.py":
            chk("checked", slug in SLUGS, f"«{title}»: rules.py checks [{slug}]")
        else:
            body = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            chk("checked", f"rule:{slug}" in body, f"«{title}»: {f} holds rule:{slug}")

for m in ok:
    print("  ok   " + m)
for m in xf:
    print("  xfail " + m)
if bad:
    print("\nFAILED:")
    for m in bad:
        print("  FAIL " + m)
print(f"\nrules: {len(ok)} ok, {len(xf)} expected to fail, {len(bad)} failed")
sys.exit(1 if bad else 0)
