// What a dataset can be fitted with, from its tags (#261), usual fit first:
// the Data list's row menu. Condition monitoring needs lifetimes and readings
// of the same units, so it's offered only with a partner dataset (pairs_with),
// and opens with both tables filled in.
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repairable")) return [{ label: "Repairable model", to: `/modelling/recurrent/new?dataset=${id}` }];
  const pairs = d.pairs_with || [];
  const readings = t.includes("Measurements");
  // One entry: with one partner both tables are filled; with several, this one
  // is, and the other is picked on the page.
  const cm = pairs.length === 0 ? [] : [{
    label: "Condition monitoring",
    to: pairs.length === 1
      ? (readings ? `/modelling/joint/new?lifetimes=${encodeURIComponent(pairs[0].id)}&readings=${id}`
        : `/modelling/joint/new?lifetimes=${id}&readings=${encodeURIComponent(pairs[0].id)}`)
      : `/modelling/joint/new?${readings ? "readings" : "lifetimes"}=${id}`,
  }];
  if (readings) return [{ label: "Degradation model", to: `/modelling/degradation?dataset=${id}` }, ...cm];
  const covs = t.includes("Covariates") || t.includes("Time-varying covariates");
  return [{ label: covs ? "Life model with covariates" : "Life model", to: `/modelling/new?dataset=${id}` }, ...cm];
}
