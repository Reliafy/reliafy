import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Section from "./ui/Section.jsx";
import Field from "./ui/Field.jsx";
import { TextArea } from "./ui/Controls.jsx";
import ClampLines from "./ui/ClampLines.jsx";
import { renderBasisMarkdown } from "../basisMarkdown.js";
import { FUNCTION_NOTES_HINT, checkNotes, notesChanged, notesCount, notesLimit, notesOf, notesPrompt } from "../rcmNotes.js";
import "./OperatingContextCard.css";

// "Notes and rationale" in an RCM row's details, the first section under its title and status chips
// (a function, a performance standard, a functional failure, a failure mode; the same on the RCM and
// FME(C)A tabs, and in the phone's sheet): the row's long description, where
// the reason for it is written. The text keeps its line breaks and is clamped
// to about six lines ("Show all"); Edit (or the add row when there are none)
// opens a box in place with a character count and Save / Cancel, as the
// operating context does. Empty, it is only its heading with a quiet "+ Add notes" at the
// right (Derryn, 9 Nov 2026: no prompt, no dashed row; the prompt is the box's placeholder). `onSave(value)` is the details' commit: true, or a
// promise of true, once saved; a string is the refusal, shown on the box with
// the text kept.
//
// A function's notes also hold the working behind its performance standards
// (they were two sections until Nov 2026; a working written before reads
// below the notes under a "Working" line, and the first save keeps both as
// one text). So on a function: the hint says the working goes here, the text
// is shown as Markdown (tables, lists; the same cleaned renderer the working
// had), it may run to 25,000 characters, and `children` (its PDFs) close the
// section. `openToken` changes when the notes are asked for in full (a
// decision's linked notes clicked): they unfold.

// A function's notes as Markdown, folded to about six lines with Show all.
function MarkdownClamp({ text, openToken }) {
  const html = useMemo(() => renderBasisMarkdown(text), [text]);
  const box = useRef(null);
  const [long, setLong] = useState(false);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => { setOpen(false); }, [text]);
  useEffect(() => { if (openToken != null) setOpen(true); }, [openToken]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || open) return undefined;
    const check = () => setLong(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [html, open]);
  return (
    <div className="clampl">
      <div ref={box} className={"rw-md rw-notes-md" + (open ? " open" : "")} dangerouslySetInnerHTML={{ __html: html }} />
      {(long || open) && (
        <button type="button" className="link clampl-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}<span className="sr-only"> of the notes</span>
        </button>
      )}
    </div>
  );
}

export default function RcmNotes({ r, readOnly = false, onSave, openToken = null, children = null }) {
  const text = notesOf(r);
  const fn = r.type === "fn";
  const limit = notesLimit(r);
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
    const res = checkNotes(draft, limit);
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

  const count = notesCount(draft, limit);
  let body;
  if (editing) {
    body = (
      <div className="td-ctx-edit">
        {fn && <p className="rw-fhelp rw-notes-hint">{FUNCTION_NOTES_HINT}</p>}
        <Field label="Notes and rationale" labelHidden error={error || (count.over ? count.message : null)}
               help={error || count.over ? null : fn ? "Markdown is fine: headings, lists, tables, links. Ctrl+Enter saves, Esc cancels."
                 : "Ctrl+Enter saves, Esc cancels."}
               count={<span className={"char-count" + (count.tone ? ` ${count.tone}` : "")}>{count.text}</span>}>
          <TextArea ref={area} rows={fn ? 8 : 5} value={draft} maxLength={limit} placeholder={notesPrompt(r)}
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
    // Empty: only the quiet "+ Add notes" at the heading's right (its prompt is
    // its tooltip and the box's placeholder); read-only, a quiet "None".
    body = readOnly ? <p className="td-quiet rw-notes-none">None</p> : null;
  } else {
    body = fn ? <MarkdownClamp text={text} openToken={openToken} />
      : <ClampLines text={text} lines={6} what="the notes" textClassName="td-ctx-text" />;
  }

  return (
    <Section title="Notes and rationale" className="td-ctx rw-notes"
             aside={note && <span className="field-saved td-ctx-note" role="status">{note}</span>}
             action={editing || readOnly ? null : text ? { label: "Edit", ariaLabel: "Edit the notes and rationale", onClick: start, ref: startBtn }
               : { label: "Add notes", plus: true, onClick: start, ref: startBtn, title: fn ? `${notesPrompt(r)} ${FUNCTION_NOTES_HINT}` : notesPrompt(r) }}>
      {body}
      {children}
    </Section>
  );
}
