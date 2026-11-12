// First guesses for a repairable model's columns: the system (i), each
// failure's time (x), each system's end of record (tr) and the failure mode.
// Pure, so `node --test src/` covers it.
//   - a time (x or tr) is only ever a numeric column: a text column such as
//     a site is never guessed as one;
//   - the end of record is a numeric column named like "observed to",
//     "records end", "end of record", "trial end", "tr": guessed rather than
//     offered as a covariate, since leaving it out changes the fit;
//   - the time is a numeric column named like hours, time, age, failure, and
//     not like an end; else the first numeric column that isn't the end.

const words = (name) => String(name ?? "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-.()/#:]+/g, " ")
  .replace(/\s+/g, " ").trim().toLowerCase();

const END_WORDS = /^(tr|t end|t_end)$|\b(observed to|observed until|observed|observation end|end of (record|records|observation|test|trial|history|data)|records? end|record end|records? to|end|ends|ended|until|trial end|test end|window end|last seen|censor(ed)? (time|at)|cutoff|cut off|horizon|stop|stopped)\b/;
const TIME_WORDS = /\b(time|times|hours?|hrs?|age|failure|failures|event|events|km|kms|miles?|cycles?|days?|operating|run|runtime|starts?|landings?)\b/;
const ID_WORDS = /^(i|id)$|\b(id|system|systems|unit|units|asset|machine|equipment|item|serial|sn|tag|truck|vehicle|pump|compressor|engine|component|fleet no|number|name)\b/;
const MODE_RE = /^(failure[ _-]?)?mode$|^cause$|^failure[ _-]?cause$/i;

// Is a column numeric? Its dtype when known ("int64", "float64"), else its
// preview values: numbers (or blanks) only.
export function numericColumns(columns, { dtypes = null, preview = [] } = {}) {
  return (columns || []).map((c, k) => {
    if (dtypes && dtypes[k]) return /int|float/.test(String(dtypes[k]));
    const vals = (preview || []).map((row) => (Array.isArray(row) ? row[k] : row?.[c]))
      .filter((v) => v !== null && v !== undefined && String(v).trim() !== "");
    return vals.length > 0 && vals.every((v) => typeof v === "number" || Number.isFinite(Number(v)));
  });
}

export function guessRecurrentMapping(columns, { dtypes = null, preview = [] } = {}) {
  const cols = columns || [];
  const numeric = numericColumns(cols, { dtypes, preview });
  const isNum = (c) => numeric[cols.indexOf(c)];
  const num = cols.filter(isNum);
  const text = cols.filter((c) => !isNum(c));
  const mode = cols.find((c) => MODE_RE.test(String(c).trim())) || "";
  const i = text.find((c) => ID_WORDS.test(words(c)) && c !== mode)
    || cols.find((c) => ID_WORDS.test(words(c)) && c !== mode)
    || text.find((c) => c !== mode) || cols[0] || "";
  const tr = num.find((c) => c !== i && END_WORDS.test(words(c))) || "";
  const free = num.filter((c) => c !== i && c !== tr);
  const x = free.find((c) => TIME_WORDS.test(words(c))) || free[0] || "";
  return { i, x, c: "", n: "", tl: "", tr, mode };
}

// The warning the Data step shows while no end of record is mapped.
export const NO_RECORD_END = "No end of record is mapped, so each system's record will be taken to end at its "
  + "last failure, which makes failures look closer together at the end than they were. Map tr, the column that "
  + "says how far each item's record goes, or add a row for each item's end of record, flagged 1 in c.";

// A dataset's ``last_recurrent_mapping`` (how its newest repairable model read
// the columns) as { mapping, unit, from }, or null when it doesn't fit these
// columns: a refit from a saved dataset starts there, not from a fresh guess.
export function savedRecurrentMapping(saved, columns) {
  const m = saved?.mapping;
  if (!m || !m.i || !m.x) return null;
  const have = new Set(columns || []);
  const keys = ["i", "x", "c", "n", "tl", "tr", "mode", "ws", "we"];
  const fields = keys.filter((k) => typeof m[k] === "string" && m[k]);
  const z = Array.isArray(m.z) ? m.z.filter(Boolean) : [];
  if ([...fields.map((k) => m[k]), ...z].some((c) => !have.has(c))) return null;
  return {
    mapping: { i: "", x: "", c: "", n: "", tl: "", tr: "", mode: "", ...Object.fromEntries(fields.map((k) => [k, m[k]])),
               ...(z.length ? { z } : {}) },
    unit: saved.unit || "",
    from: saved.model_name || "",
  };
}

// The repairable Data step: the shared selectors (ColumnMapper) with i first,
// only those the repairable fit takes (no range: xl / xr aren't read), the
// failure mode sent as ``mode``.
export const RECURRENT_ROWS = ["i", "x", "c", "n", "tl", "tr", "e"];
export const RECURRENT_KEYS = { e: "mode" };
export const RECURRENT_WORDS = {
  i: "which item each row belongs to",
  x: "the value at each failure, counted from new",
  c: "a failure, or the end of the record",
  n: "how many failures the row stands for",
  tl: "start of record: observed only from this value",
  tr: "end of record: observed only up to this value",
  e: "optional: each failure's cause",
};
export const RECURRENT_NONE = {
  c: "— none: every row is a failure —",
  tl: "— none: watched from new —",
  tr: "— none: each record ends at its last failure —",
};

// What stops a repairable mapping, or needs saying, beside its selector:
// [{ row, text, note? }] (``note``: said, but doesn't stop Next).
export function recurrentIssues(map, windows = "") {
  const out = [];
  if (!map.i) out.push({ row: "i", text: "Pick i: the column saying which item each row belongs to." });
  if (!map.x) out.push({ row: "x", text: "Pick x: the column with the value at each failure." });
  if (map.i && map.x && map.i === map.x) out.push({ row: "x", text: "x and i are the same column: pick a different one for each." });
  if (out.length === 0 && !map.tr && !map.c && !(map.ws && map.we) && !String(windows || "").trim()) {
    out.push({ row: "tr", text: NO_RECORD_END, note: true });
  }
  return out;
}

// The column fields a repairable fit is sent as (api.js recurrentForm):
// [[field, value]], in order: i, x, the optional modifiers, the covariates.
export function recurrentFields(mapping) {
  const out = [["i", mapping.i], ["x", mapping.x]];
  ["c", "n", "tl", "tr", "t", "mode", "ws", "we"].forEach((k) => { if (mapping[k]) out.push([k, mapping[k]]); });
  (mapping.z || []).forEach((col) => out.push(["z", col]));
  return out;
}
