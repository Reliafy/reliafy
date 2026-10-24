import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import { CheckCard } from "./model/ModelLayouts.jsx";
import { fitLine, referenceLine } from "../plotTheme.js";
import { degradationInducedLife } from "../api.js";
import { formatNumber, formatPercent } from "../format.js";
import { routesVerdict } from "../degradationFrame.js";
import { unitInText } from "./unitText.js";

// The degradation model's induced life, a check on its Diagnostics tab: the
// failure-time distribution the path model itself implies (Lu-Meeker: path
// parameters drawn from the fitted population, each run to the threshold),
// beside the non-repairable model fitted to the items' crossing times. The
// two agreeing is evidence the model hangs together. Every number comes from
// the server; a model's first answer is kept for the page's life, so going
// back to the tab doesn't draw the paths again.
const first = new Map();

const SMALL = { margin: { t: 6, r: 10, b: 40, l: 50 } };

// The induced life of a saved model: its first answer (reliability at a
// round time near the median, the time to 90%), and ``ask(time, relPct)``
// for another.
export function useInducedLife(modelId) {
  const [data, setData] = useState(() => first.get(modelId) || null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!modelId || first.has(modelId)) return undefined;
    let live = true;
    degradationInducedLife(modelId, { reliability: [0.9] })
      .then((d) => {
        if (!live) return null;
        if (d.median == null) return d;
        const start = Number(d.median.toPrecision(2)); // a round time near the median
        return degradationInducedLife(modelId, { times: [start], reliability: [0.9] });
      })
      .then((d) => {
        if (!live || !d) return;
        first.set(modelId, d);
        setData(d);
      })
      .catch((err) => live && setError(err.message || "Couldn't compute the induced life."));
    return () => { live = false; };
  }, [modelId]);
  const ask = async (time, relPct) => {
    setBusy(true);
    setError(null);
    try {
      const body = { reliability: [relPct / 100] };
      if (time !== "" && Number.isFinite(Number(time)) && Number(time) >= 0) body.times = [Number(time)];
      setData(await degradationInducedLife(modelId, body));
    } catch (err) {
      setError(err.message || "Couldn't compute the induced life.");
    } finally {
      setBusy(false);
    }
  };
  return { data, error, busy, ask };
}

// "Do the two routes to a life agree?": the two reliability curves, and the
// verdict on their medians.
export function InducedLifeCheck({ induced, unit, name }) {
  const { data, error } = induced;
  const v = routesVerdict(data, unit);
  let body;
  let verdict = v?.words || null;
  if (!data) {
    body = <p className="muted-line">{error || "Drawing 10,000 paths from the fitted population…"}</p>;
    verdict = null;
  } else if (!data.available) {
    body = <p className="muted-line">No induced life for this model: {data.reason}</p>;
  } else {
    const curve = data.curve || {};
    const traces = [];
    if (curve.life_sf) {
      traces.push(referenceLine({ x: curve.x, y: curve.life_sf, name: "Fit to the crossing times", hoverinfo: "skip" }));
    }
    traces.push(fitLine({
      x: curve.x, y: curve.sf, name: "Induced by the path model",
      hovertemplate: `%{x:,.4~g}${unit ? ` ${unitInText(unit)}` : ""}: R=%{y:.3f}<extra></extra>`,
    }));
    body = (
      <Plot
        fill
        data={traces}
        download={`${name || "Degradation model"} — induced life`}
        layout={{
          ...SMALL,
          showlegend: true,
          // Bottom left: the curves start at the top left and fall away right.
          legend: { x: 0.01, xanchor: "left", y: 0.02, yanchor: "bottom", bgcolor: "rgba(255,255,255,0.85)" },
          xaxis: { title: { text: unit ? `Time (${unit})` : "Time" }, rangemode: "tozero" },
          yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
        }}
      />
    );
  }
  return (
    <CheckCard chart question="Do the two routes to a life agree?" term="induced life, Lu–Meeker"
               tone={v?.tone} verdict={verdict}
               footer={data?.available && (
                 <p className="muted-line">
                   Solid: {Number(data.n_samples || 0).toLocaleString("en-US")} paths drawn from the fitted population, each
                   run to the threshold. Dashed: the life model fitted to the items' own crossing times.
                 </p>
               )}>
      {body}
    </CheckCard>
  );
}

// The induced life's figures, and a time or reliability to read it at.
export function InducedLifeCard({ induced, unit }) {
  const { data, error, busy, ask } = induced;
  const [t, setT] = useState(() => (data?.at_times?.[0]?.t != null ? String(data.at_times[0].t) : ""));
  const [relPct, setRelPct] = useState(90);
  const [seeded, setSeeded] = useState(!!data?.at_times?.length);
  if (!seeded && data?.at_times?.[0]?.t != null) {
    setSeeded(true);
    setT(String(data.at_times[0].t));
  }
  if (!data?.available) return null;
  const u = unit ? ` ${unitInText(unit)}` : "";
  const atT = data.at_times?.[0];
  const atR = data.at_reliability?.[0];
  const commit = () => ask(t, relPct);
  return (
    <section className="gof-card mf-flex-none" aria-labelledby="deg-induced-h">
      <div className="gofh life-card-head">
        <h3 className="mf-card-title" id="deg-induced-h">Induced life</h3>
        <span className="gof-sub">by the path model</span>
      </div>
      <div className="calc-eval-body deg-induced-inputs">
        <label className="calc-t">
          <span>Time{unit ? ` (${unitInText(unit)})` : ""}</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={t}
                 onChange={(e) => setT(e.target.value)} onBlur={commit}
                 onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
        </label>
        <label className="calc-t">
          <span>Reliability %</span>
          <input type="number" inputMode="numeric" min="1" max="99" step="1" value={relPct}
                 onChange={(e) => setRelPct(Number(e.target.value))} onBlur={commit}
                 onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
        </label>
      </div>
      {atT && (
        <div className="gofr">
          <span className="gk">Reliability at {formatNumber(atT.t)}{u}</span>
          <span className="gv">{atT.reliability != null ? formatPercent(atT.reliability, { sig: 3 }) : "—"}</span>
        </div>
      )}
      {atR && (
        <div className="gofr">
          <span className="gk">Time to {formatNumber(atR.reliability * 100)}% reliability</span>
          <span className="gv">{atR.t != null ? `${formatNumber(atR.t)}${u}` : "never reached"}</span>
        </div>
      )}
      <div className="gofr"><span className="gk">Median life</span><span className="gv">{formatNumber(data.median)}{u}</span></div>
      {data.life_median != null && (
        <div className="gofr"><span className="gk">By the crossing times</span><span className="gv">{formatNumber(data.life_median)}{u}</span></div>
      )}
      {/* Some paths never reaching the threshold make the mean infinite. */}
      {data.mean != null && !(data.prob_never_fails > 0) && (
        <div className="gofr"><span className="gk">Mean life</span><span className="gv">{formatNumber(data.mean)}{u}</span></div>
      )}
      {data.prob_never_fails > 0 && (
        <div className="gofr">
          <span className="gk">Never reach the threshold</span>
          <span className="gv">{formatPercent(data.prob_never_fails)}</span>
        </div>
      )}
      {busy && <p className="mf-note">Working…</p>}
      {error && <p className="mf-note" role="alert">{error}</p>}
    </section>
  );
}
