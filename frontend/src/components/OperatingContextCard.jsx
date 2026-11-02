import { useEffect, useRef, useState } from "react";
import { updateMaintenancePosition } from "../api.js";
import { CONTEXT_LIMIT, CONTEXT_PROMPT, charsLeft, checkContext, contextChanged } from "../operatingContext.js";
import Section, { AddRow } from "./ui/Section.jsx";
import Field from "./ui/Field.jsx";
import { TextArea } from "./ui/Controls.jsx";
import ClampLines from "./ui/ClampLines.jsx";
import "./OperatingContextCard.css";

// A position's operating context on the Explorer's Summary tab: how it's used
// (the load, the environment, the hours it runs), kept apart from the short
// description under its name. A section of the panel (#UI): the text keeps
// its line breaks and is clamped to about six lines ("Show all"); Edit (or
// the "+ Add the operating context" row) changes it in place, with "✓ Saved"
// by the heading after, and a refusal shown on the field. The same request as
// any other change to the position; the server says if you may only view.
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
  const startBtn = useRef(null);
  const area = useRef(null);

  useEffect(() => {
    setSaved(null);
    setEditing(false);
    setError(null);
    setNote(null);
  }, [positionId]);
  useEffect(() => setSaved(null), [loaded]);
  useEffect(() => {
    if (!note) return undefined;
    const t = setTimeout(() => setNote(null), 4000);
    return () => clearTimeout(t);
  }, [note]);

  const text = saved ?? loaded;
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
    setTimeout(() => startBtn.current?.focus(), 0);
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
      setNote(res.value ? "✓ Saved" : "✓ Cleared");
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
  if (state.error && text == null) body = <p className="field-error" role="alert">Couldn't load it: {state.error} Try again in a moment.</p>;
  else if (text == null) body = <p className="td-quiet">Loading…</p>;
  else if (editing) {
    body = (
      <div className="td-ctx-edit">
        <Field label="Operating context" labelHidden error={error} help={error ? null : "Ctrl+Enter saves, Esc cancels."}
               count={charsLeft(draft) || null}>
          <TextArea ref={area} rows={4} value={draft} maxLength={CONTEXT_LIMIT}
                    placeholder={CONTEXT_PROMPT} readOnly={busy} aria-busy={busy || undefined}
                    onChange={(e) => setDraft(e.target.value)} onKeyDown={keys} />
        </Field>
        <div className="td-ctx-actions">
          <button type="button" className="secondary sm" onClick={stop} disabled={busy}>Cancel</button>
          <button type="button" className="sm" onClick={save} disabled={busy} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
    );
  } else if (!text) {
    body = (
      <>
        <p className="td-quiet">{CONTEXT_PROMPT}</p>
        <AddRow ref={startBtn} onClick={start}>Add the operating context</AddRow>
      </>
    );
  } else {
    body = <ClampLines text={text} lines={6} what="the operating context" textClassName="td-ctx-text" />;
  }

  return (
    <Section id="operating-context" title="Operating context" className="td-ctx"
             aside={note && <span className="field-saved td-ctx-note" role="status">{note}</span>}
             action={text && !editing ? { label: "Edit", ariaLabel: "Edit the operating context", onClick: start, ref: startBtn } : null}>
      {body}
    </Section>
  );
}
