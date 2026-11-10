import test from "node:test";
import assert from "node:assert/strict";
import {
  bestFitSentence, boundSideFor, boundWords, checkTime, compareRows, perUnit, precisePercent, stretchTo,
  timeAtValue, timeInWords,
} from "./lifeResults.js";

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

test("precisePercent: never rounds the answer to 100% or 0%", () => {
  // The reported case: reliability 99.82% read "100%", its bound "99%".
  assert.equal(precisePercent(0.99823), "99.82%");
  assert.equal(precisePercent(0.9996), "99.96%");
  assert.equal(precisePercent(0.99952), "99.952%");
  assert.equal(precisePercent(0.986), "98.6%");
  assert.equal(precisePercent(0.9999977), "99.99977%");
  // Only exactly 1 and 0 read 100% and 0%.
  assert.equal(precisePercent(1), "100%");
  assert.equal(precisePercent(0), "0%");
  assert.notEqual(precisePercent(1 - 1e-13), "100%");
  assert.equal(precisePercent(1 - 1e-13), ">99.99999999%");
  // The low end keeps three figures, as before.
  assert.equal(precisePercent(0.00177), "0.177%");
  assert.equal(precisePercent(0.000331), "0.0331%");
  assert.equal(precisePercent(0.0532), "5.32%");
  // The middle: three figures, no padding zeros.
  assert.equal(precisePercent(0.5714), "57.1%");
  assert.equal(precisePercent(0.57), "57%");
  assert.equal(precisePercent(0.896), "89.6%");
  assert.equal(precisePercent(0.904), "90.4%");
  assert.equal(precisePercent(null), "—");
  assert.equal(precisePercent(Number.NaN), "—");
  // A value that isn't a proper probability is shown, not hidden.
  assert.equal(precisePercent(1.2), "120%");
});

test("timeInWords: the typed time with a unit that agrees with it", () => {
  assert.equal(timeInWords(1, "Months"), "1 month");
  assert.equal(timeInWords("1", "months"), "1 month");
  assert.equal(timeInWords(0.5, "Months"), "0.5 months");
  assert.equal(timeInWords(3000, "Hours"), "3,000 hours");
  assert.equal(timeInWords(1, "kWh"), "1 kWh");
  assert.equal(timeInWords(1234.5, ""), "1,234.5");
  assert.equal(timeInWords("", "Hours"), "—");
});

test("perUnit: the unit of a hazard or a density", () => {
  assert.equal(perUnit("Months"), "per month");
  assert.equal(perUnit("flight hours"), "per flight hour");
  assert.equal(perUnit("kWh"), "per kWh");
  assert.equal(perUnit(""), "");
  assert.equal(perUnit(null), "");
});

test("checkTime: every refused value says what to type", () => {
  assert.deepEqual(checkTime("100"), { ok: true, value: 100, message: null });
  assert.deepEqual(checkTime("0"), { ok: true, value: 0, message: null });
  assert.deepEqual(checkTime("1,500"), { ok: true, value: 1500, message: null });
  // Blank is not zero.
  assert.equal(checkTime("").ok, false);
  assert.equal(checkTime("", { example: 40 }).message, "Enter a time, e.g. 40.");
  assert.equal(checkTime("").message, "Enter a time.");
  // Negative is refused as typed.
  assert.equal(checkTime("-100").ok, false);
  assert.equal(checkTime("-100").message, "Time can't be negative. Enter 0 or more.");
  assert.equal(checkTime("abc", { example: 40 }).message, "Enter a number, e.g. 40.");
  // The optional box: blank is fine (nothing survived yet); negative is not.
  assert.deepEqual(checkTime("", { optional: true }), { ok: true, value: 0, message: null });
  assert.equal(checkTime("-5", { optional: true }).message,
               "Time can't be negative. Enter 0 or more, or leave this empty.");
});

test("boundSideFor: the side follows the function's direction", () => {
  // A lower bound on reliability is an upper bound on failure probability.
  assert.equal(boundSideFor("sf", "ff", "lower"), "upper");
  assert.equal(boundSideFor("sf", "hf", "lower"), "upper");
  assert.equal(boundSideFor("sf", "Hf", "lower"), "upper");
  assert.equal(boundSideFor("ff", "sf", "upper"), "lower");
  // The same direction keeps the side; so does going there and back.
  assert.equal(boundSideFor("ff", "hf", "upper"), "upper");
  assert.equal(boundSideFor("sf", "df", "lower"), "lower");
  assert.equal(boundSideFor("df", "ff", boundSideFor("sf", "df", "lower")), "upper");
  assert.equal(boundSideFor("ff", "sf", boundSideFor("sf", "ff", "upper")), "upper");
  // Two-sided and none have no side to flip.
  assert.equal(boundSideFor("sf", "ff", "two-sided"), "two-sided");
  assert.equal(boundSideFor("sf", "ff", "none"), "none");
});

test("stretchTo: the next 1-2-5 value comfortably past the time asked for", () => {
  assert.equal(stretchTo(100), 200);
  assert.equal(stretchTo(76), 100);
  assert.equal(stretchTo(470), 1000);
  assert.equal(stretchTo(0.3), 0.5);
  assert.equal(stretchTo(1800), 2000);
  assert.equal(stretchTo(1900), 5000);
  assert.equal(stretchTo(0), null);
  assert.equal(stretchTo(-4), null);
  // Always past the time itself.
  for (const r of [0.07, 1, 9.2, 99, 12345]) assert.ok(stretchTo(r) > r);
});
