import { useEffect, useRef, useState } from "react";
import Section from "./ui/Section.jsx";
import Field from "./ui/Field.jsx";
import { TextArea } from "./ui/Controls.jsx";
import ClampLines from "./ui/ClampLines.jsx";
import { NOTES_LIMIT, checkNotes, notesChanged, notesCount, notesOf, notesPrompt } from "../rcmNotes.js";
import "./OperatingContextCard.css";

// "Notes and rationale" in an RCM row's details (the first thing under its title) (a function, a performance
// standard, a functional failure, a failure mode; the same on the RCM and
// FME(C)A tabs, and in the phone's sheet): the row's long description, where
// the reason for it is written. The text keeps its line breaks and is clamped
// to about six lines ("Show all"); Edit (or the add row when there are none)
// opens a box in place with a character count and Save / Cancel, as the
// operating context does. `onSave(value)` is the details' commit: true, or a
// promise of true, once saved; a string is the refusal, shown on the box with
// the text kept.
export default function RcmNotes({ r, readOnly = false, onSave }) {
  const text = notesOf(r);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const startBtn = useRef(null);
  const area = useRef(null);

  useEffect(() => {
    setEditing(false);
    setError(null);
    setNote(null);
  }, [r.key]);
  useEffect(() => {
    if (!note) return undefined;
    const t = setTimeout(() => setNote(null), 4000);
    return () => clearTimeout(t);
  }, [note]);

  const start = () => {
    setDraft(text);
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
    const res = checkNotes(draft);
    if (res.error) return setError(res.error);
    if (!notesChanged(text, draft)) return stop();
    setBusy(true);
    setError(null);
    const out = await onSave(res.value);
    setBusy(false);
    if (typeof out === "string") return setError(out);
    setNote(res.value ? "✓ Saved" : "✓ Cleared");
    stop();
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

  const count = notesCount(draft);
  let body;
  if (editing) {
    body = (
      <div className="td-ctx-edit">
        <Field label="Notes and rationale" labelHidden error={error || (count.over ? count.message : null)}
               help={error || count.over ? null : "Ctrl+Enter saves, Esc cancels."}
               count={<span className={"char-count" + (count.tone ? ` ${count.tone}` : "")}>{count.text}</span>}>
          <TextArea ref={area} rows={5} value={draft} maxLength={NOTES_LIMIT} placeholder={notesPrompt(r)}
                    readOnly={busy} aria-busy={busy || undefined}
                    aria-description={`${count.n} of ${count.max} characters.`}
                    onChange={(e) => setDraft(e.target.value)} onKeyDown={keys} />
        </Field>
        <div className="td-ctx-actions">
          <button type="button" className="secondary sm" onClick={stop} disabled={busy}>Cancel</button>
          <button type="button" className="sm" onClick={save} disabled={busy} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
    );
  } else if (!text) {
    // Empty: one quiet line (the prompt and the link), so it doesn't push the details down.
    return (
      <section className="rw-notes rw-notes-empty" aria-label="Notes and rationale">
        <p className="td-quiet">
          {notesPrompt(r)}
          {!readOnly && <> <button ref={startBtn} type="button" className="link" onClick={(e) => { if (e.detail < 2) start(); }}>Add notes</button></>}
        </p>
      </section>
    );
  } else {
    body = <ClampLines text={text} lines={6} what="the notes" textClassName="td-ctx-text" />;
  }

  return (
    <Section title="Notes and rationale" className="td-ctx rw-notes"
             aside={note && <span className="field-saved td-ctx-note" role="status">{note}</span>}
             action={text && !editing && !readOnly ? { label: "Edit", ariaLabel: "Edit the notes and rationale", onClick: start, ref: startBtn } : null}>
      {body}
    </Section>
  );
}
