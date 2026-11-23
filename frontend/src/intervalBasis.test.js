import test from "node:test";
import assert from "node:assert/strict";
import { basisAction, basisLine } from "./intervalBasis.js";

const task = { interval: 50, unit: "hours" };

test("Interval based on: the saved calculation's inputs, in one line", () => {
  const pf = basisLine(task, { previous: { kind: "on_condition_interval", inputs: { pf_interval: 120, pf_unit: "hours", detection_probability: 1 } } });
  assert.equal(pf.text, "Every 50 hours · from a P-F interval of 120 hours");
  assert.equal(basisAction(pf), "Change…");
  const miss = basisLine(task, { previous: { kind: "on_condition_interval", inputs: { pf_interval: 120, pf_unit: "hours", detection_probability: 0.8, act_time: 10 } } });
  assert.equal(miss.text, "Every 50 hours · from a P-F interval of 120 hours, 10 to act, a check finding 80%");
  const ff = basisLine({ interval: 6, unit: "months" }, { previous: { kind: "failure_finding_interval", inputs: { failure_rate: 0.1, target_unavailability: 0.01 } } });
  assert.equal(ff.text, "Every 6 months · from 0.1 failures a year, at most 1% unavailable");
});

test("Interval based on: other evidence by name; nothing yet says so and offers to work it out", () => {
  assert.equal(basisLine(task, {}, { artifact_name: "Belt life" }).text, "Every 50 hours · from Belt life");
  const none = basisLine(task, {});
  assert.equal(none.text, "Every 50 hours · not worked out yet");
  assert.equal(basisAction(none), "Work it out…");
});

test("Interval based on: a saved calculation's own answer leads (Check every 60 hours)", () => {
  const got = { previous: { kind: "on_condition_interval", inputs: { pf_interval: 120, pf_unit: "hours" } } };
  assert.equal(basisLine(task, got, { artifact_name: "Belt (P-F)", headline: "Check every 60 hours" }).text,
    "Check every 60 hours · from a P-F interval of 120 hours");
});
