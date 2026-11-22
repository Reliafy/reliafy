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
import { dayText, hoursText, moneyText, periodLabel, sig } from "./positionForecast.js";

export const TASK_TYPE = "mtask";
export const isTaskRow = (r) => r?.type === TASK_TYPE;
export const taskKey = (id) => `MT:${id}`;
// A work package's row (at the meeting point of its tasks), a reference to one of its tasks under
// it, and the Forecast rows under a task or a package (the row, then its lines).
export const PKG_TYPE = "mpkg";
export const PKG_REF_TYPE = "mpref";
export const FC_TYPE = "mfc";
export const FC_LINE_TYPE = "mfcl";
export const isPackageRow = (r) => r?.type === PKG_TYPE;
export const isPackageRef = (r) => r?.type === PKG_REF_TYPE;
export const isForecastRow = (r) => r?.type === FC_TYPE || r?.type === FC_LINE_TYPE;
export const packageKey = (id) => `MP:${id}`;
// Any of the Maintenance tab's own rows (a task, a package, a reference, a Forecast row or line).
export const isMaintRow = (r) => isTaskRow(r) || isPackageRow(r) || isPackageRef(r) || isForecastRow(r);

export const TASK_COLUMNS = [
  { id: "interval", label: "Interval", width: 140, min: 112, title: "How often it's done, or what raises it" },
  { id: "due", label: "Next due", width: 120, min: 108, title: "When it's next due (overdue in red)" },
  { id: "cost", label: "Cost each time", width: 120, min: 112, num: true, title: "What it costs each time it's done: typed on the task, or from its LSA" },
  { id: "trade", label: "Trade", width: 110, min: 90, title: "Who does it" },
  // Derryn, 22 Nov 2026: "There should be a 'packaged' column": the package it's in, a link to it.
  { id: "package", label: "Packaged", width: 170, min: 116, title: "The work package it's in (click to open it), or blank when it's in none" },
  { id: "from", label: "From", width: 210, min: 120, title: "Where it came from: an RCM decision, or added directly (and why)" },
  { id: "kind", label: "Kind", width: 140, min: 100, title: "On condition, fixed interval or failure finding; a task raised by an event says which" },
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
// `packages` (the work packages on this asset, listPackages): each shows as a row at the meeting
// point of its tasks (packageHomes), its tasks listed under it as references; `all`: every task
// (the filter's `tasks` aside), so a filter never moves a package. `forecasts`: each task and each
// package gets a child Forecast row (forecastRows fills it once the forecast is read: `forecast`).
export function graftTasks(display, tasks = [], { prune = false, packages = null, all = null, forecasts = false, forecast = null } = {}) {
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
      if (forecasts) rows.get(key).kids = forecastRows(rows, key, { kind: "task", task: t, forecast });
    }
    p.kids = [...keys, ...p.kids];
  }
  // The packages, each at the lowest position (or place) all its tasks sit under, after that
  // level's own tasks; under it, a reference to each of its tasks (they stay under their own
  // positions too, their Packaged cell naming it), then its Forecast.
  if (packages?.length) {
    const shown = new Set(tasks.map((t) => t.id));
    for (const home of packageHomes(display, all || tasks, packages).values()) {
      const h = rows.get(home.at);
      if (!holds(h)) continue;
      const pkey = packageKey(home.pkg.id);
      const members = home.tasks.filter((t) => shown.has(t.id) && rows.has(taskKey(t.id)));
      // A filter on: a package none of whose tasks match isn't on the way to a match.
      if (prune && !members.length) continue;
      const refs = members.map((t) => {
        const key = `${PKG_REF_TYPE}:${home.pkg.id}:${t.id}`;
        rows.set(key, {
          key, type: PKG_REF_TYPE, parent: pkey, kids: [], depth: h.depth + 2, own: noStatus(), sum: noStatus(),
          ref: { name: t.name, task: t, task_key: taskKey(t.id), on: t.subject?.name || "", position_id: h.key, task_position: t.subject?.id, package_id: home.pkg.id },
        });
        return key;
      });
      rows.set(pkey, {
        key: pkey, type: PKG_TYPE, parent: h.key, kids: refs, depth: h.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name: home.pkg.name, pkg: home.pkg, tasks: home.tasks, outside: home.outside, position_id: h.key,
          search: [home.pkg.name, home.pkg.trade, "package"].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      if (forecasts) rows.get(pkey).kids = [...refs, ...forecastRows(rows, pkey, { kind: "package", pkg: home.pkg, tasks: home.tasks, forecast })];
      h.tsum.packages = (h.tsum.packages || 0) + 1;
      const own = h.kids.filter((k) => rows.get(k)?.type === TASK_TYPE);
      const pk = h.kids.filter((k) => rows.get(k)?.type === PKG_TYPE);
      h.kids = [...own, ...pk, pkey, ...h.kids.filter((k) => ![TASK_TYPE, PKG_TYPE].includes(rows.get(k)?.type))];
    }
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
        if (s.packages) t.packages = (t.packages || 0) + s.packages;
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
      let y = r?.type === TASK_TYPE || r?.type === PKG_REF_TYPE;
      for (const c of r?.kids || []) if (has(c)) y = true;
      keep.set(k, y);
      return y;
    };
    const tops = display.roots || [...rows.values()].filter((r) => r.parent == null).map((r) => r.key);
    for (const k of tops) has(k);
    // A task's (or package's) Forecast stays with it.
    for (const r of rows.values()) if (r.kids.length) r.kids = r.kids.filter((c) => keep.get(c) || isForecastRow(rows.get(c)));
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
  const late = (all.overdue ? ` · ${all.overdue.toLocaleString("en-AU")} overdue` : "")
    + (all.packages ? ` · ${count(all.packages, "package")}` : "");
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
// Optimise…: how often to do it, from its failure modes' life models, in the table area.
export const TASK_OPTIMISE = "mtask-optimise";
export const TASK_PACKAGE = "mtask-package";
export const TASK_ADD_TO = "mtask-add-to";
export const TASK_CLEAR = "mtask-clear";
// Package the tasks… on a level: drafts packages from its tasks in none, in the table area.
export const TASK_DRAFT = "mtask-draft";
// A task row's menu: Open…, Optimise… (this row's task), then Package… and Add to package… for the tasks selected (the row
// itself when it isn't one of them), each greyed with the reason when none of them can go.
// `tasks`: the task-table rows it acts on; `canPackage`: false on a product's design, or view only.
export function taskRowActions(r, { tasks = null, canPackage = true } = {}) {
  const out = [{ id: TASK_OPEN, label: "Open…" },
    { id: TASK_OPTIMISE, label: "Optimise…", title: "How often to do it, worked out from the life model of the failure modes it prevents" }];
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
  // A package on a position takes any task on the same asset (it then lives where its tasks meet,
  // which moves up); one on a location, the tasks at it.
  const on = pkg.subject?.id;
  if (on && display?.rows?.has(on) && display.rows.has(t.subject?.id)) {
    const top = (k) => { let x = k; while (display.rows.get(x)?.parent != null && display.rows.has(display.rows.get(x).parent)) x = display.rows.get(x).parent; return x; };
    if (pkg.subject.kind === "location") {
      let inside = false;
      for (let k = t.subject.id; k != null; k = display.rows.get(k)?.parent) if (k === on) { inside = true; break; }
      if (!inside) return `${pkg.name} is at ${pkg.subject.name}, and ${t.name} isn't there or inside it.`;
    } else if (top(on) !== top(t.subject.id)) {
      return `${t.name} is on another asset: a package's tasks are all on one asset.`;
    }
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
// A level's Forecast…: everything below this point, in the table area. A position on an asset:
// its work, failures, costs and spares for the year. A place on an asset, and a design's rows: the
// spares for the year alone (work and failures are forecast by position, and a design has no
// due dates; its spares are the items built from it, or a planned fleet).
export function forecastItem(r, { design = false } = {}) {
  if (r?.type !== "pos" && r?.type !== "loc") return [];
  if (r.type === "pos" && !design) {
    return [{ id: TASK_FORECAST, label: "Forecast…", title: "The work, failures, costs and spares to come at this level and everything inside it, by month" }];
  }
  return [{ id: TASK_FORECAST, label: "Spares for the year…", title: design
    ? "The parts the items built from this design will use: what to hold, order and buy"
    : "What failures and tasks here and inside it will use: what to hold, order and buy" }];
}

// ---- where a package lives (Derryn, 22 Nov 2026) -------------------------------------------
// "Where does a maintenance package live though... I think at the lowest point in the tree that
// all the tasks meet!" A package is drawn at the meeting point of its tasks: the deepest position
// (or place) that every one of them sits at or under. It's worked out on every read from where its
// tasks are, never stored, so a task added or taken out moves it to the new meeting point. A
// package with none of its tasks in this tree yet sits where it was made (its `subject`). The tree
// is one asset (?root=): a package with tasks beyond it says how many (`outside`), never shows them.

// pkgId → {pkg, at (the meeting point's key), tasks (its tasks in this tree), outside (its others)}.
export function packageHomes(display, tasks = [], packages = []) {
  const by = new Map();
  for (const t of tasks) {
    const id = t.package?.id;
    if (!id) continue;
    if (!by.has(id)) by.set(id, []);
    by.get(id).push(t);
  }
  const out = new Map();
  for (const pkg of packages || []) {
    if (!pkg || pkg.status === "retired") continue;
    const mine = (by.get(pkg.id) || []).filter((t) => display.rows.has(t.subject?.id));
    const at = mine.length ? commonHolder(display, mine)?.key : display.rows.has(pkg.subject?.id) ? pkg.subject.id : null;
    if (at == null) continue;
    out.set(pkg.id, { pkg, at, tasks: mine, outside: Math.max(0, (pkg.task_count ?? mine.length) - mine.length) });
  }
  return out;
}

// A package's next visit (an ISO day), or null.
export const nextVisit = (pkg) => (typeof pkg?.next_visit === "string" ? pkg.next_visit : pkg?.next_visit?.on || null);

// What a package row says in the table's columns: how often, its next visit, what a visit costs
// (its tasks' costs each time, added up), its trade, and how many tasks it holds.
export function packageCell(r, col) {
  const p = r.ref.pkg;
  const tasks = r.ref.tasks || [];
  switch (col) {
    case "interval": return { text: p.cadence?.text ? p.cadence.text[0].toUpperCase() + p.cadence.text.slice(1) : "" };
    case "due": {
      const on = nextVisit(p);
      return { text: on || "", overdue: false, title: on ? "Its next visit" : p.status === "paused" ? "Paused" : "" };
    }
    case "cost": {
      const priced = tasks.filter((t) => t.cost?.amount != null);
      if (!priced.length) return { text: "", blank: "Not set", title: "None of its tasks has a cost each time yet" };
      const sum = priced.reduce((n, t) => n + Number(t.cost.amount), 0);
      const part = priced.length < tasks.length ? ` (${priced.length} of its ${tasks.length} tasks priced)` : "";
      return { text: money(sum), title: `${money(sum)} a visit if every task is on it: its tasks' costs each time added up${part}` };
    }
    case "trade": return { text: p.trade || "" };
    case "package": {
      const n = tasks.length;
      const more = r.ref.outside ? ` · ${r.ref.outside.toLocaleString("en-AU")} on other assets` : "";
      return { text: `${count(n, "task")}${more}`, title: r.ref.outside
        ? `${count(n, "task")} on this asset; ${count(r.ref.outside, "more task")} on other assets, not shown here (the tree shows one asset)`
        : `${count(n, "task")}, listed under it` };
    }
    case "from": return { text: p.parent ? `A layer on ${p.parent.name}` : "Work package" };
    case "kind": return { text: p.status === "paused" ? "Paused" : "" };
    default: return { text: "" };
  }
}

// Where a package's row says it sits, and why: "Shown at Mower, where its 3 tasks meet".
export function packageWhere(r, display) {
  const at = display.rows.get(r.ref.position_id)?.ref?.name || "this level";
  const n = r.ref.tasks?.length || 0;
  const why = !n ? `Shown at ${at}, where it was made: none of its tasks is on this asset yet`
    : n === 1 ? `Shown at ${at}, where its task is` : `Shown at ${at}, where its ${n} tasks meet`;
  return r.ref.outside ? `${why}. ${count(r.ref.outside, "more task")} on other assets aren't shown here.` : `${why}.`;
}

// ---- forecasts under a task and a package --------------------------------------------------
// Derryn, 22 Nov 2026: "For forecasts (of cost and spares), I think they are sub items of either a
// task or a maintenance package". Under each task and each package, a Forecast row: open it and
// its lines say when it's next due, how many times it comes in each month, the labour, the parts
// and spares it uses, and what it costs. They're read from the level's forecast (the same server
// forecast Forecast… opens: backend position_forecast), so the numbers agree with it.

export const FORECAST_LABEL = "Forecast";
const fcKey = (parent) => `MF:${parent}`;

// What a task's LSA says it uses each time: [{name, qty, unit}] (spares, then consumables).
export function taskParts(task) {
  const r = task?.resources || {};
  const out = [];
  for (const x of r.spares || []) out.push({ key: x.part_id || String(x.name).toLowerCase(), name: x.part_number ? `${x.name} (${x.part_number})` : x.name, qty: Number(x.qty) || 0, unit: "" });
  for (const x of r.consumables || []) out.push({ key: `${String(x.name).toLowerCase()}|${x.unit || ""}`, name: x.name, qty: Number(x.qty) || 0, unit: x.unit || "" });
  return out;
}

const addParts = (into, parts, times) => {
  for (const x of parts) {
    const e = into.get(x.key) || { ...x, qty: 0 };
    e.qty += x.qty * times;
    into.set(x.key, e);
  }
};
// "6 × Spin-on oil filter, 12 L Engine oil" (a count says ×; "each" is a count).
const COUNTED = new Set(["", "each", "ea", "no", "pcs", "piece", "pieces"]);
export const partsText = (parts) => parts.map((x) => `${sig(x.qty)}${COUNTED.has(String(x.unit).toLowerCase()) ? " ×" : ` ${x.unit}`} ${x.name}`).join(", ");

// One task's or one package's forecast from the level's: {entries, next, overdue, periods:
// [{label, count, labour, cost, priced}], count, labour, cost (null: none priced), unpriced, parts,
// end, why (none on dates: why)}. `fc`: the forecast read; `tasks`: the task-table rows.
export function forecastOf(tasks, fc) {
  const byId = new Map((fc?.tasks || []).map((e) => [e.id, e]));
  const why = new Map((fc?.not_on_dates || []).map((x) => [x.task?.id, x.reason]));
  const rows = fc?.rows || [];
  const periods = rows.map((r, i) => ({ start: r.start, label: periodLabel(r, fc.period || "month", i === 0), count: 0, labour: 0, cost: 0, priced: 0 }));
  const parts = new Map();
  let n = 0, labour = 0, cost = 0, priced = 0, unpriced = 0, next = null, overdue = false;
  const reasons = [];
  for (const t of tasks) {
    const e = byId.get(t.id);
    if (!e) {
      if (why.has(t.id)) reasons.push({ task: t, reason: why.get(t.id) });
      continue;
    }
    const dates = e.dates || [];
    n += dates.length;
    labour += (Number(e.labour_each) || 0) * dates.length;
    if (e.cost_each != null) { cost += Number(e.cost_each) * dates.length; priced += dates.length; } else if (dates.length) unpriced += 1;
    if (dates[0] && (!next || dates[0] < next)) next = dates[0];
    if (e.overdue) overdue = true;
    addParts(parts, taskParts(t), dates.length);
    for (const d of dates) {
      let i = periods.length - 1;
      while (i > 0 && d < periods[i].start) i -= 1;
      const p = periods[i];
      if (!p) continue;
      p.count += 1;
      p.labour += Number(e.labour_each) || 0;
      if (e.cost_each != null) { p.cost += Number(e.cost_each); p.priced += 1; }
    }
  }
  return {
    next, overdue, periods, count: n, labour, cost: priced ? cost : null, unpriced, end: fc?.end || null,
    // Spares first, then consumables, each in the order the tasks name them.
    parts: [...parts.values()].filter((x) => x.qty > 0),
    why: reasons,
  };
}

const timesWord = (n, kind) => (kind === "package" ? count(n, "task") : count(n, "time"));

// The Forecast row's roll-up: "12 times to 30 Nov 2027 · 24 h labour · $1,440".
export function forecastSummary(f, kind = "task") {
  if (!f) return "";
  if (!f.count) return f.why.length ? "Not on dates" : `None due to ${dayText(f.end)}`;
  return [`${timesWord(f.count, kind)} to ${dayText(f.end)}`, f.labour ? `${hoursText(f.labour)} labour` : null,
    f.cost != null ? `${moneyText(f.cost)}${f.unpriced ? " (some not priced)" : ""}` : "cost not set"].filter(Boolean).join(" · ");
}

// The lines under a Forecast row: [{id, label (the tree column), text (across the columns),
// title?, tone?}].
export function forecastLines(f, { kind = "task", pkg = null } = {}) {
  if (!f) return [];
  const out = [];
  const visit = kind === "package" ? nextVisit(pkg) : null;
  if (visit) out.push({ id: "next", label: "Next visit", text: dayText(visit) });
  else if (f.next) out.push({ id: "next", label: f.overdue ? "Overdue" : "Next due", text: f.overdue ? `done first, on ${dayText(f.next)}` : dayText(f.next), tone: f.overdue ? "danger" : null });
  for (const x of f.why) out.push({ id: `why:${x.task.id}`, label: "Not on dates", text: kind === "package" ? `${x.task.name}: ${x.reason}` : x.reason });
  if (!f.count && !f.why.length) out.push({ id: "none", label: "Not due", text: `before ${dayText(f.end)}` });
  for (const p of f.periods) {
    if (!p.count) continue;
    out.push({ id: `p:${p.start}`, label: p.label, text: [timesWord(p.count, kind), p.labour ? `${hoursText(p.labour)} labour` : null,
      p.priced ? moneyText(p.cost) : null].filter(Boolean).join(" · ") });
  }
  if (f.count) {
    out.push({ id: "parts", label: "Parts and spares", text: f.parts.length ? partsText(f.parts) : "None in its LSA",
      title: f.parts.length ? `What the LSA says is used, times the ${count(f.count, "time")} it comes to ${dayText(f.end)}` : "Add spares and consumables to the task's LSA: open the task, then What it needs" });
    out.push({ id: "total", label: "In all", text: forecastSummary(f, kind) });
  }
  return out;
}

// The Forecast row (and its lines) under a task or a package, into `rows`: its key, in a list.
// `forecast`: {fc, error} once read (null: not yet, so its line asks for it).
function forecastRows(rows, parentKey, { kind, task = null, pkg = null, tasks = null, forecast = null }) {
  const parent = rows.get(parentKey);
  const key = fcKey(parentKey);
  const list = kind === "task" ? [task] : tasks || [];
  const f = forecast?.fc ? forecastOf(list, forecast.fc) : null;
  const lines = forecast?.error ? [{ id: "error", label: "Not worked out", text: `Couldn't work out the forecast: ${forecast.error}`, tone: "danger" }]
    : f ? forecastLines(f, { kind, pkg }) : [{ id: "wait", label: "Working out…", text: "" }];
  const kids = lines.map((l) => {
    const k = `${key}:${l.id}`;
    rows.set(k, { key: k, type: FC_LINE_TYPE, parent: key, kids: [], depth: parent.depth + 2, own: noStatus(), sum: noStatus(),
      ref: { name: l.label, line: l, of: parentKey, position_id: parent.ref.position_id } });
    return k;
  });
  rows.set(key, {
    key, type: FC_TYPE, parent: parentKey, kids, depth: parent.depth + 1, own: noStatus(), sum: noStatus(),
    ref: { name: FORECAST_LABEL, of: parentKey, kind, summary: f ? forecastSummary(f, kind) : "", position_id: parent.ref.position_id },
  });
  return [key];
}

// Whether any Forecast row is open in the tree (`open`: the keys open), so the forecast is read.
export const forecastWanted = (open) => [...(open || [])].some((k) => typeof k === "string" && k.startsWith("MF:"));

// A package row's menu, a reference's, and a Forecast row's.
export const PKG_OPEN = "mpkg-open";
export const PKG_FORECAST = "mpkg-forecast";
export const REF_GO = "mpref-go";
export const FC_OPEN = "mfc-open";
export function packageRowActions() {
  return [{ id: PKG_OPEN, label: "Open…", title: "Its tasks, visits, what each visit needs, and pause or retire" },
    { id: PKG_FORECAST, label: "Forecast…", title: "The full forecast where its tasks meet: work, failures, costs and spares, by month" }];
}
export function refRowActions(r) {
  return [{ id: REF_GO, label: "Show the task", title: `${r.ref.name}, on ${r.ref.on || "its position"}` }];
}
export function forecastRowActions() {
  return [{ id: FC_OPEN, label: "Open the full forecast…", title: "The forecast for this level and everything inside it, with spares for the year" }];
}
