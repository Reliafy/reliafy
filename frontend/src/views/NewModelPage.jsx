import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ParamsPanel from "../components/ParamsPanel.jsx";

// Dedicated page for building a new model. First question: fit to data, or
// build from known parameters. Each path (FitFlow / ParamsPanel) owns its own
// steps, review and save.
export default function NewModelPage() {
  const navigate = useNavigate();
  const initialMode = new URLSearchParams(useLocation().search).get("mode");
  const [mode, setMode] = useState(
    initialMode === "data" || initialMode === "params" ? initialMode : null
  ); // null | "data" | "params"

  const heading = mode === "params" ? "From parameters" : mode === "data" ? "Fit to data" : "New model";
  const sub =
    mode === "params"
      ? "Enter known parameters to build the model."
      : mode === "data"
      ? "Pick data, map columns, fit, then review and save."
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
                Enter known parameters — a handbook or report value — for the
                reliability functions and life metrics. No data needed.
              </span>
            </button>
          </div>
        </div>
      )}

      {mode === "data" && (
        <FitFlow
          onSaved={(model) => navigate(`/modelling/m/${model.id}`)}
          onCancel={() => setMode(null)}
        />
      )}

      {mode === "params" && (
        <ParamsPanel
          onCreated={(model) => navigate(`/modelling/m/${model.id}`)}
          onCancel={() => setMode(null)}
        />
      )}
    </div>
  );
}
