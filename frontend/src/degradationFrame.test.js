// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bLives, bandLevel, bandWords, degradationAnswer, degradationTabs, hasResiduals, itemsWords, meanAnswer,
  pathParams, pathRanking, reliabilityAt, resolveDegradationTab, routesVerdict, scatterCheck, timeAtReliability,
} from "./degradationFrame.js";

// A straight-line curve from 1 at t = 0 to 0 at t = 1000, with a band 0.1
// either side (clipped), at 90%.
const x = Array.from({ length: 101 }, (_, i) => i * 10);
const sf = x.map((t) => 1 - t / 1000);
const curves = {
  x, sf, alpha_ci: 0.1,
  lower: sf.map((v) => Math.max(0, v - 0.1)),
  upper: sf.map((v) => Math.min(1, v + 0.1)),
};
const unit = (id, residuals, censored = false) => ({
  id, censored, scatter: { x: [100, 200, 300], y: [1, 2, 3] }, line: { x: [100, 300], y: [1, 3] },
  pseudo_failure_time: 800, ...(residuals ? { residuals } : {}),
});
const results = {
  kind: "degradation", threshold: 8, unit: "Hours", measurement_unit: "mm", n_units: 3, n_measurements: 9,
  path_model: { id: "linear", name: "Linear", n_params: 2, param_names: ["a", "b"] },
  path_selection: [
    { id: "linear", name: "Linear", aicc: -240 },
    { id: "quadratic", name: "Quadratic", aicc: -224 },
    { id: "power", name: "Power", aicc: -191 },
  ],
  measurement_var: 0.01,
  path_param_mean: [0.6, 0.0012],
  units: [unit("A", [0.05, -0.1, 0.05]), unit("B", [0.02, 0.01, -0.03]), unit("C", [0, 0.3, -0.3], true)],
  life_model: {
    distribution: "Weibull", distribution_id: "weibull",
    params: [{ name: "alpha", value: 6345 }, { name: "beta", value: 7.5 }], mean: 5957.8, curves,
  },
};
const labels = (tabs) => tabs.map((t) => t.label);

test("a degradation model gets the approved tabs, leaving out what has nothing to show", () => {
  assert.deepEqual(labels(degradationTabs(results, { modelId: "m1" })),
    ["Paths", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  // A shared page (no model to ask) still has the residuals and the path comparison.
  assert.deepEqual(labels(degradationTabs(results)),
    ["Paths", "Calculator", "Model characteristics", "Diagnostics", "Data"]);
  // An older fit with a chosen path, no residuals, shared: nothing to check.
  const old = { ...results, path_selection: null, units: [unit("A")] };
  assert.deepEqual(labels(degradationTabs(old)), ["Paths", "Calculator", "Model characteristics", "Data"]);
  // No curve and no mean: the paths and the data only.
  const bare = { ...old, life_model: { distribution: "Weibull", mean: null, curves: null } };
  assert.deepEqual(labels(degradationTabs(bare)), ["Paths", "Data"]);
});

test("old tab names open the tab that holds them now", () => {
  const tabs = degradationTabs(results, { modelId: "m1" });
  assert.equal(resolveDegradationTab(tabs, "rel"), "calc");
  assert.equal(resolveDegradationTab(tabs, "Induced life"), "diag");
  assert.equal(resolveDegradationTab(tabs, "chars"), "chars");
  assert.equal(resolveDegradationTab(tabs, "nonsense"), "paths");
  assert.equal(resolveDegradationTab(tabs, null), "paths");
});

test("the curve is read at a time and at a reliability, with the band's ends", () => {
  const r = reliabilityAt(curves, 250);
  assert.ok(Math.abs(r.value - 0.75) < 1e-9);
  assert.ok(Math.abs(r.lower - 0.65) < 1e-9);
  assert.ok(Math.abs(r.upper - 0.85) < 1e-9);
  assert.deepEqual(reliabilityAt(curves, 5000), { value: null, lower: null, upper: null, beyond: true });
  assert.equal(reliabilityAt(curves, -1), null);
  assert.equal(reliabilityAt(curves, "x"), null);

  const t = timeAtReliability(curves, 0.9);
  assert.ok(Math.abs(t.value - 100) < 1e-9);
  assert.ok(Math.abs(t.lower - 0) < 1e-9); // the lower curve starts at 0.9
  assert.ok(Math.abs(t.upper - 200) < 1e-9);
  assert.equal(timeAtReliability(curves, 1), null);

  const b = bLives(curves);
  assert.deepEqual(b.map((r) => r.label), ["B1", "B5", "B10", "B50"]);
  assert.ok(Math.abs(b[3].value - 500) < 1e-9);
  assert.equal(bandLevel(curves), 90);
  assert.equal(bandLevel({}), 90);
  assert.equal(bandWords({ value: 500, lower: 400, upper: 600 }, 90), "90% band 400–600");
  assert.equal(bandWords({ value: 500, lower: 400, upper: null }, 95), "≥ 400 at 95%");
});

test("the answer line: the path, the life, B10 with its band, the mean and the data", () => {
  const parts = degradationAnswer(results, { saved: "saved just now" });
  assert.deepEqual(parts, [
    "Linear path to 8 mm",
    "Weibull life",
    "B10 100 hours (90% band 0–200)",
    "mean 5,960 hours",
    "3 items, 9 readings, 1 not yet at the threshold",
    "saved just now",
  ]);
  assert.equal(itemsWords({ n_units: 1, units: [] }), "1 item");
  // No finite mean: left out of the line.
  const noMean = { ...results, life_model: { ...results.life_model, mean: null } };
  assert.ok(!degradationAnswer(noMean).some((p) => p.startsWith("mean")));
  assert.equal(meanAnswer(noMean).kind, "none");
});

test("the path's parameters by name, falling back to letters", () => {
  assert.deepEqual(pathParams(results), [{ name: "a", value: 0.6 }, { name: "b", value: 0.0012 }]);
  assert.deepEqual(pathParams({ path_param_mean: [1, 2, 3] }).map((p) => p.name), ["a", "b", "c"]);
});

test("do the two routes to a life agree?", () => {
  const close = routesVerdict({ available: true, median: 5000, life_median: 5200 }, "Hours");
  assert.equal(close.tone, "good");
  assert.match(close.words, /^Yes: the median 5,000 hours by the path model, 5,200 hours by the crossing times/);
  const far = routesVerdict({ available: true, median: 5000, life_median: 8000 }, "Hours");
  assert.equal(far.tone, "caveat");
  assert.match(far.words, /^Not closely/);
  assert.equal(routesVerdict({ available: false }), null);
  assert.equal(routesVerdict({ available: true, median: 5000, life_median: null }), null);
});

test("which path shape fits best?", () => {
  const r = pathRanking(results);
  assert.equal(r.tone, "good");
  assert.equal(r.rows[0].name, "Linear");
  assert.ok(r.rows[0].current);
  assert.equal(r.words, "Linear fits best; Quadratic and Power are clearly worse.");
  assert.equal(pathRanking({ ...results, path_selection: [results.path_selection[0]] }), null);
});

test("do the readings scatter evenly about each path?", () => {
  assert.ok(hasResiduals(results));
  const s = scatterCheck(results); // σ = 0.1: two readings at ±0.3 are beyond 2.5 σ
  assert.equal(s.odd, 2);
  assert.equal(s.n, 9);
  assert.equal(s.tone, "caveat");
  assert.match(s.words, /^2 of 9 readings sit more than 2.5 σ from their item's path \(σ = 0.1 mm\)/);
  const tidy = { ...results, units: results.units.slice(0, 2) };
  assert.equal(scatterCheck(tidy).tone, "good");
  assert.equal(scatterCheck({ ...results, units: [unit("A")] }), null);
  assert.equal(scatterCheck({ ...tidy, measurement_var: 0 }).tone, null);
});
