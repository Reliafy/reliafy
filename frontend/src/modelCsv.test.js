// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { bLivesCsvRows, curveCsvRows, paramsCsvRows } from "./modelCsv.js";
import { csvFileName, toCsv } from "./csv.js";

const curve = {
  x: [0, 100, 200],
  sf: [1, 0.9512294245007140, 0.8187307530779818],
  ff: [0, 0.048770575499286, 0.1812692469220182],
  hf: [0, 0.001, 0.002],
  Hf: [0, 0.05, 0.2],
  df: [0, 0.00095, 0.0016],
};

test("the curve has time, every function and the bounds, units and confidence in the names", () => {
  const rows = curveCsvRows({
    series: [{ label: "Model", curve }], unit: "hours",
    band: { fn: "sf", level: 90, x: curve.x, lower: [1, 0.93, 0.79] },
  });
  assert.deepEqual(rows[0], [
    "Time (hours)", "Reliability R(t) (0 to 1)", "Probability of failure F(t) (0 to 1)",
    "Hazard rate h(t) (per hour)", "Cumulative hazard H(t)", "Density f(t) (per hour)",
    "Reliability R(t) (0 to 1), 90% lower bound",
  ]);
  // Full precision: the model's numbers, not the 4 figures on screen.
  assert.deepEqual(rows[2], [100, 0.951229424500714, 0.048770575499286, 0.001, 0.05, 0.00095, 0.93]);
  assert.equal(rows.length, 4);
});

test("a two-sided band gives a lower and an upper column; a band on another grid is interpolated", () => {
  const rows = curveCsvRows({
    series: [{ label: "Model", curve }], unit: "",
    band: { fn: "ff", level: 95, credible: true, x: [0, 200], lower: [0, 0.1], upper: [0, 0.3] },
  });
  assert.deepEqual(rows[0].slice(-2), [
    "Probability of failure F(t) (0 to 1), 95% credible two-sided, lower",
    "Probability of failure F(t) (0 to 1), 95% credible two-sided, upper",
  ]);
  assert.equal(rows[0][0], "Time");
  assert.deepEqual(rows[2].slice(-2), [0.05, 0.15]);
});

test("several covariate combinations stack under a Combination column; missing values are blank", () => {
  const rows = curveCsvRows({
    series: [{ label: "load=1", curve }, { label: "load=2", curve: { x: [0, 50], sf: [1, null] } }],
    unit: "cycles", given: 30,
  });
  assert.equal(rows[0][0], "Combination");
  assert.equal(rows[0][1], "Further time (cycles), having survived 30");
  assert.equal(rows.length, 1 + 3 + 2);
  assert.deepEqual(rows[5].slice(0, 3), ["load=2", 50, ""]);
});

test("B-lives carry the estimate and the one-sided lower bound at the level", () => {
  const rows = bLivesCsvRows({
    rows: [{ label: "B10", p: 0.1, value: 1234.5678912, lower: 1000.123 }, { label: "B50", p: 0.5, value: 5000 }],
    unit: "hours", level: 90,
  });
  assert.deepEqual(rows, [
    ["B-life", "Fraction failed (0 to 1)", "Estimate (hours)", "Lower bound (hours), 90% one-sided"],
    ["B10", 0.1, 1234.5678912, 1000.123],
    ["B50", 0.5, 5000, ""],
  ]);
  const insp = bLivesCsvRows({ rows: [{ label: "B10", p: 0.1, between: [10, 20] }], unit: "days", level: 90 });
  assert.deepEqual(insp[0].slice(3, 5), ["Between, from (days)", "Between, to (days)"]);
  assert.deepEqual(insp[1], ["B10", 0.1, "", 10, 20, ""]);
});

test("parameters say the interval's level and that it is two-sided", () => {
  const rows = paramsCsvRows({
    params: [{ name: "alpha", label: "Scale α (hours)", value: 1500.123456789, ci: [1200.5, 1800.25] },
      { name: "beta", label: "Shape β", value: 1.8 }],
    ciLabel: "90%",
  });
  assert.deepEqual(rows[0], ["Parameter", "Name", "Value", "90% two-sided, lower", "90% two-sided, upper"]);
  assert.deepEqual(rows[1], ["Scale α (hours)", "alpha", 1500.123456789, 1200.5, 1800.25]);
  assert.deepEqual(rows[2], ["Shape β", "beta", 1.8, "", ""]);
  assert.equal(paramsCsvRows({ params: [{ name: "a", value: 1, ci: [0, 2] }], ciLabel: "90% credible" })[0][3],
    "90% credible two-sided, lower");
  assert.match(toCsv(rows), /^Parameter,Name,Value/);
});

test("file names drop characters a file can't hold", () => {
  assert.equal(csvFileName('Pumps / "A"', "B-lives"), "Pumps A B-lives.csv");
  assert.equal(csvFileName("", ""), "download.csv");
});

test("each combination's own band fills its rows", () => {
  const band = (lo) => ({ fn: "sf", level: 90, x: curve.x, lower: [1, lo, lo] });
  const rows = curveCsvRows({
    series: [{ label: "a", curve, band: band(0.9) }, { label: "b", curve, band: band(0.8) }], unit: "hours",
  });
  assert.equal(rows[0].at(-1), "Reliability R(t) (0 to 1), 90% lower bound");
  assert.equal(rows[2].at(-1), 0.9);
  assert.equal(rows[5].at(-1), 0.8);
});
