import { test } from "node:test";
import assert from "node:assert/strict";
import { whyCantCreate } from "./newModelWhy.js";
import { UNITLESS, UNIT_MISSING } from "./lifeData.js";

test("a disabled Create model says the first thing missing", () => {
  assert.equal(whyCantCreate({ name: "", missing: ["alpha"], unit: "" }), "Name the model first.");
  assert.equal(whyCantCreate({ name: "Pump", missing: ["alpha"], unit: "" }), "Enter alpha (a number).");
  assert.equal(whyCantCreate({ name: "Pump", missing: ["alpha", "beta"], unit: "" }), "Enter alpha and beta (numbers).");
  // The required-unit rule: the unit is the last thing missing, and its own message is shown.
  assert.equal(whyCantCreate({ name: "Pump", missing: [], unit: "" }), UNIT_MISSING);
  assert.equal(whyCantCreate({ name: "Pump", missing: [], unit: "hours" }), null);
  assert.equal(whyCantCreate({ name: "Pump", missing: [], unit: UNITLESS }), null);
});
