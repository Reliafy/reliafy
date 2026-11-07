import { test } from "node:test";
import assert from "node:assert/strict";
import {
  caption, combine, connectionsOf, designModel, liveModel, liveProblem, nodeSize, PALETTE, searchModel, stateText,
  tableRows, toArrows, WARN,
} from "./dataModel.js";

// Invented labels: a tiny made-up graph and design.
const SCHEMA = {
  nodes: [
    { label: "Widget", count: 40, properties: { name: { type: "STRING", count: 40 }, size: { type: "INTEGER", count: 12 } } },
    { label: "Box", count: 5, properties: {} },
    { label: "Shelf", count: 2, properties: {} },
  ],
  relationships: [
    { type: "INSIDE", count: 42, connects: [{ from: "Widget", to: "Box", count: 30 }, { from: "Widget", to: "Widget", count: 12 }] },
    { type: "ON", count: 5, connects: [{ from: "Box", to: "Shelf", count: 5 }] },
  ],
};
const DESIGN = {
  available: true,
  updated: "2026-10-01T00:00:00",
  nodes: [
    { id: "w", label: "Widget", structure: "thing", definition: "A small thing." },
    { id: "b", label: "Box" },
    { id: "c", label: "Crate", definition: "A big box." },
  ],
  edges: [
    { from: "w", type: "INSIDE", to: "b", status: "decided" },
    { from: "b", type: "INSIDE", to: "c", status: "proposed", note: "Boxes go in crates." },
    { from: "w", type: "INSIDE", to: "w", status: "decided" },
  ],
};

test("the live schema becomes kinds and one connection per from-type-to", () => {
  const m = liveModel(SCHEMA);
  assert.deepEqual(m.nodes.map((n) => n.label), ["Widget", "Box", "Shelf"]);
  assert.deepEqual(m.nodes[0].properties, [{ key: "name", type: "STRING" }, { key: "size", type: "INTEGER" }]);
  assert.deepEqual(m.edges, [
    { from: "Widget", type: "INSIDE", to: "Box", count: 30 },
    { from: "Widget", type: "INSIDE", to: "Widget", count: 12 },
    { from: "Box", type: "ON", to: "Shelf", count: 5 },
  ]);
  // A connection to a label that isn't listed still gets its node.
  const odd = liveModel({ nodes: [], relationships: [{ type: "X", connects: [{ from: null, to: "A", count: 1 }] }] });
  assert.deepEqual(odd.nodes.map((n) => n.label), ["(no label)", "A"]);
  assert.deepEqual(liveModel(null), { nodes: [], edges: [] });
});

test("the design document maps ids to labels and skips broken or repeated edges", () => {
  const d = designModel({ ...DESIGN, edges: [...DESIGN.edges, { from: "w", type: "INSIDE", to: "b" }, { from: "zz", type: "Y", to: "b" }] });
  assert.equal(d.edges.length, 3);
  assert.deepEqual(d.edges[1], { from: "Box", type: "INSIDE", to: "Crate", status: "proposed", note: "Boxes go in crates." });
  assert.equal(d.nodes.find((n) => n.label === "Widget").definition, "A small thing.");
  assert.equal(designModel({ available: false }), null);
});

test("What's built: the live graph only, nothing dashed or amber", () => {
  const m = combine(liveModel(SCHEMA), designModel(DESIGN), "built");
  assert.deepEqual(m.nodes.map((n) => n.id), ["Box", "Shelf", "Widget"]);
  assert.ok(m.nodes.every((n) => !n.dashed && !n.warn));
  assert.ok(m.edges.every((e) => !e.dashed && !e.warn));
  assert.equal(m.edges.find((e) => e.loop).from, "Widget");
  // Colours come from every label, built or designed, so a kind keeps its colour in every view.
  assert.deepEqual(m.nodes.map((n) => n.colour), [PALETTE[0], PALETTE[2], PALETTE[3]]);
  const both = combine(liveModel(SCHEMA), designModel(DESIGN), "both");
  for (const n of m.nodes) assert.equal(both.nodes.find((x) => x.id === n.id).colour, n.colour);
});

test("What's designed: the design only, proposed edges dashed, live counts where built", () => {
  const m = combine(liveModel(SCHEMA), designModel(DESIGN), "designed");
  assert.deepEqual(m.nodes.map((n) => n.id), ["Box", "Crate", "Widget"]);
  assert.equal(m.nodes.find((n) => n.id === "Widget").count, 40);
  assert.equal(m.nodes.find((n) => n.id === "Crate").count, null);
  const crate = m.edges.find((e) => e.to === "Crate");
  assert.ok(crate.dashed && !crate.warn);
  assert.equal(stateText(crate, "designed"), "Proposed");
  assert.ok(!m.edges.find((e) => e.to === "Box").dashed);
});

test("Both: designed-not-built dashed, built-not-designed amber", () => {
  const m = combine(liveModel(SCHEMA), designModel(DESIGN), "both");
  assert.deepEqual(m.nodes.map((n) => n.id), ["Box", "Crate", "Shelf", "Widget"]);
  const node = (id) => m.nodes.find((n) => n.id === id);
  assert.ok(node("Crate").dashed && !node("Crate").warn);
  assert.ok(node("Shelf").warn && !node("Shelf").dashed);
  assert.ok(!node("Widget").dashed && !node("Widget").warn);
  const edge = (from, to) => m.edges.find((e) => e.from === from && e.to === to);
  assert.ok(edge("Box", "Crate").dashed);
  assert.ok(edge("Box", "Shelf").warn);
  assert.ok(!edge("Widget", "Box").dashed && !edge("Widget", "Box").warn);
  assert.equal(stateText(edge("Box", "Crate"), "both"), "Designed, not built yet");
  assert.equal(stateText(edge("Box", "Shelf"), "both"), "Built, not in the design");
  assert.equal(stateText(edge("Widget", "Box"), "both"), "Built and designed");
  // No design: Both is just what's built.
  assert.equal(combine(liveModel(SCHEMA), null, "both").nodes.length, 3);
});

test("a kind's connections out and in, a loop counted once", () => {
  const m = combine(liveModel(SCHEMA), null, "built");
  const c = connectionsOf(m, "Widget");
  assert.deepEqual(c.out.map((e) => `${e.type}>${e.to}`), ["INSIDE>Box", "INSIDE>Widget"]);
  assert.deepEqual(c.in, []);
  assert.deepEqual(connectionsOf(m, "Box").in.map((e) => e.from), ["Widget"]);
});

test("the table: every connection, then each kind with none", () => {
  const m = combine(liveModel({ ...SCHEMA, nodes: [...SCHEMA.nodes, { label: "Lonely", count: 1 }] }), null, "built");
  const rows = tableRows(m);
  assert.equal(rows.filter((r) => r.kind === "edge").length, 3);
  assert.deepEqual(rows.filter((r) => r.kind === "node").map((r) => r.from), ["Lonely"]);
});

test("search picks kinds by label and connections by type, with their ends", () => {
  const m = combine(liveModel(SCHEMA), null, "built");
  const byLabel = searchModel(m, "shel");
  assert.deepEqual([...byLabel.nodes], ["Shelf"]);
  assert.equal(byLabel.edges.size, 0);
  const byType = searchModel(m, "on");
  assert.deepEqual([...byType.edges].length, 1);
  assert.deepEqual([...byType.nodes].sort(), ["Box", "Shelf"]);
  assert.equal(searchModel(m, "  "), null);
});

test("node sizes grow with the count on a log scale; captions carry the count when asked", () => {
  assert.equal(nodeSize(0, 100), 54);
  assert.equal(nodeSize(100, 100), 110);
  assert.ok(nodeSize(10, 100) > 44 && nodeSize(10, 100) < 110);
  assert.equal(caption({ label: "Box", count: 1234 }, true), "Box\n1,234");
  assert.equal(caption({ label: "Box", count: 1234 }, false), "Box");
  assert.equal(caption({ label: "Box", count: null }, true), "Box");
});

test("the Arrows export: nodes at their places, relationships by id, dashed and amber kept", () => {
  const m = combine(liveModel(SCHEMA), designModel(DESIGN), "both");
  const out = toArrows(m, { Widget: { x: 10.4, y: -3.6 } });
  assert.deepEqual(Object.keys(out), ["nodes", "relationships"]);
  const widget = out.nodes.find((n) => n.caption === "Widget");
  assert.deepEqual(widget.position, { x: 10, y: -4 });
  assert.deepEqual(widget.labels, ["Widget"]);
  assert.equal(widget.properties.count, "40");
  assert.equal(widget.properties.name, "STRING");
  assert.equal(widget.style["node-color"], m.nodes.find((n) => n.id === "Widget").colour);
  for (const n of out.nodes) assert.ok(Number.isFinite(n.position.x) && Number.isFinite(n.position.y));
  const ids = new Set(out.nodes.map((n) => n.id));
  for (const r of out.relationships) assert.ok(ids.has(r.fromId) && ids.has(r.toId) && r.type);
  const toCrate = out.relationships.find((r) => r.toId === out.nodes.find((n) => n.caption === "Crate").id);
  assert.equal(toCrate.style["border-style"], "dashed");
  assert.equal(toCrate.properties.status, "proposed");
  const toShelf = out.relationships.find((r) => r.toId === out.nodes.find((n) => n.caption === "Shelf").id);
  assert.equal(toShelf.style["arrow-color"], WARN);
  assert.equal(out.nodes.find((n) => n.caption === "Crate").style["border-style"], "dashed");
  // Counts left out when hidden.
  assert.equal(toArrows(m, {}, { showCounts: false }).nodes.find((n) => n.caption === "Widget").properties.count, undefined);
});

test("why there's nothing to draw, from the request's status", () => {
  assert.equal(liveProblem({ status: 404 }), "no-access");
  assert.equal(liveProblem({ status: 503 }), "not-connected");
  assert.equal(liveProblem({ status: 422 }), "not-copied");
  assert.equal(liveProblem(new Error("x")), "failed");
});
