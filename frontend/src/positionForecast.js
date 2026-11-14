// The Maintenance tab's Forecast view (PositionForecast.jsx): words and numbers for the screen,
// from GET /api/maintenance/positions/{id}/forecast (backend/maintenance/position_forecast.py).
import { formatCost } from "./money.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// A period's label: "Nov 2026", "Q4 2026", "2027"; a first period cut short says from when.
export function periodLabel(row, period, first = false) {
  const [y, m, d] = row.start.split("-").map(Number);
  let text = period === "year" ? String(y) : period === "quarter" ? `Q${Math.floor((m - 1) / 3) + 1} ${y}` : `${MONTHS[m - 1]} ${y}`;
  if (first && d !== 1) text += ` (from ${d} ${MONTHS[m - 1]})`;
  else if (first && period !== "month" && (period === "year" ? m !== 1 : (m - 1) % 3 !== 0)) text += ` (from ${d} ${MONTHS[m - 1]})`;
  return text;
}

// A number to 3 significant figures for the screen, never a 15-digit float.
export function sig(v, digits = 3) {
  if (v == null || !Number.isFinite(Number(v))) return "";
  const n = Number(v);
  if (n === 0) return "0";
  if (Math.abs(n) >= 100) return Math.round(n).toLocaleString("en-GB");
  return Number(n.toPrecision(digits)).toLocaleString("en-GB", { maximumFractionDigits: 6 });
}

export function hoursText(v) {
  return v == null ? "—" : `${sig(v)} h`;
}

// Whole dollars from $100 (no "$105.2"), 3 significant figures below.
export function moneyText(v) {
  if (v == null) return "—";
  return Math.abs(v) >= 100 ? formatCost(Math.round(v), undefined, { sig: 15 }) : formatCost(v, undefined, { sig: 3 });
}

// "0.62 (0 to 1)": expected failures with their 90% range when there is one.
// A range whose ends are the same (0 to 0 in a quiet month) isn't shown.
export function failuresText(value, range) {
  if (value == null) return "—";
  const r = range && range[0] != null && range[1] != null && range[1] > range[0] ? ` (${sig(range[0])} to ${sig(range[1])})` : "";
  return `${sig(value, 2)}${r}`;
}

export function costRangeText(value, range) {
  if (value == null) return "—";
  const r = range && range[0] != null && range[1] != null && range[1] > range[0] ? ` (${moneyText(range[0])} to ${moneyText(range[1])})` : "";
  return `${moneyText(value)}${r}`;
}

// The tasks done in a period that aren't routine: those due at most `few` times in the whole forecast
// (a service, an overhaul), so the weekly round doesn't fill every row.
export function besidesRoutine(row, tasks, few = 4) {
  const count = Object.fromEntries((tasks || []).map((t) => [t.id, t.count]));
  const seen = new Set();
  const out = [];
  for (const d of row.due || []) {
    if ((count[d.task_id] ?? 0) > few || seen.has(d.task_id)) continue;
    seen.add(d.task_id);
    const [, m, day] = d.date.split("-").map(Number);
    out.push(`${d.name} (${day} ${MONTHS[m - 1]}${d.overdue ? ", overdue" : ""})`);
  }
  return out;
}

// A day-first date ("14 Nov 2026") from an ISO date, as the design system writes dates.
export function dayText(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

// A task's interval in words: "every week", "every 2,000 hours"; a pattern's own words
// ("the first Saturday of every month") pass through.
export function everyText(limit) {
  const m = /^(\d+(?:\.\d+)?) ([a-z ]+)$/i.exec(String(limit || "").trim());
  if (!m) return limit || "";
  const n = Number(m[1]);
  const unit = m[2];
  if (n === 1) return `every ${unit.replace(/s$/, "")}`;
  return `every ${n.toLocaleString("en-GB")} ${unit}`;
}

// A task's dates in short: the first few, then how many more.
export function datesText(dates, shown = 4) {
  const words = dates.slice(0, shown).map(dayText);
  const more = dates.length - shown;
  return more > 0 ? `${words.join(", ")} and ${more} more` : words.join(", ") || "none in this time";
}

// What a row's cell rests on, for its title: hours, work and failures each say where they come from.
export function restsOn(fc, what) {
  if (what === "hours") return fc.hours_basis || "No operating plan and no hours readings here.";
  if (what === "work") return "Each task assumed done on its due date; labour from each task's LSA, cost from its cost each time.";
  if (what === "failures") {
    if (!fc.models?.length) return "No life models in use on the positions here.";
    return fc.models.map((m) => `${m.position.name}: ${m.rests_on}`).join("\n");
  }
  return "";
}
