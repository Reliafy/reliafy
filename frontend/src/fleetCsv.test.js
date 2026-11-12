import { test } from "node:test";
import assert from "node:assert/strict";
import { fleetForecastCsv } from "./fleetCsv.js";

// 12 Nov review: the forecast's Export CSV held "0.9999999999999997".
test("the forecast CSV has no floating-point noise: 4 significant figures", () => {
  const text = fleetForecastCsv({
    items: [{ id: "a", name: "Genset 1 belt", current_use: 0 }, { id: "b", name: "Genset 8 belt", current_use: 14000, rate: 2190 }],
    perItem: { a: { prob_any: 0.12345678, expected: 0.1234567 }, b: { prob_any: 0.9999999999999997, expected: 1.0000000000000002 } },
    defaultRate: 2190,
    forecast: { expected: 3.8812345, interval: [2, 6], per_period: [0.80123456, 0.9234567], per_period_interval: [[0, 2], [0, 3]] },
  });
  assert.ok(!/\d\.\d{5,}/.test(text), text);
  const lines = text.split("\n");
  assert.equal(lines[1], "Genset 1 belt,0,2190,0.1235,0.1235");
  assert.equal(lines[2], "Genset 8 belt,14000,2190,1,1");
  assert.ok(lines.includes("fleet_expected,3.881"));
  assert.ok(lines.includes("1,0.8012,0,2"));
});
