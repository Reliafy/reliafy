import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyTreePlan, mergeTreeData, setTreeSetting, treeBlockPlan, treeGraph, treeKey, treeRowProblems, treeTaskPath,
} from "./rbdTreePlan.js";

const row = (plan, extra = {}) => ({ position: { id: "p1", name: "Pump A" }, used: plan ? "t1" : null, plan, ...extra });
const AGE = { task: "age", interval: 4383, operating_interval: null, duration: 8, cost: 1200, inspection_cost: null, group: null };

test("the task replaces whatever was drawn; the diagram keeps only its own settings", () => {
  const data = { label: "Pump A", duty: 0.5, crew_priority: 2, preventive: { policy: "block", interval: 1, cost: 5 },
    tree_settings: { opportunity: 2000, threshold: 0.1 } };
  const out = mergeTreeData(data, row(AGE));
  assert.deepEqual(out.preventive, { policy: "age", interval: 4383, duration: 8, cost: 1200, opportunity: 2000 });
  assert.equal(out.duty, 0.5);
  assert.equal(out.crew_priority, 2);
  assert.equal(out.tree_settings, undefined);
  assert.deepEqual(out.tree_plan, { position_id: "p1", task_id: "t1" });
});

test("no tasks on the position: it runs to failure", () => {
  const out = mergeTreeData({ label: "B", preventive: { policy: "age", interval: 9 } }, row(null));
  assert.equal(out.preventive, undefined);
  assert.equal(out.inspection, undefined);
});

test("a proof test leaves any group; on condition takes the RBD's replacement figures", () => {
  const test_ = mergeTreeData({ maintenance_group: "g", tree_settings: { offset: 10 } },
    row({ ...AGE, task: "test", interval: 8766, duration: 2, cost: 300 }));
  assert.deepEqual(test_.inspection, { interval: 8766, duration: 2, cost: 300, offset: 10 });
  assert.equal(test_.maintenance_group, undefined);
  const cond = mergeTreeData({ tree_settings: { threshold: 0.05, cost: 900, duration: 4, offset: 3 } },
    row({ ...AGE, task: "condition", interval: 730.5, duration: null, cost: null, inspection_cost: 40, group: "Shut" }));
  assert.deepEqual(cond.preventive, { policy: "condition", interval: 730.5, inspection_cost: 40, threshold: 0.05, cost: 900, duration: 4 });
  assert.equal(cond.maintenance_group, "Shut");
});

test("applyTreePlan touches only tree-linked blocks", () => {
  const nodes = [{ id: "a", type: "component", data: { label: "A" } }, { id: "b", type: "component", data: { label: "B", preventive: { policy: "age", interval: 3 } } }];
  const out = applyTreePlan(nodes, { blocks: { a: row(AGE) } });
  assert.equal(out[0].data.preventive.interval, 4383);
  assert.equal(out[1], nodes[1]);
  assert.equal(applyTreePlan(nodes, null), nodes);
});

test("settings and what's left to set", () => {
  let d = setTreeSetting({}, "threshold", 0.05);
  assert.deepEqual(d.tree_settings, { threshold: 0.05 });
  d = setTreeSetting(d, "threshold", null);
  assert.equal(d.tree_settings, undefined);
  const cond = row({ ...AGE, task: "condition" });
  assert.match(treeRowProblems({}, cond)[0], /threshold/);
  assert.deepEqual(treeRowProblems({ tree_settings: { threshold: 0.1 } }, cond), []);
  const running = row({ ...AGE, interval: null, operating_interval: 500 });
  assert.match(treeRowProblems({}, running)[0], /duty/);
  assert.deepEqual(treeRowProblems({ duty: 0.25 }, running), []);
});

test("links to the tree and the request's blocks", () => {
  assert.equal(treeTaskPath("p 1", { taskId: "t1" }), "/asset-register/explorer?arrange=positions&sel=p+1&tab=maintenance&mtask=t1");
  assert.match(treeTaskPath("p1", { add: true }), /addtask=p1/);
  const nodes = [{ id: "in", type: "input" }, { id: "a", type: "component", data: { label: "A", repair: { distribution_id: "x" }, preventive: {} } }];
  assert.deepEqual(treeGraph(nodes, "Hours"), { unit: "Hours", nodes: [{ id: "a", type: "component", data: { label: "A", repair: true } }] });
  // Editing a plan field doesn't change the key (no refetch); a label does.
  const edited = [nodes[0], { ...nodes[1], data: { ...nodes[1].data, duty: 0.5 } }];
  assert.equal(treeKey(edited, "Hours"), treeKey(nodes, "Hours"));
  assert.notEqual(treeKey([nodes[0], { ...nodes[1], data: { label: "B" } }], "Hours"), treeKey(nodes, "Hours"));
});

test("the block dialog shows the tree's task, as the plan and the Calculator use it", () => {
  // The diagram's own (stale) plan says nothing is planned; the position has an age replacement.
  const data = { label: "Pump A", preventive: undefined };
  const tree = row(AGE, { tasks: [{ id: "t1", name: "Replace the seal", used: true }] });
  const words = treeBlockPlan(data, tree, "hours");
  assert.doesNotMatch(words.summary, /Run to failure/);
  assert.match(words.summary, /^Replace on age every 4,383/);
  assert.equal(words.source, "From the tree: “Replace the seal” on Pump A");
  assert.equal(words.editLabel, "Edit in the tree");
  assert.match(words.editPath, /tab=maintenance/);
  assert.match(words.editPath, /mtask=t1/);
  // No tasks at the position: it runs to failure, whatever the diagram had drawn.
  const none = treeBlockPlan({ preventive: { policy: "age", interval: 9 } }, row(null, { tasks: [] }), "hours");
  assert.equal(none.summary, "Run to failure");
  assert.equal(none.source, "From the tree: no maintenance tasks on Pump A");
  assert.equal(none.editLabel, "Add a task in the tree");
});
