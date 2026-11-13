// Plain names for SurPyval's parameters (#299, #311): "Scale α (hours)",
// "Failure rate λ (per hour)", "Shape β" — never `alpha` or `failure_rate`.
// Shared by the non-repairable model page's side panel and the block dialog's inputs.
import { MORE_PARAMS } from "./moreModels.js";
import { unitInText } from "./components/unitText.js";

// ``time``: the value is in the model's time unit; ``rate``: per unit time.
export const PARAMS = {
  weibull: { alpha: ["Scale α", "time"], beta: ["Shape β"] },
  exponential: { failure_rate: ["Failure rate λ", "rate"] },
  normal: { mu: ["Mean μ", "time"], sigma: ["Std dev σ", "time"] },
  lognormal: { mu: ["Log-mean μ"], sigma: ["Log-std σ"] },
  gamma: { alpha: ["Shape α"], beta: ["Rate β", "rate"] },
  loglogistic: { alpha: ["Scale α", "time"], beta: ["Shape β"] },
  expo_weibull: { alpha: ["Scale α", "time"], beta: ["Shape β"], mu: ["Exponent μ"] },
  gumbel: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  gumbel_lev: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  logistic: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  rayleigh: { sigma: ["Scale σ", "time"] },
  ...MORE_PARAMS, // #179 / #72 / #63
};

// "Hours" → "hour" for "per hour"; any other unit as written.
export function singular(unit) {
  const u = unitInText(unit);
  return /^(seconds|minutes|hours|days|weeks|months|years|cycles|kilometres|miles|operations|rounds)$/.test(u)
    ? u.slice(0, -1)
    : u;
}

// A parameter's plain label with its unit: paramLabel("weibull", "alpha",
// "Hours") is "Scale α (hours)"; an unknown parameter keeps its own name.
export function paramLabel(distId, name, unit = "") {
  const spec = PARAMS[distId]?.[name];
  if (!spec) return name;
  const u = unit ? unitInText(unit) : "";
  const kind = spec[1];
  const suffix = kind === "time" && u ? ` (${u})` : kind === "rate" && u ? ` (per ${singular(unit)})` : "";
  return spec[0] + suffix;
}

// A fit option's extra quantity (the payload's ``extra_params``, named
// "gamma (offset)", "p (max fraction failing)", "f0 (failed at t=0)") in
// plain words: { label, value }. A share near zero reads "about 0", not
// "3.83e-9".
const EXTRA = {
  gamma: ["Offset γ: no failures before", "time"],
  p: ["Share that can ever fail, p", "share"],
  f0: ["Share failed at time 0, f₀", "share"],
};
export function extraParamView(name, value, unit, fmt) {
  const key = String(name).split(" ")[0];
  const spec = EXTRA[key];
  const v = Number(value);
  if (!spec) return { label: name, value: fmt(value) };
  const u = unit ? unitInText(unit) : "";
  if (spec[1] === "share") {
    const shown = !Number.isFinite(v) ? fmt(value) : Math.abs(v) < 1e-4 ? "about 0%" : `${fmt(v * 100)}%`;
    return { label: spec[0], value: shown };
  }
  return { label: spec[0], value: `${fmt(value)}${u ? ` ${u}` : ""}` };
}
