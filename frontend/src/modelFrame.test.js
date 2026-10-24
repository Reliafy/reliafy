// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  answerParts, countsSummary, curveSummary, dataWords, effectText, forestRows, hazardShape, modelTabs,
  nextTabIndex, oddUnits, ppSummary, resolveTab,
} from "./modelFrame.js";

const labels = (tabs) => tabs.map((t) => t.label);
const fns = { curves: { x: [0, 1], sf: [1, 0.5] }, life_path: "/api/models/x/life" };
const weibull = {
  kind: "distribution", distribution: "Weibull", distribution_id: "weibull", unit: "Hours", n: 30,
  params: [{ name: "alpha", value: 1435, ci: [1234, 1669] }, { name: "beta", value: 2.495, ci: [1.876, 3.319] }],
  plot: { scatter: {} }, functions: fns, randomness: { verdict: "wear_out" },
  life: { confidence: 0.9, b_lives: [{ label: "B10", value: 582.37, lower: 467.25 }], mttf: { value: 1273.2, lower: 1151 } },
  split: { failed: 30, running: 0, other: 0 },
};

test("every kind of model gets the approved tabs, in order", () => {
  assert.deepEqual(labels(modelTabs(weibull)),
    ["Probability plot", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "nonparametric", functions: fns, estimate: {} })),
    ["Survival curve", "Calculator", "Model characteristics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "flexible", functions: fns, life: {} })),
    ["Survival curve", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "discrete", functions: fns, counts: { k: [1] } })),
    ["Chance by count", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "regression", functions: fns })),
    ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "regression", functions: fns, tvc: {} })),
    ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  // Condition and life: no Fleet tab.
  assert.deepEqual(labels(modelTabs({ kind: "joint" })), ["Risk now", "Calculator", "Effects", "Diagnostics", "Data"]);
});

test("a tab that doesn't apply is left out, and a one-view model has none", () => {
  // Made from parameters: no data, so no plot and nothing to check.
  assert.deepEqual(labels(modelTabs({ ...weibull, plot: null, params_only: true })),
    ["Calculator", "Model characteristics", "Data"]);
  // A regression saved without functions has no calculator.
  assert.deepEqual(labels(modelTabs({ kind: "regression" })), ["Effects", "Diagnostics", "Data"]);
  assert.deepEqual(modelTabs({ kind: "per_demand" }), []);
  // Competing risks keeps its own page for now.
  assert.equal(modelTabs({ kind: "competing_risks" }), null);
  for (const r of [weibull, { kind: "joint" }, { kind: "regression", functions: fns }]) {
    assert.ok(modelTabs(r).length <= 6);
  }
});

test("old tab ids and names in links open the tab that holds them now", () => {
  const tabs = modelTabs({ kind: "regression", functions: fns });
  assert.equal(resolveTab(tabs, "coef"), "effects");
  assert.equal(resolveTab(tabs, "gof"), "diag");
  assert.equal(resolveTab(tabs, "check"), "diag");
  assert.equal(resolveTab(tabs, "Calculator"), "calc");
  assert.equal(resolveTab(tabs, "model characteristics"), "chars");
  assert.equal(resolveTab(tabs, "nonsense"), "effects");
  assert.equal(resolveTab(tabs, null), "effects");
  assert.equal(resolveTab([], "calc"), null);
});

test("the arrow keys move between tabs and wrap round", () => {
  assert.equal(nextTabIndex("ArrowRight", 0, 5), 1);
  assert.equal(nextTabIndex("ArrowRight", 4, 5), 0);
  assert.equal(nextTabIndex("ArrowLeft", 0, 5), 4);
  assert.equal(nextTabIndex("Home", 3, 5), 0);
  assert.equal(nextTabIndex("End", 0, 5), 4);
  assert.equal(nextTabIndex("Enter", 0, 5), null);
});

test("the answer line gives the pattern, the shape, B10 with its bound, the mean and the data", () => {
  assert.deepEqual(answerParts(weibull, { saved: "saved 3 min ago" }), [
    "Wear-out", "β 2.50 (95% 1.88–3.32)", "B10 582 hours (≥ 467 at 90%)", "mean 1,270 hours", "30 failed",
    "saved 3 min ago",
  ]);
});

test("no mean life where it can be infinite", () => {
  const lfp = { ...weibull, extras: { p: 0.6 }, life: { ...weibull.life, mttf: { value: null } } };
  assert.ok(!answerParts(lfp).some((p) => p.startsWith("mean")));
});

test("other kinds answer in their own terms", () => {
  assert.deepEqual(answerParts({ kind: "per_demand", per_demand: { p: 0.0075, ci: [0.00155, 0.0218], reliability: 0.9925,
    demands: 400, failures: 3 } }), ["failure probability 0.75% per demand (0.16%–2.2%)", "reliability 99.25%", "3 failed in 400 demands"]);
  const joint = answerParts({ kind: "joint", n_items: 40, n_events: 22, n_running: 18, n_readings: 300,
    marker: "vibration", risk: [{ id: "P6", risk: [0.1, 0.92] }], horizons: { labels: ["7 days", "30 days"] }, fit_ok: true });
  assert.deepEqual(joint, ["40 units (22 failed, 18 running)", "300 readings of vibration",
    "highest risk: unit P6, 92% in the next 30 days"]);
  const reg = answerParts({ kind: "regression", distribution: "Weibull PH", ratio_label: "hazard ratio", unit: "Hours",
    coefficients: [{ name: "temp_C", value: 0.138, ci: [0.093, 0.183] }, { name: "load", value: 0.5, ci: [-1, 2] }],
    validation: { available: true, concordance: { value: 0.868 } }, n: 32 });
  assert.equal(reg[0], "Weibull PH");
  assert.match(reg[1], /^load: hazard ratio 1.65 \(0.368–7.39\)$/);
  assert.equal(reg[2], "ranking 0.87 (Harrell's C)");
  assert.equal(reg[3], "32 observations");
  assert.deepEqual(answerParts({ kind: "nonparametric", distribution: "Kaplan-Meier", unit: "Months",
    metrics: { b10: 9 }, split: { failed: 18, running: 7 } }), ["Kaplan-Meier", "B10 9 months", "18 failed, 7 running"]);
});

test("the data in words", () => {
  assert.equal(dataWords({ n: 25 }, { failed: 18, running: 7, other: 0 }), "18 failed, 7 running");
  assert.equal(dataWords({ n: 1200 }), "1,200 observations");
  assert.equal(dataWords({}), null);
});

test("effects read as ratios with their intervals, and in words", () => {
  const rows = forestRows({ kind: "regression", ratio_label: "hazard ratio",
    coefficients: [{ name: "temp_C", value: Math.log(1.0478), ci: [Math.log(1.0154), Math.log(1.0811)], covariate_unit: "°C" }] });
  assert.equal(rows[0].unit, "°C");
  assert.ok(Math.abs(rows[0].ratio - 1.0478) < 1e-9);
  assert.equal(effectText(rows[0]),
    "Each +1 °C in temp_C multiplies the failure rate by 1.05 (95% 1.02 to 1.08); +10 °C multiplies it by 1.6.");
  // An interval through 1 says so.
  assert.match(effectText({ name: "load", ratio: 1.6, lo: 0.4, hi: 7 }), /can't rule out no effect\.$/);
  // A life (AFT) model's ratio is on the life.
  assert.match(effectText({ name: "load", ratio: 0.5, lo: 0.4, hi: 0.6 }, "time ratio"), /multiplies the life by 0.5/);
  // A category against its base level.
  assert.match(effectText({ name: "C(site)[T.B]", ratio: 2, lo: 1.2, hi: 3 }), /^site = B \(against the base level\)/);
  // An additive model has no ratio.
  const add = forestRows({ kind: "regression", coefficients: [{ name: "x", value: 0.002, ci: [0.001, 0.003] }] });
  assert.equal(add[0].additive, true);
  assert.equal(effectText(add[0]), "Each +1 in x adds 0.002 to the failure rate (95% 0.001 to 0.003).");
  // The condition and life model's ratios come with their words.
  const joint = forestRows({ kind: "joint", marker: "vibration", marker_unit: "mm/s",
    hazard_ratios: [{ name: "link", kind: "marker", hr: 3, lower: 2, upper: 4, text: "Each 1 unit higher vibration…" }] });
  assert.deepEqual([joint[0].name, joint[0].unit, effectText(joint[0])], ["vibration", "mm/s", "Each 1 unit higher vibration…"]);
});

test("the P-P check gives the largest gap in words", () => {
  const e = { x: [100, 200, 300], F: [0.1, 0.4, 0.7], model_F: [0.12, 0.3, 0.69] };
  const s = ppSummary(e, "Hours");
  assert.ok(Math.abs(s.gap - 0.1) < 1e-9);
  assert.equal(s.words, "The largest gap is 10 percentage points, at 200 hours: more had failed by then than the model says.");
  assert.match(curveSummary(e, "Hours").words, /within 10 percentage points/);
  assert.match(ppSummary({ x: [1], F: [0.5], model_F: [0.5] }).words, /sit on the diagonal/);
  assert.equal(ppSummary(null), null);
});

test("a discrete fit's counts name the biggest difference", () => {
  const s = countsSummary({ k: [1, 2, 3], failed: [2, 5, 1], expected: [2.1, 2.5, 1.2] }, "Cycles");
  assert.equal(s.words, "The biggest difference is at 2 cycles: 5 failed where the model expects 2.5.");
});

test("a hazard rate's shape in words", () => {
  const x = Array.from({ length: 50 }, (_, i) => i + 1);
  assert.equal(hazardShape(x, x.map((t) => t * 0.01)).shape, "rising");
  assert.equal(hazardShape(x, x.map((t) => 1 / t)).shape, "falling");
  assert.equal(hazardShape(x, x.map(() => 0.2)).shape, "level");
  assert.equal(hazardShape(x, x.map((t) => (t - 25) ** 2 + 10)).shape, "bathtub");
  assert.equal(hazardShape([1, 2], [1, 2]), null);
});

test("units beyond ±2.5 on the deviance residuals are counted", () => {
  assert.equal(oddUnits({ y: [0.1, -1, 2] }).tone, "good");
  const some = oddUnits({ y: [3, -0.2, 0.5, 1, 0.1, 0, 0.2, 0.1, 0.3, 0.2, 0.1, 0.4, 0.2, 0.1, 0.3, 0.2, 0.1, 0.4, 0.3, 0.1, 0.2] });
  assert.equal(some.odd, 1);
  assert.equal(some.tone, "neutral");
  assert.match(oddUnits({ y: [3, -3] }).words, /^2 units are beyond/);
});

test("a discrete model's chance at each count, read off its curve", async () => {
  const { pmfFromCurves } = await import("./modelFrame.js");
  // Geometric with p = 0.5 on a grid of quarter counts.
  const x = Array.from({ length: 17 }, (_, i) => i / 4);
  const ff = x.map((v) => (v < 1 ? 0 : 1 - 0.5 ** Math.floor(v)));
  assert.deepEqual(pmfFromCurves({ x, ff }), [{ k: 1, p: 0.5 }, { k: 2, p: 0.25 }, { k: 3, p: 0.125 }, { k: 4, p: 0.0625 }]);
  assert.deepEqual(pmfFromCurves(null), []);
});
