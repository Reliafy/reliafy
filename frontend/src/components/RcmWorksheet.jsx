import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import RcmStatusBadge from "./RcmStatusBadge.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Chevron, Highlight, LevelButtons } from "./OutlineBits.jsx";
import useOutlineNav from "./useOutlineNav.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import { ancestorsOf, depthOf, filterOpen, flatten, levelSet, visiblePick } from "../outlineTree.js";
import {
  CHIPS, COLUMN, COLUMNS, CONSEQUENCE_LABEL, DEFAULT_COLUMNS, FUNCTION_MAX, FUNCTION_NUDGE, LEVELS, LEVEL_OF, NAME_COLUMN, functionCount,
  addNode, belowDecisionText, belowOf, belowPending, buildRcmDisplay, phoneLine, consequenceWords, failuresOn, checkCounts, checkValue, chipCounts, clampCol, computeFilter, decisionText, insideWords,
  intervalText, loadPrefs, nameOf, rememberedOpen, removeNode, savePrefs, setCell, shownStatus, siblingOrder, withOpen,
} from "../rcmWorksheet.js";
import { charCount } from "../maintenanceText.js";
import { CausedBySection, CausesSection } from "./FailureLinks.jsx";
import "./RcmWorksheet.css";

// The RCM study's worksheet as an outline grid: the study's hierarchy in the
// first column (function → functional failure → failure mode: indent, arrow,
// icon, description), the worksheet's columns beside it. Levels 1 · 2 · 3 ·
// All, a filter that keeps the path to each match, chips, a sort that keeps
// the tree, a column chooser, resizable columns and two row heights. Only the
// rows on screen are in the page; the rows the first one sits inside stay
// pinned under the header. A parent row rolls up what's inside it.
//
// Editing: a row opens its details panel (Enter, or a click), where every
// field of the row is edited, a row added inside it or deleted, and a failure
// mode's decision opened in the decision dialog. A double-click edits the
// commonest cells in place (description, effects, consequence, task,
// interval, notes), checked as the server checks them. Edits change the study
// on this page only: the page's Save sends them, and Undo steps back.
//
// On a phone each row is two lines: the description and its status, then the
// main columns in a line; the details panel opens as a sheet with the rest.
//
// The Explorer's RCM tab (the asset tree and the RCM as one table, TreePane)
// uses the cells, the cell editor, the details panel and the column chooser
// from here; there, edits are written at once (Details' `ops`).

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
const PHONE_H = 60;
const HEIGHTS = { comfortable: 36, compact: 28 };
const HEAD_H = 36;
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
      return mode
        ? <span className="rw-txt rw-task" title={text}><LevelIcon type="task" className="rw-ic rw-ic-task" /><span className="rw-task-t"><Highlight text={text} query={query} /></span></span>
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

function NameCell({ r, v, open, query, phone, editing, onToggle, onCommit, onCancel, width }) {
  const has = r.kids.length > 0;
  const indent = Math.min(v.depth, 6) * (phone ? 14 : 18);
  const text = nameOf(r);
  return (
    <div className="rw-c rw-name" role="rowheader" style={phone ? undefined : { width }}>
      <span className="rw-indent" style={{ width: indent }} />
      {has ? (
        <span className={"tp-chev rw-chev" + (open ? " open" : "")} aria-hidden="true"
              onClick={(e) => { e.stopPropagation(); onToggle(r.key); }}><Chevron /></span>
      ) : <span className="tp-chev-sp rw-chev-sp" />}
      <LevelIcon type={r.type} />
      <span className="sr-only">{LEVEL_OF[r.type].label}: </span>
      {editing ? (
        <CellEditor col={NAME_COLUMN} r={r} onCommit={onCommit} onCancel={onCancel} />
      ) : (
        <span className={"rw-nm" + (text ? "" : " rw-blank")} title={text.length > 24 ? text : undefined}>
          {text ? <Highlight text={text} query={query} /> : "(no description yet)"}
        </span>
      )}
      {has && !open && !editing && (
        <span className="tp-cnt" title={`${r.kids.length} directly inside`}>{r.kids.length.toLocaleString("en-AU")}</span>
      )}
    </div>
  );
}

export function PhoneStatus({ r }) {
  if (r.type === "mode") {
    const s = shownStatus(r.ref.decision?.status);
    return s ? <RcmStatusBadge status={s} /> : null;
  }
  if (r.sum.contradicted) return <span className="rw-ck contradicted">✗{r.sum.contradicted}<span className="sr-only"> contradicted</span></span>;
  if (r.sum.undecided) return <span className="rw-sum rw-todo">{r.sum.undecided} to decide</span>;
  return null;
}

function Row({
  r, v, i, top, height, cols, widths, total, open, focused, tabbable, dim, pinned, phone, query, editing, readOnly, wt,
  onToggle, onPick, onEdit, onCommit, onCancel, onDecision,
}) {
  const has = r.kids.length > 0;
  const editCol = editing?.key === r.key ? editing.col : null;
  const cls = "rw-row rw-" + r.type + (focused ? " focus" : "") + (dim ? " dim" : "") + (pinned ? " pin" : "");
  const common = {
    className: cls,
    role: pinned ? undefined : "row",
    "aria-hidden": pinned ? "true" : undefined,
    id: pinned ? undefined : `rw-${r.key}`,
    "data-key": r.key,
    "data-wt": pinned ? undefined : wt?.row,
    "aria-rowindex": pinned ? undefined : i + 2,
    "aria-level": pinned ? undefined : v.depth + 1,
    "aria-setsize": pinned ? undefined : v.size,
    "aria-posinset": pinned ? undefined : v.pos,
    "aria-expanded": pinned || !has ? undefined : open,
    "aria-selected": pinned ? undefined : focused,
    tabIndex: pinned ? undefined : focused || tabbable ? 0 : -1,
    style: pinned ? { height, width: phone ? undefined : total } : { top, height, width: phone ? undefined : total },
    onClick: (e) => {
      if (e.target.closest("input, select, a, button.rw-todo-btn")) return;
      onPick(r.key, { open: true });
    },
  };
  const commitCell = (col) => (raw) => onCommit(r, col, raw);
  if (phone) {
    return (
      <div {...common}>
        <div className="rw-l1">
          <NameCell r={r} v={v} open={open} query={query} phone onToggle={onToggle}
                    editing={false} onCommit={commitCell("name")} onCancel={onCancel} />
          <span className="rw-st"><PhoneStatus r={r} /></span>
        </div>
        <div className="rw-l2" role="gridcell" style={{ paddingLeft: Math.min(v.depth, 6) * 14 + 46 }}>{phoneLine(r)}</div>
      </div>
    );
  }
  return (
    <div {...common}>
      <NameCell r={r} v={v} open={open} query={query} width={widths.name} onToggle={onToggle}
                editing={editCol === "name"} onCommit={commitCell("name")} onCancel={onCancel} />
      {cols.map((c) => {
        const can = !readOnly && c.edit && c.can(r);
        return (
          <div key={c.id} role="gridcell"
               className={"rw-c" + (c.align === "num" ? " num" : "") + (can ? " can" : "")}
               style={{ width: widths[c.id] }}
               data-wt={c.id === "check" ? wt?.check : undefined}
               onDoubleClick={can ? (e) => { e.stopPropagation(); onEdit(r.key, c.id); } : undefined}
               title={editCol !== c.id ? cellTip(c, r, can) : undefined} aria-description={editCol !== c.id ? cellHint(can) : undefined}>
            {editCol === c.id
              ? <CellEditor col={c} r={r} onCommit={commitCell(c.id)} onCancel={onCancel} />
              : <Cell col={c} r={r} query={query} readOnly={readOnly} onDecision={onDecision} />}
          </div>
        );
      })}
      <div className="rw-c rw-fill" aria-hidden="true" />
    </div>
  );
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

export default function RcmWorksheet({
  studyId, functions, readOnly, onChange, onDecision, onUndo, canUndo, phone, notice,
}) {
  const confirm = useConfirm();
  const display = useMemo(() => buildRcmDisplay(functions), [functions]);
  const depth = Math.max(1, depthOf(display));
  const [prefs, setPrefs] = useState(() => loadPrefs());
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState([]);
  const [sort, setSort] = useState(null); // {col, dir}
  const [focus, setFocus] = useState(null);
  const [panel, setPanel] = useState(false);
  const [editing, setEditing] = useState(null); // {key, col}
  const [message, setMessage] = useState(null); // {text, tone}
  const headingRef = useRef(null);

  // Open rows: remembered for this study, else everything for a small study
  // and two levels for a big one.
  const [open, setOpenState] = useState(() => rememberedOpen(prefs, studyId, display)
    || levelSet(display, display.rows.size <= 300 ? Infinity : 2));
  const [fopen, setFopen] = useState(null);
  const filter = useMemo(() => computeFilter(display, { query, chips }), [display, query, chips]);
  useEffect(() => setFopen(filter ? filterOpen(filter) : null), [filter]);
  const shownOpen = filter ? fopen || filterOpen(filter) : open;
  const order = useMemo(() => siblingOrder(display, sort), [display, sort]);
  const { list, index } = useMemo(() => flatten(display, shownOpen, filter, order), [display, shownOpen, filter, order]);
  const counts = useMemo(() => chipCounts(display), [display]);

  // Remembered on this device, a moment after each change, and on the way out.
  const latest = useRef(null);
  latest.current = withOpen(prefs, studyId, open);
  useEffect(() => {
    const t = setTimeout(() => savePrefs(latest.current), 200);
    return () => clearTimeout(t);
  }, [prefs, open, studyId]);
  useEffect(() => {
    const flush = () => savePrefs(latest.current);
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, []);

  const setOpen = (next) => (filter ? setFopen(next) : setOpenState(next));
  const toggle = (key, force) => {
    const next = new Set(shownOpen);
    const want = force ?? !next.has(key);
    if (want) next.add(key);
    else next.delete(key);
    setOpen(next);
  };

  const cur = focus != null && index.has(focus) ? focus : null;
  const row = cur != null ? display.rows.get(cur) : null;

  const H = phone ? PHONE_H : HEIGHTS[prefs.density];
  const cols = prefs.cols.map((id) => COLUMN[id]).filter(Boolean);
  const widths = { name: prefs.widths.name ?? NAME_COLUMN.width };
  for (const c of cols) widths[c.id] = prefs.widths[c.id] ?? c.width;
  const total = cols.reduce((s, c) => s + widths[c.id], widths.name);

  const pick = (key, opts = {}) => {
    setFocus(key);
    if (opts.open) setPanel(true);
  };
  const nav = useOutlineNav({
    display, list, index, open: shownOpen, focus: cur, rowHeight: H, maxPins: phone ? 2 : 4,
    headerHeight: phone ? 0 : HEAD_H, onPick: pick, onToggle: toggle, nameOf,
    onEnter: (key) => { setFocus(key); setPanel(true); setTimeout(() => headingRef.current?.focus(), 0); },
    measureKey: `${phone}${panel}${prefs.density}`, rowId: (key) => `rw-${key}`,
  });

  // A new row or one picked from the panel's path: open the way down to it
  // and bring it into view.
  const [want, setWant] = useState(null);
  useEffect(() => {
    if (!want || !display.rows.has(want.key)) return;
    if (!index.has(want.key)) {
      const up = ancestorsOf(display, want.key);
      if (filter) setFopen((s) => new Set([...(s || filterOpen(filter)), ...up]));
      else setOpenState((s) => new Set([...s, ...up]));
      if (filter && !filter.keep.has(want.key)) { setQuery(""); setChips([]); }
      return;
    }
    setFocus(want.key);
    nav.reveal(want.key, true);
    setWant(null);
  }, [want, display, index]); // eslint-disable-line react-hooks/exhaustive-deps

  const setLevel = (lv) => {
    let next = levelSet(display, lv);
    if (filter) next = new Set([...next].filter((k) => filter.keep.has(k)));
    setOpen(next);
    if (cur != null) {
      const { index: shown } = flatten(display, next, filter);
      const k = visiblePick(display, shown, cur);
      if (k != null && k !== cur) setFocus(k);
    }
  };

  const say = (text, tone = "ok") => setMessage({ text, tone, at: Date.now() });

  // One cell changed: checked as the server checks it, then kept on the page.
  // Returns true when kept; a refused value says why.
  const commit = (r, col, raw) => {
    const res = checkValue(col, r, raw);
    if (res.error) {
      say(res.error, "error");
      return res.error;
    }
    const label = col === "name" ? "description" : (COLUMN[col]?.label || col).toLowerCase();
    onChange(setCell(functions, r, col, res.value), `Changed the ${label} of “${(nameOf(r) || LEVEL_OF[r.type].label).slice(0, 60)}”.`);
    say(`Changed the ${label}. Save the study to keep it.`);
    setEditing(null);
    return true;
  };

  const add = (r) => {
    const { functions: next, id } = addNode(functions, r ? r.at : null);
    const what = r ? (r.type === "fn" ? "functional failure" : "failure mode") : "function";
    onChange(next, `Added a ${what}.`);
    say(`Added a ${what}: describe it in the details.`);
    if (r) setOpenState((s) => new Set([...s, r.key]));
    setPanel(true);
    setWant({ key: id });
  };

  const remove = async (r) => {
    const level = LEVEL_OF[r.type].label.toLowerCase();
    if (r.kids.length) {
      const inside = r.type === "fn"
        ? `${n(r.kids.length, "functional failure")} and ${n(r.sum.modes, "failure mode")}`
        : n(r.sum.modes, "failure mode");
      const ok = await confirm({
        title: `Delete this ${level}?`,
        body: `“${nameOf(r) || level}” and the ${inside} inside it go. Undo brings them back until you save.`,
        confirmLabel: `Delete ${level}`,
      });
      if (!ok) return;
    }
    const parent = r.parent;
    onChange(removeNode(functions, r.at), `Deleted a ${level}.`);
    say(`Deleted the ${level}. Undo brings it back.`);
    setFocus(parent);
    if (!parent) setPanel(false);
  };

  const onHeaderSort = (id) => setSort((s) => (s?.col !== id ? { col: id, dir: 1 } : s.dir === 1 ? { col: id, dir: -1 } : null));

  // Drag a header's edge to resize its column; ← → when it has focus; a
  // double-click goes back to the usual width.
  const resize = (id, w) => setPrefs((p) => ({ ...p, widths: { ...p.widths, [id]: clampCol(w, id === "name" ? NAME_COLUMN.min : 60) } }));
  const startResize = (id) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startW = widths[id];
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    const move = (ev) => resize(id, startW + ev.clientX - startX);
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };
  const resetWidth = (id) => setPrefs((p) => {
    const next = { ...p.widths };
    delete next[id];
    return { ...p, widths: next };
  });

  // The walkthrough's anchors: the first function, failure mode and evidence check.
  const wt = useMemo(() => {
    const out = {};
    for (const v of list) {
      const r = display.rows.get(v.key);
      if (r.type === "fn" && !out.fn) out.fn = v.key;
      if (r.type === "mode" && !out.mode) out.mode = v.key;
      if (r.type === "mode" && r.ref.decision?.status && !out.check) out.check = v.key;
    }
    return out;
  }, [list, display]);
  const wtFor = (key) => ({
    row: key === wt.fn ? "rcm-function" : key === wt.mode ? "rcm-mode" : undefined,
    check: key === wt.check ? "rcm-evidence" : undefined,
  });

  const c = display.counts;
  const statusText = filter
    ? `${n(filter.match.size, "match", "matches")}, shown with what they're inside`
    : `${n(c.fn, "function")} · ${n(c.fail, "functional failure")} · ${n(c.mode, "failure mode")}`;
  const dim = (key) => filter && !filter.match.has(key);
  const rowProps = (k) => ({
    r: display.rows.get(k), cols, widths, total, phone, query, readOnly, editing,
    onToggle: toggle, onPick: pick, onEdit: (key, col) => { setFocus(key); setEditing({ key, col }); },
    onCommit: commit, onCancel: () => setEditing(null), onDecision,
  });

  return (
    <div className={"rw" + (phone ? " phone" : "") + (prefs.density === "compact" ? " compact" : "")}>
      <div className="rw-bar">
        <label className="tp-filter rw-filter">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Filter: description, effects, task, notes" aria-label="Filter the worksheet" />
        </label>
        <LevelButtons levels={Array.from({ length: Math.min(depth, LEVELS.length) }, (_, i) => i + 1)}
                      names={LEVELS.map((l) => l.plural)} onLevel={setLevel} onCloseAll={() => setOpen(new Set())}
                      className="tp-levels rw-levels" />
        <div className="rw-tools">
          {!readOnly && (
            <button type="button" className="secondary rw-btn" onClick={() => { onUndo(); say("Undid the last change."); }} disabled={!canUndo}
                    title="Undo the last change (Ctrl+Z)">Undo</button>
          )}
          {!phone && (
            <ColumnChooser cols={prefs.cols} onCols={(next, o) => setPrefs((p) => {
              // Chosen (the Explorer's table keeps them whatever the window's width), or the usual ones again.
              const out = { ...p, cols: next, colsChosen: true };
              if (o?.reset) delete out.colsChosen;
              return out;
            })} />
          )}
          {!phone && (
            <SegmentedControl size="sm" label="Row height" value={prefs.density}
                              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]}
                              onChange={(v) => setPrefs((p) => ({ ...p, density: v }))} />
          )}
          {!readOnly && <button type="button" className="rw-btn" onClick={() => add(null)}>Add function</button>}
        </div>
      </div>
      <div className="tp-chips rw-chips" role="group" aria-label="Show only">
        {CHIPS.map((ch) => {
          const on = chips.includes(ch.id);
          return (
            <button key={ch.id} type="button" className={"tp-chip rw-chip" + (on ? " on" : "")} aria-pressed={on} title={ch.title}
                    onClick={() => setChips(on ? chips.filter((x) => x !== ch.id) : [...chips, ch.id])}>
              {ch.label} <span className="rw-chip-n">{counts[ch.id].toLocaleString("en-AU")}</span>
            </button>
          );
        })}
      </div>
      <div className="rw-sub">
        <p className="rw-legend" aria-label="What the icons mean">
          {LEVELS.map((l) => <span key={l.type}><LevelIcon type={l.type} /> {l.label}</span>)}
          <span><LevelIcon type="task" /> Task</span>
          {!phone && <span className="rw-legend-note">A row with things inside it counts them; double-click a cell to edit it.</span>}
        </p>
        <p className="rw-status" role="status">
          {statusText}
          {message && <span className={"rw-msg " + message.tone}> · {message.text}</span>}
        </p>
      </div>
      {notice}

      <div className={"rw-main" + (panel && row ? " with-panel" : "")}>
        <div className="rw-grid" ref={nav.scroller} onScroll={nav.onScroll} onKeyDown={(e) => {
          if (e.key === "F2" && cur && !readOnly && !editing) { e.preventDefault(); setEditing({ key: cur, col: "name" }); return; }
          if (e.key === "Escape" && panel && !editing) { e.preventDefault(); setPanel(false); return; }
          nav.onKey(e);
        }}
             role="treegrid" aria-label="RCM worksheet" aria-rowcount={list.length + 1} aria-colcount={cols.length + 1}
             aria-multiselectable="false">
          {!phone && (
            <div className="rw-head" role="row" aria-rowindex={1} style={{ width: total, height: HEAD_H }}>
              {[NAME_COLUMN, ...cols].map((col) => {
                const sorted = sort?.col === col.id;
                return (
                  <div key={col.id} role="columnheader" className={"rw-h" + (col.id === "name" ? " rw-name" : "") + (col.align === "num" ? " num" : "")}
                       style={{ width: widths[col.id] }}
                       aria-sort={sorted ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                    <button type="button" className="rw-hs" onClick={() => onHeaderSort(col.id)}
                            title={`${col.title ? `${col.title}. ` : ""}Sort by ${col.label.toLowerCase()} within each level`}>
                      {col.label}{col.sum ? <span className="rw-sig" aria-hidden="true"> Σ</span> : null}
                      {sorted && <span aria-hidden="true">{sort.dir === 1 ? " ▲" : " ▼"}</span>}
                    </button>
                    <span className="rw-rz" role="separator" aria-orientation="vertical" tabIndex={0}
                          aria-label={`Resize ${col.label}`} aria-valuenow={widths[col.id]} aria-valuemin={60} aria-valuemax={640}
                          onPointerDown={startResize(col.id)} onDoubleClick={() => resetWidth(col.id)}
                          onKeyDown={(e) => {
                            if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                              e.preventDefault();
                              e.stopPropagation();
                              resize(col.id, widths[col.id] + (e.key === "ArrowLeft" ? -16 : 16));
                            }
                          }} />
                  </div>
                );
              })}
              <div className="rw-h rw-fill" aria-hidden="true" />
            </div>
          )}
          {nav.pins.length > 0 && (
            <div className="rw-pins" style={{ top: phone ? 0 : HEAD_H }}>
              <div className="rw-pins-in">
                {nav.pins.map((k) => (
                  <Row key={k} {...rowProps(k)} v={list[index.get(k)]} i={index.get(k)} height={H}
                       open={shownOpen.has(k)} focused={k === cur} pinned editing={null}
                       onPick={(key) => { pick(key, {}); nav.reveal(key, true); }} />
                ))}
              </div>
            </div>
          )}
          <div className="rw-body" style={{ height: list.length * H, width: phone ? undefined : total }}>
            {nav.drawn.map((i) => {
              const v = list[i];
              return (
                <Row key={v.key} {...rowProps(v.key)} v={v} i={i} top={i * H} height={H}
                     open={shownOpen.has(v.key)} focused={v.key === cur} tabbable={cur == null && i === 0}
                     dim={dim(v.key)} wt={wtFor(v.key)} />
              );
            })}
          </div>
          {!list.length && (
            <div className="rw-empty">
              {filter ? (
                <p>Nothing matches. <button type="button" className="link" onClick={() => { setQuery(""); setChips([]); }}>Clear filters</button></p>
              ) : (
                <>
                  <p><b>No functions yet.</b> Start with a function: what the system must do, ideally with a performance standard.</p>
                  {!readOnly && <button type="button" onClick={() => add(null)}>Add function</button>}
                </>
              )}
            </div>
          )}
        </div>
        {panel && row && (
          <>
            {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
            <Details r={row} display={display} readOnly={readOnly} phone={phone} headingRef={headingRef}
                     onCommit={commit} onAdd={add} onDelete={remove} onDecision={onDecision}
                     onClose={() => { setPanel(false); document.getElementById(`rw-${row.key}`)?.focus({ preventScroll: true }); }}
                     onSelect={(key) => setWant({ key })} />
          </>
        )}
      </div>
    </div>
  );
}
