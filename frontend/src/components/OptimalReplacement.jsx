import { useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import ReplacementResult from "./ReplacementResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { ComputeReason } from "./StrategyTool.jsx";
import { replacementMissing } from "../strategyTools.js";
import { optimalReplacement } from "../api.js";
import { analysisName, modelFromSearch } from "../modelNext.js";
import StrategyUnit from "./StrategyUnit.jsx";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { costLabel } from "../money.js";

// Optimal preventive-replacement tool: the age that minimises the long-run
// cost rate given planned vs. unplanned costs.
//
// A link can preset it: ?model=<saved model id>&planned=<cost>&unplanned=<cost>
// (the guided walkthrough opens it on the bearing sample this way; "Use this
// model" passes ?model= alone).
export default function OptimalReplacement() {
  const [params] = useSearchParams();
  const [model, setModel] = useState(null);
  const [cp, setCp] = useState(() => params.get("planned") || "");
  const [cu, setCu] = useState(() => params.get("unplanned") || "");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null); // what produced the result
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ranWith, setRanWith] = useState(null); // the model the result is for
  const currency = useCurrency();
  // Opened from a model's "Use this model" (#294): that model, chosen.
  const wanted = modelFromSearch(useLocation().search);
  // A saved model brings its unit.
  const pickModel = (m) => {
    setModel(m);
    if (m?.unit) setUnit(m.unit);
  };

  const isRegression = model?.kind === "regression";
  // Why Compute is greyed out, said beside it (null when ready).
  const missing = replacementMissing({ model, planned: cp, unplanned: cu });
  const canRun = !missing;

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = {
        distribution_id: model.distribution_id,
        params: model.params,
        planned_cost: Number(cp),
        unplanned_cost: Number(cu),
        unit: model.unit || unit.trim() || null,
        extras: model.extras || null,
      };
      const res = await optimalReplacement(
        body.distribution_id, body.params, body.planned_cost, body.unplanned_cost, body.unit, body.extras
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
        <ModelPicker key={wanted || ""} label="Non-repairable model" value={model} onChange={pickModel} preferSaved wanted={wanted}
                     wt="repl-model" />
        {isRegression && (
          <p className="hint">
            Pick a plain distribution — proportional-hazards models aren't
            supported here.
          </p>
        )}
        <div className="strategy-costs" data-wt="repl-costs">
          <label className="calc-t">
            <span>{costLabel("Planned replacement cost", currency)}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={cp}
              onChange={(e) => setCp(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>{costLabel("Unplanned (failure) cost", currency)}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={cu}
              onChange={(e) => setCu(e.target.value)} />
          </label>
          <StrategyUnit model={model} unit={unit} onUnit={setUnit} />
          <button data-wt="repl-run" onClick={run} disabled={!canRun || loading}
                  aria-describedby={missing ? "repl-why" : undefined}>
            {loading ? "Computing…" : "Compute"}
          </button>
          <ComputeReason id="repl-why" reason={missing} />
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <ReplacementResult
          result={result}
          wt="repl-result"
          actions={inputs && (
            <SaveAnalysisButton
              kind="optimal_replacement"
              inputs={inputs}
              defaultName={analysisName("Replacement", ranWith, result.distribution)}
            />
          )}
        />
      )}
    </div>
  );
}
