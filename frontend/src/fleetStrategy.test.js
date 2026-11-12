import { test } from "node:test";
import assert from "node:assert/strict";
import { firstPeriodsParts, rangeText } from "./fleetStrategy.js";
import { fleetForecastCsv } from "./fleetCsv.js";

const st = { per_period: [9, 8, 10, 7].map((p) => ({ parts: { expected: p } })) };

test("the first quarter's parts, in the forecast's periods", () => {
  assert.deepEqual(firstPeriodsParts(st, "months"), { periods: 3, parts: 27 });
  assert.deepEqual(firstPeriodsParts(st, "quarters"), { periods: 1, parts: 9 });
  assert.equal(firstPeriodsParts(st, "years"), null);
  assert.equal(firstPeriodsParts({ per_period: st.per_period.slice(0, 2) }, "months"), null);
});

test("rangeText formats both ends", () => {
  assert.equal(rangeText({ interval: [44, 54] }), "44–54");
  assert.equal(rangeText({ interval: [1000, 2000] }, (v) => `$${v}`), "$1000–$2000");
  assert.equal(rangeText({}), null);
});

test("the forecast CSV carries the strategy's periods and years, with ranges", () => {
  const b = (e, lo, hi) => ({ expected: e, interval: [lo, hi] });
  const row = { failures: b(1, 0, 3), planned: b(8, 7, 9), parts: b(9, 7, 11), cost: b(34000, 20000, 50000) };
  const csv = fleetForecastCsv({
    items: [], forecast: { expected: 9.2, interval: [5, 14], strategy: {
      kind: "age", replace_at: 2000, per_period: [{ period: 1, ...row }],
      yearly: [{ year: 1, from_period: 1, to_period: 12, complete: true, ...row }], total: row,
    } },
  });
  const lines = csv.split("\n");
  assert.ok(lines.includes("strategy,age,replace_at,2000"));
  assert.ok(lines.includes("period,failures,failures_p5,failures_p95,planned,planned_p5,planned_p95,parts,parts_p5,parts_p95,cost,cost_p5,cost_p95"));
  assert.ok(lines.includes("1,1,0,3,8,7,9,9,7,11,34000,20000,50000"));
  assert.ok(lines.includes("year,from_period,to_period,failures,failures_p5,failures_p95,planned,planned_p5,planned_p95,parts,parts_p5,parts_p95,cost,cost_p5,cost_p95"));
  assert.ok(lines.includes("1,1,12,1,0,3,8,7,9,9,7,11,34000,20000,50000"));
});
