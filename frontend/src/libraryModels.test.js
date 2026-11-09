import { test } from "node:test";
import assert from "node:assert/strict";
import { curve, density, distributionWords, lgamma, rangeText, recordIdOf, recordPath, sig, sourcePath, unitsMeaning, whyNot } from "./libraryModels.js";

test("the three levels' addresses", () => {
  assert.equal(sourcePath("nrc-inl-2020"), "/models/library/nrc-inl-2020");
  assert.equal(recordPath("nrc-inl-2020:mov-fto"), "/models/library/nrc-inl-2020/mov-fto");
  assert.equal(recordIdOf("nrc-inl-2020", "mov-fto"), "nrc-inl-2020:mov-fto");
});

test("which records can be a model or a prior, in words", () => {
  assert.equal(whyNot({ kind: "rate", basis: "field_data" }), null);
  assert.match(whyNot({ kind: "per_demand" }), /counts of demands and failures/);
  assert.match(whyNot({ kind: "per_demand" }, "prior"), /counts lives, not demands/);
  assert.match(whyNot({ kind: "rate", basis: "prediction_model" }), /parts count/);
});

test("the words and the density", () => {
  assert.equal(sig(0.000343), "3.43e−4");
  assert.equal(rangeText({ p05: 7.8e-5, p95: 0.000762 }), "7.80e−5 – 7.62e−4");
  assert.match(unitsMeaning("rate", "per hour (calendar)"), /calendar hours/);
  assert.match(unitsMeaning("per_demand"), /each time it's asked to work/);
  assert.equal(distributionWords({ family: "gamma", params: [{ name: "alpha", value: 1.26 }, { name: "beta", value: 7170000 }] }),
    "Gamma (shape α 1.26, rate β 7,170,000)");
  assert.ok(Math.abs(lgamma(5) - Math.log(24)) < 1e-10);
  // A gamma's density integrates to about 1 over its range.
  const g = { family: "gamma", params: [{ name: "alpha", value: 2 }, { name: "beta", value: 1 }] };
  let area = 0;
  for (let x = 0.0005; x < 40; x += 0.001) area += density(g, x) * 0.001;
  assert.ok(Math.abs(area - 1) < 0.01, area);
  const c = curve({ family: "beta", params: [{ name: "alpha", value: 2.48 }, { name: "beta", value: 7220 }] }, 7.8e-5, 0.000762);
  assert.equal(c.x.length, 160);
  assert.ok(c.y.every((v) => v >= 0));
  assert.equal(curve({ family: "point", params: [] }, 1, 2), null);
});
