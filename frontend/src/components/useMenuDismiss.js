import { useEffect } from "react";

// How a dropdown menu closes, the same everywhere: a click or tap outside it,
// Escape, or the mouse moving well clear of it (more than ``leavePx`` past the
// box around ``ref``'s element: the trigger and the menu). Crossing the gap from
// the trigger to an item never closes it. Touch and pen only close on a tap.
export const MENU_LEAVE_PX = 60;

export function outsideBy(rect, x, y) {
  return Math.max(rect.left - x, x - rect.right, rect.top - y, y - rect.bottom, 0);
}

function boxOf(el) {
  // The element and its visible children: an absolutely placed menu sits outside
  // its wrapper's own box.
  const rs = [el, ...el.querySelectorAll("*")]
    .filter((c) => c.offsetParent !== null || c === el)
    .map((c) => c.getBoundingClientRect())
    .filter((r) => r.width || r.height);
  if (!rs.length) return null;
  return {
    left: Math.min(...rs.map((r) => r.left)), right: Math.max(...rs.map((r) => r.right)),
    top: Math.min(...rs.map((r) => r.top)), bottom: Math.max(...rs.map((r) => r.bottom)),
  };
}

export default function useMenuDismiss(open, close, ref, { leavePx = MENU_LEAVE_PX } = {}) {
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
    const esc = (e) => { if (e.key === "Escape") close(); };
    const far = (e) => {
      if (e.pointerType !== "mouse" || !ref.current) return;
      const box = boxOf(ref.current);
      if (box && outsideBy(box, e.clientX, e.clientY) > leavePx) close();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", esc);
    document.addEventListener("pointermove", far);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("touchstart", away);
      document.removeEventListener("keydown", esc);
      document.removeEventListener("pointermove", far);
    };
  }, [open, close, ref, leavePx]);
}
