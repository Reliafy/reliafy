import { test } from "node:test";
import assert from "node:assert/strict";
import { progressText, readingRows, readingsToSend, rowDetail, startValues, takenText, whyText } from "./workOrderReadings.js";

const WO = {
  reading_points: [
    { id: "chl", name: "Chlorinator output", unit: "%", kind: "setting", reading: 45, task_id: "t1", task: { id: "t1", name: "Change-over" }, why: ["setting"], recorded: null },
    { id: "salt", name: "Salt", unit: "ppm", kind: "condition", reading: 3100, task_id: "t1", task: { id: "t1", name: "Change-over" }, why: ["tool"], recorded: { value: 3200 } },
  ],
  measurements: [{ id: "salt", name: "Salt", unit: "ppm", kind: "condition", reading: 3100 }, { id: "temp", name: "Water", unit: "°C", kind: "condition", reading: null }],
};

test("the rows: asked first, then the other points there, each once", () => {
  const rows = readingRows(WO);
  assert.deepEqual(rows.map((r) => [r.id, r.group]), [["chl", "asked"], ["salt", "asked"], ["temp", "other"]]);
  assert.equal(whyText(["tool", "setting"]), "a tool the task uses reads it · a setting here");
  assert.equal(rowDetail(rows[0]), "a setting here · for Change-over · now 45%");
  assert.equal(rowDetail(rows[1]), "recorded 3200 ppm here · a tool the task uses reads it · for Change-over · last 3100 ppm");
  assert.equal(rowDetail(rows[2]), "never read");
});

test("a setting starts with its value; only edited boxes are sent", () => {
  const rows = readingRows(WO);
  const start = startValues(rows);
  assert.deepEqual(start.chl, { value: "45", dirty: false });
  assert.deepEqual(readingsToSend(rows, start), []);
  const edited = { ...start, chl: { value: "60", dirty: true }, temp: { value: "", dirty: true }, salt: { value: "abc", dirty: true } };
  assert.deepEqual(readingsToSend(rows, edited), [{ point_id: "chl", value: 60, task_id: "t1" }]);
});

test("progress and what was taken, in words", () => {
  assert.equal(progressText({ asked: 3, recorded: 2 }), "Readings: 2 of 3 recorded");
  assert.equal(progressText({ asked: 0, recorded: 0 }), "");
  assert.equal(takenText({ point: { name: "Chlorinator output", unit: "%", kind: "setting" }, value: 60, from: 45 }),
    "Chlorinator output set to 60% (from 45%)");
  assert.equal(takenText({ point: { name: "Salt", unit: "ppm", kind: "condition" }, value: 3200 }), "Salt 3200 ppm");
});
