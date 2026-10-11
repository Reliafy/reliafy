import { useState } from "react";
import { useLocation } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import FfiResult from "./FfiResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { failureFinding } from "../api.js";
import { analysisName, modelFromSearch } from "../modelNext.js";

// Failure-finding interval tool: how often to check a HIDDEN function (e.g. a
// protective device) so its availability stays above the target.
export default function FailureFinding() {
  const [model, setModel] = useState(null);
  const [availability, setAvailability] = useState("99");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ranWith, setRanWith] = useState(null); // the model the result is for
  // Opened from a model's "Use this model" (#294): that model, chosen.
  const wanted = modelFromSearch(useLocation().search);
  // A saved model brings its unit.
  const pickModel = (m) => {
    setModel(m);
    if (m?.unit) setUnit(m.unit);
  };

  const isRegression = model?.kind === "regression";
  const canRun =
    model && model.distribution_id && !isRegression && availability !== "";

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = {
        distribution_id: model.distribution_id,
        params: model.params,
        target_availability: Number(availability) / 100,
        unit: unit || model.unit || null,
        extras: model.extras || null,
      };
      const res = await failureFinding(
        body.distribution_id, body.params, body.target_availability, body.unit, body.extras
      );
      setResult(res);
      setInputs(body);
      setRanWith(model);
    } catch (err) {
      setError(err.message);
      setResult(null);
      setInputs(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="strategy-tool">
      <div className="strategy-form">
        <ModelPicker label="Life model of the hidden function" value={model} onChange={pickModel} preferSaved wanted={wanted} />
        {isRegression && (
          <p className="hint">Pick a plain distribution — proportional-hazards models aren't supported here.</p>
        )}
        <div className="strategy-costs">
          <label className="calc-t">
            <span>Target availability (%)</span>
            <input type="number" inputMode="decimal" min="1" max="99.999" step="any" value={availability}
              onChange={(e) => setAvailability(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Unit (optional)</span>
            <input type="text" placeholder="e.g. Hours" value={unit}
              onChange={(e) => setUnit(e.target.value)} />
          </label>
          <button onClick={run} disabled={!canRun || loading}>
            {loading ? "Computing…" : "Compute"}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <FfiResult
          result={result}
          actions={inputs && (
            <SaveAnalysisButton
              kind="failure_finding"
              inputs={inputs}
              defaultName={analysisName("Failure finding", ranWith, result.distribution)}
            />
          )}
        />
      )}
    </div>
  );
}
