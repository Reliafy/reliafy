import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { buttonClass } from "./ui/Button.jsx";
import { normaliseConfirm } from "../confirm.js";

// The app's own confirm dialog (replaces window.confirm). Mounted once near the
// root; any component asks with
//   const confirm = useConfirm();
//   if (!(await confirm({ title, body, confirmLabel: "Delete diagram" }))) return;
// It resolves true only when the person presses the action button.
const ConfirmContext = createContext(null);

export function useConfirm() {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm needs a <ConfirmProvider> above it.");
  return confirm;
}

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const queue = useRef([]);

  const confirm = useCallback((opts) => {
    const req = normaliseConfirm(opts);
    return new Promise((resolve) => {
      queue.current.push({ ...req, resolve });
      setRequest((current) => current || queue.current[0]);
    });
  }, []);

  const settle = useCallback((answer) => {
    const done = queue.current.shift();
    done?.resolve(answer);
    setRequest(queue.current[0] || null);
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {request && <ConfirmDialog key={queue.current.length + request.title} request={request} onAnswer={settle} />}
    </ConfirmContext.Provider>
  );
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

function ConfirmDialog({ request, onAnswer }) {
  const id = useId();
  const box = useRef(null);
  const cancelBtn = useRef(null);

  useEffect(() => {
    const before = document.activeElement;
    // Focus starts on the safe choice.
    cancelBtn.current?.focus();
    // Capture on window so an Escape here doesn't also close a dialog
    // underneath (Modal listens on document).
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onAnswer(false);
      } else if (e.key === "Tab" && box.current) {
        const items = [...box.current.querySelectorAll(FOCUSABLE)];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        } else if (!box.current.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      if (before && typeof before.focus === "function" && document.contains(before)) before.focus();
    };
  }, [onAnswer]);

  return createPortal(
    <div className="overlay confirm-overlay" onClick={() => onAnswer(false)}>
      <div
        ref={box}
        className="modal modal-sm confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={request.body ? `${id}-body` : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3 id={`${id}-title`}>{request.title}</h3>
        </div>
        {request.body && (
          <div className="modal-body">
            <p id={`${id}-body`} className="confirm-body">{request.body}</p>
          </div>
        )}
        <div className="modal-foot">
          <div className="row confirm-actions">
            <button type="button" ref={cancelBtn} className={buttonClass("secondary")} onClick={() => onAnswer(false)}>
              {request.cancelLabel}
            </button>
            <button
              type="button"
              className={buttonClass(request.destructive ? "danger" : "primary") || undefined}
              onClick={() => onAnswer(true)}
            >
              {request.confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
