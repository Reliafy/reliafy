// The Explorer's Operations tab (Derryn, 23 Nov 2026): how each position of a built asset runs, as
// columns of the one tree-table beside the tree. A position's own row carries its cells (no rows
// hang under it): its duty (the operating plan), where that comes from ("Own" or "From Site A"),
// other use (km or cycles a day), the shutdowns and outages that take it off-line, and its time
// zone. One server read gives every position (GET /api/maintenance/operations, inheritance worked
// out there, the same rule every calculation uses). An item runs as the position it's fitted to.

import { formatDate } from "./dates.js";
import { hoursWords, planWords } from "./operatingPlan.js";
import { EXPLORER_PATH } from "./navigation.js";

export const OPS_TREE_HEAD = "Position";

export const OPS_COLUMNS = [
  { id: "duty", label: "Duty", width: 300 },
  { id: "source", label: "From", width: 160 },
  { id: "use", label: "Other use", width: 120 },
  { id: "windows", label: "Shutdowns and outages", width: 230 },
  { id: "zone", label: "Time zone", width: 160 },
];

// {id: row} from the read's positions.
export function opsById(read) {
  return new Map((read?.positions || []).map((p) => [p.id, p]));
}

// The duty in words: "Monday to Friday, 06:00 to 22:00 · about 80 hours a week"; none: all the time.
export function dutyText(op) {
  const plan = op?.duty?.plan;
  if (!plan) return "All the time (no duty set)";
  const words = plan.plan ? planWords(plan.plan) : plan.text;
  return plan.hours_per_week != null ? `${words} · ${hoursWords(plan.hours_per_week)}` : words;
}

// Where it comes from: "Own", "From Site A", "None here or above".
export function sourceText(op) {
  const d = op?.duty;
  if (!d || d.source === "none") return "None here or above";
  if (d.source === "own") return "Own";
  return `From ${d.from?.name || "the position above"}`;
}

// What Clear leaves it on: "Clear (use Site A's)"; "Clear (run all the time)" with nothing above.
export function clearLabel(op) {
  const up = op?.parent_duty;
  if (!up || up.source === "none" || !up.from) return "Clear (run all the time)";
  return `Clear (use ${up.from.name}'s)`;
}

export function useText(op) {
  const use = op?.other_use || [];
  return use.length ? use.map((u) => u.text).join(" · ") : "";
}

function windowWhen(w) {
  const start = formatDate(String(w.start).slice(0, 10));
  if (w.kind === "shutdown") return `${start}${w.hours != null ? `, ${Number(w.hours).toLocaleString("en-AU")} h` : ""}`;
  return w.end ? `${start} to ${formatDate(String(w.end).slice(0, 10))}` : `from ${start}, no return date`;
}

// One window in words: "Annual shut · 1 Mar 2027, 72 h · from Line 1".
export function windowText(w, { from = true } = {}) {
  const head = w.kind === "shutdown" ? w.name || "Shutdown" : w.name || "Out of service";
  const where = from && !w.own && w.source?.name ? ` · from ${w.source.name}` : "";
  return `${head} · ${windowWhen(w)}${where}`;
}

// The table cell: the next window, and how many more in the year ahead.
export function windowsCell(op) {
  const ws = op?.windows || [];
  if (!ws.length) return "";
  const more = ws.length - 1;
  return `${windowText(ws[0])}${more > 0 ? ` (+${more} more)` : ""}`;
}

export function zoneText(op, workspaceZone = null) {
  const z = op?.time_zone;
  if (!z?.zone) return workspaceZone ? `${workspaceZone} (workspace)` : "UTC (workspace)";
  return z.source === "workspace" ? `${z.zone} (workspace)` : z.zone;
}

// A position's cell, as plain text (the component wraps it).
export function opsCellText(op, col, workspaceZone = null) {
  switch (col) {
    case "duty": return dutyText(op);
    case "source": return sourceText(op);
    case "use": return useText(op);
    case "windows": return windowsCell(op);
    case "zone": return zoneText(op, workspaceZone);
    default: return "";
  }
}

// A row's second line on a phone: "Own · Monday to Friday …" or "From Site A · …".
export function opsPhoneLine(op) {
  if (!op) return "";
  const parts = [sourceText(op), dutyText(op)];
  const ws = windowsCell(op);
  if (ws) parts.push(ws);
  return parts.join(" · ");
}

// Where a position's duty is set: its operating plan on the Operations tab (?plan=), inside the
// asset opened (`root`, else the position itself). A date by running hours with no duty says it
// assumes 24 h a day and links here (basis kind "continuous").
export function dutyHref(positionId, root = null) {
  const q = new URLSearchParams({ arrange: "positions", root: root || positionId, sel: positionId, tab: "operations", plan: positionId });
  return `${EXPLORER_PATH}?${q}`;
}

export const assumesContinuous = (basis) => basis?.kind === "continuous";
