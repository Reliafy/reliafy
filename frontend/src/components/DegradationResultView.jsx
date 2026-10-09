import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, DANGER, DATA_INK, bandPair, dataPoints, fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { degradationReliability } from "../api.js";
import { unitInText } from "./unitText.js";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";

// Per-item colours: the theme's series colours while each item can have its
// own; past that, every item is plain ink (colours are never reused).
const COLORS = COLORWAY;

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

// Population survival curve + shaded two-stage confidence band, as plotly data.
function buildRelTraces(curves, xTitle, rel, pointLife, designLife) {
  const data = [];
  if (curves.lower && curves.upper) {
    data.push(...bandPair(curves.x, curves.lower, curves.upper, { name: "Confidence band" }));
  }
  data.push(fitLine({ x: curves.x, y: curves.sf, name: "Reliability" }));
  const layout = {
    height: 340,
    showlegend: false,
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
    shapes: [],
    annotations: [],
  };
  if (rel != null && Number.isFinite(rel)) {
    layout.shapes.push(referenceShape({ y: rel, line: { dash: "dot" } }));
    layout.annotations.push({
      xref: "paper", x: 0, y: rel, xanchor: "left", yanchor: "bottom",
      text: `R = ${(rel * 100).toFixed(0)}%`, showarrow: false,
    });
  }
  // Design-life marker (conservative lower bound) and point-estimate tick.
  if (designLife != null && Number.isFinite(designLife)) {
    layout.shapes.push(referenceShape({ x: designLife, y1: rel ?? 1, yref: "y", y0: 0 }));
    data.push(optimumMarker({
      x: [designLife], y: [rel], name: "Design life", text: ["Design life"],
      textposition: "top right", hoverinfo: "x",
    }));
  }
  if (pointLife != null && Number.isFinite(pointLife)) {
    data.push(dataPoints({
      x: [pointLife], y: [rel], name: "Point estimate", hoverinfo: "x",
      marker: { symbol: "circle-open", size: 8, line: { color: DATA_INK, width: 1.5 } },
    }));
  }
  return { data, layout };
}

// The fitted degradation model, answer first (#311): the mean life and the
// design life (at the chosen confidence and reliability), then the per-item
// paths against the failure threshold, the reliability curve with its inputs,
// and the pseudo failure times and life model folded under Details.
// `modelId` (saved models only) enables re-fetching the confidence band at a
// different confidence level.
export default function DegradationResultView({ results, modelId, name = null }) {
  const r = results || {};
  const units = r.units || [];
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const yTitle = r.measurement_unit ? `Measurement (${r.measurement_unit})` : "Measurement";

  const traces = [];
  const coloured = units.length <= COLORS.length;
  units.forEach((u, idx) => {
    const color = coloured ? COLORS[idx] : DATA_INK;
    traces.push({
      x: u.line.x, y: u.line.y, mode: "lines", type: "scatter",
      line: { color, width: 1.5 }, opacity: coloured ? 1 : 0.6, name: u.id, legendgroup: u.id,
      hoverinfo: "skip", showlegend: false,
    });
    traces.push(dataPoints({
      x: u.scatter.x, y: u.scatter.y, marker: { color }, name: u.id, legendgroup: u.id, showlegend: coloured,
    }));
  });

  const layout = {
    height: 440,
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: yTitle } },
    // The failure threshold: red, it is where an item has failed.
    shapes: [referenceShape({ y: r.threshold, line: { color: DANGER, width: 1.5 } })],
    annotations: [{
      xref: "paper", x: 1, y: r.threshold, xanchor: "right", yanchor: "bottom",
      text: `Threshold ${fmt(r.threshold)}${r.measurement_unit ? " " + r.measurement_unit : ""}`,
      showarrow: false, font: { color: DANGER },
    }],
  };

  const life = r.life_model || {};

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
  const relTraces = curves ? buildRelTraces(curves, xTitle, rel, pointLife, designLife) : null;

  const tUnit = r.unit ? ` ${unitInText(r.unit)}` : "";
  const mUnit = r.measurement_unit ? ` ${r.measurement_unit}` : "";

  return (
    <>
      <ResultSummary
        sentence={
          <>
            <b>{r.path_model?.name || "Degradation"}</b> wear reaches the <b>{fmt(r.threshold)}{mUnit}</b> threshold
            at a mean life of <b>{formatNumber(life.mean)}{tUnit}</b>
            {designLife != null && (
              <>
                ; <b>{fmt(relPct, 0)}%</b> of the population survive to at least{" "}
                <b>{formatNumber(designLife)}{tUnit}</b> at {fmt(confPct, 0)}% confidence
              </>
            )}
            .
          </>
        }
        stats={[
          { label: `Mean life${r.unit ? ` (${unitInText(r.unit)})` : ""}`, value: formatNumber(life.mean) },
          designLife != null && {
            label: `Design life${r.unit ? ` (${unitInText(r.unit)})` : ""}`,
            value: formatNumber(designLife),
            hint: `${fmt(relPct, 0)}% survive, ${fmt(confPct, 0)}% confidence`,
          },
          { label: "Items", value: r.n_units ?? "—" },
          { label: "Threshold", value: `${fmt(r.threshold)}${mUnit}` },
        ]}
      />

      <div className="card" style={{ marginTop: "1rem" }}>
        <Plot data={traces} layout={layout} download={`${name || "Degradation model"} — degradation paths`} />
      </div>

      {relTraces && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2 style={{ marginTop: 0 }}>Reliability &amp; design life</h2>
          <p className="muted-line">
            Population reliability from the fitted life model, with a{" "}
            {fmt(confPct, 0)}% two-stage confidence band. The band widens the
            fewer items were tracked — it is the uncertainty in the population
            curve itself, not scatter between items.
          </p>

          <div className="row" style={{ gap: "1.2rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "0.4rem" }}>
            <label className="login-field" style={{ width: 150 }}>
              <span>Confidence %</span>
              <input
                type="number" min="1" max="99" step="1" value={confPct}
                disabled={!modelId || busy}
                onChange={(e) => setConfPct(Number(e.target.value))}
                onBlur={(e) => fetchBand(Number(e.target.value))}
                onKeyDown={(e) => { if (e.key === "Enter") fetchBand(Number(e.target.value)); }}
              />
            </label>
            <label className="login-field" style={{ width: 150 }}>
              <span>Reliability %</span>
              <input
                type="number" min="1" max="99" step="1" value={relPct}
                onChange={(e) => setRelPct(Number(e.target.value))}
              />
            </label>
            {!modelId && (
              <span className="muted-line" style={{ margin: 0, alignSelf: "center" }}>
                Save the model to adjust the confidence level.
              </span>
            )}
            {busy && <span className="muted-line" style={{ margin: 0, alignSelf: "center" }}>Computing…</span>}
          </div>

          {cbError && <div className="error">{cbError}</div>}

          {pointLife != null && (
            <p className="muted-line" style={{ margin: "0.2rem 0 0" }}>
              Design life above: {fmt(relPct, 0)}% survive at {fmt(confPct, 0)}% confidence. Best estimate,
              ignoring uncertainty: {formatNumber(pointLife)}{tUnit}.
            </p>
          )}

          <Plot
            data={relTraces.data} layout={relTraces.layout} style={{ marginTop: "0.6rem" }}
            download={`${name || "Degradation model"} — reliability and design life`}
          />
        </div>
      )}

      <ResultDetails summary="Pseudo failure times and life model">
        <div className="row" style={{ gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 280px", minWidth: 0 }}>
            <p className="rs-note" style={{ marginTop: 0 }}>
              When each item's fitted path crosses the threshold. The life model is fitted to these.
            </p>
            <table className="lib-table">
              <thead><tr><th>Item</th><th>Crossing{r.unit ? ` (${r.unit})` : ""}</th><th /></tr></thead>
              <tbody>
                {units.map((u) => (
                  <tr key={u.id}>
                    <td>{u.id}</td>
                    <td className="lib-n">{u.pseudo_failure_time === null ? "never (censored)" : formatNumber(u.pseudo_failure_time, { sig: 4 })}</td>
                    <td className="lib-date">{u.censored ? "censored" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ flex: "1 1 280px", minWidth: 0 }}>
            <p className="rs-note" style={{ marginTop: 0 }}>
              {life.distribution || "—"} fitted to the pseudo failure times.
            </p>
            <table className="lib-table">
              <tbody>
                {(life.params || []).map((p) => (
                  <tr key={p.name}><td>{p.name}</td><td className="lib-n">{formatNumber(p.value, { sig: 4 })}</td></tr>
                ))}
                <tr><td>mean</td><td className="lib-n">{formatNumber(life.mean, { sig: 4 })}</td></tr>
              </tbody>
            </table>

            {r.path_selection && (
              <>
                <p className="rs-note">Path selection (AICc, lower is better)</p>
                <table className="lib-table">
                  <tbody>
                    {r.path_selection.slice(0, 5).map((row, i) => (
                      <tr key={row.id}>
                        <td>{row.name || row.id}{i === 0 ? " ✓" : ""}</td>
                        <td className="lib-n">{fmt(row.aicc, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      </ResultDetails>
    </>
  );
}
