// "Update a baseline with this position's history…" (the Explorer's Modelling tab): a
// Bayesian update of a baseline life model with a few failures (backend/services/bayes_life.py,
// SurPyval's fit_bayes). The baseline is the prior, weighed by how much it's trusted; the
// position's own failures and suspensions move it. These are the dialog's choices and the
// request it sends; the arithmetic is the server's.

// How much to trust the baseline: the words, and the prior width each means (the server's TRUST).
export const TRUST_CHOICES = [
  { value: "close", label: "Trust it closely", within: 0.1, weight: 1.0 },
  { value: "guide", label: "Use it as a guide", within: 0.3, weight: 0.5 },
  { value: "start", label: "Only a starting point", within: 0.6, weight: 0.2 },
];
export const trustWords = (t) => `each number within about ${Math.round(t.within * 100)}%; a fitted baseline counts as ${t.weight === 1 ? "all" : t.weight === 0.5 ? "half" : "a fifth"} of its evidence`;

// Where the baseline comes from.
export const BASELINE_KINDS = [
  { value: "class", label: "Its class's model" },
  { value: "model", label: "A saved model" },
  { value: "params", label: "Numbers I know" },
  { value: "b10", label: "A B10 I believe" },
];

const n = (v) => (v === "" || v == null ? null : Number(v));

// The baseline the server takes, from the dialog's state; null while it's incomplete.
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

// Is the dialog ready to ask the server?
export const ready = (s) => s.kind === "class" || baselineOf(s) !== null;

// The request: {baseline?, trust, exclude, age?}.
export function bodyOf(s) {
  const base = baselineOf(s);
  return { ...(base ? { baseline: base } : {}), trust: s.trust, exclude: [...(s.exclude || [])],
    ...(Number.isFinite(n(s.age)) && n(s.age) > 0 ? { age: n(s.age) } : {}) };
}

// A history row in words: "Failed at 1,440 hours", "Still running at 900 hours".
export function rowWords(r, unit) {
  const u = String(unit || "").toLowerCase();
  const f = (v) => Number(Number(v).toPrecision(4)).toLocaleString("en-AU");
  if (r.c === 2) return `Failed between ${f(r.xl)} and ${f(r.xr)} ${u}`.trim();
  return `${r.c === 0 ? "Failed" : r.status === "removed" ? "Removed" : "Still running"} at ${f(r.x)} ${u}`.trim();
}
