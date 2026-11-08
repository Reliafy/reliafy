import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import { DEFAULT_OUTCOMES, TASK_ORDER, allowedChoices, defaultAction, worthLine } from "../decisionCheck.js";

// Question 3 of the RCM decision (SAE JA1011, RCM II): is a task worth doing? As a
// yes or no (Derryn, 9 Nov 2026: "Task(s) worth doing" · "No task is worth doing"),
// shared by the decision dialog (DecisionModal.jsx) and a failure mode's details
// (RcmModeTasks.jsx, `bare`), where each choice is saved at once.
//
// "Task(s) worth doing": each task carries its own kind (on condition, fixed interval,
// failure finding where the failure is hidden: only those the decision diagram allows
// for the mode's two answers, the worth-doing test as each kind's tooltip). In the
// dialog the decision's first task's kind is chosen here ("Kind of task"); in the
// details each task's kind is on the task, so this row is only yes or no.
// "No task is worth doing": what's done instead (run to failure, accept, redesign, as
// allowed), and run to failure's reason. A saved choice the diagram refuses (an import)
// still shows, so it can be seen and changed.
//
//   options   the server's RCM options (outcomes, rtf_bases); null: built-in labels
//   hidden, consequence  the mode's two answers
//   value     {outcome, noTask, rtfBasis, yes}: yes, "Task(s) worth doing" picked (a
//             task kind as the outcome says so too)
//   onChange  (next {outcome, noTask, rtfBasis, yes}) on any choice
//   disabled  every row disabled; `locked` the line saying why (row 1)
//   moveOnly  arrows move only (Enter, Space or a click chooses): where each choice is saved
//   n         a number before row 1's label (the dialog's "3.")
//   saved     a count that goes up on each save ("✓ Saved" by row 1's label)
//   bare      the details' grid row: no labels over the chips, no help sentences

const LABELS = {
  on_condition: "On condition", fixed_interval: "Fixed interval", failure_finding: "Failure finding",
  rtf: "Run to failure", accept: "Accept", redesign: "Redesign",
};
const BASES = [
  { id: "random", label: "Failures are random", hint: "Evidence: a Weibull fit whose β confidence interval contains 1, or an Exponential fit." },
  { id: "uneconomic", label: "Prevention isn't economic", hint: "Evidence: an optimal-replacement analysis showing no beneficial interval." },
];
export const NO_TASK_LINE = "None of the tasks reduces the risk enough, or costs less than the failures it prevents. Pick what's done instead.";

export const YES_LABEL = "Task(s) worth doing";
export const NO_LABEL = "No task is worth doing";

export default function TaskChoice({
  options = null, hidden, consequence, value, onChange, disabled = false, locked = null, moveOnly = false, saved = 0,
  className = "", n = null, bare = false,
}) {
  const { outcome = null, noTask = false, rtfBasis = null, yes = false } = value || {};
  const opt = (id) => options?.outcomes?.find((o) => o.id === id);
  const label = (id) => opt(id)?.label || LABELS[id] || id;
  const bases = options?.rtf_bases?.length ? options.rtf_bases : BASES;
  const kinds = allowedChoices(TASK_ORDER, hidden, consequence, TASK_ORDER.includes(outcome) ? outcome : null);
  const defaults = allowedChoices(DEFAULT_OUTCOMES, hidden, consequence, DEFAULT_OUTCOMES.includes(outcome) ? outcome : null);
  const tasksOn = !noTask && (yes || TASK_ORDER.includes(outcome));
  const first = noTask ? "none" : tasksOn ? "tasks" : "";
  const worth = (o) => worthLine(o, hidden, consequence) || opt(o)?.hint || null;
  const fallback = noTask && !outcome ? defaultAction(hidden, consequence) : null;
  const basis = bases.find((b) => b.id === rtfBasis);
  const sm = bare ? "sm" : "";
  const yesNo = (
    <ChoiceChips label="Which task is worth doing?" clearable value={first} disabled={disabled} moveOnly={moveOnly} className={sm}
                 options={[{ value: "tasks", label: YES_LABEL, title: "One or more tasks, each of its own kind: pick it for each task" },
                   { value: "none", label: NO_LABEL, title: NO_TASK_LINE }]}
                 onChange={(v) => onChange(v === "none" ? { outcome: null, noTask: true, rtfBasis: null, yes: false }
                   : v === "tasks" ? { outcome: TASK_ORDER.includes(outcome) ? outcome : null, noTask: false, rtfBasis: null, yes: true }
                     : { outcome: null, noTask: false, rtfBasis: null, yes: false })} />
  );
  const kindChips = (
    <ChoiceChips label="Kind of task" value={TASK_ORDER.includes(outcome) ? outcome : ""} disabled={disabled} moveOnly={moveOnly} className={sm}
                 options={kinds.map((o) => ({ value: o, label: label(o), title: worth(o) || undefined }))}
                 onChange={(v) => onChange({ outcome: v || null, noTask: false, rtfBasis: null, yes: true })} />
  );
  const insteadChips = (
    <ChoiceChips label="What's done instead" clearable value={DEFAULT_OUTCOMES.includes(outcome) ? outcome : ""}
                 disabled={disabled} moveOnly={moveOnly} className={sm}
                 options={defaults.map((o) => ({ value: o, label: label(o), ...(opt(o)?.hint ? { title: opt(o).hint } : {}) }))}
                 onChange={(v) => onChange({ outcome: v || null, noTask: true, rtfBasis: null, yes: false })} />
  );
  const basisChips = (
    <ChoiceChips label="Why run to failure?" value={rtfBasis || ""} disabled={disabled} moveOnly={moveOnly} className={sm}
                 options={bases.map((b) => ({ value: b.id, label: b.label, ...(b.hint ? { title: b.hint } : {}) }))}
                 onChange={(v) => onChange({ outcome: "rtf", noTask: true, rtfBasis: v || null, yes: false })} />
  );
  if (bare) {
    // The details' grid row: yes or no, then (no) what's done instead and why; each
    // task's kind is on the task, in the Tasks row. No labels over the chips (the grid's
    // left column names the row) and no help sentences: the hints are the chips' tooltips.
    return (
      <div className={"task-choice bare" + (className ? ` ${className}` : "")}>
        {yesNo}
        {locked && <p className="tc-line">{locked}</p>}
        {noTask && <div className="tc-sub"><span className="tc-sublabel" aria-hidden="true">Instead</span>{insteadChips}</div>}
        {outcome === "rtf" && <div className="tc-sub"><span className="tc-sublabel" aria-hidden="true">Why</span>{basisChips}</div>}
      </div>
    );
  }
  return (
    <div className={"task-choice" + (className ? ` ${className}` : "")}>
      <Field label={n ? `${n}. Is a task worth doing?` : "Is a task worth doing?"} saved={saved} className="rw-eyebrow" help={locked || (noTask ? NO_TASK_LINE : null)}>
        {yesNo}
      </Field>
      {tasksOn && (
        <Field label="Kind of task" className="rw-eyebrow" help={TASK_ORDER.includes(outcome) ? worth(outcome) : null}>
          {kindChips}
        </Field>
      )}
      {noTask && (
        <Field label="What's done instead" className="rw-eyebrow"
               help={DEFAULT_OUTCOMES.includes(outcome) ? opt(outcome)?.hint || null : fallback?.text || null}>
          {insteadChips}
        </Field>
      )}
      {outcome === "rtf" && (
        <Field label="Why run to failure?" className="rw-eyebrow" help={basis?.hint || null}>
          {basisChips}
        </Field>
      )}
    </div>
  );
}
