import { useEffect, useState } from "react";
import { deleteMaintenanceItem } from "../api.js";
import { ITEM_DELETE_NOTE, itemDeleteButton, itemDeleteLines } from "../itemDelete.js";
import { FormModal } from "./MaintenanceParts.jsx";
import "./DeleteTree.css";

// Delete… on an item's page. The dialog asks the server first (a dry run): what goes
// with it (a built item's tree, its own tasks), or why it can't go yet (fitted
// elsewhere, open work orders, positions inside it in use), in the server's words.
// One click deletes it; the page then says it's deleted, with Restore.
export default function DeleteItemModal({ item, onClose, onDone }) {
  const [plan, setPlan] = useState(null);
  const [refused, setRefused] = useState(null);
  useEffect(() => {
    let live = true;
    deleteMaintenanceItem(item.id).then((p) => live && setPlan(p)).catch((e) => live && setRefused(e.message));
    return () => { live = false; };
  }, [item.id]);
  const lines = plan ? itemDeleteLines(plan) : [];
  return (
    <FormModal title={refused ? `“${item.name}” can't be deleted yet` : `Delete “${item.name}”?`} danger
               submitLabel={plan ? itemDeleteButton(plan) : "Delete the item"} pendingLabel="Deleting…"
               canSubmit={!!plan} onClose={onClose}
               onSubmit={async () => onDone(await deleteMaintenanceItem(item.id, { dryRun: false }))}>
      {refused && <p className="field-warning" role="alert">{refused}</p>}
      {!plan && !refused && <p className="lib-date" aria-live="polite">Checking what goes with it…</p>}
      {plan && (
        <div className="td-body" data-testid="delete-counts">
          {lines.length > 0 ? (
            <>
              <p>These go with it:</p>
              <ul className="td-list">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
            </>
          ) : <p>Only the item goes.</p>}
          <p className="lib-date">{ITEM_DELETE_NOTE}</p>
        </div>
      )}
    </FormModal>
  );
}
