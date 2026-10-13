import { useState } from "react";
import Modal from "./Modal.jsx";

// Shared pieces for the Reliafy Maintenance pages.

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function today() {
  return new Date().toISOString().slice(0, 10);
}

// Every position in a tree, depth-first, with its depth (for pickers).
export function flatten(tree, depth = 0, out = []) {
  for (const node of tree || []) {
    out.push({ id: node.id, name: node.name, depth });
    flatten(node.children, depth + 1, out);
  }
  return out;
}

export function Field({ label, children }) {
  return (
    <label className="login-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function PositionPicker({ positions, value, onChange, emptyLabel = "None (top level)" }) {
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{emptyLabel}</option>
      {positions.map((p) => (
        <option key={p.id} value={p.id}>{"  ".repeat(p.depth)}{p.name}</option>
      ))}
    </select>
  );
}

// A modal with a form: `onSubmit` returns a promise; errors show in the modal.
export function FormModal({ title, submitLabel, onClose, onSubmit, canSubmit = true, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Modal
      title={title}
      locked={busy}
      onClose={onClose}
      footer={
        <>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={submit} disabled={busy || !canSubmit}>{busy ? "Saving…" : submitLabel}</button>
        </>
      }
    >
      {error && <div className="card error">{error}</div>}
      <div className="rcm-form">{children}</div>
    </Modal>
  );
}

export function DueChip({ task }) {
  if (task.by_use) return <span className="lib-date">by use (needs a meter)</span>;
  if (!task.next_due) return <span className="lib-date">—</span>;
  return (
    <span className={task.overdue ? "maint-overdue" : "lib-date"}>
      {fmtDate(task.next_due)}{task.overdue ? " (overdue)" : ""}
    </span>
  );
}

export const OUTCOME_LABELS = {
  fixed_interval: "Fixed-interval replacement",
  failure_finding: "Failure-finding",
  on_condition: "On-condition",
  rtf: "Run to failure",
  redesign: "Redesign",
  accept: "Accept",
};
