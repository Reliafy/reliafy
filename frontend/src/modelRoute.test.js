import { test } from "node:test";
import assert from "node:assert/strict";
import { firstFound, modelPage, otherModelPage, otherPages, MODEL_PAGES } from "./modelRoute.js";

test("a condition and life model fetched as a non-repairable model goes to its own page", () => {
  assert.deepEqual(otherModelPage({ id: "m1", kind: "joint" }), { label: "condition and life", to: "/models/joint/m1" });
});

test("life fits stay on the non-repairable page", () => {
  for (const kind of ["distribution", "regression", "competing_risks", "flexible", undefined]) {
    assert.equal(otherModelPage({ id: "m1", kind }), null);
  }
  assert.equal(otherModelPage(null), null);
});

test("an id another model list knows is sent there", () => {
  const pages = otherPages("life");
  assert.equal(pages.length, MODEL_PAGES.length - 1);
  assert.ok(!pages.some((p) => p.key === "life"));
  const settled = pages.map(() => ({ status: "rejected" }));
  settled[pages.findIndex((p) => p.key === "degradation")] = { status: "fulfilled", value: { id: "d1" } };
  assert.deepEqual(firstFound("d1", pages, settled), { label: "degradation", to: "/models/degradation/d1" });
  assert.equal(firstFound("x", pages, pages.map(() => ({ status: "rejected" }))), null);
});

test("every model page has its list", () => {
  for (const p of MODEL_PAGES) assert.ok(p.list.startsWith("/models/") && p.listLabel);
  assert.equal(modelPage("alt").base, "/models/alt/");
  assert.equal(modelPage("nope"), null);
});
