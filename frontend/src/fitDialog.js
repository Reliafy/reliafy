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
  { value: "library", label: "A library record" },
  { value: "params", label: "Numbers I know" },
  { value: "around", label: "Around a value, between two bounds" },
  { value: "b10", label: "A B10 I believe" },
];

// Trust (a weight or a width) applies where the prior is evidence or numbers; around/between and a
// B10 state their own ranges.
export const showsTrust = (kind) => ["class", "model", "params"].includes(kind);

// "Around a value, between two bounds": the rows for each distribution (a parameter left empty is
// the data's alone; an exponential's by its mean life or its rate).
export const AROUND_PARAMS = {
  weibull: [["alpha", "Characteristic life (alpha)"], ["beta", "Shape (beta)"]],
  exponential: [["mean", "Mean life"], ["failure_rate", "Failure rate"]],
  lognormal: [["mu", "mu (log of the median)"], ["sigma", "sigma (spread)"]],
};
const aroundDist = (s) => (s.distribution && s.distribution !== "best" ? s.distribution : "weibull");
const num = (v) => (v === "" || v == null ? null : Number(v));

// The rows typed, as the server takes them ({name: {about?, between: [lo, hi]}}); null with a
// problem in words.
export function aroundParams(s) {
  const out = {};
  for (const [name, label] of AROUND_PARAMS[aroundDist(s)]) {
    const r = s.around?.[name] || {};
    const about = num(r.about), lo = num(r.lo), hi = num(r.hi);
    if (about == null && lo == null && hi == null) continue;
    if (lo == null || hi == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return { problem: `Give ${label} both bounds, or leave it empty.` };
    if (!(lo < hi)) return { problem: `For ${label}, the low bound must be below the high one.` };
    if (about != null && !(lo < about && about < hi)) return { problem: `For ${label}, “about” must lie between the bounds.` };
    out[name] = { ...(about != null ? { about } : {}), between: [lo, hi] };
  }
  if (aroundDist(s) === "exponential" && out.mean && out.failure_rate) return { problem: "Give the mean life or the failure rate, not both." };
  if (!Object.keys(out).length) return { problem: "Give at least one parameter's bounds (the others are left to the data)." };
  return { params: out };
}

// The Data dropdown's options, each with its counts where they're known.
export function dataOptions({ positionCounts = null, cls = null, hasClass = true } = {}) {
  const tail = (c) => (c ? ` (${countsWords(c)})` : "");
  return [
    { value: "position", label: `This position's history${tail(positionCounts)}` },
    ...(hasClass ? [
      { value: "class", label: `The class's pooled history${cls ? ` (${cls.positions} position${cls.positions === 1 ? "" : "s"}, ${countsWords(cls)})` : ""}` },
      { value: "both", label: "Both: this position's, with the class's as a prior" },
    ] : []),
  ];
}

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
  if (method === "bayes" && priorKind === "around") return aroundParams(s).problem || null;
  if (method === "bayes" && priorKind === "library") {
    if (!s.recordId) return "Pick a library record.";
    if (s.libMissing?.length) return `Give the record's ${s.libMissing.join(", ")}.`;
    const lo = num(s.libShape?.lo), hi = num(s.libShape?.hi);
    if ((lo != null || hi != null) && !(lo > 0 && hi > lo)) return "The shape's bounds must be low < high, both above 0.";
    return null;
  }
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
    out.prior = priorKind === "class" ? { kind: "class" }
      : priorKind === "around" ? { kind: "around", distribution: aroundDist(s), unit: s.unit, params: aroundParams(s).params || {} }
        : priorKind === "library" ? { kind: "library", record_id: s.recordId,
          ...(s.libCov && Object.keys(s.libCov).length ? { covariates: s.libCov } : {}),
          ...(aroundDist(s) !== "exponential" && num(s.libShape?.lo) > 0 && num(s.libShape?.hi) > 0
            ? { shape: [num(s.libShape.lo), num(s.libShape.hi)] } : {}) }
        : { kind: priorKind, ...(baselineOf({ ...s, kind: priorKind }) || {}) };
  }
  if (Number(s.age) > 0) out.age = Number(s.age);
  return out;
}

// The preview's key: whenever the request (or what's missing) changes.
export const previewKey = (s) => JSON.stringify({ body: bodyOf(s), problem: problem(s) });

// The Data choices as the dialog's chips (short: the grid's label says "Data").
export const DATA_CHIPS = [
  { value: "position", label: "This position", title: "This position's own history" },
  { value: "class", label: "The class", title: "Every position of the same class, pooled" },
  { value: "both", label: "Both", title: "This position's history, with the class's other positions' history as a prior" },
];

// The method's one line, the result pane's subtitle.
export const METHOD_LINE = {
  mle: "Maximum likelihood: the numbers that make the data most likely, with 95% confidence bounds.",
  bayes: "Bayesian: the prior moved by the data, with 90% credible intervals.",
};

// "For": every failure of the position, one mode by name, or "3 of 8 picked".
export function forWords(modes = [], picked = []) {
  if (!picked.length || !modes.length) return "All failures of this position";
  if (picked.length === 1) return modes.find((m) => m.id === picked[0])?.text || "1 picked";
  return `${picked.length} of ${modes.length} picked`;
}

// The history's one-line summary: "2 failures, 1 suspension".
export function countsWords(counts) {
  if (!counts) return "";
  const f = counts.failures || 0;
  const s = counts.suspensions || 0;
  return `${f} failure${f === 1 ? "" : "s"}, ${s} suspension${s === 1 ? "" : "s"}`;
}

// A history row as the table shows it: when (the day it ended, or began if still running),
// what happened, its age in the result's unit, and failure or suspension.
export function historyRow(r, unit = "") {
  const u = String(unit || "").toLowerCase();
  const n = (v) => Number(Number(v).toPrecision(4)).toLocaleString("en-AU");
  const age = r.c === 2 ? `${n(r.xl)}–${n(r.xr)}` : n(r.x);
  const what = r.c === 1 ? (r.status === "removed" ? "Removed" : "Still running") : (r.failure_mode || "Failed");
  return { when: r.to || r.from || "", what: [what, r.item, r.position].filter(Boolean).join(" · "), age: `${age}${u ? ` ${u}` : ""}`,
    kind: r.c === 1 ? "Suspension" : "Failure" };
}

// A refusal's words as shown: the distribution named as everywhere else in the
// app ("a plain weibull fit" → "a plain Weibull fit"), the server's id
// otherwise left as it came.
export function refusalWords(text) {
  return String(text ?? "").replace(/\b(plain|a|an) (weibull|exponential|lognormal|normal|gamma|gumbel|logistic|loglogistic|beta|uniform)( fit| model)\b/g,
    (_, pre, d, post) => `${pre} ${d[0].toUpperCase()}${d.slice(1)}${post}`);
}

// The link a refusal offers: a plain fit that can't be done switches to a fit with a prior.
export const refusalSwitch = (method) => (method === "mle" ? { to: "bayes", label: "Fit with a prior instead" } : null);

// What a library record as the prior means for the distribution chosen, in one line.
export function libraryPriorWords(distribution, record = null) {
  if (record?.kind === "life") {
    const bounded = (record.params || []).some((p) => Array.isArray(p.ci));
    return `A snapshot of a saved ${record.family || ""} model: the fit is in its family and unit, each parameter about its value`
      + (bounded ? ", between the record's bounds." : ", within about 30% (the record has no bounds).");
  }
  if (distribution === "weibull" || distribution === "lognormal") {
    return "The record gives a failure rate: for this distribution it's a prior on the mean life (one over the rate), "
      + `with the ${distribution === "weibull" ? "shape" : "spread"} between the bounds below (0.5 to 5 if left empty).`;
  }
  return "On an exponential the record's distribution is the prior exactly (conjugate: worked out in closed form).";
}

// The form as it opens: `start` (what the opener chose for it: Refit…, a library record from
// Use as a prior…) and `link`, the row a refit replaces (its failure modes kept).
export function initialFit(start = {}, link = null) {
  return {
    data: start.data || "position", method: start.method || "mle", priorKind: start.priorKind || "class",
    modelId: start.modelId || null, distribution: start.priorKind === "library" ? "exponential" : "weibull", trust: "guide", unit: "hours",
    params: {}, b10: {}, shape: {}, around: {}, recordId: start.recordId || null, libShape: {},
    // The library record's covariates (a pipe's length, the clock...) and the labels of those still needed.
    libCov: start.covariates || {}, libMissing: [],
    modes: (link?.failure_modes || []).map((f) => f.id), exclude: new Set(), age: "",
  };
}

// The fit's own choices, in a form that compares: blanks dropped (a number typed and cleared
// again is no change), sets and lists sorted. The age asked about is a question, not the fit.
function settled(v) {
  if (v instanceof Set) return settled([...v]);
  if (Array.isArray(v)) return [...v].map(settled).sort();
  if (v && typeof v === "object") {
    const out = {};
    for (const k of Object.keys(v).sort()) {
      const x = settled(v[k]);
      if (x === "" || x == null || (typeof x === "object" && !Array.isArray(x) && !Object.keys(x).length)) continue;
      out[k] = x;
    }
    return out;
  }
  return typeof v === "string" ? v.trim() : v;
}

// Has anything in the fit been changed since it opened? Leaving it for another row asks
// "Discard this fit?" only then.
export function fitChanged(opened, now) {
  // libMissing is worked out from the record's covariates, not chosen.
  const { age: _a, libMissing: _m, ...a } = opened || {};
  const { age: _b, libMissing: _n, ...b } = now || {};
  return JSON.stringify(settled(a)) !== JSON.stringify(settled(b));
}

// The pane's heading: what it does, then the position it's for.
export const fitTitle = (link = null) => (link ? "Refit the life model" : "Fit a life model");
