#!/usr/bin/env python3
"""The console's user manual (docs/design/manual.md), built from one source
into three pages:

  python3 site/manual/build.py           site/landing/public/manual/index.html
                                         and its img/: the landing site's
                                         /manual/, committed, the version a
                                         placeholder deploy.sh fills; and
                                         lcars-ui/manual/ (index.html, img/):
                                         the app's copy, committed, served at
                                         /ui/manual/ (and /manual) with the
                                         console it came with, so no number
  python3 site/manual/build.py --inline OUT [--version V]
                                         one file, the pictures as data: URIs
                                         and the version filled (default:
                                         lcars-ui/index.html's APP_VERSION):
                                         the report in the media store, never
                                         committed (the deploy writes it)
  python3 site/manual/build.py --check   exit 1 if a committed build (the
                                         landing's, the app's) is not what
                                         the source makes

The source: pages/*.md (a small Markdown subset: ##/### with {#id}, flat -
and 1. lists, | tables, ![alt](img/x.webp "caption"), **bold**, `code`,
[t](#anchor), and **label**{ui} for a label of the console checked by
test/manual.py), img/*.webp, and the appendices' tables, made at every build
from index.html's KEYS and VCMDS by cmds.js (node). No script in the page."""
import base64, html, json, pathlib, re, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PAGE = ROOT / "lcars-ui" / "index.html"
OUT = ROOT / "site" / "landing" / "public" / "manual"
# the app's copy, in the shipped lcars-ui/ (so in the embedded pack and the
# release too); its pictures beside it, as the landing's
APP_OUT = ROOT / "lcars-ui" / "manual"
# what deploy.sh (the landing) and the deploy's report step put the version in
# place of: the committed page must not go stale at every deploy's APP_VERSION
VERSION_MARK = "__VERSION__"

# Help strings written for the console's own help panel, in a few places in
# the code's words; the manual says them in the reader's.
PLAIN = [
    ("the toast offers it back", "the message at the bottom offers it back"),
    ("the toast offers them back", "the message at the bottom offers them back"),
    ("(the toast's Undo)", "(as Undo in the message does)"),
    ("Undo in the toast", "Undo in the message at the bottom"),
    ("in a toast", "in the message at the bottom"),
    ("done_bool = 1", "the entry marked done"),
    ("done_bool = 0", "the entry marked open"),
    ("write value_float (a whole number writes value_int too)", "the entry's number (Value, in Details)"),
    ("created_at back by that much", "when it was written, that much earlier"),
    ("created_at forward by that much", "when it was written, that much later"),
    ("start_date = now; the open entry counts up", "the open entry starts counting up from now"),
    ("start_date = when the entry was written", "counting from when the entry was written"),
    ("end_date = now", "the timer stopped now"),
    ("clear end_date and keep counting", "keep counting from where it stopped"),
    ("start_date and end_date both emptied", "the start and the end both cleared"),
    ("a row of the child's sleep kind", "an entry of the child's sleep kind"),
    ("a counter row titled with the thing", "a counter entry titled with the thing"),
    (", with PromQL-style queries", ""),
    ("this panel", "this list, in the console"),
    ("&times; on a chip drops it", "× on a chip drops it"),
    ("a Logseq shape", "a shape such as a task line"),
    ("The rendered day reader has a &#xFF0B; between every two entries for the same", "The day reader has a ＋ between every two entries for the same"),
]


def plain(s):
    for a, b in PLAIN:
        s = s.replace(a, b)
    return s


def inline(s):
    codes = []

    def keep(m):
        codes.append("<code>" + html.escape(m.group(1), quote=False) + "</code>")
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"`([^`]+)`", keep, s)
    s = html.escape(s, quote=False)
    # **label**{ui}: a label of the console, which test/manual.py finds in index.html
    s = re.sub(r"\*\*(.+?)\*\*(?:\{ui\})?", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def heading(line, toc):
    m = re.match(r"(#{2,3}) (.+?)(?: \{#([a-z0-9-]+)\})?$", line)
    lvl, text, hid = len(m.group(1)), m.group(2), m.group(3)
    if lvl == 2:
        toc.append((hid, text))
    return f'<h{lvl}{f" id={chr(34)}{hid}{chr(34)}" if hid else ""}>{inline(text)}</h{lvl}>'


def table(lines):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines if not re.match(r"^\|[-| :]+\|$", l.strip())]
    head, body = rows[0], rows[1:]
    return ('<div class="tw"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>" +
            "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")


def image(line, inline_pics):
    m = re.match(r'!\[([^\]]+)\]\(([^ )]+)(?: "([^"]*)")?\)$', line)
    alt, src, cap = m.groups()
    if inline_pics:
        src = "data:image/webp;base64," + base64.b64encode((HERE / src).read_bytes()).decode()
    return (f'<figure><img src="{html.escape(src)}" alt="{html.escape(alt)}" loading="lazy">' +
            (f"<figcaption>{inline(cap)}</figcaption>" if cap else "") + "</figure>")


def block(b, toc, inline_pics):
    lines = b.split("\n")
    if lines[0].startswith("#"):
        return heading(lines[0], toc) + ("\n" + block("\n".join(lines[1:]), toc, inline_pics) if len(lines) > 1 else "")
    if lines[0].startswith("!["):
        return image(lines[0], inline_pics)
    if lines[0].startswith("|"):
        return table(lines)
    if lines[0].startswith("- "):
        return "<ul>" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines) + "</ul>"
    if re.match(r"\d+\. ", lines[0]):
        return "<ol>" + "".join(f"<li>{inline(re.sub(r'^[0-9]+[.] ', '', l))}</li>" for l in lines) + "</ol>"
    return "<p>" + inline(" ".join(lines)) + "</p>"


def ref_table(items, left, right, keycol):
    out, rows = [], []

    def flush():
        if rows:
            out.append('<div class="tw"><table class="ref"><thead><tr><th>' + left + "</th><th>" + right +
                       "</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
            rows.clear()
    for x in items:
        if "head" in x:
            flush()
            out.append(f"<h3>{html.escape(x['head'])}</h3>")
            continue
        k = x[keycol]
        k = html.escape(k).replace("{*}", "{…}").replace("{n}", "{number}")
        rows.append(f'<tr><td class="k">{k}</td><td>{html.escape(plain(x["help"]), quote=False)}</td></tr>')
    flush()
    return "\n".join(out)


def app_version(page=PAGE):
    m = re.search(r'^const APP_VERSION = "([^"]+)";', page.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"build: no APP_VERSION in {page}")
    return m.group(1)


def commands(page=PAGE):
    """KEYS and VCMDS out of the page, by cmds.js: {"k": [...], "v": [...]}."""
    p = subprocess.run(["node", str(HERE / "cmds.js"), str(page)], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("build: cmds.js failed: " + p.stderr.strip()[-500:])
    return json.loads(p.stdout)


def render(inline_pics, version=VERSION_MARK, cmds=None, app=False):
    """The page as a string: pictures inline (the report) or as img/ files
    beside it (the landing, the app's copy). The app's copy names no version:
    it is served by the console it shipped with, so it is always that
    console's, and a number in it would need stamping at every deploy."""
    cmds = cmds if cmds is not None else commands()
    toc, parts = [], []
    for p in sorted((HERE / "pages").glob("*.md")):
        out = []
        for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8").strip()):
            if b.strip() == "{{KEYS}}":
                out.append(ref_table([x for x in cmds["k"] if "head" in x or x["help"]], "Key", "What it does", "label"))
            elif b.strip() == "{{PHRASES}}":
                out.append(ref_table(cmds["v"], "Say “computer, …”", "What it does", "say"))
            else:
                out.append(block(b, toc, inline_pics))
        parts.append("<section>" + "\n".join(out) + "</section>")
    toc_html = "<nav aria-label=\"Contents\"><h2 id=\"contents\">Contents</h2><ul class=\"toc\">" + "".join(
        f'<li><a href="#{i}">{inline(t)}</a></li>' for i, t in toc) + "</ul></nav>"
    return (TEMPLATE.replace("{{FONTS}}", "" if inline_pics or app else FONTS)
            .replace("{{HOME}}", APP_HOME if app else "" if inline_pics else HOME)
            .replace("{{VER}}", APP_VER if app else VER)
            .replace("{{VERSION}}", html.escape(version))
            .replace("{{TOC}}", toc_html).replace("{{BODY}}", "\n".join(parts)))


def landing(cmds=None, app=False):
    """The landing build (or with app, the app's copy), as {path under OUT
    (APP_OUT): bytes}."""
    files = {"index.html": render(False, cmds=cmds, app=app).encode()}
    for f in sorted((HERE / "img").glob("*.webp")):
        files["img/" + f.name] = f.read_bytes()
    return files


def committed(out=OUT):
    return {str(f.relative_to(out)): f.read_bytes() for f in sorted(out.rglob("*")) if f.is_file()} if out.is_dir() else {}


def stale(cmds=None):
    """What differs between the committed builds and fresh ones: a list of
    paths from the repo's root, [] when both are up to date."""
    cmds = cmds if cmds is not None else commands()
    bad = []
    for out, app in ((OUT, False), (APP_OUT, True)):
        want, have = landing(cmds, app), committed(out)
        rel = out.relative_to(ROOT).as_posix()
        bad += [f"{rel}/{k}" for k in sorted(set(want) | set(have)) if want.get(k) != have.get(k)]
    return bad


def main(argv):
    if argv[:1] == ["--check"]:
        bad = stale()
        if bad:
            print("manual: a committed build is not what the source makes (" + ", ".join(bad[:6]) +
                  "): run python3 site/manual/build.py and commit it", file=sys.stderr)
            return 1
        print("manual: the landing's and the app's builds are up to date")
        return 0
    if argv[:1] == ["--inline"]:
        if len(argv) not in (2, 4) or (len(argv) == 4 and argv[2] != "--version"):
            print("usage: build.py --inline OUT [--version V]", file=sys.stderr)
            return 2
        page = render(True, argv[3] if len(argv) == 4 else app_version())
        pathlib.Path(argv[1]).write_text(page, encoding="utf-8")
        print(f"{argv[1]}: {len(page.encode())} bytes")
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmds = commands()
    for out, app in ((OUT, False), (APP_OUT, True)):
        files = landing(cmds, app)
        if out.is_dir():
            shutil.rmtree(out)
        for k, v in files.items():
            (out / k).parent.mkdir(parents=True, exist_ok=True)
            (out / k).write_bytes(v)
        print(f"{out.relative_to(ROOT)}/: {len(files)} files, index.html {len(files['index.html'])} bytes")
    return 0


FONTS = """@font-face{font-family:'Antonio';font-style:normal;font-weight:100 900;font-display:swap;src:url(/fonts/antonio-latin.woff2) format('woff2')}
"""
HOME = """<a href="/">LCARS</a> · """
# ../ from /ui/manual/ (and the demo's manual/index.html) is the console
APP_HOME = """<a href="../">The console</a> · """
VER = """For LCARS {{VERSION}}, the web console only. The version beside <strong>LCARS</strong> at the top of your console says which one you have."""
APP_VER = """For the console it came with, the web console only. The version beside <strong>LCARS</strong> at the top of the console says which one that is."""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The console: a user manual</title>
<style>
{{FONTS}}:root{--orange:#ff9900;--amber:#ffcc66;--purple:#cc99cc;--blue:#9999ff;--sky:#99ccff;--red:#cc6666;--text:#e8e8e8;--dim:#a8a8a8;--bg:#000;--panel:#111}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:46rem;margin:0 auto;padding:0 18px 64px}
header.top{border-left:28px solid var(--orange);border-bottom:6px solid var(--orange);border-bottom-left-radius:28px;padding:22px 16px 14px;margin:16px 0 8px}
h1,h2,h3{font-family:Antonio,"Arial Narrow","Roboto Condensed","Helvetica Neue",sans-serif;font-stretch:condensed;text-transform:uppercase;letter-spacing:.06em;line-height:1.2}
h1{color:var(--orange);font-size:2.1rem;margin:0 0 6px}
.ver{color:var(--dim);margin:0}
h2{color:#000;background:var(--orange);font-size:1.25rem;padding:6px 14px;border-radius:0 22px 22px 0;margin:52px 0 14px}
section:nth-of-type(3n+2) h2{background:var(--purple)}
section:nth-of-type(3n+3) h2{background:var(--sky)}
h3{color:var(--amber);font-size:1.05rem;margin:28px 0 8px}
#contents{background:var(--blue)}
.toc{list-style:none;padding-left:0}.toc li{margin:4px 0}
a{color:var(--sky)}a:visited{color:var(--purple)}
strong{color:#fff}
code{font:.92em ui-monospace,Menlo,Consolas,monospace;background:var(--panel);border:1px solid #333;border-radius:4px;padding:0 4px;color:var(--amber);overflow-wrap:anywhere}
ul,ol{padding-left:1.4em}li{margin:5px 0}
figure{margin:20px 0;text-align:center}
img{max-width:100%;height:auto;border:2px solid #333;border-radius:14px}
figcaption{color:var(--dim);font-size:.9rem;margin-top:6px}
.tw{overflow-x:auto;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th{text-align:left;color:#000;background:var(--amber);padding:5px 8px;font-weight:600}
td{border-bottom:1px solid #2a2a2a;padding:6px 8px;vertical-align:top}
table.ref td.k{color:var(--amber);white-space:nowrap;font-weight:600}
@media (max-width:480px){body{font-size:16px}table.ref td.k{white-space:normal;min-width:7em}}
footer{color:var(--dim);font-size:.9rem;margin-top:56px;border-top:2px solid #333;padding-top:12px}
</style>
</head>
<body>
<main>
<header class="top">
<h1>The console: a user manual</h1>
<p class="ver">{{VER}}</p>
</header>
{{TOC}}
{{BODY}}
<footer>{{HOME}}LCARS is open source: <a href="https://github.com/saftacatalinmihai/lcars">github.com/saftacatalinmihai/lcars</a>. The pictures show a made-up journal.</footer>
</main>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
