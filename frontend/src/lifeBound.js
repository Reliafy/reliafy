// Life bounds shown as the workspace rule has them: 90% one-sided, a lower bound on
// life (the time left, the crossing time). A degradation item's prediction carries a
// two-sided interval at 1 - alpha_ci (equal tails), so its lower end is a one-sided
// lower bound at 1 - alpha_ci / 2: an 80% interval's lower end is the 90% bound.

// The one-sided level a stored two-sided interval's lower end has: 0.2 → 0.9.
export function oneSidedLevel(alpha, fallback = 0.05) {
  const a = Number(alpha);
  return 1 - (Number.isFinite(a) && a > 0 && a < 1 ? a : fallback) / 2;
}

// The two-sided confidence to ask for, for a one-sided lower bound at `level`: 0.9 → 0.8.
export const twoSidedFor = (level) => Math.round((2 * Number(level) - 1) * 1000) / 1000;

// Whether a stored prediction is already at the one-sided `level` (no round trip needed).
export const atLevel = (pred, level) => pred?.alpha_ci != null
  && Math.abs(oneSidedLevel(pred.alpha_ci) - Number(level)) < 1e-6;

// "90%", "97.5%".
export const levelText = (level) => `${Number((Number(level) * 100).toFixed(1))}%`;

const fmt = (v) => (v == null || !Number.isFinite(Number(v)) ? "—"
  : Number(v).toLocaleString("en-AU", { maximumFractionDigits: 0 }));

// A tracked item's life left: "4,585 hours (at least 4,290, 90%)". Never the interval's upper
// end: life bounds are lower bounds.
export function rulBoundText(pred, unit = "") {
  if (!pred || pred.method === "error" || pred.rul == null) return "—";
  const u = unit ? ` ${unit}` : "";
  const base = `${fmt(pred.rul)}${u}`;
  const lo = (pred.rul_interval || [])[0];
  if (lo == null) return base;
  return `${base} (at least ${fmt(Math.max(0, lo))}, ${levelText(oneSidedLevel(pred.alpha_ci))})`;
}

// The crossing in words: "Expected to cross the limit at 6,585 hours. With 90% confidence it
// won't cross before 6,290 hours: plan for that." (plain text; the page bolds the numbers).
export function crossingBound(pred) {
  const lo = (pred?.failure_time_interval || [])[0];
  if (lo == null) return null;
  return { level: levelText(oneSidedLevel(pred.alpha_ci)), lower: lo };
}
