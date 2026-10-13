import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { addMaintenanceDocument, decideProposal, removeMaintenanceDocument } from "../api.js";
import {
  DOCUMENT_KINDS, PRECISIONS, datedText, daysText, roughDateInput, roughDateValue, safeHref,
} from "../maintenanceFields.js";
import Modal from "./Modal.jsx";

// Shared pieces for the Reliafy Maintenance pages.

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// A date as it's known: "2022", "Mar 2022", "~Mar 2022", or the day.
export function fmtDated(iso, precision) {
  return datedText(iso, precision, fmtDate);
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

// A date that may be known only to the month or year, or estimated: its
// precision, and an input to match. `value` is {text, precision}; onChange gets
// the same, and `roughDateValue(text, precision)` is what to send.
export function RoughDateField({ label, value, onChange, max }) {
  const { text, precision } = value;
  const setPrecision = (next) => {
    const sent = roughDateValue(text, precision);
    const keep = next === "year" ? sent.slice(0, 4) : next === "month" ? (sent.length >= 7 ? sent.slice(0, 7) : "")
      : sent.length === 10 ? sent : "";
    onChange({ text: keep, precision: next });
  };
  const input = precision === "year"
    ? <input type="number" inputMode="numeric" min="1900" max="2199" placeholder="e.g. 2022" value={text}
             onChange={(e) => onChange({ text: e.target.value, precision })} />
    : precision === "month"
      ? <input type="month" placeholder="e.g. 2022-03" value={text} max={max ? max.slice(0, 7) : undefined}
               onChange={(e) => onChange({ text: e.target.value, precision })} />
      : <input type="date" value={text} max={max} onChange={(e) => onChange({ text: e.target.value, precision })} />;
  return (
    <Field label={label}>
      <div className="maint-row" style={{ marginTop: 0 }}>
        <select value={precision} aria-label={`${label}: how well it's known`} onChange={(e) => setPrecision(e.target.value)}>
          {PRECISIONS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        {input}
      </div>
    </Field>
  );
}

export function roughDate(day, precision) {
  return { text: roughDateInput(day, precision || "exact"), precision: precision || "exact" };
}

// Links to documents (manuals, datasheets, invoices) on an item, a position or a
// class. Only http(s) links open; they open in a new tab with no referrer.
export function DocumentsCard({ title = "Documents", documents, target, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ url: "", title: "", kind: "manual" });
  const [error, setError] = useState(null);
  const add = async () => {
    setError(null);
    try {
      await addMaintenanceDocument({ ...target, ...f });
      setAdding(false);
      setF({ url: "", title: "", kind: "manual" });
      onChanged?.();
    } catch (e) { setError(e.message); }
  };
  const remove = async (id) => {
    setError(null);
    try { await removeMaintenanceDocument(id); onChanged?.(); } catch (e) { setError(e.message); }
  };
  return (
    <section className="card">
      <div className="maint-head">
        <h2>{title}</h2>
        {!adding && <button className="secondary" onClick={() => setAdding(true)}>Add a link</button>}
      </div>
      {error && <div className="card error">{error}</div>}
      {adding && (
        <div className="maint-action">
          <div className="rcm-form">
            <Field label="Link (https://…)"><input autoFocus type="url" value={f.url} placeholder="https://example.com/manual.pdf"
                   onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
            <Field label="Title (optional)"><input value={f.title} placeholder="e.g. Owner's manual"
                   onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
            <Field label="Kind">
              <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {DOCUMENT_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </Field>
          </div>
          <div className="maint-row">
            <button onClick={add} disabled={!f.url.trim()}>Add</button>
            <button className="secondary" onClick={() => { setAdding(false); setError(null); }}>Cancel</button>
          </div>
        </div>
      )}
      {(documents || []).length === 0 ? (
        !adding && <p className="lib-date">No documents. Link the manual, datasheet or invoice (a web address).</p>
      ) : (
        <ul className="maint-list">
          {documents.map((d) => {
            const href = safeHref(d.url);
            return (
              <li key={d.id}>
                {href ? <a href={href} target="_blank" rel="noopener noreferrer">{d.title}</a> : d.title}
                <span className="lib-date"> · {d.kind}</span>{" "}
                <button className="crumb-link" onClick={() => remove(d.id)}>remove</button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
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
    }
    // A step that keeps the dialog open (check, then import) needs the button back.
    setBusy(false);
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
    <div className="maint-scroll"><table className="lib-table">
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
            <td className="lib-date">{fmtDated(r.from, r.from_precision)}</td>
            <td className="lib-date">{fmtDated(r.to, r.to_precision)}</td>
            <td title={r.xl != null ? "The dates are known only roughly: the shortest and longest life they allow" : undefined}>
              {daysText(r)}</td>
            <td>{r.status}</td>
            <td className="lib-date">{r.failure_mode || "—"}</td>
            {onFix && <td><button className="crumb-link" onClick={() => onFix(r)}>Fix</button></td>}
          </tr>
        ))}
      </tbody>
    </table></div>
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

// Notes on an item or work order: read them, add a dated line without retyping
// the rest (onAppend), and look back at every change (a replaced note included).
export function NotesCard({ notes, history = [], onAppend, title = "Notes", canAppend = true }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const add = async () => {
    setBusy(true); setError(null);
    try { await onAppend(text.trim()); setText(""); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const changes = [...history].reverse();
  return (
    <section className="card">
      <div className="maint-head"><h2>{title}</h2></div>
      {error && <div className="card error">{error}</div>}
      {notes ? <p className="maint-notes">{notes}</p> : <p className="lib-date">No notes yet.</p>}
      {canAppend && (
        <div className="maint-row">
          <textarea rows={2} value={text} placeholder="Add a note (dated today; the rest is kept)"
                    aria-label="Add a note" onChange={(e) => setText(e.target.value)} style={{ flex: 1 }} />
          <button className="secondary" onClick={add} disabled={busy || !text.trim()}>{busy ? "Adding…" : "Add note"}</button>
        </div>
      )}
      {changes.length > 1 && (
        <details className="maint-note-history">
          <summary className="lib-date">Every change, newest first ({changes.length})</summary>
          <ul className="maint-list">
            {changes.map((h, i) => (
              <li key={i}>
                <span className="lib-date">{h.on ? fmtDate(h.on) : "date not recorded"} · {h.change === "appended" ? "added" : "set to"}</span>
                <div className="maint-notes">{h.text || <em className="lib-date">(cleared)</em>}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// How something failed: the position's modes, those seen at like positions
// (same class), or "something else" typed in. value is { choice, typed } (see
// maintenanceModes.js for turning it into request fields).
export function FailureModePicker({ modes = [], classModes = [], value, onChange, noneLabel = "Not known" }) {
  const v = value || { choice: "", typed: "" };
  return (
    <>
      <select value={v.choice} onChange={(e) => onChange({ ...v, choice: e.target.value })}>
        <option value="">{noneLabel}</option>
        {modes.length > 0 && (
          <optgroup label="This position's failure modes">
            {modes.map((m) => <option key={m.id} value={`id:${m.id}`}>{m.text}</option>)}
          </optgroup>
        )}
        {classModes.length > 0 && (
          <optgroup label="Seen at like positions">
            {classModes.map((t) => <option key={t} value={`text:${t}`}>{t}</option>)}
          </optgroup>
        )}
        <option value="new">Something else (describe it)…</option>
      </select>
      {v.choice === "new" && (
        <input autoFocus value={v.typed || ""} placeholder="e.g. Seal leaking" style={{ marginTop: "0.4rem" }}
               onChange={(e) => onChange({ ...v, typed: e.target.value })} />
      )}
    </>
  );
}

export const TASK_SOURCES = {
  manual: "Own practice", oem: "Maker's recommendation (OEM)", statutory: "Law, regulation or standard",
  other: "Other", rcm: "RCM study",
};
