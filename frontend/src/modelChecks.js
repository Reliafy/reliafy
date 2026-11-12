// A regression model's own assumption checks (diagnostics.model_checks, from
// SurPyval's diagnose()) as rows for the Diagnostics tab. Pure functions, so
// `node --test` covers them.

import { termName } from "./modelFrame.js";

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
      covariates: (r.covariates || []).map((c) => termName(c).label).join(", "),
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

// The two proportional-hazards checks on one page can disagree: the card's
// Grambsch–Therneau test (a steady drift in an effect over time, from a Cox
// model on the same covariates) and the model's own check in the table (a
// step in the effect at the median failure time). A sentence that says which
// covariates they disagree on and how to read it; null when they agree.
// ``ph``: diagnostics.ph_test; ``mc``: diagnostics.model_checks.
export function phDisagreement(ph, mc) {
  if (!ph?.available || !mc?.available) return null;
  const stepRows = (mc.rows || []).filter((r) => r.check === "proportional_hazards" && (r.covariates || []).length === 1);
  if (!stepRows.length) return null;
  const step = Object.fromEntries(stepRows.map((r) => [r.covariates[0], r]));
  const alpha = Number(ph.alpha) || 0.05;
  const drift = (ph.rows || []).filter((r) => step[r.covariate]);
  const onlyDrift = drift.filter((r) => Number(r.p) < alpha && step[r.covariate].verdict === "ok");
  const onlyStep = drift.filter((r) => Number(r.p) >= alpha && step[r.covariate].verdict === "fail");
  if (!onlyDrift.length && !onlyStep.length) return null;
  const names = (rows) => rows.map((r) => termName(r.covariate).label).join(", ");
  const parts = [];
  if (onlyDrift.length) {
    parts.push(`For ${names(onlyDrift)}, this test sees a slow drift over time (${onlyDrift.map((r) => pText(r.p)).join(", ")}) `
      + `but the model's own check below finds no jump at the median failure time (${onlyDrift.map((r) => pText(step[r.covariate].p)).join(", ")}).`);
  }
  if (onlyStep.length) {
    parts.push(`For ${names(onlyStep)}, the model's own check below finds a jump at the median failure time, `
      + "though this test sees no steady drift.");
  }
  parts.push("They look for different shapes of change, so one flag alone is weak evidence: look at the residual "
    + "plot for a trend before acting on it.");
  return parts.join(" ");
}
