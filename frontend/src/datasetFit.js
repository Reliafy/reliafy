// What a dataset can be fitted with, from its tags (#261): the first is the
// Fit button, the rest are in its menu.
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repeat failures")) return [{ label: "Repeat failures model", to: `/modelling/recurrent/new?dataset=${id}` }];
  if (t.includes("Measurements")) {
    return [
      { label: "Condition monitoring (as the readings)", to: `/modelling/joint/new?readings=${id}` },
      { label: "Degradation model", to: "/modelling/degradation" },
    ];
  }
  const life = [{ label: t.includes("Covariates") || t.includes("Time-varying covariates") ? "Life model with covariates" : "Life model", to: `/modelling/new?dataset=${id}` }];
  if (t.includes("Lifetime data")) life.push({ label: "Condition monitoring (as the lifetimes)", to: `/modelling/joint/new?lifetimes=${id}` });
  return life;
}
