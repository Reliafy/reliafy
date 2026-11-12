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

test("extraParamView: fit options' extras in plain words", async () => {
  const { extraParamView } = await import("./paramLabels.js");
  const fmt = (v) => String(Math.round(Number(v) * 1000) / 1000);
  assert.deepEqual(extraParamView("gamma (offset)", 100, "Hours", fmt), { label: "Offset γ: no failures before", value: "100 hours" });
  assert.deepEqual(extraParamView("f0 (failed at t=0)", 3.83e-9, "Hours", fmt), { label: "Share failed at time 0, f₀", value: "about 0%" });
  assert.deepEqual(extraParamView("p (max fraction failing)", 0.42, "", fmt), { label: "Share that can ever fail, p", value: "42%" });
  assert.deepEqual(extraParamView("Spline terms", 3, "", fmt), { label: "Spline terms", value: "3" });
});
