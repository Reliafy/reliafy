import { test } from "node:test";
import assert from "node:assert/strict";
import { rcmDecidedText, rcmRootLine, rcmTreeRoots } from "./rcmTreeRoots.js";

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

test("each row says where it is, so rows with one name tell apart", () => {
  const bearing = (id) => ({ id, name: "Bearing", functions: [], unassigned: [{ id: `m${id}`, decision: {} }] });
  const data = {
    positions: [bearing("b1"), bearing("b2")],
    parents: { b1: "p1", b2: "p2", p1: "st", p2: "st", st: null },
    names: { b1: "Bearing", b2: "Bearing", p1: "Pump 1", p2: "Pump 2", st: "Station" },
  };
  const roots = rcmTreeRoots(data);
  assert.deepEqual(roots.map((r) => [r.name, r.path]), [["Bearing", "Station › Pump 1"], ["Bearing", "Station › Pump 2"]]);
  assert.equal(rcmDecidedText(roots[0]), "1 of 1");
  assert.equal(rcmDecidedText({ modes: 0, decided: 0 }), "No failure modes yet");
  // An older reply with no names: the path is what's known, never a crash.
  assert.equal(rcmTreeRoots({ ...data, names: undefined })[0].path, "Unnamed position › Unnamed position");
});
