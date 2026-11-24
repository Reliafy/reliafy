// The failure ranking (the Explorer's History tab, Ranking): which positions, parts or
// failure modes below the row fail most, by count, rate, downtime or cost, over a window.
// The server works the numbers out (backend/maintenance/failure_ranking.py); these pure
// functions choose what to ask, word the cells and build the CSV and the Pareto chart.
// Tested in failureRanking.test.js.

import { formatNumber } from "./format.js";

export const VIEWS = [
  { value: "reports", label: "Reports" },
  { value: "ranking", label: "Ranking" },
];
export const RANK_BY = [
  { value: "failures", label: "Failures" },
  { value: "rate", label: "Failure rate" },
  { value: "downtime", label: "Downtime" },
  { value: "cost", label: "Cost" },
];
export const GROUP_BY = [
  { value: "position", label: "Position" },
  { value: "part", label: "Part" },
  { value: "failure_mode", label: "Failure mode" },
];
export const WINDOWS = [
  { value: "12m", label: "Last 12 months" },
  { value: "all", label: "All" },
  { value: "range", label: "Dates" },
];
export const DEFAULT_RANKING = { group_by: "position", rank_by: "failures", window: "12m", since: "", until: "" };

// The query the server takes.
export function rankingParams(positionId, opts = {}) {
  const o = { ...DEFAULT_RANKING, ...opts };
  const out = { position_id: positionId, group_by: o.group_by, rank_by: o.rank_by, window: o.window };
  if (o.window === "range") {
    if (o.since) out.since = o.since;
    if (o.until) out.until = o.until;
  }
  return out;
}

const n0 = (v) => Number(v || 0).toLocaleString("en-AU");

export const hoursText = (h) => (h == null ? "—" : `${formatNumber(h)} h`);
export const rateText = (r) => (r == null ? "—" : formatNumber(r.value));
export const rangeText = (r) => (r == null ? "" : `${formatNumber(r.lower)} to ${formatNumber(r.upper)}`);
export const shareText = (s) => (s == null ? "—" : `${Math.round(s * 100)}%`);
export function moneyText(v) {
  if (v == null) return "—";
  return `$${Number(v).toLocaleString("en-AU", { maximumFractionDigits: v >= 100 ? 0 : 2 })}`;
}
export const downtimeText = (v) => (v == null ? "—" : `${formatNumber(v)} h`);

// "Unit", "Part", "Failure mode": the first column's heading.
export function groupHeading(groupBy, scopeKind) {
  if (groupBy === "position") return scopeKind === "design" ? "Unit" : "Position";
  return groupBy === "part" ? "Part" : "Failure mode";
}

// What the row's Open in › Failure reports filters the list to (null: it opens the node instead).
export function reportsFilter(row, window) {
  if (!row?.filter || row.filter.position_id) return null;
  const out = { status: "all", failure_mode_id: row.filter.failure_mode_id || "", part_id: row.filter.part_id || "",
    since: window?.since || "", until: window?.until || "" };
  return out.failure_mode_id || out.part_id ? out : null;
}

// The table as a CSV: the numbers as drawn, plus the unrounded ones.
export function rankingCsv(data) {
  const head = [groupHeading(data.group_by, data.scope?.kind), "Rank", "Failures", "No fault found",
    "Operating hours", "Rate per 1,000 h", "Rate 90% lower", "Rate 90% upper", "Expected at the pooled rate",
    "P-value", "Downtime (h)", "Cost", "Share", "Cumulative share", "What it means"];
  const rows = (data.rows || []).map((r) => [
    r.name, r.rank, r.failures, r.no_fault_found, r.hours ?? "", r.rate_per_1000h?.value ?? "",
    r.rate_per_1000h?.lower ?? "", r.rate_per_1000h?.upper ?? "", r.expected ?? "", r.p_value ?? "",
    r.downtime_hours ?? "", r.cost ?? "", r.share ?? "", r.cumulative_share ?? "", r.sentence || "",
  ]);
  return [head, ...rows];
}

// The Pareto chart: a bar a group by the rank-by metric, and the cumulative share (0–100%).
export function paretoSeries(data, max = 15) {
  const rows = (data?.rows || []).filter((r) => r.value != null && r.value > 0).slice(0, max);
  return {
    x: rows.map((r) => r.name),
    // Tick labels cut to fit a phone; the full name is in the hover.
    labels: rows.map((r) => (r.name.length > 22 ? `${r.name.slice(0, 21)}…` : r.name)),
    y: rows.map((r) => r.value),
    cumulative: rows.map((r) => (r.cumulative_share == null ? null : r.cumulative_share * 100)),
  };
}

export const METRIC_AXIS = {
  failures: "Failures", rate: "Failures per 1,000 h", downtime: "Downtime (h)", cost: "Cost ($)",
};

// "12 failures · 1 no fault found · 3,120 operating hours".
export function totalsLine(t) {
  if (!t) return "";
  const bits = [`${n0(t.failures)} ${t.failures === 1 ? "failure" : "failures"}`];
  if (t.no_fault_found) bits.push(`${n0(t.no_fault_found)} no fault found`);
  if (t.hours) bits.push(`${formatNumber(t.hours)} operating hours`);
  if (t.rate_per_1000h) {
    bits.push(`${formatNumber(t.rate_per_1000h.value)} per 1,000 h (90% two-sided ${rangeText(t.rate_per_1000h)})`);
  }
  return bits.join(" · ");
}
