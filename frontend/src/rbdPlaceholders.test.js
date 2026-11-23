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

test("blocks with no real life model inside sub-systems are counted, and never called illustrative", () => {
  const note = placeholderNote(graph, { basic: 27, placeholders: 27, mostly: true });
  assert.equal(note.mostly, true);
  assert.match(note.text, /^27 of 27 basic blocks have no real life model yet: the results aren't real until each has one/);
  const few = placeholderNote(graph, { basic: 13, placeholders: 1, mostly: false });
  assert.equal(few.mostly, false);
  assert.match(few.text, /^1 of 13 basic blocks has no real life model yet: /);
  assert.doesNotMatch(few.text, /illustrative/);
});

test("before the server's count, the diagram's own blocks are counted and sub-systems are flagged", () => {
  const note = placeholderNote(graph);
  assert.equal(note.text, "1 block has only placeholder parameters (and maybe more inside its sub-systems): the results aren't real until each has a real model.");
  assert.equal(placeholderNote({ nodes: [{ id: "a", type: "component", data: { model: {} } }] }), null);
});
