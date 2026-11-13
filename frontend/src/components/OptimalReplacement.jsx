import { useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import ReplacementResult from "./ReplacementResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { ComputeReason } from "./StrategyTool.jsx";
import { replacementMissing, strategyUnit } from "../strategyTools.js";
import { optimalReplacement } from "../api.js";
import { analysisName, modelFromSearch } from "../modelNext.js";
import StrategyUnit from "./StrategyUnit.jsx";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { costLabel } from "../money.js";
import { savedInputs } from "../analysisInputs.js";

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
  // Optional: the use a unit runs a year, and how many units, for the saving a year.
  const [useYear, setUseYear] = useState(() => params.get("use") || "");
  const [units, setUnits] = useState(() => params.get("units") || "");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null); // what produced the result
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ranWith, setRanWith] = useState(null); // the model the result is for
  const [source, setSource] = useState("saved"); // what the model picker shows
  const currency = useCurrency();
  // Opened from a model's "Use this model" (#294): that model, chosen.
  const wanted = modelFromSearch(useLocation().search);
  // A saved model brings its unit (shown, not copied: a unit carried over
  // from the saved model picked first must not label typed parameters).
  const pickModel = (m) => setModel(m);

  const isRegression = model?.kind === "regression";
  // Why Compute is greyed out, said beside it (null when ready).
  const missing = replacementMissing({ model, planned: cp, unplanned: cu, unit, source });
  const canRun = !missing;
  // A result whose inputs have since changed says so until Compute (as Failure finding does).
  const numOrNull = (v) => (String(v ?? "").trim() === "" ? null : Number(v));
  const stale = !!inputs && (ranWith !== model || inputs.planned_cost !== Number(cp)
    || inputs.unplanned_cost !== Number(cu) || inputs.unit !== strategyUnit(model, unit)
    || inputs.use_per_year !== numOrNull(useYear) || inputs.units !== numOrNull(units));

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const num = (v) => (String(v ?? "").trim() === "" ? null : Number(v));
      const body = {
        distribution_id: model.distribution_id,
        params: model.params,
        planned_cost: Number(cp),
        unplanned_cost: Number(cu),
        unit: strategyUnit(model, unit),
        extras: model.extras || null,
        use_per_year: num(useYear),
        units: num(units),
        ...savedInputs(model),
      };
      const res = await optimalReplacement(
        body.distribution_id, body.params, body.planned_cost, body.unplanned_cost, body.unit, body.extras,
        { use_per_year: body.use_per_year, units: body.units },
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
                     onSource={setSource} wt="repl-model" />
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
          <label className="calc-t">
            <span>Use a year, per unit{strategyUnit(model, unit) ? ` (${unitInText(strategyUnit(model, unit))})` : ""}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={useYear} placeholder="optional"
              onChange={(e) => setUseYear(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Units in the fleet</span>
            <input type="number" inputMode="numeric" min="0" step="1" value={units} placeholder="optional"
              onChange={(e) => setUnits(e.target.value)} />
          </label>
          <button data-wt="repl-run" onClick={run} disabled={!canRun || loading}
                  aria-describedby={missing ? "repl-why" : undefined}>
            {loading ? "Computing…" : "Compute"}
          </button>
          <ComputeReason id="repl-why" reason={missing} />
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && stale && (
        <p className="hint" role="status">The inputs changed: Compute to update the answer below.</p>
      )}
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
