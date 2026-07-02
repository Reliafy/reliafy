// Goodness-of-fit tab: a simple table of metrics. Lower AIC/AICc/BIC and a
// higher (less negative) log-likelihood indicate a better fit.
const fmt = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? v.toFixed(4) : v.toExponential(3);

export default function GoodnessOfFit({ gof, n }) {
  if (!gof || gof.length === 0) {
    return <p className="muted-line">No goodness-of-fit metrics available.</p>;
  }
  return (
    <table className="gof-table">
      <tbody>
        {gof.map((g) => (
          <tr key={g.id}>
            <th>{g.label}</th>
            <td>{fmt(g.value)}</td>
          </tr>
        ))}
        <tr>
          <th>Observations</th>
          <td>{n}</td>
        </tr>
      </tbody>
    </table>
  );
}
