import { test } from "node:test";
import assert from "node:assert/strict";
import { rcmRootLine, rcmTreeRoots } from "./rcmTreeRoots.js";

test("the tree's RCM is grouped by the topmost position with RCM", () => {
  const data = {
    positions: [
      { id: "st", name: "Station", functions: [{ modes: [], failures: [{ modes: [{ id: "a", decision: { outcome: "rtf" } }] }] }] },
      { id: "p1", name: "Pump 1", functions: [{ modes: [{ id: "b" }], failures: [] }], unassigned: [{ id: "c", decision: {} }] },
      { id: "fan", name: "Fan", functions: [] },
    ],
    parents: { st: "site", p1: "set1", set1: "st", site: null, fan: null },
  };
  const roots = rcmTreeRoots(data);
  assert.deepEqual(roots.map((r) => [r.id, r.positions, r.modes, r.decided]), [["fan", 1, 0, 0], ["st", 2, 3, 2]]);
  assert.equal(rcmRootLine(roots[1]), "2 positions · 2 of 3 failure modes decided");
  assert.equal(rcmRootLine(roots[0]), "1 position · no failure modes yet");
  assert.deepEqual(rcmTreeRoots(null), []);
});
