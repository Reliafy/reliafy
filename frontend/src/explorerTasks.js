// The Explorer's Maintenance tab (its Tasks view) is a tree-table, like the Modelling and Missions
// tabs (Derryn, 22 Nov 2026: "the maintenance tab should show tasks in the tree. That way for a
// certain level we can run the forecasts"; "at any level, you should see all the stuff from
// underneath it aggregated"). Under each position (or place) hang its own maintenance tasks, one
// row each, with the table's columns beside them: when next due (only when it's known), how often,
// what it costs each time, its package, where it came from and its kind. Each position's roll-up
// counts the tasks on it and on everything below it, at any depth, after its soonest next due.
// No forecasts in the tree (Derryn, 23 Nov 2026): a quick forecast is the left menu's Spares
// forecast (Decisions › Forecasts), a deliberate one a mission.
//
// The tasks come in one read for the asset opened (GET /api/maintenance/task-table?within=<root>:
// the server's roll-up, Maintenance.subtree_ids, never another asset's). Pure functions, tested in
// explorerTasks.test.js; the cells are drawn by TaskTreeTable.jsx.

import { counted } from "./menuStandard.js";
import { cellText, costWhere, fromRcm, kindText, money } from "./lsaTab.js";
import { sig } from "./positionForecast.js";
import { formatDate } from "./dates.js";
import { packageExtras, taskExtras } from "./taskExtras.js";

export const TASK_TYPE = "mtask";
export const isTaskRow = (r) => r?.type === TASK_TYPE;
export const taskKey = (id) => `MT:${id}`;
// A work package's row (at the meeting point of its tasks), and a reference to one of its tasks under it.
export const PKG_TYPE = "mpkg";
export const PKG_REF_TYPE = "mpref";
export const isPackageRow = (r) => r?.type === PKG_TYPE;
export const isPackageRef = (r) => r?.type === PKG_REF_TYPE;
export const packageKey = (id) => `MP:${id}`;
// A task's optional extras as rows under it (Derryn, 23 Nov 2026): "Labour · 1.5 h mechanic",
// "Part · Spindle kit × 1", "Cost · $40 each time" (taskExtras.js), only when set. Not tasks: they
// count in no roll-up, take no pick and no filter; a click opens the task at that fold-out.
export const EXTRA_TYPE = "mxtra";
// A task's extra (ref.task), or a package's (ref.pkg: its tasks' totals, opening the package).
export const isExtraRow = (r) => r?.type === EXTRA_TYPE && !!r.ref?.task;
export const isPackageExtra = (r) => r?.type === EXTRA_TYPE && !!r.ref?.pkg;
export const extraKey = (taskId, section, i = 0) => `MX:${taskId}:${section}:${i}`;
// Any of the Maintenance tab's own rows (a task, a package, a reference, a task's extra).
export const isMaintRow = (r) => isTaskRow(r) || isPackageRow(r) || isPackageRef(r) || r?.type === EXTRA_TYPE;

// Next due is the first column (a level's roll-up runs on after its soonest next due) and sorts.
export const TASK_COLUMNS = [
  { id: "due", label: "Next due", width: 132, min: 112, sort: true, sortWords: ["soonest first", "latest first"],
    title: "When it's next due, only when that's known: blank when there's no record to count from (overdue in red)" },
  { id: "interval", label: "Interval", width: 140, min: 112, title: "How often it's done, or what raises it" },
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
// point of its tasks (packageHomes), a leaf (its tasks are in its details); `all`: every task
// (the filter's `tasks` aside), so a filter never moves a package. Each level's `tall.next` is the
// soonest known next due at and below it (a task's or a package's), or null.
export function graftTasks(display, tasks = [], { prune = false, packages = null, all = null } = {}) {
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
      const extras = taskExtras(t).map((x, i) => ({ ...x, key: extraKey(t.id, x.section, i) }));
      rows.set(key, {
        key, type: TASK_TYPE, parent: pk, kids: extras.map((x) => x.key), depth: p.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name: t.name, task: t, position_id: pk,
          search: [t.name, t.package?.name, t.trade, cellText(t, "from"), kindText(t)].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      for (const x of extras) {
        rows.set(x.key, {
          key: x.key, type: EXTRA_TYPE, parent: key, kids: [], depth: p.depth + 2, own: noStatus(), sum: noStatus(),
          ref: { name: x.text, section: x.section, task: t, task_key: key, position_id: pk, search: x.text.toLowerCase() },
        });
      }
      p.tsum.tasks += 1;
      if (nextOf(t).overdue) p.tsum.overdue += 1;
      p.tsum.next = soonest(p.tsum.next, nextOf(t), t.name);
    }
    p.kids = [...keys, ...p.kids];
  }
  // The packages, each at the lowest position (or place) all its tasks sit under, after that
  // level's own tasks: one row each, with nothing under it (Derryn, 23 Nov 2026: listing its
  // tasks under it too was "an unnecessary double up"). Its tasks stay under their own positions,
  // their Packaged cell naming it; the package's details list them.
  if (packages?.length) {
    const shown = new Set(tasks.map((t) => t.id));
    for (const home of packageHomes(display, all || tasks, packages).values()) {
      const h = rows.get(home.at);
      if (!holds(h)) continue;
      const pkey = packageKey(home.pkg.id);
      const members = home.tasks.filter((t) => shown.has(t.id) && rows.has(taskKey(t.id)));
      // A filter on: a package none of whose tasks match isn't on the way to a match.
      if (prune && !members.length) continue;
      // Its tasks' extras together, as rows under it (the tasks themselves stay under their positions).
      const extras = packageExtras(home.tasks).map((x, i) => ({ ...x, key: `MX:P:${home.pkg.id}:${x.section}:${i}` }));
      for (const x of extras) {
        rows.set(x.key, {
          key: x.key, type: EXTRA_TYPE, parent: pkey, kids: [], depth: h.depth + 2, own: noStatus(), sum: noStatus(),
          ref: { name: x.text, section: x.section, pkg: home.pkg, position_id: h.key, search: x.text.toLowerCase() },
        });
      }
      rows.set(pkey, {
        key: pkey, type: PKG_TYPE, parent: h.key, kids: extras.map((x) => x.key), depth: h.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name: home.pkg.name, pkg: home.pkg, tasks: home.tasks, outside: home.outside, position_id: h.key,
          search: [home.pkg.name, home.pkg.trade, "package"].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      h.tsum.next = soonest(h.tsum.next, packageNext(home.pkg), home.pkg.name);
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
        t.next = soonest(t.next, s.next);
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
      let y = r?.type === TASK_TYPE || r?.type === PKG_TYPE || r?.type === PKG_REF_TYPE;
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
  const late = (all.overdue ? ` · ${all.overdue.toLocaleString("en-AU")} overdue` : "")
    + (all.packages ? ` · ${count(all.packages, "package")}` : "");
  if (all.tasks === own.tasks) return `${count(all.tasks, "task")} here${late}`;
  if (open && own.tasks) return `${own.tasks.toLocaleString("en-AU")} here · ${count(all.tasks, "task")} at and below${late}`;
  return `${count(all.tasks, "task")} at and below${late}`;
}

// What a cell says for a task (and its title); `due` and `cost` carry a tone of their own.
export function taskCell(t, col) {
  switch (col) {
    case "interval": {
      // A calendar rule in words, as a cell starts: "The first Saturday of every month".
      const text = cellText(t, "interval");
      return { text: text ? text[0].toUpperCase() + text.slice(1) : (t.on_event ? "On an event" : "") };
    }
    case "due": return dueCell(nextOf(t));
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

// A task row's ⋯; a position's (or place's) own: Add task…, Package the tasks….
export const TASK_OPEN = "mtask-open";
// Optimise…: how often to do it, from its failure modes' life models, in the table area.
export const TASK_OPTIMISE = "mtask-optimise";
export const TASK_PACKAGE = "mtask-package";
export const TASK_ADD_TO = "mtask-add-to";
export const TASK_CLEAR = "mtask-clear";
// Select: starts picking rows by tap (a phone has no Shift or Ctrl).
export const TASK_SELECT = "mtask-select";
// Package the tasks… on a level: drafts packages from its tasks in none, in the table area.
export const TASK_DRAFT = "mtask-draft";
export const TASK_RETIRE = "mtask-retire";
// A task row's menu: Open…, Optimise… (this row's task), then Package… and Add to package… for the tasks selected (the row
// itself when it isn't one of them), each greyed with the reason when none of them can go.
// `tasks`: the task-table rows it acts on; `canPackage`: false on a product's design, or view only.
export function taskRowActions(r, { tasks = null, canPackage = true, canSelect = false, viewOnly = null } = {}) {
  const list = tasks?.length ? tasks : r?.ref?.task ? [r.ref.task] : [];
  const many = list.length > 1;
  // Several picked: what acts on one task says so; Package and Add to package count them.
  const one = many ? { disabled: true, reason: `It works on one task: ${list.length} are picked.` } : {};
  const out = [{ id: TASK_OPEN, label: "Open", ...one },
    { id: TASK_OPTIMISE, label: "Optimise…", title: "How often to do it, worked out from the life model of the failure modes it prevents", ...one }];
  if (canSelect) out.push({ id: TASK_SELECT, label: "Select", title: "Pick this task, then tap others to add them" });
  if (canPackage) {
    const free = list.filter((t) => !t.why_not && !t.package);
    const stuck = list.length && list.every((t) => t.why_not);
    const why = stuck ? `${list.length === 1 ? "It can't" : "They can't"} join a package: ${list[0].why_not}`
      : !free.length ? `${list.length === 1 ? "It's" : "They're"} in a package already: take ${list.length === 1 ? "it" : "them"} out there first`
        : null;
    const n = many ? ` ${list.length} tasks` : "";
    out.push(
      { id: TASK_PACKAGE, label: counted("Package…", list.length), disabled: !!why, reason: why || undefined, title: `A new work package with${n || " this task"}` },
      { id: TASK_ADD_TO, label: many ? `Add ${list.length} tasks to a package…` : "Add to package…", disabled: !!why, reason: why || undefined,
        title: `Put${n || " this task"} in a package already on this asset` });
    if (many) out.push({ id: TASK_CLEAR, label: "Clear the selection" });
  }
  // Retire… (it stops falling due; its history stays), last, one task at a time.
  const retireWhy = viewOnly || (many ? "Retire one task at a time." : null);
  out.push({ id: TASK_RETIRE, label: "Retire…", danger: true, ...(retireWhy ? { disabled: true, reason: retireWhy } : {}) });
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

// A task raised by a failure or a find (corrective, follow-on): it answers its failure mode.
export const isResponseTask = (t) => ["failure", "found"].includes(t?.trigger?.kind);
// Does a task serve a failure mode (prevent one, or answer one)?
export const servesMode = (t) => isResponseTask(t) || (t?.modes || []).length > 0;
export const DIRECT_LINKED = "direct-linked";
export const DIRECT_NONE = "direct-none";
// The Maintenance tab's filter to the tasks serving no failure mode (the RCM header's gap count).
export const NO_MODE_FILTER = { from: [DIRECT_NONE] };
// A task added directly (not an RCM decision's) that serves no failure mode.
export const withoutMode = (t) => !fromRcm(t) && !servesMode(t);

// The tasks at or below a row (`key`, in `rows`: the Explorer's tree) that serve no failure mode
// (the RCM header's "N tasks not linked to a failure mode"). A task is on its subject's row.
export function tasksWithoutMode(rows, key, tasks = []) {
  if (!rows || key == null) return 0;
  const under = (k) => {
    for (let at = k, i = 0; at != null && i < 200; i += 1) {
      if (at === key) return true;
      at = rows.get(at)?.parent;
    }
    return false;
  };
  return tasks.filter((t) => withoutMode(t) && under(t.subject?.id)).length;
}

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
    of: (t) => {
      const n = nextOf(t);
      return n.overdue ? { value: "overdue", label: "Overdue", order: 0 }
        : n.on ? { value: "due", label: "On a date", order: 1 }
          : n.at_reading != null ? { value: "reading", label: "At a reading, no date", order: 2 }
            : { value: "", label: "Not known", order: 3 };
    } },
  { id: "cost", col: "cost", label: "Cost each time",
    of: (t) => (t.cost?.amount != null ? { value: "set", label: "Cost set", order: 0 } : { value: "", label: "Not set", order: 1 }) },
  { id: "trade", col: "trade", label: "Trade",
    of: (t) => (t.trade ? { value: t.trade, label: t.trade } : { value: "", label: "No trade", order: Infinity }) },
  { id: "package", col: "package", label: "Packaged",
    of: (t) => (t.package ? { value: t.package.id, label: t.package.name }
      : t.why_not ? { value: "-", label: "Can't join a package", order: Infinity } : { value: "", label: "In no package", order: Infinity - 1 }) },
  // Added directly, split by whether it serves a failure mode: the gap between a plan and its RCM.
  { id: "from", col: "from", label: "From",
    of: (t) => (fromRcm(t) ? { value: "rcm", label: "RCM", order: 0 }
      : servesMode(t) ? { value: DIRECT_LINKED, label: "Added directly: linked to a failure mode", order: 1 }
        : { value: DIRECT_NONE, label: "Added directly: no failure mode", order: 2 }) },
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
// Ctrl/⌘-click (or Space) adds or takes one. Only task rows are picked.
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
  // A task done at planned shutdowns: only a shutdown's visits are those.
  if (t.rule_kind === "shutdowns" && !pkg.shutdown) return `${t.name} is done at planned shutdowns, and ${pkg.name} isn't a shutdown: it joins a shutdown package only.`;
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
    case "due": return dueCell(packageNext(p));
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
        : `${count(n, "task")}: open the package to see them` };
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

// What a task's LSA says it uses each time: [{name, qty, unit}] (spares, then consumables).
export function taskParts(task) {
  const r = task?.resources || {};
  const out = [];
  for (const x of r.spares || []) out.push({ key: x.part_id || String(x.name).toLowerCase(), name: x.part_number ? `${x.name} (${x.part_number})` : x.name, qty: Number(x.qty) || 0, unit: "" });
  for (const x of r.consumables || []) out.push({ key: `${String(x.name).toLowerCase()}|${x.unit || ""}`, name: x.name, qty: Number(x.qty) || 0, unit: x.unit || "" });
  return out;
}

// "6 × Spin-on oil filter, 12 L Engine oil" (a count says ×; "each" is a count).
const COUNTED = new Set(["", "each", "ea", "no", "pcs", "piece", "pieces"]);
export const partsText = (parts) => parts.map((x) => `${sig(x.qty)}${COUNTED.has(String(x.unit).toLowerCase()) ? " ×" : ` ${x.unit}`} ${x.name}`).join(", ");

// A package row's menu, and a reference's.
export const PKG_OPEN = "mpkg-open";
export const REF_GO = "mpref-go";
export const PKG_RETIRE = "mpkg-retire";
export const REF_REMOVE = "mpref-remove";
export function packageRowActions(r, { viewOnly = null } = {}) {
  const pkg = r?.ref?.pkg;
  const wo = pkg?.open_work_order;
  const why = viewOnly || (wo ? `Close or cancel work order #${wo.number} first.` : null);
  return [{ id: PKG_OPEN, label: "Open", title: "Its tasks, visits, what each visit needs, and pause or retire" },
    { id: PKG_RETIRE, label: "Retire…", danger: true, ...(why ? { disabled: true, reason: why } : {}) }];
}
export function refRowActions(r, { viewOnly = null } = {}) {
  return [{ id: REF_GO, label: "Show the task", title: `${r.ref.name}, on ${r.ref.on || "its position"}` },
    { id: REF_REMOVE, label: "Remove from package…", danger: true, ...(viewOnly ? { disabled: true, reason: viewOnly } : {}) }];
}

// ---- next due (Derryn, 23 Nov 2026: "Next due" is a column, blank when we don't know) ----------
// The server says what's known (backend/maintenance/next_due.py): {on, at_reading, unit, basis, why,
// overdue}. A date, else the reading it falls due at ("at 1,250 h"), else blank with why. Nothing
// here works out a date.

const BLANK_NEXT = { on: null, at_reading: null, unit: null, basis: null, why: null, overdue: false };
// A task's next due (a row from before the server said: blank, never its old count from "now").
export const nextOf = (t) => t?.next || { ...BLANK_NEXT, why: "Not known" };
// A package's (a paused or retired one isn't listed with one: why, from its status).
export function packageNext(p) {
  if (p?.next) return p.next;
  return { ...BLANK_NEXT, why: p?.status === "paused" ? "Paused" : p?.status === "retired" ? "Retired" : "No visit to come" };
}

// "5 Dec 2026", the one date format (dates.js): a day as written, whatever the browser's language.
export const dayWords = (iso) => (iso ? formatDate(String(iso).slice(0, 10)) : "");
const UNIT_SHORT = { hours: "h", hour: "h", h: "h" };
// "at 1,250 h" (a reading's unit as the counter says it).
export const readingWords = (n) => (n?.at_reading == null ? ""
  : `at ${Number(n.at_reading).toLocaleString("en-GB", { maximumFractionDigits: 1 })} ${UNIT_SHORT[String(n.unit || "").toLowerCase()] || n.unit || ""}`.trim());

// What a Next due cell says: {text, overdue, title, blank}. A date ("5 Dec 2026"), the reading
// ("at 1,250 h"), or blank (—) with why in the tooltip.
export function dueCell(n) {
  if (n?.on) {
    const at = readingWords(n);
    return { text: n.on, words: dayWords(n.on), overdue: !!n.overdue,
      title: [n.overdue ? "Overdue" : null, at ? `Due ${at}` : null, n.basis].filter(Boolean).join(". ") };
  }
  if (n?.at_reading != null) return { text: readingWords(n), words: readingWords(n), overdue: false, title: n.why || "" };
  return { text: "", words: "", overdue: false, blank: true, title: n?.why || "Not known" };
}

// The sooner of two known next dues (a level's roll-up): a date beats none; `name` says whose.
function soonest(a, b, name = null) {
  const bb = b?.on ? { on: b.on, overdue: !!b.overdue, name: b.name || name } : null;
  if (!a) return bb;
  if (!bb) return a;
  return bb.on < a.on ? bb : a;
}

// A level's Next due cell: the soonest next due at and below it, or blank.
export function levelDueCell(r) {
  const n = r?.tall?.next;
  if (!n) return { text: "", words: "", blank: true, overdue: false, title: r?.tall?.tasks ? "No date known for anything here or below" : "" };
  return { text: n.on, words: dayWords(n.on), overdue: !!n.overdue, title: `The soonest here or below${n.name ? `: ${n.name}` : ""}${n.overdue ? " (overdue)" : ""}` };
}

// What a row sorts by in Next due: a date first, then a reading alone, then blanks (always last).
function dueKey(r) {
  const n = isTaskRow(r) || isPackageRef(r) ? nextOf(r.ref.task) : isPackageRow(r) ? packageNext(r.ref.pkg)
    : r?.tall ? (r.tall.next ? { on: r.tall.next.on } : null) : null;
  if (n?.on) return [0, n.on];
  if (n?.at_reading != null) return [1, Number(n.at_reading)];
  return null;
}

// The Next due sort after a header click: soonest first, then latest first, then the tree's order.
export function nextDueSort(sort, col) {
  if (!sort || sort.col !== col) return { col, dir: 1 };
  return sort.dir === 1 ? { col, dir: -1 } : null;
}

// Each level's rows in Next due order (outlineTree flatten's `order`): its tasks among themselves,
// its packages, then its positions by their soonest; blanks last either way.
export function dueOrder(display, sort) {
  if (!sort || sort.col !== "due") return null;
  return (keys) => {
    const rows = keys.map((k) => display.rows.get(k));
    if (!rows.some((r) => isTaskRow(r) || isPackageRow(r) || r?.tall)) return keys;
    const group = (r) => (isTaskRow(r) ? 0 : isPackageRow(r) ? 1 : isPackageRef(r) ? 2 : 3);
    return rows.map((r, i) => ({ k: keys[i], i, g: group(r), v: dueKey(r) }))
      .sort((a, b) => {
        if (a.g !== b.g) return a.g - b.g;
        if (!a.v || !b.v) return !a.v && !b.v ? a.i - b.i : a.v ? -1 : 1;
        if (a.v[0] !== b.v[0]) return a.v[0] - b.v[0];
        const c = a.v[1] < b.v[1] ? -1 : a.v[1] > b.v[1] ? 1 : 0;
        return c ? c * sort.dir : a.i - b.i;
      })
      .map((x) => x.k);
  };
}

// ---- Open in › (Derryn, 23 Nov 2026) ----------------------------------------------------------
// "Quick one-off work lives in the left menu's tools; the detailed, saved work for a specific asset
// lives in the Explorer." A position (and everything below it), a task or a work package opens the
// left menu's tools filled in from it: Optimal replacement (a scratch Optimise: Optimise… on the
// task is the one that changes its interval) and the forecast tool's three views. Nothing is
// written to the Explorer; the tool names where it came from, with a link back.
export const OPEN_IN = [
  { id: "open-in-optimise", label: "Optimise", view: null, title: "Optimal replacement, filled in from here: try other intervals without changing the task" },
  { id: "open-in-spares", label: "Spares forecast", view: "spares", title: "How many spares these will use, filled in from here and everything below it" },
  { id: "open-in-hours", label: "Hours forecast", view: "hours", title: "The maintenance hours these will need, filled in from here and everything below it" },
  { id: "open-in-costs", label: "Cost forecast", view: "costs", title: "What these will cost to maintain, filled in from here and everything below it" },
];
const OPEN_IN_IDS = new Set(OPEN_IN.map((x) => x.id));
export const isOpenIn = (id) => OPEN_IN_IDS.has(id);

// What a row opens the tools from: {kind, id}, or null (a place, a design's row, a reference).
export function openInSource(r, { design = false } = {}) {
  if (design) return null;
  if (r?.type === "pos") return { kind: "position", id: r.key };
  if (isTaskRow(r)) return { kind: "task", id: r.ref.task.id };
  if (isPackageRow(r)) return { kind: "package", id: r.ref.pkg.id };
  return null;
}

// The row's Open in › submenu ([] where it has none).
export function openInItem(r, opts = {}) {
  if (!openInSource(r, opts)) return [];
  return [{ id: "open-in", label: "Open in", title: "Open a left-menu tool filled in from this row: nothing here changes",
    items: OPEN_IN.map(({ id, label, title }) => ({ id, label, title })) }];
}

// Where an Open in item goes: the tool's address, filled in from the row (`root`: the asset opened).
export function openInLink(r, id, root = null, opts = {}) {
  const src = openInSource(r, opts);
  const it = OPEN_IN.find((x) => x.id === id);
  if (!src || !it) return null;
  const q = new URLSearchParams({ from: `${src.kind}:${src.id}` });
  if (root) q.set("root", root);
  return `${it.view ? `/forecasts/${it.view}` : "/strategy/replacement"}?${q}`;
}
