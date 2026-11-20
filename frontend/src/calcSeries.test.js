// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyAnswer, autoRangeEnd, curveIsCurrent, markPending, nextCombinationValues, requestKey } from "./calcSeries.js";

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

test("a time past the end of the curves widens them to a round number beyond it", () => {
  const fns = { evaluate_path: "/api/models/m/evaluate", curves: { x: [0, 900, 1842] } };
  assert.equal(autoRangeEnd(fns, 3000), 3600);   // 3000 h asked, curves stop at 1842 h
  assert.equal(autoRangeEnd(fns, 20000), 24000);
  assert.equal(autoRangeEnd(fns, 1000), null);   // on the curve already
  assert.equal(autoRangeEnd(fns, NaN), null);    // nothing valid asked
  assert.equal(autoRangeEnd(fns, null), null);
  // No way to work the curves out again: nothing to widen.
  assert.equal(autoRangeEnd({ curves: fns.curves }, 3000), null);
});

test("Compare another moves a category to a level not yet shown", () => {
  const cov = [{ name: "design", type: "category", options: ["A", "B", "C"] }, { name: "load", type: "number" }];
  const one = [{ id: 0, values: { design: "A", load: 1 } }];
  assert.deepEqual(nextCombinationValues(one, cov), { design: "B", load: 1 });
  const two = [...one, { id: 1, values: { design: "B", load: 1 } }];
  assert.deepEqual(nextCombinationValues(two, cov), { design: "C", load: 1 });
  // Every level shown already: a copy of the last, to edit.
  const all = [...two, { id: 2, values: { design: "C", load: 2 } }];
  assert.deepEqual(nextCombinationValues(all, cov), { design: "C", load: 2 });
  // Numbers only: a copy; nothing yet: the defaults.
  assert.deepEqual(nextCombinationValues(one, [{ name: "load", type: "number" }]), { design: "A", load: 1 });
  assert.deepEqual(nextCombinationValues([], cov, { design: "A", load: 0 }), { design: "A", load: 0 });
});
