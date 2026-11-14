import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  addPositionPart, createMaintenancePart, listMaintenanceParts, listMeasurementPoints, recordConsumableUse, removePositionPart,
} from "../api.js";
import { Field, FormModal, today as workspaceToday } from "./MaintenanceParts.jsx";
import Plot from "./Plot.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { usePanelMenu } from "../panelMenu.js";
import {
  byText, consumableState, lsaComparison, monthlyTotals, qtyText, stockText, yearTotal,
} from "../consumables.js";
import { dayText } from "../measuringPoint.js";
import { ACCENT } from "../plotTheme.js";
import "../views/Maintenance.css";
import "./MeasurementViews.css";

// Consumables (salt added to the pool; acid; a stabiliser): the Measurements
// tab's monthly bars, the dialogs to record a use (Record use…: another date,
// the cost, a note) and to add a consumable at a position (Add a consumable…:
// a part from the register, or a new one by name and unit), and a consumable
// in full in the tab (?consumable=<key>, with "← Measurements" back): "What's
// been added over time", monthly bars, every addition with its work order or
// "by hand" and cost, the year's total, and the LSA's dose beside what was used.

// The row's trend: the last months' totals as small bars.
export function UseBars({ values = [], unit = "", name = "" }) {
  const W = 120, H = 28;
  const max = Math.max(0, ...values.map((v) => v.value));
  if (!max) return <span className="lib-date ms-no-trend" title="Nothing added in these months">—</span>;
  const w = W / values.length;
  return (
    <svg className="ms-trend" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`${name}: added by month, ${values.map((v) => `${v.at} ${qtyText(v.value, unit)}`).join(", ")}`}>
      {values.map((v, i) => {
        const h = v.value ? Math.max(2, (v.value / max) * (H - 4)) : 0;
        return <rect key={v.at} x={i * w + 2} y={H - 1 - h} width={Math.max(2, w - 4)} height={h} rx="1.5" fill="var(--accent)" />;
      })}
      <line x1="0" x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--border)" strokeWidth="1" />
    </svg>
  );
}

// Record use…: how much, on which day, its cost (default the part's) and a note.
export function ConsumableUseModal({ consumable: c, onClose, onDone }) {
  const [qty, setQty] = useState("");
  const [on, setOn] = useState(workspaceToday());
  const [cost, setCost] = useState("");
  const [note, setNote] = useState("");
  const n = Number(String(qty).replace(",", "."));
  const unitCost = c.part?.unit_cost;
  return (
    <FormModal title={`Record use: ${c.name}`} submitLabel="Record" canSubmit={qty !== "" && n > 0} onClose={onClose}
               onSubmit={async () => onDone((await recordConsumableUse(c.position.id, {
                 qty: n, on, note, ...(cost !== "" ? { cost: Number(cost) } : {}),
                 ...(c.part ? { part_id: c.part.id } : { name: c.name, unit: c.unit }),
               })).consumable)}>
      <Field label={`How much${c.unit ? ` (${c.unit})` : ""}`}>
        <input type="number" inputMode="decimal" step="any" min="0" autoFocus value={qty} onChange={(e) => setQty(e.target.value)} />
      </Field>
      <Field label="Added on"><input type="date" value={on} max={workspaceToday()} onChange={(e) => setOn(e.target.value)} /></Field>
      <Field label="Cost (optional)">
        <input type="number" inputMode="decimal" step="any" min="0" value={cost} onChange={(e) => setCost(e.target.value)}
               placeholder={unitCost != null && n > 0 ? `${(n * unitCost).toFixed(2)} at ${unitCost} each` : ""} />
      </Field>
      <Field label="Note (optional)" text={note}><input value={note} placeholder="e.g. after heavy rain" onChange={(e) => setNote(e.target.value)} /></Field>
      <p className="lib-date">{stockText(c)}.</p>
    </FormModal>
  );
}

// Add a consumable…: a part from the register, or a new one by name and unit
// (added to the register); it goes on the position's parts list as a consumable.
export function AddConsumableModal({ position, onClose, onDone }) {
  const [parts, setParts] = useState(null);
  const [mode, setMode] = useState("pick");
  const [partId, setPartId] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("kg");
  const [cost, setCost] = useState("");
  useEffect(() => {
    listMaintenanceParts().then((d) => {
      const list = d.parts || [];
      setParts(list);
      if (!list.length) setMode("new");
    }).catch(() => { setParts([]); setMode("new"); });
  }, []);
  const ok = mode === "pick" ? !!partId : !!name.trim();
  const submit = async () => {
    let id = partId;
    let label = parts?.find((p) => p.id === partId)?.name;
    if (mode === "new") {
      const made = await createMaintenancePart({ part_number: name.trim(), name: name.trim(), unit: unit.trim() || "each",
        ...(cost !== "" ? { unit_cost: Number(cost) } : {}) });
      id = made.id;
      label = made.name;
    }
    await addPositionPart(position.id, { part_id: id, role: "consumable", quantity: 1 });
    onDone(`${label} is a consumable at ${position.name}: type how much was added in its Record box.`);
  };
  return (
    <FormModal title="Add a consumable" submitLabel="Add" canSubmit={ok} onClose={onClose} onSubmit={submit}>
      <p className="lib-date">Something added at {position.name} that gets used up: salt, acid, a stabiliser. Each addition is kept, and comes out of stock where the part is held.</p>
      {parts && parts.length > 0 && (
        <Field label="It is">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="pick">A part in the parts register</option>
            <option value="new">A new one (added to the register)</option>
          </select>
        </Field>
      )}
      {mode === "pick" && parts && (
        <Field label="Part">
          <select value={partId} onChange={(e) => setPartId(e.target.value)} autoFocus>
            <option value="">Choose…</option>
            {parts.map((p) => <option key={p.id} value={p.id}>{p.part_number === p.name ? p.name : `${p.part_number} ${p.name}`}{p.unit ? ` (${p.unit})` : ""}</option>)}
          </select>
        </Field>
      )}
      {mode === "new" && (
        <>
          <Field label="Name" text={name}><input value={name} autoFocus placeholder="e.g. Pool salt" onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Counted in"><input value={unit} placeholder="kg, L, mL, bags" onChange={(e) => setUnit(e.target.value)} /></Field>
          <Field label="Cost of one (optional)"><input type="number" inputMode="decimal" step="any" min="0" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>
        </>
      )}
    </FormModal>
  );
}

const Back = ({ onBack }) => (
  <button type="button" className="link mv-back" onClick={onBack}>← Measurements</button>
);

// A consumable in full: its key is "<position id>:part:<id>" or "<position id>:name:<name>".
export function ConsumablePane({ id, today = workspaceToday(), onBack, onMenu = null }) {
  const confirm = useConfirm();
  const positionId = String(id).split(":")[0];
  const [state, setState] = useState({ row: null, error: null, loaded: false });
  const [modal, setModal] = useState(null);
  const load = useCallback(() => listMeasurementPoints({ positionIds: [positionId] })
    .then((d) => setState({ row: (d.consumables || []).find((c) => c.key === id) || null, error: null, loaded: true }))
    .catch((e) => setState({ row: null, error: e.message, loaded: true })), [id, positionId]);
  useEffect(() => { load(); }, [load]);
  const c = state.row;
  usePanelMenu(onMenu, c ? [
    { id: "use", label: "Record use…", onSelect: () => setModal("use") },
    c.listing_id ? { id: "retire", label: "Retire…", onSelect: () => confirm({
      title: `Retire ${c.name} here?`, body: `It comes off ${c.position.name}'s parts list. What was added stays in its history.`,
      confirmLabel: "Retire", pendingLabel: "Retiring…", failedWhat: "retire it",
      run: () => removePositionPart(c.listing_id).then(() => { onBack(); return true; }),
    }) } : null,
  ].filter(Boolean) : []);
  const months = useMemo(() => (c ? monthlyTotals(c.uses, today, 12) : []), [c, today]);
  if (!state.loaded) return <div className="td-tab-page mv-view">{onBack && <Back onBack={onBack} />}<p className="lib-date">Loading…</p></div>;
  if (!c) {
    return (
      <div className="td-tab-page mv-view">
        {onBack && <Back onBack={onBack} />}
        <div className={"card load-failed" + (state.error ? " error" : "")} role={state.error ? "alert" : "status"}>
          {state.error ? `Couldn't load it: ${state.error}` : "Consumable not found here. It may have been retired."}
        </div>
      </div>
    );
  }
  const last = c.uses[0];
  const st = consumableState(c, today);
  const lsa = lsaComparison(c, today);
  return (
    <div className="td-tab-page mv-view">
      {onBack && <Back onBack={onBack} />}
      <h3 className="mv-name">{c.name}</h3>
      <p className="lib-date mv-meta">{["Consumable", c.position.name, c.part?.part_number !== c.name && c.part?.part_number, c.unit].filter(Boolean).join(" · ")}</p>
      <div className="mp-facts" role="group" aria-label="Latest addition and totals">
        <div className="mp-fact">
          <span className="mp-fact-label">Last added</span>
          <span className="mp-fact-value">{last ? qtyText(last.qty, c.unit) : "Never"}</span>
          {last && <span className="lib-date">{dayText(last.on)} · {byText(last)}</span>}
        </div>
        <div className="mp-fact">
          <span className="mp-fact-label">Last 90 days</span>
          <span className="mp-fact-value">{st.label}</span>
          <span className="lib-date">{st.title}</span>
        </div>
        <div className="mp-fact">
          <span className="mp-fact-label">Stock</span>
          <span className="mp-fact-value">{c.part ? ((c.part.stock || []).filter((s) => s.on_hand > 0).map((s) => qtyText(s.on_hand, c.unit)).join(" + ") || "None") : "Not kept"}</span>
          <span className="lib-date">{c.part ? (c.part.stock || []).filter((s) => s.on_hand > 0).map((s) => s.location.name).join(", ") || "a use takes no stock" : "not in the parts register"}</span>
        </div>
      </div>

      <section className="mv-section" aria-label="What's been added over time">
        <h4>What&apos;s been added over time</h4>
        <p className="mv-summary">{yearTotal(c, today)}</p>
        {lsa.map((line) => <p key={line} className="lib-date mv-summary">{line}</p>)}
        {c.uses.length > 0 && (
          <Plot data={[{ type: "bar", x: months.map((m) => m.month), y: months.map((m) => m.value), marker: { color: ACCENT },
            hovertemplate: `%{x|%b %Y}: %{y:.4g}${c.unit ? ` ${c.unit}` : ""}<extra></extra>` }]}
                layout={{ height: 240, showlegend: false, margin: { l: 48, r: 16, t: 12, b: 36 }, xaxis: { type: "date", tickformat: "%b" },
                  yaxis: { title: { text: c.unit || "" }, rangemode: "tozero" } }}
                download={`${c.name} added by month`} />
        )}
      </section>

      <section className="mv-section" aria-label="Additions">
        <h4>Additions</h4>
        {c.uses.length ? (
          <ul className="mv-changes">
            {c.uses.map((u) => (
              <li key={u.id}>
                <span className="mv-change-text">{qtyText(u.qty, c.unit)} on {dayText(u.on)}</span>
                {u.work_order ? <> · <Link to={`/maintenance/work-orders/${u.work_order.id}`}>WO {u.work_order.number}</Link></> : <span className="lib-date"> · by hand</span>}
                {u.cost != null && <span className="lib-date"> · cost {Number(u.cost).toFixed(2)}</span>}
                {u.from_location && <span className="lib-date"> · from {u.from_location.name}</span>}
                {u.note && <span className="lib-date"> · {u.note}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="lib-date">Nothing added yet. <button type="button" className="crumb-link" onClick={() => setModal("use")}>Record the first addition</button>.</p>
        )}
      </section>
      {modal === "use" && <ConsumableUseModal consumable={c} onClose={() => setModal(null)} onDone={(row) => { setState((s) => ({ ...s, row })); setModal(null); }} />}
    </div>
  );
}
