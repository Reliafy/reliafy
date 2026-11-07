import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import { DEFAULT_OUTCOMES, TASK_ORDER, allowedChoices, defaultAction, worthLine } from "../decisionCheck.js";

// Question 3 of the RCM decision (SAE JA1011, RCM II): which task is worth
// doing, as chip rows. Shared by the decision dialog (DecisionModal.jsx) and a
// failure mode's details (RcmModeTasks.jsx), where each choice is saved at once.
//
// Row 1: the tasks the decision diagram allows for the mode's two answers, in
// its order (no failure finding on an evident failure), then "No task is worth
// doing". With that on, row 2: what's done instead (run to failure, accept,
// redesign, as allowed). With run to failure, row 3: why. Only the chosen chip
// of a row has its line under it (what makes it worth doing, or what it
// means), so the rows stay compact. A saved choice the diagram refuses (an
// import) still shows, so it can be seen and changed.
//
//   options   the server's RCM options (outcomes, rtf_bases); null: built-in labels
//   hidden, consequence  the mode's two answers
//   value     {outcome, noTask, rtfBasis}
//   onChange  (next {outcome, noTask, rtfBasis}) on any choice
//   disabled  every row disabled; `locked` the line saying why (row 1)
//   moveOnly  arrows move only (Enter, Space or a click chooses): where each choice is saved
//   n         a number before row 1's label (the dialog's "3.")
//   saved     a count that goes up on each save ("✓ Saved" by row 1's label)
//   bridge    under the chosen chip, what comes next (BRIDGE) instead of the worth-doing
//             line, which becomes each chip's tooltip (the details' step 3)

const LABELS = {
  on_condition: "On condition", fixed_interval: "Fixed interval", failure_finding: "Failure finding",
  rtf: "Run to failure", accept: "Accept", redesign: "Redesign",
};
const BASES = [
  { id: "random", label: "Failures are random", hint: "Evidence: a Weibull fit whose β confidence interval contains 1, or an Exponential fit." },
  { id: "uneconomic", label: "Prevention isn't economic", hint: "Evidence: an optimal-replacement analysis showing no beneficial interval." },
];
// Under the chosen chip in a failure mode's details (`bridge`): what comes next, in the
// card below (Derryn, 10 Nov 2026: the chip row didn't lead into the card). The "worth
// doing" test moves to each chip's tooltip there.
export const BRIDGE = {
  on_condition: "On condition: a check at an interval, then what's done when the check finds it.",
  fixed_interval: "Fixed interval: a task done at a set age or interval.",
  failure_finding: "Failure finding: a check that the hidden function still works, then what's done if it has failed.",
  none: "No task is worth doing: pick what's done instead.",
};
export const NO_TASK_LINE = "None of the tasks reduces the risk enough, or costs less than the failures it prevents. Pick what's done instead.";

export default function TaskChoice({
  options = null, hidden, consequence, value, onChange, disabled = false, locked = null, moveOnly = false, saved = 0,
  className = "", n = null, bridge = false,
}) {
  const { outcome = null, noTask = false, rtfBasis = null } = value || {};
  const opt = (id) => options?.outcomes?.find((o) => o.id === id);
  const label = (id) => opt(id)?.label || LABELS[id] || id;
  const bases = options?.rtf_bases?.length ? options.rtf_bases : BASES;
  const tasks = allowedChoices(TASK_ORDER, hidden, consequence, TASK_ORDER.includes(outcome) ? outcome : null);
  const defaults = allowedChoices(DEFAULT_OUTCOMES, hidden, consequence, DEFAULT_OUTCOMES.includes(outcome) ? outcome : null);
  const first = noTask ? "none" : TASK_ORDER.includes(outcome) ? outcome : "";
  const worth = (o) => worthLine(o, hidden, consequence) || opt(o)?.hint || null;
  const firstLine = locked || (bridge ? BRIDGE[first] || null
    : first === "none" ? NO_TASK_LINE : first ? worth(first) : null);
  const fallback = noTask && !outcome ? defaultAction(hidden, consequence) : null;
  const basis = bases.find((b) => b.id === rtfBasis);
  return (
    <div className={"task-choice" + (className ? ` ${className}` : "")}>
      <Field label={n ? `${n}. Which task is worth doing?` : "Which task is worth doing?"} saved={saved} className="rw-eyebrow" help={firstLine}>
        <ChoiceChips label="Which task is worth doing?" clearable value={first} disabled={disabled} moveOnly={moveOnly}
                     options={[...tasks.map((o) => ({ value: o, label: label(o), ...(bridge ? { title: worth(o) || undefined } : {}) })),
                       { value: "none", label: "No task is worth doing", ...(bridge ? { title: NO_TASK_LINE } : {}) }]}
                     onChange={(v) => onChange(v === "none" ? { outcome: null, noTask: true, rtfBasis: null }
                       : v ? { outcome: v, noTask: false, rtfBasis: null } : { outcome: null, noTask: false, rtfBasis: null })} />
      </Field>
      {noTask && (
        <Field label="What's done instead" className="rw-eyebrow"
               help={DEFAULT_OUTCOMES.includes(outcome) ? opt(outcome)?.hint || null : fallback?.text || null}>
          <ChoiceChips label="What's done instead" clearable value={DEFAULT_OUTCOMES.includes(outcome) ? outcome : ""}
                       disabled={disabled} moveOnly={moveOnly}
                       options={defaults.map((o) => ({ value: o, label: label(o) }))}
                       onChange={(v) => onChange({ outcome: v || null, noTask: true, rtfBasis: null })} />
        </Field>
      )}
      {outcome === "rtf" && (
        <Field label="Why run to failure?" className="rw-eyebrow" help={basis?.hint || null}>
          <ChoiceChips label="Why run to failure?" value={rtfBasis || ""} disabled={disabled} moveOnly={moveOnly}
                       options={bases.map((b) => ({ value: b.id, label: b.label }))}
                       onChange={(v) => onChange({ outcome: "rtf", noTask: true, rtfBasis: v || null })} />
        </Field>
      )}
    </div>
  );
}
