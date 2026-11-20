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

test("an item class's forecast: its positions by position class, counted at those positions alone", async () => {
  const { classForecastGroups, scopedForecast } = await import("./maintenanceForecast.js");
  const pos = (id, cls, extra = {}) => [id, { key: id, type: "pos", kids: [], ref: { name: id.toUpperCase(), class_key: cls, position_class: cls, ...extra } }];
  const display = { rows: new Map([
    ["cls:pump", { key: "cls:pump", type: "cls", kids: ["cls:sub", "p1", "p2"] }],
    ["cls:sub", { key: "cls:sub", type: "cls", kids: ["p3", "p4"] }],
    pos("p1", "Pool pump"), pos("p2", "Pool pump"), pos("p3", "Transfer pump"), pos("p4", ""),
  ]) };
  const { groups, none, count } = classForecastGroups(display, display.rows.get("cls:pump"));
  assert.deepEqual(groups.map((g) => [g.key, g.positions.map((p) => p.id)]), [["Pool pump", ["p1", "p2"]], ["Transfer pump", ["p3"]]]);
  assert.deepEqual(none.map((p) => p.id), ["p4"]);
  assert.equal(count, 4);
  // Pool pump's read ranks another asset's position too (px): left out; p2 isn't forecast.
  const reads = {
    "Pool pump": { n_forecast: 3, period: "month", periods: 12, model: { unit: "days" },
      at_risk: [{ position: { id: "px", name: "Elsewhere" }, expected_failures: 5 }, { position: { id: "p1", name: "P1" }, expected_failures: 0.4 }],
      not_forecast: [{ position: { id: "p2" }, reason: "nothing fitted" }] },
    "Transfer pump": { n_forecast: 0, headline: "No fitted life model yet." },
  };
  const out = scopedForecast(groups, reads);
  assert.equal(out.expected, 0.4);
  assert.deepEqual(out.rows.map((r) => r.position.id), ["p1"]);
  assert.deepEqual(out.missing.map((m) => [m.position.id, m.reason]), [["p2", "nothing fitted"], ["p3", "No fitted life model yet."]]);
  assert.equal(out.pending, 0);
  assert.equal(out.period, "month");
  // A read still coming: counted as pending, nothing guessed.
  assert.equal(scopedForecast(groups, { "Pool pump": reads["Pool pump"] }).pending, 1);
  assert.equal(scopedForecast(groups, { "Pool pump": { error: true } }).missing[0].reason, "its position class's forecast didn't load");
  assert.equal(scopedForecast(groups, { "Pool pump": { error: "Fit a model first." } }).missing[0].reason, "Fit a model first.");
});
