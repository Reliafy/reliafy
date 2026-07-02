import { useEffect } from "react";
import { createPortal } from "react-dom";

// Lightweight modal dialog with an overlay. Closes on Escape and overlay click
// (unless locked, e.g. while a request is in flight). Rendered through a portal
// to <body> so the overlay covers the whole viewport (including the top bar)
// regardless of where it's mounted in the tree.
export default function Modal({ title, onClose, locked, children, footer, className }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !locked) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, locked]);

  return createPortal(
    <div
      className="overlay"
      onClick={() => {
        if (!locked) onClose();
      }}
    >
      <div
        className={"modal" + (className ? " " + className : "")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3>{title}</h3>
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
    document.body
  );
}
