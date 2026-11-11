// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyAnswer, curveIsCurrent, markPending, requestKey } from "./calcSeries.js";

const DEFAULT = { temp_C: 79.375, load: 0.7 };
const start = [{ id: 0, values: DEFAULT, curves: { at: "default" }, error: null }];

test("a curve for other values is never read beside the values on screen", () => {
  // Type 80 °C: the curve for it is on order, so the default's isn't an answer.
  const a = { temp_C: "80", load: 0.7 };
  let series = markPending(start, 0, requestKey(a), a);
  assert.equal(curveIsCurrent(series[0]), false);
  // Type load 0.5 before the first answer is back.
  const b = { temp_C: "80", load: "0.5" };
  series = markPending(series, 0, requestKey(b), b);
  assert.equal(curveIsCurrent(series[0]), false);
  assert.deepEqual(series[0].curves, { at: "default" });
  // The second answer arrives: now there is something to read.
  series = applyAnswer(series, 0, requestKey(b), { curves: { at: "80 / 0.5" } });
  assert.equal(curveIsCurrent(series[0]), true);
  assert.deepEqual(series[0].curves, { at: "80 / 0.5" });
});

test("an answer that arrives late, for values since changed, is dropped", () => {
  const a = { temp_C: "80", load: 0.7 }, b = { temp_C: "80", load: "0.5" };
  let series = markPending(markPending(start, 0, requestKey(a), a), 0, requestKey(b), b);
  series = applyAnswer(series, 0, requestKey(b), { curves: { at: "80 / 0.5" } });
  // The first request's answer comes back after the second's.
  series = applyAnswer(series, 0, requestKey(a), { curves: { at: "80 / 0.7" } });
  assert.deepEqual(series[0].curves, { at: "80 / 0.5" });
  // ...and before it: still waiting for the values on screen.
  let early = markPending(markPending(start, 0, requestKey(a), a), 0, requestKey(b), b);
  early = applyAnswer(early, 0, requestKey(a), { curves: { at: "80 / 0.7" } });
  assert.equal(curveIsCurrent(early[0]), false);
  assert.deepEqual(early[0].curves, { at: "default" });
});

test("a failed request leaves no answer to read, and says why", () => {
  const a = { temp_C: "abc", load: 0.7 };
  let series = markPending(start, 0, requestKey(a), a);
  series = applyAnswer(series, 0, requestKey(a), { error: "Covariate 'temp_C' must be a number." });
  assert.equal(curveIsCurrent(series[0]), false);
  assert.equal(series[0].error, "Covariate 'temp_C' must be a number.");
  // Typing a good value recovers.
  const b = { temp_C: "80", load: 0.7 };
  series = applyAnswer(markPending(series, 0, requestKey(b), b), 0, requestKey(b), { curves: { at: "80" } });
  assert.equal(curveIsCurrent(series[0]), true);
  assert.equal(series[0].error, null);
});

test("the same number typed as text is the same request; a new range is a new one", () => {
  assert.equal(requestKey({ load: "0.5", temp_C: 80 }), requestKey({ temp_C: "80", load: 0.5 }));
  assert.notEqual(requestKey({ load: 0.5 }), requestKey({ load: 0.5 }, { xMin: 0, xMax: 5000 }));
  assert.notEqual(requestKey({ site: "North" }), requestKey({ site: "South" }));
  // Only the series named changes.
  const two = [...start, { id: 1, values: DEFAULT, curves: { at: "default" }, error: null }];
  assert.equal(curveIsCurrent(markPending(two, 1, "k")[0]), true);
});
