import { test } from "node:test";
import assert from "node:assert/strict";
import { positionOptions } from "./positionPicker.js";
import { filterOptions } from "./selectSearch.js";

const positions = [
  { id: "s", name: "Pump station", depth: 0, tag: "", path: [] },
  { id: "p1", name: "Filter pump", depth: 1, tag: "P-101", path: ["Pump station"] },
  { id: "p2", name: "Pump 1", depth: 1, tag: "", path: ["Pump station"] },
  { id: "q", name: "Pump 1", depth: 1, tag: "", path: ["Riverside"] },
];

test("each position by name and tag, with the way down to it as its hint", () => {
  const opts = positionOptions(positions, "Choose a position…");
  assert.deepEqual(opts[0], { value: "", label: "Choose a position…" });
  assert.deepEqual(opts[1], { value: "s", label: "Pump station" });
  assert.deepEqual(opts[2], { value: "p1", label: "P-101 · Filter pump", hint: "Pump station" });
  assert.equal(positionOptions(positions, null).length, 4);
  assert.deepEqual(positionOptions(null), []);
  // An old flatten row (no tag, no path) still works.
  assert.deepEqual(positionOptions([{ id: "x", name: "X", depth: 0 }]), [{ value: "x", label: "X" }]);
});

test("typing finds a position by its tag, its name or the system it's in", () => {
  const opts = positionOptions(positions, "Choose…").map((o) => ({ ...o }));
  const ids = (q) => filterOptions(opts, q).map((o) => o.value);
  assert.deepEqual(ids("p-101"), ["p1"]);
  assert.deepEqual(ids("pump 1 riverside"), ["q"]);
  assert.deepEqual(ids("filter"), ["p1"]);
});
