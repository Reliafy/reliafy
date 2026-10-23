// The model page's Model characteristics tab: which results have one, and
// what their mean life says in words. Pure functions, so `node --test` covers them; the
// numbers come from the model's life path (SurPyval's mean and mean_cb).

// The kinds the tab shows (for their mean life): a plain or flexible distribution
// and a non-parametric estimate (its mean to a horizon). A fit with no finite
// maximum gives no bounds and no trustworthy mean, so it has no tab.
export function hasMeanLife(result) {
  if (!result || result.no_finite_maximum) return false;
  if (!["distribution", "flexible", "nonparametric"].includes(result.kind)) return false;
  return !!(result.functions?.life_path || result.life);
}

// The confidence levels offered for the bound; ``level`` (the calculator's,
// which may be typed) joins them when it isn't one.
export const MEAN_LEVELS = [80, 90, 95, 99];
export function meanLevels(level) {
  const l = Number(level);
  return MEAN_LEVELS.includes(l) || !(l > 0 && l < 100) ? MEAN_LEVELS : [...MEAN_LEVELS, l].sort((a, b) => a - b);
}

const weibullShape = (result) => {
  const id = String(result.distribution_id || result.distribution || "").toLowerCase();
  if (id !== "weibull") return null;
  const beta = (result.params || []).find((p) => p.name === "beta");
  return beta && Number.isFinite(Number(beta.value)) ? Number(beta.value) : null;
};

// What the mean life is: ``mttf`` is the life path's { value, lower, tau,
// restricted } (a non-parametric estimate's has a horizon, ``tau``).
//   { kind: "mean", value, lower }               the whole mean (MTTF)
//   { kind: "restricted", value, lower, tau }    the mean counted to a horizon
//   { kind: "none", why }                        no finite mean, and why
// ``caveat``: a line for a mean that's far out (a Weibull shape below 1).
export function meanLifeAnswer(result, mttf) {
  const np = result?.kind === "nonparametric";
  if (!mttf || mttf.value == null || !Number.isFinite(Number(mttf.value))) {
    let why;
    if (result?.extras?.p != null && Number(result.extras.p) < 1)
      why = "Some units never fail (a limited failure population), so the average time to failure is infinite.";
    else if (np) why = "The estimate gives no mean life up to this time.";
    else why = "This model has no finite mean life: a few very long lives would pull any average out without limit.";
    return { kind: "none", why };
  }
  const lower = mttf.lower != null && Number.isFinite(Number(mttf.lower)) ? Number(mttf.lower) : null;
  const value = Number(mttf.value);
  const beta = weibullShape(result);
  const caveat = beta != null && beta < 1
    ? "The shape β is below 1, so a few long-lived units pull the mean far beyond most lives: the median is usually the better figure to quote."
    : null;
  if (np && mttf.tau != null && mttf.restricted !== false) {
    return { kind: "restricted", value, lower, tau: Number(mttf.tau), caveat };
  }
  return { kind: "mean", value, lower, caveat };
}

// The median (B50) from the same answer, for the comparison line.
export function medianOf(life) {
  const b = (life?.b_lives || []).find((x) => x.label === "B50");
  return b && b.value != null && Number.isFinite(Number(b.value)) ? Number(b.value) : null;
}

// Why a bound couldn't be fetched, in words: a shared page's viewer isn't
// signed in (or isn't the owner), so only the saved figures can be shown.
export function boundUnavailable(error, savedLevel) {
  if (!error) return null;
  const saved = savedLevel != null ? `${Math.round(savedLevel * 100)}%` : null;
  const status = error.status;
  if (status === 401 || status === 403 || status === 404) {
    return saved
      ? `Another confidence or time needs you signed in to a copy of this model, so this shows the saved ${saved} figures.`
      : "The bound needs you signed in to a copy of this model.";
  }
  return `Couldn't work out the mean life: ${error.message || "the request failed"}.`;
}
