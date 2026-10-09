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
export function censorInverted(name) {
  return FAILED_RE.test(String(name || "").trim());
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
// A failed / still-running flag: status, failed, censor, event, suspended…
const STATUS_WORDS = /\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event|events|suspend|suspended|suspension|suspensions|running|outcome|survived|alive|dead)\b/i;
// …but not a failure *mode*, cause or date.
const NOT_STATUS = /\b(mode|modes|cause|causes|type|code|description|desc|reason|date|time|hours?|comment|comments|notes?)\b/i;
// An identifier: never the time, however numeric.
const ID_WORDS = /\b(id|ids|no|number|serial|sn|s n|tag|asset|unit|item|equipment|code|row|index)\b/i;
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
  return null;
}

// A time unit from a column name: "Operating Hours" → "Hours", "km" →
// "Kilometres". The spellings match the Data step's unit suggestions.
const UNIT_NAMES = [
  [/\b(hours?|hrs?|hr|h)\b/i, "Hours"], [/\b(days?)\b/i, "Days"], [/\b(weeks?)\b/i, "Weeks"],
  [/\b(months?)\b/i, "Months"], [/\b(years?)\b/i, "Years"], [/\b(cycles?)\b/i, "Cycles"],
  [/\b(km|kms|kilomet(?:re|er)s?)\b/i, "Kilometres"], [/\b(miles?|mileage)\b/i, "Miles"],
  [/\b(minutes?|mins?)\b/i, "Minutes"], [/\b(operations?)\b/i, "Operations"], [/\b(starts?)\b/i, "Starts"],
  [/\b(landings?)\b/i, "Landings"],
];
export function guessUnit(name) {
  const w = words(name);
  return UNIT_NAMES.find(([re]) => re.test(w))?.[1] || "";
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
    columns.find((c) => CENSOR_RE.test(String(c.name).trim()) && looksLikeStatus(c));
  const c = status?.name || "";
  const count = columns.find((col) => col.name !== c && isNumeric(col.dtype) && COUNT_NAMES.test(String(col.name).trim()));
  const n = count?.name || "";
  const numeric = columns.filter((col) => isNumeric(col.dtype) && col.name !== c && col.name !== n);
  const x =
    numeric.find((col) => TIME_WORDS.test(words(col.name))) ||
    numeric.find((col) => !ID_WORDS.test(words(col.name))) ||
    numeric[0];
  return { x: x?.name || "", c, n, unit: guessUnit(x?.name) };
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
