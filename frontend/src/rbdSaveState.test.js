// Run with: node --test src/
// Whether an RBD has changes to save, as the Explorer's pane is told.
import { test } from "node:test";
import assert from "node:assert/strict";
import { rbdDirty, rbdSaveSnapshot } from "./rbdSaveState.js";

const io = [
  { id: "in", type: "input", position: { x: 0, y: 0 }, data: {} },
  { id: "out", type: "output", position: { x: 400, y: 0 }, data: {} },
];
const empty = { nodes: io, edges: [], unit: "", repairable: false };
const loaded = {
  nodes: [...io, { id: "p1", type: "component", position: { x: 200, y: 0 }, data: { label: "Pump A" } }],
  edges: [{ source: "in", target: "p1" }, { source: "p1", target: "out" }],
  unit: "Hours",
  repairable: false,
};

test("rbdDirty: the render after a diagram loads, before its snapshot is taken, is not a change", () => {
  // The bad input: the snapshot is still the empty canvas's, the graph the one just loaded.
  const stale = rbdSaveSnapshot(empty);
  assert.equal(rbdDirty({ graph: loaded, savedSnap: stale, rebasing: true }), false);
  // Once the snapshot is taken, the same diagram is unchanged, and an edit is a change.
  const snap = rbdSaveSnapshot(loaded);
  assert.equal(rbdDirty({ graph: loaded, savedSnap: snap }), false);
  const moved = { ...loaded, nodes: loaded.nodes.map((n) => (n.id === "p1" ? { ...n, position: { x: 260, y: 0 } } : n)) };
  assert.equal(rbdDirty({ graph: moved, savedSnap: snap }), true);
});

test("rbdDirty: untracked, or no snapshot yet, is never a change", () => {
  assert.equal(rbdDirty({ graph: loaded, savedSnap: null }), false);
  assert.equal(rbdDirty({ tracked: false, graph: loaded, savedSnap: rbdSaveSnapshot(empty) }), false);
});
