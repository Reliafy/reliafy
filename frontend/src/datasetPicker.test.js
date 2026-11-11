// The saved-data picker: every dataset listed (yours, then samples), suited first, the rest with a reason.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickerGroups, rowsWords, shortDate, shownName, unsuitableReason } from "./datasetPicker.js";

const ds = (id, tags, extra = {}) => ({ id, name: id, tags, n_rows: 10, created_at: "2026-11-11T02:00:00Z", ...extra });

test("every saved dataset is listed: yours first, however many samples are newer", () => {
  // The list comes newest first; samples seeded after the user's uploads came first in it,
  // and the old picker showed only the first five, so the user's own were out of reach.
  const samples = Array.from({ length: 8 }, (_, i) => ds(`sample-${i}`, ["Non-repairable"], { is_sample: true }));
  const mine = Array.from({ length: 6 }, (_, i) => ds(`mine-${i}`, ["Non-repairable"]));
  const out = pickerGroups("life", [...samples, ...mine]);
  assert.deepEqual(out.groups.map((g) => g.key), ["yours", "samples"]);
  assert.equal(out.groups[0].rows.length, 6);
  assert.equal(out.groups[1].rows.length, 8);
  assert.equal(out.shown, 14);
  assert.equal(out.usable, 14);
});

test("datasets a non-repairable fit can't use come last, greyed with a reason", () => {
  const list = [ds("rep", ["Repairable"]), ds("reads", ["Measurements"]), ds("life", ["Non-repairable"]), ds("none", [])];
  const rows = pickerGroups("life", list).groups[0].rows;
  assert.deepEqual(rows.map((r) => r.dataset.id), ["life", "rep", "reads", "none"]);
  assert.equal(rows[0].reason, null);
  assert.match(rows[1].reason, /repairable model/);
  assert.match(rows[2].reason, /degradation model/);
  assert.match(rows[3].reason, /No column of times/);
  assert.equal(pickerGroups("life", list).usable, 1);
});

test("life data with measurements, or with covariates, suits a non-repairable fit", () => {
  assert.equal(unsuitableReason("life", ds("a", ["Non-repairable", "Measurements"])), null);
  assert.equal(unsuitableReason("life", ds("b", ["Non-repairable", "Time-varying covariates"])), null);
  // An older server sends no tags: kept as usable.
  assert.equal(unsuitableReason("life", { id: "c" }), null);
});

test("the search narrows by name, tag or summary, every word", () => {
  const list = [ds("Pump returns", ["Non-repairable"], { summary: "25 pumps · 18 failed" }),
    ds("Fan motors", ["Non-repairable", "Covariates"]), ds("Compressor events", ["Repairable"], { is_sample: true })];
  assert.deepEqual(pickerGroups("life", list, "pump").groups[0].rows.map((r) => r.dataset.id), ["Pump returns"]);
  assert.deepEqual(pickerGroups("life", list, "covariates").groups[0].rows.map((r) => r.dataset.id), ["Fan motors"]);
  assert.deepEqual(pickerGroups("life", list, "18 failed").groups[0].rows.map((r) => r.dataset.id), ["Pump returns"]);
  const none = pickerGroups("life", list, "zzz");
  assert.equal(none.groups.length, 0);
  assert.equal(none.shown, 0);
  assert.equal(none.total, 3);
});

test("names, dates and counts read plainly", () => {
  assert.equal(shownName({ name: "Bearing fatigue test (sample)" }), "Bearing fatigue test");
  assert.equal(shortDate("2026-11-11T02:43:23.721000+00:00"), "11 Nov 2026");
  assert.equal(shortDate("not a date"), "");
  assert.equal(rowsWords(1), "1 row");
  assert.equal(rowsWords(1234), "1,234 rows");
});
