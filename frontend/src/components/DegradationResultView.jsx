import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import { Link } from "react-router-dom";
import { COLORWAY, DANGER, DATA_INK, bandPair, dataPoints, fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { degradationReliability } from "../api.js";
import { unitInText } from "./unitText.js";
import { paramView } from "./LifeSummary.jsx";
import { formatNumber, formatPercent } from "../format.js";
import { meanLevels } from "../meanLife.js";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { CheckCard, ChecksGrid, NumbersSheet, PlotCard, PlotPanel, ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { InducedLifeCard, InducedLifeCheck, useInducedLife } from "./DegradationInducedLife.jsx";
import {
  PATH_FORMULAS, POPULATION_METHODS, bLives, bandLevel, degradationTabs, meanAnswer, pathParams, pathRanking,
  reliabilityAt, resolveDegradationTab, scatterCheck, thresholdText, timeAtReliability,
} from "../degradationFrame.js";
import "./DegradationResultView.css";

// A fitted degradation model in the model frame's five tabs:
//   Paths                  each item's readings and fitted path against the
//                          failure threshold, beside the model in brief
//   Calculator             the population's reliability curve with its band:
//                          the time at a reliability (the design life) and
//                          the reliability at a time
//   Model characteristics  the mean life and the B-lives with their band
//   Diagnostics            do the two routes to a life agree (the induced
//                          life), does the path shape suit the readings
//                          (residuals), which path shape fits best (AICc)
//   Data                   what it was fitted to, the items' crossing times
//                          and every parameter
// ``modelId`` (a saved model the viewer can ask) fetches the band at another
// confidence and the induced life; a shared page shows the saved figures.

// Per-item colours: the theme's series colours while each item can have its
// own; past that, every item is plain ink (colours are never reused). Items
// are named on hover, not in a legend.
const itemColour = (n) => (i) => (n <= COLORWAY.length ? COLORWAY[i] : DATA_INK);
const SIGN_IN = "Sign in to a copy of this model to change the confidence.";
const SMALL = { margin: { t: 6, r: 10, b: 40, l: 56 } };

const pct = (v) => formatNumber(v, { sig: 3 });

// Each item's measurements and fitted path against the failure threshold.
function pathTraces(r, xTitle, yTitle, tUnit, mUnit) {
  const units = r.units || [];
  const colour = itemColour(units.length);
  const data = [];
  units.forEach((u, idx) => {
    const color = colour(idx);
    data.push({
      x: u.line.x, y: u.line.y, mode: "lines", type: "scatter",
      line: { color, width: 1.5 }, opacity: units.length <= COLORWAY.length ? 1 : 0.6, name: u.id,
      hoverinfo: "skip", showlegend: false,
    });
    data.push(dataPoints({
      x: u.scatter.x, y: u.scatter.y, marker: { color }, name: u.id, showlegend: false,
      hovertemplate: `<b>%{fullData.name}</b><br>%{x:,}${tUnit}<br>%{y}${mUnit}<extra></extra>`,
    }));
  });
  const layout = {
    showlegend: false,
    margin: { t: 24 },
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: yTitle } },
    // The failure threshold: red, it is where an item has failed.
    shapes: [referenceShape({ y: r.threshold, line: { color: DANGER, width: 1.5 } })],
    annotations: [{
      xref: "paper", x: 1, y: r.threshold, xanchor: "right", yanchor: "bottom",
      text: `Threshold ${thresholdText(r)}`, showarrow: false, font: { color: DANGER },
    }],
  };
  return { data, layout };
}

// The population's reliability curve with its band, the chosen reliability,
// the design life (the band's lower end there) and the best estimate; the
// chosen time's reading when there is one.
function relTraces(curves, xTitle, rel, life, atTime) {
  const data = [];
  if (curves.lower && curves.upper) data.push(...bandPair(curves.x, curves.lower, curves.upper, { name: "Confidence band" }));
  data.push(fitLine({ x: curves.x, y: curves.sf, name: "Reliability" }));
  const layout = {
    showlegend: false,
    margin: { t: 16 },
    xaxis: { title: { text: xTitle } },
    yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
    shapes: [referenceShape({ y: rel, line: { dash: "dot" } })],
    annotations: [{
      xref: "paper", x: 1, y: rel, xanchor: "right", yanchor: "bottom",
      text: `R = ${pct(rel * 100)}%`, showarrow: false,
    }],
  };
  if (life?.lower != null) {
    layout.shapes.push(referenceShape({ x: life.lower, yref: "y", y0: 0, y1: rel }));
    data.push(optimumMarker({ x: [life.lower], y: [rel], name: "Design life", text: undefined, mode: "markers", hoverinfo: "x" }));
    layout.annotations.push({ x: life.lower, y: 0, yanchor: "bottom", xanchor: "left", xshift: 4, text: "Design life", showarrow: false });
  }
  if (life?.value != null) {
    data.push(dataPoints({
      x: [life.value], y: [rel], name: "Best estimate", hoverinfo: "x",
      marker: { symbol: "circle-open", size: 8, line: { color: DATA_INK, width: 1.5 } },
    }));
  }
  if (atTime?.value != null) {
    layout.shapes.push(referenceShape({ x: atTime.t, line: { dash: "dot" } }));
    data.push(dataPoints({
      x: [atTime.t], y: [atTime.value], name: "At this time", hoverinfo: "x+y",
      marker: { symbol: "diamond", size: 9, color: DATA_INK },
    }));
  }
  return { data, layout };
}

// "3,210–3,950 hours" (or "—").
const spanText = (lo, hi, u) => (lo != null && hi != null ? `${formatNumber(lo)}–${formatNumber(hi)}${u}` : "—");

// The model's life model, parameters by their plain names (shape before scale).
function lifeParams(r) {
  const life = r.life_model || {};
  const asResult = { distribution: life.distribution, distribution_id: life.distribution_id, unit: r.unit };
  const order = ["beta", "alpha", "mu", "sigma"];
  return [...(life.params || [])]
    .sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
    .map((p) => ({ ...paramView(asResult, p), name: p.name }));
}

// ---- Paths --------------------------------------------------------------------

function PathsTab({ r, name, design, onDiag, onCalc }) {
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const yTitle = r.measurement_unit ? `Measurement (${r.measurement_unit})` : "Measurement";
  const tUnit = r.unit ? ` ${unitInText(r.unit)}` : "";
  const mUnit = r.measurement_unit ? ` ${r.measurement_unit}` : "";
  const paths = pathTraces(r, xTitle, yTitle, tUnit, mUnit);
  const units = r.units || [];
  const never = units.filter((u) => u.censored).length;
  const mean = meanAnswer(r);
  const formula = PATH_FORMULAS[r.path_model?.id];
  const best = (r.path_selection || []).length > 1 ? r.path_selection[0] : null;
  return (
    <PlotPanel
      plot={
        <PlotCard>
          <Plot fill data={paths.data} layout={paths.layout} download={`${name || "Degradation model"} — degradation paths`} />
        </PlotCard>
      }
      side={
        <>
          <div className="gof-card">
            <div className="gofh">The model</div>
            <div className="gofr">
              <span className="gk">Path</span>
              <span className="gv-col">
                <span className="gv">{r.path_model?.name || "—"}</span>
                {formula && <span className="param-ci">y = {formula}</span>}
              </span>
            </div>
            <div className="gofr"><span className="gk">Threshold</span><span className="gv">{thresholdText(r)}</span></div>
            <div className="gofr"><span className="gk">Life</span><span className="gv">{r.life_model?.distribution || "—"}</span></div>
            {lifeParams(r).map((p) => (
              <div className="gofr" key={p.name}><span className="gk">{p.label}</span><span className="gv">{p.value}</span></div>
            ))}
            {mean.kind === "mean" && (
              <div className="gofr"><span className="gk">Mean life</span><span className="gv">{formatNumber(mean.value)}{tUnit}</span></div>
            )}
            <div className="gofr">
              <span className="gk">Data</span>
              <span className="gv">
                {(r.n_units ?? units.length).toLocaleString("en-US")} items{never ? `, ${never} not at the threshold` : ""}
              </span>
            </div>
            {best && onDiag && (
              <button type="button" className="gofr gofr-link" onClick={onDiag}
                      aria-label={`Path comparison: ${best.name} has the lowest AICc. Open Diagnostics`}>
                <span className="gk">Path comparison</span>
                <span className="gv">AICc {formatNumber(best.aicc, { sig: 4 })} ›</span>
              </button>
            )}
          </div>
          {design && <DesignLife design={design} onCalc={onCalc} />}
          <p className="life-method">
            Each item's path is extended to the threshold; the {r.life_model?.distribution || "life"} model is fitted
            to those crossing times. Hover a point for its item.
          </p>
        </>
      }
    />
  );
}

// The design life in a line: the band's lower end at the chosen reliability.
function DesignLife({ design, onCalc }) {
  const { life, relPct, level, unit } = design;
  const u = unit ? ` ${unitInText(unit)}` : "";
  return (
    <div className="life-reading">
      <div className="life-reading-title">Design life</div>
      {life?.lower != null ? (
        <div><b>{formatNumber(life.lower)}{u}</b>: {pct(relPct)}% survive, the lower end of the {pct(level)}% band.</div>
      ) : life?.value != null ? (
        <div>Best estimate <b>{formatNumber(life.value)}{u}</b> for {pct(relPct)}% survival; the band's lower end doesn't reach it on the curve.</div>
      ) : (
        <div>The curve doesn't fall to {pct(relPct)}% within its range.</div>
      )}
      {onCalc && <button type="button" className="link deg-to-calc" onClick={onCalc}>Another reliability or confidence ›</button>}
    </div>
  );
}

// ---- Calculator ---------------------------------------------------------------

function CalculatorTab({ r, name, curves, band, relPct, setRelPct, time, setTime }) {
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const u = r.unit ? ` ${unitInText(r.unit)}` : "";
  const rel = Math.min(Math.max(relPct / 100, 1e-6), 1 - 1e-6);
  const life = timeAtReliability(curves, rel);
  const t = time === "" ? null : Number(time);
  const at = t != null ? reliabilityAt(curves, t) : null;
  const traces = relTraces(curves, xTitle, rel, life, at && !at.beyond ? { ...at, t } : null);
  const level = bandLevel(curves);
  return (
    <PlotPanel
      plot={
        <PlotCard>
          <Plot fill data={traces.data} layout={traces.layout} download={`${name || "Degradation model"} — reliability and design life`} />
        </PlotCard>
      }
      side={
        <>
          <div className="gof-card">
            <div className="gofh">Ask the model</div>
            <div className="calc-eval-body">
              <label className="calc-t">
                <span>Reliability %</span>
                <input type="number" inputMode="numeric" min="1" max="99" step="1" value={relPct}
                       onChange={(e) => setRelPct(Number(e.target.value))} />
              </label>
              <label className="calc-t">
                <span>Time{r.unit ? ` (${unitInText(r.unit)})` : ""}</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={time} placeholder="any time"
                       onChange={(e) => setTime(e.target.value)} />
              </label>
              <BandInput band={band} />
            </div>
          </div>
          {band.error && <div className="life-reading caveat" role="alert">{band.error}</div>}
          <div className="gof-card" aria-live="polite">
            <div className="gofh">Time to {pct(relPct)}% reliability</div>
            <div className="gofr"><span className="gk">Best estimate</span><span className="gv">{life?.value != null ? `${formatNumber(life.value)}${u}` : "—"}</span></div>
            <div className="gofr"><span className="gk">Design life</span><span className="gv">{life?.lower != null ? `${formatNumber(life.lower)}${u}` : "—"}</span></div>
            <div className="gofr"><span className="gk">{pct(level)}% band</span><span className="gv">{spanText(life?.lower, life?.upper, u)}</span></div>
            {at && (
              <>
                <div className="gofh deg-subhead">Reliability at {formatNumber(t)}{u}</div>
                {at.beyond ? (
                  <p className="mf-note">Past the curve's end, where 99% have failed.</p>
                ) : (
                  <>
                    <div className="gofr"><span className="gk">Best estimate</span><span className="gv">{formatPercent(at.value, { sig: 3 })}</span></div>
                    {at.lower != null && (
                      <div className="gofr"><span className="gk">{pct(level)}% band</span>
                        <span className="gv">{formatPercent(at.lower, { sig: 3 })}–{formatPercent(at.upper, { sig: 3 })}</span></div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
          <p className="life-method">
            The design life is where the band's lower edge reaches the reliability: the cautious figure to plan with.
            The band is the uncertainty in the population curve from tracking only {r.n_units ?? (r.units || []).length} items.
          </p>
        </>
      }
    />
  );
}

// The band's confidence, typed (the Calculator) — fetched again on Enter or
// leaving the field. A shared page can't ask the model.
function BandInput({ band }) {
  const [text, setText] = useState(String(band.level));
  const [prev, setPrev] = useState(band.level);
  if (band.level !== prev) {
    setPrev(band.level);
    setText(String(band.level));
  }
  const commit = () => {
    const v = Number(text);
    if (v > 0 && v < 100 && v !== band.level) band.set(v);
    else setText(String(band.level));
  };
  return (
    <>
      <label className="calc-t">
        <span>Confidence %</span>
        <input type="number" inputMode="numeric" min="1" max="99" step="1" value={text}
               disabled={!band.can || band.busy} title={band.can ? undefined : SIGN_IN}
               onChange={(e) => setText(e.target.value)} onBlur={commit}
               onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
      </label>
      {!band.can && <span className="life-method">{SIGN_IN}</span>}
      {band.busy && <span className="life-method">Working…</span>}
    </>
  );
}

// ---- Model characteristics ------------------------------------------------------

function CharsTab({ r, curves, band, onCalc }) {
  const u = r.unit ? ` ${unitInText(r.unit)}` : "";
  const mean = meanAnswer(r);
  const rows = bLives(curves);
  const median = rows.find((b) => b.label === "B50");
  const b10 = rows.find((b) => b.label === "B10");
  const level = bandLevel(curves);
  const chooser = band.can ? (
    <Select
      value={band.level}
      onChange={(v) => band.set(Number(v))}
      className="model-chars-conf"
      ariaLabel="Confidence of the band"
      title="The confidence of the band (two-sided), shared with the Calculator"
      options={meanLevels(band.level).map((l) => ({ value: l, label: `${l}% band` }))}
    />
  ) : null;
  return (
    <NumbersSheet className="model-chars">
      <section className="gof-card model-chars-card" aria-labelledby="deg-chars-mean">
        <div className="gofh life-card-head">
          <h3 id="deg-chars-mean" className="model-chars-h">Mean and design life</h3>
        </div>
        <div className="gofr">
          <span className="gk">Mean life (MTTF)</span>
          <span className="gv-col">
            <span className="gv">{mean.kind === "mean" ? `${formatNumber(mean.value)}${u}` : "None"}</span>
            {mean.kind === "mean" && <span className="param-ci">no band: the fit gives the mean alone</span>}
          </span>
        </div>
        {b10?.lower != null && (
          <div className="gofr">
            <span className="gk">Design life (B10)</span>
            <span className="gv-col">
              <span className="gv">{formatNumber(b10.lower)}{u}</span>
              <span className="param-ci">90% survive: the {pct(level)}% band's lower end</span>
            </span>
          </div>
        )}
        {median?.value != null && (
          <div className="gofr">
            <span className="gk">Median (B50)</span>
            <span className="gv-col">
              <span className="gv">{formatNumber(median.value)}{u}</span>
              {median.lower != null && <span className="param-ci">{pct(level)}% band {spanText(median.lower, median.upper, "")}</span>}
            </span>
          </div>
        )}
        <div className="model-chars-what">
          {mean.kind === "mean" ? (
            <p>The average time to reach the threshold, from the life model fitted to the items' crossing times. Half
              the items reach it by the median.</p>
          ) : <p>{mean.why}</p>}
          {mean.caveat && <p className="hint">{mean.caveat}</p>}
        </div>
      </section>
      <section className="gof-card model-chars-card" aria-labelledby="deg-chars-blives">
        <div className="gofh life-card-head">
          <h3 id="deg-chars-blives" className="model-chars-h">B-lives</h3>
          {chooser || <span className="gof-sub">{pct(level)}% band</span>}
        </div>
        {!rows.length && <p className="mf-note">This model gives no reliability curve.</p>}
        {rows.map((b) => (
          <div className="gofr life-row" key={b.label} title={`${b.label}: the time by which ${Math.round(b.p * 100)}% have reached the threshold`}>
            <span className="gk">{b.label === "B50" ? "B50 (median)" : b.label}</span>
            <span className="gv">{b.value != null ? `${formatNumber(b.value)}${u}` : "—"}</span>
            <span className="life-lo">{spanText(b.lower, b.upper, "")}</span>
          </div>
        ))}
        {band.busy && <p className="mf-note">Working…</p>}
        {band.error && <p className="mf-note" role="alert">{band.error}</p>}
        <p className="mf-note">
          B10 is the time by which 10% have reached the threshold (90% still in service). The band's lower end is the
          design life. {!band.can && SIGN_IN}
        </p>
        {onCalc && (
          <button type="button" className="link model-chars-blives" onClick={onCalc}>
            Another reliability: use the Calculator ›
          </button>
        )}
      </section>
    </NumbersSheet>
  );
}

// ---- Diagnostics --------------------------------------------------------------

function ResidualsCheck({ r, name }) {
  const s = scatterCheck(r);
  const units = r.units || [];
  const colour = itemColour(units.length);
  const mUnit = r.measurement_unit ? ` ${r.measurement_unit}` : "";
  const traces = units.map((u, i) => dataPoints({
    x: u.scatter.x, y: u.residuals, name: u.id, marker: { color: colour(i), size: 6 },
    hovertemplate: `<b>%{fullData.name}</b><br>%{x:,}${r.unit ? ` ${unitInText(r.unit)}` : ""}: %{y:+.3~g}${mUnit}<extra></extra>`,
  }));
  const shapes = [referenceShape({ y: 0, line: { dash: "solid" } })];
  if (s?.sigma) {
    shapes.push(referenceShape({ y: 2.5 * s.sigma }), referenceShape({ y: -2.5 * s.sigma }));
  }
  return (
    <CheckCard chart question="Do the readings scatter evenly about each path?" term="residuals"
               tone={s?.tone} verdict={s?.words}
               footer={<p className="muted-line">Each reading less its item's path; dashed: ±2.5 σ. A curve or a funnel says the path shape doesn't suit the readings.</p>}>
      <Plot fill data={traces} download={`${name || "Degradation model"} — residuals`}
            layout={{ ...SMALL, showlegend: false, shapes,
                      xaxis: { title: { text: r.unit ? `Time (${r.unit})` : "Time" } },
                      yaxis: { title: { text: `Reading − path${r.measurement_unit ? ` (${r.measurement_unit})` : ""}` }, zeroline: false } }} />
    </CheckCard>
  );
}

function PathRankingCheck({ r }) {
  const ranking = pathRanking(r);
  if (!ranking) return null;
  return (
    <CheckCard question="Which path shape fits the readings best?" term="AICc ranking" tone={ranking.tone}
               verdict={ranking.words}
               footer={<p className="muted-line">Every shape fitted to every item's readings; lower AICc is better, and the best is used.</p>}>
      <table className="mini-table compare-table">
        <thead><tr><th>Path</th><th>ΔAICc</th><th>Verdict</th></tr></thead>
        <tbody>
          {ranking.rows.map((row) => (
            <tr key={row.id} className={row.current ? "current" : undefined}>
              <td>{row.name}{row.current && <span className="gof-sub"> · used</span>}</td>
              <td>{row.delta === 0 ? "—" : `+${row.delta.toFixed(1)}`}</td>
              <td>{row.verdict === "best" ? "Best" : row.verdictLabel}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CheckCard>
  );
}

function DiagTab({ r, name, modelId }) {
  const induced = useInducedLife(modelId);
  const s = scatterCheck(r);
  const ranking = pathRanking(r);
  const checks = [
    modelId && <InducedLifeCheck key="induced" induced={induced} unit={r.unit} name={name} />,
    s && <ResidualsCheck key="resid" r={r} name={name} />,
  ].filter(Boolean);
  const notes = [
    !ranking && r.path_model?.name && `The ${r.path_model.name.toLowerCase()} path was chosen when fitting, so no other shapes were compared.`,
    !s && "The readings' scatter about each path isn't stored with this model: fit it again to see that check.",
    !modelId && "The induced life needs a copy of this model: sign in to see it.",
  ].filter(Boolean);
  return (
    <ChecksGrid
      className="deg-diag"
      side={
        <>
          {ranking && <PathRankingCheck r={r} />}
          {modelId && <InducedLifeCard induced={induced} unit={r.unit} />}
          {notes.length > 0 && (
            <section className="gof-card mf-flex-none" aria-label="About these checks">
              {notes.map((n) => <p className="mf-note" key={n}>{n}</p>)}
            </section>
          )}
        </>
      }
    >
      {checks.length ? checks : (
        <p className="muted-line">No checks for this model beyond the path comparison.</p>
      )}
    </ChecksGrid>
  );
}

// ---- Data ---------------------------------------------------------------------

function DataTab({ r, datasetId }) {
  const units = r.units || [];
  const u = r.unit ? ` (${unitInText(r.unit)})` : "";
  const never = units.filter((x) => x.censored).length;
  const counts = [
    ["Items", r.n_units ?? units.length],
    never ? ["Not at the threshold yet", never] : null,
    ["Readings", r.n_measurements],
  ].filter((row) => row && row[1] != null);
  const v = Number(r.measurement_var);
  const sigma = Number.isFinite(v) && v >= 0 ? Math.sqrt(v) : null;
  const mUnit = r.measurement_unit ? ` ${r.measurement_unit}` : "";
  const formula = PATH_FORMULAS[r.path_model?.id];
  const chosen = (r.path_selection || []).length > 1 ? "the best of the path shapes by AICc" : "chosen when fitting";
  return (
    <TablePanel
      main={
        <>
          <section className="gof-card mf-flex-none" aria-labelledby="deg-data-counts">
            <div className="gofh mf-card-head">
              <h3 className="mf-card-title" id="deg-data-counts">What it was fitted to</h3>
              {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
            </div>
            {counts.map(([k, n]) => (
              <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{Number(n).toLocaleString("en-US")}</span></div>
            ))}
            {r.unit && <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unitInText(r.unit)}</span></div>}
            {r.measurement_unit && <div className="gofr"><span className="gk">Measurement unit</span><span className="gv">{r.measurement_unit}</span></div>}
          </section>
          <ScrollCard className="deg-crossings" title="Crossing times" sub="when each item's path reaches the threshold: the life model is fitted to these">
            <table className="mini-table">
              <thead><tr><th>Item</th><th className="mf-num">Readings</th><th className="mf-num">Crossing{u}</th></tr></thead>
              <tbody>
                {units.map((x) => (
                  <tr key={x.id}>
                    <td>{x.id}</td>
                    <td className="mf-num">{x.scatter?.x?.length ?? "—"}</td>
                    <td className="mf-num">
                      {x.pseudo_failure_time == null
                        ? "never (censored)"
                        : `${formatNumber(x.pseudo_failure_time, { sig: 4 })}${x.censored ? " (censored)" : ""}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollCard>
        </>
      }
      side={
        <>
          <ScrollCard title="Every parameter" className="deg-params">
            <table className="mini-table">
              <thead><tr><th>Parameter</th><th className="mf-num">Estimate</th></tr></thead>
              <tbody>
                <tr className="deg-part"><th colSpan={2}>Life: {r.life_model?.distribution || "—"}</th></tr>
                {lifeParams(r).map((p) => (
                  <tr key={p.name}><td>{p.label}</td><td className="mf-num">{formatNumber((r.life_model.params.find((q) => q.name === p.name) || {}).value, { sig: 4 })}</td></tr>
                ))}
                <tr className="deg-part"><th colSpan={2}>Path: {r.path_model?.name || "—"}{formula ? ` (y = ${formula})` : ""}, the population's mean</th></tr>
                {pathParams(r).map((p) => (
                  <tr key={p.name}><td>{p.name}</td><td className="mf-num">{formatNumber(p.value, { sig: 4 })}</td></tr>
                ))}
                {sigma != null && (
                  <tr><td>Scatter of the readings (σ{mUnit ? `,${mUnit}` : ""})</td><td className="mf-num">{formatNumber(sigma, { sig: 4 })}</td></tr>
                )}
              </tbody>
            </table>
          </ScrollCard>
          <section className="gof-card mf-flex-none" aria-labelledby="deg-data-how">
            <div className="gofh"><h3 className="mf-card-title" id="deg-data-how">How it was fitted</h3></div>
            <p className="mf-note">
              A {String(r.path_model?.name || "fitted").toLowerCase()} path ({chosen}) for each item, run on to the
              threshold of {thresholdText(r)}. The {r.life_model?.distribution || "life"} model is fitted to the crossing
              times; the population of paths by {POPULATION_METHODS[r.population_method] || r.population_method || "moments"}.
            </p>
          </section>
        </>
      }
    />
  );
}

// ---- The view -------------------------------------------------------------------

// The band at the page's confidence: seeded from the saved curves, fetched
// at another level for a saved model. Shared by the Paths panel, the
// Calculator and Model characteristics.
function useBand(results, modelId) {
  const saved = results?.life_model?.curves || null;
  const [curves, setCurves] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { setCurves(saved); setError(null); }, [results]); // eslint-disable-line react-hooks/exhaustive-deps
  const level = bandLevel(curves);
  const set = async (pctLevel) => {
    if (!modelId) return;
    const conf = pctLevel / 100;
    if (!(conf > 0 && conf < 1)) return;
    setBusy(true);
    setError(null);
    try {
      const c = await degradationReliability(modelId, conf);
      if (c && c.x) setCurves(c);
      else setError("No confidence band for this model.");
    } catch (err) {
      setError(err.message || "Couldn't work out the confidence band.");
    } finally {
      setBusy(false);
    }
  };
  return { curves, level, set, busy, error, can: !!modelId };
}

export default function DegradationResultView({ results, modelId = null, name = null, datasetId = null,
                                                tab: wanted = undefined, onTab = null }) {
  const r = results || {};
  const tabs = degradationTabs(r, { modelId });
  const [own, setOwn] = useState(() => resolveDegradationTab(tabs, wanted));
  const tab = resolveDegradationTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => { setOwn(id); onTab?.(id); };
  const has = (id) => tabs.some((t) => t.id === id);
  const band = useBand(r, modelId);
  // The Calculator's inputs live here, so they survive switching tabs.
  const [relPct, setRelPct] = useState(90);
  const [time, setTime] = useState("");
  const rel = Math.min(Math.max(relPct / 100, 1e-6), 1 - 1e-6);
  const design = band.curves
    ? { life: timeAtReliability(band.curves, rel), relPct, level: band.level, unit: r.unit }
    : null;
  const toCalc = has("calc") ? () => setTab("calc") : null;

  let body = null;
  if (tab === "paths") {
    body = <PathsTab r={r} name={name} design={design} onDiag={has("diag") ? () => setTab("diag") : null} onCalc={toCalc} />;
  } else if (tab === "calc") {
    body = (
      <CalculatorTab r={r} name={name} curves={band.curves} band={band}
                     relPct={relPct} setRelPct={setRelPct} time={time} setTime={setTime} />
    );
  } else if (tab === "chars") {
    body = <CharsTab r={r} curves={band.curves} band={band} onCalc={toCalc} />;
  } else if (tab === "diag") {
    body = <DiagTab r={r} name={name} modelId={modelId} />;
  } else if (tab === "data") {
    body = <DataTab r={r} datasetId={datasetId} />;
  }
  return <ModelTabs tabs={tabs} value={tab} onChange={setTab}>{body}</ModelTabs>;
}
