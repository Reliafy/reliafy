import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import RcmStatusBadge from "./RcmStatusBadge.jsx";
import { Highlight } from "./OutlineBits.jsx";
import { ancestorsOf } from "../outlineTree.js";
import {
  COLUMN, COLUMNS, CONSEQUENCE_LABEL, DEFAULT_COLUMNS, FUNCTION_MAX, FUNCTION_NUDGE, LEVEL_OF, NAME_COLUMN, functionCount,
  belowDecisionText, belowOf, belowPending, phoneLine, consequenceWords, failuresOn, checkCounts, decisionText, insideWords,
  intervalText, nameOf, shownStatus,
} from "../rcmWorksheet.js";
import { charCount } from "../maintenanceText.js";
import RcmBasis from "./RcmBasis.jsx";
import { plainFirstLine } from "../basisMarkdown.js";
import { CausedBySection, CausesSection } from "./FailureLinks.jsx";
import "./RcmWorksheet.css";

// The RCM worksheet's pieces, drawn by the Explorer's RCM tab (the asset tree
// and the RCM as one table, TreePane): the level icons, a cell and its
// tooltip, the cell editor (a double-click edits the commonest cells in
// place: description, effects, consequence, task, interval, notes, checked as
// the server checks them), a row's status on a phone, the details panel (every
// field of the row, adding inside it, deleting it, and the failure mode's
// decision dialog) and the column chooser. Edits are written at once (Details'
// `ops`); a refused value stays in the cell with the reason.
//
// On a phone the details panel opens as a sheet.

const ICONS = {
  fn: <path d="M3 3.5h10v9H3z M6.5 6v4l3.5-2z" strokeWidth="1.4" strokeLinejoin="round" />,
  fail: <><path d="M8 2.2 14.2 13H1.8z" strokeWidth="1.4" strokeLinejoin="round" /><path d="M8 6.5v3" strokeWidth="1.6" strokeLinecap="round" /><circle cx="8" cy="11.2" r=".9" fill="currentColor" stroke="none" /></>,
  mode: <path d="M9.2 1.8 3.8 9h4l-1 5.2L12.2 7h-4z" strokeWidth="1.4" strokeLinejoin="round" />,
  cause: <path d="M4 2.5v6a2 2 0 0 0 2 2h6M9.5 7.5l3 3-3 3" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />,
  task: <path d="M10.6 2.3a3.2 3.2 0 0 0-3.9 4.1L2.4 10.7a1.4 1.4 0 0 0 2 2l4.3-4.3a3.2 3.2 0 0 0 4.1-3.9l-1.9 1.9-1.8-.4-.4-1.8z" strokeWidth="1.3" strokeLinejoin="round" />,
};

export function LevelIcon({ type, className = "rw-ic" }) {
  return (
    <svg className={className} viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">
      {ICONS[type]}
    </svg>
  );
}

export { phoneLine };
const CHECK_MARK = { contradicted: "✗", unsure: "?", stale: "–", supported: "✓" };

const n = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;

// A cell's tooltip: its whole text (a long one is cut short in the cell),
// else, for an empty cell that can be edited, how to edit it. The edit hint
// for a cell with text is in `cellHint` (its aria-description), not over the
// text.
export function cellTip(col, r, can) {
  const text = col.text(r);
  if (text) return r.type === "mode" && col.id === "decision" && r.ref.decision?.notes ? `${text}: ${r.ref.decision.notes}` : text;
  return can ? "Double-click to edit" : undefined;
}
export const cellHint = (can) => (can ? "Double-click to edit" : undefined);

// The (i) beside a function's standard (or its name, when the standard column
// is hidden) when the standard has a working behind it. It opens the details
// panel with the working in full. A letter, a label and a tooltip: never
// colour alone. Fixed size, so a row never changes height or width with it.
export function BasisInfo({ r, onBasis }) {
  if (!onBasis || r.type !== "fn" || !r.ref.has_basis) return null;
  const first = plainFirstLine(r.ref.basis_preview, 80);
  return (
    <button type="button" className="rw-info" aria-label="This standard has a working: open it"
            title={`How this standard was worked out${first ? `: ${first}` : ""}. Open the working.`}
            onDoubleClick={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); if (e.detail < 2) onBasis(r); }}>
      <span aria-hidden="true">i</span>
    </button>
  );
}

// One cell's content (desktop).
export function Cell({ col, r, query, onDecision, readOnly, linkChecks, onBasis }) {
  const d = r.ref.decision;
  const mode = r.type === "mode";
  switch (col.id) {
    case "decision":
      if (mode) {
        if (!d) {
          return readOnly ? <span className="rw-todo">To decide</span> : (
            <button type="button" className="rw-todo rw-todo-btn" onClick={(e) => { e.stopPropagation(); if (e.detail < 2) onDecision(r); }}
                    title="Choose the decision for this failure mode">To decide</button>
          );
        }
        return <span className="rw-txt" title={[decisionText(d), d.notes].filter(Boolean).join(": ")}>{decisionText(d)}</span>;
      }
      {
        const own = r.sum.modes ? (r.sum.undecided
          ? <span className="rw-sum rw-todo" title={`${n(r.sum.undecided, "failure mode")} inside with no decision yet`}>{r.sum.undecided.toLocaleString("en-AU")} to decide</span>
          : <span className="rw-sum rw-done">All decided</span>) : null;
        // A functional failure caused by lower ones (the Explorer): what's decided
        // below, beside its own, never added into it. Short beside its own (the
        // column is narrow); the whole words are in its tooltip.
        const bp = belowOf(r) ? belowPending(r) : false;
        const bb = belowOf(r);
        const below = bb ? (
          <span className={"rw-sum rw-below" + (bp ? " rw-todo" : "")} title={cellTip(col, r, false)}>
            {own ? `· ${bp ? (bb.undecided ? `${bb.undecided.toLocaleString("en-AU")} below` : "not done below") : "below"}` : belowDecisionText(r)}
          </span>
        ) : null;
        if (!own && !below) return null;
        return <>{own}{below}</>;
      }
    case "check":
      // linkChecks (the Explorer): the chip opens the model or analysis behind it.
      if (mode && linkChecks && d?.status && d.artifact_link_path) {
        return (
          <Link to={d.artifact_link_path} className="rw-cklink" onClick={(e) => e.stopPropagation()}
                title={`${d.artifact_name || "The evidence"}: ${d.summary || d.reason || ""}`.trim()}>
            <RcmStatusBadge status={d.status} />
          </Link>
        );
      }
      if (mode && d?.status === "unevidenced") {
        // Nothing linked yet: quiet, not a warning (most RCM is done from judgement).
        return <span className="rw-quiet" title="No evidence linked yet"><span aria-hidden="true">–</span><span className="sr-only">No evidence linked yet</span></span>;
      }
      if (mode) return d?.status ? <RcmStatusBadge status={d.status} /> : null;
      // One kind inside: in words ("4 to check"); more: a mark and a count each.
      if (checkCounts(r).length === 1) {
        const [c] = checkCounts(r);
        return <span className={`rw-ck ${c.kind}`} title={`${c.n} ${c.label} inside`}>{CHECK_MARK[c.kind]} {c.n} {c.label}</span>;
      }
      return (
        <span className="rw-checks">
          {checkCounts(r).map((c) => (
            <span key={c.kind} className={`rw-ck ${c.kind}`} title={`${c.n} ${c.label} inside`}>
              <span aria-hidden="true">{CHECK_MARK[c.kind]}{c.n}</span>
              <span className="sr-only">{c.n} {c.label}</span>
            </span>
          ))}
        </span>
      );
    case "evidence":
      return mode && d?.artifact_name ? (
        d.artifact_link_path
          ? <Link to={d.artifact_link_path} className="rw-txt" onClick={(e) => e.stopPropagation()}>{d.artifact_name}</Link>
          : <span className="rw-txt">{d.artifact_name}</span>
      ) : null;
    case "task": {
      const text = col.text(r);
      if (!text) return null;
      return mode
        ? <span className="rw-txt rw-task" title={text}><LevelIcon type="task" className="rw-ic rw-ic-task" /><span className="rw-task-t"><Highlight text={text} query={query} /></span></span>
        : <span className="rw-sum">{text}</span>;
    }
    case "standard": {
      const text = col.text(r);
      const info = <BasisInfo r={r} onBasis={onBasis} />;
      if (!text) return info;
      return (
        <span className="rw-withinfo">
          <span className="rw-txt" title={text}><Highlight text={text} query={query} /></span>
          {info}
        </span>
      );
    }
    default: {
      const text = col.text(r);
      if (!text) return null;
      const sum = !mode && (col.id === "consequence" || col.id === "evident");
      const title = sum && col.id === "consequence" ? consequenceWords(r) : text;
      return <span className={sum ? "rw-sum" : "rw-txt"} title={title}>
        {col.edit === "text" ? <Highlight text={text} query={query} /> : text}
      </span>;
    }
  }
}

// A cell being edited in place: Enter or leaving it keeps the change; Escape
// drops it. A value the server would refuse stays open with the reason.
// `onCommit` returns true (kept), the reason it isn't (a string), or a promise
// of either (the Explorer writes at once): meanwhile the cell keeps the text
// as typed (read-only, so it's sent once), and if it isn't saved it stays open
// with that text, to try again or Escape.
export function CellEditor({ col, r, onCommit, onCancel }) {
  const d = r.ref.decision || {};
  const start = col.id === "name" ? r.ref.text || ""
    : col.id === "consequence" ? r.ref.consequence || ""
    : col.id === "interval" ? d.interval ?? ""
    : COLUMN[col.id]?.onDecision ? d[COLUMN[col.id].field] || "" : r.ref[COLUMN[col.id].field] || "";
  const [value, setValue] = useState(String(start));
  const [busy, setBusy] = useState(false);
  const done = useRef(false);
  const field = useRef(null);
  const commit = (v = value) => {
    if (done.current) return;
    if (String(v) === String(start)) { done.current = true; onCancel(); return; }
    const out = onCommit(v);
    if (out === true) done.current = true;
    else if (out && typeof out.then === "function") {
      done.current = true;
      setBusy(true);
      out.then((ok) => {
        if (ok === true) return;
        done.current = false;
        setBusy(false);
        field.current?.focus({ preventScroll: true });
      });
    }
  };
  const keys = (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") { e.preventDefault(); done.current = true; onCancel(); }
  };
  const label = `${col.label} of ${nameOf(r) || LEVEL_OF[r.type].label.toLowerCase()}`;
  if (col.id === "consequence") {
    return (
      <select className="rw-edit" autoFocus ref={field} value={value} aria-label={label} onKeyDown={keys} disabled={busy}
              onChange={(e) => { setValue(e.target.value); commit(e.target.value); }} onBlur={() => commit()}>
        <option value="">Not set</option>
        {Object.entries(CONSEQUENCE_LABEL).map(([id, l]) => <option key={id} value={id}>{l}</option>)}
      </select>
    );
  }
  // A function's text: kept to 200 characters, with a counter at its end.
  const count = col.id === "name" && r.type === "fn" ? functionCount(value, r.ref.text || "") : null;
  return (
    <span className="rw-edit-wrap">
      <input className="rw-edit" autoFocus ref={field} aria-label={label} value={value} onKeyDown={keys} readOnly={busy} aria-busy={busy || undefined}
             maxLength={count ? FUNCTION_MAX : undefined} title={count ? FUNCTION_NUDGE : undefined}
             aria-description={count ? `${count.n} of ${count.max} characters. ${FUNCTION_NUDGE}` : undefined}
             aria-invalid={count?.over ? "true" : undefined}
             type={col.id === "interval" ? "number" : "text"} inputMode={col.id === "interval" ? "decimal" : undefined}
             min={col.id === "interval" ? "0" : undefined} step={col.id === "interval" ? "any" : undefined}
             onChange={(e) => setValue(e.target.value)} onBlur={() => commit()} />
      {col.id === "interval" && <span className="rw-unit">{d.interval_unit || "hours"}</span>}
      {count && <span className={"char-count rw-count" + (count.tone ? ` ${count.tone}` : "")} aria-hidden="true">{count.text}</span>}
    </span>
  );
}

// A row's status on a phone: a mode's evidence check, a parent's count to look at.
export function PhoneStatus({ r }) {
  if (r.type === "mode") {
    const s = shownStatus(r.ref.decision?.status);
    return s ? <RcmStatusBadge status={s} /> : null;
  }
  if (r.sum.contradicted) return <span className="rw-ck contradicted">✗{r.sum.contradicted}<span className="sr-only"> contradicted</span></span>;
  if (r.sum.undecided) return <span className="rw-sum rw-todo">{r.sum.undecided} to decide</span>;
  return null;
}

// The details panel for the row picked: every field, the decision, adding
// inside and deleting.
// The kinds of row whose description is edited (not a position's, nor the
// unassigned failure modes' heading, in the Explorer).
export const EDITABLE = new Set(["fn", "fail", "mode"]);

// With `ops` (the Explorer), a failure mode can be put under another of its
// position's functional failures.
export function Details({ r, display, readOnly, onCommit, onAdd, onDelete, onDecision, onClose, onSelect, phone, headingRef, ops, links }) {
  const level = LEVEL_OF[r.type];
  const d = r.ref.decision;
  const up = ancestorsOf(display, r.key).map((k) => display.rows.get(k));
  const field = (label, col, { area, help, limit } = {}) => {
    const column = col === "name" ? NAME_COLUMN : COLUMN[col];
    const value = col === "name" ? r.ref.text || "" : column.onDecision ? d?.[column.field] ?? "" : r.ref[column.field] || "";
    return (
      <Field key={`${r.key}:${col}`} label={label} help={help} value={value} area={area} readOnly={readOnly} limit={limit}
             type={col === "interval" ? "number" : "text"} suffix={col === "interval" ? d?.interval_unit || "hours" : null}
             onCommit={(raw) => onCommit(r, col, raw)} autoFocus={col === "name" && !r.ref.text && !readOnly} />
    );
  };
  return (
    <aside className={"rw-panel" + (phone ? " sheet" : "")} aria-label="Details"
           onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
      <div className="rw-panel-head">
        <div className="rw-panel-kind"><LevelIcon type={r.type} /> {level.label}</div>
        <button type="button" className="secondary rw-x" onClick={onClose} aria-label="Close the details">Close</button>
      </div>
      {up.length > 0 && (
        <nav className="rw-crumbs" aria-label="Inside">
          {up.map((a) => (
            <button key={a.key} type="button" className="link" onClick={() => onSelect(a.key)}
                    title={nameOf(a) || undefined}>
              {nameOf(a) || `(${LEVEL_OF[a.type].label.toLowerCase()})`}
            </button>
          ))}
        </nav>
      )}
      <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef} title={nameOf(r).length > 80 ? nameOf(r) : undefined}>
        {nameOf(r) || <span className="rw-blank">(no description yet)</span>}
      </h2>
      {r.type !== "mode" && <p className="rw-inside">{insideWords(r)}</p>}

      <div className="rw-fields">
        {EDITABLE.has(r.type) && field("Description", "name", {
          area: true,
          help: r.type === "fn" ? (ops ? "What this position must do" : "What the system must do") : r.type === "fail" ? "How it fails to do it" : "What causes the failure",
          limit: r.type === "fn" ? { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE } : null,
        })}
        {r.type === "fn" && field("Performance standard", "standard", { help: "Optional, e.g. within 30 m from 60 km/h" })}
        {r.type === "mode" && field("Failure effects", "effects", { area: true })}
        {r.type === "mode" && (
          <label className="rw-field">
            <span className="rw-flabel">Consequence</span>
            {readOnly ? <span className="rw-fval">{CONSEQUENCE_LABEL[r.ref.consequence] || "Not set"}</span> : (
              <select value={r.ref.consequence || ""} onChange={(e) => onCommit(r, "consequence", e.target.value)}>
                <option value="">Not set</option>
                {Object.entries(CONSEQUENCE_LABEL).map(([id, l]) => <option key={id} value={id}>{l}</option>)}
              </select>
            )}
          </label>
        )}
        {r.type === "mode" && field("Mode notes", "notes", { area: true })}
        {r.type === "mode" && ops && (
          <label className="rw-field">
            <span className="rw-flabel">Under</span>
            {readOnly ? <span className="rw-fval">{display.rows.get(r.parent)?.ref.text}</span> : (
              <select value={r.ref.functional_failure_id || ""} onChange={(e) => ops.assign(r, e.target.value || null)}>
                <option value="">No functional failure yet</option>
                {failuresOn(display, r.ref.position_id).map((f) => (
                  <option key={f.id} value={f.id}>{f.function ? `${f.function} › ` : ""}{f.text}</option>
                ))}
              </select>
            )}
            {r.ref.was_under && !r.ref.functional_failure_id && <span className="rw-fhelp">It was noted as under: {r.ref.was_under}</span>}
          </label>
        )}
      </div>

      {/* The panel's order: Description → (function: Performance standard → Working behind it) /
          (failure: Caused by below → Causes above) → the actions. */}
      {r.type === "fn" && ops?.basis && (
        <RcmBasis r={r} basis={ops.basis} readOnly={readOnly} context={ops.basisView?.context(r)}
                  openToken={ops.basisView?.token(r)} />
      )}

      {r.type === "mode" && (
        <section className="rw-decision" aria-label="Decision">
          <h3>Decision</h3>
          {d ? (
            <>
              <p className="rw-dline"><b>{decisionText(d)}</b>{d.interval ? ` · every ${intervalText(d)}` : ""}</p>
              {COLUMN.task.can(r) && field("Task", "task", { area: true })}
              {COLUMN.interval.can(r) && field("Interval", "interval")}
              {field("Decision notes", "dnotes", { area: true })}
              {d.status === "unevidenced" ? (
                // Nothing linked: a gentle way to link it, not a warning.
                <p className="rw-evidence rw-unlinked">
                  No evidence linked yet{readOnly ? "." : ": "}
                  {!readOnly && (
                    <button type="button" className="link" onClick={() => onDecision(r)}
                            title="Link the saved model or analysis behind this decision (optional)">Link evidence…</button>
                  )}
                </p>
              ) : (
              <div className="rw-evidence">
                {d.status && <RcmStatusBadge status={d.status} />}
                {d.artifact_name && (d.artifact_link_path
                  ? <Link to={d.artifact_link_path}>{d.artifact_name}</Link> : <span>{d.artifact_name}</span>)}
                {(d.summary || d.reason) && <p>{d.summary || d.reason}</p>}
              </div>
              )}
            </>
          ) : <p className="rw-dline">No decision yet.</p>}
          {!readOnly && (
            <button type="button" className={d ? "secondary" : ""} onClick={(e) => { if (e.detail < 2) onDecision(r); }}>
              {d ? "Change the decision…" : "Decide…"}
            </button>
          )}
        </section>
      )}

      {/* Order of the panel: Description, then (function) its standard and basis, or (failure) Caused by below
          and Causes above, then the actions. */}
      {r.type === "fail" && ops && links && (
        <CausedBySection r={r} where={display.rows.get(r.ref.position_id)?.ref.name} readOnly={readOnly} links={links} onSelect={onSelect} />
      )}
      {r.type === "fail" && ops && links && (
        <CausesSection r={r} where={display.rows.get(r.ref.position_id)?.ref.name} readOnly={readOnly} links={links} onSelect={onSelect} />
      )}

      {/* Each button acts on its first click only: a double-click opens one dialog. */}
      {!readOnly && (
        <div className="rw-panel-acts">
          {level.child && (
            <button type="button" className="secondary" onClick={(e) => { if (e.detail < 2) onAdd(r); }}>
              Add {r.type === "fn" ? "a functional failure" : "a failure mode"}
            </button>
          )}
          {EDITABLE.has(r.type) && (
            <button type="button" className="secondary danger" onClick={(e) => { if (e.detail < 2) onDelete(r); }}>Delete this {level.label.toLowerCase()}</button>
          )}
        </div>
      )}
    </aside>
  );
}

// A field in the panel: kept when you leave it (or press Enter in a one-line
// field); a value the server would refuse shows why and isn't kept.
// `limit` ({max, nudge}): a live counter beside the label (amber near the
// limit, red past it), the box stopping at `max`, and the nudge under it. A
// text saved longer before stays as it is, red, and a change to it is saved
// only once it's short enough (onCommit says so).
function Field({ label, help, value, area, readOnly, type, suffix, onCommit, autoFocus, limit = null }) {
  const [draft, setDraft] = useState(String(value ?? ""));
  const [error, setError] = useState(null);
  // What was last sent: Enter then leaving the field (or Enter twice) sends it
  // once; typing, or coming back to the field, can send it again.
  const sent = useRef(null);
  useEffect(() => { setDraft(String(value ?? "")); setError(null); sent.current = null; }, [value]);
  if (readOnly) {
    return (
      <div className="rw-field">
        <span className="rw-flabel">{label}</span>
        <span className="rw-fval">{value === "" || value == null ? "—" : `${value}${suffix ? ` ${suffix}` : ""}`}</span>
      </div>
    );
  }
  const commit = () => {
    if (draft === String(value ?? "") || draft === sent.current) return;
    const err = onCommit(draft);
    if (typeof err !== "string") sent.current = draft;
    setError(typeof err === "string" ? err : null);
    // Written at once (the Explorer): if it didn't save, the text stays as
    // typed with the reason, and leaving the field again sends it again.
    if (err && typeof err.then === "function") {
      const was = draft;
      err.then((out) => {
        if (typeof out !== "string") return;
        if (sent.current === was) sent.current = null;
        setError(out);
      });
    }
  };
  const Tag = area ? "textarea" : "input";
  const count = limit ? charCount(draft, { max: limit.max, before: String(value ?? "") }) : null;
  return (
    <label className="rw-field">
      <span className={"rw-flabel" + (count ? " rw-flabel-count" : "")}>
        {label}
        {count && <span className={"char-count" + (count.tone ? ` ${count.tone}` : "")} aria-hidden="true">{count.text}</span>}
      </span>
      <span className="rw-fin">
        <Tag value={draft} rows={area ? 2 : undefined} type={area ? undefined : type} autoFocus={autoFocus}
             maxLength={limit ? limit.max : undefined}
             aria-description={count ? `${count.n} of ${count.max} characters.${limit.nudge ? ` ${limit.nudge}` : ""}` : undefined}
             inputMode={type === "number" ? "decimal" : undefined} min={type === "number" ? "0" : undefined}
             step={type === "number" ? "any" : undefined} aria-invalid={error || count?.over ? "true" : undefined}
             onChange={(e) => { setDraft(e.target.value); sent.current = null; }} onBlur={commit}
             onFocus={() => { sent.current = null; }}
             onKeyDown={(e) => { if (e.key === "Enter" && !area) { e.preventDefault(); commit(); } }} />
        {suffix && <span className="rw-unit">{suffix}</span>}
      </span>
      {help && !error && <span className="rw-fhelp">{help}</span>}
      {limit?.nudge && !error && <span className="rw-fhelp rw-nudge">{limit.nudge}</span>}
      {count?.over && !error && <span className="rw-ferr">{count.message}</span>}
      {error && <span className="rw-ferr" role="alert">{error}</span>}
    </label>
  );
}

// The column chooser: tick the columns to show; the description is always shown.
export function ColumnChooser({ cols, onCols, usual = DEFAULT_COLUMNS }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="rw-cols" ref={box}>
      <button type="button" className="secondary rw-btn" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)}
              aria-label="Columns" title="Choose which columns to show">
        Columns
      </button>
      {open && (
        <div className="rw-pop" role="group" aria-label="Columns to show">
          {COLUMNS.map((c) => (
            <label key={c.id} className="rw-pop-item" title={c.title}>
              <input type="checkbox" checked={cols.includes(c.id)}
                     onChange={(e) => onCols(e.target.checked ? COLUMNS.map((x) => x.id).filter((id) => id === c.id || cols.includes(id)) : cols.filter((x) => x !== c.id))} />
              {c.label}{c.sum ? <span className="rw-sig" title="A parent row counts what's inside it"> Σ</span> : null}
            </label>
          ))}
          <button type="button" className="link rw-pop-reset" onClick={() => onCols(usual, { reset: true })}>Show the usual columns</button>
        </div>
      )}
    </div>
  );
}
