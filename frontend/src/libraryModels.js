// The reliability data library under Models (Derryn, 9 Nov 2026: "the records are published rates
// and distributions, so models with their uncertainty, not datasets"), three levels: the
// libraries (/models/library), one library's records (/models/library/:source) and one record
// (/models/library/:source/:record). Records are used as a model (a rate per hour → an exponential
// with the source's 5–95% range) or as a prior in a fit. The words and the arithmetic for the pages.

export const LIBRARY_PATH = "/models/library";
export const sourcePath = (source) => `${LIBRARY_PATH}/${encodeURIComponent(source)}`;
// A record's id is "source:code" (nrc-inl-2020:mov-fto).
export function recordPath(recordId) {
  const [source, ...rest] = String(recordId).split(":");
  return `${sourcePath(source)}/${encodeURIComponent(rest.join(":"))}`;
}
export const recordIdOf = (source, record) => `${source}:${record}`;

// Why a record can't be a model (or a prior) here, in words; null when it can.
export function whyNot(rec, use = "model") {
  if (!rec) return null;
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

// A number to 3 significant figures, small ones in scientific form.
export function sig(v) {
  const x = Number(v);
  if (v == null || !Number.isFinite(x)) return "—";
  if (x !== 0 && (Math.abs(x) < 0.001 || Math.abs(x) >= 1e7)) return x.toExponential(2).replace("e-", "e−");
  return Number(x.toPrecision(3)).toLocaleString("en-AU");
}
export const rangeText = (r) => (r?.p05 != null && r?.p95 != null ? `${sig(r.p05)} – ${sig(r.p95)}` : "—");

// What the units mean for a record.
export function unitsMeaning(kind, units = "") {
  if (kind === "per_demand") return "The chance it fails each time it's asked to work (a demand), whatever the time between.";
  const u = String(units).toLowerCase();
  const basis = u.includes("calendar") ? "calendar hours (whether or not it's running)" : u.includes("running") || u.includes("operat")
    ? "hours of operation" : "hours";
  return `Failures per ${basis}: the mean life is one over the rate.`;
}

// The distribution written out: "Gamma (shape 1.26, rate 7.17e6 per hour)".
export function distributionWords(d) {
  if (!d?.family) return "";
  const p = Object.fromEntries((d.params || []).map((x) => [x.name, x.value]));
  if (d.family === "gamma") return `Gamma (shape α ${sig(p.alpha)}, rate β ${sig(p.beta)})`;
  if (d.family === "beta") return `Beta (α ${sig(p.alpha)}, β ${sig(p.beta)})`;
  if (d.family === "lognormal") return `Lognormal (μ ${sig(p.mu)}, σ ${sig(p.sigma)})`;
  if (d.family === "point") return `A single value, ${sig(p.value)} (no uncertainty given)`;
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
