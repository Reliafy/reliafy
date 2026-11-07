// Competing risks (#177): read a fit's stored incidence curves at a time and
// say what they mean. The curves are SurPyval's (Aalen-Johansen, with
// Aalen's 95% bounds); these helpers only look a step function up and word
// it. Pure, so `node --test` covers them.
import { formatNumber, formatPercent } from "./format.js";

// The value of a right-continuous step curve at ``t``: the last point at or
// before it (the curve's first value before its first point).
export function stepAt(xs, ys, t) {
  if (!xs?.length || !ys?.length || !Number.isFinite(t)) return null;
  let lo = 0;
  let hi = xs.length - 1;
  if (t < xs[0]) return ys[0] ?? null;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (xs[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return ys[lo] ?? null;
}

// Each failure mode at ``t``: { name, failures, cif, lower, upper, share },
// in the fit's order (most failures first). ``share`` is the mode's part of
// all the failures by then.
export function causesAt(result, t) {
  const c = result?.curves;
  if (!c) return [];
  const rows = (result.causes || []).map((k) => ({
    name: k.name,
    failures: k.failures,
    cif: stepAt(c.x, c.cif?.[k.name], t),
    lower: stepAt(c.x, c.lower?.[k.name], t),
    upper: stepAt(c.x, c.upper?.[k.name], t),
  }));
  const total = rows.reduce((s, r) => s + (r.cif || 0), 0);
  return rows.map((r) => ({ ...r, share: total > 0 && r.cif != null ? r.cif / total : null }));
}

// A probability as a percentage: whole numbers from 10%, two figures below.
export const pct = (p) => formatPercent(p);

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// The answer in words at ``t``: "Bearing wear causes 58% of failures by
// 5,000 hours: 40% of units fail from it by then (we're 95% sure it's
// between 28% and 52%)." ``unit`` is the unit as running text.
export function readingAt(result, t, unit = "") {
  const rows = causesAt(result, t);
  if (!rows.length) return "";
  const when = `${formatNumber(t)}${unit ? ` ${unit}` : ""}`;
  const top = rows.reduce((a, b) => ((b.cif || 0) > (a.cif || 0) ? b : a));
  if (!top.cif) return `No unit has failed by ${when}.`;
  if (rows.length === 1)
    return `Every failure is ${top.name}: ${pct(top.cif)} of units have failed from it by ${when}. `
      + "With one mode there are no competing risks.";
  let text = `${cap(top.name)} causes ${pct(top.share)} of failures by ${when}: ${pct(top.cif)} of units fail `
    + "from it by then";
  if (top.lower != null && top.upper != null)
    text += ` (we're 95% sure it's between ${pct(top.lower)} and ${pct(top.upper)})`;
  return `${text}.`;
}

// When the lead changes, in words, from the fit's ``leads``: "Seal leak
// leads early; bearing wear overtakes it at about 2,810 hours." Empty when
// one mode leads throughout.
export function leadSentence(leads, unit = "") {
  if (!leads || leads.length < 2) return "";
  const [first, then] = leads;
  return `${cap(first.cause)} leads early; ${then.cause} overtakes it at about `
    + `${formatNumber(then.from)}${unit ? ` ${unit}` : ""}.`;
}

// A regression coefficient in words (#177's advanced choice): "Each +1 in
// duty_pct multiplies the bearing wear failure rate by 1.13".
export function effectSentence(coef, ratioLabel) {
  if (!coef || coef.ratio == null) return "";
  const what = ratioLabel === "subdistribution hazard ratio"
    ? `the chance of failing from ${coef.cause}` : `the ${coef.cause} failure rate`;
  return `Each +1 in ${coef.covariate} multiplies ${what} by ${formatNumber(coef.ratio, { sig: 3 })}`;
}

// The all-cause curve's key: "any mode" in the calculator and the tables.
export const ANY_MODE = "__any__";

// The chance of failing from any mode by ``t``, with its 95% band (the
// all-cause Kaplan-Meier bounds): { cif, lower, upper }.
export function anyAt(result, t) {
  const c = result?.curves;
  if (!c) return { cif: null, lower: null, upper: null };
  return {
    cif: stepAt(c.x, c.all, t),
    lower: stepAt(c.x, c.all_lower, t),
    upper: stepAt(c.x, c.all_upper, t),
  };
}

// The stored curves of one mode (or ANY_MODE): { y, lower, upper }.
export function modeCurves(result, mode) {
  const c = result?.curves || {};
  if (mode === ANY_MODE) return { y: c.all || [], lower: c.all_lower || [], upper: c.all_upper || [] };
  return { y: c.cif?.[mode] || [], lower: c.lower?.[mode] || [], upper: c.upper?.[mode] || [] };
}

// The first time a step curve reaches ``p``: the curve is non-decreasing and
// right-continuous, so it is the first stored point at or above it. Null if
// it never gets there within the data.
export function firstReach(xs, ys, p) {
  if (!xs?.length || !ys?.length || !Number.isFinite(p)) return null;
  for (let i = 0; i < xs.length; i += 1) {
    const y = ys[i];
    if (y != null && Number.isFinite(y) && y >= p - 1e-12) return xs[i];
  }
  return null;
}

// The time by which a share ``p`` (0–1) of units have failed from ``mode``
// (a mode's name or ANY_MODE): { time, lower, upper, top, last }. The 95%
// range comes from the band: the upper curve reaches ``p`` first (the
// earliest time), the lower one last (the latest). ``time`` is null when
// the curve never reaches ``p`` within the data; ``top`` is then how far it
// gets by ``last``, the last time in the data.
export function timeToChance(result, mode, p) {
  const xs = result?.curves?.x || [];
  const { y, lower, upper } = modeCurves(result, mode);
  const known = y.filter((v) => v != null && Number.isFinite(v));
  return {
    time: firstReach(xs, y, p),
    lower: firstReach(xs, upper, p),
    upper: firstReach(xs, lower, p),
    top: known.length ? Math.max(...known) : null,
    last: xs.length ? xs[xs.length - 1] : null,
  };
}

// How much data stands behind each mode's curve, for Diagnostics: each
// mode's failures and the width of its 95% band at the horizon, with a
// verdict. A mode resting on fewer than ``few`` failures is flagged: its
// curve is a handful of steps and its band is wide.
export const FEW_FAILURES = 5;
export function modeSupport(result, few = FEW_FAILURES) {
  const rows = (result?.causes || []).map((k) => {
    const at = k.at || {};
    const width = at.lower != null && at.upper != null ? at.upper - at.lower : null;
    return { name: k.name, failures: k.failures, cif: at.cif ?? null, lower: at.lower ?? null,
             upper: at.upper ?? null, width, few: Number(k.failures) < few };
  });
  const thin = rows.filter((r) => r.few);
  const words = !rows.length ? ""
    : thin.length
      ? `${thin.map((r) => cap(r.name)).join(", ")} ${thin.length === 1 ? "rests" : "rest"} on fewer than ${few} `
        + "failures: read those curves as rough."
      : `Every mode has at least ${few} failures behind its curve.`;
  return { rows, tone: !rows.length ? undefined : thin.length ? "caveat" : "good", words };
}

// The widest 95% band at the horizon, in words: "Bearing wear is the least
// certain: 28% to 52% by 5,000 hours." Empty without bands.
export function widestBand(result, unit = "") {
  const rows = modeSupport(result).rows.filter((r) => r.width != null);
  if (!rows.length) return "";
  const w = rows.reduce((a, b) => (b.width > a.width ? b : a));
  const when = `${formatNumber(result.horizon)}${unit ? ` ${unit}` : ""}`;
  return `${cap(w.name)} is the least certain: between ${pct(w.lower)} and ${pct(w.upper)} of units by ${when}.`;
}

// The incidence table for the Data tab: one row per stored time where any
// curve steps (the failure times), each mode's chance and any mode's.
export function incidenceRows(result) {
  const c = result?.curves || {};
  const xs = c.x || [];
  const names = (result?.causes || []).map((k) => k.name);
  const out = [];
  let prev = null;
  xs.forEach((x, i) => {
    const vals = names.map((n) => c.cif?.[n]?.[i] ?? null);
    const any = c.all?.[i] ?? null;
    const key = [...vals, any].join("|");
    if (key !== prev && (any || vals.some(Boolean))) out.push({ x, modes: vals, any });
    prev = key;
  });
  return out;
}

// The regression by mode in words, one line per mode: { mode, lines: [...] }.
export function effectsByMode(regression) {
  if (!regression?.coefficients?.length) return [];
  const by = new Map();
  for (const c of regression.coefficients) {
    if (!by.has(c.cause)) by.set(c.cause, []);
    by.get(c.cause).push(c);
  }
  return [...by.entries()].map(([mode, rows]) => ({
    mode,
    lines: rows.map((c) => {
      const base = effectSentence(c, regression.ratio_label);
      if (!base) return { covariate: c.covariate, text: `${c.covariate}: no estimate.` };
      const ci = c.ratio_ci?.[0] != null && c.ratio_ci?.[1] != null
        ? ` (95% ${formatNumber(c.ratio_ci[0])} to ${formatNumber(c.ratio_ci[1])})` : "";
      const none = c.ratio_ci?.[0] != null && c.ratio_ci[0] <= 1 && c.ratio_ci[1] >= 1
        ? ". The interval includes 1, so the data can't rule out no effect" : "";
      return { covariate: c.covariate, text: `${base}${ci}${none}.`, p: c.p_value ?? null };
    }),
  }));
}
