// The reliability data library under Models (Derryn, 9 Nov 2026: "the records are published rates
// and distributions, so models with their uncertainty, not datasets"), three levels: the
// libraries (/models/library), one library's records (/models/library/:source) and one record
// (/models/library/:source/:record). Records are used as a model (a rate per hour → an exponential
// with the source's 5–95% range; a life record → a model of its own family) or as a prior in a fit.
// A user's own libraries (Derryn, 9 Nov 2026: "allow a model to be added to one") sit beside the
// published sources with the same pages: their records are snapshots of saved life models (kind
// "life"). The words and the arithmetic for the pages.

export const LIBRARY_PATH = "/models/library";
export const sourcePath = (source) => `${LIBRARY_PATH}/${encodeURIComponent(source)}`;
// A record's id is "source:code" (nrc-inl-2020:mov-fto).
export function recordPath(recordId) {
  const [source, ...rest] = String(recordId).split(":");
  return `${sourcePath(source)}/${encodeURIComponent(rest.join(":"))}`;
}
export const recordIdOf = (source, record) => `${source}:${record}`;

// A record's kind in a label.
export const KIND_LABEL = { rate: "Failure rate", per_demand: "Per demand", life: "Life model" };
// A source's basis in a label.
export const BASIS_LABEL = { field_data: "Field data", prediction_model: "Handbook prediction model", fitted: "Your models" };
// A life record (a saved model's snapshot, or a published life distribution).
export const isLife = (rec) => rec?.kind === "life";

// Why a record can't be a model (or a prior) here, in words; null when it can.
export function whyNot(rec, use = "model") {
  if (!rec) return null;
  if (isLife(rec)) return null;
  if (rec.basis === "prediction_model") {
    return "A handbook base rate for a parts count: on its own it isn't a model. Use it in a prediction.";
  }
  if (rec.kind === "per_demand") {
    return use === "model"
      ? "A probability per demand, not a life over time: a model here is fitted from counts of demands and failures."
      : "A probability per demand: a position's history counts lives, not demands.";
  }
  return null;
}

// A library that has records usable as a model or a prior on their own (a failure rate counted
// from service; not a handbook of base rates for parts counts): the pickers' default.
export const usableSource = (s) => !!s && s.basis !== "prediction_model" && !!(s.kinds?.rate || s.kinds?.life);

// The pickers' libraries: the user's own first (each with records), then the published ones.
export function pickerSources(sources) {
  const list = sources || [];
  return [...list.filter((s) => s.mine), ...list.filter((s) => !s.mine)];
}

// Why a search for a use hid records, in one grey line (the search's left_out: {why: count});
// null when it hid none.
export function leftOutWords(leftOut) {
  const parts = [];
  if (leftOut?.prediction_model) parts.push("Base rates for parts counts are left out; use them in a prediction.");
  if (leftOut?.per_demand) parts.push("Probabilities per demand are left out: they aren't lives over time.");
  return parts.length ? parts.join(" ") : null;
}

// A record's one detail line in a picker: its value and units, its 5–95% range and the short
// source name ("9.13e−5 per hour (running) · 5–95%: 7.34e−7 – 3.33e−4 · NRC/INL 2020").
export const pickerDetail = (r) => (isLife(r)
  ? [familyName(r.family || r.distribution?.family), r.mean != null ? `mean life ${sig(r.mean)} ${r.units || ""}`.trim() : null,
    r.b10 != null ? `B10 ${sig(r.b10)}` : null, r.source]
  : [`${sig(r.mean)} ${r.units || ""}`.trim(), r?.p05 != null && r?.p95 != null ? `5–95%: ${rangeText(r)}` : null, r.source])
  .filter(Boolean).join(" · ");

// A distribution family's name as the app spells it.
export const familyName = (f) => ({ weibull: "Weibull", exponential: "Exponential", lognormal: "Lognormal", normal: "Normal",
  gamma: "Gamma" }[f] || f || "");

// A parameter's name in words (SurPyval's names).
const PARAM_WORDS = { alpha: "α", beta: "β", failure_rate: "λ", mu: "μ", sigma: "σ" };

// A life record's parameters written out: "Weibull (α 1,200, β 2.5; 95% bounds 900–1,500, 2–3.1)".
export function lifeWords(d, unit = "") {
  if (!d?.family) return "";
  const params = d.params || [];
  const vals = params.map((p) => `${PARAM_WORDS[p.name] || p.name} ${sig(p.value)}`).join(", ");
  const bounded = params.filter((p) => Array.isArray(p.ci));
  const bounds = bounded.length
    ? `; ${d.level ? `${Math.round(d.level * 100)}% ` : ""}bounds ${bounded.map((p) => `${sig(p.ci[0])}–${sig(p.ci[1])}`).join(", ")}` : "";
  return `${familyName(d.family)} (${vals}${bounds})${unit ? ` in ${unit}` : ""}`;
}

// How a record's model was fitted, in words.
export const methodWords = (m) => ({ mle: "fitted by maximum likelihood", bayes: "a Bayesian update", library: "from the data library",
  params: "parameters entered by hand" }[m] || "");

// A life record's evidence line: "10 observations: 8 failed, 2 running".
export function evidenceWords(e) {
  if (!e) return null;
  const parts = [];
  if (e.n != null) parts.push(`${Number(e.n).toLocaleString("en-AU")} observations`);
  const split = [e.failures != null && `${e.failures} failed`, e.suspensions ? `${e.suspensions} running` : null].filter(Boolean);
  if (split.length) parts.push(split.join(", "));
  const how = methodWords(e.method);
  if (how) parts.push(how);
  return parts.length ? parts.join(" · ") : null;
}

// A number to 3 significant figures, small ones in scientific form.
export function sig(v) {
  const x = Number(v);
  if (v == null || !Number.isFinite(x)) return "—";
  if (x !== 0 && (Math.abs(x) < 0.001 || Math.abs(x) >= 1e7)) return x.toExponential(2).replace("e-", "e−");
  // Three figures however small: 0.0037 stays "0.0037", not "0.004".
  return Number(x.toPrecision(3)).toLocaleString("en-AU", { maximumSignificantDigits: 3 });
}
export const rangeText = (r) => (r?.p05 != null && r?.p95 != null ? `${sig(r.p05)} – ${sig(r.p95)}` : "—");

// What the units mean for a record.
export function unitsMeaning(kind, units = "") {
  if (kind === "per_demand") return "The chance it fails each time it's asked to work (a demand), whatever the time between.";
  if (kind === "life") return "The times to failure the model describes; its parameters are in this unit.";
  const u = String(units).toLowerCase();
  const per = u.includes("calendar") ? "calendar hour (whether or not it's running)" : u.includes("running") || u.includes("operat")
    ? "hour of operation" : "hour";
  const foot = u.includes("foot") ? " per foot of pipe" : "";
  return `Failures per ${per}${foot}: the mean life is one over the rate.`;
}

// A rate as its source gives it, when that's another unit: a handbook's "failures per million
// hours" for a value the library keeps per hour (0.0037 failures per million hours for 3.7e−9 per
// hour). Null when the source's unit is the library's own.
export function asGivenWords(rec, value) {
  const given = String(rec?.units?.as_given || "");
  if (rec?.kind !== "rate" || value == null || !/per million hours/i.test(given)) return null;
  return `${sig(value * 1e6)} ${given}`;
}

// The distribution written out: "Gamma (shape 1.26, rate 7.17e6 per hour)".
export function distributionWords(d) {
  if (!d?.family) return "";
  const p = Object.fromEntries((d.params || []).map((x) => [x.name, x.value]));
  if (d.family === "gamma") return `Gamma (shape α ${sig(p.alpha)}, rate β ${sig(p.beta)})`;
  if (d.family === "beta") return `Beta (α ${sig(p.alpha)}, β ${sig(p.beta)})`;
  if (d.family === "lognormal") return `Lognormal (μ ${sig(p.mu)}, σ ${sig(p.sigma)})`;
  if (d.family === "point") return `A single value, ${sig(p.value)} (no uncertainty given)`;
  if (d.family === "weibull") return `Weibull (α ${sig(p.alpha)}, β ${sig(p.beta)})`;
  if (d.family === "exponential") return `Exponential (λ ${sig(p.failure_rate)})`;
  if (d.family === "normal") return `Normal (μ ${sig(p.mu)}, σ ${sig(p.sigma)})`;
  return d.family;
}

// ln Γ(x), Lanczos (g = 7), accurate to about 15 digits for x > 0.
const LANCZOS = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
  12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
export function lgamma(x) {
  if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - lgamma(1 - x);
  x -= 1;
  let a = LANCZOS[0];
  const t = x + 7.5;
  for (let i = 1; i < 9; i += 1) a += LANCZOS[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

// The density of a record's distribution at x.
export function density(d, x) {
  const p = Object.fromEntries((d?.params || []).map((q) => [q.name, Number(q.value)]));
  if (!(x > 0)) return 0;
  if (d.family === "gamma") return Math.exp(p.alpha * Math.log(p.beta) - lgamma(p.alpha) + (p.alpha - 1) * Math.log(x) - p.beta * x);
  if (d.family === "beta") {
    if (x >= 1) return 0;
    return Math.exp(lgamma(p.alpha + p.beta) - lgamma(p.alpha) - lgamma(p.beta) + (p.alpha - 1) * Math.log(x) + (p.beta - 1) * Math.log1p(-x));
  }
  if (d.family === "lognormal") {
    const z = (Math.log(x) - p.mu) / p.sigma;
    return Math.exp(-0.5 * z * z) / (x * p.sigma * Math.sqrt(2 * Math.PI));
  }
  return 0;
}

// The density of a life distribution at time t (SurPyval's parameters).
export function lifeDensity(d, t) {
  const p = Object.fromEntries((d?.params || []).map((q) => [q.name, Number(q.value)]));
  if (d.family === "normal") {
    const z = (t - p.mu) / p.sigma;
    return Math.exp(-0.5 * z * z) / (p.sigma * Math.sqrt(2 * Math.PI));
  }
  if (!(t > 0)) return 0;
  if (d.family === "weibull") return (p.beta / p.alpha) * (t / p.alpha) ** (p.beta - 1) * Math.exp(-((t / p.alpha) ** p.beta));
  if (d.family === "exponential") return p.failure_rate * Math.exp(-p.failure_rate * t);
  if (d.family === "lognormal" || d.family === "gamma") return density(d, t);
  return 0;
}

// Points for a life record's plot: a linear time axis from 0 (or the 0.5% life) to the 99% life.
export function lifeCurve(d, summary = {}, n = 160) {
  if (!d?.family || !(summary.p95 > 0)) return null;
  const hi = summary.p95 * 1.4;
  const lo = d.family === "normal" ? Math.max(0, (summary.p05 ?? 0) - (hi - summary.p05) * 0.3) : 0;
  const x = [], y = [];
  for (let i = 0; i < n; i += 1) {
    const t = lo + ((hi - lo) * i) / (n - 1);
    x.push(t);
    y.push(lifeDensity(d, t));
  }
  // Early densities can be infinite (a Weibull with β < 1 at 0): leave the first point out.
  if (!Number.isFinite(y[0])) { x.shift(); y.shift(); }
  return { x, y };
}

// Points for the plot: on a log scale from a tenth of the 5% value to three times the 95% value.
export function curve(d, p05, p95, n = 160) {
  if (!d || d.family === "point" || !(p05 > 0) || !(p95 > 0)) return null;
  let lo = Math.log(p05 / 10), hi = Math.log(p95 * 3);
  if (d.family === "beta") hi = Math.min(hi, Math.log(0.999));
  const x = [], y = [];
  for (let i = 0; i < n; i += 1) {
    const v = Math.exp(lo + ((hi - lo) * i) / (n - 1));
    x.push(v);
    y.push(density(d, v));
  }
  return { x, y };
}
