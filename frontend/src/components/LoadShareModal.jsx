import { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import { listModels } from "../api.js";

// Configure a load-sharing node: pick the load-life model (a saved AFT model
// with the load as its single covariate), the total shared load, the number of
// identical units, and how many must survive (k).
export default function LoadShareModal({ initial, onClose, onSubmit }) {
  const [models, setModels] = useState([]);
  const [modelId, setModelId] = useState(initial?.model?.modelId || "");
  const [load, setLoad] = useState(initial?.load ?? "");
  const [units, setUnits] = useState(initial?.units ?? 2);
  const [k, setK] = useState(initial?.k ?? 1);

  useEffect(() => {
    // Load-sharing units must be covariate (regression) models — the AFT ones.
    listModels()
      .then((r) => setModels((r.models || []).filter((m) => m.kind === "regression")))
      .catch(() => setModels([]));
  }, []);

  const nUnits = Math.max(2, parseInt(units, 10) || 2);
  const kk = Math.max(1, parseInt(k, 10) || 1);
  const loadNum = Number(load);
  const valid = modelId && Number.isFinite(loadNum) && loadNum > 0 && kk <= nUnits;

  const footer = (
    <>
      <span className="hint">The units share the load; survivors carry more and fail faster.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button
          onClick={() => valid && onSubmit({
            model: { source: "saved", modelId }, load: loadNum, units: nUnits, k: kk,
          })}
          disabled={!valid}
        >
          Set load-sharing
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Load-sharing node" onClose={onClose} footer={footer}>
      <div className="dist-field">
        <span className="dist-label">Load-life model</span>
        <Select
          value={modelId}
          onChange={setModelId}
          options={models.map((m) => ({ value: m.id, label: `${m.name} · ${m.distribution}` }))}
          placeholder={models.length ? "Pick a saved model…" : "No saved covariate models"}
        />
      </div>
      <p className="hint" style={{ marginTop: 6 }}>
        Must be an <strong>accelerated-failure-time</strong> model with the{" "}
        <strong>load as its single covariate</strong> (e.g. a Weibull AFT fitted
        against a load column). Fit one under Life data → New model if you don't
        have it yet.
      </p>
      <div className="ls-fields">
        <label className="login-field">
          <span>Total shared load</span>
          <input type="number" min="0" step="any" value={load}
                 onChange={(e) => setLoad(e.target.value)} placeholder="e.g. 3" />
        </label>
        <label className="login-field">
          <span>Number of units</span>
          <input type="number" min="2" step="1" value={units}
                 onChange={(e) => setUnits(e.target.value)} />
        </label>
        <label className="login-field">
          <span>Units required (k)</span>
          <input type="number" min="1" max={nUnits} step="1" value={k}
                 onChange={(e) => setK(e.target.value)} />
        </label>
      </div>
      {kk > nUnits && <p className="hint">k can't exceed the number of units.</p>}
    </Modal>
  );
}
