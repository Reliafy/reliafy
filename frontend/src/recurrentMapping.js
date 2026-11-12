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
  + "last failure, which makes failures look closer together at the end than they were. Map the column that "
  + "says how far each system's records go (tr), or add each system's end-of-record row (c = 1).";
