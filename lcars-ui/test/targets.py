#!/usr/bin/env python3
# test/targets.py (~20s, no server): the phone's tap targets (UI review
# slice 2, docs/design/ui-rules.md "Targets") in headless Chromium at an
# iPhone's size with touch, against perf.py's fake API. On the list, the
# reader, the editor, the ⋯ sheet, the filters drawer and the month, every visible
# control is probed where a finger lands: out from its middle, left, right,
# up and down, a pixel at a time, for as long as the points still hit the
# control itself (through its ::before hit area when it has one). The runs
# must reach 44px each way (a round 44px button passes), so a target short
# of 44 fails, and so does one cut short by a neighbour (named): two hit
# areas never overlap.
# A few are allowed less, each with its reason in SHORT. And the header's
# pills are 44px tall. On the same screens the rendered rules
# (docs/design/ui-rules.md): what is uppercase is Antonio (rule:uppercase),
# no key hint on a touch screen (rule:hints), and at 320px wide no sideways
# scroll (rule:reflow). And the list's rows two lines, 44 to 64px tall, at
# 390 and at 320 wide (rule:listrow). Antonio uppercase (rule:casing) and no
# middle-dot string (rule:dots) on those screens and the desk's.
import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import perf
from playwright.sync_api import sync_playwright

fails = []
def ok(c, msg):
    print(("ok   " if c else "FAIL ") + msg)
    if not c: fails.append(msg)

def xok(c, msg, until=None):
    """ok(), or for a rule a later slice fixes (ui-rules.md, "Every rule
    ships with its check"): failing is expected, passing fails (XPASS)."""
    if not until:
        return ok(c, msg)
    if c:
        ok(False, msg + f" - XPASS: it holds now, drop its UNTIL entry ({until})")
    else:
        print("xfail " + msg + f" (expected to fail until {until})")

# (rule, screen) -> the slice that makes it pass: checks failing today
UNTIL = {
}

# left out of rule:uppercase, each with why
UPPER_SKIP = {
    # the classified block is not to be touched by these slices (Number
    # One's order of 24 Oct 2026); its face is for a slice that may
    "#edcls": "the editor's Classified chip, in the sans",
}

# rule:uppercase - every visible element whose own text is uppercased by CSS
UPPER = r"""(skip) => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join('').trim();
    if (!/[a-z]/i.test(own)) continue;
    if (skip.some(q => el.closest(q))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const cs = getComputedStyle(el);
    if (cs.textTransform !== 'uppercase' || cs.visibility === 'hidden') continue;
    if (/Antonio/.test(cs.fontFamily)) continue;
    out.push({ el: el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + el.className, text: own.slice(0, 24),
               face: cs.fontFamily.split(',')[0] });
  }
  return out;
}"""

# rule:casing - Antonio's one casing, computed: a visible text in the display
# face that is not uppercased, outside the captain's own words and the
# numerals rules.py's CASE_OK names (and a text with no lowercase letter);
# rule:dots - a visible text joined by middle dots, outside an entry's text
# CASE_SKIP is rules.py's CASE_OK, read from its source so the two never drift
import ast, re
CASE_SKIP = list(ast.literal_eval(re.search(r"^CASE_OK = (\{.*?^\})", (pathlib.Path(__file__).resolve().parent
    / "rules.py").read_text(), re.S | re.M).group(1))) + [".md"]
CASEDOTS = r"""(skip) => {
  const out = { casing: [], dots: [] };
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join('').trim();
    if (!own) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden') continue;
    const nm = (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + el.className) + ' ' + own.slice(0, 30);
    if (/[a-z]/.test(own) && /Antonio/.test(cs.fontFamily) && cs.textTransform !== 'uppercase'
        && !skip.some(q => el.closest(q))) out.casing.push(nm);
    if (/\u00b7/.test(own) && !el.closest('.md')) out.dots.push(nm);
  }
  return out;
}"""

# rule:hints - a key named on a touch screen: a visible <kbd>, or a line
# ending in "· K" / "· ⏎" the way a picker's keyboard hint does
KEYHINT = r"""() => {
  const out = [];
  // on screen and on top: a drawer slid out of view, or a sheet over it, is not shown
  const shown = el => { const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const x = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), y = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2));
    const h = document.elementFromPoint(x, y);
    return !!h && (h === el || el.contains(h) || h.contains(el)); };
  // the voice orders' list (.vsays) sets the phrases to say in <kbd>, HTML's
  // "user input", voice included: words, never a key
  for (const k of document.querySelectorAll('kbd'))
    if (!k.closest('.vsays') && shown(k)) out.push({ kbd: k.textContent.slice(0, 12) });
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join('').trim();
    if (/·\s*(\S|⏎|Tab|Esc)$/.test(own) && /·\s*([A-Z?⏎]|Tab|Esc)$/.test(own) && shown(el))
      out.push({ el: el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + el.className, text: own.slice(-24) });
  }
  return out;
}"""

# selector -> [width, height] its hit area must reach instead of 44x44, and why
SHORT = {
    # an outline's lines are 24.5px apart: 44 across, as tall as the gap allows
    ".md button.task": [44, 24],
    ".fbtn": [44, 24],
    # kind chips wrap in rows 6px apart, each taking half the gap: 40 tall
    ".kc": [44, 40],
}

PROBE = r"""(short) => {
  const sel = 'button,a[href],[role=button],select,input[type=checkbox],input[type=radio],summary';
  const out = [];
  const name = el => el.id ? '#' + el.id
    : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  const shown = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.pointerEvents !== 'none';
  };
  // a checkbox's or a radio's <label> is its hit area: a tap on it toggles
  // the box (HTML's activation behaviour); a select's is not (a tap on its
  // label only focuses it, the picker does not open)
  const mine = (el, x, y) => { const h = document.elementFromPoint(x, y);
    return h && (h === el || el.contains(h)
      || (/^(checkbox|radio)$/.test(el.type) && [...(el.labels || [])].some(l => l.contains(h)))); };
  for (const el of document.querySelectorAll(sel)) {
    // a row is a target of its own, far taller than 44; the play button and
    // the day's Read are the controls a list row holds
    if (el.matches('.item') || (el.closest('.item') && !el.matches('.tplay'))) continue;
    // a link in prose, an entry's or Statistics' sentences: WCAG 2.5.8's inline exception
    if (el.matches('.md a, .md a *, .sins a')) continue;
    if (!shown(el)) continue;
    let r = el.getBoundingClientRect();
    let cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= innerWidth || cy >= innerHeight) continue;
    // under a sheet, a fixed bar or off its scroller: not a target on this screen
    if (!mine(el, cx, cy)) continue;
    let w = 44, h = 44;
    for (const k in short) if (el.matches(k)) [w, h] = short[k];
    // the run of points that hit it, out from its middle along each axis: a
    // hit area need not be centred (the fold caret's reaches into the margin)
    const run = (dx, dy) => {
      let n = 0, by = null;
      while (n < 60) {
        const x = cx + dx * (n + 1), y = cy + dy * (n + 1);
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return [n, 'edge'];
        if (!mine(el, x, y)) { const t = document.elementFromPoint(x, y); by = t && t.closest(sel); break; }
        n++;
      }
      return [n, by];
    };
    const measure = () => {
      const l = run(-1, 0), rr = run(1, 0), u = run(0, -1), d = run(0, 1);
      // a run cut by the screen's edge counts to the edge: a finger cannot go past it
      const fw = l[0] + rr[0] + 1, fh = u[0] + d[0] + 1;
      const edge = [l, rr, u, d].some(x => x[1] === 'edge');
      const by = [l, rr, u, d].map(x => x[1]).find(x => x && x !== 'edge' && x !== el);
      return { fw, fh, ok: edge ? (fw >= w - 1 || l[1] === 'edge' || rr[1] === 'edge') && (fh >= h - 1 || u[1] === 'edge' || d[1] === 'edge')
                               : fw >= w - 1 && fh >= h - 1, by };
    };
    let m = measure();
    if (!m.ok) {
      // half under the bottom bar or off its scroller: looked at again in the
      // middle of its scroller, where a finger would take it
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      r = el.getBoundingClientRect(); cx = r.left + r.width / 2; cy = r.top + r.height / 2;
      m = measure();
    }
    if (m.ok) continue;
    out.push({ el: name(el), text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 24),
               box: Math.round(r.width) + 'x' + Math.round(r.height), hit: m.fw + 'x' + m.fh, need: w + 'x' + h,
               under: m.by ? name(m.by) : '' });
  }
  return out;
}"""

# rule:listrow (ui-rules.md, "The phone's list row"): every list row on
# screen two lines, 44 to 64px tall, its title on one line
LISTROW = r"""() => {
  const L = document.querySelector('#list').getBoundingClientRect(), out = [];
  for (const it of document.querySelectorAll('#list .item')) {
    const r = it.getBoundingClientRect();
    if (r.height < 1 || r.bottom < L.top || r.top > innerHeight) continue;
    const t = it.querySelector('.t'), th = t.getBoundingClientRect().height;
    const lh = parseFloat(getComputedStyle(t).lineHeight);
    out.push({ id: it.dataset.id, h: Math.round(r.height), titleLines: Math.round(th / lh) });
  }
  return out;
}"""

# the row with a long kind name, a reading and done (rows[1], below): the
# kind's name gives way, so its last flag ends inside the kind's line with
# nothing clipped, and the text keeps a third of the text column (at 390;
# at 320 the flags only). perf.py's own kinds are short and hid this.
LONGKIND = r"""(id) => {
  const it = document.querySelector(`#list .item[data-id="${id}"]`);
  if (!it) return null;
  const m = it.querySelector('.m'), last = m.lastElementChild, sn = it.querySelector('.sn');
  return { lastIn: last.getBoundingClientRect().right <= m.getBoundingClientRect().right + 0.5,
           last: last.textContent, clipped: m.scrollWidth > m.clientWidth + 1,
           sn: Math.round(sn.getBoundingClientRect().width), col: Math.round(it.querySelector('.t').getBoundingClientRect().width) };
}"""

# a search typed: each row's text is an excerpt of one line, and its first
# highlight must show inside the text's box, not past the ellipsis: its first
# letters (20px of it, or all of a shorter one) clear of the ellipsis's 12px
SEARCHHIT = r"""() => {
  const L = document.querySelector('#list').getBoundingClientRect(), out = [];
  for (const it of document.querySelectorAll('#list .item')) {
    const r = it.getBoundingClientRect(), sn = it.querySelector('.sn'), mk = sn && sn.querySelector('mark');
    if (r.height < 1 || r.top < L.top || r.bottom > innerHeight || !mk) continue;
    const b = sn.getBoundingClientRect(), m = mk.getBoundingClientRect();
    out.push({ id: it.dataset.id, raw: /\]\(|https?:|[\[\]]/.test(sn.textContent), inside: m.left >= b.left - 0.5 && m.left + Math.min(20, m.width) <= b.right - 12, text: sn.textContent.slice(0, 30), sn: Math.round(b.width), at: Math.round(m.left - b.left), meta: it.querySelector('.m').textContent });
  }
  return out;
}"""

def listrow(pg, width):
    rs = pg.evaluate(LISTROW)
    bad = [x for x in rs if not (44 <= x["h"] <= 64) or x["titleLines"] != 1]
    for x in bad[:6]:
        print("       " + json.dumps(x))
    ok(len(rs) >= 6 and not bad, f"rule:listrow at {width}: every list row on screen 44-64px, its title one line "
       f"({len(rs)} rows, {sorted(set(x['h'] for x in rs))}px)")
    lk = pg.evaluate(LONGKIND, rows[1]["id"])
    ok(lk and lk["lastIn"] and not lk["clipped"] and lk["last"] == "done",
       f"rule:listrow at {width}: a long kind name gives way, its reading and done whole on line 2 ({lk})")
    pg.fill("#q", "plants")
    pg.wait_for_timeout(700)
    hits = pg.evaluate(SEARCHHIT)
    out = [x for x in hits if not x["inside"] or x["raw"]]
    for x in out[:4]:
        print("       " + json.dumps(x))
    ok(len(hits) >= 3 and not out, f"rule:listrow at {width}: a search's hit shows on each row's one line, "
       f"no link markup in it ({len(hits) - len(out)} of {len(hits)} rows)")
    ok(any(x["id"] == str(rows[2]["id"]) for x in hits),
       f"rule:listrow at {width}: the row whose hit is inside a link's text is among them")
    pg.fill("#q", "")
    pg.wait_for_timeout(700)
    if width >= 390:
        ok(lk and lk["sn"] * 3 >= lk["col"], f"rule:listrow at {width}: after a long kind name the text keeps a third "
           f"of the text column ({lk and lk['sn']} of {lk and lk['col']}px)")

rows = perf.journal(300)
# an entry with an outline: TODO and DONE toggles, a branch's fold caret,
# and a running stopwatch in the reader's meta line
rows[0]["content"] = ("- TODO water the plants\n- a branch\n  - its leaf\n  - another\n"
                      "- DONE the other\n\n" + rows[0]["content"])
rows[0]["start_date"] = "2026-09-25 09:00:00"
# rule:listrow's hard rows: a long kind name, a reading and done; and a
# search's hit inside a link's text (the excerpt cut must not split the link)
rows[2]["content"] = "I read [the article on plants](https://example.com/plants-article) today, then slept."
rows[2]["content_length"] = len(rows[2]["content"].encode())
rows[1].update(kind="a_rather_long_kind_name_here", value_float=6.5, value_int=0, done_bool=1, deleted=0, start_date="")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport=perf.PHONE, has_touch=True, is_mobile=True, device_scale_factor=2)
    ctx.route(perf.BASE + "/**", perf.serve(rows))
    ctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(perf.PAGE)
    pg.wait_for_selector("#list .item")
    pg.wait_for_timeout(1000)
    ok(pg.evaluate("matchMedia('(pointer:coarse)').matches"), "the page sees a finger (pointer:coarse)")

    def screen(name):
        bad = pg.evaluate(PROBE, SHORT)
        for x in bad:
            print("       " + json.dumps(x))
        # rule:targets (ui-rules.md, "Targets")
        ok(not bad, f"{name}: every control's hit area is 44px (or SHORT's), none under a neighbour's")
        rendered(name)

    def rendered(name):
        # rule:uppercase: what is shouted is Antonio's, computed
        up = pg.evaluate(UPPER, list(UPPER_SKIP))
        for x in up[:6]:
            print("       " + json.dumps(x))
        xok(not up, f"{name}: every visible uppercase text is in Antonio ({len(up)} not)",
            UNTIL.get(("uppercase", name)))
        # rule:hints: a touch screen shows no key hint
        kh = pg.evaluate(KEYHINT)
        for x in kh[:6]:
            print("       " + json.dumps(x))
        xok(not kh, f"{name}: no key hint shown on a touch screen ({len(kh)})",
            UNTIL.get(("hints", name)))
        casedots(name)

    def casedots(name):
        cd = pg.evaluate(CASEDOTS, CASE_SKIP)
        ok(not cd["casing"], f"rule:casing on {name}: what is in Antonio is uppercase ({cd['casing'][:4]})")
        until = UNTIL.get(("dots", name))
        # the expected failure covers the palette's notes alone: any other dot there fails now
        left = [d for d in cd["dots"] if until and d.startswith("span.pkl ")]
        ok(len(left) == len(cd["dots"]), f"rule:dots on {name}: none but UNTIL's "
           f"({[d for d in cd['dots'] if d not in left][:4]})")
        xok(not left, f"rule:dots on {name}: no middle-dot string ({cd['dots'][:4]})", until)

    # the views past the six screens: (name, how its button opens it, ms to
    # settle, what the screen's middle must be inside once it is up)
    VIEWS = (("a new entry", "newEntry()", 700, "#editpane"), ("Tasks", "openTasks()", 900, "#tkrows"),
             ("Statistics", "openStats()", 1200, "#dlg"), ("the chats", "chatsOpen()", 900, "#chrows"),
             ("the help", "helpDoor()", 700, "#v_gest"), ("the palette", "openPalette()", 500, "#dlg"),
             ("Reports", "openReports()", 900, "#rprows"), ("the graph", "openGraph()", 1500, "#gcanvas"),
             ("the Day view", "openDay(dayKey(st.view[0].created_at_utc))", 900, "#dayout"))

    def walk(each):
        """The six screens, then VIEWS, each handed to `each` once it is up."""
        pg.evaluate("closeOv(); closeEditor(); closeDrawer()")
        pg.wait_for_timeout(300)
        each("the list")
        pg.evaluate("select(st.view[0].id)")
        pg.wait_for_timeout(700)
        each("the reader")
        pg.click("#rwmode button[data-v=edit]")
        pg.wait_for_timeout(500)
        each("the editor")
        pg.evaluate("closeEditor()")
        pg.wait_for_timeout(400)
        pg.click("#bMore")
        pg.wait_for_timeout(500)
        each("the ⋯ sheet")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        pg.click("#bFilters")
        pg.wait_for_timeout(500)
        each("the filters drawer")
        # the month (UI review slice 4, rule:month): the dot grid's days, the
        # arrows, the scales, and the chosen day's agenda under the grid with its rows
        pg.evaluate("closeDrawer()")
        pg.wait_for_timeout(300)
        pg.evaluate("calOpen('month', dayKey(st.all[0].created_at_utc))")
        pg.wait_for_timeout(500)
        each("the month")
        pg.evaluate("document.querySelector('.mag').scrollIntoView()")
        pg.wait_for_timeout(300)
        each("the month's agenda")
        # the week and the day (the design pass's slice 4, rule:weekday): the
        # month's strip for seven days, the chosen day's agenda, the day's free rows
        pg.evaluate("calOpen('week', dayKey(st.all[0].created_at_utc))")
        pg.wait_for_timeout(500)
        each("the week")
        pg.evaluate("document.querySelector('.mag').scrollIntoView()")
        pg.wait_for_timeout(300)
        each("the week's agenda")
        pg.evaluate("calOpen('day', dayKey(st.all[0].created_at_utc))")
        pg.wait_for_timeout(500)
        each("the day")
        pg.evaluate("document.querySelector('.mag').scrollIntoView()")
        pg.wait_for_timeout(300)
        each("the day's agenda")
        # the day's free runs opened into an hour a row (calDayUnfold), every
        # one of them a target, on a day ahead with nothing in it
        pg.evaluate("""() => { let d = calShiftDays(calToday(), 9);
            while ((calIndex().get(d) || []).length || (calSchedIndex().get(d) || []).length) d = calShiftDays(d, 1);
            calOpen('day', d); calDayUnfold(0, 24); document.querySelector('.mag').scrollIntoView(); }""")
        pg.wait_for_timeout(400)
        each("the day's hours")
        pg.evaluate("closeOv()")
        pg.wait_for_timeout(300)
        # select mode (the design pass's slice 5, rule:select): the bar's
        # All and Done, and the four actions in the list's foot
        pg.evaluate("pickMode(true); pickToggle(st.view[0].id); pickToggle(st.view[1].id)")
        pg.wait_for_timeout(400)
        each("select mode")
        pg.evaluate("pickMode(false)")
        pg.wait_for_timeout(300)
        # the rest of the views, as axe.py walks them on the desk (slice G):
        # each opened by the function its button calls, at the phone's size
        for name, js, ms, up in VIEWS:
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            pg.evaluate("closeOv(); closeEditor(); closeDrawer()")
            pg.wait_for_timeout(300)
            pg.evaluate(js)
            pg.wait_for_timeout(ms)
            ok(pg.evaluate("""q => { const e = document.querySelector(q), r = e && e.getBoundingClientRect();
                 return !!r && r.width > 0 && r.height > 0 && !!document.elementFromPoint(r.left + r.width / 2,
                   Math.min(innerHeight - 1, r.top + 2))?.closest(q); }""", up),
               f"{name} is up at {pg.viewport_size['width']}px ({up} shown, on top)")
            if name == "Tasks":
                # the design pass's slice 2: every row's tick a 44px target of
                # its own, the row's open button beside it never under it
                tk = pg.evaluate("""() => [...document.querySelectorAll('#tkrows .tktick')].slice(0, 12).map(b => {
                    const r = b.getBoundingClientRect(), o = b.closest('.tkrow').querySelector('.tkopen').getBoundingClientRect();
                    return [Math.round(r.width), Math.round(r.height), r.right <= o.left + 0.5]; })""")
                ok(tk and all(w >= 44 and h >= 44 and apart for w, h, apart in tk),
                   f"Tasks: each row's tick is 44px each way, apart from the row's open button ({tk[:3]})")
            each(name)
        pg.evaluate("closeOv(); closeEditor()")
        pg.wait_for_timeout(300)

    pills = pg.evaluate("""() => [...document.querySelectorAll('header .pill')]
        .filter(b => b.getBoundingClientRect().width > 0).map(b => [b.id, b.getBoundingClientRect().height])""")
    ok(pills and all(h >= 44 for _, h in pills), f"the header's pills are 44px tall: {pills}")

    def phone(name):
        if name == "the list":
            listrow(pg, 390)
        if name == "the reader":
            ok(pg.locator("#rd_content button.task").count() >= 3 and pg.locator("#rd_content .fbtn").count() >= 1,
               "the reader shows the outline's toggles and a fold caret")
        if name == "the week":
            ok(pg.locator(".calstrip .mcd[data-d]").count() == 7 and pg.locator(".calstrip .mcd.sel").count() == 1
               and pg.locator(".calwk").count() == 0,
               "the week is the strip of seven days, the chosen one lit, no columns")
        if name == "the day's agenda":
            ok(pg.locator(".mag .magfree").count() >= 1 and pg.locator(".calday").count() == 0,
               "the day folds its empty hours into free rows, no hour slots")
        if name == "the day's hours":
            ok(pg.locator(".mag .magfree:not(.fold)").count() == 24,
               "a whole free day opened is 24 rows, an hour each")
        if name == "the month":
            ok(pg.locator(".mag .magr").count() >= 1 and pg.locator(".mcd.sel").count() == 1,
               "the month shows the chosen day lit and its agenda's rows")
        screen(name)
    walk(phone)

    # rule:reflow (ui-rules.md, "Reflow at 320px", WCAG 1.4.10): the same
    # screens at 320 CSS px, the page never wider than the screen
    pg.set_viewport_size({"width": 320, "height": 640})
    pg.wait_for_timeout(500)

    def reflow(name):
        if name == "the list":
            listrow(pg, 320)
        w = pg.evaluate("""() => { const e = document.scrollingElement;
            const wide = [...document.querySelectorAll('body *')].filter(x => {
              const r = x.getBoundingClientRect(); return r.width > 0 && r.right > innerWidth + 1
                && getComputedStyle(x).position !== 'fixed' && !x.closest('[style*="display: none"]'); })
              .slice(0, 3).map(x => (x.id ? '#' + x.id : x.tagName.toLowerCase() + '.' + x.className).slice(0, 40));
            return [e.scrollWidth, innerWidth, wide]; }""")
        ok(w[0] <= w[1], f"{name} at 320px: no sideways scroll (page {w[0]}px wide{', past the edge: ' + ', '.join(w[2]) if w[0] > w[1] else ''})")
    walk(reflow)
    ok(not errs, f"no page errors: {errs}")

    # rule:casing and rule:dots at every width: the desk's list, reader,
    # editor and month, with the filters column beside them
    dctx = b.new_context(viewport={"width": 1280, "height": 800})
    dctx.route(perf.BASE + "/**", perf.serve(rows))
    dctx.add_init_script("localStorage.setItem('lcars.cfg', JSON.stringify({base:'%s',user:'u',pass:'p'}));" % perf.BASE)
    pg = dctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(perf.PAGE)
    pg.wait_for_selector("#list .item")
    pg.wait_for_timeout(1000)
    casedots("the desk's list")
    pg.evaluate("select(st.view[0].id)")
    pg.wait_for_timeout(700)
    casedots("the desk's reader")
    pg.click("#rwmode button[data-v=edit]")
    pg.wait_for_timeout(500)
    casedots("the desk's editor")
    pg.evaluate("closeEditor(); calOpen('month', dayKey(st.all[0].created_at_utc))")
    pg.wait_for_timeout(500)
    casedots("the desk's month")
    ok(not errs, f"no page errors on the desk: {errs}")
    b.close()

print(f"targets: {len(fails)} failures")
sys.exit(1 if fails else 0)
