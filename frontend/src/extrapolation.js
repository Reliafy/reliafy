// When an answer lies outside the data it came from, the words that say so.
// One wording everywhere (the ExtrapolationNote): a life model's Calculator
// (a time before the first failure, or past the oldest unit seen) and an
// accelerated life model's use stress (outside the tested stresses).
import { formatNumber } from "./format.js";

const RESTS = "The answer comes from the fitted curve's shape alone, not from failures seen there: "
  + "treat it as a rough guide, and quote it with that caveat.";

// A life model's answer against where its data sit in time. ``range``:
// { first_failure, last_seen } from the fit (data_range); ``lo`` / ``hi``: the
// earliest and latest times the answer stands on (a time typed, a time found,
// or the bound on it); ``unit``: the time unit in words. Null when inside.
export function timeExtrapolation(range, lo, hi, unit = "") {
  const first = Number(range?.first_failure);
  const last = Number(range?.last_seen);
  const u = unit ? ` ${unit}` : "";
  const t = (v) => `${formatNumber(v)}${u}`;
  if (Number.isFinite(first) && Number.isFinite(lo) && lo < first) {
    return `${t(lo)} is before the first failure in the data (${t(first)}). ${RESTS}`;
  }
  if (Number.isFinite(last) && Number.isFinite(hi) && hi > last) {
    return `${t(hi)} is past the oldest age in the data (${t(last)}). ${RESTS}`;
  }
  return null;
}

// An accelerated life model's use stress outside the tested ones: ``parts``,
// one phrase per stress ("20 kV is well below the tested 30–36 kV");
// ``factor``: the acceleration factor, if known.
export function stressExtrapolation(parts, factor = null) {
  if (!parts?.length) return null;
  const af = Number.isFinite(factor) ? ` (an acceleration factor of ${formatNumber(factor, { sig: 4 })}×)` : "";
  return `${parts.join("; ")}${af}. The life here rests on the life-stress relationship holding that far, `
    + "not on failures seen there: treat it as a rough guide, and test nearer the use stress if the decision "
    + "depends on it.";
}
