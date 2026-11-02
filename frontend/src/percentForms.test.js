import { test } from "node:test";
import assert from "node:assert/strict";
import { PERCENT_FORMS, readPercents } from "./percentForms.js";
import { RANGE_MESSAGE } from "./percent.js";

test("failure finding: 99 is 0.99, and 0.99 is questioned, never taken as 0.99%", () => {
  assert.deepEqual(readPercents("failureFinding", { availability: "99" }).fractions, { availability: 0.99 });
  const r = readPercents("failureFinding", { availability: "0.99" });
  assert.equal(r.ready, false);
  assert.equal(r.checks.availability.message, "Did you mean 99%?");
  assert.equal(readPercents("failureFinding", { availability: "0.99%" }).fractions.availability, 0.0099);
});

test("test planning: 150 gets a message in percent, not in fractions", () => {
  const r = readPercents("demonstration", { reliability: "150", confidence: "95" });
  assert.equal(r.ready, false);
  assert.equal(r.checks.reliability.message, RANGE_MESSAGE);
  const ok = readPercents("demonstration", { reliability: "95", confidence: "90", design: "", producerRisk: "" });
  assert.equal(ok.ready, true);
  assert.deepEqual(ok.fractions, { reliability: 0.95, confidence: 0.9, design: null, producerRisk: null });
});

test("demonstration: a B-life of 1% failed is normal, not questioned", () => {
  const r = readPercents("demonstration", { bLife: "1", confidence: "90" });
  assert.equal(r.ready, true);
  assert.equal(r.fractions.bLife, 0.01);
});

test("every test-planning tab questions a fractional confidence", () => {
  for (const form of ["demonstration", "sequential", "lifeTest", "acceleratedTest", "comparison"]) {
    const r = readPercents(form, { confidence: "0.9" });
    assert.equal(r.ready, false, form);
    assert.equal(r.checks.confidence.suggestion, "90", form);
    assert.equal(readPercents(form, { confidence: "90" }).fractions.confidence, 0.9, form);
  }
});

test("sequential: reliabilities and the producer's risk convert", () => {
  const r = readPercents("sequential", { rTarget: "90", rGood: "97", confidence: "90", producerRisk: "10" });
  assert.equal(r.ready, true);
  assert.deepEqual(r.fractions, { rTarget: 0.9, rGood: 0.97, confidence: 0.9, producerRisk: 0.1 });
});

test("life test: a share failed can be 100%", () => {
  assert.equal(readPercents("lifeTest", { share: "100" }).fractions.share, 1);
  assert.equal(readPercents("lifeTest", { share: "120" }).ready, false);
});

test("comparison: power converts; a small drop to detect is fine", () => {
  const r = readPercents("comparison", { power: "80", confidence: "95", drop: "1" });
  assert.deepEqual(r.fractions, { power: 0.8, confidence: 0.95, drop: 0.01 });
});

test("RBD targets, intervals and the cheapest design's floor", () => {
  assert.equal(readPercents("rbdTargets", { target: "99.9" }).fractions.target, 0.999);
  assert.equal(readPercents("rbdTargets", { target: "0.999" }).ready, false);
  assert.equal(readPercents("rbdIntervals", { availability: "99.9" }).fractions.availability, 0.999);
  assert.equal(readPercents("rbdCheapest", { floor: "" }).ready, true);
  assert.equal(readPercents("rbdCheapest", { floor: "0.9995" }).ready, false);
});

test("calculators: reliability and confidence level", () => {
  assert.deepEqual(readPercents("calculator", { reliability: "90", level: "95" }).fractions, { reliability: 0.9, level: 0.95 });
  assert.equal(readPercents("calculator", { reliability: "0.9" }).ready, false);
  assert.equal(readPercents("degradation", { reliability: "90", confidence: "90" }).ready, true);
  assert.equal(readPercents("tvc", { level: "95" }).fractions.level, 0.95);
  assert.equal(readPercents("perDemand", { confidence: "0.95" }).ready, false);
  assert.equal(readPercents("rbdDesignLife", { reliability: "90" }).fractions.reliability, 0.9);
});

test("requirement and common-cause β take small percentages", () => {
  assert.equal(readPercents("requirement", { bLife: "0.1" }).fractions.bLife, 0.001);
  assert.equal(readPercents("ccf", { beta: "1" }).fractions.beta, 0.01);
});

test("only the fields on screen count", () => {
  const r = readPercents("demonstration", { reliability: "0.5", bLife: "10", confidence: "90" }, ["bLife", "confidence"]);
  assert.equal(r.ready, true);
  assert.equal("reliability" in r.checks, false);
});

test("every form names only known option keys", () => {
  for (const [form, fields] of Object.entries(PERCENT_FORMS)) {
    for (const [k, o] of Object.entries(fields)) {
      for (const key of Object.keys(o)) assert.ok(["optional", "fractionCheck", "allowMax"].includes(key), `${form}.${k}.${key}`);
    }
  }
});
