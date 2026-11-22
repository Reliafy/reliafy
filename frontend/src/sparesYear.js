// Spares for the year (the Explorer's Maintenance › Spares, a package's parts): how each part's
// answer reads. The server works the numbers out (maintenance get.spares_year); this words them.
import { formatDate } from "./dates.js";
import { formatNumber } from "./format.js";

// "13 Nov 2026".
export function dayText(iso) {
  return iso ? formatDate(iso) : "";
}

// When a part was last counted: "counted 10 days ago", "counted 14 weeks ago", "never counted".
export function countedText(row, today) {
  if (!row?.counted_on) return "never counted";
  const days = Math.max(0, Math.round((new Date(`${today}T00:00:00`) - new Date(`${row.counted_on}T00:00:00`)) / 864e5));
  if (days === 0) return "counted today";
  if (days < 14) return `counted ${days} day${days === 1 ? "" : "s"} ago`;
  if (days < 120) return `counted ${Math.round(days / 7)} weeks ago`;
  return `counted ${Math.round(days / 30.4375)} months ago`;
}

// A count is old once it's more than 12 weeks back (or never made): the stock may be out of date.
export function countIsOld(row, today) {
  if (!row?.counted_on) return true;
  return (new Date(`${today}T00:00:00`) - new Date(`${row.counted_on}T00:00:00`)) / 864e5 > 84;
}

// The demand: "≈ 5.4 (likely 4–7)" and its split "4.5 failures + 0.91 planned".
export function demandText(d) {
  if (!d) return "";
  return `≈ ${formatNumber(d.mean, { sig: 2 })} (likely ${formatNumber(d.p10)}–${formatNumber(d.p90)})`;
}
export function splitText(d) {
  if (!d || !(d.planned > 0)) return d && d.mean > 0 ? "all failures" : "";
  if (!(d.failures > 0.005)) return `${formatNumber(d.planned, { sig: 2 })} planned`;
  return `${formatNumber(d.failures, { sig: 2 })} failures + ${formatNumber(d.planned, { sig: 2 })} planned`;
}

// What to order: ["2 now (lands 15 Mar 2027)", "1 by 25 Oct 2027"], or [] for nothing.
export function orderLines(row) {
  const out = [];
  if (row.order_now > 0) out.push(`${formatNumber(row.order_now)} now${row.arrives ? ` (lands ${dayText(row.arrives)})` : ""}`);
  for (const o of row.order_by || []) out.push(`${formatNumber(o.qty)} by ${dayText(o.by)}`);
  return out;
}

// The service level and lead time a hold covers: "95% over 112 days".
export function holdBasis(row) {
  const lead = `${formatNumber(row.lead_time_days)} day${row.lead_time_days === 1 ? "" : "s"}`;
  return `${Math.round(row.service_level * 1000) / 10}% over ${lead}${row.lead_time_basis === "assumed" ? " (assumed)" : ""}`;
}
