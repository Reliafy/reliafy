import { useEffect, useId, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import EvidencePicker from "./EvidencePicker.jsx";
import Select from "./Select.jsx";
import TaskChoice from "./TaskChoice.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { FOUND_EMPTY, ROLE, findsSomething } from "../rcmWorksheet.js";
import { workspaceCurrency } from "../money.js";
import { decisionExtrasCheck } from "../decisionCheck.js";

// Evidence that's linked, not checked: it goes with any decision.
const LINKED_ONLY = new Set(["report", "working"]);

// The chosen tile's ✓, so the choice isn't shown by colour alone (not part of its name).
const Tick = () => <span className="choice-tick" aria-hidden="true">✓ </span>;
import { saveErrorText } from "../confirm.js";
import {
  DEFAULT_OUTCOMES, INTERVAL_UNITS, NEEDS_INTERVAL, SCHEDULED, TASK_ORDER, analysisKindOf, checkDecision, combineChoices,
  defaultAction, extraBody, modeAnswers, pruneExtras, rememberUnit, startUnit,
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
// replacement), each with its own name and interval; the rationale is the
// failure mode's notes (one place), and the decision's evidence counts for every task it fits, while a
// further task may link its own (one piece can't cover a degradation model's
// task and a replacement analysis's). Saves back {hidden, consequence, decision} straight to the
// server (the Explorer): onSave returns a promise, and the dialog stays
// open, Apply showing "Saving…", until it's done, and a refusal shows here
// with everything as typed. Apply says what's missing whenever it can't be
// pressed (decisionCheck.js); `limits` adds the Explorer's own checks.
// `workings`: the performance standards' workings the decision can link
// (explorerRcm.js workingsFor), beside models and reports.
// `loadTasks` (the Explorer): () => promise of {available} — the tasks on the
// position or above it that could serve this mode, so the decision can take an
// existing task ("Existing task") instead of making a second one. With it the
// first task also asks what's done if the check finds it, and what the task
// costs each time (kept on the task, as the Maintenance tab keeps it; sent back
// as `cost` beside the decision).
export default function DecisionModal({ options, mode, onSave, onClose, limits = false, workings = [], loadTasks = null }) {
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
  // "Task(s) worth doing" picked (Derryn, 9 Nov 2026: step 3 is a yes or no, each task of
  // its own kind): the first task's kind is chosen under it.
  const [yes, setYes] = useState(() => TASK_ORDER.includes(existing.outcome));
  const [rtfBasis, setRtfBasis] = useState(existing.rtf_basis || null);
  const [task, setTask] = useState(existing.task || own?.text || own?.name || "");
  const [interval, setInterval_] = useState(existing.interval ?? own?.interval ?? "");
  // The decision's own unit, else its task's, else the one chosen last on this device, else hours.
  const [intervalUnit, setIntervalUnit] = useState(() => startUnit(existing.interval_unit ? existing : { interval_unit: own?.unit }));
  const [evidence, setEvidence] = useState(existing.evidence || null);
  // The first task: a new one (named here) or one already on the position or above it.
  const [use, setUse] = useState(existing.task_id && !own ? "existing" : "new");
  const [picked, setPicked] = useState(existing.task_id || "");
  const [available, setAvailable] = useState(null);
  const [found, setFound] = useState(existing.on_found || "");
  const [cost, setCost] = useState("");
  useEffect(() => {
    if (!loadTasks || use !== "existing" || available !== null) return undefined;
    let on = true;
    Promise.resolve(loadTasks()).then((out) => { if (on) setAvailable(out?.available || []); }, () => { if (on) setAvailable([]); });
    return () => { on = false; };
  }, [loadTasks, use, available]);
  // A combination's further tasks ([{key, outcome, task, interval, intervalUnit, taskId}]), the first
  // being the decision's own. One kind may come more than once, so each row has a key of its own.
  const nextKey = useRef(0);
  const newKey = () => { nextKey.current += 1; return `x${nextKey.current}`; };
  const [extras, setExtras] = useState(() => (Array.isArray(existing.outcomes) && existing.outcomes.length > 1
    ? existing.outcomes.slice(1).map((o) => ({
      key: newKey(), outcome: o.outcome, task: o.task || "", interval: o.interval ?? "", intervalUnit: o.interval_unit || startUnit(null),
      evidence: o.evidence || null, had: o.evidence || null, taskId: o.task_id || null,
    }))
    : []));
  // The first task's own evidence, if it has any (linked over the API): kept as it was.
  const firstOwn = Array.isArray(existing.outcomes) && existing.outcomes.length > 1 ? existing.outcomes[0].evidence : null;
  const expectedOf = (o) => options.outcomes.find((x) => x.id === o)?.expected_evidence || null;
  const chosen = extras.map((x) => x.outcome);
  const choices = combineChoices(outcome, chosen, { hidden, consequence });
  const labelOf = (o) => options.outcomes.find((x) => x.id === o)?.label || o;
  // Each click adds a task of that kind (a redesign only once); Remove takes a row back out.
  const addExtra = (o) => setExtras((xs) => [...xs, {
    key: newKey(), outcome: o, task: "", interval: "", intervalUnit: startUnit(null), evidence: null, had: null, taskId: null,
  }]);
  const removeExtra = (key) => setExtras((xs) => xs.filter((x) => x.key !== key));
  const setExtra = (key, patch) => setExtras((xs) => xs.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  // A new outcome or basis expects other models: a linked model goes, a report or a working stays.
  const dropModel = () => setEvidence((e) => (e && LINKED_ONLY.has(e.type) ? e : null));

  const outcomeOpt = options.outcomes.find((o) => o.id === outcome);
  const consequenceOpt = options.consequences.find((c) => c.id === consequence);
  const evidentHidden = options.evident_hidden || EVIDENT_HIDDEN;
  const hiddenKey = hidden === true ? "hidden" : hidden === false ? "evident" : null;
  const hiddenOpt = evidentHidden.find((o) => o.id === hiddenKey);
  const fallback = defaultAction(hidden, consequence);

  // RTF's expected evidence depends on the claimed basis.
  const rtfBasisOpt = options.rtf_bases.find((b) => b.id === rtfBasis);
  const expectedEvidence = outcome === "rtf"
    ? rtfBasisOpt?.expected_evidence || null
    : outcomeOpt?.expected_evidence || null;
  const analysisKind = expectedEvidence === "strategy_analysis"
    ? (outcome === "failure_finding" ? "failure_finding" : "optimal_replacement")
    : null;

  // A choice in question 3: a new outcome or basis drops a linked model that no longer fits.
  const onTaskChoice = (next) => {
    setNoTask(next.noTask);
    setYes(!!next.yes);
    if (next.outcome !== outcome) {
      setOutcome(next.outcome);
      setExtras((xs) => (next.outcome ? pruneExtras(next.outcome, xs) : []));
      dropModel();
    }
    if (next.rtfBasis !== rtfBasis) {
      setRtfBasis(next.rtfBasis);
      dropModel();
    }
  };

  const fields0 = outcomeOpt?.fields || [];
  // A task of its own to name (not one shared with other modes already, not a redesign or a default action).
  const asksTask = !!loadTasks && !sharedNote && SCHEDULED.includes(outcome);
  const existingTask = asksTask && use === "existing";
  // An existing task keeps its own name and interval: nothing to type for them.
  const fields = existingTask ? fields0.filter((f) => f !== "task" && f !== "interval") : fields0;
  const asksFound = !!loadTasks && findsSomething(outcome);
  const check0 = checkDecision({ outcome, rtfBasis, task, interval, intervalUnit, fields, extras, hidden, consequence }, { limits });
  const check = decisionExtrasCheck(check0, { existingTask, picked, cost: asksTask && !existingTask ? cost : "" });
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
    if (asksFound && found.trim()) decision.on_found = found.trim();
    if (fields.includes("task") && task.trim()) decision.task = task.trim();
    if (fields.includes("interval") && interval !== "" && !Number.isNaN(Number(interval))) {
      decision.interval = Number(interval);
      decision.interval_unit = intervalUnit;
      rememberUnit(intervalUnit); // the next decision starts at it
    }
    if (extras.length) {
      // A combination: every task as one of outcomes, the decision's own first.
      const first = { outcome };
      // The first task it had, by its id, while it's the same kind (members are told apart by task).
      const firstTask = Array.isArray(existing.outcomes) && existing.outcomes.length > 1 ? existing.outcomes[0] : existing;
      if (existingTask) first.task_id = picked;
      else if (firstTask?.task_id && firstTask.outcome === outcome) first.task_id = firstTask.task_id;
      for (const k of ["task", "interval", "interval_unit"]) if (decision[k] !== undefined) first[k] = decision[k];
      if (firstOwn?.type && firstOwn?.id) first.evidence = { type: firstOwn.type, id: firstOwn.id };
      delete decision.outcome;
      delete decision.task;
      delete decision.interval;
      delete decision.interval_unit;
      decision.outcomes = [first, ...extras.map((x) => extraBody(x, expectedOf(x.outcome)))];
    } else if (existingTask) {
      // One existing task: named by its id, as a one-task combination (the server's shape for it).
      const first = { outcome, task_id: picked };
      if (decision.on_found) first.on_found = decision.on_found;
      delete decision.outcome;
      delete decision.on_found;
      decision.outcomes = [first];
    }
    // A report or a working goes with any decision; a model only with one that expects its kind
    // (or the one linked before, left as it was: the check then says why it doesn't fit).
    decision.evidence = evidence && (LINKED_ONLY.has(evidence.type) || evidence.type === expectedEvidence
      || evidence === existing.evidence) ? { type: evidence.type, id: evidence.id } : null;
    busy.current = true;
    setFailed(null);
    const typedCost = asksTask && !existingTask && String(cost).trim() !== "" ? Number(cost) : null;
    const done = onSave({ hidden, consequence, decision, ...(typedCost != null ? { cost: typedCost } : {}) });
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
        {/* Question 3 as chip rows (TaskChoice, shared with a failure mode's details): only what
            the doctrine allows here; the default actions once "No task is worth doing" is picked
            (or the saved decision is one); run to failure's reason under it. */}
        <TaskChoice n={3} options={options} hidden={hidden} consequence={consequence}
                    value={{ outcome, noTask, rtfBasis, yes }} onChange={onTaskChoice} />
        {fallback && !noTask && (
          <p className="decision-default" role="note">
            <strong>{fallback.outcome ? "The default action: " : "Next: "}</strong>{fallback.text}
          </p>
        )}
      </div>

      {asksTask && (
        <div className="decision-step">
          <ChoiceChips label="New or existing task" value={use}
                       options={[{ value: "new", label: "New task" }, { value: "existing", label: "Existing task" }]}
                       onChange={(v) => { if (v) setUse(v); }} />
          {existingTask && (
            available === null ? <p className="option-hint">Reading the tasks…</p>
              : available.length === 0 ? <p className="option-hint">No other task on this position or above it: choose New task.</p>
                : (
                  <>
                    <Select value={picked} onChange={setPicked} ariaLabel="Existing task" placeholder="Choose a task…"
                            options={[...available.map((t) => ({
                              value: t.id,
                              label: `${t.name}${t.interval ? ` · every ${t.interval} ${t.unit || ""}`.trimEnd() : ""}${t.position?.id && t.position.id !== mode.position_id ? ` · on ${t.position.name}` : ""}`,
                            }))]} />
                    <p className="option-hint">It keeps its own interval and cost for every failure mode it serves.</p>
                  </>
                )
          )}
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
                title={sharedNote && outcome !== "rtf" ? "It serves other failure modes too: change it on the task" : undefined}
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
          {asksTask && !existingTask && (
            <div className="field-row decision-cost">
              <label className="field-label" htmlFor={`${id}-cost`}>Cost each time ({workspaceCurrency()}, optional)</label>
              <input id={`${id}-cost`} type="number" inputMode="decimal" min="0" step="any" value={cost}
                     placeholder="e.g. 180" className="interval-input"
                     aria-invalid={check.costError ? "true" : undefined}
                     onChange={(e) => setCost(e.target.value)} />
            </div>
          )}
          {check.costError && <p className="field-error">{check.costError}</p>}
        </div>
      )}

      {asksFound && (
        <div className="decision-step">
          <label className="field-label" htmlFor={`${id}-found`}>{ROLE[outcome]?.then || "Then, if found:"} (optional)</label>
          <input id={`${id}-found`} type="text" value={found} maxLength={500} placeholder={FOUND_EMPTY}
                 onChange={(e) => setFound(e.target.value)} />
        </div>
      )}

      {choices.length > 0 && (
        <div className="decision-step decision-combine">
          <label className="field-label" id={`${id}-combine`}>Add another task (optional)</label>
          <div className="option-grid" role="group" aria-labelledby={`${id}-combine`}>
            {choices.map((c) => {
              const n = chosen.filter((x) => x === c.id).length;
              return (
                <button key={c.id} type="button" className="option-tile" disabled={!c.allowed}
                        title={c.allowed ? undefined : c.why || "Can't be combined with the tasks chosen: one redesign at most."}
                        onClick={() => addExtra(c.id)}>
                  <span className="option-title">+ {labelOf(c.id)}{n ? <span className="muted-line"> ({n} added)</span> : null}</span>
                </button>
              );
            })}
          </div>
          <p className="option-hint">
            A combination of tasks: a regular inspection plus a fixed-time replacement, say. Only where no single task
            makes the risk tolerable and the failure could hurt someone or harm the environment.
            Each task is scheduled on its own, and one kind can come more than once (a weekly top-up and an annual
            deep clean). A redesign can sit beside the tasks, which are done until the change is made.
          </p>
          {extras.map((x) => !SCHEDULED.includes(x.outcome) && (
            <div key={x.key} className="decision-extra field-row">
              <span className="field-label">{labelOf(x.outcome)}, beside the tasks until the change is made</span>
              <button type="button" className="link sm" onClick={() => removeExtra(x.key)}>Remove</button>
            </div>
          ))}
          {extras.map((x, i) => SCHEDULED.includes(x.outcome) && (
            <div key={x.key} className="decision-extra">
              <div className="field-row">
                <label className="field-label" htmlFor={`${id}-x-${x.key}`}>{labelOf(x.outcome)}: task and interval (the interval is needed)</label>
                <button type="button" className="link sm" aria-label={`Remove this ${labelOf(x.outcome)} task`}
                        onClick={() => removeExtra(x.key)}>Remove</button>
              </div>
              <div className="field-row">
                <input id={`${id}-x-${x.key}`} type="text" value={x.task}
                       placeholder={x.outcome === "fixed_interval" ? "e.g. Replace the bearing" : "e.g. Vibration check"}
                       onChange={(e) => setExtra(x.key, { task: e.target.value })} />
                <input type="number" inputMode="decimal" className="interval-input" min="0" step="any"
                       value={x.interval} placeholder="Interval"
                       aria-label={`${labelOf(x.outcome)} interval (needed)`} aria-required="true"
                       aria-invalid={check.extraErrors?.[i] ? "true" : undefined}
                       aria-describedby={check.extraErrors?.[i] ? `${id}-x-${x.key}-error` : undefined}
                       onChange={(e) => setExtra(x.key, { interval: e.target.value })} />
                <Select value={x.intervalUnit} options={INTERVAL_UNITS}
                        onChange={(u) => { setExtra(x.key, { intervalUnit: u }); rememberUnit(u); }} />
              </div>
              {check.extraErrors?.[i] && (
                <p className="field-error decision-interval-error" id={`${id}-x-${x.key}-error`}>{check.extraErrors[i]}</p>
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
                  onChange={(e) => setExtra(x.key, { evidence: e })}
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

      {/* The rationale is the failure mode's notes and rationale, under its title in the
          details: one place (Derryn, 9 Nov 2026), so no notes box here. */}
      <p className="option-hint">Write why in the failure mode's Notes and rationale, under its title.</p>
    </Modal>
  );
}
