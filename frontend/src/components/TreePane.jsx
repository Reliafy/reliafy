import { useEffect, useLayoutEffect, useRef } from "react";
import OverflowMenu from "./OverflowMenu.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Chevron, Highlight, LevelButtons } from "./OutlineBits.jsx";
import { Cell, CellEditor, LevelIcon, PhoneStatus, phoneLine } from "./RcmWorksheet.jsx";
import useOutlineNav from "./useOutlineNav.js";
import { ARRANGEMENTS, CHIPS, PANE, clampWidth, markersOf } from "../assetTree.js";
import { cellRow, isRcmRow } from "../explorerRcm.js";
import { LEVEL_OF, NAME_COLUMN } from "../rcmWorksheet.js";

// The asset tree as a second-level menu beside the site menu: the outline
// (indent, arrow, name, at most three markers), with the filter, Arrange by,
// the levels 1·2·3·4·All and Close everything at the top. Only the rows on
// screen are in the page, so a plant of thousands of positions scrolls and
// opens smoothly; the rows the first one sits inside stay pinned at the top.
// The keyboard follows the tree view pattern: ↑ ↓ Home End Page Up/Down, → ←
// to open, close or move to the child or parent, type to jump, Enter to go
// to the detail. Its edge drags to resize it; « folds it to a thin rail.
//
// With `table` (the Explorer's RCM tab) the same tree is the first column of
// one table: its rows go on into each position's functions, functional
// failures and failure modes (nested in the same tree), every row has the
// RCM's columns beside it, the column headers sit at the top, and the pane
// takes the page's width, with two slim rows over it (the panel's heading,
// then the filters). One scroll container, one set of rows, one selection;
// the tree column stays put when the table scrolls sideways. On a phone each row is two lines (the name,
// then the RCM's main columns in words).
//
// Presentational: the page (AssetExplorer) holds the state.

const LEVELS = [1, 2, 3, 4];
const HEAD_H = 30;

const ICON = {
  group: <path d="M2 4h12M2 8h12M2 12h8" strokeWidth="1.6" strokeLinecap="round" />,
  slot: <><rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" /><circle cx="8" cy="8" r="2.3" fill="currentColor" stroke="none" /></>,
  emptyslot: <rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" strokeDasharray="2 2" />,
  loc: <><path d="M8 14s4.5-4.2 4.5-7.5a4.5 4.5 0 1 0-9 0C3.5 9.8 8 14 8 14z" strokeWidth="1.5" /><circle cx="8" cy="6.5" r="1.6" fill="currentColor" stroke="none" /></>,
  item: <path d="M8 1.8 14 5v6L8 14.2 2 11V5z M2 5l6 3.2L14 5M8 8.2v6" strokeWidth="1.4" strokeLinejoin="round" />,
  add: <path d="M8 3v10M3 8h10" strokeWidth="1.8" strokeLinecap="round" />,
};

function RowIcon({ r }) {
  if (isRcmRow(r) && r.type !== "add") return <LevelIcon type={r.type === "unassigned" ? "fail" : r.type} className="tp-ic" />;
  let kind = r.type;
  // A position is a position: the icon only says whether an item is fitted.
  // The lines icon is for the pane's own headings ("No home yet" and so on).
  if (r.type === "pos") kind = r.ref.item ? "slot" : "emptyslot";
  return (
    <svg className="tp-ic" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">
      {ICON[kind] || ICON.group}
    </svg>
  );
}

function Markers({ r, rcm }) {
  const list = markersOf(r, { rcm });
  if (!list.length) return null;
  return (
    <span className="tp-mk">
      {list.map((m) => (
        <span key={m.kind} className={`tp-mini ${m.kind}${m.inside ? " inside" : ""}`} title={m.label}>
          <span aria-hidden="true">{m.text}</span>
          <span className="sr-only">{m.label}</span>
        </span>
      ))}
    </span>
  );
}

// Bold: the pane's own headings, the places, and an item with positions on it.
const heading = (r) => r.type === "group" || r.type === "loc" || (r.type === "item" && r.kids.length > 0);
const label = (r) => (r.type === "add" || isRcmRow(r) ? r.ref.text : r.ref.name) || "(no name)";

// A position's second line on a phone, on the RCM tab: its own failure modes.
function posLine(r) {
  const s = r.rsum;
  if (!s?.modes) return r.ref.not_analysed ? "Not analysed yet" : "";
  return `${s.modes.toLocaleString("en-AU")} failure mode${s.modes === 1 ? "" : "s"} · ${s.undecided ? `${s.undecided} to decide` : "all decided"}`;
}

// The tree's own part of a row: indent, arrow, icon, name, markers.
function TreeBit({ r, v, open, phone, query, rcm, table }) {
  const has = r.kids.length > 0;
  // What's inside, less the "Add …" rows.
  const inner = r.kids.filter((k) => !k.startsWith("+")).length;
  const indent = Math.min(v.depth, phone ? 8 : 30) * 14;
  const add = r.type === "add";
  return (
    <>
      <span className="tp-indent" style={{ width: indent }} />
      {has ? (
        <span className={"tp-chev" + (open ? " open" : "")} aria-hidden="true"><Chevron /></span>
      ) : <span className="tp-chev-sp" />}
      <RowIcon r={r} />
      {isRcmRow(r) && !add && <span className="sr-only">{LEVEL_OF[r.type]?.label}: </span>}
      <span className={"tp-nm" + (add ? " tt-add" : "")} title={table && label(r).length > 40 ? label(r) : undefined}>
        <Highlight text={label(r)} query={query} />
      </span>
      {has && !open && inner > 0 && <span className="tp-cnt" title={`${inner} directly inside`}>{inner.toLocaleString("en-AU")}</span>}
      <Markers r={r} rcm={rcm} />
    </>
  );
}

function Row({ v, r, top, height, open, focused, dim, pinned, phone, query, onToggle, onPick, rcm, table }) {
  const has = r.kids.length > 0;
  const cls = "tp-row" + (focused ? " focus" : "") + (dim ? " dim" : "") + (pinned ? " pin" : "") + (heading(r) ? " grp" : "")
    + (table ? ` tt tt-${r.type}` : "");
  const common = {
    className: cls,
    role: pinned ? undefined : table ? "row" : "treeitem",
    "aria-hidden": pinned ? "true" : undefined,
    id: pinned ? undefined : `tp-${r.key}`,
    "data-key": r.key,
    "aria-level": pinned ? undefined : v.depth + 1,
    "aria-setsize": pinned ? undefined : v.size,
    "aria-posinset": pinned ? undefined : v.pos,
    "aria-expanded": pinned || !has ? undefined : open,
    "aria-selected": pinned ? undefined : focused,
    tabIndex: pinned ? undefined : focused ? 0 : -1,
    style: pinned ? { height, width: table && !phone ? table.total : undefined } : { top, height, width: table && !phone ? table.total : undefined },
    onClick: (e) => {
      if (e.target.closest("input, select, a, button.rw-todo-btn")) return;
      if (e.target.closest(".tp-chev")) onToggle(r.key);
      else onPick(r.key, { go: true });
    },
  };
  if (!table) {
    return <div {...common}><TreeBit r={r} v={v} open={open} phone={phone} query={query} rcm={rcm} /></div>;
  }
  if (phone) {
    const line = r.type === "add" ? "" : r.type === "pos" ? posLine(r) : phoneLine(cellRow(r));
    return (
      <div {...common}>
        <div className="tt-l1">
          <TreeBit r={r} v={v} open={open} phone query={query} rcm={rcm} table />
          {isRcmRow(r) && r.type !== "add" && <span className="tt-st"><PhoneStatus r={cellRow(r)} /></span>}
        </div>
        {line && <div className="tt-l2" style={{ paddingLeft: Math.min(v.depth, 8) * 14 + 40 }}>{line}</div>}
      </div>
    );
  }
  const editCol = table.editing?.key === r.key ? table.editing.col : null;
  const cr = cellRow(r);
  return (
    <div {...common}>
      <div className="tt-tree" role="rowheader" style={{ width: table.treeW }}
           onDoubleClick={table.canEditName(r) ? (e) => { e.stopPropagation(); table.onEdit(r.key, "name"); } : undefined}>
        {editCol === "name"
          ? <CellEditor col={NAME_COLUMN} r={cr} onCommit={(raw) => table.onCommit(r, "name", raw)} onCancel={table.onCancel} />
          : <TreeBit r={r} v={v} open={open} query={query} rcm={rcm} table />}
      </div>
      {r.type !== "add" && table.cols.map((c) => {
        const rcmRow = isRcmRow(r);
        const can = rcmRow && !table.readOnly && c.edit && c.can(cr);
        return (
          <div key={c.id} role="gridcell" className={"rw-c" + (c.align === "num" ? " num" : "") + (can ? " can" : "")}
               style={{ width: table.widths[c.id] }}
               onDoubleClick={can ? (e) => { e.stopPropagation(); table.onEdit(r.key, c.id); } : undefined}
               title={can && editCol !== c.id ? "Double-click to edit" : undefined}>
            {editCol === c.id
              ? <CellEditor col={c} r={cr} onCommit={(raw) => table.onCommit(r, c.id, raw)} onCancel={table.onCancel} />
              : (rcmRow || cr.sum.modes) ? <Cell col={c} r={r.type === "pos" ? { ...cr, type: "fn" } : cr} query={query} readOnly={table.readOnly}
                                               onDecision={table.onDecision} linkChecks /> : null}
          </div>
        );
      })}
      <div className="rw-c rw-fill" aria-hidden="true" />
    </div>
  );
}

export default function TreePane({
  title, treeLabel, display, list, index, open, filter, query, onQuery, chips, onChips, mode, onMode, focus, onPick,
  onToggle, onLevel, onCloseAll, phone, width, onWidth, collapsed, onCollapse, onNew, newLabel, menu,
  notice, statusText, empty, scrollTo, onEnter, rcmMarks = false, table = null, head = null, phoneTabs = null,
  layoutKey = "", anchorKey = null, side = null, arrangeLocked = null,
}) {
  const H = phone ? (table ? 54 : 44) : 30;
  const maxPins = phone ? 2 : 4;
  const headH = phone ? 0 : HEAD_H;
  const { scroller, onScroll, onKey, pins, reveal, drawn } = useOutlineNav({
    display, list, index, open, focus, rowHeight: H, maxPins, onPick, onToggle, onEnter, headerHeight: headH,
    measureKey: `${collapsed}${phone}${!!table}${!!side}`, rowId: (key) => `tp-${key}`,
    nameOf: (r) => label(r),
  });

  // Keep a row in view when the page asks (scrollTo changes: a breadcrumb or
  // a "Directly inside" row picked).
  useEffect(() => {
    if (scrollTo?.key) reveal(scrollTo.key, true);
  }, [scrollTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Switching tab adds or removes the RCM rows: the selected position stays
  // where it was on screen.
  const anchor = useRef({ key: null, offset: 0, layout: layoutKey });
  useLayoutEffect(() => {
    const el = scroller.current;
    const a = anchor.current;
    if (el && a.layout !== layoutKey && a.key != null && index.has(a.key)) {
      el.scrollTop = Math.max(0, index.get(a.key) * H - a.offset);
      onScroll();
    }
    a.layout = layoutKey;
  });
  const record = () => {
    const el = scroller.current;
    if (el && anchorKey != null && index.has(anchorKey)) {
      anchor.current = { ...anchor.current, key: anchorKey, offset: index.get(anchorKey) * H - el.scrollTop };
    }
  };
  useEffect(record);

  // Drag the edge to resize; ← → when it has focus; double-click resets.
  const startResize = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    const move = (ev) => onWidth(clampWidth(startW + ev.clientX - startX, window.innerWidth));
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };

  if (collapsed && !phone && !table) {
    return (
      <aside className="tp tp-rail" aria-label={title}>
        <button type="button" className="tp-icon-btn" onClick={() => onCollapse(false)}
                aria-label="Show the tree" aria-expanded="false" title="Show the tree (Ctrl+\)">»</button>
      </aside>
    );
  }

  const dim = (key) => filter && !filter.match.has(key);
  const wide = table && !phone;
  const status = <p className="tp-status" role="status" title={statusText || undefined}>{statusText}</p>;
  const titleRow = (
    <div className="tp-title-row">
      {wide ? <div className="tt-title"><h2 className="tp-title">{title}</h2>{status}</div> : <h2 className="tp-title">{title}</h2>}
      {onNew && (
        <button type="button" className="tp-icon-btn tp-add" onClick={onNew} aria-label={newLabel} title={newLabel}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      )}
      {menu && <OverflowMenu>{menu}</OverflowMenu>}
      {!phone && !table && (
        <button type="button" className="tp-icon-btn" onClick={() => onCollapse(true)}
                aria-label="Fold the tree away" aria-expanded="true" title="Fold the tree away (Ctrl+\)">«</button>
      )}
    </div>
  );
  const search = (
    <label className="tp-filter">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      <input type="search" value={query} onChange={(e) => onQuery(e.target.value)}
             placeholder={table ? "Filter: names, failures, effects, tasks" : mode === "items" ? "Filter: name, serial, make, model" : "Filter: name, tag, item, serial"}
             aria-label={table ? "Filter the tree and its RCM" : "Filter the tree"} />
    </label>
  );
  const levels = mode !== "flat" && mode !== "items" && (
    <LevelButtons levels={LEVELS} onLevel={onLevel} onCloseAll={onCloseAll} />
  );
  const chipRow = (
    <div className="tp-chips" role="group" aria-label="Show only">
      {CHIPS.filter((c) => (!c.positionsOnly || mode !== "items") && (!c.rcmOnly || table)).map((c) => {
        const on = chips.includes(c.id);
        return (
          <button key={c.id} type="button" className={"tp-chip" + (on ? " on" : "") + (c.rcmOnly ? " rcm" : "")} aria-pressed={on} title={c.title}
                  onClick={() => onChips(on ? chips.filter((x) => x !== c.id) : [...chips, c.id])}>
            {c.label}
          </button>
        );
      })}
    </div>
  );
  // The RCM tab on a wide screen: two slim rows over the table instead of
  // the stacked controls, so the table gets the height. The first: the
  // tree's title and its counts over the tree column, then the panel's
  // heading (the tabs, the position and its actions). The second: the filter
  // over the tree column, then the levels and the chips. Arrange by isn't
  // offered here: the RCM is by position (the counts say so).
  const controls = wide ? (
    <div className="tt-top">
      <div className="tt-bar">
        <div className="tt-cell" style={{ width }}>{titleRow}</div>
        <div className="tt-headslot">{head}</div>
      </div>
      <div className="tt-filters">
        <div className="tt-cell" style={{ width }}>{search}</div>
        {levels}
        {chipRow}
        {notice}
      </div>
    </div>
  ) : (
    <div className="tp-head">
      {titleRow}
      {phoneTabs}
      {search}
      <SegmentedControl size="sm" className="tp-arrange" label="Arrange by" value={mode} onChange={onMode}
                        options={arrangeLocked ? ARRANGEMENTS.map((a) => (a.value === "positions" ? a : { ...a, disabled: true, title: arrangeLocked })) : ARRANGEMENTS} />
      {levels}
      {chipRow}
      {notice}
      {status}
    </div>
  );

  const rowProps = { phone, query, onToggle, rcm: rcmMarks, table };
  const columnHeads = !phone && (
    <div className="tt-head" role={wide ? "row" : undefined} aria-hidden={wide ? undefined : "true"}
         style={{ width: wide ? table.total : undefined, height: HEAD_H }}>
      <div className="tt-h tt-h-tree" role={wide ? "columnheader" : undefined} style={{ width: wide ? table.treeW : "100%" }}>
        {wide ? "Position › function, failure or mode" : treeLabel || title}
      </div>
      {wide && table.cols.map((c) => (
        <div key={c.id} role="columnheader" className={"tt-h" + (c.align === "num" ? " num" : "")} style={{ width: table.widths[c.id] }}
             title={c.title}>{c.label}</div>
      ))}
      {wide && <div className="tt-h rw-fill" aria-hidden="true">{table.headTools}</div>}
    </div>
  );

  return (
    <aside className={"tp" + (table ? " tp-table" : "")} aria-label={title} style={phone || wide ? undefined : { width }}>
      {controls}
      <div className="tt-main">
        <div className="tp-scroll" ref={scroller} onScroll={() => { onScroll(); record(); }} onKeyDown={onKey}
             role={table ? "treegrid" : "tree"} aria-label={table ? `${treeLabel || title} and their RCM` : treeLabel || title}
             aria-multiselectable="false">
          {columnHeads}
          {pins.length > 0 && (
            <div className="tp-pins" style={{ top: headH }}>
              <div className="tp-pins-in">
                {pins.map((k) => {
                  const v = list[index.get(k)];
                  const r = display.rows.get(k);
                  return (
                    <Row key={k} v={v} r={r} height={H} open={open.has(k)} focused={k === focus} pinned {...rowProps}
                         onPick={(key) => { onPick(key, {}); reveal(key, true); }} />
                  );
                })}
              </div>
            </div>
          )}
          <div className="tp-body" style={{ height: list.length * H, width: wide ? table.total : undefined }}>
            {drawn.map((i) => {
              const v = list[i];
              const r = display.rows.get(v.key);
              return (
                <Row key={v.key} v={v} r={r} top={i * H} height={H} open={open.has(v.key)} focused={v.key === focus}
                     dim={dim(v.key)} onPick={onPick} {...rowProps} />
              );
            })}
          </div>
          {!list.length && <div className="tp-empty">{empty}</div>}
        </div>
        {side}
      </div>
      {!phone && (
        <div className="tp-edge" role="separator" aria-orientation="vertical" aria-label={table ? "Resize the tree column" : "Resize the tree"}
             aria-valuemin={PANE.min} aria-valuemax={Math.round(window.innerWidth * 0.6)} aria-valuenow={width}
             style={wide ? { left: width - 4, right: "auto" } : undefined}
             tabIndex={0} onPointerDown={startResize} onDoubleClick={() => onWidth(PANE.initial)}
             onKeyDown={(e) => {
               if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                 e.preventDefault();
                 onWidth(clampWidth(width + (e.key === "ArrowLeft" ? -16 : 16), window.innerWidth));
               }
             }} />
      )}
    </aside>
  );
}
