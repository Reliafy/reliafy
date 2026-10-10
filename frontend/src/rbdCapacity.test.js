import test from "node:test";
import assert from "node:assert/strict";
import {
  boldParts, capacityFromRows, capacityRows, capacitySummary, hasCapacity, pctNear1, productionSentence,
} from "./rbdCapacity.js";

test("rows round-trip a number and levels", () => {
  assert.deepEqual(capacityRows(250), [{ value: "250", share: "100" }]);
  assert.deepEqual(capacityRows(null), []);
  const levels = [{ value: 200, probability: 0.1 }, { value: 250, probability: 0.9 }];
  assert.deepEqual(capacityFromRows(capacityRows(levels)), { value: levels, valid: true });
  assert.deepEqual(capacityFromRows([{ value: "250", share: "100" }]), { value: 250, valid: true });
});

test("empty rows are no capacity; bad rows say why", () => {
  assert.deepEqual(capacityFromRows([{ value: "", share: "" }]), { value: null, valid: true });
  assert.deepEqual(capacityFromRows([{ value: "", share: "100" }]), { value: null, valid: true });
  assert.match(capacityFromRows([{ value: "-1", share: "100" }]).error, /positive/);
  assert.match(capacityFromRows([{ value: "5", share: "60" }, { value: "4", share: "30" }]).error, /add up to 100%/);
  assert.match(capacityFromRows([{ value: "5", share: "" }]).error, /share/);
});

test("summary and presence", () => {
  assert.equal(capacitySummary(null), "none");
  assert.equal(capacitySummary(250, "kW"), "250 kW");
  assert.equal(capacitySummary([{ value: 200, probability: 0.1 }, { value: 250, probability: 0.9 }]), "2 levels, up to 250");
  assert.equal(hasCapacity({ nodes: [{ data: {} }, { data: { capacity: 5 } }] }), true);
  assert.equal(hasCapacity({ nodes: [{ data: { capacity: [] } }] }), false);
});

test("production sentence", () => {
  const p = { kind: "repairable", demand: 900, capacity_unit: "kW", production_availability: 0.99598,
              availability: 0.99868, mean_capacity: 975 };
  assert.match(productionSentence(p), /delivers \*\*99\.60%\*\* of the \*\*900 kW\*\* demand, against \*\*99\.87%\*\* plain availability/);
  assert.match(productionSentence({ ...p, production_availability: null }), /Set a demand/);
  assert.match(productionSentence({ ...p, kind: "reliability", t: 1000 }, "Hours"), /^At 1,000 hours/);
});

test("percentages near 1 keep the figures that matter", () => {
  assert.equal(pctNear1(0.99598), "99.60%");
  assert.equal(pctNear1(0.9999), "99.990%");
  assert.equal(pctNear1(0.6458), "64.6%");
  assert.equal(pctNear1(1), "100.0%");
  assert.equal(pctNear1(null), "—");
});

test("bold parts", () => {
  assert.deepEqual(boldParts("a **b** c"), [["a ", false], ["b", true], [" c", false]]);
});
