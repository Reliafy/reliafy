import { test } from "node:test";
import assert from "node:assert/strict";
import { flatten, levelSet } from "./outlineTree.js";
import {
  COLUMN, DEFAULT_COLUMNS, FUNCTION_MAX, NAME_COLUMN, functionCount, buildRcmDisplay, checkValue, chipCounts, computeFilter,
  insideWords, intervalText, loadPrefs, savePrefs, siblingOrder, decisionBody, hasTask, moreTasks, rowText, tasksOf, tasksTip } from "./rcmWorksheet.js";

// A house pool pump's RCM, as the server sends it back (decisions resolved).
const RCM = [
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
  const d = buildRcmDisplay(RCM);
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
  const d = buildRcmDisplay(RCM);
  const m = (k) => d.rows.get(k);
  assert.equal(COLUMN.decision.text(m("m2")), "Run-to-failure (random)");
  assert.equal(COLUMN.decision.text(m("m3")), "To decide");
  assert.equal(COLUMN.decision.text(m("f1")), "1 to decide");
  assert.equal(COLUMN.interval.text(m("m1")), "3 years");
  assert.equal(intervalText({ interval: 1, interval_unit: "months" }), "1 month");
  assert.equal(COLUMN.task.text(m("x2")), "1 task");
  assert.equal(COLUMN.check.text(m("f1")), "1 contradicted, 1 supported");
  // Nothing linked is quiet: no "No evidence", no "to check" on the parents.
  assert.equal(COLUMN.check.text(m("m4")), "");
  assert.equal(COLUMN.check.text(m("f2")), "");
  assert.equal(m("f2").sum.unlinked, 1);
  assert.equal(m("f2").sum.unsure, 0);
  assert.equal(COLUMN.consequence.text(m("f2")), "1 safety or env.");
  assert.equal(COLUMN.evident.text(m("m4")), "Hidden");
  assert.equal(COLUMN.standard.text(m("f1")), "12 m³/h");
  // The default set fits a 1440 px window with the menu open (about 1,140 px for the grid).
  const width = DEFAULT_COLUMNS.reduce((s, id) => s + COLUMN[id].width, NAME_COLUMN.width);
  assert.ok(width <= 1140, `default columns are ${width} px wide`);
});

test("chips and text filter failure modes, keeping the path to each", () => {
  const d = buildRcmDisplay(RCM);
  // Evidence to look at: linked evidence only (m2 contradicted), not m4 with nothing linked.
  assert.deepEqual(chipCounts(d), { undecided: 2, hidden: 1, safety: 1, task: 2, notask: 3, check: 1 });
  const f = computeFilter(d, { chips: ["undecided"] });
  assert.deepEqual([...f.match].sort(), ["m3", "m5"]);
  assert.deepEqual([...f.keep].sort(), ["f1", "f2", "m3", "m5", "x1", "x2"]);
  assert.deepEqual([...computeFilter(d, { query: "replace bear" }).match], ["m1"]);
  assert.deepEqual([...computeFilter(d, { chips: ["undecided", "safety"] }).match], ["m5"]);
  assert.equal(computeFilter(d, { query: "  " }), null);
  assert.equal(computeFilter(d, { query: "nothing like it" }).match.size, 0);
});

test("sorting keeps the tree: siblings in order, blanks last", () => {
  const d = buildRcmDisplay(RCM);
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

test("cells checked as the server checks them; only the columns that allow it are edited in place", () => {
  const d = buildRcmDisplay(RCM);
  const m1 = d.rows.get("m1");
  assert.deepEqual(checkValue("name", m1, "  "), { error: "Every failure mode needs a description." });
  assert.deepEqual(checkValue("interval", m1, "-2"), { error: "The task interval must be positive." });
  assert.deepEqual(checkValue("interval", m1, "abc"), { error: "The task interval must be a number." });
  assert.deepEqual(checkValue("interval", m1, ""), { value: null });
  assert.deepEqual(checkValue("consequence", m1, "nonsense"), { value: null });
  assert.deepEqual(checkValue("effects", m1, " Leaks "), { value: "Leaks" });
  assert.equal(COLUMN.task.can(d.rows.get("m2")), true); // run-to-failure: the action on failure
  assert.equal(COLUMN.interval.can(d.rows.get("m2")), false);
  assert.equal(COLUMN.task.can(d.rows.get("m3")), false);
  assert.equal(COLUMN.effects.can(d.rows.get("f1")), false);
});

test("remembered on this device: columns, widths and row height; an earlier version's open rows dropped", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(loadPrefs(storage).cols, DEFAULT_COLUMNS);
  savePrefs({ cols: ["task", "nope"], widths: { task: 300, bogus: 4 }, density: "compact", open: { s1: ["f1"] } }, storage);
  const p = loadPrefs(storage);
  assert.deepEqual(p.cols, ["task"]);
  assert.deepEqual(p.widths, { task: 300 });
  assert.equal(p.density, "compact");
  assert.equal(p.open, undefined);
  assert.ok(!JSON.parse(store.get("reliafy.rcmWorksheet")).open);
  // Storage that throws: the defaults, and saving quietly does nothing.
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadPrefs(broken).density, "comfortable");
  assert.doesNotThrow(() => savePrefs(p, broken));
});

// ---- the RCM in the Explorer's tree -----------------------------------------

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

test("a function's text is kept to 200 characters where it's typed; one saved longer before stays editable", () => {
  const fn = { type: "fn", ref: { text: "Pump water" } };
  assert.deepEqual(checkValue("name", fn, "a".repeat(200)), { value: "a".repeat(200) });
  assert.deepEqual(checkValue("name", fn, "a".repeat(201)),
    { error: "Shorten it to 200 characters or fewer to save the change (it's 201)." });
  // Saved longer before: a change must bring it within the limit.
  const long = { type: "fn", ref: { text: "b".repeat(1200) } };
  assert.ok(checkValue("name", long, "b".repeat(1100)).error);
  assert.deepEqual(checkValue("name", long, "Pump water"), { value: "Pump water" });
  // Other rows have no such limit here (the server's own applies).
  assert.deepEqual(checkValue("name", { type: "mode", ref: { text: "" } }, "c".repeat(300)), { value: "c".repeat(300) });
  const c = functionCount("d".repeat(190));
  assert.equal(c.tone, "near");
  assert.equal(c.text, "190 / 200");
  assert.equal(FUNCTION_MAX, 200);
});


test("a decision's tasks: its own first, how many more, the tooltip, and an older read with one", () => {
  const d = { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks", task_id: "t1",
    tasks: [{ id: "t1", name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", shared_with: 1 },
      { id: "t2", name: "Replace the acid pump", text: "Replace the acid pump", interval: 24, unit: "months", shared_with: 0 }] };
  assert.equal(tasksOf(d).length, 2);
  assert.equal(moreTasks(d), "+1 task");
  assert.equal(moreTasks({ ...d, tasks: [...d.tasks, { id: "t3", name: "Look", interval: 1, unit: "months" }] }), "+2 tasks");
  assert.equal(tasksTip(d), "Weekly pH check · every 1 week (shared with 1 other failure mode)\nReplace the acid pump · every 24 months");
  const old = { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks" };
  assert.deepEqual(tasksOf(old), [{ id: null, name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", shared_with: 0 }]);
  assert.equal(moreTasks(old), "");
  assert.deepEqual(tasksOf(null), []);
  assert.deepEqual(tasksOf({ outcome: "rtf", rtf_basis: "random" }), []);
  assert.equal(hasTask({ decision: { outcome: "on_condition", tasks: d.tasks } }), true);
  assert.equal(hasTask({ decision: { outcome: "on_condition" } }), false);
  // The search reaches the other tasks' names too.
  assert.match(rowText({ ref: { text: "Acid", decision: d } }), /replace the acid pump/);
});
