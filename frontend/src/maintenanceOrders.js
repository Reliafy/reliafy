// Maintenance › Orders and Packages: where they live, and the pure logic behind
// their lists (no React, so the tests can hold it).

export const ORDERS_PATH = "/maintenance/work-orders";
export const PACKAGES_PATH = "/maintenance/packages";
export const packagePath = (id) => `${PACKAGES_PATH}/${encodeURIComponent(id)}`;
export const workOrderPath = (id) => `${ORDERS_PATH}/${encodeURIComponent(id)}`;

// The Orders page's tabs, in order; Open is the default.
export const ORDER_TABS = [
  { id: "open", label: "Open" },
  { id: "due", label: "Due soon" },
  { id: "closed", label: "Closed" },
];
export const orderTab = (raw) => (ORDER_TABS.some((t) => t.id === raw) ? raw : "open");

// The Orders page on one tab, with any filters (?location=): the Open tab is the
// page's own address.
export function ordersPath(tab = "open", params = {}) {
  const q = new URLSearchParams();
  if (tab && tab !== "open") q.set("tab", tab);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `${ORDERS_PATH}?${s}` : ORDERS_PATH;
}

// The windows Due soon offers, in days.
export const DUE_WINDOWS = [7, 30, 90];
export const dueWindow = (raw) => (DUE_WINDOWS.includes(Number(raw)) ? Number(raw) : 30);

const DAY = 86400000;

// Whole days from `from` to `to` (ISO dates); null when either is missing.
export function daysBetween(from, to) {
  if (!from || !to) return null;
  const a = Date.parse(`${String(from).slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${String(to).slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / DAY);
}

// How late an open work order is, in days (null: it isn't). Overdue is the
// server's call (one rule everywhere); a package visit's own count wins.
export function daysLate(wo, today) {
  if (!wo?.overdue) return null;
  if (Number.isFinite(wo.days_late) && wo.days_late > 0) return wo.days_late;
  const d = daysBetween(wo.due, today);
  return d && d > 0 ? d : null;
}

export const lateText = (days) => (days == null ? "" : days === 1 ? "1 day late" : `${days} days late`);

// The Open tab's two sections: the overdue ones, most late first, then the rest
// in the order the server gives (by due date, those with none last).
export function splitOpen(rows = [], today = null) {
  const overdue = [];
  const open = [];
  for (const w of rows) (w.overdue ? overdue : open).push(w);
  overdue.sort((a, b) => (daysLate(b, today) ?? 0) - (daysLate(a, today) ?? 0) || a.number - b.number);
  return { overdue, open };
}

// A package work order's progress ("13 of 29 lines"), or "".
export function linesText(wo) {
  if (!wo?.lines_total) return "";
  return `${wo.lines_answered || 0} of ${wo.lines_total} ${wo.lines_total === 1 ? "line" : "lines"}`;
}

// Where an open work order came from: a package's visit, a task, or by hand.
export function orderKind(wo) {
  if (wo?.package) return "package";
  return wo?.type === "preventive" ? "task" : "hand";
}

// The answer first, above the tabs: "3 open, 1 late by 4 days. 12 due in the next 30 days."
export function ordersSummary({ open = [], due = null, horizon = 30, today = null } = {}) {
  const late = open.filter((w) => w.overdue);
  const parts = [];
  if (!open.length) parts.push("No open work orders");
  else {
    let s = `${open.length} open`;
    if (late.length === 1) {
      const d = daysLate(late[0], today);
      s += d ? `, 1 late by ${d === 1 ? "1 day" : `${d} days`}` : ", 1 late";
    } else if (late.length > 1) {
      const worst = Math.max(...late.map((w) => daysLate(w, today) || 0));
      s += `, ${late.length} late${worst ? ` (the latest by ${worst === 1 ? "1 day" : `${worst} days`})` : ""}`;
    }
    parts.push(s);
  }
  let text = `${parts.join("")}.`;
  if (due) text += ` ${due.length ? due.length : "Nothing"} due in the next ${horizon} days.`;
  return text;
}

// Due soon, grouped: each package's tasks under it (by name), then the tasks in
// none. Each group keeps the server's order (soonest first).
export function groupDue(rows = []) {
  const groups = new Map();
  const loose = [];
  for (const t of rows) {
    if (t.package?.id) {
      if (!groups.has(t.package.id)) groups.set(t.package.id, { key: t.package.id, package: t.package, tasks: [] });
      groups.get(t.package.id).tasks.push(t);
    } else loose.push(t);
  }
  const out = [...groups.values()].sort((a, b) =>
    (a.package.name || "").localeCompare(b.package.name || "") || a.key.localeCompare(b.key));
  if (loose.length) out.push({ key: "none", package: null, tasks: loose });
  return out;
}

// What "Create work orders" will raise for these due tasks: one per active
// package with a task still to raise (its visit), one per task in no package. A
// paused package's tasks wait for it; a task with a work order open has one.
export function createPlan(rows = []) {
  const packages = new Set();
  let tasks = 0;
  for (const t of rows) {
    if (t.open_work_order || t.held) continue;
    if (t.package?.id) {
      if (t.package.active !== false) packages.add(t.package.id);
    } else tasks += 1;
  }
  return { packages: packages.size, tasks, total: packages.size + tasks };
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// Whether a due task's work is in an area (a site and the places inside it): its
// location ({id, path: [{id}]}: the position's place, set or inherited, or where its item
// is) is the area or inside it. No area: everything is.
export function inArea(row, locationId) {
  if (!locationId) return true;
  const loc = row?.location || row?.at?.location;
  if (!loc) return false;
  return loc.id === locationId || (loc.path || []).some((a) => a.id === locationId);
}

// The words a due task is found by: its name, what it's on and what that sits in, its
// package and where it is ("Riverside" finds every task at the Riverside site).
export function dueSearchText(t) {
  const loc = t?.location || t?.at?.location;
  return [t?.name, t?.subject?.name, t?.subject?.within, t?.package?.name, loc?.display, loc?.name].filter(Boolean);
}

// "Create 2 work orders", and what they are: "1 package visit, 1 task".
export function createLabel(plan) {
  return `Create ${plural(plan.total, "work order", "work orders")}`;
}
export function createDetail(plan) {
  const bits = [];
  if (plan.packages) bits.push(plural(plan.packages, "package visit", "package visits"));
  if (plan.tasks) bits.push(plural(plan.tasks, "task", "tasks"));
  return bits.join(", ");
}

// What a closed work order's actions did, in words; a cancelled one says so.
export function doneText(wo) {
  if (wo?.status === "cancelled") return "Cancelled";
  const words = [];
  for (const a of wo?.done || []) {
    const w = a.kind === "inspect"
      ? (a.finding === "ok" ? "Checked, nothing done" : a.finding === "found_failed" ? "Inspected, found failed"
        : a.finding === "degraded" ? "Inspected, found degraded" : "Inspected")
      : a.kind === "replace" ? "Replaced" : a.kind === "repair" ? "Repaired" : "Other work";
    if (!words.includes(w)) words.push(w);
  }
  return words.length ? words.join(", ") : "Closed";
}

// A package's status in words for its list.
export function packageStatusText(p) {
  if (p?.status === "retired") return "Retired";
  if (p?.status === "paused") return p.pause?.text ? p.pause.text[0].toUpperCase() + p.pause.text.slice(1) : "Paused";
  if (p?.open_work_order?.late) return "Visit late";
  return "Active";
}

// Packages listed: top packages with their layers after them, as the server
// sorts them; `query` matches the name, what it's on, the parent's name or the
// cadence in words.
export function packageMatches(p, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return [p.name, p.subject?.name, p.parent?.name, p.cadence?.text, p.trade]
    .some((x) => x && String(x).toLowerCase().includes(q));
}
