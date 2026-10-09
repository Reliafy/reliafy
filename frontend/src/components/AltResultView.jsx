import { useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, DATA_INK, GRID, INK, SURFACE, fitLine } from "../plotTheme.js";
import AltCalculator from "./AltCalculator.jsx";
import NoMaximumNotice from "./NoMaximumNotice.jsx";
import { stressName } from "./stressName.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";

const fmt = (v, d = 4) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : Number(v).toLocaleString(undefined, { maximumSignificantDigits: d });

const ci = (pair) => (Array.isArray(pair) && pair.length === 2 ? `${fmt(pair[0])} – ${fmt(pair[1])}` : "—");

// Per-secondary-stress series (two-stress models), and per-stress-level series
// on the probability plot: the theme's series colours, in order.
const SERIES = COLORWAY;

// The answer first (#311): what was fitted and how far the characteristic
// life moves across the tested stresses; life at the user's own stress is the
// calculator's job.
function AltSummary({ r, calculator }) {
  const lives = (r.levels || []).map((l) => l.characteristic_life).filter((v) => Number.isFinite(v));
  const unit = r.unit ? ` ${unitInText(r.unit)}` : "";
  const beta = (r.params || []).find((p) => p.name === "beta");
  const name = [r.distribution, r.life_model].filter(Boolean).join(" · ");
  return (
    <ResultSummary
      sentence={
        <>
          <b>{name || "Accelerated life model"}</b>
          {lives.length > 1 ? (
            <>
              {" "}— characteristic life runs from <b>{formatNumber(Math.min(...lives))}</b> to{" "}
              <b>{formatNumber(Math.max(...lives))}{unit}</b> across the {lives.length} tested levels.
            </>
          ) : "."}
        </>
      }
      stats={[
        beta && {
          label: "Shape β",
          value: formatNumber(beta.value),
          hint: beta.ci ? `95% ${formatNumber(beta.ci[0])}–${formatNumber(beta.ci[1])}` : null,
        },
        { label: "Stress levels", value: String((r.levels || []).length || "—") },
        { label: "Observations", value: r.n != null ? r.n.toLocaleString() : "—" },
      ]}
    >
      {calculator ? "Life at your own use stress is in the Use-level calculator." : null}
    </ResultSummary>
  );
}

// A fitted Accelerated Life model, laid out like the other result views: the
// answer card, then a tabbed panel with the life-vs-stress plot (the ALT signature — characteristic
// life against stress, with the fitted line through each tested level), a
// use-level calculator (only once saved, so it can hit the evaluate endpoint),
// and a coefficients/fit detail tab.
export default function AltResultView({ results, modelId }) {
  const r = results || {};
  const plot = r.life_stress_plot || {};
  const twoStress = (r.stresses || []).length > 1;
  const [tab, setTab] = useState("plot");

  const traces = [];
  (plot.lines || []).forEach((ln, i) => {
    const color = SERIES[i % SERIES.length];
    traces.push(fitLine({
      x: ln.stress, y: ln.life,
      line: { color },
      name: twoStress ? `${plot.secondary_label} = ${fmt(ln.secondary, 3)}` : "Fitted",
      legendgroup: `g${i}`,
    }));
  });
  // Tested-level points, coloured to match their series.
  const secLevels = twoStress
    ? [...new Set((plot.lines || []).map((l) => l.secondary))]
    : [null];
  (plot.points || []).forEach((p) => {
    const idx = twoStress ? Math.max(0, secLevels.indexOf(p.secondary)) : 0;
    traces.push({
      x: [p.stress], y: [p.life], mode: "markers", type: "scatter",
      // One stress: tested levels are observed data (ink); two: their series' colour.
      marker: { color: twoStress ? SERIES[idx % SERIES.length] : INK, size: 10, symbol: "diamond",
                line: { color: SURFACE, width: 1.5 } },
      name: "Tested level", legendgroup: `g${idx}`, showlegend: false,
      hovertemplate: `${plot.x_label}: %{x}<br>Characteristic life: %{y:.4g}<extra></extra>`,
    });
  });

  // Inspection data (#237): each unit found failed between two read-outs is a
  // vertical range at its stress; units seen to fail are points.
  const obs = plot.observations;
  if (obs) {
    const times = obs.ranges.time;
    // A range from 0 (failed before the first read-out) runs to the foot of a
    // log axis: half the smallest positive time drawn.
    const floor = plot.log_y
      ? Math.min(...[...times, ...obs.failures.time].filter((t) => t > 0)) / 2
      : 0;
    if (obs.n_ranges) {
      traces.push({
        x: obs.ranges.stress, y: times.map((t) => (t === 0 ? floor : t)), mode: "lines", type: "scatter",
        line: { color: "rgba(20, 23, 28, 0.25)", width: 3 }, name: "Failed between inspections",
        hoverinfo: "skip", showlegend: true,
      });
    }
    if (obs.n_failures) {
      traces.push({
        x: obs.failures.stress, y: obs.failures.time, mode: "markers", type: "scatter",
        marker: { color: DATA_INK, size: 6, symbol: "circle" }, name: "Failure",
        hovertemplate: `${plot.x_label}: %{x}<br>Failed at: %{y:.4g}<extra></extra>`,
      });
    }
  }

  const layout = {
    height: 420,
    xaxis: { title: { text: plot.x_label || "Stress" } },
    yaxis: {
      title: { text: `${plot.y_label || "Characteristic life"}${r.unit ? ` (${r.unit})` : ""}` },
      type: plot.log_y ? "log" : "linear",
      // Log: label 1-2-5 steps in full ("2,000"), not bare digits.
      ...(plot.log_y ? { dtick: "D2", tickformat: ",~g" } : {}),
    },
    showlegend: twoStress || !!obs,
  };

  const prob = r.probability_plot || null;
  const TABS = [
    { id: "plot", label: "Life–stress" },
    ...(prob ? [{ id: "prob", label: "Probability plot" }] : []),
    ...(modelId ? [{ id: "calc", label: "Use-level calculator" }] : []),
    { id: "detail", label: "Coefficients & fit" },
  ];

  return (
    <div className="alt-result">
      <NoMaximumNotice notice={r.no_finite_maximum} />
      {(r.unit_warnings || []).map((w) => (
        <div className="detail-note warn" key={w}>⚠ {w}</div>
      ))}
      <AltSummary r={r} calculator={!!modelId} />
      <SegmentedControl
        label="View"
        value={tab}
        onChange={setTab}
        style={{ alignSelf: "flex-start" }}
        options={TABS.map((t) => ({ value: t.id, label: t.label }))}
      />

      {tab === "plot" && (
        <div className="alt-plot-wrap">
          <Plot data={traces} layout={layout} />
          <p className="muted-line" style={{ margin: 0 }}>
            Each diamond is a tested stress level; the line is the fitted
            life-stress relationship, extended below the lowest test stress toward
            your use level. {plot.log_y ? "The life axis is logarithmic." : ""}
            {obs ? ` Inspection data: each grey bar is a unit found failed between two read-outs${
              obs.shown < obs.n_ranges + obs.n_failures ? ` (${obs.shown.toLocaleString()} of ${(obs.n_ranges + obs.n_failures).toLocaleString()} shown)` : ""
            }; the fit takes the whole interval, not a midpoint.` : ""}
          </p>
        </div>
      )}

      {tab === "prob" && prob && <ProbabilityPanel prob={prob} unit={r.unit} twoStress={twoStress} />}

      {tab === "calc" && modelId && (
        <AltCalculator modelId={modelId} results={r} />
      )}

      {tab === "detail" && (
        <div className="alt-detail">
          <div className="alt-cols">
            <div>
              <div className="ds-section-h">Distribution</div>
              <p className="muted-line">
                {r.distribution} · {r.life_model} life-stress model · n = {r.n}
                {r.interval_censored ? " · inspection (interval) data" : ""}
              </p>
              <table className="mini-table alt-coef-table">
                <thead><tr><th>Parameter</th><th>Estimate</th><th>95% CI</th></tr></thead>
                <tbody>
                  {(r.params || []).map((p) => (
                    <tr key={p.name}><td>{p.name}</td><td>{fmt(p.value)}</td><td>{ci(p.ci)}</td></tr>
                  ))}
                  {(r.coefficients || []).map((c) => (
                    <tr key={c.name}>
                      <td>{c.name} <span className="muted">(life-stress)</span></td><td>{fmt(c.value)}</td><td>{ci(c.ci)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted-line" style={{ margin: "4px 0 0" }}>
                Wald intervals (SurPyval's param_cb). The use-level calculator gives likelihood-ratio
                {(r.bounds_methods || ["bootstrap"]).includes("bootstrap") ? " and bootstrap" : ""} intervals too.
              </p>
              {(r.gof || []).length > 0 && (
                <p className="muted-line" style={{ marginBottom: 0 }}>
                  {r.gof.map((g) => `${g.label} ${fmt(g.value, 5)}`).join(" · ")}
                </p>
              )}
            </div>
            <div>
              <div className="ds-section-h">Fitted life at each tested level</div>
              <table className="mini-table">
                <thead>
                  <tr>
                    {(r.stresses || []).map((s) => <th key={s.key}>{stressName(s)}</th>)}
                    <th>n</th><th>Characteristic life{r.unit ? ` (${r.unit})` : ""}</th>
                  </tr>
                </thead>
                <tbody>
                  {(r.levels || []).map((lvl, i) => (
                    <tr key={i}>
                      {lvl.stress.map((v, j) => <td key={j}>{fmt(v, 5)}</td>)}
                      <td>{lvl.n}</td><td>{fmt(lvl.characteristic_life)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Per-stress-level probability plot: each level's failure points on the
// distribution's probability paper, with its fitted CDF line. Data is already
// linearised server-side, so the axes are plain — a good fit shows parallel
// straight lines (common shape) with the points hugging them.
function ProbabilityPanel({ prob, unit, twoStress }) {
  const traces = [];
  (prob.series || []).forEach((s, i) => {
    const color = SERIES[i % SERIES.length];
    if (s.line) {
      traces.push({
        x: s.line.x, y: s.line.y, mode: "lines", type: "scatter",
        line: { color, width: 2 }, name: s.label, legendgroup: `p${i}`,
      });
    }
    if (s.scatter) {
      traces.push({
        x: s.scatter.x, y: s.scatter.y, mode: "markers", type: "scatter",
        marker: { color, size: 6, line: { color: SURFACE, width: 0.5 } },
        name: s.label, legendgroup: `p${i}`, showlegend: !s.line,
        hovertemplate: `${s.label}<extra></extra>`,
      });
    }
  });

  const layout = {
    height: 440,
    xaxis: {
      title: { text: unit ? `Time (${unit})` : "Time" },
      tickvals: prob.x_ticks?.vals, ticktext: prob.x_ticks?.labels,
      // Probability paper: both grids carry meaning.
      showgrid: true, gridcolor: GRID,
    },
    yaxis: {
      title: { text: "Unreliability, F(t)" },
      tickvals: prob.y_ticks?.vals, ticktext: prob.y_ticks?.labels,
    },
  };

  return (
    <div className="alt-plot-wrap">
      <Plot data={traces} layout={layout} />
      <p className="muted-line" style={{ margin: 0 }}>
        Each colour is a tested stress level: points are the observed failures on
        {" "}{prob.distribution} probability paper, the line is the model's fit for
        that level. A good fit shows the points tracking parallel straight lines
        (a shared shape across stresses).
      </p>
    </div>
  );
}
