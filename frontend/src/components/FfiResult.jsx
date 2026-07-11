const fmt = (v) =>
  v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });

// Presentational renderer for a failure-finding-interval result.
export default function FfiResult({ result }) {
  const u = result?.unit ? ` ${result.unit}` : "";
  return (
    <>
      <div className="strategy-reco">
        <span className="strategy-reco-icon">✓</span>
        <span>{result.note}</span>
      </div>
      <div className="params">
        <div className="stat">
          <div className="value">{fmt(result.interval)}</div>
          <div className="name">failure-finding interval{u}</div>
        </div>
        <div className="stat">
          <div className="value">{(result.target_availability * 100).toFixed(1)}%</div>
          <div className="name">target availability</div>
        </div>
        <div className="stat">
          <div className="value">{fmt(result.mttf)}</div>
          <div className="name">MTTF{u}</div>
        </div>
      </div>
      <p className="muted-line">
        Hidden failures (protective devices) stay undetected until the function
        is demanded or checked. Checking every {fmt(result.interval)}{u} keeps
        the average unavailability near {(100 * (1 - result.target_availability)).toFixed(1)}%.
        Formula: FFI = 2 × (1 − A) × MTTF (first-order approximation, accurate
        for availability targets above ~90%).
      </p>
    </>
  );
}
