import test from "node:test";
import assert from "node:assert/strict";
import {
  cvmCheck, duanePoints, fittedToData, growingCheck, logSlope, mtbfWords, planViews, recurrentAnswer, recurrentTabs,
  resolveRecurrentTab, systemsCheck, trendCheck,
  dataText, effectTone, ratioCiText, familyOf, growthReading, orderedParams, paramLabel, pct, perUnit, ratioText, repairTitle,
} from "./recurrentResults.js";

test("paramLabel: plain names with the unit, per model", () => {
  const ca = { model: { id: "crow_amsaa" }, unit: "Hours" };
  assert.equal(paramLabel(ca, "alpha"), "Scale α (hours)");
  assert.equal(paramLabel(ca, "beta"), "Shape β");
  // Duane's alpha is its shape, not a scale.
  assert.equal(paramLabel({ model: { id: "duane" }, unit: "hours" }, "alpha"), "Growth shape α");
  assert.equal(paramLabel({ model: { id: "hpp" }, unit: "hours" }, "lambda"), "Failure rate λ (per hour)");
  const grp = { family: "renewal", model: { id: "grp_i" }, unit: "hours" };
  assert.equal(paramLabel(grp, "q"), "Restoration factor q");
  assert.equal(paramLabel({ family: "renewal", model: { id: "ari" }, baseline: { id: "crow_amsaa" } }, "rho"),
    "Repair efficiency ρ");
  assert.equal(paramLabel({ family: "regression", baseline: { id: "crow_amsaa" }, unit: "days" }, "alpha"),
    "Scale α (days)");
  assert.equal(paramLabel(ca, "mystery"), "mystery");
});

test("orderedParams: shape before scale, restoration first", () => {
  const ca = { model: { id: "crow_amsaa" }, params: [{ name: "alpha" }, { name: "beta" }] };
  assert.deepEqual(orderedParams(ca).map((p) => p.name), ["beta", "alpha"]);
  const grp = { family: "renewal", model: { id: "grp_i" }, params: [{ name: "alpha" }, { name: "beta" }, { name: "q" }] };
  assert.deepEqual(orderedParams(grp).map((p) => p.name), ["q", "beta", "alpha"]);
});

test("growthReading: the verdict and the interval that decides it", () => {
  const r = {
    growth: "deteriorating",
    growth_basis: { symbol: "β", no_trend: 1, ci: [1.44, 2.95], estimate: 2.06 },
  };
  assert.deepEqual(growthReading(r), {
    title: "Deteriorating",
    text: "β's 95% interval, 1.44–2.95, is wholly above 1: failures are accelerating.",
  });
  const flat = { growth: "stable", growth_basis: { symbol: "β", no_trend: 1, ci: [0.8, 1.3] } };
  assert.match(growthReading(flat).text, /includes 1/);
  const params = { from_params: true, growth: "improving", growth_basis: { symbol: "β", no_trend: 1, ci: null, estimate: 0.7 } };
  assert.match(growthReading(params).text, /built from parameters/);
  // A fit that gives no interval (Duane) says so, not "built from parameters".
  assert.match(growthReading({ ...params, from_params: false }).text, /this fit gives no interval/);
  assert.equal(growthReading({ growth: null }), null);
});

test("small words", () => {
  assert.equal(perUnit("Hours"), "hour");
  assert.equal(perUnit("flights"), "flights");
  assert.equal(ratioText(2.164), "×2.2");
  assert.equal(ratioText(1.0334), "×1.03");
  assert.equal(ratioCiText([1.012, 1.056]), "1.01–1.06");
  assert.equal(effectTone("lower"), "success");
  assert.equal(effectTone("higher"), "warning");
  assert.equal(effectTone("unclear"), "neutral");
  assert.equal(repairTitle("partial"), "Partial repair");
  assert.equal(pct(0.793), "79%");
  assert.equal(pct(null), "—");
  assert.equal(dataText({ n_systems: 4, n_events: 30 }), "4 systems, 30 failures");
  assert.equal(dataText({ n_systems: null }), null);
  assert.equal(familyOf({}), "nhpp");
});

// ---- The model frame ---------------------------------------------------------

const observed = { x: [100, 200, 300, 400], mcf: [1, 1.5, 2, 2.25] };
const crow = {
  family: "nhpp", model: { id: "crow_amsaa", name: "Crow-AMSAA (NHPP)" }, unit: "Hours",
  n_systems: 4, n_events: 30, growth: "deteriorating",
  growth_basis: { parameter: "beta", symbol: "β", estimate: 2.06, no_trend: 1, ci: [1.44, 2.95] },
  params: [{ name: "alpha", value: 1881 }, { name: "beta", value: 2.06, ci: [1.44, 2.95] }],
  mtbf: 323.4, demonstrated_mtbf: { lower: 229.9, confidence: 0.9 },
  mcf: { observed, fitted: { x: [0, 50, 100, 400], mcf: [0, 0.2, 1, 2.25] } },
  trend_tests: [{ test: "Laplace", p_value: 0.0009, significant: true, trend: "increasing" }],
};
const names = (tabs) => tabs.map((t) => t.label);

test("recurrentTabs: only the tabs that apply, in order", () => {
  assert.deepEqual(names(recurrentTabs(crow, { modelId: "m1" })),
    ["Failures over time", "Calculator", "Plan ahead", "Diagnostics", "Data"]);
  // Not saved (the fit wizard, a share page): no server tools, so no Plan ahead.
  assert.deepEqual(names(recurrentTabs(crow)), ["Failures over time", "Calculator", "Diagnostics", "Data"]);
  const pi = { ...crow, family: "regression", coefficients: [{ name: "site: B", ratio: 2 }] };
  assert.deepEqual(names(recurrentTabs(pi, { modelId: "m1" })),
    ["Failures over time", "Effects", "Calculator", "Plan ahead", "Diagnostics", "Data"]);
  const params = { from_params: true, model: { id: "crow_amsaa" }, mcf: { observed: null, fitted: {} } };
  assert.equal(fittedToData(params), false);
  assert.deepEqual(names(recurrentTabs(params, { modelId: "m1", paramsOnly: true })),
    ["Failures over time", "Calculator", "Plan ahead", "Data"]);
});

test("planViews: next failure, growth projection, overhaul where each applies", () => {
  assert.deepEqual(planViews(crow, { modelId: "m1" }).map((v) => v.value), ["projection", "overhaul"]);
  const grp = { ...crow, family: "renewal", next_failure: { units: [{ system: "A" }] } };
  assert.deepEqual(planViews(grp, { modelId: "m1" }).map((v) => v.value), ["next", "projection"]);
  assert.deepEqual(planViews(grp).map((v) => v.value), ["next"]);
  assert.deepEqual(planViews({ ...crow, from_params: true }, { modelId: "m1", paramsOnly: true }).map((v) => v.value),
    ["overhaul"]);
});

test("resolveRecurrentTab: ids, names and the old tab ids", () => {
  const tabs = recurrentTabs(crow, { modelId: "m1" });
  assert.deepEqual(resolveRecurrentTab(tabs, null), { tab: "failures", view: null });
  assert.deepEqual(resolveRecurrentTab(tabs, "diag"), { tab: "diag", view: null });
  assert.deepEqual(resolveRecurrentTab(tabs, "Plan ahead"), { tab: "plan", view: null });
  assert.deepEqual(resolveRecurrentTab(tabs, "cause"), { tab: "failures", view: "cause" });
  assert.deepEqual(resolveRecurrentTab(tabs, "overhaul"), { tab: "plan", view: "overhaul" });
  // A tab this model doesn't have opens the first.
  assert.deepEqual(resolveRecurrentTab(tabs, "cov"), { tab: "failures", view: null });
});

test("recurrentAnswer: the verdict, the shape, MTBF now and the data", () => {
  assert.deepEqual(recurrentAnswer(crow, { saved: "saved now" }), [
    "Deteriorating", "β 2.06 (95% 1.44–2.95)", "MTBF now 323 hours (≥ 230 at 90%)", "4 systems, 30 failures", "saved now",
  ]);
  assert.equal(mtbfWords({ ...crow, demonstrated_mtbf: null, mtbf_ci: [195, 577], rates_at: "x" }),
    "MTBF now 323 hours (95% 195–577), average system");
  // No bounds from the fit (Duane): the value alone, never "—–—".
  assert.equal(mtbfWords({ ...crow, demonstrated_mtbf: { lower: null }, mtbf_ci: [null, null] }), "MTBF now 323 hours");
  const grp = {
    family: "renewal", unit: "hours", n_systems: 4, n_events: 30, repair_test: { verdict: "partial" },
    restoration: { effectiveness: 0.79, effectiveness_ci: [0.78, 0.81] },
    next_failure: { units: [{ system: "CMP-4", median: 91.3 }] },
  };
  assert.deepEqual(recurrentAnswer(grp), [
    "Partial repair", "repairs remove 79% of the age (95% 78%–81%)", "next failure: CMP-4 in about 91.3 hours (median)",
    "4 systems, 30 failures",
  ]);
  const hpp = { model: { id: "hpp" }, from_params: true, mtbf: 500, unit: "hours" };
  assert.deepEqual(recurrentAnswer(hpp), ["Constant failure rate", "MTBF at the horizon 500 hours", "made from parameters"]);
});

test("trendCheck: a trend is a finding for a growth model, a fault for a constant rate", () => {
  assert.equal(trendCheck(crow).tone, "good");
  assert.match(trendCheck(crow).words, /^Yes, it's rising/);
  assert.equal(trendCheck({ ...crow, model: { id: "hpp" } }).tone, "bad");
  const flat = { ...crow, trend_tests: [{ test: "Laplace", p_value: 0.4, significant: false, trend: "no trend" }] };
  assert.equal(trendCheck(flat).tone, "caveat");
  assert.equal(trendCheck({ ...flat, model: { id: "hpp" } }).tone, "good");
  assert.equal(trendCheck({ trend_tests: [] }), null);
});

test("the Duane plot: cumulative MTBF over the data's span, and its slope", () => {
  const d = duanePoints(crow);
  assert.deepEqual(d.observed.x, [100, 200, 300, 400]);
  assert.deepEqual(d.observed.y, [100, 400 / 3, 150, 400 / 2.25]);
  // The fitted curve starts at the first failure, not at 0.
  assert.deepEqual(d.fitted.x, [100, 400]);
  assert.ok(logSlope(d.observed) > 0);
  assert.equal(logSlope({ x: [1, 2], y: [1, 2] }), null);
  assert.match(growingCheck(crow).words, /^No, it's getting worse: failures are accelerating \(β's 95% interval, 1.44–2.95, is wholly above 1\)\. The cumulative MTBF rises/);
  assert.match(growingCheck({ mcf: crow.mcf }).words, /^Yes: the time between failures is getting longer/);
});

test("cvmCheck and systemsCheck", () => {
  assert.equal(cvmCheck({ gof_test: { p_value: 0.9, adequate: true, n_boot: 40 } }).tone, "good");
  assert.equal(cvmCheck({ gof_test: { p_value: 0.01, adequate: false } }).tone, "bad");
  assert.equal(cvmCheck({ gof_test: { p_value: null, reason: "Skipped" } }).words, "Skipped");
  assert.equal(cvmCheck({}), null);
  const rows = [{ system: "P-06", failures: 13, expected: 8.84, excess: 4.16 }, { system: "P-01", failures: 4, expected: 3.5, excess: 0.5 }];
  assert.match(systemsCheck({ system_residuals: rows }).words, /^P-06 fails most beyond the model: 13 failures where it expects 8\.8/);
  assert.match(systemsCheck({ system_residuals: [{ ...rows[1] }, rows[1]] }).words, /^No system stands out/);
  assert.equal(systemsCheck({ system_residuals: [rows[0]] }), null);
});
