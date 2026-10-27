// The Data list's row menu: which fit each kind of dataset offers (#261), and
// a dataset's two parts as its page shows them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { datasetMeta, datasetParts, fitOptions, splitText, usableDatasets, usableFor } from "./datasetFit.js";

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

const column = (name, dtype = "float64") => ({ name, dtype });

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
