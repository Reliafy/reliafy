// Pure helpers for the degradation wizard (no React, so `node --test` runs them).

// Distinct values in `column`, counted over every row: the server's count
// (`n_unique`, from /api/columns or a dataset's detail) when it sent one,
// otherwise the preview's own rows, but only when the preview holds every row.
// null when the count isn't known, so the wizard says nothing rather than
// warning off a first-rows sample that shows one item.
export function distinctCount(csv, column) {
  if (!csv || !column) return null;
  const idx = (csv.columns || []).indexOf(column);
  if (idx === -1) return null;
  const n = csv.n_unique?.[idx];
  if (Number.isFinite(n)) return n;
  const rows = csv.preview || [];
  if (csv.n_rows != null && rows.length < csv.n_rows) return null;
  return new Set(rows.map((r) => r[idx]).filter((v) => v !== null && v !== undefined && v !== "")).size;
}

// A dataset the wizard can fit: an item id, a time and a measurement column.
export const usableForDegradation = (d) => (d?.n_columns ?? 0) >= 3;

// A column name's words, lower-case: "wear_mm" → ["wear", "mm"],
// "Time (h)" → ["time", "h"], "wearMm" → ["wear", "mm"].
function words(name) {
  return String(name ?? "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-zµ°%]+/)
    .filter(Boolean);
}

// The text inside brackets, if the name has any: "Wear (mm)" → "mm".
function bracketed(name) {
  const m = String(name ?? "").match(/[([]\s*([^)\]]+?)\s*[)\]]/);
  return m ? m[1] : null;
}

// Time units in the pickers' spelling, keyed by the ways columns write them.
const TIME_WORDS = {
  Seconds: ["s", "sec", "secs", "second", "seconds"],
  Minutes: ["min", "mins", "minute", "minutes"],
  Hours: ["h", "hr", "hrs", "hour", "hours"],
  Days: ["d", "day", "days"],
  Weeks: ["wk", "wks", "week", "weeks"],
  Months: ["mo", "mon", "month", "months"],
  Years: ["y", "yr", "yrs", "year", "years"],
  Cycles: ["cyc", "cycle", "cycles"],
  Kilometres: ["km", "kms", "kilometre", "kilometres", "kilometer", "kilometers"],
  Miles: ["mi", "mile", "miles"],
  Operations: ["op", "ops", "operation", "operations"],
};
// The time-unit field's suggestions.
export const TIME_UNITS = Object.keys(TIME_WORDS);
const TIME_BY_WORD = Object.fromEntries(
  Object.entries(TIME_WORDS).flatMap(([unit, ws]) => ws.map((w) => [w, unit]))
);

// The time unit a column's name gives, in the pickers' spelling, or "".
// "hours" → "Hours", "time_h" → "Hours", "Age (days)" → "Days". A lone
// letter counts only beside another word ("time_h"), never as the whole name.
export function guessTimeUnit(column) {
  const inside = bracketed(column);
  if (inside) {
    const unit = TIME_BY_WORD[inside.toLowerCase()];
    if (unit) return unit;
  }
  const ws = words(column);
  for (let i = ws.length - 1; i >= 0; i--) {
    const w = ws[i];
    if (w.length === 1 && ws.length === 1) continue;
    if (TIME_BY_WORD[w]) return TIME_BY_WORD[w];
  }
  return "";
}

// Measurement units as they're usually written, keyed by lower-case spelling.
const MEASURE_UNITS = Object.fromEntries(
  [
    "mm", "cm", "m", "µm", "um", "in", "inch", "mil", "mils", "%", "pct", "percent",
    "kg", "g", "n", "kn", "mpa", "kpa", "pa", "psi", "bar", "v", "mv", "a", "ma",
    "ohm", "ohms", "db", "hz", "khz", "c", "degc", "°c", "f", "degf", "°f", "k", "ppm", "w", "kw",
  ].map((u) => [u, u])
);
// How to write the ones that aren't simply lower-case.
const MEASURE_SPELLING = {
  um: "µm", inch: "in", mils: "mil", pct: "%", percent: "%", n: "N", kn: "kN", mpa: "MPa",
  kpa: "kPa", pa: "Pa", v: "V", mv: "mV", a: "A", ma: "mA", ohm: "Ω", ohms: "Ω", db: "dB",
  hz: "Hz", khz: "kHz", c: "°C", degc: "°C", "°c": "°C", f: "°F", degf: "°F", "°f": "°F",
  k: "K", w: "W", kw: "kW",
};

// The measurement unit a column's name gives, or "". "wear_mm" → "mm",
// "Crack (µm)" → "µm", "temp_c" → "°C". Brackets are taken as written; a bare
// unit word counts only when it's the last word after another ("wear_mm", not
// "mm" or "m_wear").
export function guessMeasurementUnit(column) {
  const inside = bracketed(column);
  if (inside) return MEASURE_SPELLING[inside.toLowerCase()] || inside;
  const ws = words(column);
  if (ws.length < 2) return "";
  const last = ws[ws.length - 1];
  if (!MEASURE_UNITS[last]) return "";
  return MEASURE_SPELLING[last] || last;
}

// First guesses for the item, time and measurement columns by their names:
// the item is named like an id (unit, pad, serial…), the time like a time or
// with a time unit (hours, odometer_km), the measurement is the next column.
// Falls back to the first three columns in order.
const ID_NAME = /^(id|item|unit|units|asset|serial|sn|tag|vehicle|truck|pad|pads|part|specimen|sample|component|system|name|no)$/;
const TIME_NAME = /^(time|times|age|hours?|hrs?|days?|cycles?|km|kms|miles?|odometer|mileage|distance|runtime|duration|t)$/;
export function guessDegradationColumns(columns) {
  const cols = columns || [];
  const has = (re) => (c) => words(c).some((w) => re.test(w));
  const i = cols.find(has(ID_NAME)) || cols[0] || "";
  const x = cols.find((c) => c !== i && (has(TIME_NAME)(c) || guessTimeUnit(c))) || cols.find((c) => c !== i) || "";
  const y = cols.find((c) => c !== i && c !== x) || "";
  return { i, x, y };
}

// The degradation Data step: the shared selectors (ColumnMapper) with only
// what the fit reads: i (the item), x (when each reading was taken) and m
// (the measured value, sent as ``y``). No c (an item's readings simply stop)
// and no covariates (the fit takes none).
export const DEGRADATION_ROWS = ["i", "x", "m"];
export const DEGRADATION_KEYS = { m: "y" };
export const DEGRADATION_WORDS = {
  i: "which item each reading belongs to",
  x: "when the reading was taken",
  m: "the measured value",
};

// What stops the Data step, beside its selector: [{ row, text }].
export function degradationIssues(csv, mapping) {
  const out = [];
  if (!mapping.i) out.push({ row: "i", text: "Pick i: the column saying which item each reading belongs to." });
  if (!mapping.x) out.push({ row: "x", text: "Pick x: the column saying when each reading was taken." });
  if (!mapping.y) out.push({ row: "m", text: "Pick m: the column with the measured value." });
  const cols = [mapping.i, mapping.x, mapping.y].filter(Boolean);
  if (new Set(cols).size < cols.length) out.push({ row: "m", text: "i, x and m must be three different columns." });
  const items = distinctCount(csv, mapping.i);
  if (mapping.i && items !== null && items < 2) {
    out.push({ row: "i", text: `“${mapping.i}” has ${items === 1 ? "only 1 item" : "no values"}: the fit needs at least 2 items.` });
  } else if (mapping.i && items !== null && csv?.n_rows && items === csv.n_rows) {
    out.push({ row: "i", text: `Each of the ${items} items has only one reading: a path needs at least two readings per item.` });
  }
  return out;
}

// The way m goes towards failure, from the first item's readings in the
// preview: "falls" or "rises" (rises when it can't be told).
export function guessDirection(csv, mapping) {
  const cols = csv?.columns || [];
  const [ii, xi, yi] = [mapping.i, mapping.x, mapping.y].map((c) => cols.indexOf(c));
  if (ii < 0 || xi < 0 || yi < 0) return "rises";
  const first = (csv.preview || []).filter((r) => r[ii] === csv.preview[0][ii])
    .map((r) => [Number(r[xi]), Number(r[yi])]).filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b))
    .sort((a, b) => a[0] - b[0]);
  if (first.length < 2) return "rises";
  return first[first.length - 1][1] < first[0][1] ? "falls" : "rises";
}

// The threshold against the first reading: the problem beside it, or null.
// ``direction`` isn't sent: the fit reads each item's path; this is a check.
export function thresholdProblem(csv, mapping, threshold, direction, unit = "") {
  if (threshold === "" || threshold == null) return "Enter the value at which an item counts as failed.";
  const t = Number(threshold);
  if (!Number.isFinite(t)) return "The threshold must be a number.";
  const cols = csv?.columns || [];
  const yi = cols.indexOf(mapping.y);
  const start = yi < 0 ? NaN : Number(csv.preview?.[0]?.[yi]);
  if (!Number.isFinite(start)) return null;
  const u = unit ? ` ${unit}` : "";
  if (direction === "falls" && start <= t) return `The first reading (${start}${u}) is already at or below ${t}${u}: check the threshold, or whether m rises to it.`;
  if (direction === "rises" && start >= t) return `The first reading (${start}${u}) is already at or above ${t}${u}: check the threshold, or whether m falls to it.`;
  return null;
}
