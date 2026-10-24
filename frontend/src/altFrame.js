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
import { stressName } from "./components/stressName.js";

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

// "β 0.78 (95% 0.63–0.96)".
export function shapeWords(results) {
  const s = shapeParam(results);
  if (!s || !Number.isFinite(Number(s.value))) return null;
  const ci = Array.isArray(s.ci) && s.ci.every((v) => Number.isFinite(Number(v)))
    ? ` (95% ${formatNumber(s.ci[0])}–${formatNumber(s.ci[1])})` : "";
  return `${s.symbol} ${formatNumber(s.value)}${ci}`;
}

// A tested level's stresses in words: "30 kV", "60 °C, load 0.5".
export function levelWords(stress, stresses) {
  return (stress || []).map((v, j) => {
    const s = (stresses || [])[j] || {};
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

// The default use stress: the mildest tested level of each stress (lowest).
export function defaultUse(results) {
  const r = results || {};
  return (r.stresses || []).map((_, j) => {
    const vals = (r.levels || []).map((l) => l.stress?.[j]).filter((v) => Number.isFinite(v));
    return vals.length ? Math.min(...vals) : 0;
  });
}

// ---- Diagnostics in words ---------------------------------------------------

export function pWords(p) {
  if (!Number.isFinite(p)) return null;
  return p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`;
}

const TONE = { ok: "good", warn: "caveat", fail: "bad" };

// "Is the shape the same at every stress?" — the likelihood-ratio test of
// one shape against a shape for each level.
export function shapeCheck(diag, results) {
  const r = results || {};
  if (r.distribution_id === "exponential" || (diag && diag.shape === null)) {
    return { tone: null, words: "Nothing to test: an exponential has no shape, only a constant failure rate at each stress." };
  }
  const s = diag?.shape;
  if (!s) return null;
  if (!s.computed) return { tone: null, words: `Can't tell: ${s.detail}.` };
  const p = pWords(s.p);
  if (s.verdict === "ok") return { tone: "good", words: `Yes: no sign the shape changes from level to level (${p}).` };
  if (s.verdict === "warn") return { tone: "caveat", words: `Perhaps not: the shape may differ between levels (${p}).` };
  return {
    tone: "bad",
    words: `No: the shape changes between levels (${p}). That can mean a different failure mode at some stresses: check the failures there.`,
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

export { stressName };
