// The status column for a fit that reads c only as codes (repairable and
// accelerated life: 0 = a failure, 1 = still running or the end of the
// record), from a dataset's reading (datasetReading.js). A reading's c can be
// words ("Failed", "Running": c_map) or 1 = failed (c_invert), which those
// fits can't read. Then a 0/1 column the reading left out that says the same
// thing row for row (the same counts of each code) is used in its place, and
// the flow says so; with none, the fit can't go ahead and the reading needs
// changing. Pure, so `node --test src/` covers it.
import { notUsedReason } from "./datasetReading.js";
import { censorInverted } from "./datasetGuess.js";

const key = (v) => String(v ?? "").trim().toLowerCase();

// The counts of each code the reading's c gives ({ "0": 34, "1": 26 }), from
// the column's value counts, or null when they aren't known.
function codeCounts(r, fact) {
  const values = fact?.values;
  if (!values) return null;
  const out = {};
  if (r.c_map && Object.keys(r.c_map).length) {
    const codes = Object.fromEntries(Object.entries(r.c_map).map(([v, code]) => [key(v), String(code)]));
    for (const [v, n] of Object.entries(values)) {
      const code = codes[key(v)];
      if (code === undefined) return null;
      out[code] = (out[code] || 0) + n;
    }
    return out;
  }
  const flip = { 0: "1", 1: "0" };
  for (const [v, n] of Object.entries(values)) {
    const code = flip[key(v)] ?? key(v);
    out[code] = (out[code] || 0) + n;
  }
  return out;
}

const sameCounts = (a, b) => {
  const ka = Object.keys(a).filter((k) => a[k]);
  const kb = Object.keys(b || {}).filter((k) => b[k]);
  return ka.length === kb.length && ka.every((k) => String(a[k]) === String(b[String(k)]));
};

// { c, from, problem }: ``c`` the column to send; ``from`` the reading's own
// c when another column stands in for it; ``problem`` what stops the fit, in
// words. ``codes``: what 0 and 1 mean to this fit, for the problem's words.
export function codedStatus(r, facts = {}, nRows = 0, codes = "0 = failed, 1 = still running") {
  const c = r?.c || "";
  const words = !!(r?.c_map && Object.keys(r.c_map).length);
  if (!c || (!words && !r.c_invert)) return { c, from: null, problem: null };
  const want = codeCounts(r, facts[c]);
  const alt = want && [...(r.not_used || []), ...(r.z || [])].find((col) => col !== c
    && notUsedReason(col, facts[col], nRows) === "a status" && !censorInverted(col)
    && sameCounts(want, facts[col]?.values));
  if (alt) return { c: alt, from: c, problem: null };
  return {
    c,
    from: null,
    problem: words
      ? `This model reads the status as codes (${codes}), and “${c}” holds words. Change the reading so c is a column of those codes.`
      : `“${c}” uses 1 for a failure, and this model reads ${codes}. Change the reading so c is a column coded that way.`,
  };
}

// The note when another column stands in for the reading's c.
export function codedStatusNote(s) {
  return s?.from
    ? `This model reads the status as 0/1 codes, so it uses “${s.c}” for c, which says the same as “${s.from}” row for row.`
    : null;
}

// A per-row unit column (u) can't be read by these fits: every row's x must be in one unit.
export function unitColumnProblem(r) {
  return r?.u
    ? `This model needs every x in one unit, and the reading converts “${r.u}” row by row. Change the reading to a column in one unit.`
    : null;
}
