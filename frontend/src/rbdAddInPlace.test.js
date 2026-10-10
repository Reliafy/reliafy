// Adding a block in place (#282): series after a block or on a connection,
// parallel alongside a block or a line of blocks. Run with: node --test src/
//
// The diagrams built here are also in backend/tests/fixtures/
// rbd_add_in_place.json, which the backend analyses and checks against
// RePyability (test_rbd_add_in_place.py). UPDATE_FIXTURES=1 rewrites it.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  STEP_X, STEP_Y, chainOf, downstreamOf, inPlaceItems, insertAfter, insertAlongside, insertOnEdge,
} from "./rbdBuilderOps.js";

const EXP = { source: "params", distribution: "Exponential", distribution_id: "exponential",
  params: [{ name: "failure_rate", value: 0.001 }] };
const io = () => [
  { id: "input", type: "input", data: { label: "Input" }, position: { x: 0, y: 0 } },
  { id: "output", type: "output", data: { label: "Output" }, position: { x: 4 * STEP_X, y: 0 } },
];
const block = (id, x, y = 0, extra = {}) =>
  ({ id, type: "component", data: { label: id, model: EXP }, position: { x, y }, ...extra });
const e = (source, target, extra = {}) => ({ id: `${source}-${target}`, source, target, type: "smoothstep", ...extra });
const pairs = (edges) => edges.map((x) => `${x.source}>${x.target}`).sort();
const N = () => ({ id: "n", type: "component", data: { label: "New", model: EXP }, position: { x: 0, y: 0 } });

// input → a → output
const single = () => ({ nodes: [...io(), block("a", STEP_X)], edges: [e("input", "a"), e("a", "output")] });

test("add after: the new block takes over what the block fed", () => {
  const g = { nodes: [...io(), block("a", STEP_X), block("b", 2 * STEP_X)],
    edges: [e("input", "a"), e("a", "b"), e("b", "output")] };
  const out = insertAfter(g, "a", N());
  assert.deepEqual(pairs(out.edges), ["a>n", "b>output", "input>a", "n>b"]);
  const byId = Object.fromEntries(out.nodes.map((x) => [x.id, x]));
  // A column to the right; b was in the way, so it and what follows move right.
  assert.deepEqual(byId.n.position, { x: 2 * STEP_X, y: 0 });
  assert.equal(byId.b.position.x, 3 * STEP_X);
  assert.equal(byId.output.position.x, 5 * STEP_X);
  // The new block is the selection, and the edges keep their look.
  assert.deepEqual(out.nodes.filter((x) => x.selected).map((x) => x.id), ["n"]);
  assert.ok(out.edges.every((x) => x.type === "smoothstep"));
});

test("add after: nothing moves when there's room", () => {
  const g = { nodes: [...io(), block("a", STEP_X)], edges: [e("input", "a"), e("a", "output")] };
  const out = insertAfter(g, "a", N());
  assert.equal(out.nodes.find((x) => x.id === "output").position.x, 4 * STEP_X);
  assert.deepEqual(pairs(out.edges), ["a>n", "input>a", "n>output"]);
});

test("insert on a line: the block splits the connection", () => {
  const g = single();
  const out = insertOnEdge(g, "a-output", N());
  assert.deepEqual(pairs(out.edges), ["a>n", "input>a", "n>output"]);
  // Room between a (x 280) and output (x 1120): the block goes half-way.
  assert.equal(out.nodes.find((x) => x.id === "n").position.x, 700);
  // A short line: the far end and what follows move right to make room.
  const tight = { nodes: [...io(), block("a", STEP_X), block("b", 2 * STEP_X)],
    edges: [e("input", "a"), e("a", "b"), e("b", "output")] };
  const split = insertOnEdge(tight, "a-b", N());
  assert.deepEqual(pairs(split.edges), ["a>n", "b>output", "input>a", "n>b"]);
  assert.equal(split.nodes.find((x) => x.id === "b").position.x, 3 * STEP_X);
  assert.equal(split.nodes.find((x) => x.id === "input").position.x, 0);
});

test("add alongside: a new junction merges the pair", () => {
  const out = insertAlongside(single(), ["a"], N(), { junctionId: "k9" });
  assert.deepEqual(pairs(out.edges), ["a>k9", "input>a", "input>n", "k9>output", "n>k9"]);
  const byId = Object.fromEntries(out.nodes.map((x) => [x.id, x]));
  assert.deepEqual(byId.k9.data, { n: 1, k: 2 });
  assert.equal(byId.k9.type, "knode");
  // Below the block.
  assert.deepEqual(byId.n.position, { x: STEP_X, y: STEP_Y });
  assert.ok(byId.k9.position.x > byId.a.position.x && byId.k9.position.x < byId.output.position.x);
});

test("add alongside: joins the junction already there", () => {
  const g = {
    nodes: [...io(), block("a", STEP_X), block("b", STEP_X, STEP_Y),
      { id: "j", type: "knode", data: { n: 1, k: 2 }, position: { x: 2 * STEP_X, y: 0 } }],
    edges: [e("input", "a"), e("input", "b"), e("a", "j"), e("b", "j"), e("j", "output")],
  };
  const out = insertAlongside(g, ["a"], N(), { junctionId: "unused" });
  assert.deepEqual(pairs(out.edges), ["a>j", "b>j", "input>a", "input>b", "input>n", "j>output", "n>j"]);
  assert.deepEqual(out.nodes.find((x) => x.id === "j").data, { n: 1, k: 3 });
  assert.ok(!out.nodes.some((x) => x.id === "unused"));
  // b is below a: the new block goes below that.
  assert.equal(out.nodes.find((x) => x.id === "n").position.y, 2 * STEP_Y);
});

test("add alongside a block feeding a vote: the pair is still one vote", () => {
  const out = insertAlongside(voting(), ["a"], N(), { junctionId: "k9" });
  assert.deepEqual(pairs(out.edges).filter((p) => p.includes("k9") || p.includes("n>") || p.endsWith(">n")),
    ["a>k9", "input>n", "k9>vote", "n>k9"]);
  assert.equal(out.edges.filter((x) => x.target === "vote").length, 3);
});

test("add alongside in a network: the same connections, no junction", () => {
  const out = insertAlongside(single(), ["a"], N(), { junctionId: "k9", junctions: false });
  assert.deepEqual(pairs(out.edges), ["a>output", "input>a", "input>n", "n>output"]);
  assert.ok(!out.nodes.some((x) => x.id === "k9"));
});

test("the chain check: one line in series, in order", () => {
  const g = line();
  assert.deepEqual(chainOf(g.nodes, g.edges, ["b", "a"]), { ok: true, order: ["a", "b"] });
  assert.equal(chainOf(g.nodes, g.edges, ["a", "output"]).ok, false);
  assert.equal(chainOf(g.nodes, g.edges, ["a"]).ok, false);
  // Not joined.
  const apart = { nodes: [...io(), block("a", STEP_X), block("b", STEP_X, STEP_Y)],
    edges: [e("input", "a"), e("input", "b"), e("a", "output"), e("b", "output")] };
  assert.match(chainOf(apart.nodes, apart.edges, ["a", "b"]).reason, /aren't one line/);
  // A branch leaves part-way.
  const branch = { nodes: [...g.nodes, block("c", 2 * STEP_X, STEP_Y)], edges: [...g.edges, e("a", "c"), e("c", "output")] };
  assert.equal(chainOf(branch.nodes, branch.edges, ["a", "b"]).ok, false);
  // A fork within the selection.
  const fork = { nodes: [...io(), block("a", STEP_X), block("b", 2 * STEP_X), block("c", 2 * STEP_X, STEP_Y)],
    edges: [e("input", "a"), e("a", "b"), e("a", "c"), e("b", "output"), e("c", "output")] };
  assert.equal(chainOf(fork.nodes, fork.edges, ["a", "b", "c"]).ok, false);
});

test("add alongside the selection: bypasses the whole line", () => {
  const out = insertAlongside(line(), ["a", "b"], N(), { junctionId: "k9" });
  assert.deepEqual(pairs(out.edges), ["a>b", "b>k9", "input>a", "input>n", "k9>output", "n>k9"]);
  const byId = Object.fromEntries(out.nodes.map((x) => [x.id, x]));
  // Below the line, centred under it.
  assert.deepEqual(byId.n.position, { x: 1.5 * STEP_X, y: STEP_Y });
});

test("the menu's in-place items for each selection", () => {
  const g = line();
  const sel = (ids) => g.nodes.map((x) => ({ ...x, selected: ids.includes(x.id) }));
  assert.equal(inPlaceItems(g.nodes, g.edges), null);
  const one = inPlaceItems(sel(["a"]), g.edges);
  assert.deepEqual(one.ids, ["a"]);
  assert.deepEqual(one.items.map((i) => [i.key, i.reason]), [["after", null], ["alongside", null]]);
  const ends = inPlaceItems(sel(["input"]), g.edges);
  assert.ok(ends.items.every((i) => /Input and Output/.test(i.reason)));
  const chain = inPlaceItems(sel(["b", "a"]), g.edges);
  assert.deepEqual([chain.ids, chain.items[0].key, chain.items[0].reason], [["a", "b"], "bypass", null]);
  const gate = { ...voting() };
  const vote = inPlaceItems(gate.nodes.map((x) => ({ ...x, selected: x.id === "vote" })), gate.edges);
  assert.equal(vote.items[0].reason, null);
  assert.match(vote.items[1].reason, /never fail/);
  const edge = inPlaceItems(g.nodes, g.edges.map((x) => ({ ...x, selected: x.id === "a-b" })));
  assert.deepEqual([edge.edge, edge.items.map((i) => i.key)], ["a-b", ["split"]]);
  const two = inPlaceItems(g.nodes, g.edges.map((x) => ({ ...x, selected: true })));
  assert.ok(two.items[0].reason);
});

test("downstream of a block", () => {
  const g = line();
  assert.deepEqual([...downstreamOf(g.edges, ["a"])].sort(), ["b", "output"]);
});

// input → a → b → output
function line() {
  return { nodes: [...io(), block("a", STEP_X), block("b", 2 * STEP_X)],
    edges: [e("input", "a"), e("a", "b"), e("b", "output")] };
}
// input → a, b, c → 2-of-3 → output
function voting() {
  return {
    nodes: [...io(), block("a", STEP_X), block("b", STEP_X, STEP_Y), block("c", STEP_X, 2 * STEP_Y),
      { id: "vote", type: "knode", data: { n: 2, k: 3 }, position: { x: 2 * STEP_X, y: STEP_Y } }],
    edges: ["a", "b", "c"].flatMap((x) => [e("input", x), e(x, "vote")]).concat([e("vote", "output")]),
  };
}

// The diagrams the backend analyses (structure and models; no layout).
test("the analysed diagrams match the backend's fixture", () => {
  const strip = (g) => ({
    unit: "hours",
    nodes: g.nodes.map(({ id, type, data }) => ({ id, type, data })).sort((x, y) => x.id.localeCompare(y.id)),
    edges: g.edges.map(({ id, source, target }) => ({ id, source, target })).sort((x, y) => x.id.localeCompare(y.id)),
  });
  const joined = {
    nodes: [...io(), block("a", STEP_X), block("b", STEP_X, STEP_Y),
      { id: "j", type: "knode", data: { n: 1, k: 2 }, position: { x: 2 * STEP_X, y: 0 } }],
    edges: [e("input", "a"), e("input", "b"), e("a", "j"), e("b", "j"), e("j", "output")],
  };
  const built = {
    after: strip(insertAfter(single(), "a", N())),
    split: strip(insertOnEdge(single(), "a-output", N())),
    alongside: strip(insertAlongside(single(), ["a"], N(), { junctionId: "k9" })),
    alongside_joined: strip(insertAlongside(joined, ["a"], N(), { junctionId: "k9" })),
    alongside_vote: strip(insertAlongside(voting(), ["a"], N(), { junctionId: "k9" })),
    bypass: strip(insertAlongside(line(), ["a", "b"], N(), { junctionId: "k9" })),
  };
  const path = fileURLToPath(new URL("../../backend/tests/fixtures/rbd_add_in_place.json", import.meta.url));
  if (process.env.UPDATE_FIXTURES) writeFileSync(path, JSON.stringify(built, null, 2) + "\n");
  assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), built);
});
