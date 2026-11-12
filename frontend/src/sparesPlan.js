// Spares stock levels (#31): how the hold, reorder point and stock-out risk read,
// the risk at a stock the user types (from the answer's risk curve), and the
// stocking plan as CSV, for a position class's spares and a fleet's part.
import { formatNumber, formatPercent } from "./format.js";
import { csvNumber, toCsv } from "./csv.js";

export const SERVICE_LEVELS = [0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999];

// "95%", "99.5%".
export function levelText(level) {
  if (level == null) return "";
  return `${Number((level * 100).toFixed(1))}%`;
}

// A chance of running out: "31%", or "under 1%" (a simulation's 0 is a small
// chance, not none).
export function riskText(p) {
  if (p == null) return "—";
  return p < 0.005 ? "under 1%" : formatPercent(p);
}

// Expected use over the window, as the card shows it: "≈ 1.3", "≈ 0.25", or
// "< 0.01" for a tiny value (never "2.5e-4"), "0" for none.
export function useText(v) {
  if (v == null || v === "" || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  if (n === 0) return "0";
  if (n < 0.01) return "< 0.01";
  return `≈ ${formatNumber(n, { sig: 2 })}`;
}

// A lead time typed in the forecast's periods, read back in days, weeks or
// months so "0.1 years" can be checked against a supplier's "5 weeks":
// "0.1 years ≈ 5.2 weeks". Before anything is typed, an example in the
// period: "5 weeks would be 0.096 years".
// Empty for a period that isn't a calendar unit ("shifts").
const PERIOD_DAYS = { day: 1, week: 7, month: 30.4375, quarter: 91.3125, year: 365.25 };

export function leadTimeHint(value, periodLabel) {
  const key = String(periodLabel || "").trim().toLowerCase();
  const per = PERIOD_DAYS[key] ?? (key.endsWith("s") ? PERIOD_DAYS[key.slice(0, -1)] : undefined);
  if (!per) return "";
  const plural = key.endsWith("s") ? key : `${key}s`;
  if (value === "" || value == null) {
    return per === 7 ? "" : `5 weeks would be ${formatNumber(35 / per, { sig: 2 })} ${plural}`;
  }
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "";
  const days = n * per;
  const [size, word] = days < 14 ? [1, "day"] : days < 90 ? [7, "week"] : [PERIOD_DAYS.month, "month"];
  if (size === per) return "";
  const shown = formatNumber(days / size, { sig: 2 });
  return `${formatNumber(n, { sig: 6 })} ${n === 1 ? key.replace(/s$/, "") : plural} ≈ ${shown} ${word}${shown === "1" ? "" : "s"}`;
}

// The chance a stock runs out, read off a risk curve ([[stock, chance], ...],
// ascending): the level at or below it. Past the curve's end it's under 0.1%.
export function riskAt(curve, stock) {
  if (!curve?.length || stock === "" || stock == null || !Number.isFinite(Number(stock))) return null;
  const s = Number(stock);
  if (s < curve[0][0]) return 1;
  let p = curve[0][1];
  for (const [level, chance] of curve) {
    if (level > s + 1e-9) break;
    p = chance;
  }
  return p;
}

// "60 days", "30 days (assumed)", "1 day".
export function daysText(days, basis) {
  if (days == null) return "—";
  const text = `${formatNumber(days)} day${Number(days) === 1 ? "" : "s"}`;
  return basis === "assumed" ? `${text} (assumed)` : text;
}

// What a part's hold covers: its lead time (and review), or a repairable part's
// repair turnaround.
export function windowText(st) {
  if (!st) return "";
  if (st.repairable) return `repair turnaround ${daysText(st.turnaround_days)}`;
  const lead = daysText(st.lead_time_days, st.lead_time_basis);
  return st.review_days ? `${lead} lead time + ${daysText(st.review_days)} review` : `${lead} lead time`;
}

// The window a hold covers, in words: "the lead time", "the lead time and review
// period", "the repair turnaround".
export function overText(repairable, review) {
  if (repairable) return "the repair turnaround";
  return review ? "the lead time and review period" : "the lead time";
}

// The class's stocking plan, one row per part and period: the stock to hold and
// the reorder point for a window starting then, with that period's expected use.
export function stockingCsv(spares = [], { positionClass = "", period = "month" } = {}) {
  const header = ["position_class", "part_number", "part", "unit", "period_start", `expected_use_this_${period}`,
    `likely_up_to_this_${period}_p90`, "hold", "reorder_at", "service_level", "lead_time_days", "review_days",
    "repairable", "turnaround_days", "usable_now", "stock_out_risk_at_usable_now", "unit_cost", "hold_cost"];
  const rows = [header];
  for (const s of spares) {
    const st = s.stocking;
    if (!st) continue;
    (st.per_period || []).forEach((p, i) => {
      const use = s.per_period?.[i] || {};
      rows.push([positionClass, s.part.part_number, s.part.name, s.unit || "each", p.start, csvNumber(use.mean) ?? "",
        csvNumber(use.p90) ?? "", p.hold, p.reorder_at ?? "", st.service_level, st.repairable ? "" : st.lead_time_days,
        st.repairable ? "" : st.review_days, st.repairable ? "yes" : "no", st.turnaround_days ?? "",
        i === 0 ? s.usable_on_hand : "", i === 0 ? csvNumber(st.risk_at_stock) : "", st.unit_cost ?? "",
        st.unit_cost != null ? csvNumber(p.hold * st.unit_cost) : ""]);
    });
  }
  return toCsv(rows);
}

// The fleet's headline hold: "2", or "2 → 3" when a later period needs more
// (the server's hold_rising), so the card agrees with the table by period.
export function holdText(sp) {
  if (!sp || sp.hold == null) return "—";
  const now = formatNumber(sp.hold);
  return sp.hold_rising ? `${now} → ${formatNumber(sp.hold_rising.hold)}` : now;
}

// Under the hold: "3 from quarter 2" (one step up) or "3 by quarter 5" (more
// than one; the table by period has each). Empty when the need doesn't rise.
export function risingText(sp, periodLabel = "periods") {
  const r = sp?.hold_rising;
  if (!r) return "";
  const word = String(periodLabel || "periods").replace(/s$/i, "");
  const how = r.peak_period === r.from_period ? "from" : "by";
  return `${formatNumber(r.hold)} ${how} ${word} ${r.peak_period}`;
}

// A fleet's replacement-part plan: one row per period.
export function fleetSparesCsv(sp, { fleet = "", periodLabel = "periods" } = {}) {
  if (!sp || sp.status !== "ok") return "";
  const rows = [["fleet", "period", "hold", "reorder_at", "expected_demand", "service_level",
    `lead_time_${periodLabel}`, `review_${periodLabel}`, "per_failure", "repairable", `turnaround_${periodLabel}`,
    "unit_cost", "hold_cost"]];
  for (const p of sp.per_period || []) {
    rows.push([fleet, p.period, p.hold, p.reorder_at ?? "", csvNumber(p.expected_demand), sp.service_level,
      sp.lead_time ?? "", sp.review ?? "", sp.per_failure, sp.repairable ? "yes" : "no", sp.turnaround ?? "",
      sp.unit_cost ?? "", sp.unit_cost != null ? csvNumber(p.hold * sp.unit_cost) : ""]);
  }
  return toCsv(rows);
}

// Save text as a file (CSV exports).
export function saveText(text, filename, type = "text/csv;charset=utf-8") {
  saveBlob(new Blob([text], { type }), filename);
}
// Save a blob the server sent as a file (an Excel export).
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
