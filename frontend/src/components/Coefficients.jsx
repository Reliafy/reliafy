// Regression coefficients table for proportional-hazards models. The hazard
// ratio exp(β) > 1 means the covariate increases hazard (shorter life).
const fmt = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? v.toFixed(4) : v.toExponential(3);

export default function Coefficients({ coefficients }) {
  if (!coefficients || coefficients.length === 0) {
    return <p className="muted-line">This model has no covariate coefficients.</p>;
  }
  return (
    <table className="coef-table">
      <thead>
        <tr>
          <th>Covariate</th>
          <th>Coefficient (β)</th>
          <th>Hazard ratio (e^β)</th>
        </tr>
      </thead>
      <tbody>
        {coefficients.map((c) => (
          <tr key={c.name}>
            <td className="coef-name">{c.name}</td>
            <td>{fmt(c.value)}</td>
            <td>{fmt(c.hazard_ratio)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
