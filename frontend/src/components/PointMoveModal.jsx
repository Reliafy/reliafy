import { useEffect, useMemo, useState } from "react";
import { getMaintenanceTree, moveMeasurementPoint } from "../api.js";
import { pointMoveChoices } from "../measuringPoint.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import "../views/AssetExplorer.css";

// "Move…" for a measuring point (the Measurements tab's ⋯ menu and the
// point's own page): pick another position from the tree, searchable, and
// the point goes there with its readings. `onDone(result)` gets the moved
// point (with the server's note, if any).
export default function PointMoveModal({ point, onClose, onDone }) {
  const [positions, setPositions] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [to, setTo] = useState("");
  useEffect(() => {
    let live = true;
    getMaintenanceTree()
      .then((t) => live && setPositions(t.positions || []))
      .catch((e) => live && setError(e.message || "Couldn't load the tree."));
    return () => { live = false; };
  }, []);
  const here = point.position?.id || null;
  const { rows, more } = useMemo(() => pointMoveChoices(positions || [], query, here), [positions, query, here]);
  const picked = rows.find((r) => r.id === to) || (positions || []).find((p) => p.id === to);
  return (
    <FormModal title={`Move ${point.name}`} submitLabel="Move" pendingLabel="Moving…" onClose={onClose}
               canSubmit={!!to && to !== here}
               onSubmit={async () => onDone(await moveMeasurementPoint(point.id, to))}>
      <p className="lib-date">
        To another position, with its readings. Tasks that count it keep counting it; an open alarm work order goes with it.
      </p>
      <Field label="Find a position">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, tag or a position above it"
               aria-label="Find a position" autoFocus />
      </Field>
      {error && <div className="card error">{error}</div>}
      {positions === null && !error ? <p className="lib-date">Loading the tree…</p> : (
        <ul className="rcm-move-tree" role="listbox" aria-label="Positions">
          {rows.map((r) => (
            <li key={r.id} role="option" aria-selected={r.id === to} aria-disabled={r.here || undefined}
                tabIndex={0} title={r.here ? "It's on this position now" : undefined}
                className={"rcm-mt-row" + (r.here ? " no" : "") + (r.id === to ? " picked" : "")}
                style={{ paddingLeft: 4 + Math.min(query.trim() ? 0 : r.depth, 12) * 16 }}
                onClick={() => !r.here && setTo(r.id)}
                onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !r.here) { e.preventDefault(); setTo(r.id); } }}>
              <span className="rcm-mt-name">
                {query.trim() && r.path.length ? <span className="lib-date">{r.path.join(" › ")} › </span> : null}
                {r.name}{r.tag ? <span className="lib-date"> · {r.tag}</span> : null}
              </span>
              {r.here && <span className="rcm-mt-here">here now</span>}
            </li>
          ))}
        </ul>
      )}
      {positions && !rows.length && <p className="lib-date">{query.trim() ? "Nothing matches that." : "There are no positions yet."}</p>}
      {more && <p className="lib-date">Showing the first {rows.length}: type to narrow the list.</p>}
      <p className="rcm-move-say" role="status" aria-live="polite">
        {picked ? `${point.name} moves to ${picked.name}.` : "Pick the position it goes on."}
      </p>
    </FormModal>
  );
}
