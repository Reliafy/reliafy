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

import { cellText, costWhere, kindText, money } from "./lsaTab.js";

export const TASK_TYPE = "mtask";
export const isTaskRow = (r) => r?.type === TASK_TYPE;
export const taskKey = (id) => `MT:${id}`;

export const TASK_COLUMNS = [
  { id: "interval", label: "Interval", width: 140, title: "How often it's done, or what raises it" },
  { id: "due", label: "Next due", width: 120, title: "When it's next due (overdue in red)" },
  { id: "cost", label: "Cost each time", width: 120, num: true, title: "What it costs each time it's done: typed on the task, or from its LSA" },
  { id: "package", label: "Package", width: 170, title: "The work package it's done in, or blank when it's done on its own" },
  { id: "from", label: "From", width: 210, title: "Where it came from: an RCM decision, or added directly (and why)" },
  { id: "kind", label: "Kind", width: 140, title: "On condition, fixed interval or failure finding; a task raised by an event says which" },
];
export const TASK_TREE_HEAD = "Position, and its tasks";

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });
const blank = () => ({ tasks: 0, overdue: 0 });

// The tree with each position's (and place's) tasks in it. The display given is left as it is;
// position and place rows gain `tsum` (their own: tasks, overdue) and `tall` (theirs and everything
// below). A task whose position isn't in the tree (another asset, a pinned branch) isn't shown.
export function graftTasks(display, tasks = []) {
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
    case "package": return t.package ? { text: t.package.name, title: `Done in ${t.package.name}` }
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
export function taskRowActions() {
  return [{ id: TASK_OPEN, label: "Open…" }];
}
export function forecastItem(r, { design = false } = {}) {
  if (r?.type !== "pos" || design) return [];
  return [{ id: TASK_FORECAST, label: "Forecast…", title: "The work, failures and costs to come at this level and everything inside it, by month" }];
}
