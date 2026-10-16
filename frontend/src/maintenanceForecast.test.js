import { test } from "node:test";
import assert from "node:assert/strict";
import { horizonText, money, moneyRange, periodLabels, rangeText, spareCover } from "./maintenanceForecast.js";

test("periods are labelled by their start, with the year when it changes", () => {
  const rows = [{ start: "2026-11-16" }, { start: "2026-12-16" }, { start: "2027-01-15" }];
  assert.deepEqual(periodLabels(rows, "month"), ["16 Nov 2026", "16 Dec", "15 Jan 2027"]);
  assert.deepEqual(periodLabels([{ start: "2026-10-16" }], "year"), ["Oct 2026"]);
  assert.deepEqual(periodLabels(), []);
});

test("horizons and ranges read plainly", () => {
  assert.equal(horizonText(12, "month"), "12 months");
  assert.equal(horizonText(1, "quarter"), "1 quarter");
  assert.equal(rangeText([1, 6]), "1–6");
  assert.equal(rangeText([2, 2]), "2");
  assert.equal(rangeText(null), "");
});

test("a spare's cover says how long the stock lasts at the likely high end", () => {
  const cum = (n) => Array.from({ length: n }, () => ({ prob_covered: 0.42 }));
  assert.equal(spareCover({ covered_periods: 12, cumulative: cum(12) }, "month"), "covers all 12 months");
  assert.equal(spareCover({ covered_periods: 3, cumulative: cum(12) }, "month"), "covers 3 months at the likely high end");
  assert.equal(spareCover({ covered_periods: 0, cumulative: cum(4) }, "quarter"),
    "may run out in the first quarter (42% chance it covers it)");
});

test("money has no decimals and an optional currency", () => {
  assert.equal(money(1290.4), "1,290");
  assert.equal(money(500, "AUD"), "AUD 500");
  assert.equal(money(null), "—");
  assert.equal(moneyRange([12000, 20000]), "12,000–20,000");
  assert.equal(moneyRange([12000, 12000], "AUD"), "AUD 12,000");
});
