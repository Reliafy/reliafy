import { useState } from "react";
import {
  retireMaintenancePosition, updateMaintenanceItem, updateMaintenanceLocation, updateMaintenancePosition,
} from "../api.js";
import { DESCRIPTION_HINT, tooLong } from "../maintenanceText.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";

// The dialogs behind the Explorer's row menu on the Summary tab
// (treeRowMenu.js): rename, move to another place in the tree, retire. Each
// writes through the same routes as the full pages (PATCH a position,
// location or item; retire a position), once (FormModal: the button disabled
// and saying "Renaming…", "Moving…" or "Retiring…" until the server answers),
// stays open with the server's reason if it refuses, and hands back what changed.

const KIND = { pos: "position", loc: "location", item: "item" };
const quoted = (s) => `“${String(s || "").slice(0, 80)}”`;

export function RenameModal({ row, onClose, onDone }) {
  const before = row.ref.name || "";
  const [name, setName] = useState(before);
  const kind = KIND[row.type];
  const save = (body) => (row.type === "pos" ? updateMaintenancePosition(row.key, body)
    : row.type === "loc" ? updateMaintenanceLocation(row.key, body) : updateMaintenanceItem(row.key, body));
  return (
    <FormModal title={`Rename this ${kind}`} submitLabel="Rename" pendingLabel="Renaming…" onClose={onClose}
               canSubmit={!!name.trim() && name.trim() !== before.trim() && !tooLong(name)}
               onSubmit={async () => {
                 await save({ name: name.trim() });
                 onDone(name.trim());
               }}>
      <Field label="Name" text={name} hint={row.type === "pos" ? DESCRIPTION_HINT : ""}>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               onFocus={(e) => e.target.select()} />
      </Field>
    </FormModal>
  );
}

// `targets`: where it may go ([{id, name, depth}], never itself nor anything
// inside it); `parentId`: where it is now.
export function MoveModal({ row, targets, parentId, onClose, onDone }) {
  const [to, setTo] = useState(parentId || "");
  const kind = KIND[row.type];
  const top = row.type === "loc" ? "Top level (an asset of its own)" : "Top level (inside nothing)";
  const nameOf = (id) => (id ? targets.find((t) => t.id === id)?.name : null);
  return (
    <FormModal title={`Move ${quoted(row.ref.name)}`} submitLabel="Move" pendingLabel="Moving…" onClose={onClose}
               canSubmit={(to || "") !== (parentId || "")}
               onSubmit={async () => {
                 const body = { parent_id: to || null };
                 if (row.type === "pos") await updateMaintenancePosition(row.key, body);
                 else await updateMaintenanceLocation(row.key, body);
                 onDone(nameOf(to));
               }}>
      <p className="lib-date">
        Everything inside it moves with it.
        {row.type === "pos" ? " Its RCM, tasks, history and what's fitted stay with it." : " The positions and spares there stay with it."}
      </p>
      <Field label={`Inside which ${kind}?`}>
        <select value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="">{top}</option>
          {targets.map((t) => (
            <option key={t.id} value={t.id}>{"  ".repeat(t.depth)}{t.name}{t.id === parentId ? " (where it is now)" : ""}</option>
          ))}
        </select>
      </Field>
    </FormModal>
  );
}

export function RetireModal({ row, onClose, onDone }) {
  return (
    <FormModal title={`Retire ${quoted(row.ref.name)}?`} submitLabel="Retire position" pendingLabel="Retiring…" onClose={onClose}
               onSubmit={async () => {
                 await retireMaintenancePosition(row.key, "");
                 onDone();
               }}>
      <p>
        It leaves the tree and its tasks stop being scheduled. Its history stays: past fitments, work orders and
        failures still name it.
      </p>
      <p className="lib-date">
        It can't be retired while something is fitted, a position inside it is still in use, or a work order on it
        is open.
      </p>
    </FormModal>
  );
}
