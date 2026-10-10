// Plain-words helpers for a fitted recurrent-event model (#65): parameter
// names in full, the growth verdict and why, a rate in words, and the
// model's family. Pure functions, so `node --test` covers them.
import { formatNumber } from "./format.js";

// "Hours" → "hour", for "per hour"; any other unit as written, lower case.
export function perUnit(unit) {
  const u = String(unit || "").trim().toLowerCase();
  if (!u) return "";
  return /^(seconds|minutes|hours|days|weeks|months|years|cycles|kilometres|miles|operations|rounds)$/.test(u)
    ? u.slice(0, -1)
    : u;
}

// Each model's parameters by their plain names. ``time``: in the model's time
// unit; ``rate``: per unit time; ``pct``: a repair's effectiveness.
const NAMES = {
  crow_amsaa: { alpha: ["Scale α", "time"], beta: ["Shape β"] },
  duane: { alpha: ["Growth shape α"], b: ["Rate constant b"] },
  hpp: { lambda: ["Failure rate λ", "rate"] },
  cox_lewis: { alpha: ["Log-rate intercept α"], beta: ["Log-linear slope β", "rate"] },
  renewal: { alpha: ["Scale α", "time"], beta: ["Shape β"], q: ["Restoration factor q"], rho: ["Repair efficiency ρ"] },
  g1: { alpha: ["Scale α", "time"], beta: ["Shape β"], q: ["Gap factor q"] },
};

// The model's family: "nhpp" (minimal repair), "regression" (covariates) or
// "renewal" (imperfect repair). Results saved before #65 carry none.
export const familyOf = (r) => r?.family || "nhpp";

function namesFor(r) {
  const id = r?.model?.id;
  if (id === "g1") return NAMES.g1;
  if (familyOf(r) === "renewal") {
    // ARI's own parameters are its baseline's.
    return id === "ari" ? { ...NAMES[r.baseline?.id || "crow_amsaa"], rho: NAMES.renewal.rho } : NAMES.renewal;
  }
  if (familyOf(r) === "regression") return NAMES[r.baseline?.id || "crow_amsaa"] || {};
  return NAMES[id] || NAMES.crow_amsaa;
}

// A parameter's plain label, its unit included: "Scale α (hours)".
export function paramLabel(r, name) {
  const spec = namesFor(r)[name];
  const unit = String(r?.unit || "").trim().toLowerCase();
  if (!spec) return name;
  if (spec[1] === "time" && unit) return `${spec[0]} (${unit})`;
  if (spec[1] === "rate" && unit) return `${spec[0]} (per ${perUnit(unit)})`;
  return spec[0];
}

// Shape first: the reading turns on it. The restoration parameter leads an
// imperfect-repair model.
const ORDER = ["q", "rho", "beta", "alpha", "b", "lambda"];
export function orderedParams(r) {
  const params = [...(r?.params || [])];
  if (familyOf(r) === "nhpp" && r?.model?.id === "crow_amsaa") {
    return params.sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));
  }
  if (familyOf(r) === "renewal") return params.sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));
  return params;
}

export const ciText = (ci, sig = 3) => (ci ? `${formatNumber(ci[0], { sig })}–${formatNumber(ci[1], { sig })}` : null);

const GROWTH = {
  improving: { title: "Improving", note: "failures are slowing" },
  stable: { title: "No clear trend", note: "the data don't show the failure rate changing" },
  deteriorating: { title: "Deteriorating", note: "failures are accelerating" },
};

// The growth verdict and why (#81): the growth parameter's 95% interval
// against its no-trend value, or the value itself for a model built from
// parameters. Null when the model has no growth parameter.
export function growthReading(r) {
  const g = GROWTH[r?.growth];
  if (!g) return null;
  const b = r.growth_basis;
  if (!b) return { title: g.title, text: `${g.note[0].toUpperCase()}${g.note.slice(1)}.` };
  const sym = b.symbol || "β";
  const nul = b.no_trend;
  let why;
  if (b.ci) {
    const [lo, hi] = b.ci;
    const where = lo > nul ? `wholly above ${nul}` : hi < nul ? `wholly below ${nul}` : `includes ${nul}`;
    why = `${sym}'s 95% interval, ${ciText(b.ci)}, is ${where}`;
  } else {
    why = `${sym} = ${formatNumber(b.estimate, { sig: 4 })}, built from parameters (no interval)`;
  }
  return { title: g.title, text: `${why}: ${g.note}.` };
}

// A rate ratio as words for a chip: "×2.2", "×0.85".
// A small effect keeps a third figure (×1.03, not ×1).
const ratioSig = (v) => (Math.abs(v - 1) < 0.1 ? 3 : 2);
export const ratioText = (v) => (v == null ? "—" : `×${formatNumber(v, { sig: ratioSig(v) })}`);
export const ratioCiText = (ci) =>
  ci ? `${formatNumber(ci[0], { sig: ratioSig(ci[0]) })}–${formatNumber(ci[1], { sig: ratioSig(ci[1]) })}` : null;

// A covariate effect's tone: green only for a good one (fewer failures),
// amber for more, neutral when the data can't tell.
export const effectTone = (effect) => (effect === "lower" ? "success" : effect === "higher" ? "warning" : "neutral");

// The repair-test verdict as a short title.
const REPAIR = {
  partial: "Partial repair",
  perfect: "As good as new",
  minimal: "As bad as old",
  maximal: "Strongest repair ARI allows",
  unclear: "Repair quality unclear",
  renewal: "As good as new",
  not_renewal: "Not as good as new",
};
export const repairTitle = (verdict) => REPAIR[verdict] || "Repair quality";

// A percentage of a fraction, whole numbers: 0.793 → "79%".
export const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${Math.round(v * 100)}%`);

// What the data are: "4 systems, 30 failures".
export function dataText(r) {
  if (r?.n_systems == null) return null;
  const s = r.n_systems === 1 ? "1 system" : `${r.n_systems.toLocaleString()} systems`;
  const f = r.n_events === 1 ? "1 failure" : `${(r.n_events ?? 0).toLocaleString()} failures`;
  return `${s}, ${f}`;
}
