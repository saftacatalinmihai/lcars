/* The public demo's server, in the page (docs/design/demo-static.md).

   demo/static.py copies the console and the deck to a folder a static host
   serves (no server, no rewrites) and loads this script first in both, as
   demo.js. It is the whole of the demo mode's switch: window.LCARS_DEMO
   exists only where this file was loaded, which only the build does, so no
   url the live app answers can turn a demo on.

   It answers the API in the page. The pages are left as they are: their
   api() fetches cfg.base + path as ever, and cfg.base is LCARS_DEMO.base,
   the folder's "api" - so everything under it is answered here, from
   journal.json (the made-up journal, demo/fixture.py) and this browser's
   own edits over it, kept in localStorage so a reload keeps them. Nothing
   leaves the browser. The one exception is api/media/<path>: the demo's
   pictures are real files there, so an <img> (which never comes through
   fetch) finds them, and a fetch of one is let through to the host.

   What needs a server (the computer and the navigator, search by meaning,
   uploads, tapes, CalDAV, the engineers, a voice) is answered with a short
   note of why it is off, in the shape each caller already shows: the chat
   gets a reply, the rest a 503 whose error the page prints where the
   feature would have been. */
(function () {
  "use strict";
  var me = document.currentScript;
  var DIR = new URL(".", (me && me.src) || location.href).href;
  var BASE = DIR + "api";
  var EDITS = "lcars.demo.edits";       // {rows: {id: row}, next: id}
  var SHIFT = "lcars.demo.shift";       // the day shift the mirror was filled at
  var NOTE = "This is a demo on a made-up journal, with no server behind it";
  var realFetch = window.fetch.bind(window);

  /* ---------- the journal: the fixture, moved to today, and the edits ----------
     The fixture was written relative to the day it was built, so it is moved
     on by whole days to keep its newest entry today's: a journal whose last
     line is three months old reads as abandoned. The console's mirror holds
     the dates it was given, so a new day empties it (the delta sync only asks
     for rows modified since its mark, and a moved row's older neighbours
     would keep yesterday's dates). An open waits for a pending delete, so
     the page's first open below finds it gone. */
  var DAY = 864e5;
  var pad = function (n) { return (n < 10 ? "0" : "") + n; };
  var stamp = function (d) {
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()) + " " +
      pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + ":" + pad(d.getUTCSeconds());
  };
  var nowStamp = function () { return stamp(new Date()); };
  function moved(s, days) {
    if (!s || !days) return s || "";
    var t = Date.parse(s.replace(" ", "T") + "Z");
    return isNaN(t) ? s : stamp(new Date(t + days * DAY));
  }
  function shiftOf(built) {
    var b = /^(\d{4})-(\d\d)-(\d\d)$/.exec(built || "");
    if (!b) return 0;
    var n = new Date();
    return Math.max(0, Math.round((Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) -
                                   Date.UTC(+b[1], +b[2] - 1, +b[3])) / DAY));   // load() may take a day off
  }
  function lsJSON(k, d) { try { var v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; } catch (e) { return d; } }
  function lsPut(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } }

  /* ---------- the Secret entry: sealed here, at the first load ----------
     The fixture's rows marked `seal` are sealed the way the console seals
     one (index.html's "classified" block, the same envelope), under a
     vault made for this browser and kept with its edits. Its password is
     no secret - the unlock dialog prints it (LCARS_DEMO.password) - and
     its rounds are fewer than the app's, as a visitor waits on them. */
  var VAULT = "lcars.demo.vault";        // {vault, version, sealed: {id: row}}
  var DEMO_PW = "make it so";
  var DEMO_ITER = 20000;
  function b64(u8) {
    var s = "";
    for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function unb64(s) {
    s = String(s).replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var b = atob(s), u = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    return u;
  }
  var utf8 = function (s) { return new TextEncoder().encode(s); };
  function sealDemo(st) {
    var kept = lsJSON(VAULT, null) || {};
    st.vault = kept.vault || null;
    st.vaultV = kept.version || 0;
    kept.sealed = kept.sealed || {};
    // sealed on an earlier load: that copy (kept with the vault, not the
    // edits - it is the fixture's, and Reset must find no edits after it)
    var todo = [];
    st.rows.forEach(function (r) {
      if (!r.seal) return;
      if (st.vault && kept.sealed[r.id]) st.rows.set(r.id, kept.sealed[r.id]);
      else todo.push(r);
    });
    if (!todo.length) return Promise.resolve();
    // with no WebCrypto the row is left out: never shown in the clear
    var drop = function () { todo.forEach(function (r) { st.rows.delete(r.id); }); };
    if (!(window.crypto && crypto.subtle)) { drop(); return Promise.resolve(); }
    var S = crypto.subtle, w = st.vault && st.vault.wraps && st.vault.wraps[0];
    var salt = w ? unb64(w.salt) : crypto.getRandomValues(new Uint8Array(16));
    return S.importKey("raw", utf8(DEMO_PW), "PBKDF2", false, ["deriveKey"]).then(function (base) {
      return S.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: salt, iterations: w ? w.iter : DEMO_ITER },
                         base, { name: "AES-GCM", length: 256 }, false, ["wrapKey", "unwrapKey"]);
    }).then(function (kek) {
      if (w) return S.unwrapKey("raw", unb64(w.wrapped), kek, { name: "AES-GCM", iv: unb64(w.iv) },
                                { name: "AES-GCM" }, false, ["encrypt"]);
      return S.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]).then(function (mk) {
        var iv = crypto.getRandomValues(new Uint8Array(12));
        return S.wrapKey("raw", mk, kek, { name: "AES-GCM", iv: iv }).then(function (wr) {
          st.vault = { v: 1, kid: "k1", wraps: [{ type: "password", kdf: "PBKDF2-SHA256", iter: DEMO_ITER,
                                                  salt: b64(salt), iv: b64(iv), wrapped: b64(new Uint8Array(wr)) }] };
          st.vaultV = 1;
          return mk;
        });
      });
    }).then(function (mk) {
      return Promise.all(todo.map(function (r) {
        var iv = crypto.getRandomValues(new Uint8Array(12));
        var head = b64(utf8(JSON.stringify({ kid: "k1", alg: "A256GCM", iv: b64(iv) })));
        var plain = { title: r.title, content: r.content, value_int: r.value_int || 0, value_float: r.value_float || 0 };
        return S.encrypt({ name: "AES-GCM", iv: iv, additionalData: utf8("lcs1." + head) }, mk,
                         utf8(JSON.stringify(plain))).then(function (ct) {
          var o = Object.assign({}, r, { title: "", content: "", value_int: 0, value_float: 0, classification: 2,
                                         sealed: "lcs1." + head + "." + b64(new Uint8Array(ct)) });
          delete o.seal;
          o.content_length = o.sealed.length;
          st.rows.set(o.id, o);
          kept.sealed[o.id] = o;
        });
      }));
    }).then(function () {
      lsPut(VAULT, { vault: st.vault, version: st.vaultV, sealed: kept.sealed });
    }).catch(drop);
  }

  var state = null;                      // {rows: Map, media, emb, next, keys}
  var ready = null;
  function load() {
    if (ready) return ready;
    ready = realFetch(DIR + "journal.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("journal.json: " + r.status); return r.json(); })
      .then(function (fx) {
        var days = shiftOf(fx.built);
        // Never past now: the fixture's newest rows are at the late afternoon
        // of its day (fixture.NOW), so a morning visit would otherwise hold
        // rows stamped hours ahead, and the delta sync's mark with them - an
        // edit, stamped now, would be older than the mark, and the deck (or
        // any second tab) would never be told of it. A day less is yesterday's.
        var newest = "";
        fx.rows.forEach(function (r) {
          [r.created_at_utc, r.last_modified_at_utc].forEach(function (v) { if ((v || "") > newest) newest = v; });
        });
        for (var now = nowStamp(), n = 0; n < 3 && moved(newest, days) > now; n++) days--;
        var had = lsJSON(SHIFT, null);
        if (had !== null && had !== days) dropMirror();
        lsPut(SHIFT, days);
        var rows = new Map();
        fx.rows.forEach(function (r) {
          var o = Object.assign({ start_date: "", end_date: "" }, r);
          ["created_at_utc", "last_modified_at_utc", "start_date", "end_date"].forEach(function (k) { o[k] = moved(o[k], days); });
          rows.set(o.id, o);
        });
        var ed = lsJSON(EDITS, { rows: {}, next: 0 });
        Object.keys(ed.rows || {}).forEach(function (k) {
          var r = ed.rows[k];
          if (r === null) rows.delete(+k); else rows.set(+k, r);
        });
        var next = ed.next || 0;
        rows.forEach(function (r) { if (r.id >= next) next = r.id + 1; });
        state = { rows: rows, media: (fx.media || []).map(function (m) {
                    return Object.assign({}, m, { created_at_utc: moved(m.created_at_utc, days) }); }),
                  emb: fx.embeddings || null, next: next, ed: ed, keys: {} };
        return sealDemo(state).then(function () { return state; });
      });
    return ready;
  }
  function keep(r) {                     // an edit, into this browser's copy
    state.ed.rows[r.id] = r;
    state.ed.next = state.next;
    if (!lsPut(EDITS, state.ed)) throw Object.assign(new Error("this browser's storage is full"), { code: 507 });
  }
  function dropMirror() {
    ["lcars", "lcars-outbox", "lcars-stars"].forEach(function (n) {
      try { indexedDB.deleteDatabase(n); } catch (e) {}
    });
  }

  /* Reset: the fixture back - this browser's edits, the console's mirror,
     outbox and star cache, and the pages' settings (everything they keep is
     under "lcars."), for the caller to reload after. Resolves once the
     deletes have gone through, so the reload does not open them first. */
  function reset() {
    var ks = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf("lcars.") === 0) ks.push(k);
    }
    ks.forEach(function (k) { localStorage.removeItem(k); });
    return Promise.all(["lcars", "lcars-outbox", "lcars-stars"].map(function (n) {
      return new Promise(function (res) {
        try {
          var q = indexedDB.deleteDatabase(n);
          q.onsuccess = q.onerror = q.onblocked = function () { res(); };
        } catch (e) { res(); }
      });
    }));
  }

  /* ---------- the routes: lcars_http.h's, as the pages ask them ---------- */
  var FILTERS = {
    since: function (r, v) { return r.created_at_utc >= v; },
    until: function (r, v) { return r.created_at_utc <= v; },
    modified_since: function (r, v) { return (r.last_modified_at_utc || "") >= v; },
    modified_until: function (r, v) { return (r.last_modified_at_utc || "") <= v; },
    min_id: function (r, v) { return r.id >= +v; },
    max_id: function (r, v) { return r.id <= +v; },
    kind: function (r, v) { return r.kind === v; },
    date: function (r, v) { return r.created_at_utc.slice(0, 10) === v; },
    done: function (r, v) { return !!r.done_bool === (v === "1" || v === "true"); },
    q: function (r, v) { v = v.toLowerCase(); return (r.title || "").toLowerCase().indexOf(v) >= 0 || (r.content || "").toLowerCase().indexOf(v) >= 0; },
  };
  function select(qs) {
    var d = qs.get("deleted"), out = [];
    state.rows.forEach(function (r) {
      if (d === "all" || d === "any" ? true : d === "1" || d === "true" ? r.deleted : !r.deleted) out.push(r);
    });
    Object.keys(FILTERS).forEach(function (k) {
      var v = qs.get(k);
      if (v != null && v !== "") out = out.filter(function (r) { return FILTERS[k](r, v); });
    });
    var key = qs.get("order") || "id", rev = (qs.get("dir") || "desc") !== "asc";
    out.sort(function (a, b) {
      var x = a[key], y = b[key];
      return ((x < y ? -1 : x > y ? 1 : 0) || a.id - b.id) * (rev ? -1 : 1);
    });
    if (qs.get("content") === "0") out = out.map(function (r) { var o = Object.assign({}, r); delete o.content; delete o.sealed; return o; });
    return out;
  }
  function clen(r) { r.content_length = new TextEncoder().encode(r.content || "").length; return r; }
  var COLS = ["kind", "title", "content", "value_int", "value_float", "done_bool", "deleted",
              "created_at_utc", "start_date", "end_date", "classification", "sealed"];
  function apply(r, body) {
    var o = Object.assign({}, r);
    COLS.forEach(function (k) { if (body[k] !== undefined) o[k] = body[k]; });
    if (body.restore) o.deleted = 0;
    o.last_modified_at_utc = nowStamp();
    // a Secret row keeps its columns empty, as lcars_vault.h has the server do
    if (Number(o.classification) === 2) { o.title = ""; o.content = ""; o.value_int = 0; o.value_float = 0; }
    else o.sealed = "";
    clen(o);
    if (o.sealed) o.content_length = o.sealed.length;
    return o;
  }
  var json = function (code, data) { return { code: code, data: data }; };
  var off = function (what) { return json(503, { error: what + " needs the journal's server, and this demo has none" }); };

  function route(method, path, qs, body, headers) {
    var m;
    if (path === "/health") return json(200, { ok: true, demo: true });
    if (path === "/stats") {
      var all = select(qs), newest = "", last = "";
      all.forEach(function (r) {
        if (r.created_at_utc > newest) newest = r.created_at_utc;
        if ((r.last_modified_at_utc || "") > last) last = r.last_modified_at_utc;
      });
      return json(200, { count: all.length, kinds: new Set(all.map(function (r) { return r.kind; })).size,
                         done: all.filter(function (r) { return r.done_bool; }).length,
                         newest_created_at_utc: newest, last_modified_at_utc: last });
    }
    if (path === "/dump" && method === "GET") return json(200, select(qs));
    if (path === "/entries" && method === "GET") {
      var lim = +(qs.get("limit") || 100), from = +(qs.get("offset") || 0);
      if (!(lim >= 1 && lim <= 1000)) return json(400, { error: "Invalid 'limit' (1..1000)" });
      return json(200, select(qs).slice(from, from + lim));
    }
    if (path === "/entries" && method === "POST") {
      // the outbox sends a create again when it cannot tell whether the
      // first landed; the key makes the second the first's answer
      var key = headers["idempotency-key"];
      if (key && state.keys[key]) return json(201, { status: "success", id: state.keys[key] });
      var at = body.created_at_utc || nowStamp();
      var row = apply({ id: state.next++, kind: "", title: "", content: "", value_int: 0, value_float: 0,
                        done_bool: 0, deleted: 0, created_at_utc: at, start_date: "", end_date: "" }, body);
      if (!row.kind) row.kind = "personal_log";
      if (!row.title && Number(row.classification) !== 2) row.title = "HTTP Entry";
      state.rows.set(row.id, row);
      keep(row);
      if (key) state.keys[key] = row.id;
      return json(201, { status: "success", id: row.id });
    }
    if ((m = /^\/entries\/(\d+)$/.exec(path))) {
      var r = state.rows.get(+m[1]);
      if (!r) return json(404, { error: "Entry " + m[1] + " not found" });
      if (method === "GET") return json(200, r);
      if (method === "PUT" || method === "PATCH" || method === "DELETE") {
        var n = method === "DELETE" ? Object.assign({}, r, { deleted: 1, last_modified_at_utc: nowStamp() }) : apply(r, body || {});
        state.rows.set(n.id, n);
        keep(n);
        return json(200, { status: "success", id: n.id, updated: 1 });
      }
    }
    if ((m = /^\/entries\/(\d+)\/(append|title)$/.exec(path)) && method === "POST") {
      var t = state.rows.get(+m[1]);
      if (!t) return json(404, { error: "Entry " + m[1] + " not found" });
      var u = m[2] === "title" ? apply(t, { title: body.title || t.title })
        : apply(t, { content: (t.content || "").replace(/\n*$/, "\n") + (body.text || body.content || "") });
      state.rows.set(u.id, u);
      keep(u);
      return json(200, { status: "success", id: u.id });
    }
    if ((m = /^\/entries\/(\d+)\/media$/.exec(path))) {
      if (method !== "GET") return off("Attaching a file");
      return json(200, state.media.filter(function (x) { return x.entry_id === +m[1]; }));
    }
    if (/^\/entries\/\d+\/media\//.test(path)) return off("Changing a file");
    if (/^\/entries\/\d+\/caldav$/.test(path)) return off("Reminders (CalDAV)");
    if (path === "/vault" && method === "GET") return json(200, { version: state.vaultV || 0, vault: state.vault || null });
    if (path === "/vault" && method === "PUT") {
      if ((body.version || 0) !== (state.vaultV || 0)) return json(409, { error: "the vault changed: read it again" });
      state.vault = body.vault;
      state.vaultV = (state.vaultV || 0) + 1;
      lsPut(VAULT, Object.assign(lsJSON(VAULT, null) || {}, { vault: state.vault, version: state.vaultV }));
      return json(200, { status: "ok", version: state.vaultV });
    }
    if (path === "/media" && method === "GET") return json(200, state.media);
    if (path === "/reports" && method === "GET") return json(200, []);
    // GET /kinds/roles (lcars_kinds.h): every role its default, as a new
    // journal's. The table is the page's own copy (KIND_ROLES, a top-level
    // const of the console's script, read when a request comes, after it
    // has run); the demo has no mapping to write, so PUT is refused.
    if (path === "/kinds/roles" && method === "GET") {
      var live = {};
      state.rows.forEach(function (x) { if (!x.deleted) live[x.kind] = (live[x.kind] || 0) + 1; });
      var tab = typeof KIND_ROLES !== "undefined" ? KIND_ROLES : [];
      return json(200, { entry: null, error: "", roles: tab.map(function (r) {
        return { role: r[0], what: "", kind: r[1], kinds: [r[1]], "default": r[1], list: r[2], set: false, name: "",
                 rows: live[r[1]] || 0 };
      }) });
    }
    if (path === "/kinds/roles") return off("Changing the kinds");
    // GET/PUT /theme (lcars_theme.h): the demo keeps no entry for it - the
    // theme stays this browser's own (localStorage), and a write is taken
    // as done so the picker says nothing it need not
    if (path === "/theme" && (method === "GET" || method === "PUT"))
      return json(200, { name: method === "PUT" && body.name || "lcars", fmt: method === "PUT" && body.text ? "omarchy" : "builtin",
                         text: method === "PUT" && body.text || "", entry: null, error: "" });
    if (path === "/embeddings" && method === "GET") {
      var e = state.emb;
      if (!e) return off("The star chart");
      var live = 0;
      state.rows.forEach(function (x) { if (!x.deleted) live++; });
      var since = qs.get("since") || "";
      return json(200, { model: e.model, dim: e.dim, live: live, done: e.rows.length, mark: e.mark,
                         rows: since && since >= e.mark ? [] : e.rows });
    }
    if (path === "/embed") return off("Search by meaning");
    if (path === "/events") return json(404, { error: "No route for GET /events" });
    if (path === "/maps") return json(404, { error: "No route for GET /maps" });
    if (path === "/engineer" || path === "/engineer/") return json(200, { engineers: [] });
    if (path === "/engineer/queue") return json(200, { seat: {}, deploys: [], live: {}, deploy: {}, now: Math.floor(Date.now() / 1000) });
    if (path.indexOf("/engineer/") === 0) return off("The engineers");
    if (path.indexOf("/say") === 0) return off("A voice for the computer");
    if (path === "/transcribe") return off("Dictation to text");
    if (path.indexOf("/tapes") === 0) return off("Recording a tape");
    if (path.indexOf("/chat/media") === 0) return off("Attaching a file");
    if (path.indexOf("/caldav") === 0) return off("Reminders (CalDAV)");
    return json(404, { error: "No route for " + method + " " + path });
  }

  // The computer, the navigator and the crew talk through POST /chat, a
  // stream of claude's events: the demo's answer is one of them, a reply
  // saying why there is no one to answer, then the end of the turn.
  function chatReply() {
    var say = NOTE + ", so the ship's computer, the navigator and the crew cannot answer here. " +
      "On your own LCARS they are a Claude session with your journal to read.";
    var ev = function (o) { return "data: " + JSON.stringify(o) + "\n\n"; };
    return new Response(ev({ type: "result", subtype: "success", is_error: false, result: say }) +
                        ev({ type: "lcars_exit", code: 0 }),
                        { status: 200, headers: { "Content-Type": "text/event-stream" } });
  }

  function answer(method, url, init) {
    var path = url.pathname.slice(new URL(BASE).pathname.length) || "/";
    if (path === "/chat" && method === "POST") return Promise.resolve(chatReply());
    return load().then(function () {
      var body = null;
      if (init && typeof init.body === "string" && init.body) {
        try { body = JSON.parse(init.body); } catch (e) { return json(400, { error: "not JSON" }); }
      } else if (init && init.body) {
        return off("Sending a file");
      }
      var h = {}, src = (init && init.headers) || {};
      if (typeof Headers === "function" && src instanceof Headers) src.forEach(function (v, k) { h[k.toLowerCase()] = v; });
      else Object.keys(src).forEach(function (k) { h[k.toLowerCase()] = src[k]; });
      try { return route(method, path, url.searchParams, body || {}, h); }
      catch (e) { return json(e.code || 500, { error: e.message || String(e) }); }
    }, function (e) {
      return json(503, { error: "the demo's journal did not load: " + (e.message || e) });
    }).then(function (res) {
      return new Response(res.data == null ? "" : JSON.stringify(res.data),
                          { status: res.code, headers: { "Content-Type": "application/json" } });
    });
  }

  window.fetch = function (input, init) {
    var url;
    try { url = new URL(typeof input === "string" ? input : input.url, location.href); }
    catch (e) { return realFetch(input, init); }
    var mine = url.href === BASE || url.href.indexOf(BASE + "/") === 0;
    var method = ((init && init.method) || (typeof input === "object" && input.method) || "GET").toUpperCase();
    // the pictures: files of the folder's own, under api/media/
    if (!mine || (method === "GET" || method === "HEAD") && url.pathname.indexOf(new URL(BASE).pathname + "/media/") === 0)
      return realFetch(input, init);
    if (init && init.signal && init.signal.aborted)
      return Promise.reject(new DOMException("The operation was aborted.", "AbortError"));
    return answer(method, url, init);
  };

  window.LCARS_DEMO = { base: BASE, note: NOTE, reset: reset, ready: load, password: DEMO_PW };
})();
