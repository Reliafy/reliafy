import { useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, GRID, SURFACE } from "../plotTheme.js";
import AltCalculator, { initAltCalc } from "./AltCalculator.jsx";
import NoMaximumNotice from "./NoMaximumNotice.jsx";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { PlotCard, PlotPanel } from "./model/ModelLayouts.jsx";
import AltLifeStress from "./alt/AltLifeStress.jsx";
import AltDiagnostics from "./alt/AltDiagnostics.jsx";
import AltData from "./alt/AltData.jsx";
import { altTabs, defaultUse, parseUse, resolveAltTab, shapeParam } from "../altFrame.js";
import { formatNumber } from "../format.js";
import "./alt/AltFrame.css";

// A fitted accelerated life model in the model frame's tabs:
//   Life-stress       life against stress, to the use stress (two charts for
//                     two stresses), with the life there, the shape and the
//                     acceleration factor against each tested level
//   Probability plot  each tested level on probability paper
//   Calculator        the model at a use stress (a saved model only)
//   Diagnostics       can I trust it: the shape, the life model, the other
//                     life models, the distance to the use stress
//   Data              each level, how it was fitted, every parameter
// The page around it gives the header (ModelFrame). The use stress is one
// for the whole page: Life-stress, the Calculator and Diagnostics share it.
// ``tab`` / ``onTab``: the open tab (a page keeps it in its address).
export default function AltResultView({ results, modelId = null, name = null, datasetId = null,
                                        tab: wanted = undefined, onTab = null }) {
  const r = results || {};
  const tabs = altTabs(r, { saved: !!modelId });
  const [own, setOwn] = useState(() => resolveAltTab(tabs, wanted));
  const tab = resolveAltTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => { setOwn(id); onTab?.(id); };

  // The use stress (as typed), and whether it is still the default.
  const [use, setUseRaw] = useState(() => defaultUse(r).map(String));
  const [edited, setEdited] = useState(false);
  const setUse = (next) => { setUseRaw(next); setEdited(true); };
  const [calc, setCalc] = useState(() => initAltCalc(r));
  const [prev, setPrev] = useState(r);
  if (r !== prev) {
    // Another fit in place (the wizard): start again from its defaults.
    setPrev(r);
    setUseRaw(defaultUse(r).map(String));
    setEdited(false);
    setCalc(initAltCalc(r));
  }

  let body = null;
  if (tab === "life") {
    body = <AltLifeStress results={r} modelId={modelId} name={name} use={use} onUse={setUse} edited={edited} />;
  } else if (tab === "prob") {
    body = <ProbabilityTab results={r} name={name} />;
  } else if (tab === "calc") {
    body = <AltCalculator modelId={modelId} results={r} use={use} onUse={setUse} state={calc} setState={setCalc} />;
  } else if (tab === "diag") {
    body = <AltDiagnostics results={r} modelId={modelId} name={name} use={edited ? parseUse(use) : null} />;
  } else if (tab === "data") {
    body = <AltData results={r} datasetId={datasetId} />;
  }

  const notices = [
    ...(r.unit_warnings || []).map((w) => <div className="detail-note warn" key={w}>⚠ {w}</div>),
    r.no_finite_maximum && <NoMaximumNotice key="nfm" notice={r.no_finite_maximum} style={{ margin: 0 }} />,
  ].filter(Boolean);
  return (
    <ModelTabs
      tabs={tabs}
      value={tab}
      onChange={setTab}
      before={notices.length > 0 && <div className="mf-before alt-notices">{notices}</div>}
    >
      {body}
    </ModelTabs>
  );
}

// Each tested level on the distribution's probability paper: its failures
// (points) and the model's line for it. Parallel lines: one shape.
function ProbabilityTab({ results, name }) {
  const r = results;
  const prob = r.probability_plot || {};
  const traces = [];
  (prob.series || []).forEach((s, i) => {
    const color = COLORWAY[i % COLORWAY.length];
    if (s.line) {
      traces.push({
        x: s.line.x, y: s.line.y, mode: "lines", type: "scatter",
        line: { color, width: 2 }, name: s.label, legendgroup: `p${i}`, hoverinfo: "skip",
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
    margin: { t: 8, r: 12, b: 44, l: 58 },
    xaxis: {
      title: { text: r.unit ? `Time (${r.unit})` : "Time" },
      tickvals: prob.x_ticks?.vals, ticktext: prob.x_ticks?.labels,
      showgrid: true, gridcolor: GRID,
    },
    yaxis: {
      title: { text: "Unreliability, F(t)" },
      tickvals: prob.y_ticks?.vals, ticktext: prob.y_ticks?.labels,
    },
    showlegend: true,
    legend: { x: 0, xanchor: "left", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" },
  };
  const shape = shapeParam(r);
  return (
    <PlotPanel
      plot={<PlotCard><Plot fill data={traces} layout={layout} download={`${name || "Model"} — probability plot`} /></PlotCard>}
      side={(
        <section className="gof-card mf-flex-none" aria-labelledby="alt-prob-h">
          <div className="gofh life-card-head"><h3 className="mf-card-title" id="alt-prob-h">Reading it</h3></div>
          <p className="mf-note">
            Each colour is a tested level on {prob.distribution || r.distribution} paper: the points are its failures,
            the line the model's fit for it.
          </p>
          <p className="mf-note">
            <b>Parallel lines</b> mean one shape at every stress. <b>Points along their line</b> mean the
            distribution fits. Diagnostics tests both.
          </p>
          {shape && (
            <div className="gofr">
              <span className="gk">{shape.label}</span>
              <span className="gv">{formatNumber(shape.value)}</span>
            </div>
          )}
        </section>
      )}
    />
  );
}
