import { test } from "node:test";
import assert from "node:assert/strict";
import { countIsOld, countedText, dayText, demandText, holdBasis, orderLines, splitText } from "./sparesYear.js";

test("a count says how old it is", () => {
  assert.equal(countedText({ counted_on: "2026-11-13" }, "2026-11-23"), "counted 10 days ago");
  assert.equal(countedText({ counted_on: "2026-08-17" }, "2026-11-23"), "counted 14 weeks ago");
  assert.equal(countedText({ counted_on: "2025-11-23" }, "2026-11-23"), "counted 12 months ago");
  assert.equal(countedText({ counted_on: null }, "2026-11-23"), "never counted");
  assert.equal(countIsOld({ counted_on: "2026-11-13" }, "2026-11-23"), false);
  assert.equal(countIsOld({ counted_on: "2026-08-17" }, "2026-11-23"), true);
  assert.equal(countIsOld({}, "2026-11-23"), true);
});

test("the demand, the order and the hold read plainly", () => {
  const d = { mean: 5.397, p10: 4, p90: 7, failures: 4.483, planned: 0.914 };
  assert.equal(demandText(d), "≈ 5.4 (likely 4–7)");
  assert.equal(splitText(d), "4.5 failures + 0.91 planned");
  assert.equal(splitText({ mean: 3, planned: 3, failures: 0 }), "3 planned");
  assert.equal(splitText({ mean: 1.7, planned: 0, failures: 1.7 }), "all failures");
  assert.equal(dayText("2027-10-25"), "25 Oct 2027");
  assert.deepEqual(orderLines({ order_now: 2, arrives: "2027-03-15", order_by: [{ qty: 1, by: "2027-10-25" }] }),
    ["2 now (lands 15 Mar 2027)", "1 by 25 Oct 2027"]);
  assert.deepEqual(orderLines({ order_now: 0, order_by: [] }), []);
  assert.equal(holdBasis({ service_level: 0.95, lead_time_days: 112, lead_time_basis: "part" }), "95% over 112 days");
  assert.equal(holdBasis({ service_level: 0.995, lead_time_days: 30, lead_time_basis: "assumed" }), "99.5% over 30 days (assumed)");
});
