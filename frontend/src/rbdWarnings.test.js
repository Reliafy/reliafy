import test from "node:test";
import assert from "node:assert/strict";
import { foldWarnings } from "./rbdWarnings.js";

const hint = (a, b) => `“${a}” and “${b}” are wired in series but look like a redundant pair.`;

test("several like-blocks-in-series hints fold into one line that keeps the list", () => {
  const hints = [hint("Motor 1", "Motor 2"), hint("ESC 1", "ESC 2"), hint("Propeller 1", "Propeller 2")];
  const other = "Pump model was fitted in months; the diagram is in hours.";
  const out = foldWarnings({ warnings: [other, ...hints], series_hints: hints });
  assert.deepEqual(out.plain, [other]);
  assert.deepEqual(out.hints, hints);
  assert.equal(out.summary, "3 groups of like blocks are in series: check whether any are redundant");
});

test("one hint is said in full, and warnings with no hints are left alone", () => {
  const one = hint("Pump A", "Pump B");
  assert.deepEqual(foldWarnings({ warnings: [one], series_hints: [one] }), { plain: [one], hints: [], summary: null });
  assert.deepEqual(foldWarnings({ warnings: ["x", "y"] }), { plain: ["x", "y"], hints: [], summary: null });
  assert.deepEqual(foldWarnings(null), { plain: [], hints: [], summary: null });
});

test("a hint the result doesn't list as a warning is never invented", () => {
  const out = foldWarnings({ warnings: ["x"], series_hints: [hint("A 1", "A 2"), hint("B 1", "B 2")] });
  assert.deepEqual(out, { plain: ["x"], hints: [], summary: null });
});
