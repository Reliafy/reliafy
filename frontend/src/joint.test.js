import { test } from "node:test";
import assert from "node:assert/strict";
import {
  covariateParts, guessLifetimeColumns, guessReadingColumns, jointBlockLine, jointBlockModel, medianText,
  paramGroups, parseReadings, readingsText, riskTone,
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
