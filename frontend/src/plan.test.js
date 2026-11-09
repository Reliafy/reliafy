// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  CAPPED_KINDS, FREE_CAPS, capPhrase, errorText, freeStorageLines, isCapRefusal, showProTags,
} from "./plan.js";

test("Free users see Pro tags", () => {
  assert.equal(showProTags({ billing_enabled: true, plan: "free", admin: false }), true);
  // The retired Agent plan isn't Pro: simulations still need Pro.
  assert.equal(showProTags({ billing_enabled: true, plan: "agent", admin: false }), true);
});

test("Pro users, operators and self-hosted (billing off) see none", () => {
  assert.equal(showProTags({ billing_enabled: true, plan: "pro", admin: false }), false);
  assert.equal(showProTags({ billing_enabled: true, plan: "free", admin: true }), false);
  assert.equal(showProTags({ billing_enabled: false, plan: "free", admin: false }), false);
});

test("no tags until the plan is known", () => {
  assert.equal(showProTags(null), false);
  assert.equal(showProTags(undefined), false);
});

test("storage cap reached: only at or past the plan's cap", async () => {
  const { storageCapReached } = await import("./plan.js");
  const free = (used) => ({ billing_enabled: true, plan: "free", admin: false,
    plan_caps: { reliability_predictions: 1 }, usage: { reliability_predictions: used } });
  assert.equal(storageCapReached(free(0), "reliability_predictions"), null);
  assert.deepEqual(storageCapReached(free(1), "reliability_predictions"), { used: 1, cap: 1 });
  assert.deepEqual(storageCapReached(free(2), "reliability_predictions"), { used: 2, cap: 1 });
  // Pro (no caps), operators, billing off and an unknown plan: never.
  assert.equal(storageCapReached({ ...free(5), plan: "pro", plan_caps: null }, "reliability_predictions"), null);
  assert.equal(storageCapReached({ ...free(5), admin: true }, "reliability_predictions"), null);
  assert.equal(storageCapReached({ ...free(5), billing_enabled: false }, "reliability_predictions"), null);
  assert.equal(storageCapReached(null, "reliability_predictions"), null);
  assert.equal(storageCapReached(free(5), "maintainability_predictions"), null);
});

// The public pricing copy reads FREE_CAPS, so it must match the server's
// defaults (backend/config.py FREE_MAX_*) and cover every capped kind
// (backend/services/billing.py CAPPED_KINDS), in the same order.
test("FREE_CAPS matches backend/config.py and billing.py", () => {
  const config = readFileSync(new URL("../../backend/config.py", import.meta.url), "utf8");
  const billing = readFileSync(new URL("../../backend/services/billing.py", import.meta.url), "utf8");
  const fromConfig = {};
  for (const m of config.matchAll(/^FREE_MAX_([A-Z_]+) = _int\("FREE_MAX_\1", (\d+)\)/gm)) {
    fromConfig[m[1].toLowerCase()] = Number(m[2]);
  }
  assert.deepEqual({ ...FREE_CAPS }, fromConfig);
  const kinds = billing.match(/CAPPED_KINDS = \(([^)]*)\)/)[1].match(/"([a-z_]+)"/g).map((k) => k.slice(1, -1));
  assert.deepEqual(Object.keys(FREE_CAPS), kinds);
  assert.deepEqual(CAPPED_KINDS.map(([k]) => k), kinds);
});

test("capPhrase counts with the right noun", () => {
  assert.equal(capPhrase("rbds"), "1 RBD");
  assert.equal(capPhrase("datasets"), "3 datasets");
  assert.equal(capPhrase("rbds", { rbds: 2 }), "2 RBDs");
  assert.equal(capPhrase("nope"), null);
  assert.equal(capPhrase("rbds", null), null);
});

test("freeStorageLines names every capped kind once, in plain words", () => {
  const lines = freeStorageLines();
  assert.deepEqual(lines, [
    "Save 3 datasets and 3 models",
    "1 RBD, 1 fault tree and 1 outage log",
    "1 reliability prediction, 1 maintainability prediction and 1 data library",
    "Degradation tracking: 1 degradation model and 3 tracked items",
    "1 fleet failure forecast",
  ]);
  // Follows a changed limit (the live caps from GET /api/billing).
  assert.match(freeStorageLines({ ...FREE_CAPS, rbds: 2 })[1], /^2 RBDs,/);
});

test("isCapRefusal and errorText", () => {
  const cap = Object.assign(new Error("You've reached the free-plan limit of 1 saved RBD."), { code: "cap", status: 402 });
  assert.equal(isCapRefusal(cap), true);
  assert.equal(isCapRefusal(Object.assign(new Error("x"), { code: "pro_required" })), false);
  assert.equal(isCapRefusal("You've reached the limit"), false);
  assert.equal(isCapRefusal(null), false);
  assert.equal(errorText(cap), cap.message);
  assert.equal(errorText("plain"), "plain");
  assert.equal(errorText(null), "");
});
