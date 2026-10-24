import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { findByPrefix, pinnedRows, windowOf } from "../outlineTree.js";

// The scrolling and the keyboard of an outline (a tree view or a tree grid)
// whose rows are virtualised: only the rows on screen are in the page. Shared
// by the asset tree pane (TreePane) and the RCM worksheet (RcmWorksheet).
//
// The scroller is the element with the rows; `headerHeight` is what sits stuck
// at its top above the rows (a grid's column headers), 0 for none. Rows are
// `rowHeight` tall, drawn at top = index × rowHeight inside the body.
//
// Returns the scroller's ref and onScroll / onKeyDown handlers, the rows to
// draw ([from, to) plus the focused one), the pinned ancestors, and reveal(key,
// middle) to bring a row into view below them. The keyboard follows the tree
// view pattern: ↑ ↓ Home End Page Up/Down, → ← to open, close or move to the
// child or parent, type to jump, Enter for onEnter. `rowId(key)` is a row's
// element id, so the focus can follow the keyboard.
export default function useOutlineNav({
  display, list, index, open, focus, rowHeight: H, maxPins = 4, headerHeight = 0,
  onPick, onToggle, onEnter, nameOf, measureKey, rowId,
}) {
  const scroller = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(600);
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
  }, [measureKey]);

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

  const pins = pinnedRows(display, list, index, scrollTop, H, maxPins);
  const rowsH = Math.max(H, viewH - headerHeight);

  // Keep a row in view below the pinned rows (and the header, if any).
  const reveal = useCallback((key, middle = false) => {
    const el = scroller.current;
    const i = index.get(key);
    if (!el || i == null) return;
    const room = el.clientHeight - headerHeight;
    const pinsH = Math.min(pins.length, maxPins) * H;
    if (middle && (i * H < el.scrollTop + pinsH || (i + 1) * H > el.scrollTop + room)) {
      el.scrollTop = Math.max(0, i * H - room / 3);
    } else if (i * H < el.scrollTop + pinsH) {
      el.scrollTop = Math.max(0, i * H - pinsH - H);
    } else if ((i + 1) * H > el.scrollTop + room) {
      el.scrollTop = (i + 1) * H - room;
    }
    setScrollTop(el.scrollTop);
  }, [index, pins.length, maxPins, H, headerHeight]);

  // After a key press moved the focus, the row (now drawn) takes it.
  useEffect(() => {
    if (!wantFocus.current || focus == null) return;
    wantFocus.current = false;
    document.getElementById(rowId(focus))?.focus({ preventScroll: true });
  });

  const go = (key) => {
    if (key == null) return;
    wantFocus.current = true;
    onPick(key, { keyboard: true });
    reveal(key);
  };

  const onKey = (e) => {
    if (e.target.closest("input, select, textarea, [contenteditable='true']")) return;
    if (!list.length) return;
    const i = focus != null && index.has(focus) ? index.get(focus) : 0;
    const v = list[i];
    const r = display.rows.get(v.key);
    const page = Math.max(1, Math.floor(rowsH / H) - 1);
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
      go(findByPrefix(display, list, (from + list.length) % list.length, typed.current.text, nameOf));
    } else handled = false;
    if (handled) e.preventDefault();
  };

  // The rows drawn: those on screen and a few more; the focused row always,
  // so it keeps the keyboard focus when scrolled away.
  const [from, to] = windowOf(list.length, scrollTop, rowsH, H);
  const drawn = [];
  for (let i = from; i < to; i++) drawn.push(i);
  const fi = focus != null ? index.get(focus) : undefined;
  if (fi != null && (fi < from || fi >= to)) drawn.push(fi);

  return { scroller, scrollTop, onScroll, onKey, pins, reveal, drawn };
}
