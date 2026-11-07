import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { listMeasurementPoints } from "../api.js";
import { branchOf } from "../explorerTabs.js";
import { fmtDate } from "./MaintenanceParts.jsx";
import { PlusIcon } from "./LibRows.jsx";
import { readingWhen } from "../maintenanceReadings.js";
import {
  branchQuery, limitsText, needsAttention, placeOf, pointState, readMeasurementsQuery, readingDue, recentValues,
  recordedBy, sortPoints, stateText,
} from "../measurementsTab.js";
import { PointModal, PointReadingModal, ReadingsModal } from "../views/MaintenancePosition.jsx";
import "../views/Maintenance.css";
import "./MeasurementsPanel.css";

// The Measurements tab of the Explorer's panel (Assets › Explorer,
// ?tab=measurements): every measuring point on the picked row and everything
// inside it (a fitted item's own points too), worst first: where it is, its
// latest reading, when and how it was read, its limits and state in words, and
// a small trend. Record a reading, add a point to the picked position or item,
// or open a point's readings (the position page's own dialogs). The filter
// (?only=attention) and the point whose readings are open (?point=) are in the
// address, so a link opens the tab as it was.

function useMeasurementsQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (key, value) => {
    const next = new URLSearchParams(location.search);
    if (value) next.set(key, value);
    else next.delete(key);
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return {
    ...readMeasurementsQuery(params),
    setAttention: (on) => set("only", on ? "attention" : null),
    setPoint: (id) => set("point", id),
  };
}

// The last few readings as a tiny line, with the alarm limits dashed.
function Trend({ point }) {
  const rs = recentValues(point, 12);
  if (rs.length < 2) return <span className="lib-date">{rs.length ? "one reading" : "—"}</span>;
  const W = 84, H = 24;
  const vals = rs.map((r) => r.value).concat([point.alarm_above, point.alarm_below].filter((v) => v != null));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  const x = (i) => 2 + (i / (rs.length - 1)) * (W - 4);
  const d = rs.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.value).toFixed(1)}`).join(" ");
  const line = (v) => v != null && (
    <line x1="0" x2={W} y1={y(v)} y2={y(v)} stroke="var(--danger)" strokeDasharray="3 3" strokeWidth="1" />
  );
  return (
    <svg className="ms-trend" width={W} height={H} role="img"
         aria-label={`${point.name}: last ${rs.length} readings, ${rs[0].value} to ${rs[rs.length - 1].value}`}>
      {line(point.alarm_above)}
      {line(point.alarm_below)}
      <path d={d} fill="none" stroke="var(--acc)" strokeWidth="1.5" />
    </svg>
  );
}

const fmtValue = (v) => (typeof v === "number" ? Number(v.toPrecision(4)) : v);

export default function MeasurementsPanel({ row, display, today }) {
  const q = useMeasurementsQuery();
  const branch = useMemo(() => branchOf(display, row.key), [display, row.key]);
  const ask = useMemo(() => branchQuery(display, branch), [display, branch]);
  const [state, setState] = useState({ key: null, points: null, more: false, error: null });
  const [modal, setModal] = useState(null);
  const key = `${row.key}:${ask.positionIds.length}:${ask.itemIds.length}`;
  const load = useCallback(() => {
    let live = true;
    listMeasurementPoints({ positionIds: ask.positionIds, itemIds: ask.itemIds })
      .then((d) => live && setState({ key, points: d.points, more: d.more, error: null }))
      .catch((e) => live && setState({ key, points: [], more: false, error: e.message }));
    return () => { live = false; };
  }, [ask, key]);
  useEffect(() => load(), [load]);

  const points = state.key === key ? state.points : null;
  const sorted = useMemo(() => points && sortPoints(points, today, ask.fittedAt), [points, today, ask.fittedAt]);
  const shown = sorted && (q.attention ? sorted.filter((p) => needsAttention(p, today)) : sorted);
  const attention = sorted ? sorted.filter((p) => needsAttention(p, today)).length : 0;
  const branchy = branch.pos.size + branch.item.size + branch.loc.size > 1;
  const open = q.point && points?.find((p) => p.id === q.point);
  // A point is added to the picked position or item (a place has none of its own).
  const target = row.type === "pos" ? { kind: "position", id: row.key } : row.type === "item" ? { kind: "item", id: row.key } : null;
  const done = () => { setModal(null); load(); };
  const where = `at ${row.ref.name || "this row"}${branchy ? " and inside it" : ""}`;

  return (
    <div className="td-tab-page ms-panel">
      <div className="tablebar section-tablebar">
        <span className="count">{shown === null ? "Measurements"
          : `${shown.length} measuring point${shown.length === 1 ? "" : "s"} ${where}`}</span>
        <span className="grow" />
        <label className="maint-row lib-date td-tab-check" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="checkbox" checked={q.attention} onChange={(e) => q.setAttention(e.target.checked)} />
          Only points with readings due or past alarm{sorted ? ` (${attention})` : ""}
        </label>
      </div>
      <div className="maint-row td-tab-actions">
        <span className="lib-date">Read by hand or fed automatically. Worst first: past alarm, near a limit, due a reading.</span>
        <span className="grow" />
        {target
          ? <button className="sm" onClick={() => setModal({ add: true })}><PlusIcon /> Add a measuring point</button>
          : <span className="lib-date">Pick a position to add a measuring point.</span>}
      </div>
      {state.error && <div className="card error">{state.error}</div>}
      {state.more && <p className="lib-date">Showing the first {points.length} points: pick a smaller branch to see the rest.</p>}
      {shown === null ? <div className="card empty">Loading…</div> : shown.length === 0 ? (
        <div className="card empty">
          {q.attention && sorted.length > 0
            ? <>Nothing past alarm, near a limit or due a reading {where}. <button type="button" className="crumb-link" onClick={() => q.setAttention(false)}>Show every point</button></>
            : <>Nothing measured {where}. Add a counter (run hours, cycles) or a condition point (pH, chlorine, pressure,
              vibration) with alarm limits{target ? "" : " on one of the positions here"}.</>}
        </div>
      ) : (
        <div className="maint-scroll">
          <table className="lib-table ms-table">
            <thead>
              <tr>
                {branchy && <th>On</th>}
                <th>Measuring point</th><th>Latest</th><th>Limits</th><th>State</th><th>Trend</th><th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => {
                const s = pointState(p, today);
                const due = readingDue(p, today);
                const manual = p.source === "manual" && !p.derived;
                const posId = p.position?.id;
                return (
                  <tr key={p.id} className={q.point === p.id ? "ms-picked" : undefined}>
                    {branchy && (
                      <td data-label="On">
                        {posId ? <Link to={`/asset-register/positions/${posId}`}>{placeOf(p, ask.fittedAt)}</Link>
                          : p.item ? <Link to={`/asset-register/items/${p.item.id}`}>{placeOf(p, ask.fittedAt)}</Link> : "—"}
                      </td>
                    )}
                    <td data-label="Measuring point">
                      <strong>{p.name}</strong>
                      <div className="lib-date">{p.kind === "counter" ? "counts use" : "condition"}{p.unit ? ` · ${p.unit}` : ""}</div>
                    </td>
                    <td data-label="Latest">
                      {p.reading != null ? `${fmtValue(p.reading)}${p.unit ? ` ${p.unit}` : ""}` : "—"}
                      <div className="lib-date">
                        {p.read_at ? `${readingWhen({ when: p.read_when, precision: p.read_precision, at: p.read_at }, fmtDate)}, ${recordedBy(p)}` : recordedBy(p)}
                      </div>
                    </td>
                    <td data-label="Limits" className="lib-date">{limitsText(p)}</td>
                    <td data-label="State">
                      <span className={`ms-state ms-${s.key}`}>{stateText(p, today)}</span>
                      {due && <div className="ms-due">Reading due</div>}
                      {p.alarm_work_order && <div><Link to={`/maintenance/work-orders/${p.alarm_work_order.id}`}>#{p.alarm_work_order.number} open</Link></div>}
                    </td>
                    <td data-label="Trend"><Trend point={p} /></td>
                    <td className="ms-actions">
                      <div className="maint-row" style={{ marginTop: 0 }}>
                        {manual && <button className="secondary sm" onClick={() => setModal({ read: p })}
                                           aria-label={`Record a reading: ${p.name}`}>Record</button>}
                        {manual && p.readings?.length > 0 && (
                          <button className="secondary sm" onClick={() => q.setPoint(p.id)} aria-label={`Readings: ${p.name}`}>Readings</button>
                        )}
                        {!manual && posId && <Link className="lib-date" to={`/asset-register/positions/${posId}`}>Its page</Link>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {modal?.add && target && <PointModal target={target} onClose={() => setModal(null)} onDone={done} />}
      {modal?.read && <PointReadingModal point={modal.read} onClose={() => setModal(null)} onDone={done} />}
      {open && open.source === "manual" && (
        <ReadingsModal point={open} onClose={() => { q.setPoint(null); load(); }} />
      )}
    </div>
  );
}
