import { test } from "node:test";
import assert from "node:assert/strict";
import { placeholderNote } from "./rbdPlaceholders.js";

const graph = {
  nodes: [
    { id: "in", type: "input" }, { id: "out", type: "output" },
    { id: "c", type: "component", data: { label: "Comms", model: { placeholder: true } } },
    { id: "p", type: "subsystem", data: { label: "Propulsion", rbd: { id: "r1" } } },
  ],
};

test("placeholders inside sub-systems are counted, and most of them is said plainly", () => {
  const note = placeholderNote(graph, { basic: 27, placeholders: 27, mostly: true });
  assert.equal(note.mostly, true);
  assert.match(note.text, /^27 of 27 basic blocks are placeholders: most of this answer rests on invented lives/);
  const few = placeholderNote(graph, { basic: 13, placeholders: 1, mostly: false });
  assert.equal(few.mostly, false);
  assert.equal(few.text, "1 of 13 basic blocks is a placeholder: results are illustrative until you set real values.");
});

test("before the server's count, the diagram's own blocks are counted and sub-systems are flagged", () => {
  const note = placeholderNote(graph);
  assert.equal(note.text, "1 block uses placeholder parameters (and maybe more inside its sub-systems): results are illustrative until you set real values.");
  assert.equal(placeholderNote({ nodes: [{ id: "a", type: "component", data: { model: {} } }] }), null);
});
