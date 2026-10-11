import { useState } from "react";
import Modal from "./Modal.jsx";

// Name and save the current RBD — or (``asNew``) a copy of it under a new id.
// ``initialError``: why a straight save of a named diagram failed (#303).
export default function RbdSaveModal({ initialName, onClose, onSubmit, asNew = false, initialError = null }) {
  const [name, setName] = useState(initialName || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(initialError);

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit(name.trim());
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  };

  const footer = (
    <>
      <span className="hint">
        {asNew ? "A separate copy: this diagram stays as it was last saved." : "Saved RBDs can be embedded as sub-systems."}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose} disabled={saving}>
          Cancel
        </button>
        <button onClick={submit} disabled={saving || !name.trim()}>
          {saving ? "Saving…" : asNew ? "Save as new" : "Save RBD"}
        </button>
      </div>
    </>
  );

  return (
    <Modal title={asNew ? "Save as new RBD" : "Save RBD"} onClose={onClose} locked={saving} footer={footer}>
      {error && <div className="error">{error}</div>}
      <input
        className="save-name"
        type="text"
        autoFocus
        placeholder="RBD name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
    </Modal>
  );
}
