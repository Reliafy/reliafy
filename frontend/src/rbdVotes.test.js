import test from "node:test";
import assert from "node:assert/strict";
import { clampNote, clampVotes, inputCounts, voteNote, voteState } from "./rbdVotes.js";

test("a vote node is judged by the inputs wired into it", () => {
  assert.equal(voteState(2, 1), "too_many");
  assert.equal(voteState(2, 2), "all_must_work");
  assert.equal(voteState(1, 2), "ok");
  assert.equal(voteState(2, 3), "ok");
  assert.equal(voteState(1, 1), "ok");
  assert.equal(voteState(2, 0), "unwired");
  assert.equal(voteState(1, 0), "ok");
  assert.equal(voteState(0, 2), "too_many");
  assert.equal(voteNote(2, 1), "Needs 2 working inputs; 1 is wired in");
  assert.equal(voteNote(2, 2), "All 2 must work: no redundancy");
  assert.equal(voteNote(1, 2), "");
});

test("inputs are counted from the wires", () => {
  assert.deepEqual(inputCounts([{ source: "a", target: "v" }, { source: "b", target: "v" }, { source: "v", target: "out" }]),
    { v: 2, out: 1 });
});

test("removing wires below what a vote node needs clamps it, and says so", () => {
  const nodes = [{ id: "v", type: "knode", data: { label: "Logic", n: 2, k: 2 } }, { id: "a", type: "component", data: {} }];
  const { nodes: out, clamped } = clampVotes(nodes, { v: 2 }, { v: 1 });
  assert.equal(out[0].data.n, 1);
  assert.deepEqual(clamped, [{ id: "v", label: "Logic", from: 2, to: 1 }]);
  assert.equal(clampNote(clamped), "“Logic” now needs 1 of 1 (it needed 2, more than are wired in).");
  // Wiring in (or none left, mid-redrawing) never clamps.
  assert.equal(clampVotes(nodes, { v: 1 }, { v: 2 }).nodes, nodes);
  assert.equal(clampVotes(nodes, { v: 1 }, {}).nodes, nodes);
  // Still enough wired in: unchanged.
  const three = [{ id: "v", type: "knode", data: { n: 2 } }];
  assert.equal(clampVotes(three, { v: 3 }, { v: 2 }).clamped.length, 0);
});
