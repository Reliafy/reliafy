import { useState } from "react";
import Modal from "./Modal.jsx";
import { openGuide } from "./HelpButton.jsx";

// Set the beta-factor for a common-cause group: the fraction of each member's
// failures that are shared-cause (and take out the whole group at once).
export default function CcfModal({ initial, memberLabels, onClose, onSubmit }) {
  const [beta, setBeta] = useState(initial?.beta ?? 0.1);
  const b = Number(beta);
  const valid = Number.isFinite(b) && b > 0 && b < 1;
  const pct = Math.round((valid ? b : 0) * 100);
  const n = memberLabels.length;

  const footer = (
    <>
      <span className="hint">Typical β is 1–20%.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={() => valid && onSubmit({ beta: b })} disabled={!valid}>
          {initial?.groupId ? "Update group" : "Create group"}
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Common-cause group" onClose={onClose} footer={footer}>
      <p className="muted-line" style={{ marginTop: 0 }}>
        These redundant components share a failure cause:{" "}
        <strong>{memberLabels.join(", ")}</strong>. Give the <em>β-factor</em> —
        the fraction of each one's failures that are common-cause.
      </p>
      <label className="login-field">
        <span>β-factor</span>
        <div className="ccf-slider-row">
          <input type="range" min="0.01" max="0.5" step="0.01" value={beta}
                 onChange={(e) => setBeta(e.target.value)} />
          <input type="number" min="0.001" max="0.999" step="0.01" value={beta}
                 onChange={(e) => setBeta(e.target.value)} className="ccf-beta-num" />
        </div>
      </label>
      <p className="hint">
        {pct}% of each component's failures are shared-cause — they take out all{" "}
        {n} at once; the remaining {100 - pct}% are independent. Higher β erodes
        the benefit of the redundancy.{" "}
        <button type="button" className="link-btn" onClick={() => openGuide("common-cause-group")}>
          How do I use this?
        </button>
      </p>
    </Modal>
  );
}
