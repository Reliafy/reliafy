import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  addMaintenanceDocument, decideProposal, getMaintenanceDocumentBlob, removeMaintenanceDocument,
  uploadMaintenanceDocument,
} from "../api.js";
import {
  DOCUMENT_KINDS, MAX_DOCUMENT_MB, PRECISIONS, datedText, daysText, documentFileProblem, fileSizeText,
  roughDateInput, roughDateValue, safeHref,
} from "../maintenanceFields.js";
import { locationOptions } from "../maintenanceLocations.js";
import { SHORT_TEXT, lengthNote } from "../maintenanceText.js";
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

// Today in the workspace's time zone (what the server dates things by).
export { workspaceToday as today } from "../workspaceDate.js";

// Every position in a tree, depth-first, with its depth (for pickers).
export function flatten(tree, depth = 0, out = []) {
  for (const node of tree || []) {
    out.push({ id: node.id, name: node.name, depth });
    flatten(node.children, depth + 1, out);
  }
  return out;
}

// `text`: the input's value, for a field with a length limit (a name or a title):
// a count shows as it nears `max`, and past it, what to do (`hint`).
export function Field({ label, children, text, max = SHORT_TEXT, hint }) {
  const note = text === undefined ? null : lengthNote(text, max, hint);
  return (
    <label className="login-field">
      <span>{label}</span>
      {children}
      {note && <small className={note.over ? "maint-length maint-length-over" : "maint-length"}
                      role={note.over ? "alert" : undefined}>{note.text}</small>}
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

// A PDF kept in the workspace, in the browser's own PDF viewer: fetched with the
// session (the file route needs it), shown from a blob URL in a frame, with
// "Open in a new tab" and "Download". Phones (which often won't show a PDF in
// a frame) get the buttons and a note instead.
export function DocumentViewer({ doc, onClose }) {
  const [url, setUrl] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    let made = null;
    getMaintenanceDocumentBlob(doc.id)
      .then((blob) => {
        made = URL.createObjectURL(blob);
        if (alive) setUrl(made);
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
      // A tab opened from it may still be reading it: let it go a minute later.
      if (made) setTimeout(() => URL.revokeObjectURL(made), 60_000);
    };
  }, [doc.id]);
  const name = doc.file_name || `${doc.title || "document"}.pdf`;
  const download = () => {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  return (
    <Modal title={doc.title || "Document"} onClose={onClose} className="modal-xl maint-pdf-modal"
           footer={<>
             <button className="secondary" disabled={!url} onClick={() => window.open(url, "_blank", "noopener")}>
               Open in a new tab
             </button>
             <button className="secondary" disabled={!url} onClick={download}>Download</button>
             <button onClick={onClose}>Close</button>
           </>}>
      <p className="lib-date maint-pdf-meta">
        {[doc.kind, fileSizeText(doc.size), doc.added_on && `added ${fmtDate(doc.added_on)}`].filter(Boolean).join(" · ")}
      </p>
      {error ? <div className="card error">{error}</div>
        : !url ? <p className="lib-date" role="status">Loading the PDF…</p>
          : <iframe className="maint-pdf-frame" src={url} title={`PDF: ${doc.title || name}`} />}
      {url && (
        <p className="lib-date maint-pdf-phone">
          On a phone, use Open in a new tab to read it in your phone's PDF viewer, or Download to keep a copy.
        </p>
      )}
    </Modal>
  );
}

// Documents (manuals, datasheets, invoices) on an item, a position or a class:
// links to web addresses, and PDFs kept here (opened in the viewer). Only
// http(s) links open; they open in a new tab with no referrer.
export function DocumentsCard({ title = "Documents", documents, target, onChanged }) {
  const blank = { url: "", title: "", kind: "manual", file: null };
  const [adding, setAdding] = useState(null); // "pdf" | "link" | null
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const fileProblem = adding === "pdf" && f.file ? documentFileProblem(f.file) : null;
  const close = () => { setAdding(null); setF(blank); setError(null); };
  const add = async () => {
    setError(null);
    setBusy(true);
    try {
      if (adding === "pdf") {
        await uploadMaintenanceDocument(target, f.file, { title: f.title, kind: f.kind });
      } else {
        await addMaintenanceDocument({ ...target, url: f.url, title: f.title, kind: f.kind });
      }
      close();
      onChanged?.();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const remove = async (id) => {
    setError(null);
    setConfirming(null);
    try { await removeMaintenanceDocument(id); onChanged?.(); } catch (e) { setError(e.message); }
  };
  const ready = adding === "pdf" ? !!f.file && !fileProblem : !!f.url.trim();
  return (
    <section className="card">
      <div className="maint-head">
        <h2>{title}</h2>
        {!adding && (
          <div className="maint-row" style={{ marginTop: 0 }}>
            <button className="secondary" onClick={() => setAdding("link")}>Add a link</button>
            <button onClick={() => setAdding("pdf")}>Add a PDF</button>
          </div>
        )}
      </div>
      {error && <div className="card error">{error}</div>}
      {adding && (
        <div className="maint-action">
          <div className="rcm-form">
            {adding === "pdf" ? (
              <Field label={`PDF file (at most ${MAX_DOCUMENT_MB} MB)`}>
                <input autoFocus type="file" accept="application/pdf,.pdf"
                       onChange={(e) => setF({ ...f, file: e.target.files?.[0] || null })} />
              </Field>
            ) : (
              <Field label="Link (https://…)"><input autoFocus type="url" value={f.url} placeholder="https://example.com/manual.pdf"
                     onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
            )}
            <Field label="Title (optional)"><input value={f.title}
                   placeholder={adding === "pdf" ? "Default: the file name" : "e.g. Owner's manual"}
                   onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
            <Field label="Kind">
              <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {DOCUMENT_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </Field>
          </div>
          {fileProblem && <p className="maint-overdue" role="alert">{fileProblem}</p>}
          <div className="maint-row">
            <button onClick={add} disabled={!ready || busy}>{busy ? "Uploading…" : adding === "pdf" ? "Upload" : "Add"}</button>
            <button className="secondary" onClick={close} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
      {(documents || []).length === 0 ? (
        !adding && <p className="lib-date">No documents. Add the manual, datasheet or invoice: a PDF, or a link to one.</p>
      ) : (
        <ul className="maint-list maint-docs">
          {documents.map((d) => {
            const href = d.stored ? null : safeHref(d.url);
            return (
              <li key={d.id}>
                {d.stored
                  ? <button className="link maint-doc-title" onClick={() => setViewing(d)}>{d.title}</button>
                  : href ? <a href={href} target="_blank" rel="noopener noreferrer">{d.title}</a> : d.title}
                <span className="lib-date">
                  {" "}· {d.kind}{d.stored ? ` · PDF, ${fileSizeText(d.size)}` : " · link"}
                </span>{" "}
                {confirming === d.id ? (
                  <span className="maint-confirm" role="group" aria-label={`Remove ${d.title}?`}>
                    <span>{d.stored ? "Remove it? The PDF is deleted." : "Remove this link?"}</span>
                    <button className="sm danger secondary" autoFocus onClick={() => remove(d.id)}>Remove</button>
                    <button className="sm secondary" onClick={() => setConfirming(null)}>Keep</button>
                  </span>
                ) : (
                  <button className="crumb-link" onClick={() => setConfirming(d.id)}
                          aria-label={`Remove ${d.title}`}>remove</button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {viewing && <DocumentViewer doc={viewing} onClose={() => setViewing(null)} />}
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

// A location, by its full path (Site › Area X › Substation 2).
export function LocationPicker({ locations, value, onChange, emptyLabel = "Choose…" }) {
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{locations === null ? "Loading…" : emptyLabel}</option>
      {locationOptions(locations).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}

// A modal with a form: `onSubmit` returns a promise; errors show in the modal.
// Sent once: while it's in flight the button is disabled and says
// `pendingLabel` (default "Saving…"), and a second click, double-click or
// Enter sends nothing more (a ref, set before React draws again). A refusal
// shows in the modal, in the server's words, or what to do when there was no
// answer at all.
export function FormModal({ title, submitLabel, pendingLabel = "Saving…", onClose, onSubmit, canSubmit = true, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const inFlight = useRef(false);
  const submit = async () => {
    if (inFlight.current || !canSubmit) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
    } catch (err) {
      const msg = err?.message || "";
      setError(!msg || msg === "Failed to fetch" || /NetworkError|Load failed/i.test(msg)
        ? "Couldn't save: check your connection and try again." : msg);
    }
    // A step that keeps the dialog open (check, then import) needs the button back.
    inFlight.current = false;
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
          <button onClick={submit} disabled={busy || !canSubmit} aria-busy={busy || undefined}>{busy ? pendingLabel : submitLabel}</button>
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
            {showPosition && p.position && <> on <Link to={`/asset-register/positions/${p.position.id}`}>{p.position.name}</Link></>}
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
