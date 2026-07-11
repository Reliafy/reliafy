import { useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import EvidencePicker from "./EvidencePicker.jsx";
import Select from "./Select.jsx";

// Guided RCM decision flow for one failure mode: consequence → outcome
// (suggested first, per the classic decision diagram) → task details →
// linked evidence. Saves back {consequence, decision} to the tree editor;
// nothing hits the server until the study is saved.
export default function DecisionModal({ options, mode, onSave, onClose }) {
  const existing = mode.decision || {};
  const [consequence, setConsequence] = useState(mode.consequence || null);
  const [outcome, setOutcome] = useState(existing.outcome || null);
  const [rtfBasis, setRtfBasis] = useState(existing.rtf_basis || null);
  const [task, setTask] = useState(existing.task || "");
  const [interval, setInterval_] = useState(existing.interval ?? "");
  const [intervalUnit, setIntervalUnit] = useState(existing.interval_unit || "hours");
  const [notes, setNotes] = useState(existing.notes || "");
  const [evidenceId, setEvidenceId] = useState(existing.evidence?.id || null);

  const outcomeOpt = options.outcomes.find((o) => o.id === outcome);
  const consequenceOpt = options.consequences.find((c) => c.id === consequence);
  const suggested = consequenceOpt?.suggested_outcomes || [];

  // RTF's expected evidence depends on the claimed basis.
  const rtfBasisOpt = options.rtf_bases.find((b) => b.id === rtfBasis);
  const expectedEvidence = outcome === "rtf"
    ? rtfBasisOpt?.expected_evidence || null
    : outcomeOpt?.expected_evidence || null;
  const analysisKind = expectedEvidence === "strategy_analysis"
    ? (outcome === "failure_finding" ? "failure_finding" : "optimal_replacement")
    : null;

  const orderedOutcomes = useMemo(() => {
    const rank = (o) => {
      const i = suggested.indexOf(o.id);
      return i === -1 ? suggested.length + 1 : i;
    };
    return [...options.outcomes].sort((a, b) => rank(a) - rank(b));
  }, [options.outcomes, suggested]);

  const fields = outcomeOpt?.fields || [];
  const canSave = !!outcome && (outcome !== "rtf" || !!rtfBasis);

  const save = () => {
    if (!canSave) return;
    const decision = { outcome };
    if (outcome === "rtf") decision.rtf_basis = rtfBasis;
    if (fields.includes("task") && task.trim()) decision.task = task.trim();
    if (fields.includes("interval") && interval !== "" && !Number.isNaN(Number(interval))) {
      decision.interval = Number(interval);
      decision.interval_unit = intervalUnit;
    }
    if (notes.trim()) decision.notes = notes.trim();
    decision.evidence = expectedEvidence && evidenceId
      ? { type: expectedEvidence, id: evidenceId }
      : null;
    onSave({ consequence, decision });
  };

  return (
    <Modal
      title={`Decision — ${mode.text || "failure mode"}`}
      onClose={onClose}
      className="decision-modal"
      footer={
        <>
          <button className="secondary" onClick={onClose}>Cancel</button>
          <button onClick={save} disabled={!canSave}>Apply</button>
        </>
      }
    >
      <div className="decision-step">
        <label className="field-label">1. Consequence of failure</label>
        <div className="option-grid">
          {options.consequences.map((c) => (
            <button
              key={c.id}
              type="button"
              className={"option-tile" + (consequence === c.id ? " selected" : "")}
              onClick={() => setConsequence(c.id)}
            >
              <span className="option-title">{c.label}</span>
            </button>
          ))}
        </div>
        {consequenceOpt && <p className="option-hint">{consequenceOpt.hint}</p>}
      </div>

      <div className="decision-step">
        <label className="field-label">2. Maintenance decision</label>
        <div className="option-grid">
          {orderedOutcomes.map((o) => (
            <button
              key={o.id}
              type="button"
              className={
                "option-tile" +
                (outcome === o.id ? " selected" : "") +
                (suggested.includes(o.id) ? " suggested" : "")
              }
              onClick={() => {
                setOutcome(o.id);
                if (o.id !== "rtf") setRtfBasis(null);
                setEvidenceId(null);
              }}
            >
              <span className="option-title">
                {o.label}
                {suggested.includes(o.id) && <span className="suggest-tag">suggested</span>}
              </span>
            </button>
          ))}
        </div>
        {outcomeOpt && <p className="option-hint">{outcomeOpt.hint}</p>}
      </div>

      {outcome === "rtf" && (
        <div className="decision-step">
          <label className="field-label">Why run-to-failure?</label>
          <div className="option-grid">
            {options.rtf_bases.map((b) => (
              <button
                key={b.id}
                type="button"
                className={"option-tile" + (rtfBasis === b.id ? " selected" : "")}
                onClick={() => { setRtfBasis(b.id); setEvidenceId(null); }}
              >
                <span className="option-title">{b.label}</span>
              </button>
            ))}
          </div>
          {rtfBasisOpt && <p className="option-hint">{rtfBasisOpt.hint}</p>}
        </div>
      )}

      {(fields.includes("task") || fields.includes("interval")) && (
        <div className="decision-step">
          <label className="field-label">Task</label>
          <div className="field-row">
            {fields.includes("task") && (
              <input
                type="text"
                value={task}
                placeholder={outcome === "rtf" ? "Corrective action on failure (optional)" : "e.g. Replace brake pads"}
                onChange={(e) => setTask(e.target.value)}
              />
            )}
            {fields.includes("interval") && (
              <>
                <input
                  type="number"
                  className="interval-input"
                  min="0"
                  step="any"
                  value={interval}
                  placeholder="Interval"
                  onChange={(e) => setInterval_(e.target.value)}
                />
                <Select
                  value={intervalUnit}
                  onChange={setIntervalUnit}
                  title="Use the same time unit as the linked analysis — a mismatch resolves as inconclusive."
                  options={["hours", "days", "weeks", "months", "years", "cycles", "km"]}
                />
              </>
            )}
          </div>
          {fields.includes("interval") && expectedEvidence && (
            <p className="option-hint">
              Use the same time unit as the linked analysis — mismatched units
              resolve as inconclusive.
            </p>
          )}
        </div>
      )}

      {expectedEvidence && (
        <div className="decision-step">
          <label className="field-label">3. Link the evidence</label>
          <EvidencePicker
            expectedType={expectedEvidence}
            analysisKind={analysisKind}
            value={evidenceId}
            onChange={setEvidenceId}
          />
        </div>
      )}

      <div className="decision-step">
        <label className="field-label">Notes</label>
        <textarea
          rows={2}
          value={notes}
          placeholder={outcome === "redesign" || outcome === "accept" ? "Document the rationale" : "Optional"}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
    </Modal>
  );
}
