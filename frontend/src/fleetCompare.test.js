import { test } from "node:test";
import assert from "node:assert/strict";
import { compareRows } from "./fleetCompare.js";

const block = (e, lo, hi) => ({ expected: e, interval: [lo, hi] });

test("two spares scenarios side by side: failures, hold and cost", () => {
  const base = {
    name: "Seals, lead 2", model_kind: "life", items: [{}, {}, {}],
    settings: { periods: 12, period_label: "months", default_rate: 500, method: "renewals" },
    forecast: {
      status: "ok", model_name: "Seal Weibull", unit: "Hours", expected: 6.2, interval: [3, 10],
      strategy: { kind: "run_to_failure", total: { ...{ failures: block(6.2, 3, 10) }, cost: block(12400, 6000, 20000),
                                                   planned: block(0, 0, 0) },
                  yearly: [{ failures: block(6.2, 3, 10) }] },
      spares: { status: "ok", hold: 4, service_level: 0.95, lead_time: 2 },
    },
  };
  const other = { ...base, name: "Seals, lead 4",
                  forecast: { ...base.forecast, spares: { status: "ok", hold: 6, service_level: 0.95, lead_time: 4 } } };
  const { columns, rows } = compareRows([base, other], "$");
  assert.deepEqual(columns, ["Seals, lead 2", "Seals, lead 4"]);
  const row = (label) => rows.find((r) => r.label === label)?.values;
  assert.deepEqual(row("Spares to hold"), ["Hold 4 (95%, lead 2 months)", "Hold 6 (95%, lead 4 months)"]);
  assert.deepEqual(row("Failures, whole horizon"), ["≈ 6.2 (3–10)", "≈ 6.2 (3–10)"]);
  assert.equal(row("Usage a period")[0], "500 hours");
  assert.match(row("Cost, whole horizon")[0], /^\$12,?400 \(\$6,?000–\$20,?000\)$/);
  // No forecast plans replacements: the row is left out.
  assert.equal(row("Planned replacements"), undefined);
});

test("a stale forecast shows dashes, not zeros", () => {
  const { rows } = compareRows([{ name: "Gone", items: [], settings: {}, forecast: { status: "stale" } }]);
  assert.deepEqual(rows.find((r) => r.label === "Model").values, ["—"]);
  assert.equal(rows.find((r) => r.label === "Failures, whole horizon"), undefined);
});
