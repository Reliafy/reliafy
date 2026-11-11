// The Data list's row menu: which fit each kind of dataset offers (#261), and
// a dataset's two parts as its page shows them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { datasetActions, datasetMeta, datasetParts, fitOptions, splitText, usableDatasets, usableFor } from "./datasetFit.js";

test("each dataset offers the fits that take it alone", () => {
  assert.deepEqual(fitOptions({ id: "a", tags: ["Non-repairable", "Covariates"] }),
    [{ label: "Non-repairable model with covariates", to: "/models/new?dataset=a" }]);
  assert.equal(fitOptions({ id: "b", tags: ["Repairable"] })[0].to, "/models/recurrent/new?dataset=b");
  assert.deepEqual(fitOptions({ id: "c", tags: ["Measurements"] }).map((x) => x.label), ["Degradation model"]);
  // Life data with its measurements (or both in one table): condition and life first, from the one dataset.
  assert.deepEqual(fitOptions({ id: "d", tags: ["Non-repairable", "Measurements"] }), [
    { label: "Condition and life model", to: "/models/joint/new?dataset=d" },
    { label: "Non-repairable model", to: "/models/new?dataset=d" },
    { label: "Degradation model", to: "/models/degradation?dataset=d" },
  ]);
});

const column = (name, dtype = "float64") => ({ name, dtype });

// Start and stop rows with a failure flag (the pump bearings sample): several
// rows per unit, so the profile once read them as readings and offered only
// a degradation fit.
const startStop = {
  id: "sample-ds-pump-load", tags: ["Non-repairable", "Time-varying covariates"],
  columns: [column("pump", "object"), column("start_h", "int64"), column("stop_h", "int64"), column("censored", "int64"), column("load_pct", "int64")],
  profile: { repeated_units: { column: "pump", kind: "time_varying", start: "start_h", stop: "stop_h" }, split: null },
};

test("data with covariates that change over time offers a non-repairable fit", () => {
  const life = { label: "Fit a non-repairable model with covariates that change over time", to: "/models/new?dataset=sample-ds-pump-load" };
  assert.deepEqual(datasetActions(startStop), { primary: life, secondary: null });
  // From the tag alone (an older profile that called the rows readings).
  const older = { ...startStop, profile: { repeated_units: { column: "pump", kind: "degradation" } } };
  assert.deepEqual(datasetActions(older).primary, life);
  // Or from the profile alone (covariates fixed within each unit).
  assert.equal(datasetActions({ ...startStop, tags: ["Non-repairable", "Covariates"] }).primary.label, life.label);
  // Readings in the same table as well: degradation second.
  assert.deepEqual(datasetActions({ ...startStop, tags: [...startStop.tags, "Measurements"] }).secondary,
    { label: "Fit a degradation model", to: "/models/degradation?dataset=sample-ds-pump-load" });
  assert.deepEqual(fitOptions(startStop), [{ label: "Non-repairable model with covariates that change over time", to: "/models/new?dataset=sample-ds-pump-load" }]);
  assert.equal(usableFor("life", startStop), true);
});

test("the dataset page's other actions are unchanged", () => {
  const t = (tags, kind, extra = {}) => datasetActions({ id: "x", tags, profile: kind ? { repeated_units: { column: "u", kind } } : {}, ...extra });
  assert.deepEqual(t(["Measurements"], "degradation"), { primary: { label: "Fit a degradation model", to: "/models/degradation?dataset=x" }, secondary: null });
  assert.deepEqual(t(["Repairable"], "recurrent").primary, { label: "Fit a repairable model", to: "/models/recurrent/new?dataset=x" });
  assert.deepEqual(t(["Non-repairable"], null).primary, { label: "Fit a model", to: "/models/new?dataset=x" });
  assert.equal(t(["Non-repairable", "Measurements"], null, { measurements: { columns: [] } }).primary.to, "/models/joint/new?dataset=x");
});

test("each new-model flow offers only the datasets it can use", () => {
  const life = { tags: ["Non-repairable"] };
  const lifeCov = { tags: ["Non-repairable", "Covariates"] };
  const rep = { tags: ["Repairable", "Covariates"] };
  const reads = { tags: ["Measurements"] };
  const both = { tags: ["Non-repairable", "Measurements"] };
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("life", d)), [true, true, false, false, true]);
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("repairable", d)), [false, false, true, false, false]);
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("accelerated", d)), [false, true, false, false, false]);
  // Degradation reads a dataset's measurements part, or its table of readings.
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("degradation", d)), [false, false, false, true, true]);
  assert.deepEqual([life, reads, both].map((d) => usableFor("joint", d)), [false, false, true]);
  assert.equal(usableFor("life", {}), true); // no tags from the server: not hidden
  assert.equal(usableDatasets("repairable", [life, rep]).length, 1);
});

test("a dataset's parts: life data with its measurements, readings alone, or one table", () => {
  const two = {
    n_rows: 40, n_columns: 3, columns: [column("pump", "object"), column("age"), column("c", "int64")],
    preview_columns: ["pump", "age", "c"], preview: [["P1", 10, 0]], tags: ["Non-repairable", "Measurements"],
    measurements: { n_rows: 300, n_columns: 3, columns: [column("pump", "object"), column("age"), column("vib")],
                    preview_columns: ["pump", "age", "vib"], preview: [["P1", 0, 2.1]] },
  };
  const p = datasetParts(two);
  assert.equal(p.life.n_rows, 40);
  assert.deepEqual(p.measurements.columns, ["pump", "age", "vib"]);
  assert.equal(p.measurements.types.vib, "float64");
  assert.equal(p.readingsOnly, false);
  assert.equal(datasetMeta(two), "40 rows · 3 columns · 300 readings");

  const reads = { n_rows: 300, n_columns: 3, columns: two.measurements.columns, preview_columns: ["pump", "age", "vib"],
                  preview: [], tags: ["Measurements"] };
  const r = datasetParts(reads);
  assert.equal(r.life, null);
  assert.equal(r.measurements.n_rows, 300);
  assert.equal(r.readingsOnly, true);
  assert.equal(datasetMeta(reads), "300 readings");

  const one = { n_rows: 300, n_columns: 4, columns: [], preview_columns: ["pump", "age", "vib", "c"], preview: [],
                tags: ["Non-repairable", "Measurements"], profile: { split: { unit: "pump", n_units: 40 } } };
  const o = datasetParts(one);
  assert.equal(o.measurements, null);
  assert.equal(o.combined, true);
  assert.equal(datasetParts(null).life, null);
});

test("the split notice says what goes where", () => {
  const plan = { unit: "pump", age: "age", censor: "outcome", life_columns: ["load"], measurement_columns: ["vib"],
                 n_units: 40, n_readings: 314, n_without_outcome: 0 };
  assert.equal(splitText(plan),
    "This table holds life data and readings together: 40 units, 314 readings. Split it into Life data "
    + "(pump, age, outcome, load) and Measurements (pump, age, vib)?");
  assert.match(splitText({ ...plan, n_without_outcome: 2 }), /2 units have no outcome flag/);
  assert.equal(splitText(null), "");
});
