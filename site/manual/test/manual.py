#!/usr/bin/env python3
"""The manual kept true to the app (docs/design/manual.md, "The check"):

  (a) the committed builds, the landing's site/landing/public/manual/ and
      the app's lcars-ui/manual/, are what build.py makes of the source now
      (pages, pictures, and the appendices from index.html's KEYS and VCMDS:
      a changed help string makes both stale; the app's copy is the same
      pages, so (b) to (d) hold it too);
  (b) every "computer, ..." the pages quote is an order VCMDS knows (its
      say or an alias, a {*} or {n} in it standing for any words);
  (c) every key the pages name in bold (**n**, **[**, **Ctrl+S**) is one
      KEYS has; the appendix itself is KEYS, made at every build;
  (d) every label marked **label**{ui} is text in lcars-ui/index.html (its
      entities read; an N, a number or a … in the label stands for what
      the page fills in: "Delete N" is "Delete " found);
  and the report's inline build stays under 400 KB, and every #anchor the
  pages link has its heading.

  python3 site/manual/test/manual.py      (~1s; node for cmds.js)
Run by lcars-ui/test/run.sh, every run: a change to the console that the
manual describes fails here until the page is updated and rebuilt."""
import html, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build  # noqa: E402

PAGES = sorted((HERE.parent / "pages").glob("*.md"))
INLINE_MAX = 400 * 1024
# one-character bold spans that are buttons drawn as a glyph, not keys
GLYPHS = {"+", "⋯", "▶", "◎", "☰", "■", "−"}
# keys by more than one character, as the pages write them
LONG_KEYS = {"Ctrl+S": "s", "⌘S": "s", "Esc": "Escape", "Enter": "Enter", "Space": " "}


def norm(s):
    return s.replace("’", "'").replace("‘", "'").strip().lower()


def order_re(p):
    p = re.escape(norm(p))
    return re.compile(p.replace(r"\{\*\}", ".+").replace(r"\{n\}", r"\S+") + r"$")


def main():
    fails = []
    cmds = build.commands()
    text = {p.name: p.read_text(encoding="utf-8") for p in PAGES}

    # (a)
    bad = build.stale(cmds)
    if bad:
        fails.append("(a) a committed build of the manual is stale (" + ", ".join(bad[:6]) +
                     "): run python3 site/manual/build.py and commit what it writes")

    # (b)
    orders = [order_re(o) for x in cmds["v"] if "say" in x for o in [x["say"]] + list(x["alias"])]
    n_b = 0
    for name, s in text.items():
        for m in re.finditer(r'"[Cc]omputer, ([^"]+)"', s):
            said = re.sub(r"[.,…]+$", "", m.group(1)).strip()
            if not said:
                continue
            n_b += 1
            if not any(o.match(norm(said)) for o in orders):
                fails.append(f'(b) {name}: "computer, {said}" is no order in VCMDS')

    # (c)
    keys = set()
    for x in cmds["k"]:
        if x.get("key"):
            keys.add(x["key"])
        for t in (x.get("label") or "").split():
            keys.add(t)
    n_c = 0
    for name, s in text.items():
        for m in re.finditer(r"\*\*([^*\s]{1,6})\*\*(?!\{ui\})", s):
            k = m.group(1)
            if len(k) > 1 and k not in LONG_KEYS:
                continue
            if k in GLYPHS:
                continue
            n_c += 1
            if LONG_KEYS.get(k, k) not in keys and k not in keys:
                fails.append(f"(c) {name}: the key **{k}** is not in KEYS")

    # (d)
    page = html.unescape(build.PAGE.read_text(encoding="utf-8"))
    n_d = 0
    for name, s in text.items():
        for m in re.finditer(r"\*\*([^*]+)\*\*\{ui\}", s):
            label, n_d = m.group(1), n_d + 1
            parts = [p.strip() for p in re.split(r"\bN\b|…|\d+", label)]
            parts = [p for p in parts if len(p) >= 2] or [label]
            missing = [p for p in parts if p not in page]
            if missing:
                fails.append(f"(d) {name}: the label **{label}** is not in index.html ({missing[0]!r} not found)")

    # the report's size, and the anchors
    size = len(build.render(True, "0.0.0", cmds).encode())
    if size > INLINE_MAX:
        fails.append(f"the inline build is {size} bytes, over {INLINE_MAX}: smaller pictures")
    ids = {m for s in text.values() for m in re.findall(r"\{#([a-z0-9-]+)\}", s)} | {"contents"}
    for name, s in text.items():
        for a in re.findall(r"\]\(#([^)]+)\)", s):
            if a not in ids:
                fails.append(f"{name}: a link to #{a}, which no heading has")

    for f in fails:
        print("  FAIL " + f)
    print(f"manual: {n_b} spoken orders, {n_c} keys, {n_d} labels checked; inline {size} bytes; "
          + ("ok" if not fails else f"{len(fails)} failed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
