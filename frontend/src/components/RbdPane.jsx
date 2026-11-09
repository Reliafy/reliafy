import { Suspense, lazy, useState } from "react";
import { Link } from "react-router-dom";
import Chip from "./ui/Chip.jsx";
import TablePane from "./TablePane.jsx";
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
//   built     just built or rebuilt from what's inside ({name, rebuilt, kids, notes}): what it made,
//             shown over the builder until dismissed
//   onDirty(changed)   onSaved(id)   onOpenFull(event, path): may stop the link (unsaved changes)
//   phone, headingRef, onClose: TablePane's
export default function RbdPane({ rbdId, position, built = null, phone = false, headingRef = null, onClose, onDirty, onSaved, onOpenFull }) {
  const [note, setNote] = useState(built);
  const [failed, setFailed] = useState(null);
  const path = `/systems/b/${encodeURIComponent(rbdId)}`;
  return (
    <TablePane title="RBD" subject={position.name} phone={phone} headingRef={headingRef} onClose={onClose}
               className="rbd-pane" closeLabel="Close the RBD"
               actions={<Link to={path} className="rbd-pane-full" onClick={(e) => onOpenFull?.(e, path)}>Open full page</Link>}>
      <div className="rbd-pane-body">
        {note && <BuiltNote note={note} position={position} onDismiss={() => setNote(null)} />}
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
            <RbdEditor rbdId={rbdId} embedded onDirty={onDirty} onSaved={onSaved} onLoadError={setFailed} />
          </Suspense>
        )}
      </div>
    </TablePane>
  );
}

// What "Build from what's inside…" made: the positions inside, each with the model its block takes
// (or a flagged placeholder, never a made-up figure), and how it was wired.
function BuiltNote({ note, position, onDismiss }) {
  const kids = note.kids || [];
  const placeholders = kids.filter((k) => !k.model).length;
  return (
    <section className="rbd-pane-note" aria-label="What was built">
      <p className="ml-lead">
        <span>
          <strong>{note.rebuilt ? "Rebuilt" : "Built"} {note.name}</strong>
          {note.rebuilt
            ? <> : the positions inside {position.name} that weren’t blocks yet are added, in series before the output. Everything else stays as you left it.</>
            : <> from the {kids.length === 1 ? "position" : `${kids.length} positions`} inside {position.name}. It’s saved under Design › Systems and linked here; Save keeps your changes.</>}
          {placeholders > 0 && <> {placeholders === 1 ? "One block is a placeholder" : `${placeholders} blocks are placeholders`}: give {placeholders === 1 ? "its position" : "their positions"} a model to make the figures real.</>}
        </span>
        <button type="button" className="link sm" onClick={onDismiss}>Dismiss</button>
      </p>
      {(kids.length > 0 || note.notes?.length > 0) && (
        <details className="rbd-pane-how">
          <summary>What each block takes, and how they’re wired</summary>
          {kids.length > 0 && (
            <ul className="ml-used">
              {kids.map((k) => <li key={k.id}>{k.name}: {k.model || <Chip tone="warning">Placeholder</Chip>}</li>)}
            </ul>
          )}
          {note.notes?.length > 0 && (
            <ul className="ml-used">
              {note.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </details>
      )}
    </section>
  );
}
