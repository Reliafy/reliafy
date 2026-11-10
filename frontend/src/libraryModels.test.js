import { test } from "node:test";
import assert from "node:assert/strict";
import {
  curve, density, distributionWords, leftOutWords, lgamma, pickerDetail, rangeText, recordIdOf, recordPath, sig, sourcePath, unitsMeaning, asGivenWords,
  usableSource, whyNot, componentIdOf, componentPath, isComponentId,
} from "./libraryModels.js";

test("the three levels' addresses", () => {
  assert.equal(sourcePath("nrc-inl-2020"), "/models/library/nrc-inl-2020");
  assert.equal(recordPath("nrc-inl-2020:mov-fto"), "/models/library/nrc-inl-2020/mov-fto");
  assert.equal(recordIdOf("nrc-inl-2020", "mov-fto"), "nrc-inl-2020:mov-fto");
});

test("which records can be a model or a prior, in words", () => {
  assert.equal(whyNot({ kind: "rate", basis: "field_data" }), null);
  // Every input a record needs is a covariate (Derryn, 9 Nov 2026): a probability per demand is a
  // model or a prior with its demands a year; a handbook rate a model with its environment.
  assert.equal(whyNot({ kind: "per_demand" }), null);
  assert.equal(whyNot({ kind: "per_demand" }, "prior"), null);
  assert.equal(whyNot({ kind: "rate", basis: "prediction_model" }), null);
  assert.match(whyNot({ kind: "rate", basis: "prediction_model" }, "prior"), /no spread/);
  assert.match(whyNot({ kind: "covariate_model" }), /Attach it at a position/);
});

test("a component's address", () => {
  assert.ok(isComponentId("nrc-inl-2020:component:motor-driven-pump-normally-standby"));
  assert.ok(!isComponentId("nrc-inl-2020:mdp-fts-ns"));
  assert.equal(componentPath("nrc-inl-2020:component:motor-driven-pump-normally-standby"),
    "/models/library/nrc-inl-2020/components/motor-driven-pump-normally-standby");
  assert.equal(componentIdOf("nrc-inl-2020", "pipe-service-water"), "nrc-inl-2020:component:pipe-service-water");
});

test("the pickers: the default library, the records hidden, and a record's detail line", () => {
  const handbook = { id: "mil-hdbk-217f-n2", basis: "prediction_model", kinds: { rate: 236 } };
  const field = { id: "nrc-inl-2020", basis: "field_data", kinds: { rate: 211, per_demand: 89 } };
  assert.equal(usableSource(handbook), false);
  assert.equal(usableSource(field), true);
  assert.equal(usableSource(null), false);
  assert.equal([handbook, field].find(usableSource), field);
  assert.equal(leftOutWords({}), null);
  assert.equal(leftOutWords(undefined), null);
  assert.match(leftOutWords({ prediction_model: 236 }), /^Handbook rates and covariate models are left out/);
  assert.match(leftOutWords({ prediction_model: 1, per_demand: 2 }), /Handbook rates.*per demand/);
  assert.equal(pickerDetail({ mean: 9.13e-5, units: "per hour (running)", p05: 7.34e-7, p95: 3.33e-4, source: "NRC/INL 2020" }),
    "9.13e−5 per hour (running) · 5–95%: 7.34e−7 – 3.33e−4 · NRC/INL 2020");
  // A base rate with no range given says none, rather than "5–95%: —".
  assert.equal(pickerDetail({ mean: 3.8e-9, units: "per hour (running)", source: "MIL-HDBK-217F N2" }), "3.80e−9 per hour (running) · MIL-HDBK-217F N2");
});

test("the words and the density", () => {
  assert.equal(sig(0.000343), "3.43e−4");
  assert.equal(rangeText({ p05: 7.8e-5, p95: 0.000762 }), "7.80e−5 – 7.62e−4");
  assert.match(unitsMeaning("rate", "per hour (calendar)"), /calendar hour \(/);
  // "Failures per hour", never "per hours" (UX review, Nov 2026).
  assert.equal(unitsMeaning("rate", "per hour"), "Failures per hour: the mean life is one over the rate.");
  assert.match(unitsMeaning("rate", "per hour (running)"), /^Failures per hour of operation:/);
  assert.match(unitsMeaning("rate", "per hour per foot of pipe (calendar)"), /per foot of pipe/);
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

test("asGivenWords converts a per-hour rate to the handbook's per million hours", () => {
  const rec = { kind: "rate", units: { value: "per_hour", as_given: "failures per million hours" } };
  assert.equal(asGivenWords(rec, 3.7e-9), "0.0037 failures per million hours");
  assert.equal(asGivenWords({ kind: "rate", units: { as_given: "per hour" } }, 1e-6), null);
  assert.equal(asGivenWords({ kind: "life", units: { as_given: "failures per million hours" } }, 5), null);
});
