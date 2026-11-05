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
  // What can be isolated: the tree's rows and the RCM's, not a heading, not in Flat.
  assert.equal(canIsolate(d.rows.get("fnA"), "positions", canPin), true);
  assert.equal(canIsolate(d.rows.get("mA"), "positions", canPin), true);
  assert.equal(canIsolate(d.rows.get("lineA"), "positions", canPin), true);
  assert.equal(canIsolate({ type: "cause", kids: [] }, "positions", canPin), false);
  assert.equal(canIsolate({ type: "unassigned", kids: ["x"] }, "positions", canPin), false); // a heading: no menu
  assert.equal(canIsolate(buildDisplay(DATA, "flat").rows.get("lineA"), "flat", canPin), false);
  assert.equal(canIsolate(null, "positions", canPin), false);
});

test("the words said", () => {
  assert.deepEqual([1, 2, 3, "all"].map(depthWords), ["1 level", "2 levels", "3 levels", "every level"]);
});
