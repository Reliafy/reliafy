// The prior of a fit with a prior ("Fit a life model…" on the Explorer's Modelling tab,
// fitDialog.js): how much to trust it, and a saved model, typed numbers or a B10 as the request
// takes them. The arithmetic is the server's (backend/services/bayes_life.py, SurPyval's fit_bayes).

// How much to trust the baseline: the words, and the prior width each means (the server's TRUST).
export const TRUST_CHOICES = [
  { value: "close", label: "Trust it closely", within: 0.1, weight: 1.0 },
  { value: "guide", label: "Use it as a guide", within: 0.3, weight: 0.5 },
  { value: "start", label: "Only a starting point", within: 0.6, weight: 0.2 },
];

const n = (v) => (v === "" || v == null ? null : Number(v));

// The baseline the server takes, from the form's state; null while it's incomplete.
export function baselineOf(s) {
  if (s.kind === "class") return null; // the server's default: the position class's model
  if (s.kind === "model") return s.modelId ? { model_id: s.modelId } : null;
  if (s.kind === "params") {
    const names = { weibull: ["alpha", "beta"], exponential: ["failure_rate"], lognormal: ["mu", "sigma"] }[s.distribution] || [];
    if (names.some((k) => !Number.isFinite(n(s.params?.[k])))) return null;
    return { distribution: s.distribution, unit: s.unit, params: names.map((k) => ({ name: k, value: n(s.params[k]) })) };
  }
  const v = n(s.b10?.value), lo = n(s.b10?.low), hi = n(s.b10?.high);
  if (![v, lo, hi].every(Number.isFinite) || !(lo < v && v < hi)) return null;
  return { b10: { value: v, low: lo, high: hi }, shape: { low: n(s.shape?.low) ?? 1.2, high: n(s.shape?.high) ?? 4 }, unit: s.unit };
}
