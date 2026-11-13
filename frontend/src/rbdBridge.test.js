import test from "node:test";
import assert from "node:assert/strict";
import { bridgeEdges } from "./rbdBuilderOps.js";

const e = (source, target) => ({ id: `e-${source}-${target}`, source, target, type: "smoothstep" });
const pairs = (edges) => edges.map((x) => `${x.source}>${x.target}`).sort();

test("deleting a block in a series line joins the line up again", () => {
  const edges = [e("input", "a"), e("a", "b"), e("b", "output")];
  const added = bridgeEdges(edges, ["a"]);
  assert.deepEqual(pairs(added), ["input>b"]);
  assert.equal(added[0].type, "smoothstep"); // keeps the line's look
});

test("two blocks in a row deleted together still leave one line", () => {
  const edges = [e("input", "a"), e("a", "b"), e("b", "c"), e("c", "output")];
  assert.deepEqual(pairs(bridgeEdges(edges, ["a", "b"])), ["input>c"]);
});

test("a block on a parallel branch isn't bridged (that would be a branch that never fails)", () => {
  const edges = [e("input", "a"), e("input", "b"), e("a", "j"), e("b", "j"), e("j", "output")];
  assert.deepEqual(bridgeEdges(edges, ["a"]), []);
});

test("a block with nothing on one side isn't bridged", () => {
  assert.deepEqual(bridgeEdges([e("input", "a")], ["a"]), []);
});

test("a block between In and a split leaves In feeding each branch", () => {
  const edges = [e("input", "plc"), e("plc", "a"), e("plc", "b"), e("a", "output"), e("b", "output")];
  assert.deepEqual(pairs(bridgeEdges(edges, ["plc"])), ["input>a", "input>b"]);
});

test("a block after a join leaves each branch feeding what it fed", () => {
  const edges = [e("input", "a"), e("input", "b"), e("a", "m"), e("b", "m"), e("m", "output")];
  assert.deepEqual(pairs(bridgeEdges(edges, ["m"])), ["a>output", "b>output"]);
});
