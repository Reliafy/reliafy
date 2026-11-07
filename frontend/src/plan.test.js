// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { showProTags } from "./plan.js";

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
