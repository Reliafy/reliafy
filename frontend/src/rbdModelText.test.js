import { test } from "node:test";
import assert from "node:assert/strict";
import { blockLine, hoursPerUnit, lifeLine, modelMean, repairLine, unitAbbr } from "./components/rbdModelText.js";

const exp = (r) => ({ distribution: "Exponential", distribution_id: "exponential", params: [{ name: "failure_rate", value: r }] });
const wb = (a, b) => ({ distribution: "Weibull", distribution_id: "weibull", params: [{ name: "alpha", value: a }, { name: "beta", value: b }] });
const ln = (mu, s) => ({ distribution: "Lognormal", distribution_id: "lognormal", params: [{ name: "mu", value: mu }, { name: "sigma", value: s }] });

test("a block's one line", () => {
  assert.equal(blockLine({ model: exp(5e-7), repair: exp(1 / 8) }, "Hours", true), "λ 5e-7/h · MTTR 8 h");
  assert.equal(lifeLine(wb(4000, 2), "Hours"), "Weibull · η 4,000 h · β 2");
  assert.equal(blockLine({ model: wb(4000, 2), instant_repair: true }, "Hours", true), "Weibull · η 4,000 h · β 2 · instant repair");
  assert.equal(blockLine({ model: exp(1e-3) }, "Cycles", false), "λ 0.001/cycle");
});

test("means", () => {
  assert.ok(Math.abs(modelMean(wb(1000, 1)) - 1000) < 1e-6);
  assert.ok(Math.abs(modelMean(wb(1, 2)) - Math.sqrt(Math.PI) / 2) < 1e-9);
  assert.equal(repairLine(ln(Math.log(12), 0.5), "Hours"), "MTTR 13.6 h");
});

test("units", () => {
  assert.equal(unitAbbr("Hours"), "h");
  assert.equal(hoursPerUnit("Days"), 24);
  assert.equal(hoursPerUnit("Cycles"), null);
});
