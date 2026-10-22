// The Data list's row menu: which fit each kind of dataset offers (#261).
import { test } from "node:test";
import assert from "node:assert/strict";
import { fitOptions } from "./datasetFit.js";

test("each dataset offers the fits that take it alone", () => {
  assert.deepEqual(fitOptions({ id: "a", tags: ["Non-repairable", "Covariates"] }),
    [{ label: "Life model with covariates", to: "/modelling/new?dataset=a" }]);
  assert.equal(fitOptions({ id: "b", tags: ["Repairable"] })[0].to, "/modelling/recurrent/new?dataset=b");
  assert.deepEqual(fitOptions({ id: "c", tags: ["Measurements"] }).map((x) => x.label), ["Degradation model"]);
  // Life data and readings in one table go to condition monitoring, with the table as both inputs.
  assert.deepEqual(fitOptions({ id: "d", tags: ["Non-repairable", "Measurements"] }),
    [{ label: "Condition monitoring model", to: "/modelling/joint/new?lifetimes=d&readings=d" }]);
});
