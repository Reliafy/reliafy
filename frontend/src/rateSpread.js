// A library model's failure rate with its spread across plants. NRC/INL give
// a component's failure rate as a gamma: the rate differs from plant to plant,
// and times to failure are exponential given the rate. The model keeps that
// gamma (results.rate_uncertainty), so its page shows the point value with the
// 5–95% range across plants: the reliability at t lies between exp(-λ95 t) and
// exp(-λ05 t), the mean life between 1/λ95 and 1/λ05. It is the source's
// spread, not a confidence or credible interval from a fit, and says so.
import { formatNumber, singularUnit } from "./format.js";
import { unitInText } from "./components/unitText.js";

export const SPREAD_LABEL = "5–95% across plants (from the source)";

const FAMILY = { gamma: "a gamma", lognormal: "a lognormal" };

// The spread of a result's failure rate, or null: {point, p05, p95, unit, ...}.
export function rateSpread(result) {
  const u = result?.rate_uncertainty;
  if (!u) return null;
  const rate = (result.params || []).find((p) => p.name === "failure_rate");
  const point = Number(rate?.value ?? u.point);
  const p05 = Number(u.p05);
  const p95 = Number(u.p95);
  if (!(point > 0 && p05 >= 0 && p95 > 0)) return null;
  return { ...u, point, p05, p95, unit: result.unit || u.unit || "" };
}

// "Failure rate: 2.53e-9 per hour on average, for 100 feet of pipe. NRC/INL 2020 give it as a gamma
// (shape 0.3, rate 3.96e8 hours): 90% of plants lie between 2.71e-13 and 1.16e-8 per hour."
export function spreadWords(spread) {
  if (!spread) return null;
  const per = `per ${singularUnit(unitInText(spread.unit || "hours"))}`;
  const feet = spread.length_ft != null
    ? `, for ${formatNumber(spread.length_ft)} ${Number(spread.length_ft) === 1 ? "foot" : "feet"} of pipe (the source's rate is per foot)`
    : "";
  const who = spread.source?.name || "The source";
  const params = spread.distribution === "gamma"
    ? ` (shape ${formatNumber(spread.shape)}, rate ${formatNumber(spread.rate)} ${unitInText(spread.unit || "hours")})`
    : spread.distribution === "lognormal" ? ` (mu ${formatNumber(spread.mu)}, sigma ${formatNumber(spread.sigma)} on the log of the rate)` : "";
  return `Failure rate: ${formatNumber(spread.point)} ${per} on average${feet}. ${who} give it as `
    + `${FAMILY[spread.distribution] || "a distribution"} across plants${params}: 90% of plants lie between `
    + `${formatNumber(spread.p05)} and ${formatNumber(spread.p95)} ${per}.`;
}

// The band of an exponential's function at time(s) t from the rate's 5% and 95%:
// {lower, upper}; null for the density (not monotone in the rate).
export function spreadAt(spread, fn, t) {
  if (!spread) return null;
  const at = (rate) => {
    switch (fn) {
      case "sf": return Math.exp(-rate * t);
      case "ff": return 1 - Math.exp(-rate * t);
      case "hf": return rate;
      case "Hf": return rate * t;
      default: return null;
    }
  };
  const a = at(spread.p05);
  const b = at(spread.p95);
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) return null;
  return { lower: Math.min(a, b), upper: Math.max(a, b) };
}

// The band over a grid, in the shape a confidence band has: {x, lower, upper, on, bound}.
export function spreadCurves(spread, fn, x) {
  if (!spread || !x?.length || spreadAt(spread, fn, 1) == null) return null;
  const rows = x.map((t) => spreadAt(spread, fn, Number(t)));
  return { x, lower: rows.map((r) => r?.lower ?? null), upper: rows.map((r) => r?.upper ?? null), on: fn,
           bound: "two-sided", spread: true };
}

// The time at which reliability falls to ``reliability`` (a fraction): -ln R / λ, with
// its range from the rate's 95% (shortest) to its 5% (longest).
export function spreadTime(spread, reliability) {
  if (!spread || !(reliability > 0 && reliability < 1)) return null;
  const h = -Math.log(reliability);
  return { value: h / spread.point, lower: h / spread.p95, upper: spread.p05 > 0 ? h / spread.p05 : null };
}

// The mean life 1/λ with its range 1/λ95 to 1/λ05.
export function spreadMean(spread) {
  if (!spread) return null;
  return { value: 1 / spread.point, lower: 1 / spread.p95, upper: spread.p05 > 0 ? 1 / spread.p05 : null };
}

// "5–95% across plants (from the source): 86,500 to 3.7e12 hours".
export function spreadRangeText(lower, upper, fmt = formatNumber) {
  return `${SPREAD_LABEL}: ${fmt(lower)} to ${upper == null ? "no upper limit" : fmt(upper)}`;
}
