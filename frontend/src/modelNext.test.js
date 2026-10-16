import { test } from "node:test";
import assert from "node:assert/strict";
import {
  analysisName, graphWithModel, modelFromSearch, nextStepLink, nextStepsFor, plainName, preferredModel, savedModelRef,
} from "./modelNext.js";

test("nextStepsFor: which tools take which kind of model", () => {
  assert.deepEqual(nextStepsFor({ kind: "distribution", distribution_id: "weibull" }),
                   { replacement: true, fleet: true, test: true, rbd: true });
  // A mixture has no single distribution for the replacement tool.
  assert.equal(nextStepsFor({ kind: "distribution", distribution_id: "mixture" }).replacement, false);
  assert.deepEqual(nextStepsFor({ kind: "regression", distribution_id: "weibull_ph" }),
                   { replacement: false, fleet: true, test: false, rbd: true });
  assert.deepEqual(nextStepsFor({ kind: "nonparametric" }), { replacement: false, fleet: false, test: true, rbd: false });
  // Covariates over time: no fleet or block takes the item paths.
  assert.equal(nextStepsFor({ kind: "regression", tvc: {} }).fleet, false);
});

test("nextStepLink opens each tool with the model chosen", () => {
  assert.equal(nextStepLink("replacement", "m1"), "/strategy/replacement?model=m1");
  assert.equal(nextStepLink("fleet", "m1"), "/forecasts?new=1&model=m1");
  assert.equal(nextStepLink("test", "m1", { unit: "Hours" }), "/strategy/demonstration-test?unit=Hours&model=m1");
  assert.equal(modelFromSearch("?model=m1&new=1"), "m1");
  assert.equal(modelFromSearch("?model=<x>"), null);
  assert.equal(modelFromSearch(""), null);
});

test("preferredModel: the link's, then the recent one, then the newest of the user's own", () => {
  const models = [
    { id: "s1", is_sample: true, created_at: "2026-10-11T00:00:00Z" },
    { id: "a", created_at: "2026-10-01T00:00:00Z" },
    { id: "b", created_at: "2026-10-05T00:00:00Z" },
  ];
  assert.equal(preferredModel(models, { wanted: "a", recent: "b" }), "a");
  assert.equal(preferredModel(models, { wanted: "gone", recent: "s1" }), "s1");
  assert.equal(preferredModel(models, { recent: "gone" }), "b");
  assert.equal(preferredModel([models[0]]), "s1");
  assert.equal(preferredModel([]), null);
});

test("analysisName uses the saved model's name, without the sample suffix", () => {
  assert.equal(analysisName("Replacement", { source: "saved", name: "Pump bearings" }, "Weibull"),
               "Replacement: Pump bearings");
  assert.equal(analysisName("Replacement", { source: "saved", name: "Bearing life — Weibull (sample)" }, "Weibull"),
               "Replacement: Bearing life — Weibull");
  assert.equal(analysisName("Failure finding", { source: "params" }, "Exponential"), "Failure finding: Exponential");
  assert.equal(plainName(" Seals (Sample) "), "Seals");
});

test("savedModelRef carries the id, parameters and unit", () => {
  const ref = savedModelRef({
    id: "m1", name: "Seals", kind: "distribution",
    results: { distribution: "Weibull", distribution_id: "weibull", params: [{ name: "alpha", value: 9 }], unit: "Hours" },
  });
  assert.equal(ref.source, "saved");
  assert.equal(ref.modelId, "m1");
  assert.equal(ref.unit, "Hours");
  assert.deepEqual(ref.covariates, []);
  assert.equal(ref.base_distribution_id, undefined);
});

const MODEL = { source: "saved", modelId: "m1", name: "Pump bearings (sample)", unit: "Hours" };

test("graphWithModel: a new diagram gets the block wired in, in the model's unit", () => {
  const { graph, id, wired } = graphWithModel(null, MODEL);
  assert.equal(id, "c1");
  assert.equal(wired, true);
  assert.equal(graph.unit, "Hours");
  assert.deepEqual(graph.nodes.map((n) => n.id), ["input", "output", "c1"]);
  assert.equal(graph.nodes[2].data.label, "Pump bearings");
  assert.equal(graph.nodes[2].data.model, MODEL);
  assert.deepEqual(graph.edges.map((e) => [e.source, e.target]), [["input", "c1"], ["c1", "output"]]);
});

test("graphWithModel: an existing diagram keeps its wiring and unit; the block waits to be wired", () => {
  const saved = {
    unit: "Years",
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 100 } },
      { id: "c4", type: "component", position: { x: 200, y: 60 }, data: {} },
      { id: "k7", type: "knode", position: { x: 300, y: 200 }, data: {} },
      { id: "output", type: "output", position: { x: 500, y: 100 } },
    ],
    edges: [{ id: "e1", source: "input", target: "c4" }],
  };
  const { graph, id, wired } = graphWithModel(saved, MODEL);
  assert.equal(id, "c8");
  assert.equal(wired, false);
  assert.equal(graph.unit, "Years");
  assert.equal(graph.edges.length, 1);
  assert.deepEqual(graph.nodes.at(-1).position, { x: 250, y: 310 });
  // The saved graph itself is untouched.
  assert.equal(saved.nodes.length, 4);
});
