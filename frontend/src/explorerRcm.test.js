import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, flatten, levelSet, markersOf } from "./assetTree.js";
import {
  graftRcm, hasLinkedEvidence, isRcmRow, openFor, positionOf, rowActions, tableCols, withTableCols,
} from "./explorerRcm.js";
import { DEFAULT_COLUMNS, failuresOn, loadPrefs } from "./rcmWorksheet.js";

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

test("no Add rows in the tree: adding is from each row's menu", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM);
  assert.ok(![...d.rows.keys()].some((k) => k.startsWith("+")));
  assert.deepEqual(d.rows.get("f2").kids, []);
  assert.deepEqual(d.rows.get("motor").kids, []);
  const ids = (key, opts) => rowActions(d.rows.get(key), opts).map((a) => a.id);
  assert.deepEqual(ids("pump"), ["add-fn"]);
  assert.deepEqual(ids("motor"), ["add-fn"]); // a position with no RCM yet
  assert.deepEqual(ids("f1"), ["add-fail", "rename", "delete"]);
  assert.deepEqual(ids("x1"), ["add-mode", "rename", "delete"]);
  assert.deepEqual(ids("m1"), ["decide", "rename", "delete"]);
  assert.deepEqual(ids("U:pump"), []); // the "Not under a functional failure" heading has none
  // On a phone the details panel edits the description, so no Edit description.
  assert.deepEqual(ids("f1", { canRename: false }), ["add-fail", "delete"]);
  const label = (key) => rowActions(d.rows.get(key)).map((a) => a.label);
  assert.deepEqual(label("f1"), ["Add functional failure", "Edit description", "Delete function"]);
  assert.equal(label("m2")[0], "Change the decision…");
  assert.equal(label("m1")[0], "Decide…");
  assert.deepEqual(rowActions(null), []);
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

test("the Evidence check column: hidden until evidence is linked somewhere, unless chosen", () => {
  // Nothing linked (decisions from judgement, or none yet): no column, no "to check".
  assert.equal(hasLinkedEvidence(RCM), true); // m2 is contradicted: linked evidence
  const plain = { positions: [{ id: "pump", functions: [{ id: "f", failures: [{ id: "x", modes: [
    mode("a", "A", { outcome: "fixed_interval", status: "unevidenced" }), mode("b", "B")] }] }], unassigned: [] }] };
  assert.equal(hasLinkedEvidence(plain), false);
  assert.equal(hasLinkedEvidence(null), false);
  const linkedLater = { positions: [{ id: "p", functions: [], unassigned: [mode("c", "C", { outcome: "rtf", evidence: { type: "model", id: "m" } })] }] };
  assert.equal(hasLinkedEvidence(linkedLater), true);

  const prefs = { cols: DEFAULT_COLUMNS, widths: {} };
  assert.ok(!tableCols(prefs, false).includes("check"));
  assert.ok(tableCols(prefs, true).includes("check"));
  assert.deepEqual(tableCols(prefs, true), DEFAULT_COLUMNS);

  // Ticked on in the Columns menu: shown with nothing linked, and remembered.
  const shown = tableCols(prefs, false);
  const on = withTableCols(prefs, [...shown, "check"], shown);
  assert.equal(on.explorerCheck, true);
  assert.ok(tableCols(on, false).includes("check"));
  // Ticked off: hidden even when evidence is linked.
  const off = withTableCols(prefs, DEFAULT_COLUMNS.filter((c) => c !== "check"), DEFAULT_COLUMNS);
  assert.equal(off.explorerCheck, false);
  assert.ok(!tableCols(off, true).includes("check"));
  // Another column changed: the Evidence check keeps following the evidence,
  // and the shared set (the study worksheet's) keeps its own Evidence check.
  const other = withTableCols(prefs, shown.filter((c) => c !== "effects"), shown);
  assert.equal(other.explorerCheck, undefined);
  assert.ok(!other.cols.includes("effects") && other.cols.includes("check"));
  // Show the usual columns: back to following the evidence.
  const reset = withTableCols(on, DEFAULT_COLUMNS, tableCols(on, false), { reset: true });
  assert.equal("explorerCheck" in reset, false);
  // Remembered on this device with the other column choices.
  assert.equal(loadPrefs({ getItem: () => JSON.stringify({ cols: DEFAULT_COLUMNS, explorerCheck: false }) }).explorerCheck, false);
  assert.equal("explorerCheck" in loadPrefs({ getItem: () => JSON.stringify({ cols: DEFAULT_COLUMNS }) }), false);
});
