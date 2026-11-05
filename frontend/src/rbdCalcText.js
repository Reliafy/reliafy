// Plain words for the RBD calculator's figures: a reliability that keeps the
// digits that matter near 1, a failure probability with its "1 in N", and the
// time it's over. Display only: every number comes from the calculation.
import { formatNumber, formatPercent } from "./format.js";
import { unitInText } from "./components/unitText.js";

const MISSING = "—";
// Below this a failure probability is rounding, not a result.
const TINY = 1e-12;

// A reliability to four significant figures, except near 1, where it keeps
// enough decimals for the gap to 1 to show to two figures: 0.99994, not 0.9999
// (which would hide a failure probability of 6 in 100,000).
export function formatReliability(v) {
  if (v == null || !Number.isFinite(Number(v))) return MISSING;
  const r = Number(v);
  if (1 - r < TINY) return "1";
  if (r <= 0) return "0";
  if (r > 0.999) {
    const decimals = Math.min(12, Math.floor(-Math.log10(1 - r)) + 2);
    return r.toFixed(decimals).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (r < 1e-3) return formatNumber(r, { sig: 3 });
  return String(Number(r.toPrecision(4)));
}

const SUPERSCRIPT = { "-": "⁻", 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹" };

// A small probability as "6.0 × 10⁻⁵"; from 1% up, a percentage ("10%").
export function formatProbability(p) {
  if (p == null || !Number.isFinite(Number(p))) return MISSING;
  const f = Number(p);
  if (f <= 0) return "0";
  if (f >= 0.01) return formatPercent(f);
  const [m, e] = f.toExponential(1).split("e");
  return `${m} × 10${String(Number(e)).split("").map((c) => SUPERSCRIPT[c]).join("")}`;
}

// "16,700" in "about 1 in 16,700": for a failure probability under 1% (above
// that, the percentage says it plainly).
export function oneIn(p) {
  const f = Number(p);
  if (!(f > 0 && f < 0.01)) return null;
  return Number((1 / f).toPrecision(3)).toLocaleString("en-US");
}

// "1 hour", "8,760 hours", "200 cycles": a time the user typed, in words.
export function timeInWords(t, unit) {
  const n = Number(t);
  const num = n.toLocaleString("en-US", { maximumSignificantDigits: 6 });
  const u = unitInText(unit || "");
  if (!u) return num;
  return `${num} ${n === 1 && /s$/.test(u) && u !== u.toUpperCase() ? u.slice(0, -1) : u}`;
}

// The answer at the time the user asked about: what the reliability is over,
// the reliability, and the failure probability in words.
export function answerAtTime({ r, t, unit, now = false, survived = 0 }) {
  if (r == null || !Number.isFinite(Number(r)) || t == null || t === "") return null;
  const span = timeInWords(t, unit);
  const over = now
    ? `the next ${span}`
    : survived > 0
    ? `a further ${span}, having survived ${timeInWords(survived, unit)}`
    : `the first ${span}`;
  const f = 1 - Number(r);
  const n = oneIn(f);
  const failure = f < TINY
    ? "No failures expected in that time, to the precision calculated."
    : `Failure probability ${formatProbability(f)}${n ? `: about 1 in ${n} systems fail in that time` : ""}.`;
  return { over, reliability: formatReliability(r), failure };
}
