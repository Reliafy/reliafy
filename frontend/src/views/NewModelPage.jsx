import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ParamsPanel from "../components/ParamsPanel.jsx";
import PerDemandPanel from "../components/PerDemandPanel.jsx";

// Dedicated page for building a new model. First question: fit to data, or
// build from known parameters. Per-demand (Binomial) is reachable from both —
// a parameters option, and a button on the fit-to-data source step.
export default function NewModelPage() {
  const navigate = useNavigate();
  const query = new URLSearchParams(useLocation().search);
  const initialMode = query.get("mode");
  // Guided first-run deep link: ?dataset=<id>&auto=1 jumps straight into the
  // fit flow pre-loaded with a dataset (used by the activation panel).
  const initialDatasetId = query.get("dataset") || null;
  const autoFit = query.get("auto") === "1";
  const [mode, setMode] = useState(
    initialDatasetId ? "data"
    : ["data", "params", "perdemand"].includes(initialMode) ? initialMode : null
  ); // null | "data" | "params" | "perdemand"

  const openModel = (model) => navigate(`/modelling/m/${model.id}`);

  const heading =
    mode === "params" ? "From parameters"
    : mode === "perdemand" ? "Per-demand"
    : mode === "data" ? "Fit to data"
    : "New model";
  const sub =
    mode === "params" ? "Enter known parameters to build the model."
    : mode === "perdemand" ? "Reliability per demand, from a demands/failures count."
    : mode === "data" ? "Pick data, map columns, fit, then review and save."
    : "How do you want to build the model?";

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/life")}>Life data models</button> /{" "}
            <b>New model</b>
          </div>
          <h1>{heading}</h1>
          <p>{sub}</p>
        </div>
      </header>

      {/* First question: choose how to build the model. */}
      {mode === null && (
        <div className="card">
          <div className="ds-choose">
            <button className="ds-choice" onClick={() => setMode("data")}>
              <span className="ds-choice-h">Fit to data</span>
              <span className="ds-choice-b">
                Upload a CSV or pick a dataset — fit a distribution (or PH model)
                with a probability plot and goodness of fit.
              </span>
            </button>
            <button className="ds-choice" onClick={() => setMode("params")}>
              <span className="ds-choice-h">From parameters</span>
              <span className="ds-choice-b">
                Enter known parameters — a handbook or report value, or a
                per-demand count — for the reliability functions and metrics.
              </span>
            </button>
          </div>
        </div>
      )}

      {mode === "data" && (
        <FitFlow
          onSaved={openModel}
          onCancel={() => setMode(null)}
          onPerDemand={() => setMode("perdemand")}
          initialDatasetId={initialDatasetId}
          autoFit={autoFit}
        />
      )}

      {mode === "params" && (
        <ParamsPanel
          onCreated={openModel}
          onCancel={() => setMode(null)}
          onPerDemand={() => setMode("perdemand")}
        />
      )}

      {mode === "perdemand" && (
        <PerDemandPanel onCreated={openModel} onBack={() => setMode(null)} />
      )}
    </div>
  );
}
