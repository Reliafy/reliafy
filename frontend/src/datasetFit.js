// What a dataset can be fitted with, from its tags (#261), usual fit first:
// the Data list's row menu. Condition monitoring needs lifetimes and readings
// of the same units, so it's offered only with a partner dataset (pairs_with),
// and opens with both tables filled in.
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repairable")) return [{ label: "Repairable model", to: `/modelling/recurrent/new?dataset=${id}` }];
  const pairs = d.pairs_with || [];
  const many = pairs.length > 1;
  if (t.includes("Measurements")) {
    return [
      { label: "Degradation model", to: `/modelling/degradation?dataset=${id}` },
      ...pairs.map((p) => ({
        label: many ? `Condition monitoring with ${p.name}` : "Condition monitoring",
        to: `/modelling/joint/new?lifetimes=${encodeURIComponent(p.id)}&readings=${id}`,
      })),
    ];
  }
  const covs = t.includes("Covariates") || t.includes("Time-varying covariates");
  return [
    { label: covs ? "Life model with covariates" : "Life model", to: `/modelling/new?dataset=${id}` },
    ...pairs.map((p) => ({
      label: many ? `Condition monitoring with ${p.name}` : "Condition monitoring",
      to: `/modelling/joint/new?lifetimes=${id}&readings=${encodeURIComponent(p.id)}`,
    })),
  ];
}
