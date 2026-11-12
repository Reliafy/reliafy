import test from "node:test";
import assert from "node:assert/strict";
import { bestOf, designRow, unitClash } from "./rbdCompareDesigns.js";

const res = (r, mttf, basis = "given") => ({
  unit: "Hours", mttf, blife: { b10: mttf / 5, b50: mttf / 1.2 },
  importance: { time: 8760, time_basis: basis, reliability: r },
  structure: { min_cut_sets: [["a"], ["b", "c"]] },
});

test("a design's row takes R(t) from the analysis at the time asked about", () => {
  const row = designRow("C", res(0.4283, 8776), { id: "c" });
  assert.equal(row.reliability, 0.4283);
  assert.equal(row.mttf, 8776);
  assert.equal(row.singlePoints, 1);
  // Importance at the default time is not the user's t: no R(t) from it.
  assert.equal(designRow("A", res(0.9, 7135, "reliability_90")).reliability, null);
});

test("the best design is marked only when one leads", () => {
  const rows = [designRow("A", res(0.316, 7135), { id: "a" }), designRow("C", res(0.4283, 8776), { id: "c" })];
  assert.equal(bestOf(rows, "reliability"), "c");
  assert.equal(bestOf([rows[0], { ...rows[0], id: "b" }], "reliability"), null);
  assert.equal(bestOf([rows[0]], "reliability"), null);
});

test("designs in different time units are flagged", () => {
  assert.equal(unitClash([{ unit: "Hours" }, { unit: "hours" }]), false);
  assert.equal(unitClash([{ unit: "Hours" }, { unit: "Cycles" }]), true);
});
