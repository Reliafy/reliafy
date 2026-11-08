import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { listMeasurementPoints, recordMeasurementReading, retireMeasurementPoint } from "../api.js";
import { branchOf } from "../explorerTabs.js";
import { ChannelPane, LimitsModal, PointView } from "./MeasurementViews.jsx";
import Chip from "./ui/Chip.jsx";
import RowMenu from "./RowMenu.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { ColumnChooser } from "./RcmWorksheet.jsx";
import { ShowMe } from "./SectionPage.jsx";
import { VIEW_PARAMS, branchQuery, pointPagePath, readMeasurementsQuery, recentValues, withUnit } from "../measurementsTab.js";
import {
  DEFAULT_MEAS_COLUMNS, MEAS_COLUMNS, checkValue, groupRows, groupText, measurementsCsv, nextSort, parseSort, rowMenu,
  savedText, searchRows, sortParam, sortRows, sortable, tableRows, whenText,
} from "../measurementsTable.js";
import { numberText } from "../measuringPoint.js";
import { channelPath } from "../signals.js";
import NewChannel from "./SignalChannelForm.jsx";
import { usePanelMenu } from "../panelMenu.js";
import { saveText } from "../sparesPlan.js";
import { exportFilename } from "../rcmImport.js";
import { PointModal, PointReadingModal, ReadingsModal } from "../views/MaintenancePosition.jsx";
import PointMoveModal from "./PointMoveModal.jsx";
import "./RcmWorksheet.css";
import "./LsaPanel.css";
import "../views/Maintenance.css";
import "./MeasurementsPanel.css";

// The Measurements tab of the Explorer's panel (Assets › Explorer,
// ?tab=measurements; Derryn, 9 Nov 2026): a table of every measuring point,
// setting and sensor channel on the picked row and everything below it
// (positions, items, places), one row each: Position, Point (name, tag), Kind
// (Condition, Setting, Counter, Fed), Latest (value with unit, and when),
// State (OK, Needs attention, Due, No reading; a setting: "Set 1 Oct 2026"),
// Trend (a sparkline; a setting's is a step line), Next due, a Record box and
// a ⋯ (Open, Record a reading…, Edit limits…, Move…, Retire…). The same table
// as the LSA tab's (LsaPanel.jsx): search over every column (?q=), sortable
// headers (?sort=, Shift-click for a second key; worst first when none),
// Columns… and Export CSV in the heading's "…". When the rows are on several
// positions they're grouped under a quiet row per position, which folds.
//
// Type a value in a row's Record box and press Enter: it's recorded now (a
// setting's new value: "✓ Set to 28 °C"), the row's value and sparkline
// update. The heading's "…" adds a measuring point, a setting (the same
// dialog, kind preset) or a sensor channel; so does the empty state.
//
// A point's or channel's name (or Open) shows it in full in the tab
// (?point=, ?channel=: MeasurementViews.jsx, with "← Measurements" back): its
// history, for a setting what it's been over time and each change.
// ?only=attention keeps the rows that need a look; ?readings= opens a
// point's Readings dialog (older links).

function useMeasurementsQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (key, value, { push = false, hash = location.hash } = {}) => {
    const next = new URLSearchParams(location.search);
    if (value) next.set(key, value);
    else next.delete(key);
    navigate(`${location.pathname}?${next}${hash}`, { replace: !push, state: location.state });
  };
  return {
    ...readMeasurementsQuery(params),
    setAttention: (on) => set("only", on ? "attention" : null),
    setReadings: (id) => set("readings", id),
    // Back to the list from a point or channel open in full (a new history entry, so Back returns to it).
    closeView: () => {
      const next = new URLSearchParams(location.search);
      for (const k of VIEW_PARAMS) next.delete(k);
      navigate(`${location.pathname}?${next}`, { state: location.state });
    },
  };
}

// The last few readings as a line at a fixed 120 × 28 px, with the alarm limits dashed.
const TREND_W = 120, TREND_H = 28;
function Trend({ point, values = null }) {
  const rs = values || recentValues(point, 12);
  if (rs.length < 2) {
    return <span className="lib-date ms-no-trend" title={rs.length ? "One reading so far" : "No readings yet"}>—</span>;
  }
  const W = TREND_W, H = TREND_H;
  const vals = rs.map((r) => r.value).concat([point.alarm_above, point.alarm_below].filter((v) => v != null));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  const x = (i) => 2 + (i / (rs.length - 1)) * (W - 4);
  // A setting holds its value until the next change: drawn as steps.
  const d = point.kind === "setting"
    ? rs.map((r, i) => (i ? `H${x(i).toFixed(1)} V${y(r.value).toFixed(1)}` : `M${x(0).toFixed(1)} ${y(r.value).toFixed(1)}`)).join(" ")
    : rs.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.value).toFixed(1)}`).join(" ");
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

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

// The tab: the list, or (with ?point= or ?channel=) one point or channel in
// full, with a link back to the list.
export default function MeasurementsPanel(props) {
  const q = useMeasurementsQuery();
  if (q.point) return <PointView key={q.point} id={q.point} onBack={q.closeView} onMenu={props.onMenu} />;
  if (q.channel) return <ChannelPane key={q.channel} id={q.channel} onBack={q.closeView} onMenu={props.onMenu} />;
  return <MeasurementsList {...props} q={q} />;
}

const COLS_KEY = "reliafy.measurements.columns";
function readCols() {
  try {
    const got = JSON.parse(localStorage.getItem(COLS_KEY) || "null");
    if (Array.isArray(got) && got.length) return DEFAULT_MEAS_COLUMNS.filter((id) => got.includes(id));
  } catch { /* storage blocked: the usual columns */ }
  return DEFAULT_MEAS_COLUMNS;
}
function saveCols(cols) {
  try { localStorage.setItem(COLS_KEY, JSON.stringify(cols)); } catch { /* not kept */ }
}

// ?q= and ?sort=, kept in the address (each change starts from the address as
// it is when written, so a sort clicked while the search box waits isn't lost).
function useTableQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (changes) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(changes)) if (v) next.set(k, v); else next.delete(k);
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return {
    q: params.get("q") || "", setQ: (v) => set({ q: v }),
    sort: parseSort(params.get("sort")), setSort: (keys) => set({ sort: sortParam(keys) }),
  };
}

// A row's Record box: type a value, Enter records it now. Saved: "✓ Saved" (a
// setting: "✓ Set to 28 °C") for a few seconds; a refusal stays under it.
function RecordBox({ r, onSaved }) {
  const p = r.item;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState(null); // {ok, text}
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  if (!r.canRecord) {
    return <span className="lib-date ms-rec-none" title={r.type === "channel" ? "Its sensor sends the values" : "Read by a feed"}>—</span>;
  }
  const save = async () => {
    const got = checkValue(text, p);
    if (got.error) { setSaid({ ok: false, text: got.error }); return; }
    setBusy(true);
    try {
      // Now, as an instant (the server puts it on the workspace's day and clock).
      const fresh = await recordMeasurementReading(p.id, got.value, undefined, new Date().toISOString().slice(0, 16) + "Z");
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
  return (
    <span className="ms-rec">
      <input type="text" inputMode="decimal" className="ms-rec-input" value={text} disabled={busy}
             placeholder={setting ? "Set to…" : "Record…"} aria-label={`${setting ? "New setting" : "New reading"} for ${p.name}${p.unit ? ` (${p.unit})` : ""}`}
             title={`Type a value${p.unit ? ` in ${p.unit}` : ""} and press Enter to record it now`}
             onChange={(e) => { setText(e.target.value); if (said && !said.ok) setSaid(null); }}
             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } if (e.key === "Escape") { setText(""); setSaid(null); } }} />
      {said && <span className={"ms-rec-said" + (said.ok ? " ok" : " bad")} role={said.ok ? "status" : "alert"}>{said.text}</span>}
    </span>
  );
}

function Cell({ r, col, onOpen }) {
  switch (col) {
    case "position": return <span className="rw-txt" title={r.place.name}>{r.place.name || <span className="rw-blank">—</span>}</span>;
    case "point":
      return (
        <span className="pk-two">
          <button type="button" className="link ms-name-link" onClick={() => onOpen(r)} title={`Open ${r.name}: its history${r.step ? " and changes" : ""}`}>{r.name}</button>
          {r.tag && <span className="rw-sum" title={`Tag ${r.tag}`}>{r.tag}</span>}
        </span>
      );
    case "kind": return <Chip tone={r.kind === "Setting" ? "accent" : "neutral"} className="pk-kind">{r.kind}</Chip>;
    case "latest":
      return r.value == null ? <span className="rw-blank pk-num">—</span> : (
        <span className="pk-two ms-latest-cell" title={r.when ? `${whenText(r.when)}` : undefined}>
          <strong className="pk-num">{withUnit(numberText(r.value), r.unit)}</strong>
          <span className="rw-sum pk-num">{whenText(r.when)}</span>
        </span>
      );
    case "state": return <Chip tone={r.state.tone} className="ms-chip" title={r.state.title}>{r.state.label}</Chip>;
    case "trend": return <Trend point={{ ...r.item, kind: r.step ? "setting" : r.item.kind, name: r.name }} values={r.values} />;
    case "due": return r.due ? <span className={r.state.label === "Due" || r.state.label === "No reading" ? "pk-overdue" : undefined}>{whenText(r.due)}</span> : null;
    default: return null;
  }
}

function MeasurementsList({ row, display, today, onMenu = null, q }) {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const tq = useTableQuery();
  const branch = useMemo(() => branchOf(display, row.key), [display, row.key]);
  const ask = useMemo(() => branchQuery(display, branch), [display, branch]);
  const [state, setState] = useState({ key: null, points: null, channels: [], more: false, error: null });
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null); // {r, at}
  const [said, setSaid] = useState(null);
  const [cols, setColsState] = useState(readCols);
  const [colsOpen, setColsOpen] = useState(false);
  const [query, setQuery] = useState(tq.q);
  const [folded, setFolded] = useState(() => new Set());
  const key = `${row.key}:${ask.positionIds.length}:${ask.itemIds.length}`;
  const load = useCallback(() => {
    let live = true;
    listMeasurementPoints({ positionIds: ask.positionIds, itemIds: ask.itemIds })
      .then((d) => live && setState({ key, points: d.points, channels: d.channels || [], more: d.more, error: null }))
      .catch((e) => live && setState({ key, points: [], channels: [], more: false, error: e.message }));
    return () => { live = false; };
  }, [ask, key]);
  useEffect(() => load(), [load]);
  // The search box writes the address a moment after typing stops.
  useEffect(() => {
    if (query === tq.q) return undefined;
    const t = setTimeout(() => tq.setQ(query), 250);
    return () => clearTimeout(t);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  const points = state.key === key ? state.points : null;
  const channels = state.key === key ? state.channels : null;
  const all = useMemo(() => points && tableRows(points, channels, today, ask.fittedAt), [points, channels, today, ask.fittedAt]);
  const shown = useMemo(() => {
    if (!all) return null;
    const kept = q.attention ? all.filter((r) => r.attention) : all;
    return sortRows(searchRows(kept, query), tq.sort);
  }, [all, q.attention, query, tq.sort]);
  const groups = useMemo(() => shown && groupRows(shown), [shown]);
  const attention = all ? all.filter((r) => r.attention).length : 0;
  // Grouped: each group row names the position, so the Position column goes.
  const columns = MEAS_COLUMNS.filter((c) => cols.includes(c.id) && !(groups && c.id === "position"));
  const total = columns.reduce((n, c) => n + c.width, 0) + 44;
  const open = q.readings && points?.find((p) => p.id === q.readings);
  // A point is added to the picked position or item (a place has none of its own).
  const target = row.type === "pos" ? { kind: "position", id: row.key } : row.type === "item" ? { kind: "item", id: row.key } : null;
  const done = () => { setModal(null); load(); };
  const branchy = branch.pos.size + branch.item.size + branch.loc.size > 1;
  const where = `at ${row.ref.name || "this row"}${branchy ? " and below" : ""}`;
  const setCols = (next) => { setColsState(next); saveCols(next); };
  // A value recorded in place: the row takes the point the server sends back.
  const saved = (fresh) => setState((s) => ({ ...s, points: s.points.map((p) => (p.id === fresh.id ? { ...p, ...fresh } : p)) }));

  const noTarget = "Pick a position or an item: a place has none of its own.";
  const adds = [
    { id: "point-new", label: "Add a measuring point…", onSelect: () => setModal({ add: "condition" }), disabled: !target, title: target ? "" : noTarget },
    { id: "setting-new", label: "Add a setting…", onSelect: () => setModal({ add: "setting" }), disabled: !target, title: target ? "Something someone sets (a setpoint, output %, hours a day): its changes are kept" : noTarget },
    { id: "channel-new", label: "Add a sensor channel…", onSelect: () => setModal({ channel: true }), disabled: !target, title: target ? "" : noTarget },
  ];
  usePanelMenu(onMenu, [
    ...adds,
    { id: "points-cols", label: "Columns…", onSelect: () => setColsOpen(true) },
    { id: "points-csv", label: "Export CSV", disabled: !shown?.length, title: shown?.length ? "The rows shown, for Excel" : "Nothing to export",
      onSelect: () => saveText(measurementsCsv(shown || []), exportFilename(row.ref.name, { what: "measurements" })) },
  ]);

  const openRow = (r) => navigate(r.type === "channel" ? channelPath(r.item) : pointPagePath(r.item));
  const retire = (p) => confirm({
    title: `Retire ${p.name}?`,
    body: "It stops being measured and leaves this table. Its readings stay in the history.",
    confirmLabel: "Retire", pendingLabel: "Retiring…", failedWhat: "retire it",
    run: () => retireMeasurementPoint(p.id).then(() => { setSaid(`Retired ${p.name}.`); load(); return true; }),
  });
  const act = (id, r) => {
    const p = r.item;
    if (id === "page") openRow(r);
    else if (id === "bands") navigate(channelPath(p, { bands: true }));
    else if (id === "record") setModal({ read: p });
    else if (id === "limits") setModal({ limits: p });
    else if (id === "move") setModal({ move: p });
    else if (id === "retire") retire(p);
  };
  const openMenu = (e, r) => {
    e.stopPropagation();
    const b = e.currentTarget.getBoundingClientRect();
    setMenu({ r, at: { x: b.right, y: b.bottom + 2 } });
  };
  const fold = (k) => setFolded((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  const rowEl = (r) => (
    <div key={r.key} id={`ms-${r.key.replace(":", "-")}`} role="row"
         className={"rw-row pk-trow ms-trow" + (menu?.r.key === r.key ? " focus" : "")}
         onContextMenu={(e) => { e.preventDefault(); setMenu({ r, at: { x: e.clientX, y: e.clientY } }); }}>
      {columns.map((c) => (
        <div key={c.id} role="cell" className={"rw-c ms-c-" + c.id} style={{ width: c.width }}>
          {c.id === "record" ? <RecordBox r={r} onSaved={saved} /> : <Cell r={r} col={c.id} onOpen={openRow} />}
        </div>
      ))}
      <div className="rw-c ms-c-menu" role="cell" style={{ width: 44 }}>
        <button type="button" className={"ms-more" + (menu?.r.key === r.key ? " open" : "")} aria-haspopup="menu"
                aria-expanded={menu?.r.key === r.key} aria-label={`Actions for ${r.name}`} title="Actions" onClick={(e) => openMenu(e, r)}>
          <MoreIcon />
        </button>
      </div>
      <div className="rw-c rw-fill" aria-hidden="true" />
    </div>
  );

  const empty = (
    <div className="card empty pk-empty">
      <p>Nothing measured {where} yet. Add a measuring point (a pressure, a temperature, run hours), a setting someone changes (a setpoint, output %), or a sensor channel that sends readings{target ? "" : ": pick one of the positions here first"}.</p>
      {target && (
        <p className="ms-empty-add">
          {adds.map((a) => <button key={a.id} type="button" className="secondary" onClick={a.onSelect}>{a.label}</button>)}
        </p>
      )}
      <p className="section-empty-more"><ShowMe help={{ guide: "signal-channels" }}>How measurements work</ShowMe></p>
    </div>
  );

  return (
    <div className="td-tab-page pk-panel rw ms-panel">
      <p className="lib-date pk-purpose">
        Every measuring point, setting and sensor here and below, worst first. Type a value in Record and press Enter to record it now; open a point for its history.
      </p>
      {all && all.length > 0 && (
        <div className="pk-bar">
          <label className="tp-filter pk-filter">
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter: position, point, tag, kind, state"
                   aria-label="Search the measurements" />
          </label>
          <button type="button" aria-pressed={q.attention} onClick={() => q.setAttention(!q.attention)}
                  className={"chip chip-btn ms-filter " + (q.attention ? "chip-accent" : "chip-neutral")}
                  title="Past or near an alarm limit, or a reading due">
            Needs attention ({attention})
          </button>
          {shown && <span className="lib-date pk-count">{shown.length === all.length ? `${all.length} ${all.length === 1 ? "row" : "rows"}` : `${shown.length} of ${all.length} rows`}</span>}
          {colsOpen && (
            <div className="pk-cols">
              <ColumnChooser cols={cols} onCols={setCols} usual={DEFAULT_MEAS_COLUMNS} columns={MEAS_COLUMNS} open={colsOpen}
                             onClose={() => setColsOpen(false)} />
            </div>
          )}
        </div>
      )}
      {said && <p className="lib-date" role="status">{said}</p>}
      {state.error && <div className="card error">Couldn&apos;t load the measurements: {state.error}</div>}
      {state.more && <p className="lib-date">Showing the first {points.length} points: pick a smaller branch to see the rest.</p>}
      {!shown && !state.error ? <div className="card empty">Loading…</div> : shown && all.length === 0 ? empty : shown && (
        <div className="maint-scroll rw-grid pk-grid ms-grid">
          <div className={"pk-table ms-tbl" + (groups ? " ms-grouped" : "")} role="table" aria-label="Measurements here and below" style={{ minWidth: total }}>
            <div className="rw-head" role="row">
              {columns.map((c) => {
                const at = tq.sort.findIndex((k) => k.col === c.id);
                const dir = at >= 0 ? tq.sort[at].dir : 0;
                return (
                  <div key={c.id} role="columnheader" className={"rw-h ms-c-" + c.id} style={{ width: c.width }}
                       aria-sort={dir ? (dir < 0 ? "descending" : "ascending") : "none"} title={c.title ? `${c.label}: ${c.title}` : c.label}>
                    {sortable(c.id) ? (
                      <button type="button" className="rw-hs" onClick={(e) => tq.setSort(nextSort(tq.sort, c.id, e.shiftKey))}
                              aria-label={`${c.label}: sort (Shift-click to add it as a second sort)`}>
                        {c.label}{dir ? <span className="tt-sortarrow" aria-hidden="true">{dir < 0 ? " ▼" : " ▲"}{tq.sort.length > 1 ? at + 1 : ""}</span> : null}
                      </button>
                    ) : <span className="rw-hs ms-hs">{c.label}</span>}
                  </div>
                );
              })}
              <div className="rw-h ms-c-menu" role="columnheader" style={{ width: 44 }}><span className="sr-only">Actions</span></div>
              <div className="rw-h rw-fill" aria-hidden="true" />
            </div>
            {shown.length === 0 ? (
              <p className="lib-date pk-none">
                {query ? <>Nothing matches “{query}”. <button type="button" className="link" onClick={() => setQuery("")}>Clear the search</button></>
                  : <>Nothing needs attention {where}. <button type="button" className="link" onClick={() => q.setAttention(false)}>Show every row</button></>}
              </p>
            ) : groups ? groups.map((g) => (
              <div key={g.key} role="rowgroup" className="ms-group">
                <div role="row" className="ms-grow">
                  <button type="button" className="ms-gbtn" aria-expanded={!folded.has(g.key)} onClick={() => fold(g.key)}
                          title={folded.has(g.key) ? "Show its rows" : "Fold its rows"}>
                    <span className="ms-gcaret" aria-hidden="true">{folded.has(g.key) ? "▸" : "▾"}</span>
                    <span className="ms-gname">{g.place.name || "Unplaced"}</span>
                    <span className="lib-date ms-gcount">{groupText(g)}</span>
                  </button>
                </div>
                {!folded.has(g.key) && g.rows.map(rowEl)}
              </div>
            )) : shown.map(rowEl)}
          </div>
        </div>
      )}
      {menu && (
        <RowMenu items={rowMenu(menu.r)} at={menu.at} label={`Actions for ${menu.r.name}`} anchorId={`ms-${menu.r.key.replace(":", "-")}`}
                 onChoose={(id) => act(id, menu.r)}
                 onClose={() => {
                   const id = `ms-${menu.r.key.replace(":", "-")}`;
                   setMenu(null);
                   document.getElementById(id)?.querySelector(".ms-more")?.focus({ preventScroll: true });
                 }} />
      )}
      {modal?.channel && target && (
        <NewChannel target={target.kind === "item" ? { itemId: target.id } : { positionId: target.id }}
                    onCancel={() => setModal(null)} onDone={done} />
      )}
      {modal?.add && target && <PointModal target={target} kind={modal.add} onClose={() => setModal(null)} onDone={done} />}
      {modal?.read && <PointReadingModal point={modal.read} onClose={() => setModal(null)} onDone={done} />}
      {modal?.limits && <LimitsModal point={modal.limits} onClose={() => setModal(null)} onDone={done} />}
      {modal?.move && (
        <PointMoveModal point={modal.move} onClose={() => setModal(null)}
                        onDone={(r) => {
                          setSaid(`${r.name} moved to ${r.position?.name || "its new position"}.${r.note ? ` ${r.note}` : ""}`);
                          done();
                        }} />
      )}
      {open && open.source === "manual" && (
        <ReadingsModal point={open} onClose={() => { q.setReadings(null); load(); }} />
      )}
    </div>
  );
}
