// The Calculator's curves and the covariate values they were worked out at.
// Typing a covariate asks the server for a new curve, and the answer on
// screen is read off the curve held. Until the curve for the values now in
// the boxes arrives, the series is ``pending`` and nothing is read off it: an
// answer for other values must never sit beside these ones. Answers that
// arrive late, for values since changed, are dropped. Pure, so
// `node --test src/` covers it.

// What a curve was asked for: the covariate values (a number typed as text is
// the same number) and the x-range.
export function requestKey(values, range = null) {
  const norm = Object.fromEntries(Object.keys(values || {}).sort().map((k) => {
    const v = values[k];
    const num = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
    return [k, typeof num === "number" && Number.isFinite(num) ? num : v];
  }));
  return JSON.stringify([norm, range?.xMin ?? null, range?.xMax ?? null]);
}

// The series after ``id`` is given new values (or a new range): its curve is
// on order, so it is pending under ``key``.
export function markPending(series, id, key, values) {
  return series.map((s) => (s.id === id
    ? { ...s, ...(values !== undefined ? { values } : {}), pending: key, error: null } : s));
}

// The series after an answer for ``key`` arrives: taken only by the series
// still waiting for exactly that key.
export function applyAnswer(series, id, key, { curves = null, error = null } = {}) {
  return series.map((s) => {
    if (s.id !== id || s.pending !== key) return s;
    return error ? { ...s, pending: null, stale: true, error } : { ...s, curves, pending: null, stale: false, error: null };
  });
}

// Can an answer be read off this series' curve? Not while its curve is on
// order, nor after the order failed (the curve held is for other values).
export function curveIsCurrent(s) {
  return !!s && !s.pending && !s.stale;
}

// Where the curves must be worked out to for a time ``asked`` past their end (the stored grid stops at
// the 99% life): a round number a fifth beyond it. Null when the curves already reach it, when nothing
// valid is asked, or when the model can't be worked out again (no evaluate path).
export function autoRangeEnd(functions, asked) {
  const x = functions?.curves?.x;
  if (!functions?.evaluate_path || !x?.length || asked == null || !Number.isFinite(asked)) return null;
  const end = x[x.length - 1];
  if (!(asked > end)) return null;
  const want = asked * 1.2;
  const step = 10 ** (Math.floor(Math.log10(want)) - 1);
  return Math.ceil(want / step) * step;
}

// The values for a new covariate combination ("Compare another"): the last
// combination's, with its first category covariate moved to a value no
// combination uses yet, so one click compares design B with design A rather
// than adding a second design A to edit.
export function nextCombinationValues(series, covariates, fallback = {}) {
  const values = { ...(series[series.length - 1]?.values || fallback) };
  for (const c of covariates || []) {
    if (c.type !== "category" || !(c.options || []).length) continue;
    const used = new Set(series.map((s) => String(s.values?.[c.name])));
    const valueOf = (o) => (o && typeof o === "object" ? o.value : o);
    const free = c.options.map(valueOf).find((o) => o != null && !used.has(String(o)));
    if (free != null) {
      values[c.name] = free;
      break;
    }
  }
  return values;
}

// ``bases``: each categorical covariate's base level ({ site: "East" }), the
// level its effects are measured against. The calculator starts a category
// there (numbers at their data means), so its answer reads with the Effects
// tab; the stored curves are for the most common level, so a series that
// starts elsewhere is marked stale and worked out again on mount.
export function startValues(covariates, bases = {}) {
  return Object.fromEntries((covariates || []).map((c) => [c.name,
    c.type === "category" && !c.stratum && bases?.[c.name] != null && (c.options || []).map(String).includes(String(bases[c.name]))
      ? String(bases[c.name]) : c.default]));
}

// Where the first combination starts, while it is untouched: "Starting at
// each number's data mean; site at East, the base level the Effects compare
// against." Null when nothing needs saying.
export function startNote(covariates, values, bases = {}) {
  const cats = (covariates || []).filter((c) => c.type === "category" && !c.stratum && bases?.[c.name] != null);
  if (!cats.length || !values) return null;
  const start = startValues(covariates, bases);
  if ((covariates || []).some((c) => String(values[c.name]) !== String(start[c.name]))) return null;
  const nums = (covariates || []).some((c) => c.type !== "category");
  const levels = cats.map((c) => `${c.name} at ${start[c.name]}`).join(", ");
  return `Starting at ${nums ? "each number's data mean; " : ""}${levels}: the base level${cats.length > 1 ? "s" : ""} the Effects compare against.`;
}
