import { test } from "node:test";
import assert from "node:assert/strict";
import {
  accelerationRows, altAnswerParts, altTabs, compareCheck, defaultUse, distanceCheck, distanceWords,
  failureWords, levelWords, lifeCheck, parseUse, pWords, resolveAltTab, shapeCheck, shapeParam, shapeWords,
} from "./altFrame.js";

const FLUID = {
  kind: "alt", distribution: "Weibull", distribution_id: "weibull", life_model: "Inverse power law",
  unit: "minutes", n: 76, n_failures: 70,
  params: [{ name: "beta", value: 0.7769, ci: [0.6297, 0.9585] }],
  stresses: [{ key: "s1", column: "kV", label: "Voltage (kV)", unit: "kV" }],
  levels: [
    { stress: [30], n: 11, failures: 11, characteristic_life: 1950.4 },
    { stress: [36], n: 15, failures: 15, characteristic_life: 18.42 },
  ],
  probability_plot: { series: [] },
};

test("tabs: every view of a saved model; no Calculator before it is saved", () => {
  assert.deepEqual(altTabs(FLUID).map((t) => t.label),
    ["Life-stress", "Probability plot", "Calculator", "Diagnostics", "Data"]);
  assert.deepEqual(altTabs(FLUID, { saved: false }).map((t) => t.id), ["life", "prob", "diag", "data"]);
  assert.deepEqual(altTabs({ ...FLUID, probability_plot: null }).map((t) => t.id), ["life", "calc", "diag", "data"]);
});

test("tabs: old ids and names open the tab that holds them now", () => {
  const tabs = altTabs(FLUID);
  assert.equal(resolveAltTab(tabs, null), "life");
  assert.equal(resolveAltTab(tabs, "plot"), "life");
  assert.equal(resolveAltTab(tabs, "detail"), "data");
  assert.equal(resolveAltTab(tabs, "Use-level calculator"), "calc");
  assert.equal(resolveAltTab(tabs, "gof"), "diag");
  assert.equal(resolveAltTab(tabs, "Probability plot"), "prob");
  assert.equal(resolveAltTab(altTabs(FLUID, { saved: false }), "calc"), "life");
  assert.equal(resolveAltTab([], "life"), null);
});

test("answer line: the model, its shape, the life across the levels, the data", () => {
  assert.deepEqual(altAnswerParts(FLUID, { saved: "saved 1 min ago" }), [
    "Inverse power law model (Weibull)",
    "β 0.777 (95% 0.63–0.959)",
    "life 18.4–1,950 minutes across 2 tested levels",
    "70 failed, 6 still running",
    "saved 1 min ago",
  ]);
  const old = { ...FLUID, n_failures: undefined };
  assert.equal(failureWords(old), "76 observations");
  assert.ok(altAnswerParts({ ...FLUID, no_finite_maximum: { message: "x" } }).includes("no finite maximum"));
});

test("shape: β for a Weibull, σ (spread) for a lognormal, none for an exponential", () => {
  assert.equal(shapeParam(FLUID).label, "Shape β");
  assert.equal(shapeParam({ distribution_id: "lognormal", params: [{ name: "sigma", value: 0.5 }] }).label, "Spread σ");
  assert.equal(shapeParam({ distribution_id: "exponential", params: [] }), null);
  assert.equal(shapeWords({ params: [{ name: "beta", value: 2, ci: null }] }), "β 2");
});

test("levels in words: the unit given or the one the label names", () => {
  assert.equal(levelWords([30], FLUID.stresses), "30 kV");
  assert.equal(levelWords([60, 0.5], [{ label: "Temperature (°C)" }, { label: "Load" }]), "60 °C, Load 0.5");
});

test("acceleration factors against each tested level", () => {
  const rows = accelerationRows(FLUID.levels, 3901);
  assert.equal(rows[0].af.toFixed(2), "2.00");
  assert.ok(Math.abs(rows[1].af - 3901 / 18.42) < 1e-9);
  assert.equal(accelerationRows(FLUID.levels, null)[0].af, null);
});

test("use stress: parsed only when every value is a number; the mildest level by default", () => {
  assert.deepEqual(parseUse(["21", "0.4"]), [21, 0.4]);
  assert.equal(parseUse(["21", ""]), null);
  assert.equal(parseUse(["x"]), null);
  assert.deepEqual(defaultUse(FLUID), [30]);
});

test("diagnostics in words", () => {
  assert.equal(pWords(0.0004), "p < 0.001");
  assert.equal(pWords(0.1902), "p = 0.19");
  const diag = {
    shape: { verdict: "ok", computed: true, p: 0.19 },
    life_stress: { verdict: "fail", computed: true, p: 0.0205 },
    comparison: [
      { name: "Temperature–nonthermal", current: true, delta: 0 },
      { name: "Dual power", delta: -3.81, life_model_id: "dual_power" },
      { name: "General log-linear", delta: -6.76 },
      { name: "Dual exponential (temp–humidity)", delta: 0 },
    ],
    extrapolation: [
      { label: "Temperature (°C)", levels: 3, levels_verdict: "ok", use: 42, distance: 1.07, use_verdict: "warn" },
      { label: "Load", levels: 2, levels_verdict: "warn", use: 0.35, distance: 0.61, use_verdict: "ok" },
    ],
  };
  assert.equal(shapeCheck(diag, FLUID).tone, "good");
  assert.match(lifeCheck(diag, { life_model: "Temperature–nonthermal" }).words, /^No: .*Temperature–nonthermal line \(p = 0.021\)/);
  const c = compareCheck(diag);
  assert.equal(c.tone, "caveat");
  assert.equal(c.words, "Yes: General log-linear fits better (AIC 6.8 lower; not offered here), and so does "
    + "Dual power (AIC 3.8 lower). Prefer another only where its physics suits the stress.");
  const d = distanceCheck(diag);
  assert.equal(d.tone, "caveat");
  assert.match(d.words, /Temperature \(°C\): the use stress is 1.1 times/);
  assert.match(d.words, /Load was tested at only 2 levels/);
  assert.equal(distanceWords(diag.extrapolation[0]), "1.1× the range");
  assert.equal(distanceWords({ use: 30, distance: 0 }), "inside");
  // No use stress yet: it asks for one.
  const none = distanceCheck({ extrapolation: [{ label: "Voltage (kV)", levels: 4, levels_verdict: "ok" }] });
  assert.equal(none.tone, null);
  assert.match(none.words, /Enter your use stress/);
  // An exponential has no shape to test; a test that couldn't run says why.
  assert.match(shapeCheck({ shape: null }, { distribution_id: "exponential" }).words, /no shape/);
  assert.equal(lifeCheck({ life_stress: { computed: false, detail: "two levels" } }).words, "Can't tell: two levels.");
  assert.equal(compareCheck({ comparison: [{ current: true, delta: 0 }, { delta: 1.2 }] }).tone, "good");
});
