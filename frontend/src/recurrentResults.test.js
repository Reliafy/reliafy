import test from "node:test";
import assert from "node:assert/strict";
import {
  cvmCheck, duanePoints, fittedToData, growingCheck, logSlope, mtbfWords, planViews, recurrentAnswer, recurrentTabs,
  resolveRecurrentTab, systemsCheck, trendCheck, poissonUpperTail, scaledParam,
  beyondDataWords, boundsWords, restoresRange, dataText, effectTone, fitSystemsHref, ratioCiText, familyOf, growthReading, orderedParams, paramLabel, pct, perUnit, ratioText, repairTitle, terminationText,
} from "./recurrentResults.js";

test("paramLabel: plain names with the unit, per model", () => {
  const ca = { model: { id: "crow_amsaa" }, unit: "Hours" };
  assert.equal(paramLabel(ca, "alpha"), "Scale α (hours)");
  assert.equal(paramLabel(ca, "beta"), "Shape β");
  // Duane's alpha is its shape, not a scale.
  assert.equal(paramLabel({ model: { id: "duane" }, unit: "hours" }, "alpha"), "Growth shape α");
  assert.equal(paramLabel({ model: { id: "hpp" }, unit: "hours" }, "lambda"), "Failure rate λ (per hour)");
  const grp = { family: "renewal", model: { id: "grp_i" }, unit: "hours" };
  assert.equal(paramLabel(grp, "q"), "Share of age kept q (a repair restores 1 − q)");
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

test("growthReading: the evidence and what it means, no verdict", () => {
  const r = {
    growth: "deteriorating",
    growth_basis: { symbol: "β", no_trend: 1, ci: [1.44, 2.95], estimate: 2.06 },
  };
  assert.deepEqual(growthReading(r), {
    title: "Shape of the failure rate",
    text: "β 2.06 (95% two-sided range 1.44–2.95). β above 1 means failures come faster as time goes on; below 1, slower.",
  });
  const flat = { growth: "stable", growth_basis: { symbol: "β", no_trend: 1, ci: [0.8, 1.3] } };
  assert.doesNotMatch(growthReading({ ...flat, growth_basis: { ...flat.growth_basis, estimate: 1.0 } }).text, /improv|deteriorat|no clear trend/i);
  const params = { from_params: true, growth: "improving", growth_basis: { symbol: "β", no_trend: 1, ci: null, estimate: 0.7 } };
  assert.match(growthReading(params).text, /built from parameters/);
  assert.match(growthReading(params).text, /^β 0\.7 /);
  // A fit that gives no interval (Duane) says so, not "built from parameters".
  assert.match(growthReading({ ...params, from_params: false }).text, /this fit gives no range/);
  assert.equal(growthReading({ growth: null }), null);
});

test("small words", () => {
  assert.equal(perUnit("Hours"), "hour");
  assert.equal(perUnit("flights"), "flights");
  assert.equal(ratioText(2.164), "×2.2");
  assert.equal(ratioText(1.0334), "×1.03");
  assert.equal(ratioCiText([1.012, 1.056]), "1.01–1.06");
  // No good/bad colour on a covariate's effect.
  assert.equal(effectTone("lower"), "neutral");
  assert.equal(effectTone("higher"), "neutral");
  assert.equal(effectTone("unclear"), "neutral");
  assert.equal(repairTitle("partial"), "Partial repair");
  assert.equal(pct(0.793), "79%");
  assert.equal(pct(null), "—");
  assert.equal(dataText({ n_systems: 4, n_events: 30 }), "4 systems, 30 failures");
  assert.equal(dataText({ n_systems: null }), null);
  assert.equal(dataText({ n_systems: 1, n_events: 8, subset: { systems: ["CV-03"], of: 7 } }), "CV-03 alone (1 of 7 systems), 8 failures");
  assert.equal(dataText({ n_systems: 2, n_events: 9, subset: { systems: ["A", "B"], of: 7 } }), "2 of 7 systems, 9 failures");
  assert.equal(fitSystemsHref("m1", ["CV-03 GB"]), "/models/recurrent/new?from=m1&system=CV-03+GB");
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
  trend_tests: [{ id: "laplace", test: "Laplace", statistic: 3.31, p_value: 0.0009, significant: true, trend: "increasing" }],
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
  // Deteriorating: the overhaul first; a growth test: the projection first.
  assert.deepEqual(planViews(crow, { modelId: "m1" }).map((v) => v.value), ["overhaul", "replace", "projection"]);
  assert.deepEqual(planViews({ ...crow, growth: "improving" }, { modelId: "m1" }).map((v) => v.value),
    ["projection", "overhaul", "replace"]);
  const grp = { ...crow, family: "renewal", next_failure: { units: [{ system: "A" }] } };
  assert.deepEqual(planViews(grp, { modelId: "m1" }).map((v) => v.value), ["next", "projection"]);
  assert.deepEqual(planViews(grp).map((v) => v.value), ["next"]);
  assert.deepEqual(planViews({ ...crow, from_params: true }, { modelId: "m1", paramsOnly: true }).map((v) => v.value),
    ["overhaul", "replace"]);
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
    "Crow-AMSAA (NHPP)", "β 2.06 (95% two-sided 1.44–2.95)", "MTBF now 323 hours (≥ 230 at 90%, one-sided)", "4 systems, 30 failures", "saved now",
  ]);
  assert.equal(mtbfWords({ ...crow, demonstrated_mtbf: null, mtbf_ci: [195, 577], rates_at: "x" }),
    "MTBF now 323 hours (95% two-sided 195–577), at the fleet's average covariates");
  // A covariate model with levels: each level's MTBF, not an average system.
  assert.equal(mtbfWords({ ...crow, rates_at: "x", rates_by_group: [
    { label: "site Coastal", mtbf: 627.2 }, { label: "site Inland", mtbf: 263.2 }] }),
  "MTBF now site Coastal 627 hours, site Inland 263 hours");
  // No bounds from the fit (Duane): the value alone, never "—–—".
  assert.equal(mtbfWords({ ...crow, demonstrated_mtbf: { lower: null }, mtbf_ci: [null, null] }), "MTBF now 323 hours");
  const grp = {
    family: "renewal", unit: "hours", n_systems: 4, n_events: 30, repair_test: { verdict: "partial" },
    restoration: { effectiveness: 0.79, effectiveness_ci: [0.78, 0.81] },
    next_failure: { units: [{ system: "CMP-4", median: 91.3 }] },
  };
  assert.deepEqual(recurrentAnswer(grp), [
    "Partial repair", "repairs restore 79% of the age gained (95% two-sided range 78%–81%)",
    "next failure: CMP-4 in about 91.3 hours (median)", "4 systems, 30 failures",
  ]);
  // The headline follows the interval: never "As bad as old" for an estimate
  // well inside it.
  const maybe = { ...grp, ci_level: 0.9, repair_test: { verdict: "maybe_minimal" },
    restoration: { effectiveness: 0.52, effectiveness_ci: [-0.14, 0.7] } };
  const words = recurrentAnswer(maybe);
  assert.equal(words[0], "Partial repair, can't rule out as bad as old");
  // A share can't be below 0% (as bad as old): the range stops there and says it reaches it.
  assert.equal(words[1], "repairs restore 52% of the age gained (90% two-sided range 0%–70%, reaching as bad as old)");
  const both = recurrentAnswer({ ...maybe, restoration: { effectiveness: 0.6, effectiveness_ci: [-0.2, 1.3] } });
  assert.equal(both[1], "repairs restore 60% of the age gained (90% two-sided range 0%–100%, from as bad as old to as good as new)");
  const hpp = { model: { id: "hpp" }, from_params: true, mtbf: 500, unit: "hours" };
  assert.deepEqual(recurrentAnswer(hpp), ["Constant failure rate", "MTBF at the horizon 500 hours", "made from parameters"]);
});

test("trendCheck: each test's statistic and p-value, no verdict or tone", () => {
  const c = trendCheck(crow);
  assert.equal(c.tone, undefined);
  assert.match(c.words, /^Laplace trend test: U = 3\.31, p < 0\.001/);
  assert.match(c.words, /how often a pattern this strong arises by chance/);
  assert.doesNotMatch(c.words, /accelerat|slowing|rising|No clear change|constant-rate model/);
  const hpp = trendCheck({ ...crow, model: { id: "hpp" } });
  assert.equal(hpp.tone, undefined);
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
  assert.match(growingCheck(crow).words, /^β 2\.06 \(95% two-sided range 1\.44–2\.95\)\. β above 1 means .* The cumulative MTBF rises as time goes on \(Duane slope/);
  assert.doesNotMatch(growingCheck(crow).words, /getting worse|Yes|No,/);
  assert.match(growingCheck({ mcf: crow.mcf }).words, /^The cumulative MTBF rises as time goes on/);
});

test("cvmCheck and systemsCheck", () => {
  assert.equal(cvmCheck({ gof_test: { p_value: 0.9, adequate: true, n_boot: 40 } }).tone, "good");
  assert.equal(cvmCheck({ gof_test: { p_value: 0.01, adequate: false } }).tone, "bad");
  assert.equal(cvmCheck({ gof_test: { p_value: null, reason: "Skipped" } }).words, "Skipped");
  assert.equal(cvmCheck({}), null);
  const rows = [{ system: "P-06", failures: 13, expected: 8.84, excess: 4.16 }, { system: "P-01", failures: 4, expected: 3.5, excess: 0.5 }];
  // The counts against expectation and the p-value; never whether anything stands out.
  assert.match(systemsCheck({ system_residuals: rows }).words, /^Largest excess: P-06, 13 failures where the model expects 8\.8 \(p = 0\.11: /);
  const bad = [{ system: "HT-11", failures: 30, expected: 12, excess: 18 }, rows[1]];
  assert.match(systemsCheck({ system_residuals: bad, n_systems: 12 }).words, /^Largest excess: HT-11, 30 failures where the model expects 12 \(p < 0\.001: .*compare it with 0\.0042\)/);
  for (const t of [rows, bad, [{ ...rows[1] }, rows[1]]]) {
    assert.doesNotMatch(systemsCheck({ system_residuals: t }).words, /bad actor|stands? out|Worth a look/);
  }
  assert.equal(systemsCheck({ system_residuals: [rows[0]] }), null);
});

test("poissonUpperTail", () => {
  assert.ok(Math.abs(poissonUpperTail(1, 2) - (1 - Math.exp(-2))) < 1e-12);
  assert.equal(poissonUpperTail(0, 3), 1);
  assert.ok(poissonUpperTail(30, 12) < 1e-4);
});

test("scaledParam: a small rate reads per 1,000 units, never in scientific notation", () => {
  const hpp = { model: { id: "hpp" }, unit: "Hours" };
  const d = scaledParam(hpp, { name: "lambda", value: 9.81e-4, ci: [8e-4, 1.2e-3] });
  assert.equal(d.label, "Failure rate λ (per 1,000 hours)");
  assert.ok(Math.abs(d.value - 0.981) < 1e-9);
  assert.ok(Math.abs(d.ci[0] - 0.8) < 1e-9);
  const cl = scaledParam({ model: { id: "cox_lewis" }, unit: "hours" }, { name: "beta", value: 8.65e-5 });
  assert.equal(cl.label, "Log-linear slope β (per 10,000 hours)");
  // A rate that isn't small, and a parameter that isn't a rate, stay as they are.
  assert.equal(scaledParam(hpp, { name: "lambda", value: 0.5 }).scale, 1);
  assert.equal(scaledParam({ model: { id: "crow_amsaa" } }, { name: "beta", value: 1e-5 }).scale, 1);
});

test("terminationText: says how the record ends", () => {
  const one = { unit: "hours", n_systems: 1, n_events: 12 };
  assert.equal(terminationText({ ...one, termination: { kind: "time", end: 1000 } }), "time-terminated at 1,000 hours");
  assert.equal(terminationText({ ...one, termination: { kind: "failure", end: 940 } }),
    "failure-terminated: ended at the last failure (940 hours)");
  assert.equal(terminationText({ ...one, n_systems: 4, termination: { kind: "failure", end: 940 } }),
    "failure-terminated: each system ends at its last failure");
  assert.equal(terminationText({ ...one, n_systems: 4, termination: { kind: "time", end: 1000 } }),
    "time-terminated: each system to its end of record (the latest 1,000 hours)");
  // A fit saved before: from its warning, else nothing.
  assert.equal(terminationText({ ...one, end_of_observation: 940, warnings: [{ id: "no_record_end" }] }),
    "failure-terminated: ended at the last failure (940 hours)");
  assert.equal(terminationText(one), null);
  // Each system's own end of record, so a record cut short is seen.
  const ends = [{ end: 1096, systems: ["CV-01", "CV-02", "CV-04", "CV-05", "CV-06", "CV-08"] }, { end: 995, systems: ["CV-03"] }];
  assert.equal(terminationText({ ...one, unit: "days", n_systems: 7, termination: { kind: "time", end: 1096, ends } }),
    "time-terminated: 6 systems to 1,096 days; CV-03 to 995 days");
  assert.equal(terminationText({ ...one, unit: "days", n_systems: 7, termination: { kind: "time", end: 1096, ends: [ends[0]] } }),
    "time-terminated: every system to 1,096 days");
  assert.equal(terminationText({ ...one, unit: "days", termination: { kind: "time", end: 995, ends: [ends[1]] } }),
    "time-terminated: CV-03 to 995 days");
  const many = [1, 2, 3, 4].map((k) => ({ end: k * 100, systems: [`S${k}`] }));
  assert.equal(terminationText({ ...one, n_systems: 4, termination: { kind: "time", end: 400, ends: many } }),
    "time-terminated: each system to its own end of record, from 100 hours to 400 hours");
  assert.equal(terminationText({ from_params: true, termination: { kind: "time", end: 1 } }), null);
  // On the answer line, after the data.
  const words = recurrentAnswer({ ...one, model: { id: "crow_amsaa" }, termination: { kind: "time", end: 1000 } });
  assert.deepEqual(words.slice(-2), ["1 system, 12 failures", "time-terminated at 1,000 hours"]);
});

test("restoresRange keeps a restored share inside 0%–100% and names the end it reaches", () => {
  assert.equal(restoresRange({ effectiveness_ci: [-0.14, 0.7] }).words, "0%–70%, reaching as bad as old");
  assert.equal(restoresRange({ effectiveness_ci: [0.3, 1.2] }).words, "30%–100%, reaching as good as new");
  assert.equal(restoresRange({ effectiveness_ci: [0.3, 0.7] }).words, "30%–70%");
  assert.equal(restoresRange({}), null);
});

test("beyondDataWords: an answer past the longest record says how far past", () => {
  assert.equal(beyondDataWords({ data_end: 11800, times: 1.711 }, "hours"),
    "This is 1.7× the longest record in the data (11,800 hours). The data stop there, so the answer assumes the "
    + "fitted trend carries on unchanged past them.");
  assert.equal(beyondDataWords(null), null);
});

test("boundsWords: every bound on the page says its side and method", () => {
  const w = boundsWords({ ci_level: 0.9, params: [{ name: "beta", value: 0.5, ci: [0.3, 0.8] }],
    demonstrated_mtbf: { lower: 94.5, confidence: 0.9, method: "crow" } });
  assert.match(w[0], /90% two-sided, from the fit's information \(Wald/);
  assert.match(w[1], /one-sided lower bound \(the demonstrated MTBF\), by Crow's exact method \(MIL-HDBK-189C\)/);
  const k = boundsWords({ ci_level: 0.9, family: "renewal", model: { id: "grp_i" },
    params: [{ name: "q", value: 0.48, ci: [0.3, 1.14], ci_method: "lr" }] });
  assert.match(k[1], /^Share of age kept q's interval is a profile-likelihood one, so it can run past 0 or 1/);
});
