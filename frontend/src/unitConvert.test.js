import { test } from "node:test";
import assert from "node:assert/strict";
import { blockConversion, unitFactor } from "./unitConvert.js";

test("same-kind units convert with the app's calendar convention", () => {
  assert.equal(unitFactor("Days", "Hours"), 24);
  assert.equal(unitFactor("Months", "Hours"), (365.25 / 12) * 24);
  assert.equal(unitFactor("Years", "Days"), 365.25);
  assert.ok(Math.abs(unitFactor("Miles", "km") - 1.609344) < 1e-12);
});

test("other kinds, blank, unknown and equal units don't convert", () => {
  for (const [a, b] of [["Cycles", "Hours"], ["km", "Hours"], ["", "Hours"], ["Days", ""], ["hrs", "Hours"],
    ["flight hours", "Hours"]]) {
    assert.equal(unitFactor(a, b), null, `${a} → ${b}`);
  }
});

test("a block says what was converted", () => {
  const c = blockConversion({ unit: "Days", distribution_id: "weibull" }, "Hours");
  assert.equal(c.text, "Fitted in days, shown in hours");
  assert.equal(blockConversion({ unit: "Days", kind: "joint" }, "Hours"), null);
  assert.equal(blockConversion({ unit: "Cycles" }, "Hours"), null);
  assert.equal(blockConversion(null, "Hours"), null);
});
