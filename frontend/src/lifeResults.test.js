import test from "node:test";
import assert from "node:assert/strict";
import { bestFitSentence, boundWords, compareRows, timeAtValue } from "./lifeResults.js";

const CANDIDATES = [
  { id: "rayleigh", name: "Rayleigh", aic: 100.0 },
  { id: "weibull", name: "Weibull", aic: 101.3 },
  { id: "gamma", name: "Gamma", aic: 101.6 },
  { id: "lognormal", name: "Lognormal", aic: 101.0 },
  { id: "normal", name: "Normal", aic: 104.0 },
  { id: "exponential", name: "Exponential", aic: 131.2 },
  { id: "logistic", name: "Logistic", aic: Number.NaN },
];

test("compareRows: sorted by the criterion, with ΔAIC and a verdict", () => {
  const rows = compareRows(CANDIDATES, "aic", "weibull");
  assert.deepEqual(rows.map((r) => r.id), ["rayleigh", "lognormal", "weibull", "gamma", "normal", "exponential"]);
  assert.deepEqual(rows.map((r) => r.verdict), ["best", "about", "about", "about", "worse", "clearly"]);
  assert.equal(rows[0].delta, 0);
  assert.ok(Math.abs(rows[2].delta - 1.3) < 1e-9);
  assert.equal(rows.find((r) => r.current).id, "weibull");
  assert.equal(rows[4].verdictLabel, "Worse");
});

test("compareRows: nothing to rank", () => {
  assert.deepEqual(compareRows(null), []);
  assert.deepEqual(compareRows([{ id: "x", name: "X" }]), []);
});

test("bestFitSentence: best with its gloss, the ties named, the rest counted or named", () => {
  assert.equal(
    bestFitSentence(compareRows(CANDIDATES)),
    "Rayleigh (a Weibull with β = 2) fits best; Lognormal, Weibull and Gamma are about as good; " +
      "Normal and Exponential are worse."
  );
  const clear = compareRows([
    { id: "weibull", name: "Weibull", aic: 10 },
    { id: "exponential", name: "Exponential", aic: 40 },
  ]);
  assert.equal(bestFitSentence(clear), "Weibull fits best; Exponential is clearly worse.");
  const many = compareRows([
    { id: "weibull", name: "Weibull", aic: 10 },
    { id: "a", name: "A", aic: 30 }, { id: "b", name: "B", aic: 31 }, { id: "c", name: "C", aic: 32 },
  ]);
  assert.equal(bestFitSentence(many), "Weibull fits best; the other 3 are clearly worse.");
  assert.equal(bestFitSentence(compareRows([{ id: "weibull", name: "Weibull", aic: 1 }])), "Weibull fits best.");
  assert.equal(bestFitSentence([]), "");
});

test("boundWords: one-sided and two-sided bounds in words", () => {
  const pct = (v) => `${Math.round(v * 100)}%`;
  assert.equal(boundWords(90, "lower", 0.38, null, pct), "we're 90% sure it's at least 38%");
  assert.equal(boundWords(95, "upper", null, 0.6, pct), "we're 95% sure it's at most 60%");
  assert.equal(boundWords(95, "two-sided", 0.29, 0.57, pct), "we're 95% sure it's between 29% and 57%");
  assert.equal(boundWords(90, "lower", null, null, pct), "");
  assert.equal(boundWords(97.5, "lower", 3, null, String, "B10"), "we're 97.5% sure B10's at least 3");
});

test("timeAtValue: interpolates where a falling curve crosses the target", () => {
  const x = [0, 10, 20, 30];
  const y = [1, 0.8, 0.4, 0.1];
  assert.equal(timeAtValue(x, y, 0.8), 10);
  assert.ok(Math.abs(timeAtValue(x, y, 0.6) - 15) < 1e-9);
  assert.equal(timeAtValue(x, y, 0.05), null);
  assert.equal(timeAtValue(x, [1, null, 0.4, 0.1], 0.6), null);
});
