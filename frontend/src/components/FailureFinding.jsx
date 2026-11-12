import { useState } from "react";
import { useLocation } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import FfiResult from "./FfiResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { ComputeReason } from "./StrategyTool.jsx";
import { failureFindingMissing, strategyUnit } from "../strategyTools.js";
import { failureFinding } from "../api.js";
import { analysisName, modelFromSearch } from "../modelNext.js";
import PercentField from "./PercentField.jsx";
import StrategyUnit from "./StrategyUnit.jsx";
import { readPercents } from "../percentForms.js";
import { percentApiMessage } from "../percent.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { costLabel } from "../money.js";
import { unitInText } from "./unitText.js";
import { savedInputs } from "../analysisInputs.js";

// Failure-finding interval tool: how often to check a HIDDEN function (e.g. a
// protective device) so its availability stays above the target.
export default function FailureFinding() {
  const [model, setModel] = useState(null);
  const search = useLocation().search;
  // A saved analysis' "Open in Failure finding" brings its target (?target=99.5).
  const [availability, setAvailability] = useState(() => new URLSearchParams(search).get("target") || "99");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ranWith, setRanWith] = useState(null); // the model the result is for
  const [duration, setDuration] = useState("");
  const [testCost, setTestCost] = useState("");
  const [renewed, setRenewed] = useState(true);
  const currency = useCurrency();
  // Opened from a model's "Use this model" (#294): that model, chosen.
  const wanted = modelFromSearch(search);
  // A saved model brings its unit (shown, not copied: a unit carried over
  // from the saved model picked first must not label typed parameters).
  const pickModel = (m) => setModel(m);

  const isRegression = model?.kind === "regression";
  // Typed as a percentage (99), sent as a fraction (0.99); 0.99 is asked
  // about ("Did you mean 99%?"), never taken as 0.99%.
  const pcts = readPercents("failureFinding", { availability });
  const availCheck = pcts.checks.availability;
  // Why Compute is greyed out, said beside it (null when ready).
  const missing = failureFindingMissing({ model, availability, availCheck, unit });
  const canRun = !missing && !isRegression && pcts.ready;

  const num = (v) => (String(v ?? "").trim() === "" ? null : Number(v));
  const current = {
    distribution_id: model?.distribution_id,
    params: model?.params,
    target_availability: pcts.fractions.availability,
    unit: strategyUnit(model, unit),
    extras: model?.extras || null,
    test_duration: num(duration),
    test_cost: num(testCost),
    renewed_at_test: renewed,
  };
  // A result whose inputs have since changed is greyed until Compute.
  const stale = !!inputs && ["target_availability", "unit", "test_duration", "test_cost", "renewed_at_test"]
    .some((k) => inputs[k] !== current[k]) || (!!ranWith && ranWith !== model);
  const u = unitInText(strategyUnit(model, unit) || "");

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = { ...current, ...savedInputs(model) };
      const res = await failureFinding(
        body.distribution_id, body.params, body.target_availability, body.unit, body.extras,
        { test_duration: body.test_duration, test_cost: body.test_cost, renewed_at_test: body.renewed_at_test },
      );
      setResult(res);
      setInputs(body);
      setRanWith(model);
    } catch (err) {
      setError(percentApiMessage(err.message));
      setResult(null);
      setInputs(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="strategy-tool">
      <div className="strategy-form">
        <ModelPicker label="Non-repairable model of the hidden function" value={model} onChange={pickModel} preferSaved wanted={wanted} />
        {isRegression && (
          <p className="hint">Pick a plain distribution — proportional-hazards models aren't supported here.</p>
        )}
        <div className="strategy-costs">
          <PercentField label="Target availability" value={availability} onChange={setAvailability}
            check={availCheck} />
          <StrategyUnit model={model} unit={unit} onUnit={setUnit} />
          <label className="calc-t">
            <span>Each test takes{u ? ` (${u})` : ""}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={duration} placeholder="no time"
                   onChange={(e) => setDuration(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>{costLabel("Cost per test", currency)}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={testCost} placeholder="optional"
                   onChange={(e) => setTestCost(e.target.value)} />
          </label>
          <label className="calc-check">
            <input type="checkbox" checked={renewed} onChange={(e) => setRenewed(e.target.checked)} />
            <span>Each test renews the device (overhauled or replaced)</span>
          </label>
          <button onClick={run} disabled={!canRun || loading}
                  aria-describedby={missing ? "ffi-why" : undefined}>
            {loading ? "Computing…" : "Compute"}
          </button>
          <ComputeReason id="ffi-why" reason={missing} />
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <FfiResult
          result={result}
          stale={stale}
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
