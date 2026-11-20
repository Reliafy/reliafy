import { Suspense, lazy, useState } from "react";
import { Link } from "react-router-dom";
import TablePane from "./TablePane.jsx";
import Field from "./ui/Field.jsx";
import { TextInput } from "./ui/Controls.jsx";
import "./ModelTable.css";
import "./RbdPane.css";

// The builder loads with the pane (React Flow is large), as it does with its own page.
const RbdEditor = lazy(() => import("./RbdEditor.jsx"));

// A position's RBD in the Explorer's table area (?rbd=<RBD id>&on=<position id>, tablePane.js), the
// tree kept beside it: the RBD editor itself, the very component the RBD page shows (Derryn, 9 Nov
// 2026: "make sure that we're using the same components so that if we make a change in one, it's
// in the other automatically"). Saving saves the diagram, as on its page. Open full page goes to
// that page.
//
//   rbdId     the diagram           position  {id, name}: the position it's linked to
//   built     just built or rebuilt from what's inside: no note any more (the builder's blocks show
//             their placeholders); kept so callers needn't change
//   onRebuild  Rebuild from what's inside… was chosen: the question is asked here, over the diagram
//             it would change (no dialog), and nothing happens until Rebuild is pressed. Cancel
//             leaves the diagram open as it is.
//   onDirty(changed)   onSaved(id)   onOpenFull(event, path): may stop the link (unsaved changes)
//   phone, headingRef, onClose: TablePane's
export default function RbdPane({ rbdId, position, built = null, onRebuild = null, phone = false, headingRef = null, onClose, onDirty, onSaved, onOpenFull }) {
  const [failed, setFailed] = useState(null);
  const [asking, setAsking] = useState(!!onRebuild);
  const path = `/systems/b/${encodeURIComponent(rbdId)}`;
  return (
    <TablePane title="RBD" subject={position.name} phone={phone} headingRef={headingRef} onClose={onClose}
               className="rbd-pane" closeLabel="Close the RBD" bare
               actions={<Link to={path} className="rbd-pane-full" onClick={(e) => onOpenFull?.(e, path)}>Open full page</Link>}>
      <div className="rbd-pane-body">
        {asking && onRebuild && !failed && (
          <div className="rbd-pane-ask" role="group" aria-label="Rebuild from what's inside">
            <p>
              <strong>Rebuild from what’s inside {position.name}?</strong>{" "}
              Each position inside that the diagram has no block for is added, in series before the output.
              Everything else in the diagram stays as it is.
            </p>
            <div className="rbd-pane-ask-btns">
              <button type="button" className="sm" onClick={onRebuild}>Rebuild</button>
              <button type="button" className="secondary sm" onClick={() => setAsking(false)}>Cancel</button>
            </div>
          </div>
        )}
        {failed ? (
          <div className="rbd-pane-failed" role="alert">
            <p>
              {failed.status === 404 || failed.status === 403
                ? "This RBD isn't there any more: it was deleted, or isn't yours to open. Unlink it from the position, or link another."
                : `Something stopped the diagram loading: ${failed.message || "an unknown error"}. Try again in a moment.`}
            </p>
          </div>
        ) : (
          <Suspense fallback={<p className="rim-tquiet rbd-pane-wait">Opening the diagram…</p>}>
            <RbdEditor rbdId={rbdId} embedded onDirty={onDirty} onSaved={onSaved} onLoadError={setFailed}
                       pane={phone ? null : { onClose, closeLabel: "Close the RBD", fullPath: path, onOpenFull }} />
          </Suspense>
        )}
      </div>
    </TablePane>
  );
}

// The address's RBD for a diagram not built yet (?rbd=new&on=<position>): NewRbdPane, asked first.
export const NEW_RBD = "new";

// Build from what's inside…: the new diagram's name, asked once in the table pane before anything is
// saved (it was saved as "<position> (from the tree)" with no name asked). One diagram is built; a
// part with no model of its own gets a diagram of its own from its parts, named after it and listed
// under this one on Systems › RBDs.
//   position {id, name}   kids [{id, name, model}]: the positions inside, each a block
//   onCreate(name) a promise (it says what went wrong itself)   onClose()
export function NewRbdPane({ position, kids = [], phone = false, headingRef = null, onCreate, onClose }) {
  const [name, setName] = useState(`${position.name} RBD`);
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const clean = name.trim().replace(/\s+/g, " ");
  const why = clean ? null : "Give the diagram a name.";
  const shown = kids.slice(0, 8).map((k) => k.name);
  const save = async (e) => {
    e?.preventDefault();
    setTried(true);
    if (why || busy) return;
    setBusy(true);
    try {
      await onCreate(clean);
    } finally {
      setBusy(false);
    }
  };
  return (
    <TablePane title="New RBD" subject={position.name} phone={phone} busy={busy} headingRef={headingRef} onClose={onClose}
               className="rbd-pane rbd-pane-new" closeLabel="Close without building">
      <form className="rbd-new" onSubmit={save}>
        <Field label="Name" error={tried ? why : null}
               help="Saved under this name on Systems › RBDs and on this position's Modelling tab.">
          <TextInput value={name} maxLength={200} autoFocus disabled={busy} onChange={(e) => setName(e.target.value)} />
        </Field>
        <p className="rbd-new-what">
          One block for each of the {kids.length} position{kids.length === 1 ? "" : "s"} inside {position.name}
          {shown.length ? `: ${shown.join(", ")}${kids.length > shown.length ? ", …" : ""}` : ""}. A part with no model
          of its own gets a diagram of its own, made from its parts, named after it and listed under this one; a
          block with nothing to go on is a placeholder, marked as one.
        </p>
        <div className="rbd-new-foot">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" disabled={busy} aria-busy={busy || undefined}>{busy ? "Building…" : "Build the RBD"}</button>
        </div>
      </form>
    </TablePane>
  );
}
