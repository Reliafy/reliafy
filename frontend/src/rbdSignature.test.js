// Run with: node --test src/
// When a check or a calculation no longer describes the diagram on screen.
import { test } from "node:test";
import assert from "node:assert/strict";
import { graphSignature, resultIsStale } from "./rbdSignature.js";

const block = (id, rate, x = 0) => ({
  id, type: "component", position: { x, y: 0 },
  data: { label: id, model: { distribution_id: "exponential", params: [{ name: "failure_rate", value: rate }] } },
});
const diagram = (rateB, extra = {}) => ({
  nodes: [block("a", 1e-6), block("b", rateB)],
  edges: [{ source: "a", target: "b" }],
  unit: "Hours",
  repairable: true,
  ccf_groups: [{ id: "g", members: ["a", "b"], beta: 0.1 }],
  ...extra,
});

test("moving a block isn't a change; a parameter in its last digit is", () => {
  const g = diagram(1e-6);
  const moved = { ...g, nodes: [block("a", 1e-6, 300), block("b", 1e-6, 500)] };
  assert.equal(graphSignature(moved), graphSignature(g));
  assert.notEqual(graphSignature(diagram(1.0000000000000004e-6)), graphSignature(g));
});

test("the common-cause groups and repairable are part of the diagram", () => {
  const g = diagram(1e-6);
  assert.notEqual(graphSignature({ ...g, ccf_groups: [] }), graphSignature(g));
  assert.notEqual(graphSignature({ ...g, ccf_groups: [{ ...g.ccf_groups[0], beta: 0.05 }] }), graphSignature(g));
  assert.notEqual(graphSignature({ ...g, repairable: false }), graphSignature(g));
  // No groups and an empty list are the same diagram.
  assert.equal(graphSignature({ ...g, ccf_groups: [] }), graphSignature({ ...g, ccf_groups: undefined }));
});

test("a result for an earlier diagram is stale even once the new one passes its check", () => {
  const before = graphSignature(diagram(1e-6));
  const after = graphSignature(diagram(1.0000000000000004e-6));
  const result = { kind: "repairable" };
  // Changed and not yet checked.
  assert.equal(resultIsStale({ result, resultSig: before, graphSig: after, checkStale: true }), true);
  // Checked again ("Valid"), but not calculated: still stale (the bug: it showed as current).
  assert.equal(resultIsStale({ result, resultSig: before, graphSig: after, checkStale: false }), true);
  // Calculated for this diagram: current.
  assert.equal(resultIsStale({ result, resultSig: after, graphSig: after, checkStale: false }), false);
  // No result: nothing to be stale.
  assert.equal(resultIsStale({ result: null, resultSig: before, graphSig: after }), false);
});
