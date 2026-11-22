import test from "node:test";
import assert from "node:assert/strict";
import { allInstant, chainPairs, clearSpot, setInstantRepair, trackSelection } from "./rbdBuilderOps.js";

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

test("clearSpot: a block added unwired never lands on top of another", () => {
  const nodes = [
    { id: "c1", position: { x: 0, y: 0 }, width: 171, height: 95 },
    { id: "c2", position: { x: 0, y: 119 }, width: 171, height: 95 },
  ];
  // Free: kept.
  assert.deepEqual(clearSpot(nodes, { x: 400, y: 0 }), { x: 400, y: 0 });
  // On c1 (and c2 below it): moved down past both.
  const p = clearSpot(nodes, { x: 20, y: 10 });
  assert.equal(p.x, 20);
  assert.ok(p.y >= 119 + 95, `landed at ${p.y}`);
  // Unmeasured nodes use a block's drawn size; no position asked, none given.
  assert.notDeepEqual(clearSpot([{ id: "c1", position: { x: 0, y: 0 } }], { x: 0, y: 0 }), { x: 0, y: 0 });
  assert.equal(clearSpot(nodes, undefined), undefined);
});

test("addParallelPair: on an empty diagram, two blocks side by side from Input to Output through a junction", async () => {
  const { addParallelPair } = await import("./rbdBuilderOps.js");
  const nodes = [{ id: "in", type: "input", position: { x: 0, y: 0 } }, { id: "out", type: "output", position: { x: 600, y: 0 } }];
  const a = { id: "c1", type: "component", data: { label: "Pump A" }, position: { x: 0, y: 0 } };
  const b = { id: "c2", type: "component", data: { label: "Pump B" }, position: { x: 0, y: 0 } };
  const out = addParallelPair({ nodes, edges: [] }, a, b, { junctionId: "k9" });
  assert.equal(out.wired, true);
  const pairs = out.edges.map((e) => `${e.source}>${e.target}`).sort();
  assert.deepEqual(pairs, ["c1>k9", "c2>k9", "in>c1", "in>c2", "k9>out"]);
  assert.deepEqual(out.nodes.find((n) => n.id === "k9").data, { n: 1, k: 2 });
});

test("addParallelPair: with no place to wire them, the pair and its junction land unwired upstream", async () => {
  const { addParallelPair } = await import("./rbdBuilderOps.js");
  const nodes = [{ id: "in", type: "input", position: { x: 0, y: 0 } }, { id: "out", type: "output", position: { x: 900, y: 0 } },
    { id: "x", type: "component", data: {}, position: { x: 300, y: 0 } }];
  const edges = [{ id: "e1", source: "in", target: "x" }, { id: "e2", source: "x", target: "out" }];
  const a = { id: "c1", type: "component", data: {}, position: { x: 0, y: 0 } };
  const b = { id: "c2", type: "component", data: {}, position: { x: 0, y: 0 } };
  const out = addParallelPair({ nodes, edges }, a, b, { junctionId: "k9", pos: { x: 300, y: 300 } });
  assert.equal(out.wired, false);
  assert.deepEqual(out.edges.filter((e) => e.target === "k9").map((e) => e.source).sort(), ["c1", "c2"]);
});
