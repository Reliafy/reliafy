// First guesses for a dataset's columns: which is the time, which the censor
// flag (and which way round it is), and what to split a comparison by. Pure,
// so `node --test src/` covers them.

const CENSOR_RE = /^(c|cens|censor|censored|censoring|status|fail|failed|failure|failures|event|suspended|suspension|running)$/i;
// Flags that are 1 when the unit FAILED: Reliafy's convention is the other way
// round (0 = failed, 1 = still running), so these need inverting.
const FAILED_RE = /^(is_?)?(fail|failed|failure|failures|event|status|dead|death|broken)(_?flag)?$/i;
const UNIT_RE = /^(hours?|hrs?|h|minutes?|mins?|days?|weeks?|months?|years?|cycles?|km|miles?|starts?)$/i;

export const isNumeric = (dtype) => /int|float/.test(String(dtype));

// Is a censor column with this name 1 = failed (so it needs inverting)?
// "failed", "failure", "event", "status": yes. "censored", "suspended": no.
// A header that says what 1 means wins: "Failed (1=yes)", "failed?",
// "failure (y/n)", "1 = failed" are 1 = failed; "Running (1=yes)" isn't.
export function censorInverted(name) {
  const said = flagHeaderMeaning(name);
  if (said) return said === "failed";
  return FAILED_RE.test(String(name || "").trim());
}

// What a 0/1 flag column's header says 1 means: "failed", "running", or null
// when the header doesn't say (a bare "status", "flag", "outcome"), so the
// Data step asks rather than guesses.
//   - an explicit pair wins: "1=yes", "1 = failed", "yes=1", "0 = running";
//     yes / no read by the header's subject ("Failed (1=yes)": yes = failed);
//   - else the subject alone: failed / failure / fail / event / dead / broken
//     (with or without "?", "(y/n)", "is_", "_flag") is 1 = failed; censored /
//     suspended / running / survived / alive, and SurPyval's "c", are 1 = still
//     running.
const SUBJECT_FAILED = /\b(fail|failed|fails|failure|failures|event|events|dead|death|died|broken|broke|tripped)\b/;
const SUBJECT_RUNNING = /\b(c|cens|censor|censored|censoring|suspend|suspended|suspension|running|survived|survives|alive|working|ok|in service)\b/;
const WORD_FAILED = /^(failed|fail|failure|f|broken|dead|event|down)$/;
const WORD_RUNNING = /^(running|run|r|censored|cens|suspended|s|survived|alive|ok|working|in service)$/;
const WORD_YES = /^(yes|y|true|t)$/;
const WORD_NO = /^(no|n|false)$/;
export function flagHeaderMeaning(name) {
  const raw = String(name || "").toLowerCase().replace(/([a-z])([A-Z])/g, "$1 $2");
  const flip = (m) => (m === "failed" ? "running" : m === "running" ? "failed" : null);
  // The subject: the header with its "x = y" parts, brackets and marks taken out.
  const core = raw.replace(/-?\d+\s*=\s*[a-z ]+?(?=[),;/]|$)|[a-z]+\s*=\s*-?\d+/g, " ")
    .replace(/[_\-.()[\]#:?/,;]+/g, " ").replace(/\s+/g, " ").trim();
  const subject = SUBJECT_FAILED.test(core) && !SUBJECT_RUNNING.test(core) ? "failed"
    : SUBJECT_RUNNING.test(core) && !SUBJECT_FAILED.test(core) ? "running" : null;
  const wordMeaning = (w) => {
    const v = w.trim().replace(/\s+/g, " ");
    if (WORD_FAILED.test(v)) return "failed";
    if (WORD_RUNNING.test(v) || v === "still running") return "running";
    if (WORD_YES.test(v)) return subject;
    if (WORD_NO.test(v)) return flip(subject);
    return null;
  };
  // "1=yes", "1 = failed", "0 = still running"
  for (const m of raw.matchAll(/(?:^|[^\d-])([01])\s*=\s*([a-z][a-z ]*?)(?=\s*(?:[),;/]|$|\d))/g)) {
    const w = wordMeaning(m[2]);
    if (w) return m[1] === "1" ? w : flip(w);
  }
  // "yes=1", "failed = 1"
  for (const m of raw.matchAll(/([a-z][a-z ]*?)\s*=\s*([01])\b/g)) {
    const w = wordMeaning(m[1].split(/[(,;/]/).pop());
    if (w) return m[2] === "1" ? w : flip(w);
  }
  return subject;
}

// The column to split a comparison by: an explicit choice wins; otherwise the
// text column with the fewest distinct values from 2 to 8 (a site, a
// supplier), not one value per unit. ``distinct`` maps column → its count of
// distinct values. Failing that, a numeric column with 2–8 values (a test
// temperature), then any other text column.
export function guessSplit(columns, { distinct = {}, exclude = [], splitBy = null } = {}) {
  const names = columns.map((c) => c.name);
  if (splitBy && names.includes(splitBy)) return splitBy;
  const pool = columns.filter((c) => !exclude.includes(c.name));
  const few = (cols) =>
    cols
      .filter((c) => distinct[c.name] >= 2 && distinct[c.name] <= 8)
      .sort((a, b) => distinct[a.name] - distinct[b.name])[0]?.name;
  const text = pool.filter((c) => !isNumeric(c.dtype));
  return few(text) || few(pool.filter((c) => isNumeric(c.dtype))) || text[0]?.name || pool[0]?.name || "";
}

// First guesses for Compare groups: time, split, censor (and whether to
// invert it) and unit.
export function guessCompareColumns(columns, { distinct = {}, splitBy = null } = {}) {
  const names = columns.map((c) => c.name);
  const censor = columns.find((c) => CENSOR_RE.test(c.name) && isNumeric(c.dtype))?.name || "";
  const time =
    columns.find((c) => isNumeric(c.dtype) && c.name !== censor && c.name !== splitBy)?.name || names[0] || "";
  const group = guessSplit(columns, { distinct, splitBy, exclude: [time, censor] });
  return {
    time,
    group,
    censor,
    invert: !!censor && censorInverted(censor),
    unit: UNIT_RE.test(time) ? time.toLowerCase() : "",
  };
}

// ---- Life data (the fit wizard's Data step, #291) ----------------------------

// A column name as words: "operating_hours" and "OperatingHours" → "operating hours".
const words = (name) =>
  String(name || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-./()[\]#:]+/g, " ").trim();

// A time to failure or removal: hours, cycles, km, age… in the name.
const TIME_WORDS = /\b(hours?|hrs?|hr|time|times|age|cycles?|km|kms|kilomet(?:re|er)s?|miles?|mileage|odometer|days?|weeks?|months?|years?|minutes?|mins?|starts?|operations?|landings?|shots?|runtime|duration|life|ttf|tbf|mtbf)\b/i;
// A column named like a time with no unit in its name ("Time in service").
export const unitlessTimeName = (name) => TIME_WORDS.test(words(name)) && !guessUnit(name);

// A failed / still-running flag: status, failed, censor, event, suspended…
const STATUS_WORDS = /\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event|events|suspend|suspended|suspension|suspensions|running|outcome|survived|alive|dead)\b/i;
// …but not a failure *mode*, cause or date.
const NOT_STATUS = /\b(mode|modes|cause|causes|type|code|description|desc|reason|date|time|hours?|comment|comments|notes?)\b/i;
// An identifier: never the time, however numeric.
const ID_WORDS = /\b(id|ids|no|number|serial|sn|s n|tag|asset|unit|item|equipment|code|row|index)\b/i;
const CENSOR_WORDS = /\b(censor|censored|censoring|cens)\b/i;
const COUNT_NAMES = /^(n|count|counts|qty|quantity|units|number of units)$/i;

// A status value's meaning: 0 = failed, 1 = still running, null = can't tell.
// "Failed / Running", "F / S", "yes / no" (read by the column's name: a
// "running" column's yes is still running), and 0/1 codes, which follow
// ``censorInverted``.
const FAILED_VALUES = /^(f|fail|failed|failure|failures|fault|faulty|broken|broke|dead|died|event|down|u ?\/ ?s|unserviceable|defect|defective|tripped|failed in service)$/i;
const RUNNING_VALUES = /^(s|r|run|running|still running|suspended|suspension|susp|censored|survived|survivor|alive|ok|okay|working|operating|operational|in service|in-service|active|serviceable|good|healthy|removed|retired|planned|preventive)$/i;
const YES = /^(y|yes|true|t)$/i;
const NO = /^(n|no|false)$/i;
const RUNNING_NAME = /\b(censor|censored|censoring|cens|suspend|suspended|suspension|running|survived|alive)\b/i;
export function guessStatusMeaning(value, columnName = "") {
  const v = String(value ?? "").trim();
  const num = v === "" ? NaN : Number(v);
  if (num === 0 || num === 1) return censorInverted(columnName) ? 1 - num : num;
  if (num === -1 || num === 2) return num; // left / interval: kept as they are
  if (FAILED_VALUES.test(v)) return 0;
  if (RUNNING_VALUES.test(v)) return 1;
  const runningName = RUNNING_NAME.test(words(columnName)) && !censorInverted(columnName);
  if (YES.test(v)) return runningName ? 1 : 0;
  if (NO.test(v)) return runningName ? 0 : 1;
  return phraseMeaning(v);
}

// A phrase of status words ("Removed, OK", "Found failed", "OK at last
// check"): read by its words when they all point one way and nothing negates
// them ("not failed" is left for the person). backend/services/datasets.py's
// ``status_code`` reads them the same way.
const PHRASE_FAILED = new Set(["fail", "failed", "failure", "fault", "faulty", "broken", "broke", "dead", "died",
  "unserviceable", "defect", "defective", "tripped", "seized", "burst", "leaking", "leaked", "cracked", "worn"]);
const PHRASE_RUNNING = new Set(["ok", "okay", "running", "suspended", "suspension", "censored", "survived", "alive",
  "working", "operating", "operational", "serviceable", "good", "healthy", "removed", "retired", "planned",
  "preventive", "still", "active", "unfailed"]);
const PHRASE_NEGATION = new Set(["not", "no", "non", "never", "without", "un", "nil"]);
function phraseMeaning(v) {
  const tokens = String(v).toLowerCase().match(/[a-z]+/g) || [];
  if (!tokens.length || tokens.some((t) => PHRASE_NEGATION.has(t))) return null;
  const failed = tokens.some((t) => PHRASE_FAILED.has(t));
  const running = tokens.some((t) => PHRASE_RUNNING.has(t));
  if (failed === running) return null;
  return failed ? 0 : 1;
}

// A time unit from a column name: "Operating Hours" → "Hours", "km" →
// "Kilometres". The spellings match the Data step's unit suggestions.
const UNIT_NAMES = [
  [/\b(hours?|hrs?|hr|h)\b/i, "Hours"], [/\b(days?)\b/i, "Days"], [/\b(weeks?)\b/i, "Weeks"],
  [/\b(months?)\b/i, "Months"], [/\b(years?|yrs?)\b/i, "Years"], [/\b(cycles?)\b/i, "Cycles"],
  [/\b(km|kms|kilomet(?:re|er)s?)\b/i, "Kilometres"], [/\b(miles?|mileage)\b/i, "Miles"],
  [/\b(minutes?|mins?)\b/i, "Minutes"], [/\b(operations?)\b/i, "Operations"], [/\b(starts?)\b/i, "Starts"],
  [/\b(landings?)\b/i, "Landings"],
];
export function guessUnit(name) {
  const w = words(name);
  return UNIT_NAMES.find(([re]) => re.test(w))?.[1] || "";
}

// A cell that is a calendar time unit, in the unit picker's spelling ("hrs" →
// "Hours", "d" → "Days"); "" for anything else. These are the units a column
// of per-row units can be converted between (backend/unit_column.py).
export const CONVERTIBLE_UNITS = ["Minutes", "Hours", "Days", "Weeks", "Months", "Years"];
const SHORT_UNITS = { d: "Days", wk: "Weeks", wks: "Weeks", w: "Weeks", mo: "Months", mth: "Months", mths: "Months", y: "Years" };
export function timeUnitOf(value) {
  const v = String(value ?? "").trim().toLowerCase().replace(/\.$/, "");
  const u = SHORT_UNITS[v] || (v && guessUnit(v));
  return CONVERTIBLE_UNITS.includes(u) && (SHORT_UNITS[v] || words(v).split(" ").length === 1) ? u : "";
}

// A text column whose every value is a time unit, with more than one unit in
// it ("hrs" on most rows, "days" on a few): { column, counts: { Hours: 22, Days: 4 },
// common } with the most common unit; null with none. ``columns``: [{ name,
// dtype, values }] (``values``: the column's few values and their rows).
export function guessUnitColumn(columns, exclude = []) {
  for (const c of columns || []) {
    if (exclude.includes(c.name) || isNumeric(c.dtype) || !c.values) continue;
    const entries = Object.entries(c.values).filter(([v]) => String(v).trim() !== "");
    if (!entries.length || entries.some(([v]) => !timeUnitOf(v))) continue;
    const counts = {};
    for (const [v, n] of entries) counts[timeUnitOf(v)] = (counts[timeUnitOf(v)] || 0) + n;
    if (Object.keys(counts).length < 2) continue;
    const common = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    return { column: c.name, counts, common };
  }
  return null;
}

// First guesses for a life-data fit: the time column (x), the status column
// (c) and which way round its values are, a count column (n) and the unit.
// ``columns``: [{ name, dtype, values }] — ``values`` is the column's
// {value: rows} when it has only a few (null otherwise).
//   time:   a numeric column named like hours, time, age, cycles, km…; else
//           the first numeric column that isn't an id, a status or a count.
//   status: a column named like status, failed, censored, event, suspended…
//           whose few values read as failed / still running.
export function guessLifeColumns(columns) {
  const looksLikeStatus = (c) => {
    if (!c.values) return false;
    const vals = Object.keys(c.values);
    if (!vals.length) return false;
    if (isNumeric(c.dtype)) return vals.every((v) => ["0", "1", "-1", "2"].includes(String(v)));
    const known = vals.filter((v) => guessStatusMeaning(v, c.name) !== null).length;
    return known * 2 >= vals.length;
  };
  const status =
    columns.find((c) => STATUS_WORDS.test(words(c.name)) && !NOT_STATUS.test(words(c.name)) && looksLikeStatus(c)) ||
    columns.find((c) => CENSOR_RE.test(String(c.name).trim()) && looksLikeStatus(c)) ||
    // "censor_code": censor flags as numbers, whatever else the name says.
    columns.find((c) => CENSOR_WORDS.test(words(c.name)) && isNumeric(c.dtype) && looksLikeStatus(c));
  const c = status?.name || "";
  // A count holds whole numbers (``whole`` false: it has decimals, #434).
  const count = columns.find((col) => col.name !== c && isNumeric(col.dtype) && col.whole !== false
    && COUNT_NAMES.test(String(col.name).trim()));
  const n = count?.name || "";
  // A late-entry column ("Entered at (h)") is never the time, however numeric.
  const numeric = columns.filter((col) => isNumeric(col.dtype) && col.name !== c && col.name !== n
    && !LATE_ENTRY.test(words(col.name)));
  // A header that carries its unit ("Hours in service") beats a bare "Time in service".
  const x =
    numeric.find((col) => TIME_WORDS.test(words(col.name)) && guessUnit(col.name)) ||
    numeric.find((col) => TIME_WORDS.test(words(col.name))) ||
    numeric.find((col) => !ID_WORDS.test(words(col.name))) ||
    numeric[0];
  return { x: x?.name || "", c, n, unit: guessUnit(x?.name) };
}

// Late entry (left truncation): units already in service when records began,
// named like "Entered at (h)", "Entry age", "Observed from", "tl". A numeric
// column only; its name is all the guess goes on.
const LATE_ENTRY = /\b(entered|entry|enters|observed from|observation start|left truncat\w*|truncat\w*|tl)\b/i;
export function guessLateEntry(columns, exclude = []) {
  return columns.find((c) => isNumeric(c.dtype) && !exclude.includes(c.name) && LATE_ENTRY.test(words(c.name)))?.name || "";
}

// Inspection data: the two times a failure lies between, by their names —
// "last ok" and "found failed", earliest / latest, lower / upper, shortest /
// longest, xl / xr. Null when no two numeric columns pair up (two usage
// measures, or the start and stop of an item's rows, aren't an interval).
const EARLIEST = /\b(xl|last ok|last good|passed|earliest|shortest|lower|left)\b/i;
const LATEST = /\b(xr|found failed|found|failed|latest|longest|upper|right)\b/i;
export function guessIntervalPair(columns, exclude = []) {
  const numeric = columns.filter((c) => isNumeric(c.dtype) && !exclude.includes(c.name));
  for (const a of numeric) {
    if (!EARLIEST.test(words(a.name))) continue;
    const b = numeric.find((col) => col !== a && LATEST.test(words(col.name)) && !EARLIEST.test(words(col.name)));
    if (b) return { xl: a.name, xr: b.name };
  }
  return null;
}

// Columns that may say which units failed though nothing maps them: a
// failure mode or cause (``mode``), and a column named like a status whose
// values aren't ones the guess knows (``status``). Each is [{ name }].
export function likelyStatusColumns(columns) {
  const named = (re) => columns.filter((c) => re.test(words(c.name)));
  return {
    mode: named(/\b(mode|modes|cause|causes)\b/i).filter((c) => !isNumeric(c.dtype)),
    status: columns.filter((c) => STATUS_WORDS.test(words(c.name)) && !NOT_STATUS.test(words(c.name))),
  };
}

// A pandas dtype in plain words, for a preview's column heads.
export function dtypeLabel(dtype) {
  const d = String(dtype || "");
  if (/int/.test(d)) return "integer";
  if (/float/.test(d)) return "number";
  if (/bool/.test(d)) return "yes/no";
  if (/date|time/.test(d)) return "date";
  return "text";
}

// Does a model's name already say its distribution ("Bearing life — Weibull")?
// Then a distribution chip beside it repeats it.
export function nameSaysDistribution(name, distribution) {
  const dist = String(distribution || "").replace(/\s*\(.*$/, "").replace(/\s+PH$/, "").trim();
  return !!dist && String(name || "").toLowerCase().includes(dist.toLowerCase());
}

// A paste or file preview: the client sniffs the delimiter; the server does the
// authoritative parse. ``noHeader``: the first row is data (col 1, col 2, …).
function sniff(text) {
  const first = text.split(/\r?\n/).find((l) => l.trim()) || "";
  const counts = { "\t": (first.match(/\t/g) || []).length, ",": (first.match(/,/g) || []).length, ";": (first.match(/;/g) || []).length };
  const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : ",";
}
// Does the first row look like data rather than column names (#434)? True
// when every cell is a number ("300,544966.3125"): the file was saved without
// a header, and its first row would otherwise be lost as the names. The
// server guesses the same way (fitting.first_row_is_data).
const isNumberCell = (c) => c !== "" && Number.isFinite(Number(c));
export function firstRowIsData(text, delim = null) {
  const s = String(text || "").replace(/^﻿/, "");
  const first = s.split(/\r?\n/).find((l) => l.trim()) || "";
  if (!first || first.includes('"')) return false;
  const cells = first.split(delim || sniff(s)).map((c) => c.trim());
  return cells.length > 0 && cells.every(isNumberCell);
}

// A header-less CSV with a header row added (col 1, col 2, …), so the first
// row is kept as data wherever the file goes next (the fit and the save read
// a file as it is).
export function withGenericHeader(text) {
  const s = String(text || "").replace(/^﻿/, "");
  const first = s.split(/\r?\n/).find((l) => l.trim()) || "";
  const n = first.split(",").length;
  return `${Array.from({ length: n }, (_, i) => `col ${i + 1}`).join(",")}\n${s}`;
}

export function parsePreview(text, { rows = 5, noHeader = false } = {}) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < (noHeader ? 1 : 2)) return null;
  const d = sniff(text);
  const split = (l) => l.split(d).map((c) => c.trim());
  const nCols = split(lines[0]).length;
  const columns = noHeader ? Array.from({ length: nCols }, (_, i) => `col ${i + 1}`) : split(lines[0]);
  const data = noHeader ? lines : lines.slice(1);
  return { columns, preview: data.slice(0, rows).map(split), nRows: data.length, nCols };
}

// "pump_test.csv" → "pump_test": the default name for an uploaded file.
export const fileStem = (name) => String(name || "").replace(/\.(csv|tsv|txt|xlsx|xlsm|xls)$/i, "").trim();
