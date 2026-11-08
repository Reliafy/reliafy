// The Explorer's LSA tab (Assets › Explorer, ?tab=lsa; ?tab=packages, its name
// until 9 Nov 2026, opens it too): the logistic support analysis of the tasks
// at the picked position or location and inside it. The RCM says what is done
// and why; the LSA says how: per task the labour, tools and instruments,
// spares, consumables, access and method, and the work packages that bundle
// tasks done on one visit (each visit raises one work order). The logic here;
// the page is components/LsaPanel.jsx, a task's LSA components/LsaTask.jsx.

import { toCsv } from "./csv.js";
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
// The LSA tab is a table of every task on the picked row and below it (the
// server's task-table read), formatted like the RCM table: search it, sort it,
// tick tasks and package them together, with what each needs beside it.


export const TASK_COLUMNS = [
  { id: "position", label: "Position", width: 170, title: "The position or place the task is on" },
  { id: "mode", label: "Failure mode", width: 230, title: "The failure mode it prevents, with its function › functional failure" },
  { id: "task", label: "Task", width: 240 },
  { id: "kind", label: "Kind", width: 140, title: "On condition, fixed interval or failure finding" },
  { id: "interval", label: "Interval", width: 130 },
  { id: "trade", label: "Trade", width: 110 },
  { id: "due", label: "Next due", width: 110 },
  { id: "package", label: "Package", width: 200, title: "The work package it's done in; blank when it's done on its own" },
  { id: "hours", label: "Hours", width: 74, num: true, title: "Labour hours: each line's people × hours, added up" },
  { id: "people", label: "People", width: 74, num: true, title: "How many people the work needs" },
  { id: "tools", label: "Tools", width: 70, num: true, title: "Tools and instruments (hover for their names)" },
  { id: "spares", label: "Spares", width: 74, num: true, title: "Spare part lines to bring" },
  { id: "consumables", label: "Consumables", width: 112, num: true, title: "Consumable lines to bring" },
  { id: "method", label: "Method", width: 180, title: "How it's done" },
];
export const DEFAULT_TASK_COLUMNS = TASK_COLUMNS.map((c) => c.id);
const COLUMN_IDS = new Set(DEFAULT_TASK_COLUMNS);
const COUNTED = { tools: "tools", spares: "spares", consumables: "consumables" };

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
    case "hours": return t.resources?.labour_hours ? num(t.resources.labour_hours) : "";
    case "people": return t.resources?.people ? String(t.resources.people) : "";
    case "tools": case "spares": case "consumables": {
      const n = (t.resources?.[COUNTED[col]] || []).length;
      return n ? String(n) : "";
    }
    case "method": return t.resources?.method || "";
    default: return "";
  }
}

// A number as people read it: up to 2 decimals, no trailing zeros.
export function num(v) {
  return Number.isFinite(v) ? String(Math.round(v * 100) / 100) : "";
}

// A resource line in words: "2 × O-ring", "0.2 kg Grease", "Photometer (reads Free chlorine)".
export function lineText(kind, x) {
  if (kind === "labour") return `${x.people || 1} × ${x.trade || "anyone"} for ${num(x.hours)} h`;
  if (kind === "tools") return `${x.qty ? `${num(x.qty)} × ` : ""}${x.name}${x.point ? ` (reads ${x.point.name})` : ""}`;
  if (kind === "spares") return `${num(x.qty)} × ${x.part_number ? `${x.part_number} ` : ""}${x.name}`;
  if (kind === "consumables") return `${num(x.qty)}${x.unit ? ` ${x.unit}` : ""} ${x.name}`;
  return "";
}

// The names behind a counted column, for its hover: "Photometer, Brush".
export function countTitle(t, col) {
  const kind = COUNTED[col];
  return kind ? (t.resources?.[kind] || []).map((x) => lineText(kind, x)).join("\n") : "";
}

const DAYS = { hours: 1 / 24, days: 1, weeks: 7, months: 30.4375, years: 365.25 };
// The value a column sorts by: an interval by its length in days, the rest by text.
function sortValue(t, col) {
  if (col === "interval") return t.on_event || t.interval == null ? null : t.interval * (DAYS[t.unit] ?? 1);
  if (col === "hours") return t.resources?.labour_hours || null;
  if (col === "people") return t.resources?.people || null;
  if (COUNTED[col]) return (t.resources?.[COUNTED[col]] || []).length || null;
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

// ---- the LSA: what the tasks need ------------------------------------------------------

// What a set of tasks needs together (the tasks ticked, a visit): labour hours by
// trade (a line with no trade takes its task's), the tools (each once, the most
// any task needs), the spares to stage and the consumables (quantities added
// up), and the permits. The same sums as the server's lsa_rollup (a package's
// read).
export function lsaRollup(tasks = []) {
  const labour = new Map(), tools = new Map(), spares = new Map(), consumables = new Map(), permits = [];
  for (const t of tasks) {
    const r = t.resources || {};
    for (const x of r.labour || []) {
      const trade = x.trade || t.trade || "";
      const row = labour.get(trade.toLowerCase()) || { trade, hours: 0, people: 0 };
      row.hours += (x.people || 1) * (x.hours || 0);
      row.people = Math.max(row.people, x.people || 1);
      labour.set(trade.toLowerCase(), row);
    }
    for (const x of r.tools || []) {
      const row = tools.get(x.name.toLowerCase()) || { name: x.name, qty: null };
      if (x.qty != null) row.qty = Math.max(row.qty || 0, x.qty);
      tools.set(x.name.toLowerCase(), row);
    }
    for (const x of r.spares || []) {
      const key = x.part_id || x.name.toLowerCase();
      const row = spares.get(key) || { part_id: x.part_id || null, part_number: x.part_number || null, name: x.name, qty: 0 };
      row.qty += x.qty || 0;
      spares.set(key, row);
    }
    for (const x of r.consumables || []) {
      const key = `${x.name.toLowerCase()}|${(x.unit || "").toLowerCase()}`;
      const row = consumables.get(key) || { name: x.name, unit: x.unit || "", qty: 0, cost: null };
      row.qty += x.qty || 0;
      if (x.cost != null) row.cost = (row.cost || 0) + x.cost;
      consumables.set(key, row);
    }
    for (const p of r.access?.permits || []) if (!permits.some((q) => q.toLowerCase() === p.toLowerCase())) permits.push(p);
  }
  const r2 = (v) => Math.round(v * 100) / 100;
  const az = (a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base", numeric: true });
  const rows = [...labour.values()].map((x) => ({ ...x, hours: r2(x.hours) }));
  return {
    tasks: tasks.length,
    labour_hours: r2(rows.reduce((n, x) => n + x.hours, 0)),
    labour: rows.sort((a, b) => b.hours - a.hours || a.trade.localeCompare(b.trade)),
    tools: [...tools.values()].sort(az),
    spares: [...spares.values()].map((x) => ({ ...x, qty: r2(x.qty) })).sort(az),
    consumables: [...consumables.values()].map((x) => ({ ...x, qty: r2(x.qty), cost: x.cost == null ? null : r2(x.cost) })).sort(az),
    permits,
  };
}

// A rollup as lines to read: [{label, text}], only those with something in them.
export function rollupLines(rollup) {
  if (!rollup) return [];
  const out = [];
  if (rollup.labour_hours) {
    const by = rollup.labour.map((x) => `${x.trade || "no trade set"} ${num(x.hours)} h`).join(", ");
    out.push({ label: "Labour", text: `${num(rollup.labour_hours)} h${by ? ` (${by})` : ""}` });
  }
  if (rollup.tools.length) out.push({ label: "Tools", text: rollup.tools.map((x) => lineText("tools", x)).join(", ") });
  if (rollup.spares.length) out.push({ label: "Spares to stage", text: rollup.spares.map((x) => lineText("spares", x)).join(", ") });
  if (rollup.consumables.length) out.push({ label: "Consumables", text: rollup.consumables.map((x) => lineText("consumables", x)).join(", ") });
  if (rollup.permits?.length) out.push({ label: "Permits", text: rollup.permits.join(", ") });
  return out;
}

// A position's labour in a year, from its tasks' LSA and intervals: each
// calendar task's labour hours × 365.25 ÷ its interval in days, added up.
// Tasks raised by an event, or counted by use (run hours), have no yearly
// count: left out and counted (onEvent, byUse). spareLines: the spare lines
// across its tasks.
export function annualLsa(tasks = []) {
  let hours = 0, onEvent = 0, byUse = 0, spareLines = 0, counted = 0;
  for (const t of tasks) {
    const r = t.resources;
    if (!r) continue;
    spareLines += (r.spares || []).length;
    if (!r.labour_hours) continue;
    if (t.on_event) { onEvent += 1; continue; }
    const days = DAYS[t.unit] && t.unit !== "hours" ? t.interval * DAYS[t.unit] : null;
    if (!days) { byUse += 1; continue; }
    hours += (r.labour_hours * 365.25) / days;
    counted += 1;
  }
  return { hours: Math.round(hours * 10) / 10, counted, onEvent, byUse, spareLines };
}

export function annualText(a) {
  if (!a || (!a.counted && !a.spareLines && !a.onEvent && !a.byUse)) return "";
  const left = [a.onEvent ? `${a.onEvent} raised by an event` : null, a.byUse ? `${a.byUse} counted by use` : null].filter(Boolean);
  return `Annual labour: ${num(a.hours)} h; spares: ${a.spareLines} line${a.spareLines === 1 ? "" : "s"}`
    + (left.length ? ` (left out: ${left.join(", ")})` : "");
}

// The table as CSV: every column, with the tools, spares and consumables named
// (not counted) and the labour lines in full.
export function lsaCsv(tasks) {
  const cols = TASK_COLUMNS.filter((c) => c.id !== "tools" && c.id !== "spares" && c.id !== "consumables");
  const head = [...cols.map((c) => c.label), "Labour", "Tools", "Spares", "Consumables", "Duration (h)", "Downtime (h)", "Permits", "Instructions"];
  const rows = tasks.map((t) => {
    const r = t.resources || {};
    const names = (kind) => (r[kind] || []).map((x) => lineText(kind, x)).join("; ");
    return [
      ...cols.map((c) => (c.num ? (cellText(t, c.id) === "" ? "" : Number(cellText(t, c.id))) : cellText(t, c.id))),
      names("labour"), names("tools"), names("spares"), names("consumables"),
      r.duration_hours ?? "", r.access?.downtime_hours ?? "", (r.access?.permits || []).join("; "), t.instructions || "",
    ];
  });
  return toCsv([head, ...rows]);
}

// ---- a task's LSA, edited ---------------------------------------------------------------
// Each section is edited as rows of text (what the inputs hold) and saved
// cleaned: a row with nothing in it is dropped, numbers are numbers, blanks are
// left out. null: the section is empty (it clears).

const n = (v) => (v === "" || v == null ? null : Number(v));
const filled = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null));

export function cleanSection(kind, value) {
  if (kind === "labour") {
    const rows = (value || []).filter((x) => String(x.hours ?? "").trim() !== "" || (x.trade || "").trim())
      .map((x) => ({ trade: (x.trade || "").trim(), people: n(x.people) ?? 1, hours: n(x.hours) ?? 0 }));
    return rows.length ? rows : null;
  }
  if (kind === "tools") {
    const rows = (value || []).filter((x) => (x.name || "").trim())
      .map((x) => filled({ name: x.name.trim(), qty: n(x.qty), note: (x.note || "").trim(), point_id: x.point_id || null }));
    return rows.length ? rows : null;
  }
  if (kind === "spares") {
    const rows = (value || []).filter((x) => x.part_id || (x.name || "").trim())
      .map((x) => filled({ part_id: x.part_id || null, name: (x.name || "").trim(), qty: n(x.qty) ?? 1 }));
    return rows.length ? rows : null;
  }
  if (kind === "consumables") {
    const rows = (value || []).filter((x) => (x.name || "").trim())
      .map((x) => filled({ name: x.name.trim(), qty: n(x.qty) ?? 1, unit: (x.unit || "").trim(), cost: n(x.cost) }));
    return rows.length ? rows : null;
  }
  if (kind === "access") {
    const permits = String(value?.permits || "").split(",").map((x) => x.trim()).filter(Boolean);
    const out = filled({ downtime_hours: n(value?.downtime_hours), isolation: (value?.isolation || "").trim(),
      access_equipment: (value?.access_equipment || "").trim() });
    if (permits.length) out.permits = permits;
    return Object.keys(out).length ? out : null;
  }
  if (kind === "method") return (value || "").trim() || null;
  if (kind === "duration_hours") return n(value);
  return null;
}

// A section as the inputs hold it (text), from the task's resources.
export function sectionDraft(kind, resources = {}) {
  const s = (v) => (v == null ? "" : String(v));
  if (kind === "labour") return (resources.labour || []).map((x) => ({ trade: x.trade || "", people: s(x.people), hours: s(x.hours) }));
  if (kind === "tools") return (resources.tools || []).map((x) => ({ name: x.name, qty: s(x.qty), note: x.note || "", point_id: x.point_id || "" }));
  if (kind === "spares") return (resources.spares || []).map((x) => ({ part_id: x.part_id || "", name: x.name || "", qty: s(x.qty), part_number: x.part_number || "" }));
  if (kind === "consumables") return (resources.consumables || []).map((x) => ({ name: x.name, qty: s(x.qty), unit: x.unit || "", cost: s(x.cost) }));
  if (kind === "access") {
    const a = resources.access || {};
    return { downtime_hours: s(a.downtime_hours), permits: (a.permits || []).join(", "), isolation: a.isolation || "", access_equipment: a.access_equipment || "" };
  }
  if (kind === "method") return resources.method || "";
  if (kind === "duration_hours") return s(resources.duration_hours);
  return "";
}
