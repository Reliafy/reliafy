// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  answerParts, baseLevels, countsSummary, curveSummary, dataWords, effectText, forestRows, hazardShape, modelTabs,
  intervalLevel, listN, nextTabIndex, oddUnits, plainAnswer, ppSummary, ratioSign, resolveTab, termName,
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
  // Risk now stays for every account, Maintenance on or off: the Explorer scores only
  // positions on the asset tree, so a dataset's own running units are scored here.
  assert.deepEqual(labels(modelTabs({ kind: "joint" }, { riskNow: false })), ["Risk now", "Calculator", "Effects", "Diagnostics", "Data"]);
  assert.equal(resolveTab(modelTabs({ kind: "joint" }), "risk"), "risk");
  assert.equal(resolveTab(modelTabs({ kind: "joint" }), undefined), "risk");
});

test("a tab that doesn't apply is left out, and a one-view model has none", () => {
  // Made from parameters: no data, so no plot and nothing to check.
  assert.deepEqual(labels(modelTabs({ ...weibull, plot: null, params_only: true })),
    ["Calculator", "Model characteristics", "Data"]);
  // A regression saved without functions has no calculator.
  assert.deepEqual(labels(modelTabs({ kind: "regression" })), ["Effects", "Diagnostics", "Data"]);
  assert.deepEqual(modelTabs({ kind: "per_demand" }), []);
  // Competing risks: Effects only with covariates, the Calculator only with
  // stored curves.
  const cr = { kind: "competing_risks", curves: { x: [0, 1] } };
  assert.deepEqual(labels(modelTabs(cr)), ["Failure modes", "Calculator", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ ...cr, regression: { coefficients: [{ cause: "a", covariate: "z" }] } })),
    ["Failure modes", "Effects", "Calculator", "Diagnostics", "Data"]);
  assert.deepEqual(labels(modelTabs({ kind: "competing_risks" })), ["Failure modes", "Diagnostics", "Data"]);
  // Its old tab ids still open the tab that holds them.
  assert.equal(resolveTab(modelTabs(cr), "cif"), "modes");
  assert.equal(resolveTab(modelTabs({ ...cr, regression: { coefficients: [{}] } }), "coef"), "effects");
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
  // Near certain reads as the Risk now table says it: "> 99.9%", not "100%".
  const sure = answerParts({ kind: "joint", risk: [{ id: "P-19", risk: [0.5, 0.9999] }],
    horizons: { labels: ["30 days", "90 days"] } });
  assert.deepEqual(sure, ["highest risk: unit P-19, > 99.9% in the next 90 days"]);
  // ... for every account: the Risk now tab it points to is always there.
  assert.deepEqual(answerParts({ kind: "joint", risk: [{ id: "P-19", risk: [0.5, 0.9999] }],
    horizons: { labels: ["30 days", "90 days"] } }, { riskNow: false }), ["highest risk: unit P-19, > 99.9% in the next 90 days"]);
  const reg = answerParts({ kind: "regression", distribution: "Weibull PH", ratio_label: "hazard ratio", unit: "Hours",
    coefficients: [{ name: "temp_C", value: 0.138, ci: [0.093, 0.183] }, { name: "load", value: 0.5, ci: [-1, 2] }],
    validation: { available: true, concordance: { value: 0.868 } }, n: 32 });
  assert.equal(reg[0], "Weibull PH");
  assert.match(reg[1], /^load: hazard ratio 1.65 \(0.368–7.39\)$/);
  assert.equal(reg[2], "ranking 0.87 (Harrell's C)");
  assert.equal(reg[3], "32 observations");
  assert.deepEqual(answerParts({ kind: "nonparametric", distribution: "Kaplan-Meier", unit: "Months",
    metrics: { b10: 9 }, split: { failed: 18, running: 7 } }), ["Kaplan-Meier", "B10 9 months", "18 failed, 7 running"]);
  // By failure mode: the modes, the leading one at the horizon with its band,
  // any mode with its band, the data.
  const cr = {
    kind: "competing_risks", unit: "Hours", horizon: 5000, failed: 50, running: 22,
    causes: [
      { name: "bearing wear", failures: 29, at: { cif: 0.4, lower: 0.28, upper: 0.52 } },
      { name: "seal leak", failures: 15, at: { cif: 0.21, lower: 0.12, upper: 0.31 } },
    ],
    curves: { x: [0, 5000], all: [0, 0.69], all_lower: [0, 0.57], all_upper: [0, 0.8] },
  };
  assert.deepEqual(answerParts(cr), [
    "2 failure modes", "bearing wear 40% of units by 5,000 hours (28%–52%)", "any mode 69% (57%–80%)",
    "50 failed, 22 running",
  ]);
  const crReg = answerParts({ ...cr, regression: { model: "Fine-Gray" } });
  assert.equal(crReg[1], "Fine-Gray by mode");
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
  assert.match(effectText({ name: "C(site)[T.B]", ratio: 2, lo: 1.2, hi: 3, base: "A" }), /^site = B \(against A, the base level\)/);
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

// A Bayesian update (saved from the Fit dialog) says what it is on every tab: 90% credible
// intervals, never 95% confidence (UX review, Nov 2026).
const bayes = {
  ...weibull, method: "bayesian_update", credible_level: 0.9, gof: [], plot: null,
  params: [{ name: "alpha", value: 5.12, ci: [3.99, 6.6] }, { name: "beta", value: 3.03, ci: [2.33, 3.93] }],
  life: { confidence: 0.9, b_lives: [{ label: "B10", value: 2.5, lower: 1.9 }], mttf: { value: 4.6, lower: 3.9 } },
  split: { failed: 1, running: 1, other: 0 },
};

test("a Bayesian update: credible intervals at its level, Model characteristics, no Diagnostics", () => {
  assert.deepEqual(intervalLevel(bayes), { pct: 90, label: "90% credible", credible: true });
  assert.deepEqual(intervalLevel(weibull), { pct: 95, label: "95%", credible: false });
  assert.equal(intervalLevel({ method: "library" }).label, "Source's 5–95%");
  assert.deepEqual(labels(modelTabs(bayes)), ["Calculator", "Model characteristics", "Data"]);
  assert.deepEqual(labels(modelTabs({ ...bayes, plot: { scatter: {} } })),
    ["Probability plot", "Calculator", "Model characteristics", "Data"]);
  // Saved before it carried its life figures: the tab still shows (they come from the life path).
  assert.ok(labels(modelTabs({ ...bayes, life: undefined })).includes("Model characteristics"));
  const parts = answerParts(bayes);
  assert.ok(parts.includes("β 3.03 (90% credible 2.33–3.93)"), parts.join(" | "));
  assert.ok(parts.some((p) => /B10 .* at 90% credible\)/.test(p)), parts.join(" | "));
});

test("the model list's n: none for a model made from parameters, data plus prior for an update", () => {
  assert.equal(listN({ n: 0, params_only: true }).text, "—");
  assert.equal(listN({ n: 1, method: "bayesian_update" }).text, "1 + prior");
  assert.equal(listN({ n: 1200 }).text, "1,200");
  assert.equal(listN({ n: 1200 }).title, undefined);
});

// SurPyval's AFT coefficient accelerates the clock: a positive β (dust)
// shortens the life. Numbers from a Weibull AFT fit to 300 conveyor idlers
// (dusty β = 0.4388; site North β = -0.2807 against East).
const aft = {
  kind: "regression", effect: "aft", ratio_label: "time ratio", ci_level: 0.9,
  coefficients: [
    { name: "dusty", value: 0.4388, ci: [0.3, 0.58], ratio: Math.exp(0.4388) },
    { name: "site[T.North]", value: -0.2807, ci: [-0.44, -0.12] },
  ],
  functions: { covariates: [{ name: "dusty", type: "number" }, { name: "site", type: "category", options: ["East", "North"] }] },
};

test("an AFT time ratio is what the life is multiplied by: dust shortens it", () => {
  const [dusty, north] = forestRows(aft);
  // The stored exp(β) of a model saved before is ignored: worked out from β.
  assert.ok(Math.abs(dusty.ratio - Math.exp(-0.4388)) < 1e-12);
  assert.ok(dusty.ratio < 1 && dusty.lo < dusty.hi && dusty.hi < 1);
  assert.ok(Math.abs(dusty.lo - Math.exp(-0.58)) < 1e-12);
  assert.equal(effectText(dusty, "time ratio"),
    "Each +1 in dusty multiplies the life by 0.645 (90% 0.56 to 0.741): it ages 1.55× as fast.");
  assert.ok(north.ratio > 1);
  assert.match(effectText(north, "time ratio"),
    /^site = North \(against East, the base level\) multiplies the life by 1\.32 .*: it ages 1\.32× more slowly\.$/);
  assert.equal(north.label, "site = North vs East");
});

test("a PO odds ratio is on the odds of having failed; a hazard ratio keeps its sign", () => {
  const po = forestRows({ kind: "regression", effect: "odds", ratio_label: "odds ratio",
    coefficients: [{ name: "dusty", value: -1.26, ci: [-1.6, -0.9] }] });
  assert.ok(po[0].ratio > 1);
  assert.match(effectText(po[0], "odds ratio"), /multiplies the odds of having failed by 3\.53/);
  assert.equal(ratioSign({ effect: "hazard", ratio_label: "hazard ratio" }), 1);
  // A result saved with only its label.
  assert.equal(ratioSign({ ratio_label: "time ratio" }), -1);
});

test("a category's base level is named, from the payload or the calculator's levels", () => {
  assert.deepEqual(baseLevels(aft), { site: "East" });
  assert.deepEqual(baseLevels({ base_levels: { site: "Mine" } }), { site: "Mine" });
  assert.deepEqual(termName("C(site)[T.B]"), { label: "site = B", categorical: true, variable: "site", level: "B" });
  assert.equal(termName("`belt site`[T.B]").variable, "belt site");
});

test("a share page's plain answer: one in ten, its bound in words, then the pattern", () => {
  assert.equal(plainAnswer(weibull),
    "One in ten is expected to have failed by about 582 hours (at least 467 hours with 90% confidence); "
    + "failures become more likely with age.");
  // No bound with this fit: no bound said.
  const noBound = { ...weibull, life: { ...weibull.life, b_lives: [{ label: "B10", value: 582.37 }] } };
  assert.equal(plainAnswer(noBound), "One in ten is expected to have failed by about 582 hours; failures become more likely with age.");
  // Inspection data: the interval, never one end.
  const between = { ...weibull, randomness: { verdict: "random" },
    life: { confidence: 0.9, b_lives: [{ label: "B10", between: [400, 600] }] } };
  assert.equal(plainAnswer(between),
    "One in ten is expected to have failed between 400 and 600 hours; failures are about as likely at any age.");
  // A Bayesian update's bound is credible, not confidence.
  const bayes = { ...weibull, method: "bayesian_update", credible_level: 0.9 };
  assert.match(plainAnswer(bayes), /with 90% credibility/);
  // Per demand: the share of demands, and "one in N".
  assert.equal(plainAnswer({ kind: "per_demand", per_demand: { p: 0.015 } }), "About 1.5% of demands fail (about one in 67).");
  // Kinds whose answer isn't one B-life say nothing here.
  for (const kind of ["regression", "competing_risks", "joint"]) assert.equal(plainAnswer({ ...weibull, kind }), null);
  assert.equal(plainAnswer({}), null);
});
