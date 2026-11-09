import test from "node:test";
import assert from "node:assert/strict";
import {
  defaultText, fmtRate, groupInputs, isCovariateId, limitProblem, limitText, lineConditions, missingInputs, modeRows,
  modelShape, perCycle, resultLine, unitShort, valuesForServer,
} from "./covariate.js";
import { predictionAssign } from "./explorerModels.js";
import { conditionsLabel, handbooksText, isCovariateLine, lineChange, predictionResult } from "./predictionPane.js";
import { linesForServer } from "./predictions.js";

const T = { key: "T_O", name: "T_O", kind: "number", label: "Temperature", unit: "°C", default: 60, default_basis: "neutral",
  limits: [{ min: -273.15, severity: "refuse", why: "below absolute zero" }, { min: 60, max: 260, severity: "warn", page: "7-17", why: "Figure 7.5" }] };
const N = { key: "n", name: "n", kind: "number", label: "Speed", unit: "rpm", limits: [{ min: 0, exclusive: true, severity: "refuse" }] };
const C = { key: "service", name: "service", kind: "choice", label: "Service", default: "uniform", default_basis: "neutral",
  choices: [{ code: "uniform", label: "Uniform" }, { code: "shock", label: "Shock" }] };

test("an input's limits, the handbook's range with its page first", () => {
  assert.equal(limitText(T), "Handbook range 60 to 260 °C (p. 7-17) · must be at least -273.15 °C");
  assert.equal(limitText(N), "Must be more than 0 rpm");
});

test("a value past a limit says which, as it's typed", () => {
  assert.equal(limitProblem(T, ""), null);
  assert.equal(limitProblem(T, "100"), null);
  assert.deepEqual(limitProblem(T, "300"), { severity: "warn", text: "Outside the handbook’s range (60 to 260 °C, p. 7-17): Figure 7.5." });
  assert.equal(limitProblem(N, "0").severity, "refuse");
  assert.equal(limitProblem(N, "abc").text, "Not a number.");
  assert.equal(limitProblem(C, "shock"), null);
});

test("defaults say where they come from", () => {
  assert.equal(defaultText(T), "Default 60 °C (no effect)");
  assert.equal(defaultText(C), "Default Uniform (no effect)");
  assert.equal(defaultText(N), "");
});

test("values go to the server as numbers and codes, blanks left out", () => {
  assert.deepEqual(valuesForServer({ T_O: "120", n: " ", service: "shock" }, [T, N, C]), { T_O: 120, service: "shock" });
  assert.deepEqual(missingInputs([T, N, C], { T_O: "1" }).map((i) => i.key), ["n"]);
});

test("inputs group by what they are: design, use, environment", () => {
  const g = groupInputs([{ ...T, role: "environment" }, { ...N, key: "seal.n", group: "Seals", role: "use" }, { ...C, role: "design" }]);
  assert.deepEqual(g.map((x) => [x.label, x.inputs.map((i) => i.key)]), [["Design", ["service"]], ["Use", ["seal.n"]], ["Environment", ["T_O"]]]);
});

test("units, rates and shapes in words", () => {
  assert.equal(unitShort("per_million_cycles"), "per 10⁶ cycles");
  assert.ok(perCycle("per_million_operations") && !perCycle("per_million_hours"));
  assert.equal(fmtRate(NaN), "—");
  assert.equal(fmtRate(Infinity), "—");
  assert.equal(fmtRate(0.123456), "0.123");
  assert.equal(resultLine({ total: 2.5, unit: "per_million_hours" }), "2.5 failures per million hours");
  assert.equal(modelShape({ modes: [{ factors: 6 }] }), "Base rate × 6 condition factors");
  assert.equal(modelShape({ modes: [{}, {}] }), "Sum of 2 parts or failure modes");
});

test("the source page lists each component's parts or failure modes", () => {
  const rows = modeRows([{ id: "nswc-11:pump", name: "Pump", covariate: { rate_unit: "per_million_hours", equation: "10-2", modes: [
    { key: "casing", name: "Casing", base: "0.01", factors: 0 },
    { key: "seals", name: "Seals", base: "its own model", uses: "nswc-11:seal-static", uses_name: "Seal, static", factors: 0 },
    { key: "fd", name: "Fluid driver", base: "from the inputs", factors: 4 }] } }]);
  assert.deepEqual(rows.map((r) => [r.component, r.mode, r.base, r.factors]), [
    ["Pump", "Casing", "0.01 per 10⁶ h", "0"], ["Pump", "Seals", "Its own model: Seal, static", "—"],
    ["Pump", "Fluid driver", "From the inputs", "4"]]);
});

test("an NSWC-11 line sends its conditions and cycles, never a quality factor", () => {
  assert.ok(isCovariateId("nswc-11:bearing-rolling-load-rating") && !isCovariateId("mil-hdbk-217f-n2:x"));
  const line = { reference: "B1", record: { id: "nswc-11:bearing-rolling-load-rating" }, quality_factor: "3",
    conditions: { L_S: "5000", n: "", bearing_type: "roller" }, cycles_per_hour: "" };
  assert.deepEqual(lineConditions(line), { conditions: { L_S: 5000, bearing_type: "roller" } });
  assert.deepEqual(predictionAssign([line]), { B1: { record_id: "nswc-11:bearing-rolling-load-rating", conditions: { L_S: 5000, bearing_type: "roller" } } });
  assert.deepEqual(linesForServer([{ name: "Bearing", quantity: 2, record_id: line.record.id, quality_factor: "3", conditions: { L_S: 1 }, cycles_per_hour: "30" }]),
    [{ name: "Bearing", quantity: 2, record_id: line.record.id, conditions: { L_S: 1 }, cycles_per_hour: 30 }]);
  assert.ok(isCovariateLine(line));
  assert.equal(conditionsLabel(line), "Conditions (2 set)…");
  assert.equal(conditionsLabel({}), "Conditions…");
  assert.deepEqual(lineChange({ record: { id: "nswc-11:x", kind: "covariate_model" } }),
    { record: { id: "nswc-11:x", kind: "covariate_model" }, record_id: "nswc-11:x", conditions: {}, cycles_per_hour: "", environment: "", quality: "" });
});

test("the result names the handbooks, the Navy's statement and the lines needing conditions", () => {
  const out = predictionResult({ failure_rate_per_million_hours: 3, counts: { assigned: 1, lines: 2 },
    handbooks: [{ short_name: "NSWC-11", lines: ["Bearing"] }], disclaimer: "Not approved.",
    needs_conditions: [{ name: "Seal", quantity: 2 }] });
  assert.equal(out.handbooks, "NSWC-11: 1 line");
  assert.equal(out.disclaimer, "Not approved.");
  assert.deepEqual(out.needsConditions, ["Seal ×2"]);
  assert.equal(handbooksText([]), "");
});

import { bindSummary, bindingFromParam, bindingParam, bindingToSave, boundNodes, cleanConditions, initialFix, initialValues } from "./covariate.js";
import { bindingOf } from "./explorerModels.js";
import { paneFromQuery, setPaneQuery } from "./tablePane.js";

const D = { key: "L_S", label: "Load rating", kind: "number", role: "design", unit: "lbf", limits: [] };
const U = { key: "n", label: "Speed", kind: "number", role: "use", unit: "rpm", limits: [] };
const E = { key: "T_O", label: "Temperature", kind: "number", role: "environment", unit: "°C", default: 60, default_basis: "neutral", limits: [] };

test("fixing at a position: design ticked for NSWC-11, nothing for ALT and PH, the saved binding's when there is one", () => {
  assert.deepEqual(initialFix("nswc", [D, U, E]), { L_S: true, n: false, T_O: false });
  assert.deepEqual(initialFix("alt", [D, U, E]), { L_S: false, n: false, T_O: false });
  assert.deepEqual(initialFix("ph", [D, U], { fixed: { n: 900 } }), { L_S: false, n: true });
  assert.deepEqual(initialValues([D, E], { fixed: { L_S: 5000 } }), { L_S: "5000", T_O: "60" });
});

test("the binding saved: the ticked values, roles for ALT and PH, and what's ticked without a value", () => {
  const got = bindingToSave({ source: "alt", ref: "m1", inputs: [D, U, E], fix: { L_S: true, n: true }, values: { L_S: "5000", n: "" }, roles: { n: "environment" } });
  assert.deepEqual(got.binding, { source: "alt", ref: "m1", fixed: { L_S: 5000 }, roles: { L_S: "design", n: "environment", T_O: "environment" } });
  assert.deepEqual(got.missing, ["Speed"]);
  assert.equal(bindingToSave({ source: "nswc", ref: "r", inputs: [D], fix: {}, values: {} }).binding.roles, undefined);
  assert.equal(bindSummary("nswc", [D, U], { L_S: true, n: true }), "Every covariate fixed: it's saved as a constant-rate model at this position.");
  assert.match(bindSummary("alt", [D, U, E], { L_S: true }), /^1 of 3 fixed here; 2 set where it's used/);
});

test("a binding's address, and the pane it opens", () => {
  assert.equal(bindingParam("nswc", "nswc-11:bearing"), "nswc:nswc-11:bearing");
  assert.deepEqual(bindingFromParam("nswc:nswc-11:bearing"), { source: "nswc", ref: "nswc-11:bearing" });
  assert.equal(bindingFromParam("x:y"), null);
  const q = setPaneQuery(new URLSearchParams(), "bind", "p1", { rbd: "alt:m1" });
  assert.deepEqual(paneFromQuery(q), { kind: "bind", id: "p1", bind: "alt:m1" });
});

test("which rows can fix covariates at their position", () => {
  assert.deepEqual(bindingOf({ model_type: "alt_model", model_id: "a1" }), { source: "alt", ref: "a1" });
  assert.deepEqual(bindingOf({ model_type: "covariate_record", model_id: "nswc-11:x" }), { source: "nswc", ref: "nswc-11:x" });
  assert.deepEqual(bindingOf({ model_type: "model", model_id: "m", model: { covariates: ["load"] } }), { source: "ph", ref: "m" });
  assert.deepEqual(bindingOf({ model_type: "model", model_id: "e", source: { binding: { source: "nswc", ref: "nswc-11:y" } } }), { source: "nswc", ref: "nswc-11:y" });
  assert.equal(bindingOf({ model_type: "model", model_id: "w", model: { kind: "Weibull" } }), null);
});

test("the diagram's Use and Environment values as the server keeps them", () => {
  assert.deepEqual(cleanConditions([{ name: " Temperature ", role: "environment", unit: "°C", value: "40" }, { name: "", value: "1" }, { name: "Duty", value: "" }]),
    [{ name: "Temperature", role: "environment", unit: "°C", value: 40 }]);
  assert.equal(boundNodes({ nodes: [{ data: { model: { kind: "bound" } } }, { data: { model: {} } }] }).length, 1);
});

import { bindingForRecord, covariatesToSave, isNeeded, missingInputs as missingOf, neededInputs, recordAnswer } from "./covariate.js";
import { handbookConditionsLabel, handbookCovariates } from "./predictions.js";

const CLOCK = { key: "clock", kind: "choice", role: "use", default: "operating", choices: [{ code: "calendar" }, { code: "operating" }] };
const HOURS = { key: "running_hours_per_year", kind: "number", role: "use", needed_if: { clock: ["calendar"] } };
const LEN = { key: "length_ft", kind: "number", role: "design" };

test("a record's covariates: running hours only when the clock is changed", () => {
  assert.equal(isNeeded(HOURS, [CLOCK, HOURS], {}), false);
  assert.equal(isNeeded(HOURS, [CLOCK, HOURS], { clock: "calendar" }), true);
  assert.deepEqual(neededInputs([CLOCK, HOURS], {}).map((i) => i.key), ["clock"]);
  assert.deepEqual(missingOf([CLOCK, HOURS, LEN], { clock: "calendar" }).map((i) => i.key), ["running_hours_per_year", "length_ft"]);
  assert.deepEqual(missingOf([CLOCK, HOURS], {}), []);
  // What's saved: the typed ones asked for (a running hours typed then the clock put back is dropped).
  assert.deepEqual(covariatesToSave([CLOCK, HOURS, LEN], { clock: "", running_hours_per_year: "4380", length_ft: "120" }), { length_ft: 120 });
  assert.deepEqual(covariatesToSave([CLOCK, HOURS], { clock: "calendar", running_hours_per_year: "4380" }), { clock: "calendar", running_hours_per_year: 4380 });
});

test("a library record's binding at a position, and what's ticked", () => {
  assert.deepEqual(bindingForRecord({ id: "nswc-11:bearing", kind: "covariate_model" }), { source: "nswc", ref: "nswc-11:bearing" });
  assert.deepEqual(bindingForRecord({ id: "nrc-inl-2020:pipe-sws-els", kind: "rate" }), { source: "library", ref: "nrc-inl-2020:pipe-sws-els" });
  assert.deepEqual(bindingForRecord({ id: "nrc-inl-2020:component:pipe-service-water" }), { source: "component", ref: "nrc-inl-2020:component:pipe-service-water" });
  assert.deepEqual(bindingFromParam("library:nrc-inl-2020:aov-fto"), { source: "library", ref: "nrc-inl-2020:aov-fto" });
  assert.deepEqual(bindingFromParam("component:nrc-inl-2020:component:x"), { source: "component", ref: "nrc-inl-2020:component:x" });
  // Design ticked by default for a library record (the pipe's length), use left to the RBD.
  assert.deepEqual(initialFix("library", [LEN, CLOCK]), { length_ft: true, clock: false });
  const got = bindingToSave({ source: "library", ref: "r", inputs: [LEN, CLOCK, HOURS], fix: { length_ft: true, running_hours_per_year: true }, values: { length_ft: "50" } });
  assert.deepEqual(got.binding, { source: "library", ref: "r", fixed: { length_ft: 50 } }); // running hours not asked for: not saved
  assert.match(bindSummary("library", [LEN, CLOCK, HOURS], { length_ft: true }, {}), /^1 of 2 fixed here/);
});

test("a record's answer in words, the answer first", () => {
  const rate = recordAnswer({ failure_rate: 6.89e-8, clock: "calendar", bounds: { p05: 2.71e-10, p95: 2.65e-7 }, mean_time_to_failure: 14512000, assumptions: ["100 feet of pipe."] });
  assert.match(rate.big, /^6\.89e−8 failures per calendar hour$/);
  assert.ok(rate.sub.some((x) => /5–95% across plants/.test(x)) && rate.sub.includes("100 feet of pipe."));
  const pd = recordAnswer({ probability: 3.04e-4, failure_rate: 3.47e-7, clock: "calendar", covariates: { demands_per_year: 10 }, bounds_rate: { p05: 2.7e-7, p95: 4.3e-7 } });
  assert.match(pd.big, /per demand/);
  assert.match(pd.sub[0], /at 10 demands a year/);
  assert.match(recordAnswer({ probability: 3.04e-4, bounds: {} }).sub.at(-1), /demands a year/);
  const comp = recordAnswer({ component_id: "c", probability: 0.0101, rare_event_sum: 0.0101, bounds: { p05: 0.003, p95: 0.021 },
    rate_per_calendar_hour: 1.15e-6, modes: [{ counted: true, mode: "Fails to start", trigger: "demand", mean: 5.9e-4, unit: "per demand", exposure: 12, exposure_unit: "demands", probability: 0.007 },
      { counted: false, mode: "Alt" }] });
  assert.match(comp.big, /chance it fails over the period/);
  assert.equal(comp.modes.length, 1);
  assert.equal(recordAnswer({ total: 1, modes: [] }), null); // NSWC-11: its own view
});

test("a handbook line's own environment and grade", () => {
  assert.deepEqual(handbookCovariates({ environment: "NS", quality: "" }), { environment: "NS" });
  assert.equal(handbookConditionsLabel({ record: { quality_factors: { levels: [] } } }), "Grade and environment…");
  assert.equal(handbookConditionsLabel({ record: {}, environment: "NS" }), "Environment (set)…");
  assert.deepEqual(linesForServer([{ name: "IC", quantity: 1, record_id: "mil:x", quality: "B", environment: "" }]),
    [{ name: "IC", quantity: 1, record_id: "mil:x", quality: "B" }]);
});
