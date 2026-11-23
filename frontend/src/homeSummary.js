// Home's one request (GET /api/home/summary) as the pieces Home draws from.
// Each section of the summary is exactly what its own list endpoint answers, so
// this hands Home what it used to read from fourteen requests:
//   lists        { models, datasets, rbds, forecasts, analyses, tracked, failed, trackedFailed }
//   changes      What changed (null: it couldn't be read)
//   access       whether this viewer has Reliafy Maintenance (null: unknown)
//   maintenance  the Maintenance overview (undefined without Maintenance; null: couldn't be read)
//   rcm          the RCM rollup (as maintenance)
//   failedParts  the names of the parts that failed (cardFailed says which lists they spoil)
// `summary` null: the request itself failed, so every section says it couldn't load.
import { modelRows } from "./modelRows.js";

// The parts the lists are built from; any failing makes Home's counts a guess
// (`failed`), except Condition and life's, which the Models list also reads quietly.
const LIST_PARTS = ["models", "alt_models", "recurrent_models", "degradation_models", "datasets", "rbds",
  "fleets", "strategy_analyses", "tracked_fleets"];

// The parts each of Home's own lists is drawn from: one failing gives that list
// its error card (with Try again) and leaves the others as they are.
export const CARD_PARTS = {
  "recent-models": ["models", "alt_models", "recurrent_models", "degradation_models"],
  "recent-data": ["datasets"],
  "recent-systems": ["rbds"],
  fleets: ["fleets", "tracked_fleets"],
  recent: LIST_PARTS,
};

// Whether any part a list (CARD_PARTS) is drawn from failed.
export function cardFailed(card, failedParts = []) {
  return (CARD_PARTS[card] || []).some((p) => failedParts.includes(p));
}

export function homeFromSummary(summary) {
  if (!summary) {
    return {
      lists: { models: [], datasets: [], rbds: [], forecasts: [], analyses: [], tracked: [], failed: true,
        trackedFailed: true },
      changes: null, access: null, maintenance: null, rcm: null, failedParts: LIST_PARTS,
    };
  }
  const s = summary.sections || {};
  const errors = summary.errors || {};
  const list = (part, key) => (s[part]?.[key]) || [];
  const models = modelRows({
    life: s.models, degradation: s.degradation_models, alt: s.alt_models, recurrent: s.recurrent_models,
    joint: s.joint_models,
  });
  const access = !!summary.maintenance;
  const part = (name) => (name in errors ? null : s[name] ?? null);
  return {
    lists: {
      models,
      datasets: list("datasets", "datasets"),
      rbds: list("rbds", "rbds"),
      forecasts: list("fleets", "fleets"),
      analyses: list("strategy_analyses", "analyses"),
      tracked: list("tracked_fleets", "fleets"),
      failed: LIST_PARTS.some((p) => p in errors),
      trackedFailed: "tracked_fleets" in errors,
    },
    changes: part("changes"),
    access,
    maintenance: access ? part("maintenance_overview") : undefined,
    rcm: access ? part("rcm_rollup") : undefined,
    failedParts: Object.keys(errors),
    // The lists the first-run starts are worked out from (firstRun.js firstRunFrom).
    firstRunLists: {
      models: list("models", "models"), datasets: list("datasets", "datasets"), rbds: list("rbds", "rbds"),
      alt: list("alt_models", "models"), recurrent: list("recurrent_models", "models"),
      degradation: list("degradation_models", "models"),
    },
  };
}
