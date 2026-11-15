import test from "node:test";
import assert from "node:assert/strict";
import { describeStandby, hasOwnUnits, kindOf, standbyUnits, tidyOwn } from "./standbyWords.js";

const W = (a, b) => ({ distribution_id: "weibull", params: [{ name: "alpha", value: a }, { name: "beta", value: b }] });

test("describes the arrangement in plant words", () => {
  assert.equal(describeStandby({ k: 2, spares: 1, dormancy: 0.3 }), "2 running, 1 warm spare ageing at 30% while waiting");
  assert.equal(describeStandby({ k: 2, spares: 1, dormancy: 0.3, startProb: 0.95 }),
    "2 running, 1 warm spare ageing at 30% while waiting; each spare starts 95% of the time");
  assert.equal(describeStandby({ spares: 2, dormancy: 0 }), "1 running, 2 cold spares (not ageing while waiting)");
  assert.equal(describeStandby({ spares: 1, dormancy: 1 }), "1 running, 1 hot spare (ageing as if running)");
  assert.equal(describeStandby({ spares: 1, cold: true }), "1 running, 1 cold spare (not ageing while waiting)");
});

test("names the units with models of their own", () => {
  assert.match(describeStandby({ k: 2, spares: 2, dormancy: 0, spareModels: [W(50, 1.5)] }), /spare 1 has its own model$/);
  assert.match(describeStandby({ k: 2, spares: 1, dormancy: 0, runningModels: [null, W(1, 2)], spareModels: [W(3, 1)] }),
    /running unit 2 and spare 1 have their own models$/);
  assert.match(describeStandby({ spares: 2, dormancy: 0, standbyModel: W(3, 1) }), /the spares have their own models$/);
});

test("lists the units in order, each on its own model or the default", () => {
  const units = standbyUnits({ model: W(100, 2), standbyModel: W(80, 2), k: 2, spares: 2, spareModels: [null, W(50, 1)],
    runningModels: [W(90, 2)] });
  assert.deepEqual(units.map((u) => [u.label, u.own, u.model.params[0].value]), [
    ["Running unit 1", true, 90], ["Running unit 2", false, 100], ["Spare 1", false, 80], ["Spare 2", true, 50],
  ]);
  assert.equal(hasOwnUnits({ spareModels: [null] }), false);
  assert.equal(hasOwnUnits({ spareModels: [null, W(1, 1)] }), true);
  assert.equal(kindOf({ dormancy: 0.5 }), "warm");
});

test("tidies a per-unit list to its count", () => {
  assert.deepEqual(tidyOwn([W(1, 1), null, null], 3), [W(1, 1)]);
  assert.equal(tidyOwn([null, null], 2), null);
  assert.deepEqual(tidyOwn([null, W(1, 1), W(2, 2)], 2), [null, W(1, 1)]);
});
