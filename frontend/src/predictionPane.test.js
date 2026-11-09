import { test } from "node:test";
import assert from "node:assert/strict";
import { lineChange, lineMode, missionHours, predictionKey, predictionResult, predictionTitle } from "./predictionPane.js";

test("the heading: add, or refresh the one there", () => {
  assert.equal(predictionTitle(), "Add a prediction");
  assert.equal(predictionTitle({ id: "l1" }), "Refresh the prediction");
});

test("the mission time typed", () => {
  assert.equal(missionHours(""), null);
  assert.equal(missionHours("0"), null);
  assert.equal(missionHours("abc"), null);
  assert.equal(missionHours(" 500 "), 500);
  assert.equal(missionHours(12.5), 12.5);
});

test("a change is a change of what's sent; a blank typed and cleared is none", () => {
  const lines = [{ reference: "C-1", record: { id: "r1" }, quality_factor: "" }, { reference: "AF", excluded: true }];
  const opened = predictionKey({ environment: "GB", mission: "", lines });
  assert.equal(predictionKey({ environment: "GB", mission: " ", lines: lines.map((l) => ({ ...l })) }), opened);
  assert.notEqual(predictionKey({ environment: "GF", mission: "", lines }), opened);
  assert.notEqual(predictionKey({ environment: "GB", mission: "100", lines }), opened);
  assert.notEqual(predictionKey({ environment: "GB", lines: [{ ...lines[0], record: null }, lines[1]] }), opened);
  assert.notEqual(predictionKey({ environment: "GB", lines: [lines[0], { reference: "AF", excluded: false }] }), opened);
});

test("what a line uses", () => {
  assert.equal(lineMode({ excluded: true, record: { id: "r" } }), "excluded");
  assert.equal(lineMode({ record: { id: "r" }, rate_per_million_hours: "3" }), "type");
  assert.equal(lineMode({ rate_per_million_hours: "3" }), "rate");
  assert.equal(lineMode({ rate_mode: true, rate_per_million_hours: "" }), "rate");
  assert.equal(lineMode({}), "type");
});

test("the result in the panel's words", () => {
  assert.equal(predictionResult(null), null);
  const r = {
    failure_rate_per_million_hours: 12.345, mtbf_hours: 81004.5, mission_time_hours: 500, reliability_at_mission: 0.99385,
    environment: { code: "GB", name: "Ground, benign" }, counts: { lines: 4, assigned: 2 },
    excluded: [{ name: "Airframe", quantity: 1 }], unassigned: [{ name: "Propeller", quantity: 4 }],
  };
  const out = predictionResult(r, "500");
  assert.equal(out.rate, "12.3");
  assert.equal(out.mtbf, "81,000");
  assert.equal(out.reliability, "99.39%");
  assert.equal(out.mission, "500");
  assert.equal(out.counted, "2 of 4 lines counted");
  assert.equal(out.environment, "Ground, benign (GB)");
  assert.deepEqual(out.notElectronic, ["Airframe"]);
  assert.deepEqual(out.noType, ["Propeller ×4"]);
  // No mission typed: no reliability (the server's default mission isn't the user's).
  assert.equal(predictionResult(r, "").reliability, null);
  // A mission typed but the result still for the last one: not shown until it catches up.
  assert.equal(predictionResult(r, "800").reliability, null);
  // Nothing counted yet: no rate, no MTBF.
  const none = predictionResult({ failure_rate_per_million_hours: 0, mtbf_hours: null, counts: { lines: 1, assigned: 0 } });
  assert.equal(none.rate, null);
  assert.equal(none.mtbf, null);
  assert.equal(none.counted, "0 of 1 line counted");
});

test("a change from the shared part-type controls as the line's fields", () => {
  assert.deepEqual(lineChange({ record: { id: "r1", name: "Cap" } }), { record: { id: "r1", name: "Cap" }, record_id: "r1" });
  assert.deepEqual(lineChange({ record: null, rateMode: true }), { record: null, record_id: null, rate_mode: true });
  assert.deepEqual(lineChange({ rate: "0.5", rateMode: true }), { rate_per_million_hours: "0.5", rate_mode: true });
  assert.deepEqual(lineChange({ excluded: true, record: null, rate: "", rateMode: false }),
    { excluded: true, record: null, record_id: null, rate_per_million_hours: "", rate_mode: false });
  assert.deepEqual(lineChange({}), {});
});
