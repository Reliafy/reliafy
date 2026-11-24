// A task's optional extras (Derryn, 23 Nov 2026): its Cost, Labour and Parts, each a fold-out of its
// own in the task panel (MaintenanceTask) with a one-line summary while folded, and each a row
// under the task in the Explorer's Maintenance tree ("Labour · 1.5 h mechanic", "Part · Spindle kit
// × 1", "Cost · $40 each time"), shown only when set. The words come from here, so the panel and the
// tree say the same. Pure: tested in taskExtras.test.js.
import { money } from "./lsaTab.js";

export const EXTRA_SECTIONS = ["cost", "labour", "parts"];
export const EXTRA_WORDS = { cost: "Cost", labour: "Labour", parts: "Part" };

const n = (v) => {
  const x = Number(v);
  return Number.isFinite(x) ? x : 0;
};
const sig = (v) => Number(Number(v).toPrecision(4)).toLocaleString("en-GB");

// Labour lines ({trade, people, hours}, as typed or as saved) in words: "1.5 h mechanic",
// "2 × 3 h fitter", one per line, joined by commas. "" when no line has hours.
export function labourWords(lines = []) {
  return (lines || []).filter((x) => n(x.hours) > 0).map((x) => {
    const people = Math.max(1, Math.round(n(x.people) || 1));
    const trade = String(x.trade || "").trim();
    return `${people > 1 ? `${people} × ` : ""}${sig(x.hours)} h${trade ? ` ${trade}` : ""}`;
  }).join(", ");
}

// The spares lines ({name, qty, part_number?}) in words: "Spindle kit × 1, Belt × 2". "" for none.
export function partWords(spares = []) {
  return (spares || []).filter((x) => String(x.name || "").trim()).map((x) => `${String(x.name).trim()} × ${sig(n(x.qty) || 1)}`).join(", ");
}

// The cost typed on the task (and a visit's call-out) in words: "$40 each time · call-out $25". "" when
// neither is typed (a cost from its LSA isn't "set": it follows the labour and parts).
export function costWords(typed, visit = null) {
  const bits = [];
  if (typed !== "" && typed != null && Number.isFinite(Number(typed))) bits.push(`${money(Number(typed))} each time`);
  if (visit !== "" && visit != null && Number.isFinite(Number(visit)) && Number(visit) > 0) bits.push(`call-out ${money(Number(visit))}`);
  return bits.join(" · ");
}

// The tree's rows under a task (a task-table row): [{section, text}], only the ones set.
export function taskExtras(t) {
  if (!t) return [];
  const r = t.resources || {};
  const out = [];
  const labour = labourWords(r.labour);
  if (labour) out.push({ section: "labour", text: `Labour · ${labour}` });
  for (const s of r.spares || []) {
    const w = partWords([s]);
    if (w) out.push({ section: "parts", text: `Part · ${w}` });
  }
  const cost = costWords(t.cost?.typed, t.visit_cost);
  if (cost) out.push({ section: "cost", text: `Cost · ${cost}` });
  return out;
}

// A work package's extras: its tasks' together (labour hours by trade, each part's total, the
// typed costs a visit), in the same words: "Labour · 3 h fitter", "Part · Belt × 2", "Cost · $120 a visit".
export function packageExtras(tasks = []) {
  const hours = new Map();
  const parts = new Map();
  let cost = 0;
  let costed = false;
  for (const t of tasks || []) {
    const r = t?.resources || {};
    for (const x of r.labour || []) {
      if (!(n(x.hours) > 0)) continue;
      const trade = String(x.trade || "").trim();
      hours.set(trade, (hours.get(trade) || 0) + n(x.hours) * Math.max(1, Math.round(n(x.people) || 1)));
    }
    for (const x of r.spares || []) {
      const name = String(x.name || "").trim();
      if (name) parts.set(name, (parts.get(name) || 0) + (n(x.qty) || 1));
    }
    if (t?.cost?.typed != null && Number.isFinite(Number(t.cost.typed))) { cost += Number(t.cost.typed); costed = true; }
  }
  const out = [];
  if (hours.size) out.push({ section: "labour", text: `Labour · ${[...hours].map(([trade, h]) => `${sig(h)} h${trade ? ` ${trade}` : ""}`).join(", ")}` });
  for (const [name, q] of parts) out.push({ section: "parts", text: `Part · ${name} × ${sig(q)}` });
  if (costed) out.push({ section: "cost", text: `Cost · ${money(cost)} a visit` });
  return out;
}

