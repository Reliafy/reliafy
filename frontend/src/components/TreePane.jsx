import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import OverflowMenu from "./OverflowMenu.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import {
  ARRANGEMENTS, CHIPS, PANE, clampWidth, findByPrefix, markersOf, pinnedRows, windowOf,
} from "../assetTree.js";

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

const Chevron = () => (
  <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
    <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" />
  </svg>
);

// The name with the filter's text marked.
function Highlight({ text, query }) {
  const q = query.trim();
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

function Markers({ r }) {
  const list = markersOf(r);
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

function Row({ v, r, top, height, open, focused, dim, pinned, phone, query, onToggle, onPick }) {
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
      <Markers r={r} />
    </div>
  );
}

export default function TreePane({
  title, treeLabel, display, list, index, open, filter, query, onQuery, chips, onChips, mode, onMode, focus, onPick,
  onToggle, onLevel, onCloseAll, phone, width, onWidth, collapsed, onCollapse, onNew, newLabel, menu,
  notice, statusText, empty, scrollTo, onEnter,
}) {
  const scroller = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(600);
  const H = phone ? 44 : 30;
  const typed = useRef({ text: "", at: 0 });
  const wantFocus = useRef(false);

  // The scroller's height, as the window and the pane change.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return undefined;
    const measure = () => setViewH(el.clientHeight || 600);
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [collapsed, phone]);

  // One state update a frame, however fast the scroll events come.
  const frame = useRef(0);
  const onScroll = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      if (scroller.current) setScrollTop(scroller.current.scrollTop);
    });
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const pins = pinnedRows(display, list, index, scrollTop, H, phone ? 2 : 4);

  // Keep a row in view below the pinned rows: on a key press, or when the page
  // asks (scrollTo changes: a breadcrumb or a "Directly inside" row picked).
  const reveal = useCallback((key, middle = false) => {
    const el = scroller.current;
    const i = index.get(key);
    if (!el || i == null) return;
    const pinsH = Math.min(pins.length, phone ? 2 : 4) * H;
    if (middle && (i * H < el.scrollTop + pinsH || (i + 1) * H > el.scrollTop + el.clientHeight)) {
      el.scrollTop = Math.max(0, i * H - el.clientHeight / 3);
    } else if (i * H < el.scrollTop + pinsH) {
      el.scrollTop = Math.max(0, i * H - pinsH - H);
    } else if ((i + 1) * H > el.scrollTop + el.clientHeight) {
      el.scrollTop = (i + 1) * H - el.clientHeight;
    }
    setScrollTop(el.scrollTop);
  }, [index, pins.length, phone, H]);

  useEffect(() => {
    if (scrollTo?.key) reveal(scrollTo.key, true);
  }, [scrollTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a key press moved the focus, the row (now drawn) takes it.
  useEffect(() => {
    if (!wantFocus.current || !focus) return;
    wantFocus.current = false;
    document.getElementById(`tp-${focus}`)?.focus({ preventScroll: true });
  });

  const go = (key) => {
    if (key == null) return;
    wantFocus.current = true;
    onPick(key, { keyboard: true });
    reveal(key);
  };

  const onKey = (e) => {
    if (e.target.closest("input, select, textarea")) return;
    if (!list.length) return;
    const i = focus != null && index.has(focus) ? index.get(focus) : 0;
    const v = list[i];
    const r = display.rows.get(v.key);
    const page = Math.max(1, Math.floor((scroller.current?.clientHeight || 600) / H) - 1);
    const key = e.key;
    let handled = true;
    if (key === "ArrowDown") go(list[Math.min(list.length - 1, i + 1)].key);
    else if (key === "ArrowUp") go(list[Math.max(0, i - 1)].key);
    else if (key === "Home") go(list[0].key);
    else if (key === "End") go(list[list.length - 1].key);
    else if (key === "PageDown") go(list[Math.min(list.length - 1, i + page)].key);
    else if (key === "PageUp") go(list[Math.max(0, i - page)].key);
    else if (key === "ArrowRight") {
      if (r.kids.length && !open.has(v.key)) onToggle(v.key, true);
      else if (r.kids.length && list[i + 1]) go(list[i + 1].key);
    } else if (key === "ArrowLeft") {
      if (r.kids.length && open.has(v.key)) onToggle(v.key, false);
      else if (r.parent != null && index.has(r.parent)) go(r.parent);
    } else if (key === "Enter") {
      onEnter?.(v.key);
    } else if (key.length === 1 && /\S/.test(key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const now = Date.now();
      typed.current = { text: now - typed.current.at < 700 ? typed.current.text + key : key, at: now };
      const from = typed.current.text.length > 1 ? i - 1 : i;
      go(findByPrefix(display, list, (from + list.length) % list.length, typed.current.text));
    } else handled = false;
    if (handled) e.preventDefault();
  };

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

  const [from, to] = windowOf(list.length, scrollTop, viewH, H);
  const drawn = [];
  for (let i = from; i < to; i++) drawn.push(i);
  // The focused row is always drawn, so it keeps the keyboard focus when scrolled away.
  const fi = focus != null ? index.get(focus) : undefined;
  if (fi != null && (fi < from || fi >= to)) drawn.push(fi);
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
          <div className="tp-levels" role="group" aria-label="Open the tree to a level">
            <span className="tp-levels-label" aria-hidden="true">Levels</span>
            <div className="seg seg-sm">
              {LEVELS.map((n) => (
                <button key={n} type="button" className="seg-btn" onClick={() => onLevel(n)}
                        aria-label={`Open to level ${n}`} title={`Open to level ${n}`}>{n}</button>
              ))}
              <button type="button" className="seg-btn" onClick={() => onLevel(Infinity)} aria-label="Open everything" title="Open everything">All</button>
            </div>
            <button type="button" className="tp-icon-btn" onClick={onCloseAll} aria-label="Close everything" title="Close everything">
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.4" fill="none" /><path d="M5.5 8h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
          </div>
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
                       query={query} onToggle={onToggle} onPick={(key) => { onPick(key, {}); reveal(key, true); }} />
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
                   dim={dim(v.key)} phone={phone} query={query} onToggle={onToggle} onPick={onPick} />
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
