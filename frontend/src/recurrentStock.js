// A repairable model's count over a stretch, as the Calculator shows it: the
// range of how many failures there will be (chance and the fit's own
// uncertainty), the expected number's own narrower range, the stock to hold
// for a chosen chance of not running out (spares in parts; the dollars are
// worked out elsewhere), and the same stretch at the record's average rate.
import { formatNumber } from "./format.js";
import { riskText } from "./sparesPlan.js";

const n3 = (v) => formatNumber(v, { sig: 3 });
const whole = (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US"));

// "4–15", or null when the range is missing.
export function countRange(ci) {
  if (!ci || !Number.isFinite(ci[0]) || !Number.isFinite(ci[1])) return null;
  return `${whole(ci[0])}–${whole(ci[1])}`;
}

// "5.97–11.9", or null.
export function meanRange(ci) {
  if (!ci || !Number.isFinite(ci[0]) || !Number.isFinite(ci[1])) return null;
  return `${n3(ci[0])}–${n3(ci[1])}`;
}

// The chance a stock runs out, and one fewer's: "9.4% chance of running out
// (12 would be 14%)".
export function runoutText(stock) {
  if (!stock || stock.hold == null) return null;
  let text = `${riskText(stock.runout)} chance of running out`;
  if (stock.hold >= 1 && stock.runout_one_less != null) {
    text += ` (${whole(stock.hold - 1)} would be ${riskText(stock.runout_one_less)})`;
  }
  return text;
}

// The record's average rate over the same stretch: "16 (48 failures in
// 216,000 hours)".
export function constantRateText(cr, unit = "") {
  if (!cr || cr.expected == null) return null;
  const u = unit ? ` ${unit}` : "";
  return `${n3(cr.expected)} (${whole(cr.failures)} failure${cr.failures === 1 ? "" : "s"} in ${whole(Math.round(cr.exposure))}${u})`;
}

// The service levels to choose from, as Select options.
export function levelOptions(levels) {
  return levels.map((l) => ({ value: String(l), label: `${Math.round(l * 1000) / 10}%` }));
}
