import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import Units from "./Units.jsx";
import { getDistributions, createModelFromParams } from "../api.js";

// Create a model from known parameters — no data. For handbook values,
// values from a report, or a fit done elsewhere. Produces reliability
// functions and life metrics (no probability plot, since there are no
// observations). Complements uploading data.
export default function ParamsModelModal({ onClose, onCreated }) {
  const [dists, setDists] = useState([]);
  const [distribution, setDistribution] = useState("weibull");
  const [values, setValues] = useState({}); // { paramName: string }
  const [extras, setExtras] = useState({}); // { gamma|p|f0: string }
  const [advanced, setAdvanced] = useState(false);
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDistributions()
      .then((d) => setDists(d.distributions.filter((x) => !x.covariates && x.id !== "best")))
      .catch(() => setError("Couldn't load distributions."));
  }, []);

  const selected = dists.find((d) => d.id === distribution);
  const paramNames = useMemo(() => selected?.params || [], [selected]);

  // Reset entered values when the distribution changes.
  useEffect(() => { setValues({}); setExtras({}); }, [distribution]);

  const num = (v) => v !== "" && v !== undefined && !Number.isNaN(Number(v));
  const paramsReady = paramNames.length > 0 && paramNames.every((p) => num(values[p]));
  const canSave = name.trim() && paramsReady && !busy;

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      const params = paramNames.map((p) => ({ name: p, value: Number(values[p]) }));
      const ex = {};
      for (const k of ["gamma", "p", "f0"]) if (num(extras[k])) ex[k] = Number(extras[k]);
      const model = await createModelFromParams(name.trim(), distribution, params, {
        unit,
        extras: Object.keys(ex).length ? ex : null,
      });
      onCreated(model);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Create a model from parameters"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={onSave} disabled={!canSave}>{busy ? "Creating…" : "Create model"}</button>
        </div>
      }
    >
      <p className="muted-line" style={{ marginTop: 0 }}>
        For known parameters — a handbook value, a figure from a report, or a
        fit done elsewhere. You get the reliability functions and life metrics;
        upload data instead if you want a probability plot.
      </p>

      <label className="login-field">
        <span>Model name</span>
        <input type="text" autoFocus value={name} placeholder="e.g. Bearing — MIL-HDBK value"
               onChange={(e) => setName(e.target.value)} />
      </label>

      <div className="dist-field" style={{ marginTop: "0.8rem" }}>
        <span className="dist-label">Distribution</span>
        <Select
          value={distribution}
          onChange={setDistribution}
          options={dists.map((d) => ({ value: d.id, label: d.name }))}
        />
      </div>

      <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap", marginTop: "0.8rem" }}>
        {paramNames.map((p) => (
          <label key={p} className="login-field" style={{ width: 130 }}>
            <span>{p}</span>
            <input type="number" step="any" value={values[p] ?? ""}
                   onChange={(e) => setValues((v) => ({ ...v, [p]: e.target.value }))} />
          </label>
        ))}
      </div>

      <div style={{ marginTop: "0.8rem" }}>
        <Units value={unit} onChange={setUnit} />
      </div>

      <div className="fitopts" style={{ marginTop: "0.8rem" }}>
        <button type="button" className="fitopts-toggle" onClick={() => setAdvanced((a) => !a)}>
          {advanced ? "▾" : "▸"} Advanced (offset / LFP / zero-inflation)
        </button>
        {advanced && (
          <div className="fitopts-body">
            <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
              {selected?.offsetable && (
                <label className="login-field" style={{ width: 150 }}>
                  <span>γ — offset</span>
                  <input type="number" step="any" placeholder="0" value={extras.gamma ?? ""}
                         onChange={(e) => setExtras((x) => ({ ...x, gamma: e.target.value }))} />
                </label>
              )}
              <label className="login-field" style={{ width: 150 }}>
                <span>p — max failing</span>
                <input type="number" step="any" placeholder="1" value={extras.p ?? ""}
                       onChange={(e) => setExtras((x) => ({ ...x, p: e.target.value }))} />
              </label>
              <label className="login-field" style={{ width: 150 }}>
                <span>f₀ — failed at t=0</span>
                <input type="number" step="any" placeholder="0" value={extras.f0 ?? ""}
                       onChange={(e) => setExtras((x) => ({ ...x, f0: e.target.value }))} />
              </label>
            </div>
          </div>
        )}
      </div>

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
