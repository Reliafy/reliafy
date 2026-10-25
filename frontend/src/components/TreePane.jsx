import { useEffect, useLayoutEffect, useRef, useState } from "react";
import RowMenu from "./RowMenu.jsx";
import TreeControlsMenu from "./TreeControlsMenu.jsx";
import { Chevron, Highlight, PinIcon } from "./OutlineBits.jsx";
import { Cell, CellEditor, LevelIcon, PhoneStatus, phoneLine } from "./RcmWorksheet.jsx";
import useOutlineNav from "./useOutlineNav.js";
import { ARRANGEMENTS, CHIPS, PANE, clampWidth, markersOf } from "../assetTree.js";
import { cellRow, isRcmRow } from "../explorerRcm.js";
import { LEVEL_OF, NAME_COLUMN } from "../rcmWorksheet.js";

// The asset tree as a second-level menu beside the site menu: the outline
// (indent, arrow, name, at most three markers), with the search box and the
// counts at the top, and everything else about how the tree is shown (Arrange
// by, the levels 1·2·3·4·All, Close everything, the Show only filters) in the
// ⋯ menu beside its title (TreeControlsMenu), the same on both tabs. Only the rows on
// screen are in the page, so a plant of thousands of positions scrolls and
// opens smoothly; the rows the first one sits inside stay pinned at the top.
// The keyboard follows the tree view pattern: ↑ ↓ Home End Page Up/Down, → ←
// to open, close or move to the child or parent, type to jump, Enter to go
// to the detail. Its edge drags to resize it; « folds it to a thin rail.
//
// With `table` (the Explorer's RCM tab) the same tree is the first column of
// one table: its rows go on into each position's functions, functional
// failures and failure modes (nested in the same tree), every row has the
// RCM's columns beside it and the column headers sit at the top. One scroll
// container, one set of rows, one selection; the tree column stays put when
// the table scrolls sideways.
//
// On a wide screen the frame is the same on both tabs, so switching tabs moves
// nothing but what's meant to change: the pane takes the page's width, with
// two slim rows over it (the tree's title, counts and ⋯ beside the panel's
// heading; then the search box beside the panel's tabs), and under them the
// tree, as wide as the tree column, with the table's columns (the RCM tab) or
// the panel's page (`side`, the Summary tab) beside it. The same elements stay
// in the page across the tabs (the search box, the tree's scroll area, the
// heading, the tabs), so the scroll, the focus and what's open stay put.
//
// On a phone each row is two lines on the RCM tab (the name, then the RCM's
// main columns in words). Each row's actions (adding inside it,
// editing, deleting, deciding) are in its menu (`rowMenu`): right-click the
// row, press its ⋯ button (shown on hover and focus; always on a touch screen),
// or Shift+F10 / the Menu key on the focused row.
//
// A branch can be pinned (treePin.js): the tree then starts at that row, and a
// bar under the search box says so, with Show everything to undo it (as does
// "Show whole tree" at the top of the ⋯ menu). `branch`: {name, onUnpin} while
// one is; `branchNote`: a line in the bar's place when the page un-pinned to
// show something outside the branch.
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
};

function RowIcon({ r }) {
  if (isRcmRow(r)) return <LevelIcon type={r.type === "unassigned" ? "fail" : r.type} className="tp-ic" />;
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
const label = (r) => (isRcmRow(r) ? r.ref.text : r.ref.name) || "(no name)";

// What a row's menu is called, for screen readers: "Actions for Function: Pump water".
const menuLabel = (r) => `Actions for ${isRcmRow(r) ? `${LEVEL_OF[r.type]?.label}: ` : ""}${label(r)}`;

// The row's ⋯ button: the same menu as a right-click, for touch and for anyone
// who doesn't know to right-click. Not a tab stop (the row is; Shift+F10 opens
// the menu from it).
function MoreButton({ r, open, onMenu }) {
  return (
    <button type="button" className={"tt-more" + (open ? " open" : "")} tabIndex={-1} aria-haspopup="menu" aria-expanded={open}
            aria-label="Actions" title="Actions (or right-click the row)"
            onDoubleClick={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              const b = e.currentTarget.getBoundingClientRect();
              onMenu(r.key, { x: b.left, y: b.bottom + 2 });
            }}>
      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
        <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
      </svg>
    </button>
  );
}

// What the RCM tab says on the row of the position picked when it has no
// functions yet: how to start (the heading's Add function, or a row's menu).
export const NO_FUNCTIONS = "No functions yet. Press Add function, or right-click a row to add inside it.";
const NO_FUNCTIONS_PHONE = "No functions yet. Tap ⋯ to add one.";

// A position's second line on a phone, on the RCM tab: its own failure modes.
function posLine(r, hint) {
  if (hint) return NO_FUNCTIONS_PHONE;
  const s = r.rsum;
  if (!s?.modes) return r.ref.not_analysed ? "Not analysed yet" : "";
  return `${s.modes.toLocaleString("en-AU")} failure mode${s.modes === 1 ? "" : "s"} · ${s.undecided ? `${s.undecided} to decide` : "all decided"}`;
}

// The tree's own part of a row: indent, arrow, icon, name, markers.
function TreeBit({ r, v, open, phone, query, rcm, table }) {
  const has = r.kids.length > 0;
  const inner = r.kids.length;
  const indent = Math.min(v.depth, phone ? 8 : 30) * 14;
  return (
    <>
      <span className="tp-indent" style={{ width: indent }} />
      {has ? (
        <span className={"tp-chev" + (open ? " open" : "")} aria-hidden="true"><Chevron /></span>
      ) : <span className="tp-chev-sp" />}
      <RowIcon r={r} />
      {isRcmRow(r) && <span className="sr-only">{LEVEL_OF[r.type]?.label}: </span>}
      <span className="tp-nm" title={table && label(r).length > 40 ? label(r) : undefined}>
        <Highlight text={label(r)} query={query} />
      </span>
      {has && !open && inner > 0 && <span className="tp-cnt" title={`${inner} directly inside`}>{inner.toLocaleString("en-AU")}</span>}
      <Markers r={r} rcm={rcm} />
    </>
  );
}

function Row({ v, r, top, height, open, focused, dim, pinned, phone, query, onToggle, onPick, rcm, table, onMenu, menuOpen, rowW }) {
  const has = r.kids.length > 0;
  const cls = "tp-row" + (focused ? " focus" : "") + (dim ? " dim" : "") + (pinned ? " pin" : "") + (heading(r) ? " grp" : "")
    + (table ? ` tt tt-${r.type}` : "") + (menuOpen ? " menu-open" : "");
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
    style: { top: pinned ? undefined : top, height, width: table && !phone ? table.total : rowW },
    onClick: (e) => {
      if (e.target.closest("input, select, a, button.rw-todo-btn, .tt-more")) return;
      if (e.target.closest(".tp-chev")) onToggle(r.key);
      else onPick(r.key, { go: true });
    },
    // Right-click opens the row's menu (the browser's own stays on a field
    // being edited in it, and on a row with no menu).
    onContextMenu: onMenu ? (e) => {
      if (e.target.closest("input, textarea, select, [contenteditable='true']")) return;
      e.preventDefault();
      // From the keyboard (the Menu key, Shift+F10) there's no pointer: under the row's name.
      const kb = e.button !== 2 || (!e.clientX && !e.clientY);
      onMenu(r.key, kb ? cornerOf(e.currentTarget) : { x: e.clientX, y: e.clientY });
    } : undefined,
  };
  const more = onMenu && <MoreButton r={r} open={!!menuOpen} onMenu={onMenu} />;
  if (!table) {
    return <div {...common}><TreeBit r={r} v={v} open={open} phone={phone} query={query} rcm={rcm} />{more}</div>;
  }
  if (phone) {
    const line = r.type === "pos" ? posLine(r, table.hint === r.key) : phoneLine(cellRow(r));
    return (
      <div {...common}>
        <div className="tt-l1">
          <TreeBit r={r} v={v} open={open} phone query={query} rcm={rcm} table />
          {isRcmRow(r) && <span className="tt-st"><PhoneStatus r={cellRow(r)} /></span>}
          {more}
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
          : <><TreeBit r={r} v={v} open={open} query={query} rcm={rcm} table />{more}</>}
      </div>
      {table.hint === r.key && editCol == null ? (
        <div role="gridcell" aria-colspan={table.cols.length} className="rw-c tt-empty-hint"
             style={{ width: table.cols.reduce((t, c) => t + table.widths[c.id], 0) }}>
          {NO_FUNCTIONS}
        </div>
      ) : table.cols.map((c) => {
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

// Where a menu opened from the keyboard goes: under the start of the row's name.
function cornerOf(row) {
  const el = row.querySelector(".tp-nm") || row;
  const b = el.getBoundingClientRect();
  return { x: b.left, y: b.bottom + 2 };
}

export default function TreePane({
  title, treeLabel, display, list, index, open, filter, query, onQuery, chips, onChips, mode, onMode, focus, onPick,
  onToggle, onLevel, onCloseAll, level = null, changed = [], onReset, phone, width, onWidth, collapsed, onCollapse,
  onNew, newLabel, menuActions = [], notice, statusText, empty, scrollTo, onEnter, rcmMarks = false, table = null,
  head = null, headTabs = null, phoneTabs = null, layoutKey = "", anchorKey = null, side = null, arrangeLocked = null,
  rowMenu = null, branch = null, branchNote = null,
}) {
  const H = phone ? (table ? 54 : 44) : 30;
  const wide = !phone;
  const wideTable = !!table && wide;
  // The tree folded to a thin rail (the Summary tab, a wide screen).
  const railed = collapsed && wide && !table;
  const treeW = railed ? PANE.rail : width;
  const maxPins = phone ? 2 : 4;
  const headH = phone ? 0 : HEAD_H;
  const { scroller, onScroll, syncScroll, onKey, pins, reveal, drawn } = useOutlineNav({
    display, list, index, open, focus, rowHeight: H, maxPins, onPick, onToggle, onEnter, headerHeight: headH,
    measureKey: `${railed}${phone}${!!table}${!!side}`, rowId: (key) => `tp-${key}`,
    nameOf: (r) => label(r),
  });

  // A row's menu (rowMenu: {actions(r) → [{id, label}], onAction(r, id)}):
  // {key, at} while it's open. Opening it picks the row; closing puts the
  // focus back on the row.
  const [rowOpen, setRowOpen] = useState(null);
  const itemsFor = (key) => (rowMenu && display.rows.has(key) ? rowMenu.actions(display.rows.get(key)) : []);
  const openMenu = (key, at) => {
    if (!itemsFor(key).length) return;
    if (key !== focus) onPick(key, {});
    setRowOpen({ key, at });
  };
  const closeMenu = () => {
    const key = rowOpen?.key;
    setRowOpen(null);
    if (key != null) document.getElementById(`tp-${key}`)?.focus({ preventScroll: true });
  };
  const keys = (e) => {
    if (rowMenu && focus != null && itemsFor(focus).length && (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))
        && !e.target.closest("input, select, textarea, [contenteditable='true']")) {
      e.preventDefault();
      const row = document.getElementById(`tp-${focus}`);
      if (row) openMenu(focus, cornerOf(row));
      return;
    }
    onKey(e);
  };

  // Keep a row in view when the page asks (scrollTo changes: a breadcrumb or
  // a "Directly inside" row picked).
  useEffect(() => {
    if (scrollTo?.key) reveal(scrollTo.key, true);
  }, [scrollTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Switching tab adds or removes the RCM rows: the selected position stays
  // where it was on screen. At the top (or the end) of the tree there may be
  // no room to keep it there; then the place it had is kept until the tree is
  // scrolled or another row picked, so switching back puts everything back
  // exactly where it was.
  const anchor = useRef({ key: null, offset: 0, layout: layoutKey, held: null });
  useLayoutEffect(() => {
    const el = scroller.current;
    const a = anchor.current;
    if (el && a.layout !== layoutKey && a.key != null && index.has(a.key)) {
      const want = index.get(a.key) * H - a.offset;
      el.scrollTop = Math.max(0, want);
      a.held = Math.abs(el.scrollTop - want) >= 1 ? { key: a.key, top: el.scrollTop } : null;
      syncScroll();
    }
    a.layout = layoutKey;
  });
  const record = () => {
    const el = scroller.current;
    const a = anchor.current;
    if (!el || anchorKey == null || !index.has(anchorKey)) return;
    if (a.held && a.held.key === anchorKey && Math.abs(el.scrollTop - a.held.top) < 1) return;
    anchor.current = { ...a, key: anchorKey, offset: index.get(anchorKey) * H - el.scrollTop, held: null };
  };
  useEffect(record);

  // The Summary tab's tree is exactly as wide as the RCM tab's tree column:
  // its scroll area adds the scrollbar's width (none where scrollbars float
  // over the content), with the gutter always kept, so the rows never narrow
  // when the scrollbar comes and goes.
  const [gutter, setGutter] = useState(0);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !wide || table) return;
    const cs = getComputedStyle(el);
    const g = Math.max(0, el.offsetWidth - el.clientWidth - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth));
    if (g !== gutter) setGutter(g);
  });

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

  const unfold = (
    <button type="button" className="tp-icon-btn" onClick={() => onCollapse(false)}
            aria-label="Show the tree" aria-expanded="false" title="Show the tree (Ctrl+\)">»</button>
  );
  const dim = (key) => filter && !filter.match.has(key);
  const levelsOn = mode !== "flat" && mode !== "items";
  const chipList = CHIPS.filter((c) => (!c.positionsOnly || mode !== "items") && (!c.rcmOnly || table));
  const status = <p className="tp-status" role="status" title={statusText || undefined}>{statusText}</p>;
  const titleRow = (
    <div className="tp-title-row">
      {wide ? <div className="tt-title"><h2 className="tp-title">{title}</h2>{status}</div> : <h2 className="tp-title">{title}</h2>}
      {onNew && (
        <button type="button" className="tp-icon-btn tp-add" onClick={onNew} aria-label={newLabel} title={newLabel}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      )}
      <TreeControlsMenu
        pinned={branch ? { name: branch.name, onUnpin: branch.onUnpin } : null}
        arrange={arrangeLocked ? null : { value: mode, options: ARRANGEMENTS, onChange: onMode }}
        note={arrangeLocked}
        levels={levelsOn ? { value: level, onLevel, onCloseAll } : null}
        chips={chipList.map((c) => ({ ...c, on: chips.includes(c.id) }))}
        onChip={(id) => onChips(chips.includes(id) ? chips.filter((x) => x !== id) : [...chips, id])}
        changed={changed} onReset={onReset} actions={menuActions} />
      {/* Folding is for the Summary tab; on the RCM tab its place is kept, so
          the + and ⋯ beside it don't move when the tab changes. */}
      {wide && (
        <button type="button" className={"tp-icon-btn tp-fold" + (table ? " is-off" : "")} onClick={() => onCollapse(true)}
                disabled={!!table} tabIndex={table ? -1 : undefined} aria-hidden={table ? "true" : undefined}
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
  // The pinned branch's bar (or, just after un-pinning to show something
  // outside it, a line saying so).
  const branchBar = branch ? (
    <div className="tp-branch" role="group" aria-label="Pinned branch">
      <PinIcon />
      <span className="tp-branch-text" title={branch.name}>Showing only: <strong>{branch.name}</strong></span>
      <button type="button" className="secondary tp-branch-x" onClick={branch.onUnpin} title="Show the whole tree again">
        <span aria-hidden="true">✕</span> Show everything
      </button>
    </div>
  ) : branchNote ? <p className="tp-branch-note" role="status">{branchNote}</p> : null;
  // The two slim rows over the tree (a wide screen, both tabs): the tree's
  // title, counts and ⋯ over the tree column, beside the panel's heading (the
  // way up over the row's name, and its actions); then the search box over the
  // tree column, beside the panel's tabs. On a phone the title, the tabs, the
  // search box and the counts stack over the tree.
  const controls = wide ? (
    <div className="tt-top">
      <div className="tt-bar">
        <div className={"tt-cell" + (railed ? " tt-rail" : "")} style={{ width: treeW }}>{railed ? unfold : titleRow}</div>
        <div className="tt-headslot">{head}</div>
      </div>
      <div className="tt-row2">
        <div className="tt-cell" style={{ width: treeW }}>{railed ? null : search}</div>
        <div className="tt-tabslot">{headTabs}</div>
        {notice}
      </div>
      {branchBar && !railed && <div className="tt-row3"><div className="tt-cell" style={{ width }}>{branchBar}</div></div>}
    </div>
  ) : (
    <div className="tp-head">
      {titleRow}
      {phoneTabs}
      {search}
      {branchBar}
      {notice}
      {status}
    </div>
  );

  // A row on the Summary tab (a wide screen) is as wide as the RCM tab's tree cell.
  const rowProps = { phone, query, onToggle, rcm: rcmMarks, table, rowW: wide && !table ? width : undefined };
  const menuProps = (key) => (itemsFor(key).length ? { onMenu: openMenu, menuOpen: rowOpen?.key === key } : {});
  const columnHeads = !phone && (
    <div className="tt-head" role={wideTable ? "row" : undefined} aria-hidden={wideTable ? undefined : "true"}
         style={{ width: wideTable ? table.total : width, height: HEAD_H }}>
      <div className="tt-h tt-h-tree" role={wideTable ? "columnheader" : undefined} style={{ width: wideTable ? table.treeW : width }}>
        {wideTable ? "Position › function, failure or mode" : treeLabel || title}
      </div>
      {wideTable && table.cols.map((c) => (
        <div key={c.id} role="columnheader" className={"tt-h" + (c.align === "num" ? " num" : "")} style={{ width: table.widths[c.id] }}
             title={c.title}>{c.label}</div>
      ))}
      {wideTable && <div className="tt-h rw-fill" aria-hidden="true">{table.headTools}</div>}
    </div>
  );

  return (
    <aside className={"tp" + (table ? " tp-table" : "") + (railed ? " tp-railed" : "")} aria-label={title}>
      {controls}
      <div className="tt-main">
        {railed ? <div className="tp-railcol" style={{ width: PANE.rail }} /> : (
        <div className="tp-scroll" ref={scroller} onScroll={() => { onScroll(); record(); }} onKeyDown={keys}
             role={table ? "treegrid" : "tree"} aria-label={table ? `${treeLabel || title} and their RCM` : treeLabel || title}
             aria-multiselectable="false" style={wide && !table ? { width: width + gutter } : undefined}>
          {columnHeads}
          {pins.length > 0 && (
            <div className="tp-pins" style={{ top: headH }}>
              <div className="tp-pins-in">
                {pins.map((k) => {
                  const v = list[index.get(k)];
                  const r = display.rows.get(k);
                  return (
                    <Row key={k} v={v} r={r} height={H} open={open.has(k)} focused={k === focus} pinned {...rowProps} {...menuProps(k)}
                         onPick={(key) => { onPick(key, {}); reveal(key, true); }} />
                  );
                })}
              </div>
            </div>
          )}
          <div className="tp-body" style={{ height: list.length * H, width: wideTable ? table.total : wide ? width : undefined }}>
            {drawn.map((i) => {
              const v = list[i];
              const r = display.rows.get(v.key);
              return (
                <Row key={v.key} v={v} r={r} top={i * H} height={H} open={open.has(v.key)} focused={v.key === focus}
                     dim={dim(v.key)} onPick={onPick} {...rowProps} {...menuProps(v.key)} />
              );
            })}
          </div>
          {!list.length && <div className="tp-empty" style={wide && !table ? { width } : undefined}>{empty}</div>}
        </div>
        )}
        {side}
      </div>
      {rowOpen && itemsFor(rowOpen.key).length > 0 && (
        <RowMenu items={itemsFor(rowOpen.key)} at={rowOpen.at} label={menuLabel(display.rows.get(rowOpen.key))} anchorId={`tp-${rowOpen.key}`} onClose={closeMenu}
                 onChoose={(id) => rowMenu.onAction(display.rows.get(rowOpen.key), id)} />
      )}
      {wide && !railed && (
        <div className="tp-edge" role="separator" aria-orientation="vertical" aria-label={table ? "Resize the tree column" : "Resize the tree"}
             aria-valuemin={PANE.min} aria-valuemax={Math.round(window.innerWidth * 0.6)} aria-valuenow={width}
             style={{ left: width - 4, right: "auto" }}
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
