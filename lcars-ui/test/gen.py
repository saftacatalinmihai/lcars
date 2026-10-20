#!/usr/bin/env python3
"""Assemble a runnable QuickJS bundle: shim + real page markup + real page
script + tests, with a fake API backed by real rows read out of the database."""
import json, os, re, sqlite3, sys

T = os.path.dirname(os.path.abspath(__file__))
UI = os.path.dirname(T)
src = open(os.path.join(UI, "index.html"), encoding="utf-8").read()

script = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))
body = re.search(r"<body>(.*?)</body>", src, re.S).group(1)
body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)

COLS = ["id","kind","title","content","value_int","value_float","done_bool",
        "deleted","created_at_utc","last_modified_at_utc","start_date","end_date"]
# $LCARS_TEST_DB points at another copy -- a laptop's lcars.db can predate
# the start_date/end_date migration, and a test must never be what migrates it
DB = os.environ.get("LCARS_TEST_DB") or os.path.join(os.path.dirname(UI), "lcars.db")
con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
con.row_factory = sqlite3.Row
# LCARS_TEST_NOW="2026-10-01 06:30:00" (UTC) runs the suite as if it were
# then: the page's clock reads that moment (and runs on from it), and the
# fixture is the journal as it stood, rows written later left out. The suite
# reads "today" all over (the calendar, the rail, the day bars), so a check
# that fails only on some days (the 1st of a month, a time-zone change) is
# found by running it on those days rather than waiting for them.
NOW = os.environ.get("LCARS_TEST_NOW", "")
if NOW and not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", NOW):
    sys.exit("gen.py: LCARS_TEST_NOW is YYYY-MM-DD HH:MM:SS, in UTC")
until = "WHERE created_at_utc <= :now" if NOW else ""
both = "AND created_at_utc <= :now" if NOW else ""
# The newest 300 rows, and 100 older ones taken evenly across the rest of the
# journal. The newest 400 alone could all land in one month (they did, in
# September 2026), and the suite needs a journal with a history: the month
# rail, the chart over time, the resurfacing of old entries.
rows = [dict(r) for r in con.execute(
    f"SELECT {','.join(COLS)} FROM entries {until} ORDER BY id DESC LIMIT 300", {"now": NOW})]
older = [dict(r) for r in con.execute(
    f"SELECT {','.join(COLS)} FROM entries WHERE id < :id {both} ORDER BY id DESC",
    {"id": rows[-1]["id"] if rows else 0, "now": NOW})]
step = max(1, len(older) // 100)
rows += older[step - 1::step][:100]
con.close()
for r in rows:
    r["content_length"] = len((r.get("content") or "").encode())

# Kinds by role (docs/design/kinds.md): the server's table, read out of
# lcars_kinds.h for the check that the page's copy agrees, and the mapping
# the fake GET /kinds/roles answers with - $LCARS_TEST_KINDS (a JSON file: the
# entry's content, or its "roles" object alone), else the journal's own
# `settings` entry titled `kinds`, else none (every role its default). So a
# run on a copy of the captain's journal runs with the captain's mapping.
csrc = open(os.path.join(os.path.dirname(UI), "lcars_kinds.h"), encoding="utf-8").read()
ctab = csrc[csrc.index("g_kind_roles[] = {"):]
ctab = ctab[:ctab.index("};")]
c_roles = [[m[0], m[1], m[2] == "true"] for m in
           re.findall(r'\{"([a-z_]+)",\s*"([a-z_]+)",\s*(?:"(?:[^"\\]|\\.)*"\s*)+,\s*(true|false)\}', ctab)]
kmap = {}
kfile = os.environ.get("LCARS_TEST_KINDS", "")
try:
    if kfile:
        kj = json.load(open(kfile, encoding="utf-8"))
    else:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        kr = con.execute("SELECT content FROM entries WHERE kind='settings' AND title='kinds' AND deleted=0"
                         " ORDER BY id LIMIT 1").fetchone()
        con.close()
        kj = json.loads(kr[0]) if kr else {}
    kmap = kj.get("roles", kj) if isinstance(kj, dict) else {}
except (ValueError, OSError, sqlite3.Error) as e:
    if kfile:
        sys.exit(f"gen.py: LCARS_TEST_KINDS {kfile}: {e}")

out = open(os.path.join(T, "run.js"), "w", encoding="utf-8")
if NOW:
    # Date with its clock moved: no arguments (and Date.now) read the pinned
    # moment plus the time since start; anything else is the real Date's
    out.write("""(function () {
  var D = Date, off = D.parse(%s) - D.now();
  function P() {
    if (!(this instanceof P)) return new D(D.now() + off).toString();
    if (!arguments.length) return new D(D.now() + off);
    return new (Function.prototype.bind.apply(D, [null].concat([].slice.call(arguments))))();
  }
  P.prototype = D.prototype; P.UTC = D.UTC; P.parse = D.parse;
  P.now = function () { return D.now() + off; };
  globalThis.Date = P;
})();
""" % json.dumps(NOW.replace(" ", "T") + "Z"))
out.write(open(os.path.join(T, "shim.js"), encoding="utf-8").read())
out.write("\n\n/* ===== fixture + fake api ===== */\n")
out.write("var FIX = JSON.parse(" + json.dumps(json.dumps(rows)) + ");\n")
out.write("var C_KIND_ROLES = " + json.dumps(c_roles) + ";\n")
out.write("var KINDMAP = " + json.dumps(kmap) + ";\n")
out.write(open(os.path.join(T, "api.js"), encoding="utf-8").read())
out.write("\n/* ===== page markup ===== */\n")
out.write("document.body.innerHTML = " + json.dumps(body) + ";\n")
out.write("\n/* ===== page script ===== */\n")
out.write(script)
# the public demo's server in the page (demo/static.js), as text: the suite
# runs it in a sandbox of stand-ins of its own, never over the page's globals
out.write("\nvar DEMO_STATIC_SRC = " + json.dumps(open(os.path.join(UI, "demo", "static.js"), encoding="utf-8").read()) + ";\n")
out.write("\n/* ===== tests ===== */\n")
out.write(open(os.path.join(T, "tests.js"), encoding="utf-8").read())
out.close()
print(f"run.js: {os.path.getsize(os.path.join(T,'run.js'))} bytes, {len(rows)} fixture rows")
