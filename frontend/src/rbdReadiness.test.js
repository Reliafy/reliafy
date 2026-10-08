// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_BLOCKS, NOT_CONNECTED, diagramGap } from "./rbdReadiness.js";

const io = [
  { id: "input", type: "input" },
  { id: "output", type: "output" },
];
const block = (id, type = "component") => ({ id, type, data: { label: id } });
const edge = (source, target) => ({ id: `${source}-${target}`, source, target });

test("Input and Output alone have no blocks", () => {
  assert.equal(diagramGap({ nodes: io, edges: [] }), NO_BLOCKS);
  assert.equal(diagramGap({ nodes: io, edges: [edge("input", "output")] }), NO_BLOCKS);
  assert.equal(diagramGap({}), NO_BLOCKS);
  assert.equal(diagramGap(null), NO_BLOCKS);
});

test("blocks off the path from Input to Output aren't connected", () => {
  assert.equal(diagramGap({ nodes: [...io, block("a")], edges: [] }), NOT_CONNECTED);
  assert.equal(diagramGap({ nodes: [...io, block("a")], edges: [edge("input", "a")] }), NOT_CONNECTED);
  assert.equal(diagramGap({ nodes: [...io, block("a")], edges: [edge("a", "output")] }), NOT_CONNECTED);
  // Wired backwards.
  assert.equal(
    diagramGap({ nodes: [...io, block("a")], edges: [edge("output", "a"), edge("a", "input")] }),
    NOT_CONNECTED
  );
});

test("one block on a path is enough", () => {
  const nodes = [...io, block("a"), block("b")];
  assert.equal(diagramGap({ nodes, edges: [edge("input", "a"), edge("a", "output")] }), null);
  // b dangles: that's validation's to explain, not an empty diagram.
  assert.equal(
    diagramGap({ nodes, edges: [edge("input", "a"), edge("a", "output"), edge("input", "b")] }),
    null
  );
  const vote = block("v", "knode");
  assert.equal(
    diagramGap({
      nodes: [...nodes, vote],
      edges: [edge("input", "a"), edge("input", "b"), edge("a", "v"), edge("b", "v"), edge("v", "output")],
    }),
    null
  );
});

test("without one Input and one Output, validation explains it", () => {
  assert.equal(diagramGap({ nodes: [block("a")], edges: [] }), null);
});
