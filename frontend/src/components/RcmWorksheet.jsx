import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import RcmStatusBadge from "./RcmStatusBadge.jsx";
import { Highlight } from "./OutlineBits.jsx";
import { ancestorsOf } from "../outlineTree.js";
import {
  COLUMN, COLUMNS, CONSEQUENCE_LABEL, DEFAULT_COLUMNS, FUNCTION_MAX, FUNCTION_NUDGE, LEVEL_OF, NAME_COLUMN, functionCount,
  belowDecisionText, belowOf, belowPending, phoneLine, consequenceWords, failuresOn, functionOf, checkCounts, decisionText, insideWords,
  intervalText, moreTasks, nameOf, shownStatus, taskLine, tasksOf, tasksTip, checkValue,
} from "../rcmWorksheet.js";
import { charCount } from "../maintenanceText.js";
import RcmBasis from "./RcmBasis.jsx";
import RcmFunctionStandards, { BreachesField } from "./RcmFunctionStandards.jsx";
import { plainFirstLine } from "../basisMarkdown.js";
import { COMPARATORS, COMPARATOR_LABEL } from "../rcmStandards.js";
import RcmModeTasks from "./RcmModeTasks.jsx";
import { saveErrorText } from "../confirm.js";
import { CausedBySection, CausesSection } from "./FailureLinks.jsx";
import { basisMarked, failureRows, failureStatusWords, failureSummary } from "../explorerRcm.js";
import "./RcmWorksheet.css";

// The RCM worksheet's pieces, drawn by the Explorer's RCM tab (the asset tree
// and the RCM as one table, TreePane): the level icons, a cell and its
// tooltip, the cell editor (a double-click edits the commonest cells in
// place: description, effects, consequence, task, interval, notes, checked as
// the server checks them), a row's status on a phone, the details panel (the
// one place a row is edited in full: every field, its lists, adding inside
// it, deleting it; beside the table, or expanded across it) and the column
// chooser. Edits are written at once (Details' `ops`); a refused value stays
// in the cell or field with the reason.
//
// On a phone the details panel opens as a sheet.

const ICONS = {
  fn: <path d="M3 3.5h10v9H3z M6.5 6v4l3.5-2z" strokeWidth="1.4" strokeLinejoin="round" />,
  // A performance standard: a limit on a scale.
  std: <><path d="M2 10.5h12M4 10.5v-3M7 10.5v-4.5M10 10.5v-3M13 10.5v-4.5" strokeWidth="1.4" strokeLinecap="round" /><path d="M2 13h12" strokeWidth="1.4" strokeLinecap="round" /></>,
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

// The (i) at the end of a performance standard's name (or a function's, when
// it has no performance standard) when its function has a working behind it
// (basisMarked). It opens the function's details with the working in full. A
// letter, a label and a tooltip: never colour alone. Fixed size, so a row
// never changes height or width with it.
export function BasisInfo({ r, onBasis }) {
  if (!onBasis || !basisMarked(r)) return null;
  const first = plainFirstLine(r.type === "std" ? r.ref.function_basis_preview : r.ref.basis_preview, 80);
  const what = r.type === "std" ? "this performance standard" : "this function's performance standard";
  return (
    <button type="button" className="rw-info" aria-label={`How ${what} was worked out: open the working`}
            title={`How ${what} was worked out${first ? `: ${first}` : ""}. Open the working.`}
            onDoubleClick={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); if (e.detail < 2) onBasis(r); }}>
      <span aria-hidden="true">i</span>
    </button>
  );
}

// One cell's content (desktop).
export function Cell({ col, r, query, onDecision, readOnly, linkChecks }) {
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
      // A mode with several tasks: its own, then "+1 task" (kept whole when the
      // name is cut short); the tooltip lists them all.
      const more = mode ? moreTasks(r.ref) : "";
      const main = more && text.endsWith(` · ${more}`) ? text.slice(0, -(more.length + 3)) : text;
      const tip = mode && tasksOf(r.ref).length > 1 ? tasksTip(r.ref) : text;
      return mode
        ? (
          <span className="rw-txt rw-task" title={tip}>
            <LevelIcon type="task" className="rw-ic rw-ic-task" />
            <span className="rw-task-t"><Highlight text={main} query={query} /></span>
            {more && <span className="rw-more">· {more}</span>}
          </span>
        )
        : <span className="rw-sum">{text}</span>;
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

// The details panel for the row picked: every field, the decision, the tasks,
// adding inside and deleting. Beside the table at its usual width (a click on
// a row), or filling the table's room (`expanded`: a double-click on a row's
// name, Open… in its menu, or Expand here), with the tree column still beside
// it so another row can be picked; the panel follows the row picked. Every
// field is kept as you go (when you leave it, or Enter in a one-line field);
// a value the server would refuse stays as typed with the reason. Escape (or
// Back to table) returns from expanded to side by side; Escape again closes.
// The kinds of row whose description is edited (not a position's, nor the
// unassigned failure modes' or the "No standard" heading, in the Explorer).
// A standard's description is its text.
export const EDITABLE = new Set(["fn", "std", "fail", "mode"]);

// A performance standard's structured limit, when it applies and its source,
// as the panel's fields: each one kept as you go.
const LIMIT_FIELDS = [
  { col: "parameter", label: "Parameter", placeholder: "e.g. pH" },
  { col: "value", label: "Value", placeholder: "7.2-7.8" },
  { col: "unit", label: "Unit", placeholder: "ppm" },
];

//   r          the row (cellRow: sum is its own counts)
//   display    the tree as shown (the way up); whole: the whole tree (what's inside)
//   ops        the Explorer's ops (useTreeRcm, with basis, basisView, standards, tasks, saveItem)
//   links      { onLink, onUnlink } (a functional failure's links)
//   expanded   filling the table's room; onExpand / onCollapse switch it (none on a phone)
//   taskStart  {key, at}: open this failure mode's tasks on the add form (the row menu's Add a task…)
//   onSaid     (text) a few words in the page's status line once something saved
export function Details({
  r, display, whole = display, readOnly, onCommit, onAdd, onDelete, onDecision, onClose, onSelect, phone, headingRef, ops, links,
  expanded = false, onExpand = null, onCollapse = null, taskStart = null, onSaid = null,
}) {
  const level = LEVEL_OF[r.type];
  const d = r.ref.decision;
  const up = ancestorsOf(display, r.key).map((k) => display.rows.get(k)).filter(Boolean);
  const tasks = r.type === "mode" ? tasksOf(r.ref) : [];
  // A failure mode's tasks (RcmModeTasks) are where its tasks are changed;
  // the decision's own task and interval stay as fields only while no task
  // does the work (an action on failure, a decision written before tasks).
  const taskList = r.type === "mode" && !!ops?.addTask;
  const ownFields = !taskList || !tasks.some((t) => t.id);
  const sharedOwn = tasks[0]?.shared_with || 0;
  const field = (label, col, { area, help, limit, locked = false } = {}) => {
    const column = col === "name" ? NAME_COLUMN : COLUMN[col];
    const value = col === "name" ? r.ref.text || "" : column.onDecision ? d?.[column.field] ?? "" : r.ref[column.field] || "";
    return (
      <Field key={`${r.key}:${col}`} label={label} help={help} value={value} area={area} readOnly={readOnly || locked} limit={limit}
             type={col === "interval" ? "number" : "text"} suffix={col === "interval" ? d?.interval_unit || "hours" : null}
             onCommit={(raw) => onCommit(r, col, raw)} autoFocus={col === "name" && !r.ref.text && !readOnly} />
    );
  };
  // A standard's limit field, kept at once (as the table's cells are).
  const saveStd = (col, raw) => {
    const res = checkValue(col, r, raw);
    if (res.error) return res.error;
    return ops.saveItem(r, { [col]: res.value }).then(() => { onSaid?.("Saved."); return true; },
      (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  const stdField = ({ col, label, placeholder }) => (
    <Field key={`${r.key}:${col}`} label={label} value={String(r.ref[col] ?? "")} readOnly={readOnly} placeholder={placeholder}
           onCommit={(raw) => saveStd(col, raw)} />
  );
  const [stdFailed, setStdFailed] = useState(null);
  useEffect(() => setStdFailed(null), [r.key]);
  // What's inside: a function's functional failures (through its standard
  // rows), a standard's functional failures, a failure's failure modes.
  const inTree = whole.rows.get(r.key) || r;
  const kids = r.type === "fn" ? failureRows(whole, inTree)
    : (inTree.kids || []).map((k) => whole.rows.get(k)).filter((k) => k && (k.type === "fail" || k.type === "mode"));
  const where = display.rows.get(r.ref.position_id)?.ref.name || whole.rows.get(r.ref.position_id)?.ref.name;
  const said = (text) => onSaid?.(text);
  const canExpand = !phone && onExpand && onCollapse;
  return (
    <aside className={"rw-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented) return;
             e.stopPropagation();
             if (expanded && canExpand) onCollapse();
             else onClose();
           }}>
      <div className="rw-panel-head">
        <div className="rw-panel-kind"><LevelIcon type={r.type} /> {level.label}</div>
        <div className="rw-panel-btns">
          {canExpand && (expanded ? (
            <button type="button" className="secondary rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)">
              Back to table
            </button>
          ) : (
            <button type="button" className="secondary rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them"
                    aria-label="Expand the details">
              Expand
            </button>
          ))}
          <button type="button" className="secondary rw-x" onClick={onClose} aria-label="Close the details">Close</button>
        </div>
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

      <div className="rw-pbody">
        <div className="rw-pcol">
          <div className="rw-fields">
            {EDITABLE.has(r.type) && field(r.type === "std" ? "Performance standard" : "Description", "name", {
              area: true,
              help: r.type === "fn" ? (ops ? "What this position must do" : "What the system must do") : r.type === "std" ? "One parameter and one limit, e.g. pH 7.2-7.8"
                : r.type === "fail" ? "How it fails to do it" : "What causes the failure",
              limit: r.type === "fn" ? { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE } : null,
            })}
            {r.type === "std" && r.ref.legacy && (
              <p className="rw-fhelp">
                This is the function's one performance standard, as written. To make it a list (one row each, with a limit on each), pick the
                function and press <b>Add performance standard</b>, or <b>Split into performance standards…</b> when the text is several joined by “;”.
              </p>
            )}
            {r.type === "std" && !r.ref.legacy && ops?.saveItem && (
              <fieldset className="rw-limit">
                <legend className="rw-flabel">Limit (optional)</legend>
                <div className="rw-limit-row">
                  {stdField(LIMIT_FIELDS[0])}
                  <label className="rw-field">
                    <span className="rw-flabel">Comparator</span>
                    {readOnly ? <span className="rw-fval">{COMPARATOR_LABEL[r.ref.comparator] || "—"}</span> : (
                      <select value={r.ref.comparator || ""}
                              onChange={(e) => {
                                setStdFailed(null);
                                ops.saveItem(r, { comparator: e.target.value }).then(() => said("Saved."),
                                  (err) => setStdFailed(saveErrorText(err, { offline: navigator.onLine === false })));
                              }}>
                        <option value="">—</option>
                        {COMPARATORS.map((c) => <option key={c} value={c}>{COMPARATOR_LABEL[c]} ({c})</option>)}
                      </select>
                    )}
                    {stdFailed && <span className="rw-ferr" role="alert">{stdFailed}</span>}
                  </label>
                  {stdField(LIMIT_FIELDS[1])}
                  {stdField(LIMIT_FIELDS[2])}
                </div>
                {stdField({ col: "when", label: "When it applies", placeholder: "e.g. while the filter pump runs" })}
                {stdField({ col: "source", label: "Source", placeholder: "e.g. AS 1926.3, the E25 manual" })}
              </fieldset>
            )}
            {r.type === "std" && r.ref.function_has_basis && ops?.basis && (
              <p className="rw-fhelp">
                The working behind it is the function's:{" "}
                <button type="button" className="link" onClick={() => onSelect(r.ref.function_id, { basis: true })}>open the working</button>.
              </p>
            )}
            {r.type === "mode" && field("Failure effects", "effects", { area: true })}
            {r.type === "fail" && ops?.setBreach && (
              <BreachesField r={r} readOnly={readOnly} standards={functionOf(display, r)?.ref.standards || []}
                             onChange={(id) => ops.setBreach(r, id).then(() => said("Saved."), () => {})} />
            )}
            {r.type === "fail" && ops && <p className="rw-status">{failureStatusWords(r)}</p>}
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
                    {failuresOn(whole, r.ref.position_id).map((f) => (
                      <option key={f.id} value={f.id}>{f.function ? `${f.function} › ` : ""}{f.text}</option>
                    ))}
                  </select>
                )}
                {r.ref.was_under && !r.ref.functional_failure_id && <span className="rw-fhelp">It was noted as under: {r.ref.was_under}</span>}
              </label>
            )}
          </div>

          {r.type === "mode" && (
            <section className="rw-decision" aria-label="Decision">
              <h3>Decision</h3>
              {d ? (
                <>
                  <p className="rw-dline"><b>{decisionText(d)}</b>{d.interval ? ` · every ${intervalText(d)}` : ""}</p>
                  {ownFields && COLUMN.task.can(r) && field("Task", "task", { area: true, locked: sharedOwn > 0 && d.outcome !== "rtf" })}
                  {ownFields && COLUMN.interval.can(r) && field("Interval", "interval", { locked: sharedOwn > 0 })}
                  {ownFields && sharedOwn > 0 && (
                    <p className="rw-fhelp">
                      Shared with {sharedOwn} other failure mode{sharedOwn === 1 ? "" : "s"}: its name and interval are changed on the task, for all of them.
                    </p>
                  )}
                  {!taskList && tasks.length > 0 && (
                    <div className="rw-field">
                      <span className="rw-flabel">{tasks.length === 1 ? "Task" : `Tasks (${tasks.length})`}</span>
                      <ul className="rw-tasks">
                        {tasks.map((t, i) => (
                          <li key={t.id || i}>
                            <LevelIcon type="task" className="rw-ic rw-ic-task" />
                            <span>{taskLine(t)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
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
        </div>

        <div className="rw-pcol">
          {/* A function: its performance standards, then the working behind them. */}
          {r.type === "fn" && ops?.standards && <RcmFunctionStandards key={r.key} r={r} ops={ops} readOnly={readOnly} onSaid={said} />}
          {r.type === "fn" && ops?.basis && (
            <RcmBasis r={r} basis={ops.basis} readOnly={readOnly} context={ops.basisView?.context(r)}
                      openToken={ops.basisView?.token(r)} />
          )}

          {/* A failure mode's tasks: several under one mode, each with its own interval, kind and measurement. */}
          {taskList && !readOnly && (
            <RcmModeTasks key={`${r.key}:${taskStart?.key === r.key ? taskStart.at : ""}`} r={r} ops={ops}
                          start={taskStart?.key === r.key ? { tasks: true } : null} onSaid={said} />
          )}

          {/* A functional failure: Caused by below, then Causes above. */}
          {r.type === "fail" && ops && links && (
            <CausedBySection r={r} where={where} readOnly={readOnly} links={links} onSelect={onSelect} />
          )}
          {r.type === "fail" && ops && links && (
            <CausesSection r={r} where={where} readOnly={readOnly} links={links} onSelect={onSelect} />
          )}

          {/* What's inside it, each one a link that shows it here. */}
          {ops && r.type !== "mode" && EDITABLE.has(r.type) && (
            <section className="rw-kids" aria-label={r.type === "fail" ? "Failure modes" : "Functional failures"}>
              <h3>{r.type === "fail" ? "Failure modes" : "Functional failures"}</h3>
              {kids.length === 0 ? (
                <p className="rw-fhelp">
                  {r.type === "fn" ? "No functional failures yet."
                    : r.type === "std" ? (r.ref.legacy ? "No functional failures yet." : "No functional failure written yet: add one below, or from the performance standard's row menu.")
                    : "No failure modes of its own yet."}
                </p>
              ) : (
                <ul className="rw-klist">
                  {kids.map((k) => (
                    <li key={k.key}>
                      <button type="button" className="link rw-kgo" onClick={() => onSelect(k.key)}
                              title={`Show the ${LEVEL_OF[k.type].label.toLowerCase()}`}>
                        <LevelIcon type={k.type} /> {nameOf(k) || `(${LEVEL_OF[k.type].label.toLowerCase()})`}
                      </button>
                      <span className={"rw-fhelp" + (k.type === "mode" && !k.ref.decision ? " rw-todo" : "")}>
                        {k.type === "fail" ? failureSummary(k) : k.ref.decision ? decisionText(k.ref.decision) : "To decide"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      </div>

      {/* Each button acts on its first click only: a double-click opens one dialog. */}
      {!readOnly && (
        <div className="rw-panel-acts">
          {level.child && (
            <button type="button" className="secondary" onClick={(e) => { if (e.detail < 2) onAdd(r); }}>
              Add {r.type === "fn" || r.type === "std" || r.type === "nostd" ? "a functional failure" : "a failure mode"}
            </button>
          )}
          {EDITABLE.has(r.type) && (
            <button type="button" className="secondary danger" onClick={(e) => { if (e.detail < 2) onDelete(r); }}>{r.type === "std" ? "Remove this performance standard" : `Delete this ${level.label.toLowerCase()}`}</button>
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
function Field({ label, help, value, area, readOnly, type, suffix, onCommit, autoFocus, limit = null, placeholder = null }) {
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
        <Tag value={draft} rows={area ? 2 : undefined} type={area ? undefined : type} autoFocus={autoFocus} placeholder={placeholder || undefined}
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
