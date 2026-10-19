// The Data list's row menu: which fits each kind of dataset offers (#261).
import { test } from "node:test";
import assert from "node:assert/strict";
import { fitOptions } from "./datasetFit.js";

test("lifetime data alone fits a life model, and no condition monitoring", () => {
  const o = fitOptions({ id: "a", tags: ["Lifetime data", "Covariates"] });
  assert.deepEqual(o.map((x) => x.label), ["Life model with covariates"]);
  assert.equal(o[0].to, "/modelling/new?dataset=a");
});

test("with matching readings, condition monitoring opens with both tables", () => {
  const life = fitOptions({ id: "L", tags: ["Lifetime data"], pairs_with: [{ id: "R", name: "Readings" }] });
  assert.deepEqual(life.map((x) => x.label), ["Life model", "Condition monitoring"]);
  assert.equal(life[1].to, "/modelling/joint/new?lifetimes=L&readings=R");
  const reads = fitOptions({ id: "R", tags: ["Lifetime data", "Measurements"], pairs_with: [{ id: "L", name: "Lifetimes" }] });
  assert.deepEqual(reads.map((x) => x.label), ["Degradation model", "Condition monitoring"]);
  assert.equal(reads[1].to, "/modelling/joint/new?lifetimes=L&readings=R");
});

test("repeat failures and lone measurements open their own fits", () => {
  assert.equal(fitOptions({ id: "b", tags: ["Repeat failures"] })[0].to, "/modelling/recurrent/new?dataset=b");
  assert.deepEqual(fitOptions({ id: "c", tags: ["Lifetime data", "Measurements"] }).map((x) => x.label), ["Degradation model"]);
});
