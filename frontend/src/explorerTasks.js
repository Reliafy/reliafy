// The Explorer's Maintenance tab (its Tasks view) is a tree-table, like the Modelling and Missions
// tabs (Derryn, 22 Nov 2026: "the maintenance tab should show tasks in the tree. That way for a
// certain level we can run the forecasts"; "at any level, you should see all the stuff from
// underneath it aggregated"). Under each position (or place) hang its own maintenance tasks, one
// row each, with the table's columns beside them: how often, when next due, what it costs each
// time, its package, where it came from and its kind. Each position's roll-up counts the tasks on
// it and on everything below it, at any depth. A position's menu has Forecast…: the forecast for
// that level and everything inside it, in the table area (PositionForecast.jsx).
//
// The tasks come in one read for the asset opened (GET /api/maintenance/task-table?within=<root>:
// the server's roll-up, Maintenance.subtree_ids, never another asset's). Pure functions, tested in
// explorerTasks.test.js; the cells are drawn by TaskTreeTable.jsx.

import { cellText, costWhere, fromRcm, kindText, money, SOURCE_WORDS } from "./lsaTab.js";

export const TASK_TYPE = "mtask";
export const isTaskRow = (r) => r?.type === TASK_TYPE;
export const taskKey = (id) => `MT:${id}`;

export const TASK_COLUMNS = [
  { id: "interval", label: "Interval", width: 140, title: "How often it's done, or what raises it" },
  { id: "due", label: "Next due", width: 120, title: "When it's next due (overdue in red)" },
  { id: "cost", label: "Cost each time", width: 120, num: true, title: "What it costs each time it's done: typed on the task, or from its LSA" },
  { id: "trade", label: "Trade", width: 110, title: "Who does it" },
  // Derryn, 22 Nov 2026: "There should be a 'packaged' column": the package it's in, a link to it.
  { id: "package", label: "Packaged", width: 170, title: "The work package it's in (click to open it), or blank when it's in none" },
  { id: "from", label: "From", width: 210, title: "Where it came from: an RCM decision, or added directly (and why)" },
  { id: "kind", label: "Kind", width: 140, title: "On condition, fixed interval or failure finding; a task raised by an event says which" },
];
export const TASK_TREE_HEAD = "Position, and its tasks";

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });
const blank = () => ({ tasks: 0, overdue: 0 });

// The tree with each position's (and place's) tasks in it. The display given is left as it is;
// position and place rows gain `tsum` (their own: tasks, overdue) and `tall` (theirs and everything
// below). A task whose position isn't in the tree (another asset, a pinned branch) isn't shown.
// `prune` (a column filter on: the tasks given are the ones that match): a row with no task at or
// below it leaves its parent's kids, so the tree reads as the way down to each match; the top
// rows stay. The rows left out stay in `rows` (a row picked keeps its place for when the filter
// goes), only unreachable.
export function graftTasks(display, tasks = [], { prune = false } = {}) {
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, tasks: true };
  // A position shown above a place's positions for context (assetTree.js VIA) counts what's under it too.
  const holds = (r) => r?.type === "pos" || r?.type === "loc" || !!r?.ref?.via;
  for (const r of rows.values()) if (holds(r)) Object.assign(r, { tsum: blank(), tall: blank() });
  const byHolder = new Map();
  for (const t of tasks) {
    const p = rows.get(t.subject?.id);
    if (!holds(p)) continue;
    if (!byHolder.has(p.key)) byHolder.set(p.key, []);
    byHolder.get(p.key).push(t);
  }
  for (const [pk, list] of byHolder) {
    const p = rows.get(pk);
    const keys = [];
    for (const t of [...list].sort((a, b) => String(a.name).localeCompare(String(b.name), "en", { numeric: true }))) {
      const key = taskKey(t.id);
      keys.push(key);
      rows.set(key, {
        key, type: TASK_TYPE, parent: pk, kids: [], depth: p.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name: t.name, task: t, position_id: pk,
          search: [t.name, t.package?.name, t.trade, cellText(t, "from"), kindText(t)].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      p.tsum.tasks += 1;
      if (t.overdue) p.tsum.overdue += 1;
    }
    p.kids = [...keys, ...p.kids];
  }
  const done = new Set();
  const total = (k) => {
    const r = rows.get(k);
    if (done.has(k)) return r.tall;
    done.add(k);
    const t = { ...r.tsum };
    for (const c of r.kids) {
      if (holds(rows.get(c))) {
        const s = total(c);
        t.tasks += s.tasks;
        t.overdue += s.overdue;
      }
    }
    r.tall = t;
    return t;
  };
  for (const r of rows.values()) if (holds(r)) total(r.key);
  if (prune) {
    const keep = new Map();
    const has = (k) => {
      if (keep.has(k)) return keep.get(k);
      const r = rows.get(k);
      keep.set(k, false);
      let y = r?.type === TASK_TYPE;
      for (const c of r?.kids || []) if (has(c)) y = true;
      keep.set(k, y);
      return y;
    };
    const tops = display.roots || [...rows.values()].filter((r) => r.parent == null).map((r) => r.key);
    for (const k of tops) has(k);
    for (const r of rows.values()) if (r.kids.length) r.kids = r.kids.filter((c) => keep.get(c));
    out.pruned = true;
  }
  return out;
}

const count = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// A level's roll-up: the tasks at and below it ("7 tasks at and below · 1 overdue"); open, its own
// first ("2 here · 7 at and below"). "No tasks here or below" when there are none.
export function rollupText(r, open = false) {
  if (!r?.tsum) return "";
  const own = r.tsum;
  const all = r.tall || own;
  if (!all.tasks) return "No tasks here or below";
  const late = all.overdue ? ` · ${all.overdue.toLocaleString("en-AU")} overdue` : "";
  if (all.tasks === own.tasks) return `${count(all.tasks, "task")} here${late}`;
  if (open && own.tasks) return `${own.tasks.toLocaleString("en-AU")} here · ${count(all.tasks, "task")} at and below${late}`;
  return `${count(all.tasks, "task")} at and below${late}`;
}

// What a cell says for a task (and its title); `due` and `cost` carry a tone of their own.
export function taskCell(t, col) {
  switch (col) {
    case "interval": return { text: cellText(t, "interval") || (t.on_event ? "On an event" : "") };
    case "due": return { text: t.next_due || "", overdue: !!t.overdue, title: [t.overdue ? "Overdue" : null, t.due_basis].filter(Boolean).join(". ") };
    case "cost": return t.cost?.amount == null
      ? { text: "", blank: "Not set", title: costWhere(t.cost) }
      : { text: money(t.cost.amount), title: `${money(t.cost.amount)} each time. ${costWhere(t.cost)}` };
    case "trade": return { text: t.trade || "" };
    case "package": return t.package ? { text: t.package.name, title: `In ${t.package.name}: click to open it` }
      : { text: "", blank: t.why_not ? "On its own" : "", title: t.why_not ? `Stays on its own: ${t.why_not}` : "" };
    case "from": return { text: cellText(t, "from") };
    case "kind": return { text: kindText(t) };
    default: return { text: "" };
  }
}

// The way down to a position, so its tasks show when the tab opens.
export function openForTasks(display, key) {
  const out = [];
  for (let k = key; k != null; k = display.rows.get(k)?.parent) out.push(k);
  return out;
}

// A task row's ⋯; a position's (or place's) own: Add task…, then Forecast… (a position on an
// asset: the forecast for it and everything inside it, in the table area).
export const TASK_OPEN = "mtask-open";
export const TASK_FORECAST = "mtask-forecast";
export const TASK_PACKAGE = "mtask-package";
export const TASK_ADD_TO = "mtask-add-to";
export const TASK_CLEAR = "mtask-clear";
// A task row's menu: Open…, then Package… and Add to package… for the tasks selected (the row
// itself when it isn't one of them), each greyed with the reason when none of them can go.
// `tasks`: the task-table rows it acts on; `canPackage`: false on a product's design, or view only.
export function taskRowActions(r, { tasks = null, canPackage = true } = {}) {
  const out = [{ id: TASK_OPEN, label: "Open…" }];
  if (!canPackage) return out;
  const list = tasks?.length ? tasks : r?.ref?.task ? [r.ref.task] : [];
  const free = list.filter((t) => !t.why_not && !t.package);
  const stuck = list.length && list.every((t) => t.why_not);
  const why = stuck ? `${list.length === 1 ? "It can't" : "They can't"} join a package: ${list[0].why_not}`
    : !free.length ? `${list.length === 1 ? "It's" : "They're"} in a package already: take ${list.length === 1 ? "it" : "them"} out there first`
      : null;
  const n = list.length > 1 ? ` ${list.length} tasks` : "";
  out.push({ separator: true },
    { id: TASK_PACKAGE, label: "Package…", disabled: !!why, reason: why || undefined, title: `A new work package with${n || " this task"}` },
    { id: TASK_ADD_TO, label: "Add to package…", disabled: !!why, reason: why || undefined, title: `Put${n || " this task"} in a package already on this asset` });
  if (list.length > 1) out.push({ id: TASK_CLEAR, label: "Clear the selection" });
  return out;
}

// ---- column filters ------------------------------------------------------------------------
// Derryn, 22 Nov 2026: "the columns need to be filterable (to what is open in the tree)". Each
// column has one or more facets (Interval: its unit, then the interval itself); a facet's values
// come from the tasks on show in the open part of the tree, each with how many tasks have it.
// A filter keeps the tasks with any of the values ticked in a facet, and all facets at once.

const UNIT_WORDS = { hours: "Operating hours", days: "Days", weeks: "Weeks", months: "Months", years: "Years" };
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const UNIT_ORDER = { hours: 0, days: 1, weeks: 2, months: 3, years: 4 };
const SPAN = { hours: 1 / 24, days: 1, weeks: 7, months: 30.4375, years: 365.25 };

export const TASK_FACETS = [
  { id: "unit", col: "interval", label: "Unit",
    of: (t) => (t.on_event ? { value: "event", label: "On an event", order: 9 }
      : t.unit ? { value: t.unit, label: UNIT_WORDS[t.unit] || cap(t.unit), order: UNIT_ORDER[t.unit] ?? 5 }
        : { value: "", label: "None set", order: 10 }) },
  { id: "interval", col: "interval", label: "Interval",
    of: (t) => {
      const text = taskCell(t, "interval").text;
      if (!text) return { value: "", label: "None set", order: Infinity };
      return { value: text, label: text, order: (Number(t.interval) || 0) * (SPAN[t.unit] ?? 1000) + (UNIT_ORDER[t.unit] ?? 5) * 1e-6 };
    } },
  { id: "due", col: "due", label: "Next due",
    of: (t) => (t.overdue ? { value: "overdue", label: "Overdue", order: 0 }
      : t.next_due ? { value: "due", label: "Not overdue", order: 1 } : { value: "", label: "No date", order: 2 }) },
  { id: "cost", col: "cost", label: "Cost each time",
    of: (t) => (t.cost?.amount != null ? { value: "set", label: "Cost set", order: 0 } : { value: "", label: "Not set", order: 1 }) },
  { id: "trade", col: "trade", label: "Trade",
    of: (t) => (t.trade ? { value: t.trade, label: t.trade } : { value: "", label: "No trade", order: Infinity }) },
  { id: "package", col: "package", label: "Packaged",
    of: (t) => (t.package ? { value: t.package.id, label: t.package.name }
      : t.why_not ? { value: "-", label: "Can't join a package", order: Infinity } : { value: "", label: "In no package", order: Infinity - 1 }) },
  { id: "from", col: "from", label: "From",
    of: (t) => (fromRcm(t) ? { value: "rcm", label: "RCM", order: 0 }
      : { value: t.source || "other", label: `Added directly: ${SOURCE_WORDS[t.source] || "other"}`, order: 1 }) },
  { id: "kind", col: "kind", label: "Kind",
    of: (t) => { const k = kindText(t); return k ? { value: k, label: cap(k) } : { value: "", label: "None set", order: Infinity }; } },
];
export const facetsOf = (col) => TASK_FACETS.filter((f) => f.col === col);
const FACET = Object.fromEntries(TASK_FACETS.map((f) => [f.id, f]));

// Whether a task passes the filters ({facet id: [values]}), all but `skip` (a facet's own values
// are counted against the others, so ticking one doesn't hide its neighbours).
export function passes(t, filters, skip = null) {
  for (const [id, vals] of Object.entries(filters || {})) {
    if (id === skip || !vals?.length || !FACET[id]) continue;
    if (!vals.includes(FACET[id].of(t).value)) return false;
  }
  return true;
}
export const anyFilter = (filters) => Object.values(filters || {}).some((v) => v?.length);
export const filterTasks = (tasks, filters) => (anyFilter(filters) ? tasks.filter((t) => passes(t, filters)) : tasks);

// The values a facet offers: those of the tasks on show (`shown`), each with how many pass the
// other filters; a value ticked stays listed (at 0) so it can be unticked.
export function facetValues(facetId, shown = [], filters = {}) {
  const f = FACET[facetId];
  const seen = new Map();
  for (const t of shown) {
    const v = f.of(t);
    const e = seen.get(v.value) || { ...v, count: 0 };
    if (passes(t, filters, facetId)) e.count += 1;
    seen.set(v.value, e);
  }
  for (const v of filters?.[facetId] || []) if (!seen.has(v)) seen.set(v, { value: v, label: v || "None set", count: 0 });
  return [...seen.values()].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)
    || String(a.label).localeCompare(String(b.label), "en", { numeric: true }));
}

// The tasks on show in a tree (`list`: the rows drawn, flatten()), for the facets' values.
export function shownTasks(display, list) {
  const out = [];
  for (const v of list) {
    const r = display.rows.get(v.key);
    if (isTaskRow(r)) out.push(r.ref.task);
  }
  return out;
}

// What the filter line says: "Filtered by Packaged, Kind".
export function filterWords(filters) {
  const cols = [...new Set(Object.entries(filters || {}).filter(([, v]) => v?.length).map(([id]) => FACET[id]?.col))];
  const names = cols.map((c) => TASK_COLUMNS.find((x) => x.id === c)?.label).filter(Boolean);
  return names.length ? `Filtered by ${names.join(", ")}` : "";
}

// ---- selecting tasks -----------------------------------------------------------------------
// Click picks one task, Shift-click the tasks between it and the last one clicked (as drawn),
// Ctrl/⌘-click (or its box, or Space) adds or takes one. Only task rows are picked.
export function pickTasks(picked, list, display, key, { shift = false, toggle = false, anchor = null } = {}) {
  if (!isTaskRow(display.rows.get(key))) return { picked: toggle || shift ? picked : new Set(), anchor };
  if (toggle) {
    const n = new Set(picked);
    if (n.has(key)) n.delete(key); else n.add(key);
    return { picked: n, anchor: key };
  }
  if (shift && anchor != null) {
    const at = list.findIndex((v) => v.key === anchor);
    const to = list.findIndex((v) => v.key === key);
    if (at >= 0 && to >= 0) {
      const n = new Set(picked);
      for (let i = Math.min(at, to); i <= Math.max(at, to); i++) if (isTaskRow(display.rows.get(list[i].key))) n.add(list[i].key);
      return { picked: n, anchor };
    }
  }
  return { picked: new Set([key]), anchor: key };
}

// The picks still on show after the tree changed (a read, a filter, a branch closed): the same
// set when nothing went, so nothing draws again.
export function keepShown(picked, index) {
  if (!picked.size) return picked;
  const kept = [...picked].filter((k) => index.has(k));
  return kept.length === picked.size ? picked : new Set(kept);
}

// ---- packaging -----------------------------------------------------------------------------

// The lowest position (or place) holding every task given: where a new package goes.
export function commonHolder(display, tasks) {
  let path = null;
  for (const t of tasks) {
    const up = [];
    for (let k = t.subject?.id; k != null && display.rows.has(k); k = display.rows.get(k).parent) up.unshift(k);
    if (path == null) { path = up; continue; }
    let i = 0;
    while (i < path.length && i < up.length && path[i] === up[i]) i += 1;
    path = path.slice(0, i);
  }
  for (let i = (path || []).length - 1; i >= 0; i--) {
    const r = display.rows.get(path[i]);
    if (r?.type === "pos" || r?.type === "loc") return r;
  }
  return null;
}

// Why a package can't take a task (null: it can). The server has the last word (a task's home
// package, an hour meter); these are the reasons it gives, said before the click.
export function packageMisfit(pkg, t, display) {
  if (t.why_not) return `${t.name} can't join a package: ${t.why_not}.`;
  if (t.package?.id === pkg.id) return `${t.name} is in it already.`;
  if (t.package) return `${t.name} is in ${t.package.name} already: a task has one home package.`;
  const hours = pkg.cadence?.unit === "hours";
  if (hours && t.unit !== "hours") return `${pkg.name} goes by operating hours, and ${t.name} by the calendar: a package by hours holds tasks by hours.`;
  if (!hours && t.unit === "hours") return `${pkg.name} goes by the calendar, and ${t.name} by operating hours: put it in a package by hours on its position.`;
  const on = pkg.subject?.id;
  if (on && display?.rows?.has(on) && display.rows.has(t.subject?.id)) {
    let inside = false;
    for (let k = t.subject.id; k != null; k = display.rows.get(k)?.parent) if (k === on) { inside = true; break; }
    if (!inside) return `${pkg.name} is on ${pkg.subject.name}, and ${t.name} isn't there or inside it.`;
  }
  return null;
}

// How often a task comes on a package's visits: every visit, or every Nth when its interval is a
// whole multiple of the package's in the same unit (a 100 h task on every second 50 h visit).
export function visitFor(pkg, t) {
  const every = Number(pkg?.cadence?.every);
  if (!every || t.unit !== pkg.cadence?.unit) return { visit_rule: "every" };
  const k = Number(t.interval) / every;
  return Number.isInteger(k) && k >= 2 && k <= 100 ? { visit_rule: "nth", every_nth: k } : { visit_rule: "every" };
}

// The packages on this asset for the tasks given: the ones that can take all of them first (the
// same interval before the rest), then the others, each with why it can't.
export function rankPackages(pkgs, tasks, display) {
  const rows = pkgs.filter((p) => p.status !== "retired").map((p) => {
    const why = tasks.map((t) => packageMisfit(p, t, display)).find(Boolean) || null;
    const same = !why && tasks.every((t) => visitFor(p, t).visit_rule === "every" && Number(t.interval) === Number(p.cadence?.every) && t.unit === p.cadence?.unit);
    return { pkg: p, why, rank: why ? 2 : same ? 0 : 1 };
  });
  return rows.sort((a, b) => a.rank - b.rank || String(a.pkg.name).localeCompare(String(b.pkg.name), "en", { numeric: true }));
}
export function forecastItem(r, { design = false } = {}) {
  if (r?.type !== "pos" || design) return [];
  return [{ id: TASK_FORECAST, label: "Forecast…", title: "The work, failures and costs to come at this level and everything inside it, by month" }];
}
