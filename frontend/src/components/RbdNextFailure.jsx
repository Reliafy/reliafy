import Plot from "./Plot.jsx";
import MethodTag from "./MethodTag.jsx";

// As of now with the simulation (#220, #221): the time to the next system
// failure from the blocks' states, its mean (the mean residual life),
// percentiles, the chance it has come by each time, and the blocks whose
// failures most often cause it. Shows only when the result carries it.

const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(4)).toLocaleString());
const fmtPct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`);

export function meanResidualLife(nf) {
  if (!nf || nf.mean == null) return null;
  return `${nf.mean_is_lower_bound ? "≥ " : ""}${fmtT(nf.mean)}`;
}

export default function RbdNextFailure({ result, unit }) {
  const nf = result?.next_failure;
  if (!nf) return null;
  const u = unit ? ` ${unit}` : "";
  const pc = nf.percentiles || {};
  const conf = Math.round((nf.confidence || 0.95) * 100);
  const curve = nf.curve || {};
  const causes = nf.causes || [];
  return (
    <div className="rbd-next-failure">
      <div className="ds-section-h">
        Next system failure from now <MethodTag method="simulated" />
      </div>
      {nf.down_now > 0 && (
        <p className="muted-line" style={{ margin: 0 }}>
          The system is down now{nf.down_now < 1 ? ` in ${fmtPct(nf.down_now)} of the histories` : ""}: its next
          failure is counted from now, after it is restored.
        </p>
      )}
      <div className="rbd-avail-metrics">
        <div className="alt-metric" title="The mean time from now to the next system failure: the mean residual life given the blocks' states.">
          <span className="k">Mean residual life</span>
          <span className="v">{meanResidualLife(nf)}{u}</span>
        </div>
        <div className="alt-metric" title={`${conf}% confidence interval on the mean`}>
          <span className="k">{conf}% interval</span>
          <span className="v">
            {nf.mean_lower == null ? "—" : `${fmtT(nf.mean_lower)} – ${fmtT(nf.mean_upper)}`}
          </span>
        </div>
        <div className="alt-metric" title="Half of the histories fail by then">
          <span className="k">Median</span>
          <span className="v">{fmtT(pc.p50)}{pc.p50 != null ? u : ""}</span>
        </div>
        <div className="alt-metric" title="10% of the histories fail by then">
          <span className="k">10% fail by</span>
          <span className="v">{fmtT(pc.p10)}{pc.p10 != null ? u : ""}</span>
        </div>
      </div>
      {curve.t?.length > 1 && (
        <Plot
          data={[{
            x: curve.t, y: curve.cdf, mode: "lines", type: "scatter", line: { color: "#b42318", width: 2 },
            name: "P(failed by t)", hovertemplate: "%{x:.4g}: %{y:.1%}<extra></extra>",
          }]}
          layout={{
            autosize: true, height: 260, margin: { l: 56, r: 16, t: 16, b: 44 },
            paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff", showlegend: false,
            xaxis: { title: `Time from now${unit ? ` (${unit})` : ""}`, gridcolor: "#eef1f5", zeroline: false },
            yaxis: { title: "P(next failure by t)", gridcolor: "#eef1f5", range: [0, 1.02], tickformat: ".0%" },
          }}
          useResizeHandler style={{ width: "100%" }} config={{ displayModeBar: false, responsive: true }}
        />
      )}
      {causes.length > 0 && (
        <div className="rbd-avail-nodes">
          <div className="ds-section-h">Likely cause</div>
          {causes.map((c) => (
            <div className="rbd-avail-bar" key={c.id}>
              <span className="rbd-avail-bar-label" title={c.label}>{c.label}</span>
              <span className="rbd-avail-bar-track">
                <span className="rbd-avail-bar-fill" style={{ width: `${Math.round((c.share || 0) * 100)}%` }} />
              </span>
              <span className="rbd-avail-bar-pct">{fmtPct(c.share)}</span>
            </div>
          ))}
        </div>
      )}
      <p className="muted-line" style={{ margin: "8px 0 0" }}>
        {nf.n_simulations?.toLocaleString()} simulated histories from the blocks' states now, over {fmtT(nf.window)}
        {u}. Each block's share is how often its failure was the one that took the system down first.
        {nf.mean_is_lower_bound
          ? ` ${fmtPct(1 - nf.failed_share)} of the histories had not failed by the window's end, so the mean is a lower bound.`
          : ""}
      </p>
    </div>
  );
}
