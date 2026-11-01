import { useCallback, useEffect, useId, useReducer, useRef } from "react";
import { AddRow } from "./Section.jsx";
import { CLOSED, commitAction, inlineAddReducer, refusalOf } from "../../inlineAdd.js";

// Adding to a list in place (inlineAdd.js has the rules): the dashed
// "+ Add …" row ends the list; pressed, it becomes a new row of the list with
// a box where the row's text goes. Enter or leaving the row saves; Esc or an
// empty box drops it; a refusal keeps the text with the reason under it.
// Once saved, the add row is back and focused, ready for the next one.
//
// The list draws the new row itself, with its own row markup, so it looks
// like the rows above it:
//
//   const add = useInlineAdd({ onSave, check, startToken });
//   <ol>{rows}{add.open && <InlineAddRow add={add} as="li" className="…" lead={…} placeholder="…" label="…" />}</ol>
//   {!add.open && <InlineAddButton add={add}>Add a …</InlineAddButton>}
//
//   onSave      (text) → a promise; it rejects (or resolves a string) with a refusal
//   errorText   (error) → the words for a rejection
//   check       (text) → why it can't be saved yet (null when it can)
//   startToken  a value that, when it changes (and isn't null), opens the row (a row menu's Add …)
export function useInlineAdd({ onSave, errorText = (e) => e?.message || "It couldn't be added.", check = null, startToken = null, disabled = false }) {
  const [state, dispatch] = useReducer(inlineAddReducer, CLOSED);
  const box = useRef(null);
  const button = useRef(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const live = useRef(state);
  live.current = state;
  const refocus = useRef(false);

  const start = useCallback(() => { if (!disabled) dispatch({ type: "start" }); }, [disabled]);
  useEffect(() => { if (startToken != null) start(); }, [startToken]); // eslint-disable-line react-hooks/exhaustive-deps
  // Opened: the box focused and in view.
  useEffect(() => {
    if (!state.open) return;
    const el = box.current;
    if (el && document.activeElement !== el && !el.closest("[data-ia-row]")?.contains(document.activeElement)) {
      el.focus({ preventScroll: true });
      el.scrollIntoView?.({ block: "nearest" });
    }
  }, [state.open]);
  // Closed after a save or Esc: the focus back on the add row.
  useEffect(() => {
    if (state.open || !refocus.current) return;
    refocus.current = false;
    button.current?.focus({ preventScroll: true });
  }, [state.open]);

  const commit = useCallback(async ({ focusBack = true } = {}) => {
    const what = commitAction(live.current, { check });
    if (what.act === "cancel") { refocus.current = focusBack; dispatch({ type: "cancel" }); return; }
    if (what.act === "invalid") { dispatch({ type: "failed", error: what.error, check: true }); return; }
    if (what.act !== "save") return;
    dispatch({ type: "saving" });
    live.current = { ...live.current, busy: true };
    try {
      const refusal = refusalOf(await onSave(what.text));
      if (!alive.current) return;
      if (refusal) dispatch({ type: "failed", error: refusal });
      else { refocus.current = focusBack; dispatch({ type: "saved" }); }
    } catch (e) {
      if (alive.current) dispatch({ type: "failed", error: errorText(e) });
    }
  }, [check, onSave, errorText]);
  const cancel = useCallback(() => { refocus.current = true; dispatch({ type: "cancel" }); }, []);
  const type = useCallback((text) => dispatch({ type: "type", text }), []);
  return { ...state, start, commit, cancel, type, box, button, disabled };
}

// The new row: the list's own row (`as`, `className`), its leading column
// (`lead`: a blank grip, an icon), the box, anything the row needs besides
// its text (`children`: a task's interval), and one line under it: the
// refusal, or else `help`.
export function InlineAddRow({ add, as: Tag = "li", className = "", lead = null, label, placeholder, help = null, children = null }) {
  const id = useId();
  const under = add.error || help ? `${id}-under` : undefined;
  return (
    <Tag className={"ia-row" + (className ? ` ${className}` : "")} data-ia-row=""
         onKeyDown={(e) => {
           if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); add.cancel(); }
           else if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "BUTTON") { e.preventDefault(); add.commit(); }
         }}
         onBlur={(e) => {
           // Leaving the row (not moving within it) keeps what's typed, or drops an empty one.
           if (e.currentTarget.contains(e.relatedTarget)) return;
           add.commit({ focusBack: false });
         }}>
      {lead}
      <span className="ia-main">
        <input ref={add.box} type="text" className="ctl ia-box" aria-label={label} placeholder={placeholder} value={add.text}
               readOnly={add.busy} aria-busy={add.busy || undefined} aria-invalid={add.error && add.onText ? "true" : undefined}
               aria-describedby={under} enterKeyHint="done" autoComplete="off"
               onChange={(e) => add.type(e.target.value)} />
        {children}
        {add.error ? <span id={under} className="field-error" role="alert">{add.error}</span>
          : help ? <span id={under} className="field-help">{help}</span> : null}
        {add.busy && <span className="sr-only" role="status">Adding…</span>}
      </span>
    </Tag>
  );
}

// The dashed "+ Add …" row that starts it.
export function InlineAddButton({ add, children }) {
  return <AddRow ref={add.button} disabled={add.disabled} onClick={add.start}>{children}</AddRow>;
}
