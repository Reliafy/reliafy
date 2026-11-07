import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import RowMenu from "./RowMenu.jsx";
import TreeControlsMenu from "./TreeControlsMenu.jsx";
import { Chevron, Highlight, PinIcon } from "./OutlineBits.jsx";
import { BasisInfo, Cell, CellEditor, LevelIcon, PhoneStatus, cellHint, cellTip, phoneLine } from "./RcmWorksheet.jsx";
import useOutlineNav from "./useOutlineNav.js";
import { ARRANGEMENTS, CHIPS, CHIP_MARK, PANE, clampWidth, markersOf, nextGutter, statusParts } from "../assetTree.js";
import { TASK_WITH_INTERVAL, cellRow, fitWidths, isRcmRow, opensItem } from "../explorerRcm.js";
import { isFullScreenKey } from "../fullScreen.js";
import { LEVEL_OF, NAME_COLUMN } from "../rcmWorksheet.js";
import { isDeleteKey } from "../treeDelete.js";

// The asset tree as a second-level menu beside the site menu: the outline
// (indent, arrow, name, at most three markers). Over it, two lines: the title
// and counts with the Positions / Locations switch (ArrangeSwitch) and « on
// the right; then the search box with the ⋯ menu beside it (TreeControlsMenu:
// the levels 1·2·3·4·All, Close everything, the Show only filters), the same
// on every tab. Adding is in the tree itself: a row's menu has New … inside,
// and a quiet last row (`addRow`) adds at the top level. Only the rows on
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
// two slim rows over it (the tree's title, counts, switch and « beside the
// panel's heading; then the search box and ⋯ beside the panel's tabs), and under them the
// tree, as wide as the tree column, with the table's columns (the RCM tab) or
// the panel's page (`side`, the Summary tab) beside it. The same elements stay
// in the page across the tabs (the search box, the tree's scroll area, the
// heading, the tabs), so the scroll, the focus and what's open stay put.
//
// On a phone each row is two lines on the RCM tab (the name, then the RCM's
// main columns in words). Each row's actions (adding inside it,
// editing, deleting, deciding) are in its menu (`rowMenu`): right-click the
// row, press its ⋯ button (shown on hover and focus; always on a touch screen),
// or Shift+F10 / the Menu key on the focused row. `rowMenu.actions(r, {keyboard})`
// is told how the menu was opened: from the keyboard (Shift+F10, the Menu key)
// or with a pointer (right-click, the ⋯ button), so the page can offer the
// moves a drag does only where there's no dragging.
//
// A branch can be pinned (treePin.js): the tree then starts at that row. It
// says so without a row of its own: on a wide screen the tree's column header
// reads "Pinned: <name>" with a ✕ (Show everything) beside it; on a phone (no
// column header) the pinned row itself has the pin before its name and the ✕
// at its end. "Show whole tree" at the top of the ⋯ menu un-pins too.
// `branch`: {key, name, path, onUnpin} while one is; `branchNote`: a few words
// in the same place (the column header; the counts on a phone) when the page
// un-pinned to show something outside the branch.
//
// Presentational: the page (AssetExplorer) holds the state.

const LEVELS = [1, 2, 3, 4];
const HEAD_H = 30;
// The tree column's header on the RCM tab: what its rows are.
// The table's vertical scrollbar (styled 12 px wide in AssetExplorer.css).
const SCROLLBAR_W = 12;
export const TREE_HEAD = "Function, performance standard, failure or mode";
// The soft shadow on a side of the table with more to scroll to: its width,
// and how far from the end it fades in.
const SHADE_W = 16;
const SHADE_FADE = 24;

// The table (the RCM tab, a wide screen) fitted to its pane: its columns
// narrowed (never below their least) so it scrolls sideways only when it
// must, and with the Interval column not shown, the interval in the Task cell.
// `room`: the scroll area's width inside its scrollbar (null: not measured yet).
function fitTable(table, room) {
  if (!table) return table;
  const fold = table.foldInterval && table.cols.some((c) => c.id === "task");
  const cols = fold ? table.cols.map((c) => (c.id === "task" ? TASK_WITH_INTERVAL : c)) : table.cols;
  // The Task cell with the interval in it takes the Interval column's room too.
  const base = fold ? { ...table.widths, task: table.widths.task + (table.intervalW || 0) } : table.widths;
  const widths = room == null ? base : fitWidths(cols.map((c) => c.id), base, room - table.treeW);
  return { ...table, cols, widths, total: table.treeW + cols.reduce((t, c) => t + widths[c.id], 0) };
}

const ICON = {
  group: <path d="M2 4h12M2 8h12M2 12h8" strokeWidth="1.6" strokeLinecap="round" />,
  slot: <><rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" /><circle cx="8" cy="8" r="2.3" fill="currentColor" stroke="none" /></>,
  emptyslot: <rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" strokeDasharray="2 2" />,
  loc: <><path d="M8 14s4.5-4.2 4.5-7.5a4.5 4.5 0 1 0-9 0C3.5 9.8 8 14 8 14z" strokeWidth="1.5" /><circle cx="8" cy="6.5" r="1.6" fill="currentColor" stroke="none" /></>,
  item: <path d="M8 1.8 14 5v6L8 14.2 2 11V5z M2 5l6 3.2L14 5M8 8.2v6" strokeWidth="1.4" strokeLinejoin="round" />,
};

export function RowIcon({ r }) {
  // The "Not under a functional failure" and "No standard" headings take the
  // icon of what's under them.
  if (isRcmRow(r)) return <LevelIcon type={r.type === "unassigned" || r.type === "nofail" ? "fail" : r.type === "nostd" ? "std" : r.type} className="tp-ic" />;
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

function Markers({ r, rcm, onGoto }) {
  const list = markersOf(r, { rcm });
  if (!list.length) return null;
  return (
    <span className="tp-mk">
      {list.map((m) => (
        // The ↑ n marker (a failure that causes ones above): a click goes up to
        // the first of them. Not a tab stop, as no marker is (the panel lists them).
        <span key={m.kind} className={`tp-mini ${m.kind}${m.inside ? " inside" : ""}${m.effect && onGoto ? " go" : ""}`} title={m.label}
              onClick={m.effect && onGoto ? (e) => { e.stopPropagation(); onGoto(m.effect); } : undefined}>
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
              // A click from the keyboard (Enter on it, a screen reader) has no pointer: detail 0.
              onMenu(r.key, { x: b.left, y: b.bottom + 2 }, { keyboard: e.detail === 0 });
            }}>
      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
        <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
      </svg>
    </button>
  );
}

// Positions or Locations: a two-way switch in the pane's heading (a radio
// group: Tab reaches the one on, ← → move and choose, the way radios do). With
// `locked` (the RCM and FME(C)A tabs are by position) it stays on show, greyed,
// and says why, so the heading looks the same on every tab.
export function ArrangeSwitch({ value, options, onChange, locked = null }) {
  const group = useRef(null);
  const choose = (v) => {
    if (locked || v === value) return;
    onChange(v);
  };
  const onKeyDown = (e) => {
    const i = options.findIndex((o) => o.value === value);
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step || locked) return;
    e.preventDefault();
    const next = options[(i + step + options.length) % options.length];
    choose(next.value);
    // The switch stays in the page as the address changes: the focus follows the choice.
    setTimeout(() => group.current?.querySelector(`[data-value="${next.value}"]`)?.focus(), 0);
  };
  return (
    <div ref={group} className={"tp-arrange" + (locked ? " is-off" : "")} role="radiogroup" aria-label="Arrange by"
         aria-disabled={locked ? "true" : undefined} title={locked || undefined} onKeyDown={onKeyDown}>
      {options.map((o) => {
        const on = o.value === value;
        // Its label, or (a narrow tree pane: AssetExplorer.css) its icon, with the label in its name and tooltip.
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} data-value={o.value}
                  tabIndex={on ? 0 : -1} className={"tp-arrange-btn" + (on ? " on" : "")}
                  aria-disabled={locked && !on ? "true" : undefined} aria-label={o.label}
                  title={locked ? `${o.label}. ${locked}` : `${o.label}: ${o.title}`} onClick={() => choose(o.value)}>
            <ArrangeIcon value={o.value} />
            <span className="tp-arrange-lbl">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// The switch's icons, shown in place of the labels where the tree pane is
// narrow: a tree of boxes (what each position does, inside what) and a map pin
// (where things are).
function ArrangeIcon({ value }) {
  return (
    <svg className="tp-arrange-ico" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {value === "locations" ? (
        <><path d="M8 14.5s4.5-4.2 4.5-7.8a4.5 4.5 0 0 0-9 0c0 3.6 4.5 7.8 4.5 7.8Z" /><circle cx="8" cy="6.6" r="1.6" /></>
      ) : (
        <><rect x="5.5" y="1.5" width="5" height="3.5" rx="0.8" /><rect x="1.5" y="11" width="5" height="3.5" rx="0.8" />
          <rect x="9.5" y="11" width="5" height="3.5" rx="0.8" /><path d="M8 5v3M4 11V8h8v3" /></>
      )}
    </svg>
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
  const state = s.undecided ? `${s.undecided} to decide` : r.ref.not_analysed ? "not analysed yet" : "all decided";
  return `${s.modes.toLocaleString("en-AU")} failure mode${s.modes === 1 ? "" : "s"} · ${state}`;
}

// A reference row's tooltip: what it is and what a click does.
const causeTip = (r) => (r.ref.inside === false
  ? `${r.ref.text} (on ${r.ref.on}) isn't inside ${r.ref.effect_position || "this position"} any more, so it no longer counts. Click to go there; Unlink takes it off.`
  : `Caused by: ${r.ref.text} (on ${r.ref.on}). Click to go there.`);

// The tree's own part of a row: indent, arrow, icon, name, markers.
function TreeBit({ r, v, open, phone, query, rcm, table, pinRoot, onGoto, info = null }) {
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
      {pinRoot && <span className="tp-pinmark" title={`Pinned: ${pinRoot.path}`}><PinIcon size={13} /><span className="sr-only">Pinned: </span></span>}
      {isRcmRow(r) && <span className="sr-only">{LEVEL_OF[r.type]?.label}: </span>}
      <span className="tp-nm" title={r.type === "cause" ? causeTip(r) : label(r).length > 24 ? label(r) : undefined}>
        <Highlight text={label(r)} query={query} />
      </span>
      {r.type === "cause" && <span className="tp-on" title={causeTip(r)}>on {r.ref.on}</span>}
      {has && !open && inner > 0 && <span className="tp-cnt" title={`${inner} directly inside`}>{inner.toLocaleString("en-AU")}</span>}
      {info}
      <Markers r={r} rcm={rcm} onGoto={onGoto} />
    </>
  );
}

// The ✕ on the pinned row (a phone): the whole tree again. Always shown, a
// 36 px target; not a tab stop (the ⋯ menu's Show whole tree is, from the keyboard).
function UnpinButton({ pinRoot }) {
  return (
    <button type="button" className="tp-unpin" tabIndex={-1} aria-label="Show everything" title="Show everything"
            onDoubleClick={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); pinRoot.onUnpin(); }}>
      <span aria-hidden="true">✕</span>
    </button>
  );
}

// The RCM table's drag and drop (a wide screen): the mark on the row under
// the pointer (into: an outline; before / after: a line at its top or
// bottom; no: a red outline), drawn inside the row so nothing moves.
function dropClass(drag, key) {
  const o = drag?.over;
  if (!o || o.key !== key) return "";
  return o.state === "no" ? " drop-no" : ` drop-${o.zone || "into"}`;
}

function Row({ v, r, top, height, open, focused, dim, pinned, phone, query, onToggle, onPick, rcm, table, onMenu, menuOpen, rowW, pinRoot }) {
  const has = r.kids.length > 0;
  const drag = table && !phone ? table.drag : null;
  const movable = !!drag && !pinned && drag.canDrag(r);
  const cls = "tp-row" + (focused ? " focus" : "") + (dim ? " dim" : "") + (pinned ? " pin" : "") + (heading(r) ? " grp" : "")
    + (table ? ` tt tt-${r.type}` : "") + (menuOpen ? " menu-open" : "") + (drag?.picked?.has(r.key) ? " picked" : "")
    + (movable ? " movable" : "") + dropClass(drag, r.key) + (drag?.dragging?.has(r.key) ? " dragged" : "");
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
    "aria-selected": pinned ? undefined : focused || (drag?.picked?.has(r.key) ? true : undefined),
    tabIndex: pinned ? undefined : focused ? 0 : -1,
    style: { top: pinned ? undefined : top, height, width: table && !phone ? table.total : rowW },
    onClick: (e) => {
      if (e.target.closest("input, select, a, button.rw-todo-btn, .tt-more, .tp-unpin, .rw-info")) return;
      // Failure modes picked with Shift / Ctrl / Cmd-click, to drag (or move) together.
      if (drag && r.type === "mode" && (e.shiftKey || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        drag.onPickMany(r.key, e);
        return;
      }
      if (drag?.picked?.size) drag.onPickMany(null, e);
      // In the table a double-click on the chevron opens or closes the row
      // once (its second click isn't another toggle).
      if (e.target.closest(".tp-chev")) {
        if (!(table && e.detail > 1)) onToggle(r.key);
      } else onPick(r.key, { go: true });
    },
    // The RCM table (a wide screen): a double-click on the name of a function,
    // performance standard, functional failure or failure mode opens its
    // details across the table; not on a data cell (an editable one's own
    // double-click edits it in place), a control or the chevron.
    onDoubleClick: table && !phone && table.onOpen && opensItem(r) ? (e) => {
      if (e.target.closest("input, select, textarea, a, button, .tp-chev, .rw-c, [contenteditable='true']")) return;
      e.preventDefault();
      window.getSelection?.()?.removeAllRanges?.();
      table.onOpen(r.key);
    } : undefined,
    // Right-click opens the row's menu (the browser's own stays on a field
    // being edited in it, and on a row with no menu).
    onContextMenu: onMenu ? (e) => {
      if (e.target.closest("input, textarea, select, [contenteditable='true']")) return;
      e.preventDefault();
      // From the keyboard (the Menu key, Shift+F10) there's no pointer: under the row's name.
      const kb = e.button !== 2 || (!e.clientX && !e.clientY);
      onMenu(r.key, kb ? cornerOf(e.currentTarget) : { x: e.clientX, y: e.clientY }, { keyboard: kb });
    } : undefined,
  };
  const more = onMenu && <MoreButton r={r} open={!!menuOpen} onMenu={onMenu} />;
  const unpin = pinRoot && <UnpinButton pinRoot={pinRoot} />;
  if (!table) {
    return <div {...common}><TreeBit r={r} v={v} open={open} phone={phone} query={query} rcm={rcm} pinRoot={pinRoot} />{unpin}{more}</div>;
  }
  if (phone) {
    // The second line: the page's own words for the tab (the FME(C)A's
    // scores), else the RCM's main columns, or a position's own modes.
    const line = table.phoneLine ? (r.type === "pos" && table.hint === r.key ? NO_FUNCTIONS_PHONE : table.phoneLine(cellRow(r)))
      : r.type === "pos" ? posLine(r, table.hint === r.key) : phoneLine(cellRow(r));
    return (
      <div {...common}>
        <div className="tt-l1">
          <TreeBit r={r} v={v} open={open} phone query={query} rcm={rcm} table pinRoot={pinRoot} onGoto={table.onGoto} />
          {(isRcmRow(r) || (table.fmea && r.type === "pos")) && <span className="tt-st"><PhoneStatus r={cellRow(r)} fmea={!!table.fmea} /></span>}
          {unpin}{more}
        </div>
        {line && <div className="tt-l2" style={{ paddingLeft: Math.min(v.depth, 8) * 14 + 40 }}>{line}</div>}
      </div>
    );
  }
  const editCol = table.editing?.key === r.key ? table.editing.col : null;
  const cr = cellRow(r);
  // A parent row's roll-up (the FME(C)A's "3 of 5 scored"): in the first of the
  // leading text columns, running on over the blank ones beside it.
  const rollup = table.rollup && r.type !== "mode" ? table.rollup.text(cr) : "";
  let rollRun = 0;
  if (rollup) {
    for (const c of table.cols) {
      if (!table.rollup.ids.has(c.id)) break;
      rollRun += 1;
    }
  }
  const rollW = rollRun ? table.cols.slice(0, rollRun).reduce((t, c) => t + table.widths[c.id], 0) : 0;
  return (
    <div {...common}>
      <div className="tt-tree" role="rowheader" style={{ width: table.treeW }}
           title={drag && !movable ? drag.block(r) || undefined : undefined}
           onPointerDown={movable && editCol !== "name" ? (e) => drag.begin(e, r.key) : undefined}
           onDoubleClick={!table.onOpen && table.canEditName(r) ? (e) => { e.stopPropagation(); table.onEdit(r.key, "name"); } : undefined}>
        {movable && editCol !== "name" && <span className="tt-grip" aria-hidden="true" style={{ left: Math.max(0, Math.min(v.depth, 30) * 14 - 13) }}><GripIcon /></span>}
        {editCol === "name"
          ? <CellEditor col={NAME_COLUMN} r={cr} onCommit={(raw) => table.onCommit(r, "name", raw)} onCancel={table.onCancel} />
          : <><TreeBit r={r} v={v} open={open} query={query} rcm={rcm} table onGoto={table.onGoto}
                       info={<BasisInfo r={r} onBasis={table.onBasis} />} />{more}</>}
      </div>
      {table.hint === r.key && editCol == null ? (
        <div role="gridcell" aria-colspan={table.cols.length} className="rw-c tt-empty-hint"
             style={{ width: table.cols.reduce((t, c) => t + table.widths[c.id], 0) }}>
          {NO_FUNCTIONS}
        </div>
      ) : table.cols.map((c, ci) => {
        const rcmRow = isRcmRow(r);
        if (rollRun && ci < rollRun) {
          return (
            <div key={c.id} role="gridcell" className={"rw-c" + (ci === 0 ? " tt-rollup-c" : "")} style={{ width: table.widths[c.id] }}>
              {ci === 0 && <span className="rw-sum tt-rollup-t" style={{ width: rollW - 16 }} title={rollup}>{rollup}</span>}
            </div>
          );
        }
        const can = rcmRow && !table.readOnly && c.edit && c.can(cr);
        // A failure mode's Task cell drags its (first) task to another failure mode or a position.
        const task = drag && !pinned && c.id === "task" && r.type === "mode" && editCol !== c.id ? drag.taskOf(r) : null;
        return (
          <div key={c.id} role="gridcell" className={"rw-c" + (c.align === "num" ? " num" : "") + (can ? " can" : "") + (task ? " tt-task-drag" : "")}
               style={{ width: table.widths[c.id] }}
               onPointerDown={task ? (e) => drag.begin(e, r.key, task) : undefined}
               onDoubleClick={can ? (e) => { e.stopPropagation(); table.onEdit(r.key, c.id); } : undefined}
               title={editCol !== c.id ? cellTip(c, cr, can) : undefined} aria-description={editCol !== c.id ? cellHint(can) : undefined}>
            {editCol === c.id
              ? <CellEditor col={c} r={cr} onCommit={(raw) => table.onCommit(r, c.id, raw)} onCancel={table.onCancel} />
              : (rcmRow || cr.sum.modes) ? <Cell col={c} r={r.type === "pos" ? { ...cr, type: "fn" } : cr} query={query} readOnly={table.readOnly}
                                               onDecision={table.onDecision} linkChecks
                                               onWorking={table.onBasis ? (id) => table.onBasis({ type: "fn", key: id }) : null} /> : null}
          </div>
        );
      })}
      <div className="rw-c rw-fill" aria-hidden="true" />
    </div>
  );
}

function GripIcon() {
  return (
    <svg viewBox="0 0 10 16" width="8" height="13" fill="currentColor">
      <circle cx="3" cy="3" r="1.3" /><circle cx="7" cy="3" r="1.3" /><circle cx="3" cy="8" r="1.3" />
      <circle cx="7" cy="8" r="1.3" /><circle cx="3" cy="13" r="1.3" /><circle cx="7" cy="13" r="1.3" />
    </svg>
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
  addRow = null, canArrange = true, menuActions = [], notice, statusText, empty, scrollTo, onEnter, rcmMarks = false, table: tableIn = null,
  head = null, headTabs = null, phoneTabs = null, layoutKey = "", anchorKey = null, side = null, arrangeLocked = null,
  rowMenu = null, branch = null, branchNote = null, fullScreenKey = false, statusTitle,
}) {
  const H = phone ? (tableIn ? 54 : 44) : 30;
  const wide = !phone;
  const wideTable = !!tableIn && wide;
  // The details panel filling the table's room (table.expanded, a wide
  // screen): only the tree column shows, beside it, so the place is kept and
  // another row can be picked; the panel follows it.
  const expanded = wideTable && !!tableIn.expanded;
  // The scroll area's width inside its scrollbar (the RCM tab, a wide screen),
  // measured before each paint, so the columns fit it from the first frame.
  const [room, setRoom] = useState(null);
  const table = wideTable ? fitTable(tableIn, room) : tableIn;
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

  // A row's menu (rowMenu: {actions(r, {keyboard}) → [{id, label}], onAction(r, id)}):
  // {key, at, keyboard} while it's open. Opening it picks the row; closing
  // puts the focus back on the row. Whether a row has a menu at all (its ⋯
  // button) is asked as the keyboard would see it (the most it can offer).
  const [rowOpen, setRowOpen] = useState(null);
  const itemsFor = (key, { keyboard = true } = {}) => (rowMenu && display.rows.has(key) ? rowMenu.actions(display.rows.get(key), { keyboard }) : []);
  const openMenu = (key, at, { keyboard = false } = {}) => {
    if (!itemsFor(key, { keyboard }).length) return;
    if (key !== focus) onPick(key, {});
    setRowOpen({ key, at, keyboard });
  };
  const closeMenu = () => {
    const key = rowOpen?.key;
    setRowOpen(null);
    if (key != null) document.getElementById(`tp-${key}`)?.focus({ preventScroll: true });
  };
  const keys = (e) => {
    if (e.target.closest(".tt-head button, .tp-addrow")) return;
    // F is the page's full screen (its own key handler), not a jump to a row.
    if (fullScreenKey && isFullScreenKey(e)) return;
    if (rowMenu && focus != null && itemsFor(focus).length && (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))
        && !e.target.closest("input, select, textarea, [contenteditable='true']")) {
      e.preventDefault();
      const row = document.getElementById(`tp-${focus}`);
      if (row) openMenu(focus, cornerOf(row), { keyboard: true });
      return;
    }
    // A reference row (a failure below that causes the one above): Enter or
    // Space goes to the real row, Delete unlinks it.
    const fr = focus != null ? display.rows.get(focus) : null;
    if (fr?.type === "cause" && rowMenu && !e.ctrlKey && !e.metaKey && !e.altKey && !e.target.closest("input, select, textarea, button, a, [contenteditable='true']")) {
      const act = e.key === "Enter" || e.key === " " ? "go" : e.key === "Delete" ? "unlink" : null;
      if (act) {
        e.preventDefault();
        rowMenu.onAction(fr, act);
        return;
      }
    }
    // Delete or Backspace on a row its menu can delete: the Delete… dialog (not while typing).
    if (fr && rowMenu && isDeleteKey(e) && !e.target.closest("button, a")) {
      const del = itemsFor(focus).find((a) => a.id === "tree-delete");
      if (del && !del.disabled) {
        e.preventDefault();
        rowMenu.onAction(fr, "tree-delete");
        return;
      }
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
    // Only ever wider (nextGutter): a measure that flips with the width it sets
    // (a browser rounding the bar's width, a bar that comes and goes) would
    // otherwise update the state on every render, without end.
    const next = nextGutter(gutter, g);
    if (next !== gutter) setGutter(next);
  });

  // The table's width to fit (before each paint, and as the window or the
  // panel beside it changes), and the soft shadows on the sides with more to
  // scroll to: on the left at the tree column's edge (the columns slide under
  // it), on the right at the scroll area's edge; each fades in over the last
  // few pixels before its end, and neither shows when everything fits. They
  // sit over the scroll area (not in it), so overlay scrollbars and the sticky
  // tree column don't matter.
  const shadeL = useRef(null);
  const shadeR = useRef(null);
  const treeColW = table?.treeW ?? 0;
  // The table's own width: the scroll area's scrollWidth can count a few
  // pixels more than can be scrolled to (the scrollbar's gutter).
  const tableW = useRef(0);
  tableW.current = wideTable ? table.total : 0;
  const paintShade = useCallback(() => {
    const el = scroller.current;
    const l = shadeL.current;
    const r = shadeR.current;
    if (!el || !l || !r) return;
    const max = Math.min(el.scrollWidth, tableW.current || el.scrollWidth) - el.clientWidth;
    const x = el.scrollLeft;
    const place = (s, left, on) => {
      s.style.top = `${el.offsetTop + el.clientTop}px`;
      s.style.height = `${el.clientHeight}px`;
      s.style.left = `${left}px`;
      s.style.opacity = String(on);
    };
    place(l, el.offsetLeft + treeColW, max > 1 ? Math.min(1, x / SHADE_FADE) : 0);
    place(r, el.offsetLeft + el.clientWidth - SHADE_W, max > 1 ? Math.min(1, (max - x) / SHADE_FADE) : 0);
    l.dataset.on = x > 0.5 && max > 1 ? "true" : "false";
    r.dataset.on = max - x > 0.5 && max > 1 ? "true" : "false";
  }, [treeColW]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !wideTable) return;
    if (el.clientWidth !== room) setRoom(el.clientWidth);
    paintShade();
  });
  useEffect(() => {
    const el = scroller.current;
    if (!el || !wideTable || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => {
      setRoom(el.clientWidth);
      paintShade();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [wideTable, paintShade]); // eslint-disable-line react-hooks/exhaustive-deps

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
  // A tab's own chips (the RCM's, the FME(C)A's) show on that tab only.
  const chipList = CHIPS.filter((c) => !c.rcmOnly || (table && (!c.tab || c.tab === (table.tab || "rcm"))));
  const status = (
    <p className="tp-status" role="status" title={statusTitle || statusText || undefined}>
      {/* The counts' parts ("4 positions", "3 not analysed") each kept whole: where
          the pane is too narrow for one line they wrap between the parts, never cut
          short. Each part keeps its dot; the line can break only at the space after it. */}
      {statusParts(statusText).map((part, i, all) => (
        <Fragment key={i}><span className="tp-status-part">{part}{i < all.length - 1 ? " ·" : ""}</span>{i < all.length - 1 ? " " : ""}</Fragment>
      ))}
    </p>
  );
  const titleRow = (
    <div className="tp-title-row">
      {wide ? <div className="tt-title"><h2 className="tp-title">{title}</h2>{status}</div> : <h2 className="tp-title">{title}</h2>}
      {canArrange && <ArrangeSwitch value={mode} options={ARRANGEMENTS} onChange={onMode} locked={arrangeLocked} />}
      {/* Folding is for the Summary tab; on the RCM and FME(C)A tabs the tree
          is the table's first column, so the button stays, greyed, and says
          why: the pane's header looks the same on every tab. */}
      {wide && (
        <button type="button" className={"tp-icon-btn tp-fold" + (table ? " is-off" : "")} onClick={() => onCollapse(true)}
                disabled={!!table} aria-label="Fold the tree away" aria-expanded="true"
                title={table ? `The tree is the first column of the ${table.what || "RCM"} table here, so it stays open` : "Fold the tree away (Ctrl+\\)"}>«</button>
      )}
    </div>
  );
  // The search line: the filter box, then the ⋯ menu (the levels and the
  // Show only filters; its badge counts what isn't as usual).
  const search = (
    <div className="tp-search-row">
      <label className="tp-filter">
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        <input type="search" value={query} onChange={(e) => onQuery(e.target.value)}
               placeholder={table ? "Filter: name, tag, failures, tasks" : "Filter: name, tag, item, serial"}
               aria-label={table ? "Filter the tree and its RCM" : "Filter the tree"} />
      </label>
      <TreeControlsMenu
        pinned={branch ? { name: branch.name, onUnpin: branch.onUnpin } : null}
        levels={{ value: level, onLevel, onCloseAll }}
        // Each Show only filter with the marker it matches in the tree: the
        // markers' key (the "not analysed" one only where it shows).
        chips={chipList.map((c) => ({ ...c, on: chips.includes(c.id), mark: c.id !== "unanalysed" || rcmMarks ? CHIP_MARK[c.id] : null }))}
        markNote="A row's markers count what's on it; dashed ones count everything inside it too."
        onChip={(id) => onChips(chips.includes(id) ? chips.filter((x) => x !== id) : [...chips, id])}
        changed={changed} onReset={onReset} actions={menuActions} />
    </div>
  );
  // While a branch is pinned, the tree's column header says so (a wide screen,
  // both tabs): the pin, "Pinned: <name>" (cut short, the whole path in its
  // tooltip) and a ✕ to show everything. Just after un-pinning to show
  // something outside the branch, a few words in its place.
  const pinHead = branch ? (
    <span className="tt-pinned" role="group" aria-label="Pinned branch">
      <PinIcon size={13} />
      <span className="tt-pinned-nm" title={`Pinned: ${branch.path || branch.name}`}>Pinned: <strong>{branch.name}</strong></span>
      <button type="button" className="tt-pinned-x" onClick={branch.onUnpin} aria-label="Show everything" title="Show everything">
        <span aria-hidden="true">✕</span>
      </button>
    </span>
  ) : branchNote ? <span className="tt-pinned-note" role="status">{branchNote}</span> : null;
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
    </div>
  ) : (
    <div className="tp-head">
      {titleRow}
      {phoneTabs}
      {search}
      {notice}
      {branchNote && !branch ? <p className="tp-status" role="status">{branchNote}</p> : status}
    </div>
  );

  // A row on the Summary tab (a wide screen) is as wide as the RCM tab's tree cell.
  const rowProps = { phone, query, onToggle, rcm: rcmMarks, table, rowW: wide && !table ? width : undefined };
  // The pinned row on a phone: the pin before its name and the ✕ at its end.
  const pinRootOf = (key) => (phone && branch && key === branch.key ? branch : undefined);
  const menuProps = (key) => (itemsFor(key).length ? { onMenu: openMenu, menuOpen: rowOpen?.key === key } : {});
  const columnHeads = !phone && (
    <div className="tt-head" role={wideTable ? "row" : undefined} aria-hidden={wideTable || pinHead ? undefined : "true"}
         style={{ width: wideTable ? table.total : width, height: HEAD_H }}>
      <div className="tt-h tt-h-tree" role={wideTable ? "columnheader" : undefined} style={{ width: wideTable ? table.treeW : width }}
           aria-label={wideTable && pinHead ? table.treeHead || TREE_HEAD : undefined}>
        {pinHead || (wideTable ? table.treeHead || TREE_HEAD : treeLabel || title)}
      </div>
      {wideTable && table.cols.map((c) => {
        // With `onSort` (the FME(C)A tab) a header with something to sort by
        // is a button: highest first, then lowest, then the worksheet's own order.
        const sortable = !!table.onSort && !!c.sort;
        const sorted = sortable && table.sort?.col === c.id ? table.sort.dir : 0;
        return (
          <div key={c.id} role="columnheader" className={"tt-h" + (c.align === "num" ? " num" : "") + (sorted ? " is-sorted" : "")} style={{ width: table.widths[c.id] }}
               aria-sort={sorted ? (sorted === -1 ? "descending" : "ascending") : sortable ? "none" : undefined}
               title={c.title ? `${c.label}: ${c.title}` : c.label}>
            {sortable ? (
              <button type="button" className="tt-sortbtn" onClick={() => table.onSort(c.id)}
                      aria-label={`${c.label}: sort${sorted === -1 ? " lowest first" : sorted === 1 ? ": back to the worksheet's order" : " highest first"}`}>
                {c.label}{sorted ? <span className="tt-sortarrow" aria-hidden="true">{sorted === -1 ? "▼" : "▲"}</span> : null}
              </button>
            ) : c.label}
          </div>
        );
      })}
      {wideTable && <div className="tt-h rw-fill" aria-hidden="true">{table.headTools}</div>}
    </div>
  );

  return (
    <aside className={"tp" + (table ? " tp-table" : "") + (railed ? " tp-railed" : "")} aria-label={title}>
      {controls}
      <div className={"tt-main" + (expanded ? " tt-expanded" : "")}>
        {railed ? <div className="tp-railcol" style={{ width: PANE.rail }} /> : (
        <div className="tp-scroll" ref={scroller} onScroll={() => { onScroll(); record(); if (wideTable) paintShade(); }} onKeyDown={keys}
             role={table ? "treegrid" : "tree"} aria-label={table ? `${treeLabel || title} and their ${table.what || "RCM"}` : treeLabel || title}
             aria-multiselectable={table?.drag?.picked?.size ? "true" : "false"}
             style={wide && !table ? { width: width + gutter } : expanded ? { width: table.treeW + SCROLLBAR_W } : undefined}>
          {columnHeads}
          {pins.length > 0 && (
            <div className="tp-pins" style={{ top: headH }}>
              <div className="tp-pins-in">
                {pins.map((k) => {
                  const v = list[index.get(k)];
                  const r = display.rows.get(k);
                  return (
                    <Row key={k} v={v} r={r} height={H} open={open.has(k)} focused={k === focus} pinned {...rowProps} {...menuProps(k)} pinRoot={pinRootOf(k)}
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
                     dim={dim(v.key)} onPick={onPick} {...rowProps} {...menuProps(v.key)} pinRoot={pinRootOf(v.key)} />
              );
            })}
          </div>
          {/* Adding at the top level: a quiet last row of the tree (a row's
              own menu adds inside it). Not while filtering: what's added
              might not match. */}
          {addRow && !filter && list.length > 0 && (
            <div className="tp-addrow-line" style={{ height: H, width: wideTable ? table.treeW : wide ? width : undefined }}>
              <button type="button" className="tp-addrow" onClick={addRow.onAdd} disabled={!!addRow.disabled}
                      title={addRow.disabled ? addRow.reason : undefined}>
                <span className="tp-addrow-plus" aria-hidden="true">+</span>
                <span className="tp-addrow-nm">{addRow.label}</span>
              </button>
            </div>
          )}
          {!list.length && <div className="tp-empty" style={wide && !table ? { width } : undefined}>{empty}</div>}
        </div>
        )}
        {wideTable && (
          <>
            <div className="tt-shade tt-shade-l" ref={shadeL} aria-hidden="true" />
            <div className="tt-shade tt-shade-r" ref={shadeR} aria-hidden="true" />
          </>
        )}
        {side}
      </div>
      {rowOpen && itemsFor(rowOpen.key, rowOpen).length > 0 && (
        <RowMenu items={itemsFor(rowOpen.key, rowOpen)} at={rowOpen.at} label={menuLabel(display.rows.get(rowOpen.key))} anchorId={`tp-${rowOpen.key}`} onClose={closeMenu}
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
