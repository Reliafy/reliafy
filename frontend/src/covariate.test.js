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
    { record: { id: "nswc-11:x", kind: "covariate_model" }, record_id: "nswc-11:x", conditions: {}, cycles_per_hour: "" });
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
