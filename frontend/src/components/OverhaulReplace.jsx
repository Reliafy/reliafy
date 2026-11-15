import "./OverhaulReplace.css";
import { useEffect, useMemo, useState } from "react";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import OverhaulReplaceResult from "./OverhaulReplaceResult.jsx";
import { ComputeReason } from "./StrategyTool.jsx";
import { repairableRef } from "./ModelPicker.jsx";
import { getRecurrentModel, listRecurrentModels, overhaulReplace } from "../api.js";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { costLabel } from "../money.js";
import {
  TYPED_FORMS, modelUnit, overhaulReplaceBody, overhaulReplaceInputs, overhaulReplaceMissing, usableRepairable,
} from "../overhaulReplace.js";

// Overhaul every X, replace after N overhauls: the one tool for it, on Strategy › Overhaul and
// replace, a repairable model's Plan ahead tab and the Explorer's table pane (a model's Strategy).
//
//   modelId     a saved repairable model, chosen (the model's own page, the Explorer)
//   lockModel   that model only: no picker (the model's page and the Explorer)
//   presets     starting figures {cost_repair, cost_overhaul, cost_replace, overhaul_restores, ...}
//   extraInputs kept with a saved analysis (the Explorer: the position's model row)
//   onSaved     after Save (the Explorer shows the model's Strategy item)
export default function OverhaulReplace({ modelId = null, lockModel = false, presets = {}, extraInputs = null,
  defaultName = null, compact = false }) {
  const currency = useCurrency();
  const [source, setSource] = useState("saved");
  const [saved, setSaved] = useState(null); // the list of usable saved models
  const [savedId, setSavedId] = useState(modelId || "");
  const [model, setModel] = useState(null);
  const [modelError, setModelError] = useState(null);
  const [form, setForm] = useState("crow_amsaa");
  const [alpha, setAlpha] = useState("");
  const [beta, setBeta] = useState("");
  const [unit, setUnit] = useState("");
  const [f, setF] = useState(() => ({ ...Object.fromEntries(Object.entries(presets || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => [k, String(v)])) }));
  const [result, setResult] = useState(null);
  const [ran, setRan] = useState(null); // the inputs the result is for
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));

  useEffect(() => {
    if (lockModel) return undefined;
    let live = true;
    listRecurrentModels().then((d) => live && setSaved((d.models || []).filter(usableRepairable)))
      .catch(() => live && setSaved([]));
    return () => { live = false; };
  }, [lockModel]);
  // With no saved repairable models, the parameters.
  useEffect(() => { if (saved && !saved.length && !modelId) setSource("params"); }, [saved, modelId]);

  // The saved model chosen, read in full (its form and parameters, kept with a saved analysis).
  useEffect(() => {
    if (source !== "saved" || !savedId) { if (source === "saved") setModel(null); return undefined; }
    let live = true;
    setModelError(null);
    getRecurrentModel(savedId).then((doc) => {
      if (!live) return;
      const fam = doc.results?.family || "nhpp";
      if (fam !== "nhpp") {
        setModel(null);
        setModelError("This is an imperfect-repair or covariate model: overhaul and replace needs a minimal-repair "
          + "model (Crow-AMSAA, Duane, HPP or Cox-Lewis), whose failures can be worked out from any age.");
        return;
      }
      setModel(repairableRef(doc));
    }).catch((e) => live && (setModel(null), setModelError(e.message)));
    return () => { live = false; };
  }, [source, savedId]);

  const typed = useMemo(() => (source === "params"
    ? { source: "params", form, params: [alpha, beta], unit: "" } : null), [source, form, alpha, beta]);
  const chosen = source === "params" ? typed : model;
  const missing = overhaulReplaceMissing({ model: chosen, f, unit });
  const inputsNow = chosen && !missing ? JSON.stringify(overhaulReplaceBody(chosen, f, unit)) : null;
  const stale = !!result && inputsNow !== ran;
  const ut = unitInText(modelUnit(chosen, unit) || "");

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = overhaulReplaceBody(chosen, f, unit);
      setResult(await overhaulReplace(body));
      setRan(JSON.stringify(body));
    } catch (e) {
      setError(e.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const money = (k, label, hint) => (
    <label className="calc-t">
      <span>{costLabel(label, currency)}</span>
      <input type="number" inputMode="decimal" min="0" step="any" value={f[k] ?? ""} onChange={set(k)} placeholder={hint} />
    </label>
  );
  const hours = (k, label) => (
    <label className="calc-t">
      <span>{label}</span>
      <input type="number" inputMode="decimal" min="0" step="any" value={f[k] ?? ""} onChange={set(k)} placeholder="optional" />
    </label>
  );

  return (
    <div className={"strategy-tool overhaul-replace" + (compact ? " is-compact" : "")}>
      <div className="strategy-form">
        {!lockModel && (
          <SegmentedControl size="sm" label="Repairable model" value={source} onChange={setSource}
            options={[{ value: "saved", label: "Saved model" }, { value: "params", label: "Parameters" }]} />
        )}
        {!lockModel && source === "saved" && (
          <label className="calc-t or-model">
            <span>Repairable model (minimal repair)</span>
            <Select value={savedId} onChange={setSavedId} searchable ariaLabel="Repairable model"
              placeholder={saved && !saved.length ? "No saved repairable models yet" : "— choose —"}
              options={(saved || []).map((m) => ({ value: m.id, label: m.name, hint: [m.model, m.unit].filter(Boolean).join(" · ") }))} />
          </label>
        )}
        {lockModel && model && (
          <p className="hint or-model-fixed">Model: <b>{model.name}</b>{model.unit ? ` · ${unitInText(model.unit)}` : ""}</p>
        )}
        {modelError && <p className="hint" role="note">! {modelError}</p>}
        {source === "params" && !lockModel && (
          <div className="strategy-costs">
            <label className="calc-t">
              <span>Form</span>
              <Select value={form} onChange={setForm} ariaLabel="Model form" options={TYPED_FORMS} />
            </label>
            <label className="calc-t">
              <span>Scale alpha</span>
              <input type="number" inputMode="decimal" min="0" step="any" value={alpha} onChange={(e) => setAlpha(e.target.value)} />
            </label>
            <label className="calc-t">
              <span>Shape beta</span>
              <input type="number" inputMode="decimal" min="0" step="any" value={beta} onChange={(e) => setBeta(e.target.value)} />
            </label>
            <label className="calc-t">
              <span>Unit of the model's times</span>
              <input type="text" placeholder="e.g. flight hours" value={unit} onChange={(e) => setUnit(e.target.value)} />
            </label>
          </div>
        )}
        <div className="strategy-costs">
          {money("cost_repair", "Repair cost, per failure")}
          {money("cost_overhaul", "Overhaul cost")}
          {money("cost_replace", "Replacement cost")}
          <label className="calc-t">
            <span>An overhaul takes off (% of its age)</span>
            <input type="number" inputMode="decimal" min="0" max="100" step="any" value={f.overhaul_restores ?? ""}
              onChange={set("overhaul_restores")} aria-describedby="or-restores-help" />
          </label>
          <label className="calc-t">
            <span>Most overhauls to search</span>
            <input type="number" inputMode="numeric" min="1" max="60" step="1" value={f.max_overhauls ?? ""}
              onChange={set("max_overhauls")} placeholder="19" />
          </label>
        </div>
        <p className="field-help" id="or-restores-help">100% makes it as good as new; 50% takes off half its age. Ask whoever does the overhaul.</p>
        <details className="or-downtime">
          <summary>Downtime (optional)</summary>
          <div className="strategy-costs">
            {hours("downtime_repair", "Hours down per repair")}
            {hours("downtime_overhaul", "Hours down per overhaul")}
            {hours("downtime_replace", "Hours down per replacement")}
            {money("downtime_cost", "Cost of an hour down", "optional")}
          </div>
          <p className="field-help">Downtime is added to each event's cost. The model's clock{ut ? ` (${ut})` : ""} stops while the unit is down.</p>
        </details>
        <div className="strategy-costs">
          <button onClick={run} disabled={!!missing || loading} aria-describedby={missing ? "or-why" : undefined}>
            {loading ? "Computing…" : "Compute"}
          </button>
          <ComputeReason id="or-why" reason={missing} />
        </div>
      </div>

      {error && <div className="error" role="alert">{error}</div>}
      {result && stale && <p className="hint" role="status">The inputs changed: Compute to update the answer below.</p>}
      {result && (
        <OverhaulReplaceResult
          result={result}
          name={chosen?.name}
          compact={compact}
          actions={ran && chosen && (
            <SaveAnalysisButton
              kind="overhaul_replace"
              inputs={overhaulReplaceInputs(chosen, f, unit, extraInputs || {})}
              defaultName={defaultName || `Overhaul and replace${chosen.name ? ` · ${chosen.name}` : ""}`}
            />
          )}
        />
      )}
    </div>
  );
}
