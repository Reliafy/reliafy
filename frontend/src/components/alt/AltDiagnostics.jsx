// The Diagnostics tab of an accelerated life model: "can I trust it?" as four
// small checks, each titled with its question: whether the shape is the
// same at every stress, whether the tested levels follow the life model,
// whether another life model fits better and how far the use stress is from
// the tests. The tests come from SurPyval's diagnose() on the server (about
// half a second; nothing resamples); the two charts from each level's own
// fit, which the saved result carries.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "../Plot.jsx";
import { CheckCard, ChecksGrid } from "../model/ModelLayouts.jsx";
import { diagnoseAlt } from "../../api.js";
import { formatNumber } from "../../format.js";
import { ACCENT, BAND_FILL, DATA_INK, INK, SURFACE } from "../../plotTheme.js";
import {
  compareCheck, distanceCheck, distanceWords, levelWords, lifeCheck, shapeCheck, shapeParam,
} from "../../altFrame.js";
import { altPlanLink, altPrefill } from "../../testPlanning.js";
import { unitInText } from "../unitText.js";

const SMALL = { margin: { t: 6, r: 10, b: 44, l: 54 } };
// A tested level as a category on a small chart's axis: one stress a line.
const tick = (stress, stresses) => levelWords(stress, stresses).split(", ").join("<br>");
const SAVE_FIRST = "The test runs once the model is saved.";

// The checks' answers, per model and use stress, kept for the page's life.
const asked = new Map();

function useDiagnostics(modelId, use) {
  const key = modelId ? `${modelId}|${use ? JSON.stringify(use) : ""}` : null;
  const [state, setState] = useState(() => (key && asked.has(key) ? { data: asked.get(key) } : null));
  useEffect(() => {
    if (!key) { setState(null); return undefined; }
    if (asked.has(key)) { setState({ data: asked.get(key) }); return undefined; }
    let live = true;
    setState({ busy: true });
    diagnoseAlt(modelId, use)
      .then((data) => { asked.set(key, data); if (live) setState({ data }); })
      .catch((e) => live && setState({ error: e.message }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state || {};
}

function noOwnFits() {
  return <p className="muted-line">Not stored with this model: fit it again to see each level's own fit.</p>;
}

// Each level's own shape (fitted to that level alone, with its 95% interval)
// against the model's one shape.
function ShapeChart({ results, name }) {
  const r = results;
  const shape = shapeParam(r);
  const rows = (r.levels || []).filter((l) => l.own?.shape?.length);
  if (!shape || !rows.length) return noOwnFits();
  const x = rows.map((l) => tick(l.stress, r.stresses));
  const v = rows.map((l) => l.own.shape[0].value);
  const lo = rows.map((l, i) => (l.own.shape[0].ci ? v[i] - l.own.shape[0].ci[0] : 0));
  const hi = rows.map((l, i) => (l.own.shape[0].ci ? l.own.shape[0].ci[1] - v[i] : 0));
  const traces = [];
  if (Array.isArray(shape.ci)) {
    traces.push({
      type: "scatter", mode: "lines", x: [...x, ...[...x].reverse()],
      y: [...x.map(() => shape.ci[1]), ...x.map(() => shape.ci[0])], fill: "toself", fillcolor: BAND_FILL,
      line: { width: 0 }, hoverinfo: "skip", name: "Model's 95% interval",
    });
  }
  traces.push({
    type: "scatter", mode: "lines", x, y: x.map(() => shape.value), line: { color: ACCENT, width: 2 },
    name: `The model's ${shape.symbol}`, hovertemplate: `model: %{y:.3~g}<extra></extra>`,
  });
  traces.push({
    type: "scatter", mode: "markers", x, y: v, name: "Each level alone",
    marker: { color: INK, size: 8, line: { color: SURFACE, width: 1 } },
    error_y: { type: "data", array: hi, arrayminus: lo, color: DATA_INK, thickness: 1.25, width: 4 },
    hovertemplate: `${shape.symbol} %{y:.3~g}<extra>level alone</extra>`,
  });
  return (
    <Plot fill data={traces} download={`${name || "Model"} — shape at each level`}
          layout={{ ...SMALL, showlegend: false,
                    xaxis: { type: "category", tickangle: 0, tickfont: { size: 11 } },
                    yaxis: { title: { text: shape.label }, rangemode: "tozero" } }} />
  );
}

// Each level's own life (fitted alone, with its 95% interval) against the
// life the model gives that level.
function LifeChart({ results, name }) {
  const r = results;
  const rows = (r.levels || []).filter((l) => l.own && Number.isFinite(l.own.life));
  if (!rows.length) return noOwnFits();
  const unit = r.unit ? ` (${r.unit})` : "";
  const x = rows.map((l) => tick(l.stress, r.stresses));
  const own = rows.map((l) => l.own.life);
  const lo = rows.map((l, i) => (l.own.life_ci ? own[i] - l.own.life_ci[0] : 0));
  const hi = rows.map((l, i) => (l.own.life_ci ? l.own.life_ci[1] - own[i] : 0));
  const log = r.life_stress_plot?.log_y !== false && own.every((v) => v > 0);
  const traces = [
    {
      type: "scatter", mode: "markers", x, y: own, name: "Each level alone",
      marker: { color: INK, size: 8, line: { color: SURFACE, width: 1 } },
      error_y: { type: "data", array: hi, arrayminus: lo, color: DATA_INK, thickness: 1.25, width: 4 },
      hovertemplate: "%{y:,.4~g}<extra>level alone</extra>",
    },
    {
      type: "scatter", mode: "markers", x, y: rows.map((l) => l.characteristic_life), name: "The model",
      marker: { color: ACCENT, size: 10, symbol: "diamond-open", line: { width: 2 } },
      hovertemplate: "%{y:,.4~g}<extra>model</extra>",
    },
  ];
  return (
    <Plot fill data={traces} download={`${name || "Model"} — life at each level`}
          layout={{ ...SMALL, showlegend: false,
                    xaxis: { type: "category", tickangle: 0, tickfont: { size: 11 } },
                    yaxis: { title: { text: `Life${unit}` }, type: log ? "log" : "linear",
                             ...(log ? { dtick: "D2", tickformat: ",~g" } : {}) } }} />
  );
}

// An AIC difference from this model: "−6.8" (better), "+0.2", "0".
function deltaText(d) {
  if (!Number.isFinite(d)) return "—";
  if (Math.abs(d) < 0.05) return "0";
  return `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}`;
}

function CompareTable({ diag, unit }) {
  const rows = diag?.comparison || [];
  const hasUse = rows.some((r) => r.life_at_use != null);
  const u = unit ? unitInText(unit) : "";
  return (
    <table className="mini-table">
      <thead>
        <tr><th>Life model</th><th className="mf-num">ΔAIC</th>{hasUse && <th className="mf-num">Life at use{u ? ` (${u})` : ""}</th>}</tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name} className={r.current ? "current" : undefined}>
            <td>
              {r.name}
              {r.current && <span className="gof-sub"> · this model</span>}
              {!r.current && !r.life_model_id && <span className="gof-sub"> · not offered here</span>}
            </td>
            <td className="mf-num">{r.current ? "—" : deltaText(r.delta)}</td>
            {hasUse && <td className="mf-num">{formatNumber(r.life_at_use)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DistanceTable({ diag }) {
  const rows = diag?.extrapolation || [];
  const hasUse = rows.some((r) => r.use != null);
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th>Stress</th><th className="mf-num">Levels</th><th className="mf-num">Tested</th>
          {hasUse && <th className="mf-num">Use</th>}{hasUse && <th className="mf-num">Beyond</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.stress}>
            <td>{r.label}</td>
            <td className="mf-num">{r.levels ?? "—"}</td>
            <td className="mf-num">{formatNumber(r.low, { sig: 4 })}–{formatNumber(r.high, { sig: 4 })}</td>
            {hasUse && <td className="mf-num">{formatNumber(r.use, { sig: 4 })}</td>}
            {hasUse && <td className="mf-num">{distanceWords(r)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AltDiagnostics({ results, modelId, name, use }) {
  const r = results || {};
  const { data: diag, busy, error } = useDiagnostics(modelId, use);
  const pending = !modelId ? SAVE_FIRST : busy ? "Running the checks…" : error ? `Couldn't run the checks: ${error}` : null;
  const shape = diag ? shapeCheck(diag, r) : r.distribution_id === "exponential" ? shapeCheck(null, r) : null;
  const life = diag && lifeCheck(diag, r);
  const compare = diag && compareCheck(diag);
  const distance = diag && distanceCheck(diag);
  const plan = modelId && altPrefill(r);
  // SurPyval's notes (a level left out of a test, a life model it couldn't
  // fit) go under the check they are about.
  const notes = diag?.notes || [];
  const noteOf = (re) => notes.filter((n) => re.test(n));
  const noteLines = (list) => list.map((n) => <p className="muted-line" key={n}>{n}</p>);
  const stats = (r.gof || []).map((g) => `${g.label} ${formatNumber(g.value, { sig: 5 })}`);
  // Two columns of checks over the whole width: on a laptop screen each
  // question and verdict then takes a line or two, and the charts the rest.
  return (
    <ChecksGrid className="alt-checks">
      <CheckCard chart question="Is the shape the same at every stress?" term="likelihood-ratio test"
                 tone={shape?.tone} verdict={shape?.words || pending}
                 footer={r.distribution_id !== "exponential" && (
                   <>
                     <p className="muted-line">Dots: each level fitted alone, with its 95% interval. Line and band: the model's one shape.</p>
                     {noteLines(noteOf(/common-shape/))}
                   </>
                 )}>
        {r.distribution_id === "exponential" ? null : <ShapeChart results={r} name={name} />}
      </CheckCard>
      <CheckCard chart question="Do the levels follow the life model?" term="lack-of-fit test"
                 tone={life?.tone} verdict={life?.words || pending}
                 footer={(
                   <>
                     <p className="muted-line">Dots: each level's own life, with its 95% interval. Diamonds: the life the model gives it.</p>
                     {noteLines(noteOf(/life-stress test/))}
                   </>
                 )}>
        <LifeChart results={r} name={name} />
      </CheckCard>
      {/* A fit not saved yet (the wizard) has the charts; the other two
          checks ask the saved model. */}
      {modelId && <CheckCard question="Would another life model fit better?" term="AIC ranking"
                 tone={compare?.tone} verdict={compare?.words || pending}
                 footer={(
                   <>
                     {diag && <p className="muted-line">Lower AIC is better; under 2 apart, the data can't tell two models apart.</p>}
                     {stats.length > 0 && (
                       <p className="muted-line alt-fit-stats">
                         This model: {stats.join(" · ")}{r.n != null ? ` · ${Number(r.n).toLocaleString()} observations` : ""}.
                       </p>
                     )}
                     {noteLines(notes.filter((n) => !/common-shape|life-stress test/.test(n)))}
                   </>
                 )}>
        {diag && <CompareTable diag={diag} unit={r.unit} />}
      </CheckCard>}
      {modelId && <CheckCard question="How far is the use stress from the tested stresses?" term="extrapolation"
                 tone={distance?.tone} verdict={distance?.words || pending}
                 footer={plan && (
                   <p className="muted-line">
                     Testing again? <Link to={altPlanLink(modelId)}>Plan the next test from this fit</Link>.
                   </p>
                 )}>
        {diag && <DistanceTable diag={diag} />}
      </CheckCard>}
    </ChecksGrid>
  );
}
