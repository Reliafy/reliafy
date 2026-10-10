import test from "node:test";
import assert from "node:assert/strict";
import { paramLabel } from "./paramLabels.js";

test("paramLabel: plain names with the diagram's unit (#299)", () => {
  assert.equal(paramLabel("exponential", "failure_rate", "Hours"), "Failure rate λ (per hour)");
  assert.equal(paramLabel("weibull", "alpha", "Hours"), "Scale α (hours)");
  assert.equal(paramLabel("weibull", "beta", "Hours"), "Shape β");
  assert.equal(paramLabel("lognormal", "mu"), "Log-mean μ");
  assert.equal(paramLabel("normal", "sigma", "Cycles"), "Std dev σ (cycles)");
  assert.equal(paramLabel("weibull", "alpha"), "Scale α");
  assert.equal(paramLabel("mystery", "theta", "Hours"), "theta");
});
