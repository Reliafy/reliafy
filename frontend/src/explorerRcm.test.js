import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, flatten, levelSet, markersOf } from "./assetTree.js";
import {
  ITEM_FIELDS, NARROW_TABLE, TASK_WITH_INTERVAL, basisInName, causeKey, checkItem, failureStatusWords, itemChanges, itemValue, itemWrites, opensItem, filterChoices, fitWidths, graftRcm, linkChoices, unlinkEmptiesFailure, hasLinkedEvidence, isRcmRow, openFor, positionOf, rowActions, secondTaskHint, tableCols,
  taskWithInterval, usualCols, withTableCols,
} from "./explorerRcm.js";
import { COLUMN, DEFAULT_COLUMNS, belowDecisionText, insideWords, phoneLine, failuresOn, loadPrefs, savePrefs } from "./rcmWorksheet.js";

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
  assert.deepEqual(ids("pump"), ["add-fn", "import-sheet", "export-csv"]);
  assert.deepEqual(ids("motor"), ["add-fn", "import-sheet", "export-csv"]); // a position with no RCM yet
  assert.deepEqual(ids("f1"), ["open", "add-fail", "rename", "delete"]);
  assert.deepEqual(ids("x1"), ["open", "add-mode", "link-cause", "link-effect", "rename", "delete"]); // pump has a position above it
  assert.deepEqual(ids("m1"), ["open", "decide", "add-task", "rename", "delete"]);
  assert.deepEqual(ids("U:pump"), []); // the "Not under a functional failure" heading has none
  // On a phone the details panel edits the description, so no Edit description.
  // Open… stays on a phone: it's the way to the dialog there (no double-click).
  assert.deepEqual(ids("f1", { canRename: false }), ["open", "add-fail", "delete"]);
  const label = (key) => rowActions(d.rows.get(key)).map((a) => a.label);
  assert.deepEqual(label("f1"), ["Open…", "Add functional failure", "Edit description", "Delete function"]);
  assert.equal(label("m2")[1], "Change the decision…");
  assert.equal(label("m1")[1], "Decide…");
  assert.equal(label("m1")[2], "Add a task…");
  assert.deepEqual(rowActions(null), []);
});

test("the Task cell says how many more tasks a mode has; a second task on a cost-only consequence asks why", () => {
  const two = { id: "m", text: "Acid under-dosed", consequence: "operational", decision: {
    outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks", task_id: "t1",
    tasks: [{ id: "t1", name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", shared_with: 2 },
      { id: "t2", name: "Replace the acid pump", text: "Replace the acid pump", interval: 24, unit: "months", shared_with: 0 }] } };
  const row = (m) => ({ type: "mode", ref: m, sum: { modes: 1, tasks: 1 }, kids: [] });
  assert.equal(taskWithInterval(row(two)), "Weekly pH check · every 1 week · +1 task");
  assert.equal(COLUMN.task.text(row(two)), "Weekly pH check · +1 task");
  assert.equal(TASK_WITH_INTERVAL.text(row(two)), "Weekly pH check · every 1 week · +1 task");
  assert.match(secondTaskHint(row(two)), /What does this task catch that “Weekly pH check” doesn't\?/);
  assert.equal(secondTaskHint(row({ ...two, consequence: "safety" })), null);
  assert.equal(secondTaskHint(row({ ...two, decision: null })), null);
  // One task, or an older read with only the decision's task: nothing more.
  const one = { ...two, decision: { ...two.decision, tasks: two.decision.tasks.slice(0, 1) } };
  assert.equal(taskWithInterval(row(one)), "Weekly pH check · every 1 week");
  const old = { ...two, decision: { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks" } };
  assert.equal(taskWithInterval(row(old)), "Weekly pH check · every 1 week");
  assert.equal(phoneLine(row(two)), "Operational · On-condition · 1 week · Weekly pH check · +1 task");
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

test("the usual columns by the window's width: under 1400 px, no Interval (it's in the Task cell) and no Evidence check", () => {
  assert.equal(NARROW_TABLE, 1400);
  const fresh = loadPrefs({ getItem: () => null });
  assert.equal(fresh.colsChosen, undefined);
  assert.deepEqual(tableCols(fresh, false, { narrow: true }), ["effects", "consequence", "decision", "task"]);
  assert.deepEqual(tableCols(fresh, true, { narrow: true }), ["effects", "consequence", "decision", "task"]); // even with evidence linked
  assert.deepEqual(tableCols(fresh, false, { narrow: false }), ["effects", "consequence", "decision", "task", "interval"]);
  assert.deepEqual(tableCols(fresh, true, { narrow: false }), ["effects", "consequence", "decision", "task", "interval", "check"]);
  assert.deepEqual(usualCols({ narrow: true }), ["effects", "consequence", "decision", "task"]);
  // Saved before as the usual set (the page saves its prefs as it opens): still the usual ones, by width.
  const saved = loadPrefs({ getItem: () => JSON.stringify({ cols: DEFAULT_COLUMNS }) });
  assert.equal(saved.colsChosen, undefined);
  assert.deepEqual(tableCols(saved, false, { narrow: true }), ["effects", "consequence", "decision", "task"]);
  // Chosen in the Columns menu: kept whatever the width, and remembered.
  const shown = tableCols(fresh, false, { narrow: true });
  const withInterval = withTableCols(fresh, [...shown, "interval"], shown);
  assert.equal(withInterval.colsChosen, true);
  assert.deepEqual(tableCols(withInterval, false, { narrow: true }), ["effects", "consequence", "decision", "task", "interval"]);
  let stored = null;
  const box = { getItem: () => stored, setItem: (k, v) => { stored = v; } };
  savePrefs(withInterval, box);
  assert.equal(loadPrefs(box).colsChosen, true);
  const noTask = withTableCols(fresh, shown.filter((c) => c !== "task"), shown);
  assert.deepEqual(tableCols(noTask, false, { narrow: false }), ["effects", "consequence", "decision"]);
  // Columns chosen before this was remembered (not the usual set): chosen.
  assert.equal(loadPrefs({ getItem: () => JSON.stringify({ cols: ["effects", "task"] }) }).colsChosen, true);
  // Show the usual columns: by width again; the shared set back to its usual.
  const reset = withTableCols(withInterval, usualCols({ narrow: true }), tableCols(withInterval, false, { narrow: true }), { reset: true });
  assert.equal("colsChosen" in reset, false);
  assert.deepEqual(reset.cols, DEFAULT_COLUMNS);
  assert.deepEqual(tableCols(reset, false, { narrow: true }), ["effects", "consequence", "decision", "task"]);
  savePrefs(reset, box);
  assert.equal(loadPrefs(box).colsChosen, undefined);
});

test("the columns narrow to fit the pane before the table scrolls sideways, never below their least", () => {
  const ids = ["effects", "consequence", "decision", "task"];
  const w = { effects: 180, consequence: 114, decision: 150, task: 190 }; // 634
  assert.deepEqual(fitWidths(ids, w, 900), w); // room to spare: as they are (never widened)
  const fit = fitWidths(ids, w, 500);
  assert.equal(Object.values(fit).reduce((a, b) => a + b, 0), 500);
  for (const id of ids) assert.ok(fit[id] >= COLUMN[id].min && fit[id] <= w[id], id);
  // Each gives up the same share of its slack.
  assert.ok(fit.effects < 180 && fit.task < 190 && fit.consequence < 114);
  // Too little room: each at its least, and the table scrolls.
  const least = fitWidths(ids, w, 200);
  for (const id of ids) assert.equal(least[id], COLUMN[id].min);
  // The side panel open at 1280 px: the four main columns still fit.
  const mins = ids.reduce((t, id) => t + COLUMN[id].min, 0);
  assert.ok(mins <= 410, `the four columns at their least: ${mins} px`);
  // A width already under its least (chosen narrower before) isn't widened.
  assert.equal(fitWidths(["task"], { task: 80 }, 60).task, 80);
  assert.deepEqual(fitWidths(ids, w, NaN), w);
});

test("the Task cell with the interval folded in", () => {
  const m = (decision) => ({ type: "mode", ref: { decision } });
  assert.equal(taskWithInterval(m({ outcome: "fixed_interval", task: "Inspect roof tubes", interval: 12, interval_unit: "months" })),
    "Inspect roof tubes · every 12 months");
  assert.equal(taskWithInterval(m({ outcome: "fixed_interval", task: "Empty the basket", interval: 1, interval_unit: "weeks" })),
    "Empty the basket · every 1 week");
  assert.equal(taskWithInterval(m({ outcome: "on_condition", interval: 3, interval_unit: "months" })), "Every 3 months");
  assert.equal(taskWithInterval(m({ outcome: "rtf", task: "Replace the motor" })), "Replace the motor");
  assert.equal(taskWithInterval(m(null)), "");
  // A parent row: what's inside it, as the Task column says.
  assert.equal(taskWithInterval({ type: "fn", ref: {}, sum: { tasks: 2 } }), "2 tasks");
  assert.equal(TASK_WITH_INTERVAL.id, "task");
  assert.equal(TASK_WITH_INTERVAL.edit, "text"); // still edits the task itself
});

test("the (i) for a working sits in the name while the Performance standard column is hidden", () => {
  assert.equal(basisInName(tableCols({}, false)), true);
  assert.equal(basisInName(["standard", "effects"]), false);
  assert.equal(basisInName(tableCols({ colsChosen: true, cols: ["standard", "effects"] }, false)), false);
});

test("the one search box also reaches the first words of a working, never the whole text", () => {
  const display = graftRcm(buildDisplay(DATA, "positions"), {
    positions: [{ id: "pump", functions: [{ id: "f", text: "Keep it clean", standard: "", has_basis: true,
      basis_preview: "Chlorine demand 4.3 ppm per day", failures: [] }] }],
  });
  const f = computeFilter(display, { query: "chlorine demand" });
  assert.ok(f.keep.has("f"));
  assert.equal(computeFilter(display, { query: "turnover" })?.keep.has("f") ?? false, false);
});

// ---- a functional failure caused by lower ones ---------------------------------------

const roll = (modes, undecided, tasks) => ({ modes, undecided, tasks, hidden: 0, safety: 0, mode_ids: [] });
const cause = (id, text, pos, name, over = {}) => ({
  id, text, position: { id: pos, name }, inside: true, covered: true, chain: roll(2, 0, 1), ...over,
});
const LINKED = {
  positions: [
    { id: "plant", functions: [{ id: "pf", text: "Make power", failures: [
      { id: "px", text: "No power", modes: [mode("pm", "Own cause", { outcome: "accept" })],
        causes: [cause("x1", "No flow", "pump", "Pump", { chain: { ...roll(3, 1, 1), mode_ids: ["m1", "m2", "m3"] }, covered: false })],
        effects: [], below: roll(3, 1, 1), covered: false, explained_below: false },
      { id: "py", text: "Output low", modes: [], causes: [cause("x2", "Low flow", "pump", "Pump"), cause("mx", "Motor stops", "motor", "Motor")],
        effects: [], below: roll(4, 0, 2), covered: true, explained_below: true },
    ] }], unassigned: [] },
    { id: "pump", functions: [{ id: "f1", text: "Pump water", failures: [
      { id: "x1", text: "No flow", modes: [mode("m1", "Bearing seizes"), mode("m2", "Seal leaks", { outcome: "rtf" })],
        causes: [], effects: [{ id: "px", text: "No power", position: { id: "plant", name: "Plant" }, inside: true }], below: null },
      { id: "x2", text: "Low flow", modes: [mode("m3", "Impeller worn")], causes: [],
        effects: [{ id: "py", text: "Output low", position: { id: "plant", name: "Plant" }, inside: true }], below: null },
    ] }], unassigned: [] },
    { id: "motor", functions: [{ id: "mf", text: "Turn", failures: [{ id: "mx", text: "Motor stops", modes: [], causes: [],
      effects: [{ id: "py", text: "Output low", position: { id: "plant", name: "Plant" }, inside: true }], below: null }] }], unassigned: [] },
  ],
};

test("a reference row under a higher failure per cause, after its own modes, with the chain's roll-up", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  assert.deepEqual(d.rows.get("px").kids, ["pm", causeKey("px", "x1")]);
  assert.deepEqual(d.rows.get("py").kids, [causeKey("py", "x2"), causeKey("py", "mx")]);
  const ref = d.rows.get(causeKey("px", "x1"));
  assert.equal(ref.type, "cause");
  assert.ok(isRcmRow(ref));
  assert.equal(ref.ref.on, "Pump");
  assert.equal(ref.ref.cause_id, "x1");
  assert.equal(ref.depth, d.rows.get("pm").depth);
  assert.deepEqual(ref.kids, []);
  // The chain's own failure modes (m1, m2, m3), counted as a mode's are.
  assert.equal(ref.rsum.modes, 3);
  assert.equal(ref.rsum.undecided, 2);
  assert.equal(positionOf(ref), "plant"); // the position the failure it explains is on
});

test("positions, functions and failures count their own failure modes: a chain below is not added in", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  assert.equal(d.rows.get("plant").rsum.modes, 1);
  assert.equal(d.rows.get("pf").rsum.modes, 1);
  assert.equal(d.rows.get("px").rsum.modes, 1);
  assert.equal(d.rows.get("py").rsum.modes, 0);
  assert.equal(d.rows.get("pump").rsum.modes, 3);
});

test("the Decision and Task cells say what is below, and the panel and phone lines match", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const cell = (key) => ({ ...d.rows.get(key), sum: d.rows.get(key).rsum });
  // Own failure modes and a chain with one still to decide.
  assert.equal(COLUMN.decision.text(cell("px")), "All decided · 1 to decide below");
  assert.equal(COLUMN.task.text(cell("px")), "1 below");
  // No failure modes of its own, all decided below.
  assert.equal(COLUMN.decision.text(cell("py")), "Explained below");
  assert.equal(COLUMN.task.text(cell("py")), "2 below");
  assert.equal(belowDecisionText(cell("py")), "Explained below");
  assert.equal(insideWords(cell("py")), "Explained below");
  assert.equal(phoneLine(cell("py")), "Explained below");
  assert.equal(phoneLine(cell("px")), "1 failure mode · all decided · 1 to decide below");
  // A failure with nothing linked reads as it did.
  assert.equal(COLUMN.decision.text(cell("x1")), "1 to decide");
  assert.equal(COLUMN.task.text(cell("x1")), "");
  // A reference row's phone lines: where it is, and its chain.
  const ref = cell(causeKey("px", "x1"));
  assert.equal(phoneLine(ref), "on Pump · 2 to decide");
  assert.equal(COLUMN.decision.text(ref), "2 to decide");
});

test("a failure shows ↑ n for the failures above it that it causes (and only there)", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const m = markersOf(d.rows.get("x1"));
  assert.equal(m.length, 1);
  assert.equal(m[0].text, "↑ 1");
  assert.equal(m[0].effect, "px");
  assert.equal(m[0].label, "Causes: No power (on Plant)");
  assert.deepEqual(markersOf(d.rows.get("px")), []);
  assert.deepEqual(markersOf(d.rows.get("m1")), []);
  assert.deepEqual(markersOf(d.rows.get(causeKey("px", "x1"))), []);
});

test("row menus: a failure offers Link to a cause and, with a position above, Link to an effect; a reference row Go to it and Unlink", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const labels = (key) => rowActions(d.rows.get(key)).map((a) => a.label);
  assert.deepEqual(labels("px"), ["Open…", "Add failure mode", "Link to a cause…", "Edit description", "Delete functional failure"]); // the plant is the top
  assert.deepEqual(labels("x1"), ["Open…", "Add failure mode", "Link to a cause…", "Link to an effect…", "Edit description", "Delete functional failure"]);
  assert.deepEqual(labels(causeKey("px", "x1")), ["Go to it", "Unlink"]);
  assert.deepEqual(rowActions(d.rows.get(causeKey("px", "x1")), { canRename: false }).map((a) => a.id), ["go", "unlink"]);
  assert.deepEqual(rowActions(d.rows.get("f1")).map((a) => a.id), ["open", "add-fail", "rename", "delete"]);
});

test("opening a position's RCM opens functions and failures, so the reference rows show", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const open = openFor(d, "plant");
  assert.ok(open.has("px") && open.has("py"));
  assert.ok(![...open].some((k) => k.startsWith("L:")));
});

test("the pickers: a cause is on a position inside, an effect on one above; linked ones are marked", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const down = linkChoices(d, "px", "cause");
  assert.deepEqual(down.map((g) => [g.name, g.depth]), [["Pump", 0], ["Motor", 1]]);
  assert.deepEqual(down[0].items.map((i) => [i.text, i.linked]), [["No flow", true], ["Low flow", false]]);
  assert.equal(down[0].items[0].function, "Pump water");
  assert.equal(down[0].items[1].summary, "1 failure mode · 1 to decide");
  assert.equal(down[1].items[0].summary, "no failure modes yet");
  assert.deepEqual(down[0].functions, [{ id: "f1", text: "Pump water" }]);
  // Upwards from the motor: the nearest first.
  const up = linkChoices(d, "mx", "effect");
  assert.deepEqual(up.map((g) => g.name), ["Pump", "Plant"]);
  assert.deepEqual(up[1].items.map((i) => [i.text, i.linked]), [["No power", false], ["Output low", true]]);
  assert.equal(up[1].items[1].summary, "explained below");
  // The failure's own position is left out, and a failure with nothing above has no effect choices.
  assert.deepEqual(linkChoices(d, "px", "effect"), []);
  assert.deepEqual(linkChoices(d, "m1", "cause"), []);
});

test("the picker's filter matches the position, function or failure text", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  const down = linkChoices(d, "px", "cause");
  assert.equal(filterChoices(down, "  ").length, 2);
  assert.deepEqual(filterChoices(down, "low flow").map((g) => g.items.map((i) => i.text)), [["Low flow"]]);
  assert.deepEqual(filterChoices(down, "motor").map((g) => g.name), ["Motor"]);
  assert.equal(filterChoices(down, "pump")[0].items.length, 2); // the position's name keeps all its failures
  assert.deepEqual(filterChoices(down, "zzz"), []);
});

test("unlinking asks only when it would leave the higher failure with nothing explaining it", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), LINKED);
  assert.equal(unlinkEmptiesFailure(d, "px", "x1"), false); // it has a failure mode of its own
  assert.equal(unlinkEmptiesFailure(d, "py", "x2"), false); // another cause stays
  const one = graftRcm(buildDisplay(DATA, "positions"), { positions: [
    { id: "plant", functions: [{ id: "pf", text: "Make power", failures: [
      { id: "py", text: "Output low", modes: [], causes: [cause("x2", "Low flow", "pump", "Pump")], effects: [], below: roll(1, 0, 0) }] }], unassigned: [] }] });
  assert.equal(unlinkEmptiesFailure(one, "py", "x2"), true);
  assert.equal(unlinkEmptiesFailure(one, "py", "nope"), false);
  assert.equal(unlinkEmptiesFailure(one, "missing", "x2"), false);
});

test("a link whose cause is no longer inside still shows, and is said to be", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), { positions: [
    { id: "plant", functions: [{ id: "pf", text: "Make power", failures: [
      { id: "py", text: "Output low", modes: [], causes: [cause("x2", "Low flow", "pump", "Pump", { inside: false, covered: false })], effects: [], below: null }] }], unassigned: [] }] });
  const ref = d.rows.get(causeKey("py", "x2"));
  assert.equal(ref.ref.inside, false);
  assert.match(phoneLine({ ...ref, sum: ref.rsum }), /no longer inside Plant/);
  // It doesn't count: no "explained below" on the failure.
  const f = { ...d.rows.get("py"), sum: d.rows.get("py").rsum };
  assert.equal(COLUMN.decision.text(f), "");
});

test("a row's dialog: which rows open one, and what Save sends", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM);
  const row = (k) => d.rows.get(k);
  assert.deepEqual(["pump", "f1", "x1", "m1", "U:pump", "m4"].map((k) => opensItem(row(k))), [false, true, true, true, false, true]);
  assert.equal(opensItem(null), false);
  assert.deepEqual(ITEM_FIELDS.mode, ["name", "effects", "consequence", "notes"]);

  // Only what was typed differently counts (spaces at the ends don't).
  const m1 = row("m1");
  assert.equal(itemValue(m1, "consequence"), "operational");
  assert.deepEqual(itemChanges(m1, {}), {});
  assert.deepEqual(itemChanges(m1, { name: " Bearing seizes " }), {});
  assert.deepEqual(itemChanges(m1, { effects: "Pump stops", consequence: "hidden" }), { effects: "Pump stops", consequence: "hidden" });

  // Checked as the table and the panel check them.
  assert.deepEqual(checkItem(m1, { name: "  " }).errors, { name: "Every failure mode needs a description." });
  const long = checkItem(row("f1"), { name: "x".repeat(201) });
  assert.match(long.errors.name, /Shorten it to 200 characters/);
  const ok = checkItem(m1, { name: " Bearing seizes early ", consequence: "", effects: " Stops " });
  assert.deepEqual(ok, { values: { name: "Bearing seizes early", consequence: null, effects: "Stops" }, errors: {} });

  // A failure mode's words in one write, its consequence in another; one write for the rest.
  assert.deepEqual(itemWrites(m1, ok.values), [
    { api: "mode", body: { text: "Bearing seizes early", effects: "Stops" } },
    { api: "decide", body: { consequence: null } },
  ]);
  assert.deepEqual(itemWrites(m1, { notes: "n" }), [{ api: "mode", body: { notes: "n" } }]);
  assert.deepEqual(itemWrites(row("f1"), { name: "Pump", standard: "10 L/s" }), [{ api: "function", body: { text: "Pump" } }]); // the standards are a list, saved on their own
  assert.deepEqual(ITEM_FIELDS.fn, ["name"]);
  assert.deepEqual(itemWrites(row("x1"), { name: "No flow at all" }), [{ api: "failure", body: { text: "No flow at all" } }]);
  assert.deepEqual(itemWrites(row("x1"), {}), []);
});

test("a functional failure's state in plain words", () => {
  const blank = { modes: 0, undecided: 0 };
  const ff = (sum, ref = {}) => ({ type: "fail", sum, rsum: sum, ref: { causes: [], ...ref } });
  assert.equal(failureStatusWords(ff({ modes: 2, undecided: 1 })), "1 of its 2 failure modes still needs a decision.");
  assert.equal(failureStatusWords(ff({ modes: 3, undecided: 0 })), "Analysed: all 3 of its failure modes have a decision.");
  assert.equal(failureStatusWords(ff({ modes: 1, undecided: 0 })), "Analysed: its failure mode has a decision.");
  assert.equal(failureStatusWords(ff(blank)), "Not analysed yet: it has no failure modes and nothing linked below.");
  assert.match(failureStatusWords(ff(blank, { causes: [{ id: "c" }], explained_below: true })), /^Covered/);
  assert.match(failureStatusWords(ff(blank, { causes: [{ id: "c" }], explained_below: false })), /^Not finished/);
  assert.match(failureStatusWords(ff({ modes: 1, undecided: 0 }, { causes: [{ id: "c" }] })), /also caused by a failure below/);
});
