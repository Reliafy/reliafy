// A degradation model's page in the model frame (modelFrame.js): its tabs,
// the answer line under its name, the figures read off its reliability curve
// and the plain words of its checks. Pure functions, so `node --test` covers
// them; DegradationResultView.jsx lays them out.
//
// Every figure here is read off what the fit returns: the population
// reliability curve with its two-sided confidence band, the life model's
// mean, the path comparison (AICc) and each reading's residual about its
// item's fitted path. Nothing is resampled or refitted.
import { formatNumber, formatPercent } from "./format.js";
import { TAB_LABELS, resolveTab } from "./modelFrame.js";
import { bestFitSentence, compareRows, timeAtValue } from "./lifeResults.js";
import { meanLifeAnswer } from "./meanLife.js";
import { unitInText } from "./components/unitText.js";

const LABELS = { ...TAB_LABELS, paths: "Paths" };

// Tab ids from before the frame ("Path plot", "Reliability", "Induced life"),
// mapped to the tab that holds that content now.
const ALIASES = {
  "path plot": "paths", path: "paths",
  rel: "calc", reliability: "calc",
  induced: "diag", "induced life": "diag", fit: "diag", stats: "diag",
};

const curvesOf = (results) => results?.life_model?.curves || null;
const hasCurve = (c) => Array.isArray(c?.x) && c.x.length > 1 && Array.isArray(c?.sf);

// Whether the readings' residuals came with the fit (models fitted since
// they were added to the result carry them).
export const hasResiduals = (results) => {
  const units = results?.units || [];
  return units.length > 0 && units.every((u) => Array.isArray(u.residuals));
};

// The path shapes compared when the fit chose one (path "best"): more than one.
export const hasPathRanking = (results) => (results?.path_selection || []).length > 1;

// The tabs, in order: Paths · Calculator · Model characteristics ·
// Diagnostics · Data. A tab with nothing to show is left out. ``modelId``
// (a saved model the viewer can ask) adds the induced-life check.
export function degradationTabs(results, { modelId = null } = {}) {
  const r = results || {};
  const curve = hasCurve(curvesOf(r));
  const mean = Number.isFinite(Number(r.life_model?.mean)) && r.life_model?.mean != null;
  const diag = !!modelId || hasPathRanking(r) || hasResiduals(r);
  return ["paths", curve && "calc", (curve || mean) && "chars", diag && "diag", "data"]
    .filter(Boolean)
    .map((id) => ({ id, label: LABELS[id] }));
}

// The tab to open: the one asked for (by id, an old id or its name), else
// the first.
export function resolveDegradationTab(tabs, wanted) {
  const w = String(wanted || "").trim().toLowerCase();
  return resolveTab(tabs, ALIASES[w] || w);
}

// ---- Reading the curve ---------------------------------------------------------

// A value of the curve ``y`` at ``t``, interpolated; null off the grid.
function valueAt(x, y, t) {
  if (!x?.length || !y || !Number.isFinite(t)) return null;
  if (t < x[0] || t > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (t <= x[i]) {
      const a = y[i - 1];
      const b = y[i];
      if (a == null || b == null) return null;
      const f = x[i] === x[i - 1] ? 0 : (t - x[i - 1]) / (x[i] - x[i - 1]);
      return a + f * (b - a);
    }
  }
  return null;
}

// The reliability at a time with its band: { value, lower, upper, beyond }.
// ``beyond``: the time is past the curve's end (where 99% have failed).
export function reliabilityAt(curves, t) {
  const time = Number(t);
  if (!hasCurve(curves) || !Number.isFinite(time) || time < 0) return null;
  const x = curves.x;
  if (time > x[x.length - 1]) return { value: null, lower: null, upper: null, beyond: true };
  return {
    value: valueAt(x, curves.sf, time),
    lower: curves.lower ? valueAt(x, curves.lower, time) : null,
    upper: curves.upper ? valueAt(x, curves.upper, time) : null,
    beyond: false,
  };
}

// The time by which the reliability falls to ``rel`` (a fraction), with the
// band's ends: { value, lower, upper }. The band's lower curve reaches it
// first, so ``lower`` (the design life) is the earlier time. Null ends where
// a curve doesn't reach it on its grid.
export function timeAtReliability(curves, rel) {
  if (!hasCurve(curves) || !(rel > 0 && rel < 1)) return null;
  return {
    value: timeAtValue(curves.x, curves.sf, rel),
    lower: curves.lower ? timeAtValue(curves.x, curves.lower, rel) : null,
    upper: curves.upper ? timeAtValue(curves.x, curves.upper, rel) : null,
  };
}

// The band's confidence (%) from the curves' alpha (90 when it isn't given).
export const bandLevel = (curves) => {
  const a = Number(curves?.alpha_ci);
  return Number.isFinite(a) && a > 0 && a < 1 ? Math.round((1 - a) * 1000) / 10 : 90;
};

// The usual B-lives off the curve, each with its band's ends.
const B_LIVES = [["B1", 0.01], ["B5", 0.05], ["B10", 0.1], ["B50", 0.5]];
export function bLives(curves) {
  if (!hasCurve(curves)) return [];
  return B_LIVES.map(([label, p]) => ({ label, p, ...timeAtReliability(curves, 1 - p) }));
}

const withUnit = (v, unit) => `${formatNumber(v)}${unit ? ` ${unitInText(unit)}` : ""}`;
const span = (lo, hi) => `${formatNumber(lo)}–${formatNumber(hi)}`;

// "90% band 3,210–3,950" (or "≥ 3,210 at 90%" with only the lower end).
export function bandWords(life, level) {
  if (!life) return "";
  if (life.lower != null && life.upper != null) return `${formatNumber(level)}% band ${span(life.lower, life.upper)}`;
  if (life.lower != null) return `≥ ${formatNumber(life.lower)} at ${formatNumber(level)}%`;
  return "";
}

// The life model's mean in the shape the shared mean-life words take.
export function meanAnswer(results) {
  const life = results?.life_model || {};
  const asResult = { distribution_id: life.distribution_id, params: life.params, kind: "distribution" };
  return meanLifeAnswer(asResult, life.mean != null ? { value: life.mean } : null);
}

// ---- The answer line -----------------------------------------------------------

// "8 mm" / "8": the threshold with its unit.
export const thresholdText = (r) =>
  `${formatNumber(r?.threshold, { sig: 4 })}${r?.measurement_unit ? ` ${r.measurement_unit}` : ""}`;

// The items and readings: "6 items, 48 readings" (", 1 never reaches the
// threshold" when some don't).
export function itemsWords(r) {
  const units = r?.units || [];
  const n = r?.n_units ?? units.length;
  if (!n) return null;
  const parts = [`${Number(n).toLocaleString("en-US")} item${n === 1 ? "" : "s"}`];
  if (r?.n_measurements != null) parts.push(`${Number(r.n_measurements).toLocaleString("en-US")} readings`);
  const never = units.filter((u) => u.censored).length;
  if (never) parts.push(`${never} not yet at the threshold`);
  return parts.join(", ");
}

// The three or four numbers that answer "what does this model say?".
export function degradationAnswer(results, { saved = null } = {}) {
  const r = results || {};
  const parts = [];
  const add = (p) => p && parts.push(p);
  add(r.path_model?.name && `${r.path_model.name} path to ${thresholdText(r)}`);
  add(r.life_model?.distribution && `${r.life_model.distribution} life`);
  const curves = curvesOf(r);
  const b10 = timeAtReliability(curves, 0.9);
  if (b10?.value != null) {
    const band = bandWords(b10, bandLevel(curves));
    add(`B10 ${withUnit(b10.value, r.unit)}${band ? ` (${band})` : ""}`);
  }
  const mean = meanAnswer(r);
  if (mean.kind === "mean") add(`mean ${withUnit(mean.value, r.unit)}`);
  add(itemsWords(r));
  add(saved);
  return parts.filter(Boolean);
}

// ---- The path ----------------------------------------------------------------

// Each path shape's formula (SurPyval's), with t for time.
export const PATH_FORMULAS = {
  linear: "a + b·t",
  exponential: "a·exp(b·t)",
  power: "a·t^b",
  logarithmic: "a + b·ln(t)",
  "lloyd-lipow": "a − b/t",
  quadratic: "a + b·t + c·t²",
  gompertz: "a·exp(−b·exp(−c·t))",
  "offset-exponential": "a + b·exp(c·t)",
  "michaelis-menten": "a·t/(b + t)",
};

// The population's mean path parameters by name: [{ name, value }].
export function pathParams(r) {
  const values = r?.path_param_mean || [];
  const names = r?.path_model?.param_names || [];
  return values.map((value, i) => ({ name: names[i] || "abcdefgh"[i] || `p${i + 1}`, value }));
}

export const POPULATION_METHODS = {
  moments: "two-stage moments (Lu–Meeker)",
  reml: "restricted maximum likelihood (REML)",
};

// ---- Diagnostics ---------------------------------------------------------------

// Do the two routes to a life agree? The median the path model itself
// implies (its paths drawn from the fitted population, each run to the
// threshold) against the median of the life model fitted to the items'
// crossing times. Within 10%: they agree.
export const ROUTES_AGREE = 0.1;
export function routesVerdict(induced, unit = "") {
  const a = Number(induced?.median);
  const b = Number(induced?.life_median);
  if (!induced?.available || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0) return null;
  const gap = Math.abs(a - b) / b;
  const pct = formatPercent(gap, { sig: 2 });
  const both = `median ${withUnit(a, unit)} by the path model, ${withUnit(b, unit)} by the crossing times`;
  return gap <= ROUTES_AGREE
    ? { tone: "good", gap, words: `Yes: the ${both} (${pct} apart).` }
    : { tone: "caveat", gap, words: `Not closely: the ${both} (${pct} apart). Check the path shape and the items that never reach the threshold.` };
}

// Which path shape fits the readings best? The comparison by AICc, as the
// shared comparison rows (lowest first) with a verdict for the one used.
export function pathRanking(r) {
  if (!hasPathRanking(r)) return null;
  const candidates = r.path_selection.map((c) => ({ id: c.id, name: c.name, aic_c: c.aicc }));
  const rows = compareRows(candidates, "aic_c", r.path_model?.id);
  if (!rows.length) return null;
  const used = rows.find((row) => row.current);
  const good = !used || used.verdict === "best" || used.verdict === "about";
  return { rows, tone: good ? "good" : "caveat", words: bestFitSentence(rows) };
}

// Do the readings scatter evenly about each path? Each reading's residual
// against the readings' own scatter (σ, the fit's measurement standard
// deviation): how many sit more than 2.5 σ from their item's path.
export const SCATTER_LIMIT = 2.5;
export function scatterCheck(r) {
  if (!hasResiduals(r)) return null;
  const all = (r.units || []).flatMap((u) => u.residuals).filter((v) => v != null && Number.isFinite(v));
  if (!all.length) return null;
  const v = Number(r.measurement_var);
  const sigma = Number.isFinite(v) && v > 0 ? Math.sqrt(v) : null;
  const mu = r.measurement_unit ? ` ${r.measurement_unit}` : "";
  if (!sigma) {
    return { sigma: null, odd: 0, n: all.length, tone: null,
             words: "The paths run through every reading exactly: there's no scatter to check." };
  }
  const odd = all.filter((e) => Math.abs(e) > SCATTER_LIMIT * sigma).length;
  const s = `σ = ${formatNumber(sigma)}${mu}`;
  return {
    sigma, odd, n: all.length,
    tone: odd === 0 ? "good" : odd / all.length > 0.05 ? "caveat" : null,
    words: odd === 0
      ? `Yes: every reading is within ${SCATTER_LIMIT} σ of its item's path (${s}).`
      : `${odd} of ${all.length} readings sit more than ${SCATTER_LIMIT} σ from their item's path (${s}): worth checking in the data.`,
  };
}
