// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { answerFor, exactBound, exactKey, exactTimes, exactValues } from "./calcExact.js";

// The grid of a steep early curve (lognormal, B10 ≈ 226 h): straight lines
// between its points read 95.6% at 100 h; the model says 96.3%.
const GRID = { x: [0, 80, 160], sf: [1, 0.985, 0.89] };
const gridAt100 = () => GRID.sf[1] + (100 - 80) / 80 * (GRID.sf[2] - GRID.sf[1]);

test("the answer is the model's value at the time typed, not read off the grid", () => {
  const key = exactKey(null, 100);
  const entry = { key, data: exactValues({ x: [100], sf: [0.963], ff: [0.037], hf: [1e-3], Hf: [0.0377], df: [5e-4] }) };
  const a = answerFor(entry, key, "sf", { canAsk: true, gridValue: gridAt100 });
  assert.deepEqual(a, { value: 0.963, state: "exact" });
  assert.notEqual(a.value, gridAt100());
});

test("while the model's answer is on its way, nothing is read off the grid", () => {
  const key = exactKey(null, 100);
  assert.deepEqual(answerFor(null, key, "sf", { canAsk: true, gridValue: gridAt100 }), { value: null, state: "working" });
  // An answer for another time is never shown for this one.
  const old = { key: exactKey(null, 90), data: { sf: 0.97 } };
  assert.equal(answerFor(old, key, "sf", { canAsk: true, gridValue: gridAt100 }).state, "working");
});

test("only where the model can't be asked is the drawn curve read, and said approximate", () => {
  const key = exactKey(null, 100);
  const refused = { key, data: null, error: "Not signed in" };
  const a = answerFor(refused, key, "sf", { canAsk: true, gridValue: gridAt100 });
  assert.equal(a.state, "approx");
  assert.equal(answerFor(null, key, "sf", { canAsk: false, gridValue: gridAt100 }).state, "approx");
});

test("the times asked: t, or the age survived to and that age plus t", () => {
  assert.deepEqual(exactTimes(100), [100]);
  assert.deepEqual(exactTimes(100, 50), [50, 150]);
  assert.equal(exactTimes(null), null);
});

test("conditional answers from the model's values at s and s + t", () => {
  const v = exactValues({ x: [50, 150], sf: [0.9, 0.6], hf: [0.001, 0.004], Hf: [0.105, 0.511], df: [0.002, 0.003] }, 50);
  assert.ok(Math.abs(v.sf - 0.6 / 0.9) < 1e-12);
  assert.ok(Math.abs(v.ff - (1 - 0.6 / 0.9)) < 1e-12);
  assert.equal(v.hf, 0.004);
  assert.ok(Math.abs(v.Hf - 0.406) < 1e-12);
  assert.ok(Math.abs(v.df - 0.003 / 0.9) < 1e-12);
});

test("a bound at one time from the confidence route", () => {
  assert.deepEqual(exactBound({ bound: "lower", lower: [0.86], upper: null }), { bound: "lower", lower: 0.86, upper: null });
  assert.deepEqual(exactBound({ bound: "two-sided", lower: [0.8], upper: [0.99] }), { bound: "two-sided", lower: 0.8, upper: 0.99 });
});

test("the key reads a number typed as text as that number", () => {
  assert.equal(exactKey({ a: "80" }, 100), exactKey({ a: 80 }, 100));
  assert.notEqual(exactKey({ a: 80 }, 100), exactKey({ a: 80 }, 100, 20));
});

test("the Calculator reads the grid only to draw, and for a model that can't be asked", () => {
  const src = readFileSync(new URL("./components/Calculator.jsx", import.meta.url), "utf8");
  const calls = [...src.matchAll(/interp\(/g)].length;
  // The definition, conditionalize's s (drawing), and answerOf's fallback for a model that can't be asked.
  assert.equal(calls, 4);
  assert.ok(!/interp\(band\./.test(src), "the bound is never read off the band's grid");
});
