// The Explorer's Packages tab (Assets › Explorer, ?tab=packages): the work
// packages planned at the picked position or location and inside it (a
// package bundles tasks done on one visit, so each visit raises one work
// order). The logic here; the page is components/PackagesPanel.jsx.

import { OUTCOME_LABEL, triggerText, whenText } from "./rcmWorksheet.js";

const DAY = 86400000;
const toDay = (s) => Date.parse(`${String(s).slice(0, 10)}T00:00:00Z`);

// What a read is limited to for a row: a position, or a place.
export function packageScope(row) {
  if (row?.type === "pos") return { position_id: row.key };
  if (row?.type === "loc") return { location_id: row.key };
  return null;
}

// "Every Saturday", "The first Saturday of every month", "Every 4 weeks after the last visit".
export function cadenceWords(pkg) {
  const text = pkg?.cadence?.text || pkg?.cadence_text || "";
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

export function ordinal(n) {
  const k = Number(n);
  const tail = k % 100 >= 11 && k % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[k % 10] || "th");
  return `${k}${tail}`;
}

// A member's visit rule in words: "every visit", "every 4th visit".
export function visitRuleText(member) {
  if (member?.visit_rule === "nth" && member.every_nth) return `every ${ordinal(member.every_nth)} visit`;
  return "every visit";
}

// How late a top package is, in days past its tolerance (0: on time). Its open
// work order says (frozen while paused); with none raised yet, a next visit
// already past the tolerance counts too.
export function daysLate(pkg, today) {
  const wo = pkg?.open_work_order;
  if (wo) return wo.late ? Math.max(1, wo.days_late || 0) : 0;
  if (!pkg?.next_visit || !today || pkg.pause) return 0;
  const tol = pkg.tolerance?.enforced ? pkg.tolerance.amount || 0 : 0;
  const over = Math.round((toDay(today) - toDay(pkg.next_visit)) / DAY) - tol;
  return over > 0 ? over : 0;
}

export function lateText(days) {
  return days > 0 ? `Late by ${days} day${days === 1 ? "" : "s"}` : "";
}

// The Package the tasks… table: each draft a row, ticked, with the name it'll
// get; layers know their top.
export function proposalRows(drafts = []) {
  return drafts.map((d) => ({
    ref: d.ref, name: d.name, ticked: true, layerOf: d.layer_of || null, draft: d,
  }));
}

// Tick or untick one row: unticking a top unticks its layers (they visit on
// its visits); ticking a layer ticks its top.
export function toggleRow(rows, ref, on) {
  const row = rows.find((r) => r.ref === ref);
  if (!row) return rows;
  return rows.map((r) => {
    if (r.ref === ref) return { ...r, ticked: on };
    if (!on && r.layerOf === ref) return { ...r, ticked: false };
    if (on && row.layerOf && r.ref === row.layerOf) return { ...r, ticked: true };
    return r;
  });
}

export function renameRow(rows, ref, name) {
  return rows.map((r) => (r.ref === ref ? { ...r, name } : r));
}

// The ticked rows as the batch to make: tops (with the tolerance in days)
// before their layers.
export function proposalBatch(rows, { tolerance = null } = {}) {
  const ticked = rows.filter((r) => r.ticked);
  const tol = tolerance === "" || tolerance == null ? null : Number(tolerance);
  return ticked.map((r) => ({
    ref: r.ref, ...r.draft.create, name: r.name.trim() || r.draft.name,
    ...(!r.layerOf && tol != null && Number.isFinite(tol) && tol > 0 ? { tolerance: Math.round(tol), tolerance_unit: "days" } : {}),
  }));
}

// What's wrong with the table before making it (null: nothing).
export function proposalProblem(rows) {
  const ticked = rows.filter((r) => r.ticked);
  if (!ticked.length) return "Tick at least one package to make.";
  if (ticked.some((r) => !r.name.trim())) return "Give every ticked package a name.";
  return null;
}

// The tasks that could join a package: those in a proposal's drafts (in no
// package, on the calendar, not an item's or a round), A–Z.
export function freeTasks(proposal) {
  const seen = new Map();
  for (const d of proposal?.drafts || []) for (const t of d.tasks || []) if (!seen.has(t.id)) seen.set(t.id, t);
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base", numeric: true }));
}

// The Summary's "Next visit": the soonest visit of a package any of the
// position's tasks is in, or null.
export function nextVisit(tasks = []) {
  let best = null;
  for (const t of tasks) {
    if (t.due_by !== "package" || !t.package || !t.next_due) continue;
    if (!best || t.next_due < best.on) best = { name: t.package.name, id: t.package.id, on: t.next_due };
  }
  return best;
}

export const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
export const dayName = (d) => d[0].toUpperCase() + d.slice(1);

// ---- the tab's table of tasks --------------------------------------------------------
// The Packages tab is a table of every task on the picked row and below it (the
// server's task-table read), formatted like the RCM table: search it, sort it,
// tick tasks and package them together.


export const TASK_COLUMNS = [
  { id: "position", label: "Position", width: 170, title: "The position or place the task is on" },
  { id: "mode", label: "Failure mode", width: 230, title: "The failure mode it prevents, with its function › functional failure" },
  { id: "task", label: "Task", width: 240 },
  { id: "kind", label: "Kind", width: 140, title: "On condition, fixed interval or failure finding" },
  { id: "interval", label: "Interval", width: 130 },
  { id: "trade", label: "Trade", width: 110 },
  { id: "due", label: "Next due", width: 110 },
  { id: "package", label: "Package", width: 200, title: "The work package it's done in; blank when it's done on its own" },
];
export const DEFAULT_TASK_COLUMNS = TASK_COLUMNS.map((c) => c.id);
const COLUMN_IDS = new Set(DEFAULT_TASK_COLUMNS);

// What each column shows for a task (and what it sorts and searches by).
export function kindText(t) {
  if (t.on_event) return triggerText(t.trigger) || "on event";
  return OUTCOME_LABEL[t.kind] || "";
}
export function modeLine(m) {
  return m ? [m.function, m.failure].filter(Boolean).join(" › ") : "";
}
export function cellText(t, col) {
  switch (col) {
    case "position": return t.subject?.name || "";
    case "mode": return t.modes?.[0]?.text || "";
    case "task": return t.name || "";
    case "kind": return kindText(t);
    case "interval": return t.on_event ? "" : whenText({ interval: t.interval, interval_unit: t.unit, trigger: t.trigger });
    case "trade": return t.trade || "";
    case "due": return t.next_due || "";
    case "package": return t.package?.name || "";
    default: return "";
  }
}

const DAYS = { hours: 1 / 24, days: 1, weeks: 7, months: 30.4375, years: 365.25 };
// The value a column sorts by: an interval by its length in days, the rest by text.
function sortValue(t, col) {
  if (col === "interval") return t.on_event || t.interval == null ? null : t.interval * (DAYS[t.unit] ?? 1);
  const v = cellText(t, col);
  return v === "" ? null : v.toLowerCase();
}

// Every word of the search somewhere in the row's columns (and the second line
// of its failure mode, and its other failure modes).
export function searchTasks(tasks, q) {
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return tasks;
  return tasks.filter((t) => {
    const hay = [...DEFAULT_TASK_COLUMNS.map((c) => cellText(t, c)), ...(t.modes || []).flatMap((m) => [m.text, modeLine(m)])]
      .join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

// ?sort=due,-interval: the keys in order, "-" for descending.
export function parseSort(param) {
  return String(param || "").split(",").map((s) => s.trim()).filter(Boolean)
    .map((s) => (s.startsWith("-") ? { col: s.slice(1), dir: -1 } : { col: s, dir: 1 }))
    .filter((k) => COLUMN_IDS.has(k.col)).slice(0, 3);
}
export function sortParam(keys) {
  return keys.map((k) => (k.dir < 0 ? `-${k.col}` : k.col)).join(",");
}

// A header clicked: the only key (again: the other way round, then off).
// Shift-clicked: added as the next key (again: the other way round, then off).
export function nextSort(keys, col, shift = false) {
  const at = keys.findIndex((k) => k.col === col);
  if (!shift) {
    if (at === 0 && keys.length === 1) return keys[0].dir === 1 ? [{ col, dir: -1 }] : [];
    return [{ col, dir: 1 }];
  }
  if (at < 0) return [...keys, { col, dir: 1 }].slice(0, 3);
  if (keys[at].dir === 1) return keys.map((k, i) => (i === at ? { col, dir: -1 } : k));
  return keys.filter((_, i) => i !== at);
}

// Blank values last whichever way; then position and task A–Z.
export function sortTasks(tasks, keys) {
  const cmpKey = (a, b, { col, dir }) => {
    const x = sortValue(a, col), y = sortValue(b, col);
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    const c = typeof x === "number" ? x - y : x.localeCompare(y, "en", { numeric: true });
    return c * dir;
  };
  const tail = [{ col: "position", dir: 1 }, { col: "task", dir: 1 }];
  return [...tasks].sort((a, b) => {
    for (const k of [...keys, ...tail]) {
      const c = cmpKey(a, b, k);
      if (c) return c;
    }
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

// The tick box for every task shown: all, some or none ticked.
export function tickState(shown, picked) {
  const n = shown.filter((t) => picked.has(t.id)).length;
  return n === 0 ? "none" : n === shown.length ? "all" : "some";
}
export function tickAll(shown, picked, on) {
  const next = new Set(picked);
  for (const t of shown) if (on) next.add(t.id); else next.delete(t.id);
  return next;
}

// A new package's cadence from the tasks picked: the commonest calendar
// interval among them (weekly → every week on the weekday; monthly and longer
// → the first weekday of every N months), and a note when they differ.
export function cadenceFor(tasks) {
  const count = new Map();
  for (const t of tasks) {
    if (t.on_event || t.interval == null || !(t.unit in DAYS) || t.unit === "hours") continue;
    const key = `${t.interval} ${t.unit}`;
    count.set(key, (count.get(key) || 0) + 1);
  }
  if (!count.size) return { every: 1, unit: "weeks", mixed: false };
  const [best] = [...count].sort((a, b) => b[1] - a[1] || DAYS[a[0].split(" ")[1]] * Number(a[0].split(" ")[0]) - DAYS[b[0].split(" ")[1]] * Number(b[0].split(" ")[0]));
  let [every, unit] = best[0].split(" ");
  every = Number(every);
  if (unit === "days" && every % 7 === 0) { every /= 7; unit = "weeks"; }
  if (unit === "years") { every *= 12; unit = "months"; }
  if (!Number.isInteger(every) || every < 1) { every = Math.max(1, Math.round(every)); }
  return { every, unit, mixed: count.size > 1 };
}

// Which of the picked tasks can't join a package (an item's, by use, a round), and why.
export function cantJoin(tasks) {
  return tasks.filter((t) => t.why_not);
}
