import { useState } from "react";
import Modal from "./Modal.jsx";
import { openGuide } from "./HelpButton.jsx";

// Set the beta-factor for a common-cause group: the fraction of each member's
// failures that are shared-cause (and take out the whole group at once).
// β is entered as a percentage (#298) and stored as a fraction.
const toPct = (b) => String(Number((Number(b) * 100).toPrecision(6)));

export default function CcfModal({ initial, memberLabels, repairable, onClose, onSubmit }) {
  const [pctText, setPctText] = useState(toPct(initial?.beta ?? 0.1));
  // What β is a fraction of (#210): each member's failure rate (holds over
  // the whole life, the default) or its failure probability (PRA basic
  // events: only while that probability is small).
  const [basis, setBasis] = useState(initial?.basis === "probability" ? "probability" : "rate");
  const b = Number(pctText) / 100;
  const valid = pctText !== "" && Number.isFinite(b) && b > 0 && b < 1;
  const pct = valid ? Number((b * 100).toPrecision(3)) : 0;
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
        <span>β-factor (%)</span>
        <div className="ccf-slider-row">
          <input type="range" min="1" max="50" step="1" value={valid ? Math.min(50, Math.max(1, b * 100)) : 10}
                 onChange={(e) => setPctText(e.target.value)} aria-label="β-factor, percent" />
          <span className="ccf-beta-pct">
            <input type="number" min="0.1" max="99.9" step="0.5" value={pctText}
                   onChange={(e) => setPctText(e.target.value)} className="ccf-beta-num" aria-label="β-factor in percent" />
            %
          </span>
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
          lives (revealed failures with exponential repairs, or proof-tested ones repaired in no time, a fixed
          time or an exponential one), no scheduled maintenance and a crew for every repair. Otherwise it's
          left out of every figure, and Validate says why; a safety function's PFDavg still takes it in where
          the long run can (proof tests that take time, say).
        </p>
      )}
      <p className="hint">
        {pct}% of each component's failures are shared-cause — they take out all{" "}
        {n} at once; the remaining {Number((100 - pct).toPrecision(3))}% are independent. Higher β erodes
        the benefit of the redundancy.{" "}
        <button type="button" className="link" onClick={() => openGuide("common-cause-group")}>
          How do I use this?
        </button>
      </p>
    </Modal>
  );
}
