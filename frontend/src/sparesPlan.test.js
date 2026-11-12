import { test } from "node:test";
import assert from "node:assert/strict";
import { daysText, fleetSparesCsv, holdText, leadTimeHint, levelText, overText, riskAt, riskText, risingText, stockingCsv, useText, windowText } from "./sparesPlan.js";

test("service levels and chances read plainly", () => {
  assert.equal(levelText(0.95), "95%");
  assert.equal(levelText(0.995), "99.5%");
  assert.equal(riskText(0.534), "53%");
  assert.equal(riskText(0.001), "under 1%");
  assert.equal(riskText(0), "under 1%");
  assert.equal(riskText(null), "—");
});

test("the risk at a typed stock is read off the curve", () => {
  const curve = [[0, 0.83], [1, 0.53], [2, 0.27], [3, 0.11], [4, 0.035]];
  assert.equal(riskAt(curve, 0), 0.83);
  assert.equal(riskAt(curve, "2"), 0.27);
  assert.equal(riskAt(curve, 2.5), 0.27); // part of a unit doesn't cover another
  assert.equal(riskAt(curve, 9), 0.035); // past the curve: its last (smallest) chance
  assert.equal(riskAt(curve, -1), 1);
  assert.equal(riskAt(curve, ""), null);
  assert.equal(riskAt([], 2), null);
  // A curve in steps of 3 (large demand): the level at or below.
  assert.equal(riskAt([[0, 1], [3, 0.6], [6, 0.2]], 5), 0.6);
});

test("what a hold covers", () => {
  assert.equal(daysText(60), "60 days");
  assert.equal(daysText(1), "1 day");
  assert.equal(daysText(30, "assumed"), "30 days (assumed)");
  assert.equal(windowText({ lead_time_days: 60, review_days: 0 }), "60 days lead time");
  assert.equal(windowText({ lead_time_days: 30, review_days: 14 }), "30 days lead time + 14 days review");
  assert.equal(windowText({ repairable: true, turnaround_days: 20 }), "repair turnaround 20 days");
  assert.equal(overText(false, 0), "the lead time");
  assert.equal(overText(false, 14), "the lead time and review period");
  assert.equal(overText(true, 14), "the repair turnaround");
});

test("the class's stocking plan exports one row per part and period", () => {
  const spares = [{
    part: { part_number: "P-1", name: "Pump, 3 kW" }, unit: "each", usable_on_hand: 1,
    per_period: [{ mean: 0.9, p90: 2 }, { mean: 0.92, p90: 2 }],
    stocking: {
      service_level: 0.95, lead_time_days: 60, review_days: 0, repairable: false, turnaround_days: null,
      risk_at_stock: 0.53, unit_cost: 900,
      per_period: [{ start: "2026-10-16", hold: 4, reorder_at: 4 }, { start: "2026-11-15", hold: 4, reorder_at: 3 }],
    },
  }, { part: { part_number: "S-1", name: "Seal" }, per_period: [], stocking: null }];
  const lines = stockingCsv(spares, { positionClass: "Pump", period: "month" }).split("\n");
  assert.equal(lines.length, 3); // the header and two periods; a part without stock levels is left out
  assert.match(lines[0], /^position_class,part_number,part,unit,period_start,expected_use_this_month,/);
  assert.equal(lines[1], 'Pump,P-1,"Pump, 3 kW",each,2026-10-16,0.9,2,4,4,0.95,60,0,no,,1,0.53,900,3600');
  assert.equal(lines[2], 'Pump,P-1,"Pump, 3 kW",each,2026-11-15,0.92,2,4,3,0.95,60,0,no,,,,900,3600');
});

test("a fleet's spares plan exports one row per period", () => {
  const sp = {
    status: "ok", service_level: 0.9, lead_time: 2, review: 0, per_failure: 1, unit_cost: 100,
    per_period: [{ period: 1, hold: 5, reorder_at: 5, expected_demand: 2.4 }],
  };
  const lines = fleetSparesCsv(sp, { fleet: "Trucks", periodLabel: "months" }).split("\n");
  assert.equal(lines[0], "fleet,period,hold,reorder_at,expected_demand,service_level,lead_time_months,review_months,"
    + "per_failure,repairable,turnaround_months,unit_cost,hold_cost");
  assert.equal(lines[1], "Trucks,1,5,5,2.4,0.9,2,0,1,no,,100,500");
  assert.equal(fleetSparesCsv({ status: "needs_lead_time" }), "");
});

test("expected use never shows scientific notation", () => {
  assert.equal(useText(2.5e-4), "< 0.01");
  assert.equal(useText(0.0099), "< 0.01");
  assert.equal(useText(0.01), "≈ 0.01");
  assert.equal(useText(0.2512), "≈ 0.25");
  assert.equal(useText(1.34), "≈ 1.3");
  assert.equal(useText(0), "0");
  assert.equal(useText(null), "—");
});

test("a lead time in the forecast's periods reads back in days, weeks or months", () => {
  assert.equal(leadTimeHint(0.1, "years"), "0.1 years ≈ 5.2 weeks");
  assert.equal(leadTimeHint("", "years"), "5 weeks would be 0.096 years");
  assert.equal(leadTimeHint("", "months"), "5 weeks would be 1.1 months");
  assert.equal(leadTimeHint(2, "months"), "2 months ≈ 8.7 weeks");
  assert.equal(leadTimeHint(0.25, "years"), "0.25 years ≈ 3 months");
  assert.equal(leadTimeHint(10, "days"), "");
  assert.equal(leadTimeHint(1, "weeks"), "1 week ≈ 7 days");
  assert.equal(leadTimeHint(3, "weeks"), "");
  assert.equal(leadTimeHint("", "weeks"), "");
  assert.equal(leadTimeHint(1, "shifts"), "");
  assert.equal(leadTimeHint("", "shifts"), "");
});

// 12 Nov review: the card said "Hold 2" while the table by quarter said 3 from
// quarter 2. The card now shows the rise the server reports.
test("the hold shows a later rise, so the card agrees with the table", () => {
  const sp = { status: "ok", hold: 2, hold_rising: { hold: 3, from_period: 2, peak_period: 2 } };
  assert.equal(holdText(sp), "2 → 3");
  assert.equal(risingText(sp, "quarters"), "3 from quarter 2");
  assert.equal(risingText({ hold: 1, hold_rising: { hold: 3, from_period: 3, peak_period: 5 } }, "quarters"), "3 by quarter 5");
  assert.equal(holdText({ hold: 4 }), "4");
  assert.equal(risingText({ hold: 4 }, "months"), "");
});

test("the fleet spares CSV rounds expected use", () => {
  const sp = { status: "ok", service_level: 0.95, per_failure: 1, lead_time: 1,
               per_period: [{ period: 1, hold: 2, reorder_at: 2, expected_demand: 0.7749999999999999 }] };
  const row = fleetSparesCsv(sp, { fleet: "Belts", periodLabel: "quarters" }).split("\n")[1];
  assert.equal(row, "Belts,1,2,2,0.775,0.95,1,,1,no,,,");
});
