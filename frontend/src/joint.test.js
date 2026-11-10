import { test } from "node:test";
import assert from "node:assert/strict";
import {
  covariateParts, fleetAnswer, guessLifetimeColumns, lifeLeftNumber, riskText, sortRiskRows, guessReadingColumns, jointBlockLine, jointBlockModel, medianText,
  paramGroups, parseReadings, readingsText, riskTone, sortColumn,
} from "./joint.js";

const col = (name, dtype = "float64", values = null) => ({ name, dtype, values });

test("lifetimes: id, age, flag and the covariates left over", () => {
  const g = guessLifetimeColumns([
    col("pump", "object"), col("hours"), col("failed", "int64", { 0: 10, 1: 30 }), col("load"),
  ]);
  assert.equal(g.id, "pump");
  assert.equal(g.x, "hours");
  assert.equal(g.c, "failed");
  assert.equal(g.invert, true); // "failed" is 1 = failed
  assert.deepEqual(g.covariates, ["load"]);
});

test("readings: id, age and value", () => {
  const g = guessReadingColumns([col("unit_id", "object"), col("age"), col("vibration")]);
  assert.deepEqual(g, { id: "unit_id", age: "age", value: "vibration" });
  const h = guessReadingColumns([col("serial", "object"), col("hours"), col("mm")]);
  assert.deepEqual(h, { id: "serial", age: "hours", value: "mm" });
});

test("covariate parts: both by default, else each list", () => {
  assert.deepEqual(covariateParts([{ name: "a", risk: true, path: true }]), { covariates: ["a"] });
  assert.deepEqual(
    covariateParts([{ name: "a", risk: true, path: false }, { name: "b", risk: true, path: true },
      { name: "c", risk: false, path: false }]),
    { covariates: ["a", "b"], hazard_covariates: ["a", "b"], path_covariates: ["b"] },
  );
});

test("typed readings parse, sort and refuse nonsense", () => {
  assert.deepEqual(parseReadings("40 3.1\n0: 2\n20, 2.5").readings, [[0, 2], [20, 2.5], [40, 3.1]]);
  assert.match(parseReadings("40").error, /age and a value/);
  assert.match(parseReadings("-1 2").error, /since new/);
  assert.equal(readingsText([[0, 2], [40, 3.1]]), "0 2\n40 3.1");
});

test("median remaining life: never infinite", () => {
  assert.equal(medianText({ median_reached: false, median_remaining: null }), "not reached");
  assert.equal(medianText({ median_reached: true, median_remaining: 23.4 }, "Days"), "23.4 days");
  // One precision down a column: not "9.99 days" beside "12 days".
  assert.equal(medianText({ median_remaining: 9.9944 }, "Days"), "10.0 days");
  assert.equal(medianText({ median_remaining: 11.96 }, "Days"), "12.0 days");
  assert.equal(lifeLeftNumber(1234.5), "1,230");
  assert.equal(riskTone(0.6), "danger");
  assert.equal(riskTone(0.2), "warning");
  assert.equal(riskTone(0.01), "success");
});

test("block model and line", () => {
  const m = jointBlockModel({ id: "m1", name: "Pumps", unit: "Days" }, { id: "P3" });
  assert.equal(m.kind, "joint");
  assert.equal(m.unit, "Days"); // the time unit, as every block model's
  assert.deepEqual(m.joint_unit, { id: "P3" });
  assert.equal(jointBlockLine(m), "Condition and life · unit P3");
  assert.equal(jointBlockLine({ joint_unit: { age: 50, markers: [[0, 1]] } }, "d"), "Condition and life · age 50 d, 1 reading");
});

test("parameters grouped by part", () => {
  const g = paramGroups([
    { part: "path", part_label: "Reading path", name: "a" },
    { part: "path", part_label: "Reading path", name: "b" },
    { part: "link", part_label: "Link", name: "marker_effect" },
  ]);
  assert.deepEqual(g.map((x) => [x.label, x.rows.length]), [["Reading path", 2], ["Link", 1]]);
});

test("a chance of failing is never shown as certain", () => {
  assert.equal(riskText(1), "> 99.9%");
  assert.equal(riskText(0.9996), "> 99.9%");
  assert.equal(riskText(0.9958), "99.5%");
  assert.equal(riskText(0.6375), "64%");
  assert.equal(riskText(0.0004), "< 0.1%");
  assert.equal(riskText(0), "< 0.1%");
  assert.equal(riskText(null), "—");
});

test("the risk table is sorted by the named column, ties by median life left", () => {
  // The review's rows: P38 sat above P8 with both showing "99%" for 90 days
  // and P8 higher at 30. Now the 90-day column shows the difference.
  const rows = [
    { id: "P35", risk: [0.8715, 1, 1], median_remaining: 11.96 },
    { id: "P38", risk: [0.6302, 0.9942, 1], median_remaining: 22.4 },
    { id: "P6", risk: [0.9178, 1, 1], median_remaining: 9.99 },
    { id: "P8", risk: [0.6375, 0.9915, 1], median_remaining: 21.8 },
    { id: "P1", risk: [0.1, 0.3, 0.6], median_reached: false, median_remaining: null },
  ];
  assert.deepEqual(sortRiskRows(rows).map((r) => r.id), ["P6", "P35", "P38", "P8", "P1"]);
  assert.deepEqual(rows.map((r) => riskText(r.risk[1])).slice(0, 4), ["> 99.9%", "99.4%", "> 99.9%", "99.1%"]);
  // Shown alike: the shorter median life left first.
  const tied = [{ id: "a", risk: [0, 0.5], median_remaining: 30 }, { id: "b", risk: [0, 0.5], median_remaining: 20 }];
  assert.deepEqual(sortRiskRows(tied).map((r) => r.id), ["b", "a"]);
  assert.deepEqual(sortRiskRows(rows, 0).map((r) => r.id), ["P6", "P35", "P8", "P38", "P1"]);
});

test("a class's fleet in one line: how many positions, how many with risk now, and the highest", () => {
  const horizons = { labels: ["30 days", "90 days", "365 days"], values: [30, 90, 365] };
  const pump = (name, risk) => ({ position: { name }, scored: !!risk, risk });
  assert.equal(sortColumn(horizons.labels), 1);
  assert.equal(sortColumn(["30 days"]), 0);
  assert.equal(fleetAnswer(null), "");
  assert.equal(
    fleetAnswer({ positions: 2, scored: 2, horizons, members: [pump("Pump 1", [0.28, 0.65, 0.997]), pump("Pump 4", [0.11, 0.32, 0.9])] }),
    "2 positions · all with risk now · highest: Pump 1, 65% in the next 90 days",
  );
  // Members that can't be scored come after: the count says how many can, and the first scored one is the highest.
  assert.equal(
    fleetAnswer({ positions: 1200, scored: 1, horizons, members: [pump("", [0.0004, 0.9995, 1]), pump("Spare", null)] }),
    "1,200 positions · 1 with risk now · highest: (no name), > 99.9% in the next 90 days",
  );
  assert.equal(fleetAnswer({ positions: 1, scored: 0, horizons, members: [pump("Valve", null)] }), "1 position · no risk now yet");
});
