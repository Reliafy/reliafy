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
