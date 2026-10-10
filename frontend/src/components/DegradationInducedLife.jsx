import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, referenceLine } from "../plotTheme.js";
import { degradationInducedLife } from "../api.js";
import { formatNumber, formatPercent } from "../format.js";

// The degradation model page's "Induced life" tab (#63): the failure-time
// distribution the path model itself implies (Lu-Meeker: path parameters
// drawn from the fitted population, each extended to the threshold), beside
// the life model fitted to the items' crossing times. The two agreeing is
// evidence the model hangs together. Every number comes from the server.
const PLOT_HEIGHT = 470;

export default function DegradationInducedLife({ modelId, unit, name = null }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState("");
  const [relPct, setRelPct] = useState(90);
  const tUnit = unit ? ` ${unit.toLowerCase()}` : "";

  const load = async (time, rel) => {
    setBusy(true);
    setError(null);
    try {
      const body = { reliability: [rel / 100] };
      if (time !== "" && Number.isFinite(Number(time)) && Number(time) >= 0) body.times = [Number(time)];
      setData(await degradationInducedLife(modelId, body));
    } catch (err) {
      setError(err.message || "Couldn't compute the induced life.");
    } finally {
      setBusy(false);
    }
  };

  // First view: the curve and summary; the time input opens on the median.
  useEffect(() => {
    let live = true;
    degradationInducedLife(modelId, { reliability: [0.9] })
      .then((d) => {
        if (!live) return;
        if (d.median == null) return d;
        const start = Number(d.median.toPrecision(2)); // a round time near the median
        setT(String(start));
        return degradationInducedLife(modelId, { times: [start], reliability: [0.9] });
      })
      .then((d) => live && d && setData(d))
      .catch((err) => live && setError(err.message || "Couldn't compute the induced life."));
    return () => { live = false; };
  }, [modelId]);

  if (error && !data) return <p className="muted-line" style={{ marginTop: 20 }}>{error}</p>;
  if (!data) return <p className="muted-line" style={{ marginTop: 20 }}>Drawing 10,000 paths…</p>;
  if (!data.available) {
    return <p className="muted-line" style={{ marginTop: 20 }}>No induced life for this model: {data.reason}</p>;
  }

  const curve = data.curve || {};
  const traces = [];
  if (curve.life_sf) {
    traces.push(referenceLine({ x: curve.x, y: curve.life_sf, name: "Fit to crossing times", hoverinfo: "skip" }));
  }
  traces.push(fitLine({
    x: curve.x, y: curve.sf, name: "Induced by the path model",
    hovertemplate: `%{x:,.4~g}${tUnit}: R=%{y:.3f}<extra></extra>`,
  }));
  const atT = data.at_times?.[0];
  const atR = data.at_reliability?.[0];
  const commit = () => load(t, relPct);

  return (
    <div className="detail-panel">
      <div className="plotwrap">
        <Plot
          data={traces}
          layout={{
            height: PLOT_HEIGHT,
            margin: { t: 16 },
            showlegend: true,
            // Bottom left: the curves start at the top left and fall away right.
            legend: { x: 0.01, xanchor: "left", y: 0.02, yanchor: "bottom", bgcolor: "rgba(255,255,255,0.8)" },
            xaxis: { title: { text: unit ? `Time (${unit})` : "Time" }, rangemode: "tozero" },
            yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
          }}
          download={`${name || "Degradation model"} — induced life`}
        />
      </div>
      <div className="aside">
        <div className="gof-card">
          <div className="gofh">Inputs</div>
          <div className="calc-eval-body">
            <label className="calc-t">
              <span>Time{unit ? ` (${unit.toLowerCase()})` : ""}</span>
              <input
                type="number" min="0" step="any" value={t}
                onChange={(e) => setT(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
              />
            </label>
            <label className="calc-t">
              <span>Reliability %</span>
              <input
                type="number" min="1" max="99" step="1" value={relPct}
                onChange={(e) => setRelPct(Number(e.target.value))}
                onBlur={commit}
                onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
              />
            </label>
            {busy && <span className="life-method">Computing…</span>}
          </div>
        </div>
        <div className="gof-card">
          <div className="gofh">Induced life</div>
          {atT && (
            <div className="gofr">
              <span className="gk">Reliability at {formatNumber(atT.t)}{tUnit}</span>
              <span className="gv">{atT.reliability != null ? formatPercent(atT.reliability, { sig: 3 }) : "—"}</span>
            </div>
          )}
          {atR && (
            <div className="gofr">
              <span className="gk">Time to {formatNumber(relPct)}% reliability</span>
              <span className="gv">{atR.t != null ? `${formatNumber(atR.t)}${tUnit}` : "never reached"}</span>
            </div>
          )}
          <div className="gofr">
            <span className="gk">Median life{tUnit && ` (${unit.toLowerCase()})`}</span>
            <span className="gv">{formatNumber(data.median)}</span>
          </div>
          <div className="gofr">
            <span className="gk">Mean life{tUnit && ` (${unit.toLowerCase()})`}</span>
            <span className="gv">{data.mean != null ? formatNumber(data.mean) : "—"}</span>
          </div>
          {data.prob_never_fails > 0 && (
            <div className="gofr">
              <span className="gk">Never reach the threshold</span>
              <span className="gv">{formatPercent(data.prob_never_fails)}</span>
            </div>
          )}
        </div>
        {error && <div className="life-reading caveat">{error}</div>}
        {data.life_median != null && (
          <div className="life-reading">
            Median <b>{formatNumber(data.median)}{tUnit}</b> by the path model, <b>{formatNumber(data.life_median)}{tUnit}</b>{" "}
            by the fit to the crossing times (dashed). Close agreement means the model hangs together.
          </div>
        )}
        <p className="life-method">
          Lu–Meeker: {data.n_samples.toLocaleString()} path draws from the fitted population, each run to the threshold.
        </p>
      </div>
    </div>
  );
}
