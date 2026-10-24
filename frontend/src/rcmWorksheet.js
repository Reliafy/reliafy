// The RCM study's worksheet as an outline grid (RcmWorksheet): the study's own
// hierarchy as the index (function → functional failure → failure mode), and
// the worksheet's columns beside it (effects, consequence, decision, task,
// interval, the evidence check...). A failure mode's decision is its task, so
// the task is columns on the mode's row, not a level of its own.
//
// Pure functions (no React), tested in rcmWorksheet.test.js: the display
// built from the study's functions with each row's roll-up of what's inside
// it, the columns, the filter chips, the sort that keeps the tree, the edits
// (each returns a new functions list; nothing is saved until the study is),
// the CSV rows, and what's remembered on this device.

import { filterRows } from "./outlineTree.js";

export const LEVELS = [
  { type: "fn", label: "Function", plural: "Functions", child: "failures" },
  { type: "fail", label: "Functional failure", plural: "Functional failures", child: "modes" },
  { type: "mode", label: "Failure mode", plural: "Failure modes", child: null },
];
export const LEVEL_OF = Object.fromEntries(LEVELS.map((l, i) => [l.type, { ...l, depth: i }]));
// The RCM on the positions (an Explorer position's RCM tab) has two more kinds
// of row: each position in it (when there's more than one), and, under a
// position, its failure modes under no functional failure yet.
export const POSITION_LEVEL = { type: "pos", label: "Position", plural: "Positions", child: "functions" };
LEVEL_OF.pos = { ...POSITION_LEVEL, depth: 0 };
LEVEL_OF.unassigned = { type: "unassigned", label: "Not under a functional failure", plural: "Unassigned", child: "modes", depth: 1 };

export const OUTCOME_LABEL = {
  on_condition: "On-condition",
  fixed_interval: "Fixed-interval",
  rtf: "Run-to-failure",
  failure_finding: "Failure-finding",
  redesign: "Redesign",
  accept: "Accept risk",
};
export const CONSEQUENCE_LABEL = {
  safety: "Safety",
  environmental: "Environmental",
  operational: "Operational",
  non_operational: "Non-operational",
  hidden: "Hidden",
};
export const STATUS_LABEL = {
  supported: "Supported",
  contradicted: "Contradicted",
  inconclusive: "Inconclusive",
  unevidenced: "No evidence",
  stale: "Stale link",
};
const RTF_LABEL = { random: "random", uneconomic: "not economic" };

// Which decisions take a task and an interval (as the decision dialog asks).
export const TASK_OUTCOMES = new Set(["on_condition", "fixed_interval", "rtf", "failure_finding"]);
export const INTERVAL_OUTCOMES = new Set(["on_condition", "fixed_interval", "failure_finding"]);

const blank = () => ({
  modes: 0, undecided: 0, tasks: 0, hidden: 0, safety: 0,
  supported: 0, contradicted: 0, unsure: 0, stale: 0,
});

// A failure mode's own counts (each 0 or 1).
function modeCounts(m) {
  const d = m.decision;
  const s = d?.status;
  return {
    modes: 1,
    undecided: d ? 0 : 1,
    tasks: hasTask(m) ? 1 : 0,
    hidden: m.consequence === "hidden" ? 1 : 0,
    safety: m.consequence === "safety" || m.consequence === "environmental" ? 1 : 0,
    supported: s === "supported" ? 1 : 0,
    contradicted: s === "contradicted" ? 1 : 0,
    unsure: s === "inconclusive" || s === "unevidenced" ? 1 : 0,
    stale: s === "stale" ? 1 : 0,
  };
}

export const hasTask = (m) => !!(m.decision && (String(m.decision.task || "").trim() || m.decision.interval));

// The display: rows {key, type, ref, at, parent, kids, depth, sum} keyed by
// the node's id (a repeated id gets a suffix, so every row is drawn), and the
// tops. `at` is where the node is: [function, failure, mode] indexes. `sum`
// counts the failure modes inside the row (for a mode, the mode itself).
export function buildRcmDisplay(functions) {
  const rows = new Map();
  const roots = [];
  const counts = { fn: 0, fail: 0, mode: 0 };
  const keyFor = (id, type, at) => {
    let key = typeof id === "string" && id ? id : `${type}:${at.join(".")}`;
    while (rows.has(key)) key += "~";
    return key;
  };
  const add = (type, ref, at, parent) => {
    const key = keyFor(ref.id, type, at);
    const r = { key, type, ref, at, parent, kids: [], depth: at.length - 1, sum: blank() };
    rows.set(key, r);
    (parent == null ? roots : rows.get(parent).kids).push(key);
    counts[type] += 1;
    return r;
  };
  (functions || []).forEach((fn, fi) => {
    const f = add("fn", fn, [fi], null);
    (fn.failures || []).forEach((fail, xi) => {
      const x = add("fail", fail, [fi, xi], f.key);
      (fail.modes || []).forEach((mode, mi) => {
        const m = add("mode", mode, [fi, xi, mi], x.key);
        m.sum = modeCounts(mode);
        for (const k of Object.keys(m.sum)) {
          x.sum[k] += m.sum[k];
          f.sum[k] += m.sum[k];
        }
      });
    });
  });
  return { rows, roots, counts };
}

// The display for the RCM on the positions (GET /api/maintenance/positions/:id/rcm):
// the same rows as a study's, keyed by the graph's own ids, each with the
// position it's on (ref.position_id). With more than one position, each is a
// row at the top (named by its path below the first: "Pump › Motor"), the
// functions inside it; a position's failure modes under no functional failure
// go under an "unassigned" row of their own, so nothing is hidden.
export function buildPositionRcmDisplay(sheet) {
  const rows = new Map();
  const roots = [];
  const counts = { pos: 0, fn: 0, fail: 0, mode: 0, unassigned: 0 };
  const add = (type, key, ref, parent) => {
    const depth = parent == null ? 0 : rows.get(parent).depth + 1;
    const r = { key, type, ref, at: null, parent, kids: [], depth, sum: blank() };
    rows.set(key, r);
    (parent == null ? roots : rows.get(parent).kids).push(key);
    counts[type] += 1;
    return r;
  };
  const positions = sheet?.positions || [];
  const withPositions = positions.length > 1;
  const path = [];
  for (const p of positions) {
    path.length = Math.max(0, p.depth);
    path.push(p.name);
    const label = p.depth === 0 ? p.name : path.slice(1).join(" › ");
    const top = withPositions
      ? add("pos", `P:${p.id}`, { id: p.id, text: label, name: p.name, position_id: p.id, analysed: p.analysed, rollup: p.rollup }, null).key
      : null;
    const modeRow = (m, parent, ffId) => {
      const r = add("mode", m.id, { ...m, position_id: p.id, functional_failure_id: ffId }, parent);
      r.sum = modeCounts(m);
      for (let up = parent; up != null; up = rows.get(up).parent) {
        const u = rows.get(up);
        for (const k of Object.keys(r.sum)) u.sum[k] += r.sum[k];
      }
    };
    for (const fn of p.functions || []) {
      const f = add("fn", fn.id, { ...fn, position_id: p.id }, top);
      for (const ff of fn.failures || []) {
        const x = add("fail", ff.id, { ...ff, position_id: p.id, function_id: fn.id }, f.key);
        for (const m of ff.modes || []) modeRow(m, x.key, ff.id);
      }
    }
    if ((p.unassigned || []).length) {
      const u = add("unassigned", `U:${p.id}`, { id: `U:${p.id}`, text: "Not under a functional failure", position_id: p.id }, top);
      for (const m of p.unassigned) modeRow(m, u.key, null);
    }
  }
  return { rows, roots, counts, positions: withPositions };
}

// The functional failures on a position, for a failure mode's "Under" choice.
export function failuresOn(display, positionId) {
  const out = [];
  for (const r of display.rows.values()) {
    if (r.type === "fail" && r.ref.position_id === positionId) {
      const fn = display.rows.get(r.parent);
      out.push({ id: r.key, text: r.ref.text, function: fn?.ref.text || "" });
    }
  }
  return out;
}

// A decision as the server takes it back: the fields a decision is made of,
// without the evidence check the server added.
export function decisionBody(d, patch = {}) {
  if (!d) return null;
  const out = {};
  for (const k of ["outcome", "rtf_basis", "task", "interval", "interval_unit", "notes", "evidence"]) {
    if (d[k] !== undefined && d[k] !== null && d[k] !== "") out[k] = d[k];
  }
  for (const [k, v] of Object.entries(patch)) {
    if (v === null || v === "") delete out[k];
    else out[k] = v;
  }
  if (out.interval != null && !out.interval_unit) out.interval_unit = "hours";
  if (out.interval == null) delete out.interval_unit;
  return out;
}

// A row's text (the node's description).
export const nameOf = (r) => r.ref.text || "";

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// "580 hours", "1 month": units are stored as typed (usually plural), so
// singularise them for an interval of exactly 1.
export function intervalText(d) {
  if (!d || d.interval == null || d.interval === "") return "";
  const u = d.interval_unit || "";
  const unit = Number(d.interval) === 1 && /[a-z]s$/i.test(u) ? u.slice(0, -1) : u;
  return `${Number(d.interval).toLocaleString("en-AU", { maximumSignificantDigits: 6 })} ${unit}`.trim();
}

export function decisionText(d) {
  if (!d) return "";
  const label = OUTCOME_LABEL[d.outcome] || d.outcome || "";
  return d.outcome === "rtf" && RTF_LABEL[d.rtf_basis] ? `${label} (${RTF_LABEL[d.rtf_basis]})` : label;
}

// What's inside a row, in words: "5 failure modes · 2 to decide · 3 with a task".
export function insideWords(r) {
  const s = r.sum;
  if (r.type === "mode") return "";
  if (!s.modes) return r.kids.length ? plural(r.kids.length, "functional failure") + ", no failure modes yet" : "Nothing inside yet";
  return [
    plural(s.modes, "failure mode"),
    s.undecided ? `${s.undecided.toLocaleString("en-AU")} to decide` : "all decided",
    s.tasks ? `${s.tasks.toLocaleString("en-AU")} with a task` : null,
  ].filter(Boolean).join(" · ");
}

// The evidence checks inside a row: [{kind, n, label}] (kind: supported,
// contradicted, unsure, stale), for the parent rows' Evidence check cell.
export function checkCounts(r) {
  const s = r.sum;
  return [
    { kind: "contradicted", n: s.contradicted, label: "contradicted" },
    { kind: "unsure", n: s.unsure, label: "to check" },
    { kind: "stale", n: s.stale, label: "stale" },
    { kind: "supported", n: s.supported, label: "supported" },
  ].filter((c) => c.n > 0);
}

// ---- columns -----------------------------------------------------------------

// Every column but the index (the description, always shown first). `on`: in
// the default set (fits 1440 px wide with the menu open). `text(r)`: the cell
// as plain text (the phone's second line, the CSV of what's shown). `sort(r)`:
// the value it sorts by, null for blank (blanks go last); a row with things
// inside it sorts by what's inside. `edit`: the field edited in the cell
// ("text", "choice" or "number"), and `can(r)` the rows that allow it.
const CONS_RANK = { safety: 0, environmental: 1, hidden: 2, operational: 3, non_operational: 4 };
const OUT_RANK = { on_condition: 0, fixed_interval: 1, failure_finding: 2, rtf: 3, redesign: 4, accept: 5 };
const STATUS_RANK = { contradicted: 0, stale: 1, unevidenced: 2, inconclusive: 3, supported: 4 };
const isMode = (r) => r.type === "mode";
const d = (r) => r.ref.decision || null;

export const COLUMNS = [
  {
    id: "standard", label: "Performance standard", width: 200, on: false,
    title: "What the function must achieve, e.g. within 30 m from 60 km/h",
    text: (r) => (r.type === "fn" ? r.ref.standard || "" : ""),
    sort: (r) => (r.type === "fn" ? r.ref.standard || null : null),
    edit: "text", can: (r) => r.type === "fn", field: "standard",
  },
  {
    id: "effects", label: "Failure effects", width: 180, on: true,
    title: "What happens when the failure mode occurs",
    text: (r) => (isMode(r) ? r.ref.effects || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.effects || null : null),
    edit: "text", can: isMode, field: "effects",
  },
  {
    id: "consequence", label: "Consequence", width: 114, on: true,
    title: "Safety, environmental, operational, non-operational or hidden",
    text: (r) => (isMode(r) ? CONSEQUENCE_LABEL[r.ref.consequence] || "" : consequenceSum(r)),
    sort: (r) => (isMode(r) ? CONS_RANK[r.ref.consequence] ?? null : r.sum.safety ? 0 : r.sum.hidden ? 2 : null),
    edit: "choice", can: isMode, field: "consequence",
  },
  {
    id: "evident", label: "Evident or hidden", width: 120, on: false,
    title: "Hidden: the failure can't be seen in normal operation",
    text: (r) => (isMode(r) ? (r.ref.consequence === "hidden" ? "Hidden" : r.ref.consequence ? "Evident" : "") : r.sum.hidden ? `${r.sum.hidden} hidden` : ""),
    sort: (r) => (isMode(r) ? (r.ref.consequence === "hidden" ? 0 : r.ref.consequence ? 1 : null) : r.sum.hidden ? 0 : null),
  },
  {
    id: "decision", label: "Decision", width: 150, on: true,
    title: "The maintenance decision for the failure mode",
    text: (r) => (isMode(r) ? decisionText(d(r)) || "To decide" : r.sum.modes ? (r.sum.undecided ? `${r.sum.undecided} to decide` : "All decided") : ""),
    sort: (r) => (isMode(r) ? (d(r) ? OUT_RANK[d(r).outcome] ?? 9 : -1) : -r.sum.undecided),
  },
  {
    id: "task", label: "Task", width: 190, on: true,
    title: "What is done, and for run-to-failure the action on failure",
    text: (r) => (isMode(r) ? d(r)?.task || "" : r.sum.tasks ? plural(r.sum.tasks, "task") : ""),
    sort: (r) => (isMode(r) ? d(r)?.task || null : r.sum.tasks || null),
    edit: "text", can: (r) => isMode(r) && TASK_OUTCOMES.has(d(r)?.outcome), field: "task", onDecision: true,
  },
  {
    id: "interval", label: "Interval", width: 92, on: true, align: "num",
    title: "How often the task is done, in its unit",
    text: (r) => (isMode(r) ? intervalText(d(r)) : ""),
    sort: (r) => (isMode(r) && d(r)?.interval ? Number(d(r).interval) : null),
    edit: "number", can: (r) => isMode(r) && INTERVAL_OUTCOMES.has(d(r)?.outcome), field: "interval", onDecision: true,
  },
  {
    id: "check", label: "Evidence check", width: 126, on: true,
    title: "Whether the linked analysis backs the decision, checked each time the study opens",
    text: (r) => (isMode(r) ? STATUS_LABEL[d(r)?.status] || "" : checkCounts(r).map((c) => `${c.n} ${c.label}`).join(", ")),
    sort: (r) => (isMode(r) ? STATUS_RANK[d(r)?.status] ?? null
      : r.sum.contradicted ? 0 : r.sum.stale ? 1 : r.sum.unsure ? 2 : r.sum.supported ? 4 : null),
  },
  {
    id: "evidence", label: "Evidence", width: 200, on: false,
    title: "The saved model or analysis linked to the decision",
    text: (r) => (isMode(r) ? d(r)?.artifact_name || "" : ""),
    sort: (r) => (isMode(r) ? d(r)?.artifact_name || null : null),
  },
  {
    id: "detail", label: "What the evidence shows", width: 260, on: false,
    text: (r) => (isMode(r) ? d(r)?.summary || d(r)?.reason || "" : ""),
    sort: (r) => (isMode(r) ? d(r)?.summary || d(r)?.reason || null : null),
  },
  {
    id: "dnotes", label: "Decision notes", width: 220, on: false,
    text: (r) => (isMode(r) ? d(r)?.notes || "" : ""),
    sort: (r) => (isMode(r) ? d(r)?.notes || null : null),
    edit: "text", can: (r) => isMode(r) && !!d(r), field: "notes", onDecision: true,
  },
  {
    id: "notes", label: "Mode notes", width: 200, on: false,
    title: "Notes on the failure mode itself (for example scores kept from an FMEA)",
    text: (r) => (isMode(r) ? r.ref.notes || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.notes || null : null),
    edit: "text", can: isMode, field: "notes",
  },
  {
    id: "modes", label: "Failure modes", width: 104, on: false, align: "num", sum: true,
    title: "How many failure modes are inside",
    text: (r) => (isMode(r) ? "" : String(r.sum.modes)),
    sort: (r) => (isMode(r) ? null : r.sum.modes),
  },
  {
    id: "undecided", label: "To decide", width: 90, on: false, align: "num", sum: true,
    title: "Failure modes inside with no decision yet",
    text: (r) => (isMode(r) ? "" : r.sum.undecided ? String(r.sum.undecided) : ""),
    sort: (r) => (isMode(r) ? null : r.sum.undecided || null),
  },
];
export const COLUMN = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
export const NAME_COLUMN = { id: "name", label: "Function, failure or mode", width: 270, min: 180 };
export const DEFAULT_COLUMNS = COLUMNS.filter((c) => c.on).map((c) => c.id);

// A parent row's consequences: the most serious kind inside it (all of them
// in consequenceWords, for its title).
function consequenceSum(r) {
  if (r.sum.safety) return `${r.sum.safety.toLocaleString("en-AU")} safety or env.`;
  return r.sum.hidden ? `${r.sum.hidden.toLocaleString("en-AU")} hidden` : "";
}
export function consequenceWords(r) {
  return [r.sum.safety ? `${plural(r.sum.safety, "failure mode")} with a safety or environmental consequence` : null,
    r.sum.hidden ? `${plural(r.sum.hidden, "hidden failure")}` : null].filter(Boolean).join("; ");
}

// Siblings in a column's order (dir 1 or -1), blanks last whichever way; a
// tie keeps the worksheet's own order. For flatten's `order`.
export function siblingOrder(display, sort) {
  const col = sort && COLUMN[sort.col];
  if (!col && sort?.col !== "name") return null;
  const value = sort.col === "name" ? (r) => nameOf(r) || null : col.sort;
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  return (keys) => keys
    .map((k, i) => ({ k, i, v: value(display.rows.get(k)) }))
    .sort((a, b) => {
      const an = a.v == null || a.v === "";
      const bn = b.v == null || b.v === "";
      if (an || bn) return an === bn ? a.i - b.i : an ? 1 : -1;
      const c = typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : collator.compare(String(a.v), String(b.v));
      return c ? c * sort.dir : a.i - b.i;
    })
    .map((x) => x.k);
}

// ---- filter ------------------------------------------------------------------

// The chips, each about the failure modes (and showing how many there are).
export const CHIPS = [
  { id: "undecided", label: "Needs a decision", test: (r) => isMode(r) && !d(r) },
  { id: "hidden", label: "Hidden failures", test: (r) => isMode(r) && r.ref.consequence === "hidden" },
  { id: "safety", label: "Safety or environment", test: (r) => isMode(r) && (r.ref.consequence === "safety" || r.ref.consequence === "environmental") },
  { id: "task", label: "Has a task", test: (r) => isMode(r) && hasTask(r.ref) },
  { id: "notask", label: "No task yet", test: (r) => isMode(r) && !hasTask(r.ref) },
  { id: "check", label: "Evidence to look at", title: "Contradicted, inconclusive, not linked yet, or a stale link",
    test: (r) => isMode(r) && ["contradicted", "inconclusive", "unevidenced", "stale"].includes(d(r)?.status) },
];

export function chipCounts(display) {
  const out = Object.fromEntries(CHIPS.map((c) => [c.id, 0]));
  for (const r of display.rows.values()) {
    if (!isMode(r)) continue;
    for (const c of CHIPS) if (c.test(r)) out[c.id] += 1;
  }
  return out;
}

// What the filter's text is searched by: the description, the standard, the
// effects, the task and the notes.
export function rowText(r) {
  const p = r.ref;
  return [p.text, p.standard, p.effects, p.notes, p.decision?.task, p.decision?.notes]
    .filter(Boolean).join(" ").toLowerCase();
}

// The rows matching the text and every chip that's on, with the path to each.
// null when nothing filters.
export function computeFilter(display, { query = "", chips = [] } = {}) {
  const q = query.trim().toLowerCase();
  const tests = CHIPS.filter((c) => chips.includes(c.id));
  if (!q && !tests.length) return null;
  return filterRows(display, (r) => (!q || rowText(r).includes(q)) && tests.every((c) => c.test(r)));
}

// ---- edits (each returns a new functions list) -------------------------------

const newId = () => (globalThis.crypto?.randomUUID
  ? globalThis.crypto.randomUUID().replaceAll("-", "")
  : Math.random().toString(36).slice(2) + Date.now().toString(36));

// Replace the node at `at` with update(node).
function mapAt(functions, at, update) {
  const [fi, xi, mi] = at;
  return functions.map((fn, i) => {
    if (i !== fi) return fn;
    if (xi == null) return update(fn);
    return {
      ...fn,
      failures: (fn.failures || []).map((fail, j) => {
        if (j !== xi) return fail;
        if (mi == null) return update(fail);
        return { ...fail, modes: (fail.modes || []).map((m, k) => (k === mi ? update(m) : m)) };
      }),
    };
  });
}

export const patchNode = (functions, at, patch) => mapAt(functions, at, (n) => ({ ...n, ...patch }));

// Change a decision's task, interval or notes (a failure mode with one).
export function patchDecision(functions, at, patch) {
  return mapAt(functions, at, (m) => (m.decision ? { ...m, decision: { ...m.decision, ...patch } } : m));
}

// A new node inside the row at `at` (null: a new function at the end).
// Returns {functions, id}.
export function addNode(functions, at) {
  const id = newId();
  if (!at) return { functions: [...functions, { id, text: "", failures: [] }], id };
  if (at.length === 1) {
    return { functions: mapAt(functions, at, (fn) => ({ ...fn, failures: [...(fn.failures || []), { id, text: "", modes: [] }] })), id };
  }
  return {
    functions: mapAt(functions, at, (fail) => ({
      ...fail, modes: [...(fail.modes || []), { id, text: "", consequence: null, decision: null }],
    })),
    id,
  };
}

export function removeNode(functions, at) {
  const [fi, xi, mi] = at;
  if (xi == null) return functions.filter((_, i) => i !== fi);
  return functions.map((fn, i) => {
    if (i !== fi) return fn;
    if (mi == null) return { ...fn, failures: fn.failures.filter((_, j) => j !== xi) };
    return {
      ...fn,
      failures: fn.failures.map((fail, j) => (j !== xi ? fail : { ...fail, modes: fail.modes.filter((_, k) => k !== mi) })),
    };
  });
}

// A cell's new value, checked as the server will check it on Save: a
// description can't be empty; an interval is a positive number (blank clears
// it). {value} or {error}.
export function checkValue(col, row, raw) {
  if (col === "name") {
    const text = String(raw ?? "").trim();
    return text ? { value: text } : { error: `Every ${LEVEL_OF[row.type].label.toLowerCase()} needs a description.` };
  }
  const c = COLUMN[col];
  if (c?.edit === "number") {
    const s = String(raw ?? "").trim();
    if (!s) return { value: null };
    const n = Number(s);
    if (!Number.isFinite(n)) return { error: "The task interval must be a number." };
    if (n <= 0) return { error: "The task interval must be positive." };
    return { value: n };
  }
  if (c?.edit === "choice") return { value: CONSEQUENCE_LABEL[raw] ? raw : null };
  return { value: String(raw ?? "").trim() };
}

// The functions list with one cell changed (the value from checkValue).
export function setCell(functions, row, col, value) {
  if (col === "name") return patchNode(functions, row.at, { text: value });
  const c = COLUMN[col];
  if (c.onDecision) {
    const patch = { [c.field]: value };
    if (c.field === "interval" && value != null && !row.ref.decision?.interval_unit) patch.interval_unit = "hours";
    return patchDecision(functions, row.at, patch);
  }
  return patchNode(functions, row.at, { [c.field]: value });
}

// ---- CSV ---------------------------------------------------------------------

// The worksheet as rows for a spreadsheet: a header, then one row per failure
// mode with its function and functional failure.
export function worksheetCsvRows(functions) {
  const rows = [[
    "function", "functional_failure", "failure_mode", "effects", "consequence",
    "outcome", "rtf_basis", "task", "interval", "interval_unit",
    "evidence_type", "evidence_name", "evidence_status", "evidence_detail", "notes",
  ]];
  for (const fn of functions || []) {
    for (const fail of fn.failures || []) {
      for (const mode of fail.modes || []) {
        const dd = mode.decision || {};
        rows.push([
          fn.text, fail.text, mode.text, mode.effects || "", mode.consequence || "",
          dd.outcome || "", dd.rtf_basis || "", dd.task || "", dd.interval ?? "", dd.interval_unit || "",
          dd.evidence?.type || "", dd.artifact_name || "", dd.status || "", dd.summary || dd.reason || "",
          mode.notes || "",
        ]);
      }
    }
  }
  return rows;
}

// ---- remembered on this device -----------------------------------------------

// The columns shown and their widths, the row density, the view (worksheet or
// tree) and, per study (the last 30), the rows open. Storage can throw
// (private mode, blocked site data), so every read and write is guarded and
// the worksheet works without it.
const KEY = "reliafy.rcmWorksheet";
const MAX_STUDIES = 30;

export function loadPrefs(storage = globalThis.localStorage) {
  const fallback = { cols: DEFAULT_COLUMNS, widths: {}, density: "comfortable", open: {} };
  try {
    const raw = storage?.getItem(KEY);
    const v = raw ? JSON.parse(raw) : {};
    const cols = Array.isArray(v.cols) ? v.cols.filter((c) => COLUMN[c]) : DEFAULT_COLUMNS;
    const widths = {};
    for (const [k, w] of Object.entries(v.widths || {})) if ((COLUMN[k] || k === "name") && Number.isFinite(w)) widths[k] = w;
    return {
      cols,
      widths,
      density: v.density === "compact" ? "compact" : "comfortable",
      open: v.open && typeof v.open === "object" ? v.open : {},
    };
  } catch {
    return fallback;
  }
}

export function savePrefs(prefs, storage = globalThis.localStorage) {
  try {
    const open = Object.entries(prefs.open || {}).slice(-MAX_STUDIES);
    storage?.setItem(KEY, JSON.stringify({ ...prefs, open: Object.fromEntries(open) }));
  } catch {
    // Not remembered on this device; the worksheet still works.
  }
}

// The rows to open for a study seen before (those still in it), else null.
export function rememberedOpen(prefs, studyId, display) {
  const keys = prefs.open?.[studyId];
  if (!Array.isArray(keys)) return null;
  return new Set(keys.filter((k) => display.rows.has(k)));
}

// The prefs with a study's open rows set (most recent last).
export function withOpen(prefs, studyId, open) {
  const rest = Object.fromEntries(Object.entries(prefs.open || {}).filter(([k]) => k !== studyId));
  return { ...prefs, open: { ...rest, [studyId]: [...open] } };
}

// A width kept between a column's least and 640 px.
export const clampCol = (w, min = 60) => Math.min(640, Math.max(min, Math.round(w)));
