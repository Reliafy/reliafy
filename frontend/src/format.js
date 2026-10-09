// Number formatting for results (#310, #311): thousands separators, about
// three significant figures, and no scientific notation for everyday sizes
// (0.001 up to 10 million). Callers format; components only display.

const MISSING = "—";

// 4573.2 → "4,570"; 580.28 → "580"; 0.58371 → "0.584"; 12 → "12";
// 0.000123 → "1.23e-4"; 2.5e8 → "2.5e8". sig sets the significant figures
// (pass 4 where a reader compares close values).
export function formatNumber(v, { sig = 3 } = {}) {
  if (v == null || v === "") return MISSING;
  const n = Number(v);
  if (!Number.isFinite(n)) return MISSING;
  if (n === 0) return "0";
  const a = Math.abs(n);
  if (a < 0.001 || a >= 1e7) {
    const [m, e] = n.toExponential(sig - 1).split("e");
    const mant = m.includes(".") ? m.replace(/\.?0+$/, "") : m;
    return `${mant}e${Number(e)}`;
  }
  return new Intl.NumberFormat("en-US", { maximumSignificantDigits: sig }).format(n);
}

// A fraction as a percentage: 0.5714 → "57%", 0.0532 → "5.3%", 0.00123 → "0.12%".
export function formatPercent(fraction, { sig = 2 } = {}) {
  if (fraction == null || fraction === "") return MISSING;
  const p = Number(fraction) * 100;
  if (!Number.isFinite(p)) return MISSING;
  const a = Math.abs(p);
  if (a === 0) return "0%";
  if (a >= 10) return `${Math.round(p).toLocaleString("en-US")}%`;
  return `${formatNumber(p, { sig })}%`;
}

// A value with its unit: (4573.2, "hours") → "4,570 hours".
export function formatWithUnit(v, unit, opts) {
  const s = formatNumber(v, opts);
  return unit && s !== MISSING ? `${s} ${unit}` : s;
}
