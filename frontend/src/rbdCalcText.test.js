import { test } from "node:test";
import assert from "node:assert/strict";
import { answerAtTime, formatProbability, formatReliability, oneIn, timeInWords } from "./rbdCalcText.js";

test("a reliability near 1 keeps the digits that show its gap to 1", () => {
  assert.equal(formatReliability(0.99994), "0.99994");
  assert.equal(formatReliability(0.999871234), "0.99987");
  assert.equal(formatReliability(0.904612), "0.9046");
  assert.equal(formatReliability(0.5), "0.5");
  assert.equal(formatReliability(1), "1");
  assert.equal(formatReliability(0.9999999999999999), "1");
  assert.equal(formatReliability(0), "0");
  assert.equal(formatReliability(null), "—");
});

test("a failure probability: scientific when small, a percentage from 1%", () => {
  assert.equal(formatProbability(6.0e-5), "6.0 × 10⁻⁵");
  assert.equal(formatProbability(0.00123), "1.2 × 10⁻³");
  assert.equal(formatProbability(0.103), "10%");
  assert.equal(oneIn(6.0e-5), "16,700");
  assert.equal(oneIn(0.004), "250");
  assert.equal(oneIn(0.103), null);
  assert.equal(oneIn(0.6), null);
});

test("times in words", () => {
  assert.equal(timeInWords(1, "Hours"), "1 hour");
  assert.equal(timeInWords(8760, "Hours"), "8,760 hours");
  assert.equal(timeInWords(3, ""), "3");
});

test("the answer at the time asked about", () => {
  assert.deepEqual(answerAtTime({ r: 0.99994, t: 1, unit: "Hours" }), {
    over: "the first 1 hour",
    reliability: "0.99994",
    failure: "Failure probability 6.0 × 10⁻⁵: about 1 in 16,700 systems fail in that time.",
  });
  assert.equal(answerAtTime({ r: 0.9, t: 100, unit: "Hours", now: true }).over, "the next 100 hours");
  assert.equal(answerAtTime({ r: 0.9, t: 100, unit: "Hours", survived: 500 }).over,
    "a further 100 hours, having survived 500 hours");
  assert.equal(answerAtTime({ r: 0.3, t: 100, unit: "Hours" }).failure, "Failure probability 70%.");
  assert.equal(answerAtTime({ r: null, t: 1 }), null);
  assert.equal(answerAtTime({ r: 0.9, t: "" }), null);
});

test("a life's band reads as its one-sided lower bound", async () => {
  const { lifeBoundText } = await import("./rbdCalcText.js");
  assert.equal(lifeBoundText({ lower: 915.7, upper: 1690, bound: 1012.3 }, 0.9), "≥ 1,012 at 90%");
  // A result from before the rule: the two-sided lower end, at its own one-sided level.
  assert.equal(lifeBoundText({ lower: 915.7, upper: 1690 }, 0.9), "≥ 915.7 at 95%");
  assert.equal(lifeBoundText(null, 0.9), null);
  assert.equal(lifeBoundText({ lower: null, upper: null }, 0.9), null);
});

test("the importance heading says which time it ranks at", async () => {
  const { importanceHeading } = await import("./rbdCalcText.js");
  const given = importanceHeading({ time: 8760, time_basis: "given" }, "Hours");
  assert.equal(given.at, "8,760 hours");
  assert.match(given.why, /Evaluate at t/);
  assert.match(importanceHeading({ time: 1727.09, time_basis: "reliability_90" }, "Hours").why, /falls to 90%/);
  assert.equal(importanceHeading({}, "Hours"), null);
});
