import test from "node:test";
import assert from "node:assert/strict";
import { basisText, bodyFor, every, modelSource, modelWords, setsCount, setsLine, startText, useLabel, usedText } from "./taskOptimise.js";

test("an interval reads as the plan shows it", () => {
  assert.equal(every(96, "hours"), "96 h");
  assert.equal(every(3, "months"), "3 months");
  assert.equal(every(1, "weeks"), "1 week");
  assert.equal(useLabel({ value: 96, unit: "hours" }), "Use every 96 h");
  assert.equal(useLabel(null), "Use");
});

test("the body sends only what was changed, the target as a chance", () => {
  assert.deepEqual(bodyFor("m1", { planned_cost: "", unplanned_cost: "900", target: "1", pf_unit: "hours" },
    { type: "degradation_model", id: "d1" }),
  { failure_mode_id: "m1", unplanned_cost: 900, pf_unit: "hours", target_unavailability: 0.01, model_type: "degradation_model", model_id: "d1" });
  assert.deepEqual(bodyFor("m1", { pf_interval: "abc" }), { failure_mode_id: "m1" });
});

test("starting text, sources and the words both places share", () => {
  assert.equal(startText({ value: 49.0 }), "49");
  assert.equal(startText({ value: null }), "");
  assert.equal(modelSource({ source: "position" }), "This failure mode's model on the position.");
  assert.equal(modelSource({ source: "analysis", note: "No model is linked." }), "No model is linked.");
  assert.equal(modelWords({ words: "Weibull", unit: "hours" }), "Weibull · hours");
  assert.equal(setsLine({ name: "Replace spark plugs", interval: 96, unit: "hours" }), "Replace spark plugs (every 96 h)");
  assert.equal(setsCount([{}, {}]), "sets 2 tasks' interval");
  assert.equal(setsCount([]), "");
  assert.equal(basisText({ use: { value: 96, unit: "hours" }, model: { name: "Spark plug life" } }), "Every 96 h rests on Spark plug life");
});

test("after Use, one line says what changed", () => {
  assert.equal(usedText({ interval: 96, unit: "hours", evidence_linked: true, evidence_status: "supported" }),
    "Set to every 96 h, the calculation saved as its evidence. The evidence reads supported.");
  assert.match(usedText({ interval: 5, unit: "weeks", evidence_linked: false, evidence_not_linked: "No decision yet." }), /No decision yet\.$/);
});

test("a task's Optimise opens on its asset's Maintenance tab", async () => {
  const { optimisePath } = await import("./taskOptimise.js");
  const p = optimisePath({ task_id: "t1", position_id: "p1", root: "top" });
  const q = new URLSearchParams(p.split("?")[1]);
  assert.equal(q.get("root"), "top");
  assert.equal(q.get("tab"), "maintenance");
  assert.equal(q.get("optimise"), "t1");
  assert.equal(q.get("on"), "p1");
});

test("a supporting task's break-even: tiles, never an interval", async () => {
  const { breakEvenTiles } = await import("./taskOptimise.js");
  const tiles = breakEvenTiles({ break_even: 6360.4, task_cost: 562.5, k: 2.5, reference: 250, unit: "hours" });
  assert.deepEqual(tiles.map((t) => t.label), ["Break-even, one doing", "It costs", "If it isn't done", "Its life assumes"]);
  assert.equal(tiles[0].value, "$6,360");
  assert.equal(tiles[1].value, "$562.50");
  assert.deepEqual(breakEvenTiles({ break_even: null }), []);
});
