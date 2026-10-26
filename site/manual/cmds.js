// The console's own lists, for the manual's appendices and its check: VCMDS
// (the spoken orders) and KEYS (the keyboard help), cut out of
// lcars-ui/index.html and evaluated here, printed as JSON. Each array is
// taken from its `const NAME = [` line to the first `];` at a line's start,
// as both are written; their entries' functions are never run, and any name
// they mention resolves to a no-op (the `with` over a proxy), so the page's
// other code is not needed. node site/manual/cmds.js [index.html]
"use strict";
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(process.argv[2] || path.join(__dirname, "../../lcars-ui/index.html"), "utf8");

function cut(name) {
  const m = new RegExp("^const " + name + " = \\[$", "m").exec(src);
  if (!m) throw new Error("no `const " + name + " = [` line in index.html");
  const end = src.indexOf("\n];", m.index);
  if (end < 0) throw new Error("no `];` closing " + name);
  return src.slice(m.index + m[0].length - 1, end + 2);
}
const P = new Proxy({}, { has: (t, k) => !(k in globalThis) || k === "$", get: () => function () {} });
const ev = s => Function("P", "with(P){return " + s + "}")(P); // eslint-disable-line no-new-func

// the help strings are HTML; the manual escapes what it prints itself
const ENT = { mdash: "—", ndash: "–", rsquo: "’", lsquo: "‘", ldquo: "“", rdquo: "”", hellip: "…", nbsp: " ", amp: "&",
  middot: "·", larr: "←", rarr: "→", uarr: "↑", darr: "↓", times: "×", lt: "<", gt: ">", quot: '"' };
const text = s => String(s || "").replace(/<[^>]+>/g, "")
  .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
  .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d))
  .replace(/&([a-z]+);/g, (a, n) => ENT[n] || a);

const V = ev(cut("VCMDS")), K = ev(cut("KEYS"));
const out = {
  v: V.map(x => x.head ? { head: x.head } : { say: x.say, alias: x.alias || [], help: text(x.help) }),
  k: K.map(x => x.head ? { head: x.head }
    : { key: x.key === undefined ? null : x.key, label: text(x.label || x.key), help: text(x.help) }),
};
process.stdout.write(JSON.stringify(out));
