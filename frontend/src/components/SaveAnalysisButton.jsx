import { useState } from "react";
import Modal from "./Modal.jsx";
import { saveStrategyAnalysis } from "../api.js";

// "Save analysis" affordance shared by the strategy tools: prompts for a name,
// then persists {kind, inputs} — the server recomputes the results (saved
// analyses are evidence for RCM decisions, so the client never supplies them).
export default function SaveAnalysisButton({ kind, inputs, defaultName }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [savedId, setSavedId] = useState(null);

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      const doc = await saveStrategyAnalysis(name.trim(), kind, inputs);
      setSavedId(doc.id);
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (savedId) {
    return <span className="saved-note">✓ Saved to <a href="/strategy/analyses">analyses</a></span>;
  }

  return (
    <>
      <button className="secondary" onClick={() => { setName(defaultName || ""); setOpen(true); }}>
        Save analysis
      </button>
      {open && (
        <Modal
          title="Save this analysis"
          className="modal-sm"
          onClose={() => setOpen(false)}
          locked={busy}
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              <button className="secondary" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
              <button onClick={onSave} disabled={busy || !name.trim()}>
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          }
        >
          <label className="login-field">
            <span>Name</span>
            <input type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
          </label>
          <p className="muted-line">
            Saved analyses can be linked as evidence in RCM studies. The result
            is recomputed on the server from your inputs when saved.
          </p>
          {error && <div className="error">{error}</div>}
        </Modal>
      )}
    </>
  );
}
