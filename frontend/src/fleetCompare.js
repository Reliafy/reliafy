// Saved forecasts side by side (Forecasts list, 2–4 ticked): one row per
// figure, one column per forecast. Pure, so `node --test src/` covers it.
import { formatNumber } from "./format.js";
import { formatCost } from "./money.js";

export const MAX_COMPARE = 4;

const range = (block, fmt) => {
  const [lo, hi] = block?.interval || [];
  return lo == null || hi == null ? "" : ` (${fmt(lo)}–${fmt(hi)})`;
};
const n3 = (v) => formatNumber(v, { sig: 3 });
const plural = (label, n) => (Number(n) === 1 ? String(label || "periods").replace(/s$/i, "") : String(label || "periods"));

function methodText(f) {
  const s = f.settings || {};
  const fc = f.forecast || {};
  if (f.model_kind === "recurrent") return "Every failure (repairable)";
  if ((s.method || "renewals") === "single") return "First failures only";
  if (fc.strategy?.kind === "age" || s.strategy === "age") return `Replace at ${n3(s.replace_at)}${fc.unit ? ` ${fc.unit.toLowerCase()}` : ""}`;
  return "Run to failure (replaced)";
}

function sparesText(sp, label) {
  if (!sp) return "—";
  if (sp.status !== "ok") return "—";
  const lead = sp.repairable ? `repair ${n3(sp.turnaround)}` : `lead ${n3(sp.lead_time)}`;
  return `Hold ${formatNumber(sp.hold, { sig: 4 })} (${Math.round((sp.service_level || 0) * 100)}%, ${lead} ${plural(label, sp.turnaround ?? sp.lead_time)})`;
}

// ``fleets``: GET /api/fleet/fleets/{id} payloads. Returns { columns, rows }:
// columns the forecasts' names, rows [{ label, values }] with "—" where a
// forecast has no such figure. Rows no forecast has are left out.
export function compareRows(fleets, currency) {
  const cost = (v) => formatCost(v, currency, { sig: 3 });
  const rows = [
    { label: "Model", values: fleets.map((f) => f.forecast?.model_name || "—") },
    { label: "Items", values: fleets.map((f) => String((f.items || []).length)) },
    { label: "Horizon", values: fleets.map((f) => {
      const p = f.settings?.periods ?? 12;
      return `${p} ${plural(f.settings?.period_label || "months", p)}`;
    }) },
    { label: "Usage a period", values: fleets.map((f) => (Number(f.settings?.default_rate) > 0
      ? `${n3(f.settings.default_rate)}${f.forecast?.unit ? ` ${plural(f.forecast.unit.toLowerCase(), f.settings.default_rate)}` : ""}`
      : "each item's own")) },
    { label: "Counting", values: fleets.map(methodText) },
    { label: "Failures, whole horizon", values: fleets.map((f) => (f.forecast?.status === "ok"
      ? `≈ ${n3(f.forecast.expected)}${range({ interval: f.forecast.interval }, n3)}` : "—")) },
    { label: "Failures, year 1", values: fleets.map((f) => {
      const y = f.forecast?.strategy?.yearly?.[0];
      return y ? `≈ ${n3(y.failures.expected)}${range(y.failures, n3)}` : "—";
    }) },
    { label: "Planned replacements", values: fleets.map((f) => {
      const st = f.forecast?.strategy;
      return st?.kind === "age" ? `≈ ${n3(st.total.planned.expected)}${range(st.total.planned, n3)}` : "—";
    }) },
    { label: "Spares to hold", values: fleets.map((f) => sparesText(f.forecast?.spares, f.settings?.period_label)) },
    { label: "Cost, whole horizon", values: fleets.map((f) => {
      const c = f.forecast?.strategy?.total?.cost;
      return c ? `${cost(c.expected)}${range(c, cost)}` : "—";
    }) },
  ];
  return {
    columns: fleets.map((f) => f.name),
    rows: rows.filter((r) => r.label === "Model" || r.values.some((v) => v !== "—")),
  };
}
