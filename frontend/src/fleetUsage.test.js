import test from "node:test";
import assert from "node:assert/strict";
import { itemsOnFleetRate, itemsWithoutUsage, usageInputValue } from "./fleetUsage.js";

const items = [
  { name: "Pump 1", current_use: 300, rate: null },
  { name: "Pump 2", current_use: 700 },
];

test("a new forecast (usage 0) with items is missing usage", () => {
  const settings = { default_rate: 0, periods: 12, period_label: "months" };
  assert.equal(itemsWithoutUsage(settings, items), 2);
  assert.equal(itemsWithoutUsage({ ...settings, default_rate: "" }, items), 2);
  assert.equal(itemsWithoutUsage({ ...settings, default_rate: "0" }, items), 2);
  assert.equal(itemsWithoutUsage({}, items), 2);
});

test("a usage per period, or every item's own rate, is enough", () => {
  assert.equal(itemsWithoutUsage({ default_rate: 100 }, items), 0);
  assert.equal(itemsWithoutUsage({ default_rate: "0.5" }, items), 0);
  const own = items.map((it, i) => ({ ...it, rate: i === 0 ? "40" : 0 }));
  assert.equal(itemsWithoutUsage({ default_rate: 0 }, own), 0);
});

test("no items: nothing is missing", () => {
  assert.equal(itemsWithoutUsage({ default_rate: 0 }, []), 0);
});

test("estimated rates count only when rates come from API readings", () => {
  const est = [{ name: "A", rate: null, estimated_rate: 12, estimated_rate_n: 2 }, { name: "B", rate: null }];
  assert.equal(itemsOnFleetRate({ rate_source: "estimated" }, est).length, 1);
  assert.equal(itemsWithoutUsage({ default_rate: 0, rate_source: "estimated" }, est), 1);
  assert.equal(itemsWithoutUsage({ default_rate: 0, rate_source: "manual" }, est), 2);
});

test("the usage box shows a stored 0 as blank but keeps a typed 0", () => {
  assert.equal(usageInputValue(0), "");
  assert.equal(usageInputValue(null), "");
  assert.equal(usageInputValue(undefined), "");
  assert.equal(usageInputValue("0"), "0");
  assert.equal(usageInputValue(500), 500);
});
