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
