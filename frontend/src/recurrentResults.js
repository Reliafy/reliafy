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

// An interval as "1.44–2.95"; null when it has no finite bounds (a fit that
// gives no interval).
export const ciText = (ci, sig = 3) => (ci && Number.isFinite(ci[0]) && Number.isFinite(ci[1])
  ? `${formatNumber(ci[0], { sig })}–${formatNumber(ci[1], { sig })}` : null);

const GROWTH = {
  improving: { title: "Improving", note: "failures are slowing" },
  stable: { title: "No clear trend", note: "the data don't show the failure rate changing" },
  deteriorating: { title: "Deteriorating", note: "failures are accelerating" },
};

// The growth verdict and why (#81): the growth parameter's 95% interval
// against its no-trend value, or the value itself for a model built from
// parameters. Null when the model has no growth parameter.
// The growth parameter's symbol, as the parameter table names it (Duane's
// shape is its α).
const growthSymbol = (r) => (r?.model?.id === "duane" || (familyOf(r) === "regression" && r?.baseline?.id === "duane")
  ? "α" : r?.growth_basis?.symbol || "β");

export function growthReading(r) {
  const g = GROWTH[r?.growth];
  if (!g) return null;
  const b = r.growth_basis;
  if (!b) return { title: g.title, text: `${g.note[0].toUpperCase()}${g.note.slice(1)}.` };
  const sym = growthSymbol(r);
  const nul = b.no_trend;
  let why;
  if (b.ci) {
    const [lo, hi] = b.ci;
    const where = lo > nul ? `wholly above ${nul}` : hi < nul ? `wholly below ${nul}` : `includes ${nul}`;
    why = `${sym}'s 95% interval, ${ciText(b.ci)}, is ${where}`;
  } else {
    why = `${sym} = ${formatNumber(b.estimate, { sig: 4 })}${r.from_params ? ", built from parameters (no interval)" : " (this fit gives no interval)"}`;
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

// ---- The model frame (components/model/) ------------------------------------
//
// A repairable model's page has the shared frame's tabs, those that apply:
//   failures  Failures over time: the MCF with the fitted curve [All | By cause]
//   effects   Effects: what changes the failure rate (covariate models only)
//   calc      Calculator: expected failures, failure rate and MTBF
//   plan      Plan ahead [Next failure | Growth projection | Overhaul interval]
//   diag      Diagnostics: the trend, growth and fit checks (a fit to data)
//   data      Data: what it was fitted to, and every parameter

export const REC_TAB_LABELS = {
  failures: "Failures over time",
  effects: "Effects",
  calc: "Calculator",
  plan: "Plan ahead",
  diag: "Diagnostics",
  data: "Data",
};

export const PLAN_LABELS = { next: "Next failure", projection: "Growth projection", overhaul: "Overhaul interval" };

// Whether the model was fitted to event data (not built from parameters).
export const fittedToData = (r) => !r?.from_params && !!r?.mcf?.observed?.x?.length;

// The Plan ahead views that apply: each system's next failure (imperfect
// repair), and on a saved model (``modelId``) the growth projection (data
// models) and the overhaul interval (minimal repair). [{ value, label }].
export function planViews(r, { modelId = null, paramsOnly = false } = {}) {
  const ids = [
    familyOf(r) === "renewal" && (r?.next_failure?.units || []).length > 0 && "next",
    modelId && !paramsOnly && !r?.from_params && "projection",
    modelId && familyOf(r) === "nhpp" && "overhaul",
  ].filter(Boolean);
  return ids.map((value) => ({ value, label: PLAN_LABELS[value] }));
}

// The tabs of a repairable model's page, in order: [{ id, label }].
export function recurrentTabs(r, ctx = {}) {
  const ids = [
    "failures",
    familyOf(r) === "regression" && (r?.coefficients || []).length > 0 && "effects",
    "calc",
    planViews(r, ctx).length > 0 && "plan",
    fittedToData(r) && "diag",
    "data",
  ].filter(Boolean);
  return ids.map((id) => ({ id, label: REC_TAB_LABELS[id] }));
}

// The tabs' ids before the frame (and their old names), to the tab that holds
// them now and the view inside it.
const REC_ALIASES = {
  mcf: ["failures", "all"], cause: ["failures", "cause"], "by cause": ["failures", "cause"],
  cov: ["effects"], covariates: ["effects"],
  next: ["plan", "next"], "next failure": ["plan", "next"],
  overhaul: ["plan", "overhaul"], projection: ["plan", "projection"], "growth projection": ["plan", "projection"],
  gof: ["diag"], stats: ["diag"], trend: ["diag"], diagnostics: ["diag"], calculator: ["calc"],
};

// ``{ tab, view }``: the tab to open for what a link asks (an id, an old id
// or a name), else the first; ``view`` the switch inside it an old id meant.
export function resolveRecurrentTab(tabs, wanted) {
  if (!tabs?.length) return { tab: null, view: null };
  const w = String(wanted || "").trim().toLowerCase();
  const [id, view = null] = REC_ALIASES[w] || [w];
  const hit = tabs.find((t) => t.id === id || t.label.toLowerCase() === id);
  return hit ? { tab: hit.id, view } : { tab: tabs[0].id, view: null };
}

const sig3 = (v) => formatNumber(v, { sig: 3 });
const unitWord = (r) => String(r?.unit || "").trim().toLowerCase();
const withUnitR = (v, r) => `${sig3(v)}${unitWord(r) ? ` ${unitWord(r)}` : ""}`;

// "MTBF now 323 hours (≥ 230 at 90%)": the instantaneous MTBF at the end of
// the data, with the demonstrated lower bound (or the 95% interval).
export function mtbfWords(r) {
  if (r?.mtbf == null || !Number.isFinite(r.mtbf)) return null;
  const dm = r.demonstrated_mtbf;
  const bound = dm?.lower != null
    ? ` (≥ ${sig3(dm.lower)} at ${Math.round((dm.confidence || 0.9) * 100)}%)`
    : ciText(r.mtbf_ci) ? ` (95% ${ciText(r.mtbf_ci)})` : "";
  const who = r.rates_at ? ", average system" : "";
  return `MTBF ${r.from_params ? "at the horizon" : "now"} ${withUnitR(r.mtbf, r)}${bound}${who}`;
}

// The growth shape in a few words: "β 2.06 (95% 1.44–2.95)".
function shapeWords(r) {
  const b = r?.growth_basis;
  if (!b || b.estimate == null) return null;
  return `${growthSymbol(r)} ${formatNumber(b.estimate, { sig: 3 })}${ciText(b.ci) ? ` (95% ${ciText(b.ci)})` : ""}`;
}

// The covariate with the largest effect: "site Inland: failures ×2.2 (1.37–3.40)".
function strongestCoefficient(r) {
  const rows = (r?.coefficients || []).filter((c) => c.ratio != null && c.ratio > 0);
  if (!rows.length) return null;
  const top = rows.reduce((a, b) => (Math.abs(Math.log(b.ratio)) > Math.abs(Math.log(a.ratio)) ? b : a));
  return `${top.name.replace(": ", " ")}: failures ${ratioText(top.ratio)}${top.ratio_ci ? ` (${ratioCiText(top.ratio_ci)})` : ""}`;
}

// The answer line under the model's name: the verdict, the shape, the rate
// now and the data, as short phrases. ``saved`` ends it.
export function recurrentAnswer(r, { saved = null } = {}) {
  const parts = [];
  const add = (p) => p && parts.push(p);
  const fam = familyOf(r);
  const g = GROWTH[r?.growth];
  if (fam === "renewal") {
    add(r.repair_test ? repairTitle(r.repair_test.verdict) : r.model?.name);
    const rest = r.restoration;
    if (rest?.effectiveness != null) {
      add(`repairs remove ${pct(rest.effectiveness)} of the age${rest.effectiveness_ci ? ` (95% ${pct(rest.effectiveness_ci[0])}–${pct(rest.effectiveness_ci[1])})` : ""}`);
    } else if (rest?.ratio != null) {
      add(`gap ratio ${ratioText(rest.ratio)}${rest.ratio_ci ? ` (95% ${ciText(rest.ratio_ci)})` : ""}`);
    }
    const soon = r.next_failure?.units?.[0];
    if (soon?.median != null) add(`next failure: ${soon.system} in about ${withUnitR(soon.median, r)} (median)`);
  } else {
    add(g ? g.title : r?.model?.id === "hpp" || r?.baseline?.id === "hpp" ? "Constant failure rate" : r?.model?.name);
    add(fam === "regression" ? strongestCoefficient(r) : shapeWords(r));
    add(mtbfWords(r));
  }
  add(r?.from_params ? "made from parameters" : dataText(r));
  add(saved);
  return parts.filter(Boolean);
}

// ---- Diagnostics -------------------------------------------------------------

const pText = (p) => (p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`);

// Whether the model assumes a constant failure rate (HPP, or covariates on
// an HPP baseline): then a trend is a fault, not a finding.
export const assumesConstantRate = (r) => r?.model?.id === "hpp" || r?.baseline?.id === "hpp";

// "Is the failure rate changing?" from the Laplace and MIL-HDBK-189C trend
// tests (null: a constant rate). For a model that assumes a constant rate a
// trend is a problem; for the others it is what they model, and no trend
// means a constant-rate model may do as well. { tone, words } or null.
export function trendCheck(r) {
  const tests = (r?.trend_tests || []).filter((t) => t.p_value != null);
  if (!tests.length) return null;
  const sig = tests.filter((t) => t.significant && t.trend !== "no trend");
  const ps = tests.map((t) => `${t.test} ${pText(t.p_value)}`).join(", ");
  if (sig.length) {
    const dir = sig[0].trend === "decreasing" ? "falling: failures are slowing" : "rising: failures are accelerating";
    if (assumesConstantRate(r)) {
      return { tone: "bad", words: `Yes, it's ${dir}, but this model assumes a constant rate: try Crow-AMSAA (${ps}).` };
    }
    return { tone: "good", words: `Yes, it's ${dir}, which this model allows for (${ps}).` };
  }
  if (assumesConstantRate(r)) {
    return { tone: "good", words: `No clear change: a constant rate fits the data (${ps}).` };
  }
  return { tone: "caveat", words: `No clear change (${ps}): a constant-rate model (HPP) may do as well. Compare their AIC.` };
}

// The Duane plot's points: the cumulative MTBF (time ÷ failures per system so
// far) against time, observed and fitted, both for log-log axes (positive
// values only). { observed: { x, y }, fitted: { x, y } }.
export function duanePoints(r) {
  const pick = (xs, ys) => {
    const x = [];
    const y = [];
    (xs || []).forEach((t, i) => {
      const n = ys?.[i];
      if (t > 0 && n > 0 && Number.isFinite(t / n)) { x.push(t); y.push(t / n); }
    });
    return { x, y };
  };
  const observed = pick(r?.mcf?.observed?.x, r?.mcf?.observed?.mcf);
  // The fitted curve over the data's own span: before the first failure its
  // cumulative MTBF runs off to infinity.
  const from = observed.x.length ? observed.x[0] : 0;
  const fitted = pick(r?.mcf?.fitted?.x, r?.mcf?.fitted?.mcf);
  const keep = fitted.x.map((t) => t >= from);
  return { observed, fitted: { x: fitted.x.filter((_, i) => keep[i]), y: fitted.y.filter((_, i) => keep[i]) } };
}

// The least-squares slope of log y on log x: the Duane growth rate (a rising
// cumulative MTBF, a positive slope, is reliability growth).
export function logSlope({ x, y }) {
  const pts = (x || []).map((v, i) => [Math.log(v), Math.log(y[i])]).filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b));
  if (pts.length < 3) return null;
  const mx = pts.reduce((s, [a]) => s + a, 0) / pts.length;
  const my = pts.reduce((s, [, b]) => s + b, 0) / pts.length;
  const sxx = pts.reduce((s, [a]) => s + (a - mx) ** 2, 0);
  if (!sxx) return null;
  return pts.reduce((s, [a, b]) => s + (a - mx) * (b - my), 0) / sxx;
}

// "Is reliability growing?" in words: the model's growth verdict where it has
// one (its shape's interval), else the slope of the data's Duane plot. A
// reading, not a test of the model: no tone.
export function growingCheck(r) {
  const slope = logSlope(duanePoints(r).observed);
  const minus = (v) => formatNumber(v, { sig: 2 }).replace(/^-/, "−");
  const slopeWords = slope == null ? ""
    : ` The cumulative MTBF ${slope > 0.05 ? "rises" : slope < -0.05 ? "falls" : "is about level"} (Duane slope ${minus(slope)}).`;
  const g = GROWTH[r?.growth];
  const b = r?.growth_basis;
  if (g) {
    const lead = r.growth === "improving" ? "Yes" : r.growth === "deteriorating" ? "No, it's getting worse" : "Not clearly";
    let why = "";
    if (ciText(b?.ci)) {
      const [lo, hi] = b.ci;
      const nul = b.no_trend;
      const where = lo > nul ? `wholly above ${nul}` : hi < nul ? `wholly below ${nul}` : `includes ${nul}`;
      why = ` (${growthSymbol(r)}'s 95% interval, ${ciText(b.ci)}, is ${where})`;
    } else if (b?.estimate != null) {
      why = ` (${growthSymbol(r)} = ${formatNumber(b.estimate, { sig: 3 })})`;
    }
    return { words: `${lead}: ${g.note}${why}.${slopeWords}` };
  }
  if (slope == null) return null;
  return {
    words: slope > 0.05 ? `Yes: the time between failures is getting longer.${slopeWords}`
      : slope < -0.05 ? `No: the time between failures is getting shorter.${slopeWords}`
      : `Not clearly: the time between failures is about steady.${slopeWords}`,
  };
}

// "Do the event times follow the model?" (Cramér-von Mises).
export function cvmCheck(r) {
  const c = r?.gof_test;
  if (!c) return null;
  if (c.p_value == null) return { tone: null, words: c.reason || "Not computed for this fit." };
  return c.adequate
    ? { tone: "good", words: `Yes: no evidence against the model (${pText(c.p_value)}, ${c.n_boot} bootstrap samples).` }
    : { tone: "bad", words: `No: the failure times don't follow the model (${pText(c.p_value)}). Try another model.` };
}

// "Does any system fail more than the model expects?" from each system's
// failures against the model's expectation over its own window.
export function systemsCheck(r) {
  const rows = r?.system_residuals || [];
  if (rows.length < 2) return null;
  const top = rows[0];
  if (!(top.excess >= 1)) {
    return { rows, words: "No system stands out: each has about the failures the model expects." };
  }
  return {
    rows,
    words: `${top.system} fails most beyond the model: ${formatNumber(top.failures)} failures where it expects `
      + `${formatNumber(top.expected, { sig: 2 })}. Worth a look as a bad actor.`,
  };
}
