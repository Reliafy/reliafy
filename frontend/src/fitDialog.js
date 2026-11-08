// "Fit a life model…" on the Modelling tab (Derryn, 9 Nov 2026: "'From history' needs to include
// the class and Bayesian"): which data (this position's history, the class's pooled history, or
// both: this position's with the class's as the prior) and which method (a plain fit, or with a
// prior: the class's history, a saved model, numbers you know or a B10 you believe). These are the
// dialog's rules and the request it sends; the arithmetic is the server's (fit_life.py).

import { baselineOf } from "./bayesUpdate.js";

export const DATA_CHOICES = [
  { value: "position", label: "This position's history" },
  { value: "class", label: "The class's pooled history" },
  { value: "both", label: "Both: this position's, with the class's as a prior" },
];
export const METHOD_CHOICES = [
  { value: "mle", label: "Plain fit" },
  { value: "bayes", label: "With a prior" },
];
export const PRIOR_CHOICES = [
  { value: "class", label: "The class's history" },
  { value: "model", label: "A saved model" },
  { value: "params", label: "Numbers I know" },
  { value: "b10", label: "A B10 I believe" },
];

// The method and prior the data choice allows: Both is always with the class's history as the
// prior; the class's pooled history as the data can't also be the prior.
export function effective(s) {
  if (s.data === "both") return { method: "bayes", priorKind: "class" };
  if (s.method !== "bayes") return { method: "mle", priorKind: null };
  const priorKind = s.data === "class" && s.priorKind === "class" ? "model" : s.priorKind || "class";
  return { method: "bayes", priorKind };
}

// The prior choices offered for the data chosen.
export const priorChoices = (data) => PRIOR_CHOICES.filter((p) => !(data === "class" && p.value === "class"));

// Why the dialog can't ask yet (null once it can).
export function problem(s) {
  const { method, priorKind } = effective(s);
  if (method === "bayes" && s.distribution === "best" && (priorKind === "class")) return "“Best of” is for a plain fit: choose a distribution.";
  if (method === "bayes" && priorKind !== "class" && !baselineOf({ ...s, kind: priorKind })) {
    return priorKind === "model" ? "Pick the model to use as the prior." : priorKind === "params"
      ? "Give the prior's numbers." : "Give the B10 with the values you'd be surprised under and over.";
  }
  return null;
}

// The request: {data, method, prior?, distribution, trust?, failure_mode_ids, exclude, age?}.
export function bodyOf(s) {
  const { method, priorKind } = effective(s);
  const out = { data: s.data, method, distribution: s.distribution || "weibull", failure_mode_ids: s.modes || [],
    exclude: [...(s.exclude || [])] };
  if (method === "bayes") {
    out.trust = s.trust || "guide";
    out.prior = priorKind === "class" ? { kind: "class" } : { kind: priorKind, ...(baselineOf({ ...s, kind: priorKind }) || {}) };
  }
  if (Number(s.age) > 0) out.age = Number(s.age);
  return out;
}

// The preview's key: whenever the request (or what's missing) changes.
export const previewKey = (s) => JSON.stringify({ body: bodyOf(s), problem: problem(s) });
