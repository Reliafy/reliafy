import test from "node:test";
import assert from "node:assert/strict";
import { dateText, daysText, measurementsOf, percent, usefulHorizons } from "./timeToLimit.js";

test("days read as days, months or years", () => {
  assert.equal(daysText(0.01), "under an hour");
  assert.equal(daysText(0.5), "12 hours");
  assert.equal(daysText(18.2), "18 days");
  assert.equal(daysText(120), "4 months");
  assert.equal(daysText(900), "2.5 years");
  assert.equal(daysText(null), "?");
});

test("percent and dates tolerate gaps", () => {
  assert.equal(percent(0.126), "13%");
  assert.equal(percent(null), "–");
  assert.equal(dateText(""), "");
  assert.equal(dateText("not a date"), "");
});

test("the chance table drops leading zeros and stops at certainty", () => {
  const rows = [
    { days: 7, chance: 0, high: 0 }, { days: 30, chance: 0.2, low: 0.01, high: 0.5 },
    { days: 90, chance: 0.999, low: 0.99, high: 1 }, { days: 180, chance: 1, low: 1, high: 1 },
  ];
  assert.deepEqual(usefulHorizons(rows).map((r) => r.days), [30, 90]);
  assert.deepEqual(usefulHorizons([]), []);
});

test("measurements keep the age in days", () => {
  assert.deepEqual(measurementsOf([{ age_days: 0, value: 1 }, { age_days: 2.5, value: 3 }]), [{ t: 0, y: 1 }, { t: 2.5, y: 3 }]);
});
