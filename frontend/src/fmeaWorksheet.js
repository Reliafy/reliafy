// The FME(C)A worksheet's columns, counts, chips and checks, as the Explorer's
// FME(C)A tab draws them on the asset tree (TreePane, explorerFmea.js): a
// position › its functions › their failure modes, with the worksheet's
// columns beside each mode (cause, the three effects, detection method, S, O,
// D, RPN, AP, the recommended action and its owner, due date and status; and
// the criticality figures). The same failure modes as the RCM tab: a column
// is a field on the mode (its id is the field's name, as the API takes it),
// so an edit here shows there at once.
//
// Pure functions (no React), tested in fmeaWorksheet.test.js: the columns
// and what each cell says, a mode's counts and a parent row's roll-up, the
// chips, the check on a cell's value (as the server checks it), the phone's
// second line, and what's remembered on this device (its own key, apart from
// the RCM's).

import {
  AP_LABEL, CLASS_LABEL, SOURCE_LABEL, STATUS_LABEL, cmOf, fmt3, rpnOf, score,
} from "./fmea.js";
import { COLUMN as RCM_COLUMN, blank as rcmBlank, checkValue as rcmCheckValue, modeCounts } from "./rcmWorksheet.js";

const isMode = (r) => r.type === "mode";
const n = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;

// ---- counts -----------------------------------------------------------------------
// A failure mode's own FMEA counts (each 0 or 1, but max_rpn and cr), added
// into its function's and its position's (the RCM's own counts, modeCounts,
// come along, so the RCM columns still read on this tab).
export const fmeaBlank = () => ({ scored: 0, high: 0, medium: 0, low: 0, max_rpn: null, cr: 0, with_cm: 0, action_open: 0 });

export const hasActionOpen = (m) => !!String(m?.action || "").trim() && m?.action_status !== "done";

export function fmeaCounts(m) {
  const rpn = m.rpn ?? rpnOf(m.severity, m.occurrence, m.detection);
  const cm = m.cm ?? cmOf(m);
  return {
    scored: rpn != null ? 1 : 0,
    high: m.ap === "H" ? 1 : 0,
    medium: m.ap === "M" ? 1 : 0,
    low: m.ap === "L" ? 1 : 0,
    max_rpn: rpn,
    cr: cm ?? 0,
    with_cm: cm != null ? 1 : 0,
    action_open: hasActionOpen(m) ? 1 : 0,
  };
}

// A mode's counts for the tree: the RCM's and the FMEA's together.
export const modeSums = (m) => ({ ...modeCounts(m), ...fmeaCounts(m) });
export const blankSums = () => ({ ...rcmBlank(), ...fmeaBlank() });

// `into` gains `add`: every count summed, but max_rpn is the greatest.
export function addSums(into, add) {
  for (const k of Object.keys(add)) {
    if (k === "max_rpn") into.max_rpn = add.max_rpn == null ? into.max_rpn ?? null : Math.max(into.max_rpn ?? -Infinity, add.max_rpn);
    else into[k] = (into[k] || 0) + (add[k] || 0);
  }
  return into;
}

// "2 high · 1 medium" (a parent's AP cell; "3 low" alone when that's all).
export function apSummary(s) {
  const bits = [s.high ? `${s.high} high` : null, s.medium ? `${s.medium} medium` : null].filter(Boolean);
  if (bits.length) return bits.join(" · ");
  return s.low ? `${s.low} low` : "";
}
export function apWords(s) {
  const bits = [s.high ? n(s.high, "high-priority failure mode") : null, s.medium ? n(s.medium, "medium-priority failure mode") : null,
    s.low ? n(s.low, "low-priority failure mode") : null];
  const unscored = (s.modes || 0) - (s.scored || 0);
  if (unscored > 0) bits.push(`${unscored} not scored yet`);
  return bits.filter(Boolean).join("; ");
}
// "3 of 5 scored" (a parent's first text cell).
export const scoredWords = (s) => (s.modes ? `${s.scored} of ${s.modes} scored` : "");

// ---- columns ----------------------------------------------------------------------
// Every column but the index (the name, always first). The ids of the mode's
// fields are the API's keys (PATCH /failure-modes/{id}); `rcm: true` reuses
// an RCM column as it is. `edit`: "text", "number" (with `range`: {min, max,
// integer}), "choice" (with `options`) or "date"; `can(r)`: the rows that
// allow it (failure modes). `text(r)`: the cell as plain words; `sort(r)`:
// what it sorts by (null blank).
const text = (field) => (r) => (isMode(r) ? r.ref[field] || "" : "");
const sortText = (field) => (r) => (isMode(r) ? r.ref[field] || null : null);
const textCol = (id, label, width, min, title, on = true) => ({
  id, label, width, min, on, title, text: text(id), sort: sortText(id), edit: "text", can: isMode, field: id,
});
const scoreOf = (field) => (r) => (isMode(r) ? score(r.ref[field]) : null);
const scoreCol = (id, label, title) => ({
  id, label, width: 46, min: 40, on: true, align: "num", title,
  text: (r) => (isMode(r) ? (score(r.ref[id]) != null ? String(score(r.ref[id])) : "") : ""),
  sort: scoreOf(id), edit: "number", can: isMode, field: id, range: { min: 1, max: 10, integer: true },
});
const numCol = (id, label, width, min, title, range, { unit = null } = {}) => ({
  id, label, width, min, on: false, align: "num", title,
  text: (r) => (isMode(r) ? fmt3(r.ref[id]) : ""),
  sort: (r) => (isMode(r) && r.ref[id] != null && r.ref[id] !== "" ? Number(r.ref[id]) : null),
  edit: "number", can: isMode, field: id, range, unit,
});
const choiceCol = (id, label, width, min, title, labels) => ({
  id, label, width, min, on: false, title, labels,
  text: (r) => (isMode(r) ? labels[r.ref[id]] || "" : ""),
  sort: (r) => (isMode(r) ? Object.keys(labels).indexOf(r.ref[id]) + 1 || null : null),
  edit: "choice", can: isMode, field: id, options: Object.entries(labels).map(([value, l]) => ({ value, label: l })),
});
const rpnOfRow = (r) => (isMode(r) ? r.ref.rpn ?? rpnOf(r.ref.severity, r.ref.occurrence, r.ref.detection) : r.sum.max_rpn ?? null);
const AP_RANK = { H: 3, M: 2, L: 1 };

export const COLUMNS = [
  {
    id: "failure", label: "Functional failure", width: 130, min: 84, on: true,
    title: "From the RCM tab: the functional failure the mode sits under (none for a mode written here)",
    text: (r) => (isMode(r) ? r.ref.failure_text || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.failure_text || null : null),
  },
  {
    ...textCol("cause", "Cause", 170, 100, "What brings the failure mode about"),
    // A parent row's first text cell says how many of its modes are scored.
    text: (r) => (isMode(r) ? r.ref.cause || "" : scoredWords(r.sum)),
  },
  textCol("effect_local", "Local effect", 150, 90, "What happens at this position"),
  textCol("effect_next", "Next higher effect", 150, 90, "What happens at the assembly above it"),
  textCol("effects", "End effect", 150, 90, "What happens to the whole system or mission (the RCM tab's Failure effects: the same field)"),
  textCol("detection_method", "Detection method", 150, 90, "How the failure or its cause would be noticed first: current controls"),
  scoreCol("severity", "S", "Severity, 1 (no effect) to 10 (hazardous without warning)"),
  scoreCol("occurrence", "O", "Occurrence, 1 (almost never) to 10 (almost certain)"),
  scoreCol("detection", "D", "Detection, 1 (almost certain to detect) to 10 (cannot detect)"),
  {
    id: "rpn", label: "RPN", width: 58, min: 50, on: true, align: "num",
    title: "Risk priority number: S × O × D (a parent row: the highest inside it)",
    text: (r) => { const v = rpnOfRow(r); return v == null ? "" : String(v); },
    sort: rpnOfRow,
  },
  {
    id: "ap", label: "AP", width: 112, min: 64, on: true,
    title: "Action priority from S, O and D: High (act), Medium (act or say why not), Low (a parent row: how many of each)",
    text: (r) => (isMode(r) ? AP_LABEL[r.ref.ap] || "" : apSummary(r.sum)),
    sort: (r) => (isMode(r) ? AP_RANK[r.ref.ap] ?? null : r.sum.high ? 3 : r.sum.medium ? 2 : r.sum.low ? 1 : null),
  },
  textCol("action", "Recommended action", 170, 100, "What should be done about it"),
  textCol("action_owner", "Owner", 100, 70, "Who the action is with"),
  {
    id: "action_due", label: "Due", width: 104, min: 96, on: true, title: "When the action is due",
    text: (r) => (isMode(r) ? r.ref.action_due || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.action_due || null : null),
    edit: "date", can: isMode, field: "action_due",
  },
  { ...choiceCol("action_status", "Status", 100, 84, "Open, In progress or Done", STATUS_LABEL), on: true,
    text: (r) => (isMode(r) ? STATUS_LABEL[r.ref.action_status] || "" : r.sum.action_open ? `${r.sum.action_open} open` : "") },
  // Off by default: the RCM's own columns, then the criticality figures.
  { ...RCM_COLUMN.consequence, on: false, rcm: true },
  { ...RCM_COLUMN.decision, on: false, rcm: true },
  { ...RCM_COLUMN.task, on: false, rcm: true },
  numCol("failure_rate", "Failure rate", 100, 80, "λ: failures per unit of time (the time unit column)", { min: 0 }),
  textCol("time_unit", "Time unit", 84, 70, "The unit the failure rate and operating time are in (hours unless set)", false),
  choiceCol("rate_source", "Rate source", 110, 90, "Where the failure rate came from", SOURCE_LABEL),
  numCol("mode_ratio", "Mode ratio (α)", 100, 84, "The share of the item's failures that are this mode, 0 to 1", { min: 0, max: 1 }),
  numCol("loss_probability", "Loss probability (β)", 120, 96, "The chance the mode's effect is the loss named by the severity class, 0 to 1", { min: 0, max: 1 }),
  numCol("operating_time", "Operating time (t)", 120, 96, "The time the criticality is figured over, in the time unit", { min: 0, exclusiveMin: true }),
  {
    id: "cm", label: "Mode criticality (Cm)", width: 130, min: 100, on: false, align: "num",
    title: "β × α × λ × t (a parent row: Cr, the sum over the modes inside it)",
    text: (r) => (isMode(r) ? fmt3(r.ref.cm ?? cmOf(r.ref)) : r.sum.with_cm ? fmt3(r.sum.cr) : ""),
    sort: (r) => (isMode(r) ? r.ref.cm ?? cmOf(r.ref) : r.sum.with_cm ? r.sum.cr : null),
  },
  choiceCol("severity_class", "Severity class", 110, 90, "I Catastrophic, II Critical, III Marginal, IV Minor", CLASS_LABEL),
];
export const COLUMN = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
export const DEFAULT_COLUMNS = COLUMNS.filter((c) => c.on).map((c) => c.id);
export const NAME_COLUMN = { id: "name", label: "Function or failure mode", width: 270, min: 180 };
export const TREE_HEAD = "Function or failure mode";
// The fields of a failure mode this tab edits (the API's keys): a column id
// that is one of these is written as {key: value}.
export const FIELDS = new Set(["severity", "occurrence", "detection", "cause", "effect_local", "effect_next", "effects", "detection_method",
  "action", "action_owner", "action_due", "action_status", "failure_rate", "time_unit", "rate_source", "mode_ratio", "loss_probability",
  "operating_time", "severity_class"]);

// The usual columns follow the window's width, so the scores and the action
// priority stay in view beside the tree without scrolling sideways: a wide
// window (1700 px and up) shows the whole preset; a laptop (under 1400 px)
// keeps the cause, the end effect, S, O, D, RPN, AP and the action; between
// the two, the local and next higher effects and the owner wait in the
// Columns menu. A set chosen there is kept whatever the width.
export const NARROW_TABLE = 1400;
export const WIDE_TABLE = 1700;
const MEDIUM_OFF = ["effect_local", "effect_next", "action_owner"];
const NARROW_OFF = [...MEDIUM_OFF, "detection_method", "action_due", "action_status"];
export function usualCols({ narrow = false, wide = false } = {}) {
  const off = wide ? [] : narrow ? NARROW_OFF : MEDIUM_OFF;
  return DEFAULT_COLUMNS.filter((id) => !off.includes(id));
}
const inOrder = (ids) => COLUMNS.map((c) => c.id).filter((id) => ids.includes(id));
// The columns shown: the ones chosen in the Columns menu, else the usual ones for the width.
export function tableCols(prefs, { narrow = false, wide = false } = {}) {
  return inOrder(prefs.colsChosen ? prefs.cols || DEFAULT_COLUMNS : usualCols({ narrow, wide }));
}
export function withTableCols(prefs, next, { reset = false } = {}) {
  if (reset) {
    const out = { ...prefs, cols: DEFAULT_COLUMNS };
    delete out.colsChosen;
    return out;
  }
  return { ...prefs, cols: inOrder(next), colsChosen: true };
}

// ---- sort ---------------------------------------------------------------------------
// A column header clicked: the failure modes under each function (and each
// group) in that column's order, blanks last whichever way; the functions and
// positions keep their place, so the tree stays as it is. For flatten's `order`.
export function siblingOrder(display, sort) {
  const col = sort && COLUMN[sort.col];
  if (!col?.sort) return null;
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  return (keys) => {
    const rows = keys.map((k) => display.rows.get(k));
    if (!rows.length || rows.some((r) => !r || r.type !== "mode")) return keys;
    return rows
      .map((r, i) => ({ k: r.key, i, v: col.sort({ ...r, sum: r.rsum || blankSums() }) }))
      .sort((a, b) => {
        const an = a.v == null || a.v === "";
        const bn = b.v == null || b.v === "";
        if (an || bn) return an === bn ? a.i - b.i : an ? 1 : -1;
        const c = typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : collator.compare(String(a.v), String(b.v));
        return c ? c * sort.dir : a.i - b.i;
      })
      .map((x) => x.k);
  };
}
// The next sort after a header click: highest first, then lowest first, then none.
export function nextSort(sort, col) {
  if (!sort || sort.col !== col) return { col, dir: -1 };
  return sort.dir === -1 ? { col, dir: 1 } : null;
}

// ---- chips ----------------------------------------------------------------------------
export const CHIPS = [
  { id: "ap-high", label: "High priority", rcmOnly: true, tab: "fmea", title: "Failure modes with a High action priority", test: (r) => isMode(r) && r.ref.ap === "H" },
  { id: "ap-medium", label: "Medium priority", rcmOnly: true, tab: "fmea", title: "Failure modes with a Medium action priority", test: (r) => isMode(r) && r.ref.ap === "M" },
  { id: "unscored", label: "Not scored", rcmOnly: true, tab: "fmea", title: "Failure modes missing one or more of S, O and D",
    test: (r) => isMode(r) && rpnOf(r.ref.severity, r.ref.occurrence, r.ref.detection) == null },
  { id: "action-open", label: "Has an action open", rcmOnly: true, tab: "fmea", title: "Failure modes with a recommended action not yet done",
    test: (r) => isMode(r) && hasActionOpen(r.ref) },
];
export const CHIP_IDS = CHIPS.map((c) => c.id);

// ---- the phone's second line --------------------------------------------------------
// A failure mode: "S 9 · O 4 · D 6 · RPN 216 · High · Open"; a function or
// position: "3 of 5 scored · 2 high · 1 medium".
export function phoneLine(r) {
  const s = r.sum || blankSums();
  if (!isMode(r)) return [scoredWords(s), apSummary(s)].filter(Boolean).join(" · ");
  const m = r.ref;
  const sc = ["severity", "occurrence", "detection"].filter((k) => score(m[k]) != null).map((k) => `${k[0].toUpperCase()} ${score(m[k])}`);
  const rpn = rpnOfRow(r);
  return [...sc, rpn != null ? `RPN ${rpn}` : sc.length ? "not fully scored" : "Not scored", AP_LABEL[m.ap], STATUS_LABEL[m.action_status]].filter(Boolean).join(" · ");
}

// ---- a cell's value -------------------------------------------------------------------
// A cell's new value, checked as the server will check it: {value} or {error}
// in the server's own words. Blank clears a field (null).
export const SCORE_ERROR = {
  severity: "Severity is a whole number from 1 (no effect) to 10 (hazardous without warning).",
  occurrence: "Occurrence is a whole number from 1 (almost never) to 10 (almost certain).",
  detection: "Detection is a whole number from 1 (almost certain to detect) to 10 (cannot detect).",
};
export function checkValue(col, row, raw) {
  if (col === "name") return rcmCheckValue("name", row, raw);
  const c = COLUMN[col];
  if (!c) return rcmCheckValue(col, row, raw);
  if (c.rcm) return rcmCheckValue(col, row, raw);
  const s = String(raw ?? "").trim();
  if (c.edit === "number") {
    if (!s) return { value: null };
    const v = Number(s);
    if (SCORE_ERROR[col]) return score(v) != null ? { value: score(v) } : { error: SCORE_ERROR[col] };
    if (!Number.isFinite(v)) return { error: `${c.label} must be a number.` };
    const { min, max, exclusiveMin } = c.range || {};
    if (min != null && (exclusiveMin ? v <= min : v < min)) {
      return { error: exclusiveMin ? `${c.label} must be more than ${min}.` : `${c.label} can't be less than ${min}.` };
    }
    if (max != null && v > max) return { error: `${c.label} is between ${min ?? 0} and ${max}.` };
    return { value: v };
  }
  if (c.edit === "choice") return s && c.labels[s] ? { value: s } : s ? { error: `${c.label} is one of: ${Object.values(c.labels).join(", ")}.` } : { value: null };
  if (c.edit === "date") {
    if (!s) return { value: null };
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    const ok = m && !Number.isNaN(Date.parse(s)) && new Date(s).toISOString().slice(0, 10) === s;
    return ok ? { value: s } : { error: "The due date is a date (YYYY-MM-DD)." };
  }
  return { value: s || null };
}

// ---- remembered on this device -----------------------------------------------------
// The columns shown and their widths, apart from the RCM tab's. Storage can
// throw (private mode, blocked site data), so every read and write is guarded.
const KEY = "reliafy.fmeaWorksheet";
export function loadPrefs(storage = globalThis.localStorage) {
  const fallback = { cols: DEFAULT_COLUMNS, widths: {} };
  try {
    const raw = storage?.getItem(KEY);
    const v = raw ? JSON.parse(raw) : {};
    const cols = Array.isArray(v.cols) ? v.cols.filter((c) => COLUMN[c]) : DEFAULT_COLUMNS;
    const widths = {};
    for (const [k, w] of Object.entries(v.widths || {})) if ((COLUMN[k] || k === "name") && Number.isFinite(w)) widths[k] = w;
    return { cols, widths, ...(v.colsChosen === true ? { colsChosen: true } : {}) };
  } catch {
    return fallback;
  }
}
export function savePrefs(prefs, storage = globalThis.localStorage) {
  try {
    storage?.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Not remembered on this device; the worksheet still works.
  }
}
