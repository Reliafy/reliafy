// A dataset's modelling reading (#dataset-reading): which column is x, c, n,
// xl/xr, tl, tr, i, m, e (failure mode) and which are the covariates Z, kept
// with the dataset from upload so building a model never asks which column is
// which. The server keeps and checks it (backend/services/dataset_reading.py,
// the same format and the same first guess: readingGuessCases.json is checked
// by both test suites). Pure, so `node --test src/` covers it.
//
//   reading = {
//     x, xl, xr, c, n, tl, tr, i, m, e, s, u, // column names, "" for none
//                                           // (s: the state during the row, multi-state; kept, not yet fitted)
//     c_invert, c_map,                      // what the status values mean
//     all_failed,                           // no status column, on purpose: every row failed
//     unit, m_unit,                         // x's unit (any unit), m's
//     z: [col], z_units: { col: unit },     // the covariates, with optional units
//     not_used: [col],                      // columns read as nothing
//   }
import {
  EMPTY_MAPPING, dataStepIssues, guessMapping, savedMapping, startingMapping,
} from "./lifeData.js";
import { isNumeric } from "./datasetGuess.js";
import { guessTvc, tvcUnit } from "./tvcData.js";

export const ROLES = ["x", "xl", "xr", "c", "n", "tl", "tr", "i", "m", "e", "s", "u"];
// The selectors the upload shows, in order (x carries its range xl to xr).
export const READING_ROWS = ["x", "c", "n", "tl", "tr", "i", "m", "e", "s"];
const LABEL = { e: "failure mode" };

export const emptyReading = () => ({
  ...Object.fromEntries(ROLES.map((r) => [r, ""])),
  c_invert: false, c_map: null, all_failed: false, unit: "", m_unit: "", z: [], z_units: {}, not_used: [],
});

const words = (name) => String(name || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-./()[\]#:]+/g, " ").trim();
const ITEM_NAMES = /\b(tag|serial|sn|asset|equipment|unit|item|pump|motor|machine|vehicle|truck|engine|compressor|component|system|subject|specimen|sample|pad|position)\b/i;
const BARE_ID = /\b(id|ids|no|number)\b/i;
// A class, site or make is a covariate, never the item, however it repeats.
const CATEGORY = /\b(class|classes|family|families|type|types|category|group|site|location|area|make|model|supplier|vendor|manufacturer|kind|service|duty)\b/i;
const VALUE_NAMES = /\b(value|reading|readings|measure|measured|measurement|marker|vib|vibration|wear|thickness|depth|crack|debris|level|degradation|y)\b/i;
const FREE_TEXT_NAMES = /\b(notes?|remarks?|comments?|description|desc|details?|narrative|text)\b/i;
const DATE_NAMES = /\b(date|dated|dates|timestamp|datetime|when|commissioned|installed on)\b/i;
// The end of each row's observation: tr ("Observed until", "Records end", "Trial end").
const END_NAMES = /^(tr|t end)$|\b(observed to|observed until|observation end|end of (record|records|observation|test|trial|history|data)|records? end|record end|records? to|trial end|test end|window end|last seen|censor(ed)? (time|at)|cutoff|cut off|horizon)\b/i;
const MODE_NAMES = /\b(mode|modes|cause|causes)\b/i;
const STATUS_NAMES = /\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event|events|suspend|suspended|suspension|running|survived|alive|dead)\b/i;
const CODES = new Set(["0", "1", "-1", "2"]);
const TIME_UNIT_VALUES = /^(min|mins|minutes?|h|hr|hrs|hours?|d|days?|wk|wks|w|weeks?|mo|mth|mths|months?|y|yr|yrs|years?)\.?$/i;
const DATE_VALUE = /^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}.*)?$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$/;

// The columns a reading gives a role (never also covariates).
export const usedColumns = (r) => new Set(ROLES.map((k) => r?.[k]).filter((v) => typeof v === "string" && v));

// Why a column left over isn't a covariate by default, or null: it is one.
// "one value", "a date", "an id" or "free text": one tap includes it anyway.
export function notUsedReason(name, fact = {}, nRows = 0) {
  const w = words(name);
  const nu = fact.nUnique ?? null;
  if (nu !== null && nu <= 1) return "one value";
  const dtype = String(fact.dtype || "");
  const text = !isNumeric(dtype);
  if (/date|time/.test(dtype) || (DATE_NAMES.test(w) && text)
      || (text && fact.sample != null && DATE_VALUE.test(String(fact.sample).trim()))) return "a date";
  if (((ITEM_NAMES.test(w) || BARE_ID.test(w)) && !CATEGORY.test(w)) || (text && nu !== null && nRows > 1 && nu >= nRows)) {
    return "an id";
  }
  if (text && (FREE_TEXT_NAMES.test(w) || (nu !== null && nRows >= 6 && nu * 2 > nRows))) return "free text";
  const vals = fact.values ? Object.keys(fact.values).filter((v) => String(v).trim() !== "") : [];
  if (STATUS_NAMES.test(w) && !MODE_NAMES.test(w) && vals.length && vals.every((v) => CODES.has(String(v)))) return "a status";
  if (MODE_NAMES.test(w) && text) return "a failure mode";
  if (text && vals.length && vals.every((v) => TIME_UNIT_VALUES.test(String(v).trim()))) return "units";
  return null;
}

// Z (every column not used as something else) and not used (the guarded ones).
export function defaultZ(columns, facts, used, nRows) {
  const z = [], off = [];
  for (const c of columns || []) {
    if (used.has(c)) continue;
    (notUsedReason(c, facts[c], nRows) ? off : z).push(c);
  }
  return { z, not_used: off };
}

// The item each row belongs to: a column named like one (a tag, serial,
// asset; a bare "ID" last), preferring one whose values repeat.
function itemColumn(columns, facts, nRows, used) {
  const pool = columns.filter((c) => !used.has(c) && !CATEGORY.test(words(c))
    && (!isNumeric(facts[c]?.dtype) || facts[c]?.whole !== false));
  const named = pool.filter((c) => ITEM_NAMES.test(words(c)));
  const bare = pool.filter((c) => BARE_ID.test(words(c)) && !named.includes(c));
  const repeats = (c) => facts[c]?.nUnique != null && nRows && facts[c].nUnique > 1 && facts[c].nUnique < nRows;
  for (const group of [named, bare]) {
    const hit = group.find(repeats);
    if (hit) return hit;
  }
  // Text that repeats with many values (a unit id per row of readings).
  const many = pool.find((c) => !isNumeric(facts[c]?.dtype) && repeats(c) && facts[c]?.values == null);
  return named[0] || bare[0] || many || "";
}

// The roles past the life ones (an item, a readings column) and Z, around a
// life mapping the Data step would start from.
function complete(mapping, unit, columns, facts, nRows, timeVarying = false) {
  const r = { ...emptyReading() };
  for (const k of ROLES) if (typeof mapping[k] === "string") r[k] = mapping[k];
  r.c_invert = !!mapping.c_invert;
  r.c_map = mapping.c_map || null;
  r.unit = unit || "";
  const used = usedColumns(r);
  if (!r.i) r.i = itemColumn(columns, facts, nRows, used);
  if (r.i) used.add(r.i);
  const reps = facts[r.i]?.nUnique;
  const repeated = r.i && reps != null && reps < nRows;
  if (!r.tr && !timeVarying) {
    r.tr = columns.find((c) => !used.has(c) && isNumeric(facts[c]?.dtype) && END_NAMES.test(words(c))) || "";
    if (r.tr) used.add(r.tr);
  }
  if (!r.e && repeated) {
    // Failures by mode on items followed over time (a repairable record).
    r.e = columns.find((c) => !used.has(c) && !isNumeric(facts[c]?.dtype) && MODE_NAMES.test(words(c))) || "";
    if (r.e) used.add(r.e);
  }
  if (r.i && !r.c && !r.m && reps != null && reps < nRows) {
    // A table of readings (an item measured again and again, no status): the measured value.
    r.m = columns.find((c) => !used.has(c) && isNumeric(facts[c]?.dtype) && VALUE_NAMES.test(words(c))) || "";
    if (r.m) used.add(r.m);
  }
  return { ...r, ...defaultZ(columns, facts, used, nRows) };
}

// The app's first reading of a sheet: lifeData's guessMapping for the life
// roles, then the item, readings and Z. ``facts``: lifeData.columnFacts.
export function guessReading(columns, facts, nRows) {
  const g = guessMapping(columns, facts);
  // Start and stop rows of items (covariates over time, #60), as the Data step reads them.
  const tvc = guessTvc(columns, facts, nRows);
  if (tvc) {
    const m = { ...g.mapping, i: tvc.i, x: "", xl: tvc.xl, xr: tvc.xr, n: "", tl: "", tr: "", e: "", u: "" };
    return complete(m, tvcUnit(tvc) || g.unit, columns, facts, nRows, true);
  }
  return complete(g.mapping, g.unit, columns, facts, nRows);
}

// A reading as a fit flow's life mapping (lifeData's EMPTY_MAPPING shape):
// the life roles, the status meanings and the per-row unit column.
export function lifeMapping(r) {
  if (!r) return { ...EMPTY_MAPPING };
  const m = { ...EMPTY_MAPPING };
  for (const k of ["x", "c", "n", "xl", "xr", "tl", "tr", "e", "u"]) m[k] = r[k] || "";
  m.c_invert = !!r.c_invert && !!r.c;
  m.c_map = r.c ? r.c_map || null : null;
  return m;
}

// The reading for a saved dataset (its detail), and where it came from:
// "saved" (kept with the dataset, or confirmed), or for a dataset saved
// before readings (or one the API guessed) the reading today's Data step
// starts from (its newest model's mapping, else the guess), marked "guessed"
// so the summary says "guessed — check it". { reading, source, from }.
export function datasetReading(detail, cols) {
  if (!detail) return null;
  if (detail.reading && detail.reading_source === "saved") {
    return { reading: { ...emptyReading(), ...detail.reading }, source: "saved", from: null };
  }
  const columns = cols.columns || [];
  const facts = cols.facts;
  if (detail.reading && detail.reading_kept) {
    // Guessed over the API and kept: shown as kept, still "guessed — check it".
    return { reading: { ...emptyReading(), ...detail.reading }, source: "guessed", from: null };
  }
  const start = startingMapping(detail.last_mapping, columns, facts, cols.n_rows);
  const reading = complete(start.mapping, start.unit, columns, facts, cols.n_rows);
  return { reading, source: "guessed", from: start.from };
}

// Whether a reading's rows follow items over time: an item column whose values
// repeat (several rows per item). A plain life model then reads one life per
// item (its last time and final status: the ``item_lives`` fit option).
export function itemRows(r, facts, nRows) {
  if (!r?.i) return false;
  const nu = facts?.[r.i]?.nUnique;
  return nu != null && nRows > 0 && nu < nRows;
}

// What stops a reading being saved, each beside the selector it concerns:
// [{ col, row, text }]. x and c are required (c: a status column, or "every
// row failed" ticked; a range or a readings table needs none); the rest are
// the Data step's own checks (lifeData.dataStepIssues).
export function readingIssues(r, facts, nRows) {
  const out = [];
  const range = !!(r.xl || r.xr);
  if (!r.x && !range) {
    out.push({ col: null, row: "x", text: "Pick x: the column with the value when each unit failed or was removed (hours, cycles, km…). Every model is built on it, so the dataset can't be saved without it." });
  }
  if (!r.c && !r.all_failed && !range && !r.m && (r.x || range)) {
    out.push({ col: null, row: "c", text: "Pick c: the column that says failed or still running, or tick “every row failed”. Without it a model can't tell failures from units still running." });
  }
  const used = {};
  for (const k of ROLES) {
    const col = r[k];
    if (!col) continue;
    if (used[col]) out.push({ col, row: k === "u" ? "x" : k === "xl" || k === "xr" ? "x" : k, text: `“${col}” is already ${LABEL[used[col]] || used[col]}: a column can have one role.` });
    else used[col] = k;
  }
  if (r.x || range) {
    for (const i of dataStepIssues(lifeMapping(r), facts, nRows, r.unit)) {
      if (/^Pick x:/.test(i.text)) continue;
      out.push(i);
    }
  }
  return out;
}

// The one-line summary: [{ key, label, value }] —
// "x = Age (hours) · c = Status · i = Tag · failure mode = Mode · Z: Load, Site".
export function readingParts(r) {
  if (!r) return [];
  const out = [];
  if (r.x) out.push({ key: "x", label: "x", value: r.x + (r.unit && r.unit !== "units" ? ` (${r.unit.toLowerCase()})` : "") });
  if (r.xl) out.push({ key: "range", label: "range", value: `${r.xl} to ${r.xr}` });
  if (r.c) out.push({ key: "c", label: "c", value: r.c });
  else if (r.all_failed) out.push({ key: "c", label: "c", value: "every row failed" });
  for (const k of ["n", "tl", "tr", "i", "m", "e", "s"]) {
    if (r[k]) out.push({ key: k, label: LABEL[k] || k, value: r[k] + (k === "m" && r.m_unit ? ` (${r.m_unit})` : "") });
  }
  if (r.z?.length) out.push({ key: "z", label: "Z", value: r.z.join(", "), list: true });
  return out;
}

export function readingText(r) {
  return readingParts(r).map((p) => (p.list ? `${p.label}: ${p.value}` : `${p.label} = ${p.value}`)).join(" · ");
}

// "Z: Load, Site, Duty (3 covariates) · not used: Remarks, Commissioning date".
export function zLine(r) {
  const z = r?.z || [];
  const off = r?.not_used || [];
  const parts = [];
  parts.push(z.length ? `Z: ${z.join(", ")} (${z.length} covariate${z.length === 1 ? "" : "s"})` : "Z: none");
  if (off.length) parts.push(`not used: ${off.join(", ")}`);
  return parts.join(" · ");
}

// The reading after a column is given a role: it leaves Z and not used, and
// any other role it had; a column freed from a role goes back to Z or not
// used by the guard.
export function setRole(r, role, col, facts, nRows) {
  const next = { ...r, [role]: col };
  if (col) for (const k of ROLES) if (k !== role && next[k] === col) next[k] = "";
  if (role === "c") next.all_failed = next.all_failed && !col;
  return withZ(next, r, facts, nRows);
}

// Z and not used kept in step with the roles: columns given a role leave them;
// columns no longer given one come back by the guard.
export function withZ(next, prev, facts, nRows) {
  const used = usedColumns(next);
  const was = usedColumns(prev || {});
  const z = (next.z || []).filter((c) => !used.has(c));
  const off = (next.not_used || []).filter((c) => !used.has(c));
  for (const c of was) {
    if (used.has(c) || z.includes(c) || off.includes(c)) continue;
    (notUsedReason(c, facts?.[c], nRows) ? off : z).push(c);
  }
  const units = Object.fromEntries(Object.entries(next.z_units || {}).filter(([c]) => z.includes(c)));
  return { ...next, z, not_used: off, z_units: units };
}

// Include a not-used column as a covariate, or leave one out.
export function toggleZ(r, col) {
  if ((r.z || []).includes(col)) {
    return { ...r, z: r.z.filter((c) => c !== col), not_used: [...(r.not_used || []), col] };
  }
  return { ...r, z: [...(r.z || []), col], not_used: (r.not_used || []).filter((c) => c !== col) };
}

// The reading as the server keeps it (no empty extras).
export function readingPayload(r) {
  const out = emptyReading();
  for (const k of Object.keys(out)) if (r?.[k] !== undefined) out[k] = r[k];
  // The measurements part's own reading ({ i, x, m, unit, m_unit }), when it has one.
  if (r?.measurements) {
    const { i = "", x = "", m = "", unit = "", m_unit = "" } = r.measurements;
    out.measurements = { i, x, m, unit, m_unit };
  }
  return out;
}

// What a model kind needs that the reading doesn't give, in words, or null.
// ``kind``: "life", "repairable", "alt", "degradation", "joint".
export function missingFor(kind, r) {
  if (!r) return null;
  const x = r.x || r.xl;
  if (kind === "repairable" && !r.i) return "A repairable model follows each system's failures, so it needs i: the column that says which system each row belongs to. This dataset's reading has none.";
  if (kind === "degradation" && (!r.i || !r.m)) return `A degradation model follows each item's readings, so it needs ${!r.i ? "i (which item each row belongs to)" : ""}${!r.i && !r.m ? " and " : ""}${!r.m ? "m (the measured value)" : ""}. This dataset's reading has ${!r.i && !r.m ? "neither" : "none"}.`;
  if (!x) return "This dataset's reading has no x: the value when each unit failed or was removed.";
  return null;
}

// A saved reading still names the dataset's columns (else it's read afresh).
export function readingFits(r, columns) {
  const have = new Set(columns || []);
  return [...usedColumns(r)].every((c) => have.has(c));
}

export { savedMapping };

// A saved dataset's detail in the shape /api/columns gives (the fit flows'
// Data step reads it so), with its column facts.
export function detailColumns(full) {
  return {
    columns: full.preview_columns || [],
    preview: full.preview || [],
    // Wholly blank rows are skipped by every fit, so they aren't counted.
    n_rows: full.n_rows - (full.blank_rows || 0),
    blank_rows: full.blank_rows || 0,
    n_unique: full.n_unique,
    dtypes: full.dtypes,
    blanks: full.blanks,
    values: full.values,
    whole: full.whole,
    nonpositive: full.nonpositive,
  };
}

// The reading without ``column`` (a split's dataset column, left out of every
// part): its role cleared, out of Z and not used; ``back``, a column the
// split gave back, returns to Z or not used by the guard.
export function withoutColumn(r, column, facts = {}, nRows = 0, back = "") {
  if (!r) return r;
  const out = { ...r };
  for (const k of ROLES) if (out[k] === column) out[k] = "";
  out.z = (out.z || []).filter((c) => c !== column);
  out.not_used = (out.not_used || []).filter((c) => c !== column);
  out.z_units = Object.fromEntries(Object.entries(out.z_units || {}).filter(([c]) => c !== column));
  if (back && back !== column && !usedColumns(out).has(back) && !out.z.includes(back) && !out.not_used.includes(back)) {
    (notUsedReason(back, facts[back], nRows) ? out.not_used : out.z).push(back);
  }
  return out;
}
