// A regression model's own assumption checks (diagnostics.model_checks, from
// SurPyval's diagnose()) as rows for the Diagnostics tab. Pure functions, so
// `node --test` covers them.

const VERDICT_WORDS = { ok: "Passes", warn: "Borderline", fail: "Fails" };

// The card's tone: bad if any check fails, caveat if any is borderline.
export function checksTone(mc) {
  if (!mc?.available || !mc.rows?.length) return undefined;
  if (mc.rows.some((r) => r.verdict === "fail")) return "bad";
  if (mc.rows.some((r) => r.verdict === "warn")) return "caveat";
  return "good";
}

// "p = 0.012", "p < 0.001", or "" when the check has no p-value.
export function pText(p) {
  if (p == null || !Number.isFinite(Number(p))) return "";
  const v = Number(p);
  return v < 0.001 ? "p < 0.001" : `p = ${v.toFixed(v < 0.01 ? 4 : 3)}`;
}

// The table rows, problems first (fail, then borderline, then passing),
// keeping SurPyval's order within each.
export function checkRows(mc) {
  const rank = { fail: 0, warn: 1, ok: 2 };
  return (mc?.rows || [])
    .map((r, i) => ({
      key: `${r.check}-${(r.covariates || []).join("+")}-${i}`,
      title: r.title,
      covariates: (r.covariates || []).join(", "),
      verdict: r.verdict,
      verdictLabel: VERDICT_WORDS[r.verdict] || r.verdict,
      p: pText(r.p),
      detail: r.detail,
      // Several rows share a check (calibration at three times): say which.
      sub: r.check === "calibration" && r.test ? `${r.test}: ${r.detail}` : r.detail,
      order: rank[r.verdict] ?? 3,
      i,
    }))
    .sort((a, b) => a.order - b.order || a.i - b.i);
}
