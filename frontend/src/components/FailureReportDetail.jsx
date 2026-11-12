import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  addCorrectiveAction, getFailureReport, listFailureReports, listMaintenanceWorkOrders, raiseActionWorkOrder,
  saveFailureReportInvestigation, setFailureReportStatus, updateCorrectiveAction, verifyFailureReport,
} from "../api.js";
import { workOrderPath } from "../maintenanceOrders.js";
import {
  ACTION_STATUSES, MAX_WHYS, RESULTS, ROOT_CAUSES, STATUSES, canMoveTo, closeBlock, consequenceLabel, fmtWhen, historyRows,
  isOpen, itemText, lifeDataText, repeatSentence, resultLabel, rootCauseLabel, signOffText, stageOf, statusLabel,
} from "../failureReports.js";
import { SHORT_TEXT, tooLong } from "../maintenanceText.js";
import { useAuth } from "../AuthProvider.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import MaintenancePhotos from "./MaintenancePhotos.jsx";
import { Field, fmtDate } from "./MaintenanceParts.jsx";
import NewFailureReportModal from "./NewFailureReportModal.jsx";

// One failure report, in the Failure reports tab in place of the list: its
// stage on the loop (Reported › Investigating › Corrective action › Verifying
// › Closed, with Rejected aside), the facts, then the loop's cards in order,
// the one for the stage it's at open: Investigation (notes, root cause, the
// whys), Corrective actions (what, who, by when, done or dropped), Verification
// (did it work? with the repeat check beside it), Close (the sign-off) and
// Reject (the reason, a duplicate). Photos, then every change at the bottom.
// Every save shows a short message and the report as the server now has it;
// a refusal shows the server's words. `onStatusChanged`: the tree's roll-up
// counts open reports, so it's read again when a report opens or closes.

const CARD_OF_STAGE = { investigating: "investigation", corrective_action: "actions", verifying: "verification" };

// What happened, in a few words, when a save fails.
function failText(e) {
  const msg = e?.message || "";
  return !msg || msg === "Failed to fetch" || /NetworkError|Load failed/i.test(msg)
    ? "Couldn't save. Check your connection and try again." : msg;
}

// A card of the loop that folds: open when its stage is the current one (or
// toggled), its one-line summary in the heading while folded.
function Fold({ id, title, summary, open, onToggle, children, className = "" }) {
  return (
    <section className={`card td-card fr-card${open ? " is-open" : ""} ${className}`.trim()}>
      <h3 className="fr-card-h">
        <button type="button" className="fr-fold" aria-expanded={open} aria-controls={`fr-${id}`} onClick={() => onToggle(id)}>
          <span className="fr-fold-arrow" aria-hidden="true">{open ? "▾" : "▸"}</span> {title}
        </button>
        {!open && summary && <span className="lib-date fr-card-sum">{summary}</span>}
      </h3>
      {open && <div id={`fr-${id}`}>{children}</div>}
    </section>
  );
}

// The loop as steps: the stage it's at is marked; an open report can be moved
// to any other open stage by its step (Closed goes through the Close card);
// a closed or rejected one back into the loop (a reopen, asked first).
function Stepper({ status, onMove, busy }) {
  const at = STATUSES.indexOf(status);
  return (
    <ol className="fr-steps" aria-label="Stage">
      {STATUSES.map((s, i) => {
        const can = s !== "closed" && canMoveTo(status, s);
        const cls = ["fr-step", s === status ? "current" : "", at >= 0 && i < at ? "done" : ""].filter(Boolean).join(" ");
        return (
          <li key={s} className={cls}>
            {can ? (
              <button type="button" className="fr-step-btn" disabled={busy} onClick={() => onMove(s)}
                      title={isOpen(status) ? `Move to ${statusLabel(s)}` : `Reopen at ${statusLabel(s)}`}>
                {statusLabel(s)}
              </button>
            ) : (
              <span className="fr-step-btn" aria-current={s === status ? "step" : undefined}>{statusLabel(s)}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Investigation({ report, editable, onSave, busy }) {
  const inv = report.investigation;
  const [notes, setNotes] = useState(inv?.notes || "");
  const [category, setCategory] = useState(inv?.root_cause_category || "");
  const [rootCause, setRootCause] = useState(inv?.root_cause || "");
  const [whys, setWhys] = useState(inv?.whys?.length ? inv.whys : [""]);
  useEffect(() => {
    setNotes(inv?.notes || "");
    setCategory(inv?.root_cause_category || "");
    setRootCause(inv?.root_cause || "");
    setWhys(inv?.whys?.length ? inv.whys : [""]);
  }, [inv]);
  if (!editable) {
    if (!inv) return <p className="lib-date">Not investigated.</p>;
    return (
      <dl className="td-facts">
        {inv.notes && <div><dt>Notes</dt><dd className="fr-pre">{inv.notes}</dd></div>}
        <div><dt>Root cause</dt><dd>{[rootCauseLabel(inv.root_cause_category), inv.root_cause].filter(Boolean).join(": ") || <span className="lib-date">Not said</span>}</dd></div>
        {inv.whys?.length > 0 && <div><dt>The whys</dt><dd><ol className="fr-whys-read">{inv.whys.map((w, i) => <li key={i}>{w}</li>)}</ol></dd></div>}
        {inv.on && <div><dt>Recorded</dt><dd className="lib-date">{fmtDate(inv.on)}{inv.by ? ` by ${inv.by}` : ""}</dd></div>}
      </dl>
    );
  }
  const setWhy = (i, v) => setWhys((w) => w.map((x, j) => (j === i ? v : x)));
  const save = () => onSave({
    notes: notes.trim(), root_cause_category: category || null, root_cause: rootCause.trim(),
    whys: whys.map((w) => w.trim()).filter(Boolean),
  });
  return (
    <div className="rcm-form fr-form">
      <Field label="What was found">
        <textarea rows={3} value={notes} placeholder="What was inspected, measured or taken apart, and what it showed"
                  onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <div className="fr-modal-row">
        <Field label="Root cause category">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Not said yet</option>
            {ROOT_CAUSES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </Field>
        <Field label="Root cause" text={rootCause} max={SHORT_TEXT}>
          <input value={rootCause} placeholder="e.g. Misaligned coupling after the last overhaul" onChange={(e) => setRootCause(e.target.value)} />
        </Field>
      </div>
      <fieldset className="fr-whys">
        <legend>The whys <span className="lib-date">(ask why until the cause is something you can change; up to {MAX_WHYS})</span></legend>
        <ol>
          {whys.map((w, i) => (
            <li key={i}>
              <input value={w} aria-label={`Why ${i + 1}`} placeholder={i === 0 ? "Why did it fail?" : "Why was that?"}
                     onChange={(e) => setWhy(i, e.target.value)} />
              {whys.length > 1 && (
                <button type="button" className="secondary sm" aria-label={`Remove why ${i + 1}`}
                        onClick={() => setWhys((x) => x.filter((_, j) => j !== i))}>✕</button>
              )}
            </li>
          ))}
        </ol>
        {whys.length < MAX_WHYS && (
          <button type="button" className="secondary sm" onClick={() => setWhys((x) => [...x, ""])}>Add a why</button>
        )}
      </fieldset>
      <div className="fr-form-foot">
        <button type="button" onClick={save} disabled={busy || tooLong(rootCause)}>{busy ? "Saving…" : "Save investigation"}</button>
      </div>
    </div>
  );
}

// The work orders a corrective action can link: those on the report's position or its
// item, open ones first, then the latest closed.
function useReportWorkOrders(report, enabled) {
  const [wos, setWos] = useState([]);
  const ids = [report.position?.id, report.item?.id].filter(Boolean).join(",");
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    const wanted = new Set(ids.split(","));
    Promise.all([listMaintenanceWorkOrders({ status: "open" }), listMaintenanceWorkOrders({ status: "done", limit: 200 })])
      .then(([o, d]) => {
        if (!live) return;
        const rows = [...(o.work_orders || []), ...(d.work_orders || [])].filter((w) => wanted.has(w.subject?.id));
        setWos(rows);
      })
      .catch(() => live && setWos([]));
    return () => { live = false; };
  }, [ids, enabled]);
  return wos;
}

function woText(w) {
  return `#${w.number} ${w.title}${w.status === "closed" ? " (closed)" : w.status === "cancelled" ? " (cancelled)" : ""}`;
}

function Actions({ report, editable, today, onAdd, onUpdate, onRaise, busy }) {
  const [what, setWhat] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [ref, setRef] = useState("");
  const [woId, setWoId] = useState("");
  const actions = report.actions || [];
  const wos = useReportWorkOrders(report, editable);
  const add = async () => {
    const ok = await onAdd({ what: what.trim(), owner: owner.trim(), due: due || null, work_order_ref: ref.trim(),
      work_order_id: woId || null });
    if (!ok) return; // the reason is said; what was typed stays to try again
    setWhat(""); setOwner(""); setDue(""); setRef(""); setWoId("");
  };
  return (
    <>
      {actions.length ? (
        <div className="maint-scroll">
          <table className="lib-table td-table fr-actions">
            <thead>
              <tr><th>What</th><th>Owner</th><th>Due</th><th>Work order</th><th>Status</th>{editable && <th><span className="sr-only">Change</span></th>}</tr>
            </thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.id} className={a.status !== "open" ? "fr-action-done" : undefined}>
                  <td>{a.what}</td>
                  <td>{a.owner || <span className="lib-date">—</span>}</td>
                  <td className={a.due && a.status === "open" && a.due < today ? "maint-overdue" : "lib-date"}>
                    {a.due ? `${fmtDate(a.due)}${a.status === "open" && a.due < today ? " (overdue)" : ""}` : "—"}
                  </td>
                  <td>
                    {a.work_order ? <Link to={workOrderPath(a.work_order.id)}>{woText(a.work_order)}</Link>
                      : a.work_order_ref || (editable && a.status === "open" ? (
                        <button type="button" className="secondary sm" disabled={busy} onClick={() => onRaise(a.id)}
                                title="A corrective work order on this position, linked to this action">Raise work order</button>
                      ) : <span className="lib-date">—</span>)}
                    {a.work_order && a.work_order_ref && <div className="lib-date">{a.work_order_ref}</div>}
                  </td>
                  <td>
                    <span className={`td-pill act-${a.status}`}>{ACTION_STATUSES[a.status] || a.status}</span>
                    {a.status === "done" && a.done_on && <span className="lib-date"> {fmtDate(a.done_on)}</span>}
                  </td>
                  {editable && (
                    <td className="fr-action-btns">
                      {a.status === "open" ? (
                        <>
                          <button type="button" className="sm" disabled={busy} onClick={() => onUpdate(a.id, { status: "done", done_on: today }, "Marked done.")}>Done</button>
                          <button type="button" className="secondary sm" disabled={busy} onClick={() => onUpdate(a.id, { status: "dropped" }, "Dropped.")}>Drop</button>
                        </>
                      ) : (
                        <button type="button" className="secondary sm" disabled={busy} onClick={() => onUpdate(a.id, { status: "open", done_on: null }, "Open again.")}>Reopen</button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="lib-date">No corrective action yet. What will stop this failure happening again?</p>}
      {editable && (
        <div className="rcm-form fr-form fr-add-action">
          <Field label="What will be done" text={what} max={SHORT_TEXT}>
            <input value={what} placeholder="e.g. Replace the coupling and align to 0.05 mm" onChange={(e) => setWhat(e.target.value)} />
          </Field>
          <div className="fr-modal-row fr-row-3">
            <Field label="Owner" text={owner} max={SHORT_TEXT}>
              <input value={owner} placeholder="A name" onChange={(e) => setOwner(e.target.value)} />
            </Field>
            <Field label="Due (optional)">
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </Field>
            <Field label="Work order (optional)">
              <select value={woId} onChange={(e) => setWoId(e.target.value)}>
                <option value="">None yet (raise one from the action once added)</option>
                {wos.map((w) => <option key={w.id} value={w.id}>{woText(w)}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Or a reference kept elsewhere (optional)" text={ref} max={SHORT_TEXT}>
            <input value={ref} placeholder="A number or link in another system" onChange={(e) => setRef(e.target.value)} />
          </Field>
          <div className="fr-form-foot">
            <button type="button" onClick={add} disabled={busy || !what.trim() || tooLong(what) || tooLong(owner) || tooLong(ref)}>
              {busy ? "Adding…" : "Add action"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function Verification({ report, editable, today, onSave, busy }) {
  const v = report.verification;
  const [on, setOn] = useState(v?.verified_on || today || "");
  const [result, setResult] = useState(v?.result || "");
  const [notes, setNotes] = useState(v?.notes || "");
  useEffect(() => {
    setOn(v?.verified_on || today || "");
    setResult(v?.result || "");
    setNotes(v?.notes || "");
  }, [v, today]);
  const repeat = repeatSentence(report.repeat_check, fmtDate);
  return (
    <>
      {repeat && <p className={`fr-repeat${report.repeat_check?.repeats ? " maint-overdue" : " td-ok"}`}>{repeat}</p>}
      {editable ? (
        <div className="rcm-form fr-form">
          <fieldset className="fr-radios">
            <legend>Did the corrective action work?</legend>
            {RESULTS.map((r) => (
              <label key={r.id} className="fr-radio">
                <input type="radio" name="fr-result" value={r.id} checked={result === r.id} onChange={() => setResult(r.id)} />
                <span>{r.label}</span>
              </label>
            ))}
          </fieldset>
          <div className="fr-modal-row">
            <Field label="Checked on">
              <input type="date" value={on} max={today || undefined} onChange={(e) => setOn(e.target.value)} />
            </Field>
            <Field label="Notes (optional)">
              <input value={notes} placeholder="What was checked, and how" onChange={(e) => setNotes(e.target.value)} />
            </Field>
          </div>
          <div className="fr-form-foot">
            <button type="button" disabled={busy || !result || !on}
                    onClick={() => onSave({ result, notes: notes.trim(), verified_on: on })}>{busy ? "Saving…" : "Save verification"}</button>
          </div>
        </div>
      ) : v ? (
        <dl className="td-facts">
          <div><dt>Result</dt><dd>{resultLabel(v.result)}</dd></div>
          <div><dt>Checked on</dt><dd>{fmtDate(v.verified_on)}{v.by ? <span className="lib-date"> by {v.by}</span> : null}</dd></div>
          {v.notes && <div><dt>Notes</dt><dd>{v.notes}</dd></div>}
        </dl>
      ) : <p className="lib-date">Not verified.</p>}
    </>
  );
}

function Close({ report, user, today, onClose, busy }) {
  const [note, setNote] = useState("");
  const block = closeBlock(report);
  const who = user?.displayName || user?.email || "you";
  return (
    <div className="rcm-form fr-form">
      <p className="lib-date">Signed off by <strong>{who}</strong> on {fmtDate(today)}.</p>
      <Field label="Sign-off note (optional)">
        <input value={note} placeholder="e.g. Coupling replaced and aligned; no leak in 60 days" onChange={(e) => setNote(e.target.value)} />
      </Field>
      {block && <p className="fr-block" role="note">{block}</p>}
      <div className="fr-form-foot">
        <button type="button" disabled={busy || !!block} onClick={() => onClose(note.trim())}>{busy ? "Closing…" : "Close report"}</button>
      </div>
    </div>
  );
}

function Reject({ report, onReject, busy }) {
  const [reason, setReason] = useState("");
  const [duplicateOf, setDuplicateOf] = useState("");
  const [others, setOthers] = useState(null);
  useEffect(() => {
    let live = true;
    listFailureReports({ status: "all", sort: "newest", limit: 200 })
      .then((d) => live && setOthers((d.reports || []).filter((r) => r.id !== report.id)))
      .catch(() => live && setOthers([]));
    return () => { live = false; };
  }, [report.id]);
  return (
    <div className="rcm-form fr-form">
      <Field label="Why it's rejected">
        <input value={reason} placeholder="e.g. Not a failure: the trip was a test" onChange={(e) => setReason(e.target.value)} />
      </Field>
      <Field label="A duplicate of (optional)">
        <select value={duplicateOf} onChange={(e) => setDuplicateOf(e.target.value)}>
          <option value="">Not a duplicate</option>
          {(others || []).map((r) => <option key={r.id} value={r.id}>{r.label} · {r.title}</option>)}
        </select>
      </Field>
      <div className="fr-form-foot">
        <button type="button" className="secondary danger" disabled={busy || !reason.trim()}
                onClick={() => onReject(reason.trim(), duplicateOf || null)}>{busy ? "Rejecting…" : "Reject report"}</button>
      </div>
    </div>
  );
}

export default function FailureReportDetail({ id, today, viewOnly, onBack, onStatusChanged }) {
  const confirm = useConfirm();
  const { user } = useAuth();
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [editing, setEditing] = useState(false);
  const [folds, setFolds] = useState({});
  const heading = useRef(null);

  const load = useCallback(() => {
    setError(null);
    return getFailureReport(id).then(setReport).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    setReport(null);
    setFolds({});
    load();
  }, [load]);
  useEffect(() => {
    if (report && heading.current) heading.current.focus({ preventScroll: true });
  }, [report?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const say = (text, tone = "ok") => setMessage({ text, tone, at: Date.now() });
  useEffect(() => {
    if (!message || message.tone === "error") return undefined;
    const t = setTimeout(() => setMessage((m) => (m === message ? null : m)), 6000);
    return () => clearTimeout(t);
  }, [message]);

  // A change: the server's view of the report comes back; the tree's roll-up
  // is read again when the status changed (it counts open reports).
  const run = async (fn, text, { tree = false } = {}) => {
    if (busy) return false;
    setBusy(true);
    setMessage(null);
    try {
      const before = report?.status;
      const view = await fn();
      setReport(view);
      say(typeof text === "function" ? text(view) : text);
      if (tree || view.status !== before) onStatusChanged?.();
      return true;
    } catch (e) {
      say(failText(e), "error");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const move = async (status) => {
    if (!report) return;
    if (!isOpen(report.status)) {
      const ok = await confirm({
        title: `Reopen ${report.label}?`,
        body: `It goes back to ${statusLabel(status)}. Its sign-off is kept in the history.`,
        confirmLabel: "Reopen",
      });
      if (!ok) return;
    }
    run(() => setFailureReportStatus(report.id, { status }), `Now ${statusLabel(status).toLowerCase()}.`);
  };

  if (error) {
    return (
      <div className="fr-detail">
        <button type="button" className="secondary sm fr-back" onClick={onBack}>‹ All reports</button>
        <p className="lib-date">Couldn't load the report: {error} <button type="button" className="link" onClick={load}>Try again</button></p>
      </div>
    );
  }
  if (!report) {
    return (
      <div className="fr-detail">
        <button type="button" className="secondary sm fr-back" onClick={onBack}>‹ All reports</button>
        <p className="lib-date">Loading…</p>
      </div>
    );
  }

  const open = isOpen(report.status);
  const editable = open && !viewOnly;
  const stage = stageOf(report);
  const stageCard = CARD_OF_STAGE[stage];
  const isFolded = (key) => !(folds[key] ?? (key === stageCard || (stage === "verifying" && key === "close")));
  const toggle = (key) => setFolds((f) => ({ ...f, [key]: isFolded(key) }));
  const actions = report.actions || [];
  const openActions = actions.filter((a) => a.status === "open").length;
  const inv = report.investigation;
  const invSummary = inv ? ([rootCauseLabel(inv.root_cause_category), inv.root_cause].filter(Boolean).join(": ") || "Notes recorded") : "Not started";
  const actSummary = actions.length ? `${actions.length} ${actions.length === 1 ? "action" : "actions"}${openActions ? `, ${openActions} open` : ", all done"}` : "None yet";
  const verSummary = report.verification ? `${resultLabel(report.verification.result)} · ${fmtDate(report.verification.verified_on)}` : "Not yet";
  const closeSummary = report.closed ? signOffText("Closed", report.closed, fmtDate) : closeBlock(report) ? "Not yet" : "Ready to close";
  const p = report.position || {};
  // The way down to the position (its path may or may not end with itself).
  const above = (p.path || []).filter((x) => x.id !== p.id).map((x) => x.name);
  const path = [...above, p.name].filter(Boolean).join(" › ");

  return (
    <div className="fr-detail" aria-busy={busy || undefined}>
      <div className="fr-detail-top">
        <button type="button" className="secondary sm fr-back" onClick={onBack}>‹ All reports</button>
        {message && <p className={`fr-msg ${message.tone}`} role="status">{message.text}</p>}
      </div>
      <h2 className="fr-h2"><span ref={heading} tabIndex={-1}><span className="fr-label">{report.label}</span> {report.title}</span>
        <span className={`td-pill st-${report.status}`}>{statusLabel(report.status)}</span>
      </h2>
      <Stepper status={report.status} onMove={move} busy={busy || !!viewOnly} />
      {report.status === "rejected" && report.rejected && (
        <p className="fr-signoff maint-overdue">
          {signOffText("Rejected", report.rejected, fmtDate)}
          {report.rejected.duplicate_of && <span className="lib-date"> · a duplicate of another report</span>}
        </p>
      )}
      {report.status === "closed" && report.closed && <p className="fr-signoff td-ok">{signOffText("Closed", report.closed, fmtDate)}</p>}
      {viewOnly && <p className="lib-date">{viewOnly}</p>}

      <section className="card td-card fr-card">
        <h3 className="fr-card-h">Facts
          {editable && <button type="button" className="secondary sm" onClick={() => setEditing(true)}>Edit…</button>}
        </h3>
        {report.description && <p className="fr-pre">{report.description}</p>}
        <dl className="td-facts">
          <div><dt>When</dt><dd>{fmtDate(report.occurred_on)}<span className="lib-date"> · reported {fmtDate(report.filed_on)}</span></dd></div>
          <div><dt>Who found it</dt><dd>{report.found_by || <span className="lib-date">Not said</span>}</dd></div>
          <div><dt>Position</dt><dd>{path || p.name || "—"}</dd></div>
          <div><dt>Item</dt><dd>{itemText(report.item) || <span className="lib-date">Nothing fitted at the time</span>}</dd></div>
          <div><dt>Failure mode</dt><dd>{report.failure_mode ? <>{report.failure_mode.text}{report.failure_mode.ad_hoc && <span className="lib-date"> (not in the RCM)</span>}</> : <span className="lib-date">Not known</span>}</dd></div>
          <div><dt>Consequence</dt><dd>{consequenceLabel(report.consequence)}</dd></div>
        </dl>
        {lifeDataText(report.life_data, fmtDate) && <p className="lib-date">{lifeDataText(report.life_data, fmtDate)}</p>}
      </section>

      <Fold id="investigation" title="Investigation" summary={invSummary} open={!isFolded("investigation")} onToggle={toggle}>
        <Investigation report={report} editable={editable} busy={busy}
                       onSave={(body) => run(() => saveFailureReportInvestigation(report.id, body), "Investigation saved.")} />
      </Fold>
      <Fold id="actions" title="Corrective actions" summary={actSummary} open={!isFolded("actions")} onToggle={toggle}>
        <Actions report={report} editable={editable} today={today} busy={busy}
                 onAdd={(body) => run(() => addCorrectiveAction(report.id, body), "Action added.")}
                 onUpdate={(aid, body, text) => run(() => updateCorrectiveAction(report.id, aid, body), text)}
                 onRaise={(aid) => run(() => raiseActionWorkOrder(report.id, aid),
                   (view) => `Raised work order #${view.actions.find((x) => x.id === aid)?.work_order?.number ?? ""}, linked to this action.`)} />
      </Fold>
      <Fold id="verification" title="Verification" summary={verSummary} open={!isFolded("verification")} onToggle={toggle}>
        <Verification report={report} editable={editable} today={today} busy={busy}
                      onSave={(body) => run(() => verifyFailureReport(report.id, body), "Verification saved.")} />
      </Fold>
      {open && (
        <Fold id="close" title="Close" summary={closeSummary} open={!isFolded("close")} onToggle={toggle}>
          {editable ? (
            <Close report={report} user={user} today={today} busy={busy}
                   onClose={(note) => run(() => setFailureReportStatus(report.id, { status: "closed", note }), `Closed ${report.label}.`)} />
          ) : <p className="lib-date">{viewOnly}</p>}
        </Fold>
      )}
      {open && (
        <Fold id="reject" title="Reject" summary="Not a failure, or a duplicate" open={!isFolded("reject")} onToggle={toggle} className="fr-reject">
          {editable ? (
            <Reject report={report} busy={busy}
                    onReject={(note, duplicateOf) => run(() => setFailureReportStatus(report.id, { status: "rejected", note, duplicate_of: duplicateOf }), `Rejected ${report.label}.`)} />
          ) : <p className="lib-date">{viewOnly}</p>}
        </Fold>
      )}

      <MaintenancePhotos targetId={report.id} targetName={report.label} targetKind="FailureReport" photos={report.photos || []} onChanged={load}
                         related={[
                           p.id ? { id: p.id, kind: "Position", name: p.name } : null,
                           report.item?.id && report.item.exists !== false ? { id: report.item.id, kind: "Item", name: report.item.name } : null,
                         ].filter(Boolean)} />

      <section className="card td-card fr-card">
        <h3>History</h3>
        <ul className="td-list fr-history">
          {historyRows(report.history).map((h, i) => (
            <li key={i}><span className="lib-date">{fmtWhen(h.at)}{h.by ? ` · ${h.by}` : ""} · </span>{h.change}</li>
          ))}
        </ul>
      </section>

      {editing && (
        <NewFailureReportModal positionId={p.id} positionName={p.name} today={today} report={report}
                               onClose={() => setEditing(false)}
                               onDone={(view) => { setEditing(false); setReport(view); say("Saved."); }} />
      )}
    </div>
  );
}
