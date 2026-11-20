import { test } from "node:test";
import assert from "node:assert/strict";
import { nestRbds, rbdNames } from "./rbdList.js";

test("a sub-diagram and a mission's copy are listed under their diagram, not at the top", () => {
  const rows = [
    { id: "drone", name: "Drone RBD" },
    { id: "prop", name: "Propulsion", parent_id: "drone" },
    { id: "esc", name: "ESC pack", parent_id: "prop" },
    { id: "sortie", name: "Drone — Sortie", parent_id: "drone", mission: { name: "Sortie" } },
    { id: "pump", name: "Pump" },
  ];
  const out = nestRbds(rows);
  assert.deepEqual(out.map((r) => r.id), ["drone", "pump"]);
  assert.deepEqual(out[0].children.map((r) => [r.id, r.depth]), [["prop", 1], ["sortie", 1]]);
  assert.deepEqual(out[0].children[0].children.map((r) => [r.id, r.depth]), [["esc", 2]]);
  assert.deepEqual(rbdNames(out[0]), ["Drone RBD", "Propulsion", "ESC pack", "Drone — Sortie"]);
});

test("a parent not in the list, or a loop, leaves the rows at the top: none is lost", () => {
  const out = nestRbds([
    { id: "a", name: "A", parent_id: "gone" },
    { id: "b", name: "B", parent_id: "c" },
    { id: "c", name: "C", parent_id: "b" },
  ]);
  assert.deepEqual(out.map((r) => r.id).sort(), ["a", "b"]);
  const all = (r) => [r.id, ...r.children.flatMap(all)];
  assert.deepEqual(out.flatMap(all).sort(), ["a", "b", "c"]);
});
