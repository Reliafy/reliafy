// The Data list's Fit button: which fit each kind of dataset opens (#261).
import { test } from "node:test";
import assert from "node:assert/strict";
import { fitOptions } from "./datasetFit.js";

test("lifetime data fits a life model first, condition monitoring second", () => {
  const o = fitOptions({ id: "a", tags: ["Lifetime data", "Covariates"] });
  assert.deepEqual(o.map((x) => x.label), ["Life model with covariates", "Condition monitoring (as the lifetimes)"]);
  assert.equal(o[0].to, "/modelling/new?dataset=a");
});

test("repeat failures and measurements open their own fits", () => {
  assert.equal(fitOptions({ id: "b", tags: ["Repeat failures"] })[0].to, "/modelling/recurrent/new?dataset=b");
  assert.equal(fitOptions({ id: "c", tags: ["Lifetime data", "Measurements"] })[0].to, "/modelling/joint/new?readings=c");
});
