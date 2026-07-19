// Regression coefficients (PH / AFT / PO / AH), in the same card format as the
// other tabs, with a 95% CI. exp(β) is a hazard ratio (PH), time ratio (AFT) or
// odds ratio (PO) — ``ratioLabel`` says which; additive-hazards coefficients
// have no ratio, so it's omitted.
const fmt = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? v.toFixed(4) : v.toExponential(3);

export default function Coefficients({ coefficients, ratioLabel }) {
  if (!coefficients || coefficients.length === 0) {
    return <p className="muted-line">This model has no covariate coefficients.</p>;
  }
  return (
    <div className="gof-metrics-card">
      <div className="gofh">Coefficients</div>
      {coefficients.map((c) => {
        const ratio = c.ratio ?? c.hazard_ratio;
        return (
          <div className="gofr" key={c.name}>
            <span className="gk">{c.name}</span>
            <span className="gv-col">
              <span className="gv">β = {fmt(c.value)}</span>
              {c.ci && (
                <span className="param-ci">95% CI [{fmt(c.ci[0])}, {fmt(c.ci[1])}]</span>
              )}
              {ratioLabel && ratio != null && (
                <span className="param-ci">{ratioLabel} e^β = {fmt(ratio)}</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
