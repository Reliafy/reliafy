// A position class's failure forecast (#407): how its periods, ranges and
// spares read on the class page.
import { formatNumber, formatPercent } from "./format.js";

export const FORECAST_PERIODS = [
  { id: "month", label: "Months", most: 120 },
  { id: "quarter", label: "Quarters", most: 40 },
  { id: "year", label: "Years", most: 10 },
];

const day = (iso) => new Date(`${iso}T00:00:00Z`);

// Each period's label from its start date: "16 Oct" (the year on the first and
// whenever it changes), or "2027" for years.
export function periodLabels(rows = [], period = "month") {
  let year = null;
  return rows.map((r) => {
    const d = day(r.start);
    const y = d.getUTCFullYear();
    if (period === "year") return d.toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
    const text = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
    const label = y !== year ? `${text} ${y}` : text;
    year = y;
    return label;
  });
}

// "12 months", "1 quarter".
export function horizonText(periods, period) {
  return `${periods} ${period}${periods === 1 ? "" : "s"}`;
}

// "1–6" (a P10–P90 pair); "3" when both ends agree.
export function rangeText(pair) {
  if (!pair) return "";
  const [lo, hi] = pair.map((v) => formatNumber(v));
  return lo === hi ? lo : `${lo}–${hi}`;
}

// What a spare's stock covers: "short" when the likely high end (P90) of the
// demand over the horizon is more than is usable in stock.
export function spareCover(s, period) {
  if (!s) return "";
  const n = s.covered_periods;
  const total = s.cumulative?.length || 0;
  if (n >= total) return `covers all ${horizonText(total, period)}`;
  if (n === 0) return `may run out in the first ${period} (${formatPercent(s.cumulative?.[0]?.prob_covered ?? 0)} chance it covers it)`;
  return `covers ${horizonText(n, period)} at the likely high end`;
}

// "1,290" for money (no currency is kept on class costs).
export function money(v, currency) {
  if (v == null) return "—";
  const n = Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
  return currency ? `${currency} ${n}` : n;
}

// A P10–P90 pair of amounts: "12,000–20,000", or "12,000" when both ends agree.
export function moneyRange(pair, currency) {
  if (!pair) return "";
  const [lo, hi] = pair.map((v) => money(v, currency));
  return lo === hi ? lo : `${lo}–${hi}`;
}
