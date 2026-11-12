import { test } from "node:test";
import assert from "node:assert/strict";
import {
  analysisName, appendNotes, calculatorFor, linksEvidence, money, pct, rationale, roundDown, taskUnit, withUnit,
} from "./rcmIntervals.js";

const DAY = new Date(2026, 10, 9);

test("each scheduled kind opens its calculator; the others none", () => {
  assert.equal(calculatorFor("on_condition").key, "pf");
  assert.equal(calculatorFor("failure_finding").key, "ff");
  assert.equal(calculatorFor("fixed_interval").key, "fixed");
  assert.equal(calculatorFor("rtf"), null);
});

test("units and numbers read as people write them", () => {
  assert.equal(taskUnit("Hours"), "hours");
  assert.equal(taskUnit("mth"), "months");
  assert.equal(taskUnit("Flights"), "flights");
  assert.equal(withUnit(1, "months"), "1 month");
  assert.equal(withUnit(2, "Weeks"), "2 weeks");
  assert.equal(money(2000), "$2,000");
  assert.equal(money(204.357), "$204");
  assert.equal(pct(0.00833), "0.83%");
  assert.equal(pct(0.25), "25%");
  assert.equal(roundDown(493.4), 493);
  // What the button says is what's saved: 14,885 shows as 14,900, so it's taken down to 14,800.
  assert.equal(roundDown(14885.2), 14800);
  assert.equal(withUnit(roundDown(14885.2), "hours"), "14,800 hours");
  assert.equal(roundDown(1234.9), 1230);
  assert.equal(roundDown(250000), 250000);
  assert.equal(roundDown(2.39), 2.3);
  assert.equal(roundDown(0), null);
});

test("the P-F rationale names only the inputs given", () => {
  const alone = rationale("pf", { pf_interval: 10, pf_unit: "weeks", detection_probability: 1 },
    { basis: "half_pf", at_recommended: {} }, { value: 5, unit: "weeks" }, DAY);
  assert.equal(alone, "Interval from the P-F calculator (9 Nov 2026): P-F 10 weeks → 5 weeks (half the P-F interval).");
  const net = rationale("pf", { pf_interval: 10, pf_unit: "weeks", act_time: 8 },
    { basis: "net_pf", at_recommended: {} }, { value: 2, unit: "weeks" }, DAY);
  assert.equal(net, "Interval from the P-F calculator (9 Nov 2026): P-F 10 weeks, time to act 8 weeks → 2 weeks (the net P-F interval).");
  const priced = rationale("pf",
    { pf_interval: 10, pf_unit: "weeks", onset_rate: 0.5, inspection_cost: 20, found_cost: 200, failure_cost: 2000, detection_probability: 1 },
    { basis: "half_pf", at_recommended: { cost_rate: 308 }, run_to_failure_cost_rate: 1000, cost_optimal: { at_recommended: { cost_rate: 220 } } },
    { value: 2, unit: "months", cheapest: true }, DAY);
  assert.equal(priced, "Interval from the P-F calculator (9 Nov 2026): P-F 10 weeks, onset 0.5/year, inspection $20, found $200, "
    + "failure $2,000 → 2 months (the cheapest interval); cost rate $220/year (letting it fail: $1,000/year).");
  const doubtful = rationale("pf", { pf_interval: 3, pf_unit: "days", detection_probability: 0.8 },
    { basis: "half_pf", at_recommended: {} }, { value: 36, unit: "hours" }, DAY);
  assert.match(doubtful, /P-F 3 days, detection 80% → 36 hours/);
});

test("the failure-finding rationale names an assumed target", () => {
  const line = rationale("ff", { target_assumed: true, test_cost: 50 },
    { device: { source: "rate", rate: 0.1 }, target_unavailability: 0.01, at_recommended: { mean_unavailability: 0.0083, cost_rate: 300 } },
    { value: 2, unit: "months" }, DAY);
  assert.equal(line, "Interval from the failure-finding calculator (9 Nov 2026): device 0.1 failures/year, target unavailability 1% (assumed), "
    + "test $50 → 2 months; mean unavailability 0.83%, cost rate $300/year.");
});

test("the replacement rationale is in the model's unit", () => {
  const line = rationale("fixed", { planned_cost: 150, unplanned_cost: 400, model_name: "Bearings" },
    { distribution: "Weibull", unit: "Days", optimal_cost_rate: 1.13, run_to_failure_cost_rate: 1.23, savings: 0.08 },
    { value: 298, unit: "days" }, DAY);
  assert.equal(line, "Interval from the replacement calculator (9 Nov 2026): Weibull model “Bearings”, planned $150, unplanned $400 → 298 days; "
    + "cost rate $1.13/day against $1.23/day running to failure (8% saving).");
});

test("notes keep what's there, the paragraph after a blank line", () => {
  assert.equal(appendNotes("Seal weeps first.\n", "Line."), "Seal weeps first.\n\nLine.");
  assert.equal(appendNotes("", "Line."), "Line.");
  assert.equal(appendNotes(null, "Line."), "Line.");
});

test("the saved analysis is named for the mode; evidence only when there's none", () => {
  assert.equal(analysisName("Seal leaks", "pf"), "Seal leaks: check interval");
  assert.ok(analysisName("x".repeat(300), "ff").length <= 120);
  assert.equal(linksEvidence({ evidence: null }), true);
  assert.equal(linksEvidence({ evidence: { type: "report", id: "r1" } }), false);
});
