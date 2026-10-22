// The worker's contract, in node with nothing installed:
//   node --test site/landing/test/
// Each case calls src/worker.js's fetch with a stand-in D1 and assets.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { signup, LIMITS } from "../src/worker.js";
import { fakeD1 } from "./fake-d1.mjs";

const ORIGIN = "https://landing.test";
const env = () => ({ DB: fakeD1(), ASSETS: { fetch: async () => new Response("asset", { status: 200 }) }, RATE_SALT: "t" });
const post = (body, { type = "application/json", origin = ORIGIN, ip = "198.51.100.7", path = "/api/signup", method = "POST" } = {}) => {
  const h = { "content-type": type, "cf-connecting-ip": ip };
  if (origin) h.origin = origin;
  return new Request(ORIGIN + path, { method, headers: h, body: method === "GET" ? undefined : typeof body === "string" ? body : JSON.stringify(body) });
};
const call = async (e, req) => { const r = await worker.fetch(req, e); const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch {} return { r, j }; };
const good = { email: "Pat@Example.org", use: "a work log", consent: true };

test("a good signup is stored, lower-cased, with its line, consent and time", async () => {
  const e = env();
  const { r, j } = await call(e, post(good));
  assert.equal(r.status, 200);
  assert.deepEqual(j, { ok: true });
  assert.equal(e.DB.signups.length, 1);
  const s = e.DB.signups[0];
  assert.equal(s.email, "pat@example.org");
  assert.equal(s.use, "a work log");
  assert.equal(s.consent, 1);
  assert.match(s.created, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  assert.equal(r.headers.get("access-control-allow-origin"), null, "CORS stays closed");
  assert.equal(r.headers.get("cache-control"), "no-store");
});

test("the use line is optional, and an empty one is stored as null", async () => {
  const e = env();
  await call(e, post({ email: "a@b.io", consent: true }));
  assert.equal(e.DB.signups[0].use, null);
});

test("a second signup of the same address answers the same and keeps the first line", async () => {
  const e = env();
  await call(e, post(good));
  const { r, j } = await call(e, post({ ...good, email: "PAT@example.org", use: "overwrite" }, { ip: "203.0.113.9" }));
  assert.equal(r.status, 200);
  assert.deepEqual(j, { ok: true });
  assert.equal(e.DB.signups.length, 1);
  assert.equal(e.DB.signups[0].use, "a work log");
});

test("bad input is refused with a code, and nothing is written", async () => {
  const cases = [
    [{ consent: true }, "email_missing"],
    [{ email: "not-an-email", consent: true }, "email_invalid"],
    [{ email: "a@b", consent: true }, "email_invalid"],
    [{ email: "a b@c.de", consent: true }, "email_invalid"],
    [{ email: "<a@b.cd>", consent: true }, "email_invalid"],
    [{ email: "x".repeat(250) + "@b.cd", consent: true }, "email_invalid"],
    [{ email: "a@b.cd", consent: true, use: "u".repeat(LIMITS.use + 1) }, "use_too_long"],
    [{ email: "a@b.cd" }, "consent_missing"],
    [{ email: "a@b.cd", consent: false }, "consent_missing"],
    [{ email: "a@b.cd", consent: "no" }, "consent_missing"],
  ];
  for (const [body, code] of cases) {
    const e = env();
    const { r, j } = await call(e, post(body));
    assert.equal(r.status, 400, JSON.stringify(body));
    assert.equal(j.error, code, JSON.stringify(body));
    assert.ok(j.message);
    assert.equal(e.DB.signups.length, 0);
  }
});

test("control and bidi characters are taken out of the line", async () => {
  const e = env();
  await call(e, post({ ...good, use: "diary\u202e\u0007 and\n\ttasks " }));
  assert.equal(e.DB.signups[0].use, "diary and tasks");
});

test("the honeypot is told it worked, and nothing is written", async () => {
  const e = env();
  const { r, j } = await call(e, post({ ...good, website: "http://spam.example" }));
  assert.equal(r.status, 200);
  assert.deepEqual(j, { ok: true });
  assert.equal(e.DB.signups.length, 0);
  assert.equal(e.DB.rate.length, 0);
});

test("another origin is refused; no origin (curl) goes on to the checks", async () => {
  const e = env();
  let { r, j } = await call(e, post(good, { origin: "https://evil.example" }));
  assert.equal(r.status, 403);
  assert.equal(j.error, "origin");
  ({ r } = await call(e, post(good, { origin: null })));
  assert.equal(r.status, 200);
  assert.equal(e.DB.signups.length, 1);
});

test("the wrong method, type, size or JSON is refused", async () => {
  const e = env();
  let { r, j } = await call(e, post(null, { method: "GET" }));
  assert.equal(r.status, 405);
  assert.equal(r.headers.get("allow"), "POST");
  ({ r, j } = await call(e, post("email=a", { type: "text/plain" })));
  assert.equal(r.status, 415);
  ({ r, j } = await call(e, post("{not json")));
  assert.equal(j.error, "bad_json");
  ({ r, j } = await call(e, post("[1]")));
  assert.equal(j.error, "bad_json");
  ({ r, j } = await call(e, post({ ...good, use: "x".repeat(LIMITS.body) })));
  assert.equal(r.status, 413);
  ({ r, j } = await call(e, post(null, { method: "OPTIONS" })));
  assert.equal(r.status, 405);
  assert.equal(e.DB.signups.length, 0);
});

test("the rate limit: five from one address in ten minutes, then 429; another address is free", async () => {
  const e = env();
  const t0 = 1_800_000_000;
  for (let i = 0; i < LIMITS.perWindow; i++) {
    const r = await signup(post({ ...good, email: `p${i}@example.org` }), e, t0 + i);
    assert.equal(r.status, 200);
  }
  let r = await signup(post({ ...good, email: "late@example.org" }), e, t0 + 10);
  assert.equal(r.status, 429);
  assert.equal(r.headers.get("retry-after"), String(LIMITS.windowSec));
  assert.equal((await r.json()).error, "rate");
  r = await signup(post({ ...good, email: "other@example.org" }, { ip: "192.0.2.1" }), e, t0 + 11);
  assert.equal(r.status, 200);
  r = await signup(post({ ...good, email: "later@example.org" }), e, t0 + LIMITS.windowSec + 5);
  assert.equal(r.status, 200, "the window passes");
  assert.ok(!e.DB.signups.some((s) => s.email === "late@example.org"));
  // the address is never stored as itself, and old rows go
  assert.ok(e.DB.rate.every((x) => /^[0-9a-f]{64}$/.test(x.k)));
  await signup(post({ ...good, email: "much@later.org" }), e, t0 + LIMITS.keepSec + 100);
  assert.ok(e.DB.rate.every((x) => x.at >= t0 + 100));
});

test("a form posted without the script is answered by a redirect back with the outcome", async () => {
  const e = env();
  const form = "email=f%40example.org&use=&consent=on&website=";
  let { r } = await call(e, post(form, { type: "application/x-www-form-urlencoded" }));
  assert.equal(r.status, 303);
  assert.equal(r.headers.get("location"), ORIGIN + "/?signup=ok#join");
  assert.equal(e.DB.signups[0].email, "f@example.org");
  ({ r } = await call(e, post("email=f%40example.org", { type: "application/x-www-form-urlencoded" })));
  assert.equal(r.headers.get("location"), ORIGIN + "/?signup=consent_missing#join");
});

test("other paths: /api/* is a JSON 404, everything else the assets", async () => {
  const e = env();
  let { r, j } = await call(e, post(null, { method: "GET", path: "/api/list" }));
  assert.equal(r.status, 404);
  assert.equal(j.error, "not_found");
  const a = await worker.fetch(new Request(ORIGIN + "/index.html"), e);
  assert.equal(await a.text(), "asset");
});

test("a D1 failure is a 500 with a plain message, nothing thrown", async () => {
  const e = env();
  e.DB.prepare = () => { throw new Error("D1 down"); };
  const orig = console.error; console.error = () => {};
  const { r, j } = await call(e, post(good));
  console.error = orig;
  assert.equal(r.status, 500);
  assert.equal(j.error, "server");
});
