import { useId, useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import EvidencePicker from "./EvidencePicker.jsx";
import Select from "./Select.jsx";
import Chip from "./ui/Chip.jsx";
import { INTERVAL_UNITS, NEEDS_INTERVAL, checkDecision, rememberUnit, startUnit } from "../decisionCheck.js";

// Guided RCM decision flow for one failure mode: consequence → outcome
// (suggested first, per the classic decision diagram) → task details →
// linked evidence. Saves back {consequence, decision}: to the study's tree
// (nothing hits the server until the study is saved), or straight to the
// server (the Explorer), when onSave returns a promise: the dialog then stays
// open, Apply showing "Saving…", until it's done, and a refusal shows here
// with everything as typed. Apply says what's missing whenever it can't be
// pressed (decisionCheck.js); `limits` adds the Explorer's own checks.
export default function DecisionModal({ options, mode, onSave, onClose, limits = false }) {
  const id = useId();
  const existing = mode.decision || {};
  const [consequence, setConsequence] = useState(mode.consequence || null);
  const [outcome, setOutcome] = useState(existing.outcome || null);
  const [rtfBasis, setRtfBasis] = useState(existing.rtf_basis || null);
  const [task, setTask] = useState(existing.task || "");
  const [interval, setInterval_] = useState(existing.interval ?? "");
  // The decision's own unit, else the one chosen last on this device, else hours.
  const [intervalUnit, setIntervalUnit] = useState(() => startUnit(existing));
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
  const check = checkDecision({ outcome, rtfBasis, task, interval, intervalUnit, notes, fields }, { limits });
  const canSave = check.blockers.length === 0;
  const needsInterval = NEEDS_INTERVAL.has(outcome) && fields.includes("interval");
  // One save at a time: a second click (or Enter) while one is on its way does nothing.
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const busy = useRef(false);

  const save = async () => {
    if (!canSave || busy.current) return;
    const decision = { outcome };
    if (outcome === "rtf") decision.rtf_basis = rtfBasis;
    if (fields.includes("task") && task.trim()) decision.task = task.trim();
    if (fields.includes("interval") && interval !== "" && !Number.isNaN(Number(interval))) {
      decision.interval = Number(interval);
      decision.interval_unit = intervalUnit;
      rememberUnit(intervalUnit); // the next decision starts at it
    }
    if (notes.trim()) decision.notes = notes.trim();
    decision.evidence = expectedEvidence && evidenceId
      ? { type: expectedEvidence, id: evidenceId }
      : null;
    busy.current = true;
    setFailed(null);
    const done = onSave({ consequence, decision });
    if (!done || typeof done.then !== "function") return;
    setSaving(true);
    try {
      await done;
    } catch (e) {
      busy.current = false;
      setSaving(false);
      setFailed(e?.message === "Failed to fetch" ? "Couldn't save: check your connection and try again." : e?.message || "Couldn't save the decision.");
    }
  };

  return (
    <Modal
      title={`Decision — ${mode.text || "failure mode"}`}
      onClose={onClose}
      locked={saving}
      className="decision-modal"
      footer={
        <>
          <button className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <div className="decision-apply">
            {(failed || !canSave) && (
              <p className={"decision-why" + (failed ? " error" : "")} id={`${id}-why`} role={failed ? "alert" : "status"}>
                {failed || check.blockers.join(" ")}
              </p>
            )}
            <button onClick={save} disabled={!canSave || saving} aria-busy={saving || undefined}
                    aria-describedby={failed || !canSave ? `${id}-why` : undefined}>
              {saving ? "Saving…" : "Apply"}
            </button>
          </div>
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
                {suggested.includes(o.id) && <Chip tone="accent" style={{ marginLeft: 6 }}>Suggested</Chip>}
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
          <label className="field-label">{needsInterval ? "Task and interval (the interval is needed)" : "Task"}</label>
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
                  type="number" inputMode="decimal"
                  className="interval-input"
                  min="0"
                  step="any"
                  value={interval}
                  placeholder="Interval"
                  aria-label={needsInterval ? "Interval (needed)" : "Interval"}
                  aria-required={needsInterval || undefined}
                  aria-invalid={check.intervalError ? "true" : undefined}
                  aria-describedby={check.intervalError ? `${id}-interval` : undefined}
                  onChange={(e) => setInterval_(e.target.value)}
                />
                <Select
                  value={intervalUnit}
                  onChange={(u) => { setIntervalUnit(u); rememberUnit(u); }}
                  title="Use the same time unit as the linked analysis — a mismatch resolves as inconclusive."
                  options={INTERVAL_UNITS}
                />
              </>
            )}
          </div>
          {check.intervalError && <p className="field-error decision-interval-error" id={`${id}-interval`}>{check.intervalError}</p>}
          {check.notice && <p className="option-hint decision-notice" role="note">{check.notice}</p>}
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
