import { useEffect, useRef, useState } from "react";
import { deleteRcm, deleteRcmPreview, deleteTree, deleteTreePreview, restoreTree } from "../api.js";
import { DELETE_NOTE, deleteButton, deleteLines, deleteTitle, deletedText, isUndoKey, rbdsNote, undoneText } from "../treeDelete.js";
import {
  RCM_DELETE_NOTE, rcmDeleteButton, rcmDeleteCounts, rcmDeleteLines, rcmDeleteTitle, rcmDeletedText,
} from "../rcmDelete.js";
import { FormModal } from "./MaintenanceParts.jsx";
import { hasOpenLayer } from "../fullScreen.js";
import "./DeleteTree.css";

// Delete… on a position or location (the Explorer's row menu, the Assets and
// Products lists, the position and location pages; never an item). The dialog asks the
// server what would go (a dry run) and says it in plain words; one click
// deletes it all (treeDelete.js has the words). `onDone(answer, toast)`: the
// server's answer, and the toast to show ({text, kind, id, name}).
export function DeleteTreeModal({ kind, id, name, onClose, onDone }) {
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    deleteTreePreview(kind, id).then((c) => live && setCounts({ ...c, kind, name: c.name || name }))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [kind, id, name]);
  const lines = counts ? deleteLines(counts) : [];
  return (
    <FormModal title={counts ? deleteTitle(counts) : `Delete “${name || "it"}”?`} danger
               submitLabel={counts ? deleteButton(counts) : "Delete"} pendingLabel="Deleting…"
               canSubmit={!!counts} onClose={onClose}
               onSubmit={async () => {
                 const answer = await deleteTree(kind, id);
                 const done = { ...answer, kind, name: answer.name || counts.name };
                 onDone(done, { text: deletedText(done), kind, id, name: done.name });
               }}>
      {error && <p className="card error">{error}</p>}
      {!counts && !error && <p className="lib-date" aria-live="polite">Counting what's inside it…</p>}
      {counts && (
        <div className="td-body" data-testid="delete-counts">
          {lines.length > 0 ? (
            <>
              <p>Everything inside it goes too:</p>
              <ul className="td-list">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
            </>
          ) : <p>Nothing else is inside it.</p>}
          {rbdsNote(counts.rbds) && <p className="field-warning" role="note">{rbdsNote(counts.rbds)}</p>}
          <p className="lib-date">{DELETE_NOTE}</p>
        </div>
      )}
    </FormModal>
  );
}

// Delete… on a row of a position's RCM (the RCM and FME(C)A tabs): a
// function, performance standard, functional failure or failure mode with
// everything under it. The same dialog as a position's: the server's dry-run
// counts in plain words ("2 functional failures, 5 failure modes, 3 tasks."),
// one click deletes it all (rcmDelete.js has the words). `onDone(answer,
// toast)`: the server's answer and the toast to show ({text, id, name}).
export function DeleteRcmModal({ kind, id, name, onClose, onDone }) {
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    deleteRcmPreview(kind, id).then((c) => live && setCounts({ ...c, kind, name: c.name || name }))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [kind, id, name]);
  const summary = counts ? rcmDeleteCounts(counts) : "";
  const lines = counts ? rcmDeleteLines(counts) : [];
  return (
    <FormModal title={counts ? rcmDeleteTitle(counts) : `Delete “${name || "it"}”?`} danger
               submitLabel={counts ? rcmDeleteButton(counts) : "Delete"} pendingLabel="Deleting…"
               canSubmit={!!counts} onClose={onClose}
               onSubmit={async () => {
                 const answer = await deleteRcm(kind, id);
                 const done = { ...counts, ...answer, kind, name: answer.name || counts.name };
                 onDone(done, { text: rcmDeletedText(done), id, name: done.name });
               }}>
      {error && <p className="card error">{error}</p>}
      {!counts && !error && <p className="lib-date" aria-live="polite">Counting what's under it…</p>}
      {counts && (
        <div className="td-body" data-testid="delete-counts">
          {summary ? <p>Everything under it goes too: {summary}</p> : <p>Nothing else is under it.</p>}
          {lines.length > 0 && <ul className="td-list">{lines.map((l) => <li key={l}>{l}</li>)}</ul>}
          <p className="lib-date">{RCM_DELETE_NOTE}</p>
        </div>
      )}
    </FormModal>
  );
}

// The toast after a delete, with Undo (also Ctrl+Z / Cmd+Z while it shows).
// For pages without a toast of their own (the Explorer has one). `deleted`:
// {text, kind, id, name}; `onRestored(answer)` after an undo, to read the
// list again.
export function DeletedToast({ deleted, onClose, onRestored }) {
  const [state, setState] = useState({ busy: false, text: null, tone: null });
  const busy = useRef(false);
  const undo = async () => {
    if (busy.current || state.text) return;
    busy.current = true;
    setState({ busy: true, text: null });
    try {
      const answer = await restoreTree(deleted.kind, deleted.id);
      setState({ busy: false, text: undoneText({ ...answer, name: deleted.name }) });
      onRestored?.(answer);
    } catch (e) {
      setState({ busy: false, text: `Couldn't undo it: ${e.message}`, tone: "error" });
    }
    busy.current = false;
  };
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (state.busy) return undefined;
    const t = setTimeout(() => close.current(), state.text ? 5000 : 12000);
    return () => clearTimeout(t);
  }, [state]);
  useEffect(() => {
    if (state.text) return undefined;
    const onKey = (e) => {
      if (!isUndoKey(e) || hasOpenLayer(document)) return;
      e.preventDefault();
      undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className={"undo-toast" + (state.tone === "error" ? " error" : "")} role="status">
      <span>{state.text || deleted.text}</span>
      {!state.text && (
        <button type="button" className="secondary sm" onClick={undo} disabled={state.busy}
                title="Undo (Ctrl+Z or Cmd+Z)">{state.busy ? "Undoing…" : "Undo"}</button>
      )}
      <button type="button" className="undo-toast-x" onClick={onClose} aria-label="Dismiss">✕</button>
    </div>
  );
}
