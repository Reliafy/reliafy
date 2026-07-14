import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ParamsPanel from "../components/ParamsPanel.jsx";
import ResultView from "../components/ResultView.jsx";
import { saveModel } from "../api.js";

// Dedicated page for building a new model. First question: fit to data, or
// build from known parameters. The data path then runs the fit flow and a
// review/save step; the parameters path creates the model directly.
export default function NewModelPage() {
  const navigate = useNavigate();
  const initialMode = new URLSearchParams(useLocation().search).get("mode");
  const [mode, setMode] = useState(
    initialMode === "data" || initialMode === "params" ? initialMode : null
  ); // null | "data" | "params"
  const [pending, setPending] = useState(null); // { result, fit } — data path
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const onFitted = ({ result, fit }) => {
    setPending({ result, fit });
    const source = fit.file?.name || fit.sourceName || "dataset";
    setName(`${result.distribution} — ${source.replace(/\.csv$/i, "")}`);
    setError(null);
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const { fit } = pending;
      const saved = await saveModel(name.trim(), fit.distribution, fit.file, fit.mapping, {
        covariates: fit.covariates,
        formula: fit.formula,
        unit: fit.unit,
        datasetId: fit.datasetId,
        fitOptions: fit.fitOptions,
      });
      navigate(`/modelling/m/${saved.id}`);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  const heading = pending
    ? "Review & save"
    : mode === "params"
    ? "From parameters"
    : mode === "data"
    ? "Fit to data"
    : "New model";
  const sub = pending
    ? "Check the fit, give it a name, and save — or discard to try again."
    : mode === "params"
    ? "Enter known parameters to build the model."
    : mode === "data"
    ? "Upload a CSV or pick a dataset, then map columns and fit."
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

      {mode === "data" && !pending && (
        <FitFlow onFitted={onFitted} onCancel={() => setMode(null)} />
      )}

      {mode === "data" && pending && (
        <div className="card">
          <div className="save-bar">
            <input
              className="save-name"
              type="text"
              value={name}
              placeholder="Model name"
              onChange={(e) => setName(e.target.value)}
            />
            <button onClick={onSave} disabled={saving || !name.trim()}>
              {saving ? "Saving…" : "Save model"}
            </button>
            <button className="secondary" onClick={() => setPending(null)} disabled={saving}>
              Discard
            </button>
          </div>
          {error && <div className="error">{error}</div>}
          <ResultView result={pending.result} />
        </div>
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
