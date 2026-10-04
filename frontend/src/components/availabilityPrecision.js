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

// A difference of fractions in percentage points, signed.
export const pointsAt = (v, digits) =>
  v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}`;

// The footnote sentence for an availability result, or "" for a result saved
// before the precision report existed.
export function precisionNote(result) {
  const p = result?.precision;
  if (!p || p.window_availability == null) return "";
  const conf = Math.round((p.confidence || 0.95) * 100);
  const d = pctDigits(p.half_width || p.tolerance);
  const n = (p.n_simulations ?? result.n_simulations)?.toLocaleString();
  // Exact (RePyability's mission availability) where it can be; the interval
  // is the simulation's own, which sets its precision.
  const exact = p.window_availability_basis === "exact" || p.window_availability_basis === "numerical";
  const ci = p.lower != null && p.upper != null ? `${conf}% CI ${pctAt(p.lower, d)} to ${pctAt(p.upper, d)}` : "";
  const interval = exact
    ? ` (exact${ci ? `; the simulation's ${ci}` : ""})`
    : ci ? ` (${ci})` : "";
  const lead = exact
    ? ` Over that window the system is up ${pctAt(p.window_availability, d)} of the time${interval}`
    : ` Over that window the system was up ${pctAt(p.window_availability, d)} of the time${interval}`;
  const target = `±${Math.abs(p.tolerance * 100).toFixed(pctDigits(p.tolerance))}-point`;
  if (p.mode === "fixed") return `${lead}, from a fixed ${n} replications.`;
  if (p.reached) return `${lead}: within the ${target} precision target, reached after ${n} replications.`;
  return `${lead}: the ${target} precision target wasn't reached within the time budget (${n} replications), so the interval shows the precision achieved.`;
}
