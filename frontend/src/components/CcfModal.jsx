import { useState } from "react";
import Modal from "./Modal.jsx";
import { openGuide } from "./HelpButton.jsx";

// Set the beta-factor for a common-cause group: the fraction of each member's
// failures that are shared-cause (and take out the whole group at once).
export default function CcfModal({ initial, memberLabels, repairable, onClose, onSubmit }) {
  const [beta, setBeta] = useState(initial?.beta ?? 0.1);
  // What β is a fraction of (#210): each member's failure rate (holds over
  // the whole life, the default) or its failure probability (PRA basic
  // events: only while that probability is small).
  const [basis, setBasis] = useState(initial?.basis === "probability" ? "probability" : "rate");
  const b = Number(beta);
  const valid = Number.isFinite(b) && b > 0 && b < 1;
  const pct = Math.round((valid ? b : 0) * 100);
  const n = memberLabels.length;

  const footer = (
    <>
      <span className="hint">Typical β is 1–20%.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={() => valid && onSubmit({ beta: b, basis })} disabled={!valid}>
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
      {!repairable && (
        <label className="login-field">
          <span>β splits each component's</span>
          <select value={basis} onChange={(e) => setBasis(e.target.value)}>
            <option value="rate">Failure rate — holds over the whole life (recommended)</option>
            <option value="probability">Failure probability — short missions only (PRA basic events)</option>
          </select>
        </label>
      )}
      {!repairable && basis === "probability" && (
        <p className="hint">
          The probability split is a rare-event model: over a lifetime it makes the group more reliable
          than it is, and the MTTF isn't given.
        </p>
      )}
      {repairable && (
        <p className="hint">
          β splits each member's failure rate. The group is followed over time in every availability
          figure — the long run, A(t), events and costs, the simulation — when its members have exponential
          lives (revealed failures, or proof tests and repairs that take no time), no scheduled maintenance
          and a crew for every repair. Otherwise it's left out of every figure, and Validate says why.
        </p>
      )}
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
