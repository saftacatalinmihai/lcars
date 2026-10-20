/* An in-memory stand-in for the LCARS HTTP API. The real database is never
   touched by the tests: everything here lives and dies with the process. */
var DB = JSON.parse(JSON.stringify(FIX));
var DBLOG = [];
var DUMP_ON = false;
// The embeddings (the star chart). Off - a server too old to have them, 404 -
// unless a test sets EMB to {model, dim, rows: [[id, base64, embedded_at]]};
// EMB_CODE is the status an off server answers with, EMBQ(text) the base64
// vector POST /embed answers.
var EMB = null, EMB_CODE = 404, EMBQ = null;
// GET /media, every attachment (the media view). Null answers 404, a server
// from before the route; a test sets it to the rows it wants listed.
var MEDIA = null;
// GET /reports, the published reports, newest first; null answers 404.
var REPORTS = null;
// GET /features (lcars_features.h): null answers 404, a server from before
// the route; a number answers that status (403, a limited login); else the
// object it answers.
var FEATURES = null;
// /entries/<id>/caldav: a task's kept iCalendar lines, keyed by id. CDAV_NEXT
// is a one-shot status for the next PUT (412: Reminders wrote meanwhile).
var CDAV = {}, CDAV_SEQ = 0, CDAV_NEXT = 0;
// Kinds whose list was deleted in Reminders (hidden, not published).
var CDAV_HIDDEN = {};
var KINDS_CODE = 0;
function kindsAnswer() {
  var live = {};
  DB.forEach(function (e) { if (!e.deleted) live[e.kind] = (live[e.kind] || 0) + 1; });
  return { entry: null, error: "", roles: C_KIND_ROLES.map(function (r) {
    var m = KINDMAP[r[0]], kinds = m && m.kind ? String(m.kind).split(",") : [r[1]];
    return { role: r[0], what: "", kind: kinds.join(","), kinds: kinds, "default": r[1], list: r[2],
             set: !!(m && m.kind), name: (m && m.name) || "",
             rows: kinds.reduce(function (n, k) { return n + (live[k] || 0); }, 0) };
  }) };
}
function cdavTaskish(k) { return k === "task" || /^task_./.test(k || ""); }
function dbFind(id) { for (var i = 0; i < DB.length; i++) if (DB[i].id === +id) return DB[i]; return null; }
function clen(r) { r.content_length = new TextEncoder().encode(r.content || "").length; }

function route(method, path, qs, body) {
  DBLOG.push(method + " " + path + (body ? " " + JSON.stringify(body) : ""));
  var m = /^\/entries\/(\d+)$/.exec(path);
  // a listening key for Deepgram (lcars_say.h); TEST.sayToken: the status
  if (path === "/say/token") {
    var ts = TEST.sayToken || 200;
    return ts === 200 ? { code: 200, data: { access_token: "aaaa.bbbb.cccc", expires_in: 30 } }
                      : { code: ts, data: { error: "no listening", status: ts } };
  }
  if (path === "/stats") {
    var rows = scope(qs.get("deleted"));
    var newest = "";
    for (var i = 0; i < rows.length; i++) if (rows[i].created_at_utc > newest) newest = rows[i].created_at_utc;
    return { code: 200, data: { count: rows.length, newest_created_at_utc: newest } };
  }
  var cdm = /^\/entries\/(\d+)\/caldav$/.exec(path);
  if (cdm) {
    var cr = dbFind(cdm[1]);
    if (!cr) return { code: 404, data: { error: "No entry " + cdm[1] } };
    var cview = function () {
      var c = CDAV[cr.id] || { extra: "", seq: 0 };
      var listed = cdavTaskish(cr.kind) && !CDAV_HIDDEN[cr.kind];
      var live = listed && !cr.deleted;
      var seg = cr.kind === "task" || !listed ? "tasks" : cr.kind;
      var name = !listed ? "" : cr.kind === "task" ? "LCARS Tasks"
        : cr.kind.slice(5).charAt(0).toUpperCase() + cr.kind.slice(6).replace(/_/g, " ");
      return { code: 200, data: { entry_id: cr.id, task_kind: "task", list: name, list_kind: listed ? cr.kind : "",
        synced: live, stored: !!CDAV[cr.id],
        href: "/caldav/calendars/" + seg + "/lcars-" + cr.id + ".ics", uid: "lcars-" + cr.id + "@lcars",
        last_modified_at_utc: cr.last_modified_at_utc, extra_ical: c.extra, extra_vcal: "",
        ics: live ? "BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nSUMMARY:" + cr.title + "\r\n" +
                    c.extra.split("\n").filter(Boolean).join("\r\n") + "\r\nEND:VTODO\r\nEND:VCALENDAR\r\n" : "",
        etag: live ? '"' + cr.id + "-" + c.seq + '"' : "" } };
    };
    if (method === "GET") return cview();
    if (method !== "PUT") return { code: 405, data: { error: "no" } };
    if (CDAV_NEXT) { var cc = CDAV_NEXT; CDAV_NEXT = 0;
      return { code: cc, data: { error: "The task changed since it was read; reload it" } }; }
    if (!cdavTaskish(cr.kind) || CDAV_HIDDEN[cr.kind]) return { code: 409, data: { error: "not a task" } };
    var cur = cview().data;
    if (body.etag && body.etag !== cur.etag) return { code: 412, data: { error: "The task changed since it was read; reload it" } };
    if (/^SUMMARY/m.test(body.extra_ical)) return { code: 400, data: { error: "line 1: SUMMARY comes from the entry itself" } };
    CDAV[cr.id] = { extra: body.extra_ical.split("\n").filter(function (l) { return l.trim(); }).join("\n") + (body.extra_ical.trim() ? "\n" : ""),
                    seq: ++CDAV_SEQ };
    cr.last_modified_at_utc = "2099-01-01 00:00:00";
    return cview();
  }
  // the report viewer's HEAD before it frames one: there if REPORTS lists it
  if (/^\/media\/reports\//.test(path) && method === "HEAD") {
    var rp = decodeURIComponent(path.slice(1));
    return (REPORTS || []).some(function (x) { return x.path === rp; })
      ? { code: 200, data: null } : { code: 404, data: { error: "no such file" } };
  }
  // GET/PUT /kinds/roles (lcars_kinds.h): KINDMAP is the mapping gen.py
  // found (the journal's `kinds` entry, or $LCARS_TEST_KINDS); KINDS_CODE a
  // status to answer instead (404: a server older than the route; 403 for a
  // PUT by a limited login).
  if (path === "/kinds/roles" && (method === "GET" || method === "PUT")) {
    if (KINDS_CODE) return { code: KINDS_CODE, data: { error: KINDS_CODE === 403 ? "the owner's login only" : "no such route" } };
    if (method === "PUT") {
      var pb = typeof body === "string" ? JSON.parse(body) : body;
      Object.keys(pb).forEach(function (r) {
        if (pb[r] === null) delete KINDMAP[r];
        else KINDMAP[r] = { kind: pb[r].kind, name: pb[r].name || "" };
      });
    }
    return { code: 200, data: kindsAnswer() };
  }
  if (path === "/features" && method === "GET") {
    return typeof FEATURES === "number" ? { code: FEATURES, data: { error: "the owner's login only" } }
      : FEATURES ? { code: 200, data: FEATURES } : { code: 404, data: { error: "no such route" } };
  }
  if (path === "/reports" && method === "GET") {
    return REPORTS ? { code: 200, data: REPORTS } : { code: 404, data: { error: "no such route" } };
  }
  if (path === "/media" && method === "GET") {
    return MEDIA ? { code: 200, data: MEDIA } : { code: 404, data: { error: "no such route" } };
  }
  if (m && method === "GET") {
    var r = dbFind(m[1]);
    return r ? { code: 200, data: r } : { code: 404, data: { error: "no such entry" } };
  }
  if (m && method === "PUT") {
    var r2 = dbFind(m[1]);
    if (!r2) return { code: 404, data: { error: "no such entry" } };
    for (var k in body) if (k !== "id" && k !== "last_modified_at_utc") r2[k] = body[k];
    if (body.last_modified_at_utc !== undefined) DBLOG.push("!! PUT carried last_modified_at_utc");
    r2.last_modified_at_utc = "2099-01-01 00:00:00";
    clen(r2);
    return { code: 200, data: { ok: true } };
  }
  // PATCH: the server's partial update; an if_modified is compared as the
  // UPDATE's WHERE does (412 moved, 409 deleted) and is never a column
  if (m && method === "PATCH") {
    var rp2 = dbFind(m[1]);
    if (!rp2) return { code: 404, data: { error: "no such entry" } };
    if (body.if_modified !== undefined) {
      if (rp2.deleted) return { code: 409, data: { error: "deleted" } };
      if (String(body.if_modified) !== String(rp2.last_modified_at_utc)) return { code: 412, data: { error: "the entry changed since it was read" } };
    }
    for (var kp in body) if (kp !== "id" && kp !== "last_modified_at_utc" && kp !== "if_modified") rp2[kp] = body[kp];
    rp2.last_modified_at_utc = "2099-01-01 00:00:0" + (TEST.patchSeq = ((TEST.patchSeq || 0) + 1) % 10);
    clen(rp2);
    return { code: 200, data: { ok: true } };
  }
  if (m && method === "DELETE") {
    var r3 = dbFind(m[1]);
    if (!r3) return { code: 404, data: { error: "no such entry" } };
    r3.deleted = 1; r3.last_modified_at_utc = "2099-01-01 00:00:00";
    return { code: 200, data: { ok: true } };
  }
  if (path === "/entries" && method === "POST") {
    var max = 0;
    for (var j = 0; j < DB.length; j++) if (DB[j].id > max) max = DB[j].id;
    var row = { id: max + 1, kind: "", title: "", content: "", value_int: 0, value_float: 0,
                done_bool: 0, deleted: 0, created_at_utc: "", last_modified_at_utc: "",
                start_date: "", end_date: "" };
    for (var k2 in body) row[k2] = body[k2];
    if (!row.last_modified_at_utc) row.last_modified_at_utc = row.created_at_utc;
    // lcars_http.h's HandlePostEntry does this, and a fake that did not was
    // how a caller sending title:"" got a blank title here and the server's
    // placeholder in production.
    if (!row.title) row.title = "HTTP Entry";
    clen(row);
    DB.push(row);
    return { code: 201, data: { id: row.id } };
  }
  // GET /dump is /entries without the page cap. Off unless a test turns it on,
  // so everything written before it existed still exercises the paged sweep —
  // which is also exactly what the page sees against an older server.
  if (path === "/dump" && method === "GET") {
    if (!DUMP_ON) return { code: 404, data: { error: "No route for GET /dump" } };
    if (qs.get("limit") || qs.get("offset")) return { code: 400, data: { error: "no limit/offset" } };
    var dq = new URLSearchParams(qs.toString());
    dq.set("limit", "1000");
    var dall = [];
    for (var doff = 0; ; doff += 1000) {
      dq.set("offset", String(doff));
      var dp = route("GET", "/entries", dq, null).data;
      DBLOG.pop();
      dall = dall.concat(dp);
      if (dp.length < 1000) break;
    }
    return { code: 200, data: dall };
  }
  if (path === "/embeddings" && method === "GET") {
    if (!EMB) return { code: EMB_CODE, data: { error: "No route for GET /embeddings" } };
    var since = qs.get("since") || "", mark = since;
    var live = DB.filter(function (r) { return !r.deleted; });
    var out = EMB.rows.filter(function (r) {
      var e = dbFind(r[0]);
      return e && !e.deleted && r[2] >= since;
    });
    out.forEach(function (r) { if (r[2] > mark) mark = r[2]; });
    return { code: 200, data: { model: EMB.model, dim: EMB.dim, live: live.length,
                                done: EMB.rows.length,
                                rows: out.map(function (r) { return [r[0], r[1]]; }),
                                mark: mark } };
  }
  if (path === "/embed" && method === "POST") {
    if (!EMB || !EMBQ) return { code: EMB ? 503 : 404, data: { error: "no /embed" } };
    return { code: 200, data: { model: EMB.model, dim: EMB.dim, vec: EMBQ(body.text) } };
  }
  if (path === "/entries" && method === "GET") {
    var list = scope(qs.get("deleted")).slice();
    var mx = qs.get("max_id");
    if (mx) list = list.filter(function (r) { return r.id <= +mx; });
    // the two the mirror's sync asks with (lcars_http.h's BuildEntryFilter)
    var mn = qs.get("min_id");
    if (mn) list = list.filter(function (r) { return r.id >= +mn; });
    var ms = qs.get("modified_since");
    if (ms) list = list.filter(function (r) { return (r.last_modified_at_utc || "") >= ms; });
    var key = qs.get("order") || "id";
    var rev = (qs.get("dir") || "desc") === "desc";
    list.sort(function (a, b) {
      var x = a[key], y = b[key];
      return (x < y ? -1 : x > y ? 1 : 0) * (rev ? -1 : 1);
    });
    var off = +(qs.get("offset") || 0), lim = +(qs.get("limit") || 100);
    if (lim < 1 || lim > 1000) return { code: 400, data: { error: "Invalid 'limit' (1..1000)" } };
    var page = list.slice(off, off + lim);
    // content=0 is what the initial sweep uses: every column except the body,
    // which is most of the bytes. The key is absent, not empty.
    if (qs.get("content") === "0") {
      page = page.map(function (r) {
        var o = {};
        for (var k in r) if (k !== "content") o[k] = r[k];
        return o;
      });
    }
    return { code: 200, data: page };
  }
  return { code: 404, data: { error: "not found" } };
}
function scope(d) {
  if (d === "all") return DB;
  if (d === "1") return DB.filter(function (r) { return r.deleted; });
  return DB.filter(function (r) { return !r.deleted; });
}

function fetch(url, init) {
  var u = String(url).replace(/^https?:\/\/[^/]+/, "");
  TEST.fetches.push(((init && init.method) || "GET") + " " + u);
  var qi = u.indexOf("?");
  var path = qi < 0 ? u : u.slice(0, qi);
  var qs = new URLSearchParams(qi < 0 ? "" : u.slice(qi + 1));
  var res;
  try {
    res = route((init && init.method) || "GET", path, qs,
                init && init.body ? JSON.parse(init.body) : null);
  } catch (e) { res = { code: 500, data: { error: String(e) } }; }
  return Promise.resolve({
    ok: res.code < 400, status: res.code, statusText: "err",
    text: function () { return Promise.resolve(JSON.stringify(res.data)); },
  });
}
