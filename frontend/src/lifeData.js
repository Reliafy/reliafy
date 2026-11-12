// The fit wizard's Data step (#291): what each column holds, what each status
// value means, the failures-and-running count before a fit, and what is wrong
// with a mapping, in plain words. Pure, so `node --test src/` covers it.
import {
  CONVERTIBLE_UNITS, flagHeaderMeaning, guessIntervalPair, guessLateEntry, guessLifeColumns,
  guessStatusMeaning, guessUnit, guessUnitColumn, isNumeric, likelyStatusColumns, timeUnitOf, unitlessTimeName,
} from "./datasetGuess.js";

// ``e`` names each failure's mode and ``g`` the groups to compare (#177):
// competing risks only. ``u``: a column giving each row's time unit (sent as
// the ``u_col`` fit option): every time is converted to the fit's unit first.
export const EMPTY_MAPPING = {
  x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "", e: "", g: "", u: "", c_invert: false, c_map: null,
};

// The form fields a mapping is sent as, in order: [[field, value]] (api.js's
// fit and save requests). ``u``, a column of per-row units, goes as the
// ``u_col`` fit option; the status meanings with the status column only.
export function mappingFields(mapping) {
  const { c_invert, c_map, u, ...columns } = mapping || {};
  const out = [];
  if (u) out.push(["u_col", u]);
  for (const [field, column] of Object.entries(columns)) {
    if (column) out.push([field, column]);
  }
  if (columns.c) out.push(["c_invert", c_invert ? "1" : "0"]);
  if (columns.c && c_map && Object.keys(c_map).length) out.push(["c_map", JSON.stringify(c_map)]);
  return out;
}

// Column facts from /api/columns or a dataset's detail: name → { dtype,
// blanks, values ({value: rows} when there are few, else null), nUnique }.
// Without dtypes (an older response) a column is numeric when its preview is.
// ``whole``: the column holds only whole numbers (null for text, undefined
// when the server didn't say); ``decimal``: a value from the preview that
// isn't one, for a message.
export function columnFacts(csv) {
  const { columns = [], dtypes, blanks, values, n_unique: nUnique, whole, nonpositive, preview = [] } = csv || {};
  return Object.fromEntries(
    columns.map((name, i) => {
      const sample = preview.map((r) => r[i]).filter((v) => v !== null && v !== "");
      const dtype = dtypes?.[i] ?? (sample.length && sample.every((v) => typeof v === "number") ? "float64" : "object");
      const decimal = sample.find((v) => typeof v === "number" && !Number.isInteger(v));
      return [name, {
        dtype, blanks: blanks?.[i] ?? 0, values: values?.[i] ?? null, nUnique: nUnique?.[i] ?? null, sample: sample[0],
        whole: whole?.[i] ?? (decimal !== undefined ? false : undefined), decimal,
        nonpositive: nonpositive?.[i] ?? null,
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

// What a mapping field does when a column is picked for it: no failure modes
// means no groups, and a new status column starts from guessed meanings for
// its values. x and the range (xl, xr) go together: each row is read from x
// where it is filled and from its range where x is blank.
export function setMappingField(mapping, field, value, facts = {}) {
  const next = { ...mapping, [field]: value };
  if (field === "e" && !value) next.g = "";
  if (field === "c") Object.assign(next, guessStatus(value, facts));
  return next;
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

// A status column's values with its blank cells as one more value ("", shown
// as "(blank)"): a failure-mode column picked as the status is blank for the
// units still running, and a blank can be given a meaning like any word.
export const BLANK_LABEL = "(blank)";
export function statusValuesWithBlank(values, blanks = 0) {
  return blanks > 0 ? { ...(values || {}), "": blanks } : values;
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

// The mapping a dataset was last fitted with (its detail's ``last_mapping``:
// the newest model's columns and status meanings), when every column it names
// is still there: a refit starts from it, keeping the late-entry column and
// what each status word means. Null otherwise.
export function savedMapping(saved, columns) {
  const m = saved?.mapping;
  if (!m || !(m.x || m.xl)) return null;
  const have = new Set(columns || []);
  // ``i``: the item column of rows whose covariates change over time (#60).
  const fields = Object.entries(m).filter(([k, v]) => (k in EMPTY_MAPPING || k === "i") && typeof v === "string" && v);
  if (!fields.length || fields.some(([, v]) => !have.has(v))) return null;
  const opts = saved.options || {};
  return {
    mapping: { ...EMPTY_MAPPING, ...Object.fromEntries(fields), c_invert: !!opts.c_invert, c_map: opts.c_map || null },
    unit: saved.unit || "",
    from: saved.model_name || "",
  };
}

// A first mapping from the column facts, and its unit.
// Two inspection times ("last ok", "found failed") are read as the interval
// the failure lies in, in place of a single time.
export function guessMapping(columns, facts) {
  const cols = columns.map((name) => ({ name, ...facts[name] }));
  const g = guessLifeColumns(cols);
  const pair = guessIntervalPair(cols, [g.c, g.n].filter(Boolean));
  const times = pair ? { x: "", ...pair } : { x: g.x };
  // A column of per-row units ("hrs" / "days"): converted to the most common.
  const mixed = !pair && unitColumnIsAnothers(g.x, columns, facts) ? null : guessUnitColumn(cols, [g.c, g.n, g.x, pair?.xl, pair?.xr].filter(Boolean));
  // A text column named for the failure mode or cause ("Failure mode") beside
  // a status column is the failure mode: fitted as competing risks (one time
  // per unit only). Without a status column its blanks are asked about
  // first (dataQuestions: were those units still running?).
  const mode = !pair && g.c ? likelyStatusColumns(cols).mode.find((c) => ![g.c, g.n, g.x].includes(c.name)) : null;
  // Units already in service when records began ("Entered at (h)"): late
  // entry, so their time before it isn't counted as survived. Not with a
  // failure mode, which takes one time per unit.
  const tl = mode ? "" : guessLateEntry(cols, [g.c, g.n, times.x, pair?.xl, pair?.xr].filter(Boolean));
  return {
    mapping: { ...EMPTY_MAPPING, ...times, c: g.c, n: g.n, e: mode?.name || "", u: mixed?.column || "", tl,
               ...guessStatus(g.c, facts) },
    unit: mixed ? mixed.common : pair ? guessUnit(pair.xl) || guessUnit(pair.xr) : g.unit,
  };
}

// Where the Data step starts: how the dataset was last fitted (its saved
// mapping), unless that reading leaves something unsettled (a value with no
// meaning, a blank status) where a fresh guess reads the sheet cleanly. A
// saved mapping can carry an old choice, a failure-mode column read as the
// status, say, without the meanings that went with it. Returns
// { mapping, unit, from } (``from``: the model it was kept from, or null).
export function startingMapping(saved, columns, facts, nRows) {
  const guess = guessMapping(columns, facts);
  const kept = savedMapping(saved, columns);
  if (!kept) return { ...guess, from: null };
  const unsettled = (m, unit) => dataStepIssues(m, facts, nRows, unit).length
    + dataQuestions(m, facts, columns, nRows).length;
  if (unsettled(kept.mapping, kept.unit) > 0 && unsettled(guess.mapping, guess.unit) === 0) {
    return { ...guess, from: null };
  }
  return { ...kept, from: kept.from || "the last model" };
}

// The choices made on the file loaded before, kept for a corrected copy of
// it loaded next: when every column they name is in the new file (and they
// name a value), { mapping, unit, covariates, tvc }; null otherwise.
export function keptChoices(previous, columns) {
  const m = previous?.mapping;
  if (!m || !(m.x || m.xl || m.i)) return null;
  const have = new Set(columns || []);
  const named = [...Object.values(m).filter((v) => typeof v === "string" && v), ...(previous.covariates || [])];
  if (named.some((c) => !have.has(c))) return null;
  return {
    mapping: { ...m }, unit: previous.unit || "", covariates: [...(previous.covariates || [])], tvc: previous.tvc || null,
  };
}

// Is a column of per-row units another time column's? True when the time
// column names its unit ("Hours in service") and another numeric column is a
// time without one ("Time in service"): the units describe that one.
function unitColumnIsAnothers(x, columns, facts) {
  if (!x || !guessUnit(x)) return false;
  return (columns || []).some((c) => c !== x && isNumeric(facts[c]?.dtype) && unitlessTimeName(c));
}

// A unit column's rows by unit, from its few values: { Hours: 22, Days: 4 }
// (null when the values aren't all time units).
export function unitCounts(column, facts) {
  const values = facts[column]?.values;
  if (!values) return null;
  const counts = {};
  for (const [v, n] of Object.entries(values)) {
    if (String(v).trim() === "") continue;
    const u = timeUnitOf(v);
    if (!u) return null;
    counts[u] = (counts[u] || 0) + n;
  }
  return counts;
}

const countsWords = (counts) => Object.entries(counts).sort((a, b) => b[1] - a[1])
  .map(([u, n]) => `${n.toLocaleString()} in ${u.toLowerCase()}`).join(", ");

// What the Data step says about a unit column: { note } (how many rows are
// converted to ``unit``) or { problem } (a unit it can't convert to, values it
// can't read); null without one.
export function unitColumnWords(mapping, facts, unit) {
  if (!mapping.u) return null;
  const counts = unitCounts(mapping.u, facts);
  if (!counts) {
    return { problem: `“${mapping.u}” doesn't hold only time units (hours, days, weeks…), so it can't give each row's unit. Set it to Ignore.` };
  }
  const to = timeUnitOf(unit) || CONVERTIBLE_UNITS.find((u) => u.toLowerCase() === String(unit || "").trim().toLowerCase());
  if (!to) {
    return { problem: `“${mapping.u}” gives each row's unit (${countsWords(counts)}): pick Hours, Days, Weeks, Months, Years or Minutes as the unit to convert them to.` };
  }
  const converted = Object.entries(counts).filter(([u]) => u !== to).reduce((a, [, n]) => a + n, 0);
  return {
    note: `“${mapping.u}” gives each row's unit (${countsWords(counts)})`
      + (converted ? `: ${plural(converted, "row is", "rows are")} converted to ${to.toLowerCase()} before the fit.` : "."),
    converted, to, counts,
  };
}

// ---- Where the first reading is a guess ---------------------------------------
// With no status column every row is read as a failure. When a column left
// unused could say otherwise, the Data step asks instead of stating a count:
//   mode:<col>    a failure mode (or cause) that is blank on some rows — were
//                 those units still running?
//   status:<col>  a column named like a status whose values aren't known.
// ``answered``: the ids already answered "no". Each question:
// { id, text, yes, no, field, column } — "yes" maps ``column`` to ``field``.
//   flags:<col>   a status column of 0/1 codes whose header doesn't say what
//                 1 means ("status", "flag"): which way round, with the
//                 counts both ways. ``set``: the mapping fields each answer sets.
//   unit:<col>    a column of per-row units (hrs / days) left unused: convert?
export function dataQuestions(mapping, facts, columns, nRows, answered = []) {
  const first = [unitQuestion(mapping, facts, columns), mapping.c && flagQuestion(mapping, facts, nRows)]
    .filter((q) => q && !answered.includes(q.id));
  if (mapping.c || mapping.e) return first;
  return [...first, ...otherQuestions(mapping, facts, columns, nRows, answered)];
}

// A column of mixed per-row units that nothing uses: every time would be read in one unit.
function unitQuestion(mapping, facts, columns) {
  // A time column that names its unit ("Hours in service") is in that unit;
  // a column of per-row units then belongs to another time column.
  if (mapping.u || unitColumnIsAnothers(mapping.x, columns, facts)) return null;
  const used = Object.values(mapping).filter((v) => typeof v === "string" && v);
  const mixed = guessUnitColumn((columns || []).map((name) => ({ name, ...facts[name] })), used);
  if (!mixed) return null;
  return {
    id: `unit:${mixed.column}`, field: "u", column: mixed.column,
    text: `“${mixed.column}” says the rows are in different units (${countsWords(mixed.counts)}), but it isn't being used, so every time would be read in one unit. Convert them?`,
    yes: `Yes: convert each row by “${mixed.column}”`,
    no: "No: the times are all in one unit",
  };
}

function otherQuestions(mapping, facts, columns, nRows, answered) {
  const cols = (columns || []).map((name) => ({ name, ...facts[name] }));
  const used = new Set(Object.values(mapping).filter((v) => typeof v === "string" && v));
  const likely = likelyStatusColumns(cols.filter((c) => !used.has(c.name)));
  const out = [];
  const mode = likely.mode.find((c) => c.blanks > 0 && c.blanks < nRows);
  if (mode && !mapping.xl && !mapping.xr) {
    const n = mode.blanks;
    out.push({
      id: `mode:${mode.name}`, field: "e", column: mode.name,
      text: `${plural(n, "row has", "rows have")} no “${mode.name}”. ${n === 1 ? "Was that unit" : "Were those units"} still running?`,
      yes: "Yes: still running (fit by failure mode)",
      no: "No: every row is a failure",
    });
  }
  const status = likely.status.find((c) => !mode || c.name !== mode.name);
  if (status) {
    // Inspection data reads a blank latest time as still running, so "No"
    // there never means every row failed.
    const interval = mapping.xl && mapping.xr;
    out.push({
      id: `status:${status.name}`, field: "c", column: status.name,
      text: `“${status.name}” looks like it says which units failed, but it isn't being used. Does it?`,
      yes: `Yes: use “${status.name}”`,
      no: interval ? `No: a blank “${mapping.xr}” is a unit still running` : "No: every row is a failure",
    });
  }
  return out.filter((q) => !answered.includes(q.id));
}

// Whether a status column holds only the codes 0 and 1 (both of them).
function zeroOneCodes(values) {
  const keys = statusValues(values).map((v) => statusKey(v.label)).sort();
  return keys.length === 2 && keys[0] === "0" && keys[1] === "1";
}

// The failures and units still running with 1 read as failed (``oneFailed``)
// or as still running, from the status column's value counts.
function countsWay(mapping, facts, nRows, oneFailed) {
  return statusSummary({ ...mapping, c_map: null, c_invert: oneFailed }, facts, nRows);
}

// The question for a 0/1 status column whose header doesn't say which way round
// it is; null when it says ("Failed (1=yes)", "censored") or isn't 0/1 codes.
export function flagQuestion(mapping, facts, nRows) {
  if (!mapping.c || mapping.c_map || !zeroOneCodes(facts[mapping.c]?.values)) return null;
  if (flagHeaderMeaning(mapping.c)) return null;
  const a = countsWay(mapping, facts, nRows, true);
  const b = countsWay(mapping, facts, nRows, false);
  if (!a || !b) return null;
  const words = (s) => summaryParts(s).join(", ");
  return {
    id: `flags:${mapping.c}`, field: "c", column: mapping.c,
    text: `“${mapping.c}” doesn't say what 1 means. Which way round is it?`,
    yes: `1 = failed: ${words(a)}`,
    no: `0 = failed: ${words(b)}`,
    set: { yes: { c_invert: true, c_map: null }, no: { c_invert: false, c_map: null } },
  };
}

// How a status column is read, in words, for the line above the counts:
// "1 = failed, 0 = still running". Empty for a word map or no status column.
export function flagWords(mapping, facts) {
  if (!mapping.c || mapping.c_map || !zeroOneCodes(facts[mapping.c]?.values)) return "";
  return mapping.c_invert ? "1 = failed, 0 = still running" : "0 = failed, 1 = still running";
}

// The mapping after a question is answered, and the ids answered so far.
export function answerQuestion(mapping, question, yes, facts = {}, answered = []) {
  if (question.set) return { mapping: { ...mapping, ...(yes ? question.set.yes : question.set.no) }, answered: [...answered, question.id] };
  return {
    mapping: yes ? setMappingField(mapping, question.field, question.column, facts) : mapping,
    answered: [...answered, question.id],
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
  const values = statusValues(statusValuesWithBlank(facts[mapping.c]?.values, facts[mapping.c]?.blanks));
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
// A header that spells it out ("Failed (1=yes)") is taken at its word.
export function flagsLookSwapped(mapping, summary) {
  if (!mapping.c || mapping.c_map || !summary) return null;
  if (/(^|[^\d])[01]\s*=|=\s*[01]\b/.test(mapping.c) && flagHeaderMeaning(mapping.c)) return null;
  if (summary.left || summary.interval) return null;
  const total = summary.failed + summary.running;
  if (!total || summary.running * 2 <= total) return null;
  return { code: mapping.c_invert ? "0" : "1" };
}

const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

// "15 failures, 6 still running" — numbers to show bold, as parts.
// ``inspection``: the rows are inspection times (an earliest and a latest),
// worded as an inspector would.
export function summaryParts(s, { inspection = false } = {}) {
  if (!s) return [];
  if (inspection) {
    return [
      s.failed ? `${s.failed.toLocaleString()} failed at a known time` : null,
      s.interval ? `${s.interval.toLocaleString()} failed between inspections` : null,
      s.left ? `${s.left.toLocaleString()} found failed at the first inspection` : null,
      s.running ? `${s.running.toLocaleString()} still running` : null,
    ].filter(Boolean);
  }
  return [
    plural(s.failed, "failure", "failures"),
    s.running ? `${s.running.toLocaleString()} still running` : null,
    s.left ? `${s.left.toLocaleString()} found failed (left-censored)` : null,
    s.interval ? plural(s.interval, "interval", "intervals") : null,
  ].filter(Boolean);
}

// What stops this mapping fitting, in plain words. Empty when it is ready.
// ``unit``: the fit's unit, which a column of per-row units converts to.
export function dataStepProblems(mapping, facts, nRows, unit = undefined) {
  return dataStepIssues(mapping, facts, nRows, unit).map((i) => i.text);
}

// What may stop some fits without stopping all, said on its column: a value
// of 0 or less, which Kaplan-Meier takes but a Weibull refuses. [{ col, text }].
export function dataStepNotes(mapping, facts) {
  const n = facts[mapping.x]?.nonpositive;
  if (!mapping.x || !n) return [];
  return [{
    col: mapping.x,
    text: `${plural(n, "row has", "rows have")} a value of 0 or less in “${mapping.x}”. A distribution such as Weibull can't fit `
      + `${n === 1 ? "it" : "them"}: correct or remove ${n === 1 ? "that row" : "those rows"}, or use a non-parametric estimate.`,
  }];
}

// The same, each with the column it comes from (``col``; null when it is
// about no one column, such as a missing x), so the Data step can show it
// beside the selector it concerns (issueRow): [{ col, text }]. The words
// never assume time: x may be hours, cycles, km, volts…
export function dataStepIssues(mapping, facts, nRows, unit = undefined) {
  const out = [];
  const add = (col, text) => out.push({ col: col || null, text });
  const perRow = unit === undefined ? null : unitColumnWords(mapping, facts, unit);
  if (perRow?.problem) add(mapping.u, perRow.problem);
  const f = (col) => facts[col] || {};
  const rows = (n) => plural(n, "row has", "rows have");
  const sample = (col) => (f(col).sample != null ? ` (e.g. “${f(col).sample}”)` : "");
  const numericCol = (col, what) => {
    if (col && !isNumeric(f(col).dtype)) add(col, `“${col}” holds text${sample(col)}, not ${what}. Pick another column.`);
  };
  // x and a range (xl to xr) are read per row: x where it is filled, the
  // range where x is blank. Either alone works too.
  const range = !!(mapping.xl || mapping.xr);
  if (range && (!mapping.xl || !mapping.xr)) {
    add(null, "Pick both xl and xr for the range, or neither.");
  }
  numericCol(mapping.xl, "numbers");
  numericCol(mapping.xr, "numbers");
  if (!mapping.x && !range) {
    add(null, "Pick x: the column with the value when each unit failed or was removed.");
  } else if (mapping.x && !isNumeric(f(mapping.x).dtype)) {
    add(mapping.x, `“${mapping.x}” holds text${sample(mapping.x)}, not numbers. Pick the column with the values (hours, cycles, km…).`);
  } else if (mapping.x && !range && f(mapping.x).blanks) {
    add(mapping.x, `${rows(f(mapping.x).blanks)} no value in “${mapping.x}”. Fill them in, give those rows a range (xl to xr), or delete them.`);
  }
  if (mapping.c) {
    const values = f(mapping.c).values;
    if (!values) {
      add(mapping.c, `“${mapping.c}” has ${f(mapping.c).nUnique ?? "too many"} different values, so it can't say failed or still running. Pick the status column, or none.`);
    } else {
      if (f(mapping.c).blanks && statusMeaning("", mapping) === null) {
        add(mapping.c, `${rows(f(mapping.c).blanks)} no value in “${mapping.c}”. Say what a blank means (failed or still running) beside the column, or fill them in.`);
      }
      const unknown = statusValues(values).filter((v) => statusMeaning(v.label, mapping) === null);
      if (unknown.length) {
        const names = unknown.slice(0, 3).map((v) => `“${v.label}”`).join(", ");
        add(mapping.c, `Say whether ${names}${unknown.length > 3 ? " and the rest" : ""} ${unknown.length === 1 ? "means" : "mean"} failed or still running.`);
      }
    }
  }
  if (mapping.e && (mapping.xl || mapping.xr || mapping.tl || mapping.tr)) {
    add(mapping.e, "Failure modes take one exact value per unit: clear the range (xl, xr) and late entry (tl), or the failure mode.");
  }
  numericCol(mapping.n, "counts");
  if (mapping.n && countProblem(f(mapping.n)) === "decimals") {
    const eg = f(mapping.n).decimal != null ? ` (e.g. “${f(mapping.n).decimal}”)` : "";
    add(mapping.n, `“${mapping.n}” holds decimals${eg}, so it can't be a count: a count says how many units share each row, in whole numbers. Set n to none, or pick a column of whole numbers.`);
  }
  numericCol(mapping.tl, "numbers");
  numericCol(mapping.tr, "numbers");
  const s = statusSummary(mapping, facts, nRows);
  if (!out.length && s && s.failed + s.left + s.interval === 0 && s.running > 0) {
    add(mapping.c || null, "No row is marked failed, so there is nothing to fit. Check what each status means.");
  }
  return out;
}

// Which Data step selector an issue sits beside: "x" (x, the range, the
// per-row unit, or no one column), "c", "n", "tl" or "e".
const ISSUE_ROWS = { x: "x", xl: "x", xr: "x", u: "x", i: "x", c: "c", n: "n", tl: "tl", tr: "tl", e: "e" };
export function issueRow(issue, mapping) {
  if (!issue?.col) return "x";
  const field = Object.keys(ISSUE_ROWS).find((f) => mapping[f] === issue.col);
  return field ? ISSUE_ROWS[field] : "x";
}

// Whether a status column holds only the codes 0 and 1 (either or both):
// read as 0 = failed, 1 = still running, or flipped with "my column uses 1 = failed".
export function statusCodesOnly(values) {
  const keys = statusValues(values).map((v) => statusKey(v.label));
  return keys.length > 0 && keys.every((k) => k === "0" || k === "1");
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

const MEANING_WORDS = { 0: "failed", 1: "still running", "-1": "found failed", 2: "interval" };

// How a mapping reads a table, in words, for the saved-data picker's pane:
// [{ label, value }]. The status line spells out each flag's meaning
// (0 = failed, 1 = still running, or the other way round when flipped).
export function mappingWords(mapping, facts = {}, unit = "") {
  const u = unit ? ` (${unit})` : " (no unit yet)";
  const out = [];
  if (mapping.xl || mapping.xr) {
    out.push({ label: "Time", value: `between “${mapping.xl || "?"}” and “${mapping.xr || "?"}”${u}` });
  } else {
    out.push({ label: "Time", value: mapping.x ? `“${mapping.x}”${u}` : "not found: pick it on the next step" });
  }
  if (mapping.c) {
    const flags = statusValues(facts[mapping.c]?.values)
      .map((v) => {
        const m = statusMeaning(v.label, mapping);
        return `${v.label} = ${m == null ? "not said yet" : MEANING_WORDS[m]}`;
      });
    out.push({ label: "Status", value: `“${mapping.c}”${flags.length ? `: ${flags.join(", ")}` : ""}` });
  } else if (mapping.xr && facts[mapping.xr]?.blanks) {
    out.push({ label: "Status", value: `none: a blank “${mapping.xr}” is a unit still running` });
  } else {
    out.push({ label: "Status", value: "none: every row is a failure" });
  }
  if (mapping.n) out.push({ label: "Count", value: `“${mapping.n}”` });
  if (mapping.tl) out.push({ label: "Observed from", value: `“${mapping.tl}”` });
  if (mapping.tr) out.push({ label: "Observed until", value: `“${mapping.tr}”` });
  const perRow = unitColumnWords(mapping, facts, unit);
  if (perRow) out.push({ label: "Unit of each row", value: perRow.note || perRow.problem });
  return out;
}

// Late entry in words for the Data step: "20 entered late (observed from
// “Entered at (h)”): accounted for". Counted from the column's values when
// it has few (a row entering at 0 isn't late); otherwise named only.
export function lateEntryWords(column, facts) {
  const values = facts?.[column]?.values;
  if (values) {
    const late = Object.entries(values).filter(([v]) => Number(v) > 0).reduce((a, [, n]) => a + n, 0);
    if (late) return `${plural(late, "unit", "units")} entered late (observed from “${column}”): accounted for`;
    return `no unit entered late in “${column}”`;
  }
  return `late entry from “${column}”: accounted for`;
}

// A life chart's value axis: "Time (Hours)" for a time unit, the unit itself
// for anything else ("Cycles", "kV"): x needn't be time. "Time" with no unit,
// as before.
const TIME_WORD = /\b(minutes?|hours?|hrs?|days?|weeks?|months?|years?)\b/i;
export function valueAxisTitle(unit) {
  const u = String(unit ?? "").trim();
  if (!u || isUnitless(u)) return "Time";
  return TIME_WORD.test(u) || timeUnitOf(u) ? `Time (${u})` : u;
}
