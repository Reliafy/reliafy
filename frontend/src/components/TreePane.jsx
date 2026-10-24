import { useEffect } from "react";
import OverflowMenu from "./OverflowMenu.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Chevron, Highlight, LevelButtons } from "./OutlineBits.jsx";
import useOutlineNav from "./useOutlineNav.js";
import { ARRANGEMENTS, CHIPS, PANE, clampWidth, markersOf } from "../assetTree.js";

// The asset tree as a second-level menu beside the site menu: the outline
// only (indent, arrow, name, at most three markers), with the filter, Arrange
// by, the levels 1·2·3·4·All and Close everything at the top. Only the rows on
// screen are in the page, so a plant of thousands of positions scrolls and
// opens smoothly; the rows the first one sits inside stay pinned at the top.
// The keyboard follows the tree view pattern: ↑ ↓ Home End Page Up/Down, → ←
// to open, close or move to the child or parent, type to jump, Enter to go
// to the detail. Its edge drags to resize it; « folds it to a thin rail.
//
// Presentational: the page (AssetExplorer) holds the state.

const LEVELS = [1, 2, 3, 4];

const ICON = {
  group: <path d="M2 4h12M2 8h12M2 12h8" strokeWidth="1.6" strokeLinecap="round" />,
  slot: <><rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" /><circle cx="8" cy="8" r="2.3" fill="currentColor" stroke="none" /></>,
  emptyslot: <rect x="2.5" y="2.5" width="11" height="11" rx="2.5" strokeWidth="1.5" strokeDasharray="2 2" />,
  loc: <><path d="M8 14s4.5-4.2 4.5-7.5a4.5 4.5 0 1 0-9 0C3.5 9.8 8 14 8 14z" strokeWidth="1.5" /><circle cx="8" cy="6.5" r="1.6" fill="currentColor" stroke="none" /></>,
  item: <path d="M8 1.8 14 5v6L8 14.2 2 11V5z M2 5l6 3.2L14 5M8 8.2v6" strokeWidth="1.4" strokeLinejoin="round" />,
};

function RowIcon({ r }) {
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

function Row({ v, r, top, height, open, focused, dim, pinned, phone, query, onToggle, onPick, rcm }) {
  const has = r.kids.length > 0;
  const indent = Math.min(v.depth, phone ? 8 : 30) * 14;
  return (
    <div
      className={"tp-row" + (focused ? " focus" : "") + (dim ? " dim" : "") + (pinned ? " pin" : "") + (heading(r) ? " grp" : "")}
      role={pinned ? undefined : "treeitem"}
      aria-hidden={pinned ? "true" : undefined}
      id={pinned ? undefined : `tp-${r.key}`}
      data-key={r.key}
      aria-level={pinned ? undefined : v.depth + 1}
      aria-setsize={pinned ? undefined : v.size}
      aria-posinset={pinned ? undefined : v.pos}
      aria-expanded={pinned || !has ? undefined : open}
      aria-selected={pinned ? undefined : focused}
      tabIndex={pinned ? undefined : focused ? 0 : -1}
      style={pinned ? { height } : { top, height }}
      onClick={(e) => (e.target.closest(".tp-chev") ? onToggle(r.key) : onPick(r.key, { go: true }))}
    >
      <span className="tp-indent" style={{ width: indent }} />
      {has ? (
        <span className={"tp-chev" + (open ? " open" : "")} aria-hidden="true"><Chevron /></span>
      ) : <span className="tp-chev-sp" />}
      <RowIcon r={r} />
      <span className="tp-nm"><Highlight text={r.ref.name || "(no name)"} query={query} /></span>
      {has && !open && <span className="tp-cnt" title={`${r.kids.length} directly inside`}>{r.kids.length.toLocaleString("en-AU")}</span>}
      <Markers r={r} rcm={rcm} />
    </div>
  );
}

export default function TreePane({
  title, treeLabel, display, list, index, open, filter, query, onQuery, chips, onChips, mode, onMode, focus, onPick,
  onToggle, onLevel, onCloseAll, phone, width, onWidth, collapsed, onCollapse, onNew, newLabel, menu,
  notice, statusText, empty, scrollTo, onEnter, rcmMarks = false,
}) {
  const H = phone ? 44 : 30;
  const maxPins = phone ? 2 : 4;
  const { scroller, onScroll, onKey, pins, reveal, drawn } = useOutlineNav({
    display, list, index, open, focus, rowHeight: H, maxPins, onPick, onToggle, onEnter,
    measureKey: `${collapsed}${phone}`, rowId: (key) => `tp-${key}`,
  });

  // Keep a row in view when the page asks (scrollTo changes: a breadcrumb or
  // a "Directly inside" row picked).
  useEffect(() => {
    if (scrollTo?.key) reveal(scrollTo.key, true);
  }, [scrollTo]); // eslint-disable-line react-hooks/exhaustive-deps

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

  if (collapsed && !phone) {
    return (
      <aside className="tp tp-rail" aria-label={title}>
        <button type="button" className="tp-icon-btn" onClick={() => onCollapse(false)}
                aria-label="Show the tree" aria-expanded="false" title="Show the tree (Ctrl+\)">»</button>
      </aside>
    );
  }

  const dim = (key) => filter && !filter.match.has(key);

  return (
    <aside className="tp" aria-label={title} style={phone ? undefined : { width }}>
      <div className="tp-head">
        <div className="tp-title-row">
          <h2 className="tp-title">{title}</h2>
          {onNew && (
            <button type="button" className="tp-icon-btn tp-add" onClick={onNew} aria-label={newLabel} title={newLabel}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            </button>
          )}
          {menu && <OverflowMenu>{menu}</OverflowMenu>}
          {!phone && (
            <button type="button" className="tp-icon-btn" onClick={() => onCollapse(true)}
                    aria-label="Fold the tree away" aria-expanded="true" title="Fold the tree away (Ctrl+\)">«</button>
          )}
        </div>
        <label className="tp-filter">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          <input type="search" value={query} onChange={(e) => onQuery(e.target.value)}
                 placeholder={mode === "items" ? "Filter: name, serial, make, model" : "Filter: name, tag, item, serial"}
                 aria-label="Filter the tree" />
        </label>
        <SegmentedControl size="sm" className="tp-arrange" label="Arrange by" options={ARRANGEMENTS} value={mode} onChange={onMode} />
        {mode !== "flat" && mode !== "items" && (
          <LevelButtons levels={LEVELS} onLevel={onLevel} onCloseAll={onCloseAll} />
        )}
        <div className="tp-chips" role="group" aria-label="Show only">
          {CHIPS.filter((c) => !c.positionsOnly || mode !== "items").map((c) => {
            const on = chips.includes(c.id);
            return (
              <button key={c.id} type="button" className={"tp-chip" + (on ? " on" : "")} aria-pressed={on} title={c.title}
                      onClick={() => onChips(on ? chips.filter((x) => x !== c.id) : [...chips, c.id])}>
                {c.label}
              </button>
            );
          })}
        </div>
        {notice}
        <p className="tp-status" role="status">{statusText}</p>
      </div>
      <div className="tp-scroll" ref={scroller} onScroll={onScroll} onKeyDown={onKey}
           role="tree" aria-label={treeLabel || title} aria-multiselectable="false">
        {pins.length > 0 && (
          <div className="tp-pins">
            <div className="tp-pins-in">
              {pins.map((k) => {
                const v = list[index.get(k)];
                const r = display.rows.get(k);
                return (
                  <Row key={k} v={v} r={r} height={H} open={open.has(k)} focused={k === focus} pinned phone={phone}
                       query={query} onToggle={onToggle} onPick={(key) => { onPick(key, {}); reveal(key, true); }} rcm={rcmMarks} />
                );
              })}
            </div>
          </div>
        )}
        <div className="tp-body" style={{ height: list.length * H }}>
          {drawn.map((i) => {
            const v = list[i];
            const r = display.rows.get(v.key);
            return (
              <Row key={v.key} v={v} r={r} top={i * H} height={H} open={open.has(v.key)} focused={v.key === focus}
                   dim={dim(v.key)} phone={phone} query={query} onToggle={onToggle} onPick={onPick} rcm={rcmMarks} />
            );
          })}
        </div>
        {!list.length && <div className="tp-empty">{empty}</div>}
      </div>
      {!phone && (
        <div className="tp-edge" role="separator" aria-orientation="vertical" aria-label="Resize the tree"
             aria-valuemin={PANE.min} aria-valuemax={Math.round(window.innerWidth * 0.6)} aria-valuenow={width}
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
