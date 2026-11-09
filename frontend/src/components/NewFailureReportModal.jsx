import { useEffect, useState } from "react";
import { createFailureReport, getMaintenancePosition, updateFailureReport } from "../api.js";
import { failureModeBody, failureModeReady } from "../maintenanceModes.js";
import { SHORT_TEXT, tooLong } from "../maintenanceText.js";
import { CONSEQUENCES, defaultFoundBy, itemText } from "../failureReports.js";
import { useAuth } from "../AuthProvider.jsx";
import { FailureModePicker, Field, FormModal } from "./MaintenanceParts.jsx";

// A new failure report at a position (the tree's row menu "Add failure
// report…", or the Failure reports tab's button), or the same fields on one
// already filed (Edit…). What happened, the detail, when, who found it, the
// item fitted there (shown: the server keeps a copy of it with the report),
// the consequence, and the failure mode: one of the position's, or words for
// a new one. `today` is the workspace's day (the tree's); `user` the person
// signed in, whose name is who found it unless changed.
const DESCRIPTION_HINT = "put the detail below";

export default function NewFailureReportModal({ positionId, positionName, today, report = null, onClose, onDone }) {
  const { user } = useAuth();
  const editing = !!report;
  const [title, setTitle] = useState(report?.title || "");
  const [description, setDescription] = useState(report?.description || "");
  const [occurredOn, setOccurredOn] = useState(report?.occurred_on || today || "");
  const [foundBy, setFoundBy] = useState(editing ? (report.found_by || "") : defaultFoundBy(user));
  const [consequence, setConsequence] = useState(report?.consequence || "");
  const [mode, setMode] = useState(report?.failure_mode?.id ? { choice: `id:${report.failure_mode.id}`, typed: "" } : { choice: "", typed: "" });
  // The position's failure modes and what's fitted there.
  const [position, setPosition] = useState(null);
  const [positionError, setPositionError] = useState(null);
  useEffect(() => {
    let live = true;
    getMaintenancePosition(positionId)
      .then((p) => live && setPosition(p))
      .catch((e) => live && setPositionError(e.message));
    return () => { live = false; };
  }, [positionId]);

  const modes = position?.failure_modes || [];
  const classModes = position?.class_failure_modes || [];
  // A mode the report names that the position no longer lists (an ad-hoc one): kept as a choice.
  const extraMode = editing && report.failure_mode && !modes.some((m) => m.id === report.failure_mode.id)
    ? [{ id: report.failure_mode.id, text: report.failure_mode.text }] : [];
  const fitted = position?.fitted?.item || null;
  const itemLine = editing ? itemText(report.item) : fitted ? itemText({ ...fitted, exists: true }) : "";

  const canSubmit = !!title.trim() && !tooLong(title) && !!occurredOn && !tooLong(foundBy) && failureModeReady(mode);
  const submit = async () => {
    const modeBody = failureModeBody(mode);
    if (!editing) {
      onDone(await createFailureReport({
        position_id: positionId, title: title.trim(), description: description.trim(), occurred_on: occurredOn,
        found_by: foundBy.trim(), consequence: consequence || null, ...modeBody,
      }));
      return;
    }
    const changes = {};
    if (title.trim() !== (report.title || "")) changes.title = title.trim();
    if (description.trim() !== (report.description || "")) changes.description = description.trim();
    if (occurredOn !== (report.occurred_on || "")) changes.occurred_on = occurredOn;
    if (foundBy.trim() !== (report.found_by || "")) changes.found_by = foundBy.trim();
    if ((consequence || null) !== (report.consequence || null)) changes.consequence = consequence || null;
    const was = report.failure_mode?.id || null;
    if (modeBody.failure_mode_id !== was || modeBody.failure_mode_text) {
      if (modeBody.failure_mode_text) changes.failure_mode_text = modeBody.failure_mode_text;
      else changes.failure_mode_id = modeBody.failure_mode_id;
    }
    if (!Object.keys(changes).length) {
      onClose();
      return;
    }
    onDone(await updateFailureReport(report.id, changes));
  };

  return (
    <FormModal title={editing ? `Edit ${report.label}` : "New failure report"} submitLabel={editing ? "Save" : "Report it"}
               pendingLabel={editing ? "Saving…" : "Reporting…"} canSubmit={canSubmit} onClose={onClose} onSubmit={submit}>
      <p className="lib-date fr-modal-where">At <strong>{positionName || position?.name || "this position"}</strong></p>
      <Field label="What happened" text={title} max={SHORT_TEXT} hint={DESCRIPTION_HINT}>
        <input autoFocus value={title} placeholder="e.g. Seal leaking at the drive end" onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Details (optional)">
        <textarea rows={3} value={description} placeholder="What was seen, what was running, what was done at the time"
                  onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="fr-modal-row">
        <Field label="When">
          <input type="date" value={occurredOn} max={today || undefined} onChange={(e) => setOccurredOn(e.target.value)} />
        </Field>
        <Field label="Who found it" text={foundBy} max={SHORT_TEXT}>
          <input value={foundBy} placeholder="A name" onChange={(e) => setFoundBy(e.target.value)} />
        </Field>
      </div>
      <Field label="Item involved">
        <p className="fr-modal-item">
          {positionError ? <span className="lib-date">Couldn't read what's fitted: {positionError}</span>
            : !position && !editing ? <span className="lib-date">Loading…</span>
            : itemLine || <span className="lib-date">Nothing fitted at this position</span>}
        </p>
      </Field>
      <fieldset className="fr-radios">
        <legend>Consequence</legend>
        {CONSEQUENCES.map((c) => (
          <label key={c.id || "none"} className="fr-radio">
            <input type="radio" name="fr-consequence" value={c.id} checked={consequence === c.id}
                   onChange={() => setConsequence(c.id)} />
            <span>{c.label}</span>
          </label>
        ))}
      </fieldset>
      <Field label="Failure mode">
        {positionError && !editing ? <span className="lib-date">Couldn't read the position's failure modes.</span>
          : <FailureModePicker modes={[...extraMode, ...modes]} classModes={classModes} value={mode} onChange={setMode} />}
      </Field>
    </FormModal>
  );
}
