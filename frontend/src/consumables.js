// Consumables (Nov 2026: "Salt is added to the pool; it's not a setting nor a
// measurement, it's a consumption"): what's added at a position, as the
// Measurements tab's Consumable rows and a consumable's view show it. A row is
// GET /api/maintenance/points' `consumables` entry: {key, position, name, unit,
// part (with its stock by store) or null, listing_id, uses (newest first: on,
// qty, cost, note, work_order, from_location), lsa (the doses its position's
// tasks list)}. Pure functions, tested in consumables.test.js.

import { dayText, numberText } from "./measuringPoint.js";
import { withUnit } from "./measurementsTab.js";

const DAY = 86400000;
const ms = (d) => Date.parse(`${String(d).slice(0, 10)}T00:00:00Z`);
const iso = (t) => new Date(t).toISOString().slice(0, 10);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// How many days the state's total looks back.
export const WINDOW_DAYS = 90;

// A quantity with its unit, as people write it: "20 kg", "1.5 L".
export const qtyText = (qty, unit) => withUnit(numberText(qty), unit || "");

// "1 Sep" (this year) or "1 Sep 2025".
export function shortDay(d, today) {
  const t = dayText(d);
  return today && String(d).slice(0, 4) === String(today).slice(0, 4) ? t.replace(/ \d{4}$/, "") : t;
}

// What was added since a day (that day included).
export function totalSince(uses = [], since) {
  return uses.filter((u) => u.on && u.on >= since).reduce((n, u) => n + Number(u.qty || 0), 0);
}

// The day `days` before today.
export const daysBefore = (today, days) => iso(ms(today) - days * DAY);

// The row's state: the total of the last 90 days ("130 kg since 1 Sep"), or "None
// added" (no use in that time; "Never added" with none at all).
export function consumableState(row, today) {
  const since = daysBefore(today, WINDOW_DAYS);
  const total = totalSince(row.uses, since);
  if (!row.uses?.length) return { label: "Never added", tone: "neutral", rank: 6, title: "Nothing recorded yet: type the quantity in Record" };
  if (!total) return { label: `None since ${shortDay(since, today)}`, tone: "neutral", rank: 5, title: `Last added ${dayText(row.uses[0].on)}` };
  return { label: `${qtyText(round(total), row.unit)} since ${shortDay(since, today)}`, tone: "neutral", rank: 5,
    title: `${qtyText(round(total), row.unit)} added in the last ${WINDOW_DAYS} days` };
}

const round = (v) => Math.round(v * 1000) / 1000;

// The last `n` months' totals, oldest first ({month: "2026-10", label: "Oct", value}),
// for the sparkline's bars and the view's chart.
export function monthlyTotals(uses = [], today, n = 12) {
  const [y, m] = String(today).slice(0, 7).split("-").map(Number);
  const out = [];
  for (let k = n - 1; k >= 0; k -= 1) {
    const d = new Date(Date.UTC(y, m - 1 - k, 1));
    const month = d.toISOString().slice(0, 7);
    out.push({ month, label: MONTHS[d.getUTCMonth()], value: 0 });
  }
  const at = new Map(out.map((x, i) => [x.month, i]));
  for (const u of uses) {
    const i = at.get(String(u.on || "").slice(0, 7));
    if (i != null) out[i].value = round(out[i].value + Number(u.qty || 0));
  }
  return out;
}

// The stock line for the row's tooltip: where a use comes from, and what's left.
export function stockText(row) {
  if (!row.part) return "Not in the parts register: no stock is taken";
  const held = (row.part.stock || []).filter((s) => s.on_hand > 0);
  if (!held.length) return `${row.part.part_number}: none in stock, so a use takes no stock`;
  return `A use comes out of stock (the nearest store holding enough): ${held.map((s) => `${qtyText(s.on_hand, row.unit)} at ${s.location.name}`).join(", ")}`;
}

// A use in words: "20 kg · 18 Oct 2026".
export const useText = (u, unit) => `${qtyText(u.qty, unit)} · ${dayText(u.on)}`;

// Who added it: "WO 123" or "by hand".
export const byText = (u) => (u.work_order ? `WO ${u.work_order.number}` : "by hand");

const UNIT_DAYS = { days: 1, weeks: 7, months: 30.4375, years: 365.25 };

// The LSA's dose beside what was used: for each task at the position that lists
// it, "The LSA says 20 kg every month (Top up salt); 50 kg were added in the last
// month." Over the same span as the task's interval.
export function lsaComparison(row, today) {
  return (row.lsa || []).filter((l) => l.qty != null).map((l) => {
    const per = l.interval && UNIT_DAYS[l.interval_unit] ? l.interval * UNIT_DAYS[l.interval_unit] : null;
    const every = l.interval && UNIT_DAYS[l.interval_unit]
      ? `every ${l.interval === 1 ? l.interval_unit.replace(/s$/, "") : `${numberText(l.interval)} ${l.interval_unit}`}`
      : l.interval ? `every ${numberText(l.interval)} ${l.interval_unit}` : "each time";
    const lsa = `The LSA says ${qtyText(l.qty, l.unit || row.unit)} ${every} (${l.task.name})`;
    if (!per) return `${lsa}.`;
    const window = Math.round(per);
    const used = round(totalSince(row.uses, daysBefore(today, window)));
    const span = l.interval === 1 ? `the last ${l.interval_unit.replace(/s$/, "")}` : `the last ${numberText(l.interval)} ${l.interval_unit}`;
    return `${lsa}; ${qtyText(used, row.unit)} ${used === 1 ? "was" : "were"} added in ${span}.`;
  });
}

// The view's total line: "In the last 12 months: 240 kg, costing 144.00." (cost when known).
export function yearTotal(row, today) {
  const since = daysBefore(today, 365);
  const recent = (row.uses || []).filter((u) => u.on >= since);
  const qty = round(recent.reduce((n, u) => n + Number(u.qty || 0), 0));
  const costs = recent.filter((u) => u.cost != null);
  const cost = costs.reduce((n, u) => n + Number(u.cost), 0);
  if (!recent.length) return "Nothing added in the last 12 months.";
  return `In the last 12 months: ${qtyText(qty, row.unit)} in ${recent.length} addition${recent.length === 1 ? "" : "s"}${costs.length ? `, costing ${cost.toFixed(2)}` : ""}.`;
}
