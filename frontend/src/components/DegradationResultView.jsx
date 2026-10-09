import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import Modal from "./Modal.jsx";
import { COLORWAY, DANGER, DATA_INK, bandPair, dataPoints, fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { degradationReliability } from "../api.js";
import { unitInText } from "./unitText.js";
import { paramView } from "./LifeSummary.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";

// Per-item colours: the theme's series colours while each item can have its
// own; past that, every item is plain ink (colours are never reused). Items
// are named on hover, not in a legend.
const COLORS = COLORWAY;

const TABS = [
  { id: "paths", label: "Path plot" },
  { id: "rel", label: "Reliability" },
];

// Both charts share a height that keeps the page on one 900 px screen.
const PLOT_HEIGHT = 470;

const fmt = (v, digits = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

// First crossing of a monotone-decreasing curve y(x) through level `level`,
// linearly interpolated. Returns null if the curve never reaches it.
function crossing(x, y, level) {
  if (!x || !y) return null;
  for (let i = 1; i < x.length; i++) {
    const y0 = y[i - 1], y1 = y[i];
    if (y0 == null || y1 == null) continue;
    if ((y0 >= level && y1 <= level) || (y0 <= level && y1 >= level)) {
      const f = y1 === y0 ? 0 : (level - y0) / (y1 - y0);
      return x[i - 1] + f * (x[i] - x[i - 1]);
    }
  }
  return null;
}

// Each item's measurements and fitted path against the failure threshold.
function buildPathTraces(r, xTitle, yTitle, tUnit, mUnit) {
  const units = r.units || [];
  const coloured = units.length <= COLORS.length;
  const data = [];
  units.forEach((u, idx) => {
    const color = coloured ? COLORS[idx] : DATA_INK;
    data.push({
      x: u.line.x, y: u.line.y, mode: "lines", type: "scatter",
      line: { color, width: 1.5 }, opacity: coloured ? 1 : 0.6, name: u.id,
      hoverinfo: "skip", showlegend: false,
    });
    data.push(dataPoints({
      x: u.scatter.x, y: u.scatter.y, marker: { color }, name: u.id, showlegend: false,
      hovertemplate: `<b>%{fullData.name}</b><br>%{x:,}${tUnit}<br>%{y}${mUnit}<extra></extra>`,
    }));
  });
  const layout = {
    height: PLOT_HEIGHT,
    showlegend: false,
    margin: { t: 24 },
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: yTitle } },
    // The failure threshold: red, it is where an item has failed.
    shapes: [referenceShape({ y: r.threshold, line: { color: DANGER, width: 1.5 } })],
    annotations: [{
      xref: "paper", x: 1, y: r.threshold, xanchor: "right", yanchor: "bottom",
      text: `Threshold ${fmt(r.threshold)}${mUnit}`,
      showarrow: false, font: { color: DANGER },
    }],
  };
  return { data, layout };
}

// Population survival curve + shaded two-stage confidence band, as plotly data.
// The labels keep off the curve: "R = 90%" at the right end of its line, where
// the curve has fallen away, and "Design life" at the foot of its marker line.
function buildRelTraces(curves, xTitle, rel, pointLife, designLife) {
  const data = [];
  if (curves.lower && curves.upper) {
    data.push(...bandPair(curves.x, curves.lower, curves.upper, { name: "Confidence band" }));
  }
  data.push(fitLine({ x: curves.x, y: curves.sf, name: "Reliability" }));
  const layout = {
    height: PLOT_HEIGHT,
    showlegend: false,
    margin: { t: 16 },
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
    shapes: [],
    annotations: [],
  };
  if (rel != null && Number.isFinite(rel)) {
    layout.shapes.push(referenceShape({ y: rel, line: { dash: "dot" } }));
    layout.annotations.push({
      xref: "paper", x: 1, y: rel, xanchor: "right", yanchor: "bottom",
      text: `R = ${(rel * 100).toFixed(0)}%`, showarrow: false,
    });
  }
  // Design-life marker (conservative lower bound) and point-estimate tick.
  if (designLife != null && Number.isFinite(designLife)) {
    layout.shapes.push(referenceShape({ x: designLife, y1: rel ?? 1, yref: "y", y0: 0 }));
    data.push(optimumMarker({ x: [designLife], y: [rel], name: "Design life", text: undefined, mode: "markers", hoverinfo: "x" }));
    layout.annotations.push({
      x: designLife, y: 0, yanchor: "bottom", xanchor: "left", xshift: 4,
      text: "Design life", showarrow: false,
    });
  }
  if (pointLife != null && Number.isFinite(pointLife)) {
    data.push(dataPoints({
      x: [pointLife], y: [rel], name: "Point estimate", hoverinfo: "x",
      marker: { symbol: "circle-open", size: 8, line: { color: DATA_INK, width: 1.5 } },
    }));
  }
  return { data, layout };
}

// The fitted degradation model in the life model page's shape (#311): tabs
// first, each a chart with a side panel. Path plot: the per-item paths against
// the threshold, beside the Parameters card and the design life. Reliability:
// the population curve with its band, beside the confidence and reliability
// inputs. Path selection opens from the Parameters card; the pseudo failure
// times are folded under Details.
// `modelId` (saved models only) enables re-fetching the confidence band at a
// different confidence level.
export default function DegradationResultView({ results, modelId, name = null }) {
  const r = results || {};
  const units = r.units || [];
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const yTitle = r.measurement_unit ? `Measurement (${r.measurement_unit})` : "Measurement";
  const tUnit = r.unit ? ` ${unitInText(r.unit)}` : "";
  const mUnit = r.measurement_unit ? ` ${r.measurement_unit}` : "";

  const life = r.life_model || {};
  const [tab, setTab] = useState("paths");
  const [statsOpen, setStatsOpen] = useState(false);

  // Reliability curve with two-stage confidence band. Seeded from the payload's
  // default-confidence curves; re-fetched at other levels for saved models.
  const [curves, setCurves] = useState(life.curves || null);
  const initialConf = life.curves?.alpha_ci != null ? 1 - life.curves.alpha_ci : 0.9;
  const [confPct, setConfPct] = useState(Math.round(initialConf * 100));
  const [relPct, setRelPct] = useState(90); // target reliability for design life
  const [busy, setBusy] = useState(false);
  const [cbError, setCbError] = useState(null);

  // Re-seed when a different model's results are rendered.
  useEffect(() => {
    setCurves(life.curves || null);
    setConfPct(Math.round((life.curves?.alpha_ci != null ? 1 - life.curves.alpha_ci : 0.9) * 100));
  }, [results]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchBand = async (pct) => {
    if (!modelId) return;
    const conf = pct / 100;
    if (!(conf > 0 && conf < 1)) return;
    setBusy(true);
    setCbError(null);
    try {
      const c = await degradationReliability(modelId, conf);
      if (c && c.x) setCurves(c);
      else setCbError("No confidence band available for this model.");
    } catch (err) {
      setCbError(err.message || "Couldn't compute the confidence band.");
    } finally {
      setBusy(false);
    }
  };

  const rel = Math.min(Math.max(relPct / 100, 1e-6), 1 - 1e-6);
  const pointLife = curves ? crossing(curves.x, curves.sf, rel) : null;
  const designLife = curves?.lower ? crossing(curves.x, curves.lower, rel) : null;
  const paths = buildPathTraces(r, xTitle, yTitle, tUnit, mUnit);
  const relTraces = curves ? buildRelTraces(curves, xTitle, rel, pointLife, designLife) : null;

  // The life model's parameters by their plain names (shape before scale).
  const lifeAsResult = { distribution: life.distribution, distribution_id: life.distribution_id, unit: r.unit };
  const order = ["beta", "alpha", "mu", "sigma"];
  const params = [...(life.params || [])].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  const nCensored = units.filter((u) => u.censored).length;
  const selection = r.path_selection || [];
  const best = selection[0];
  const unitLabel = r.unit ? ` (${unitInText(r.unit)})` : "";

  // The answer, quietly: the design life at the chosen reliability and
  // confidence (the best estimate joins it beside the reliability curve).
  const reading = (withPoint) => (
    <div className="life-reading">
      <div className="life-reading-title">Design life</div>
      {designLife != null ? (
        <div>
          <b>{formatNumber(designLife)}{tUnit}</b>: {fmt(relPct, 0)}% survive at {fmt(confPct, 0)}% confidence.
          {withPoint && pointLife != null && <> Best estimate, ignoring uncertainty: {formatNumber(pointLife)}{tUnit}.</>}
        </div>
      ) : pointLife != null ? (
        <div>
          Best estimate <b>{formatNumber(pointLife)}{tUnit}</b> for {fmt(relPct, 0)}% survival; the
          {" "}{fmt(confPct, 0)}% lower bound doesn't reach it within the curve.
        </div>
      ) : (
        <div>The curve doesn't fall to {fmt(relPct, 0)}% reliability within its range.</div>
      )}
    </div>
  );

  return (
    <>
      <div className="tabs">
        {TABS.filter((t) => t.id !== "rel" || relTraces).map((t) => (
          <button key={t.id} className={"tab" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="tab-panel">
        {tab === "paths" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <Plot data={paths.data} layout={paths.layout} download={`${name || "Degradation model"} — degradation paths`} />
            </div>
            <div className="aside">
              <div className="gof-card">
                <div className="gofh">Parameters</div>
                <div className="gofr">
                  <span className="gk">Path</span>
                  <span className="gv">{r.path_model?.name || "—"}</span>
                </div>
                <div className="gofr">
                  <span className="gk">Threshold</span>
                  <span className="gv">{fmt(r.threshold)}{mUnit}</span>
                </div>
                {params.map((p) => {
                  const v = paramView(lifeAsResult, p);
                  return (
                    <div className="gofr" key={p.name}>
                      <span className="gk">{v.label}</span>
                      <span className="gv">{v.value}</span>
                    </div>
                  );
                })}
                <div className="gofr">
                  <span className="gk">Mean life{unitLabel}</span>
                  <span className="gv">{formatNumber(life.mean)}</span>
                </div>
                <div className="gofr">
                  <span className="gk">Data</span>
                  <span className="gv">
                    {(r.n_units ?? units.length).toLocaleString()} items
                    {nCensored ? `, ${nCensored} censored` : ""}
                  </span>
                </div>
                {best && (
                  <button type="button" className="gofr gofr-link" onClick={() => setStatsOpen(true)}>
                    <span className="gk">Fit statistics</span>
                    <span className="gv">AICc {fmt(best.aicc, 1)} ›</span>
                  </button>
                )}
              </div>
              {reading(false)}
              <p className="life-method">
                Each item's {(r.path_model?.name || "fitted").toLowerCase()} path is extended to the threshold;
                {" "}{life.distribution || "the life model"} is fitted to those crossing times. Hover a point for its item.
              </p>
            </div>
          </div>
        )}

        {tab === "rel" && relTraces && (
          <div className="detail-panel">
            <div className="plotwrap">
              <Plot
                data={relTraces.data} layout={relTraces.layout}
                download={`${name || "Degradation model"} — reliability and design life`}
              />
            </div>
            <div className="aside">
              <div className="gof-card">
                <div className="gofh">Inputs</div>
                <div className="calc-eval-body">
                  <label className="calc-t">
                    <span>Confidence %</span>
                    <input
                      type="number" min="1" max="99" step="1" value={confPct}
                      disabled={!modelId || busy}
                      onChange={(e) => setConfPct(Number(e.target.value))}
                      onBlur={(e) => fetchBand(Number(e.target.value))}
                      onKeyDown={(e) => { if (e.key === "Enter") fetchBand(Number(e.target.value)); }}
                    />
                  </label>
                  <label className="calc-t">
                    <span>Reliability %</span>
                    <input
                      type="number" min="1" max="99" step="1" value={relPct}
                      onChange={(e) => setRelPct(Number(e.target.value))}
                    />
                  </label>
                  {!modelId && <span className="life-method">Save the model to adjust the confidence level.</span>}
                  {busy && <span className="life-method">Computing…</span>}
                </div>
              </div>
              {cbError && <div className="life-reading caveat">{cbError}</div>}
              {reading(true)}
              <p className="life-method">
                Population reliability from the fitted life model, with a {fmt(confPct, 0)}% two-stage
                confidence band. The band widens the fewer items were tracked: it is the uncertainty in
                the population curve itself, not scatter between items.
              </p>
            </div>
          </div>
        )}
      </div>

      <ResultDetails summary="Pseudo failure times">
        <p className="rs-note" style={{ marginTop: 0 }}>
          When each item's fitted path crosses the threshold. The life model is fitted to these.
        </p>
        <div className="rs-table-wrap">
          <table className="mini-table">
            <thead><tr><th>Item</th><th>Crossing{unitLabel}</th></tr></thead>
            <tbody>
              {units.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td>
                    {u.pseudo_failure_time === null
                      ? "never (censored)"
                      : `${formatNumber(u.pseudo_failure_time, { sig: 4 })}${u.censored ? " (censored)" : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ResultDetails>

      {statsOpen && (
        <Modal title="Fit statistics" onClose={() => setStatsOpen(false)}
               footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}>
                 <button onClick={() => setStatsOpen(false)}>Done</button></div>}>
          <p className="rs-note" style={{ marginTop: 0 }}>
            Path models compared by AICc over every item's readings; lower is better, and the best is used.
          </p>
          <div className="rs-table-wrap">
            <table className="mini-table">
              <thead><tr><th>Path</th><th>AICc</th><th>ΔAICc</th></tr></thead>
              <tbody>
                {selection.map((row, i) => (
                  <tr key={row.id}>
                    <td>{row.name || row.id}{i === 0 ? " (used)" : ""}</td>
                    <td>{fmt(row.aicc, 1)}</td>
                    <td>{i > 0 && row.aicc != null && best?.aicc != null ? `+${fmt(row.aicc - best.aicc, 1)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Modal>
      )}
    </>
  );
}
