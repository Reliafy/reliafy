// The saved-data picker's list (components/DatasetPicker.jsx): the user's own
// datasets first, then the shared samples; in each, the ones this fit can use
// first and the rest greyed with a one-line reason. A search narrows both by
// name, tag or summary. Every dataset is listed (no "newest five"): a sample
// seeded after a user's upload must never push it out of reach.
import { usableFor } from "./datasetFit.js";

// Why a dataset doesn't suit a fit, in one line (null when it does).
const WHY_NOT = {
  life: (t) =>
    t.includes("Repairable") ? "Repeated failures of the same units: fit a repairable model instead."
    : t.includes("Measurements") ? "Readings with no failure times: fit a degradation model instead."
    : "No column of times to failure found.",
  repairable: (t) =>
    t.includes("Non-repairable") ? "One life per unit, not repeated failures: fit a non-repairable model instead."
    : t.includes("Measurements") ? "Readings with no failures: fit a degradation model instead."
    : "No repeated failures of the same units found.",
  accelerated: (t) =>
    t.includes("Repairable") ? "Repeated failures of the same units: fit a repairable model instead."
    : t.includes("Non-repairable") ? "No stress column (a covariate such as temperature or load) found."
    : "No times to failure found.",
  degradation: (t) =>
    t.includes("Repairable") ? "Repeated failures of the same units: fit a repairable model instead."
    : "No readings (measurements) found: fit a non-repairable model instead.",
  joint: (t) =>
    t.includes("Repairable") ? "Repeated failures of the same units: fit a repairable model instead."
    : t.includes("Non-repairable") ? "Life data with no measurements yet: add them on its page under Data."
    : t.includes("Measurements") ? "Readings with no failures: fit a degradation model instead."
    : "Needs life data with its measurements.",
};

// ``extra``: the flow's own rule on top of the tags, (dataset) => reason | null.
export function unsuitableReason(kind, d, extra = null) {
  if (usableFor(kind, d)) return extra ? extra(d) || null : null;
  const rule = WHY_NOT[kind];
  return rule ? rule(d.tags || []) : "Not suited to this fit.";
}

const SAMPLE_SUFFIX = /\s*\(sample\)\s*$/i;
export const shownName = (d) => String(d?.name || "Untitled").replace(SAMPLE_SUFFIX, "");

function matches(d, q) {
  if (!q) return true;
  const hay = [d.name, d.summary, ...(d.tags || [])].filter(Boolean).join(" ").toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

// { groups: [{ key, label, rows: [{ dataset, reason }] }], total, shown, usable }
//   kind    the fit ("life", "repairable", ...: datasetFit.usableFor's kinds)
//   query   the search box's text
//   extra   the flow's own rule (unsuitableReason), optional
export function pickerGroups(kind, datasets, query = "", extra = null) {
  const q = String(query || "").trim().toLowerCase();
  const all = Array.isArray(datasets) ? datasets : [];
  const rowsOf = (list) => {
    const rows = list.filter((d) => matches(d, q)).map((d) => ({ dataset: d, reason: unsuitableReason(kind, d, extra) }));
    // Suited first; otherwise the list's own order (newest first) is kept.
    return [...rows.filter((r) => !r.reason), ...rows.filter((r) => r.reason)];
  };
  const groups = [
    { key: "yours", label: "Yours", rows: rowsOf(all.filter((d) => !d.is_sample)) },
    { key: "samples", label: "Samples", rows: rowsOf(all.filter((d) => d.is_sample)) },
  ].filter((g) => g.rows.length > 0);
  const shown = groups.reduce((n, g) => n + g.rows.length, 0);
  const usable = groups.reduce((n, g) => n + g.rows.filter((r) => !r.reason).length, 0);
  return { groups, total: all.length, shown, usable };
}

// "11 Nov 2026" (British order), or "" when the date can't be read.
export function shortDate(iso) {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${t.getUTCDate()} ${months[t.getUTCMonth()]} ${t.getUTCFullYear()}`;
}

export const rowsWords = (n) => `${(n ?? 0).toLocaleString("en-GB")} row${n === 1 ? "" : "s"}`;
