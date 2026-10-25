import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { updateMaintenancePosition } from "../api.js";
import { CONTEXT_LIMIT, CONTEXT_PROMPT, charsLeft, checkContext, contextChanged } from "../operatingContext.js";
import "./OperatingContextCard.css";

// A position's operating context on the Explorer's Summary tab: how it's used
// (the load, the environment, the hours it runs), kept apart from the short
// description under its name. The text keeps its line breaks and is clamped to
// about six lines (More / Less); Edit changes it in place (the same request as
// any other change to the position; the server says if you may only view).
// `state` is the Summary tab's position fetch ({ data, error }); `onSaved`
// hears the text saved (so the panel's copy of the position keeps it).
export default function OperatingContextCard({ positionId, state, onSaved }) {
  const loaded = state.data ? state.data.operating_context || "" : null;
  // The text as saved here, until the next fetch brings it back.
  const [saved, setSaved] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);
  const box = useRef(null);
  const editBtn = useRef(null);
  const area = useRef(null);

  useEffect(() => {
    setSaved(null);
    setEditing(false);
    setError(null);
    setNote(null);
    setOpen(false);
  }, [positionId]);
  useEffect(() => setSaved(null), [loaded]);
  useEffect(() => {
    if (!note) return undefined;
    const t = setTimeout(() => setNote(null), 4000);
    return () => clearTimeout(t);
  }, [note]);

  const text = saved ?? loaded;
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || open) return undefined;
    const check = () => setLong(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [text, editing, open]);

  const start = () => {
    setDraft(text || "");
    setError(null);
    setNote(null);
    setEditing(true);
    setTimeout(() => area.current?.focus(), 0);
  };
  const stop = () => {
    setEditing(false);
    setError(null);
    setTimeout(() => editBtn.current?.focus(), 0);
  };
  const save = async () => {
    const res = checkContext(draft);
    if (res.error) return setError(res.error);
    if (!contextChanged(text, res.value)) return stop();
    setBusy(true);
    setError(null);
    try {
      const p = await updateMaintenancePosition(positionId, { operating_context: res.value });
      setSaved(p?.operating_context ?? res.value);
      onSaved?.(p?.operating_context ?? res.value);
      setOpen(false);
      setNote(res.value ? "Saved." : "Cleared.");
      stop();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };
  const keys = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      stop();
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      save();
    }
  };

  let body;
  if (state.error && text == null) body = <p className="lib-date">Couldn't load it: {state.error} Try again in a moment.</p>;
  else if (text == null) body = <p className="lib-date">Loading…</p>;
  else if (editing) {
    const left = charsLeft(draft);
    body = (
      <div className="td-ctx-edit">
        <textarea ref={area} id={`td-ctx-${positionId}`} rows={6} value={draft} maxLength={CONTEXT_LIMIT}
                  aria-label="Operating context" placeholder={CONTEXT_PROMPT} disabled={busy}
                  onChange={(e) => setDraft(e.target.value)} onKeyDown={keys} />
        <div className="td-ctx-actions">
          <button type="button" className="sm" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          <button type="button" className="secondary sm" onClick={stop} disabled={busy}>Cancel</button>
          {left && <span className="lib-date" aria-live="polite">{left}</span>}
        </div>
      </div>
    );
  } else if (!text) {
    body = (
      <div className="td-ctx-empty">
        <p className="lib-date">{CONTEXT_PROMPT}</p>
        <button type="button" className="secondary sm" onClick={start} ref={editBtn}>Add</button>
      </div>
    );
  } else {
    body = (
      <>
        <p ref={box} className={"td-ctx-text" + (open ? " open" : "")}>{text}</p>
        {(long || open) && (
          <button type="button" className="link sm td-ctx-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Less" : "More"}<span className="sr-only"> of the operating context</span>
          </button>
        )}
      </>
    );
  }

  return (
    <section className="card td-card td-ctx" id="operating-context" aria-label="Operating context">
      <div className="td-ctx-head">
        <h3>Operating context</h3>
        {note && <span className="tt-msg ok" role="status">{note}</span>}
        {text && !editing && (
          <button type="button" className="secondary sm td-ctx-edit-btn" onClick={start} ref={editBtn}>
            Edit<span className="sr-only"> the operating context</span>
          </button>
        )}
      </div>
      {error && <p className="td-ctx-error" role="alert">{error}</p>}
      {body}
    </section>
  );
}
