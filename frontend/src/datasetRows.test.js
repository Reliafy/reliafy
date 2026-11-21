// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { ROWS_PAGE, nextWindow, numberedRows } from "./datasetRows.js";

test("rows are numbered from 1 across windows", () => {
  const first = numberedRows(["tag", "hours"], [["SP-101", 14010], ["SP-102", 8240]], 0);
  assert.deepEqual(first.columns, ["#", "tag", "hours"]);
  assert.deepEqual(first.rows, [[1, "SP-101", 14010], [2, "SP-102", 8240]]);
  const second = numberedRows(["tag", "hours"], [["SP-103", 10740]], ROWS_PAGE);
  assert.deepEqual(second.rows, [[ROWS_PAGE + 1, "SP-103", 10740]]);
});

test("the next window is a page, or what is left", () => {
  assert.equal(nextWindow(200, 1000), 200);
  assert.equal(nextWindow(900, 1000), 100);
  assert.equal(nextWindow(1000, 1000), 0);
  assert.equal(nextWindow(0, 24), 24);
});
