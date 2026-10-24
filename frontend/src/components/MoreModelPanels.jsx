import { useState } from "react";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { PlotCard, PlotPanel } from "./model/ModelLayouts.jsx";
import LifeAside from "./LifeSummary.jsx";
import Plot from "./Plot.jsx";
import { DATA_INK, fitLine } from "../plotTheme.js";
import "./MoreModels.css";

// Royston-Parmar's curve over the data (#179). The semi-parametric and
// shared-frailty regressions' tables and group effect are in the model
// frame's Effects and Data tabs (components/model/).

// Royston-Parmar: the fitted curve over the data's own Kaplan-Meier curve
// (or its hazard rate), beside the non-repairable model's usual panel.
export function FlexibleSurvival({ result, split = null, name = null, modelId = null, onStats = null }) {
  const [view, setView] = useState("sf");
  const c = result.functions?.curves || {};
  const est = result.estimate;
  const traces = [];
  const hazard = view === "hf" && c.hf;
  if (!hazard && est?.x?.length) {
    traces.push({
      type: "scatter", mode: "lines", x: est.x, y: est.R, name: est.label || "Kaplan-Meier",
      line: { shape: "hv", color: DATA_INK, width: 1.25 },
      hovertemplate: `%{x:,.4~g}: R=%{y:.3f} (${est.label || "Kaplan-Meier"})<extra></extra>`,
    });
  }
  traces.push(hazard
    ? fitLine({ x: c.x, y: c.hf, name: "Fitted hazard rate", hovertemplate: "%{x:,.4~g}: h=%{y:.3~g}<extra></extra>" })
    : fitLine({ x: c.x, y: c.sf, name: "Fitted spline", hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra></extra>" }));
  return (
    <PlotPanel
      plot={
        <PlotCard controls={c.hf && (
          <SegmentedControl size="sm" label="Show" value={view} onChange={setView}
                            options={[{ value: "sf", label: "Reliability" }, { value: "hf", label: "Hazard rate" }]} />
        )}>
          <Plot
            fill
            data={traces}
            layout={{
              height: 470,
              xaxis: { title: { text: result.unit ? `Time (${result.unit})` : "Time" }, rangemode: "tozero" },
              yaxis: hazard
                ? { title: { text: "Hazard rate, h(t)" }, rangemode: "tozero" }
                : { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
              showlegend: true,
              legend: { x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.8)" },
            }}
            download={`${name || result.distribution} — ${hazard ? "hazard rate" : "survival curve"}`}
          />
        </PlotCard>
      }
      // The spline's coefficients mean nothing on their own (they're in the
      // Data tab): the panel gives its size, the data and the fit.
      side={
        <LifeAside
          result={{ ...result, params: [], extra_params: [{ name: "Spline terms", value: result.spline?.n_terms ?? 3 }] }}
          split={split} modelId={modelId} onStats={onStats} showUse={false}
        />
      }
    />
  );
}
