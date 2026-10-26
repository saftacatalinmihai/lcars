#!/usr/bin/env python3
"""The page's half of test/classified.py: Secret entries in headless Chromium
against a scratch server (run from classified.py, which builds it).

  1. Config: no password yet; the setup refused without the tick-box, then
     set - unlocked at once, the vault on the server holding no password;
  2. a new entry marked Secret before its first save: the server's row
     empty with an envelope, the page's in memory whole; local search finds
     its words while unlocked;
  3. an existing entry raised by the chip: "sealing…" in the same frame,
     then Secret on the server; a refused raise (a wrong token) shown on the
     chip and the row with Retry, and the Retry landing;
  4. lock (the header's button): the rows' placeholders, search finding
     nothing, the editor read-only; L, a wrong password told apart, the
     right one opening them again;
  5. the dictation mark in a Secret entry; the auto-lock (15 minutes idle,
     5 away); deck patches refused while unlocked;
  6. offline: a Secret edit waits in the outbox as an envelope, and is sent
     when the link is back;
  7. declassify by the chip (it asks), and a reload: locked again;
  8. every request the page made: none carries the password or a Secret
     entry's words; localStorage and IndexedDB hold none of them; nor does
     lcars.db or its WAL;
  9. phase 5, at http://localhost (WebAuthn wants a domain, not an IP) with
     CDP's virtual authenticator (hasPrf): the page's CSP refusing an
     outside fetch; a passkey registered from Config ("Waiting for the
     passkey…" while the OS's sheet would be up), listed, unlocking after a
     lock, removed; an authenticator without PRF told so and not
     registered; the recovery code (shown once at setup) unlocking and
     setting a new password; a one-wrap vault, as phase 1 left them,
     unlocking as before; and every request: no PRF output, master key,
     password, code or Secret word in any.
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
UI = HERE.parent

PW = "correct horse battery staple 7"
WRONG = "not the password at all"
S_TITLE = "Zanzibar ledger"           # the Secret entry's words, sent nowhere
S_BODY = "quixotic marmalade protocol"
S_EDIT = "offline xylophone amendment"
R_TEXT = "ordinary raise subject"     # the raised entry's: plain until raised


def run(binary, tmp, check):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check(False, "playwright is needed for the page's half (CHROMIUM=0 skips it)")
        return
    import classified as C
    d = tmp / "ui"
    d.mkdir()
    (d / "media").mkdir()
    s = C.Server(binary, d, env_extra={"LCARS_UI_DIR": str(UI)})
    try:
        st, r = s.req("POST", "/entries", {"kind": "note", "title": R_TEXT, "content": "to be raised"})
        rid = r["id"]
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            try:
                sid, code = page_run(b, s, rid, check)
                passkey_run(b, s, sid, code, check)
            finally:
                b.close()
    finally:
        s.stop()
    found = [n for n in ("lcars.db", "lcars.db-wal") if (d / n).exists() and
             any(w.encode() in (d / n).read_bytes() for w in (S_TITLE, S_BODY, S_EDIT))]
    check(found == [], f"no Secret word in lcars.db or its WAL ({found})")


def page_run(b, s, rid, check):
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    base = f"http://127.0.0.1:{s.port}"
    cfg = {"base": base, "user": C_USER(), "pass": C_PASS()}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs, reqs = [], []
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.on("request", lambda r: reqs.append((r.method, r.url, json.dumps(r.headers), r.post_data or "")))
    p.goto(base + "/ui/")
    p.wait_for_function("typeof clsOn === 'function' && st.all.length >= 1", timeout=30000)

    print("Config: the password, set")
    p.evaluate("openCfg()")
    p.wait_for_selector("#c_clsl [data-cls=setup]", timeout=5000)
    check("No password set" in p.text_content("#c_clsl"), "Config says no password is set")
    p.click("#c_clsl [data-cls=setup]")
    p.wait_for_selector("#clsPw", timeout=3000)
    check("gone" in p.text_content("#dlg"), "the setup says plainly a lost password loses the entries")
    p.fill("#clsPw", PW)
    p.fill("#clsPw2", PW)
    p.click("#clsGo")
    p.wait_for_function("document.querySelector('#clsMsg').textContent.includes('tick')", timeout=3000)
    check(not p.evaluate("clsOn()"), "refused without the tick-box")
    p.check("#clsOk")
    check(p.is_checked("#clsRec"), "the recovery code is offered at setup, on by default")
    p.click("#clsGo")
    p.wait_for_selector("#clsCode", timeout=20000)
    code = p.text_content("#clsCode").strip()
    check(len(code.replace("-", "")) == 26 and code.count("-") == 4, f"the recovery code, shown once in groups ({code})")
    p.click("#clsKept")
    p.wait_for_function("clsOn() && !$('#ov').classList.contains('on')", timeout=5000)
    check(p.text_content("#clsCode") == "", "kept: the code gone from the page")
    check(p.evaluate("!!cls.vault && cls.version === 1"), "set, and unlocked at once")
    st, v = s.req("GET", "/vault")
    check(PW not in json.dumps(v) and v["vault"]["wraps"][0]["kdf"] == "PBKDF2-SHA256",
          "the server's vault: a wrap and its KDF, no password")
    check([w["type"] for w in v["vault"]["wraps"]] == ["password", "recovery"] and code.replace("-", "") not in json.dumps(v),
          "and a recovery wrap, with no code in it")
    check(p.is_visible("#bCls") and "Unlocked" in p.text_content("#bCls"), "the header's button shows it unlocked")

    print("a new entry, Secret before its first save")
    p.evaluate("startNew({kind: 'note', title: '', content: ''}, 'New entry')")
    p.fill("#e_head", S_TITLE)
    p.fill("#content", S_BODY)
    p.click("#edcls")
    check(p.text_content("#edcls").startswith("▮ Secret"), "the chip says Secret at once")
    p.evaluate("save()")
    p.wait_for_function("st.all.some(e => clsSecret(e) && e.title === %s)" % json.dumps(S_TITLE), timeout=10000)
    sid = p.evaluate("st.all.find(e => clsSecret(e) && e.title === %s).id" % json.dumps(S_TITLE))
    st, row = s.req("GET", f"/entries/{sid}")
    check(row.get("classification") == 2 and row.get("title") == "" and row.get("content") == ""
          and str(row.get("sealed", "")).startswith("lcs1."), "the server holds an envelope and empty columns")
    check(p.evaluate(f"st.byId.get({sid}).content") == S_BODY, "the page holds its text, in memory")
    p.fill("#q", "marmalade")
    p.wait_for_function(f"st.view.some(e => e.id === {sid})", timeout=5000)
    check(True, "local search finds its words while unlocked")
    p.fill("#q", "")
    p.wait_for_timeout(300)

    print("an existing entry raised by the chip")
    p.evaluate(f"select({rid})")
    p.evaluate("st.read = false; paintMode && paintMode(true)")
    good = p.evaluate("cls.token")
    p.evaluate("cls.token = '0'.repeat(64)")
    face = p.evaluate("clsChipTap(); document.querySelector('#edcls').textContent")
    check("sealing" in face, f"sealing… shows in the same frame ({face!r})")
    p.wait_for_function(f"cls.failed.has({rid})", timeout=10000)
    check("Retry" in p.text_content("#edcls"), "a refused raise: the chip says Not sealed · Retry")
    check("not sealed" in p.text_content(f'.item[data-id="{rid}"]'), "and so does its row")
    check(p.is_visible("#toast .tact") and p.text_content("#toast .tact") == "Retry", "the toast carries Retry")
    p.evaluate(f"cls.token = {json.dumps(good)}")
    p.click("#edcls")
    p.wait_for_function(f"clsSecret(st.byId.get({rid})) && !cls.busy.has({rid})", timeout=10000)
    st, row = s.req("GET", f"/entries/{rid}")
    check(row.get("classification") == 2 and row.get("title") == "", "Retry: raised on the server, its title emptied")
    check(p.evaluate(f"st.byId.get({rid}).title") == R_TEXT, "and still readable here")

    print("lock, and unlock again")
    p.click("#bCls")
    p.wait_for_function("!clsOn()", timeout=5000)
    check(p.evaluate(f"st.byId.get({sid}).title === '' && st.byId.get({sid}).content === ''"),
          "locked: the plaintext gone from the rows")
    check("Classified" in p.text_content(f'.item[data-id="{sid}"]'), "the row shows its placeholder")
    p.fill("#q", "marmalade")
    p.wait_for_timeout(600)
    check(not p.evaluate(f"st.view.some(e => e.id === {sid})"), "search finds nothing of it")
    p.fill("#q", "")
    p.evaluate(f"select({sid})")
    check(p.evaluate("$('#content').readOnly && $('#e_head').readOnly"), "its editor is read-only")
    p.evaluate("st.read = true; renderRead()")
    check(p.query_selector("#rd_content [data-cls=unlock]") is not None, "the reader offers Unlock")
    p.evaluate("document.activeElement && document.activeElement.blur()")
    p.keyboard.press("L")
    p.wait_for_selector("#clsPw", timeout=3000)
    p.fill("#clsPw", WRONG)
    p.click("#clsGo")
    p.wait_for_function("document.querySelector('#clsMsg').textContent.includes('wrong password')", timeout=20000)
    check(not p.evaluate("clsOn()"), "L: a wrong password is told apart")
    p.fill("#clsPw", PW)
    p.click("#clsGo")
    p.wait_for_function("clsOn()", timeout=20000)
    p.wait_for_function(f"st.byId.get({sid}).title === {json.dumps(S_TITLE)}", timeout=5000)
    check(True, "the right one opens them again")

    print("the dictation mark, the auto-lock, the deck's patches")
    p.evaluate(f"select({sid})")
    p.evaluate("vx.on = true; clsVoicePaint()")
    check(p.is_visible("#clsvmark"), "the microphone in a Secret entry: the voice-leaves mark")
    p.evaluate("vx.on = false; clsVoicePaint()")
    check(not p.is_visible("#clsvmark"), "and gone with the microphone")
    check(p.evaluate("lcarsClsUnlocked()") is True, "the deck can ask whether the console is unlocked")
    p.evaluate("cls.lastInput = Date.now() - 16 * 60000; clsTick()")
    p.wait_for_function("!clsOn()", timeout=5000)
    check(True, "15 minutes idle: locked")
    p.evaluate(f"clsUnlock({json.dumps(PW)})")
    p.wait_for_function("clsOn()", timeout=20000)
    p.evaluate("cls.hiddenAt = Date.now() - 6 * 60000; document.dispatchEvent(new Event('visibilitychange'))")
    p.wait_for_function("!clsOn()", timeout=5000)
    check(True, "5 minutes away: locked on return")
    p.evaluate(f"clsUnlock({json.dumps(PW)})")
    p.wait_for_function("clsOn()", timeout=20000)

    print("offline: an edit waits as an envelope")
    p.evaluate(f"select({sid})")
    p.wait_for_function(f"st.sel && st.sel.id === {sid} && st.sel.content === {json.dumps(S_BODY)}", timeout=5000)
    ctx.set_offline(True)
    p.evaluate("st.read = false; paintMode && paintMode(true)")
    p.fill("#content", S_BODY + " " + S_EDIT)
    p.evaluate("save()")
    p.wait_for_function(f"ob.ops.has({sid})", timeout=10000)
    held = p.evaluate("JSON.stringify([...ob.ops.values()])")
    check(S_EDIT not in held and "lcs1." in held, "the outbox holds the envelope, not the words")
    stored = p.evaluate("""async () => { const o = await outboxStore.get(); return JSON.stringify(o || {}); }""")
    check(S_EDIT not in stored and S_BODY not in stored, "and so does its IndexedDB copy")
    ctx.set_offline(False)
    p.evaluate("obBack && obBack(); obFlush && obFlush()")
    p.wait_for_function(f"!ob.ops.has({sid})", timeout=20000)
    st, row = s.req("GET", f"/entries/{sid}")
    check(row.get("classification") == 2 and row.get("content") == "" and row.get("sealed", "").startswith("lcs1."),
          "back online: sent, still sealed")
    p.wait_for_function(f"st.byId.get({sid}).content.includes({json.dumps(S_EDIT)})", timeout=5000)
    check(True, "and the page reads the edit")

    print("declassify by the chip, and a reload")
    p.evaluate(f"select({rid})")
    p.evaluate("st.read = false; paintMode(true)")      # the chip is the editor's, as the kind's is
    p.click("#edcls")
    p.wait_for_selector("#lcOk", timeout=3000)
    check("Declassify" in p.text_content("#dlg"), "it asks first")
    p.click("#lcOk")
    p.wait_for_function(f"!clsSecret(st.byId.get({rid})) && !cls.busy.has({rid})", timeout=10000)
    st, row = s.req("GET", f"/entries/{rid}")
    check(row.get("classification") == 0 and row.get("title") == R_TEXT and "sealed" not in row,
          "declassified: the server has its title back, no envelope")
    p.reload()
    p.wait_for_function("typeof clsOn === 'function' && st.all.length >= 2", timeout=30000)
    check(not p.evaluate("clsOn()"), "a reload: locked")
    check(p.evaluate(f"st.byId.get({sid}).title") == "", "the Secret row a placeholder again")

    print("what left the page, and what it kept")
    sent = "\n".join(m + " " + u + " " + h + " " + d for m, u, h, d in reqs)
    check(PW not in sent and WRONG not in sent, f"no request carries the password ({len(reqs)} recorded)")
    leaks = [w for w in (S_TITLE, S_BODY, S_EDIT) if w in sent]
    check(leaks == [], f"no request carries a Secret entry's words ({leaks})")
    ls = p.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    check(not any(w in ls for w in (S_TITLE, S_BODY, S_EDIT, PW)), "localStorage holds none of them")
    idb = p.evaluate("""async () => {
      const out = [];
      const dbs = indexedDB.databases ? await indexedDB.databases() : [];
      for (const d of dbs) {
        const db = await new Promise((res, rej) => { const r = indexedDB.open(d.name); r.onsuccess = () => res(r.result); r.onerror = rej; });
        for (const n of db.objectStoreNames) {
          const all = await new Promise(res => { const q = db.transaction(n).objectStore(n).getAll(); q.onsuccess = () => res(q.result); q.onerror = () => res([]); });
          out.push(JSON.stringify(all));
        }
        db.close();
      }
      return out.join("\\n");
    }""")
    check(len(idb) > 0 and not any(w in idb for w in (S_TITLE, S_BODY, S_EDIT, PW)),
          f"IndexedDB (the mirror, the outbox) holds none of them ({len(idb)} bytes read)")
    check(errs == [], f"no page errors ({errs[:2]})")
    sent_all.extend(reqs)
    ctx.close()
    return sid, code


sent_all = []
NEWPW = "a brand new password 42"


def passkey_run(b, s, sid, code, check):
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    base = f"http://localhost:{s.port}"
    cfg = {"base": base, "user": C_USER(), "pass": C_PASS()}
    ctx.add_init_script(f"localStorage.setItem('lcars.cfg', {json.dumps(json.dumps(cfg))});")
    p = ctx.new_page()
    errs, reqs = [], []
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.on("request", lambda r: reqs.append((r.method, r.url, json.dumps(r.headers), r.post_data or "")))
    cdp = ctx.new_cdp_session(p)
    cdp.send("WebAuthn.enable")
    opts = {"protocol": "ctap2", "ctap2Version": "ctap2_1", "transport": "internal", "hasResidentKey": True,
            "hasUserVerification": True, "isUserVerified": True, "automaticPresenceSimulation": True}
    auth = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": dict(opts, hasPrf=True)})["authenticatorId"]
    p.goto(base + "/ui/")
    p.wait_for_function("typeof clsOn === 'function' && st.all.length >= 1", timeout=30000)
    # what the passkeys gave, kept to look for in the requests afterwards
    p.evaluate("""() => { window.__prf = [];
      for (const k of ["pkCreate", "pkGet"]) { const o = clsCrypto[k];
        clsCrypto[k] = async (...a) => { const r = await o(...a);
          if (r.prf) window.__prf.push(clsHex(r.prf), clsB64(r.prf)); return r; }; } }""")

    print("the page's CSP (at localhost)")
    pol = p.evaluate("document.querySelector('meta[http-equiv=Content-Security-Policy]').content")
    check(pol.startswith("connect-src 'self'") and base in pol and "wss://api.deepgram.com" in pol,
          f"connect-src: the page's own origin, its server and the services it names ({pol[:60]}…)")
    seen = p.evaluate("""async () => {
      let v = "";
      document.addEventListener("securitypolicyviolation", e => { v = e.violatedDirective + " " + e.blockedURI; });
      try { await fetch("https://example.com/steal?x=1"); } catch (e) { /* refused */ }
      await new Promise(r => setTimeout(r, 200));
      return v; }""")
    check(seen.startswith("connect-src") and "example.com" in seen, f"a fetch to anywhere else is refused ({seen})")

    print("a passkey, registered from Config")
    p.evaluate(f"clsUnlock({json.dumps(PW)})")
    p.wait_for_function(f"clsOn() && st.byId.get({sid}).title === {json.dumps(S_TITLE)}", timeout=20000)
    p.evaluate("openCfg()")
    p.wait_for_selector("#c_clsl [data-cls=pkadd]", timeout=5000)
    check("None registered" in p.text_content("#c_clsl"), "Config: no passkey yet")
    p.click("#c_clsl [data-cls=pkadd]")
    p.wait_for_selector("#clsPkHead", timeout=3000)
    p.fill("#clsPkHead", "Test laptop")
    p.fill("#clsPw", WRONG)
    p.click("#clsGo")
    p.wait_for_function("document.querySelector('#clsMsg').textContent.includes('wrong password')", timeout=20000)
    check(len(s.req("GET", "/vault")[1]["vault"]["wraps"]) == 2, "a wrong password: refused before any passkey is made")
    p.evaluate("""() => { window.__faces = []; const b = document.querySelector('#clsGo');
      new MutationObserver(() => window.__faces.push(b.textContent)).observe(b, {childList: true, characterData: true, subtree: true}); }""")
    p.fill("#clsPw", PW)
    p.click("#clsGo")
    p.wait_for_function("!$('#ov').classList.contains('on') || $('#clsMsg').classList.contains('bad')", timeout=30000)
    check(not p.evaluate("$('#ov').classList.contains('on')"), f"registered ({p.text_content('#clsMsg')})")
    faces = p.evaluate("window.__faces")
    check("Waiting for the passkey…" in faces, f"the button says it waits on the passkey ({faces})")
    st_, v = s.req("GET", "/vault")
    pks = [w for w in v["vault"]["wraps"] if w["type"] == "passkey"]
    check(len(pks) == 1 and pks[0]["name"] == "Test laptop" and pks[0]["cred"] and pks[0]["prf_salt"] and
          pks[0]["kdf"] == "HKDF-SHA256", "the vault gains a passkey wrap: its credential, PRF salt, name and KDF")
    check(p.evaluate("window.__prf.length") >= 2, "the authenticator gave a PRF secret")
    p.evaluate("openCfg()")
    p.wait_for_selector("#c_clsl .clspk li", timeout=5000)
    check("Test laptop" in p.text_content("#c_clsl .clspk"), "Config lists it by name and date")
    p.evaluate("closeOv()")

    print("lock, and unlock with the passkey")
    p.evaluate("clsLock(true)")
    p.wait_for_function("!clsOn()", timeout=5000)
    p.evaluate("document.activeElement && document.activeElement.blur()")
    p.keyboard.press("L")
    p.wait_for_selector("#clsPk", timeout=3000)
    check(p.query_selector("#clsRecUse") is not None, "the unlock door offers the passkey and the recovery code")
    p.click("#clsPk")
    p.wait_for_function(f"clsOn() && st.byId.get({sid}).title === {json.dumps(S_TITLE)}", timeout=20000)
    check(True, "the passkey opens the Secret entries")
    p.evaluate("clsLock(true)")
    p.wait_for_function("!clsOn()", timeout=5000)
    p.evaluate("clsPasskeyAsk()")
    p.wait_for_function("clsOn()", timeout=20000)
    check(True, "and so does voice's \"unlock with a passkey\"")

    print("removed from Config")
    p.evaluate("openCfg()")
    p.wait_for_selector("#c_clsl [data-cls=pkdel]", timeout=5000)
    p.click("#c_clsl [data-cls=pkdel]")
    p.wait_for_selector("#lcOk", timeout=3000)
    p.click("#lcOk")
    p.wait_for_function("!clsWrapsOf(cls.vault, 'passkey').length", timeout=10000)
    st_, v = s.req("GET", "/vault")
    check([w["type"] for w in v["vault"]["wraps"]] == ["password", "recovery"], "the vault without it, the rest kept")
    p.evaluate("closeOv()")

    print("an authenticator without PRF")
    cdp.send("WebAuthn.removeVirtualAuthenticator", {"authenticatorId": auth})
    cdp.send("WebAuthn.addVirtualAuthenticator", {"options": dict(opts, hasPrf=False)})
    p.evaluate("clsPasskeyAddAsk()")
    p.wait_for_selector("#clsPkHead", timeout=3000)
    p.fill("#clsPw", PW)
    p.click("#clsGo")
    p.wait_for_function("document.querySelector('#clsMsg').textContent.includes('PRF')", timeout=30000)
    check("not registered" in p.text_content("#clsMsg") and
          len(s.req("GET", "/vault")[1]["vault"]["wraps"]) == 2, "told it has no PRF, and not registered")
    p.evaluate("closeOv()")

    print("the recovery code")
    mk = p.evaluate(f"""async () => {{ const u = await clsUnwrapPw({json.dumps(PW)}, true);
      const raw = new Uint8Array(await crypto.subtle.exportKey("raw", u.key)); return [clsHex(raw), clsB64(raw), btoa(String.fromCharCode(...raw))]; }}""")
    p.evaluate("clsLock(true)")
    p.wait_for_function("!clsOn()", timeout=5000)
    p.evaluate("clsUnlockAsk()")
    p.wait_for_selector("#clsRecUse", timeout=3000)
    p.click("#clsRecUse")
    p.wait_for_selector("#clsCodeIn", timeout=3000)
    p.fill("#clsCodeIn", "AAAAA-AAAAA-AAAAA-AAAAA-AAAAAA")
    p.fill("#clsPw", NEWPW)
    p.fill("#clsPw2", NEWPW)
    p.click("#clsGo")
    p.wait_for_function("document.querySelector('#clsMsg').classList.contains('bad')", timeout=20000)
    check(not p.evaluate("clsOn()"), f"a wrong code is refused ({p.text_content('#clsMsg')})")
    p.fill("#clsCodeIn", code.lower().replace("-", " "))
    p.fill("#clsPw", NEWPW)
    p.fill("#clsPw2", NEWPW)
    p.click("#clsGo")
    p.wait_for_function(f"clsOn() && st.byId.get({sid}).title === {json.dumps(S_TITLE)}", timeout=30000)
    check(True, "the code (as typed: lower case, spaced) opens the entries")
    p.evaluate("clsLock(true)")
    p.wait_for_function("!clsOn()", timeout=5000)
    bad = p.evaluate(f"clsUnlock({json.dumps(PW)}).then(() => '', e => e.message)")
    check("wrong password" in bad, "the old password no longer does")
    p.evaluate(f"clsUnlock({json.dumps(NEWPW)})")
    p.wait_for_function("clsOn()", timeout=20000)
    check(True, "the new one does")

    print("a one-wrap vault, as phase 1 left them")
    prf = p.evaluate("window.__prf")    # a reload drops it
    token = p.evaluate("cls.token")
    st_, v = s.req("GET", "/vault")
    one = dict(v["vault"], wraps=[w for w in v["vault"]["wraps"] if w["type"] == "password"])
    st_, r = s.req("PUT", "/vault", {"vault": one, "token": token, "version": v["version"]})
    check(st_ == 200, f"the vault cut to its password wrap ({st_})")
    p.reload()
    p.wait_for_function("typeof clsOn === 'function' && st.all.length >= 1", timeout=30000)
    p.evaluate("clsUnlockAsk()")
    p.wait_for_selector("#clsPw", timeout=5000)
    check(p.query_selector("#clsPk") is None and p.query_selector("#clsRecUse") is None,
          "its unlock door: the password alone")
    p.fill("#clsPw", NEWPW)
    p.click("#clsGo")
    p.wait_for_function(f"clsOn() && st.byId.get({sid}).title === {json.dumps(S_TITLE)}", timeout=30000)
    check(True, "and it unlocks exactly as before")
    p.evaluate("openCfg()")
    p.wait_for_selector("#c_clsl [data-cls=recmake]", timeout=5000)
    check("none" in p.text_content("#c_clsl"), "Config offers it a recovery code")
    p.evaluate("closeOv()")

    print("what left the page (phase 5)")
    sent = "\n".join(m + " " + u + " " + h + " " + d for m, u, h, d in reqs + sent_all)
    secrets_ = [PW, NEWPW, WRONG, code, code.replace("-", ""), S_TITLE, S_BODY, S_EDIT] + mk
    leaks = [x[:12] for x in secrets_ if x and x in sent]
    check(leaks == [], f"no request carries a password, the code, the master key or a Secret word ({leaks}; "
                       f"{len(reqs) + len(sent_all)} requests)")
    check(not any(x in sent for x in prf), "nor a passkey's PRF output")
    ls = p.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    check(not any(x in ls for x in secrets_ if x), "localStorage holds none of them")
    check(errs == [], f"no page errors ({errs[:2]})")
    ctx.close()


def C_USER():
    import classified as C
    return C.USER


def C_PASS():
    import classified as C
    return C.PASS
