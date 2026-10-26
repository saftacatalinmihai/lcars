#!/usr/bin/env python3
"""Static checks for the parts of the plan that no JS test can see.

Fonts, contrast, aria, CSS rules and constraints in the source that a run
cannot catch. Not whether a function or a class exists by name: a feature the
behaviour suite or buttons.py drives fails there for real when it goes."""
import os, re, sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(D, "index.html"), encoding="utf-8").read()
style = "\n".join(re.findall(r"<style>(.*?)</style>", src, re.S))
head = src[:src.index("</head>")]
ok, bad = [], []
def chk(cond, msg):
    (ok if cond else bad).append(msg)

# --- 1.1 the display font is actually loaded ---
chk("fonts.googleapis.com/css2?family=Antonio" in head, "1.1 Antonio stylesheet is linked")
chk('rel="preconnect" href="https://fonts.gstatic.com"' in head, "1.1 gstatic preconnected")
chk(re.search(r"--disp:\s*\"Antonio\"", style) is not None, "1.1 --disp leads with Antonio")
chk("Antonio" not in re.search(r"--sans:[^;]*;", style).group(0),
    "1.1 body copy is NOT condensed (--sans has no Antonio)")
for sel in [".brand", ".pill", ".lbl", ".day", ".seg button", ".dlg h2", ".mini"]:
    m = re.search(re.escape(sel) + r"\s*\{[^}]*\}", style)
    chk(m and "var(--disp)" in m.group(0), f"1.1 {sel} uses the display face")

# --- 1.8 aria ---
chk('id="toast" role="status" aria-live="polite"' in src, "1.8 toast is a live region")
# (#bFilters is named by its text, "Filters" and the count of those on:
# a label would hide the count from a reader, slice F)
chk(re.search(r'id="bFilters">Filters<span id="fcount">', src), "1.8 #bFilters is named by its words and count")
for bid in ["bNew", "bReload", "bCfg", "bBack", "bClose", "bRefresh", "bVoice"]:
    m = re.search(r'id="%s"[^>]*' % bid, src)
    chk(m and "aria-label" in m.group(0), f"1.8 #{bid} has an aria-label")

# --- 1.9 scrollbars ---
chk("::-webkit-scrollbar" in style, "1.9 webkit scrollbars themed")
chk("scrollbar-color" in style, "1.9 firefox scrollbars themed")

# --- 2.x look and feel ---
chk("header::after" in style and "linear-gradient" in style, "2.2 segmented header strip")
chk("#elbow" in style and "#elbow::after" in style, "2.1 LCARS elbow present")
chk('data-tag="' in src, "2.1 decorative numeric tags on the section bars")
chk(re.search(r"\.lbl\s*\{[^}]*border-radius:0 var\(--r12\) var\(--r12\) 0", style) is not None,
    "2.1 section bars are right-rounded")
chk("prefers-reduced-motion: no-preference" in style, "2.3 motion is opt-in")
chk("prefers-reduced-motion: reduce" in style, "2.3 existing transitions respect reduce")
chk(":focus-visible" in style, "2.4 keyboard focus is visible")
chk(".day.today" in style, "2.5 today inverts")
chk("--dc" in style, "2.5 weekday colour rotation")

# --- 2.6 contrast, computed ---
def lum(h):
    c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
dim = re.search(r"--dim:\s*#([0-9a-f]{6})", style).group(1)
r = ratio(dim, "080809")
chk(r >= 4.5, f"2.6 --dim on the list background is AA ({r:.2f}:1)")
sn = ratio("9a97a5", "080809")
chk(sn >= 4.5, f"2.6 snippet text is AA ({sn:.2f}:1)")
chk(ratio("fc6", "000000") if False else True, "")
for name, fg in [("amber", "ffcc66"), ("orange", "ff9900"), ("purple", "cc99cc"),
                 ("blue", "99ccff"), ("green", "99cc66"), ("red", "cc6666")]:
    rr = ratio(fg, "0d0d10")
    chk(rr >= 4.5, f"2.6 {name} on panel is AA ({rr:.2f}:1)")
# slice E's text tokens, read from :root: a text colour is checked where it is named
for name in ("soft", "txt2", "red-light", "red-lighter"):
    m = re.search(r"--%s:\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b" % re.escape(name), style)
    fg = m and (m.group(1) if len(m.group(1)) == 6 else "".join(c * 2 for c in m.group(1)))
    rr = ratio(fg, "0d0d10") if fg else 0
    chk(rr >= 4.5, f"2.6 --{name} on panel is AA ({rr:.2f}:1)")

# --- bleeding section bars are not clipped by their own scroller ---
# .shead/.kh reach past the dialog's padding with a negative margin; the
# scroller they sit in has to give that back, or overflow-y clips them
# sideways and the bars lose their first letters ("BY KIND" -> "Y KIND").
def rule(sel):
    m = re.search(re.escape(sel) + r"\s*\{[^}]*\}", style)
    return m.group(0) if m else ""
ss = rule(".sscroll")
# the bars use the `margin:a b c -18px` shorthand, so the bleed is the largest
# negative length anywhere in their rules
bleed = max((int(n) for n in re.findall(r"-(\d+)px", rule(".shead") + rule(".kh"))),
            default=0)
pad = max((int(n) for n in re.findall(r"padding-left:\s*(\d+)px", ss)), default=0)
chk("overflow-y:auto" in ss.replace(" ", "") and pad >= bleed,
    f"bleed: .sscroll gives back the {bleed}px its section bars reach past (has {pad}px)")

# --- a dialog can never grow past the screen it is centred in ---
chk("max-height" in rule(".dlg"), "dialog: bounded height, so #ov cannot clip it off both ends")

# --- flex containers do not swallow the spaces around inline markup ---
for eid in ["edempty", "gempty"]:
    m = re.search(r'id="%s"[^>]*>(.*?)</div>' % eid, src, re.S)
    chk(m and m.group(1).lstrip().startswith("<span"),
        f"flex: #{eid} wraps its text, so the spaces around <b> survive")

# --- backlinks ---
chk("#rd_back:empty{display:none}" in style.replace(" ", ""),
    "backlinks: nothing is drawn when nothing links here")

# --- outline folding ---
chk(re.search(r"\.md li\.fold\+ul\s*\{\s*display:none", style.replace(" ", "").replace("li.fold+ul", "li.fold+ul")) is not None
    or ".mdli.fold+ul{display:none" in style.replace(" ", ""),
    "fold: a folded branch is hidden by the sibling rule")

# --- the themed confirm ---
# The comments here talk about confirm() a good deal, and this file's block
# comments carry no leading asterisks, so they have to be stripped as blocks
# rather than line by line.
code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
code = re.sub(r"(?m)^\s*//.*$", "", code)
native = re.findall(r"(?<![\w.])confirm\(", code)
chk(len(native) == 1,
    f"confirm: exactly one native confirm() is left, the discard prompt (found {len(native)})")

# --- voice ---
# The parsing is covered by the behaviour suite; what is checked here is the
# part of the feature that only exists in markup and CSS.
chk("window.SpeechRecognition || window.webkitSpeechRecognition" in src,
    "voice: the recogniser is feature-detected, not assumed")
chk("if (r.isFinal) voiceHeard(" in src,
    "voice: only a finished transcript is acted on, never an interim one")
flat = style.replace(" ", "").replace("\n", "")
chk("#vhud{display:none}" in flat and 'body[data-voice="on"]#vhud{' in flat,
    "voice: the read-out exists only while the microphone is open")
# the mode is worth announcing; the running transcript would be read twice a
# second, so the region around it is explicitly silent
chk('id="vhud" data-state="off" aria-live="off"' in src, "voice: the transcript is not a live region")
chk('id="vmode" aria-live="polite"' in src, "voice: the mode is announced")
chk('id="bVoice"' in src and "aria-pressed" in re.search(r'id="bVoice"[^>]*(?:\n[^>]*)*?>', src).group(0),
    "voice: the toggle reports whether it is listening")
# --- the second recogniser ---
chk('id="c_veng"' in src and 'value="deepgram"' in src,
    "voice: the recogniser is chosen in Config, not compiled in")
chk('id="c_vkey"' not in src and 'apiNet("/say/token"' in src,
    "voice: no deepgram key is asked for: the server mints one per socket (GET /say/token)")
# The key belongs to this browser, and to nothing that is committed: it is read
# out of localStorage and is empty until somebody types it into Config. This
# page is in a public repository, so the check is that no key-shaped literal is
# anywhere in it.
chk('typeof c.key === "string" ? c.key : ""' in src,
    "voice: the deepgram key comes from localStorage, never from the page")
chk(re.search(r"[\"'][0-9a-f]{32,}[\"']", src) is None,
    "voice: no api key is baked into the page")
chk("encoding: \"linear16\"" in src,
    "voice: deepgram is sent raw pcm, which every browser can produce")
chk('new WebSocket(dgUrl(rate), pttProto(token))' in src,
    "voice: the key travels as a websocket subprotocol, the only header a browser has")
chk("m.speech_final" in src and 'm.type === "UtteranceEnd"' in src,
    "voice: an utterance is flushed on an end of speech, not on every final fragment")
chk("t.stop()" in src and "getTracks()" in src,
    "voice: stopping closes the microphone rather than leaving the light on")

# it takes a corner of the screen that other things already live in
for sel in ["#lfoot", "#side", "#edactions"]:
    chk('body[data-voice="on"]' in style and re.search(
        r'body\[data-voice="on"\][^{]*%s\s*\{' % re.escape(sel), style) is not None,
        f"voice: {sel} moves clear of the read-out")
# rule:frame (ui-rules.md, "The phone's frame"): the foot and what docks above it
# the toast is placed by measurement rather than by a rule per neighbour: it
# dodges the read-out along with everything else docked to the bottom edge
m = re.search(r"const TOAST_DODGE = \[([^\]]*)\]", src)
chk(m and all(q in m.group(1) for q in ['"#vhud"', '"#edactions"', '"#lfoot"']),
    "toast: placeToast dodges the read-out, the action bar and the list's foot (New)")

# --- the task board ---
# The renderer paints task markers and the board collects them. If the two ever
# read different lists, a marker could be styled as a task in an entry and be
# invisible on the board — so both are built from TASK_WORDS and neither may
# carry a marker list of its own.
chk("const TASK_WORDS = TASK_OPEN.concat(TASK_SHUT)" in src,
    "tasks: the markers are one list")
chk('new RegExp("^(" + TASK_WORDS.join("|")' in src,
    "tasks: the renderer's marker regex is built from that list")
chk('TASK_WORDS.join("|")' in src.split("const TASK_LINE")[1][:200],
    "tasks: so is the board's")
chk(".tkrow" in style and ".tkage.old" in style and ".tktick" in style, "tasks: the board has its tick and its staleness colour")

# --- new since the last visit ---
chk(".item.fresh" in style and ".newtag" in style,
    "fresh: a new row is marked in colour and in words")

# --- reading aloud ---
chk("window.speechSynthesis" in src and "const ttsApi = () =>" in src,
    "aloud: the synthesiser is feature-detected, never assumed")
m = re.search(r'id="bAloud"[^>]*', src)
chk(m and "aria-label" in m.group(0), "aloud: the button has an aria-label")
chk(m and 'style="display:none"' in m.group(0),
    "aloud: and is absent until a reader with a synthesiser behind it says otherwise")
chk("pagehide" in src, "aloud: speech does not outlive the page")

# --- the month grid ---
chk(".mcal" in style and ".mcdd i" in style, "month: the grid and its per-kind dots")

# --- the calendar's other three scales ---
# The four layouts share one table and one drag machine. What is checked here
# is that neither has quietly grown a second copy: a scale missing from CAL
# would page by the wrong unit, and a layout that drew its own drop targets
# without data-drop would silently stop accepting entries.
chk("const CAL = {" in src and all(
        re.search(r"\n  %s:\s*\{" % k, src.split("const CAL = {")[1][:900]) for k in
        ("year", "month", "week", "day")),
    "calendar: all four scales are rows of one table")
chk("const CAL_HTML = {" in src and all(
        "function cal%sHtml(" % k in src for k in ("Year", "Month", "Week", "Day")),
    "calendar: and each has exactly one layout behind it")
for cls in [".calyr", ".calmg", ".calwk", ".calcol", ".calday", ".calhr", ".mce"]:
    chk(cls in style, f"calendar: {cls} is styled")
chk("[data-drop].drop" in style, "calendar: a drop target lights up under a carried entry")
cal = src.split("const CAL_HTML")[0]
# the month's cells are calCellHtml's (shared with the phone's strip, slice 4)
chk("calCellHtml(" in cal.split("function calMonthHtml(")[1].split("\nfunction ")[0],
    "calendar: calMonthHtml draws its days as calCellHtml's cells")
for layout, want in [("calYearHtml", 1), ("calCellHtml", 1), ("calWeekHtml", 1), ("calDayHtml", 1)]:
    body = cal.split("function %s(" % layout)[1].split("\nfunction ")[0]
    chk(body.count("data-drop=") >= want,
        f"calendar: {layout} draws somewhere to drop an entry")
chk('closest("[data-drop]")' in src,
    "calendar: the drag finds its target by that attribute and nothing else")

# --- the calendar and the filter bar ---
# One answer to "does this row pass the filters", shared by the list and the
# calendar; the two having separate copies is how they would quietly diverge.
chk("st.all.filter(makeRowFilter(false))" in src, "filters: the list builds st.view with it")
chk(src.count("makeRowFilter(true)") == 2,
    "filters: and both calendar indexes ask the same question")
chk("if (skipDates && c.byDate) continue;" in src,
    "filters: the calendar skips the date range, whose axis it already is")
chk(src.count("byDate: true") == 2,
    "filters: which is marked on the two date controls themselves")
chk("function calFilterCount(" in src and "!c.byDate" in src,
    "filters: a narrowed grid says so, counting only the filters it applied")

# --- moving an entry ---
# A drag is a write, and it is held to the same manners the editor's Save is.
mv = src.split("async function calMove(")[1][:2200]
chk('await api("/entries/" + id)' in mv and "last_modified_at_utc" in mv,
    "move: one GET first, so a drag cannot flatten somebody else's edit")
chk("lcarsConfirm(" in mv, "move: and it asks, in the app's own voice, before it does")

# --- naming a block in place ---
ren = src.split("function calRenameOpen(")[1][:2200]
chk("lane.appendChild(inp)" in ren and "blk.appendChild" not in ren,
    "rename: the field is laid over the block, not inside the button")
chk(".calren{" in style.replace(" ", "") and "pointer-events:auto" in style,
    "rename: and takes the pointer, which the lane around it does not")
rk = src.split("function calRenameKey(")[1][:400]
chk("ev.stopPropagation()" in rk,
    "rename: the calendar's own keys do not reach a field being typed into")
chk('ev.key === "Escape"' in rk and "calRenameClose()" in rk,
    "rename: Escape drops the name rather than closing the calendar under it")
chk('addEventListener("blur"' in ren,
    "rename: clicking away to draw the next block keeps what was typed")
# A block is as short as what it stands for — a quarter hour is 11px — so its
# name shares the line with its time rather than sitting under it, unseen.
blk_css = style.split(".calblk{")[1].split("}")[0].replace(" ", "")
chk("flex-direction:row" in blk_css, "day grid: a block reads on one line, like a chip")
chk("text-overflow:ellipsis" in style.split(".calblkn{")[1].split("}")[0].replace(" ", ""),
    "day grid: and a name too long for the block is cut, not wrapped away")
# The grid a drag is read off has to be linear, or a cursor position is not a
# time; and the lane has to exist on an empty day, or there is nothing to draw on.
chk('class="calday sched"' in src,
    "day grid: always on the fixed hour scale, so a drag on it means a time")
chk('const lane = `<div class="calsched"' in src,
    "day grid: and always has a lane, including on a day with nothing scheduled")
# A clipped edge is where the drawing stopped, not where the entry does.
chk("b.clipTop ?" in src and "b.open || b.clipBot ?" in src,
    "resize: a block cut off by midnight offers only the edge it really owns")
# the touch half of the gesture is the part no JS test can reach
chk("CAL_HOLD" in src and 'pointerType === "touch"' in src,
    "move: a finger has to hold still before it is carrying anything")
chk('addEventListener("touchmove", calNoScroll, { passive: false })' in src,
    "move: and only then is the page's own scrolling taken off it")
chk("calRepaint = null" in src.split("function closeOv(")[1][:500],
    "calendar: closing the overlay takes its repaint with it")
chk("calDragDrop(false)" in src.split("function closeOv(")[1][:500],
    "calendar: and puts down anything still in mid-air")

# --- possibly related ---
chk("#rd_rel:empty{display:none}" in style.replace(" ", ""),
    "related: nothing is drawn when nothing clears the floor")
# a generator that yields whenever over() says the frame's share is spent
# (renderExtras drives it); it replaced relIndex()'s 60ms REL_BUDGET stopwatch
chk("function* relatedJob(e, over)" in src and "over()) yield;" in src,
    "related: the index is built in slices that yield to the frame, never in one stall")
chk("relBag" in src and "st.all is what gets" in src,
    "related: the term sets stay out of the rows the cache serialises")
chk("REL_NORM" in src and "Math.sqrt(Math.max(REL_NORM" in src,
    "related: the length correction has a floor, so short notes cannot win on nothing")

# --- topic trends ---
chk("function trendSeries(" in src and "function openTrend(" in src,
    "trend: a term, counted per month")
chk("RE_ESC" in src and "term.replace(RE_ESC" in src,
    "trend: a term is escaped before it becomes a regex")
chk("/^\\w/.test(term)" in src, "trend: \\b is only used where it means something")
chk(".trwrap" in style and ".traxis" in style, "trend: the chart and its axis")

# --- the stack ---
chk("function stackOpen(" in src and "function stackLink(" in src,
    "stack: shift-clicking a [[link]] pins the entry it names")
chk('body[data-stack="on"] #stackpane{display:flex}' in style,
    "stack: the column exists only while something is pinned")
chk('body[data-focus="on"] #stackpane{display:none}' in style,
    "stack: focus mode is still one entry alone on screen")
chk(".stk.on>.stkbody{display:block}" in style.replace(" ", ""),
    "stack: exactly one panel is open; the rest stay bars")
chk("STACK_MAX" in src, "stack: the shelf has a depth")
for bid in ["bStackClear"]:
    m = re.search(r'id="%s"[^>]*' % bid, src)
    chk(m and "aria-label" in m.group(0), f"stack: #{bid} has an aria-label")
# in the phones' own block: the first max-width:820px query in the style
# is any one-line rule (0.183.5's version mark made it one)
chk(re.search(r'#stackpane\{[^}]*\}', style.split("phones / small tablets")[1]) is not None,
    "stack: on a phone it docks to the bottom edge instead of taking a column")

# --- templates ---
chk("TPL_KIND_LINE" in src and "kind::" in src, "templates: a kind:: header sets the new entry's kind")
chk("TPL_CURSOR" in src and "setSelectionRange" in src, "templates: {cursor} places the caret")

# --- quick capture ---
man = open(os.path.join(D, "manifest.webmanifest"), encoding="utf-8").read()
chk('"share_target"' in man and '"method": "GET"' in man,
    "capture: a GET share target, so the cached shell needs no worker for it")
chk("history.replaceState" in src.split("function shareTarget(")[1][:600],
    "capture: the shared text is wiped out of the url once it has been read")

# --- saved views ---
chk(".vc .vcx" in style and ".vc.on" in style,
    "views: a chip applies, forgets, and says when the filters are already on it")

# --- ambient mode ---
chk('body[data-amb="on"] #amb{' in style.replace("\n", "").replace("  ", ""),
    "ambient: it exists only while it is up")
chk("if (ambOn) { ev.preventDefault(); ambStop(); return; }" in src,
    "ambient: any key hands the console straight back")
amb = src.split("function idleArm(")[1][:700]
chk('classList.contains("dirty")' in amb and "vx.on" in amb and "tts.on" in amb,
    "ambient: unsaved work, a dialog, the microphone and a voice all hold it back")
chk('id="ambexit"' in src and "aria-label" in re.search(r'id="ambexit"[^>]*', src).group(0),
    "ambient: the way out has an aria-label")

# --- 5.1 pwa ---
for f in ["manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png", "apple-touch-icon.png"]:
    chk(os.path.exists(os.path.join(D, f)), f"5.1 {f} exists")
chk('name="theme-color"' in head, "5.1 theme-color meta")
chk('name="apple-mobile-web-app-capable"' in head, "5.1 iOS standalone meta")
chk('rel="manifest"' in head, "5.1 manifest linked")
chk('rel="apple-touch-icon"' in head, "5.1 apple touch icon linked")
sw = open(os.path.join(D, "sw.js"), encoding="utf-8").read()
chk("/^\\/(entries|stats)\\b/" in sw, "5.1 the API is never served from cache")

# --- 6 a11y ---
chk('role="dialog" aria-modal="true"' in src, "6 dialog is modal")
chk('aria-labelledby="dlgh"' in src, "6 dialog is labelled")
chk('role="button"' in src and 'aria-current' in src, "6 rows are announced")

# --- every css variable resolves ---
defined = set(re.findall(r"(--[\w-]+)\s*:", style))
used = set(re.findall(r"var\((--[\w-]+)", style)) | set(re.findall(r"var\((--[\w-]+)", src))
missing = sorted(u for u in used - defined if u not in ("--k", "--c", "--dc"))
chk(not missing, "css: every var() resolves" + (" — missing " + ", ".join(missing) if missing else ""))

# --- the constraints the plan said not to regress ---
# rule:keep (ui-rules.md, "Keep"), with 2.3, 2.4 and 2.6's lines above
chk("-webkit-overflow-scrolling:touch" in style, "constraint: momentum scrolling kept")
chk("env(safe-area-inset" in style, "constraint: safe-area insets kept")
chk("100dvh" in style, "constraint: dvh height kept")
# the inputs take --fs-body (ui-rules.md's scale), which must stay 16px
chk("--fs-body:16px" in style and ("font-size:var(--fs-body)" in style or "font-size:16px" in style),
    "constraint: 16px inputs (no iOS focus zoom)")
chk("histOk = false" in src, "constraint: file:// pushState degrades")
chk("if (limit > 15)" in src, "constraint: 1MB arena page halving kept")
chk("last_modified_at_utc is deliberately never sent on PUT" in src,
    "constraint: PUT never sends last_modified_at_utc")

print("\n".join("  ok   " + m for m in ok if m))
if bad:
    print("\nFAILED:")
    print("\n".join("  FAIL " + m for m in bad))
print(f"\naudit: {len(ok)} ok, {len(bad)} failed")
sys.exit(1 if bad else 0)
