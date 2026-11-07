import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addChild, addRepeat, emptyTree, eventSummary, gateSummary, indentRow, moveRow, newId, outdentRow, outlineRows,
  removeRow, rename, setEventData, setGate, treeIssues,
} from "./faultTree.js";

const build = () => {
  let t = emptyTree("Loss of flow");
  let r = addChild(t, "top", "gate", "and");
  t = r.tree;
  const g = r.id;
  r = addChild(t, g, "event");
  t = r.tree;
  const a = r.id;
  r = addChild(t, g, "event");
  t = r.tree;
  const b = r.id;
  r = addChild(t, "top", "event");
  return { t: r.tree, g, a, b, c: r.id };
};

test("adding gates and events builds the outline top first, depth first", () => {
  const { t, g, a, b, c } = build();
  const rows = outlineRows(t);
  assert.deepEqual(rows.map((x) => [x.id, x.depth]), [["top", 0], [g, 1], [a, 2], [b, 2], [c, 1]]);
  assert.equal(rows[1].node.gate, "and");
  assert.equal(newId(t, "e"), "e4");
});

test("an unfinished tree says what it still needs", () => {
  const { t, a, b, c } = build();
  assert.equal(treeIssues(t).length, 3);
  let done = setEventData(t, a, { probability: 0.1 });
  done = setEventData(done, b, { model: { distribution_id: "exponential", params: [{ name: "failure_rate", value: 1e-3 }] } });
  done = setEventData(done, c, { probability: 0.2, placeholder: true });
  assert.deepEqual(treeIssues(done), []);
  assert.equal(done.nodes.find((n) => n.id === c).placeholder, true);
  const empty = addChild(done, "top", "gate").tree;
  assert.match(treeIssues(empty)[0].text, /add its inputs/);
});

test("a vote gate keeps k and flags k above its inputs", () => {
  const { t, g } = build();
  const v = setGate(t, g, "vote", 3);
  assert.equal(v.nodes.find((n) => n.id === g).k, 3);
  assert.match(treeIssues(v).find((i) => i.id === g).text, /needs 3 of its inputs but has 2/);
  assert.equal(setGate(v, g, "or").nodes.find((n) => n.id === g).k, undefined);
  assert.equal(gateSummary(setGate(v, g, "vote", 2).nodes.find((n) => n.id === g)), "Vote · 2 of 2");
});

test("delete removes the branch, and only what nothing else uses", () => {
  const { t, g, a } = build();
  const rows = outlineRows(t);
  const gone = removeRow(t, rows[1]);
  assert.deepEqual(gone.nodes.map((n) => n.id).sort(), ["e3", "top"]);
  // A repeated event stays while another gate still uses it.
  const rep = addRepeat(t, "top", a);
  const repRows = outlineRows(rep);
  assert.equal(repRows.filter((r) => r.id === a).length, 2);
  assert.ok(repRows.find((r) => r.id === a).repeated);
  const after = removeRow(rep, repRows.find((r) => r.id === g));
  assert.ok(after.nodes.some((n) => n.id === a));
  assert.equal(removeRow(t, rows[0]), t); // the top stays
});

test("move up, down, into the gate above and back out", () => {
  const { t, g, c } = build();
  let rows = outlineRows(t);
  const cRow = rows.find((r) => r.id === c);
  const up = moveRow(t, cRow, -1);
  assert.deepEqual(up.nodes.find((n) => n.id === "top").inputs, [c, g]);
  const into = indentRow(t, cRow);
  assert.deepEqual(into.nodes.find((n) => n.id === g).inputs.slice(-1), [c]);
  rows = outlineRows(into);
  const out = outdentRow(into, rows, rows.find((r) => r.id === c));
  assert.deepEqual(out.nodes.find((n) => n.id === "top").inputs, [g, c]);
  assert.equal(indentRow(t, rows[1]), null); // first child: nothing above to go into
});

test("rename and the one-line summaries", () => {
  const { t, a } = build();
  assert.equal(rename(t, a, "Pump A fails").nodes.find((n) => n.id === a).label, "Pump A fails");
  assert.equal(eventSummary({ probability: 0.01 }), "q = 0.01");
  assert.equal(eventSummary({ model: { distribution_id: "exponential", params: [{ name: "failure_rate", value: 2e-5 }] } }, "Hours"),
    "λ = 2e-5 /hour");
  assert.equal(eventSummary({ model: { source: "saved", modelId: "m1", name: "Pump fit" } }), "Saved model: Pump fit");
  assert.equal(eventSummary({}), "No failure data");
});
