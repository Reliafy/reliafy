import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import useAutoGrow from "./ui/useAutoGrow.js";
import { Link, useLocation } from "react-router-dom";
import RcmStatusBadge from "./RcmStatusBadge.jsx";
import { CloseIcon, ExpandIcon, PlusIcon, ShrinkIcon } from "./icons.jsx";
import Chip from "./ui/Chip.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field, { SavedMark } from "./ui/Field.jsx";
import InputGroup, { ReadsAs } from "./ui/InputGroup.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import Section from "./ui/Section.jsx";
import { InlineAddButton, InlineAddRow, useInlineAdd } from "./ui/InlineAdd.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";
import { Highlight } from "./OutlineBits.jsx";
import { ancestorsOf } from "../outlineTree.js";
import {
  CATEGORY_LABEL, COLUMN, COLUMNS, CONSEQUENCE_LABEL, DEFAULT_COLUMNS, EVIDENT_LABEL, consequenceText, FUNCTION_MAX, FUNCTION_NUDGE, LEVEL_OF, NAME_COLUMN, functionCount,
  belowDecisionText, belowOf, decisionBody, belowPending, phoneLine, consequenceWords, checkCounts, decisionText, insideWords,
  intervalText, isCombination, memberEvidenceLine, moreTasks, nameOf, shownStatus, tasksOf, tasksTip, checkValue,
  OUTCOME_LABEL, decisionWithMemberEvidence, everyText, memberEvidenceText, taskKindText, taskServesTip, taskSharedText,
} from "../rcmWorksheet.js";
import { charCount } from "../maintenanceText.js";
import { modeAnswers } from "../decisionCheck.js";
import RcmFunctionStandards from "./RcmFunctionStandards.jsx";
import { COMPARATORS, COMPARATOR_LABEL, limitReads, limitWords } from "../rcmStandards.js";
import RcmModeTasks, { RcmTaskSections, StepLabel, removeTaskFromMode } from "./RcmModeTasks.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { getTaskLsa } from "../api.js";
import { explorerHere } from "../products.js";
import Modal from "./Modal.jsx";
import EvidencePicker from "./EvidencePicker.jsx";
import RcmNotes from "./RcmNotes.jsx";
import RcmFunctionPdfs from "./RcmFunctionPdfs.jsx";
import ModeFailureReports from "./ModeFailureReports.jsx";
import { hasNotes, hasNotesField, notesTip } from "../rcmNotes.js";
import { saveErrorText } from "../confirm.js";
import { CausedBySection, CausesSection } from "./FailureLinks.jsx";
import { failureRows, failureStatusWords, failureSummary, taskServes } from "../explorerRcm.js";
import { AP_LABEL, AP_TONE } from "../fmea.js";
import { apWords } from "../fmeaWorksheet.js";
import { CriticalityGroup, FmeaGroup } from "./FmeaPanels.jsx";
import { PanelField } from "./PanelField.jsx";
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
    <svg className={type === "std" ? `${className} rw-ic-std` : className} viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">
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

// The small note mark after a row's name when it has notes and rationale:
// the notes' first line is its tooltip (and its accessible name). Not a
// button: the notes are read and edited in the row's details. Fixed size, so a
// row never changes height or width with it.
export function NotesMark({ r }) {
  if (!hasNotes(r)) return null;
  const tip = notesTip(r);
  return (
    <span className="rw-note-mark" role="img" aria-label={`Has notes: ${tip}`} title={tip}>
      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" aria-hidden="true">
        <path d="M3 2.5h7l3 3v8H3z M10 2.5v3h3 M5.5 8h5 M5.5 10.5h5" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    </span>
  );
}

// One cell's content (desktop).
// onWorking(functionId): open a decision's linked function notes (evidence
// type "working") in place (the Explorer); without it the link goes to their address.
export function Cell({ col, r, query, onDecision, readOnly, linkChecks, onWorking = null }) {
  if (r.type === "task") return <TaskCell col={col} r={r} />;
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
        if (r.ref.needs_review) {
          // Saved against the decision rules: the advice note the guide promises, in the cell.
          return (
            <span className="rw-txt rw-review" title={r.ref.advice || "This decision breaks the decision rules: look at it again."}>
              {decisionText(d)} <span className="rw-todo rw-review-note">· Needs review</span>
            </span>
          );
        }
        return <span className="rw-txt" title={[decisionText(d), d.notes].filter(Boolean).join(": ")}>{decisionText(d)}</span>;
      }
      {
        const own = r.sum.modes ? (r.sum.undecided
          ? <span className="rw-sum rw-todo" title={`${n(r.sum.undecided, "failure mode")} inside with no decision yet`}>{r.sum.undecided.toLocaleString("en-AU")} to decide</span>
          : r.sum.review
          ? <span className="rw-sum rw-todo" title={`${n(r.sum.review, "decision")} inside that break${r.sum.review === 1 ? "s" : ""} the decision rules: look again`}>{r.sum.review.toLocaleString("en-AU")} to review</span>
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
      // linkChecks (the Explorer): the chip opens the model, analysis or report
      // behind it; a function's linked notes open in the details beside the table.
      if (mode && linkChecks && d?.status && d.artifact_link_path) {
        const tip = `${d.artifact_name || "The evidence"}: ${d.summary || d.reason || ""}`.trim();
        if (onWorking && d.evidence_kind === "working" && d.working) {
          return (
            <button type="button" className="rw-cklink" title={tip}
                    onClick={(e) => { e.stopPropagation(); onWorking(d.working.id); }}>
              <RcmStatusBadge status={d.status} kind={d.evidence_kind} />
            </button>
          );
        }
        return (
          <Link to={d.artifact_link_path} className="rw-cklink" onClick={(e) => e.stopPropagation()} title={tip}>
            <RcmStatusBadge status={d.status} kind={d.evidence_kind} />
          </Link>
        );
      }
      if (mode && d?.status === "unevidenced") {
        // Nothing linked yet: quiet, not a warning (most RCM is done from judgement).
        return <span className="rw-quiet" title="No evidence linked yet"><span aria-hidden="true">–</span><span className="sr-only">No evidence linked yet</span></span>;
      }
      if (mode) return d?.status ? <RcmStatusBadge status={d.status} kind={d.evidence_kind} /> : null;
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
        onWorking && d.evidence_kind === "working" && d.working
          ? <button type="button" className="link rw-txt" onClick={(e) => { e.stopPropagation(); onWorking(d.working.id); }}>{d.artifact_name}</button>
          : d.artifact_link_path
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
    case "ap": {
      // The action priority: its word in a chip (the tone says it too, never alone).
      if (mode) {
        const ap = r.ref.ap;
        return ap ? <Chip tone={AP_TONE[ap]} className="rw-ap" title={`Action priority: ${AP_LABEL[ap]}`}>{AP_LABEL[ap]}</Chip> : null;
      }
      const text = col.text(r);
      return text ? <span className="rw-sum" title={apWords(r.sum)}>{text}</span> : null;
    }
    default: {
      const text = col.text(r);
      if (!text) return null;
      // A parent row's cell is a roll-up of what's inside it, in quieter type.
      const sum = !mode;
      const title = sum && col.id === "consequence" ? consequenceWords(r) : text;
      return <span className={sum ? "rw-sum" : "rw-txt"} title={title}>
        {col.edit === "text" ? <Highlight text={text} query={query} /> : text}
      </span>;
    }
  }
}

// A task row's cells (the tree's fifth level): its kind in the Decision column; how
// often, then "Serves N here" and "In: ‹package›" as chips, in the Task column.
function TaskCell({ col, r }) {
  const t = r.ref.task || {};
  if (col.id === "decision") {
    const kind = taskKindText(r);
    return kind ? <span className="rw-txt" title={kind}>{kind}</span> : null;
  }
  if (col.id !== "task") return null;
  const every = everyText(t);
  const shared = taskSharedText(t);
  if (!every && !shared && !t.package) return null;
  return (
    <span className="rw-txt rw-taskrow" title={col.text(r)}>
      {every && <span className="rw-task-t">{every}</span>}
      {shared && <Chip className="rw-tchip" title={taskServesTip(t)}>{shared}</Chip>}
      {t.package && <Chip className="rw-tchip" title={`Done on the visits of the work package ${t.package.name}`}>In: {t.package.name}</Chip>}
    </span>
  );
}

// A cell being edited in place: Enter or leaving it keeps the change; Escape
// drops it. A value the server would refuse stays open with the reason.
// `onCommit` returns true (kept), the reason it isn't (a string), or a promise
// of either (the Explorer writes at once): meanwhile the cell keeps the text
// as typed (read-only, so it's sent once), and if it isn't saved it stays open
// with that text, to try again or Escape.
export function CellEditor({ col, r, onCommit, onCancel }) {
  const d = r.ref.decision || {};
  // The column itself says which field it edits (the RCM's and the FME(C)A's
  // columns alike): a decision's field, or the mode's own.
  const start = col.id === "name" ? r.ref.text || ""
    : col.id === "consequence" ? r.ref.consequence || ""
    : col.id === "interval" ? d.interval ?? ""
    : col.onDecision ? d[col.field] ?? "" : r.ref[col.field] ?? "";
  const [value, setValue] = useState(String(start));
  const [busy, setBusy] = useState(false);
  // Why the value wasn't kept: shown in a bubble under the cell (the whole
  // reason, as the drag refusal shows), the cell outlined red, its text kept.
  const [refused, setRefused] = useState(null);
  const done = useRef(false);
  const field = useRef(null);
  const commit = (v = value) => {
    if (done.current) return;
    if (String(v) === String(start)) { done.current = true; onCancel(); return; }
    const out = onCommit(v);
    if (out === true) done.current = true;
    else if (typeof out === "string") { setRefused(out); field.current?.focus({ preventScroll: true }); }
    else if (out && typeof out.then === "function") {
      done.current = true;
      setBusy(true);
      out.then((ok) => {
        if (ok === true) return;
        done.current = false;
        setBusy(false);
        if (typeof ok === "string") setRefused(ok);
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
  if (col.edit === "choice") {
    // One tap: the choices as chips under the cell (the Decide dialog's
    // tiles); ← → move, Enter or a click chooses, Escape or leaving them drops
    // it. The Consequence column's choices, or the column's own `options`
    // (the FME(C)A's status, rate source and severity class).
    const labels = col.labels || CONSEQUENCE_LABEL;
    const options = col.options || Object.entries(CONSEQUENCE_LABEL).map(([v, l]) => ({ value: v, label: l }));
    return (
      <span className="rw-edit-wrap rw-edit-chips" ref={field} tabIndex={-1}
            onBlur={(e) => {
              const to = e.relatedTarget;
              if (busy || (to && (e.currentTarget.contains(to) || to.closest?.(".rw-pop-under")))) return;
              done.current = true;
              onCancel();
            }}>
        <span className="rw-txt">{labels[value] || "Not set"}</span>
        <Popover>
          <ChoiceChips label={label} value={value} moveOnly autoFocus disabled={busy}
                       options={[...options, { value: "", label: "Not set" }]}
                       onKeyDown={keys}
                       onChange={(v) => { setValue(v); setRefused(null); commit(v); }} />
          {refused && <span className="rw-cell-why" role="alert">{refused}</span>}
        </Popover>
      </span>
    );
  }
  // A function's text: kept to 200 characters, with a counter at its end.
  const count = col.id === "name" && r.type === "fn" ? functionCount(value, r.ref.text || "") : null;
  // A number cell: the task interval (positive), or a column with its own
  // `range` (a score 1–10, a share 0–1, a rate ≥ 0); a date cell as a date.
  const num = col.edit === "number";
  const range = col.range || (col.id === "interval" ? { min: 0 } : null);
  return (
    <span className="rw-edit-wrap">
      <input className="rw-edit" autoFocus ref={field} aria-label={label} value={value} onKeyDown={keys} readOnly={busy} aria-busy={busy || undefined}
             maxLength={count ? FUNCTION_MAX : undefined} title={count ? FUNCTION_NUDGE : col.title || undefined}
             aria-description={count ? `${count.n} of ${count.max} characters. ${FUNCTION_NUDGE}` : refused || undefined}
             aria-invalid={count?.over || refused ? "true" : undefined}
             type={num ? "number" : col.edit === "date" ? "date" : "text"} inputMode={num ? (range?.integer ? "numeric" : "decimal") : undefined}
             min={num && range?.min != null ? String(range.min) : undefined} max={num && range?.max != null ? String(range.max) : undefined}
             step={num ? (range?.integer ? "1" : "any") : undefined}
             onChange={(e) => { setValue(e.target.value); setRefused(null); }} onBlur={() => commit()} />
      {col.id === "interval" && <span className="rw-unit">{d.interval_unit || "hours"}</span>}
      {count && <span className={"char-count rw-count" + (count.tone ? ` ${count.tone}` : "")} aria-hidden="true">{count.text}</span>}
      {refused && (
        <Popover>
          <span className="rw-cell-why" role="alert">{refused}</span>
        </Popover>
      )}
    </span>
  );
}

// A small box fixed under the table cell it's drawn in (a cell being
// edited), drawn in the shared portal host so the cell's clipping can't cut
// it, and kept on screen at the edges. A probe in the cell finds the cell.
function Popover({ children }) {
  const probe = useRef(null);
  const [at, setAt] = useState(null);
  useLayoutEffect(() => {
    const place = () => {
      const el = probe.current?.closest(".rw-c") || probe.current?.parentElement;
      if (!el) return;
      const b = el.getBoundingClientRect();
      setAt({ left: Math.max(8, Math.min(b.left, window.innerWidth - 328)), top: b.bottom + 4 });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, []);
  return (
    <>
      <span ref={probe} hidden />
      {createPortal(
        <div className="rw-pop-under" style={at ? { left: at.left, top: at.top } : { visibility: "hidden" }}>{children}</div>,
        portalHost(),
      )}
    </>
  );
}

// A row's status on a phone: a mode's evidence check (on the FME(C)A tab, its
// action priority), a parent's count to look at.
export function PhoneStatus({ r, fmea = false }) {
  if (r.type === "mode") {
    if (fmea) {
      const ap = r.ref.ap;
      return ap ? <Chip tone={AP_TONE[ap]} className="rw-ap">{AP_LABEL[ap]}</Chip> : null;
    }
    if (r.ref.decision && r.ref.needs_review) return <Chip tone="warning" title={r.ref.advice || undefined}>Needs review</Chip>;
    const s = shownStatus(r.ref.decision?.status);
    return s ? <RcmStatusBadge status={s} kind={r.ref.decision?.evidence_kind} /> : null;
  }
  if (fmea) return r.sum.high ? <Chip tone="danger" className="rw-ap">{r.sum.high} high</Chip> : null;
  if (r.sum.contradicted) return <span className="rw-ck contradicted">✗{r.sum.contradicted}<span className="sr-only"> contradicted</span></span>;
  if (r.sum.undecided) return <span className="rw-sum rw-todo">{r.sum.undecided} to decide</span>;
  if (r.sum.review) return <span className="rw-sum rw-todo">{r.sum.review} to review</span>;
  return null;
}

// The details panel for the row picked: every field, the decision, the tasks,
// adding inside and deleting. Beside the table at its usual width (a click on
// a row), or filling the table's room (`expanded`: a double-click on a row's
// name, Open… in its menu, or Expand here), with the tree column still beside
// it so another row can be picked; the panel follows the row picked. Every
// field is kept as you go (when you leave it, or Enter in a one-line field),
// and says "✓ Saved" by its label when it is; a value the server would refuse
// stays as typed with the reason under it. Escape (or Back to table) returns
// from expanded to side by side; Escape again closes.
//
// Its head: the kind, then Expand, ⋯ (add inside, delete) and Close as icon
// buttons; one line "in ‹the way up›"; the title, which is the description
// (a click edits it in place); status chips under it. Delete is also red
// text in the footer (it still asks first).
// The kinds of row whose description is edited (not a position's, nor the
// unassigned failure modes' or the "No standard" heading, in the Explorer).
// A standard's description is its text.
export const EDITABLE = new Set(["fn", "std", "fail", "mode"]);

// A failure mode's step heading: "1. Failure effects" (the standard RCM terms, Derryn, 9 Nov 2026).

// A status chip's tone from its words (the words always say it too).
const toneOf = (text) => (/to decide|to review|not analysed|no functional failure|no failure modes|nothing inside|not finished/i.test(text) ? "warning"
  : /all decided|covered/i.test(text) ? "success" : "neutral");

//   r          the row (cellRow: sum is its own counts)
//   display    the tree as shown (the way up); whole: the whole tree (what's inside)
//   ops        the Explorer's ops (useTreeRcm, with functionPdfs, notesView, standards, tasks, saveItem)
//   links      { onLink, onUnlink } (a functional failure's links)
//   expanded   filling the table's room; onExpand / onCollapse switch it (none on a phone)
//   addStart   {key, list, at}: open one of this row's lists on its add row (a row menu's Add …):
//              list "std" (a function's performance standards), "inside" (what's inside it), "task" (a mode's tasks)
//   onSaid     (text) a few words in the page's status line once something saved
//   onMove     (r, {task}) opens Move to… for the row (or a failure mode's task); none: no Move in the ⋯
//   fmea       {on, opts, rcm}: the FME(C)A's fields on a failure mode (FmeaPanels.jsx), shown only when
//              that tab is `on` (then first, and a function lists its failure modes, added directly
//              under it); `opts` the action priority table (fmea.js readFmeaOptions); `rcm` the read
//   options    the server's RCM options (step 3's chips, the evidence picker); workings: the
//              function notes a decision can link (explorerRcm.js workingsFor)
export function Details({
  r, display, whole = display, readOnly, onCommit, onAdd, onDelete, onDecision, onClose, onSelect, phone, headingRef, ops, links,
  expanded = false, onExpand = null, onCollapse = null, addStart = null, onSaid = null, onMove = null, fmea = null,
  options = null, workings = [],
}) {
  const level = LEVEL_OF[r.type];
  const d = r.ref.decision;
  const up = ancestorsOf(display, r.key).map((k) => display.rows.get(k)).filter(Boolean);
  // A task's row: its failure mode's row holds the decision, and every save goes through it.
  const isTask = r.type === "task";
  const modeRow = isTask ? whole.rows.get(r.ref.mode_id) || null : null;
  const confirm = useConfirm();
  const tasks = r.type === "mode" ? tasksOf(r.ref) : [];
  // "✓ Saved" by a field's label: a count per field that goes up on each save.
  const [saved, setSaved] = useState({});
  useEffect(() => setSaved({}), [r.key]);
  const markSaved = (col) => setSaved((s) => ({ ...s, [col]: (s[col] || 0) + 1 }));
  const keep = (col, out) => {
    if (out === true) markSaved(col);
    else if (out && typeof out.then === "function") return out.then((v) => { if (v === true) markSaved(col); return v; });
    return out;
  };
  const field = (label, col, { area, help, locked = false, optional = false, labelHidden = false, placeholder = null } = {}) => {
    const column = col === "name" ? NAME_COLUMN : COLUMN[col];
    const value = col === "name" ? r.ref.text || "" : column.onDecision ? d?.[column.field] ?? "" : r.ref[column.field] || "";
    return (
      <PanelField key={`${r.key}:${col}`} label={label} help={help} value={value} area={area} readOnly={readOnly || locked} optional={optional}
                  type={col === "interval" ? "number" : "text"} suffix={col === "interval" ? d?.interval_unit || "hours" : null}
                  labelHidden={labelHidden} placeholder={placeholder} saved={labelHidden ? 0 : saved[col]} onCommit={(raw) => keep(col, onCommit(r, col, raw))} />
    );
  };
  // A standard's limit field, kept at once (as the table's cells are).
  const saveStd = (col, raw) => {
    const res = checkValue(col, r, raw);
    if (res.error) return res.error;
    return ops.saveItem(r, { [col]: res.value }).then(() => { onSaid?.("Saved."); markSaved(col); return true; },
      (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  const stdField = ({ col, label, placeholder, optional = false }) => (
    <PanelField key={`${r.key}:${col}`} label={label} value={String(r.ref[col] ?? "")} readOnly={readOnly} placeholder={placeholder}
                optional={optional} saved={saved[col]} onCommit={(raw) => saveStd(col, raw)} />
  );
  const [stdFailed, setStdFailed] = useState(null);
  useEffect(() => setStdFailed(null), [r.key]);
  // What's inside: a function's functional failures (through its standard
  // rows), a standard's functional failures, a failure's failure modes.
  const inTree = whole.rows.get(r.key) || r;
  // On the FME(C)A tab a function's list is its failure modes (added directly
  // under it, with no functional failure yet).
  const fmeaFn = !!fmea?.on && r.type === "fn";
  const kids = fmeaFn ? (inTree.kids || []).map((k) => whole.rows.get(k)).filter((k) => k?.type === "mode")
    : r.type === "fn" ? failureRows(whole, inTree)
    : (inTree.kids || []).map((k) => whole.rows.get(k)).filter((k) => k && (k.type === "fail" || k.type === "mode"));
  const where = display.rows.get(r.ref.position_id)?.ref.name || whole.rows.get(r.ref.position_id)?.ref.name;
  const said = (text) => onSaid?.(text);
  // A task's name, kept on the task (a shared task's name changes for every mode it serves).
  const saveTaskName = (raw) => {
    const text = String(raw ?? "").trim();
    if (!text) return "Every task needs a name.";
    return ops.editTask(r.ref.task_id, { name: text }).then(() => { said("Saved the task."); return true; },
      (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  const canExpand = !phone && onExpand && onCollapse;
  const name = nameOf(r);
  const kindWord = level.label.toLowerCase();
  const addLabel = (r.type === "fn" && !fmeaFn) || r.type === "std" || r.type === "nostd" ? "Add a functional failure" : "Add a failure mode";
  // What's inside it is listed (and added to, in place) here: a function's,
  // a standard's and the "No performance standard" row's functional failures;
  // a functional failure's and the "Not under a functional failure" row's failure modes.
  const insideList = !!ops?.create && (EDITABLE.has(r.type) || r.type === "nostd" || r.type === "unassigned") && r.type !== "mode";
  // A row menu's Add … (or the ⋯ here): that list's add row, opened.
  const [ownStart, setOwnStart] = useState(null);
  useEffect(() => setOwnStart(null), [r.key]);
  const startOf = (list) => {
    const from = addStart?.key === r.key && addStart.list === list ? addStart.at : null;
    const own = ownStart?.list === list ? ownStart.at : null;
    return from == null && own == null ? null : Math.max(from ?? 0, own ?? 0);
  };
  // Everything under it goes too (the old single standard text is only cleared).
  const deleteLabel = r.type === "std" && r.ref?.legacy ? "Remove this performance standard" : `Delete this ${kindWord}`;
  // A task comes off this failure mode (a shared one stays with the others), or is retired.
  const shared = isTask && !!r.ref.task?.shared_with;
  const removeTaskLabel = shared ? "Remove from this failure mode" : "Retire the task";
  const removeTask = async () => {
    if (!modeRow || !ops?.removeTask) return;
    const ok = await removeTaskFromMode({ confirm, ops, mode: modeRow, task: r.ref.task, onSaid: said });
    if (ok) onSelect?.(modeRow.key);
  };
  const headItems = readOnly ? [] : isTask ? (modeRow && ops?.removeTask ? [{ id: "remove-task", label: `${removeTaskLabel}…`, danger: true, onSelect: removeTask }] : []) : [
    ...(level.child ? [{ id: "add", label: `${addLabel}…`, onSelect: () => (insideList ? setOwnStart({ list: "inside", at: Date.now() }) : onAdd(r)) }] : []),
    // Move to… (the one picker every kind uses), and a failure mode's Move a task….
    ...(onMove && EDITABLE.has(r.type) && !(r.type === "std" && r.ref.legacy) ? [{ id: "move-to", label: "Move to…", onSelect: () => onMove(r) }] : []),
    ...(onMove && r.type === "mode" && tasks.some((t) => t.id) ? [{ id: "move-task", label: "Move a task…", onSelect: () => onMove(r, { task: true }) }] : []),
    ...(EDITABLE.has(r.type) ? [{ id: "delete", label: `${deleteLabel}…`, danger: true, onSelect: () => onDelete(r) }] : []),
  ];
  // The status chips under the title.
  const chips = isTask
    ? [
      taskKindText(r) ? { text: taskKindText(r), tone: "accent" } : { text: "Not in a decision yet", tone: "warning" },
      everyText(r.ref.task) ? { text: everyText(r.ref.task), tone: "neutral" } : null,
      taskSharedText(r.ref.task) ? { text: taskSharedText(r.ref.task), tone: "neutral", title: taskServesTip(r.ref.task) } : null,
      r.ref.task?.package ? { text: `In: ${r.ref.task.package.name}`, tone: "neutral", title: "Done on this work package's visits" } : null,
    ].filter(Boolean)
    : r.type === "mode"
    ? [
      consequenceText(r.ref) ? { text: consequenceText(r.ref), tone: "neutral" } : null,
      d ? { text: [decisionText(d), d.interval && !isCombination(d) ? `every ${intervalText(d)}` : null].filter(Boolean).join(" · "), tone: "accent" }
        : { text: "No decision yet", tone: "warning" },
      // A saved decision that breaks the decision rules: not decided until it's looked at again.
      d && r.ref.needs_review ? { text: "Needs review", tone: "warning", title: r.ref.advice || undefined } : null,
    ].filter(Boolean)
    : (insideWords(r) || "").split(" · ").filter(Boolean).map((t) => ({ text: t, tone: toneOf(t) }));
  const limitNow = r.type === "std" ? limitReads(r.ref) : "";
  // A standard of the list keeps its limit as data (parameter, comparator, value, unit, when, source): folded.
  const checkable = r.type === "std" && !r.ref.legacy && !!ops?.saveItem;
  const limitSet = checkable && ["parameter", "comparator", "value", "unit", "when", "source"].some((k) => String(r.ref[k] ?? "").trim());
  const [limitOpen, setLimitOpen] = useState(false);
  useEffect(() => setLimitOpen(false), [r.key]);
  const inside = (
    <InsideList key={`${r.key}:inside`} r={r} kids={kids} ops={ops} readOnly={readOnly} addLabel={addLabel} addStart={startOf("inside")}
                status={r.type === "fail" ? failureStatusWords(r) : null} onSelect={onSelect} onSaid={said} />
  );
  // The RCM's two questions, in order (SAE JA1011, RCM II): evident or hidden,
  // then the category; for a hidden failure, what the multiple failure would do.
  const answers = r.type === "mode" ? modeAnswers(r.ref) : null;
  const hiddenValue = answers?.hidden === true ? "hidden" : answers?.hidden === false ? "evident" : "";
  const consequenceField = r.type === "mode" && (
    <>
      <Field label="Hidden failure?" saved={saved.hidden} className="rw-eyebrow"
             help={fmea?.on ? "Hidden: the crew wouldn't notice the loss of function in normal operation, until something else fails too." : null}>
        {readOnly ? <span className="rw-fval">{EVIDENT_LABEL[hiddenValue] || "Not set"}</span> : (
          <ChoiceChips label="Hidden failure?" clearable value={hiddenValue}
                       options={Object.entries(EVIDENT_LABEL).map(([value, label]) => ({ value, label }))}
                       onChange={(v) => keep("hidden", onCommit(r, "hidden", v))} />
        )}
      </Field>
      <Field label="Consequence category" saved={saved.consequence} className="rw-eyebrow"
             help={!fmea?.on ? null : answers?.hidden ? "The consequence of the multiple failure: the hidden failure plus the one it protects against." : "The first that applies: safety, environmental, operational, non-operational."}>
        {readOnly ? <span className="rw-fval">{CATEGORY_LABEL[answers.consequence] || "Not set"}</span> : (
          <ChoiceChips label="Consequence category" clearable value={answers.consequence || ""}
                       options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))}
                       onChange={(v) => keep("consequence", onCommit(r, "consequence", v))} />
        )}
      </Field>
    </>
  );
  // The RCM tab's step 2 as grid rows: "2 · Hidden failure?" and "Consequence", chips only.
  const consequenceRows = r.type === "mode" && (
    <>
      <StepLabel n={2} saved={saved.hidden}>Hidden failure?</StepLabel>
      <div className="rw-sc">
        {readOnly ? <span className="rw-fval">{EVIDENT_LABEL[hiddenValue] || "Not set"}</span> : (
          <ChoiceChips label="Hidden failure?" clearable value={hiddenValue} className="sm"
                       options={Object.entries(EVIDENT_LABEL).map(([value, label]) => ({ value, label }))}
                       onChange={(v) => keep("hidden", onCommit(r, "hidden", v))} />
        )}
      </div>
      <StepLabel saved={saved.consequence}>Consequence</StepLabel>
      <div className="rw-sc">
        {readOnly ? <span className="rw-fval">{CATEGORY_LABEL[answers.consequence] || "Not set"}</span> : (
          <ChoiceChips label="Consequence category" clearable value={answers.consequence || ""} className="sm"
                       options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))}
                       onChange={(v) => keep("consequence", onCommit(r, "consequence", v))} />
        )}
      </div>
    </>
  );
  // Link evidence… (step 3's Evidence): the evidence picker alone, in a small dialog.
  // {at}: a combination's member's own evidence (its index), or the decision's (at null).
  const [linkingEvidence, setLinkingEvidence] = useState(null);
  useEffect(() => setLinkingEvidence(null), [r.key]);
  // Step 3's open "Evidence": the evidence (Link evidence… when none), what it says and a
  // combination's members' own evidence. The rationale is the failure mode's notes and
  // rationale under its title: one place (Derryn, 9 Nov 2026).
  const evidenceOf = (m, { bare = false } = {}) => {
    const d = m.ref.decision;
    return (
    <>
      <div className="rw-evidence">
        {!bare && <span className="rw-evlabel">Evidence</span>}
        {d.status === "unevidenced" ? (
          <>
            None linked{!readOnly && ops?.decide && <> · <button type="button" className="link" onClick={() => setLinkingEvidence({ at: null })}
                                                 title="Link the model, analysis, report or function notes behind this decision (optional)">Link evidence…</button></>}
          </>
        ) : (
          <>
            {d.status && <RcmStatusBadge status={d.status} kind={d.evidence_kind} />}
            {d.artifact_name && (d.evidence_kind === "working" && d.working && onSelect
              ? <button type="button" className="link" onClick={() => onSelect(d.working.id, { notes: true })}
                        title="Open the function's notes and rationale">{d.artifact_name}</button>
              : d.artifact_link_path
                ? <Link to={d.artifact_link_path}>{d.artifact_name}</Link> : <span>{d.artifact_name}</span>)}
            {!d.status && !d.artifact_name && "None needed"}
            {!readOnly && ops?.decide && (
              <> · <button type="button" className="link" onClick={() => setLinkingEvidence({ at: null })}
                           title="Link other evidence, or none">Change evidence…</button></>
            )}
          </>
        )}
      </div>
      {d.status !== "unevidenced" && (d.summary || d.reason) ? <p className="rw-dwhy">{d.summary || d.reason}</p> : null}
      {isCombination(d) && d.outcomes.some((o) => o.status) && (
        <ul className="rw-members">{d.outcomes.filter((o) => o.status).map((o, i) => <li key={`${o.outcome}:${i}`}>{memberEvidenceLine(o)}</li>)}</ul>
      )}
    </>
    );
  };
  // A failure mode's Rationale row (Derryn, 9 Nov 2026): its first line "Based on:" the
  // evidence as citations (the linked model, analysis, report or function notes, with Link… /
  // Change…), the evidence's status at its right; a combination's members' own evidence and
  // what the evidence shows under it. Per-task evidence stays on the task's own panel.
  const basedOn = r.type === "mode" && d && (
    <div className="rw-basedon-wrap">
      <div className="rw-basedon rw-evidence" role="group" aria-label="Evidence">
        <span className="rw-basedon-lead">Based on:</span>
        <span className="rw-basedon-cites">
          {d.artifact_name ? (d.evidence_kind === "working" && d.working && onSelect
            ? <button type="button" className="link" onClick={() => onSelect(d.working.id, { notes: true })}
                      title="Open the function's notes and rationale">{d.artifact_name}</button>
            : d.artifact_link_path ? <Link to={d.artifact_link_path}>{d.artifact_name}</Link> : <span>{d.artifact_name}</span>)
            : <span className="rw-basedon-none">{d.status === "unevidenced" ? "nothing linked yet" : "judgement (none needed)"}</span>}
          {!readOnly && ops?.decide && (
            <> · <button type="button" className="link" aria-label={d.status === "unevidenced" ? "Link evidence…" : "Change evidence…"}
                         title={d.status === "unevidenced" ? "Link the model, analysis, report or function notes behind this decision (optional)" : "Link other evidence, or none"}
                         onClick={() => setLinkingEvidence({ at: null })}>{d.status === "unevidenced" ? "Link…" : "Change…"}</button></>
          )}
        </span>
        <span className="rw-basedon-status">
          {d.status === "unevidenced" ? <Chip>None linked</Chip>
            : d.status ? <RcmStatusBadge status={d.status} kind={d.evidence_kind} /> : null}
        </span>
      </div>
      {d.status !== "unevidenced" && (d.summary || d.reason) ? <p className="rw-dwhy">{d.summary || d.reason}</p> : null}
      {isCombination(d) && d.outcomes.some((o) => o.status) && (
        <ul className="rw-members">{d.outcomes.filter((o) => o.status).map((o, i) => <li key={`${o.outcome}:${i}`}>{memberEvidenceLine(o)}</li>)}</ul>
      )}
    </div>
  );
  // A task's own evidence: a combination's member has its own (or the decision's stands for
  // it); the one task of a plain decision has the decision's.
  // One line, as the failure mode's "Based on": the evidence as a link (or "nothing linked
  // yet"), Link… / Change…, and its status chip at the right. A plain decision's one task has
  // the decision's evidence; a combination's member its own (or the decision's stands for it).
  const taskEvidence = isTask && modeRow && (() => {
    const md = modeRow.ref.decision;
    if (!md) return <p className="rim-tquiet">Decide the failure mode first: evidence is linked to its decision.</p>;
    const at = isCombination(md) ? md.outcomes.findIndex((o) => o.task_id === r.ref.task_id) : null;
    if (at != null && at < 0) return <p className="rim-tquiet">Linked beside the decision, so it has no evidence of its own.</p>;
    const e = at != null ? md.outcomes[at] : md;
    const own = at == null || !!e.evidence;
    const none = !e.status || e.status === "unevidenced";
    const name = own ? e.artifact_name : null;
    return (
      <div className="rw-basedon rw-evidence" role="group" aria-label="Evidence">
        <span className="rw-basedon-cites">
          {name ? (e.artifact_link_path ? <Link to={e.artifact_link_path}>{name}</Link> : <span>{name}</span>)
            : <span className="rw-basedon-none">{at != null && !none ? memberEvidenceText(e) : none ? "nothing linked yet" : "judgement (none needed)"}</span>}
          {!readOnly && ops?.decide && (
            <> · <button type="button" className="link" aria-label={none ? "Link evidence…" : "Change evidence…"}
                         title="The model, analysis, report or function notes behind this task (optional)"
                         onClick={() => setLinkingEvidence({ at })}>{none ? "Link…" : "Change…"}</button></>
          )}
        </span>
        <span className="rw-basedon-status">
          {none ? <Chip>None linked</Chip> : <RcmStatusBadge status={e.status} kind={e.evidence_kind} />}
        </span>
      </div>
    );
  })();
  const serves = isTask ? taskServes(whole, r.ref.task_id) : [];
  // Run to failure's action on failure, kept as you go in step 3 (a scheduled decision's task
  // is a task card, or the task form while it has none: RcmModeTasks).
  const ownBlock = r.type === "mode" && !readOnly && d?.outcome === "rtf" && COLUMN.task.can(r)
    ? field("What's done on failure", "task", { area: true, optional: true, labelHidden: true, placeholder: "Corrective action on failure" }) : null;
  // The FME(C)A's two groups on a failure mode (FmeaPanels.jsx): each field
  // kept as you go, as the others are; the RPN and action priority previewed
  // from the scores as they're typed.
  const fmeaGroups = r.type === "mode" && fmea && (
    <>
      <FmeaGroup key={`${r.key}:fmea`} r={r} opts={fmea.opts} readOnly={readOnly} saved={saved}
                 onCommit={(col, raw) => keep(col, onCommit(r, col, raw))} consequence={fmea.on ? consequenceField : null} />
      <CriticalityGroup key={`${r.key}:crit`} r={r} opts={fmea.opts} readOnly={readOnly} saved={saved}
                        onCommit={(col, raw) => keep(col, onCommit(r, col, raw))} />
    </>
  );
  return (
    <aside className={"rw-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented) return;
             // A dialog opened from the panel (Add another task, Decide…) is
             // portalled out of it, but React still bubbles its keys here:
             // its Escape closes the dialog, not the panel.
             if (!e.currentTarget.contains(e.target)) return;
             e.stopPropagation();
             if (expanded && canExpand) onCollapse();
             else onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind"><LevelIcon type={r.type} /> {level.label}</div>
          <div className="rw-panel-btns">
            {canExpand && (expanded ? (
              <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)"
                      aria-label="Back to table">
                <ShrinkIcon />
              </button>
            ) : (
              <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them"
                      aria-label="Expand the details">
                <ExpandIcon />
              </button>
            ))}
            {headItems.length > 0 && <MoreMenu label={`More for this ${kindWord}`} items={headItems} className="rw-x" />}
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        {up.length > 0 && <Crumbs up={up} onSelect={onSelect} />}
        <PanelTitle key={r.key} r={r} name={name} headingRef={headingRef} expanded={expanded}
                    editable={isTask ? !readOnly && !!ops?.editTask : EDITABLE.has(r.type) && !readOnly}
                    label={r.type === "std" ? "Performance standard" : isTask ? "Task" : "Description"}
                    help={r.type === "fn" ? (ops ? "What this position must do" : "What the system must do") : r.type === "std" ? "One parameter and one limit, e.g. pH 7.2-7.8"
                      : r.type === "fail" ? "How it fails to do it" : isTask ? "What's done, in a few words" : "What causes the failure"}
                    limit={r.type === "fn" ? { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE } : null}
                    onCommit={(raw) => keep("name", isTask ? saveTaskName(raw) : onCommit(r, "name", raw))} />
        {(chips.length > 0 || saved.name) && (
          <div className="rw-chips-row">
            {chips.map((c) => <Chip key={c.text} tone={c.tone} title={c.title}>{c.text}</Chip>)}
            {d?.status && shownStatus(d.status) && <RcmStatusBadge status={d.status} kind={d.evidence_kind} />}
            <SavedMark saved={saved.name} />
          </div>
        )}
        {/* The note the guide promises on a decision the rules wouldn't make now (and a hidden
            mode's missing category): kept as saved, with what to look at. */}
        {r.type === "mode" && r.ref.advice && (
          <p className={"rw-advice" + (r.ref.needs_review ? " rw-advice-review" : "")} role="note">{r.ref.advice}</p>
        )}
        {r.type === "mode" && ops && <ModeFailureReports modeId={r.ref.id} positionId={r.ref.position_id} />}
        {/* Notes and rationale come first among the sections, directly below the chips, the
            same section at every level: a failure mode's are its notes. */}
        {hasNotesField(r) && r.type !== "mode" && (
          <RcmNotes key={`${r.key}:notes`} r={r} readOnly={readOnly} onSave={(value) => keep("notes", onCommit(r, "notes", value))}
                    openToken={r.type === "fn" ? ops?.notesView?.token(r) ?? null : null}>
            {/* A function's notes hold the working behind its standards: its PDFs close the section. */}
            {r.type === "fn" && ops?.functionPdfs && <RcmFunctionPdfs r={r} files={ops.functionPdfs} readOnly={readOnly} />}
          </RcmNotes>
        )}
      </div>

      {/* One order at every level: the notes and rationale directly below the chips (above), then
          what's inside it (the next level down, as in the tree), then what belongs to this level,
          then the quieter things (the checkable limit, where it sits) last. */}
      <div className="rw-pbody">
        {/* The FME(C)A tab: a failure mode's two groups first (the end effect and the
            consequence are in the first), its decision and tasks after. */}
        {r.type === "mode" && fmea?.on && fmeaGroups}
        {/* 1. What's inside it. A function: its performance standards, then the functional
            failures under them. A standard (and "No performance standard"): its functional
            failures. A functional failure (and "Not under a functional failure"): its failure
            modes. A failure mode has no list here: its tasks come after its decision. */}
        {/* On the FME(C)A tab a function's details are about its failure modes: the
            performance standards stay on the RCM tab. */}
        {r.type === "fn" && ops?.standards && !fmea?.on && (
          <RcmFunctionStandards key={`${r.key}:std`} r={r} ops={ops} readOnly={readOnly} addStart={startOf("std")} onSaid={said} />
        )}
        {insideList && inside}

        {/* 2. This level's own. A functional failure: its links to failures on other
            positions. A failure mode: its three steps (below). */}
        {r.type === "fail" && ops && links && (
          <CausedBySection r={r} where={where} readOnly={readOnly} links={links} onSelect={onSelect} />
        )}
        {r.type === "fail" && ops && links && (
          <CausesSection r={r} where={where} readOnly={readOnly} links={links} onSelect={onSelect} />
        )}
        {/* A failure mode on the RCM tab: three numbered steps, the flow of the worksheet (Derryn,
            9 Nov 2026): what happens, how bad it is, what we do. The help sentences stay in the
            Decide dialog, where the choice is made; the decision is one card. */}
        {/* A failure mode on the RCM tab: its three steps as one grid, "step | choice", a row
            per question (Derryn, 9 Nov 2026). Each step is still a region of its own. */}
        {r.type === "mode" && !fmea?.on && (
          <section className="rw-sg rw-steps-first" aria-label="Failure effects">
            <StepLabel n={1} saved={saved.effects}>Failure effects</StepLabel>
            <div className="rw-sc">
              {field("Failure effects", "effects", { area: true, labelHidden: true, placeholder: "What's seen, what stops, what it costs" })}
            </div>
          </section>
        )}
        {r.type === "mode" && !fmea?.on && (
          <section className="rw-sg" aria-label="Failure consequences">{consequenceRows}</section>
        )}
        {(r.type === "mode" || isTask) && linkingEvidence && (isTask ? modeRow?.ref.decision : d) && (
          <EvidenceDialog r={isTask ? modeRow : r} at={linkingEvidence.at} options={options} workings={workings} ops={ops}
                          onClose={() => setLinkingEvidence(null)}
                          onDone={() => { setLinkingEvidence(null); said("Saved the evidence."); }} />
        )}
        {r.type === "mode" && (
          <section className={"rw-sgwrap" + (fmea?.on ? " rw-steps-first" : "")} aria-label="Proactive task or default action">
            <RcmModeTasks key={`${r.key}:tasks`} r={r} ops={ops} readOnly={readOnly} addStart={startOf("task")} onSaid={said}
                          options={options} own={ownBlock} onPick={onSelect ? (k) => onSelect(k) : null}
                          n={fmea?.on ? null : 3} />
          </section>
        )}
        {/* The foot of a failure mode's grid: its rationale, based on its evidence (Derryn,
            9 Nov 2026), in place of the notes over the steps and the separate Evidence row. */}
        {r.type === "mode" && (
          <section className="rw-sg rw-rationale" aria-label="Rationale">
            <StepLabel>Rationale</StepLabel>
            <div className="rw-sc">
              <RcmNotes key={`${r.key}:notes`} r={r} readOnly={readOnly} bare lead={basedOn}
                        onSave={(value) => keep("notes", onCommit(r, "notes", value))} />
            </div>
          </section>
        )}
        {/* A task (the tree's fifth level): what it is and how often, what's done when its check
            finds it, its instructions, then its evidence, the failure modes it serves and what doing
            it needs (its LSA record, changed on the LSA tab). */}
        {isTask && modeRow && <RcmTaskSections key={`${r.key}:task`} r={r} mode={modeRow} ops={ops} readOnly={readOnly} onSaid={said} />}
        {isTask && modeRow && (
          <section className="rw-sg" aria-label="Based on">
            <StepLabel>Based on</StepLabel>
            <div className="rw-sc rim-tcell">{taskEvidence}</div>
          </section>
        )}
        {isTask && (
          <section className="rw-sg rw-serves" aria-label="Serves">
            <StepLabel>Serves</StepLabel>
            <div className="rw-sc rim-tcell">
              <p className="rim-tquiet">{`Serves ${n(serves.length, "failure mode")} here`}</p>
              <ul className="rw-servelist">
                {serves.map(({ key, mode }) => {
                  const here = mode.key === r.ref.mode_id;
                  const t = whole.rows.get(key)?.ref.task || r.ref.task;
                  return (
                    <li key={key}>
                      <button type="button" className="link rw-kgo" onClick={() => onSelect(mode.key)} title="Show the failure mode">
                        {nameOf(mode) || "(failure mode)"}
                      </button>
                      {here && <span className="rim-tquiet"> · this one</span>}
                      {serves.length > 1 && !readOnly && ops?.removeTask && (
                        <button type="button" className="link rw-serves-rm" aria-label={`Remove from “${nameOf(mode)}”`}
                                onClick={async () => {
                                  const ok = await removeTaskFromMode({ confirm, ops, mode, task: t, onSaid: said });
                                  if (ok && here) onSelect?.(mode.key);
                                }}>Remove</button>
                      )}
                    </li>
                  );
                })}
              </ul>
              {!readOnly && onMove && (
                <button type="button" className="link rim-tquietlink" onClick={() => onMove(r)}>Link to another failure mode…</button>
              )}
            </div>
          </section>
        )}
        {isTask && <TaskLogistics taskId={r.ref.task_id} positionId={r.ref.task?.position_id || r.ref.position_id} />}
        {/* 3. The quieter things, last. */}
        {/* Which standard a failure breaches is where it sits in the tree (moved by drag or Move
            to…); said here only when the way up doesn't show it (a pinned branch, say). */}
        {r.type === "fail" && r.ref.standard?.id && !up.some((a) => a.key === r.ref.standard.id) && (
          <div className="rw-foot">
            <p className="rw-fhelp rw-foot-note">Under the performance standard “{r.ref.standard.text}”.</p>
          </div>
        )}
        {r.type === "std" && (r.ref.legacy || checkable || (r.ref.function_has_notes && ops)) && (
          <div className="rw-foot">
            {r.ref.legacy && (
              <p className="rw-fhelp rw-foot-note">
                This is the function's one performance standard, as written. To make it a list (one row each, with a limit on each), pick the
                function and use <b>Add a performance standard</b> at the end of its list, or <b>Split into performance standards…</b> when the text is several joined by “;”.
              </p>
            )}
            {checkable && limitOpen && (
              <Section title="Checkable limit" label="Checkable limit" className="rw-limit"
                       action={{ label: "Hide", ariaLabel: "Hide the checkable limit", onClick: () => setLimitOpen(false) }}>
                <p className="rw-fhelp rw-sec-note">Write the limit as data so readings can be checked against it later.</p>
                {stdField({ col: "parameter", label: "Parameter" })}
                <LimitGroup r={r} readOnly={readOnly} saved={saved.limit} failed={stdFailed}
                            onComparator={(c) => {
                              setStdFailed(null);
                              ops.saveItem(r, { comparator: c }).then(() => { said("Saved."); markSaved("limit"); },
                                (err) => setStdFailed(saveErrorText(err, { offline: navigator.onLine === false })));
                            }}
                            onField={(col, raw) => {
                              const out = saveStd(col, raw);
                              if (out && typeof out.then === "function") out.then((v) => { if (v === true) markSaved("limit"); });
                              return out;
                            }} />
                <ReadsAs>{limitNow}</ReadsAs>
                {stdField({ col: "when", label: "When it applies", placeholder: "Always", optional: true })}
                {stdField({ col: "source", label: "Source", placeholder: "A standard, manual or study", optional: true })}
              </Section>
            )}
            {/* A standard's limit as data: folded away until it's wanted (nothing reads it yet).
                Set already: one line saying what it reads as, with Edit…. */}
            {checkable && !limitOpen && (
              <p className="rw-checkable">
                {limitSet ? (
                  <>
                    <span>Checkable: {limitNow || limitWords(r.ref)}</span>
                    {!readOnly && <> · <button type="button" className="link" onClick={() => setLimitOpen(true)} aria-label="Edit the checkable limit">Edit…</button></>}
                  </>
                ) : !readOnly && (
                  <button type="button" className="link" onClick={() => setLimitOpen(true)}>Make this checkable…</button>
                )}
              </p>
            )}
            {r.ref.function_has_notes && ops && (
              <p className="rw-fhelp rw-foot-note">
                The working behind it is in the function's notes and rationale:{" "}
                <button type="button" className="link" onClick={() => onSelect(r.ref.function_id, { notes: true })}>open them</button>.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Each button acts on its first click only: a double-click opens one dialog. */}
      {!readOnly && isTask && modeRow && ops?.removeTask && (
        <div className="rw-panel-acts">
          <button type="button" className="ghost sm rw-del" onClick={(e) => { if (e.detail < 2) removeTask(); }}>{removeTaskLabel}</button>
        </div>
      )}
      {!readOnly && ((level.child && !insideList) || EDITABLE.has(r.type)) && (
        <div className="rw-panel-acts">
          {/* The add lives at the end of its list (above); here only where there's no list. */}
          {level.child && !insideList && (
            <button type="button" className="secondary sm" onClick={(e) => { if (e.detail < 2) onAdd(r); }}>
              <PlusIcon /> {addLabel}
            </button>
          )}
          {EDITABLE.has(r.type) && (
            <button type="button" className="ghost sm rw-del" onClick={(e) => { if (e.detail < 2) onDelete(r); }}>{deleteLabel}</button>
          )}
        </div>
      )}
    </aside>
  );
}

// What's inside a row, in its details: a function's (or a standard's, or the
// "No performance standard" row's) functional failures, a functional
// failure's failure modes; each a link that shows it here. The list ends in
// its add row, which becomes a new row of the list: Enter or leaving it
// writes it (no dialog) and the add row is back for the next; the new one is
// opened from its link, like any other.
//
// `status`: a functional failure's state in words, said once at the head of
// its failure modes (it is about them, and the links below).
function InsideList({ r, kids, ops, readOnly, addLabel, addStart, status = null, onSelect, onSaid }) {
  const failures = addLabel === "Add a functional failure";
  const where = {
    positionId: r.ref.position_id,
    functionId: r.type === "fn" ? r.ref.id : r.type === "std" || r.type === "nostd" ? r.ref.function_id : null,
    standardId: r.type === "std" ? r.ref.standard_id ?? null : null,
    failureId: r.type === "fail" ? r.ref.id : null,
  };
  const add = useInlineAdd({
    disabled: readOnly,
    startToken: addStart,
    onSave: (text) => ops.create(failures ? "fail" : "mode", where, text)
      .then(() => { onSaid?.(failures ? "Added the functional failure." : "Added the failure mode."); }),
    errorText: (e) => saveErrorText(e, { offline: navigator.onLine === false }),
  });
  const kind = failures ? "fail" : "mode";
  return (
    <Section title={failures ? "Functional failures" : "Failure modes"} count={kids.length} className="rw-kids">
      {status && <p className="rw-fstatus">{status}</p>}
      {kids.length === 0 && !add.open && !status && (
        <p className="rw-fhelp">
          {r.type === "std" && !r.ref.legacy ? "None yet. A breach of this limit, e.g. “Alkalinity below 80 ppm”."
            : r.type === "fail" ? "No failure modes of its own yet." : "None yet."}
        </p>
      )}
      {(kids.length > 0 || add.open) && (
        <ul className="rw-klist">
          {kids.map((k) => (
            <li key={k.key}>
              <LevelIcon type={k.type} />
              <span className="rw-kbody">
                <button type="button" className="link rw-kgo" onClick={() => onSelect(k.key)}
                        title={`Show the ${LEVEL_OF[k.type].label.toLowerCase()}`}>
                  {nameOf(k) || `(${LEVEL_OF[k.type].label.toLowerCase()})`}
                </button>
                <span className={"rw-fhelp" + (k.type === "mode" && !k.ref.decision ? " rw-todo" : "")}>
                  {k.type === "fail" ? failureSummary(k) : k.ref.decision ? decisionText(k.ref.decision) : "To decide"}
                </span>
              </span>
            </li>
          ))}
          {add.open && (
            <InlineAddRow add={add} as="li" className="rw-knew" lead={<LevelIcon type={kind} />}
                          label={failures ? "New functional failure" : "New failure mode"}
                          placeholder={failures ? (r.type === "std" ? "e.g. pH above 7.8" : "e.g. No flow at all") : "e.g. Impeller worn"} />
          )}
        </ul>
      )}
      {!readOnly && !add.open && <InlineAddButton add={add}>{addLabel}</InlineAddButton>}
    </Section>
  );
}

// The title: the row's description, a heading. A click (or Enter on it)
// edits it in place: one box that grows with the text, kept on Enter or
// leaving it, Escape to drop the change; a refusal keeps the box open with
// the reason. A function's text has its counter (200 at most). A row with no
// text yet opens editing.
function PanelTitle({ r, name, headingRef, editable, label, help, limit, onCommit, expanded }) {
  const [editing, setEditing] = useState(editable && !r.ref.text);
  const [draft, setDraft] = useState(name || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const box = useRef(null);
  const grow = useAutoGrow(editing ? draft : null, box);
  useEffect(() => { if (!editing) setDraft(name || ""); }, [name, editing]);
  useEffect(() => {
    if (!editing) return;
    const el = box.current;
    if (el && document.activeElement !== el) { el.focus({ preventScroll: true }); el.setSelectionRange?.(el.value.length, el.value.length); }
  }, [editing]);
  const stop = () => {
    setEditing(false);
    setError(null);
    setTimeout(() => headingRef?.current?.focus({ preventScroll: true }), 0);
  };
  const commit = () => {
    if (busy) return;
    if (draft === (name || "")) { if (r.ref.text) stop(); return; }
    const out = onCommit(draft);
    if (typeof out === "string") { setError(out); return; }
    if (out && typeof out.then === "function") {
      setBusy(true);
      out.then((v) => {
        setBusy(false);
        if (typeof v === "string") setError(v);
        else { setError(null); setEditing(false); }
      });
      return;
    }
    setEditing(false);
  };
  const count = limit ? charCount(draft, { max: limit.max, before: name || "" }) : null;
  if (editing) {
    return (
      <Field label={label} className="rw-title-edit" error={error || (count?.over ? `${count.message}${limit?.nudge ? ` ${limit.nudge}` : ""}` : null)}
             help={limit?.nudge ? `${help}. ${limit.nudge}` : help}
             count={count ? <span className={"char-count" + (count.tone ? ` ${count.tone}` : "")}>{count.text}</span> : null}>
        <TextArea ref={grow} value={draft} readOnly={busy} aria-busy={busy || undefined} maxLength={limit ? limit.max : undefined}
                  className={"rw-title-box" + (expanded ? " big" : "")}
                  aria-description={count ? `${count.n} of ${count.max} characters.` : undefined}
                  onChange={(e) => { setDraft(e.target.value); }}
                  onBlur={commit}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
                    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setDraft(name || ""); if (r.ref.text) stop(); }
                  }} />
      </Field>
    );
  }
  return (
    <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef} title={name.length > 80 ? name : undefined}>
      {editable ? (
        <button type="button" className="rw-title-btn" onClick={() => setEditing(true)}
                aria-description={`Edit the ${label.toLowerCase()}`} title={`Click to edit the ${label.toLowerCase()}`}>
          {name || <span className="rw-blank">(no description yet)</span>}
        </button>
      ) : (name || <span className="rw-blank">(no description yet)</span>)}
    </h2>
  );
}

// A standard's limit: the comparator, the value and the unit as one control.
function LimitGroup({ r, readOnly, onComparator, onField, failed, saved }) {
  const [vals, setVals] = useState({ value: String(r.ref.value ?? ""), unit: String(r.ref.unit ?? "") });
  const [errs, setErrs] = useState({});
  const sent = useRef({});
  useEffect(() => { setVals({ value: String(r.ref.value ?? ""), unit: String(r.ref.unit ?? "") }); setErrs({}); sent.current = {}; }, [r.ref.value, r.ref.unit]);
  if (readOnly) {
    return (
      <Field label="Limit">
        <span className="rw-fval">{limitReads(r.ref) || "—"}</span>
      </Field>
    );
  }
  const commit = (col) => {
    const v = vals[col];
    if (v === String(r.ref[col] ?? "") || v === sent.current[col]) return;
    sent.current[col] = v;
    const out = onField(col, v);
    const fail = (text) => { sent.current[col] = null; setErrs((e) => ({ ...e, [col]: text })); };
    if (typeof out === "string") fail(out);
    else if (out && typeof out.then === "function") out.then((x) => { if (typeof x === "string") fail(x); else setErrs((e) => ({ ...e, [col]: null })); });
  };
  const error = failed || errs.value || errs.unit || null;
  return (
    <Field label="Limit" as="fieldset" saved={saved} error={error}
           help={r.ref.comparator === "between" ? "A range as “80-120”; one limit as a number." : null}>
      <InputGroup label="Limit">
        <Select aria-label="Comparator" value={r.ref.comparator || ""} onChange={(e) => onComparator(e.target.value)} className="rw-cmp">
          <option value="">—</option>
          {COMPARATORS.map((c) => <option key={c} value={c}>{COMPARATOR_LABEL[c]}</option>)}
        </Select>
        {["value", "unit"].map((col) => (
          <TextInput key={col} aria-label={col === "value" ? "Value" : "Unit"} value={vals[col]} id={undefined}
                     className={col === "unit" ? "ctl-unit" : undefined} placeholder={col === "value" ? "Value" : "Unit"}
                     aria-invalid={errs[col] ? "true" : undefined}
                     onChange={(e) => { setVals((x) => ({ ...x, [col]: e.target.value })); sent.current[col] = null; }}
                     onBlur={() => commit(col)}
                     onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(col); } }} />
        ))}
      </InputGroup>
    </Field>
  );
}

// The way up, on one muted line: the nearest kept, those above it folded
// into "…" when they don't fit (the whole path in its tooltip; a click on it
// shows them all, wrapped).
function Crumbs({ up, onSelect }) {
  const box = useRef(null);
  const [skip, setSkip] = useState(0);
  const [all, setAll] = useState(false);
  const path = up.map((a) => nameOf(a) || LEVEL_OF[a.type].label).join(" › ");
  const key = up.map((a) => a.key).join("/");
  useEffect(() => { setSkip(0); setAll(false); }, [key]);
  // Fold one more each pass until it fits (or only the nearest is left).
  useLayoutEffect(() => {
    const el = box.current;
    if (el && !all && el.scrollWidth > el.clientWidth + 1 && skip < up.length - 1) setSkip(skip + 1);
  }, [skip, all, up.length, key]);
  // A new width: start again from the whole path.
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver !== "function") return undefined;
    let w = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth !== w) { w = el.clientWidth; setSkip(0); }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const shown = all ? up : up.slice(skip);
  return (
    <nav ref={box} className={"rw-crumbs" + (all ? " all" : "")} aria-label="Inside" title={path}>
      <span className="rw-in">in</span>
      {!all && skip > 0 && (
        <button type="button" className="link rw-crumb-more" aria-label={`Show the whole way up: ${path}`} onClick={() => setAll(true)}>…</button>
      )}
      {shown.map((a) => (
        <button key={a.key} type="button" className="link" onClick={() => onSelect(a.key)} title={nameOf(a) || undefined}>
          {nameOf(a) || `(${LEVEL_OF[a.type].label.toLowerCase()})`}
        </button>
      ))}
    </nav>
  );
}

// The column chooser: tick the columns to show; the description is always
// shown. `columns`: the table's columns (the RCM's, or the FME(C)A tab's).
// With `open` given it has no button of its own: something else opens it (the
// Explorer heading's "…" › Columns…) and `onClose` closes it (a click away,
// Escape), focus going back to `returnFocus()`.
export function ColumnChooser({ cols, onCols, usual = DEFAULT_COLUMNS, columns = COLUMNS, open: openProp, onClose, returnFocus }) {
  const controlled = openProp !== undefined;
  const [openOwn, setOpenOwn] = useState(false);
  const open = controlled ? openProp : openOwn;
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (refocus) => {
      if (controlled) onClose?.();
      else setOpenOwn(false);
      if (refocus) returnFocus?.()?.focus?.();
    };
    const away = (e) => { if (!box.current?.contains(e.target)) close(false); };
    const esc = (e) => { if (e.key === "Escape") { e.preventDefault(); close(true); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    // Opened from a menu: the first box takes the focus, so the keyboard can tick.
    if (controlled) box.current?.querySelector("input")?.focus({ preventScroll: true });
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  if (controlled && !open) return null;
  return (
    <div className="rw-cols" ref={box}>
      {!controlled && (
        <button type="button" className="secondary rw-btn" aria-expanded={open} aria-haspopup="true" onClick={() => setOpenOwn((o) => !o)}
                aria-label="Columns" title="Choose which columns to show">
          Columns
        </button>
      )}
      {open && (
        <div className="rw-pop" role="group" aria-label="Columns to show">
          {columns.map((c) => (
            <label key={c.id} className="rw-pop-item" title={c.title}>
              <input type="checkbox" checked={cols.includes(c.id)}
                     onChange={(e) => onCols(e.target.checked ? columns.map((x) => x.id).filter((id) => id === c.id || cols.includes(id)) : cols.filter((x) => x !== c.id))} />
              {c.label}{c.sum ? <span className="rw-sig" title="A parent row counts what's inside it"> Σ</span> : null}
            </label>
          ))}
          <button type="button" className="link rw-pop-reset" onClick={() => onCols(usual, { reset: true })}>Show the usual columns</button>
        </div>
      )}
    </div>
  );
}

// Step 3's Link evidence… (or Change evidence…): the evidence picker alone, in
// a small dialog, the rest of the decision as it is. The evidence the outcome
// expects (run to failure: its reason's) is offered as the Models kind; a
// report or a function's notes go with any decision. Saved as the whole
// decision with the new evidence (or none); a refusal shows here.
// `at`: a combination's member (its index), whose own evidence this links (a task's details).
function EvidenceDialog({ r, at = null, options, workings, ops, onClose, onDone }) {
  const d = r.ref.decision;
  const member = at != null && isCombination(d) ? d.outcomes[at] || null : null;
  const start = member ? member.evidence : d.evidence;
  const [value, setValue] = useState(start?.type && start?.id ? start : null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const outcome = member ? member.outcome : d.outcome;
  const outcomeOpt = options?.outcomes?.find((o) => o.id === outcome);
  const expected = !member && d.outcome === "rtf"
    ? options?.rtf_bases?.find((b) => b.id === d.rtf_basis)?.expected_evidence || null
    : outcomeOpt?.expected_evidence || null;
  const analysisKind = expected === "strategy_analysis" ? (outcome === "failure_finding" ? "failure_finding" : "optimal_replacement") : null;
  const save = async () => {
    if (busy) return;
    setBusy(true);
    setFailed(null);
    try {
      const evidence = value ? { type: value.type, id: value.id } : null;
      await ops.decide(r, { consequence: r.ref.consequence || null,
        decision: member ? decisionWithMemberEvidence(d, at, evidence) : decisionBody(d, { evidence }) });
      onDone();
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="Link evidence" onClose={onClose} locked={busy} trapFocus className="rw-evidence-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save"}</button>
             </>
           )}>
      <p className="rw-fhelp">The model, analysis, report or function notes behind this {member ? "task" : "decision"} (optional).</p>
      <EvidencePicker expectedType={expected} analysisKind={analysisKind} value={value} onChange={setValue} workings={workings} />
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// A task's logistics in its details: a short summary of its LSA record (labour hours,
// tools, method), read when the task is picked, and "Open in LSA" for the whole record.
function TaskLogistics({ taskId, positionId }) {
  // On a product's page the link stays there (its design's LSA); elsewhere the Explorer's.
  const location = useLocation();
  const [state, setState] = useState({ id: null, data: null, error: null });
  useEffect(() => {
    let on = true;
    getTaskLsa(taskId).then((data) => { if (on) setState({ id: taskId, data, error: null }); },
      (e) => { if (on) setState({ id: taskId, data: null, error: e.message || "It didn't load." }); });
    return () => { on = false; };
  }, [taskId]);
  const here = state.id === taskId;
  const res = here ? state.data?.task?.resources || null : null;
  const method = String(res?.method || "").split("\n").map((l) => l.trim()).find(Boolean) || "";
  const tools = (res?.tools || []).length;
  const parts = res ? [
    res.labour_hours ? `${res.labour_hours.toLocaleString("en-AU", { maximumSignificantDigits: 4 })} labour hour${res.labour_hours === 1 ? "" : "s"}` : null,
    tools ? n(tools, "tool") : null,
    method ? `Method: ${method}` : null,
  ].filter(Boolean) : [];
  return (
    <section className="rw-sg rw-logistics" aria-label="Logistics">
      <StepLabel>Logistics</StepLabel>
      <div className="rw-sc rim-tcell">
        <p className="rim-tline">
          <span className="rim-tquiet">
            {!here ? "Reading…" : state.error ? `Couldn't read it: ${state.error}`
              : parts.length ? parts.join(" · ") : "No labour, tools or method set yet."}
          </span>
          {" · "}
          <Link to={explorerHere(location.pathname, location.search, { sel: positionId, tab: "lsa", task: taskId })}
                title="How it's done: its instructions, labour, tools, spares and method">Open in LSA</Link>
        </p>
      </div>
    </section>
  );
}
