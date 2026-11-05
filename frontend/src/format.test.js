import test from "node:test";
import assert from "node:assert/strict";
import { formatNumber, formatPercent, formatWithUnit, singularUnit } from "./format.js";

test("formatNumber: three significant figures with separators", () => {
  assert.equal(formatNumber(4573.2), "4,570");
  assert.equal(formatNumber(580.28), "580");
  assert.equal(formatNumber(1273.2), "1,270");
  assert.equal(formatNumber(0.58371), "0.584");
  assert.equal(formatNumber(12), "12");
  assert.equal(formatNumber(1234567), "1,230,000");
  assert.equal(formatNumber(-42.678), "-42.7");
  assert.equal(formatNumber(0), "0");
});

test("formatNumber: sig sets the significant figures", () => {
  assert.equal(formatNumber(4573.2, { sig: 4 }), "4,573");
  assert.equal(formatNumber(3.14159, { sig: 4 }), "3.142");
  assert.equal(formatNumber(0.0012345, { sig: 2 }), "0.0012");
});

test("formatNumber: scientific only outside 0.001 to 10 million", () => {
  assert.equal(formatNumber(0.001), "0.001");
  assert.equal(formatNumber(0.000123), "1.23e-4");
  assert.equal(formatNumber(9876543), "9,880,000");
  assert.equal(formatNumber(2.5e8), "2.5e8");
});

test("formatNumber: missing values", () => {
  assert.equal(formatNumber(null), "—");
  assert.equal(formatNumber(undefined), "—");
  assert.equal(formatNumber(NaN), "—");
  assert.equal(formatNumber(Infinity), "—");
});

test("formatPercent", () => {
  assert.equal(formatPercent(0.5714), "57%");
  assert.equal(formatPercent(0.0532), "5.3%");
  assert.equal(formatPercent(0.00123), "0.12%");
  assert.equal(formatPercent(0), "0%");
  assert.equal(formatPercent(null), "—");
});

test("formatWithUnit", () => {
  assert.equal(formatWithUnit(4573.2, "hours"), "4,570 hours");
  assert.equal(formatWithUnit(12, ""), "12");
  assert.equal(formatWithUnit(null, "hours"), "—");
});

test("formatWithUnit: one of a unit reads singular", () => {
  assert.equal(formatWithUnit(1, "hours"), "1 hour");
  assert.equal(formatWithUnit(1, "cycles"), "1 cycle");
  assert.equal(formatWithUnit(1, "flight hours"), "1 flight hour");
  assert.equal(formatWithUnit(1, "Kilometres"), "1 Kilometre");
  assert.equal(formatWithUnit(0.9996, "hours"), "1 hour"); // shown as 1, read as 1
  assert.equal(formatWithUnit(1.5, "hours"), "1.5 hours");
  assert.equal(formatWithUnit(0, "hours"), "0 hours");
  assert.equal(formatWithUnit(2, "hours"), "2 hours");
  assert.equal(formatWithUnit(1.04, "hours"), "1.04 hours");
  assert.equal(formatWithUnit(1, "hour"), "1 hour");
});

test("singularUnit leaves anything that isn't a plain plural alone", () => {
  for (const u of ["kWh", "km", "ms", "hrs", "MPa", "Celsius", "batteries", "boxes", "starts/day", "%", ""]) {
    assert.equal(singularUnit(u), u, u);
  }
  assert.equal(singularUnit("Flights"), "Flight");
  assert.equal(singularUnit("miles"), "mile");
});
