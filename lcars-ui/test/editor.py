#!/usr/bin/env python3
"""The entry editor in Chromium, at a phone's size and a desktop's.

    python3 test/editor.py          (~40s; LCARS_TEST_BIN=<binary> skips the build)

docs/design/editor.md's proposals, as built, against a scratch server on an
empty journal the test fills (nothing here touches lcars.db):

- the bar (P1, P5): at 390px it is Dictate, Video and ⋯, no hidden
  button shows, and ⋯ is a sheet of the rest,
  Chat on a crew entry only, Delete last; a desktop's bar is ranked the
  same (research slice C): one primary action, the rest in the sheet;
  and the desk reads at the body's size (rule:deskread);
- leaving saves (P2): every door out of an edited entry leaves at once and
  the text reaches the server, with no browser question; a failed save marks
  the row and keeps the text; the save chip (P4) in every state;
- Details (P6): one shut fold that reads as a line, a chip per column in
  words opening its own picker, Number for a reading kind, Done by a task's
  title, the deleted toggle and the last-modified field gone;
- the top (P7): the title in the reader's face, the kind a chip under it
  that opens the picker, a new entry's kinds one scrolling row;
- a new entry (P8): + focuses the box in the tap, the chip says Write
  something first, words autosave (the row, the url) and leave with it,
  a copy waits for an edit;
- the reader (P9): a tap on its text is the editor with the caret at the
  word, but not on a task box, a fold, after a selection or a scroll;
- Escape (P13): the first saves and lets go, letters after it do nothing
  for a second, e is back in, a second Escape reads.
"""
import json
import os
import pathlib
import shutil
import sys
import urllib.request
import uuid
import killclean  # its scratch goes when the run is killed

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import offline as rig  # the scratch build and server  # noqa: E402

UI = rig.UI
check, fails, checks = rig.check, rig.fails, rig.checks


def create(srv, body):
    """POST /entries with a key of its own. The phone's and the desktop's
    rows are the same bodies, made within a second: keyless, the server's
    twin guard (HandlePostEntryDeduped) folds each desktop one into the
    phone's, and the desktop half then reads the rows the phone half
    changed. A keyed create is never a twin."""
    rq = urllib.request.Request(srv.base + "/entries", data=json.dumps(body).encode(), method="POST",
                                headers={"Authorization": rig.AUTH, "Content-Type": "application/json",
                                         "Idempotency-Key": "editor-" + uuid.uuid4().hex})
    with urllib.request.urlopen(rq, timeout=10) as r:
        return json.loads(r.read())["id"]


def make(srv, kind, title, content):
    return create(srv, {"kind": kind, "title": title, "content": content})


def visible_ids(page, box):
    return page.evaluate("""box => [...document.querySelectorAll(box + ' button')]
      .filter(b => b.offsetParent && getComputedStyle(b).display !== 'none').map(b => b.id)""", box)


def shown_hidden(page):
    """Every element carrying `hidden` that a stylesheet shows anyway."""
    return page.evaluate("""() => [...document.querySelectorAll('[hidden]')]
      .filter(e => getComputedStyle(e).display !== 'none')
      .map(e => e.id || e.className || e.tagName)""")


def edit(page, eid, text):
    """Open an entry, switch to the editor and type into it, as a person does."""
    page.evaluate(f"select({eid})")
    page.click("#rwmode button[data-v=edit]")
    page.fill("#content", text)
    page.wait_for_timeout(50)


def server_text(srv, eid):
    return srv.json("GET", f"/entries/{eid}")["content"]


def settle(page, srv, eid, text, what):
    for _ in range(40):
        if server_text(srv, eid) == text:
            break
        page.wait_for_timeout(100)
    check(server_text(srv, eid) == text, f"{what}: the text reached the server")


# Click a selector and, in the same task (the same frame), read what shows.
SAME_FRAME = """([sel, id]) => {
  document.querySelector(sel).click();
  const row = document.querySelector('#list .item[data-id="' + id + '"] .svmark');
  return { pane: document.body.dataset.pane, mark: row ? row.textContent : '',
           title: (st.byId.get(id) || {}).content };
}"""


def doors(page, srv, ids, dialogs, phone):
    tag = "phone" if phone else "desktop"
    eid = ids["log"]
    n0 = len(dialogs)

    # ‹ List (✕ on the desktop): out at once, the row saying saving…
    edit(page, eid, f"{tag} list door")
    sel = "#bBack" if phone else "#bClose"
    got = page.evaluate(SAME_FRAME, [sel, eid])
    check(got["pane"] == "list", f"{tag}: {sel} leaves in the tap  ({got['pane']})")
    check(got["title"] == f"{tag} list door", f"{tag}: the row holds the new text at once")
    check("saving" in got["mark"], f"{tag}: the row says saving… in the same frame  ({got['mark']!r})")
    settle(page, srv, eid, f"{tag} list door", f"{tag} {sel}")
    page.wait_for_timeout(200)
    mark = page.evaluate(f"(document.querySelector('#list .item[data-id=\"{eid}\"] .svmark') || {{}}).textContent || ''")
    check(mark == "", f"{tag}: then the row says nothing  ({mark!r})")

    # Back (the browser's): the same
    edit(page, eid, f"{tag} back door")
    page.go_back(wait_until="commit")
    page.wait_for_timeout(150)
    check(page.evaluate("document.body.dataset.pane") == "list", f"{tag}: Back leaves at once")
    settle(page, srv, eid, f"{tag} back door", f"{tag} Back")

    # another row
    edit(page, eid, f"{tag} row door")
    if phone:
        page.go_back(wait_until="commit")           # the phone's list is under the editor
        page.wait_for_timeout(150)
        settle(page, srv, eid, f"{tag} row door", f"{tag} Back before another row")
    else:
        page.click(f"#list .item[data-id=\"{ids['other']}\"]")
        page.wait_for_timeout(100)
        check(page.evaluate("st.sel && st.sel.id") == ids["other"], f"{tag}: another row opens at once")
        settle(page, srv, eid, f"{tag} row door", f"{tag} another row")

    # Duplicate from the sheet / the row: a copy opens, the original is saved
    edit(page, eid, f"{tag} dup door")
    # the sheet at every width since research slice C
    page.click("#bEdMore")
    page.click("#dlg .shtile >> text=Duplicate")
    page.wait_for_timeout(100)
    check(page.evaluate("st.isNew"), f"{tag}: Duplicate opens the copy at once")
    settle(page, srv, eid, f"{tag} dup door", f"{tag} Duplicate")
    page.evaluate("setClean(); closeEditor()")

    check(len(dialogs) == n0, f"{tag}: no browser question on any door  ({dialogs[n0:]})")

    # the chip: Editing while typing, Saving… in the tap's frame, then Saved
    edit(page, eid, f"{tag} chip")
    chip = "#edchip2" if phone else "#edchip"
    check(page.is_visible(chip), f"{tag}: the chip is on screen ({chip})")
    if phone:
        check(page.evaluate("(() => { const r = document.querySelector('#edchip2').getBoundingClientRect(),"
                            " c = document.querySelector('#content').getBoundingClientRect();"
                            " return r.bottom <= c.top + 2 && c.top - r.bottom < 40; })()"),
              "phone: the chip rides on the content label's line, over the text")
    check(page.text_content(chip).strip() == "● Editing", f"{tag}: the chip says Editing  ({page.inner_text(chip)!r})")
    face = page.evaluate(f"""() => {{ document.querySelector('{chip}').click();
      return document.querySelector('{chip}').textContent; }}""")
    check(face == "Saving…", f"{tag}: a tap is Saving… in the same frame  ({face!r})")
    settle(page, srv, eid, f"{tag} chip", f"{tag} the chip's tap")
    page.wait_for_function(f"document.querySelector('{chip}').dataset.s === 'saved'")
    check(True, f"{tag}: then ✓ Saved")
    page.wait_for_function(f"document.querySelector('{chip}').dataset.s === 'idle'", timeout=4000)
    check(page.text_content(chip).strip() == "Saved", f"{tag}: and Saved, dim")

    # Read with unsaved text: the reader at once, the chip carries the save
    edit(page, eid, f"{tag} read door")
    page.click("#rwmode button[data-v=read]")
    check(page.evaluate("st.read && document.querySelector('#readbody').style.display === 'block'"),
          f"{tag}: Read switches at once")
    settle(page, srv, eid, f"{tag} read door", f"{tag} Read")

    # Revert: an Undo in the toast
    page.click("#rwmode button[data-v=edit]")
    page.fill("#content", f"{tag} reverted words")
    page.click("#bEdMore")
    page.click("#dlg .shtile >> text=Revert")
    check(page.input_value("#content") == f"{tag} read door", f"{tag}: Revert restores the text")
    page.click("#toast .tact >> text=Undo")
    check(page.input_value("#content") == f"{tag} reverted words", f"{tag}: Undo brings the edit back")
    page.evaluate("setClean(); closeEditor()")


def popups(page, ids, phone):
    tag = "phone" if phone else "desktop"
    page.evaluate(f"select({ids['tagged']})")
    page.click("#rwmode button[data-v=edit]")
    page.click("#content")
    page.keyboard.press("Control+End")
    page.keyboard.type(" #walking")
    page.wait_for_timeout(100)
    check(page.evaluate("!!(wac && wac.mode === 'tag')"), f"{tag}: the tag popup is open on a complete #walking")
    page.keyboard.press("Enter")
    page.keyboard.type("next")
    v = page.input_value("#content")
    check(v.endswith(" #walking\nnext"), f"{tag}: Enter after it breaks the line  ({v[-24:]!r})")
    page.keyboard.press("Enter")
    page.keyboard.type("/")
    page.wait_for_timeout(100)
    rows = page.eval_on_selector_all("#wikiac .wac .wacn", "rs => rs.map(r => r.textContent)")
    check(rows[:6] == ["/todo", "/log", "/now", "/day", "/time", "/location"],
          f"{tag}: a bare / leads with todo, log, now, day, time, location  ({rows[:6]})")
    help_shown = page.evaluate("(() => { const h = document.querySelector('#wikiac .wach');"
                               " return !!h && getComputedStyle(h).display !== 'none'; })()")
    check(help_shown == (not phone), f"{tag}: the key help {'is hidden' if phone else 'shows'}")
    page.keyboard.press("Escape")
    page.evaluate("setClean(); closeEditor()")


def details(page, srv, ids, phone):
    """P6: the columns under one Details fold, in words."""
    tag = "phone" if phone else "desktop"
    ids = ids[tag]
    page.evaluate(f"select({ids['log']})")
    page.click("#rwmode button[data-v=edit]")
    page.wait_for_timeout(100)
    check(not page.evaluate("document.querySelector('#eddet').open"), f"{tag}: Details is shut")
    # each fact its own span (ui-rules.md, "Words": no middle-dot string)
    facts = lambda: page.evaluate("[...document.querySelectorAll('#eddet_sum > span')].map(s => s.textContent)")
    summ = facts()
    check(page.is_visible("#eddet_sum") and summ[0].startswith("Written ") and summ[1:] == ["open", "unscheduled"]
          and "·" not in page.inner_text("#eddet_sum"),
          f"{tag}: the shut fold reads as a line  ({summ!r})")
    h = page.evaluate("document.querySelector('#edbody').scrollHeight")
    vh = page.evaluate("innerHeight")
    check(h <= vh * 1.25, f"{tag}: the form is about a screen, not three  ({h}px in {vh})")
    for gone in ("#tog_del", "#lm_note"):
        check(page.query_selector(gone) is None, f"{tag}: {gone} is gone (Delete/Restore is the way)")
    check(page.get_attribute("#e_last_modified_at_utc", "type") == "hidden",
          f"{tag}: last changed is not a field")
    page.click("#eddet summary")
    check(page.is_visible("#ed_lm") and page.inner_text("#ed_lm").strip() not in ("", "—"),
          f"{tag}: Last changed is plain text  ({page.inner_text('#ed_lm')!r})")
    check(not page.is_visible(".dtpick"), f"{tag}: every picker shut when Details opens")
    check("created_at_utc" in (page.get_attribute("#dc_dt", "title") or ""),
          f"{tag}: the UTC column name is in the tooltip")
    got = page.evaluate("""() => { document.querySelector('#dc_dt').click();
      return [document.querySelector('#dc_dt').classList.contains('on'),
              !document.querySelector('.dpane[data-dp=dt]').hidden]; }""")
    check(got == [True, True], f"{tag}: Written opens its picker in the tap  ({got})")
    check(page.inner_text("#dc_sd").strip() == "Add a time", f"{tag}: Scheduled says Add a time")
    page.click("#dc_sd")
    shown = page.evaluate("[...document.querySelectorAll('.dpane')].filter(p => !p.hidden).map(p => p.dataset.dp)")
    check(shown == ["sd"], f"{tag}: one picker open, the one tapped  ({shown})")
    page.click(".dpane[data-dp=sd] button[data-off='60']")
    check(page.input_value("#e_start_date") != "", f"{tag}: the picker schedules it")
    summ = facts()
    check("unscheduled" not in summ and summ[1:2] == ["open"], f"{tag}: the line follows  ({summ!r})")
    check(page.is_visible("#dc_ed") and page.inner_text("#dc_ed").strip() == "add an end",
          f"{tag}: an end can be added")
    check(not page.is_visible("#ednum"), f"{tag}: no Number on a kind without readings")
    page.click("#edchip2" if phone else "#edchip")
    for _ in range(40):
        if srv.json("GET", f"/entries/{ids['log']}")["start_date"]:
            break
        page.wait_for_timeout(100)
    check(srv.json("GET", f"/entries/{ids['log']}")["start_date"] != "", f"{tag}: the schedule is saved")
    page.wait_for_timeout(300)
    # a kind with readings: one Number, value_float underneath
    page.evaluate(f"select({ids['weight']}); setRead(false)")
    page.wait_for_timeout(100)
    if not page.evaluate("document.querySelector('#eddet').open"):
        page.click("#eddet summary")
    check(page.is_visible("#ednum") and page.input_value("#e_num") == "72.5",
          f"{tag}: a reading kind shows its Number  ({page.input_value('#e_num')!r})")
    page.fill("#e_num", "73.25")
    page.click("#edchip2" if phone else "#edchip")
    for _ in range(40):
        if srv.json("GET", f"/entries/{ids['weight']}")["value_float"] == 73.25:
            break
        page.wait_for_timeout(100)
    check(srv.json("GET", f"/entries/{ids['weight']}")["value_float"] == 73.25,
          f"{tag}: the Number is value_float on the server")
    page.wait_for_timeout(300)
    # a task kind: Done is also a chip by the title
    page.evaluate(f"select({ids['task']}); setRead(false)")
    page.wait_for_timeout(100)
    check(page.is_visible("#eddone"), f"{tag}: a task has a Done chip by the title")
    face = page.evaluate("""() => { document.querySelector('#eddone').click();
      return [document.querySelector('#eddone').textContent, document.body.classList.contains('dirty')]; }""")
    check(face[0].endswith("Done") and face[1], f"{tag}: the chip turns Done in the tap  ({face})")
    page.click("#edchip2" if phone else "#edchip")
    for _ in range(40):
        if srv.json("GET", f"/entries/{ids['task']}")["done_bool"]:
            break
        page.wait_for_timeout(100)
    check(srv.json("GET", f"/entries/{ids['task']}")["done_bool"] == 1, f"{tag}: and done reaches the server")
    page.wait_for_timeout(300)
    page.evaluate(f"select({ids['log']})")
    check(not page.is_visible("#eddone"), f"{tag}: no Done chip on a log")
    page.evaluate("setClean(); closeEditor()")


def top(page, srv, ids, phone):
    """P7: the editor's top is the reader's - the title a heading, the kind a chip."""
    tag = "phone" if phone else "desktop"
    ids = ids[tag]
    page.evaluate(f"select({ids['kindy']})")
    page.wait_for_timeout(100)
    read_face = page.evaluate("""() => { const t = getComputedStyle(document.querySelector('#rd_title'));
      return [t.fontFamily, t.fontSize, document.querySelector('#rd_title').getBoundingClientRect().top]; }""")
    page.click("#rwmode button[data-v=edit]")
    page.wait_for_timeout(100)
    ed_face = page.evaluate("""() => { const t = getComputedStyle(document.querySelector('#e_head'));
      return [t.fontFamily, t.fontSize, document.querySelector('#e_head').getBoundingClientRect().top,
              t.borderTopWidth, t.borderLeftWidth, t.backgroundColor]; }""")
    check(ed_face[:2] == read_face[:2], f"{tag}: the title is in the reader's face  ({ed_face[:2]} vs {read_face[:2]})")
    check(abs(ed_face[2] - read_face[2]) <= 16, f"{tag}: and where the reader has it  ({ed_face[2]} vs {read_face[2]})")
    check(ed_face[3] == "0px" and ed_face[4] == "0px", f"{tag}: borderless  ({ed_face[3:5]})")
    check(page.get_attribute("#e_kind", "type") == "hidden", f"{tag}: the full-width kind field is gone")
    # by its name, the slug in the tooltip (ui-rules.md, Words; slice A)
    check(page.is_visible("#edkind") and page.inner_text("#edkind").strip().lower().startswith("personal log")
          and "personal_log" in (page.get_attribute("#edkind", "title") or ""),
          f"{tag}: the kind is a chip, by its name  ({page.inner_text('#edkind')!r})")
    below = page.evaluate("""() => document.querySelector('#edkind').getBoundingClientRect().top >=
      document.querySelector('#e_head').getBoundingClientRect().bottom - 2""")
    check(below, f"{tag}: under the title, where the reader has its badge")
    got = page.evaluate("""() => { document.querySelector('#edkind').click();
      return [document.querySelector('#ov').classList.contains('on'), document.querySelector('#dlgh').textContent]; }""")
    check(got == [True, "Set the kind"], f"{tag}: a tap on it is the kind picker, in the tap  ({got})")
    page.fill("#pkq", "task")
    page.click("#pkrows .pkr >> nth=0")
    page.wait_for_timeout(100)
    check(page.input_value("#e_kind") == "task" and page.inner_text("#edkind").strip().lower().startswith("task"),
          f"{tag}: a row sets it and the chip says it")
    check(page.is_visible("#eddone"), f"{tag}: a task now has its Done chip")
    page.click("#edchip2" if phone else "#edchip")
    for _ in range(40):
        if srv.json("GET", f"/entries/{ids['kindy']}")["kind"] == "task":
            break
        page.wait_for_timeout(100)
    check(srv.json("GET", f"/entries/{ids['kindy']}")["kind"] == "task", f"{tag}: the new kind is saved")
    page.wait_for_timeout(300)
    page.evaluate("setClean(); closeEditor()")
    # a new entry: one kind control, the chip (UI review slice 6,
    # rule:one-control) - no row
    # of kind chips offering the same choice again under it
    page.evaluate("newEntry()")
    page.wait_for_timeout(100)
    kc = page.evaluate("""() => [[...document.querySelectorAll('#editpane .kc')].filter(c => !c.closest('#esug')).length,
      !!document.querySelector('#edkind') && document.querySelector('#edkind').offsetParent !== null]""")
    check(kc == [0, True], f"{tag}: a new entry's one kind control is the chip  (row chips, chip shown: {kc})")
    ctop = page.evaluate("document.querySelector('#content').getBoundingClientRect().top")
    check(ctop < 330, f"{tag}: the text box starts high on the screen  ({ctop}px; it was 372)")
    page.evaluate("setClean(); closeEditor()")


def rows_with(srv, text):
    got = srv.json("GET", "/entries")
    rows = got if isinstance(got, list) else got.get("entries", got.get("rows", []))
    return [r for r in rows if r.get("content") == text and not r.get("deleted")]


def drafts(page, srv, dialogs, phone):
    """P8: + is the keyboard up, never an empty row, then autosaved like any entry."""
    tag = "phone" if phone else "desktop"
    chip = "#edchip2" if phone else "#edchip"
    plus = "#lnew" if phone else "#bNew"     # the phone: New in the list's foot
    n0 = len(dialogs)
    got = page.evaluate(f"""() => {{ document.querySelector('{plus}').click();
      return [document.activeElement && document.activeElement.id, st.isNew,
              document.querySelector('{chip}').textContent]; }}""")
    check(got[0] == "content" and got[1], f"{tag}: + focuses the text box inside the tap  ({got[:2]})")
    check(got[2] == "Write something first", f"{tag}: an empty draft's chip says so  ({got[2]!r})")
    said = page.evaluate("""() => [...document.querySelectorAll('.edchip')]
      .filter(c => c.offsetParent !== null && c.textContent === 'Write something first').length""")
    check(said == 1, f"{tag}: \"Write something first\" is on screen once  ({said})")
    page.click(chip)
    page.wait_for_timeout(3600)
    check(page.evaluate("st.isNew") and page.evaluate("document.activeElement.id") == "content",
          f"{tag}: its tap saves nothing, and leaves the caret in the box")
    text = f"{tag} a draft of my own"
    page.keyboard.type(text)
    check(page.text_content(chip).strip() == "● Editing", f"{tag}: with words it is Editing  ({page.inner_text(chip)!r})")
    for _ in range(60):
        if rows_with(srv, text):
            break
        page.wait_for_timeout(100)
    made = rows_with(srv, text)
    check(len(made) == 1, f"{tag}: a pause creates the row  ({len(made)})")
    page.wait_for_timeout(300)
    if made:
        rid = made[0]["id"]
        try:
            page.wait_for_function(f"location.pathname.endsWith('/entry/{rid}')", timeout=3000)
        except Exception:
            pass
        check(page.url.endswith(f"/entry/{rid}"), f"{tag}: the url becomes ./entry/{rid}  ({page.url})")
        check(page.is_visible(f"#list .item[data-id=\"{rid}\"]") or phone,
              f"{tag}: the list has the row")
        check(page.evaluate(f"st.byId.has({rid}) && !st.isNew && st.sel.id === {rid}"), f"{tag}: the editor is that row")
        check(page.evaluate("document.activeElement.id") == "content", f"{tag}: and the caret never left")
        page.keyboard.type(" and on")
        for _ in range(60):
            if rows_with(srv, text + " and on"):
                break
            page.wait_for_timeout(100)
        check(len(rows_with(srv, text + " and on")) == 1 and not rows_with(srv, text),
              f"{tag}: then it autosaves as an update, one row")
    page.wait_for_timeout(300)
    page.evaluate("closeEditor()")

    # leaving a new entry with words: out at once, created on the way
    page.click(plus)
    text = f"{tag} written and left"
    page.keyboard.type(text)
    door = "#bBack" if phone else "#bClose"
    pane = page.evaluate(f"() => {{ document.querySelector('{door}').click(); return document.body.dataset.pane; }}")
    check(pane == "list", f"{tag}: a door out of a new entry opens in the tap  ({pane})")
    for _ in range(60):
        if rows_with(srv, text):
            break
        page.wait_for_timeout(100)
    check(len(rows_with(srv, text)) == 1, f"{tag}: and its words were saved on the way")
    check(len(dialogs) == n0, f"{tag}: no browser question  ({dialogs[n0:]})")

    # a scaffold keeps today's rule: nothing written until an edit or Save
    src = rows_with(srv, text)[0]["id"] if rows_with(srv, text) else None
    if src:
        page.wait_for_function(f"st.byId.has({src})")
        page.evaluate(f"select({src}); duplicate()")
        page.wait_for_timeout(3600)
        check(len(rows_with(srv, text)) == 1, f"{tag}: a copy is not written by a pause")
        check(page.text_content(chip).strip() == "● Save new", f"{tag}: its chip asks for the Save  ({page.inner_text(chip)!r} {page.evaluate('[st.touched, st.scaffold, st.isNew]')})")
        page.evaluate("closeEditor()")
        page.wait_for_timeout(500)
        check(len(rows_with(srv, text)) == 1, f"{tag}: nor by leaving it untouched")
        check("not kept" in page.inner_text("#toast"), f"{tag}: the toast says it was not kept  ({page.inner_text('#toast')!r})")
    page.wait_for_timeout(200)


WORD_AT = """([sel, word]) => {
  const root = document.querySelector(sel);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    const i = n.nodeValue.indexOf(word);
    if (i < 0) continue;
    const r = document.createRange();
    r.setStart(n, i + 1); r.setEnd(n, i + 2);
    const b = r.getBoundingClientRect();
    return [b.left + b.width / 2, b.top + b.height / 2];
  }
  return null;
}"""


def reader_tap(page, srv, ids, phone):
    """P9: one tap on the reader's text edits, the caret at the word; P13: Escape lets go first."""
    tag = "phone" if phone else "desktop"
    ids = ids[tag]
    eid = ids["outline"]
    src = srv.json("GET", f"/entries/{eid}")["content"]

    def open_reader():
        page.evaluate(f"setClean(); select({eid}); setRead(true)")
        page.wait_for_timeout(450)       # the phone's layer slides in (.2s), the reader fades in

    def tap(x, y):
        if phone:
            page.touchscreen.tap(x, y)
        else:
            page.mouse.click(x, y)

    open_reader()
    xy = page.evaluate(WORD_AT, ["#rd_content", "heron"])
    tap(*xy)
    got = page.evaluate("[st.read, document.activeElement.id, document.querySelector('#content').selectionStart]")
    want = src.index("heron")
    check(got[0] is False and got[1] == "content", f"{tag}: a tap on the reader's text opens the editor, focused  ({got[:2]})")
    # within the word: a touch's tap is adjusted, and may land at its end
    check(want <= got[2] <= want + len("heron"), f"{tag}: the caret at the tapped word  ({got[2]} in {want}-{want + 5})")

    # what keeps its own meaning
    for what, sel in (("a task box", "#rd_content button.task"), ("a fold", "#rd_content .fbtn")):
        open_reader()
        el = page.query_selector(sel)
        check(el is not None, f"{tag}: the outline has {what}")
        if el:
            page.evaluate("s => document.querySelector(s).click()", sel)
            page.wait_for_timeout(100)
            check(page.evaluate("st.read && st.sel.id") == eid, f"{tag}: {what} keeps its meaning, the reader stays")
            page.wait_for_timeout(1000)       # the task box writes the entry: let it land
            page.evaluate(f"setClean(); select({eid})")
    open_reader()
    page.evaluate("""() => { const p = document.querySelector('#rd_content p, #rd_content li');
      const r = document.createRange(); r.selectNodeContents(p); getSelection().removeAllRanges(); getSelection().addRange(r); }""")
    xy = page.evaluate(WORD_AT, ["#rd_content", "heron"])
    page.evaluate("([x, y]) => document.elementFromPoint(x, y).dispatchEvent(new MouseEvent('click', {bubbles: true, clientX: x, clientY: y}))", xy)
    check(page.evaluate("st.read"), f"{tag}: a tap that ends a selection does not edit")
    page.evaluate("getSelection().removeAllRanges()")
    page.evaluate("rdScrollAt = Date.now()")
    page.evaluate("([x, y]) => document.elementFromPoint(x, y).dispatchEvent(new MouseEvent('click', {bubbles: true, clientX: x, clientY: y}))", xy)
    check(page.evaluate("st.read"), f"{tag}: nor one that stops a scroll")

    # P13: Escape saves and lets go, a second Escape reads
    page.evaluate(f"setClean(); select({eid}); setRead(false)")
    page.click("#content")
    page.keyboard.press("Control+End")
    page.keyboard.type(" esc")
    page.keyboard.press("Escape")
    got = page.evaluate("[st.read, document.activeElement && document.activeElement.id, document.body.dataset.pane,"
                        " !document.querySelector('#eschint').hidden]")
    check(got[0] is False and got[1] != "content" and got[2] == "edit",
          f"{tag}: the first Escape lets go of the text and stays in the editor  ({got[:3]})")
    check(got[3], f"{tag}: saying press e to type")
    page.keyboard.type("hello")
    got = page.evaluate(f"[st.read, st.isNew, st.sel && st.sel.id, document.querySelector('#content').value.endsWith(' esc')]")
    check(got == [False, False, eid, True], f"{tag}: letters straight after it do nothing  ({got})")
    for _ in range(40):
        if srv.json("GET", f"/entries/{eid}")["content"].endswith(" esc"):
            break
        page.wait_for_timeout(100)
    check(srv.json("GET", f"/entries/{eid}")["content"].endswith(" esc"), f"{tag}: that Escape saved")
    page.wait_for_timeout(1100)
    page.keyboard.press("e")
    check(page.evaluate("document.activeElement.id") == "content", f"{tag}: then e is back into the text")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    check(page.evaluate("st.read"), f"{tag}: and Escape twice reads")
    page.evaluate("setClean(); closeEditor()")


def run(p, srv, ids):
    browser = p.chromium.launch(headless=True)
    cfg = {"base": srv.base, "user": rig.USER, "pass": rig.PASS}
    init = ("if (!localStorage.getItem('lcars.cfg')) "
            f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")

    def open_page(vw, vh, mobile):
        ctx = browser.new_context(viewport={"width": vw, "height": vh},
                                  is_mobile=mobile, has_touch=mobile)
        ctx.set_default_timeout(20000)
        ctx.add_init_script(init)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        dialogs = []

        def on_dialog(d):
            dialogs.append(d.message)
            d.dismiss()
        page.on("dialog", on_dialog)
        page.goto(srv.base + "/ui/", wait_until="domcontentloaded")
        page.wait_for_function("typeof st !== 'undefined' && !st.loading && st.all.length >= 4")
        page.wait_for_timeout(400)
        return page, errs, dialogs

    # ---- the phone ----
    page, errs, dialogs = open_page(390, 844, True)
    page.evaluate(f"select({ids['log']})")
    page.wait_for_timeout(200)
    bar = visible_ids(page, "#edactions")
    check("bCrewChat" not in bar, f"phone, the captain's entry: no Chat on the bar  (bar {bar})")
    for gone in ("bRevert", "bDup", "bCont", "bDel"):
        check(gone not in bar, f"phone: {gone} is in the ⋯ sheet, not on the bar")
    check(bar == ["bMic", "bVid", "bEdMore"], f"phone bar: Dictate, Video, ⋯  (got {bar})")
    # Dictate the primary action (UI review slice 6): the wide, lit segment
    lit = page.evaluate("""() => { const m = document.querySelector('#bMic'), v = document.querySelector('#bVid');
      return [Math.round(m.getBoundingClientRect().width), Math.round(v.getBoundingClientRect().width),
              getComputedStyle(m).backgroundColor, getComputedStyle(v).backgroundColor]; }""")
    check(lit[0] > 1.5 * lit[1] and lit[2] != lit[3],
          f"phone bar: Dictate is the wide, lit segment  (widths {lit[0]}/{lit[1]}, {lit[2]} vs {lit[3]})")
    sh = shown_hidden(page)
    check(not sh, f"phone: nothing hidden is shown  (got {sh})")
    page.click("#bEdMore")
    tiles = page.eval_on_selector_all("#dlg .shtile", "ts => ts.map(t => t.textContent)")
    check(page.is_visible("#dlg .shtile"), "⋯ opens the sheet in the tap")
    check(not any("Chat" in t for t in tiles), f"no Chat tile on the captain's entry  ({tiles})")
    check(tiles and "Delete" in tiles[-1], f"Delete is the last tile  ({tiles})")
    page.click("#edMoreClose")
    page.evaluate(f"select({ids['crew']})")
    page.wait_for_timeout(200)
    check("bCrewChat" not in visible_ids(page, "#edactions"), "a crew entry's Chat is not on the phone bar either")
    page.click("#bEdMore")
    tiles = page.eval_on_selector_all("#dlg .shtile", "ts => ts.map(t => t.textContent)")
    check(any("Chat" in t for t in tiles), f"…it is a tile in its ⋯ sheet  ({tiles})")
    # a tile presses the real button: Duplicate starts the copy
    page.click("#dlg .shtile >> text=Duplicate")
    page.wait_for_timeout(200)
    check(page.evaluate("st.isNew"), "the Duplicate tile starts a copy")
    for v in ("tasks", "media"):
        page.evaluate(f"ROUTES['{v}'] && ROUTES['{v}'].open([])")
        page.wait_for_timeout(300)
        sh = shown_hidden(page)
        check(not sh, f"phone, {v} open: nothing hidden is shown  (got {sh})")
        page.evaluate("closeOv()")
    page.evaluate("setClean(); closeEditor()")
    # the box is taller than the room an iPhone's keyboard leaves (at most
    # ~64% of the screen in portrait): WebKit centres a focused field that
    # fits there, which put the tapped line under the status bar (editor.md,
    # "The caret under the top")
    page.evaluate(f"select({ids['log']}); setRead(false)")
    page.wait_for_timeout(200)
    box = page.evaluate("[document.querySelector('#content').getBoundingClientRect().height, innerHeight]")
    check(box[0] > 0.65 * box[1], f"phone: the body's box is taller than the room above the keys  ({box})")
    page.evaluate("setClean(); closeEditor()")
    doors(page, srv, ids, dialogs, phone=True)
    popups(page, ids, phone=True)
    details(page, srv, ids, phone=True)
    top(page, srv, ids, phone=True)
    drafts(page, srv, dialogs, phone=True)
    reader_tap(page, srv, ids, phone=True)
    check(not errs, f"phone: no page errors  ({errs[:3]})")
    page.context.close()

    # ---- the desktop ----
    page, errs, dialogs = open_page(1280, 860, False)
    page.evaluate(f"select({ids['log']}); setRead(false)")
    page.wait_for_timeout(200)
    bar = visible_ids(page, "#edactions")
    # rule:one-control at every width (research slice C; the analysis of
    # 0.321.0, finding 3: the desk's bar was fifteen buttons of one weight,
    # Delete cut off at 1280): Dictate, Video, ⋯, as on the phone
    check(bar == ["bMic", "bVid", "bEdMore"], f"desktop bar: Dictate, Video, ⋯  (got {bar})")
    ws = page.evaluate("""() => [...document.querySelectorAll('#edactions button')]
      .filter(b => b.offsetParent && getComputedStyle(b).display !== 'none')
      .map(b => Math.round(b.getBoundingClientRect().width)).sort((a, b) => b - a)""")
    one = len(ws) > 1 and ws[0] > 1.5 * ws[len(ws) // 2] and ws[1] <= 1.5 * ws[len(ws) // 2]
    lit = page.evaluate("[getComputedStyle(document.querySelector('#bMic')).backgroundColor,"
                        " getComputedStyle(document.querySelector('#bVid')).backgroundColor]")
    check(one and lit[0] != lit[1], f"desktop bar: one primary action, Dictate lit and wider than the rest  (widths {ws}, {lit})")
    hb = visible_ids(page, "#edhead")
    check("bShare" not in hb, f"desktop head: Share is in the ⋯ sheet, not the head  (got {hb})")
    page.click("#bEdMore")
    tiles = page.eval_on_selector_all("#dlg .shtile", "ts => ts.map(t => t.textContent)")
    check(all(any(w in t for t in tiles) for w in ("Duplicate", "Continue", "Pin", "Share", "Revert"))
          and "Delete" in tiles[-1], f"desktop: ⋯ holds the rest, Delete last  ({tiles})")
    page.click("#edMoreClose")
    # rule:deskread: the desk reads at the body's size (research slice C):
    # a row's title and text and the reader's text at --fs-body, the row's
    # kind and time at --fs-meta, and the head's badge not cut to "PERS…"
    fs = page.evaluate("""() => { const f = q => { const e = document.querySelector(q);
        return e ? getComputedStyle(e).fontSize : null; };
      const vb = [...document.querySelectorAll('#edtitle > *')].filter(e => e.getBoundingClientRect().width > 0).length;
      return { t: f('#list .item .t'), sn: f('#list .item .sn'), m: f('#list .item .m'),
               rd: f('#rd_content'), head: vb, body: getComputedStyle(document.documentElement).getPropertyValue('--fs-body').trim(),
               meta: getComputedStyle(document.documentElement).getPropertyValue('--fs-meta').trim() }; }""")
    check(fs["t"] == fs["body"] and fs["sn"] == fs["body"] and fs["m"] == fs["meta"],
          f"rule:deskread: a desk list row's title and text at --fs-body, its kind line at --fs-meta  ({fs})")
    page.evaluate("setRead(true)")
    page.wait_for_timeout(100)
    rd = page.evaluate("getComputedStyle(document.querySelector('#rd_content')).fontSize")
    check(rd == fs["body"], f"rule:deskread: the desk reader's text at --fs-body  ({rd})")
    # and the filters column (research slice E): no text in it under --fs-meta
    small = page.evaluate("""() => { const meta = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fs-meta'));
      return [...document.querySelectorAll('#side *')].filter(e => {
        const own = [...e.childNodes].some(n => n.nodeType === 3 && n.data.trim());
        return own && e.getBoundingClientRect().width > 0 && parseFloat(getComputedStyle(e).fontSize) < meta; })
        .slice(0, 6).map(e => (e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + e.className) + ' ' + getComputedStyle(e).fontSize); }""")
    check(not small, f"rule:deskread: the desk's filters column has no text under --fs-meta  ({small})")
    check(fs["head"] == 0, f"rule:deskread: the head shows no kind badge or date cut short ({fs['head']} shown)")
    # rule:one-control: Dictate capped on a desk (the critic: 612px at 1440,
    # 1092 at 1920, louder than New), and ⋯ reachable with the chat dock's
    # list open over the lower right (the dock gives way to the bar)
    def dock_over_bar(pg, tag):
        pg.evaluate(f"select({ids['log']}); setRead(true)")
        pg.evaluate("dockExpand(false)")
        pg.wait_for_timeout(300)
        r = pg.evaluate("""() => { const m = document.querySelector('#bEdMore').getBoundingClientRect();
          const e = document.elementFromPoint(m.left + m.width / 2, m.top + m.height / 2);
          const l = document.querySelector('#dock .dklist');
          return { hit: !!(e && e.closest('#bEdMore')), by: e ? e.outerHTML.slice(0, 60) : null,
                   list: !!(l && l.getBoundingClientRect().height > 0) }; }""")
        check(r["list"] and r["hit"], f"desktop {tag}: the dock's list open, ⋯ is not under it  ({r})")
        pg.evaluate("dockCollapse(); closeEditor()")
    dock_over_bar(page, "1280")
    pg2, errs2, _ = open_page(1440, 900, False)
    pg2.evaluate(f"select({ids['log']}); setRead(true)")
    pg2.wait_for_timeout(200)
    mw = pg2.evaluate("Math.round(document.querySelector('#bMic').getBoundingClientRect().width)")
    check(mw <= 360, f"desktop 1440: Dictate capped, at most 360px  ({mw}px)")
    pg2.evaluate("closeEditor()")
    pg2.context.close()
    pg3, errs3, _ = open_page(1920, 1080, False)
    dock_over_bar(pg3, "1920")
    check(not errs2 and not errs3, f"desktop 1440 and 1920: no page errors  ({(errs2 + errs3)[:3]})")
    pg3.context.close()
    check(not shown_hidden(page), "desktop: nothing hidden is shown")
    page.evaluate("closeEditor()")
    doors(page, srv, ids, dialogs, phone=False)
    popups(page, ids, phone=False)
    details(page, srv, ids, phone=False)
    top(page, srv, ids, phone=False)
    drafts(page, srv, dialogs, phone=False)
    reader_tap(page, srv, ids, phone=False)
    check(not errs, f"desktop: no page errors  ({errs[:3]})")
    page.context.close()
    browser.close()


def main():
    tmp = pathlib.Path(killclean.mkdtemp(prefix="lcars-editor-", dir=os.path.expanduser("~/.cache")))
    binary = os.environ.get("LCARS_TEST_BIN")
    if not binary:
        binary = tmp / "lcars-test"
        rig.build(binary)
    os.environ["LCARS_UI_DIR"] = str(UI)
    srv = rig.Server(binary, tmp)
    try:
        ids = {
            "log": make(srv, "personal_log", "a walk", "went out along the river"),
            "crew": make(srv, "crew_ops", "disk report", "the disk is fine"),
            "other": make(srv, "personal_log", "another", "a second entry"),
            "tagged": make(srv, "personal_log", "tagged", "out #walking today"),
        }
        for tag in ("phone", "desktop"):     # each size its own, untouched by the other's run
            ids[tag] = {"log": make(srv, "personal_log", tag + " details", "plain"),
                        "task": make(srv, "task", "buy milk", "two litres"),
                        "kindy": make(srv, "personal_log", "a kind to change", "words"),
                        "outline": make(srv, "personal_log", "by the water",
                                        "went out along the river and saw a heron fishing\n"
                                        "- TODO call the boat club\n"
                                        "- the light\n  - at five, low and gold\n")}
            for v in (71.0, 72.5):
                ids[tag]["weight"] = create(srv, {
                    "kind": "weight", "title": "", "content": "", "value_float": v})
        made = [ids[k] for k in ids if k not in ("phone", "desktop")]
        made += [i for t in ("phone", "desktop") for i in ids[t].values()]
        check(len(set(made)) == len(made), f"every fixture row its own  ({made})")
        with sync_playwright() as p:
            run(p, srv, ids)
    finally:
        srv.stop()
    print(f"\neditor: {checks[0]} checks, {len(fails)} failures")
    for f in fails:
        print("  - " + f)
    if fails:
        print(f"server log kept in {tmp}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
