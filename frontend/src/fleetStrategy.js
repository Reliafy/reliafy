// A fleet forecast's strategy answer, in words and numbers for the card and
// the CSV (FleetStrategy.jsx, fleetCsv.js). Pure, so node --test covers it.

const PERIODS_A_QUARTER = { month: 3, months: 3, quarter: 1, quarters: 1, week: 13, weeks: 13 };

// "44–54": a block's 90% range, each end formatted by ``fmt``.
export function rangeText(block, fmt = String) {
  const [lo, hi] = block?.interval || [];
  if (lo == null || hi == null) return null;
  return `${fmt(lo)}–${fmt(hi)}`;
}

// The parts the first quarter needs (the lead time most parts are ordered
// on): { periods, parts }, or null when the periods aren't months, weeks or
// quarters, or the horizon is shorter.
export function firstPeriodsParts(strategy, periodLabel) {
  const n = PERIODS_A_QUARTER[String(periodLabel || "").trim().toLowerCase()];
  const rows = strategy?.per_period || [];
  if (!n || rows.length < n) return null;
  return { periods: n, parts: rows.slice(0, n).reduce((a, r) => a + (r.parts?.expected || 0), 0) };
}
