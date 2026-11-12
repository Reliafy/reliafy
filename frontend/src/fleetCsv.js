// A fleet forecast as CSV: one row per item, the fleet's totals, then one row
// per period. Numbers are rounded like the screen (csvNumber: 4 significant
// figures); the inputs the user typed (current use, rates) are kept as typed.
import { csvNumber, toCsv } from "./csv.js";

export function fleetForecastCsv({ items = [], perItem = {}, fields = [], defaultRate, covariateDefault = () => "",
                                   forecast = {}, repairable = false }) {
  const n = csvNumber;
  const header = ["item", "current_use", "rate_per_period", ...fields.map((f) => f.name),
                  "prob_any_failure", "expected_failures"];
  if (repairable) header.push("next_service_at", "prob_failure_before_service");
  const rows = [header, ...items.map((it) => {
    const r = perItem[it.id] || {};
    const row = [it.name, it.current_use, it.rate ?? defaultRate,
                 ...fields.map((f) => r.covariates?.[f.name] ?? it.covariates?.[f.name] ?? covariateDefault(f) ?? ""),
                 n(r.prob_any) ?? "", n(r.expected) ?? ""];
    if (repairable) row.push(it.next_service_at ?? "", n(r.prob_before_service) ?? "");
    return row;
  })];
  rows.push([]);
  rows.push(["fleet_expected", n(forecast.expected) ?? ""]);
  rows.push(["interval_p5", n(forecast.interval?.[0]) ?? "", "interval_p95", n(forecast.interval?.[1]) ?? ""]);
  if (forecast.per_period_interval) {
    rows.push([]);
    rows.push(["period", "expected", "p5", "p95"]);
    (forecast.per_period || []).forEach((v, i) =>
      rows.push([i + 1, n(v), n(forecast.per_period_interval[i]?.[0]) ?? "", n(forecast.per_period_interval[i]?.[1]) ?? ""]));
  }
  // The strategy (renewals forecasts): failures, planned replacements, parts and
  // cost per period and per year, each with its 90% range, for a budget sheet.
  const st = forecast.strategy;
  if (st && Array.isArray(st.per_period)) {
    const keys = ["failures", "planned", "parts", ...(st.total?.cost ? ["cost"] : [])];
    const head = keys.flatMap((k) => [k, `${k}_p5`, `${k}_p95`]);
    const cells = (r) => keys.flatMap((k) => [n(r[k]?.expected) ?? "", n(r[k]?.interval?.[0]) ?? "",
                                               n(r[k]?.interval?.[1]) ?? ""]);
    rows.push([]);
    rows.push(["strategy", st.kind, ...(st.kind === "age" ? ["replace_at", st.replace_at] : [])]);
    rows.push(["period", ...head]);
    st.per_period.forEach((r) => rows.push([r.period, ...cells(r)]));
    if (Array.isArray(st.yearly) && st.yearly.length) {
      rows.push([]);
      rows.push(["year", "from_period", "to_period", ...head]);
      st.yearly.forEach((y) => rows.push([y.year, y.from_period, y.to_period, ...cells(y)]));
    }
  }
  return toCsv(rows);
}
