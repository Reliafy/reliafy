import { useState } from "react";
import Select from "./Select.jsx";
// Short blurbs shown under the dropdown for context (keyed by distribution id).
const DESCRIPTIONS = {
  best: "Fits every distribution and keeps the lowest-AIC winner — let the data decide.",
  weibull: "Two-parameter (α scale, β shape). The most common life model.",
  exponential: "Single rate parameter; constant hazard.",
  normal: "Gaussian location–scale model.",
  lognormal: "Normal on the log scale; right-skewed lifetimes.",
  gamma: "Flexible shape–scale lifetime model.",
  loglogistic: "Log-scale logistic; heavier tail than lognormal.",
  expo_weibull: "Three-parameter Weibull generalisation (extra shape μ).",
  gumbel: "Extreme-value (minimum) location–scale model.",
  logistic: "Location–scale model with slightly heavy tails.",
  discrete_weibull: "Whole-count analogue of the Weibull — cycles or shocks to failure.",
  geometric: "Discrete constant-hazard (memoryless) model — the discrete Exponential.",
  negative_binomial: "Discrete counts to failure; more dispersed than the Geometric.",
  weibull_ph: "Weibull baseline with proportional-hazards covariate effects.",
  exponential_ph: "Exponential baseline proportional-hazards model.",
  lognormal_ph: "Lognormal baseline proportional-hazards model.",
  normal_ph: "Normal baseline proportional-hazards model.",
  gamma_ph: "Gamma baseline proportional-hazards model.",
  cox_ph: "Semi-parametric Cox model — covariate effects, no baseline shape.",
  weibull_aft: "Weibull baseline; covariates scale time to failure (accelerated life).",
  exponential_aft: "Exponential baseline accelerated-failure-time model.",
  lognormal_aft: "Lognormal baseline accelerated-failure-time model.",
  normal_aft: "Normal baseline accelerated-failure-time model.",
  gamma_aft: "Gamma baseline accelerated-failure-time model.",
  kaplan_meier: "Non-parametric survival estimate — no distribution assumed.",
  nelson_aalen: "Non-parametric survival via cumulative hazard.",
  fleming_harrington: "Non-parametric, tie-corrected cumulative hazard.",
  turnbull: "Non-parametric estimate that handles left/interval censoring.",
};

const OPTION_HELP = {
  offset: "Adds a failure-free period γ: no failures can occur before it (3-parameter fit).",
  lfp: "Limited failure population: only a fraction p of units can ever fail (defective subpopulation).",
  zi: "Zero-inflated: a fraction f₀ is failed at t = 0 (dead on arrival).",
};

// Distribution picker plus advanced fit options (offset / LFP / zero
// inflation / fixed parameters). ``options`` come from the backend
// ([{ id, name, params, offsetable }]); ``fitOpts``/``onFitOpts`` hold
// { offset, zi, lfp, fixed } for plain distributions.
export default function DistributionStep({ options, value, onChange, fitOpts, onFitOpts }) {
  const [open, setOpen] = useState(false);
  const selected = options.find((d) => d.id === value);
  // Advanced fit options (offset/LFP/ZI/fixed) apply to continuous parametric
  // distributions only — not to discrete, non-parametric or regression models.
  const isPlain =
    selected && !selected.covariates && !selected.nonparametric && !selected.discrete;
  const opts = fitOpts || {};

  const setOpt = (key, val) => onFitOpts({ ...opts, [key]: val });
  const setFixed = (name, raw) => {
    const fixed = { ...(opts.fixed || {}) };
    if (raw === "" || raw === null) delete fixed[name];
    else fixed[name] = Number(raw);
    onFitOpts({ ...opts, fixed });
  };

  const activeCount =
    (opts.offset ? 1 : 0) + (opts.zi ? 1 : 0) + (opts.lfp ? 1 : 0) +
    Object.keys(opts.fixed || {}).length;

  // Group the picker into sections when more than one group is present. The
  // covariate path lists regression models — split into proportional-hazards
  // and accelerated-failure-time; the no-covariate path splits into Continuous /
  // Discrete / Non-parametric.
  const asOpt = (d) => ({ value: d.id, label: d.name });
  const isCovariateList = options.some((d) => d.covariates);
  const groups = isCovariateList
    ? [
        ["Proportional hazards", options.filter((d) => d.effect !== "aft")],
        ["Accelerated failure time", options.filter((d) => d.effect === "aft")],
      ].filter(([, list]) => list.length)
    : [
        ["Continuous", options.filter((d) => !d.nonparametric && !d.discrete)],
        ["Discrete", options.filter((d) => d.discrete)],
        ["Non-parametric", options.filter((d) => d.nonparametric)],
      ].filter(([, list]) => list.length);
  const selectOptions =
    groups.length > 1
      ? groups.flatMap(([heading, list]) => [{ heading }, ...list.map(asOpt)])
      : options.map(asOpt);

  return (
    <div className="dist-picker">
      <div className="dist-field">
        <span className="dist-label">Model</span>
        <Select value={value} onChange={onChange} options={selectOptions} />
      </div>
      {DESCRIPTIONS[value] && <p className="dist-blurb">{DESCRIPTIONS[value]}</p>}

      {isPlain && (
        <div className="fitopts">
          <button type="button" className="fitopts-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? "▾" : "▸"} Advanced fit options{activeCount > 0 ? ` (${activeCount} active)` : ""}
          </button>
          {open && (
            <div className="fitopts-body">
              <span className="dist-label">Model adjustments (optional)</span>
              {selected.offsetable && (
                <label className="fitopts-row" title={OPTION_HELP.offset}>
                  <input
                    type="checkbox"
                    checked={!!opts.offset}
                    onChange={(e) => setOpt("offset", e.target.checked)}
                  />
                  <span><b>Offset (3-parameter)</b> — failure-free period γ</span>
                </label>
              )}
              <label className="fitopts-row" title={OPTION_HELP.lfp}>
                <input
                  type="checkbox"
                  checked={!!opts.lfp}
                  onChange={(e) => setOpt("lfp", e.target.checked)}
                />
                <span><b>Limited failure population</b> — a fraction p never fails</span>
              </label>
              <label className="fitopts-row" title={OPTION_HELP.zi}>
                <input
                  type="checkbox"
                  checked={!!opts.zi}
                  onChange={(e) => setOpt("zi", e.target.checked)}
                />
                <span><b>Zero-inflated</b> — a fraction f₀ failed at t = 0</span>
              </label>

              {(selected.params || []).length > 0 && (
                <div className="fitopts-fixed">
                  <span className="dist-label">Fix parameters (optional)</span>
                  <div className="fitopts-fixed-row">
                    {selected.params.map((p) => (
                      <label key={p} className="login-field" style={{ width: 120 }}>
                        <span>{p}</span>
                        <input
                          type="number"
                          step="any"
                          placeholder="free"
                          value={opts.fixed?.[p] ?? ""}
                          onChange={(e) => setFixed(p, e.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                  <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
                    A fixed parameter is held at the given value while the rest
                    are estimated — e.g. fix β = 2 for a known wear-out slope.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
