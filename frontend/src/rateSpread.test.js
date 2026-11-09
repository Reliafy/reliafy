import { test } from "node:test";
import assert from "node:assert/strict";
import { SPREAD_LABEL, rateSpread, spreadAt, spreadCurves, spreadMean, spreadRangeText, spreadTime, spreadWords } from "./rateSpread.js";

// "Pipe: external leak, large (not service water)", 100 feet: gamma(0.3, 1.187e10) per hour per foot.
const RESULT = {
  unit: "Hours",
  params: [{ name: "failure_rate", value: 2.527e-9, ci: [2.705e-13, 1.156e-8] }],
  rate_uncertainty: {
    distribution: "gamma", shape: 0.3, rate: 1.187e8, mean: 2.527e-9, point: 2.527e-9, p05: 2.705e-13, p95: 1.156e-8,
    unit: "Hours", length_ft: 100, source: { name: "NRC/INL 2020", record_id: "nrc-inl-2020:pipe-other-ell" },
  },
};

test("a model without a rate distribution has no spread", () => {
  assert.equal(rateSpread({ params: [{ name: "failure_rate", value: 1e-3 }] }), null);
  assert.equal(spreadWords(null), null);
  assert.equal(spreadAt(null, "sf", 1), null);
});

test("the words come first: the rate, the gamma and where 90% of plants lie", () => {
  const s = rateSpread(RESULT);
  assert.equal(
    spreadWords(s),
    "Failure rate: 2.53e-9 per hour on average, for 100 feet of pipe (the source's rate is per foot). "
      + "NRC/INL 2020 give it as a gamma across plants (shape 0.3, rate 1.19e8 hours): 90% of plants lie "
      + "between 2.71e-13 and 1.16e-8 per hour.",
  );
});

test("reliability, mean and time at reliability run between the rate's 95% and 5%", () => {
  const s = rateSpread(RESULT);
  const t = 1e6;
  const r = spreadAt(s, "sf", t);
  assert.ok(Math.abs(r.lower - Math.exp(-1.156e-8 * t)) < 1e-12);
  assert.ok(Math.abs(r.upper - Math.exp(-2.705e-13 * t)) < 1e-12);
  const f = spreadAt(s, "ff", t);
  assert.ok(Math.abs(f.upper - (1 - r.lower)) < 1e-12);
  assert.deepEqual(spreadAt(s, "hf", t), { lower: 2.705e-13, upper: 1.156e-8 });
  assert.equal(spreadAt(s, "df", t), null);

  const m = spreadMean(s);
  assert.ok(Math.abs(m.value - 1 / 2.527e-9) < 1);
  assert.ok(Math.abs(m.lower - 1 / 1.156e-8) < 1e-3 && Math.abs(m.upper - 1 / 2.705e-13) < 1e3);

  const b10 = spreadTime(s, 0.9);
  assert.ok(Math.abs(b10.value - -Math.log(0.9) / 2.527e-9) < 1e-3);
  assert.ok(b10.lower < b10.value && b10.value < b10.upper);

  const c = spreadCurves(s, "sf", [0, 1e6, 1e8]);
  assert.equal(c.lower.length, 3);
  assert.equal(c.lower[0], 1);
  assert.equal(spreadCurves(s, "df", [0, 1]), null);
  assert.ok(spreadRangeText(1, 2).startsWith(SPREAD_LABEL));
});
