import test from "node:test";
import assert from "node:assert/strict";
import { allInstant, chainPairs, setInstantRepair, trackSelection } from "./rbdBuilderOps.js";

test("trackSelection: clicks keep their order; a box select has none", () => {
  let s = trackSelection(undefined, ["c3"]);
  s = trackSelection(s, ["c3", "c1"]);
  s = trackSelection(s, ["c3", "c1", "c2"]);
  assert.deepEqual(s, { ids: ["c3", "c1", "c2"], ordered: true });
  // Deselecting one keeps the rest in order.
  assert.deepEqual(trackSelection(s, ["c3", "c2"]), { ids: ["c3", "c2"], ordered: true });
  // Several at once: no click order until cleared.
  const box = trackSelection(s, ["c3", "c1", "c2", "c4", "c5"]);
  assert.equal(box.ordered, false);
  assert.equal(trackSelection(box, ["c3", "c1", "c2", "c4", "c5", "c6"]).ordered, false);
  assert.deepEqual(trackSelection(box, []), { ids: [], ordered: true });
});

test("chainPairs: a series chain in the order clicked", () => {
  assert.deepEqual(chainPairs(["a", "b", "c"]), [["a", "b"], ["b", "c"]]);
  assert.deepEqual(chainPairs(["a"]), []);
});

test("instant repair for the whole diagram", () => {
  const nodes = [
    { id: "input", type: "input", data: {} },
    { id: "c1", type: "component", data: { label: "A", repair: { x: 1 } } },
    { id: "c2", type: "component", data: { label: "B", instant_repair: true } },
    { id: "c3", type: "component", data: { repeat_of: "c1" } },
    { id: "sb", type: "standby", data: { label: "S" } },
  ];
  assert.equal(allInstant(nodes), false);
  const on = setInstantRepair(nodes, true);
  assert.equal(allInstant(on), true);
  assert.equal(on[1].data.instant_repair, true);
  assert.deepEqual(on[1].data.repair, { x: 1 }, "the repair model is kept for when it's turned off");
  assert.equal(on[3].data.instant_repair, undefined, "a repeat follows its original");
  assert.equal(on[4].data.instant_repair, undefined, "standby groups have their own repairs");
  const off = setInstantRepair(on, false);
  assert.equal(off[2].data.instant_repair, undefined);
  assert.equal(allInstant([{ id: "input", type: "input" }]), false);
});
