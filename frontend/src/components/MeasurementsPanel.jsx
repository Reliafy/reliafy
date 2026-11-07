import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { listMeasurementPoints, updateMeasurementPoint } from "../api.js";
import { branchOf } from "../explorerTabs.js";
import { Field, FormModal, fmtDate } from "./MaintenanceParts.jsx";
import { PlusIcon } from "./LibRows.jsx";
import Chip from "./ui/Chip.jsx";
import RowMenu from "./RowMenu.jsx";
import { readingWhen } from "../maintenanceReadings.js";
import {
  branchQuery, latestNote, needsAttention, pointChip, pointHref, pointMenu, pointPagePath, pointSubline, pointsCsv, readMeasurementsQuery,
  recentValues, recordedBy, rowAction, sortPoints,
} from "../measurementsTab.js";
import { usePanelMenu } from "../panelMenu.js";
import { saveText } from "../sparesPlan.js";
import { exportFilename } from "../rcmImport.js";
import { PointModal, PointReadingModal, ReadingsModal } from "../views/MaintenancePosition.jsx";
import PointMoveModal from "./PointMoveModal.jsx";
import "../views/Maintenance.css";
import "./MeasurementsPanel.css";

// The Measurements tab of the Explorer's panel (Assets › Explorer,
// ?tab=measurements): every measuring point on the picked row and everything
// inside it (a fitted item's own points too), worst first, one line each (two
// with the muted line under): the point, its latest value and when, one state
// chip, a small trend, and a ⋯ menu. The detail a row would otherwise carry
// (which limit, the limits, the reading's note) is in tooltips and the
// readings history, so the list stays scannable. Clicking a row opens its
// readings. The filter (?only=attention) and the point whose readings are open
// (?point=) are in the address, so a link opens the tab as it was. Where the
// panel is narrow (a phone) each point becomes a block. A new point: the
// dashed "+ Add a measuring point" row over the list, or the panel heading's
// "…" (given through `onMenu`), which also exports the points shown as CSV.

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

// The last few readings as a line at a fixed 120 × 28 px, with the alarm limits dashed.
const TREND_W = 120, TREND_H = 28;
function Trend({ point }) {
  const rs = recentValues(point, 12);
  if (rs.length < 2) {
    return <span className="lib-date ms-no-trend" title={rs.length ? "One reading so far" : "No readings yet"}>—</span>;
  }
  const W = TREND_W, H = TREND_H;
  const vals = rs.map((r) => r.value).concat([point.alarm_above, point.alarm_below].filter((v) => v != null));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  const x = (i) => 2 + (i / (rs.length - 1)) * (W - 4);
  const d = rs.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.value).toFixed(1)}`).join(" ");
  const line = (v) => v != null && (
    <line x1="0" x2={W} y1={y(v)} y2={y(v)} stroke="var(--danger)" strokeDasharray="3 3" strokeWidth="1" />
  );
  const last = rs[rs.length - 1];
  return (
    <svg className="ms-trend" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`${point.name}: last ${rs.length} readings, ${fmtValue(rs[0].value)} to ${fmtValue(last.value)}`}>
      {line(point.alarm_above)}
      {line(point.alarm_below)}
      <path d={d} fill="none" stroke="var(--acc)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(rs.length - 1)} cy={y(last.value)} r="2" fill="var(--acc)" />
    </svg>
  );
}

const fmtValue = (v) => (typeof v === "number" ? Number(v.toPrecision(4)) : v);

// A small mark for a reading that has a note: the note is its tooltip, and in full in the history.
const NoteMark = ({ note }) => (
  <span className="ms-note" role="img" aria-label={`Note: ${note}`} title={note}>
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 4h14v12l-4 4H5z" /><path d="M15 20v-4h4M9 9h6M9 13h4" />
    </svg>
  </span>
);

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

// A condition point's alarm limits: either may be left blank (no limit that side).
export function LimitsModal({ point, onClose, onDone }) {
  const str = (v) => (v == null ? "" : String(v));
  const [above, setAbove] = useState(str(point.alarm_above));
  const [below, setBelow] = useState(str(point.alarm_below));
  const num = (v) => (v.trim() === "" ? null : Number(v));
  const bad = above.trim() !== "" && below.trim() !== "" && Number(below) >= Number(above);
  const u = point.unit ? ` (${point.unit})` : "";
  return (
    <FormModal title={`Limits: ${point.name}`} submitLabel="Save" canSubmit={!bad} onClose={onClose}
               onSubmit={async () => onDone(await updateMeasurementPoint(point.id, { alarm_above: num(above), alarm_below: num(below) }))}>
      <p className="lib-date">An alarm when a reading goes past either limit. Leave one blank for no limit on that side.</p>
      <Field label={`Alarm above${u}`}><input type="number" inputMode="decimal" step="any" autoFocus value={above} onChange={(e) => setAbove(e.target.value)} /></Field>
      <Field label={`Alarm below${u}`}><input type="number" inputMode="decimal" step="any" value={below} onChange={(e) => setBelow(e.target.value)} /></Field>
      {bad && <p className="lib-date" role="alert">The low alarm must be below the high alarm.</p>}
    </FormModal>
  );
}

export default function MeasurementsPanel({ row, display, today, onMenu = null }) {
  const q = useMeasurementsQuery();
  const navigate = useNavigate();
  const branch = useMemo(() => branchOf(display, row.key), [display, row.key]);
  const ask = useMemo(() => branchQuery(display, branch), [display, branch]);
  const [state, setState] = useState({ key: null, points: null, more: false, error: null });
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null); // {point, at}
  const [moved, setMoved] = useState(null); // what the last Move… said
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
  const count = sorted && (q.attention
    ? `${shown.length} of ${sorted.length} measuring point${sorted.length === 1 ? "" : "s"} ${where}`
    : `${sorted.length} measuring point${sorted.length === 1 ? "" : "s"} ${where}`);

  const noTarget = "Pick a position or an item to add a measuring point: a place has none of its own.";
  const exportCsv = () => saveText(pointsCsv(shown || [], today, ask.fittedAt), exportFilename(row.ref.name, { what: "measuring points" }));
  usePanelMenu(onMenu, [
    { id: "point-new", label: "Add a measuring point…", onSelect: () => setModal({ add: true }), disabled: !target, title: target ? "" : noTarget },
    { id: "points-csv", label: "Export CSV", onSelect: exportCsv, disabled: !shown?.length, title: shown?.length ? "" : "No measuring points to export" },
  ]);

  const act = (id, p) => {
    if (id === "page") navigate(pointPagePath(p.id));
    else if (id === "record") setModal({ read: p });
    else if (id === "history") q.setPoint(p.id);
    else if (id === "limits") setModal({ limits: p });
    else if (id === "open") navigate(pointHref(p));
    else if (id === "work-order") navigate(`/maintenance/work-orders/${p.alarm_work_order.id}`);
    else if (id === "move") setModal({ move: p });
  };
  const openRow = (p) => {
    const a = rowAction(p);
    if (a) act(a, p);
  };
  const openMenu = (e, p) => {
    e.stopPropagation();
    const b = e.currentTarget.getBoundingClientRect();
    setMenu({ point: p, at: { x: b.right, y: b.bottom + 2 } });
  };

  return (
    <div className="td-tab-page ms-panel">
      <p className="lib-date ms-purpose">Read by hand or fed automatically, worst first: past alarm, near a limit, due a reading.</p>
      {sorted && sorted.length > 0 && (
        <div className="ms-bar">
          <button type="button" aria-pressed={q.attention} onClick={() => q.setAttention(!q.attention)}
                  className={"chip chip-btn ms-filter " + (q.attention ? "chip-accent" : "chip-neutral")}
                  title="Past alarm, near a limit, or due a reading">
            Needs attention ({attention})
          </button>
          <span className="lib-date ms-count">{count}</span>
        </div>
      )}
      {/* The list's add row, first: a point goes on the picked position or item. */}
      {target ? (
        <button type="button" className="add-row ms-add" onClick={(e) => { if (e.detail < 2) setModal({ add: true }); }}>
          <PlusIcon /> Add a measuring point
        </button>
      ) : <p className="lib-date ms-add-note">Pick a position or an item to add a measuring point.</p>}
      {moved && <p className="lib-date ms-moved" role="status">{moved}</p>}
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
        <div className="ms-list">
          <table className="lib-table ms-table">
            <colgroup>
              <col /><col className="ms-c-latest" /><col className="ms-c-state" /><col className="ms-c-trend" /><col className="ms-c-menu" />
            </colgroup>
            <thead>
              <tr>
                <th>Point</th><th className="ms-num">Latest</th><th>State</th><th>Trend</th><th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => {
                const chip = pointChip(p, today);
                const note = latestNote(p);
                const sub = pointSubline(p, { branch: branchy, fittedAt: ask.fittedAt });
                const when = p.read_at ? readingWhen({ when: p.read_when, precision: p.read_precision, at: p.read_at }, fmtDate) : "";
                const by = recordedBy(p);
                const action = rowAction(p);
                const rowTitle = action === "history" ? "Open its readings" : action === "record" ? "Record its first reading" : action === "open" ? `Open its ${p.position?.id ? "position" : "item"}` : undefined;
                return (
                  <tr key={p.id} id={`ms-${p.id}`}
                      className={"ms-row" + (action ? " ms-clickable" : "") + (q.point === p.id || menu?.point.id === p.id ? " ms-picked" : "")}
                      onClick={() => openRow(p)} title={rowTitle}
                      onContextMenu={(e) => { e.preventDefault(); setMenu({ point: p, at: { x: e.clientX, y: e.clientY } }); }}>
                    <td className="ms-point">
                      {/* The name opens the point's own page; the rest of the row its readings (or first reading). */}
                      <Link className="ms-name" to={pointPagePath(p.id)} title={`${p.name}: open its page`}
                            onClick={(e) => e.stopPropagation()}>{p.name}</Link>
                      <span className="lib-date ms-sub" title={sub}>{sub}</span>
                    </td>
                    <td className="ms-latest">
                      <span className="ms-value-line">
                        {note && <NoteMark note={note} />}
                        <strong className="ms-value">{p.reading != null ? `${fmtValue(p.reading)}${p.unit ? ` ${p.unit}` : ""}` : "—"}</strong>
                      </span>
                      <span className="lib-date ms-sub" title={when ? `${when}, ${by}` : by}>
                        {when ? `${when}${p.source === "manual" && !p.derived ? "" : ` · ${p.derived ? "signal" : "feed"}`}` : p.reading == null ? "never read" : by}
                      </span>
                    </td>
                    <td className="ms-state-cell">
                      <Chip tone={chip.tone} className={`ms-chip ms-${chip.key}`} title={chip.title}>{chip.label}</Chip>
                      {p.alarm_work_order && <span className="lib-date ms-wo" title={`Work order #${p.alarm_work_order.number} is open`}>#{p.alarm_work_order.number}</span>}
                    </td>
                    <td className="ms-trend-cell"><Trend point={p} /></td>
                    <td className="ms-menu-cell">
                      <button type="button" className={"ms-more" + (menu?.point.id === p.id ? " open" : "")} aria-haspopup="menu"
                              aria-expanded={menu?.point.id === p.id} aria-label={`Actions for ${p.name}`} title="Actions"
                              onClick={(e) => openMenu(e, p)}>
                        <MoreIcon />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {menu && (
        <RowMenu items={pointMenu(menu.point)} at={menu.at} label={`Actions for ${menu.point.name}`} anchorId={`ms-${menu.point.id}`}
                 onChoose={(id) => act(id, menu.point)}
                 onClose={() => {
                   const id = menu.point.id;
                   setMenu(null);
                   document.getElementById(`ms-${id}`)?.querySelector(".ms-more")?.focus({ preventScroll: true });
                 }} />
      )}
      {modal?.add && target && <PointModal target={target} onClose={() => setModal(null)} onDone={done} />}
      {modal?.read && <PointReadingModal point={modal.read} onClose={() => setModal(null)} onDone={done} />}
      {modal?.limits && <LimitsModal point={modal.limits} onClose={() => setModal(null)} onDone={done} />}
      {modal?.move && (
        <PointMoveModal point={modal.move} onClose={() => setModal(null)}
                        onDone={(r) => {
                          setMoved(`${r.name} moved to ${r.position?.name || "its new position"}.${r.note ? ` ${r.note}` : ""}`);
                          done();
                        }} />
      )}
      {open && open.source === "manual" && (
        <ReadingsModal point={open} onClose={() => { q.setPoint(null); load(); }} />
      )}
    </div>
  );
}
