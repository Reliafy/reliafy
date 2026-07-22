import { useState } from "react";
import { createPerDemandModel } from "../api.js";

// Per-demand (Binomial) reliability from a demands/failures count — for
// one-shot and protective equipment where "reliability" is per demand, not
// over time. Rendered as a page panel; calls onCreated with the saved model.
export default function PerDemandPanel({ onCreated, onBack }) {
  const [name, setName] = useState("");
  const [demands, setDemands] = useState("");
  const [failures, setFailures] = useState("");
  const [conf, setConf] = useState("95"); // confidence % for the zero-failure (success-run) bound
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nd = Number(demands);
  const nf = Number(failures);
  const nc = Number(conf);
  const confValid = conf !== "" && nc > 0 && nc < 100;
  const valid =
    name.trim() && demands !== "" && failures !== "" &&
    Number.isInteger(nd) && nd > 0 && Number.isInteger(nf) && nf >= 0 && nf <= nd &&
    confValid;
  const p = valid ? nf / nd : null;
  // Success run: n zero-failure demands demonstrate reliability >= (1 - C)^(1/n).
  const successRun = nf === 0 && Number.isInteger(nd) && nd > 0 && confValid;
  const rLower = successRun ? Math.pow(1 - nc / 100, 1 / nd) : null;

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await createPerDemandModel(name.trim(), nd, nf, nc / 100));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Per-demand reliability for one-shot or protective equipment (a valve
        that must open, a device that must start). Enter how many times it was
        demanded and how many times it failed. With <b>zero failures</b> this is a
        success-run demonstration test — the demanded count and confidence give a
        demonstrated reliability lower bound.
      </p>

      <label className="login-field">
        <span>Model name</span>
        <input type="text" autoFocus value={name} placeholder="e.g. Relief valve — open on demand"
               onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="row" style={{ gap: "0.6rem", marginTop: "0.8rem" }}>
        <label className="login-field" style={{ flex: 1, maxWidth: 220 }}>
          <span>Demands (trials)</span>
          <input type="number" min="1" step="1" value={demands}
                 onChange={(e) => setDemands(e.target.value)} />
        </label>
        <label className="login-field" style={{ flex: 1, maxWidth: 220 }}>
          <span>Failures</span>
          <input type="number" min="0" step="1" value={failures}
                 onChange={(e) => setFailures(e.target.value)} />
        </label>
        <label className="login-field" style={{ flex: 1, maxWidth: 160 }}>
          <span>Confidence (%)</span>
          <input type="number" min="1" max="99" step="1" value={conf}
                 onChange={(e) => setConf(e.target.value)} />
        </label>
      </div>
      {successRun ? (
        <p className="muted-line" style={{ marginBottom: 0 }}>
          Success run — {nd} demand{nd === 1 ? "" : "s"}, zero failures demonstrates
          reliability <b>≥ {(rLower * 100).toFixed(rLower > 0.99 ? 2 : 1)}%</b> at {nc}% confidence.
        </p>
      ) : p != null && (
        <p className="muted-line" style={{ marginBottom: 0 }}>
          Failure probability per demand: <b>{(p * 100).toFixed(p < 0.1 ? 2 : 1)}%</b>
        </p>
      )}
      {error && <div className="error">{error}</div>}

      <div className="fit-flow-foot">
        <span />
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={onBack} disabled={busy}>Back</button>
          <button onClick={onSave} disabled={!valid || busy}>{busy ? "Creating…" : "Create model"}</button>
        </div>
      </div>
    </div>
  );
}
