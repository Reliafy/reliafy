import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { buttonClass } from "./ui/Button.jsx";
import { normaliseConfirm, normalisePrompt, saveErrorText } from "../confirm.js";

// The app's own confirm dialog (replaces window.confirm and window.prompt).
// Mounted once near the root; any component asks with
//   const confirm = useConfirm();
//   if (!(await confirm({ title, body, confirmLabel: "Delete diagram" }))) return;
// which resolves true only when the person presses the action button, or, for
// a name to type,
//   const ask = useAskText();
//   const name = changedText(await ask(renamePrompt({ kind: "dataset", name })), name);
// which resolves to the text typed, or null when cancelled.
//
// With `run` (and `pendingLabel`, e.g. "Adding…"), the dialog does the work
// itself: pressing the button calls run(text) (or run() for a confirm), and
// the dialog stays open, the button disabled and saying pendingLabel, until it
// settles. It resolves to what run returned; if run throws, the error shows in
// the dialog, with the text as typed, to try again or cancel. Either way the
// dialog answers once: a second click, double-click or Enter does nothing.
const ConfirmContext = createContext(null);

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm needs a <ConfirmProvider> above it.");
  return ctx.confirm;
}

export function useAskText() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useAskText needs a <ConfirmProvider> above it.");
  return ctx.askText;
}

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);
  const queue = useRef([]);
  const nextId = useRef(0);

  const enqueue = useCallback((req) => new Promise((resolve) => {
    nextId.current += 1;
    queue.current.push({ ...req, id: nextId.current, resolve });
    setRequest((current) => current || queue.current[0]);
  }), []);

  const confirm = useCallback((opts) => {
    const req = normaliseConfirm(opts);
    return enqueue(req);
  }, [enqueue]);

  const askText = useCallback((opts) => {
    const req = normalisePrompt(opts);
    return enqueue({ ...req, input: true });
  }, [enqueue]);

  const settle = useCallback((answer) => {
    const done = queue.current.shift();
    done?.resolve(answer);
    setRequest(queue.current[0] || null);
  }, []);

  const value = useMemo(() => ({ confirm, askText }), [confirm, askText]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      {request && <ConfirmDialog key={request.id} request={request} onAnswer={settle} />}
    </ConfirmContext.Provider>
  );
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

function ConfirmDialog({ request, onAnswer }) {
  const id = useId();
  const box = useRef(null);
  const cancelBtn = useRef(null);
  const inputRef = useRef(null);
  const asking = !!request.input;
  const [text, setText] = useState(asking ? request.value : "");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const answered = useRef(false); // set at once, before React draws the dialog again
  const cancel = useCallback(() => {
    if (answered.current) return;
    answered.current = true;
    onAnswer(asking ? null : false);
  }, [onAnswer, asking]);
  const canGo = !asking || text.trim() !== "";

  useEffect(() => {
    const before = document.activeElement;
    // Focus starts on the safe choice, or in the box with its text selected.
    if (inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    } else {
      cancelBtn.current?.focus();
    }
    // Capture on window so an Escape here doesn't also close a dialog
    // underneath (Modal listens on document).
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancel();
      } else if (e.key === "Tab" && box.current) {
        const items = [...box.current.querySelectorAll(FOCUSABLE)];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (!box.current.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
        } else if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
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
  }, [cancel]);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!canGo || answered.current) return;
    answered.current = true;
    const answer = asking ? text.trim() : true;
    if (!request.run) {
      onAnswer(answer);
      return;
    }
    setBusy(true);
    setFailed(null);
    try {
      const out = await request.run(asking ? answer : undefined);
      onAnswer(out);
    } catch (err) {
      answered.current = false;
      setBusy(false);
      setFailed(saveErrorText(err, { what: request.failedWhat, offline: navigator.onLine === false }));
    }
  };

  return createPortal(
    <div className="overlay confirm-overlay"
         // Not the second click of a double-click on the button that opened it.
         onClick={(e) => { if (e.detail < 2) cancel(); }}>
      <form
        ref={box}
        className="modal modal-sm confirm-dialog"
        role={asking ? "dialog" : "alertdialog"}
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={request.body ? `${id}-body` : undefined}
        onClick={(e) => e.stopPropagation()}
        onSubmit={onSubmit}
        noValidate
      >
        <div className="modal-head">
          <h3 id={`${id}-title`}>{request.title}</h3>
        </div>
        {(request.body || asking) && (
          <div className="modal-body">
            {request.body && <p id={`${id}-body`} className="confirm-body">{request.body}</p>}
            {asking && (
              <label className="confirm-field">
                <span>{request.label}</span>
                <input
                  ref={inputRef}
                  type="text"
                  value={text}
                  maxLength={200}
                  autoComplete="off"
                  spellCheck="false"
                  readOnly={busy}
                  aria-invalid={failed ? "true" : undefined}
                  onChange={(e) => setText(e.target.value)}
                />
              </label>
            )}
            {failed && <p className="confirm-error" role="alert">{failed}</p>}
          </div>
        )}
        <div className="modal-foot">
          <div className="row confirm-actions">
            <button type="button" ref={cancelBtn} className={buttonClass("secondary")} onClick={cancel} disabled={busy}>
              {request.cancelLabel}
            </button>
            <button
              type="submit"
              className={buttonClass(request.destructive ? "danger" : "primary") || undefined}
              disabled={!canGo || busy}
              aria-busy={busy || undefined}
            >
              {busy ? request.pendingLabel : request.confirmLabel}
            </button>
          </div>
        </div>
      </form>
    </div>,
    portalHost()
  );
}
