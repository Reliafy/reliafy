// Covariates that change over time (#60): the Data step's item / start / stop
// (or timeline) columns, what stops them fitting, and the calculator's
// covariate schedule. Pure, so `node --test src/` covers it.
import { isNumeric } from "./datasetGuess.js";
import { statusMeaning, statusValues } from "./lifeData.js";

export const LAYOUTS = [
  { value: "intervals", label: "Start and stop rows", title: "One row per stretch of an item's life at one set of covariate values" },
  { value: "timeline", label: "Timeline rows", title: "One row per change: its values hold until the item's next row; the last row is the failure or removal" },
];

const words = (name) => String(name || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-.]+/g, " ").toLowerCase();
const ID_RE = /\b(id|ids|item|unit|serial|sn|asset|tag|equipment|pump|motor|machine|vehicle|truck|engine|subject|system|no|number)\b/;
const START_RE = /\b(start|starts|from|begin|begins|entry|t0|tstart|xl)\b/;
const STOP_RE = /\b(stop|stops|end|ends|until|exit|t1|tstop|xr)\b|^to$/;

// Whether a column looks like an item id: named like one, or text that
// repeats (several rows per item).
function idColumn(columns, facts, nRows) {
  const repeats = (c) => facts[c]?.nUnique != null && nRows && facts[c].nUnique < nRows;
  return (
    columns.find((c) => ID_RE.test(words(c)) && repeats(c)) ||
    columns.find((c) => !isNumeric(facts[c]?.dtype) && repeats(c) && facts[c]?.values == null) ||
    ""
  );
}

// Interval rows the data says it holds: an item id that repeats and a
// numeric start and stop column. Null when it doesn't look like that.
export function guessTvc(columns, facts, nRows) {
  const numeric = (columns || []).filter((c) => isNumeric(facts[c]?.dtype));
  const start = numeric.find((c) => START_RE.test(words(c)));
  const stop = numeric.find((c) => c !== start && STOP_RE.test(words(c)));
  const i = idColumn(columns || [], facts, nRows);
  if (!start || !stop || !i) return null;
  return { layout: "intervals", i, xl: start, xr: stop };
}

// The mapping for a layout (null: covariates fixed): the fields the other
// layout used are cleared, counts and truncation too (they don't apply), and
// the item / time columns guessed where they are empty.
export function tvcMapping(mapping, layout, columns = [], facts = {}, nRows = 0) {
  const next = { ...mapping, n: "", tl: "", tr: "" };
  if (!layout) return { ...mapping, i: "", ...(mapping.i ? { xl: "", xr: "" } : {}) };
  const guess = guessTvc(columns, facts, nRows) || {};
  next.i = mapping.i || guess.i || idColumn(columns, facts, nRows);
  if (layout === "intervals") {
    next.xl = mapping.xl || guess.xl || "";
    next.xr = mapping.xr || guess.xr || "";
    next.x = "";
  } else {
    next.x = mapping.x || mapping.xl || "";
    next.xl = "";
    next.xr = "";
  }
  return next;
}

// What stops a time-varying mapping fitting, in plain words.
export function tvcProblems(mapping, facts, layout, nCovariates) {
  const out = [];
  const f = (col) => facts[col] || {};
  const timeCol = (col, what) => {
    if (!col) return;
    if (!isNumeric(f(col).dtype)) out.push(`“${col}” holds text, not times. Pick the column with ${what}.`);
    else if (f(col).blanks) out.push(`${f(col).blanks.toLocaleString()} ${f(col).blanks === 1 ? "row has" : "rows have"} no time in “${col}”. Fill them in or delete those rows.`);
  };
  if (!mapping.i) out.push("Pick the column that names each item.");
  if (layout === "intervals") {
    if (!mapping.xl || !mapping.xr) out.push("Pick the columns with the start and the stop of each row.");
    timeCol(mapping.xl, "each row's start");
    timeCol(mapping.xr, "each row's stop");
  } else {
    if (!mapping.x) out.push("Pick the column with the time each row's values take effect.");
    timeCol(mapping.x, "the times");
  }
  if (!mapping.c) {
    out.push("Pick the status column: it says which row ended in a failure.");
  } else if (f(mapping.c).values) {
    const unknown = statusValues(f(mapping.c).values).filter((v) => statusMeaning(v.label, mapping) === null);
    if (unknown.length) {
      out.push(`Say whether ${unknown.slice(0, 3).map((v) => `“${v.label}”`).join(", ")} ${unknown.length === 1 ? "means" : "mean"} failed or still running.`);
    }
  }
  if (!nCovariates) out.push("Tick the covariates that change over time below.");
  return out;
}

// "30 items, 96 rows, 25 failures" — the failures only for interval rows
// (a timeline's status counts on each item's last row only).
export function tvcSummaryParts(mapping, facts, nRows, layout) {
  const items = facts[mapping.i]?.nUnique;
  const parts = [];
  if (items != null) parts.push(`${items.toLocaleString()} ${items === 1 ? "item" : "items"}`);
  parts.push(`${nRows.toLocaleString()} ${nRows === 1 ? "row" : "rows"}`);
  const values = facts[mapping.c]?.values;
  if (layout === "intervals" && values) {
    const failed = statusValues(values)
      .filter((v) => statusMeaning(v.label, mapping) === 0)
      .reduce((n, v) => n + v.rows, 0);
    parts.push(`${failed.toLocaleString()} ${failed === 1 ? "failure" : "failures"}`);
  }
  return parts;
}

// The schedule route beside a fit's evaluate route: /api/evaluate/<fit> →
// /api/tvc/<fit>, /api/models/<id>/evaluate → /api/models/<id>/tvc.
export function tvcPath(functions) {
  const p = functions?.evaluate_path;
  if (!p) return null;
  if (/^\/api\/evaluate\//.test(p)) return p.replace(/^\/api\/evaluate\//, "/api/tvc/");
  if (/\/evaluate$/.test(p)) return p.replace(/\/evaluate$/, "/tvc");
  return null;
}

// A round time near ``v`` (two significant figures).
const round2 = (v) => (v > 0 ? Number(v.toPrecision(2)) : 0);

// The schedule the calculator opens on: each numeric covariate at its
// lowest value in the data, then at its highest from half-way along; a
// categorical one at its most common level.
export function initialSchedule(fields, xEnd) {
  const low = {}, high = {};
  for (const f of fields || []) {
    const isNum = f.type === "number";
    low[f.name] = isNum && f.min != null ? f.min : f.default;
    high[f.name] = isNum && f.max != null ? f.max : f.default;
  }
  const changes = (fields || []).some((f) => high[f.name] !== low[f.name]);
  const rows = [{ id: 0, t: 0, values: low }];
  if (changes && xEnd > 0) rows.push({ id: 1, t: round2(xEnd / 2), values: high });
  return rows;
}

// The schedule as the route takes it, or null with the reason it can't go:
// times numbers, 0 or more and different; numeric values numbers.
export function scheduleBody(rows, fields) {
  const seen = new Set();
  const out = [];
  for (const [k, r] of rows.entries()) {
    const t = k === 0 ? 0 : Number(r.t);
    if (r.t === "" || !Number.isFinite(t) || t < 0) return { error: `Row ${k + 1}: give a time of 0 or more.` };
    if (seen.has(t)) return { error: "Two rows start at the same time." };
    seen.add(t);
    const values = {};
    for (const f of fields || []) {
      const v = r.values?.[f.name];
      if (f.type === "number") {
        if (v === "" || v == null || !Number.isFinite(Number(v))) return { error: `Row ${k + 1}: ${f.name} must be a number.` };
        values[f.name] = Number(v);
      } else {
        values[f.name] = v;
      }
    }
    out.push({ t, values });
  }
  return { schedule: out };
}

// The time axis must reach past the last change.
export function scheduleXMax(rows, xEnd) {
  const last = Math.max(0, ...rows.map((r) => Number(r.t)).filter(Number.isFinite));
  return last > 0.8 * xEnd ? round2(last * 1.25) : null;
}
