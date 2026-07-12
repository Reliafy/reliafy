import { useState } from "react";
import ModelPicker from "./ModelPicker.jsx";
import ReplacementResult from "./ReplacementResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { optimalReplacement } from "../api.js";

// Optimal preventive-replacement tool: the age that minimises the long-run
// cost rate given planned vs. unplanned costs.
export default function OptimalReplacement() {
  const [model, setModel] = useState(null);
  const [cp, setCp] = useState("");
  const [cu, setCu] = useState("");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null); // what produced the result
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const isRegression = model?.kind === "regression";
  const canRun =
    model && model.distribution_id && !isRegression && cp !== "" && cu !== "";

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = {
        distribution_id: model.distribution_id,
        params: model.params,
        planned_cost: Number(cp),
        unplanned_cost: Number(cu),
        unit: unit || model.unit || null,
        extras: model.extras || null,
      };
      const res = await optimalReplacement(
        body.distribution_id, body.params, body.planned_cost, body.unplanned_cost, body.unit, body.extras
      );
      setResult(res);
      setInputs(body);
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
        <ModelPicker label="Life model" value={model} onChange={setModel} />
        {isRegression && (
          <p className="hint">
            Pick a plain distribution — proportional-hazards models aren't
            supported here.
          </p>
        )}
        <div className="strategy-costs">
          <label className="calc-t">
            <span>Planned replacement cost</span>
            <input type="number" min="0" step="any" value={cp}
              onChange={(e) => setCp(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Unplanned (failure) cost</span>
            <input type="number" min="0" step="any" value={cu}
              onChange={(e) => setCu(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Unit (optional)</span>
            <input type="text" placeholder="e.g. Hours" value={unit}
              onChange={(e) => setUnit(e.target.value)} />
          </label>
          <button onClick={run} disabled={!canRun || loading}>
            {loading ? "Computing…" : "Compute"}
          </button>
          {result && inputs && (
            <SaveAnalysisButton
              kind="optimal_replacement"
              inputs={inputs}
              defaultName={`Replacement — ${result.distribution}`}
            />
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && <ReplacementResult result={result} />}
    </div>
  );
}
