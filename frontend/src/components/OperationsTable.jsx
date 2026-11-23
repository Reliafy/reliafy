import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { backInService, getOperations, takeOutOfService } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { opsById, opsCellText, opsPhoneLine, sourceText, windowText } from "../explorerOperations.js";
import { latestOnly } from "../explorerMissions.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import Chip from "./ui/Chip.jsx";
import { TextInput } from "./ui/Controls.jsx";
import { DateInput } from "./ui/DateTimeInput.jsx";
import "./OperationsTable.css";

// The Explorer's Operations tab (explorerOperations.js): the read of every position's operations,
// a position row's cells, its phone line, and the shutdowns section of its details (the operating
// plan editor, OperatingPlanPane, with this under it).

// Every position's operations inside the asset opened, read when the tab is on (and again on
// `load`, after a plan or an outage is saved). The read asked for last is the one shown.
export function useTreeOperations({ on, root = null }) {
  const [state, setState] = useState({ data: null, byId: new Map(), error: null });
  const asked = useRef(null);
  if (!asked.current) asked.current = latestOnly();
  const load = useCallback(() => {
    const latest = asked.current();
    return getOperations(root)
      .then((d) => latest() && setState({ data: d, byId: opsById(d), error: null }))
      .catch((e) => latest() && setState((s) => ({ ...s, error: e.message })));
  }, [root]);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { ...state, load };
}

// One cell of a position's row. An item runs as the position it's fitted to: said once, quietly.
export function OpsCell({ r, col, op, zone }) {
  if (r.type === "item") return col.id === "duty" ? <span className="rw-blank">Runs as the position it&apos;s fitted to</span> : null;
  if (r.type !== "pos") return null;
  if (!op) return col.id === "duty" ? <span className="rw-blank">—</span> : null;
  const text = opsCellText(op, col.id, zone);
  if (col.id === "source") {
    return <Chip tone={op.duty?.source === "own" ? "accent" : "neutral"} title={text}>{text}</Chip>;
  }
  if (!text) return <span className="rw-blank">—</span>;
  const quiet = col.id === "duty" && op.duty?.source === "none";
  return <span className={"ops-cell" + (quiet ? " ops-quiet" : "")} title={text}>{text}</span>;
}

export function opsPhoneRow(r, op) {
  if (r.type === "item") return { line: "Runs as the position it's fitted to", status: null };
  if (r.type !== "pos" || !op) return { line: "", status: null };
  return { line: opsPhoneLine(op), status: null };
}

// The heading's one line for the position picked: "Own · Monday to Friday …".
export function opsHeadline(op) {
  if (!op) return "";
  return `${sourceText(op)} · ${opsCellText(op, "duty")}`;
}

// The details' shutdowns section: every window that takes the position off-line in the year ahead
// (its own and inherited, each saying where it's set), a shutdown package opening in the
// Maintenance tab, and a planned outage of its own (Plan an outage…, Back in service).
export function OperationsShutdowns({ op, position, readOnly = null, onChanged }) {
  const confirm = useConfirm();
  const { pathname, search } = useLocation();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const windows = op?.windows || [];
  const ownOutage = windows.find((w) => w.kind === "outage" && w.own);
  const pkgLink = (id) => {
    const q = new URLSearchParams(search);
    q.set("tab", "maintenance");
    q.set("mpkg", id);
    for (const k of ["plan", "pane"]) q.delete(k);
    return `${pathname}?${q}`;
  };
  const save = async () => {
    if (!form.reason.trim()) { setFailed("Say why it's off-line (the reason shows on its tasks)."); return; }
    setSaving(true);
    setFailed(null);
    try {
      await takeOutOfService(position.id, { start: form.start || null, until: form.until || null, reason: form.reason.trim() });
      setForm(null);
      onChanged?.(`${position.name} is planned off-line from ${form.start || "today"}.`);
    } catch (e) {
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setSaving(false);
    }
  };
  const back = async () => {
    const ok = await confirm({
      title: "Back in service?", body: `${position.name}'s outage ends today, and its tasks fall due again from today.`,
      confirmLabel: "Back in service", pendingLabel: "Saving…", failedWhat: "end it",
      run: () => backInService(position.id).then(() => true),
    });
    if (ok) onChanged?.(`${position.name} is back in service.`);
  };
  return (
    <section className="op-history ops-shut" aria-label="Shutdowns and outages">
      <h3 className="op-sub">Shutdowns and outages · the year ahead</h3>
      {windows.length ? (
        <ul className="td-rows">
          {windows.map((w, i) => (
            <li key={`${w.kind}:${w.package_id || w.source?.id}:${w.start}:${i}`} className="op-hist-row ops-win">
              <span>{windowText(w, { from: false })}</span>
              <span className="lib-date">
                {w.own ? "Set here" : `From ${w.source?.name || "above"}`}
                {w.kind === "shutdown" && w.cost != null ? ` · costs ${Number(w.cost).toLocaleString("en-AU")} each time` : ""}
                {w.rule ? ` · ${w.rule}` : ""}
                {w.kind === "shutdown" && w.package_id && (
                  <>{" · "}<Link to={pkgLink(w.package_id)}>Open the package</Link></>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="lib-date">None planned here or above it. A shutdown is a work package (Maintenance tab) that takes its position off-line; an outage is set here.</p>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      {!readOnly && !form && (
        <div className="op-actions">
          {ownOutage
            ? <button type="button" className="secondary" onClick={back}>Back in service…</button>
            : <button type="button" className="secondary" onClick={() => { setFailed(null); setForm({ start: "", until: "", reason: "" }); }}>Plan an outage…</button>}
        </div>
      )}
      {form && (
        <form className="op-form ops-outage" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <div className="op-row op-meta">
            <label htmlFor="ops-from">From</label>
            <DateInput id="ops-from" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} disabled={saving} />
            <label htmlFor="ops-until">Back on <span className="field-opt">optional</span></label>
            <DateInput id="ops-until" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} disabled={saving} />
          </div>
          <div className="op-row op-meta">
            <label htmlFor="ops-reason">Why</label>
            <TextInput id="ops-reason" className="op-name" value={form.reason} maxLength={200} placeholder="e.g. Rebuild" disabled={saving}
                       onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </div>
          <p className="lib-date op-text">Its tasks, and those of everything inside it, aren&apos;t due meanwhile. Leave the date blank for today.</p>
          <div className="op-actions">
            <button type="submit" disabled={saving}>{saving ? "Saving…" : "Save the outage"}</button>
            <button type="button" className="secondary" onClick={() => setForm(null)} disabled={saving}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  );
}
