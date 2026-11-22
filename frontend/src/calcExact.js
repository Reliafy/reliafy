// The Calculator's answer at the time typed, worked out by the model at exactly
// that time: the plotted grid is for drawing only. Reading the answer off the
// grid by straight lines between its points was wrong between them — most on a
// steep early curve, where a 90% bound read that way came out optimistic
// (96.3%, at least 86.0% read as 95.6%, at least 89.8%). Pure, so
// `node --test src/` covers it.

// The times to ask the model about: t itself, or — having survived to age s —
// the age s and s + t (R(t | s) = R(s + t) / R(s)).
export function exactTimes(t, cond = 0) {
  if (t == null || !Number.isFinite(t)) return null;
  return cond > 0 ? [cond, cond + t] : [t];
}

// What an answer was asked for: the covariate values (a number typed as text
// is the same number), the time and the age survived to.
export function exactKey(values, t, cond = 0) {
  const norm = Object.fromEntries(Object.keys(values || {}).sort().map((k) => {
    const v = values[k];
    const num = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
    return [k, typeof num === "number" && Number.isFinite(num) ? num : v];
  }));
  return JSON.stringify([norm, t, cond > 0 ? cond : 0]);
}

const at = (curves, fn, i) => {
  const v = curves?.[fn]?.[i];
  return v == null || !Number.isFinite(v) ? null : v;
};

// Each function's value from the model's answer at ``exactTimes`` (the
// evaluate route's ``curves``): as they are, or conditioned on having
// survived to ``cond`` — R(t|s) = R(s+t)/R(s), F = 1 − R, h(t|s) = h(s+t),
// H(t|s) = H(s+t) − H(s), f(t|s) = f(s+t)/R(s).
export function exactValues(curves, cond = 0) {
  if (!curves) return null;
  if (!(cond > 0)) {
    return { sf: at(curves, "sf", 0), ff: at(curves, "ff", 0), hf: at(curves, "hf", 0),
             Hf: at(curves, "Hf", 0), df: at(curves, "df", 0) };
  }
  const sfS = at(curves, "sf", 0);
  const ok = sfS != null && sfS > 0;
  const sf = ok && at(curves, "sf", 1) != null ? at(curves, "sf", 1) / sfS : null;
  const HfS = at(curves, "Hf", 0);
  const Hf1 = at(curves, "Hf", 1);
  return {
    sf,
    ff: sf == null ? null : 1 - sf,
    hf: at(curves, "hf", 1),
    Hf: HfS != null && Hf1 != null ? Hf1 - HfS : null,
    df: ok && at(curves, "df", 1) != null ? at(curves, "df", 1) / sfS : null,
  };
}

// A bound at one time from the confidence route's answer asked ``at`` it:
// { bound, lower, upper } (a one-sided bound has the other side null).
export function exactBound(res) {
  if (!res) return null;
  const first = (a) => (Array.isArray(a) && a[0] != null && Number.isFinite(a[0]) ? a[0] : null);
  return { bound: res.bound, lower: first(res.lower), upper: first(res.upper) };
}

// The answer to show for function ``fn`` from a series' fetched entry
// ({ key, data, error }) when ``key`` is what's asked now:
//   { value, state: "exact" }    the model's own value at the time;
//   { value: null, state: "working" } still on its way (never the last one);
//   { value, state: "approx" }   the model can't be asked (no route, or the
//                                 route refused, as on a signed-out share
//                                 page): read off the drawn curve, said "≈";
//   { value: null, state: "none" } nothing to show.
// ``canAsk``: the model has an evaluate route. ``gridValue``: a function
// giving the drawn curve's value, used only when the model can't be asked.
export function answerFor(entry, key, fn, { canAsk, gridValue = null } = {}) {
  if (canAsk) {
    if (entry?.key === key && entry.data) {
      const v = entry.data[fn];
      return { value: v ?? null, state: v == null ? "none" : "exact" };
    }
    if (!(entry?.key === key && entry.error)) return { value: null, state: "working" };
  }
  const v = gridValue ? gridValue() : null;
  return v == null ? { value: null, state: "none" } : { value: v, state: "approx" };
}
