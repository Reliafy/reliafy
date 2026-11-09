import { useState } from "react";
import { Link } from "react-router-dom";
import { checkWorkItem, markWorkOrderLine } from "../api.js";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { subjectPath } from "../maintenanceSubjects.js";
import { progressText } from "../workOrderReadings.js";
import { LINE_CHOICES, choiceAsks, groupLines, lineChoice, lineText, markBody } from "../packageLines.js";

// A work package's work order: its lines grouped by position, each answered
// Done, Done with a problem (a note) or Not done (a reason), saved at once.
export default function PackageLines({ wo, onChanged }) {
  const open = !["closed", "cancelled"].includes(wo.status);
  const lines = wo.lines || [];
  return (
    <section className="card">
      <div className="maint-head"><h2>Lines</h2><span className="lib-date">{lines.filter(lineChoice).length} of {lines.length} answered</span></div>
      {groupLines(lines).map((g) => (
        <div key={g.key} className="maint-group">
          <h3>{g.subject ? <Link to={subjectPath(g.subject)}>{g.subject.name}</Link> : "Elsewhere"}</h3>
          <ul className="pkg-lines">
            {g.lines.map((line) => <Line key={line.task_id} wo={wo} line={line} open={open} onChanged={onChanged} />)}
          </ul>
        </div>
      ))}
    </section>
  );
}

function Line({ wo, line, open, onChanged }) {
  // A choice that needs words, being written: {choice, text}.
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const saved = lineChoice(line);
  const save = async (choice, text) => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await markWorkOrderLine(wo.id, line.task_id, markBody(choice, text)));
      setDraft(null);
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };
  const choose = (choice) => {
    if (choiceAsks(choice)) setDraft({ choice, text: choice === saved ? lineText(line) : "" });
    else { setDraft(null); save(choice); }
  };
  const ask = draft && choiceAsks(draft.choice);
  const progress = progressText(wo.readings_by_task?.[line.task_id]);
  return (
    <li className="pkg-line">
      <div className="pkg-line-name">
        <strong>{line.name}</strong>
        {progress && <span className="lib-date maint-line-readings">{progress}</span>}
      </div>
      {(line.steps || []).map((i) => {
        const step = wo.checklist[i];
        return (
          <label key={i} className="maint-row pkg-step">
            <input type="checkbox" checked={!!step?.done} disabled={!open}
                   onChange={async (e) => onChanged(await checkWorkItem(wo.id, i, e.target.checked))} />
            <span>{step?.text}</span>
          </label>
        );
      })}
      <ChoiceChips label={`${line.name}: was it done?`} options={LINE_CHOICES} value={draft ? draft.choice : saved}
                   onChange={(v) => (v ? choose(v) : save(""))} clearable disabled={!open || busy} />
      {ask ? (
        <form className="maint-row pkg-ask" onSubmit={(e) => { e.preventDefault(); save(draft.choice, draft.text); }}>
          <input autoFocus aria-label={ask} placeholder={ask} value={draft.text}
                 onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
          <button type="submit" disabled={busy || !draft.text.trim()}>Save</button>
          <button type="button" className="secondary" onClick={() => setDraft(null)}>Cancel</button>
        </form>
      ) : lineText(line) && (
        <p className="lib-date pkg-said">{saved === "not_done" ? "Not done: " : "Problem: "}{lineText(line)}</p>
      )}
      {error && <p className="field-error" role="alert">{error}</p>}
    </li>
  );
}
