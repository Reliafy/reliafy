// Pure helpers for the cost of ownership over several horizons (#319) and a
// safety function's PFD(t) chart (#322), shared by AvailabilityCosts,
// RbdCheapestDesign and RbdPfdChart (and tested with node --test).
import { unitInText } from "./components/unitText.js";

const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(5)).toLocaleString());

// A horizon in words: "5 years", "87,600 hours", or "For ever" (endless).
export function horizonWords(row, unit) {
  if (row.endless) return "For ever";
  const years = row.years;
  if (years != null && years >= 1 && Math.abs(years - Math.round(years)) < 1e-9) {
    const n = Math.round(years);
    return `${n} year${n === 1 ? "" : "s"}`;
  }
  return `${fmtT(row.horizon)}${unit ? ` ${unitInText(unit)}` : ""}`;
}

// The copies a horizon's cheapest design adds: "Pump ×2, Valve ×2", or "As drawn".
export function copiesText(copies) {
  const more = (copies || []).filter((c) => c.copies !== 1);
  return more.length ? more.map((c) => `${c.label} ×${c.copies}`).join(", ") : "As drawn";
}

// SIL n is [10^-(n+1), 10^-n) (IEC 61508-1, low demand): its upper limit.
export const silLimit = (n) => 10 ** -n;

// The decades a PFD(t) log axis spans, [lo, hi] as powers of ten: down to two
// below the PFDavg (or to the lowest PFD, if that is higher), up to the decade
// above the band limit drawn (or the highest PFD), within [1e-9, 1]. null
// with nothing to draw.
export function pfdRange(values, pfdAvg, limit) {
  const pos = (values || []).filter((v) => v != null && v > 0 && Number.isFinite(v));
  if (!pos.length) return null;
  const lowest = Math.min(...pos);
  const highest = Math.max(...pos);
  const anchor = pfdAvg > 0 ? pfdAvg : highest;
  const lo = Math.max(-9, Math.floor(Math.log10(anchor)) - 2, Math.floor(Math.log10(lowest)));
  const top = Math.max(highest, limit ? silLimit(limit) : 0, pfdAvg || 0);
  const hi = Math.min(0, Math.floor(Math.log10(top) + 1e-9) + 1);
  return [lo, Math.max(hi, lo + 1)];
}

// The SIL bands (1–4) inside a range of decades.
export const bandsIn = (range) => [1, 2, 3, 4].filter((n) => -(n + 1) < range[1] && -n > range[0]);
