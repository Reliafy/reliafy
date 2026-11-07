import { useState } from "react";
import { logPositionEvent } from "../api.js";
import { SHORT_TEXT, tooLong } from "../maintenanceText.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";

// Log an event at a position (the tree's row menu "Log an event…", or the
// Summary tab's Work area): something that happened there, in your words (a
// storm, a lightning strike, an overflow), and the day. Every task on the
// position, or inside it, whose trigger names that event raises its work
// order (one per event: none while one is open). `today` is the workspace's
// day; onDone gets the server's answer ({event, work_orders_raised}).
export default function LogEventModal({ positionId, positionName, today, onClose, onDone }) {
  const [eventType, setEventType] = useState("");
  const [note, setNote] = useState("");
  const [when, setWhen] = useState(today || "");
  const canSubmit = !!eventType.trim() && !tooLong(eventType) && !!when;
  const submit = async () => {
    onDone(await logPositionEvent(positionId, { event_type: eventType.trim(), note: note.trim(), when }));
  };
  return (
    <FormModal title="Log an event" submitLabel="Log it" pendingLabel="Logging…" canSubmit={canSubmit}
               onClose={onClose} onSubmit={submit}>
      <p className="lib-date fr-modal-where">At <strong>{positionName || "this position"}</strong></p>
      <p className="lib-date">Tasks here, or inside it, set to run on this event raise their work orders.</p>
      <Field label="What happened" text={eventType} max={SHORT_TEXT}>
        <input autoFocus value={eventType} placeholder="e.g. Lightning strike" onChange={(e) => setEventType(e.target.value)} />
      </Field>
      <Field label="Details (optional)">
        <textarea rows={2} value={note} placeholder="e.g. Board tripped at 3 pm" onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Field label="When">
        <input type="date" value={when} max={today || undefined} onChange={(e) => setWhen(e.target.value)} />
      </Field>
    </FormModal>
  );
}
