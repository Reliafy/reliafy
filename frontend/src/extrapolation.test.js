import { test } from "node:test";
import assert from "node:assert/strict";
import { stressExtrapolation, timeExtrapolation } from "./extrapolation.js";

const RANGE = { first_failure: 1500, last_seen: 6 * 1000 };

test("timeExtrapolation: before the first failure, past the oldest age, or nothing inside", () => {
  // A B2 life of 1,050 hours (833 at its bound) under a first failure found at 1,500 hours.
  assert.match(timeExtrapolation(RANGE, 833, 1050, "hours"),
    /^833 hours is before the first failure in the data \(1,500 hours\)\. The answer comes from the fitted curve's shape alone/);
  assert.match(timeExtrapolation({ first_failure: 1, last_seen: 6 }, 12, 12, "months"),
    /^12 months is past the oldest age in the data \(6 months\)/);
  assert.equal(timeExtrapolation(RANGE, 2000, 5000, "hours"), null);
  assert.equal(timeExtrapolation(null, 1, 1), null);
  assert.equal(timeExtrapolation(RANGE, null, null), null);
});

test("stressExtrapolation: the phrases, the factor, and nothing without a phrase", () => {
  assert.match(stressExtrapolation(["20 kV is well below the tested 30–36 kV"], 612.3),
    /^20 kV is well below the tested 30–36 kV \(an acceleration factor of 612\.3×\)\. The life here rests on/);
  assert.equal(stressExtrapolation([]), null);
});
