import test from "node:test";
import assert from "node:assert/strict";
import { constantRateText, countRange, levelOptions, meanRange, runoutText } from "./recurrentStock.js";

test("count and expected-number ranges read differently", () => {
  assert.equal(countRange([4, 15]), "4–15");
  assert.equal(meanRange([5.967, 11.864]), "5.97–11.9");
  assert.equal(countRange(null), null);
  assert.equal(meanRange([1, NaN]), null);
});

test("runoutText gives the chance at the stock and at one fewer", () => {
  assert.equal(runoutText({ hold: 13, runout: 0.094, runout_one_less: 0.1407 }),
    "9.4% chance of running out (12 would be 14%)");
  assert.equal(runoutText({ hold: 0, runout: 0.05, runout_one_less: null }), "5% chance of running out");
  assert.equal(runoutText(null), null);
});

test("constantRateText says what the average-rate figure rests on", () => {
  assert.equal(constantRateText({ expected: 16, failures: 48, exposure: 216000 }, "hours"),
    "16 (48 failures in 216,000 hours)");
  assert.equal(constantRateText(null), null);
});

test("levelOptions", () => {
  assert.deepEqual(levelOptions([0.9, 0.995]), [{ value: "0.9", label: "90%" }, { value: "0.995", label: "99.5%" }]);
});
