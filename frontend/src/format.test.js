import test from "node:test";
import assert from "node:assert/strict";
import { formatNumber, formatPercent, formatWithUnit } from "./format.js";

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
