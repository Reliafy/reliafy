import { useId, useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import EvidencePicker from "./EvidencePicker.jsx";
import Select from "./Select.jsx";
import Field from "./ui/Field.jsx";
import { TextArea } from "./ui/Controls.jsx";

// Evidence that's linked, not checked: it goes with any decision.
const LINKED_ONLY = new Set(["report", "working"]);

// The chosen tile's ✓, so the choice isn't shown by colour alone (not part of its name).
const Tick = () => <span className="choice-tick" aria-hidden="true">✓ </span>;
import { saveErrorText } from "../confirm.js";
import {
  DEFAULT_OUTCOMES, INTERVAL_UNITS, NEEDS_INTERVAL, SCHEDULED, TASK_ORDER, analysisKindOf, checkDecision, combineChoices,
  defaultAction, doctrineRefusal, extraBody, modeAnswers, pruneExtras, rememberUnit, startUnit, worthLine,
} from "../decisionCheck.js";

// The first question's choices when the server's options don't carry them (an older server).
const EVIDENT_HIDDEN = [
  { id: "evident", label: "Evident", hint: "The crew would notice the loss of function on its own, in normal operation." },
  { id: "hidden", label: "Hidden", hint: "Nobody would notice in normal operation until something else fails too (a standby pump, a trip, an alarm). The category is then what that multiple failure would do." },
];

// Guided RCM decision flow for one failure mode, walking the RCM decision
// diagram (SAE JA1011, RCM II; decisionCheck.js): evident or hidden →
// consequence category (for a hidden failure, what the multiple failure would
// do) → the tasks in the diagram's order (on condition, fixed interval, then
// failure finding for a hidden failure), each with what makes it worth doing
// here, and what's done if none is (greyed out where the diagram forbids it,
// with why; the default action named at the end) → task details → linked
// evidence. A scheduled outcome (or a redesign) may take further tasks,
// a combination of tasks (RCM II: a regular inspection plus a fixed-time
// replacement), each with its own name and interval; the notes are once per
// decision, and the decision's evidence counts for every task it fits, while a
// further task may link its own (one piece can't cover a degradation model's
// task and a replacement analysis's). Saves back {hidden, consequence, decision} straight to the
// server (the Explorer): onSave returns a promise, and the dialog stays
// open, Apply showing "Saving…", until it's done, and a refusal shows here
// with everything as typed. Apply says what's missing whenever it can't be
// pressed (decisionCheck.js); `limits` adds the Explorer's own checks.
// `workings`: the performance standards' workings the decision can link
// (explorerRcm.js workingsFor), beside models and reports.
export default function DecisionModal({ options, mode, onSave, onClose, limits = false, workings = [] }) {
  const id = useId();
  const existing = mode.decision || {};
  // The decision's own task, when it also serves other failure modes: it keeps
  // one name and interval for all of them, changed on the task itself, so the
  // dialog shows them read-only (the same values go back, and the decision
  // may still change). A mode not decided yet but with a task linked starts
  // from that task's name and interval.
  const own = (mode.tasks || existing.tasks || [])[0];
  const sharedWith = own?.shared_with || 0;
  const sharedNote = sharedWith
    ? `“${own.name}” also serves ${sharedWith} other failure mode${sharedWith === 1 ? "" : "s"}, so its name and interval are changed on the task (under Tasks in the failure mode's dialog), for all of them.`
    : null;
  const answers0 = modeAnswers(mode);
  const [hidden, setHidden] = useState(answers0.hidden);
  const [consequence, setConsequence] = useState(answers0.consequence);
  const [outcome, setOutcome] = useState(existing.outcome || null);
  // "No task is worth doing" picked: the default actions show (Derryn, 9 Nov 2026).
  // Starts on when the saved decision is already one of them.
  const [noTask, setNoTask] = useState(() => DEFAULT_OUTCOMES.includes(existing.outcome));
  const [rtfBasis, setRtfBasis] = useState(existing.rtf_basis || null);
  const [task, setTask] = useState(existing.task || own?.text || own?.name || "");
  const [interval, setInterval_] = useState(existing.interval ?? own?.interval ?? "");
  // The decision's own unit, else its task's, else the one chosen last on this device, else hours.
  const [intervalUnit, setIntervalUnit] = useState(() => startUnit(existing.interval_unit ? existing : { interval_unit: own?.unit }));
  const [notes, setNotes] = useState(existing.notes || "");
  const [evidence, setEvidence] = useState(existing.evidence || null);
  // A combination's further tasks ([{outcome, task, interval, intervalUnit}]), the first being the decision's own.
  const [extras, setExtras] = useState(() => (Array.isArray(existing.outcomes) && existing.outcomes.length > 1
    ? existing.outcomes.slice(1).map((o) => ({
      outcome: o.outcome, task: o.task || "", interval: o.interval ?? "", intervalUnit: o.interval_unit || startUnit(null),
      evidence: o.evidence || null, had: o.evidence || null,
    }))
    : []));
  // The first task's own evidence, if it has any (linked over the API): kept as it was.
  const firstOwn = Array.isArray(existing.outcomes) && existing.outcomes.length > 1 ? existing.outcomes[0].evidence : null;
  const expectedOf = (o) => options.outcomes.find((x) => x.id === o)?.expected_evidence || null;
  const chosen = extras.map((x) => x.outcome);
  const choices = combineChoices(outcome, chosen, { hidden, consequence });
  const labelOf = (o) => options.outcomes.find((x) => x.id === o)?.label || o;
  const toggleExtra = (o) => setExtras((xs) => (xs.some((x) => x.outcome === o)
    ? xs.filter((x) => x.outcome !== o)
    : [...xs, { outcome: o, task: "", interval: "", intervalUnit: startUnit(null), evidence: null, had: null }]));
  const setExtra = (o, patch) => setExtras((xs) => xs.map((x) => (x.outcome === o ? { ...x, ...patch } : x)));
  // A new outcome or basis expects other models: a linked model goes, a report or a working stays.
  const dropModel = () => setEvidence((e) => (e && LINKED_ONLY.has(e.type) ? e : null));

  const outcomeOpt = options.outcomes.find((o) => o.id === outcome);
  const consequenceOpt = options.consequences.find((c) => c.id === consequence);
  const evidentHidden = options.evident_hidden || EVIDENT_HIDDEN;
  const hiddenKey = hidden === true ? "hidden" : hidden === false ? "evident" : null;
  const hiddenOpt = evidentHidden.find((o) => o.id === hiddenKey);
  const fallback = defaultAction(hidden, consequence);
  const outcomeById = (o) => options.outcomes.find((x) => x.id === o);

  // RTF's expected evidence depends on the claimed basis.
  const rtfBasisOpt = options.rtf_bases.find((b) => b.id === rtfBasis);
  const expectedEvidence = outcome === "rtf"
    ? rtfBasisOpt?.expected_evidence || null
    : outcomeOpt?.expected_evidence || null;
  const analysisKind = expectedEvidence === "strategy_analysis"
    ? (outcome === "failure_finding" ? "failure_finding" : "optimal_replacement")
    : null;

  // The tasks in the diagram's order, then what's done if none is worth doing.
  // One outcome tile with its one-line test; a second click unselects it.
  const tile = (o, extra = "") => {
    const line = worthLine(o.id, hidden, consequence) || o.hint;
    return (
      <div key={o.id} className={"decision-row" + extra}>
        <button
          type="button"
          className={"option-tile" + (outcome === o.id ? " selected" : "")}
          aria-pressed={outcome === o.id}
          aria-describedby={`${id}-o-${o.id}`}
          title={outcome === o.id ? "Click again to unselect" : undefined}
          onClick={() => {
            const next = outcome === o.id ? null : o.id;
            setOutcome(next);
            if (next !== "rtf") setRtfBasis(null);
            setExtras((xs) => (next ? pruneExtras(next, xs) : []));
            dropModel();
          }}
        >
          <span className="option-title">{outcome === o.id && <Tick />}{o.label}</span>
        </button>
        <p className="decision-line" id={`${id}-o-${o.id}`}>{line}</p>
      </div>
    );
  };
  const taskTiles = useMemo(() => TASK_ORDER.map(outcomeById).filter(Boolean), [options.outcomes]); // eslint-disable-line react-hooks/exhaustive-deps
  const otherTiles = useMemo(() => DEFAULT_OUTCOMES.map(outcomeById).filter(Boolean), [options.outcomes]); // eslint-disable-line react-hooks/exhaustive-deps

  const fields = outcomeOpt?.fields || [];
  const check = checkDecision({ outcome, rtfBasis, task, interval, intervalUnit, notes, fields, extras, hidden, consequence }, { limits });
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
    if (extras.length) {
      // A combination: every task as one of outcomes, the decision's own first.
      const first = { outcome };
      for (const k of ["task", "interval", "interval_unit"]) if (decision[k] !== undefined) first[k] = decision[k];
      if (firstOwn?.type && firstOwn?.id) first.evidence = { type: firstOwn.type, id: firstOwn.id };
      delete decision.outcome;
      delete decision.task;
      delete decision.interval;
      delete decision.interval_unit;
      decision.outcomes = [first, ...extras.map((x) => extraBody(x, expectedOf(x.outcome)))];
    }
    // A report or a working goes with any decision; a model only with one that expects its kind
    // (or the one linked before, left as it was: the check then says why it doesn't fit).
    decision.evidence = evidence && (LINKED_ONLY.has(evidence.type) || evidence.type === expectedEvidence
      || evidence === existing.evidence) ? { type: evidence.type, id: evidence.id } : null;
    busy.current = true;
    setFailed(null);
    const done = onSave({ hidden, consequence, decision });
    if (!done || typeof done.then !== "function") return;
    setSaving(true);
    try {
      await done;
    } catch (e) {
      busy.current = false;
      setSaving(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
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
        <label className="field-label" id={`${id}-q1`}>1. Would the crew notice the failure on its own?</label>
        <div className="option-grid" role="group" aria-labelledby={`${id}-q1`}>
          {evidentHidden.map((c) => (
            <button key={c.id} type="button" className={"option-tile" + (hiddenKey === c.id ? " selected" : "")}
                    aria-pressed={hiddenKey === c.id} onClick={() => setHidden(c.id === "hidden")}>
              <span className="option-title">{hiddenKey === c.id && <Tick />}{c.label}</span>
            </button>
          ))}
        </div>
        {hiddenOpt && <p className="option-hint">{hiddenOpt.hint}</p>}
      </div>

      <div className="decision-step">
        <label className="field-label" id={`${id}-q2`}>
          {hidden ? "2. What would the multiple failure do?" : "2. Consequence of failure"}
        </label>
        <div className="option-grid" role="group" aria-labelledby={`${id}-q2`}>
          {options.consequences.filter((c) => c.id !== "hidden").map((c) => (
            <button
              key={c.id}
              type="button"
              className={"option-tile" + (consequence === c.id ? " selected" : "")}
              aria-pressed={consequence === c.id}
              onClick={() => setConsequence(c.id)}
            >
              <span className="option-title">{consequence === c.id && <Tick />}{c.label}</span>
            </button>
          ))}
        </div>
        <p className="option-hint">
          {consequenceOpt
            ? [consequenceOpt.hint, consequenceOpt.worth_doing].filter(Boolean).join(" ")
            : hidden
              ? "The hidden failure plus the second failure it fails to protect against. The first that applies: safety, environmental, operational, non-operational."
              : "The first that applies, in this order: safety, environmental, operational, non-operational."}
        </p>
      </div>

      <div className="decision-step">
        <label className="field-label" id={`${id}-q3`}>3. Which task is worth doing?</label>
        <div className="decision-list" role="group" aria-labelledby={`${id}-q3`}>
          {/* Only what the doctrine allows here is shown (a failure-finding task on an
              evident failure isn't offered at all). The default actions appear once "No
              task is worth doing" is picked, or when the saved decision is one of them. */}
          {taskTiles.filter((o) => !doctrineRefusal(hidden, consequence, [o.id])).map((o) => tile(o))}
          <div className="decision-row decision-row-gap">
            <button
              type="button"
              className={"option-tile" + (noTask ? " selected" : "")}
              aria-pressed={noTask}
              aria-describedby={`${id}-o-notask`}
              title={noTask ? "Click again to unselect" : undefined}
              onClick={() => {
                const next = !noTask;
                setNoTask(next);
                // Leaving the task choice for the default actions (or back) clears what was picked.
                setOutcome(null); setRtfBasis(null); setExtras([]); dropModel();
              }}
            >
              <span className="option-title">{noTask && <Tick />}No task is worth doing</span>
            </button>
            <p className="decision-line" id={`${id}-o-notask`}>None of the tasks above reduces the risk enough, or costs less than the failures it prevents. Pick what's done instead.</p>
          </div>
          {noTask && otherTiles.filter((o) => !doctrineRefusal(hidden, consequence, [o.id])).map((o) => tile(o, " decision-row-indent"))}
        </div>
        {outcomeOpt && <p className="option-hint">{outcomeOpt.hint}</p>}
        {fallback && (
          <p className="decision-default" role="note">
            <strong>{fallback.outcome ? "The default action: " : "Next: "}</strong>{fallback.text}
          </p>
        )}
      </div>

      {outcome === "rtf" && (
        <div className="decision-step">
          <label className="field-label">Why run to failure?</label>
          <div className="option-grid">
            {options.rtf_bases.map((b) => (
              <button
                key={b.id}
                type="button"
                className={"option-tile" + (rtfBasis === b.id ? " selected" : "")}
                aria-pressed={rtfBasis === b.id}
                onClick={() => { setRtfBasis(b.id); dropModel(); }}
              >
                <span className="option-title">{rtfBasis === b.id && <Tick />}{b.label}</span>
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
                readOnly={!!sharedNote && outcome !== "rtf"}
                aria-describedby={sharedNote && outcome !== "rtf" ? `${id}-shared` : undefined}
                title={sharedNote && outcome !== "rtf" ? "Shared with other failure modes: change it on the task" : undefined}
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
                  readOnly={!!sharedNote}
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
                  disabled={!!sharedNote}
                />
              </>
            )}
          </div>
          {sharedNote && outcome !== "rtf" && <p className="option-hint decision-shared" id={`${id}-shared`} role="note">{sharedNote}</p>}
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

      {choices.length > 0 && (
        <div className="decision-step decision-combine">
          <label className="field-label" id={`${id}-combine`}>Add another task (optional)</label>
          <div className="option-grid" role="group" aria-labelledby={`${id}-combine`}>
            {choices.map((c) => {
              const on = chosen.includes(c.id);
              return (
                <button key={c.id} type="button" className={"option-tile" + (on ? " selected" : "")} aria-pressed={on}
                        disabled={!c.allowed}
                        title={c.allowed ? undefined : c.why || "Can't be combined with the tasks chosen: a redesign goes beside one scheduled task only."}
                        onClick={() => toggleExtra(c.id)}>
                  <span className="option-title">{on && <Tick />}+ {labelOf(c.id)}</span>
                </button>
              );
            })}
          </div>
          <p className="option-hint">
            A combination of tasks: a regular inspection plus a fixed-time replacement, say. Only where no single task
            makes the risk tolerable and the failure could hurt someone or harm the environment.
            Each task is scheduled on its own. A redesign can sit beside one task, which is done until the change is made.
          </p>
          {extras.map((x, i) => SCHEDULED.includes(x.outcome) && (
            <div key={x.outcome} className="decision-extra">
              <label className="field-label" htmlFor={`${id}-x-${x.outcome}`}>{labelOf(x.outcome)}: task and interval (the interval is needed)</label>
              <div className="field-row">
                <input id={`${id}-x-${x.outcome}`} type="text" value={x.task}
                       placeholder={x.outcome === "fixed_interval" ? "e.g. Replace the bearing" : "e.g. Vibration check"}
                       onChange={(e) => setExtra(x.outcome, { task: e.target.value })} />
                <input type="number" inputMode="decimal" className="interval-input" min="0" step="any"
                       value={x.interval} placeholder="Interval"
                       aria-label={`${labelOf(x.outcome)} interval (needed)`} aria-required="true"
                       aria-invalid={check.extraErrors?.[i] ? "true" : undefined}
                       aria-describedby={check.extraErrors?.[i] ? `${id}-x-${x.outcome}-error` : undefined}
                       onChange={(e) => setExtra(x.outcome, { interval: e.target.value })} />
                <Select value={x.intervalUnit} options={INTERVAL_UNITS}
                        onChange={(u) => { setExtra(x.outcome, { intervalUnit: u }); rememberUnit(u); }} />
              </div>
              {check.extraErrors?.[i] && (
                <p className="field-error decision-interval-error" id={`${id}-x-${x.outcome}-error`}>{check.extraErrors[i]}</p>
              )}
              <details className="decision-extra-evidence" open={!!x.evidence}>
                <summary>Evidence for this task (optional){x.evidence ? ": linked" : ""}</summary>
                <p className="option-hint">
                  Only when the decision's evidence (step 4) doesn't cover this task: a replacement analysis for a
                  fixed-interval task, say, beside a degradation model for the inspection.
                </p>
                <EvidencePicker
                  expectedType={expectedOf(x.outcome)}
                  analysisKind={analysisKindOf(x.outcome)}
                  value={x.evidence}
                  onChange={(e) => setExtra(x.outcome, { evidence: e })}
                  workings={workings}
                />
              </details>
            </div>
          ))}
        </div>
      )}

      {outcome && (outcome !== "rtf" || rtfBasis) && (
        <div className="decision-step">
          <label className="field-label">4. Link the evidence (optional)</label>
          {extras.some((x) => SCHEDULED.includes(x.outcome)) && (
            <p className="option-hint">
              In a combination this evidence counts for every task it fits (a report or function notes fit any). A task
              it doesn't cover can link its own above; the decision shows as partly evidenced until each task has some.
            </p>
          )}
          <EvidencePicker
            expectedType={expectedEvidence}
            analysisKind={analysisKind}
            value={evidence}
            onChange={setEvidence}
            workings={workings}
          />
        </div>
      )}

      <div className="decision-step">
        <Field label="Notes" optional={!(outcome === "redesign" || outcome === "accept")}>
          <TextArea value={notes} rows={2}
                    placeholder={outcome === "redesign" || outcome === "accept" ? "Document the rationale" : "Why this decision"}
                    onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
