// The models of #179 / #72 / #63 in the fit wizard and on the result page:
// one-line descriptions, plain parameter names, the picker's grouping (rare
// models under "More models") and the Group by column of a shared-frailty fit.

// One plain line each, under the model picker.
export const MORE_DESCRIPTIONS = {
  beta: "Life as a fraction between 0 and 1 — a share of rated life, a proportion degraded.",
  beta4: "A Beta between a floor and a ceiling estimated from the data.",
  uniform: "Equally likely anywhere between a smallest and a largest value.",
  discretized_lognormal: "A lognormal on whole counts 1, 2, 3… — cycles or demands to failure.",
  discretized_gamma: "A gamma on whole counts 1, 2, 3… — cycles or demands to failure.",
  discretized_loglogistic: "A log-logistic on whole counts 1, 2, 3… — cycles or demands to failure.",
  royston_parmar: "A flexible spline curve for data no single distribution follows.",
  additive_hazards: "Covariates add to the failure rate, with no baseline shape assumed.",
  proportional_odds: "Covariates scale the odds of failure, with no baseline shape assumed.",
  buckley_james: "Covariates speed up or slow down time, with no distribution assumed.",
  weibull_frailty: "Weibull PH where units of one site or batch share a hidden risk.",
  exponential_frailty: "Exponential PH where units of one site or batch share a hidden risk.",
  lognormal_frailty: "Lognormal PH where units of one site or batch share a hidden risk.",
  gamma_frailty: "Gamma PH where units of one site or batch share a hidden risk.",
  cox_frailty: "Cox PH where units of one site or batch share a hidden risk.",
};

// Plain names for the parameters (as LifeSummary's PARAMS: [label, "time"
// when the value is in the model's time unit, "rate" when per unit time]).
const RP = {
  gamma_0: ["Spline intercept γ₀"],
  gamma_1: ["Spline term γ₁"],
  gamma_2: ["Spline term γ₂"],
  gamma_3: ["Spline term γ₃"],
};
export const MORE_PARAMS = {
  beta: { alpha: ["Shape α"], beta: ["Shape β"] },
  beta4: { alpha: ["Shape α"], beta: ["Shape β"], a: ["Lower end a", "time"], b: ["Upper end b", "time"] },
  uniform: { a: ["Lower end a", "time"], b: ["Upper end b", "time"] },
  discretized_lognormal: { mu: ["Log-mean μ"], sigma: ["Log-std σ"] },
  discretized_gamma: { alpha: ["Shape α"], beta: ["Rate β"] },
  discretized_loglogistic: { alpha: ["Scale α"], beta: ["Shape β"] },
  royston_parmar: RP,
};

// The picker's sections: the everyday groups first, then everything flagged
// ``more`` in one "More models" section at the end.
export function pickerGroups(options, covariateList) {
  const everyday = options.filter((d) => !d.more);
  const groups = covariateList
    ? [
        ["Proportional hazards", everyday.filter((d) => !d.effect || d.effect === "hazard")],
        ["Accelerated failure time", everyday.filter((d) => d.effect === "aft")],
        ["Proportional odds", everyday.filter((d) => d.effect === "odds")],
        ["Additive hazards", everyday.filter((d) => d.effect === "additive")],
      ]
    : [
        ["Continuous", everyday.filter((d) => !d.nonparametric && !d.discrete)],
        ["Discrete", everyday.filter((d) => d.discrete)],
        ["Non-parametric", everyday.filter((d) => d.nonparametric)],
      ];
  return [...groups, ["More models", options.filter((d) => d.more)]].filter(([, list]) => list.length);
}

// The column mapping sent with a fit: the Group by column for a
// shared-frailty model, and never for any other (the server refuses it).
export function withGroup(mapping, selected, group) {
  const { group: _drop, ...rest } = mapping || {};
  return selected?.frailty && group ? { ...rest, group } : rest;
}

// What stops a fit before it's sent, in words (null when nothing does).
export function groupProblem(selected, group) {
  return selected?.frailty && !group ? "Choose the Group by column — the site, batch or unit each row belongs to." : null;
}
