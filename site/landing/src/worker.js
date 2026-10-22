// The landing page's Worker: the page is static assets (public/, served by
// Cloudflare before this code runs), and this answers the one route that is
// not a file, POST /api/signup, into the D1 table in schema.sql.
//
// What it promises the visitor (the page's privacy note) is what it does:
// it keeps the email, an optional line on what they would use LCARS for, the
// consent and the time - nothing else. The address a request came from is
// kept only as a salted hash, for an hour, to count requests (the rate
// limit), and then deleted. No mail is sent from here: the list is read with
// list-signups.sh when hosted LCARS opens.
//
// CORS is closed: no Access-Control-* header is ever sent, so another site's
// script cannot read an answer, and a POST that says it came from another
// origin is refused before anything is written (a plain HTML form on another
// site would otherwise be able to sign someone up).

export const LIMITS = {
  body: 4096, // bytes: an email and a sentence, with room to spare
  email: 254, // RFC 5321's path limit
  use: 280, // one line, like the field says
  perWindow: 5, // signups tried from one address...
  windowSec: 600, // ...in ten minutes
  keepSec: 3600, // a rate row's life
};

// Deliberately plain: one @, a dot in the domain, no spaces. The real check
// is the mail that is written when hosted opens; this one only catches typos
// and junk. A stricter pattern refuses real addresses more often than it
// stops a bad one.
const EMAIL_RE = /^[^\s@<>()",;:\\]+@[^\s@<>()",;:\\]+\.[^\s@<>()",;:\\.]{2,}$/;

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
};

function answer(status, body, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...(extra || {}) },
  });
}

function refuse(status, error, message, extra) {
  return answer(status, { ok: false, error, message }, extra);
}

// A form posted without the page's script (no JS on the phone) is answered
// with a redirect back to the page, the outcome in the query, so the page
// says it in the same place the script would.
function back(req, outcome) {
  const u = new URL("/", req.url);
  u.searchParams.set("signup", outcome);
  u.hash = "join";
  return Response.redirect(u.toString(), 303);
}

// Control characters and the bidi overrides go: the line is shown later in a
// terminal and a dashboard, and neither should be steered by it.
function clean(s) {
  return String(s)
    .replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function validate(f) {
  const email = clean(f.email || "").toLowerCase();
  const use = clean(f.use || "");
  const consent = f.consent === true || f.consent === "on" || f.consent === "true" || f.consent === "1";
  if (!email) return { error: "email_missing", message: "Enter your email." };
  if (email.length > LIMITS.email || !EMAIL_RE.test(email))
    return { error: "email_invalid", message: "That email does not look right." };
  if (use.length > LIMITS.use)
    return { error: "use_too_long", message: `Keep it to ${LIMITS.use} characters.` };
  if (!consent) return { error: "consent_missing", message: "Tick the box so we may write to you." };
  return { email, use: use || null };
}

async function hashAddress(ip, salt) {
  const data = new TextEncoder().encode(`${salt}|${ip}`);
  const d = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The limit lives in D1 beside the list rather than in a Rate Limiting
// binding: the binding is per-colo and approximate, this is exact, costs one
// small table, and runs the same in the tests. Old rows go on every call, so
// the table never holds more than an hour of hashes.
async function overLimit(env, ip, now) {
  const key = await hashAddress(ip || "unknown", env.RATE_SALT || "lcars-landing");
  const since = now - LIMITS.windowSec;
  await env.DB.prepare("DELETE FROM rate WHERE at < ?").bind(now - LIMITS.keepSec).run();
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM rate WHERE k = ? AND at >= ?").bind(key, since).first();
  if (row && row.n >= LIMITS.perWindow) return true;
  await env.DB.prepare("INSERT INTO rate (k, at) VALUES (?, ?)").bind(key, now).run();
  return false;
}

async function readBody(req) {
  const len = Number(req.headers.get("content-length") || 0);
  if (len > LIMITS.body) return { tooBig: true };
  const raw = await req.text();
  if (raw.length > LIMITS.body) return { tooBig: true };
  const type = (req.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  if (type === "application/json") {
    try {
      const v = JSON.parse(raw);
      return v && typeof v === "object" && !Array.isArray(v) ? { fields: v, json: true } : { bad: true };
    } catch {
      return { bad: true };
    }
  }
  if (type === "application/x-www-form-urlencoded") {
    return { fields: Object.fromEntries(new URLSearchParams(raw)), json: false };
  }
  return { badType: true };
}

export async function signup(req, env, now = Math.floor(Date.now() / 1000)) {
  // Same origin only. A browser always sends Origin on a cross-site POST;
  // curl and the like send none, and are let through to the same checks.
  const origin = req.headers.get("origin");
  if (origin && origin !== new URL(req.url).origin) return refuse(403, "origin", "Not from this page.");

  const body = await readBody(req);
  if (body.tooBig) return refuse(413, "too_big", "That is more than a signup.");
  if (body.badType) return refuse(415, "type", "Send JSON or a form.");
  if (body.bad) return refuse(400, "bad_json", "That was not JSON.");
  const f = body.fields;
  const done = (status, outcome, payload) => (body.json ? answer(status, payload) : back(req, outcome));

  // The honeypot: a field hidden from people that a form-filling bot fills.
  // It is told it worked, so it learns nothing, and nothing is written.
  if (clean(f.website || "")) return done(200, "ok", { ok: true });

  const v = validate(f);
  if (v.error) return body.json ? refuse(400, v.error, v.message) : back(req, v.error);

  if (await overLimit(env, req.headers.get("cf-connecting-ip"), now))
    return body.json
      ? refuse(429, "rate", "Too many tries from here. Try again in a few minutes.", { "retry-after": String(LIMITS.windowSec) })
      : back(req, "rate");

  // An address already on the list is answered like a new one: the answer
  // must not tell anyone whether a given person signed up. The first line
  // given is kept (ON CONFLICT DO NOTHING), so a second visit cannot be used
  // to overwrite someone else's.
  const created = new Date(now * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  await env.DB.prepare(
    "INSERT INTO signups (email, use, consent, created) VALUES (?, ?, 1, ?) ON CONFLICT(email) DO NOTHING",
  )
    .bind(v.email, v.use, created)
    .run();
  return done(200, "ok", { ok: true });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/api/signup") {
      if (req.method !== "POST") return refuse(405, "method", "POST only.", { allow: "POST" });
      try {
        return await signup(req, env);
      } catch (e) {
        console.error("signup failed", e && e.message);
        return refuse(500, "server", "Something went wrong on our side. Try again.");
      }
    }
    if (url.pathname.startsWith("/api/")) return refuse(404, "not_found", "No such route.");
    // Anything else is a file; a name that is none gets the assets' 404 page.
    return env.ASSETS.fetch(req);
  },
};
