// Closing a dialog by clicking its backdrop, without closing it when a press
// that began inside the dialog (selecting text in a field, say) is released
// out on the backdrop: the browser fires `click` on the nearest element that
// holds both ends of the gesture, which is the backdrop, so a plain onClick
// there can't tell the two apart. The backdrop closes only when the press
// *and* the release are both on it.
import { useRef } from "react";

// `downOnBackdrop`: the press started on the backdrop itself. `target` and
// `currentTarget`: the click's. `detail`: the click count; the second click of
// a double-click on the button that opened the dialog doesn't close it.
export function shouldCloseOnBackdrop({ downOnBackdrop, target, currentTarget, detail }) {
  return !!downOnBackdrop && target === currentTarget && !(detail >= 2);
}

// Props for the backdrop element: onPointerDown remembers where the press
// began, onClick closes (onClose) only if it began and ended on the backdrop.
// `enabled` false (a locked dialog) closes nothing.
export function useBackdropClose(onClose, enabled = true) {
  const down = useRef(false);
  return {
    onPointerDown: (e) => { down.current = e.target === e.currentTarget; },
    onClick: (e) => {
      const downOnBackdrop = down.current;
      down.current = false;
      if (enabled && shouldCloseOnBackdrop({ downOnBackdrop, target: e.target, currentTarget: e.currentTarget, detail: e.detail })) onClose();
    },
  };
}
