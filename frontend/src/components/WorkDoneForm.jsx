import { useState } from "react";
import { Link } from "react-router-dom";
import { FailureModePicker, Field, today } from "./MaintenanceParts.jsx";
import { failureModeBody, failureModeReady } from "../maintenanceModes.js";
import { closeBlocker, closePayload, unanswered } from "../packageLines.js";
import { partChoices, stockText } from "../maintenanceSpares.js";
import {
  actionKinds, closeActionKind, closeTarget, defaultCloseKind, defaultFailed, foundFailedText, newItemBody,
  replaceReason, replaceRecordText, subjectPath, closeActionBlocker,
} from "../maintenanceSubjects.js";
import { DateInput } from "./ui/DateTimeInput.jsx";

// What was done, as a work order's close records it: each action (checked, replaced,
// repaired, inspected, other; a replacement's failure mode, the part and the new
// item), the day and notes: a work order's close (onSubmit closes it). Work
// management only: with it turned off (workManagement.js) nothing records work done.
// `wo`: the work order.

export const KINDS = [
  // A check that found nothing to do: sent as an inspection that found it OK.
  { id: "checked", label: "Checked, nothing done" },
  { id: "replace", label: "Replaced it" },
  { id: "repair", label: "Repaired it" },
  { id: "inspect", label: "Inspected it" },
  { id: "other", label: "Other work" },
];

// The failure mode a picker's value names, in words ("" when none).
function modeName(target, mode) {
  const choice = mode?.choice || "";
  if (choice.startsWith("id:")) return (target.failure_modes || []).find((m) => m.id === choice.slice(3))?.text || "";
  if (choice.startsWith("text:")) return choice.slice(5);
  return choice === "new" ? (mode.typed || "").trim() : "";
}

export default function WorkDoneForm({
  wo, readings = [], onSubmit, onDone, heading = "Close it", submitLabel = "Close work order", busyLabel = "Closing…",
  notesLabel = "Closing notes (optional; the notes above are kept)", back = true,
}) {
  const [on, setOn] = useState(today());
  const [notes, setNotes] = useState("");
  const kinds = actionKinds(KINDS, wo);
  // A replacement can only be recorded at a position (an item's: where it's fitted now).
  const atPosition = wo.can_replace !== false;
  // Starts from the task's kind: a check is "Checked, nothing done", a fixed-interval task a replacement.
  // A work package's work order: its lines say what was done (a problem is recorded at its line's
  // position), so it starts with no action of its own.
  const lines = wo.package ? wo.lines || [] : null;
  // A breakdown (a corrective work order) starts at nothing: the person picks what was
  // done and, for a replacement, whether it failed (the Close button says what's missing).
  // Where each action is recorded: the work order's own position, or one inside it (the
  // seal inside the pump); the task's failure mode, when it's inside, is the starting point.
  const inside = lines ? [] : wo.inside_positions || [];
  const startWhere = wo.suggested_position_id || "";
  const [actions, setActions] = useState(lines ? [] : [{ kind: defaultCloseKind(wo), failed: defaultFailed(wo), where: startWhere }]);
  // Why Close can't be pressed yet, in words on the button: the package's lines, then each action.
  const blocker = (lines && closeBlocker(lines))
    || actions.map((a) => closeActionBlocker(a, {
      atPosition, modeReady: a.kind === "checked" || a.kind === "other" || (a.kind === "replace" && !a.failed) || failureModeReady(a.mode),
    })).find(Boolean) || "";
  const left = lines ? unanswered(lines) : [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const update = (i, patch) => setActions((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  // The parts the action's position lists, replacement first: what a replacement is picked from.
  const listedAt = (a) => partChoices(closeTarget(wo, a.where).suggested_parts).listed;
  const pickPart = (i, id) => {
    const pt = listedAt(actions[i]).find((x) => x.id === id);
    update(i, { part_id: id, from: pt ? mostStock(pt) : "" });
  };
  const removeAt = (i) => setActions((as) => as.filter((_, j) => j !== i));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = actions.map((a) => ({
        ...(a.kind === "other" || a.kind === "checked" || (a.kind === "replace" && !a.failed) ? {} : failureModeBody(a.mode)),
        ...(a.kind === "replace" ? { reason: replaceReason(a) } : {}),
        finding: a.kind === "inspect" ? a.finding || null : null,
        ...closeActionKind(a.kind),
        notes: a.notes || "",
        new_item: newItemBody(a),
        ...(a.where ? { position_id: a.where } : {}),
        ...(a.kind === "replace" && a.part_id ? { part_id: a.part_id, from_location_id: a.from || null } : {}),
      }));
      onDone(await onSubmit(closePayload({ actions: body, on, notes, readings, lines })));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="maint-head"><h2>{heading}</h2></div>
      {error && <div className="card error">{error}</div>}
      {atPosition && !lines && (
        <p className="lib-date">
          Fitted now{wo.position && wo.subject?.kind !== "position" ? ` at ${wo.position.name}` : ""}:{" "}
          {wo.fitted ? <strong>{wo.fitted.item?.name}</strong> : "nothing"}
          {wo.fitted?.item?.serial && ` (${wo.fitted.item.serial})`}
        </p>
      )}
      {actions.map((a, i) => {
        const target = closeTarget(wo, a.where);
        const listed = listedAt(a);
        return (
        <div key={i} className="maint-action">
          <div className="rcm-form">
            {inside.length > 0 && (
              <Field label="On">
                <select value={a.where || ""} onChange={(e) => update(i, { where: e.target.value, mode: null, part_id: "", from: "" })}>
                  <option value="">{wo.position?.name || wo.subject?.name} (this work order's)</option>
                  <optgroup label="Inside it">
                    {inside.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}{p.fitted?.item ? `: ${p.fitted.item.name}${p.fitted.item.serial ? ` (${p.fitted.item.serial})` : ""}` : ""}</option>
                    ))}
                  </optgroup>
                </select>
              </Field>
            )}
            <Field label="What was done">
              <select value={a.kind} onChange={(e) => update(i, { kind: e.target.value })}>
                {!a.kind && <option value="">Choose…</option>}
                {kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
            </Field>
            {a.kind === "inspect" && (
              <Field label="Finding">
                <select value={a.finding || ""} onChange={(e) => update(i, { finding: e.target.value })}>
                  <option value="">Choose…</option>
                  <option value="ok">OK</option>
                  <option value="degraded">Degraded</option>
                  <option value="found_failed">Found failed</option>
                </select>
              </Field>
            )}
            {a.kind === "replace" && atPosition && (
              <Field label="Did it fail?">
                <select value={a.failed == null ? "" : a.failed ? "yes" : "no"} onChange={(e) => update(i, { failed: e.target.value === "yes" })}>
                  {a.failed == null && <option value="">Choose…</option>}
                  <option value="yes">Yes, it failed</option>
                  <option value="no">No, a planned replacement</option>
                </select>
              </Field>
            )}
            {a.kind && a.kind !== "other" && a.kind !== "checked" && atPosition && (a.kind !== "replace" || a.failed) && (
              <Field label={a.kind === "replace" ? "Which way did it fail?" : "Failure mode (optional)"}>
                <FailureModePicker modes={target.failure_modes} classModes={target.class_failure_modes} value={a.mode}
                                   onChange={(mode) => update(i, { mode })}
                                   noneLabel={a.kind === "replace" ? "Not known" : "None"} />
              </Field>
            )}
            {a.kind === "replace" && listed.length > 0 && (
              <>
                <Field label="Part fitted (from the parts list)">
                  <select value={a.part_id || ""} onChange={(e) => pickPart(i, e.target.value)}>
                    <option value="">Not from the parts list</option>
                    {listed.map((pt) => <option key={pt.id} value={pt.id}>{partLabel(pt)}</option>)}
                  </select>
                </Field>
                {a.part_id && (
                  <Field label="Take it from stock at">
                    <StockPicker part={listed.find((x) => x.id === a.part_id)} value={a.from || ""}
                                 onChange={(from) => update(i, { from })} />
                  </Field>
                )}
              </>
            )}
            {a.kind === "replace" && (
              <>
                <Field label={a.part_id || target.fitted ? "New item (optional: named after the part or what it replaces)" : "New item"}>
                  <input value={a.new_name || ""}
                         placeholder={listed.find((x) => x.id === a.part_id)?.name || target.fitted?.item?.name || "e.g. Rheem 315 L"}
                         onChange={(e) => update(i, { new_name: e.target.value })} />
                </Field>
                <Field label="New item's serial (optional)">
                  <input value={a.new_serial || ""} onChange={(e) => update(i, { new_serial: e.target.value })} />
                </Field>
              </>
            )}
            <Field label="Notes (optional)">
              <input value={a.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} />
            </Field>
          </div>
          {a.kind === "replace" && atPosition && (
            <p className="lib-date" role="status">{replaceRecordText(a, target, modeName(target, a.mode))}</p>
          )}
          {a.kind === "inspect" && a.finding === "found_failed" && atPosition && (
            <p className="lib-date" role="status">{foundFailedText(target)}</p>
          )}
          {actions.length > 1 && <button className="secondary" onClick={() => removeAt(i)}>Remove this action</button>}
        </div>
        );
      })}
      <div className="maint-row">
        <button className="secondary" onClick={() => setActions((as) => [...as, { kind: "", failed: defaultFailed(wo), where: as[as.length - 1]?.where || startWhere }])}>{actions.length ? "Add another action" : "Add an action"}</button>
      </div>
      <div className="rcm-form">
        <Field label="Done on"><DateInput value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        {readings.length > 0 && (
          <p className="lib-date">Closing also records {readings.length === 1 ? "the value" : `the ${readings.length} values`} filled in under Readings and settings.</p>
        )}
        <Field label={notesLabel}><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <div className="maint-row">
        <button onClick={submit} disabled={busy || !!blocker}>
          {busy ? busyLabel : blocker || submitLabel}
        </button>
        {back && wo.subject && <Link to={subjectPath(wo.subject)} className="lib-date">Back to {wo.subject.name}</Link>}
      </div>
      {left.length > 0 && (
        <p className="lib-date">Still to answer under Lines: {left.slice(0, 5).join("; ")}{left.length > 5 ? ` and ${left.length - 5} more` : ""}.</p>
      )}
    </section>
  );
}

export function partLabel(pt) {
  return `${pt.part_number}: ${pt.name}${pt.note ? `, ${pt.note}` : ""} · ${stockText(pt)}`;
}

// The store holding the most of a part, if any: where a part is taken from by default.
export function mostStock(pt) {
  const best = [...(pt.stock || [])].sort((a, b) => b.quantity - a.quantity)[0];
  return best && best.quantity > 0 ? best.location.id : "";
}

// Where to take a part from: the stores holding it (with how many), then any other
// location; or leave stock as it is.
export function StockPicker({ part, places = [], value, onChange }) {
  const held = (part?.stock || []).filter((s) => s.quantity > 0);
  const heldIds = new Set(held.map((s) => s.location.id));
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Don't change stock</option>
      {held.map((s) => <option key={s.location.id} value={s.location.id}>{s.location.name} ({s.quantity} there)</option>)}
      {places.filter((l) => !heldIds.has(l.id)).map((l) => <option key={l.id} value={l.id}>{l.name} (none there)</option>)}
    </select>
  );
}
