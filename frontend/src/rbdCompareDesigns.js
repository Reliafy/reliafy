// Non-repairable designs side by side (the RBD Calculator's "Compare with
// other designs"): each design's reliability at the time asked about, MTTF and
// B-lives, every one from the same exact analysis the Calculator runs —
// R(t) is the analysis' own value at the time (``evaluate_at``), not read off
// a curve. Display only: every number comes from the server.

// One design's row from its analysis result.
export function designRow(name, result, { id = null, current = false } = {}) {
  const imp = result?.importance || {};
  return {
    id,
    name,
    current,
    reliability: imp.time_basis === "given" && Number.isFinite(imp.reliability) ? imp.reliability : null,
    mttf: Number.isFinite(result?.mttf) ? result.mttf : null,
    b10: Number.isFinite(result?.blife?.b10) ? result.blife.b10 : null,
    b50: Number.isFinite(result?.blife?.b50) ? result.blife.b50 : null,
    unit: result?.unit || "",
    singlePoints: (result?.structure?.min_cut_sets || []).filter((s) => s.length === 1).length,
  };
}

// The id of the row with the highest value of ``key`` (null on a tie for
// first, or with fewer than two values).
export function bestOf(rows, key) {
  const vals = rows.filter((r) => r[key] != null);
  if (vals.length < 2) return null;
  const top = Math.max(...vals.map((r) => r[key]));
  const winners = vals.filter((r) => Math.abs(r[key] - top) <= 1e-12 * Math.max(1, Math.abs(top)));
  return winners.length === 1 ? (winners[0].id ?? winners[0].name) : null;
}

// Whether two diagrams' time units differ (their figures can't be compared as numbers).
export const unitClash = (rows) => new Set(rows.map((r) => (r.unit || "").trim().toLowerCase())).size > 1;
