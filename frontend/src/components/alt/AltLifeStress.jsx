// The Life-stress tab of an accelerated life model: life against stress, the
// tested levels marked, the fitted line run on to the use stress and the use
// point marked; beside it the use stress, the life there, the shape and the
// acceleration factor against each tested level. A model with two stresses
// has two charts side by side, one along each stress (a line for each tested
// level of the other); on a phone a switch picks one.
import { useEffect, useState } from "react";
import Plot from "../Plot.jsx";
import SegmentedControl from "../ui/SegmentedControl.jsx";
import { PlotCard, PlotPanel, ScrollCard, TwoPlots } from "../model/ModelLayouts.jsx";
import { COLORWAY, DATA_INK, INK, SURFACE, fitLine } from "../../plotTheme.js";
import { formatNumber } from "../../format.js";
import { evaluateAlt } from "../../api.js";
import { accelerationRows, levelWords, parseUse, shapeParam, stressName } from "../../altFrame.js";
import { unitInText } from "../unitText.js";
import usePhone from "./usePhone.js";

const SERIES = COLORWAY;
const USE_MARK = "#b45309";

// One life-stress chart: ``plot`` is a life_stress_plot from the fit (along
// one stress); ``along`` the line through the use stress from the
// calculator's answer, and ``usePoint`` { x, y } the use point.
export function LifeStressChart({ plot, unit, along = null, usePoint = null, otherUse = null, name, fill = true }) {
  const p = plot || {};
  const two = p.secondary_label != null;
  const traces = [];
  const secLevels = two ? [...new Set((p.lines || []).map((l) => l.secondary))] : [null];
  (p.lines || []).forEach((ln, i) => {
    // One stress: the line through the use stress replaces the fitted line
    // (it is the same line, run on to the use stress).
    if (!two && along) return;
    traces.push(fitLine({
      x: ln.stress, y: ln.life,
      line: { color: SERIES[i % SERIES.length] },
      name: two ? `${p.secondary_label} = ${formatNumber(ln.secondary, { sig: 4 })}` : "Fitted line",
      legendgroup: `g${i}`,
    }));
  });
  // Two stresses: the line through the use stress, unless the other stress's
  // use value is a tested level (its line is already drawn).
  const onTested = two && otherUse != null && secLevels.some((v) => Math.abs(v - otherUse) <= 1e-9 * Math.max(1, Math.abs(v)));
  if (along?.stress?.length && !onTested) {
    traces.push(fitLine({
      x: along.stress, y: along.life,
      line: two ? { color: USE_MARK, dash: "dash" } : { color: SERIES[0] },
      name: two ? `${p.secondary_label} = ${formatNumber(otherUse, { sig: 4 })} (use)` : "Fitted line",
      hovertemplate: `${p.x_label}: %{x:.4~g}<br>Life: %{y:.4~g}<extra></extra>`,
    }));
  }
  (p.points || []).forEach((pt) => {
    const idx = two ? Math.max(0, secLevels.indexOf(pt.secondary)) : 0;
    traces.push({
      x: [pt.stress], y: [pt.life], mode: "markers", type: "scatter",
      marker: { color: two ? SERIES[idx % SERIES.length] : INK, size: 10, symbol: "diamond",
                line: { color: SURFACE, width: 1.5 } },
      name: "Tested level", legendgroup: `g${idx}`, showlegend: false,
      hovertemplate: `${p.x_label}: %{x}<br>Life: %{y:.4~g}<extra>tested level</extra>`,
    });
  });
  const obs = p.observations;
  if (obs) {
    const times = obs.ranges.time;
    const floor = p.log_y
      ? Math.min(...[...times, ...obs.failures.time].filter((t) => t > 0)) / 2
      : 0;
    if (obs.n_ranges) {
      traces.push({
        x: obs.ranges.stress, y: times.map((t) => (t === 0 ? floor : t)), mode: "lines", type: "scatter",
        line: { color: "rgba(20, 23, 28, 0.25)", width: 3 }, name: "Failed between inspections",
        hoverinfo: "skip",
      });
    }
    if (obs.n_failures) {
      traces.push({
        x: obs.failures.stress, y: obs.failures.time, mode: "markers", type: "scatter",
        marker: { color: DATA_INK, size: 6 }, name: "Failure",
        hovertemplate: `${p.x_label}: %{x}<br>Failed at: %{y:.4g}<extra></extra>`,
      });
    }
  }
  if (usePoint && Number.isFinite(usePoint.x) && Number.isFinite(usePoint.y)) {
    traces.push({
      x: [usePoint.x], y: [usePoint.y], mode: "markers", type: "scatter",
      marker: { color: USE_MARK, size: 13, symbol: "star", line: { color: SURFACE, width: 1 } },
      name: "Use stress",
      hovertemplate: `Use stress: %{x}<br>Life: %{y:.4~g}<extra></extra>`,
    });
  }
  const layout = {
    margin: { t: 8, r: 12, b: 44, l: 64 },
    xaxis: { title: { text: p.x_label || "Stress" } },
    yaxis: {
      title: { text: `Characteristic life${unit ? ` (${unit})` : ""}` },
      type: p.log_y ? "log" : "linear",
      ...(p.log_y ? { dtick: "D2", tickformat: ",~g" } : {}),
    },
    showlegend: true,
    // One stress: a small legend inside, top right; two: the theme's, above.
    ...(two ? {} : { legend: { orientation: "v", x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" } }),
  };
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — life against ${p.x_label || "stress"}`} />;
}

// The life at the use stress from the server, asked again (after a pause)
// whenever the use stress changes. Null until there is one.
function useLifeAtUse(modelId, use) {
  const [state, setState] = useState(null);
  const key = use ? JSON.stringify(use) : null;
  useEffect(() => {
    if (!modelId || !key) { setState(null); return undefined; }
    let live = true;
    setState((s) => (s && s.key === key ? s : { key, busy: true, ev: s?.ev || null }));
    const timer = setTimeout(() => {
      evaluateAlt(modelId, JSON.parse(key), null, {})
        .then((ev) => live && setState({ key, ev }))
        .catch((e) => live && setState({ key, error: e.message }));
    }, 350);
    return () => { live = false; clearTimeout(timer); };
  }, [modelId, key]);
  return state;
}

function UseInputs({ results, use, onUse }) {
  return (
    <div className="alt-use-inputs">
      {(results.stresses || []).map((s, j) => (
        <label key={s.key || j} className="alt-use-field">
          <span>{stressName(s)}</span>
          <input type="number" inputMode="decimal" step="any" value={use[j] ?? ""}
                 aria-label={`Use stress: ${stressName(s)}`}
                 onChange={(e) => onUse(use.map((v, k) => (k === j ? e.target.value : v)))} />
        </label>
      ))}
    </div>
  );
}

function Side({ results, modelId, use, onUse, edited, state }) {
  const r = results;
  const unit = r.unit ? unitInText(r.unit) : "";
  const shape = shapeParam(r);
  const ev = state?.ev;
  const lifeUse = ev?.metrics?.characteristic_life;
  const rows = accelerationRows(r.levels, modelId ? lifeUse : null);
  return (
    <>
      <section className="gof-card mf-flex-none" aria-labelledby="alt-use-h">
        <div className="gofh life-card-head">
          <h3 className="mf-card-title" id="alt-use-h">{modelId ? "At your use stress" : "The fit"}</h3>
        </div>
        {modelId && (
          <div className="alt-use-box">
            <UseInputs results={r} use={use} onUse={onUse} />
            {!edited && <p className="alt-use-hint">The mildest tested level: enter your own.</p>}
            {state?.error && <p className="alt-use-hint error-text" role="alert">{state.error}</p>}
          </div>
        )}
        {modelId && (
          <div className="gofr">
            <span className="gk">Life at use stress</span>
            <span className="gv" aria-live="polite">
              {Number.isFinite(lifeUse) ? `${formatNumber(lifeUse)}${unit ? ` ${unit}` : ""}` : state?.busy ? "…" : "—"}
            </span>
          </div>
        )}
        {shape && (
          <div className="gofr">
            <span className="gk">{shape.label}</span>
            <span className="gv">
              {formatNumber(shape.value)}
              {Array.isArray(shape.ci) && <span className="gof-sub alt-ci"> 95% {formatNumber(shape.ci[0])}–{formatNumber(shape.ci[1])}</span>}
            </span>
          </div>
        )}
      </section>
      <ScrollCard title={modelId ? "Acceleration factor" : "Life at each tested level"}
                  sub={modelId ? "use ÷ each level" : null} id="alt-af-h">
        <table className="mini-table">
          <thead>
            <tr>
              <th>Tested at</th>
              <th className="mf-num">Life{unit ? ` (${unit})` : ""}</th>
              {modelId && <th className="mf-num">Factor</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td>{levelWords(row.stress, r.stresses)}</td>
                <td className="mf-num">{formatNumber(row.life)}</td>
                {modelId && <td className="mf-num">{row.af == null ? "—" : `${formatNumber(row.af)}×`}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {modelId && (
          <p className="mf-note">How many times longer a unit lasts at the use stress than at each tested level.</p>
        )}
      </ScrollCard>
    </>
  );
}

export default function AltLifeStress({ results, modelId, name, use, onUse, edited }) {
  const r = results || {};
  const phone = usePhone();
  const [which, setWhich] = useState(0);
  const numeric = parseUse(use);
  const state = useLifeAtUse(modelId, numeric);
  const ev = state?.ev && state.key === JSON.stringify(numeric) ? state.ev : null;
  const lifeUse = ev?.metrics?.characteristic_life;
  const lines = ev?.life_lines || [];
  const plots = [r.life_stress_plot, r.life_stress_plot_2].filter(Boolean);
  const side = <Side results={r} modelId={modelId} use={use} onUse={onUse} edited={edited} state={state} />;
  const chart = (j) => (
    <PlotCard key={j} title={plots.length > 1 ? `Life against ${plots[j].x_label}` : null}>
      <LifeStressChart
        plot={plots[j]}
        unit={r.unit}
        name={name}
        along={lines[j] || null}
        otherUse={numeric && plots.length > 1 ? numeric[1 - j] : null}
        usePoint={ev && numeric ? { x: numeric[j], y: lifeUse } : null}
      />
    </PlotCard>
  );
  if (plots.length < 2) return <PlotPanel plot={chart(0)} side={side} />;
  if (phone) {
    return (
      <PlotPanel
        plot={(
          <>
            <SegmentedControl
              label="Chart"
              value={which}
              onChange={setWhich}
              className="alt-stress-switch"
              options={plots.map((p, j) => ({ value: j, label: (r.stresses?.[j]?.label) || p.x_label }))}
            />
            {chart(which)}
          </>
        )}
        side={side}
      />
    );
  }
  return <TwoPlots first={chart(0)} second={chart(1)} side={side} />;
}
