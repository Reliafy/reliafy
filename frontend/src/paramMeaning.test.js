import { test } from "node:test";
import assert from "node:assert/strict";
import { paramMeaning } from "./paramMeaning.js";

test("β and α in plain words, read for the fitted values", () => {
  const b = paramMeaning("weibull", "beta", 2.5, "Hours");
  assert.equal(b.name, "Shape β");
  assert.match(b.text, /above 1: failures get more likely with age \(wear-out\)/);
  assert.match(paramMeaning("weibull", "beta", 0.6).text, /below 1/);
  assert.match(paramMeaning("weibull", "beta", 1.0).text, /about 1/);
  const a = paramMeaning("weibull", "alpha", 1440, "Hours");
  assert.equal(a.name, "Scale α");
  assert.match(a.text, /about 63% of units have failed/);
  assert.match(a.text, /Here, 1,440 hours\./);
});

test("other parameters say something plain; unknown ones say nothing", () => {
  assert.match(paramMeaning("exponential", "failure_rate", 0.001, "Hours").text, /mean life is 1 ÷ λ = 1,000 hours/);
  assert.match(paramMeaning("lognormal", "mu", Math.log(500), "Hours").text, /= 500 hours/);
  assert.equal(paramMeaning("weibull", "nope", 1), null);
});
