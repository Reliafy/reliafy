import { test } from "node:test";
import assert from "node:assert/strict";
import { repairSpecFromMean, typedRepairs } from "./rbdRepairAvailability.js";

test("typed repair times keep only numbers above 0", () => {
  assert.deepEqual(typedRepairs({ a: "12", b: "", c: "-1", d: "x", e: "0.5" }), { a: 12, e: 0.5 });
  assert.deepEqual(typedRepairs(null), {});
});

test("a typed mean in hours becomes an exponential in the diagram's unit", () => {
  // 12 hours on a diagram in days: a mean of 0.5 days, a rate of 2 a day.
  const days = repairSpecFromMean(12, "Days");
  assert.equal(days.distribution_id, "exponential");
  assert.ok(Math.abs(days.params[0].value - 2) < 1e-12);
  // Already in hours: the rate is 1 / mean.
  assert.ok(Math.abs(repairSpecFromMean(4, "Hours").params[0].value - 0.25) < 1e-12);
  // A clock that isn't a time (cycles): the mean is in its own unit.
  assert.ok(Math.abs(repairSpecFromMean(5, "Cycles", "Cycles").params[0].value - 0.2) < 1e-12);
});
