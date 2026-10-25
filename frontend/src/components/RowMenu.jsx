import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { placeMenu } from "../menuPlace.js";
import useMenuDismiss from "./useMenuDismiss.js";

// A row's own menu (a context menu): opened by right-click, a row's ⋯ button,
// or Shift+F10 / the Menu key. Drawn in the shared portal host (so it shows in
// full screen too) at `at` ({x, y}: the pointer, or the corner of what opened
// it), moved in to stay on screen near the edges. The menu pattern: the first
// item takes the focus, ↑ ↓ Home End move, Enter or Space chooses, Esc or Tab
// closes. It closes like every menu (useMenuDismiss), on a resize, and on a
// scroll that moves its row (the element `anchorId` names) away from it.
// `onClose` puts the focus back where it belongs (the row).
//
// items: [{id, label, danger?, disabled?, reason?}]; onChoose(id) runs after
// the menu has closed. A disabled item stays in the menu (so it can be found
// and its reason read: under its label, and to a screen reader as its
// description) but does nothing.
// Styled as the app's other menus (.ovm-menu / .ovm-item).

export default function RowMenu({ items, at, label, anchorId, onChoose, onClose }) {
  const ref = useRef(null);
  const uid = useId();
  const [pos, setPos] = useState(null);
  const close = useCallback(() => onClose(), [onClose]);
  useMenuDismiss(true, close, ref);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos(placeMenu(at, { w: r.width, h: r.height }, { vw: window.innerWidth, vh: window.innerHeight }));
  }, [at]);

  useEffect(() => {
    if (pos) ref.current?.querySelector("[role='menuitem']")?.focus({ preventScroll: true });
  }, [pos]);

  // A scroll that moves the row, or a resize, closes it (it would be left
  // floating away from its row). A scroll event that arrives just after the
  // menu opened, from a scroll that ended before it, moves nothing.
  useEffect(() => {
    const topOf = () => document.getElementById(anchorId)?.getBoundingClientRect().top;
    const start = topOf();
    const onScroll = (e) => {
      if (ref.current?.contains(e.target)) return;
      const now = topOf();
      if (start == null || now == null || Math.abs(now - start) > 1) close();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [close, anchorId]);

  const choose = (it) => {
    if (it.disabled) return;
    onClose();
    onChoose(it.id);
  };
  const onKeyDown = (e) => {
    const all = [...ref.current.querySelectorAll("[role='menuitem']")];
    const i = all.indexOf(document.activeElement);
    const to = (n) => all[(n + all.length) % all.length]?.focus();
    if (e.key === "ArrowDown") to(i + 1);
    else if (e.key === "ArrowUp") to(i < 0 ? all.length - 1 : i - 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(all.length - 1);
    else if (e.key === "Escape" || e.key === "Tab") close();
    else if ((e.key === "Enter" || e.key === " ") && i >= 0) choose(items[i]);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  return createPortal(
    <div ref={ref} className="ovm-menu row-menu" role="menu" aria-label={label} tabIndex={-1}
         style={pos ? { left: pos.left, top: pos.top } : { left: at.x, top: at.y, visibility: "hidden" }}
         onKeyDown={onKeyDown} onContextMenu={(e) => e.preventDefault()}>
      {items.map((it, i) => (
        <button key={it.id} type="button" role="menuitem" tabIndex={-1}
                className={"ovm-item" + (it.danger ? " danger" : "") + (it.disabled ? " off" : "")}
                aria-disabled={it.disabled ? "true" : undefined}
                aria-describedby={it.disabled && it.reason ? `${uid}-${i}` : undefined}
                onClick={() => choose(it)}>
          {it.label}
          {it.disabled && it.reason && <span id={`${uid}-${i}`} className="row-menu-why">{it.reason}</span>}
        </button>
      ))}
    </div>,
    portalHost(),
  );
}
