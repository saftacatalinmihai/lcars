#!/usr/bin/env node
// A local preview with nothing installed: public/ served as the assets
// binding would (its _headers applied, 404.html for a missing file), and
// /api/* handed to src/worker.js with an in-memory D1 (test/fake-d1.mjs).
//   node site/landing/preview.mjs [PORT]     # default 8790, 127.0.0.1 only
// `npx wrangler dev` runs the real runtime and a local D1 instead (README).
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import worker from "./src/worker.js";
import { fakeD1 } from "./test/fake-d1.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUB = path.join(HERE, "public");
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".mp4": "video/mp4", ".vtt": "text/vtt" };

// _headers: a path pattern line, then indented "Name: value" lines.
function headerRules() {
  const rules = [];
  for (const line of fs.readFileSync(path.join(PUB, "_headers"), "utf8").split("\n")) {
    if (!line.trim()) continue;
    if (!/^\s/.test(line)) rules.push({ re: new RegExp("^" + line.trim().replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$"), h: [] });
    else { const i = line.indexOf(":"); rules[rules.length - 1].h.push([line.slice(0, i).trim(), line.slice(i + 1).trim()]); }
  }
  return rules;
}
const RULES = headerRules();

const ASSETS = {
  async fetch(req) {
    let p = decodeURIComponent(new URL(req.url).pathname);
    if (p.endsWith("/")) p += "index.html";
    const f = path.normalize(path.join(PUB, p));
    let status = 200, file = f;
    if (!f.startsWith(PUB + path.sep) || path.basename(f) === "_headers" || !fs.existsSync(f) || !fs.statSync(f).isFile()) { status = 404; file = path.join(PUB, "404.html"); }
    const h = new Headers({ "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    for (const r of RULES) if (r.re.test(p)) for (const [k, v] of r.h) h.set(k, v);
    // deploy.sh fills __SITE__ with https://<host>; the preview with its own origin
    let data = fs.readFileSync(file);
    // and __EXPLAINER__ with the cut's R2 URL; the preview with the local copy
    // at public/video/explainer.mp4 (ignored), so it plays and no test reaches the bucket
    if (file.endsWith(".html"))
      data = data.toString("utf8").replaceAll("__SITE__", new URL(req.url).origin).replaceAll("__EXPLAINER__", "/video/explainer.mp4");
    return new Response(data, { status, headers: h });
  },
};

export function serve(port = 8790, env = { DB: fakeD1(), ASSETS }) {
  const srv = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const headers = new Headers();
    for (const [k, v] of Object.entries(req.headers)) headers.set(k, Array.isArray(v) ? v.join(", ") : v);
    headers.set("cf-connecting-ip", req.socket.remoteAddress || "");
    const r = await worker.fetch(new Request(`http://${req.headers.host}${req.url}`, { method: req.method, headers, body: req.method === "GET" || req.method === "HEAD" ? undefined : body }), env);
    res.writeHead(r.status, Object.fromEntries(r.headers));
    res.end(Buffer.from(await r.arrayBuffer()));
  });
  return new Promise((ok) => srv.listen(port, "127.0.0.1", () => ok({ srv, env })));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.argv[2] || 8790);
  const { env } = await serve(port);
  console.log(`preview: http://127.0.0.1:${port}/  (signups kept in memory, printed on Ctrl-C)`);
  process.on("SIGINT", () => { console.log(JSON.stringify(env.DB.signups, null, 1)); process.exit(0); });
}
