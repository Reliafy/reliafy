// What a dataset can be fitted with, from its tags (#261), usual fit first:
// the Data list's row menu. A dataset stands alone: only fits that take this one
// dataset are offered (condition monitoring, which takes two, is on its own page).
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repairable")) return [{ label: "Repairable model", to: `/modelling/recurrent/new?dataset=${id}` }];
  if (t.includes("Measurements")) return [{ label: "Degradation model", to: `/modelling/degradation?dataset=${id}` }];
  const covs = t.includes("Covariates") || t.includes("Time-varying covariates");
  return [{ label: covs ? "Life model with covariates" : "Life model", to: `/modelling/new?dataset=${id}` }];
}
