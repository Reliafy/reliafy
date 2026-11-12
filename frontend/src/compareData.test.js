import { test } from "node:test";
import assert from "node:assert/strict";
import { parseColumn, statusReading } from "./compareData.js";

test("a text status column is read as the Data step reads it, never as all failures", () => {
  const csv = "Hours,Result\n100,Failed\n200,Running\n300,F\n400,S\n500,suspended\n";
  assert.deepEqual(parseColumn(csv, "Hours", "Result"), { x: [100, 200, 300, 400, 500], c: [0, 1, 0, 1, 1] });
  // 0/1 codes keep their meaning; a "failed" column's 1 is a failure.
  assert.deepEqual(parseColumn("t,censored\n1,0\n2,1\n", "t", "censored").c, [0, 1]);
  assert.deepEqual(parseColumn("t,failed\n1,1\n2,0\n", "t", "failed").c, [0, 1]);
  // A value it can't place is refused, by name.
  assert.throws(() => parseColumn("t,state\n1,Failed\n2,Mystery\n", "t", "state"), /“Mystery”/);
  assert.deepEqual(parseColumn("t\n1\n2\n", "t", null), { x: [1, 2] });
});

test("statusReading says how a status column reads", () => {
  assert.equal(statusReading({ Failed: 26, Running: 19 }, "Status"), "26 failed, 19 still running");
  assert.equal(statusReading({ F: 2, "??": 1 }, "Status"), "2 failed, 0 still running, 1 not read");
  assert.equal(statusReading(null, "Status"), null);
});
