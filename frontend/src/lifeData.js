// The fit wizard's Data step (#291): what each column holds, what each status
// value means, the failures-and-running count before a fit, and what is wrong
// with a mapping, in plain words. Pure, so `node --test src/` covers it.
import { guessLifeColumns, guessStatusMeaning, isNumeric } from "./datasetGuess.js";

// ``e`` names each failure's mode and ``g`` the groups to compare (#177):
// competing risks only.
export const EMPTY_MAPPING = {
  x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "", e: "", g: "", c_invert: false, c_map: null,
};

// Column facts from /api/columns or a dataset's detail: name → { dtype,
// blanks, values ({value: rows} when there are few, else null), nUnique }.
// Without dtypes (an older response) a column is numeric when its preview is.
// ``whole``: the column holds only whole numbers (null for text, undefined
// when the server didn't say); ``decimal``: a value from the preview that
// isn't one, for a message.
export function columnFacts(csv) {
  const { columns = [], dtypes, blanks, values, n_unique: nUnique, whole, preview = [] } = csv || {};
  return Object.fromEntries(
    columns.map((name, i) => {
      const sample = preview.map((r) => r[i]).filter((v) => v !== null && v !== "");
      const dtype = dtypes?.[i] ?? (sample.length && sample.every((v) => typeof v === "number") ? "float64" : "object");
      const decimal = sample.find((v) => typeof v === "number" && !Number.isInteger(v));
      return [name, {
        dtype, blanks: blanks?.[i] ?? 0, values: values?.[i] ?? null, nUnique: nUnique?.[i] ?? null, sample: sample[0],
        whole: whole?.[i] ?? (decimal !== undefined ? false : undefined), decimal,
      }];
    })
  );
}

// Why a column can't be the count (n), or null when it can (#434): a count
// says how many units share a row, so it holds whole numbers. "text" or
// "decimals".
export function countProblem(fact) {
  if (!fact) return null;
  if (!isNumeric(fact.dtype)) return "text";
  if (fact.whole === false) return "decimals";
  return null;
}

// What a mapping field does when a column is picked for it: the time column
// and the interval pair exclude each other, no failure modes means no groups,
// and a new status column starts from guessed meanings for its values.
export function setMappingField(mapping, field, value, facts = {}) {
  const next = { ...mapping, [field]: value };
  if (field === "x" && value) {
    next.xl = "";
    next.xr = "";
  } else if ((field === "xl" || field === "xr") && value) {
    next.x = "";
  }
  if (field === "e" && !value) next.g = "";
  if (field === "c") Object.assign(next, guessStatus(value, facts));
  return next;
}

// ---- What each column is for (#434) -------------------------------------------
// The Data step also lists every column with its role, so a column that isn't
// a time, a status or a count (a cost, an id) has a home: Ignore, or a
// covariate where the model takes them.

const ROLE_FIELDS = ["x", "xl", "xr", "i", "c", "n", "e", "tl", "tr", "g", "group"];
const ROLE_LABELS = {
  x: "Time to failure", xl: "Earliest failure time", xr: "Latest failure time", i: "Item",
  c: "Failed or still running", n: "Count", e: "Failure mode", tl: "Observed from", tr: "Observed until",
  g: "Group to compare", group: "Group by", cov: "Covariate", "": "Ignored",
};
const TVC_LABELS = {
  intervals: { xl: "Start of the row", xr: "End of the row" },
  timeline: { x: "Time of the row" },
};

// A role's name in words, for the layout (#60's rows name their times their own way).
export function roleLabel(role, timeVarying = null) {
  return TVC_LABELS[timeVarying]?.[role] || ROLE_LABELS[role] || role;
}

// The roles a column can be given: the survival fields of the layout, a
// covariate (``covariates``: the model takes them), and "Ignore this column".
export function roleChoices({ timeVarying = null, covariates = false, failureMode = false } = {}) {
  const fields = timeVarying === "intervals" ? ["i", "xl", "xr", "c"]
    : timeVarying === "timeline" ? ["i", "x", "c"]
    : ["x", "c", "n", "xl", "xr", "tl", "tr"];
  if (failureMode) fields.push("e");
  return [...fields, ...(covariates ? ["cov"] : []), ""];
}

// Each column's role: a mapping field, "cov" or "" (ignored).
export function columnRoles(columns, mapping, covariates = []) {
  return Object.fromEntries((columns || []).map((col) => [
    col,
    ROLE_FIELDS.find((f) => mapping[f] === col) || (covariates.includes(col) ? "cov" : ""),
  ]));
}

// The mapping and covariates after ``col`` is given ``role`` ("" ignores it):
// it leaves whatever it did before, and takes the role from any other column.
export function assignRole(mapping, covariates, col, role, facts = {}) {
  let next = { ...mapping };
  for (const f of ROLE_FIELDS) if (next[f] === col) next = setMappingField(next, f, "", facts);
  let covs = (covariates || []).filter((c) => c !== col);
  if (role === "cov") covs = [...covs, col];
  else if (role) next = setMappingField(next, role, col, facts);
  return { mapping: next, covariates: covs };
}

// Which columns are used, and for what, and which are ignored.
export function roleSummary(roles) {
  const entries = Object.entries(roles || {});
  return {
    used: entries.filter(([, r]) => r).map(([col, role]) => ({ col, role })),
    ignored: entries.filter(([, r]) => !r).map(([col]) => col),
  };
}

// How a status value is matched (as the server does): trimmed and
// case-folded; a number as a whole number where it is one ("1.0" → "1").
export function statusKey(value) {
  const v = String(value ?? "").trim();
  const num = v === "" ? NaN : Number(v);
  if (Number.isFinite(num) && Number.isInteger(num)) return String(num);
  return v.toLowerCase();
}

// A status column's values, case variants merged: [{ label, rows }].
export function statusValues(values) {
  const out = new Map();
  for (const [label, rows] of Object.entries(values || {})) {
    const k = statusKey(label);
    const prev = out.get(k);
    out.set(k, prev ? { ...prev, rows: prev.rows + rows } : { label, rows });
  }
  return [...out.values()];
}

const CODES = ["0", "1", "-1", "2"];

// What a status value means under a mapping: 0 failed, 1 still running, -1
// left-censored, 2 interval, null not said yet. A word map (``c_map``) wins;
// otherwise the value is a 0/1 code, flipped by ``c_invert``.
export function statusMeaning(label, mapping) {
  const k = statusKey(label);
  if (mapping.c_map) {
    const hit = Object.entries(mapping.c_map).find(([key]) => statusKey(key) === k);
    return hit ? Number(hit[1]) : null;
  }
  if (k === "0" || k === "1") return mapping.c_invert ? 1 - Number(k) : Number(k);
  if (k === "-1" || k === "2") return Number(k);
  return null;
}

// The fields a set of meanings is sent as: 0/1 codes as they are or flipped
// (``c_invert``, as before), anything else as a word map (``c_map``).
// ``choices``: [[label, meaning | null]].
export function encodeStatus(choices) {
  if (choices.length && choices.every(([l]) => CODES.includes(statusKey(l)))) {
    const at = (code) => choices.find(([l]) => statusKey(l) === code)?.[1];
    const fixed = choices.every(([l, m]) => !["-1", "2"].includes(statusKey(l)) || m === Number(statusKey(l)));
    const zero = at("0"), one = at("1");
    if (fixed && (zero === undefined || zero === 0) && (one === undefined || one === 1)) return { c_invert: false, c_map: null };
    if (fixed && (zero === undefined || zero === 1) && (one === undefined || one === 0)) return { c_invert: true, c_map: null };
  }
  return { c_invert: false, c_map: Object.fromEntries(choices.filter(([, m]) => m !== null && m !== undefined)) };
}

// The mapping after one status value is given a meaning.
export function setStatusMeaning(mapping, values, label, meaning) {
  const choices = statusValues(values).map((v) => [
    v.label, statusKey(v.label) === statusKey(label) ? meaning : statusMeaning(v.label, mapping),
  ]);
  return { ...mapping, ...encodeStatus(choices) };
}

// The status fields for a newly picked status column: each value's guessed
// meaning (from its word, or the column's name for 0/1 codes).
export function guessStatus(column, facts) {
  if (!column) return { c_invert: false, c_map: null };
  const values = statusValues(facts[column]?.values);
  if (!values.length) return { c_invert: false, c_map: null };
  return encodeStatus(values.map((v) => [v.label, guessStatusMeaning(v.label, column)]));
}

// A first mapping from the column facts, and its unit.
export function guessMapping(columns, facts) {
  const g = guessLifeColumns(columns.map((name) => ({ name, ...facts[name] })));
  return {
    mapping: { ...EMPTY_MAPPING, x: g.x, c: g.c, n: g.n, ...guessStatus(g.c, facts) },
    unit: g.unit,
  };
}

// A paste of one column of times, or times and 0/1 flags, needs no mapping.
export function isSimplePaste(columns) {
  const key = (columns || []).join(",");
  return key === "time" || key === "time,censored";
}

// Failures and units still running, from the status column's value counts.
// Null when it can't be told from them: interval data, a count column (each
// row is several units), a status column with many values, or values not
// given a meaning yet.
export function statusSummary(mapping, facts, nRows) {
  if (!mapping.x || mapping.xl || mapping.xr || mapping.n) return null;
  const rows = nRows - (facts[mapping.x]?.blanks || 0);
  if (!mapping.c && mapping.e) {
    // No status column beside a failure-mode one: a blank mode is still running.
    const running = facts[mapping.e]?.blanks || 0;
    return { failed: rows - running, running, left: 0, interval: 0 };
  }
  if (!mapping.c) return { failed: rows, running: 0, left: 0, interval: 0 };
  const values = statusValues(facts[mapping.c]?.values);
  if (!facts[mapping.c]?.values) return null;
  const out = { failed: 0, running: 0, left: 0, interval: 0 };
  for (const v of values) {
    const m = statusMeaning(v.label, mapping);
    if (m === null) return null;
    out[{ 0: "failed", 1: "running", "-1": "left", 2: "interval" }[m]] += v.rows;
  }
  return out;
}

// Flags that may be the other way round: most units still running, from a
// plain 0/1 status column (no word map, no -1 or 2). Spreadsheets often use
// 1 = failed, and a fit then reads as far too optimistic with no other sign.
// Returns { code }: the flag value now read as still running, or null.
export function flagsLookSwapped(mapping, summary) {
  if (!mapping.c || mapping.c_map || !summary) return null;
  if (summary.left || summary.interval) return null;
  const total = summary.failed + summary.running;
  if (!total || summary.running * 2 <= total) return null;
  return { code: mapping.c_invert ? "0" : "1" };
}

const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

// "15 failures, 6 still running" — numbers to show bold, as parts.
export function summaryParts(s) {
  if (!s) return [];
  return [
    plural(s.failed, "failure", "failures"),
    s.running ? `${s.running.toLocaleString()} still running` : null,
    s.left ? `${s.left.toLocaleString()} found failed (left-censored)` : null,
    s.interval ? plural(s.interval, "interval", "intervals") : null,
  ].filter(Boolean);
}

// What stops this mapping fitting, in plain words. Empty when it is ready.
export function dataStepProblems(mapping, facts, nRows) {
  const out = [];
  const f = (col) => facts[col] || {};
  const rows = (n) => plural(n, "row has", "rows have");
  const sample = (col) => (f(col).sample != null ? ` (e.g. “${f(col).sample}”)` : "");
  const numericCol = (col, what) => {
    if (col && !isNumeric(f(col).dtype)) out.push(`“${col}” holds text${sample(col)}, not ${what}. Pick another column.`);
  };
  if (mapping.xl || mapping.xr) {
    if (!mapping.xl || !mapping.xr) out.push("Pick both the earliest and the latest possible failure time, or use a single time column.");
    numericCol(mapping.xl, "times");
    numericCol(mapping.xr, "times");
  } else if (!mapping.x) {
    out.push("Pick the column that holds the time to failure or removal.");
  } else if (!isNumeric(f(mapping.x).dtype)) {
    out.push(`“${mapping.x}” holds text${sample(mapping.x)}, not times. Pick the column with the hours, cycles or days.`);
  } else if (f(mapping.x).blanks) {
    out.push(`${rows(f(mapping.x).blanks)} no time in “${mapping.x}”. Fill them in or delete those rows, then load the file again.`);
  }
  if (mapping.c) {
    const values = f(mapping.c).values;
    if (!values) {
      out.push(`“${mapping.c}” has ${f(mapping.c).nUnique ?? "too many"} different values, so it can't say failed or still running. Pick the status column, or none.`);
    } else {
      if (f(mapping.c).blanks) {
        out.push(`${rows(f(mapping.c).blanks)} no value in “${mapping.c}”. Fill in whether each unit failed or was still running.`);
      }
      const unknown = statusValues(values).filter((v) => statusMeaning(v.label, mapping) === null);
      if (unknown.length) {
        const names = unknown.slice(0, 3).map((v) => `“${v.label}”`).join(", ");
        out.push(`Say whether ${names}${unknown.length > 3 ? " and the rest" : ""} ${unknown.length === 1 ? "means" : "mean"} failed or still running.`);
      }
    }
  }
  if (mapping.e && (mapping.xl || mapping.xr || mapping.tl || mapping.tr)) {
    out.push("Failure modes take one time per unit: clear the interval and truncation columns, or the failure mode.");
  }
  numericCol(mapping.n, "counts");
  if (mapping.n && countProblem(f(mapping.n)) === "decimals") {
    const eg = f(mapping.n).decimal != null ? ` (e.g. “${f(mapping.n).decimal}”)` : "";
    out.push(`“${mapping.n}” holds decimals${eg}, so it can't be a count: a count says how many units share each row, in whole numbers. Set Count to none, or pick a column of whole numbers.`);
  }
  numericCol(mapping.tl, "times");
  numericCol(mapping.tr, "times");
  const s = statusSummary(mapping, facts, nRows);
  if (!out.length && s && s.failed + s.left + s.interval === 0 && s.running > 0) {
    out.push("No row is marked failed, so there is nothing to fit. Check what each status means.");
  }
  return out;
}

// Failures and units still running in an uploaded or pasted file, counted
// from its status (and count) columns: the Data step's summary when a count
// column is mapped, and the result's Data tile (#311). Null when the file
// isn't plain comma-separated text with a header the mapping names, or holds
// inspection (interval) data — the tile then shows the observation count.
export async function dataSplit(file, mapping) {
  if (!file || !mapping.x || mapping.xl || mapping.xr) return null;
  const text = await file.text();
  if (text.includes('"')) return null;
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return null;
  const header = lines[0].split(",").map((h) => h.trim());
  const col = (name) => (name ? header.indexOf(name) : -1);
  const xi = col(mapping.x), ci = col(mapping.c), ni = col(mapping.n);
  if (xi < 0 || (mapping.c && ci < 0) || (mapping.n && ni < 0)) return null;
  const out = { failed: 0, running: 0, other: 0 };
  for (const line of lines.slice(1)) {
    const cells = line.split(",");
    if (!(cells[xi] || "").trim()) continue;
    const n = ni >= 0 ? Number(cells[ni]) : 1;
    const c = ci >= 0 ? statusMeaning(cells[ci], mapping) : 0;
    if (!Number.isFinite(n) || c === null) return null;
    if (c === 0) out.failed += n;
    else if (c === 1) out.running += n;
    else out.other += n;
  }
  return out;
}

// ---- Pasted values -----------------------------------------------------------

// "1, 2, 3, 5" → "lines 1–3 and 5" (line numbers as the user sees them).
export function lineRanges(lines) {
  const sorted = [...lines].sort((a, b) => a - b);
  const runs = [];
  for (const n of sorted) {
    const last = runs[runs.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else runs.push([n, n]);
  }
  const parts = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`));
  const shown = parts.length > 4 ? [...parts.slice(0, 3), `${parts.length - 3} more`] : parts;
  const text = shown.length > 1 ? `${shown.slice(0, -1).join(", ")} and ${shown[shown.length - 1]}` : shown[0];
  return `${sorted.length === 1 ? "line" : "lines"} ${text}`;
}

const FLAGS = [-1, 0, 1, 2];
const pastedNumber = (t) => {
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
};

// The non-blank lines of a paste with their line numbers in the text, a
// leading header line (no digits) dropped.
function pastedLines(text) {
  const lines = String(text || "").split(/\r?\n/)
    .map((raw, i) => ({ n: i + 1, cells: raw.trim().split(/[\s,;]+/).filter(Boolean) }))
    .filter((l) => l.cells.length);
  if (lines.length && !/[0-9]/.test(lines[0].cells.join(" "))) lines.shift();
  return lines;
}

// Some lines are "time flag" and others a bare time: the flags can't be
// guessed, so say which lines are which and how to fix it. ``fix`` lets the
// paste box offer "Add 0 (failed) to lines without a flag" (never applied
// without the user pressing it).
function mixedFlagsError(bare, flagged) {
  const err = new Error(
    `${cap(lineRanges(bare.map((l) => l.n)))} ${bare.length === 1 ? "has" : "have"} one value, but ` +
    `${lineRanges(flagged.map((l) => l.n))} ${flagged.length === 1 ? "has" : "have"} two (a time and a censor flag). ` +
    "Every line needs the same shape: give each line a flag (0 = failed, 1 = still running), or remove the flags."
  );
  err.fix = "add-flags";
  err.lines = bare.map((l) => l.n);
  return err;
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// Turn pasted values into CSV text. Accepts one value per line, or values
// separated by commas / spaces / tabs / semicolons on any number of lines. When
// every line carries exactly two numbers the second is read as the censoring
// flag (0 = failed, 1 = still running; -1 left, 2 interval also pass). A
// leading non-numeric line (a header) is ignored. Returns { csv, rows, cols }
// or throws with a message fit to show inline.
export function parsePastedValues(text) {
  const lines = pastedLines(text);
  if (!lines.length) throw new Error("Paste at least a few values first.");
  const rows = lines.map((l) => l.cells);
  if (rows.every((r) => r.length === 2)) {
    const out = [];
    for (const { n, cells: [t, c] } of lines) {
      const tv = pastedNumber(t);
      const cv = pastedNumber(c);
      if (tv === null) throw new Error(`Line ${n}: "${t}" isn't a number.`);
      if (cv === null || !FLAGS.includes(cv)) {
        throw new Error(`Line ${n}: censoring flag "${c}" should be 0 (failed) or 1 (still running).`);
      }
      out.push(`${tv},${cv}`);
    }
    return { csv: `time,censored\n${out.join("\n")}\n`, rows: out.length, cols: 2 };
  }
  // Lines of one value mixed with lines of two whose second value is a flag:
  // the way people add suspensions to a list of failures.
  const bare = lines.filter((l) => l.cells.length === 1);
  const flagged = lines.filter((l) => l.cells.length === 2);
  if (bare.length && flagged.length && bare.length + flagged.length === lines.length
      && flagged.every((l) => FLAGS.includes(pastedNumber(l.cells[1])))) {
    throw mixedFlagsError(bare, flagged);
  }
  // Other mixed line shapes are ambiguous: point at the first line that breaks
  // the pattern of the first one.
  const bad = lines.findIndex((l) => l.cells.length !== lines[0].cells.length);
  if (bad !== -1 && lines.length > 1 && lines[0].cells.length <= 2) {
    const n = lines[bad].cells.length;
    const first = lines[0].cells.length;
    throw new Error(
      `Line ${lines[bad].n} has ${n} value${n === 1 ? "" : "s"} but line ${lines[0].n} has ${first}. ` +
      "Put one time on each line, or a time and a censor flag (0 = failed, 1 = still running) on every line."
    );
  }
  const out = [];
  for (const t of rows.flat()) {
    const tv = pastedNumber(t);
    if (tv === null) throw new Error(`"${t}" isn't a number.`);
    out.push(String(tv));
  }
  if (out.length < 2) throw new Error("Paste at least two values.");
  return { csv: `time\n${out.join("\n")}\n`, rows: out.length, cols: 1 };
}

// The paste with " 0" (failed) added to every line that holds a single time,
// for the "Add 0 (failed) to lines without a flag" button. Other lines, blank
// lines and a header line are kept as they were.
export function addMissingFlags(text) {
  const header = pastedLines(text)[0]?.n;
  return String(text || "").split(/(\r?\n)/).map((part, i) => {
    if (i % 2) return part; // a line break
    const n = i / 2 + 1;
    const cells = part.trim().split(/[\s,;]+/).filter(Boolean);
    if (cells.length !== 1 || pastedNumber(cells[0]) === null || (n < header)) return part;
    const sep = /\t/.test(text) ? "\t" : /,/.test(text) ? "," : " ";
    return `${part.replace(/\s+$/, "")}${sep}0`;
  }).join("");
}

// ---- The time unit -------------------------------------------------------------

// What the fit flow stores when the user says the times have no unit: the
// backend reads "units" as unspecified (backend/units.py), and results read
// "B10 257 units", so a unit always shows.
export const UNITLESS = "units";

export function isUnitless(unit) {
  return ["units", "unitless", "no unit"].includes(String(unit ?? "").trim().toLowerCase());
}
