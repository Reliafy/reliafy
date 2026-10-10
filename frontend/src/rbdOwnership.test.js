import test from "node:test";
import assert from "node:assert/strict";
import { bandsIn, copiesText, horizonWords, pfdRange, silLimit } from "./rbdOwnership.js";

test("horizonWords: whole years, other times in the unit, and for ever", () => {
  assert.equal(horizonWords({ horizon: 43800, years: 5 }, "Hours"), "5 years");
  assert.equal(horizonWords({ horizon: 8760, years: 1 }, "Hours"), "1 year");
  assert.equal(horizonWords({ horizon: 1000, years: 1000 / 8760 }, "Hours"), "1,000 hours");
  assert.equal(horizonWords({ horizon: 5000, years: null }, "Cycles"), "5,000 cycles");
  assert.equal(horizonWords({ horizon: null, endless: true }, "Hours"), "For ever");
});

test("copiesText lists only the blocks given copies", () => {
  assert.equal(copiesText([{ label: "Pump", copies: 2 }, { label: "Valve", copies: 1 }]), "Pump ×2");
  assert.equal(copiesText([{ label: "Pump", copies: 1 }]), "As drawn");
  assert.equal(copiesText(null), "As drawn");
});

test("pfdRange spans the PFDavg, the limit and the curve, on whole decades", () => {
  assert.equal(silLimit(2), 0.01);
  // PFDavg 1.3e-3 with the SIL 2 limit: 1e-5 up to the decade above the limit.
  assert.deepEqual(pfdRange([0, 2.6e-6, 1e-4, 2.7e-3], 1.34e-3, 2), [-5, -1]);
  // No band: up to the decade above the highest PFD.
  assert.deepEqual(pfdRange([2.6e-6, 2.7e-3], 1.34e-3, null), [-5, -2]);
  // Nothing to draw on a log axis.
  assert.equal(pfdRange([0, null], 1e-3, 2), null);
  // Never above 1, never below 1e-9, at least one decade.
  assert.deepEqual(pfdRange([0.5], 0.5, null), [-1, 0]);
  assert.deepEqual(pfdRange([1e-14, 1e-12], 1e-12, null), [-9, -8]);
  assert.deepEqual(bandsIn([-5, -2]), [2, 3, 4]);
  assert.deepEqual(bandsIn([-5, -1]), [1, 2, 3, 4]);
});
