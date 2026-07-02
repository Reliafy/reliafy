// Short blurbs shown under the dropdown for context (keyed by distribution id).
const DESCRIPTIONS = {
  weibull: "Two-parameter (α scale, β shape). The most common life model.",
  exponential: "Single rate parameter; constant hazard.",
  normal: "Gaussian location–scale model.",
  lognormal: "Normal on the log scale; right-skewed lifetimes.",
  gamma: "Flexible shape–scale lifetime model.",
  weibull_ph: "Weibull baseline with proportional-hazards covariate effects.",
  exponential_ph: "Exponential baseline proportional-hazards model.",
  lognormal_ph: "Lognormal baseline proportional-hazards model.",
  normal_ph: "Normal baseline proportional-hazards model.",
  gamma_ph: "Gamma baseline proportional-hazards model.",
  cox_ph: "Semi-parametric Cox model — covariate effects, no baseline shape.",
};

// Distribution picker rendered as a dropdown. ``options`` come from the
// backend ([{ id, name }]).
export default function DistributionStep({ options, value, onChange }) {
  return (
    <div className="dist-picker">
      <label className="dist-field" htmlFor="dist-select">
        <span className="dist-label">Distribution</span>
        <div className="select-wrap">
          <select
            id="dist-select"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            {options.map((d) => (
              <option value={d.id} key={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </label>
      {DESCRIPTIONS[value] && <p className="dist-blurb">{DESCRIPTIONS[value]}</p>}
    </div>
  );
}
