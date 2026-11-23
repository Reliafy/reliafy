import { test } from "node:test";
import assert from "node:assert/strict";
import { modelUnit, overhaulReplaceBody, overhaulReplaceInputs, overhaulReplaceMissing, savingPctText, vsBestPct, vsBestWords } from "./overhaulReplace.js";

const saved = { source: "saved", modelId: "r1", name: "Gearbox", form: "crow_amsaa",
  params: [{ name: "alpha", value: 100 }, { name: "beta", value: 2.5 }], unit: "Flight hours" };
const f = { cost_repair: "1", cost_overhaul: "5", cost_replace: "20", overhaul_restores: "40" };

test("Compute says what it still needs", () => {
  assert.match(overhaulReplaceMissing({ model: null, f, unit: "" }), /repairable model/);
  assert.equal(overhaulReplaceMissing({ model: saved, f, unit: "" }), null);
  assert.match(overhaulReplaceMissing({ model: saved, f: { ...f, cost_replace: "" }, unit: "" }), /replacement cost/);
  assert.match(overhaulReplaceMissing({ model: saved, f: { ...f, cost_overhaul: "1" }, unit: "" }), /more than a repair/);
  assert.match(overhaulReplaceMissing({ model: saved, f: { ...f, overhaul_restores: "0" }, unit: "" }), /more than 0%/);
  assert.match(overhaulReplaceMissing({ model: saved, f: { ...f, downtime_repair: "2" }, unit: "" }), /hour down/);
  // Typed parameters carry no unit: one must be entered (no default).
  const typed = { source: "params", form: "crow_amsaa", params: ["100", "2.5"] };
  assert.match(overhaulReplaceMissing({ model: typed, f, unit: "" }), /unit/);
  assert.equal(overhaulReplaceMissing({ model: typed, f, unit: "flight hours" }), null);
  assert.equal(modelUnit(saved, "days"), "Flight hours");
});

test("the request reads a saved model on the server; the saved inputs keep its form and parameters", () => {
  const body = overhaulReplaceBody(saved, { ...f, downtime_repair: "" }, "");
  assert.equal(body.recurrent_model_id, "r1");
  assert.equal(body.cost_replace, 20);
  assert.ok(!("downtime_repair" in body));
  const kept = overhaulReplaceInputs(saved, f, "", { position_link_id: "L1" });
  assert.deepEqual([kept.form, kept.unit, kept.model_name, kept.position_link_id], ["crow_amsaa", "Flight hours", "Gearbox", "L1"]);
  assert.ok(!("recurrent_model_id" in kept));
  assert.deepEqual(overhaulReplaceBody({ source: "params", form: "duane", params: ["10", "2"] }, f, "cycles").params, [10, 2]);
});

test("other plans against the best plan, as a % of the best plan's cost", () => {
  // Overhaul only at $37.34/h against the best overhaul-and-replace plan at $39.31/h: 5.0% less
  // (not 5.3%, which is the best plan's excess as a % of overhaul only).
  assert.equal(vsBestWords(vsBestPct(37.34, 39.31)), "costs 5.0% less");
  assert.equal(vsBestWords(vsBestPct(44.0, 39.31)), "costs 12% more");
  assert.equal(vsBestWords(vsBestPct(39.311, 39.31)), "the same");
  assert.equal(vsBestWords(vsBestPct(null, 39.31)), "—");
  assert.equal(savingPctText(12.4), "12");
  assert.equal(savingPctText(1.234), "1.2");
});
