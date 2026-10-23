// The Data list's row menu: which fit each kind of dataset offers (#261).
import { test } from "node:test";
import assert from "node:assert/strict";
import { fitOptions } from "./datasetFit.js";

test("each dataset offers the fits that take it alone", () => {
  assert.deepEqual(fitOptions({ id: "a", tags: ["Non-repairable", "Covariates"] }),
    [{ label: "Non-repairable model with covariates", to: "/models/new?dataset=a" }]);
  assert.equal(fitOptions({ id: "b", tags: ["Repairable"] })[0].to, "/models/recurrent/new?dataset=b");
  assert.deepEqual(fitOptions({ id: "c", tags: ["Measurements"] }).map((x) => x.label), ["Degradation model"]);
  // Life data and readings in one table go to condition and life, with the table as both inputs.
  assert.deepEqual(fitOptions({ id: "d", tags: ["Non-repairable", "Measurements"] }),
    [{ label: "Condition and life model", to: "/models/joint/new?lifetimes=d&readings=d" }]);
});

test("each new-model flow offers only the datasets it can use", async () => {
  const { usableFor, usableDatasets } = await import("./datasetFit.js");
  const life = { tags: ["Non-repairable"] };
  const lifeCov = { tags: ["Non-repairable", "Covariates"] };
  const rep = { tags: ["Repairable", "Covariates"] };
  const reads = { tags: ["Measurements"] };
  const both = { tags: ["Non-repairable", "Measurements"] };
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("life", d)), [true, true, false, false, true]);
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("repairable", d)), [false, false, true, false, false]);
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("accelerated", d)), [false, true, false, false, false]);
  assert.deepEqual([life, lifeCov, rep, reads, both].map((d) => usableFor("degradation", d)), [false, false, false, true, false]);
  assert.deepEqual([life, reads, both].map((d) => usableFor("lifetimes", d)), [true, false, true]);
  assert.deepEqual([life, reads, both].map((d) => usableFor("readings", d)), [false, true, true]);
  assert.equal(usableFor("life", {}), true); // no tags from the server: not hidden
  assert.equal(usableDatasets("repairable", [life, rep]).length, 1);
});
