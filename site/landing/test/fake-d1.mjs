// A stand-in for D1 that knows exactly the statements src/worker.js runs,
// in memory, so the worker's tests and the local preview need nothing
// installed. It throws on any other SQL: a new statement in the worker must
// be added here (and to schema.sql), not silently answered.
export function fakeD1() {
  const signups = []; // {email, use, consent, created}
  let rate = []; // {k, at}
  const run = (sql, a) => {
    const s = sql.replace(/\s+/g, " ").trim();
    if (s === "DELETE FROM rate WHERE at < ?") { const n = rate.length; rate = rate.filter((r) => r.at >= a[0]); return { changes: n - rate.length }; }
    if (s === "SELECT COUNT(*) AS n FROM rate WHERE k = ? AND at >= ?") return { row: { n: rate.filter((r) => r.k === a[0] && r.at >= a[1]).length } };
    if (s === "INSERT INTO rate (k, at) VALUES (?, ?)") { rate.push({ k: a[0], at: a[1] }); return { changes: 1 }; }
    if (s === "INSERT INTO signups (email, use, consent, created) VALUES (?, ?, 1, ?) ON CONFLICT(email) DO NOTHING") {
      if (signups.some((r) => r.email.toLowerCase() === a[0].toLowerCase())) return { changes: 0 };
      signups.push({ email: a[0], use: a[1], consent: 1, created: a[2] });
      return { changes: 1 };
    }
    throw new Error("fake D1: unknown statement: " + s);
  };
  const stmt = (sql, a = []) => ({
    bind: (...b) => stmt(sql, b),
    run: async () => ({ success: true, meta: { changes: run(sql, a).changes || 0 } }),
    first: async () => run(sql, a).row ?? null,
  });
  return { prepare: (sql) => stmt(sql), signups, get rate() { return rate; } };
}
