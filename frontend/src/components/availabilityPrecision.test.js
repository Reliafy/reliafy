import { test } from "node:test";
import assert from "node:assert/strict";
import { availabilityPct, downPct, precisionNote } from "./availabilityPrecision.js";

test("availability to about four significant figures", () => {
  assert.equal(availabilityPct(0.9996858), "99.97%");
  assert.equal(availabilityPct(0.9512), "95.12%");
  assert.equal(availabilityPct(0.0731), "7.310%");
  assert.equal(availabilityPct(null), "—");
});

test("downtime to three significant figures", () => {
  assert.equal(downPct(0.9996858), "0.0314%");
  assert.equal(downPct(1), "0%");
});

test("the footnote doesn't quote seven figures", () => {
  const note = precisionNote({
    n_simulations: 1000,
    precision: { window_availability: 0.9996858, lower: 0.9996768, upper: 0.9996894, half_width: 0.0000063,
      tolerance: 0.001, confidence: 0.95, mode: "fixed" },
  });
  assert.match(note, /up 99\.97% \(down 0\.0314%\) of the time/);
  assert.doesNotMatch(note, /\d+\.\d{5,}/);
});
