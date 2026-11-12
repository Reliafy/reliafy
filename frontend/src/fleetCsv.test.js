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

test("a first-failures forecast's CSV has its years: failures and cost, with ranges", () => {
  const block = (e, lo, hi) => ({ expected: e, interval: [lo, hi] });
  const row = (e, lo, hi) => ({ failures: block(e, lo, hi), planned: block(0, 0, 0), parts: block(e, lo, hi),
                                cost: block(e * 100, lo * 100, hi * 100) });
  const text = fleetForecastCsv({
    items: [], forecast: {
      expected: 9.5, interval: [7, 12],
      strategy: { kind: "first_failures", total: row(9.5, 7, 12), per_period: [{ period: 1, ...row(1, 0, 3) }],
                  yearly: [{ year: 1, from_period: 1, to_period: 12, ...row(6.2, 4, 8) },
                           { year: 2, from_period: 13, to_period: 24, ...row(3.3, 1, 6) }] },
    },
  });
  const lines = text.split("\n");
  assert.ok(lines.includes("strategy,first_failures"));
  assert.ok(lines.includes("year,from_period,to_period,failures,failures_p5,failures_p95,cost,cost_p5,cost_p95"));
  assert.ok(lines.includes("1,1,12,6.2,4,8,620,400,800"));
  assert.ok(lines.includes("2,13,24,3.3,1,6,330,100,600"));
});
