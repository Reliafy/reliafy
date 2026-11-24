import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_RANKING, GROUP_BY, RANK_BY, VIEWS, groupHeading, paretoSeries, rangeText, rankingCsv, rankingParams, reportsFilter,
  totalsLine,
} from "./failureRanking.js";
import { queryParams } from "./failureReports.js";

test("the History tab switches between Reports and Ranking", () => {
  assert.deepEqual(VIEWS.map((v) => v.label), ["Reports", "Ranking"]);
  assert.deepEqual(RANK_BY.map((v) => v.value), ["failures", "rate", "downtime", "cost"]);
  assert.deepEqual(GROUP_BY.map((v) => v.value), ["position", "part", "failure_mode"]);
});

test("the query: last 12 months by default; dates only with a range", () => {
  assert.deepEqual(rankingParams("p1"), { position_id: "p1", group_by: "position", rank_by: "failures", window: "12m" });
  assert.deepEqual(rankingParams("p1", { ...DEFAULT_RANKING, rank_by: "rate", group_by: "part", window: "12m", since: "2025-01-01" }),
    { position_id: "p1", group_by: "part", rank_by: "rate", window: "12m" });
  assert.deepEqual(rankingParams("p1", { window: "range", since: "2025-01-01", until: "2025-06-30" }),
    { position_id: "p1", group_by: "position", rank_by: "failures", window: "range", since: "2025-01-01", until: "2025-06-30" });
});

test("headings, ranges and the totals line", () => {
  assert.equal(groupHeading("position", "design"), "Unit");
  assert.equal(groupHeading("position", "position"), "Position");
  assert.equal(groupHeading("failure_mode"), "Failure mode");
  assert.equal(rangeText({ value: 2.5, lower: 1.0888, upper: 4.934 }), "1.09 to 4.93");
  assert.equal(totalsLine({ failures: 7, no_fault_found: 1, hours: 4800, rate_per_1000h: { value: 1.458, lower: 0.68, upper: 2.75 } }),
    "7 failures · 1 no fault found · 4,800 operating hours · 1.46 per 1,000 h (90% two-sided 0.68 to 2.75)");
});

test("Open in › Failure reports filters by mode or part, with the window; a position opens its node", () => {
  const win = { since: "2025-01-01", until: "2025-04-10" };
  assert.deepEqual(reportsFilter({ filter: { failure_mode_id: "fm1" } }, win),
    { status: "all", failure_mode_id: "fm1", part_id: "", since: "2025-01-01", until: "2025-04-10" });
  assert.equal(reportsFilter({ filter: { position_id: "p2" } }, win), null);
  assert.equal(reportsFilter({ filter: {} }, win), null);
  const q = queryParams({ status: "all", part_id: "pt1" }, { position_id: "p1" });
  assert.equal(q.part_id, "pt1");
});

test("the Pareto series and the CSV", () => {
  const data = { group_by: "position", rank_by: "failures", scope: { kind: "position" }, rows: [
    { name: "A", rank: 1, failures: 6, no_fault_found: 1, hours: 2400, value: 6, cumulative_share: 6 / 7, share: 6 / 7,
      rate_per_1000h: { value: 2.5, lower: 1.09, upper: 4.93 }, expected: 3.5, p_value: 0.142, sentence: "6 failures…" },
    { name: "B", rank: 2, failures: 1, no_fault_found: 0, hours: 2400, value: 1, cumulative_share: 1, share: 1 / 7 },
    { name: "C", rank: 3, failures: 0, value: 0, cumulative_share: 1 },
  ] };
  const s = paretoSeries(data);
  assert.deepEqual(s.x, ["A", "B"]);
  assert.deepEqual(s.y, [6, 1]);
  assert.equal(Math.round(s.cumulative[0]), 86);
  const csv = rankingCsv(data);
  assert.equal(csv[0][0], "Position");
  assert.deepEqual(csv[1].slice(0, 6), ["A", 1, 6, 1, 2400, 2.5]);
  assert.equal(csv.length, 4);
});
