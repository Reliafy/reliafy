// Plain-words helpers for a fitted recurrent-event model (#65): parameter
// names in full, the growth verdict and why, a rate in words, and the
// model's family. Pure functions, so `node --test` covers them.
import { formatNumber } from "./format.js";
import { ciPct } from "./levels.js";

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
  renewal: { alpha: ["Scale α", "time"], beta: ["Shape β"], q: ["Share of age kept q (a repair restores 1 − q)"],
    rho: ["Repair efficiency ρ"] },
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

// A rate parameter shown per 1,000 (or 10,000…) units of time when it is
// small, so it never reads in scientific notation: an HPP rate of 9.81e-4 per
// hour is "0.981 per 1,000 hours". { label, value, ci, scale }.
export function scaledParam(r, p) {
  const spec = namesFor(r)[p?.name];
  const v = Number(p?.value);
  let k = 1;
  if (spec?.[1] === "rate" && Number.isFinite(v) && v !== 0) {
    while (Math.abs(v) * k < 0.1 && k < 1e9) k *= 10;
    if (k > 1 && k < 1000) k = 1000;
  }
  if (k === 1) return { label: paramLabel(r, p.name), value: p.value, ci: p.ci, scale: 1 };
  const unit = String(r?.unit || "").trim().toLowerCase();
  const per = `per ${k.toLocaleString("en-US")} ${unit || "time units"}`;
  return {
    label: `${spec[0]} (${per})`,
    value: v * k,
    ci: Array.isArray(p.ci) ? p.ci.map((c) => (c == null ? c : c * k)) : p.ci,
    scale: k,
  };
}

// A failure rate in words, per 1,000 (or 10,000…) units of time when it is
// small, never in scientific notation: 9.821e-4 per hour reads
// { value: "0.9821", per: "per 1,000 hours" }. ``unit`` is plural ("hours").
export function rateScale(rate) {
  const v = Number(rate);
  let k = 1;
  if (Number.isFinite(v) && v !== 0) {
    while (Math.abs(v) * k < 0.1 && k < 1e9) k *= 10;
    if (k > 1 && k < 1000) k = 1000;
  }
  return k;
}

export function rateWords(rate, unit, sig = 4, k = rateScale(rate)) {
  const v = Number(rate);
  const u = String(unit || "").trim();
  if (rate == null || !Number.isFinite(v)) return { value: "—", per: "", k: 1 };
  const per = k === 1
    ? (u ? `per ${u.replace(/s$/, "")}` : "")
    : `per ${k.toLocaleString("en-US")} ${u || "time units"}`;
  return { value: formatNumber(v * k, { sig }), per, k };
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

// What a growth parameter means, without a judgement: which way the failure
// rate moves as time goes on on either side of its no-trend value.
const growthMeaning = (r, sym, nul) => (r?.growth_basis?.parameter === "beta" && nul === 0
  ? `${sym} above 0 means failures come faster as time goes on; below 0, slower.`
  : `${sym} above ${nul} means failures come faster as time goes on; below ${nul}, slower.`);

// The growth parameter's symbol, as the parameter table names it (Duane's
// shape is its α).
const growthSymbol = (r) => (r?.model?.id === "duane" || (familyOf(r) === "regression" && r?.baseline?.id === "duane")
  ? "α" : r?.growth_basis?.symbol || "β");

// The growth shape's evidence and what it means, no verdict (the analyst
// decides): "β 1.35 (90% range 1.02–1.80). β above 1 means ...". Null when the
// model has no growth parameter.
export function growthReading(r) {
  const b = r?.growth_basis;
  if (!b || b.estimate == null) return null;
  const sym = growthSymbol(r);
  const est = formatNumber(b.estimate, { sig: 3 });
  let what;
  if (b.ci && ciText(b.ci)) what = `${sym} ${est} (${ciPct(r)} two-sided range ${ciText(b.ci)})`;
  else what = `${sym} ${est}${r.from_params ? " (built from parameters, no range)" : " (this fit gives no range)"}`;
  return { title: "Shape of the failure rate", text: `${what}. ${growthMeaning(r, sym, b.no_trend)}` };
}

// A rate ratio as words for a chip: "×2.2", "×0.85".
// A small effect keeps a third figure (×1.03, not ×1).
const ratioSig = (v) => (Math.abs(v - 1) < 0.1 ? 3 : 2);
export const ratioText = (v) => (v == null ? "—" : `×${formatNumber(v, { sig: ratioSig(v) })}`);
export const ratioCiText = (ci) =>
  ci ? `${formatNumber(ci[0], { sig: ratioSig(ci[0]) })}–${formatNumber(ci[1], { sig: ratioSig(ci[1]) })}` : null;

// A covariate effect carries no good/bad colour: more or fewer failures is for the analyst to judge.
export const effectTone = () => "neutral";

// The repair-test verdict as a short title.
// The verdict follows the restoration interval (an end is named only when the
// interval includes it): "maybe_minimal" is an estimate well inside with the
// interval reaching as bad as old.
const REPAIR = {
  partial: "Partial repair",
  perfect: "As good as new",
  minimal: "As bad as old",
  maybe_minimal: "Partial repair, can't rule out as bad as old",
  maybe_perfect: "Partial repair, can't rule out as good as new",
  maximal: "Strongest repair ARI allows",
  unclear: "Repair quality unclear",
  renewal: "As good as new",
  not_renewal: "Not as good as new",
};
export const repairTitle = (verdict) => REPAIR[verdict] || "Repair quality";

// A percentage of a fraction, whole numbers: 0.793 → "79%".
export const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${Math.round(v * 100)}%`);

// A repair's restored share's interval as shown: a share runs from 0% (as bad
// as old) to 100% (as good as new), so the range is shown inside those ends,
// and an end the interval reaches (or passes) is named in words. The fit's
// own interval on q is unbounded, so it can pass either end; the parameter
// table keeps it as fitted. "0%–70%, reaching as bad as old". null without one.
export function restoresRange(rest) {
  const ci = rest?.effectiveness_ci;
  if (!ci || !Number.isFinite(ci[0]) || !Number.isFinite(ci[1])) return null;
  const top = rest?.parameter === "rho" && /failure rate/.test(rest?.what || "") ? "the most a repair can remove" : "as good as new";
  const lo = Math.min(Math.max(ci[0], 0), 1);
  const hi = Math.min(Math.max(ci[1], 0), 1);
  const old = ci[0] <= 0;
  const fresh = ci[1] >= 1;
  const reach = old && fresh ? `from as bad as old to ${top}` : old ? "reaching as bad as old" : fresh ? `reaching ${top}` : "";
  return { lo, hi, text: `${pct(lo)}–${pct(hi)}`, reach, words: `${pct(lo)}–${pct(hi)}${reach ? `, ${reach}` : ""}` };
}

// Which side and method each bound on a repairable model's page is, in
// words: the parameters' intervals (two-sided), and the MTBF's "≥" (one-sided,
// the demonstrated MTBF) with its method. [sentences].
export function boundsWords(r) {
  const lv = ciPct(r);
  const out = [];
  const params = r?.params || [];
  if (params.some((p) => p.ci)) {
    out.push(`Parameter intervals are ${lv} two-sided, from the fit's information (Wald; a positive parameter's on the log scale).`);
    const q = params.find((p) => p.ci && p.ci_method === "lr");
    if (q) {
      out.push(`${paramLabel(r, q.name).split(" (")[0]}'s interval is a profile-likelihood one, so it can run past 0 or 1; `
        + "the restored share beside it is shown between 0% and 100%.");
    }
  }
  const dm = r?.demonstrated_mtbf;
  if (dm?.lower != null) {
    const how = dm.method === "crow" ? "Crow's exact method (MIL-HDBK-189C)" : "the Wald (delta) method";
    out.push(`MTBF now "≥" is a ${Math.round((dm.confidence || 0.9) * 100)}% one-sided lower bound (the demonstrated MTBF), by ${how}; `
      + `its ${lv} interval is two-sided.`);
  }
  return out;
}

// "This is 1.7× the longest record in the data (11,800 hours): ..." for an
// answer past the end of the data (the server's ``beyond_data``). ``unit`` in
// words ("hours").
export function beyondDataWords(beyond, unit = "") {
  if (!beyond?.data_end) return null;
  const end = `${formatNumber(beyond.data_end)}${unit ? ` ${unit}` : ""}`;
  return `This is ${formatNumber(beyond.times, { sig: 2 })}× the longest record in the data (${end}). The data stop `
    + "there, so the answer assumes the fitted trend carries on unchanged past them.";
}

// What the data are: "4 systems, 30 failures".
export function dataText(r) {
  if (r?.n_systems == null) return null;
  const f = r.n_events === 1 ? "1 failure" : `${(r.n_events ?? 0).toLocaleString()} failures`;
  const sub = r.subset;
  if (sub?.systems?.length) {
    const of = sub.of ? ` of ${sub.of.toLocaleString()}` : "";
    const s = sub.systems.length === 1 ? `${sub.systems[0]} alone (1${of} systems)` : `${sub.systems.length}${of} systems`;
    return `${s}, ${f}`;
  }
  const s = r.n_systems === 1 ? "1 system" : `${r.n_systems.toLocaleString()} systems`;
  return `${s}, ${f}`;
}

// Where each system's record ends (``termination.ends``: [{end, systems}],
// most systems first), so a cut-short record is visible: "every system to
// 1,096 days", or "6 systems to 1,096 days; CV-03-GB to 995 days". Many
// different ends: their range. Null when the fit doesn't say.
export function recordEndsText(ends, r) {
  if (!Array.isArray(ends) || !ends.length) return null;
  const u = unitWord(r) ? ` ${unitWord(r)}` : "";
  const at = (v) => `${formatNumber(v, { sig: 6 })}${u}`;
  if (ends.length === 1) {
    return ends[0].systems.length === 1 ? `${ends[0].systems[0]} to ${at(ends[0].end)}` : `every system to ${at(ends[0].end)}`;
  }
  if (ends.length > 3) {
    const all = ends.map((g) => g.end);
    return `each system to its own end of record, from ${at(Math.min(...all))} to ${at(Math.max(...all))}`;
  }
  const who = (g) => (g.systems.length <= 2 ? g.systems.join(" and ") : `${g.systems.length} systems`);
  return ends.map((g) => `${who(g)} to ${at(g.end)}`).join("; ");
}

// The link that fits some of a saved model's systems by themselves: the new
// repairable model flow, started from the model's data and settings.
export function fitSystemsHref(modelId, systems = []) {
  const q = new URLSearchParams({ from: modelId });
  systems.forEach((s) => q.append("system", s));
  return `/models/recurrent/new?${q}`;
}

// How the record ends, said on every fit to data: "time-terminated at 1,000
// hours" (an end of test or end of record was given) or "failure-terminated:
// ended at the last failure (940 hours)". A fit saved before this was said
// shows it only when its warning tells (null otherwise).
export function terminationText(r) {
  if (!r || r.from_params) return null;
  const term = r.termination
    || ((r.warnings || []).some((w) => w.id === "no_record_end") ? { kind: "failure", end: r.end_of_observation } : null);
  if (!term) return null;
  const at = term.end != null && Number.isFinite(term.end) ? withUnitR(term.end, r) : null;
  const one = r.n_systems === 1;
  if (term.kind === "time") {
    const ends = recordEndsText(term.ends, r);
    if (ends) return `time-terminated: ${ends}`;
    if (!at) return "time-terminated";
    return one ? `time-terminated at ${at}` : `time-terminated: each system to its end of record (the latest ${at})`;
  }
  if (one) return `failure-terminated: ended at the last failure${at ? ` (${at})` : ""}`;
  return "failure-terminated: each system ends at its last failure";
}

// ---- The model frame (components/model/) ------------------------------------
//
// A repairable model's page has the shared frame's tabs, those that apply:
//   failures  Failures over time: the MCF with the fitted curve [All | By cause]
//   effects   Effects: what changes the failure rate (covariate models only)
//   calc      Calculator: expected failures, failure rate and MTBF
//   plan      Plan ahead [Next failure | Growth projection | Overhaul interval | Overhaul and replace]
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

export const PLAN_LABELS = { next: "Next failure", projection: "Growth projection", overhaul: "Overhaul interval",
  replace: "Overhaul and replace" };

// Whether the model was fitted to event data (not built from parameters).
export const fittedToData = (r) => !r?.from_params && !!r?.mcf?.observed?.x?.length;

// The Plan ahead views that apply: each system's next failure (imperfect
// repair), and on a saved model (``modelId``) the growth projection (data
// models) and the overhaul interval (minimal repair). [{ value, label }].
// A deteriorating fleet's question is when to overhaul, so that comes first;
// a growth test's is the projection.
export function planViews(r, { modelId = null, paramsOnly = false } = {}) {
  const projection = modelId && !paramsOnly && !r?.from_params && "projection";
  const overhaul = modelId && familyOf(r) === "nhpp" && "overhaul";
  // Overhaul every X, replace after N (Strategy › Overhaul and replace, the same tool): beside the overhaul interval.
  const replace = overhaul && "replace";
  const ids = [
    familyOf(r) === "renewal" && (r?.next_failure?.units || []).length > 0 && "next",
    ...(r?.growth === "deteriorating" ? [overhaul, replace, projection] : [projection, overhaul, replace]),
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
// the data, with the demonstrated lower bound (or the interval, 90%).
export function mtbfWords(r) {
  if (r?.mtbf == null || !Number.isFinite(r.mtbf)) return null;
  const dm = r.demonstrated_mtbf;
  const bound = dm?.lower != null
    ? ` (≥ ${sig3(dm.lower)} at ${Math.round((dm.confidence || 0.9) * 100)}%, one-sided)`
    : ciText(r.mtbf_ci) ? ` (${ciPct(r)} two-sided ${ciText(r.mtbf_ci)})` : "";
  // A covariate model: each level's MTBF, not a made-up average system.
  const groups = (r.rates_by_group || []).filter((g) => g.mtbf != null);
  if (groups.length) {
    return `MTBF now ${groups.map((g) => `${g.label} ${withUnitR(g.mtbf, r)}`).join(", ")}`;
  }
  const who = r.rates_at ? ", at the fleet's average covariates" : "";
  return `MTBF ${r.from_params ? "at the horizon" : "now"} ${withUnitR(r.mtbf, r)}${bound}${who}`;
}

// The growth shape in a few words: "β 2.06 (90% 1.44–2.95)".
function shapeWords(r) {
  const b = r?.growth_basis;
  if (!b || b.estimate == null) return null;
  // A small log-linear slope reads per 1,000 (or more) units of time.
  const d = scaledParam(r, { name: b.parameter, value: b.estimate, ci: b.ci });
  const per = d.scale > 1 ? ` per ${d.scale.toLocaleString("en-US")} ${unitWord(r) || "time units"}` : "";
  return `${growthSymbol(r)} ${formatNumber(d.value, { sig: 3 })}${per}${ciText(d.ci) ? ` (${ciPct(r)} two-sided ${ciText(d.ci)})` : ""}`;
}

// The covariate with the largest effect: "site Inland: failures ×2.2 (1.37–3.40)".
function strongestCoefficient(r) {
  const rows = (r?.coefficients || []).filter((c) => c.ratio != null && c.ratio > 0);
  if (!rows.length) return null;
  const top = rows.reduce((a, b) => (Math.abs(Math.log(b.ratio)) > Math.abs(Math.log(a.ratio)) ? b : a));
  return `${top.name.replace(": ", " ")}: failures ${ratioText(top.ratio)}${top.ratio_ci ? ` (${ratioCiText(top.ratio_ci)})` : ""}`;
}

// The answer line under the model's name: the model, the shape, the rate
// now and the data, as short phrases. ``saved`` ends it.
export function recurrentAnswer(r, { saved = null } = {}) {
  const parts = [];
  const add = (p) => p && parts.push(p);
  const fam = familyOf(r);
  if (fam === "renewal") {
    add(r.repair_test ? repairTitle(r.repair_test.verdict) : r.model?.name);
    const rest = r.restoration;
    if (rest?.effectiveness != null) {
      const verb = r.model?.id === "ari" ? "remove" : "restore";
      const what = r.model?.id === "ari" ? "of the rise in failure rate" : r.model?.id === "grp_ii" ? "of the age" : "of the age gained";
      const range = restoresRange(rest);
      add(`repairs ${verb} ${pct(Math.max(rest.effectiveness, 0))} ${what}${range ? ` (${ciPct(r)} two-sided range ${range.words})` : ""}`);
    } else if (rest?.ratio != null) {
      add(`gap ratio ${ratioText(rest.ratio)}${rest.ratio_ci ? ` (${ciPct(r)} ${ciText(rest.ratio_ci)})` : ""}`);
    }
    const soon = r.next_failure?.units?.[0];
    if (soon?.median != null) add(`next failure: ${soon.system} in about ${withUnitR(soon.median, r)} (median)`);
  } else {
    add(r?.model?.id === "hpp" || r?.baseline?.id === "hpp" ? "Constant failure rate" : r?.model?.name);
    add(fam === "regression" ? strongestCoefficient(r) : shapeWords(r));
    add(mtbfWords(r));
  }
  add(r?.from_params ? "made from parameters" : dataText(r));
  if (!r?.from_params) add(terminationText(r));
  add(saved);
  return parts.filter(Boolean);
}

// ---- Diagnostics -------------------------------------------------------------

const pText = (p) => (p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`);

// "Is the failure rate changing?" from the Laplace and MIL-HDBK-189C trend
// tests (null hypothesis: a constant rate): each test's statistic and p-value,
// and what a p-value is. No verdict, no tone. { words } or null.
const TREND_STAT = { laplace: "U", mil_hdbk_189c: "χ²" };
export function trendCheck(r) {
  const tests = (r?.trend_tests || []).filter((t) => t.p_value != null);
  if (!tests.length) return null;
  const rows = tests.map((t) => {
    const stat = Number.isFinite(t.statistic) ? `${TREND_STAT[t.id] || "statistic"} = ${formatNumber(t.statistic, { sig: 3 })}, ` : "";
    return `${t.test} trend test: ${stat}${pText(t.p_value)}`;
  });
  return {
    words: `${rows.join("; ")}. The p-value is how often a pattern this strong arises by chance when the failure rate is constant.`,
  };
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

// "Is reliability growing?" as evidence: the model's growth shape with its
// range where it has one, and the slope of the data's Duane plot. No verdict:
// the analyst decides.
export function growingCheck(r) {
  const slope = logSlope(duanePoints(r).observed);
  const minus = (v) => formatNumber(v, { sig: 2 }).replace(/^-/, "−");
  const slopeWords = slope == null ? ""
    : `The cumulative MTBF ${slope > 0.05 ? "rises" : slope < -0.05 ? "falls" : "is about level"} as time goes on (Duane slope ${minus(slope)}).`;
  const shape = growthReading(r)?.text || "";
  const words = [shape, slopeWords].filter(Boolean).join(" ");
  return words ? { words } : null;
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

// The chance of ``k`` or more events from a Poisson count with mean ``mu``.
export function poissonUpperTail(k, mu) {
  if (!(mu > 0) || !(k > 0)) return 1;
  // 1 − P(X ≤ k − 1), the terms summed in logs so a large mean doesn't overflow.
  let term = Math.exp(-mu);
  let below = 0;
  for (let j = 0; j < Math.ceil(k); j++) {
    below += term;
    term *= mu / (j + 1);
  }
  return Math.min(1, Math.max(0, 1 - below));
}

// "Does any system fail more than the model expects?" from each system's
// failures against the model's expectation over its own window: the counts,
// and the chance of that many or more from a Poisson count (a p-value, and the
// level it would take across this many systems). No verdict.
export function systemsCheck(r) {
  const rows = r?.system_residuals || [];
  if (rows.length < 2) return null;
  const top = rows[0];
  const n = Math.max(rows.length, Number(r?.n_systems) || 0);
  const p = poissonUpperTail(top.failures, top.expected);
  const what = `${formatNumber(top.failures)} failures where the model expects ${formatNumber(top.expected, { sig: 2 })}`;
  const pw = p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`;
  return {
    rows,
    words: `Largest excess: ${top.system}, ${what} (${pw}: how often that many or more arise by chance for one system; `
      + `with ${n} systems to pick from, compare it with ${formatNumber(0.05 / n, { sig: 2 })}).`,
  };
}
