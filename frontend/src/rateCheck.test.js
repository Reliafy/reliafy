import test from "node:test";
import assert from "node:assert/strict";
import { rateLooksLikeMean } from "./rateCheck.js";

test("an MTBF typed as a failure rate is caught, with the rate it likely means", () => {
  const r = rateLooksLikeMean("exponential", "failure_rate", "4000", "hours");
  assert.equal(r.text, "This looks like an MTBF of 4,000 hours; did you mean a rate of 0.00025 per hour?");
  assert.equal(r.rate, 0.00025);
  assert.equal(rateLooksLikeMean("exponential", "failure_rate", 50000, "").text,
    "This looks like an MTBF of 50,000; did you mean a rate of 0.00002 per unit of time?");
});

test("a plausible rate, a blank and other parameters pass", () => {
  assert.equal(rateLooksLikeMean("exponential", "failure_rate", "0.00025", "hours"), null);
  assert.equal(rateLooksLikeMean("exponential", "failure_rate", "1", "hours"), null);
  assert.equal(rateLooksLikeMean("exponential", "failure_rate", "", "hours"), null);
  assert.equal(rateLooksLikeMean("weibull", "alpha", "4000", "hours"), null);
});
