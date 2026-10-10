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
export function columnFacts(csv) {
  const { columns = [], dtypes, blanks, values, n_unique: nUnique, preview = [] } = csv || {};
  return Object.fromEntries(
    columns.map((name, i) => {
      const sample = preview.map((r) => r[i]).filter((v) => v !== null && v !== "");
      const dtype = dtypes?.[i] ?? (sample.length && sample.every((v) => typeof v === "number") ? "float64" : "object");
      return [name, { dtype, blanks: blanks?.[i] ?? 0, values: values?.[i] ?? null, nUnique: nUnique?.[i] ?? null, sample: sample[0] }];
    })
  );
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
