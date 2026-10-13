import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { decideProposal } from "../api.js";
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
  if (!task.next_due) {
    const note = (task.limits || []).map((l) => l.note).find(Boolean);
    return <span className="lib-date">{note || "—"}</span>;
  }
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

// The Maintenance section's own tabs.
export function MaintenanceTabs() {
  const tabs = [
    { to: "/maintenance", label: "Overview", end: true },
    { to: "/maintenance/items", label: "Items" },
    { to: "/maintenance/locations", label: "Locations" },
    { to: "/maintenance/parts", label: "Parts" },
    { to: "/maintenance/classes", label: "Classes" },
  ];
  return (
    <nav className="maint-tabs" aria-label="Maintenance">
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => (isActive ? "active" : "")}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function LifeTable({ rows, showPosition = false, onFix }) {
  return (
    <table className="lib-table">
      <thead>
        <tr>
          {showPosition && <th>Position</th>}
          <th>Item</th><th>In</th><th>Out</th><th>Days</th><th>Outcome</th><th>Failure mode</th>
          {onFix && <th><span className="sr-only">Fix</span></th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.fitment_id || `${r.from}-${r.item}`}>
            {showPosition && <td>{r.position}</td>}
            <td>{r.item}</td>
            <td className="lib-date">{fmtDate(r.from)}</td>
            <td className="lib-date">{fmtDate(r.to)}</td>
            <td>{r.x}</td>
            <td>{r.status}</td>
            <td className="lib-date">{r.failure_mode || "—"}</td>
            {onFix && <td><button className="crumb-link" onClick={() => onFix(r)}>Fix</button></td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function everyText(t) {
  const first = `${t.interval} ${t.unit}`;
  return t.also_interval ? `${first} or ${t.also_interval} ${t.also_unit}` : first;
}

// Proposed changes to the plan, each with its reason, to accept or reject.
export function Proposals({ proposals, onDecided, showPosition = true }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  if (!proposals?.length) return null;
  const decide = async (p, accept) => {
    setBusy(p.id);
    setError(null);
    try {
      await decideProposal(p.id, accept);
      onDecided?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="card maint-proposals">
      <div className="maint-head"><h2>Proposed changes</h2></div>
      {error && <div className="card error">{error}</div>}
      {proposals.map((p) => (
        <div key={p.id} className="maint-proposal">
          <p>
            <strong>{p.task?.name}</strong>
            {showPosition && p.position && <> on <Link to={`/maintenance/positions/${p.position.id}`}>{p.position.name}</Link></>}
            {": "}
            {p.kind === "interval"
              ? <>every {p.current.interval} {p.current.unit} → <strong>every {p.proposed.interval} {p.proposed.unit}</strong></>
              : <strong>stop scheduling it (run to failure)</strong>}
          </p>
          <p className="lib-date">{p.reason}</p>
          <div className="maint-row" style={{ marginTop: 0 }}>
            <button disabled={busy === p.id} onClick={() => decide(p, true)}>Accept</button>
            <button className="secondary" disabled={busy === p.id} onClick={() => decide(p, false)}>Reject</button>
          </div>
        </div>
      ))}
    </section>
  );
}
