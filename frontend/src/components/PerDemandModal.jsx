import { useState } from "react";
import Modal from "./Modal.jsx";
import { createPerDemandModel } from "../api.js";

// Create a per-demand (Binomial) reliability model from a demands/failures
// count — for one-shot and protective equipment where "reliability" is per
// demand, not over time. Mirrors the "From parameters" entry.
export default function PerDemandModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [demands, setDemands] = useState("");
  const [failures, setFailures] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nd = Number(demands);
  const nf = Number(failures);
  const valid =
    name.trim() && demands !== "" && failures !== "" &&
    Number.isInteger(nd) && nd > 0 && Number.isInteger(nf) && nf >= 0 && nf <= nd;

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      const model = await createPerDemandModel(name.trim(), nd, nf);
      onCreated(model);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const p = valid ? nf / nd : null;

  return (
    <Modal
      title="Per-demand model"
      className="modal-sm"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={onSave} disabled={!valid || busy}>{busy ? "Creating…" : "Create model"}</button>
        </div>
      }
    >
      <p className="muted-line" style={{ marginTop: 0 }}>
        Per-demand reliability for one-shot or protective equipment (a valve
        that must open, a device that must start). Enter how many times it was
        demanded and how many times it failed.
      </p>
      <label className="login-field">
        <span>Model name</span>
        <input type="text" autoFocus value={name} placeholder="e.g. Relief valve — open on demand"
               onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="row" style={{ gap: "0.6rem", marginTop: "0.8rem" }}>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Demands (trials)</span>
          <input type="number" min="1" step="1" value={demands}
                 onChange={(e) => setDemands(e.target.value)} />
        </label>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Failures</span>
          <input type="number" min="0" step="1" value={failures}
                 onChange={(e) => setFailures(e.target.value)} />
        </label>
      </div>
      {p != null && (
        <p className="muted-line" style={{ marginBottom: 0 }}>
          Failure probability per demand: <b>{(p * 100).toFixed(p < 0.1 ? 2 : 1)}%</b>
        </p>
      )}
      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
