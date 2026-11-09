import { Suspense, lazy, useState } from "react";
import { Link } from "react-router-dom";
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
//   built     just built or rebuilt from what's inside: no note any more (the builder's blocks show
//             their placeholders); kept so callers needn't change
//   onDirty(changed)   onSaved(id)   onOpenFull(event, path): may stop the link (unsaved changes)
//   phone, headingRef, onClose: TablePane's
export default function RbdPane({ rbdId, position, built = null, phone = false, headingRef = null, onClose, onDirty, onSaved, onOpenFull }) {
  const [failed, setFailed] = useState(null);
  const path = `/systems/b/${encodeURIComponent(rbdId)}`;
  return (
    <TablePane title="RBD" subject={position.name} phone={phone} headingRef={headingRef} onClose={onClose}
               className="rbd-pane" closeLabel="Close the RBD" bare
               actions={<Link to={path} className="rbd-pane-full" onClick={(e) => onOpenFull?.(e, path)}>Open full page</Link>}>
      <div className="rbd-pane-body">
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
