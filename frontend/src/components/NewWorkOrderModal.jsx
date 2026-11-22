import { useState } from "react";
import { openWorkOrder } from "../api.js";
import { Field, FormModal, PositionPicker } from "./MaintenanceParts.jsx";
import { tooLong } from "../maintenanceText.js";
import { DateInput } from "./ui/DateTimeInput.jsx";
import { Select } from "./ui/Controls.jsx";

// A new work order on a position: what needs doing, its type and when it's due.
// On a position's page the position is that one (`positionId`); on the
// Maintenance page it's picked from `positions` ([{id, name, depth}]).
export default function NewWorkOrderModal({ positionId = null, positions = null, onClose, onDone }) {
  const [on, setOn] = useState(positionId);
  const [title, setTitle] = useState("");
  const [type, setType] = useState("corrective");
  const [due, setDue] = useState("");
  return (
    <FormModal title="New work order" submitLabel="Open work order" canSubmit={!!on && !!title.trim() && !tooLong(title)} onClose={onClose}
               onSubmit={async () => onDone(await openWorkOrder({ position_id: on, title, type, due: due || null }))}>
      {!positionId && positions && (
        <Field label="Position">
          <PositionPicker positions={positions} value={on} onChange={setOn} emptyLabel="Choose a position…" />
        </Field>
      )}
      <Field label="What needs doing" text={title} hint="add the detail to the notes once it's open">
        <input autoFocus={!!positionId} value={title} placeholder="e.g. No hot water" onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Type">
        <Select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="corrective">Corrective (something's wrong)</option>
          <option value="preventive">Preventive</option>
          <option value="inspection">Inspection</option>
          <option value="other">Other</option>
        </Select>
      </Field>
      <Field label="Due (optional)"><DateInput value={due} onChange={(e) => setDue(e.target.value)} /></Field>
    </FormModal>
  );
}
