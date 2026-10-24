import { test } from "node:test";
import assert from "node:assert/strict";
import { flatten, levelSet } from "./outlineTree.js";
import {
  COLUMN, DEFAULT_COLUMNS, NAME_COLUMN, addNode, buildRcmDisplay, checkValue, chipCounts, computeFilter,
  insideWords, intervalText, loadPrefs, patchNode, rememberedOpen, removeNode, savePrefs, setCell, siblingOrder,
  withOpen, worksheetCsvRows, POSITION_COLUMN, buildPositionRcmDisplay, decisionBody, failuresOn,
} from "./rcmWorksheet.js";

// A house pool pump, as the server sends it back (decisions resolved).
const STUDY = [
  { id: "f1", text: "Circulate the water", standard: "12 m³/h", failures: [
    { id: "x1", text: "No flow", modes: [
      { id: "m1", text: "Bearing seizes", effects: "Pump stops", consequence: "operational",
        decision: { outcome: "fixed_interval", task: "Replace bearings", interval: 3, interval_unit: "years", status: "supported" } },
      { id: "m2", text: "Capacitor fails", consequence: "non_operational",
        decision: { outcome: "rtf", rtf_basis: "random", status: "contradicted" } },
      { id: "m3", text: "Impeller worn", consequence: null, decision: null },
    ] },
  ] },
  { id: "f2", text: "Protect against dry running", failures: [
    { id: "x2", text: "Runs dry without tripping", modes: [
      { id: "m4", text: "Level switch stuck (hidden)", consequence: "hidden",
        decision: { outcome: "failure_finding", task: "Test the switch", interval: 1, interval_unit: "months", status: "unevidenced" } },
      { id: "m5", text: "Earth leakage device fails", consequence: "safety", decision: null },
    ] },
  ] },
];

test("the display: three levels, each row counting the failure modes inside it", () => {
  const d = buildRcmDisplay(STUDY);
  assert.deepEqual(d.counts, { fn: 2, fail: 2, mode: 5 });
  assert.deepEqual(d.roots, ["f1", "f2"]);
  const f1 = d.rows.get("f1");
  assert.equal(f1.type, "fn");
  assert.deepEqual(d.rows.get("m3").at, [0, 0, 2]);
  assert.equal(d.rows.get("m3").depth, 2);
  assert.deepEqual(
    { modes: f1.sum.modes, undecided: f1.sum.undecided, tasks: f1.sum.tasks, supported: f1.sum.supported, contradicted: f1.sum.contradicted },
    { modes: 3, undecided: 1, tasks: 1, supported: 1, contradicted: 1 },
  );
  assert.equal(insideWords(f1), "3 failure modes · 1 to decide · 1 with a task");
  assert.equal(insideWords(d.rows.get("x2")), "2 failure modes · 1 to decide · 1 with a task");
  assert.equal(d.rows.get("f2").sum.hidden, 1);
  assert.equal(d.rows.get("f2").sum.safety, 1);
  // Level 1: functions only; level 2: their failures too.
  assert.deepEqual(flatten(d, levelSet(d, 1)).list.map((v) => v.key), ["f1", "f2"]);
  assert.deepEqual(flatten(d, levelSet(d, 2)).list.map((v) => v.key), ["f1", "x1", "f2", "x2"]);
});

test("a repeated id still gets a row of its own", () => {
  const d = buildRcmDisplay([{ id: "same", text: "A", failures: [{ id: "same", text: "B", modes: [] }] }]);
  assert.equal(d.rows.size, 2);
  assert.deepEqual([...d.rows.keys()], ["same", "same~"]);
});

test("the cells, as text: decisions, intervals, roll-ups", () => {
  const d = buildRcmDisplay(STUDY);
  const m = (k) => d.rows.get(k);
  assert.equal(COLUMN.decision.text(m("m2")), "Run-to-failure (random)");
  assert.equal(COLUMN.decision.text(m("m3")), "To decide");
  assert.equal(COLUMN.decision.text(m("f1")), "1 to decide");
  assert.equal(COLUMN.interval.text(m("m1")), "3 years");
  assert.equal(intervalText({ interval: 1, interval_unit: "months" }), "1 month");
  assert.equal(COLUMN.task.text(m("x2")), "1 task");
  assert.equal(COLUMN.check.text(m("f1")), "1 contradicted, 1 supported");
  assert.equal(COLUMN.consequence.text(m("f2")), "1 safety or env.");
  assert.equal(COLUMN.evident.text(m("m4")), "Hidden");
  assert.equal(COLUMN.standard.text(m("f1")), "12 m³/h");
  // The default set fits a 1440 px window with the menu open (about 1,140 px for the grid).
  const width = DEFAULT_COLUMNS.reduce((s, id) => s + COLUMN[id].width, NAME_COLUMN.width);
  assert.ok(width <= 1140, `default columns are ${width} px wide`);
});

test("chips and text filter failure modes, keeping the path to each", () => {
  const d = buildRcmDisplay(STUDY);
  assert.deepEqual(chipCounts(d), { undecided: 2, hidden: 1, safety: 1, task: 2, notask: 3, check: 2 });
  const f = computeFilter(d, { chips: ["undecided"] });
  assert.deepEqual([...f.match].sort(), ["m3", "m5"]);
  assert.deepEqual([...f.keep].sort(), ["f1", "f2", "m3", "m5", "x1", "x2"]);
  assert.deepEqual([...computeFilter(d, { query: "replace bear" }).match], ["m1"]);
  assert.deepEqual([...computeFilter(d, { chips: ["undecided", "safety"] }).match], ["m5"]);
  assert.equal(computeFilter(d, { query: "  " }), null);
  assert.equal(computeFilter(d, { query: "nothing like it" }).match.size, 0);
});

test("sorting keeps the tree: siblings in order, blanks last", () => {
  const d = buildRcmDisplay(STUDY);
  const byInterval = siblingOrder(d, { col: "interval", dir: -1 });
  assert.deepEqual(byInterval(["m1", "m2", "m3"]), ["m1", "m2", "m3"]);
  const byName = siblingOrder(d, { col: "name", dir: 1 });
  assert.deepEqual(byName(["m1", "m2", "m3"]), ["m1", "m2", "m3"]);
  assert.deepEqual(siblingOrder(d, { col: "name", dir: -1 })(["m1", "m2", "m3"]), ["m3", "m2", "m1"]);
  // Decision: undecided first going up; a parent sorts by how many are left to decide.
  assert.deepEqual(siblingOrder(d, { col: "decision", dir: 1 })(["m1", "m2", "m3"]), ["m3", "m1", "m2"]);
  assert.deepEqual(siblingOrder(d, { col: "check", dir: 1 })(["m1", "m2", "m3"]), ["m2", "m1", "m3"]);
  const all = flatten(d, levelSet(d, Infinity), null, siblingOrder(d, { col: "name", dir: -1 })).list.map((v) => v.key);
  assert.deepEqual(all, ["f2", "x2", "m4", "m5", "f1", "x1", "m3", "m2", "m1"]);
  assert.equal(siblingOrder(d, null), null);
});

test("edits: change, add and remove, each a new list; cells checked as the server checks them", () => {
  const d = buildRcmDisplay(STUDY);
  const m1 = d.rows.get("m1");
  assert.deepEqual(checkValue("name", m1, "  "), { error: "Every failure mode needs a description." });
  assert.deepEqual(checkValue("interval", m1, "-2"), { error: "The task interval must be positive." });
  assert.deepEqual(checkValue("interval", m1, "abc"), { error: "The task interval must be a number." });
  assert.deepEqual(checkValue("interval", m1, ""), { value: null });
  assert.deepEqual(checkValue("consequence", m1, "nonsense"), { value: null });
  assert.deepEqual(checkValue("effects", m1, " Leaks "), { value: "Leaks" });

  let next = setCell(STUDY, m1, "interval", 4);
  assert.equal(next[0].failures[0].modes[0].decision.interval, 4);
  assert.equal(STUDY[0].failures[0].modes[0].decision.interval, 3, "the original is untouched");
  next = setCell(next, m1, "name", "Bearing seizes early");
  assert.equal(next[0].failures[0].modes[0].text, "Bearing seizes early");
  next = setCell(next, d.rows.get("m3"), "consequence", "hidden");
  assert.equal(next[0].failures[0].modes[2].consequence, "hidden");
  next = setCell(next, m1, "dnotes", "Per the OEM");
  assert.equal(next[0].failures[0].modes[0].decision.notes, "Per the OEM");
  next = setCell(next, d.rows.get("f1"), "standard", "13 m³/h");
  assert.equal(next[0].standard, "13 m³/h");
  // A mode without a decision has no task to change.
  assert.equal(setCell(STUDY, d.rows.get("m3"), "task", "x")[0].failures[0].modes[2].decision, null);

  const added = addNode(STUDY, [0, 0]);
  assert.equal(added.functions[0].failures[0].modes.length, 4);
  assert.equal(added.functions[0].failures[0].modes[3].id, added.id);
  assert.equal(addNode(STUDY, [1]).functions[1].failures.length, 2);
  assert.equal(addNode(STUDY, null).functions.length, 3);
  assert.equal(removeNode(STUDY, [0, 0, 1])[0].failures[0].modes.map((m) => m.id).join(), "m1,m3");
  assert.equal(removeNode(STUDY, [1, 0])[1].failures.length, 0);
  assert.equal(removeNode(STUDY, [0]).length, 1);
  assert.equal(patchNode(STUDY, [1, 0], { text: "Dry run" })[1].failures[0].text, "Dry run");
  // Only the columns that allow it are edited in place.
  assert.equal(COLUMN.task.can(d.rows.get("m2")), true); // run-to-failure: the action on failure
  assert.equal(COLUMN.interval.can(d.rows.get("m2")), false);
  assert.equal(COLUMN.task.can(d.rows.get("m3")), false);
  assert.equal(COLUMN.effects.can(d.rows.get("f1")), false);
});

test("the CSV: one row per failure mode", () => {
  const rows = worksheetCsvRows(STUDY);
  assert.equal(rows.length, 6);
  assert.equal(rows[0][0], "function");
  assert.deepEqual(rows[1].slice(0, 3), ["Circulate the water", "No flow", "Bearing seizes"]);
  assert.equal(rows[1][8], 3);
});

test("remembered on this device: columns, widths, row height and each study's open rows", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(loadPrefs(storage).cols, DEFAULT_COLUMNS);
  const d = buildRcmDisplay(STUDY);
  savePrefs(withOpen({ cols: ["task", "nope"], widths: { task: 300, bogus: 4 }, density: "compact", open: {} }, "s1", new Set(["f1", "gone"])), storage);
  const p = loadPrefs(storage);
  assert.deepEqual(p.cols, ["task"]);
  assert.deepEqual(p.widths, { task: 300 });
  assert.equal(p.density, "compact");
  assert.deepEqual([...rememberedOpen(p, "s1", d)], ["f1"]);
  assert.equal(rememberedOpen(p, "s2", d), null);
  // Storage that throws: the defaults, and saving quietly does nothing.
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadPrefs(broken).density, "comfortable");
  assert.doesNotThrow(() => savePrefs(p, broken));
});

// ---- the RCM on the positions (an Explorer position's RCM tab) -------------

const SHEET = {
  scope: "below",
  positions: [
    { id: "p1", name: "Plant", depth: 0, analysed: false, functions: [], unassigned: [] },
    { id: "p2", name: "Pump", depth: 1, analysed: false, functions: [
      { id: "f1", text: "Pump water", failures: [{ id: "x1", text: "No flow", modes: [
        { id: "m1", text: "Bearing", consequence: "hidden", decision: { outcome: "rtf", rtf_basis: "random", status: "contradicted", evidence: { type: "model", id: "e" } } },
      ] }] },
    ], unassigned: [{ id: "m2", text: "Seal", consequence: null, decision: null }] },
    { id: "p3", name: "Motor", depth: 2, analysed: false, functions: [], unassigned: [] },
  ],
};

test("the positions' RCM: no position rows (the tree is the index); the Position column names them", () => {
  const d = buildPositionRcmDisplay(SHEET);
  assert.equal(d.many, true);
  assert.ok(![...d.rows.values()].some((r) => r.type === "pos"));
  assert.deepEqual(d.roots, ["f1", "U:p2"]);
  assert.equal(d.rows.get("f1").ref.position_path, "Pump");
  assert.equal(POSITION_COLUMN.text(d.rows.get("f1")), "Pump");
  assert.equal(POSITION_COLUMN.text(d.rows.get("m1")), "");
  assert.equal(d.rows.get("m1").depth, 2);
  assert.equal(d.rows.get("m2").ref.functional_failure_id, null);
  assert.equal(d.rows.get("m1").ref.position_id, "p2");
  // Roll-ups count every mode inside.
  assert.equal(d.rows.get("f1").sum.contradicted, 1);
  assert.equal(d.rows.get("U:p2").sum.undecided, 1);
  assert.deepEqual(failuresOn(d, "p2"), [{ id: "x1", text: "No flow", function: "Pump water" }]);
  // A deeper position is named by its path below the one picked.
  const deep = buildPositionRcmDisplay({ positions: [SHEET.positions[0], SHEET.positions[1],
    { ...SHEET.positions[2], functions: [{ id: "f9", text: "Turn", failures: [] }] }] });
  assert.equal(deep.rows.get("f9").ref.position_path, "Pump › Motor");
  // One position: no paths (no Position column).
  const one = buildPositionRcmDisplay({ positions: [SHEET.positions[1]] });
  assert.equal(one.many, false);
  assert.equal(one.rows.get("f1").ref.position_path, undefined);
});

test("a decision goes back without the evidence check, a change applied", () => {
  const d = { outcome: "fixed_interval", task: "Replace", interval: 6, interval_unit: "months", status: "supported",
    summary: "ok", artifact_name: "A", evidence: { type: "strategy_analysis", id: "a" }, task_id: "t1" };
  assert.deepEqual(decisionBody(d), { outcome: "fixed_interval", task: "Replace", interval: 6, interval_unit: "months",
    evidence: { type: "strategy_analysis", id: "a" } });
  assert.deepEqual(decisionBody(d, { interval: null }), { outcome: "fixed_interval", task: "Replace",
    evidence: { type: "strategy_analysis", id: "a" } });
  assert.equal(decisionBody({ outcome: "fixed_interval" }, { interval: 3 }).interval_unit, "hours");
  assert.equal(decisionBody(null), null);
});
