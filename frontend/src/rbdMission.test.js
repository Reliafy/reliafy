// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cleanPhases, missionFields, networkGap, phaseBlocks, reliabilityPercent, terminals, topBlocks,
  undirectedEdges, voteNodes,
} from "./rbdMission.js";

const io = [{ id: "input", type: "input", data: { label: "Input" } }, { id: "output", type: "output", data: { label: "Output" } }];
const nodes = [
  ...io,
  { id: "c1", type: "component", data: { label: "Engine 1" } },
  { id: "c2", type: "component", data: { label: "Engine 2" } },
  { id: "c3", type: "component", data: { label: "Engine 1 again", repeat_of: "c1" } },
  { id: "k1", type: "knode", data: { n: 1, k: 2 } },
];
const edges = [
  { source: "input", target: "c1" }, { source: "input", target: "c2" },
  { source: "c1", target: "k1" }, { source: "c2", target: "k1" }, { source: "k1", target: "output" },
];

test("the mission keys ride with the graph only when set", () => {
  assert.deepEqual(missionFields({ phases: [], network: null }), {});
  assert.deepEqual(missionFields({ phases: [{ name: "A", duration: 1 }], network: { source: "a" } }),
    { phases: [{ name: "A", duration: 1 }], network: { source: "a" } });
  assert.deepEqual(terminals({ network: {} }), { source: "input", target: "output" });
});

test("a network's links lose their arrows", () => {
  const [e] = undirectedEdges([{ id: "e", source: "a", target: "b", markerEnd: { type: "arrowclosed" } }]);
  assert.equal(e.markerEnd, undefined);
  assert.match(e.className, /rbd-link/);
});

test("a network is connected either way round", () => {
  const graph = { nodes, edges: [{ source: "c1", target: "input" }, { source: "output", target: "c1" }] };
  assert.equal(networkGap(graph), null);
  assert.equal(networkGap({ nodes, edges: [{ source: "input", target: "c1" }] }), "not_connected");
  assert.equal(networkGap({ nodes: io, edges: [] }), "no_blocks");
});

test("a phase chooses among blocks (no vote nodes or copies) and vote nodes", () => {
  assert.deepEqual(phaseBlocks(nodes).map((b) => b.id), ["c1", "c2"]);
  assert.deepEqual(voteNodes(nodes, edges), [{ id: "k1", label: "Vote node", n: 1, inputs: 2 }]);
});

test("phases are cleaned and checked in plain words", () => {
  const { phases, errors } = cleanPhases([
    { name: " Take-off ", duration: "0.2", not_needed: ["c2", "gone", "c2"], votes: { k1: "2", c1: "3" } },
    { name: "Cruise", duration: 5, votes: { k1: "" } },
  ], nodes);
  assert.deepEqual(errors, []);
  assert.deepEqual(phases, [
    { name: "Take-off", duration: 0.2, not_needed: ["c2"], votes: { k1: 2 } },
    { name: "Cruise", duration: 5 },
  ]);
  const bad = cleanPhases([{ name: "", duration: "" }, { name: "A", duration: -1 }, { name: "a", duration: 1, votes: { k1: "0" } }], nodes);
  assert.equal(bad.errors.length, 5);
});

test("a reliability near 1 never rounds to 100%", () => {
  assert.equal(reliabilityPercent(0.8969), "89.7%");
  assert.equal(reliabilityPercent(0.98), "98.0%");
  assert.equal(reliabilityPercent(0.99956), "99.956%");
  assert.equal(reliabilityPercent(1), "100%");
  assert.equal(reliabilityPercent(null), "—");
});

test("ties for the most important block are all named", () => {
  assert.deepEqual(topBlocks([{ label: "C", birnbaum: 0.3 }, { label: "D", birnbaum: 0.3 }, { label: "A", birnbaum: 0.1 }])
    .map((r) => r.label), ["C", "D"]);
  assert.deepEqual(topBlocks([{ label: "C", birnbaum: 0 }]), []);
});
