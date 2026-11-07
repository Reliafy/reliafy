// Plain-language wording for the availability simulation's precision (#104):
// the window's mean availability with its confidence interval, and whether the
// run reached its precision target. Shared by the availability panel's
// footnote and the "Compare with…" panel.

// Decimal places that show a value to about two significant figures of its
// uncertainty `spread` (both as fractions; shown as percentages).
export function pctDigits(spread) {
  const s = Math.abs(spread) * 100;
  if (!Number.isFinite(s) || s <= 0) return 3;
  return Math.min(8, Math.max(1, Math.ceil(-Math.log10(s)) + 1));
}

// A fraction as a percentage with `digits` decimals.
export const pctAt = (v, digits) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

// An availability to about four significant figures: 0.99968 → "99.97%",
// 0.9512 → "95.12%", 0.0731 → "7.310%". Close to 100% the downtime says more
// than more decimals would, so see downPct.
export function availabilityPct(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const p = v * 100;
  const digits = p >= 10 ? 2 : p >= 1 ? 3 : 4;
  return `${p.toFixed(digits)}%`;
}

// Above this an availability is quoted with its downtime ("down 0.031%").
export const HIGH_AVAILABILITY = 0.999;

// The unavailability (1 − A) as a percentage, to three significant figures:
// 0.99968579 → "0.0314%".
export function downPct(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const d = Math.max(0, 1 - v) * 100;
  if (d === 0) return "0%";
  return `${Number(d.toPrecision(3)).toString()}%`;
}

// A difference of fractions in percentage points, signed.
export const pointsAt = (v, digits) =>
  v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}`;

// The footnote sentence for an availability result, or "" for a result saved
// before the precision report existed.
export function precisionNote(result) {
  const p = result?.precision;
  if (!p || p.window_availability == null) return "";
  const conf = Math.round((p.confidence || 0.95) * 100);
  // About four significant figures (#UX): more digits than that read as false
  // precision; near 100% the downtime carries the detail.
  const fmt = (v) =>
    v != null && v > HIGH_AVAILABILITY ? `${availabilityPct(v)} (down ${downPct(v)})` : availabilityPct(v);
  const n = (p.n_simulations ?? result.n_simulations)?.toLocaleString();
  // Exact (RePyability's mission availability) where it can be; the interval
  // is the simulation's own, which sets its precision.
  const exact = p.window_availability_basis === "exact" || p.window_availability_basis === "numerical";
  const ci = p.lower != null && p.upper != null ? `${conf}% CI ${fmt(p.lower)} to ${fmt(p.upper)}` : "";
  // With an exact headline the interval is centred on the simulation's own
  // mean, not on the exact value: show that mean beside it (#262).
  const simMean = p.simulated_window_availability;
  const own = simMean != null ? `simulated ${fmt(simMean)}, ` : "";
  const interval = exact
    ? ` (exact${ci ? `; the simulation's own estimate: ${own}${ci}` : ""})`
    : ci ? ` (${ci})` : "";
  const lead = exact
    ? ` Over that window the system is up ${fmt(p.window_availability)} of the time${interval}`
    : ` Over that window the system was up ${fmt(p.window_availability)} of the time${interval}`;
  const target = `±${Math.abs(p.tolerance * 100).toFixed(pctDigits(p.tolerance))}-point`;
  if (p.mode === "fixed") return `${lead}, from a fixed ${n} replications.`;
  // A free quick run (#147): as many replications as fit a few seconds.
  if (p.mode === "quick") return `${lead}: a quick estimate from ${n} replications — Pro runs to the precision target.`;
  if (p.reached) return `${lead}: within the ${target} precision target, reached after ${n} replications.`;
  return `${lead}: the ${target} precision target wasn't reached within the time budget (${n} replications), so the interval shows the precision achieved.`;
}
