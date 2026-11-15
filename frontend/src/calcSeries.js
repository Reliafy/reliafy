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
