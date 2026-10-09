// Plain words for an RBD block's models (#314): "λ 5e-7/h · MTTR 8 h" or
// "Weibull · η 4,000 h · β 2" on the block, and the means the block dialog
// echoes under its inputs. Display only: the analysis reads the parameters.
import { formatNumber } from "../format.js";

// "h" for Hours, "d" for Days … ; anything else (Cycles, a custom unit) as typed.
const ABBR = {
  second: "s", seconds: "s", minute: "min", minutes: "min", hour: "h", hours: "h",
  day: "d", days: "d", week: "wk", weeks: "wk", month: "mo", months: "mo", year: "y", years: "y",
};
export function unitAbbr(unit) {
  const key = (unit || "").trim().toLowerCase();
  if (!key) return "";
  return ABBR[key] || key;
}

// Hours in one of the diagram's time units (null for cycles or a custom unit).
const HOURS = {
  s: 1 / 3600, min: 1 / 60, h: 1, d: 24, wk: 168, mo: 730, y: 8760,
};
export function hoursPerUnit(unit) {
  return HOURS[unitAbbr(unit)] ?? null;
}

// Lanczos approximation of the gamma function (for a Weibull's mean).
const G = [
  0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
  -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6,
  1.5056327351493116e-7,
];
function gamma(z) {
  if (z < 0.5) return Math.PI / (Math.sin(Math.PI * z) * gamma(1 - z));
  const x = z - 1;
  let a = G[0];
  const t = x + 7.5;
  for (let i = 1; i < 9; i += 1) a += G[i] / (x + i);
  return Math.sqrt(2 * Math.PI) * t ** (x + 0.5) * Math.exp(-t) * a;
}

const param = (model, name) => {
  const p = (model?.params || []).find((q) => q.name === name);
  return p == null ? null : Number(p.value);
};
const distKey = (model) =>
  String(model?.distribution_id || model?.distribution || "").toLowerCase().replace(/[^a-z]/g, "");

// The mean of a plain distribution, or null when it isn't a simple formula.
export function modelMean(model) {
  if (!model || model.kind === "regression") return null;
  const k = distKey(model);
  let m = null;
  if (k === "exponential") {
    const r = param(model, "failure_rate");
    m = r > 0 ? 1 / r : null;
  } else if (k === "weibull") {
    const a = param(model, "alpha");
    const b = param(model, "beta");
    m = a > 0 && b > 0 ? a * gamma(1 + 1 / b) : null;
  } else if (k === "lognormal") {
    const mu = param(model, "mu");
    const s = param(model, "sigma");
    m = mu != null && s != null ? Math.exp(mu + (s * s) / 2) : null;
  } else if (k === "normal") {
    m = param(model, "mu");
  }
  return m != null && Number.isFinite(m) ? m : null;
}

// The median of a lognormal (the "about 12 h" a user usually means), else null.
export function modelMedian(model) {
  if (distKey(model) !== "lognormal") return null;
  const mu = param(model, "mu");
  return mu == null ? null : Math.exp(mu);
}

const GREEK = { alpha: "α", beta: "β", mu: "μ", sigma: "σ", failure_rate: "λ" };
const n3 = (v) => formatNumber(v, { sig: 3 });

// One short line for a life model: "λ 1e-6/h", "Weibull · η 12,000 h · β 1.6",
// "Lognormal · mean 13.6 h". ``short`` leaves out the "Weibull" its η and β
// already say ("η 12,000 h · β 1.6"), for a block's one line on the canvas.
export function lifeLine(model, unit, { short = false } = {}) {
  if (!model) return "";
  const u = unitAbbr(unit);
  const withU = (v) => `${n3(v)}${u ? ` ${u}` : ""}`;
  if (model.kind === "regression") return `${model.distribution} · covariates`;
  const k = distKey(model);
  if (k === "exponential") {
    const r = param(model, "failure_rate");
    // "/h", "/cycle": a custom unit per one of it.
    const per = u.length > 3 ? u.replace(/s$/, "") : u;
    return `λ ${n3(r)}${per ? `/${per}` : ""}`;
  }
  if (k === "weibull") return `${short ? "" : "Weibull · "}η ${withU(param(model, "alpha"))} · β ${n3(param(model, "beta"))}`;
  const mean = modelMean(model);
  if (mean != null) return `${model.distribution} · mean ${withU(mean)}`;
  const ps = (model.params || []).map((p) => `${GREEK[p.name] || p.name} ${n3(p.value)}`).join(" · ");
  return `${model.distribution}${ps ? ` · ${ps}` : ""}`;
}

// "MTTR 8 h" from a repair-time model (the distribution's name when its mean
// isn't a simple formula).
export function repairLine(repair, unit) {
  if (!repair) return "";
  const u = unitAbbr(unit);
  const mean = modelMean(repair);
  return mean != null ? `MTTR ${n3(mean)}${u ? ` ${u}` : ""}` : `repair ${repair.distribution}`;
}

// The block's one line: life, then (repairable) its repair.
export function blockLine(data, unit, repairable) {
  const life = lifeLine(data.model, unit);
  if (!repairable) return life;
  const rep = data.instant_repair ? "instant repair" : repairLine(data.repair, unit);
  return [life, rep].filter(Boolean).join(" · ");
}
