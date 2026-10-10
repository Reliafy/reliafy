// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  guessTvc, initialSchedule, scheduleBody, scheduleXMax, tvcMapping, tvcPath, tvcProblems, tvcSummaryParts,
} from "./tvcData.js";

const COLS = ["pump", "start_h", "stop_h", "censored", "load_pct"];
const FACTS = {
  pump: { dtype: "object", nUnique: 30, values: null, blanks: 0 },
  start_h: { dtype: "int64", nUnique: 60, values: null, blanks: 0 },
  stop_h: { dtype: "int64", nUnique: 80, values: null, blanks: 0 },
  censored: { dtype: "int64", nUnique: 2, values: { 0: 25, 1: 71 }, blanks: 0 },
  load_pct: { dtype: "int64", nUnique: 3, values: { 60: 30, 75: 30, 90: 36 }, blanks: 0 },
};
const EMPTY = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "", i: "", c_invert: false, c_map: null };

test("start-stop rows with a repeating item id are recognised", () => {
  assert.deepEqual(guessTvc(COLS, FACTS, 96), { layout: "intervals", i: "pump", xl: "start_h", xr: "stop_h" });
  // Plain life data (one row per unit, no start / stop) is not.
  assert.equal(guessTvc(["hours", "censored"], { hours: { dtype: "int64" }, censored: FACTS.censored }, 30), null);
  // "hours to failure" is a time, not a stop column.
  const facts = { ...FACTS, hours_to_failure: { dtype: "int64" } };
  assert.equal(guessTvc(["pump", "start_h", "hours_to_failure"], facts, 96), null);
});

test("switching layouts clears the other layout's fields", () => {
  const m = tvcMapping({ ...EMPTY, x: "start_h", c: "censored", n: "x" }, "intervals", COLS, FACTS, 96);
  assert.equal(m.i, "pump");
  assert.equal(m.xl, "start_h");
  assert.equal(m.xr, "stop_h");
  assert.equal(m.x, "");
  assert.equal(m.n, "");
  assert.equal(m.c, "censored");
  const t = tvcMapping(m, "timeline", COLS, FACTS, 96);
  assert.equal(t.x, "start_h");
  assert.equal(t.xl, "");
  assert.equal(t.xr, "");
  const off = tvcMapping(m, null);
  assert.equal(off.i, "");
  assert.equal(off.xl, "");
});

test("problems in plain words", () => {
  assert.deepEqual(tvcProblems({ ...EMPTY }, FACTS, "intervals", 0), [
    "Pick the column that names each item.",
    "Pick the columns with the start and the stop of each row.",
    "Pick the status column: it says which row ended in a failure.",
    "Tick the covariates that change over time below.",
  ]);
  const ok = { ...EMPTY, i: "pump", xl: "start_h", xr: "stop_h", c: "censored" };
  assert.deepEqual(tvcProblems(ok, FACTS, "intervals", 1), []);
  assert.match(tvcProblems({ ...ok, xl: "pump" }, FACTS, "intervals", 1)[0], /holds text/);
  assert.deepEqual(tvcProblems({ ...EMPTY, i: "pump", x: "start_h", c: "censored" }, FACTS, "timeline", 1), []);
  const words = { ...FACTS, state: { dtype: "object", values: { failed: 3, odd: 2 } } };
  assert.match(tvcProblems({ ...ok, c: "state", c_map: { failed: 0 } }, words, "intervals", 1)[0], /“odd” means/);
  // Failure modes and covariates over time don't fit together (#177 / #60).
  assert.deepEqual(tvcProblems({ ...ok, e: "mode" }, FACTS, "intervals", 1).length, 1);
  assert.match(tvcProblems({ ...ok, e: "mode" }, FACTS, "intervals", 1)[0], /failure-mode column can't/);
});

test("summary counts items, rows and (interval rows) failures", () => {
  const ok = { ...EMPTY, i: "pump", xl: "start_h", xr: "stop_h", c: "censored" };
  assert.deepEqual(tvcSummaryParts(ok, FACTS, 96, "intervals"), ["30 items", "96 rows", "25 failures"]);
  assert.deepEqual(tvcSummaryParts({ ...ok, c_invert: true }, FACTS, 96, "intervals"), ["30 items", "96 rows", "71 failures"]);
  assert.deepEqual(tvcSummaryParts(ok, FACTS, 96, "timeline"), ["30 items", "96 rows"]);
});

test("the schedule route sits beside the evaluate route", () => {
  assert.equal(tvcPath({ evaluate_path: "/api/evaluate/abc" }), "/api/tvc/abc");
  assert.equal(tvcPath({ evaluate_path: "/api/models/m1/evaluate" }), "/api/models/m1/tvc");
  assert.equal(tvcPath({}), null);
});

test("the opening schedule steps from the lowest to the highest value", () => {
  const fields = [{ name: "load_pct", type: "number", default: 75.46, min: 60, max: 90 }];
  assert.deepEqual(initialSchedule(fields, 9600), [
    { id: 0, t: 0, values: { load_pct: 60 } },
    { id: 1, t: 4800, values: { load_pct: 90 } },
  ]);
  const flat = [{ name: "load_pct", type: "number", default: 5, min: 5, max: 5 }];
  assert.equal(initialSchedule(flat, 9600).length, 1);
});

test("schedule rows go to the route as numbers, or say what's wrong", () => {
  const fields = [{ name: "load_pct", type: "number" }, { name: "duty", type: "category" }];
  assert.deepEqual(scheduleBody([{ t: "5", values: { load_pct: "60", duty: "low" } },
                                 { t: "4000", values: { load_pct: 90, duty: "high" } }], fields), {
    schedule: [{ t: 0, values: { load_pct: 60, duty: "low" } }, { t: 4000, values: { load_pct: 90, duty: "high" } }],
  });
  assert.match(scheduleBody([{ t: 0, values: { load_pct: "" } }], fields).error, /must be a number/);
  assert.match(scheduleBody([{ t: 0, values: { load_pct: 1 } }, { t: "", values: { load_pct: 1 } }], fields).error, /time of 0/);
  assert.match(scheduleBody([{ t: 0, values: { load_pct: 1 } }, { t: 0, values: { load_pct: 1 } }], fields).error, /same time/);
});

test("the axis reaches past the last change", () => {
  assert.equal(scheduleXMax([{ t: 0 }, { t: 4000 }], 9600), null);
  assert.equal(scheduleXMax([{ t: 0 }, { t: 12000 }], 9600), 15000);
});
