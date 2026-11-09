import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, markersOf } from "./assetTree.js";
import { failuresOn, functionsOn, graftFmea, modesUnder, positionSummary, rowActions } from "./explorerFmea.js";
import { isRcmRow, openFor, positionOf } from "./explorerRcm.js";
import { readFmeaOptions } from "./fmea.js";
import { OPTIONS } from "./fmea.test.js";

const DATA = {
  positions: [
    { id: "uav", name: "Quadcopter UAV", parent_id: null, not_analysed: true },
    { id: "prop", name: "Propulsion", parent_id: "uav", not_analysed: true },
    { id: "motor", name: "Motor", parent_id: "prop", not_analysed: true },
    { id: "gps", name: "GPS receiver", parent_id: "uav", not_analysed: true },
  ],
  locations: [], spares: [], unhomed: [],
};
const m = (id, text, extra = {}) => ({ id, text, consequence: "operational", decision: null, ...extra });
const SCORED = { severity: 9, occurrence: 4, detection: 6, rpn: 216, ap: "H", failure_rate: 8e-5, mode_ratio: 0.5, loss_probability: 1, operating_time: 100, cm: 0.004, severity_class: "I" };
const RCM = {
  positions: [
    {
      id: "motor",
      fmea: { modes: 3, scored: 2, high: 1, medium: 1, low: 0, max_rpn: 216, cr: 0.004, cr_by_class: { I: 0.004 } },
      functions: [
        { id: "f1", text: "Provide thrust",
          // Two modes directly under the function (no functional failure), one under a failure.
          modes: [m("m1", "Bearing seizes", SCORED), m("m2", "Winding shorts", { severity: 5, occurrence: 6, detection: 2, rpn: 60, ap: "M" })],
          failures: [{ id: "x1", text: "No thrust", modes: [m("m3", "Prop breaks", { action: "Check props", action_status: "open" })] }] },
        { id: "f2", text: "Stay cool", modes: [], failures: [] },
      ],
      unassigned: [m("m4", "Connector loose")],
    },
    { id: "gps", fmea: { modes: 1, scored: 1, high: 0, medium: 0, low: 1, max_rpn: 8, cr: null, cr_by_class: {} },
      functions: [{ id: "f3", text: "Fix position", modes: [m("m5", "Antenna detached", { severity: 2, occurrence: 2, detection: 2, rpn: 8, ap: "L" })], failures: [] }], unassigned: [] },
  ],
};
const opts = readFmeaOptions(OPTIONS);

test("the worksheet nested in the tree: position › function › failure modes (direct first, then under failures), then the unassigned", () => {
  const base = buildDisplay(DATA, "positions");
  const d = graftFmea(base, RCM);
  assert.notEqual(d.rows, base.rows);
  assert.ok(d.fmea);
  assert.deepEqual(d.rows.get("motor").kids, ["f1", "f2", "U:motor"]);
  assert.equal(d.rows.get("motor").rcmKids, 3);
  assert.deepEqual(d.rows.get("f1").kids, ["m1", "m2", "m3"]);
  assert.deepEqual(d.rows.get("U:motor").kids, ["m4"]);
  assert.equal(d.rows.get("m1").depth, 4);
  assert.equal(d.rows.get("gps").depth, 1); // the positions keep their place
  // Each mode knows its function and (if any) its functional failure, for the read-only column.
  assert.equal(d.rows.get("m1").ref.failure_text, "");
  assert.equal(d.rows.get("m1").ref.direct, true);
  assert.equal(d.rows.get("m1").ref.function_id, "f1");
  assert.equal(d.rows.get("m3").ref.failure_text, "No thrust");
  assert.equal(d.rows.get("m3").ref.failure_id, "x1");
  assert.equal(d.rows.get("m3").ref.direct, false);
  assert.equal(positionOf(d.rows.get("m3")), "motor");
  assert.ok(isRcmRow(d.rows.get("f1")) && isRcmRow(d.rows.get("m1")) && !isRcmRow(d.rows.get("motor")));
  // The same keys as the RCM tab (the mode's id), so ?sel= carries across.
  assert.ok(d.rows.has("m1") && d.rows.has("m4"));
  // Roll-ups: the function's and the position's.
  const f1 = d.rows.get("f1").rsum;
  assert.equal(f1.modes, 3);
  assert.equal(f1.scored, 2);
  assert.equal(f1.high, 1);
  assert.equal(f1.medium, 1);
  assert.equal(f1.max_rpn, 216);
  assert.equal(f1.action_open, 1);
  assert.ok(Math.abs(f1.cr - 0.004) < 1e-12);
  assert.equal(d.rows.get("motor").rsum.modes, 4);
  assert.equal(d.rows.get("motor").rsum.undecided, 4); // the RCM's counts come along
  assert.equal(d.rows.get("motor").fmea.cr, 0.004); // the server's summary on the position
  // The tree's markers don't count the worksheet's rows as positions inside.
  assert.equal(markersOf(d.rows.get("f1")).length, 0);
  // openFor opens the position, its functions and the unassigned group (the modes are leaves).
  assert.deepEqual([...openFor(d, "motor")].sort(), ["U:motor", "f1", "f2", "motor"]);
});

test("each row's menu on the FME(C)A tab: a function adds a failure mode directly under it; no moving", () => {
  const d = graftFmea(buildDisplay(DATA, "positions"), RCM);
  const ids = (key, o) => rowActions(d.rows.get(key), o).map((a) => a.id);
  assert.deepEqual(ids("motor"), ["add-fn", "import-sheet", "export-csv", "print", "tree-delete"]);
  assert.equal(rowActions(d.rows.get("motor")).at(-1).label, "Delete…");
  assert.equal(rowActions(d.rows.get("f1")).at(-1).label, "Delete function…");
  assert.equal(rowActions(d.rows.get("m1")).at(-1).label, "Delete failure mode…");
  assert.deepEqual(ids("f1"), ["open", "add-mode", "rename", "delete"]);
  assert.deepEqual(ids("m1"), ["open", "score", "rename", "delete"]);
  assert.deepEqual(ids("U:motor"), ["add-mode"]);
  assert.deepEqual(ids("m1", { canRename: false }), ["open", "score", "delete"]);
  assert.deepEqual(rowActions(null), []);
});

test("the chips filter the worksheet's rows, keeping the path to each", () => {
  const d = graftFmea(buildDisplay(DATA, "positions"), RCM);
  const high = computeFilter(d, { chips: ["ap-high"] });
  assert.deepEqual([...high.match], ["m1"]);
  assert.ok(high.keep.has("f1") && high.keep.has("motor") && high.keep.has("uav"));
  assert.deepEqual([...computeFilter(d, { chips: ["ap-medium"] }).match], ["m2"]);
  assert.deepEqual([...computeFilter(d, { chips: ["unscored"] }).match].sort(), ["m3", "m4"]);
  assert.deepEqual([...computeFilter(d, { chips: ["action-open"] }).match], ["m3"]);
  // The search box finds a mode by its cause or action too.
  assert.deepEqual([...computeFilter(d, { query: "check props" }).match], ["m3"]);
});

test("a position's summary for its details: the matrix over it and what's inside, the counts, its own Cr and the Cr with everything inside", () => {
  const d = graftFmea(buildDisplay(DATA, "positions"), RCM);
  // In tree order: the positions inside are A to Z ("GPS receiver" before "Propulsion").
  assert.deepEqual(modesUnder(d, "uav").map((x) => x.id), ["m5", "m1", "m2", "m3", "m4"]);
  assert.deepEqual(modesUnder(d, "gps").map((x) => x.id), ["m5"]);
  const uav = positionSummary(d, "uav", opts);
  assert.equal(uav.inside, true);
  assert.deepEqual(uav.counts, { modes: 5, scored: 3, high: 1, medium: 1, low: 1 });
  assert.equal(uav.own.modes, 0); // nothing of its own
  assert.equal(uav.own.cr, null);
  assert.ok(Math.abs(uav.cr.cr - 0.004) < 1e-12);
  assert.equal(uav.matrix.scored, 3);
  assert.deepEqual(uav.ranked.map((x) => x.id), ["m1"]);
  const motor = positionSummary(d, "motor", opts);
  assert.equal(motor.inside, false);
  assert.equal(motor.own.cr, 0.004);
  assert.equal(motor.own.scored, 2);
  assert.equal(motor.own.modes, 4);
  assert.deepEqual(motor.own.crByClass, { I: 0.004 });
  assert.equal(positionSummary(d, "nope", opts), null);
});

test("the functions and functional failures on a position, from the read, for the Under choice", () => {
  assert.deepEqual(functionsOn(RCM, "motor"), [{ id: "f1", text: "Provide thrust" }, { id: "f2", text: "Stay cool" }]);
  assert.deepEqual(failuresOn(RCM, "motor"), [{ id: "x1", text: "No thrust", function: "Provide thrust", function_id: "f1" }]);
  assert.deepEqual(failuresOn(RCM, "gps"), []);
  assert.deepEqual(functionsOn(null, "motor"), []);
});
