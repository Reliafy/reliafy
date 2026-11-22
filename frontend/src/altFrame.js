// An accelerated life model's page in the model frame: its tabs, the answer
// line under its name, and the plain words of its Diagnostics checks. Pure
// functions, so `node --test` covers them; components/alt/ lays them out.
//
// Tabs: Life-stress (life against stress, to the use stress), Probability
// plot (each tested level on probability paper), Calculator (the model at a
// use stress), Diagnostics (can I trust it?) and Data (what it was fitted
// to, and every parameter).
import { formatNumber } from "./format.js";
import { unitInText } from "./components/unitText.js";
import { stressName, withUnit as nameWithUnit } from "./components/stressName.js";
import { ciPct } from "./levels.js";
import { stressExtrapolation } from "./extrapolation.js";

export const ALT_TAB_LABELS = {
  life: "Life-stress",
  prob: "Probability plot",
  calc: "Calculator",
  diag: "Diagnostics",
  data: "Data",
};

// Ids and names from before the frame (the old views' ids and labels), and
// the other model pages' tab ids, mapped to the tab that holds that content.
const ALIASES = {
  plot: "life", "life-stress": "life", "life–stress": "life", lifestress: "life",
  probability: "prob", "probability plot": "prob",
  "use-level calculator": "calc", uselevel: "calc", calculator: "calc",
  detail: "data", "coefficients & fit": "data", coefficients: "data", coef: "data",
  gof: "diag", fit: "diag", check: "diag", diagnostics: "diag", validation: "diag",
};

// The tabs of an ALT model's page, in order: [{ id, label }]. The Calculator
// asks the saved model, so a fit not saved yet (the wizard) has none.
export function altTabs(results, { saved = true } = {}) {
  const r = results || {};
  const ids = ["life", r.probability_plot && "prob", saved && "calc", "diag", "data"];
  return ids.filter(Boolean).map((id) => ({ id, label: ALT_TAB_LABELS[id] }));
}

// The tab to open: the one asked for (its id, an old id, or its name) when
// the page has it, else the first.
export function resolveAltTab(tabs, wanted) {
  if (!tabs?.length) return null;
  const w = String(wanted || "").trim().toLowerCase();
  if (w) {
    const id = ALIASES[w] || w;
    const hit = tabs.find((t) => t.id === id || t.label.toLowerCase() === w);
    if (hit) return hit.id;
  }
  return tabs[0].id;
}

// ---- Numbers and words ------------------------------------------------------

const SYMBOL = { beta: "β", sigma: "σ", alpha: "α", mu: "μ" };
// A Weibull's or gamma's beta is its shape; a (log)normal's sigma its spread.
const SPREAD = new Set(["lognormal", "normal"]);

// The model's shape parameter (none for an exponential): { name, symbol,
// label, value, ci }.
export function shapeParam(results) {
  const p = (results?.params || [])[0];
  if (!p) return null;
  const symbol = SYMBOL[p.name] || p.name;
  const word = SPREAD.has(results.distribution_id) ? "Spread" : "Shape";
  return { ...p, symbol, label: `${word} ${symbol}` };
}

const withUnit = (v, unit) => `${formatNumber(v)}${unit ? ` ${unitInText(unit)}` : ""}`;

// Boltzmann's constant in eV per kelvin.
export const BOLTZMANN_EV = 8.617333262e-5;

// The activation energy of a thermal fit, in eV, with its two-sided interval:
// { value, ci, level } or null. SurPyval's own (activation_energy(): Arrhenius
// and Eyring), from the use-stress answer ``ev`` or the fit; SurPyval gives
// none for the temperature–nonthermal model, whose ``a`` is still Ea / k
// (life ∝ exp(a / T), T in kelvin), so that one is a × k here.
export function activationEnergy(results, ev = null) {
  const own = ev?.activation_energy || results?.activation_energy;
  if (own && Number.isFinite(Number(own.value))) {
    const ci = Array.isArray(own.ci) && own.ci.length === 2 && own.ci.every((x) => Number.isFinite(Number(x)))
      ? own.ci.map(Number) : null;
    return { value: Number(own.value), ci, level: Number.isFinite(own.level) ? own.level : null };
  }
  if (results?.life_model_id !== "power_exponential") return null;
  const a = (results.coefficients || []).find((c) => c.name === "a");
  const v = Number(a?.value);
  if (!Number.isFinite(v)) return null;
  const ci = Array.isArray(a.ci) && a.ci.length === 2 && a.ci.every((x) => Number.isFinite(Number(x)))
    ? a.ci.map((x) => Number(x) * BOLTZMANN_EV) : null;
  return { value: v * BOLTZMANN_EV, ci, level: null };
}

// The mean life (MTTF) at the use stress from the use-stress answer, with its
// two-sided interval (SurPyval's mean_cb): { value, ci, level } or null where
// there is none (an infinite mean is never shown).
export function meanAtUse(ev) {
  const m = ev?.mean_life;
  if (!m || !Number.isFinite(Number(m.value))) return null;
  const ci = Array.isArray(m.ci) && m.ci.length === 2 && m.ci.every((x) => Number.isFinite(Number(x)))
    ? m.ci.map(Number) : null;
  return { value: Number(m.value), ci, level: Number.isFinite(m.level) ? m.level : 0.9 };
}

// The lives the life-stress chart can show: the median and B10 come with a
// one-sided lower bound; the characteristic life (the life the model is
// fitted in) with a two-sided band.
export const CHART_LIVES = [
  { value: "b50", label: "Median" },
  { value: "b10", label: "B10" },
  { value: "eta", label: "Characteristic" },
];

// The life-stress line (from the use-stress answer) and the tested levels'
// marks for the life chosen: ``line`` { stress, life, lower, upper?, level,
// bound } and ``points`` [{ stress (the row), life }]. ``eta`` keeps the
// line as it is (its two-sided band). Null where the answer has no such line.
export function lifeLineFor(along, which, testedLives = null) {
  if (!along?.stress?.length) return null;
  if (which === "eta") return { line: along, points: null };
  const q = along.quantiles?.[which];
  if (!q || !Array.isArray(q.life)) return null;
  const keep = q.life.map((v, i) => Number.isFinite(v) && v > 0 && i < along.stress.length);
  const pick = (arr) => (arr || []).filter((_, i) => keep[i]);
  const line = {
    stress: pick(along.stress), life: pick(q.life),
    lower: pick(q.lower).map((v) => (Number.isFinite(v) && v > 0 ? v : null)),
    level: along.quantiles.level ?? 0.9, bound: "lower",
  };
  const points = (testedLives || []).map((t) => ({ stress: t.stress, life: t[which] }))
    .filter((t) => Number.isFinite(t.life));
  return { line, points };
}

// "β 0.78 (90% two-sided 0.63–0.96)".
export function shapeWords(results) {
  const s = shapeParam(results);
  if (!s || !Number.isFinite(Number(s.value))) return null;
  const ci = Array.isArray(s.ci) && s.ci.every((v) => Number.isFinite(Number(v)))
    ? ` (${ciPct(results, 0.9)} two-sided ${formatNumber(s.ci[0])}–${formatNumber(s.ci[1])})` : "";
  return `${s.symbol} ${formatNumber(s.value)}${ci}`;
}

// ---- A temperature given in °C or °F ------------------------------------------
// A thermal model's temperature typed in °C or °F is fitted in kelvin (the
// stress's ``unit`` is "K"; ``entered_unit`` the one the user chose). The
// page takes the use stress and shows the tested levels in the user's unit,
// and asks the model in kelvin.

export const enteredUnit = (s) => (s?.entered_unit === "°C" || s?.entered_unit === "°F" ? s.entered_unit : "");
const tidy = (v) => Number(Number(v).toPrecision(12));
export function fromKelvin(v, unit) {
  const k = Number(v);
  if (!Number.isFinite(k)) return k;
  if (unit === "°C") return tidy(k - 273.15);
  if (unit === "°F") return tidy((k - 273.15) * 9 / 5 + 32);
  return k;
}
export function toKelvin(v, unit) {
  const t = Number(v);
  if (!Number.isFinite(t)) return t;
  if (unit === "°C") return tidy(t + 273.15);
  if (unit === "°F") return tidy((t - 32) * 5 / 9 + 273.15);
  return t;
}

// A stress's name as the use-stress boxes take it: "Temperature (°C)" for a
// temperature given in °C, else its own name ("Temperature (K)").
export function inputStressName(s) {
  const u = enteredUnit(s);
  return u ? nameWithUnit(s?.label || s?.column || "Temperature", u) : stressName(s);
}

// The use stress as typed (the user's units) → the model's units (kelvin),
// or null while any is blank or not a number.
export function useForModel(results, values) {
  const n = parseUse(values);
  if (!n) return null;
  const ss = results?.stresses || [];
  return n.map((v, j) => toKelvin(v, enteredUnit(ss[j])));
}

// A life-stress chart (``plot``, along stress ``j``) in the user's units: a
// temperature given in °C or °F reads in that unit on the axis, the points
// and the other stress's lines, not in the kelvin the model was fitted in.
// Unchanged when nothing was converted.
export function plotInEnteredUnits(plot, stresses, j = 0) {
  if (!plot) return plot;
  const ss = stresses || [];
  const k = 1 - j;
  const u = enteredUnit(ss[j]);
  const uo = plot.secondary_label != null ? enteredUnit(ss[k]) : "";
  if (!u && !uo) return plot;
  const x = (v) => (u && v != null ? fromKelvin(v, u) : v);
  const o = (v) => (uo && v != null ? fromKelvin(v, uo) : v);
  const obs = plot.observations;
  return {
    ...plot,
    x_label: u ? inputStressName(ss[j]) : plot.x_label,
    secondary_label: uo ? inputStressName(ss[k]) : plot.secondary_label,
    lines: (plot.lines || []).map((ln) => ({ ...ln, stress: (ln.stress || []).map(x), secondary: o(ln.secondary) })),
    points: (plot.points || []).map((pt) => ({ ...pt, stress: x(pt.stress), secondary: o(pt.secondary) })),
    ...(obs ? {
      observations: {
        ...obs,
        ranges: { ...obs.ranges, stress: (obs.ranges?.stress || []).map(x) },
        failures: { ...obs.failures, stress: (obs.failures?.stress || []).map(x) },
      },
    } : {}),
  };
}

// A probability-plot series' legend label in the user's units
// ("Temperature (°C)=114"); the fit's own label when nothing was converted.
export function seriesLabel(series, stresses) {
  const ss = stresses || [];
  const row = series?.stress;
  if (!Array.isArray(row) || !row.some((_, j) => enteredUnit(ss[j]))) return series?.label;
  return row.map((v, j) => {
    const s = ss[j] || {};
    const u = enteredUnit(s);
    const name = u ? inputStressName(s) : stressName(s);
    return `${name}=${formatNumber(fromKelvin(v, u), { sig: 4 })}`;
  }).join(" · ");
}

// "40 °C is 313.15 K" for a converted use stress; null when nothing is converted.
export function kelvinWords(results, values) {
  const ss = results?.stresses || [];
  const n = parseUse(values);
  if (!n) return null;
  const parts = n.map((v, j) => {
    const u = enteredUnit(ss[j]);
    return u ? `${formatNumber(v, { sig: 6 })} ${u} is ${formatNumber(toKelvin(v, u), { sig: 6 })} K` : null;
  }).filter(Boolean);
  return parts.length ? parts.join("; ") : null;
}

// A tested level's stresses in words: "30 kV", "60 °C, load 0.5".
export function levelWords(stress, stresses) {
  return (stress || []).map((v, j) => {
    const s = (stresses || [])[j] || {};
    const shown = enteredUnit(s);
    if (shown) return `${formatNumber(fromKelvin(v, shown), { sig: 4 })} ${shown}`;
    const label = String(s.label || s.column || `stress ${j + 1}`);
    // The unit given, or the one the label names ("Temperature (°C)").
    const unit = String(s.unit || "").trim() || (/\(([^()]+)\)\s*$/.exec(label) || [])[1] || "";
    return unit ? `${formatNumber(v, { sig: 4 })} ${unit}` : `${label} ${formatNumber(v, { sig: 4 })}`;
  }).join(", ");
}

// "60 failed, 16 still running", or "76 observations" for a fit saved before
// the levels carried their failures.
export function failureWords(results) {
  const r = results || {};
  if (Number.isFinite(r.n_failures)) {
    const running = Number.isFinite(r.n) ? r.n - r.n_failures : 0;
    return `${r.n_failures.toLocaleString("en-US")} failed${running > 0 ? `, ${running.toLocaleString("en-US")} still running` : ""}`;
  }
  return Number.isFinite(r.n) ? `${r.n.toLocaleString("en-US")} observations` : null;
}

// The line under the model's name: the model, its shape, how far the life
// moves across the tested levels, the data.
export function altAnswerParts(results, { saved = null } = {}) {
  const r = results || {};
  const parts = [];
  const add = (p) => p && parts.push(p);
  add(r.life_model ? `${r.life_model} model${r.distribution ? ` (${r.distribution})` : ""}` : r.distribution);
  add(shapeWords(r));
  const lives = (r.levels || []).map((l) => l.characteristic_life).filter((v) => Number.isFinite(v));
  if (lives.length > 1) {
    add(`life ${formatNumber(Math.min(...lives))}–${withUnit(Math.max(...lives), r.unit)} across ${lives.length} tested levels`);
  }
  add(failureWords(r));
  add(r.no_finite_maximum && "no finite maximum");
  add(saved);
  return parts;
}

// The acceleration factor of the use stress against each tested level: how
// many times longer a unit lasts at the use stress than at that level.
export function accelerationRows(levels, lifeAtUse) {
  return (levels || []).map((l) => {
    const life = l.characteristic_life;
    const af = Number.isFinite(lifeAtUse) && Number.isFinite(life) && life > 0 ? lifeAtUse / life : null;
    return { stress: l.stress, life, af };
  });
}

// The use stress as numbers, or null while any is blank or not a number.
export function parseUse(values) {
  const out = (values || []).map((v) => (String(v).trim() === "" ? NaN : Number(v)));
  return out.length && out.every(Number.isFinite) ? out : null;
}

// The default use stress: the mildest tested level of each stress (lowest),
// in the user's units (105 for a temperature given in °C).
export function defaultUse(results) {
  const r = results || {};
  return (r.stresses || []).map((s, j) => {
    const vals = (r.levels || []).map((l) => l.stress?.[j]).filter((v) => Number.isFinite(v));
    return vals.length ? fromKelvin(Math.min(...vals), enteredUnit(s)) : 0;
  });
}

// ---- Diagnostics in words ---------------------------------------------------

export function pWords(p) {
  if (!Number.isFinite(p)) return null;
  return p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`;
}

const TONE = { ok: "good", warn: "caveat", fail: "bad" };

// "Is the failure mechanism the same at every stress?" — SurPyval's
// likelihood-ratio test of one shape at every tested level against a shape
// for each (common_shape_test(), chi-squared on k − 1 degrees of freedom).
// The test and what it means, never a verdict word: ``words`` is the line
// under the question, ``detail`` the statistic, each level's shape and any
// level left out. A p-value under 0.05 is flagged to check (tone "caveat").
export const SHAPE_ALPHA = 0.05;
export function shapeCheck(diag, results) {
  const r = results || {};
  if (r.distribution_id === "exponential" || (diag && diag.common_shape === null)) {
    return { tone: null, words: "Nothing to test: an exponential has no shape, only a constant failure rate at each stress." };
  }
  const s = diag?.common_shape;
  if (!s) return null;
  if (!s.computed) return { tone: null, words: `Can't tell: ${s.detail}.` };
  const p = pWords(s.p);
  const sym = shapeParam(r)?.symbol || s.parameter || "shape";
  const differ = Number.isFinite(s.p) && s.p < SHAPE_ALPHA;
  const words = differ
    ? `The shapes differ (${p}): one ${sym} doesn't fit every tested stress, which can mean a different failure mechanism at some of them. Extrapolation is unreliable.`
    : `The shapes are consistent (${p}): one ${sym} fits every tested stress, so extrapolating to the use stress rests on that.`;
  const ss = r.stresses || [];
  const parts = [];
  if (Number.isFinite(s.statistic) && Number.isFinite(s.df)) {
    parts.push(`Likelihood-ratio statistic ${formatNumber(s.statistic, { sig: 3 })} on ${s.df} degree${s.df === 1 ? "" : "s"} of freedom (χ²)`);
  }
  const shapes = (s.shapes || []).filter((x) => Number.isFinite(x.shape));
  if (shapes.length) {
    const each = shapes.map((x) => `${formatNumber(x.shape, { sig: 3 })} at ${levelWords(x.stress, ss)}`).join(", ");
    parts.push(`each level's own ${sym} ${each}${Number.isFinite(s.common_shape) ? `; one ${sym} for all ${formatNumber(s.common_shape, { sig: 3 })}` : ""}`);
  }
  const left = (s.left_out || []).map((x) => `${levelWords(x.stress, ss)} (${x.failures} failure${x.failures === 1 ? "" : "s"})`);
  const leftOut = left.length
    ? `Left out of the test: ${left.join(", ")}. A level needs two failures for a shape of its own.`
    : null;
  return {
    tone: differ ? "caveat" : null,
    words,
    detail: parts.length ? `${parts.join("; ")}.` : null,
    leftOut,
  };
}

// "Do the levels follow the life model?" — the life model's lack-of-fit test
// against a separate life at each level.
export function lifeCheck(diag, results) {
  const s = diag?.life_stress;
  if (!s) return null;
  if (!s.computed) return { tone: null, words: `Can't tell: ${s.detail}.` };
  const p = pWords(s.p);
  const model = results?.life_model || "life";
  if (s.verdict === "ok") return { tone: "good", words: `Yes: each level's own life sits on the ${model} line (${p}).` };
  if (s.verdict === "warn") return { tone: "caveat", words: `Perhaps not: the levels stray a little from the ${model} line (${p}).` };
  return { tone: "bad", words: `No: the levels' own lives stray from the ${model} line (${p}).` };
}

// "Would another life model fit better?" — every other life model for the
// same number of stresses, refitted, by AIC.
export function compareCheck(diag) {
  const rows = diag?.comparison || [];
  if (!rows.length) return null;
  const better = rows.filter((r) => !r.current && Number.isFinite(r.delta) && r.delta < -2)
    .sort((a, b) => a.delta - b.delta);
  if (!better.length) {
    return { tone: "good", words: "No: none of the other life models fits clearly better (AIC lower by more than 2)." };
  }
  const lower = (r) => `AIC ${formatNumber(-r.delta, { sig: 2 })} lower`;
  const best = better[0];
  const offered = better.find((r) => r.life_model_id);
  let words = `Yes: ${best.name} fits better (${lower(best)}${best.life_model_id ? "" : "; not offered here"})`;
  if (!best.life_model_id && offered) words += `, and so does ${offered.name} (${lower(offered)})`;
  return { tone: "caveat", words: `${words}. Prefer another only where its physics suits the stress.` };
}

// "How far is the use stress from the tested stresses?" — the levels tested
// along each stress, and the use stress's distance from them in widths of
// the tested range (on the scale the life model is straight in).
export function distanceCheck(diag) {
  const rows = diag?.extrapolation || [];
  if (!rows.length) return null;
  const few = rows.filter((r) => r.levels_verdict === "warn");
  const far = rows.filter((r) => r.use_verdict === "warn");
  const words = [];
  for (const r of far) {
    words.push(`${r.label}: the use stress is ${formatNumber(r.distance, { sig: 2 })} times the tested range's width beyond it, so the life there rests on the life model alone.`);
  }
  for (const r of few) {
    words.push(`${r.label} was tested at only ${r.levels} level${r.levels === 1 ? "" : "s"}, so the data can't check the life model's form along it.`);
  }
  const hasUse = rows.some((r) => r.use != null);
  if (!hasUse) {
    words.push("Enter your use stress (on Life-stress or the Calculator) to see how far it is.");
    return { tone: few.length ? "caveat" : null, words: words.join(" ") };
  }
  if (!far.length && !few.length) {
    return { tone: "good", words: "Close: the use stress is within one range-width of the tested stresses." };
  }
  return { tone: "caveat", words: words.join(" ") };
}

// "1.07×" — a distance in range widths; "inside" for none.
export function distanceWords(r) {
  if (r.use == null) return "—";
  if (!Number.isFinite(r.distance)) return "—";
  if (r.distance === 0) return "inside";
  return `${formatNumber(r.distance, { sig: 2 })}× the range`;
}

// A plain warning when the use stress is outside the tested stresses (any
// distance: the life there rests on the life-stress relationship alone),
// "well" outside when more than one tested range's width beyond them:
// "20 kV is well below the tested 30–36 kV …" (extrapolation.js, shown with
// the shared ExtrapolationNote). ``useModel``: the use stress in the model's
// units (kelvin for a temperature); ``af``: the acceleration factor against
// the reference. null when the use stress is within the tested stresses.
export function useRangeWarning(results, useModel, af = null) {
  const ss = results?.stresses || [];
  const levels = results?.levels || [];
  if (!useModel || !levels.length) return null;
  const parts = [];
  ss.forEach((s, j) => {
    const vals = levels.map((l) => Number(l.stress?.[j])).filter(Number.isFinite);
    const u = Number(useModel[j]);
    if (!vals.length || !Number.isFinite(u)) return;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const width = hi - lo;
    const tol = 1e-9 * Math.max(1, Math.abs(lo), Math.abs(hi));
    const beyond = u < lo - tol ? lo - u : u > hi + tol ? u - hi : 0;
    if (beyond === 0) return;
    const far = !(width > 0 && beyond <= width);
    const unit = enteredUnit(s) || s?.unit || "";
    const show = (v) => `${formatNumber(fromKelvin(v, enteredUnit(s)), { sig: 4 })}${unit ? ` ${unit}` : ""}`;
    const tested = width > 0 ? `${formatNumber(fromKelvin(lo, enteredUnit(s)), { sig: 4 })}–${show(hi)}` : show(lo);
    parts.push(`${show(u)} is ${far ? "well " : ""}${u < lo ? "below" : "above"} the tested ${tested}`);
  });
  return stressExtrapolation(parts, af?.value != null ? Number(af.value) : null);
}

export { stressName };
