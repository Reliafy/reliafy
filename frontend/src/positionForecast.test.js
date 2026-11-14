import { test } from "node:test";
import assert from "node:assert/strict";
import { besidesRoutine, costRangeText, datesText, failuresText, periodLabel, restsOn, sig } from "./positionForecast.js";

test("period labels say where a cut-short first period starts", () => {
  assert.equal(periodLabel({ start: "2026-11-16" }, "month", true), "Nov 2026 (from 16 Nov)");
  assert.equal(periodLabel({ start: "2026-12-01" }, "month"), "Dec 2026");
  assert.equal(periodLabel({ start: "2026-11-16" }, "quarter", true), "Q4 2026 (from 16 Nov)");
  assert.equal(periodLabel({ start: "2027-01-01" }, "year"), "2027");
});

test("numbers are rounded for the screen, with their 90% range", () => {
  assert.equal(sig(0.62239), "0.622");
  assert.equal(sig(12884.000000001), "12,884");
  assert.equal(sig(null), "");
  assert.equal(failuresText(0.6224, [0, 1]), "0.62 (0 to 1)");
  assert.equal(failuresText(null, null), "—");
  assert.equal(failuresText(0.022, [0, 0]), "0.022");
  assert.match(costRangeText(2987.56, [0, 4800]), /^\$2,988 \(\$0 to \$4,800\)$/);
});

test("besides the routine lists the rare tasks only, once each", () => {
  const tasks = [{ id: "i", count: 55 }, { id: "s", count: 2 }];
  const row = { due: [{ task_id: "i", name: "Inspect", date: "2027-04-05" }, { task_id: "s", name: "Service", date: "2027-04-08" }] };
  assert.deepEqual(besidesRoutine(row, tasks), ["Service (8 Apr)"]);
});

test("dates in short, and what each column rests on", () => {
  assert.equal(datesText(["2027-04-08", "2027-09-30"]), "8 Apr 2027, 30 Sep 2027");
  assert.equal(datesText(["2027-01-01", "2027-02-01", "2027-03-01", "2027-04-01", "2027-05-01"]),
    "1 Jan 2027, 1 Feb 2027, 1 Mar 2027, 1 Apr 2027 and 1 more");
  assert.equal(datesText([]), "none in this time");
  const fc = { hours_basis: "Hours from the operating plan", models: [{ position: { name: "Ring" }, rests_on: "Weibull life" }] };
  assert.equal(restsOn(fc, "hours"), "Hours from the operating plan");
  assert.equal(restsOn(fc, "failures"), "Ring: Weibull life");
  assert.match(restsOn({ models: [] }, "failures"), /No life models/);
});
