// Goodness-of-fit tab: the metrics in the same card format used elsewhere.
// Lower AIC/AICc/BIC and a higher (less negative) log-likelihood mean a better
// fit.
const fmt = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? Number(v).toFixed(2) : Number(v).toExponential(2);

export default function GoodnessOfFit({ gof, n }) {
  if (!gof || gof.length === 0) {
    return <p className="muted-line">No goodness-of-fit metrics available.</p>;
  }
  return (
    <div className="gof-metrics-card">
      <div className="gofh">Goodness of fit</div>
      {gof.map((g) => (
        <div className="gofr" key={g.id}>
          <span className="gk">{g.label}</span>
          <span className="gv">{fmt(g.value)}</span>
        </div>
      ))}
      {n != null && (
        <div className="gofr">
          <span className="gk">Observations</span>
          <span className="gv">{n}</span>
        </div>
      )}
    </div>
  );
}
