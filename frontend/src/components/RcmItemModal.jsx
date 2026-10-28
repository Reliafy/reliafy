import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Modal from "./Modal.jsx";
import RcmBasis from "./RcmBasis.jsx";
import RcmStatusBadge from "./RcmStatusBadge.jsx";
import RcmModeTasks from "./RcmModeTasks.jsx";
import RcmFunctionStandards, { BreachesField } from "./RcmFunctionStandards.jsx";
import { CausedBySection, CausesSection } from "./FailureLinks.jsx";
import { LevelIcon } from "./RcmWorksheet.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { ancestorsOf } from "../outlineTree.js";
import {
  CONSEQUENCE_LABEL, FUNCTION_MAX, FUNCTION_NUDGE, LEVEL_OF, decisionText, functionCount, intervalText, nameOf, tasksOf,
} from "../rcmWorksheet.js";
import { ITEM_FIELDS, checkItem, failureStatusWords, failureSummary, itemChanges, itemValue } from "../explorerRcm.js";
import "./RcmItemModal.css";

// A function, functional failure or failure mode in its own dialog (the
// Explorer's RCM tab: double-click its row, or Open… in its menu): all of it
// in one place. Its words are edited here and kept with Save (Cancel, Escape
// or × drops them, asking first when something was typed); the working behind
// a standard, the links between failures and the decision keep their own
// buttons, which save at once, as in the Details panel.
//
//   r          the row (cellRow: sum is its own counts), read afresh after each save
//   display    the whole tree with the RCM in it (what it sits under, what's inside)
//   ops        the panel's ops (ops.basis, ops.basisView)
//   links      { onLink, onUnlink } (the failure's links, as in the panel)
//   onSave     (r, values) → a promise; a refusal shows here with the words as typed
//   onDecision (r) opens the decision dialog over this one
//   onOpen     (key) shows another function, failure or mode here
//   onDetails  (r) closes this and shows the row in the Details panel
//   onClose    ()
//   start      what it opens on ({tasks: true}: a failure mode's Tasks, on the add form)
//   onSaid     (text) a few words in the page's status line once a task was changed
export default function RcmItemModal({ r, display, ops, links, onSave, onDecision, onOpen, onDetails, onClose, start = null, onSaid }) {
  const confirm = useConfirm();
  const level = LEVEL_OF[r.type];
  const [state, setState] = useState({ key: r.key, drafts: {}, errors: {} });
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const busy = useRef(false);
  const asking = useRef(false);
  const form = useRef(null);
  // Another row shown here: its own words, nothing typed yet.
  const cur = state.key === r.key ? state : { key: r.key, drafts: {}, errors: {} };
  if (cur !== state) setState(cur);
  const { drafts, errors } = cur;
  // The consequence chosen in the decision dialog (over this one) wins over one
  // chosen here and not saved yet.
  const savedConsequence = useRef(r.ref.consequence);
  useEffect(() => {
    if (savedConsequence.current === r.ref.consequence) return;
    savedConsequence.current = r.ref.consequence;
    setState((s) => {
      if (!("consequence" in s.drafts)) return s;
      const next = { ...s.drafts };
      delete next.consequence;
      return { ...s, drafts: next };
    });
  }, [r.ref.consequence]);

  const changes = itemChanges(r, drafts);
  const dirty = Object.keys(changes).length > 0;
  const value = (col) => (col in drafts ? drafts[col] : itemValue(r, col));
  const type = (col, v) => {
    setFailed(null);
    setState((s) => {
      const nextErrors = { ...s.errors };
      delete nextErrors[col];
      return { ...s, drafts: { ...s.drafts, [col]: v }, errors: nextErrors };
    });
  };

  // Leaving with words typed and not saved asks first.
  const leave = async (go) => {
    if (busy.current || asking.current) return;
    if (dirty) {
      asking.current = true;
      const ok = await confirm({
        title: "Discard your changes?",
        body: `What you typed for this ${level.label.toLowerCase()} hasn't been saved.`,
        confirmLabel: "Discard changes", cancelLabel: "Keep editing",
      });
      asking.current = false;
      if (!ok) return;
    }
    go();
  };
  const close = () => leave(onClose);
  const openOther = (key) => leave(() => onOpen(key));

  const save = async (e) => {
    e?.preventDefault();
    if (busy.current) return;
    const { values, errors: bad } = checkItem(r, changes);
    if (Object.keys(bad).length) {
      setState((s) => ({ ...s, errors: bad }));
      const first = ITEM_FIELDS[r.type].find((c) => bad[c]);
      setTimeout(() => form.current?.querySelector(`[name="${first}"]`)?.focus(), 0);
      return;
    }
    if (!Object.keys(values).length) {
      onClose();
      return;
    }
    busy.current = true;
    setSaving(true);
    setFailed(null);
    try {
      await onSave(r, values);
      busy.current = false;
      onClose();
    } catch (err) {
      busy.current = false;
      setSaving(false);
      setFailed(saveErrorText(err, { offline: navigator.onLine === false }));
    }
  };

  // Where it sits: its position, then the function and failure above it.
  const up = ancestorsOf(display, r.key).map((k) => display.rows.get(k)).filter(Boolean);
  const posAt = up.findIndex((a) => a.key === r.ref.position_id);
  const position = posAt >= 0 ? up[posAt] : display.rows.get(r.ref.position_id);
  const above = posAt >= 0 ? up.slice(posAt + 1) : [];
  const where = position?.ref.name || "";
  const kids = r.kids.map((k) => display.rows.get(k)).filter((k) => k && (k.type === "fail" || k.type === "mode"));
  const d = r.ref.decision;
  const fnCount = r.type === "fn" ? functionCount(value("name"), r.ref.text || "") : null;

  const field = (col, label, { area = false, help = null } = {}) => {
    const id = `rim-${col}`;
    const count = col === "name" ? fnCount : null;
    const Tag = area ? "textarea" : "input";
    return (
      <div className="rw-field" key={col}>
        <label className={"rw-flabel" + (count ? " rw-flabel-count" : "")} htmlFor={id}>
          {label}
          {count && <span className={"char-count" + (count.tone ? ` ${count.tone}` : "")} aria-hidden="true">{count.text}</span>}
        </label>
        <span className="rw-fin">
          <Tag id={id} name={col} value={value(col)} rows={area ? 3 : undefined} readOnly={saving}
               maxLength={count ? FUNCTION_MAX : undefined}
               aria-description={count ? `${count.n} of ${count.max} characters. ${FUNCTION_NUDGE}` : undefined}
               aria-invalid={errors[col] || count?.over ? "true" : undefined}
               aria-errormessage={errors[col] ? `${id}-err` : undefined}
               onChange={(e) => type(col, e.target.value)}
               onKeyDown={area ? (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save(e); } : undefined} />
        </span>
        {help && !errors[col] && <span className="rw-fhelp">{help}</span>}
        {count && !errors[col] && <span className="rw-fhelp rw-nudge">{FUNCTION_NUDGE}</span>}
        {errors[col] && <span className="rw-ferr" id={`${id}-err`} role="alert">{errors[col]}</span>}
      </div>
    );
  };

  const footer = (
    <>
      <button type="button" className="link rim-details" onClick={() => leave(() => onDetails(r))} disabled={saving}>
        Show in Details
      </button>
      {failed && <p className="hint rw-ferr rim-failed" role="alert">{failed}</p>}
      <div className="row confirm-actions">
        <button type="button" className="secondary" onClick={close} disabled={saving}>Cancel</button>
        <button type="submit" form="rim-form" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );

  return (
    <Modal title={<><LevelIcon type={r.type} /> {level.label}</>} onClose={close} locked={saving} footer={footer}
           className="rcm-item-modal" overlayClassName="rcm-item-overlay" trapFocus>
      <p className="rim-where">
        <span className="rim-on">On {where || "this position"}</span>
        {above.map((a) => (
          <span key={a.key} className="rim-crumb">
            <span aria-hidden="true"> › </span>
            {a.type === "fn" || a.type === "fail" ? (
              <button type="button" className="link" onClick={() => openOther(a.key)} title={`Open the ${LEVEL_OF[a.type].label.toLowerCase()}`}>
                {nameOf(a) || `(${LEVEL_OF[a.type].label.toLowerCase()})`}
              </button>
            ) : <span>{nameOf(a)}</span>}
          </span>
        ))}
      </p>

      <form id="rim-form" ref={form} className="rw-fields" onSubmit={save} noValidate>
        {field("name", "Description", {
          area: true,
          help: r.type === "fn" ? "What this position must do" : r.type === "fail" ? "How it fails to do it" : "What causes the failure",
        })}
        {r.type === "mode" && field("effects", "Failure effects", { area: true, help: "What happens when it occurs" })}
        {r.type === "mode" && (
          <div className="rw-field">
            <label className="rw-flabel" htmlFor="rim-consequence">Consequence</label>
            <select id="rim-consequence" name="consequence" value={value("consequence")} disabled={saving}
                    onChange={(e) => type("consequence", e.target.value)}>
              <option value="">Not set</option>
              {Object.entries(CONSEQUENCE_LABEL).map(([id, l]) => <option key={id} value={id}>{l}</option>)}
            </select>
          </div>
        )}
        {r.type === "mode" && field("notes", "Mode notes", { area: true })}
      </form>

      {/* The standards and the working save at once, as in the Details panel. */}
      {r.type === "fn" && ops?.standards && <RcmFunctionStandards key={r.key} r={r} ops={ops} onSaid={onSaid} />}
      {r.type === "fn" && ops?.basis && (
        <RcmBasis r={r} basis={ops.basis} context={ops.basisView?.context(r)} />
      )}
      {r.type === "fail" && ops?.setBreach && (
        <BreachesField r={r} standards={display.rows.get(r.parent)?.ref.standards || []}
                       onChange={(id) => ops.setBreach(r, id).then(() => onSaid?.("Saved."), (e) => setFailed(saveErrorText(e, { offline: navigator.onLine === false })))} />
      )}

      {r.type === "fail" && <p className="rim-status">{failureStatusWords(r)}</p>}
      {r.type === "fail" && links && <CausedBySection r={r} where={where} links={links} onSelect={openOther} />}
      {r.type === "fail" && links && <CausesSection r={r} where={where} links={links} onSelect={openOther} />}

      {r.type === "mode" && (
        <section className="rw-decision" aria-label="Decision">
          <h3>Decision</h3>
          {d ? (
            <>
              <p className="rw-dline"><b>{decisionText(d)}</b>{intervalText(d) ? <span className="rw-fhelp"> · every {intervalText(d)}</span> : null}</p>
              {/* The action on failure of a decision that schedules nothing; the tasks have their own section. */}
              {d.task && !tasksOf(r.ref).some((t) => t.id) && (
                <p className="rim-task">
                  <LevelIcon type="task" className="rw-ic rw-ic-task" />
                  <span><span className="rim-task-name">{d.task}</span></span>
                </p>
              )}
              {d.notes && <p className="rim-dnotes">{d.notes}</p>}
              {d.status === "unevidenced" ? (
                <p className="rw-evidence rw-unlinked">No evidence linked yet.</p>
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
          <button type="button" className={d ? "secondary" : ""} disabled={saving}
                  onClick={(e) => { if (e.detail < 2) onDecision({ ...r, ref: { ...r.ref, consequence: value("consequence") || null } }); }}>
            {d ? "Change the decision…" : "Decide…"}
          </button>
        </section>
      )}

      {r.type === "mode" && ops && <RcmModeTasks key={r.key} r={r} ops={ops} start={start} onSaid={onSaid} />}

      {r.type !== "mode" && (
        <section className="rim-kids" aria-label={r.type === "fn" ? "Functional failures" : "Failure modes"}>
          <h3>{r.type === "fn" ? "Functional failures" : "Failure modes"}</h3>
          {kids.length === 0 ? (
            <p className="rw-fhelp">{r.type === "fn" ? "No functional failures yet." : "No failure modes of its own yet."}</p>
          ) : (
            <ul className="rim-list">
              {kids.map((k) => (
                <li key={k.key}>
                  <button type="button" className="link rim-go" onClick={() => openOther(k.key)}
                          title={`Open the ${LEVEL_OF[k.type].label.toLowerCase()}`}>
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
    </Modal>
  );
}
