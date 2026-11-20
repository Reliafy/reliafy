// A position class's failure forecast (#407): how its periods, ranges and
// spares read on the class page.
import { formatDate, formatMonth } from "./dates.js";
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
    if (period === "year") return formatMonth(d, { utc: true });
    const text = formatDate(d, { utc: true, year: false });
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

// ---- an item class's Forecast and Spares tabs (the Explorer by Classes) ----------------------

// The positions under an item class's row in the tree (its own and its sub-classes'), grouped
// by their position class: [{key, label, positions: [{id, name, item}]}] by label, and `none`:
// the positions with no position class (nothing to forecast them from). The tree is the one on
// show, so an asset opened gives its own positions alone.
export function classForecastGroups(display, row) {
  const groups = new Map();
  const none = [];
  const seen = new Set();
  const walk = (key) => {
    const r = display?.rows?.get(key);
    if (!r || seen.has(key)) return;
    seen.add(key);
    if (r.type === "pos") {
      const p = { id: r.key, name: r.ref?.name || "", item: r.ref?.item || null };
      const k = r.ref?.class_key || r.ref?.position_class || "";
      if (!k) none.push(p);
      else {
        if (!groups.has(k)) groups.set(k, { key: k, label: r.ref?.position_class || k, positions: [] });
        groups.get(k).positions.push(p);
      }
      return;
    }
    for (const kid of r.kids || []) walk(kid);
  };
  for (const kid of row?.kids || []) walk(kid);
  const list = [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
  return { groups: list, none, count: list.reduce((n, g) => n + g.positions.length, 0) + none.length };
}

// The forecast at the class's own positions, from each position class's read (`reads`: key →
// the forecast, or {error}): expected failures add, so the class's total is the sum of its
// positions' own. Each position is a row (forecast) or a reason it isn't. A position the read
// doesn't name (past the top 100 it ranks) is "not in the forecast's list".
export function scopedForecast(groups, reads) {
  const rows = [];
  const missing = [];
  let expected = 0;
  let pending = 0;
  let period = null;
  let periods = null;
  let unit = null;
  for (const g of groups || []) {
    const f = reads?.[g.key];
    if (!f) { pending += 1; continue; }
    if (f.error) {
      const reason = typeof f.error === "string" && f.error ? f.error : "its position class's forecast didn't load";
      for (const p of g.positions) missing.push({ position: p, label: g.label, reason });
      continue;
    }
    if (!f.n_forecast) {
      for (const p of g.positions) missing.push({ position: p, label: g.label, reason: f.headline || "no fitted life model for its position class yet" });
      continue;
    }
    period = period || f.period;
    periods = periods || f.periods;
    unit = unit || f.model?.unit || null;
    const risk = new Map((f.at_risk || []).map((r) => [r.position?.id, r]));
    const why = new Map((f.not_forecast || []).map((r) => [r.position?.id, r.reason]));
    for (const p of g.positions) {
      const r = risk.get(p.id);
      if (r) {
        rows.push({ ...r, label: g.label, unit: f.model?.unit || "", position: { ...r.position, name: r.position?.name || p.name } });
        expected += Number(r.expected_failures) || 0;
      } else {
        missing.push({ position: p, label: g.label, reason: why.get(p.id) || "not in the forecast's list" });
      }
    }
  }
  rows.sort((a, b) => (b.expected_failures || 0) - (a.expected_failures || 0));
  return { rows, missing, expected, pending, period, periods, unit };
}
