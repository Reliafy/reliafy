import { test } from "node:test";
import assert from "node:assert/strict";
import { readRule } from "./rbdReplacement.js";
import { blockLine, lifeLine } from "./components/rbdModelText.js";

test("a replacement rule as typed", () => {
  assert.deepEqual(readRule("age", "8000", "", "", ""), { valid: true, value: { rule: "age", age: 8000 } });
  assert.deepEqual(readRule("age", "8000", "", "8", "4000").value, { rule: "age", age: 8000, duration: 8, cost: 4000 });
  assert.equal(readRule("age", "", "", "", "").error, "Enter an age above 0.");
  assert.equal(readRule("age", "0", "", "", "").valid, false);
  assert.deepEqual(readRule("repairs", "", "3", "", "").value, { rule: "repairs", repairs: 3 });
  assert.deepEqual(readRule("repairs", "", "0", "", "").value, { rule: "repairs", repairs: 0 });
  assert.equal(readRule("repairs", "", "1.5", "", "").error, "Enter a whole number of repairs, 0 to 999.");
  assert.deepEqual(readRule("none", "", "", "", "").value, { rule: "none" });
});

test("a repairable model's one line on the canvas", () => {
  const ca = { kind: "repairable", form: "crow_amsaa", params: [{ name: "alpha", value: 100 }, { name: "beta", value: 1.8 }] };
  assert.equal(lifeLine(ca, "Hours"), "Crow-AMSAA · β 1.8");
  const duane = { kind: "repairable", form: "duane", params: [{ name: "alpha", value: 1.4 }, { name: "b", value: 0.01 }] };
  assert.equal(lifeLine(duane, "Hours"), "Duane · β 1.4");
  const cl = { kind: "repairable", form: "cox_lewis", params: [{ name: "alpha", value: -4 }, { name: "beta", value: 0.002 }] };
  assert.equal(lifeLine(cl, "Hours"), "Cox-Lewis · trend 0.002");
  assert.equal(lifeLine({ kind: "repairable", form: "hpp", params: [{ name: "lambda", value: 0.01 }] }, "Hours"), "HPP");
  const exp = { distribution: "Exponential", distribution_id: "exponential", params: [{ name: "failure_rate", value: 0.2 }] };
  assert.equal(blockLine({ model: ca, repair: exp }, "Hours", true), "Crow-AMSAA · β 1.8 · MTTR 5 h");
});
