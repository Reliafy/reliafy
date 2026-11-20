import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { trapTab, useDialogFocus } from "./focusTrap.js";

// Open modals, oldest first: Escape closes only the topmost one (a sheet
// picker opened from inside another dialog, say).
const openModals = [];

// Lightweight modal dialog with an overlay. Closes on Escape and overlay click
// (unless locked, e.g. while a request is in flight). Rendered through a portal
// to <body> (the shared portal host, which moves into a part of the page that
// is full screen) so the overlay covers the whole viewport (including the top
// bar) regardless of where it's mounted in the tree. Every dialog holds the
// keyboard: focus moves into it when it opens (unless a field inside took it
// already, e.g. autoFocus), Tab and Shift+Tab go round its own controls, never
// out to the page behind it, and when it closes (Escape, ×, the overlay or its
// own buttons) focus goes back to whatever had it, the button that opened it.
// `overlayClassName`: a class on the overlay too (e.g. a dialog that becomes a
// sheet on a phone).
export default function Modal({ title, onClose, locked, children, footer, className, overlayClassName }) {
  const token = useRef({});
  const box = useRef(null);
  const titleId = useId();
  useDialogFocus(box);
  useEffect(() => {
    const me = token.current;
    openModals.push(me);
    return () => {
      const i = openModals.indexOf(me);
      if (i >= 0) openModals.splice(i, 1);
    };
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      // A dropdown in the dialog that took the Escape (to close its list) keeps the dialog open.
      if (e.key === "Escape" && !e.defaultPrevented && !locked && openModals[openModals.length - 1] === token.current) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, locked]);

  return createPortal(
    <div
      className={"overlay" + (overlayClassName ? " " + overlayClassName : "")}
      onClick={(e) => {
        // Not the second click of a double-click on the button that opened it.
        if (!locked && e.detail < 2) onClose();
      }}
    >
      <div
        ref={box}
        className={"modal" + (className ? " " + className : "")}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (openModals[openModals.length - 1] === token.current) trapTab(e, box.current); }}
      >
        <div className="modal-head">
          <h3 id={titleId}>{title}</h3>
          <button
            className="modal-close"
            onClick={onClose}
            disabled={locked}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    portalHost()
  );
}
