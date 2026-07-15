// Regression coefficients for proportional-hazards / accelerated-failure-time
// models, in the same card format as the other tabs. exp(β) is a hazard ratio
// (PH) or a time ratio (AFT) — ``ratioLabel`` says which.
const fmt = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? v.toFixed(4) : v.toExponential(3);

export default function Coefficients({ coefficients, ratioLabel = "hazard ratio" }) {
  if (!coefficients || coefficients.length === 0) {
    return <p className="muted-line">This model has no covariate coefficients.</p>;
  }
  return (
    <div className="gof-metrics-card">
      <div className="gofh">Coefficients</div>
      {coefficients.map((c) => (
        <div className="gofr" key={c.name}>
          <span className="gk">{c.name}</span>
          <span className="gv-col">
            <span className="gv">β = {fmt(c.value)}</span>
            <span className="param-ci">{ratioLabel} e^β = {fmt(c.ratio ?? c.hazard_ratio)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
