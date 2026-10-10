import { useState } from "react";
import Modal from "./Modal.jsx";
import { openGuide } from "./HelpButton.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import "./RbdBlockOptions.css";

// The letters after β of the multiple Greek letter model (#84): γ for a group
// of three, γ and δ for four, …; each the chance a shared failure that takes
// k members takes at least one more.
const LETTERS = [["γ", 3], ["δ", 4], ["ε", 5], ["ζ", 6], ["η", 7], ["θ", 8]];

// Set the beta-factor for a common-cause group: the fraction of each member's
// failures that are shared-cause (and take out the whole group at once).
export default function CcfModal({ initial, memberLabels, repairable, onClose, onSubmit }) {
  const [beta, setBeta] = useState(initial?.beta ?? 0.1);
  // What β is a fraction of (#210): each member's failure rate (holds over
  // the whole life, the default) or its failure probability (PRA basic
  // events: only while that probability is small).
  const [basis, setBasis] = useState(initial?.basis === "probability" ? "probability" : "rate");
  const b = Number(beta);
  const n = memberLabels.length;
  // The multiple Greek letter model for groups of three or more (#84).
  const lettersNeeded = Math.max(n - 2, 0);
  const [model, setModel] = useState(initial?.mgl?.length && n >= 3 ? "mgl" : "beta");
  const [mgl, setMgl] = useState(() =>
    Array.from({ length: lettersNeeded }, (_, i) => initial?.mgl?.[i] ?? 0.3));
  const useMgl = model === "mgl" && lettersNeeded > 0;
  const mglNums = mgl.map(Number);
  const validMgl = !useMgl || mglNums.every((x) => Number.isFinite(x) && x >= 0 && x <= 1);
  const valid = Number.isFinite(b) && b > 0 && b < 1 && validMgl;
  const pct = Math.round((Number.isFinite(b) && b > 0 && b < 1 ? b : 0) * 100);

  const footer = (
    <>
      <span className="hint">Typical β is 1–20%.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={() => valid && onSubmit({ beta: b, basis, mgl: useMgl ? mglNums : null })} disabled={!valid}>
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
      {n >= 3 && (
        <div className="ccf-model">
          <SegmentedControl label="Common-cause model" showLabel value={model} onChange={setModel}
                            options={[{ value: "beta", label: "Beta factor" },
                                      { value: "mgl", label: "Multiple Greek letter" }]} />
          {useMgl && (
            <>
              <div className="param-fields">
                {mgl.map((v, i) => (
                  <label className="param-field" key={LETTERS[i][0]}
                         title={`Of the shared failures that take ${LETTERS[i][1] - 1} or more, the share that take at least ${LETTERS[i][1]}.`}>
                    <span>{LETTERS[i][0]} — at least {LETTERS[i][1]} of {n}</span>
                    <input type="number" step="any" min="0" max="1" value={v}
                           onChange={(e) => setMgl((m) => m.map((x, j) => (j === i ? e.target.value : x)))} />
                  </label>
                ))}
              </div>
              {!validMgl && <p className="hint">Each letter is a probability from 0 to 1.</p>}
              <p className="hint">
                β is the share of each member's failures that are shared; the letters split those shared failures
                by how many members they take, so a cause can take two of {n} without taking all {n}.
              </p>
            </>
          )}
        </div>
      )}
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
          left out of every figure, and Validate says why. Where proof tests take time, only the exact failure
          frequency leaves it out, and the results say so.
        </p>
      )}
      <p className="hint">
        {pct}% of each component's failures are shared-cause — they take out{" "}
        {useMgl ? `two or more of the ${n}` : `all ${n} at once`}; the remaining {100 - pct}% are independent.
        Higher β erodes the benefit of the redundancy.{" "}
        <button type="button" className="link" onClick={() => openGuide("common-cause-group")}>
          How do I use this?
        </button>
      </p>
    </Modal>
  );
}
