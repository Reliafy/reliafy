import { useState } from "react";
import { useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ResultView from "../components/ResultView.jsx";
import { saveModel } from "../api.js";

// Dedicated page for fitting a new model: the fit flow, then review + save —
// on its own route so the Models-list entry buttons aren't in the way.
export default function NewModelPage() {
  const navigate = useNavigate();
  const [pending, setPending] = useState(null); // { result, fit }
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

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/models")}>Models</button> /{" "}
            <b>New model</b>
          </div>
          <h1>{pending ? "Review & save" : "New model"}</h1>
          <p>
            {pending
              ? "Check the fit, give it a name, and save — or discard to try again."
              : "Fit a life distribution or proportional-hazards model to your data."}
          </p>
        </div>
      </header>

      {pending ? (
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
      ) : (
        <FitFlow onFitted={onFitted} onCancel={() => navigate("/modelling/models")} />
      )}
    </div>
  );
}
