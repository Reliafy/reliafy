import { useState } from "react";
import Select from "./Select.jsx";
import { createRecurrentFromParams } from "../api.js";

// Build a simple recurrent (repairable-system) model from known parameters —
// no data. For reliability-growth planning and repair-vs-replace decisions
// (e.g. the optimal number of repairs before replacement). Only the models that
// SurPyval can construct from parameters are offered.
const MODELS = [
  { value: "crow_amsaa", label: "Crow-AMSAA (NHPP)" },
  { value: "duane", label: "Duane" },
];
const MODEL_DESC = {
  crow_amsaa: "NHPP power law: MCF(t) = (t/α)^β. β < 1 improving, β > 1 deteriorating.",
  duane: "Duane growth model — a cumulative-MTBF power law.",
};

export default function RecurrentParamsPanel({ onCreated, onBack }) {
  const [model, setModel] = useState("crow_amsaa");
  const [alpha, setAlpha] = useState("");
  const [beta, setBeta] = useState("");
  const [horizon, setHorizon] = useState("");
  const [unit, setUnit] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const na = Number(alpha), nb = Number(beta), nh = Number(horizon);
  const ok = (s, v) => s !== "" && !Number.isNaN(v) && v > 0;
  const valid = name.trim() && ok(alpha, na) && ok(beta, nb) && ok(horizon, nh) && !busy;
  const growth = ok(beta, nb)
    ? (nb < 0.95 ? "improving — failures slowing" : nb > 1.05 ? "deteriorating — failures accelerating" : "stable — roughly constant rate")
    : null;

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await createRecurrentFromParams(name.trim(), model, { alpha: na, beta: nb, horizon: nh, unit }));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Build a simple repairable-system model from known parameters — no data. Use it for
        reliability-growth planning and repair-vs-replace decisions, like the optimal number of
        repairs before replacement.
      </p>

      <label className="login-field">
        <span>Model name</span>
        <input type="text" autoFocus value={name} placeholder="e.g. Fleet growth target"
               onChange={(e) => setName(e.target.value)} />
      </label>

      <div className="row" style={{ gap: "0.7rem", flexWrap: "wrap", marginTop: "0.8rem", alignItems: "flex-end" }}>
        <label className="dist-field" style={{ width: 200 }}>
          <span className="dist-label">Model</span>
          <Select value={model} onChange={setModel} options={MODELS} />
        </label>
        <label className="login-field" style={{ width: 120 }}>
          <span>α (alpha)</span>
          <input type="number" step="any" value={alpha} placeholder="scale" onChange={(e) => setAlpha(e.target.value)} />
        </label>
        <label className="login-field" style={{ width: 120 }}>
          <span>β (beta)</span>
          <input type="number" step="any" value={beta} placeholder="shape" onChange={(e) => setBeta(e.target.value)} />
        </label>
        <label className="login-field" style={{ width: 150 }}>
          <span>Horizon (max time)</span>
          <input type="number" step="any" value={horizon} placeholder="e.g. 5000" onChange={(e) => setHorizon(e.target.value)} />
        </label>
        <label className="login-field" style={{ width: 120 }}>
          <span>Time unit</span>
          <input type="text" value={unit} placeholder="e.g. hours" onChange={(e) => setUnit(e.target.value)} />
        </label>
      </div>

      {MODEL_DESC[model] && <p className="muted-line" style={{ margin: "0.6rem 0 0" }}>{MODEL_DESC[model]}</p>}
      {growth && <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>β = {nb} → <b>{growth}</b>.</p>}
      {error && <div className="error">{error}</div>}

      <div className="fit-flow-foot">
        <span />
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={onBack} disabled={busy}>Back</button>
          <button onClick={onSave} disabled={!valid}>{busy ? "Saving…" : "Save model"}</button>
        </div>
      </div>
    </div>
  );
}
