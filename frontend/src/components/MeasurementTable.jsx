import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  listMeasurementPoints, recordConsumableUse, recordMeasurementReading, removePositionPart, retireMeasurementPoint,
} from "../api.js";
import Chip from "./ui/Chip.jsx";
import { ChannelPane, LimitsModal, PointView } from "./MeasurementViews.jsx";
import { AddConsumableModal, ConsumablePane, ConsumableUseModal, UseBars } from "./ConsumableViews.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import NewChannel from "./SignalChannelForm.jsx";
import PointMoveModal from "./PointMoveModal.jsx";
import { PointModal, PointReadingModal } from "../views/MaintenancePosition.jsx";
import { measurementAsk } from "../explorerMeasurements.js";
import { MEAS_COLUMNS, checkValue, rowMenu, savedText, whenText } from "../measurementsTable.js";
import { recentValues, withUnit } from "../measurementsTab.js";
import { numberText } from "../measuringPoint.js";
import "./MeasurementTable.css";

// The Explorer's Measurements tab is the tree with each position's measurement
// rows in it (explorerMeasurements.js), like the RCM tab. This file has what
// the page needs for it: the read of every position's points, channels and
// consumables; each row's cells (Kind, Latest, State, Trend, Next due, and the
// Record box: type a value, Enter records it now); the row's ⋯ items; its
// phone line; the details beside the table for a row picked (a point's
// history, a setting's changes, a channel's spectrum, a consumable's
// additions); and the dialogs its actions open.

// The table's columns beside the tree (the tree is the Position and Point).
export const MEAS_TABLE_COLS = MEAS_COLUMNS.filter((c) => c.id !== "position" && c.id !== "point");
export const MEAS_TREE_HEAD = "Position, and what's measured, set or added there";

const NO_FITTED = new Map();

// Every position's measurements, read when the tab is on (and again on
// `load`); `patch` puts a point or consumable the server sent back in place.
export function useTreeMeasurements({ on, display }) {
  const [state, setState] = useState({ data: null, error: null });
  // What to ask for (and where fitted items' rows go): only when the tree changes,
  // so the tree grafted from it stays the same object between renders.
  const ask = useMemo(() => (on && display ? measurementAsk(display) : null), [on, display]);
  const load = useCallback(() => {
    if (!ask) return Promise.resolve();
    const a = ask;
    return listMeasurementPoints({ positionIds: a.positionIds, itemIds: a.itemIds })
      .then((data) => setState({ data, error: null }))
      .catch((e) => setState((s) => ({ data: s.data, error: e.message })));
  }, [ask]);
  useEffect(() => { if (on) load(); }, [on, load]);
  const patch = useCallback((fresh) => setState((s) => {
    if (!s.data || !fresh) return s;
    if (fresh.uses !== undefined) {
      const has = s.data.consumables.some((c) => c.key === fresh.key);
      return { ...s, data: { ...s.data, consumables: has ? s.data.consumables.map((c) => (c.key === fresh.key ? fresh : c)) : [...s.data.consumables, fresh] } };
    }
    return { ...s, data: { ...s.data, points: s.data.points.map((p) => (p.id === fresh.id ? { ...p, ...fresh } : p)) } };
  }), []);
  return { data: state.data, error: state.error, fittedAt: ask?.fittedAt || NO_FITTED, load, patch };
}

// The last few values as a line at a fixed 120 × 28 px, alarm limits dashed;
// a setting's as steps.
const TREND_W = 120, TREND_H = 28;
const fmtValue = (v) => (typeof v === "number" ? Number(v.toPrecision(4)) : v);
export function Trend({ point, values = null }) {
  const rs = values || recentValues(point, 12);
  if (rs.length < 2) {
    return <span className="lib-date ms-no-trend" title={rs.length ? "One reading so far" : "No readings yet"}>—</span>;
  }
  const W = TREND_W, H = TREND_H;
  const vals = rs.map((r) => r.value).concat([point.alarm_above, point.alarm_below].filter((v) => v != null));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  const x = (i) => 2 + (i / (rs.length - 1)) * (W - 4);
  const d = point.kind === "setting"
    ? rs.map((r, i) => (i ? `H${x(i).toFixed(1)} V${y(r.value).toFixed(1)}` : `M${x(0).toFixed(1)} ${y(r.value).toFixed(1)}`)).join(" ")
    : rs.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.value).toFixed(1)}`).join(" ");
  const line = (v) => v != null && <line x1="0" x2={W} y1={y(v)} y2={y(v)} stroke="var(--danger)" strokeDasharray="3 3" strokeWidth="1" />;
  const last = rs[rs.length - 1];
  return (
    <svg className="ms-trend" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`${point.name}: last ${rs.length} values, ${fmtValue(rs[0].value)} to ${fmtValue(last.value)}`}>
      {line(point.alarm_above)}
      {line(point.alarm_below)}
      <path d={d} fill="none" stroke="var(--acc)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(rs.length - 1)} cy={y(last.value)} r="2" fill="var(--acc)" />
    </svg>
  );
}

// A row's Record box: type a value, Enter records it now (a consumable: how
// much was added, today). "✓ Saved" ("✓ Set to 28 °C", "✓ Added 20 kg") for a
// few seconds; a refusal stays under it.
export function RecordBox({ row, onSaved }) {
  const p = row.item;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState(null); // {ok, text}
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  if (!row.canRecord) {
    return <span className="lib-date ms-rec-none" title={row.type === "channel" ? "Its sensor sends the values" : "Read by a feed"}>—</span>;
  }
  const save = async () => {
    const got = checkValue(text, p);
    if (got.error) { setSaid({ ok: false, text: got.error }); return; }
    setBusy(true);
    try {
      // Now, as an instant (the server puts it on the workspace's day and clock).
      const now = new Date().toISOString().slice(0, 16) + "Z";
      const fresh = row.type === "consumable"
        ? (await recordConsumableUse(p.position.id, { qty: got.value, at: now,
          ...(p.part ? { part_id: p.part.id } : { name: p.name, unit: p.unit }) })).consumable
        : await recordMeasurementReading(p.id, got.value, undefined, now);
      setText("");
      setSaid({ ok: true, text: savedText(p, got.value) });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setSaid(null), 4000);
      onSaved(fresh);
    } catch (e) {
      setSaid({ ok: false, text: e.message });
    }
    setBusy(false);
  };
  const setting = p.kind === "setting";
  const used = row.type === "consumable";
  return (
    <span className="ms-rec" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      <input type="text" inputMode="decimal" className="ms-rec-input" value={text} disabled={busy}
             placeholder={used ? `Add${p.unit ? ` ${p.unit}` : ""}…` : setting ? "Set to…" : "Record…"}
             aria-label={used ? `Quantity of ${p.name} added${p.unit ? ` (${p.unit})` : ""}` : `${setting ? "New setting" : "New reading"} for ${p.name}${p.unit ? ` (${p.unit})` : ""}`}
             title={used ? `Type how much was added${p.unit ? ` in ${p.unit}` : ""} and press Enter: recorded today. ${row.stock}`
               : `Type a value${p.unit ? ` in ${p.unit}` : ""} and press Enter to record it now`}
             onChange={(e) => { setText(e.target.value); if (said && !said.ok) setSaid(null); }}
             onKeyDown={(e) => {
               e.stopPropagation(); // the tree's own keys (arrows, F, letters) stay out of the box
               if (e.key === "Enter") { e.preventDefault(); save(); }
               if (e.key === "Escape") { setText(""); setSaid(null); }
             }} />
      {said && <span className={"ms-rec-said" + (said.ok ? " ok" : " bad")} role={said.ok ? "status" : "alert"}>{said.text}</span>}
    </span>
  );
}

// One cell of a measurement row (the tree row `r`, its table row r.ref.row).
export function MeasCell({ r, col, onSaved }) {
  const row = r.ref.row;
  switch (col.id) {
    case "kind": return <Chip tone={row.kind === "Setting" ? "accent" : "neutral"} className="pk-kind">{row.kind}</Chip>;
    case "latest":
      return row.value == null ? <span className="rw-blank">—</span> : (
        <span className="mt-latest" title={whenText(row.when)}>
          <strong>{withUnit(numberText(row.value), row.unit)}</strong>
          <span className="rw-sum">{whenText(row.when)}</span>
        </span>
      );
    case "state": return <Chip tone={row.state.tone} className="ms-chip" title={[row.state.title, row.stock].filter(Boolean).join(". ")}>{row.state.label}</Chip>;
    case "trend":
      if (row.bars) return <UseBars values={row.values} unit={row.unit} name={row.name} />;
      return <Trend point={{ ...row.item, kind: row.step ? "setting" : row.item.kind, name: row.name }} values={row.values} />;
    case "due": return row.due ? <span className={row.state.label === "Due" || row.state.label === "No reading" ? "pk-overdue" : undefined}>{whenText(row.due)}</span> : null;
    case "record": return <RecordBox row={row} onSaved={onSaved} />;
    default: return null;
  }
}

// A row's second line on a phone: its latest value and when; the state as its chip.
export function measPhoneRow(r, rollup) {
  if (r.type !== "meas") return { line: rollup || "", status: null };
  const row = r.ref.row;
  const latest = row.value == null ? "" : `${withUnit(numberText(row.value), row.unit)} · ${whenText(row.when)}`;
  return {
    line: [row.kind, latest].filter(Boolean).join(" · "),
    status: <Chip tone={row.state.tone} className="ms-chip" title={row.state.title}>{row.state.label}</Chip>,
  };
}

// The row's ⋯ (the tree's row menu): Open, Record…, Edit…, Move…, Retire….
export const measRowActions = (r) => rowMenu(r.ref.row).map((it) => ({ ...it, id: `meas-${it.id}` }));

// The details beside the table for a row picked: its view, with Expand / Back
// to table and Close in its head. Its actions go in the heading's "…" (onMenu).
export function MeasSide({ r, phone, expanded, onExpand, onCollapse, onClose, headingRef, onMenu, onChanged, today }) {
  const row = r.ref.row;
  const kind = row.type === "consumable" ? "Consumable" : row.type === "channel" ? "Sensor channel" : row.kind === "Setting" ? "Setting" : "Measuring point";
  return (
    <aside className={"rw-panel mt-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select")) return;
             e.stopPropagation();
             if (expanded) onCollapse(); else onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind">{kind}</div>
          <div className="rw-panel-btns">
            {!phone && (expanded ? (
              <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)" aria-label="Back to table"><ShrinkIcon /></button>
            ) : (
              <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them" aria-label="Expand the details"><ExpandIcon /></button>
            ))}
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{row.name}</h2>
      </div>
      <div className="rw-pbody mt-pbody">
        {row.type === "consumable" ? <ConsumablePane key={row.item.key} id={row.item.key} today={today} onMenu={onMenu} />
          : row.type === "channel" ? <ChannelPane key={row.item.id} id={row.item.id} onMenu={onMenu} />
            : <PointView key={row.item.id} id={row.item.id} onMenu={onMenu} onChanged={onChanged} />}
      </div>
    </aside>
  );
}

// The dialogs the tab's actions open: {kind: "add" (point or setting: preset),
// "consumable", "channel" (on a position: `target`), "read", "limits", "move",
// "use" (on a row's point or consumable: `item`)}.
export function MeasDialogs({ modal, onClose, onDone, onSaid }) {
  if (!modal) return null;
  const done = (text) => { if (text) onSaid?.(text); onDone(); };
  switch (modal.kind) {
    case "add": return <PointModal target={modal.target} kind={modal.preset || "condition"} onClose={onClose} onDone={() => done()} />;
    case "consumable": return <AddConsumableModal position={modal.position} onClose={onClose} onDone={done} />;
    case "channel": return <NewChannel target={modal.target.kind === "item" ? { itemId: modal.target.id } : { positionId: modal.target.id }} onCancel={onClose} onDone={() => done()} />;
    case "read": return <PointReadingModal point={modal.item} onClose={onClose} onDone={() => done()} />;
    case "limits": return <LimitsModal point={modal.item} onClose={onClose} onDone={() => done()} />;
    case "move": return <PointMoveModal point={modal.item} onClose={onClose} onDone={(r) => done(`${r.name} moved to ${r.position?.name || "its new position"}.${r.note ? ` ${r.note}` : ""}`)} />;
    case "use": return <ConsumableUseModal consumable={modal.item} onClose={onClose} onDone={() => done()} />;
    default: return null;
  }
}

// Retire… on a row: a point (its readings stay), or a consumable off its position's parts list.
export function retireMeasurement(confirm, row, onDone) {
  const p = row.item;
  if (row.type === "consumable") {
    return confirm({
      title: `Retire ${p.name} here?`,
      body: `It comes off ${p.position.name}'s parts list${p.uses.length ? "; what was added stays in its history, and the row stays while it has additions recorded by hand" : ""}.`,
      confirmLabel: "Retire", pendingLabel: "Retiring…", failedWhat: "retire it",
      run: () => removePositionPart(p.listing_id).then(() => { onDone(`Retired ${p.name} at ${p.position.name}.`); return true; }),
    });
  }
  return confirm({
    title: `Retire ${p.name}?`,
    body: "It stops being measured and leaves the table. Its readings stay in the history.",
    confirmLabel: "Retire", pendingLabel: "Retiring…", failedWhat: "retire it",
    run: () => retireMeasurementPoint(p.id).then(() => { onDone(`Retired ${p.name}.`); return true; }),
  });
}
