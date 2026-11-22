import { test } from "node:test";
import assert from "node:assert/strict";
import {
  plotInEnteredUnits,
  seriesLabel,
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
    "β 0.777 (90% two-sided 0.63–0.959)",
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
    common_shape: { computed: true, p: 0.19, statistic: 3.31, df: 2, shapes: [], left_out: [] },
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
  assert.equal(shapeCheck(diag, FLUID).tone, null);
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
  assert.match(shapeCheck({ common_shape: null }, { distribution_id: "exponential" }).words, /no shape/);
  assert.match(shapeCheck({ common_shape: null }, {}).words, /no shape/);
  assert.equal(shapeCheck({ common_shape: { computed: false, detail: "one level has two failures" } }, {}).words,
    "Can't tell: one level has two failures.");
  assert.equal(lifeCheck({ life_stress: { computed: false, detail: "two levels" } }).words, "Can't tell: two levels.");
  assert.equal(compareCheck({ comparison: [{ current: true, delta: 0 }, { delta: 1.2 }] }).tone, "good");
});

test("the shape's interval says its level: 90% by the rule, a fit's own level where it carries one", () => {
  assert.equal(altAnswerParts({ ...FLUID, ci_level: 0.9 })[1], "β 0.777 (90% two-sided 0.63–0.959)");
  assert.equal(altAnswerParts({ ...FLUID, ci_level: 0.95 })[1], "β 0.777 (95% two-sided 0.63–0.959)");
});

test("a temperature given in °C is shown and entered in °C, asked in kelvin", async () => {
  const { defaultUse, useForModel, levelWords, kelvinWords, inputStressName } = await import("./altFrame.js");
  const r = {
    stresses: [{ key: "s1", column: "temp_C", label: "Temperature", unit: "K", entered_unit: "°C" }],
    levels: [{ stress: [378.15] }, { stress: [398.15] }, { stress: [418.15] }],
  };
  assert.deepEqual(defaultUse(r), [105]);
  assert.deepEqual(useForModel(r, ["40"]), [313.15]);
  assert.equal(levelWords([378.15], r.stresses), "105 °C");
  assert.equal(kelvinWords(r, ["40"]), "40 °C is 313.15 K");
  assert.equal(inputStressName(r.stresses[0]), "Temperature (°C)");
  // A model fitted in kelvin is as before.
  const k = { stresses: [{ key: "s1", label: "Temperature", unit: "K" }], levels: [{ stress: [378.15] }] };
  assert.deepEqual(useForModel(k, ["313.15"]), [313.15]);
  assert.equal(kelvinWords(k, ["313.15"]), null);
  const f = { stresses: [{ unit: "K", entered_unit: "°F", label: "T" }], levels: [{ stress: [313.15] }] };
  assert.deepEqual(defaultUse(f), [104]);
  assert.deepEqual(useForModel(f, ["104"]), [313.15]);
});

test("useRangeWarning: says when the use stress is far from the tested ones", async () => {
  const { useRangeWarning } = await import("./altFrame.js");
  const r = { stresses: [{ label: "Voltage", unit: "kV" }], levels: [{ stress: [30] }, { stress: [33] }, { stress: [36] }] };
  const w = useRangeWarning(r, [20], { value: 10990 });
  assert.match(w, /^20 kV is well below the tested 30–36 kV \(an acceleration factor of 10,990×\)/);
  // Outside at all is an extrapolation; inside is not.
  assert.match(useRangeWarning(r, [27]), /^27 kV is below the tested 30–36 kV\. The life here rests on/);
  assert.equal(useRangeWarning(r, [33]), null);
  assert.equal(useRangeWarning(r, [36]), null);
  // A temperature entered in °C reads back in °C.
  const t = { stresses: [{ label: "Temperature", entered_unit: "°C" }], levels: [{ stress: [378.15] }, { stress: [418.15] }] };
  assert.match(useRangeWarning(t, [313.15]), /^40 °C is well below the tested 105–145 °C/);
});

test("activationEnergy: SurPyval's own value; a × k only for the temperature–nonthermal model", async () => {
  const { activationEnergy } = await import("./altFrame.js");
  const coefficients = [{ name: "a", value: 6957, ci: [5000, 9000] }, { name: "b", value: 8.39e-5 }];
  const own = { value: 0.5995, ci: [0.473, 0.726], kelvin: 6957, level: 0.9 };
  // From the fit's payload, or the use-stress answer (a model saved before the fit carried it).
  assert.deepEqual(activationEnergy({ life_model_id: "arrhenius", activation_energy: own }),
    { value: 0.5995, ci: [0.473, 0.726], level: 0.9 });
  assert.equal(activationEnergy({ life_model_id: "eyring" }, { activation_energy: own }).value, 0.5995);
  // No SurPyval value: none for Arrhenius (it waits for the answer), a × k for temperature–nonthermal.
  assert.equal(activationEnergy({ life_model_id: "arrhenius", coefficients }), null);
  const pe = activationEnergy({ life_model_id: "power_exponential", coefficients });
  assert.ok(Math.abs(pe.value - 0.5995) < 1e-3);
  assert.ok(Math.abs(pe.ci[0] - 0.4309) < 1e-3);
  assert.equal(activationEnergy({ life_model_id: "inverse_power", coefficients }), null);
});

test("shapeCheck: the common-shape test in plain words, with its statistic and the levels left out", () => {
  const stresses = [{ key: "s1", label: "Temperature", unit: "K", entered_unit: "°C" }];
  const r = { distribution_id: "weibull", params: [{ name: "beta", value: 2.24 }], stresses };
  const same = shapeCheck({ common_shape: {
    computed: true, p: 0.4325, statistic: 1.676, df: 2, parameter: "beta", common_shape: 2.244,
    shapes: [{ stress: [378.15], shape: 2.474 }, { stress: [398.15], shape: 1.69 }, { stress: [418.15], shape: 2.602 }],
    left_out: [],
  } }, r);
  assert.equal(same.tone, null);
  assert.equal(same.words, "The shapes are consistent (p = 0.43): one β fits every tested stress, so extrapolating "
    + "to the use stress rests on that.");
  assert.equal(same.detail, "Likelihood-ratio statistic 1.68 on 2 degrees of freedom (χ²); each level's own β 2.47 "
    + "at 105 °C, 1.69 at 125 °C, 2.6 at 145 °C; one β for all 2.24.");
  assert.equal(same.leftOut, null);
  const differ = shapeCheck({ common_shape: {
    computed: true, p: 0.003, statistic: 9.1, df: 1, shapes: [], left_out: [{ stress: [358.15], failures: 1 }],
  } }, r);
  assert.equal(differ.tone, "caveat");
  assert.match(differ.words, /^The shapes differ \(p = 0.003\): .* Extrapolation is unreliable\.$/);
  assert.match(differ.detail, /on 1 degree of freedom/);
  assert.equal(differ.leftOut, "Left out of the test: 85 °C (1 failure). A level needs two failures for a shape of its own.");
  // No verdict words.
  for (const c of [same, differ]) assert.doesNotMatch(`${c.words} ${c.detail}`, /\b(Yes|No|OK|Perhaps)\b/);
});

test("meanAtUse and lifeLineFor: the MTTF's two-sided interval and the median or B10 line", async () => {
  const { meanAtUse, lifeLineFor } = await import("./altFrame.js");
  assert.deepEqual(meanAtUse({ mean_life: { value: 330538, ci: [112538, 970829], level: 0.9 } }),
    { value: 330538, ci: [112538, 970829], level: 0.9 });
  assert.equal(meanAtUse({ mean_life: null }), null);
  assert.equal(meanAtUse({ mean_life: { value: Infinity } }), null);
  const along = { stress: [300, 310, 320], life: [9, 8, 7], lower: [5, 4, 3], upper: [12, 11, 10], level: 0.9,
    quantiles: { level: 0.9, bound: "lower", b10: { life: [4, null, 2], lower: [2, null, 1] } } };
  const tested = [{ stress: 320, b10: 2, b50: 6 }];
  const b10 = lifeLineFor(along, "b10", tested);
  assert.deepEqual(b10.line, { stress: [300, 320], life: [4, 2], lower: [2, 1], level: 0.9, bound: "lower" });
  assert.deepEqual(b10.points, [{ stress: 320, life: 2 }]);
  assert.equal(lifeLineFor(along, "eta").line, along);
  assert.equal(lifeLineFor(along, "b50", tested), null);
  assert.equal(lifeLineFor(null, "b10"), null);
});

test("a temperature typed in °C reads in °C on the charts, not kelvin", () => {
  const stresses = [{ key: "s1", column: "temp_C", label: "Temperature", unit: "K", entered_unit: "°C" }];
  assert.equal(seriesLabel({ label: "Temperature (K)=387.15", stress: [387.15] }, stresses), "Temperature (°C)=114");
  const plot = plotInEnteredUnits({ x_label: "Temperature (K)", lines: [{ stress: [373.15, 387.15], life: [1, 2], secondary: null }],
    points: [{ stress: 387.15, life: 2, secondary: null }], secondary_label: null }, stresses, 0);
  assert.equal(plot.x_label, "Temperature (°C)");
  assert.deepEqual(plot.lines[0].stress, [100, 114]);
  assert.equal(plot.points[0].stress, 114);
  // In kelvin from the start: as the fit gave it.
  const k = [{ key: "s1", label: "Temperature", unit: "K" }];
  assert.equal(seriesLabel({ label: "Temperature (K)=387.15", stress: [387.15] }, k), "Temperature (K)=387.15");
  const same = { x_label: "Temperature (K)", lines: [] };
  assert.equal(plotInEnteredUnits(same, k, 0), same);
});
