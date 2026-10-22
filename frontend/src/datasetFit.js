// What a dataset can be fitted with, from its tags (#261), usual fit first:
// the Data list's row menu. A dataset stands alone: only fits that take this one
// dataset are offered (condition monitoring, which takes two, is on its own page).
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repairable")) return [{ label: "Repairable model", to: `/modelling/recurrent/new?dataset=${id}` }];
  // Life data and readings in one table: condition monitoring takes it for both.
  if (t.includes("Measurements") && t.includes("Non-repairable")) {
    return [{ label: "Condition monitoring model", to: `/modelling/joint/new?lifetimes=${id}&readings=${id}` }];
  }
  if (t.includes("Measurements")) return [{ label: "Degradation model", to: `/modelling/degradation?dataset=${id}` }];
  const covs = t.includes("Covariates") || t.includes("Time-varying covariates");
  return [{ label: covs ? "Non-repairable model with covariates" : "Non-repairable model", to: `/modelling/new?dataset=${id}` }];
}

// The saved datasets a "new model" flow can use, from their tags: each flow
// offers only these. Datasets with no tags field (an older server) are kept.
//   life        Non-repairable model (with or without covariates)
//   repairable  Repairable model
//   accelerated accelerated-life model: lifetimes with a stress covariate
//   degradation measurements with no outcome column
//   lifetimes   condition monitoring's lifetimes (or one table holding both)
//   readings    condition monitoring's readings (or one table holding both)
const USABLE = {
  life: (t) => t.includes("Non-repairable"),
  repairable: (t) => t.includes("Repairable"),
  accelerated: (t) => t.includes("Non-repairable") && t.includes("Covariates"),
  degradation: (t) => t.includes("Measurements") && !t.includes("Non-repairable"),
  lifetimes: (t) => t.includes("Non-repairable"),
  readings: (t) => t.includes("Measurements"),
};

export function usableFor(kind, d) {
  if (!Array.isArray(d?.tags)) return true;
  const rule = USABLE[kind];
  return rule ? rule(d.tags) : true;
}

export const usableDatasets = (kind, datasets) => (datasets || []).filter((d) => usableFor(kind, d));
