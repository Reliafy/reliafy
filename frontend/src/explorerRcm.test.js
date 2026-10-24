import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, flatten, levelSet, markersOf } from "./assetTree.js";
import { cellRow, graftRcm, isRcmRow, openFor, positionOf } from "./explorerRcm.js";
import { failuresOn } from "./rcmWorksheet.js";

const DATA = {
  positions: [
    { id: "plant", name: "Plant", parent_id: null, not_analysed: true },
    { id: "pump", name: "Pump", parent_id: "plant", not_analysed: true },
    { id: "motor", name: "Motor", parent_id: "pump", not_analysed: true },
  ],
  locations: [], spares: [], unhomed: [],
};
const mode = (id, text, decision = null) => ({ id, text, consequence: "operational", decision });
const RCM = {
  positions: [{
    id: "pump",
    functions: [
      { id: "f1", text: "Pump water", failures: [
        { id: "x1", text: "No flow", modes: [mode("m1", "Bearing seizes"), mode("m2", "Seal leaks", { outcome: "rtf", status: "contradicted" })] },
        { id: "x2", text: "Low flow", modes: [mode("m3", "Impeller worn")] },
      ] },
      { id: "f2", text: "Contain the water", failures: [] },
    ],
    unassigned: [mode("m4", "Coupling fails", { outcome: "redesign" })],
  }],
};

test("the RCM nested in the tree: functions, then failures, then modes, before the positions inside", () => {
  const base = buildDisplay(DATA, "positions");
  const d = graftRcm(base, RCM);
  assert.notEqual(d.rows, base.rows); // the tree it came from is left as it was
  assert.deepEqual(base.rows.get("pump").kids, ["motor"]);
  assert.deepEqual(d.rows.get("pump").kids, ["f1", "f2", "U:pump", "motor"]);
  assert.equal(d.rows.get("pump").rcmKids, 3);
  assert.deepEqual(d.rows.get("f1").kids, ["x1", "x2"]);
  assert.deepEqual(d.rows.get("x1").kids, ["m1", "m2"]);
  assert.equal(d.rows.get("m1").depth, 4);
  assert.equal(d.rows.get("motor").depth, 2); // the positions keep their place
  // Counts: a position's own modes, each row's inside it.
  assert.equal(d.rows.get("pump").rsum.modes, 4);
  assert.equal(d.rows.get("pump").rsum.undecided, 2);
  assert.equal(d.rows.get("f1").rsum.contradicted, 1);
  assert.equal(positionOf(d.rows.get("m3")), "pump");
  assert.equal(positionOf(d.rows.get("pump")), "pump");
  assert.ok(isRcmRow(d.rows.get("U:pump")) && !isRcmRow(d.rows.get("pump")));
  assert.deepEqual(failuresOn(d, "pump").map((f) => f.id), ["x1", "x2"]);
  // The tree's markers don't count the RCM rows as positions inside.
  assert.equal(markersOf(d.rows.get("f1")).length, 0);
  assert.equal(markersOf(d.rows.get("pump"), { rcm: true })[0].label, "2 positions not analysed yet here and inside");
});

test("the Add rows: only for the position being worked on, and not counted as inside", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM, { addFor: "pump" });
  assert.deepEqual(d.rows.get("pump").kids, ["f1", "f2", "U:pump", "+fn:pump", "motor"]);
  assert.deepEqual(d.rows.get("f2").kids, ["+fail:f2"]);
  assert.deepEqual(d.rows.get("x2").kids, ["m3", "+mode:x2"]);
  assert.deepEqual(d.rows.get("+mode:x2").ref, { add: "mode", text: "Add a failure mode", position_id: "pump", functional_failure_id: "x2" });
  assert.deepEqual(cellRow(d.rows.get("x2")).kids, ["m3"]);
  // A position with no RCM yet gets its Add a function row.
  const m = graftRcm(buildDisplay(DATA, "positions"), RCM, { addFor: "motor" });
  assert.deepEqual(m.rows.get("motor").kids, ["+fn:motor"]);
  assert.equal(m.rows.get("+fn:pump"), undefined);
});

test("levels count functions and failures; the one search and the chips reach the RCM rows", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM);
  const { list } = flatten(d, levelSet(d, 3));
  assert.ok(list.some((v) => v.key === "f1") && !list.some((v) => v.key === "x1"));
  assert.ok(flatten(d, levelSet(d, Infinity)).list.some((v) => v.key === "m3"));
  const found = computeFilter(d, { query: "impeller" });
  assert.deepEqual([...found.match], ["m3"]);
  assert.ok(found.keep.has("x2") && found.keep.has("f1") && found.keep.has("pump") && found.keep.has("plant"));
  assert.deepEqual([...computeFilter(d, { chips: ["undecided"] }).match].sort(), ["m1", "m3"]);
  assert.deepEqual([...computeFilter(d, { chips: ["unanalysed"] }).match].sort(), ["motor", "plant", "pump"]);
  // Opening the tab on the pump opens it down to its failure modes.
  assert.deepEqual([...openFor(d, "pump")].sort(), ["U:pump", "f1", "f2", "pump", "x1", "x2"]);
});
