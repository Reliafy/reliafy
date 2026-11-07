import { test } from "node:test";
import assert from "node:assert/strict";
import {
  atLastDoneText, checkChoice, choiceBody, choiceLabel, fieldBody, measurementLines, pointLabel, readingText, startChoice,
  withMeasurement,
} from "./taskMeasurement.js";

const VIEW = {
  task_id: "t1", name: "Service", by_use: true, unit: "hours", last_done: "2026-03-01", last_done_reading: 1600,
  last_done_reading_estimated: false, chosen: false, fits: false,
  measurement: { id: "h12", name: "Engine hours", unit: "hours", on: { kind: "position", id: "t12", name: "Truck 12" }, reading: 1900, read_on: "2026-03-15" },
  choices: [{ id: "h14", name: "Engine hours", unit: "hours", on: { name: "Truck 14" }, relation: "here", reading: 5600,
    at_last_done: { value: 5400, estimated: true } }],
  suggested_point_id: "h14",
};

test("readings and labels read plainly", () => {
  assert.equal(readingText(12345.678, "hours"), "12,345.7 hours");
  assert.equal(readingText(null, "hours"), "");
  assert.equal(pointLabel(VIEW.measurement), "Engine hours on Truck 12");
  assert.equal(pointLabel({ name: "hours while fitted", derived: true }), "hours while fitted (the use it has had where it was fitted)");
  assert.equal(choiceLabel(VIEW.choices[0]), "Engine hours on Truck 14 · reads 5,600 hours");
  assert.equal(choiceLabel({ name: "ECU", on: { name: "Engine" }, reading: null }), "ECU on Engine · no readings yet");
  assert.equal(atLastDoneText(VIEW.choices[0], "hours"), "about 5,400 hours");
  assert.equal(atLastDoneText({ at_last_done: { value: 10, estimated: false } }, "hours"), "10 hours");
});

test("a move's question starts on the measurement there, else keep", () => {
  assert.deepEqual(startChoice(VIEW), { mode: "switch", pointId: "h14", readingMode: "estimate", reading: "", interval: "", calendarUnit: "months" });
  assert.equal(startChoice({ ...VIEW, suggested_point_id: null, choices: [] }).mode, "keep");
});

test("each choice is checked and sent as the move takes it", () => {
  const s = startChoice(VIEW);
  assert.equal(checkChoice(s, VIEW), null);
  assert.deepEqual(choiceBody(s, VIEW), { choice: "switch", point_id: "h14" });
  const typed = { ...s, readingMode: "enter", reading: "" };
  assert.match(checkChoice(typed, VIEW), /Enter the reading/);
  assert.deepEqual(choiceBody({ ...typed, reading: "5410" }, VIEW), { choice: "switch", point_id: "h14", last_done_reading: 5410 });
  // Never done: no reading to ask for.
  assert.deepEqual(choiceBody(typed, { ...VIEW, last_done: null }), { choice: "switch", point_id: "h14" });
  assert.match(checkChoice({ ...s, pointId: "" }, VIEW), /Pick the measurement/);
  assert.match(checkChoice({ ...s, mode: "calendar", interval: "0" }, VIEW), /how often/);
  assert.deepEqual(choiceBody({ ...s, mode: "calendar", interval: "6", calendarUnit: "months" }, VIEW), { choice: "calendar", interval: 6, unit: "months" });
  assert.deepEqual(choiceBody({ ...s, mode: "keep" }, VIEW), { choice: "keep" });
});

test("the batch is sent again with that operation's measurement merged in", () => {
  const ops = [{ do: "failure_modes.reorder", args: { parent_id: "x", ids: [] } },
    { do: "tasks.move", args: { task_id: "t1", position_id: "t14", measurement: { t0: { choice: "keep" } } } }];
  const out = withMeasurement(ops, 1, { t1: { choice: "keep" } });
  assert.deepEqual(out[1].args.measurement, { t0: { choice: "keep" }, t1: { choice: "keep" } });
  assert.equal(out[0], ops[0]);
  assert.equal(ops[1].args.measurement.t1, undefined); // not changed in place
});

test("the task dialog's field says what it counts and sends only a change", () => {
  const lines = measurementLines(VIEW);
  assert.deepEqual(lines, { counts: "Engine hours on Truck 12", reads: "Reads 1,900 hours (2026-03-15)", lastDone: "Last done 2026-03-01 at 1,600 hours" });
  assert.match(measurementLines({ ...VIEW, last_done_reading_estimated: true }).lastDone, /an estimate, worked out from the date/);
  assert.equal(measurementLines({ ...VIEW, by_use: false }).counts, "");
  assert.equal(measurementLines({ ...VIEW, measurement: null }).counts, "Nothing yet: no hours counter here");
  assert.equal(fieldBody(VIEW, "", "estimate", ""), null); // automatic, as it was
  assert.deepEqual(fieldBody(VIEW, "h99", "estimate", ""), { point_id: "h99" });
  assert.deepEqual(fieldBody(VIEW, "h99", "enter", "12"), { point_id: "h99", last_done_reading: 12 });
  assert.deepEqual(fieldBody({ ...VIEW, chosen: true, measurement: { id: "h12" } }, "", "estimate", ""), { point_id: "" });
});
