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
