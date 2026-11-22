import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, flatten } from "./assetTree.js";
import { graftRcm } from "./explorerRcm.js";
import { canPin, pinDisplay } from "./treePin.js";
import { canIsolate, depthWords, isolateOpen } from "./treeIsolate.js";

// A plant with two lines, each with a pump and its seal, and a second plant.
const DATA = {
  positions: [
    { id: "plant", name: "Plant", parent_id: null },
    { id: "lineA", name: "Line A", parent_id: "plant" },
    { id: "pumpA", name: "Pump A", parent_id: "lineA" },
    { id: "sealA", name: "Seal A", parent_id: "pumpA" },
    { id: "lineB", name: "Line B", parent_id: "plant" },
    { id: "pumpB", name: "Pump B", parent_id: "lineB" },
    { id: "sealB", name: "Seal B", parent_id: "pumpB" },
    { id: "other", name: "Other plant", parent_id: null },
    { id: "otherLine", name: "Other line", parent_id: "other" },
  ],
  locations: [],
};
const shown = (d, open) => flatten(d, open).list.map((v) => d.rows.get(v.key).ref.name || d.rows.get(v.key).ref.text);
const everything = (d) => new Set([...d.rows.values()].filter((r) => r.kids.length).map((r) => r.key));

test("isolate N levels: the rest closed but on show, the way up open, the row opened exactly that far", () => {
  const d = buildDisplay(DATA, "positions");
  const all = everything(d);
  // Line A, 1 level: its pump shows, closed; Line B and the other plant closed, still there.
  assert.deepEqual(shown(d, isolateOpen(d, all, "lineA", 1)), ["Other plant", "Plant", "Line A", "Pump A", "Line B"]);
  assert.deepEqual(shown(d, isolateOpen(d, all, "lineA", 2)), ["Other plant", "Plant", "Line A", "Pump A", "Seal A", "Line B"]);
  assert.deepEqual(shown(d, isolateOpen(d, all, "lineA", 3)), shown(d, isolateOpen(d, all, "lineA", 2)));
  assert.deepEqual(shown(d, isolateOpen(d, new Set(), "lineA", "all")), ["Other plant", "Plant", "Line A", "Pump A", "Seal A", "Line B"]);
  // The plant, 1 level: both lines show, closed (deeper rows close even if open before).
  assert.deepEqual(shown(d, isolateOpen(d, all, "plant", 1)), ["Other plant", "Plant", "Line A", "Line B"]);
  assert.deepEqual(shown(d, isolateOpen(d, all, "plant", 2)), ["Other plant", "Plant", "Line A", "Pump A", "Line B", "Pump B"]);
  // Exactly the way up and the branch to that depth are open.
  assert.deepEqual([...isolateOpen(d, all, "pumpB", 1)].sort(), ["lineB", "plant", "pumpB"]);
  // A row with nothing inside: only the way up.
  assert.deepEqual([...isolateOpen(d, all, "sealA", 2)].sort(), ["lineA", "plant", "pumpA"]);
  // Not a row: what was open, as it was.
  assert.deepEqual([...isolateOpen(d, new Set(["plant"]), "nope", 2)], ["plant"]);
});

test("isolate in a pinned branch: rows outside it keep what they had", () => {
  const whole = buildDisplay(DATA, "positions");
  const d = pinDisplay(whole, "plant");
  const next = isolateOpen(d, new Set(["other", "lineB", "pumpB"]), "lineA", 1);
  assert.deepEqual([...next].sort(), ["lineA", "other", "plant"]);
});

test("isolate on the RCM tab: a function and the rows inside it", () => {
  const rcm = {
    positions: [
      { id: "pumpA", functions: [{ id: "fnA", text: "Pump water", failures: [{ id: "ffA", text: "No flow", modes: [{ id: "mA", text: "Seal leaks" }] }] }] },
      { id: "pumpB", functions: [{ id: "fnB", text: "Pump oil", failures: [] }] },
    ],
  };
  const d = graftRcm(buildDisplay(DATA, "positions"), rcm);
  const all = everything(d);
  const one = isolateOpen(d, all, "fnA", 1);
  assert.ok(one.has("fnA") && one.has("pumpA") && one.has("lineA") && one.has("plant"));
  assert.ok(!one.has("ffA") && !one.has("pumpB") && !one.has("lineB"));
  assert.ok(isolateOpen(d, all, "fnA", 2).has("ffA"));
  // What can be isolated: the tree's rows and the RCM's, not a heading.
  assert.equal(canIsolate(d.rows.get("fnA"), "positions", canPin), true);
  assert.equal(canIsolate(d.rows.get("mA"), "positions", canPin), true);
  assert.equal(canIsolate(d.rows.get("lineA"), "positions", canPin), true);
  assert.equal(canIsolate({ type: "cause", kids: [] }, "positions", canPin), false);
  assert.equal(canIsolate({ type: "unassigned", kids: ["x"] }, "positions", canPin), false); // a heading: no menu
  assert.equal(canIsolate(null, "positions", canPin), false);
});

test("the words said", () => {
  assert.deepEqual([1, 2, 3, "all"].map(depthWords), ["1 level", "2 levels", "3 levels", "every level"]);
});

import { incompleteRows, isolateIncompleteOpen, isolateIncompleteItem } from "./treeIsolate.js";
import { flatten as flat2 } from "./assetTree.js";

test("isolate incomplete rows: the way to what's unfinished opens, the rest closes", () => {
  const rcm = { positions: [
    { id: "pumpA", functions: [
      { id: "f1", text: "Pump water", failures: [{ id: "ff1", text: "No flow", modes: [{ id: "m1", name: "Seal leaks", decision: { task: "x" } }] }], modes: [] },
      { id: "f2", text: "Contain water", failures: [], modes: [] },
    ], unassigned: [] },
    { id: "pumpB", functions: [
      { id: "f3", text: "Pump water", failures: [{ id: "ff3", text: "No flow", modes: [{ id: "m3", name: "Shaft breaks" }] }], modes: [] },
    ], unassigned: [] },
  ] };
  const d = graftRcm(buildDisplay(DATA, "positions"), rcm);
  const found = incompleteRows(d, "plant").map((r) => r.key);
  assert.deepEqual(found, ["f2", "m3"]);
  const all = new Set([...d.rows.values()].filter((r) => r.kids.length).map((r) => r.key));
  const { open } = isolateIncompleteOpen(d, all, "plant");
  assert.ok(open.has("pumpA") && open.has("pumpB") && open.has("f3") && open.has("ff3"));
  assert.ok(!open.has("f1") && !open.has("ff1"));
  assert.deepEqual(incompleteRows(d, "pumpA").map((r) => r.key), ["f2"]);
  assert.deepEqual(isolateIncompleteItem(d.rows.get("plant"), { can: true }), [{ id: "isolate-incomplete", label: "Focus on incomplete rows" }]);
  assert.deepEqual(isolateIncompleteItem(d.rows.get("m3"), { can: true }), []);
});

// ---- Focus here in a tab's tree-table, and Clear focus ---------------------------
import { focusFrom, focusShown } from "./treeIsolate.js";
import { filterTasks, graftTasks, taskKey } from "./explorerTasks.js";

const tasks = [
  { id: "t1", name: "Grease the pump", subject: { id: "pumpA" }, interval: 3, unit: "months", trade: "Fitter" },
  { id: "t2", name: "Check the seal", subject: { id: "sealA" }, interval: 1, unit: "months", trade: "Fitter" },
  { id: "t3", name: "Walk the line", subject: { id: "lineB" }, interval: 1, unit: "weeks", trade: "Operator" },
  { id: "t4", name: "Inspect the seal", subject: { id: "sealB" }, interval: 6, unit: "months", trade: "Fitter" },
];
const names = (d, open) => flatten(d, open).list.map((v) => d.rows.get(v.key).ref.name);

test("Focus here on the Maintenance tab: a mid-level position's every task shows, every other branch closed", () => {
  const d = graftTasks(buildDisplay(DATA, "positions"), tasks);
  const all = everything(d);
  // Line A at every level: its pump's and its seal's tasks; line B closed (its task hidden in it), the other plant closed.
  assert.deepEqual(names(d, isolateOpen(d, all, "lineA", "all")),
    ["Other plant", "Plant", "Line A", "Pump A", "Grease the pump", "Seal A", "Check the seal", "Line B"]);
  // 1 level: the pump only, closed (so its task and the seal stay in it).
  assert.deepEqual(names(d, isolateOpen(d, all, "lineA", 1)), ["Other plant", "Plant", "Line A", "Pump A", "Line B"]);
});

test("Focus here and the column filters: the filter applies inside what the focus opened", () => {
  const filtered = filterTasks(tasks, { trade: ["Operator"] });
  const d = graftTasks(buildDisplay(DATA, "positions"), filtered, { prune: true });
  // Line A has no Operator task: focused, nothing of its tasks shows. Line B's one task does.
  const a = names(d, isolateOpen(d, new Set(), "lineA", "all"));
  assert.ok(!a.includes("Grease the pump") && !a.includes("Check the seal"));
  const open = isolateOpen(d, new Set(), "lineB", "all");
  assert.ok(names(d, open).includes("Walk the line"));
  assert.ok(!names(d, open).includes("Inspect the seal"));
});

test("the other tree-tables' rows with something inside them can be focused; their leaves can't", () => {
  const pin = (r) => canPin(r);
  assert.equal(canIsolate({ type: "mission", kids: ["ph"] }, "positions", pin), true);
  assert.equal(canIsolate({ type: "phase", kids: ["c"] }, "positions", pin), true);
  assert.equal(canIsolate({ type: "phase", kids: [] }, "positions", pin), false);
  assert.equal(canIsolate({ type: "pmodel", kids: ["s"] }, "positions", pin), true);
  assert.equal(canIsolate({ type: "mtask", kids: [] }, "positions", pin), false);
  assert.equal(canIsolate({ type: "meas", kids: [] }, "positions", pin), false);
});

test("Clear focus goes back to what was open before the first focus; a focus off the tree isn't shown", () => {
  const d = buildDisplay(DATA, "positions");
  const before = new Set(["plant", "lineB"]);
  const f1 = focusFrom(null, "lineA", "Line A", before);
  assert.deepEqual(f1, { key: "lineA", name: "Line A", before });
  assert.notEqual(f1.before, before); // a copy: later changes to what's open don't touch it
  // Focusing again moves the focus; Clear focus still goes back to the start.
  const f2 = focusFrom(f1, "pumpB", "Pump B", isolateOpen(d, before, "lineA", "all"));
  assert.equal(f2.key, "pumpB");
  assert.deepEqual([...f2.before].sort(), ["lineB", "plant"]);
  assert.equal(focusShown(f2, d), f2);
  assert.equal(focusShown(f2, pinDisplay(d, "lineA")), null); // outside a pinned branch
  assert.equal(focusShown(null, d), null);
});
