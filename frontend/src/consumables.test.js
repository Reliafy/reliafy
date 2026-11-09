import test from "node:test";
import assert from "node:assert/strict";
import {
  byText, consumableState, lsaComparison, monthlyTotals, shortDay, stockText, totalSince, useText, yearTotal,
} from "./consumables.js";
import { checkValue, rowMenu, savedText, searchRows, sortRows, tableRows } from "./measurementsTable.js";

const TODAY = "2026-11-09";
const salt = (over = {}) => ({
  key: "pool:part:s1", position: { id: "pool", name: "Pool" }, name: "Pool salt", unit: "kg", listing_id: "l1",
  part: { id: "s1", part_number: "SALT-20", name: "Pool salt", unit: "kg", unit_cost: 0.6,
    stock: [{ location: { id: "shed", name: "Pool shed" }, on_hand: 40 }, { location: { id: "g", name: "Garage" }, on_hand: 0 }] },
  uses: [
    { id: "u3", on: "2026-11-01", qty: 20, cost: 12, note: "", work_order: null },
    { id: "u2", on: "2026-10-18", qty: 20, cost: 12, note: "after rain", work_order: { id: "w", number: 123 } },
    { id: "u1", on: "2026-09-01", qty: 90, cost: 54, note: "", work_order: null },
    { id: "u0", on: "2026-06-01", qty: 25, cost: null, note: "", work_order: null },
  ],
  lsa: [{ task: { id: "t", name: "Top up salt" }, qty: 20, unit: "kg", interval: 1, interval_unit: "months" }],
  ...over,
});

test("the row's state: what was added in the last 90 days, or nothing", () => {
  assert.equal(totalSince(salt().uses, "2026-09-01"), 130);
  assert.deepEqual(consumableState(salt(), TODAY), { label: "130 kg since 11 Aug", tone: "neutral", rank: 5, title: "130 kg added in the last 90 days" });
  assert.equal(consumableState(salt({ uses: [salt().uses[3]] }), TODAY).label, "None since 11 Aug");
  assert.equal(consumableState(salt({ uses: [] }), TODAY).label, "Never added");
  assert.equal(shortDay("2025-12-01", TODAY), "1 Dec 2025");
});

test("monthly bars, a use in words, who added it, the stock it comes from", () => {
  const m = monthlyTotals(salt().uses, TODAY, 6);
  assert.deepEqual(m.map((x) => [x.label, x.value]), [["Jun", 25], ["Jul", 0], ["Aug", 0], ["Sep", 90], ["Oct", 20], ["Nov", 20]]);
  assert.equal(monthlyTotals([], "2026-01-15", 3)[0].month, "2025-11");
  assert.equal(useText(salt().uses[1], "kg"), "20 kg · 18 Oct 2026");
  assert.equal(byText(salt().uses[1]), "WO 123");
  assert.equal(byText(salt().uses[0]), "by hand");
  assert.match(stockText(salt()), /40 kg at Pool shed/);
  assert.doesNotMatch(stockText(salt()), /Garage/);
  assert.match(stockText(salt({ part: null })), /no stock is taken/);
});

test("the LSA's dose beside what was added over the same span, and the year's total", () => {
  assert.deepEqual(lsaComparison(salt(), TODAY), ["The LSA says 20 kg every month (Top up salt); 40 kg were added in the last month."]);
  const weekly = salt({ unit: "L", lsa: [{ task: { id: "t", name: "Dose acid" }, qty: 0.3, unit: "L", interval: 2, interval_unit: "weeks" }] });
  assert.match(lsaComparison(weekly, TODAY)[0], /^The LSA says 0.3 L every 2 weeks \(Dose acid\); 20 L were added in the last 2 weeks\.$/);
  assert.equal(yearTotal(salt(), TODAY), "In the last 12 months: 155 kg in 4 additions, costing 78.00.");
  assert.equal(yearTotal(salt({ uses: [] }), TODAY), "Nothing added in the last 12 months.");
});

test("consumable rows in the table: kind, latest, state, bars, record and menu", () => {
  const [r] = tableRows([], [], TODAY, new Map(), [salt()]);
  assert.equal(r.type, "consumable");
  assert.equal(r.kind, "Consumable");
  assert.equal(r.value, 20);
  assert.equal(r.when, "2026-11-01");
  assert.equal(r.state.label, "130 kg since 11 Aug");
  assert.equal(r.bars, true);
  assert.equal(r.values.length, 6);
  assert.equal(r.due, null);
  assert.equal(r.tag, "SALT-20");
  assert.deepEqual(rowMenu(r).map((i) => i.label), ["Open", "Record use…", "Retire…"]);
  const [byHand] = tableRows([], [], TODAY, new Map(), [salt({ listing_id: null, part: null })]);
  assert.equal(rowMenu(byHand)[2].disabled, true);
  assert.deepEqual(checkValue("20", r.item), { value: 20 });
  assert.equal(checkValue("0", r.item).error, "The quantity must be more than 0");
  assert.equal(savedText(r.item, 20), "✓ Added 20 kg");
  assert.deepEqual(searchRows([r], "consumable salt").map((x) => x.key), [r.key]);
  // Consumables sit after the points that need attention.
  const point = { id: "p", name: "pH", kind: "condition", unit: "", source: "manual", status: "high", alarm_above: 7.8, reading: 8.2, read_at: TODAY, readings: [], position: { id: "pool", name: "Pool" } };
  assert.deepEqual(sortRows(tableRows([point], [], TODAY, new Map(), [salt()])).map((x) => x.type), ["point", "consumable"]);
});
