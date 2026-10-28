import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";

// Open modals, oldest first: Escape closes only the topmost one (a sheet
// picker opened from inside another dialog, say).
const openModals = [];

// Lightweight modal dialog with an overlay. Closes on Escape and overlay click
// (unless locked, e.g. while a request is in flight). Rendered through a portal
// to <body> (the shared portal host, which moves into a part of the page that
// is full screen) so the overlay covers the whole viewport (including the top
// bar) regardless of where it's mounted in the tree. Focus moves into the dialog
// when it opens (unless a field inside took it already, e.g. autoFocus) and
// goes back to whatever had it, the button that opened it, when it closes.
// `trapFocus`: Tab and Shift+Tab go round the dialog's own controls, never out
// to the page behind it. `overlayClassName`: a class on the overlay too (e.g.
// a dialog that becomes a sheet on a phone).
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function trapTab(e, node) {
  if (e.key !== "Tab" || !node) return;
  const all = [...node.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
  if (!all.length) {
    e.preventDefault();
    return;
  }
  const first = all[0];
  const last = all[all.length - 1];
  const at = document.activeElement;
  if (e.shiftKey && (at === first || at === node || !node.contains(at))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (at === last || !node.contains(at))) {
    e.preventDefault();
    first.focus();
  }
}

export default function Modal({ title, onClose, locked, children, footer, className, trapFocus = false, overlayClassName }) {
  const token = useRef({});
  const box = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const before = document.activeElement;
    const node = box.current;
    if (node && !node.contains(document.activeElement)) node.focus({ preventScroll: true });
    return () => {
      // Only when focus is still in this dialog (or dropped to the page):
      // a page it navigated to keeps its own focus.
      const now = document.activeElement;
      const lost = !now || now === document.body || (node && node.contains(now));
      if (lost && before && typeof before.focus === "function" && document.contains(before)) {
        before.focus({ preventScroll: true });
      }
    };
  }, []);
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
        onKeyDown={trapFocus ? (e) => { if (openModals[openModals.length - 1] === token.current) trapTab(e, box.current); } : undefined}
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
