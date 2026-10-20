// Exercises the LCARS client against a real server. This is the half of the
// app that does not need the glasses, and it is the half that talks to the
// journal, so it is the half worth testing.
//
//   lcars --http-only --port 8099 --user test --password test   # in a scratch dir
//   npm test
//
// Point it elsewhere with LCARS_TEST_URL / LCARS_TEST_USER / LCARS_TEST_PASS.
// It creates, mutates and soft-deletes entries under kind `hyper_test`, which
// is the kind the repo already uses for throwaway data - never run it against
// the real journal.
import { LcarsClient, LcarsError } from "../src/lcars.ts";

const fails: string[] = [];
function ok(name: string, cond: boolean, detail: unknown = "") {
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (cond ? "" : "   <- " + String(detail)));
  if (!cond) fails.push(name);
}

const BASE = process.env.LCARS_TEST_URL ?? "http://127.0.0.1:8099";
const USER = process.env.LCARS_TEST_USER ?? "test";
const PASS = process.env.LCARS_TEST_PASS ?? "test";

const client = new LcarsClient({ baseUrl: BASE, user: USER, pass: PASS });

console.log("== health / auth ==");
ok("health reachable", await client.health());

const kinds = await client.kinds();
ok("kinds returns rows", kinds.length > 0, kinds.length);
ok("kinds have counts", typeof kinds[0]?.count === "number", kinds[0]);

console.log("\n== C: create ==");
const createdId = await client.create("hyper_test", "G2 CRUD probe", "line one\nline two");
ok("create returns an id", createdId > 0, createdId);
const created = await client.get(createdId);
ok("kind round-tripped", created.kind === "hyper_test", created.kind);

console.log("\n== R: list and get ==");
const list = await client.list("hyper_test", 10);
ok("list finds it", list.some((e) => e.id === created.id), list.length);
ok("list omits bodies (content=0)", list.every((e) => e.content === undefined || e.content === ""), "content present");
ok("list still reports content_length", typeof list[0]?.content_length === "number", list[0]);

const fetched = await client.get(created.id);
ok("get returns the body", fetched.content === "line one\nline two", JSON.stringify(fetched.content));

console.log("\n== U: update ==");
const ack = await client.setDone(created.id, true);
ok("setDone acknowledges the id", ack.id === created.id, ack);
const done = await client.get(created.id);
ok("done_bool set", done.done_bool === 1, done.done_bool);
ok("title NOT blanked by a partial update", done.title === "G2 CRUD probe", done.title);
await client.setDone(created.id, false);
ok("done_bool cleared", (await client.get(created.id)).done_bool === 0);

await client.update(created.id, { title: "renamed" });
const retitled = await client.get(created.id);
ok("title updated", retitled.title === "renamed", retitled.title);
ok("content survived the title-only PATCH", retitled.content === "line one\nline two", retitled.content);

console.log("\n== D: soft delete and restore ==");
await client.remove(created.id);
const afterDelete = await client.list("hyper_test", 50);
ok("gone from the default list", !afterDelete.some((e) => e.id === created.id));
const stillThere = await client.get(created.id);
ok("row survives (soft delete)", stillThere.deleted === 1, stillThere.deleted);
await client.restore(created.id);
ok("restore brings it back", (await client.get(created.id)).deleted === 0);
await client.remove(created.id); // leave the scratch db tidy

console.log("\n== error mapping ==");
try {
  await client.get(999999999);
  ok("missing entry raises", false, "no throw");
} catch (e) {
  ok("missing entry raises LcarsError", e instanceof LcarsError, e);
  ok("  with a 4xx status", (e as LcarsError).status >= 400, (e as LcarsError).status);
}

const badAuth = new LcarsClient({ baseUrl: BASE, user: USER, pass: "definitely-wrong" });
try {
  await badAuth.kinds();
  ok("bad password rejected", false, "no throw");
} catch (e) {
  ok("bad password maps to auth error", e instanceof LcarsError && (e as LcarsError).status === 401, e);
}

// Port 9 (discard) refuses immediately - the transport-failure path, which
// the app maps to "check the whitelist / the tailnet" rather than to a status.
const unreachable = new LcarsClient({ baseUrl: "http://127.0.0.1:9", user: "x", pass: "y" });
try {
  await unreachable.kinds();
  ok("unreachable host raises", false, "no throw");
} catch (e) {
  ok("unreachable maps to status 0", e instanceof LcarsError && (e as LcarsError).status === 0, e);
}

console.log("\n" + (fails.length === 0 ? "ALL PASS" : "FAILURES: " + fails.join(", ")));
process.exit(fails.length === 0 ? 0 : 1);
